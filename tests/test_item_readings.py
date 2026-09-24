"""REG-6's reader: every rule-carrying item has a current reading against its title.

`tools/audit_item_readings.py` holds the check; this runs it in the suite, so a changed
rule is red on the machine that changed it and not only in CI, and probes each way a
reading can fall out of step. See the tool's docstring for what it does not do.
"""
from __future__ import annotations

import copy
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "skills", "seo-checklist", "tools")
sys.path.insert(0, TOOLS)

import audit_item_readings as R  # noqa: E402

REGISTRY = R.load(R.REGISTRY)
READINGS = R.load(R.READINGS)


def named(problems: list[str], item_id: str, words: str) -> bool:
    return any(line.startswith(f"{item_id}:") and words in line for line in problems)


class TheShippedReadingsDescribeTheRegistry(unittest.TestCase):
    def test_no_problem(self):
        self.assertEqual(R.problems(REGISTRY, READINGS), [])

    def test_the_verdicts_are_the_recorded_ones(self):
        # 0.114.0: one entry per item whose check runs a script (145). Fourteen owed:
        # nine rule repairs, KW-070 and GO-139 awaiting the branded-query decision, and
        # GO-135, GO-145, TE-174 owing a `measures` sentence.
        counts = {v: 0 for v in R.VERDICTS}
        for entry in READINGS["items"].values():
            counts[entry["verdict"]] += 1
        # 0.115.0: GEO-001 repaired (owed -> answers); AR-147 repaired for length and
        # given a statement for the rest, GO-135, GO-145, TE-174 given statements
        # (owed -> measures). Nine owed remain.
        # 0.116.0: CN-044 repaired to contact routes, with a statement (owed -> measures).
        # 0.117.0: AR-151 repaired (owed -> answers); TE-180 repaired with a statement
        # (owed -> measures).
        # 0.118.0: SE-117 asks the http:// address, with a statement for the rest of the
        # site (owed -> measures).
        self.assertEqual(counts, {"answers": 114, "measures": 26, "owed": 5})

    def test_the_file_keeps_the_shape_a_hand_edit_expects(self):
        """Line endings are normalised first: a Windows checkout writes CRLF, and how
        the file is *stored* is `test_line_endings`' question, not this one."""
        with open(R.READINGS, "rb") as f:
            text = f.read().decode("utf-8").replace("\r\n", "\n")
        again = json.dumps(json.loads(text), ensure_ascii=False, indent=2) + "\n"
        self.assertEqual(again, text)


class EachWayAReadingFallsOutOfStep(unittest.TestCase):
    def setUp(self):
        self.registry = copy.deepcopy(REGISTRY)
        self.readings = copy.deepcopy(READINGS)
        self.items = {i["id"]: i for i in self.registry["items"]}

    def found(self):
        return R.problems(self.registry, self.readings)

    def test_a_changed_title(self):
        self.items["CI-003"]["title"] = "Page Returns 2xx"
        self.assertTrue(named(self.found(), "CI-003", "title changed"))

    def test_a_changed_threshold(self):
        self.items["MS-020"]["check"]["assert"]["len_lte"] = 70
        self.assertTrue(named(self.found(), "MS-020", "rule changed"))

    def test_a_changed_warn_band(self):
        self.items["BL-084"]["check"]["warn"]["lte"] = 70
        self.assertTrue(named(self.found(), "BL-084", "rule changed"))

    def test_a_removed_reading(self):
        del self.readings["items"]["CI-005"]
        self.assertTrue(named(self.found(), "CI-005", "no reading"))

    def test_a_reading_for_an_item_with_no_rule(self):
        self.readings["items"]["ZZ-999"] = copy.deepcopy(self.readings["items"]["CI-005"])
        self.assertTrue(named(self.found(), "ZZ-999", "carries no rule"))

    def test_a_reading_that_stops_naming_its_path(self):
        entry = self.readings["items"]["CI-015"]
        entry["reading"] = entry["reading"].replace("`rows.0.status`", "the status")
        self.assertTrue(named(self.found(), "CI-015", "does not name the asserted path"))

    def test_measures_removed_from_an_item_read_as_measures(self):
        self.items["TE-167"].pop("measures")
        self.assertTrue(named(self.found(), "TE-167", "disagree"))

    def test_a_missing_shape_answer(self):
        self.readings["items"]["CN-048"]["shapes"].pop("conjunction")
        self.assertTrue(named(self.found(), "CN-048", "conjunction shape fires"))

    def test_an_answer_for_a_shape_that_does_not_fire(self):
        self.readings["items"]["CI-005"]["shapes"]["qualifier"] = "stale"
        self.assertTrue(named(self.found(), "CI-005", "no longer fires"))

    def test_an_unknown_verdict(self):
        self.readings["items"]["CI-005"]["verdict"] = "fine"
        self.assertTrue(named(self.found(), "CI-005", "is not one of"))


