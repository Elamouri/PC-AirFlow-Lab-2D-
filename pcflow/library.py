"""Your own parts: fans, graphics cards, processors, CPU coolers, motherboards, cases and blocks.

Parts made in the app (Parts tab) are checked against the ranges below, put into the same lists as
the built-in parts (pcflow.hardware) and saved in my_parts.json:

    Windows : %APPDATA%\\PC Airflow Lab\\my_parts.json
    others  : ~/.config/pc-airflow-lab/my_parts.json
    any OS  : the file named by the PCFLOW_PARTS environment variable

A saved setup also carries the custom parts it uses, so it opens on another PC.
The file is plain JSON and is only ever read as data.  Entries that cannot be used (a typo, a part
type from a newer version) are kept in the file untouched, never thrown away.
"""
import json
import math
import os
import shutil
import sys
import tempfile
import time
import unicodedata
from collections import namedtuple
from typing import Dict, List, Optional

from . import hardware as hw
from .safejson import read_json

FILE_FORMAT = 'pc-airflow-lab parts'
FILE_VERSION = 1
MAX_FILE_BYTES = 2_000_000
MAX_NAME = 80
MAX_PARTS = 500                       # your own saved parts per category
MAX_IMPORTS = 60                      # parts one setup file may bring along
MAX_DEPTH = 32                        # deepest nesting kept from a parts file (real parts are 2 levels deep)

CATEGORIES = {'fan': 'Fans', 'gpu': 'Graphics cards', 'cpu': 'Processors', 'cooler': 'CPU coolers',
              'motherboard': 'Motherboards', 'case': 'Cases', 'block': 'Blocks'}
SINGULAR = {'fan': 'fan', 'gpu': 'graphics card', 'cpu': 'processor', 'cooler': 'CPU cooler',
            'motherboard': 'motherboard', 'case': 'case', 'block': 'block'}

# characters that show nothing (fillers, joiners, direction marks, variation selectors ...)
_INVISIBLE = set([0x00AD, 0x034F, 0x061C, 0x115F, 0x1160, 0x17B4, 0x17B5, 0x3164, 0xFEFF, 0xFFA0]
                 + list(range(0x180B, 0x1810)) + list(range(0x200B, 0x2010)) + list(range(0x202A, 0x202F))
                 + list(range(0x2060, 0x2070)) + list(range(0xFE00, 0xFE10)) + list(range(0x1BCA0, 0x1BCA4))
                 + list(range(0x1D173, 0x1D17B)) + list(range(0xE0000, 0xE1000)))


class PartError(ValueError):
    """A part was refused; .problems lists what is wrong, one line each."""

    def __init__(self, problems):
        self.problems = [problems] if isinstance(problems, str) else list(problems)
        super().__init__('; '.join(self.problems))


class SaveError(PartError):
    """The change is in use for this session, but my_parts.json could not be written."""


# type: int | float | choice | bool ;  kinds: cooler types that use the field (None = all)
Field = namedtuple('Field', 'key label type lo hi unit choices kinds')


def _f(key, label, type_, lo=None, hi=None, unit='', choices=(), kinds=None):
    return Field(key, label, type_, lo, hi, unit, tuple(choices), kinds)


