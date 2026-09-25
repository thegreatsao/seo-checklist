"""`openspec/specs/governance/` GOV-3 for `checklist_runner.py`: every hand-written set
that decides what the runner does is derived from what it describes, or read here.

Until 0.126.0 the census counted sixteen of the runner's sets as named by nothing outside
the code that consumes them. None of the readers below restates a list: each holds a set
against the thing it describes — the registry's own vocabularies, the operator language
`evaluate()` implements, what a script can actually emit, what the classifier does with
each member — so a forgotten entry or a dead one fails here by name. Where the thing
described was a second copy of another set, the copy became a derivation and the reader
holds the source.

Measured before any of it was written (`local/gov3/measure.py`): every relation below held
on the tree as it stood. This is a reader for the next edit, not the repair of a defect.
"""
from __future__ import annotations

import ast
import json
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(ROOT, "skills", "seo-checklist")
SCRIPTS = os.path.join(SKILL, "scripts")
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, os.path.join(SKILL, "tools"))

import checklist_report  # noqa: E402
import checklist_runner as r  # noqa: E402
import seo_common  # noqa: E402

import audit_assertions  # noqa: E402
# The module, not a class out of it: a TestCase imported here would run twice.
import test_registry  # noqa: E402

with open(os.path.join(SKILL, "resources", "config", "checklist.json"),
          encoding="utf-8") as _stream:
    REGISTRY = json.load(_stream)
ITEMS = REGISTRY["items"]
CHECKS = [i["check"] for i in ITEMS if i.get("check")]
REGISTRY_SCRIPTS = sorted({c["script"] for c in CHECKS if c.get("script")})


def row(status: str) -> dict:
    return {"id": "X-1", "title": "x", "category": "c", "category_label": "C",
            "severity": "high", "effort": "low", "status": status, "evidence": "",
            "fix": "f"}


