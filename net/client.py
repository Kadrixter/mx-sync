"""Klient: połączenie z hostem, sprawdzanie lokalnych modów i pobieranie.

Sprawdzanie: najpierw indeks hosta, potem MD5 liczone TYLKO dla plików o zgodnym
rozmiarze (brakujące / inny rozmiar od razu idą do pobrania), z cache hashy.
Pobieranie: plik .part, wznawianie (Range), ponawianie z odczekaniem, MD5 w locie.
"""
import hashlib
import os
import shutil
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

import requests
from requests.adapters import HTTPAdapter

from net.protocol import CHUNK, HDR_AUTH, HDR_CLIENT, MAGIC, make_proof
from utils.config import CLIENT_CACHE
from utils.files import safe_join
from utils.fmt import fmt_size
from utils.hashing import HASH_CHUNK, Cancelled, HashCache, md5_file
from utils.speed import SpeedMeter

RETRIES = 4
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
        self.legacy = False          # stary host v3 (bez /hello i /ping)
        self.nonce = ""
        self.state, self.total = "połączony", 0
        self._closed = threading.Event()
        self.sess = requests.Session()
        self.sess.mount("http://", HTTPAdapter(pool_connections=16, pool_maxsize=16))
        try:
            self._hello()
        except BaseException:
            self.sess.close()
            raise
        threading.Thread(target=self._heartbeat, daemon=True).start()

    def _hello(self):
        r = self.sess.get(self.base + "/hello", timeout=(5, 10))
        if r.status_code == 404:
            self.legacy = True
            r = self.sess.get(self.base + "/status", timeout=(5, 10))
            r.raise_for_status()
            return
        r.raise_for_status()
        info = r.json()
        if info.get("magic") != MAGIC:
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
        h = {HDR_CLIENT: quote(self.client_name)}
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
        if self.legacy or self._closed.is_set():
            return
        try:
            self.get("/ping", params={"state": self.state, "total": self.total}, timeout=3).close()
        except requests.RequestException:
            pass

    def _heartbeat(self):
        while not self._closed.wait(HEARTBEAT):
            self._ping()

    def close(self):
        if self._closed.is_set():
            return
        self._closed.set()

        def bye():
            if not self.legacy:
                try:
                    self.get("/bye", timeout=2).close()
                except requests.RequestException:
                    pass
            self.sess.close()
        threading.Thread(target=bye, daemon=True).start()


class FileItem:
    __slots__ = ("rel", "name", "size", "hash", "reason", "status", "done")

    def __init__(self, rel, info, reason):
        self.rel = rel                         # klucz z indeksu hosta (do URL)
        self.name = rel.replace("\\", "/")     # do wyświetlania
        self.size = int(info["size"])
        self.hash = info["hash"]
        self.reason = reason                   # "brakuje" / "inna wersja"
        self.status = reason
        self.done = 0


class CheckJob(threading.Thread):
    """Pobiera indeks hosta i porównuje go z lokalnym folderem modów."""

    def __init__(self, conn, folder):
        super().__init__(daemon=True)
        self.conn, self.folder = conn, folder
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
                p = safe_join(self.folder, rel)
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


