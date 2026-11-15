# MX Sync

Wymiana modów MX Bikes między graczami w sieci lokalnej i przez Radmin VPN – jak torrent.
Nie ma już hosta ani klienta: każdy gracz udostępnia cały swój folder modów i pobiera od innych.
Mod, który ma kilka osób, pobiera się naraz od wszystkich, a pobierający od razu wysyłają
pobrane kawałki dalej – im więcej graczy, tym szybciej.

## Instalacja

Pobierz `MXSync-Setup-X.Y.Z.exe` z [wydań](https://github.com/Kadrixter/mx-sync/releases/latest) i zainstaluj
(Windows 10/11, 64-bit). Instalator dodaje MX Sync do menu Start (i opcjonalnie na pulpit), od razu ustawia
zaporę Windows (też dla Radmin VPN), a odinstalować można z „Aplikacji” w Ustawieniach.
Windows może pokazać „Nieznany wydawca” – kliknij „Więcej informacji → Uruchom mimo to”.

## Jak to działa

- **Gracze pojawiają się sami** – MX Sync szuka innych w sieci lokalnej i w Radmin VPN. Gracze przekazują sobie
  też listy znajomych, więc wystarczy, że widzisz jednego, żeby zobaczyć resztę. Spoza sieci: „Dodaj gracza po IP”.
- **Zgodność modów** – przy każdym graczu kółko z procentem: ile modów macie identycznych (w tej samej wersji)
  względem wszystkich modów was obu. W szczegółach gracza zakładki: *Brakuje ci*, *Inna wersja*, *Wspólne*,
  *Tylko u ciebie*.
- **Malowania** – osobny rodzaj obok motorów; pod nazwą małym drukiem motor, do którego jest malowanie
  (folder nad `paints`, np. `bikes/sm1oemktm450f/paints/` -> `sm1oemktm450f`).
- **Mody i grupy** – każdy plik `.pkz` to osobny mod. Folder z paczkami (np. `tracks/motocross/Paczka2024/`) to grupa:
  grupy są na górze listy, a zaznaczenie grupy zaznacza wszystkie jej mapy / mody. Folder z rozpakowanym modem
  (pliki `.ini`, `.hrc`, …) to jeden mod.
- **Brakujące mody** – zbiorczo wszystko, co mają gracze online, a ty nie (z liczbą graczy, którzy mają dany mod).
- **Filtr „min. graczy z modem”** (domyślnie 2) – pokazuje tylko mody, które ma co najmniej tylu graczy.
- **Wyszukiwarka** – po nazwie, grupie i folderze; kilka słów naraz, znaki `_ - .` są pomijane
  (np. `spa` albo `1998` znajdzie `0xspa1998.pkz`).
- **Integralność** – pełne sprawdzenie liczy sumy wszystkich twoich modów od nowa; lista pokazuje mody o tej samej
  nazwie co u innych, ale z inną zawartością – każdy można pominąć albo pobrać wersję innych.
- **Pobieranie** – zaznaczasz mody (albo całą grupę) i „Pobierz zaznaczone”. Każdy mod pobiera się od wszystkich,
  którzy go mają, i od innych pobierających w tym samym czasie. Inna wersja modu jest podmieniana: pobierane są
  tylko zmienione pliki, a pliki starej wersji, których nie ma w nowej, są usuwane.
- **Moja biblioteka** – twoje mody, ilu graczy ma każdy z nich; folder modów wykrywany automatycznie
  (`Dokumenty\PiBoSo\MX Bikes\mods`), można zmienić w Ustawieniach.
- **Transfery** – postęp, prędkość i od ilu graczy pobierasz; komu i jak szybko wysyłasz; ostatnio pobrane.
- **Zasobnik** – krzyżyk chowa MX Sync obok zegara (dalej udostępnia mody). Opcjonalnie start razem z Windows.
  Ponowne uruchomienie programu pokazuje już działające okno.
- **Ustawienia** – nazwa gracza, folder modów, hasło grupy (widzicie się tylko z tym samym hasłem; hasło nie idzie
  przez sieć), limity wysyłania / pobierania, zasobnik, autostart.
- **Aktualizacje** – sprawdzanie GitHuba przy starcie i co 10 minut; pomarańczowy pasek u góry okna, kliknięcie
  pobiera instalator, instaluje i uruchamia program ponownie.

Pierwsze uruchomienie przygotowuje mody do udostępniania (liczy sumy kontrolne – przy dużej bibliotece kilka minut)
etapami: rider, tyres, misc, bikes, na końcu tracks. Po każdym etapie postęp jest zapisywany, a gotowe mody są już
udostępniane. Kolejne starty biorą wynik z pamięci i liczą tylko nowe / zmienione mody – program o tym informuje.

Zgodność: 2.1 to protokół 4 (mod = pojedynczy plik) – nie łączy się z 2.0 ani 1.x; starsze wersje same proponują aktualizację.

## Pod spodem

- każdy mod to osobny prywatny torrent (BitTorrent v2, biblioteka libtorrent); ten sam mod u dwóch graczy ma ten sam
  identyfikator – po nim porównywane są biblioteki i łączeni są wszyscy, którzy go mają
- torrenty są prywatne: bez DHT i publicznych trackerów, połączenia tylko między graczami MX Sync
- UPnP / NAT-PMP otwierają port na routerze (przydatne przy dodawaniu graczy po IP przez internet)

| Port | Protokół | Zastosowanie |
|------|----------|--------------|
| 50515 | UDP | wyszukiwanie graczy |
| 8888 | TCP (HTTP) | informacje o graczu i jego modach (kolejny wolny, jeśli zajęty) |
| 50520 | TCP + UDP | transfery (BitTorrent / uTP; kolejny wolny, jeśli zajęty) |

## Wydawanie nowej wersji

1. Zmień `VERSION` w `utils/version.py` i zrób commit.
2. `git tag vX.Y.Z && git push origin main vX.Y.Z`
3. GitHub Actions (`.github/workflows/release.yml`) zbuduje aplikację (Python 3.12, PyInstaller `--onedir`),
   instalator (Inno Setup, `installer/MXSync.iss`) i opublikuje wydanie z plikiem `MXSync-Setup-X.Y.Z.exe`.

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
core/            mods.py (co jest modem), library.py (skan + torrenty + cache), engine.py (libtorrent),
                 api.py (HTTP gracza), discovery.py (UDP), players.py (inni gracze), compare.py, node.py (całość)
gui/             app.py (okno), topbar, sidebar, views/ (porównanie, biblioteka, transfery), mod_table.py
                 (szybka lista na Canvasie), tray.py, settings_dialog.py, update_banner.py / update_dialog.py
utils/           ustawienia, autostart, aktualizacje, interfejsy sieciowe / Radmin VPN, formatowanie
assets/          ikona i logo + make_icon.py, który je generuje
installer/       skrypt Inno Setup
```

Dane: `%USERPROFILE%\.mxsync.json` (ustawienia), `%USERPROFILE%\.mxsync\` (identyfikator gracza, cache torrentów).
