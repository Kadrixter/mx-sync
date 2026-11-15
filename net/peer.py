"""P2P między klientami (jak torrent) – klient udostępnia swoje aktualne mody innym klientom hosta.

Każdy klient po połączeniu z hostem uruchamia mały serwer HTTP i zgłasza hostowi jego port
(/ping?peer=). Pobierający pyta hosta o innych klientów (/peers), a każdego z nich o to,
które pliki ma (/have). Klient udostępnia tylko pliki, których MD5 zna (cache sprawdzania
albo właśnie pobrane) i które zgadzają się z indeksem hosta – nigdy plików .part.

  POST /have                  [{"rel", "size", "hash"}] -> ["rel", ...]
  GET  /piece/<rel>?hash=md5  nagłówek Range -> bajty pliku
Autoryzacja: ten sam nagłówek X-MXSync-Auth co u hosta (dowód znajomości hasła hosta).
"""
import json
import os
import re
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

from net.protocol import HDR_AUTH, HDR_CLIENT, PEER_PORT
from utils.config import CLIENT_CACHE
from utils.files import mods_rel, safe_join
from utils.hashing import HashCache
from utils.speed import SpeedMeter

SEND_CHUNK = 1024 * 1024
MAX_UPLOADS = 6
RECENT = 4.0                # ile sekund po ostatnim kawałku gracz liczy się jako „pobiera ode mnie”


class _HttpServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 32
    allow_reuse_address = sys.platform != "win32"


class PeerServer:
    def __init__(self, auth=None):
        self.auth = auth            # oczekiwany X-MXSync-Auth (None = host bez hasła)
        self.folder = None          # folder mods klienta
        self.port = None
        self.bytes_up = 0
        self.uploads = 0
        self.meter = SpeedMeter()
        self._extra = {}            # ścieżka -> (rozmiar, mtime_ns, md5) – pliki pobrane w tej sesji
        self._cache = None
        self._cache_mtime = None
        self._lock = threading.Lock()
        self._slots = threading.BoundedSemaphore(MAX_UPLOADS)
        self._takers = {}           # nazwa gracza -> [czas ostatniego kawałka, SpeedMeter]
        self._httpd = None
        self._stop = threading.Event()

    def start(self):
        for port in range(PEER_PORT, PEER_PORT + 20):
            try:
                self._httpd = _HttpServer(("", port), _make_handler(self))
                self.port = port
                break
            except OSError:
                continue
        if self._httpd:
            threading.Thread(target=self._httpd.serve_forever, kwargs={"poll_interval": 0.3},
                             daemon=True).start()
        return self.port

    def stop(self):
        self._stop.set()
        if self._httpd:
            httpd, self._httpd = self._httpd, None

            def down():
                httpd.shutdown()
                httpd.server_close()
            threading.Thread(target=down, daemon=True).start()

    def _taker(self, name):
        with self._lock:
            t = self._takers.get(name)
            if t is None:
                t = self._takers[name] = [time.monotonic(), SpeedMeter()]
            t[0] = time.monotonic()
            return t

    def takers(self):
        """[(nazwa, prędkość)] graczy, którzy właśnie pobierają ode mnie."""
        now = time.monotonic()
        with self._lock:
            return sorted(((n, t[1].speed()) for n, t in self._takers.items() if now - t[0] < RECENT),
                          key=lambda x: -x[1])

    def remember(self, path, st, md5):
        """Plik właśnie pobrany i zweryfikowany – od razu można go dawać innym."""
        with self._lock:
            self._extra[os.path.abspath(path)] = (st.st_size, st.st_mtime_ns, md5)

    # ---------- co mam ----------

    def _known_hash(self, path, st):
        with self._lock:
            e = self._extra.get(path)
            if e and e[0] == st.st_size and e[1] == st.st_mtime_ns:
                return e[2]
            try:
                mtime = os.stat(CLIENT_CACHE).st_mtime_ns
            except OSError:
                mtime = None
            if self._cache is None or mtime != self._cache_mtime:
                self._cache, self._cache_mtime = HashCache(CLIENT_CACHE), mtime
            return self._cache.get(path, st)

    def local_file(self, rel, size, md5):
        """Ścieżka pliku, jeśli mam dokładnie tę wersję (rozmiar + MD5), inaczej None."""
        if not self.folder:
            return None
        try:
            path = os.path.abspath(safe_join(self.folder, mods_rel(rel)))
            st = os.stat(path)
        except (ValueError, OSError):
            return None
        if st.st_size != size or self._known_hash(path, st) != md5:
            return None
        return path


