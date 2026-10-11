"""The 'Powered by ElAmouri' credit (pictures, videos, reports, command line) and the .exe start-up code."""
import os
import subprocess
import sys

import matplotlib.pyplot as plt
import pytest

from pcflow import branding, cli
from pcflow.config import my_pc
from pcflow.layout import Layout
from pcflow.render import ReportFrame
from pcflow.results import summarize, text_report
from pcflow.solver import Solver

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_credit_details():
    assert branding.POWERED_BY == 'Powered by ElAmouri'
    assert branding.GITHUB_URL == 'https://github.com/Elamouri'
    digits = ''.join(ch for ch in branding.WHATSAPP_TEXT if ch.isdigit())
    assert digits == branding.WHATSAPP_NUMBER.lstrip('+') == branding.WHATSAPP_URL.rsplit('/', 1)[1] == '962796742759'
    for text in (branding.CREDIT_LINE, branding.CREDIT_ASCII, branding.WINDOW_TITLE):
        assert branding.POWERED_BY in text
    assert branding.CREDIT_ASCII.isascii()
    assert branding.VERSION in branding.WINDOW_TITLE


def small_sim():
    L = Layout(my_pc(), 4.0)
    sim = Solver(L, n_particles=60)
    sim.run(0.15)
    return L, sim


def test_text_report_has_the_credit():
    L, sim = small_sim()
    head = text_report(sim).splitlines()[:4]
    assert any(branding.POWERED_BY in line and branding.GITHUB_TEXT in line and branding.WHATSAPP_TEXT in line
               for line in head)


def test_every_picture_and_video_frame_has_the_credit():
    L, sim = small_sim()
    frame = ReportFrame(L, width=540, height=960, dpi=60)
    frame.update(0, sim.interior_T(), sim.frame_particles(), summarize(sim))
    frame.rgb()
    assert frame.t_credit.get_text() == branding.CREDIT_LINE
    bb = frame.t_credit.get_window_extent()
    w, h = frame.fig.canvas.get_width_height()
    assert 0 <= bb.x0 and bb.x1 <= w and 0 <= bb.y0 and bb.y1 <= h       # fully inside the picture
    plt.close(frame.fig)


def test_png_file_carries_the_credit(tmp_path):
    from PIL import Image
    from pcflow.video import export_png
    out = tmp_path / 'r.png'
    export_png(my_pc(), str(out), quality='fast', warmup=0.1, progress=lambda *_: None)
    with Image.open(out) as im:
        info = dict(im.info)
    assert info.get('Author') == branding.AUTHOR
    assert branding.POWERED_BY in info.get('Comment', '')


def test_video_file_carries_the_credit(tmp_path):
    pytest.importorskip('imageio_ffmpeg')
    from pcflow.video import _ffmpeg, export_video
    exe = _ffmpeg()
    if exe is None:
        pytest.skip('no ffmpeg')
    out = tmp_path / 'v.mp4'
    export_video(my_pc(), str(out), seconds=0.1, quality='fast', warmup=0.05, progress=lambda *_: None)
    probe = subprocess.run([exe, '-hide_banner', '-i', str(out)], capture_output=True, text=True, errors='replace')
    assert branding.POWERED_BY in probe.stderr and 'ElAmouri' in probe.stderr


