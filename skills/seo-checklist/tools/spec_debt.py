#!/usr/bin/env python3
"""What the twelve normative documents in `specs/` do and do not hold.

Each document ends with a census of its own requirements — enforced, partial, none,
opposed — and `tests/test_specs.py` makes sure each of those censuses is honest about
itself. Nothing summed them, so the suite's total debt was twelve numbers in twelve
files and, as the coverage map put it, a feeling rather than a number.

This is the sum. It reads the documents, not a ledger beside them: there is nothing
here a hand can set while the documents move.

    python tools/spec_debt.py                  # the roll-up
    python tools/spec_debt.py --unread         # every requirement no reader holds
    python tools/spec_debt.py --out FILE       # write the JSON record
    python tools/spec_debt.py --check FILE     # exit 1 if the record is stale

`--check` exists for the same reason the verdict census has one: a total that moves
without anybody deciding it should is the thing this suite keeps finding. It compares
the whole record, so a requirement changing class is a difference somebody has to
re-record deliberately.

What this tool does **not** do is judge whether a classification is right. That needs a
mutation probe per requirement, which is what the documents' own Appendix B sections
record having done or not done. A wrong `enforced` counts as enforced here, and the
only defence against that is the one `test_specs.py` holds: a document may not tabulate
a claim more kindly than its own evidence line.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

# tools/ -> skills/seo-checklist/ -> skills/ -> repo root
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SPECS = os.path.join(ROOT, "specs")

CLASSES = ("enforced", "partial", "none", "opposed")
REQUIREMENT = re.compile(r"^### ([A-Z]{2,4}-\d+) — (.+)$")
ROW = re.compile(r"^\| \*\*(enforced|partial|none|opposed)\*\* \| (.+?) \|$")
ID = re.compile(r"\b([A-Z]{2,4}-\d+)\b")


def documents() -> list[tuple[str, str]]:
    """Discovered, never listed — a thirteenth document must not need an edit here."""
    found = []
    for name in sorted(os.listdir(SPECS)):
        path = os.path.join(SPECS, name, "spec.md")
        if os.path.isfile(path):
            found.append((name, path))
    return found


def read(name: str, path: str) -> dict:
    with open(path, encoding="utf-8") as stream:
        lines = stream.read().splitlines()

    titles = {}
    for line in lines:
        found = REQUIREMENT.match(line)
        if found:
            titles[found.group(1)] = found.group(2)

    table = {}
    for line in lines:
        row = ROW.match(line)
        if row:
            table[row.group(1)] = ID.findall(row.group(2))

    where = {item: label for label, ids in table.items() for item in ids}
    return {
        "requirements": len(titles),
        "counts": {label: len(table.get(label, [])) for label in CLASSES},
        "unread": sorted(i for i, label in where.items() if label == "none"),
        "opposed": sorted(i for i, label in where.items() if label == "opposed"),
        "titles": titles,
    }


def record() -> dict:
    docs = {name: read(name, path) for name, path in documents()}
    totals = {label: sum(d["counts"][label] for d in docs.values())
              for label in CLASSES}
    totals["requirements"] = sum(d["requirements"] for d in docs.values())
    return {
        "documents": {name: {k: v for k, v in d.items() if k != "titles"}
                      for name, d in docs.items()},
        "totals": totals,
    }


def report(data: dict, with_titles: bool = False) -> list[str]:
    docs, totals = data["documents"], data["totals"]
    width = max(len(n) for n in docs)
    out = ["%-*s  %5s %8s %7s %5s %8s" % (width, "document", "reqs", "enforced",
                                          "partial", "none", "opposed")]
    for name in sorted(docs):
        d = docs[name]
        c = d["counts"]
        out.append("%-*s  %5d %8d %7d %5d %8d"
                   % (width, name, d["requirements"], c["enforced"], c["partial"],
                      c["none"], c["opposed"]))
    out.append("%-*s  %5d %8d %7d %5d %8d"
               % (width, "TOTAL", totals["requirements"], totals["enforced"],
                  totals["partial"], totals["none"], totals["opposed"]))
    held = totals["enforced"]
    out.append("")
    out.append("%d of %d requirements are held by something that fails when they are "
               "violated." % (held, totals["requirements"]))
    out.append("%d are unread and %d are opposed — a reader that fires when the "
               "requirement is *met*." % (totals["none"], totals["opposed"]))
    out.append("")
    out.append("A count is not a verdict on the tree: `partial` is the largest column "
               "and says nothing about")
    out.append("how much of each requirement is held. Read the document.")
    return out


def unread_lines(data: dict) -> list[str]:
    docs = {name: read(name, path) for name, path in documents()}
    out = []
    for name in sorted(docs):
        d = docs[name]
        rows = [(i, d["titles"].get(i, "")) for i in d["unread"] + d["opposed"]]
        if not rows:
            continue
        out.append("== %s" % name)
        for item, title in sorted(rows):
            mark = "opposed" if item in d["opposed"] else "unread "
            out.append("  %s  %-8s %s" % (mark, item, title))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", help="write the JSON record here")
    ap.add_argument("--check", help="compare against this record and exit 1 on drift")
    ap.add_argument("--unread", action="store_true",
                    help="list every unread and opposed requirement by name")
    args = ap.parse_args()

    data = record()
    print("\n".join(report(data)))
    if args.unread:
        print()
        print("\n".join(unread_lines(data)))

    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(data, stream, indent=2, ensure_ascii=False, sort_keys=True)
            stream.write("\n")
        print("\nwrote %s" % args.out)
    if args.check:
        with open(args.check, encoding="utf-8") as stream:
            stored = json.load(stream)
        if stored != json.loads(json.dumps(data, sort_keys=True)):
            print("\n%s is out of step with the documents — re-record it with --out"
                  % args.check, file=sys.stderr)
            return 1
        print("\n%s is in step" % args.check)
    return 0


if __name__ == "__main__":
    sys.exit(main())
