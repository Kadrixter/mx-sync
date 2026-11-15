"""Aktualizacja z GitHub Releases – przez instalator (MXSync-Setup-X.Y.Z.exe).

check()    – pyta API GitHuba o najnowsze wydanie i porównuje wersję,
download() – pobiera instalator do katalogu tymczasowego,
install()  – uruchamia instalator w trybie cichym (/SILENT – widać tylko pasek postępu);
             instalator zamyka aplikację, instaluje nową wersję i uruchamia ją ponownie.
"""
import ctypes
import os
import re
import sys
import tempfile

import requests

from utils.version import REPO, VERSION

API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"


class UpdateError(Exception):
    pass


def parse_version(text):
    nums = [int(n) for n in re.findall(r"\d+", text or "")[:3]]
    return tuple(nums + [0] * (3 - len(nums)))


def is_frozen():
    """True, gdy działa jako .exe z PyInstallera (można podmienić plik)."""
    return bool(getattr(sys, "frozen", False))


class UpdateInfo:
    def __init__(self, data):
        self.tag = data.get("tag_name", "")
        self.version = self.tag.lstrip("vV")
        self.name = data.get("name") or self.tag
        self.notes = (data.get("body") or "").strip()
        self.page = data.get("html_url") or RELEASES_PAGE
        self.asset_url, self.asset_size = None, 0
        exes = [a for a in data.get("assets", []) if a.get("name", "").lower().endswith(".exe")]
        exes.sort(key=lambda a: "setup" not in a.get("name", "").lower())   # instalator najpierw
        if exes:
            self.asset_url = exes[0].get("browser_download_url")
            self.asset_size = int(exes[0].get("size", 0))
        self.newer = parse_version(self.tag) > parse_version(VERSION)


def check(timeout=8):
    try:
        r = requests.get(API_LATEST, timeout=timeout,
                         headers={"Accept": "application/vnd.github+json",
                                  "User-Agent": f"MXSync/{VERSION}"})
    except requests.RequestException as e:
        raise UpdateError(f"Brak połączenia z GitHubem: {e.__class__.__name__}")
    if r.status_code == 404:
        raise UpdateError("Na GitHubie nie ma jeszcze żadnego wydania")
    if r.status_code == 403:
        raise UpdateError("GitHub chwilowo ogranicza zapytania – spróbuj za kilka minut")
    if r.status_code != 200:
        raise UpdateError(f"GitHub odpowiedział HTTP {r.status_code}")
    return UpdateInfo(r.json())


def download(info, progress=None, stop=None):
    """Pobiera instalator; zwraca jego ścieżkę. progress(done, total)."""
    if not info.asset_url:
        raise UpdateError("Wydanie nie zawiera instalatora")
    dest = os.path.join(tempfile.gettempdir(), f"MXSync-Setup-{info.version or 'nowa'}.exe")
    part = dest + ".part"
    try:
        with requests.get(info.asset_url, stream=True, timeout=(10, 30),
                          headers={"User-Agent": f"MXSync/{VERSION}"}) as r:
            if r.status_code != 200:
                raise UpdateError(f"Pobieranie nie powiodło się (HTTP {r.status_code})")
            total = int(r.headers.get("Content-Length") or info.asset_size or 0)
            done = 0
            with open(part, "wb") as f:
                for chunk in r.iter_content(256 * 1024):
                    if stop is not None and stop.is_set():
                        raise UpdateError("Anulowano")
                    f.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total)
        if total and done != total:
            raise UpdateError("Pobrany plik jest niekompletny")
        os.replace(part, dest)
    except requests.RequestException as e:
        raise UpdateError(f"Błąd pobierania: {e.__class__.__name__}")
    except OSError as e:
        raise UpdateError(f"Nie można zapisać pliku: {e}")
    finally:
        if os.path.exists(part):
            try:
                os.remove(part)
            except OSError:
                pass
    return dest


def install(setup_exe):
    """Uruchamia instalator po cichu. Po wywołaniu aplikację trzeba zamknąć.

    ShellExecute zamiast subprocess – instalator wymaga uprawnień administratora (zapora),
    więc Windows musi móc pokazać okno UAC.
    """
    # nowa wersja (uruchomiona przez instalator) nie może dziedziczyć zmiennych PyInstallera
    for k in [k for k in os.environ if k.startswith(("_MEIPASS", "_PYI"))]:
        del os.environ[k]
    os.environ["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    args = "/SILENT /SP- /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS"
    rc = ctypes.windll.shell32.ShellExecuteW(None, "open", setup_exe, args, None, 1)
    if rc <= 32:
        raise OSError("Instalacja anulowana" if rc == 5 else f"ShellExecute zwrócił {rc}")