FIELDS = {
    'fan': [_f('size', 'Size', 'int', 40, 200, 'mm'),
            _f('rpm', 'Maximum speed', 'int', 200, 10000, 'rpm'),
            _f('cfm', 'Airflow at full speed', 'float', 1, 300, 'CFM'),
            _f('mmh2o', 'Static pressure at full speed', 'float', 0.1, 20, 'mmH2O')],
    'gpu': [_f('tbp', 'Board power (maximum)', 'float', 10, 1000, 'W'),
            _f('length', 'Card length', 'float', 120, 450, 'mm'),
            _f('slots', 'Thickness', 'float', 1, 5, 'slots'),
            _f('fans', 'Fans on the card', 'int', 1, 4)],
    'cpu': [_f('vendor', 'Maker', 'choice', choices=('AMD', 'Intel')),
            _f('memory', 'Memory type', 'choice', choices=hw.CPU_MEMORY),
            _f('tdp', 'TDP on the box', 'float', 10, 400, 'W'),
            _f('max_w', 'Power limit (PPT / PL2)', 'float', 10, 500, 'W'),
            _f('gaming_w', 'Typical gaming power', 'float', 1, 500, 'W'),
            _f('idle_w', 'Idle power', 'float', 1, 200, 'W'),
            _f('r_int', 'Die-to-cooler resistance', 'float', 0.05, 1.5, 'K/W'),
            _f('tjmax', 'Throttle temperature', 'float', 60, 115, '°C')],
    'cooler': [_f('kind', 'Type', 'choice', choices=('tower', 'aio')),
               _f('fan_mm', 'Fan size', 'choice', unit='mm', choices=(120, 140)),
               _f('stacks', 'Fin stacks', 'choice', choices=(1, 2), kinds=('tower',)),
               _f('stack_depth', 'Fin stack thickness', 'float', 20, 80, 'mm', kinds=('tower',)),
               _f('stack_height', 'Fin stack height', 'float', 60, 170, 'mm', kinds=('tower',)),
               _f('fans', 'Radiator fans', 'int', 1, 4, kinds=('aio',)),
               _f('r100', 'Thermal resistance at full fan speed', 'float', 0.03, 0.6, 'K/W')],
    'motherboard': [_f('form', 'Size', 'choice', choices=tuple(hw.BOARD_FORMS)),
                    _f('chipset_w', 'Chipset power', 'float', 0, 40, 'W'),
                    _f('vrm_eff', 'CPU power stage efficiency', 'float', 0.70, 0.98),
                    _f('ecc', 'ECC with Intel Core CPUs (W680 / W880)', 'bool')],
    'case': [_f('depth_mm', 'Inside depth (front-rear)', 'float', 300, 700, 'mm'),
             _f('height_mm', 'Inside height', 'float', 300, 700, 'mm'),
             _f('width_mm', 'Width (glass to tray)', 'float', 150, 320, 'mm'),
             _f('shroud', 'PSU shroud', 'bool'),
             _f('shroud_height_mm', 'Shroud height', 'float', 80, 130, 'mm'),
             _f('shroud_length_mm', 'Shroud length', 'float', 170, 660, 'mm')],
    'block': [_f('w', 'Width (front - rear)', 'float', hw.BLOCK_MIN_MM, hw.BLOCK_MAX_MM, 'mm'),
              _f('h', 'Height', 'float', hw.BLOCK_MIN_MM, hw.BLOCK_MAX_MM, 'mm'),
              _f('air', 'Air through it', 'choice', unit='solid / dense / cables / mesh', choices=tuple(hw.BLOCK_AIR)),
              _f('watts', 'Heat it gives off', 'float', 0, hw.MAX_BLOCK_WATTS, 'W')],
}

_DEFAULTS = {
    'fan': dict(size=120, rpm=1500, cfm=55.0, mmh2o=1.6),
    'gpu': dict(tbp=220.0, length=270.0, slots=2.5, fans=3),
    'cpu': dict(vendor='AMD', memory='DDR5', tdp=105.0, max_w=142.0, gaming_w=70.0, idle_w=25.0, r_int=0.36,
                tjmax=95.0),
    'cooler': {'tower': dict(kind='tower', fan_mm=120, stacks=1, stack_depth=52.0, stack_height=126.0, r100=0.16),
               'aio': dict(kind='aio', fan_mm=120, fans=3, r100=0.08)},
    'motherboard': dict(form='ATX', chipset_w=7.0, vrm_eff=0.88, ecc=False),
    'case': dict(depth_mm=440.0, height_mm=450.0, width_mm=210.0, shroud=True, shroud_height_mm=90.0,
                 shroud_length_mm=340.0),
    'block': dict(w=80.0, h=80.0, air='solid', watts=0.0),
}


def _cat(cat):
    if cat not in CATEGORIES:
        raise PartError('unknown part type "%s"' % (str(cat)[:40],))
    return cat


def table(cat: str) -> Dict[str, dict]:
    """the hardware list a category lives in"""
    return {'fan': hw.ALL_FANS, 'gpu': hw.GPUS, 'cpu': hw.CPUS, 'cooler': hw.COOLERS,
            'motherboard': hw.MOTHERBOARDS, 'case': hw.CASES, 'block': hw.BLOCKS}[_cat(cat)]