def test_cli_version_and_help(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(['--version'])
    assert e.value.code == 0
    out = capsys.readouterr().out
    assert branding.POWERED_BY in out and branding.GITHUB_URL in out and branding.WHATSAPP_TEXT in out
    with pytest.raises(SystemExit):
        cli.main(['--help'], prog='PC_Airflow_Lab.exe --cli')
    out = capsys.readouterr().out
    assert out.startswith('usage: PC_Airflow_Lab.exe --cli')
    assert branding.POWERED_BY in out and branding.WHATSAPP_TEXT in out


# ---------------------------------------------------------------- start file of the .exe
@pytest.fixture
def entry():
    import pc_airflow_lab                             # the project folder is on the path (conftest)
    return pc_airflow_lab


@pytest.fixture
def gui():
    pytest.importorskip('tkinter')
    import matplotlib
    backend = matplotlib.get_backend()
    import pcflow.gui as gui
    matplotlib.use(backend)                           # importing the window code switches to TkAgg
    return gui


def test_entry_sends_options_to_the_command_line(entry, gui, monkeypatch):
    calls = []
    monkeypatch.setattr(entry, '_text_output', lambda: None)
    monkeypatch.setattr('pcflow.cli.main', lambda argv, prog=None: calls.append((argv, prog)) or 0)
    monkeypatch.setattr('pcflow.gui.main', lambda argv: calls.append(('window', argv)))
    assert entry.main(['--cli', 'a.json', '--png', 'b.png']) == 0
    assert entry.main(['--selftest']) == 0
    assert entry.main(['setup.json']) == 0
    assert entry.main([]) == 0
    assert calls[0][0] == ['a.json', '--png', 'b.png'] and calls[0][1].endswith(' --cli')
    assert calls[1][0] == ['--selftest']
    assert calls[2] == ('window', ['setup.json']) and calls[3] == ('window', [])


def test_entry_command_line_really_runs(tmp_path):
    out = tmp_path / 'r.png'
    run = subprocess.run([sys.executable, os.path.join(ROOT, 'pc_airflow_lab.py'), '--cli',
                          os.path.join(ROOT, 'configs', 'my_pc.json'), '--png', str(out), '--quality', 'fast',
                          '--warmup', '0.1'], capture_output=True, text=True, timeout=300, cwd=str(tmp_path))
    assert run.returncode == 0, run.stderr
    assert out.stat().st_size > 20000
    assert 'saved' in run.stdout


def test_text_output_never_leaves_print_broken(entry, monkeypatch):
    monkeypatch.setattr(sys, 'stdout', None)
    monkeypatch.setattr(sys, 'stderr', None)
    entry._text_output()
    print('still works')
    print('also on stderr', file=sys.stderr)
    assert sys.stdout is not None and sys.stderr is not None


# ---------------------------------------------------------------- frozen (.exe) helpers in the window code
def test_export_command_from_the_source(gui, monkeypatch):
    monkeypatch.setattr(gui, 'FROZEN', False)
    cmd, cwd = gui.export_command('t.json', 'video', 'out.mp4', 'fast')
    assert cmd[:2] == [sys.executable, os.path.join(gui.HERE, 'run_cli.py')]
    assert cmd[2:] == ['t.json', '--video', 'out.mp4', '--quality', 'fast', '--no-parts-file', '--seconds', '20']
    assert cwd == gui.HERE


def test_export_command_from_the_exe_runs_itself(gui, monkeypatch):
    monkeypatch.setattr(gui, 'FROZEN', True)
    cmd, cwd = gui.export_command('t.json', 'png', 'out.png', 'high')
    assert cmd == [sys.executable, '--cli', 't.json', '--png', 'out.png', '--quality', 'high', '--no-parts-file']
    assert os.path.isdir(cwd)


def test_exe_keeps_setups_in_documents(gui, monkeypatch, tmp_path):
    docs = tmp_path / 'Documents'
    monkeypatch.setattr(gui, 'FROZEN', True)
    monkeypatch.setattr(gui, 'BUNDLE', ROOT)
    monkeypatch.setattr(gui, 'documents_dir', lambda: str(docs))
    folder = gui.setups_dir()
    assert folder == str(docs / branding.APP_NAME)
    shipped = sorted(f for f in os.listdir(os.path.join(ROOT, 'configs')) if f.endswith('.json'))
    assert sorted(os.listdir(folder)) == shipped
    mine = os.path.join(folder, 'my_pc.json')
    with open(mine, 'w', encoding='utf-8') as fh:
        fh.write('{"mine": true}')
    os.remove(os.path.join(folder, 'positive_pressure.json'))   # you delete an example you do not want
    gui.setups_dir()                                   # later: your own changes stay, deleted stays deleted
    with open(mine, encoding='utf-8') as fh:
        assert fh.read() == '{"mine": true}'
    assert not os.path.exists(os.path.join(folder, 'positive_pressure.json'))


def test_source_keeps_setups_in_configs(gui, monkeypatch):
    monkeypatch.setattr(gui, 'FROZEN', False)
    assert gui.setups_dir() == os.path.join(gui.HERE, 'configs')


def test_spec_and_icon_are_there():
    spec = open(os.path.join(ROOT, 'pc_airflow_lab.spec'), encoding='utf-8').read()
    for needed in ("'pc_airflow_lab.py'", 'console=False', 'app.ico', 'version=version_file', 'configs'):
        assert needed in spec
    with open(os.path.join(ROOT, 'assets', 'app.ico'), 'rb') as fh:
        assert fh.read(4) == b'\x00\x00\x01\x00'      # a real .ico file


def test_text_size_fits_the_screen(gui):
    base = gui.BASE_SCALING
    assert gui.fitted_scaling(base, 1920, 1080) == base                     # 100 %: unchanged
    s150 = gui.fitted_scaling(2.0, 1920, 1080)                               # 150 % on a 1080p laptop
    assert base < s150 < 1.5 and 1600 * s150 / base <= 1920 and 1040 * s150 / base <= 1080
    assert gui.fitted_scaling(2.0, 2560, 1440) == pytest.approx(base * 1440 / 1040)
    assert gui.fitted_scaling(8 / 3, 3840, 2160) == 8 / 3                   # 4K at 200 % fits as it is
    assert gui.fitted_scaling(base, 1366, 768) == base                      # never smaller than 100 %



def test_unexpected_command_line_error_ends_the_job(entry, monkeypatch, capsys):
    def broken(argv, prog=None):
        raise ValueError('Format "3" is not supported')
    monkeypatch.setattr(entry, '_text_output', lambda: None)
    monkeypatch.setattr('pcflow.cli.main', broken)
    assert entry.main(['--cli', 'x.json', '--png', 'airflow v1.3']) == 1     # no dialog, a normal error exit
    assert 'Format "3" is not supported' in capsys.readouterr().err


def test_picture_is_png_whatever_the_name(tmp_path):
    from pcflow.video import export_png
    out = tmp_path / 'airflow v1.3'
    export_png(my_pc(), str(out), quality='fast', warmup=0.05, progress=lambda *_: None)
    with open(out, 'rb') as fh:
        assert fh.read(8) == b'\x89PNG\r\n\x1a\n'
