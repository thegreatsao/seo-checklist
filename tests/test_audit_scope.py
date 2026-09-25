"""`openspec/specs/governance/` GOV-6: a passing audit says what it established and what
it did not.

Every `tools/audit_*.py` answers one narrow question, and a green one is read as "the
registry is correct" unless its output says which question it was. Until 0.125.0 one of
the ten said so on a pass — `audit_reachability.py`, "the other 143 are not claimed
either way" — and `audit_item_semantics.py` printed `OK`.

The contract, per audit: two module-level strings, `ESTABLISHES` and
`DOES_NOT_ESTABLISH`, and a passing run whose last two lines are those strings behind
`establishes: ` and `does not establish: `. Last, because a CI log is read from the
bottom, and a disclaimer above forty lines of counts is one nobody reaches.

What no test here can hold is GOV-6's second scenario: that a reader who sees the line
does not take a green audit for a right threshold anyway.
"""
from __future__ import annotations

import ast
import contextlib
import glob
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "skills", "seo-checklist", "tools")

import harness  # noqa: E402
# The module, not the class: a TestCase imported into this namespace would be
# collected and run a second time from here.
import test_registry  # noqa: E402

ESTABLISHES = "establishes: "
DISCLAIMS = "does not establish: "


def audits() -> list[str]:
    return sorted(os.path.basename(path)
                  for path in glob.glob(os.path.join(TOOLS, "audit_*.py")))


def scope_of(name: str) -> dict[str, str]:
    """The two strings, read from the source rather than imported, so a module that
    fails to import still says which half it is missing."""
    with open(os.path.join(TOOLS, name), encoding="utf-8") as stream:
        tree = ast.parse(stream.read())
    found = {}
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id in ("ESTABLISHES", "DOES_NOT_ESTABLISH")
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)):
            found[node.targets[0].id] = node.value.value
    return found


def closing_lines(stdout: str) -> list[str]:
    lines = [line.rstrip() for line in stdout.splitlines() if line.strip()]
    return lines[-2:]


def expected_close(name: str) -> list[str]:
    scope = scope_of(name)
    return [ESTABLISHES + scope.get("ESTABLISHES", "<missing>"),
            DISCLAIMS + scope.get("DOES_NOT_ESTABLISH", "<missing>")]


def gated() -> dict[str, list[str]]:
    """The audits the workflow runs, with the arguments it runs them with — taken from
    the class that already holds that list against `ci.yml`."""
    return {name: list(args)
            for name, args in test_registry.EveryToolGateRunsHereToo.GATES
            if name.startswith("audit_")}


class EveryAuditDeclaresItsScope(unittest.TestCase):

    def test_the_population_is_the_audits_on_disk(self):
        """Derived by globbing, so an audit added tomorrow is in scope the day it
        lands. The four GOV-6 names by purpose are pinned so the glob cannot go
        vacuous."""
        found = audits()
        for name in ("audit_assertions.py", "audit_reachability.py",
                     "audit_item_semantics.py", "audit_thresholds.py"):
            self.assertIn(name, found)

    def test_every_audit_states_both_halves(self):
        for name in audits():
            with self.subTest(audit=name):
                scope = scope_of(name)
                for key in ("ESTABLISHES", "DOES_NOT_ESTABLISH"):
                    text = scope.get(key, "")
                    self.assertTrue(
                        text.strip(),
                        f"tools/{name} has no module-level string {key}")
                    self.assertNotIn("\n", text,
                                     f"tools/{name} {key} is printed as one line")
                self.assertNotEqual(scope.get("ESTABLISHES"),
                                    scope.get("DOES_NOT_ESTABLISH"))

    def test_no_two_audits_share_a_sentence(self):
        """A sentence copied from one audit to the next is boilerplate, and boilerplate
        is the disclaimer nobody reads."""
        seen: dict[str, str] = {}
        for name in audits():
            for text in scope_of(name).values():
                with self.subTest(audit=name, sentence=text[:40]):
                    self.assertNotIn(text, seen,
                                     f"tools/{name} repeats tools/{seen.get(text)}")
                    seen[text] = name


