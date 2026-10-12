# Implementation Plan: PC Airflow Lab v1.2 — parts library, motherboards, placement fixes

*(written with the ECC `planner` agent format)*

## Overview
Users can add their own parts (fans, GPUs, CPUs, coolers, motherboards, cases) from inside the app. New fans never
land on top of existing ones. Motherboard type, RAM (DDR4/DDR5, ECC), storage, dust-filter condition, altitude and an
automatic case-fan curve are simulated.

## Requirements
- Fix "duplicate fan" problems: **Add**, **Duplicate**, changing a fan's wall and dragging must never create a fan
  that overlaps another fan, the PSU, the GPU bracket or a radiator (today it is "left out").
- A **Parts** tab to create / copy / edit / delete custom fans, GPUs, CPUs, coolers, motherboards and cases, with
  validated fields, saved to `my_parts.json` and embedded in saved setups (so a setup opens on another PC).
- **Motherboard type** (E-ATX / ATX / Micro-ATX / Mini-ITX, mainstream / high-end): board size, socket, PCIe slot
  (GPU height) and RAM slots move; chipset + VRM power heats the board area.
- **RAM**: number of sticks, DDR4 / DDR5, **ECC** on/off → power + heat next to the CPU cooler intake.
- **Storage**: NVMe count (board heat), 3.5" HDD count (drive cage under the shroud: blocks air + heat).
- **Dust filters**: clean / dusty / clogged → more resistance. **Altitude** → thinner air (Amman ≈ 800–1000 m).
- **Case fan "auto"**: follows a fan curve on the hottest of CPU / GPU, like a motherboard fan header.
- Tests first (pytest), ECC reviews (python-reviewer, security-reviewer, silent-failure-hunter) before delivery.

## Architecture Changes
- `pcflow/placement.py` (new): free-spot search on walls and inside the case, using the real layout geometry.
- `pcflow/library.py` (new): part schemas, validation, load/save `my_parts.json`, embed/extract in setups,
  register custom parts into `hardware` tables.
- `pcflow/hardware.py`: `MOTHERBOARDS`, `RAM_TYPES`, storage powers, `FILTER_CONDITIONS`, custom-part registry.
- `pcflow/config.py`: new fields (`motherboard`, `ram_*`, `nvme_count`, `hdd_count`, `filter_condition`,
  `altitude_m`, `fan_curve`), custom parts in JSON, `speed_pct = -1` = auto for case fans.
- `pcflow/thermal.py`: power breakdown (board, RAM, storage, fans), air density.
- `pcflow/layout.py`: board form factor geometry, RAM heat block, HDD cage, filter multiplier, density-aware fans.
- `pcflow/solver.py`: per-instance air density; live update of auto case fans (no rebuild).
- `pcflow/render.py`: board outline per form factor, RAM sticks, HDD cage, auto-fan marker.
- `pcflow/gui.py`: Parts tab, motherboard / RAM / storage controls, filter + altitude, per-fan *auto*, placement.
- `tests/` (new): unit + integration tests.

## Implementation Steps

### Phase 1: Tests first (RED)
1. **Placement tests** (tests/test_placement.py) — adding 4th front fan goes to another wall / inside; duplicate never
   overlaps; dragged overlap snaps to nearest free spot. Risk: Low.
2. **Library tests** (tests/test_library.py) — add/edit/delete, validation errors, round-trip file, embedded parts in
   setup JSON load on a clean registry. Risk: Low.
3. **Hardware/physics tests** (tests/test_layout.py, test_thermal.py, test_solver.py) — ITX board moves GPU, RAM power
   by type/ECC, HDD count adds heat, clogged filters reduce airflow, altitude raises temperatures, auto fan speeds up
   under load, mass balance exact, energy balance within 10 %. Risk: Medium (physics tolerances).

### Phase 2: Engine (GREEN)
4. `hardware.py` + `library.py` (Dependencies: none). Risk: Low.
5. `config.py` fields + JSON (Requires 4). Risk: Low.
6. `thermal.py` power breakdown + density (Requires 5). Risk: Low.
7. `layout.py` motherboard / RAM / HDD / filters / density (Requires 6). Risk: Medium — geometry clashes.
8. `placement.py` (Requires 7). Risk: Medium — must agree with layout's overlap rules (uses the layout itself).
9. `solver.py` density + auto fans (Requires 7). Risk: Medium — stability when fan speeds change live.

### Phase 3: App + drawing
10. `render.py` (Requires 7). Risk: Low.
11. `gui.py` Parts tab, new controls, placement integration (Requires 4–10). Risk: Medium — Tk state syncing.

### Phase 4: Quality gate
12. Run tests + coverage (target ≥ 80 % on non-GUI modules).
13. ECC review agents → fix CRITICAL/HIGH findings.
14. Automated GUI click-through on a virtual display, screenshots, README, package.

## Testing Strategy
- Unit: placement, library validation, power breakdown, config round-trip.
- Integration: layout + solver on several setups (fast grid) checking conservation and trends.
- GUI: scripted click-through (`tests/gui_smoke.py`, needs a display).

