@echo off
cd /d "%~dp0"
echo Backing up and pulling the latest version from GitHub...
if exist .venv\Scripts\activate.bat call .venv\Scripts\activate.bat
python update.py
if errorlevel 1 (
  echo.
  echo Update stopped. Read the message above. Nothing was lost.
  pause
  exit /b 1
)
pip install -r requirements.txt
echo.
echo Update done. Starting the server...
start http://127.0.0.1:8000
uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
pause
