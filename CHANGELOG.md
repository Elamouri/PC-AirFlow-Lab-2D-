# Changelog

PC Airflow Lab - Powered by ElAmouri (https://github.com/Elamouri)

## 1.4.0 - 2026-10-11

**The live view is much quicker.**

* Quick live frames: the case, the parts, the fan housings and the fixed labels are drawn once into see-through
  layers, and each frame only paints the moving air, the blades and the numbers. A frame takes about 15 ms instead
  of 85-100 ms and looks the same.
* The simulation runs in slices of about 16 ms with the window answering in between. Clicks, drags and typing wait
  about 15 ms instead of about 200 ms, also while the air settles after a change.
* Changes of fan speed, load, room temperature or auto mode keep the drawing and reuse the pressure solver's
  factorisation. A change takes about 16 ms instead of about 250 ms, and sliders react after 0.12 s instead of
  0.35-0.4 s.
* Building the view for a new layout is twice as fast. The flow dashes and fan blades are drawn with fewer
  objects, which also speeds up picture and video exports.
* Number boxes show whole numbers (`130`, not `130.0`).
* GitHub page with screenshots, a demo animation and the .exe to download.

## 1.3.0 - 2026-10-11

* Ready-made Windows program `PC_Airflow_Lab.exe` (one file, no Python needed). Setups live in
  `Documents\PC Airflow Lab`.
* **Powered by ElAmouri** with GitHub and WhatsApp links in the window, the About box, every exported picture and
  video, the file details, the text report and the command line.
* The window fits 125 % / 150 % Windows display scaling. On small screens the read-outs move into two rows.
* Review fixes: an unexpected command-line error no longer opens a blocking dialog in the .exe, and pictures are
  always PNG and videos always MP4 whatever the file name ends with.

## 1.2.0

* No more stacked fans: new, duplicated, dragged and moved fans always go to a free spot.
* Parts library: add your own fans, graphics cards, processors, CPU coolers, motherboards and cases. Setups carry
  the parts they use.
* Motherboard sizes, RAM (DDR4 / DDR5, ECC), M.2 SSDs and hard drives, dust filters, altitude, and a fan curve for
  auto case fans.

## 1.1.0

* Every fan speed in rpm or %, fans anywhere (including inside the case), full CPU cooler fan control, GPU types
  with their power use and maximum, and temperatures from the simulated cooler airflow.

## 1.0.0

* First version: configurable airflow and heat simulation, the desktop app, the command line, and video and
  picture export.
