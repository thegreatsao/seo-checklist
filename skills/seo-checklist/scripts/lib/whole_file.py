"""A file that is replaced whole or left as it was.

`open(path, "w")` empties the file before the first byte of the new contents is
written. A run's results file is the only copy of what an audit found, and three
merges and the runner itself wrote it that way: a process killed between the
truncation and the last byte left half a JSON document where the results had been.

The new contents go to a file beside the target and take its name in one step. A
reader sees the old file or the new one, never a part of either, and a writer that
dies leaves the old one.
"""
from __future__ import annotations

import json
import os
import time

# How long a replacement waits for a file somebody else has open, and how often it
# asks again. Only Windows refuses to replace an open file: a viewer that reads the
# results while they are being rewritten holds them for milliseconds, and the same
# ten seconds the pacing lock waits (`safe_http.WINDOWS_LOCK_PATIENCE`) is far past
# any read. Neither number decides a verdict.
REPLACE_PATIENCE = 10.0
REPLACE_POLL = 0.05
# Where a refusal can mean "somebody has it open" and asking again can help.
# Elsewhere a refusal is about permissions and asking again changes nothing.
ASKS_AGAIN = os.name == "nt"


def _replace(tmp: str, path: str) -> None:
    deadline = time.monotonic() + REPLACE_PATIENCE
    while True:
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if not ASKS_AGAIN or time.monotonic() >= deadline:
                raise
            time.sleep(REPLACE_POLL)


def write_text_whole(path: str, text: str, encoding: str = "utf-8") -> None:
    """Put `text` at `path` so that `path` never holds a part of it.

    When the target cannot be replaced the error says where the complete new
    contents are, and the target is as it was. A failure before the contents were
    complete removes them.
    """
    tmp = f"{path}.{os.getpid()}.tmp"
    try:
        with open(tmp, "w", encoding=encoding) as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    try:
        _replace(tmp, path)
    except OSError as exc:
        raise OSError(
            f"{path} could not be replaced ({exc}) and is as it was; the complete "
            f"new contents are in {tmp}") from exc


def write_json_whole(path: str, payload, indent: int | None = 2) -> None:
    """`json.dump` to `path`, whole or not at all.

    Serialised before anything is opened: a payload that will not serialise used to
    be discovered halfway through the file it had already emptied.
    """
    write_text_whole(path, json.dumps(payload, ensure_ascii=False, indent=indent))
