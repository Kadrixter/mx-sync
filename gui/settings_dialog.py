"""Ustawienia: nazwa gracza, folder modów, hasło grupy, limity prędkości, połączenie bezpośrednie, zasobnik."""
from tkinter import filedialog

import customtkinter as ctk

from gui import theme as T
from gui.direct_panel import DirectPanel
from utils.autostart import set_autostart
from utils.files import resolve_mods_root


class SettingsDialog(ctk.CTkToplevel):
    def __init__(self, app):
        super().__init__(app, fg_color=T.BG)
        self.app = app
        node = app.node
        cfg = node.cfg
        self.title("Ustawienia – MX Sync")
        self.geometry(f"580x700+{app.winfo_rootx() + 120}+{app.winfo_rooty() + 40}")
        self.resizable(False, False)
        self.transient(app)

        ctk.CTkLabel(self, text="USTAWIENIA", font=T.title_font(22), text_color=T.ACCENT).pack(pady=(18, 8))
        body = ctk.CTkFrame(self, fg_color=T.CARD, corner_radius=14)
        body.pack(fill="both", expand=True, padx=18)

        self.name = self._entry(body, "Twoja nazwa (widzą ją inni gracze)", cfg.get("name") or node.name)
        row = self._label(body, "Folder modów MX Bikes")
        frow = ctk.CTkFrame(body, fg_color="transparent")
        frow.pack(fill="x", padx=16)
        self.folder = ctk.CTkEntry(frow, height=34, fg_color=T.BG, border_color=T.BORDER)
        self.folder.insert(0, node.folder)
        self.folder.pack(side="left", fill="x", expand=True)
        T.button(frow, "Wybierz…", self._pick, width=90).pack(side="left", padx=(8, 0))
        del row
        self.password = self._entry(body, "Hasło grupy (opcjonalne – widzicie się tylko z tym samym hasłem)",
                                    cfg.get("password", ""), show="•")
        lim = ctk.CTkFrame(body, fg_color="transparent")
        lim.pack(fill="x", padx=16, pady=(12, 0))
        self.max_up = self._small(lim, "Limit wysyłania KB/s (0 = bez)", cfg.get("max_up", 0))
        self.max_down = self._small(lim, "Limit pobierania KB/s (0 = bez)", cfg.get("max_down", 0))
        self.port = self._small(lim, "Port transferów (0 = auto)", cfg.get("lt_port", 0))
        self.direct = DirectPanel(body, node)
        self.direct.pack(fill="x", padx=16, pady=(16, 0))

        self.tray = ctk.CTkCheckBox(body, text="Krzyżyk chowa MX Sync do zasobnika (dalej udostępnia mody)",
                                    font=T.font(13), fg_color=T.ACCENT, hover_color=T.ACCENT_HOVER,
                                    checkmark_color="#111111")
        self.tray.pack(anchor="w", padx=16, pady=(16, 6))
        if cfg.get("close_to_tray", True):
            self.tray.select()
        self.auto = ctk.CTkCheckBox(body, text="Uruchamiaj razem z Windows (od razu w zasobniku)",
                                    font=T.font(13), fg_color=T.ACCENT, hover_color=T.ACCENT_HOVER,
                                    checkmark_color="#111111")
        self.auto.pack(anchor="w", padx=16, pady=6)
        if cfg.get("autostart"):
            self.auto.select()
        self.err = ctk.CTkLabel(body, text="", font=T.font(12), text_color=T.RED)
        self.err.pack(pady=(6, 0))

        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.pack(pady=14)
        T.button(btns, "Anuluj", self.destroy, width=120, height=38).pack(side="left", padx=6)
        T.button(btns, "Zapisz", self._save, kind="primary", width=140, height=38).pack(side="left", padx=6)
        self.bind("<Escape>", lambda e: self.destroy())
        self.after(150, self._focus)

    def _focus(self):
        self.lift()
        self.focus_force()

    def _label(self, master, text):
        lbl = ctk.CTkLabel(master, text=text, font=T.font(12, "bold"), text_color=T.MUTED, anchor="w")
        lbl.pack(fill="x", padx=16, pady=(14, 4))
        return lbl

    def _entry(self, master, label, value, show=None):
        self._label(master, label)
        e = ctk.CTkEntry(master, height=34, fg_color=T.BG, border_color=T.BORDER, show=show)
        e.insert(0, value or "")
        e.pack(fill="x", padx=16)
        return e

    def _small(self, master, label, value):
        box = ctk.CTkFrame(master, fg_color="transparent")
        box.pack(side="left", fill="x", expand=True, padx=(0, 10))
        ctk.CTkLabel(box, text=label, font=T.font(12, "bold"), text_color=T.MUTED, anchor="w").pack(fill="x")
        e = ctk.CTkEntry(box, height=34, fg_color=T.BG, border_color=T.BORDER)
        e.insert(0, str(value or 0))
        e.pack(fill="x", pady=(4, 0))
        return e

    def _pick(self):
        d = filedialog.askdirectory(parent=self, initialdir=self.folder.get() or None,
                                    title="Wybierz folder mods MX Bikes")
        if d:
            self.folder.delete(0, "end")
            self.folder.insert(0, resolve_mods_root(d))

    def _save(self):
        try:
            up, down = int(self.max_up.get() or 0), int(self.max_down.get() or 0)
            if up < 0 or down < 0:
                raise ValueError
        except ValueError:
            self.err.configure(text="Limity muszą być liczbami (0 = bez limitu)")
            return
        try:
            port = int(self.port.get() or 0)
            if port and not 1024 <= port <= 65535:
                raise ValueError
        except ValueError:
            self.err.configure(text="Port: 0 (automatycznie) albo liczba 1024–65535")
            return
        port_changed = port != int(self.app.node.cfg.get("lt_port") or 0)
        auto = bool(self.auto.get())
        set_autostart(auto)
        self.app.node.set_options(name=self.name.get().strip()[:32], folder=self.folder.get().strip(),
                                  password=self.password.get(), max_up=up, max_down=down,
                                  close_to_tray=bool(self.tray.get()), autostart=auto,
                                  direct=self.direct.enabled, lt_port=port)
        self.app.toast("Zapisano ustawienia – nowy port zadziała po ponownym uruchomieniu MX Sync"
                       if port_changed else "Zapisano ustawienia")
        self.destroy()
