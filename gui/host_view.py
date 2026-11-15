"""Tryb hosta: wybór folderów z modami -> hostowanie z listą klientów i postępem."""
import os
import socket
import threading
import time
from tkinter import filedialog

import customtkinter as ctk

from gui import theme as T
from gui.base import View
from gui.widgets import AnimatedProgressBar, SelectableList
from net.server import ModServer
from utils import config
from utils.files import find_mx_mods_folder, list_folder
from utils.fmt import fmt_eta, fmt_size, fmt_speed, plural_files
from utils.netinfo import interfaces


def _fill_entries(lst, folder, checked):
    """Wypełnia listę elementami folderu modów; checked=None zaznacza wszystko."""
    for path, name, is_dir in list_folder(folder):
        if name.endswith(".part"):
            continue
        lst.add(name, name, is_dir, checked=checked is None or name in checked)
        lst.autosize(name, path)


class HostSetupView(View):
    def __init__(self, app, folder=None, checked=None, name=None, password=""):
        super().__init__(app)
        cfg = config.load()
        if folder is None:
            folder = cfg.get("host_folder") or find_mx_mods_folder()
            if folder and checked is None and cfg.get("host_folder") == folder and "host_entries" in cfg:
                checked = set(cfg["host_entries"])
        self.folder = folder if folder and os.path.isdir(folder) else None
        self.header("Tryb hosta", "Zaznacz foldery z modami, które chcesz udostępnić", back=self._back)

        tools = ctk.CTkFrame(self, fg_color="transparent")
        tools.pack(fill="x", padx=20, pady=(0, 6))
        self.path_lbl = ctk.CTkLabel(tools, text="Nie wybrano folderu", text_color=T.MUTED,
                                     font=T.font(12), anchor="w")
        self.path_lbl.pack(side="left", fill="x", expand=True)
        T.button(tools, "Zaznacz wszystko", self._toggle_all, width=130).pack(side="right", padx=3)
        T.button(tools, "⟳ Odśwież", lambda: self._load(self.folder, set(self.list.selected())),
                 width=100).pack(side="right", padx=3)
        T.button(tools, "Zmień folder", self._choose_folder, width=110).pack(side="right", padx=3)

        self.list = SelectableList(self, on_change=self._update_footer)
        self.list.pack(fill="both", expand=True, padx=20, pady=4)

        foot = ctk.CTkFrame(self, fg_color=T.PANEL, corner_radius=10)
        foot.pack(fill="x", padx=20, pady=(6, 16))
        self.name_entry = ctk.CTkEntry(foot, width=180, height=36, placeholder_text="Nazwa hosta")
        self.name_entry.insert(0, name or cfg.get("host_name") or socket.gethostname())
        self.name_entry.pack(side="left", padx=(12, 6), pady=12)
        self.pw_entry = ctk.CTkEntry(foot, width=180, height=36, show="•",
                                     placeholder_text="Hasło (opcjonalne)")
        if password:
            self.pw_entry.insert(0, password)
        self.pw_entry.pack(side="left", padx=6)
        self.summary = ctk.CTkLabel(foot, text="", text_color=T.MUTED, font=T.font(12))
        self.summary.pack(side="left", padx=10)
        self.host_btn = T.button(foot, "Hostuj  ▶", self._host, kind="primary", width=130, height=38)
        self._btn_visible = False

        if self.folder:
            self._load(self.folder, checked)
        else:
            self.list.set_empty_text("Wybierz folder z modami MX Bikes (Dokumenty\\PiBoSo\\MX Bikes\\mods)")
            self._update_footer()
            self.after(200, self._choose_folder)

    def _back(self):
        from gui.start_view import StartView
        self.app.show(StartView)

    def _choose_folder(self):
        d = filedialog.askdirectory(parent=self, title="Wybierz folder z modami MX Bikes",
                                    initialdir=self.folder or os.path.expanduser("~/Documents"))
        if d:
            self._load(os.path.normpath(d), None)

    def _load(self, folder, checked):
        if not folder:
            return
        self.folder = folder
        self.path_lbl.configure(text=f"📂 {T.shorten(folder, 60)}")
        self.list.clear()
        _fill_entries(self.list, folder, checked)
        if not self.list.keys():
            self.list.set_empty_text("Folder jest pusty")
        self._update_footer()

    def _toggle_all(self):
        self.list.set_all(len(self.list.selected()) < len(self.list.keys()))

    def _update_footer(self):
        sel = self.list.selected()
        if sel:
            size, complete = self.list.size_of(sel)
            self.summary.configure(text=f"Zaznaczono: {len(sel)}  •  {fmt_size(size)}" + ("" if complete else " +"))
            if not self._btn_visible:
                self.host_btn.pack(side="right", padx=12)
                self._btn_visible = True
        else:
            self.summary.configure(text="Nic nie zaznaczono")
            if self._btn_visible:
                self.host_btn.pack_forget()
                self._btn_visible = False

    def _host(self):
        entries = self.list.selected()
        if not entries or not self.folder:
            return
        name = self.name_entry.get().strip() or socket.gethostname()
        config.update(host_folder=self.folder, host_entries=entries, host_name=name)
        self.app.show(HostRunView, folder=self.folder, entries=entries, name=name,
                      password=self.pw_entry.get())


