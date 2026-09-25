#!/usr/bin/env python3
"""Every number a verdict rests on, and what each one rests on in turn.

§2 of KNOWN-ISSUES.md names the gap this closes: **a test can show that a threshold
fires; it cannot show the threshold is right.** Four layers of tests prove that a
named field answers a named question, that a check can tell two sites apart, that
nothing is decided about a site which answered nothing. None of them argues with the
numbers. A site audited at the wrong threshold gets a confident verdict about the
wrong question, and that is what this suite is worst at seeing.

Calibration is not more tests. It is deciding, per threshold, what the number rests
on, and writing that down beside it — so a reader who disagrees can see the basis
instead of arguing with a verdict whose grounds are invisible. This tool is what
makes "written down beside it" checkable rather than aspirational.

    python3 tools/audit_thresholds.py            # the inventory, and the gaps
    python3 tools/audit_thresholds.py --check    # non-zero if any basis declaration is invalid

**The convention.** A module-level numeric constant that a comparison or a
verdict-affecting multiplicative estimate reads is a threshold, and it must carry a
line of the form

    # basis: <kind> — <what it rests on>

in the comment block above it, or in its own trailing comment. Five kinds, and the
distinction between them is the whole point:

  standard    An external published authority, named in the text. Google's Core Web
              Vitals bands, an RFC, a WCAG level. The number is not ours and a reader
              can go and check it.
  measured    Calibrated against something, and the text says against what. This is
              the only kind that is evidence rather than judgement. Required form:
              # basis: measured — corpus=<what was measured>; date=<YYYY-MM-DD>; method=<how>
  convention  A judgement made here. A round number, chosen because a line had to be
              somewhere. Saying so is the point: it invites the argument instead of
              hiding from it.
  inherited   Arrived with borrowed code and has not been examined. **Not an excuse —
              a to-do with a name.** The count is printed, and it is the honest
              measure of how much of this registry rests on numbers nobody here
              decided.
  presentation
              Decides what is *printed*, never what is decided: a truncation length,
              a "… and 7 more" cut-off, how much of a key is masked. Counted apart
              from the four above and excluded from "numbers a verdict depends on",
              because a report that lists three linking pages instead of four is a
              report making a different choice, not an audit reaching a different
              verdict. **The line is that the verdict is already computed** when one
              of these is read; anything that could still change it is a threshold.

**The scan reads names and is deliberately shallow, and a written basis is
authoritative over it.** When a reader finds a number the name-based scan misses,
write the basis rather than filing a bug against the scan. 0.68.0 found one — a
constant used inside `timedelta(days=…)` and therefore invisible — wrote its basis,
recorded in the changelog that the inventory could not see it, and named fixing this
tool as the next step; 0.71.0 is that step, and it recovered seven such declarations.

That authority has a cost which must not be hidden: a basis line is a claim, not a
proof. Writing one on a buffer size or retry count puts it into "numbers a verdict
depends on" and the gate will not object. The count is only as honest as the lines;
review catches a wrong one, not this tool — the same is already true of a
`convention` basis that says nothing useful.

**Every number is named now.** The unnamed count was 77 at 0.14.0 and is a ceiling in
CI; a comparison against a bare literal cannot carry a basis, because it has no name
to hang one on, so the first step for those was a constant rather than a comment.
Naming them is what let `presentation` be told from `convention` at all — and what
turned up two thresholds written twice, which is the concrete argument for the
exercise: one number in two places is one number that can drift into two.
"""
from __future__ import annotations

import argparse
import ast
import datetime
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
SCRIPTS = os.path.join(SKILL, "scripts")

from scope_line import print_scope  # noqa: E402

# What a passing run establishes, and what it does not (openspec/specs/governance/ GOV-6).
ESTABLISHES = (
    "every named number a verdict depends on carries a basis line of a known kind, "
    "and every measured basis names its corpus, date and method"
)
DOES_NOT_ESTABLISH = (
    "that any number is right: a basis is a claim and not a proof, an inherited one "
    "has not been examined here, and constants this name-based scan cannot see are "
    "listed with --uncounted rather than judged"
)



def _report_path(path: str) -> str:
    """`path` relative to the skill, or absolute when no relation can be expressed.

    `os.path.relpath` raises ValueError on Windows when the two paths sit on
    different drive letters — the checkout on D: and a temp file on C: is the
    ordinary case on a GitHub runner. This label is for a human reading a report,
    so an unhelpful-but-correct absolute path beats an exception.
    """
    try:
        return os.path.relpath(path, SKILL)
    except ValueError:
        return os.path.abspath(path)


