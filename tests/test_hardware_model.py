"""Motherboard, RAM (DDR4 / DDR5 / ECC), storage, dust filters, altitude, fan curve, setup files."""
import glob
import json
import math
import os

import pytest

from pcflow import hardware as hw
from pcflow import thermal
from pcflow.config import Config, Fan, my_pc
from pcflow.layout import Layout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ITX = 'Mini-ITX (B650I / Z790I class)'
MATX = 'Micro-ATX (B650M / B760M class)'
WORKSTATION = 'ATX workstation (W680 / W880, ECC)'


def setup(**kw):
    cfg = my_pc()
    for k, v in kw.items():
        setattr(cfg, k, v)
    return cfg


def loads(**kw):
    return thermal.compute_loads(setup(**kw))


# ---------------------------------------------------------------- power
def test_power_breakdown_adds_up():
    ld = loads()
    parts = (ld['p_cpu'] + ld['p_gpu'] + ld['p_board'] + ld['p_ram'] + ld['p_storage'] + ld['p_fans']
             + ld['p_usb'])
    assert parts == pytest.approx(ld['p_dc'])
    assert ld['p_other'] == pytest.approx(ld['p_dc'] - ld['p_cpu'] - ld['p_gpu'])
    assert ld['p_board'] == pytest.approx(ld['p_chipset'] + ld['p_vrm'] + hw.BOARD_MISC_W)
    assert 15 < ld['p_other'] < 80                     # a sane "rest of the PC"


def test_max_draw_covers_everything_at_full_load():
    ld = loads()
    assert ld['p_dc_max'] >= loads(load='max')['p_dc'] - 1e-6


def test_ram_power_by_type_ecc_and_sticks():
    d4 = loads(ram_type='DDR4', cpu='Intel Core i5-13400F')['p_ram']
    d5 = loads(ram_type='DDR5', cpu='Intel Core i5-13400F')['p_ram']
    assert d5 > d4
    assert loads(ram_ecc=True)['p_ram'] > loads(ram_ecc=False)['p_ram']
    assert loads(ram_sticks=4)['p_ram'] == pytest.approx(2 * loads(ram_sticks=2)['p_ram'])


def test_ecc_on_an_intel_consumer_board_warns():
    ld = loads(cpu='Intel Core i7-14700K', ram_ecc=True)
    assert any('ECC' in w for w in ld['warnings'])
    ld = loads(cpu='Intel Core i7-14700K', ram_ecc=True, motherboard=WORKSTATION)
    assert not any('ECC' in w for w in ld['warnings'])
    ld = loads(cpu='AMD Ryzen 7 7800X3D', ram_ecc=True)
    assert not any('ECC' in w for w in ld['warnings'])


def test_wrong_memory_type_for_the_cpu_warns():
    assert any('DDR4' in w for w in loads(cpu='AMD Ryzen 7 5800X3D', ram_type='DDR5')['warnings'])
    assert any('DDR5' in w for w in loads(cpu='AMD Ryzen 7 7800X3D', ram_type='DDR4')['warnings'])
    assert not any('DDR' in w for w in loads(cpu='Intel Core i5-13400F', ram_type='DDR4')['warnings'])


def test_vrm_loss_grows_with_cpu_power():
    assert loads(load='max')['p_vrm'] > loads(load='gaming')['p_vrm'] > loads(load='idle')['p_vrm'] > 0


def test_storage_power():
    assert loads(nvme_count=0, hdd_count=0)['p_storage'] == 0
    assert loads(hdd_count=2)['p_hdd'] == pytest.approx(2 * hw.STORAGE_POWER['hdd']['gaming'])
    assert loads(nvme_count=3)['p_nvme'] == pytest.approx(3 * hw.STORAGE_POWER['nvme']['gaming'])


def test_fan_power_grows_with_speed():
    slow, fast = my_pc(), my_pc()
    for f in slow.fans:
        f.speed_pct = 40
    for f in fast.fans:
        f.speed_pct = 100
    assert thermal.compute_loads(fast)['p_fans'] > 3 * thermal.compute_loads(slow)['p_fans']


def test_aio_pump_counts():
    assert loads(cooler='AIO liquid 360 mm')['p_fans'] > loads()['p_fans']


# ---------------------------------------------------------------- motherboard geometry
@pytest.mark.parametrize('name', list(hw.MOTHERBOARDS))
def test_every_board_builds_with_its_own_size(name):
    L = Layout(setup(motherboard=name), 4.0)
    x0, x1, y0, y1 = L.draw['board']
    form = hw.BOARD_FORMS[hw.MOTHERBOARDS[name]['form']]
    assert x1 - x0 == pytest.approx(form['w'], abs=0.5)
    assert y1 - y0 == pytest.approx(form['h'], abs=0.5)
    assert len(L.draw['ram']) == form['ram_slots']
    assert L.draw['board_form'] == hw.MOTHERBOARDS[name]['form']


