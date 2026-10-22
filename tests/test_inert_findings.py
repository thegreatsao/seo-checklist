"""The recorded inert findings, kept in step with the registry they describe.

``tests/inert-findings.json`` is a measurement, not a declaration and not a gate.
It records which findings a ``none_severity`` assertion cannot act on, but it cannot
decide whether any one of them is deliberate advice or an item that cannot keep the
claim in its title.

Recomputing the AST measurement was said not to belong in the suite, and that was an
estimate rather than a measurement: it costs 0.15 s against a 418 s run. Until 0.97.0
the recompute therefore ran only in ``ci.yml``, and a change that blinded the reader
passed locally and failed there. It runs here now, beside the cheap invariants that
make a stale or empty record visible. Re-record and read it with

    python tests/inert_findings.py --out tests/inert-findings.json
"""
from __future__ import annotations

import json
import os
import unittest

import harness  # noqa: E402
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RECORD = os.path.join(ROOT, "tests", "inert-findings.json")


def load(path: str) -> dict:
    with open(path, encoding="utf-8") as stream:
        return json.load(stream)


class RecordedInertFindings(unittest.TestCase):

    def setUp(self):
        self.record = load(RECORD)
        self.registry = harness.registry()

    def test_it_describes_this_registry(self):
        self.assertEqual(self.record["registry_version"],
                         self.registry["registry_version"],
                         "tests/inert-findings.json describes another registry — "
                         "re-record it with tests/inert_findings.py")

    def test_every_none_severity_item_is_accounted_for(self):
        registry_ids = {item["id"] for item in self.registry["items"]}
        recorded_ids = set(self.record["items"])
        none_severity_ids = {
            item["id"]
            for item in self.registry["items"]
            if "none_severity" in ((item.get("check") or {}).get("assert") or {})
        }
        self.assertLessEqual(recorded_ids, registry_ids)
        self.assertLessEqual(none_severity_ids, recorded_ids)

    def test_what_it_copies_from_the_registry_still_describes_it(self):
        """The same reading `tests/test_census.py` makes of its own record, for the
        same reason: `registry_version` above is taken from the registry by the tool
        that records, so it cannot drift on its own — which leaves it the one field in
        the file that an edit can set, and it was the only field being read. Title and
        script are copies and cost nothing to re-read; the AST measurement beside them
        is what does not belong in the suite.

        This record was in step when the guard was written and its stamp was moved by
        hand in the same release that left the census stale — `66d1b2037c32` to
        `b0abf2819da0`, one line, no re-recording. Nothing was wrong with it; nothing
        would have said so either.

        This record is deliberately a subset — the test above owns "every
        `none_severity` item is in here" — so what this one adds is the other
        direction: a row that has left the registry, or one whose title or script has
        moved under it, named rather than counted.
        """
        items = {item["id"]: item for item in self.registry["items"]}
        for item_id in sorted(self.record["items"]):
            with self.subTest(item=item_id):
                item = items.get(item_id)
                self.assertIsNotNone(
                    item, f"{item_id} is recorded and is not in this registry")
                row = self.record["items"][item_id]
                copied = {"title": item["title"],
                          "script": (item.get("check") or {}).get("script")}
                self.assertEqual(
                    {field: row.get(field) for field in copied}, copied,
                    f"{item_id}: the record copies a registry field that has since "
                    "moved — re-record it with tests/inert_findings.py --out")

    def test_the_record_is_not_empty(self):
        self.assertTrue(self.record["items"], "the inert-findings record is empty")

    def test_the_measurement_itself_still_describes_this_tree(self):
        """The recompute, which this file's docstring said does not belong here.

        It said so on an estimate, and the estimate was wrong by orders of magnitude:
        `measure()` costs **0.15 s** against a 418 s suite. What the estimate bought
        instead was a gate living only in `ci.yml`, and on 16 September that cost a
        red pipeline after a green local run — four CI-018 caveats moved behind a
        helper, this record lost all four and gained a meaningless `{message}` in
        their place, and nothing local said so.

        Kept as a whole-record comparison rather than a spot check, deliberately. The
        failure that prompted it was not a wrong value in a field; it was rows quietly
        leaving, and only comparing the whole thing sees that.
        """
        import sys
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import inert_findings
        fresh = json.loads(json.dumps(inert_findings.measure(), sort_keys=True))
        self.assertEqual(
            self.record, fresh,
            "the inert-findings measurement moved; re-record with "
            "python tests/inert_findings.py --out tests/inert-findings.json — and "
            "read what changed first: a finding leaving this list is either a rule "
            "that now acts on it, or a reader that has gone blind to it")


class TheRecordFeedsNothing(unittest.TestCase):
    """`openspec/specs/governance/` GOV-5: the record says what no rule reads, never
    what is worth reading, and its existence is not an argument for moving a verdict.

    The half of that a test can hold is that nothing the plugin ships reads it: no
    file under `skills/` — the runner, the checkers, the generator, the agent's
    instructions, its resources — names the record or the module that measures it.
    A person citing it as grounds for a rule, or copying its rows into one by hand, is
    the other half, and no program here reaches that.
    """

    NAMES = ("inert-findings", "inert_findings")

    def test_nothing_the_plugin_ships_names_the_record(self):
        skills = os.path.join(ROOT, "skills")
        read = 0
        found = []
        for folder, dirs, files in os.walk(skills):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for name in files:
                path = os.path.join(folder, name)
                try:
                    with open(path, encoding="utf-8") as stream:
                        text = stream.read()
                except (UnicodeDecodeError, OSError):
                    continue
                read += 1
                found += [f"{os.path.relpath(path, ROOT)} names {word}"
                          for word in self.NAMES if word in text]
        self.assertGreater(read, 100, "the walk over skills/ read almost nothing")
        self.assertEqual(found, [], "the inert-findings record is read by the plugin, so "
                         "its existence can move a verdict — " + "; ".join(found))


if __name__ == "__main__":
    unittest.main()
