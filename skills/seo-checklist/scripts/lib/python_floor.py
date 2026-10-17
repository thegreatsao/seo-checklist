"""The oldest Python this plugin runs on, and one line for anything older.

The plugin is installed by copying, so `requires-python` stops nobody: every program
starts on whatever `python3` is. Before 0.166.0 that meant 3.9 died at import with a
`TypeError` about `|` that says nothing about versions, and the floor was 3.10. On 15
October 2026 Anton decided that a Python needing patches to be supported raises the
floor instead, and it is 3.11: what 3.10 needed was taken out, and 3.10 would now run
and read some inputs differently — a server log's ISO times ending in `Z` among them,
which `datetime.fromisoformat` refuses before 3.11.

So every program imports this first — `from lib import python_floor` in `scripts/`,
`import python_floor` in `tools/`, which loads this same file — and an older
interpreter is told so in one line, with a non-zero exit, before the program has
imported, read, written or asked for anything else. `REQUIRES` is `requires-python`
in `pyproject.toml` without its `>=`, and `tests/test_python_floor.py` holds the two
equal. Written in syntax every Python 3 parses, since the interpreter it is for is
the one too old for everything else here.
"""
import sys

REQUIRES = "3.11"

if tuple(sys.version_info[:2]) < tuple(int(part) for part in REQUIRES.split(".")):
    raise SystemExit("seo-checklist needs Python %s or newer; this is Python %s."
                     % (REQUIRES, ".".join(str(part) for part in sys.version_info[:3])))
