#!/bin/sh
# PC Airflow Lab - macOS / Linux launcher
cd "$(dirname "$0")"
python3 -c "import numpy, scipy, matplotlib, imageio_ffmpeg, PIL, tkinter" 2>/dev/null || python3 -m pip install -r requirements.txt
python3 run_gui.py configs/my_pc.json
