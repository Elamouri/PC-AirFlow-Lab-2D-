"""Simulation settings: what is in the case and how it is set up.  Saved / loaded as JSON.

Setup files are plain JSON and are only read as data.  Anything unknown or out of range is replaced
by a safe value and listed in Config.notes, so a damaged file never crashes the app.
"""
import json
import math
import os
import tempfile
from dataclasses import dataclass, field, asdict

from . import hardware as hw
from . import library
from .safejson import read_json

WALLS = ('front', 'top', 'rear', 'bottom', 'side', 'inside')
INSIDE_DIRS = ('up', 'down', 'left', 'right')
COOLER_ORIENTATIONS = ('to rear', 'to top', 'to front', 'to bottom')
LOADS = ('idle', 'gaming', 'max')
QUALITY_MM = {'fast': 4.0, 'normal': 3.0, 'high': 2.0}     # simulation cell size
PSU_FAN_MODES = ('bottom intake', 'from inside case', 'off (fanless)')
RAM_STICKS = (1, 2, 4)
FAN_CURVE_SOURCES = ('hottest', 'cpu', 'gpu')
DEFAULT_FAN_CURVE = dict(source='hottest', t_lo=50.0, pct_lo=30.0, t_hi=80.0, pct_hi=100.0)
MAX_FANS = 40
MAX_FILE_BYTES = 5_000_000
FILE_VERSION = 2


@dataclass
class Fan:
    """One case fan.

    wall      front | top | rear | bottom | side | inside
                bottom fans under the PSU shroud sit on top of the shroud and pull air
                through the floor vent; inside fans can go anywhere in the case
    pos_mm    centre of the fan:
                front / rear : height above the case floor
                top / bottom : distance from the rear wall
                side / inside: distance from the rear wall
    pos2_mm   side / inside fans: height above the floor
    direction in | out          (walls and side panel)
              up | down | left | right   (inside fans: where the air is blown)
    model     a key of hardware.ALL_FANS
    speed_pct 0 .. 100 % of the fan's maximum rpm, or -1 = auto (follows the fan curve)
              (JSON may give "rpm" instead)
    """
    wall: str = 'front'
    pos_mm: float = 250.0
    pos2_mm: float = 250.0
    direction: str = 'in'
    model: str = hw.DEFAULT_CASE_FAN
    speed_pct: float = 70.0

    @property
    def size(self):
        return hw.ALL_FANS[self.model]['size']

    @property
    def max_rpm(self):
        return hw.ALL_FANS[self.model]['rpm']

    @property
    def auto(self):
        return self.speed_pct < 0

    @property
    def rpm(self):
        """set speed in rpm (0 for an auto fan: its speed comes from the running simulation)"""
        return self.max_rpm * max(0.0, self.speed_pct) / 100.0

    def set_rpm(self, rpm):
        self.speed_pct = float(min(100.0, max(0.0, 100.0 * rpm / self.max_rpm)))

    def copy(self):
        return Fan(self.wall, self.pos_mm, self.pos2_mm, self.direction, self.model, self.speed_pct)


@dataclass
class Case:
    name: str = "Mid-tower 440 x 450 mm"
    depth_mm: float = 440.0          # rear wall -> front panel (inside)
    height_mm: float = 450.0         # floor -> top panel (inside)
    width_mm: float = 210.0          # side panel -> motherboard tray
    shroud: bool = True              # PSU shroud along the floor
    shroud_height_mm: float = 90.0
    shroud_length_mm: float = 340.0
    front_panel: str = "mesh + dust filter"
    top_panel: str = "mesh + dust filter"


