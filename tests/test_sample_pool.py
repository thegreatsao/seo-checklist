"""No sampled verdict is decided by the crawl caps (F11, `openspec/specs/verdicts/` VRD-14).

`--sample N` folds N pages into one verdict per page-level item, worst page first. With a
crawl the pages are drawn from the ones it read, so a crawl stopped at `--crawl-max-pages`
or `--crawl-depth` decided which pages a sample could reach: F13 measured MS-020 `PASS`
on three pages of a three-page crawl and `FAIL` over the whole, CI-016 `N/A` over a
two-page crawl and `FAIL` over the whole, and a pool the cap shrank to the entry alone.
F13's first withholding keyed on the crawl's truncation and so also withheld a sample the
sitemap supplied, which no cap had cut.

So the pool says where it came from and whether it was cut (`discover_urls(report=)`),
and `withhold_cut_sample` turns, over a cut pool, a `PASS` and an `N/A` read off the pages
into `NO_DATA`; a `FAIL` found stands, a `WARN` stands as a floor, and an `N/A` decided by
scope before any page was read stands. The table is in `docs/sprint-20261020-F11-1.md`.
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "seo-checklist", "scripts"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import checklist_runner as r  # noqa: E402
from checklist_runner import FAIL, NA, NO_DATA, PASS, WARN  # noqa: E402
from harness import run_audit, served  # noqa: E402

ROBOTS = (200, {"Content-Type": "text/plain"}, "User-agent: *\nDisallow:\n")
BODY = ("Body copy with enough words to keep the thin-entry warning quiet. These pages "
        "differ in one thing only, so the item under test is the only one that moves, "
        "and the rest of the copy is here to make each of them a page.")


def page(title: str, links=(), body: str = "") -> str:
    anchors = "".join(f'<a href="{href}">{href}</a>' for href in links)
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<title>{title}</title>"
            '<meta name="description" content="Enough of a description to be one, and '
            'long enough that the length check has something to measure."></head>'
            f"<body><h1>{title}</h1><p>{BODY}</p>{body}{anchors}</body></html>")


def statuses(payload: dict, *ids: str) -> dict:
    rows = {row["id"]: row for row in payload["items"]}
    return {i: (rows[i]["status"], rows[i].get("evidence") or "") for i in ids}


class ASampleFromACappedCrawl(unittest.TestCase):
    """End to end, through the runner, on served sites. Each case runs the capped crawl
    and the same site uncapped, so the control proves the site is one the cap decides."""

    LONG = ("A title long enough to break the sixty character limit that MS-020 "
            "measures on every page")

    def title_site(self) -> dict:
        """Four pages one hop from the entry's links; the last one's title is too
        long. A three-page crawl reads `/`, `/p1`, `/p2` and never `/p3`."""
        routes = {"/": page("The entry page", ("/p1", "/p2", "/p3")),
                  "/p1": page("Page one of a small site"),
                  "/p2": page("Page two of a small site"),
                  "/p3": page(self.LONG),
                  "/robots.txt": ROBOTS}
        return routes

    def test_a_sampled_pass_from_a_capped_crawl_is_withheld(self):
        with served(self.title_site()) as site:
            capped = run_audit(site.url, "--sample", "4", "--crawl-max-pages", "3",
                               only="meta_structured")
            whole = run_audit(site.url, "--sample", "4", "--crawl-max-pages", "10",
                              only="meta_structured")
        status, evidence = statuses(capped, "MS-020")["MS-020"]
        self.assertEqual(status, NO_DATA, evidence)
        self.assertIn("--crawl-max-pages 3", evidence)
        self.assertEqual(statuses(whole, "MS-020")["MS-020"][0], FAIL,
                         "the control: the whole site fails")

    def test_a_pool_the_cap_shrank_to_the_entry_is_withheld(self):
        with served(self.title_site()) as site:
            payload = run_audit(site.url, "--sample", "3", "--crawl-max-pages", "1",
                                only="meta_structured")
        self.assertEqual(payload["sampled_urls"], [])
        status, evidence = statuses(payload, "MS-020")["MS-020"]
        self.assertEqual(status, NO_DATA, evidence)
        self.assertIn("--crawl-max-pages 1", evidence)

    def test_a_sampled_not_applicable_from_a_capped_crawl_is_withheld(self):
        """CI-016 applies when a page has images. Only the third page does, and its alt
        says nothing; a two-page crawl never reads it."""
        routes = {"/": page("The entry page", ("/p1", "/p2")),
                  "/p1": page("Page one of a small site"),
                  "/p2": page("Page two of a small site",
                              body='<img src="/a.png" alt="image" width="10" height="10">'),
                  "/a.png": (200, {"Content-Type": "image/png"}, "png"),
                  "/robots.txt": ROBOTS}
        with served(routes) as site:
            capped = run_audit(site.url, "--sample", "3", "--crawl-max-pages", "2")
            whole = run_audit(site.url, "--sample", "3", "--crawl-max-pages", "10")
        status, evidence = statuses(capped, "CI-016")["CI-016"]
        self.assertEqual(status, NO_DATA, evidence)
        self.assertEqual(statuses(whole, "CI-016")["CI-016"][0], FAIL,
                         "the control: the whole site fails")


SITE = "https://e.test/"


def urlset(*urls: str) -> str:
    return ('<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/'
            'sitemap/0.9">' + "".join(f"<url><loc>{u}</loc></url>" for u in urls)
            + "</urlset>")


def index(*urls: str) -> str:
    return ('<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/'
            'sitemap/0.9">' + "".join(f"<sitemap><loc>{u}</loc></sitemap>" for u in urls)
            + "</sitemapindex>")


class WhereThePoolCameFrom(unittest.TestCase):
    """`discover_urls(report=)`: the source and the cut, per row of the contract's table."""

    def discover(self, docs: dict, inventory=None, limit=5):
        import lib.safe_http as safe_http

        def get(url, **_kwargs):
            if url in docs:
                return mock.Mock(text=docs[url])
            raise OSError("not served")

        report: dict = {}
        with mock.patch.object(safe_http, "safe_get", get), \
                mock.patch.object(safe_http, "robots_allows", return_value=(True, "")):
            found = r.discover_urls(SITE, limit, inventory, report=report)
        return found, report

    @staticmethod
    def inventory(truncated=False, html=True, walk=None):
        pages = {SITE + p: {"html": html, "status": 200} for p in ("", "a", "b")}
        return {"pages": pages, "max_pages": 3, "depth": 3,
                "summary": {"truncated": truncated},
                "sitemap": {"urls": [], **(walk or {})}}

    def test_a_complete_crawl_is_an_uncut_pool(self):
        found, report = self.discover({}, self.inventory())
        self.assertEqual(report, {"source": "crawl", "cut": ""})
        self.assertEqual(len(found), 3)

    def test_a_truncated_crawl_is_a_cut_pool_that_names_the_caps(self):
        inventory = self.inventory(truncated=True)
        inventory["summary"].update(pages_fetched=3, unchecked_internal_targets=1)
        _found, report = self.discover({}, inventory)
        self.assertEqual(report["source"], "crawl")
        self.assertIn("--crawl-max-pages 3", report["cut"])
        self.assertIn("--crawl-depth 3", report["cut"])

    def test_a_crawl_seeded_from_a_cut_sitemap_set_is_a_cut_pool(self):
        """Not truncated, but a sitemap file past the walk's limits was never read, so
        the pages only it lists never entered the crawl."""
        _found, report = self.discover(
            {}, self.inventory(walk={"unvisited": [SITE + "s26.xml"]}))
        self.assertEqual(report["source"], "crawl")
        self.assertIn("sitemap", report["cut"])

    def test_a_sitemap_sample_after_a_cut_crawl_is_not_withheld(self):
        """F13's review: the crawl read no page eligible to be sampled, the sitemap
        supplied the pool, and no cap shortened the sitemap."""
        docs = {SITE + "sitemap.xml": urlset(SITE + "x", SITE + "y")}
        found, report = self.discover(docs, self.inventory(truncated=True, html=False))
        self.assertEqual(report, {"source": "sitemap", "cut": ""})
        self.assertEqual(found, [SITE.rstrip("/"), SITE + "x", SITE + "y"])

    def test_an_index_past_the_fallback_child_cap_is_a_cut_pool(self):
        children = [f"{SITE}s{i}.xml" for i in range(r.SAMPLE_FALLBACK_SITEMAPS + 1)]
        docs = {SITE + "sitemap.xml": index(*children)}
        docs.update({child: urlset(f"{SITE}page{i}") for i, child in enumerate(children)})
        _found, report = self.discover(docs)
        self.assertEqual(report["source"], "sitemap")
        self.assertIn(f"first {r.SAMPLE_FALLBACK_SITEMAPS}", report["cut"])
        docs = {SITE + "sitemap.xml": index(*children[:-1])}
        docs.update({child: urlset(f"{SITE}page{i}") for i, child in enumerate(children)})
        self.assertEqual(self.discover(docs)[1], {"source": "sitemap", "cut": ""})

    def test_a_cut_index_whose_read_children_are_empty_stays_cut(self):
        """Review of batch 1: the first three children were empty, the fourth listed
        the failing page, the cut was erased with the empty result and the pool fell
        to the entry's links — PASS at three children, FAIL at four."""
        children = [f"{SITE}s{i}.xml" for i in range(r.SAMPLE_FALLBACK_SITEMAPS + 1)]
        docs = {SITE + "sitemap.xml": index(*children), SITE: '<a href="/good">g</a>'}
        docs.update({child: urlset() for child in children[:-1]})
        docs[children[-1]] = urlset(SITE + "bad")
        _found, report = self.discover(docs)
        self.assertIn(f"first {r.SAMPLE_FALLBACK_SITEMAPS}", report["cut"])

    def test_a_crawl_cut_only_by_refusals_says_so(self):
        """Review of batch 1: a guard refusal is not a cap, and the reason said caps."""
        inventory = self.inventory(truncated=True)
        inventory["summary"].update(refused_pages=1, pages_fetched=2,
                                    unchecked_internal_targets=0)
        _found, report = self.discover({}, inventory)
        self.assertIn("refused", report["cut"])
        self.assertNotIn("--crawl-max-pages", report["cut"])

    def test_an_index_child_on_another_host_is_a_cut_pool(self):
        docs = {SITE + "sitemap.xml": index(SITE + "own.xml", "https://cdn.test/s.xml"),
                SITE + "own.xml": urlset(SITE + "a")}
        _found, report = self.discover(docs)
        self.assertIn("another host", report["cut"])

    def test_links_on_the_entry_and_nothing_at_all_are_uncut(self):
        docs = {SITE: '<a href="/a">a</a><a href="/b">b</a>'}
        self.assertEqual(self.discover(docs)[1], {"source": "links", "cut": ""})
        self.assertEqual(self.discover({})[1], {"source": "", "cut": ""})


