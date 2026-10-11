"""Find a free spot for a fan, so a new or moved fan never lands on another fan or part.

The checks come from the layout itself (Layout.why_wall / why_inside / why_side), which works in
millimetres, so a spot found here is free at every simulation detail level.
"""
from typing import List, Optional, Tuple

import numpy as np

from .layout import Layout, FAN_T

PROBE_MM = 4.0                    # grid of the probe layout (the checks themselves are in mm)
WALL_STEP = 2.5                   # search step along a wall (mm)
AREA_STEP = 10.0                  # search step on the side panel / inside the case (mm)
WALL_ORDER = {'in': ('front', 'bottom', 'side', 'top', 'rear'),
              'out': ('top', 'rear', 'side', 'front', 'bottom')}
WALL_NAMES = {'front': 'front panel', 'top': 'top', 'rear': 'rear', 'bottom': 'bottom', 'side': 'side panel',
              'inside': 'inside the case'}


class Probe:
    """The case with some fans left out: answers 'what is in the way?' for a fan somewhere."""

    def __init__(self, cfg, skip=(), h_mm: float = PROBE_MM):
        self.cfg = cfg
        self.L = Layout(cfg, h_mm, skip=skip)

    def why(self, fan, wall: Optional[str] = None, pos: Optional[float] = None,
            pos2: Optional[float] = None) -> Optional[str]:
        """None if the fan fits at its position (or the one given), else what it would sit on"""
        wall = wall or fan.wall
        pos = fan.pos_mm if pos is None else pos
        pos2 = fan.pos2_mm if pos2 is None else pos2
        s = float(fan.size)
        if wall == 'side':
            return self.L.why_side(s, pos, pos2)
        if wall == 'inside':
            return self.L.why_inside(s, fan.direction, pos, pos2)
        return self.L.why_wall(wall, pos, s)

    # ------------------------------------------------------------------ search
    def natural_spot(self, wall, s):
        """where a new fan would normally go on a wall"""
        L = self.L
        if wall == 'front':
            return L.H / 2
        if wall == 'rear':
            return L.socket[1]
        if wall == 'top':
            return L.D / 2
        if wall == 'bottom':
            return L.D * 0.55
        return (L.D * 0.55, L.H * 0.55)

    def find_on_wall(self, fan, wall, near):
        L = self.L
        s = float(fan.size)
        length = L.wall_length(wall)
        if s > length:
            return None
        near = float(np.clip(near, s / 2, length - s / 2))
        cand = np.arange(s / 2, length - s / 2 + 1e-6, WALL_STEP)
        cand = np.concatenate([[near], cand, [length - s / 2]])
        for c in sorted(cand, key=lambda c: (abs(c - near), c)):
            if L.why_wall(wall, float(c), s) is None:
                return round(float(c), 1)
        return None

    def find_in_area(self, fan, wall, near):
        L = self.L
        s = float(fan.size)
        nx, ny = near
        if wall == 'side':
            xs = np.arange(s / 2, L.D - s / 2 + 1e-6, AREA_STEP)
            ys = np.arange(s / 2, L.H - s / 2 + 1e-6, AREA_STEP)
        else:
            half_x = s / 2 if fan.direction in ('up', 'down') else FAN_T / 2
            half_y = FAN_T / 2 if fan.direction in ('up', 'down') else s / 2
            xs = np.arange(half_x + 1, L.D - half_x - 1 + 1e-6, AREA_STEP / 2)
            ys = np.arange(half_y + 1, L.H - half_y - 1 + 1e-6, AREA_STEP / 2)
        X, Y = np.meshgrid(xs, ys)
        pts = np.concatenate([[[nx, ny]], np.stack([X.ravel(), Y.ravel()], 1)])
        order = np.argsort(np.hypot(pts[:, 0] - nx, pts[:, 1] - ny), kind='stable')
        for i in order:
            x, y = float(pts[i, 0]), float(pts[i, 1])
            if wall == 'side':
                x, y = L.side_centre(s, x, y)
                ok = L.why_side(s, x, y) is None
            else:
                slot = L.inside_slot(s, fan.direction, x, y)
                x, y = slot['centre']
                ok = L.blocked_by(slot['box']) is None
            if ok:
                return round(x, 1), round(y, 1)
        return None

    def find(self, fan, walls=None, near=None) -> Optional[dict]:
        """first free spot, trying the walls in order (nearest to `near` on the first wall).
        Returns dict(wall, pos_mm, pos2_mm, direction) or None."""
        walls = list(walls or [fan.wall])
        for k, wall in enumerate(walls):
            s = float(fan.size)
            first = k == 0 and near is not None
            if wall in ('side', 'inside'):
                if first:
                    target = near if isinstance(near, (tuple, list)) else (near, fan.pos2_mm)
                elif wall == fan.wall:
                    target = (fan.pos_mm, fan.pos2_mm)
                else:
                    target = self.natural_spot(wall, s)
                spot = self.find_in_area(fan, wall, target)
                if spot:
                    return dict(wall=wall, pos_mm=spot[0], pos2_mm=spot[1],
                                direction=fan.direction if wall == fan.wall else _dir_for(fan, wall))
                continue
            if first:
                target = near[0] if isinstance(near, (tuple, list)) else near
            elif wall == fan.wall:
                target = fan.pos_mm
            else:
                target = self.natural_spot(wall, s)
            pos = self.find_on_wall(fan, wall, target)
            if pos is not None:
                return dict(wall=wall, pos_mm=pos, pos2_mm=fan.pos2_mm, direction=_dir_for(fan, wall))
        return None


