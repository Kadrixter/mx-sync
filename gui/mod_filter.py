"""Pasek nad listą modów: wyszukiwarka (lupka) i grupy (Mapy, Motory, Opony…)."""
import customtkinter as ctk

from gui import theme as T
from net.client import KIND_GROUPS

ALL = "Wszystkie"
GROUP_ICONS = {"Mapa": "🏁", "Motor": "🏍", "Opony": "◎", "Kask": "⛑", "Strój": "🧤",
               "Rider": "🪖", "Inne": "📦"}
DEBOUNCE_MS = 250


class ModFilterBar(ctk.CTkFrame):
    """on_change() wywoływane po zmianie frazy lub grupy; matches(mod) mówi, czy mod pasuje."""

    def __init__(self, master, on_change):
        super().__init__(master, fg_color="transparent")
        self.on_change = on_change
        self.kind = None            # None = wszystkie grupy
        self._labels = {}           # tekst przycisku -> rodzaj
        self._job = None

        box = ctk.CTkFrame(self, fg_color=T.ROW, corner_radius=8)
        box.pack(side="left", padx=(0, 8))
        ctk.CTkLabel(box, text="🔍", font=T.font(14), text_color=T.MUTED, width=26).pack(side="left", padx=(8, 0))
        self.entry = ctk.CTkEntry(box, width=220, height=30, border_width=0, fg_color=T.ROW,
                                  placeholder_text="Szukaj moda…", placeholder_text_color=T.MUTED,
                                  text_color=T.TEXT, font=T.font(13))
        self.entry.pack(side="left", padx=(0, 2), pady=2)
        self.entry.bind("<KeyRelease>", self._typed)
        self.entry.bind("<Escape>", lambda e: self.clear_search())
        self.clear_btn = ctk.CTkButton(box, text="✕", width=26, height=26, fg_color="transparent",
                                       hover_color=T.ROW_HOVER, text_color=T.MUTED, command=self.clear_search)

        self.groups = ctk.CTkSegmentedButton(self, values=[ALL], command=self._group_clicked,
                                             font=T.font(12, "bold"), selected_color=T.ACCENT,
                                             selected_hover_color=T.ACCENT_HOVER, unselected_color=T.ROW,
                                             unselected_hover_color=T.ROW_HOVER, fg_color=T.PANEL,
                                             text_color=T.TEXT, height=30)
        self.groups.pack(side="left", fill="x", expand=True)
        self.groups.set(ALL)

    # ----- stan -----

    @property
    def query(self):
        return self.entry.get().strip().lower()

    def matches(self, mod, ignore_kind=False):
        if not ignore_kind and self.kind and mod.kind != self.kind:
            return False
        q = self.query
        return not q or all(w in f"{mod.name} {mod.path}".lower() for w in q.split())

    def active(self):
        return bool(self.kind or self.query)

    def set_counts(self, mods):
        """Przyciski grup z liczbą modów (tylko grupy, które występują)."""
        counts = {}
        for g in mods:
            if self.matches(g, ignore_kind=True):
                counts[g.kind] = counts.get(g.kind, 0) + 1
        self._labels = {f"{ALL} ({sum(counts.values())})": None}
        for kind, label in KIND_GROUPS:
            if counts.get(kind) or kind == self.kind:
                self._labels[f"{GROUP_ICONS.get(kind, '')} {label} ({counts.get(kind, 0)})"] = kind
        self.groups.configure(values=list(self._labels))
        self.groups.set(next(t for t, k in self._labels.items() if k == self.kind))

    # ----- zdarzenia -----

    def _group_clicked(self, value):
        self.kind = self._labels.get(value)
        self.on_change()

    def _typed(self, _e=None):
        if self.entry.get():
            self.clear_btn.pack(side="left", padx=(0, 4))
        else:
            self.clear_btn.pack_forget()
        if self._job:
            self.after_cancel(self._job)
        self._job = self.after(DEBOUNCE_MS, self._fire)

    def _fire(self):
        self._job = None
        self.on_change()

    def _clear_entry(self):
        # pusty CTkEntry trzyma w środku placeholder – delete() skasowałby i jego
        if self.entry.get():
            self.entry.delete(0, "end")

    def clear_search(self):
        self._clear_entry()
        self._typed()

    def reset(self):
        self.kind = None
        self._clear_entry()
        self.clear_btn.pack_forget()
