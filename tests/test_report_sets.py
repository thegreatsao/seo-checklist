"""`checklist_report.py`'s hand-written tables, each held against what it describes.

`openspec/specs/governance/` GOV-3, the report's six. The census called six sets in
`checklist_report.py` unread. Measured on 1 October 2026 (`local/gov3/measure_report.py`,
`measure_import_blindness.py`, outside git): all six were correct on this tree, and **two
were never unread** — `test_report.py` imports `STATUS_ICON` and `FIX_STATUSES` and
asserts both, in a parenthesised import that spans lines, which the census's one-line
pattern could not see (`tests/test_derived_sets.py` holds that repair). The other four had
no reader at all:

* `CATEGORY_HELP` — one paragraph per category. A category added to the registry would
  render with an empty explanation and nothing would say so.
* `DIRECTION_HEADING`, `DIRECTION_NOTE` — the three kinds `checklist_runner.direction`
  can return. The kinds were also written out by hand twice more, as the tuple the
  Markdown and the HTML diff sections iterate; a fourth kind added to the runner and to
  the tables would have been classified, translated and never printed. Those loops now
  read the table.
* `FIX_COLUMNS` — the CSV header. `fix_rows` builds the rows with the same keys in a
  dict literal sixty lines away; a column added to one and not the other is a
  `ValueError` from `csv.DictWriter` on the first export, or a silently missing column
  in the JSON form.
"""
from __future__ import annotations

import ast
import csv
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(ROOT, "skills", "seo-checklist")
REPORT = os.path.join(SKILL, "scripts", "checklist_report.py")
sys.path.insert(0, os.path.join(SKILL, "scripts"))

import harness  # noqa: E402
import checklist_runner as runner  # noqa: E402
from checklist_report import (  # noqa: E402
    CATEGORY_HELP, DIRECTION_HEADING, DIRECTION_NOTE, FIX_COLUMNS, Lang, fix_rows,
    write_fixes,
)

ITEMS = harness.registry()["items"]

STATUSES = (runner.PASS, runner.WARN, runner.FAIL, runner.NO_DATA, runner.NEEDS_INPUT,
            runner.LLM_PENDING, runner.MANUAL, runner.NA)


class EveryCategoryIsExplained(unittest.TestCase):

    def test_the_help_covers_exactly_the_registrys_categories(self):
        self.assertEqual(set(CATEGORY_HELP), {item["category"] for item in ITEMS})

    def test_no_explanation_is_empty_or_shared(self):
        texts = [text.strip() for text in CATEGORY_HELP.values()]
        self.assertTrue(all(texts))
        self.assertEqual(len(set(texts)), len(texts),
                         "two categories carry the same paragraph")

    def test_a_shipped_language_explains_the_same_categories(self):
        self.assertEqual(set(Lang("ru").data.get("categories", {})), set(CATEGORY_HELP))


class TheDiffPrintsEveryDirectionTheRunnerCanReturn(unittest.TestCase):

    def returned(self):
        return {runner.direction(was, now)
                for was in STATUSES for now in STATUSES if was != now}

    def test_both_tables_name_exactly_the_kinds_direction_returns(self):
        self.assertEqual(set(DIRECTION_HEADING), self.returned())
        self.assertEqual(set(DIRECTION_NOTE), self.returned())

    def test_each_kind_has_its_own_key_and_wording(self):
        for table in (DIRECTION_HEADING, DIRECTION_NOTE):
            keys = [key for key, _default in table.values()]
            defaults = [default for _key, default in table.values()]
            self.assertEqual(len(set(keys)), len(keys))
            self.assertEqual(len(set(defaults)), len(defaults))
            self.assertTrue(all(default.strip() for default in defaults))
        self.assertFalse({k for k, _ in DIRECTION_HEADING.values()}
                         & {k for k, _ in DIRECTION_NOTE.values()})

    def test_the_kinds_are_written_once(self):
        """The Markdown and the HTML diff sections iterated a tuple of the three kinds
        written out beside the tables. A sequence literal holding exactly the kinds is
        a second copy of the table's keys."""
        with open(REPORT, encoding="utf-8") as stream:
            tree = ast.parse(stream.read())
        kinds = set(DIRECTION_HEADING)
        copies = [node.lineno for node in ast.walk(tree)
                  if isinstance(node, (ast.Tuple, ast.List, ast.Set))
                  and node.elts
                  and all(isinstance(e, ast.Constant) for e in node.elts)
                  and {e.value for e in node.elts} == kinds]
        self.assertEqual(copies, [],
                         "iterate DIRECTION_HEADING instead of a copy of its keys")


class TheFixListHasTheColumnsItsHeaderNames(unittest.TestCase):

    DATA = {"url": "https://example.com/", "items": [
        {"id": "X-001", "status": runner.FAIL, "severity": "high", "effort": "low",
         "category": "content", "category_label": "Content", "title": "A title",
         "fix": "Do it", "evidence": "measured"}]}

    def test_a_row_carries_the_header_in_order(self):
        rows = fix_rows(self.DATA)
        self.assertEqual(len(rows), 1)
        self.assertEqual(tuple(rows[0]), FIX_COLUMNS)

    def test_the_csv_header_is_the_columns(self):
        with tempfile.TemporaryDirectory() as folder:
            path = write_fixes(os.path.join(folder, "fixes.csv"), self.DATA)
            with open(path, encoding="utf-8-sig", newline="") as stream:
                header = next(csv.reader(stream))
        self.assertEqual(tuple(header), FIX_COLUMNS)


if __name__ == "__main__":
    unittest.main()
