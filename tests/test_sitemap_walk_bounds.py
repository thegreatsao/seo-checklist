"""What a sitemap walk may fetch, and how much of it it may hold.

The audit also runs behind a public web form, for anyone, so the site being
audited is the input of a stranger. Two things a sitemap walk did with that
input, found in the security review of 18 October 2026:

* **Size.** `site_crawl.load_sitemap_urls` and `sitemap_checker.check_sitemaps`
  followed up to 25 sitemaps of up to 8 MB each and kept every `<loc>`; the crawl's
  page cap bounds pages fetched, not sitemap URLs held. A gzipped sitemap was
  decompressed with no limit at all, so 8 MB on the wire could become gigabytes.
* **Hosts.** A sitemap named in robots.txt, or by a sitemap index, was fetched on
  any public host and port, so the audit could be pointed at somebody else's server
  as a GET proxy.

Each case below fails on 0.166.0.
"""
from __future__ import annotations

import gzip
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent
                       / "skills/seo-checklist/scripts"))

import seo_common  # noqa: E402
import site_crawl  # noqa: E402
import sitemap_checker  # noqa: E402

SITE = "https://site.example/"
NS = "http://www.sitemaps.org/schemas/sitemap/0.9"


def urlset(urls, padding: int = 0) -> str:
    rows = "".join(f"<url><loc>{u}</loc><lastmod>2026-01-01</lastmod></url>"
                   for u in urls)
    pad = f"<!--{'x' * padding}-->" if padding else ""
    return f'<urlset xmlns="{NS}">{pad}{rows}</urlset>'


def index(children) -> str:
    rows = "".join(f"<sitemap><loc>{u}</loc></sitemap>" for u in children)
    return f'<sitemapindex xmlns="{NS}">{rows}</sitemapindex>'


class Documents:
    """An injectable `fetch` serving fixed documents and recording every request."""

    def __init__(self, documents: dict):
        self.documents = documents
        self.requested: list[str] = []

    def __call__(self, url, **_kwargs):
        self.requested.append(url)
        text = self.documents.get(url)
        if text is None:
            return {"status": 404, "url": url, "text": "", "headers": {},
                    "redirect_chain": [], "error": None, "error_kind": None}
        return {"status": 200, "url": url, "text": text, "bytes": len(text),
                "headers": {"content-type": "application/xml"},
                "redirect_chain": [], "error": None, "error_kind": None}


class SitemapChecker:
    """`sitemap_checker.check_sitemaps` with its two fetchers replaced."""

    def __init__(self, documents: dict, robots: str = ""):
        self.fetch = Documents(documents)
        self.robots = robots

    def run(self, sitemap_urls=None) -> dict:
        saved = (sitemap_checker.fetch_url, sitemap_checker.fetch_robots,
                 seo_common.fetch_robots)

        def fetch_robots(site_url, timeout=15):
            url = seo_common.origin(site_url) + "/robots.txt"
            same = seo_common.origin(site_url) == seo_common.origin(SITE)
            return {"url": url, "fetch": {"status": 200, "url": url},
                    "parsed": seo_common.parse_robots_txt(self.robots if same else "")}

        sitemap_checker.fetch_url = self.fetch
        sitemap_checker.fetch_robots = fetch_robots
        seo_common.fetch_robots = fetch_robots
        try:
            return sitemap_checker.check_sitemaps(SITE, sitemap_urls)
        finally:
            (sitemap_checker.fetch_url, sitemap_checker.fetch_robots,
             seo_common.fetch_robots) = saved


def big_index(children: int, urls_each: int, padding: int = 0) -> dict:
    root = SITE + "sitemap.xml"
    names = [f"{SITE}part-{i}.xml" for i in range(children)]
    docs = {root: index(names)}
    for i, name in enumerate(names):
        docs[name] = urlset([f"{SITE}p/{i}/{j}" for j in range(urls_each)],
                            padding=padding)
    return docs


class SizeBudget(unittest.TestCase):

    def test_the_crawl_holds_no_more_sitemap_urls_than_its_budget_and_says_so(self):
        # 24 children of 2,500 URLs: 60,000 locations, over the 50,000 budget.
        docs = big_index(24, 2_500)
        out = site_crawl.load_sitemap_urls(SITE, [SITE + "sitemap.xml"],
                                           fetch=Documents(docs))
        self.assertLessEqual(len(out["urls"]), seo_common.SITEMAP_URLS_BUDGET)
        self.assertTrue(out["cut"], "URLs were dropped and nothing recorded it")
        self.assertIn("URL budget", " ".join(out["cut"]))

    def test_the_crawl_stops_reading_sitemaps_past_its_byte_budget(self):
        # 24 children of about 1.5 MB each: 36 MB, over the 20 MB budget.
        docs = big_index(24, 10, padding=1_500_000)
        fetch = Documents(docs)
        out = site_crawl.load_sitemap_urls(SITE, [SITE + "sitemap.xml"], fetch=fetch)
        read = sum(len(docs[u]) for u in fetch.requested if u in docs)
        self.assertLess(read, seo_common.SITEMAP_BYTES_BUDGET + 2_000_000)
        self.assertTrue(out["unvisited"], "the sitemaps not read must be named")
        self.assertIn("byte budget", " ".join(out["cut"]))

    def test_the_checker_holds_no_more_sitemap_urls_than_its_budget_and_says_so(self):
        out = SitemapChecker(big_index(24, 2_500)).run([SITE + "sitemap.xml"])
        self.assertLessEqual(len(out["urls"]), seo_common.SITEMAP_URLS_BUDGET)
        self.assertTrue(out["truncated"])
        self.assertIn("URL budget", out["truncated_reason"])

    def test_the_checker_stops_reading_sitemaps_past_its_byte_budget(self):
        checker = SitemapChecker(big_index(24, 10, padding=1_500_000))
        out = checker.run([SITE + "sitemap.xml"])
        self.assertLess(len(checker.fetch.requested), 25)
        self.assertTrue(out["truncated"])
        self.assertIn("byte budget", out["truncated_reason"])

    def test_a_gzipped_sitemap_is_not_decompressed_past_the_protocol_limit(self):
        # Valid XML whose decompressed size is 60 MB: it parsed, and was held whole.
        body = (f'<urlset xmlns="{NS}"><!--'.encode() + b"x" * 60_000_000
                + b"--></urlset>")
        wire = gzip.compress(body, compresslevel=1).decode("latin1")
        parsed = seo_common.parse_sitemap_xml(wire, SITE + "sitemap.xml.gz")
        self.assertEqual(parsed["type"], "invalid")
        self.assertIn("uncompressed", parsed["error"])


