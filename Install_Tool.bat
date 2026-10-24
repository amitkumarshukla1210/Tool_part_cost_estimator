@echo off
rem Install Design to Cost on this computer (run once, also after downloading the ZIP of a new machine).
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python is not installed. Install Python 3.11 or 3.12 from https://www.python.org/downloads/ and tick "Add python.exe to PATH", then run this again.
  pause
  exit /b 1
)
if not exist .venv\Scripts\python.exe (
  echo Creating the private Python environment .venv ...
  python -m venv .venv
)
call .venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
if errorlevel 1 (
  echo Installing the libraries failed. Check the internet connection and the message above.
  pause
  exit /b 1
)
if not exist upgrades mkdir upgrades
python -m backend.app.migrate
echo.
echo Installed. Start the tool with Start_Tool.bat  (it opens http://127.0.0.1:8000/)
pause
