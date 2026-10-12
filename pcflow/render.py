"""Drawing: the case view (used by the app and the video) and the portrait video / report frame."""
import numpy as np
from matplotlib.axis import Axis
from matplotlib.collections import LineCollection, PolyCollection, PatchCollection
from matplotlib.lines import Line2D
from matplotlib.colors import to_rgba
from matplotlib.patches import Rectangle, Circle, FancyBboxPatch, FancyArrow, Polygon
from matplotlib.spines import Spine
import matplotlib.pyplot as plt
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from PIL import Image

from . import branding
from . import hardware as _hw


def hw_fan_size(name):
    return _hw.ALL_FANS[name]['size'] if name in _hw.ALL_FANS else 120

VMIN, VMAX = 22.0, 42.0
BG = '#0a0e17'
PANEL = '#121827'
EDGE = '#2a3247'
TXT = '#e9edf5'
SUB = '#9aa3b5'
COOL = '#5ac8fa'
HOT = '#ff6b5a'
ACC_CREDIT = '#5ac8fa'                 # the 'Powered by' line under every picture / video frame
CMAP = plt.get_cmap('jet')
LUT32 = np.ascontiguousarray((CMAP(np.linspace(0, 1, 256)) * 255 + 0.5).astype(np.uint8)).view(np.uint32).ravel()
DASH_SHADES = 6                        # flow dashes fade in and out in this many steps
HEAT = '#ff9f5a'                       # outline of a block that gives off heat
BLOCK_STYLE = {                        # how much air gets through: solid ... mesh
    'solid':  dict(fc=to_rgba('#596276', 0.95), ec='#dfe6f2', hatch='////'),
    'dense':  dict(fc=to_rgba('#3a4152', 0.90), ec='#c9d1e0', hatch=None),
    'cables': dict(fc=to_rgba('#2b303c', 0.55), ec='#aab3c5', hatch='\\\\'),
    'mesh':   dict(fc='none', ec='#aab3c5', hatch='++'),
}
HANDLE_MM = 9.0                        # the triangle in a block's top-right corner: drag it to resize the block


_BT = np.linspace(0, 1, 7)
_BLADE_R = np.concatenate([0.30 + 0.63 * _BT, (0.30 + 0.63 * _BT)[::-1]])      # radius / fan radius
_BLADE_A = np.concatenate([0.55 * _BT, (0.38 + 0.75 * _BT)[::-1]])             # angle along the blade


def fan_blades(cx, cy, r, rot, n=7):
    """n curved blades of a fan icon, as an (n, 14, 2) array of polygon corners"""
    a = rot + 2 * np.pi * np.arange(n)[:, None] / n + _BLADE_A[None, :]
    return np.stack([cx + r * _BLADE_R * np.cos(a), cy + r * _BLADE_R * np.sin(a)], axis=-1)


def view_limits(L):
    bottom_icons = any(f['wall'] == 'bottom' for f in L.draw['wall_fans']) or L.draw['psu']['mode'] == 'bottom intake'
    return (-82.0, L.D + 82.0), (-(100.0 if bottom_icons else 44.0), L.H + 96.0)


