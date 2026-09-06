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


class TheHarnessSaysWhatItCannotExercise(unittest.TestCase):
    """`openspec/specs/declarations/` DEC-13. An item that gave one answer everywhere is
    a question for a person, and what the mechanism cannot express has to be written
    where the output is read — otherwise each reader re-derives it and the third one
    files it as a defect.

    Four items need a 5xx, a redirect chain, a redirect loop, or a status that varies by
    user agent. A static file server produces none of those, so those four can never be
    seen failing here, and that is a fact about the harness rather than about the
    registry.

    Two of the three clauses hold and are pinned below. The third — that the *census
    output itself* says so, rather than a README beside the trees — does not exist, and
    is pinned as an absence in the same shape `openspec/specs/http/` HTTP-8 uses: a test
    written to fail on the day the gap closes, saying in its own message what to replace
    it with.
    """

    README = os.path.join(ROOT, "tests", "corpus", "README.md")

    @classmethod
    def unexercisable(cls):
        """The ids the corpus README names as impossible here, read from the README.

        Derived rather than retyped. The list is hand-kept — DEC-6's objection applies
        to it exactly as it does to the manifest — so reading it is what makes the
        drift visible instead of duplicating it here.
        """
        import re
        with open(cls.README, encoding="utf-8") as stream:
            text = stream.read()
        start = text.index("## What a corpus tree can and cannot express")
        end = text.find(chr(10) + "## ", start + 1)
        section = text[start:end if end != -1 else len(text)]
        return sorted(set(re.findall(r"`([A-Z]{2,4}-\d+)`", section)))

    def setUp(self):
        with open(CENSUS, encoding="utf-8") as stream:
            self.census = json.load(stream)

    def test_the_items_it_names_are_items(self):
        """A list of ids nobody resolves is a list that outlives the ids in it."""
        named = self.unexercisable()
        self.assertTrue(named, "the README section names no ids; this test is vacuous")
        missing = [i for i in named if i not in self.census["items"]]
        self.assertEqual(missing, [],
                         "the corpus README names items the registry does not have")

    def test_none_of_them_was_ever_seen_failing(self):
        """The claim itself. If one of these does fail on some tree, the harness grew a
        capability the README says it lacks, and the sentence is now wrong."""
        for item_id in self.unexercisable():
            with self.subTest(item=item_id):
                distinct = self.census["items"][item_id]["distinct"]
                self.assertNotIn(
                    "FAIL", distinct,
                    f"{item_id} failed somewhere, so the corpus can express what the "
                    f"README says it cannot — update the README, not this test")

    def test_the_census_still_knows_nothing_of_the_limit(self):
        """The half DEC-13 asks for and the tree does not do.

        The output *does* print these four ids — as members of the group they inflate,
        the way it prints every id in every group. What it never does is mark them as
        items no tree here can exercise, so a reader sees them beside items that simply
        did not fail and cannot tell the two apart. The connection lives only in a
        README beside the fixtures, which is the Reader line's own complaint.

        Pinned structurally, because that is where the absence is: the census tool has
        no reference to the corpus README and no knowledge of any of the four ids. This
        goes red on the day somebody gives it one, and says what to replace it with.
        """
        with open(os.path.join(ROOT, "tests", "verdict_census.py"),
                  encoding="utf-8") as stream:
            source = stream.read()
        knows = [t for t in ["corpus/README", "corpus" + chr(92) + "README"]
                            + self.unexercisable()
                 if t in source]
        self.assertEqual(
            knows, [],
            "the census now knows which items the harness cannot exercise — good; "
            "replace this test with one asserting the output marks them, and close "
            "DEC-13 in openspec/specs/declarations/")


if __name__ == "__main__":
    unittest.main()
