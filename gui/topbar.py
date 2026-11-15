"""Górny pasek: logo, kim jestem, stan (skan / gracze), prędkości i ustawienia."""
import os

import customtkinter as ctk
from PIL import Image, ImageSequence

from gui import theme as T
from utils.files import resource_path
from utils.fmt import fmt_size, fmt_speed, plural_mods
from utils.version import VERSION

LOGO_H = 44          # wysokość animowanego logo w pasku (px, przed skalowaniem DPI)
MIN_FRAME_MS = 20    # minimalny czas klatki
DEFAULT_FRAME_MS = 90
HIDDEN_POLL_MS = 500  # co ile sprawdzać, czy okno wróciło z zasobnika


def load_gif_frames(path, height=LOGO_H, bg=None):
    """Wczytuje wszystkie klatki GIF-a jako RGBA, skaluje do `height` z zachowaniem proporcji.

    Zwraca listę (PIL.Image, czas_ms). Jeśli podano `bg` (np. "#111216"), klatki są nakładane
    na to tło przed skalowaniem, więc na krawędziach nie zostają ciemne/jasne obwódki.
    """
    out = []
    with Image.open(path) as im:
        for frame in ImageSequence.Iterator(im):
            rgba = frame.convert("RGBA")  # Pillow składa klatki częściowe (disposal)
            if bg:
                base = Image.new("RGBA", rgba.size, bg)
                rgba = Image.alpha_composite(base, rgba)
            w = max(1, round(rgba.width * height / rgba.height))
            ms = frame.info.get("duration") or DEFAULT_FRAME_MS
            out.append((rgba.resize((w, height), Image.LANCZOS), max(MIN_FRAME_MS, int(ms))))
    return out


class AnimatedLogo(ctk.CTkLabel):
    """Etykieta z zapętlonym GIF-em; nie podmienia klatek, gdy okno jest schowane do zasobnika."""

    def __init__(self, master, frames, **kw):
        super().__init__(master, text="", **kw)
        # CTkImage sam skaluje pod DPI, więc obraz jest ostry przy każdym skalowaniu Windows
        self._frames = [(ctk.CTkImage(img, size=img.size), ms) for img, ms in frames]
        self._i = 0
        self._job = None
        self.configure(image=self._frames[0][0])
        if len(self._frames) > 1:
            self._job = self.after(self._frames[0][1], self._tick)

    def _tick(self):
        self._job = None
        try:
            hidden = self.winfo_toplevel().state() == "withdrawn"
        except Exception:
            return
        if hidden:
            self._job = self.after(HIDDEN_POLL_MS, self._tick)
            return
        self._i = (self._i + 1) % len(self._frames)
        img, ms = self._frames[self._i]
        self.configure(image=img)
        self._job = self.after(ms, self._tick)

    def destroy(self):
        if self._job is not None:
            try:
                self.after_cancel(self._job)
            except Exception:
                pass
            self._job = None
        super().destroy()


def make_logo(master):
    """Animowane logo z assets/logo.gif, a gdy go nie ma (lub jest uszkodzony) - statyczne wheel.png."""
    try:
        frames = load_gif_frames(resource_path(os.path.join("assets", "logo.gif")), bg=T.SIDEBAR)
        if frames:
            return AnimatedLogo(master, frames)
    except (OSError, ValueError, EOFError):
        pass
    try:
        img = Image.open(resource_path(os.path.join("assets", "wheel.png")))
        return ctk.CTkLabel(master, image=ctk.CTkImage(img, size=(38, 38)), text="")
    except OSError:
        return None


class TopBar(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color=T.SIDEBAR, corner_radius=0, height=64)
        self.pack_propagate(False)
        self.app = app
        logo = make_logo(self)
        if logo is not None:
            logo.pack(side="left", padx=(18, 10))
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
