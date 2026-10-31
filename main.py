"""MX Sync – synchronizacja modów MX Bikes w sieci lokalnej / Radmin VPN (host i klient)."""
import sys

from gui.app import App

if __name__ == "__main__":
    if sys.platform == "win32":
        import ctypes
        # własny identyfikator – pasek zadań nie grupuje okna z Pythonem i bierze jego ikonę
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("MXSync.App")
    App().mainloop()
