"""Desktop app: edit fans and hardware, add your own parts, watch the airflow live, export a video.

Run:  python run_gui.py   (or double-click start_windows.bat)

Mouse on the picture:
  drag a fan            move it (wall fans slide along their wall; it never lands on another fan)
  drag a block          move it; drag the small triangle in its top-right corner to resize it
  double-click          add a fan there (near a wall = wall fan, elsewhere = fan inside the case)
  mouse wheel on a fan  speed up / slow down by 5 %
  right-click a fan     reverse / auto / full speed / half speed / duplicate / delete
  right-click a block   duplicate / turn 90° / how much air gets through / kind / delete
  right-click elsewhere add a fan or a block there
"""
import logging
import logging.handlers
import math
import os
import queue
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
import webbrowser
from tkinter import ttk, filedialog, messagebox

import matplotlib
matplotlib.use('TkAgg')
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import numpy as np

from . import branding
from . import hardware as hw
from . import library, placement
from .config import (Config, Fan, Block, PRESETS, QUALITY_MM, PSU_FAN_MODES, COOLER_ORIENTATIONS, INSIDE_DIRS,
                     RAM_STICKS, FAN_CURVE_SOURCES, MAX_BLOCKS, my_pc)
from .layout import Layout
from .solver import Solver, LIVE_STEP
from .results import summarize, text_report
from .render import CaseView, LiveFrames, CMAP, VMIN, VMAX, HANDLE_MM, drawing_key, clear_view
from .thermal import compute_loads

BG = '#0f1420'
PANEL = '#161d2c'
FIELD = '#1e2638'
TXT = '#e9edf5'
SUB = '#9aa3b5'
ACC = '#5ac8fa'
WARN = '#ffd166'
BAD = '#ff6b5a'
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FROZEN = bool(getattr(sys, 'frozen', False))          # running as the Windows .exe
BUNDLE = getattr(sys, '_MEIPASS', HERE)                # where the bundled configs / icons are
PART_COUNT = {'fast': 700, 'normal': 900, 'high': 1100}
STOCK = '(stock fan of the cooler)'
ORIENT_TEXT = {'to rear': 'blows to the rear (normal)', 'to top': 'blows up to the top fans',
               'to front': 'blows to the front', 'to bottom': 'blows down'}
FAN_COUNT_TEXT = {1: '1 fan (push)', 2: '2 fans (push-pull / front + middle)', 3: '3 fans (dual tower: push + middle + pull)'}
CURVE_TEXT = {'hottest': 'the hottest of CPU / GPU', 'cpu': 'the CPU temperature', 'gpu': 'the GPU temperature'}
TAB_FANS = 1
TAB_BLOCKS = 2
AIR_SHORT = {'solid': 'solid', 'dense': 'dense', 'cables': 'cables', 'mesh': 'mesh'}
SIM_SLICE = 0.016                 # s of simulation per turn of the event loop - the window answers in between
FRAME_GAP = 0.045                 # s between pictures (about 20 a second) ...
FRAME_GAP_SETTLING = 0.20         # ... and 5 a second while the air settles after a change
FRAME_SHARE = 0.30                # pictures never take more than this share of the time: on a slower PC the
                                  # picture rate drops a little and the simulation keeps its speed
SPIN_RATE = 9.0                   # fan blade animation steps per second
DESIGN_SIZE = (1600, 1040)        # room the window needs at 100 % text size (with the taskbar)
BASE_SCALING = 96 / 72            # Tk pixels per point at 100 % display scaling
log = logging.getLogger('pcflow')


def setup_logging():
    """problems (with full tracebacks) go to pc_airflow_lab.log next to my_parts.json"""
    path = os.path.join(os.path.dirname(library.parts_path()), 'pc_airflow_lab.log')
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        h = logging.handlers.RotatingFileHandler(path, maxBytes=500_000, backupCount=2, encoding='utf-8')
    except OSError:
        h = logging.StreamHandler()
        path = None
    h.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    log.addHandler(h)
    log.setLevel(logging.INFO)
    return path


def documents_dir():
    """the user's Documents folder (also when Windows moved it, e.g. to OneDrive)"""
    if sys.platform.startswith('win'):
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(1024)
            if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0 and buf.value:
                return buf.value
        except (AttributeError, OSError):
            pass
    return os.path.join(os.path.expanduser('~'), 'Documents')


def setups_dir():
    """where setups are opened / saved: the configs folder, or for the .exe Documents\\PC Airflow Lab
    (the example setups are copied there the first time; your own files are never overwritten)"""
    if not FROZEN:
        return os.path.join(HERE, 'configs')
    folder = os.path.join(documents_dir(), branding.APP_NAME)
    try:
        if os.path.isdir(folder):
            return folder                    # examples only go into a new folder: deleted ones stay deleted
        os.makedirs(folder)
        src = os.path.join(BUNDLE, 'configs')
        for name in (os.listdir(src) if os.path.isdir(src) else []):
            dst = os.path.join(folder, name)
            if name.endswith('.json') and not os.path.exists(dst):
                shutil.copy2(os.path.join(src, name), dst)
    except OSError:
        log.warning('could not prepare the setups folder %s', folder, exc_info=True)
    return folder


def export_command(tmp, kind, out, quality):
    """how a picture / video export is started in the background (the .exe runs itself with --cli)"""
    args = [tmp, '--' + ('video' if kind == 'video' else 'png'), out, '--quality', quality, '--no-parts-file']
    if kind == 'video':
        args += ['--seconds', '20']
    if FROZEN:
        return [sys.executable, '--cli'] + args, tempfile.gettempdir()
    return [sys.executable, os.path.join(HERE, 'run_cli.py')] + args, HERE


def fitted_scaling(scaling, screen_w, screen_h):
    """Tk text size (pixels per point): as big as the display scaling asks for (125 %, 150 % ...), but only
    as far as the whole window still fits on the screen, so nothing is cut off - never below 100 %"""
    room = min(screen_w / DESIGN_SIZE[0], screen_h / DESIGN_SIZE[1])
    return min(scaling, BASE_SCALING * max(1.0, room))


def fit_text_to_screen(root):
    """Windows laptops often run at 125 % / 150 %: keep the window usable there"""
    if not sys.platform.startswith('win'):
        return None
    try:
        now = float(root.tk.call('tk', 'scaling'))
        new = fitted_scaling(now, root.winfo_screenwidth(), root.winfo_screenheight())
        if new < now - 0.01:
            root.tk.call('tk', 'scaling', new)
            log.info('text scaling %.2f -> %.2f so the window fits the screen', now, new)
            return new
    except (tk.TclError, ValueError):
        log.info('could not adjust the text size', exc_info=True)
    return None


def style_dark(root):
    st = ttk.Style(root)
    st.theme_use('clam')
    st.configure('.', background=BG, foreground=TXT, fieldbackground=FIELD, bordercolor='#2a3247',
                 lightcolor=PANEL, darkcolor=PANEL, troughcolor=FIELD, font=('Segoe UI', 10))
    st.configure('TFrame', background=BG)
    st.configure('Panel.TFrame', background=PANEL)
    st.configure('TLabel', background=BG, foreground=TXT)
    st.configure('Panel.TLabel', background=PANEL, foreground=TXT)
    st.configure('Sub.TLabel', background=BG, foreground=SUB, font=('Segoe UI', 9))
    st.configure('PanelSub.TLabel', background=PANEL, foreground=SUB, font=('Segoe UI', 9))
    st.configure('Head.TLabel', background=BG, foreground=TXT, font=('Segoe UI', 11, 'bold'))
    st.configure('Big.TLabel', background=PANEL, foreground=TXT, font=('Segoe UI', 17, 'bold'))
    st.configure('Warn.TLabel', background=BG, foreground=WARN, font=('Segoe UI', 9))
    st.configure('Link.TLabel', background=BG, foreground=ACC, font=('Segoe UI', 9, 'underline'))
    st.configure('Brand.TLabel', background=BG, foreground=TXT, font=('Segoe UI', 9, 'bold'))
    st.configure('PanelLink.TLabel', background=PANEL, foreground=ACC, font=('Segoe UI', 10, 'underline'))
    st.configure('PanelWarn.TLabel', background=PANEL, foreground=WARN, font=('Segoe UI', 9))
    st.configure('TButton', background='#253049', foreground=TXT, padding=(10, 5), borderwidth=0)
    st.map('TButton', background=[('active', '#2f3d5c'), ('disabled', PANEL)], foreground=[('disabled', SUB)])
    st.configure('Accent.TButton', background='#1d6fa5', foreground='white')
    st.map('Accent.TButton', background=[('active', '#2384c4')])
    for w in ('TCheckbutton', 'TRadiobutton'):
        st.configure(w, background=BG, foreground=TXT)
        st.map(w, background=[('active', BG)])
        st.configure('Panel.' + w, background=PANEL, foreground=TXT)
        st.map('Panel.' + w, background=[('active', PANEL)])
    st.configure('TCombobox', fieldbackground=FIELD, background='#253049', foreground=TXT, arrowcolor=TXT)
    st.map('TCombobox', fieldbackground=[('readonly', FIELD), ('disabled', BG)],
           foreground=[('readonly', TXT), ('disabled', SUB)],
           selectbackground=[('readonly', FIELD)], selectforeground=[('readonly', TXT)],
           background=[('active', '#2f3d5c'), ('readonly', '#253049')])
    st.configure('TEntry', fieldbackground=FIELD, foreground=TXT, insertcolor=TXT)
    root.option_add('*TCombobox*Listbox.background', FIELD)
    root.option_add('*TCombobox*Listbox.foreground', TXT)
    root.option_add('*TCombobox*Listbox.selectBackground', '#1d6fa5')
    st.configure('TSpinbox', fieldbackground=FIELD, foreground=TXT, arrowcolor=TXT, background='#253049')
    st.map('TSpinbox', fieldbackground=[('disabled', BG)], foreground=[('disabled', SUB)])
    st.configure('TNotebook', background=BG, borderwidth=0)
    st.configure('TNotebook.Tab', background=PANEL, foreground=SUB, padding=(14, 6))
    st.map('TNotebook.Tab', background=[('selected', '#253049')], foreground=[('selected', TXT)])
    st.configure('Treeview', background=FIELD, fieldbackground=FIELD, foreground=TXT, rowheight=24)
    st.configure('Treeview.Heading', background=PANEL, foreground=SUB)
    st.map('Treeview', background=[('selected', '#1d6fa5')])
    st.configure('Horizontal.TScale', background=BG, troughcolor=FIELD)
    st.configure('Vertical.TScrollbar', background=PANEL, troughcolor=BG, arrowcolor=SUB)


def row(parent, r, text, widget, unit=None, style=''):
    ttk.Label(parent, text=text, style=(style + 'TLabel') if style else 'TLabel').grid(
        row=r, column=0, sticky='w', padx=(0, 8), pady=3)
    widget.grid(row=r, column=1, sticky='ew', pady=3)
    if unit is not None:
        u = ttk.Label(parent, text=unit, style=(style + 'Sub.TLabel') if style else 'Sub.TLabel', width=16)
        u.grid(row=r, column=2, sticky='w', padx=(6, 0))
        return u
    return None


def head(parent, r, text, top=12):
    ttk.Label(parent, text=text, style='Head.TLabel').grid(row=r, column=0, columnspan=3, sticky='w', pady=(top, 0))


def spinbox(parent, var, lo, hi, step, cmd, width=8):
    kw = {'format': '%.0f'} if float(step).is_integer() and float(lo).is_integer() else {}
    sp = ttk.Spinbox(parent, from_=lo, to=hi, increment=step, textvariable=var, width=width, command=cmd, **kw)
    sp.bind('<Return>', lambda e: cmd())
    sp.bind('<FocusOut>', lambda e: cmd())
    return sp


def whole(v):
    """120.0 -> 120 for the number boxes (they show 0, not 0.0); other values unchanged"""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return v
    return int(f) if f.is_integer() else f


class NumVar(tk.DoubleVar):
    """the value of a number box: 120.0 shows as 120 (a decimal value keeps its decimals)"""

    def set(self, value):
        super().set(whole(value))


def fmt_num(v):
    if isinstance(v, bool):
        return 'yes' if v else 'no'
    if isinstance(v, float):
        return '%g' % v
    return str(v)


class SpeedControl:
    """[auto] + % slider + rpm box, all kept in sync."""

    def __init__(self, parent, on_change, max_rpm_fn, with_auto=True, panel=False, auto_text='auto', on_error=None):
        self.on_change, self.max_rpm_fn, self.on_error = on_change, max_rpm_fn, on_error
        self.frame = ttk.Frame(parent, style='Panel.TFrame' if panel else 'TFrame')
        self.v_auto = tk.BooleanVar(value=False)
        self.v_pct = tk.DoubleVar(value=70)
        self.v_rpm = tk.StringVar(value='')
        self.quiet = False
        sub = 'PanelSub.TLabel' if panel else 'Sub.TLabel'
        if with_auto:
            ttk.Checkbutton(self.frame, text=auto_text, variable=self.v_auto, command=self._auto,
                            style=('Panel.TCheckbutton' if panel else 'TCheckbutton')).pack(side='left')
        ttk.Scale(self.frame, from_=0, to=100, variable=self.v_pct, command=self._slid).pack(
            side='left', fill='x', expand=True, padx=6)
        self.lab = ttk.Label(self.frame, text='', style=sub, width=6)
        self.lab.pack(side='left')
        self.spin = ttk.Spinbox(self.frame, from_=0, to=5000, increment=50, textvariable=self.v_rpm, width=6,
                                command=self._typed)
        self.spin.bind('<Return>', lambda e: self._typed())
        self.spin.bind('<FocusOut>', lambda e: self._typed())
        self.spin.pack(side='left')
        ttk.Label(self.frame, text='rpm', style=sub).pack(side='left', padx=(3, 0))

    def set(self, pct, auto=False, shown_pct=None):
        self.quiet = True
        self.v_auto.set(bool(auto))
        self.v_pct.set(shown_pct if (auto and shown_pct is not None) else max(0.0, pct))
        self.quiet = False
        self.refresh()

    def value(self):
        return -1.0 if self.v_auto.get() else float(round(self.v_pct.get()))

    def refresh(self):
        mx = self.max_rpm_fn()
        self.spin.configure(to=mx, increment=max(10, round(mx / 40, -1)))
        p = self.v_pct.get()
        self.lab.configure(text='%3.0f %%' % p)
        try:
            focused = self.spin.focus_get() is self.spin
        except (KeyError, tk.TclError):
            focused = False
        if not focused:
            self.v_rpm.set('%.0f' % (p * mx / 100.0))

    def _slid(self, *_):
        if self.quiet:
            return
        self.v_auto.set(False)
        self.refresh()
        self.on_change(slider=True)

    def _typed(self, *_):
        if self.quiet:
            return
        text = self.v_rpm.get()
        try:
            rpm = float(text.strip().replace(',', '.'))
            if not math.isfinite(rpm):
                raise ValueError
        except (ValueError, OverflowError):
            if self.on_error:
                self.on_error('"%s" is not a number of rpm - type only the number' % library.printable(text, 20))
            self.refresh()
            return
        mx = self.max_rpm_fn()
        pct = max(0.0, min(100.0, 100.0 * rpm / mx))
        if abs(pct - self.v_pct.get()) < 0.05 and not self.v_auto.get():
            return
        self.v_auto.set(False)
        self.quiet = True
        self.v_pct.set(pct)
        self.quiet = False
        self.lab.configure(text='%3.0f %%' % pct)
        self.on_change()

    def _auto(self):
        if not self.quiet:
            self.on_change()


