"""Command line: simulate a saved setup without the window.

    python run_cli.py configs/my_pc.json --report
    python run_cli.py configs/my_pc.json --png result.png
    python run_cli.py configs/my_pc.json --video result.mp4 --seconds 20 --quality high
    python run_cli.py --selftest
"""
import argparse
import sys
import time

from . import branding, library
from .config import Config, QUALITY_MM, my_pc
from .layout import Layout
from .solver import Solver
from .results import text_report


def main(argv=None, prog=None):
    title = '%s %s - PC case airflow simulator  (%s)' % (branding.APP_NAME, branding.VERSION, branding.POWERED_BY)
    contact = '%s\n  GitHub    %s\n  WhatsApp  %s' % (branding.POWERED_BY, branding.GITHUB_URL, branding.WHATSAPP_TEXT)
    ap = argparse.ArgumentParser(prog=prog, description=title, epilog=contact,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--version', action='version', version='%s %s - %s\nGitHub %s - WhatsApp %s' % (
        branding.APP_NAME, branding.VERSION, branding.POWERED_BY, branding.GITHUB_URL, branding.WHATSAPP_TEXT))
    ap.add_argument('config', nargs='?', help='setup file (.json) - made with the app or by hand')
    ap.add_argument('--report', action='store_true', help='print temperatures, airflow and power')
    ap.add_argument('--png', help='save a report image (.png)')
    ap.add_argument('--video', help='save a video (.mp4, or .gif)')
    ap.add_argument('--seconds', type=float, default=20.0, help='video length')
    ap.add_argument('--quality', choices=list(QUALITY_MM), help='fast / normal / high (overrides the file)')
    ap.add_argument('--warmup', type=float, default=3.0, help='simulated seconds before measuring')
    ap.add_argument('--load', choices=['idle', 'gaming', 'max'], help='override the load in the file')
    ap.add_argument('--selftest', action='store_true', help='quick check that everything works')
    ap.add_argument('--no-parts-file', action='store_true',
                    help='use only the parts stored inside the setup file, not my_parts.json')
    a = ap.parse_args(argv)
    if 'matplotlib.pyplot' not in sys.modules:
        import matplotlib
        matplotlib.use('Agg')                   # pictures are drawn off-screen, no window needed

    if a.selftest:
        cfg = my_pc()
        cfg.quality = 'fast'
        t0 = time.time()
        sim = Solver(Layout(cfg))
        sim.run(2.0)
        print(text_report(sim))
        r = sim.raw
        bal = abs(r['cfm_in'] - r['cfm_out']) / max(r['cfm_in'], 1)
        ok = bal < 0.01 and abs(r['heat_out'] - r['heat_in']) / r['heat_in'] < 0.15
        print('mass balance error %.2f %%, energy balance %.0f / %.0f W, %.1f s  ->  %s' % (
            100 * bal, r['heat_out'], r['heat_in'], time.time() - t0, 'OK' if ok else 'CHECK'))
        return 0 if ok else 1
    if not a.config:
        ap.print_help()
        return 1
    if not a.no_parts_file:
        for note in library.load():             # your own parts (setups also carry the ones they use)
            print('note: ' + note, file=sys.stderr)
    try:
        cfg = Config.read(a.config)
    except (OSError, ValueError) as e:
        print('Could not read the setup: %s' % e, file=sys.stderr)
        return 2
    for note in cfg.notes:
        print('note: ' + note, file=sys.stderr)
    if a.quality:
        cfg.quality = a.quality
    if a.load:
        cfg.load = a.load
    if not (a.png or a.video):
        a.report = True
    sim = None
    try:
        if a.video:
            from .video import export_video
            sim = export_video(cfg, a.video, seconds=a.seconds, warmup=a.warmup)
        elif a.png:
            from .video import export_png
            sim = export_png(cfg, a.png, warmup=a.warmup)
        if a.png and a.video:
            from .video import export_png
            export_png(cfg, a.png, warmup=a.warmup)
    except (RuntimeError, OSError) as e:
        print('Export failed: %s' % e, file=sys.stderr)
        return 3
    if sim is not None and not a.report:
        for w in sim.L.warnings:
            print('note: ' + w, file=sys.stderr)
    if a.report:
        if sim is None:
            sim = Solver(Layout(cfg))
            sim.run(a.warmup)
        print(text_report(sim))
    return 0


if __name__ == '__main__':
    sys.exit(main())
