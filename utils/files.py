"""Operacje na plikach: folder modów, listowanie, rozmiary, bezpieczne ścieżki."""
import os
import sys
from pathlib import Path


def resource_path(rel):
    """Ścieżka do pliku w projekcie lub wewnątrz .exe (PyInstaller rozpakowuje do _MEIPASS)."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, rel)


MODS_DIR = "mods"


def _documents_dirs():
    """Folder Dokumenty z Windows (działa też, gdy jest przeniesiony na inny dysk / do OneDrive)."""
    out = []
    if sys.platform == "win32":
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(260)
            # CSIDL_PERSONAL = 5 (Moje dokumenty), SHGFP_TYPE_CURRENT = 0
            if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0 and buf.value:
                out.append(Path(buf.value))
        except (OSError, AttributeError):
            pass
    home = Path.home()
    out += [home / "Documents", home / "Dokumenty", home / "OneDrive" / "Documents",
            home / "OneDrive" / "Dokumenty"]
    return out


def find_mx_mods_folder():
    """Domyślny folder modów MX Bikes: Dokumenty\\PiBoSo\\MX Bikes\\mods."""
    for docs in _documents_dirs():
        p = docs / "PiBoSo" / "MX Bikes" / MODS_DIR
        if p.is_dir():
            return os.path.normpath(str(p))
    return None


def resolve_mods_root(path):
    """Z dowolnie wybranego folderu wyznacza właściwy folder `mods` MX Bikes.

    'MX Bikes' -> 'MX Bikes\\mods', 'mods\\tracks\\motocross' -> 'mods', 'mods' -> 'mods'.
    Folder spoza struktury MX Bikes zostaje bez zmian.
    """
    if not path:
        return path
    p = os.path.normpath(os.path.abspath(path))
    parts = Path(p).parts
    # wybrany folder leży w mods (albo nim jest); najpierw '...\MX Bikes\mods', potem pierwszy 'mods'
    hits = [i for i in range(1, len(parts)) if parts[i].lower() == MODS_DIR]
    if hits:
        game = [i for i in hits if parts[i - 1].lower() == "mx bikes"]
        i = game[-1] if game else hits[0]
        return os.path.normpath(str(Path(*parts[:i + 1])))
    # wybrano folder gry (MX Bikes) – mods jest w środku
    sub = os.path.join(p, MODS_DIR)
    if os.path.isdir(sub):
        return sub
    return p


def mods_rel(rel):
    """Ścieżka względna względem folderu mods, zawsze z '/' (bez wiodącego 'mods/').

    Stary host v2 wysyła ścieżki z '\\', a host wskazujący folder 'MX Bikes' –
    z przedrostkiem 'mods/'; po normalizacji obie trafiają w to samo miejsce.
    """
    parts = [x for x in rel.replace("\\", "/").split("/") if x and x != "."]
    while len(parts) > 1 and parts[0].lower() == MODS_DIR:
        parts.pop(0)
    return "/".join(parts)


def entry_name(path):
    """Nazwa elementu; dla katalogu głównego dysku (np. D:\\) zwraca 'D'."""
    name = os.path.basename(os.path.normpath(path))
    return name or path.replace(":", "").strip("\\/") or "dysk"


def dir_size(path):
    total = 0
    stack = [path]
    while stack:
        p = stack.pop()
        try:
            with os.scandir(p) as it:
                for e in it:
                    try:
                        if e.is_symlink():
                            continue
                        if e.is_dir():
                            stack.append(e.path)
                        elif e.is_file():
                            total += e.stat().st_size
                    except OSError:
                        pass
        except OSError:
            pass
    return total


def entry_size(path):
    try:
        return dir_size(path) if os.path.isdir(path) else os.path.getsize(path)
    except OSError:
        return 0


def list_folder(folder):
    """Zwraca [(ścieżka, nazwa, is_dir)] – najpierw foldery, potem pliki."""
    out = []
    try:
        with os.scandir(folder) as it:
            for e in it:
                try:
                    out.append((os.path.normpath(e.path), e.name, e.is_dir()))
                except OSError:
                    pass
    except OSError:
        pass
    out.sort(key=lambda x: (not x[2], x[1].lower()))
    return out


def walk_files(folder, name):
    """Pliki elementu `name` z folderu modów: [(rel, ścieżka, stat)], rel z '/'."""
    root = os.path.join(folder, name)
    if not os.path.isdir(root):
        try:
            return [(name, root, os.stat(root))]
        except OSError:
            return []
    out = []
    stack = [(root, name)]
    while stack:
        p, rel = stack.pop()
        try:
            entries = list(os.scandir(p))
        except OSError:
            continue
        for e in entries:
            r = f"{rel}/{e.name}"
            try:
                if e.is_symlink():
                    continue
                if e.is_dir():
                    stack.append((e.path, r))
                elif e.is_file() and not e.name.endswith(".part"):
                    out.append((r, e.path, e.stat()))
            except OSError:
                pass
    out.sort(key=lambda f: f[0].lower())
    return out


def safe_join(base, rel):
    """Łączy folder ze ścieżką względną i odrzuca próby wyjścia poza folder."""
    b = os.path.abspath(base)
    p = os.path.abspath(os.path.join(b, rel))
    if not rel or os.path.isabs(rel) or os.path.commonpath([b, p]) != b or p == b:
        raise ValueError(f"Niedozwolona ścieżka: {rel}")
    return p
