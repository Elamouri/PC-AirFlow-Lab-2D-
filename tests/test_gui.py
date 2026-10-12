"""Window tests (need a screen; skipped on a headless machine without a virtual display)."""
import os
import sys
import types

import pytest

tk = pytest.importorskip('tkinter')

from pcflow import hardware as hw  # noqa: E402
from pcflow.config import my_pc  # noqa: E402


def _screen():
    if sys.platform.startswith('win') or sys.platform == 'darwin':
        return True
    return bool(os.environ.get('DISPLAY'))


pytestmark = pytest.mark.skipif(not _screen(), reason='needs a screen')
ITX = 'Mini-ITX (B650I / Z790I class)'


@pytest.fixture
def app():
    from pcflow.gui import App
    root = tk.Tk()
    a = App(root, my_pc())
    a.running = False
    pump(a)
    yield a
    a.close()


def pump(app, n=3):
    for _ in range(n):
        app.root.update()


def rejected(app):
    app.rebuild(keep=False)
    return app.view.L.draw['rejected']


def test_add_and_duplicate_never_overlap(app):
    for _ in range(3):
        app.add_fan()
    for k in (0, 3, 6):
        app.select_fan(k)
        app.dup_fan()
    pump(app)
    assert len(app.cfg.fans) == 13
    assert rejected(app) == []


def mouse(app, x, y, button=1, dbl=False):
    return types.SimpleNamespace(inaxes=app.ax, xdata=x, ydata=y, button=button, dblclick=dbl,
                                 guiEvent=types.SimpleNamespace(x_root=10, y_root=10))


def test_drag_onto_another_fan_snaps_beside_it(app):
    D = app.cfg.case.depth_mm
    app.on_press(mouse(app, D + 44, 130))           # Fan 1 icon outside the front panel
    assert app.drag == 0
    app.on_motion(mouse(app, D + 44, 250))          # onto Fan 2
    app.on_release(mouse(app, D + 44, 250))
    pump(app)
    assert abs(app.cfg.fans[0].pos_mm - 250) >= 115
    assert rejected(app) == []


def test_double_click_inside_adds_a_free_inside_fan(app):
    g = app.view.L.draw['gpu']['box']
    app.on_press(mouse(app, (g[0] + g[1]) / 2, (g[2] + g[3]) / 2, dbl=True))
    pump(app)
    assert app.cfg.fans[-1].wall == 'inside'
    assert rejected(app) == []


def test_changing_to_a_full_wall_keeps_the_fan_where_it_was(app):
    app.select_fan(6)                               # rear exhaust
    app.v_wall.set('top')                           # top already has 3 fans
    app.on_fan_edit()
    pump(app)
    assert app.cfg.fans[6].wall == 'rear'
    assert 'top' in app.status.cget('text')


def test_parts_tab_new_gpu_appears_in_the_hardware_list(app):
    app.parts_select_category('gpu')
    app.parts_new()
    app.part_name.set('My test card')
    for key, val in dict(tbp='260', length='305', slots='2.5', fans='3').items():
        app.part_vars[key].set(val)
    assert app.parts_save()
    assert 'My test card' in hw.GPUS
    assert 'My test card' in app.cb_gpu.cget('values')
    app.parts_use()
    assert app.cfg.gpu == 'My test card'


def test_parts_tab_shows_what_is_wrong(app):
    app.parts_select_category('fan')
    app.parts_new()
    app.part_name.set('Broken fan')
    app.part_vars['rpm'].set('-5')
    assert not app.parts_save()
    assert 'rpm' in app.l_part_err.cget('text').lower()
    assert 'Broken fan' not in hw.ALL_FANS


