#!/usr/bin/env python3
"""Find registry assertions that can never fire.

`none_matching` returns PASS when nothing matches. So an assertion aimed at
wording its script does not emit — or emits in a different word order — reports
PASS for every site, forever, silently. Fifteen of the registry's twenty-one
pattern assertions were in exactly that state when this was first run: three
asked an accessibility checker about font sizes it never measures, two asked a
mobile checker about interstitials it never looks for, and one wanted "lazy"
before "LCP" in a message that says "LCP image is lazy-loaded".

This scans each producing script for the strings it can actually emit and reports
any pattern that matches none of them.

    python3 tools/audit_assertions.py            # report, exit 1 if any are dead
    python3 tools/audit_assertions.py --verbose   # show every assertion

Prose is not the only way to answer an item and usually not the best one: prefer
a counted field or a `value_map` over the script's own vocabulary, both of which
report NO_DATA when the field is absent instead of passing.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
SCRIPTS = os.path.join(SKILL_DIR, "scripts")
REGISTRY = os.path.join(SKILL_DIR, "resources", "config", "checklist.json")

PATTERN_OPS = ("matching", "none_matching", "any_matching", "matches")

SHAPES = os.path.join(SKILL_DIR, "resources", "references",
                      "script-output-shapes.md")

sys.path.insert(0, SCRIPTS)
# Imported rather than restated: a copy of this table kept in the auditor would
# drift from the runner's exactly the way the assertions themselves drifted, and
# then the audit would clear rules the runner cannot fire.
from checklist_runner import SEVERITY_ALIAS  # noqa: E402

# Asserted paths that are absent from the probed output on purpose, because the
# probe ran without the credential that produces them. Each one reports NO_DATA
# without its key, which is the documented state — not a silent pass.
#
# `neighbors.suspicious` sat here until 0.46.0 under "needs a Safe Browsing key",
# and that was never true: `check_neighbors()` wants a paid reverse-IP service and
# has never had one, so the field is not withheld for want of a credential — no
# code writes it at all. The entry was right about the symptom for three releases
# and wrong about the cause, which is what an exemption list does when it is only
# ever read. It is now a `cannot_fail` declaration on the item, where
# `audit_reachability.py` re-derives the mechanism from the source every run.
# Everything left here must be a path its script demonstrably writes.
PATH_EXEMPT = {
    ("domain_safety_check.py", "safe_browsing.threats"): "needs a Safe Browsing key",
    ("domain_safety_check.py", "safe_browsing.clean"): "needs a Safe Browsing key",
    ("indexnow_checker.py", "key_valid"): "needs an IndexNow key",
}

# Paths whose value comes from the audited page rather than from the script's own
# vocabulary. A pattern over one of these is checking the site, not the script's
# wording, so there is nothing in the source to match it against.
PAGE_DERIVED = {
    ("parse_html.py", "meta_robots"),
}

from scope_line import print_scope  # noqa: E402

# What a passing run establishes, and what it does not (openspec/specs/governance/ GOV-6).
ESTABLISHES = (
    "every pattern and severity assertion in the registry can match something its "
    "script emits, and every path a rule reads is recorded in the probed shapes "
    "reference or exempted here with a reason"
)
DOES_NOT_ESTABLISH = (
    "that an assertion fires on the sites it should, or that what it asserts is the "
    "right question for the item's title"
)



def assertions(registry_path: str = REGISTRY) -> list[dict]:
    """Every pattern assertion in the registry, with the script that answers it."""
    with open(registry_path, encoding="utf-8") as f:
        registry = json.load(f)
    found: list[dict] = []

    def walk(node, item):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in PATTERN_OPS:
                    pattern = value[0] if key == "count_matching_lte" else value
                    found.append({"id": item["id"], "script": item["check"]["script"],
                                  "path": node.get("path"), "op": key,
                                  "pattern": pattern})
                else:
                    walk(value, item)
        elif isinstance(node, list):
            for value in node:
                walk(value, item)

    for item in registry["items"]:
        if item.get("check"):
            walk(item["check"], item)
    return found


def emittable_strings(script: str) -> list[str]:
    """String literals a script can put in its output.

    Docstrings, argparse text and remediation strings are excluded. Both describe what a script is
    for using the same words its findings would, and counting them made dead
    assertions look alive: the one pattern this tool initially cleared was
    matching `robots_checker.py`'s module docstring, which mentions CSS and
    JavaScript while the script itself never reports on either.
    """
    with open(os.path.join(SCRIPTS, script), encoding="utf-8") as f:
        tree = ast.parse(f.read())

    documentation: set[int] = set()
    for node in ast.walk(tree):
        # Remediation text. A finding says what is wrong; a `fix` says what to do
        # about it, in the vocabulary of the thing being asked for — so a pattern
        # meant for findings matches advice instead and fires for the wrong reason.
        # KW-072 and KW-073 asked whether the primary keyword was in the title and
        # the H1; `article_seo.py` has no keyword finding at all, and both patterns
        # were matching "…containing the primary keyword" inside a fix string. They
        # reported a keyword problem whenever the title or H1 had any problem, and
        # said nothing when the keyword was genuinely absent. This tool cleared
        # them, which is why the exclusion is here and not only in the registry.
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values, strict=True):
                if (isinstance(key, ast.Constant)
                        and str(key.value).lower() in ("fix", "recommendation",
                                                       "remediation", "suggestion",
                                                       "action")):
                    for sub in ast.walk(value):
                        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                            documentation.add(id(sub))
        # Docstrings: the first statement of a module, class or function.
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            first = node.body[0] if node.body else None
            if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                documentation.add(id(first.value))
        # Argparse prose: --help text says the same things the output does.
        if isinstance(node, ast.Call):
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            if name in ("add_argument", "ArgumentParser", "add_parser", "print_help"):
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                        documentation.add(id(sub))

    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and id(n) not in documentation]


def severity_literals(script: str, scripts_dir: str = SCRIPTS) -> set[str]:
    """The severity values a script can actually put in an issues[] entry.

    Read from the AST rather than by regex, because the two ways this codebase
    writes them look nothing alike: `{"severity": "High"}` and
    `seo_common.issue("warning", ...)`, whose first positional argument is the
    severity. A regex over the source finds every word in the file and clears rules
    that cannot fire — the same mistake that let fifteen dead patterns through the
    first version of this tool.
    """
    with open(os.path.join(scripts_dir, script), encoding="utf-8") as f:
        tree = ast.parse(f.read())
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values, strict=True):
                if (isinstance(key, ast.Constant) and str(key.value).lower() == "severity"
                        and isinstance(value, ast.Constant) and isinstance(value.value, str)):
                    out.add(value.value.lower())
        if isinstance(node, ast.Call):
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            if name == "issue" and node.args and isinstance(node.args[0], ast.Constant):
                if isinstance(node.args[0].value, str):
                    out.add(node.args[0].value.lower())
            for kw in node.keywords:
                if (kw.arg == "severity" and isinstance(kw.value, ast.Constant)
                        and isinstance(kw.value.value, str)):
                    out.add(kw.value.value.lower())
    return {SEVERITY_ALIAS.get(s, s) for s in out}


def severity_rules(registry_path: str = REGISTRY) -> list[dict]:
    """Every `none_severity` assertion, with the script that answers it."""
    with open(registry_path, encoding="utf-8") as f:
        registry = json.load(f)
    found = []
    for item in registry["items"]:
        chk = item.get("check") or {}
        for block, rule in (("assert", chk.get("assert")), ("warn", chk.get("warn"))):
            if isinstance(rule, dict) and "none_severity" in rule:
                found.append({"id": item["id"], "script": chk.get("script"),
                              "path": rule.get("path"), "block": block,
                              "wants": rule["none_severity"]})
    return found


def audit_severities(registry_path: str = REGISTRY) -> list[dict]:
    """Every `none_severity` rule asking for a severity its script never emits.

    This is the second family of assertion that silently passes forever, and it was
    larger than the first: thirteen items, one of them `critical`, asked for
    critical/high over scripts whose whole vocabulary is error/warning/info. The
    pattern audit above could not see them because the rule contains no pattern.
    """
    dead = []
    for row in severity_rules(registry_path):
        wants = {SEVERITY_ALIAS.get(s.lower(), s.lower()) for s in row["wants"]}
        try:
            emits = severity_literals(row["script"])
        except (OSError, SyntaxError) as exc:
            dead.append(dict(row, reason=f"cannot read script: {exc}"))
            continue
        if not emits:
            dead.append(dict(row, reason="the script emits no severity at all — "
                                         "its issues[] entries may be plain strings"))
        elif not (wants & emits) and row["block"] == "assert":
            dead.append(dict(row, reason=f"script only ever emits "
                                         f"{'/'.join(sorted(emits))}"))
        # A `warn` rule that cannot fire is not the same defect. In warn position a
        # rule that always passes means "nothing this script reports is serious
        # enough to fail the item", which for a script whose whole vocabulary is
        # warning/info is a true statement rather than a dead check — and it starts
        # failing by itself the day that script learns to say "error". Only the
        # no-severity-at-all case is broken in both positions.
    return dead


def probed_paths(shapes_path: str = SHAPES) -> dict[str, set[str]]:
    """Field paths per script, parsed out of the machine-probed shapes reference."""
    shapes: dict[str, set[str]] = {}
    current = None
    with open(shapes_path, encoding="utf-8") as f:
        for line in f:
            heading = re.match(r"^### `?([a-z0-9_]+\.py)`?\s*$", line)
            if heading:
                current = heading.group(1)
                shapes[current] = set()
                continue
            if current is None:
                continue
            field = re.match(r"^`([^`]+)`\s+—", line)
            if field:
                shapes[current].add(field.group(1))
                continue
            keys = re.match(r"^\s+- item keys: (.+)$", line)
            if keys and shapes[current]:
                arrays = [p for p in shapes[current] if p.endswith("[]")]
                if arrays:
                    holder = sorted(arrays, key=len)[-1]
                    for key in (k.strip() for k in keys.group(1).split(",")):
                        shapes[current].add(f"{holder}.{key}")
    return shapes


def path_is_probed(path: str, known: set[str]) -> bool:
    """Has any probe of the script reported this field path?

    A function rather than four lines inside the loop below because
    `audit_reachability.py` asks the same question — a field no probe has seen is
    half of its proof that a rule can never fail — and two copies of this matching
    would drift apart while both tools reported green.
    """
    # A list index in a rule is a position in an array the probe documents once.
    norm = re.sub(r"\.\d+(?=\.|$)", "[]", path)
    stem = norm.rstrip("[]")
    return any(norm == k or k.startswith(norm + ".") or k == norm + "[]"
               or k.rstrip("[]") == stem or norm.startswith(k.rstrip("[]") + ".")
               for k in known)


def audit_paths(registry_path: str = REGISTRY,
                shapes_path: str = SHAPES) -> list[dict]:
    """Every assertion reading a field no probe of its script has ever seen.

    The third family, and the quietest: `parse_html.py` never emitted
    `meta_keywords`, and MS-031 asserts it is falsy with `missing_is: pass`, so the
    item passed on every site including one with a stuffed keywords tag. A rule can
    only be as honest as the existence of the field it reads.
    """
    with open(registry_path, encoding="utf-8") as f:
        registry = json.load(f)
    shapes = probed_paths(shapes_path)
    missing = []
    for item in registry["items"]:
        chk = item.get("check") or {}
        script = chk.get("script")
        rule = chk.get("assert") or {}
        path = rule.get("path")
        if not script or not path:
            continue
        if (script, path) in PATH_EXEMPT:
            continue
        # A field the script has no code to write is a stronger statement than a
        # field this probe did not see, and `audit_reachability.py` proves it from
        # the source. That claim is declared on the item, checked in both
        # directions there, and would only rot a second time if restated here.
        if (chk.get("cannot_fail") or {}).get("mechanism") == "path_never_emitted":
            continue
        known = shapes.get(script)
        if known is None:
            missing.append({"id": item["id"], "script": script, "path": path,
                            "reason": "script has no section in the shapes reference"})
            continue
        if not path_is_probed(path, known):
            missing.append({"id": item["id"], "script": script, "path": path,
                            "reason": "not in the probed output"})
    return missing


def audit(registry_path: str = REGISTRY) -> list[dict]:
    """Every assertion whose pattern cannot match anything its script emits."""
    dead = []
    for row in assertions(registry_path):
        if (row["script"], row["path"]) in PAGE_DERIVED:
            continue
        try:
            candidates = emittable_strings(row["script"])
        except (OSError, SyntaxError) as exc:
            dead.append(dict(row, reason=f"cannot read script: {exc}"))
            continue
        if not any(re.search(row["pattern"], text) for text in candidates):
            dead.append(dict(row, reason="matches nothing the script emits"))
    return dead


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--registry", default=REGISTRY)
    ap.add_argument("--verbose", action="store_true",
                    help="list every pattern assertion, not just the dead ones")
    a = ap.parse_args()

    every = assertions(a.registry)
    dead = audit(a.registry)
    sev_rules = severity_rules(a.registry)
    dead_sev = audit_severities(a.registry)
    dead_paths = audit_paths(a.registry)
    if a.verbose:
        bad = {(d["id"], d["pattern"]) for d in dead}
        for row in sorted(every, key=lambda r: r["script"]):
            mark = "DEAD" if (row["id"], row["pattern"]) in bad else "ok  "
            print(f"{mark} {row['id']:9}{row['script']:30}{row['pattern'][:40]}")
        bad_sev = {(d["id"], d["block"]) for d in dead_sev}
        for row in sorted(sev_rules, key=lambda r: r["script"]):
            mark = "DEAD" if (row["id"], row["block"]) in bad_sev else "ok  "
            print(f"{mark} {row['id']:9}{row['script']:30}"
                  f"{row['block']}: none_severity={'/'.join(row['wants'])}")

    print(f"\n{len(every)} pattern assertion(s), {len(dead)} that can never fire")
    print(f"{len(sev_rules)} severity assertion(s), {len(dead_sev)} that can never fire")
    print(f"{len(every) + len(sev_rules)} of them audited against script source; "
          f"every path audited against the probed shapes reference, "
          f"{len(dead_paths)} unseen")
    for d in dead:
        print(f"  {d['id']} {d['script']} {d['path']} "
              f"{d['op']}={d['pattern']!r} — {d['reason']}", file=sys.stderr)
    for d in dead_sev:
        print(f"  {d['id']} {d['script']} {d['block']}.none_severity="
              f"{d['wants']} — {d['reason']}", file=sys.stderr)
    for d in dead_paths:
        print(f"  {d['id']} {d['script']} path={d['path']!r} — {d['reason']}",
              file=sys.stderr)
    if dead or dead_sev or dead_paths:
        print("\nEach of these reports PASS for every site. Replace the rule with a "
              "counted field or a value_map over the script's own vocabulary, point "
              "it at a severity the script emits, or move the item to whoever can "
              "answer it. If a path is genuinely absent only without a credential, "
              "add it to PATH_EXEMPT with the reason.", file=sys.stderr)
    if dead or dead_sev or dead_paths:
        return 1
    print_scope(ESTABLISHES, DOES_NOT_ESTABLISH)
    return 0


if __name__ == "__main__":
    sys.exit(main())
