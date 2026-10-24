@echo off
rem Start Design to Cost on http://127.0.0.1:8000/  (close this window to stop it)
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Not installed yet. Run Install_Tool.bat first.
  pause
  exit /b 1
)
call .venv\Scripts\activate
start "" http://127.0.0.1:8000/
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
pause
