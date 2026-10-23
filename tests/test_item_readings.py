"""REG-6's reader: every rule-carrying item has a current reading against its title.

`tools/audit_item_readings.py` holds the check; this runs it in the suite, so a changed
rule is red on the machine that changed it and not only in CI, and probes each way a
reading can fall out of step. See the tool's docstring for what it does not do.
"""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "skills", "seo-checklist", "tools")
sys.path.insert(0, TOOLS)

import audit_item_readings as R  # noqa: E402

REGISTRY = R.load(R.REGISTRY)
READINGS = R.load(R.READINGS)

# The suite's switches and tripwire, also when this module runs alone (GOV-7).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402,F401


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
        # 0.119.0: MB-095 reads Lighthouse's page weight (owed -> answers).
        # 0.120.0: MS-030 reads the calibrated band, with a statement for *Clear &
        # Relevant* (owed -> measures).
        # 0.121.0: TE-175 reads mixed content, with a statement for the page's other
        # errors (owed -> measures).
        # 0.122.0: the brand is a name the site publishes or the operator supplies.
        # KW-070 reads both halves of its title (owed -> answers); GO-139 carries a
        # statement for the rest of the brand's results page (owed -> measures). None
        # owed.
        # 0.129.0: MB-104 reads Google's favicon requirements and carries a statement
        # for the brand and URL-stability halves it cannot read (answers -> measures).
        # 0.130.0: CI-003 reads the status class and carries a statement naming the
        # items that read the rest of the site (answers -> measures).
        self.assertEqual(counts, {"answers": 114, "measures": 31, "owed": 0})

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
        before = entry["reading"]
        entry["reading"] = before.replace("`summary.server_errors`", "the count")
        # The mutation must happen, or this passes over an unchanged reading: it did at
        # 0.128.0, when the path it cut out stopped being CI-015's.
        self.assertNotEqual(entry["reading"], before)
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


