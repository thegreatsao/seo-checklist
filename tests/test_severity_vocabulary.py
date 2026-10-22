"""EVD-2: findings speak one severity vocabulary, translated in one place.

`SEVERITY_ALIAS` maps the words checkers inherited (`error`, `warning`, `warn`, `info`,
`notice`) onto the registry's four. Until F04 four call sites in the runner each spelled
the translation out, nothing forbade a fifth elsewhere, and a word outside both sets was
passed through: a `none_severity` rule over an issue at `fatal` found no hit and said
`PASS`. Here the translation is one function, read by the source; the words the shipped
checkers write are held to the vocabulary; and a word outside it is caught at grading.
"""
from __future__ import annotations

import ast
import json
import os
import sys
import tempfile
import unittest

from harness import SCRIPTS

sys.path.insert(0, SCRIPTS)
sys.path.insert(0, os.path.join(SCRIPTS, os.pardir, "tools"))
import audit_assertions  # noqa: E402
import checklist_runner as cr  # noqa: E402

REGISTRY = os.path.join(SCRIPTS, os.pardir, "resources", "config", "checklist.json")
FOUR = set(cr.SEVERITIES)


TOOLS = os.path.join(SCRIPTS, os.pardir, "tools")


def sources(*dirs):
    """Every module under `dirs` (the shipped scripts by default), named from the skill."""
    for top in dirs or (SCRIPTS,):
        for root, _, names in os.walk(top):
            for name in sorted(names):
                if name.endswith(".py"):
                    path = os.path.join(root, name)
                    with open(path, encoding="utf-8") as f:
                        yield (os.path.relpath(path, os.path.dirname(SCRIPTS))
                               .replace(os.sep, "/"),
                               ast.parse(f.read()))


def words(node) -> list[str]:
    """The string constants a comparison tests against, inside a tuple or set too."""
    found = []
    for part in [node.left, *node.comparators]:
        for c in ([*part.elts] if isinstance(part, (ast.Tuple, ast.List, ast.Set))
                  else [part]):
            if isinstance(c, ast.Constant) and isinstance(c.value, str):
                found.append(c.value)
    return found


class OnePlaceTranslates(unittest.TestCase):
    """Read over the shipped scripts and `tools/`, whose gates read rule severities too:
    a second translation there makes a gate and the runner disagree about one rule."""

    def test_the_table_is_read_by_one_function(self):
        # `severity_literals` is the gate's census of what a script can say, and passes a
        # word outside the vocabulary through on purpose, so the census sees it; nothing
        # a rule or a report reads goes through it.
        # Every read of the name, a module-level alias (`_A = SEVERITY_ALIAS`) included:
        # one counted only inside functions let the alias carry the table out.
        readers = set()
        for name, tree in sources(SCRIPTS, TOOLS):
            inside = {}
            for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
                for n in ast.walk(fn):
                    inside.setdefault(id(n), fn.name)
            for n in ast.walk(tree):
                if (isinstance(n, ast.Name) and n.id == "SEVERITY_ALIAS"
                        and isinstance(n.ctx, ast.Load)):
                    readers.add(f"{name}:{inside.get(id(n), '<module>')}")
        self.assertEqual(sorted(readers),
                         ["scripts/checklist_runner.py:normal_severity",
                          "tools/audit_assertions.py:severity_literals"])

    def test_a_module_is_named_with_forward_slashes_on_windows(self):
        """Both tests here look modules up by `scripts/…`; Windows's `relpath` answers
        with backslashes, and until 0.176.2 both failed there."""
        from unittest import mock
        relpath = os.path.relpath

        def windows_relpath(path, start):
            return relpath(path, start).replace("/", "\\")

        with mock.patch.object(os.path, "relpath", windows_relpath), \
                mock.patch.object(os, "sep", "\\"):
            self.assertIn("scripts/checklist_runner.py", [name for name, _ in sources(SCRIPTS)])

    def test_no_other_mapping_turns_an_inherited_word_into_one_of_the_four(self):
        """A second table or a second translation, written under any name: a dict
        literal or a `dict(...)` call taking an inherited word to one of the four; a
        branch on an inherited word (`if`, either arm, a ternary, a `match` case) that
        yields one of the four; and, in the runner and
        the report, whose job is to read severities rather than to write them, any
        comparison against an inherited word. A checker comparing its own words to count
        them is not a translation and is not refused."""
        inherited = set(cr.SEVERITY_ALIAS)

        def maps(key, value):
            return key.lower() in inherited and value.lower() in FOUR

        def tests_inherited(test):
            return any(isinstance(c, ast.Compare)
                       and any(w.lower() in inherited for w in words(c))
                       for c in ast.walk(test))

        def yields_four(nodes):
            return any(isinstance(c, ast.Constant) and isinstance(c.value, str)
                       and c.value.lower() in FOUR
                       for n in nodes for c in ast.walk(n))

        found = []
        for name, tree in sources(SCRIPTS, TOOLS):
            for node in ast.walk(tree):
                hit = False
                if isinstance(node, ast.Dict):
                    hit = any(isinstance(k, ast.Constant) and isinstance(v, ast.Constant)
                              and isinstance(k.value, str) and isinstance(v.value, str)
                              and maps(k.value, v.value)
                              for k, v in zip(node.keys, node.values, strict=True))
                elif isinstance(node, ast.Call) and getattr(node.func, "id", "") == "dict":
                    hit = any(k.arg and isinstance(k.value, ast.Constant)
                              and isinstance(k.value.value, str)
                              and maps(k.arg, k.value.value) for k in node.keywords)
                elif isinstance(node, ast.IfExp):
                    hit = tests_inherited(node.test) and yields_four([node.body,
                                                                      node.orelse])
                elif isinstance(node, ast.If):
                    hit = tests_inherited(node.test) and yields_four([*node.body,
                                                                      *node.orelse])
                elif isinstance(node, ast.Match):
                    hit = any(any(isinstance(c, ast.MatchValue)
                                  and isinstance(c.value, ast.Constant)
                                  and isinstance(c.value.value, str)
                                  and c.value.value.lower() in inherited
                                  for c in ast.walk(case.pattern))
                              and yields_four(case.body) for case in node.cases)
                elif (isinstance(node, ast.Compare)
                      and name in ("scripts/checklist_runner.py",
                                   "scripts/checklist_report.py")):
                    hit = any(w.lower() in inherited for w in words(node))
                if hit:
                    found.append(f"{name}:{node.lineno}")
        alias_line = next(f"scripts/checklist_runner.py:{n.lineno}"
                          for n in ast.walk(dict(sources(SCRIPTS))[
                              "scripts/checklist_runner.py"])
                          if isinstance(n, ast.Assign)
                          and any(getattr(t, "id", "") == "SEVERITY_ALIAS"
                                  for t in n.targets))
        self.assertEqual([f for f in found if f != alias_line], [])

    def test_every_word_translates_to_one_of_the_four(self):
        for word in [*cr.SEVERITY_ALIAS, *FOUR, "High", "Warning", "CRITICAL", " info "]:
            with self.subTest(word=word):
                self.assertIn(cr.normal_severity(word), FOUR)
        self.assertIsNone(cr.normal_severity("fatal"))
        self.assertIsNone(cr.normal_severity(None))


