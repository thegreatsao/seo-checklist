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


if __name__ == "__main__":
    unittest.main()
