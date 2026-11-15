"""Porównanie modów: z jednym graczem (mode="player") albo ze wszystkimi naraz (mode="all")."""
import customtkinter as ctk

from core.mods import KIND_GROUPS, KIND_PLURAL, mod_dir
from gui import theme as T
from gui.mod_table import ModTable
from gui.widgets import Ring
from utils.fmt import fmt_size, plural_mods

TABS_PLAYER = [("missing", "Brakuje ci"), ("different", "Inna wersja"), ("same", "Wspólne"),
               ("only_mine", "Tylko u ciebie")]
TABS_ALL = [("missing", "Brakuje ci"), ("different", "Inna wersja")]
KINDS = [("", "Wszystko")] + KIND_GROUPS


class ModsView(ctk.CTkFrame):
    def __init__(self, master, app, mode, pid=None):
        super().__init__(master, fg_color="transparent")
        self.app, self.mode, self.pid = app, mode, pid
        self.tab = "missing"
        self.kind = ""
        self._sig = None
        self._mods = {}             # id wiersza -> Mod

        head = ctk.CTkFrame(self, fg_color=T.CARD, corner_radius=14)
        head.pack(fill="x", pady=(0, 12))
        self.ring = Ring(head, size=78, width=7, bg=T.CARD, font_size=20)
        self.ring.pack(side="left", padx=18, pady=14)
        box = ctk.CTkFrame(head, fg_color="transparent")
        box.pack(side="left", fill="x", expand=True, pady=10)
        self.title = ctk.CTkLabel(box, text="", font=T.title_font(26), text_color=T.TEXT, anchor="w")
        self.title.pack(fill="x")
        self.sub = ctk.CTkLabel(box, text="", font=T.font(12), text_color=T.MUTED, anchor="w")
        self.sub.pack(fill="x")
        self.stats = ctk.CTkLabel(box, text="", font=T.font(13, "bold"), text_color=T.TEXT, anchor="w")
        self.stats.pack(fill="x", pady=(4, 0))

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", pady=(0, 8))
        tabs = TABS_PLAYER if mode == "player" else TABS_ALL
        self._tab_labels = dict(tabs)
        self.tabs = ctk.CTkSegmentedButton(bar, values=[t for _, t in tabs], command=self._tab_clicked,
                                           font=T.font(13, "bold"), height=34, fg_color=T.CARD,
                                           selected_color=T.ACCENT, selected_hover_color=T.ACCENT_HOVER,
                                           unselected_color=T.CARD, unselected_hover_color=T.ROW_HOVER,
                                           text_color=T.TEXT)
        self.tabs.pack(side="left")
        self.search = ctk.CTkEntry(bar, placeholder_text="szukaj moda…", width=220, height=34, fg_color=T.CARD,
                                   border_color=T.BORDER, font=T.font(13))
        self.search.pack(side="right")
        self.search.bind("<KeyRelease>", lambda e: self.refresh(force=True))
        self.search.bind("<Escape>", lambda e: (self.search.delete(0, "end"), self.refresh(force=True)))

        self.kinds = ctk.CTkSegmentedButton(self, values=[k for _, k in KINDS], command=self._kind_clicked,
                                            font=T.font(12), height=28, fg_color=T.BG,
                                            selected_color=T.ROW_HOVER, selected_hover_color=T.ROW_HOVER,
                                            unselected_color=T.BG, unselected_hover_color=T.CARD,
                                            text_color=T.TEXT)
        self.kinds.set("Wszystko")
        self.kinds.pack(anchor="w", pady=(0, 8))

        self.table = ModTable(self, on_change=self._update_footer)
        self.table.pack(fill="both", expand=True)

        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.pack(fill="x", pady=(10, 0))
        self.sel_lbl = ctk.CTkLabel(foot, text="", font=T.font(13), text_color=T.MUTED)
        self.sel_lbl.pack(side="left")
        self.dl_btn = T.button(foot, "↓  Pobierz zaznaczone", self._download, kind="primary", width=220, height=40)
        self.all_btn = T.button(foot, "Zaznacz wszystko", lambda: self.table.set_all(True), width=150, height=40)
        self._show_actions(True)
        self.tabs.set(self._tab_labels["missing"])
        self.refresh(force=True)

    # ---------- dane ----------

    def _source(self):
        """(lista modów dla zakładki, dodatkowa kolumna, nagłówek)"""
        node, cache = self.app.node, self.app.cache
        holders = cache.holders_count()
        if self.mode == "all":
            missing = cache.missing_all()
            items = [(m, n) for m, n, diff in missing if diff == (self.tab == "different")]
            return [m for m, _ in items], {m.ih: f"ma {_players(n)}" for m, n in items}, None
        p = node.players.get(self.pid)
        cmp = cache.get(p) if p else None
        if cmp is None:
            return [], {}, (p, None)
        mods = getattr(cmp, self.tab)
        extra = {m.ih: f"ma {_players(holders.get(m.ih, 0))}" for m in mods} if self.tab != "only_mine" else {}
        return mods, extra, (p, cmp)

    def refresh(self, force=False):
        node = self.app.node
        mods, extra, pc = self._source()
        self._header(pc)
        transfers = {t.ih: t for t in node.engine.active()}
        q = self.search.get().strip().lower().split()
        rows, groups = [], {}
        for m in mods:
            if self.kind and m.kind != self.kind:
                continue
            if q and not all(w in m.key.lower() for w in q):
                continue
            groups.setdefault(m.kind, []).append(m)
        self._mods = {}
        checkable = self.tab in ("missing", "different")
        for kind, _ in KIND_GROUPS:
            if kind not in groups:
                continue
            g = groups[kind]
            rows.append({"header": True, "kind": kind, "selectable": checkable,
                         "label": f"{KIND_PLURAL[kind]}  ·  {len(g)}  ·  {fmt_size(sum(m.size for m in g))}"})
            for m in g:
                t = transfers.get(m.ih)
                chip, color = _chip(self.tab, t)
                rows.append({"id": m.ih, "kind": m.kind, "name": m.name, "path": mod_dir(m.key) or "mods",
                             "size": m.size, "extra": extra.get(m.ih, ""), "chip": chip, "chip_color": color,
                             "checkable": checkable and t is None})
                self._mods[m.ih] = m
        sig = (tuple((r.get("id"), r.get("chip"), r.get("extra"), r.get("label")) for r in rows), self.tab)
        if force or sig != self._sig:
            self._sig = sig
            self.table.checkable = checkable
            self.table.empty = _empty_text(self.mode, self.tab, bool(q or self.kind))
            self.table.set_rows(rows)
            self._update_footer()

    def _header(self, pc):
        node, cache = self.app.node, self.app.cache
        if self.mode == "all":
            missing = cache.missing_all()
            online = [p for p in node.players.online() if p.mods]
            self.title.configure(text="Brakujące mody")
            self.sub.configure(text=f"Wszystko, co mają gracze online ({len(online)}), a ty nie. "
                                    "Pobierasz naraz od wszystkich, którzy mają dany mod.")
            n_diff = sum(1 for _, _, d in missing if d)
            self.ring.set(None, str(len(missing)) if missing else ":]", T.ACCENT)
            self.stats.configure(text=f"brakuje {len(missing) - n_diff}   ·   inna wersja {n_diff}   ·   "
                                      f"razem {fmt_size(sum(m.size for m, _, _ in missing))}")
            self._set_tab_counts({"missing": len(missing) - n_diff, "different": n_diff})
            return
        p, cmp = pc if pc else (None, None)
        if p is None:
            self.title.configure(text="Gracz rozłączony")
            return
        self.title.configure(text=p.name)
        self.sub.configure(text=f"{p.state}  ·  {p.via}  ·  {plural_mods(p.mod_count)}  ·  {fmt_size(p.size)}"
                                + (f"  ·  v{p.version}" if p.version else ""))
        if cmp is None:
            self.ring.set(None, "…")
            self.stats.configure(text="wczytuję jego mody…" if p.online else "")
            return
        self.ring.set(cmp.percent)
        self.stats.configure(text=f"zgodność {cmp.percent}%   ·   wspólne {len(cmp.same)}   ·   "
                                  f"brakuje ci {len(cmp.missing)} ({fmt_size(cmp.missing_size)})   ·   "
                                  f"inna wersja {len(cmp.different)}   ·   tylko u ciebie {len(cmp.only_mine)}")
        self._set_tab_counts({k: len(getattr(cmp, k)) for k, _ in TABS_PLAYER})

    def _set_tab_counts(self, counts):
        names = [f"{label} ({counts.get(k, 0)})" for k, label in self._tab_labels.items()]
        current = list(self._tab_labels).index(self.tab)
        if list(self.tabs._buttons_dict) != names:
            self.tabs.configure(values=names)
            self.tabs.set(names[current])

    # ---------- akcje ----------

    def _tab_clicked(self, value):
        label = value.rsplit(" (", 1)[0]
        self.tab = next(k for k, v in self._tab_labels.items() if v == label)
        self._show_actions(self.tab in ("missing", "different"))
        self.table.checked = set()
        self.refresh(force=True)

    def _kind_clicked(self, value):
        self.kind = next(k for k, v in KINDS if v == value)
        self.refresh(force=True)

    def _show_actions(self, on):
        if on:
            self.dl_btn.pack(side="right")
            self.all_btn.pack(side="right", padx=8)
        else:
            self.dl_btn.pack_forget()
            self.all_btn.pack_forget()

    def _update_footer(self):
        ids = self.table.checked_ids()
        size = sum(self._mods[i].size for i in ids if i in self._mods)
        if self.tab in ("missing", "different"):
            self.sel_lbl.configure(text=f"zaznaczono {plural_mods(len(ids))}  ·  {fmt_size(size)}" if ids
                                   else "kliknij mody (albo nagłówek grupy), żeby je zaznaczyć")
            self.dl_btn.configure(state="normal" if ids else "disabled")
        else:
            self.sel_lbl.configure(text="")

    def _download(self):
        mods = [self._mods[i] for i in self.table.checked_ids() if i in self._mods]
        if mods:
            self.app.node.download(mods)
            self.table.checked = set()
            self.app.toast(f"Pobieram {plural_mods(len(mods))} – postęp w zakładce Transfery")
            self.refresh(force=True)


def _players(n):
    return "1 gracz" if n == 1 else (f"{n} graczy" if n != 0 else "nikt online")


def _chip(tab, transfer):
    if transfer is not None:
        if transfer.error:
            return "błąd", T.RED
        return f"pobieram {round(transfer.progress * 100)}%", T.CYAN
    return {"missing": ("BRAKUJE", T.ORANGE), "different": ("INNA WERSJA", T.YELLOW),
            "same": ("MASZ", T.GREEN), "only_mine": ("TYLKO TY", T.MUTED)}[tab]


def _empty_text(mode, tab, filtered):
    if filtered:
        return "Nic nie pasuje do filtra :/"
    if mode == "all":
        return "Masz wszystko, co mają gracze online :D" if tab == "missing" else "Żadnych różnic w wersjach :]"
    return {"missing": "Masz wszystkie jego mody :D", "different": "Wszystkie wspólne mody w tej samej wersji :]",
            "same": "Nie macie wspólnych modów", "only_mine": "On ma wszystko, co ty"}[tab]
