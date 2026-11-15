"""Ikona w zasobniku (obok zegara): pokaż okno, zakończ, powiadomienia.

pystray działa we własnym wątku – polecenia z menu trafiają do kolejki, którą okno czyta co chwilę
(Tkinter nie lubi wywołań z innych wątków).
"""
import os
import queue

from utils.files import resource_path

try:
    import pystray
    from PIL import Image
except ImportError:         # bez pystray program działa, tylko bez zasobnika
    pystray = None


class Tray:
    def __init__(self):
        self.commands = queue.Queue()
        self.icon = None
        if pystray is None:
            return
        try:
            img = Image.open(resource_path(os.path.join("assets", "icon.ico")))
        except OSError:
            return
        menu = pystray.Menu(
            pystray.MenuItem("Otwórz MX Sync", lambda: self.commands.put("show"), default=True),
            pystray.MenuItem("Transfery", lambda: self.commands.put("transfers")),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Zakończ", lambda: self.commands.put("quit")),
        )
        self.icon = pystray.Icon("MXSync", img, "MX Sync", menu)

    @property
    def available(self):
        return self.icon is not None

    def start(self):
        if self.icon:
            self.icon.run_detached()

    def stop(self):
        if self.icon:
            try:
                self.icon.stop()
            except Exception:       # noqa: BLE001 – przy zamykaniu nie ma co ratować
                pass

    def tooltip(self, text):
        if self.icon:
            self.icon.title = text[:120]

    def notify(self, title, text):
        if self.icon:
            try:
                self.icon.notify(text, title)
            except Exception:       # noqa: BLE001 – powiadomienie to dodatek
                pass
