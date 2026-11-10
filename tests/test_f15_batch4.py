"""F15 batch 4: robots, sitemaps, redirects and URLs — `robots_checker.py`,
`robots_path_tester.py`, `sitemap_checker.py`, `indexability_matrix.py`,
`redirect_checker.py`, `gsc_url_inspection.py`, `hreflang_checker.py`,
`faceted_nav_audit.py`, `url_quality.py`, `llms_txt_checker.py`, `indexnow_checker.py` —
as the owner ruled them (docs/sprint-20261109-F15.md), and the owner's rulings 1 and 3
on batch 3's questions (cross-host canonicals; AR-153 and AR-162 on small sites).

Each verdict is the item's real rule from the registry, `applies_when` included, over
the script's real output, from a site served on loopback or a hand-built inventory.
"""
import contextlib
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "skills", "seo-checklist", "scripts")
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness  # noqa: E402
import canonical_checker  # noqa: E402
import faceted_nav_audit  # noqa: E402
import gsc_url_inspection  # noqa: E402
import hreflang_checker  # noqa: E402
import indexability_matrix  # noqa: E402
import indexnow_checker  # noqa: E402
import link_profile  # noqa: E402
import redirect_checker  # noqa: E402
import robots_checker  # noqa: E402
import robots_path_tester  # noqa: E402
import seo_common  # noqa: E402
import site_crawl  # noqa: E402
import sitemap_checker  # noqa: E402
import topical_cluster_mapper  # noqa: E402
from harness import served  # noqa: E402
from lib import robots_rules  # noqa: E402
from checklist_runner import FAIL, NA, NO_DATA, PASS, evaluate  # noqa: E402
from test_evidence import verdict  # noqa: E402
from test_f15_batch3 import (inventory, page_html, row, run_rule_script,  # noqa: E402
                             written)

ITEMS = {item["id"]: item for item in harness.registry()["items"]}
ROBOTS = (200, "User-agent: *\nAllow: /\n")


def full_verdict(item_id: str, output: dict) -> str:
    """`verdict` with the item's `applies_when` read first, as the runner reads it."""
    applies = ITEMS[item_id]["check"].get("applies_when")
    if applies:
        ok, _ = evaluate(applies, output)
        if ok is None:
            return NO_DATA
        if not ok:
            return NA
    return verdict(item_id, output)


@contextlib.contextmanager
def site_with(routes: dict):
    """A loopback site whose routes may name `{origin}` and `{other}` (the same server
    reached as `localhost`, so another host)."""
    routes = dict(routes)
    routes.setdefault("/robots.txt", ROBOTS)
    with harness.allow_loopback(), served(routes) as site:
        origin = site.url.rstrip("/")
        other = origin.replace("127.0.0.1", "localhost")

        def fill(value):
            if isinstance(value, str):
                return value.replace("{origin}", origin).replace("{other}", other)
            if isinstance(value, tuple):
                return tuple(fill(part) if not isinstance(part, dict) else
                             {k: fill(v) for k, v in part.items()} for part in value)
            return value
        site.routes.clear()
        site.routes.update({k: harness._normalise(fill(v)) for k, v in routes.items()})
        site.origin, site.other = origin, other
        yield site


def two_headers(module, path: str, values: list):
    """`module.fetch_url` answering `path` with `X-Robots-Tag` sent once per value, as
    `seo_common.fetch_url` reports a repeated header: `x_robots_tags` keeps them apart,
    `headers` joins them (a served route can carry one header of a name)."""
    real = module.fetch_url

    def fetch(url, *args, **kwargs):
        answer = real(url, *args, **kwargs)
        if url.split("?")[0].endswith(path):
            answer["x_robots_tags"] = list(values)
            answer.setdefault("headers", {})["x-robots-tag"] = ", ".join(values)
        return answer
    return mock.patch.object(module, "fetch_url", fetch)


# ---------------------------------------------------------------------------
# The owner's ruling 1: a cross-host canonical alone fails no canonical item
# ---------------------------------------------------------------------------

class CrossHostCanonical(unittest.TestCase):
    def test_a_cross_host_canonical_to_a_live_page_passes_ci_009(self):
        with site_with({"/a": page_html(canonical="{other}/original"),
                        "/original": page_html(canonical="{other}/original")}) as site:
            out = run_rule_script(canonical_checker, "CI-009", site.origin + "/a")
        self.assertEqual(out["rows"][0]["verdict"], "cross_host")
        self.assertEqual(verdict("CI-009", out), PASS)

    def test_a_cross_host_canonical_to_a_404_still_fails_ci_009(self):
        with site_with({"/a": page_html(canonical="{other}/gone")}) as site:
            out = run_rule_script(canonical_checker, "CI-009", site.origin + "/a")
        self.assertEqual(verdict("CI-009", out), FAIL)

    def test_a_cross_host_canonical_whose_target_never_answers_is_withheld(self):
        """Same as a same-host target nobody answered: `target_unchecked`, NO_DATA."""
        out = None
        with site_with({"/a": page_html(canonical="http://127.0.0.1:9/x")}) as site:
            out = run_rule_script(canonical_checker, "CI-009", site.origin + "/a")
        self.assertEqual(verdict("CI-009", out), NO_DATA)

    def test_a_cross_host_canonical_still_has_its_variants_requested(self):
        """Review round 2: `/a/` serving the page beside `/a` is CI-009's failure whatever
        host the canonical names."""
        with site_with({"/a": page_html(canonical="{other}/original"),
                        "/original": page_html(canonical="{other}/original"),
                        "/a/": page_html()}) as site:
            out = run_rule_script(canonical_checker, "CI-009", site.origin + "/a")
        self.assertEqual(out["rows"][0]["verdict"], "variant_unconsolidated")
        self.assertEqual(verdict("CI-009", out), FAIL)

    def test_te_176_lists_no_issue_for_a_cross_host_canonical_alone(self):
        with site_with({"/original": page_html(canonical="{other}/original")}) as site:
            inv = inventory([row(site.origin + "/",
                                 canonical=site.other + "/original")])
            inv["site"] = inv["entry"] = site.origin + "/"
            inv["pages"] = {k.replace("https://example.test", site.origin): v
                            for k, v in inv["pages"].items()}
            out = run_rule_script(canonical_checker, "TE-176", site.origin + "/",
                                  written(inv))
        self.assertEqual(out["rows"][0]["verdict"], "cross_host")
        self.assertEqual(out["issues"], [])
        self.assertEqual(verdict("TE-176", out), PASS)

    def test_te_176_still_fails_a_cross_host_canonical_to_a_404(self):
        with site_with({}) as site:
            inv = inventory([row(site.origin + "/", canonical=site.other + "/gone")])
            inv["site"] = inv["entry"] = site.origin + "/"
            inv["pages"] = {k.replace("https://example.test", site.origin): v
                            for k, v in inv["pages"].items()}
            out = run_rule_script(canonical_checker, "TE-176", site.origin + "/",
                                  written(inv))
        self.assertEqual(verdict("TE-176", out), FAIL)