## Risks & Mitigations
- **Risk**: overlap rules in placement drift from layout → **Mitigation**: placement asks a probe `Layout` for blocked
  spans instead of re-implementing them.
- **Risk**: bad custom part values crash the solver → **Mitigation**: schema with min/max, rejected on save and on load.
- **Risk**: auto fans oscillate → **Mitigation**: smoothed temperature, update every 0.3 s, change ≤ 10 %/update.

## Success Criteria
- [x] No new fan is ever created on top of another (tests).
- [x] Custom parts can be created in the app, used, saved, and reopened from a setup file on a fresh install.
- [x] Motherboard, RAM/ECC, storage, filters, altitude, fan curve all change the simulation.
- [x] All tests pass; ECC reviews have no open CRITICAL/HIGH findings.

## Results
- 199 pytest tests pass (placement, parts library, hardware model, physics, export / CLI, review regressions, GUI
  under a virtual display). Coverage: 83 % overall, 84-98 % on every non-GUI module, 69 % on the GUI.
- Scripted click-through of the app (35 steps: add / duplicate / drag / wall change, motherboard, RAM / ECC,
  drives, auto fans and curve, filters, altitude, all six part types, save and reopen on a clean library,
  fix overlaps, PNG export) passes.
- ECC reviews, three rounds:
  - python-reviewer: Block (4 HIGH) -> Warning -> **Approve**
  - security-reviewer: PASS (3 MEDIUM) -> PASS -> **PASS**
  - silent-failure-hunter: 17 findings -> 4 partly open + 1 new -> **all fixed**
  Every finding has a regression test in `tests/test_review_fixes.py` / `tests/test_gui.py`.
- Design change found while testing: Mini-ITX / Micro-ATX boards no longer move the graphics card - in a real
  case the card always sits in the case's top expansion slot.

---

# v1.3: "Powered by ElAmouri" and a Windows .exe

