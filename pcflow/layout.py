"""Turn a Config into simulation geometry.

Coordinates are millimetres in a side view through the glass panel:
x = 0 at the REAR wall (left) ... x = depth at the FRONT panel (right)
y = 0 at the case FLOOR       ... y = height at the TOP panel

Parts in the airflow plane (GPU, cooler, radiator, PSU, drive cage, shroud, fans) are also kept as
boxes in millimetres, so "does a fan fit here?" has the same answer at every simulation detail level.
"""
import math

import numpy as np

from . import hardware as hw
from .config import QUALITY_MM
from .thermal import compute_loads, RHO_SEA

FLUID, SOLID, AMB = 0, 1, 2
FAN_T = 26.0                 # fan + mount thickness (mm)
FRAME = 4.0                  # solid fan frame at each edge of a fan opening
PSU_BOX = (0.0, 150.0, 0.0, 86.0)
PSU_FAN_SPAN = (15.0, 135.0)
MMH2O = 9.80665              # Pa per mm of water
CFM = 2118.88                # CFM per m^3/s
RHO = RHO_SEA
TOUCH = 1.0                  # parts may touch (overlap up to this many mm) without counting as a clash
WALL_TOUCH = 2.0             # same along a wall

K_CROSS = 3000.0             # porous resistances (1/s)
K_REAR = 25.0
K_BOTTOM = 80.0
K_FINS_CPU = 250.0
K_RAD = 180.0
K_GPU_FINS = 300.0
K_BLOCK = 20000.0
K_PSU = 60.0
K_HDD = 2500.0               # a drive fills ~70 % of the case width: air squeezes round it
H_FIN, H_RAD, H_PSU, H_BOARD = 45.0, 60.0, 30.0, 1.5   # heat-transfer rates (1/s)
H_RAM, H_HDD = 6.0, 8.0
HDD_PITCH, HDD_THICK, HDD_CAGE_W = 28.0, 26.0, 110.0
DIMM_W = 4.5


class FanSpec:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def fan_profile(s, R, r):
    """depth-averaged blade-annulus width at distance s from the fan axis"""
    s = np.abs(s)
    return 2 * np.sqrt(np.clip(R * R - s * s, 0, None)) - 2 * np.sqrt(np.clip(r * r - s * s, 0, None))


def hub_radius(size):
    """fan hub radius (mm): 20 mm for 120 mm fans, 23 mm for 140 mm, in proportion for other sizes"""
    return min(20.0 if size <= 120 else 23.0, 0.17 * size)


def operating_velocity(n_series, pmax, ufree, k_len, rho=RHO):
    """through-flow of n fans in series pushing through a porous block (Pa per m/s = rho*K*L)"""
    if pmax <= 0 or ufree <= 0:
        return 0.0
    return n_series * pmax / (n_series * pmax / ufree + rho * k_len)


def boxes_clash(a, b, tol=TOUCH):
    w = min(a[1], b[1]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[2], b[2])
    return w > tol and h > tol, max(w, 0.0) * max(h, 0.0)