BASIS = re.compile(
    r"#\s*basis:\s*(standard|measured|convention|inherited|presentation)\s*[—-]\s*(\S.*)",
    re.I)
MEASURED_FIELD = re.compile(r"^\s*([a-z]+)\s*=\s*([^;]*\S)\s*$", re.I)
BASIS_MARKER = re.compile(r"#\s*basis:\s*", re.I)
KINDS = ("standard", "measured", "convention", "inherited", "presentation")
# The four that decide a verdict. `presentation` is named and checked like the rest and
# then kept out of this total, because the number §2 of KNOWN-ISSUES quotes is meant to
# be "how much of the registry rests on numbers nobody here decided", and a truncation
# length is not part of that.
VERDICT_KINDS = ("standard", "measured", "convention", "inherited")
MEASURED_KEYS = frozenset({"corpus", "date", "method"})

# Numbers that are not thresholds, and excluding them is what keeps this tool worth
# reading. An HTTP status code is an identity, not a limit: `status == 404` asks which
# answer arrived, and there is no version of it that could be "calibrated". Same for
# the arithmetic constants — a comparison against 0 or 1 is almost always "is there
# any" or "is there more than one".
HTTP_STATUS = frozenset(range(100, 600))
# 0, 1, 2 and -1 only. This set used to hold 100, 1000 and 1024 as well, on the theory
# that they are units rather than limits — and that was measured wrong: removing them
# surfaced eleven comparisons, ten of them real thresholds, including "a meta
# description under 100 characters is too short" and "under 1000 words may be thin for
# a blog post". A round number is *more* likely to be a threshold somebody typed, not
# less. `2` stays because it is almost always arity — "did we get at least two labels",
# "is there more than one hop to compare" — and the ones it hides are visible in
# `--unnamed` output as soon as anybody looks.
ARITHMETIC = frozenset({0, 1, 2, -1})
# A comparison is about a status code when the other side says so. Checked by name
# rather than by value, because 200 is also a perfectly good byte count.
STATUS_WORDS = re.compile(r"\b(status|status_code|code|http_status|response_code)\b")


def _numeric(node: ast.AST) -> bool:
    """Whether an expression is, or contains, a number worth calling a threshold."""
    if isinstance(node, ast.Constant):
        return isinstance(node.value, (int, float)) and not isinstance(node.value, bool)
    if isinstance(node, (ast.Dict, ast.Tuple, ast.List, ast.Set)):
        parts = list(getattr(node, "values", [])) + list(getattr(node, "elts", []))
        return bool(parts) and any(_numeric(p) for p in parts)
    if isinstance(node, ast.BinOp):          # 5 * 1024 * 1024
        return _numeric(node.left) or _numeric(node.right)
    if isinstance(node, ast.UnaryOp):
        return _numeric(node.operand)
    return False


def _names_in(node: ast.AST) -> set[str]:
    """Every constant a comparison reads, including through a subscript.

    The subscript case is not an edge case — it is where the most consequential
    thresholds in this tree live. `cwv_metrics.THRESHOLDS["lcp_ms"]["good"]` is
    Google's LCP band, and a scan that only looked at bare `Name` nodes in a
    comparison would report it as absent while it decided three items.
    """
    found = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name):
            found.add(sub.id)
    return found


def _basis_for(src_lines: list[str], lineno: int) -> tuple[str, str]:
    """The `# basis:` line for an assignment at `lineno`, searching upward.

    Its own trailing comment first, then the contiguous comment block above it. A
    blank line ends the block: a basis three paragraphs up belongs to something else.
    """
    own = src_lines[lineno - 1]
    match = BASIS.search(own)
    if match:
        return match.group(1).lower(), match.group(2).strip()
    i = lineno - 2
    while i >= 0:
        line = src_lines[i].strip()
        if not line:
            break
        if not line.startswith("#"):
            break
        match = BASIS.search(line)
        if match:
            return match.group(1).lower(), match.group(2).strip()
        i -= 1
    return "", ""


