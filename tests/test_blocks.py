"""Blocks: parts you place yourself (something that stops the air, cables, a grille, a part that makes heat)."""
import json

import matplotlib.pyplot as plt
import numpy as np
import pytest

from pcflow import hardware as hw
from pcflow import library as lib
from pcflow import placement
from pcflow.config import Block, Config, Fan, MAX_BLOCKS, my_pc
from pcflow.layout import Layout, SOLID, BLOCK_K
from pcflow.render import CaseView, ReportFrame, drawing_key
from pcflow.results import summarize, text_report
from pcflow.solver import Solver
from pcflow.thermal import compute_loads

WALL = 'Block (no air through)'


def run(cfg, seconds=2.5, h=4.0):
    sim = Solver(Layout(cfg, h), n_particles=50)
    sim.run(seconds)
    return sim, summarize(sim)


def with_blocks(*blocks):
    cfg = my_pc()
    cfg.blocks = list(blocks)
    return cfg


def nothing_left_out(cfg):
    for h in (4.0, 3.0, 2.0):
        L = Layout(cfg, h)
        assert L.draw['rejected'] == [] and L.draw['rejected_blocks'] == [], (h, L.warnings)


# ---------------------------------------------------------------- setup files
def test_blocks_survive_a_save_and_reopen(tmp_path):
    cfg = with_blocks(Block.of('Pump + reservoir', 330, 300), Block('Cable bundle', 360, 160, 30, 150, 'cables', 0))
    p = tmp_path / 'setup.json'
    cfg.write(str(p))
    back = Config.read(str(p))
    assert back.blocks == cfg.blocks and back.notes == []
    assert json.loads(p.read_text(encoding='utf-8'))['version'] == 3


def test_missing_block_values_come_from_its_kind():
    cfg = Config.from_dict(dict(blocks=[dict(model='Capture / sound card', x_mm=150, y_mm=170)]))
    b = cfg.blocks[0]
    spec = hw.BLOCKS['Capture / sound card']
    assert (b.w_mm, b.h_mm, b.air, b.watts) == (spec['w'], spec['h'], spec['air'], spec['watts'])
    assert cfg.notes == []


def test_bad_block_values_are_fixed_and_listed():
    cfg = Config.from_dict(dict(blocks=[
        dict(model='no such kind', w_mm='wide', air='glass', watts=-5, colour='red'),
        'junk', dict(x_mm=float('nan'), h_mm=1e9, watts=1e6)]))
    notes = ' | '.join(cfg.notes)
    for word in ('unknown', 'glass', 'wide', 'heat', 'unreadable', 'colour', 'position', 'height'):
        assert word in notes, word
    assert len(cfg.blocks) == 2
    for b in cfg.blocks:
        assert b.model in hw.BLOCKS and b.air in hw.BLOCK_AIR
        assert hw.BLOCK_MIN_MM <= b.w_mm <= hw.BLOCK_MAX_MM and hw.BLOCK_MIN_MM <= b.h_mm <= hw.BLOCK_MAX_MM
        assert 0 <= b.watts <= hw.MAX_BLOCK_WATTS and np.isfinite(b.x_mm)


def test_too_many_blocks_and_an_unreadable_list():
    cfg = Config.from_dict(dict(blocks=[dict(model=WALL)] * (MAX_BLOCKS + 5)))
    assert len(cfg.blocks) == MAX_BLOCKS and any('only the first' in n for n in cfg.notes)
    cfg = Config.from_dict(dict(blocks='lots'))
    assert cfg.blocks == [] and any('block list' in n for n in cfg.notes)


def test_old_setups_without_blocks_still_open():
    d = my_pc().to_dict()
    d.pop('blocks')
    d['version'] = 2
    cfg = Config.from_dict(d)
    assert cfg.blocks == [] and cfg.notes == []


