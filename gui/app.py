import os
import sys

import customtkinter as ctk

from gui import theme as T
from gui.start_view import StartView
from utils.files import resource_path
from utils.version import VERSION


def set_crisp_icon(window, ico_path):
    """Tk ustawia ikonę w jednym rozmiarze i pasek zadań ją rozciąga (rozmycie).
    Tu ładujemy z .ico rozmiary pasujące do DPI ekranu i ustawiamy je przez WM_SETICON."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        user32 = ctypes.windll.user32
        user32.LoadImageW.restype = ctypes.c_void_p
        user32.SendMessageW.argtypes = (ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p)
        hwnd = int(window.wm_frame(), 16)
        try:
            dpi = user32.GetDpiForWindow(ctypes.c_void_p(hwnd)) or 96
            big = user32.GetSystemMetricsForDpi(11, dpi)    # SM_CXICON
            small = user32.GetSystemMetricsForDpi(49, dpi)  # SM_CXSMICON
        except AttributeError:
            big, small = user32.GetSystemMetrics(11), user32.GetSystemMetrics(49)
        for kind, size in ((1, big), (0, small)):  # ICON_BIG, ICON_SMALL
            h = user32.LoadImageW(None, ico_path, 1, size, size, 0x10)  # IMAGE_ICON, LR_LOADFROMFILE
            if h:
                user32.SendMessageW(hwnd, 0x0080, kind, h)  # WM_SETICON
    except Exception:
        pass


class App(ctk.CTk):
    def __init__(self):
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        super().__init__(fg_color=T.BG)
        self.title(f"MX Sync  v{VERSION}")
        self.geometry("960x680")
        self.minsize(800, 560)
        icon = resource_path(os.path.join("assets", "icon.ico"))
        if os.path.exists(icon):
            self.iconbitmap(icon)
            self.after(300, lambda: set_crisp_icon(self, icon))
        self._view = None
        self.update_info = None      # wynik cichego sprawdzenia aktualizacji przy starcie
        self.update_dialog = None    # otwarte okno aktualizacji (najwyżej jedno)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.show(StartView)

    def show(self, cls, **kw):
        if self._view:
            self._view.cleanup()
            self._view.destroy()
        self._view = cls(self, **kw)
        self._view.pack(fill="both", expand=True)

    def open_updates(self, info=None):
        from gui.update_dialog import UpdateDialog
        if self.update_dialog is not None and self.update_dialog.winfo_exists():
            self.update_dialog.lift()
            self.update_dialog.focus_force()
            return
        self.update_dialog = UpdateDialog(self, info)

    def quit_app(self):
        self._on_close()

    def _on_close(self):
        if self._view:
            self._view.cleanup()
            self._view = None
        self.destroy()