class AFoundFailIsKept(unittest.TestCase):
    """Review of batch 1: the entry's second fetch failed, one sampled page FAILed, and
    `aggregate_pages` kept the primary row because one run is fewer than two — the
    primary PASS, which the cut then withheld. The entry was read once already, so its
    primary rows stand in for the run the second fetch lost."""

    def test_a_lone_sampled_fail_is_not_dropped_when_the_entry_refetch_fails(self):
        row = {"id": "MS-020", "status": PASS, "evidence": "52 chars"}
        failed = {"id": "MS-020", "status": FAIL, "evidence": "90 chars",
                  "url": "https://e.test/bad"}
        out = r.fold_sample([row], [[failed]], entry_read=False,
                            sampled={"MS-020"})[0]
        self.assertEqual(out["status"], FAIL, out)
        self.assertEqual(out["pages_checked"], 2)
        # With the entry re-read, its own run is in the list and is not added twice.
        out = r.fold_sample([row], [[dict(row)], [failed]], entry_read=True,
                            sampled={"MS-020"})[0]
        self.assertEqual((out["status"], out["pages_checked"]), (FAIL, 2))

    def test_the_runner_says_whether_the_entry_was_read_again(self):
        """The served path cannot make the entry's second fetch fail on its own — the
        run's HTTP cache answers it — so the line that decides is pinned, as
        `test_runner` pins the per-page selection."""
        with open(r.__file__, encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn('entry_read = not page_evidence[sampled_urls[0]].get("skipped")',
                      source)
        self.assertIn("graded = fold_sample(graded, per_page, entry_read, sampled)", source)


class WithholdingByStatus(unittest.TestCase):
    """`withhold_cut_sample`, one row per status of the contract's second table."""

    @staticmethod
    def item(item_id: str, requires: str = "offline", args=("{html}",)):
        return {"id": item_id, "check": {"script": "parse_html.py",
                                         "requires": requires, "args": list(args)}}

    @staticmethod
    def row(item_id: str, status: str):
        """A graded row, which carries no `check`: the registry item says what it is."""
        return {"id": item_id, "status": status, "evidence": f"{status} evidence"}

    def test_each_status_over_a_cut_pool(self):
        items = [self.item(i) for i in "ABCDEF"] + [
            self.item("G", requires="crawl"), self.item("H", args=("{cwv_json}",))]
        rows = [self.row("A", FAIL), self.row("B", WARN), self.row("C", PASS),
                self.row("D", NA), self.row("E", NA), self.row("F", NO_DATA),
                self.row("G", PASS), self.row("H", PASS)]
        out = {row["id"]: row for row in
               r.withhold_cut_sample(rows, "the crawl stopped",
                                     r.sampled_item_ids(items), scope_na={"E"})}
        self.assertEqual({k: v["status"] for k, v in out.items()},
                         {"A": FAIL, "B": WARN, "C": NO_DATA, "D": NO_DATA, "E": NA,
                          "F": NO_DATA, "G": PASS, "H": PASS})
        self.assertIn("floor", out["B"]["evidence"])
        self.assertIn("the crawl stopped", out["C"]["evidence"])
        self.assertIn("the crawl stopped", out["D"]["evidence"])
        self.assertEqual(out["A"]["evidence"], "FAIL evidence")
        self.assertEqual(out["F"]["evidence"], "NO_DATA evidence")


if __name__ == "__main__":
    unittest.main()
