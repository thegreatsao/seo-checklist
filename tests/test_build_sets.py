"""`openspec/specs/governance/` GOV-3 for `tools/build_checklist.py`: every hand-written
table the registry is built from is derived from what it describes, or read here.

Until 0.127.0 the census counted twenty of them as named by nothing. Several were in fact
held — `CANNOT_FAIL` by `audit_reachability.py`'s proofs, `APPLIES_WHEN` by the REG-9
sweep in `test_registry.py`, `SAME_CHECK` by `audit_item_semantics.py`'s duplicate
groups — but through the built registry, where a census reading imports cannot see it.
Those are tied to their reader here by name. The rest are held against what each
describes: the registry's categories, sources and scripts, the runner's requirement and
effort vocabularies, the proofs and the agents that consume them.

Measured before anything was written (`local/gov3/measure_build.py`). Two tables carried
dead entries: `REQUIRES` named `competitor_gap.py` and `readability.py`, which no item
runs, and `EFFORT_OVERRIDES` gave MS-031 the effort its category already gives it. A dead
entry reads as a decision somebody made about something that is not there.
"""
from __future__ import annotations

import json
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(ROOT, "skills", "seo-checklist")
sys.path.insert(0, os.path.join(SKILL, "scripts"))
sys.path.insert(0, os.path.join(SKILL, "tools"))

import audit_reachability  # noqa: E402
import build_checklist as b  # noqa: E402
import checklist_report  # noqa: E402
import checklist_runner as r  # noqa: E402

with open(os.path.join(SKILL, "resources", "config", "checklist.json"),
          encoding="utf-8") as _stream:
    ITEMS = {i["id"]: i for i in json.load(_stream)["items"]}
CHECKS = {k: i["check"] for k, i in ITEMS.items() if i.get("check")}
SCRIPTED = {k: c for k, c in CHECKS.items() if c.get("script")}
CATEGORIES = {i["category"] for i in ITEMS.values()}

TEMPLATES = {"PAGE": b.PAGE, "JSRENDER": b.JSRENDER, "HTMLARG": b.HTMLARG,
             "CRAWLARG": b.CRAWLARG, "GSCARG": b.GSCARG, "LINKSARG": b.LINKSARG,
             "INSPECTARG": b.INSPECTARG, "RENDERED": b.RENDERED}


def pairs(same_check: dict) -> list[tuple[str, str]]:
    return [(carrier, twin) for carrier, twins in same_check.items()
            for twin in (twins if isinstance(twins, list) else [twins])]


class TheSourceListIsTiled(unittest.TestCase):

    def test_the_plerdy_spans_tile_the_source_list_and_name_its_items(self):
        """`CATEGORIES` cuts the 200 Plerdy rows into fifteen sections, and every item
        id is the section's prefix and the row number. A gap, an overlap or a wrong
        prefix would file an item under somebody else's section."""
        spans = sorted(c[3] for c in b.CATEGORIES)
        self.assertEqual(spans[0][0], 1)
        for before, after in zip(spans, spans[1:], strict=False):
            self.assertEqual(after[0], before[1] + 1, f"{before} then {after}")
        self.assertEqual(spans[-1][1], max(b.MAP))
        self.assertEqual(sorted(b.MAP), list(range(1, max(b.MAP) + 1)))
        self.assertEqual(len({c[0] for c in b.CATEGORIES}), len(b.CATEGORIES))
        self.assertEqual(len({c[1] for c in b.CATEGORIES}), len(b.CATEGORIES))
        for category, prefix, _label, (first, last) in b.CATEGORIES:
            for ref in range(first, last + 1):
                with self.subTest(ref=ref):
                    item = ITEMS.get(f"{prefix}-{ref:03d}")
                    self.assertIsNotNone(item, f"row {ref} built no {prefix} item")
                    self.assertEqual(item["category"], category)


class EveryInvocationIsOneTheRunnerCanAnswer(unittest.TestCase):

    def test_every_argument_template_is_used(self):
        for name, template in TEMPLATES.items():
            with self.subTest(template=name):
                users = [k for k, c in SCRIPTED.items()
                         if (c.get("args") or [])[:len(template)] == template]
                self.assertTrue(users, f"{name} is an invocation no item makes")

    def test_a_template_that_reads_the_crawl_or_search_console_requires_it(self):
        """The placeholder says what the run must have produced or been given; the
        requirement says when the item can run. A crawl-reading item filed as `fetch`
        would run in page mode against an inventory that was never built."""
        for item_id, check in SCRIPTED.items():
            argv = " ".join(check.get("args") or [])
            with self.subTest(item=item_id):
                if "{inventory_json}" in argv:
                    self.assertEqual(check["requires"], "crawl")
                if "{gsc_property}" in argv:
                    self.assertEqual(check["requires"], "gsc")

    def test_every_script_requirement_is_a_script_the_registry_runs(self):
        scripts = {c["script"] for c in SCRIPTED.values()}
        self.assertEqual(sorted(set(b.REQUIRES) - scripts), [],
                         "a requirement recorded for a script no item runs")
        vocabulary = set(r.REQUIREMENT_GATES)
        self.assertLessEqual(set(b.REQUIRES.values()), vocabulary)
        self.assertIn(b.DEFAULT_REQUIRES, vocabulary)
        for item_id, check in SCRIPTED.items():
            with self.subTest(item=item_id):
                expected = b.ITEM_REQUIRES.get(
                    item_id, b.REQUIRES.get(check["script"], b.DEFAULT_REQUIRES))
                self.assertEqual(check["requires"], expected)

    def test_every_item_requirement_overrides_its_script(self):
        for item_id, requirement in b.ITEM_REQUIRES.items():
            with self.subTest(item=item_id):
                self.assertIn(item_id, SCRIPTED)
                self.assertIn(requirement, r.REQUIREMENT_GATES)
                script_wide = b.REQUIRES.get(SCRIPTED[item_id]["script"],
                                             b.DEFAULT_REQUIRES)
                self.assertNotEqual(requirement, script_wide,
                                    "an override that changes nothing")


