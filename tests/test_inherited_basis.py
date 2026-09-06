"""`inherited` is the recorded absence of a decision, and 77 numbers carry it.

`openspec/specs/governance/` GOV-2. Every number a verdict depends on carries a
`# basis:` line naming one of five kinds, and `inherited` means the number came with the
borrowed code and nobody here has defended it. It licenses no conclusion about whether
the number is right. The category exists so the debt is countable, and it stops working
the moment it reads as a fourth kind of justification.

`tools/audit_thresholds.py --check` already refuses a malformed declaration. What it does
not do is care which kind a number carries: the gate counts them and no consumer treats
`inherited` differently from `standard`. This module holds the two halves of the
requirement a test can reach.

**The count may not rise.** A new constant filed as `inherited` is a deliberate act, and
the scenario in the requirement asks that it be visible as one rather than absorbed into
a total nobody watches. 77 of 146 today.

**An `inherited` line may not defend its number.** The convention is
`# basis: inherited — <what the number is>`, and the description is why the category is
useful; what it must not contain is an argument. A line that cites a source is filed in
the flattering direction — somebody had a reason and recorded an absence.

That second half is a positive search, and a positive search finds what its pattern
knows. It catches a URL and a short list of phrasings, and it does not prove that no
`inherited` line anywhere argues its number in words nobody thought of. The requirement's
first scenario — an undefended number cited as justification in an argument with a client
— happens outside this repository entirely, and nothing here reaches it. `partial` is the
honest label and the document says so.
"""
from __future__ import annotations

import collections
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "seo-checklist", "tools"))

import audit_thresholds  # noqa: E402

# Measured 6 September 2026. A ceiling, not a target: the requirement's third scenario is
# a basis being upgraded, and every one of those lowers this number. Lower it in the
# commit that earns it.
INHERITED_AT_MOST = 77

# Phrasings that turn a description into a defence. A positive search, so this finds what
# it knows and proves nothing about what it does not — the docstring says so rather than
# letting the empty result read as a clean bill.
DEFENCE = re.compile(
    r"https?://|\b(?:because|industry standard|best practice|widely used|"
    r"recommended by|google (?:says|recommends)|the norm|correct value|"
    r"known to be right)\b", re.IGNORECASE)


class InheritedIsAnAdmission(unittest.TestCase):

    def setUp(self):
        named, _unnamed = audit_thresholds.scan()
        self.named = named
        self.inherited = [row for row in named if row["kind"] == "inherited"]

    def test_the_scan_still_finds_the_declarations(self):
        """Everything below counts rows. A scan that stopped finding them would report
        an empty `inherited` list, which is the best possible news and would be a
        failure of the instrument rather than progress."""
        self.assertGreater(len(self.named), 100,
                           "the threshold scan found almost nothing; it has gone blind")
        self.assertTrue(self.inherited, "no number carries `inherited` — if that is "
                                        "real, delete this module and say so")

    def test_the_kinds_are_the_closed_set_the_tool_defines(self):
        """Read from the tool rather than listed here, so a sixth kind arrives as a
        failure. A new word for "we did not decide" would split the debt in two and
        halve the number this module ratchets."""
        seen = {row["kind"] for row in self.named}
        self.assertLessEqual(seen, set(audit_thresholds.KINDS))
        self.assertIn("inherited", audit_thresholds.KINDS)

    def test_the_undefended_count_does_not_rise(self):
        """The scenario, as a ratchet. `inherited` is fine as an accounting and
        dangerous as a standard, and the difference between the two is whether anybody
        is watching the total."""
        distribution = collections.Counter(row["kind"] for row in self.named)
        self.assertLessEqual(
            len(self.inherited), INHERITED_AT_MOST,
            f"{len(self.inherited) - INHERITED_AT_MOST} more number(s) filed as "
            f"`inherited`. Measure it, argue it, or say in the commit why the debt "
            f"grew — the distribution is now {dict(distribution)}")

    def test_no_inherited_line_argues_its_number(self):
        """The half of "must not be cited as anything else" that lives in this tree.

        A `# basis: inherited` line that carries a source or an argument has recorded an
        absence where there was a decision, which is the same error as the reverse and
        harder to notice, because it reads as thoroughness.
        """
        offenders = [f"{row['file']}:{row['line']} {row['name']} — {row['why'][:60]}"
                     for row in self.inherited if DEFENCE.search(row["why"])]
        self.assertEqual(
            offenders, [],
            "these `inherited` declarations argue their number. If the argument is "
            "good the basis is `standard`, `measured` or `convention`; if it is not, "
            "it does not belong on the line — " + "; ".join(offenders))

    def test_the_search_for_a_defence_would_find_one(self):
        """A positive search whose corpus is clean says nothing until it has been shown
        to fire. This is that demonstration, on a line shaped like the ones above."""
        self.assertTrue(DEFENCE.search("200 links, the industry standard"))
        self.assertTrue(DEFENCE.search("see https://developers.google.com/search"))
        self.assertFalse(DEFENCE.search("200 links, present at import"))

    def test_a_defended_number_is_not_filed_as_inherited_anywhere_else(self):
        """The converse, over the other four kinds: a number whose basis names a
        standard or a measurement must not also be described as inherited, which would
        make the count meaningless in the other direction."""
        for row in self.named:
            if row["kind"] == "inherited":
                continue
            with self.subTest(name=row["name"]):
                self.assertNotRegex(
                    row["why"], r"\binherited\b",
                    "a defended number describes itself as inherited")


if __name__ == "__main__":
    unittest.main()
