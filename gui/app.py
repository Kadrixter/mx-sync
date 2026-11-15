"""Główne okno MX Sync 2: górny pasek, gracze po lewej, wybrany widok po prawej, zasobnik."""
import os
import queue
from tkinter import messagebox

import customtkinter as ctk

from core.node import Node
from gui import theme as T
from gui.compare_cache import CompareCache
from gui.sidebar import Sidebar
from gui.topbar import TopBar
from gui.tray import Tray
from gui.update_banner import UpdateWatcher
from gui.views.integrity_view import IntegrityView
from gui.views.library_view import LibraryView
from gui.views.mods_view import ModsView
from gui.views.transfers_view import TransfersView
from gui.winicon import set_crisp_icon
from utils.files import resource_path
from utils.fmt import fmt_speed
from utils.version import VERSION

TICK_MS = 500


class App(ctk.CTk):
    def __init__(self, start_hidden=False):
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        super().__init__(fg_color=T.BG)
        self.title(f"MX Sync  v{VERSION}")
        self.geometry("1180x760")
        self.minsize(980, 620)
        icon = resource_path(os.path.join("assets", "icon.ico"))
        if os.path.exists(icon):
            self.iconbitmap(icon)
            self.after(300, lambda: set_crisp_icon(self, icon))
        self.closing = False
        self.update_info = None      # None = jeszcze nie sprawdzono, False = brak nowszej, UpdateInfo
        self.update_dialog = None
        self._commands = queue.Queue()
        self._hint_shown = False

        try:
            self.node = Node()
        except Exception as e:      # noqa: BLE001 – bez silnika nie ma programu, pokaż czemu
            messagebox.showerror("MX Sync", f"Nie można uruchomić MX Sync:\n{e}")
            raise SystemExit(1)
        self.node.on_show = lambda: self._commands.put("show")
        self.node.start()
        self.cache = CompareCache(self.node)

        self.topbar = TopBar(self, self)
        self.topbar.pack(fill="x")
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True)
        self.sidebar = Sidebar(body, self)
        self.sidebar.pack(side="left", fill="y")
        self.content = ctk.CTkFrame(body, fg_color="transparent")
        self.content.pack(side="left", fill="both", expand=True, padx=20, pady=18)
        self.view, self.view_key = None, None
        self.open_view("all")

        self.toast_lbl = ctk.CTkLabel(self, text="", font=T.font(13, "bold"), fg_color=T.ACCENT,
                                      text_color="#111111", corner_radius=10, height=36)
        self._toast_job = None
        self.update_watcher = UpdateWatcher(self)
        self.tray = Tray()
        self.tray.start()
        self.protocol("WM_DELETE_WINDOW", self._close_button)
        if start_hidden and self.tray.available:
            self.withdraw()
        self._tick()

    # ---------- widoki ----------

    @property
    def current_view(self):
        """Element, nad którym pojawia się pasek aktualizacji."""
        return self.topbar

    def open_view(self, kind, pid=None):
        key = (kind, pid)
        if key == self.view_key and self.view is not None:
            return
        if self.view is not None:
            self.view.destroy()
        if kind == "player":
            self.view = ModsView(self.content, self, "player", pid)
        elif kind == "library":
            self.view = LibraryView(self.content, self)
        elif kind == "transfers":
            self.view = TransfersView(self.content, self)
        elif kind == "integrity":
            self.view = IntegrityView(self.content, self)
        else:
            self.view = ModsView(self.content, self, "all")
        self.view_key = key
        self.view.pack(fill="both", expand=True)
        self.sidebar.refresh(self.view_key)

    def open_settings(self):
        from gui.settings_dialog import SettingsDialog
        SettingsDialog(self)

    def add_player_dialog(self):
        d = ctk.CTkInputDialog(text="Adres IP gracza (np. 26.12.34.56 albo 1.2.3.4:8888)\n"
                                    "Gracze w tej samej sieci i w Radmin VPN pojawiają się sami.",
                               title="Dodaj gracza", button_fg_color=T.ACCENT,
                               button_hover_color=T.ACCENT_HOVER, button_text_color="#111111")
        text = (d.get_input() or "").strip()
        if text:
            try:
                self.node.add_player(text)
                self.toast(f"Dodano {text} – łączę…")
            except ValueError:
                self.toast("Nieprawidłowy adres")

    def open_updates(self, info=None, auto=False):
        from gui.update_dialog import UpdateDialog
        if self.update_dialog is not None and self.update_dialog.winfo_exists():
            self.update_dialog.lift()
            self.update_dialog.focus_force()
            return
        self.show_window()
        self.update_watcher.banner.hide()
        self.update_dialog = UpdateDialog(self, info, auto=auto)

    # ---------- powiadomienia ----------

    def toast(self, text, ms=3500):
        self.toast_lbl.configure(text=f"   {text}   ")
        self.toast_lbl.place(relx=0.5, rely=1.0, y=-24, anchor="s")
        self.toast_lbl.lift()
        if self._toast_job:
            self.after_cancel(self._toast_job)
        self._toast_job = self.after(ms, self.toast_lbl.place_forget)

    def _events(self):
        events, self.node.events[:] = list(self.node.events), []
        hidden = self.state() == "withdrawn"
        if len(events) > 3:
            names = ", ".join(t for _, t in events[:3])
            events = [(events[0][0], f"{names} i {len(events) - 3} więcej")]
        for title, text in events:
            if hidden:
                self.tray.notify(title, text)
            else:
                self.toast(f"{title}: {text}")

    # ---------- pętla ----------

    def _tick(self):
        if self.closing:
            return
        self._handle_commands()
        self._events()
        if self.state() != "withdrawn":
            try:
                self.topbar.refresh()
                self.sidebar.refresh(self.view_key)
                if self.view is not None:
                    self.view.refresh()
            except Exception as e:  # noqa: BLE001 – błąd odświeżania nie może zatrzymać pętli
                print("refresh:", e)
        eng = self.node.engine
        self.tray.tooltip(f"MX Sync  –  ↓ {fmt_speed(eng.down_rate)}  ↑ {fmt_speed(eng.up_rate)}")
        self.after(TICK_MS, self._tick)

    def _handle_commands(self):
        while True:
            try:
                cmd = self._commands.get_nowait()
            except queue.Empty:
                break
            self._command(cmd)
        while self.tray.available:
            try:
                cmd = self.tray.commands.get_nowait()
            except queue.Empty:
                break
            self._command(cmd)

    def _command(self, cmd):
        if cmd == "show":
            self.show_window()
        elif cmd == "transfers":
            self.show_window()
            self.open_view("transfers")
        elif cmd == "quit":
            self.quit_app()

    def show_window(self):
        self.deiconify()
        self.lift()
        self.attributes("-topmost", True)
        self.after(200, lambda: self.attributes("-topmost", False))
        self.focus_force()

    # ---------- zamykanie ----------

    def _close_button(self):
        if self.node.cfg.get("close_to_tray", True) and self.tray.available:
            self.withdraw()
            if not self._hint_shown:
                self._hint_shown = True
                self.tray.notify("MX Sync dalej działa", "Udostępniam mody w tle. Kliknij ikonę obok zegara, "
                                                         "żeby otworzyć, albo prawym – Zakończ.")
            return
        self.quit_app()

    def quit_app(self):
        if self.closing:
            return
        self.closing = True
        self.tray.stop()
        self.node.stop()
        self.destroy()
