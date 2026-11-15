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

from core.mods import STAGE_NAMES, belongs_to_mod, mod_kind, mod_name, safe_path, scan_mods, scan_one, scan_stage
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
    if os.path.isdir(path):
        # nazwy w torrencie zaczynają się od nazwy folderu modu: 'neuro\paints\x.pnt'
        files = [e for e in files if belongs_to_mod(e.filename.replace("\\", "/").split("/", 1)[-1])]
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
        self.stage = None           # (numer etapu, ile etapów, nazwa) w trakcie skanu
        self.to_hash = 0            # ile modów trzeba policzyć w tym skanie
        self.changed = []           # mody, których zawartość zmieniła się od poprzedniego skanu
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

    def scan(self, root, on_mod=None, skip=(), on_event=None, force=False):
        """Skanuje folder etapami (rider, tyres, misc, bikes, inne, tracks); po każdym etapie zapis
        postępu (checkpoint) – mody z gotowych etapów są już udostępniane, a przerwany skan
        zaczyna od miejsca, w którym skończył.

        on_mod(Mod, path) – mod gotowy (od razu udostępnij); on_event(tytuł, tekst) – komunikat.
        skip – mody właśnie pobierane (pliki niekompletne – nie liczymy ich ani nie usuwamy).
        force – licz od nowa, bez pamięci (sprawdzanie integralności): True – wszystko,
                funkcja(Mod lokalny -> bool) – tylko pasujące mody (np. jeden rodzaj)."""
        self.root, self.error, self.scanning = root, None, True
        self.changed = []
        self._stop.clear()
        event = on_event or (lambda *a: None)
        try:
            if not root or not os.path.isdir(root):
                self.error = "Nie znaleziono folderu modów – ustaw go w Ustawieniach"
                return
            local = scan_mods(root, self._stop)
            forced = (force if callable(force) else (lambda lm: True)) if force else (lambda lm: False)
            todo = [m for m in local.values() if forced(m) or self._cache.get(m.key, {}).get("sig") != m.signature()]
            self.to_hash = len(todo)
            first = not self._cache
            if force:
                event("Sprawdzam integralność", f"Liczę od nowa {len(todo)} modów – program może chwilę zwolnić")
            elif first and local:
                event("Pierwsze uruchomienie", f"Przygotowuję {len(local)} modów do udostępniania (rider, opony, "
                                               "misc, motory, mapy) – to potrwa, program może chwilę zwolnić")
            elif todo:
                event("Nowe albo zmienione mody", f"Liczę {len(todo)} – reszta ({len(local) - len(todo)}) "
                                                  "wczytana z pamięci; program może chwilę zwolnić")
            stages = {}
            for m in local.values():
                stages.setdefault(scan_stage(m.key), []).append(m)
            self.progress = (0, len(local))
            done, found = 0, {}
            for st in sorted(stages):
                self.stage = (sorted(stages).index(st) + 1, len(stages), STAGE_NAMES[st])
                for lm in sorted(stages[st], key=lambda m: m.key.lower()):
                    if self._stop.is_set():
                        break
                    done += 1
                    self.progress = (done, len(local))
                    if lm.key in skip:
                        found[lm.key] = self.mods.get(lm.key)
                        continue
                    mod = self._mod_for(lm, forced(lm))
                    if not mod:
                        continue
                    found[mod.key] = mod
                    with self._lock:
                        old = self.mods.get(mod.key)
                        if old is None or old.ih != mod.ih:
                            if old is not None:
                                self.changed.append(mod.key)
                            self.mods[mod.key] = mod
                            self.rev += 1
                    if on_mod:
                        on_mod(mod, safe_path(root, mod.key))
                self._save_cache()          # checkpoint po każdym etapie
            if not self._stop.is_set():
                with self._lock:
                    gone = [k for k in self.mods if k not in found and k not in skip]
                    for k in gone:
                        del self.mods[k]
                    if gone:
                        self.rev += 1
                self._cache = {k: v for k, v in self._cache.items() if k in found or k in skip}
                self._save_cache()
                if todo and not force:
                    event("Mody gotowe", f"Udostępniasz {len(found)} modów" +
                          (f" (nowe / zmienione: {len(todo)})" if not first else ""))
        finally:
            self.current = ""
            self.stage = None
            self.scanning = False

    def _mod_for(self, lm, force=False):
        sig = lm.signature()
        c = self._cache.get(lm.key)
        if not force and c and c.get("sig") == sig and (TORRENTS / f"{c['ih']}.torrent").exists():
            return Mod(lm.key, c["ih"], lm.size, len(lm.files))
        self.current, self.current_pct = mod_name(lm.key), 0.0
        try:
            raw = make_torrent(safe_path(self.root, lm.key), lambda p: setattr(self, "current_pct", p))
        except (RuntimeError, OSError, ValueError):
            return None                 # plik zablokowany / zniknął w trakcie – pominięty
        ih = self.store_torrent(raw)
        self._cache[lm.key] = {"sig": sig, "ih": ih}
        if len(self._cache) % 25 == 0:
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