class TheVocabulariesAreTheRegistrys(unittest.TestCase):

    def test_severities_are_the_registrys_in_weight_order(self):
        """One ordered tuple; the rank maps in the runner and the report are
        enumerations of it, and the score's weights must fall along it."""
        self.assertEqual(set(r.SEVERITIES), {i["severity"] for i in ITEMS})
        self.assertEqual(len(r.SEVERITIES), len(set(r.SEVERITIES)))
        self.assertEqual(set(r.SEVERITY_WEIGHT), set(r.SEVERITIES))
        weights = [r.SEVERITY_WEIGHT[s] for s in r.SEVERITIES]
        self.assertEqual(weights, sorted(weights, reverse=True))
        self.assertEqual(len(set(weights)), len(weights), "two severities weigh the same")
        ranks = {s: n for n, s in enumerate(r.SEVERITIES)}
        self.assertEqual(r.SEVERITY_ORDER_KEY, ranks)
        self.assertEqual(checklist_report.SEVERITY_ORDER, ranks)

    def test_verdicts_run_worst_to_best_by_the_credit_the_score_gives(self):
        """`VERDICTS` is what `score()` decides on, in the order its credit rises. The
        two rank maps are read off it; a status outside it earns no score at all."""
        credit = [r.score([row(s)])["seo_score"] for s in r.VERDICTS]
        self.assertEqual(credit, sorted(credit))
        self.assertEqual(len(set(credit)), len(credit))
        for status in (r.NO_DATA, r.MANUAL, r.LLM_PENDING, r.NA):
            with self.subTest(status=status):
                self.assertNotIn(status, r.VERDICTS)
                self.assertIsNone(r.score([row(status)])["seo_score"])
        self.assertEqual(r.VERDICT_RANK, {s: n for n, s in enumerate(r.VERDICTS)})
        # Aggregation takes the worst page, so its rank runs the other way.
        self.assertEqual(sorted(r.STATUS_RANK, key=r.STATUS_RANK.get, reverse=True),
                         list(r.VERDICTS))
        self.assertEqual(set(r.STATUS_RANK), set(r.VERDICTS))

    def test_every_requirement_value_is_decided_once_for_every_gate(self):
        """`check.requires` is a closed vocabulary and three gates partition it. They
        are read off one table keyed by every value the registry uses, so a new value
        is decided there or refused here — the omission a set of its own cannot show."""
        used = {c.get("requires", "fetch") for c in CHECKS}
        self.assertEqual(set(r.REQUIREMENT_GATES), used | {"fetch"})
        for requirement, gates in r.REQUIREMENT_GATES.items():
            with self.subTest(requires=requirement):
                self.assertLessEqual(set(gates),
                                     {"live_site", "outside_world", "page_level"})
        # What each gate holds, stated once more on purpose: moving a value in or out
        # of a gate is a decision about what a run can answer, and it is made twice.
        self.assertEqual(r.NEEDS_A_LIVE_SITE, {"fetch", "crawl", "api"})
        self.assertEqual(r.NEEDS_THE_OUTSIDE_WORLD, {"api", "gsc", "safe_browsing"})
        self.assertEqual(r.PAGE_LEVEL, {"offline", "fetch"})
        self.assertEqual(r.NEEDS_THE_RIGHT_PAGE, r.NEEDS_A_LIVE_SITE | {"offline"})

    def test_measurement_names_every_operator_the_language_has(self):
        """`measurement()` walks `THRESHOLD_OPS` and then the operators that carry no
        threshold. Between them they must name every operator `evaluate()`
        implements, and only those."""
        vocabulary = test_registry.operator_vocabulary()
        self.assertLessEqual(set(r.THRESHOLD_OPS), vocabulary)
        for op in sorted(vocabulary):
            with self.subTest(op=op):
                out = r.measurement({"path": "absent", op: 1}, {})
                self.assertEqual(out.get("op"), op)
                self.assertEqual("want" in out, op in r.THRESHOLD_OPS)

    def test_every_script_failure_kind_is_under_the_error_kind_gate(self):
        """`tools/audit_error_kinds.py` holds `ERROR_KINDS` against every kind the
        source assigns, both directions. `ERROR_KINDS` is `FAILURE_LABEL`'s keys plus
        three named kinds, and this is what makes that gate `FAILURE_LABEL`'s reader."""
        others = (r.SITE_UNREADABLE, r.SERVICE_REFUSED, r.BAD_INPUT)
        self.assertEqual(r.ERROR_KINDS, tuple(r.FAILURE_LABEL) + others)
        self.assertFalse(set(r.FAILURE_LABEL) & set(others))
        for kind, label in r.FAILURE_LABEL.items():
            with self.subTest(kind=kind):
                self.assertEqual(r.kind_label(kind), label)


class WhatScriptsEmitIsCovered(unittest.TestCase):

    def test_every_severity_word_a_script_emits_is_the_registrys_or_aliased(self):
        """Read without the alias, so the table is held against the raw words. The
        direction that matters is the omission: a script saying `fatal` would pass
        every `none_severity` rule on every site. `notice` and `warn` have no literal
        emitter today and stay, because a script passing a service's own severity
        through is invisible to a literal scan."""
        raw: set[str] = set()
        with mock.patch.object(audit_assertions, "SEVERITY_ALIAS", {}):
            for script in REGISTRY_SCRIPTS:
                raw |= audit_assertions.severity_literals(script)
        self.assertTrue(raw, "the scan found no severity at all; it is blind")
        unaliased = sorted(raw - set(r.SEVERITIES) - set(r.SEVERITY_ALIAS))
        self.assertEqual(unaliased, [], "a script emits a severity nothing maps")
        self.assertLessEqual(set(r.SEVERITY_ALIAS.values()), set(r.SEVERITIES))
        self.assertFalse(set(r.SEVERITY_ALIAS) & set(r.SEVERITIES))

    def test_the_slow_scripts_are_scripts_the_registry_runs(self):
        self.assertEqual(len(r.SLOW_FIRST), len(set(r.SLOW_FIRST)))
        self.assertEqual(sorted(set(r.SLOW_FIRST) - set(REGISTRY_SCRIPTS)), [],
                         "scheduled first, and nothing runs it")

    def test_every_unread_key_is_one_a_script_writes(self):
        """The singular keys a script writes when its measurement did not happen. The
        plural per-URL lists are deliberately not among them — see the comment above
        the set."""
        written: set[str] = set()
        for name in os.listdir(SCRIPTS):
            if not name.endswith(".py") or name == "checklist_runner.py":
                continue
            with open(os.path.join(SCRIPTS, name), encoding="utf-8") as stream:
                tree = ast.parse(stream.read())
            for node in ast.walk(tree):
                if isinstance(node, ast.Dict):
                    written |= {k.value for k in node.keys
                                if isinstance(k, ast.Constant) and isinstance(k.value, str)}
                if isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Store):
                    key = node.slice
                    if isinstance(key, ast.Constant) and isinstance(key.value, str):
                        written.add(key.value)
        for key in r.UNREAD_KEYS:
            with self.subTest(key=key):
                self.assertIn(key, written)
                self.assertNotIn(key + "s", r.UNREAD_KEYS)


