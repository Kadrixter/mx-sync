# MX Sync

Synchronizacja modów MX Bikes w sieci lokalnej oraz przez Radmin VPN.
Jeden program obsługuje oba tryby: **Host** (udostępnia mody) i **Klient** (dociąga brakujące / zmienione).
Wygląd w stylu MX Bikes (czerń + pomarańcz, ikona koła crossowego).

Przy pierwszym uruchomieniu hosta Windows zapyta o zaporę – zezwól na dostęp (sieci prywatne), inaczej klienci nie znajdą hosta.

## Funkcje

**Host**
- folder modów wykrywany automatycznie (`Dokumenty\PiBoSo\MX Bikes\mods`), można zmienić
- lista folderów z rozmiarem i polami do zaznaczenia – udostępniasz tylko to, co chcesz
- opcjonalne hasło (sprawdzane bez wysyłania hasła przez sieć)
- skan MD5 z cache (drugi skan trwa sekundy), postęp, prędkość i czas skanu
- edycja udostępnionych folderów, ponowny skan i pełny skan bez cache w trakcie hostowania
- wstrzymywanie / wznawianie pobierań
- lista połączonych klientów (co robią) oraz postęp i prędkość (MB/s) każdego z nich

**Klient**
- automatyczne wyszukiwanie hostów w sieci lokalnej i w sieci Radmin VPN (oznaczone `[Radmin VPN host]`)
- informacja, że host jest chroniony hasłem; połączenie ręczne po IP (`ip` lub `ip:port`)
- po połączeniu pobiera listę modów hosta i porównuje z lokalnym folderem: każda mapa / motor / mod
  dostaje status **brakuje**, **nieaktualny** albo **aktualny**
- pobierasz tylko zaznaczone mody, a z nich tylko brakujące / zmienione pliki (nie wszystko naraz);
  zakładka „Wszystkie mody hosta” pokazuje pełną listę tego, co host udostępnia
- sprawdzanie: hashuje tylko pliki o zgodnym rozmiarze, z cache – kolejne sprawdzenia trwają sekundy
- pobieranie równoległe (1–8), animowane paski postępu, prędkość, pozostały czas, status każdego pliku
- wznawianie przerwanych pobrań (pliki `.part`), automatyczne ponawianie, weryfikacja MD5, sprawdzanie miejsca na dysku

Zgodność: nowy host obsługuje stary `mx_sync_client_v3.py`, a nowy klient łączy się ze starym `mx_sync_host_v2.py`
(bez wykrywania w sieci – wtedy połącz po IP).

**Aktualizacje**
- przy starcie aplikacja po cichu sprawdza GitHub; przycisk „Sprawdź aktualizacje” na ekranie startowym
- „Pobierz i zainstaluj” pobiera nowy `MXSync.exe`, podmienia plik i uruchamia nową wersję

## Wydawanie nowej wersji

1. Zmień `VERSION` w `utils/version.py` (np. `1.2.0`) i zrób commit.
2. `git tag v1.2.0 && git push origin main v1.2.0`
3. GitHub Actions (`.github/workflows/release.yml`) zbuduje `MXSync.exe` i opublikuje wydanie –
   aplikacje użytkowników zobaczą je po kliknięciu „Sprawdź aktualizacje”.

## Uruchomienie ze źródeł

Wymagany Python 3.10+.

```
pip install -r requirements.txt
python main.py
```

Budowanie pliku `.exe`: uruchom `build.bat` – wynik trafi do `dist\MXSync.exe`.

## Porty

| Port | Protokół | Zastosowanie |
|------|----------|--------------|
| 50515 | UDP | wyszukiwanie hostów |
| 8888 | TCP (HTTP) | indeks modów i pobieranie (kolejny wolny, jeśli zajęty) |

## Struktura

```
main.py          start aplikacji
gui/             ekrany (start, host, klient), widgety, motyw
net/             protokół, wykrywanie hostów, serwer hosta, klient (sprawdzanie + pobieranie)
utils/           rozmiary, hashe + cache, pomiar prędkości, interfejsy sieciowe / Radmin VPN, ustawienia
assets/          ikona (koło MX), logo wheel.png i skrypt, który je generuje
```

Ustawienia i cache hashy: `%USERPROFILE%\.mxsync.json`, `.mxsync_host_cache.json`, `.mxsync_client_cache.json`.

Uwaga: pliki przesyłane są bez szyfrowania – aplikacja jest przeznaczona do zaufanych sieci (LAN, Radmin VPN).