# ---------------------------------------------------------------- what a block does to the case
def test_a_solid_block_stops_the_air_and_others_slow_it():
    base = Layout(my_pc(), 4.0)
    cfg = with_blocks(Block(WALL, 330, 330, 40, 60, 'solid', 0), Block('Cable bundle', 380, 160, 30, 100, 'cables', 0))
    L = Layout(cfg, 4.0)
    assert (L.ct == SOLID).sum() > (base.ct == SOLID).sum()
    sl = L.cells(365, 395, 110, 210)
    assert np.allclose(L.Kx[sl], BLOCK_K['cables']) and np.allclose(L.Ky[sl], BLOCK_K['cables'])
    assert [b['label'] for b in L.draw['blocks']] == ['Block 1', 'Block 2']


def test_a_wall_behind_the_intakes_cuts_the_airflow():
    _, s0 = run(my_pc())
    _, s1 = run(with_blocks(Block(WALL, 380, 250, 30, 330, 'solid', 0)))
    assert s1['cfm_in'] < 0.6 * s0['cfm_in']
    assert s1['cpu_in'] > s0['cpu_in'] + 1.0


def test_a_part_that_makes_heat_warms_its_air_and_counts_everywhere():
    cfg = with_blocks(Block('Heat source', 300, 300, 60, 40, 'cables', 60.0))
    ld, ld0 = compute_loads(cfg), compute_loads(my_pc())
    assert ld['p_blocks'] == 60 and ld['p_dc'] == pytest.approx(ld0['p_dc'] + 60)
    assert ld['p_dc_max'] == pytest.approx(ld0['p_dc_max'] + 60)
    sim, s = run(cfg, 3.0)
    assert s['blocks'][0]['t_air'] > cfg.room_c + 10
    r = sim.raw
    assert abs(r['heat_out'] - r['heat_in']) / r['heat_in'] < 0.15
    L = sim.L
    assert sum(h['P'] for h in L.heat) == pytest.approx(L.loads['p_dc'] - L.loads['p_usb'] + L.loads['p_psu'])


def test_heat_of_a_solid_block_goes_into_the_air_round_it():
    cfg = with_blocks(Block(WALL, 300, 300, 50, 50, 'solid', 30.0))
    L = Layout(cfg, 4.0)
    heat = next(h for h in L.heat if h['name'] == 'block 1')
    assert heat['mask'].any() and (L.ct[heat['mask']] != SOLID).all()
    sim, s = run(cfg, 2.0)
    assert s['blocks'][0]['t_air'] > cfg.room_c + 2


def test_touching_solid_blocks_never_heat_a_solid_cell():
    cfg = with_blocks(Block(WALL, 300, 300, 50, 50, 'solid', 30.0), Block(WALL, 350, 300, 50, 50, 'solid', 0.0))
    L = Layout(cfg, 3.0)
    assert L.draw['rejected_blocks'] == []
    for h in L.heat:
        assert (L.ct[h['mask']] != SOLID).all(), h['name']


def test_a_block_on_a_part_is_left_out_but_its_heat_counts():
    g = Layout(my_pc(), 4.0).gpu_box
    cfg = with_blocks(Block('Heat source', 0.5 * (g[0] + g[1]), 0.5 * (g[2] + g[3]), 60, 40, 'cables', 25.0))
    L = Layout(cfg, 4.0)
    assert L.draw['rejected_blocks'][0]['why'] == 'the GPU'
    assert any('Block 1 overlaps the GPU' in w for w in L.warnings)
    assert sum(h['P'] for h in L.heat) == pytest.approx(L.loads['p_dc'] - L.loads['p_usb'] + L.loads['p_psu'])


def test_a_block_outside_the_case_is_kept_inside():
    L = Layout(with_blocks(Block(WALL, 900, -40, 80, 80, 'solid', 0)), 4.0)
    x0, x1, y0, y1 = L.draw['blocks'][0]['box']
    assert 0 <= x0 < x1 <= L.D and 0 <= y0 < y1 <= L.H
    assert any('did not fit there' in w for w in L.warnings)


def test_fans_never_stay_on_a_block():
    cfg = with_blocks(Block(WALL, 400, 130, 60, 100, 'solid', 0))
    L = Layout(cfg, 4.0)
    assert [r['why'] for r in L.draw['rejected']] == ['Block 1']
    notes = placement.resolve(cfg)
    assert any('Fan 1 overlapped Block 1' in n for n in notes)
    nothing_left_out(cfg)


