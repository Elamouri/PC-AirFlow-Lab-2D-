#!/usr/bin/env python3
"""PC Airflow Lab - Powered by ElAmouri (https://github.com/Elamouri, WhatsApp +962 79 674 2759)

One start file for the window and the command line. It is also what PC_Airflow_Lab.exe runs:

    PC_Airflow_Lab.exe                                   the window
    PC_Airflow_Lab.exe my_setup.json                     the window with that setup
    PC_Airflow_Lab.exe --cli --selftest                  command line (same options as run_cli.py)
    PC_Airflow_Lab.exe --cli my_setup.json --png result.png --quality fast
    PC_Airflow_Lab.exe --version
"""
import os
import sys


def _text_output():
    """The .exe is a window program, so it may start without text output of its own.

    Use the pipe / file it was given (the app's own exports read it line by line), otherwise the
    command prompt it was started from, otherwise nowhere - printing must never crash it."""
    frozen = getattr(sys, 'frozen', False)
    for stream in (sys.stdout, sys.stderr):
        if stream is None or not hasattr(stream, 'reconfigure'):
            continue
        try:
            if frozen and not stream.isatty():
                stream.reconfigure(encoding='utf-8', errors='replace')
            stream.reconfigure(line_buffering=True)     # progress lines arrive while the export runs
        except (OSError, ValueError):
            pass
    if sys.stdout is not None and sys.stderr is not None:
        return
    out = None
    if sys.platform.startswith('win'):
        try:
            import ctypes
            if ctypes.windll.kernel32.AttachConsole(-1):      # the command prompt that started the .exe
                out = open('CONOUT$', 'w', encoding='utf-8', errors='replace')
        except (AttributeError, OSError):
            out = None
    if out is None:
        out = open(os.devnull, 'w', encoding='utf-8')
    if sys.stdout is None:
        sys.stdout = out
    if sys.stderr is None:
        sys.stderr = out


def wants_cli(argv):
    """--cli, or any option (--selftest, --version, --help ...): the window only takes a setup file"""
    return bool(argv) and argv[0].startswith('-')


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if wants_cli(argv):
        if argv[0] == '--cli':
            argv = argv[1:]
        _text_output()
        from pcflow.cli import main as cli_main
        try:
            return cli_main(argv, prog=os.path.basename(sys.argv[0] or 'pc_airflow_lab') + ' --cli')
        except Exception:                      # noqa: BLE001 - in the .exe an uncaught error would open a
            import traceback                    # dialog that blocks the export job until someone closes it
            traceback.print_exc()
            return 1
    from pcflow.gui import main as gui_main
    gui_main(argv)
    return 0


if __name__ == '__main__':
    sys.exit(main())
