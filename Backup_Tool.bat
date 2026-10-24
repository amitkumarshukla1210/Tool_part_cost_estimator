@echo off
rem Back up your projects, CAD files and master data into the folder "backups". Keep a copy of the ZIP outside this computer too.
cd /d "%~dp0"
call .venv\Scripts\activate
python backup.py
pause