def _measured_problem(tail: str) -> str:
    """Return why a measured tail is not reproducible, or an empty string."""
    fields: dict[str, tuple[str, int]] = {}
    problems = []
    parts = tail.split(";")
    for index, part in enumerate(parts):
        match = MEASURED_FIELD.fullmatch(part)
        if not match:
            problems.append(f"field {index + 1} is not a non-empty key=value field")
            continue
        key, value = match.group(1).lower(), match.group(2).strip()
        if key not in MEASURED_KEYS:
            problems.append(f"unknown field {key!r}")
        elif key in fields:
            problems.append(f"field {key!r} appears more than once")
        else:
            fields[key] = (value, index)

    missing = sorted(MEASURED_KEYS - fields.keys())
    if missing:
        problems.append("missing " + ", ".join(missing))

    if "date" in fields:
        value, index = fields["date"]
        # Only the last field may carry the optional prose suffix. A period or em
        # dash is the boundary; the ISO date itself remains the value we validate.
        if index == len(parts) - 1:
            date_match = re.fullmatch(
                r"(\d{4}-\d{2}-\d{2})(?:\s*(?:—|\.)\s*.*)?", value)
        else:
            date_match = re.fullmatch(r"(\d{4}-\d{2}-\d{2})", value)
        if not date_match:
            problems.append(f"date {value!r} is not YYYY-MM-DD")
        else:
            try:
                datetime.date.fromisoformat(date_match.group(1))
            except ValueError:
                problems.append(f"date {date_match.group(1)!r} is not a real date")
    return "; ".join(problems)


def basis_issues(path: str) -> list[dict]:
    """Malformed measured declarations and basis kinds outside the vocabulary."""
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().splitlines()

    out = []
    for lineno, line in enumerate(lines, 1):
        marker = BASIS_MARKER.search(line)
        if not marker:
            continue
        rest = line[marker.end():].strip()
        kind_match = re.match(r"[a-z]+", rest, re.I)
        kind = kind_match.group(0).lower() if kind_match else ""
        where = {"file": _report_path(path), "line": lineno}
        if kind not in KINDS:
            out.append({**where, "type": "unknown", "kind": kind or "(none)",
                        "detail": (f"{kind!r} is not one of {', '.join(KINDS)}"
                                   if kind else "no basis kind follows the colon")})
            continue
        if kind != "measured":
            continue
        match = BASIS.search(line)
        problem = (_measured_problem(match.group(2).strip()) if match else
                   "missing a non-empty tail after the dash")
        if problem:
            out.append({**where, "type": "measured", "kind": kind,
                        "detail": problem})
    return out


def _constant_lines(tree: ast.Module) -> dict[str, int]:
    """Names and lines of module-level uppercase numeric constants."""
    out = {}
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id.isupper() and _numeric(node.value)):
            out[node.targets[0].id] = node.lineno
    return out


def numeric_constants(path: str) -> list[dict]:
    """Every module-level uppercase numeric constant in `path`."""
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    lines = src.splitlines()
    tree = ast.parse(src)
    out = []
    for name, lineno in sorted(_constant_lines(tree).items(), key=lambda kv: kv[1]):
        kind, why = _basis_for(lines, lineno)
        out.append({"file": _report_path(path), "name": name, "line": lineno,
                    "kind": kind, "why": why})
    return out


def named_thresholds(path: str) -> list[dict]:
    """Module-level numeric constants a scan sees or an author declares."""
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    lines = src.splitlines()
    tree = ast.parse(src)

    consts = _constant_lines(tree)

    # Ordering comparisons only. A constant that is only ever tested for equality is
    # an **identity, not a threshold**: `inventory_version != INVENTORY_VERSION` asks
    # which format this file is, and there is no version of that question a
    # calibration could improve. Asking for a basis there would train the reader to
    # skim past the ones that have one.
    ordering = (ast.Lt, ast.LtE, ast.Gt, ast.GtE)
    compared: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            if any(isinstance(op, ordering) for op in node.ops):
                compared |= _names_in(node)
        # A number handed to min/max is a bound as surely as one in a comparison.
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id in ("min", "max"):
            for arg in node.args:
                compared |= _names_in(arg)
        # A multiplicative estimate can move a verdict without appearing in an
        # ordering comparison itself. `MINIFICATION_SAVINGS_FRACTION` estimates raw
        # bytes saved; the estimated total is compared with a severity threshold.
        # Missing it was the same blind spot as a bare multiplier, only with a name.
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
            compared |= _names_in(node)
        # A numeric table whose values are looked up at all. Following the value to
        # the comparison would need dataflow the AST does not give for free, and the
        # cost of not trying was concrete: `cwv_metrics.THRESHOLDS` holds Google's
        # Core Web Vitals bands, is read as `limits = THRESHOLDS[metric]` and then
        # compared as `value <= limits["good"]`, and a scan that only looked inside
        # `Compare` nodes reported the most authoritative numbers in the tree as
        # absent while they decided six items. Over-including a lookup table that
        # turns out to decide nothing costs one line of explanation; missing those
        # cost the whole point of the tool.
        elif isinstance(node, (ast.Subscript, ast.Attribute)):
            compared |= _names_in(node.value)

    out = []
    for name, lineno in sorted(consts.items(), key=lambda kv: kv[1]):
        kind, why = _basis_for(lines, lineno)
        if name not in compared and not kind:
            continue
        out.append({"file": _report_path(path), "name": name,
                    "line": lineno, "kind": kind, "why": why})
    return out


