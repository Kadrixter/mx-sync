"""Ustawienia: połączenia bezpośrednie – włącznik, stan portu i publiczne IP (zasłonięte, widać po najechaniu)."""
import customtkinter as ctk

from core.direct import mask_ip
from gui import theme as T

COLORS = {"ok": T.GREEN, "warn": T.YELLOW, "bad": T.RED, "off": T.MUTED}


class DirectPanel(ctk.CTkFrame):
    def __init__(self, master, node):
        super().__init__(master, fg_color="transparent")
        self.node = node
        self._hover = False
        ctk.CTkLabel(self, text="Połączenie bezpośrednie (jak w qBittorrent): UPnP / NAT-PMP, hole punching", font=T.font(12, "bold"),
                     text_color=T.MUTED, anchor="w").pack(fill="x", pady=(0, 4))
        self.check = ctk.CTkCheckBox(self, text="Łącz się z graczami wprost przez internet (Radmin jako zapas)",
                                     font=T.font(13), fg_color=T.ACCENT, hover_color=T.ACCENT_HOVER,
                                     checkmark_color="#111111")
        self.check.pack(anchor="w")
        if node.direct.enabled:
            self.check.select()
        self.status = ctk.CTkLabel(self, text="", font=T.font(12), anchor="w", justify="left", wraplength=490)
        self.status.pack(fill="x", pady=(6, 0))
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", pady=(4, 0))
        ctk.CTkLabel(row, text="Twoje publiczne IP to:", font=T.font(12), text_color=T.MUTED).pack(side="left")
        self.ip = ctk.CTkLabel(row, text="", font=("Consolas", 13, "bold"), text_color=T.TEXT, cursor="hand2")
        self.ip.pack(side="left", padx=(6, 0))
        self.hint = ctk.CTkLabel(row, text="(najedź, żeby zobaczyć)", font=T.font(11), text_color=T.FAINT)
        self.hint.pack(side="left", padx=(8, 0))
        self.ip.bind("<Enter>", lambda e: self._set_hover(True))
        self.ip.bind("<Leave>", lambda e: self._set_hover(False))
        self._tick()

    @property
    def enabled(self):
        return bool(self.check.get())

    def _set_hover(self, on):
        self._hover = on
        self._render()

    def _tick(self):
        if not self.winfo_exists():
            return
        self._render()
        self.after(1000, self._tick)

    def _render(self):
        d = self.node.direct
        _, text, level = d.status()
        self.status.configure(text=text, text_color=COLORS.get(level, T.MUTED))
        ip = d.public_ip
        if not d.enabled:
            self.ip.configure(text="-")
            self.hint.configure(text="")
        elif not ip:
            self.ip.configure(text=d.ip_error or "sprawdzam…")
            self.hint.configure(text="")
        else:
            port = self.node.engine.external_port or self.node.engine.port
            self.ip.configure(text=f"{ip}:{port}" if self._hover else f"{mask_ip(ip)}:{port}")
            self.hint.configure(text="" if self._hover else "(najedź, żeby zobaczyć)")
