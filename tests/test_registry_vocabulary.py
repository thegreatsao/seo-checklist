"""`openspec/specs/registry/` §2.1 — the closed vocabularies — held against the registry.

REG-3 says the table in §2.1 is exhaustive and that "a new value is a change to this
document first". Until 0.132.0 nothing read the table. The suite held four of the five
fields against sets written out in `test_registry.py` (`VALID_SOURCES`, `VALID_SEVERITY`,
`VALID_EFFORT`, `VALID_REQUIRES`), which are a second copy of the table and not the table;
`lens` was held by the build (`LENS` against `LENS_AGENTS`, since 0.127.0) while REG-3's
own `Reader:` line still said nothing held it; and the column headed *distribution today*
was held by nothing at all.

Measured on 1 October 2026 (`local/gov3/measure_vocab_table.py`, outside git): four rows
were true and **`requires` had been stale for releases** — it said fetch 74 / api 11 /
gsc 8 where the registry has 72 / 12 / 9 — and 0.132.0 itself moved the `effort` row
(TE-176), which the plan for that release did not name: the same counts are written in
`openspec/specs/scoring/` §2.3, where `test_runner.py` reads them, and that reader is how
the move was noticed at all.

So the table is read here, both columns, in both directions: a value the registry uses
and the row does not list, a value the row lists and no item uses, and a count that is
not the registry's.
"""
from __future__ import annotations

import collections
import os
import re
import unittest

import harness  # noqa: E402
ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isdir(os.path.join(ROOT, "openspec")):
    ROOT = os.path.dirname(ROOT)
SPEC = os.path.join(ROOT, "openspec", "specs", "registry", "spec.md")

ITEMS = harness.registry()["items"]

# The fields REG-3 names, and where each one lives on an item. `requires` is the only one
# that is not a top-level key.
FIELDS = {
    "source": lambda item: item.get("source"),
    "severity": lambda item: item.get("severity"),
    "effort": lambda item: item.get("effort"),
    "lens": lambda item: item.get("lens"),
    "requires": lambda item: (item.get("check") or {}).get("requires"),
}
ROW = re.compile(r"^\| `(\w+)` \| ([^|\n]+) \| ([^|\n]+) \|$", re.M)


def section() -> str:
    with open(SPEC, encoding="utf-8") as stream:
        text = stream.read()
    return text.split("### 2.1 Closed vocabularies", 1)[1].split("\n## ", 1)[0]


def table() -> dict[str, dict[str, int]]:
    """Field -> {value: stated count}, in the order the row writes them."""
    rows = {}
    for field, values, counts in ROW.findall(section()):
        names = [value.strip() for value in values.split(",")]
        stated = [int(count) for count in counts.split("/")]
        if len(names) != len(stated):
            raise AssertionError(f"§2.1 `{field}`: {len(names)} values, {len(stated)} counts")
        rows[field] = dict(zip(names, stated, strict=True))
    return rows


def measured(field: str) -> collections.Counter:
    return collections.Counter(value for value in map(FIELDS[field], ITEMS)
                               if value is not None)


class TheTableIsTheVocabulary(unittest.TestCase):

    def test_the_table_has_a_row_for_each_field_reg_3_names(self):
        self.assertEqual(set(table()), set(FIELDS))

    def test_every_value_an_item_uses_is_listed(self):
        for field, row in table().items():
            with self.subTest(field=field):
                self.assertEqual(set(measured(field)) - set(row), set(),
                                 f"`{field}`: the registry uses a value §2.1 does not list")

    def test_every_listed_value_is_used(self):
        for field, row in table().items():
            with self.subTest(field=field):
                self.assertEqual(set(row) - set(measured(field)), set(),
                                 f"`{field}`: §2.1 lists a value no item carries")


class TheDistributionIsTodays(unittest.TestCase):

    def test_each_count_is_the_registrys(self):
        for field, row in table().items():
            with self.subTest(field=field):
                self.assertEqual(row, {value: measured(field)[value] for value in row})

    def test_the_items_without_a_check_are_counted(self):
        said = re.search(r"(\d+) items carry no `check`", section())
        self.assertIsNotNone(said, "§2.1 no longer says how many items carry no `check`")
        self.assertEqual(int(said.group(1)),
                         sum(1 for item in ITEMS if not item.get("check")))

    def test_a_field_every_item_carries_sums_to_the_registry(self):
        for field in ("source", "severity", "effort"):
            with self.subTest(field=field):
                self.assertEqual(sum(table()[field].values()), len(ITEMS))


if __name__ == "__main__":
    unittest.main()
