"""F15 batch 7: Search Console and the links export — `gsc_cannibalization.py`,
`gsc_links_csv.py`, `gsc_checker.py`, `gsc_sitemap_reconcile.py` — as the owner ruled
them (docs/sprint-20261109-F15.md), and the owner's rulings 1-2 on batch 6's questions
(TECH-002 leaves icon fonts out; TE-174 reads only the site's own stylesheets).

Each verdict is the item's real rule from the registry over the script's real output.
Search Console is stood in for by `test_evidence_apis._Query`; pages are served on
loopback.
"""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "skills", "seo-checklist", "scripts")
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import css_minify_check  # noqa: E402
import font_audit  # noqa: E402
import gsc_cannibalization  # noqa: E402
import gsc_links_csv  # noqa: E402
from checklist_runner import FAIL, NA, NO_DATA, PASS, WARN  # noqa: E402
from test_evidence_apis import _Query, verdict  # noqa: E402
from test_f15_batch4 import ITEMS  # noqa: E402
from test_f15_batch5 import html, page_verdict, run_item  # noqa: E402
from test_f15_batch6 import UNMINIFIED, graded  # noqa: E402

MINIFIED = "a{b:c}" * 500
CSS = {"Content-Type": "text/css"}


# ---------------------------------------------------------------------------
# The owner's ruling 1 on batch 6's questions: TECH-002 and icon fonts
# ---------------------------------------------------------------------------

class IconFonts(unittest.TestCase):
    def tech(self, family: str, display: str = "font-display: block") -> str:
        face = ("@font-face{font-family:%s;src:url(/x.woff2) format('woff2');%s}"
                % (family, display))
        return page_verdict(font_audit, "TECH-002", html("<p>x</p>", head=f"<style>{face}</style>"))

    def test_an_icon_font_is_not_read_for_font_display(self):
        for family in ('"Font Awesome 6 Free"', "'Font Awesome 5 Brands'", "FontAwesome",
                       '"Material Icons"', '"Material Icons Outlined"',
                       '"Material Symbols Rounded"', '"Glyphicons Halflings"',
                       "bootstrap-icons", "dashicons", "Ionicons"):
            for display in ("font-display: block", "font-display: auto", ""):
                with self.subTest(family=family, display=display):
                    self.assertEqual(self.tech(family, display), PASS)

    def test_a_text_font_still_fails(self):
        for family in ("Roboto", '"Open Sans"', '"Awesome Serif"', '"Icons Grotesk"'):
            with self.subTest(family=family):
                self.assertEqual(self.tech(family), FAIL)

    def test_the_sentence_names_the_list(self):
        sentence = ITEMS["TECH-002"]["measures"]
        for name in ("Font Awesome", "Material Icons", "Material Symbols"):
            with self.subTest(name=name):
                self.assertIn(name, sentence)

    def test_the_closed_list_is_the_one_the_sentence_names(self):
        from font_audit import ICON_FONT_FAMILIES
        named = ("Font Awesome", "Material Icons", "Material Symbols", "Glyphicons",
                 "Bootstrap Icons", "Dashicons", "Ionicons")
        self.assertEqual(ICON_FONT_FAMILIES,
                         tuple(name.lower().replace(" ", "") for name in named))
        for name in named:
            with self.subTest(name=name):
                self.assertIn(name, ITEMS["TECH-002"]["measures"])


# ---------------------------------------------------------------------------
# The owner's ruling 2 on batch 6's questions: TE-174 reads the site's own sheets
# ---------------------------------------------------------------------------

