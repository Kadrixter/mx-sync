"""Tryb klienta: lista hostów -> sprawdzenie modów -> pobieranie brakujących."""
import math
import os
import threading
from tkinter import filedialog

import customtkinter as ctk

from gui import theme as T
from gui.base import View
from gui.widgets import AnimatedProgressBar, PasswordDialog, SelectableList
from net.client import AuthError, CheckJob, DownloadJob, HostConnection, PasswordRequired
from net.discovery import DiscoveryScanner
from net.protocol import parse_address
from utils import config
from utils.config import CLIENT_CACHE
from utils.files import find_mx_mods_folder, resolve_mods_root
from utils.fmt import fmt_eta, fmt_size, fmt_speed, plural_files
from utils.hashing import HashCache
from utils.netinfo import is_radmin_ip, radmin_available

MAX_FILE_ROWS = 300
MAX_MOD_ROWS = 400
KIND_ICONS = {"Mapa": "🏁", "Motor": "🏍", "Rider": "🪖", "Opony": "◎", "Inne": "📦", "Mod": "📦"}
STATUS_BADGES = {"brakuje": ("BRAKUJE", T.ORANGE), "nieaktualny": ("NIEAKTUALNY", T.YELLOW),
                 "aktualny": ("✔ AKTUALNY", T.GREEN)}


def _badges(master, host):
    if host.get("radmin"):
        ctk.CTkLabel(master, text="[Radmin VPN host]", font=T.font(12, "bold"),
                     text_color=T.CYAN).pack(side="left", padx=6)
    if host.get("protected"):
        ctk.CTkLabel(master, text="[🔒 z hasłem]", font=T.font(12, "bold"),
                     text_color=T.YELLOW).pack(side="left", padx=6)


