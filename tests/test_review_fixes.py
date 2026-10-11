"""Regression tests for the findings of the ECC review agents (python / security / silent-failure)."""
import json
import math
import os
import sys

import matplotlib.pyplot as plt
import pytest

from pcflow import cli, hardware as hw, library as lib, video
from pcflow.config import Config, my_pc
from pcflow.layout import Layout
from pcflow.render import ReportFrame
from pcflow.results import summarize
from pcflow.solver import Solver

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GPU = dict(tbp=250, length=300, slots=2.5, fans=3)


# ---------------------------------------------------------------- card length
@pytest.mark.parametrize('length', [5, 12, 60, 119])
def test_impossible_card_length_is_refused_and_simulates(length):
    d = my_pc().to_dict()
    d['gpu_length_mm'] = length
    cfg = Config.from_dict(d)
    assert cfg.gpu_length_mm == 0 and any('Card length' in n for n in cfg.notes)
    cfg.gpu_length_mm = length                     # even if something sets it later
    sim = Solver(Layout(cfg, 4.0), n_particles=20)
    sim.run(0.3)
    s = summarize(sim)
    assert math.isfinite(s['t_gpu']) and math.isfinite(s['gpu_in'])


# ---------------------------------------------------------------- hostile files
def test_huge_numbers_do_not_crash_the_setup_reader():
    d = my_pc().to_dict()
    d['room_c'] = 10 ** 400
    d['case']['depth_mm'] = -10 ** 400
    d['fans'][0]['speed_pct'] = 10 ** 400
    d['fans'][1].pop('speed_pct')
    d['fans'][1]['rpm'] = 10 ** 400
    cfg = Config.from_dict(d)
    assert cfg.notes and cfg.validate() == []
    Layout(cfg, 4.0)


def test_huge_numbers_do_not_crash_the_parts_check():
    with pytest.raises(lib.PartError):
        lib.add('gpu', 'Huge', dict(GPU, tbp=10 ** 400))


def deep(n):
    return '[' * n + ']' * n


def test_deeply_nested_setup_gives_a_clear_error(tmp_path):
    p = tmp_path / 'deep.json'
    p.write_text('{"fans": %s}' % deep(100000), encoding='utf-8')
    with pytest.raises(ValueError):
        Config.read(str(p))


def test_moderately_nested_setup_is_read_without_copying_it():
    d = my_pc().to_dict()
    d['junk'] = json.loads(deep(800))              # deeper than copy.deepcopy allows
    cfg = Config.from_dict(d)
    assert any('Unknown settings' in n for n in cfg.notes)


def test_deeply_nested_parts_file_never_stops_the_app(isolated_parts):
    isolated_parts.write_text('{"parts": %s}' % deep(100000), encoding='utf-8')
    notes = lib.load()
    assert notes and 'could not be read' in notes[0]


@pytest.mark.skipif(not hasattr(os, 'mkfifo'), reason='needs named pipes')
def test_pipes_and_devices_are_refused(tmp_path, monkeypatch):
    fifo = tmp_path / 'setup.json'
    os.mkfifo(fifo)
    with pytest.raises(ValueError):
        Config.read(str(fifo))
    monkeypatch.setenv('PCFLOW_PARTS', str(fifo))
    assert 'not a normal file' in lib.load()[0]
    if os.path.exists('/dev/zero'):
        link = tmp_path / 'zero.json'
        link.symlink_to('/dev/zero')
        with pytest.raises(ValueError):
            Config.read(str(link))


# ---------------------------------------------------------------- names
@pytest.mark.parametrize('name', ['Card \ud800', 'Card \udcff', 'Card‮evil', 'Card​',
                                  'Noctua NF-A12x25 PWM', 'Noctua NF-A12x25 PWMㅤ',
                                  'Noctua NF-A12x25 PWM️', 'noctua nf-a12x25 pwm'])
def test_invisible_broken_and_lookalike_names_are_refused(name):
    with pytest.raises(lib.PartError):
        lib.add('fan', name, dict(size=120, rpm=1500, cfm=55, mmh2o=1.6))


def test_arabic_names_are_fine():
    assert lib.add('gpu', 'كرت الشاشة الخاص بي', GPU) in hw.GPUS


def test_unusable_case_name_is_replaced_and_saving_works(tmp_path):
    d = my_pc().to_dict()
    d['case']['name'] = 'Case \ud800‮' + 'x' * 500
    cfg = Config.from_dict(d)
    assert cfg.case.name == 'Custom case' and cfg.notes
    cfg.write(str(tmp_path / 'ok.json'))


