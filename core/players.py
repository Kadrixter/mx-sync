"""Inni gracze: kto jest online, pod jakim adresem i jakie ma mody.

Gracz pojawia się z wykrywania UDP albo z listy dodanych po IP. Wątek odświeżania co REFRESH s
pyta każdego o /hello; jeśli zmienił się numer wersji biblioteki (rev) – pobiera /library.
"""
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

import requests

from core.library import Mod
from core.protocol import HDR_AUTH, HDR_ID, HDR_NAME, HDR_PROTO, PROTO, make_proof, proto_of
from utils.netinfo import is_radmin_ip

REFRESH = 4.0
OFFLINE_AFTER = 15.0


class Player:
    def __init__(self, pid):
        self.id = pid
        self.name = "?"
        self.ip = None
        self.http = None
        self.lt = None
        self.addrs = {}             # ip -> http port (ten sam gracz w LAN i w Radminie)
        self.rev = -1
        self.mods = {}              # klucz -> Mod
        self.mod_count = 0
        self.size = 0
        self.protected = False
        self.nonce = ""
        self.state = "łączę"        # łączę / online / offline / hasło / stara wersja / nowsza wersja
        self.last_seen = 0.0
        self.manual = False
        self.gossip = False         # znany tylko z listy innego gracza (jeszcze niepotwierdzony)
        self.version = ""
        self.wan = None             # [publiczne ip, port] – połączenia bezpośrednie (core/direct.py)
        self.direct = False         # jest teraz połączenie bezpośrednie przez internet

    @property
    def online(self):
        return self.state == "online"

    @property
    def via(self):
        if not self.ip:
            return ""
        if self.ip.startswith("127."):
            return "ten komputer"
        if self.direct:
            return "bezpośrednio"
        return "Radmin VPN" if is_radmin_ip(self.ip) else ("LAN" if not self.manual else "internet")

    def base(self):
        return f"http://{self.ip}:{self.http}"


