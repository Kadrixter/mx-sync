"""MD5 plików i cache hashy (rozmiar + mtime) – kolejne sprawdzenia trwają sekundy."""
import hashlib
import json
import os
import threading
import time

HASH_CHUNK = 1024 * 1024


class Cancelled(Exception):
    pass


def md5_file(path, cb=None, stop=None):
    h = hashlib.md5()
    buf = bytearray(HASH_CHUNK)
    mv = memoryview(buf)
    with open(path, "rb", buffering=0) as f:
        while True:
            n = f.readinto(buf)
            if not n:
                break
            h.update(mv[:n])
            if cb:
                cb(n)
            if stop is not None and stop.is_set():
                raise Cancelled()
    return h.hexdigest()


class HashCache:
    """Słownik ścieżka -> [rozmiar, mtime_ns, md5], zapisywany atomowo."""

    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        self._save_lock = threading.Lock()
        self.data = {}
        self._last_save = time.monotonic()
        try:
            self.data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass

    def get(self, p, st):
        c = self.data.get(p)
        if c and c[0] == st.st_size and c[1] == st.st_mtime_ns:
            return c[2]
        return None

    def put(self, p, st, h):
        with self.lock:
            self.data[p] = [st.st_size, st.st_mtime_ns, h]

    def prune(self, folder, valid):
        """Usuwa wpisy plików z tego folderu, których już nie ma w indeksie."""
        base = os.path.abspath(folder) + os.sep
        with self.lock:
            for k in [k for k in self.data if k.startswith(base) and k not in valid]:
                del self.data[k]

    def clear(self):
        with self.lock:
            self.data = {}
        try:
            self.path.unlink()
        except OSError:
            pass

    def save(self):
        with self._save_lock:
            self._last_save = time.monotonic()
            try:
                with self.lock:
                    text = json.dumps(self.data)
                tmp = self.path.with_suffix(".tmp")
                tmp.write_text(text, encoding="utf-8")
                os.replace(tmp, self.path)
            except OSError:
                pass

    def checkpoint(self, every=15):
        """Zapis co kilkanaście sekund – przerwane sprawdzanie nie traci pracy."""
        if time.monotonic() - self._last_save > every:
            self.save()
