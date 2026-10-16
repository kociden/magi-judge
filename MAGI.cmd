@echo off
rem MAGI launcher: double-click to open the menu.
cd /d "%~dp0"
chcp 65001 >nul
where py >nul 2>nul
if %errorlevel%==0 (py -3 -m magi menu) else (python -m magi menu)
if errorlevel 1 pause
