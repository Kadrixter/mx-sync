"""Szybka lista modów na Canvasie – rysuje tylko widoczne wiersze (setki modów bez zacinania).

Wiersz: dict(id, kind, name, path, size, extra, chip, chip_color, checkable)
Nagłówek sekcji: dict(header=True, kind, label) – kliknięcie zaznacza/odznacza całą sekcję.
Grupa modów (folder z paczkami): dict(group=True, id, kind, name, path, size, members, extra) –
checkbox grupy zaznacza wszystkie jej mody (kreska = zaznaczona część).
"""
import tkinter as tk
import tkinter.font as tkfont

import customtkinter as ctk

from gui import theme as T
from utils.fmt import fmt_size

ROW_H = 44
HEAD_H = 34


class ModTable(ctk.CTkFrame):
    def __init__(self, master, on_change=None, checkable=True, empty="Brak modów"):
        super().__init__(master, fg_color=T.CARD, corner_radius=12)
        self.on_change = on_change
        self.checkable = checkable
        self.empty = empty
        self.rows = []
        self.checked = set()
        self._can = set()           # mody, które da się zaznaczyć
        self._y = []                # górna krawędź każdego wiersza
        self._total = 0
        self._top = 0
        self._hover = None
        self.cv = tk.Canvas(self, bg=T.CARD, highlightthickness=0, bd=0)
        self.cv.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=8)
        self.sb = ctk.CTkScrollbar(self, command=self._scroll_to, button_color=T.ROW_HOVER,
                                   button_hover_color=T.FAINT)
        self.sb.pack(side="right", fill="y", padx=(2, 6), pady=8)
        self.f_name = tkfont.Font(family="Segoe UI", size=-14, weight="bold")
        self.f_small = tkfont.Font(family="Segoe UI", size=-12)
        self.f_badge = tkfont.Font(family="Consolas", size=-14, weight="bold")
        self.f_head = tkfont.Font(family=T.title_family(), size=-13, weight="bold")
        self.cv.bind("<Configure>", lambda e: self._render())
        self.cv.bind("<Motion>", self._motion)
        self.cv.bind("<Leave>", lambda e: self._set_hover(None))
        self.cv.bind("<Button-1>", self._click)
        for w in (self.cv, self):
            w.bind("<Enter>", lambda e: self.cv.bind_all("<MouseWheel>", self._wheel))
            w.bind("<Leave>", lambda e: self.cv.unbind_all("<MouseWheel>"), add="+")

    # ---------- dane ----------

    def set_rows(self, rows, keep_checks=True):
        ids = {r["id"] for r in rows if _is_mod(r) and r.get("checkable", True)}
        self.checked = (self.checked & ids) if keep_checks else set()
        self._can = ids
        self.rows = rows
        self._y, y = [], 0
        for r in rows:
            self._y.append(y)
            y += HEAD_H if r.get("header") else ROW_H
        self._total = y
        self._top = max(0, min(self._top, self._total - self.cv.winfo_height()))
        self._render()

    def checked_ids(self):
        return [r["id"] for r in self.rows if _is_mod(r) and r["id"] in self.checked]

    def set_all(self, value):
        self.checked = set(self._can) if value else set()
        self._render()
        self._changed()

    def _changed(self):
        if self.on_change:
            self.on_change()

    # ---------- przewijanie ----------

    def _wheel(self, e):
        self._top = max(0, min(self._top - e.delta // 120 * ROW_H, max(0, self._total - self.cv.winfo_height())))
        self._render()

    def _scroll_to(self, *args):
        h = self.cv.winfo_height()
        if args[0] == "moveto":
            self._top = float(args[1]) * self._total
        elif args[0] == "scroll":
            self._top += int(args[1]) * (ROW_H if args[2] == "units" else h)
        self._top = max(0, min(self._top, max(0, self._total - h)))
        self._render()

    # ---------- mysz ----------

    def _row_at(self, y):
        y += self._top
        lo, hi = 0, len(self._y) - 1
        while lo <= hi:
            mid = (lo + hi) // 2
            if self._y[mid] <= y:
                lo = mid + 1
            else:
                hi = mid - 1
        i = lo - 1
        return i if 0 <= i < len(self.rows) and y < self._total else None

    def _motion(self, e):
        self._set_hover(self._row_at(e.y))

    def _set_hover(self, i):
        if i != self._hover:
            self._hover = i
            r = self.rows[i] if i is not None else None
            clickable = r is not None and self.checkable and (r.get("header") or r.get("checkable", True))
            self.cv.configure(cursor="hand2" if clickable else "")
            self._render()

    def _click(self, e):
        i = self._row_at(e.y)
        if i is None or not self.checkable:
            return
        r = self.rows[i]
        if r.get("header"):
            group = [x["id"] for x in self.rows if _is_mod(x) and x["kind"] == r["kind"]
                     and x.get("checkable", True)]
            if not group or not r.get("selectable", True):
                return
            on = not all(g in self.checked for g in group)
            self.checked = (self.checked | set(group)) if on else (self.checked - set(group))
        elif r.get("group"):
            members = [m for m in r["members"] if m in self._can]
            if not members:
                return
            on = not all(m in self.checked for m in members)
            self.checked = (self.checked | set(members)) if on else (self.checked - set(members))
        elif r.get("checkable", True):
            self.checked ^= {r["id"]}
        else:
            return
        self._render()
        self._changed()

    # ---------- rysowanie ----------

    def _render(self):
        cv = self.cv
        cv.delete("all")
        w, h = cv.winfo_width(), cv.winfo_height()
        if w < 10:
            return
        if not self.rows:
            cv.create_text(w / 2, max(60, h / 3), text=self.empty, fill=T.MUTED, font=self.f_name)
            self.sb.set(0, 1)
            return
        top = self._top
        first = self._row_at(0) or 0
        for i in range(first, len(self.rows)):
            y = self._y[i] - top
            if y > h:
                break
            r = self.rows[i]
            if r.get("header"):
                self._draw_header(r, y, w)
            elif r.get("group"):
                self._draw_group(r, y, w, i == self._hover)
            else:
                self._draw_row(r, y, w, i == self._hover)
        if self._total > 0:
            self.sb.set(top / self._total, min(1.0, (top + h) / self._total))

    def _draw_header(self, r, y, w):
        cv = self.cv
        glyph, color = T.KIND_STYLE.get(r["kind"], ("*", T.MUTED))
        cv.create_text(10, y + HEAD_H / 2 + 3, text=r["label"].upper(), anchor="w", fill=color, font=self.f_head)
        if self.checkable and r.get("selectable", True):
            cv.create_text(w - 12, y + HEAD_H / 2 + 3, text="zaznacz grupę", anchor="e", fill=T.MUTED,
                           font=self.f_small)

    def _checkbox(self, x, y, state, can):
        """state: 0 – pusty, 1 – część zaznaczona (kreska), 2 – zaznaczony."""
        cv = self.cv
        box = T.ACCENT if state else (T.ROW_HOVER if can else T.ROW)
        _round(cv, x, y + 13, x + 18, y + 31, 5, box, outline="" if state else (T.FAINT if can else T.BORDER))
        if state == 2:
            cv.create_line(x + 4, y + 22, x + 8, y + 26, x + 14, y + 17, fill="#111111", width=2.4,
                           capstyle="round", joinstyle="round")
        elif state == 1:
            cv.create_line(x + 4, y + 22, x + 14, y + 22, fill="#111111", width=2.4, capstyle="round")

    def _draw_group(self, r, y, w, hover):
        cv = self.cv
        members = [m for m in r["members"] if m in self._can]
        n_on = sum(1 for m in members if m in self.checked)
        state = 2 if members and n_on == len(members) else (1 if n_on else 0)
        _round(cv, 4, y + 3, w - 4, y + ROW_H - 3, 8, T.CARD_SEL if state else (T.CARD_HOVER if hover else T.ROW))
        _round(cv, 4, y + 3, 9, y + ROW_H - 3, 2, T.KIND_STYLE.get(r["kind"], ("", T.MUTED))[1])
        x = 18
        if self.checkable:
            self._checkbox(x, y, state, bool(members))
            x += 30
        _round(cv, x, y + 10, x + 24, y + 34, 6, T.BG)
        cv.create_text(x + 12, y + 22, text="[]", fill=T.ACCENT2, font=self.f_badge)
        x += 36
        right = w - 16
        info = f"{r['count']} w grupie" + (f"  ·  zaznaczono {n_on}" if n_on else "")
        cv.create_text(right, y + 22, text=fmt_size(r.get("size", 0)), anchor="e", fill=T.TEXT, font=self.f_small)
        right -= 92
        cv.create_text(right, y + 22, text=info, anchor="e", fill=T.ACCENT2 if n_on else T.MUTED, font=self.f_small)
        right -= self.f_small.measure(info) + 16
        if r.get("extra"):
            cv.create_text(right, y + 22, text=r["extra"], anchor="e", fill=T.MUTED, font=self.f_small)
            right -= self.f_small.measure(r["extra"]) + 16
        cv.create_text(x, y + 15, text=_fit(self.f_name, r["name"], right - x), anchor="w", fill=T.TEXT,
                       font=self.f_name)
        cv.create_text(x, y + 31, text=_fit(self.f_small, r.get("path", ""), right - x), anchor="w",
                       fill=T.FAINT, font=self.f_small)

    def _draw_row(self, r, y, w, hover):
        cv = self.cv
        y1, y2 = y + 3, y + ROW_H - 3
        on = r["id"] in self.checked
        bg = T.CARD_SEL if on else (T.CARD_HOVER if hover else T.ROW)
        _round(cv, 4, y1, w - 4, y2, 8, bg)
        x = 14
        if self.checkable:
            self._checkbox(x, y, 2 if on else 0, r.get("checkable", True))
            x += 30
        glyph, color = T.KIND_STYLE.get(r["kind"], ("*", T.MUTED))
        _round(cv, x, y + 10, x + 24, y + 34, 6, T.BG)
        cv.create_text(x + 12, y + 22, text=glyph, fill=color, font=self.f_badge)
        x += 36
        right = w - 16
        chip = r.get("chip")
        if chip:
            cw = self.f_small.measure(chip) + 20
            _round(cv, right - cw, y + 12, right, y + 32, 10, T.BG)
            cv.create_text(right - cw / 2, y + 22, text=chip, fill=r.get("chip_color", T.MUTED), font=self.f_small)
            right -= cw + 14
        cv.create_text(right, y + 22, text=fmt_size(r.get("size", 0)), anchor="e", fill=T.TEXT, font=self.f_small)
        right -= 92
        extra = r.get("extra")
        if extra:
            cv.create_text(right, y + 22, text=extra, anchor="e", fill=r.get("extra_color", T.MUTED),
                           font=self.f_small)
            right -= self.f_small.measure(extra) + 16
        name = _fit(self.f_name, r["name"], right - x)
        cv.create_text(x, y + 15, text=name, anchor="w", fill=T.TEXT, font=self.f_name)
        cv.create_text(x, y + 31, text=_fit(self.f_small, r.get("path", ""), right - x), anchor="w",
                       fill=T.FAINT, font=self.f_small)


def _is_mod(r):
    return not r.get("header") and not r.get("group")


def _round(cv, x1, y1, x2, y2, r, fill, outline=""):
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2, x2 - r, y2,
           x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return cv.create_polygon(pts, smooth=True, fill=fill, outline=outline)


def _fit(font, text, width):
    if width <= 20 or font.measure(text) <= width:
        return text
    while text and font.measure(text + "…") > width:
        text = text[:-1]
    return text + "…"
