@echo off
rem Upgrade to a newer version from a downloaded ZIP: put the ZIP in the folder "upgrades" (or leave it in Downloads) and double-click this file.
rem Close the tool first. Your projects, CAD files and master data are kept; a backup is made; if anything fails the old version is put back.
cd /d "%~dp0"
if not exist upgrades mkdir upgrades
call .venv\Scripts\activate
python upgrade.py %*
echo.
pause
