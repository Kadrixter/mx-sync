"""Klient: połączenie z hostem, sprawdzanie lokalnych modów i pobieranie.

Sprawdzanie: najpierw indeks hosta, potem MD5 liczone TYLKO dla plików o zgodnym
rozmiarze (brakujące / inny rozmiar od razu idą do pobrania), z cache hashy.
Pliki z indeksu są grupowane w mody (mapa, motor, kask…) – klient widzi, które mody
hosta ma aktualne, a których brakuje, i pobiera tylko wybrane.
Pobieranie (z hosta i innych klientów naraz) jest w net/swarm.py.
"""
import os
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

import requests
from requests.adapters import HTTPAdapter

from net.peer import PeerServer
from net.protocol import HDR_AUTH, HDR_CLIENT, HDR_PROTO, MAGIC, OLD_VERSION_MSG, PROTO, UPDATE_ME_MSG, make_proof
from utils.config import CLIENT_CACHE
from utils.files import mods_rel, resolve_mods_root, safe_join
from utils.hashing import Cancelled, HashCache, md5_file
from utils.speed import SpeedMeter

HASH_WORKERS = 4
HEARTBEAT = 3.0


class PasswordRequired(Exception):
    pass


class AuthError(Exception):
    pass


class HostConnection:
    """Sesja HTTP z hostem. Co kilka sekund zgłasza hostowi, co robi klient."""

    def __init__(self, ip, port, password=None):
        self.ip, self.port, self.password = ip, port, password
        self.base = f"http://{ip}:{port}"
        self.client_name = socket.gethostname()
        self.host_name = None
        self.protected = False
        self.nonce = ""
        self.state, self.total = "połączony", 0
        self.done_fn = None          # ile już pobrano (ustawia pobieranie) – host pokazuje postęp
        self.peer = None             # serwer P2P – udostępnia moje mody innym klientom
        self._closed = threading.Event()
        self.sess = requests.Session()
        self.sess.mount("http://", HTTPAdapter(pool_connections=16, pool_maxsize=16))
        try:
            self._hello()
        except BaseException:
            self.sess.close()
            raise
        self.peer = PeerServer(self.headers().get(HDR_AUTH))
        if not self.peer.start():
            self.peer = None
        threading.Thread(target=self._heartbeat, daemon=True).start()
        self._ping()

    def _hello(self):
        r = self.sess.get(self.base + "/hello", timeout=(5, 10))
        if r.status_code == 404:            # skrypt host v2 – bez /hello
            raise ValueError(OLD_VERSION_MSG)
        r.raise_for_status()
        info = r.json()
        magic = str(info.get("magic", ""))
        if magic != MAGIC:
            if magic.startswith("MXSYNC"):
                newer = magic[6:].isdigit() and int(magic[6:]) > PROTO
                raise ValueError(UPDATE_ME_MSG if newer else OLD_VERSION_MSG)
            raise ValueError("To nie jest host MX Sync")
        self.host_name = info.get("name")
        self.protected = bool(info.get("protected"))
        self.nonce = info.get("nonce", "")
        if self.protected:
            if self.password is None:
                raise PasswordRequired()
            if self.get("/status", timeout=(5, 10)).status_code == 401:
                raise AuthError("Nieprawidłowe hasło")

    def headers(self):
        h = {HDR_CLIENT: quote(self.client_name), HDR_PROTO: str(PROTO)}
        if self.protected:
            h[HDR_AUTH] = make_proof(self.password, self.nonce)
        return h

    def get(self, path, **kw):
        kw.setdefault("timeout", (5, 30))
        headers = {**self.headers(), **kw.pop("headers", {})}
        return self.sess.get(self.base + path, headers=headers, **kw)

    def set_state(self, state, total=None):
        self.state = state
        if total is not None:
            self.total = total
        self._ping()

    def _ping(self):
        if self._closed.is_set():
            return
        params = {"state": self.state, "total": self.total,
                  "peer": self.peer.port if self.peer else 0}
        if self.done_fn:
            params["done"] = int(self.done_fn())
        try:
            self.get("/ping", params=params, timeout=3).close()
        except requests.RequestException:
            pass

    def peers(self):
        """Inni klienci tego hosta z serwerem P2P: [{"name", "ip", "port"}]."""
        try:
            r = self.get("/peers", timeout=(3, 5))
            data = r.json() if r.status_code == 200 else []
        except (requests.RequestException, ValueError):
            return []
        return [p for p in data if isinstance(p, dict) and p.get("ip") and p.get("port")]

    def _heartbeat(self):
        while not self._closed.wait(HEARTBEAT):
            self._ping()

    def close(self):
        if self._closed.is_set():
            return
        self._closed.set()
        if self.peer:
            self.peer.stop()

        def bye():
            try:
                self.get("/bye", timeout=2).close()
            except requests.RequestException:
                pass
            self.sess.close()
        threading.Thread(target=bye, daemon=True).start()