# ---------------------------------------------------------------------------
# The owner's ruling 3: AR-153 and AR-162 are N/A below a minimum page count
# ---------------------------------------------------------------------------

SITE = "https://example.test/"


def pages(titles: list, links=None) -> dict:
    """An inventory of pages `/p0`… with these titles; `links` maps index -> targets."""
    links = links or {}
    rows = [row(f"{SITE}p{i}", title=title,
                links=[f"{SITE}p{j}" for j in links.get(i, [])])
            for i, title in enumerate(titles)]
    return inventory(rows)


class SmallSites(unittest.TestCase):
    def test_ar_153_is_na_on_a_three_page_site(self):
        """Two of three titles sharing a word is the site's word (over half), so no
        subtopic of two pages can form: the rule could only fail here."""
        inv = pages(["Sourdough bread", "Rye loaves", "Opening hours"])
        out = topical_cluster_mapper.map_inventory(inv)
        self.assertEqual(full_verdict("AR-153", out), NA)

    def test_ar_153_is_na_on_a_one_page_site(self):
        out = topical_cluster_mapper.map_inventory(pages(["Sourdough bread"]))
        self.assertEqual(full_verdict("AR-153", out), NA)

    def test_ar_153_does_not_count_an_error_page_toward_the_minimum(self):
        """Review round 2: a broken link's 404 page is no page of the site's."""
        inv = pages(["Sourdough bread", "Rye loaves", "Opening hours"])
        gone = row(f"{SITE}gone", title="Page not found", status=404)
        inv["pages"][f"{SITE}gone"] = gone
        out = topical_cluster_mapper.map_inventory(inv)
        self.assertEqual(full_verdict("AR-153", out), NA)

    def test_ar_153_still_judges_a_four_page_site(self):
        inv = pages(["Sourdough bread", "Rye loaves", "Opening hours", "Contact us"])
        out = topical_cluster_mapper.map_inventory(inv)
        self.assertEqual(full_verdict("AR-153", out), FAIL)

    def test_ar_153_minimum_is_the_one_its_arithmetic_needs(self):
        """Below 4, a word on two titles is on more than half of them (site-wide)."""
        need = topical_cluster_mapper.MIN_PAGES_FOR_HUBS
        self.assertEqual(need, 4)
        self.assertGreater(2 / (need - 1), topical_cluster_mapper.SITE_WIDE_SHARE)
        self.assertLessEqual(2 / need, topical_cluster_mapper.SITE_WIDE_SHARE)
        self.assertEqual(ITEMS["AR-153"]["check"]["applies_when"],
                         {"path": "too_few_pages_for_hubs", "falsy": True})

    def test_a_crawl_cut_at_its_cap_is_never_too_small(self):
        """It has more pages than it read: AR-153 and AR-162 are withheld, not N/A."""
        inv = pages(["Sourdough bread", "Rye loaves"], {0: [1], 1: [0]})
        inv["summary"]["truncated"] = True
        inv["entry"] = inv["site"] = f"{SITE}p0"
        out = topical_cluster_mapper.map_inventory(inv)
        self.assertIs(out["too_few_pages_for_hubs"], False)
        self.assertEqual(full_verdict("AR-153", out), NO_DATA)
        graph, crawled, base, refused = link_profile.graph_from_inventory(inv)
        out = link_profile.analyze_link_profile(graph, crawled, base, refused,
                                                truncated=True)
        self.assertIs(out["too_few_pages_for_average"], False)
        self.assertNotEqual(full_verdict("AR-162", out), NA)

    def ar_162(self, inv: dict) -> dict:
        graph, crawled, base, refused = link_profile.graph_from_inventory(inv)
        return link_profile.analyze_link_profile(graph, crawled, base, refused)

    def test_ar_162_is_na_on_a_three_page_site_with_a_full_menu(self):
        inv = pages(["Home", "About", "Contact"],
                    {0: [1, 2], 1: [0, 2], 2: [0, 1]})
        inv["entry"] = inv["site"] = f"{SITE}p0"
        self.assertEqual(full_verdict("AR-162", self.ar_162(inv)), NA)

    def test_ar_162_still_judges_a_four_page_site(self):
        full = {i: [j for j in range(4) if j != i] for i in range(4)}
        inv = pages(["Home", "About", "Contact", "Menu"], full)
        inv["entry"] = inv["site"] = f"{SITE}p0"
        self.assertEqual(full_verdict("AR-162", self.ar_162(inv)), PASS)
        thin = pages(["Home", "About", "Contact", "Menu"],
                     {0: [1, 2, 3], 1: [0], 2: [0], 3: [0]})
        thin["entry"] = thin["site"] = f"{SITE}p0"
        self.assertEqual(full_verdict("AR-162", self.ar_162(thin)), FAIL)

    def test_ar_162_counts_a_redirect_row_once(self):
        """A redirect read again is its landing page, not a fourth page."""
        full = {i: [j for j in range(3) if j != i] for i in range(3)}
        inv = pages(["Home", "About", "Contact"], full)
        inv["entry"] = inv["site"] = f"{SITE}p0"
        again = dict(inv["pages"][f"{SITE}p1"], url=f"{SITE}old",
                     final_url=f"{SITE}p1", redirected=True,
                     redirect_chain=[f"{SITE}old"])
        inv["pages"][f"{SITE}old"] = again
        out = self.ar_162(inv)
        self.assertEqual(out["pages_read"], 3)
        self.assertEqual(full_verdict("AR-162", out), NA)

    def test_ar_162_minimum_is_the_one_its_arithmetic_needs(self):
        """Three distinct other pages a page need, so four pages at least."""
        need = link_profile.MIN_PAGES_FOR_AVERAGE
        self.assertEqual(need, link_profile.LOW_AVERAGE_INTERNAL_LINKS + 1)
        self.assertEqual(ITEMS["AR-162"]["check"]["applies_when"],
                         {"path": "too_few_pages_for_average", "falsy": True})


