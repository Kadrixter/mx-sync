"""Kolory i drobne helpery wyglądu – motyw w stylu MX Bikes (błoto, czerń, pomarańcz)."""
import tkinter.font as tkfont

import customtkinter as ctk

BG = "#0d0e10"
PANEL = "#16181c"
ROW = "#1f2126"
ROW_HOVER = "#2b2e35"
TRACK = "#2b2e35"
ACCENT = "#ff6b1a"          # pomarańcz jak plastiki crossa
ACCENT_HOVER = "#e2550a"
ACCENT2 = "#ffc21a"         # żółta tablica startowa
TEXT = "#f1f1f1"
MUTED = "#8f939c"
GREEN = "#3ddc84"
RED = "#ff5a5a"
YELLOW = "#ffd23f"
ORANGE = "#ff9a4a"
CYAN = "#38bdf8"            # Radmin VPN
PURPLE = "#b48cff"
SIDEBAR = "#111216"
CARD = "#17191e"
CARD_HOVER = "#1f2228"
CARD_SEL = "#2a1f17"        # zaznaczona karta (ciepły odcień pomarańczu)
BORDER = "#262930"
FAINT = "#5d616b"

# rodzaje modów: znaczek ASCII i kolor
KIND_STYLE = {"Mapa": ("#", ACCENT2), "Motor": (">", ACCENT), "Malowanie": ("%", YELLOW),
              "Opony": ("o", "#c9ccd3"), "Kask": ("^", CYAN), "Gogle": ("8", CYAN), "Strój": ("~", GREEN),
              "Rękawice": ("w", GREEN), "Buty": ("L", PURPLE), "Ochraniacze": ("=", PURPLE),
              "Postać": ("@", PURPLE), "Animacje": ("&", ORANGE), "Kamerka": ("c", ORANGE),
              "Font": ("f", MUTED), "Inne": ("*", MUTED)}


def percent_color(p):
    """Kolor zgodności: zielony (dużo wspólnych modów) -> żółty -> pomarańczowy."""
    if p >= 80:
        return GREEN
    if p >= 50:
        return YELLOW
    return ACCENT

_KINDS = {
    "primary": (ACCENT, ACCENT_HOVER, "#111111"),
    "secondary": (ROW, ROW_HOVER, TEXT),
    "danger": ("#b4383f", "#952d33", "#ffffff"),
    "success": ("#1f9d6b", "#178257", "#ffffff"),
}


_title_family = None


def title_family():
    """Bahnschrift (Windows 10+) – wąski, „wyścigowy” krój; inaczej Segoe UI."""
    global _title_family
    if _title_family is None:
        try:
            fams = set(tkfont.families())
        except Exception:
            fams = set()
        _title_family = next((f for f in ("Bahnschrift SemiBold", "Bahnschrift") if f in fams), "Segoe UI")
    return _title_family


def font(size=13, weight="normal"):
    return ctk.CTkFont(family="Segoe UI", size=size, weight=weight)


def title_font(size=22):
    fam = title_family()
    return ctk.CTkFont(family=fam, size=size, weight="normal" if "SemiBold" in fam else "bold")


def button(master, text, command=None, kind="secondary", **kw):
    fg, hover, txt = _KINDS[kind]
    kw.setdefault("height", 34)
    kw.setdefault("corner_radius", 8)
    kw.setdefault("font", font(13, "bold" if kind == "primary" else "normal"))
    b = ctk.CTkButton(master, text=text, command=command, fg_color=fg,
                      hover_color=hover, text_color=txt, text_color_disabled=FAINT, **kw)
    b.mx_fg = fg
    return b


def enable(btn, on):
    """Włącz / wyłącz przycisk; wyłączony ma szare tło (czytelnie widać, że nie da się kliknąć)."""
    state = "normal" if on else "disabled"
    if btn.cget("state") != state:
        btn.configure(state=state, fg_color=getattr(btn, "mx_fg", ROW) if on else ROW)


def lerp_color(c1, c2, t):
    t = max(0.0, min(1.0, t))
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))


def shorten(text, n=70):
    return text if len(text) <= n else text[:n - 1] + "…"
