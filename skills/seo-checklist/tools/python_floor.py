"""`python_floor` for the tools, which is the scripts' own and not a second copy.

A tool run by path has `tools/` on `sys.path` and not `scripts/`. The check is loaded
from its file, as `utf8_streams` is, so a tool that imports this has not thereby
changed where its other imports are looked for. See `scripts/lib/python_floor.py`.
"""
import importlib.util
import os

_HOME = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "scripts", "lib", "python_floor.py")
_spec = importlib.util.spec_from_file_location("_scripts_lib_python_floor", _HOME)
_spec.loader.exec_module(importlib.util.module_from_spec(_spec))