class ReviewRound1SmallSites(unittest.TestCase):
    """F15 review round 1: the average counts distinct internal URLs, files and refused
    paths among them, so three pages linking a PDF and `/cart` can reach it."""

    def test_three_pages_linking_other_urls_are_judged(self):
        def site(links):
            inv = pages(["Home", "Menu", "Hours"], links)
            inv["entry"] = inv["site"] = f"{SITE}p0"
            for row_ in inv["pages"].values():
                if not row_["links"]:
                    continue        # a dead end links nothing at all
                row_["links"] += [{"target": f"{SITE}menu.pdf", "internal": True,
                                   "anchor": "Menu (PDF)", "rel": [], "nofollow": False},
                                  {"target": f"{SITE}cart", "internal": True,
                                   "anchor": "Cart", "rel": [], "nofollow": False}]
            graph, crawled, base, refused = link_profile.graph_from_inventory(inv)
            return link_profile.analyze_link_profile(graph, crawled, base, refused)
        full = site({0: [1, 2], 1: [0, 2], 2: [0, 1]})
        self.assertIs(full["too_few_pages_for_average"], False)
        self.assertEqual(full_verdict("AR-162", full), PASS)
        self.assertEqual(full_verdict("AR-162", site({0: [1, 2], 1: [0, 2], 2: []})),
                         FAIL)


# ---------------------------------------------------------------------------
# robots_checker.py — AR-151, CI-006
# ---------------------------------------------------------------------------

def robots_rule(item_id: str, robots_txt: str, crawled_paths=("/",)) -> dict:
    with site_with({"/robots.txt": (200, {"Content-Type": "text/plain"}, robots_txt)}) as site:
        inv = inventory([row(site.origin + path) for path in crawled_paths])
        inv["site"] = inv["entry"] = site.origin + "/"
        inv["pages"] = {k.replace("https://example.test", site.origin): v
                        for k, v in inv["pages"].items()}
        return run_rule_script(robots_checker, item_id, site.origin + "/", written(inv))


