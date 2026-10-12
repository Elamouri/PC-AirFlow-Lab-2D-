<p align="center">
  <img src="assets/app.png" width="96" alt="PC Airflow Lab icon">
</p>

<h1 align="center">PC Airflow Lab</h1>

<p align="center">
  <b>See how air and heat move through your PC case, and what every fan, part and setting changes.</b><br>
  A 2D airflow and heat simulation · a Windows app · Python source
</p>

<p align="center">
  <a href="https://github.com/Elamouri/PC-AirFlow-Lab-2D-/releases/latest/download/PC_Airflow_Lab.exe"><img src="docs/images/download-button.svg" width="320" alt="Download PC_Airflow_Lab.exe for Windows"></a><br>
  <sub>Windows 10 / 11 (64-bit) · version 1.5.0 · <a href="https://github.com/Elamouri/PC-AirFlow-Lab-2D-/releases/latest">release notes</a></sub>
</p>

<p align="center">
  <b>Powered by ElAmouri</b> · <a href="https://github.com/Elamouri">GitHub</a> · <a href="https://wa.me/962796742759">WhatsApp +962 79 674 2759</a>
</p>

<p align="center">
  <img src="docs/images/demo.gif" width="480" alt="Live airflow: 3 front intakes, 3 top and 1 rear exhaust, tower cooler, graphics card and PSU">
</p>

You choose where every fan goes, which way it blows and how fast it spins: in rpm, in %, or **auto** on a fan curve. That covers case fans, fans anywhere inside the case, the CPU cooler fans, the GPU fans and the PSU fan. You also pick the CPU, cooler, graphics card, motherboard size, RAM (DDR4 / DDR5, ECC), SSDs and hard drives, power supply, dust-filter condition and altitude. You can put **blocks** anywhere in the case: something that stops the air, a divider panel, cables, a grille, or a part that makes heat, such as a pump or a capture card. Then you watch the air move.

The app shows:

* the temperature of the air that actually reaches the **CPU cooler** and the **GPU**, and rough **CPU and GPU temperatures**
* how much **power** every part uses now and at most, and which **PSU size** is recommended
* the **airflow (CFM)** and outgoing air temperature of every fan, including the PSU fan
* the **pressure inside the case** (negative or positive) and **which fans carry the heat out**

Parts that are not in the lists can be **added in the app**: fans, graphics cards, processors, CPU coolers, motherboards, cases and kinds of blocks. New, duplicated and dragged fans and blocks always go to a free spot, never on top of another fan or part. Results can be exported as a 1080 × 1920 **video** or **picture**, sized for a phone screen.

---

## Download

