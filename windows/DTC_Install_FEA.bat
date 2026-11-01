@echo off
rem Strength check (FEA, stage 45): installs Gmsh into the app's Python and tells you where to put CalculiX (ccx.exe).
cd /d "%~dp0"
title Design to Cost - install FEA programs
where py >nul 2>nul && (py -3 "%~dp0dtc_manager.py" fea %* & pause & exit /b)
python "%~dp0dtc_manager.py" fea %* & pause & exit /b