@dataclass
class Config:
    case: Case = field(default_factory=Case)
    fans: list = field(default_factory=list)
    cpu: str = "AMD Ryzen 7 7800X3D"
    cpu_power_w: float = 0.0          # 0 = take it from the database for the chosen load
    cooler: str = "Single tower 120 mm (Hyper 212 / AK400 class)"
    cooler_fan_pct: float = -1.0      # -1 = automatic (follows the load)
    cooler_fan_model: str = ""        # "" = the cooler's own fan; any key of hardware.ALL_FANS
    cooler_fans: int = 0              # 0 = the cooler's normal count; tower: 1 = push, 2 = push-pull, 3 (dual tower)
    cooler_orientation: str = "to rear"   # which way the tower blows: to rear | to top | to front | to bottom
    aio_mount: str = "top"            # AIO radiator position: top | front
    aio_direction: str = "out"        # radiator fans: out (exhaust) | in (intake)
    gpu: str = "NVIDIA GeForce RTX 4070 Super"
    gpu_power_w: float = 0.0          # 0 = from the database
    gpu_fan_pct: float = -1.0         # -1 = automatic (card's own fan curve)
    gpu_length_mm: float = 0.0        # 0 = typical length from the database
    psu_watts: int = 750
    psu_rating: str = "80 PLUS Gold"
    psu_fan_mode: str = "bottom intake"
    psu_fan_pct: float = -1.0         # -1 = automatic (semi-passive)
    load: str = "gaming"              # idle | gaming | max
    room_c: float = 22.0
    quality: str = "normal"           # fast | normal | high
    motherboard: str = hw.DEFAULT_MOTHERBOARD
    ram_sticks: int = 2               # 1, 2 or 4 (Mini-ITX: 1 or 2)
    ram_type: str = "DDR5"            # DDR4 | DDR5
    ram_ecc: bool = False             # ECC sticks: extra memory chips, a little more power
    nvme_count: int = 1               # M.2 SSDs on the motherboard
    hdd_count: int = 0                # 3.5" hard drives in a cage under the PSU shroud
    filter_condition: str = "clean"   # clean | dusty | clogged dust filters
    altitude_m: float = 0.0           # height above sea level: thinner air carries less heat
    fan_curve: dict = field(default_factory=lambda: dict(DEFAULT_FAN_CURVE))   # for case fans set to auto

    def __post_init__(self):
        self.notes = []               # what was fixed while reading a file (not saved)
        self.info = []                # what the file brought along (its own parts), for the status line

    # ------------------------------------------------------------------ io
    def to_dict(self):
        d = asdict(self)
        d['version'] = FILE_VERSION
        parts = library.embed(self)
        if parts:
            d['custom_parts'] = parts
        return d

    def write(self, path):
        """save as JSON (written to a temporary file first, so a crash never leaves half a file)"""
        folder = os.path.dirname(os.path.abspath(path))
        fd, tmp = tempfile.mkstemp(prefix='.setup-', suffix='.tmp', dir=folder)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    @classmethod
    def from_dict(cls, d):
        if not isinstance(d, dict):
            raise ValueError('this is not a PC Airflow Lab setup')
        d = dict(d)                          # nested values are only read, never changed
        info = []
        notes = library.register_embedded(d.pop('custom_parts', None), used=library.referenced_parts(d, MAX_FANS),
                                          info=info)
        version = d.pop('version', FILE_VERSION)
        if not isinstance(version, int) or isinstance(version, bool) or version > FILE_VERSION:
            notes.append('This setup was saved by a newer version of the app - settings it does not know are ignored')
        known = set(cls.__dataclass_fields__) | {'cooler_fan_rpm', 'gpu_fan_rpm', 'psu_fan_rpm'}
        _unknown_note(notes, 'Unknown settings ignored', [k for k in d if k not in known])
        case_d = d.pop('case', {})
        if not isinstance(case_d, dict):
            notes.append('The case settings are unreadable - using the default case')
            case_d = {}
        _unknown_note(notes, 'Unknown case settings ignored', [k for k in case_d if k not in Case.__dataclass_fields__])
        case = Case(**{k: v for k, v in case_d.items() if k in Case.__dataclass_fields__})
        fans_d = d.pop('fans', [])
        if not isinstance(fans_d, list):
            notes.append('The fan list is unreadable - no case fans loaded')
            fans_d = []
        if len(fans_d) > MAX_FANS:
            notes.append('%d fans in the file - only the first %d are used' % (len(fans_d), MAX_FANS))
            fans_d = fans_d[:MAX_FANS]
        fans, rpm_of, odd = [], {}, set()
        for k, fd in enumerate(fans_d):
            if not isinstance(fd, dict):
                notes.append('Fan %d in the file is unreadable - skipped' % (k + 1))
                continue
            odd.update(kk for kk in fd if kk not in Fan.__dataclass_fields__ and kk != 'rpm')
            fan = Fan(**{kk: v for kk, v in fd.items() if kk in Fan.__dataclass_fields__})
            if 'rpm' in fd and 'speed_pct' not in fd:
                rpm_of[id(fan)] = fd['rpm']
            fans.append(fan)
        _unknown_note(notes, 'Unknown fan settings ignored', odd)
        if isinstance(d.get('fan_curve'), dict):
            _unknown_note(notes, 'Unknown fan curve settings ignored',
                          [k for k in d['fan_curve'] if k not in DEFAULT_FAN_CURVE])
        rpms = {k: d.pop(k) for k in ('cooler_fan_rpm', 'gpu_fan_rpm', 'psu_fan_rpm') if k in d}
        skip = ('case', 'fans')
        cfg = cls(case=case, fans=fans, **{k: v for k, v in d.items() if k in cls.__dataclass_fields__ and k not in skip})
        notes += cfg.validate()
        for k, fan in enumerate(cfg.fans):
            if id(fan) in rpm_of:
                pct = _rpm_to_pct(rpm_of[id(fan)], fan.max_rpm, 'Fan %d rpm' % (k + 1), notes)
                if pct is not None:
                    fan.speed_pct = pct
        maxima = {'cooler_fan_rpm': ('cooler_fan_pct', hw.ALL_FANS[cfg.cooler_fan_name()]['rpm']),
                  'gpu_fan_rpm': ('gpu_fan_pct', hw.GPU_FAN['rpm']), 'psu_fan_rpm': ('psu_fan_pct', hw.PSU_FAN['rpm'])}
        for key, raw in rpms.items():
            attr, mx = maxima[key]
            pct = _rpm_to_pct(raw, mx, key, notes)
            if pct is not None:
                setattr(cfg, attr, pct)
        cfg.notes = notes
        cfg.info = info
        return cfg

    @classmethod
    def read(cls, path):
        return cls.from_dict(read_json(path, MAX_FILE_BYTES))

    def copy(self):
        c = Config.from_dict(self.to_dict())
        c.notes = []
        return c

    # ------------------------------------------------------------------ helpers
    def cooler_fan_name(self):
        """the fan model really used on the CPU cooler / AIO radiator"""
        c = hw.COOLERS[self.cooler]
        name = self.cooler_fan_model
        if not name or name not in hw.ALL_FANS:
            return hw.stock_cooler_fan(self.cooler)
        if c['kind'] == 'aio' and hw.ALL_FANS[name]['size'] != c['fan_mm']:
            return hw.stock_cooler_fan(self.cooler)      # radiator holes only fit one size
        return name

    def n_cooler_fans(self):
        c = hw.COOLERS[self.cooler]
        if c['kind'] == 'aio':
            return c['fans']
        hi = 2 if c['stacks'] == 1 else 3
        return int(min(hi, max(1, self.cooler_fans))) if self.cooler_fans > 0 else hw.cooler_fan_count(self.cooler)

    def board(self):
        return hw.MOTHERBOARDS[self.motherboard]

    def ram_slots(self):
        return hw.BOARD_FORMS[self.board()['form']]['ram_slots']

    def apply_case_preset(self, name):
        """copy the sizes of a case from the case list (built-in or your own)"""
        p = hw.CASES[name]
        self.case.name = name
        for k in ('depth_mm', 'height_mm', 'width_mm', 'shroud', 'shroud_height_mm', 'shroud_length_mm'):
            setattr(self.case, k, p[k])

    # ------------------------------------------------------------------ checking
    def validate(self):
        """Fix unknown names / wrong types / out-of-range values; returns a list of what was changed."""
        notes = []

        def pick(value, options, default, label):
            if isinstance(value, str) and value in options:
                return value
            notes.append('%s "%s" is unknown, using "%s"' % (label, library.printable(value, 60), default))
            return default

        def num(value, default, lo, hi, label, integer=False):
            x = _finite(value)
            if x is None:
                notes.append('%s "%s" is not a number, using %s' % (label, library.printable(value, 30), default))
                return min(hi, max(lo, default))
            if integer and abs(x - round(x)) > 1e-9:
                notes.append('%s %s is not a whole number, using %d' % (label, x, round(x)))
                x = round(x)
            if x < lo or x > hi:
                y = min(hi, max(lo, x))
                notes.append('%s %g is out of range, using %g' % (label, x, y))
                x = y
            return int(round(x)) if integer else float(x)

        def flag(value, default, label):
            if isinstance(value, bool):
                return value
            notes.append('%s "%s" should be true or false, using %s' % (label, library.printable(value, 20), default))
            return default

        self.cpu = pick(self.cpu, hw.CPUS, "AMD Ryzen 7 7800X3D", 'CPU')
        self.gpu = pick(self.gpu, hw.GPUS, "NVIDIA GeForce RTX 4070 Super", 'GPU')
        self.cooler = pick(self.cooler, hw.COOLERS, "Single tower 120 mm (Hyper 212 / AK400 class)", 'Cooler')
        self.motherboard = pick(self.motherboard, hw.MOTHERBOARDS, hw.DEFAULT_MOTHERBOARD, 'Motherboard')
        self.psu_rating = pick(self.psu_rating, hw.PSU_RATINGS, "80 PLUS Gold", 'PSU rating')
        self.psu_fan_mode = pick(self.psu_fan_mode, PSU_FAN_MODES, "bottom intake", 'PSU fan mode')
        self.load = pick(self.load, LOADS, "gaming", 'Load')
        self.quality = pick(self.quality, QUALITY_MM, "normal", 'Quality')
        self.aio_mount = pick(self.aio_mount, ('top', 'front'), 'top', 'AIO mount')
        self.aio_direction = pick(self.aio_direction, ('in', 'out'), 'out', 'AIO direction')
        self.cooler_orientation = pick(self.cooler_orientation, COOLER_ORIENTATIONS, 'to rear', 'Cooler orientation')
        self.ram_type = pick(self.ram_type, hw.RAM_TYPES, 'DDR5', 'RAM type')
        self.filter_condition = pick(self.filter_condition, hw.FILTER_CONDITIONS, 'clean', 'Dust filters')
        if not isinstance(self.cooler_fan_model, str) or (self.cooler_fan_model and
                                                          self.cooler_fan_model not in hw.ALL_FANS):
            notes.append('Cooler fan "%s" is unknown, using the stock fan' % library.printable(self.cooler_fan_model))
            self.cooler_fan_model = ''
        self.cooler_fans = num(self.cooler_fans, 0, 0, 3, 'Cooler fans', integer=True)
        self.cpu_power_w = num(self.cpu_power_w, 0.0, 0, 1000, 'Own CPU watts')
        self.gpu_power_w = num(self.gpu_power_w, 0.0, 0, 1500, 'Own GPU watts')
        self.gpu_length_mm = num(self.gpu_length_mm, 0.0, 0, 450, 'GPU length')
        if 0 < self.gpu_length_mm < 120:
            notes.append('Card length %g mm is shorter than any graphics card - using the typical length'
                         % self.gpu_length_mm)
            self.gpu_length_mm = 0.0
        for attr, label in (('cooler_fan_pct', 'Cooler fan speed'), ('gpu_fan_pct', 'GPU fan speed'),
                            ('psu_fan_pct', 'PSU fan speed')):
            v = num(getattr(self, attr), -1.0, -1e9, 100, label)
            setattr(self, attr, -1.0 if v < 0 else v)
        self.psu_watts = num(self.psu_watts, 750, 200, 3000, 'PSU watts', integer=True)
        self.room_c = num(self.room_c, 22.0, 5, 45, 'Room temperature')
        self.altitude_m = num(self.altitude_m, 0.0, -500, 5000, 'Altitude')
        self.ram_ecc = flag(self.ram_ecc, False, 'ECC')
        self.nvme_count = num(self.nvme_count, 1, 0, hw.MAX_NVME, 'M.2 SSDs', integer=True)
        self.hdd_count = num(self.hdd_count, 0, 0, hw.MAX_HDD, 'Hard drives', integer=True)
        sticks = num(self.ram_sticks, 2, 1, 8, 'RAM sticks', integer=True)
        allowed = [n for n in RAM_STICKS if n <= self.ram_slots()]
        if sticks not in allowed:
            best = max([n for n in allowed if n <= sticks] or [allowed[0]])
            notes.append('%d RAM sticks do not fit this board (%d slots), using %d' % (sticks, self.ram_slots(), best))
            sticks = best
        self.ram_sticks = sticks
        self._validate_curve(notes, num, pick)
        # case
        cs = self.case
        if not isinstance(cs.name, str) or len(cs.name) > library.MAX_NAME or library.text_problem(cs.name):
            notes.append('The case name in the file is not usable - called "Custom case"')
            cs.name = 'Custom case'
        cs.front_panel = pick(cs.front_panel, hw.FRONT_PANELS, "mesh + dust filter", 'Front panel')
        cs.top_panel = pick(cs.top_panel, hw.TOP_PANELS, "mesh + dust filter", 'Top panel')
        cs.depth_mm = num(cs.depth_mm, 440.0, 300, 700, 'Case depth')
        cs.height_mm = num(cs.height_mm, 450.0, 300, 700, 'Case height')
        cs.width_mm = num(cs.width_mm, 210.0, 150, 320, 'Case width')
        cs.shroud = flag(cs.shroud, True, 'PSU shroud')
        cs.shroud_height_mm = num(cs.shroud_height_mm, 90.0, 80, 130, 'Shroud height')
        cs.shroud_length_mm = num(cs.shroud_length_mm, 340.0, 170, cs.depth_mm - 40, 'Shroud length')
        # fans
        good = []
        for k, f in enumerate(self.fans):
            if not isinstance(f, Fan):
                notes.append('Fan %d is unreadable - removed' % (k + 1))
                continue
            f.wall = pick(f.wall, WALLS, 'front', 'Fan %d wall' % (k + 1))
            f.model = pick(f.model, hw.ALL_FANS, hw.DEFAULT_CASE_FAN, 'Fan %d model' % (k + 1))
            if f.wall == 'inside':
                if f.direction not in INSIDE_DIRS:
                    notes.append('Fan %d inside the case had direction "%s" - set to blow up'
                                 % (k + 1, library.printable(f.direction, 10)))
                    f.direction = 'up'
            else:
                f.direction = pick(f.direction, ('in', 'out'), 'in', 'Fan %d direction' % (k + 1))
            v = num(f.speed_pct, 70.0, -1e9, 100, 'Fan %d speed' % (k + 1))
            f.speed_pct = -1.0 if v < 0 else v
            f.pos_mm = num(f.pos_mm, 250.0, 0, 1000, 'Fan %d position' % (k + 1))
            f.pos2_mm = num(f.pos2_mm, 250.0, 0, 1000, 'Fan %d height' % (k + 1))
            good.append(f)
        if len(good) > MAX_FANS:
            notes.append('%d fans - only the first %d are used' % (len(good), MAX_FANS))
        self.fans = good[:MAX_FANS]
        return notes

    def _validate_curve(self, notes, num, pick):
        c = self.fan_curve
        if not isinstance(c, dict):
            notes.append('The fan curve is unreadable - using the standard curve')
            c = {}
        full = dict(DEFAULT_FAN_CURVE)
        full.update({k: v for k, v in c.items() if k in DEFAULT_FAN_CURVE})
        out = dict(source=pick(full['source'], FAN_CURVE_SOURCES, 'hottest', 'Fan curve source'))
        out['t_lo'] = num(full['t_lo'], 50.0, 20, 95, 'Fan curve low temperature')
        out['t_hi'] = num(full['t_hi'], 80.0, 25, 110, 'Fan curve high temperature')
        if out['t_hi'] < out['t_lo'] + 5:
            notes.append('Fan curve: the high temperature must be at least 5 °C above the low one - fixed')
            out['t_hi'] = min(110.0, out['t_lo'] + 30.0)
        out['pct_lo'] = num(full['pct_lo'], 30.0, 0, 100, 'Fan curve low speed')
        out['pct_hi'] = num(full['pct_hi'], 100.0, out['pct_lo'], 100, 'Fan curve high speed')
        self.fan_curve = out