**Windows 10 / 11 (64-bit):** download **[PC_Airflow_Lab.exe](https://github.com/Elamouri/PC-AirFlow-Lab-2D-/releases/latest/download/PC_Airflow_Lab.exe)** from the [latest release](https://github.com/Elamouri/PC-AirFlow-Lab-2D-/releases/latest). It is one file and needs no install and no Python.

1. Put `PC_Airflow_Lab.exe` anywhere, for example on the Desktop, and double-click it. The window takes a few seconds to open, because the program first unpacks itself.
2. The first time, Windows may say **"Windows protected your PC"**, because the program is new and not signed with a paid certificate. Click **More info → Run anyway**.

Where the program keeps things:

| What | Where |
|---|---|
| your setups | `Documents\PC Airflow Lab` (the example setups are copied there on the first start) |
| your own parts | `%APPDATA%\PC Airflow Lab\my_parts.json` (the Python version uses the same file) |
| pictures and videos | where you choose when you export |

You can also drag a setup file (`.json`) onto `PC_Airflow_Lab.exe` to open it. macOS and Linux: [run it from the source](#run-from-the-source).

## What's new in 1.5

* **Less lag: the air moves about twice as fast in the live view.** A simulation step takes 3.9 ms instead of 7.8 ms with the same physics, and the live view takes a slightly longer step. In the window the simulation now runs at about 0.35× real time instead of 0.18× (normal detail), and after a change the air settles in about 1.7 s instead of 4.2 s (3.4 s instead of 7.7 s after *Restart airflow*).
* **The controls stay smooth while the air moves.** Buttons, sliders and numbers used to wait up to 4 s for a redraw while the air settled; now they wait about 20 ms, and at most about 60 ms. On Windows the simulation no longer pauses for a clock tick (about 15 ms) between its slices. Moving a fan or a block redraws in about 70 ms instead of about 105 ms.
* **Blocks: put your own parts anywhere in the case.** A block that stops the air, a divider panel, a cable bundle, a grille, a pump with its reservoir, a capture card, a 2.5" SSD, or any part that makes heat. Drag them, resize them by their corner, set how much air gets through and how many watts they give off. Their heat counts in the power budget, and your own kinds of blocks can be saved in the Parts tab.
* **Air with no way out is handled.** In a case without fans the pressure had no fixed level (the solver relied on rounding). Now such air, and any pocket of air closed in by blocks, is tied to the room like a small gap, and the app tells you.

Earlier versions are listed in [CHANGELOG.md](CHANGELOG.md).

## Screenshots

<p align="center"><img src="docs/images/app-window.png" alt="The main window: live airflow on the left, settings on the right, read-outs underneath"></p>

<table>
  <tr>
    <td width="50%"><img src="docs/images/fans-tab.png" alt="Fans tab"><br><b>Fans:</b> every fan's wall, position, direction, model and speed (rpm, % or auto), plus the fan curve.</td>
    <td width="50%"><img src="docs/images/blocks-tab.png" alt="Blocks tab"><br><b>Blocks:</b> things you place yourself: kind, place, size, how much air gets through and the heat they give off, with the air temperature at each one.</td>
  </tr>
  <tr>
    <td width="50%"><img src="docs/images/parts-tab.png" alt="Parts tab"><br><b>Parts:</b> add your own graphics card, fan, CPU, cooler, motherboard, case or kind of block. Every value is checked.</td>
    <td width="50%"><img src="docs/images/case-tab.png" alt="Case tab"><br><b>Case:</b> size, PSU shroud, front and top panels, dust filters, altitude and simulation detail.</td>
  </tr>
  <tr>
    <td width="50%"><img src="docs/images/results-tab.png" alt="Results tab"><br><b>Results:</b> the full text report: power budget, temperatures, airflow per fan, your blocks and where the heat leaves.</td>
    <td width="50%"></td>
  </tr>
</table>

<table>
  <tr>
    <td width="40%"><img src="docs/images/report.png" alt="An exported report picture"></td>
    <td><b>Export picture / Export video</b> makes a 1080 × 1920 report for a phone screen: the airflow, the temperature scale, the six read-outs and your hardware. Every picture and video frame carries the <i>Powered by ElAmouri</i> line.<br><br><img src="docs/images/about.png" alt="About box" width="420"></td>
  </tr>
</table>

---

## Using the app

**Left side: the live view.**

* **Colours** show the air temperature. Blue is room air; dark red is 20 °C warmer.
* **Black dashes** show which way the air moves. Longer dashes mean faster air.
* **Fan icons** sit outside the case. Blue arrows blow in, red arrows blow out. The numbers show the CFM, and exhaust fans also show the temperature of the air leaving through them.
* **"air in" labels** show the temperature of the air entering the CPU cooler and the GPU fans.
* **Blocks** are drawn with their number and kind: hatched = solid, filled = dense, striped = cables, crossed = mesh. An orange outline means the block gives off heat; its air temperature is shown next to it. The small triangle in the top-right corner is the handle for resizing it.
* **The tiles underneath** show the CPU / GPU estimates, power use, total airflow, the pressure inside the case and where the heat leaves.

**Mouse on the picture:**

| Do this | What happens |
|---|---|
| drag a fan | moves it. Wall fans slide along their wall; side and inside fans go anywhere. The outline turns red where the fan would sit on something; let go there and it snaps to the nearest free spot |
| drag a block | moves it, the same way: red outline where it would sit on something, and it snaps right beside it when you let go |
| drag a block's corner (the small triangle) | resizes it; the opposite corner stays where it is. A size that would sit on something is refused |
| double-click an empty spot | adds a fan there: near a wall it becomes a wall fan, anywhere else a fan *inside* the case |
| mouse wheel over a fan | speed +5 % / −5 % |
| right-click a fan | reverse · auto (fan curve) · full / half speed / stop · duplicate · delete |
| right-click a block | duplicate · turn 90° · how much air gets through · kind · delete |
| right-click an empty spot | add a fan there, or a block of any kind |

**Right side: six tabs.**

| Tab | What you can change |
|---|---|
| **Hardware** | CPU · your own CPU watts · CPU cooler (tower 120 / dual 120 / dual 140, or a 240 / 280 / 360 AIO on top or front, blowing in or out) · cooler fan model, number of cooler fans (push, push-pull, 3 on a dual tower) and which way the tower blows · cooler fan speed · motherboard (ATX / E-ATX / Micro-ATX / Mini-ITX; board size, socket and RAM slot positions, chipset and power-stage heat) · RAM (1 / 2 / 4 sticks, DDR4 / DDR5, ECC) · M.2 SSDs and 3.5" hard drives · graphics card, your own GPU watts, card length, GPU fan speed · load (idle / gaming / max stress) · room temperature · PSU watts, 80 PLUS rating, PSU fan mode and speed. The box underneath shows the power budget, the recommended PSU size and every fan speed in rpm. |
| **Fans** | All fans with live CFM, rpm and air temperature. Select a fan to set **where it goes** (front, top, rear, bottom, side panel, or inside, blowing up / down / to the rear / to the front), its **position in mm**, **in or out**, the **fan model** and its **speed**. The **fan curve** drives every fan set to auto from the hottest of CPU / GPU (or only one of them), like a motherboard fan header. Add, duplicate or remove fans, set all fans at once, fix overlaps, or load a ready-made layout (your blocks stay). |
| **Blocks** | All blocks with the live air temperature at each one. Pick a kind and press **+ Add block**; select a block to set its **kind**, its **centre in mm** (from the rear wall and above the floor), its **size**, how much **air** gets through and the **heat** it gives off. **Turn 90°** swaps width and height. |
| **Case** | Case size presets or your own inside depth, height and width · PSU shroud · front and top panel type · dust filters (clean / dusty / clogged) · altitude · simulation detail. |
| **Parts** | Your own parts: pick a type, press **+ New** or **Copy as new**, fill in the numbers and **Save part**. They appear in every list; **Use in this setup** puts the selected part into the current setup (a kind of block is added to the case). |
| **Results** | The full text report, the same one the command line prints. |

**Bottom bar:** Pause / Play · Restart airflow · Open / Save setup · Export picture · Export video. Exports run in the background, so you can keep working.

After a change the simulation gets most of the time for about a second of simulated time while the air settles; the numbers are final once the status bar no longer says *settling…*.

**Fan positions** are measured to the centre of the fan: front and rear fans from the case floor, top and bottom fans from the rear wall, side-panel and inside fans from the rear wall plus the height above the floor. Bottom fans under the PSU shroud sit on the shroud and pull air in through the floor, like real shroud-mounted fans.

**No stacked fans or blocks.** *+ Add fan*, *+ Add block*, *Duplicate*, dragging, resizing, typing a position and changing a fan's wall all check the real parts in the case: other fans, blocks, the PSU, the GPU and its bracket, the cooler, the radiator, the drive cage and the shroud. A fan or block that cannot fit is drawn as a yellow dashed box with ✕, and **Fix overlaps** moves it to a free spot.

## Blocks

<p align="center"><img src="docs/images/blocks.png" alt="Blocks in the case: a pump with its reservoir, a cable bundle behind the front fans, a capture card and a 2.5-inch SSD"></p>

A block is anything you put in the case yourself. Pick a kind in the Blocks tab and press **+ Add block**, or right-click an empty spot in the picture. Then drag it where it belongs and drag its corner to resize it.

| Kind | Size (mm) | Air | Heat |
|---|---|---|---|
| Block (no air through) | 80 × 80 | solid | – |
| Divider panel | 4 × 150 | solid | – |
| Dense part (air goes round) | 80 × 60 | dense | – |
| Cable bundle | 30 × 150 | cables | – |
| Mesh / grille | 6 × 150 | mesh | – |
| Pump + reservoir | 60 × 140 | dense | 6 W |
| Capture / sound card | 170 × 20 | dense | 12 W |
| 2.5" SSD | 100 × 10 | dense | 3 W |
| Heat source | 60 × 40 | cables | 20 W |

Every block keeps its own size, air and heat, so you can stretch a cable bundle or give a heat source 80 W.

* **Air:** *solid* = no air gets through. It fills the whole case width, like a panel or a closed drive cage. *Dense* = the air squeezes round it, like a pump, a drive or a card. *Cables* = some air gets through. *Mesh* = most air gets through.
* **Heat** goes into the air inside the block, or, for a solid block, into the air right round it. It is part of the power budget and the PSU recommendation, because the PSU powers it.
* The tiles, the Fans and Blocks lists and the report show what a block changes: try a cable bundle right behind the front fans, or a pump in the path of the CPU cooler.
* Your own kinds of blocks (Parts tab → *Blocks*) are saved like your other parts and travel inside the setups that use them.
* A pocket of air closed in by blocks (or a case without any fan) cannot exchange air with the room. It is simulated as if it had a small gap, and a note says so.

## Your own parts

1. In the **Parts** tab pick the part type, for example *Graphics cards*.
2. Select a similar part and press **Copy as new**, or press **+ New**.
3. Type a name and the numbers from the spec sheet, then **Save part**. If a value is out of range, the app says which one and what is allowed.
4. Press **Use in this setup**, or pick the part from the normal lists.

| Part | What you enter |
|---|---|
| Fan | size (mm), maximum rpm, airflow (CFM) and static pressure (mmH₂O) at full speed |
| Graphics card | maximum board power (W), length (mm), thickness (slots), number of fans |
| Processor | maker, memory type, box TDP, power limit (AMD PPT / Intel PL2), typical gaming and idle watts, die-to-cooler resistance, throttle temperature |
| CPU cooler | tower (fin stacks, thickness, height, fan size) or AIO (radiator fans, fan size), thermal resistance at full fan speed |
| Motherboard | size, chipset watts, CPU power-stage efficiency, ECC with Intel Core CPUs |
| Case | inside depth, height, width, PSU shroud and its size |
| Block | width and height (mm), how much air gets through (solid / dense / cables / mesh), the heat it gives off (W) |

Your parts are saved in `my_parts.json`: on Windows in `%APPDATA%\PC Airflow Lab\`, on macOS / Linux in `~/.config/pc-airflow-lab/` (the Parts tab shows the path and has an *Open folder* button). A saved setup also carries the parts it uses, so it opens on another PC. Entries the app cannot use are never deleted from the file. The built-in lists are in `pcflow/hardware.py`.

## Setup files

Setups are plain JSON files (Save setup in the app, or by hand):

```json
{
  "case": {"depth_mm": 440, "height_mm": 450, "width_mm": 210,
           "shroud": true, "shroud_height_mm": 90, "shroud_length_mm": 340,
           "front_panel": "mesh + dust filter", "top_panel": "mesh + dust filter"},
  "fans": [
    {"wall": "front", "pos_mm": 130, "direction": "in",  "model": "Generic 120 mm (1500 rpm)", "speed_pct": 70},
    {"wall": "top",   "pos_mm": 100, "direction": "out", "model": "Generic 120 mm (1500 rpm)", "speed_pct": 70},
    {"wall": "rear",  "pos_mm": 342, "direction": "out", "model": "Generic 120 mm (1500 rpm)", "speed_pct": 70},
    {"wall": "side",  "pos_mm": 300, "pos2_mm": 300, "direction": "in", "model": "Arctic P12 PWM PST", "speed_pct": 80},
    {"wall": "inside","pos_mm": 340, "pos2_mm": 150, "direction": "up", "model": "Arctic P12 PWM PST", "rpm": 1200}
  ],
  "cpu": "AMD Ryzen 7 7800X3D", "cooler": "Single tower 120 mm (Hyper 212 / AK400 class)",
  "gpu": "NVIDIA GeForce RTX 4070 Super", "psu_watts": 750, "psu_rating": "80 PLUS Gold",
  "load": "gaming", "room_c": 22, "quality": "normal",
  "motherboard": "ATX mainstream (B650 / B760 / B860 class)",
  "ram_sticks": 2, "ram_type": "DDR5", "ram_ecc": false, "nvme_count": 1, "hdd_count": 0,
  "filter_condition": "clean", "altitude_m": 0,
  "fan_curve": {"source": "hottest", "t_lo": 50, "pct_lo": 30, "t_hi": 80, "pct_hi": 100},
  "blocks": [
    {"model": "Pump + reservoir", "x_mm": 330, "y_mm": 300, "w_mm": 60, "h_mm": 140, "air": "dense", "watts": 6},
    {"model": "Cable bundle", "x_mm": 375, "y_mm": 160, "w_mm": 30, "h_mm": 120, "air": "cables", "watts": 0}
  ]
}
```

* Any fan can use `"rpm"` instead of `"speed_pct"`; `-1` means *auto* (case fans follow `fan_curve`; the cooler, GPU and PSU fans follow the load, like their own fan curves).
* Inside fans blow `up`, `down`, `left` (to the rear) or `right` (to the front). `0` watts or `0` length means *take it from the built-in list*.
* Blocks: `x_mm` / `y_mm` are the centre (from the rear wall / above the floor), `w_mm` × `h_mm` the size, `air` is `solid`, `dense`, `cables` or `mesh`, `watts` the heat. Values left out come from the block's kind (`model`).
* Anything unknown, misspelled or out of range is replaced by a safe value, and the app lists what it changed.
* `configs/my_pc.json` is the example PC: 3 front fans in, 3 top out, 1 rear out, PSU fan from the bottom. Others: `positive_pressure.json`, `classic_2in_2out.json`, `aio_360_top.json`, `example_extra_fans_push_pull.json`, and `example_blocks.json` (the example PC with a pump, cables, a capture card and an SSD).

## Command line

```
py run_cli.py configs/my_pc.json --report                 # text report
py run_cli.py configs/my_pc.json --png result.png          # picture
py run_cli.py configs/my_pc.json --video result.mp4 --seconds 20 --quality high
py run_cli.py configs/my_pc.json --report --load max       # another load without editing the file
py run_cli.py --selftest                                   # checks the physics (air in = air out, energy balance)
```

The Windows program runs the same command line: `PC_Airflow_Lab.exe --cli my_setup.json --png result.png`, `PC_Airflow_Lab.exe --selftest`, `PC_Airflow_Lab.exe --version`. It is a window program, so in a Command Prompt use `start /wait PC_Airflow_Lab.exe --selftest` to see the output before the prompt returns. `--quality` sets the cell size: `fast` 4 mm, `normal` 3 mm, `high` 2 mm.

## Run from the source

1. Install **Python 3.10 or newer** (on Windows from <https://www.python.org/downloads/>, with *Add python.exe to PATH* ticked; it includes Tkinter).
2. Download this repository (**Code → Download ZIP**) and unzip it, or `git clone https://github.com/Elamouri/PC-AirFlow-Lab-2D-.git`.
3. Windows: double-click **`start_windows.bat`**. macOS / Linux: `sh start_linux_mac.sh` (on Linux you may first need `sudo apt install python3-tk`).

By hand:

```
py -m pip install -r requirements.txt
py pc_airflow_lab.py configs\my_pc.json
```

## Build the .exe yourself

On Windows with Python 3.10 – 3.13, double-click **`tools\build_exe.bat`**. It installs the libraries and PyInstaller, then builds `dist\PC_Airflow_Lab.exe`. By hand:

```
py -m pip install -r requirements.txt pyinstaller
py -m PyInstaller --noconfirm --clean pc_airflow_lab.spec
```

On Linux, `tools/build_exe_wine.sh` does the same through Wine 11 or newer, with a Windows Python installed in the Wine prefix. `tools/make_readme_images.py` remakes `docs/images/report.png` and `demo.gif`; `tools/make_screenshots.py` remakes the window pictures (it needs a screen; on Linux `xvfb-run` gives it one).

## How it works, and how realistic it is

**Physics.** The app solves the equations of air flow (incompressible Navier–Stokes with buoyancy) and heat transport on a grid of 2–4 mm cells, in real units.

* **Air in equals air out exactly.** More fans in than out raises the pressure inside the case; the intake fans slow down and the exhaust fans speed up, as real fans do.
* **Each fan follows a fan curve:** its airflow drops as the pressure it pushes against rises. Fan laws scale airflow with rpm and pressure with rpm².
* **Resistances:** front mesh, dust filters, grilles, the cooler and GPU fins, the radiator and the inside of the PSU each slow the air. The GPU fins only pass air up and down, because they are seen edge-on.
* **Heat:** the CPU cooler or radiator, the GPU, the PSU (its 80 PLUS loss), the motherboard (chipset, CPU power stage, M.2 SSDs, fan motors), the RAM and the hard drives each give their power to the air passing through them. Energy is conserved, and `--selftest` checks it.
* **Dust filters** raise the filter resistance 1.6× (dusty) or 3× (clogged). **Altitude** thins the air (1000 m ≈ 11 % thinner): fans move the same volume, but it carries less heat.
* **Auto fans** read the CPU / GPU estimate every 0.3 s and change speed by at most 10 % at a time, so they settle instead of hunting.
* **Hot air rises** (buoyancy), and turbulence is modelled as extra mixing.

* **Blocks** you place are solid cells (no air at all) or porous parts with a resistance: dense 2500 /s (like a hard drive), cables 400 /s, mesh 60 /s. Their heat goes into the air inside them, or round a solid one.
* **Air with no way out** (a case without fans, a pocket closed in by blocks) has no pressure of its own; one cell of each such pocket is tied to the room, like a small gap.

**Limits.** It is 2D: the view is averaged across the width of the case, from the glass to the motherboard tray. The case is sealed apart from the fan openings. The CPU and GPU temperatures are estimates (simulated air temperature at the cooler + power × thermal resistance; the CPU cooler's resistance follows the simulated airflow through its fins), so treat them as ±5–10 °C. **Use it to compare setups:** is the front-most top fan better as an intake? Where does the GPU's hot air go? Does a front 360 AIO heat up the GPU? It does not replace a thermometer.

**Why the live view is quick.**

* **The solver makes no new arrays while it runs.** Every work array is made once (the advection work is shared by the air speed and the temperature), the flow and temperature fields are 32-bit, all fans and all heat sinks are handled in one go, and what only depends on the walls (the pressure factorisation, index lists) is kept while they stay the same. A step at normal detail takes 3.9 ms instead of 7.8 ms and gives the same answers.
* **The live view takes a slightly longer step:** 0.85 × cell / (1 m/s) instead of 0.7. The porous resistances keep the loss per second they were tuned with, so the results stay within about 0.5 °C and 1 % airflow (a step of 1.0 was tried too, but then the heat balance drifted). The command line, pictures and videos keep the shorter step.
* **Drawing:** the case, the parts, the fan housings and the fixed labels are drawn once into see-through layers. Each frame then only paints the moving air, the spinning blades and the numbers, and pastes the layers in between, in the same stacking order as a normal drawing. Pictures never take more than 30 % of the time (on a slower PC there are a few less of them, and the air keeps its speed), and the Results text is only made while its tab is open.
* **The window:** the simulation runs in slices of about 16 ms with the window answering in between, and changed controls are redrawn after every slice. The next slice is started with a zero delay, because Windows waits a whole clock tick (about 15 ms) for any other delay.

## Project layout

```
pc_airflow_lab.py     start file for the window and the command line (what the .exe runs)
pc_airflow_lab.spec   PyInstaller recipe for PC_Airflow_Lab.exe
run_gui.py, run_cli.py, start_windows.bat, start_linux_mac.sh, requirements.txt
configs/              example setups (.json)
assets/               app icon
docs/                 PLAN.md (implementation plans) and images/ (this page)
tools/                build_exe.bat, build_exe_wine.sh, make_icon.py, make_readme_images.py, make_screenshots.py
pcflow/
  branding.py         name, version and the Powered by ElAmouri credit
  hardware.py         parts database (GPUs, CPUs, coolers, fans, motherboards, RAM, drives, PSUs, cases, blocks)
  library.py          your own parts: checks, my_parts.json, parts stored inside setups
  placement.py        finds a free spot for new / duplicated / moved fans and blocks
  safejson.py         reads JSON files from other people safely
  config.py           setup format, load / save with checks, ready-made layouts
  layout.py           turns a setup into geometry: walls, fan openings, fins, heat sources
  solver.py           the airflow + heat simulation
  thermal.py          power budget, PSU efficiency, temperature estimates
  results.py          numbers for the read-outs and the text report
  render.py           drawing the case, the quick live frames and the video frames
  video.py            MP4 / GIF / PNG export
  gui.py              the desktop app (Tkinter)
  cli.py              command line
tests/                pytest tests
```

## Tests

```
py -m pip install pytest
py -m pytest -q
```

294 tests cover:

* **fans, blocks and parts:** fans and blocks never overlap at any detail level; random mixes of blocks never break the simulation; the parts library; hostile setup files
* **physics:** motherboard, RAM, drives, filters, altitude, fan curves and blocks; conservation checks; air with no way out
* **speed:** the fast solver gives the plain solver's answers (advection, face averages, all fans at once); the live step is stable and keeps the balance; the factorisation is kept when only porous parts move
* **output:** picture, video and command line; the credit line
* **the window:** the .exe start-up code; high-DPI and small screens; the quick live view (it matches a normal drawing, also after a new layout, and stays under half its time; speed changes keep the drawing; the window answers while the simulation runs; pictures leave most of the time to the simulation); blocks with the mouse, the Blocks tab and the Parts tab

The window tests need a screen and are skipped without one. Each version was planned in `docs/PLAN.md` and checked by code, security and silent-failure reviews; every finding has a regression test.

## Troubleshooting

* **`No module named tkinter`:** on Windows, reinstall Python with the default options; on Linux, `sudo apt install python3-tk`.
* **The simulation itself is slow on an old PC:** set *Simulation detail* to **fast** in the Case tab. The window stays responsive either way, and exports use their own *Video / picture detail*.
* **"Windows protected your PC":** click **More info → Run anyway** (new program without a paid code-signing certificate).
* **An antivirus program blocks the .exe:** one-file PyInstaller programs are sometimes flagged by mistake. Build it yourself (above) or run the Python version.
* **The .exe takes a few seconds to start:** it unpacks itself into a temporary folder every time.
* **A fan or a block is "left out":** read the yellow notes above the view, then press **Fix overlaps** in the Fans or Blocks tab, or drag it to a free spot.
* **"Pocket of air closed in":** blocks (often solid ones) close off some air completely. Leave a gap, or make one of them dense, cables or mesh.
* **Video saves as GIF:** `imageio-ffmpeg` is missing (`py -m pip install imageio-ffmpeg`).
* **Something went wrong:** details are in `pc_airflow_lab.log` next to `my_parts.json`.

## Credits

**Powered by ElAmouri**

* GitHub: <https://github.com/Elamouri>
* WhatsApp: [+962 79 674 2759](https://wa.me/962796742759)