class TheEffortTables(unittest.TestCase):

    def test_every_category_has_an_effort_and_every_override_changes_one(self):
        """`effort_for` falls back to `medium` for a category the table forgets, so
        the omission is silent there and has to be loud here."""
        efforts = set(b.EFFORT_RANK)
        self.assertEqual(set(b.EFFORT_BY_CATEGORY), CATEGORIES)
        self.assertLessEqual(set(b.EFFORT_BY_CATEGORY.values()), efforts)
        for item_id, effort in b.EFFORT_OVERRIDES.items():
            with self.subTest(override=item_id):
                self.assertIn(item_id, ITEMS)
                self.assertIn(effort, efforts)
                self.assertNotEqual(effort,
                                    b.EFFORT_BY_CATEGORY[ITEMS[item_id]["category"]],
                                    "an override equal to its category's effort")
        self.assertLessEqual(set(b.EFFORT_FLOOR_BY_SOURCE),
                             {i["source"] for i in ITEMS.values()})
        self.assertLessEqual(set(b.EFFORT_FLOOR_BY_SOURCE.values()), efforts)

    def test_the_effort_rank_is_the_order_of_the_effort_cost(self):
        """Two tables over the same three words: the build ranks them, the report
        divides by their cost. They must agree about which is harder."""
        self.assertEqual(set(b.EFFORT_RANK), set(r.EFFORT_COST))
        self.assertEqual(sorted(b.EFFORT_RANK, key=b.EFFORT_RANK.get),
                         sorted(r.EFFORT_COST, key=r.EFFORT_COST.get))


class TheTablesThatGatesReadThroughTheRegistry(unittest.TestCase):

    def test_cannot_fail_is_exactly_what_reachability_proves(self):
        proven = {k: row["mechanism"] for k, row in audit_reachability.proofs().items()}
        declared = {k: row["mechanism"] for k, row in b.CANNOT_FAIL.items()}
        self.assertEqual(declared, proven)
        self.assertLessEqual(set(declared.values()), set(audit_reachability.MECHANISMS))

    def test_applies_when_is_the_registrys_declarations(self):
        """What `test_registry`'s REG-9 sweep holds against `passes_by_absence`, named
        here so the table itself is the thing held."""
        self.assertEqual({k: c["applies_when"] for k, c in CHECKS.items()
                          if c.get("applies_when")}, b.APPLIES_WHEN)

    def test_every_twin_is_the_same_check_as_the_item_it_scores_with(self):
        """`audit_item_semantics.py` refuses a duplicate group nobody ruled on. It does
        not refuse the other direction — a twin that is *not* the same check — and
        that one is silent: the twin stops carrying weight for a question nothing
        else scores."""
        declared = pairs(b.SAME_CHECK)
        self.assertEqual(sorted((i["scores_with"], k) for k, i in ITEMS.items()
                                if i.get("scores_with")), sorted(declared))
        for carrier, twin in declared:
            with self.subTest(twin=twin):
                a, c = SCRIPTED[carrier], SCRIPTED[twin]
                self.assertEqual((a["script"], a.get("args"), a.get("assert")),
                                 (c["script"], c.get("args"), c.get("assert")))

    def test_every_lens_is_an_agent_and_every_model_item_has_one(self):
        lensed = [i for ids in b.LENS.values() for i in ids]
        self.assertEqual(set(b.LENS), set(checklist_report.LENS_AGENTS))
        self.assertEqual(len(lensed), len(set(lensed)))
        self.assertEqual(set(lensed),
                         {k for k, i in ITEMS.items() if i["source"] == "llm"})

    def test_every_guard_token_is_claimed_by_a_recorded_reason(self):
        """The build refuses a reason claiming a token outside `GUARD_TOKENS`. This is
        the other direction: a token no reason claims is a mechanism nothing uses."""
        claimed = {token for token in b.GUARD_TOKENS
                   for why in b.SUBJECT_ALWAYS_PRESENT.values()
                   if re.match(re.escape(token) + ":", why)}
        self.assertEqual(claimed, set(b.GUARD_TOKENS))


if __name__ == "__main__":
    unittest.main()
