"""Drawing, picture / video export and the command line (smoke tests on the coarse grid)."""
import os

import matplotlib.pyplot as plt
import pytest

from pcflow import cli, hardware as hw
from pcflow.config import Fan, my_pc
from pcflow.layout import Layout
from pcflow.render import CaseView, ReportFrame
from pcflow.results import summarize
from pcflow.solver import Solver

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def busy_setup(board):
    cfg = my_pc()
    cfg.motherboard = board
    cfg.ram_sticks = min(2, cfg.ram_sticks)
    cfg.hdd_count = 2
    cfg.fans[0].speed_pct = -1
    cfg.fans.append(Fan('side', 250, 250, 'in'))
    cfg.fans.append(Fan('inside', 330, 330, 'up'))
    return cfg


@pytest.mark.parametrize('board', list(hw.MOTHERBOARDS))
def test_case_view_draws_every_board(board):
    L = Layout(busy_setup(board), 4.0)
    sim = Solver(L, n_particles=60)
    sim.run(0.15)
    fig, ax = plt.subplots()
    view = CaseView(ax, L, fs=0.8, dashes=60)
    view.update(0, sim.interior_T(), sim.frame_particles(), summarize(sim))
    fig.canvas.draw()
    texts = [t.get_text() for t in ax.texts]
    assert any('HDD' in t for t in texts)
    assert any(hw.MOTHERBOARDS[board]['form'] in t for t in texts)
    assert any('auto' in t for t in texts)
    plt.close(fig)


def test_report_frame_renders():
    L = Layout(busy_setup('ATX mainstream (B650 / B760 / B860 class)'), 4.0)
    sim = Solver(L, n_particles=60)
    sim.run(0.15)
    frame = ReportFrame(L, width=540, height=960, dpi=60)
    frame.update(0, sim.interior_T(), sim.frame_particles(), summarize(sim), t_real=0.1)
    rgb = frame.rgb()
    assert rgb.shape[2] == 3 and rgb.mean() > 5
    plt.close(frame.fig)


def test_png_export(tmp_path):
    from pcflow.video import export_png
    cfg = my_pc()
    out = tmp_path / 'r.png'
    export_png(cfg, str(out), quality='fast', warmup=0.2, progress=lambda *_: None)
    assert out.stat().st_size > 20000


def test_short_video_export(tmp_path):
    pytest.importorskip('imageio_ffmpeg')
    from pcflow.video import export_video
    out = tmp_path / 'v.mp4'
    export_video(my_pc(), str(out), seconds=0.2, quality='fast', warmup=0.1, progress=lambda *_: None)
    assert out.stat().st_size > 5000


def test_cli_selftest():
    assert cli.main(['--selftest']) == 0


def test_cli_report(capsys):
    assert cli.main([os.path.join(ROOT, 'configs', 'my_pc.json'), '--report', '--quality', 'fast',
                     '--warmup', '0.3']) == 0
    out = capsys.readouterr().out
    assert 'CPU' in out and 'Motherboard' in out


def test_cli_bad_file_gives_a_message_not_a_traceback(tmp_path, capsys):
    bad = tmp_path / 'bad.json'
    bad.write_text('{oops', encoding='utf-8')
    assert cli.main([str(bad), '--report']) == 2
    assert 'could not' in capsys.readouterr().err.lower()
