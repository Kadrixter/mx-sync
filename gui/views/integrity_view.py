"""Integralność: czy mody o tej samej nazwie to na pewno te same pliki co u innych graczy.

„Sprawdź integralność” liczy sumy wszystkich moich modów od nowa (bez pamięci), a lista pokazuje
mody, które mam pod tą samą nazwą co inni, ale z inną zawartością. Dla każdego: pomiń albo pobierz
wersję innych (od wszystkich, którzy ją mają).
"""
import customtkinter as ctk

from core.compare import conflicts
from gui import theme as T
from gui.mod_table import ModTable
from gui.rows import build_rows, players_text
from gui.widgets import AnimatedProgressBar
from utils.fmt import fmt_size, plural_mods


class IntegrityView(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self._sig = None
        self._items = {}            # id wiersza (ih wersji innych) -> (mój Mod, ich Mod)

        head = ctk.CTkFrame(self, fg_color=T.CARD, corner_radius=14)
        head.pack(fill="x", pady=(0, 12))
        top = ctk.CTkFrame(head, fg_color="transparent")
        top.pack(fill="x", padx=18, pady=(14, 2))
        ctk.CTkLabel(top, text="Integralność plików", font=T.title_font(26), text_color=T.TEXT).pack(side="left")
        self.check_btn = T.button(top, "Sprawdź integralność", app.node.verify, kind="primary", width=190, height=36)
        self.check_btn.pack(side="right")
        ctk.CTkLabel(head, text="Sprawdza, czy mody o tej samej nazwie co u innych graczy to naprawdę te same "
                                "pliki. Pełne sprawdzenie liczy sumy wszystkich twoich modów od nowa.",
                     font=T.font(12), text_color=T.MUTED, anchor="w", justify="left", wraplength=760).pack(
            fill="x", padx=18)
        self.status = ctk.CTkLabel(head, text="", font=T.font(13, "bold"), text_color=T.TEXT, anchor="w")
        self.status.pack(fill="x", padx=18, pady=(6, 0))
        self.bar = AnimatedProgressBar(head, height=10, bg=T.CARD)
        ctk.CTkFrame(head, fg_color="transparent", height=12).pack(side="bottom")

        self.table = ModTable(self, on_change=self._update_footer,
                              empty="Wszystkie mody o tych samych nazwach są identyczne jak u innych :]")
        self.table.pack(fill="both", expand=True)
        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.pack(fill="x", pady=(10, 0))
        self.sel_lbl = ctk.CTkLabel(foot, text="", font=T.font(13), text_color=T.MUTED)
        self.sel_lbl.pack(side="left")
        self.dl_btn = T.button(foot, "↓  Pobierz ich wersję", self._download, kind="primary", width=190, height=40)
        self.dl_btn.pack(side="right")
        self.skip_btn = T.button(foot, "Pomiń", self._skip, width=100, height=40)
        self.skip_btn.pack(side="right", padx=8)
        T.button(foot, "Przywróć pominięte", self._unskip, width=150, height=40).pack(side="right")
        self.refresh(force=True)

    def refresh(self, force=False):
        node = self.app.node
        lib = node.library
        if node.verifying and lib.scanning:
            d, t = lib.progress
            self.status.configure(text=f"Sprawdzam: {d} / {t}" + (f"  ·  {lib.current}" if lib.current else ""),
                                  text_color=T.ACCENT2)
            self.bar.pack(fill="x", padx=18, pady=(6, 0))
            self.bar.set(d / t if t else 0)
            self.check_btn.configure(state="disabled")
        else:
            self.bar.pack_forget()
            self.check_btn.configure(state="disabled" if lib.scanning else "normal")
            changed = len(lib.changed)
            self.status.configure(
                text=(f"Ostatnie pełne sprawdzenie: {node.verified_at}  ·  zmienione pliki u ciebie: {changed}"
                      if node.verified_at else "Pełnego sprawdzenia jeszcze nie było w tej sesji – "
                                               "różnice z innymi graczami widać poniżej od razu"),
                text_color=T.TEXT if node.verified_at else T.MUTED)

        online = [p for p in node.players.online() if p.mods]
        items = conflicts(lib.snapshot(), online, node.cfg.get("ignored_conflicts") or {})
        transfers = {t.ih for t in node.engine.active()}
        self._items = {theirs.ih: (mine, theirs) for mine, theirs, _, _ in items}
        info = {theirs.ih: (n, ignored) for _, theirs, n, ignored in items}

        def row(m):
            n, ignored = info[m.ih]
            if m.ih in transfers:
                chip, color = "pobieram", T.CYAN
            elif ignored:
                chip, color = "POMINIĘTE", T.MUTED
            else:
                chip, color = "RÓŻNE PLIKI", T.YELLOW
            return {"extra": f"inna wersja ma {players_text(n)}", "chip": chip, "chip_color": color,
                    "checkable": not ignored and m.ih not in transfers}
        rows = build_rows([theirs for _, theirs, _, _ in items], row)
        sig = tuple((r.get("id"), r.get("chip"), r.get("extra"), r.get("count")) for r in rows)
        if force or sig != self._sig:
            self._sig = sig
            self.table.set_rows(rows)
            self._update_footer()

    def _update_footer(self):
        ids = self.table.checked_ids()
        size = sum(self._items[i][1].size for i in ids if i in self._items)
        self.sel_lbl.configure(text=f"zaznaczono {plural_mods(len(ids))}  ·  {fmt_size(size)}" if ids
                               else "zaznacz, co pominąć albo pobrać")
        state = "normal" if ids else "disabled"
        self.dl_btn.configure(state=state)
        self.skip_btn.configure(state=state)

    def _download(self):
        mods = [self._items[i][1] for i in self.table.checked_ids() if i in self._items]
        if mods:
            self.app.node.download(mods)
            self.app.toast(f"Pobieram wersję innych graczy: {plural_mods(len(mods))}")
            self.table.checked = set()
            self.refresh(force=True)

    def _skip(self):
        pairs = [(self._items[i][1].key, i) for i in self.table.checked_ids() if i in self._items]
        if pairs:
            self.app.node.ignore_conflicts(pairs)
            self.table.checked = set()
            self.app.toast(f"Pominięto {plural_mods(len(pairs))}")
            self.refresh(force=True)

    def _unskip(self):
        self.app.node.unignore_all()
        self.refresh(force=True)
