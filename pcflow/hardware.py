"""Built-in hardware database.

Everything here is plain Python data - add your own parts by copying a line.

Power figures
-------------
GPU  tbp       : maximum total board / graphics power from the manufacturer (W)
     length/slots/fans : a typical partner card (override the length in the app if yours differs)
CPU  tdp       : the "TDP" printed on the box (W)
     max_w     : the sustained power limit the CPU may really draw (AMD PPT / Intel PL2) (W)
     gaming_w  : rough typical draw while gaming - varies a lot from game to game (W)
     idle_w    : desktop idle (W)
     r_int     : rough die -> cooler thermal resistance (K/W) used for the temperature estimate
     tjmax     : the temperature at which the CPU starts limiting itself (deg C)
"""

GPUS = {
    # ---------------- NVIDIA GeForce RTX 50
    "NVIDIA GeForce RTX 5090":          dict(tbp=575, length=340, slots=3.5, fans=3),
    "NVIDIA GeForce RTX 5080":          dict(tbp=360, length=330, slots=3.0, fans=3),
    "NVIDIA GeForce RTX 5070 Ti":       dict(tbp=300, length=320, slots=3.0, fans=3),
    "NVIDIA GeForce RTX 5070":          dict(tbp=250, length=290, slots=2.5, fans=3),
    "NVIDIA GeForce RTX 5060 Ti":       dict(tbp=180, length=240, slots=2.0, fans=2),
    "NVIDIA GeForce RTX 5060":          dict(tbp=145, length=230, slots=2.0, fans=2),
    "NVIDIA GeForce RTX 5050":          dict(tbp=130, length=210, slots=2.0, fans=2),
    # ---------------- NVIDIA GeForce RTX 40
    "NVIDIA GeForce RTX 4090":          dict(tbp=450, length=340, slots=3.5, fans=3),
    "NVIDIA GeForce RTX 4080 Super":    dict(tbp=320, length=320, slots=3.0, fans=3),
    "NVIDIA GeForce RTX 4080":          dict(tbp=320, length=320, slots=3.0, fans=3),
    "NVIDIA GeForce RTX 4070 Ti Super": dict(tbp=285, length=305, slots=3.0, fans=3),
    "NVIDIA GeForce RTX 4070 Ti":       dict(tbp=285, length=300, slots=3.0, fans=3),
    "NVIDIA GeForce RTX 4070 Super":    dict(tbp=220, length=270, slots=2.5, fans=3),
    "NVIDIA GeForce RTX 4070":          dict(tbp=200, length=260, slots=2.5, fans=2),
    "NVIDIA GeForce RTX 4060 Ti":       dict(tbp=160, length=240, slots=2.0, fans=2),
    "NVIDIA GeForce RTX 4060":          dict(tbp=115, length=230, slots=2.0, fans=2),
    # ---------------- NVIDIA GeForce RTX 30
    "NVIDIA GeForce RTX 3090":          dict(tbp=350, length=315, slots=3.0, fans=3),
    "NVIDIA GeForce RTX 3080":          dict(tbp=320, length=300, slots=2.7, fans=3),
    "NVIDIA GeForce RTX 3070":          dict(tbp=220, length=270, slots=2.5, fans=3),
    "NVIDIA GeForce RTX 3060 Ti":       dict(tbp=200, length=240, slots=2.0, fans=2),
    "NVIDIA GeForce RTX 3060":          dict(tbp=170, length=240, slots=2.0, fans=2),
    # ---------------- AMD Radeon
    "AMD Radeon RX 9070 XT":            dict(tbp=304, length=320, slots=3.0, fans=3),
    "AMD Radeon RX 9070":               dict(tbp=220, length=290, slots=2.5, fans=3),
    "AMD Radeon RX 9060 XT 16GB":       dict(tbp=160, length=250, slots=2.0, fans=2),
    "AMD Radeon RX 7900 XTX":           dict(tbp=355, length=320, slots=3.0, fans=3),
    "AMD Radeon RX 7900 XT":            dict(tbp=315, length=300, slots=3.0, fans=3),
    "AMD Radeon RX 7800 XT":            dict(tbp=263, length=280, slots=2.5, fans=3),
    "AMD Radeon RX 7700 XT":            dict(tbp=245, length=270, slots=2.5, fans=2),
    "AMD Radeon RX 7600":               dict(tbp=165, length=210, slots=2.0, fans=2),
    # ---------------- Intel Arc
    "Intel Arc B580":                   dict(tbp=190, length=270, slots=2.0, fans=2),
    "Intel Arc B570":                   dict(tbp=150, length=250, slots=2.0, fans=2),
    "Intel Arc A770":                   dict(tbp=225, length=270, slots=2.0, fans=2),
}
GPU_GAMING_FRACTION = 0.88      # demanding games usually run close to the board power limit


