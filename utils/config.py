"""Ustawienia zapamiętywane między uruchomieniami (~/.mxsync.json) i folder danych (~/.mxsync)."""
import json
import os
import socket
from pathlib import Path

# MXSYNC_HOME – inny katalog domowy (np. dwie instancje na jednym komputerze do testów)
_HOME = Path(os.environ.get("MXSYNC_HOME") or Path.home())
CONFIG_FILE = _HOME / ".mxsync.json"
DATA_DIR = _HOME / ".mxsync"                  # cache torrentów, identyfikator gracza, instancja

DEFAULTS = {
    "name": "",                 # nazwa gracza (pusta = nazwa komputera)
    "folder": "",               # folder mods MX Bikes (pusty = wykryty automatycznie)
    "password": "",             # hasło grupy – widzą się tylko gracze z tym samym hasłem
    "close_to_tray": True,      # krzyżyk chowa do zasobnika zamiast zamykać
    "autostart": False,         # start z Windows (od razu w zasobniku)
    "max_up": 0,                # KB/s, 0 = bez limitu
    "max_down": 0,
    "manual_peers": [],         # gracze dodani ręcznie po IP (poza LAN / Radminem)
}


def load():
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        data = data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        data = {}
    return {**DEFAULTS, **data}


def update(**values):
    cfg = load()
    cfg.update(values)
    try:
        tmp = CONFIG_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, CONFIG_FILE)
    except OSError:
        pass
    return cfg


def player_name(cfg=None):
    cfg = cfg or load()
    return (cfg.get("name") or "").strip()[:32] or socket.gethostname()
