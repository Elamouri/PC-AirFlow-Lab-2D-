# Changelog

PC Airflow Lab - Powered by ElAmouri (https://github.com/Elamouri)

## 1.5.0 - 2026-10-12

**Less lag, and blocks: put your own parts anywhere in the case.**

* The simulation is about 2.5 times faster in the live view. A step makes no new arrays any more (work arrays are
  made once, the fields are 32-bit, all fans and heat sinks are handled at once, the pressure factorisation is kept
  while the walls stay the same): 3.9 ms instead of 7.8 ms at normal detail, with the same answers. The live view
  also takes a 1.4 times longer step; the porous resistances keep their tuned loss per second, so the results stay
  within about 1 °C and 2 % airflow (command line, pictures and videos keep the shorter step). In the window the
  simulation runs at about 0.45x real time instead of 0.17x, and the air settles after a change in about 1.5-3 s
  instead of 4-7 s.
* The controls stay smooth while the air moves: they are redrawn after every simulation slice (they used to wait up
  to 3.5 s while the air settled). On Windows the loop no longer waits for a clock tick (~15 ms) between slices.
  Pictures take at most 30 % of the time, the Results text is only made while its tab is open, and a moved fan or
  block redraws in about 70 ms instead of about 105 ms.
* Blocks (new Blocks tab): something that stops the air, a divider panel, a dense part, a cable bundle, a grille, a
  pump with its reservoir, a capture card, a 2.5" SSD or a heat source. Drag them, resize them by their corner,
  right-click for more, set how much air gets through (solid / dense / cables / mesh) and the heat they give off.
  Their heat counts in the power budget and the PSU recommendation. Your own kinds of blocks can be saved in the
  Parts tab and travel inside setups. New example: `configs/example_blocks.json`.
* Blocks and fans never land on each other; **Fix overlaps** (was *Fix overlapping fans*) also moves blocks and
  pulls them inside a smaller case. Ready-made fan layouts keep your blocks.
* Air with no way out (a case without fans, a pocket closed in by blocks) made the pressure solver singular; such
  air is now tied to the room like a small gap, and the app says so.
* Setup files are version 3 (they have a `blocks` list); older files open as before.
* Closing the window cancels the simulation loop's next turn (no more stray Tcl message).

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
