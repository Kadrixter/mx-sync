"""Serwer hosta: HTTP (zgodny z klientem v3) + odpowiadanie na wykrywanie UDP.

Skan modów liczy MD5 z cache (rozmiar + mtime), pliki wysyła sendfile z obsługą Range.
"""
import gzip
import itertools
import json
import os
import re
import secrets
import socket
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

from net.discovery import DiscoveryResponder
from net.protocol import HDR_AUTH, HDR_CLIENT, HTTP_PORT, MAGIC, make_proof
from utils.config import HOST_CACHE
from utils.files import mods_rel, resolve_mods_root, walk_files
from utils.hashing import Cancelled, HashCache, md5_file
from utils.speed import SpeedMeter

SEND_CHUNK = 1024 * 1024
SESSION_TTL = 15.0
HASH_WORKERS = min(8, (os.cpu_count() or 2) * 2)


class ClientSession:
    def __init__(self, sid, name, ip):
        self.id = sid
        self.name = name
        self.ip = ip
        self.connected_at = time.time()
        self.last_seen = time.monotonic()
        self.state = "połączony"
        self.total = 0          # ile bajtów klient zamierza pobrać (z /ping)
        self.sent = 0
        self.files_done = 0
        self.current = ""
        self.active = 0         # pobierania w toku
        self.meter = SpeedMeter()


class _HttpServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 64
    # na Windows SO_REUSEADDR pozwala dwóm programom zająć ten sam port
    allow_reuse_address = sys.platform != "win32"


