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
SCRIPTS_DIR = os.path.join(SKILL_DIR, "scripts")
RUNNER = os.path.join(SCRIPTS_DIR, "checklist_runner.py")

sys.path.insert(0, os.path.join(SKILL_DIR, "scripts"))
from checklist_runner import ERROR_KINDS  # noqa: E402

FIELD = "error_kind"

from scope_line import print_scope  # noqa: E402

# What a passing run establishes, and what it does not (openspec/specs/governance/ GOV-6).
ESTABLISHES = (
    "every error_kind the runner and the evidence scripts assign is named in the "
    "runner's vocabulary, and every kind the vocabulary names is assigned somewhere"
)
DOES_NOT_ESTABLISH = (
    "that any failure is given the right kind, or anything about the fetch layer's "
    "own vocabulary, whose kinds stay on per-URL rows and do not reach the runner"
)



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


def sources() -> list[str]:
    """Every file that can put an `error_kind` in front of the runner.

    The runner is one of them and was the only one read until 0.102.0. That was the
    census's own blind spot, and it cost the same kind of defect it exists to catch:
    `_timed()` reads `out.get("error_kind", "crash")` from **the script's** output, so
    an evidence script is a source of the vocabulary — and eleven of them emitted a
    top-level `error` with no kind, which the runner then reported as *"script
    failed"*. A site that was down, and a Google quota, both read as the plugin's
    defect. The census stayed green throughout, because it was reading one file and
    the kinds were arriving from another forty.

    Derived by walking `scripts/`, not listed: a list here would have the same shape
    as the defect.
    """
    found = [RUNNER]
    for name in sorted(os.listdir(SCRIPTS_DIR)):
        if name.endswith(".py") and name != "checklist_runner.py":
            found.append(os.path.join(SCRIPTS_DIR, name))
    return found


def fetch_vocabulary() -> set[str]:
    """What `seo_common.fetch_error_kind` can return, read out of its own source.

    There are **two** error-kind vocabularies in this tree and they share one word.
    The runner's seven say what the operator should do — open the script, wait for
    the site, wait out a quota. The fetch layer's seven (`unresolved`, `robots`,
    `blocked`, `timeout`, `tls`, `refused`, `other`) classify one failed HTTP call,
    and they live on per-URL rows inside a result rather than at its top level, which
    is why the runner never sees them today.

    Naming the second vocabulary is what keeps this census honest in both directions.
    Reading only the runner's leaves a blind spot — that is the 0.102.0 defect.
    Reading every assignment against the runner's list alone would redden on
    `blocked` and `other`, which are correct where they are, and a gate that cries
    without cause is a gate somebody switches off.

    The seam itself is unguarded and is recorded as such: nothing stops a fetch-layer
    kind being promoted to a top-level `error_kind`, where six of its seven values
    would land on no label at all.
    """
    with open(os.path.join(SCRIPTS_DIR, "seo_common.py"), encoding="utf-8") as stream:
        tree = ast.parse(stream.read())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "fetch_error_kind":
            return {n.value.value for n in ast.walk(node)
                    if isinstance(n, ast.Return) and isinstance(n.value, ast.Constant)
                    and isinstance(n.value.value, str)}
    raise SystemExit("seo_common.fetch_error_kind is gone; this census assumed it")


def assigned_everywhere() -> dict[str, list[str]]:
    """Each assigned kind, and the basenames that assign it."""
    out: dict[str, list[str]] = {}
    for path in sources():
        for kind in assigned_kinds(path):
            out.setdefault(kind, []).append(os.path.basename(path))
    return out


def disagreements() -> list[str]:
    """What the sources and the vocabulary say about each other."""
    assigned = assigned_everywhere()
    declared = set(ERROR_KINDS)
    known = declared | fetch_vocabulary()
    out = []
    for kind in sorted(set(assigned) - known):
        where = ", ".join(assigned[kind])
        out.append(f"{kind!r} is assigned in {where} and belongs to neither "
                   f"vocabulary — an unlabelled kind is also an uncounted one")
    for kind in sorted(declared - set(assigned)):
        out.append(f"{kind!r} is in ERROR_KINDS and is assigned nowhere — a dead label "
                   f"reads as coverage")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="exit 1 if the source and the vocabulary disagree")
    args = parser.parse_args()

    assigned = assigned_everywhere()
    print(f"{len(sources())} source file(s) read: the runner and every evidence script")
    print()
    print(f"named by ERROR_KINDS:     {' '.join(sorted(ERROR_KINDS))}")
    print(f"named by the fetch layer: {' '.join(sorted(fetch_vocabulary()))}")
    print()
    for kind in sorted(assigned):
        where = ", ".join(sorted(assigned[kind]))
        print(f"  {kind:<12} assigned in {where}")
    print()

    problems = disagreements()
    for line in problems:
        print(f"  {line}", file=sys.stderr)
    if args.check and problems:
        return 1
    if not problems:
        print("\nthe vocabulary and the source agree in both directions")
    print_scope(ESTABLISHES, DOES_NOT_ESTABLISH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
