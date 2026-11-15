"""Moja biblioteka: folder modów, stan skanowania i lista moich modów (ilu graczy ma każdy)."""
import os

import customtkinter as ctk

from core.mods import KIND_GROUPS, KIND_PLURAL
from gui import theme as T
from gui.mod_table import ModTable
from gui.rows import build_rows, filter_mods, players_text
from gui.views.mods_view import KINDS
from gui.widgets import AnimatedProgressBar, MinHolders, SearchBox
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

        filt = ctk.CTkFrame(self, fg_color="transparent")
        filt.pack(fill="x", pady=(0, 8))
        self.kind, self.min_holders = "", 1
        self.kinds = ctk.CTkSegmentedButton(filt, values=[k for _, k in KINDS], command=self._kind_clicked,
                                            font=T.font(12), height=28, fg_color=T.BG,
                                            selected_color=T.ROW_HOVER, selected_hover_color=T.ROW_HOVER,
                                            unselected_color=T.BG, unselected_hover_color=T.CARD,
                                            text_color=T.TEXT)
        self.kinds.set("Wszystko")
        self.kinds.pack(side="left")
        self.search = SearchBox(filt, lambda: self.refresh(force=True), "szukaj w moich modach…")
        self.search.pack(side="right")
        MinHolders(self, 1, self._min_changed).pack(anchor="e", pady=(0, 8))
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
            stage = f"etap {lib.stage[0]}/{lib.stage[1]} ({lib.stage[2]})  ·  " if lib.stage else ""
            what = "Sprawdzam integralność" if node.verifying else "Przygotowuję mody do udostępniania"
            self.scan_lbl.configure(text=f"{what}: {stage}{done} / {total}{cur}  ·  gotowe etapy są już "
                                         "udostępniane", text_color=T.ACCENT2)
            self.scan_lbl.pack(fill="x", padx=18, pady=(6, 0))
            self.bar.pack(fill="x", padx=18, pady=(6, 0))
            self.bar.set(done / total if total else 0)
        else:
            self.scan_lbl.pack_forget()
            self.bar.pack_forget()

        counts = self.app.cache.holders_count()
        # „ilu graczy ma” w bibliotece liczy też ciebie (masz każdy z tych modów)
        mine_counts = {m.ih: counts.get(m.ih, 0) + 1 for m in mods.values()}
        query = self.search.get()
        shown = filter_mods(list(mods.values()), query, self.kind, self.min_holders, mine_counts)

        def row(m):
            n = counts.get(m.ih, 0)
            return {"extra": f"ma też {players_text(n)}" if n else "tylko ty",
                    "extra_color": T.GREEN if n else T.MUTED, "chip": "UDOSTĘPNIASZ", "chip_color": T.CYAN}
        rows = build_rows(shown, row, checkable=False)
        sig = tuple((r.get("id"), r.get("extra"), r.get("label"), r.get("count")) for r in rows)
        if force or sig != self._sig:
            self._sig = sig
            hidden = len(mods) - len(shown)
            self.table.empty = ("Nic nie pasuje do filtra :/" if hidden else "Brak modów w folderze")
            self.table.set_rows(rows)

    def _kind_clicked(self, value):
        self.kind = next(k for k, v in KINDS if v == value)
        self.refresh(force=True)

    def _min_changed(self, value):
        self.min_holders = value
        self.refresh(force=True)
