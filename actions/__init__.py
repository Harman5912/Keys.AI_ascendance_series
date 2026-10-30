"""actions — desktop automation tool modules for Keys.ai.
Also forces UTF-8 console output so emoji/Unicode log lines never crash on
legacy Windows (cp1252) consoles — even when action modules are imported
directly (e.g. by the offscreen test suites).
"""

import sys as _sys

for _stream in (_sys.stdout, _sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