# ---------------------------------------------------------------- parts file never loses entries
def test_parts_file_keeps_what_this_version_cannot_use(isolated_parts):
    isolated_parts.write_text(json.dumps({'format': lib.FILE_FORMAT, 'version': 7, 'parts': {
        'gpu': {'Typo card': dict(GPU, tbp=1200), 'Good card': GPU},
        'psu': {'My PSU': {'watts': 850}}}}), encoding='utf-8')
    notes = lib.load()
    assert any('newer version' in n for n in notes) and any('Typo card' in n for n in notes)
    lib.add('gpu', 'New card', GPU)
    data = json.loads(isolated_parts.read_text(encoding='utf-8'))
    assert data['parts']['gpu']['Typo card']['tbp'] == 1200
    assert data['parts']['psu'] == {'My PSU': {'watts': 850}}
    assert {'Good card', 'New card'} <= set(data['parts']['gpu'])
    backups = [p for p in isolated_parts.parent.iterdir() if p.name.startswith('my_parts.backup')]
    assert backups and '"version": 7' in backups[0].read_text(encoding='utf-8')


def test_parts_beyond_the_limit_are_kept(isolated_parts):
    fans = {'Fan %d' % k: dict(size=120, rpm=1500, cfm=55, mmh2o=1.6) for k in range(lib.MAX_PARTS + 5)}
    isolated_parts.write_text(json.dumps({'version': 1, 'parts': {'fan': fans}}), encoding='utf-8')
    notes = lib.load()
    assert any('More than' in n for n in notes)
    lib.delete('fan', 'Fan 0')
    lib.add('fan', 'Fan new', dict(size=140, rpm=1500, cfm=70, mmh2o=2))
    data = json.loads(isolated_parts.read_text(encoding='utf-8'))
    assert len(data['parts']['fan']) == lib.MAX_PARTS + 5
    assert 'Fan 0' not in data['parts']['fan'] and 'Fan new' in data['parts']['fan']


def _other_window_adds(path, name):
    data = json.loads(path.read_text(encoding='utf-8'))
    data['parts'].setdefault('gpu', {})[name] = GPU
    path.write_text(json.dumps(data, indent=1), encoding='utf-8')


def test_two_app_windows_do_not_erase_each_others_parts(isolated_parts):
    lib.add('gpu', 'Card A', GPU)
    _other_window_adds(isolated_parts, 'Card B')
    lib.add('gpu', 'Card C', GPU)
    names = set(json.loads(isolated_parts.read_text(encoding='utf-8'))['parts']['gpu'])
    assert names == {'Card A', 'Card B', 'Card C'}


def test_a_deleted_part_is_not_brought_back_by_the_other_window(isolated_parts):
    lib.add('gpu', 'Card A', GPU)
    _other_window_adds(isolated_parts, 'Card B')
    lib.delete('gpu', 'Card A')
    names = set(json.loads(isolated_parts.read_text(encoding='utf-8'))['parts']['gpu'])
    assert names == {'Card B'}


def test_save_problem_message_fits_the_action(monkeypatch):
    lib.add('gpu', 'Card A', GPU)

    def fail(path=None):
        raise OSError('disk full')
    monkeypatch.setattr(lib, 'save', fail)
    with pytest.raises(lib.SaveError) as e:
        lib.delete('gpu', 'Card A')
    assert 'back the next time' in str(e.value)
    with pytest.raises(lib.SaveError) as e:
        lib.add('gpu', 'Card B', GPU)
    assert 'until you close the app' in str(e.value) and 'Card B' in hw.GPUS


# ---------------------------------------------------------------- setups bring only the parts they use
def test_setup_imports_only_the_parts_it_uses():
    lib.add('gpu', 'Used card', GPU)
    lib.add('gpu', 'Spare card', GPU)
    cfg = my_pc()
    cfg.gpu = 'Used card'
    d = cfg.to_dict()
    d['custom_parts']['gpu']['Spare card'] = GPU      # a file stuffed with extra parts
    lib.reset()
    cfg2 = Config.from_dict(d)
    assert cfg2.gpu == 'Used card' and 'Spare card' not in hw.GPUS
    assert any('Used card' in i for i in cfg2.info)


def test_negative_rpm_means_auto_and_too_fast_is_noted():
    d = my_pc().to_dict()
    d['fans'][0].pop('speed_pct')
    d['fans'][0]['rpm'] = -1
    d['fans'][1].pop('speed_pct')
    d['fans'][1]['rpm'] = 3000
    d['cooler_fan_rpm'] = -1
    cfg = Config.from_dict(d)
    assert cfg.fans[0].auto and cfg.fans[1].speed_pct == 100 and cfg.cooler_fan_pct == -1
    assert any('negative' in n for n in cfg.notes) and any('maximum' in n for n in cfg.notes)


def test_unknown_settings_and_newer_files_are_noted():
    d = my_pc().to_dict()
    d['cpu_power'] = 90
    d['version'] = 99
    notes = Config.from_dict(d).notes
    assert any('cpu_power' in n for n in notes) and any('newer version' in n for n in notes)


