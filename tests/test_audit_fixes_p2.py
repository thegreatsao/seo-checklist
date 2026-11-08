"""Findings 7, 8, 9 and 16 of the repository audit of 2026-11-04 (batch P2).

Each case failed on `b30480c`:

* 7 — `sitemap_checker`: on a site answering 200 HTML for any path, the guessed
  `/sitemap_index.xml` and `/sitemap-index.xml` read as invalid sitemaps and failed
  GO-136; GO-138 checked 25 URLs of 41 and called the sitemap clean.
* 8 — CI-001 and CI-009: a raw UTF-8 self-canonical against the percent-encoded final
  URL read as "canonicalized"; `<meta name="googlebot" content="noindex">` was ignored;
  `X-Robots-Tag: otherbot: noindex` counted for Google; a canonical only in the `Link`
  header, or under `rel="Canonical"`, read as missing; of two conflicting canonicals the
  first was taken, where Google ignores both ("When more than one is specified, all
  rel=canonical links will be ignored", Search Central blog, 2013-04, "5 common
  mistakes with rel=canonical").
* 9 — CI-011 could not see noindex beside a canonical pointing elsewhere.
* 16 — `link_profile`: a self-link counted as an inbound link, and a link to `/old`
  that redirects to `/new` was not credited to `/new`.
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402,F401
from checklist_runner import FAIL, PASS  # noqa: E402
from test_evidence import verdict  # noqa: E402

import canonical_checker  # noqa: E402
import indexability_matrix  # noqa: E402
import link_profile  # noqa: E402
import seo_common  # noqa: E402
import sitemap_checker  # noqa: E402

SITE = "https://site.example/"
NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
HTML_PAGE = "<!doctype html><html><head><title>Shop</title></head><body>Hi</body></html>"


def answer(url, status=200, text="", ctype="text/html; charset=utf-8", final=None,
           headers=None):
    hdrs = {"content-type": ctype}
    hdrs.update({k.lower(): v for k, v in (headers or {}).items()})
    return {"status": status, "url": final or url, "text": text,
            "body": text.encode("utf-8"), "bytes": len(text.encode("utf-8")),
            "headers": hdrs, "redirect_chain": [], "error": None, "error_kind": None}


class Sitemaps:
    """`check_sitemaps` over a site whose every unknown path answers `fallback`."""

    def __init__(self, documents: dict, fallback=None):
        self.documents, self.fallback = documents, fallback

    def fetch(self, url, **_kw):
        if url in self.documents:
            status, text, ctype = self.documents[url]
            return answer(url, status, text, ctype)
        if self.fallback is not None:
            return answer(url, 200, self.fallback)
        return answer(url, 404, "")

    def run(self, **kw) -> dict:
        saved = (sitemap_checker.fetch_url, sitemap_checker.fetch_robots,
                 seo_common.fetch_robots)

        def fetch_robots(site_url, timeout=15):
            url = seo_common.origin(site_url) + "/robots.txt"
            return {"url": url, "fetch": {"status": 200, "url": url},
                    "parsed": seo_common.parse_robots_txt("User-agent: *\nAllow: /\n")}

        sitemap_checker.fetch_url = self.fetch
        sitemap_checker.fetch_robots = fetch_robots
        seo_common.fetch_robots = fetch_robots
        try:
            return sitemap_checker.check_sitemaps(SITE, **kw)
        finally:
            (sitemap_checker.fetch_url, sitemap_checker.fetch_robots,
             seo_common.fetch_robots) = saved


def urlset(urls) -> str:
    rows = "".join(f"<url><loc>{u}</loc><lastmod>2026-01-01</lastmod></url>"
                   for u in urls)
    return f'<urlset xmlns="{NS}">{rows}</urlset>'


XML = "application/xml"


class GuessedSitemapNamesOnACatchAllSite(unittest.TestCase):
    """Finding 7a."""

    def test_html_at_a_guessed_name_is_absence_not_an_invalid_sitemap(self):
        site = Sitemaps({SITE + "sitemap.xml": (200, urlset([SITE + "a"]), XML)},
                        fallback=HTML_PAGE)
        out = site.run()
        errors = [i for i in out["issues"] if i["severity"] == "error"]
        self.assertEqual(errors, [], errors)
        self.assertEqual(verdict("GO-136", out), PASS)
        self.assertEqual(out["summary"]["probed_absent"], 2)

    def test_a_catch_all_site_with_no_sitemap_is_still_told_so(self):
        out = Sitemaps({}, fallback=HTML_PAGE).run()
        messages = [i["message"] for i in out["issues"]]
        self.assertIn("No sitemap found", messages)
        self.assertEqual([m for m in messages if m.startswith("Invalid sitemap")], [])

    def test_a_declared_sitemap_that_is_html_is_still_invalid(self):
        site = Sitemaps({}, fallback=HTML_PAGE)
        out = site.run(sitemap_urls=[SITE + "sitemap_index.xml"])
        self.assertTrue(any(i["message"].startswith("Invalid sitemap XML")
                            for i in out["issues"]))
        self.assertEqual(verdict("GO-136", out), FAIL)


class TheUrlsGO138DidNotRequest(unittest.TestCase):
    """Finding 7b: `--max-urls 25` over 41 listed URLs."""

    def site(self, broken_from: int) -> Sitemaps:
        urls = [f"{SITE}p/{i}" for i in range(41)]
        docs = {SITE + "sitemap.xml": (200, urlset(urls), XML)}
        for i, url in enumerate(urls):
            docs[url] = ((404, "", "text/html") if i >= broken_from
                         else (200, HTML_PAGE, "text/html; charset=utf-8"))
        return Sitemaps(docs)

    def test_urls_past_the_cap_withhold_the_pass(self):
        out = self.site(broken_from=25).run(fetch_urls=True, max_urls=25)
        self.assertTrue(out["truncated"])
        self.assertIn("--max-urls", out["truncated_reason"])
        self.assertIn("16", out["truncated_reason"])

    def test_a_cap_that_covers_every_url_is_not_a_truncation(self):
        out = self.site(broken_from=41).run(fetch_urls=True, max_urls=41)
        self.assertFalse(out["truncated"], out.get("truncated_reason"))
        self.assertEqual(out["invalid_url_count"], 0)

    def test_a_bad_url_inside_the_cap_still_fails(self):
        out = self.site(broken_from=10).run(fetch_urls=True, max_urls=25)
        self.assertTrue(out["truncated"])
        self.assertGreater(out["invalid_url_count"], 0)


PAGE = "https://site.example/caf%C3%A9"


def page(head: str = "") -> str:
    return (f"<!doctype html><html><head><title>Café</title>{head}</head>"
            "<body><p>Words.</p></body></html>")


class Matrix(unittest.TestCase):
    """Finding 8, CI-001 over `indexability_matrix.evaluate`."""

    def setUp(self):
        self.saved = (indexability_matrix.fetch_url, indexability_matrix.fetch_robots,
                      indexability_matrix.urls_from_sitemaps)
        indexability_matrix.urls_from_sitemaps = lambda *a, **k: set()
        indexability_matrix.fetch_robots = lambda *a, **k: {
            "url": SITE + "robots.txt", "fetch": {"status": 404}, "parsed": None}

    def tearDown(self):
        (indexability_matrix.fetch_url, indexability_matrix.fetch_robots,
         indexability_matrix.urls_from_sitemaps) = self.saved

    def row(self, head="", headers=None, url=PAGE) -> dict:
        indexability_matrix.fetch_url = lambda u, **kw: answer(
            u, 200, page(head), final=PAGE, headers=headers)
        out = indexability_matrix.evaluate([url], SITE)
        self.out = out
        return out["rows"][0]

    def test_a_raw_utf8_self_canonical_is_self(self):
        row = self.row('<link rel="canonical" href="https://site.example/café">')
        self.assertEqual(row["verdict"], "indexable", row["blockers"])
        self.assertEqual(verdict("CI-001", self.out), PASS)

    def test_googlebot_meta_noindex_blocks(self):
        row = self.row('<meta name="googlebot" content="noindex">')
        self.assertEqual(row["verdict"], "not_indexable")
        self.assertEqual(verdict("CI-001", self.out), FAIL)

    def test_meta_robots_none_blocks(self):
        row = self.row('<meta name="robots" content="none">')
        self.assertEqual(row["verdict"], "not_indexable")

    def test_a_noindex_scoped_to_another_crawler_does_not_block_google(self):
        row = self.row(headers={"X-Robots-Tag": "otherbot: noindex, nofollow"})
        self.assertEqual(row["verdict"], "indexable", row["blockers"])

    def test_a_noindex_scoped_to_googlebot_blocks(self):
        row = self.row(headers={"X-Robots-Tag": "otherbot: nofollow, googlebot: noindex"})
        self.assertEqual(row["verdict"], "not_indexable")

    def test_an_unscoped_noindex_after_a_value_rule_blocks(self):
        row = self.row(headers={"X-Robots-Tag": "max-snippet: 20, noindex"})
        self.assertEqual(row["verdict"], "not_indexable")

    def test_a_canonical_in_the_link_header_counts(self):
        row = self.row(headers={"Link": '<https://site.example/other>; rel="canonical"'})
        self.assertEqual(row["verdict"], "not_indexable")
        self.assertIn("canonicalized to different URL", row["blockers"])

    def test_a_capitalised_rel_counts(self):
        row = self.row('<link rel="Canonical" href="https://site.example/other">')
        self.assertIn("canonicalized to different URL", row["blockers"])

    def test_conflicting_canonicals_are_both_ignored(self):
        row = self.row('<link rel="canonical" href="https://site.example/other">'
                       f'<link rel="canonical" href="{PAGE}">')
        self.assertEqual(row["verdict"], "indexable", row["blockers"])


class Canonicals(unittest.TestCase):
    """Findings 8 and 9: CI-009 and CI-011 over `canonical_checker.check_canonicals`."""

    def setUp(self):
        self.saved = canonical_checker.fetch_url

    def tearDown(self):
        canonical_checker.fetch_url = self.saved

    def check(self, head="", headers=None) -> dict:
        canonical_checker.fetch_url = lambda u, **kw: answer(
            u, 200, page(head), final=PAGE, headers=headers)
        return canonical_checker.check_canonicals([PAGE])

    def test_a_raw_utf8_self_canonical_is_self(self):
        out = self.check('<link rel="canonical" href="https://site.example/café">')
        self.assertEqual(out["rows"][0]["verdict"], "self_canonical")

    def test_a_canonical_in_the_link_header_is_not_missing(self):
        out = self.check(headers={"Link": f'<{PAGE}>; rel="canonical"'})
        self.assertEqual(out["rows"][0]["verdict"], "self_canonical")
        self.assertEqual(verdict("CI-009", out), PASS)

    def test_a_capitalised_rel_is_not_missing(self):
        out = self.check(f'<link rel="Canonical" href="{PAGE}">')
        self.assertEqual(out["rows"][0]["verdict"], "self_canonical")

    def test_conflicting_canonicals_fail_both_items(self):
        out = self.check(f'<link rel="canonical" href="{PAGE}">'
                         '<link rel="canonical" href="https://site.example/other">')
        self.assertEqual(out["rows"][0]["verdict"], "conflicting")
        self.assertEqual(verdict("CI-009", out), FAIL)
        self.assertEqual(verdict("CI-011", out), FAIL)

    def test_a_link_header_that_disagrees_with_the_tag_conflicts(self):
        out = self.check(f'<link rel="canonical" href="{PAGE}">',
                         headers={"Link": '<https://site.example/other>; rel="canonical"'})
        self.assertEqual(out["rows"][0]["verdict"], "conflicting")

    def test_the_same_canonical_twice_is_not_a_conflict(self):
        out = self.check(f'<link rel="canonical" href="{PAGE}">'
                         '<link rel="canonical" href="https://site.example/café">')
        self.assertEqual(out["rows"][0]["verdict"], "self_canonical")

    def test_noindex_with_a_canonical_elsewhere_fails_ci_011(self):
        out = self.check('<meta name="robots" content="noindex">'
                         '<link rel="canonical" href="https://site.example/other">')
        self.assertEqual(out["rows"][0]["signal"], "noindex_canonicalized")
        self.assertEqual(verdict("CI-011", out), FAIL)
        self.assertEqual(verdict("CI-009", out), PASS)

    def test_googlebot_noindex_with_a_canonical_elsewhere_fails_ci_011(self):
        out = self.check('<link rel="canonical" href="https://site.example/other">',
                         headers={"X-Robots-Tag": "googlebot: noindex"})
        self.assertEqual(verdict("CI-011", out), FAIL)

    def test_noindex_on_a_self_canonical_page_is_not_mixed(self):
        out = self.check(f'<meta name="robots" content="noindex">'
                         f'<link rel="canonical" href="{PAGE}">')
        self.assertEqual(verdict("CI-011", out), PASS)

    def test_a_canonical_elsewhere_alone_passes_ci_011(self):
        out = self.check('<link rel="canonical" href="https://site.example/other">')
        self.assertEqual(verdict("CI-011", out), PASS)

    def test_no_canonical_still_fails_ci_009_and_passes_ci_011(self):
        out = self.check()
        self.assertEqual(verdict("CI-009", out), FAIL)
        self.assertEqual(verdict("CI-011", out), PASS)


def inventory(pages: dict) -> dict:
    rows = {}
    for key, (links, final) in pages.items():
        rows[key] = {"url": key, "final_url": final or key, "html": True,
                     "status": 200,
                     "redirect_chain": [key] if final else [],
                     "links": [{"target": t, "internal": True, "anchor": "go"}
                               for t in links]}
    return {"site": SITE, "entry": SITE, "pages": rows, "summary": {}}


def orphans(pages: dict) -> list:
    graph, crawled, domain, refused = link_profile.graph_from_inventory(inventory(pages))
    out = link_profile.analyze_link_profile(graph, crawled, domain, refused,
                                            entry_url=SITE)
    return out["orphan_pages"]["urls"]


class OrphansBothWays(unittest.TestCase):
    """Finding 16."""

    def test_a_page_linked_only_from_itself_is_an_orphan(self):
        found = orphans({SITE: ([SITE + "a"], None),
                         SITE + "a": ([SITE], None),
                         SITE + "lonely": ([SITE + "lonely", SITE], None)})
        self.assertEqual(found, [SITE + "lonely"])

    def test_a_link_through_a_redirect_reaches_its_target(self):
        found = orphans({SITE: ([SITE + "old"], None),
                         SITE + "old": ([SITE], SITE + "new"),
                         SITE + "new": ([SITE], None)})
        self.assertEqual(found, [])

    def test_a_redirected_copy_does_not_link_its_target_to_itself(self):
        # /old lands on /new and carries /new's self-link: still nobody else's link.
        found = orphans({SITE: ([SITE + "a"], None),
                         SITE + "a": ([SITE], None),
                         SITE + "old": ([SITE + "new"], SITE + "new"),
                         SITE + "new": ([SITE + "new"], None)})
        self.assertIn(SITE + "new", found)



class CodexReviewOne(unittest.TestCase):
    """Codex's first review of 803c287 (session 01a1ba45-954e-7a72-ae4b-ba6bbbb0bdba)."""

    def test_the_link_header_parse_is_linear(self):
        import time
        started = time.perf_counter()
        seo_common.declared_canonicals({}, {"link": "<" * 100_000}, SITE)
        self.assertLess(time.perf_counter() - started, 1.0)

    def test_an_unparseable_canonical_is_skipped_not_raised(self):
        self.assertEqual(seo_common.declared_canonicals(
            {}, {"link": '<https://[>; rel=canonical'}, SITE), [])
        html = seo_common.parse_html(
            '<link rel="canonical" href="https://site.example/a">'
            '<link rel="canonical" href="https://[">', SITE)
        self.assertEqual(html["canonical"], "https://site.example/a")

    def test_separate_headers_keep_their_own_crawler_scope(self):
        self.assertEqual(seo_common.google_noindex(
            None, None, ["otherbot: nofollow", "noindex"]), ["x-robots-tag"])

    def test_a_cached_response_keeps_separate_headers_apart(self):
        from lib import safe_http
        from urllib3 import HTTPHeaderDict
        import requests
        live = requests.Response()
        live.status_code, live.url, live._content = 200, SITE, b""
        live.headers = requests.structures.CaseInsensitiveDict(
            {"X-Robots-Tag": "otherbot: nofollow, noindex"})
        raw = HTTPHeaderDict()
        raw.add("X-Robots-Tag", "otherbot: nofollow")
        raw.add("X-Robots-Tag", "noindex")
        live.raw = type("Raw", (), {"headers": raw})()
        self.assertEqual(safe_http.header_values(live, "x-robots-tag"),
                         ["otherbot: nofollow", "noindex"])
        entry = safe_http._entry_from_response(live, {})
        restored = safe_http._response_from_entry(entry)
        self.assertEqual(safe_http.header_values(restored, "x-robots-tag"),
                         ["otherbot: nofollow", "noindex"])

    def test_the_matrix_reads_separate_headers(self):
        saved = (indexability_matrix.fetch_url, indexability_matrix.fetch_robots,
                 indexability_matrix.urls_from_sitemaps)
        try:
            indexability_matrix.urls_from_sitemaps = lambda *a, **k: set()
            indexability_matrix.fetch_robots = lambda *a, **k: {
                "url": SITE + "robots.txt", "fetch": {"status": 404}, "parsed": None}

            def fetch(u, **kw):
                out = answer(u, 200, page(), final=PAGE,
                             headers={"X-Robots-Tag": "otherbot: nofollow, noindex"})
                out["x_robots_tags"] = ["otherbot: nofollow", "noindex"]
                return out
            indexability_matrix.fetch_url = fetch
            row = indexability_matrix.evaluate([PAGE], SITE)["rows"][0]
        finally:
            (indexability_matrix.fetch_url, indexability_matrix.fetch_robots,
             indexability_matrix.urls_from_sitemaps) = saved
        self.assertEqual(row["verdict"], "not_indexable")

    def test_an_argument_of_none_is_not_the_none_rule(self):
        for value in ("max-image-preview: none", "max-image-preview:none"):
            self.assertEqual(seo_common.google_noindex(value, None, value), [], value)

    def test_rel_inside_another_parameter_is_no_canonical(self):
        for header in ('</other>; title="rel=canonical"; rel=next',
                       '</other>; x-rel=canonical',
                       '</other>; title="a;rel=canonical"'):
            self.assertEqual(seo_common.declared_canonicals(
                {}, {"link": header}, SITE), [], header)
        self.assertEqual(seo_common.declared_canonicals(
            {}, {"link": '</a>; rel=next, </b>; rel="canonical"'}, SITE),
            [SITE + "b"])

    def test_escape_case_and_authority_spellings_are_one_url(self):
        same = seo_common.comparable_url
        self.assertEqual(same("https://site.example/%cF%80"),
                         same("https://site.example/%CF%80"))
        self.assertEqual(same("https://bücher.example/p"),
                         same("https://xn--bcher-kva.example/p"))
        self.assertEqual(same("https://site.example:443/p"),
                         same("https://site.example/p"))
        self.assertNotEqual(same("https://site.example:8443/p"),
                            same("https://site.example/p"))

    def test_an_index_declares_a_child_with_a_guessed_name(self):
        index = (f'<sitemapindex xmlns="{NS}"><sitemap><loc>{SITE}sitemap_index.xml'
                 '</loc></sitemap></sitemapindex>')
        out = Sitemaps({SITE + "sitemap.xml": (200, index, XML)},
                       fallback=HTML_PAGE).run()
        self.assertTrue(any(i["message"].startswith("Invalid sitemap XML")
                            for i in out["issues"]), out["issues"])
        self.assertEqual(verdict("GO-136", out), FAIL)

    def test_an_index_declares_a_guessed_name_already_read_as_absent(self):
        index = (f'<sitemapindex xmlns="{NS}"><sitemap><loc>{SITE}sitemap.xml'
                 '</loc></sitemap></sitemapindex>')
        out = Sitemaps({SITE + "sitemap_index.xml": (200, index, XML)},
                       fallback=HTML_PAGE).run()
        self.assertTrue(any(i["message"].startswith("Invalid sitemap XML")
                            and i.get("url") == SITE + "sitemap.xml"
                            for i in out["issues"]), out["issues"])
        self.assertEqual(out["summary"]["probed_absent"], 1)

    def test_a_redirected_entry_reaches_where_it_lands(self):
        found = orphans({SITE: ([SITE + "home"], SITE + "home/"),
                         SITE + "home": ([SITE + "home"], None)})
        self.assertEqual(found, [])



