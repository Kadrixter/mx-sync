"""Pobieranie z wielu źródeł naraz (jak torrent): host + inni klienci, którzy mają ten sam mod.

Plik dzielony jest na kawałki po PIECE bajtów. Każde źródło ma własne wątki, które biorą
kolejny wolny kawałek pliku, który to źródło posiada (duże pliki najpierw, więc wszystkie
źródła ciągną naraz ten sam plik). Kawałek trafia od razu na swoje miejsce w pliku .part,
a lista gotowych kawałków w .part.map (wznawianie). Po złożeniu pliku liczone jest MD5 –
jeśli się nie zgadza, plik pobierany jest od nowa wyłącznie z hosta.
Co REDISCOVER sekund pytamy hosta o nowych klientów (ktoś dołączył w trakcie pobierania).
"""
import json
import os
import shutil
import threading
import time
from urllib.parse import quote

import requests
from requests.adapters import HTTPAdapter

from net.client import KIND_GROUPS, local_path, mod_key, mod_kind
from net.protocol import CHUNK
from utils.config import CLIENT_CACHE
from utils.fmt import fmt_size
from utils.hashing import Cancelled, HashCache, md5_file
from utils.speed import SpeedMeter

PIECE = 4 * 1024 * 1024
RETRIES = 4                 # nieudane próby hosta dla jednego pliku
PEER_WORKERS = 2            # wątki na jednego klienta-źródło
PEER_MAX_ERRORS = 3         # po tylu błędach klient przestaje być źródłem
REDISCOVER = 10.0


class Source:
    """Skąd pobieramy: host (ma wszystko) albo inny klient (ma część plików)."""

    def __init__(self, name, get, workers, is_host=False, has=None, key=None):
        self.name = name
        self.get = get
        self.workers = workers
        self.is_host = is_host
        self.has = has              # zbiór rel albo None (= wszystko)
        self.key = key
        self.meter = SpeedMeter()
        self.bytes = 0
        self.errors = 0
        self.active = 0
        self.dead = False
        self.revivals = 0

    def can(self, task):
        if self.dead:
            return False
        if self.is_host:
            return True
        return not task.host_only and task.f.rel in (self.has or ())

    def url(self, f):
        if self.is_host:
            return "/download/" + quote(f.rel)
        return "/piece/" + quote(f.rel) + "?hash=" + f.hash


