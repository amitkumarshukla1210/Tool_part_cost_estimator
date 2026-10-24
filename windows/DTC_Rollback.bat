@echo off
rem Back to the version before the last update, with the data of that moment.
cd /d "%~dp0"
title Design to Cost - rollback
where py >nul 2>nul && (py -3 "%~dp0dtc_manager.py" rollback %* & pause & exit /b)
python "%~dp0dtc_manager.py" rollback %* & pause & exit /b
