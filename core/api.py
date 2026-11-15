"""Serwer HTTP gracza: kim jestem, jakie mam mody i ich pliki .torrent (patrz core/protocol.py)."""
import gzip
import json
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit

from core.protocol import HDR_AUTH, HDR_PROTO, HTTP_PORT, MAGIC, PROTO, make_proof


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 32
    allow_reuse_address = sys.platform != "win32"


class ApiServer:
    """node: obiekt z hello(), library_wire(), torrent_bytes(ih), password, on_show()."""

    def __init__(self, node):
        self.node = node
        self.port = None
        self._httpd = None

    def start(self):
        last = None
        for port in range(HTTP_PORT, HTTP_PORT + 20):
            try:
                self._httpd = _Server(("", port), _handler(self.node))
                self.port = port
                break
            except OSError as e:
                last = e
        if not self._httpd:
            raise OSError(f"Nie można otworzyć portu HTTP {HTTP_PORT}: {last}")
        threading.Thread(target=self._httpd.serve_forever, kwargs={"poll_interval": 0.3}, daemon=True).start()
        return self.port

    def stop(self):
        httpd, self._httpd = self._httpd, None
        if httpd:
            threading.Thread(target=lambda: (httpd.shutdown(), httpd.server_close()), daemon=True).start()


def _handler(node):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        timeout = 30

        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="application/json; charset=utf-8", gz=False):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            if gz:
                self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code=200):
            self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

        def _authorized(self):
            if self.headers.get(HDR_PROTO) != str(PROTO):
                return False
            pw = node.password
            return not pw or self.headers.get(HDR_AUTH, "") == make_proof(pw, node.nonce)

        def do_GET(self):
            try:
                self._route()
            except (ConnectionError, OSError):
                self.close_connection = True

        def _route(self):
            path = unquote(urlsplit(self.path).path)
            if path == "/hello":
                return self._json(node.hello())
            if path == "/show":
                if self.client_address[0] != "127.0.0.1":
                    return self._json({"error": "?"}, 403)
                node.on_show()
                return self._json({"ok": True, "magic": MAGIC})
            if not self._authorized():
                return self._json({"error": "Inne hasło grupy albo stara wersja MX Sync"}, 401)
            if path == "/library":
                body = gzip.compress(json.dumps(node.library_wire()).encode("utf-8"), 5)
                return self._send(200, body, gz=True)
            m = re.fullmatch(r"/torrent/([0-9a-f]{64})", path)
            if m:
                raw = node.torrent_bytes(m.group(1))
                if raw is None:
                    return self._json({"error": "brak"}, 404)
                return self._send(200, raw, "application/x-bittorrent")
            self._json({"error": "?"}, 404)

    return Handler
