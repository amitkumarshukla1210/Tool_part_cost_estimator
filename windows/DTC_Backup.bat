@echo off
rem Backup of DTC_Data (projects, CAD files, master data) into DTC_Backups.
cd /d "%~dp0"
title Design to Cost - backup
where py >nul 2>nul && (py -3 "%~dp0dtc_manager.py" backup %* & pause & exit /b)
python "%~dp0dtc_manager.py" backup %* & pause & exit /b