class CaseView:
    """Draws one case layout on a matplotlib Axes and animates it."""

    def __init__(self, ax, layout, fs=1.0, dashes=800):
        self.ax, self.L, self.fs = ax, layout, fs
        self.n_dash = dashes
        L = layout
        xl, yl = view_limits(L)
        ax.set_facecolor(BG)
        ax.set_xlim(*xl)
        ax.set_ylim(*yl)
        ax.set_aspect('equal', adjustable='box')
        ax.axis('off')
        self.img = ax.imshow(np.full((L.NYI, L.NXI), L.room), origin='lower', cmap=CMAP, vmin=VMIN, vmax=VMAX,
                             interpolation='bilinear', extent=[0, L.D, 0, L.H], zorder=1)
        self.edge_fans = []
        self.edge_src = []                         # where each spinning fan gets its speed from
        self.icons = []
        self.icon_text = []
        self._static()
        self.dash_lines = []                       # flow dashes, grouped by how faded they are: one path each
        for j in range(DASH_SHADES):              # (square ends: at this width they look the same and draw quicker)
            line = Line2D([], [], color=(0, 0, 0, 0.78 * (j + 0.5) / DASH_SHADES), lw=1.15 * fs, zorder=4,
                          solid_capstyle='butt')
            ax.add_line(line)
            self.dash_lines.append(line)
        self.blade_lc = LineCollection([], colors='#c9d1e0', linewidths=1.0 * fs, alpha=0.75, zorder=6.5)
        ax.add_collection(self.blade_lc)
        self.blades = PolyCollection([], facecolors='#8f99ad', edgecolors='#b9c1d1', linewidths=0.4, zorder=9)
        ax.add_collection(self.blades)
        hubs = [Circle((cx, cy), 0.28 * r) for cx, cy, r, _ in self.icons]
        ax.add_collection(PatchCollection(hubs, facecolor='#c3cad8', edgecolor='#e8ecf3', linewidth=0.5, zorder=10))
        self._labels()
        self.T_last = None
        self.key = drawing_key(layout)
        # what changes from frame to frame (everything else is drawn once by LiveFrames)
        self.dynamic_below = [self.img] + self.dash_lines
        self.dynamic_mid = [self.blade_lc, self.blades]
        self.dynamic_texts = ([self.t_cpu, self.t_gpu] + [t for _, t in self.t_icons] + [self.t_psu]
                              + [t for t in (self.t_hdd, self.t_psu_in) if t is not None]
                              + [t for _, t in self.t_blocks])
        self.dynamic_top = [self.ghost, self.ghost_box]

    def retarget(self, layout):
        """use this drawing for a new layout that looks the same (only speeds, loads or temperatures changed)"""
        fans = {f.label: f.frac for f in layout.fans}

        def frac(src, old):
            if src[0] == 'psu':
                return layout.draw['psu'].get('frac', old)
            if src[0] == 'loads':
                return layout.loads.get(src[1], old)
            return fans.get(src[1], old)
        self.edge_fans = [e[:5] + (frac(src, e[5]),) for e, src in zip(self.edge_fans, self.edge_src)]
        self.L = layout

    def _edge(self, entry, src):
        self.edge_fans.append(entry)
        self.edge_src.append(src)

    # ------------------------------------------------------------------ static parts
    # parts are added with add_artist, not add_patch: the view limits are fixed, so matplotlib does not need
    # to measure every shape for autoscaling (that made building the view twice as slow)
    def _rect(self, x0, x1, y0, y1, **kw):
        self.ax.add_artist(Rectangle((x0, y0), x1 - x0, y1 - y0, **kw))

    def _static(self):
        ax, L, fs = self.ax, self.L, self.fs
        D, H, t = L.D, L.H, 6.0
        wall = dict(fc='#4a5265', ec='none', zorder=5)
        for x0, y0, w, h in ((-t, -t, t, H + 2 * t), (D, -t, t, H + 2 * t), (-t, H, D + 2 * t, t), (-t, -t, D + 2 * t, t)):
            ax.add_artist(Rectangle((x0, y0), w, h, **wall))
        mesh_lines = []
        for op in L.openings:
            c = op['cells']
            if len(c) == 0:
                continue
            lo = (c[0] - 1) * L.h_mm
            hi = (c[-1]) * L.h_mm
            w = op['wall']
            if w in ('front', 'rear'):
                x0 = D if w == 'front' else -t
                self._rect(x0, x0 + t, lo, hi, fc='#1d2230', ec='none', zorder=5.1)
                mesh_lines += [[(x0 + 1, yy), (x0 + t - 1, yy)] for yy in np.arange(lo + 2.5, hi, 5.0)]
            else:
                y0 = H if w == 'top' else -t
                self._rect(lo, hi, y0, y0 + t, fc='#1d2230', ec='none', zorder=5.1)
                mesh_lines += [[(xx, y0 + 1), (xx, y0 + t - 1)] for xx in np.arange(lo + 2.5, hi, 5.0)]
        ax.add_collection(LineCollection(mesh_lines, colors='#6b7385', linewidths=0.5, zorder=5.2))
        self._rect(-t, D + t, -t, H + t, fill=False, ec='#8c95a8', lw=1.1, zorder=5.3)
        for xf in (30.0, D - 60.0):
            ax.add_artist(FancyBboxPatch((xf, -t - 9), 30, 8, boxstyle='round,pad=0,rounding_size=3',
                                        fc='#2a303d', ec='#5c6579', lw=0.6, zorder=5))
        ylo = ax.get_ylim()[0]
        ax.text(-44, ylo + 12, 'REAR', color=SUB, fontsize=9.5 * fs, ha='center', va='center', fontweight='bold')
        ax.text(D + 44, ylo + 12, 'FRONT', color=SUB, fontsize=9.5 * fs, ha='center', va='center', fontweight='bold')

        # PCIe slot covers on the rear wall
        g = L.draw['gpu']
        for k in range(7):
            yy = g['box'][3] + 2 - k * 20.3
            if yy - 7 < (L.sh + 2 if L.cfg.case.shroud else 92):
                break
            self._rect(-t + 1, -1, yy - 7, yy + 7, fc='#5c6579', ec='#8c95a8', lw=0.4, zorder=5.2)

        # shroud + PSU
        if L.draw['shroud']:
            x0, x1, y0, y1 = L.draw['shroud']
            self._rect(x0, x1, y0, y1, fc='#2a303d', ec='#7d869a', lw=0.9, zorder=5)
            hdd = L.draw.get('hdd')
            right = hdd['cage'][0] if (hdd and hdd['under_shroud']) else x1
            if right - 150 > 110:
                ax.text(0.5 * (right + 150), 0.5 * y0, 'PSU shroud area', color='#7d869a', fontsize=8 * fs,
                        ha='center', va='center', zorder=5.5)
            for a, b in L.draw.get('shroud_vents', []):
                self._rect(a, b, y0 - 0.5, y1 + 0.5, fc='#151a25', ec='#7d869a', lw=0.6, ls=(0, (2, 2)), zorder=5.2)
        p = L.draw['psu']
        x0, x1, y0, y1 = p['box']
        self._rect(x0, x1, y0, y1, fc='#262b36', alpha=0.55, ec='#9aa3b5', lw=1.0, zorder=5)
        ax.text(0.5 * (x0 + x1), 0.62 * y1, 'PSU', color='#c9d1e0', fontsize=9 * fs, ha='center', va='center',
                zorder=12, fontweight='bold')
        b0, b1 = p['band']
        s0, s1 = p['fan_span']
        self._rect(s0, s1, b0, b1, fc='#2f3646', alpha=0.6, ec='#aab3c5', lw=0.7, zorder=5.5)
        self._edge(('y', (b0, b1), 0.5 * (s0 + s1), 40.0, 20.0, p['frac']), ('psu',))
        self._rect(-t, 0, y0 + 4, y1 - 4, fc='#1d2230', ec='none', zorder=5.15)
        ax.add_artist(FancyArrow(-3, 0.5 * y1, -50, 0, width=4, head_width=12, head_length=8,
                                length_includes_head=True, fc='#ff9f5a', ec='none', alpha=0.9, zorder=11))
        if p['mode'] == 'bottom intake':
            self.icons.append((0.5 * (s0 + s1), -64.0, 26.0, +1))
            ax.add_artist(FancyArrow(0.5 * (s0 + s1), -96, 0, 84, width=6, head_width=17, head_length=11,
                                    length_includes_head=True, fc=COOL, ec='#0b2a3a', lw=0.6, zorder=11))

        # motherboard + RAM, behind the airflow plane
        dash = dict(fill=False, ec='#dfe6f2', lw=0.8, ls=(0, (4, 3)), alpha=0.55, zorder=3)
        bx0, bx1, by0, by1 = L.draw['board']
        self._rect(bx0 + 1, bx1, max(by0, L.sh + 2), by1, **dash)
        ax.text(bx0 + 8, max(by0, L.sh + 2) + 9, '%s motherboard (behind)' % L.draw.get('board_form', ''),
                color='#e6ebf5', alpha=0.85, fontsize=7.5 * fs, va='center', zorder=3)
        for r, used in zip(L.draw['ram'], L.draw.get('ram_used', [True] * len(L.draw['ram']))):
            if used:
                self._rect(*r, fc='#9fd3ff', alpha=0.30, ec='#dfe6f2', lw=0.8, zorder=3)
            else:
                self._rect(*r, **dash)
        if any(L.draw.get('ram_used', [])):
            r0 = L.draw['ram'][0]
            ax.text(0.5 * (r0[0] + L.draw['ram'][-1][1]), r0[3] - 6, 'RAM', color='#e6ebf5', alpha=0.85,
                    fontsize=6.5 * fs, ha='center', va='top', rotation=90, zorder=3)

        # hard-drive cage
        hdd = L.draw.get('hdd')
        if hdd:
            x0, x1, y0, y1 = hdd['cage']
            self._rect(x0, x1, y0, y1, fill=False, ec='#aab3c5', lw=0.9, zorder=5)
            for (a, b, c0, c1) in hdd['drives']:
                self._rect(a, b, c0, c1, fc='#3a4152', alpha=0.85, ec='#c9d1e0', lw=0.6, zorder=5.2)
            ax.text(0.5 * (x0 + x1), 0.5 * (y0 + y1), 'HDD ×%d' % len(hdd['drives']), color='#e6ebf5',
                    fontsize=7.5 * fs, ha='center', va='center', zorder=12, fontweight='bold')

        # CPU cooler
        c = L.draw['cooler']
        if c['kind'] == 'tower':
            for (a, b, y0, y1) in c['stacks']:
                self._rect(a, b, y0, y1, fc='#ffffff', alpha=0.07, ec='none', zorder=2)
                self._rect(a, b, y0, y1, fill=False, ec='#e6ebf5', lw=1.3, zorder=6)
            ax.add_collection(PatchCollection([Circle(pp, 3.4) for pp in c['heatpipes']], facecolor='#c8783c',
                                              edgecolor='#ffd2a8', linewidth=0.6, zorder=6))
            boxes = list(c['stacks'])
            fsz = hw_fan_size(c.get('fan_model'))
            for axis, band, span in c['fans']:
                bx_ = (band[0], band[1], span[0], span[1]) if axis == 'x' else (span[0], span[1], band[0], band[1])
                boxes.append(bx_)
                self._rect(*bx_, fc='#2f3646', alpha=0.45, ec='#aab3c5', lw=0.9, zorder=5)
                self._edge((axis, band, 0.5 * (span[0] + span[1]), fsz / 3.0, fsz / 6.0, L.loads['f_cooler']),
                           ('loads', 'f_cooler'))
            ybot = min(b_[2] for b_ in boxes)
            xs = 0.5 * (min(b_[0] for b_ in boxes) + max(b_[1] for b_ in boxes))
            ly = ybot - 11
            if c['axis'] == 'y':                      # rotated cooler: label beside it, not on the GPU
                xs, ly = max(b_[1] for b_ in boxes) + 40, ybot + 12
            ax.text(xs, ly, 'CPU cooler', color='white', fontsize=8.5 * fs, ha='center', va='center', zorder=12,
                    fontweight='bold', bbox=dict(boxstyle='round,pad=0.2', fc='#000000', ec='none', alpha=0.45))
            ex, ey = self._flow_arrow(c)
            ax.add_artist(FancyArrow(ex[0], ey[0], ex[1] - ex[0], ey[1] - ey[0], width=3.0, head_width=9,
                                    head_length=7, length_includes_head=True, fc='#ffffff', ec='none', alpha=0.75,
                                    zorder=7))
            st0 = c['stacks'][0]
            self.cpu_label_xy = (0.5 * (st0[0] + st0[1]), 0.5 * (st0[2] + st0[3]))
        else:
            x0, x1, y0, y1 = c['radiator']
            bx = c['box']
            self._rect(bx[0], bx[1], bx[2], bx[3], fc='#3a4152', alpha=0.35, ec='#c9d1e0', lw=1.0, zorder=5.5)
            self._rect(x0, x1, y0, y1, fill=False, ec='#e6ebf5', lw=1.0, zorder=6)
            if c['mount'] == 'top':
                segs = [[(xx, y0 + 1), (xx, y1 - 1)] for xx in np.arange(x0 + 2, x1, 3.0)]
            else:
                segs = [[(x0 + 1, yy), (x1 - 1, yy)] for yy in np.arange(y0 + 2, y1, 3.0)]
            ax.add_collection(LineCollection(segs, colors='#d8efff', linewidths=0.4, alpha=0.35, zorder=5.6))
            px0, px1, py0, py1 = c['pump']
            ax.add_artist(FancyBboxPatch((px0, py0), px1 - px0, py1 - py0, boxstyle='round,pad=0,rounding_size=8',
                                        fc='#262b36', ec='#c9d1e0', lw=1.0, alpha=0.9, zorder=6))
            ax.text(0.5 * (px0 + px1), 0.5 * (py0 + py1), 'pump', color='#c9d1e0', fontsize=7.5 * fs, ha='center',
                    va='center', zorder=12)
            if c['mount'] == 'top':
                ty = y0
                ax.plot([px0 + 10, px0 + 10, x0 + 30], [py1, ty - 4, ty - 4], color='#20242e', lw=4 * fs, zorder=5.4,
                        solid_capstyle='round')
                ax.plot([px1 - 10, px1 - 10, x0 + 70], [py1, ty - 12, ty - 12], color='#20242e', lw=4 * fs, zorder=5.4,
                        solid_capstyle='round')
                self.cpu_label_xy = (0.5 * (x0 + x1) + 60, y0 - 34)
            else:
                ax.plot([px1, x0 - 6, x0 - 6], [py1 - 10, py1 - 10, y1 - 30], color='#20242e', lw=4 * fs, zorder=5.4)
                ax.plot([px1, x0 - 14, x0 - 14], [py0 + 10, py0 + 10, y0 + 30], color='#20242e', lw=4 * fs, zorder=5.4)
                self.cpu_label_xy = (x0 - 48, 0.5 * (y0 + y1))
            ax.text(0.5 * (x0 + x1), 0.5 * (y0 + y1), 'radiator', color='white', fontsize=7.5 * fs, ha='center',
                    va='center', zorder=12, rotation=0 if c['mount'] == 'top' else 90,
                    bbox=dict(boxstyle='round,pad=0.15', fc='#000000', ec='none', alpha=0.45))

        # GPU: fins (edge-on), backplate, fan shroud + fans, bracket
        gx0, gx1, gy0, gy1 = g['box']
        fy0, fy1 = g['band']
        segs = [[(xx, fy1 + 1), (xx, gy1 - 5)] for xx in np.arange(gx0 + 6, gx1 - 3, 4.0)]
        ax.add_collection(LineCollection(segs, colors='#d8efff', linewidths=0.6, alpha=0.35, zorder=5))
        self._rect(gx0, gx1, gy1 - 5, gy1, fc='#596276', ec='#b3bccd', lw=0.6, zorder=6)
        self._rect(gx0, gx1, fy0, fy1, fc='#1f2430', alpha=0.9, ec='#8c95a8', lw=0.6, zorder=5)
        for a, b in g['fans']:
            self._rect(a, b, fy0 + 1.5, fy1 - 1.5, fc='#3a4255', alpha=0.85, ec='none', zorder=5.5)
            self._edge(('y', (fy0, fy1), 0.5 * (a + b), 30.0, 15.0, L.loads['f_gpu']), ('loads', 'f_gpu'))
        self._rect(gx0, gx1, gy0, gy1, fill=False, ec='#e6ebf5', lw=1.2, zorder=6)
        self._rect(-6, -1, gy0 - 4, gy1 + 8, fc='#7d869a', ec='#b3bccd', lw=0.5, zorder=6)
        ax.text(0.5 * (gx0 + gx1), 0.5 * (fy1 + gy1), 'GPU', color='white', fontsize=10 * fs, ha='center',
                va='center', zorder=12, fontweight='bold',
                bbox=dict(boxstyle='round,pad=0.2', fc='#000000', ec='none', alpha=0.45))
        self.gpu_label_xy = (0.5 * (gx0 + gx1), gy0 - 30)

        # wall fans (case fans + AIO fans): edge-on frames inside, spinning icons outside
        for wf in L.draw['wall_fans']:
            w, (b0, b1), (s0, s1) = wf['wall'], wf['band'], wf['span']
            cs = 0.5 * (s0 + s1)
            frac = next((f.frac for f in L.fans if f.label == wf['label']), 0.0)
            r_icon = 0.235 * wf['size']
            col = COOL if wf['direction'] == 'in' else HOT
            if w in ('front', 'rear'):
                self._rect(b0, b1, s0 + 1, s1 - 1, fc='#2f3646', alpha=0.45, ec='#aab3c5', lw=0.9, zorder=5)
                self._edge(('x', (b0, b1), cs, wf['size'] / 3.0, wf['size'] / 6.0, frac), ('fan', wf['label']))
                cx = L.D + 44 if w == 'front' else -44
                self.icons.append((cx, cs, r_icon, +1 if w == 'front' else -1))
                inward = (wf['direction'] == 'in')
                sgn = (-1 if w == 'front' else +1) if inward else (+1 if w == 'front' else -1)
                xs = cx - sgn * 36
                ax.add_artist(FancyArrow(xs, cs, sgn * 72, 0, width=6, head_width=17, head_length=11,
                                        length_includes_head=True, fc=col, ec='#1a1a1a', lw=0.5, zorder=11))
                self.icon_text.append((wf['label'], cx, cs - r_icon - 6, 'center', 'top'))
            else:
                self._rect(s0 + 1, s1 - 1, b0, b1, fc='#2f3646', alpha=0.45, ec='#aab3c5', lw=0.9, zorder=5)
                self._edge(('y', (b0, b1), cs, wf['size'] / 3.0, wf['size'] / 6.0, frac), ('fan', wf['label']))
                cy = L.H + 38 if w == 'top' else -64
                if wf.get('on_shroud'):
                    self._rect(s0 + 4, s1 - 4, 1, L.sh - 3, fill=False, ec='#6b7385', lw=0.6, ls=(0, (2, 3)), zorder=5)
                self.icons.append((cs, cy, r_icon, -1))
                inward = (wf['direction'] == 'in')
                sgn = (-1 if w == 'top' else +1) if inward else (+1 if w == 'top' else -1)
                ys = cy - sgn * 34
                ax.add_artist(FancyArrow(cs, ys, 0, sgn * 68, width=6, head_width=17, head_length=11,
                                        length_includes_head=True, fc=col, ec='#1a1a1a', lw=0.5, zorder=11))
                if w == 'top':
                    self.icon_text.append((wf['label'], cs, cy + r_icon + 4, 'center', 'bottom'))
                else:
                    self.icon_text.append((wf['label'], cs, cy - r_icon - 6, 'center', 'top'))
        for cx, cy, r, _ in self.icons:
            ax.add_artist(FancyBboxPatch((cx - r, cy - r), 2 * r, 2 * r, boxstyle='round,pad=0,rounding_size=%.1f' % (0.2 * r),
                                        fc='#232937', ec='#6b7385', lw=0.9, zorder=8))
            ax.add_artist(Circle((cx, cy), 0.97 * r, fc='#151a25', ec='#4b5468', lw=0.8, zorder=8))

        # side-panel fans: blow towards / away from the viewer
        for sf in L.draw['side_fans']:
            (cx, cy), r = sf['centre'], sf['r']
            col = COOL if sf['direction'] == 'in' else HOT
            ax.add_artist(Circle((cx, cy), r, fill=False, ec=col, lw=1.6 * fs, ls=(0, (5, 3)), zorder=7))
            ax.add_artist(Circle((cx, cy), 0.18 * r, fill=False, ec=col, lw=1.6 * fs, zorder=7))
            if sf['direction'] == 'in':
                ax.add_artist(Circle((cx, cy), 0.06 * r, fc=col, ec='none', zorder=7))
            else:
                k = 0.12 * r
                ax.plot([cx - k, cx + k], [cy - k, cy + k], color=col, lw=1.6 * fs, zorder=7)
                ax.plot([cx - k, cx + k], [cy + k, cy - k], color=col, lw=1.6 * fs, zorder=7)
            self.icon_text.append((sf['label'], cx, cy + r + 4, 'center', 'bottom'))

        # fans placed anywhere inside the case
        for inf in L.draw['inside_fans']:
            axis, (b0, b1), (s0, s1) = inf['axis'], inf['band'], inf['span']
            frac = next((f.frac for f in L.fans if f.label == inf['label']), 0.0)
            box = (b0, b1, s0, s1) if axis == 'x' else (s0, s1, b0, b1)
            self._rect(*box, fc='#2f2a46', alpha=0.55, ec='#c7a6ff', lw=1.2, zorder=6)
            self._edge((axis, (b0, b1), 0.5 * (s0 + s1), inf['size'] / 3.0, inf['size'] / 6.0, frac),
                       ('fan', inf['label']))
            d = inf['direction']
            cx, cy = 0.5 * (box[0] + box[1]), 0.5 * (box[2] + box[3])
            vx, vy = {'up': (0, 1), 'down': (0, -1), 'left': (-1, 0), 'right': (1, 0)}[d]
            ax.add_artist(FancyArrow(cx + vx * 16, cy + vy * 16, vx * 34, vy * 34, width=5, head_width=14,
                                    head_length=10, length_includes_head=True, fc='#c7a6ff', ec='#1a1a1a', lw=0.5,
                                    zorder=11))
            if axis == 'y':                       # label beside the fan, not on the part below it
                self.icon_text.append((inf['label'], box[1] + 6, cy, 'left', 'center'))
            else:
                self.icon_text.append((inf['label'], cx, box[3] + 8, 'center', 'bottom'))
        # blocks you placed yourself
        self.block_text = []                       # where the air temperature of a heated block is shown
        for b in L.draw.get('blocks', []):
            self._block(b)
        # fans and blocks that could not be placed: show where they are
        for rj in L.draw.get('rejected', []) + L.draw.get('rejected_blocks', []):
            x0, x1, y0, y1 = rj['box']
            self._rect(x0, x1, y0, y1, fill=False, ec='#ffd166', lw=1.4, ls=(0, (3, 2)), zorder=13)
            ax.text(0.5 * (x0 + x1), 0.5 * (y0 + y1), '%s ✕' % rj['label'], color='#ffd166', fontsize=7.5 * fs,
                    ha='center', va='center', zorder=13, fontweight='bold')
        self.ghost = Circle((0, 0), 30, fill=False, ec='white', lw=1.5, ls=(0, (3, 2)), zorder=14, visible=False)
        ax.add_artist(self.ghost)
        self.ghost_box = Rectangle((0, 0), 1, 1, fill=False, ec='white', lw=1.5, ls=(0, (3, 2)), zorder=14,
                                   visible=False)
        ax.add_artist(self.ghost_box)

    def _block(self, b):
        """one block: its fill shows how much air gets through, an orange outline that it makes heat"""
        ax, fs, L = self.ax, self.fs, self.L
        x0, x1, y0, y1 = b['box']
        w, h = x1 - x0, y1 - y0
        st = BLOCK_STYLE.get(b['air'], BLOCK_STYLE['solid'])
        hot = b['watts'] > 0
        ax.add_artist(Rectangle((x0, y0), w, h, fc=st['fc'], ec=HEAT if hot else st['ec'], hatch=st['hatch'],
                                lw=1.3 if hot else 1.0, zorder=5.6))
        g = min(HANDLE_MM, 0.45 * w, 0.45 * h)
        ax.add_artist(Polygon([(x1, y1), (x1 - g, y1), (x1, y1 - g)], closed=True, fc='#e6ebf5', ec='none',
                              alpha=0.85, zorder=5.7))
        name = '%d · %s' % (b['index'] + 1, short(b['model']))
        if hot:
            name += ' · %.0f W' % b['watts']
        size = 7.0 * fs
        text_w = 5.2 * len(name) * fs + 6                                   # about how wide the name is (mm)
        dy = 6.0 if hot else 0.0
        cy = 0.5 * (y0 + y1)
        if w >= text_w + 4 and h >= (30.0 if hot else 16.0):                  # room inside the block
            x, y, ha = 0.5 * (x0 + x1), cy, 'center'
        elif x1 + text_w < L.D - 4:                                           # beside it, inside the case
            x, y, ha = x1 + 5, cy, 'left'
        elif x0 - text_w > 4:
            x, y, ha = x0 - 5, cy, 'right'
        elif y1 + 28 < L.H:                                                 # above or below it
            x, y, ha = 0.5 * (x0 + x1), y1 + 8 + dy, 'center'
        else:
            x, y, ha = 0.5 * (x0 + x1), y0 - 8 - 2 * dy, 'center'
        ax.text(x, y + dy, name, color='white', fontsize=size, ha=ha, va='center', zorder=12, fontweight='bold',
                bbox=dict(boxstyle='round,pad=0.15', fc='#000000', ec='none', alpha=0.45), parse_math=False)
        if hot:
            self.block_text.append((b['label'], x, y - dy - 2, ha))

    def _flow_arrow(self, c):
        st = c['stacks']
        x0 = min(b[0] for b in st); x1 = max(b[1] for b in st)
        y0 = min(b[2] for b in st); y1 = max(b[3] for b in st)
        xc, yc = 0.5 * (x0 + x1), 0.5 * (y0 + y1)
        if c['axis'] == 'x':
            return ((xc + 18, xc - 18) if c['sign'] < 0 else (xc - 18, xc + 18)), (y1 - 22, y1 - 22)
        return (x1 - 20, x1 - 20), ((yc - 18, yc + 18) if c['sign'] > 0 else (yc + 18, yc - 18))

    def _labels(self):
        ax, fs = self.ax, self.fs
        box = dict(boxstyle='round,pad=0.28', fc='#000000', ec='none', alpha=0.6)
        self.t_cpu = ax.text(*self.cpu_label_xy, '', ha='center', va='center', color='white', fontsize=10.5 * fs,
                             fontweight='bold', zorder=12, bbox=box, linespacing=1.1)
        self.t_gpu = ax.text(*self.gpu_label_xy, '', ha='center', va='center', color='white', fontsize=10.5 * fs,
                             fontweight='bold', zorder=12, bbox=box)
        small = dict(fontsize=8.0 * fs, zorder=12, color=TXT, fontweight='bold', linespacing=1.05)
        self.t_icons = [(lab, ax.text(x, y, '', ha=ha, va=va, multialignment='center', **small))
                        for lab, x, y, ha, va in self.icon_text]
        self.t_hdd = None
        if self.L.draw.get('hdd'):
            x0, x1, y0, y1 = self.L.draw['hdd']['cage']
            self.t_hdd = ax.text(0.5 * (x0 + x1), y1 + 7, '', ha='center', va='bottom', fontsize=7.0 * fs,
                                 color='#e6ebf5', zorder=12)
        self.t_psu = ax.text(-50, 0.5 * self.L.draw['psu']['box'][3] + 15, '', ha='center', va='center',
                             fontsize=7.5 * fs, color='#ffc9a0', zorder=12, fontweight='bold')
        self.t_psu_in = None
        if self.L.draw['psu']['mode'] == 'bottom intake':
            s0, s1 = self.L.draw['psu']['fan_span']
            self.t_psu_in = ax.text(0.5 * (s0 + s1) + 46, -64, '', ha='left', va='center', fontsize=7.5 * fs,
                                    color=TXT, zorder=12, fontweight='bold')
        self.t_blocks = [(lab, ax.text(x, y, '', ha=ha, va='center', fontsize=7.0 * fs, color='#ffc9a0', zorder=12,
                                       fontweight='bold', bbox=dict(boxstyle='round,pad=0.15', fc='#000000',
                                                                    ec='none', alpha=0.45)))
                         for lab, x, y, ha in self.block_text]

    # ------------------------------------------------------------------ per frame
    def update(self, k, T, P, summary):
        self.T_last = np.array(T, dtype=np.float32)          # a copy: the solver reuses its arrays
        self.img.set_data(self.T_last)
        if P is not None and len(P):
            P = P[:self.n_dash]
            x, y, u, v, a = P[:, 0], P[:, 1], P[:, 2], P[:, 3], P[:, 4]
            sp = np.hypot(u, v) + 1e-9
            Ld = 2.0 + 9.0 * np.clip(sp / 1.1, 0, 1)
            dx, dy = 0.5 * Ld * u / sp, 0.5 * Ld * v / sp
            shade = np.minimum((np.clip(a, 0, 1) * DASH_SHADES).astype(int), DASH_SHADES - 1)
            for j, line in enumerate(self.dash_lines):
                m = shade == j
                n = int(m.sum())
                xs = np.full(3 * n, np.nan)
                ys = np.full(3 * n, np.nan)
                xs[0::3], xs[1::3] = x[m] - dx[m], x[m] + dx[m]
                ys[0::3], ys[1::3] = y[m] - dy[m], y[m] + dy[m]
                line.set_data(xs, ys)
        bsegs = []
        for axis, band, cs, rb, rhub, frac in self.edge_fans:
            if frac <= 0.01:
                continue
            phase = 0.33 * k * min(1.0, 0.3 + frac)
            for j in range(7):
                th = phase + 2 * np.pi * j / 7
                if np.cos(th) < 0:
                    continue
                s = cs + rb * np.sin(th)
                if axis == 'x':
                    bsegs.append([(band[0] + 3, s - 4), (band[1] - 3, s + 4)])
                else:
                    bsegs.append([(s - 4, band[0] + 2), (s + 4, band[1] - 2)])
        self.blade_lc.set_segments(bsegs)
        if self.icons:
            self.blades.set_verts(np.concatenate([fan_blades(cx, cy, r, sgn * 0.21 * k)
                                                  for cx, cy, r, sgn in self.icons]))
        if summary is None:
            return
        s = summary
        self.t_cpu.set_text(('air in\n%.0f °C' if self.L.draw['cooler']['kind'] == 'tower' else 'radiator air in\n%.0f °C')
                            % s['cpu_in'])
        self.t_gpu.set_text('air in %.0f °C' % s['gpu_in'])
        by_label = {f['label']: f for f in s['fans']}
        for lab, t in self.t_icons:
            f = by_label.get(lab)
            if f is None:
                t.set_text('')
                continue
            if f['wall'] == 'inside':
                txt = '%.0f CFM · %.0f rpm' % (f['cfm'], f['rpm'])
            elif f['direction'] == 'out':
                txt = '%.0f °C · %.0f CFM' % (f['t_out'], f['cfm'])
            else:
                txt = '%.0f CFM in' % f['cfm']
            t.set_text(txt + ('\nauto %.0f rpm' % f['rpm'] if f.get('auto') and f['wall'] != 'inside' else
                              (' · auto' if f.get('auto') else '')))
        self.t_psu.set_text('PSU out\n%.0f °C' % s['psu_t_out'])
        if self.t_hdd is not None and s.get('t_hdd') is not None:
            self.t_hdd.set_text('drives ≈ %.0f °C' % s['t_hdd'])
        if self.t_psu_in is not None:
            self.t_psu_in.set_text('PSU fan\n%.0f CFM' % s['psu_cfm'])
        if self.t_blocks:
            air = {b['label']: b['t_air'] for b in s.get('blocks', [])}
            for lab, t in self.t_blocks:
                t.set_text(('air ≈ %.0f °C' % air[lab]) if lab in air else '')