class DownloadJob(threading.Thread):
    """Pobiera listę plików równolegle; postęp w atrybutach (czytane przez GUI)."""

    def __init__(self, conn, folder, files, parallel=3):
        super().__init__(daemon=True)
        self.conn, self.folder = conn, folder
        self.files = sorted(files, key=lambda f: f.size, reverse=True)   # duże najpierw
        self.parallel = max(1, min(8, parallel))
        self.total = sum(f.size for f in files)
        self.done_bytes = 0
        self.files_done = 0
        self.failed = 0
        self.active = []
        self.meter = SpeedMeter()
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.finished = False
        self.cancelled = False
        self.error = None
        self.cache = None

    def cancel(self):
        self.stop.set()

    def run(self):
        try:
            try:
                free = shutil.disk_usage(self.folder).free
                need = sum(f.size - f.done for f in self.files)
                if need > free:
                    self.error = f"Za mało miejsca na dysku: potrzeba {fmt_size(need)}, wolne {fmt_size(free)}"
                    return
            except OSError:
                pass
            self.cache = HashCache(CLIENT_CACHE)
            self.conn.set_state("pobiera", self.total)
            with ThreadPoolExecutor(max_workers=self.parallel) as ex:
                list(ex.map(self._one, self.files))
            self.cache.save()
            self.cancelled = self.stop.is_set()
            if self.cancelled:
                self.conn.set_state("przerwał pobieranie")
            else:
                self.conn.set_state("zakończono" if not self.failed else "zakończono z błędami")
        except Exception as e:
            self.error = str(e) or e.__class__.__name__
        finally:
            if self.stop.is_set():
                self.cancelled = True
            self.finished = True

    def _set_done(self, f, value):
        with self.lock:
            self.done_bytes += value - f.done
            f.done = value

    def _one(self, f):
        if self.stop.is_set():
            return
        with self.lock:
            self.active.append(f)
        try:
            try:
                dest = safe_join(self.folder, f.rel)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
            except (ValueError, OSError) as e:
                f.status = "błąd"
                self._failed(e)
                return
            url = "/download/" + quote(f.rel)
            last = ""
            for attempt in range(1, RETRIES + 1):
                if self.stop.is_set():
                    f.status = "przerwano"
                    return
                f.status = "pobieranie"
                try:
                    self._attempt(url, dest, f)
                    f.status = "gotowe"
                    with self.lock:
                        self.files_done += 1
                    return
                except Cancelled:
                    f.status = "przerwano"
                    return
                except (requests.RequestException, OSError) as e:
                    last = str(e)
                    if attempt < RETRIES:
                        f.status = "ponawiam…"
                        self.stop.wait(min(2 ** attempt, 10))
            f.status = "błąd"
            self._failed(last)
        finally:
            with self.lock:
                self.active.remove(f)

    def _failed(self, err):
        with self.lock:
            self.failed += 1

    def _attempt(self, url, dest, f):
        part = dest + ".part"
        h = hashlib.md5()
        have = 0
        if os.path.exists(part):
            have = os.path.getsize(part)
            if have > f.size:
                os.remove(part)
                have = 0
            elif have:
                with open(part, "rb") as src:
                    read = 0
                    while True:
                        b = src.read(HASH_CHUNK)
                        if not b:
                            break
                        h.update(b)
                        read += len(b)
                        self._set_done(f, read)
                        if self.stop.is_set():
                            raise Cancelled()
        self._set_done(f, have)

        if have < f.size:
            headers = {"Range": f"bytes={have}-"} if have else {}
            r = self.conn.get(url, stream=True, headers=headers, timeout=(10, 30))
            try:
                if r.status_code == 416:
                    os.remove(part)
                    self._set_done(f, 0)
                    raise IOError("Zły zakres, zaczynam od nowa")
                if r.status_code == 200 and have:
                    have = 0                    # host zignorował Range
                    h = hashlib.md5()
                    self._set_done(f, 0)
                elif r.status_code not in (200, 206):
                    raise IOError(f"HTTP {r.status_code}")
                got = have
                with open(part, "ab" if have else "wb", buffering=CHUNK) as out:
                    for chunk in r.iter_content(chunk_size=CHUNK):
                        if self.stop.is_set():
                            raise Cancelled()
                        if not chunk:
                            continue
                        out.write(chunk)
                        h.update(chunk)
                        got += len(chunk)
                        self.meter.add(len(chunk))
                        self._set_done(f, got)
                if got != f.size:
                    raise IOError(f"Połączenie przerwane ({fmt_size(got)} z {fmt_size(f.size)})")
            finally:
                r.close()

        if h.hexdigest() != f.hash:
            os.remove(part)
            self._set_done(f, 0)
            raise IOError("Zły hash – pobieram od nowa")
        os.replace(part, dest)
        try:
            self.cache.put(os.path.abspath(dest), os.stat(dest), f.hash)
        except OSError:
            pass
