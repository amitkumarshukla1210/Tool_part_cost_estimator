@echo off
rem New password for a user of the app (e.g. a forgotten admin password). Only possible at this PC.
cd /d "%~dp0"
title Design to Cost - reset a password
where py >nul 2>nul && (py -3 "%~dp0dtc_manager.py" reset-password %* & pause & exit /b)
python "%~dp0dtc_manager.py" reset-password %* & pause & exit /b
