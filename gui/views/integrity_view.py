"""Integralność: czy mody o tej samej nazwie to na pewno te same pliki co u innych graczy.

Wybór zakresu (wszystko, mapy, motory, postacie – kaski, buty… itd.) i gracza, z którym porównać.
„Sprawdź integralność” liczy sumy moich modów z zakresu od nowa (bez pamięci), a lista pokazuje
mody, które mam pod tą samą nazwą co wybrani gracze, ale z inną zawartością. Dla każdego: pomiń
albo pobierz wersję innych (od wszystkich, którzy ją mają).
"""
import customtkinter as ctk

from core.compare import conflicts
from core.mods import CHARACTER_KINDS, CHARACTERS, KIND_PLURAL, kind_in
from gui import theme as T
from gui.mod_table import ModTable
from gui.rows import build_rows, players_text
from gui.widgets import AnimatedProgressBar, Dropdown, FlowRow, autowrap
from utils.fmt import fmt_size, plural_mods

SCOPES = ([("", "Wszystko"), ("Mapa", "Mapy"), ("Motor", "Motory"), ("Malowanie", "Malowania"),
           ("Opony", "Opony"), (CHARACTERS, "Postacie – wszystko")]
          + [(k, f"Postacie – {KIND_PLURAL[k].lower()}") for k in CHARACTER_KINDS]
          + [("Inne", "Inne")])
SCOPE_LABEL = dict(SCOPES)


