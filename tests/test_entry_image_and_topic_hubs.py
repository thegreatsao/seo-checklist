"""Release 0.175.0 (F06): the two items the census showed could not fail, repaired by
Anton's decision rather than by a fixture.

**MD-184** *Confirm the Page References at Least One Image* asserted `count gte 1`, and
`image_inventory.py` writes `count` only when a page has an image — so the rule was PASS
or NO_DATA on every site. It could not fail for a reason: under `--sample` the worst page
decides, and in 0.49.0 a privacy page with no picture failed the exemplary fixture.
Decision: the entry page alone decides it — the URL the operator asked about fails when it
references no image, and sampled pages do not decide it.

**AR-153** *Design Clear Topic Hubs (Silos)* ran `topical_cluster_mapper.py` on one URL,
which maps one page into one cluster and scores 100. Decision: hand it the shared crawl,
so a topic's hub and its spokes are compared across the pages the crawl read. The topic of
a page is still a crude reading — the most frequent title word — so the words most titles
on the site share (a brand, a section name) are set aside before it is taken, and a crawl
cut at its caps does not decide the item.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "skills", "seo-checklist", "scripts")
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "skills", "seo-checklist", "tools"))

import harness  # noqa: E402
import checklist_runner as runner  # noqa: E402
from checklist_runner import FAIL, NO_DATA, PASS, grade  # noqa: E402
from registry_verdict import verdict  # noqa: E402

ITEMS = {item["id"]: item for item in harness.registry()["items"]}


class TheEntryAloneDecidesWhetherAPageReferencesAnImage(unittest.TestCase):

    def inventory_of(self, body: str) -> dict:
        import image_inventory
        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False,
                                         encoding="utf-8") as page:
            page.write(f"<!doctype html><html><head><title>t</title></head>"
                       f"<body>{body}</body></html>")
        try:
            return image_inventory.inventory(page.name)
        finally:
            os.unlink(page.name)

    def test_a_page_that_references_no_image_fails(self):
        out = self.inventory_of("<h1>Privacy</h1><p>No pictures here.</p>")
        self.assertEqual(verdict("MD-184", out), FAIL)

    def test_a_page_that_references_one_passes(self):
        out = self.inventory_of('<img src="/loaf.png" alt="A loaf">')
        self.assertEqual(verdict("MD-184", out), PASS)

    def test_the_other_image_items_still_say_nothing_about_a_page_with_none(self):
        """0.49.0's repair stands for the three that read the images themselves."""
        out = self.inventory_of("<p>No pictures here.</p>")
        for item_id in ("CI-016", "MD-186", "CN-054"):
            with self.subTest(item=item_id):
                self.assertNotIn(verdict(item_id, out), (PASS, FAIL))

    def test_the_build_table_is_the_registry_and_names_one_item(self):
        """`ENTRY_ONLY` is a hand-written set, so its membership is asserted here: one
        item, and the registry carries exactly what the table says."""
        from build_checklist import ENTRY_ONLY
        self.assertEqual(set(ENTRY_ONLY), {"MD-184"})
        self.assertEqual({i: item["check"]["entry_only"] for i, item in ITEMS.items()
                          if (item.get("check") or {}).get("entry_only")}, ENTRY_ONLY)

    def test_a_sampled_page_does_not_decide_it(self):
        """The 0.49.0 objection, answered by scope rather than by withholding: a
        privacy page in the sample cannot fail the site, because MD-184 is not folded
        across the sample at all. Its neighbours over the same script still are."""
        sampled = runner.sampled_item_ids(list(ITEMS.values()))
        self.assertNotIn("MD-184", sampled)
        self.assertIn("CI-016", sampled)


