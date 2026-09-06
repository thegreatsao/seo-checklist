"""Which sentences in the protocol are the tool's and which are the operator's.

`openspec/specs/operator-protocol/` OPR-1: every instruction is marked as one of two
things — a behaviour the tool guarantees, or a behaviour the operator must supply — and a
reader can tell which. The document was 743 lines in one voice with no marking, and the
failure that causes is silent and lands on a client: an operator who reads a
recommendation as a guarantee stops checking, and from inside the run everything happened
correctly, so nothing here can detect it.

`SKILL.md` now opens with a contract table, one row per `##` section, two columns. This
module holds the table against the document: every section has a row, every row names a
section that exists, the order matches, and no row is empty on both sides.

**What it does not hold, and why the requirement stays `partial`.** Whether a row is
*true* is a reading, and no test can perform it. Nor is the marking per line — a reader
who lands in the middle of a section learns which kinds of sentence that section contains
and not which kind the line in front of them is. Marking every instruction inline was the
other design, and it turns on identifying an instruction mechanically; the closed list of
imperative verbs that would take is the hand-kept list GOV-3 is about. The open question
is recorded in the document rather than settled here.
"""
from __future__ import annotations

import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(ROOT, "skills", "seo-checklist", "SKILL.md")

CONTRACT = "## What this tool guarantees, and what you must supply"
HEADER = "| Section | The tool guarantees | You must |"


def document() -> list[str]:
    with open(SKILL, encoding="utf-8") as stream:
        return stream.read().splitlines()


def sections(lines: list[str]) -> list[str]:
    """Every `##` heading except the contract's own, in document order."""
    return [line[3:].strip() for line in lines
            if line.startswith("## ") and line.strip() != CONTRACT]


def rows(lines: list[str]) -> list[tuple[str, str, str]]:
    """The contract table's rows, as (section, guarantee, obligation)."""
    try:
        start = lines.index(HEADER)
    except ValueError:
        return []
    out = []
    for line in lines[start + 2:]:
        if not line.startswith("|"):
            break
        cells = [cell.strip() for cell in line.strip().strip("|").split(" | ")]
        if len(cells) == 3:
            out.append(tuple(cells))
    return out


class TheProtocolSaysWhoseObligationEachSentenceIs(unittest.TestCase):

    def setUp(self):
        self.lines = document()
        self.rows = rows(self.lines)
        self.sections = sections(self.lines)

    def test_the_table_is_there_and_has_rows(self):
        """Run first. Every assertion below is over `self.rows`, and an empty table
        satisfies most of them — a section with no row cannot be missing from a
        comparison that has nothing to compare against."""
        self.assertIn(CONTRACT, self.lines, "the contract section is gone")
        self.assertTrue(self.rows, "the contract table has no rows")
        self.assertGreater(len(self.sections), 15,
                           "the section scan found almost nothing; it has gone blind")

    def test_every_section_has_a_row_and_every_row_a_section(self):
        """Both directions. A section with no row is prose whose obligations nobody
        declared; a row with no section is a promise about a part of the document that
        no longer exists."""
        named = [row[0] for row in self.rows]
        self.assertEqual(sorted(named), sorted(self.sections))

    def test_the_rows_are_in_document_order(self):
        """A table a reader can follow while reading. Out of order it is a lookup
        structure, and a moved section stops being visible as a move."""
        self.assertEqual([row[0] for row in self.rows], self.sections)

    def test_no_row_is_empty_on_both_sides(self):
        """A section that guarantees nothing and asks nothing is a section with no
        contract in it, which is either untrue or a sign the section should not be a
        section."""
        for section, guarantee, obligation in self.rows:
            with self.subTest(section=section):
                self.assertFalse(guarantee == "—" and obligation == "—",
                                 "neither half of this section's contract is stated")

    def test_a_cell_says_something_or_says_nothing_explicitly(self):
        """`—` is the way to say "no claim of this kind". An empty cell reads as an
        oversight and a reader cannot tell it from one."""
        for section, guarantee, obligation in self.rows:
            for column, cell in (("guarantees", guarantee), ("you must", obligation)):
                with self.subTest(section=section, column=column):
                    self.assertTrue(cell, "an empty cell; write `—` if there is no "
                                          "claim of this kind")
                    if cell != "—":
                        self.assertGreater(len(cell), 20,
                                           "a contract row this short is a label "
                                           "rather than a claim")

    def test_the_obligations_read_as_obligations(self):
        """A weak check on the voice, and it is weak deliberately: the strong version
        would need to decide mechanically whether a sentence is an instruction, and the
        closed list of verbs that takes is the hand-kept list `openspec/specs/governance/`
        GOV-3 exists to object to.

        What it can hold is that the `You must` column is not written in the third
        person about the tool, which is the specific way the two voices collapsed
        before the table existed."""
        for section, _guarantee, obligation in self.rows:
            if obligation == "—":
                continue
            with self.subTest(section=section):
                self.assertNotRegex(
                    obligation, r"^(?:the (?:tool|run|runner|report)|it) ",
                    "this obligation is written as a statement about the tool")

    def test_the_contract_comes_before_the_sections_it_describes(self):
        """An operator reads top to bottom, and a contract found after the instructions
        is a contract found after the decision it was for."""
        self.assertLess(self.lines.index(CONTRACT),
                        self.lines.index("## " + self.sections[0]))


if __name__ == "__main__":
    unittest.main()