_BUILTIN = {c: frozenset(table(c)) for c in CATEGORIES}
_folds = {c: {} for c in CATEGORIES}           # what each name looks like -> name (look-alike check in O(1))
_custom = {c: {} for c in CATEGORIES}          # parts registered by this module: name -> clean spec
_saved = {c: set() for c in CATEGORIES}        # the ones that belong in my_parts.json
_deleted = {c: set() for c in CATEGORIES}      # removed / renamed this session (never brought back)
_kept = {}                                     # raw file entries we could not use: written back untouched
_kept_whole = {}                               # whole unknown sections of the file (not name -> part)
_state = {'backup': None, 'stamp': None}       # back the file up before the next write / file as last seen


# ---------------------------------------------------------------- schema
def fields(cat: str, kind: Optional[str] = None) -> List[Field]:
    """the fields of a part; for coolers pass kind='tower' / 'aio' to get only the ones that apply"""
    out = list(FIELDS[_cat(cat)])
    if kind is not None:
        out = [f for f in out if f.kinds is None or kind in f.kinds]
    return out


def defaults(cat: str, kind: Optional[str] = None) -> dict:
    d = _DEFAULTS[_cat(cat)]
    if cat == 'cooler':
        return dict(d[kind or 'tower'])
    return dict(d)


def _range_text(f):
    return '%g ... %g%s' % (f.lo, f.hi, (' ' + f.unit) if f.unit else '')


def _value(f, raw, problems):
    tag = '%s [%s]' % (f.label, f.key)
    if f.type == 'bool':
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str) and raw.strip().lower() in ('yes', 'true', '1', 'no', 'false', '0'):
            return raw.strip().lower() in ('yes', 'true', '1')
        problems.append('%s: must be yes or no' % tag)
        return None
    if f.type == 'choice':
        if not isinstance(raw, bool):
            for c in f.choices:
                if raw == c or (isinstance(raw, str) and raw.strip() == str(c)):
                    return c
        problems.append('%s: must be one of %s' % (tag, ', '.join(str(c) for c in f.choices)))
        return None
    if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
        problems.append('%s: must be a number' % tag)
        return None
    try:
        x = float(raw.strip().replace(',', '.')) if isinstance(raw, str) else float(raw)
    except (ValueError, OverflowError):
        problems.append('%s: "%s" is not a usable number' % (tag, str(raw)[:20]))
        return None
    if not math.isfinite(x):
        problems.append('%s: must be a normal number' % tag)
        return None
    if f.type == 'int':
        if abs(x - round(x)) > 1e-9:
            problems.append('%s: must be a whole number' % tag)
            return None
        x = int(round(x))
    if x < f.lo or x > f.hi:
        problems.append('%s: must be %s (got %g)' % (tag, _range_text(f), x))
        return None
    return x if f.type == 'int' else float(x)


def validate(cat: str, spec: dict) -> dict:
    """check a part's values; returns a clean copy with only the known fields, raises PartError"""
    _cat(cat)
    problems = []
    if not isinstance(spec, dict):
        raise PartError('the part values are missing')
    kind = None
    if cat == 'cooler':
        kind = _value(FIELDS['cooler'][0], spec.get('kind'), problems)
        if kind is None:
            raise PartError(problems)
    clean = {}
    for f in fields(cat, kind):
        if f.key not in spec:
            problems.append('%s [%s]: missing' % (f.label, f.key))
            continue
        v = _value(f, spec[f.key], problems)
        if v is not None:
            clean[f.key] = v
    if not problems:
        if cat == 'cpu':
            if not clean['idle_w'] <= clean['gaming_w'] <= clean['max_w']:
                problems.append('Powers must go idle [idle_w] <= gaming [gaming_w] <= power limit [max_w]')
            if clean['tdp'] > clean['max_w']:
                problems.append('TDP [tdp] cannot be above the power limit [max_w]')
        if cat == 'case' and clean['shroud_length_mm'] > clean['depth_mm'] - 40:
            problems.append('Shroud length [shroud_length_mm]: must be at most the depth - 40 mm (%g mm)'
                            % (clean['depth_mm'] - 40))
    if problems:
        raise PartError(problems)
    return clean


