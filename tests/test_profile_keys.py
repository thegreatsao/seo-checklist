"""`openspec/specs/registry/` REG-13 — severity and effort are the item's, never a run's.

Grading was held: a row carries its item's `effort`. What was not held is the door the
requirement names first — *the profile*. `profiles.json` was validated for the keys it
used and not closed against the ones it must not carry, so a profile declaring a
`severity` loaded without a word; it changed nothing only because no code reads the key,
which is the kind of safety that lasts until somebody adds the three lines that do.

Measured on 1 October 2026: six profiles use eight keys between them (`label`, `note`,
`exclude_categories`, `exclude_scripts`, `exclude_items`, `exclude_item_reasons`,
`script_args`, `script_args_note`). The runner now names them, `PROFILE_KEYS`, and
refuses a profile carrying anything else. A profile narrows the registry and may tune a
script's arguments; it does not get a vocabulary in which an item's weight can be said.
"""
from __future__ import annotations

import ast
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(ROOT, "skills", "seo-checklist")
sys.path.insert(0, os.path.join(SKILL, "scripts"))

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import checklist_runner as runner  # noqa: E402
import harness  # noqa: E402
from harness import served  # noqa: E402
from test_shapes import page, run_audit  # noqa: E402

ITEMS = harness.registry()["items"]
with open(runner.PROFILES, encoding="utf-8") as _stream:
    SHIPPED = json.load(_stream)["profiles"]

# What an item's weight is said in. None of these may ever be a profile's to state.
ITEM_FIELDS = ("severity", "effort", "source", "weight", "items", "overrides")


class TheKeysAreClosed(unittest.TestCase):

    def test_the_vocabulary_is_exactly_what_the_shipped_profiles_use(self):
        used = {key for profile in SHIPPED.values() for key in profile}
        self.assertEqual(set(runner.PROFILE_KEYS), used)

    def test_no_item_field_is_in_the_vocabulary(self):
        self.assertEqual(set(runner.PROFILE_KEYS) & set(ITEM_FIELDS), set())
        self.assertEqual(set(runner.PROFILE_KEYS) & set(ITEMS[0]), set(),
                         "a profile key shares its name with a field of an item")

    def write(self, profile: dict) -> str:
        handle = tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8")
        with handle:
            json.dump({"profiles": {"default": SHIPPED["default"], "probe": profile}},
                      handle)
        self.addCleanup(os.unlink, handle.name)
        return handle.name

    def test_a_profile_carrying_a_severity_is_refused_by_name(self):
        for key in ITEM_FIELDS:
            with self.subTest(key=key):
                path = self.write({**SHIPPED["default"], key: {"CN-039": "low"}})
                with mock.patch.object(runner, "PROFILES", path):
                    with self.assertRaises(ValueError) as refused:
                        runner.load_profile("probe")
                    self.assertIn(key, str(refused.exception))
                    self.assertIn("probe", str(refused.exception))
                    with self.assertRaises(ValueError):
                        runner.all_profiles()

    def test_one_bad_profile_does_not_pass_because_another_was_asked_for(self):
        """The file is one artifact. `--profile default` over a file whose `store`
        carries a severity would otherwise run clean until somebody picked `store`."""
        path = self.write({**SHIPPED["default"], "severity": {"CN-039": "low"}})
        with mock.patch.object(runner, "PROFILES", path):
            with self.assertRaises(ValueError):
                runner.load_profile("default")

    def test_a_profile_using_only_the_vocabulary_loads(self):
        path = self.write(dict(SHIPPED["local"]))
        with mock.patch.object(runner, "PROFILES", path):
            self.assertEqual(runner.load_profile("probe"), SHIPPED["local"])


class TheRunSaysSoInsteadOfCrashing(unittest.TestCase):
    """An unknown profile name already ends the run with a sentence and exit 2. A refused
    profile raises from the same two calls and has to leave by the same door: a traceback
    is the one answer an operator cannot act on."""

    def test_the_handler_around_the_profile_catches_the_refusal(self):
        with open(runner.__file__, encoding="utf-8") as stream:
            tree = ast.parse(stream.read())
        guarded = [
            node for node in ast.walk(tree) if isinstance(node, ast.Try)
            and any(isinstance(call, ast.Call) and getattr(call.func, "id", "") == "load_profile"
                    for statement in node.body for call in ast.walk(statement))]
        self.assertEqual(len(guarded), 1, "the run loads its profile in one guarded place")
        caught = set()
        for handler in guarded[0].handlers:
            kinds = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
            caught |= {kind.id for kind in kinds}
        self.assertLessEqual({"KeyError", "ValueError"}, caught)


class ARowCarriesItsItemsWeightUnderEveryProfile(unittest.TestCase):

    def test_severity_and_effort_are_the_registrys(self):
        registry = {item["id"]: (item["severity"], item["effort"]) for item in ITEMS}
        for name in runner.all_profiles():
            excluded = runner.profile_excludes(ITEMS, runner.load_profile(name))
            skipped = {item_id: (runner.NA, why) for item_id, why in excluded.items()}
            graded = runner.grade(ITEMS, {}, {}, skipped, False)
            self.assertEqual(len(graded), len(ITEMS), name)
            for row in graded:
                with self.subTest(profile=name, item=row["id"]):
                    self.assertEqual((row["severity"], row["effort"]), registry[row["id"]])


class AFinishedRunCarriesItToo(unittest.TestCase):
    """The class above asks `grade`. This asks the artifact, after everything a run does
    to a row on the way out — sampling, aggregation over pages, a profile's exclusions
    and its moved arguments — because "the row had it when it was graded" is not "the
    reader of the JSON has it"."""

    def test_a_sampled_run_under_a_narrowing_profile_states_the_registrys_weights(self):
        registry = {item["id"]: (item["severity"], item["effort"]) for item in ITEMS}
        with served({"/": page("The entry page",
                               'It links onward. <a href="/second.html">second</a>'),
                     "/second.html": page("The second page", "")}) as site:
            payload = run_audit(site.url, "--profile", "local", "--sample", "2",
                                only="meta_structured")
        self.assertEqual(payload["profile"], "local")
        self.assertEqual({row["id"] for row in payload["items"]}, set(registry))
        self.assertTrue(any(row["status"] == runner.NA for row in payload["items"]),
                        "the profile excluded nothing, so this asks less than it says")
        for row in payload["items"]:
            with self.subTest(item=row["id"]):
                self.assertEqual((row["severity"], row["effort"]), registry[row["id"]])


if __name__ == "__main__":
    unittest.main()
