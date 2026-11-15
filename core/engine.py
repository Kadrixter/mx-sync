"""Sesja libtorrent: udostępnianie wszystkich moich modów i pobieranie cudzych.

Torrenty są prywatne (bez DHT / LSD / wymiany peerów) – peerów podajemy sami: gracze znalezieni
przez MX Sync (LAN, Radmin VPN, dodani po IP, ich publiczne adresy). UPnP / NAT-PMP otwierają
port na routerze (połączenia bezpośrednie, patrz core/direct.py); filtr IP wpuszcza tylko graczy.
"""
import threading
import time

import libtorrent as lt

from utils.version import VERSION

LT_PORT = 50520             # TCP + UDP (uTP); kolejny wolny, jeśli zajęty


class Transfer:
    """Pobieranie jednego modu (dla GUI)."""
    __slots__ = ("key", "ih", "name", "kind", "size", "handle", "progress", "down", "up", "peers",
                 "state", "done", "error", "started", "replace")

    def __init__(self, key, ih, name, kind, size, handle, replace=False):
        self.key, self.ih, self.name, self.kind, self.size, self.handle = key, ih, name, kind, size, handle
        self.progress = 0.0
        self.down = self.up = 0
        self.peers = 0
        self.state = "czekam na graczy"
        self.done = False
        self.error = None
        self.started = time.monotonic()
        self.replace = replace          # podmiana mojej wersji modu

    @property
    def eta(self):
        left = self.size * (1 - self.progress)
        return left / self.down if self.down > 0 else None


STATES = {0: "czekam", 1: "sprawdzam pliki", 2: "pobieram dane", 3: "pobieram", 4: "gotowe",
          5: "udostępniam", 6: "przydzielam", 7: "sprawdzam pliki"}