def printable(text, limit: int = 60) -> str:
    """text from a file made safe to show: control / broken characters become '?', and it is cut short"""
    t = str(text)[:limit]
    return ''.join('?' if unicodedata.category(ch)[0] == 'C' or ord(ch) in _INVISIBLE else ch for ch in t)


def text_problem(text: str) -> Optional[str]:
    """why a name / label from a file is not shown as it is (None = fine)"""
    if any(unicodedata.category(ch)[0] == 'C' or unicodedata.category(ch) in ('Zl', 'Zp') for ch in text):
        return 'contains control or unusable characters'
    if any(ord(ch) in _INVISIBLE for ch in text):
        return 'contains invisible characters'
    return None


def _fold(name):
    """what a name looks like on screen (for spotting look-alike names)"""
    n = unicodedata.normalize('NFKC', name)
    return ' '.join(''.join(ch for ch in n if ord(ch) not in _INVISIBLE).split()).casefold()


def clean_name(cat: str, name: str, keep: Optional[str] = None) -> str:
    """trimmed name, or PartError; `keep` = the part's current name when editing it"""
    if not isinstance(name, str):
        raise PartError('Give the part a name')
    n = name.strip()
    if not n:
        raise PartError('Give the part a name')
    if len(n) > MAX_NAME:
        raise PartError('The name is too long (at most %d characters)' % MAX_NAME)
    why = text_problem(n)
    if why:
        raise PartError('The name %s' % why)
    if n in _BUILTIN[_cat(cat)]:
        raise PartError('A built-in %s is already called "%s" - pick another name' % (SINGULAR[cat], n))
    if n in table(cat) and n != keep:
        raise PartError('You already have a %s called "%s"' % (SINGULAR[cat], n))
    other = _folds[cat].get(_fold(n))
    if other is not None and other not in (n, keep):
        raise PartError('"%s" looks just like the %s "%s" - pick a clearly different name' % (
            n, SINGULAR[cat], other))
    return n


for _c in CATEGORIES:                          # built-in names take part in the look-alike check
    for _n in sorted(_BUILTIN[_c]):
        _folds[_c].setdefault(_fold(_n), _n)


# ---------------------------------------------------------------- registry
def is_custom(cat: str, name: str) -> bool:
    return name in _custom[_cat(cat)]


def is_saved(cat: str, name: str) -> bool:
    return name in _saved[_cat(cat)]


def custom_names(cat: str) -> List[str]:
    return sorted(_custom[_cat(cat)])


def _register(cat, name, clean):
    table(cat)[name] = dict(clean)
    _custom[cat][name] = dict(clean)
    _folds[cat].setdefault(_fold(name), name)


def _unregister(cat, name):
    table(cat).pop(name, None)
    _custom[cat].pop(name, None)
    _saved[cat].discard(name)
    f = _fold(name)
    if _folds[cat].get(f) == name:
        del _folds[cat][f]


def add(cat: str, name: str, spec: dict, save: bool = True) -> str:
    """add a new part; returns its (trimmed) name.  save=False keeps it for this session only."""
    n = clean_name(cat, name)
    clean = validate(cat, spec)
    if save and len(_saved[cat]) >= MAX_PARTS:
        raise PartError('You have %d %ss already - delete some first' % (MAX_PARTS, SINGULAR[cat]))
    _register(cat, n, clean)
    _deleted[cat].discard(n)
    if save:
        _kept.get(cat, {}).pop(n, None)           # a saved good part replaces an unusable one of the same name
        _saved[cat].add(n)
        _save_or_raise('The part works until you close the app')
    return n


def update(cat: str, old: str, name: str, spec: dict, save: bool = True) -> str:
    """change (and maybe rename) one of your parts; the old part stays if the new values are refused"""
    _cat(cat)
    if old not in _custom[cat]:
        raise PartError('Only your own parts can be changed - use "Copy as new" for a built-in %s'
                        % SINGULAR[cat])
    n = clean_name(cat, name, keep=old)
    clean = validate(cat, spec)
    keep_saved = old in _saved[cat]
    _unregister(cat, old)
    if old != n:
        _deleted[cat].add(old)
    _register(cat, n, clean)
    if keep_saved or save:
        _saved[cat].add(n)
    if save:
        _save_or_raise('The change works until you close the app; the saved part is the old one')
    return n


