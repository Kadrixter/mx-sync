"""MX Sync – wymiana modów MX Bikes między graczami (LAN / Radmin VPN), jak torrent."""
import json
import sys
import urllib.request


def _show_running_instance():
    """Jeśli MX Sync już działa (np. w zasobniku) – pokaż jego okno i zakończ ten proces."""
    from utils.config import DATA_DIR
    try:
        port = json.loads((DATA_DIR / "instance.json").read_text())["port"]
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/show", timeout=1.5) as r:
            return json.loads(r.read()).get("ok") is True
    except (OSError, ValueError, KeyError):
        return False


if __name__ == "__main__":
    if sys.platform == "win32":
        import ctypes
        # własny identyfikator – pasek zadań nie grupuje okna z Pythonem i bierze jego ikonę
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("MXSync.App")
    if _show_running_instance():
        sys.exit(0)
    from gui.app import App
    App(start_hidden="--tray" in sys.argv).mainloop()
