"""Operacje na plikach: folder modów, listowanie, rozmiary, bezpieczne ścieżki."""
import os
import sys
from pathlib import Path


def resource_path(rel):
    """Ścieżka do pliku w projekcie lub wewnątrz .exe (PyInstaller rozpakowuje do _MEIPASS)."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, rel)


def find_mx_mods_folder():
    """Domyślny folder modów MX Bikes (także przy Dokumentach w OneDrive)."""
    home = Path.home()
    for docs in (home / "Documents", home / "OneDrive" / "Documents", home / "OneDrive" / "Dokumenty"):
        p = docs / "PiBoSo" / "MX Bikes" / "mods"
        if p.is_dir():
            return os.path.normpath(str(p))
    return None


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
