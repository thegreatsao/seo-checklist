#!/usr/bin/env python3
"""Every `error_kind` the runner assigns, read out of its source rather than listed.

`openspec/specs/run-lifecycle/` RUN-7. A run that cannot answer an item records *why*,
and the kinds are counted apart because they send the reader to different places: a
`timeout` is retryable, a `crash` is the plugin's problem, and `unread` is the site's.

The census this replaces derived the vocabulary with

    re.findall(r'"error_kind":\\s*"(\\w+)"', src)

which finds a dict literal and not a keyword argument. `grade()` assigns the sixth kind
as `row.update(status=NO_DATA, error_kind="unread", ...)`, so it was invisible to the
check whose whole job was noticing an unlabelled kind — and, being unlabelled, it was
also uncounted, and a run against a site that stopped answering printed no failure line
at all. A census finds only the spellings it was given; an AST reads the assignment.

Both directions matter and the regex could do neither honestly:

* a kind the source assigns and the vocabulary does not name is an unlabelled failure,
  which is the defect above;
* a kind the vocabulary names and the source never assigns is a dead label, which reads
  as coverage and is not.

    python tools/audit_error_kinds.py           # the census
    python tools/audit_error_kinds.py --check   # exit 1 if the two disagree
"""
from __future__ import annotations

import argparse
import ast
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
RUNNER = os.path.join(SKILL_DIR, "scripts", "checklist_runner.py")

sys.path.insert(0, os.path.join(SKILL_DIR, "scripts"))
from checklist_runner import ERROR_KINDS  # noqa: E402

FIELD = "error_kind"


def assigned_kinds(path: str = RUNNER) -> set[str]:
    """Every literal string the source assigns to `error_kind`, however spelled.

    Three spellings reach the field and all three are in use: a dict literal
    (`{"error_kind": "missing"}`), a keyword argument (`row.update(error_kind=...)`),
    and a subscript assignment (`out["error_kind"] = ...`). The last is not used today
    and is read anyway, because the point of deriving the set is that it keeps working
    when somebody writes it the fourth way.
    """
    with open(path, encoding="utf-8") as stream:
        tree = ast.parse(stream.read())

    found: set[str] = set()

    def literal(node) -> None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            found.add(node.value)

    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values, strict=True):
                if isinstance(key, ast.Constant) and key.value == FIELD:
                    literal(value)
        elif isinstance(node, ast.Call):
            for keyword in node.keywords:
                if keyword.arg == FIELD:
                    literal(keyword.value)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if (isinstance(target, ast.Subscript)
                        and isinstance(target.slice, ast.Constant)
                        and target.slice.value == FIELD):
                    literal(node.value)
    return found


def disagreements() -> list[str]:
    """What the source and the vocabulary say about each other."""
    assigned, declared = assigned_kinds(), set(ERROR_KINDS)
    out = []
    for kind in sorted(assigned - declared):
        out.append(f"{kind!r} is assigned in checklist_runner.py and is not in "
                   f"ERROR_KINDS — an unlabelled kind is also an uncounted one")
    for kind in sorted(declared - assigned):
        out.append(f"{kind!r} is in ERROR_KINDS and is assigned nowhere — a dead label "
                   f"reads as coverage")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="exit 1 if the source and the vocabulary disagree")
    args = parser.parse_args()

    assigned = assigned_kinds()
    print(f"assigned in checklist_runner.py: {' '.join(sorted(assigned))}")
    print(f"named by ERROR_KINDS:            {' '.join(sorted(ERROR_KINDS))}")

    problems = disagreements()
    for line in problems:
        print(f"  {line}", file=sys.stderr)
    if args.check and problems:
        return 1
    if not problems:
        print("\nthe vocabulary and the source agree in both directions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
