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

import contextlib
import gzip
import io
import sys
import tracemalloc
import unittest
import zlib
from unittest import mock
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
        # `bytes` as `fetch_url` reports it: the body's length, not the text's.
        return {"status": 200, "url": url, "text": text,
                "bytes": len(text.encode("utf-8")),
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

    def test_the_byte_budget_counts_bytes_in_all_three_walkers(self):
        # 24 children of 1.5 MB, each 750,000 two-byte characters: 36 MB read and
        # 18 million characters. Counting characters let 0.169.1 read all of it.
        docs = big_index(24, 1)
        for name in list(docs)[1:]:
            docs[name] = docs[name].replace("<url>", f"<!--{'ж' * 750_000}--><url>", 1)
        root = SITE + "sitemap.xml"

        fetch = Documents(docs)
        out = site_crawl.load_sitemap_urls(SITE, [root], fetch=fetch)
        read = sum(len(docs[u].encode()) for u in fetch.requested if u in docs)
        self.assertLess(read, seo_common.SITEMAP_BYTES_BUDGET + 2_000_000)
        self.assertIn("byte budget", " ".join(out["cut"]))

        checker = SitemapChecker(docs)
        out = checker.run([root])
        self.assertLess(len(checker.fetch.requested), 25)
        self.assertIn("byte budget", out.get("truncated_reason", ""))

        # The matrix reads at most ten declared sitemaps: ten of 3 MB, 15 million
        # characters.
        import indexability_matrix as ix
        declared = [f"{SITE}sitemap-{i}.xml" for i in range(10)]
        docs = {sm: urlset([f"{SITE}p{i}"]).replace(
                    "<url>", f"<!--{'ж' * 1_500_000}--><url>", 1)
                for i, sm in enumerate(declared)}
        fetch = Documents(docs)
        with mock.patch.object(ix, "fetch_url", fetch), \
                mock.patch.object(ix, "discover_sitemap_urls",
                                  lambda *a, **k: declared):
            found = ix.urls_from_sitemaps(SITE, 15)
        self.assertTrue(found is None, f"{len(found or ())} URLs held")
        self.assertLess(len(fetch.requested), len(declared))

    def test_an_error_page_body_counts_against_the_byte_budget(self):
        # 24 children answering 404 with 1.5 MB each: the crawl skipped the count for
        # a failed fetch, so 36 MB were read and no cut reported (F13 review).
        root = SITE + "sitemap.xml"
        names = [f"{SITE}part-{i}.xml" for i in range(24)]
        body = "x" * 1_500_000

        class Missing(Documents):
            def __call__(self, url, **kwargs):
                if url == root:
                    return super().__call__(url, **kwargs)
                self.requested.append(url)
                return {"status": 404, "url": url, "text": body, "bytes": len(body),
                        "headers": {}, "redirect_chain": [], "error": None,
                        "error_kind": None}

        fetch = Missing({root: index(names)})
        out = site_crawl.load_sitemap_urls(SITE, [root], fetch=fetch)
        self.assertLess(len(fetch.requested), 16)
        self.assertIn("byte budget", " ".join(out["cut"]))

    def test_the_indexability_matrix_holds_no_more_sitemap_urls_than_its_budget(self):
        # Two sitemaps of 30,000: 60,000 held until F13. Past the budget a URL not
        # among those kept is not known to be missing, so membership is unknown.
        import indexability_matrix as ix
        declared = [SITE + "a.xml", SITE + "b.xml"]
        docs = {sm: urlset([f"{SITE}{k}/{j}" for j in range(30_000)])
                for k, sm in enumerate(declared)}
        with mock.patch.object(ix, "fetch_url", Documents(docs)), \
                mock.patch.object(ix, "discover_sitemap_urls",
                                  lambda *a, **k: declared):
            found = ix.urls_from_sitemaps(SITE, 15)
        self.assertTrue(found is None, f"{len(found or ())} URLs held")

    def test_a_gzipped_sitemap_is_expanded_no_further_than_the_protocol_limit(self):
        # 200 MB of comment behind 0.9 MB on the wire. Memory is what the limit is
        # for, so memory is what is measured: the bounded read peaks under 100 MB,
        # an unbounded one at about 400.
        packer = zlib.compressobj(1, zlib.DEFLATED, 31)
        parts = [packer.compress(f'<urlset xmlns="{NS}"><!--'.encode())]
        parts += [packer.compress(b"x" * 1_000_000) for _ in range(200)]
        parts += [packer.compress(b"--></urlset>"), packer.flush()]
        wire = b"".join(parts).decode("latin1")
        tracemalloc.start()
        try:
            parsed = seo_common.parse_sitemap_xml(wire, SITE + "sitemap.xml.gz")
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        self.assertEqual(parsed["type"], "invalid")
        self.assertLess(peak, 150_000_000, f"peak {peak:,} bytes")


class TheProtocolLimitIsItsOwnNumber(unittest.TestCase):
    """HTTP-10 (F04): the decompression limit tested by the number sitemaps.org gives,
    not by memory. The review of 0.172.0 replaced the bounded read with
    `read(60_000_001)` and both tests above stayed green: a limit anywhere under about
    150 MB meets a memory ceiling. The literal is written here rather than read off
    `seo_common`, so a constant moved away from the protocol reddens too.
    """

    LIMIT = 52_428_800      # sitemaps.org: 50 MB uncompressed

    @staticmethod
    def wire(size: int) -> str:
        """A gzipped urlset with one URL that expands to exactly `size` bytes."""
        head = f'<urlset xmlns="{NS}"><url><loc>{SITE}a</loc></url><!--'.encode()
        tail = b"--></urlset>"
        body = head + b"x" * (size - len(head) - len(tail)) + tail
        assert len(body) == size
        return gzip.compress(body, compresslevel=1).decode("latin1")

    def test_a_sitemap_of_exactly_the_limit_is_read(self):
        parsed = seo_common.parse_sitemap_xml(self.wire(self.LIMIT),
                                              SITE + "sitemap.xml.gz")
        self.assertEqual(parsed["type"], "urlset", parsed.get("error"))
        self.assertEqual([row["loc"] for row in parsed["urls"]], [SITE + "a"])

    def test_one_byte_past_the_limit_is_refused_naming_it(self):
        parsed = seo_common.parse_sitemap_xml(self.wire(self.LIMIT + 1),
                                              SITE + "sitemap.xml.gz")
        self.assertEqual(parsed["type"], "invalid")
        self.assertIn(f"{self.LIMIT}", parsed["error"])

    def test_no_more_than_the_limit_and_one_byte_is_ever_expanded(self):
        # 200 MB of comment behind 0.9 MB on the wire, read through a reader that
        # counts what it hands back: the bytes expanded, which is what the limit bounds.
        packer = zlib.compressobj(1, zlib.DEFLATED, 31)
        parts = [packer.compress(f'<urlset xmlns="{NS}"><!--'.encode())]
        parts += [packer.compress(b"x" * 1_000_000) for _ in range(200)]
        parts += [packer.compress(b"--></urlset>"), packer.flush()]
        wire = b"".join(parts).decode("latin1")
        expanded = []

        class Counted(gzip.GzipFile):
            def read(self, size=-1):
                out = super().read(size)
                expanded.append(len(out))
                return out

        with mock.patch.object(seo_common.gzip, "GzipFile", Counted):
            parsed = seo_common.parse_sitemap_xml(wire, SITE + "sitemap.xml.gz")
        self.assertEqual(parsed["type"], "invalid")
        self.assertTrue(expanded, "the reader was not the one counted")
        self.assertLessEqual(sum(expanded), self.LIMIT + 1,
                             f"{sum(expanded):,} bytes expanded")


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

    # The same clause for the other three paths that read a sitemap (F04). Until then
    # only the crawl was asked: a checker, matrix or fallback that refused the `www.`
    # variant left every test here green.
    WWW = "https://www.site.example/www.xml"
    PLAIN = "http://site.example/plain.xml"

    def test_the_checker_reads_the_www_variant_and_the_other_scheme_as_its_own(self):
        root = SITE + "sitemap.xml"
        checker = SitemapChecker({root: index([self.WWW, self.PLAIN]),
                                  self.WWW: urlset([SITE + "a"]),
                                  self.PLAIN: urlset([SITE + "b"])})
        out = checker.run([root])
        self.assertEqual(checker.fetch.requested, [root, self.WWW, self.PLAIN])
        self.assertEqual(out["off_host_sitemaps"], [])

    def test_the_matrix_reads_the_www_variant_and_the_other_scheme_as_its_own(self):
        import indexability_matrix as ix
        declared = [self.WWW, self.PLAIN]
        fetch = Documents({self.WWW: urlset([SITE + "a"]),
                           self.PLAIN: urlset([SITE + "b"])})
        with mock.patch.object(ix, "fetch_url", fetch), \
                mock.patch.object(ix, "discover_sitemap_urls",
                                  lambda *a, **k: declared):
            found = ix.urls_from_sitemaps(SITE, 15)
        self.assertEqual(fetch.requested, declared)
        self.assertEqual(sorted(found or ()), [SITE + "a", SITE + "b"])

    def test_the_sample_fallback_reads_a_www_child_and_the_other_scheme_as_its_own(self):
        import checklist_runner
        import lib.safe_http as safe_http
        asked = []
        docs = {SITE + "sitemap.xml": index([self.WWW, self.PLAIN]),
                self.WWW: urlset([SITE + "a"]), self.PLAIN: urlset([SITE + "b"])}

        def get(url, **_kwargs):
            asked.append(url)
            if url in docs:
                return mock.Mock(text=docs[url])
            raise OSError("not served")

        stderr = io.StringIO()
        with mock.patch.object(safe_http, "safe_get", get), \
                mock.patch.object(safe_http, "robots_allows", return_value=(True, "")), \
                contextlib.redirect_stderr(stderr):
            found = checklist_runner.discover_urls(SITE, 5)
        self.assertEqual(asked, [SITE + "sitemap.xml", self.WWW, self.PLAIN])
        self.assertNotIn("another host", stderr.getvalue())
        self.assertEqual(found, [SITE.rstrip("/"), SITE + "a", SITE + "b"])

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

    def test_another_port_on_the_audited_host_is_another_host(self):
        root = SITE + "sitemap.xml"
        port = "https://site.example:8443/child.xml"
        docs = {root: index([port]), port: urlset([SITE + "a"])}
        fetch = Documents(docs)
        out = site_crawl.load_sitemap_urls(SITE, [root], fetch=fetch)
        self.assertEqual(fetch.requested, [root])
        self.assertEqual(out["off_host_sitemaps"], [port])
        checker = SitemapChecker(docs)
        out = checker.run([root])
        self.assertEqual(checker.fetch.requested, [root])
        self.assertEqual(out["off_host_sitemaps"], [port])

    def test_the_sample_fallback_requests_no_index_child_off_the_audited_host(self):
        # `--sample` with no crawl reads the conventional sitemap paths itself and
        # followed an index's children wherever they pointed (0.169.1).
        import checklist_runner
        import lib.safe_http as safe_http
        asked = []
        own = SITE + "own.xml"
        docs = {SITE + "sitemap.xml": index(["https://other.example/s.xml",
                                             "https://site.example:8443/s.xml", own]),
                own: urlset([SITE + "a", SITE + "b"])}

        def get(url, **_kwargs):
            asked.append(url)
            if url in docs:
                return mock.Mock(text=docs[url])
            raise OSError("not served")

        stderr = io.StringIO()
        with mock.patch.object(safe_http, "safe_get", get), \
                mock.patch.object(safe_http, "robots_allows", return_value=(True, "")), \
                contextlib.redirect_stderr(stderr):
            found = checklist_runner.discover_urls(SITE, 5)
        self.assertEqual(asked, [SITE + "sitemap.xml", own])
        self.assertIn("2 sitemap(s) on another host not requested: "
                      "https://other.example/s.xml, https://site.example:8443/s.xml",
                      stderr.getvalue())
        self.assertEqual(found, [SITE.rstrip("/"), SITE + "a", SITE + "b"])

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
        # Membership is unknown, not the one host's URLs: the unread sitemap may list
        # the URL (F14, HTTP-10).
        self.assertIsNone(found)

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


class TheMatrixSaysWhenItStopped(unittest.TestCase):
    """HTTP-10 (F14): `indexability_matrix` reads at most ten sitemap locations, did not
    follow an index, and read a location that did not answer as one that lists
    nothing, each time reporting `in_sitemap: false` about URLs it had not looked
    for. Membership is known only when every location it was given was read.
    """

    PAGE = SITE + "page"

    def evaluate(self, docs: dict, locations: list[str]) -> dict:
        import indexability_matrix as ix
        docs = dict(docs)
        docs[self.PAGE] = "<html><head><title>t</title></head><body>x</body></html>"

        class Pages(Documents):
            def __call__(self, url, **kwargs):
                out = super().__call__(url, **kwargs)
                if url == TheMatrixSaysWhenItStopped.PAGE:
                    out["headers"] = {"content-type": "text/html"}
                return out

        robots = {"url": SITE + "robots.txt", "parsed": None,
                  "fetch": {"status": 404, "error": None, "error_kind": None}}
        with mock.patch.object(ix, "fetch_url", Pages(docs)), \
                mock.patch.object(ix, "fetch_robots", return_value=robots), \
                mock.patch.object(ix, "discover_sitemap_urls",
                                  lambda *a, **k: locations):
            return ix.evaluate([self.PAGE], SITE)

    def test_a_location_past_the_tenth_makes_membership_unknown_and_says_so(self):
        locations = [f"{SITE}s{i}.xml" for i in range(11)]
        docs = {sm: urlset([f"{SITE}p{i}"]) for i, sm in enumerate(locations)}
        out = self.evaluate(docs, locations)
        self.assertIsNone(out["rows"][0]["in_sitemap"])
        self.assertIn("10", out["sitemap_membership_unknown"])
        self.assertIn(locations[10], out["sitemap_membership_unknown"])

    def test_exactly_ten_locations_all_read_is_known(self):
        locations = [f"{SITE}s{i}.xml" for i in range(10)]
        docs = {sm: urlset([f"{SITE}p{i}"]) for i, sm in enumerate(locations)}
        docs[locations[9]] = urlset([self.PAGE])
        out = self.evaluate(docs, locations)
        self.assertIs(out["rows"][0]["in_sitemap"], True)
        self.assertIsNone(out["sitemap_membership_unknown"])
        docs[locations[9]] = urlset([SITE + "elsewhere"])
        out = self.evaluate(docs, locations)
        self.assertIs(out["rows"][0]["in_sitemap"], False)

    def test_no_sitemap_at_any_location_is_false(self):
        # Every location answers 404: the site names none and the conventional
        # paths hold none, which is what `false` says.
        locations = [SITE + p.lstrip("/") for p in seo_common.CONVENTIONAL_SITEMAP_PATHS]
        out = self.evaluate({}, locations)
        self.assertIs(out["rows"][0]["in_sitemap"], False)
        self.assertIsNone(out["sitemap_membership_unknown"])

    def test_an_index_whose_children_are_not_read_is_unknown(self):
        root = SITE + "sitemap.xml"
        out = self.evaluate({root: index([SITE + "child.xml"]),
                             SITE + "child.xml": urlset([self.PAGE])}, [root])
        self.assertIsNone(out["rows"][0]["in_sitemap"])
        self.assertIn(root, out["sitemap_membership_unknown"])

    def test_a_location_that_did_not_answer_is_unknown(self):
        root = SITE + "sitemap.xml"

        class Refused(Documents):
            def __call__(self, url, **kwargs):
                if url == root:
                    self.requested.append(url)
                    return {"status": None, "url": url, "text": "", "bytes": 0,
                            "headers": {}, "redirect_chain": [],
                            "error": "Blocked: port 8443", "error_kind": "blocked"}
                return super().__call__(url, **kwargs)

        import indexability_matrix as ix
        with mock.patch.object(ix, "fetch_url", Refused({})), \
                mock.patch.object(ix, "discover_sitemap_urls", lambda *a, **k: [root]):
            unread: list[str] = []
            self.assertIsNone(ix.urls_from_sitemaps(SITE, 15, unread))
        self.assertIn(root, " ".join(unread))

    def test_a_location_answering_503_or_429_is_unknown(self):
        root = SITE + "sitemap.xml"
        import indexability_matrix as ix
        for status in (503, 429):
            class Busy(Documents):
                def __call__(self, url, _status=status, **kwargs):
                    self.requested.append(url)
                    return {"status": _status, "url": url, "text": "", "bytes": 0,
                            "headers": {}, "redirect_chain": [], "error": None,
                            "error_kind": None}

            with self.subTest(status=status), \
                    mock.patch.object(ix, "fetch_url", Busy({})), \
                    mock.patch.object(ix, "discover_sitemap_urls", lambda *a, **k: [root]):
                unread: list[str] = []
                self.assertIsNone(ix.urls_from_sitemaps(SITE, 15, unread))
                self.assertIn(f"HTTP {status}", " ".join(unread))

    def test_a_robots_txt_that_gave_no_answer_leaves_its_sitemaps_unknown(self):
        # Review of 0.173.0: robots.txt refused, the three conventional paths 404, and
        # membership read `false` about sitemaps only robots.txt could have named.
        import indexability_matrix as ix
        robots = {"url": SITE + "robots.txt", "parsed": None,
                  "fetch": {"status": None, "error": "Blocked: port 8443",
                            "error_kind": "blocked"}}
        locations = [SITE + p.lstrip("/") for p in seo_common.CONVENTIONAL_SITEMAP_PATHS]
        with mock.patch.object(ix, "fetch_url", Documents({})), \
                mock.patch.object(ix, "discover_sitemap_urls", lambda *a, **k: locations):
            unread: list[str] = []
            self.assertIsNone(ix.urls_from_sitemaps(SITE, 15, unread, robots))
        self.assertIn("robots.txt gave no answer", " ".join(unread))

    def test_each_budget_names_itself(self):
        import indexability_matrix as ix
        declared = [SITE + "a.xml", SITE + "b.xml"]
        docs = {sm: urlset([f"{SITE}{k}/{j}" for j in range(30_000)])
                for k, sm in enumerate(declared)}
        with mock.patch.object(ix, "fetch_url", Documents(docs)), \
                mock.patch.object(ix, "discover_sitemap_urls", lambda *a, **k: declared):
            unread: list[str] = []
            ix.urls_from_sitemaps(SITE, 15, unread)
        self.assertIn("URL budget", " ".join(unread))
        declared = [f"{SITE}sitemap-{i}.xml" for i in range(10)]
        docs = {sm: urlset([f"{SITE}p{i}"], padding=3_000_000)
                for i, sm in enumerate(declared)}
        with mock.patch.object(ix, "fetch_url", Documents(docs)), \
                mock.patch.object(ix, "discover_sitemap_urls", lambda *a, **k: declared):
            unread = []
            ix.urls_from_sitemaps(SITE, 15, unread)
        self.assertIn("byte budget", " ".join(unread))

    def test_the_text_output_says_membership_is_unknown(self):
        import indexability_matrix as ix
        out = {"rows": [], "sitemap_membership_unknown": "a reason"}
        stdout = io.StringIO()
        with mock.patch.object(ix, "evaluate", return_value=out), \
                mock.patch.object(sys, "argv", ["indexability_matrix.py", SITE]), \
                contextlib.redirect_stdout(stdout):
            ix.main()
        self.assertIn("Sitemap membership unknown: a reason", stdout.getvalue())

    def test_a_sitemap_on_another_host_is_unknown_not_absent(self):
        declared = "https://third.example:8443/sitemap.xml"
        out = self.evaluate({}, [declared])
        self.assertIsNone(out["rows"][0]["in_sitemap"])
        self.assertIn(declared, out["sitemap_membership_unknown"])


if __name__ == "__main__":
    unittest.main()
