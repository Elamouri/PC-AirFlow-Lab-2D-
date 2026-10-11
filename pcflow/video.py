"""Export a simulation as an MP4 video (or GIF fallback) and as a PNG report image."""
import math
import os
import shutil
import subprocess

import sys

import numpy as np

from . import branding
from .config import QUALITY_MM
from .layout import Layout
from .solver import Solver
from .results import summarize
from .render import ReportFrame


def _ffmpeg():
    """full path of ffmpeg - never a bare name or one sitting in the current folder"""
    found = []
    try:
        import imageio_ffmpeg
        env = os.environ.get('IMAGEIO_FFMPEG_EXE', '')
        bindir = os.path.join(os.path.dirname(imageio_ffmpeg.__file__), 'binaries')
        bundled = os.path.isdir(bindir) and any(f.startswith('ffmpeg') for f in os.listdir(bindir))
        if bundled or os.path.isabs(env):      # otherwise its own search would run a bare 'ffmpeg'
            found.append(imageio_ffmpeg.get_ffmpeg_exe())
    except (ImportError, RuntimeError, OSError):
        pass
    found.append(shutil.which('ffmpeg'))
    here = os.path.realpath(os.getcwd())
    for exe in found:
        if exe and os.path.isabs(exe):
            real = os.path.realpath(exe)
            if os.path.isfile(real) and os.path.dirname(real) != here:
                return real
    return None


# Windows: ffmpeg is a console program - without this a black console window would pop up during the export
NO_WINDOW = {'creationflags': subprocess.CREATE_NO_WINDOW} if sys.platform.startswith('win') else {}
PNG_INFO = {'Software': '%s %s' % (branding.APP_NAME, branding.VERSION), 'Author': branding.AUTHOR,
            'Comment': branding.CREDIT_ASCII}


def free_name(path):
    """path, or 'name (2).ext' ... if a file with that name exists already"""
    base, ext = os.path.splitext(path)
    k = 2
    while os.path.exists(path):
        path = '%s (%d)%s' % (base, k, ext)
        k += 1
    return path


def prepare(cfg, quality=None, warmup=3.0, fps=30, slowmo=0.25, n_particles=1700, progress=print):
    """Build the layout, run the airflow to a steady state and return (layout, solver, substeps)."""
    h_mm = QUALITY_MM[quality or cfg.quality]
    layout = Layout(cfg, h_mm)
    frame_dt = slowmo / fps
    dt0 = 0.7 * layout.h
    sub = max(1, math.ceil(frame_dt / dt0))
    sim = Solver(layout, n_particles=n_particles, dt=frame_dt / sub)
    n = int(round(warmup / sim.dt))
    for k in range(n):
        sim.step()
        if k % max(1, n // 20) == 0:
            progress('warming up  %3d %%' % (100 * k / n))
    sim.update_probes()
    sim.set_heat_capacity(400.0)          # real heat sinks change temperature slowly
    for _ in range(30):                   # let the flow dashes settle into the flow
        for _ in range(sub):
            sim.step()
            sim.move_particles()
        sim.frame_particles()
    return layout, sim, sub


def export_png(cfg, path, quality=None, warmup=3.0, progress=print):
    layout, sim, sub = prepare(cfg, quality, warmup, progress=progress)
    frame = ReportFrame(layout)
    frame.update(0, sim.interior_T(), sim.frame_particles(), summarize(sim))
    frame.fig.savefig(path, format='png', facecolor=frame.fig.get_facecolor(), metadata=PNG_INFO)
    progress('saved %s' % path)
    return sim


def export_video(cfg, path, seconds=20.0, quality=None, warmup=3.0, fps=30, slowmo=0.25, progress=print):
    layout, sim, sub = prepare(cfg, quality, warmup, fps, slowmo, progress=progress)
    frame = ReportFrame(layout)
    nframes = int(round(seconds * fps))
    exe = _ffmpeg()
    gif = exe is None or path.lower().endswith('.gif')
    if gif and not path.lower().endswith('.gif'):
        path = free_name(os.path.splitext(path)[0] + '.gif')
        progress('ffmpeg not found - writing a GIF instead: %s' % path)
    images = []
    proc = None
    if not gif:
        w, h = frame.fig.canvas.get_width_height()
        cmd = [exe, '-y', '-v', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '%dx%d' % (w, h), '-r', str(fps),
               '-i', '-', '-c:v', 'libx264', '-preset', 'medium', '-crf', '19', '-pix_fmt', 'yuv420p',
               '-movflags', '+faststart', '-f', 'mp4', '-metadata', 'title=PC airflow simulation',
               '-metadata', 'artist=' + branding.AUTHOR, '-metadata', 'comment=' + branding.CREDIT_ASCII, path]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, **NO_WINDOW)
    t0 = sim.t
    for k in range(nframes):
        for _ in range(sub):
            sim.step()
            sim.move_particles()
        P = sim.frame_particles()
        frame.update(k, sim.interior_T(), P, summarize(sim), t_real=sim.t - t0)
        rgb = frame.rgb()
        if gif:
            if k % 2 == 0:
                from PIL import Image
                images.append(Image.fromarray(np.ascontiguousarray(rgb)).resize((540, 960)))
        else:
            try:
                proc.stdin.write(np.ascontiguousarray(rgb).tobytes())
            except (BrokenPipeError, OSError) as e:
                proc.kill()
                raise RuntimeError('ffmpeg stopped while writing the video (%s) - nothing usable was saved' % e) from e
        if k % 30 == 0:
            progress('video frame %d / %d' % (k, nframes))
    if gif:
        images[0].save(path, save_all=True, append_images=images[1:], duration=int(2000 / fps), loop=0,
                       comment=branding.CREDIT_ASCII.encode('ascii'))
    else:
        proc.stdin.close()
        code = proc.wait()
        if code != 0 or not os.path.exists(path) or os.path.getsize(path) == 0:
            raise RuntimeError('ffmpeg could not write %s (exit code %s)' % (path, code))
    progress('saved %s' % path)
    return sim
