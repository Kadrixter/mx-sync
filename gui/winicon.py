"""Ostra ikona okna na pasku zadań (rozmiar zależny od DPI)."""
import sys


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