def gpu_idle_w(tbp):
    return max(8.0, min(30.0, 0.06 * tbp))


CPUS = {
    # ---------------- AMD Ryzen
    "AMD Ryzen 5 5600X":       dict(tdp=65,  max_w=76,  gaming_w=50,  idle_w=20, r_int=0.42, tjmax=95),
    "AMD Ryzen 7 5800X3D":     dict(tdp=105, max_w=142, gaming_w=60,  idle_w=22, r_int=0.55, tjmax=90),
    "AMD Ryzen 5 7600":        dict(tdp=65,  max_w=88,  gaming_w=50,  idle_w=22, r_int=0.38, tjmax=95),
    "AMD Ryzen 5 7600X":       dict(tdp=105, max_w=142, gaming_w=60,  idle_w=22, r_int=0.38, tjmax=95),
    "AMD Ryzen 7 7700X":       dict(tdp=105, max_w=142, gaming_w=70,  idle_w=25, r_int=0.36, tjmax=95),
    "AMD Ryzen 7 7800X3D":     dict(tdp=120, max_w=162, gaming_w=60,  idle_w=25, r_int=0.50, tjmax=89),
    "AMD Ryzen 9 7900X":       dict(tdp=170, max_w=230, gaming_w=90,  idle_w=30, r_int=0.26, tjmax=95),
    "AMD Ryzen 9 7950X":       dict(tdp=170, max_w=230, gaming_w=110, idle_w=30, r_int=0.24, tjmax=95),
    "AMD Ryzen 5 9600X":       dict(tdp=65,  max_w=88,  gaming_w=50,  idle_w=22, r_int=0.38, tjmax=95),
    "AMD Ryzen 7 9700X":       dict(tdp=65,  max_w=88,  gaming_w=60,  idle_w=25, r_int=0.36, tjmax=95),
    "AMD Ryzen 7 9800X3D":     dict(tdp=120, max_w=162, gaming_w=75,  idle_w=25, r_int=0.32, tjmax=95),
    "AMD Ryzen 9 9900X":       dict(tdp=120, max_w=162, gaming_w=90,  idle_w=30, r_int=0.27, tjmax=95),
    "AMD Ryzen 9 9950X":       dict(tdp=170, max_w=230, gaming_w=110, idle_w=30, r_int=0.24, tjmax=95),
    # ---------------- Intel Core
    "Intel Core i5-12400F":    dict(tdp=65,  max_w=117, gaming_w=50,  idle_w=10, r_int=0.30, tjmax=100),
    "Intel Core i5-13400F":    dict(tdp=65,  max_w=148, gaming_w=60,  idle_w=10, r_int=0.30, tjmax=100),
    "Intel Core i5-14600K":    dict(tdp=125, max_w=181, gaming_w=95,  idle_w=12, r_int=0.24, tjmax=100),
    "Intel Core i7-14700K":    dict(tdp=125, max_w=253, gaming_w=130, idle_w=14, r_int=0.20, tjmax=100),
    "Intel Core i9-14900K":    dict(tdp=125, max_w=253, gaming_w=150, idle_w=15, r_int=0.19, tjmax=100),
    "Intel Core Ultra 5 245K": dict(tdp=125, max_w=159, gaming_w=70,  idle_w=12, r_int=0.25, tjmax=105),
    "Intel Core Ultra 7 265K": dict(tdp=125, max_w=250, gaming_w=90,  idle_w=14, r_int=0.21, tjmax=105),
    "Intel Core Ultra 9 285K": dict(tdp=125, max_w=250, gaming_w=100, idle_w=15, r_int=0.20, tjmax=105),
}
# maker and memory type: AM4 Ryzen 5000 = DDR4, AM5 Ryzen 7000 / 9000 = DDR5,
# Intel 12th-14th gen = DDR4 or DDR5 (depends on the board), Core Ultra 200S = DDR5
for _name, _c in CPUS.items():
    _c.setdefault('vendor', 'AMD' if _name.startswith('AMD') else 'Intel')
    if _name in ("AMD Ryzen 5 5600X", "AMD Ryzen 7 5800X3D"):
        _c.setdefault('memory', 'DDR4')
    elif _name.startswith('Intel Core i'):
        _c.setdefault('memory', 'DDR4/DDR5')
    else:
        _c.setdefault('memory', 'DDR5')
