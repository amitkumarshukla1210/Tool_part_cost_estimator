@echo off
rem Puts a backup from DTC_Backups back (what is there now is backed up first).
cd /d "%~dp0"
title Design to Cost - restore
where py >nul 2>nul && (py -3 "%~dp0dtc_manager.py" restore %* & pause & exit /b)
python "%~dp0dtc_manager.py" restore %* & pause & exit /b