class RobotsFile(unittest.TestCase):
    def test_ar_151_reads_the_crawled_paths(self):
        self.assertIn("{inventory_json}", ITEMS["AR-151"]["check"]["args"])
        self.assertEqual(ITEMS["AR-151"]["check"]["requires"], "crawl")

    def test_a_home_only_disallow_is_not_the_whole_site(self):
        """`Disallow: /$` keeps `/` out and every other page in."""
        out = robots_rule("AR-151", "User-agent: *\nDisallow: /$\n",
                          crawled_paths=("/", "/about", "/menu"))
        self.assertNotIn("the whole site is disallowed for Googlebot",
                         out["correctness_problems"])
        self.assertEqual(verdict("AR-151", out), PASS)

    def test_a_site_wide_disallow_still_fails(self):
        out = robots_rule("AR-151", "User-agent: *\nDisallow: /\n",
                          crawled_paths=("/", "/about"))
        self.assertIn("the whole site is disallowed for Googlebot",
                      out["correctness_problems"])
        self.assertEqual(verdict("AR-151", out), FAIL)

    def test_an_empty_user_agent_line_fails(self):
        out = robots_rule("AR-151", "User-agent:\nDisallow: /private\n")
        self.assertEqual(verdict("AR-151", out), FAIL)
        self.assertTrue(any("user-agent" in p for p in out["correctness_problems"]))

    def unread_crawl(self, robots_answer) -> dict:
        with site_with({"/robots.txt": robots_answer}) as site:
            inv = inventory([row(site.origin + "/")])
            inv["site"] = inv["entry"] = site.origin + "/"
            inv["pages"] = {}
            inv["fetch_error"] = "the crawl read no page"
            return run_rule_script(robots_checker, "AR-151", site.origin + "/", written(inv))

    def test_a_problem_the_crawl_does_not_decide_stands_without_it(self):
        """Review round 1: a 404 or an HTML page is a problem whatever the crawl read."""
        with site_with({}) as site:
            inv = inventory([row(site.origin + "/")])
            inv["site"] = inv["entry"] = site.origin + "/"
            inv["fetch_error"] = "the crawl read no page"
            out = run_rule_script(robots_checker, "AR-151", site.origin + "/", written(inv))
        self.assertEqual(verdict("AR-151", out), FAIL)
        out = self.unread_crawl((200, "<!doctype html><html><body>Home</body></html>"))
        self.assertEqual(verdict("AR-151", out), FAIL)

    def test_a_shut_home_page_without_the_crawl_withholds_the_whole_site_answer(self):
        out = self.unread_crawl((200, {"Content-Type": "text/plain"},
                                 "User-agent: *\nDisallow: /\n"))
        self.assertEqual(out["correctness_problems"], [])
        self.assertTrue(out["truncated"])

    def capped(self, robots_txt: str, paths=("/",)) -> dict:
        with site_with({"/robots.txt": (200, {"Content-Type": "text/plain"},
                                        robots_txt)}) as site:
            inv = inventory([row(site.origin + p) for p in paths], truncated=True)
            inv["site"] = inv["entry"] = site.origin + "/"
            inv["pages"] = {k.replace("https://example.test", site.origin): v
                            for k, v in inv["pages"].items()}
            return run_rule_script(robots_checker, "AR-151", site.origin + "/",
                                   written(inv))

    def test_a_capped_crawl_withholds_only_the_whole_site_claim(self):
        """Review round 3: a path the cap skipped may be open, so "every path is shut"
        is withheld; it cannot overturn an open path read or the file's own problems."""
        out = self.capped("User-agent: Googlebot\nDisallow: /\nAllow: /blog/\n\n"
                          "User-agent: *\nAllow: /\n", paths=("/", "/shop/a"))
        self.assertEqual(out["correctness_problems"], [])
        self.assertTrue(out["truncated"])
        self.assertEqual(verdict("AR-151", out), PASS)      # the runner withholds it

    def test_a_capped_crawl_keeps_a_pass_it_cannot_overturn(self):
        out = self.capped("User-agent: *\nAllow: /\n")
        self.assertEqual(out["correctness_problems"], [])
        self.assertFalse(out.get("truncated"))
        out = self.capped("User-agent: *\nAllow: /\nNoindex: /x\n")
        self.assertEqual(verdict("AR-151", out), FAIL)

    def test_the_paths_tested_are_the_urls_crawled_not_their_keys(self):
        """`Allow: /en/` matches `/en/`, the URL read; its key folds the slash."""
        out = robots_rule("AR-151", "User-agent: *\nDisallow: /\nAllow: /en/\n",
                          crawled_paths=("/", "/en/"))
        self.assertEqual(out["correctness_problems"], [])

    def test_a_refused_url_is_tested_as_it_was_asked(self):
        """Review round 2: the crawl refuses `/en/` under `*`; Googlebot may fetch it.
        The refused key folds to `/en`, which `Allow: /en/` does not match."""
        robots = ("User-agent: *\nDisallow: /\n\nUser-agent: Googlebot\nDisallow: /\n"
                  "Allow: /en/\n")
        routes = {"/robots.txt": (200, {"Content-Type": "text/plain"}, robots),
                  "/": '<html><body><a href="/en/">English</a></body></html>',
                  "/en/": page_html()}
        with site_with(routes) as site:
            crawled_inv = site_crawl.crawl(site.url, workers=1, use_sitemap=False)
            self.assertIn(site.origin + "/en/",
                          crawled_inv["robots_blocked_urls"].values())
            out = run_rule_script(robots_checker, "AR-151", site.url, written(crawled_inv))
        self.assertEqual(out["correctness_problems"], [])

    def test_an_empty_sitemap_line_is_no_declaration(self):
        self.assertEqual(robots_rules.parse("User-agent: *\nSitemap:\n")["sitemaps"], [])
        out = robots_rule("CI-006", "User-agent: *\nAllow: /\nSitemap:   \n")
        self.assertEqual(out["sitemaps"], [])
        self.assertEqual(verdict("CI-006", out), FAIL)

    def test_a_declared_sitemap_still_passes_ci_006(self):
        out = robots_rule("CI-006", "User-agent: *\nAllow: /\n"
                                    "Sitemap: https://example.test/sitemap.xml\n")
        self.assertEqual(verdict("CI-006", out), PASS)


# ---------------------------------------------------------------------------
# robots_path_tester.py — CI-013, CI-019
# ---------------------------------------------------------------------------

CSS = {"Content-Type": "text/css"}