class Engine:
    def __init__(self, on_finished=None, port=0, upnp=True):
        self.on_finished = on_finished      # (Transfer) po pobraniu i sprawdzeniu modu
        self.port = None
        self.mapped = {}                    # "TCP"/"UDP" -> port zewnętrzny otwarty przez UPnP / NAT-PMP
        self.external_port = None
        self.map_error = None
        self.map_started = time.monotonic()  # od kiedy czekamy na router (brak odpowiedzi = brak UPnP)
        self.peer_ips = set()               # IP, z którymi libtorrent ma teraz połączenia
        self.seeds = {}                     # ih -> handle (moje mody)
        self.transfers = {}                 # ih -> Transfer (pobierane)
        self.down_rate = self.up_rate = 0
        self.uploading = {}                 # ip -> prędkość wysyłania (ostatni pomiar)
        self._lock = threading.RLock()
        settings = {
            "user_agent": f"MXSync/{VERSION}",
            "enable_dht": False, "enable_lsd": False,
            "enable_upnp": bool(upnp), "enable_natpmp": bool(upnp),
            "alert_mask": (lt.alert_category.status | lt.alert_category.error | lt.alert_category.storage
                           | lt.alert_category.port_mapping),
            "active_downloads": 8, "active_seeds": 50000, "active_limit": 50000,
            "connections_limit": 400,
            "allow_multiple_connections_per_ip": True,
            "ignore_limits_on_local_network": False,   # limity z ustawień działają też w LAN
            "close_redundant_connections": True,
        }
        self.port = _free_port(port or LT_PORT, 1 if port else 20)
        self.ses = lt.session({**settings, "listen_interfaces": f"0.0.0.0:{self.port},[::]:{self.port}"})
        # libtorrent otwiera port w tle – czekamy, aż naprawdę słucha (port z systemu, gdy był 0)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if any(isinstance(a, lt.listen_succeeded_alert) for a in self.ses.pop_alerts()):
                break
            time.sleep(0.02)
        self.port = self.ses.listen_port() or self.port

    # ---------- moje mody ----------

    def seed(self, ih, raw, save_path):
        """Udostępnia mod, który mam (seed_mode – bez ponownego liczenia hashy)."""
        with self._lock:
            if ih in self.seeds or ih in self.transfers:
                return
            atp = lt.add_torrent_params()
            atp.ti = lt.torrent_info(lt.bdecode(raw))
            atp.save_path = save_path
            atp.flags = lt.torrent_flags.seed_mode     # bez auto_managed – zawsze aktywny
            self.seeds[ih] = self.ses.add_torrent(atp)

    def unseed(self, ih):
        with self._lock:
            h = self.seeds.pop(ih, None)
            if h is not None and h.is_valid():
                self.ses.remove_torrent(h)

    # ---------- pobieranie ----------

    def download(self, mod, raw, save_path, peers, replace=False):
        with self._lock:
            if mod.ih in self.transfers or mod.ih in self.seeds:
                return self.transfers.get(mod.ih)
            atp = lt.add_torrent_params()
            atp.ti = lt.torrent_info(lt.bdecode(raw))
            atp.save_path = save_path
            h = self.ses.add_torrent(atp)
            t = Transfer(mod.key, mod.ih, mod.name, mod.kind, mod.size, h, replace)
            self.transfers[mod.ih] = t
        self.connect(mod.ih, peers)
        return t

    def connect(self, ih, peers):
        """Łączy pobieranie z graczami (ci, którzy nie mają modu, po prostu odrzucą połączenie)."""
        t = self.transfers.get(ih)
        if not t or t.done or not t.handle.is_valid():
            return
        for ip, port in peers:
            try:
                t.handle.connect_peer((ip, int(port)))
            except (RuntimeError, ValueError):
                pass

    def connect_any(self, ih, endpoint):
        """Połączenie z adresem dla modu, który pobieram albo udostępniam (hole punching) -> 1/0."""
        with self._lock:
            t = self.transfers.get(ih)
            h = t.handle if t else self.seeds.get(ih)
        if h is None or not h.is_valid():
            return 0
        try:
            h.connect_peer((endpoint[0], int(endpoint[1])))     # domyślne flagi: uTP + holepunch
            return 1
        except (RuntimeError, ValueError):
            return 0

    def cancel(self, ih):
        with self._lock:
            t = self.transfers.pop(ih, None)
            if t and t.handle.is_valid():
                self.ses.remove_torrent(t.handle)

    def forget(self, ih):
        """Gotowy transfer znika z listy, a mod przechodzi do udostępnianych."""
        with self._lock:
            t = self.transfers.pop(ih, None)
            if t and t.handle.is_valid():
                self.seeds[ih] = t.handle

    def active(self):
        with self._lock:
            return list(self.transfers.values())

    # ---------- ustawienia ----------

    def set_limits(self, up_kbs, down_kbs):
        self.ses.apply_settings({"upload_rate_limit": int(up_kbs) * 1024,
                                 "download_rate_limit": int(down_kbs) * 1024})

    def set_upnp(self, on):
        if not on:
            self.mapped.clear()
            self.external_port = None
        self.map_error = None
        self.map_started = time.monotonic()
        self.ses.apply_settings({"enable_upnp": bool(on), "enable_natpmp": bool(on)})

    def set_filter(self, ips, nets, nets6):
        """Wpuszcza tylko podane IP i sieci (reszta internetu zablokowana)."""
        import ipaddress
        f = lt.ip_filter()
        f.add_rule("0.0.0.0", "255.255.255.255", 1)
        f.add_rule("::", "ffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff", 1)
        for net in (*nets, *nets6):
            n = ipaddress.ip_network(net)
            f.add_rule(str(n.network_address), str(n.broadcast_address), 0)
        for ip in ips:
            try:
                ipaddress.ip_address(ip)
                f.add_rule(ip, ip, 0)
            except (ValueError, RuntimeError):
                pass
        self.ses.set_ip_filter(f)

    def close(self):
        try:
            self.ses.pause()
        except RuntimeError:
            pass

    # ---------- odświeżanie (co ~0,5 s z wątku Node) ----------

    def poll(self):
        for a in self.ses.pop_alerts():
            if isinstance(a, lt.torrent_finished_alert):
                self._finished(a.handle)
            elif isinstance(a, (lt.file_error_alert, lt.torrent_error_alert)):
                self._failed(a.handle, a.message())
            elif isinstance(a, lt.portmap_alert):
                kind = "UPnP" if a.map_transport == lt.portmap_transport.upnp else "NAT-PMP"
                self.mapped[kind] = a.external_port
                self.external_port = a.external_port
                self.map_error = None
            elif isinstance(a, lt.portmap_error_alert):
                if not self.mapped:
                    self.map_error = _short_error(a.message())
        down = up = 0
        with self._lock:
            transfers = list(self.transfers.values())
            seeds = list(self.seeds.values())
        for t in transfers:
            if not t.handle.is_valid():
                continue
            st = t.handle.status()
            t.progress = 1.0 if t.done else st.progress
            t.down, t.up, t.peers = st.download_payload_rate, st.upload_payload_rate, st.num_peers
            if not t.done and not t.error:
                if st.flags & lt.torrent_flags.paused:
                    t.state = "w kolejce"           # libtorrent pobiera kilka modów naraz, reszta czeka
                elif st.num_peers or int(st.state) in (1, 7):
                    t.state = STATES.get(int(st.state), "?")
                else:
                    t.state = "czekam na graczy"
            down += t.down
            up += t.up
        uploading = {}
        peer_ips = set()
        for h in seeds + [t.handle for t in transfers]:
            if not h.is_valid():
                continue
            st = h.status()
            if st.num_peers <= 0:
                continue
            up += st.upload_payload_rate if h in seeds else 0
            for p in h.get_peer_info():
                ip = p.ip[0]
                peer_ips.add(ip)
                if p.payload_up_speed > 0:
                    uploading[ip] = uploading.get(ip, 0) + p.payload_up_speed
        self.down_rate, self.up_rate, self.uploading, self.peer_ips = down, up, uploading, peer_ips

    def _find(self, handle):
        with self._lock:
            for t in self.transfers.values():
                if t.handle == handle:
                    return t
        return None

    def _finished(self, handle):
        t = self._find(handle)
        if t and not t.done:
            t.done, t.progress, t.state = True, 1.0, "gotowe"
            if self.on_finished:
                self.on_finished(t)

    def _failed(self, handle, msg):
        t = self._find(handle)
        if t and not t.done:
            t.error = msg
            t.state = "błąd"


