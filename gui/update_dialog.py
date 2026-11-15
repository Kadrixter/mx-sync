"""Okno aktualizacji: sprawdza GitHub Releases, pobiera nowy .exe i restartuje aplikację."""
import os
import threading
import time
import tkinter as tk
import webbrowser

import customtkinter as ctk

from gui import theme as T
from gui.widgets import AnimatedProgressBar
from utils import updater
from utils.files import resource_path
from utils.fmt import fmt_size, fmt_speed
from utils.version import VERSION


def check_in_background(widget, on_result):
    """Ciche sprawdzenie (np. przy starcie); on_result(UpdateInfo | None) w wątku GUI."""
    box = {}
    widget = widget.winfo_toplevel()   # widok może zniknąć, okno główne zostaje

    def work():
        try:
            box["info"] = updater.check(timeout=5)
        except updater.UpdateError:
            box["info"] = None

    def wait():
        if "info" not in box:
            widget.after(300, wait)
            return
        try:
            on_result(box["info"])
        except tk.TclError:
            pass  # widok zdążył zniknąć

    threading.Thread(target=work, daemon=True).start()
    widget.after(300, wait)


class UpdateDialog(ctk.CTkToplevel):
    W, H = 460, 360

    def __init__(self, app, info=None):
        super().__init__(app, fg_color=T.BG)
        # CTkToplevel przy starcie pokazuje białe okno, chowa je i pokazuje znowu (kolor paska
        # tytułu), a po 200 ms podmienia ikonę – okno jest przezroczyste, aż to wszystko minie
        self.attributes("-alpha", 0.0)
        self.app = app
        self.title("Aktualizacja MX Sync")
        x = app.winfo_rootx() + (app.winfo_width() - self.W) // 2
        y = app.winfo_rooty() + (app.winfo_height() - self.H) // 3
        self.geometry(f"{self.W}x{self.H}+{max(0, x)}+{max(0, y)}")
        self.resizable(False, False)
        self.transient(app)
        self.info = None
        self._result = {}
        self._progress = (0, 0)
        self._stop = threading.Event()
        self._job = None

        ctk.CTkLabel(self, text="AKTUALIZACJA", font=T.title_font(22), text_color=T.ACCENT).pack(pady=(18, 0))
        ctk.CTkLabel(self, text=f"Twoja wersja: v{VERSION}", font=T.font(12),
                     text_color=T.MUTED).pack()
        self.msg = ctk.CTkLabel(self, text="", font=T.font(14, "bold"), text_color=T.TEXT, wraplength=410)
        self.msg.pack(pady=(14, 6), padx=20)
        # postęp w osobnej etykiecie o stałej szerokości – zmiana liczb nie przestawia układu okna
        self.prog = ctk.CTkLabel(self, text="", font=T.font(12), text_color=T.MUTED, width=380)
        self._prog_text = ""
        self._speed = (0.0, 0)
        self.notes = ctk.CTkTextbox(self, height=110, fg_color=T.PANEL, text_color=T.TEXT,
                                    font=T.font(12), wrap="word", corner_radius=8)
        self.bar = AnimatedProgressBar(self, height=12, bg=T.BG)
        self.btns = ctk.CTkFrame(self, fg_color="transparent")
        self.btns.pack(side="bottom", pady=14)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.bind("<Escape>", lambda e: self._close())
        self.after(260, self._reveal)

        if info is not None:
            self._show(info)
        else:
            self._check()

    def _reveal(self):
        icon = resource_path(os.path.join("assets", "icon.ico"))
        if os.path.exists(icon):
            try:
                self.iconbitmap(icon)
            except tk.TclError:
                pass
        self.attributes("-alpha", 1.0)
        self.lift()
        self.focus_force()

    def _buttons(self, *specs):
        for w in self.btns.winfo_children():
            w.destroy()
        for text, cmd, kind, width in specs:
            T.button(self.btns, text, cmd, kind=kind, width=width, height=38).pack(side="left", padx=6)

    def _run(self, fn, done):
        self._result = {}

        def work():
            try:
                self._result["ok"] = fn()
            except updater.UpdateError as e:
                self._result["err"] = str(e)
            except Exception as e:  # nieprzewidziany błąd nie może zawiesić okna
                self._result["err"] = str(e) or e.__class__.__name__

        threading.Thread(target=work, daemon=True).start()
        self._wait(done)

    def _wait(self, done):
        if not self._result:
            d, t = self._progress
            if t:
                self.bar.set(d / t)
                self._set_prog(d, t)
            self._job = self.after(250, lambda: self._wait(done))
            return
        self._job = None
        done()

    def _set_prog(self, d, t):
        now = time.monotonic()
        last_t, last_d = self._speed
        speed = (d - last_d) / (now - last_t) if last_t and now > last_t else 0
        self._speed = (now, d)
        text = f"{fmt_size(d)} / {fmt_size(t)}   •   {d / t * 100:.0f}%" + (f"   •   {fmt_speed(speed)}" if speed > 0 else "")
        if text != self._prog_text:
            self._prog_text = text
            self.prog.configure(text=text)

    # ----- etapy -----

    def _check(self):
        self.msg.configure(text="Sprawdzam GitHub…", text_color=T.TEXT)
        self.bar.pack(fill="x", padx=40, pady=6)
        self.bar.set_indeterminate()
        self._buttons(("Zamknij", self._close, "secondary", 120))
        self._run(updater.check, self._checked)

    def _checked(self):
        self.bar.pack_forget()
        if "err" in self._result:
            self.msg.configure(text=self._result["err"], text_color=T.RED)
            self._buttons(("Spróbuj ponownie", self._check, "primary", 150),
                          ("Zamknij", self._close, "secondary", 110))
            return
        self._show(self._result["ok"])

    def _show(self, info):
        self.info = info
        if not info.newer:
            self.msg.configure(text=f"✔ Masz najnowszą wersję (v{VERSION})", text_color=T.GREEN)
            self._buttons(("OK", self._close, "primary", 120))
            return
        self.msg.configure(text=f"Dostępna nowa wersja: {info.name}", text_color=T.ACCENT2)
        if info.notes:
            self.notes.pack(fill="x", padx=20)
            self.notes.insert("1.0", info.notes)
            self.notes.configure(state="disabled")
        if updater.is_frozen() and info.asset_url:
            size = f" ({fmt_size(info.asset_size)})" if info.asset_size else ""
            self._buttons((f"⬇ Pobierz i zainstaluj{size}", self._download, "primary", 250),
                          ("Później", self._close, "secondary", 100))
        else:
            # uruchomione ze źródeł – pokaż stronę wydania
            self._buttons(("Otwórz stronę wydania", lambda: webbrowser.open(info.page), "primary", 200),
                          ("Zamknij", self._close, "secondary", 100))

    def _download(self):
        self.notes.pack_forget()
        self.bar.pack(fill="x", padx=40, pady=6)
        self.prog.pack(pady=(2, 0))
        self._speed = (0.0, 0)
        self.bar.set(0)
        self.msg.configure(text="Pobieram aktualizację…", text_color=T.TEXT)
        self._buttons(("Anuluj", self._close, "danger", 120))
        self._stop.clear()

        def progress(d, t):
            self._progress = (d, t)

        self._run(lambda: updater.download(self.info, progress, self._stop), self._downloaded)

    def _downloaded(self):
        if "err" in self._result:
            self.bar.set_color(T.RED)
            self.msg.configure(text=self._result["err"], text_color=T.RED)
            self._buttons(("Spróbuj ponownie", self._download, "primary", 150),
                          ("Zamknij", self._close, "secondary", 110))
            return
        self.bar.set(1.0)
        self.bar.set_color(T.GREEN)
        self.msg.configure(text="Instaluję – aplikacja uruchomi się ponownie…", text_color=T.GREEN)
        self._buttons()
        try:
            updater.install(self._result["ok"])
        except OSError as e:
            self.msg.configure(text=f"Nie udało się uruchomić instalacji: {e}", text_color=T.RED)
            self._buttons(("Zamknij", self._close, "secondary", 110))
            return
        self.after(600, self.app.quit_app)

    def destroy(self):
        if getattr(self.app, "update_dialog", None) is self:
            self.app.update_dialog = None
        super().destroy()

    def _close(self):
        self._stop.set()
        if self._job:
            self.after_cancel(self._job)
            self._job = None
        self.destroy()