class EditSharesDialog(ctk.CTkToplevel):
    """✎ Zmiana udostępnionych folderów w trakcie hostowania (potem ponowny skan)."""

    def __init__(self, master, folder, checked, on_save):
        super().__init__(master, fg_color=T.BG)
        self.title("Edytuj udostępnione mody")
        self.geometry("680x520")
        self.transient(master.winfo_toplevel())
        self.on_save = on_save

        ctk.CTkLabel(self, text="Zaznacz, co ma być udostępnione", font=T.font(16, "bold"),
                     text_color=T.TEXT).pack(anchor="w", padx=16, pady=(14, 4))
        ctk.CTkLabel(self, text="Po zapisaniu host przeskanuje mody ponownie (z cache – szybko).",
                     font=T.font(12), text_color=T.MUTED).pack(anchor="w", padx=16)

        self.list = SelectableList(self)
        self.list.pack(fill="both", expand=True, padx=16, pady=8)
        _fill_entries(self.list, folder, set(checked))

        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.pack(fill="x", padx=16, pady=(0, 14))
        T.button(btns, "Zapisz", self._save, kind="primary", width=120).pack(side="right", padx=4)
        T.button(btns, "Anuluj", self.destroy, width=120).pack(side="right", padx=4)
        T.button(btns, "Zaznacz wszystko",
                 lambda: self.list.set_all(len(self.list.selected()) < len(self.list.keys())),
                 width=130).pack(side="left")
        self.after(150, self._focus)

    def _focus(self):
        self.lift()
        self.focus_force()

    def _save(self):
        sel = self.list.selected()
        if not sel:
            return
        self.on_save(sel)
        self.destroy()


