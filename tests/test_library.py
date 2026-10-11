"""Your own parts: add / edit / delete, validation, the parts file, parts carried inside setups."""
import json
import math

import pytest

from pcflow import hardware as hw
from pcflow import library as lib
from pcflow.config import Config, my_pc
from pcflow.layout import Layout

GPU = dict(tbp=250, length=300, slots=2.5, fans=3)
FAN92 = dict(size=92, rpm=2500, cfm=40.0, mmh2o=2.5)
CPU = dict(vendor='AMD', memory='DDR5', tdp=105, max_w=142, gaming_w=70, idle_w=25, r_int=0.40, tjmax=95)
TOWER = dict(kind='tower', stacks=1, fan_mm=120, stack_depth=50, stack_height=150, r100=0.15)
AIO = dict(kind='aio', fans=2, fan_mm=140, r100=0.09)
BOARD = dict(form='Mini-ITX', chipset_w=6.0, vrm_eff=0.90, ecc=False)
CASE = dict(depth_mm=420, height_mm=460, width_mm=220, shroud=True, shroud_height_mm=95, shroud_length_mm=320)


def test_add_gpu_registers_saves_and_reloads(isolated_parts):
    lib.add('gpu', 'My RTX 4070 Super OC', GPU)
    assert hw.GPUS['My RTX 4070 Super OC']['tbp'] == 250
    assert lib.is_custom('gpu', 'My RTX 4070 Super OC')
    assert isolated_parts.exists()
    lib.reset()
    assert 'My RTX 4070 Super OC' not in hw.GPUS
    assert lib.load() == []
    assert hw.GPUS['My RTX 4070 Super OC']['length'] == 300


def test_parts_file_is_plain_json(isolated_parts):
    lib.add('fan', 'My 92 mm fan', FAN92)
    data = json.loads(isolated_parts.read_text(encoding='utf-8'))
    assert data['parts']['fan']['My 92 mm fan']['rpm'] == 2500


@pytest.mark.parametrize('field,value', [('tbp', -5), ('tbp', 5000), ('length', 'long'), ('fans', 0),
                                         ('slots', float('nan')), ('tbp', float('inf')), ('fans', 2.5),
                                         ('tbp', True)])
def test_bad_values_are_rejected(field, value):
    with pytest.raises(lib.PartError) as e:
        lib.add('gpu', 'Bad card', dict(GPU, **{field: value}))
    assert field in str(e.value)
    assert 'Bad card' not in hw.GPUS


def test_missing_field_is_rejected():
    spec = dict(GPU)
    del spec['tbp']
    with pytest.raises(lib.PartError) as e:
        lib.add('gpu', 'No power', spec)
    assert 'tbp' in str(e.value)


def test_unknown_category_is_rejected():
    with pytest.raises(lib.PartError):
        lib.add('toaster', 'Toaster', {})


@pytest.mark.parametrize('name', ['', '   ', 'x' * 81, 'bad\nname', 'tab\tname', 'NVIDIA GeForce RTX 4090'])
def test_bad_names_are_rejected(name):
    with pytest.raises(lib.PartError):
        lib.add('gpu', name, GPU)


def test_names_are_trimmed():
    name = lib.add('gpu', '  My card  ', GPU)
    assert name == 'My card' and 'My card' in hw.GPUS


def test_same_custom_name_twice_is_rejected():
    lib.add('gpu', 'Card A', GPU)
    with pytest.raises(lib.PartError):
        lib.add('gpu', 'Card A', GPU)


def test_edit_and_rename():
    lib.add('gpu', 'Card A', GPU)
    lib.update('gpu', 'Card A', 'Card B', dict(GPU, tbp=300))
    assert 'Card A' not in hw.GPUS
    assert hw.GPUS['Card B']['tbp'] == 300


def test_edit_keeps_the_old_part_when_the_new_values_are_bad():
    lib.add('gpu', 'Card A', GPU)
    with pytest.raises(lib.PartError):
        lib.update('gpu', 'Card A', 'Card A', dict(GPU, tbp=-1))
    assert hw.GPUS['Card A']['tbp'] == 250


def test_rename_onto_an_existing_name_is_rejected():
    lib.add('gpu', 'Card A', GPU)
    lib.add('gpu', 'Card B', GPU)
    with pytest.raises(lib.PartError):
        lib.update('gpu', 'Card A', 'Card B', GPU)


def test_builtin_parts_cannot_be_edited_or_deleted():
    with pytest.raises(lib.PartError):
        lib.delete('gpu', 'NVIDIA GeForce RTX 4090')
    with pytest.raises(lib.PartError):
        lib.update('gpu', 'NVIDIA GeForce RTX 4090', 'X', GPU)
    assert 'NVIDIA GeForce RTX 4090' in hw.GPUS


def test_delete_custom_part_also_from_the_file(isolated_parts):
    lib.add('gpu', 'Card A', GPU)
    lib.delete('gpu', 'Card A')
    assert 'Card A' not in hw.GPUS
    data = json.loads(isolated_parts.read_text(encoding='utf-8'))
    assert 'Card A' not in data['parts'].get('gpu', {})


def test_setup_carries_its_custom_parts_to_another_pc():
    lib.add('gpu', 'My card', GPU)
    lib.add('fan', 'My 92 mm fan', FAN92)
    cfg = my_pc()
    cfg.gpu = 'My card'
    cfg.fans[0].model = 'My 92 mm fan'
    d = json.loads(json.dumps(cfg.to_dict()))
    assert 'My card' in d['custom_parts']['gpu']
    assert 'My 92 mm fan' in d['custom_parts']['fan']
    lib.reset()                                       # a fresh install: no parts of its own
    cfg2 = Config.from_dict(d)
    assert cfg2.gpu == 'My card'
    assert cfg2.fans[0].model == 'My 92 mm fan'
    assert not lib.is_saved('gpu', 'My card')         # used, but not added to this PC's own list
    L = Layout(cfg2, 4.0)
    assert any(f.size == 92 for f in L.fans if f.kind == 'case')


