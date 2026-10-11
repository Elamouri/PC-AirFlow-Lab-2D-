@echo off
rem PC Airflow Lab - Windows launcher
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (set "PY=py -3") else (set "PY=python")
%PY% -c "import numpy, scipy, matplotlib, imageio_ffmpeg, PIL, tkinter" >nul 2>nul
if errorlevel 1 (
  echo Installing the libraries the simulator needs - first start only...
  %PY% -m pip install -r requirements.txt
)
%PY% run_gui.py configs\my_pc.json
if errorlevel 1 pause
