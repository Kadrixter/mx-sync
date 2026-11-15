"""Sesja libtorrent: udostępnianie wszystkich moich modów i pobieranie cudzych.

Torrenty są prywatne (bez DHT / LSD / wymiany peerów) – peerów podajemy sami: gracze znalezieni
przez MX Sync (LAN, Radmin VPN, dodani po IP). UPnP / NAT-PMP otwierają port na routerze,
co przyda się przy połączeniach przez internet.
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
    def __init__(self, on_finished=None):
        self.on_finished = on_finished      # (Transfer) po pobraniu i sprawdzeniu modu
        self.port = None
        self.seeds = {}                     # ih -> handle (moje mody)
        self.transfers = {}                 # ih -> Transfer (pobierane)
        self.down_rate = self.up_rate = 0
        self.uploading = {}                 # ip -> prędkość wysyłania (ostatni pomiar)
        self._lock = threading.RLock()
        settings = {
            "user_agent": f"MXSync/{VERSION}",
            "enable_dht": False, "enable_lsd": False,
            "enable_upnp": True, "enable_natpmp": True,
            "alert_mask": lt.alert_category.status | lt.alert_category.error | lt.alert_category.storage,
            "active_downloads": 8, "active_seeds": 50000, "active_limit": 50000,
            "connections_limit": 400,
            "allow_multiple_connections_per_ip": True,
            "ignore_limits_on_local_network": False,   # limity z ustawień działają też w LAN
            "close_redundant_connections": True,
        }
        self.port = _free_port(LT_PORT)
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
        for h in seeds + [t.handle for t in transfers]:
            if not h.is_valid():
                continue
            st = h.status()
            if st.upload_payload_rate <= 0:
                continue
            up += st.upload_payload_rate if h in seeds else 0
            for p in h.get_peer_info():
                if p.payload_up_speed > 0:
                    ip = p.ip[0]
                    uploading[ip] = uploading.get(ip, 0) + p.payload_up_speed
        self.down_rate, self.up_rate, self.uploading = down, up, uploading

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


def _free_port(start):
    """Pierwszy wolny port TCP i UDP od `start`.

    Windows pozwala kilku programom „otworzyć” ten sam port (SO_REUSEADDR) – wtedy połączenia
    przychodzące trafiają nie tam, gdzie trzeba. Sprawdzamy port na wyłączność, zanim dostanie go
    libtorrent; gdy wszystkie z zakresu są zajęte, system wybiera dowolny.
    """
    import socket
    exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
    for port in range(start, start + 20):
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