class OffHostSitemaps(unittest.TestCase):

    def test_the_crawl_requests_no_sitemap_off_the_audited_host(self):
        root = SITE + "sitemap.xml"
        elsewhere = "http://other.example:6379/child.xml"
        docs = {root: index([SITE + "own.xml", elsewhere]),
                SITE + "own.xml": urlset([SITE + "a"]),
                elsewhere: urlset(["http://other.example:6379/x"])}
        declared = "https://third.example/sitemap.xml"
        fetch = Documents(docs)
        out = site_crawl.load_sitemap_urls(SITE, [root, declared], fetch=fetch)
        self.assertEqual(fetch.requested, [root, SITE + "own.xml"])
        self.assertEqual(sorted(out["off_host_sitemaps"]), sorted([declared, elsewhere]))
        self.assertEqual(out["urls"], [SITE + "a"])

    def test_the_www_variant_and_the_other_scheme_are_the_same_site(self):
        root = SITE + "sitemap.xml"
        www = "https://www.site.example/www.xml"
        plain = "http://site.example/plain.xml"
        docs = {root: index([www, plain]), www: urlset([SITE + "a"]),
                plain: urlset([SITE + "b"])}
        fetch = Documents(docs)
        out = site_crawl.load_sitemap_urls(SITE, [root], fetch=fetch)
        self.assertEqual(fetch.requested, [root, www, plain])
        self.assertEqual(out["off_host_sitemaps"], [])

    def test_the_checker_requests_no_sitemap_robots_txt_names_on_another_host(self):
        declared = "https://third.example:8443/sitemap.xml"
        checker = SitemapChecker({declared: urlset([SITE + "a"])},
                                 robots=f"User-agent: *\nSitemap: {declared}\n")
        out = checker.run()
        self.assertNotIn(declared, checker.fetch.requested)
        self.assertEqual(out["off_host_sitemaps"], [declared])
        # Unread is not absent: the site declared a sitemap, so "No sitemap found"
        # would be an accusation, and a clean verdict would rest on nothing.
        messages = [row["message"] for row in out["issues"]]
        self.assertNotIn("No sitemap found", messages)
        self.assertTrue(out["truncated"])
        self.assertIn(declared, out["truncated_reason"])

    def test_the_checker_requests_no_index_child_on_another_host(self):
        root = SITE + "sitemap.xml"
        child = "http://other.example:6379/child.xml"
        checker = SitemapChecker({root: index([child]), child: urlset([SITE + "a"])})
        out = checker.run([root])
        self.assertEqual(checker.fetch.requested, [root])
        self.assertEqual(out["off_host_sitemaps"], [child])


    def test_the_indexability_matrix_requests_no_sitemap_on_another_host(self):
        import indexability_matrix as ix
        declared = "https://third.example:8443/sitemap.xml"
        own = SITE + "sitemap.xml"
        fetch = Documents({declared: urlset([SITE + "x"]), own: urlset([SITE + "a"])})
        saved = ix.fetch_url, ix.discover_sitemap_urls
        ix.fetch_url = fetch
        ix.discover_sitemap_urls = lambda *a, **k: [declared, own]
        try:
            found = ix.urls_from_sitemaps(SITE, 15)
        finally:
            ix.fetch_url, ix.discover_sitemap_urls = saved
        self.assertEqual(fetch.requested, [own])
        self.assertEqual(found, {SITE + "a"})

    def test_the_indexability_matrix_stops_reading_sitemaps_past_its_byte_budget(self):
        # Ten declared sitemaps of about 3 MB each: 30 MB, over the 20 MB budget. With
        # sitemaps left unread, a URL not found in the ones read is not known to be
        # missing, so membership is unknown rather than false.
        import indexability_matrix as ix
        declared = [f"{SITE}sitemap-{i}.xml" for i in range(10)]
        docs = {sm: urlset([f"{SITE}p{i}"], padding=3_000_000)
                for i, sm in enumerate(declared)}
        fetch = Documents(docs)
        saved = ix.fetch_url, ix.discover_sitemap_urls
        ix.fetch_url = fetch
        ix.discover_sitemap_urls = lambda *a, **k: declared
        try:
            found = ix.urls_from_sitemaps(SITE, 15)
        finally:
            ix.fetch_url, ix.discover_sitemap_urls = saved
        read = sum(len(docs[u]) for u in fetch.requested)
        self.assertLess(read, seo_common.SITEMAP_BYTES_BUDGET + 3_100_000)
        self.assertLess(len(fetch.requested), len(declared))
        self.assertIsNone(found)

if __name__ == "__main__":
    unittest.main()