def test_validation_settles_in_one_pass():
    d = my_pc().to_dict()
    d['case']['depth_mm'] = 300
    d['case']['shroud_length_mm'] = 'abc'
    cfg = Config.from_dict(d)
    assert cfg.case.shroud_length_mm <= 260 and cfg.validate() == []


# ---------------------------------------------------------------- geometry edge cases
def test_big_custom_cooler_blowing_down_stays_inside_the_case():
    lib.add('cooler', 'Huge tower', dict(kind='tower', stacks=2, fan_mm=140, stack_depth=80, stack_height=170,
                                         r100=0.1))
    for orient in ('to bottom', 'to top', 'to front', 'to rear'):
        cfg = my_pc()
        cfg.cooler, cfg.cooler_fans, cfg.cooler_orientation = 'Huge tower', 3, orient
        cfg.case.depth_mm, cfg.case.height_mm = 300, 300
        L = Layout(cfg, 4.0)
        for x0, x1, y0, y1 in L.draw['cooler']['stacks']:
            assert 0 <= x0 < x1 <= L.D and 0 <= y0 < y1 <= L.H
        sim = Solver(L, n_particles=20)
        sim.run(0.1)


def test_short_case_with_a_tall_shroud_keeps_a_real_gpu():
    cfg = my_pc()
    cfg.case.height_mm, cfg.case.shroud_height_mm = 340, 130
    L = Layout(cfg, 4.0)
    x0, x1, y0, y1 = L.draw['gpu']['box']
    assert y1 - y0 >= 20 and any('too short' in w for w in L.warnings)


def test_heat_sink_temperatures_carry_over_by_name():
    sim = Solver(Layout(my_pc(), 4.0), n_particles=20)
    sim.run(0.6)
    cfg = my_pc()
    cfg.hdd_count = 1                                # adds a heat source before the GPU
    sim2 = Solver(Layout(cfg, 4.0), n_particles=20, previous=sim)
    old = {h['name']: h['Ts'] for h in sim.hs}
    new = {h['name']: h['Ts'] for h in sim2.hs}
    for name in ('gpu', 'cpu', 'psu', 'ram', 'board'):
        assert new[name] == old[name], name


def test_ram_under_a_huge_cooler_is_reported():
    lib.add('cooler', 'Wide tower', dict(kind='tower', stacks=2, fan_mm=140, stack_depth=80, stack_height=170,
                                         r100=0.1))
    cfg = my_pc()
    cfg.motherboard, cfg.cooler, cfg.cooler_fans = 'Mini-ITX (B650I / Z790I class)', 'Wide tower', 3
    L = Layout(cfg, 4.0)
    if not any(h['name'] == 'ram' for h in L.heat):
        assert any('RAM' in w for w in L.warnings)
    total = sum(h['P'] for h in L.heat)
    ld = L.loads
    assert total == pytest.approx(ld['p_dc'] - ld['p_usb'] + ld['p_psu'])


# ---------------------------------------------------------------- drawing and export
def test_dollar_signs_in_part_names_do_not_break_pictures():
    lib.add('gpu', 'RTX $\\foo$ edition', GPU)
    cfg = my_pc()
    cfg.gpu = 'RTX $\\foo$ edition'
    L = Layout(cfg, 4.0)
    sim = Solver(L, n_particles=20)
    sim.run(0.1)
    frame = ReportFrame(L, width=540, height=960, dpi=60)
    frame.update(0, sim.interior_T(), sim.frame_particles(), summarize(sim))
    frame.rgb()
    plt.close(frame.fig)


def test_gif_fallback_never_overwrites(tmp_path):
    a = tmp_path / 'clip.gif'
    a.write_bytes(b'x')
    assert video.free_name(str(a)) == str(tmp_path / 'clip (2).gif')


