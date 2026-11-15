"""Połączenia bezpośrednie przez internet (jak w qBittorrent), a Radmin VPN / LAN jako zapas.

1. Port: libtorrent otwiera go na routerze przez UPnP / NAT-PMP (alerty czyta Engine).
2. Publiczne IP: z usługi HTTPS (ipify i zapasowe); adres WAN z routera służy do wykrycia CGNAT.
3. Wymiana: mój adres [ip, port] idzie w /hello tylko do graczy z tym samym hasłem grupy.
4. Test portu: inny gracz (przez Radmina) próbuje połączyć się z moim publicznym adresem (/reach).
5. Do gracza z otwartym portem łączymy się wprost. Gdy jego port jest zamknięty, prosimy go przez
   Radmina (/punch), żeby w tej samej chwili połączył się z nami – jednoczesne połączenie uTP
   przebija większość domowych NAT-ów (hole punching); Radmin zostaje jako zapas.
"""
import ipaddress
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests

from utils.netinfo import is_radmin_ip
from utils.upnp_wan import router_wan_ip

IP_SERVICES = ("https://api.ipify.org", "https://ipv4.icanhazip.com", "https://ifconfig.me/ip")
IP_REFRESH = 600.0          # co ile s sprawdzamy publiczne IP
REACH_EVERY = 60.0          # co ile s testujemy, czy porty innych graczy są otwarte
SELF_TEST_EVERY = 120.0     # co ile s prosimy kogoś o sprawdzenie mojego portu
PUNCH_EVERY = 20.0          # co ile s ponawiamy hole punching do jednego gracza (dłużej po porażkach)
PUNCH_GRACE = 6.0           # tyle s po hole punchingu nie dokładamy połączeń przez Radmina
DIRECT_TTL = 180.0          # tak długo pamiętamy, że bezpośrednie połączenie z graczem działało
CONNECT_TIMEOUT = 4.0
MAP_WAIT = 25.0             # po tylu s bez odpowiedzi routera uznajemy, że nie ma UPnP / NAT-PMP

# Zawsze dozwolone w filtrze IP: sieci lokalne i popularne VPN-y (Radmin 26/8, Hamachi 25/8, CGNAT/Tailscale)
ALLOWED_NETS = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8", "169.254.0.0/16",
                "26.0.0.0/8", "25.0.0.0/8", "100.64.0.0/10")
ALLOWED_NETS6 = ("::1/128", "fc00::/7", "fe80::/10")


def is_public(ip):
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return a.is_global and not is_radmin_ip(ip) and a not in ipaddress.ip_network("25.0.0.0/8")


def mask_ip(ip):
    """'83.24.115.7' -> 'xx.xx.xxx.x' (do pokazania w GUI, cyfry widać po najechaniu)."""
    return "".join("x" if c.isdigit() else c for c in ip or "")


