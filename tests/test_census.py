"""The recorded verdict census, kept in step with the registry it describes.

`tests/census.json` is a measurement, not a declaration: it records what every item
answered on every tree this repository can serve. Its value is the range — an item
that gave one answer everywhere is either a rule that cannot give another or a
question every site answers the same way, and those two are worth telling apart.

Recomputing it costs four full audits, so this module does not do that. It checks the
cheap invariants that make a stale record impossible to ignore: the census describes
*this* registry, and it describes every item in it. Re-record with

    python tests/verdict_census.py --out tests/census.json

whenever the registry moves, and read the report it prints while you are there.
"""
from __future__ import annotations

import json
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CENSUS = os.path.join(ROOT, "tests", "census.json")
REGISTRY = os.path.join(ROOT, "skills", "seo-checklist", "resources", "config",
                        "checklist.json")


def load(path: str) -> dict:
    with open(path, encoding="utf-8") as stream:
        return json.load(stream)


class RecordedCensus(unittest.TestCase):

    def setUp(self):
        self.census = load(CENSUS)
        self.registry = load(REGISTRY)

    def test_it_describes_this_registry(self):
        """A census taken against an older contract describes a checklist that no
        longer exists, and the difference is invisible from inside the file."""
        self.assertEqual(self.census["registry_version"],
                         self.registry["registry_version"],
                         "tests/census.json was taken against a different registry — "
                         "re-record it with tests/verdict_census.py")

    def test_every_item_is_accounted_for(self):
        self.assertEqual(set(self.census["items"]),
                         {i["id"] for i in self.registry["items"]})
        self.assertEqual(self.census["item_count"], self.registry["item_count"])

    def test_what_it_copies_from_the_registry_still_describes_it(self):
        """A census row is two things at once: one answer per served tree, which cost
        an audit each, and four fields copied from the registry, which cost nothing to
        re-read. Until now this module read neither kind. `registry_version` above was
        its whole staleness check — and a stamp cannot drift on its own, because
        `verdict_census.py` takes it from the same registry load the titles come from.
        Which is exactly the trouble: **the one field the suite read was the one field
        an edit could set.**

        Measured rather than reasoned. `tests/census.json` shipped `GO-143` as
        *Provide Complete WebSite Data for the Site Name*, the first of two titles the
        item was given inside 0.89.0, under `registry_version` `b0abf2819da0`. A
        registry carrying that first title hashes to `872e9c3fd2fc`, so no single
        recording can produce the file as it shipped: the content was taken while the
        first title stood and the stamp was moved onto it afterwards, the way the
        release ritual moves a stamp when the registry has changed under a record that
        costs five audits to re-take. The title survived two further releases, and the
        test above passed on every one of them.

        The copies stay — a record that named only ids could not be read beside the
        registry it was taken from, and an archived one could not be read at all. What
        changes is that they are read, in both directions, so an item recorded and no
        longer in the registry and an item in the registry and never recorded both
        fail here and not only in the sibling test above. Re-record with

            python tests/verdict_census.py --out tests/census.json
        """
        items = {item["id"]: item for item in self.registry["items"]}
        for item_id in sorted(set(items) | set(self.census["items"])):
            with self.subTest(item=item_id):
                item = items.get(item_id)
                row = self.census["items"].get(item_id)
                self.assertIsNotNone(
                    item, f"{item_id} is recorded and is not in this registry")
                self.assertIsNotNone(
                    row, f"{item_id} is in this registry and was never censused")
                copied = {"title": item["title"],
                          "severity": item["severity"],
                          "source": item["source"],
                          "script": (item.get("check") or {}).get("script")}
                self.assertEqual(
                    {field: row.get(field) for field in copied}, copied,
                    f"{item_id}: the census copies a registry field that has since "
                    "moved — re-record it with tests/verdict_census.py --out")

    def test_every_item_was_asked_on_every_site(self):
        """A missing answer is the census failing to run an item, not an item
        declining to answer; the two must not be readable as the same thing."""
        sites = set(self.census["sites"])
        self.assertTrue(sites, "the census names no site")
        for item_id, row in self.census["items"].items():
            self.assertEqual(set(row["answers"]), sites, item_id)
            self.assertNotIn("MISSING", row["distinct"], item_id)


if __name__ == "__main__":
    unittest.main()