class CodexReviewTwo(unittest.TestCase):
    """Codex's second review, of 42290f4 (session 01a1ba51-6c98-7d63-b4b8-6d5fb104d280)."""

    def link(self, header: str) -> list:
        return seo_common.declared_canonicals({}, {"link": header}, SITE + "page")

    def test_a_broken_first_canonical_does_not_raise(self):
        html = seo_common.parse_html('<link rel="canonical" href="https://[">', SITE)
        self.assertIsNone(html["canonical"])

    def test_idna_is_idna_2008_as_requests_sends_it(self):
        same = seo_common.comparable_url
        self.assertNotEqual(same("https://faß.example/p"), same("https://fass.example/p"))
        self.assertEqual(same("https://faß.example/p"),
                         same("https://xn--fa-hia.example/p"))

    def test_userinfo_is_part_of_the_comparison(self):
        same = seo_common.comparable_url
        self.assertNotEqual(same("https://alice:one@site.example/p"),
                            same("https://bob:two@site.example/p"))

    def test_port_zero_is_not_the_default(self):
        same = seo_common.comparable_url
        self.assertNotEqual(same("https://site.example:0/p"), same("https://site.example/p"))

    def test_only_the_first_rel_counts(self):
        self.assertEqual(self.link("</other>; rel=next; rel=canonical"), [])

    def test_a_quoted_parameter_name_is_not_rel(self):
        self.assertEqual(self.link('</other>; r"el"=canonical'), [])

    def test_an_anchored_link_is_about_another_page(self):
        self.assertEqual(self.link('</other>; rel=canonical; anchor="/different"'), [])

    def test_an_empty_target_is_this_page(self):
        self.assertEqual(self.link("<>; rel=canonical"), [SITE + "page"])

    def test_a_quoted_rel_with_several_values_and_an_escape(self):
        self.assertEqual(self.link('</a>; title="x\\"y, z"; rel="alternate canonical"'),
                         [SITE + "a"])



class CodexReviewThree(unittest.TestCase):
    """Codex's third review, of 4e4e3a3 (session 01a1ba5d-68f3-7c51-b769-444e1dda6a14)."""

    def test_a_host_mixing_ascii_and_unicode_labels_is_encoded_per_label(self):
        # requests sends https://cdn_assets.xn--bcher-kva.example/p for the first.
        same = seo_common.comparable_url
        self.assertEqual(same("https://cdn_assets.bücher.example/p"),
                         same("https://cdn_assets.xn--bcher-kva.example/p"))


if __name__ == "__main__":
    unittest.main()