# foldery-kategorie MX Bikes – mod to pierwszy element ścieżki, który nie jest kategorią
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
# grupy na liście modów (kolejność wyświetlania)
KIND_GROUPS = [("Mapa", "Mapy"), ("Motor", "Motory"), ("Opony", "Opony"), ("Kask", "Kaski"),
               ("Strój", "Stroje"), ("Rider", "Ridery"), ("Inne", "Inne")]


def mod_kind(key):
    parts = [p.lower() for p in key.split("/")[:-1]]
    first = parts[0] if parts else ""
    for p in reversed(parts):
        kind = CATEGORY_LABELS.get(p)
        # 'tracks/enduro' to mapa, ale 'bikes/enduro' to motor – foldery dyscyplin liczą się tylko przy mapach
        if kind == "Mapa" and p != "tracks" and first != "tracks":
            continue
        if kind:
            return kind
    return "Inne"


def local_path(folder, rel):
    """Gdzie u klienta leży plik z indeksu hosta – zawsze względem folderu mods."""
    return safe_join(folder, mods_rel(rel))


def mod_key(rel):
    """'tracks/motocross/Foo.pkz' -> 'tracks/motocross/Foo.pkz',
    'tracks/motocross/Foo/terrain/a.hrc' -> 'tracks/motocross/Foo'."""
    parts = [p for p in mods_rel(rel).split("/") if p]
    for i, p in enumerate(parts):
        if p.lower() not in CATEGORY_DIRS or i == len(parts) - 1:
            return "/".join(parts[:i + 1])
    return "/".join(parts)


class ModGroup:
    """Jeden mod hosta (mapa, motor…) i stan jego plików u klienta."""

    def __init__(self, key):
        self.key = key
        parts = key.split("/")
        self.name = parts[-1]
        self.path = "/".join(parts[:-1])
        self.kind = mod_kind(key)
        self.files = 0
        self.size = 0
        self.todo = []           # FileItem do pobrania

    @property
    def todo_size(self):
        return sum(f.size for f in self.todo)

    @property
    def status(self):
        if not self.todo:
            return "aktualny"
        if len(self.todo) == self.files and all(f.reason == "brakuje" for f in self.todo):
            return "brakuje"
        return "nieaktualny"


class FileItem:
    __slots__ = ("rel", "name", "size", "hash", "reason", "status", "done")

    def __init__(self, rel, info, reason):
        self.rel = rel                         # klucz z indeksu hosta (do URL)
        self.name = mods_rel(rel)              # względem folderu mods (zapis + wyświetlanie)
        self.size = int(info["size"])
        self.hash = info["hash"]
        self.reason = reason                   # "brakuje" / "inna wersja"
        self.status = reason
        self.done = 0