def _dir_for(fan, wall):
    """keep in / out when moving between walls; inside fans that go to a wall become intakes"""
    if wall == 'inside':
        return fan.direction if fan.direction in ('up', 'down', 'left', 'right') else 'up'
    if fan.direction in ('in', 'out'):
        return fan.direction
    return 'out' if wall in ('top', 'rear') else 'in'


def _walls_for(fan):
    if fan.wall == 'inside':
        return ['inside']
    order = WALL_ORDER['out' if fan.direction == 'out' else 'in']
    return [fan.wall] + [w for w in order if w != fan.wall]


def apply_spot(fan, spot: dict) -> None:
    fan.wall, fan.pos_mm, fan.pos2_mm, fan.direction = spot['wall'], spot['pos_mm'], spot['pos2_mm'], spot['direction']


def describe(fan) -> str:
    if fan.wall in ('side', 'inside'):
        return '%s at %.0f, %.0f mm' % (WALL_NAMES[fan.wall], fan.pos_mm, fan.pos2_mm)
    return '%s at %.0f mm' % (WALL_NAMES[fan.wall], fan.pos_mm)


def place_new(cfg, fan, near=None, walls=None) -> Tuple[bool, str]:
    """Put a new fan (not yet in cfg.fans) on a free spot: its own wall first (near `near`),
    then the other walls.  Changes `fan`; returns (ok, message for the user)."""
    probe = Probe(cfg)
    wanted = fan.wall
    spot = probe.find(fan, walls or _walls_for(fan), near)
    if spot is None:
        return False, 'No room for another %d mm fan - every free spot is taken' % fan.size
    apply_spot(fan, spot)
    if fan.wall != wanted:
        return True, 'The %s is full - the new fan went to the %s' % (WALL_NAMES.get(wanted, wanted), describe(fan))
    return True, 'New fan: %s' % describe(fan)


def snap(cfg, index: int, near=None) -> Tuple[bool, str]:
    """A fan in cfg.fans was moved (dragged / typed / wall changed): if it now sits on something,
    move it to the nearest free spot on the same wall.  Returns (ok, message)."""
    fan = cfg.fans[index]
    probe = Probe(cfg, skip={index})
    why = probe.why(fan)
    if why is None:
        return True, ''
    target = near if near is not None else ((fan.pos_mm, fan.pos2_mm) if fan.wall in ('side', 'inside') else fan.pos_mm)
    spot = probe.find(fan, [fan.wall], target)
    if spot is None:
        return False, 'There is no free spot on the %s for Fan %d (%s is in the way)' % (
            WALL_NAMES.get(fan.wall, fan.wall), index + 1, why)
    apply_spot(fan, spot)
    return True, 'Fan %d would sit on %s - moved beside it (%s)' % (index + 1, why, describe(fan))


def resolve(cfg) -> List[str]:
    """Move fans that overlap something (e.g. in an old setup file) to free spots.  Returns notes."""
    L = Layout(cfg, PROBE_MM)
    # fans where the radiator sits are replaced by the radiator's own fans on purpose
    bad = [r['index'] for r in L.draw['rejected'] if r.get('index') is not None and r.get('why') != 'the radiator']
    notes = []
    pending = set(bad)
    for k in sorted(bad):
        pending.discard(k)
        fan = cfg.fans[k]
        probe = Probe(cfg, skip=pending | {k})
        why = probe.why(fan) or 'another part'
        spot = probe.find(fan, _walls_for(fan), (fan.pos_mm, fan.pos2_mm) if fan.wall in ('side', 'inside')
                          else fan.pos_mm)
        if spot is None:
            notes.append('Fan %d overlaps %s and there is no free spot for it - it is left out' % (k + 1, why))
            continue
        apply_spot(fan, spot)
        notes.append('Fan %d overlapped %s - moved to the %s' % (k + 1, why, describe(fan)))
    return notes
