@echo off
rem Country rate book: one Excel per country (RM, labour, process, electricity, transport, forex), 24 months, with sources.
rem Run once a month. Hand-downloaded ILOSTAT files: DTC_Country_Rates.bat --ilo-file C:\path\file.csv
cd /d "%~dp0"
title Design to Cost - country rate book
where py >nul 2>nul && (py -3 "%~dp0dtc_manager.py" country-rates %* & pause & exit /b)
python "%~dp0dtc_manager.py" country-rates %* & pause & exit /b
