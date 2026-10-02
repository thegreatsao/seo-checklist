"""The registry's ids, read across every revision of the registry there has been.

`openspec/specs/registry/` REG-4: an id names one question for the life of the registry.
Uniqueness inside one build was always held. What nothing held was the half the
requirement exists for — *retired in one release, issued to another question in a later
one* — because that is a property of a history and every reader looked at one tree.

So this walks the history: every commit that touched `checklist.json`, oldest first, and
then the file on disk, which is the release being made. Measured before it was written
(1 October 2026, `local/gov3/measure_id_history.py`, outside git): 70 revisions, 217 ids
ever seen, none retired, none returned, no reference moved, no prefix in two categories.
The history is clean, so this is a reader for the next edit and not a repair.

A retirement is legal and has to be said: `build_checklist.RETIRED` names the id and why,
and from then on the id may not ship. An id that leaves without being named there, one
named there that still ships, and one that comes back are each a violation.

The git plumbing is `tools/audit_declaration_revisions.py`'s — the same three rules about
spawning, and the same refusal: a clone too shallow to hold the first commit finds no
revisions, agrees with anything, and must fail by name rather than pass.
"""
from __future__ import annotations

import collections
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "seo-checklist", "tools"))

import audit_declaration_revisions as revisions  # noqa: E402

Unreadable = revisions.Unreadable

# The commit that created the registry. Every clone that can run this walk holds it.
FIRST = "b3e251f62e6241760a9f008c3ce656c85f7fe530"
REGISTRY = "skills/seo-checklist/resources/config/checklist.json"
ON_DISK = "the working tree"

# One row of a state: the id, the borrowed title's number (None for an added item), and
# the category. A list and not a dict, so that two rows sharing an id are still two rows.
Row = tuple


def rows(document: dict) -> list[Row]:
    return [(item["id"], item.get("plerdy_ref"), item["category"])
            for item in document["items"]]


def first_is_reachable() -> None:
    revisions.git_directory(ROOT)
    try:
        kind = revisions.git("cat-file", "-t", FIRST).strip()
    except Unreadable as exc:
        raise Unreadable(
            f"the registry's first commit {FIRST[:8]} is not in this clone ({exc}). A "
            f"shallow checkout sees one revision, in which no id can have been re-used "
            f"— give the job `fetch-depth: 0`") from exc
    if kind != "commit":
        raise Unreadable(f"{FIRST[:8]} is a {kind}, not a commit")


def states() -> list[tuple[str, list[Row]]]:
    """(label, rows) for every revision of the registry, then the file on disk."""
    first_is_reachable()
    listed = revisions.git("log", "--format=%H", "--reverse", "--", REGISTRY).split()
    if not listed or listed[0] != FIRST:
        raise Unreadable(f"the registry's history does not start at {FIRST[:8]}: "
                         f"{listed[:1] or 'no revisions'}")
    series = []
    for sha in listed:
        series.append((sha[:8], rows(json.loads(revisions.git("show", f"{sha}:{REGISTRY}")))))
    with open(os.path.join(ROOT, *REGISTRY.split("/")), encoding="utf-8") as stream:
        series.append((ON_DISK, rows(json.load(stream))))
    return series


def violations(series: list[tuple[str, list[Row]]], retired: dict[str, str]) -> list[str]:
    """Every way the series breaks REG-4, in the order it happens."""
    out = []
    reference = {}                    # id -> the plerdy_ref it first carried
    left = {}                         # id -> label of the state it was first absent from
    ever = set()
    previous: set[str] = set()
    for label, state in series:
        counted = collections.Counter(item_id for item_id, _, _ in state)
        for item_id in sorted(i for i, n in counted.items() if n > 1):
            out.append(f"{label}: {item_id} is carried by {counted[item_id]} items")
        prefixes = collections.defaultdict(set)
        for item_id, ref, category in state:
            prefixes[item_id.split("-")[0]].add(category)
            if item_id in left:
                out.append(f"{label}: {item_id} left the registry at {left[item_id]} and "
                           f"is issued again — an id is never re-used")
            if item_id in reference and reference[item_id] != ref:
                out.append(f"{label}: {item_id} named source title {reference[item_id]} "
                           f"and now names {ref} — the id was given to another question")
            reference.setdefault(item_id, ref)
        for prefix in sorted(p for p, categories in prefixes.items() if len(categories) > 1):
            out.append(f"{label}: prefix {prefix} sits in {sorted(prefixes[prefix])} — a "
                       f"prefix belongs to one category")
        now = set(counted)
        for item_id in sorted(previous - now):
            left.setdefault(item_id, label)
            if item_id not in retired:
                out.append(f"{label}: {item_id} left the registry and RETIRED does not "
                           f"say why")
        ever |= now
        previous = now
    for item_id in sorted(retired):
        if item_id not in ever:
            out.append(f"RETIRED names {item_id}, which the registry never carried")
        elif item_id in previous:
            out.append(f"RETIRED names {item_id}, which still ships")
        if not str(retired[item_id]).strip():
            out.append(f"RETIRED gives no reason for {item_id}")
    return out