def uncounted_constants(path: str, counted: list[dict] | None = None) -> list[dict]:
    """Module-level numeric constants neither seen nor declared with a basis."""
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    rows = counted if counted is not None else named_thresholds(path)
    counted_names = {row["name"] for row in rows}
    return [{"file": _report_path(path), "name": name, "line": lineno}
            for name, lineno in sorted(_constant_lines(tree).items(), key=lambda kv: kv[1])
            if name not in counted_names]


def non_numeric_basis_lines(path: str) -> list[dict]:
    """Basis markers not attached to a module-level numeric constant."""
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    lines = src.splitlines()
    tree = ast.parse(src)
    attached = set()
    for lineno in _constant_lines(tree).values():
        if BASIS_MARKER.search(lines[lineno - 1]):
            attached.add(lineno)
            continue
        i = lineno - 2
        while i >= 0:
            line = lines[i].strip()
            if not line or not line.startswith("#"):
                break
            if BASIS_MARKER.search(line):
                attached.add(i + 1)
                break
            i -= 1
    return [{"file": _report_path(path), "line": lineno}
            for lineno, line in enumerate(lines, 1)
            if BASIS_MARKER.search(line) and lineno not in attached]


def unnamed_thresholds(path: str) -> list[dict]:
    """Ordering comparisons against a bare number, less status codes and arithmetic.

    Ordering only, for the same reason `named_thresholds` counts ordering only: a bare
    number tested for equality is an identity, not a limit. `len(lang) == 2` asks
    whether a code is two letters, and there is no calibration of that. Keeping the two
    halves of this tool on one rule also matters for its arithmetic — the unnamed count
    is meant to be "how many of these have not been given a name yet", and it cannot be
    if the two sides disagree about what counts.
    """
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    lines = src.splitlines()
    ordering = (ast.Lt, ast.LtE, ast.Gt, ast.GtE)
    out = []
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Compare):
            continue
        if not any(isinstance(op, ordering) for op in node.ops):
            continue
        text = lines[node.lineno - 1] if node.lineno <= len(lines) else ""
        about_status = bool(STATUS_WORDS.search(text))
        for side in [node.left, *node.comparators]:
            if not isinstance(side, ast.Constant):
                continue
            value = side.value
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                continue
            if value in ARITHMETIC:
                continue
            if about_status and value in HTTP_STATUS and float(value).is_integer():
                continue
            out.append({"file": _report_path(path), "line": node.lineno,
                        "value": value, "source": text.strip()[:90]})
    return out


def _script_paths() -> list[str]:
    paths = []
    for folder in (SCRIPTS, os.path.join(SCRIPTS, "lib")):
        for entry in sorted(os.listdir(folder)):
            if entry.endswith(".py") and entry != "__init__.py":
                paths.append(os.path.join(folder, entry))
    return paths


def _scan_all(paths: list[str] | None = None) -> tuple[list[dict], list[dict], list[dict]]:
    named, unnamed, uncounted = [], [], []
    for path in paths if paths is not None else _script_paths():
        path_named = named_thresholds(path)
        named += path_named
        unnamed += unnamed_thresholds(path)
        uncounted += uncounted_constants(path, path_named)
    return named, unnamed, uncounted


def scan(paths: list[str] | None = None) -> tuple[list[dict], list[dict]]:
    named, unnamed, _ = _scan_all(paths)
    return named, unnamed


def scan_uncounted(paths: list[str] | None = None) -> list[dict]:
    return _scan_all(paths)[2]


def scan_non_numeric_basis(paths: list[str] | None = None) -> list[dict]:
    out = []
    for path in paths if paths is not None else _script_paths():
        out += non_numeric_basis_lines(path)
    return out


def scan_basis_issues(paths: list[str] | None = None) -> list[dict]:
    out = []
    for path in paths if paths is not None else _script_paths():
        out += basis_issues(path)
    return out


