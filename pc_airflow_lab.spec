# -*- mode: python ; coding: utf-8 -*-
# PyInstaller recipe for PC_Airflow_Lab.exe - Powered by ElAmouri (https://github.com/Elamouri)
#
#   py -3 -m pip install -r requirements.txt pyinstaller
#   py -3 -m PyInstaller --noconfirm --clean pc_airflow_lab.spec        ->  dist\PC_Airflow_Lab.exe
#
# (tools\build_exe.bat does exactly this.)  One file, no console window, with its own icon and
# version details. The same .exe also runs the command line:  PC_Airflow_Lab.exe --cli --selftest
import os
import sys

from PyInstaller.utils.hooks import collect_data_files

sys.path.insert(0, SPECPATH)
from pcflow import branding                       # noqa: E402  (name, version and credit in one place)

ver = tuple(([int(x) for x in branding.VERSION.split('.')] + [0, 0, 0, 0])[:4])      # (1, 3, 0, 0)
VERSION_INFO = '''# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(filevers=%(ver)r, prodvers=%(ver)r, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', %(author)r),
      StringStruct('FileDescription', %(desc)r),
      StringStruct('FileVersion', %(version)r),
      StringStruct('InternalName', 'PC_Airflow_Lab'),
      StringStruct('LegalCopyright', %(copyright)r),
      StringStruct('OriginalFilename', 'PC_Airflow_Lab.exe'),
      StringStruct('ProductName', %(name)r),
      StringStruct('ProductVersion', %(version)r),
      StringStruct('Comments', %(comments)r)])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
''' % dict(ver=ver, author=branding.AUTHOR, version=branding.VERSION, name=branding.APP_NAME,
           desc='%s - %s' % (branding.APP_NAME, branding.POWERED_BY),
           copyright='(c) 2026 %s - %s' % (branding.AUTHOR, branding.GITHUB_TEXT),
           comments=branding.CREDIT_ASCII)
os.makedirs(workpath, exist_ok=True)
version_file = os.path.join(workpath, 'version_info.txt')
with open(version_file, 'w', encoding='utf-8') as fh:
    fh.write(VERSION_INFO)

datas = [(os.path.join('configs', '*.json'), 'configs'),
         (os.path.join('assets', 'app.ico'), 'assets'),
         (os.path.join('assets', 'app.png'), 'assets')]
datas += collect_data_files('imageio_ffmpeg', subdir='binaries')        # ffmpeg, for the videos

# Parts of the libraries the program never uses (checked: the window, the simulation and the picture / video
# export load none of them) - leaving them out makes the .exe smaller and start faster.
NOT_NEEDED = (
    ['pytest', '_pytest', 'PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'wx', 'gi', 'IPython', 'jupyter', 'notebook',
     'sphinx', 'pip', 'setuptools', 'pkg_resources', 'lib2to3', 'pydoc_data', '_ssl', '_hashlib']
    + ['scipy.' + m for m in ('optimize', 'special', 'fft', 'fftpack', 'spatial', 'interpolate', 'stats',
                              'integrate', 'signal', 'ndimage', 'io', 'cluster', 'odr', 'datasets',
                              'differentiate', 'misc', 'constants')]
    + ['PIL.' + m for m in ('_avif', 'AvifImagePlugin', '_webp', 'WebPImagePlugin', 'ImageQt', '_imagingcms',
                            'ImageCms', '_imagingft', 'ImageFont')]
)

a = Analysis(
    ['pc_airflow_lab.py'],
    pathex=[SPECPATH],
    binaries=[],
    datas=datas,
    hiddenimports=['matplotlib.backends.backend_tkagg', 'matplotlib.backends.backend_agg', 'PIL.PngImagePlugin',
                   'PIL.GifImagePlugin'],
    hookspath=[],
    hooksconfig={'matplotlib': {'backends': ['TkAgg', 'Agg']}},
    runtime_hooks=[],
    excludes=NOT_NEEDED,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='PC_Airflow_Lab',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    icon=os.path.join(SPECPATH, 'assets', 'app.ico'),
    version=version_file,
)