def delete(cat: str, name: str, save: bool = True) -> None:
    _cat(cat)
    if name not in _custom[cat]:
        raise PartError('Built-in parts cannot be deleted')
    _unregister(cat, name)
    _deleted[cat].add(name)
    if save:
        _save_or_raise('It is gone for now, but it will be back the next time the app starts')


def reset() -> None:
    """forget every custom part (used by the tests)"""
    for cat in CATEGORIES:
        for name in list(_custom[cat]):
            _unregister(cat, name)
        _deleted[cat].clear()
    _kept.clear()
    _kept_whole.clear()
    _state.update(backup=None, stamp=None)


# ---------------------------------------------------------------- my_parts.json
def parts_path() -> str:
    env = os.environ.get('PCFLOW_PARTS')
    if env:
        return os.path.abspath(os.path.expanduser(env))
    if sys.platform.startswith('win'):
        base = os.environ.get('APPDATA') or os.path.expanduser('~')
        return os.path.join(base, 'PC Airflow Lab', 'my_parts.json')
    base = os.environ.get('XDG_CONFIG_HOME') or os.path.join(os.path.expanduser('~'), '.config')
    return os.path.join(base, 'pc-airflow-lab', 'my_parts.json')


def _stamp(path):
    try:
        st = os.stat(path)
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def _keep_raw(cat, name, raw):
    """keep an entry we cannot use so it is written back untouched (False if it cannot even be written)"""
    if not _writable(raw):
        return False
    _kept.setdefault(str(cat), {})[str(name)] = raw
    return True


def _depth_ok(raw, limit=MAX_DEPTH):
    """nesting no deeper than `limit` (checked without recursion)"""
    stack = [(raw, 1)]
    while stack:
        item, d = stack.pop()
        if d > limit:
            return False
        if isinstance(item, dict):
            stack.extend((v, d + 1) for v in item.values())
        elif isinstance(item, list):
            stack.extend((v, d + 1) for v in item)
    return True


def _writable(raw):
    """can this be written back the way save() writes it?  (never deeper than MAX_DEPTH)"""
    if not _depth_ok(raw):
        return False
    try:
        json.dumps(raw, indent=2, ensure_ascii=True)
        return True
    except (RecursionError, ValueError, TypeError):
        return False


def load(path: Optional[str] = None) -> List[str]:
    """read my_parts.json; returns notes about anything skipped (never raises for a bad file)"""
    path = path or parts_path()
    if not os.path.exists(path):
        _state['stamp'] = 'missing'              # another window may create it before we save
        return []
    try:
        data = read_json(path, MAX_FILE_BYTES)
    except (OSError, ValueError) as e:
        _state['backup'] = path
        return ['Your parts file could not be read (%s) - it is kept as it is, and a copy is made before '
                'anything new is saved' % e]
    if not isinstance(data, dict) or not isinstance(data.get('parts'), dict):
        _state['backup'] = path
        return ['%s is not a parts file - it is kept as it is' % path]
    notes = []
    version = data.get('version', 1)
    if not isinstance(version, int) or version > FILE_VERSION:
        _state['backup'] = path
        notes.append('Your parts file was saved by a newer version of the app - what this version does not '
                     'understand is kept as it is')
    for cat, parts in data['parts'].items():
        if cat not in CATEGORIES or not isinstance(parts, dict):
            if isinstance(parts, dict):
                for n, s in parts.items():
                    if not _keep_raw(cat, n, s):
                        _state['backup'] = path
            else:
                _state['backup'] = path            # a damaged section: keep a copy of the whole file
                if _writable(parts):
                    _kept_whole[str(cat)] = parts
            notes.append('Part type "%s" in your parts file is not known to this version - kept, not used'
                         % str(cat)[:40])
            continue
        for k, (name, spec) in enumerate(parts.items()):
            if k >= MAX_PARTS:
                if not _keep_raw(cat, name, spec):
                    _state['backup'] = path
                if k == MAX_PARTS:
                    notes.append('More than %d %ss in your parts file - the rest are kept but not loaded'
                                 % (MAX_PARTS, SINGULAR[cat]))
                continue
            try:
                n = add(cat, name, spec, save=False)
                _saved[cat].add(n)
            except PartError as e:
                if _keep_raw(cat, name, spec):
                    notes.append('Your %s "%s" was not loaded (%s) - it stays in the file; fix it there or make it '
                                 'again' % (SINGULAR[cat], printable(name, MAX_NAME), e))
                else:
                    _state['backup'] = path
                    notes.append('Your %s "%s" is damaged - it is only kept in a backup copy of the file'
                                 % (SINGULAR[cat], printable(name, MAX_NAME)))
    _state['stamp'] = _stamp(path)
    return notes


