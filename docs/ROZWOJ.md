# MX Sync – dla programistów

Opis działania programu: [README](../README.md).

## Pod spodem

- każdy mod to osobny prywatny torrent (BitTorrent v2, biblioteka libtorrent); ten sam mod u dwóch graczy ma ten sam
  identyfikator – po nim porównywane są biblioteki i łączeni są wszyscy, którzy go mają
- torrenty są prywatne: bez DHT i publicznych trackerów, połączenia tylko między graczami MX Sync
- połączenia bezpośrednie: UPnP / NAT-PMP, publiczne IP w `/hello` (tylko z hasłem grupy), test portu `/reach`, hole punching `/punch`, filtr IP – `core/direct.py`

| Port | Protokół | Zastosowanie |
|------|----------|--------------|
| 50515 | UDP | wyszukiwanie graczy |
| 8888 | TCP (HTTP) | informacje o graczu i jego modach (kolejny wolny, jeśli zajęty) |
| 50520 | TCP + UDP | transfery (BitTorrent / uTP; kolejny wolny, jeśli zajęty) |

## Wydawanie nowej wersji

1. Zmień `VERSION` w `utils/version.py` i zrób commit.
2. `git tag vX.Y.Z && git push origin main vX.Y.Z`
3. GitHub Actions (`.github/workflows/release.yml`) zbuduje aplikację (Python 3.12, PyInstaller `--onedir`),
   instalator (Inno Setup, `installer/MXSync.iss`) i opublikuje wydanie z plikiem `MXSync-Setup.exe` (stała nazwa – bezpośredni link w README zawsze wskazuje najnowszą wersję).

## Uruchomienie ze źródeł

Wymagany Python **3.12** (libtorrent ma gotowe paczki dla Windows tylko dla tej wersji).

```
py -3.12 -m pip install -r requirements.txt
py -3.12 main.py
```

Dwie instancje na jednym komputerze (testy): ustaw zmienną `MXSYNC_HOME` na inny folder dla każdej.
Budowanie instalatora: `build.bat` (wymaga Inno Setup 6) → `dist\installer\MXSync-Setup-X.Y.Z.exe`.

## Struktura

```
main.py          start (jedna instancja, --tray = start w zasobniku)
core/            direct.py (połączenia bezpośrednie), mods.py (co jest modem), library.py (skan + torrenty + cache), engine.py (libtorrent),
                 api.py (HTTP gracza), discovery.py (UDP), players.py (inni gracze), compare.py, node.py (całość)
gui/             app.py (okno), topbar, sidebar, views/ (porównanie, biblioteka, transfery), mod_table.py
                 (szybka lista na Canvasie), tray.py, settings_dialog.py, update_banner.py / update_dialog.py
utils/           ustawienia, autostart, aktualizacje, interfejsy sieciowe / Radmin VPN, formatowanie
assets/          ikona i logo + make_icon.py, który je generuje
installer/       skrypt Inno Setup
```

Dane: `%USERPROFILE%\.mxsync.json` (ustawienia), `%USERPROFILE%\.mxsync\` (identyfikator gracza, cache torrentów).
