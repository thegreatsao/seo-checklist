"""What the tool does is decided by 166 hand-written sets, and 16 of them are read.

`openspec/specs/governance/` GOV-3: where a list, tuple or mapping decides behaviour, it
is derived from what it describes or read by something. A hand-kept list guarded only by
the mechanism that consumes it is neither, and that is the defect this suite found in six
of its twelve layers — the mechanism gets a reader; the list it runs over does not.

The failure has one shape, and it is why looking harder at the consuming code never finds
it: **a list cannot say what is missing from it, and the reader that would have noticed
the omission is the same line somebody would have had to edit to avoid it.**

`tools/audit_derived_sets.py` counts them. This module holds the count and the direction:
the record must describe the tree, and the unread column may not grow. That is `partial`
and is labelled `partial` — a ratchet holds "no worse", not "every set is derived or
read", and 150 unread is not a state any test here should be read as endorsing.

**Why the number is the flattering one.** "Read" means a test imports the name from its
module. Importing a name is not asserting what belongs in it, so 16 is a ceiling. A bare
word match over the test corpus would say 44, by crediting one module's constant with a
test that mentions another module's `PAGE` or `CONFIG`; that measure was written first
and discarded for exactly that reason.
"""
from __future__ import annotations

import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RECORD = os.path.join(ROOT, "tests", "derived-sets.json")
sys.path.insert(0, os.path.join(ROOT, "skills", "seo-checklist", "tools"))

import audit_derived_sets  # noqa: E402

# The count on 6 September 2026, when this module was written. It is a ceiling, not a
# target: every set moved out of it is one fewer place where a forgotten entry is
# invisible. Lower it in the same commit that earns the lower number.
UNREAD_AT_MOST = 150


class TheCensusDescribesThisTree(unittest.TestCase):

    def setUp(self):
        with open(RECORD, encoding="utf-8") as stream:
            self.stored = json.load(stream)
        self.fresh = audit_derived_sets.census()

    def test_the_record_is_the_census_this_tree_produces(self):
        """Re-taken rather than trusted. A stamp a hand can set is not a freshness
        check, and this record's whole value is that it cannot be edited into
        agreement — the tree is re-scanned here every run."""
        self.assertEqual(self.stored, self.fresh,
                         "re-record with tools/audit_derived_sets.py --out "
                         "tests/derived-sets.json and say which set moved and why")

    def test_the_unread_column_does_not_grow(self):
        """The direction, which is the part a record alone does not hold. A new
        hand-kept set that nothing reads is the defect being added, not merely
        counted."""
        self.assertLessEqual(
            self.fresh["unread"], UNREAD_AT_MOST,
            f"{self.fresh['unread'] - UNREAD_AT_MOST} more hand-written set(s) that "
            f"nothing reads. Derive the new one from what it describes, or import it "
            f"into a test that asserts its membership")

    def test_a_set_that_becomes_derived_leaves_the_census_entirely(self):
        """The escape route, pinned so it stays open. A comprehension or a call is not
        a literal, so deriving a set removes it from `total` rather than moving it to
        the read column — which is the outcome the requirement prefers."""
        import ast
        module = ast.parse(
            "LITERAL = ['a', 'b']\n"
            "DERIVED = [x for x in LITERAL]\n"
            "ALSO_DERIVED = sorted(LITERAL)\n")
        found = []
        for node in module.body:
            value = node.value
            if isinstance(value, audit_derived_sets.LITERALS):
                found.append(node.targets[0].id)
        self.assertEqual(found, ["LITERAL"])

    def test_the_scan_finds_the_sets_this_suite_already_knows_about(self):
        """A floor. Every count above would read as good news if the scan quietly
        stopped finding module-level literals, so three known ones are named — one
        read, one unread, and one whose size is the thing other tests assert on."""
        modules = self.fresh["modules"]
        runner = {entry["name"]: entry["entries"]
                  for column in ("read", "unread")
                  for entry in modules["checklist_runner"][column]}
        self.assertIn("SEVERITY_WEIGHT", runner)
        self.assertEqual(runner["SEVERITY_WEIGHT"], 4)
        self.assertIn("SEVERITY_WEIGHT",
                      [e["name"] for e in modules["checklist_runner"]["read"]])
        self.assertIn("MODE_CAPS",
                      [e["name"] for e in modules["checklist_runner"]["unread"]])

    def test_read_means_the_test_named_the_module_it_came_from(self):
        """The measure itself, in both directions. `PAGE` is a constant in
        `build_checklist.py` and a word in tests that have nothing to do with it; a
        looser match would credit the second to the first and report three times as
        much coverage as there is."""
        corpus = "from checklist_runner import SEVERITY_WEIGHT\nPAGE = 1\n"
        self.assertTrue(audit_derived_sets.read_by_a_test(
            "checklist_runner", "SEVERITY_WEIGHT", corpus))
        self.assertFalse(audit_derived_sets.read_by_a_test(
            "build_checklist", "PAGE", corpus))
        self.assertTrue(audit_derived_sets.read_by_a_test(
            "build_checklist", "PAGE", "build_checklist.PAGE\n"))


if __name__ == "__main__":
    unittest.main()
