@echo off
rem Buduje dist\MXSync\ (PyInstaller, folder) i instalator dist\installer\MXSync-Setup.exe
rem Wymaga Inno Setup 6 (https://jrsoftware.org/isdl.php).
cd /d "%~dp0"
python -m pip install -r requirements.txt || goto :fail
rem libtorrent ma gotowe paczki tylko dla Pythona 3.12 – uruchom z py -3.12, jeśli masz kilka wersji
python -m PyInstaller --noconfirm --clean --onedir --windowed --name MXSync --collect-data customtkinter --hidden-import pystray._win32 ^
    --icon assets\icon.ico --add-data "assets\icon.ico;assets" --add-data "assets\wheel.png;assets" --add-data "assets\logo.gif;assets" main.py || goto :fail
for /f "tokens=2 delims==" %%v in ('findstr /b "VERSION" utils\version.py') do set VER=%%~v
set VER=%VER: =%
set VER=%VER:"=%
set ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe
if not exist "%ISCC%" set ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe
"%ISCC%" /DAppVersion=%VER% installer\MXSync.iss || goto :fail
echo.
echo Gotowe: dist\installer\MXSync-Setup.exe (wersja %VER%)
pause
exit /b 0
:fail
echo BLAD budowania
pause
exit /b 1
