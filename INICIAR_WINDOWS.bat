@echo off
setlocal
cd /d "%~dp0"
py -3.12 --version >nul 2>&1
if not errorlevel 1 (
    py -3.12 run_bot.py
    goto fin
)
python --version >nul 2>&1
if not errorlevel 1 (
    python run_bot.py
    goto fin
)
echo Necesitas Python 3.12. Instalador oficial:
echo https://www.python.org/downloads/release/python-31210/
echo Durante la instalacion, marca Add python.exe to PATH.
:fin
echo.
echo Puedes volver a abrir este archivo para iniciar Vector.
pause
