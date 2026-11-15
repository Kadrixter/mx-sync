"""Gracz MX Sync: moja biblioteka + silnik torrent + serwer API + wykrywanie innych graczy.

GUI rozmawia tylko z Node. Wszystko działa w wątkach; GUI co chwilę czyta stan.
"""
import json
import os
from collections import deque
import secrets
import threading
import time
import uuid

from core.api import ApiServer
from core.compare import holders
from core.discovery import Beacon
from core.engine import Engine
from core.library import Library, save_path_for, torrent_ih
from core.mods import safe_path, scan_one
from core.players import Players
from core.protocol import MAGIC, PROTO, parse_address
from utils import config
from utils.config import DATA_DIR
from utils.files import find_mx_mods_folder, resolve_mods_root
from utils.version import VERSION

RECONNECT = 5.0             # co ile s dołączamy nowych graczy do trwających pobierań
RESCAN = 120.0              # co ile s sprawdzamy, czy w folderze modów coś się zmieniło


def _node_id():
    p = DATA_DIR / "id"
    try:
        return p.read_text(encoding="ascii").strip()
    except OSError:
        pid = uuid.uuid4().hex
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        p.write_text(pid, encoding="ascii")
        return pid


class Node:
    def __init__(self):
        self.cfg = config.load()
        self.id = _node_id()
        self.nonce = secrets.token_hex(16)
        self.library = Library()
        self.engine = Engine(on_finished=self._finished)
        self.api = ApiServer(self)
        self.players = Players(self.id, lambda: self.password, lambda: self.name)
        self.beacon = Beacon(self.hello, self.players.found, self._manual_ips)
        self.events = []            # komunikaty dla GUI / zasobnika: (tytuł, tekst)
        self.recent = deque(maxlen=30)  # (godzina, nazwa) ostatnio pobranych modów
        self.on_show = lambda: None
        self._stop = threading.Event()
        self._scan_lock = threading.Lock()
        self._seeded = {}           # klucz modu -> infohash udostępnianej wersji
        self.engine.set_limits(self.cfg["max_up"], self.cfg["max_down"])

    # ---------- ustawienia ----------

    @property
    def name(self):
        return config.player_name(self.cfg)

    @property
    def password(self):
        return self.cfg.get("password") or ""

    @property
    def folder(self):
        f = self.cfg.get("folder") or find_mx_mods_folder() or ""
        return resolve_mods_root(f) if f else ""

    def set_options(self, **values):
        old_folder = self.folder
        self.cfg = config.update(**values)
        if "max_up" in values or "max_down" in values:
            self.engine.set_limits(self.cfg["max_up"], self.cfg["max_down"])
        if "password" in values:
            self.nonce = secrets.token_hex(16)      # stare dowody hasła przestają działać
        if self.folder != old_folder:
            for ih in list(self.engine.seeds):
                self.engine.unseed(ih)
            self._seeded.clear()
            self.library.mods.clear()
            self.library.rev += 1
            self.rescan()

    def add_player(self, text):
        ip, port = parse_address(text)
        peers = [p for p in self.cfg["manual_peers"] if p != f"{ip}:{port}"] + [f"{ip}:{port}"]
        self.cfg = config.update(manual_peers=peers)
        self.players.add_manual(ip, port)
        self.beacon.poke()

    def _manual_ips(self):
        return [p.split(":")[0] for p in self.cfg["manual_peers"]]

    # ---------- start / stop ----------

    def start(self):
        self.api.start()
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            (DATA_DIR / "instance.json").write_text(json.dumps({"port": self.api.port, "pid": os.getpid()}))
        except OSError:
            pass
        self.beacon.start()
        self.players.start()
        for entry in self.cfg["manual_peers"]:
            ip, port = parse_address(entry)
            self.players.add_manual(ip, port)
        self.rescan()
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self._stop.set()
        self.library.stop()
        self.beacon.stop()
        self.players.stop()
        self.api.stop()
        self.engine.close()

    def _loop(self):
        last_connect = last_scan = time.monotonic()
        while not self._stop.is_set():
            try:
                self.engine.poll()
            except RuntimeError:
                pass
            now = time.monotonic()
            if now - last_connect > RECONNECT:
                last_connect = now
                peers = self._peers()
                for t in self.engine.active():
                    if not t.done:
                        self.engine.connect(t.ih, peers)
            if now - last_scan > RESCAN and not self.library.scanning:
                last_scan = now
                self.rescan()
            self._stop.wait(0.5)

    # ---------- biblioteka ----------

    def rescan(self):
        def run():
            with self._scan_lock:
                busy = {t.key for t in self.engine.active() if not t.done}
                self.library.scan(self.folder, self._seed, skip=busy)
                if not self._stop.is_set():
                    mods = self.library.snapshot()
                    for key, ih in list(self._seeded.items()):
                        if key not in mods and key not in busy:   # mod usunięty z dysku
                            self.engine.unseed(ih)
                            self._seeded.pop(key, None)
        threading.Thread(target=run, daemon=True).start()

    def _seed(self, mod, path):
        raw = self.library.torrent_bytes(mod.ih)
        if raw:
            old = self._seeded.get(mod.key)
            if old and old != mod.ih:
                self.engine.unseed(old)             # mod się zmienił – stara wersja przestaje być dzielona
            self.engine.seed(mod.ih, raw, save_path_for(path, raw))
            self._seeded[mod.key] = mod.ih

    def hello(self):
        mods = self.library.snapshot()
        return {"magic": MAGIC, "proto": PROTO, "id": self.id, "name": self.name, "version": VERSION,
                "http": self.api.port, "port": self.api.port, "lt": self.engine.port,
                "rev": self.library.rev, "mods": len(mods), "size": sum(m.size for m in mods.values()),
                "protected": bool(self.password), "nonce": self.nonce,
                "peers": self.players.known_addresses()}

    def library_wire(self):
        return {"rev": self.library.rev, "mods": {k: m.to_wire() for k, m in self.library.snapshot().items()}}

    def torrent_bytes(self, ih):
        mine = any(m.ih == ih for m in self.library.snapshot().values())
        return self.library.torrent_bytes(ih) if mine or ih in self.engine.transfers else None

    # ---------- pobieranie ----------

    def _peers(self):
        return [(p.ip, p.lt) for p in self.players.online() if p.lt]

    def download(self, mods):
        """Pobiera listę modów (Mod z biblioteki innego gracza) – od wszystkich, którzy je mają."""
        threading.Thread(target=self._download, args=(list(mods),), daemon=True).start()

    def _download(self, mods):
        online = self.players.online()
        for mod in mods:
            if mod.ih in self.engine.transfers:
                continue
            try:
                raw = self.library.torrent_bytes(mod.ih) or self._fetch_torrent(mod, online)
                path = safe_path(self.folder, mod.key)
            except (OSError, ValueError) as e:
                self.events.append(("Nie udało się pobrać", f"{mod.name}: {e}"))
                continue
            save = save_path_for(path, raw)
            os.makedirs(save, exist_ok=True)
            mine = self.library.mods.get(mod.key)
            if mine is not None:
                self.engine.unseed(mine.ih)         # moja stara wersja – pliki zaraz się zmienią
                self._seeded.pop(mod.key, None)
            self.engine.download(mod, raw, save, self._peers(), replace=mine is not None)

    def _fetch_torrent(self, mod, online):
        for p in holders(mod.ih, online):
            try:
                raw = self.players.fetch_torrent(p, mod.ih)
            except Exception:       # noqa: BLE001 – spróbuj u następnego gracza
                continue
            if torrent_ih(raw) == mod.ih:           # nie ufamy ślepo – sprawdzamy, że to ten mod
                self.library.store_torrent(raw)
                return raw
        raise OSError("nikt online nie ma tego modu")

    def cancel(self, ih):
        t = self.engine.transfers.get(ih)
        self.engine.cancel(ih)
        if t and t.replace:
            self.rescan()               # pliki mogły się częściowo zmienić – policz od nowa

    def _finished(self, t):
        self.engine.forget(t.ih)
        self._seeded[t.key] = t.ih
        threading.Thread(target=self._settle, args=(t,), daemon=True).start()

    def _settle(self, t):
        """libtorrent zgłasza koniec, zanim dysk zapisze ostatnie dane – czekamy na pełne pliki,
        dopiero wtedy mod trafia do biblioteki (inaczej odcisk plików byłby zły)."""
        try:
            t.handle.flush_cache()
        except (AttributeError, RuntimeError):
            pass
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline and not self._stop.is_set():
            if t.replace:
                _remove_extra_files(self.folder, t)
            try:
                if scan_one(self.folder, t.key).size >= t.size:
                    break
            except (OSError, ValueError):
                pass
            time.sleep(0.5)
        self.library.add_downloaded(t.key, t.ih)
        self.recent.append((time.strftime("%H:%M"), t.name))
        self.events.append(("Pobrano mod", t.name))


def _remove_extra_files(root, t):
    """Po podmianie wersji: usuń pliki starej wersji, których nie ma w nowej."""
    try:
        path = safe_path(root, t.key)
        if not os.path.isdir(path):
            return
        fs = t.handle.torrent_file().files()
        save = t.handle.status().save_path
        keep = {os.path.normcase(os.path.join(save, fs.file_path(i))) for i in range(fs.num_files())}
        for d, _, files in os.walk(path):
            for f in files:
                p = os.path.join(d, f)
                if os.path.normcase(p) not in keep:
                    os.remove(p)
    except (OSError, ValueError, RuntimeError):
        pass