class Direct:
    def __init__(self, node):
        self.node = node
        self.public_ip = None
        self.router_ip = None       # adres WAN routera (UPnP) – inny niż publiczne IP = CGNAT
        self.ip_error = None
        self.checked = None         # (otwarty: bool, nazwa gracza, godzina) – wynik testu przez innego gracza
        self.reach = {}             # id gracza -> True/False (czy jego publiczny port odpowiada)
        self._last_punch = {}       # id gracza -> czas ostatniego hole punchingu
        self._punch_fails = {}      # id gracza -> ile prób z rzędu bez połączenia
        self._direct_seen = {}      # id gracza -> kiedy ostatnio było z nim połączenie bezpośrednie
        self._filter_key = None
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._sess = requests.Session()

    @property
    def enabled(self):
        return bool(self.node.cfg.get("direct", True))

    # ---------- stan dla GUI ----------

    def wan(self):
        """[ip, port] widoczny z internetu albo None."""
        eng = self.node.engine
        if not self.enabled or not self.public_ip or not eng.port:
            return None
        return [self.public_ip, eng.external_port or eng.port]

    @property
    def cgnat(self):
        """Router ma adres WAN z puli prywatnej / CGNAT albo inny niż publiczne IP – port nie da się otworzyć."""
        rip = self.router_ip
        if not rip or not self.public_ip:
            return False
        return rip != self.public_ip

    def status(self):
        """(krótki tekst, długi opis, kolor: ok / warn / bad / off)."""
        eng = self.node.engine
        port = eng.external_port or eng.port
        if not self.enabled:
            return "tylko Radmin", "Połączenia bezpośrednie wyłączone – wszystko idzie przez Radmin VPN / LAN.", "off"
        if self.checked and self.checked[0]:
            return (f"port {port} otwarty", f"Port {port} otwarty – sprawdził {self.checked[1]} o {self.checked[2]}. "
                    "Inni gracze łączą się z tobą bezpośrednio.", "ok")
        if self.cgnat:
            return ("CGNAT", "Operator ma CGNAT albo jest podwójny router – portu nie da się otworzyć. "
                    "Próbuję hole punchingu, a w razie czego zostaje Radmin.", "bad")
        if eng.mapped:
            how = ", ".join(sorted(eng.mapped))
            if self.checked:
                return (f"port {port} zamknięty", f"Router zgłosił otwarcie portu ({how}), ale {self.checked[1]} "
                        "nie może się połączyć (zapora / drugi router). Próbuję hole punchingu.", "warn")
            return f"port {port} otwarty ({how})", f"Router otworzył port {port} ({how}). Czekam na test od innego gracza.", "ok"
        error = eng.map_error or ("router nie odpowiada na UPnP / NAT-PMP"
                                  if time.monotonic() - eng.map_started > MAP_WAIT else None)
        if error:
            return ("port zamknięty", f"Router nie otworzył portu ({error}). Włącz UPnP w routerze albo "
                    f"przekieruj port {eng.port} TCP+UDP ręcznie. Do tego czasu: hole punching i Radmin.", "warn")
        if self.checked:
            return f"port {port} zamknięty", f"{self.checked[1]} nie może połączyć się z twoim portem {port}. " \
                                             "Próbuję hole punchingu, w razie czego Radmin.", "warn"
        return "otwieram port…", f"Otwieram port {eng.port} na routerze (UPnP / NAT-PMP)…", "warn"

    # ---------- pętla ----------

    def start(self):
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self._stop.set()
        self._wake.set()

    def poke(self):
        self._wake.set()

    def toggled(self):
        """Zmieniono włącznik w ustawieniach."""
        self.node.engine.set_upnp(self.enabled)
        self.checked = None
        self.reach.clear()
        self._wake.set()

    def _loop(self):
        last_ip = last_reach = last_self = -1e9
        while not self._stop.is_set():
            now = time.monotonic()
            try:
                self._update_filter()
                if self.enabled:
                    if now - last_ip > IP_REFRESH or not self.public_ip and now - last_ip > 30:
                        last_ip = now
                        self._fetch_ip()
                    if now - last_reach > REACH_EVERY or self._wake.is_set():
                        last_reach = now
                        self._test_players()
                    if now - last_self > SELF_TEST_EVERY or (self.checked is None and now - last_self > 15):
                        if self._ask_test():
                            last_self = now
            except Exception:       # noqa: BLE001 – wątek tła nie może paść
                pass
            self._wake.clear()
            self._wake.wait(5.0)

    def _fetch_ip(self):
        try:
            self.router_ip = router_wan_ip()
        except Exception:       # noqa: BLE001 – dziwny router nie może zatrzymać reszty
            self.router_ip = None
        for url in IP_SERVICES:
            try:
                ip = self._sess.get(url, timeout=6).text.strip()
                ipaddress.IPv4Address(ip)
            except (requests.RequestException, ValueError):
                continue
            if ip != self.public_ip:
                self.public_ip = ip
                self.checked = None
            self.ip_error = None
            return
        self.ip_error = "nie udało się sprawdzić publicznego IP"

    # ---------- test portów ----------

    def _candidates(self):
        """Gracze online z publicznym adresem innym niż mój (ten sam adres = ta sama sieć, wystarczy LAN)."""
        return [p for p in self.node.players.online()
                if p.wan and p.wan[0] != self.public_ip and p.via != "LAN"]

    def _test_players(self):
        players = self._candidates()
        if players:
            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(lambda p: tcp_reachable(p.wan[0], p.wan[1]), players))
            for p, ok in zip(players, results):
                self.reach[p.id] = ok

    def _ask_test(self):
        """Prosi jednego gracza (spoza mojej sieci) o połączenie z moim publicznym portem."""
        wan = self.wan()
        if not wan:
            return False
        for p in self._candidates():
            try:
                r = self.node.players.request(p, "/reach")
                if r.status_code != 200:
                    continue
                ok = r.json().get("ok")
            except (requests.RequestException, ValueError):
                continue
            if ok is None:
                continue            # on jeszcze nie zna mojego adresu – spróbujemy później
            self.checked = (bool(ok), p.name, time.strftime("%H:%M"))
            return True
        return False

    def handle_reach(self, requester_id):
        """/reach – ktoś pyta, czy jego port jest otwarty. Łączymy się tylko z adresem z jego /hello."""
        p = self.node.players.get(requester_id)
        if not p or not p.wan:
            return {"ok": None, "error": "nie znam jeszcze twojego publicznego adresu"}
        return {"ok": tcp_reachable(p.wan[0], p.wan[1])}

    # ---------- łączenie ----------

    def endpoints(self, p):
        """Adresy, pod którymi łączymy się z graczem p: LAN > bezpośrednio > Radmin."""
        radmin = [(p.ip, p.lt)] if p.ip and p.lt else []
        if not self.enabled or not p.wan or p.via == "LAN" or p.wan[0] == self.public_ip:
            return radmin
        direct = [(p.wan[0], p.wan[1])]
        reach = self.reach.get(p.id)
        if reach or time.monotonic() - self._direct_seen.get(p.id, -1e9) < DIRECT_TTL:
            return direct
        if reach is None:
            return direct + radmin      # port jeszcze niesprawdzony – libtorrent odrzuci podwójne połączenie
        if time.monotonic() - self._last_punch.get(p.id, -1e9) < PUNCH_GRACE:
            return []                   # trwa hole punching – niech połączenie bezpośrednie zdąży pierwsze
        return radmin

    def observe(self, peer_ips):
        """Co kilka s: przy których graczach jest teraz połączenie bezpośrednie (do GUI i wyboru adresu)."""
        now = time.monotonic()
        for p in self.node.players.all():
            p.direct = bool(self.enabled and p.wan and p.wan[0] in peer_ips)
            if p.direct:
                self._direct_seen[p.id] = now
                self._punch_fails.pop(p.id, None)

    def punch(self, transfers):
        """Hole punching do graczy z zamkniętym portem, którzy mają moje pobierane mody."""
        if not self.enabled or not self.wan():
            return
        now = time.monotonic()
        for p in self._candidates():
            if self.reach.get(p.id) is not False or p.direct:
                continue
            wait = min(300.0, PUNCH_EVERY * (1 + self._punch_fails.get(p.id, 0)))
            if now - self._last_punch.get(p.id, -1e9) < wait:
                continue
            have = {m.ih for m in p.mods.values()}
            ihs = [t.ih for t in transfers if t.ih in have][:50]
            if not ihs:
                continue
            if p.id in self._last_punch:
                self._punch_fails[p.id] = self._punch_fails.get(p.id, 0) + 1
            self._last_punch[p.id] = now
            threading.Thread(target=self._punch_one, args=(p, ihs), daemon=True).start()

    def _punch_one(self, p, ihs):
        ep = (p.wan[0], p.wan[1])
        for ih in ihs:                  # ja łączę się z nim...
            self.node.engine.connect_any(ih, ep)
        try:                            # ...a on w tej samej chwili ze mną
            self.node.players.request(p, "/punch?ih=" + ",".join(ihs))
        except requests.RequestException:
            pass

    def handle_punch(self, requester_id, ihs):
        """/punch – gracz prosi, żebym połączył się z jego publicznym adresem (dla podanych modów)."""
        p = self.node.players.get(requester_id)
        if not self.enabled or not p or not p.wan:
            return {"ok": False}
        n = 0
        for ih in ihs[:50]:
            n += self.node.engine.connect_any(ih, (p.wan[0], p.wan[1]))
        return {"ok": True, "n": n}

    # ---------- filtr IP ----------

    def _update_filter(self):
        """Port wystawiony do internetu – przyjmujemy połączenia tylko od znanych graczy i sieci lokalnych."""
        ips = set()
        for p in self.node.players.all():
            ips.update(ip for ip in [p.ip, *p.addrs] if ip)
            if p.wan:
                ips.add(p.wan[0])
        for entry in self.node.cfg.get("manual_peers") or []:
            ips.add(entry.split(":")[0])
        key = frozenset(ips)
        if key != self._filter_key:
            self._filter_key = key
            self.node.engine.set_filter(sorted(ips), ALLOWED_NETS, ALLOWED_NETS6)


def tcp_reachable(ip, port):
    try:
        with socket.create_connection((ip, int(port)), timeout=CONNECT_TIMEOUT):
            return True
    except (OSError, ValueError):
        return False