class TheShapesAreTheFourTheRequirementNames(unittest.TestCase):
    """REG-6's scenarios name an adjacent subject, a weaker question and half a title;
    the four shapes are how a reading is made to answer each. Held here so a fifth, or a
    lost one, is a decision rather than a drift."""

    def test_the_four_shapes(self):
        self.assertEqual(set(R.SHAPES),
                         {"external", "existential", "conjunction", "qualifier"})

    def test_each_outside_subject_fires_off_its_source_and_not_on_it(self):
        cases = (
            ("Ensure URL Is Indexed", "indexability_matrix.py", "gsc_url_inspection.py"),
            ("Fix Broken Backlinks", "broken_links.py", "gsc_links_csv.py"),
            ("Own Your Branded Query", "parse_html.py", "gsc_cannibalization.py"),
            ("Monitor Site Uptime", "indexability_matrix.py", "domain_safety_check.py"),
        )
        self.assertEqual(len(cases), len(R.EXTERNAL_SUBJECTS))
        for title, elsewhere, source in cases:
            with self.subTest(title):
                item = {"title": title, "check": {"script": elsewhere, "assert": {}}}
                self.assertIn("external", R.fired(item))
                item["check"]["script"] = source
                self.assertNotIn("external", R.fired(item))


class TheShapesWouldHaveExposedEveryItemRepairedByHand(unittest.TestCase):
    """The seven pairs as they stood at `v0.104.0`, before each was repaired. The word
    audit passed all seven; each must fire at least the shape named here."""

    HISTORY = (
        ("GO-137", "Reconcile Indexed Pages vs. Sitemaps", "orphan_pages_from_sitemap.py",
         {"path": "summary.orphan_pages", "eq": 0}, "external"),
        ("BL-083", "Fix Broken Backlinks (Redirect or Update Link)",
         "external_link_quality.py", {"path": "summary.broken_links", "eq": 0},
         "external"),
        ("MB-096", "Use Responsive Images", "image_weight_audit.py",
         {"path": "responsive_count", "gte": 1}, "existential"),
        ("MB-097", "Optimize Image Formats & Compression", "image_weight_audit.py",
         {"path": "modern_format_count", "gte": 1}, "existential"),
        ("MD-189", "Use Modern Formats & Responsive Images", "image_weight_audit.py",
         {"path": "responsive_count", "gte": 1}, "existential"),
        ("CI-016", "Provide Meaningful Image Alt Text", "image_inventory.py",
         {"path": "missing_alt", "eq": 0}, "qualifier"),
        ("MD-186", "Provide Meaningful Alt Text", "image_inventory.py",
         {"path": "missing_alt", "eq": 0}, "qualifier"),
    )

    def test_each_fires_its_shape(self):
        for item_id, title, script, rule, shape in self.HISTORY:
            with self.subTest(item_id):
                item = {"id": item_id, "title": title,
                        "check": {"script": script, "assert": rule}}
                self.assertIn(shape, R.fired(item))


if __name__ == "__main__":
    unittest.main()