def test_unused_custom_parts_are_not_embedded():
    lib.add('gpu', 'Spare card', GPU)
    assert 'gpu' not in my_pc().to_dict().get('custom_parts', {})


def test_embedded_part_does_not_override_your_own():
    lib.add('gpu', 'My card', GPU)
    cfg = my_pc()
    cfg.gpu = 'My card'
    d = cfg.to_dict()
    d['custom_parts']['gpu']['My card']['tbp'] = 400
    cfg2 = Config.from_dict(d)
    assert hw.GPUS['My card']['tbp'] == 250
    assert any('My card' in n for n in cfg2.notes)


def test_bad_embedded_part_is_skipped_with_a_note():
    d = my_pc().to_dict()
    d['gpu'] = 'Broken card'
    d['custom_parts'] = {'gpu': {'Broken card': {'tbp': 'lots'}}}
    cfg = Config.from_dict(d)
    assert cfg.gpu in hw.GPUS and cfg.gpu != 'Broken card'
    assert any('Broken card' in n for n in cfg.notes)


def test_embedded_part_with_a_builtin_name_is_ignored():
    d = my_pc().to_dict()
    d['custom_parts'] = {'gpu': {'NVIDIA GeForce RTX 4090': dict(GPU, tbp=1)}}
    Config.from_dict(d)
    assert hw.GPUS['NVIDIA GeForce RTX 4090']['tbp'] == 450


def test_corrupt_parts_file_is_reported_and_kept(isolated_parts):
    isolated_parts.write_text('{not json', encoding='utf-8')
    notes = lib.load()
    assert notes and 'could not be read' in notes[0]
    lib.add('gpu', 'New card', GPU)                   # saving must not destroy the unreadable file
    kept = [p for p in isolated_parts.parent.iterdir() if p.read_text(encoding='utf-8') == '{not json']
    assert kept


def test_bad_part_in_the_file_is_skipped_others_load(isolated_parts):
    isolated_parts.write_text(json.dumps({'format': lib.FILE_FORMAT, 'version': 1, 'parts': {
        'gpu': {'Good card': GPU, 'Bad card': dict(GPU, tbp=-3)},
        'nonsense': {'x': {}}}}), encoding='utf-8')
    notes = lib.load()
    assert 'Good card' in hw.GPUS and 'Bad card' not in hw.GPUS
    assert any('Bad card' in n for n in notes)


def test_oversized_parts_file_is_refused(isolated_parts):
    isolated_parts.write_text(' ' * (lib.MAX_FILE_BYTES + 10), encoding='utf-8')
    notes = lib.load()
    assert notes and 'too big' in notes[0]


def test_every_category_works_in_a_simulation():
    lib.add('cpu', 'My CPU', CPU)
    lib.add('cooler', 'My tower', TOWER)
    lib.add('cooler', 'My AIO', AIO)
    lib.add('motherboard', 'My ITX board', BOARD)
    lib.add('case', 'My case', CASE)
    lib.add('fan', 'My 92 mm fan', FAN92)
    for cooler in ('My tower', 'My AIO'):
        cfg = my_pc()
        cfg.cpu, cfg.cooler, cfg.motherboard = 'My CPU', cooler, 'My ITX board'
        cfg.apply_case_preset('My case')
        cfg.cooler_fan_model = 'My 92 mm fan' if cooler == 'My tower' else ''
        assert cfg.validate() == []
        assert cfg.case.depth_mm == 420 and cfg.case.shroud_height_mm == 95
        L = Layout(cfg, 4.0)
        assert L.draw['board_form'] == 'Mini-ITX'
        assert L.loads['p_cpu'] == 70


def test_tower_and_aio_coolers_need_different_fields():
    lib.add('cooler', 'Small AIO', AIO)               # no stack sizes needed
    with pytest.raises(lib.PartError) as e:
        lib.add('cooler', 'Half tower', dict(kind='tower', fan_mm=120, r100=0.2))
    assert 'stack' in str(e.value)


def test_cpu_powers_must_be_in_order():
    with pytest.raises(lib.PartError):
        lib.add('cpu', 'Odd CPU', dict(CPU, idle_w=90, gaming_w=60))


def test_case_shroud_must_fit_inside_the_case():
    with pytest.raises(lib.PartError):
        lib.add('case', 'Odd case', dict(CASE, depth_mm=320, shroud_length_mm=600))


def test_fields_and_summaries_for_every_category():
    for cat in lib.CATEGORIES:
        fields = lib.fields(cat)
        assert fields and all(f.label for f in fields)
        name = next(iter(lib.table(cat)))
        assert lib.summary(cat, name)
        assert lib.defaults(cat)


def test_defaults_are_valid_parts():
    for cat in lib.CATEGORIES:
        for kind in (('tower', 'aio') if cat == 'cooler' else (None,)):
            spec = lib.defaults(cat, kind)
            clean = lib.validate(cat, spec)
            assert all(isinstance(v, (int, float, str, bool)) for v in clean.values())
            assert all(math.isfinite(v) for v in clean.values() if isinstance(v, float))
            lib.add(cat, 'Default %s %s' % (cat, kind), spec, save=False)


def test_session_only_parts_are_not_written(isolated_parts):
    lib.add('gpu', 'Just for now', GPU, save=False)
    assert 'Just for now' in hw.GPUS
    assert not isolated_parts.exists()
