"""Transfery: co pobieram (postęp, prędkość, od ilu graczy) i komu wysyłam."""
import customtkinter as ctk

from core.mods import paint_bike
from gui import theme as T
from gui.widgets import AnimatedProgressBar
from utils.fmt import fmt_eta, fmt_size, fmt_speed


class TransferRow(ctk.CTkFrame):
    def __init__(self, master, t, on_cancel):
        super().__init__(master, fg_color=T.ROW, corner_radius=10)
        self.ih = t.ih
        glyph, color = T.KIND_STYLE.get(t.kind, ("*", T.MUTED))
        ctk.CTkLabel(self, text=glyph, width=30, height=30, corner_radius=8, fg_color=T.BG, text_color=color,
                     font=("Consolas", 15, "bold")).pack(side="left", padx=12, pady=12)
        box = ctk.CTkFrame(self, fg_color="transparent")
        box.pack(side="left", fill="x", expand=True, pady=8)
        top = ctk.CTkFrame(box, fg_color="transparent")
        top.pack(fill="x")
        ctk.CTkLabel(top, text=T.shorten(t.name, 60), font=T.font(14, "bold"), text_color=T.TEXT).pack(side="left")
        bike = paint_bike(t.key) if t.kind == "Malowanie" else None
        if bike:
            ctk.CTkLabel(top, text=f"do motoru: {bike}", font=T.font(11), text_color=T.FAINT).pack(
                side="left", padx=(8, 0))
        self.info = ctk.CTkLabel(top, text="", font=T.font(12), text_color=T.MUTED)
        self.info.pack(side="right")
        self.bar = AnimatedProgressBar(box, height=10, bg=T.ROW)
        self.bar.pack(fill="x", pady=(6, 2))
        T.button(self, "Anuluj", lambda: on_cancel(t.ih), kind="secondary", width=80, height=30).pack(
            side="right", padx=12)

    def update_from(self, t):
        self.bar.set(t.progress)
        if t.error:
            self.bar.set_color(T.RED)
            self.info.configure(text=f"błąd: {T.shorten(t.error, 60)}", text_color=T.RED)
            return
        who = f"od {t.peers} {'gracza' if t.peers == 1 else 'graczy'}" if t.peers else t.state
        eta = fmt_eta(t.eta) if t.down else "—"
        self.info.configure(text=f"{round(t.progress * 100)}%  ·  {fmt_size(t.size * t.progress)} / "
                                 f"{fmt_size(t.size)}  ·  {fmt_speed(t.down)}  ·  {who}  ·  {eta}",
                            text_color=T.TEXT if t.down else T.MUTED)


class TransfersView(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.rows = {}
        head = ctk.CTkFrame(self, fg_color=T.CARD, corner_radius=14)
        head.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(head, text="Transfery", font=T.title_font(26), text_color=T.TEXT, anchor="w").pack(
            fill="x", padx=18, pady=(14, 0))
        self.speed = ctk.CTkLabel(head, text="", font=T.font(13, "bold"), text_color=T.TEXT, anchor="w")
        self.speed.pack(fill="x", padx=18, pady=(2, 14))

        ctk.CTkLabel(self, text="POBIERANIE", font=T.title_font(13), text_color=T.FAINT, anchor="w").pack(fill="x")
        self.list = ctk.CTkScrollableFrame(self, fg_color=T.CARD, corner_radius=12, height=260)
        self.list.pack(fill="both", expand=True, pady=(4, 12))
        self.empty = ctk.CTkLabel(self.list, text="Nic się nie pobiera. Wybierz gracza albo „Brakujące mody”.",
                                  font=T.font(13), text_color=T.MUTED)
        ctk.CTkLabel(self, text="WYSYŁASZ DO", font=T.title_font(13), text_color=T.FAINT, anchor="w").pack(fill="x")
        self.up = ctk.CTkLabel(self, text="", font=T.font(13), text_color=T.TEXT, anchor="w", justify="left",
                               fg_color=T.CARD, corner_radius=12, height=60)
        self.up.pack(fill="x", pady=(4, 12), ipadx=14, ipady=8)
        ctk.CTkLabel(self, text="OSTATNIO POBRANE", font=T.title_font(13), text_color=T.FAINT, anchor="w").pack(fill="x")
        self.recent = ctk.CTkLabel(self, text="", font=T.font(13), text_color=T.MUTED, anchor="w", justify="left",
                                   fg_color=T.CARD, corner_radius=12, height=60)
        self.recent.pack(fill="x", pady=(4, 0), ipadx=14, ipady=8)
        self.refresh()

    def refresh(self, force=False):
        node = self.app.node
        eng = node.engine
        active = [t for t in eng.active() if not t.done]
        left = sum(t.size * (1 - t.progress) for t in active)
        self.speed.configure(text=f"↓ {fmt_speed(eng.down_rate)}     ↑ {fmt_speed(eng.up_rate)}     ·     "
                                  f"pobierasz {len(active)}  ·  zostało {fmt_size(left)}")
        for ih in [ih for ih in self.rows if ih not in {t.ih for t in active}]:
            self.rows.pop(ih).destroy()
        for t in active:
            row = self.rows.get(t.ih)
            if row is None:
                row = self.rows[t.ih] = TransferRow(self.list, t, node.cancel)
                row.pack(fill="x", padx=6, pady=4)
            row.update_from(t)
        if active:
            self.empty.pack_forget()
        else:
            self.empty.pack(pady=30)

        names = {p.ip: p.name for p in node.players.all() if p.ip}
        ups = sorted(eng.uploading.items(), key=lambda x: -x[1])
        self.up.configure(text="   ·   ".join(f"{names.get(ip, ip)}  {fmt_speed(sp)}" for ip, sp in ups)
                          if ups else "Teraz nikt od ciebie nie pobiera.",
                          text_color=T.TEXT if ups else T.MUTED)
        recent = list(node.recent)[-4:][::-1]
        self.recent.configure(text="\n".join(f"{when}   {name}" for when, name in recent) if recent
                              else "Jeszcze nic w tej sesji.")
