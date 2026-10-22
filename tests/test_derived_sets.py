"""What the tool does is decided by 173 hand-written sets, and 43 of them are read.

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
read", and 130 unread is not a state any test here should be read as endorsing.

**Why the number is the flattering one.** "Read" means a test imports the name from its
module. Importing a name is not asserting what belongs in it, so 43 is a ceiling. A bare
word match over the test corpus would say more still, by crediting one module's constant
with a test that mentions another module's `PAGE` or `CONFIG`; that measure was written
first and discarded for exactly that reason.

**The read column jumped 28 → 43 at 0.104.0 and the tree did not move.** The measure had
only ever matched the module spelled out, so fifteen sets a test asserts through an alias
— `import checklist_runner as r`, then `r.MODE_CAPS` — were recorded as read by nothing.
The defect was in the instrument, in the same shape it exists to find elsewhere: a census
reporting completeness over the spellings it was given. The floor below was lowered to the
number that repair revealed, not to one this session earned.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RECORD = os.path.join(ROOT, "tests", "derived-sets.json")
sys.path.insert(0, os.path.join(ROOT, "skills", "seo-checklist", "tools"))

import audit_derived_sets  # noqa: E402

# The count on 6 September 2026, when this module was written, was 149. It is a ceiling,
# not a target: every set moved out of it is one fewer place where a forgotten entry is
# invisible. Lower it in the same commit that earns the lower number.
#
# 130 since 0.104.0, and the fifteen that moved were never unread — the measure could not
# see an aliased import. Lowered anyway, because the ratchet's job is to hold the best
# number the instrument can currently justify, and leaving it at 149 would bank nineteen
# sets of slack against a future regression.
# 128 at 0.116.0: 0.114.0 and 0.116.0 added four sets (`SHAPES`, `EXTERNAL_SUBJECTS`,
# `CONCEPTS`, `HREF_CONCEPTS`), and the tests that now assert their membership read
# them, taking the column back to where 0.113.0 left it.
# 108 at 0.126.0, the runner's sixteen: ten unread sets left the census as derivations
# (the three `requires` gates, three orderings and `SITEMAP_PATHS` in the runner, the
# report's `SEVERITY_ORDER`, and `audit_score_sensitivity`'s `SEVERITIES` and `DECIDED`),
# ten moved to the read column through `tests/test_runner_sets.py`, and the three sources
# they are read off — `REQUIREMENT_GATES`, `SEVERITIES`, `VERDICTS` — joined it read.
# 88 at 0.127.0, `build_checklist.py`'s twenty: `EFFORT_RANK` left as a derivation of the
# runner's `EFFORT_COST`, and the other nineteen moved to the read column through
# `tests/test_build_sets.py`.
# 82 at 0.132.0, the report's six. Two were never unread: `test_report.py` imports
# `STATUS_ICON` and `FIX_STATUSES` in a parenthesised import spanning lines, which the
# one-line pattern could not see (the second time this instrument under-counted its own
# read column; 0.104.0 was aliases). The other four moved through
# `tests/test_report_sets.py`.
# 81 at 0.144.0, and not earned: `calibrate_css_minification._RUNTIME` is an empty dict
# the tool fills when it runs, never a hand-kept set, and it moved because
# `tests/test_calibration_reports.py` fills it with `mock.patch.dict` — a mention, not a
# reading of what belongs in it. Lowered anyway, for the reason given at 130.
# 80 at 0.147.0, and no set was read: the census stopped counting an empty literal the
# module fills itself. Three left it — `_RUNTIME` and `build_checklist.MAP` from the read
# column, `env_loader._LOADED_FROM` from this one.
# 99 at F04 (batch 4), and the tree did not get worse: the census learned to see three
# spellings it had missed — `scripts/lib/`, a set bound inside a function, and a literal
# handed to `frozenset(...)` or its kin — and found 24 unread sets that had been there all
# along (`LOCAL_BUSINESS_TYPES` among them). Five left the column: the four hreflang sets,
# completed to their standards and held by `tests/test_closed_sets.py`, and `SOURCES`,
# held by the folders it lists. Raised, because a ceiling below what the instrument can
# now see would fail on the day it learned to look.
# 85 at F04 (batch 4b), so far: the schema.org type sets derived from a bundled
# release (four left the census), the retired-schema copies and the AI crawler lists
# made one each (eight left), `STANDARD_CRAWLERS` deleted (read by nothing), and
# `RICH_RESULT_REQUIRED` read against Google's pages. 71 when `tests/test_tool_sets.py`
# read the fourteen in `tools/`. 46 when the scripts' standard vocabularies were read
# against their sources (and the dead `THIN_CONTENT_THRESHOLDS`, `JPEG_SOF_MARKERS` and
# `KNOWN_RATINGS` left the census).
UNREAD_AT_MOST = 46

# GOV-3 in full (F04, batch 4b): an unread set must be open, with its reason in
# `tests/open-sets.json`; a closed one is derived or read. This counts the unread sets
# with no reason, and it is lowered as each is derived or given a reader.
UNREAD_CLOSED_AT_MOST = 3


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

    def test_no_unread_set_is_closed(self):
        """GOV-3's sentence, counted: a set nothing reads must say why it cannot be
        read — an open sample — or it is a closed vocabulary that nothing holds to its
        source. A new set written without either fails here the day it is written."""
        unclassified = [f"{module}.{row['name']}"
                        for module, columns in self.fresh["modules"].items()
                        for row in columns["unread"] if "open" not in row]
        self.assertLessEqual(
            len(unclassified), UNREAD_CLOSED_AT_MOST,
            f"unread with no open reason: {unclassified}. Derive it, give it a reader "
            f"that holds it to its source, or, if no complete form of it exists, record "
            f"why in tests/open-sets.json")

    def test_every_open_reason_names_an_unread_set(self):
        """The record in the other direction: a reason for a set that is read, renamed
        or gone is a judgment about nothing, and an empty one is no judgment."""
        unread = {f"{module}.{row['name']}"
                  for module, columns in self.fresh["modules"].items()
                  for row in columns["unread"]}
        reasons = audit_derived_sets.open_sets()
        self.assertEqual(sorted(set(reasons) - unread), [])
        self.assertEqual([key for key, reason in reasons.items() if not reason.strip()], [])

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

    def test_an_empty_literal_the_module_fills_is_not_a_hand_written_set(self):
        """It holds what a run found and has no member a hand could forget. Each way
        of filling it is here once, beside the two that must stay counted: an empty
        list nobody writes into is hand-kept with no entry yet, and a literal with
        members is hand-written whatever is added to it later."""
        source = ("KEPT = {}\n"
                  "ASSIGNED = {}\n"
                  "ASSIGNED['a'] = 1\n"
                  "CALLED = []\n"
                  "REBOUND = []\n"
                  "GROWN = ['a']\n"
                  "GROWN.append('b')\n"
                  "def run():\n"
                  "    global REBOUND\n"
                  "    CALLED.append(1)\n"
                  "    REBOUND = [1]\n")
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "module.py")
            with open(path, "w", encoding="utf-8") as stream:
                stream.write(source)
            self.assertEqual(audit_derived_sets.literal_sets(path),
                             [("KEPT", 0), ("GROWN", 1)])

    def test_a_literal_wrapped_or_inside_a_function_is_still_hand_written(self):
        """The two spellings the census could not see until F04. `frozenset({...})`
        is a call, and a call was read as a derivation, which it is only when its
        argument is not itself a literal; a list bound inside a function is as
        hand-kept as one at module level, and no test can import it, which is the
        point of naming it."""
        source = ("WRAPPED = frozenset({'a', 'b'})\n"
                  "SORTED = sorted(['b', 'a'])\n"
                  "DERIVED = frozenset(WRAPPED)\n"
                  "BUILT = frozenset(x for x in 'ab')\n"
                  "def parse():\n"
                  "    LOCAL = {'c'}\n"
                  "    x = ['not', 'upper']\n")
        self.assertIn("frozenset", audit_derived_sets.WRAPPERS)
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "module.py")
            with open(path, "w", encoding="utf-8") as stream:
                stream.write(source)
            self.assertEqual(audit_derived_sets.literal_sets(path),
                             [("WRAPPED", 2), ("SORTED", 2), ("parse.LOCAL", 1)])

    def test_every_folder_of_shipped_code_is_a_source(self):
        """`SOURCES`, read against the tree it lists. Until F04 it named `scripts/` and
        `tools/` and not `scripts/lib/`, so the six sets in `safe_http` and
        `image_header` — the fetch policy's private networks among them — were outside
        the census by omission, the shape this module exists to find."""
        skill = audit_derived_sets.SKILL
        folders = {folder for folder, dirs, files in os.walk(skill)
                   if "__pycache__" not in folder and any(f.endswith(".py") for f in files)}
        self.assertEqual(folders, set(audit_derived_sets.SOURCES))

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
        # `MODE_CAPS` stood here as the unread example until 0.104.0, when the measure
        # learned to resolve aliases and found that `test_runner.py` had been asserting
        # it all along as `r.MODE_CAPS`. `ASSET_EXTENSIONS` is the replacement, and the
        # swap is the point: an example of "nothing reads this" is a claim about the
        # tree, and it goes stale like any other. It went stale again at 0.126.0, when
        # `tests/test_runner_sets.py` gave every set in the runner a reader;
        # `HEAD_REFUSED_STATUSES` stands here now.
        self.assertIn("HEAD_REFUSED_STATUSES",
                      [e["name"] for e in modules["seo_common"]["unread"]])

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

    def test_an_import_that_spans_lines_still_credits_the_name(self):
        """The arm added at 0.132.0. `from m import ... NAME` was matched on one line,
        so a parenthesised import — the form every long import in this suite takes —
        credited only the names on the line that says `import`. Measured before the
        repair in `local/gov3/measure_import_blindness.py`: two sets recorded as unread
        were asserted by `test_report.py` all along."""
        spanning = ("from checklist_report import (  # noqa: E402\n"
                    "    FAIL, FIX_STATUSES, LLM_PENDING,\n"
                    "    STATUS_ICON, render_html,\n"
                    ")\n")
        for name in ("FIX_STATUSES", "STATUS_ICON"):
            self.assertTrue(audit_derived_sets.read_by_a_test(
                "checklist_report", name, spanning), name)
        # The module still has to be the one named: the same names imported from
        # another module credit nothing here, and a name only mentioned in a comment
        # inside the parentheses was not imported.
        self.assertFalse(audit_derived_sets.read_by_a_test(
            "checklist_runner", "STATUS_ICON", spanning))
        commented = ("from checklist_report import (\n"
                     "    FAIL,  # not STATUS_ICON\n"
                     ")\n")
        self.assertFalse(audit_derived_sets.read_by_a_test(
            "checklist_report", "STATUS_ICON", commented))
        packaged = ("from lib.safe_http import (\n"
                    "    ROBOTS_MAX_BYTES,\n"
                    ")\n")
        self.assertTrue(audit_derived_sets.read_by_a_test(
            "safe_http", "ROBOTS_MAX_BYTES", packaged))

    def test_a_module_the_test_renamed_still_credits_the_module(self):
        """The arm added at 0.104.0, and the reason the read column was 28 not 43.

        Both older patterns spell the module out, so the fifteen sets a test asserts
        through an alias were recorded as read by nothing — a census reporting
        completeness over the spellings it was given, which is this suite's most
        frequent defect and was in its own instrument.
        """
        aliased = ("import checklist_runner as r\n"
                   "assert r.MODE_CAPS\n")
        self.assertTrue(audit_derived_sets.read_by_a_test(
            "checklist_runner", "MODE_CAPS", aliased))

    def test_an_alias_bound_in_another_file_credits_nothing(self):
        """The direction that flatters, refused.

        `sh` is `lib.safe_http` in one test module and `security_headers` in another.
        Resolving aliases against a corpus flattened into one string would let either
        file's `sh.SOMETHING` credit either module, which is precisely the
        cross-attribution the original measure was narrowed to avoid. Aliases are
        resolved per file, and this is what says so.
        """
        corpus = [("binds_it.py", "import security_headers as sh\n"),
                  ("uses_it.py", "assert sh.HEADERS\n")]
        self.assertFalse(audit_derived_sets.read_by_a_test(
            "security_headers", "HEADERS", corpus))
        self.assertTrue(audit_derived_sets.read_by_a_test(
            "security_headers", "HEADERS",
            [("both.py", "import security_headers as sh\nassert sh.HEADERS\n")]))


if __name__ == "__main__":
    unittest.main()