class ClientServersView(View):
    def __init__(self, app):
        super().__init__(app)
        self.header("Tryb klienta", "Wyszukiwanie hostów z modami w sieci lokalnej", back=self._back)
        self._busy = False
        self._sig = None
        self._dots = 0

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=20)
        self.status = ctk.CTkLabel(top, text="Szukam hostów", font=T.font(14, "bold"),
                                   text_color=T.ACCENT, anchor="w")
        self.status.pack(side="left")
        rad = radmin_available()
        ctk.CTkLabel(top, text="Radmin VPN: wykryto – szukam też w sieci Radmin" if rad
                     else "Radmin VPN: nie wykryto", font=T.font(12),
                     text_color=T.CYAN if rad else T.MUTED).pack(side="right")

        self.box = ctk.CTkScrollableFrame(self, fg_color=T.PANEL, corner_radius=10)
        self.box.pack(fill="both", expand=True, padx=20, pady=8)
        self.empty = ctk.CTkLabel(self.box, text="Nie znaleziono jeszcze żadnego hosta…\n"
                                  "Upewnij się, że host działa i zapora Windows go nie blokuje.",
                                  text_color=T.MUTED, font=T.font(13))
        self.empty.pack(pady=40)

        foot = ctk.CTkFrame(self, fg_color=T.PANEL, corner_radius=10)
        foot.pack(fill="x", padx=20, pady=(0, 16))
        ctk.CTkLabel(foot, text="Nie widzisz hosta? Połącz po IP:", text_color=T.MUTED,
                     font=T.font(12)).pack(side="left", padx=(12, 6), pady=12)
        self.ip_entry = ctk.CTkEntry(foot, width=200, height=34, placeholder_text="np. 26.10.20.30:8888")
        last = config.load().get("last_ip")
        if last:
            self.ip_entry.insert(0, last)
        self.ip_entry.pack(side="left", padx=6)
        self.ip_entry.bind("<Return>", lambda e: self._manual())
        T.button(foot, "Połącz", self._manual, kind="primary", width=100).pack(side="left", padx=6)

        self.scanner = DiscoveryScanner()
        self.scanner.start()
        self._poll_job = None
        self._poll()

    def _back(self):
        from gui.start_view import StartView
        self.app.show(StartView)

    def _poll(self):
        if not self._busy:
            self._dots = (self._dots + 1) % 4
            self.status.configure(text="Szukam hostów" + "." * self._dots, text_color=T.ACCENT)
        hosts = self.scanner.get_hosts()
        sig = tuple((h["key"], h["name"], h["ip"], h["port"], h["protected"], h["files"], h["scanning"])
                    for h in hosts)
        if sig != self._sig:
            self._sig = sig
            self._render(hosts)
        self._poll_job = self.after(500, self._poll)

    def _render(self, hosts):
        for w in self.box.winfo_children():
            if w is not self.empty:
                w.destroy()
        if not hosts:
            self.empty.pack(pady=40)
            return
        self.empty.pack_forget()
        for h in hosts:
            card = ctk.CTkFrame(self.box, fg_color=T.ROW, corner_radius=10)
            card.pack(fill="x", padx=6, pady=4)
            line = ctk.CTkFrame(card, fg_color="transparent")
            line.pack(side="left", fill="x", expand=True, padx=12, pady=10)
            name = ctk.CTkLabel(line, text=f"🖥  {h['name']}", font=T.font(15, "bold"), text_color=T.TEXT)
            name.pack(side="left")
            _badges(line, h)
            addr = ctk.CTkLabel(line, text=f"{h['ip']}:{h['port']}", font=T.font(12), text_color=T.MUTED)
            addr.pack(side="left", padx=10)
            mods = "skanuje mody…" if h["scanning"] else f"{plural_files(h['files'])}  •  {fmt_size(h['size'])}"
            info = ctk.CTkLabel(line, text=mods, font=T.font(12),
                                text_color=T.YELLOW if h["scanning"] else T.MUTED)
            info.pack(side="left", padx=6)
            T.button(card, "Połącz  →", lambda h=h: self._connect(h), kind="primary",
                     width=110).pack(side="right", padx=12)
            for w in (card, line, name, addr, info):
                w.bind("<Button-1>", lambda e, h=h: self._connect(h))

    def _manual(self):
        text = self.ip_entry.get().strip()
        if not text:
            return
        try:
            ip, port = parse_address(text)
        except ValueError:
            self.status.configure(text="Nieprawidłowy port", text_color=T.RED)
            return
        config.update(last_ip=text)
        self.scanner.add_manual(ip)
        self._connect({"name": ip, "ip": ip, "port": port, "protected": False,
                       "radmin": is_radmin_ip(ip)})

    def _connect(self, host, password=None):
        if self._busy:
            return
        self._busy = True
        self.status.configure(text=f"Łączenie z {host['name']}…", text_color=T.YELLOW)
        result = {}

        def work():
            try:
                result["ok"] = HostConnection(host["ip"], host["port"], password)
            except PasswordRequired:
                result["pw"] = True
            except AuthError as e:
                result["auth"] = str(e)
            except (OSError, ValueError) as e:
                result["err"] = str(e) or e.__class__.__name__

        def wait():
            if not result:
                self.after(100, wait)
                return
            self._busy = False
            if "ok" in result:
                conn = result["ok"]
                host["name"] = conn.host_name or host["name"]
                host["protected"] = conn.protected
                self.app.show(ClientSyncView, conn=conn, host=host)
            elif "pw" in result or "auth" in result:
                pw = PasswordDialog.ask(self, "Hasło", f"Host „{host['name']}” wymaga hasła",
                                        error=result.get("auth"))
                if pw is not None:
                    self._connect(host, pw)
            else:
                self.status.configure(text=f"Nie udało się połączyć: {T.shorten(result['err'], 90)}",
                                      text_color=T.RED)

        threading.Thread(target=work, daemon=True).start()
        wait()

    def cleanup(self):
        if self._poll_job:
            self.after_cancel(self._poll_job)
        self.scanner.stop()