CPU_MEMORY = ('DDR4', 'DDR5', 'DDR4/DDR5')

# CPU coolers. r100 = cooler thermal resistance (K/W) at 100 % fan speed (rough, for the estimate)
COOLERS = {
    "Single tower 120 mm (Hyper 212 / AK400 class)":
        dict(kind='tower', stacks=1, fan_mm=120, stack_depth=52, stack_height=126, r100=0.16),
    "Dual tower 120 mm (Peerless Assassin 120 class)":
        dict(kind='tower', stacks=2, fan_mm=120, stack_depth=40, stack_height=126, r100=0.12),
    "Dual tower 140 mm (NH-D15 class)":
        dict(kind='tower', stacks=2, fan_mm=140, stack_depth=48, stack_height=146, r100=0.105),
    "AIO liquid 240 mm":  dict(kind='aio', fans=2, fan_mm=120, r100=0.100),
    "AIO liquid 280 mm":  dict(kind='aio', fans=2, fan_mm=140, r100=0.090),
    "AIO liquid 360 mm":  dict(kind='aio', fans=3, fan_mm=120, r100=0.080),
}
COOLER_FAN = {120: dict(rpm=1550, cfm=66.0, mmh2o=2.0), 140: dict(rpm=1500, cfm=82.0, mmh2o=2.0)}
AIO_FAN = {120: dict(rpm=2000, cfm=70.0, mmh2o=2.6), 140: dict(rpm=1700, cfm=85.0, mmh2o=2.3)}
GPU_FAN = dict(rpm=3000, cfm=38.0, mmh2o=2.9)          # one ~90 mm GPU fan at 100 %
PSU_FAN = dict(size=120, rpm=1800, cfm=50.0, mmh2o=2.0)

# Case fans: airflow / static pressure at 100 % speed (manufacturer figures for the named ones)
CASE_FANS = {
    "Generic 120 mm (1200 rpm)":   dict(size=120, rpm=1200, cfm=45.0, mmh2o=1.30),
    "Generic 120 mm (1500 rpm)":   dict(size=120, rpm=1500, cfm=55.0, mmh2o=1.60),
    "Arctic P12 PWM PST":          dict(size=120, rpm=1800, cfm=56.3, mmh2o=2.20),
    "Noctua NF-A12x25 PWM":        dict(size=120, rpm=2000, cfm=60.1, mmh2o=2.34),
    "Generic 140 mm (1200 rpm)":   dict(size=140, rpm=1200, cfm=65.0, mmh2o=1.30),
    "Arctic P14 PWM PST":          dict(size=140, rpm=1700, cfm=72.8, mmh2o=2.40),
    "Noctua NF-A14 PWM":           dict(size=140, rpm=1500, cfm=82.5, mmh2o=2.08),
}
DEFAULT_CASE_FAN = "Generic 120 mm (1500 rpm)"

# Fans that come with CPU coolers / AIOs (any fan in ALL_FANS can be used anywhere)
COOLER_FANS = {
    "Stock cooler fan 120 mm (1550 rpm)": dict(size=120, rpm=1550, cfm=66.0, mmh2o=2.00),
    "Stock cooler fan 140 mm (1500 rpm)": dict(size=140, rpm=1500, cfm=82.0, mmh2o=2.00),
    "Stock AIO fan 120 mm (2000 rpm)":    dict(size=120, rpm=2000, cfm=70.0, mmh2o=2.60),
    "Stock AIO fan 140 mm (1700 rpm)":    dict(size=140, rpm=1700, cfm=85.0, mmh2o=2.30),
}
ALL_FANS = dict(CASE_FANS, **COOLER_FANS)


def fans_of_size(size):
    return [k for k, v in ALL_FANS.items() if v['size'] == size]


def stock_cooler_fan(cooler):
    c = COOLERS[cooler]
    if c['kind'] == 'aio':
        return "Stock AIO fan %d mm (%d rpm)" % (c['fan_mm'], AIO_FAN[c['fan_mm']]['rpm'])
    return "Stock cooler fan %d mm (%d rpm)" % (c['fan_mm'], COOLER_FAN[c['fan_mm']]['rpm'])


def cooler_fan_count(cooler):
    c = COOLERS[cooler]
    return c['fans'] if c['kind'] == 'aio' else (1 if c['stacks'] == 1 else 2)

