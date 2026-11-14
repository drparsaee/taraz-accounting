@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
echo TARAZ PREVIEW - SYNTHETIC DATA ONLY
echo Installed Taraz and real accounting data will not be changed.
echo.
py -3.12 -B "%~dp0scripts\run_taraz_preview_20261114.py" --launch
set "EXIT_CODE=%ERRORLEVEL%"
echo.
echo Taraz preview exited with code %EXIT_CODE%.
if not "%EXIT_CODE%"=="0" pause
exit /b %EXIT_CODE%
