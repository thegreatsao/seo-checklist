"""`openspec/specs/registry/` REG-8 — absence of data is not a verdict — and its warrant.

`missing_is: pass | fail` says the absence of a field is itself the answer. The requirement
permits it "only where" that is true, and nothing read whether it was. Measured on
2 October 2026 (`local/gov3/measure_missing_is.py`, outside git), over the three
declarations the registry carried:

* **every one of them passed on an empty output.** A script that reported nothing — the
  checker not looking — was read as the site being clean, which is the sentence REG-8
  exists to forbid;
* two of the three, CI-004 and MS-031, never fired on a real page at all: `parse_html.py`
  emits `meta_robots` and `meta_keywords` as `None` when the tag is absent, the operator
  answers over that `None`, and the declaration was reachable only when the key itself
  had gone — which is how MS-031 once passed on every site ever audited, for a release in
  which the script did not emit the key;
* the third, GO-143, reads `incomplete_nodes_by_type.WebSite`, a map with one entry per
  schema type present, where an absent entry really is "this page has no such node" — and
  passed just the same when the map was not there.

So the warrant has a shape and the shape is checked. Absence is an answer when the thing
that would have carried the field is itself present: the declaration is honoured only when
every segment of the path above the last resolves, and it may not be made on a path of one
segment, because a key missing from the root of a script's output is the script not
reporting. Each declaration that remains is run here against its script, both ways.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(ROOT, "skills", "seo-checklist")
sys.path.insert(0, os.path.join(SKILL, "scripts"))
sys.path.insert(0, os.path.join(SKILL, "tools"))

import build_checklist  # noqa: E402
import checklist_runner as runner  # noqa: E402
import parse_html  # noqa: E402
import schema_required_props  # noqa: E402

with open(os.path.join(SKILL, "resources", "config", "checklist.json"),
          encoding="utf-8") as _stream:
    ITEMS = {item["id"]: item for item in json.load(_stream)["items"]}


def declarations(node, where: str = ""):
    """(where, rule) for every rule under `node` that declares `missing_is`."""
    if isinstance(node, dict):
        if "missing_is" in node:
            yield where, node
        for key, value in node.items():
            yield from declarations(value, f"{where}.{key}" if where else key)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from declarations(value, f"{where}[{index}]")


DECLARED = {(item_id, where): rule
            for item_id, item in ITEMS.items()
            for where, rule in declarations(item.get("check") or {})}


def page(head: str = "") -> str:
    handle = tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8")
    with handle:
        handle.write('<!doctype html><html lang="en"><head><meta charset="utf-8">'
                     f"<title>A page</title>{head}</head><body><h1>One</h1></body></html>")
    return handle.name


def schema_output(*nodes: dict) -> dict:
    path = page("".join('<script type="application/ld+json">' + json.dumps(node) + "</script>"
                        for node in nodes))
    try:
        documents, meta = schema_required_props.extract_schema_documents(path)
        return schema_required_props.validate_schema_required_props(
            documents, None, meta.get("invalid_blocks"))
    finally:
        os.unlink(path)


ORGANISATION = {"@context": "https://schema.org", "@type": "Organization",
                "name": "Example", "url": "https://example.test/"}
WEBSITE = {"@context": "https://schema.org", "@type": "WebSite",
           "name": "Example", "url": "https://example.test/"}


class AbsenceAnswersOnlyUnderSomethingPresent(unittest.TestCase):
    """The evaluator. `missing_is` over `a.b` speaks when `a` is there and `b` is not."""

    RULE = {"path": "by_type.WebSite", "eq": 0, "missing_is": "pass"}

    def test_the_last_key_absent_under_a_present_parent_is_the_declared_answer(self):
        self.assertIs(runner.evaluate(self.RULE, {"by_type": {}})[0], True)
        self.assertIs(runner.evaluate(dict(self.RULE, missing_is="fail"),
                                      {"by_type": {"Organization": 0}})[0], False)

    def test_an_absent_parent_is_undecided(self):
        for data in ({}, {"other": 1}, {"__error__": "boom"}):
            with self.subTest(data=data):
                passed, evidence = runner.evaluate(self.RULE, data)
                self.assertIsNone(passed, evidence)
                self.assertIn("by_type", evidence)

    def test_a_parent_that_cannot_carry_the_key_is_undecided(self):
        for parent in (None, [], "text", 0):
            with self.subTest(parent=parent):
                self.assertIsNone(runner.evaluate(self.RULE, {"by_type": parent})[0])

    def test_a_deeper_path_needs_every_segment_above_the_last(self):
        rule = {"path": "a.b.c", "eq": 0, "missing_is": "pass"}
        self.assertIs(runner.evaluate(rule, {"a": {"b": {}}})[0], True)
        self.assertIsNone(runner.evaluate(rule, {"a": {}})[0])
        self.assertIsNone(runner.evaluate(rule, {})[0])

    def test_a_present_value_is_still_judged_by_the_operator(self):
        self.assertIs(runner.evaluate(self.RULE, {"by_type": {"WebSite": 0}})[0], True)
        self.assertIs(runner.evaluate(self.RULE, {"by_type": {"WebSite": 2}})[0], False)


class TheBuildRefusesAbsenceAtTheRoot(unittest.TestCase):

    def item(self, **check) -> dict:
        return {"id": "ZZ-999", "check": {"script": "parse_html.py", **check}}

    def test_a_declaration_on_a_path_of_one_segment_is_a_problem_wherever_it_sits(self):
        root = {"path": "meta_robots", "falsy": True, "missing_is": "pass"}
        for where in ("assert", "warn", "applies_when"):
            with self.subTest(where=where):
                problems = build_checklist.missing_is_problems([self.item(**{where: root})])
                self.assertEqual(len(problems), 1)
                self.assertIn("ZZ-999", problems[0])
                self.assertIn("meta_robots", problems[0])

    def test_a_declaration_under_a_parent_is_not(self):
        nested = {"path": "by_type.WebSite", "eq": 0, "missing_is": "pass"}
        self.assertEqual(build_checklist.missing_is_problems([self.item(**{"assert": nested})]), [])
        self.assertEqual(build_checklist.missing_is_problems(
            [self.item(**{"assert": {"path": "meta_robots", "falsy": True}})]), [])

    def test_the_build_consults_it(self):
        with mock.patch.object(build_checklist, "missing_is_problems",
                               return_value=["ZZ-999 declares absence at the root"]), \
                mock.patch.object(sys, "argv", ["build_checklist.py", "--check"]):
            self.assertEqual(build_checklist.main(), 1)

    def test_the_shipped_registry_has_none(self):
        self.assertEqual(build_checklist.missing_is_problems(list(ITEMS.values())), [])
        for (item_id, where), rule in DECLARED.items():
            with self.subTest(item=item_id, where=where):
                self.assertGreater(len(rule["path"].split(".")), 1)


class EveryDeclarationIsRunAgainstItsScript(unittest.TestCase):
    """A declaration nobody ran is a claim about a script's output made from memory.

    `PROVEN` names the test below that runs each one; a declaration added to the registry
    without a proof here fails by name, and so does a proof for one that is gone."""

    PROVEN = {("GO-143", "assert"): "test_go_143_an_absent_website_entry_is_a_page_without_one"}

    def test_every_declaration_has_a_proof_and_every_proof_a_declaration(self):
        self.assertEqual(set(DECLARED), set(self.PROVEN))
        for name in self.PROVEN.values():
            self.assertTrue(callable(getattr(self, name, None)), name)

    def test_go_143_an_absent_website_entry_is_a_page_without_one(self):
        rule = ITEMS["GO-143"]["check"]["assert"]
        self.assertEqual(rule["path"], "incomplete_nodes_by_type.WebSite")
        # The script looked and the page has no WebSite node: the map is there, the
        # entry is not, and that is the answer.
        without = schema_output(ORGANISATION)
        self.assertIsInstance(without["incomplete_nodes_by_type"], dict)
        self.assertNotIn("WebSite", without["incomplete_nodes_by_type"])
        passed, evidence = runner.evaluate(rule, without)
        self.assertIs(passed, True)
        self.assertIn("absent", evidence)
        # The map is emitted on a page with no structured data at all, so its absence
        # can only mean the script did not report.
        self.assertEqual(schema_output()["incomplete_nodes_by_type"], {})
        # With the node present the entry is, and the operator decides.
        self.assertIs(runner.evaluate(rule, schema_output(WEBSITE))[0], True)
        incomplete = schema_output({"@context": "https://schema.org", "@type": "WebSite"})
        self.assertGreater(incomplete["incomplete_nodes_by_type"]["WebSite"], 0)
        self.assertIs(runner.evaluate(rule, incomplete)[0], False)
        # The checker not looking is not the site being clean.
        for silent in ({}, {"__error__": "boom"}, {"schema_nodes": 1}):
            with self.subTest(output=silent):
                self.assertIsNone(runner.evaluate(rule, silent)[0])


class TwoItemsThatNeverNeededIt(unittest.TestCase):
    """CI-004 and MS-031 declared `missing_is: pass` over a key the script always emits.

    The tag being absent is reported as `None` and judged by the operator; the declaration
    spoke only when the key was gone, which is the script not reporting."""

    def parsed(self, head: str = "") -> dict:
        path = page(head)
        try:
            with open(path, encoding="utf-8") as stream:
                return parse_html.parse_html(stream.read(), "https://example.test/")
        finally:
            os.unlink(path)

    def test_neither_declares_it(self):
        for item_id in ("CI-004", "MS-031"):
            with self.subTest(item=item_id):
                self.assertNotIn("missing_is", ITEMS[item_id]["check"]["assert"])

    def test_a_page_without_the_tag_still_passes_through_the_operator(self):
        out = self.parsed()
        for item_id, key in (("CI-004", "meta_robots"), ("MS-031", "meta_keywords")):
            with self.subTest(item=item_id):
                self.assertIn(key, out)
                self.assertIsNone(out[key])
                passed, evidence = runner.evaluate(ITEMS[item_id]["check"]["assert"], out)
                self.assertIs(passed, True)
                self.assertNotIn("absent", evidence)

    def test_a_page_with_the_tag_still_fails(self):
        out = self.parsed('<meta name="robots" content="noindex">'
                          '<meta name="keywords" content="seo, cheap seo">')
        for item_id in ("CI-004", "MS-031"):
            with self.subTest(item=item_id):
                self.assertIs(runner.evaluate(ITEMS[item_id]["check"]["assert"], out)[0], False)

    def test_an_output_without_the_key_is_undecided(self):
        for item_id in ("CI-004", "MS-031"):
            for silent in ({}, {"__error__": "boom"}, {"title": "A page"}):
                with self.subTest(item=item_id, output=silent):
                    self.assertIsNone(
                        runner.evaluate(ITEMS[item_id]["check"]["assert"], silent)[0])


if __name__ == "__main__":
    unittest.main()