class EveryAuditIsHeardPassing(unittest.TestCase):
    """The printed half. Each audit is run the way something in this repository runs
    it, and a passing run must close on its two lines."""

    # Audits the workflow does not run as a gate, each with the test below that runs
    # it and the reason it is not in `EveryToolGateRunsHereToo.GATES`.
    OUTSIDE_THE_GATES = {
        # Needs a finished run's results; the workflow feeds it `live.json`.
        "audit_score_sensitivity.py":
            "test_the_score_report_closes_on_its_scope",
        # Run in-process by `tests/test_declaration_revisions.py`, and its history
        # walk costs well over a minute; the printed half does not depend on it.
        "audit_declaration_revisions.py":
            "test_the_revision_walk_closes_on_its_scope_when_it_agrees",
    }

    def test_every_audit_is_run_passing_somewhere(self):
        covered = set(gated()) | set(self.OUTSIDE_THE_GATES)
        self.assertEqual(sorted(set(audits()) - covered), [],
                         "an audit nothing here runs, so nothing hears it pass")
        self.assertEqual(sorted(covered - set(audits())), [],
                         "an audit named here that is not on disk")
        self.assertEqual(sorted(set(gated()) & set(self.OUTSIDE_THE_GATES)), [])
        for test in self.OUTSIDE_THE_GATES.values():
            self.assertTrue(hasattr(self, test), f"{test} does not exist")

    def test_every_gated_audit_closes_on_its_scope(self):
        for name, args in gated().items():
            with self.subTest(audit=name):
                proc = harness.spawn([sys.executable, os.path.join(TOOLS, name), *args])
                self.assertEqual(proc.returncode, 0,
                                 f"tools/{name} failed, so its close is not a pass's")
                self.assertEqual(closing_lines(proc.stdout), expected_close(name))

    def test_the_score_report_closes_on_its_scope(self):
        name = "audit_score_sensitivity.py"
        items = [{"id": "A-1", "status": "PASS", "severity": "critical",
                  "effort": "low"},
                 {"id": "A-2", "status": "FAIL", "severity": "high",
                  "effort": "medium"},
                 {"id": "A-3", "status": "WARN", "severity": "low", "effort": "high"}]
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "run.json")
            with open(path, "w", encoding="utf-8") as stream:
                json.dump({"items": items}, stream)
            proc = harness.spawn([sys.executable, os.path.join(TOOLS, name), path])
        self.assertEqual(proc.returncode, 0, proc.stdout[-2000:] + proc.stderr[-2000:])
        self.assertEqual(closing_lines(proc.stdout), expected_close(name))

    def test_the_revision_walk_closes_on_its_scope_when_it_agrees(self):
        """The walk is replaced by an agreeing one: what is under test is what `main`
        prints when the ledgers agree, not the ledgers."""
        name = "audit_declaration_revisions.py"
        sys.path.insert(0, TOOLS)
        try:
            import audit_declaration_revisions as revisions
        finally:
            sys.path.remove(TOOLS)
        out = io.StringIO()
        with mock.patch.object(revisions, "states", return_value=[("x", {}, {})]), \
                mock.patch.object(revisions, "observed", return_value=[]), \
                mock.patch.object(revisions, "recorded", return_value=[]), \
                mock.patch.object(revisions, "watched_paths", return_value=("m",)), \
                mock.patch.object(revisions, "stamp_disagreement", return_value=[]), \
                mock.patch.object(revisions, "disagreements", return_value=[]), \
                mock.patch.object(sys, "argv", [name, "--check"]), \
                contextlib.redirect_stdout(out):
            code = revisions.main()
        self.assertEqual(code, 0)
        self.assertEqual(closing_lines(out.getvalue()), expected_close(name))


if __name__ == "__main__":
    unittest.main()
