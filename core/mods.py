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
    "animations", "fonts", "helmetcams", "dashes", "stands", "pitboard",
}
PACKAGE_EXT = (".pkz", ".pkg", ".zip")
# rodzaj modu z najgłębszego folderu-kategorii w ścieżce ('rider/helmets/X' -> Kask)
# rodzaje modów (kolejność = kolejność sekcji na liście) i ich nazwy w liczbie mnogiej
KIND_GROUPS = [("Mapa", "Mapy"), ("Motor", "Motory"), ("Malowanie", "Malowania"), ("Opony", "Opony"),
               ("Kask", "Kaski"), ("Gogle", "Gogle"), ("Strój", "Stroje"), ("Rękawice", "Rękawice"),
               ("Buty", "Buty"), ("Ochraniacze", "Ochraniacze"), ("Postać", "Modele postaci"),
               ("Animacje", "Animacje"), ("Kamerka", "Kamerki"), ("Font", "Fonty"), ("Inne", "Inne")]
KIND_ORDER = {k: i for i, (k, _) in enumerate(KIND_GROUPS)}
KIND_PLURAL = dict(KIND_GROUPS)
# wszystko z folderu rider/ – w filtrach zbiorczo jako „Postacie”
CHARACTER_KINDS = ("Kask", "Gogle", "Strój", "Rękawice", "Buty", "Ochraniacze", "Postać", "Animacje",
                   "Kamerka", "Font")
CHARACTERS = "@postacie"
# filtr rodzaju na listach: (zakres, etykieta); zakres = rodzaj albo CHARACTERS
FILTERS = [("", "Wszystko"), ("Mapa", "Mapy"), ("Motor", "Motory"), ("Malowanie", "Malowania"),
           ("Opony", "Opony"), (CHARACTERS, "Postacie"), ("Inne", "Inne")]
# podfoldery rider/ -> rodzaj
RIDER_DIRS = {"animations": "Animacje", "boots": "Buty", "fonts": "Font", "helmetcams": "Kamerka",
              "helmets": "Kask", "paints": "Strój", "protections": "Ochraniacze", "neckbraces": "Ochraniacze",
              "riders": "Postać", "gloves": "Rękawice", "goggles": "Gogle"}
# podfoldery z dodatkami do modu (malowania, rękawice, gogle) – każdy plik to osobny mod, także wewnątrz
# rozpakowanego modu (np. 'rider/riders/neuro/paints/red.pnt' nie jest częścią modelu 'neuro')
PART_DIRS = {"paints", "gloves", "goggles"}
# napis pod nazwą dodatku: do czego jest
PART_LABEL = {"Malowanie": "do motoru", "Kask": "malowanie kasku", "Gogle": "do kasku", "Strój": "do postaci",
              "Rękawice": "do postaci", "Buty": "malowanie butów", "Ochraniacze": "malowanie ochraniaczy"}
_TRACK_DIRS = {"tracks", "motocross", "supercross", "enduro", "supermoto", "arenacross", "freestyle"}
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
    if first == "bikes":
        return "Malowanie" if "paints" in parts else "Motor"
    if first == "tyres":
        return "Opony"
    if first == "rider":
        if "gloves" in parts[1:]:
            return "Rękawice"
        if "goggles" in parts[1:]:
            return "Gogle"
        sub = parts[1] if len(parts) > 1 else ""
        if sub == "riders" and "paints" in parts[2:]:
            return "Strój"                  # malowanie modelu postaci = strój
        if sub in RIDER_DIRS:
            return RIDER_DIRS[sub]
        if not sub and key.lower().endswith(".pnt"):
            return "Strój"                  # stroje leżące wprost w rider/
        return "Inne"
    if first == "tracks" or (first not in ("misc",) and any(p in _TRACK_DIRS for p in parts)):
        return "Mapa"
    return "Inne"


def kind_in(kind, scope):
    """Czy rodzaj pasuje do filtra: '' – wszystko, CHARACTERS – wszystko z rider/, inaczej dokładnie."""
    if not scope:
        return True
    if scope == CHARACTERS:
        return kind in CHARACTER_KINDS
    return kind == scope


def part_owner(key):
    """Do czego jest dodatek: folder nad 'paints' / 'gloves' / 'goggles' ('bikes/sm1oemktm450f/paints/x.pnt')."""
    parts = key.split("/")
    for i in range(len(parts) - 2, 0, -1):
        if parts[i].lower() in PART_DIRS:
            owner = parts[i - 1]
            return None if owner.lower() in CATEGORY_DIRS else owner
    return None


def paint_bike(key):
    """Do jakiego motoru jest malowanie (dla malowań motorów)."""
    return part_owner(key) if mod_kind(key) == "Malowanie" else None


def mod_subtitle(key, kind):
    """Mały napis pod nazwą modu: przy dodatkach (malowania, rękawice, gogle) do czego są, przy reszcie folder."""
    owner = part_owner(key) if kind in PART_LABEL else None
    if owner:
        return f"{PART_LABEL[kind]}: {owner}"
    return mod_dir(key) or "mods"


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
    __slots__ = ("key", "files", "size", "is_dir", "hidden")

    def __init__(self, key):
        self.key = key
        self.files = []
        self.size = 0
        self.is_dir = False
        self.hidden = False     # ma plik z atrybutem „ukryty” (stare wersje liczyły go do sumy modu)

    def signature(self):
        """Odcisk zawartości z metadanych – zmiana pliku = inny odcisk (bez czytania danych)."""
        h = hashlib.sha1()
        for rel, size, mtime in sorted(self.files):
            h.update(f"{rel}\0{size}\0{mtime}\n".encode("utf-8", "surrogatepass"))
        return h.hexdigest()


def _is_hidden(st):
    return bool(getattr(st, "st_file_attributes", 0) & 2)     # FILE_ATTRIBUTE_HIDDEN


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
    """Cały folder (rozpakowany mod) jako jeden mod – bez podfolderów z dodatkami (PART_DIRS),
    które są osobnymi modami. Zwraca listę pominiętych podfolderów [(ścieżka, klucz)]."""
    parts = []
    stack = [(path, rel, True)]
    while stack:
        p, r, top = stack.pop()
        files, dirs = _entries(p)
        for f in files:
            try:
                st = f.stat()
            except OSError:
                continue
            mod.files.append((f"{r}/{f.name}", st.st_size, st.st_mtime_ns))
            mod.size += st.st_size
            mod.hidden = mod.hidden or _is_hidden(st)
        for d in dirs:
            if top and d.name.lower() in PART_DIRS:
                parts.append((d.path, f"{r}/{d.name}"))
            else:
                stack.append((d.path, f"{r}/{d.name}", False))
    return parts


def belongs_to_mod(rel):
    """Czy plik 'rel' (względem folderu rozpakowanego modu) należy do modu – to samo co liczy skan:
    bez podfolderów z dodatkami (PART_DIRS) i bez plików tymczasowych."""
    parts = rel.replace("\\", "/").split("/")
    low = parts[-1].lower()
    if low.endswith(SKIP_SUFFIXES) or low in SKIP_NAMES:
        return False
    return not (len(parts) > 1 and parts[0].lower() in PART_DIRS)


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
            stack += _whole_dir(m, path, rel)      # malowania / rękawice / gogle – osobno, plik po pliku
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
            m.hidden = _is_hidden(st)
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
        m.hidden = _is_hidden(st)
        return m
    m.is_dir = True
    _whole_dir(m, path, key)
    return m
