"""Read JSON files that may come from other people without letting them crash or hang the app.

Only normal files (no devices, pipes or sockets), a size cap, UTF-8 text, and hostile structures
(deep nesting, huge numbers) turned into a plain ValueError with a readable message.
"""
import json
import os
import stat


def read_json(path: str, max_bytes: int):
    """parsed JSON from `path`; raises OSError (cannot open) or ValueError (not a usable file)"""
    st = os.stat(path)
    if not stat.S_ISREG(st.st_mode):
        raise ValueError('%s is not a normal file' % path)
    if st.st_size > max_bytes:
        raise ValueError('%s is too big (%d bytes, at most %d)' % (path, st.st_size, max_bytes))
    with open(path, 'rb') as f:
        raw = f.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError('%s is too big (more than %d bytes)' % (path, max_bytes))
    try:
        text = raw.decode('utf-8-sig')
    except UnicodeDecodeError as e:
        raise ValueError('%s is not UTF-8 text (%s)' % (path, e)) from e
    try:
        return json.loads(text)
    except RecursionError as e:
        raise ValueError('%s is nested too deeply to be a real file' % path) from e
    except ValueError as e:
        raise ValueError('%s is not valid JSON: %s' % (path, e)) from e