def _merge_from_disk(path):
    """another window may have saved parts since we last looked: keep them"""
    now = _stamp(path)
    if now is None or now == _state['stamp']:
        return
    try:
        data = read_json(path, MAX_FILE_BYTES)
        parts = data.get('parts', {}) if isinstance(data, dict) else {}
    except (OSError, ValueError):
        _state['backup'] = path
        return
    if not isinstance(parts, dict):
        return
    for cat, entries in parts.items():
        if not isinstance(entries, dict):
            continue
        for name, raw in entries.items():
            ours = cat in CATEGORIES and (name in _saved[cat] or name in _deleted[cat])
            if not ours and name not in _kept.get(cat, {}) and not _keep_raw(cat, name, raw):
                _state['backup'] = path


def save(path: Optional[str] = None) -> None:
    """write my_parts.json safely (temporary file + rename); raises OSError / ValueError"""
    path = path or parts_path()
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    if os.path.exists(path):
        _merge_from_disk(path)
        if _state['backup'] == path:
            keep = os.path.join(folder, 'my_parts.backup-%s.json' % time.strftime('%Y%m%d-%H%M%S'))
            shutil.copy2(path, keep)
            _state['backup'] = None
    out = {cat: raw for cat, raw in _kept_whole.items() if cat not in CATEGORIES}
    for cat, entries in _kept.items():
        for name, raw in entries.items():
            if not (cat in CATEGORIES and name in _saved[cat]):
                out.setdefault(cat, {})[name] = raw
    for cat in CATEGORIES:
        for n in sorted(_saved[cat]):
            out.setdefault(cat, {})[n] = _custom[cat][n]
    data = {'format': FILE_FORMAT, 'version': FILE_VERSION, 'parts': out}
    text = json.dumps(data, indent=2, ensure_ascii=True)      # escapes keep any odd text exactly as it was
    fd, tmp = tempfile.mkstemp(prefix='.my_parts-', suffix='.tmp', dir=folder)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    _state['stamp'] = _stamp(path)


def _save_or_raise(what_now):
    try:
        save()
    except (OSError, ValueError, RecursionError) as e:
        raise SaveError('Could not save %s (%s). %s.' % (parts_path(), e, what_now)) from e


# ---------------------------------------------------------------- parts inside setup files
def used_parts(cfg) -> Dict[str, set]:
    fans = {f.model for f in cfg.fans}
    if cfg.cooler_fan_model:
        fans.add(cfg.cooler_fan_model)
    return {'cpu': {cfg.cpu}, 'gpu': {cfg.gpu}, 'cooler': {cfg.cooler}, 'motherboard': {cfg.motherboard},
            'case': {cfg.case.name}, 'fan': fans, 'block': {b.model for b in getattr(cfg, 'blocks', [])}}


def referenced_parts(d: dict, max_fans: int = 40, max_blocks: int = 30) -> Dict[str, set]:
    """the part names a raw setup dict refers to (before it is checked; only the fans and blocks that will be used)"""
    out = {c: set() for c in CATEGORIES}
    for cat, key in (('cpu', 'cpu'), ('gpu', 'gpu'), ('cooler', 'cooler'), ('motherboard', 'motherboard'),
                     ('fan', 'cooler_fan_model')):
        v = d.get(key)
        if isinstance(v, str):
            out[cat].add(v)
    case = d.get('case')
    if isinstance(case, dict) and isinstance(case.get('name'), str):
        out['case'].add(case['name'])
    fans = d.get('fans')
    if isinstance(fans, list):
        out['fan'].update(f['model'] for f in fans[:max_fans] if isinstance(f, dict) and isinstance(f.get('model'), str))
    blocks = d.get('blocks')
    if isinstance(blocks, list):
        out['block'].update(b['model'] for b in blocks[:max_blocks]
                            if isinstance(b, dict) and isinstance(b.get('model'), str))
    return out