class CriticalAssets(unittest.TestCase):
    def run_ci_013(self, routes: dict) -> dict:
        with site_with(routes) as site:
            return run_rule_script(robots_path_tester, "CI-013", site.url)

    def test_an_imported_stylesheet_blocked_by_robots_fails(self):
        out = self.run_ci_013({
            "/robots.txt": (200, "User-agent: *\nDisallow: /private/\n"),
            "/": '<html><head><link rel="stylesheet" href="/css/main.css"></head>'
                 '<body>Hi</body></html>',
            "/css/main.css": (200, CSS, '@import url("/private/theme.css");\nbody{}'),
            "/private/theme.css": (200, CSS, "body{color:red}")})
        self.assertIn(out["site"].rstrip("/") + "/private/theme.css", out["blocked_urls"])
        self.assertEqual(verdict("CI-013", out), FAIL)

    def test_imports_are_followed_through_imports_and_style_blocks(self):
        out = self.run_ci_013({
            "/robots.txt": (200, "User-agent: *\nDisallow: /private/\n"),
            "/": "<html><head><style>@import '/css/a.css';</style></head>"
                 "<body>Hi</body></html>",
            "/css/a.css": (200, CSS, "@import 'b.css' screen;"),
            "/css/b.css": (200, CSS, "@import url(/private/c.css);"),
            "/private/c.css": (200, CSS, "p{}")})
        self.assertEqual([u.rsplit("/", 2)[-2:] for u in out["blocked_urls"]],
                         [["private", "c.css"]])

    def test_a_minified_import_is_followed(self):
        """Review round 1: `@import"x.css"` with no space is valid CSS minifiers write."""
        for rule in ('@import"/private/a.css";', "@import'/private/a.css';"):
            with self.subTest(rule=rule):
                self.assertEqual([u.rsplit("/", 1)[-1] for u in
                                  robots_path_tester.css_imports(rule, "https://x.test/")],
                                 ["a.css"])

    def test_an_unread_stylesheet_withholds_the_pass(self):
        out = self.run_ci_013({
            "/": '<html><head><link rel="stylesheet" href="/css/main.css"></head>'
                 '<body>Hi</body></html>',
            "/css/main.css": (500, CSS, "")})
        self.assertEqual(out["blocked_urls"], [])
        self.assertTrue(out.get("truncated"))

    def test_a_page_with_allowed_imports_passes(self):
        out = self.run_ci_013({
            "/": '<html><head><link rel="stylesheet" href="/css/main.css"></head>'
                 '<body>Hi</body></html>',
            "/css/main.css": (200, CSS, "@import url(/css/more.css);"),
            "/css/more.css": (200, CSS, "p{}")})
        self.assertFalse(out.get("truncated"))
        self.assertEqual(verdict("CI-013", out), PASS)


class SystemPages(unittest.TestCase):
    def test_a_failed_probe_truncates_the_result(self):
        """A path whose probe found nothing out is unread: no clean answer over it."""
        with site_with({"/cart": (500, "oops")}) as site:
            out = run_rule_script(robots_path_tester, "CI-019", site.url)
        self.assertEqual(out["indexable_urls"], [])
        self.assertIn(site.origin + "/cart", out["unprobed_urls"])
        self.assertTrue(out.get("truncated"))
        self.assertIn("/cart", out.get("truncated_reason", ""))

    def test_a_rate_limited_probe_truncates_the_result(self):
        """Review round 2: a 429 has not said the page is absent."""
        with site_with({"/search": (429, {"Retry-After": "1"}, "")}) as site:
            out = run_rule_script(robots_path_tester, "CI-019", site.url)
        self.assertIn(site.origin + "/search", out["unprobed_urls"])
        self.assertTrue(out.get("truncated"))

    def test_paths_that_answer_404_leave_the_result_whole(self):
        with site_with({}) as site:
            out = run_rule_script(robots_path_tester, "CI-019", site.url)
        self.assertFalse(out.get("truncated"))
        self.assertEqual(verdict("CI-019", out), PASS)


# ---------------------------------------------------------------------------
# sitemap_checker.py — GO-136, GO-138
# ---------------------------------------------------------------------------

NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
XML = {"Content-Type": "application/xml"}


def urlset(*locs, ns=NS, bare=0) -> str:
    entries = "".join(f"<url><loc>{loc}</loc><lastmod>2026-01-01</lastmod></url>"
                      for loc in locs)
    entries += "<url><lastmod>2026-01-01</lastmod></url>" * bare
    xmlns = f' xmlns="{ns}"' if ns else ""
    return f'<?xml version="1.0" encoding="UTF-8"?><urlset{xmlns}>{entries}</urlset>'


def sitemap_rule(item_id: str, sitemap: str, extra=None) -> dict:
    routes = {"/robots.txt": (200, "User-agent: *\nAllow: /\n"
                                   "Sitemap: {origin}/sitemap.xml\n"),
              "/sitemap.xml": (200, XML, sitemap), "/": page_html(canonical="/")}
    routes.update(extra or {})
    with site_with(routes) as site:
        return run_rule_script(sitemap_checker, item_id, site.url)


class CleanSitemaps(unittest.TestCase):
    def test_a_clean_sitemap_passes(self):
        self.assertEqual(verdict("GO-136", sitemap_rule("GO-136", urlset("{origin}/"))),
                         PASS)

    def test_a_url_entry_without_loc_fails(self):
        out = sitemap_rule("GO-136", urlset("{origin}/", bare=1))
        self.assertEqual(verdict("GO-136", out), FAIL)

    def test_a_wrong_namespace_fails(self):
        for ns in ("http://www.google.com/schemas/sitemap/0.84", ""):
            with self.subTest(ns=ns):
                out = sitemap_rule("GO-136", urlset("{origin}/", ns=ns))
                self.assertEqual(verdict("GO-136", out), FAIL)

    def test_an_index_entry_without_loc_fails(self):
        doc = (f'<?xml version="1.0"?><sitemapindex xmlns="{NS}"><sitemap><loc>'
               f'{{origin}}/s1.xml</loc></sitemap><sitemap><lastmod>2026-01-01</lastmod>'
               f"</sitemap></sitemapindex>")
        out = sitemap_rule("GO-136", doc, {"/s1.xml": (200, XML, urlset("{origin}/"))})
        self.assertEqual(verdict("GO-136", out), FAIL)

    def test_an_unknown_root_with_url_children_fails(self):
        doc = (f'<?xml version="1.0"?><pages xmlns="{NS}"><url><loc>{{origin}}/</loc>'
               f"</url></pages>")
        self.assertEqual(verdict("GO-136", sitemap_rule("GO-136", doc)), FAIL)

    def test_an_empty_sitemap_fails(self):
        out = sitemap_rule("GO-136", urlset())
        self.assertEqual(verdict("GO-136", out), FAIL)
        index = f'<?xml version="1.0"?><sitemapindex xmlns="{NS}"></sitemapindex>'
        self.assertEqual(verdict("GO-136", sitemap_rule("GO-136", index)), FAIL)


