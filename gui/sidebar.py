"""Lewy panel: przegląd (brakujące od wszystkich, biblioteka, transfery) i lista graczy."""
import customtkinter as ctk

from gui import theme as T
from gui.widgets import Ring
from utils.fmt import fmt_size, fmt_speed, plural_mods

STATE_TEXT = {"łączę": ("łączę…", T.MUTED), "offline": ("offline", T.FAINT),
              "hasło": ("inne hasło grupy", T.YELLOW), "stara wersja": ("stara wersja MX Sync", T.RED)}


class NavItem(ctk.CTkFrame):
    """Pozycja menu: znaczek, tytuł, podtytuł i licznik po prawej."""

    def __init__(self, master, glyph, title, on_click):
        super().__init__(master, fg_color="transparent", corner_radius=10, cursor="hand2", height=52)
        self.pack_propagate(False)
        self.selected = False
        self.icon = ctk.CTkLabel(self, text=glyph, width=30, height=30, corner_radius=8, fg_color=T.CARD,
                                 text_color=T.ACCENT, font=("Consolas", 15, "bold"))
        self.icon.pack(side="left", padx=(10, 10))
        box = ctk.CTkFrame(self, fg_color="transparent")
        box.pack(side="left", fill="x", expand=True)
        self.title = ctk.CTkLabel(box, text=title, font=T.font(13, "bold"), text_color=T.TEXT, anchor="w", height=18)
        self.title.pack(fill="x")
        self.sub = ctk.CTkLabel(box, text="", font=T.font(11), text_color=T.MUTED, anchor="w", height=15)
        self.sub.pack(fill="x")
        self.count = ctk.CTkLabel(self, text="", font=T.font(12, "bold"), text_color="#111111", fg_color=T.ACCENT,
                                  corner_radius=9, height=20)
        _bind_click(self, on_click)
        _bind_hover(self)

    def set(self, sub=None, count=None, color=T.ACCENT):
        if sub is not None:
            self.sub.configure(text=sub)
        if count:
            self.count.configure(text=f" {count} ", fg_color=color)
            self.count.pack(side="right", padx=10)
        else:
            self.count.pack_forget()

    def select(self, on):
        if on == self.selected:
            return
        self.selected = on
        self.configure(fg_color=T.CARD_SEL if on else "transparent")


class PlayerCard(ctk.CTkFrame):
    def __init__(self, master, player, on_click):
        super().__init__(master, fg_color="transparent", corner_radius=10, cursor="hand2", height=58)
        self.pack_propagate(False)
        self.pid = player.id
        self.selected = False
        self.ring = Ring(self, size=42, width=4, bg=T.SIDEBAR)
        self.ring.pack(side="left", padx=(8, 10))
        box = ctk.CTkFrame(self, fg_color="transparent")
        box.pack(side="left", fill="x", expand=True)
        self.name = ctk.CTkLabel(box, text="", font=T.font(13, "bold"), text_color=T.TEXT, anchor="w", height=18)
        self.name.pack(fill="x")
        self.sub = ctk.CTkLabel(box, text="", font=T.font(11), text_color=T.MUTED, anchor="w", height=15)
        self.sub.pack(fill="x")
        _bind_click(self, lambda: on_click(self.pid))
        _bind_hover(self)

    def update_from(self, p, cmp):
        self.name.configure(text=T.shorten(p.name, 22), text_color=T.TEXT if p.online else T.MUTED)
        if p.online and cmp is not None:
            self.ring.set(cmp.percent)
            miss = len(cmp.missing) + len(cmp.different)
            self.sub.configure(text=f"{p.via}  ·  brakuje ci {miss}" if miss else f"{p.via}  ·  masz wszystko",
                               text_color=T.ORANGE if miss else T.GREEN)
        elif p.online:
            self.ring.set(None, "…")
            self.sub.configure(text=f"{p.via}  ·  wczytuję mody", text_color=T.MUTED)
        else:
            text, color = STATE_TEXT.get(p.state, (p.state, T.MUTED))
            self.ring.set(None, "-")
            self.sub.configure(text=text, text_color=color)

    def select(self, on):
        if on == self.selected:
            return
        self.selected = on
        self.configure(fg_color=T.CARD_SEL if on else "transparent")
        self.ring.configure(bg=T.CARD_SEL if on else T.SIDEBAR)


