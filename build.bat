@echo off
rem Buduje dist\MXSync.exe (jeden plik, bez konsoli)
cd /d "%~dp0"
python -m pip install -r requirements.txt
python -m PyInstaller --noconfirm --clean --onefile --windowed --name MXSync --collect-data customtkinter ^
    --icon assets\icon.ico --add-data "assets\icon.ico;assets" --add-data "assets\wheel.png;assets" main.py
echo.
echo Gotowe: dist\MXSync.exe
pause