class ClientSyncView(View):
    """Porównanie lokalnego folderu modów z hostem i wybór, co pobrać."""

    def __init__(self, app, conn, host):
        super().__init__(app)
        self.conn = conn
        self.host = host
        cfg = config.load()
        folder = resolve_mods_root(cfg.get("client_folder") or find_mx_mods_folder())
        if not (folder and os.path.isdir(folder)):
            folder = find_mx_mods_folder()          # zapamiętany folder zniknął -> domyślny
        self.folder = folder if folder and os.path.isdir(folder) else None
        self.job = None
        self.mods = []               # ModGroup z ostatniego sprawdzenia
        self.sel = set()             # klucze zaznaczonych modów
        self.show_all = False
        self._poll_job = None

        bar = self.header(f"Mody hosta „{host['name']}”", f"{host['ip']}:{host['port']}", back=self._back)
        badges = ctk.CTkFrame(bar, fg_color="transparent")
        badges.pack(side="right")
        _badges(badges, host)
        if not host.get("protected"):
            ctk.CTkLabel(badges, text="[bez hasła]", font=T.font(12), text_color=T.MUTED).pack(side="left", padx=6)

        tools = ctk.CTkFrame(self, fg_color="transparent")
        tools.pack(fill="x", padx=20, pady=(0, 6))
        self.path_lbl = ctk.CTkLabel(tools, text="", text_color=T.MUTED, font=T.font(12), anchor="w")
        self.path_lbl.pack(side="left", fill="x", expand=True)
        T.button(tools, "Wyczyść cache", self._clear_cache, width=120).pack(side="right", padx=3)
        self.par_var = ctk.StringVar(value=str(cfg.get("parallel", 3)))
        ctk.CTkOptionMenu(tools, values=[str(i) for i in range(1, 9)], variable=self.par_var, width=64,
                          height=34, fg_color=T.ROW, button_color=T.ROW, button_hover_color=T.ROW_HOVER,
                          dropdown_fg_color=T.PANEL, font=T.font(13)).pack(side="right", padx=(3, 8))
        ctk.CTkLabel(tools, text="Równolegle:", text_color=T.MUTED, font=T.font(12)).pack(side="right", padx=3)
        T.button(tools, "Zmień folder", self._choose_folder, width=110).pack(side="right", padx=3)

        card = ctk.CTkFrame(self, fg_color=T.PANEL, corner_radius=12)
        card.pack(fill="x", padx=20, pady=(0, 6))
        top = ctk.CTkFrame(card, fg_color="transparent")
        top.pack(fill="x", padx=16, pady=(12, 2))
        self.state_lbl = ctk.CTkLabel(top, text="", font=T.font(16, "bold"), text_color=T.TEXT, anchor="w")
        self.state_lbl.pack(side="left")
        self.speed_lbl = ctk.CTkLabel(top, text="", font=T.font(14, "bold"), text_color=T.ACCENT)
        self.speed_lbl.pack(side="right")
        self.bar = AnimatedProgressBar(card, height=14, bg=T.PANEL)
        self.bar.pack(fill="x", padx=16, pady=6)
        self.stats_lbl = ctk.CTkLabel(card, text="", font=T.font(12), text_color=T.MUTED, anchor="w")
        self.stats_lbl.pack(fill="x", padx=16, pady=(0, 12))

        self.filter = ctk.CTkSegmentedButton(self, values=["Do pobrania", "Wszystkie mody hosta"],
                                             command=self._set_filter, font=T.font(12, "bold"),
                                             selected_color=T.ACCENT, selected_hover_color=T.ACCENT_HOVER,
                                             unselected_color=T.ROW, unselected_hover_color=T.ROW_HOVER,
                                             fg_color=T.PANEL, text_color=T.TEXT, height=30)
        self.filter.set("Do pobrania")

        self.list_holder = ctk.CTkFrame(self, fg_color="transparent")
        self.list_holder.pack(fill="both", expand=True, padx=20, pady=4)
        self.list = None
        self._more_lbl = None
        self._new_list(True, "")

        foot = ctk.CTkFrame(self, fg_color=T.PANEL, corner_radius=10)
        foot.pack(fill="x", padx=20, pady=(6, 16))
        self.summary = ctk.CTkLabel(foot, text="", font=T.font(13), text_color=T.TEXT)
        self.summary.pack(side="left", padx=14, pady=12)
        self.dl_btn = T.button(foot, "⬇  Pobierz zaznaczone", self._download, kind="primary", width=210, height=40)
        self.check_btn = T.button(foot, "⟳ Sprawdź ponownie", self._start_check, width=160, height=40)
        self.check_btn.pack(side="right", padx=(4, 12), pady=10)
        self.sel_btn = T.button(foot, "Zaznacz wszystko", self._toggle_all, width=130, height=40)

        if self.folder:
            self._show_folder()
            self._start_check()
        else:
            self.state_lbl.configure(text="Nie znaleziono folderu modów MX Bikes", text_color=T.YELLOW)
            self.list.set_empty_text("Wybierz folder z modami (Dokumenty\\PiBoSo\\MX Bikes\\mods)")
            self.after(200, self._choose_folder)

    # ----- ustawienia -----

    def _show_folder(self):
        self.path_lbl.configure(text=f"📂 {T.shorten(self.folder, 60)}")

    def _choose_folder(self):
        if self.job and self.job.phase != "done":
            return
        d = filedialog.askdirectory(parent=self, title="Wybierz folder z modami MX Bikes",
                                    initialdir=self.folder or os.path.expanduser("~/Documents"))
        if d:
            # 'MX Bikes' albo 'mods\tracks' -> właściwy folder mods (tam, gdzie gra szuka modów)
            self.folder = resolve_mods_root(os.path.normpath(d))
            config.update(client_folder=self.folder)
            self._show_folder()
            self._start_check()

    def _clear_cache(self):
        if self.job and self.job.phase != "done":
            return
        HashCache(CLIENT_CACHE).clear()
        self.stats_lbl.configure(text="Cache wyczyszczony – następne sprawdzanie policzy wszystkie hashe od nowa.")

    def _parallel(self):
        try:
            return max(1, min(8, int(self.par_var.get())))
        except ValueError:
            return 3

    # ----- lista modów hosta -----

    def _new_list(self, checkable, empty_text):
        if self.list is None:
            self.list = SelectableList(self.list_holder, on_change=self._list_changed)
            self.list.pack(fill="both", expand=True)
        if self._more_lbl:
            self._more_lbl.destroy()
            self._more_lbl = None
        self.list.clear(empty_text)
        self.list.checkable = checkable

    def _needed(self):
        return [g for g in self.mods if g.todo]

    def _set_filter(self, value):
        self.show_all = value != "Do pobrania"
        self._fill_list()

    def _fill_list(self):
        mods = self.mods if self.show_all else self._needed()
        self._new_list(True, "Nie ma nic do pobrania 🎉" if not self.show_all else "Host nic nie udostępnia")
        for g in mods[:MAX_MOD_ROWS]:
            badge, color = STATUS_BADGES[g.status]
            if g.status == "nieaktualny":
                badge += f" · {plural_files(len(g.todo))} z {g.files}"
            sub = g.kind + (f"  •  {g.path}" if g.path else "")
            self.list.add(g.key, g.name, True, size=g.todo_size if g.todo else g.size,
                          checked=g.key in self.sel, badge=badge, badge_color=color,
                          icon=KIND_ICONS.get(g.kind, "📦"), enabled=bool(g.todo), sub=sub)
        if len(mods) > MAX_MOD_ROWS:
            rest = mods[MAX_MOD_ROWS:]
            chosen = sum(1 for g in rest if g.key in self.sel)
            self._more_lbl = ctk.CTkLabel(self.list, text=f"… i jeszcze {len(rest)} modów "
                                                          f"(zaznaczone z nich: {chosen})",
                                          text_color=T.MUTED)
            self._more_lbl.pack(pady=6)
        self._update()

    def _list_changed(self):
        chosen = set(self.list.selected())
        for k in self.list.keys():
            if k in chosen:
                self.sel.add(k)
            else:
                self.sel.discard(k)
        self._update()

    def _toggle_all(self):
        needed = {g.key for g in self._needed()}
        if self.sel >= needed:
            self.sel.clear()
        else:
            self.sel |= needed
        self.list.set_all(bool(self.sel))

    def _chosen(self):
        return [f for g in self.mods if g.key in self.sel for f in g.todo]

    def _update(self):
        needed = self._needed()
        if not needed:
            return
        files = self._chosen()
        mods = sum(1 for g in needed if g.key in self.sel)
        size = sum(f.size for f in files)
        self.dl_btn.configure(text=f"⬇  Pobierz zaznaczone ({mods})",
                              state="normal" if files else "disabled")
        self.sel_btn.configure(text="Odznacz wszystko" if mods == len(needed) else "Zaznacz wszystko")
        self.summary.configure(text=f"Zaznaczono {mods} z {len(needed)} modów  •  "
                                    f"{plural_files(len(files))}  •  {fmt_size(size)}" if files
                               else "Zaznacz mody, które chcesz pobrać")

    # ----- sprawdzanie -----

    def _start_check(self):
        if not self.folder or (self.job and self.job.phase != "done"):
            return
        self.mods = []
        self.sel = set()
        self.dl_btn.pack_forget()
        self.sel_btn.pack_forget()
        self.filter.pack_forget()
        self.check_btn.configure(text="Anuluj", command=self._cancel_check)
        self.summary.configure(text="")
        self._new_list(True, "Sprawdzam mody…")
        self.bar.set_color(None)
        self.bar.set_indeterminate()
        self.job = CheckJob(self.conn, self.folder)
        self.job.start()
        self._poll()

    def _cancel_check(self):
        if self.job:
            self.job.cancel()
            self.check_btn.configure(state="disabled", text="Anulowanie…")

    def _poll(self):
        job = self.job
        if job.phase == "host":
            if job.host_total:
                self.bar.set(job.host_done / job.host_total)
                self.state_lbl.configure(text=f"Host skanuje mody…  {job.host_done / job.host_total * 100:.0f}%",
                                         text_color=T.YELLOW)
                self.stats_lbl.configure(text=f"{job.host_done} / {job.host_total} plików  •  czekam na koniec skanu hosta")
            else:
                self.state_lbl.configure(text="Pobieram listę modów z hosta…", text_color=T.YELLOW)
        elif job.phase == "check":
            total, done = job.bytes_total, job.bytes_done
            speed = job.meter.speed()
            frac = done / total if total else 1.0
            self.bar.set(frac)
            self.state_lbl.configure(text=f"Sprawdzam lokalne mody…  {frac * 100:.0f}%", text_color=T.TEXT)
            self.speed_lbl.configure(text=fmt_speed(speed) if total else "")
            eta = (total - done) / speed if speed > 1 else None
            cur = f"  •  {T.shorten(job.current[0].replace(chr(92), '/'), 50)}" if job.current else ""
            self.stats_lbl.configure(text=f"{job.files_done} / {job.files_total} plików do zhashowania  •  "
                                          f"{fmt_size(done)} / {fmt_size(total)}  •  z cache: {job.cached}  •  "
                                          f"pozostało: {fmt_eta(eta)}{cur}")
        else:
            self._check_done()
            return
        self._poll_job = self.after(200, self._poll)

    def _check_done(self):
        job = self.job
        self._poll_job = None
        self.speed_lbl.configure(text="")
        self.check_btn.configure(state="normal", text="⟳ Sprawdź ponownie", command=self._start_check)
        if job.error or job.cancelled:
            msg = "Anulowano sprawdzanie" if job.cancelled else f"Błąd: {job.error}"
            self.state_lbl.configure(text=msg, text_color=T.YELLOW if job.cancelled else T.RED)
            self.bar.set(0 if job.cancelled else 1.0)
            self.bar.set_color(T.YELLOW if job.cancelled else T.RED)
            self.stats_lbl.configure(text="Policzone hashe są zapisane – następne sprawdzanie będzie szybsze.")
            self.list.set_empty_text("")
            self.conn.set_state("połączony")
            return

        total = sum(v["size"] for v in job.index.values())
        self.mods = job.mods
        needed = self._needed()
        self.bar.set(1.0)
        self.stats_lbl.configure(text=f"Host udostępnia {len(self.mods)} modów ({plural_files(len(job.index))}, "
                                      f"{fmt_size(total)})   •   aktualne: {len(self.mods) - len(needed)}   •   "
                                      f"sprawdzono w {job.duration:.1f} s")
        self.filter.pack(fill="x", padx=20, pady=(2, 0), before=self.list_holder)
        if not needed:
            self.bar.set_color(T.GREEN)
            self.state_lbl.configure(text="✔ Masz wszystkie mody hosta – wszystko aktualne", text_color=T.GREEN)
            self.summary.configure(text="")
            self.filter.set("Wszystkie mody hosta")
            self._set_filter("Wszystkie mody hosta")
            self.conn.set_state("aktualny", 0)
            return

        missing = sum(1 for g in needed if g.status == "brakuje")
        size = sum(g.todo_size for g in needed)
        self.sel = {g.key for g in needed}
        self.bar.set_color(T.YELLOW)
        self.state_lbl.configure(text=f"Brakuje {missing}, nieaktualne {len(needed) - missing}  •  "
                                      f"{fmt_size(size)} do pobrania", text_color=T.YELLOW)
        self.dl_btn.pack(side="right", padx=4, pady=10, before=self.check_btn)
        self.sel_btn.pack(side="right", padx=4, pady=10, after=self.check_btn)
        self.filter.set("Do pobrania")
        self._set_filter("Do pobrania")
        self.conn.set_state("czeka na pobieranie", size)

    def _download(self):
        files = self._chosen()
        if not files:
            return
        par = self._parallel()
        config.update(parallel=par, client_folder=self.folder)
        self.app.show(ClientDownloadView, conn=self.conn, host=self.host, folder=self.folder,
                      files=files, parallel=par)

    def _back(self):
        self.conn.close()
        self.app.show(ClientServersView)

    def cleanup(self):
        if self._poll_job:
            self.after_cancel(self._poll_job)
        if self.job and self.job.phase != "done":
            self.job.cancel()


