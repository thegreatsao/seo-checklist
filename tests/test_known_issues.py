"""The KNOWN-ISSUES record, kept in step with the file it describes.

The probes are re-run by `python tests/known_issues.py --check`, in CI, because they
import evidence scripts and parse a calibration corpus. What belongs here is the part
that must hold whatever the probes answer: every entry in section 6 is marked, every
marker is in the record, and no entry is exempt from a probe without saying why.

The last of those is the one that decays. A ledger drifts into uselessness by having
every awkward entry declared unprobeable, one at a time, each with a reason that looked
fine on the day. Nothing here can judge those reasons — but an entry with no probe and
no reason at all is a failure this can see.

    python tests/known_issues.py --out tests/known-issues.json
"""
from __future__ import annotations

import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RECORD = os.path.join(ROOT, "tests", "known-issues.json")
sys.path.insert(0, os.path.join(ROOT, "tests"))

import known_issues  # noqa: E402


class RecordedKnownIssues(unittest.TestCase):

    def setUp(self):
        with open(RECORD, encoding="utf-8") as stream:
            self.record = json.load(stream)
        self.found = known_issues.entries_in_the_file()

    def test_every_entry_in_section_six_carries_a_marker(self):
        unmarked = ["KNOWN-ISSUES.md:%d %s" % (entry["line"], entry["lead"])
                    for entry in self.found if entry["slug"] is None]
        self.assertEqual(unmarked, [],
                         "an entry with no `<!-- ki: slug -->` marker is an entry the "
                         "record cannot describe")

    def test_the_record_and_the_file_name_the_same_entries(self):
        self.assertEqual(sorted(e["slug"] for e in self.found if e["slug"]),
                         sorted(self.record["entries"]),
                         "re-record with tests/known_issues.py --out")

    def test_the_counts_the_record_states_are_its_own(self):
        entries = self.record["entries"]
        probed = [entry for entry in entries.values() if entry["probe"]]
        self.assertEqual(self.record["entry_count"], len(entries))
        self.assertEqual(self.record["probed_entry_count"], len(probed))
        self.assertEqual(self.record["unprobed_entry_count"], len(entries) - len(probed))

    def test_every_entry_is_classified_and_makes_a_claim(self):
        for slug, entry in sorted(self.record["entries"].items()):
            with self.subTest(entry=slug):
                self.assertIn(entry.get("state"), known_issues.STATES)
                self.assertTrue(entry.get("claim"), "the entry records no claim")

    def test_an_entry_without_a_probe_says_why(self):
        for slug, entry in sorted(self.record["entries"].items()):
            if entry.get("probe"):
                with self.subTest(entry=slug):
                    self.assertIn(entry["probe"], known_issues._PROBES)
                    self.assertIn("measured", entry)
                continue
            with self.subTest(entry=slug):
                self.assertTrue(entry.get("why"),
                                "no probe and no reason for having none")

    def test_the_comparison_complains_when_a_recorded_value_moves(self):
        """The one thing the whole instrument is for, asserted rather than assumed.

        Every other test here reads the record. A `differences()` gutted to `return []`
        — or a `--check` that always exits 0 — would leave all of them green and the
        gate permanently silent, which is worse than not having the gate: it reads as
        a checked claim. So one probe is answered with a value the tree does not
        produce, and this asserts the disagreement is reported by name.
        """
        entries = json.loads(json.dumps(self.record))["entries"]
        slug = next(slug for slug, entry in sorted(entries.items()) if entry["probe"])
        entries[slug]["measured"] = {"a value no probe returns": True}
        problems = known_issues.differences({"entries": entries})
        self.assertTrue(any(slug in problem for problem in problems),
                        "a recorded value that moved was not reported: %s" % problems)

    def test_the_comparison_complains_when_an_entry_is_unclassified(self):
        entries = json.loads(json.dumps(self.record))["entries"]
        slug = sorted(entries)[0]
        entries[slug] = dict(entries[slug], state="unclassified")
        problems = known_issues.differences({"entries": entries})
        self.assertTrue(any(slug in problem for problem in problems), problems)

    def test_the_comparison_is_quiet_on_the_record_as_recorded(self):
        """The other half of the pair above: a check that always complains is as
        useless as one that never does, and only running both says which this is.

        This runs every probe, which the two ledgers beside this one deliberately do
        not do in the suite. They recompute an AST scan over the whole tree; these
        thirty-three probes take about seven seconds together, and paying that locally
        is what makes a stale entry a failure somebody sees before pushing.
        """
        self.assertEqual(known_issues.differences(self.record), [])

    def test_the_file_is_still_asking_more_than_it_is_guarding(self):
        """A probe on a closed entry guards a repair; a probe on an open one is the
        measurement itself. Both belong here, and the second is what the instrument is
        for — if closed entries ever came to dominate it, this would have quietly
        become a regression suite with a documentation file attached.

        **Counted over entries, because counting it over probes made repair the thing
        that failed.** Until 0.91.0 this asserted that probes on open entries
        outnumbered all probes. Every closure moves one probe from the open side to
        the guarding side and none ever comes back, so the ratio falls with each
        release that fixes something — and it fell below the line the day an entry
        covering twenty-three scripts was closed by reading all of them. The fear the
        line was drawn against is real and is about the file, not about the probes: a
        list with three questions and sixty guarded repairs is a regression suite. So
        the question is asked of the entries, and `history` is left out of it, being
        neither a live question nor a guard.

        The live half being measured is the other half of the claim, and it is not a
        ratio: an open entry either carries a probe or carries a written reason it
        cannot, which `differences()` enforces entry by entry.
        """
        entries = self.record["entries"].values()
        current = [entry for entry in entries if entry["state"] in ("open", "closed")]
        asking = [entry for entry in current if entry["state"] == "open"]
        self.assertGreater(len(asking), len(current) / 2)


if __name__ == "__main__":
    unittest.main()