class ModServer:
    def __init__(self, folder, entries, name, password=""):
        self.folder = os.path.abspath(folder)
        self.entries = list(entries)
        self.name = name
        self.password = password or ""
        self.id = uuid.uuid4().hex
        self.nonce = secrets.token_hex(16)
        self.port = None
        self.paused = False
        self.bytes_sent = 0

        # klucze indeksu są zawsze względem folderu mods MX Bikes (jak w skryptach v2/v3),
        # nawet gdy host wskazał folder 'MX Bikes' albo podfolder typu 'mods\tracks'
        self.mods_root = resolve_mods_root(self.folder)
        self.index = None           # rel -> {"size", "hash"}
        self.paths = {}             # rel -> pełna ścieżka pliku na dysku hosta
        self._index_json = b"{}"
        self._index_gz = b""
        self.items = []             # podsumowanie elementów dla GUI
        self.scanning = False
        self.scan_error = None
        self.scan_files_total = self.scan_files_done = 0
        self.scan_bytes_total = self.scan_bytes_done = 0
        self.scan_cached = 0
        self.scan_dur = 0.0
        self.scan_gen = 0           # rośnie po każdym skanie (GUI odświeża listę)
        self.scan_meter = SpeedMeter()

        self._lock = threading.Lock()
        self._sessions = {}
        self._sid = itertools.count(1)
        self._stop = threading.Event()
        self._scan_stop = threading.Event()
        self._scan_thread = None
        self._httpd = None
        self._discovery = None

    @property
    def protected(self):
        return bool(self.password)

    @property
    def discovery_error(self):
        return self._discovery.error if self._discovery else None

    # ---------- start / stop ----------

    def start(self):
        last = None
        for port in range(HTTP_PORT, HTTP_PORT + 10):
            try:
                self._httpd = _HttpServer(("", port), _make_handler(self))
                self.port = port
                break
            except OSError as e:
                last = e
        if not self._httpd:
            raise OSError(f"Nie można otworzyć portu TCP {HTTP_PORT}: {last}")
        threading.Thread(target=self._httpd.serve_forever, kwargs={"poll_interval": 0.3},
                         daemon=True).start()
        self._discovery = DiscoveryResponder(self.discovery_info)
        self._discovery.start()
        self.rescan()

    def stop(self):
        self._stop.set()
        self._scan_stop.set()
        if self._discovery:
            self._discovery.stop()
        if self._httpd:
            threading.Thread(target=self._shutdown_http, daemon=True).start()

    def _shutdown_http(self):
        self._httpd.shutdown()
        self._httpd.server_close()

    def discovery_info(self):
        idx = self.index or {}
        return {"magic": MAGIC, "id": self.id, "name": self.name, "port": self.port,
                "protected": self.protected, "files": len(idx),
                "size": sum(v["size"] for v in idx.values()), "scanning": self.scanning}

    # ---------- skanowanie ----------

    def rescan(self, entries=None, force=False):
        """Skan w tle; podczas skanu /index zwraca 503 (klient v3 czeka)."""
        if entries is not None:
            self.entries = list(entries)
        old = self._scan_thread
        self._scan_stop.set()
        stop = self._scan_stop = threading.Event()
        self.scanning = True
        self.index = None

        def run():
            if old:
                old.join()
            self._scan(stop, force)
        self._scan_thread = threading.Thread(target=run, daemon=True)
        self._scan_thread.start()

    def _scan(self, stop, force):
        t0 = time.monotonic()
        self.scan_error = None
        cache = HashCache(HOST_CACHE)
        if force:
            cache.data = {}
        try:
            files, items = [], []
            for name in self.entries:
                found = walk_files(self.folder, name)
                files += found
                items.append({"name": name, "is_dir": os.path.isdir(os.path.join(self.folder, name)),
                              "files": len(found), "size": sum(st.st_size for _, _, st in found)})
            index, todo, paths = {}, [], {}
            keyed = []
            for rel, path, st in files:
                rel = self._key(rel, path)
                if rel in paths:
                    continue
                paths[rel] = path
                keyed.append((rel, path, st))
            files = keyed
            for rel, path, st in files:
                h = cache.get(path, st)
                if h:
                    index[rel] = {"size": st.st_size, "hash": h}
                else:
                    todo.append((rel, path, st))
            self.scan_cached = len(index)
            self.scan_files_total, self.scan_files_done = len(files), len(index)
            self.scan_bytes_total, self.scan_bytes_done = sum(st.st_size for _, _, st in todo), 0
            self.scan_meter.reset()

            def add(n):
                self.scan_bytes_done += n
                self.scan_meter.add(n)

            def work(item):
                rel, path, st = item
                try:
                    h = md5_file(path, add, stop)
                except OSError:
                    return None
                cache.put(path, st, h)
                self.scan_files_done += 1
                cache.checkpoint()
                return rel, {"size": st.st_size, "hash": h}

            with ThreadPoolExecutor(max_workers=HASH_WORKERS) as ex:
                for r in ex.map(work, todo):
                    if r:
                        index[r[0]] = r[1]
            if stop.is_set():
                return
            cache.prune(self.folder, {p for _, p, _ in files})
            cache.save()
            raw = json.dumps(index, ensure_ascii=False).encode("utf-8")
            with self._lock:
                self._index_json, self._index_gz = raw, gzip.compress(raw, 4)
                self.items = items
                self.paths = paths
                self.index = index
            self.scan_dur = time.monotonic() - t0
            self.scan_gen += 1
        except Cancelled:
            cache.save()
        except Exception as e:
            self.scan_error = str(e)
        finally:
            if not stop.is_set():
                self.scanning = False

    def _key(self, rel, path):
        """Klucz pliku względem folderu mods (z '/'), żeby klient zapisał go we właściwym miejscu."""
        try:
            r = os.path.relpath(path, self.mods_root)
            if not r.startswith(".."):
                return mods_rel(r)
        except ValueError:          # inny dysk niż folder mods
            pass
        return mods_rel(rel)

    # ---------- klienci ----------

    def session(self, handler):
        ip = handler.client_address[0]
        name = unquote(handler.headers.get(HDR_CLIENT, "")) or ip
        key = (ip, name)
        with self._lock:
            s = self._sessions.get(key)
            if not s:
                s = self._sessions[key] = ClientSession(next(self._sid), name, ip)
            s.last_seen = time.monotonic()
            return s

    def drop_session(self, handler):
        ip = handler.client_address[0]
        name = unquote(handler.headers.get(HDR_CLIENT, "")) or ip
        with self._lock:
            self._sessions.pop((ip, name), None)

    def snapshot(self):
        now = time.monotonic()
        out = []
        with self._lock:
            for k, s in list(self._sessions.items()):
                if s.active == 0 and now - s.last_seen > SESSION_TTL:
                    del self._sessions[k]
                    continue
                out.append({"id": s.id, "name": s.name, "ip": s.ip, "connected_at": s.connected_at,
                            "state": s.state, "total": s.total, "sent": s.sent, "current": s.current,
                            "files_done": s.files_done, "active": s.active, "speed": s.meter.speed()})
        out.sort(key=lambda s: s["id"])
        return out

    def total_speed(self):
        with self._lock:
            return sum(s.meter.speed() for s in self._sessions.values())


