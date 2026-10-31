"""Ustawienia zapamiętywane między uruchomieniami (~/.mxsync.json)."""
import json
import os
from pathlib import Path

CONFIG_FILE = Path.home() / ".mxsync.json"
HOST_CACHE = Path.home() / ".mxsync_host_cache.json"
CLIENT_CACHE = Path.home() / ".mxsync_client_cache.json"


def load():
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def update(**values):
    cfg = load()
    cfg.update(values)
    try:
        tmp = CONFIG_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, CONFIG_FILE)
    except OSError:
        pass
