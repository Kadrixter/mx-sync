"""Biblioteka modów gracza: skan folderu mods + torrent (BitTorrent v2) dla każdego modu.

Każdy mod dostaje własny prywatny torrent v2. Ten sam mod (identyczne pliki i nazwa) u dwóch
graczy ma ten sam identyfikator (infohash) – po nim porównujemy biblioteki i łączymy pobierających.
Liczenie SHA-256 trwa, więc torrenty są zapisywane w cache (~/.mxsync/torrents) razem z odciskiem
metadanych plików (rozmiar + mtime). Kolejny start bierze je z cache w sekundy.
"""
import json
import os
import threading

import libtorrent as lt

from core.mods import mod_kind, mod_name, safe_path, scan_mods, scan_one
from utils.config import DATA_DIR

TORRENTS = DATA_DIR / "torrents"
INDEX = DATA_DIR / "library.json"


class Mod:
    """Mod w bibliotece (mój albo innego gracza)."""
    __slots__ = ("key", "ih", "size", "files", "kind", "name")

    def __init__(self, key, ih, size, files):
        self.key, self.ih, self.size, self.files = key, ih, int(size), int(files)
        self.kind = mod_kind(key)
        self.name = mod_name(key)

    def to_wire(self):
        return [self.ih, self.size, self.files]

    @classmethod
    def from_wire(cls, key, v):
        return cls(key, str(v[0]), v[1], v[2])


def make_torrent(path, progress=None):
    """Tworzy prywatny torrent v2 dla pliku albo folderu; zwraca surowe bajty .torrent."""
    files = lt.list_files(path)
    t = lt.create_torrent(files, 0, lt.create_torrent.v2_only)
    t.set_priv(True)
    t.set_creator("MX Sync")
    total = max(1, t.num_pieces())
    lt.set_piece_hashes(t, os.path.dirname(path), lambda i: progress and progress((i + 1) / total))
    return lt.bencode(t.generate())


def torrent_ih(raw):
    return str(lt.torrent_info(lt.bdecode(raw)).info_hashes().v2)


def save_path_for(mod_path, raw):
    """Gdzie libtorrent ma trzymać pliki modu.

    Folder z jednym plikiem daje torrent jednoplikowy nazwany jak ten plik (bez nazwy folderu) –
    wtedy zapisujemy w samym folderze modu, w pozostałych przypadkach w folderze nadrzędnym.
    """
    name = lt.torrent_info(lt.bdecode(raw)).name()
    if name == os.path.basename(mod_path):
        return os.path.dirname(mod_path)
    return mod_path


class Library:
    """Stan mojej biblioteki; scan() działa w wątku, GUI czyta pola postępu."""

    def __init__(self):
        self.root = None
        self.mods = {}              # klucz -> Mod
        self.rev = 0                # rośnie przy każdej zmianie (inni gracze wiedzą, że trzeba pobrać)
        self.scanning = False
        self.progress = (0, 0)      # (gotowe mody, wszystkie)
        self.current = ""           # mod liczony w tej chwili
        self.current_pct = 0.0
        self.error = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._cache = self._load_cache()
        TORRENTS.mkdir(parents=True, exist_ok=True)

    # ---------- cache ----------

    @staticmethod
    def _load_cache():
        try:
            data = json.loads(INDEX.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_cache(self):
        try:
            tmp = INDEX.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._cache), encoding="utf-8")
            os.replace(tmp, INDEX)
        except OSError:
            pass

    def torrent_bytes(self, ih):
        try:
            return (TORRENTS / f"{ih}.torrent").read_bytes()
        except OSError:
            return None

    def store_torrent(self, raw):
        ih = torrent_ih(raw)
        p = TORRENTS / f"{ih}.torrent"
        if not p.exists():
            p.write_bytes(raw)
        return ih

    # ---------- skan ----------

    def stop(self):
        self._stop.set()

    def snapshot(self):
        with self._lock:
            return dict(self.mods)

    def scan(self, root, on_mod=None, skip=()):
        """Skanuje folder; on_mod(Mod, path) dla każdego gotowego modu (np. od razu udostępnij).
        skip – mody właśnie pobierane (pliki są niekompletne – nie liczymy ich ani nie usuwamy)."""
        self.root, self.error, self.scanning = root, None, True
        self._stop.clear()
        try:
            local = scan_mods(root, self._stop) if root and os.path.isdir(root) else {}
            if root and not os.path.isdir(root):
                self.error = "Nie znaleziono folderu modów – ustaw go w Ustawieniach"
            # najpierw mody z cache (szybko), potem te do policzenia
            order = sorted(local.values(), key=lambda m: self._cache.get(m.key, {}).get("sig") != m.signature())
            self.progress = (0, len(order))
            found = {}
            for n, lm in enumerate(order):
                if self._stop.is_set():
                    break
                if lm.key in skip:
                    found[lm.key] = self.mods.get(lm.key)
                    continue
                mod = self._mod_for(lm)
                if mod:
                    found[mod.key] = mod
                    with self._lock:
                        if self.mods.get(mod.key) is None or self.mods[mod.key].ih != mod.ih:
                            self.mods[mod.key] = mod
                            self.rev += 1
                    if on_mod:
                        on_mod(mod, safe_path(root, mod.key))
                self.progress = (n + 1, len(order))
            if not self._stop.is_set():
                with self._lock:
                    gone = [k for k in self.mods if k not in found and k not in skip]
                    for k in gone:
                        del self.mods[k]
                    if gone:
                        self.rev += 1
                self._cache = {k: v for k, v in self._cache.items() if k in found or k in skip}
            self._save_cache()
        finally:
            self.current = ""
            self.scanning = False

    def _mod_for(self, lm):
        sig = lm.signature()
        c = self._cache.get(lm.key)
        if c and c.get("sig") == sig and (TORRENTS / f"{c['ih']}.torrent").exists():
            return Mod(lm.key, c["ih"], lm.size, len(lm.files))
        self.current, self.current_pct = mod_name(lm.key), 0.0
        try:
            raw = make_torrent(safe_path(self.root, lm.key), lambda p: setattr(self, "current_pct", p))
        except (RuntimeError, OSError, ValueError):
            return None                 # plik zablokowany / zniknął w trakcie – pominięty
        ih = self.store_torrent(raw)
        self._cache[lm.key] = {"sig": sig, "ih": ih}
        if len(self._cache) % 20 == 0:
            self._save_cache()
        return Mod(lm.key, ih, lm.size, len(lm.files))

    # ---------- zmiany po pobraniu ----------

    def add_downloaded(self, key, ih):
        """Mod pobrany od innych – od razu w bibliotece (z odciskiem, żeby nie liczyć go znowu)."""
        try:
            local = scan_one(self.root, key)
        except (OSError, ValueError):
            return
        self._cache[key] = {"sig": local.signature(), "ih": ih}
        self._save_cache()
        with self._lock:
            self.mods[key] = Mod(key, ih, local.size, len(local.files))
            self.rev += 1

    def remove(self, key):
        with self._lock:
            if self.mods.pop(key, None):
                self.rev += 1
