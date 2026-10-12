"""The live view must stay quick: a fast solver, layered drawing, short simulation slices, edits without a full
rebuild, and a window that redraws its controls while the air moves."""
import copy
import os
import sys
import time

import numpy as np
import pytest

from pcflow.config import Block, my_pc
from pcflow.layout import Layout
from pcflow.render import drawing_key, fan_blades
from pcflow.solver import (Advection, Solver, advect_reference, LIVE_STEP, REF_STEP, u_at_v, v_at_u)


# ---------------------------------------------------------------- the solver: same answers, less work
@pytest.mark.parametrize('shape', [(40, 41), (41, 40), (152, 150)])
def test_fast_advection_gives_the_plain_answer(shape):
    rng = np.random.default_rng(5)
    f, U, V = rng.standard_normal(shape), 2 * rng.standard_normal(shape), 2 * rng.standard_normal(shape)
    ref = advect_reference(f, U, V, 0.7)
    out = np.empty(shape)
    assert np.array_equal(Advection(shape, np.float64).advect(f, U, V, 0.7, out), ref)       # exactly, in float64
    out32 = np.empty(shape, np.float32)
    Advection(shape).advect(f.astype(np.float32), U.astype(np.float32), V.astype(np.float32), 0.7, out32)
    assert np.abs(out32 - ref).max() < 1e-4


def test_face_averages_match_the_plain_ones():
    sim = Solver(Layout(my_pc(), 4.0), n_particles=20)
    rng = np.random.default_rng(1)
    u = rng.standard_normal(sim.u.shape).astype(np.float32)
    v = rng.standard_normal(sim.v.shape).astype(np.float32)
    assert np.array_equal(sim._v_at_u(v), v_at_u(v))
    assert np.array_equal(sim._u_at_v(u), u_at_v(u))


def test_all_fans_at_once_push_like_one_after_the_other():
    cfg = my_pc()
    cfg.fans.append(copy.deepcopy(cfg.fans[0]))
    cfg.fans[-1].wall, cfg.fans[-1].pos_mm, cfg.fans[-1].pos2_mm, cfg.fans[-1].direction = 'inside', 330, 330, 'up'
    a = Solver(Layout(cfg, 4.0), n_particles=20)
    b = Solver(Layout(cfg, 4.0), n_particles=20)
    b._fan_groups = None                                          # the plain way: fan by fan
    for _ in range(30):
        a.step()
        b.step()
    assert np.allclose(a.u, b.u, atol=1e-4) and np.allclose(a.v, b.v, atol=1e-4)
    assert all(abs(fa.q - fb.q) < 1e-4 for fa, fb in zip(a.L.fans, b.L.fans))


def test_porous_parts_lose_the_same_speed_per_second_at_any_step():
    L = Layout(my_pc(), 4.0)
    K = np.array([0.0, 60.0, 300.0, 2500.0, 20000.0])
    ref = Solver(L, n_particles=20)
    assert np.allclose(ref.damping(K), 1.0 / (1.0 + ref.dt * K))           # the tuned step: unchanged
    live = Solver(L, n_particles=20, dt=LIVE_STEP * L.h)
    assert np.allclose(np.log(live.damping(K)) / live.dt, np.log(ref.damping(K)) / ref.dt)


def test_the_live_step_is_stable_and_keeps_the_balance():
    cfg = my_pc()
    for f in cfg.fans:
        f.speed_pct = 100
    for h in (4.0, 3.0):
        sim = Solver(Layout(cfg, h), n_particles=20, dt=LIVE_STEP * h * 1e-3)
        sim.run(2.0)
        r = sim.raw
        assert np.isfinite(sim.u).all() and np.isfinite(sim.T).all()
        assert abs(r['cfm_in'] - r['cfm_out']) / r['cfm_in'] < 0.01
        assert abs(r['heat_out'] - r['heat_in']) / r['heat_in'] < 0.2
    assert LIVE_STEP > REF_STEP


