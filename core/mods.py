"""Co jest „modem” w folderze mods MX Bikes, do jakiej grupy należy i jakiego jest rodzaju.

Zasady (od 2.1):
  * każdy plik paczki (.pkz) to osobny mod:      'tracks/motocross/Foo.pkz'
  * folder z paczkami to GRUPA (np. paczka map):  'tracks/motocross/Pack/a.pkz' -> grupa 'tracks/motocross/Pack'
  * folder z rozpakowanym modem (pliki .ini, .hrc, … bez paczek) to jeden mod: 'bikes/MojMotor'
Foldery-kategorie (tracks, motocross, bikes, rider, …) nie są ani modami, ani grupami.
"""
import hashlib
import os
import re

CATEGORY_DIRS = {
    "mods", "tracks", "bikes", "rider", "riders", "tyres", "misc", "motocross", "supercross",
    "enduro", "supermoto", "arenacross", "freestyle", "paints", "helmets", "boots", "gloves",
    "goggles", "protections", "neckbraces", "bodies", "models", "sounds", "skins", "gear",
}
PACKAGE_EXT = (".pkz", ".pkg", ".zip")
# rodzaj modu z najgłębszego folderu-kategorii w ścieżce ('rider/helmets/X' -> Kask)
CATEGORY_LABELS = {"tracks": "Mapa", "motocross": "Mapa", "supercross": "Mapa", "enduro": "Mapa",
                   "supermoto": "Mapa", "arenacross": "Mapa", "freestyle": "Mapa",
                   "bikes": "Motor", "paints": "Motor", "sounds": "Motor", "models": "Motor",
                   "tyres": "Opony",
                   "helmets": "Kask",
                   "boots": "Strój", "gloves": "Strój", "goggles": "Strój", "protections": "Strój",
                   "neckbraces": "Strój", "gear": "Strój", "skins": "Strój",
                   "rider": "Rider", "riders": "Rider", "bodies": "Rider",
                   "misc": "Inne"}
KIND_GROUPS = [("Mapa", "Mapy"), ("Motor", "Motory"), ("Opony", "Opony"), ("Kask", "Kaski"),
               ("Strój", "Stroje"), ("Rider", "Ridery"), ("Inne", "Inne")]
KIND_ORDER = {k: i for i, (k, _) in enumerate(KIND_GROUPS)}
KIND_PLURAL = dict(KIND_GROUPS)
SKIP_SUFFIXES = (".part", ".parts", ".!qb", ".tmp")
SKIP_NAMES = {"thumbs.db", "desktop.ini", ".ds_store"}
# kolejność skanowania (etapy z zapisem postępu): najmniejsze najpierw, tracks – zwykle największe – na końcu
SCAN_ORDER = ["rider", "tyres", "misc", "bikes"]
SCAN_LAST = "tracks"


def norm_rel(rel):
    """Ścieżka względem folderu mods, zawsze z '/'."""
    return "/".join(p for p in rel.replace("\\", "/").split("/") if p and p != ".")


def mod_kind(key):
    parts = [p.lower() for p in key.split("/")[:-1]]
    first = parts[0] if parts else ""
    for p in reversed(parts):
        kind = CATEGORY_LABELS.get(p)
        # 'tracks/enduro' to mapa, ale 'bikes/enduro' to motor
        if kind == "Mapa" and p != "tracks" and first != "tracks":
            continue
        if kind:
            return kind
    return "Inne"


def mod_name(key):
    return key.rsplit("/", 1)[-1]


def mod_dir(key):
    """Folder, w którym leży mod ('tracks/motocross')."""
    return key.rsplit("/", 1)[0] if "/" in key else ""


def mod_group(key):
    """Grupa modu = jego folder, jeśli to nie jest sam folder-kategoria; inaczej None."""
    d = mod_dir(key)
    if not d:
        return None
    return None if d.rsplit("/", 1)[-1].lower() in CATEGORY_DIRS else d


def group_parents(group):
    """Grupa i wszystkie grupy nadrzędne ('t/m/A/B' -> ['t/m/A/B', 't/m/A'])."""
    out = []
    g = group
    while g and g.rsplit("/", 1)[-1].lower() not in CATEGORY_DIRS:
        out.append(g)
        g = mod_dir(g)
    return out