def test_new_hardware_controls_reach_the_setup(app):
    app.v_board.set(ITX)
    app.v_hdd.set(2)
    app.v_nvme.set(3)
    app.v_ram_type.set('DDR5')
    app.v_ecc.set(True)
    app.on_hw()
    app.v_alt.set(900)
    app.v_filter.set('clogged')
    app.on_case()
    c = app.cfg
    assert (c.motherboard, c.hdd_count, c.nvme_count, c.ram_ecc) == (ITX, 2, 3, True)
    assert (c.altitude_m, c.filter_condition) == (900, 'clogged')
    assert c.ram_sticks <= 2
    app.rebuild(keep=False)
    assert app.view.L.draw['board_form'] == 'Mini-ITX'


def test_fan_auto_checkbox(app):
    app.select_fan(0)
    app.sc_fan.v_auto.set(True)
    app.on_fan_edit()
    assert app.cfg.fans[0].auto
    assert app.tree.item('0', 'values')[5].startswith('auto')


def test_position_arrows_never_put_a_fan_on_another(app):
    app.select_fan(0)
    app.v_pos.set(135)                              # one arrow click up from 130 mm
    app.root.tk.call(app.sp_pos.cget('command'))    # what the spinbox arrow runs
    pump(app)
    assert rejected(app) == []
    assert app.cfg.fans[0].pos_mm <= 132


def test_text_that_is_not_a_number_is_reported(app):
    app.v_cpu_w.set('150W')
    app.on_hw()
    assert 'not a number' in app.status.cget('text')
    assert app.cfg.cpu_power_w == 0


def test_a_setup_that_cannot_be_built_stops_the_view(app, monkeypatch):
    import pcflow.gui as gui

    def broken(*a, **k):
        raise RuntimeError('test failure')
    monkeypatch.setattr(gui, 'Layout', broken)
    app.rebuild(keep=False)
    assert app.sim is None and app.view is None
    assert 'stopped' in app.warn.cget('text')
    app.running = True
    app.tick()                                      # nothing runs on a stopped simulation


def test_mouse_wheel_does_not_change_lists(app):
    before = app.v_cpu.get()
    app.cb_cpu.event_generate('<MouseWheel>', delta=-120)
    app.cb_cpu.event_generate('<Button-5>')
    pump(app)
    assert app.v_cpu.get() == before


def test_notes_window_shows_everything(app):
    win = app.show_notes('Test', ['note %d' % k for k in range(40)])
    pump(app)
    assert win.winfo_exists()
    win.destroy()


def test_impossible_card_length_from_the_box(app):
    app.v_gpu_len.set(5)
    app.on_hw()
    pump(app)
    assert app.cfg.gpu_length_mm == 0 and app.v_gpu_len.get() == 0
    assert app.sim is not None


def test_infinity_in_a_whole_number_box_is_reported(app):
    app.root.globalsetvar(str(app.v_nvme), 'inf')
    app.on_hw()
    assert 'not a number' in app.status.cget('text')
    assert app.cfg.nvme_count == 1


def test_text_in_an_rpm_box_is_reported(app):
    app.select_fan(0)
    app.sc_fan.v_rpm.set('1200 rpm')
    app.sc_fan._typed()
    assert 'not a number' in app.status.cget('text')
    assert app.cfg.fans[0].speed_pct == 70


def test_own_watts_keep_the_last_good_value(app):
    app.v_cpu_w.set(120)
    app.on_hw()
    app.v_cpu_w.set('150W')
    app.on_hw()
    assert app.cfg.cpu_power_w == 120


def test_closing_after_the_export_already_finished(monkeypatch):
    import subprocess
    import time
    from pcflow.gui import App
    root = tk.Tk()
    a = App(root, my_pc())
    a.running = False
    a.job = subprocess.Popen([sys.executable, '-c', 'pass'])
    a.job.wait()
    a.job_path, a.job_started = os.path.join(os.path.dirname(__file__), 'no_such_video.mp4'), time.time()
    monkeypatch.setattr('pcflow.gui.messagebox.askyesno', lambda *x, **k: True)
    a.close()                                       # must not raise, nothing to stop or delete


