"""MS-030 *Keep Meta Descriptions ~150–160 Characters (Clear & Relevant)*, and the one
length this tree has measured for that question.

Until 0.120.0 the registry asked for 120–165 characters while `article_seo.py` said
100–144 — two answers to one question in one tree, and only one of them measured.
`tools/calibration/serp-length.json` fits ordinary text in Arial at 14 px into the 920 px
desktop snippet at **144** characters; 155 overshoots it by 7 %, 165 by 14 %. So the old
ceiling passed a description the tree itself measured as cut, and so does the title's own
150–160. The floor of 100 is a convention, not a measurement, and it is the one the
calibration artifact records beside the ceiling.

MS-030 now reads `meta_description_band`, computed from `article_seo`'s two constants —
the ones the calibration check holds — and not from numbers written into the registry.
Whitespace is collapsed before counting, because a snippet shows it collapsed. A page
with no description, or an empty one, has no band: that is MS-028's subject, and one
fact is one item's.
"""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPTS = os.path.join(ROOT, "skills", "seo-checklist", "scripts")
REGISTRY = os.path.join(ROOT, "skills", "seo-checklist", "resources", "config",
                        "checklist.json")
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)

from checklist_runner import FAIL, NO_DATA, PASS, WARN, evaluate  # noqa: E402
import article_seo  # noqa: E402
import parse_html as ph  # noqa: E402


def rule() -> dict:
    with open(REGISTRY, encoding="utf-8") as f:
        return {i["id"]: i for i in json.load(f)["items"]}["MS-030"]["check"]


def verdict(output: dict) -> str:
    check = rule()
    ok, _ = evaluate(check["assert"], output)
    if ok is None:
        return NO_DATA
    if ok:
        return PASS
    warn = check.get("warn")
    if warn and evaluate(warn, output)[0]:
        return WARN
    return FAIL


def page(description=None) -> str:
    meta = ("" if description is None
            else f'<meta name="description" content="{description}">')
    return (f"<!doctype html><html lang=\"en\"><head><title>A page</title>{meta}"
            f"</head><body><h1>A page</h1></body></html>")


def parse(description=None) -> dict:
    return ph.parse_html(page(description), "https://example.com/")


class TheBandIsTheCalibratedOne(unittest.TestCase):

    def test_the_bounds_are_article_seos_constants(self):
        self.assertEqual(article_seo.META_MIN_CHARS, 100)
        self.assertEqual(article_seo.META_MAX_CHARS, 144)
        self.assertEqual(ph.META_DESCRIPTION_BANDS, ("short", "fits", "long"))

    def test_the_edges(self):
        cases = [(99, "short", FAIL), (100, "fits", PASS), (144, "fits", PASS),
                 (145, "long", FAIL)]
        for length, band, status in cases:
            with self.subTest(length=length):
                out = parse("x" * length)
                self.assertEqual(out["meta_description_chars"], length)
                self.assertEqual(out["meta_description_band"], band)
                self.assertEqual(verdict(out), status)

    def test_the_titles_own_range_is_cut_and_the_old_rule_passed_it(self):
        """155 characters: inside the old 120–165 and inside the title's 150–160, and
        7 % past the 920 px the calibration fits. The snippet cuts it."""
        out = parse("y" * 155)
        self.assertTrue(120 <= len(out["meta_description"]) <= 165)
        self.assertEqual(out["meta_description_band"], "long")
        self.assertEqual(verdict(out), FAIL)

    def test_whitespace_is_counted_the_way_a_snippet_shows_it(self):
        out = parse("  " + " ".join(["word"] * 25) + "\n\n   ")
        # 25 words of 4 letters and 24 single spaces
        self.assertEqual(out["meta_description_chars"], 124)
        self.assertEqual(out["meta_description_band"], "fits")

    def test_no_description_is_ms_028s_and_not_this_items(self):
        for description in (None, "", "   "):
            with self.subTest(description=description):
                out = parse(description)
                self.assertNotIn("meta_description_band", out)
                self.assertNotIn("meta_description_chars", out)
                self.assertEqual(verdict(out), NO_DATA)


class TheRuleNamesEveryBand(unittest.TestCase):

    def test_the_rule_reads_the_band_and_holds_no_number(self):
        check = rule()
        self.assertEqual(check["script"], "parse_html.py")
        self.assertEqual(check["assert"]["path"], "meta_description_band")
        self.assertEqual(set(check["assert"]["value_map"]),
                         set(ph.META_DESCRIPTION_BANDS))
        self.assertNotIn("warn", check)
        self.assertNotIn("len_between", json.dumps(check))


if __name__ == "__main__":
    unittest.main()