def _freeze(x):
    """a comparable copy of nested layout data, without the fan speeds (the drawing does not show them)"""
    if isinstance(x, dict):
        return tuple(sorted((k, _freeze(v)) for k, v in x.items() if k not in ('frac', 'auto')))
    if isinstance(x, (list, tuple)):
        return tuple(_freeze(v) for v in x)
    if isinstance(x, np.ndarray):
        return ('array', x.shape, x.tobytes())
    if isinstance(x, (float, np.floating)):
        return round(float(x), 4)
    if isinstance(x, np.integer):
        return int(x)
    return x


def clear_view(ax):
    """take a case drawing off its axes, ready for the next one (ax.clear() also rebuilds the hidden ticks and
    spines, which made every redrawn layout about 20 ms slower)"""
    keep = {id(ax.patch), id(ax.title), id(ax._left_title), id(ax._right_title)}
    for a in list(ax.get_children()):
        if id(a) not in keep and not isinstance(a, (Spine, Axis)):
            a.remove()


def drawing_key(L):
    """two layouts with the same key look the same on screen (only fan speeds, loads or temperatures differ)"""
    c = L.cfg.case
    return _freeze((L.D, L.H, L.h_mm, L.sh, bool(c.shroud), L.draw,
                    [(op['wall'], np.asarray(op['cells'])) for op in L.openings],
                    [(f.label, f.kind) for f in L.fans], L.draw['cooler'].get('kind')))