class SitemapNoindex(unittest.TestCase):
    def go_138(self, answer) -> dict:
        return sitemap_rule("GO-138", urlset("{origin}/", "{origin}/b"),
                            {"/b": answer})

    def test_an_x_robots_tag_noindex_is_invalid(self):
        out = self.go_138((200, {"X-Robots-Tag": "noindex"}, page_html()))
        self.assertEqual(out["invalid_url_count"], 1)
        self.assertEqual(verdict("GO-138", out), FAIL)

    def test_a_googlebot_meta_or_none_is_invalid(self):
        for head in ('<meta name="googlebot" content="noindex">',
                     '<meta name="robots" content="none">'):
            with self.subTest(head=head):
                out = self.go_138(f"<html><head>{head}</head><body>x</body></html>")
                self.assertEqual(verdict("GO-138", out), FAIL)

    def test_each_header_is_read_on_its_own(self):
        """Review round 2: `otherbot: noarchive` in one header does not own the next."""
        with two_headers(sitemap_checker, "/b", ["otherbot: noarchive", "noindex"]):
            out = self.go_138(page_html(canonical="/b"))
        self.assertEqual(verdict("GO-138", out), FAIL)

    def test_another_crawlers_header_noindex_is_not_googles(self):
        out = self.go_138((200, {"X-Robots-Tag": "otherbot: noindex"},
                           page_html(canonical="/b")))
        self.assertEqual(verdict("GO-138", out), PASS)


# ---------------------------------------------------------------------------
# indexability_matrix.py — GEO-008
# ---------------------------------------------------------------------------

class SnippetScope(unittest.TestCase):
    def test_another_crawlers_nosnippet_does_not_fail(self):
        controls = indexability_matrix.snippet_controls(page_html(), "bingbot: nosnippet")
        self.assertEqual(controls["snippet_availability"], "full")

    def test_googlebots_and_unscoped_rules_still_count(self):
        for header in ("googlebot: nosnippet", "nosnippet",
                       "otherbot: noindex, googlebot: max-snippet: 0"):
            with self.subTest(header=header):
                controls = indexability_matrix.snippet_controls(page_html(), header)
                self.assertEqual(controls["snippet_availability"], "suppressed")

    def test_a_rule_with_an_argument_is_no_crawler_name(self):
        """`max-snippet: 0` is a rule and its argument, not a crawler named `max-snippet`."""
        for name in seo_common._RULES_WITH_ARGUMENT:
            with self.subTest(rule=name):
                self.assertEqual(seo_common.google_robots_directives(f"{name}: 0, nosnippet",
                                                                     scoped=True),
                                 [f"{name}: 0", "nosnippet"])
                self.assertEqual(seo_common.google_robots_rules(f"{name}: 0", scoped=True),
                                 {name})

    def test_each_header_is_read_on_its_own(self):
        """`bingbot: noindex` in one header does not scope the next header's rule."""
        controls = indexability_matrix.snippet_controls(
            page_html(), ["bingbot: noarchive", "nosnippet"])
        self.assertEqual(controls["snippet_availability"], "suppressed")

    def test_the_script_reads_each_header_on_its_own(self):
        """Review round 2: the row passes `x_robots_tags`, not the joined header."""
        with two_headers(indexability_matrix, "/", ["bingbot: noarchive", "nosnippet"]):
            with site_with({"/": page_html()}) as site:
                out = run_rule_script(indexability_matrix, "GEO-008", site.url)
        self.assertEqual(verdict("GEO-008", out), FAIL)

    def test_geo_008_through_the_script(self):
        with site_with({"/": (200, {"X-Robots-Tag": "bingbot: nosnippet"},
                              page_html())}) as site:
            out = run_rule_script(indexability_matrix, "GEO-008", site.url)
        self.assertEqual(verdict("GEO-008", out), PASS)


# ---------------------------------------------------------------------------
# redirect_checker.py — AR-150, CI-014
# ---------------------------------------------------------------------------

class RedirectLoops(unittest.TestCase):
    def ar_150(self, routes: dict, path="/a") -> dict:
        with site_with(routes) as site:
            return run_rule_script(redirect_checker, "AR-150", site.origin + path)

    def test_a_self_loop_fails(self):
        out = self.ar_150({"/a": (301, {"Location": "/a"}, "")})
        self.assertTrue(out["has_loop"])
        self.assertEqual(verdict("AR-150", out), FAIL)

    def test_a_two_url_loop_fails(self):
        out = self.ar_150({"/a": (301, {"Location": "/b"}, ""),
                           "/b": (302, {"Location": "/a"}, "")})
        self.assertEqual(verdict("AR-150", out), FAIL)

    def test_a_walk_stopped_at_the_cap_is_a_chain(self):
        """Ten hops and more fail as a chain; the loop question is withheld, not the hops."""
        routes = {f"/r{i}": (301, {"Location": f"/r{i + 1}"}, "") for i in range(12)}
        routes["/r12"] = page_html()
        out = self.ar_150(routes, path="/r0")
        self.assertEqual(out.get("walk"), "chain")
        self.assertEqual(verdict("AR-150", out), FAIL)

    def test_one_hop_passes_and_two_fail(self):
        self.assertEqual(verdict("AR-150", self.ar_150(
            {"/a": (301, {"Location": "/b"}, ""), "/b": page_html()})), PASS)
        self.assertEqual(verdict("AR-150", self.ar_150(
            {"/a": (301, {"Location": "/b"}, ""), "/b": (301, {"Location": "/c"}, ""),
             "/c": page_html()})), FAIL)
        self.assertEqual(verdict("AR-150", self.ar_150({"/a": page_html()})), PASS)


