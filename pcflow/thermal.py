"""Power budget, air density, fan curves and rough component-temperature estimates."""
import numpy as np

from . import hardware as hw

RHO_SEA = 1.2                     # air density the solver and the calibrations use (sea level, ~22 °C)


def air_density(alt_m, room_c):
    """kg/m^3 from the standard atmosphere pressure at that height and the room temperature"""
    alt = min(max(float(alt_m), -500.0), 8000.0)
    p = 101325.0 * (1.0 - 2.25577e-5 * alt) ** 5.25588
    return p / (287.05 * (float(room_c) + 273.15))


def density_ratio(alt_m, room_c):
    """air density compared with sea level at 22 °C (1.0 for the default room)"""
    return air_density(alt_m, room_c) / air_density(0.0, 22.0)


def psu_efficiency(rating, load_frac):
    e10, e20, e50, e100 = hw.PSU_RATINGS[rating]
    return float(np.interp(load_frac, [0.0, 0.10, 0.20, 0.50, 1.00, 1.30], [e10 - 0.06, e10, e20, e50, e100, e100 - 0.02]))


def fan_curve_frac(curve, t):
    """case fan speed (0..1) for a temperature, like a motherboard fan header curve"""
    return float(np.interp(t, [curve['t_lo'], curve['t_hi']], [curve['pct_lo'] / 100.0, curve['pct_hi'] / 100.0]))


def curve_temp(curve, t_cpu, t_gpu):
    """the temperature the fan curve follows"""
    if curve.get('source') == 'cpu':
        return t_cpu
    if curve.get('source') == 'gpu':
        return t_gpu
    return max(t_cpu, t_gpu)


def _ram_per_stick(cfg, load):
    r = hw.RAM_TYPES[cfg.ram_type]
    return r[load] * ((1.0 + r['ecc_extra']) if cfg.ram_ecc else 1.0)


def compute_loads(cfg):
    """Power numbers for the chosen load (idle / gaming / max) and fan speeds in 'auto'."""
    cpu = hw.CPUS[cfg.cpu]
    gpu = hw.GPUS[cfg.gpu]
    mb = hw.MOTHERBOARDS[cfg.motherboard]
    cool = hw.COOLERS[cfg.cooler]
    load = cfg.load
    p_cpu = {'idle': cpu['idle_w'], 'gaming': cpu['gaming_w'], 'max': cpu['max_w']}[load]
    p_gpu = {'idle': hw.gpu_idle_w(gpu['tbp']), 'gaming': hw.GPU_GAMING_FRACTION * gpu['tbp'],
             'max': float(gpu['tbp'])}[load]
    if cfg.cpu_power_w > 0:
        p_cpu = float(cfg.cpu_power_w)
    if cfg.gpu_power_w > 0:
        p_gpu = float(cfg.gpu_power_w)

    # fan speeds (fractions of max rpm)
    gpu_frac_power = p_gpu / gpu['tbp']
    if cfg.gpu_fan_pct >= 0:
        f_gpu = cfg.gpu_fan_pct / 100.0
    else:                                  # most cards stop their fans at idle
        f_gpu = 0.0 if gpu_frac_power < 0.15 else float(np.clip(0.30 + 0.55 * gpu_frac_power, 0.3, 0.9))
    if cfg.cooler_fan_pct >= 0:
        f_cool = cfg.cooler_fan_pct / 100.0
    else:
        f_cool = float(np.clip(0.30 + 0.70 * (p_cpu / cpu['max_w']), 0.30, 1.0))
    rho_ratio = density_ratio(cfg.altitude_m, cfg.room_c)

    # auto case fans start from a quick estimate; the running simulation then follows the real temperatures
    first = estimate_temps(cfg, dict(p_cpu=p_cpu, p_gpu=p_gpu, f_gpu=f_gpu, f_cooler=f_cool, rho_ratio=rho_ratio),
                           cfg.room_c + 6.0, cfg.room_c + 6.0)
    f_auto = fan_curve_frac(cfg.fan_curve, curve_temp(cfg.fan_curve, first['t_cpu'], first['t_gpu']))

    # the rest of the PC
    p_vrm = p_cpu * (1.0 / mb['vrm_eff'] - 1.0)
    p_chipset = mb['chipset_w'] * hw.CHIPSET_LOAD[load]
    p_board = p_chipset + p_vrm + hw.BOARD_MISC_W
    p_ram = cfg.ram_sticks * _ram_per_stick(cfg, load)
    p_nvme = cfg.nvme_count * hw.STORAGE_POWER['nvme'][load]
    p_hdd = cfg.hdd_count * hw.STORAGE_POWER['hdd'][load]
    p_storage = p_nvme + p_hdd
    cooler_fan = hw.ALL_FANS[cfg.cooler_fan_name()]
    pump = hw.AIO_PUMP_W if cool['kind'] == 'aio' else 0.0

    def fans_power(case_frac=None, cool_frac=f_cool):
        p = sum(hw.fan_power_w(hw.ALL_FANS[f.model], case_frac if case_frac is not None else
                               (f_auto if f.auto else f.speed_pct / 100.0)) for f in cfg.fans)
        return p + cfg.n_cooler_fans() * hw.fan_power_w(cooler_fan, cool_frac) + pump

    p_fans = fans_power()
    p_usb = hw.USB_POWER[load]
    p_other = p_board + p_ram + p_storage + p_fans + p_usb
    p_dc = p_cpu + p_gpu + p_other
    cpu_top, gpu_top = max(cpu['max_w'], p_cpu), max(gpu['tbp'], p_gpu)     # own watts may be above the list
    p_dc_max = (cpu_top + gpu_top + mb['chipset_w'] + cpu_top * (1.0 / mb['vrm_eff'] - 1.0)
                + hw.BOARD_MISC_W + cfg.ram_sticks * _ram_per_stick(cfg, 'max')
                + cfg.nvme_count * hw.STORAGE_POWER['nvme']['max'] + cfg.hdd_count * hw.STORAGE_POWER['hdd']['max']
                + fans_power(1.0, 1.0) + hw.USB_POWER['max'])
    psu_frac = p_dc / cfg.psu_watts
    eta = psu_efficiency(cfg.psu_rating, psu_frac)
    p_wall = p_dc / eta
    p_psu = p_wall - p_dc

    # recommended PSU: max draw + 30 % head-room (+ extra for high-end GPU power spikes)
    need = p_dc_max * (1.30 if gpu['tbp'] < 350 else 1.40)
    rec = next((s for s in hw.PSU_SIZES if s >= need), hw.PSU_SIZES[-1])

    if cfg.psu_fan_mode.startswith('off'):
        f_psu = 0.0
    elif cfg.psu_fan_pct >= 0:
        f_psu = cfg.psu_fan_pct / 100.0
    else:                                  # semi-passive PSU: fan only above ~25 % load
        f_psu = 0.0 if psu_frac < 0.25 else float(np.clip(0.30 + 0.70 * (psu_frac - 0.25) / 0.75, 0.3, 1.0))

    warnings = []
    if p_dc_max > cfg.psu_watts:
        warnings.append('PSU %d W is below the maximum system draw (%.0f W)' % (cfg.psu_watts, p_dc_max))
    elif rec > cfg.psu_watts:
        warnings.append('PSU %d W has little head-room; %d W recommended' % (cfg.psu_watts, rec))
    memory = cpu.get('memory', 'DDR4/DDR5')
    if cfg.ram_type not in memory.split('/'):
        warnings.append('%s uses %s memory - %s sticks do not fit its boards' % (cfg.cpu, memory.replace('/', ' or '),
                                                                                 cfg.ram_type))
    if cfg.ram_ecc and cpu.get('vendor') == 'Intel' and not mb['ecc']:
        warnings.append('Intel Core CPUs only use ECC on W680 / W880 boards - on this board the ECC sticks run '
                        'without error correction')
    return dict(p_cpu=float(p_cpu), p_gpu=float(p_gpu), p_other=float(p_other), p_dc=float(p_dc),
                p_dc_max=float(p_dc_max), psu_frac=float(psu_frac), eta=eta, p_wall=float(p_wall),
                p_psu=float(p_psu), psu_recommended=rec, cpu_max=float(cpu['max_w']), cpu_tdp=float(cpu['tdp']),
                gpu_max=float(gpu['tbp']), f_gpu=f_gpu, f_cooler=f_cool, f_psu=f_psu, f_auto=f_auto,
                p_board=float(p_board), p_vrm=float(p_vrm), p_chipset=float(p_chipset), p_ram=float(p_ram),
                p_nvme=float(p_nvme), p_hdd=float(p_hdd), p_storage=float(p_storage), p_fans=float(p_fans),
                p_usb=float(p_usb), rho_ratio=float(rho_ratio), warnings=warnings)


