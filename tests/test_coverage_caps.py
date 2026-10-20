"""The coverage caps whose basis is `convention`, held to the argument written on them.

Each of these numbers was `inherited` until 0.167.1, and each now says the same thing:
it bounds how much of a site is read, and past it the script says so — `truncated`
for a reading cap, an `error` and no verdict field for a retry count or a timeout — so
the runner withholds a PASS by absence instead of reading a clean answer off part of
the input. That is a judgement about cost and coverage, not about the site, and it is
only true while the script actually raises the flag. These tests are what keeps it
true: each drives one cap one step past its value, and one step short of it.

`DEFAULT_MAX_EXTERNAL`, `DEFAULT_MAX_IMAGES`, `MAX_ASSETS` and `MAX_URLS_FROM_PAGE` are
driven where their scripts are tested (`test_evidence_scripts.py`,
`test_release_0740.py`); `DEFAULT_MAX_LINES` beside the other partial logs in
`ALogThatCouldOnlyAnswerHalfTheQuestion`.
"""
from __future__ import annotations

import os
import socket
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "skills", "seo-checklist", "scripts")
sys.path.insert(0, SCRIPTS)

import broken_links  # noqa: E402
import css_minify_check  # noqa: E402
import gsc_url_inspection  # noqa: E402
import sitemap_checker  # noqa: E402
import tls_certificate  # noqa: E402

SITE = "https://example.test"


def page(body: str) -> SimpleNamespace:
    """A fetched HTML page, the shape `safe_get` returns."""
    html = f"<!doctype html><html><head>{body}</head><body>{body}</body></html>"
    return SimpleNamespace(status_code=200, text=html, content=html.encode(),
                           headers={"content-type": "text/html"}, url=SITE + "/",
                           history=[])


class BrokenLinksPageCap(unittest.TestCase):
    """`DEFAULT_MAX_LINKS`: TE-168 counts broken links over the ones requested."""

    def run_with(self, links: int, cap: int) -> dict:
        body = "".join(f'<a href="/p{i}">p{i}</a>' for i in range(links))
        healthy = lambda link, timeout: {**link, "status": 200, "error": None,  # noqa: E731
                                         "error_kind": None, "redirect": None,
                                         "response_time_ms": 1}
        with mock.patch.object(broken_links, "safe_get", return_value=page(body)), \
                mock.patch.object(broken_links, "check_link", side_effect=healthy):
            return broken_links.check_broken_links(SITE + "/", max_links=cap)

    def test_one_link_past_the_cap_is_not_requested_and_truncates(self):
        result = self.run_with(links=3, cap=2)
        self.assertEqual(result["checked"], 2)
        self.assertTrue(result["truncated"])

    def test_a_page_at_the_cap_is_read_whole(self):
        result = self.run_with(links=2, cap=2)
        self.assertEqual(result["checked"], 2)
        self.assertFalse(result["truncated"])


class StylesheetCap(unittest.TestCase):
    """`MAX_SHEETS`: TE-174 counts unminified sheets over the ones fetched."""

    def run_with(self, sheets: int, cap: int) -> dict:
        links = "".join(f'<link rel="stylesheet" href="/s{i}.css">' for i in range(sheets))
        css = SimpleNamespace(status_code=200, text="a{b:c}", content=b"a{b:c}",
                              headers={"content-type": "text/css"})

        def fetch(url, **_kwargs):
            return css if url.endswith(".css") else page(links)

        with mock.patch.object(css_minify_check, "safe_get", side_effect=fetch), \
                mock.patch.object(css_minify_check, "MAX_SHEETS", cap):
            return css_minify_check.check(SITE + "/")

    def test_one_sheet_past_the_cap_truncates(self):
        result = self.run_with(sheets=3, cap=2)
        self.assertEqual(len(result["stylesheets"]), 2)
        self.assertTrue(result["truncated"])

    def test_a_page_at_the_cap_is_read_whole(self):
        result = self.run_with(sheets=2, cap=2)
        self.assertEqual(len(result["stylesheets"]), 2)
        self.assertFalse(result["truncated"])


