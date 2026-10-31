"""Ekran startowy: okno przecięte ukośnie – lewa strona Klient, prawa Host.

Po najechaniu strona się poszerza, rozjaśnia i powiększa napisy;
po kliknięciu wypełnia cały ekran i przenosi do wybranego trybu.
U góry logo (koło MX), na dole flaga w szachownicę, wersja i przycisk aktualizacji.
"""
import math
import os
import tkinter as tk
import tkinter.font as tkfont

from gui import theme as T
from gui.base import View
from utils.files import resource_path
from utils.version import VERSION

CHECKER = 8          # bok pola flagi w szachownicę (px)

SIDES = {
    "client": {"color": T.ACCENT2, "icon": "⬇", "title": "KLIENT",
               "desc": "Pobierz brakujące mapy i mody od hosta", "phase": 0.0},
    "host": {"color": T.ACCENT, "icon": "⬆", "title": "HOST",
             "desc": "Udostępnij swoje mapy i mody", "phase": math.pi},
}


def _pill(x1, y1, x2, y2, r):
    """Zaokrąglony prostokąt dla create_polygon(smooth=True)."""
    return [x1 + r, y1, x1 + r, y1, x2 - r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
            x2, y1 + r, x2, y2 - r, x2, y2 - r, x2, y2, x2 - r, y2, x2 - r, y2,
            x1 + r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y2 - r, x1, y1 + r,
            x1, y1 + r, x1, y1]