def test_a_step_reuses_its_arrays():
    sim = Solver(Layout(my_pc(), 4.0), n_particles=20)
    sim.step()
    sim.step()
    seen = {id(sim.u), id(sim.v), id(sim.T)}
    for _ in range(4):
        sim.step()
        seen |= {id(sim.u), id(sim.v), id(sim.T)}
    assert len(seen) == 6                                         # two sets of fields, used in turn


def test_porous_blocks_keep_the_factorisation():
    cfg = my_pc()
    cfg.blocks = [Block('Cable bundle', 360, 160, 30, 150, 'cables', 0)]
    first = Solver(Layout(cfg, 4.0), n_particles=20)
    cfg.blocks[0].x_mm += 20                                      # air still flows through it: same cells of air
    second = Solver(Layout(cfg, 4.0), n_particles=20, previous=first)
    assert second.lu is first.lu
    cfg.blocks[0].air = 'solid'
    third = Solver(Layout(cfg, 4.0), n_particles=20, previous=second)
    assert third.lu is not second.lu


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
@pytest.mark.parametrize('change', ['moved fan', 'smaller case', 'blocks'])
def test_quick_frame_after_a_new_layout_looks_like_a_normal_drawing(app, change):
    from pcflow.results import summarize
    if change == 'moved fan':
        app.cfg.fans[1].pos_mm += 30
    elif change == 'smaller case':
        app.cfg.case.depth_mm, app.cfg.case.height_mm, app.cfg.case.shroud_length_mm = 360, 520, 300
    else:
        app.cfg.blocks = [Block.of('Pump + reservoir', 330, 300), Block.of('Cable bundle', 360, 160)]
    app.rebuild(keep=True)                                        # the background of the old view is reused
    for _ in range(30):
        app.sim.step()
    app.summary = summarize(app.sim)
    app.view.update(3, app.sim.interior_T(), app.sim.frame_particles(), app.summary)
    app.live.frame()
    quick = axes_pixels(app)
    app.canvas.draw()
    normal = axes_pixels(app)
    d = np.abs(normal - quick).max(axis=2)
    assert d.mean() < 1.5 and (d > 40).mean() < 0.005


@window
def test_the_loop_never_waits_for_a_timer_tick_and_update_idletasks_returns(app):
    app.running = True
    app.settle_until = 0.0
    app.tick()
    ids = app.root.tk.splitlist(app.root.tk.call('after', 'info'))
    kinds = [app.root.tk.splitlist(app.root.tk.call('after', 'info', i))[1] for i in ids]
    assert kinds and all(k == 'timer' for k in kinds)              # after(0), never after_idle ...
    app.root.update_idletasks()                                   # ... which this would run forever
    app.running = False


@window
def test_pictures_leave_most_of_the_time_to_the_simulation(app, monkeypatch):
    from pcflow import gui
    app.running = True
    app.settle_until = 0.0
    app._frame_cost = 0.03                                        # a slow PC: 30 ms per picture
    app._last_frame = time.perf_counter() - 0.06                  # 60 ms ago: 20 a second would draw now
    drawn = []
    monkeypatch.setattr(app, 'show_frame', lambda: drawn.append(1))
    app.tick()
    assert drawn == []                                            # at most 30 % of the time: wait until 100 ms
    app._last_frame = time.perf_counter() - 0.11
    app.tick()
    assert drawn == [1]
    assert gui.FRAME_SHARE <= 0.3
    app.running = False


@window
def test_report_text_is_only_made_while_its_tab_is_open(app, monkeypatch):
    from pcflow import gui
    made = []
    monkeypatch.setattr(gui, 'text_report', lambda sim: made.append(1) or 'report')
    app.sim.update_probes()
    app.k = 39
    app.show_frame()                                              # every 40th picture, but the tab is closed
    assert made == []
    app.nb.select(app.tab_results)
    app.root.update()
    assert made                                                   # opening the tab fills it at once
    app.k = 39
    app.show_frame()
    assert len(made) >= 2


@window
def test_quick_drawing_failure_falls_back_to_normal(app, monkeypatch):
    def broken():
        raise RuntimeError('test')
    monkeypatch.setattr(app.live, 'frame', broken)
    app._paint()
    assert app.live is None
    app._paint()                                                  # normal drawing from now on
