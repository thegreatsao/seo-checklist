"""`utf8_streams` for the tools, which is the scripts' own and not a second copy.

A tool run by path has `tools/` on `sys.path` and not `scripts/`, and half of them
never put it there. The function is loaded from its file, so that a tool which
imports this has not thereby changed where its other imports are looked for.
See `scripts/lib/utf8_streams.py` for what it is for and what was measured.
"""
from __future__ import annotations

import importlib.util
import os

_HOME = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "scripts", "lib", "utf8_streams.py")
_spec = importlib.util.spec_from_file_location("_scripts_lib_utf8_streams", _HOME)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
utf8_streams = _module.utf8_streams
