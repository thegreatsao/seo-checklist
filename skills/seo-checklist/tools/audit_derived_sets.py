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
`from <module> import <NAME>` or `<module>.<NAME>`, including where that test bound the
module to an alias. That is the strictest of the three
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
import functools
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

from scope_line import print_scope  # noqa: E402

# What a passing run establishes, and what it does not (openspec/specs/governance/ GOV-6).
ESTABLISHES = (
    "the census of hand-written sets in scripts/ and tools/, and of which ones a test "
    "imports, matches the record it is checked against"
)
DOES_NOT_ESTABLISH = (
    "that any set holds the right members, since importing a name is not asserting "
    "what belongs in it and the read column is a ceiling, or anything about a set "
    "built by a call or a comprehension, which is not counted"
)



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


def test_corpus() -> list[tuple[str, str]]:
    """`(path, source)` per test module, not one joined string.

    Per file on purpose: aliases are resolved below, and an alias is only meaningful
    inside the file that bound it. `sh` means `lib.safe_http` in one test module and
    `security_headers` in another, so a corpus flattened into a single string cannot
    tell which module `sh.SOMETHING` credits — and guessing would credit one module's
    coverage to another's constant, the direction this census is careful not to flatter.
    """
    out = []
    for path in sorted(glob.glob(os.path.join(TESTS, "*.py"))):
        with open(path, encoding="utf-8") as stream:
            out.append((path, stream.read()))
    return out


@functools.lru_cache(maxsize=None)
def aliases_in(source: str) -> dict[str, frozenset[str]]:
    """`{real module name: {alias bound in this file}}`, read with the AST.

    `import lib.safe_http as sh` binds the alias to the last component, which is how
    the census names its modules, so the key is the basename.

    Cached because the question is asked once per set and there are 173 of them: the
    uncached version re-parsed forty test modules for each, and turned a census that
    ran in a second into one that ran for two minutes. A gate nobody will wait for is
    a gate somebody will take out of CI.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}
    found: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    found.setdefault(alias.name.split(".")[-1], set()).add(alias.asname)
    return {module: frozenset(names) for module, names in found.items()}


def read_by_a_test(module: str, name: str,
                   corpus: list[tuple[str, str]] | str) -> bool:
    """`from <module> import <NAME>`, `<module>.<NAME>`, or the same under an alias.

    A bare word match is what the first draft used, and it counted `PAGE` as read
    because some other module's `PAGE` appears in a test. Attributing one module's
    coverage to another's constant is the direction that flatters, so the match is
    anchored on the module.

    **The alias arm was added at 0.104.0, and it moved the read column from 28 to 43.**
    Both older patterns spell the module out, so `import checklist_runner as r` followed
    by `r.MODE_CAPS` asserted the membership and was recorded as unread — fifteen sets
    of forty-three, more than a third of the column, invisible for the usual reason: a
    census finds only the spellings it was given. Measured before the repair in
    `local/dec8/measure-alias-blindness.py`, which resolves the aliases with the AST and
    re-asks the same question of the record this tool had already written.
    """
    if isinstance(corpus, str):
        # One test module's worth of source, which is how `test_derived_sets.py` asks
        # this question about a hand-written example. The per-file shape is what the
        # census itself passes.
        corpus = [("<given>", corpus)]
    imported = (r"from\s+" + re.escape(module) + r"\s+import[^\n]*\b"
                + re.escape(name) + r"\b")
    for _path, source in corpus:
        for spelling in {module, *aliases_in(source).get(module, set())}:
            if re.search(re.escape(spelling) + r"\." + re.escape(name) + r"\b", source):
                return True
        if re.search(imported, source):
            return True
    return False


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
        "read_means": "a test imports the name from its module, under its own name or "
                      "an alias the test bound, which is an upper bound on the "
                      "membership being asserted",
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


def moved(stored: dict, fresh: dict) -> list[str]:
    """Which named sets differ between a stored record and the tree, in its own words.

    The two totals are not where most differences live. A set whose *membership* moved
    leaves both counts alone, and the message then read "it records 169 sets and 145
    unread, the tree has 169 and 145" — identical numbers on both sides, which reads as
    a broken tool rather than as a stale record. That happened at 0.96.3, when a fifth
    debt class took `spec_debt.CLASSES` from four entries to five.
    """
    def flat(record: dict) -> dict:
        out = {}
        for module, columns in (record.get("modules") or {}).items():
            for column, sets in columns.items():
                for entry in sets:
                    out[f"{module}.{entry['name']}"] = (column, entry.get("entries"))
        return out

    before, after = flat(stored), flat(fresh)
    lines = []
    for name in sorted(set(before) | set(after)):
        old, new = before.get(name), after.get(name)
        if old == new:
            continue
        if old is None:
            lines.append(f"{name} is new to the tree ({new[1]} entries, {new[0]})")
        elif new is None:
            lines.append(f"{name} is recorded and is no longer in the tree")
        elif old[1] != new[1]:
            lines.append(f"{name}: {old[1]} entries -> {new[1]}")
        else:
            lines.append(f"{name}: {old[0]} -> {new[0]}")
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
        print_scope(ESTABLISHES, DOES_NOT_ESTABLISH)
        return 0

    if args.check:
        with open(args.check, encoding="utf-8") as stream:
            stored = json.load(stream)
        if stored == record:
            print("\nthe record is in step with the tree")
            print_scope(ESTABLISHES, DOES_NOT_ESTABLISH)
            return 0
        print(f"\n{os.path.relpath(args.check, ROOT)} is stale.", file=sys.stderr)
        if (stored.get("total"), stored.get("unread")) != (record["total"],
                                                           record["unread"]):
            print(f"  it records {stored.get('total')} sets and "
                  f"{stored.get('unread')} unread; the tree has {record['total']} "
                  f"and {record['unread']}.", file=sys.stderr)
        for line in moved(stored, record):
            print(f"  {line}", file=sys.stderr)
        print("Re-record with --out and say in the commit which set moved and why.",
              file=sys.stderr)
        return 1
    print_scope(ESTABLISHES, DOES_NOT_ESTABLISH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