def test_itx_board_keeps_the_gpu_slot_and_moves_socket_and_ram():
    atx = Layout(my_pc(), 4.0)
    itx = Layout(setup(motherboard=ITX, ram_sticks=2), 4.0)
    assert itx.draw['gpu']['box'] == atx.draw['gpu']['box']      # the card uses the case's top slot
    assert len(itx.draw['ram']) == 2
    assert itx.socket[0] < atx.socket[0] and itx.socket[1] > atx.socket[1]
    assert itx.draw['ram'][0][0] < atx.draw['ram'][0][0]
    assert itx.draw['board'][1] - itx.draw['board'][0] == 170


def test_too_many_sticks_for_the_board_is_fixed():
    cfg = setup(motherboard=ITX, ram_sticks=4)
    notes = cfg.validate()
    assert cfg.ram_sticks == 2 and notes


def test_ram_is_a_heat_source_in_front_of_the_cooler():
    L = Layout(my_pc(), 4.0)
    ram = next(h for h in L.heat if h['name'] == 'ram')
    assert ram['P'] == pytest.approx(L.loads['p_ram'])
    assert ram['mask'].any()
    assert sum(L.draw['ram_used']) == 2


def test_board_heat_includes_vrm_chipset_and_ssds():
    L = Layout(setup(nvme_count=2), 4.0)
    board = next(h for h in L.heat if h['name'] == 'board')
    ld = L.loads
    assert board['P'] == pytest.approx(ld['p_board'] + ld['p_nvme'] + ld['p_fans'])


def test_all_heat_put_in_the_case_is_accounted_for():
    L = Layout(setup(hdd_count=2, nvme_count=2, ram_sticks=4), 4.0)
    ld = L.loads
    inside = sum(h['P'] for h in L.heat)
    assert inside == pytest.approx(ld['p_dc'] - ld['p_usb'] + ld['p_psu'])


# ---------------------------------------------------------------- hard drives
def test_hdd_cage_sits_under_the_shroud_blocks_air_and_heats():
    L = Layout(setup(hdd_count=2), 4.0)
    hdd = next(h for h in L.heat if h['name'] == 'hdd')
    assert hdd['P'] == pytest.approx(2 * hw.STORAGE_POWER['hdd']['gaming'])
    x0, x1, y0, y1 = L.draw['hdd']['cage']
    assert y1 <= L.sh and x0 >= 150.0               # in front of the PSU, below the shroud
    assert len(L.draw['hdd']['drives']) == 2
    assert (L.Kx[L.cells(x0, x1, y0, y1)] > 0).any()


def test_no_hdd_no_cage():
    L = Layout(my_pc(), 4.0)
    assert L.draw['hdd'] is None
    assert not any(h['name'] == 'hdd' for h in L.heat)


def test_hdd_without_shroud_goes_on_the_floor():
    cfg = setup(hdd_count=1)
    cfg.case.shroud = False
    L = Layout(cfg, 4.0)
    x0, x1, y0, y1 = L.draw['hdd']['cage']
    assert y0 == pytest.approx(0.0, abs=0.1) and x1 <= L.D - 26


# ---------------------------------------------------------------- dust filters
def front_k(cfg):
    L = Layout(cfg, 4.0)
    f = next(f for f in L.fans if f.wall == 'front')
    return float(L.Kx[L.cells(*L.box_of(f.axis, f.band, f.span))].max())


def test_dusty_and_clogged_filters_raise_resistance():
    k = [front_k(setup(filter_condition=c)) for c in ('clean', 'dusty', 'clogged')]
    assert k[0] < k[1] < k[2]


def test_open_mesh_has_no_filter_to_clog():
    a, b = setup(filter_condition='clean'), setup(filter_condition='clogged')
    a.case.front_panel = b.case.front_panel = 'open mesh'
    assert front_k(a) == front_k(b)


# ---------------------------------------------------------------- altitude
def test_air_density():
    assert thermal.air_density(0, 22) == pytest.approx(1.196, abs=0.01)
    assert thermal.air_density(1000, 22) == pytest.approx(1.06, abs=0.015)
    assert thermal.air_density(2000, 22) < thermal.air_density(1000, 22)
    assert thermal.air_density(0, 40) < thermal.air_density(0, 10)


def test_altitude_lowers_fan_pressure_not_free_airflow():
    lo, hi = Layout(my_pc(), 4.0), Layout(setup(altitude_m=2000), 4.0)
    a = next(f for f in lo.fans if f.label == 'Fan 1')
    b = next(f for f in hi.fans if f.label == 'Fan 1')
    assert b.ufree == pytest.approx(a.ufree)
    assert b.pmax < a.pmax
    assert hi.rho < lo.rho


def test_altitude_raises_the_temperature_estimate():
    cfg0, cfg2 = my_pc(), setup(altitude_m=2000)
    t0 = thermal.estimate_temps(cfg0, thermal.compute_loads(cfg0), 30.0, 30.0)
    t2 = thermal.estimate_temps(cfg2, thermal.compute_loads(cfg2), 30.0, 30.0)
    assert t2['t_cpu'] > t0['t_cpu'] and t2['t_gpu'] > t0['t_gpu']


