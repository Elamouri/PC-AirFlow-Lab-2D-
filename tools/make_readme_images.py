"""Make the pictures for the GitHub page: docs/images/report.png (an exported report) and docs/images/demo.gif
(the live airflow of the example PC).  Run from the project folder:  python tools/make_readme_images.py"""
import os
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import matplotlib  # noqa: E402
matplotlib.use('Agg')
from matplotlib.backends.backend_agg import FigureCanvasAgg  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

from pcflow.config import my_pc  # noqa: E402
from pcflow.render import BG, CaseView, view_limits  # noqa: E402
from pcflow.results import summarize  # noqa: E402
from pcflow.video import _ffmpeg, export_png, prepare  # noqa: E402

OUT = os.path.join(HERE, 'docs', 'images')


def demo_gif(path, seconds=6.0, fps=15, width=480):
    exe = _ffmpeg()
    if exe is None:
        raise SystemExit('ffmpeg is needed for the GIF (pip install imageio-ffmpeg)')
    layout, sim, sub = prepare(my_pc(), 'normal', warmup=4.0, fps=fps, slowmo=0.25, n_particles=1500,
                               progress=lambda *a: None)
    (x0, x1), (y0, y1) = view_limits(layout)
    x0, x1, y0, y1 = x0 - 22, x1 + 22, y0 - 6, y1 + 6          # room for the fan labels at the edges
    w_in = 6.0
    fig = Figure(figsize=(w_in, w_in * (y1 - y0) / (x1 - x0)), dpi=110, facecolor=BG)
    FigureCanvasAgg(fig)
    ax = fig.add_axes([0, 0, 1, 1])
    view = CaseView(ax, layout, fs=0.85, dashes=1500)
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    fig.canvas.draw()
    W, H = fig.canvas.get_width_height()
    vf = ('[0:v]scale=%d:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=160:stats_mode=diff[p];'
          '[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle' % width)
    proc = subprocess.Popen([exe, '-y', '-v', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '%dx%d' % (W, H),
                             '-r', str(fps), '-i', '-', '-filter_complex', vf, '-loop', '0', path],
                            stdin=subprocess.PIPE)
    for k in range(int(seconds * fps)):
        for _ in range(sub):
            sim.step()
            sim.move_particles()
        view.update(k, sim.interior_T(), sim.frame_particles(), summarize(sim))
        fig.canvas.draw()
        proc.stdin.write(np.ascontiguousarray(np.asarray(fig.canvas.buffer_rgba())[:, :, :3]).tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        raise SystemExit('ffmpeg could not write %s' % path)


def main():
    os.makedirs(OUT, exist_ok=True)
    export_png(my_pc(), os.path.join(OUT, 'report.png'), quality='normal', warmup=4.0, progress=lambda *a: None)
    demo_gif(os.path.join(OUT, 'demo.gif'))
    for name in ('report.png', 'demo.gif'):
        print('%-12s %6.0f KB' % (name, os.path.getsize(os.path.join(OUT, name)) / 1024))


if __name__ == '__main__':
    main()