def embed(cfg) -> dict:
    """the custom parts a setup uses, to be stored inside the setup file"""
    out = {}
    for cat, names in used_parts(cfg).items():
        parts = {n: dict(_custom[cat][n]) for n in sorted(names) if isinstance(n, str) and n in _custom[cat]}
        if parts:
            out[cat] = parts
    return out


def register_embedded(d, used: Optional[Dict[str, set]] = None, info: Optional[list] = None) -> List[str]:
    """make the parts stored in a setup file available (for this session).
    Only parts the setup really uses are taken.  Returns problem notes; `info` collects what was added."""
    notes = []
    if not d:
        return notes
    if not isinstance(d, dict):
        return ['The custom parts in this setup file are unreadable - skipped']
    imported = 0
    for cat, parts in d.items():
        if cat not in CATEGORIES or not isinstance(parts, dict):
            notes.append('Unknown part type "%s" in this setup - skipped' % printable(cat, 40))
            continue
        for name, spec in parts.items():
            n = name.strip() if isinstance(name, str) else ''
            if not n or (used is not None and n not in used.get(cat, ())):
                continue
            if imported >= MAX_IMPORTS:
                notes.append('This setup brings more than %d parts of its own - the rest are not used' % MAX_IMPORTS)
                return notes
            imported += 1
            if n in _BUILTIN[cat]:
                notes.append('The setup has its own "%s" - the built-in one is used' % printable(n, MAX_NAME))
                continue
            if n in _custom[cat]:
                try:
                    same = validate(cat, spec) == _custom[cat][n]
                except PartError:
                    same = False
                if not same:
                    notes.append('Your own %s "%s" differs from the one saved in this setup - yours is used'
                                 % (SINGULAR[cat], n))
                continue
            try:
                add(cat, n, spec, save=False)
                if info is not None:
                    info.append('Uses its own %s "%s" (stored in the setup)' % (SINGULAR[cat], n))
            except PartError as e:
                notes.append('The %s "%s" in this setup is not valid (%s) - a built-in part is used instead'
                             % (SINGULAR[cat], printable(n, MAX_NAME), e))
    return notes


# ---------------------------------------------------------------- one-line descriptions
def summary(cat: str, name: str) -> str:
    p = table(cat)[name]
    if cat == 'fan':
        return '%d mm · %d rpm · %.0f CFM · %.2f mmH2O' % (p['size'], p['rpm'], p['cfm'], p['mmh2o'])
    if cat == 'gpu':
        return '%.0f W · %.0f mm · %.1f slots · %d fans' % (p['tbp'], p['length'], p['slots'], p['fans'])
    if cat == 'cpu':
        return '%s · TDP %.0f W · max %.0f W · %s' % (p.get('vendor', '?'), p['tdp'], p['max_w'],
                                                     p.get('memory', 'DDR4/DDR5'))
    if cat == 'cooler':
        if p['kind'] == 'aio':
            return 'AIO %d × %d mm · %.3f K/W' % (p['fans'], p['fan_mm'], p['r100'])
        return 'tower · %d stack%s · %d mm fan · %.3f K/W' % (p['stacks'], '' if p['stacks'] == 1 else 's',
                                                            p['fan_mm'], p['r100'])
    if cat == 'motherboard':
        return '%s · chipset %.0f W · power stage %.0f %%%s' % (p['form'], p['chipset_w'], 100 * p['vrm_eff'],
                                                               ' · ECC with Intel' if p['ecc'] else '')
    if cat == 'block':
        return '%.0f × %.0f mm · %s%s' % (p['w'], p['h'], p['air'], (' · %.0f W' % p['watts']) if p['watts'] else '')
    return '%.0f × %.0f × %.0f mm · %s' % (p['depth_mm'], p['height_mm'], p['width_mm'],
                                          'PSU shroud' if p['shroud'] else 'no shroud')
