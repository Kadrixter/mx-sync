"""Aktualizacja z GitHub Releases.

check()    – pyta API GitHuba o najnowsze wydanie i porównuje wersję,
download() – pobiera nowy MXSync.exe obok obecnego (MXSync.new.exe),
install()  – uruchamia ukryty skrypt, który po zamknięciu aplikacji podmienia
             plik .exe i uruchamia nową wersję.
"""
import os
import re
import subprocess
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
        for a in data.get("assets", []):
            if a.get("name", "").lower().endswith(".exe"):
                self.asset_url = a.get("browser_download_url")
                self.asset_size = int(a.get("size", 0))
                break
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


def _target_dir():
    d = os.path.dirname(os.path.abspath(sys.executable))
    return d if os.access(d, os.W_OK) else tempfile.gettempdir()


def download(info, progress=None, stop=None):
    """Pobiera nowy .exe; zwraca jego ścieżkę. progress(done, total)."""
    if not info.asset_url:
        raise UpdateError("Wydanie nie zawiera pliku .exe")
    dest = os.path.join(_target_dir(), "MXSync.new.exe")
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


def install(new_exe):
    """Uruchamia skrypt podmieniający .exe. Po wywołaniu aplikację trzeba zamknąć."""
    exe = os.path.abspath(sys.executable)
    script = os.path.join(tempfile.gettempdir(), "mxsync_update.bat")
    # ping zamiast timeout – timeout nie działa bez konsoli
    text = f"""@echo off
set n=0
:retry
ping -n 2 127.0.0.1 >nul
move /y "{new_exe}" "{exe}" >nul 2>&1 && goto ok
set /a n+=1
if %n% lss 30 goto retry
start "" "{new_exe}"
goto end
:ok
start "" "{exe}"
:end
(goto) 2>nul & del "%~f0"
"""
    with open(script, "w", encoding="oem" if sys.platform == "win32" else "utf-8") as f:
        f.write(text)
    # nowa wersja nie może dziedziczyć katalogu tymczasowego tej instancji PyInstallera
    env = {k: v for k, v in os.environ.items() if not k.startswith(("_MEIPASS", "_PYI"))}
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    # bez DETACHED_PROCESS – wtedy ping/move otwierałyby własne okna konsoli
    flags = 0x08000000 | 0x00000200  # CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(["cmd", "/c", script], env=env, creationflags=flags, close_fds=True,
                     cwd=os.path.dirname(exe))