class Sidebar(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color=T.SIDEBAR, corner_radius=0, width=290)
        self.pack_propagate(False)
        self.app = app
        self.cards = {}
        self._sig = None

        _section(self, "PRZEGLĄD")
        self.nav = {
            "all": NavItem(self, "!", "Brakujące mody", lambda: app.open_view("all")),
            "library": NavItem(self, "#", "Moja biblioteka", lambda: app.open_view("library")),
            "transfers": NavItem(self, "=", "Transfery", lambda: app.open_view("transfers")),
            "integrity": NavItem(self, "?", "Integralność", lambda: app.open_view("integrity")),
        }
        for n in self.nav.values():
            n.pack(fill="x", padx=10, pady=1)
        self.players_hdr = _section(self, "GRACZE")
        # przycisk pakowany przed listą graczy (od dołu) – przy niskim oknie kurczy się lista, nie przycisk
        T.button(self, "+  Dodaj gracza po IP", app.add_player_dialog, height=36).pack(
            side="bottom", fill="x", padx=14, pady=12)
        self.list = ctk.CTkScrollableFrame(self, fg_color="transparent", scrollbar_button_color=T.CARD,
                                           scrollbar_button_hover_color=T.ROW_HOVER)
        self.list.pack(fill="both", expand=True, padx=4)
        self.empty = ctk.CTkLabel(self.list, text="Szukam graczy w sieci (LAN, Radmin VPN)…\n"
                                                  "Inni muszą mieć włączony MX Sync.",
                                  font=T.font(12), text_color=T.MUTED, justify="left")


    def _conflicts(self):
        """Liczba nierozwiązanych konfliktów – liczona tylko gdy coś się zmieniło."""
        node = self.app.node
        key = (node.library.rev, tuple((p.id, p.rev) for p in node.players.online()),
               len(node.cfg.get("ignored_conflicts") or {}))
        if getattr(self, "_conf_key", None) != key:
            self._conf_key, self._conf_n = key, _conflicts_count(node)
        return self._conf_n

    def refresh(self, selected):
        node, cache = self.app.node, self.app.cache
        players = sorted(node.players.all(), key=lambda p: (not p.online, p.name.lower()))
        sig = tuple(p.id for p in players)
        if sig != self._sig:
            self._sig = sig
            for c in self.cards.values():
                c.destroy()
            self.cards = {p.id: PlayerCard(self.list, p, lambda pid: self.app.open_view("player", pid))
                          for p in players}
            for p in players:
                self.cards[p.id].pack(fill="x", padx=6, pady=1)
        if players:
            self.empty.pack_forget()
        else:
            self.empty.pack(fill="x", padx=12, pady=10)
        online = sum(p.online for p in players)
        self.players_hdr.configure(text=f"GRACZE  ·  {online} ONLINE" if players else "GRACZE")
        for p in players:
            card = self.cards[p.id]
            card.update_from(p, cache.get(p) if p.online else None)
            card.select(selected == ("player", p.id))

        missing = cache.missing_all()
        size = sum(m.size for m, _, _ in missing)
        self.nav["all"].set(f"{plural_mods(len(missing))}  ·  {fmt_size(size)}" if missing
                            else "masz wszystko, co mają inni", len(missing))
        lib = node.library
        lib_sub = (f"skanuję {lib.progress[0]}/{lib.progress[1]}" if lib.scanning
                   else f"{plural_mods(len(lib.mods))}  ·  {fmt_size(sum(m.size for m in lib.mods.values()))}")
        self.nav["library"].set(lib_sub)
        active = [t for t in node.engine.active() if not t.done]
        eng = node.engine
        self.nav["transfers"].set(f"↓ {fmt_speed(eng.down_rate)}   ↑ {fmt_speed(eng.up_rate)}", len(active), T.CYAN)
        n_conf = self._conflicts()
        self.nav["integrity"].set("sprawdzam…" if node.verifying else
                                  (f"różne pliki: {n_conf}" if n_conf else "wszystko się zgadza"),
                                  n_conf, T.YELLOW)
        for k, n in self.nav.items():
            n.select(selected == (k, None))


def _conflicts_count(node):
    from core.compare import conflicts
    online = [p for p in node.players.online() if p.mods]
    return sum(1 for *_, ignored in conflicts(node.library.snapshot(), online,
                                              node.cfg.get("ignored_conflicts") or {}) if not ignored)


def _section(master, text):
    lbl = ctk.CTkLabel(master, text=text, font=T.title_font(12), text_color=T.FAINT, anchor="w")
    lbl.pack(fill="x", padx=22, pady=(16, 4))
    return lbl


def _bind_click(widget, cmd):
    widget.bind("<Button-1>", lambda e: cmd())
    for child in widget.winfo_children():
        _bind_click(child, cmd)


def _bind_hover(widget):
    ring = getattr(widget, "ring", None)

    def enter(e):
        if not widget.selected:
            widget.configure(fg_color=T.CARD)
            if ring:
                ring.configure(bg=T.CARD)

    def leave(e):
        if not widget.selected:
            widget.configure(fg_color="transparent")
            if ring:
                ring.configure(bg=T.SIDEBAR)
    for w in [widget] + _descendants(widget):
        w.bind("<Enter>", enter, add="+")
        w.bind("<Leave>", leave, add="+")


def _descendants(w):
    out = []
    for c in w.winfo_children():
        out.append(c)
        out += _descendants(c)
    return out