class CheckJob(threading.Thread):
    """Pobiera indeks hosta i porównuje go z lokalnym folderem modów."""

    def __init__(self, conn, folder):
        super().__init__(daemon=True)
        self.conn, self.folder = conn, resolve_mods_root(folder)
        self.stop = threading.Event()
        self.phase = "host"          # host / check / done
        self.host_done = self.host_total = 0
        self.files_total = self.files_done = 0
        self.bytes_total = self.bytes_done = 0
        self.cached = 0
        self.current = []
        self.meter = SpeedMeter()
        self.index = {}
        self.todo = []
        self.mods = []               # ModGroup – wszystkie mody hosta
        self.ok_count = 0
        self.error = None
        self.cancelled = False
        self.duration = 0.0

    def cancel(self):
        self.stop.set()

    def run(self):
        t0 = time.monotonic()
        try:
            self.conn.set_state("sprawdza mody")
            self.index = self._get_index()
            if self.index is not None:
                self._check()
        except Cancelled:
            self.cancelled = True
        except (requests.RequestException, OSError, ValueError) as e:
            self.error = str(e) or e.__class__.__name__
        finally:
            if self.stop.is_set():
                self.cancelled = True
            self.duration = time.monotonic() - t0
            self.phase = "done"

    def _get_index(self):
        while not self.stop.is_set():
            r = self.conn.get("/index", timeout=(5, 60))
            if r.status_code == 200:
                return r.json()
            if r.status_code == 401:
                raise ValueError("Nieprawidłowe hasło")
            if r.status_code != 503:
                raise ValueError(f"Host odpowiedział HTTP {r.status_code}")
            try:
                st = self.conn.get("/status", timeout=5).json()
            except (requests.RequestException, ValueError):
                st = {"scanning": True}
            if not st.get("scanning"):
                raise ValueError("Host nie zeskanował jeszcze modów")
            self.host_done, self.host_total = st.get("done", 0), st.get("total", 0)
            self.stop.wait(1)
        raise Cancelled()

    def _check(self):
        self.phase = "check"
        cache = HashCache(CLIENT_CACHE)
        todo, cand, valid = [], [], set()
        for rel, info in self.index.items():
            try:
                p = local_path(self.folder, rel)
            except ValueError:
                continue
            valid.add(p)
            try:
                st = os.stat(p)
            except OSError:
                todo.append(FileItem(rel, info, "brakuje"))
                continue
            if st.st_size != info["size"]:
                todo.append(FileItem(rel, info, "inna wersja"))
                continue
            h = cache.get(p, st)
            if h is not None:
                self.cached += 1
                if h != info["hash"]:
                    todo.append(FileItem(rel, info, "inna wersja"))
            else:
                cand.append((rel, info, p, st))

        self.files_total = len(cand)
        self.bytes_total = sum(c[1]["size"] for c in cand)
        self.meter.reset()
        lock = threading.Lock()

        def add(n):
            self.meter.add(n)
            with lock:
                self.bytes_done += n

        def work(item):
            rel, info, p, st = item
            if self.stop.is_set():
                raise Cancelled()
            self.current.append(rel)
            try:
                h = md5_file(p, add, self.stop)
                cache.put(p, st, h)
                cache.checkpoint()
            except OSError:
                h = None
            finally:
                self.current.remove(rel)
            with lock:
                self.files_done += 1
            return rel, info, h

        try:
            with ThreadPoolExecutor(max_workers=HASH_WORKERS) as ex:
                for rel, info, h in ex.map(work, cand):
                    if h != info["hash"]:
                        todo.append(FileItem(rel, info, "inna wersja"))
        finally:
            cache.save()
        cache.prune(self.folder, valid)
        cache.save()
        todo.sort(key=lambda f: f.name.lower())
        self.todo = todo
        self.ok_count = len(self.index) - len(todo)
        self.mods = group_mods(self.index, todo)


def group_mods(index, todo):
    """Grupuje indeks hosta w mody; najpierw te do pobrania, potem aktualne."""
    groups = {}
    for rel, info in index.items():
        k = mod_key(rel)
        g = groups.get(k)
        if g is None:
            g = groups[k] = ModGroup(k)
        g.files += 1
        g.size += int(info["size"])
    for f in todo:
        groups[mod_key(f.rel)].todo.append(f)
    order = {"brakuje": 0, "nieaktualny": 1, "aktualny": 2}
    return sorted(groups.values(), key=lambda g: (order[g.status], g.kind, g.name.lower()))