## Requirements
- Credit "Powered by ElAmouri" with GitHub (https://github.com/Elamouri) and WhatsApp (+962 79 674 2759) in the
  app and in what it produces.
- One Windows program file (.exe) that needs no Python.

## Steps
1. `pcflow/branding.py` holds the name, version and credit; the window title, footer links, About box, report
   picture / video frames, PNG / MP4 / GIF metadata, text report and `--version` use it.
2. `pc_airflow_lab.py` starts the window, or the command line for `--cli` / any option; it repairs text output in
   a window program (pipe, console, or nowhere) and turns unexpected errors into a normal exit code.
3. `pc_airflow_lab.spec`: one file, no console window, icon, version details from `branding.py`, unused library
   parts left out (100 MB -> 75 MB).
4. Frozen mode in the app: setups in `Documents\PC Airflow Lab`, exports re-run the .exe with `--cli`, no console
   windows for the export, ffmpeg or taskkill.
5. Layout: text size fitted to the screen at 125 / 150 % scaling, the controls keep their width, the read-outs
   wrap into two rows on small screens.

## Results
- 226 pytest tests pass; coverage 83 %.
- The .exe was built with PyInstaller 6.22 (Windows Python 3.12) and run under Wine 11 on virtual screens of
  1600 x 1000, 1920 x 1080 at 150 % and 1366 x 768: window, About box, picture export from the window, video export
  with the bundled ffmpeg, `--selftest`, `--version`.
- Review (python / security / silent-failure in one pass): 1 MEDIUM (an unexpected command-line error opened a
  blocking dialog in the .exe) and 4 LOW (tiles not re-checked when numbers grow, a matplotlib warning from a left-out
  module, Windows browser failure not reported, deleted example setups came back) - all fixed with tests.
- A PyInstaller start-up picture was tried and dropped: in the same process it made Tk see a wrong screen size.

---

# v1.4: no more lag in the live view

## Measurements before (Linux, default window, "normal" detail)
- A frame: 84-98 ms to draw (texts 37 ms, temperature image 26 ms, parts 20 ms, flow dashes 14 ms).
- One loop turn: 30 ms (120 ms while settling) of simulation + a frame. Clicks waited 190 ms on average, 280 ms at
  worst (Windows Python: 154 ms average, 225 ms 95th percentile).
- A speed change: new solver factorisation (55 ms) + new drawing (55 ms) + a full draw; sliders waited 350-400 ms.

## Steps
1. `render.LiveFrames`: the parts that do not move are drawn once into see-through layers, one per height level
   between the moving parts (field, dashes, edge blades, icon blades, numbers). The temperature field is scaled
   with Pillow and a colour table. The number layer is redrawn only when a number changes. The drag marker is
   pasted on the last frame.
2. Flow dashes in 6 shades, one path each, instead of 900 paths. Fan blades computed with numpy.
3. `gui.tick`: one 16 ms simulation slice or one frame per loop turn. 20 frames a second, 5 while settling.
4. Solver: the pressure factorisation is reused when the cells are the same. The view is reused when
   `render.drawing_key` is the same (only speeds, loads or temperatures changed).
5. Parts added with `add_artist`, so matplotlib does not measure every shape for autoscaling.

## Results
- A quick frame takes 12-16 ms, and its pixels match a normal drawing (mean difference 0.3 of 255 levels).
- Clicks wait 13 ms on average and 21 ms at the 95th percentile (Windows Python under Wine: 19 / 40 ms, was
  154 / 225 ms). The simulation advances about 50 % faster.
- A speed change takes about 16 ms; a moved fan takes about 180 ms (new factorisation and drawing).
- Tests: tests/test_speed.py (quick frame looks like a normal drawing and is under half its time, drawing key,
  factorisation reuse, fan blade shape, the window answers while running, drag marker, fallback to normal drawing).

---

# v1.5: less lag, and blocks you place yourself

## Requirements
- Reduce the lag that is left: the air moved in slow motion and took long to settle after a change, controls were
  redrawn late while the air settled, and moving a fan redrew the view slowly.
- Let people add parts the way they want, such as a block area: something that stops the air, cables, a grille, or a
  part that makes heat, placed and sized anywhere in the case.

## Measurements before (Linux, default window, "normal" detail)
- A simulation step: 7.8 ms for 2.1 ms of air (0.27x real time): advection 3.8 ms (mostly making and freeing
  temporary arrays), pressure solve 1.5 ms, diffusion 1.1 ms, fans / heat / wall fill / projection 1.4 ms.
- In the window (real Tk main loop): 0.16-0.19x real time; after a change the air settled in 4.2 s (7.7 s after a
  restart). While settling the loop used `after(0)`, so Tk's idle work (redrawing controls) only ran inside the
  picture blits: controls waited 0.8-1.3 s (median) and up to 4 s. On
  Windows every other turn waited for the ~15 ms clock tick (`after(2)`).
- A moved fan: ~105 ms (new factorisation 55, drawing 26, layers 50; `ax.clear()` alone 21 ms).

## Steps
1. Solver without temporary arrays: `Advection` works in arrays made once (shared by u, v and T), float32 fields,
   fans and heat sinks in one go (`np.add.reduceat`), the wall temperature fill as a sparse map, flat index lists,
   the pressure factorisation in a `Geometry` that the next solver reuses when the cells of air are the same.
   Same operations in the same order: the fast advection equals the plain one exactly in float64.
2. Longer live step (0.85 instead of 0.7 cell per (m/s)); `Solver.damping` keeps the tuned loss per second of every
   porous part. A step of 1.0 was tried first: the averages stayed within 1 K, but the heat balance check (heat out
   vs heat in) drifted from +4 % to +12-14 %, so the live view uses 0.85 (+7 to +10 %). Exports and the command line
   keep 0.7.
3. Window loop: `after(0)` (never `after_idle`: `update_idletasks()` would then run the simulation forever),
   `update_idletasks()` after each slice, pictures limited to 30 % of the time, the Results text only while its tab
   is open, `clear_view` instead of `ax.clear()`, the background reused when the canvas did not change, flow dashes
   with square ends.
4. Blocks: `hardware.BLOCKS` (nine kinds), `config.Block` and `Config.blocks` (file version 3), `Layout` builds them
   before the RAM and the fans (solid = no air, others porous; heat into or round them, after all blocks are in),
   `placement` finds the nearest free spot (including right beside every part) and fixes overlaps, the power budget
   counts their heat, `library` has a Blocks category, the view, the report and the exports show them, and the
   window has a Blocks tab, mouse drag / resize and right-click menus.
5. Air with no way out (no fans, a pocket closed in by blocks) made the pressure matrix singular: one cell of each
   closed pocket is tied to the room (`scipy.sparse.csgraph`; `scipy.ndimage` is left out of the .exe).
6. The .exe adds new example setups once (`examples_offered.json` next to `my_parts.json`).

## Results
- A step at normal detail: 3.9 ms (was 7.8), fast 2.5 ms (4.7), high 11.5 ms (19.5). The old and the new solver give
  the same averages on five setups (CPU / GPU air within 0.1 K, airflow within 0.2 %). The live step (0.85) moves CPU
  / GPU air by -0.04 to +0.56 K and airflow by less than 1 % on five setups, the blocks example the most (1.0 moved
  CPU air by +0.4 to +0.9 K).
- In the window: 0.33-0.38x real time (was 0.16-0.19x); after a change the air settles in 1.7 s (was 4.2 s), after a
  restart in 3.4 s (was 7.7 s); controls wait ~20 ms (median) and 40-60 ms at most (were 0.8-1.3 s and up to 4 s); a
  moved fan or block redraws in ~73 ms (was ~105 ms); a picture takes ~10 ms (was ~12 ms).
- A randomised test of blocks (any kind, size, place, air and heat on every ready-made setup): no failure, no heat in a
  solid cell, every watt accounted for, and *Fix overlaps* leaves nothing on top of anything in one run.
- 294 pytest tests pass (58 new: blocks, solver equivalence, window loop, block mouse / tabs, example updates,
  review fixes).