# ---------------------------------------------------------------------------
# gsc_url_inspection.py — CI-010
# ---------------------------------------------------------------------------

class InspectedCanonical(unittest.TestCase):
    def analyze(self, google: str, user: str) -> dict:
        answer = {"inspectionResult": {}, "indexStatusResult": {
            "googleCanonical": google, "userCanonical": user,
            "coverageState": "Submitted and indexed"}}
        with mock.patch.object(gsc_url_inspection, "build_service"), \
                mock.patch.object(gsc_url_inspection, "inspect", return_value=answer):
            return gsc_url_inspection.analyze("https://a.test/page", "https://a.test/",
                                              "/dev/null", "en")

    def test_a_trailing_slash_is_another_url(self):
        out = self.analyze("https://a.test/page/", "https://a.test/page")
        self.assertIs(out["canonical_match"], False)
        self.assertEqual(verdict("CI-010", out), FAIL)

    def test_one_url_spelled_two_ways_matches(self):
        out = self.analyze("https://A.test:443/caf%c3%a9", "https://a.test/café")
        self.assertIs(out["canonical_match"], True)


# ---------------------------------------------------------------------------
# hreflang_checker.py — IN-122
# ---------------------------------------------------------------------------

def hreflang_page(*pairs) -> str:
    links = "".join(f'<link rel="alternate" hreflang="{lang}" href="{href}">'
                    for lang, href in pairs)
    return f"<html><head>{links}</head><body>Hi</body></html>"


class HreflangValidity(unittest.TestCase):
    def in_122(self, routes: dict) -> dict:
        with site_with(routes) as site:
            with mock.patch.object(hreflang_checker.time, "sleep"):
                return hreflang_checker.run_hreflang_check(site.origin + "/en",
                                                           verify_returns=True)

    def test_a_valid_pair_passes(self):
        pair = (("en", "{origin}/en"), ("de", "{origin}/de"))
        out = self.in_122({"/en": hreflang_page(*pair), "/de": hreflang_page(*pair)})
        self.assertEqual(verdict("IN-122", out), PASS)

    def test_an_invalid_language_code_fails(self):
        """`jp` is a country, not a language: the return tags alone do not make it valid."""
        pair = (("en", "{origin}/en"), ("jp", "{origin}/ja"))
        out = self.in_122({"/en": hreflang_page(*pair), "/ja": hreflang_page(*pair)})
        self.assertTrue(out["language_code_issues"])
        self.assertEqual(verdict("IN-122", out), FAIL)

    def test_a_valid_code_with_a_better_spelling_passes(self):
        """Review round 1: `zh-CN`, `zh-TW` and `zh` are valid language-region codes;
        that a script subtag says more is advice, not invalidity."""
        for code in hreflang_checker.SCRIPT_ADVICE:
            with self.subTest(table=code):
                checked = hreflang_checker.validate_lang_code(code)
                self.assertTrue(checked["valid"])
                self.assertTrue(checked["advice"])
        for code in ("zh-CN", "zh-TW", "zh"):
            with self.subTest(code=code):
                pair = (("en", "{origin}/en"), (code, "{origin}/zh"))
                out = self.in_122({"/en": hreflang_page(*pair), "/zh": hreflang_page(*pair)})
                self.assertEqual(verdict("IN-122", out), PASS)

    def test_an_invalid_code_fails_without_fetching_the_alternates(self):
        """Archive mode passes no `--verify-returns`; a code needs no network."""
        pair = (("en", "{origin}/en"), ("jp", "{origin}/ja"))
        with site_with({"/en": hreflang_page(*pair)}) as site:
            out = hreflang_checker.run_hreflang_check(site.origin + "/en")
        self.assertEqual(verdict("IN-122", out), FAIL)

    def test_one_language_beside_an_x_default_elsewhere_is_verified(self):
        """Review round 2: the x-default names another URL, whose return is checked."""
        pair = (("en", "{origin}/en"), ("x-default", "{origin}/"))
        out = self.in_122({"/en": hreflang_page(*pair), "/": hreflang_page(*pair)})
        self.assertEqual(verdict("IN-122", out), PASS)
        out = self.in_122({"/en": hreflang_page(*pair), "/": hreflang_page()})
        self.assertEqual(verdict("IN-122", out), FAIL)

    def test_codes_outside_googles_format_are_invalid(self):
        """Review round 3: ISO 639-1 languages and ISO 3166-1 alpha-2 regions."""
        for code in ("eng-US", "es-419", "jp-JP"):
            with self.subTest(code=code):
                self.assertFalse(hreflang_checker.validate_lang_code(code)["valid"])
        # Review round 4: a language with no two-letter code is valid in its three.
        for code in ("en-US", "es-MX", "pt-BR", "fil-PH", "yue"):
            with self.subTest(code=code):
                self.assertTrue(hreflang_checker.validate_lang_code(code)["valid"])

    def test_a_set_with_no_alternate_does_not_pass(self):
        out = self.in_122({"/en": hreflang_page(("en", "{origin}/en"),
                                                ("x-default", "{origin}/en"))})
        self.assertNotEqual(verdict("IN-122", out), PASS)


# ---------------------------------------------------------------------------
# faceted_nav_audit.py — AR-163
# ---------------------------------------------------------------------------

