"""Make the window pictures for the GitHub page: docs/images/app-window.png, blocks.png, the tab pictures and
about.png.  It opens the real window, lets the air settle, then photographs it.

Needs a screen. On Linux a virtual one is fine:
    xvfb-run -a -s "-screen 0 1600x1000x24" python tools/make_screenshots.py
"""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ['PCFLOW_PARTS'] = os.path.join(tempfile.mkdtemp(), 'my_parts.json')   # only the built-in parts

import tkinter as tk  # noqa: E402

from PIL import ImageGrab  # noqa: E402

from pcflow import gui  # noqa: E402
from pcflow.config import Config, my_pc  # noqa: E402

OUT = os.path.join(HERE, 'docs', 'images')
SIZE = '1560x920+0+0'


def grab(widget, name, height=None):
    widget.update_idletasks()
    x, y = widget.winfo_rootx(), widget.winfo_rooty()
    w, h = widget.winfo_width(), height or widget.winfo_height()
    display = os.environ.get('DISPLAY') if sys.platform.startswith('linux') else None
    ImageGrab.grab(bbox=(x, y, x + w, y + h), xdisplay=display).save(os.path.join(OUT, name))
    print('%-16s %4d x %d' % (name, w, h))


def show(app, tab):
    app.nb.select(tab)
    for _ in range(3):
        app.root.update()
    time.sleep(0.2)
    app.root.update()


def shoot(cfg, seconds, pictures):
    """open the window with this setup, simulate for a few seconds, then take the pictures"""
    root = tk.Tk()
    root.geometry(SIZE)
    app = gui.App(root, cfg)

    def take():
        app.running = False                  # the simulation stops while the pictures are taken
        for fn in pictures:
            fn(app)
        app.close()
    root.after(int(seconds * 1000), take)
    root.mainloop()


def window_pictures(app):
    show(app, 0)
    grab(app.root, 'app-window.png')
    for tab, name in ((gui.TAB_FANS, 'fans-tab.png'), (3, 'case-tab.png')):
        show(app, tab)
        grab(app.nb, name)
    show(app, app.tab_results)
    app.update_report()
    show(app, app.tab_results)
    grab(app.nb, 'results-tab.png')
    show(app, 4)                                  # Parts: a graphics card copied as a new part
    app.parts_select_category('gpu')
    iid = next(i for i, n in app._pnames.items() if n == app.cfg.gpu)
    app.ptree.selection_set(iid)
    app.ptree.see(iid)
    app.parts_copy()
    app.part_name.set('My RTX 4070 Super OC')
    app.part_vars['tbp'].set('245')
    app.part_vars['length'].set('336')
    app.ptree.yview_moveto(0)
    show(app, 4)
    grab(app.nb, 'parts-tab.png', height=694)
    win = app.show_about()
    for _ in range(3):
        app.root.update()
    time.sleep(0.2)
    app.root.update()
    grab(win, 'about.png')
    win.destroy()


def block_pictures(app):
    app.select_block(0)
    show(app, gui.TAB_BLOCKS)
    grab(app.root, 'blocks.png')
    grab(app.nb, 'blocks-tab.png')


def main():
    os.makedirs(OUT, exist_ok=True)
    shoot(my_pc(), 8.0, [window_pictures])
    shoot(Config.read(os.path.join(HERE, 'configs', 'example_blocks.json')), 8.0, [block_pictures])


if __name__ == '__main__':
    main()