# ---------------------------------------------------------------- fan curve
CURVE = dict(source='hottest', t_lo=50.0, pct_lo=30.0, t_hi=80.0, pct_hi=100.0)


def test_fan_curve_shape():
    assert thermal.fan_curve_frac(CURVE, 40) == pytest.approx(0.30)
    assert thermal.fan_curve_frac(CURVE, 65) == pytest.approx(0.65)
    assert thermal.fan_curve_frac(CURVE, 95) == pytest.approx(1.00)


def test_fan_curve_source():
    assert thermal.curve_temp(dict(CURVE, source='cpu'), 70, 60) == 70
    assert thermal.curve_temp(dict(CURVE, source='gpu'), 70, 60) == 60
    assert thermal.curve_temp(CURVE, 70, 75) == 75


def test_auto_case_fan_starts_on_the_curve():
    cfg = my_pc()
    cfg.fans[0].speed_pct = -1
    assert cfg.fans[0].auto and cfg.fans[0].rpm == 0
    L = Layout(cfg, 4.0)
    f = next(f for f in L.fans if f.label == 'Fan 1')
    assert f.auto and 0.3 <= f.frac <= 1.0
    other = next(f for f in L.fans if f.label == 'Fan 2')
    assert not other.auto and other.frac == pytest.approx(0.70)


def test_set_fan_frac_updates_the_fan():
    L = Layout(my_pc(), 4.0)
    f = next(f for f in L.fans if f.label == 'Fan 1')
    u, p = f.ufree, f.pmax
    L.set_fan_frac(f, 0.35)
    assert f.ufree == pytest.approx(u * 0.35 / 0.70)
    assert f.pmax == pytest.approx(p * (0.35 / 0.70) ** 2)
    assert f.rpm == pytest.approx(f.rpm100 * 0.35)
    L.set_fan_frac(f, 0.0)
    assert not f.active


# ---------------------------------------------------------------- setup files
NEW = dict(motherboard=MATX, ram_sticks=4, ram_type='DDR5', ram_ecc=True, nvme_count=3, hdd_count=1,
           filter_condition='dusty', altitude_m=900.0)


def test_round_trip_keeps_new_fields():
    cfg = setup(**NEW)
    cfg.fan_curve = dict(source='cpu', t_lo=45.0, pct_lo=25.0, t_hi=85.0, pct_hi=90.0)
    cfg.fans[2].speed_pct = -1
    c2 = Config.from_dict(json.loads(json.dumps(cfg.to_dict())))
    for k, v in NEW.items():
        assert getattr(c2, k) == v, k
    assert c2.fan_curve == cfg.fan_curve
    assert c2.fans[2].auto
    assert c2.notes == []


@pytest.mark.parametrize('path', sorted(glob.glob(os.path.join(ROOT, 'configs', '*.json'))))
def test_shipped_setups_load_cleanly(path):
    cfg = Config.read(path)
    assert cfg.notes == []
    Layout(cfg, 4.0)


def test_old_setup_without_new_fields_gets_defaults():
    d = my_pc().to_dict()
    for k in list(NEW) + ['fan_curve', 'custom_parts']:
        d.pop(k, None)
    cfg = Config.from_dict(d)
    assert cfg.motherboard in hw.MOTHERBOARDS and cfg.ram_sticks == 2 and cfg.altitude_m == 0


def _set(d, path, value):
    *head, last = path
    for k in head:
        d = d[k]
    d[last] = value


@pytest.mark.parametrize('path,value', [
    (('case', 'depth_mm'), 'abc'), (('fans', 0, 'speed_pct'), 'fast'), (('altitude_m',), float('nan')),
    (('ram_sticks',), 99), (('fans',), 'nope'), (('fan_curve',), {'t_lo': 90, 't_hi': 40}),
    (('case',), None), (('room_c',), float('inf')), (('fans', 1), 'x'), (('hdd_count',), -4),
    (('psu_watts',), 'big'), (('fans', 0, 'wall'), 7), (('case', 'shroud'), 'yes'),
    (('cooler_fans',), 2.7), (('motherboard',), ['ATX']),
])
def test_bad_values_in_a_setup_file_are_fixed_not_a_crash(path, value):
    d = my_pc().to_dict()
    _set(d, path, value)
    cfg = Config.from_dict(d)
    assert cfg.notes
    assert cfg.validate() == []
    Layout(cfg, 4.0)
    assert all(math.isfinite(x) for x in (cfg.room_c, cfg.altitude_m, cfg.case.depth_mm))


def test_too_many_fans_in_a_file_are_cut():
    d = my_pc().to_dict()
    d['fans'] = d['fans'] * 20
    cfg = Config.from_dict(d)
    assert len(cfg.fans) <= 40 and cfg.notes


def test_setup_json_reads_rpm_instead_of_percent():
    d = my_pc().to_dict()
    d['fans'][0].pop('speed_pct')
    d['fans'][0]['rpm'] = 750
    cfg = Config.from_dict(d)
    assert cfg.fans[0].speed_pct == pytest.approx(50.0)