class EveryMemberDoesItsJob(unittest.TestCase):
    """Data tables have nothing to be derived from. What can be held is that each
    member works through the mechanism that reads it — a marker in the wrong case, or
    one the classifier strips before looking, is a member that decides nothing."""

    def test_every_challenge_marker_is_recognised_where_it_lives(self):
        for marker, vendor in r.CHALLENGE_MARKUP_MARKERS:
            with self.subTest(markup=marker):
                html = (f'<html><head><title>Hello</title></head><body><script '
                        f'src="https://e.test/{marker}/a.js"></script><p>One moment '
                        f'please.</p></body></html>')
                kind, why = r.page_guard(html)
                self.assertEqual(kind, "bot_challenge")
                self.assertIn(vendor, why)
                # In prose it is an article about the vendor, not its challenge.
                prose = (f"<html><head><title>Hello</title></head><body><p>{marker} "
                         f"is a path.</p></body></html>")
                self.assertNotEqual(r.page_guard(prose)[0], "bot_challenge")
        for marker, vendor in r.CHALLENGE_TEXT_MARKERS:
            with self.subTest(text=marker):
                html = (f"<html><head><title>Hello</title></head><body><p>"
                        f"{marker.upper()} 12345</p></body></html>")
                kind, why = r.page_guard(html)
                self.assertEqual(kind, "bot_challenge")
                self.assertIn(vendor, why)
        for phrase in r.CHALLENGE_TITLES:
            with self.subTest(title=phrase):
                html = (f"<html><head><title>{phrase.title()}</title></head><body><p>"
                        f"Wait.</p></body></html>")
                self.assertEqual(r.page_guard(html)[0], "bot_challenge")

    def test_no_asset_extension_is_sampled_as_a_page(self):
        self.assertTrue(r.looks_like_a_page("https://e.test/about"))
        for extension in sorted(r.ASSET_EXTENSIONS):
            with self.subTest(extension=extension):
                self.assertTrue(extension.startswith("."))
                self.assertEqual(extension, extension.lower())
                self.assertFalse(r.looks_like_a_page(f"https://e.test/file{extension}"))

    def test_the_runner_probes_the_conventional_sitemap_paths(self):
        """One list of where a sitemap conventionally lives, not two that had already
        drifted by one entry. Held by what `discover_urls` asks for, since the runner
        reads `seo_common` only when it needs it."""
        import lib.safe_http as safe_http
        asked = []

        def refuse(url, **_kwargs):
            asked.append(url)
            raise OSError("refused")

        with mock.patch.object(safe_http, "safe_get", refuse):
            r.discover_urls("https://e.test/", 5)
        self.assertEqual(
            [url for url in asked if url != "https://e.test/"],
            [f"https://e.test{path}" for path in seo_common.CONVENTIONAL_SITEMAP_PATHS])
        self.assertFalse(hasattr(r, "SITEMAP_PATHS"), "a second copy survives")


if __name__ == "__main__":
    unittest.main()