class FacetControls(unittest.TestCase):
    def ar_163(self, routes: dict) -> dict:
        with site_with(routes) as site:
            return run_rule_script(faceted_nav_audit, "AR-163", site.url)

    def test_a_self_canonical_is_no_control(self):
        """The facet answering at its own URL with a canonical naming itself."""
        out = self.ar_163({
            "/": '<html><body><a href="/shop?color=red">Red</a></body></html>',
            "/shop": page_html(canonical="{origin}/shop?color=red")})
        self.assertEqual(verdict("AR-163", out), FAIL)

    def test_a_facet_redirecting_to_its_clean_page_is_controlled(self):
        """Review round 3: `/old?color=red` 301s to `/shop`, which names itself."""
        out = self.ar_163({
            "/": '<html><body><a href="/old?color=red">Red</a></body></html>',
            "/old": (301, {"Location": "/shop"}, ""),
            "/shop": page_html(canonical="{origin}/shop")})
        self.assertEqual(verdict("AR-163", out), PASS)

    def test_a_facet_redirecting_to_another_spelling_of_itself_is_not(self):
        """Review round 4: `/shop?color=red` -> `/shop/?color=red` naming itself is the
        same facet, indexable, uncontrolled."""
        out = self.ar_163({
            "/": '<html><body><a href="/shop?color=red">Red</a></body></html>',
            "/shop": (301, {"Location": "/shop/?color=red"}, ""),
            "/shop/": page_html(canonical="{origin}/shop/?color=red")})
        self.assertEqual(verdict("AR-163", out), FAIL)

    def test_variants_robots_txt_disallows_are_no_path_explosion(self):
        links = "".join(f'<a href="/shop?sort=p{i}">s{i}</a>' for i in range(6))
        out = self.ar_163({"/robots.txt": (200, "User-agent: *\nDisallow: /shop?\n"),
                           "/": f"<html><body>{links}</body></html>",
                           "/shop": page_html()})
        self.assertEqual(out["path_explosions"], {})

    def test_a_canonical_elsewhere_is_a_control(self):
        out = self.ar_163({
            "/": '<html><body><a href="/shop?color=red">Red</a></body></html>',
            "/shop": page_html(canonical="{origin}/shop")})
        self.assertEqual(verdict("AR-163", out), PASS)

    def test_a_noindex_google_reads_is_a_control(self):
        """Review round 1: the header, the googlebot meta and `none` noindex a facet."""
        for answer in ((200, {"X-Robots-Tag": "noindex"}, page_html(canonical="{origin}/shop?color=red")),
                       page_html(canonical="{origin}/shop?color=red", robots="none"),
                       '<html><head><link rel="canonical" href="{origin}/shop?color=red">'
                       '<meta name="googlebot" content="noindex"></head><body>x</body></html>'):
            with self.subTest(answer=str(answer)[:60]):
                out = self.ar_163({
                    "/": '<html><body><a href="/shop?color=red">Red</a></body></html>',
                    "/shop": answer})
                self.assertEqual(verdict("AR-163", out), PASS)

    def test_controlled_variants_are_no_path_explosion(self):
        links = "".join(f'<a href="/shop?sort=p{i}">s{i}</a>' for i in range(6))
        out = self.ar_163({"/": f"<html><body>{links}</body></html>",
                           "/shop": page_html(canonical="{origin}/shop")})
        self.assertEqual(out["path_explosions"], {})
        self.assertEqual(verdict("AR-163", out), PASS)

    def test_uncontrolled_variants_still_explode(self):
        links = "".join(f'<a href="/list?page={i}">p{i}</a>' for i in range(2, 8))
        out = self.ar_163({"/": f"<html><body>{links}</body></html>",
                           "/list": page_html()})
        self.assertTrue(out["path_explosions"])


# ---------------------------------------------------------------------------
# indexnow_checker.py — GEO-007
# ---------------------------------------------------------------------------

KEY = "0123456789abcdef0123456789abcdef"


class IndexNowKeyFile(unittest.TestCase):
    def key_file(self, answer) -> dict:
        with site_with({f"/{KEY}.txt": answer}) as site:
            return indexnow_checker.check_key_file(site.url, KEY)

    def test_a_file_that_only_contains_the_key_fails(self):
        out = self.key_file((200, {"Content-Type": "text/plain"}, f"key: {KEY} ok"))
        self.assertIs(out["passed"], False)

    def test_an_html_page_echoing_the_key_fails(self):
        out = self.key_file((200, {"Content-Type": "text/html"}, KEY))
        self.assertIs(out["passed"], False)

    def test_the_key_alone_as_text_passes(self):
        for body in (KEY, KEY + "\n", "﻿" + KEY + "\r\n"):
            with self.subTest(body=body):
                out = self.key_file((200, {"Content-Type": "text/plain; charset=utf-8"},
                                     body))
                self.assertIs(out["passed"], True)


# ---------------------------------------------------------------------------
# The measures rulings: CI-014, AR-155, CI-012, GEO-001, GEO-002, AR-153, AR-162
# ---------------------------------------------------------------------------

class MeasuresSentences(unittest.TestCase):
    SAYS = {
        "CI-014": "temporary codes are flagged for review",
        "AR-155": "path",
        "CI-012": "heuristic",
        "GEO-001": "except 204",
        "GEO-002": "convention",
        "AR-153": "fewer than 4",
        "AR-162": "fewer than 4",
        "TE-176": "another host",
        "CI-009": "another host",
    }

    def test_each_ruled_item_states_what_its_rule_decides(self):
        for item_id, words in self.SAYS.items():
            with self.subTest(item=item_id):
                self.assertIn(words, ITEMS[item_id].get("measures", ""))


if __name__ == "__main__":
    unittest.main()
