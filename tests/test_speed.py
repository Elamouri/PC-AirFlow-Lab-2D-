"""The live view must stay quick: layered drawing, short simulation slices, edits without a full rebuild."""
import copy
import os
import sys
import time

import numpy as np
import pytest

from pcflow.config import my_pc
from pcflow.layout import Layout
from pcflow.render import drawing_key, fan_blades
from pcflow.solver import Solver


# ---------------------------------------------------------------- without a screen
def test_drawing_key_ignores_speeds_loads_and_temperatures():
    cfg = my_pc()
    base = drawing_key(Layout(cfg, 4.0))
    for change in (lambda c: setattr(c.fans[0], 'speed_pct', 35), lambda c: setattr(c, 'load', 'max'),
                   lambda c: setattr(c, 'room_c', 30.0), lambda c: setattr(c.fans[2], 'speed_pct', -1)):
        c = copy.deepcopy(cfg)
        change(c)
        assert drawing_key(Layout(c, 4.0)) == base
    moved = copy.deepcopy(cfg)
    moved.fans[1].pos_mm += 40
    assert drawing_key(Layout(moved, 4.0)) != base
    turned = copy.deepcopy(cfg)
    turned.fans[0].direction = 'out' if turned.fans[0].direction == 'in' else 'in'
    assert drawing_key(Layout(turned, 4.0)) != base


def test_factorisation_is_reused_only_for_the_same_walls_and_parts():
    cfg = my_pc()
    first = Solver(Layout(cfg, 4.0), n_particles=50)
    faster = copy.deepcopy(cfg)
    faster.fans[0].speed_pct = 100
    second = Solver(Layout(faster, 4.0), n_particles=50, previous=first)
    assert second.lu is first.lu
    moved = copy.deepcopy(cfg)
    moved.fans[1].pos_mm += 40
    third = Solver(Layout(moved, 4.0), n_particles=50, previous=second)
    assert third.lu is not second.lu
    fresh = Solver(Layout(faster, 4.0), n_particles=50)          # same answers as a fresh factorisation
    rhs = np.random.default_rng(3).standard_normal(int(fresh.fl.sum()))
    assert np.allclose(second.lu.solve(rhs), fresh.lu.solve(rhs), atol=1e-9)


def old_fan_blades(cx, cy, r, rot, n=7):
    polys = []
    rh, rt = 0.30 * r, 0.93 * r
    t = np.linspace(0, 1, 7)
    for k in range(n):
        a0 = rot + 2 * np.pi * k / n
        lead = [(rh + (rt - rh) * s, a0 + 0.55 * s) for s in t]
        trail = [(rh + (rt - rh) * s, a0 + 0.55 * s + 0.38 + 0.20 * s) for s in t[::-1]]
        polys.append([(cx + rr * np.cos(aa), cy + rr * np.sin(aa)) for rr, aa in lead + trail])
    return np.array(polys)


def test_fan_blades_keep_their_shape():
    for args in ((10.0, 20.0, 28.0, 0.0), (-44.0, 300.0, 33.0, 1.7)):
        assert np.allclose(fan_blades(*args), old_fan_blades(*args))


# ---------------------------------------------------------------- the window
def _screen():
    if sys.platform.startswith('win') or sys.platform == 'darwin':
        return True
    return bool(os.environ.get('DISPLAY'))


window = pytest.mark.skipif(not _screen(), reason='needs a screen')


@pytest.fixture
def app():
    tk = pytest.importorskip('tkinter')
    import matplotlib
    backend = matplotlib.get_backend()
    from pcflow.gui import App
    matplotlib.use(backend)
    root = tk.Tk()
    a = App(root, my_pc())
    a.running = False
    for _ in range(4):
        root.update()
    for _ in range(60):
        a.sim.step()
        a.sim.move_particles()
    yield a
    a.close()


def axes_pixels(app):
    buf = np.asarray(app.canvas.get_renderer().buffer_rgba())
    x0, y0, x1, y1 = [int(round(v)) for v in app.ax.bbox.extents]
    H = buf.shape[0]
    return buf[H - y1:H - y0, x0:x1, :3].astype(int)


@window
def test_quick_frame_looks_like_a_normal_drawing(app):
    from pcflow.results import summarize
    app.summary = summarize(app.sim)
    app.view.update(3, app.sim.interior_T(), app.sim.frame_particles(), app.summary)
    app.canvas.draw()
    normal = axes_pixels(app)
    app.live.frame()
    quick = axes_pixels(app)
    d = np.abs(normal - quick).max(axis=2)
    assert d.mean() < 1.5 and (d > 40).mean() < 0.005


@window
def test_quick_frame_is_much_faster(app):
    app.live.frame()                                             # layers ready

    def timed(fn, n=8):
        fn()
        t0 = time.perf_counter()
        for _ in range(n):
            fn()
        return (time.perf_counter() - t0) / n
    k = [0]

    def step():
        k[0] += 1
        app.view.update(k[0], app.sim.interior_T(), app.sim.frame_particles(), None)
    normal = timed(lambda: (step(), app.canvas.draw()))
    quick = timed(lambda: (step(), app.live.frame()))
    assert quick < 0.5 * normal


@window
def test_speed_change_keeps_the_drawing(app):
    view, lu = app.view, app.sim.lu
    fan = next(i for i, f in enumerate(app.cfg.fans) if f.wall in ('front', 'top'))
    app.cfg.fans[fan].speed_pct = 100
    app.rebuild(keep=True)
    assert app.view is view and app.sim.lu is lu
    label = 'Fan %d' % (fan + 1)
    fracs = [e[5] for e, src in zip(view.edge_fans, view.edge_src) if src == ('fan', label)]
    assert fracs and all(abs(f - 1.0) < 1e-6 for f in fracs)       # its blades spin at the new speed
    app.cfg.fans[fan].pos_mm += 30
    app.rebuild(keep=True)
    assert app.view is not view                                   # moved: drawn again


@window
def test_window_answers_while_the_simulation_runs(app):
    app.running = True
    app.settle_until = app.sim.t + 10.0                           # the busiest phase
    times = []
    for _ in range(25):
        t0 = time.perf_counter()
        app.tick()
        times.append(time.perf_counter() - t0)
    times = sorted(times[2:])
    assert times[len(times) // 2] < 0.05                          # a turn of the event loop stays short
    app.running = False


@window
def test_drag_marker_appears_on_the_quick_frame(app):
    app.live.frame()
    fan = app.cfg.fans[0]
    x, y = app._fan_points(fan)[0]
    app._show_ghost(fan, x, y)
    px, py = app.ax.transData.transform((x + 0.5 * fan.size, y))
    buf = np.asarray(app.canvas.get_renderer().buffer_rgba())
    H = buf.shape[0]
    near = buf[int(H - py) - 3:int(H - py) + 4, int(px) - 3:int(px) + 4, :3]
    assert near.max() > 200                                       # the white dashed circle is there
    app.view.ghost.set_visible(False)
    app._marker()


@window
def test_quick_drawing_failure_falls_back_to_normal(app, monkeypatch):
    def broken():
        raise RuntimeError('test')
    monkeypatch.setattr(app.live, 'frame', broken)
    app._paint()
    assert app.live is None
    app._paint()                                                  # normal drawing from now on
