"""`openspec/specs/registry/` REG-4 — an id is never re-used — held across history.

`tests/id_history.py` is the walk and says why it exists. Three classes, because they
fail for different reasons:

* `HistoryIsReadableAtAll` — a shallow clone must fail by name, never agree by default;
* `NoIdWasEverReused` — the registry's real history, with `build_checklist.RETIRED`;
* `EveryDoorIsOneTheWalkSees` — one synthetic history per violation, so that a walk
  gutted to return nothing does not leave the class above green and meaningless.
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "seo-checklist", "tools"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import build_checklist  # noqa: E402
import id_history  # noqa: E402

A = ("CN-001", 1, "content")
B = ("CN-002", 2, "content")
T = ("TE-003", 3, "technical")


class HistoryIsReadableAtAll(unittest.TestCase):

    def test_the_walk_starts_at_the_registrys_first_commit(self):
        series = id_history.states()
        self.assertEqual(series[0][0], id_history.FIRST[:8])
        self.assertEqual(series[-1][0], id_history.ON_DISK)
        self.assertGreater(len(series), 60, "the registry has had more revisions than this")

    def test_a_clone_without_the_first_commit_is_refused_by_name(self):
        with mock.patch.object(id_history, "FIRST", "0" * 40):
            with self.assertRaises(id_history.Unreadable) as refused:
                id_history.states()
        self.assertIn("fetch-depth: 0", str(refused.exception))


class NoIdWasEverReused(unittest.TestCase):

    def test_the_history_of_this_registry_breaks_nothing(self):
        self.assertEqual(
            id_history.violations(id_history.states(), build_checklist.RETIRED), [])

    def test_a_retired_id_is_refused_by_the_build(self):
        """The record is not only read after the fact: an id named in `RETIRED` cannot
        be built into the registry at all."""
        entry = {"id": "ZZ-999", "category": "content", "source": "manual"}
        self.assertEqual(build_checklist.retired_problems([entry]), [])
        with mock.patch.dict(build_checklist.RETIRED, {"ZZ-999": "a probe"}):
            problems = build_checklist.retired_problems([entry])
        self.assertEqual(len(problems), 1)
        self.assertIn("ZZ-999", problems[0])

    def test_the_build_consults_the_record(self):
        """`retired_problems` existing is not the build calling it."""
        with mock.patch.object(build_checklist, "retired_problems",
                               return_value=["ZZ-999 is retired: a probe"]), \
                mock.patch.object(sys, "argv", ["build_checklist.py", "--check"]):
            self.assertEqual(build_checklist.main(), 1)


class EveryDoorIsOneTheWalkSees(unittest.TestCase):

    def found(self, series, retired=None):
        return id_history.violations(series, retired or {})

    def test_a_quiet_history_is_quiet(self):
        self.assertEqual(self.found([("r1", [A, B]), ("r2", [A, B, T])]), [])

    def test_an_id_that_leaves_must_be_recorded(self):
        series = [("r1", [A, B]), ("r2", [A])]
        self.assertEqual(len(self.found(series)), 1)
        self.assertIn("CN-002", self.found(series)[0])
        self.assertEqual(self.found(series, {"CN-002": "merged into CN-001"}), [])

    def test_an_id_that_comes_back_is_reuse_even_when_its_retirement_was_recorded(self):
        series = [("r1", [A, B]), ("r2", [A]), ("r3", [A, ("CN-002", None, "content")])]
        found = self.found(series, {"CN-002": "merged into CN-001"})
        self.assertTrue(any("issued again" in line for line in found), found)

    def test_an_id_given_another_source_title_in_place(self):
        found = self.found([("r1", [A, B]), ("r2", [A, ("CN-002", 7, "content")])])
        self.assertEqual(len(found), 1)
        self.assertIn("another question", found[0])

    def test_two_items_sharing_an_id(self):
        found = self.found([("r1", [A, A, B])])
        self.assertEqual(len(found), 1)
        self.assertIn("CN-001", found[0])

    def test_a_prefix_in_two_categories(self):
        found = self.found([("r1", [A, ("CN-005", 5, "technical")])])
        self.assertEqual(len(found), 1)
        self.assertIn("prefix CN", found[0])

    def test_a_record_of_a_retirement_that_did_not_happen(self):
        series = [("r1", [A, B])]
        self.assertIn("still ships", self.found(series, {"CN-002": "x"})[0])
        self.assertIn("never carried", self.found(series, {"CN-009": "x"})[0])

    def test_a_retirement_without_a_reason(self):
        found = self.found([("r1", [A, B]), ("r2", [A])], {"CN-002": " "})
        self.assertEqual(len(found), 1)
        self.assertIn("no reason", found[0])


if __name__ == "__main__":
    unittest.main()
