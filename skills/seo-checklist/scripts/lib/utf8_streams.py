"""What a program writes to a pipe does not depend on the machine it is run on.

Python encodes `print` with the stream's encoding, and for a pipe or a file on Windows
that is the machine's ANSI codepage. A program started by the runner is told to write
UTF-8 (`run_script` sets `PYTHONIOENCODING`); one started by hand is told nothing. The
eight scripts that print raw JSON have reconfigured their own streams since the Greek ρ
of KNOWN-ISSUES 4. The rest did not, and their `--help` alone was enough: measured on
8 October 2026, with the output a pipe and each of the fourteen codepages Windows uses
named in turn, thirteen of the eighty-one programs died of `UnicodeEncodeError` under
cp932 and cp949 — Japanese and Korean Windows — on the em dash in their own
description, and two of them under cp874 as well. None died under cp1252, which is
the codepage of the machine this is developed on and of CI's Windows runner, so
nothing here had seen it.

A program calls `utf8_streams()` as the first thing it does when it is started, and
not when it is imported: a module that reconfigures the streams of whatever imported
it has decided something for a process that is not its own.
"""
from __future__ import annotations

import sys


def utf8_streams() -> None:
    """Make stdout and stderr write UTF-8, whatever the machine's codepage is."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):  # absent, already wrapped, or not a TextIO
            pass
