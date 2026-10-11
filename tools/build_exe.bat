@echo off
rem Build dist\PC_Airflow_Lab.exe  -  PC Airflow Lab, Powered by ElAmouri (https://github.com/Elamouri)
rem Needs Python 3.10 - 3.13 for Windows (python.org). Run this file from anywhere.
cd /d "%~dp0\.."
where py >nul 2>nul
if %errorlevel%==0 (set "PY=py -3") else (set "PY=python")
echo Installing the build tools (first time only)...
%PY% -m pip install -r requirements.txt pyinstaller || goto :fail
echo Building the .exe - this takes a few minutes...
%PY% -m PyInstaller --noconfirm --clean pc_airflow_lab.spec || goto :fail
echo.
echo Done:  %cd%\dist\PC_Airflow_Lab.exe
pause
exit /b 0
:fail
echo.
echo The build stopped - see the messages above.
pause
exit /b 1