class LiveFrames:
    """Fast drawing of the live view.

    The case, the parts, the fan housings and the fixed labels do not change from frame to frame, so they are
    drawn once into see-through layers (one per height level, so the stacking order stays exactly as in a normal
    drawing). A frame then only paints the moving air (temperature colours + flow dashes), the spinning blades and
    the numbers, and pastes the layers in between - about 5x quicker than drawing everything, which keeps the
    window responsive while the simulation runs."""

    LEVELS = (1.0, 4.0, 6.5, 9.0, 12.0)        # z-orders of the moving parts: field, dashes, edge blades, icons, numbers

    def __init__(self, canvas, view, previous=None):
        """previous = the LiveFrames of the view this one replaces: its background is reused when it still fits"""
        self.canvas, self.view, self.ax = canvas, view, view.ax
        self.key = None
        self.text_key = None
        self.last = None
        self.texts = None
        self.bg = None
        self.bg_key = None
        if previous is not None and previous.bg is not None:
            self.bg, self.bg_key = previous.bg, previous.bg_key

    def invalidate(self):
        self.key = None

    def _current_key(self):
        ax = self.ax
        return (self.canvas.get_width_height(), tuple(np.round(ax.bbox.bounds, 2)), tuple(ax.get_xlim()),
                tuple(ax.get_ylim()))

    def _background_key(self):
        return self.canvas.get_width_height(), tuple(np.round(self.ax.bbox.bounds, 2))

    def _static(self):
        v, ax = self.view, self.ax
        moving = {id(a) for a in v.dynamic_below + v.dynamic_mid + v.dynamic_texts + v.dynamic_top}
        skip = {id(ax.patch), id(ax.title), id(ax._left_title), id(ax._right_title)}
        return [a for a in ax.get_children()
                if id(a) not in moving and id(a) not in skip and not isinstance(a, (Spine, Axis))]

    def _box(self):
        buf = np.asarray(self.canvas.get_renderer().buffer_rgba())
        H, W = buf.shape[:2]
        x0, y0, x1, y1 = self.ax.bbox.extents
        x0, y0 = max(0, int(np.floor(x0))), max(0, int(np.floor(y0)))
        x1, y1 = min(W, int(np.ceil(x1))), min(H, int(np.ceil(y1)))
        return x0, y0, x1, y1, H

    def _layer(self, renderer, artists):
        """draw these artists alone on a clear background and keep the see-through result (or None if empty)"""
        if not artists:
            return None
        renderer.clear()
        for a in sorted(artists, key=lambda a: a.get_zorder()):      # stable: same order as a normal drawing
            a.draw(renderer)
        x0, y0, x1, y1, H = self.box
        part = np.asarray(renderer.buffer_rgba())[H - y1:H - y0, x0:x1]
        rows = np.nonzero(part[..., 3].any(axis=1))[0]
        if len(rows) == 0:
            return None
        cols = np.nonzero(part[..., 3].any(axis=0))[0]
        r0, r1, c0, c1 = rows[0], rows[-1] + 1, cols[0], cols[-1] + 1
        img = np.ascontiguousarray(part[r0:r1, c0:c1][::-1])          # draw_image wants the bottom row first
        return x0 + c0, (y1 - r1), img

    @staticmethod
    def _paste(renderer, gc, layer):
        if layer is not None:
            x, y, img = layer
            renderer.draw_image(gc, x, y, img)

    def _build(self):
        canvas, ax = self.canvas, self.ax
        ax.apply_aspect()                            # a new case size moves the view box (normally done while drawing)
        static = self._static()
        everything = static + [a for a in ax.get_children() if a not in static]
        shown = [(a, a.get_visible()) for a in everything]
        lv = self.LEVELS
        bg_key = self._background_key()
        reuse = (self.bg is not None and self.bg_key == bg_key and
                 not any(a.get_zorder() < lv[0] for a in static))    # the background has nothing of the view in it
        try:
            if not reuse:
                for a in everything:                 # 1. the background: the figure without this view
                    if not (a in static and a.get_zorder() < lv[0]):
                        a.set_visible(False)
                ax.patch.set_visible(dict(shown).get(ax.patch, True))
                FigureCanvasAgg.draw(canvas)
                self.bg, self.bg_key = canvas.copy_from_bbox(ax.bbox), bg_key
                canvas.blit()                        # the rest of the figure (colour bar) is on screen now
                for a, vis in shown:
                    a.set_visible(vis)
            renderer = canvas.get_renderer()
            self.box = self._box()
            z = lambda a: a.get_zorder()
            self.layers = [
                self._layer(renderer, [a for a in static if lv[0] <= z(a) <= lv[1]]),
                self._layer(renderer, [a for a in static if lv[1] < z(a) <= lv[2]]),
                self._layer(renderer, [a for a in static if lv[2] < z(a) <= lv[3]]),
                self._layer(renderer, [a for a in static if lv[3] < z(a) <= lv[4]]),
                self._layer(renderer, [a for a in static if z(a) > lv[4]]),
            ]
        finally:
            for a, vis in shown:
                a.set_visible(vis)
        self.text_key = None
        self.key = self._current_key()

    def _paint_field(self, renderer, gc):
        """the temperature colours, scaled smoothly to the screen (much quicker than imshow)"""
        v = self.view
        T = v.T_last
        if T is None:
            return
        L = v.L
        (px0, py0), (px1, py1) = self.ax.transData.transform([(0.0, 0.0), (L.D, L.H)])
        x, y = int(round(px0)), int(round(py0))
        w, h = int(round(px1)) - x, int(round(py1)) - y
        if w < 2 or h < 2:
            return
        idx = np.clip((T - VMIN) * (255.0 / (VMAX - VMIN)) + 0.5, 0, 255).astype(np.uint8)
        big = np.asarray(Image.fromarray(np.ascontiguousarray(idx), 'L').resize((w, h), Image.BILINEAR))
        renderer.draw_image(gc, x, y, LUT32[big].view(np.uint8).reshape(h, w, 4))

    def frame(self):
        """draw one frame of the live view and put it on screen"""
        if self.key != self._current_key():
            self._build()
        canvas, v = self.canvas, self.view
        renderer = canvas.get_renderer()
        texts = [t for t in v.dynamic_texts if t is not None]
        tkey = tuple((t.get_text(), t.get_visible()) for t in texts)
        if tkey != self.text_key:                    # numbers changed: draw them again (a few times a second)
            self.texts = self._layer(renderer, texts)
            self.text_key = tkey
        canvas.restore_region(self.bg)
        gc = renderer.new_gc()
        gc.set_clip_rectangle(self.ax.bbox)
        try:
            self._paint_field(renderer, gc)
            self._paste(renderer, gc, self.layers[0])
            for a in v.dynamic_below[1:]:            # flow dashes
                a.draw(renderer)
            self._paste(renderer, gc, self.layers[1])
            v.blade_lc.draw(renderer)
            self._paste(renderer, gc, self.layers[2])
            v.blades.draw(renderer)
            self._paste(renderer, gc, self.layers[3])
            self._paste(renderer, gc, self.texts)
            self._paste(renderer, gc, self.layers[4])
        finally:
            gc.restore()
        self.last = canvas.copy_from_bbox(self.ax.bbox)
        for a in v.dynamic_top:                      # the drag marker
            a.draw(renderer)
        canvas.blit(self.ax.bbox)

    def marker(self):
        """only the drag marker moved: put it on the last frame (very quick)"""
        if self.last is None or self.key != self._current_key():
            return self.frame()
        renderer = self.canvas.get_renderer()
        self.canvas.restore_region(self.last)
        for a in self.view.dynamic_top:
            a.draw(renderer)
        self.canvas.blit(self.ax.bbox)


