"""Collect the numbers a person cares about from a running simulation."""
from . import branding
from . import hardware as hw
from .thermal import estimate_temps

HDD_R = 1.5          # K/W: drive surface above the air around it (a drive in a cage with some airflow)


def _ratios(L):
    """airflow through the CPU cooler / GPU fins compared with the reference airflow"""
    cool_q = [f.q for f in L.fans if f.kind in ('cooler', 'aio') and f.active]
    gpu_q = [f.q for f in L.fans if f.kind == 'gpu' and f.active]
    cooler_ratio = (max(cool_q[0] if L.draw['cooler']['kind'] == 'tower' else sum(cool_q) / len(cool_q), 0.0)
                    / L.cooler_ref_q) if cool_q and L.cooler_ref_q > 0 else 0.05
    gpu_ratio = (max(sum(gpu_q) / len(gpu_q), 0.0) / L.gpu_ref_q) if gpu_q and L.gpu_ref_q > 0 else 0.05
    return cooler_ratio, gpu_ratio


def component_temps(sim):
    """current CPU / GPU estimate (what the auto fan curve follows)"""
    L = sim.L
    d = sim.disp or sim.raw
    cooler_ratio, _ = _ratios(L)
    est = estimate_temps(L.cfg, L.loads, d['cpu_in'], d['gpu_in'], cooler_ratio, None)
    return est['t_cpu'], est['t_gpu']


def summarize(sim):
    L = sim.L
    cfg, loads = L.cfg, L.loads
    d = sim.disp or sim.raw
    per = getattr(sim, 'disp_per', {})
    cooler_ratio, gpu_ratio = _ratios(L)
    # CPU: from the simulated airflow through the cooler; GPU: from its fan speed (its fins sit edge-on in
    # this 2D view, so the simulated GPU airflow is less reliable than the card's own fan curve)
    est = estimate_temps(cfg, loads, d['cpu_in'], d['gpu_in'], cooler_ratio, None)
    Tf = sim.T.ravel()
    fans = []
    for f in L.fans:
        if f.kind not in ('case', 'aio'):
            continue
        auto = bool(getattr(f, 'auto', False))
        if f.wall == 'inside':
            cfm = abs(f.q) * (f.span[1] - f.span[0]) * 1e-3 * L.W * 2118.88
            fans.append(dict(label=f.label, wall='inside', direction=f.direction, rpm=f.rpm, cfm=cfm, auto=auto,
                             t_out=float(Tf[f.cells].mean()) if len(f.cells) else L.room, kind='inside'))
            continue
        g = per.get(f.label, {})
        cfm = g.get('CFM_in', 0.0) if f.direction == 'in' else g.get('CFM_out', 0.0)
        fans.append(dict(label=f.label, wall=f.wall, direction=f.direction, rpm=f.rpm, cfm=cfm, auto=auto,
                         t_out=g.get('T', L.room) if f.direction == 'out' else L.room, kind=f.kind))
    for f in L.openings:
        if f['fan'] is None and f['kind'] == 'aio':
            g = per.get(f['owner'], {})
            fans.append(dict(label=f['owner'] + ' (stopped)', wall=f['wall'], direction='-', rpm=0.0, auto=False,
                             cfm=g.get('CFM_out', 0.0) - g.get('CFM_in', 0.0), t_out=g.get('T', L.room), kind='aio'))
    for sd in L.sides:
        g = per.get(sd['label'], {})
        cfm = g.get('CFM_in', 0.0) if sd['direction'] == 'in' else g.get('CFM_out', 0.0)
        fans.append(dict(label=sd['label'], wall='side', direction=sd['direction'], rpm=sd['rpm'], cfm=cfm,
                         auto=bool(sd['auto']), t_out=g.get('T', L.room) if sd['direction'] == 'out' else L.room,
                         kind='side'))
    heat_by_wall = {}
    for key, g in per.items():
        if g['kind'] == 'psu':
            continue
        heat_by_wall[g['wall']] = heat_by_wall.get(g['wall'], 0.0) + max(g['heat'], 0.0)
    tot = sum(heat_by_wall.values()) or 1.0
    shares = {w: 100.0 * hh / tot for w, hh in heat_by_wall.items() if hh / tot > 0.005}
    psu = per.get('PSU', {})
    cfm_in = sum(f['cfm'] for f in fans if f['direction'] == 'in')
    cfm_out = sum(f['cfm'] for f in fans if f['direction'] == 'out')
    blocks = []
    by_index = {b['index']: b for b in L.draw.get('blocks', [])}
    for k, idx in getattr(L, 'block_probes', []):
        b = by_index.get(k)
        if b is not None:
            blocks.append(dict(label=b['label'], model=b['model'], air=b['air'], watts=b['watts'], box=b['box'],
                               t_air=float(Tf[idx].mean()) if len(idx) else L.room))
    t_hdd = None
    hdd = next((h for h in sim.hs if h['name'] == 'hdd' and len(h['idx'])), None)
    if hdd is not None:
        t_hdd = float(Tf[hdd['idx']].mean()) + L.hdd_per_drive * HDD_R * max(loads['rho_ratio'], 0.3) ** -0.8
    return dict(cpu_in=d['cpu_in'], gpu_in=d['gpu_in'], t_cpu=est['t_cpu'], t_cpu_raw=est['t_cpu_raw'],
                cpu_limited=est['cpu_limited'], tjmax=est['tjmax'], t_gpu=est['t_gpu'],
                p_case=d['p_case'], cfm_in=cfm_in, cfm_out=cfm_out, fans=fans, heat_share=shares,
                psu_cfm=psu.get('CFM_out', 0.0), psu_t_out=psu.get('T', L.room),
                heat_in=d.get('heat_in', 0.0), heat_out=d.get('heat_out', 0.0), loads=loads,
                cooler_cfm=sum(v for k, v in d.items() if k.startswith('CFM_Cooler fan')) /
                max(1, sum(1 for f in L.fans if f.kind == 'cooler')),
                cooler_ratio=cooler_ratio, gpu_ratio=gpu_ratio, t_hdd=t_hdd, blocks=blocks,
                gpu_fan_cfm=sum(v for k, v in d.items() if k.startswith('CFM_GPU fan')),
                warnings=L.warnings, n_in=L.n_in, n_out=L.n_out, room=L.room, t=sim.t)