def _make_handler(srv):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        timeout = 300

        def setup(self):
            super().setup()
            try:
                self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                self.connection.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1024 * 1024)
            except OSError:
                pass

        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code=200):
            self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

        def _authorized(self):
            if not srv.protected:
                return True
            return self.headers.get(HDR_AUTH, "") == make_proof(srv.password, srv.nonce)

        def do_GET(self):
            try:
                self._route()
            except (ConnectionError, OSError):
                self.close_connection = True

        def _route(self):
            url = urlsplit(self.path)
            path = unquote(url.path)
            if path == "/hello":
                return self._json({"magic": MAGIC, "id": srv.id, "name": srv.name,
                                   "protected": srv.protected, "nonce": srv.nonce})
            if not self._authorized():
                return self._json({"error": "Nieprawidłowe hasło"}, 401)
            if path == "/status":
                return self._json({"scanned": srv.index is not None, "scanning": srv.scanning,
                                   "done": srv.scan_files_done, "total": srv.scan_files_total,
                                   "paused": srv.paused})
            if path == "/index":
                sess = srv.session(self)
                if srv.index is None:
                    return self._json({"error": "host skanuje mody"}, 503)
                sess.state = "sprawdza mody"
                with srv._lock:
                    raw, gz = srv._index_json, srv._index_gz
                if "gzip" in self.headers.get("Accept-Encoding", ""):
                    return self._send(200, gz, extra={"Content-Encoding": "gzip"})
                return self._send(200, raw)
            if path == "/ping":
                q = parse_qs(url.query)
                sess = srv.session(self)
                state = q.get("state", [""])[0]
                if state:
                    if state == "pobiera" and sess.state != "pobiera":
                        sess.sent = sess.files_done = 0
                    sess.state = state
                try:
                    sess.total = int(q.get("total", [sess.total])[0])
                except ValueError:
                    pass
                return self._json({"ok": True})
            if path == "/bye":
                srv.drop_session(self)
                return self._json({"ok": True})
            if path.startswith("/download/"):
                return self._download(path[len("/download/"):])
            self._json({"error": "Nie znaleziono"}, 404)

        def _download(self, rel):
            idx = srv.index
            if srv.paused or idx is None:
                return self._json({"error": "Host wstrzymał pobierania" if srv.paused else "Host skanuje mody"}, 503)
            key = rel if rel in idx else mods_rel(rel)
            info, fp = idx.get(key), srv.paths.get(key)
            if info is None or fp is None:
                return self._json({"error": "Plik nie jest udostępniony"}, 404)
            try:
                size = os.path.getsize(fp)
            except OSError:
                return self._json({"error": "Plik nie istnieje"}, 404)

            start, end, partial = 0, size - 1, False
            rng = self.headers.get("Range")
            m = re.match(r"bytes=(\d*)-(\d*)", rng.strip()) if rng else None
            if m and size > 0:
                a, b = m.groups()
                if a:
                    start = int(a)
                    if b:
                        end = min(int(b), size - 1)
                elif b:
                    start = max(0, size - int(b))
                partial = True
                if start > end:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return

            length = max(0, end - start + 1)
            self.send_response(206 if partial else 200)
            if partial:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(length))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            self.wfile.flush()
            if length == 0:
                return

            sess = srv.session(self)
            with srv._lock:
                sess.active += 1
                sess.current = rel.replace("\\", "/")
                sess.sent += start          # wznowienie: ta część jest już u klienta
                if sess.state not in ("pobiera",):
                    sess.state = "pobiera"
            pos, done = start, False
            try:
                with open(fp, "rb") as f:
                    while pos <= end:
                        if srv._stop.is_set():
                            break
                        sent = self.connection.sendfile(f, pos, min(SEND_CHUNK, end - pos + 1))
                        if not sent:
                            break
                        pos += sent
                        sess.meter.add(sent)
                        with srv._lock:
                            sess.sent += sent
                            srv.bytes_sent += sent
                    done = pos > end
            except OSError:
                self.close_connection = True
            finally:
                with srv._lock:
                    sess.active -= 1
                    sess.last_seen = time.monotonic()
                    if done:
                        sess.files_done += 1
                    if sess.active == 0:
                        sess.current = ""
            if not done:
                self.close_connection = True

    return Handler
