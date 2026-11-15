"""Własne widgety: animowany pasek postępu i kółko z procentem."""
import tkinter as tk


from gui import theme as T


def _rr(x1, y1, x2, y2, r):
    """Punkty zaokrąglonego prostokąta dla create_polygon(smooth=True)."""
    return [x1 + r, y1, x1 + r, y1, x2 - r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
            x2, y1 + r, x2, y2 - r, x2, y2 - r, x2, y2, x2 - r, y2, x2 - r, y2,
            x1 + r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y2 - r, x1, y1 + r,
            x1, y1 + r, x1, y1]


class AnimatedProgressBar(tk.Canvas):
    """Pasek z płynnym dojazdem do wartości, gradientem koloru i przesuwającym się
    połyskiem. Tryb nieokreślony = przesuwający się blok."""

    def __init__(self, master, height=14, bg=T.PANEL, **kw):
        super().__init__(master, height=height, bg=bg, highlightthickness=0, bd=0, **kw)
        self._h = height
        self._target = 0.0
        self._shown = 0.0
        self._phase = 0.0
        self._indeterminate = False
        self._color = None
        self._track = self.create_polygon(0, 0, 0, 0, smooth=True, fill=T.TRACK, outline="")
        self._fill = self.create_polygon(0, 0, 0, 0, smooth=True, fill=T.ACCENT, outline="")
        self._shine = self.create_polygon(0, 0, 0, 0, smooth=True, fill=T.ACCENT, outline="")
        self._job = None
        self._tick()

    def set(self, value):
        self._target = max(0.0, min(1.0, value))
        self._indeterminate = False

    def set_indeterminate(self, on=True):
        self._indeterminate = on

    def set_color(self, color=None):
        """Wymusza kolor (np. zielony po zakończeniu); None = gradient."""
        self._color = color

    def destroy(self):
        if self._job:
            self.after_cancel(self._job)
            self._job = None
        super().destroy()

    def _tick(self):
        diff = self._target - self._shown
        self._shown = self._target if abs(diff) < 0.0005 else self._shown + diff * 0.15
        self._phase = (self._phase + 0.012) % 1.0
        self._draw()
        self._job = self.after(33, self._tick)

    def _draw(self):
        w, h = self.winfo_width(), self._h
        if w < 4:
            return
        self.coords(self._track, *_rr(0, 0, w, h, h / 2))

        if self._indeterminate:
            seg = w * 0.28
            x = (self._phase * 1.4 - 0.2) * w
            x1, x2 = max(0, x), min(w, x + seg)
            if x2 - x1 < 2:
                self.itemconfigure(self._fill, state="hidden")
            else:
                color = T.lerp_color(T.ACCENT, T.ACCENT2, self._phase)
                self.coords(self._fill, *_rr(x1, 0, x2, h, min(h / 2, (x2 - x1) / 2)))
                self.itemconfigure(self._fill, fill=color, state="normal")
            self.itemconfigure(self._shine, state="hidden")
            return

        fw = self._shown * w
        if fw < 1:
            self.itemconfigure(self._fill, state="hidden")
            self.itemconfigure(self._shine, state="hidden")
            return
        color = self._color or T.lerp_color(T.ACCENT, T.ACCENT2, self._shown)
        self.coords(self._fill, *_rr(0, 0, fw, h, min(h / 2, fw / 2)))
        self.itemconfigure(self._fill, fill=color, state="normal")

        sw = 60
        sx = self._phase * (fw + sw) - sw
        x1, x2 = max(0, sx), min(fw, sx + sw)
        if self._color is None and x2 - x1 > 3 and h > 6:
            self.coords(self._shine, *_rr(x1, 2, x2, h - 2, min((h - 4) / 2, (x2 - x1) / 2)))
            self.itemconfigure(self._shine, fill=T.lerp_color(color, "#ffffff", 0.3), state="normal")
        else:
            self.itemconfigure(self._shine, state="hidden")


class Ring(tk.Canvas):
    """Kółko z procentem zgodności (łuk w kolorze zależnym od wartości)."""

    def __init__(self, master, size=48, width=5, bg=T.CARD, font_size=None):
        super().__init__(master, width=size, height=size, bg=bg, highlightthickness=0, bd=0)
        self.size, self.w = size, width
        self.value = None
        fs = font_size or max(9, size // 4)
        self._font = (T.title_family(), -fs, "bold")
        self._shown = 0.0
        self._job = None

    def set(self, value, text=None, color=None):
        """value 0–100 albo None (nieznane – szare kółko z tekstem)."""
        self.value, self._text, self._color = value, text, color
        self._animate()

    def _animate(self):
        target = self.value or 0
        diff = target - self._shown
        self._shown = target if abs(diff) < 0.5 else self._shown + diff * 0.25
        self._draw()
        if self._shown != target:
            self._job = self.after(30, self._animate)

    def _draw(self):
        self.delete("all")
        s, w = self.size, self.w
        pad = w / 2 + 1
        self.create_oval(pad, pad, s - pad, s - pad, outline=T.TRACK, width=w)
        if self.value is not None and self._shown > 0:
            color = self._color or T.percent_color(self.value)
            extent = -359.9 * self._shown / 100
            self.create_arc(pad, pad, s - pad, s - pad, start=90, extent=extent, style="arc",
                            outline=color, width=w)
        text = self._text if self._text is not None else (f"{round(self._shown)}%" if self.value is not None else "?")
        self.create_text(s / 2, s / 2 + 1, text=text, fill=T.TEXT if self.value is not None else T.MUTED,
                         font=self._font)

    def destroy(self):
        if self._job:
            self.after_cancel(self._job)
            self._job = None
        super().destroy()
