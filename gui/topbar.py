"""Górny pasek: logo, kim jestem, stan (skan / gracze), prędkości i ustawienia."""
import os

import customtkinter as ctk
from PIL import Image

from gui import theme as T
from utils.files import resource_path
from utils.fmt import fmt_size, fmt_speed, plural_mods
from utils.version import VERSION


class TopBar(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color=T.SIDEBAR, corner_radius=0, height=64)
        self.pack_propagate(False)
        self.app = app
        try:
            img = Image.open(resource_path(os.path.join("assets", "wheel.png")))
            logo = ctk.CTkImage(img, size=(38, 38))
            ctk.CTkLabel(self, image=logo, text="").pack(side="left", padx=(18, 10))
        except OSError:
            pass
        brand = ctk.CTkFrame(self, fg_color="transparent")
        brand.pack(side="left")
        ctk.CTkLabel(brand, text="MX SYNC", font=T.title_font(22), text_color=T.TEXT, height=24).pack(anchor="w")
        ctk.CTkLabel(brand, text=f"v{VERSION}", font=T.font(11), text_color=T.FAINT, height=14).pack(anchor="w")
        ctk.CTkFrame(self, fg_color=T.BORDER, width=2, height=34).pack(side="left", padx=18)
        me = ctk.CTkFrame(self, fg_color="transparent")
        me.pack(side="left")
        self.me = ctk.CTkLabel(me, text="", font=T.font(14, "bold"), text_color=T.TEXT, height=20, anchor="w")
        self.me.pack(anchor="w")
        self.me_sub = ctk.CTkLabel(me, text="", font=T.font(11), text_color=T.MUTED, height=15, anchor="w")
        self.me_sub.pack(anchor="w")

        T.button(self, "Ustawienia", app.open_settings, width=110, height=34).pack(side="right", padx=(8, 18))
        self.speed = ctk.CTkLabel(self, text="", font=("Consolas", 14, "bold"), text_color=T.TEXT)
        self.speed.pack(side="right", padx=10)
        self.status = ctk.CTkLabel(self, text="", font=T.font(12, "bold"), corner_radius=10, height=26,
                                   fg_color=T.CARD, text_color=T.MUTED)
        self.status.pack(side="right", padx=10)

    def refresh(self):
        node = self.app.node
        lib = node.library
        mods = lib.snapshot()
        self.me.configure(text=f"Ty: {T.shorten(node.name, 24)}")
        self.me_sub.configure(text=f"{plural_mods(len(mods))}  ·  {fmt_size(sum(m.size for m in mods.values()))}"
                                   f"  ·  udostępniasz wszystko")
        if lib.error:
            self.status.configure(text="  ustaw folder modów  ", text_color=T.RED)
        elif lib.scanning:
            d, t = lib.progress
            stage = f"  ·  {lib.stage[2]}" if lib.stage else ""
            what = "sprawdzam integralność" if node.verifying else "skanuję mody"
            self.status.configure(text=f"  {what} {d}/{t}{stage}  ", text_color=T.ACCENT2)
        else:
            n = len(node.players.online())
            self.status.configure(text=f"  online  ·  {n} {'gracz' if n == 1 else 'graczy'}  ",
                                  text_color=T.GREEN if n else T.MUTED)
        eng = node.engine
        self.speed.configure(text=f"↓ {fmt_speed(eng.down_rate):>10}   ↑ {fmt_speed(eng.up_rate):>10}")