def _short_error(msg):
    """'upnp: ... : No such device' -> krótki powód dla GUI."""
    low = msg.lower()
    if "no router" in low or "no such device" in low or "not found" in low or "timed out" in low:
        return "router nie odpowiada na UPnP / NAT-PMP"
    if "conflict" in low or "in use" in low:
        return "port zajęty na routerze"
    return msg.split(":")[-1].strip()[:80] or "błąd UPnP"


def _free_port(start, count=20):
    """Pierwszy wolny port TCP i UDP od `start`.

    Windows pozwala kilku programom „otworzyć” ten sam port (SO_REUSEADDR) – wtedy połączenia
    przychodzące trafiają nie tam, gdzie trzeba. Sprawdzamy port na wyłączność, zanim dostanie go
    libtorrent; gdy wszystkie z zakresu są zajęte, system wybiera dowolny.
    """
    import socket
    exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
    for port in range(start, start + count):
        ok = True
        for kind in (socket.SOCK_STREAM, socket.SOCK_DGRAM):
            s = socket.socket(socket.AF_INET, kind)
            try:
                if exclusive is not None:
                    s.setsockopt(socket.SOL_SOCKET, exclusive, 1)
                s.bind(("0.0.0.0", port))
            except OSError:
                ok = False
            finally:
                s.close()
        if ok:
            return port
    return 0
