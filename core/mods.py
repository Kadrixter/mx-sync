"""Co jest „modem” w folderze mods MX Bikes i jakiego jest rodzaju.

Mod = pierwszy element ścieżki, który nie jest folderem-kategorią:
  'tracks/motocross/Foo.pkz'          -> mod 'tracks/motocross/Foo.pkz' (plik)
  'tracks/motocross/Foo/terrain/a.hrc' -> mod 'tracks/motocross/Foo'   (folder)
scan_mods() przechodzi cały folder mods i grupuje pliki w mody.
"""
import hashlib
import os

CATEGORY_DIRS = {
    "mods", "tracks", "bikes", "rider", "riders", "tyres", "misc", "motocross", "supercross",
    "enduro", "supermoto", "arenacross", "freestyle", "paints", "helmets", "boots", "gloves",
    "goggles", "protections", "neckbraces", "bodies", "models", "sounds", "skins", "gear",
}
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
# grupy (kolejność wyświetlania) i ich znaczki ASCII
KIND_GROUPS = [("Mapa", "Mapy"), ("Motor", "Motory"), ("Opony", "Opony"), ("Kask", "Kaski"),
               ("Strój", "Stroje"), ("Rider", "Ridery"), ("Inne", "Inne")]
KIND_ORDER = {k: i for i, (k, _) in enumerate(KIND_GROUPS)}
KIND_PLURAL = dict(KIND_GROUPS)
SKIP_SUFFIXES = (".part", ".parts", ".!qb", ".tmp")


def norm_rel(rel):
    """Ścieżka względem folderu mods, zawsze z '/'."""
    return "/".join(p for p in rel.replace("\\", "/").split("/") if p and p != ".")


def mod_key(rel):
    parts = [p for p in norm_rel(rel).split("/") if p]
    for i, p in enumerate(parts):
        if p.lower() not in CATEGORY_DIRS or i == len(parts) - 1:
            return "/".join(parts[:i + 1])
    return "/".join(parts)


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
    """Folder kategorii, w którym leży mod ('tracks/motocross')."""
    return key.rsplit("/", 1)[0] if "/" in key else ""


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


def scan_mods(root, stop=None):
    """{klucz modu: LocalMod} dla całego folderu mods (bez plików tymczasowych)."""
    mods = {}
    stack = [(root, "")]
    while stack:
        if stop is not None and stop.is_set():
            break
        path, rel = stack.pop()
        try:
            entries = list(os.scandir(path))
        except OSError:
            continue
        for e in entries:
            r = f"{rel}/{e.name}" if rel else e.name
            try:
                if e.is_symlink():
                    continue
                if e.is_dir():
                    stack.append((e.path, r))
                    continue
                if not e.is_file() or e.name.lower().endswith(SKIP_SUFFIXES):
                    continue
                st = e.stat()
            except OSError:
                continue
            key = mod_key(r)
            m = mods.get(key)
            if m is None:
                m = mods[key] = LocalMod(key)
            m.is_dir = m.is_dir or key != r
            m.files.append((r, st.st_size, st.st_mtime_ns))
            m.size += st.st_size
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
    stack = [(path, key)]
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
                elif e.is_file() and not e.name.lower().endswith(SKIP_SUFFIXES):
                    st = e.stat()
                    m.files.append((r, st.st_size, st.st_mtime_ns))
                    m.size += st.st_size
            except OSError:
                pass
    return m