def main(argv: list[str] | None = None, paths: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Inventory every number a verdict depends on",
        epilog=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true",
                    help="exit non-zero if a counted threshold basis is absent, or any is malformed")
    ap.add_argument("--unnamed", action="store_true",
                    help="list the comparisons against a bare number")
    ap.add_argument("--uncounted", action="store_true",
                    help="list module-level numeric constants outside the inventory")
    ap.add_argument("--kind", default="", choices=("", *KINDS),
                    help="list only thresholds of this kind")
    a = ap.parse_args(argv)

    source_paths = paths if paths is not None else _script_paths()
    named, unnamed, uncounted = _scan_all(source_paths)
    non_numeric_basis = scan_non_numeric_basis(source_paths)
    issues = scan_basis_issues(source_paths)
    bare = [t for t in named if not t["kind"]]
    by_kind = {k: [t for t in named if t["kind"] == k] for k in KINDS}
    measured_issues = [i for i in issues if i["type"] == "measured"]
    unknown_issues = [i for i in issues if i["type"] == "unknown"]

    if a.kind and not a.check:
        for t in by_kind[a.kind]:
            print(f"  {t['file']}:{t['line']}  {t['name']}\n      {t['why']}")
        print(f"\n{len(by_kind[a.kind])} {a.kind} threshold(s)")
        print_scope(ESTABLISHES, DOES_NOT_ESTABLISH)
        return 0

    if a.unnamed and not a.check:
        for t in unnamed:
            print(f"  {t['file']}:{t['line']}  {t['value']}   {t['source']}")
        print(f"\n{len(unnamed)} comparison(s) against a bare number")
        print_scope(ESTABLISHES, DOES_NOT_ESTABLISH)
        return 0

    if a.uncounted:
        for t in sorted(uncounted, key=lambda row: (row["file"], row["line"], row["name"])):
            print(f"  {t['file']}:{t['line']}  {t['name']}")
        print(f"\n{len(uncounted)} module-level numeric constant(s) not in the inventory")
        if not a.check:
            print_scope(ESTABLISHES, DOES_NOT_ESTABLISH)
            return 0
        print()

    verdict = sum(len(by_kind[k]) for k in VERDICT_KINDS)
    print(f"{verdict} number(s) a verdict depends on:")
    for kind in VERDICT_KINDS:
        print(f"  {kind:<12} {len(by_kind[kind]):>3}")
    print(f"  {'no basis':<12} {len(bare):>3}")
    print(f"\n{len(by_kind['presentation'])} more decide only what is printed "
          f"(presentation), and are not counted above")
    print(f"{len(unnamed)} threshold(s) still unnamed — a comparison against a bare "
          f"number cannot carry a basis, so the first step for those is a constant")
    print(f"{len(uncounted)} module-level numeric constant(s) are not in this inventory: "
          "no `# basis:` line, and\n   no comparison this name-based scan can see. "
          "Listed with --uncounted.")
    locations = ", ".join(
        f"{os.path.basename(row['file'])}:{row['line']}" for row in non_numeric_basis)
    print(f"{len(non_numeric_basis)} basis line(s) name something that is not a "
          "module-level numeric constant, so nothing\n   here counts them: "
          f"{locations or 'none'}.")

    failed = False
    if measured_issues:
        print("\nMeasured, but without a reproducible measurement:")
        for issue in measured_issues:
            print(f"  {issue['file']}:{issue['line']}  {issue['detail']}")
        if a.check:
            print("\nWrite `# basis: measured — corpus=<what was measured>; "
                  "date=<YYYY-MM-DD>; method=<how>`. The corpus says what the number "
                  "describes, the date makes staleness visible, and the method makes "
                  "the measurement repeatable.", file=sys.stderr)
            failed = True

    if unknown_issues:
        print("\nBasis lines outside the documented five-kind vocabulary:")
        for issue in unknown_issues:
            print(f"  {issue['file']}:{issue['line']}  {issue['detail']}")
        if a.check:
            print("\nWrite `# basis: standard|measured|convention|inherited|"
                  "presentation — why`. If the comment does not describe a numeric "
                  "threshold, describe it without the `# basis:` marker so it cannot "
                  "silently look like one.", file=sys.stderr)
            failed = True

    if bare:
        print("\nNamed, and resting on nothing stated:")
        for t in bare:
            print(f"  {t['file']}:{t['line']}  {t['name']}")
        if a.check:
            print("\nAdd a `# basis: standard|measured|convention|inherited — why` "
                  "line above each. `inherited` is allowed and counted: a number that "
                  "arrived with borrowed code and has not been examined is a to-do "
                  "with a name, which is worth more than a number with neither.",
                  file=sys.stderr)
            failed = True
    if failed:
        return 1
    print_scope(ESTABLISHES, DOES_NOT_ESTABLISH)
    return 0


if __name__ == "__main__":
    sys.exit(main())