class OwnStylesheets(unittest.TestCase):
    """`{other}` is the same loopback server reached as `localhost`: another site."""

    def te(self, head: str, routes: dict) -> dict:
        routes = dict(routes)
        routes["/"] = html("<p>x</p>", head=head)
        return run_item(css_minify_check, "TE-174", routes)

    def test_a_third_party_sheet_is_left_out(self):
        out = self.te('<link rel="stylesheet" href="/ok.css">'
                      '<link rel="stylesheet" href="{other}/fonts.css">',
                      {"/ok.css": (200, CSS, MINIFIED), "/fonts.css": (200, CSS, UNMINIFIED)})
        self.assertEqual(graded("TE-174", out), PASS)
        self.assertEqual([row["href"].rsplit("/", 1)[-1] for row in out["stylesheets"]],
                         ["ok.css"])
        self.assertEqual([href.rsplit("/", 1)[-1] for href in out["third_party_sheets"]],
                         ["fonts.css"])

    def test_a_third_party_import_is_left_out(self):
        out = self.te("<style>@import url('{other}/fonts.css');</style>"
                      '<link rel="stylesheet" href="/ok.css">',
                      {"/ok.css": (200, CSS, MINIFIED), "/fonts.css": (200, CSS, UNMINIFIED)})
        self.assertEqual(graded("TE-174", out), PASS)

    def test_a_page_with_only_third_party_sheets_has_none_to_read(self):
        out = self.te('<link rel="stylesheet" href="{other}/fonts.css">',
                      {"/fonts.css": (200, CSS, UNMINIFIED)})
        self.assertEqual(graded("TE-174", out), NA)

    def test_an_unminified_own_sheet_still_fails(self):
        out = self.te('<link rel="stylesheet" href="/big.css">'
                      '<link rel="stylesheet" href="{other}/fonts.css">',
                      {"/big.css": (200, CSS, UNMINIFIED), "/fonts.css": (200, CSS, MINIFIED)})
        self.assertEqual(graded("TE-174", out), FAIL)

    def test_a_sheet_on_the_sites_own_subdomain_is_its_own(self):
        own = css_minify_check.own_sheet
        self.assertTrue(own("https://www.bakery.co.uk/", "https://static.bakery.co.uk/site.css"))
        self.assertTrue(own("https://bakery.example/", "https://cdn.bakery.example/a.css"))
        self.assertFalse(own("https://bakery.example/", "https://fonts.googleapis.com/css2?f=x"))
        self.assertFalse(own("https://bakery.co.uk/", "https://other.co.uk/a.css"))
        # The Public Suffix List's private section: two sites on one platform.
        self.assertFalse(own("https://alice.github.io/", "https://bob.github.io/a.css"))

    def test_the_sentence_says_third_party_sheets_are_left_out(self):
        self.assertIn("third-party", ITEMS["TE-174"]["measures"].lower())


# ---------------------------------------------------------------------------
# gsc_cannibalization.py — MS-023 (fix); GO-139, KW-070, KW-071 (measures)
# ---------------------------------------------------------------------------

def gsc_rows(triples):
    return [{"keys": list(keys), "clicks": clicks, "impressions": impressions,
             "ctr": 0.05, "position": position}
            for keys, clicks, impressions, position in triples]


def cannibalization(rows, brand=None, source="operator"):
    saved = gsc_cannibalization.build_service
    gsc_cannibalization.build_service = lambda *a, **k: _Query(rows=rows)
    try:
        return gsc_cannibalization.analyze(
            "https://example.com/", "/dev/null", 90, brand_names=brand,
            brand_source=source if brand else "",
            no_brand_reason="the homepage publishes no WebSite or organisation name "
                            "and no og:site_name; pass --brand")
    finally:
        gsc_cannibalization.build_service = saved


# The top-click query lands on the homepage and is split with an inner page: before
# the fix, with no brand given, it became the inferred "brand" and left the count.
SPLIT_HEAD = gsc_rows([
    (("sourdough bread", "https://example.com/"), 400, 2000, 1.2),
    (("sourdough bread", "https://example.com/blog/sourdough"), 60, 900, 1.9),
])


class GuessedBrand(unittest.TestCase):
    def test_with_no_brand_given_a_split_top_query_counts(self):
        out = cannibalization(SPLIT_HEAD)
        self.assertEqual(out["summary"]["cannibalized_queries"], 1)
        self.assertEqual(verdict("MS-023", out), WARN)
        self.assertEqual(verdict("KW-071", out), WARN)
        self.assertEqual(out["spread_brand"], {"source": "none", "names": []})

    def test_a_supplied_or_published_brand_still_drops_its_queries(self):
        for source in ("operator", "published"):
            with self.subTest(source=source):
                out = cannibalization(SPLIT_HEAD, brand=["Sourdough Bread"], source=source)
                self.assertEqual(out["summary"]["cannibalized_queries"], 0)
                self.assertEqual(verdict("MS-023", out), PASS)

    def test_a_full_page_with_no_brand_given_is_a_floor(self):
        """Nothing is dropped as branded without a brand, so a row past the cap can only
        add a page to a split: the count is a floor and MS-023's verdict stands."""
        filler = gsc_rows([((f"q{n}", f"https://example.com/p{n}"), 0, 1, 9.0)
                           for n in range(gsc_cannibalization.ROW_LIMIT - len(SPLIT_HEAD))])
        out = cannibalization(SPLIT_HEAD + filler)
        self.assertTrue(out["truncated"])
        self.assertEqual(out["summary"]["cannibalized_queries"], 1)
        self.assertNotEqual(verdict("MS-023", out), NO_DATA)


