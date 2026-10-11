"""New fans must never land on top of another fan or a part (the "duplicate fan" bug)."""
import pytest

from pcflow import placement
from pcflow.config import Fan, my_pc
from pcflow.layout import Layout


def no_overlaps(cfg):
    """the layout leaves nothing out, at every detail level the app can use"""
    for h in (4.0, 3.0, 2.0):
        L = Layout(cfg, h)
        assert L.draw['rejected'] == [], (h, L.draw['rejected'], L.warnings)
        assert not [w for w in L.warnings if 'left out' in w or 'move it' in w], L.warnings


def test_ready_made_setup_has_no_overlaps():
    no_overlaps(my_pc())


def test_add_fan_when_front_is_full_goes_to_a_free_wall():
    cfg = my_pc()
    fan = Fan('front', 250, 0, 'in')
    ok, note = placement.place_new(cfg, fan)
    assert ok, note
    assert fan.wall != 'front'                      # 3 x 120 mm already fill the 450 mm front
    assert note                                     # the user is told where it went
    cfg.fans.append(fan)
    no_overlaps(cfg)


def test_duplicate_every_fan_never_overlaps():
    cfg = my_pc()
    for k in range(len(cfg.fans)):
        o = cfg.fans[k]
        twin = Fan(o.wall, o.pos_mm, o.pos2_mm, o.direction, o.model, o.speed_pct)
        ok, note = placement.place_new(cfg, twin, near=o.pos_mm)
        assert ok, note
        cfg.fans.append(twin)
        no_overlaps(cfg)


def test_duplicate_keeps_speed_model_and_direction():
    cfg = my_pc()
    o = cfg.fans[3]                                 # top exhaust
    o.speed_pct = 85
    twin = Fan(o.wall, o.pos_mm, o.pos2_mm, o.direction, o.model, o.speed_pct)
    ok, _ = placement.place_new(cfg, twin, near=o.pos_mm)
    assert ok
    assert (twin.direction, twin.model, twin.speed_pct) == ('out', o.model, 85)


def test_adding_until_full_never_overlaps_and_says_why_it_stops():
    cfg = my_pc()
    placed = 0
    note = ''
    for _ in range(30):
        fan = Fan('front', 250, 0, 'in')
        ok, note = placement.place_new(cfg, fan)
        if not ok:
            break
        cfg.fans.append(fan)
        placed += 1
    assert placed >= 3
    assert not ok and 'room' in note.lower()
    no_overlaps(cfg)


def test_rear_fan_avoids_psu_and_gpu_bracket():
    cfg = my_pc()
    cfg.fans = [f for f in cfg.fans if f.wall != 'rear']
    fan = Fan('rear', 60, 0, 'out')                 # 60 mm would sit on the PSU
    ok, note = placement.place_new(cfg, fan, near=60.0)
    assert ok, note
    assert fan.wall == 'rear'
    L = Layout(cfg, 4.0)
    lo, hi = fan.pos_mm - fan.size / 2, fan.pos_mm + fan.size / 2
    for a, b, tag in L.occupied['rear']:
        assert min(hi, b) - max(lo, a) <= 2.0, tag
    cfg.fans.append(fan)
    no_overlaps(cfg)


def test_drag_onto_another_fan_snaps_beside_it():
    cfg = my_pc()
    cfg.fans[0].pos_mm = 250                        # dropped right on Fan 2
    ok, note = placement.snap(cfg, 0, near=250)
    assert ok, note
    assert cfg.fans[0].wall == 'front'
    assert abs(cfg.fans[0].pos_mm - 250) >= 115
    no_overlaps(cfg)


def test_snap_on_a_full_wall_fails_and_names_the_wall():
    cfg = my_pc()
    cfg.fans.append(Fan('front', 250, 0, 'in'))
    ok, note = placement.snap(cfg, len(cfg.fans) - 1, near=250)
    assert not ok
    assert 'front' in note


def test_probe_names_what_is_in_the_way():
    cfg = my_pc()
    probe = placement.Probe(cfg, skip={0})
    fan = cfg.fans[0]
    fan.pos_mm = 250
    assert 'Fan 2' in probe.why(fan)
    fan.pos_mm = 130
    assert probe.why(fan) is None
    fan.wall, fan.pos_mm = 'rear', 40
    assert 'PSU' in probe.why(fan)


def test_inside_fan_is_kept_off_the_gpu():
    cfg = my_pc()
    gx0, gx1, gy0, gy1 = Layout(cfg, 4.0).draw['gpu']['box']
    fan = Fan('inside', (gx0 + gx1) / 2, (gy0 + gy1) / 2, 'up')
    ok, note = placement.place_new(cfg, fan, near=(fan.pos_mm, fan.pos2_mm))
    assert ok, note
    assert fan.wall == 'inside' and fan.direction == 'up'
    cfg.fans.append(fan)
    no_overlaps(cfg)


def test_layout_refuses_side_fans_on_top_of_each_other():
    cfg = my_pc()
    cfg.fans += [Fan('side', 250, 250, 'in'), Fan('side', 250, 250, 'in')]
    L = Layout(cfg, 4.0)
    assert len(L.sides) == 1
    assert len(L.draw['rejected']) == 1


def test_second_side_fan_is_moved_clear_of_the_first():
    cfg = my_pc()
    cfg.fans.append(Fan('side', 250, 250, 'in'))
    twin = Fan('side', 250, 250, 'in')
    ok, note = placement.place_new(cfg, twin, near=(250, 250))
    assert ok, note
    assert ((twin.pos_mm - 250) ** 2 + (twin.pos2_mm - 250) ** 2) ** 0.5 >= 116
    cfg.fans.append(twin)
    no_overlaps(cfg)


def test_resolve_fixes_an_old_setup_with_stacked_fans():
    cfg = my_pc()
    cfg.fans.append(Fan('top', 220, 0, 'out'))      # exactly on Fan 5
    cfg.fans.append(Fan('front', 130, 0, 'in'))     # exactly on Fan 1
    notes = placement.resolve(cfg)
    assert len(notes) == 2
    no_overlaps(cfg)


def test_resolve_leaves_a_good_setup_alone():
    cfg = my_pc()
    before = [(f.wall, f.pos_mm, f.pos2_mm) for f in cfg.fans]
    assert placement.resolve(cfg) == []
    assert [(f.wall, f.pos_mm, f.pos2_mm) for f in cfg.fans] == before


def test_bottom_fan_is_not_put_over_the_drive_cage():
    cfg = my_pc()
    cfg.hdd_count = 2
    cage = Layout(cfg, 4.0).draw['hdd']['cage']
    over = Fan('bottom', (cage[0] + cage[1]) / 2, 0, 'in')
    test = my_pc()
    test.hdd_count = 2
    test.fans.append(Fan('bottom', over.pos_mm, 0, 'in'))
    assert Layout(test, 4.0).draw['rejected']        # the layout refuses it ...
    ok, note = placement.place_new(cfg, over, near=over.pos_mm)
    assert ok, note                                  # ... and placement finds a real spot
    cfg.fans.append(over)
    no_overlaps(cfg)


@pytest.mark.parametrize('quality', ['fast', 'normal', 'high'])
def test_placement_holds_at_every_detail_level(quality):
    cfg = my_pc()
    cfg.quality = quality
    for _ in range(4):
        fan = Fan('top', 220, 0, 'out')
        ok, _ = placement.place_new(cfg, fan, near=220)
        if ok:
            cfg.fans.append(fan)
    no_overlaps(cfg)