def estimate_temps(cfg, loads, cpu_air_in, gpu_air_in, cooler_ratio=None, gpu_ratio=None):
    """Rough core temperatures from the air reaching each cooler and the airflow through it.

    cooler_ratio / gpu_ratio = simulated airflow through the CPU cooler (or radiator) / GPU fins
    divided by the airflow the stock fans give at full speed (CPU) or 70 % (GPU).  Thermal
    resistance grows as 1 / sqrt(airflow), so slower or blocked fans raise the estimate.
    Thinner air (altitude) carries less heat for the same airflow: heat-sink resistance grows
    as (sea-level density / density)^0.8.

    GPU : coolers are sized so that at full board power and ~70 % fan the core sits ~45 K
          above its intake air.
    CPU : intake air + power x (cooler resistance + die-to-cooler resistance).
    """
    gpu = hw.GPUS[cfg.gpu]
    cpu = hw.CPUS[cfg.cpu]
    cool = hw.COOLERS[cfg.cooler]
    k_air = max(loads.get('rho_ratio', 1.0), 0.3) ** -0.8
    if gpu_ratio is None:
        f_g = loads['f_gpu']
        k_gpu = (0.70 / f_g) ** 0.5 if f_g > 0.05 else 2.6
    else:
        k_gpu = min(2.6, max(gpu_ratio, 0.05) ** -0.5)
    t_gpu = gpu_air_in + loads['p_gpu'] * 45.0 / gpu['tbp'] * k_gpu * k_air
    if cooler_ratio is None:
        k_cpu = (1.0 / max(loads['f_cooler'], 0.2)) ** 0.5
    else:
        k_cpu = min(3.5, max(cooler_ratio, 0.05) ** -0.5)
    r_cpu = cool['r100'] * k_cpu * k_air + cpu['r_int']
    t_cpu = cpu_air_in + loads['p_cpu'] * r_cpu
    limited = t_cpu > cpu['tjmax']
    return dict(t_cpu=float(min(t_cpu, cpu['tjmax'])), t_cpu_raw=float(t_cpu), cpu_limited=bool(limited),
                tjmax=float(cpu['tjmax']), t_gpu=float(t_gpu), k_cpu=float(k_cpu), k_gpu=float(k_gpu))
