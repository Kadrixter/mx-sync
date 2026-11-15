"""Automatyczne sprawdzanie aktualizacji i pasek „Dostępna aktualizacja” u góry okna.

UpdateWatcher – sprawdza GitHub przy starcie i potem co INTERVAL_MS (także gdy program
                tylko leży w tle). Nowa wersja → pasek na każdym ekranie + mrugnięcie
                ikoną na pasku zadań, jeśli okno nie jest aktywne.
UpdateBanner  – pomarańczowy pasek; kliknięcie od razu pobiera instalator, instaluje
                i uruchamia program ponownie (UpdateDialog z auto=True).
"""
import sys

import customtkinter as ctk

from gui import theme as T

FIRST_CHECK_MS = 1500
INTERVAL_MS = 10 * 60 * 1000


def flash_taskbar(window, count=5):
    """Mruga przyciskiem programu na pasku zadań (aż użytkownik przełączy się na okno)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes

        class FLASHWINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("hwnd", wintypes.HWND), ("dwFlags", wintypes.DWORD),
                        ("uCount", wintypes.UINT), ("dwTimeout", wintypes.DWORD)]
        hwnd = int(window.wm_frame(), 16)
        # FLASHW_ALL | FLASHW_TIMERNOFG – mruga, dopóki okno nie dostanie fokusu
        info = FLASHWINFO(ctypes.sizeof(FLASHWINFO), hwnd, 0x03 | 0x0C, count, 0)
        ctypes.windll.user32.FlashWindowEx(ctypes.byref(info))
    except Exception:
        pass


class UpdateBanner(ctk.CTkFrame):
    def __init__(self, app):
        super().__init__(app, fg_color=T.ACCENT, corner_radius=0, height=40, cursor="hand2")
        self.app = app
        self.info = None
        self._pulse = 0
        self._job = None
        self.pack_propagate(False)

        self.badge = ctk.CTkLabel(self, text="↑", width=28, height=28, corner_radius=14,
                                  fg_color="#111111", text_color=T.ACCENT2, font=T.font(15, "bold"))
        self.badge.pack(side="left", padx=(12, 10))
        self.text = ctk.CTkLabel(self, text="", text_color="#111111", font=T.font(13, "bold"), anchor="w")
        self.text.pack(side="left", fill="x", expand=True)
        self.close = ctk.CTkButton(self, text="x", width=30, height=28, corner_radius=6, fg_color="transparent",
                                   hover_color=T.ACCENT_HOVER, text_color="#111111", font=T.font(14, "bold"),
                                   command=self.dismiss)
        self.close.pack(side="right", padx=(4, 8))
        self.install = ctk.CTkButton(self, text="Zainstaluj teraz", width=150, height=28, corner_radius=6,
                                     fg_color="#111111", hover_color="#2b2e35", text_color=T.TEXT,
                                     font=T.font(12, "bold"), command=self._install)
        self.install.pack(side="right", padx=4)
        for w in (self, self.badge, self.text):
            w.bind("<Button-1>", lambda e: self._install())

    def show(self, info):
        self.info = info
        self.text.configure(text=f"Dostępna nowa wersja MX Sync {info.tag}  –  kliknij, aby pobrać, "
                                 f"zainstalować i uruchomić ponownie")
        if not self.winfo_ismapped():
            view = self.app.current_view
            if view is not None:
                self.pack(side="top", fill="x", before=view)
            else:
                self.pack(side="top", fill="x")
        if self._job is None:
            self._animate()

    def dismiss(self):
        """Ukrywa pasek do czasu następnej nowszej wersji."""
        self.app.update_watcher.dismissed = self.info.tag if self.info else None
        self.hide()

    def hide(self):
        if self._job:
            self.after_cancel(self._job)
            self._job = None
        self.pack_forget()

    def _install(self):
        if self.info:
            self.app.open_updates(self.info, auto=True)

    def _animate(self):
        # znaczek delikatnie pulsuje (żółty ↔ biały), żeby było widać, że coś czeka
        self._pulse += 1
        t = (self._pulse % 20) / 10
        t = t if t <= 1 else 2 - t
        self.badge.configure(text_color=T.lerp_color(T.ACCENT2, "#ffffff", t))
        self._job = self.after(80, self._animate)


class UpdateWatcher:
    def __init__(self, app):
        self.app = app
        self.dismissed = None       # tag schowany krzyżykiem
        self._notified = None       # tag, o którym już mrugaliśmy
        self.banner = UpdateBanner(app)
        app.after(FIRST_CHECK_MS, self.check_now)

    def check_now(self):
        from gui.update_dialog import check_in_background
        check_in_background(self.app, self._checked)
        self.app.after(INTERVAL_MS, self.check_now)

    def _checked(self, info):
        if not info or not info.newer:
            if self.app.update_info is None:
                self.app.update_info = False
            return
        self.app.update_info = info
        hook = getattr(self.app.current_view, "on_update_info", None)
        if hook:
            hook(info)
        if info.tag != self.dismissed and self.app.update_dialog is None:
            self.banner.show(info)
        if info.tag != self._notified:
            self._notified = info.tag
            if self.app.focus_displayof() is None:
                flash_taskbar(self.app)