def _finite(value):
    """float(value) if it is a real, finite number (bools and text that is not a number -> None)"""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        x = float(value)
    except (ValueError, OverflowError):
        return None
    return x if math.isfinite(x) else None


def _unknown_note(notes, what, keys):
    keys = sorted(library.printable(k, 30) for k in keys)
    if keys:
        notes.append('%s: %s%s' % (what, ', '.join(keys[:8]), ' ...' if len(keys) > 8 else ''))


def _rpm_to_pct(raw, max_rpm, label, notes):
    """speed % from an rpm value in a file: negative = auto (-1), above the maximum = 100 %"""
    rpm = _finite(raw)
    if rpm is None:
        notes.append('%s "%s" is not a number - ignored' % (label, library.printable(raw, 30)))
        return None
    if rpm < 0:
        notes.append('%s %g is negative - set to auto' % (label, rpm))
        return -1.0
    if rpm > max_rpm:
        notes.append("%s %g is above the fan's maximum %d rpm - using full speed" % (label, rpm, max_rpm))
    return min(100.0, 100.0 * rpm / max_rpm)


# ---------------------------------------------------------------------- ready-made setups
def my_pc():
    """3 x 120 front intake, 3 x 120 top exhaust, 1 x 120 rear exhaust, PSU fan pulling from the bottom."""
    f = hw.DEFAULT_CASE_FAN
    fans = [Fan('front', 130, 0, 'in', f, 70), Fan('front', 250, 0, 'in', f, 70), Fan('front', 370, 0, 'in', f, 70),
            Fan('top', 100, 0, 'out', f, 70), Fan('top', 220, 0, 'out', f, 70), Fan('top', 340, 0, 'out', f, 70),
            Fan('rear', 342, 0, 'out', f, 70)]
    return Config(fans=fans)


def positive_pressure():
    """Same fans as my_pc, but the front-most top fan blows IN: 4 in / 3 out."""
    cfg = my_pc()
    for fan in cfg.fans:
        if fan.wall == 'top' and fan.pos_mm > 300:
            fan.direction = 'in'
    return cfg


def classic_two_in_two_out():
    f = hw.DEFAULT_CASE_FAN
    fans = [Fan('front', 190, 0, 'in', f, 70), Fan('front', 310, 0, 'in', f, 70),
            Fan('top', 100, 0, 'out', f, 70), Fan('rear', 342, 0, 'out', f, 70)]
    return Config(fans=fans)


def aio_top():
    cfg = my_pc()
    cfg.fans = [fan for fan in cfg.fans if fan.wall != 'top']
    cfg.cooler = "AIO liquid 360 mm"
    cfg.aio_mount, cfg.aio_direction = 'top', 'out'
    return cfg


PRESETS = {
    "My PC: 3 front in, 3 top out, 1 rear out": my_pc,
    "Front-most top fan as intake (positive pressure)": positive_pressure,
    "Classic 2 in / 2 out": classic_two_in_two_out,
    "360 mm AIO on top, 3 front in, rear out": aio_top,
}