class IntegrityView(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self._sig = None
        self._items = {}            # id wiersza (ih wersji innych) -> (mój Mod, ich Mod)
        self.scope = ""
        self.who = None             # id gracza albo None = wszyscy online
        self._who_labels = {}       # etykieta w menu -> id gracza

        head = ctk.CTkFrame(self, fg_color=T.CARD, corner_radius=14)
        head.pack(fill="x", pady=(0, 12))
        top = FlowRow(head)
        top.pack(fill="x", padx=18, pady=(14, 2))
        ctk.CTkLabel(top.left, text="Integralność plików", font=T.title_font(26), text_color=T.TEXT).pack(side="left")
        self.check_btn = T.button(top.right, "Sprawdź integralność", self._verify, kind="primary", width=190,
                                  height=36)
        self.check_btn.pack(side="right")
        desc = ctk.CTkLabel(head, text="Sprawdza, czy mody o tej samej nazwie co u innych graczy to naprawdę te same "
                                       "pliki. Wybierz, co sprawdzić i z kim porównać – sprawdzenie liczy sumy "
                                       "twoich modów z tego zakresu od nowa.",
                            font=T.font(12), text_color=T.MUTED, anchor="w", justify="left")
        desc.pack(fill="x", padx=18)
        autowrap(desc, head, 40)

        ctl = FlowRow(head)
        ctl.pack(fill="x", padx=18, pady=(10, 0))
        ctk.CTkLabel(ctl.left, text="Co sprawdzić:", font=T.font(12), text_color=T.MUTED).pack(side="left")
        self.scope_menu = Dropdown(ctl.left, [v for _, v in SCOPES], self._scope_changed, width=210)
        self.scope_menu.set(SCOPES[0][1])
        self.scope_menu.pack(side="left", padx=(6, 0))
        ctk.CTkLabel(ctl.right, text="Porównaj z:", font=T.font(12), text_color=T.MUTED).pack(side="left")
        self.who_menu = Dropdown(ctl.right, ["Wszyscy online"], self._who_changed, width=210)
        self.who_menu.set("Wszyscy online")
        self.who_menu.pack(side="left", padx=(6, 0))

        self.status = ctk.CTkLabel(head, text="", font=T.font(13, "bold"), text_color=T.TEXT, anchor="w",
                                   justify="left")
        self.status.pack(fill="x", padx=18, pady=(8, 0))
        autowrap(self.status, head, 40)
        self.bar = AnimatedProgressBar(head, height=10, bg=T.CARD)
        ctk.CTkFrame(head, fg_color="transparent", height=12).pack(side="bottom")

        self.table = ModTable(self, on_change=self._update_footer, empty="")
        self.table.pack(fill="both", expand=True)
        foot = FlowRow(self)
        foot.pack(side="bottom", fill="x", pady=(10, 0), before=self.table)
        self.sel_lbl = ctk.CTkLabel(foot.left, text="", font=T.font(13), text_color=T.MUTED)
        self.sel_lbl.pack(side="left")
        self.dl_btn = T.button(foot.right, "↓  Pobierz ich wersję", self._download, kind="primary", width=190,
                               height=40)
        self.dl_btn.pack(side="right")
        self.skip_btn = T.button(foot.right, "Pomiń", self._skip, width=100, height=40)
        self.skip_btn.pack(side="right", padx=8)
        T.button(foot.right, "Przywróć pominięte", self._unskip, width=150, height=40).pack(side="right")
        self.refresh(force=True)

    # ---------- wybór zakresu i gracza ----------

    def _scope_changed(self, label):
        self.scope = next(k for k, v in SCOPES if v == label)
        self.table.checked = set()
        self.refresh(force=True)

    def _who_changed(self, label):
        self.who = self._who_labels.get(label)
        self.table.checked = set()
        self.refresh(force=True)

    def _sync_players(self, online):
        """Lista graczy w menu „Porównaj z” – odświeżana, gdy ktoś wejdzie / wyjdzie."""
        names = {}
        for p in online:
            names[p.name] = names.get(p.name, 0) + 1
        labels = {}
        for p in sorted(online, key=lambda p: p.name.lower()):
            label = T.shorten(p.name, 24)
            if names[p.name] > 1:
                label += f" ({p.ip})"
            labels[label] = p.id
        values = [f"Wszyscy online ({len(online)})"] + list(labels)
        if values != list(self.who_menu.cget("values")):
            self._who_labels = labels
            self.who_menu.configure(values=values)
        current = next((lbl for lbl, pid in labels.items() if pid == self.who), None)
        if self.who is None:
            self.who_menu.set(values[0])
        elif current:
            self.who_menu.set(current)
        else:
            p = self.app.node.players.get(self.who)
            self.who_menu.set(f"{T.shorten(p.name, 20)} (offline)" if p else "gracz rozłączony")

    def _verify(self):
        self.app.node.verify(self.scope)
        self.app.toast(f"Sprawdzam integralność: {SCOPE_LABEL[self.scope].lower()}")

    # ---------- odświeżanie ----------

    def refresh(self, force=False):
        node = self.app.node
        lib = node.library
        online = [p for p in node.players.online() if p.mods]
        self._sync_players(online)
        chosen = online if self.who is None else [p for p in online if p.id == self.who]
        who_text = "wszystkimi graczami online" if self.who is None else (
            chosen[0].name if chosen else "wybranym graczem (offline)")

        if node.verifying and lib.scanning:
            d, t = lib.progress
            self.status.configure(text=f"Sprawdzam ({SCOPE_LABEL.get(node.verified_scope, '').lower()}): {d} / {t}"
                                       + (f"  ·  {lib.current}" if lib.current else ""), text_color=T.ACCENT2)
            self.bar.pack(fill="x", padx=18, pady=(6, 0))
            self.bar.set(d / t if t else 0)
            T.enable(self.check_btn, False)
        else:
            self.bar.pack_forget()
            T.enable(self.check_btn, not lib.scanning)
            if node.verified_at:
                text = (f"Ostatnie sprawdzenie: {node.verified_at} ({SCOPE_LABEL.get(node.verified_scope, '')})"
                        f"  ·  zmienione pliki u ciebie: {len(lib.changed)}")
            else:
                text = "Pełnego sprawdzenia jeszcze nie było w tej sesji – różnice z innymi graczami widać poniżej od razu"
            self.status.configure(text=text, text_color=T.TEXT if node.verified_at else T.MUTED)

        items = conflicts(lib.snapshot(), chosen, node.cfg.get("ignored_conflicts") or {})
        items = [it for it in items if kind_in(it[0].kind, self.scope)]
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
        sig = (tuple((r.get("id"), r.get("chip"), r.get("extra"), r.get("count")) for r in rows),
               self.scope, self.who, bool(chosen))
        if force or sig != self._sig:
            self._sig = sig
            if not chosen:
                self.table.empty = ("Nikt nie jest online – nie ma z kim porównać" if self.who is None
                                    else "Ten gracz jest teraz offline – wybierz innego w „Porównaj z”")
            else:
                self.table.empty = (f"{SCOPE_LABEL[self.scope]}: wszystko identyczne jak u gracza "
                                    f"{who_text} :]" if self.who else
                                    f"{SCOPE_LABEL[self.scope]}: wszystko identyczne jak u innych graczy :]")
            self.dl_btn.configure(text="↓  Pobierz jego wersję" if self.who else "↓  Pobierz ich wersję")
            self.table.set_rows(rows)
            self._update_footer()

    def _update_footer(self):
        ids = self.table.checked_ids()
        size = sum(self._items[i][1].size for i in ids if i in self._items)
        self.sel_lbl.configure(text=f"zaznaczono {plural_mods(len(ids))}  ·  {fmt_size(size)}" if ids
                               else "zaznacz, co pominąć albo pobrać")
        T.enable(self.dl_btn, bool(ids))
        T.enable(self.skip_btn, bool(ids))

    # ---------- akcje ----------

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