class ASecondReadingIsOfTheCurrentReading(unittest.TestCase):
    """F03: a second reader's record sits in the entry it read, bound by a digest to what
    it judged. A record that no longer matches is named; one that is absent or disputes
    the first reading is counted, not named, until the plan's last batch."""

    def setUp(self):
        self.registry = copy.deepcopy(REGISTRY)
        self.readings = copy.deepcopy(READINGS)
        self.items = {i["id"]: i for i in self.registry["items"]}
        self.entry = self.readings["items"]["TE-167"]
        self.entry["second_reading"] = {
            "reader": "codex gpt-6.1-sol high", "session": "s-1",
            "read": R.digest(self.items["TE-167"], self.entry),
            "verdict": self.entry["verdict"]}

    def found(self):
        return R.problems(self.registry, self.readings)

    def test_a_current_record_is_no_problem_and_is_counted(self):
        self.assertEqual(self.found(), [])
        self.assertEqual(R.second_readings(self.registry, self.readings),
                         {"current": 1, "agree": 1, "disputed": 0})

    def test_the_digest_ignores_key_order_and_the_record_itself(self):
        """Nested order too (Codex's review of 22c5f62: reordering only the entry's own
        keys passed with `sort_keys` gone)."""
        def reverse(value):
            if isinstance(value, dict):
                return {k: reverse(v) for k, v in reversed(list(value.items()))}
            return value
        item = self.items["CN-048"]
        entry = self.readings["items"]["CN-048"]
        before = R.digest(item, entry)
        reordered = reverse(entry)
        reordered["second_reading"] = {"reader": "x"}
        self.assertEqual(R.digest(reverse(item), reordered), before)

    def test_the_digest_moves_with_everything_the_second_reader_judged(self):
        item = self.items["TE-167"]
        before = R.digest(item, self.entry)
        changes = (
            ("title", lambda i, e: i.__setitem__("title", i["title"] + "!")),
            ("check", lambda i, e: i["check"].__setitem__("args", ["{other}"])),
            ("measures", lambda i, e: i.__setitem__("measures", i["measures"] + " More.")),
            ("verdict", lambda i, e: e.__setitem__("verdict", "answers")),
            ("reading", lambda i, e: e.__setitem__("reading", e["reading"] + " More.")),
            ("shapes", lambda i, e: e.__setitem__("shapes", {"qualifier": "x"})),
        )
        for name, change in changes:
            with self.subTest(name):
                i, e = copy.deepcopy(item), copy.deepcopy(self.entry)
                change(i, e)
                self.assertNotEqual(R.digest(i, e), before)

    def test_a_changed_reading_makes_the_record_stale(self):
        self.entry["reading"] += " Amended."
        self.assertTrue(named(self.found(), "TE-167", "changed under its second reading"))
        self.assertEqual(R.second_readings(self.registry, self.readings)["current"], 0)

    def test_a_changed_measures_sentence_makes_the_record_stale(self):
        self.items["TE-167"]["measures"] += " Amended."
        self.assertTrue(named(self.found(), "TE-167", "changed under its second reading"))

    def test_each_malformed_record_is_named(self):
        cases = (
            ("not an object", "a string", "not an object"),
            ("unknown key", {"agrees": True}, "carries keys"),
            ("empty reader", {"reader": " "}, "no reader"),
            ("no session", {"session": None}, "no session"),
            ("no digest", {"read": ""}, "no read"),
            ("unknown verdict", {"verdict": "fine"}, "is not one of"),
            # Codex's review of 22c5f62: `str()` let `true` and `[null]` stand for a
            # reader and a session, and the record was counted current.
            ("reader not text", {"reader": True}, "no reader"),
            ("session not text", {"session": [None]}, "no session"),
            ("dispute not text", {"dispute": ["x"]}, "dispute"),
        )
        for name, change, words in cases:
            with self.subTest(name):
                record = copy.deepcopy(self.entry["second_reading"])
                if isinstance(change, dict):
                    record.update(change)
                else:
                    record = change
                readings = copy.deepcopy(self.readings)
                readings["items"]["TE-167"]["second_reading"] = record
                self.assertTrue(named(R.problems(self.registry, readings), "TE-167", words))
                self.assertEqual(R.second_readings(self.registry, readings)["current"], 0)

    def test_a_dispute_is_counted_and_not_a_problem(self):
        for change in ({"verdict": "owed"}, {"dispute": "reads half the title"}):
            with self.subTest(change):
                readings = copy.deepcopy(self.readings)
                readings["items"]["TE-167"]["second_reading"].update(change)
                self.assertEqual(R.problems(self.registry, readings), [])
                self.assertEqual(R.second_readings(self.registry, readings),
                                 {"current": 1, "agree": 0, "disputed": 1})

    def test_the_record_defines_the_five_keys_the_plan_names(self):
        """A sixth key is a decision about what a second reading says, not a drift."""
        self.assertEqual(set(R.SECOND_READING),
                         {"reader", "session", "read", "verdict", "dispute"})

    def test_the_shipped_file_is_counted(self):
        counts = R.second_readings(REGISTRY, READINGS)
        self.assertEqual(counts, {"current": 0, "agree": 0, "disputed": 0})


class TheDigestCommand(unittest.TestCase):
    def run_tool(self, *args):
        return subprocess.run(
            [sys.executable, os.path.join(TOOLS, "audit_item_readings.py"), *args],
            capture_output=True, encoding="utf-8",
            env=dict(os.environ, PYTHONIOENCODING="utf-8"), close_fds=False)

    def test_it_prints_the_digest_of_a_read_item(self):
        done = self.run_tool("--digest", "TE-167")
        self.assertEqual(done.returncode, 0, done.stderr)
        items = {i["id"]: i for i in REGISTRY["items"]}
        self.assertEqual(done.stdout.strip(),
                         R.digest(items["TE-167"], READINGS["items"]["TE-167"]))

    def test_it_refuses_an_id_with_no_reading(self):
        done = self.run_tool("--digest", "ZZ-999")
        self.assertEqual(done.returncode, 1)
        self.assertIn("ZZ-999", done.stdout + done.stderr)

    def test_the_summary_counts_second_readings(self):
        done = self.run_tool()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn(f"second readings: 0 of {len(READINGS['items'])} current — 0 agree, "
                      "0 disputed", done.stdout)


