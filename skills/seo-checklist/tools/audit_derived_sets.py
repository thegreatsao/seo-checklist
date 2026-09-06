#!/usr/bin/env python3
"""Every hand-written set that decides what this tool does, and whether anything reads it.

`openspec/specs/governance/` GOV-3. Where a list, tuple or mapping decides behaviour, it
is derived from what it describes or read by something. A hand-kept list guarded only by
the mechanism that consumes it is neither — and that is the defect this suite found in
six of its twelve layers: the mechanism gets a reader; the list it runs over does not.

The failure has one shape. A list cannot say what is missing from it, and the reader that
would have noticed the omission is the same line somebody would have had to edit to avoid
it. So it is never found by looking harder at the code that consumes the list.

    python tools/audit_derived_sets.py            # the census
    python tools/audit_derived_sets.py --out F    # write the record
    python tools/audit_derived_sets.py --check F  # exit 1 if the record is stale

**What is counted.** A module-level assignment in `scripts/` or `tools/` whose name is
upper case and whose value is a list, tuple, set or dict **literal**. A literal is the
whole point: a collection built by a comprehension or a function call is derived from
something, which is what the requirement asks for, so it is out of scope by construction.

**What "read" means here, exactly.** That a test file imports the name from its module —
`from <module> import <NAME>` or `<module>.<NAME>`. That is the strictest of the three
measures available and the only honest one. A bare word match over the test corpus counts
44 rather than 14, because names like `PAGE`, `CONFIG` and `CLASSES` occur in tests that
have nothing to do with them; and even the strict measure is an **upper bound** on being
read, since importing a name is not asserting what belongs in it. The number this prints
is therefore the most flattering one that is defensible, and the requirement is still
violated 150 times.
"""
from __future__ import annotations

import argparse
import ast
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
SKILL = os.path.join(ROOT, "skills", "seo-checklist")
SOURCES = (os.path.join(SKILL, "scripts"), os.path.join(SKILL, "tools"))
TESTS = os.path.join(ROOT, "tests")

LITERALS = (ast.List, ast.Tuple, ast.Set, ast.Dict)


def literal_sets(path: str) -> list[tuple[str, int]]:
    """Upper-case module-level names bound to a collection literal, with their size."""
    with open(path, encoding="utf-8") as stream:
        tree = ast.parse(stream.read())
    out = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        if not isinstance(value, LITERALS):
            continue
        for target in targets:
            name = getattr(target, "id", None)
            if name and name.isupper():
                size = len(value.keys) if isinstance(value, ast.Dict) else len(value.elts)
                out.append((name, size))
    return out


def test_corpus() -> str:
    return "\n".join(
        open(path, encoding="utf-8").read()
        for path in sorted(glob.glob(os.path.join(TESTS, "*.py"))))


def read_by_a_test(module: str, name: str, corpus: str) -> bool:
    """`from <module> import <NAME>` or `<module>.<NAME>`, and nothing looser.

    A bare word match is what the first draft used, and it counted `PAGE` as read
    because some other module's `PAGE` appears in a test. Attributing one module's
    coverage to another's constant is the direction that flatters, so the match is
    anchored on the module.
    """
    qualified = re.escape(module) + r"\." + re.escape(name) + r"\b"
    imported = (r"from\s+" + re.escape(module) + r"\s+import[^\n]*\b"
                + re.escape(name) + r"\b")
    return bool(re.search(qualified, corpus) or re.search(imported, corpus))


def census() -> dict:
    corpus = test_corpus()
    modules: dict[str, dict] = {}
    for directory in SOURCES:
        for path in sorted(glob.glob(os.path.join(directory, "*.py"))):
            module = os.path.basename(path)[:-3]
            for name, size in literal_sets(path):
                entry = modules.setdefault(module, {"read": [], "unread": []})
                where = "read" if read_by_a_test(module, name, corpus) else "unread"
                entry[where].append({"name": name, "entries": size})
    total = sum(len(m["read"]) + len(m["unread"]) for m in modules.values())
    unread = sum(len(m["unread"]) for m in modules.values())
    return {
        "measured": "module-level upper-case names bound to a list, tuple, set or dict "
                    "literal in scripts/ or tools/",
        "read_means": "a test imports the name from its module, which is an upper bound "
                      "on the membership being asserted",
        "total": total,
        "read": total - unread,
        "unread": unread,
        "modules": dict(sorted(modules.items())),
    }


def report(record: dict) -> list[str]:
    worst = sorted(record["modules"].items(),
                   key=lambda kv: -len(kv[1]["unread"]))[:10]
    lines = [
        f"{record['total']} hand-written sets decide behaviour in scripts/ and tools/.",
        f"{record['read']} are imported by a test; {record['unread']} are named by "
        f"nothing outside the code that consumes them.",
        "",
        "Most unread, by module:",
    ]
    lines += [f"  {module:34} {len(body['unread']):3}"
              for module, body in worst if body["unread"]]
    lines += [
        "",
        "Importing a name is not asserting what belongs in it, so the read column is a",
        "ceiling rather than a measurement. A set that is derived — built by a",
        "comprehension or a call — is out of scope here, because deriving it is what the",
        "requirement asks for.",
    ]
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", help="write the record here")
    parser.add_argument("--check", help="exit 1 if this record is stale")
    args = parser.parse_args()

    record = census()
    print("\n".join(report(record)))

    if args.out:
        with open(args.out, "w", encoding="utf-8") as stream:
            json.dump(record, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        print(f"\nwrote {os.path.relpath(args.out, ROOT)}")
        return 0

    if args.check:
        with open(args.check, encoding="utf-8") as stream:
            stored = json.load(stream)
        if stored == record:
            print("\nthe record is in step with the tree")
            return 0
        print(f"\n{os.path.relpath(args.check, ROOT)} is stale: it records "
              f"{stored.get('total')} sets and {stored.get('unread')} unread, the tree "
              f"has {record['total']} and {record['unread']}. Re-record with --out and "
              f"say in the commit which set moved and why.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