# ---------------------------------------------------------------- air that cannot get out
def test_a_case_without_fans_still_gets_a_sound_answer():
    cfg = my_pc()
    cfg.fans = []
    sim = Solver(Layout(cfg, 4.0), n_particles=20)
    sim.run(0.3)
    assert sim.geo.sealed and np.isfinite(sim.u).all() and np.isfinite(sim.T).all()
    assert any('No fan or opening' in w for w in sim.L.warnings)


def test_a_pocket_closed_in_by_blocks_is_reported_and_stays_finite():
    x, y, s, t = 330.0, 330.0, 60.0, 6.0               # a closed square of four panels
    cfg = with_blocks(Block(WALL, x, y + s / 2, s + t, t, 'solid', 0), Block(WALL, x, y - s / 2, s + t, t, 'solid', 0),
                      Block(WALL, x - s / 2, y, t, s - t, 'solid', 0), Block(WALL, x + s / 2, y, t, s - t, 'solid', 0))
    L = Layout(cfg, 3.0)
    assert L.draw['rejected_blocks'] == []
    sim = Solver(L, n_particles=20)
    sim.run(0.3)
    assert len(sim.geo.sealed) == 1 and sim.geo.sealed[0] < 0.1 * sim.geo.n_air
    assert any('pocket' in w for w in L.warnings)
    assert np.isfinite(sim.u).all()
    r = sim.raw
    assert abs(r['cfm_in'] - r['cfm_out']) / r['cfm_in'] < 0.01


def test_no_ready_made_setup_has_closed_pockets():
    from pcflow.config import PRESETS, QUALITY_MM
    from pcflow.solver import Geometry
    for make in PRESETS.values():
        for h in QUALITY_MM.values():
            assert Geometry(Layout(make(), h).ct).sealed == []


# ---------------------------------------------------------------- placing blocks
def test_new_blocks_never_land_on_anything():
    cfg = my_pc()
    for kind in hw.BLOCKS:
        b = Block.of(kind, 220, 250)
        ok, note = placement.place_new_block(cfg, b, near=(220, 250))
        assert ok, note
        cfg.blocks.append(b)
        nothing_left_out(cfg)


def test_a_block_moved_onto_the_gpu_snaps_right_beside_it():
    cfg = with_blocks(Block.of('Pump + reservoir', 330, 300))
    g = Layout(cfg, 4.0).gpu_box
    b = cfg.blocks[0]
    b.x_mm, b.y_mm = 0.5 * (g[0] + g[1]), 0.5 * (g[2] + g[3])
    ok, note = placement.snap_block(cfg, 0)
    assert ok and 'the GPU' in note
    nothing_left_out(cfg)


def test_a_snapped_block_touches_what_it_hit():
    """the nearest free spot is found exactly, not on a coarse grid"""
    cfg = with_blocks(Block(WALL, 100, 160, 40, 30, 'solid', 0))     # just under the GPU, overlapping it a little
    g = Layout(cfg, 4.0).gpu_box
    cfg.blocks[0].y_mm = g[2] - 15 + 8
    ok, _ = placement.snap_block(cfg, 0)
    assert ok and cfg.blocks[0].y_mm == pytest.approx(g[2] - 15, abs=0.2)


def test_a_block_too_big_for_any_free_spot_is_refused():
    cfg = my_pc()
    b = Block(WALL, 220, 220, 420, 420, 'solid', 0)
    ok, note = placement.place_new_block(cfg, b)
    assert not ok and 'No room' in note


def test_fix_overlaps_moves_overlapping_blocks():
    g = Layout(my_pc(), 4.0).gpu_box
    cfg = with_blocks(Block.of('Pump + reservoir', 330, 300), Block.of('Capture / sound card', 150, 0.5 * (g[2] + g[3])))
    notes = placement.resolve(cfg)
    assert any('Block 2 overlapped the GPU' in n for n in notes)
    nothing_left_out(cfg)
    assert placement.resolve(cfg) == []