class HostRunView(View):
    def __init__(self, app, folder, entries, name, password):
        super().__init__(app)
        self.folder = folder
        self.entries = list(entries)
        self.name = name
        self.password = password
        self.server = ModServer(folder, entries, name, password)
        self._state = "starting"  # starting | running -> running_shown | error -> error_shown
        self._error = None
        self._scan_gen = -1
        self._client_rows = {}
        self._transfer_rows = {}
        self._poll_job = None

        bar = self.header("Hostowanie", "Uruchamianie…")
        T.button(bar, "■  Zatrzymaj hosting", self._stop, kind="danger", width=170).pack(side="right")
        self.pause_btn = T.button(bar, "⏸  Wstrzymaj pobierania", self._toggle_pause, width=190)
        self.pause_btn.pack(side="right", padx=8)

        info = ctk.CTkFrame(self, fg_color=T.PANEL, corner_radius=10)
        info.pack(fill="x", padx=20, pady=(0, 4))
        top = ctk.CTkFrame(info, fg_color="transparent")
        top.pack(fill="x", padx=14, pady=(10, 0))
        self.status_lbl = ctk.CTkLabel(top, text="●  Uruchamiam serwer…", font=T.font(14, "bold"),
                                       text_color=T.YELLOW, anchor="w")
        self.status_lbl.pack(side="left")
        self.traffic_lbl = ctk.CTkLabel(top, text="", font=T.font(12), text_color=T.MUTED)
        self.traffic_lbl.pack(side="right")
        self.scan_bar = AnimatedProgressBar(info, height=10, bg=T.PANEL)
        self.scan_bar.set_indeterminate()
        self.scan_bar.pack(fill="x", padx=14, pady=(8, 0))
        self._scan_bar_visible = True
        self.addr_lbl = ctk.CTkLabel(info, text="", font=T.font(12), text_color=T.MUTED,
                                     anchor="w", justify="left")
        self.addr_lbl.pack(fill="x", padx=14, pady=(4, 10))

        # siatka: listy dzielą wolne miejsce w proporcji 2 : 1 : 3
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=20, pady=(0, 14))
        body.grid_columnconfigure(0, weight=1)
        for row, weight in ((1, 2), (3, 1), (5, 3)):
            body.grid_rowconfigure(row, weight=weight, uniform="lists")

        bar, _ = self._grid_section(body, 0, "Udostępnione mody")
        T.button(bar, "✎ Edytuj", self._edit, width=90, height=28).pack(side="left", padx=(10, 4))
        T.button(bar, "⟳ Przeskanuj", lambda: self._rescan(False), width=110, height=28).pack(side="left", padx=4)
        T.button(bar, "Pełny skan", lambda: self._rescan(True), width=100, height=28).pack(side="left", padx=4)
        self.files_lbl = ctk.CTkLabel(bar, text="", font=T.font(12), text_color=T.MUTED)
        self.files_lbl.pack(side="right")
        self.files_box = ctk.CTkScrollableFrame(body, fg_color=T.PANEL, corner_radius=10, height=40)
        self.files_box.grid(row=1, column=0, sticky="nsew")
        self.no_files = ctk.CTkLabel(self.files_box, text="Skanuję mody…", text_color=T.MUTED)
        self.no_files.pack(pady=10)

        _, self.clients_title = self._grid_section(body, 2, "Połączeni klienci (0)")
        self.clients_box = ctk.CTkScrollableFrame(body, fg_color=T.PANEL, corner_radius=10, height=40)
        self.clients_box.grid(row=3, column=0, sticky="nsew")
        self.no_clients = ctk.CTkLabel(self.clients_box, text="Czekam na klientów…", text_color=T.MUTED)
        self.no_clients.pack(pady=10)

        self._grid_section(body, 4, "Postęp pobierania")
        self.transfer_box = ctk.CTkScrollableFrame(body, fg_color=T.PANEL, corner_radius=10, height=40)
        self.transfer_box.grid(row=5, column=0, sticky="nsew")
        self.no_transfers = ctk.CTkLabel(self.transfer_box, text="Nikt jeszcze nie pobiera", text_color=T.MUTED)
        self.no_transfers.pack(pady=10)

        threading.Thread(target=self._start_server, daemon=True).start()
        self._poll()

    def _grid_section(self, master, row, title):
        bar = ctk.CTkFrame(master, fg_color="transparent")
        bar.grid(row=row, column=0, sticky="ew", pady=(10, 4))
        lbl = ctk.CTkLabel(bar, text=title, font=T.font(15, "bold"), text_color=T.TEXT, anchor="w")
        lbl.pack(side="left")
        return bar, lbl

    # ----- serwer -----

    def _start_server(self):
        try:
            self.server.start()
            self._state = "running"
        except Exception as e:
            self._error = str(e)
            self._state = "error"

    def _show_running(self):
        lines = []
        for i in interfaces():
            tag = "   [Radmin VPN]" if i["radmin"] and "radmin" not in i["name"].lower() else ""
            lines.append(f"{i['ip']}:{self.server.port}   ({T.shorten(i['name'], 40)}){tag}")
        pw = "z hasłem 🔒" if self.server.protected else "bez hasła"
        self.subtitle_lbl.configure(text=f"Host „{self.name}”  •  {pw}  •  📂 {T.shorten(self.folder, 60)}")
        warn = f"\n⚠ {self.server.discovery_error} – klienci mogą połączyć się ręcznie po IP" \
            if self.server.discovery_error else ""
        self.addr_lbl.configure(text="Adresy: " + ("\n             ".join(lines) or "brak sieci") + warn)

    def _show_scan(self):
        s = self.server
        if s.scanning:
            done, total = s.scan_bytes_done, s.scan_bytes_total
            speed = s.scan_meter.speed()
            if total:
                self.scan_bar.set(done / total)
                eta = (total - done) / speed if speed > 1 else None
                text = (f"●  Skanuję mody…  {done / total * 100:.0f}%  •  {s.scan_files_done}/{s.scan_files_total}"
                        f" plików  •  {fmt_speed(speed)}  •  pozostało {fmt_eta(eta)}")
            else:
                self.scan_bar.set_indeterminate()
                text = "●  Skanuję mody…" + (f"  {s.scan_files_done}/{s.scan_files_total} plików"
                                            if s.scan_files_total else "")
            self.status_lbl.configure(text=text, text_color=T.YELLOW)
            if not self._scan_bar_visible:
                self.scan_bar.pack(fill="x", padx=14, pady=(8, 0), before=self.addr_lbl)
                self._scan_bar_visible = True
            return
        if self._scan_bar_visible:
            self.scan_bar.pack_forget()
            self._scan_bar_visible = False
        if s.scan_error:
            self.status_lbl.configure(text=f"●  Błąd skanowania: {s.scan_error}", text_color=T.RED)
        elif s.paused:
            self.status_lbl.configure(text="●  Pobierania wstrzymane – klienci czekają", text_color=T.ORANGE)
        else:
            self.status_lbl.configure(text="●  Hostowanie aktywne", text_color=T.GREEN)

    def _refresh_files(self):
        for w in self.files_box.winfo_children():
            if w is not self.no_files:
                w.destroy()
        items = self.server.items
        self.no_files.configure(text="Brak plików do udostępnienia")
        if items:
            self.no_files.pack_forget()
        else:
            self.no_files.pack(pady=10)
        for it in items:
            row = ctk.CTkFrame(self.files_box, fg_color=T.ROW, corner_radius=8)
            row.pack(fill="x", padx=6, pady=2)
            ctk.CTkLabel(row, text=("📁 " if it["is_dir"] else "📄 ") + T.shorten(it["name"], 70),
                         anchor="w", text_color=T.TEXT).pack(side="left", padx=10, pady=4)
            extra = f"{plural_files(it['files'])}  •  " if it["is_dir"] else ""
            ctk.CTkLabel(row, text=extra + fmt_size(it["size"]), text_color=T.MUTED,
                         font=T.font(12)).pack(side="right", padx=12)
        idx = self.server.index or {}
        self.files_lbl.configure(text=f"{plural_files(len(idx))}  •  {fmt_size(sum(v['size'] for v in idx.values()))}"
                                      f"  •  skan {self.server.scan_dur:.1f} s")

    def _edit(self):
        if self._state != "running_shown":
            return
        EditSharesDialog(self, self.folder, self.entries, self._apply_edit)

    def _apply_edit(self, entries):
        self.entries = list(entries)
        config.update(host_entries=self.entries)
        self.server.rescan(self.entries)
        self.files_lbl.configure(text="Skanuję…")

    def _rescan(self, force):
        if self._state != "running_shown":
            return
        self.server.rescan(force=force)
        self.files_lbl.configure(text="Skanuję…")

    def _toggle_pause(self):
        self.server.paused = not self.server.paused
        self.pause_btn.configure(text="▶  Wznów pobierania" if self.server.paused else "⏸  Wstrzymaj pobierania")

    # ----- odświeżanie -----

    def _poll(self):
        if self._state == "running":
            self._show_running()
            self._state = "running_shown"
        elif self._state == "error":
            self.status_lbl.configure(text=f"●  Błąd: {self._error}", text_color=T.RED)
            self.scan_bar.pack_forget()
            self._state = "error_shown"
        if self._state == "running_shown":
            self._show_scan()
            if self.server.scan_gen != self._scan_gen:
                self._scan_gen = self.server.scan_gen
                self._refresh_files()
            self.traffic_lbl.configure(text=f"wysłano łącznie: {fmt_size(self.server.bytes_sent)}"
                                            f"   •   teraz: {fmt_speed(self.server.total_speed())}")

        snap = self.server.snapshot()
        self._sync_clients(snap)
        self._sync_transfers([s for s in snap if s["total"] or s["sent"] or s["state"] == "pobiera"])
        self._poll_job = self.after(250, self._poll)

    def _sync_clients(self, snap):
        ids = {s["id"] for s in snap}
        for sid in list(self._client_rows):
            if sid not in ids:
                self._client_rows.pop(sid)["frame"].destroy()
        for s in snap:
            r = self._client_rows.get(s["id"])
            if not r:
                frame = ctk.CTkFrame(self.clients_box, fg_color=T.ROW, corner_radius=8)
                frame.pack(fill="x", padx=6, pady=2)
                ctk.CTkLabel(frame, text=f"💻  {s['name']}", text_color=T.TEXT,
                             font=T.font(13, "bold")).pack(side="left", padx=10, pady=4)
                ctk.CTkLabel(frame, text=s["ip"], text_color=T.MUTED, font=T.font(12)).pack(side="left", padx=6)
                ctk.CTkLabel(frame, text="od " + time.strftime("%H:%M", time.localtime(s["connected_at"])),
                             text_color=T.MUTED, font=T.font(12)).pack(side="left", padx=6)
                state = ctk.CTkLabel(frame, text="", font=T.font(12))
                state.pack(side="right", padx=12)
                p2p = ctk.CTkLabel(frame, text="", font=T.font(11, "bold"), text_color=T.CYAN)
                p2p.pack(side="right", padx=4)
                r = self._client_rows[s["id"]] = {"frame": frame, "state": state, "p2p": p2p}
            r["p2p"].configure(text="⇅ P2P" if s.get("p2p") else "")
            st = s["state"]
            color = (T.ACCENT if st == "pobiera" else T.YELLOW if st == "sprawdza mody"
                     else T.GREEN if st.startswith("zakończ") or st == "aktualny" else T.MUTED)
            r["state"].configure(text=st, text_color=color)
        self.clients_title.configure(text=f"Połączeni klienci ({len(snap)})")
        if snap:
            self.no_clients.pack_forget()
        else:
            self.no_clients.pack(pady=10)

    def _sync_transfers(self, snap):
        ids = {s["id"] for s in snap}
        for sid in list(self._transfer_rows):
            if sid not in ids:
                self._transfer_rows.pop(sid)["frame"].destroy()
        for s in snap:
            r = self._transfer_rows.get(s["id"])
            if not r:
                frame = ctk.CTkFrame(self.transfer_box, fg_color=T.ROW, corner_radius=8)
                frame.pack(fill="x", padx=6, pady=3)
                top = ctk.CTkFrame(frame, fg_color="transparent")
                top.pack(fill="x", padx=12, pady=(8, 2))
                ctk.CTkLabel(top, text=f"💻  {s['name']}", font=T.font(13, "bold"),
                             text_color=T.TEXT).pack(side="left")
                speed = ctk.CTkLabel(top, text="", font=T.font(13, "bold"), text_color=T.ACCENT)
                speed.pack(side="right")
                bar = AnimatedProgressBar(frame, height=12, bg=T.ROW)
                bar.pack(fill="x", padx=12, pady=4)
                info = ctk.CTkLabel(frame, text="", font=T.font(11), text_color=T.MUTED, anchor="w")
                info.pack(fill="x", padx=12, pady=(0, 8))
                r = self._transfer_rows[s["id"]] = {"frame": frame, "bar": bar, "speed": speed, "info": info}
            total, sent = s["total"], s.get("progress", s["sent"])
            done = s["state"].startswith("zakończ")
            if total:
                sent = min(sent, total)
                frac = 1.0 if done else sent / total
                r["bar"].set(frac)
                sizes = f"{fmt_size(sent)} / {fmt_size(total)}  ({frac * 100:.0f}%)"
            else:  # stary klient v3 nie zgłasza, ile pobierze
                r["bar"].set_indeterminate(s["active"] > 0)
                if not s["active"]:
                    r["bar"].set(1.0 if done else 0.0)
                sizes = f"wysłano {fmt_size(sent)}"
            r["bar"].set_color(T.GREEN if done else None)
            r["speed"].configure(text="✔ gotowe" if done else fmt_speed(s["speed"]),
                                 text_color=T.GREEN if done else T.ACCENT)
            cur = f"  •  {T.shorten(s['current'], 60)}" if s["current"] else ""
            p2p = s.get("progress", 0) - s["sent"]
            p2p = f"  •  od innych graczy (P2P): {fmt_size(p2p)}" if p2p > 0 else ""
            r["info"].configure(text=f"{sizes}  •  od Ciebie: {fmt_size(s['sent'])}{p2p}  •  "
                                     f"{plural_files(s['files_done'])}{cur}")
        if snap:
            self.no_transfers.pack_forget()
        else:
            self.no_transfers.pack(pady=10)

    def _stop(self):
        self.app.show(HostSetupView, folder=self.folder, checked=set(self.entries),
                      name=self.name, password=self.password)

    def cleanup(self):
        if self._poll_job:
            self.after_cancel(self._poll_job)
        self.server.stop()
