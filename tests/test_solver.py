"""Physics checks on the coarse (fast) grid: conservation and the direction of every new effect."""
import pytest

from pcflow.config import my_pc
from pcflow.layout import Layout
from pcflow.results import summarize, text_report
from pcflow.solver import Solver


def run(cfg, seconds=2.5, h=4.0, previous=None):
    sim = Solver(Layout(cfg, h), n_particles=50, previous=previous)
    sim.run(seconds)
    return sim, summarize(sim)


def test_mass_balance_is_exact():
    sim, _ = run(my_pc(), 1.5)
    r = sim.raw
    assert abs(r['cfm_in'] - r['cfm_out']) / r['cfm_in'] < 0.01


def test_energy_balance_with_every_new_heat_source():
    cfg = my_pc()
    cfg.hdd_count, cfg.nvme_count, cfg.ram_sticks = 2, 2, 4
    sim, _ = run(cfg, 3.5)
    r = sim.raw
    assert abs(r['heat_out'] - r['heat_in']) / r['heat_in'] < 0.15


def test_altitude_same_airflow_hotter_air():
    _, s0 = run(my_pc())
    cfg = my_pc()
    cfg.altitude_m = 2500
    _, s1 = run(cfg)
    assert s1['cfm_in'] == pytest.approx(s0['cfm_in'], rel=0.05)
    assert s1['cpu_in'] > s0['cpu_in'] + 0.2
    assert s1['t_cpu'] > s0['t_cpu']
    assert s1['t_gpu'] > s0['t_gpu']


def test_clogged_filters_cut_airflow():
    _, s0 = run(my_pc(), 2.0)
    cfg = my_pc()
    cfg.filter_condition = 'clogged'
    _, s1 = run(cfg, 2.0)
    assert s1['cfm_in'] < 0.97 * s0['cfm_in']


def test_drives_in_the_basement_warm_the_psu_area():
    cfg = my_pc()
    cfg.hdd_count = 3
    sim, s = run(cfg, 2.5)
    assert s['t_hdd'] is not None and s['t_hdd'] > cfg.room_c


def auto_setup(load):
    cfg = my_pc()
    cfg.load = load
    for f in cfg.fans:
        f.speed_pct = -1
    return cfg


def test_auto_fans_speed_up_under_load():
    _, idle = run(auto_setup('idle'), 3.0)
    _, hot = run(auto_setup('max'), 3.0)
    rpm = lambda s: next(f['rpm'] for f in s['fans'] if f['label'] == 'Fan 1')
    assert rpm(hot) > rpm(idle) + 100
    assert all(f['auto'] for f in hot['fans'] if f['kind'] == 'case')


def test_auto_fan_speed_carries_over_when_the_setup_changes():
    sim, _ = run(auto_setup('max'), 2.0)
    before = next(f.frac for f in sim.L.fans if f.label == 'Fan 1')
    sim2 = Solver(Layout(auto_setup('max'), 4.0), n_particles=50, previous=sim)
    after = next(f.frac for f in sim2.L.fans if f.label == 'Fan 1')
    assert after == pytest.approx(before)


def test_fixed_speed_fans_never_change():
    sim, _ = run(my_pc(), 1.0)
    assert all(f.frac == pytest.approx(0.70) for f in sim.L.fans if f.kind == 'case')


def test_report_lists_the_new_parts():
    cfg = my_pc()
    cfg.hdd_count, cfg.ram_ecc, cfg.altitude_m = 1, True, 900
    cfg.fans[0].speed_pct = -1
    sim, _ = run(cfg, 0.6)
    txt = text_report(sim)
    for word in ('Motherboard', 'RAM', 'ECC', 'hard drive', 'altitude', 'auto'):
        assert word in txt, word
