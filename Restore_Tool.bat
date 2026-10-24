@echo off
rem Put the newest backup back (what is there now is saved first as dtc-before-restore-...zip). Close the tool first.
cd /d "%~dp0"
call .venv\Scripts\activate
echo This replaces your projects, CAD files and master data with the newest backup in the folder "backups".
set /p OK=Type YES to continue: 
if /i not "%OK%"=="YES" exit /b 0
python backup.py --restore latest
pause