# 80 PLUS efficiency at 10 / 20 / 50 / 100 % load (230 V mains)
PSU_RATINGS = {
    "80 PLUS White":    (0.80, 0.82, 0.85, 0.82),
    "80 PLUS Bronze":   (0.82, 0.85, 0.88, 0.85),
    "80 PLUS Silver":   (0.84, 0.87, 0.90, 0.87),
    "80 PLUS Gold":     (0.86, 0.90, 0.92, 0.89),
    "80 PLUS Platinum": (0.88, 0.92, 0.94, 0.90),
    "80 PLUS Titanium": (0.90, 0.94, 0.96, 0.94),
}
PSU_SIZES = [450, 550, 650, 750, 850, 1000, 1200, 1300, 1600]

# ---------------------------------------------------------------- motherboards
# Form factors as mounted in a tower: w = depth from the rear I/O edge, h = height (mm).
# socket = CPU socket centre (mm from the rear edge, mm below the top edge),
# gpu_from_top = top of the graphics card below the board's top edge (first x16 slot; Mini-ITX and
#                Micro-ATX boards line their slot up with ATX slot 1, so the card sits at the same height),
# ram_x = first DIMM slot (mm from the rear edge), ram_y = DIMM ends (mm below the top edge)
BOARD_FORMS = {
    'E-ATX':     dict(w=277.0, h=305.0, socket=(128.0, 95.0), gpu_from_top=175.0, ram_x=196.0,
                      ram_y=(0.0, 133.0), ram_slots=4),
    'ATX':       dict(w=244.0, h=305.0, socket=(120.0, 95.0), gpu_from_top=175.0, ram_x=184.0,
                      ram_y=(0.0, 133.0), ram_slots=4),
    'Micro-ATX': dict(w=244.0, h=244.0, socket=(120.0, 95.0), gpu_from_top=175.0, ram_x=184.0,
                      ram_y=(0.0, 133.0), ram_slots=4),
    'Mini-ITX':  dict(w=170.0, h=170.0, socket=(100.0, 80.0), gpu_from_top=175.0, ram_x=146.0,
                      ram_y=(12.0, 145.0), ram_slots=2),
}
# chipset_w = chipset power at full load (B650 ~7 W, X670E / X870E two chips ~14 W, Intel 600-800 series ~6 W,
#             high-end boards add USB4 / 10G LAN / Wi-Fi controllers)
# vrm_eff   = CPU power stage efficiency: the loss heats the board around the socket
# ecc       = True when the board uses ECC error correction with Intel Core CPUs (W680 / W880).
#             Ryzen CPUs use ECC on most AM4 / AM5 boards.
MOTHERBOARDS = {
    "ATX mainstream (B650 / B760 / B860 class)": dict(form='ATX', chipset_w=7.0, vrm_eff=0.88, ecc=False),
    "ATX high-end (X870E / Z890 class)":         dict(form='ATX', chipset_w=12.0, vrm_eff=0.91, ecc=False),
    "ATX workstation (W680 / W880, ECC)":        dict(form='ATX', chipset_w=7.0, vrm_eff=0.90, ecc=True),
    "E-ATX high-end (X870E / Z890 class)":       dict(form='E-ATX', chipset_w=14.0, vrm_eff=0.92, ecc=False),
    "Micro-ATX (B650M / B760M class)":           dict(form='Micro-ATX', chipset_w=7.0, vrm_eff=0.87, ecc=False),
    "Mini-ITX (B650I / Z790I class)":            dict(form='Mini-ITX', chipset_w=7.0, vrm_eff=0.88, ecc=False),
}
DEFAULT_MOTHERBOARD = "ATX mainstream (B650 / B760 / B860 class)"
CHIPSET_LOAD = {'idle': 0.70, 'gaming': 0.85, 'max': 1.0}    # chipsets barely idle down
BOARD_MISC_W = 4.0             # audio, LAN, Wi-Fi, BIOS, fan / RGB controller

# ---------------------------------------------------------------- memory and storage
# per stick (W); ecc_extra = extra memory chips for ECC (DDR4 9 instead of 8, DDR5 10 instead of 8 per rank)
RAM_TYPES = {
    'DDR4': dict(idle=1.0, gaming=2.0, max=3.0, ecc_extra=0.125),
    'DDR5': dict(idle=1.5, gaming=3.0, max=4.5, ecc_extra=0.25),      # includes the on-stick PMIC
}
STORAGE_POWER = {
    'nvme': dict(idle=1.0, gaming=2.5, max=7.0),       # PCIe 4.0 M.2 SSD (on the motherboard)
    'hdd':  dict(idle=4.5, gaming=5.5, max=8.0),       # 3.5" 7200 rpm hard drive
}
MAX_NVME, MAX_HDD = 4, 3
USB_POWER = {'idle': 5.0, 'gaming': 8.0, 'max': 8.0}  # keyboard, mouse, headset ... (their heat stays outside)
AIO_PUMP_W = 3.5