def test_window_shows_the_credit(app):
    from pcflow import branding
    assert branding.POWERED_BY in app.root.title()
    assert app.l_brand.cget('text') == branding.POWERED_BY


def test_credit_links_open_github_and_whatsapp(app, monkeypatch):
    from pcflow import branding
    opened = []
    monkeypatch.setattr('pcflow.gui.webbrowser.open', lambda url, *a, **k: opened.append(url) or True)

    def labels(widget):
        for w in widget.winfo_children():
            yield w
            yield from labels(w)

    links = {w.cget('text'): w for w in labels(app.root) if w.winfo_class() == 'TLabel'
             and str(w.cget('cursor')) == 'hand2'}
    for text, w in links.items():
        w.event_generate('<Button-1>')
    pump(app)
    assert branding.GITHUB_URL in opened and branding.WHATSAPP_URL in opened
    assert any('WhatsApp' in t and branding.WHATSAPP_TEXT in t for t in links)


def test_about_window(app, monkeypatch):
    from pcflow import branding
    opened = []
    monkeypatch.setattr('pcflow.gui.webbrowser.open', lambda url, *a, **k: opened.append(url) or True)
    win = app.show_about()
    pump(app)
    assert win.winfo_exists()
    assert app.show_about() is win                       # a second click brings the same window back
    texts = []

    def walk(w):
        for c in w.winfo_children():
            try:
                texts.append(str(c.cget('text')))
            except tk.TclError:
                pass
            walk(c)
    walk(win)
    assert branding.POWERED_BY in texts and branding.GITHUB_TEXT in texts and branding.WHATSAPP_TEXT in texts
    app.open_link(branding.WHATSAPP_URL)
    assert opened == [branding.WHATSAPP_URL]
    win.destroy()
    assert app.show_about() is not win                   # closed: a new one opens


def test_a_broken_browser_is_reported(app, monkeypatch):
    import webbrowser

    def broken(url, *a, **k):
        raise webbrowser.Error('no browser')
    monkeypatch.setattr('pcflow.gui.webbrowser.open', broken)
    app.open_link('https://github.com/Elamouri')
    assert 'Could not open' in app.status.cget('text')


def test_read_outs_wrap_on_a_narrow_window(app):
    app.root.geometry('1000x700')
    pump(app, 6)
    assert app._tile_cols == 3
    rows = {int(f.grid_info()['row']) for f in app._tile_frames}
    assert rows == {0, 1}
    app.root.geometry('1560x900')
    pump(app, 6)
    assert app._tile_cols == 6
    assert {int(f.grid_info()['row']) for f in app._tile_frames} == {0}


def test_controls_keep_their_width(app):
    pump(app, 4)
    need = max(f.winfo_reqwidth() for f in app._tab_frames)
    assert app.nb.winfo_width() >= need


def test_background_export_gets_no_console_window(app, monkeypatch, tmp_path):
    seen = {}

    class FakeProc:
        stdout = iter(())
        pid = 1

        def poll(self):
            return 0

        def wait(self, timeout=None):
            return 0

    def fake_popen(cmd, **kw):
        seen.update(kw, cmd=cmd)
        return FakeProc()
    monkeypatch.setattr('pcflow.gui.subprocess.Popen', fake_popen)
    app.start_export('png', str(tmp_path / 'p.png'))
    assert seen['env']['PYTHONUNBUFFERED'] == '1'
    assert '--no-parts-file' in seen['cmd']
    if sys.platform.startswith('win'):
        assert seen['creationflags'] & 0x08000000          # CREATE_NO_WINDOW
    else:
        assert seen['start_new_session']
    app.job = None
    app._remove_tmp()


