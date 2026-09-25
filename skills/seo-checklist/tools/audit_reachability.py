#!/usr/bin/env python3
"""Find registry rules that cannot report FAIL, and make the deliberate ones say so.

`KW-076` *Use the Primary Keyword in Body Copy* asserted `target_keyword` truthy, and
`article_seo.py` wrote that field only when it already held something:

    if target_kw:
        result["target_keyword"] = target_kw

So the value the rule read was true whenever it existed and absent otherwise. The item
reported PASS or NO_DATA on every site ever audited, for years, and no gate saw it —
`audit_assertions.py` audits patterns, severities and unseen paths, none of which this
is. A rule that cannot fail is a rule that cannot find the defect its title names.

Some rules cannot fail **on purpose**. `TE-179` grades domain age with a numeric warn
band that is the assertion's exact complement, so an established domain passes, a
younger one warns, and there is no third value. The same proof applies to complementary
`truthy`/`falsy` flags and to `value_map` pairs where every value that fails the
assertion passes the band.
`TE-178` asserts a field its script deliberately never fabricates. Both are decisions,
and the difference between them and `KW-076` is not in the code: in all three the field
is absent, or safe, exactly when the answer would have been bad. **The code cannot tell
you which were meant.**

So intent is declared, in the registry, beside the rule — `check.cannot_fail`, from the
`CANNOT_FAIL` table in `build_checklist.py`. This tool holds no item ids at all. What it
does hold is the machinery to re-derive, from the script's own source, *why* a rule
cannot fail, and it checks the declaration in three directions:

  * proven unreachable and undeclared — the `KW-076` class, and the reason this exists;
  * declared and no longer provable — the declaration outlived its reason, the failure
    `test_no_exemption_outlives_the_reason_for_it` catches for `SAME_ON_BOTH`;
  * declared under one mechanism, provable only under another — the rule still cannot
    fail, but not for the recorded reason. This is how an exemption list rots while
    every entry in it still looks true: `audit_assertions.PATH_EXEMPT` carried
    "needs a Safe Browsing key" against a field whose script wants a paid reverse-IP
    service and has never had one.

An exclusion list rots because it is only ever read. This one is derived again on every
run, and the prose is anchored to a token the code has to keep earning.

**What it does not claim.** Four detectors, each proving unreachability from a shape
this registry has actually held. Silence about an item is not a finding that it can
fail; it is the absence of a proof either way, and the summary line prints that count
rather than implying coverage it does not have.

**And `severity_vocabulary` reads literals, not reachable code.** A script that writes
`"severity": "error"` under a flag the registry never passes has the word and cannot
say it, so this tool falls silent while FAIL stays unreachable. That is not
hypothetical: 0.50.0 graded the uncontrolled facet in `faceted_nav_audit.py` as
`error`, and the finding sits inside `if fetch:` while `AR-163` was invoking the script
without `--fetch`. **Adding the severity silenced this gate and changed nothing**, and
it was caught by reading the invocation rather than by any check here. The flag is
passed now. When you grade a finding to make an item failable, check that the
registry's own arguments reach the line.

A fourth was written and removed before it shipped, and the reason is worth keeping. It
claimed a rule could not fail when every write of its field was a literal that passed.
On its first run it reported four items, and all four were wrong in four different ways:
`unminified_count` is initialised to `0` and counted up with `+=`, which the site scan
does not model; `duplicates` is initialised to `[]` and filled with `.append`;
`headers_missing` is initialised to `{}` and written *into* by subscript; and
`strict-transport-security` is a key of a static table of header descriptions and has
nothing to do with `header_values`, because the scan matched the last segment of the
path and ignored its parent. Every one of those four has a declared FAIL in the fixture
oracle that a real run matched, so the registry was right and the detector was wrong
four times out of four. Asking "is the emitted value always this literal" needs
dataflow this does not have; the surviving three ask questions answerable from shape
alone. `test_reachability.py` keeps the oracle check that caught it.

**The other unreachable verdict.** A `warn` band only fires when the assertion has
already failed *and* the warn rule holds (`checklist_runner.py:1228`), so a band the two
rules leave no room for is decoration: the item can only PASS or FAIL, while the registry
promises a middle. `CN-048` *Use Hierarchical Headings and Semantic HTML* carried
`ISSUES_ANY()` with `NOTHING_SERIOUS()` — the standard pair, meaning "an error-class
finding fails this, a warning-class one only warns" — over `parse_html.py`, which grades
a heading skip and a missing `<main>` as `error` and has no warning-class finding at all.
The band could not fire on any page ever built. Unlike an unfailable rule, this is never
a decision, so it is a plain error with nothing to declare.

    python3 tools/audit_reachability.py            # report, exit 1 on any mismatch
    python3 tools/audit_reachability.py --verbose  # show every proof, declared or not
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
SCRIPTS = os.path.join(SKILL_DIR, "scripts")
REGISTRY = os.path.join(SKILL_DIR, "resources", "config", "checklist.json")
SHAPES = os.path.join(SKILL_DIR, "resources", "references",
                      "script-output-shapes.md")

sys.path.insert(0, HERE)
# Imported rather than restated. A second copy of "is this path one the probe has
# seen", or of "which severities can this script say", would drift from the one the
# assertion audit uses, and then the two tools would disagree about the same field
# while both reported green.
from audit_assertions import (SEVERITY_ALIAS, path_is_probed,  # noqa: E402
                              probed_paths, severity_literals)

# Every mechanism this tool can prove. A declaration naming anything else is an
# error rather than an exemption: the vocabulary is closed so that "why" cannot
# quietly become a free-text field nobody checks.
MECHANISMS = ("warn_complement", "path_never_emitted", "guarded_by_assertion",
              "severity_vocabulary")

# Complementary comparison pairs. `gte 90` with `warn lt 90` covers the number line,
# so no value is left for FAIL.
COMPLEMENTS = (("gte", "lt"), ("gt", "lte"), ("lte", "gt"), ("lt", "gte"))

from scope_line import print_scope  # noqa: E402

# What a passing run establishes, and what it does not (openspec/specs/governance/ GOV-6).
ESTABLISHES = (
    "no rule this tool can prove unable to report FAIL is left undeclared, every "
    "cannot_fail declaration still has the proof it names, and no warn band is left "
    "with no verdict to reach"
)
DOES_NOT_ESTABLISH = (
    "that the rules it proves nothing about can fail, since silence here is the "
    "absence of a proof either way, or that a rule able to fail fails on the right "
    "sites"
)



def script_backed(registry: dict) -> list[dict]:
    """Items answered by a script, with an assertion to be reached."""
    out = []
    for item in registry["items"]:
        check = item.get("check") or {}
        if check.get("script") and isinstance(check.get("assert"), dict):
            out.append(item)
    return out


# --- reading what a script can write ----------------------------------------

class _Sites(ast.NodeVisitor):
    """Every place a script writes a given output key, with the tests guarding it.

    Three spellings are in use across these scripts and all three matter:
    `{"in_body": ...}` in a dict literal, `result["target_keyword"] = ...` by
    subscript, and `results.setdefault("x", ...)`. A tool that saw only the first
    would have cleared `KW-076`, which was written in the second.
    """

    def __init__(self, key: str):
        self.key = key
        self.sites: list[tuple[ast.AST, list[ast.AST], int]] = []
        self.guards: list[ast.AST] = []

    def visit_If(self, node: ast.If) -> None:
        self.guards.append(node.test)
        for child in node.body:
            self.visit(child)
        self.guards.pop()
        # An `else` branch runs when the test is false, so the test does not
        # guarantee anything about what is written there.
        for child in node.orelse:
            self.visit(child)

    def _record(self, value: ast.AST, lineno: int) -> None:
        self.sites.append((value, list(self.guards), lineno))

    def visit_Dict(self, node: ast.Dict) -> None:
        # `**expansion` puts a None in `keys`, which the isinstance below rejects;
        # the two lists are the same length either way.
        for key, value in zip(node.keys, node.values, strict=True):
            if isinstance(key, ast.Constant) and key.value == self.key:
                self._record(value, getattr(value, "lineno", node.lineno))
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            if (isinstance(target, ast.Subscript)
                    and isinstance(target.slice, ast.Constant)
                    and target.slice.value == self.key):
                self._record(node.value, node.lineno)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if (getattr(node.func, "attr", None) == "setdefault" and len(node.args) == 2
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == self.key):
            self._record(node.args[1], node.lineno)
        self.generic_visit(node)


def tree_of(script: str, scripts_dir: str = SCRIPTS) -> ast.Module:
    with open(os.path.join(scripts_dir, script), encoding="utf-8") as f:
        return ast.parse(f.read())


def producing_sites(script: str, key: str, scripts_dir: str = SCRIPTS
                    ) -> list[tuple[ast.AST, list[ast.AST], int]]:
    """Where `key` is written, and what `if` tests were true to get there."""
    finder = _Sites(key)
    finder.visit(tree_of(script, scripts_dir))
    return finder.sites


def mentions_key(script: str, key: str, scripts_dir: str = SCRIPTS) -> bool:
    """Does the key appear anywhere in the script as a string at all?

    Deliberately looser than `producing_sites`: a key written through a helper, a
    dict comprehension or a `**` merge would be missed by the structured search,
    and claiming a field is never emitted when it is would be the worst mistake
    this tool can make. Used only to refuse a claim, never to support one.
    """
    return any(isinstance(node, ast.Constant) and node.value == key
               for node in ast.walk(tree_of(script, scripts_dir)))


def changed_outside_the_scan(script: str, key: str,
                             scripts_dir: str = SCRIPTS) -> bool:
    """Is the field altered in a way `producing_sites` cannot see?

    `result["n"] += 1`, `result["found"].append(...)` and
    `result["missing"][label] = ...` all change what the rule will read while
    leaving the write the scan found — usually an empty initialiser — looking like
    the whole story. Three of the four false positives that retired the
    `constant_value` detector were exactly these. A proof about the value must
    stand down when the value moves somewhere it cannot follow.
    """
    def names_key(node) -> bool:
        return (isinstance(node, ast.Subscript)
                and isinstance(node.slice, ast.Constant) and node.slice.value == key)

    for node in ast.walk(tree_of(script, scripts_dir)):
        if isinstance(node, ast.AugAssign) and names_key(node.target):
            return True
        # A write into the container: `d[key][...] = ...`
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Subscript) and names_key(target.value):
                    return True
        # A mutating method on the container: `d[key].append(...)`
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and names_key(node.func.value)):
            return True
    return False


# --- the four proofs --------------------------------------------------------

def prove_warn_complement(item: dict) -> dict | None:
    """The warn band is the assertion's exact complement, so nothing is left to fail.

    Both rules must be a single condition. A two-sided assertion is not
    complemented by a one-sided band: `gte 90` with `lte 100`, warned by `lt 90`,
    leaves 101 and up failing both, and reading only the `gte`/`lt` pair would call
    a live rule unfailable — the worst mistake here, because the repair for one is
    a written declaration that the other must never receive.

    A `value_map` pair must also read the same field, and the assertion must map at
    least one value to `fail`. For a failable pair, this proof fires when the set of
    assertion-fail values is a subset of the band's pass values; `dead_warn_bands`
    fires when those sets are disjoint. At most one can fire, and neither fires when
    the sets partially overlap.
    """
    check = item["check"]
    rule, warn = check["assert"], check.get("warn")
    if (not isinstance(warn, dict) or rule.get("path") != warn.get("path")
            or rule.get("field") != warn.get("field")):
        return None
    if (len(set(rule) - {"field", "path"}) != 1
            or len(set(warn) - {"field", "path"}) != 1):
        return None
    for left, right in COMPLEMENTS:
        if left in rule and right in warn and rule[left] == warn[right]:
            return {"mechanism": "warn_complement",
                    "evidence": f"assert {left} {rule[left]} / warn {right} "
                                f"{warn[right]} on {rule['path']}"}
    for left, right in (("falsy", "truthy"), ("truthy", "falsy")):
        if rule.get(left) is True and warn.get(right) is True:
            return {"mechanism": "warn_complement",
                    "evidence": f"assert {left} true / warn {right} true "
                                f"on {rule['path']}"}
    if isinstance(rule.get("value_map"), dict) and isinstance(
            warn.get("value_map"), dict):
        assertion_fails = {value for value, verdict in rule["value_map"].items()
                           if verdict == "fail"}
        warn_passes = {value for value, verdict in warn["value_map"].items()
                       if verdict == "pass"}
        if assertion_fails and assertion_fails <= warn_passes:
            return {"mechanism": "warn_complement",
                    "evidence": "every value mapped fail by the assertion is mapped "
                                f"pass by the warn value_map on {rule['path']}"}
    return None


def prove_path_never_emitted(item: dict, shapes: dict,
                             scripts_dir: str = SCRIPTS) -> dict | None:
    """No run of the script writes the field, so every verdict is NO_DATA.

    Two independent sources have to agree: the machine-probed shapes reference has
    never seen the path, **and** the key appears nowhere in the script's source.
    One alone is not enough in either direction — a probe run without a credential
    is missing fields the script writes perfectly well, which is why
    `safe_browsing.threats` is not this and must not be reported as this.
    """
    check = item["check"]
    script, path = check["script"], check["assert"].get("path")
    if not path:
        return None
    known = shapes.get(script)
    if known is None or path_is_probed(path, known):
        return None
    key = path.split(".")[-1]
    if mentions_key(script, key, scripts_dir):
        return None
    return {"mechanism": "path_never_emitted",
            "evidence": f"{script} never writes {key!r}, and no probe of it has "
                        f"reported {path!r}"}


def prove_guarded_by_assertion(item: dict, scripts_dir: str = SCRIPTS) -> dict | None:
    """The field is written only under a test that is the assertion itself.

    `if target_kw: result["target_keyword"] = target_kw` against `truthy` — the
    value is emitted exactly when it would pass and withheld exactly when it would
    fail. Narrow on purpose: the guard has to be the same expression as the value,
    so `if args.keyword is not None:` around `"in_body": occurrences > 0` — a guard
    about whether the input arrived, wrapping a value that can still be False — is
    not this, and is the shape KW-076 was repaired into.

    Only single-segment paths. The scan matches a key by name, and a dotted path's
    last segment can belong to a different dict entirely — `header_values.
    strict-transport-security` matched a static table of header descriptions, which
    is how the retired fourth detector produced its fourth wrong answer.
    """
    rule = item["check"]["assert"]
    path = rule.get("path")
    if not path or "." in path:
        return None
    if set(rule) - {"path"} != {"truthy"} or rule["truthy"] is not True:
        return None
    if changed_outside_the_scan(item["check"]["script"], path, scripts_dir):
        return None
    sites = producing_sites(item["check"]["script"], path, scripts_dir)
    if not sites:
        return None
    for value, guards, _line in sites:
        # Two identical expressions are the same value only if reading them twice
        # means the same thing. `if obj.pop(): result["k"] = obj.pop()` dumps
        # identically and returns two different things, so a call anywhere in the
        # compared expression ends the proof. KW-076's real shape is a bare name.
        if any(isinstance(n, ast.Call) for n in ast.walk(value)):
            return None
        shape = ast.dump(value)
        if not any(ast.dump(test) == shape for test in guards):
            return None
    return {"mechanism": "guarded_by_assertion",
            "evidence": f"{item['check']['script']} writes {path!r} only under a "
                        f"test that is the value itself, at line(s) "
                        f"{', '.join(str(s[2]) for s in sites)}"}


def prove_severity_vocabulary(item: dict, scripts_dir: str = SCRIPTS) -> dict | None:
    """The warn band refuses severities the script has no word for, so FAIL is dead.

    A `none_severity` assertion fails when an issue carries one of the severities it
    grades. The band is then consulted, and FAIL arrives only if the band fails too —
    so **FAIL needs an issue graded at something the band refuses.** A script that
    cannot say any of those words stops at WARN on every site there will ever be.

    This is the mirror of `dead_warn_bands`' severity case below and not the same
    check: there the band can never fire, here it can never *not* fire. Both read the
    same two sets and neither implies the other.

    Three conditions, and each rules out a way of being wrong:

      * both rules grade the same path, or they are two measurements and this says
        nothing about either — `CI-014` warns on `total_hops` while asserting
        `has_loop`;
      * the script's vocabulary is non-empty. A script that says no severity at all
        cannot fail the assertion either, which is a different shape with a different
        repair, and claiming it here would put two findings under one word;
      * the assertion is failable — the vocabulary contains something it grades. An
        item that can only ever PASS is again not this.

    The vocabulary comes from `severity_literals`, which reads the whole file. That
    matters more than it looks: `cache_compression_checker.py` builds its issues in
    `_check_url` and re-emits them in `audit` as `{**item, "url": ...}`, three hops
    from the returned list, so anything reading only the function that returns
    `issues` sees no severity at all. A reviewer handed exactly that file read the
    unpack as an upstream producer and concluded the opposite. Whole file, always.
    """
    check = item["check"]
    rule, warn = check["assert"], check.get("warn")
    if not isinstance(warn, dict):
        return None
    if "none_severity" not in rule or "none_severity" not in warn:
        return None
    if rule.get("path") != warn.get("path"):
        return None

    def norm(names) -> set[str]:
        return {SEVERITY_ALIAS.get(n.lower(), n.lower()) for n in names}

    emits = severity_literals(check["script"], scripts_dir)
    graded, refused = norm(rule["none_severity"]), norm(warn["none_severity"])
    if not emits or not (emits & graded) or (emits & refused):
        return None
    return {"mechanism": "severity_vocabulary",
            "evidence": f"{check['script']} can only say "
                        f"{'/'.join(sorted(emits))}; FAIL needs "
                        f"{'/'.join(sorted(refused))}, which the band refuses and "
                        f"the script never writes"}


# When is there no value that fails the assertion and satisfies the warn rule?
# Only same-direction pairs on one path can be empty: `gte 90` with `warn lt 90`
# leaves everything below the threshold to WARN, which is the complement case
# above. Read `A` as the assertion's bound and `B` as the band's.
EMPTY_BAND = {
    ("lte", "lte"): lambda a, b: b <= a,
    ("lte", "lt"): lambda a, b: b <= a,
    ("lt", "lt"): lambda a, b: b <= a,
    ("lt", "lte"): lambda a, b: b < a,
    ("gte", "gte"): lambda a, b: b >= a,
    ("gte", "gt"): lambda a, b: b >= a,
    ("gt", "gt"): lambda a, b: b >= a,
    ("gt", "gte"): lambda a, b: b > a,
}


def dead_warn_bands(registry_path: str = REGISTRY,
                    scripts_dir: str = SCRIPTS) -> list[dict]:
    """Warn bands no value can land in.

    A band fires only when the assertion has already failed and the warn rule then
    holds, so a pair that leaves no room between them promises a middle verdict the
    item can never reach. Three shapes are decidable without knowing anything about
    the site: a numeric band on the wrong side of its own assertion, a `value_map`
    pair with no assertion-fail/band-pass value, and a severity window over a script
    whose vocabulary has nothing to put in it.

    Bands over a *different* path than the assertion — `has_loop` failing while
    `total_hops` warns — are two measurements, and whether they can disagree is a
    question about the script, not about the rules. Not claimed.
    """
    with open(registry_path, encoding="utf-8") as f:
        registry = json.load(f)
    dead = []
    for item in registry["items"]:
        check = item.get("check") or {}
        rule, warn = check.get("assert"), check.get("warn")
        if not (isinstance(rule, dict) and isinstance(warn, dict)):
            continue
        if rule.get("path") != warn.get("path"):
            continue
        for (left, right), empty in EMPTY_BAND.items():
            if left in rule and right in warn and empty(rule[left], warn[right]):
                dead.append({"id": item["id"], "script": check.get("script"),
                             "detail": f"assert {left} {rule[left]} leaves "
                                       f"{right} {warn[right]} nothing to warn about "
                                       f"on {rule['path']}"})
        if (rule.get("field") == warn.get("field")
                and isinstance(rule.get("value_map"), dict)
                and isinstance(warn.get("value_map"), dict)):
            assertion_fails = {value for value, verdict in rule["value_map"].items()
                               if verdict == "fail"}
            warn_passes = {value for value, verdict in warn["value_map"].items()
                           if verdict == "pass"}
            if not (assertion_fails & warn_passes):
                dead.append({"id": item["id"], "script": check.get("script"),
                             "detail": "assert/warn value_map share no value that "
                                       "fails the assertion and passes the band on "
                                       f"{rule['path']}"})
        if "none_severity" in rule and "none_severity" in warn:
            def norm(names):
                return {SEVERITY_ALIAS.get(n.lower(), n.lower()) for n in names}
            window = norm(rule["none_severity"]) - norm(warn["none_severity"])
            try:
                emits = severity_literals(check["script"], scripts_dir)
            except (OSError, SyntaxError):
                continue
            if not window:
                dead.append({"id": item["id"], "script": check["script"],
                             "detail": "the warn rule asks for at least as much as "
                                       "the assertion, so nothing falls between them"})
            elif not (window & emits):
                dead.append({"id": item["id"], "script": check["script"],
                             "detail": f"the band is {'/'.join(sorted(window))} and "
                                       f"{check['script']} only ever says "
                                       f"{'/'.join(sorted(emits)) or 'nothing'}"})
    return dead


def proofs(registry_path: str = REGISTRY, shapes_path: str = SHAPES,
           scripts_dir: str = SCRIPTS) -> dict[str, dict]:
    """Every item this tool can prove unable to report FAIL, by item id."""
    with open(registry_path, encoding="utf-8") as f:
        registry = json.load(f)
    shapes = probed_paths(shapes_path)
    found = {}
    for item in script_backed(registry):
        for prove in (lambda i: prove_warn_complement(i),
                      lambda i: prove_path_never_emitted(i, shapes, scripts_dir),
                      lambda i: prove_guarded_by_assertion(i, scripts_dir),
                      lambda i: prove_severity_vocabulary(i, scripts_dir)):
            try:
                hit = prove(item)
            except (OSError, SyntaxError) as exc:
                hit = {"mechanism": "unreadable", "evidence": str(exc)}
            if hit:
                found[item["id"]] = dict(hit, id=item["id"],
                                         script=item["check"]["script"],
                                         path=item["check"]["assert"].get("path"))
                break
    return found


def audit(registry_path: str = REGISTRY, shapes_path: str = SHAPES,
          scripts_dir: str = SCRIPTS) -> list[dict]:
    """Every disagreement between what the code proves and what the registry says."""
    with open(registry_path, encoding="utf-8") as f:
        registry = json.load(f)
    proven = proofs(registry_path, shapes_path, scripts_dir)
    findings = [{"id": row["id"], "kind": "dead warn band", "detail": row["detail"]}
                for row in dead_warn_bands(registry_path, scripts_dir)]
    for item in registry["items"]:
        declared = ((item.get("check") or {}).get("cannot_fail") or {})
        hit = proven.get(item["id"])
        if declared and not isinstance(declared, dict):
            findings.append({"id": item["id"], "kind": "malformed",
                             "detail": "cannot_fail must be an object with a "
                                       "mechanism and a why"})
            continue
        if declared and declared.get("mechanism") not in MECHANISMS:
            findings.append({"id": item["id"], "kind": "unknown mechanism",
                             "detail": f"{declared.get('mechanism')!r} is not one of "
                                       f"{', '.join(MECHANISMS)}"})
            continue
        if declared and not (declared.get("why") or "").strip():
            findings.append({"id": item["id"], "kind": "unexplained",
                             "detail": "a declaration without a reason is an "
                                       "exemption, not a decision"})
            continue
        if hit and not declared:
            findings.append({"id": item["id"], "kind": "undeclared",
                             "detail": f"{hit['mechanism']}: {hit['evidence']}"})
        elif declared and not hit:
            findings.append({"id": item["id"], "kind": "stale",
                             "detail": f"declared {declared['mechanism']}, and "
                                       f"nothing proves this rule cannot fail any "
                                       f"more — drop the declaration"})
        elif hit and declared and hit["mechanism"] != declared["mechanism"]:
            findings.append({"id": item["id"], "kind": "wrong mechanism",
                             "detail": f"declared {declared['mechanism']}, proved "
                                       f"{hit['mechanism']}: {hit['evidence']}"})
    return findings


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--registry", default=REGISTRY)
    ap.add_argument("--shapes", default=SHAPES)
    ap.add_argument("--scripts", default=SCRIPTS,
                    help="read the answering scripts from here instead of the "
                         "shipped ones — used to re-run a proof against an older "
                         "tree")
    ap.add_argument("--verbose", action="store_true",
                    help="list every rule proved unable to fail")
    a = ap.parse_args()

    with open(a.registry, encoding="utf-8") as f:
        registry = json.load(f)
    items = script_backed(registry)
    banded = [i for i in registry["items"] if (i.get("check") or {}).get("warn")]
    proven = proofs(a.registry, a.shapes, a.scripts)
    findings = audit(a.registry, a.shapes, a.scripts)

    if a.verbose:
        for row in sorted(proven.values(), key=lambda r: r["id"]):
            print(f"  {row['id']:9}{row['script']:28}{row['mechanism']:22}"
                  f"{row['evidence']}")

    print(f"\n{len(items)} script-backed assertion(s); {len(proven)} proved unable to "
          f"report FAIL, {len(findings)} disagreeing with the registry")
    print(f"the other {len(items) - len(proven)} are not claimed either way: no "
          f"detector here proves them reachable")
    print(f"{len(banded)} warn band(s) audited for a middle verdict nothing reaches")
    for f_ in findings:
        print(f"  {f_['id']} [{f_['kind']}] {f_['detail']}", file=sys.stderr)
    if findings:
        print("\nA rule that cannot fail reports PASS for every site, and a warn band "
              "nothing can reach promises a middle verdict the item never returns. If "
              "that is the defect it looks like, repair the rule or the script. If an "
              "unfailable rule is deliberate, record it in CANNOT_FAIL in "
              "build_checklist.py with the mechanism this tool proved and a reason a "
              "reader can check. A dead warn band is never deliberate.",
              file=sys.stderr)
    if findings:
        return 1
    print_scope(ESTABLISHES, DOES_NOT_ESTABLISH)
    return 0


if __name__ == "__main__":
    sys.exit(main())