def fan_power_w(spec, frac):
    """electrical power of a fan: ~1.5-2 W for a 120 mm fan at full speed, P ~ speed^3"""
    pmax = 0.5 + 2.5 * (spec['cfm'] / 2118.88) * (spec['mmh2o'] * 9.80665)
    return pmax * max(0.0, frac) ** 3


# kept for old code: the rest of the PC (board + RAM + SSD + fans + USB) for the default parts
OTHER_POWER = {'idle': 30.0, 'gaming': 50.0, 'max': 60.0}

# Case presets (interior sizes in mm)
CASES = {
    "Mid-tower 440 x 450 mm": dict(depth_mm=440, height_mm=450, width_mm=210, shroud=True,
                                   shroud_height_mm=90, shroud_length_mm=340),
    "Compact mid-tower 400 x 430 mm": dict(depth_mm=400, height_mm=430, width_mm=205, shroud=True,
                                           shroud_height_mm=88, shroud_length_mm=310),
    "Large mid-tower 470 x 480 mm": dict(depth_mm=470, height_mm=480, width_mm=230, shroud=True,
                                         shroud_height_mm=95, shroud_length_mm=360),
    "Full tower 520 x 540 mm": dict(depth_mm=520, height_mm=540, width_mm=240, shroud=True,
                                    shroud_height_mm=100, shroud_length_mm=400),
    "Open floor, no PSU shroud 440 x 450 mm": dict(depth_mm=440, height_mm=450, width_mm=210, shroud=False,
                                                   shroud_height_mm=90, shroud_length_mm=340),
}

FRONT_PANELS = {           # resistance of the front panel in front of the intake fans (clean filters)
    "open mesh": 60.0,
    "mesh + dust filter": 120.0,
    "solid front, side slits": 450.0,
}
TOP_PANELS = {
    "open mesh": 35.0,
    "mesh + dust filter": 70.0,
}
# the part of each resistance that is the dust filter (only that part clogs up)
FRONT_FILTER = {"open mesh": 0.0, "mesh + dust filter": 60.0, "solid front, side slits": 60.0}
TOP_FILTER = {"open mesh": 0.0, "mesh + dust filter": 35.0}
BOTTOM_FILTER = 40.0       # floor filter under bottom fans and the PSU
FILTER_CONDITIONS = {'clean': 1.0, 'dusty': 1.6, 'clogged': 3.0}


def panel_resistance(table, filters, panel, condition):
    """resistance (1/s) of a front / top panel with its dust filter in the given condition"""
    return table[panel] + (FILTER_CONDITIONS[condition] - 1.0) * filters.get(panel, 0.0)


# ---------------------------------------------------------------- blocks: parts you place yourself
# A block is anything you put in the case yourself (Blocks tab): something that stops the air, cables, a grille,
# or a part that makes heat.  w x h = its size seen through the glass (mm), air = how much air gets through it,
# watts = the heat it gives to the air (0 = none; it also counts in the power budget).
BLOCK_AIR = {
    'solid':  'solid: no air gets through',            # fills the case width: a panel, a divider, a closed cage
    'dense':  'dense: air squeezes round it',          # fills most of the width: a pump, a drive, a card
    'cables': 'cables: some air gets through',
    'mesh':   'mesh: most air gets through',
}
BLOCKS = {
    "Block (no air through)":      dict(w=80.0, h=80.0, air='solid', watts=0.0),
    "Divider panel":               dict(w=4.0, h=150.0, air='solid', watts=0.0),
    "Dense part (air goes round)": dict(w=80.0, h=60.0, air='dense', watts=0.0),
    "Cable bundle":                dict(w=30.0, h=150.0, air='cables', watts=0.0),
    "Mesh / grille":               dict(w=6.0, h=150.0, air='mesh', watts=0.0),
    "Pump + reservoir":            dict(w=60.0, h=140.0, air='dense', watts=6.0),
    "Capture / sound card":        dict(w=170.0, h=20.0, air='dense', watts=12.0),
    '2.5" SSD':                    dict(w=100.0, h=10.0, air='dense', watts=3.0),
    "Heat source":                 dict(w=60.0, h=40.0, air='cables', watts=20.0),
}
DEFAULT_BLOCK = "Block (no air through)"
BLOCK_MIN_MM = 4.0             # thinnest block (a divider panel)
BLOCK_MAX_MM = 700.0
MAX_BLOCK_WATTS = 600.0