def test_export_dialog_name_gets_the_right_extension(app, monkeypatch):
    started = []
    monkeypatch.setattr(app, 'start_export', lambda kind, p: started.append((kind, p)))
    for kind, typed, wanted in (('png', 'C:/out/airflow v1.3', 'C:/out/airflow v1.3.png'),
                                ('png', 'C:/out/a.PNG', 'C:/out/a.PNG'),
                                ('video', 'C:/out/clip v2.0', 'C:/out/clip v2.0.mp4'),
                                ('video', 'C:/out/clip.gif', 'C:/out/clip.gif')):
        monkeypatch.setattr('pcflow.gui.filedialog.asksaveasfilename', lambda *a, t=typed, **k: t)
        app.export(kind)
        assert started[-1] == (kind, wanted)


def test_read_outs_rearrange_when_the_numbers_grow(app, monkeypatch):
    from pcflow.results import summarize
    calls = []
    monkeypatch.setattr(app, '_flow_tiles', lambda: calls.append(1))
    app.sim.run(0.1)
    app.summary = summarize(app.sim)
    app.update_tiles()
    assert calls


def test_link_without_a_browser_is_reported(app, monkeypatch):
    monkeypatch.setattr('pcflow.gui.webbrowser.open', lambda url, *a, **k: False)    # what Windows does
    app.open_link('https://wa.me/962796742759')
    assert 'no web browser' in app.status.cget('text')


def test_number_boxes_show_whole_numbers(app):
    app.select_fan(0)
    assert app.sp_pos.get() == '130'                     # not 130.0
    assert app.root.globalgetvar(str(app.v_cpu_w)) in (0, '0')
    app.v_pos.set(132.5)
    assert app.sp_pos.get() == '132.5'                   # real decimals stay


# ---------------------------------------------------------------- blocks
def blocks_left_out(app):
    app.rebuild(keep=False)
    return app.view.L.draw['rejected_blocks']


def test_add_block_button_puts_it_on_a_free_spot(app):
    app.v_bkind_new.set('Pump + reservoir')
    app.add_block()
    app.add_block()
    pump(app)
    assert [b.model for b in app.cfg.blocks] == ['Pump + reservoir'] * 2
    assert app.bsel == 1 and app.btree.selection() == ('b1',)
    assert blocks_left_out(app) == [] and rejected(app) == []


def test_drag_a_block_onto_the_gpu_snaps_beside_it(app):
    app.add_block('Pump + reservoir')
    app.rebuild(keep=False)
    b = app.cfg.blocks[0]
    g = app.view.L.draw['gpu']['box']
    app.on_press(mouse(app, b.x_mm, b.y_mm))
    assert app.bdrag is not None and app.bdrag['mode'] == 'move'
    app.on_motion(mouse(app, 0.5 * (g[0] + g[1]), 0.5 * (g[2] + g[3])))
    assert 'would sit on the GPU' in app.status.cget('text')
    app.on_release(mouse(app, 0.5 * (g[0] + g[1]), 0.5 * (g[2] + g[3])))
    pump(app)
    assert app.bdrag is None and 'moved beside it' in app.status.cget('text')
    assert blocks_left_out(app) == []


def test_drag_the_corner_to_resize_a_block(app):
    app.add_block('Block (no air through)')
    app.rebuild(keep=False)
    b = app.cfg.blocks[0]
    x0, x1, y0, y1 = b.box()
    app.on_press(mouse(app, x1 - 2, y1 - 2))
    assert app.bdrag['mode'] == 'resize'
    app.on_motion(mouse(app, x1 - 30, y1 + 10))
    app.on_release(mouse(app, x1 - 30, y1 + 10))
    b = app.cfg.blocks[0]
    assert (b.w_mm, b.h_mm) == (pytest.approx(x1 - 30 - x0, abs=1), pytest.approx(y1 + 10 - y0, abs=1))
    assert b.box()[0] == pytest.approx(x0, abs=0.6)               # the opposite corner stays put
    app.rebuild(keep=True)                                        # (the mouse finds what is drawn)
    x0, x1, y0, y1 = app.cfg.blocks[0].box()
    app.on_press(mouse(app, x1 - 2, y1 - 2))
    assert app.bdrag['mode'] == 'resize'
    top = app.cfg.case.height_mm - 3
    app.on_motion(mouse(app, x1 - 2, top))                        # up into the top fans: refused
    app.on_release(mouse(app, x1 - 2, top))
    assert 'keeps its size' in app.status.cget('text') and app.cfg.blocks[0].box() == (x0, x1, y0, y1)