class StartView(View):
    def __init__(self, app):
        super().__init__(app)
        self.cv = tk.Canvas(self, bg=T.BG, highlightthickness=0, bd=0, cursor="hand2")
        self.cv.pack(fill="both", expand=True)

        self.split = 0.5
        self.hover = {"client": 0.0, "host": 0.0}
        self.hovered = None
        self.leaving = None
        self.t = 0
        self._job = None

        title_fam = T.title_family()
        title_weight = "normal" if "SemiBold" in title_fam else "bold"

        self.poly = {s: self.cv.create_polygon(0, 0, 0, 0, outline="") for s in SIDES}
        self.glow = self.cv.create_line(0, 0, 0, 0, width=12, capstyle="round")
        self.line = self.cv.create_line(0, 0, 0, 0, width=3, capstyle="round")
        self.fonts, self.texts, self._sizes = {}, {}, {}
        for s, cfg in SIDES.items():
            f = {"icon": tkfont.Font(family="Segoe UI Symbol", size=-70, weight="bold"),
                 "title": tkfont.Font(family=title_fam, size=-48, weight=title_weight),
                 "desc": tkfont.Font(family="Segoe UI", size=-16),
                 "hint": tkfont.Font(family=title_fam, size=-14, weight=title_weight)}
            self.fonts[s] = f
            self.texts[s] = {
                "icon": self.cv.create_text(0, 0, text=cfg["icon"], font=f["icon"]),
                "title": self.cv.create_text(0, 0, text=cfg["title"], font=f["title"]),
                "desc": self.cv.create_text(0, 0, text=cfg["desc"], font=f["desc"]),
                "hint": self.cv.create_text(0, 0, text="KLIKNIJ, ABY WEJŚĆ  →" if s == "host"
                                            else "←  KLIKNIJ, ABY WEJŚĆ", font=f["hint"]),
            }

        # logo: koło MX na ciemnym „numerze startowym”
        self.logo_img = None
        logo = resource_path(os.path.join("assets", "wheel.png"))
        if os.path.exists(logo):
            try:
                self.logo_img = tk.PhotoImage(file=logo).subsample(2)
            except tk.TclError:
                self.logo_img = None
        self.logo_bg = self.cv.create_oval(0, 0, 0, 0, fill=T.BG, outline=T.ACCENT, width=3)
        self.logo = self.cv.create_image(0, 0, image=self.logo_img) if self.logo_img else None
        self.brand_bg = self.cv.create_polygon(0, 0, 0, 0, smooth=True, fill=T.BG, outline="")
        self.brand = self.cv.create_text(0, 0, text="MX SYNC", fill=T.TEXT,
                                         font=tkfont.Font(family=title_fam, size=-30, weight="bold"))
        self.brand_sub = self.cv.create_text(0, 0, text="MX BIKES MOD SYNC", fill=T.ACCENT,
                                             font=tkfont.Font(family=title_fam, size=-12, weight="bold"))

        self.footer = self.cv.create_text(0, 0, text="sieć lokalna i Radmin VPN",
                                          font=tkfont.Font(family="Segoe UI", size=-12), fill=T.MUTED)

        # flaga w szachownicę na dole
        self._checker_key = None
        self._checker = []

        # wersja + przycisk aktualizacji (rysowany na płótnie)
        small = tkfont.Font(family="Segoe UI", size=-12, weight="bold")
        self.version = self.cv.create_text(0, 0, text=f"v{VERSION}", font=small, fill=T.MUTED, anchor="w")
        self.upd_bg = self.cv.create_polygon(0, 0, 0, 0, smooth=True, fill=T.PANEL, outline=T.ROW_HOVER)
        self.upd_txt = self.cv.create_text(0, 0, text="⟳  Sprawdź aktualizacje", font=small,
                                           fill=T.TEXT, anchor="e")
        self._upd_hover = False
        self._upd_new = None
        if app.update_info is None:
            from gui.update_dialog import check_in_background
            check_in_background(self, self._update_checked)
        else:
            self._update_checked(app.update_info)

        self.cv.bind("<Motion>", self._on_motion)
        self.cv.bind("<Leave>", lambda e: (self._set_hover(None), setattr(self, "_upd_hover", False)))
        self.cv.bind("<Button-1>", self._on_click)
        self._tick()

    # ----- geometria -----

    def _geom(self):
        w, h = max(self.cv.winfo_width(), 2), max(self.cv.winfo_height(), 2)
        slant = h * 0.14
        mid = self.split * w
        return w, h, slant, mid + slant, mid - slant  # górny i dolny x przekątnej

    def _side_at(self, x, y):
        w, h, _, tx, bx = self._geom()
        return "client" if x < tx + (bx - tx) * y / h else "host"

    # ----- aktualizacje -----

    def _in_update_btn(self, x, y):
        box = self.cv.bbox(self.upd_bg)
        return bool(box) and box[0] <= x <= box[2] and box[1] <= y <= box[3]

    def _update_checked(self, info):
        self.app.update_info = info or False
        if info and info.newer:
            self._upd_new = info
            self.cv.itemconfigure(self.upd_txt, text=f"⬆  Dostępna aktualizacja {info.tag}")

    # ----- zdarzenia -----

    def _set_hover(self, side):
        if not self.leaving:
            self.hovered = side

    def _on_motion(self, e):
        self._upd_hover = self._in_update_btn(e.x, e.y)
        if self._upd_hover:
            self._set_hover(None)
            return
        self._set_hover(self._side_at(e.x, e.y))

    def _on_click(self, e):
        if self._in_update_btn(e.x, e.y):
            if not self.leaving:
                self.app.open_updates(self._upd_new)
            return
        if not self.leaving:
            self.leaving = self._side_at(e.x, e.y)
            self.hovered = self.leaving

    # ----- animacja -----

    def _tick(self):
        self.t += 1
        w, h, slant, _, _ = self._geom()
        if self.leaving:
            # strona rozlewa się na cały ekran (z zapasem na skos)
            target = 1 + slant / w + 0.02 if self.leaving == "client" else -slant / w - 0.02
            self.split += (target - self.split) * 0.16
        else:
            target = {"client": 0.58, "host": 0.42}.get(self.hovered, 0.5)
            self.split += (target - self.split) * 0.12
        for s in SIDES:
            goal = 1.0 if s == self.hovered else 0.0
            self.hover[s] += (goal - self.hover[s]) * 0.15
        self._render()

        if self.leaving and abs(target - self.split) < 0.01:
            self._job = None
            self._open(self.leaving)
            return
        self._job = self.after(16, self._tick)

    def _render(self):
        w, h, slant, tx, bx = self._geom()
        cv = self.cv
        cv.coords(self.poly["client"], 0, 0, tx, 0, bx, h, 0, h)
        cv.coords(self.poly["host"], tx, 0, w, 0, w, h, bx, h)

        hv_c, hv_h = self.hover["client"], self.hover["host"]
        line_color = T.lerp_color(T.lerp_color(T.ACCENT2, T.ACCENT, 0.5),
                                  T.ACCENT2 if hv_c > hv_h else T.ACCENT, max(hv_c, hv_h))
        cv.coords(self.glow, tx, -10, bx, h + 10)
        cv.coords(self.line, tx, -10, bx, h + 10)
        cv.itemconfigure(self.glow, fill=T.lerp_color(T.BG, line_color, 0.35))
        cv.itemconfigure(self.line, fill=line_color)

        mid = self.split * w
        centers = {"client": mid / 2 - slant * 0.3, "host": (mid + w) / 2 + slant * 0.3}
        for s, cfg in SIDES.items():
            hv = self.hover[s]
            color = cfg["color"]
            fill = T.lerp_color(T.BG, color, 0.08 + 0.20 * hv)
            cv.itemconfigure(self.poly[s], fill=fill)

            self._resize(s, "icon", 70 + 26 * hv)
            self._resize(s, "title", 48 + 12 * hv)

            cx, cy = centers[s], h / 2 + 30
            bob = math.sin(self.t / 18 + cfg["phase"]) * (4 + 6 * hv)
            items = self.texts[s]
            cv.coords(items["icon"], cx, cy - 78 + bob)
            cv.coords(items["title"], cx, cy + 14)
            cv.coords(items["desc"], cx, cy + 56)
            cv.coords(items["hint"], cx, cy + 96 + 6 * (1 - hv))
            cv.itemconfigure(items["icon"], fill=T.lerp_color(T.lerp_color(T.BG, color, 0.55), color, hv))
            cv.itemconfigure(items["title"], fill=T.lerp_color(T.MUTED, "#ffffff", 0.4 + 0.6 * hv))
            cv.itemconfigure(items["desc"], fill=T.lerp_color(T.MUTED, T.TEXT, hv))
            cv.itemconfigure(items["hint"], fill=T.lerp_color(fill, color, hv))

        self._render_chrome(w, h, tx, bx)

    def _render_chrome(self, w, h, tx, bx):
        cv = self.cv
        band = CHECKER * 2
        cols = w // CHECKER + 1
        if self._checker_key != (w, h):
            self._checker_key = (w, h)
            for i in self._checker:
                cv.delete(i)
            self._checker = []
            for row in range(2):
                for col in range(cols):
                    x, y = col * CHECKER, h - band + row * CHECKER
                    color = "#f1f1f1" if (col + row) % 2 == 0 else "#111111"
                    self._checker.append(cv.create_rectangle(x, y, x + CHECKER, y + CHECKER,
                                                             fill=color, outline=""))

        # logo u góry, na przekątnej
        lx = tx + (bx - tx) * 0.11
        cv.coords(self.logo_bg, lx - 46, 26, lx + 46, 118)
        if self.logo:
            cv.coords(self.logo, lx, 72)
        cv.coords(self.brand_bg, *_pill(lx - 96, 128, lx + 96, 184, 14))
        cv.coords(self.brand, lx, 150)
        cv.coords(self.brand_sub, lx, 173)

        # stopka nad flagą
        y = h - band - 24
        cv.coords(self.footer, w / 2, y)
        cv.coords(self.version, 18, y)
        right = w - 16
        cv.coords(self.upd_txt, right - 14, y)
        box = cv.bbox(self.upd_txt)
        if box:
            cv.coords(self.upd_bg, *_pill(box[0] - 14, y - 16, right, y + 16, 10))
        new, hov = self._upd_new is not None, self._upd_hover
        if new and hov:
            bg, outline, fg = T.ACCENT, T.ACCENT, "#111111"
        elif new or hov:
            bg, outline, fg = T.lerp_color(T.PANEL, T.ACCENT, 0.25), T.ACCENT, T.ACCENT2 if new else T.TEXT
        else:
            bg, outline, fg = T.PANEL, T.ROW_HOVER, T.TEXT
        cv.itemconfigure(self.upd_bg, fill=bg, outline=outline)
        cv.itemconfigure(self.upd_txt, fill=fg)
        for item in (self.logo_bg, self.logo, self.brand_bg, self.brand, self.brand_sub,
                     self.footer, self.version, self.upd_bg, self.upd_txt):
            if item:
                cv.tag_raise(item)

    def _resize(self, side, key, px):
        px = int(px)
        if self._sizes.get((side, key)) != px:
            self._sizes[(side, key)] = px
            self.fonts[side][key].configure(size=-px)

    def _open(self, side):
        if side == "host":
            from gui.host_view import HostSetupView
            self.app.show(HostSetupView)
        else:
            from gui.client_view import ClientServersView
            self.app.show(ClientServersView)

    def cleanup(self):
        if self._job:
            self.after_cancel(self._job)
            self._job = None