class CannibalizationSentences(unittest.TestCase):
    def test_go_139_says_the_page_with_most_impressions_averages_1_5(self):
        sentence = ITEMS["GO-139"]["measures"]
        self.assertNotIn("any of its pages", sentence)
        self.assertIn("1.5", sentence)
        self.assertIn("most impressions", sentence)

    def test_kw_070_says_an_average_of_1_5_is_first(self):
        sentence = ITEMS["KW-070"]["measures"]
        self.assertIn("1.5", sentence)
        self.assertIn("homepage", sentence)
        self.assertIn("average", sentence)

    def test_kw_071_names_its_band_its_floor_and_its_brand_filter(self):
        sentence = ITEMS["KW-071"]["measures"]
        for part in ("3.0", "10 impressions", "brand", "copy"):
            with self.subTest(part=part):
                self.assertIn(part, sentence)


# ---------------------------------------------------------------------------
# gsc_links_csv.py — BL-084, BL-086's missing sheet (fix); BL-083, BL-086, BL-087
# (measures)
# ---------------------------------------------------------------------------

def links(files: dict) -> dict:
    folder = tempfile.mkdtemp()
    for name, content in files.items():
        with open(os.path.join(folder, name), "w", encoding="utf-8") as stream:
            stream.write(content)
    return gsc_links_csv.analyze(folder, "https://example.com/")


ANCHORS = "Top linking text,Links\nexample,40\nclick here,3\n"


class LinksExport(unittest.TestCase):
    def test_bl_084_takes_the_largest_share_whatever_the_order(self):
        out = links({"top-linking-sites.csv": "Site,Links\nsmall.example,10\nbig.example,90\n"})
        self.assertEqual(out["concentration"]["top1_share_pct"], 90.0)
        self.assertEqual(verdict("BL-084", out), FAIL)

    def test_bl_084_top_ten_is_the_ten_largest(self):
        rows = "".join(f"s{n}.example,1\n" for n in range(10)) + "big.example,90\n"
        out = links({"top-linking-sites.csv": "Site,Links\n" + rows})
        self.assertEqual(out["concentration"]["top10_share_pct"], 99.0)

    def test_a_missing_linking_sites_sheet_is_no_data(self):
        out = links({"top-linking-text.csv": ANCHORS})
        for item in ("BL-084", "BL-086", "BL-087"):
            with self.subTest(item=item):
                self.assertEqual(verdict(item, out), NO_DATA)

    def test_an_empty_linking_sites_sheet_is_no_links(self):
        out = links({"top-linking-sites.csv": "Site,Links\n", "top-linking-text.csv": ANCHORS})
        self.assertEqual(verdict("BL-086", out), FAIL)
        self.assertEqual(verdict("BL-087", out), FAIL)

    def test_the_sentences(self):
        self.assertIn("final HTTP status", ITEMS["BL-083"]["measures"])
        self.assertIn("link counts", ITEMS["BL-086"]["measures"])
        self.assertIn("NO_DATA", ITEMS["BL-086"]["measures"])
        self.assertIn("at least five linking root domains in the export",
                      ITEMS["BL-087"]["measures"].lower())


# ---------------------------------------------------------------------------
# gsc_checker.py — GO-134; gsc_sitemap_reconcile.py — GO-137 (measures)
# ---------------------------------------------------------------------------

class SearchConsoleSentences(unittest.TestCase):
    def test_go_134_says_only_submitted_sitemaps_are_read(self):
        self.assertIn("submitted sitemaps", ITEMS["GO-134"]["measures"])

    def test_go_137_says_pages_with_impressions_in_28_days(self):
        self.assertIn("pages with impressions in 28 days", ITEMS["GO-137"]["measures"])


if __name__ == "__main__":
    unittest.main()
