@echo off
rem Start Design to Cost for several users at the same time (logins, roles, data by tool group).
rem The people open http://THIS-COMPUTER-NAME:8000/ in their browser. Close this window to stop it.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Not installed yet. Run Install_Tool.bat first.
  pause
  exit /b 1
)
call .venv\Scripts\activate
set DTC_MODE=server
set /p DTC_ADMIN_PASSWORD=Admin password (used only the first time, to create the admin; at least 10 characters, Enter to skip): 
echo.
echo Admin user ID: admin   Login page: http://127.0.0.1:8000/login
python -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
pause