class Players:
    def __init__(self, me_id, password_fn, name_fn, on_change=None):
        self.me_id = me_id
        self.password_fn, self.name_fn = password_fn, name_fn
        self.on_change = on_change or (lambda: None)
        self._players = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._sess = requests.Session()
        self._pool = ThreadPoolExecutor(max_workers=8)
        self.gen = 0                # rośnie przy każdej zmianie (GUI odświeża listy)
        self._me_addrs = set()      # (ip, port), pod którymi odpowiadam ja – nie dodawać siebie

    def all(self):
        with self._lock:
            return list(self._players.values())

    def get(self, pid):
        with self._lock:
            return self._players.get(pid)

    def online(self):
        return [p for p in self.all() if p.online]

    def stop(self):
        self._stop.set()
        self._pool.shutdown(wait=False, cancel_futures=True)

    def start(self):
        threading.Thread(target=self._loop, daemon=True).start()

    # ---------- źródła graczy ----------

    def found(self, info, ip):
        """Z wykrywania UDP."""
        pid = str(info.get("id") or "")
        if not pid or pid == self.me_id:
            return
        with self._lock:
            p = self._players.get(pid)
            if p is None:
                p = self._players[pid] = Player(pid)
        p.name = str(info.get("name") or p.name)[:32]
        p.addrs[ip] = int(info.get("http") or info.get("port") or 0)
        p.last_seen = time.monotonic()
        if info.get("old"):
            p.ip, p.http = ip, p.addrs[ip]
            p.version = str(info.get("version") or "")[:16]
            self._set(p, _other_version(info))
            return
        if p.ip is None or _better(ip, p.ip):
            p.ip, p.http = ip, p.addrs[ip]

    def add_manual(self, ip, port):
        """Gracz dodany po IP – sprawdzany przez HTTP (UDP przez internet może nie dojść)."""
        pid = f"manual:{ip}:{port}"
        with self._lock:
            if pid not in self._players:
                p = self._players[pid] = Player(pid)
                p.ip, p.http, p.manual, p.name = ip, port, True, ip
        self._pool.submit(self._refresh, self._players[pid])

    def add_candidate(self, ip, port):
        """Gracz, o którym powiedział nam inny gracz („znajomi znajomych”) – sprawdzamy przez HTTP."""
        if (ip, port) in self._me_addrs:
            return
        with self._lock:
            if any(p.addrs.get(ip) == port or (p.ip == ip and p.http == port) for p in self._players.values()):
                return
            pid = f"cand:{ip}:{port}"
            if pid in self._players:
                return
            p = self._players[pid] = Player(pid)
            p.ip, p.http, p.gossip, p.name = ip, port, True, ip
        self._pool.submit(self._refresh, p)

    def known_addresses(self):
        """[[ip, port]] graczy online – przekazywane innym w /hello."""
        return [[p.ip, p.http] for p in self.online() if p.ip and p.http]

    # ---------- odświeżanie ----------

    def headers(self, p):
        h = {HDR_PROTO: str(PROTO), HDR_NAME: quote(self.name_fn()), HDR_ID: self.me_id}
        pw = self.password_fn()
        if pw and p.nonce:
            h[HDR_AUTH] = make_proof(pw, p.nonce)
        return h

    def _loop(self):
        while not self._stop.is_set():
            for p in self.all():
                if p.state not in OTHER_VERSION and p.ip:
                    self._pool.submit(self._refresh, p)
            self._stop.wait(REFRESH)

    def _set(self, p, state):
        if p.state != state:
            p.state = state
            self.gen += 1
            self.on_change()

    def _refresh(self, p):
        try:
            r = self._sess.get(p.base() + "/hello", headers=self.headers(p), timeout=(3, 6))
            info = r.json()
        except (requests.RequestException, ValueError):
            if p.gossip:
                with self._lock:
                    self._players.pop(p.id, None)  # nie da się połączyć – nie zaśmiecamy listy
                return
            if not p.manual and time.monotonic() - p.last_seen < OFFLINE_AFTER:
                return              # chwilowy problem – UDP jeszcze go widzi
            return self._set(p, "offline")
        if proto_of(info) != PROTO:
            p.version = str(info.get("version") or "")[:16]
            return self._set(p, _other_version(info))
        if info.get("id") == self.me_id:
            self._me_addrs.add((p.ip, p.http))
            with self._lock:
                self._players.pop(p.id, None)      # dodano po IP samego siebie
            return
        if (p.manual or p.gossip) and info.get("id"):
            self._merge_manual(p, info)
            p.gossip = False
        for ip, port in info.get("peers", [])[:64]:
            ip = p.ip if str(ip).startswith("127.") else str(ip)   # „localhost” u niego = jego adres
            self.add_candidate(ip, int(port))
        p.name = str(info.get("name") or p.name)[:32]
        p.lt, p.protected, p.nonce = int(info.get("lt") or 0), bool(info.get("protected")), info.get("nonce", "")
        p.mod_count, p.size, p.version = int(info.get("mods", 0)), int(info.get("size", 0)), info.get("version", "")
        p.wan = _wan(info.get("wan"))
        p.last_seen = time.monotonic()
        if int(info.get("rev", -1)) != p.rev:
            self._load_library(p)
        elif p.state != "hasło":
            self._set(p, "online")

    def _merge_manual(self, p, info):
        """Gracz dodany po IP okazał się tym samym, którego już widać z UDP – zostaje jeden."""
        with self._lock:
            other = self._players.get(info["id"])
            if other is not None and other is not p:
                other.addrs[p.ip] = p.http
                self._players.pop(p.id, None)
            else:
                self._players.pop(p.id, None)
                p.id = info["id"]
                self._players[p.id] = p

    def _load_library(self, p):
        try:
            r = self._sess.get(p.base() + "/library", headers=self.headers(p), timeout=(3, 30))
            if r.status_code == 401:
                return self._set(p, "hasło")
            r.raise_for_status()
            data = r.json()             # requests sam rozpakowuje gzip
        except (requests.RequestException, ValueError):
            return
        p.mods = {k: Mod.from_wire(k, v) for k, v in data.get("mods", {}).items()}
        p.rev = int(data.get("rev", 0))
        self.gen += 1
        self._set(p, "online")
        self.on_change()

    def request(self, p, path):
        """Zapytanie z hasłem grupy i moim id (/reach, /punch)."""
        return self._sess.get(p.base() + path, headers=self.headers(p), timeout=(3, 10))

    def fetch_torrent(self, p, ih):
        r = self._sess.get(f"{p.base()}/torrent/{ih}", headers=self.headers(p), timeout=(3, 20))
        r.raise_for_status()
        return r.content


def _wan(value):
    """["1.2.3.4", 50520] z /hello -> [ip, port] albo None (tylko poprawny publiczny adres)."""
    from core.direct import is_public
    try:
        ip, port = str(value[0]), int(value[1])
    except (TypeError, ValueError, IndexError, KeyError):
        return None
    return [ip, port] if is_public(ip) and 0 < port < 65536 else None


def _better(new, old):
    """Który adres tego samego gracza wolimy: LAN > Radmin > localhost."""
    def rank(ip):
        return 2 if ip.startswith("127.") else (1 if is_radmin_ip(ip) else 0)
    return rank(new) < rank(old)


OTHER_VERSION = ("stara wersja", "nowsza wersja")


def _other_version(info):
    """Inny protokół = żadnej wymiany modów; nowszy – to ja muszę zaktualizować."""
    return "nowsza wersja" if proto_of(info) > PROTO else "stara wersja"