def _make_handler(peer):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        timeout = 60

        def setup(self):
            super().setup()
            try:
                self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except OSError:
                pass

        def log_message(self, *a):
            pass

        def _send(self, code, obj):
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _authorized(self):
            return not peer.auth or self.headers.get(HDR_AUTH, "") == peer.auth

        def do_POST(self):
            try:
                if not self._authorized():
                    return self._send(401, {"error": "auth"})
                if urlsplit(self.path).path != "/have":
                    return self._send(404, {"error": "?"})
                n = int(self.headers.get("Content-Length", "0"))
                if n > 32 * 1024 * 1024:
                    return self._send(413, {"error": "za duże"})
                items = json.loads(self.rfile.read(n) or b"[]")
                have = [it["rel"] for it in items if isinstance(it, dict)
                        and peer.local_file(str(it.get("rel", "")), int(it.get("size", -1)), it.get("hash"))]
                self._send(200, have)
            except (ValueError, KeyError, TypeError):
                self._send(400, {"error": "zły format"})
            except OSError:
                self.close_connection = True

        def do_GET(self):
            try:
                self._get()
            except OSError:
                self.close_connection = True

        def _get(self):
            if not self._authorized():
                return self._send(401, {"error": "auth"})
            url = urlsplit(self.path)
            path = unquote(url.path)
            if path == "/hello":
                return self._send(200, {"peer": True, "uploads": peer.uploads})
            if not path.startswith("/piece/"):
                return self._send(404, {"error": "?"})
            rel = path[len("/piece/"):]
            md5 = parse_qs(url.query).get("hash", [""])[0]
            m = re.match(r"bytes=(\d+)-(\d+)", (self.headers.get("Range") or "").strip())
            if not m:
                return self._send(416, {"error": "wymagany Range"})
            try:
                size = os.path.getsize(safe_join(peer.folder or "", mods_rel(rel)))
            except (ValueError, OSError):
                return self._send(404, {"error": "brak pliku"})
            fp = peer.local_file(rel, size, md5)
            if not fp:
                return self._send(404, {"error": "brak pliku"})
            start, end = int(m.group(1)), min(int(m.group(2)), size - 1)
            if start > end:
                return self._send(416, {"error": "zły zakres"})
            if not peer._slots.acquire(blocking=False):
                return self._send(503, {"error": "zajęty"})
            name = unquote(self.headers.get(HDR_CLIENT, "")) or self.client_address[0]
            try:
                peer.uploads += 1
                self._stream(fp, start, end, size, peer._taker(name))
            finally:
                peer.uploads -= 1
                peer._slots.release()

        def _stream(self, fp, start, end, size, taker):
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(end - start + 1))
            self.end_headers()
            self.wfile.flush()
            pos = start
            with open(fp, "rb") as f:
                while pos <= end and not peer._stop.is_set():
                    sent = self.connection.sendfile(f, pos, min(SEND_CHUNK, end - pos + 1))
                    if not sent:
                        break
                    pos += sent
                    peer.meter.add(sent)
                    taker[1].add(sent)
                    taker[0] = time.monotonic()
                    with peer._lock:
                        peer.bytes_up += sent
            if pos <= end:
                self.close_connection = True

    return Handler
