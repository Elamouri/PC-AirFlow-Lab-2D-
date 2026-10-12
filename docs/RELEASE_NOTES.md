## PC Airflow Lab 1.5.0 · Powered by ElAmouri

**Download `PC_Airflow_Lab.exe` below.** It runs on Windows 10 / 11 (64-bit) as one file, with no install and no Python needed.

### What's new
- **Less lag: the air moves about 2.5 times faster in the live view.** A simulation step takes half the time with the same physics, and the live view takes a longer step. After a change the air settles in about 1.5–3 s instead of 4–7 s.
- **Smooth controls while the air moves.** Buttons, sliders and numbers are redrawn at once instead of waiting up to 3.5 s, and on Windows the simulation no longer pauses for a clock tick between its slices.
- **Blocks: put your own parts anywhere in the case.** A block that stops the air, a divider panel, cables, a grille, a pump with its reservoir, a capture card, a 2.5" SSD or any part that makes heat. Drag them, resize them by their corner, set how much air gets through and how many watts they give off. Save your own kinds of blocks in the Parts tab.
- A case without fans, or air closed in by blocks, now gets a sound answer and a note.
- Earlier: a quicker live view, the one-file Windows program, your own parts, no stacked fans (see [CHANGELOG.md](https://github.com/Elamouri/PC-AirFlow-Lab-2D-/blob/main/CHANGELOG.md)).

### First start
- Windows may show **"Windows protected your PC"**, because the program is new and not code-signed. Click **More info → Run anyway**.
- The window takes a few seconds to open, because the program unpacks itself first.
- Setups are kept in `Documents\PC Airflow Lab`, your own parts in `%APPDATA%\PC Airflow Lab\my_parts.json`. The new example `example_blocks.json` is added to your setups folder once (delete it and it stays deleted).
- Command line: `PC_Airflow_Lab.exe --selftest`, `PC_Airflow_Lab.exe --cli my_setup.json --png result.png`.

**Powered by ElAmouri** · [GitHub](https://github.com/Elamouri) · [WhatsApp +962 79 674 2759](https://wa.me/962796742759)