class ClientDownloadView(View):
    STATUS_COLORS = {"gotowe": T.GREEN, "pobieranie": T.ACCENT, "błąd": T.RED,
                     "ponawiam…": T.YELLOW, "przerwano": T.YELLOW}

    def __init__(self, app, conn, host, folder, files, parallel, intro=True):
        super().__init__(app)
        self.conn = conn
        self.host = host
        self.folder = folder
        self.files = files
        self.parallel = parallel
        for f in files:
            f.done = 0
            f.status = f.reason
        self.job = DownloadJob(conn, folder, files, parallel)
        self.job.start()
        self._poll_job = None
        self._anim_job = None
        self._intro_job = None
        self._done_shown = False
        if intro:
            self._show_intro()
        else:
            self._show_main()

    # ----- animacja „Pobieram X…” (3 s) -----

    def _show_intro(self):
        self.intro = ctk.CTkFrame(self, fg_color="transparent")
        self.intro.place(relx=0.5, rely=0.5, anchor="center")
        self.intro_lbl = ctk.CTkLabel(self.intro, text="", font=T.font(28, "bold"), text_color=T.TEXT)
        self.intro_lbl.pack()
        ctk.CTkLabel(self.intro, text=f"{plural_files(len(self.files))} z „{self.host['name']}”",
                     font=T.font(13), text_color=T.MUTED).pack(pady=(6, 18))
        self.intro_bar = AnimatedProgressBar(self.intro, height=10, bg=T.BG, width=380)
        self.intro_bar.set_indeterminate()
        self.intro_bar.pack()
        self._anim_t = 0
        self._animate_intro()
        self._intro_job = self.after(3000, self._show_main)

    def _animate_intro(self):
        self._anim_t += 1
        t = self._anim_t
        dots = "." * (t // 6 % 4)
        pulse = (1 + math.sin(t / 4)) / 2
        self.intro_lbl.configure(text=f"Pobieram {fmt_size(self.job.total)} modów{dots}",
                                 text_color=T.lerp_color(T.TEXT, T.ACCENT, pulse))
        self._anim_job = self.after(50, self._animate_intro)

    # ----- główny widok pobierania -----

    def _show_main(self):
        self._intro_job = None
        if self._anim_job:
            self.after_cancel(self._anim_job)
            self._anim_job = None
        if hasattr(self, "intro"):
            self.intro.destroy()

        self.header(f"Pobieranie z „{self.host['name']}”", f"Do: {self.folder}")
        card = ctk.CTkFrame(self, fg_color=T.PANEL, corner_radius=12)
        card.pack(fill="x", padx=20, pady=(0, 8))
        top = ctk.CTkFrame(card, fg_color="transparent")
        top.pack(fill="x", padx=16, pady=(14, 4))
        self.pct_lbl = ctk.CTkLabel(top, text="0%", font=T.font(26, "bold"), text_color=T.TEXT)
        self.pct_lbl.pack(side="left")
        self.speed_lbl = ctk.CTkLabel(top, text="", font=T.font(20, "bold"), text_color=T.ACCENT)
        self.speed_lbl.pack(side="right")
        self.bar = AnimatedProgressBar(card, height=18, bg=T.PANEL)
        self.bar.pack(fill="x", padx=16, pady=6)
        self.stats_lbl = ctk.CTkLabel(card, text="", font=T.font(12), text_color=T.MUTED, anchor="w")
        self.stats_lbl.pack(fill="x", padx=16)

        # sloty na pliki pobierane równolegle
        self.slots_box = ctk.CTkFrame(card, fg_color="transparent", height=1)
        self.slots_box.pack(fill="x", padx=16, pady=(8, 12))
        self._slots = []
        for _ in range(min(self.parallel, len(self.files))):
            row = ctk.CTkFrame(self.slots_box, fg_color="transparent")
            lbl = ctk.CTkLabel(row, text="", font=T.font(12), text_color=T.TEXT, anchor="w")
            lbl.pack(fill="x")
            bar = AnimatedProgressBar(row, height=6, bg=T.PANEL)
            bar.pack(fill="x", pady=(0, 4))
            self._slots.append({"row": row, "lbl": lbl, "bar": bar, "file": None, "shown": False})

        self.files_box = ctk.CTkScrollableFrame(self, fg_color=T.PANEL, corner_radius=10)
        self.files_box.pack(fill="both", expand=True, padx=20, pady=4)
        self._rows = []
        for f in self.job.files[:MAX_FILE_ROWS]:
            row = ctk.CTkFrame(self.files_box, fg_color=T.ROW, corner_radius=6)
            row.pack(fill="x", padx=4, pady=1)
            ctk.CTkLabel(row, text=T.shorten(f.name, 80), anchor="w", font=T.font(12),
                         text_color=T.TEXT).pack(side="left", padx=10, pady=2)
            st = ctk.CTkLabel(row, text="", width=110, anchor="e", font=T.font(12))
            st.pack(side="right", padx=10)
            ctk.CTkLabel(row, text=fmt_size(f.size), width=90, anchor="e", font=T.font(12),
                         text_color=T.MUTED).pack(side="right")
            self._rows.append((f, st, [None]))
        if len(self.job.files) > MAX_FILE_ROWS:
            ctk.CTkLabel(self.files_box, text=f"… i jeszcze {len(self.job.files) - MAX_FILE_ROWS} plików",
                         text_color=T.MUTED).pack(pady=6)

        self.foot = ctk.CTkFrame(self, fg_color="transparent")
        self.foot.pack(fill="x", padx=20, pady=(4, 16))
        self.result_lbl = ctk.CTkLabel(self.foot, text="", font=T.font(13, "bold"), anchor="w",
                                       justify="left")
        self.result_lbl.pack(side="left")
        self.cancel_btn = T.button(self.foot, "Anuluj", self._cancel, kind="danger", width=120)
        self.cancel_btn.pack(side="right")
        self._poll()

    def _poll(self):
        job = self.job
        total, done = job.total, job.done_bytes
        frac = done / total if total else (1.0 if job.finished else 0.0)
        speed = job.meter.speed()
        self.bar.set(frac)
        self.pct_lbl.configure(text=f"{frac * 100:.1f}%")
        self.speed_lbl.configure(text=fmt_speed(speed))
        eta = (total - done) / speed if speed > 1 else None
        fail = f"   •   błędy: {job.failed}" if job.failed else ""
        self.stats_lbl.configure(text=f"{fmt_size(done)} / {fmt_size(total)}   •   "
                                      f"pliki {job.files_done} / {len(job.files)}   •   "
                                      f"pozostało: {fmt_eta(eta)}{fail}")
        self._sync_slots(list(job.active))
        for f, lbl, last in self._rows:
            status = f.status
            if status == "pobieranie" and f.size:
                status = f"{f.done / f.size * 100:.0f}%"
            if status != last[0]:
                last[0] = status
                color = self.STATUS_COLORS.get(f.status, T.MUTED)
                lbl.configure(text=("✔ " if f.status == "gotowe" else "") + status, text_color=color)

        if job.finished:
            self._finish()
        else:
            self._poll_job = self.after(200, self._poll)

    def _sync_slots(self, active):
        free = [s for s in self._slots if s["file"] not in active]
        taken = {id(s["file"]) for s in self._slots if s["file"] in active}
        for f in active:
            if id(f) not in taken and free:
                s = free.pop(0)
                s["file"] = f
                s["bar"]._shown = 0.0
        for s in free:
            s["file"] = None
        for s in self._slots:
            f = s["file"]
            if f is None:
                if s["shown"]:
                    s["row"].pack_forget()
                    s["shown"] = False
                continue
            if not s["shown"]:
                s["row"].pack(fill="x")
                s["shown"] = True
            pct = f.done / f.size if f.size else 1.0
            s["lbl"].configure(text=f"⬇  {T.shorten(f.name, 80)}   {fmt_size(f.done)} / {fmt_size(f.size)}"
                                    + ("   (ponawiam…)" if f.status == "ponawiam…" else ""))
            s["bar"].set(pct)

    def _finish(self):
        if self._done_shown:
            return
        self._done_shown = True
        job = self.job
        self.cancel_btn.destroy()
        self.speed_lbl.configure(text="")
        self._sync_slots([])
        self.slots_box.pack_forget()
        self.stats_lbl.pack_configure(pady=(0, 14))
        if job.error or job.cancelled:
            msg = "Anulowano" if job.cancelled and not job.error else f"Błąd: {job.error}"
            self.result_lbl.configure(text=f"{msg}\nPostęp jest zapisany (pliki .part) – „Wznów” dokończy pobieranie.",
                                      text_color=T.RED if job.error else T.YELLOW)
            self.bar.set_color(T.RED if job.error else T.YELLOW)
            T.button(self.foot, "↻ Wznów", self._resume, kind="primary", width=120).pack(side="right", padx=4)
        elif job.failed:
            self.bar.set_color(T.YELLOW)
            self.result_lbl.configure(text=f"Pobrano {job.files_done} z {len(job.files)} – "
                                           f"{plural_files(job.failed)} z błędem", text_color=T.YELLOW)
            T.button(self.foot, "↻ Ponów nieudane", self._resume, kind="primary", width=150).pack(side="right", padx=4)
        else:
            self.bar.set(1.0)
            self.bar.set_color(T.GREEN)
            self.pct_lbl.configure(text="100%", text_color=T.GREEN)
            self.result_lbl.configure(text="✔ Mody zsynchronizowane", text_color=T.GREEN)
            T.button(self.foot, "📂 Otwórz folder", self._open, kind="success", width=150).pack(side="right", padx=4)
        T.button(self.foot, "← Sprawdź ponownie", self._back, width=150).pack(side="right", padx=4)

    def _cancel(self):
        self.cancel_btn.configure(state="disabled", text="Anulowanie…")
        self.job.cancel()

    def _resume(self):
        rest = [f for f in self.files if f.status != "gotowe"]
        self.app.show(ClientDownloadView, conn=self.conn, host=self.host, folder=self.folder,
                      files=rest, parallel=self.parallel, intro=False)

    def _open(self):
        try:
            os.startfile(self.folder)
        except OSError:
            pass

    def _back(self):
        self.app.show(ClientSyncView, conn=self.conn, host=self.host)

    def cleanup(self):
        for job_id in (self._poll_job, self._anim_job, self._intro_job):
            if job_id:
                self.after_cancel(job_id)
        if not self.job.finished:
            self.job.cancel()