def _cooler_rpm(cfg):
    return hw.ALL_FANS[cfg.cooler_fan_name()]['rpm']


def text_report(sim):
    s = summarize(sim)
    L = sim.L
    cfg, ld = L.cfg, s['loads']
    lines = []
    lines.append('=' * 76)
    lines.append('PC airflow simulation  -  %s load, room %.0f C' % (cfg.load, cfg.room_c))
    lines.append('%s %s  -  %s  -  %s  -  WhatsApp %s' % (
        branding.APP_NAME, branding.VERSION, branding.POWERED_BY, branding.GITHUB_TEXT, branding.WHATSAPP_TEXT))
    lines.append('=' * 76)
    lines.append('CPU  %-34s now %4.0f W   (TDP %3.0f W, max %3.0f W)' % (cfg.cpu, ld['p_cpu'], ld['cpu_tdp'], ld['cpu_max']))
    lines.append('GPU  %-34s now %4.0f W   (max board power %3.0f W)' % (cfg.gpu, ld['p_gpu'], ld['gpu_max']))
    lines.append('Motherboard  %s: %.0f W (chipset %.0f W + CPU power stage %.0f W + %.0f W other)' % (
        cfg.motherboard, ld['p_board'], ld['p_chipset'], ld['p_vrm'], hw.BOARD_MISC_W))
    lines.append('RAM  %d x %s%s: %.1f W   |   M.2 SSDs x%d: %.1f W   |   hard drives x%d: %.1f W%s' % (
        cfg.ram_sticks, cfg.ram_type, ' ECC' if cfg.ram_ecc else '', ld['p_ram'], cfg.nvme_count, ld['p_nvme'],
        cfg.hdd_count, ld['p_hdd'], ('  (drives ~%.0f C)' % s['t_hdd']) if s['t_hdd'] is not None else ''))
    lines.append('Fans and pump %.1f W   |   USB devices %.0f W (heat stays outside the case)%s' % (
        ld['p_fans'], ld['p_usb'], ('   |   your blocks %.0f W' % ld['p_blocks']) if ld.get('p_blocks') else ''))
    lines.append('System DC load %.0f W now, %.0f W max  |  from the wall %.0f W  |  PSU %d W %s at %.0f %%'
                 % (ld['p_dc'], ld['p_dc_max'], ld['p_wall'], cfg.psu_watts, cfg.psu_rating, 100 * ld['psu_frac']))
    lines.append('Recommended PSU for this PC: %d W' % ld['psu_recommended'])
    lines.append('Air: altitude %.0f m (air density %.0f %% of sea level), dust filters %s' % (
        cfg.altitude_m, 100 * ld['rho_ratio'], cfg.filter_condition))
    lines.append('-' * 76)
    lines.append('CPU cooler air in  %5.1f C   ->  CPU  ~%3.0f C %s' % (
        s['cpu_in'], s['t_cpu'], '(at its limit - would slow down)' if s['cpu_limited'] else '(estimate)'))
    lines.append('    cooler: %s, fan %s at %.0f %% (%.0f rpm), airflow through it %.0f %% of stock-fan full speed' % (
        cfg.cooler.split(' (')[0], L.draw['cooler'].get('fan_model', '').split(' (')[0], 100 * ld['f_cooler'],
        ld['f_cooler'] * _cooler_rpm(cfg), 100 * s['cooler_ratio']))
    lines.append('GPU air in         %5.1f C   ->  GPU  ~%3.0f C (core, estimate)' % (s['gpu_in'], s['t_gpu']))
    lines.append('Case pressure %+.1f Pa (%s)   airflow in %.0f CFM / out %.0f CFM' % (
        s['p_case'], 'negative' if s['p_case'] < 0 else 'positive', s['cfm_in'], s['cfm_out']))
    lines.append('-' * 76)
    lines.append('%-18s %-7s %-5s %6s %8s %9s' % ('fan', 'wall', 'dir', 'rpm', 'CFM', 'air out'))
    for f in s['fans']:
        lines.append('%-18s %-7s %-5s %6.0f %8.1f %8s' % (
            f['label'] + (' (auto)' if f.get('auto') else ''), f['wall'], f['direction'], f['rpm'], f['cfm'],
            ('%.1f C' % f['t_out']) if (f['direction'] == 'out' or f['wall'] == 'inside') else '-'))
    lines.append('PSU fan            %-7s %-4s %6.0f %8.1f %8s' % (
        'bottom' if cfg.psu_fan_mode == 'bottom intake' else 'inside', 'in', ld['f_psu'] * 1800,
        s['psu_cfm'], '%.1f C' % s['psu_t_out']))
    if any(f.get('auto') for f in s['fans']):
        c = cfg.fan_curve
        lines.append('auto fans follow the %s temperature: %.0f %% at %.0f C ... %.0f %% at %.0f C' % (
            {'hottest': 'hottest (CPU or GPU)', 'cpu': 'CPU', 'gpu': 'GPU'}[c['source']], c['pct_lo'], c['t_lo'],
            c['pct_hi'], c['t_hi']))
    if cfg.blocks:
        lines.append('-' * 76)
        lines.append('%-8s %-28s %-17s %-7s %6s %9s' % ('block', 'kind', 'size / place (mm)', 'air', 'heat', 'air at it'))
        built = {b['label']: b for b in s['blocks']}
        for k, b in enumerate(cfg.blocks):
            lab = 'Block %d' % (k + 1)
            got = built.get(lab)
            lines.append('%-8s %-28s %-17s %-7s %5.0f W %9s' % (
                lab, b.model[:28], '%.0fx%.0f @%.0f,%.0f' % (b.w_mm, b.h_mm, b.x_mm, b.y_mm), b.air, b.watts,
                ('%.1f C' % got['t_air']) if got else 'left out'))
    lines.append('-' * 76)
    lines.append('Heat leaving the case: ' + ', '.join('%s %.0f %%' % (k, v) for k, v in
                                                     sorted(s['heat_share'].items(), key=lambda kv: -kv[1])))
    lines.append('Energy check: heat added %.0f W, carried out %.0f W' % (s['heat_in'], s['heat_out'] + 0.0))
    for w in s['warnings']:
        lines.append('NOTE: ' + w)
    lines.append('=' * 76)
    return '\n'.join(lines)
