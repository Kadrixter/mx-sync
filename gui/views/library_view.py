"""Moja biblioteka: folder modów, stan skanowania i lista moich modów (ilu graczy ma każdy)."""
import os

import customtkinter as ctk

from core.mods import KIND_GROUPS, KIND_PLURAL, mod_dir
from gui import theme as T
from gui.mod_table import ModTable
from gui.widgets import AnimatedProgressBar
from utils.fmt import fmt_size, plural_mods


class LibraryView(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self._sig = None

        head = ctk.CTkFrame(self, fg_color=T.CARD, corner_radius=14)
        head.pack(fill="x", pady=(0, 12))
        top = ctk.CTkFrame(head, fg_color="transparent")
        top.pack(fill="x", padx=18, pady=(14, 4))
        ctk.CTkLabel(top, text="Moja biblioteka", font=T.title_font(26), text_color=T.TEXT).pack(side="left")
        T.button(top, "Skanuj ponownie", app.node.rescan, width=140).pack(side="right")
        T.button(top, "Otwórz folder", self._open, width=120).pack(side="right", padx=8)
        T.button(top, "Zmień folder", app.open_settings, width=120).pack(side="right")
        self.folder = ctk.CTkLabel(head, text="", font=T.font(12), text_color=T.MUTED, anchor="w")
        self.folder.pack(fill="x", padx=18)
        self.stats = ctk.CTkLabel(head, text="", font=T.font(13, "bold"), text_color=T.TEXT, anchor="w")
        self.stats.pack(fill="x", padx=18, pady=(4, 0))
        self.scan_lbl = ctk.CTkLabel(head, text="", font=T.font(12), text_color=T.ACCENT2, anchor="w")
        self.bar = AnimatedProgressBar(head, height=10, bg=T.CARD)
        ctk.CTkFrame(head, fg_color="transparent", height=10).pack(side="bottom")

        self.table = ModTable(self, checkable=False, empty="Brak modów w folderze")
        self.table.pack(fill="both", expand=True)
        self.refresh(force=True)

    def _open(self):
        if self.app.node.folder and os.path.isdir(self.app.node.folder):
            os.startfile(self.app.node.folder)

    def refresh(self, force=False):
        node = self.app.node
        lib = node.library
        self.folder.configure(text=f"Folder: {node.folder or 'nie ustawiony'}",
                              text_color=T.RED if lib.error else T.MUTED)
        mods = lib.snapshot()
        per_kind = {}
        for m in mods.values():
            per_kind[m.kind] = per_kind.get(m.kind, 0) + 1
        kinds = "   ".join(f"{KIND_PLURAL[k].lower()} {per_kind[k]}" for k, _ in KIND_GROUPS if k in per_kind)
        self.stats.configure(text=f"{plural_mods(len(mods))}  ·  {fmt_size(sum(m.size for m in mods.values()))}"
                                  + (f"   ·   {kinds}" if kinds else ""))
        if lib.error:
            self.scan_lbl.configure(text=lib.error, text_color=T.RED)
            self.scan_lbl.pack(fill="x", padx=18, pady=(6, 0))
        elif lib.scanning:
            done, total = lib.progress
            cur = f"  ·  liczę: {lib.current} {round(lib.current_pct * 100)}%" if lib.current else ""
            self.scan_lbl.configure(text=f"Przygotowuję mody do udostępniania: {done} / {total}{cur}  "
                                         "(pierwszy raz trwa dłużej, potem sekundy)", text_color=T.ACCENT2)
            self.scan_lbl.pack(fill="x", padx=18, pady=(6, 0))
            self.bar.pack(fill="x", padx=18, pady=(6, 0))
            self.bar.set(done / total if total else 0)
        else:
            self.scan_lbl.pack_forget()
            self.bar.pack_forget()

        counts = self.app.cache.holders_count()
        rows, groups = [], {}
        for m in mods.values():
            groups.setdefault(m.kind, []).append(m)
        for kind, _ in KIND_GROUPS:
            g = sorted(groups.get(kind, []), key=lambda m: m.name.lower())
            if not g:
                continue
            rows.append({"header": True, "kind": kind, "selectable": False,
                         "label": f"{KIND_PLURAL[kind]}  ·  {len(g)}  ·  {fmt_size(sum(m.size for m in g))}"})
            for m in g:
                n = counts.get(m.ih, 0)
                rows.append({"id": m.ih, "kind": m.kind, "name": m.name, "path": mod_dir(m.key) or "mods",
                             "size": m.size, "extra": f"ma też {n} graczy" if n > 1 else
                             ("ma też 1 gracz" if n == 1 else "tylko ty"),
                             "extra_color": T.GREEN if n else T.MUTED,
                             "chip": "UDOSTĘPNIASZ", "chip_color": T.CYAN})
        sig = tuple((r.get("id"), r.get("extra"), r.get("label")) for r in rows)
        if force or sig != self._sig:
            self._sig = sig
            self.table.set_rows(rows)