def test_a_smaller_case_moves_blocks_inside():
    cfg = with_blocks(Block.of('Pump + reservoir', 400, 300))
    cfg.case.depth_mm, cfg.case.shroud_length_mm = 330, 280
    notes = placement.resolve(cfg)
    assert any('stuck out' in n for n in notes)
    b = cfg.blocks[0]
    assert b.x_mm + b.w_mm / 2 <= 330 + 1e-6
    nothing_left_out(cfg)


# ---------------------------------------------------------------- your own kinds of blocks
def test_your_own_block_kind_is_checked_saved_and_travels_with_the_setup(tmp_path):
    lib.add('block', 'My reservoir', dict(w=70, h=150, air='dense', watts=8))
    assert hw.BLOCKS['My reservoir']['watts'] == 8 and 'block' in lib.CATEGORIES
    with pytest.raises(lib.PartError):
        lib.add('block', 'Broken', dict(w=1, h=150, air='glass', watts=-1))
    cfg = with_blocks(Block.of('My reservoir', 330, 300))
    p = tmp_path / 'with_reservoir.json'
    cfg.write(str(p))
    assert 'My reservoir' in json.loads(p.read_text(encoding='utf-8'))['custom_parts']['block']
    lib.reset()                                       # another PC: only the setup file has the part
    assert 'My reservoir' not in hw.BLOCKS
    back = Config.read(str(p))
    assert back.blocks[0].model == 'My reservoir' and back.notes == []
    assert lib.summary('block', 'My reservoir') == '70 × 150 mm · dense · 8 W'


# ---------------------------------------------------------------- report and pictures
def test_report_lists_the_blocks():
    cfg = with_blocks(Block.of('Pump + reservoir', 330, 300), Block(WALL, 900, 900, 600, 600, 'solid', 0))
    sim, _ = run(cfg, 0.6)
    txt = text_report(sim)
    assert 'Pump + reservoir' in txt and 'left out' in txt and 'your blocks 6 W' in txt


def test_blocks_are_drawn_and_a_moved_block_redraws():
    cfg = with_blocks(Block.of('Pump + reservoir', 330, 300), Block('Divider panel', 300, 40, 4, 70, 'solid', 0),
                      Block.of('Mesh / grille', 405, 330), Block.of('2.5" SSD', 230, 120))
    L = Layout(cfg, 4.0)
    assert L.draw['rejected_blocks'] == []
    sim = Solver(L, n_particles=50)
    sim.run(0.2)
    fig = plt.figure()
    view = CaseView(fig.add_axes([0, 0, 1, 1]), L, fs=0.78)
    view.update(1, sim.interior_T(), sim.frame_particles(), summarize(sim))
    texts = [t.get_text() for t in view.ax.texts]
    assert any('Pump + reservoir · 6 W' in t for t in texts) and any('Divider panel' in t for t in texts)
    assert [t.get_text() for _, t in view.t_blocks][0].startswith('air ≈')
    fig.canvas.draw()
    plt.close(fig)
    key = drawing_key(L)
    cfg.blocks[0].x_mm += 20
    assert drawing_key(Layout(cfg, 4.0)) != key


def test_report_picture_with_blocks():
    cfg = with_blocks(Block.of('Heat source', 300, 300), Block.of('Cable bundle', 360, 160))
    L = Layout(cfg, 4.0)
    sim = Solver(L, n_particles=50)
    sim.run(0.2)
    frame = ReportFrame(L, width=540, height=960, dpi=60)
    frame.update(0, sim.interior_T(), sim.frame_particles(), summarize(sim))
    assert frame.rgb().shape == (960, 540, 3)
    assert any('2 blocks' in t.get_text() for t in frame.fig.texts)
    plt.close(frame.fig)


def test_a_fan_added_inside_never_lands_on_a_block():
    cfg = with_blocks(Block(WALL, 330, 330, 120, 120, 'solid', 0))
    fan = Fan('inside', 330, 330, 'up')
    ok, note = placement.place_new(cfg, fan, near=(330, 330))
    assert ok, note
    cfg.fans.append(fan)
    nothing_left_out(cfg)