class _Task:
    """Stan pobierania jednego pliku."""

    def __init__(self, f, dest):
        self.f = f
        self.dest = dest
        self.part = dest + ".part"
        self.map = dest + ".part.map"
        self.n = max(1, -(-f.size // PIECE))
        self.done = set()
        self.free = []              # numery kawałków do pobrania (rosnąco)
        self.inflight = 0
        self.verifying = False
        self.finished = False       # gotowy albo nieudany
        self.host_only = False
        self.host_fails = 0         # błędy hosta z rzędu (zeruje się po udanym kawałku)
        self.bad_hash = 0           # ile razy złożony plik miał zły MD5
        self.lock = threading.Lock()
        self.created = False
        self.mod = 0                # numer modu w kolejce (mody pobierane po kolei)

    def piece_range(self, i):
        start = i * PIECE
        return start, min(self.f.size, start + PIECE) - 1

    def load(self):
        """Wznawianie: .part.map albo stary ciągły .part (pełne kawałki od początku)."""
        f = self.f
        if f.size == 0:
            self.done, self.free = {0}, []
            return 0
        try:
            have = os.path.getsize(self.part)
        except OSError:
            have = -1
        if have >= 0:
            try:
                with open(self.map, encoding="utf-8") as fh:
                    m = json.load(fh)
                if m.get("size") == f.size and m.get("hash") == f.hash and have == f.size:
                    self.done = {int(i) for i in m.get("done", []) if 0 <= int(i) < self.n}
                    self.created = True
                else:
                    raise ValueError
            except (OSError, ValueError, TypeError, AttributeError):
                self.done = set(range(have // PIECE)) if 0 < have <= f.size else set()
        self.free = [i for i in range(self.n) if i not in self.done]
        return sum(self.piece_range(i)[1] - self.piece_range(i)[0] + 1 for i in self.done) if f.size else 0

    def ensure_file(self):
        with self.lock:
            if self.created:
                return
            mode = "r+b" if os.path.exists(self.part) else "wb"
            with open(self.part, mode) as fh:
                fh.truncate(self.f.size)
            self.created = True

    def save_map(self):
        with self.lock:
            data = {"size": self.f.size, "hash": self.f.hash, "done": sorted(self.done)}
            try:
                tmp = self.map + ".tmp"
                with open(tmp, "w", encoding="utf-8") as fh:
                    json.dump(data, fh)
                os.replace(tmp, self.map)
            except OSError:
                pass

    def reset(self):
        self.done.clear()
        self.free = list(range(self.n))
        for p in (self.map,):
            try:
                os.remove(p)
            except OSError:
                pass


def ask_have(sess, base, body, headers, timeout=(2, 10)):
    """Pyta gracza (serwer P2P), które z plików ma; None = nie odpowiada."""
    try:
        r = sess.post(base + "/have", json=body, headers=headers, timeout=timeout)
        return set(r.json()) if r.status_code == 200 else set()
    except (requests.RequestException, ValueError, TypeError):
        return None


class PeerScan(threading.Thread):
    """W tle co INTERVAL s sprawdza, ilu innych graczy ma każdy mod hosta (cały, aktualny)."""
    INTERVAL = 15.0

    def __init__(self, conn, index):
        super().__init__(daemon=True)
        self.conn = conn
        self.body = [{"rel": r, "size": int(v["size"]), "hash": v["hash"]} for r, v in index.items()]
        self.files_per_mod = {}
        for r in index:
            k = mod_key(r)
            self.files_per_mod[k] = self.files_per_mod.get(k, 0) + 1
        self.counts = {}            # klucz modu -> ilu graczy go ma
        self.peers = []             # nazwy graczy z P2P, którzy odpowiedzieli
        self.gen = 0                # rośnie po każdej zmianie wyników
        self.stop = threading.Event()

    def cancel(self):
        self.stop.set()

    def run(self):
        sess = requests.Session()
        try:
            while not self.stop.is_set() and not self.conn._closed.is_set():
                self._scan(sess)
                self.stop.wait(self.INTERVAL)
        finally:
            sess.close()

    def _scan(self, sess):
        headers = self.conn.headers()
        counts, names = {}, []
        for p in self.conn.peers():
            if self.stop.is_set():
                return
            have = ask_have(sess, f"http://{p['ip']}:{p['port']}", self.body, headers, timeout=(2, 30))
            if have is None:
                continue
            names.append(str(p.get("name") or p["ip"]))
            per = {}
            for r in have:
                k = mod_key(r)
                per[k] = per.get(k, 0) + 1
            for k, n in per.items():
                if n == self.files_per_mod.get(k):
                    counts[k] = counts.get(k, 0) + 1
        if counts != self.counts or names != self.peers:
            self.counts, self.peers = counts, names
            self.gen += 1


class DownloadJob(threading.Thread):
    """Pobiera listę plików; postęp w atrybutach (czytane przez GUI)."""

    def __init__(self, conn, folder, files, parallel=3):
        super().__init__(daemon=True)
        self.conn, self.folder = conn, folder
        # po kolei: mod za modem (w kolejności z listy: mapy, motory, opony…), w modzie duże pliki najpierw
        order = {k: i for i, (k, _) in enumerate(KIND_GROUPS)}

        def key(f):
            k = mod_key(f.rel)
            return order.get(mod_kind(k), 99), k.lower(), -f.size
        self.files = sorted(files, key=key)
        self.mod_keys = []          # mody w kolejności pobierania
        for f in self.files:
            k = mod_key(f.rel)
            if not self.mod_keys or self.mod_keys[-1] != k:
                self.mod_keys.append(k)
        self.parallel = max(1, min(8, parallel))
        self.total = sum(f.size for f in files)
        self.done_bytes = 0
        self.files_done = 0
        self.failed = 0
        self.meter = SpeedMeter()
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.finished = False
        self.cancelled = False
        self.error = None
        self.cache = None
        self.tasks = []
        self.sources = []
        self._threads = []
        self._peer_sess = None

    # ---------- API dla GUI ----------

    @property
    def active(self):
        return [t.f for t in self.tasks if t.inflight or t.verifying]

    def mod_progress(self):
        """(numer bieżącego modu od 1, ile modów, nazwa bieżącego, ile gotowych)."""
        tasks = list(self.tasks)
        left = {t.mod for t in tasks if not t.finished}
        done = len(self.mod_keys) - len(left)
        if not left:
            return len(self.mod_keys), len(self.mod_keys), "", done
        cur = min(left)
        return cur + 1, len(self.mod_keys), self.mod_keys[cur].split("/")[-1], done

    @property
    def peer_bytes(self):
        return sum(s.bytes for s in self.sources if not s.is_host)

    def cancel(self):
        self.stop.set()

    # ---------- główna pętla ----------

    def run(self):
        try:
            self._prepare()
            if self.error:
                return
            self.cache = HashCache(CLIENT_CACHE)
            self.conn.done_fn = lambda: self.done_bytes
            self.conn.set_state("pobiera", self.total)
            host = Source(self.conn.host_name or "host", self.conn.get, self.parallel, is_host=True)
            self._add_source(host)
            self._discover()
            last = time.monotonic()
            while not self.stop.is_set() and not all(t.finished for t in self.tasks):
                self.stop.wait(0.25)
                if time.monotonic() - last > REDISCOVER:
                    last = time.monotonic()
                    self._discover()
            for t in self._threads:
                t.join()
            self.cache.save()
            self.cancelled = self.stop.is_set()
            for t in self.tasks:
                if not t.finished and t.f.status in ("pobieranie", "ponawiam…", "weryfikuję"):
                    t.f.status = "przerwano"
            if self.cancelled:
                self.conn.set_state("przerwał pobieranie")
            else:
                self.conn.set_state("zakończono" if not self.failed else "zakończono z błędami")
        except Exception as e:
            self.error = str(e) or e.__class__.__name__
            self.stop.set()
        finally:
            self.conn.done_fn = None
            if self._peer_sess:
                self._peer_sess.close()
            if self.stop.is_set():
                self.cancelled = True
            self.finished = True

    def _prepare(self):
        for f in self.files:
            try:
                dest = local_path(self.folder, f.rel)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
            except (ValueError, OSError):
                f.status = "błąd"
                self.failed += 1
                continue
            t = _Task(f, dest)
            t.mod = self.mod_keys.index(mod_key(f.rel))
            f.status = "w kolejce"
            try:
                f.done = t.load()
            except OSError:
                f.done = 0
            self.done_bytes += f.done
            self.tasks.append(t)
        try:
            free = shutil.disk_usage(self.folder).free
            need = sum(t.f.size - t.f.done for t in self.tasks if not t.created)
            if need > free:
                self.error = f"Za mało miejsca na dysku: potrzeba {fmt_size(need)}, wolne {fmt_size(free)}"
        except OSError:
            pass

    # ---------- źródła ----------

    def _add_source(self, src):
        self.sources.append(src)
        self._start_workers(src)

    def _start_workers(self, src):
        for _ in range(src.workers):
            th = threading.Thread(target=self._worker, args=(src,), daemon=True)
            self._threads.append(th)
            th.start()

    def _discover(self):
        """Pyta hosta o innych klientów i każdego z nich o to, które z moich plików ma."""
        todo = [t.f for t in self.tasks if not t.finished]
        if not todo or self.stop.is_set():
            return
        if self._peer_sess is None:
            self._peer_sess = requests.Session()
            self._peer_sess.mount("http://", HTTPAdapter(pool_connections=8, pool_maxsize=16))
        headers = self.conn.headers()          # hasło hosta + moja nazwa (gracz widzi, kto od niego pobiera)
        me = self.conn.peer.port if self.conn.peer else None
        known = {s.key: s for s in self.sources if s.key}
        body = [{"rel": f.rel, "size": f.size, "hash": f.hash} for f in todo]
        for p in self.conn.peers():
            key = f"{p['ip']}:{p['port']}"
            if p["ip"].startswith("127.") and p["port"] == me:
                continue
            base = f"http://{key}"
            have = ask_have(self._peer_sess, base, body, headers)
            if have is None:
                continue
            src = known.get(key)
            if src:
                src.has = have
                if have and src.dead and src.revivals < 3:
                    src.dead, src.errors = False, 0     # znów odpowiada – kolejna szansa
                    src.revivals += 1
                    self._start_workers(src)
                continue
            if not have:
                continue

            def get(path, base=base, **kw):
                kw.setdefault("timeout", (3, 15))
                return self._peer_sess.get(base + path, headers={**headers, **kw.pop("headers", {})}, **kw)
            self._add_source(Source(str(p.get("name") or p["ip"]), get, PEER_WORKERS, has=have, key=key))

    # ---------- wątki pobierające ----------

    def _next(self, src):
        """('piece', task, i) / ('verify', task) / ('wait',) / None (koniec dla tego źródła)."""
        with self.lock:
            useful = False
            # mody po kolei: kawałki rozdajemy tylko z pierwszego modu, który ma jeszcze coś do
            # rozdania – następny mod zaczyna się dopiero, gdy z bieżącego wszystko jest już w drodze
            window = next((t.mod for t in self.tasks if t.free and not t.finished), None)
            first = next((t.mod for t in self.tasks if not t.finished), 0)
            if window is not None:
                window = min(window, first + 1)     # najwyżej bieżący mod + początek następnego
            for t in self.tasks:
                if t.finished or not src.can(t):
                    continue
                if t.free and t.mod > window:
                    useful = True
                    continue
                if t.free:
                    t.inflight += 1
                    t.f.status = "pobieranie"
                    return "piece", t, t.free.pop(0)
                if not t.inflight and not t.verifying and len(t.done) == t.n:
                    t.verifying = True
                    return "verify", t
                useful = True
            return ("wait",) if useful else None

    def _worker(self, src):
        while not self.stop.is_set() and not src.dead:
            job = self._next(src)
            if job is None:
                if src.is_host or all(t.finished for t in self.tasks):
                    return
                self.stop.wait(1.0)             # klient może dostać nowe pliki po _discover
                continue
            if job[0] == "wait":
                self.stop.wait(0.2)
                continue
            if job[0] == "verify":
                self._verify(job[1])
                continue
            _, t, i = job
            src.active += 1
            try:
                self._piece(src, t, i)
            except Cancelled:
                self._piece_back(t, i)
                return
            except Exception as e:             # noqa: BLE001 – wątek nie może zginąć z kawałkiem „w locie”
                self._piece_back(t, i)
                self._source_failed(src, t, e)
            else:
                with self.lock:
                    t.done.add(i)
                    t.inflight -= 1
                    src.errors = 0
                    if src.is_host:
                        t.host_fails = 0
                t.save_map()
            finally:
                src.active -= 1

    def _piece_back(self, t, i):
        with self.lock:
            t.inflight -= 1
            if i not in t.done and i not in t.free:
                t.free.append(i)
                t.free.sort()

    def _source_failed(self, src, t, err):
        if not src.is_host:
            src.errors += 1
            if src.errors >= PEER_MAX_ERRORS:
                src.dead = True
            return
        with self.lock:
            t.host_fails += 1
            fails = t.host_fails
            if fails >= RETRIES and not t.finished:
                t.finished = True
                t.f.status = "błąd"
                self.failed += 1
                return
            t.f.status = "ponawiam…"
        self.stop.wait(min(2 ** fails, 10))

    def _add(self, f, n, src=None):
        with self.lock:
            f.done += n
            self.done_bytes += n
            if src:
                src.bytes += n
        if src and n > 0:
            src.meter.add(n)
            self.meter.add(n)

    def _piece(self, src, t, i):
        start, end = t.piece_range(i)
        want = end - start + 1
        t.ensure_file()
        r = src.get(src.url(t.f), stream=True, headers={"Range": f"bytes={start}-{end}"},
                    timeout=(10, 30) if src.is_host else (3, 15))
        got = 0
        try:
            if r.status_code == 200 and start != 0 or r.status_code not in (200, 206):
                raise IOError(f"HTTP {r.status_code}")
            with open(t.part, "r+b") as out:
                out.seek(start)
                for chunk in r.iter_content(chunk_size=CHUNK):
                    if self.stop.is_set():
                        raise Cancelled()
                    chunk = chunk[:want - got]
                    if not chunk:
                        continue
                    out.write(chunk)
                    got += len(chunk)
                    self._add(t.f, len(chunk), src)
                    if got >= want:
                        break
            if got != want:
                raise IOError(f"Połączenie przerwane ({fmt_size(got)} z {fmt_size(want)})")
        except BaseException:
            self._add(t.f, -got)
            raise
        finally:
            r.close()

    def _verify(self, t):
        f = t.f
        f.status = "weryfikuję"
        try:
            if f.size == 0:
                open(t.part, "wb").close()
            ok = md5_file(t.part, stop=self.stop) == f.hash
            if ok:
                os.replace(t.part, t.dest)
                try:
                    os.remove(t.map)
                except OSError:
                    pass
                st = os.stat(t.dest)
                self.cache.put(os.path.abspath(t.dest), st, f.hash)
                if self.conn.peer:
                    self.conn.peer.remember(t.dest, st, f.hash)
        except Cancelled:
            with self.lock:
                t.verifying = False
            return
        except OSError:
            ok = False
        with self.lock:
            t.verifying = False
            if ok:
                t.finished = True
                f.status = "gotowe"
                self.files_done += 1
                return
            # zły hash – od nowa i tylko z hosta (jeśli to już był host, liczymy jako nieudaną próbę)
            self.done_bytes -= f.done
            f.done = 0
            t.reset()
            if t.host_only:
                t.bad_hash += 1
                if t.bad_hash >= 2:
                    t.finished = True
                    f.status = "błąd"
                    self.failed += 1
                    return
            t.host_only = True
            f.status = "ponawiam…"