# ====================================================================== portrait frame
class ReportFrame:
    """1080 x 1920 frame: title, case view, colour bar, read-out tiles, footer."""

    def __init__(self, layout, width=1080, height=1920, dpi=120):
        L = self.L = layout
        cfg = L.cfg
        # drawn off-screen in any program (no window, whatever matplotlib backend is active)
        self.fig = Figure(figsize=(width / dpi, height / dpi), dpi=dpi, facecolor=BG)
        FigureCanvasAgg(self.fig)
        fig = self.fig
        fig.text(0.5, 0.970, 'PC case airflow simulation', color=TXT, ha='center', va='center', fontsize=24,
                 fontweight='bold')
        fig.text(0.5, 0.950, fan_summary(L), color=TXT, ha='center', va='center', fontsize=12)
        fig.text(0.5, 0.933, '%s  ·  %s' % (short(cfg.cooler), cfg.gpu), color=SUB, ha='center', va='center',
                 fontsize=9.5, parse_math=False)
        xl, yl = view_limits(L)
        ax_h = min(0.56, (yl[1] - yl[0]) / (xl[1] - xl[0]) * width / height)
        top = 0.922
        ax = fig.add_axes([0.0, top - ax_h, 1.0, ax_h])
        self.view = CaseView(ax, L, fs=1.0, dashes=1150)
        y_cb = top - ax_h - 0.028
        cax = fig.add_axes([0.06, y_cb, 0.88, 0.011])
        cax.imshow(np.linspace(0, 1, 256)[None, :], aspect='auto', cmap=CMAP, extent=[VMIN, VMAX, 0, 1])
        cax.set_yticks([])
        cax.set_xticks([22, 27, 32, 37, 42])
        cax.set_xticklabels(['22 °C', '27', '32', '37', '42 °C'], color=TXT, fontsize=9.5)
        cax.tick_params(length=0, pad=4)
        for s_ in cax.spines.values():
            s_.set_visible(False)
        fig.text(0.06, y_cb + 0.020, 'air temperature', color=SUB, fontsize=9, va='center')
        fig.text(0.94, y_cb + 0.020, 'blue = room air', color=SUB, fontsize=9, va='center', ha='right')
        t_top = y_cb - 0.035
        t_bot = 0.095
        tax = fig.add_axes([0.03, t_bot, 0.94, t_top - t_bot])
        tax.set_xlim(0, 3)
        tax.set_ylim(0, 2)
        tax.axis('off')
        self.tiles = {}
        specs = [('cpu', 0, 1, 'CPU  (estimate)'), ('gpu', 1, 1, 'GPU core  (estimate)'),
                 ('power', 2, 1, 'Power use now'),
                 ('flow', 0, 0, 'Airflow through the case'), ('press', 1, 0, 'Pressure inside'),
                 ('heat', 2, 0, 'Where the heat leaves')]
        for key, cx_, cy_, label in specs:
            x0, y0 = cx_ + 0.03, cy_ + 0.06
            tax.add_patch(FancyBboxPatch((x0, y0), 0.94, 0.88, boxstyle='round,pad=0,rounding_size=0.06',
                                         fc=PANEL, ec=EDGE, lw=1.0, mutation_aspect=0.5))
            bar = Rectangle((x0 + 0.035, y0 + 0.14), 0.022, 0.60, fc=SUB, ec='none')
            tax.add_patch(bar)
            tax.text(x0 + 0.10, y0 + 0.72, label, color=SUB, fontsize=9.4, va='center')
            val = tax.text(x0 + 0.10, y0 + 0.45, '', color=TXT, fontsize=19, fontweight='bold', va='center')
            sub = tax.text(x0 + 0.10, y0 + 0.21, '', color=SUB, fontsize=8.3, va='center', linespacing=1.25)
            self.tiles[key] = (bar, val, sub)
        fig.text(0.5, 0.079, '%s  ·  %s  ·  %s load  ·  room %.0f °C' % (cfg.cpu, cfg.gpu, cfg.load, cfg.room_c),
                 color=SUB, ha='center', va='center', fontsize=8.8, parse_math=False)
        fig.text(0.5, 0.064, '%s board  ·  %d × %s%s  ·  %d SSD  ·  %d HDD  ·  PSU %d W %s%s' % (
            L.draw.get('board_form', ''), cfg.ram_sticks, cfg.ram_type, ' ECC' if cfg.ram_ecc else '',
            cfg.nvme_count, cfg.hdd_count, cfg.psu_watts, cfg.psu_rating,
            ('  ·  %d block%s' % (len(cfg.blocks), '' if len(cfg.blocks) == 1 else 's')) if cfg.blocks else ''),
            color=SUB, ha='center', va='center', fontsize=8.8)
        fig.text(0.5, 0.049, 'Case %.0f × %.0f × %.0f mm  ·  dust filters %s  ·  altitude %.0f m' % (
            cfg.case.depth_mm, cfg.case.height_mm, cfg.case.width_mm, cfg.filter_condition, cfg.altitude_m),
            color=SUB, ha='center', va='center', fontsize=8.8)
        fig.text(0.5, 0.034, '2D airflow + heat simulation (averaged across the case width) — values are estimates',
                 color='#6f7890', ha='center', va='center', fontsize=8.3, style='italic')
        self.t_credit = fig.text(0.5, 0.014, branding.CREDIT_LINE, color=ACC_CREDIT, ha='center', va='center',
                                 fontsize=9.6, fontweight='bold')
        self.t_time = fig.text(0.5, top - ax_h + 0.006, '', color=SUB, ha='center', va='center', fontsize=8.5)

    def update(self, k, T, P, s, t_real=None):
        self.view.update(k, T, P, s)
        ld = s['loads']
        norm = lambda T_: CMAP(np.clip((T_ - VMIN) / (VMAX - VMIN), 0, 1))

        def put(key, val, sub, color):
            bar, tv, ts = self.tiles[key]
            tv.set_text(val)
            ts.set_text(sub)
            bar.set_facecolor(color)
        put('cpu', '≈ %.0f °C' % s['t_cpu'] + ('  (limit)' if s['cpu_limited'] else ''),
            'air in %.1f °C\n%.0f W of %.0f W max' % (s['cpu_in'], ld['p_cpu'], ld['cpu_max']),
            '#ff9f5a' if s['cpu_limited'] else norm(s['cpu_in']))
        put('gpu', '≈ %.0f °C' % s['t_gpu'], 'air in %.1f °C\n%.0f W of %.0f W max' % (s['gpu_in'], ld['p_gpu'], ld['gpu_max']),
            norm(s['gpu_in']))
        put('power', '%.0f W' % ld['p_dc'], 'max %.0f W · PSU %d W at %.0f %%\nfrom the wall ≈ %.0f W' % (
            ld['p_dc_max'], self.L.cfg.psu_watts, 100 * ld['psu_frac'], ld['p_wall']), '#ffd166')
        put('flow', '%.0f CFM' % s['cfm_in'], 'in %d fans · out %d fans\nout %.0f CFM' % (
            self.L.n_in, self.L.n_out, s['cfm_out']), COOL)
        p = s['p_case']
        put('press', ('%+.1f Pa' % p).replace('-', '−'),
            ('negative: dust enters\nthrough gaps' if p < -0.3 else ('positive: air pushes\nout of gaps' if p > 0.3 else 'balanced')),
            COOL if p < 0 else HOT)
        sh = sorted(s['heat_share'].items(), key=lambda kv: -kv[1])
        main = sh[0] if sh else ('-', 0)
        put('heat', '%s %.0f %%' % (main[0], main[1]), '  '.join('%s %.0f %%' % kv for kv in sh[1:4]) or ' ', HOT)
        if t_real is not None:
            self.t_time.set_text('slow motion · 0.25× real speed · t = %.2f s' % t_real)

    def rgb(self):
        self.fig.canvas.draw()
        return np.asarray(self.fig.canvas.buffer_rgba())[:, :, :3]


def short(name):
    return name.split(' (')[0]


def fan_summary(L):
    parts = []
    for wall in ('front', 'top', 'rear', 'bottom', 'side'):
        fins = [f for f in L.fans if f.kind in ('case', 'aio') and f.wall == wall]
        if wall == 'side':
            fins = [s for s in L.sides]
        n_in = sum(1 for f in fins if (f['direction'] if isinstance(f, dict) else f.direction) == 'in')
        n_out = len(fins) - n_in
        if n_in:
            parts.append('%s %d in' % (wall.capitalize(), n_in))
        if n_out:
            parts.append('%s %d out' % (wall.capitalize(), n_out))
    n_inside = sum(1 for f in L.fans if f.wall == 'inside')
    if n_inside:
        parts.append('%d inside' % n_inside)
    mode = L.cfg.psu_fan_mode
    parts.append('PSU fan: ' + ('bottom intake' if mode == 'bottom intake' else
                                ('from inside' if mode == 'from inside case' else 'off')))
    return '  ·  '.join(parts)