class SitemapIndexCap(unittest.TestCase):
    """`MAX_SITEMAPS_FOLLOWED`: GO-136 reads issues over the sitemap files walked."""

    INDEX = SITE + "/sitemap.xml"

    def run_with(self, children: int, cap: int) -> dict:
        child_urls = [f"{SITE}/sitemap-{i}.xml" for i in range(children)]
        index = ('<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                 + "".join(f"<sitemap><loc>{u}</loc></sitemap>" for u in child_urls)
                 + "</sitemapindex>")
        urlset = ('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                  f"<url><loc>{SITE}/</loc></url></urlset>")

        def fetch_url(url, **_kwargs):
            return {"status": 200, "url": url, "redirect_chain": [],
                    "headers": {"content-type": "application/xml"},
                    "text": index if url == self.INDEX else urlset,
                    "error": None, "error_kind": None}

        def fetch_robots(site_url, timeout=15):
            robots = sitemap_checker.origin(site_url) + "/robots.txt"
            return {"url": robots, "fetch": {"status": 404, "url": robots}, "parsed": None}

        with mock.patch.object(sitemap_checker, "fetch_url", side_effect=fetch_url), \
                mock.patch.object(sitemap_checker, "fetch_robots", side_effect=fetch_robots), \
                mock.patch.object(sitemap_checker, "MAX_SITEMAPS_FOLLOWED", cap):
            return sitemap_checker.check_sitemaps(SITE, [self.INDEX], fetch_urls=False)

    def test_one_file_past_the_cap_truncates(self):
        # The index itself is one of the files followed. No `truncated_reason`: the
        # cap is the cause, and the runner's own wording for a cap is the true one.
        result = self.run_with(children=2, cap=2)
        self.assertTrue(result["truncated"])
        self.assertNotIn("truncated_reason", result)

    def test_an_index_within_the_cap_is_read_whole(self):
        result = self.run_with(children=1, cap=2)
        self.assertFalse(result["truncated"])


class InspectionRetries(unittest.TestCase):
    """`RETRIES`: how often a refused Search Console call is tried before giving up.

    It decides whether CI-002, CI-010 and GO-135 get an answer, never which answer:
    after the last attempt the result carries `error` and no `indexed`, which the
    `truthy` rules read as NO_DATA rather than as a page Google left out.
    """

    def test_the_last_refusal_leaves_an_error_and_no_answer(self):
        calls = []

        def refuse(*_args, **_kwargs):
            calls.append(1)
            raise RuntimeError("service refused")

        with mock.patch.object(gsc_url_inspection, "build_service", side_effect=refuse), \
                mock.patch.object(gsc_url_inspection.time, "sleep"):
            result = gsc_url_inspection.analyze(SITE + "/", SITE + "/", "/dev/null", "en")
        self.assertEqual(len(calls), gsc_url_inspection.RETRIES)
        self.assertEqual(result["error_kind"], "service")
        self.assertNotIn("indexed", result)
        self.assertIsNone(result.get("canonical_match"))


class HandshakeTimeout(unittest.TestCase):
    """`DEFAULT_TIMEOUT`: a handshake that outlasts it is no answer, not a bad certificate.

    SE-118 is `critical` and reads `valid`. A timeout that set `valid: False` would
    fail a site for being slow; it sets `error` instead, so the timeout decides only
    whether the item answers.
    """

    def test_a_timed_out_handshake_sets_no_verdict(self):
        with mock.patch.object(tls_certificate, "validated_addresses",
                               return_value=["192.0.2.1"]), \
                mock.patch.object(tls_certificate.socket, "create_connection",
                                  side_effect=socket.timeout("timed out")):
            result = tls_certificate.inspect(SITE + "/")
        self.assertIsNone(result.get("valid"))
        self.assertIn("timeout", result["error"].lower())



class TheCrawlCaps(unittest.TestCase):
    """`site_crawl.py` `DEFAULT_MAX_PAGES` and `DEFAULT_DEPTH` (F09): the crawl every
    site-wide item reads. Driven at their own values — the crawl is called without
    either, so a change to a constant is a change to what these tests read — over a
    served site one step past and one step short of each."""

    ROBOTS = (200, "User-agent: *\nAllow: /\n")

    @staticmethod
    def page(*links: str) -> str:
        return ("<html><head><title>t</title></head><body>"
                + "".join(f'<a href="{href}">{href}</a>' for href in links)
                + "</body></html>")

    def crawl(self, routes: dict) -> dict:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import harness
        import site_crawl
        with harness.allow_loopback(), harness.served(routes) as site:
            return site_crawl.crawl(site.url, use_sitemap=False, workers=4)["summary"]

    def chain(self, length: int) -> dict:
        """`/` -> `/p1` -> ... -> `/p{length-1}`: one page per hop."""
        paths = ["/"] + [f"/p{i}" for i in range(1, length)]
        routes = {path: self.page(*paths[i + 1:i + 2]) for i, path in enumerate(paths)}
        routes["/robots.txt"] = self.ROBOTS
        return self.crawl(routes)

    def fan(self, pages: int) -> dict:
        """`/` linking to `pages - 1` others: every page one hop from the entry."""
        others = [f"/p{i}" for i in range(1, pages)]
        routes = {"/": self.page(*others), "/robots.txt": self.ROBOTS}
        routes.update({path: self.page() for path in others})
        return self.crawl(routes)

    def test_a_chain_one_hop_past_the_depth_is_cut_and_says_so(self):
        import site_crawl
        summary = self.chain(site_crawl.DEFAULT_DEPTH + 2)
        self.assertEqual(summary["pages_fetched"], site_crawl.DEFAULT_DEPTH + 1)
        self.assertEqual(summary["unchecked_internal_targets"], 1)
        self.assertTrue(summary["truncated"])

    def test_a_chain_as_deep_as_the_depth_is_read_whole(self):
        import site_crawl
        summary = self.chain(site_crawl.DEFAULT_DEPTH + 1)
        self.assertEqual(summary["pages_fetched"], site_crawl.DEFAULT_DEPTH + 1)
        self.assertFalse(summary["truncated"])

    def test_a_site_one_page_past_the_budget_is_cut_and_says_so(self):
        import site_crawl
        summary = self.fan(site_crawl.DEFAULT_MAX_PAGES + 1)
        self.assertEqual(summary["pages_fetched"], site_crawl.DEFAULT_MAX_PAGES)
        self.assertTrue(summary["truncated"])

    def test_a_site_one_page_short_of_the_budget_is_read_whole(self):
        """One short, not at: a crawl that fetched exactly the budget cannot know
        nothing was left, and says `truncated` — the cautious side of the cap."""
        import site_crawl
        summary = self.fan(site_crawl.DEFAULT_MAX_PAGES - 1)
        self.assertEqual(summary["pages_fetched"], site_crawl.DEFAULT_MAX_PAGES - 1)
        self.assertFalse(summary["truncated"])

    def test_the_audit_crawls_with_these_numbers(self):
        """The runner passes `--depth` and `--max-pages` to the crawl, and until
        0.170.0 its defaults were the literals 3 and 100: the constants decided only a
        crawl run by hand, and a basis line on them argued a number the audit did not
        read. Moved here, the runner's defaults move with them."""
        import checklist_runner
        import site_crawl
        with mock.patch.object(site_crawl, "DEFAULT_DEPTH", 7), \
                mock.patch.object(site_crawl, "DEFAULT_MAX_PAGES", 11):
            args = checklist_runner.build_parser().parse_args(["https://example.test/"])
        self.assertEqual((args.crawl_depth, args.crawl_max_pages), (7, 11))



class TheMinHashPairDecidesOnlyWhatIsPrinted(unittest.TestCase):
    """`site_crawl.py` `MINHASH_FUNCTIONS` and `SHINGLE_WORDS` are `presentation`
    (F09): they feed the MinHash signature, the signature feeds `near_duplicates` and
    `summary.near_duplicate_pairs` alone, and no rule reads either. Pointing an item
    at one makes both thresholds again, and this is what says so."""

    def test_no_rule_or_declaration_reads_a_near_duplicate_field(self):
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import harness
        readers = []
        for item in harness.registry()["items"]:
            check = item.get("check") or {}
            for part in ("assert", "warn", "applies_when"):
                path = str((check.get(part) or {}).get("path") or "")
                if "near_dup" in path:
                    readers.append(f"{item['id']} {part}: {path}")
        self.assertEqual(readers, [],
                         "a verdict now reads the MinHash estimate; give "
                         "MINHASH_FUNCTIONS and SHINGLE_WORDS a counted basis")


if __name__ == "__main__":
    unittest.main()