def test_random_block_setups_never_break():
    """any mix of blocks: no crash, finite numbers, no heat in a solid cell, every watt accounted for, and Fix
    overlaps leaves nothing on top of anything (a second run changes nothing)"""
    import random
    from pcflow.config import PRESETS
    rng = random.Random(7)
    for _ in range(12):
        cfg = rng.choice(list(PRESETS.values()))()
        cfg.case.shroud = rng.random() > 0.3
        cfg.blocks = []
        for _ in range(rng.randint(1, 8)):
            b = Block.of(rng.choice(list(hw.BLOCKS)), rng.uniform(-50, 500), rng.uniform(-50, 500))
            if rng.random() < 0.5:
                b.w_mm, b.h_mm = rng.uniform(2, 300), rng.uniform(2, 300)
            b.air, b.watts = rng.choice(list(hw.BLOCK_AIR)), rng.choice([0, 5, 40, 150])
            cfg.blocks.append(b)
        cfg.validate()
        L = Layout(cfg, 4.0)
        assert all((L.ct[h['mask']] != SOLID).all() for h in L.heat)
        ld = L.loads
        assert sum(h['P'] for h in L.heat) == pytest.approx(ld['p_dc'] - ld['p_usb'] + ld['p_psu'])
        sim = Solver(L, n_particles=20)
        sim.run(0.2)
        assert np.isfinite(sim.u).all() and np.isfinite(sim.v).all() and np.isfinite(sim.T).all()
        text_report(sim)
        notes = placement.resolve(cfg)
        if not any('no free spot' in n for n in notes):
            assert Layout(cfg, 4.0).draw['rejected_blocks'] == []
            assert placement.resolve(cfg) == []


# ---------------------------------------------------------------- found in review
def test_a_snapped_block_is_checked_where_it_is_stored():
    """the free spot is checked at 0.1 mm, as stored: a rounded spot may not end up 1.05 mm on a fan"""
    cfg = with_blocks(Block('Divider panel', 10, 330, 4.3, 100, 'solid', 0))
    ok, _ = placement.snap_block(cfg, 0, near=(10, 330))
    assert ok
    nothing_left_out(cfg)
    for w10 in range(41, 80):                                      # widths with an odd tenth
        cfg = with_blocks(Block('Divider panel', 10, 330, w10 / 10, 100, 'solid', 0))
        assert placement.snap_block(cfg, 0, near=(10, 330))[0]
        assert Layout(cfg, 4.0).draw['rejected'] == [], w10


def test_a_side_fan_never_goes_onto_a_solid_block():
    cfg = with_blocks(Block(WALL, 250, 330, 160, 160, 'solid', 0))
    fan = Fan('side', 250, 330, 'in')
    probe = placement.Probe(cfg)
    assert probe.why(fan) == 'a solid part'
    ok, _ = placement.place_new(cfg, fan, near=(250, 330))
    assert ok
    cfg.fans.append(fan)
    nothing_left_out(cfg)
    cfg.fans[-1].pos_mm, cfg.fans[-1].pos2_mm = 250, 330          # e.g. from a file: Fix overlaps really moves it
    assert any('Fan 8 overlapped a solid part' in n for n in placement.resolve(cfg))
    nothing_left_out(cfg)
    assert placement.resolve(cfg) == []


def test_side_fans_are_a_way_in_and_out():
    m = hw.DEFAULT_CASE_FAN
    cfg = my_pc()
    cfg.fans = [Fan('side', 300, 250, 'in', m, 100), Fan('side', 120, 330, 'out', m, 100)]
    sim, s = run(cfg, 2.0)
    assert not any('No fan or opening' in w or 'pocket' in w for w in sim.L.warnings)
    r = sim.raw
    assert abs(r['cfm_in'] - r['cfm_out']) / r['cfm_in'] < 0.01


def test_a_block_touching_the_gpu_never_takes_its_heat():
    cfg = with_blocks(Block(WALL, 137, 259.5, 80, 20, 'solid', 0))
    for h in (4.0, 3.0, 2.0):
        L = Layout(cfg, h)
        assert L.draw['rejected_blocks'] == []
        for src in L.heat:
            assert (L.ct.ravel()[src['idx']] != SOLID).all(), (h, src['name'])
        assert sum(src['P'] for src in L.heat) == pytest.approx(L.loads['p_dc'] - L.loads['p_usb'] + L.loads['p_psu'])