class Layout:
    def __init__(self, cfg, h_mm=None, skip=()):
        """skip = indexes of case fans to leave out (used to test where a fan could go)"""
        self.cfg = cfg
        self.skip = set(skip)
        self.h_mm = float(h_mm if h_mm else QUALITY_MM[cfg.quality])
        self.h = self.h_mm * 1e-3
        cs = cfg.case
        self.NXI = int(round(cs.depth_mm / self.h_mm))
        self.NYI = int(round(cs.height_mm / self.h_mm))
        # geometry is placed in true millimetres (the grid covers the case to within half a cell)
        self.D = float(cs.depth_mm)
        self.H = float(cs.height_mm)
        self.NX, self.NY = self.NXI + 2, self.NYI + 2
        self.W = cs.width_mm * 1e-3
        self.room = float(cfg.room_c)
        self.loads = compute_loads(cfg)
        self.rho_ratio = self.loads['rho_ratio']
        self.rho = RHO * self.rho_ratio
        self.warnings = list(self.loads['warnings'])
        self.ct = np.full((self.NY, self.NX), SOLID, np.int8)
        self.ct[1:-1, 1:-1] = FLUID
        self.Kx = np.zeros((self.NY, self.NX))
        self.Ky = np.zeros((self.NY, self.NX))
        self.band_mask = np.zeros((self.NY, self.NX), bool)
        self.heat, self.fans, self.sides, self.openings = [], [], [], []
        self.parts = []              # (name, (x0, x1, y0, y1)) in the airflow plane, mm
        self.probes = {}
        self.draw = {'wall_fans': [], 'side_fans': [], 'inside_fans': [], 'rejected': [], 'hdd': None}
        self.occupied = {'front': [], 'top': [], 'rear': [], 'bottom': []}
        self._heat_masks = []
        self._orphan_heat = 0.0
        self.cooler_ref_q = 0.0
        self.gpu_ref_q = 0.0
        self.hdd_per_drive = 0.0
        self._build()

    # ------------------------------------------------------------------ index helpers
    def ci(self, mm):
        return int(np.floor(mm / self.h_mm + 0.5)) + 1

    def cells(self, x0, x1, y0, y1):
        i0, i1, j0, j1 = self.ci(x0), self.ci(x1), self.ci(y0), self.ci(y1)
        i1 = max(i1, i0 + 1)
        j1 = max(j1, j0 + 1)
        return slice(max(j0, 1), min(j1, self.NY - 1)), slice(max(i0, 1), min(i1, self.NX - 1))

    def mask(self, x0, x1, y0, y1):
        m = np.zeros((self.NY, self.NX), bool)
        m[self.cells(x0, x1, y0, y1)] = True
        return m

    def ring(self, lo, hi, n):
        a, b = self.ci(lo + FRAME), self.ci(hi - FRAME)
        return np.arange(max(a, 1), min(max(b, a + 1), n - 1))

    def fan_faces(self, axis, band, span):
        n_ax = self.NX if axis == 'x' else self.NY
        n_sp = self.NY if axis == 'x' else self.NX
        ax_idx = np.arange(max(self.ci(band[0]) + 1, 1), min(self.ci(band[1]), n_ax - 1))
        if len(ax_idx) == 0:
            ax_idx = np.array([min(max(self.ci(band[0]), 1), n_ax - 2)])
        sp_idx = np.arange(max(self.ci(span[0]), 1), min(max(self.ci(span[1]), self.ci(span[0]) + 1), n_sp - 1))
        sc = (sp_idx - 1 + 0.5) * self.h_mm
        if axis == 'x':
            F = sp_idx[:, None] * (self.NX + 1) + ax_idx[None, :]
        else:
            F = ax_idx[None, :] * self.NX + sp_idx[:, None]
        return F, sc

    @staticmethod
    def box_of(axis, band, span):
        return (band[0], band[1], span[0], span[1]) if axis == 'x' else (span[0], span[1], band[0], band[1])

    def wall_length(self, wall):
        return self.H if wall in ('front', 'rear') else self.D

    # ------------------------------------------------------------------ fans
    def _fan_params(self, cfm, mmh2o, frac, size_mm):
        """free-air speed (m/s) and shut-off pressure (Pa) of a fan at a speed fraction.
        Fan laws: airflow ~ rpm, pressure ~ rpm^2 x air density."""
        ufree = cfm * frac / CFM / (size_mm * 1e-3 * self.W)
        pmax = mmh2o * MMH2O * frac * frac * self.rho_ratio
        return ufree, pmax

    def _add_fan(self, kind, label, wall, axis, sign, band, span, cfm, mmh2o, frac, size, hub, rpm100,
                 direction, opening=None, index=None, model='', auto=False):
        ufree, pmax = self._fan_params(cfm, mmh2o, frac, size)
        F, sc = self.fan_faces(axis, band, span)
        w = fan_profile(sc - 0.5 * (span[0] + span[1]), size / 2.0 - 2.0, hub)
        mean = float(w.mean()) if len(w) else 0.0
        w = w / mean if mean > 1e-6 else np.ones_like(w)
        bm = self.mask(*self.box_of(axis, band, span))
        self.band_mask |= bm
        spec = FanSpec(kind=kind, label=label, wall=wall, axis=axis, sign=sign, band=band, span=span,
                       ufree=ufree, pmax=pmax, active=frac > 0.01, F=F, w=w, n_ax=F.shape[1], size=size,
                       rpm=rpm100 * frac, rpm100=rpm100, cfm100=cfm, mmh2o100=mmh2o, direction=direction,
                       frac=frac, index=index, q=0.0, model=model, auto=auto, cells=np.nonzero(bm.ravel())[0])
        self.fans.append(spec)
        if opening is not None:
            self.openings.append(dict(owner=label, kind=kind, wall=wall, cells=opening, fan=spec))
        return spec

    def set_fan_frac(self, f, frac):
        """change a fan's speed without rebuilding the layout (auto fans)"""
        if not math.isfinite(frac):
            return
        frac = float(min(1.0, max(0.0, frac)))
        f.ufree, f.pmax = self._fan_params(f.cfm100, f.mmh2o100, frac, f.size)
        f.frac, f.rpm, f.active = frac, f.rpm100 * frac, frac > 0.01

    def set_side_frac(self, sd, frac):
        if not math.isfinite(frac):
            return
        frac = float(min(1.0, max(0.0, frac)))
        sd['Qfree'] = sd['cfm100'] * frac / CFM * 0.85
        sd['pmax'] = sd['mmh2o100'] * MMH2O * frac * frac * self.rho_ratio
        sd['frac'], sd['rpm'] = frac, sd['rpm100'] * frac

    def _open_wall(self, wall, lo, hi):
        if wall == 'front':
            rows = self.ring(lo, hi, self.NY)
            self.ct[rows, self.NX - 1] = AMB
            return rows
        if wall == 'rear':
            rows = self.ring(lo, hi, self.NY)
            self.ct[rows, 0] = AMB
            return rows
        if wall == 'top':
            cols = self.ring(lo, hi, self.NX)
            self.ct[self.NY - 1, cols] = AMB
            return cols
        cols = self.ring(lo, hi, self.NX)
        self.ct[0, cols] = AMB
        return cols

    # ------------------------------------------------------------------ where can a fan go?
    def _overlaps(self, wall, lo, hi):
        for item in self.occupied[wall]:
            a, b = item[0], item[1]
            if min(hi, b) - max(lo, a) > WALL_TOUCH:
                return item[2] if len(item) > 2 else 'another part'
        return None

    def blocked_by(self, box):
        """name of the part a box would sit on (the biggest overlap), None if it is free"""
        best, area = None, 0.0
        for name, other in self.parts:
            clash, a = boxes_clash(box, other)
            if clash and a > area:
                best, area = name, a
        return best

    def wall_slot(self, wall, p, s):
        """where a wall fan of size s centred p mm along the wall sits"""
        lo, hi = p - s / 2.0, p + s / 2.0
        on_shroud = False
        if wall == 'front':
            band, axis = (self.D - FAN_T, self.D), 'x'
        elif wall == 'rear':
            band, axis = (0.0, FAN_T), 'x'
        elif wall == 'top':
            band, axis = (self.H - FAN_T, self.H), 'y'
        else:
            axis = 'y'
            if self.cfg.case.shroud and p < self.sl:
                # the fan sits on top of the PSU shroud and breathes through the floor vent below it
                on_shroud = True
                band = (self.sh, self.sh + FAN_T)
            else:
                band = (0.0, FAN_T)
        return dict(band=band, axis=axis, span=(lo, hi), box=self.box_of(axis, band, (lo, hi)), on_shroud=on_shroud)

    def clip_wall(self, wall, p, s):
        """a wall fan is kept on its panel, like the layout does when it builds the fan"""
        length = self.wall_length(wall)
        return float(np.clip(p, s / 2.0, max(s / 2.0, length - s / 2.0)))

    def why_wall(self, wall, p, s):
        """None if a fan fits here (after keeping it on the panel), else what is in the way"""
        p = self.clip_wall(wall, p, s)
        if s > self.wall_length(wall):
            return 'the edge of the %s panel' % wall
        what = self._overlaps(wall, p - s / 2.0, p + s / 2.0)
        return what or self.blocked_by(self.wall_slot(wall, p, s)['box'])

    def inside_slot(self, s, d, x, y):
        if d in ('up', 'down'):
            axis, sign = 'y', (+1 if d == 'up' else -1)
            cx = float(np.clip(x, s / 2 + 1, self.D - s / 2 - 1))
            cy = float(np.clip(y, FAN_T / 2 + 1, self.H - FAN_T / 2 - 1))
            band, span = (cy - FAN_T / 2, cy + FAN_T / 2), (cx - s / 2, cx + s / 2)
        else:
            axis, sign = 'x', (+1 if d == 'right' else -1)
            cx = float(np.clip(x, FAN_T / 2 + 1, self.D - FAN_T / 2 - 1))
            cy = float(np.clip(y, s / 2 + 1, self.H - s / 2 - 1))
            band, span = (cx - FAN_T / 2, cx + FAN_T / 2), (cy - s / 2, cy + s / 2)
        return dict(axis=axis, sign=sign, band=band, span=span, box=self.box_of(axis, band, span), centre=(cx, cy))

    def why_inside(self, s, d, x, y):
        return self.blocked_by(self.inside_slot(s, d, x, y)['box'])

    def side_centre(self, s, x, y):
        return float(np.clip(x, s / 2, self.D - s / 2)), float(np.clip(y, s / 2, self.H - s / 2))

    def why_side(self, s, x, y):
        cx, cy = self.side_centre(s, x, y)
        for sd in self.sides:
            if math.hypot(cx - sd['centre'][0], cy - sd['centre'][1]) < s / 2 + sd['r'] - WALL_TOUCH:
                return '%s on the side panel' % sd['label']
        return None

    # ------------------------------------------------------------------ build
    def _build(self):
        cfg, cs = self.cfg, self.cfg.case
        if cs.shroud:
            self.sh, self.sl = cs.shroud_height_mm, cs.shroud_length_mm
            self.ct[self.cells(0, self.sl, self.sh - 2, self.sh)] = SOLID
            self.draw['shroud'] = (0.0, self.sl, self.sh - 2, self.sh)
            self.parts.append(('the PSU shroud', self.draw['shroud']))
        else:
            self.sh, self.sl = 0.0, 0.0
            self.draw['shroud'] = None
        self.draw['shroud_vents'] = []
        bt = self.H - 25.0
        self._build_board(bt)
        self._build_psu()
        self._build_storage()
        self._build_gpu()
        self._build_cooler()
        self._build_ram()
        for k, fan in enumerate(cfg.fans):
            if k not in self.skip:
                self._build_case_fan(k, fan)
        self._build_board_heat()
        self._finish()

    def _build_board(self, bt):
        mb = hw.MOTHERBOARDS[self.cfg.motherboard]
        form = hw.BOARD_FORMS[mb['form']]
        x1 = form['w']
        if x1 > self.D - FAN_T - 6.0:
            x1 = self.D - FAN_T - 6.0
            self.warnings.append('A %s board (%.0f mm deep) is too big for this case - check that it fits'
                                 % (mb['form'], form['w']))
        self.board = (0.0, x1, bt - form['h'], bt)
        self.socket = (form['socket'][0], bt - form['socket'][1])
        self.gpu_top_y = bt - form['gpu_from_top']
        self.draw['board'] = self.board
        self.draw['board_form'] = mb['form']
        y0, y1 = bt - form['ram_y'][1], bt - form['ram_y'][0]
        n = form['ram_slots']
        self.draw['ram'] = [(form['ram_x'] + 7.5 * k, form['ram_x'] + 7.5 * k + DIMM_W, y0, y1) for k in range(n)]
        sticks = min(int(self.cfg.ram_sticks), n)
        if sticks >= n:
            used = set(range(n))
        elif n == 4:
            used = {1} if sticks == 1 else {1, 3}        # A2 / B2 first, like the board manuals say
        else:
            used = {0}
        self.draw['ram_used'] = [k in used for k in range(n)]

    def _build_psu(self):
        cfg, L = self.cfg, self.loads
        x0, x1, y0, y1 = PSU_BOX
        mode = cfg.psu_fan_mode
        self.ct[self.cells(x0, x1, y1 - 2, y1)] = SOLID
        self.ct[self.cells(x1 - 2, x1, y0, y1 - 2)] = SOLID
        inner = self.mask(x0, x1 - 2, y0, y1 - 2)
        if mode == 'from inside case':
            band = (y1 - 2 - 16.0, y1 - 2)
            a, b = PSU_FAN_SPAN[0] + FRAME, PSU_FAN_SPAN[1] - FRAME     # fan grille, frame stays solid
            self.ct[self.cells(a, b, y1 - 2, y1)] = FLUID
            if self.cfg.case.shroud:      # vented shroud above a fan-up PSU
                self.ct[self.cells(a, b, y1, self.sh)] = FLUID
                self.draw['shroud_vents'].append((a, b))
        else:
            band = (0.0, 16.0)
        hm = inner & ~self.mask(x0, x1, band[0], band[1])
        self.Kx[inner] = K_PSU
        self.Ky[inner] = K_PSU
        if mode != 'from inside case':        # the floor dust filter in front of the PSU fan
            self.Ky[self.cells(x0, x1 - 2, band[0], band[1])] += \
                (hw.FILTER_CONDITIONS[cfg.filter_condition] - 1.0) * hw.BOTTOM_FILTER
        self._add_heat('psu', hm, H_PSU, L['p_psu'])
        rows = self._open_wall('rear', 4.0, y1 - 4.0)
        self.openings.append(dict(owner='PSU', kind='psu', wall='rear', cells=rows, fan=None))
        f = L['f_psu']
        spec = hw.PSU_FAN
        if mode != 'from inside case':
            cols = self._open_wall('bottom', *PSU_FAN_SPAN)
            self.openings.append(dict(owner='PSU', kind='psu', wall='bottom', cells=cols, fan=None))
        if f > 0.01:
            sign = +1 if mode != 'from inside case' else -1
            self._add_fan('psu', 'PSU fan', 'psu', 'y', sign, band, PSU_FAN_SPAN, spec['cfm'], spec['mmh2o'],
                          f, spec['size'], 20.0, spec['rpm'], 'in')
        else:
            self.band_mask |= self.mask(PSU_FAN_SPAN[0], PSU_FAN_SPAN[1], band[0], band[1])
        self.draw['psu'] = dict(box=PSU_BOX, fan_span=PSU_FAN_SPAN, band=band, mode=mode, frac=f)
        self.occupied['bottom'].append((x0, x1, 'the PSU'))
        self.occupied['rear'].append((0.0, y1 + 6, 'the PSU'))
        self.parts.append(('the PSU', PSU_BOX))

    def _build_storage(self):
        """3.5" hard drives: a cage at the front of the PSU basement (or on the floor at the front)"""
        n = int(self.cfg.hdd_count)
        if n <= 0:
            return
        cs = self.cfg.case
        psu_end = PSU_BOX[1] + 20.0                      # room for the PSU cables
        x0 = x1 = None
        if cs.shroud and self.sl - 6.0 - HDD_CAGE_W >= psu_end:
            fit = int((self.sh - 6.0) // HDD_PITCH)
            if fit >= 1:
                x1 = self.sl - 6.0
                x0 = x1 - HDD_CAGE_W
                if n > fit:
                    self.warnings.append('Only %d hard drive%s fit under this shroud - the others are left out'
                                         % (fit, '' if fit == 1 else 's'))
                    n = fit
        if x0 is None:
            x1 = self.D - FAN_T - 8.0
            x0 = x1 - HDD_CAGE_W
            if cs.shroud and x0 < self.sl + 2.0:
                x0 = self.sl + 2.0
                x1 = x0 + HDD_CAGE_W
            if x0 < psu_end or x1 > self.D - FAN_T - 4.0:
                self.warnings.append('There is no room for a hard-drive cage in this case - drives left out')
                self._orphan_heat += self.loads['p_hdd']
                return
        cage = (x0, x1, 0.0, n * HDD_PITCH + 4.0)
        drives = [(x0 + 4.0, x1 - 4.0, 2.0 + k * HDD_PITCH, 2.0 + k * HDD_PITCH + HDD_THICK) for k in range(n)]
        m = np.zeros((self.NY, self.NX), bool)
        for d in drives:
            sl_ = self.cells(*d)
            self.Kx[sl_] = K_HDD
            self.Ky[sl_] = K_HDD
            m |= self.mask(*d)
        p_all = self.loads['p_hdd']
        P = p_all * n / max(1, int(self.cfg.hdd_count))
        self._orphan_heat += p_all - P                   # drives that did not fit: their heat still counts
        self.hdd_per_drive = P / n
        self._add_heat('hdd', m, H_HDD, P)
        self.parts.append(('the hard-drive cage', cage))
        self.occupied['bottom'].append((x0, x1, 'the hard-drive cage'))
        self.draw['hdd'] = dict(cage=cage, drives=drives, under_shroud=bool(cs.shroud and x1 <= self.sl))

    def _build_gpu(self):
        cfg, cs, L = self.cfg, self.cfg.case, self.loads
        g = hw.GPUS[cfg.gpu]
        length = max(120.0, cfg.gpu_length_mm if cfg.gpu_length_mm > 0 else g['length'])
        top = self.gpu_top_y
        bottom = top - 20.0 * g['slots']
        min_bottom = (self.sh + 12.0) if cs.shroud else 25.0
        if bottom < min_bottom:
            self.warnings.append('GPU is too thick for the space above the shroud - drawn thinner')
            bottom = min_bottom
        if top - bottom < 20.0:
            self.warnings.append('This case is too short for the motherboard and graphics card - the card is '
                                 'drawn higher than it would really sit')
            top = bottom + 20.0
        x0 = 2.0
        x1 = x0 + length
        front_limit = self.D - FAN_T - 10.0
        if hw.COOLERS[cfg.cooler]['kind'] == 'aio' and cfg.aio_mount == 'front':
            front_limit -= 27.0
        if x1 > front_limit:
            self.warnings.append('A %.0f mm GPU does not fit this case (max ~%.0f mm) - shortened' % (length, front_limit - x0))
            x1 = front_limit
        band = (bottom, bottom + 14.0)
        caps = self.cells(x0, x1, band[1], top)
        self.Kx[caps] = K_BLOCK
        self.Ky[caps] = K_BLOCK
        fins = (x0 + 2.0, x1 - 2.0, band[1], top)
        fs = self.cells(*fins)
        self.Kx[fs] = K_BLOCK
        self.Ky[fs] = K_GPU_FINS
        bs = self.cells(x0, x1, band[0], band[1])
        self.Kx[bs] = K_CROSS
        self.Ky[bs] = K_CROSS
        nf = max(1, int(g['fans']))
        fd = 90.0 if nf >= 3 else 95.0
        centres = x0 + (x1 - x0) * (np.arange(nf) + 0.5) / nf
        fd = max(20.0, min(fd, (x1 - x0) / nf - 4.0))
        spans = [(c - fd / 2, c + fd / 2) for c in centres]
        f = L['f_gpu']
        hub = min(16.0, 0.17 * fd)
        for k, sp in enumerate(spans):
            self.Ky[self.cells(sp[0], sp[1], band[0], band[1])] = 10.0
            if f > 0.01:
                self._add_fan('gpu', 'GPU fan %d' % (k + 1), 'gpu', 'y', +1, band, sp, hw.GPU_FAN['cfm'],
                              hw.GPU_FAN['mmh2o'], f, fd, hub, hw.GPU_FAN['rpm'], 'in')
        self.band_mask |= self.mask(x0, x1, band[0], band[1])
        self._add_heat('gpu', self.mask(*fins), H_FIN, L['p_gpu'])
        jb = self.ci(band[0])
        cols = np.concatenate([np.arange(self.ci(a), self.ci(b)) for a, b in spans])
        self.probes['gpu_in'] = ('v', jb * self.NX + cols, +1, (jb - 1) * self.NX + cols)
        u70, p70 = self._fan_params(hw.GPU_FAN['cfm'], hw.GPU_FAN['mmh2o'], 0.70, fd)
        self.gpu_ref_q = operating_velocity(1, p70, u70, K_GPU_FINS * (top - band[1]) * 1e-3, self.rho)
        self.gpu_box = (x0, x1, bottom, top)
        self.draw['gpu'] = dict(box=self.gpu_box, band=band, fans=spans, fins=fins, backplate=(top - 5.0, top),
                                name=cfg.gpu, length=x1 - x0)
        self.occupied['rear'].append((bottom - 8.0, top + 14.0, 'the GPU bracket'))
        self.parts.append(('the GPU', self.gpu_box))

    # ------------------------------------------------------------------ CPU cooler
    def _build_cooler(self):
        cfg = self.cfg
        c = hw.COOLERS[cfg.cooler]
        fan_name = cfg.cooler_fan_name()
        spec = hw.ALL_FANS[fan_name]
        if c['kind'] == 'tower':
            self._build_tower(c, fan_name, spec)
        else:
            self._build_aio(c, fan_name, spec)

    def _build_tower(self, c, fan_name, spec):
        cfg, L = self.cfg, self.loads
        sx, sy = self.socket
        f = L['f_cooler']
        fm = spec['size']
        n_st, d, hs = c['stacks'], c['stack_depth'], c['stack_height']
        nf = cfg.n_cooler_fans()
        orient = cfg.cooler_orientation
        FT = 25.0
        if n_st == 1:
            seq = ['F', 'S'] if nf == 1 else ['F', 'S', 'F']
        else:
            seq = {1: ['S', 'F', 'S'], 2: ['F', 'S', 'F', 'S'], 3: ['F', 'S', 'F', 'S', 'F']}[nf]
        lens = [FT if e == 'F' else d for e in seq]
        total = sum(lens)
        gpu_top = self.gpu_box[3]
        top_lim = self.H - FAN_T - 8.0
        room = (self.D - FAN_T - 12.0) - (FAN_T + 8.0) if orient in ('to rear', 'to front') else \
            top_lim - (gpu_top + 12.0)
        if total > room:                     # keep the whole cooler inside the case
            scale = max(room, 40.0) / total
            lens = [ln * scale for ln in lens]
            total = sum(lens)
            self.warnings.append('This CPU cooler does not fit the space in this case - it is drawn (and simulated) '
                                 'smaller')
        if orient in ('to rear', 'to front'):
            axis = 'x'
            ytop = min(sy + 18.0 + hs / 2, top_lim)
            ybot = ytop - hs
            if ybot < gpu_top + 12.0:
                ybot = gpu_top + 12.0
                self.warnings.append('CPU cooler is very close to the GPU in this case')
            yc = 0.5 * (ybot + ytop)
            cross_st, cross_fan = (ybot, ytop), (yc - fm / 2, yc + fm / 2)
            lo_lim, hi_lim = FAN_T + 8.0, self.D - FAN_T - 12.0
            start = sx - total / 2
            start = min(max(start, lo_lim), hi_lim - total)
            sign = -1 if orient == 'to rear' else +1
        else:
            axis = 'y'
            xc = max(sx, FAN_T + 10.0 + max(hs, fm) / 2)
            cross_st, cross_fan = (xc - hs / 2, xc + hs / 2), (xc - fm / 2, xc + fm / 2)
            lo_lim, hi_lim = gpu_top + 12.0, top_lim
            start = sy + 10.0 - total / 2
            if total > hi_lim - lo_lim:
                self.warnings.append('This cooler / fan set-up is taller than the space between GPU and top fans')
            start = max(min(start, hi_lim - total), lo_lim)
            sign = +1 if orient == 'to top' else -1
        # lay the parts out from the intake side
        parts = []
        if sign < 0:
            pos = start + total
            for e, ln in zip(seq, lens):
                parts.append((e, (pos - ln, pos)))
                pos -= ln
        else:
            pos = start
            for e, ln in zip(seq, lens):
                parts.append((e, (pos, pos + ln)))
                pos += ln
        heat = np.zeros((self.NY, self.NX), bool)
        stacks, fans = [], []
        k = 0
        for e, (a, b) in parts:
            if e == 'S':
                box = self.box_of(axis, (a, b), cross_st)
                sl_ = self.cells(*box)
                self.Kx[sl_] = K_FINS_CPU
                self.Ky[sl_] = K_FINS_CPU
                heat |= self.mask(*box)
                stacks.append(box)
            else:
                k += 1
                box = self.box_of(axis, (a, b), cross_fan)
                sl_ = self.cells(*box)
                if axis == 'x':
                    self.Kx[sl_], self.Ky[sl_] = 10.0, K_CROSS
                else:
                    self.Kx[sl_], self.Ky[sl_] = K_CROSS, 10.0
                if f > 0.01:
                    self._add_fan('cooler', 'Cooler fan %d' % k, 'cooler', axis, sign, (a, b), cross_fan, spec['cfm'],
                                  spec['mmh2o'], f, fm, hub_radius(fm), spec['rpm'], 'in', model=fan_name)
                else:
                    self.band_mask |= self.mask(*box)
                fans.append((axis, (a, b), cross_fan))
            self.parts.append(('the CPU cooler', box))
        self._add_heat('cpu', heat, H_FIN, L['p_cpu'])
        # intake face of the first part (indices kept on the grid)
        first, (a, b) = parts[0]
        cross = cross_fan if first == 'F' else cross_st
        NX, NY = self.NX, self.NY
        if axis == 'x':
            rows = np.clip(np.arange(self.ci(cross[0]), self.ci(cross[1])), 1, NY - 2)
            if sign < 0:
                i = int(np.clip(self.ci(b), 1, NX - 2))
                self.probes['cpu_in'] = ('u', rows * (NX + 1) + i, -1, rows * NX + i)
            else:
                i = int(np.clip(self.ci(a), 2, NX - 1))
                self.probes['cpu_in'] = ('u', rows * (NX + 1) + i, +1, rows * NX + (i - 1))
        else:
            cols = np.clip(np.arange(self.ci(cross[0]), self.ci(cross[1])), 1, NX - 2)
            if sign > 0:
                j = int(np.clip(self.ci(a), 2, NY - 1))
                self.probes['cpu_in'] = ('v', j * NX + cols, +1, (j - 1) * NX + cols)
            else:
                j = int(np.clip(self.ci(b), 1, NY - 2))
                self.probes['cpu_in'] = ('v', j * NX + cols, -1, j * NX + cols)
        st = hw.COOLER_FAN[c['fan_mm']]
        u100, p100 = self._fan_params(st['cfm'], st['mmh2o'], 1.0, c['fan_mm'])
        # stock fans at full speed; 1.25 = case fans helping, calibrated against the full simulation
        self.cooler_ref_q = 1.25 * operating_velocity(hw.cooler_fan_count(cfg.cooler), p100, u100,
                                                      K_FINS_CPU * n_st * d * 1e-3, self.rho)
        pipes = []
        for (x0, x1, y0, y1) in stacks:
            if axis == 'x':
                pipes += [(x0 + (x1 - x0) * q, y) for q in (0.25, 0.5, 0.75) for y in (y0 + 14.0, y1 - 14.0)]
            else:
                pipes += [(x, y0 + (y1 - y0) * q) for q in (0.25, 0.5, 0.75) for x in (x0 + 14.0, x1 - 14.0)]
        self.draw['cooler'] = dict(kind='tower', stacks=stacks, fans=fans, heatpipes=pipes, name=cfg.cooler,
                                   axis=axis, sign=sign, fan_model=fan_name)
        self.cooler_top = max(bx[3] for bx in stacks)

    def _build_aio(self, c, fan_name, spec):
        cfg, L = self.cfg, self.loads
        sx, sy = self.socket
        f = L['f_cooler']
        fm = c['fan_mm']
        n = c['fans']
        tank = 18.0
        mount, direction = cfg.aio_mount, cfg.aio_direction
        fans_draw = []
        low_front = 8.0
        if mount == 'top':
            room_len = self.D - 30.0 - 5.0
        else:
            reach_front = self.cfg.case.shroud and self.sl > self.D - FAN_T - 27.0 - 8.0
            low_front = (self.sh + 5.0) if reach_front else 8.0
            room_len = self.H - 20.0 - low_front
        n0 = n
        while n > 1 and n * fm + 2 * tank > room_len:
            n -= 1
        if n < n0:
            self.warnings.append('The %d-fan radiator does not fit on the %s of this case - simulated with %d fan%s'
                                 % (n0, mount, n, '' if n == 1 else 's'))
        core = n * fm
        hub = hub_radius(fm)
        if mount == 'top':
            x0 = 40.0
            if x0 + core + 2 * tank > self.D - 30.0:
                x0 = max(5.0, self.D - 30.0 - core - 2 * tank)
            band = (self.H - FAN_T, self.H)
            rad = (x0 + tank, x0 + tank + core, self.H - FAN_T - 27.0, self.H - FAN_T)
            self.Kx[self.cells(*rad)] = 5000.0
            self.Ky[self.cells(*rad)] = K_RAD
            sign = +1 if direction == 'out' else -1
            k_panel = self._panel_k('top')
            for k in range(n):
                sp = (rad[0] + k * fm, rad[0] + (k + 1) * fm)
                sl_ = self.cells(sp[0], sp[1], band[0], band[1])
                self.Kx[sl_] = K_CROSS
                self.Ky[sl_] = k_panel
                cols = self._open_wall('top', *sp)
                lab = 'AIO fan %d' % (k + 1)
                if f > 0.01:
                    self._add_fan('aio', lab, 'top', 'y', sign, band, sp, spec['cfm'], spec['mmh2o'],
                                  f, fm, hub, spec['rpm'], direction, opening=cols, model=fan_name)
                else:
                    self.openings.append(dict(owner=lab, kind='aio', wall='top', cells=cols, fan=None))
                fans_draw.append(dict(wall='top', band=band, span=sp, direction=direction, kind='aio', size=fm,
                                      label=lab, auto=False))
                self.parts.append((lab, self.box_of('y', band, sp)))
            self.occupied['top'].append((x0, x0 + core + 2 * tank, 'the radiator'))
            if direction == 'out':
                j = self.ci(rad[2])
                cols = np.arange(self.ci(rad[0]), self.ci(rad[1]))
                self.probes['cpu_in'] = ('v', j * self.NX + cols, +1, (j - 1) * self.NX + cols)
            box = (x0, x0 + core + 2 * tank, rad[2], rad[3])
        else:
            ytop = self.H - 20.0
            y0 = max(low_front, ytop - core - 2 * tank)
            band = (self.D - FAN_T, self.D)
            rad = (self.D - FAN_T - 27.0, self.D - FAN_T, y0 + tank, y0 + tank + core)
            self.Kx[self.cells(*rad)] = K_RAD
            self.Ky[self.cells(*rad)] = 5000.0
            sign = -1 if direction == 'in' else +1
            k_panel = self._panel_k('front')
            for k in range(n):
                sp = (rad[2] + k * fm, rad[2] + (k + 1) * fm)
                sl_ = self.cells(band[0], band[1], sp[0], sp[1])
                self.Kx[sl_] = k_panel
                self.Ky[sl_] = K_CROSS
                rows = self._open_wall('front', *sp)
                lab = 'AIO fan %d' % (k + 1)
                if f > 0.01:
                    self._add_fan('aio', lab, 'front', 'x', sign, band, sp, spec['cfm'], spec['mmh2o'],
                                  f, fm, hub, spec['rpm'], direction, opening=rows, model=fan_name)
                else:
                    self.openings.append(dict(owner=lab, kind='aio', wall='front', cells=rows, fan=None))
                fans_draw.append(dict(wall='front', band=band, span=sp, direction=direction, kind='aio', size=fm,
                                      label=lab, auto=False))
                self.parts.append((lab, self.box_of('x', band, sp)))
            self.occupied['front'].append((y0, y0 + core + 2 * tank, 'the radiator'))
            if direction == 'out':
                i = self.ci(rad[0])
                rows = np.arange(self.ci(rad[2]), self.ci(rad[3]))
                self.probes['cpu_in'] = ('u', rows * (self.NX + 1) + i, +1, rows * self.NX + (i - 1))
            box = (rad[0], rad[1], y0, y0 + core + 2 * tank)
        self._add_heat('cpu', self.mask(*rad), H_RAD, L['p_cpu'])
        st = hw.AIO_FAN[fm]
        u100, p100 = self._fan_params(st['cfm'], st['mmh2o'], 1.0, fm)
        self.cooler_ref_q = 0.79 * operating_velocity(1, p100, u100, K_RAD * 0.027, self.rho)   # calibrated
        self.draw['wall_fans'] += fans_draw
        self.draw['cooler'] = dict(kind='aio', mount=mount, radiator=rad, box=box, tank=tank,
                                   pump=(sx - 30.0, sx + 30.0, sy - 30.0, sy + 30.0), name=cfg.cooler,
                                   fan_model=fan_name)
        self.parts.append(('the radiator', box))
        self.cooler_top = sy + 30.0

    def _build_ram(self):
        """memory sticks stand out of the board next to the cooler: their heat goes into that air"""
        m = np.zeros((self.NY, self.NX), bool)
        for r, used in zip(self.draw['ram'], self.draw['ram_used']):
            if used:
                m |= self.mask(*r)
        self._add_heat('ram', m, H_RAM, self.loads['p_ram'])

    # ------------------------------------------------------------------ case fans
    def _panel_k(self, wall):
        cs, cond = self.cfg.case, self.cfg.filter_condition
        if wall == 'front':
            return hw.panel_resistance(hw.FRONT_PANELS, hw.FRONT_FILTER, cs.front_panel, cond)
        if wall == 'top':
            return hw.panel_resistance(hw.TOP_PANELS, hw.TOP_FILTER, cs.top_panel, cond)
        if wall == 'bottom':
            return K_BOTTOM + (hw.FILTER_CONDITIONS[cond] - 1.0) * hw.BOTTOM_FILTER
        return K_REAR

    def _build_case_fan(self, k, fan):
        s = float(fan.size)
        label = 'Fan %d' % (k + 1)
        spec = hw.ALL_FANS[fan.model]
        auto = fan.auto
        frac = self.loads['f_auto'] if auto else fan.speed_pct / 100.0
        wall, d = fan.wall, fan.direction
        if wall == 'side':
            self._build_side_fan(k, fan, spec, frac, label, auto)
            return
        if wall == 'inside':
            self._build_inside_fan(k, fan, spec, frac, label, auto)
            return
        p = self.clip_wall(wall, float(fan.pos_mm), s)
        if abs(p - float(fan.pos_mm)) > 0.01:
            self.warnings.append('%s did not fit on the %s - moved to %.0f mm' % (label, wall, p))
        slot = self.wall_slot(wall, p, s)
        lo, hi = slot['span']
        why = self.why_wall(wall, p, s)
        if why:
            self._reject(slot['box'], label, k, why)
            if why == 'the radiator':
                self.warnings.append('%s sits where the radiator fans are - the radiator fans are used instead' % label)
            else:
                self.warnings.append('%s overlaps %s on the %s - left out' % (label, why, wall))
            return
        band, axis = slot['band'], slot['axis']
        sign = {'front': -1, 'rear': +1, 'top': -1, 'bottom': +1}[wall] * (1 if d == 'in' else -1)
        kax = self._panel_k(wall)
        sl_ = self.cells(*slot['box'])
        if slot['on_shroud']:
            self.ct[self.cells(lo + FRAME, hi - FRAME, self.sh - 2, self.sh)] = FLUID
            self.draw['shroud_vents'].append((lo + FRAME, hi - FRAME))
        if axis == 'x':
            self.Kx[sl_], self.Ky[sl_] = kax, K_CROSS
        else:
            self.Kx[sl_], self.Ky[sl_] = K_CROSS, kax
        opening = self._open_wall(wall, lo, hi)
        self._add_fan('case', label, wall, axis, sign, band, (lo, hi), spec['cfm'], spec['mmh2o'], frac, s,
                      hub_radius(s), spec['rpm'], d, opening=opening, index=k, model=fan.model, auto=auto)
        self.occupied[wall].append((lo, hi, label))
        self.parts.append((label, slot['box']))
        self.draw['wall_fans'].append(dict(wall=wall, band=band, span=(lo, hi), direction=d, kind='case', size=s,
                                           label=label, on_shroud=slot['on_shroud'], auto=auto))

    def _build_side_fan(self, k, fan, spec, frac, label, auto):
        s = float(fan.size)
        d = fan.direction
        cx, cy = self.side_centre(s, fan.pos_mm, fan.pos2_mm)
        box = (cx - s / 2, cx + s / 2, cy - s / 2, cy + s / 2)
        why = self.why_side(s, cx, cy)
        if why:
            self._reject(box, label, k, why)
            self.warnings.append('%s overlaps %s - left out' % (label, why))
            return
        jj, ii = np.mgrid[0:self.NY, 0:self.NX]
        xc = (ii - 1 + 0.5) * self.h_mm
        yc = (jj - 1 + 0.5) * self.h_mm
        m = ((xc - cx) ** 2 + (yc - cy) ** 2 <= (s / 2) ** 2) & (self.ct == FLUID)
        if m.sum() < 4:
            self._reject(box, label, k, 'a solid part')
            self.warnings.append('%s (side) sits on a solid part - left out' % label)
            return
        sd = dict(label=label, index=k, mask=m, direction=d, centre=(cx, cy), r=s / 2, size=s, Q=0.0, auto=auto,
                  rpm100=spec['rpm'], cfm100=spec['cfm'], mmh2o100=spec['mmh2o'])
        self.set_side_frac(sd, frac)
        self.sides.append(sd)
        self.draw['side_fans'].append(dict(centre=(cx, cy), r=s / 2, direction=d, label=label, auto=auto))

    def _build_inside_fan(self, k, fan, spec, frac, label, auto):
        s = float(fan.size)
        d = fan.direction
        slot = self.inside_slot(s, d, fan.pos_mm, fan.pos2_mm)
        box = slot['box']
        why = self.blocked_by(box)
        if why:
            self._reject(box, label, k, why)
            self.warnings.append('%s would sit in %s - move it a little' % (label, why))
            return
        axis, band, span = slot['axis'], slot['band'], slot['span']
        sl_ = self.cells(*box)
        if axis == 'x':
            self.Kx[sl_], self.Ky[sl_] = 10.0, K_CROSS
        else:
            self.Kx[sl_], self.Ky[sl_] = K_CROSS, 10.0
        self._add_fan('case', label, 'inside', axis, slot['sign'], band, span, spec['cfm'], spec['mmh2o'], frac, s,
                      hub_radius(s), spec['rpm'], d, index=k, model=fan.model, auto=auto)
        self.parts.append((label, box))
        self.draw['inside_fans'].append(dict(axis=axis, band=band, span=span, direction=d, label=label, size=s,
                                             centre=slot['centre'], auto=auto))

    def _reject(self, box, label, index, why):
        self.draw['rejected'].append(dict(box=box, label=label, index=index, why=why))

    # ------------------------------------------------------------------ heat
    def _add_heat(self, name, m, H, P):
        m = m & (self.ct == FLUID)
        for other in self._heat_masks:
            m &= ~other
        if not m.any():                    # no free cells left for it: the heat goes to the board area
            self._orphan_heat += float(P)
            if name != 'board' and P > 0.05:
                what = {'ram': 'The RAM sits under the CPU cooler', 'hdd': 'The hard drives are covered',
                        'gpu': 'The graphics card is covered', 'cpu': 'The CPU cooler is covered',
                        'psu': 'The PSU is covered'}.get(name, name)
                self.warnings.append('%s - its %.0f W of heat is added to the board area instead' % (what, P))
            return
        self._heat_masks.append(m)
        self.heat.append(dict(name=name, mask=m, H=H, P=float(P)))

    def _build_board_heat(self):
        """chipset, CPU power stage, M.2 SSDs and fan motors warm the air in front of the board"""
        x0, x1, y0, y1 = self.board
        ld = self.loads
        P = ld['p_board'] + ld['p_nvme'] + ld['p_fans'] + self._orphan_heat
        m = self.mask(x0, x1, max(y0, self.sh + 2), y1) & (self.Kx == 0) & (self.Ky == 0) & (self.ct == FLUID)
        for other in self._heat_masks:
            m &= ~other
        if not m.any():
            m = (self.ct == FLUID) & (self.Kx == 0) & (self.Ky == 0)
            for other in self._heat_masks:
                m &= ~other
        self._orphan_heat = 0.0
        self._add_heat('board', m, H_BOARD, P)

    # ------------------------------------------------------------------ indices for the solver / probes
    def _finish(self):
        NX, NY = self.NX, self.NY
        for op in self.openings:
            c = op['cells']
            w = op['wall']
            if w == 'front':
                op.update(arr='u', faces=c * (NX + 1) + (NX - 1), out_sign=+1, tin=c * NX + (NX - 2))
            elif w == 'rear':
                op.update(arr='u', faces=c * (NX + 1) + 1, out_sign=-1, tin=c * NX + 1)
            elif w == 'top':
                op.update(arr='v', faces=(NY - 1) * NX + c, out_sign=+1, tin=(NY - 2) * NX + c)
            else:
                op.update(arr='v', faces=1 * NX + c, out_sign=-1, tin=1 * NX + c)
        for hsrc in self.heat:
            hsrc['idx'] = np.nonzero(hsrc['mask'].ravel())[0]
        for sd in self.sides:
            sd['idx'] = np.nonzero(sd['mask'].ravel())[0]
        moving = [f for f in self.fans if f.kind in ('case', 'aio') and f.wall != 'inside']
        self.n_in = sum(1 for f in moving if f.direction == 'in') + sum(1 for s in self.sides if s['direction'] == 'in')
        self.n_out = sum(1 for f in moving if f.direction == 'out') + \
            sum(1 for s in self.sides if s['direction'] == 'out')
        self.n_inside = sum(1 for f in self.fans if f.wall == 'inside')
        self.n_auto = sum(1 for f in self.fans if getattr(f, 'auto', False)) + sum(1 for s in self.sides if s['auto'])
