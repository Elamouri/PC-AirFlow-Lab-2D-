#!/usr/bin/env bash
# Build the Windows PC_Airflow_Lab.exe on Linux with Wine (Powered by ElAmouri - https://github.com/Elamouri).
#
# Needs: Wine 11 or newer (older Wine cannot import numpy: ucrtbase crealf is missing) and a Windows
# Python inside the Wine prefix with:  pip install -r requirements.txt pyinstaller
#
#   WINEPREFIX=~/.wine-pcflow WINPY='C:\py\python\python.exe' tools/build_exe_wine.sh
set -euo pipefail
cd "$(dirname "$0")/.."
: "${WINPY:=C:\\py\\python\\python.exe}"
export WINEDEBUG="${WINEDEBUG:--all}" WINEDLLOVERRIDES="${WINEDLLOVERRIDES:-mscoree,mshtml=}"
wine "$WINPY" -m PyInstaller --noconfirm --clean pc_airflow_lab.spec
ls -l dist/PC_Airflow_Lab.exe