def scan_stage(key):
    """Numer etapu skanowania dla modu: rider, tyres, misc, bikes, (inne), tracks."""
    top = key.split("/", 1)[0].lower()
    if top in SCAN_ORDER:
        return SCAN_ORDER.index(top)
    return len(SCAN_ORDER) + (1 if top == SCAN_LAST else 0)


STAGE_NAMES = SCAN_ORDER + ["inne", SCAN_LAST]


def search_text(*parts):
    """Tekst do wyszukiwania: małe litery + wersja bez znaków innych niż litery i cyfry."""
    raw = " ".join(p for p in parts if p).lower()
    return raw + " " + re.sub(r"[^0-9a-ząćęłńóśźż]+", "", raw)


def matches(text, query):
    """Każde słowo zapytania musi wystąpić (np. 'spa' i '1998' pasują do '0xspa1998.pkz')."""
    words = [re.sub(r"[^0-9a-ząćęłńóśźż]+", "", w) for w in query.lower().split()]
    return all(w in text for w in words if w)


def safe_path(root, key):
    """Ścieżka modu w folderze mods; odrzuca próby wyjścia poza folder."""
    base = os.path.abspath(root)
    p = os.path.abspath(os.path.join(base, *norm_rel(key).split("/")))
    if not key or os.path.commonpath([base, p]) != base or p == base:
        raise ValueError(f"Niedozwolona ścieżka: {key}")
    return p


class LocalMod:
    """Mod na dysku: lista plików (rel względem folderu mods, rozmiar, mtime)."""
    __slots__ = ("key", "files", "size", "is_dir")

    def __init__(self, key):
        self.key = key
        self.files = []
        self.size = 0
        self.is_dir = False

    def signature(self):
        """Odcisk zawartości z metadanych – zmiana pliku = inny odcisk (bez czytania danych)."""
        h = hashlib.sha1()
        for rel, size, mtime in sorted(self.files):
            h.update(f"{rel}\0{size}\0{mtime}\n".encode("utf-8", "surrogatepass"))
        return h.hexdigest()


def _entries(path):
    files, dirs = [], []
    try:
        for e in os.scandir(path):
            try:
                if e.is_symlink():
                    continue
                if e.is_dir():
                    dirs.append(e)
                elif e.is_file():
                    low = e.name.lower()
                    if not low.endswith(SKIP_SUFFIXES) and low not in SKIP_NAMES:
                        files.append(e)
            except OSError:
                pass
    except OSError:
        pass
    return files, dirs


def _whole_dir(mod, path, rel):
    """Cały folder (rozpakowany mod) jako jeden mod."""
    stack = [(path, rel)]
    while stack:
        p, r = stack.pop()
        files, dirs = _entries(p)
        for f in files:
            try:
                st = f.stat()
            except OSError:
                continue
            mod.files.append((f"{r}/{f.name}", st.st_size, st.st_mtime_ns))
            mod.size += st.st_size
        stack += [(d.path, f"{r}/{d.name}") for d in dirs]


def scan_mods(root, stop=None):
    """{klucz modu: LocalMod} dla całego folderu mods (bez plików tymczasowych)."""
    mods = {}
    stack = [(root, "")]
    while stack:
        if stop is not None and stop.is_set():
            break
        path, rel = stack.pop()
        files, dirs = _entries(path)
        name = rel.rsplit("/", 1)[-1].lower()
        is_category = rel == "" or name in CATEGORY_DIRS
        has_package = any(f.name.lower().endswith(PACKAGE_EXT) for f in files)
        if not is_category and files and not has_package:
            m = mods[rel] = LocalMod(rel)          # rozpakowany mod – cały folder
            m.is_dir = True
            _whole_dir(m, path, rel)
            continue
        for f in files:                            # kategoria albo grupa: każdy plik osobno
            try:
                st = f.stat()
            except OSError:
                continue
            key = f"{rel}/{f.name}" if rel else f.name
            m = mods[key] = LocalMod(key)
            m.files.append((key, st.st_size, st.st_mtime_ns))
            m.size = st.st_size
        stack += [(d.path, f"{rel}/{d.name}" if rel else d.name) for d in dirs]
    return mods


def scan_one(root, key):
    """LocalMod dla jednego modu (po pobraniu) – te same ścieżki co w scan_mods()."""
    path = safe_path(root, key)
    m = LocalMod(key)
    if os.path.isfile(path):
        st = os.stat(path)
        m.files.append((key, st.st_size, st.st_mtime_ns))
        m.size = st.st_size
        return m
    m.is_dir = True
    _whole_dir(m, path, key)
    return m