def test_right_click_an_empty_spot_adds_a_block_there(app):
    app.on_press(mouse(app, 60, 380, button=3))
    assert app._menu_xy == (60, 380)
    app.emenu_kind.invoke(app.emenu_kind.index('Cable bundle'))
    pump(app)
    b = app.cfg.blocks[-1]
    assert b.model == 'Cable bundle' and abs(b.x_mm - 60) < 40 and abs(b.y_mm - 380) < 60
    assert blocks_left_out(app) == []


def test_block_menu_turns_changes_and_deletes(app):
    app.add_block('Capture / sound card')
    app.rebuild(keep=False)
    b = app.cfg.blocks[0]
    app.on_press(mouse(app, b.x_mm, b.y_mm, button=3))
    assert app.bsel == 0 and app.v_bmenu_air.get() == 'dense'
    app.turn_block()
    assert (app.cfg.blocks[0].w_mm, app.cfg.blocks[0].h_mm) == (20.0, 170.0)
    app.set_block_air('mesh')
    app.set_block_kind('Pump + reservoir')
    assert app.cfg.blocks[0].model == 'Pump + reservoir' and app.cfg.blocks[0].air == 'dense'
    app.del_block()
    assert app.cfg.blocks == [] and app.bsel is None
    assert blocks_left_out(app) == []


def test_blocks_tab_editing_reaches_the_setup_and_the_power_budget(app):
    app.add_block('Heat source')
    app.v_bwatts.set(45)
    app.on_block_edit()
    assert app.cfg.blocks[0].watts == 45
    assert 'your blocks 45 W' in app.l_power.cget('text')
    app.v_bw.set('lots')
    app.on_block_edit()
    assert 'not a number' in app.status.cget('text') and app.cfg.blocks[0].w_mm == 60


def test_own_block_kind_from_the_parts_tab(app):
    app.parts_select_category('block')
    app.parts_new()
    app.part_name.set('My reservoir')
    for key, val in dict(w='70', h='150', air='dense', watts='8').items():
        app.part_vars[key].set(val)
    assert app.parts_save()
    assert 'My reservoir' in app.cb_bkind_new.cget('values')
    iid = next(i for i, n in app._pnames.items() if n == 'My reservoir')
    app.ptree.selection_set(iid)
    app.parts_use()
    assert app.cfg.blocks[-1].model == 'My reservoir' and app.cfg.blocks[-1].watts == 8
    assert blocks_left_out(app) == []


def test_fix_overlaps_moves_a_block_and_the_simulation_waits_while_dragging(app):
    from pcflow.config import Block
    g = app.view.L.draw['gpu']['box']
    app.cfg.blocks = [Block.of('Pump + reservoir', 0.5 * (g[0] + g[1]), 0.5 * (g[2] + g[3]))]
    assert blocks_left_out(app)
    assert 'Fix overlaps' in app.warn.cget('text')
    app.fix_overlaps()
    assert blocks_left_out(app) == []
    b = app.cfg.blocks[0]
    app.on_press(mouse(app, b.x_mm, b.y_mm))
    app.running = True
    t = app.sim.t
    app.tick()
    assert app.sim.t == t                                         # no simulation while a block is held
    app.on_release(mouse(app, b.x_mm, b.y_mm))
    app.running = False


def test_ready_made_fan_layouts_keep_your_blocks(app):
    app.add_block('Pump + reservoir')
    app.load_preset()
    assert [b.model for b in app.cfg.blocks] == ['Pump + reservoir']
