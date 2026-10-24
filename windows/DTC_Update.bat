@echo off
rem Backup, new version from GitHub or a ZIP, master data merged, libraries installed. Your data stays in DTC_Data.
cd /d "%~dp0"
title Design to Cost - update
where py >nul 2>nul && (py -3 "%~dp0dtc_manager.py" update %* & pause & exit /b)
python "%~dp0dtc_manager.py" update %* & pause & exit /b
