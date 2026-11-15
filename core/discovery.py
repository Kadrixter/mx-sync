"""Wykrywanie graczy przez UDP (LAN i Radmin VPN) – jedno gniazdo do pytania i odpowiadania.

Co INTERVAL s wysyłamy b"MXSYNC3?" + swoje dane na broadcast każdego interfejsu i na IP
graczy dodanych ręcznie. Kto dostanie pytanie, zapisuje pytającego i odpowiada swoimi danymi –
dzięki temu nowy gracz widzi innych (i oni jego) w ciągu sekund.
"""
import json
import socket
import threading
import time

from core.protocol import DISCOVERY_PORT, MAGIC, OLD_QUERY, QUERY, proto_of
from utils.netinfo import interfaces

INTERVAL = 3.0


class Beacon(threading.Thread):
    def __init__(self, hello_fn, on_found, manual_fn=lambda: ()):
        """hello_fn() -> dict o mnie; on_found(info, ip) dla każdego innego gracza;
        manual_fn() -> IP dodane ręcznie."""
        super().__init__(daemon=True)
        self.hello_fn, self.on_found, self.manual_fn = hello_fn, on_found, manual_fn
        self.error = None
        self._stop = threading.Event()
        self._wake = threading.Event()

    def stop(self):
        self._stop.set()

    def poke(self):
        """Zapytaj od razu (np. po dodaniu gracza po IP)."""
        self._wake.set()

    def run(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        try:
            s.bind(("", DISCOVERY_PORT))
        except OSError as e:
            # port zajęty (np. stara wersja MX Sync) – pytamy z losowego portu, odpowiedzi i tak dojdą
            self.error = f"Port UDP {DISCOVERY_PORT} zajęty: {e}"
            s.bind(("", 0))
        s.settimeout(0.3)
        next_query = 0.0
        while not self._stop.is_set():
            now = time.monotonic()
            if now >= next_query or self._wake.is_set():
                self._wake.clear()
                self._query(s)
                next_query = now + INTERVAL
            try:
                data, addr = s.recvfrom(65536)
            except (socket.timeout, OSError):
                continue            # Windows zgłasza ICMP „port unreachable” jako błąd recvfrom
            self._handle(s, data, addr)
        s.close()

    def _me(self):
        return json.dumps(self.hello_fn()).encode("utf-8")

    def _query(self, s):
        msg = QUERY + self._me()
        targets = {"127.0.0.1", "255.255.255.255"} | {i["broadcast"] for i in interfaces()}
        targets |= set(self.manual_fn())
        for ip in targets:
            for port in {DISCOVERY_PORT, s.getsockname()[1]}:
                try:
                    s.sendto(msg, (ip, port))
                except OSError:
                    pass

    def _handle(self, s, data, addr):
        if data.strip() == OLD_QUERY or (data.startswith(b"MXSYNC") and not data.startswith(QUERY)
                                         and b"?" in data[:10]):
            # inna wersja – niech zobaczy, że trzeba zaktualizować (bez dalszej wymiany)
            try:
                s.sendto(self._me(), addr)
            except OSError:
                pass
            return
        if data.startswith(QUERY):
            self._found(data[len(QUERY):], addr[0])
            try:
                s.sendto(self._me(), addr)
            except OSError:
                pass
            return
        self._found(data, addr[0])

    def _found(self, raw, ip):
        try:
            info = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return
        if isinstance(info, dict) and str(info.get("magic", "")).startswith("MXSYNC"):
            info["old"] = info.get("magic") != MAGIC
            info["proto"] = proto_of(info)
            self.on_found(info, ip)
