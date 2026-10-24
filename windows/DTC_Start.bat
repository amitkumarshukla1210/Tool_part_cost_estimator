@echo off
rem Starts the app on http://127.0.0.1:8000 (keep the window open; close it to stop the app).
cd /d "%~dp0"
title Design to Cost - start
where py >nul 2>nul && (py -3 "%~dp0dtc_manager.py" start %* & pause & exit /b)
python "%~dp0dtc_manager.py" start %* & pause & exit /b