class App:
    def __init__(self, root, cfg=None, notes=()):
        self.root = root
        self.cfg = cfg or my_pc()
        self.sim = None
        self.view = None
        self.running = True
        self.k = 0
        self.k_anim = 0.0                      # animation phase of the spinning fans
        self._anim_t = 0.0
        self._last_frame = 0.0
        self._frame_cost = 0.0                 # how long a picture takes on this PC (s, smoothed)
        self.live = None                       # quick drawing of the live view (render.LiveFrames)
        self.summary = None
        self._pending = None
        self._quiet = False
        self._hold_until = 0.0
        self.jobs = queue.Queue()
        self.job = None
        self.job_tmp = None
        self.sel = None
        self.drag = None
        self.drag_probe = None
        self.bsel = None                       # selected block
        self.bdrag = None                      # a block being moved / resized with the mouse
        self.drag_start = None
        self.part_mode, self.part_old = None, None
        self.part_vars = {}
        self._pnames = {}
        self._tab_frames = []
        self._errors = 0
        self.job_log = []
        self.job_started = 0.0
        root.title(branding.WINDOW_TITLE)
        self._set_icon(root)
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        try:                                  # bigger text (display scaling) needs a bigger window
            grow = max(1.0, float(root.tk.call('tk', 'scaling')) / BASE_SCALING)
        except (tk.TclError, ValueError):
            grow = 1.0
        self._win_w = min(int(1560 * grow), sw - 40)
        root.geometry('%dx%d' % (self._win_w, min(int(980 * grow), sh - 80)))
        root.configure(bg=BG)
        root.report_callback_exception = self._tk_error
        style_dark(root)
        for cls in ('TCombobox', 'TSpinbox'):
            for seq in ('<MouseWheel>', '<Button-4>', '<Button-5>'):
                root.bind_class(cls, seq, lambda e: None)

        credit = ttk.Frame(root)
        credit.pack(side='bottom', fill='x', padx=12, pady=(0, 8))
        self.l_brand = self._link(credit, branding.POWERED_BY, branding.GITHUB_URL, style='Brand.TLabel')
        ttk.Label(credit, text='·', style='Sub.TLabel').pack(side='left', padx=8)
        self._link(credit, 'GitHub: ' + branding.GITHUB_TEXT, branding.GITHUB_URL)
        ttk.Label(credit, text='·', style='Sub.TLabel').pack(side='left', padx=8)
        self._link(credit, 'WhatsApp: ' + branding.WHATSAPP_TEXT, branding.WHATSAPP_URL)
        ttk.Button(credit, text='About', command=self.show_about).pack(side='right')
        ttk.Label(credit, text='%s %s' % (branding.APP_NAME, branding.VERSION), style='Sub.TLabel').pack(
            side='right', padx=10)
        bar = ttk.Frame(root)
        bar.pack(side='bottom', fill='x', padx=10, pady=(4, 6))
        main = ttk.Frame(root)
        main.pack(side='top', fill='both', expand=True, padx=10, pady=(10, 4))
        main.columnconfigure(0, weight=3)
        main.columnconfigure(1, weight=2)
        main.rowconfigure(0, weight=1)
        left = ttk.Frame(main)
        left.grid(row=0, column=0, sticky='nsew', padx=(0, 10))
        right = ttk.Frame(main)
        right.grid(row=0, column=1, sticky='nsew')

        # ---------------- live view
        self.warn = ttk.Label(left, text='', style='Warn.TLabel', wraplength=820, justify='left')
        self.warn.pack(side='top', fill='x')
        self.fig = Figure(figsize=(6.4, 5.6), dpi=100, facecolor=BG)
        self.ax = self.fig.add_axes([0.0, 0.07, 1.0, 0.93])
        cax = self.fig.add_axes([0.08, 0.03, 0.84, 0.018])
        cax.imshow(np.linspace(0, 1, 256)[None, :], aspect='auto', cmap=CMAP, extent=[VMIN, VMAX, 0, 1])
        cax.set_yticks([])
        cax.set_xticks([22, 27, 32, 37, 42])
        cax.set_xticklabels(['22 °C', '27', '32', '37', '42 °C'], color=SUB, fontsize=8)
        cax.tick_params(length=0, pad=2)
        for s_ in cax.spines.values():
            s_.set_visible(False)
        self.canvas = FigureCanvasTkAgg(self.fig, master=left)
        self.canvas.get_tk_widget().configure(bg=BG, highlightthickness=0)
        tiles = ttk.Frame(left)
        tiles.pack(side='bottom', fill='x', pady=(6, 0))
        hint = ttk.Label(left, text='Drag fans and blocks · drag a block\'s corner to resize it · double-click: new fan · '
                                    'wheel on a fan: speed · right-click: more', style='Sub.TLabel', justify='left')
        hint.pack(side='bottom', anchor='w', fill='x')
        hint.bind('<Configure>', lambda e: hint.configure(wraplength=max(200, e.width)))
        self.canvas.get_tk_widget().pack(side='top', fill='both', expand=True)
        self.canvas.mpl_connect('button_press_event', self.on_press)
        self.canvas.mpl_connect('motion_notify_event', self.on_motion)
        self.canvas.mpl_connect('button_release_event', self.on_release)
        self.canvas.mpl_connect('scroll_event', self.on_scroll)
        self.tile = {}
        self._tiles_box, self._tile_frames, self._tile_cols = tiles, [], 6
        tiles.bind('<Configure>', lambda e: self._flow_tiles())
        for k, (key, title) in enumerate((('cpu', 'CPU (estimate)'), ('gpu', 'GPU core (estimate)'),
                                          ('power', 'Power now'), ('flow', 'Airflow in / out'),
                                          ('press', 'Pressure inside'), ('heat', 'Heat leaves via'))):
            fr = ttk.Frame(tiles, style='Panel.TFrame', padding=(10, 6))
            fr.grid(row=0, column=k, sticky='nsew', padx=3)
            tiles.columnconfigure(k, weight=1)
            self._tile_frames.append(fr)
            ttk.Label(fr, text=title, style='PanelSub.TLabel').pack(anchor='w')
            big = ttk.Label(fr, text='-', style='Big.TLabel')
            big.pack(anchor='w')
            sub = ttk.Label(fr, text='', style='PanelSub.TLabel', justify='left')
            sub.pack(anchor='w')
            self.tile[key] = (big, sub)

        # ---------------- controls
        nb = ttk.Notebook(right)
        nb.pack(fill='both', expand=True)
        self.nb = nb
        self._tab_hardware(nb)
        self._tab_fans(nb)
        self._tab_blocks(nb)
        self._tab_case(nb)
        self._tab_parts(nb)
        self._tab_results(nb)
        self._main = main

        self.btn_play = ttk.Button(bar, text='Pause', command=self.toggle_run)
        self.btn_play.pack(side='left')
        ttk.Button(bar, text='Restart airflow', command=lambda: self.rebuild(keep=False)).pack(side='left', padx=6)
        ttk.Button(bar, text='Open setup…', command=self.open_cfg).pack(side='left', padx=(18, 0))
        ttk.Button(bar, text='Save setup…', command=self.save_cfg).pack(side='left', padx=6)
        ttk.Button(bar, text='Export picture…', command=lambda: self.export('png')).pack(side='left', padx=(18, 0))
        ttk.Button(bar, text='Export video…', style='Accent.TButton', command=lambda: self.export('video')).pack(side='left', padx=6)
        self.status = ttk.Label(bar, text='', style='Sub.TLabel', padding=(0, 0, 6, 0))
        self.status.pack(side='right')

        self.menu = tk.Menu(root, tearoff=0, bg=FIELD, fg=TXT, activebackground='#1d6fa5', activeforeground='white')
        self.menu.add_command(label='Reverse direction', command=self.reverse_fan)
        self.menu.add_command(label='Auto (follows the fan curve)', command=lambda: self.set_fan_speed(-1))
        self.menu.add_command(label='Full speed (100 %)', command=lambda: self.set_fan_speed(100))
        self.menu.add_command(label='Half speed (50 %)', command=lambda: self.set_fan_speed(50))
        self.menu.add_command(label='Stop (0 %)', command=lambda: self.set_fan_speed(0))
        self.menu.add_separator()
        self.menu.add_command(label='Duplicate', command=self.dup_fan)
        self.menu.add_command(label='Delete fan', command=self.del_fan)
        menu = dict(tearoff=0, bg=FIELD, fg=TXT, activebackground='#1d6fa5', activeforeground='white')
        self.bmenu = tk.Menu(root, **menu)                 # right-click on a block
        self.bmenu_kind = tk.Menu(self.bmenu, **menu)
        self.bmenu_air = tk.Menu(self.bmenu, **menu)
        self.v_bmenu_air = tk.StringVar()
        for air, text in hw.BLOCK_AIR.items():
            self.bmenu_air.add_radiobutton(label=text, value=air, variable=self.v_bmenu_air,
                                           command=lambda a=air: self.set_block_air(a))
        self.bmenu.add_command(label='Duplicate block', command=self.dup_block)
        self.bmenu.add_command(label='Turn 90°', command=self.turn_block)
        self.bmenu.add_cascade(label='Air through it', menu=self.bmenu_air)
        self.bmenu.add_cascade(label='Kind', menu=self.bmenu_kind)
        self.bmenu.add_separator()
        self.bmenu.add_command(label='Delete block', command=self.del_block)
        self.emenu = tk.Menu(root, **menu)                 # right-click on an empty spot
        self.emenu_kind = tk.Menu(self.emenu, **menu)
        self.emenu.add_command(label='Add a fan here', command=lambda: self.add_fan_at(*self._menu_xy))
        self.emenu.add_cascade(label='Add a block here', menu=self.emenu_kind)
        self._menu_xy = (0.0, 0.0)

        notes = list(notes) + list(getattr(self.cfg, 'notes', [])) + self._try(placement.resolve, self.cfg, default=[])
        self.load_widgets_from_cfg()
        self.rebuild(keep=False)
        self._fit_controls()
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.after(50, self.tick)
        if getattr(self.cfg, 'info', None):
            self.say(' · '.join(self.cfg.info), seconds=10)
        if notes:
            root.after(400, lambda: self.show_notes('Opened with changes', notes))

    # ================================================================ small helpers
    def say(self, text, seconds=7.0):
        """a message in the status line that stays for a few seconds"""
        self.status.configure(text=library.printable(text, 400))
        self._hold_until = time.time() + seconds

    def _flow_tiles(self):
        """the six read-outs in one row, or in two rows of three when the window is narrow"""
        frames = self._tile_frames
        if not frames:
            return
        need = sum(f.winfo_reqwidth() + 6 for f in frames)
        width = self._tiles_box.winfo_width()
        if self._tile_cols == 6:                # a little margin, so changing numbers never flip it
            cols = 3 if width < need else 6
        else:
            cols = 6 if width >= need + 16 else 3
        if cols == self._tile_cols:
            return
        self._tile_cols = cols
        for k, fr in enumerate(frames):
            fr.grid_configure(row=k // cols, column=k % cols, pady=(0, 6) if k // cols < len(frames) // cols - 1 else 0)
        for c in range(len(frames)):
            self._tiles_box.columnconfigure(c, weight=1 if c < cols else 0)

    def _fit_controls(self):
        """the controls on the right keep their full width (nothing cut off with bigger text);
        the picture on the left gives way instead"""
        try:
            self.root.update_idletasks()
            need = max([f.winfo_reqwidth() for f in self._tab_frames] + [0]) + 24   # + scroll bar, borders
            self._main.columnconfigure(1, minsize=min(need, int(0.55 * self._win_w)), weight=0)
            self._main.columnconfigure(0, weight=1)          # extra room goes to the picture
        except tk.TclError:
            log.info('could not measure the controls', exc_info=True)

    def _set_icon(self, root):
        try:
            ico = os.path.join(BUNDLE, 'assets', 'app.ico')
            png = os.path.join(BUNDLE, 'assets', 'app.png')
            if sys.platform.startswith('win') and os.path.exists(ico):
                root.iconbitmap(default=ico)
            elif os.path.exists(png):
                self._icon = tk.PhotoImage(file=png)
                root.iconphoto(True, self._icon)
        except tk.TclError:
            log.info('could not set the window icon', exc_info=True)

    def _link(self, parent, text, url, style='Link.TLabel'):
        lab = ttk.Label(parent, text=text, style=style, cursor='hand2')
        lab.pack(side='left')
        lab.bind('<Button-1>', lambda e: self.open_link(url))
        return lab

    def open_link(self, url):
        try:
            if not webbrowser.open(url):           # Windows reports a missing browser this way
                self.say('Could not open %s - no web browser found' % url, 12)
        except webbrowser.Error as e:
            self.say('Could not open %s (%s)' % (url, e), 12)

    def show_about(self):
        """the About window: who made the app and how to reach him"""
        old = getattr(self, '_about_win', None)
        if old is not None and old.winfo_exists():     # already open: bring it to the front
            old.deiconify()
            old.lift()
            return old
        win = tk.Toplevel(self.root)
        win.title('About %s' % branding.APP_NAME)
        win.configure(bg=PANEL)
        win.resizable(False, False)
        box = ttk.Frame(win, style='Panel.TFrame', padding=22)
        box.pack(fill='both', expand=True)
        png = os.path.join(BUNDLE, 'assets', 'app.png')
        if os.path.exists(png):
            try:
                self._about_img = tk.PhotoImage(file=png).subsample(2, 2)
                ttk.Label(box, image=self._about_img, style='Panel.TLabel').grid(row=0, column=0, rowspan=4,
                                                                                  padx=(0, 18), sticky='n')
            except tk.TclError:
                pass
        ttk.Label(box, text=branding.APP_NAME, style='Panel.TLabel', font=('Segoe UI', 16, 'bold')).grid(
            row=0, column=1, sticky='w')
        ttk.Label(box, text='Version %s · 2D airflow and heat simulation of a PC case' % branding.VERSION,
                  style='PanelSub.TLabel').grid(row=1, column=1, sticky='w')
        ttk.Label(box, text=branding.POWERED_BY, style='Panel.TLabel', font=('Segoe UI', 12, 'bold')).grid(
            row=2, column=1, sticky='w', pady=(14, 2))
        links = ttk.Frame(box, style='Panel.TFrame')
        links.grid(row=3, column=1, sticky='w')
        for r, (label, text, url) in enumerate((('GitHub', branding.GITHUB_TEXT, branding.GITHUB_URL),
                                                 ('WhatsApp', branding.WHATSAPP_TEXT, branding.WHATSAPP_URL))):
            ttk.Label(links, text=label, style='PanelSub.TLabel', width=10).grid(row=r, column=0, sticky='w', pady=2)
            lab = ttk.Label(links, text=text, style='PanelLink.TLabel', cursor='hand2')
            lab.grid(row=r, column=1, sticky='w', pady=2)
            lab.bind('<Button-1>', lambda e, u=url: self.open_link(u))
        ttk.Label(box, text='Temperatures are estimates from the simulated airflow - use the app to compare set-ups.',
                  style='PanelSub.TLabel', wraplength=400, justify='left', padding=(0, 0, 12, 0)).grid(
            row=4, column=0, columnspan=2, sticky='w', pady=(16, 10))
        ttk.Button(box, text='Close', command=win.destroy).grid(row=5, column=1, sticky='e')
        win.transient(self.root)
        win.update_idletasks()                         # open it over the middle of the main window
        x = self.root.winfo_rootx() + (self.root.winfo_width() - win.winfo_reqwidth()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - win.winfo_reqheight()) // 3
        win.geometry('+%d+%d' % (max(0, x), max(0, y)))
        self._about_win = win
        return win

    def show_notes(self, title, notes):
        """every note in a small window that can be scrolled (does not block the app)"""
        win = tk.Toplevel(self.root)
        win.title(title)
        win.configure(bg=BG)
        txt = tk.Text(win, bg=FIELD, fg=TXT, relief='flat', wrap='word', width=90, height=min(24, 3 + 2 * len(notes)),
                      font=('Segoe UI', 10), padx=10, pady=8)
        txt.insert('1.0', '\n'.join('• ' + library.printable(n, 2000) for n in notes))
        txt.configure(state='disabled')
        txt.pack(fill='both', expand=True, padx=10, pady=(10, 4))
        ttk.Button(win, text='OK', command=win.destroy).pack(pady=(0, 10))
        win.transient(self.root)
        self._notes_win = win
        return win

    def _tk_error(self, exc, value, tb):
        log.error('error in a window action', exc_info=(exc, value, tb))
        try:
            self.say('Something went wrong: %s (details in the log)' % value, seconds=12)
        except tk.TclError:
            pass

    def _try(self, fn, *args, default=None):
        """run a helper that builds a layout; a problem is shown and logged instead of breaking the app"""
        try:
            return fn(*args)
        except Exception as e:                   # noqa: BLE001 - any failure here must reach the user
            log.exception('%s failed', getattr(fn, '__name__', fn))
            self.say('Could not do that: %s' % e, seconds=12)
            return default

    def _num(self, var, default):
        try:
            raw = var.get()
        except (tk.TclError, ValueError, OverflowError):
            raw = self.root.globalgetvar(str(var))
        try:
            x = float(raw)
            if not math.isfinite(x):
                raise ValueError
        except (TypeError, ValueError, OverflowError):
            self.say('"%s" is not a number - kept %s' % (str(raw)[:20], fmt_num(default)))
            self._quiet, was = True, self._quiet
            try:
                var.set(default)
            finally:
                self._quiet = was
            return default
        return x

    # ================================================================ tabs
    def _scroll_tab(self, nb, title):
        outer = ttk.Frame(nb)
        nb.add(outer, text=title)
        cv = tk.Canvas(outer, bg=BG, highlightthickness=0, bd=0)
        sb = ttk.Scrollbar(outer, orient='vertical', command=cv.yview)
        inner = ttk.Frame(cv, padding=12)
        inner.columnconfigure(1, weight=1)
        win = cv.create_window((0, 0), window=inner, anchor='nw')
        self._tab_frames.append(inner)
        inner.bind('<Configure>', lambda e: cv.configure(scrollregion=cv.bbox('all')))
        cv.bind('<Configure>', lambda e: cv.itemconfigure(win, width=e.width))
        cv.configure(yscrollcommand=sb.set)
        cv.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')

        def wheel(e):
            delta = -1 if (getattr(e, 'delta', 0) > 0 or getattr(e, 'num', 0) == 4) else 1
            cv.yview_scroll(delta, 'units')
        inner.bind('<Enter>', lambda e: (cv.bind_all('<MouseWheel>', wheel), cv.bind_all('<Button-4>', wheel),
                                         cv.bind_all('<Button-5>', wheel)))
        inner.bind('<Leave>', lambda e: (cv.unbind_all('<MouseWheel>'), cv.unbind_all('<Button-4>'),
                                         cv.unbind_all('<Button-5>')))
        return inner

    def _tab_hardware(self, nb):
        f = self._scroll_tab(nb, 'Hardware')
        r = 0
        head(f, r, 'Processor and CPU cooler', top=0); r += 1
        self.v_cpu = tk.StringVar()
        self.cb_cpu = ttk.Combobox(f, textvariable=self.v_cpu, values=list(hw.CPUS), state='readonly', height=24)
        self.cb_cpu.bind('<<ComboboxSelected>>', lambda e: self.on_hw(cpu_changed=True))
        row(f, r, 'CPU', self.cb_cpu); r += 1
        self.l_cpu = ttk.Label(f, text='', style='Sub.TLabel')
        self.l_cpu.grid(row=r, column=1, columnspan=2, sticky='w'); r += 1
        self.v_cpu_w = NumVar()
        row(f, r, 'Own CPU watts', spinbox(f, self.v_cpu_w, 0, 400, 5, self.on_hw), '0 = from list'); r += 1
        self.v_cooler = tk.StringVar()
        self.cb_cooler = ttk.Combobox(f, textvariable=self.v_cooler, values=list(hw.COOLERS), state='readonly')
        self.cb_cooler.bind('<<ComboboxSelected>>', lambda e: self.on_hw(cooler_changed=True))
        row(f, r, 'CPU cooler', self.cb_cooler); r += 1
        self.v_cfan = tk.StringVar()
        self.cb_cfan = ttk.Combobox(f, textvariable=self.v_cfan, state='readonly')
        self.cb_cfan.bind('<<ComboboxSelected>>', lambda e: self.on_hw())
        row(f, r, 'Cooler fan model', self.cb_cfan); r += 1
        self.v_cfans = tk.StringVar()
        self.cb_cfans = ttk.Combobox(f, textvariable=self.v_cfans, state='readonly')
        self.cb_cfans.bind('<<ComboboxSelected>>', lambda e: self.on_hw())
        row(f, r, 'Fans on the cooler', self.cb_cfans); r += 1
        self.v_orient = tk.StringVar()
        self.cb_orient = ttk.Combobox(f, textvariable=self.v_orient, values=[ORIENT_TEXT[o] for o in COOLER_ORIENTATIONS],
                                      state='readonly')
        self.cb_orient.bind('<<ComboboxSelected>>', lambda e: self.on_hw())
        row(f, r, 'Tower direction', self.cb_orient); r += 1
        self.sc_cool = SpeedControl(f, self.on_hw, lambda: hw.ALL_FANS[self.cfg.cooler_fan_name()]['rpm'],
                                    on_error=self.say)
        row(f, r, 'Cooler fan speed', self.sc_cool.frame); r += 1
        fr = ttk.Frame(f)
        self.v_aio_mount = tk.StringVar()
        self.v_aio_dir = tk.StringVar()
        ttk.Label(fr, text='radiator on').pack(side='left')
        for val in ('top', 'front'):
            ttk.Radiobutton(fr, text=val, value=val, variable=self.v_aio_mount, command=self.on_hw).pack(side='left', padx=4)
        ttk.Label(fr, text='   fans blow').pack(side='left')
        for val in ('out', 'in'):
            ttk.Radiobutton(fr, text=val, value=val, variable=self.v_aio_dir, command=self.on_hw).pack(side='left', padx=4)
        row(f, r, 'AIO radiator', fr); r += 1

        head(f, r, 'Motherboard, memory and drives'); r += 1
        self.v_board = tk.StringVar()
        self.cb_board = ttk.Combobox(f, textvariable=self.v_board, values=list(hw.MOTHERBOARDS), state='readonly')
        self.cb_board.bind('<<ComboboxSelected>>', lambda e: self.on_hw())
        row(f, r, 'Motherboard', self.cb_board); r += 1
        self.l_board = ttk.Label(f, text='', style='Sub.TLabel', wraplength=480, justify='left')
        self.l_board.grid(row=r, column=1, columnspan=2, sticky='w'); r += 1
        fr = ttk.Frame(f)
        self.v_sticks = tk.StringVar()
        self.cb_sticks = ttk.Combobox(fr, textvariable=self.v_sticks, state='readonly', width=3)
        self.cb_sticks.bind('<<ComboboxSelected>>', lambda e: self.on_hw())
        self.cb_sticks.pack(side='left')
        ttk.Label(fr, text='sticks').pack(side='left', padx=(4, 14))
        self.v_ram_type = tk.StringVar()
        for t in hw.RAM_TYPES:
            ttk.Radiobutton(fr, text=t, value=t, variable=self.v_ram_type, command=self.on_hw).pack(side='left', padx=(0, 8))
        self.v_ecc = tk.BooleanVar()
        ttk.Checkbutton(fr, text='ECC', variable=self.v_ecc, command=self.on_hw).pack(side='left', padx=(8, 0))
        row(f, r, 'Memory (RAM)', fr); r += 1
        self.l_ram = ttk.Label(f, text='', style='Sub.TLabel', wraplength=480, justify='left')
        self.l_ram.grid(row=r, column=1, columnspan=2, sticky='w'); r += 1
        fr = ttk.Frame(f)
        self.v_nvme = tk.IntVar()
        spinbox(fr, self.v_nvme, 0, hw.MAX_NVME, 1, self.on_hw, width=3).pack(side='left')
        ttk.Label(fr, text='M.2 SSDs').pack(side='left', padx=(4, 16))
        self.v_hdd = tk.IntVar()
        spinbox(fr, self.v_hdd, 0, hw.MAX_HDD, 1, self.on_hw, width=3).pack(side='left')
        ttk.Label(fr, text='3.5" hard drives').pack(side='left', padx=(4, 0))
        row(f, r, 'Drives', fr); r += 1

        head(f, r, 'Graphics card'); r += 1
        self.v_gpu = tk.StringVar()
        self.cb_gpu = ttk.Combobox(f, textvariable=self.v_gpu, values=list(hw.GPUS), state='readonly', height=24)
        self.cb_gpu.bind('<<ComboboxSelected>>', lambda e: self.on_hw())
        row(f, r, 'GPU', self.cb_gpu); r += 1
        self.l_gpu = ttk.Label(f, text='', style='Sub.TLabel')
        self.l_gpu.grid(row=r, column=1, columnspan=2, sticky='w'); r += 1
        self.v_gpu_w = NumVar()
        row(f, r, 'Own GPU watts', spinbox(f, self.v_gpu_w, 0, 700, 5, self.on_hw), '0 = from list'); r += 1
        self.v_gpu_len = NumVar()
        row(f, r, 'Card length', spinbox(f, self.v_gpu_len, 0, 420, 5, self.on_hw), 'mm, 0 = typical'); r += 1
        self.sc_gpu = SpeedControl(f, self.on_hw, lambda: hw.GPU_FAN['rpm'], on_error=self.say)
        row(f, r, 'GPU fans', self.sc_gpu.frame); r += 1

        head(f, r, 'Load and room'); r += 1
        fr = ttk.Frame(f)
        self.v_load = tk.StringVar()
        for val, txt in (('idle', 'Idle / desktop'), ('gaming', 'Gaming'), ('max', 'Max stress')):
            ttk.Radiobutton(fr, text=txt, value=val, variable=self.v_load, command=self.on_hw).pack(side='left', padx=(0, 10))
        row(f, r, 'Load', fr); r += 1
        self.v_room = tk.DoubleVar()
        sc = ttk.Scale(f, from_=15, to=40, variable=self.v_room, command=lambda e: self.on_hw(slider=True))
        self.l_room = row(f, r, 'Room temperature', sc, ''); r += 1

        head(f, r, 'Power supply'); r += 1
        self.v_psu_w = tk.StringVar()
        cb = ttk.Combobox(f, textvariable=self.v_psu_w, values=[str(s) for s in hw.PSU_SIZES], width=8)
        cb.bind('<<ComboboxSelected>>', lambda e: self.on_hw())
        cb.bind('<Return>', lambda e: self.on_hw())
        row(f, r, 'PSU watts', cb); r += 1
        self.v_psu_rating = tk.StringVar()
        cb = ttk.Combobox(f, textvariable=self.v_psu_rating, values=list(hw.PSU_RATINGS), state='readonly')
        cb.bind('<<ComboboxSelected>>', lambda e: self.on_hw())
        row(f, r, 'Efficiency', cb); r += 1
        self.v_psu_mode = tk.StringVar()
        cb = ttk.Combobox(f, textvariable=self.v_psu_mode, values=list(PSU_FAN_MODES), state='readonly')
        cb.bind('<<ComboboxSelected>>', lambda e: self.on_hw())
        row(f, r, 'PSU fan', cb); r += 1
        self.sc_psu = SpeedControl(f, self.on_hw, lambda: hw.PSU_FAN['rpm'], on_error=self.say)
        row(f, r, 'PSU fan speed', self.sc_psu.frame); r += 1

        self.l_power = ttk.Label(f, text='', style='Panel.TLabel', justify='left', padding=10, wraplength=640)
        self.l_power.grid(row=r, column=0, columnspan=3, sticky='ew', pady=(12, 0)); r += 1

    def _tab_fans(self, nb):
        f = self._scroll_tab(nb, 'Fans')
        f.columnconfigure(0, weight=1)
        cols = ('n', 'wall', 'pos', 'size', 'dir', 'speed', 'rpm', 'cfm', 'out')
        heads = ('#', 'Where', 'Position', 'Size', 'Dir', 'Speed', 'rpm', 'CFM', 'Air')
        widths = (34, 70, 80, 50, 50, 74, 58, 58, 62)
        self.tree = ttk.Treeview(f, columns=cols, show='headings', height=9, selectmode='browse')
        for c, hd, w in zip(cols, heads, widths):
            self.tree.heading(c, text=hd)
            self.tree.column(c, width=w, anchor='center', stretch=(c == 'wall'))
        self.tree.grid(row=0, column=0, columnspan=3, sticky='nsew')
        self.tree.bind('<<TreeviewSelect>>', lambda e: self.on_select_fan())
        bt = ttk.Frame(f)
        bt.grid(row=1, column=0, columnspan=3, sticky='w', pady=6)
        ttk.Button(bt, text='+ Add fan', command=self.add_fan).pack(side='left')
        ttk.Button(bt, text='Duplicate', command=self.dup_fan).pack(side='left', padx=6)
        ttk.Button(bt, text='Remove', command=self.del_fan).pack(side='left')
        ttk.Button(bt, text='Fix overlaps', command=self.fix_overlaps).pack(side='left', padx=(14, 0))

        ed = ttk.Frame(f, style='Panel.TFrame', padding=12)
        ed.grid(row=2, column=0, columnspan=3, sticky='ew', pady=(4, 0))
        ed.columnconfigure(1, weight=1)
        self.l_edit = ttk.Label(ed, text='Selected fan', style='Panel.TLabel', font=('Segoe UI', 11, 'bold'))
        self.l_edit.grid(row=0, column=0, columnspan=4, sticky='w')
        self.v_wall = tk.StringVar()
        fr = ttk.Frame(ed, style='Panel.TFrame')
        for w in ('front', 'top', 'rear', 'bottom', 'side', 'inside'):
            ttk.Radiobutton(fr, text=w, value=w, variable=self.v_wall, command=self.on_fan_edit,
                            style='Panel.TRadiobutton').pack(side='left', padx=(0, 6))
        ttk.Label(ed, text='Where', style='Panel.TLabel').grid(row=1, column=0, sticky='w', pady=3)
        fr.grid(row=1, column=1, columnspan=3, sticky='w')
        self.v_pos = NumVar()
        self.s_pos = ttk.Scale(ed, from_=0, to=450, variable=self.v_pos, command=lambda e: self.on_fan_edit(slider=True))
        self.s_pos.bind('<ButtonRelease-1>', lambda e: self.on_fan_edit(snap=True))
        self.l_posname = ttk.Label(ed, text='Position', style='Panel.TLabel')
        self.l_posname.grid(row=2, column=0, sticky='w', pady=3)
        self.s_pos.grid(row=2, column=1, sticky='ew')
        self.sp_pos = spinbox(ed, self.v_pos, 0, 700, 5, lambda: self.on_fan_edit(snap=True), width=6)
        self.sp_pos.grid(row=2, column=2, padx=6)
        self.l_pos = ttk.Label(ed, text='', style='PanelSub.TLabel', width=16)
        self.l_pos.grid(row=2, column=3, sticky='w')
        self.v_pos2 = NumVar()
        self.s_pos2 = ttk.Scale(ed, from_=0, to=450, variable=self.v_pos2, command=lambda e: self.on_fan_edit(slider=True))
        self.s_pos2.bind('<ButtonRelease-1>', lambda e: self.on_fan_edit(snap=True))
        self.l_pos2name = ttk.Label(ed, text='Height', style='Panel.TLabel')
        self.l_pos2name.grid(row=3, column=0, sticky='w', pady=3)
        self.s_pos2.grid(row=3, column=1, sticky='ew')
        self.sp_pos2 = spinbox(ed, self.v_pos2, 0, 700, 5, lambda: self.on_fan_edit(snap=True), width=6)
        self.sp_pos2.grid(row=3, column=2, padx=6)
        self.l_pos2 = ttk.Label(ed, text='', style='PanelSub.TLabel', width=16)
        self.l_pos2.grid(row=3, column=3, sticky='w')
        self.v_dir = tk.StringVar()
        ttk.Label(ed, text='Direction', style='Panel.TLabel').grid(row=4, column=0, sticky='w', pady=3)
        self.fr_dir_wall = ttk.Frame(ed, style='Panel.TFrame')
        ttk.Radiobutton(self.fr_dir_wall, text='in (intake)', value='in', variable=self.v_dir, command=self.on_fan_edit,
                        style='Panel.TRadiobutton').pack(side='left', padx=(0, 12))
        ttk.Radiobutton(self.fr_dir_wall, text='out (exhaust)', value='out', variable=self.v_dir, command=self.on_fan_edit,
                        style='Panel.TRadiobutton').pack(side='left')
        self.fr_dir_in = ttk.Frame(ed, style='Panel.TFrame')
        for d, txt in (('up', 'blows up ↑'), ('down', 'down ↓'), ('left', 'to rear ←'), ('right', 'to front →')):
            ttk.Radiobutton(self.fr_dir_in, text=txt, value=d, variable=self.v_dir, command=self.on_fan_edit,
                            style='Panel.TRadiobutton').pack(side='left', padx=(0, 8))
        self.fr_dir_wall.grid(row=4, column=1, columnspan=3, sticky='w')
        self.fr_dir_in.grid(row=4, column=1, columnspan=3, sticky='w')
        self.v_model = tk.StringVar()
        self.cb_model = ttk.Combobox(ed, textvariable=self.v_model, values=list(hw.ALL_FANS), state='readonly')
        self.cb_model.bind('<<ComboboxSelected>>', lambda e: self.on_fan_edit())
        ttk.Label(ed, text='Fan model', style='Panel.TLabel').grid(row=5, column=0, sticky='w', pady=3)
        self.cb_model.grid(row=5, column=1, columnspan=3, sticky='ew')
        self.sc_fan = SpeedControl(ed, self.on_fan_edit, self._sel_max_rpm, with_auto=True, panel=True,
                                   on_error=self.say)
        ttk.Label(ed, text='Speed', style='Panel.TLabel').grid(row=6, column=0, sticky='w', pady=3)
        self.sc_fan.frame.grid(row=6, column=1, columnspan=3, sticky='ew')
        self.l_speed = ttk.Label(ed, text='', style='PanelSub.TLabel')
        self.l_speed.grid(row=7, column=1, columnspan=3, sticky='w')

        al = ttk.Frame(f)
        al.grid(row=3, column=0, columnspan=3, sticky='ew', pady=(10, 0))
        self.v_all = tk.DoubleVar(value=70)
        ttk.Label(al, text='All case fans').pack(side='left')
        ttk.Scale(al, from_=0, to=100, variable=self.v_all).pack(side='left', fill='x', expand=True, padx=8)
        self.l_all = ttk.Label(al, text='70 %', style='Sub.TLabel', width=6)
        self.l_all.pack(side='left')
        self.v_all.trace_add('write', lambda *a: self.l_all.configure(text='%.0f %%' % self.v_all.get()))
        ttk.Button(al, text='Set all', command=self.set_all_speed).pack(side='left')
        ttk.Button(al, text='All auto', command=lambda: self.set_all_speed(auto=True)).pack(side='left', padx=(6, 0))

        cf = ttk.Frame(f, style='Panel.TFrame', padding=12)
        cf.grid(row=4, column=0, columnspan=3, sticky='ew', pady=(10, 0))
        ttk.Label(cf, text='Fan curve for fans set to auto (like a motherboard fan header)', style='Panel.TLabel',
                  font=('Segoe UI', 10, 'bold')).grid(row=0, column=0, columnspan=8, sticky='w')
        ttk.Label(cf, text='follow', style='Panel.TLabel').grid(row=1, column=0, sticky='w', pady=4)
        self.v_csrc = tk.StringVar()
        cb = ttk.Combobox(cf, textvariable=self.v_csrc, values=[CURVE_TEXT[s] for s in FAN_CURVE_SOURCES],
                          state='readonly', width=24)
        cb.bind('<<ComboboxSelected>>', lambda e: self.on_curve())
        cb.grid(row=1, column=1, columnspan=7, sticky='w')
        self.v_tlo, self.v_plo, self.v_thi, self.v_phi = NumVar(), NumVar(), NumVar(), NumVar()
        items = (('at', None), (None, self.v_tlo), ('°C →', None), (None, self.v_plo), ('%    at', None),
                 (None, self.v_thi), ('°C →', None), (None, self.v_phi), ('%', None))
        c = 0
        for text, var in items:
            if var is None:
                ttk.Label(cf, text=text, style='Panel.TLabel').grid(row=2, column=c, sticky='w', padx=(0, 4))
            else:
                spinbox(cf, var, 0, 110, 5, self.on_curve, width=4).grid(row=2, column=c, sticky='w', padx=(0, 4))
            c += 1
        self.l_curve = ttk.Label(cf, text='', style='PanelSub.TLabel', wraplength=520, justify='left')
        self.l_curve.grid(row=3, column=0, columnspan=9, sticky='w', pady=(4, 0))

        pr = ttk.Frame(f)
        pr.grid(row=5, column=0, columnspan=3, sticky='ew', pady=(10, 0))
        ttk.Label(pr, text='Ready-made').pack(side='left')
        self.v_preset = tk.StringVar(value=list(PRESETS)[0])
        cb = ttk.Combobox(pr, textvariable=self.v_preset, values=list(PRESETS), state='readonly', width=40)
        cb.pack(side='left', padx=8, fill='x', expand=True)
        ttk.Button(pr, text='Load', command=self.load_preset).pack(side='left')
        ttk.Label(f, text='Where: front / top / rear = case panels · bottom = case floor (under the PSU shroud the fan sits '
                          'on the shroud and pulls air through the floor) · side = side-panel fan blowing through the '
                          'glass · inside = anywhere in the case, blowing up, down, to the rear or to the front.\n'
                          'Position = centre of the fan in mm: front/rear = height above the floor, everything else = '
                          'distance from the rear wall. New, duplicated and moved fans always go to a free spot.',
                  style='Sub.TLabel', wraplength=540, justify='left').grid(row=6, column=0, columnspan=3, sticky='w', pady=(12, 0))

    def _tab_blocks(self, nb):
        f = self._scroll_tab(nb, 'Blocks')
        f.columnconfigure(0, weight=1)
        ttk.Label(f, text='Things you place yourself anywhere in the case: a block or a panel that stops the air, '
                          'cables, a grille, or a part that makes heat (a pump, a capture card ...).',
                  style='Sub.TLabel', wraplength=540, justify='left').grid(row=0, column=0, columnspan=3, sticky='w',
                                                                           pady=(0, 6))
        cols = ('n', 'kind', 'size', 'pos', 'air', 'heat', 'temp')
        heads = ('#', 'Kind', 'Size', 'Centre', 'Air', 'Heat', 'Air at it')
        widths = (30, 150, 76, 76, 58, 50, 66)
        self.btree = ttk.Treeview(f, columns=cols, show='headings', height=7, selectmode='browse')
        for c, hd, w in zip(cols, heads, widths):
            self.btree.heading(c, text=hd)
            self.btree.column(c, width=w, anchor='w' if c == 'kind' else 'center', stretch=(c == 'kind'))
        self.btree.grid(row=1, column=0, columnspan=3, sticky='nsew')
        self.btree.bind('<<TreeviewSelect>>', lambda e: self.on_select_block())
        bt = ttk.Frame(f)
        bt.grid(row=2, column=0, columnspan=3, sticky='w', pady=(6, 0))
        self.v_bkind_new = tk.StringVar(value=hw.DEFAULT_BLOCK)
        self.cb_bkind_new = ttk.Combobox(bt, textvariable=self.v_bkind_new, values=list(hw.BLOCKS), state='readonly',
                                         width=28)
        self.cb_bkind_new.pack(side='left')
        ttk.Button(bt, text='+ Add block', command=self.add_block).pack(side='left', padx=6)
        bt = ttk.Frame(f)
        bt.grid(row=3, column=0, columnspan=3, sticky='w', pady=6)
        ttk.Button(bt, text='Duplicate', command=self.dup_block).pack(side='left')
        ttk.Button(bt, text='Remove', command=self.del_block).pack(side='left', padx=6)
        ttk.Button(bt, text='Fix overlaps', command=self.fix_overlaps).pack(side='left', padx=(8, 0))

        ed = ttk.Frame(f, style='Panel.TFrame', padding=12)
        ed.grid(row=4, column=0, columnspan=3, sticky='ew', pady=(4, 0))
        ed.columnconfigure(1, weight=1)
        self.l_bedit = ttk.Label(ed, text='Selected block', style='Panel.TLabel', font=('Segoe UI', 11, 'bold'))
        self.l_bedit.grid(row=0, column=0, columnspan=4, sticky='w')
        self.v_bkind = tk.StringVar()
        self.cb_bkind = ttk.Combobox(ed, textvariable=self.v_bkind, values=list(hw.BLOCKS), state='readonly')
        self.cb_bkind.bind('<<ComboboxSelected>>', lambda e: self.on_block_kind())
        ttk.Label(ed, text='Kind', style='Panel.TLabel').grid(row=1, column=0, sticky='w', pady=3)
        self.cb_bkind.grid(row=1, column=1, columnspan=3, sticky='ew')
        self.v_bx, self.v_by, self.v_bw, self.v_bh, self.v_bwatts = NumVar(), NumVar(), NumVar(), NumVar(), NumVar()
        self.s_bx = ttk.Scale(ed, from_=0, to=450, variable=self.v_bx, command=lambda e: self.on_block_edit(slider=True))
        self.s_bx.bind('<ButtonRelease-1>', lambda e: self.on_block_edit(snap=True))
        self.s_by = ttk.Scale(ed, from_=0, to=450, variable=self.v_by, command=lambda e: self.on_block_edit(slider=True))
        self.s_by.bind('<ButtonRelease-1>', lambda e: self.on_block_edit(snap=True))
        for r, (lab, sc, var, unit) in enumerate((('From rear', self.s_bx, self.v_bx, 'mm (centre)'),
                                                 ('Above floor', self.s_by, self.v_by, 'mm (centre)')), start=2):
            ttk.Label(ed, text=lab, style='Panel.TLabel').grid(row=r, column=0, sticky='w', pady=3)
            sc.grid(row=r, column=1, sticky='ew')
            spinbox(ed, var, 0, 700, 5, lambda: self.on_block_edit(snap=True), width=6).grid(row=r, column=2, padx=6)
            ttk.Label(ed, text=unit, style='PanelSub.TLabel').grid(row=r, column=3, sticky='w')
        fr = ttk.Frame(ed, style='Panel.TFrame')
        spinbox(fr, self.v_bw, hw.BLOCK_MIN_MM, hw.BLOCK_MAX_MM, 5, lambda: self.on_block_edit(snap=True),
                width=6).pack(side='left')
        ttk.Label(fr, text='×', style='Panel.TLabel').pack(side='left', padx=4)
        spinbox(fr, self.v_bh, hw.BLOCK_MIN_MM, hw.BLOCK_MAX_MM, 5, lambda: self.on_block_edit(snap=True),
                width=6).pack(side='left')
        ttk.Label(fr, text='mm', style='PanelSub.TLabel').pack(side='left', padx=(6, 12))
        ttk.Button(fr, text='Turn 90°', command=self.turn_block).pack(side='left')
        ttk.Label(ed, text='Size', style='Panel.TLabel').grid(row=4, column=0, sticky='w', pady=3)
        fr.grid(row=4, column=1, columnspan=3, sticky='w')
        self.v_bair = tk.StringVar()
        fr = ttk.Frame(ed, style='Panel.TFrame')
        for air in hw.BLOCK_AIR:
            ttk.Radiobutton(fr, text=AIR_SHORT[air], value=air, variable=self.v_bair, command=self.on_block_edit,
                            style='Panel.TRadiobutton').pack(side='left', padx=(0, 10))
        ttk.Label(ed, text='Air', style='Panel.TLabel').grid(row=5, column=0, sticky='w', pady=3)
        fr.grid(row=5, column=1, columnspan=3, sticky='w')
        fr = ttk.Frame(ed, style='Panel.TFrame')
        spinbox(fr, self.v_bwatts, 0, hw.MAX_BLOCK_WATTS, 5, self.on_block_edit, width=6).pack(side='left')
        ttk.Label(fr, text='W  (0 = no heat)', style='PanelSub.TLabel').pack(side='left', padx=(6, 0))
        ttk.Label(ed, text='Heat', style='Panel.TLabel').grid(row=6, column=0, sticky='w', pady=3)
        fr.grid(row=6, column=1, columnspan=3, sticky='w')
        self.l_binfo = ttk.Label(ed, text='', style='PanelSub.TLabel', wraplength=440, justify='left')
        self.l_binfo.grid(row=7, column=1, columnspan=3, sticky='w')
        ttk.Label(f, text='Air: solid = no air gets through (it fills the case width, like a panel) · dense = air '
                          'squeezes round it (a pump, a drive, a card) · cables = some air gets through · mesh = most '
                          'air gets through.\n'
                          'In the picture: drag a block to move it, drag the small triangle in its top-right corner to '
                          'resize it, right-click it for more, or right-click an empty spot to add one there. Blocks '
                          'never land on a fan or another part. Your own kinds of blocks: Parts tab → Blocks.',
                  style='Sub.TLabel', wraplength=540, justify='left').grid(row=5, column=0, columnspan=3, sticky='w',
                                                                           pady=(12, 0))
        self._block_widgets(None)

    def _tab_case(self, nb):
        f = self._scroll_tab(nb, 'Case')
        r = 0
        self.v_case = tk.StringVar()
        self.cb_case = ttk.Combobox(f, textvariable=self.v_case, values=list(hw.CASES), state='readonly')
        self.cb_case.bind('<<ComboboxSelected>>', lambda e: self.on_case_preset())
        row(f, r, 'Case size preset', self.cb_case); r += 1
        self.v_depth, self.v_height, self.v_width = NumVar(), NumVar(), NumVar()
        for var, lab, lo, hi in ((self.v_depth, 'Inside depth (front-rear)', 300, 700),
                                 (self.v_height, 'Inside height', 300, 700),
                                 (self.v_width, 'Width (glass to tray)', 150, 320)):
            row(f, r, lab, spinbox(f, var, lo, hi, 5, self.on_case), 'mm'); r += 1
        self.v_shroud = tk.BooleanVar()
        ttk.Checkbutton(f, text='PSU shroud along the floor', variable=self.v_shroud, command=self.on_case).grid(
            row=r, column=0, columnspan=3, sticky='w', pady=(8, 2)); r += 1
        self.v_sh_h, self.v_sh_l = NumVar(), NumVar()
        for var, lab, lo, hi in ((self.v_sh_h, 'Shroud height', 80, 130), (self.v_sh_l, 'Shroud length', 170, 660)):
            row(f, r, lab, spinbox(f, var, lo, hi, 5, self.on_case), 'mm'); r += 1
        self.v_front, self.v_top = tk.StringVar(), tk.StringVar()
        cb = ttk.Combobox(f, textvariable=self.v_front, values=list(hw.FRONT_PANELS), state='readonly')
        cb.bind('<<ComboboxSelected>>', lambda e: self.on_case())
        row(f, r, 'Front panel', cb); r += 1
        cb = ttk.Combobox(f, textvariable=self.v_top, values=list(hw.TOP_PANELS), state='readonly')
        cb.bind('<<ComboboxSelected>>', lambda e: self.on_case())
        row(f, r, 'Top panel', cb); r += 1
        self.v_filter = tk.StringVar()
        cb = ttk.Combobox(f, textvariable=self.v_filter, values=list(hw.FILTER_CONDITIONS), state='readonly', width=10)
        cb.bind('<<ComboboxSelected>>', lambda e: self.on_case())
        row(f, r, 'Dust filters', cb, ''); r += 1
        self.v_alt = NumVar()
        row(f, r, 'Altitude', spinbox(f, self.v_alt, -500, 5000, 100, self.on_case), 'm above sea level'); r += 1
        self.v_quality = tk.StringVar()
        cb = ttk.Combobox(f, textvariable=self.v_quality, values=list(QUALITY_MM), state='readonly', width=10)
        cb.bind('<<ComboboxSelected>>', lambda e: self.on_case())
        row(f, r, 'Simulation detail', cb, ''); r += 1
        self.v_vq = tk.StringVar(value='high')
        cb = ttk.Combobox(f, textvariable=self.v_vq, values=list(QUALITY_MM), state='readonly', width=10)
        row(f, r, 'Video / picture detail', cb, ''); r += 1
        ttk.Label(f, text='Dust filters: the filter part of the front, top and floor panels gets 1.6× (dusty) or 3× '
                          '(clogged) harder to breathe through. Altitude: higher up the air is thinner - fans move the '
                          'same volume of air but it carries less heat (1000 m ≈ 11 % thinner air).\n'
                          'Detail = size of the simulation cells: fast 4 mm (smoothest live view), normal 3 mm, '
                          'high 2 mm (sharpest, slower). Videos and pictures are made in the background with '
                          '"Video / picture detail".', style='Sub.TLabel', wraplength=520, justify='left').grid(
            row=r, column=0, columnspan=3, sticky='w', pady=(6, 0))

    def _tab_parts(self, nb):
        f = self._scroll_tab(nb, 'Parts')
        r = 0
        head(f, r, 'Your own parts', top=0); r += 1
        ttk.Label(f, text='Add a fan, graphics card, processor, CPU cooler, motherboard or case that is not in the lists. '
                          'The values are checked, saved on this PC, shown in every list of the app, and stored inside '
                          'the setups that use them (so a setup opens on another PC too).',
                  style='Sub.TLabel', wraplength=540, justify='left').grid(row=r, column=0, columnspan=3, sticky='w',
                                                                           pady=(2, 8)); r += 1
        self.v_pcat = tk.StringVar(value=library.CATEGORIES['gpu'])
        cb = ttk.Combobox(f, textvariable=self.v_pcat, values=list(library.CATEGORIES.values()), state='readonly',
                          width=18)
        cb.bind('<<ComboboxSelected>>', lambda e: self.parts_select_category(self._pcat()))
        row(f, r, 'Part type', cb); r += 1
        self.ptree = ttk.Treeview(f, columns=('name', 'spec', 'own'), show='headings', height=9, selectmode='browse')
        for c, hd, w in (('name', 'Name', 230), ('spec', 'Specs', 270), ('own', 'Yours', 50)):
            self.ptree.heading(c, text=hd)
            self.ptree.column(c, width=w, anchor='center' if c == 'own' else 'w', stretch=(c != 'own'))
        self.ptree.grid(row=r, column=0, columnspan=3, sticky='ew'); r += 1
        self.ptree.bind('<<TreeviewSelect>>', lambda e: self._parts_buttons())
        self.ptree.bind('<Double-1>', lambda e: self.parts_edit() if self._sel_part_is_custom() else self.parts_copy())
        bt = ttk.Frame(f)
        bt.grid(row=r, column=0, columnspan=3, sticky='w', pady=6); r += 1
        ttk.Button(bt, text='+ New', width=6, command=self.parts_new).pack(side='left')
        ttk.Button(bt, text='Copy as new', command=self.parts_copy).pack(side='left', padx=6)
        self.b_pedit = ttk.Button(bt, text='Edit', width=6, command=self.parts_edit)
        self.b_pedit.pack(side='left')
        self.b_pdel = ttk.Button(bt, text='Delete', width=7, command=self.parts_delete)
        self.b_pdel.pack(side='left', padx=6)
        ttk.Button(bt, text='Use in this setup', style='Accent.TButton', command=self.parts_use).pack(side='left',
                                                                                                    padx=(10, 0))
        self.ped = ttk.Frame(f, style='Panel.TFrame', padding=12)
        self.ped.grid(row=r, column=0, columnspan=3, sticky='ew'); r += 1
        self.ped.columnconfigure(1, weight=1)
        self.ped.grid_remove()
        self.part_name = tk.StringVar()
        self.l_part_err = ttk.Label(f, text='', style='Warn.TLabel', wraplength=540, justify='left')
        self.l_part_err.grid(row=r, column=0, columnspan=3, sticky='w', pady=(4, 0)); r += 1
        pf = ttk.Frame(f)
        pf.grid(row=r, column=0, columnspan=3, sticky='ew', pady=(10, 0)); r += 1
        self.l_ppath = ttk.Label(pf, text='Saved in: %s' % library.parts_path(), style='Sub.TLabel', wraplength=420,
                                 justify='left')
        self.l_ppath.pack(side='left')
        ttk.Button(pf, text='Open folder', command=self.parts_open_folder).pack(side='right')
        self.parts_select_category('gpu')

    def _tab_results(self, nb):
        f = ttk.Frame(nb, padding=8)
        nb.add(f, text='Results')
        self.tab_results = f
        self.txt = tk.Text(f, bg=FIELD, fg=TXT, insertbackground=TXT, font=('Consolas', 9), relief='flat', wrap='none')
        self.txt.pack(fill='both', expand=True)
        nb.bind('<<NotebookTabChanged>>', lambda e: self.update_report() if self._results_shown() else None, add='+')

    def _results_shown(self):
        try:
            return self.nb.select() == str(self.tab_results)
        except tk.TclError:
            return False

    def update_report(self):
        """the full text report (only made while the Results tab is open: it is not needed otherwise)"""
        if self.sim is None or self.sim.disp is None:
            return
        self.txt.delete('1.0', 'end')
        self.txt.insert('1.0', text_report(self.sim))

    # ================================================================ config <-> widgets
    def load_widgets_from_cfg(self, keep_sel=False):
        c = self.cfg
        ld = compute_loads(c)
        self._quiet = True
        self.v_cpu.set(c.cpu)
        self.v_cpu_w.set(c.cpu_power_w)
        self.v_cooler.set(c.cooler)
        self._cooler_lists()
        self.v_orient.set(ORIENT_TEXT[c.cooler_orientation])
        self.sc_cool.set(c.cooler_fan_pct, c.cooler_fan_pct < 0, 100 * ld['f_cooler'])
        self.v_aio_mount.set(c.aio_mount)
        self.v_aio_dir.set(c.aio_direction)
        self.v_board.set(c.motherboard)
        self._ram_lists()
        self.v_ram_type.set(c.ram_type)
        self.v_ecc.set(c.ram_ecc)
        self.v_nvme.set(c.nvme_count)
        self.v_hdd.set(c.hdd_count)
        self.v_gpu.set(c.gpu)
        self.v_gpu_w.set(c.gpu_power_w)
        self.v_gpu_len.set(c.gpu_length_mm)
        self.sc_gpu.set(c.gpu_fan_pct, c.gpu_fan_pct < 0, 100 * ld['f_gpu'])
        self.v_load.set(c.load)
        self.v_room.set(c.room_c)
        self.v_psu_w.set(str(c.psu_watts))
        self.v_psu_rating.set(c.psu_rating)
        self.v_psu_mode.set(c.psu_fan_mode)
        self.sc_psu.set(c.psu_fan_pct, c.psu_fan_pct < 0, 100 * ld['f_psu'])
        cs = c.case
        self.v_case.set(cs.name)
        self.v_depth.set(cs.depth_mm)
        self.v_height.set(cs.height_mm)
        self.v_width.set(cs.width_mm)
        self.v_shroud.set(cs.shroud)
        self.v_sh_h.set(cs.shroud_height_mm)
        self.v_sh_l.set(cs.shroud_length_mm)
        self.v_front.set(cs.front_panel)
        self.v_top.set(cs.top_panel)
        self.v_filter.set(c.filter_condition)
        self.v_alt.set(c.altitude_m)
        self.v_quality.set(c.quality)
        self._curve_widgets()
        self._quiet = False
        self.refresh_tree()
        if self.cfg.fans:
            k = self.sel if (keep_sel and self.sel is not None and self.sel < len(self.cfg.fans)) else 0
            self.select_fan(k)
        self.refresh_btree()
        if self.cfg.blocks:
            k = self.bsel if (keep_sel and self.bsel is not None and self.bsel < len(self.cfg.blocks)) else 0
            self.select_block(k)
        else:
            self.bsel = None
            self._block_widgets(None)
        self.update_info()

    def _curve_widgets(self):
        cv = self.cfg.fan_curve
        self.v_csrc.set(CURVE_TEXT[cv['source']])
        self.v_tlo.set(cv['t_lo'])
        self.v_plo.set(cv['pct_lo'])
        self.v_thi.set(cv['t_hi'])
        self.v_phi.set(cv['pct_hi'])

    def _cooler_lists(self):
        c = self.cfg
        cool = hw.COOLERS[c.cooler]
        if cool['kind'] == 'aio':
            names = hw.fans_of_size(cool['fan_mm'])
            self.cb_cfans.configure(values=['%d fans (radiator)' % cool['fans']], state='disabled')
            self.v_cfans.set('%d fans (radiator)' % cool['fans'])
            self.cb_orient.configure(state='disabled')
        else:
            names = list(hw.ALL_FANS)
            counts = [1, 2] if cool['stacks'] == 1 else [1, 2, 3]
            self.cb_cfans.configure(values=[FAN_COUNT_TEXT[n] for n in counts], state='readonly')
            self.v_cfans.set(FAN_COUNT_TEXT[c.n_cooler_fans()])
            self.cb_orient.configure(state='readonly')
        self.cb_cfan.configure(values=[STOCK] + names)
        self.v_cfan.set(c.cooler_fan_model if c.cooler_fan_model in names else STOCK)

    def _ram_lists(self):
        c = self.cfg
        allowed = [str(n) for n in RAM_STICKS if n <= c.ram_slots()]
        self.cb_sticks.configure(values=allowed)
        self.v_sticks.set(str(c.ram_sticks))

    def on_hw(self, slider=False, cooler_changed=False, cpu_changed=False):
        if self._quiet:
            return
        c = self.cfg
        c.cpu = self.v_cpu.get()
        c.cpu_power_w = max(0.0, self._num(self.v_cpu_w, c.cpu_power_w))
        if cooler_changed:
            c.cooler = self.v_cooler.get()
            c.cooler_fan_model, c.cooler_fans = '', 0
            self._quiet = True
            self._cooler_lists()
            self._quiet = False
        else:
            m = self.v_cfan.get()
            c.cooler_fan_model = '' if m == STOCK else m
            txt = self.v_cfans.get()
            c.cooler_fans = next((n for n, t in FAN_COUNT_TEXT.items() if t == txt), 0)
        c.cooler_orientation = next((o for o, t in ORIENT_TEXT.items() if t == self.v_orient.get()), 'to rear')
        c.cooler_fan_pct = self.sc_cool.value()
        c.aio_mount = self.v_aio_mount.get()
        c.aio_direction = self.v_aio_dir.get()
        c.motherboard = self.v_board.get()
        try:
            c.ram_sticks = int(self.v_sticks.get())
        except ValueError:
            pass
        c.ram_type = self.v_ram_type.get()
        c.ram_ecc = bool(self.v_ecc.get())
        c.nvme_count = int(round(self._num(self.v_nvme, c.nvme_count)))
        c.hdd_count = int(round(self._num(self.v_hdd, c.hdd_count)))
        if cpu_changed and c.cpu in hw.CPUS:
            mem = hw.CPUS[c.cpu].get('memory', 'DDR4/DDR5').split('/')
            if c.ram_type not in mem:
                c.ram_type = mem[-1]
                self.say('%s uses %s memory - RAM switched to %s' % (c.cpu, ' or '.join(mem), c.ram_type))
        c.gpu = self.v_gpu.get()
        c.gpu_power_w = max(0.0, self._num(self.v_gpu_w, c.gpu_power_w))
        c.gpu_length_mm = max(0.0, self._num(self.v_gpu_len, c.gpu_length_mm))
        c.gpu_fan_pct = self.sc_gpu.value()
        c.load = self.v_load.get()
        c.room_c = round(self.v_room.get(), 1)
        try:
            c.psu_watts = int(float(self.v_psu_w.get()))
        except (ValueError, OverflowError):
            self.say('"%s" is not a number of watts - kept %d W' % (self.v_psu_w.get()[:20], c.psu_watts))
        c.psu_rating = self.v_psu_rating.get()
        c.psu_fan_mode = self.v_psu_mode.get()
        c.psu_fan_pct = self.sc_psu.value()
        fixed = c.validate()
        moved = self._resolve_after_change()
        if fixed:
            self.say(' · '.join(fixed[:3] + (moved or [])), seconds=12)
            self.load_widgets_from_cfg(keep_sel=True)
        else:
            self._quiet = True
            self._ram_lists()
            self.v_ram_type.set(c.ram_type)
            self.v_nvme.set(c.nvme_count)
            self.v_hdd.set(c.hdd_count)
            self.v_psu_w.set(str(c.psu_watts))
            self._quiet = False
        ld = compute_loads(c)
        for sc_, key in ((self.sc_cool, 'f_cooler'), (self.sc_gpu, 'f_gpu'), (self.sc_psu, 'f_psu')):
            if sc_.v_auto.get():                 # show what "auto" chose
                sc_.set(-1, True, 100 * ld[key])
            else:
                sc_.refresh()
        self.update_info()
        self.schedule_rebuild(120 if slider else 60)    # speed-only changes rebuild in a few ms now

    def on_case_preset(self):
        name = self.v_case.get()
        if name not in hw.CASES:
            return
        self.cfg.apply_case_preset(name)
        cs = self.cfg.case
        self._quiet = True
        self.v_depth.set(cs.depth_mm)
        self.v_height.set(cs.height_mm)
        self.v_width.set(cs.width_mm)
        self.v_shroud.set(cs.shroud)
        self.v_sh_h.set(cs.shroud_height_mm)
        self.v_sh_l.set(cs.shroud_length_mm)
        self._quiet = False
        self.on_case()

    def on_case(self):
        if self._quiet:
            return
        cs = self.cfg.case
        cs.depth_mm = self._num(self.v_depth, cs.depth_mm)
        cs.height_mm = self._num(self.v_height, cs.height_mm)
        cs.width_mm = self._num(self.v_width, cs.width_mm)
        cs.shroud = bool(self.v_shroud.get())
        cs.shroud_height_mm = self._num(self.v_sh_h, cs.shroud_height_mm)
        cs.shroud_length_mm = self._num(self.v_sh_l, cs.shroud_length_mm)
        cs.front_panel = self.v_front.get()
        cs.top_panel = self.v_top.get()
        self.cfg.filter_condition = self.v_filter.get()
        self.cfg.altitude_m = self._num(self.v_alt, self.cfg.altitude_m)
        self.cfg.quality = self.v_quality.get()
        fixed = self.cfg.validate()
        moved = self._resolve_after_change()
        if fixed:
            self.say(' · '.join(fixed[:3] + (moved or [])), seconds=12)
            self.load_widgets_from_cfg(keep_sel=True)
        self.update_info()
        self.schedule_rebuild(300)

    def on_curve(self):
        if self._quiet:
            return
        src = next((s for s, t in CURVE_TEXT.items() if t == self.v_csrc.get()), 'hottest')
        cv = self.cfg.fan_curve
        self.cfg.fan_curve = dict(source=src, t_lo=self._num(self.v_tlo, cv['t_lo']),
                                  pct_lo=self._num(self.v_plo, cv['pct_lo']), t_hi=self._num(self.v_thi, cv['t_hi']),
                                  pct_hi=self._num(self.v_phi, cv['pct_hi']))
        notes = self.cfg.validate()
        self._quiet = True
        self._curve_widgets()
        self._quiet = False
        if notes:
            self.say(notes[0])
        self.update_info()           # the running simulation reads the curve directly: no restart needed

    def update_info(self):
        c = self.cfg
        cpu, gpu = hw.CPUS[c.cpu], hw.GPUS[c.gpu]
        self.l_cpu.configure(text='box TDP %d W · can draw up to %d W · gaming ≈ %d W · idle ≈ %d W · %s' % (
            cpu['tdp'], cpu['max_w'], cpu['gaming_w'], cpu['idle_w'], cpu.get('memory', 'DDR4/DDR5')))
        self.l_gpu.configure(text='max board power %d W · gaming ≈ %.0f W · idle ≈ %.0f W · %d mm, %.1f slot, %d fans' % (
            gpu['tbp'], hw.GPU_GAMING_FRACTION * gpu['tbp'], hw.gpu_idle_w(gpu['tbp']), gpu['length'], gpu['slots'],
            gpu['fans']))
        mb = hw.MOTHERBOARDS[c.motherboard]
        form = hw.BOARD_FORMS[mb['form']]
        self.l_board.configure(text='%s board %.0f × %.0f mm · %d RAM slots · chipset %.0f W · CPU power stage %.0f %% '
                                    'efficient%s' % (mb['form'], form['h'], form['w'], form['ram_slots'],
                                                     mb['chipset_w'], 100 * mb['vrm_eff'],
                                                     ' · ECC with Intel Core CPUs' if mb['ecc'] else ''))
        ld = compute_loads(c)
        notes = [w for w in ld['warnings'] if 'DDR' in w or 'ECC' in w]
        self.l_ram.configure(text='%d × %s%s ≈ %.1f W now · drives %.1f W%s' % (
            c.ram_sticks, c.ram_type, ' ECC' if c.ram_ecc else '', ld['p_ram'], ld['p_storage'],
            ('\n⚠ ' + '\n⚠ '.join(notes)) if notes else ''))
        ok = 'OK' if ld['psu_recommended'] <= c.psu_watts else 'too small'
        cf = hw.ALL_FANS[c.cooler_fan_name()]
        self.l_power.configure(text=(
            'Now (%s): CPU %.0f W + GPU %.0f W + rest of the PC %.0f W = %.0f W\n'
            '   rest = board %.0f W (chipset %.0f + CPU power stage %.0f + %.0f) · RAM %.1f W · drives %.1f W · '
            'fans %.1f W · USB %.0f W%s\n'
            'From the wall ≈ %.0f W · PSU %d W at %.0f %% load, %.0f %% efficient, %.0f W heat\n'
            'Maximum possible %.0f W → recommended PSU ≥ %d W · yours %d W (%s)\n'
            'Fan speeds: cooler %.0f %% = %.0f rpm · GPU %.0f %% = %.0f rpm · PSU %.0f %% = %.0f rpm' % (
                c.load, ld['p_cpu'], ld['p_gpu'], ld['p_other'], ld['p_dc'], ld['p_board'], ld['p_chipset'],
                ld['p_vrm'], hw.BOARD_MISC_W, ld['p_ram'], ld['p_storage'], ld['p_fans'], ld['p_usb'],
                (' · your blocks %.0f W' % ld['p_blocks']) if ld['p_blocks'] else '',
                ld['p_wall'], c.psu_watts, 100 * ld['psu_frac'], 100 * ld['eta'], ld['p_psu'], ld['p_dc_max'],
                ld['psu_recommended'], c.psu_watts, ok, 100 * ld['f_cooler'], ld['f_cooler'] * cf['rpm'],
                100 * ld['f_gpu'], ld['f_gpu'] * hw.GPU_FAN['rpm'], 100 * ld['f_psu'], ld['f_psu'] * hw.PSU_FAN['rpm'])))
        self.l_room.configure(text='%.0f °C' % c.room_c)
        n_auto = sum(1 for fan in c.fans if fan.auto)
        self.l_curve.configure(text='%d fan%s on auto · start speed ≈ %.0f %% (they then follow the live temperature)'
                               % (n_auto, '' if n_auto == 1 else 's', 100 * ld['f_auto']) if n_auto else
                               'No fan is on auto - tick "auto" in a fan\'s speed, or press "All auto".')

    # ================================================================ fans tab
    def _pos_text(self, fan):
        if fan.wall in ('side', 'inside'):
            return '%.0f, %.0f' % (fan.pos_mm, fan.pos2_mm)
        return '%.0f' % fan.pos_mm

    def refresh_tree(self):
        sel = self.sel
        self.tree.delete(*self.tree.get_children())
        for k, fan in enumerate(self.cfg.fans):
            self.tree.insert('', 'end', iid=str(k), values=(
                k + 1, fan.wall, self._pos_text(fan), fan.size, fan.direction,
                'auto' if fan.auto else '%.0f %%' % fan.speed_pct, '' if fan.auto else '%.0f' % fan.rpm, '', ''))
        if sel is not None and sel < len(self.cfg.fans):
            self.tree.selection_set(str(sel))

    def update_tree_live(self):
        if self.summary is None:
            return
        live = {f['label']: f for f in self.summary['fans']}
        left_out = {r['index'] for r in self.view.L.draw['rejected']} if self.view is not None else set()
        for k, fan in enumerate(self.cfg.fans):
            if not self.tree.exists(str(k)):
                continue
            lv = live.get('Fan %d' % (k + 1))
            vals = list(self.tree.item(str(k), 'values'))
            vals[7] = ('%.0f' % lv['cfm']) if lv else ('left out' if k in left_out else 'off')
            vals[8] = ('%.0f °C' % lv['t_out']) if lv and (fan.direction == 'out' or fan.wall == 'inside') else ''
            if fan.auto and lv:
                vals[5] = 'auto %.0f %%' % (100.0 * lv['rpm'] / fan.max_rpm)
                vals[6] = '%.0f' % lv['rpm']
            self.tree.item(str(k), values=vals)

    def on_select_fan(self):
        s = self.tree.selection()
        if s and int(s[0]) != self.sel:
            self.select_fan(int(s[0]), from_tree=True)

    def _sel_max_rpm(self):
        if self.sel is None or self.sel >= len(self.cfg.fans):
            return hw.ALL_FANS[hw.DEFAULT_CASE_FAN]['rpm']
        return self.cfg.fans[self.sel].max_rpm

    def _live_pct(self, k):
        """speed an auto fan is running at right now (or its start speed)"""
        fan = self.cfg.fans[k]
        if self.summary is not None:
            lv = next((f for f in self.summary['fans'] if f['label'] == 'Fan %d' % (k + 1)), None)
            if lv is not None and fan.max_rpm > 0:
                return 100.0 * lv['rpm'] / fan.max_rpm
        return 100.0 * compute_loads(self.cfg)['f_auto']

    def select_fan(self, k, from_tree=False):
        if k is None or k >= len(self.cfg.fans):
            return
        self.sel = k
        fan = self.cfg.fans[k]
        self._quiet = True
        self.v_wall.set(fan.wall)
        self._pos_range(fan)
        self.v_pos.set(fan.pos_mm)
        self.v_pos2.set(fan.pos2_mm)
        self.v_dir.set(fan.direction)
        self.v_model.set(fan.model)
        self.sc_fan.set(fan.speed_pct, fan.auto, self._live_pct(k) if fan.auto else None)
        self._quiet = False
        self._edit_labels(fan)
        self.l_edit.configure(text='Fan %d' % (k + 1))
        if not from_tree and self.tree.exists(str(k)):
            self.tree.selection_set(str(k))
            self.tree.see(str(k))

    def _pos_range(self, fan):
        cs = self.cfg.case
        s = fan.size
        if fan.wall in ('front', 'rear'):
            self.s_pos.configure(from_=s / 2, to=cs.height_mm - s / 2)
            self.l_posname.configure(text='Height')
        else:
            self.s_pos.configure(from_=s / 2 if fan.wall != 'inside' else 13, to=cs.depth_mm - (s / 2 if fan.wall != 'inside' else 13))
            self.l_posname.configure(text='From rear')
        self.s_pos2.configure(from_=13 if fan.wall == 'inside' else s / 2, to=cs.height_mm - 13)
        two = fan.wall in ('side', 'inside')
        self.l_pos2name.configure(text='Height' if two else '(side / inside)')
        self.s_pos2.state(['!disabled'] if two else ['disabled'])
        self.sp_pos2.state(['!disabled'] if two else ['disabled'])
        if fan.wall == 'inside':
            self.fr_dir_wall.grid_remove()
            self.fr_dir_in.grid()
        else:
            self.fr_dir_in.grid_remove()
            self.fr_dir_wall.grid()

    def _edit_labels(self, fan):
        what = {'front': 'mm above floor', 'rear': 'mm above floor', 'top': 'mm from rear', 'bottom': 'mm from rear',
                'side': 'mm from rear', 'inside': 'mm from rear'}[fan.wall]
        self.l_pos.configure(text=what)
        self.l_pos2.configure(text='mm above floor' if fan.wall in ('side', 'inside') else '')
        spec = hw.ALL_FANS[fan.model]
        if fan.auto:
            self.l_speed.configure(text='max %d rpm · auto: follows the fan curve below (%.0f CFM / %.2f mmH₂O at full '
                                        'speed)' % (spec['rpm'], spec['cfm'], spec['mmh2o']))
            return
        f = fan.speed_pct / 100
        self.l_speed.configure(text='max %d rpm · at %.0f %%: %.0f rpm, %.0f CFM / %.2f mmH₂O in free air' % (
            spec['rpm'], fan.speed_pct, fan.rpm, spec['cfm'] * f, spec['mmh2o'] * f * f))

    def on_fan_edit(self, slider=False, snap=False):
        if self._quiet or self.sel is None or self.sel >= len(self.cfg.fans):
            return
        k = self.sel
        fan = self.cfg.fans[k]
        wall = self.v_wall.get()
        if wall != fan.wall:
            self._change_wall(k, wall)
            return
        before = (fan.pos_mm, fan.pos2_mm, fan.model)
        if self.v_model.get() != fan.model and self.v_model.get() in hw.ALL_FANS:
            fan.model = self.v_model.get()
            self._pos_range(fan)
            snap = True                       # a bigger fan may now touch its neighbour
        fan.pos_mm = round(self._num(self.v_pos, fan.pos_mm))
        fan.pos2_mm = round(self._num(self.v_pos2, fan.pos2_mm))
        d = self.v_dir.get()
        if (wall == 'inside') == (d in INSIDE_DIRS):
            fan.direction = d
        fan.speed_pct = self.sc_fan.value()
        if fan.auto:
            self.sc_fan.set(-1, True, self._live_pct(k))
        else:
            self.sc_fan.refresh()
        if snap:
            ok, note = self._try(placement.snap, self.cfg, k, default=(True, ''))
            if not ok:                        # no free spot: the fan stays where it was
                fan.pos_mm, fan.pos2_mm, fan.model = before
                self._pos_range(fan)
                note += ' - Fan %d stays where it was' % (k + 1)
            if note:
                self.say(note)
            self._quiet = True
            self.v_pos.set(fan.pos_mm)
            self.v_pos2.set(fan.pos2_mm)
            self.v_model.set(fan.model)
            self._quiet = False
        self._edit_labels(fan)
        self.refresh_tree()
        self.update_info()
        self.schedule_rebuild(120 if slider else 60)

    def _change_wall(self, k, wall):
        """move a fan to another wall - onto a free spot there, or not at all"""
        fan = self.cfg.fans[k]
        before = (fan.wall, fan.pos_mm, fan.pos2_mm, fan.direction)
        old = fan.wall
        fan.wall = wall
        if wall == 'inside':
            fan.direction = 'up'
            fan.pos2_mm = max(fan.pos2_mm, 150.0)
        elif old == 'inside':
            fan.direction = 'in' if wall in ('front', 'bottom', 'side') else 'out'
        elif wall == 'side':
            fan.pos2_mm = fan.pos2_mm if fan.pos2_mm > 0 else self.cfg.case.height_mm * 0.55
        ok, note = self._try(placement.snap, self.cfg, k, default=(False, 'Could not check the new spot'))
        if not ok:
            fan.wall, fan.pos_mm, fan.pos2_mm, fan.direction = before
            self.say('The %s has no free spot for Fan %d - it stays on the %s' % (
                placement.WALL_NAMES.get(wall, wall), k + 1, placement.WALL_NAMES.get(old, old)))
        else:
            self.say(note or 'Fan %d moved to the %s' % (k + 1, placement.describe(fan)))
        self.select_fan(k)
        self.refresh_tree()
        self.update_info()
        self.schedule_rebuild(150)

    def _append(self, fan):
        self.cfg.fans.append(fan)
        self.refresh_tree()
        self.select_fan(len(self.cfg.fans) - 1)
        self.update_info()
        self.schedule_rebuild(100)

    def add_fan(self):
        fan = Fan('front', 250, 250, 'in', hw.DEFAULT_CASE_FAN, 70)
        ok, note = self._try(placement.place_new, self.cfg, fan, default=(False, ''))
        if not ok:
            self.say(note)
            return
        self._append(fan)
        self.say(note)

    def dup_fan(self):
        if self.sel is None or self.sel >= len(self.cfg.fans):
            return
        k = self.sel
        o = self.cfg.fans[k]
        twin = o.copy()
        near = (o.pos_mm, o.pos2_mm) if o.wall in ('side', 'inside') else o.pos_mm
        ok, note = self._try(lambda: placement.place_new(self.cfg, twin, near=near), default=(False, ''))
        if not ok:
            if note:
                self.say(note)
            return
        self._append(twin)
        if note.startswith('New fan: '):
            note = 'Copy of Fan %d: %s' % (k + 1, note[len('New fan: '):])
        self.say(note)

    def del_fan(self):
        if self.sel is None or not self.cfg.fans or self.sel >= len(self.cfg.fans):
            return
        del self.cfg.fans[self.sel]
        self.sel = min(self.sel, len(self.cfg.fans) - 1) if self.cfg.fans else None
        self.refresh_tree()
        if self.sel is not None:
            self.select_fan(self.sel)
        self.update_info()
        self.schedule_rebuild(100)

    def _resolve_after_change(self):
        """new hardware (a drive cage, a longer GPU, a smaller case) may sit where a fan or block was: move it"""
        moved = self._try(placement.resolve, self.cfg, default=[])
        if moved:
            self.refresh_tree()
            if self.sel is not None and self.sel < len(self.cfg.fans):
                self.select_fan(self.sel)
            self.refresh_btree()
            if self.bsel is not None and self.bsel < len(self.cfg.blocks):
                self.select_block(self.bsel)
            self.say(' · '.join(moved), seconds=12)
        return moved

    def fix_overlaps(self):
        """fans and blocks that sit on something go to the nearest free spot"""
        notes = self._try(placement.resolve, self.cfg, default=[])
        if not notes:
            self.say('No fan or block overlaps anything')
            return
        self.refresh_tree()
        if self.sel is not None:
            self.select_fan(self.sel)
        self.refresh_btree()
        if self.bsel is not None and self.bsel < len(self.cfg.blocks):
            self.select_block(self.bsel)
        self.schedule_rebuild(100)
        self.say(' · '.join(notes), seconds=12)

    def reverse_fan(self):
        if self.sel is None or self.sel >= len(self.cfg.fans):
            return
        fan = self.cfg.fans[self.sel]
        fan.direction = {'in': 'out', 'out': 'in', 'up': 'down', 'down': 'up', 'left': 'right',
                         'right': 'left'}[fan.direction]
        self.select_fan(self.sel)
        self.refresh_tree()
        self.schedule_rebuild(100)

    def set_fan_speed(self, pct):
        if self.sel is None or self.sel >= len(self.cfg.fans):
            return
        self.cfg.fans[self.sel].speed_pct = float(pct)
        self.select_fan(self.sel)
        self.refresh_tree()
        self.update_info()
        self.schedule_rebuild(100)

    def set_all_speed(self, auto=False):
        for fan in self.cfg.fans:
            fan.speed_pct = -1.0 if auto else float(round(self.v_all.get()))
        self.refresh_tree()
        if self.sel is not None:
            self.select_fan(self.sel)
        self.update_info()
        self.schedule_rebuild(100)

    def load_preset(self):
        keep = self.cfg
        cfg = PRESETS[self.v_preset.get()]()
        for name in ('cpu', 'gpu', 'load', 'room_c', 'case', 'quality', 'psu_watts', 'psu_rating', 'psu_fan_mode',
                     'psu_fan_pct', 'gpu_fan_pct', 'cpu_power_w', 'gpu_power_w', 'gpu_length_mm', 'motherboard',
                     'ram_sticks', 'ram_type', 'ram_ecc', 'nvme_count', 'hdd_count', 'filter_condition', 'altitude_m',
                     'fan_curve', 'blocks'):                  # your blocks stay in the case
            setattr(cfg, name, getattr(keep, name))
        preset_aio = hw.COOLERS[cfg.cooler]['kind'] == 'aio'
        if not preset_aio:                     # the ready-made fan layouts keep your own cooler
            for name in ('cooler', 'cooler_fan_model', 'cooler_fans', 'cooler_orientation', 'cooler_fan_pct',
                         'aio_mount', 'aio_direction'):
                setattr(cfg, name, getattr(keep, name))
        notes = self._try(placement.resolve, cfg, default=[])
        if preset_aio and keep.cooler != cfg.cooler:
            notes.insert(0, 'This ready-made setup uses its own cooler: %s' % cfg.cooler)
        self.cfg = cfg
        self.sel = None
        self.load_widgets_from_cfg()
        self.rebuild(keep=True)
        if notes:
            self.say(' · '.join(notes), seconds=12)

    # ================================================================ blocks tab
    def refresh_btree(self):
        sel = self.bsel
        self.btree.delete(*self.btree.get_children())
        for k, b in enumerate(self.cfg.blocks):
            self.btree.insert('', 'end', iid='b%d' % k, values=(
                k + 1, b.model, '%.0f × %.0f' % (b.w_mm, b.h_mm), '%.0f, %.0f' % (b.x_mm, b.y_mm),
                AIR_SHORT.get(b.air, b.air), ('%.0f W' % b.watts) if b.watts else '-', ''))
        if sel is not None and sel < len(self.cfg.blocks):
            self.btree.selection_set('b%d' % sel)

    def update_btree_live(self):
        if self.summary is None:
            return
        air = {b['label']: b['t_air'] for b in self.summary.get('blocks', [])}
        left_out = {r['index'] for r in self.view.L.draw.get('rejected_blocks', [])} if self.view is not None else set()
        for k in range(len(self.cfg.blocks)):
            iid = 'b%d' % k
            if not self.btree.exists(iid):
                continue
            vals = list(self.btree.item(iid, 'values'))
            t = air.get('Block %d' % (k + 1))
            vals[6] = ('%.0f °C' % t) if t is not None else ('left out' if k in left_out else '')
            self.btree.item(iid, values=vals)

    def on_select_block(self):
        s = self.btree.selection()
        if s and int(s[0][1:]) != self.bsel:
            self.select_block(int(s[0][1:]), from_tree=True)

    def _block_widgets(self, b):
        if b is None:
            self.l_bedit.configure(text='No block selected - press "+ Add block", or right-click the picture')
            self.l_binfo.configure(text='')
            return
        self.l_bedit.configure(text='Block %d' % (self.bsel + 1))
        self.l_binfo.configure(text=hw.BLOCK_AIR.get(b.air, '') +
                               ((' · gives %.0f W of heat to the air (counted in the power budget)' % b.watts)
                                if b.watts else ''))

    def select_block(self, k, from_tree=False):
        if k is None or k >= len(self.cfg.blocks):
            return
        self.bsel = k
        b = self.cfg.blocks[k]
        cs = self.cfg.case
        self._quiet = True
        self.s_bx.configure(from_=b.w_mm / 2, to=max(b.w_mm / 2, cs.depth_mm - b.w_mm / 2))
        self.s_by.configure(from_=b.h_mm / 2, to=max(b.h_mm / 2, cs.height_mm - b.h_mm / 2))
        self.v_bkind.set(b.model)
        self.v_bx.set(b.x_mm)
        self.v_by.set(b.y_mm)
        self.v_bw.set(b.w_mm)
        self.v_bh.set(b.h_mm)
        self.v_bair.set(b.air)
        self.v_bwatts.set(b.watts)
        self._quiet = False
        self._block_widgets(b)
        if not from_tree and self.btree.exists('b%d' % k):
            self.btree.selection_set('b%d' % k)
            self.btree.see('b%d' % k)

    def _block_changed(self, k, note='', ms=60):
        if note:
            self.say(note)
        self.refresh_btree()
        self.select_block(k)
        self.update_info()
        self.schedule_rebuild(ms)

    def _snap_block(self, k, before):
        """after a move / resize / new kind: on a free spot, or back to how it was"""
        ok, note = self._try(placement.snap_block, self.cfg, k, default=(False, 'Could not check the new spot'))
        if not ok:
            self.cfg.blocks[k] = before
            note += ' - Block %d stays as it was' % (k + 1)
        return note

    def on_block_edit(self, slider=False, snap=False):
        if self._quiet or self.bsel is None or self.bsel >= len(self.cfg.blocks):
            return
        k = self.bsel
        b = self.cfg.blocks[k]
        before = b.copy()
        b.x_mm = round(self._num(self.v_bx, b.x_mm))
        b.y_mm = round(self._num(self.v_by, b.y_mm))
        b.w_mm = round(min(max(self._num(self.v_bw, b.w_mm), hw.BLOCK_MIN_MM), hw.BLOCK_MAX_MM), 1)
        b.h_mm = round(min(max(self._num(self.v_bh, b.h_mm), hw.BLOCK_MIN_MM), hw.BLOCK_MAX_MM), 1)
        if self.v_bair.get() in hw.BLOCK_AIR:
            b.air = self.v_bair.get()
        b.watts = min(max(self._num(self.v_bwatts, b.watts), 0.0), hw.MAX_BLOCK_WATTS)
        note = ''
        if snap or (not slider and (b.w_mm, b.h_mm) != (before.w_mm, before.h_mm)):
            note = self._snap_block(k, before)
        self._block_changed(k, note, 120 if slider else 60)

    def on_block_kind(self):
        if not self._quiet and self.v_bkind.get() in hw.BLOCKS:
            self.set_block_kind(self.v_bkind.get())

    def set_block_kind(self, kind):
        """a block becomes another kind: that kind's size, air and heat, at the same place"""
        k = self.bsel
        if k is None or k >= len(self.cfg.blocks) or kind not in hw.BLOCKS:
            return
        b = self.cfg.blocks[k]
        before = b.copy()
        new = Block.of(kind, b.x_mm, b.y_mm)
        b.model, b.w_mm, b.h_mm, b.air, b.watts = new.model, new.w_mm, new.h_mm, new.air, new.watts
        note = self._snap_block(k, before) or 'Block %d is now: %s' % (k + 1, kind)
        self._block_changed(k, note)

    def set_block_air(self, air):
        k = self.bsel
        if k is None or k >= len(self.cfg.blocks) or air not in hw.BLOCK_AIR:
            return
        self.cfg.blocks[k].air = air
        self._block_changed(k, 'Block %d: %s' % (k + 1, hw.BLOCK_AIR[air]))

    def turn_block(self):
        k = self.bsel
        if k is None or k >= len(self.cfg.blocks):
            return
        b = self.cfg.blocks[k]
        before = b.copy()
        b.w_mm, b.h_mm = b.h_mm, b.w_mm
        self._block_changed(k, self._snap_block(k, before) or 'Block %d turned: %.0f × %.0f mm' % (k + 1, b.w_mm, b.h_mm))

    def add_block(self, kind=None, near=None):
        kind = kind if kind in hw.BLOCKS else self.v_bkind_new.get()
        if kind not in hw.BLOCKS:
            kind = hw.DEFAULT_BLOCK
        if len(self.cfg.blocks) >= MAX_BLOCKS:
            self.say('A setup can have at most %d blocks' % MAX_BLOCKS)
            return
        cs = self.cfg.case
        near = near if near is not None else (0.55 * cs.depth_mm, 0.6 * cs.height_mm)
        b = Block.of(kind, *near)
        ok, note = self._try(lambda: placement.place_new_block(self.cfg, b, near=near), default=(False, ''))
        if not ok:
            if note:
                self.say(note)
            return
        self.cfg.blocks.append(b)
        self.nb.select(TAB_BLOCKS)
        self._block_changed(len(self.cfg.blocks) - 1, '%s: %s - drag it in the picture to move it' % (
            kind, note[len('New block: '):] if note.startswith('New block: ') else note))

    def dup_block(self):
        k = self.bsel
        if k is None or k >= len(self.cfg.blocks):
            return
        if len(self.cfg.blocks) >= MAX_BLOCKS:
            self.say('A setup can have at most %d blocks' % MAX_BLOCKS)
            return
        twin = self.cfg.blocks[k].copy()
        ok, note = self._try(lambda: placement.place_new_block(self.cfg, twin), default=(False, ''))
        if not ok:
            if note:
                self.say(note)
            return
        self.cfg.blocks.append(twin)
        self._block_changed(len(self.cfg.blocks) - 1, 'Copy of Block %d: %s' % (k + 1, placement.describe_block(twin)))

    def del_block(self):
        k = self.bsel
        if k is None or k >= len(self.cfg.blocks):
            return
        del self.cfg.blocks[k]
        self.bsel = min(k, len(self.cfg.blocks) - 1) if self.cfg.blocks else None
        self.refresh_btree()
        if self.bsel is not None:
            self.select_block(self.bsel)
        else:
            self._block_widgets(None)
        self.update_info()
        self.schedule_rebuild(60)

    # ================================================================ parts tab
    def _pcat(self):
        title = self.v_pcat.get()
        return next((c for c, t in library.CATEGORIES.items() if t == title), 'gpu')

    def parts_select_category(self, cat):
        self.v_pcat.set(library.CATEGORIES[cat])
        self.parts_cancel()
        self.parts_refresh_list()

    def parts_refresh_list(self, select=None):
        cat = self._pcat()
        self.ptree.delete(*self.ptree.get_children())
        self._pnames = {}
        table = library.table(cat)
        names = [n for n in table if not library.is_custom(cat, n)] + library.custom_names(cat)
        for i, name in enumerate(names):
            iid = 'p%d' % i
            self._pnames[iid] = name
            own = library.is_custom(cat, name)
            self.ptree.insert('', 'end', iid=iid, values=(name, library.summary(cat, name),
                                                          ('★' if library.is_saved(cat, name) else '☆') if own else ''))
            if name == select:
                self.ptree.selection_set(iid)
                self.ptree.see(iid)
        self._parts_buttons()

    def _sel_part(self):
        s = self.ptree.selection()
        return self._pnames.get(s[0]) if s else None

    def _sel_part_is_custom(self):
        name = self._sel_part()
        return bool(name) and library.is_custom(self._pcat(), name)

    def _parts_buttons(self):
        own = self._sel_part_is_custom()
        for b in (self.b_pedit, self.b_pdel):
            b.state(['!disabled'] if own else ['disabled'])

    def _parts_editor(self, title, spec, name):
        ed = self.ped
        for w in ed.winfo_children():
            w.destroy()
        cat = self._pcat()
        ttk.Label(ed, text=title, style='Panel.TLabel', font=('Segoe UI', 11, 'bold')).grid(
            row=0, column=0, columnspan=3, sticky='w', pady=(0, 6))
        self.part_name.set(name)
        ttk.Label(ed, text='Name', style='Panel.TLabel').grid(row=1, column=0, sticky='w', pady=3, padx=(0, 8))
        ttk.Entry(ed, textvariable=self.part_name).grid(row=1, column=1, columnspan=2, sticky='ew')
        kind = spec.get('kind', 'tower') if cat == 'cooler' else None
        self.part_vars = {}
        r = 2
        for fd in library.fields(cat, kind):
            if fd.type == 'bool':
                var = tk.BooleanVar(value=bool(spec.get(fd.key, False)))
                w = ttk.Checkbutton(ed, variable=var, style='Panel.TCheckbutton')
            elif fd.type == 'choice':
                var = tk.StringVar(value=str(spec.get(fd.key, fd.choices[0])))
                w = ttk.Combobox(ed, textvariable=var, values=[str(c) for c in fd.choices], state='readonly', width=12)
                if cat == 'cooler' and fd.key == 'kind':
                    w.bind('<<ComboboxSelected>>', lambda e: self._parts_kind_changed())
            else:
                var = tk.StringVar(value=fmt_num(spec.get(fd.key, '')))
                w = ttk.Entry(ed, textvariable=var, width=10)
            ttk.Label(ed, text=fd.label, style='Panel.TLabel').grid(row=r, column=0, sticky='w', pady=2, padx=(0, 8))
            w.grid(row=r, column=1, sticky='w')
            hint = ('%s   (%g … %g)' % (fd.unit, fd.lo, fd.hi)).strip() if fd.type in ('int', 'float') else fd.unit
            ttk.Label(ed, text=hint, style='PanelSub.TLabel').grid(row=r, column=2, sticky='w', padx=(8, 0))
            self.part_vars[fd.key] = var
            r += 1
        bt = ttk.Frame(ed, style='Panel.TFrame')
        bt.grid(row=r, column=0, columnspan=3, sticky='w', pady=(8, 0))
        ttk.Button(bt, text='Save part', style='Accent.TButton', command=self.parts_save).pack(side='left')
        ttk.Button(bt, text='Cancel', command=self.parts_cancel).pack(side='left', padx=6)
        self.l_part_err.configure(text='')
        ed.grid()

    def _parts_values(self):
        return {k: v.get() for k, v in self.part_vars.items()}

    def _parts_kind_changed(self):
        now = self._parts_values()
        spec = library.defaults('cooler', now.get('kind', 'tower'))
        for k in ('fan_mm', 'r100'):
            if k in now:
                spec[k] = now[k]
        title = 'New CPU cooler' if self.part_mode == 'new' else 'Edit "%s"' % self.part_old
        self._parts_editor(title, spec, self.part_name.get())

    def parts_new(self):
        cat = self._pcat()
        self.part_mode, self.part_old = 'new', None
        self._parts_editor('New %s' % library.SINGULAR[cat], library.defaults(cat), '')

    def parts_copy(self):
        cat = self._pcat()
        name = self._sel_part()
        if not name:
            self.say('Pick a part in the list to copy')
            return
        base = '%s copy' % name[:library.MAX_NAME - 8]
        new, n = base, 2
        while new in library.table(cat):
            new = '%s %d' % (base, n)
            n += 1
        self.part_mode, self.part_old = 'new', None
        self._parts_editor('New %s (copy of "%s")' % (library.SINGULAR[cat], name), dict(library.table(cat)[name]), new)

    def parts_edit(self):
        cat = self._pcat()
        name = self._sel_part()
        if not name or not library.is_custom(cat, name):
            self.say('Built-in parts cannot be changed - use "Copy as new"')
            return
        self.part_mode, self.part_old = 'edit', name
        self._parts_editor('Edit "%s"' % name, dict(library.table(cat)[name]), name)

    def parts_cancel(self):
        self.part_mode, self.part_old = None, None
        self.ped.grid_remove()
        self.l_part_err.configure(text='')

    def parts_save(self):
        """check and save the part in the editor; returns True when it was added"""
        cat = self._pcat()
        spec = self._parts_values()
        saved_note = ''
        try:
            if self.part_mode == 'edit':
                name = library.update(cat, self.part_old, self.part_name.get(), spec)
            else:
                name = library.add(cat, self.part_name.get(), spec)
        except library.SaveError as e:
            name = self.part_name.get().strip()
            saved_note = str(e)
        except library.PartError as e:
            self.l_part_err.configure(text='Please fix:\n• ' + '\n• '.join(e.problems))
            return False
        old = self.part_old
        self.parts_cancel()
        in_use = name in library.used_parts(self.cfg)[cat] or (old is not None and old in library.used_parts(self.cfg)[cat])
        if old is not None and old != name:
            self._rename_in_setup(cat, old, name)
        if cat == 'case' and self.cfg.case.name == name:
            self.cfg.apply_case_preset(name)
        self.refresh_part_lists(select=name)
        if in_use:
            fixed = self.cfg.validate()
            moved = self._resolve_after_change()
            self.load_widgets_from_cfg(keep_sel=True)
            self.schedule_rebuild(100)
            if fixed or moved:
                saved_note = (saved_note + ' · ' if saved_note else 'Saved "%s" · ' % name) + \
                    ' · '.join(fixed[:3] + (moved or []))
        self.say(saved_note or 'Saved "%s" - it is in the %s list now' % (name, library.CATEGORIES[cat].lower()))
        return True

    def _rename_in_setup(self, cat, old, new):
        c = self.cfg
        if cat == 'cpu' and c.cpu == old:
            c.cpu = new
        elif cat == 'gpu' and c.gpu == old:
            c.gpu = new
        elif cat == 'cooler' and c.cooler == old:
            c.cooler = new
        elif cat == 'motherboard' and c.motherboard == old:
            c.motherboard = new
        elif cat == 'case' and c.case.name == old:
            c.case.name = new
        elif cat == 'fan':
            for f in c.fans:
                if f.model == old:
                    f.model = new
            if c.cooler_fan_model == old:
                c.cooler_fan_model = new
        elif cat == 'block':
            for b in c.blocks:
                if b.model == old:
                    b.model = new

    def parts_delete(self):
        cat = self._pcat()
        name = self._sel_part()
        if not name or not library.is_custom(cat, name):
            self.say('Built-in parts cannot be deleted')
            return
        if not messagebox.askyesno('Delete part', 'Delete your %s "%s"?' % (library.SINGULAR[cat], name),
                                   parent=self.root):
            return
        try:
            library.delete(cat, name)
            note = 'Deleted "%s"' % name
        except library.SaveError as e:
            note = str(e)
        except library.PartError as e:
            self.say(str(e))
            return
        changed = self.cfg.validate()
        self.refresh_part_lists()
        if changed:
            self.load_widgets_from_cfg()
            self.schedule_rebuild(100)
            note += ' - this setup now uses a built-in part instead'
        self.say(note)

    def parts_use(self):
        cat = self._pcat()
        name = self._sel_part()
        if not name:
            self.say('Pick a part in the list first')
            return
        c = self.cfg
        if cat == 'fan':
            if self.sel is None or self.sel >= len(c.fans):
                self.say('Select a case fan in the Fans tab first - the fan model is set on that fan')
                return
            old_model = c.fans[self.sel].model
            c.fans[self.sel].model = name
            ok, snap_note = self._try(placement.snap, c, self.sel, default=(False, 'Could not check its spot'))
            if not ok:
                c.fans[self.sel].model = old_model
                self.say('%s - "%s" was not fitted' % (snap_note, name), seconds=10)
                return
            what = 'Fan %d%s' % (self.sel + 1, (' (%s)' % snap_note) if snap_note else '')
        elif cat == 'gpu':
            c.gpu, c.gpu_length_mm = name, 0.0
            what = 'the graphics card'
        elif cat == 'cpu':
            c.cpu = name
            mem = hw.CPUS[name].get('memory', 'DDR4/DDR5').split('/')
            if c.ram_type not in mem:
                c.ram_type = mem[-1]
            what = 'the processor'
        elif cat == 'cooler':
            c.cooler, c.cooler_fan_model, c.cooler_fans = name, '', 0
            what = 'the CPU cooler'
        elif cat == 'motherboard':
            c.motherboard = name
            what = 'the motherboard'
        elif cat == 'block':
            self.add_block(name)                     # a block is added to the case, at a free spot
            return
        else:
            c.apply_case_preset(name)
            what = 'the case'
        fixed = c.validate()
        moved = self._try(placement.resolve, c, default=[])
        self.load_widgets_from_cfg(keep_sel=True)
        self.rebuild(keep=False)
        extra = fixed[:3] + (moved or [])
        self.say('"%s" is now %s of this setup%s' % (name, what, (' · ' + ' · '.join(extra)) if extra else ''), 12)

    def parts_open_folder(self):
        folder = os.path.dirname(library.parts_path())
        try:
            os.makedirs(folder, exist_ok=True)
            if sys.platform.startswith('win'):
                os.startfile(folder)
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', folder])
            else:
                subprocess.Popen(['xdg-open', folder])
        except OSError as e:
            self.say('Could not open %s (%s)' % (folder, e))

    def refresh_part_lists(self, select=None):
        """after parts were added / changed / removed: every list in the app shows them"""
        self.cb_cpu.configure(values=list(hw.CPUS))
        self.cb_gpu.configure(values=list(hw.GPUS))
        self.cb_cooler.configure(values=list(hw.COOLERS))
        self.cb_board.configure(values=list(hw.MOTHERBOARDS))
        self.cb_case.configure(values=list(hw.CASES))
        self.cb_model.configure(values=list(hw.ALL_FANS))
        self.cb_bkind.configure(values=list(hw.BLOCKS))
        self.cb_bkind_new.configure(values=list(hw.BLOCKS))
        self._quiet = True
        self._cooler_lists()
        self._quiet = False
        self.parts_refresh_list(select=select)
        self.refresh_btree()

    # ================================================================ mouse on the picture
    def _fan_points(self, fan):
        cs = self.cfg.case
        D, H, p = cs.depth_mm, cs.height_mm, fan.pos_mm
        if fan.wall == 'front':
            return [(D - 13, p), (D + 44, p)]
        if fan.wall == 'rear':
            return [(13, p), (-44, p)]
        if fan.wall == 'top':
            return [(p, H - 13), (p, H + 38)]
        if fan.wall == 'bottom':
            y = (cs.shroud_height_mm + 13) if (cs.shroud and p < cs.shroud_length_mm) else 13
            return [(p, y), (p, -64)]
        return [(fan.pos_mm, fan.pos2_mm)]

    def _hit(self, x, y):
        best = None
        for k, fan in enumerate(self.cfg.fans):
            for fx, fy in self._fan_points(fan):
                d = math.hypot(x - fx, y - fy)
                if d < max(32.0, 0.5 * fan.size) and (best is None or d < best[0]):
                    best = (d, k)
        return None if best is None else best[1]

    def _constrain(self, fan, x, y):
        cs = self.cfg.case
        s = fan.size
        if fan.wall in ('front', 'rear'):
            return float(np.clip(y, s / 2, cs.height_mm - s / 2)), fan.pos2_mm
        if fan.wall in ('top', 'bottom'):
            return float(np.clip(x, s / 2, cs.depth_mm - s / 2)), fan.pos2_mm
        return float(np.clip(x, 13, cs.depth_mm - 13)), float(np.clip(y, 13, cs.height_mm - 13))

    def _hit_block(self, x, y):
        """(index, 'move' or 'resize') of the block under the mouse (as drawn), or None"""
        if self.view is None:
            return None
        L, best = self.view.L, None
        for b in L.draw.get('blocks', []) + L.draw.get('rejected_blocks', []):
            if b['index'] >= len(self.cfg.blocks):
                continue
            x0, x1, y0, y1 = b['box']
            g = max(HANDLE_MM, 6.0)
            if x1 - g <= x <= x1 + 3 and y1 - g <= y <= y1 + 3:
                return b['index'], 'resize'
            t = 3.0 if min(x1 - x0, y1 - y0) < 10 else 0.0         # thin panels are easier to catch
            if x0 - t <= x <= x1 + t and y0 - t <= y <= y1 + t:
                area = (x1 - x0) * (y1 - y0)
                if best is None or area < best[2]:
                    best = (b['index'], 'move', area)
        return None if best is None else best[:2]

    def _under(self, x, y):
        """the fan or the block under the mouse: (fan index or None, (block index, mode) or None)"""
        k, hb = self._hit(x, y), self._hit_block(x, y)
        if k is not None and hb is not None:                   # inside a block, a fan only wins right at its frame
            near = min(math.hypot(x - fx, y - fy) for fx, fy in self._fan_points(self.cfg.fans[k]))
            if near > 15.0:
                k = None
            else:
                hb = None
        return k, hb

    def _popup(self, menu, ev):
        try:
            menu.tk_popup(int(ev.guiEvent.x_root), int(ev.guiEvent.y_root))
        finally:
            menu.grab_release()

    def _kind_menu(self, menu, command):
        menu.delete(0, 'end')
        for kind in hw.BLOCKS:
            menu.add_command(label=kind, command=lambda kd=kind: command(kd))

    def on_press(self, ev):
        if ev.inaxes is not self.ax or ev.xdata is None:
            return
        k, hb = self._under(ev.xdata, ev.ydata)
        if ev.button == 3:
            if k is not None:
                self.select_fan(k)
                self._popup(self.menu, ev)
            elif hb is not None:
                self.select_block(hb[0])
                self.v_bmenu_air.set(self.cfg.blocks[hb[0]].air)
                self._kind_menu(self.bmenu_kind, self.set_block_kind)
                self._popup(self.bmenu, ev)
            else:
                self._menu_xy = (ev.xdata, ev.ydata)
                self._kind_menu(self.emenu_kind, lambda kd: self.add_block(kd, near=self._menu_xy))
                self._popup(self.emenu, ev)
            return
        if ev.button != 1:
            return
        if ev.dblclick:
            if k is None and hb is None:
                self.add_fan_at(ev.xdata, ev.ydata)
            return
        if hb is not None and k is None:
            self.start_block_drag(hb[0], hb[1], ev.xdata, ev.ydata)
            return
        if k is not None:
            self.select_fan(k)
            self.nb.select(TAB_FANS)
            fan = self.cfg.fans[k]
            self.drag = k
            self.drag_moved = False
            self.drag_start = (fan.wall, fan.pos_mm, fan.pos2_mm, fan.direction)
            self.drag_probe = self._try(lambda: placement.Probe(self.cfg, skip={k}))
            self._show_ghost(fan, *self._fan_points(fan)[0])

    def _show_ghost(self, fan, x, y, bad=False):
        if self.view is None:
            return
        g = self.view.ghost
        g.set_center((x, y))
        g.set_radius(0.5 * fan.size)
        g.set_edgecolor(BAD if bad else 'white')
        g.set_visible(True)
        self._marker()

    # ---------------------------------------------------------------- blocks with the mouse
    def start_block_drag(self, k, mode, x, y):
        self.select_block(k)
        self.nb.select(TAB_BLOCKS)
        b = self.cfg.blocks[k]
        self.bdrag = dict(index=k, mode=mode, start=b.copy(), moved=False, dx=x - b.x_mm, dy=y - b.y_mm,
                          x0=b.x_mm - b.w_mm / 2, y0=b.y_mm - b.h_mm / 2,
                          probe=self._try(lambda: placement.Probe(self.cfg, skip_blocks={k})))
        self._show_ghost_box(b)

    def _show_ghost_box(self, b, bad=False):
        if self.view is None:
            return
        x0, x1, y0, y1 = b.box()
        g = self.view.ghost_box
        g.set_bounds(x0, y0, x1 - x0, y1 - y0)
        g.set_edgecolor(BAD if bad else 'white')
        g.set_visible(True)
        self._marker()

    def drag_block(self, x, y):
        d = self.bdrag
        k = d['index']
        if k >= len(self.cfg.blocks):
            return
        b, cs = self.cfg.blocks[k], self.cfg.case
        if d['mode'] == 'move':
            b.x_mm = round(float(np.clip(x - d['dx'], b.w_mm / 2, max(b.w_mm / 2, cs.depth_mm - b.w_mm / 2))))
            b.y_mm = round(float(np.clip(y - d['dy'], b.h_mm / 2, max(b.h_mm / 2, cs.height_mm - b.h_mm / 2))))
        else:                                                  # the bottom-left corner stays where it is
            b.w_mm = round(float(np.clip(x - d['x0'], hw.BLOCK_MIN_MM, max(hw.BLOCK_MIN_MM, cs.depth_mm - d['x0']))))
            b.h_mm = round(float(np.clip(y - d['y0'], hw.BLOCK_MIN_MM, max(hw.BLOCK_MIN_MM, cs.height_mm - d['y0']))))
            b.x_mm, b.y_mm = d['x0'] + b.w_mm / 2, d['y0'] + b.h_mm / 2
        d['moved'] = True
        self._quiet = True
        for var, val in ((self.v_bx, b.x_mm), (self.v_by, b.y_mm), (self.v_bw, b.w_mm), (self.v_bh, b.h_mm)):
            var.set(val)
        self._quiet = False
        why = d['probe'].why_block(b) if d['probe'] is not None else None
        self._show_ghost_box(b, bad=bool(why))
        self.status.configure(text='%s Block %d → %s%s' % (
            'moving' if d['mode'] == 'move' else 'resizing', k + 1, placement.describe_block(b),
            ('   ·   would sit on %s' % why) if why else ''))

    def drop_block(self):
        d, self.bdrag = self.bdrag, None
        if self.view is not None:
            self.view.ghost_box.set_visible(False)
            self._marker()
        k = d['index']
        if not d['moved'] or k >= len(self.cfg.blocks):
            return
        b, probe = self.cfg.blocks[k], d['probe']
        why = probe.why_block(b) if probe is not None else None
        note = 'Block %d: %s' % (k + 1, placement.describe_block(b))
        if why and d['mode'] == 'resize':
            self.cfg.blocks[k] = d['start']
            note = 'Block %d would sit on %s at that size - it keeps its size' % (k + 1, why)
        elif why:
            spot = probe.find_block(b, (b.x_mm, b.y_mm))
            if spot:
                b.x_mm, b.y_mm = spot
                note = 'Block %d would sit on %s - moved beside it (%s)' % (k + 1, why, placement.describe_block(b))
            else:
                self.cfg.blocks[k] = d['start']
                note = 'No free spot there for Block %d - it went back' % (k + 1)
        self._block_changed(k, note, 30)

    def on_motion(self, ev):
        if self.bdrag is not None and ev.xdata is not None:
            self.drag_block(ev.xdata, ev.ydata)
            return
        if self.drag is None or ev.xdata is None or self.drag >= len(self.cfg.fans):
            return
        fan = self.cfg.fans[self.drag]
        p, p2 = self._constrain(fan, ev.xdata, ev.ydata)
        fan.pos_mm, fan.pos2_mm = round(p), round(p2)
        self.drag_moved = True
        self._quiet = True
        self.v_pos.set(fan.pos_mm)
        self.v_pos2.set(fan.pos2_mm)
        self._quiet = False
        why = self.drag_probe.why(fan) if self.drag_probe is not None else None
        self._show_ghost(fan, *self._fan_points(fan)[0], bad=bool(why))
        self.status.configure(text='moving Fan %d → %s %s mm%s' % (
            self.drag + 1, fan.wall, self._pos_text(fan), ('   ·   would sit on %s' % why) if why else ''))

    def on_release(self, ev):
        if self.bdrag is not None:
            self.drop_block()
            return
        if self.drag is None:
            return
        k, moved, probe = self.drag, self.drag_moved, self.drag_probe
        self.drag, self.drag_probe = None, None
        if self.view is not None:
            self.view.ghost.set_visible(False)
            self._marker()
        if not moved or k >= len(self.cfg.fans):
            return
        fan = self.cfg.fans[k]
        why = probe.why(fan) if probe is not None else None
        if why:
            near = (fan.pos_mm, fan.pos2_mm) if fan.wall in ('side', 'inside') else fan.pos_mm
            spot = probe.find(fan, [fan.wall], near)
            if spot:
                placement.apply_spot(fan, spot)
                self.say('Fan %d would sit on %s - moved beside it (%s)' % (k + 1, why, placement.describe(fan)))
            else:
                fan.wall, fan.pos_mm, fan.pos2_mm, fan.direction = self.drag_start
                self.say('No free spot there for Fan %d - it went back' % (k + 1))
        self.refresh_tree()
        self.select_fan(k)
        self.schedule_rebuild(30)

    def on_scroll(self, ev):
        if ev.inaxes is not self.ax or ev.xdata is None:
            return
        k = self._hit(ev.xdata, ev.ydata)
        if k is None:
            return
        fan = self.cfg.fans[k]
        start = self._live_pct(k) if fan.auto else fan.speed_pct
        fan.speed_pct = float(np.clip(round(start) + (5 if ev.button == 'up' else -5), 0, 100))
        self.select_fan(k)
        self.refresh_tree()
        self.say('Fan %d speed %.0f %% = %.0f rpm' % (k + 1, fan.speed_pct, fan.rpm), seconds=3)
        self.schedule_rebuild(120)

    def add_fan_at(self, x, y):
        cs = self.cfg.case
        D, H = cs.depth_mm, cs.height_mm
        near = 32.0
        dist = {'front': D - x, 'rear': x, 'top': H - y, 'bottom': y}
        wall = min(dist, key=dist.get)                   # nearest wall (or the side we clicked outside of)
        if dist[wall] > near:
            fan = Fan('inside', x, y, 'up')
        elif wall in ('front', 'rear'):
            fan = Fan(wall, y, 0, 'in' if wall == 'front' else 'out')
        else:
            fan = Fan(wall, x, 0, 'out' if wall == 'top' else 'in')
        fan.pos_mm, fan.pos2_mm = self._constrain(fan, x, y)
        fan.pos_mm, fan.pos2_mm = round(fan.pos_mm), round(fan.pos2_mm)
        target = (fan.pos_mm, fan.pos2_mm) if fan.wall == 'inside' else fan.pos_mm
        ok, note = self._try(lambda: placement.place_new(self.cfg, fan, near=target), default=(False, ''))
        if not ok:
            if note:
                self.say(note)
            return
        self._append(fan)
        self.nb.select(TAB_FANS)
        self.say('%s - set its direction and speed in the Fans tab' % note)

    # ================================================================ simulation loop
    def schedule_rebuild(self, ms=200):
        if self._pending is not None:
            self.root.after_cancel(self._pending)
        self._pending = self.root.after(ms, self.rebuild)

    def rebuild(self, keep=True):
        self._pending = None
        try:
            layout = Layout(self.cfg)
            prev = self.sim if keep else None
            self.sim = Solver(layout, n_particles=PART_COUNT.get(self.cfg.quality, 900), previous=prev,
                              dt=LIVE_STEP * layout.h)
        except Exception as e:                       # noqa: BLE001 - show it, never keep old results on screen
            log.exception('could not build the setup')
            self.sim, self.summary = None, None
            self.live = None
            self.ax.clear()
            self.ax.set_axis_off()
            self.ax.text(0.5, 0.5, 'This setup could not be simulated:\n%s\n\nChange the setting you just edited.'
                         % e, transform=self.ax.transAxes, ha='center', va='center', color=WARN, fontsize=11,
                         wrap=True, parse_math=False)
            self.view = None
            for big, sub in self.tile.values():
                big.configure(text='-')
                sub.configure(text='')
            self.warn.configure(text='⚠ The simulation is stopped: %s' % e)
            self.canvas.draw_idle()
            return
        if keep and self.view is not None and self.live is not None and self.view.key == drawing_key(layout):
            self.view.retarget(layout)               # only speeds / loads changed: the drawing stays
        else:
            clear_view(self.ax)
            self.view = CaseView(self.ax, layout, fs=0.78, dashes=PART_COUNT.get(self.cfg.quality, 900))
            self.live = LiveFrames(self.canvas, self.view, previous=self.live)
            self.summary = None
        self.settle_until = self.sim.t + (0.8 if keep else 1.5)
        w = layout.warnings
        if any(r.get('why') != 'the radiator' for r in layout.draw['rejected']) or layout.draw['rejected_blocks']:
            w = w + ['Press "Fix overlaps" (Fans or Blocks tab) to move what is marked ✕ to a free spot']
        self.warn.configure(text=('⚠ ' + '\n⚠ '.join(w)) if w else '')
        self.view.update(self.k_anim, self.sim.interior_T(), self.sim.frame_particles(), self.summary)
        self._paint()

    def _paint(self):
        """put the current state of the view on screen - the quick way when possible"""
        if self.live is not None:
            try:
                self.live.frame()
                return
            except Exception:                        # noqa: BLE001 - never lose the picture: draw it normally
                log.exception('quick drawing failed - using the normal drawing')
                self.live = None
        self.canvas.draw_idle()

    def _marker(self):
        """only the drag marker changed"""
        if self.live is not None:
            try:
                self.live.marker()
                return
            except Exception:                        # noqa: BLE001
                log.exception('quick drawing failed - using the normal drawing')
                self.live = None
        self.canvas.draw_idle()

    def show_frame(self):
        now = time.perf_counter()
        self.k_anim += min(1.5, SPIN_RATE * (now - self._anim_t)) if self._anim_t else 1.0
        self._anim_t = now
        P = self.sim.frame_particles()
        if self.k % 4 == 0 and self.sim.disp is not None:
            self.summary = summarize(self.sim)
        self.view.update(self.k_anim, self.sim.interior_T(), P, self.summary)
        self.k += 1
        self._paint()
        if self.k % 8 == 0 and self.summary is not None:
            self.update_tiles()
            self.update_tree_live()
            self.update_btree_live()
        if self.k % 40 == 0 and self.sim.disp is not None and self._results_shown():
            self.update_report()

    def tick(self):
        """one short slice of simulation (and a new picture when one is due), then back to the window:
        clicks, drags and typing never wait for more than about one slice"""
        t_start = time.perf_counter()
        delay = 40
        try:
            if (self.running and self.sim is not None and self.view is not None and self.drag is None
                    and self.bdrag is None):
                settling = self.sim.t < getattr(self, 'settle_until', 0.0)
                gap = FRAME_GAP_SETTLING if settling else max(FRAME_GAP, self._frame_cost / FRAME_SHARE)
                if t_start - self._last_frame >= gap:
                    self._last_frame = t_start           # a picture this turn, simulation the next turns
                    self.show_frame()
                    cost = min(time.perf_counter() - t_start, 0.1)       # (a first picture of a new layout is slow)
                    self._frame_cost += 0.2 * (cost - self._frame_cost)
                else:
                    n = 0
                    while n < 40 and time.perf_counter() - t_start < SIM_SLICE:
                        self.sim.step()
                        self.sim.move_particles()
                        n += 1
                    self.root.update_idletasks()         # redraw changed controls now, not at the next picture
                delay = 0
            self.poll_job()
            self._errors = 0
        except Exception as e:                       # noqa: BLE001 - keep the app alive, show and log the problem
            self._errors += 1
            log.exception('simulation step failed')
            self.say('Error: %s' % e, seconds=10)
            if self._errors >= 5 and self.running:
                self.toggle_run()
                self.show_notes('Simulation paused', ['The simulation kept failing: %s' % e,
                                                      'Details are in %s' % (getattr(self, 'log_path', None) or
                                                                             'the log')])
        # 0 = right after the clicks and key presses waiting now (any other delay waits for the next ~15 ms clock
        # tick on Windows); never after_idle: update_idletasks() would then run the simulation forever
        self.root.after(delay, self.tick)

    def update_tiles(self):
        s = self.summary
        ld = s['loads']
        self.tile['cpu'][0].configure(text='≈ %.0f °C' % s['t_cpu'] + (' !' if s['cpu_limited'] else ''))
        self.tile['cpu'][1].configure(text='air in %.1f °C\n%.0f of %.0f W' % (s['cpu_in'], ld['p_cpu'], ld['cpu_max']))
        self.tile['gpu'][0].configure(text='≈ %.0f °C' % s['t_gpu'])
        self.tile['gpu'][1].configure(text='air in %.1f °C\n%.0f of %.0f W' % (s['gpu_in'], ld['p_gpu'], ld['gpu_max']))
        self.tile['power'][0].configure(text='%.0f W' % ld['p_dc'])
        self.tile['power'][1].configure(text='max %.0f W\nPSU %d W at %.0f %%' % (ld['p_dc_max'], self.cfg.psu_watts,
                                                                              100 * ld['psu_frac']))
        self.tile['flow'][0].configure(text='%.0f CFM' % s['cfm_in'])
        self.tile['flow'][1].configure(text='%d in · %d out\nout %.0f CFM' % (s['n_in'], s['n_out'], s['cfm_out']))
        p = s['p_case']
        self.tile['press'][0].configure(text=('%+.1f Pa' % p).replace('-', '−'))
        self.tile['press'][1].configure(text='negative\n(dust via gaps)' if p < -0.3 else
                                        ('positive\n(air leaks out)' if p > 0.3 else 'balanced\n'))
        sh = sorted(s['heat_share'].items(), key=lambda kv: -kv[1])
        self.tile['heat'][0].configure(text=('%s %.0f %%' % sh[0]) if sh else '-')
        self.tile['heat'][1].configure(text='\n'.join('%s %.0f %%' % kv for kv in sh[1:3]) or ' ')
        self._flow_tiles()                           # wider numbers may need the two-row layout
        if self.job is None and self.drag is None and self.bdrag is None and time.time() > self._hold_until:
            settling = self.sim.t < getattr(self, 'settle_until', 0.0)
            self.status.configure(text='%ssimulated %.1f s  ·  %s detail' % (
                'settling…  ' if settling else '', self.sim.t, self.cfg.quality))

    def toggle_run(self):
        self.running = not self.running
        self.btn_play.configure(text='Pause' if self.running else 'Play')

    # ================================================================ files / export
    def open_cfg(self):
        p = filedialog.askopenfilename(title='Open setup', initialdir=setups_dir(),
                                       filetypes=[('Setup', '*.json')])
        if not p:
            return
        try:
            cfg = Config.read(p)
            notes = list(cfg.notes) + placement.resolve(cfg)
        except Exception as e:                       # noqa: BLE001 - a bad file must never close the app
            log.exception('could not open %s', p)
            messagebox.showerror('Open setup', 'Could not open this setup:\n%s' % e, parent=self.root)
            return
        self.cfg = cfg
        self.sel = None
        self.refresh_part_lists()
        self.load_widgets_from_cfg()
        self.rebuild(keep=False)
        if cfg.info:
            self.say(' · '.join(cfg.info), seconds=10)
        if notes:
            self.show_notes('Opened with changes', notes)

    def save_cfg(self):
        p = filedialog.asksaveasfilename(title='Save setup', initialdir=setups_dir(),
                                         defaultextension='.json', filetypes=[('Setup', '*.json')])
        if not p:
            return
        try:
            self.cfg.write(p)
        except (OSError, ValueError) as e:
            log.exception('could not save %s', p)
            messagebox.showerror('Save setup', 'Could not save the setup:\n%s' % e, parent=self.root)
            return
        n = sum(len(v) for v in library.embed(self.cfg).values())
        self.say('saved %s%s' % (p, (' (with %d of your own parts inside)' % n) if n else ''))

    def export(self, kind):
        if self.job is not None:
            messagebox.showinfo('Export', 'An export is already running.', parent=self.root)
            return
        ext = '.mp4' if kind == 'video' else '.png'
        where = {'initialdir': setups_dir()} if FROZEN else {}     # the .exe: Documents\PC Airflow Lab
        p = filedialog.asksaveasfilename(title='Export ' + kind, defaultextension=ext, initialfile='airflow' + ext,
                                         filetypes=[('MP4 video', '*.mp4'), ('GIF', '*.gif')] if kind == 'video'
                                         else [('PNG image', '*.png')], **where)
        if not p:
            return
        if not p.lower().endswith(('.mp4', '.gif') if kind == 'video' else ('.png',)):
            p += ext                                 # e.g. "airflow v1.3" - the dialog saw ".3" as the extension
        self.start_export(kind, p)

    def start_export(self, kind, p):
        fd, tmp = tempfile.mkstemp(prefix='pcflow_export_', suffix='.json')
        os.close(fd)
        try:
            self.cfg.write(tmp)
        except (OSError, ValueError) as e:
            self._remove_tmp(tmp)
            log.exception('could not start the export')
            self.say('Could not start the export: %s' % e, seconds=12)
            return
        self.job_tmp = tmp
        # the setup carries its own parts: the export uses exactly what is on screen
        cmd, cwd = export_command(tmp, kind, p, self.v_vq.get())
        env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUNBUFFERED='1')
        group = ({'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW}
                 if sys.platform.startswith('win')          # no console window pops up
                 else {'start_new_session': True})          # so closing can stop ffmpeg too
        try:
            self.job = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                        encoding='utf-8', errors='replace', cwd=cwd, env=env, **group)
        except OSError as e:
            self._remove_tmp()
            self.say('Could not start the export: %s' % e, seconds=12)
            return
        self.job_path = p
        self.job_saved = None
        self.job_log = []
        self.job_started = time.time()

        def reader(proc, q):
            try:
                for line in proc.stdout:
                    q.put(line.rstrip())
            finally:
                q.put(None)
        threading.Thread(target=reader, args=(self.job, self.jobs), daemon=True).start()
        self.status.configure(text='exporting… (you can keep working)')

    def _remove_tmp(self, path=None):
        path = path or self.job_tmp
        if path:
            try:
                os.remove(path)
            except OSError:
                pass
        if path == self.job_tmp:
            self.job_tmp = None

    def poll_job(self):
        if self.job is None:
            return
        try:
            while True:
                line = self.jobs.get_nowait()
                if line is None:
                    self._export_done(self.job.wait())
                    return
                if line:
                    self.job_log = (self.job_log + [line])[-40:]
                    if line.startswith('saved '):
                        self.job_saved = line[len('saved '):]
                    self.status.configure(text='export: ' + line[-70:])
        except queue.Empty:
            pass

    def _export_done(self, code):
        out = self.job_saved or self.job_path
        self.job = None
        self._remove_tmp()
        ok = code == 0 and os.path.isfile(out) and os.path.getsize(out) > 0
        if not ok:
            log.warning('export failed (code %s): %s', code, ' | '.join(self.job_log[-10:]))
            self.say('export failed', 12)
            self.show_notes('Export failed', ['The export stopped (code %s). Its last messages:' % code]
                            + (self.job_log[-12:] or ['(none)']))
            return
        self.say('saved %s' % out, 12)
        if sys.platform.startswith('win'):
            try:
                os.startfile(os.path.dirname(out))
            except OSError:
                log.info('could not open the folder of %s', out)

    def _stop_job(self):
        """stop the export and everything it started (ffmpeg)"""
        p = self.job
        if p is None or p.poll() is not None:       # it may have finished while we were asking
            return
        try:
            if sys.platform.startswith('win'):
                taskkill = os.path.join(os.environ.get('SystemRoot', r'C:\Windows'), 'System32', 'taskkill.exe')
                subprocess.run([taskkill, '/F', '/T', '/PID', str(p.pid)], capture_output=True, timeout=10,
                               creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                os.killpg(p.pid, signal.SIGTERM)
        except (OSError, subprocess.SubprocessError):
            p.kill()
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()

    def close(self):
        if self.job is not None:
            if not messagebox.askyesno('Export running', 'A picture / video export is still running.\n'
                                       'Stop it and quit?', parent=self.root):
                return
        if self.job is not None and self.job.poll() is None:   # still running after the question
            self._stop_job()
            part = self.job_path
            for _ in range(10):               # a half-written video must not look like a finished one
                try:
                    if os.path.isfile(part) and os.path.getmtime(part) >= self.job_started - 1:
                        os.remove(part)
                    break
                except OSError:               # Windows: the file is free a moment after ffmpeg stops
                    time.sleep(0.2)
            else:
                log.warning('could not remove the unfinished export %s', part)
        self._remove_tmp()
        self.root.destroy()


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    log_path = setup_logging()
    notes = library.load()                     # your own parts first, so setups can use them
    cfg = None
    if argv:
        try:
            cfg = Config.read(argv[0])
        except (OSError, ValueError) as e:
            notes.append('Could not open %s (%s) - started with the default setup' % (argv[0], e))
    if sys.platform.startswith('win'):
        try:                                   # sharp text on high-DPI Windows screens
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
        try:                                   # the taskbar shows the app's own icon, not Python's
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('ElAmouri.PCAirflowLab')
        except (AttributeError, OSError):
            pass
    root = tk.Tk()
    fit_text_to_screen(root)
    app = App(root, cfg, notes)
    app.log_path = log_path
    root.mainloop()


if __name__ == '__main__':
    main()
