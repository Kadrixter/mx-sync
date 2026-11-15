"""Uruchamianie MX Sync razem z Windows (klucz Run w rejestrze użytkownika, od razu w zasobniku)."""
import sys

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
NAME = "MX Sync"


def set_autostart(on):
    """Działa tylko w zainstalowanej wersji (.exe) – ze źródeł nic nie robi."""
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if on:
                winreg.SetValueEx(k, NAME, 0, winreg.REG_SZ, f'"{sys.executable}" --tray')
            else:
                try:
                    winreg.DeleteValue(k, NAME)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        return False