class TopicHubsAreReadAcrossTheCrawl(unittest.TestCase):

    ORIGIN = "https://bakery.test"

    def pages(self, titled: dict[str, str], links: dict[str, list[str]]) -> dict:
        row = {"status": 200, "html": True, "error": None, "depth": 1}
        return {f"{self.ORIGIN}{path}": {
                    **row, "final_url": f"{self.ORIGIN}{path}", "title": title,
                    "links": [{"internal": True, "target": f"{self.ORIGIN}{to}",
                               "anchor": "x"} for to in links.get(path, [])]}
                for path, title in titled.items()}

    def graded(self, pages: dict, truncated: bool = False) -> dict:
        import topical_cluster_mapper
        result = topical_cluster_mapper.map_inventory(
            {"site": f"{self.ORIGIN}/", "pages": pages,
             "summary": {"truncated": truncated}})
        key = ("topical_cluster_mapper.py", ())
        return grade([ITEMS["AR-153"]], {key: ["AR-153"]}, {key: result}, {}, False)[0]

    # Four pages on rye and four on other breads: rye is a topic, not the whole site.
    TITLES = {"/rye-bread": "Rye bread", "/rye-flour": "Rye flour",
              "/rye-starter": "Rye starter", "/rye-crackers": "Rye crackers",
              "/spelt": "Spelt loaf", "/brioche": "Brioche buns",
              "/bagels": "Bagels", "/scones": "Scones"}
    RYE = ["/rye-bread", "/rye-flour", "/rye-starter", "/rye-crackers"]

    def test_the_registry_hands_it_the_crawl(self):
        check = ITEMS["AR-153"]["check"]
        self.assertIn("{inventory_json}", check["args"])
        self.assertEqual(check["requires"], "crawl")

    def test_a_topic_whose_pages_do_not_link_each_other_fails(self):
        row = self.graded(self.pages(self.TITLES, {}))
        self.assertEqual(row["status"], FAIL, row["evidence"])

    def test_a_topic_whose_hub_and_spokes_link_both_ways_passes(self):
        hub, spokes = self.RYE[0], self.RYE[1:]
        links = {hub: spokes, **{spoke: [hub] for spoke in spokes}}
        row = self.graded(self.pages(self.TITLES, links))
        self.assertEqual(row["status"], PASS, row["evidence"])

    def test_a_word_every_title_shares_is_not_a_topic(self):
        """The false FAIL Anton was warned about: a brand leading every title made the
        whole site one cluster, and a site whose product pages do not all link to one
        another failed for a silo it never meant to build."""
        branded = {path: f"Shape Street Bakery | {title}"
                   for path, title in self.TITLES.items() if path not in self.RYE}
        branded["/"] = "Shape Street Bakery | Home"
        row = self.graded(self.pages(branded, {}))
        self.assertEqual(row["status"], PASS, row["evidence"])

    def test_a_page_with_no_topic_word_is_a_topic_of_its_own(self):
        """Found by F06's third review. A title the word pattern reads nothing in — one
        in Cyrillic or Greek, an empty one, one made only of site-wide words — gave
        every such page the topic "uncategorized", so a whole Russian-language site was
        one cluster whose hub had to link every page: the same structure scored 80 with
        Latin titles and failed with Cyrillic ones. A page with no readable topic word
        says nothing about which topic it belongs to, so it is its own cluster."""
        for label, titled in (
                ("cyrillic", {"/": "Главная", "/rye": "Хлеб ржаной", "/buns": "Булочки",
                              "/cookies": "Печенье", "/contact": "Контакты",
                              "/delivery": "Доставка"}),
                ("untitled", {path: "" for path in self.TITLES})):
            with self.subTest(titles=label):
                row = self.graded(self.pages(titled, {}))
                self.assertEqual(row["status"], PASS, row["evidence"])

    def test_a_crawl_cut_at_its_caps_does_not_decide_it(self):
        """A missing hub link is a share of the pages read; a page the cap left out
        can be the hub, so a cut crawl is undecided (as BL-081 since 0.171.0)."""
        row = self.graded(self.pages(self.TITLES, {}), truncated=True)
        self.assertEqual(row["status"], NO_DATA, row["evidence"])


if __name__ == "__main__":
    unittest.main()