@pytest.mark.skipif(not os.path.exists('/bin/false'), reason='needs /bin/false')
def test_failed_ffmpeg_is_an_error_not_saved(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(video, '_ffmpeg', lambda: '/bin/false')
    out = tmp_path / 'v.mp4'
    code = cli.main([os.path.join(ROOT, 'configs', 'my_pc.json'), '--video', str(out), '--seconds', '0.1',
                     '--quality', 'fast', '--warmup', '0.05'])
    assert code == 3
    assert 'Export failed' in capsys.readouterr().err


def test_cli_can_ignore_the_parts_file(monkeypatch, capsys):
    def boom(path=None):
        raise AssertionError('my_parts.json must not be read')
    monkeypatch.setattr(lib, 'load', boom)
    assert cli.main([os.path.join(ROOT, 'configs', 'my_pc.json'), '--report', '--quality', 'fast', '--warmup',
                     '0.2', '--no-parts-file']) == 0


def test_ffmpeg_in_the_current_folder_is_not_used(tmp_path, monkeypatch):
    fake = tmp_path / ('ffmpeg.exe' if sys.platform.startswith('win') else 'ffmpeg')
    fake.write_text('not a program')
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr('shutil.which', lambda name: str(fake))
    monkeypatch.setitem(sys.modules, 'imageio_ffmpeg', None)
    assert video._ffmpeg() is None


# ---------------------------------------------------------------- second review round
def test_odd_entry_in_the_parts_file_never_blocks_saving(isolated_parts):
    isolated_parts.write_text('{"version": 1, "parts": {"gpu": {"Card \\ud800": {"tbp": 250, "length": 300, '
                              '"slots": 2.5, "fans": 3}, "Good card": {"tbp": 250, "length": 300, "slots": 2.5, '
                              '"fans": 3}}}}', encoding='utf-8')
    lib.load()
    lib.add('gpu', 'New card', GPU)
    data = json.loads(isolated_parts.read_text(encoding='utf-8'))
    assert {'Good card', 'New card', 'Card \ud800'} <= set(data['parts']['gpu'])


def test_deeply_nested_entry_goes_to_the_backup_only(isolated_parts):
    isolated_parts.write_text('{"version": 1, "parts": {"gpu": {"Deep": %s, "Good card": %s}}}'
                              % (deep(1500), json.dumps(GPU)), encoding='utf-8')
    notes = lib.load()
    assert any('Deep' in n for n in notes)
    lib.add('gpu', 'New card', GPU)
    data = json.loads(isolated_parts.read_text(encoding='utf-8'))
    assert {'Good card', 'New card'} <= set(data['parts']['gpu'])
    assert any(p.name.startswith('my_parts.backup') for p in isolated_parts.parent.iterdir())


def test_two_windows_on_a_fresh_install(isolated_parts):
    assert lib.load() == []                         # no file yet
    isolated_parts.write_text(json.dumps({'version': 1, 'parts': {'gpu': {'Card B': GPU}}}), encoding='utf-8')
    lib.add('gpu', 'Card A', GPU)
    names = set(json.loads(isolated_parts.read_text(encoding='utf-8'))['parts']['gpu'])
    assert names == {'Card A', 'Card B'}


def test_a_shared_setup_never_erases_a_kept_entry(isolated_parts):
    isolated_parts.write_text(json.dumps({'version': 1, 'parts': {'gpu': {'My GPU': dict(GPU, tbp=1200)}}}),
                              encoding='utf-8')
    lib.load()
    cfg = my_pc()
    d = cfg.to_dict()
    d['gpu'] = 'My GPU'
    d['custom_parts'] = {'gpu': {'My GPU': GPU}}
    assert Config.from_dict(d).gpu == 'My GPU'     # used for this session
    lib.add('gpu', 'Other card', GPU)
    data = json.loads(isolated_parts.read_text(encoding='utf-8'))
    assert data['parts']['gpu']['My GPU']['tbp'] == 1200


def test_a_setup_stuffed_with_parts_is_cheap_and_capped():
    import time
    d = my_pc().to_dict()
    names = ['Card %d' % k for k in range(3000)]
    d['fans'] = [dict(d['fans'][0], model=n) for n in names]
    d['custom_parts'] = {'fan': {n: dict(size=120, rpm=1500, cfm=55, mmh2o=1.6) for n in names}}
    t = time.perf_counter()
    cfg = Config.from_dict(d)
    assert time.perf_counter() - t < 3.0
    assert len(lib.custom_names('fan')) <= lib.MAX_IMPORTS
    assert len(cfg.fans) == 40


def test_notes_show_odd_text_safely():
    d = my_pc().to_dict()
    d['gpu'] = 'Bad \ud800 name'
    d['case']['depth'] = 400                        # a typo inside the case section
    d['fans'][0]['speed'] = 80                      # a typo inside a fan
    d['fan_curve'] = dict(d['fan_curve'], t_low=40)
    notes = Config.from_dict(d).notes
    assert all('\ud800' not in n for n in notes)
    for word in ('case settings', 'fan settings', 'fan curve settings'):
        assert any(word in n for n in notes), word


def test_printable():
    assert lib.printable('a\ud800b‮c\n', 10) == 'a?b?c?'


def test_kept_entries_are_never_deeper_than_the_limit(isolated_parts):
    isolated_parts.write_text('{"version": 1, "parts": {"gpu": {"Deep": %s}}}' % deep(lib.MAX_DEPTH + 5),
                              encoding='utf-8')
    lib.load()
    lib.add('gpu', 'New card', GPU)
    data = json.loads(isolated_parts.read_text(encoding='utf-8'))
    assert 'Deep' not in data['parts']['gpu']
    assert any(p.name.startswith('my_parts.backup') for p in isolated_parts.parent.iterdir())