class TheCheckersSpeakIt(unittest.TestCase):
    """The checker side of a fifth word: every severity a shipped script writes as a
    literal — in an `issues` element, or through `seo_common.issue` — translates."""

    def test_every_literal_severity_in_the_scripts_translates(self):
        outside = []
        for name, tree in sources():
            for node in ast.walk(tree):
                values = []
                if isinstance(node, ast.Dict):
                    values = [v for k, v in zip(node.keys, node.values, strict=True)
                              if isinstance(k, ast.Constant) and k.value == "severity"]
                elif (isinstance(node, ast.Call) and node.args
                      and getattr(node.func, "id", getattr(node.func, "attr", "")) == "issue"):
                    values = [node.args[0]]
                for v in values:
                    if (isinstance(v, ast.Constant) and isinstance(v.value, str)
                            and cr.normal_severity(v.value) is None):
                        outside.append(f"{name}:{v.lineno} {v.value!r}")
        self.assertEqual(outside, [])

    def test_every_rule_names_a_word_that_translates(self):
        with open(REGISTRY, encoding="utf-8") as f:
            items = json.load(f)["items"]
        outside = [f"{i['id']} {word!r}" for i in items
                   for part in ("assert", "warn")
                   for word in ((i.get("check") or {}).get(part) or {}).get("none_severity", [])
                   if cr.normal_severity(word) is None]
        self.assertEqual(outside, [])

    def test_the_gate_refuses_a_rule_naming_a_word_that_does_not_translate(self):
        """E2-c (F04): the runner drops such a word from the levels it looks for, so a
        rule naming only words like it never fires. `audit_assertions.py` refused one
        only by accident — an `assert` rule sharing no word with its script — and let
        one through beside a real word, or in `warn` position."""
        with open(REGISTRY, encoding="utf-8") as f:
            registry = json.load(f)
        assert_rule = next(r for r in audit_assertions.severity_rules()
                           if r["block"] == "assert")
        for block, words in (("assert", ["critical", "high", "fatal"]),
                             ("warn", ["fatal"])):
            with self.subTest(block=block):
                data = json.loads(json.dumps(registry))
                item = next(i for i in data["items"] if i["id"] == assert_rule["id"])
                item["check"][block] = {"path": assert_rule["path"],
                                        "none_severity": words}
                with tempfile.NamedTemporaryFile("w", suffix=".json",
                                                 delete=False) as f:
                    json.dump(data, f)
                self.addCleanup(os.unlink, f.name)
                refused = [d for d in audit_assertions.audit_severities(f.name)
                           if d["id"] == item["id"] and d["block"] == block]
                self.assertEqual(len(refused), 1, refused)
                self.assertIn("fatal", refused[0]["reason"])


class AFifthWordIsCaught(unittest.TestCase):

    RULE = {"path": "issues", "none_severity": ["critical", "high"]}

    def test_an_issue_at_a_word_outside_the_vocabulary_is_not_a_clean_answer(self):
        ok, evidence = cr.evaluate(self.RULE, {"issues": [
            {"severity": "fatal", "message": "the database is on fire"}]})
        self.assertIsNone(ok, evidence)
        self.assertIn("fatal", evidence)

    def test_an_inherited_word_is_still_read(self):
        ok, _ = cr.evaluate(self.RULE, {"issues": [{"severity": "Error", "message": "x"}]})
        self.assertIs(ok, False)
        ok, _ = cr.evaluate(self.RULE, {"issues": [{"severity": "notice", "message": "x"}]})
        self.assertIs(ok, True)


if __name__ == "__main__":
    unittest.main()