class WhatTheSecondReaderIsShown(unittest.TestCase):
    """F03-2: the blind pass shows the item and its script and nothing of the first
    reading; the open pass then shows the first reading. The brief is the fixed prompt."""

    def setUp(self):
        self.items = R.rule_items(REGISTRY)

    def blind(self, *ids):
        return R.blind_input([(i, self.items[i]) for i in ids], R.sources(
            self.items[i] for i in ids))

    def test_it_carries_the_title_check_measures_and_source(self):
        text = self.blind("CN-065")
        item = self.items["CN-065"]
        self.assertIn(item["title"], text)
        self.assertIn(json.dumps(item["check"], sort_keys=True, ensure_ascii=False), text)
        self.assertIn(item["measures"], text)
        with open(os.path.join(R.SCRIPTS, "parse_html.py"), encoding="utf-8") as f:
            self.assertIn(f.read().rstrip("\n"), text)

    def test_it_says_when_there_is_no_measures_sentence(self):
        self.assertNotIn("measures", self.items["CN-066"])
        self.assertIn("Measures: (none", self.blind("CN-066"))

    def test_each_script_once(self):
        text = self.blind("CN-065", "CN-066", "CN-036")
        self.assertEqual(text.count("### Script parse_html.py"), 1)
        self.assertEqual(text.count("### Script rendered_audit.py"), 1)

    def test_nothing_of_the_first_reading(self):
        for item_id, entry in READINGS["items"].items():
            with self.subTest(item_id):
                text = self.blind(item_id)
                self.assertNotIn(entry["reading"], text)
                for answer in (entry.get("shapes") or {}).values():
                    self.assertNotIn(answer, text)

    def test_the_open_pass_shows_the_first_reading(self):
        entry = READINGS["items"]["CN-065"]
        text = R.open_input("CN-065", entry)
        self.assertIn(entry["verdict"], text)
        self.assertIn(entry["reading"], text)
        for answer in entry["shapes"].values():
            self.assertIn(answer, text)

    def test_the_brief_names_both_passes_and_the_three_verdicts(self):
        with open(R.BRIEF, encoding="utf-8") as f:
            brief = f.read()
        for words in ("## Blind pass", "## Open pass", *R.VERDICTS):
            self.assertIn(words, brief)


class TheReadOnlyCommands(unittest.TestCase):
    def run_tool(self, *args):
        return subprocess.run(
            [sys.executable, os.path.join(TOOLS, "audit_item_readings.py"), *args],
            capture_output=True, encoding="utf-8",
            env=dict(os.environ, PYTHONIOENCODING="utf-8"), close_fds=False)

    def test_blind_prints_each_item(self):
        done = self.run_tool("--blind", "CN-065", "CN-066")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("### Item CN-065", done.stdout)
        self.assertIn("### Item CN-066", done.stdout)
        self.assertEqual(done.stdout.count("### Script parse_html.py"), 1)
        self.assertNotIn(READINGS["items"]["CN-065"]["reading"], done.stdout)

    def test_open_prints_each_first_reading(self):
        done = self.run_tool("--open", "CN-065")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn(READINGS["items"]["CN-065"]["reading"], done.stdout)

    def test_both_refuse_an_id_with_no_reading(self):
        for flag in ("--blind", "--open"):
            with self.subTest(flag):
                done = self.run_tool(flag, "CN-065", "ZZ-999")
                self.assertEqual(done.returncode, 1)
                # Refused, not crashed: a KeyError also exits 1 and names the id.
                self.assertIn("ZZ-999: no reading", done.stdout)
                self.assertEqual(done.stderr, "")


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
