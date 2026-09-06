"""Tests for the evidence scripts that decide the `critical` items.

Everything above these tests was well covered and everything below them was not:
248 tests defended the registry, the runner and the report, and 45 of the 55
evidence scripts had none at all. Every verdict an audit prints is the output of one
of those scripts read by a well-tested interpreter, so a script that quietly stops
emitting a field, or emits it in a second vocabulary, produces a confident number
built on nothing — and the frame cannot tell.

Seventeen of the nineteen `critical` items are decided by seven scripts. These are
those seven, and each test asserts **the field the registry actually reads**, named
in the test, so that a change to the script's output contract fails here rather than
in a client's report. Writing them found four fabricated verdicts on critical items;
they are pinned below with the item id.

Offline: no fixture site, no network, no API key. The HTTP layer is stubbed at
`seo_common.fetch_url` or `lib.safe_http.safe_get`, whichever the script uses.
"""
import ast
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "skills", "seo-checklist", "scripts")
REGISTRY = os.path.join(ROOT, "skills", "seo-checklist", "resources", "config",
                        "checklist.json")
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from checklist_runner import NO_DATA, PASS, FAIL, WARN, evaluate  # noqa: E402
from harness import allow_loopback, served  # noqa: E402


def registry_rule(item_id: str) -> dict:
    """The live assert rule for an item, so a test cannot drift from the registry.

    Reading the rule instead of restating it is the point: a test that hard-codes
    `{"path": "title"}` keeps passing after the registry stops asking for `title`,
    which is precisely how a check goes quiet.
    """
    with open(REGISTRY, encoding="utf-8") as f:
        items = {i["id"]: i for i in json.load(f)["items"]}
    return items[item_id]["check"]


def verdict(item_id: str, output: dict) -> str:
    """Run an item's real rule over a script's real output, as the runner would."""
    check = registry_rule(item_id)
    ok, _ = evaluate(check["assert"], output)
    if ok is None:
        return NO_DATA
    if ok:
        return PASS
    warn = check.get("warn")
    if warn and evaluate(warn, output)[0]:
        return WARN
    return FAIL


class SharedHelpersStayShared(unittest.TestCase):
    def test_no_script_carries_its_own_copy_of_a_shared_helper(self):
        """Shared helpers have one definition, in seo_common, not one per caller.

        Each copied helper worked on its own; the defect appeared only when copies
        drifted or when the same policy had to change in several places. Keep both
        public and formerly-private spellings here, because a future script-local
        copy would most likely restore the leading underscore.
        """
        offenders = []
        for name in sorted(os.listdir(SCRIPTS)):
            if not name.endswith(".py") or name == "seo_common.py":
                continue
            with open(os.path.join(SCRIPTS, name), encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=name)
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name in (
                        "fetch_html", "walk_json", "_walk_json", "is_url",
                        "_is_url", "as_list", "favicon_href", "_rel_contains",
                        "page_nodes", "_page_nodes", "page_author_names",
                        "_page_author_names", "under_foreign_credit",
                        "_under_foreign_credit", "foreign_itemref_ids",
                        "_foreign_itemref_ids", "schema_values", "_schema_values"):
                    offenders.append(f"{name}:{node.lineno} defines {node.name}")
        self.assertEqual(offenders, [], "import it from seo_common instead: "
                                        + "; ".join(offenders))


class ADocumentDeclaresItsOwnEncoding(unittest.TestCase):
    """A server that sends bare `text/html` must not cost us the page's characters.

    `requests` reads the charset from `Content-Type` and falls back to ISO-8859-1 for
    `text/*` without one — the old HTTP default. A site that sends bare `text/html`
    and lets `<meta charset="utf-8">` speak for the page was therefore decoded as
    latin-1, so `—` arrived as `â\x80\x94` and every title, heading and word count
    downstream carried it. Nothing caught it until MB-105 compared the raw document
    against a rendered one and found two differences in a fixture built to have none:
    the browser had read the meta and we had not.

    Only a *declaration* wins — a BOM, an XML declaration, or a `<meta>`. Detection is
    deliberately not consulted, because a guess that rewrites a page's text silently is
    the failure this repository keeps paying for.
    """

    def response(self, body: bytes, content_type: str = "text/html"):
        import requests
        from lib.safe_http import _honour_declared_encoding
        made = requests.Response()
        made.status_code = 200
        made.headers = requests.structures.CaseInsensitiveDict(
            {"Content-Type": content_type} if content_type else {})
        made._content = body
        made._content_consumed = True
        made.encoding = requests.utils.get_encoding_from_headers(made.headers)
        _honour_declared_encoding(made)
        return made

    def test_a_meta_charset_is_honoured_when_the_header_is_silent(self):
        body = '<html><head><meta charset="utf-8"><title>a — b</title>'.encode("utf-8")
        made = self.response(body)
        self.assertEqual(made.encoding, "utf-8")
        self.assertIn("a — b", made.text)

    def test_the_server_wins_when_it_names_a_charset(self):
        """A document disagreeing with its server is a site defect for an item to
        report, not something to quietly correct here."""
        body = '<html><head><meta charset="utf-8"><title>a — b</title>'.encode("utf-8")
        made = self.response(body, "text/html; charset=iso-8859-1")
        self.assertEqual(made.encoding.lower(), "iso-8859-1")
        self.assertNotIn("a — b", made.text)

    def test_a_document_that_declares_nothing_is_left_alone(self):
        made = self.response(b"<html><head><title>plain</title>")
        self.assertEqual((made.encoding or "").upper(), "ISO-8859-1")

    def test_an_xml_declaration_counts(self):
        body = '<?xml version="1.0" encoding="utf-8"?><urlset><loc>a — b</loc>'.encode("utf-8")
        made = self.response(body, "application/xml")
        self.assertEqual(made.encoding, "utf-8")

    def test_a_utf8_bom_counts(self):
        made = self.response("﻿<html><title>a — b</title>".encode("utf-8-sig"))
        self.assertEqual(made.encoding, "utf-8-sig")
        self.assertIn("a — b", made.text)

    def test_an_unknown_charset_name_is_ignored_rather_than_raising(self):
        body = b'<html><head><meta charset="totally-not-a-codec"><title>x</title>'
        made = self.response(body)
        self.assertEqual((made.encoding or "").upper(), "ISO-8859-1")
        self.assertIn("x", made.text)

    def test_a_binary_content_type_is_never_touched(self):
        """The sniff is for markup and plain text. A PNG that happens to contain the
        bytes `charset=` is not declaring anything."""
        made = self.response(b'\x89PNG\r\n\x1a\n charset="utf-8"', "image/png")
        self.assertIsNone(made.encoding)

    def test_the_declaration_may_sit_past_the_first_kilobyte(self):
        padding = b"<link rel='preload' href='/a.css'>" * 40
        body = b"<html><head>" + padding + b'<meta charset="utf-8">'
        self.assertGreater(len(body), 1024)
        self.assertEqual(self.response(body).encoding, "utf-8")

    def test_a_declaration_past_the_sniff_window_is_not_read(self):
        """The window is a bound, not a suggestion; prove it stops rather than trusting
        that it does."""
        from lib.safe_http import ENCODING_SNIFF_BYTES
        body = (b" " * (ENCODING_SNIFF_BYTES + 1)) + b'<meta charset="utf-8">'
        self.assertEqual((self.response(body).encoding or "").upper(), "ISO-8859-1")

    def test_spaces_around_the_header_charset_still_count_as_the_server_naming_one(self):
        """`text/html; charset = utf-8` is parsed by `requests` as utf-8, so a substring
        test for `charset=` misses it and overwrites an encoding the server did name.
        That was a real defect in the first version of this code."""
        import requests
        from requests.structures import CaseInsensitiveDict
        headers = CaseInsensitiveDict({"Content-Type": "text/html; charset = utf-8"})
        self.assertEqual(requests.utils.get_encoding_from_headers(headers), "utf-8")
        made = self.response(b'<meta charset="iso-8859-1">', "text/html; charset = utf-8")
        self.assertEqual(made.encoding, "utf-8")

    def test_the_older_http_equiv_spelling_is_read(self):
        body = (b'<meta http-equiv="Content-Type" '
                b'content="text/html; charset=windows-1251">')
        self.assertEqual(self.response(body).encoding, "windows-1251")

    def test_a_commented_out_meta_does_not_decide_the_encoding(self):
        """A template that leaves `<!-- <meta charset="utf-8"> -->` behind must not
        thereby set the encoding of the live page. Browsers skip comments in the
        prescan for the same reason."""
        self.assertEqual(
            (self.response(b'<!-- <meta charset="utf-8"> --><title>x</title>')
             .encoding or "").upper(), "ISO-8859-1")
        # ...but a real declaration after a comment is still found.
        self.assertEqual(
            self.response(b'<!-- theme header --><meta charset="utf-8">').encoding,
            "utf-8")

    def test_a_missing_content_type_header_is_sniffed(self):
        """No header at all is the strongest case for reading the document."""
        self.assertEqual(self.response(b'<meta charset="utf-8">', "").encoding, "utf-8")

    def test_a_bom_outranks_a_meta_that_disagrees_with_it(self):
        body = "﻿".encode("utf-8") + b'<meta charset="windows-1251">'
        self.assertEqual(self.response(body).encoding, "utf-8-sig")


class LoadHtml(unittest.TestCase):
    def setUp(self):
        import seo_common
        self.common = seo_common
        self.saved_fetch = seo_common.fetch_url
        self.saved_cwd = os.getcwd()
        self.directory = tempfile.TemporaryDirectory()
        os.chdir(self.directory.name)

    def tearDown(self):
        self.common.fetch_url = self.saved_fetch
        os.chdir(self.saved_cwd)
        self.directory.cleanup()

    def test_a_dotted_filename_is_opened_without_fetching(self):
        expected = "<html><body>read from disk</body></html>"
        with open("page.html", "w", encoding="utf-8") as handle:
            handle.write(expected)

        def unexpected_fetch(*args, **kwargs):
            self.fail(f"load_html fetched an existing file: {args}, {kwargs}")

        self.common.fetch_url = unexpected_fetch
        self.assertFalse(self.common.is_url("page.html"))
        html, url, result = self.common.load_html("page.html")
        self.assertEqual(html, expected)
        self.assertEqual(url, "")
        self.assertEqual(result["url"], "page.html")

    def test_a_bare_domain_is_fetched_when_no_file_has_that_name(self):
        calls = []

        def fake_fetch(url, **kwargs):
            calls.append((url, kwargs))
            return {"text": "<html>fetched</html>", "url": "https://example.test/",
                    "status": 200, "headers": {}, "error": None}

        self.common.fetch_url = fake_fetch
        self.assertTrue(self.common.is_url("example.test"))
        html, url, _ = self.common.load_html("example.test", timeout=7)
        self.assertEqual(html, "<html>fetched</html>")
        self.assertEqual(url, "https://example.test/")
        self.assertEqual(calls, [("example.test", {"timeout": 7})])


class PrimaryLanguage(unittest.TestCase):
    def test_the_three_declared_sources_are_read_in_order_and_none_stays_none(self):
        import seo_common

        pages = (
            ('<html lang="lt-LT"><head>'
             '<meta http-equiv="content-language" content="ru">'
             '<meta property="og:locale" content="en_US"></head></html>', "lt"),
            ('<html><head><meta http-equiv="content-language" content="lt-LT">'
             '<meta property="og:locale" content="ru_RU"></head></html>', "lt"),
            ('<html><head><meta property="og:locale" content="ru_RU">'
             '</head></html>', "ru"),
            ('<html><head></head></html>', None),
        )
        for html, expected in pages:
            with self.subTest(expected=expected):
                parsed = seo_common.parse_html(html)
                self.assertEqual(
                    seo_common.primary_language(parsed, parsed["soup"]), expected)


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>A page with everything the critical items ask for</title>
<meta name="description" content="Enough of a description to be a description.">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="canonical" href="https://example.com/page">
</head><body><h1>One heading</h1><p>Some prose.</p></body></html>"""


class ParseHtml(unittest.TestCase):
    """Four critical items read this script: CI-004 (meta robots), MS-026 (title),
    CN-065 (one h1), MB-093 (viewport)."""

    def parse(self, html, url="https://example.com/page"):
        import parse_html
        return parse_html.parse_html(html, url)

    def test_a_complete_page_satisfies_all_four_critical_items(self):
        out = self.parse(PAGE)
        for item_id in ("CI-004", "MS-026", "CN-065", "MB-093"):
            self.assertEqual(verdict(item_id, out), PASS, item_id)

    def test_a_noindex_page_fails_ci_004(self):
        out = self.parse(PAGE.replace("<meta charset=\"utf-8\">",
                                      '<meta charset="utf-8">'
                                      '<meta name="robots" content="noindex, follow">'))
        self.assertEqual(out["meta_robots"], "noindex, follow")
        self.assertEqual(verdict("CI-004", out), FAIL)

    def test_an_absent_meta_robots_passes_because_the_rule_says_so(self):
        """The one place absence is an answer: no meta robots means indexable, and
        the rule carries `missing_is: pass` to say that out loud."""
        out = self.parse(PAGE)
        self.assertIsNone(out["meta_robots"])
        self.assertEqual(registry_rule("CI-004")["assert"]["missing_is"], "pass")
        self.assertEqual(verdict("CI-004", out), PASS)

    def test_a_missing_title_and_a_missing_viewport_fail(self):
        no_title = self.parse(PAGE.replace(
            "<title>A page with everything the critical items ask for</title>", ""))
        self.assertIsNone(no_title["title"])
        self.assertEqual(verdict("MS-026", no_title), FAIL)
        no_viewport = self.parse(PAGE.replace(
            '<meta name="viewport" content="width=device-width, initial-scale=1">', ""))
        self.assertIsNone(no_viewport["viewport"])
        self.assertEqual(verdict("MB-093", no_viewport), FAIL)

    def test_two_h1s_and_no_h1_both_fail_cn_065(self):
        two = self.parse(PAGE.replace("<h1>One heading</h1>",
                                      "<h1>One</h1><h1>Two</h1>"))
        self.assertEqual(len(two["h1"]), 2)
        self.assertEqual(verdict("CN-065", two), FAIL)
        none = self.parse(PAGE.replace("<h1>One heading</h1>", "<h2>Not an h1</h2>"))
        self.assertEqual(verdict("CN-065", none), FAIL)

    def test_meta_keywords_is_emitted_at_all(self):
        """MS-031 asserts this is falsy with `missing_is: pass`, and the script never
        emitted the key — so the item passed on every site ever audited, including
        one with a stuffed keywords tag. A rule can only be as honest as the
        existence of the field it reads."""
        out = self.parse(PAGE)
        self.assertIn("meta_keywords", out)
        self.assertIsNone(out["meta_keywords"])
        self.assertEqual(verdict("MS-031", out), PASS)
        stuffed = self.parse(PAGE.replace(
            "</head>", '<meta name="keywords" content="seo, seo services, cheap seo">'
                       "</head>"))
        self.assertEqual(stuffed["meta_keywords"], "seo, seo services, cheap seo")
        self.assertEqual(verdict("MS-031", stuffed), FAIL)

    def test_ar_158_requires_parseable_schema_and_a_visible_ui_marker(self):
        schema = ('<script type="application/ld+json">'
                  '{"@context":"https://schema.org",'
                  '"@type":"BreadcrumbList","itemListElement":[]}'
                  '</script>')
        schema_only = self.parse(PAGE.replace("</head>", schema + "</head>"))
        self.assertEqual(schema_only["breadcrumbs"], {"schema": True, "ui": False})
        self.assertEqual(verdict("AR-158", schema_only), FAIL)

        complete = self.parse(PAGE.replace(
            "</head>", schema + "</head>").replace(
                "<body>", '<body><nav aria-label="Breadcrumb">Home</nav>'))
        self.assertEqual(complete["breadcrumbs"], {"schema": True, "ui": True})
        self.assertEqual(verdict("AR-158", complete), PASS)

    def test_ar_158_accepts_each_explicit_ui_marker(self):
        markers = (
            '<nav aria-label="Breadcrumb trail"><a href="/">Home</a></nav>',
            ('<span id="crumb-label">Breadcrumb trail</span>'
             '<nav aria-labelledby="crumb-label"><a href="/">Home</a></nav>'),
            '<ol class="site-breadcrumbs"><li>Home</li></ol>',
            '<div id="breadcrumb-trail"><a href="/">Home</a></div>',
        )
        for marker in markers:
            with self.subTest(marker=marker):
                out = self.parse(PAGE.replace("<body>", "<body>" + marker))
                self.assertTrue(out["breadcrumbs"]["ui"])
                self.assertFalse(out["breadcrumbs"]["schema"])

    def test_ar_158_accepts_microdata_and_rdfa_as_ui_and_schema(self):
        markers = (
            ('<ol itemscope itemtype="https://schema.org/BreadcrumbList">'
             '<li>Home</li></ol>'),
            '<ol typeof="schema:BreadcrumbList"><li>Home</li></ol>',
        )
        for marker in markers:
            with self.subTest(marker=marker):
                out = self.parse(PAGE.replace("<body>", "<body>" + marker))
                self.assertEqual(out["breadcrumbs"], {"schema": True, "ui": True})

    def test_ar_158_does_not_infer_plain_links_or_invalid_json_ld(self):
        plain = '<p><a href="/">Home</a> / <a href="/shop">Shop</a></p>'
        invalid = '<script type="application/ld+json">{"@type":"BreadcrumbList"</script>'
        out = self.parse(PAGE.replace("<body>", "<body>" + plain).replace(
            "</head>", invalid + "</head>"))
        self.assertEqual(out["breadcrumbs"], {"schema": False, "ui": False})

    def test_cn_048_passes_a_hierarchical_h1_only_semantic_page(self):
        html = ("<html><body><nav>Site</nav><main><h1>Gallery</h1>"
                "<p>Photographs need no artificial subheadings.</p></main>"
                "<footer>Contact</footer></body></html>")
        out = self.parse(html)
        self.assertEqual(out["h2"], [])
        self.assertEqual(out["issues"], [])
        self.assertEqual(verdict("CN-048", out), PASS)
        self.assertEqual(verdict("CN-066", out), FAIL)

    def test_cn_048_fails_a_skipped_heading_level(self):
        html = ("<html><body><nav>Site</nav><main><h1>Menu</h1>"
                "<h3>Dessert</h3></main><footer>Contact</footer></body></html>")
        out = self.parse(html)
        self.assertIn("error", [finding["severity"] for finding in out["issues"]])
        self.assertIn("H1 to H3", out["issues"][0]["message"])
        self.assertEqual(verdict("CN-048", out), FAIL)

    def test_cn_048_fails_a_page_that_never_marks_its_main_content(self):
        no_main = self.parse(
            "<html><body><nav>Site</nav><h1>Menu</h1><footer>Contact</footer>"
            "</body></html>")
        self.assertEqual([finding["severity"] for finding in no_main["issues"]],
                         ["error"])
        self.assertEqual(verdict("CN-048", no_main), FAIL)

    def test_cn_048_does_not_penalise_a_page_for_having_no_nav_or_footer(self):
        """Absence of `nav` or `footer` is page design, not markup semantics.

        Both were warnings when this item was rewritten, and that put the
        exemplary fixture into WARN over a blog post with no footer — an
        entirely ordinary page. `main` stays an error because every page has
        main content, so failing to mark it is a real defect."""
        for shape, html in (
            ("no nav", "<main><h1>Menu</h1></main><footer>Contact</footer>"),
            ("no footer", "<nav>Site</nav><main><h1>Menu</h1></main>"),
            ("neither", "<main><h1>Menu</h1></main>"),
        ):
            with self.subTest(shape=shape):
                out = self.parse(f"<html><body>{html}</body></html>")
                self.assertEqual(out["issues"], [])
                self.assertEqual(verdict("CN-048", out), PASS)


class IndexabilityMatrix(unittest.TestCase):
    """Four critical items read this script: CI-001 (indexable), CI-003 (200),
    CI-005 (robots allows), CI-015 (no 5xx)."""

    def setUp(self):
        import indexability_matrix as ix
        self.ix = ix
        self.saved = (ix.fetch_url, ix.fetch_robots, ix.urls_from_sitemaps)
        ix.urls_from_sitemaps = lambda *a, **k: set()

    def tearDown(self):
        (self.ix.fetch_url, self.ix.fetch_robots,
         self.ix.urls_from_sitemaps) = self.saved

    def serve(self, status=200, html=PAGE, headers=None, robots=""):
        hdrs = {"content-type": "text/html; charset=utf-8"}
        hdrs.update({k.lower(): v for k, v in (headers or {}).items()})

        def fake_fetch(url, **kw):
            return {"url": url, "status": status, "headers": hdrs, "text": html,
                    "redirect_chain": [], "error": None}
        self.ix.fetch_url = fake_fetch
        from seo_common import parse_robots_txt
        self.ix.fetch_robots = lambda *a, **k: {
            "url": "https://example.com/robots.txt",
            "fetch": {"status": 200 if robots else 404},
            "parsed": parse_robots_txt(robots) if robots else None}

    def test_a_healthy_page_satisfies_all_four(self):
        self.serve()
        out = self.ix.evaluate(["https://example.com/page"], "https://example.com/")
        self.assertEqual(out["rows"][0]["status"], 200)
        self.assertIs(out["rows"][0]["robots_allowed"], True)
        self.assertEqual(out["rows"][0]["verdict"], "indexable")
        for item_id in ("CI-001", "CI-003", "CI-005", "CI-015"):
            self.assertEqual(verdict(item_id, out), PASS, item_id)

    def test_a_500_fails_both_status_items(self):
        self.serve(status=503)
        out = self.ix.evaluate(["https://example.com/page"], "https://example.com/")
        self.assertEqual(verdict("CI-003", out), FAIL)
        self.assertEqual(verdict("CI-015", out), FAIL)

    def test_a_robots_disallow_fails_ci_005(self):
        self.serve(robots="User-agent: *\nDisallow: /page\n")
        out = self.ix.evaluate(["https://example.com/page"], "https://example.com/")
        self.assertIs(out["rows"][0]["robots_allowed"], False)
        self.assertEqual(verdict("CI-005", out), FAIL)

    def test_a_noindex_page_is_not_indexable_and_ci_001_says_so(self):
        """CI-001 is "ensure the URL is indexed" and used to assert
        `robots_allowed` — the same field, and the same rule, as CI-005. A page
        crawlable by robots.txt and marked `noindex` passed a critical item about
        being indexed. The script's own `verdict` accounts for meta robots,
        X-Robots-Tag, the status and a canonical pointing elsewhere; nothing in the
        registry read it."""
        self.serve(html=PAGE.replace("</head>",
                                     '<meta name="robots" content="noindex"></head>'))
        out = self.ix.evaluate(["https://example.com/page"], "https://example.com/")
        row = out["rows"][0]
        self.assertIs(row["robots_allowed"], True)
        self.assertEqual(row["verdict"], "not_indexable")
        self.assertIn("meta robots noindex", row["blockers"])
        self.assertEqual(verdict("CI-001", out), FAIL)
        self.assertEqual(verdict("CI-005", out), PASS, "robots.txt is not the problem")

    def test_an_x_robots_noindex_header_is_caught_too(self):
        """The half of CI-004's title — "Meta Robots / X-Robots-Tag" — that
        `parse_html.py` cannot see: it is handed a file, so it never has headers. A
        CDN noindexing a whole path does it with the header."""
        self.serve(headers={"X-Robots-Tag": "noindex"})
        out = self.ix.evaluate(["https://example.com/page"], "https://example.com/")
        self.assertIn("x-robots-tag noindex", out["rows"][0]["blockers"])
        self.assertEqual(verdict("CI-001", out), FAIL)


class SnippetControls(unittest.TestCase):
    """GEO-008 reads both response surfaces through the real fixture server."""

    def check(self, response):
        import indexability_matrix as ix
        saved = ix.urls_from_sitemaps
        ix.urls_from_sitemaps = lambda *a, **k: set()
        try:
            with served({"/": response}) as site, allow_loopback():
                return ix.evaluate([site.url], site.url)
        finally:
            ix.urls_from_sitemaps = saved

    def test_meta_delivered_nosnippet_fails_and_reads_googlebot(self):
        html = PAGE.replace(
            "</head>", '<meta name="googlebot" content="nosnippet"></head>')
        out = self.check(html)
        controls = out["rows"][0]["snippet_controls"]
        self.assertIs(controls["nosnippet"], True)
        self.assertEqual(controls["nosnippet_sources"], ["meta googlebot"])
        self.assertEqual(controls["snippet_availability"], "suppressed")
        self.assertEqual(verdict("GEO-008", out), FAIL)

    def test_header_delivered_nosnippet_fails(self):
        out = self.check((200, {"X-Robots-Tag": "nosnippet"}, PAGE))
        controls = out["rows"][0]["snippet_controls"]
        self.assertEqual(controls["nosnippet_sources"], ["x-robots-tag"])
        self.assertEqual(controls["snippet_availability"], "suppressed")
        self.assertEqual(verdict("GEO-008", out), FAIL)

    def test_max_snippet_minus_one_is_unlimited_and_passes(self):
        html = PAGE.replace(
            "</head>", '<meta name="robots" content="max-snippet:-1"></head>')
        out = self.check(html)
        controls = out["rows"][0]["snippet_controls"]
        self.assertEqual(controls["max_snippet"], -1)
        self.assertIs(controls["restricted"], False)
        self.assertEqual(controls["snippet_availability"], "full")
        self.assertEqual(verdict("GEO-008", out), PASS)

    def test_max_snippet_zero_suppresses_snippets_and_fails(self):
        out = self.check((200, {"X-Robots-Tag": "max-snippet: 0"}, PAGE))
        controls = out["rows"][0]["snippet_controls"]
        self.assertEqual(controls["max_snippet"], 0)
        self.assertIs(controls["restricted"], True)
        self.assertEqual(controls["snippet_availability"], "suppressed")
        self.assertEqual(verdict("GEO-008", out), FAIL)

    def test_a_positive_max_snippet_is_limited_and_warns(self):
        html = PAGE.replace(
            "</head>", '<meta name="robots" content="max-snippet:120"></head>')
        out = self.check(html)
        controls = out["rows"][0]["snippet_controls"]
        self.assertEqual(controls["max_snippet"], 120)
        self.assertEqual(controls["snippet_availability"], "limited")
        self.assertEqual(verdict("GEO-008", out), WARN)

    def test_data_nosnippet_is_detected_and_counted(self):
        html = PAGE.replace("<p>Some prose.</p>",
                            "<p data-nosnippet>Hidden prose.</p>"
                            "<span data-nosnippet>Hidden detail.</span>")
        out = self.check(html)
        controls = out["rows"][0]["snippet_controls"]
        self.assertEqual(controls["data_nosnippet_count"], 2)
        self.assertEqual(controls["data_nosnippet_sources"],
                         ["html data-nosnippet attribute"])
        self.assertEqual(controls["snippet_availability"], "limited")
        self.assertEqual(verdict("GEO-008", out), WARN)

    def test_data_nosnippet_on_the_whole_body_suppresses_and_fails(self):
        out = self.check(PAGE.replace("<body>", "<body data-nosnippet>"))
        controls = out["rows"][0]["snippet_controls"]
        self.assertEqual(controls["data_nosnippet_count"], 1)
        self.assertEqual(controls["snippet_availability"], "suppressed")
        self.assertEqual(verdict("GEO-008", out), FAIL)

    def test_only_whitespace_outside_data_nosnippet_suppresses_and_fails(self):
        html = ("<html><head><title>Excluded head text</title></head><body> \n"
                "<div data-nosnippet>Hidden prose.</div> \t</body></html>")
        out = self.check(html)
        controls = out["rows"][0]["snippet_controls"]
        self.assertEqual(controls["snippet_availability"], "suppressed")
        self.assertEqual(verdict("GEO-008", out), FAIL)

    def test_a_clean_page_passes(self):
        out = self.check(PAGE)
        controls = out["rows"][0]["snippet_controls"]
        self.assertIs(controls["restricted"], False)
        self.assertEqual(controls["snippet_availability"], "full")
        self.assertEqual(verdict("GEO-008", out), PASS)

    def test_no_document_or_header_leaves_availability_absent(self):
        out = self.check("")
        controls = out["rows"][0]["snippet_controls"]
        self.assertIs(controls["restricted"], False)
        self.assertNotIn("snippet_availability", controls)
        self.assertEqual(verdict("GEO-008", out), NO_DATA)

    def test_the_three_availability_states_produce_the_required_verdicts(self):
        cases = [
            (PAGE, "full", PASS),
            (PAGE.replace("</head>",
                          '<meta name="robots" content="max-snippet:-1"></head>'),
             "full", PASS),
            (PAGE.replace("</head>",
                          '<meta name="robots" content="max-snippet:120"></head>'),
             "limited", WARN),
            (PAGE.replace("<p>Some prose.</p>",
                          "<p data-nosnippet>Hidden prose.</p>"), "limited", WARN),
            (PAGE.replace("</head>",
                          '<meta name="robots" content="nosnippet"></head>'),
             "suppressed", FAIL),
            (PAGE.replace("</head>",
                          '<meta name="googlebot" content="nosnippet"></head>'),
             "suppressed", FAIL),
            ((200, {"X-Robots-Tag": "nosnippet"}, PAGE), "suppressed", FAIL),
            ((200, {"X-Robots-Tag": "max-snippet: 0"}, PAGE), "suppressed", FAIL),
            (PAGE.replace("</head>", '<meta name="robots" '
                          'content="max-snippet:-1, max-snippet:0"></head>'),
             "suppressed", FAIL),
        ]
        for response, availability, expected in cases:
            with self.subTest(response=str(response)[:80]):
                out = self.check(response)
                self.assertEqual(out["rows"][0]["snippet_controls"]
                                 ["snippet_availability"], availability)
                self.assertEqual(verdict("GEO-008", out), expected)


class CanonicalChecker(unittest.TestCase):
    """CI-009 (critical) and CI-011 (high) read this script's `verdict`."""

    def setUp(self):
        import canonical_checker as cc
        self.cc = cc
        self.saved = cc.fetch_url

    def tearDown(self):
        self.cc.fetch_url = self.saved

    def serve(self, canonical, status=200):
        html = PAGE.replace('<link rel="canonical" href="https://example.com/page">',
                            f'<link rel="canonical" href="{canonical}">'
                            if canonical else "")

        def fake(url, **kw):
            return {"url": url, "status": status,
                    "headers": {"content-type": "text/html"},
                    "text": html, "redirect_chain": [], "error": None}
        self.cc.fetch_url = fake

    def check(self):
        return self.cc.check_canonicals(["https://example.com/page"])

    def test_a_self_canonical_passes(self):
        self.serve("https://example.com/page")
        out = self.check()
        self.assertEqual(out["rows"][0]["verdict"], "self_canonical")
        self.assertEqual(verdict("CI-009", out), PASS)

    def test_a_cross_host_canonical_fails(self):
        self.serve("https://other.example.net/page")
        out = self.check()
        self.assertEqual(out["rows"][0]["verdict"], "cross_host")
        self.assertEqual(verdict("CI-009", out), FAIL)

    def test_no_canonical_at_all_fails_ci_009_and_passes_ci_011(self):
        """The split is deliberate: CI-009 is "serve content at a single canonical
        URL", so declaring none is the failure it names; CI-011 is about a canonical
        that contradicts something else, and there is nothing to contradict."""
        self.serve(None)
        out = self.check()
        self.assertEqual(out["rows"][0]["verdict"], "missing")
        self.assertEqual(verdict("CI-009", out), FAIL)
        self.assertEqual(verdict("CI-011", out), PASS)

    def test_the_old_rule_could_not_fire_at_all(self):
        """CI-009 asserted `issues` had no critical/high entry. This script says
        "warning" and "error" and never those two words, so the rule matched nothing
        and the item reported PASS on every site ever audited — including this one,
        whose canonical points at another domain."""
        self.serve("https://other.example.net/page")
        out = self.check()
        emitted = {i["severity"] for i in out["issues"]}
        self.assertTrue(emitted)
        self.assertFalse(emitted & {"critical", "high"})
        ok, _ = evaluate({"path": "issues",
                          "none_severity": ["critical", "high"]}, out)
        self.assertIs(ok, True, "the retired rule still passes — that was the bug")

    def test_an_unreadable_page_is_undecided(self):
        self.serve("https://example.com/page", status=500)
        self.check()          # asserts only that a 500 does not raise
        # No text is parsed on a 500 here, so the verdict is `missing`; what matters
        # is that `unknown` — which the script emits when it has nothing at all —
        # stays out of the map and lands on NO_DATA.
        rule = registry_rule("CI-009")["assert"]
        self.assertNotIn("unknown", rule["value_map"])
        ok, _ = evaluate(rule, {"rows": [{"verdict": "unknown"}]})
        self.assertIsNone(ok)


class RobotsPathTester(unittest.TestCase):
    """CI-013 (critical): may Googlebot fetch the page's own CSS, JS and images?"""

    def setUp(self):
        import robots_path_tester as rpt
        self.rpt = rpt
        self.saved = (rpt.fetch_robots, rpt.safe_get)
        self.args = registry_rule("CI-013")["args"]

    def tearDown(self):
        self.rpt.fetch_robots, self.rpt.safe_get = self.saved

    def serve(self, body, status=200):
        from seo_common import parse_robots_txt
        self.rpt.fetch_robots = lambda *a, **k: {
            "url": "https://example.com/robots.txt",
            "fetch": {"status": status},
            "parsed": parse_robots_txt(body) if status == 200 else None}

    def run_test(self, paths):
        return self.rpt.test_paths("https://example.com/", paths, ["Googlebot"])

    def test_registry_discovers_assets_instead_of_inventing_paths(self):
        self.assertIn("--discover-assets", self.args)
        self.assertEqual([arg for arg in self.args[1:] if arg.startswith("/")], [])

    def test_only_same_origin_page_assets_are_discovered(self):
        class Response:
            status_code = 200
            url = "https://example.com/guide/"
            text = """<link rel=\"stylesheet\" href=\"/assets/site.css\">
                <script src=\"app.js\"></script>
                <img src=\"/images/hero.jpg\"
                     srcset=\"/images/hero-2x.jpg 2x, https://cdn.example/hero.jpg 3x\">
                <script src=\"https://third.example/tracker.js\"></script>
                <img src=\"http://example.com/not-same-origin.jpg\">"""

        self.rpt.safe_get = lambda *a, **k: Response()
        found, error = self.rpt.discover_asset_paths("https://example.com/guide/")
        self.assertIsNone(error)
        self.assertEqual(found, ["/assets/site.css", "/guide/app.js",
                                 "/images/hero-2x.jpg", "/images/hero.jpg"])

    def test_assets_reachable_passes(self):
        self.serve("User-agent: *\nDisallow: /admin\n")
        out = self.run_test(["/assets/site.css", "/app.js", "/hero.jpg"])
        self.assertEqual(out["blocked_urls"], [])
        self.assertEqual(verdict("CI-013", out), PASS)

    def test_a_blocked_asset_directory_fails(self):
        self.serve("User-agent: *\nDisallow: /assets/\nDisallow: /static/\n")
        out = self.run_test(["/assets/site.css", "/static/app.js", "/hero.jpg"])
        self.assertEqual(len(out["blocked_urls"]), 2)
        self.assertEqual(verdict("CI-013", out), FAIL)

    def test_a_page_with_no_blockable_asset_is_undecided(self):
        self.serve("User-agent: *\nDisallow: /admin\n")
        out = self.run_test([])
        self.assertNotIn("blocked_urls", out)
        self.assertEqual(verdict("CI-013", out), NO_DATA)

    def test_an_unreachable_robots_txt_is_undecided_not_clean(self):
        """A 500 says nothing about whether the page's own assets are blocked."""
        self.serve("", status=500)
        out = self.run_test(["/assets/site.css"])
        self.assertNotIn("blocked_urls", out)
        self.assertEqual(verdict("CI-013", out), NO_DATA)


class SystemPagesAreNotIndexable(unittest.TestCase):
    """CI-019 (high): the same script as CI-013, read in the opposite direction.

    The item's history is two opposite defects in the same field. Until 0.13 the rule
    matched text across a nested dict, `allowed` and `true` never landed in one string,
    and every site passed. Flattening to `allowed_urls` fixed that and produced the
    inverse: `allowed_urls` is computed from robots.txt alone, so a café with no cart
    is accused of exposing `/cart` — nothing disallows a page that does not exist.

    0.20 asserts `indexable_urls` instead, which requires a fetch: the path is there,
    a crawler may have it, and nothing keeps it out of the index. `noindex` counts,
    which is what the item's title said all along.
    """

    def setUp(self):
        import robots_path_tester as rpt
        self.rpt = rpt
        self.saved = (rpt.fetch_robots, rpt.safe_get)
        self.paths = [a for a in registry_rule("CI-019")["args"][1:]
                      if a.startswith("/")]

    def tearDown(self):
        self.rpt.fetch_robots, self.rpt.safe_get = self.saved

    def serve_robots(self, body, status=200):
        from seo_common import parse_robots_txt
        self.rpt.fetch_robots = lambda *a, **k: {
            "url": "https://example.com/robots.txt",
            "fetch": {"status": status},
            "parsed": parse_robots_txt(body) if status == 200 else None}

    def serve_pages(self, by_path):
        """`{path: (status, body, headers)}`; anything unlisted is a 404."""
        class Resp:
            def __init__(self, status, body, headers):
                self.status_code, self.text, self.headers = status, body, headers

        def fake_get(url, **kwargs):
            path = url[url.index("/", 8):]
            status, body, headers = by_path.get(path, (404, "", {}))
            return Resp(status, body, headers)
        self.rpt.safe_get = fake_get

    def run_test(self):
        return self.rpt.test_paths("https://example.com/", self.paths,
                                   ["Googlebot"], probe=True)

    OPEN = "User-agent: *\nDisallow: /admin\n"

    def test_a_site_without_those_pages_is_not_accused(self):
        """The defect that a live audit found and the fixture could not.

        Every path 404s, robots.txt disallows nothing, and the pre-0.20 assertion
        counted four permitted URLs and failed a `high` item on a site that has no
        cart, no checkout and no login.
        """
        self.serve_robots(self.OPEN)
        self.serve_pages({})
        out = self.run_test()
        self.assertEqual(len(out["allowed_urls"]), len(self.paths))   # old field
        self.assertEqual(out["indexable_urls"], [])                   # new one
        self.assertEqual(verdict("CI-019", out), PASS)

    def test_a_reachable_system_page_with_nothing_stopping_it_fails(self):
        self.serve_robots(self.OPEN)
        self.serve_pages({"/cart": (200, "<html><body>Your cart</body></html>", {})})
        out = self.run_test()
        self.assertEqual(out["indexable_urls"], ["https://example.com/cart"])
        self.assertEqual(verdict("CI-019", out), FAIL)

    def test_noindex_satisfies_the_item_in_either_place_it_can_be_written(self):
        """Meta tag on one page, `X-Robots-Tag` on another. The title has always
        asked for `noindex`; before 0.20 writing one changed nothing."""
        self.serve_robots(self.OPEN)
        self.serve_pages({
            "/cart": (200, '<html><head><meta name="robots" content="noindex,follow">'
                           "</head><body>c</body></html>", {}),
            "/login": (200, "<html><body>l</body></html>",
                       {"X-Robots-Tag": "noindex"}),
        })
        out = self.run_test()
        self.assertEqual(out["indexable_urls"], [])
        self.assertEqual(verdict("CI-019", out), PASS)

    def test_a_noindex_written_inside_a_comment_is_not_a_noindex(self):
        """Markup inside a comment is not markup, and this is not a hypothetical.

        The first version of the probe read `noindex` off a `<meta name="robots">`
        that a fixture page's comment block quoted while explaining that the page
        deliberately has no such tag — so the page built to fail CI-019 passed it.
        The registry's own history of this: the keyword items fired on their own
        remediation text in 0.5.0, and the soft-404 guard carries the warning that
        `404` appears in the title of every article ever written about broken links.
        """
        self.serve_robots(self.OPEN)
        self.serve_pages({"/cart": (200,
                                    '<html><head><!-- deliberately absent: <meta '
                                    'name="robots" content="noindex"> --></head>'
                                    "<body>Your cart</body></html>", {})})
        out = self.run_test()
        self.assertEqual(out["indexable_urls"], ["https://example.com/cart"])
        self.assertEqual(verdict("CI-019", out), FAIL)

    def test_a_path_disallowed_in_robots_is_never_fetched(self):
        """The other accepted mechanism, and a request the run must not spend: a
        blocked path is out of the index already, and fetching it to confirm that
        would buy nothing."""
        fetched = []
        self.serve_robots("User-agent: *\nDisallow: /cart\n")
        self.serve_pages({"/cart": (200, "<html><body>c</body></html>", {})})
        inner = self.rpt.safe_get
        self.rpt.safe_get = lambda url, **k: (fetched.append(url), inner(url, **k))[1]
        out = self.run_test()
        self.assertNotIn("https://example.com/cart", fetched)
        self.assertNotIn("https://example.com/cart", out["indexable_urls"])

    def test_a_failed_probe_is_not_evidence_of_a_clean_site(self):
        """A page we could not reach is neither indexable nor proven absent. It goes
        to `unprobed_urls`, where it cannot be read as either verdict."""
        self.serve_robots(self.OPEN)

        def explode(url, **kwargs):
            raise OSError("connection reset")
        self.serve_pages({})
        self.rpt.safe_get = explode
        out = self.run_test()
        self.assertEqual(out["indexable_urls"], [])
        self.assertEqual(len(out["unprobed_urls"]), len(self.paths))

    def test_an_unreachable_robots_txt_is_still_undecided(self):
        self.serve_robots("", status=500)
        self.serve_pages({})
        out = self.run_test()
        self.assertNotIn("indexable_urls", out)
        self.assertEqual(verdict("CI-019", out), NO_DATA)


class SecurityHeaders(unittest.TestCase):
    """SE-117 (critical) reads `https`; TE-175 (high) reads `headers_missing`.

    SE-118 read `https` too until 0.20, from this same script — two critical items
    sharing one field, so SE-118 could not fail independently on any site and a
    certificate that expired yesterday passed it. It now reads `valid` from
    `tls_certificate.py` (`test_tls_certificate.py`). The other half of that fix is
    asserted here: this script's output can no longer decide SE-118 at all.
    """

    def setUp(self):
        import security_headers as sh
        self.sh = sh
        self.saved = sh.safe_get

    def tearDown(self):
        self.sh.safe_get = self.saved

    def serve(self, url, headers=None):
        class Resp:
            def __init__(self):
                self.url = url
                self.headers = headers or {}
                self.status_code = 200
        self.sh.safe_get = lambda *a, **k: Resp()

    ALL_HEADERS = {
        "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
        "Content-Security-Policy": "default-src 'self'",
        "X-Frame-Options": "SAMEORIGIN",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Permissions-Policy": "camera=()",
    }

    def test_https_with_every_header_passes_both_items_it_decides(self):
        self.serve("https://example.com/", self.ALL_HEADERS)
        out = self.sh.check_security_headers("https://example.com/")
        self.assertIs(out["https"], True)
        self.assertEqual(out["headers_missing"], {})
        for item_id in ("SE-117", "TE-175"):
            self.assertEqual(verdict(item_id, out), PASS, item_id)

    def test_plain_http_fails_the_critical_item(self):
        self.serve("http://example.com/", {})
        out = self.sh.check_security_headers("http://example.com/")
        self.assertIs(out["https"], False)
        self.assertEqual(verdict("SE-117", out), FAIL)

    def test_missing_hsts_fails_se_115_instead_of_becoming_no_data(self):
        """An absent required header is measured absence, not missing evidence."""
        self.serve("https://example.com/", {})
        out = self.sh.check_security_headers("https://example.com/")
        self.assertIn("strict-transport-security", out["header_values"])
        self.assertEqual(out["header_values"]["strict-transport-security"], "")
        self.assertEqual(verdict("SE-115", out), FAIL)

    def test_this_script_cannot_decide_se_118_in_either_direction(self):
        """The regression guard for the 0.20 fix, and the reason it is two asserts.

        A scheme is not a certificate. Whatever this script says about `https`, the
        item that claims a certificate was verified must not resolve from it — and
        `NO_DATA` on both a good and a bad response is what proves the field it used
        to read is genuinely gone rather than merely renamed.
        """
        for url, headers in (("https://example.com/", self.ALL_HEADERS),
                             ("http://example.com/", {})):
            self.serve(url, headers)
            out = self.sh.check_security_headers(url)
            self.assertEqual(verdict("SE-118", out), NO_DATA, url)

    def test_te_175_reads_a_field_and_not_the_prose(self):
        """This script appends plain strings to `issues`, so the old
        `none_severity` rule iterated dicts, found none, and reported PASS — while
        the script itself was printing "Site not using HTTPS" and "6 security
        headers missing". `headers_missing` is a dict, and the rule uses the
        script's own bar: more than three of six absent is a failure."""
        self.serve("http://example.com/", {})
        out = self.sh.check_security_headers("http://example.com/")
        self.assertEqual(len(out["headers_missing"]), 6)
        self.assertTrue(out["issues"])
        self.assertFalse([i for i in out["issues"] if isinstance(i, dict)],
                         "issues are strings; no severity rule can read them")
        ok, _ = evaluate({"path": "issues",
                          "none_severity": ["critical", "high"]}, out)
        self.assertIsNone(ok, "a list of strings must be undecided, never a pass")
        self.assertEqual(verdict("TE-175", out), FAIL)

    def test_three_missing_headers_is_still_a_pass(self):
        keep = dict(list(self.ALL_HEADERS.items())[:3])
        self.serve("https://example.com/", keep)
        out = self.sh.check_security_headers("https://example.com/")
        self.assertEqual(len(out["headers_missing"]), 3)
        self.assertEqual(verdict("TE-175", out), PASS)


class PageSpeed(unittest.TestCase):
    """SP-108 and SP-113 (critical), SP-107 (high), SE-119 (medium). No network:
    `parse_pagespeed_response` is the whole contract, and the API payload is the
    input."""

    def setUp(self):
        import pagespeed
        self.ps = pagespeed

    def crux(self, lcp_category="FAST", inp_category="FAST", cls_category="FAST"):
        return {
            "loadingExperience": {"metrics": {
                "LARGEST_CONTENTFUL_PAINT_MS": {"percentile": 1800,
                                                "category": lcp_category},
                "INTERACTION_TO_NEXT_PAINT": {"percentile": 120,
                                              "category": inp_category},
                "CUMULATIVE_LAYOUT_SHIFT_SCORE": {"percentile": 5,
                                                  "category": cls_category},
                "FIRST_CONTENTFUL_PAINT_MS": {"percentile": 1200,
                                              "category": "FAST"},
            }},
            "lighthouseResult": {"categories": {"performance": {"score": 0.98}}},
        }

    def lab_only(self, lcp_ms=1500):
        return {"lighthouseResult": {
            "categories": {"performance": {"score": 0.97}},
            "audits": {
                "largest-contentful-paint": {"numericValue": lcp_ms},
                "cumulative-layout-shift": {"numericValue": 0.02},
                "first-contentful-paint": {"numericValue": 900},
            }}}

    def parse(self, payload):
        return self.ps.parse_pagespeed_response(payload, "https://example.com/",
                                                "mobile")

    def test_a_rating_says_which_kind_of_measurement_it_is(self):
        """`openspec/specs/inputs/` INP-5. Both branches write `metrics.*.rating`, and two
        items decide from it without their titles mentioning field data — SP-107 reads FCP,
        SE-119 reads CLS. Without `source` beside the rating, a verdict earned on one
        synthetic load in a datacentre is indistinguishable in the payload from one earned
        on what real visitors got, and the report has nothing to disclose."""
        self.assertEqual(self.parse(self.crux())["metrics"]["FCP"]["source"], "field")
        lab = self.parse(self.lab_only())["metrics"]
        self.assertEqual({m["source"] for m in lab.values()}, {"lab"})

    def test_field_data_is_normalised_to_one_vocabulary(self):
        out = self.parse(self.crux())
        self.assertIs(out["field_data_available"], True)
        self.assertEqual(out["metrics"]["LCP"]["rating"], "good")
        self.assertEqual(out["metrics"]["LCP"]["crux_category"], "fast")
        self.assertEqual(verdict("SP-113", out), PASS)
        self.assertEqual(verdict("SP-108", out), PASS)

    def test_a_fast_page_without_crux_data_is_no_longer_failed(self):
        """The bug: CrUX said FAST and Lighthouse says `good`, both went into the
        same `rating`, and the rule compared it to "fast". CrUX publishes nothing for
        a low-traffic URL — most of the sites this tool audits — so a page with a
        1.5s lab LCP failed two critical items for being small."""
        out = self.parse(self.lab_only(lcp_ms=1500))
        self.assertIs(out["field_data_available"], False)
        self.assertEqual(out["metrics"]["LCP"]["rating"], "good")
        ok, _ = evaluate({"path": "metrics.LCP.rating", "eq": "fast"}, out)
        self.assertIs(ok, False, "the retired rule still fails a fast page")
        # 0.25.0 changed this deliberately, and it is a breaking change worth naming:
        # SP-113 used to PASS here. `metrics` carries CrUX when there is field data and
        # Lighthouse's lab audits when there is not, so an item reading `metrics.LCP`
        # switched data source without saying so — a `critical` PASS about "Core Web
        # Vitals", earned on a lab number, on exactly the small sites CrUX has no sample
        # for. Core Web Vitals are field metrics by definition; with no field data the
        # honest verdict is the one SP-108 already gave, and the lab measurement of this
        # same page has its own items (SP-214 to SP-216) fed from a browser trace.
        self.assertEqual(verdict("SP-113", out), NO_DATA)
        self.assertEqual(verdict("SP-108", out), NO_DATA)

    def test_no_field_data_leaves_sp_108_undecided(self):
        """"CrUX has no sample for this URL" is not "real users had a bad time".
        The old rule asserted that field data exists, so every small site failed a
        critical item for being small."""
        out = self.parse(self.lab_only())
        self.assertNotIn("field_cwv", out)
        self.assertEqual(verdict("SP-108", out), NO_DATA)

    def field_titled_items(self):
        """Every registry item that decides on `field_cwv`, derived rather than listed.

        Four today — SP-108, SP-111, SP-112, SP-113 — and the set is read from the
        registry so a fifth is swept the day somebody adds it. Two of the four are
        already pinned individually above; this is the invariant they are halves of.
        """
        import json
        with open(REGISTRY, encoding="utf-8") as stream:
            items = json.load(stream)["items"]
        found = [i["id"] for i in items
                 if "field_cwv" in json.dumps((i.get("check") or {}).get("assert") or {})]
        self.assertGreaterEqual(len(found), 3, "the field-data items moved; re-read INP-5")
        return found

    def test_no_field_titled_item_is_ever_decided_from_a_lab_number(self):
        """`openspec/specs/inputs/` INP-5. A synthetic run and a real-user sample answer
        different questions and a client acts differently on each; the distinction is
        invisible in the number itself.

        The structural reason this holds is worth naming, because it is what a future
        edit would break: `field_cwv` is written only inside `if field_data_available`,
        so an item asserting on it cannot be reached by a lab measurement. Dedent that
        assignment and every one of these decides from Lighthouse ratings instead.
        """
        lab = self.parse(self.lab_only())
        self.assertIs(lab["field_data_available"], False)
        self.assertNotIn("field_cwv", lab,
                         "a lab-only payload carries a field verdict")
        for item_id in self.field_titled_items():
            with self.subTest(item=item_id):
                self.assertEqual(
                    verdict(item_id, lab), NO_DATA,
                    f"{item_id} asks about field data and answered from a lab run")

    def test_the_same_items_do_decide_when_there_is_field_data(self):
        """Without this the sweep above would pass on a payload nothing can decide, and
        on an implementation that answered NO_DATA to everything."""
        real = self.parse(self.crux())
        self.assertIs(real["field_data_available"], True)
        for item_id in self.field_titled_items():
            with self.subTest(item=item_id):
                self.assertNotEqual(verdict(item_id, real), NO_DATA)

    def test_a_slow_lcp_in_the_field_fails_the_whole_group(self):
        """SP-108, SP-112 and SP-113 are one measurement as of 0.25.0, so they answer
        together. SP-113 used to read `metrics.LCP.rating` alone with a three-band warn
        in the middle; Google's own assessment has no middle — a URL passes only when all
        of LCP, INP and CLS are `good` — and the middle band came from grading one metric
        instead of three."""
        slow = self.parse(self.crux(lcp_category="SLOW"))
        self.assertEqual(slow["metrics"]["LCP"]["rating"], "poor")
        self.assertEqual(slow["field_cwv"]["verdict"], "fail")
        self.assertEqual(slow["field_cwv"]["failing"], ["LCP"])
        for item in ("SP-108", "SP-112", "SP-113"):
            self.assertEqual(verdict(item, slow), FAIL, item)

        middling = self.parse(self.crux(lcp_category="AVERAGE"))
        self.assertEqual(middling["metrics"]["LCP"]["rating"], "needs-improvement")
        self.assertEqual(middling["field_cwv"]["verdict"], "fail")
        self.assertEqual(verdict("SP-113", middling), FAIL)

    def test_desktop_field_data_is_asserted_by_its_own_item(self):
        """SP-111's whole point after 0.25.0: nothing in the registry read desktop field
        data before, because it read Lighthouse's blended desktop score instead."""
        with open(REGISTRY, encoding="utf-8") as f:
            registry = {i["id"]: i for i in json.load(f)["items"]}
        self.assertIn("desktop", registry["SP-111"]["check"]["args"])
        self.assertEqual(registry["SP-111"]["check"]["assert"]["path"],
                         "field_cwv.verdict")
        self.assertIsNone(registry["SP-111"].get("scores_with"),
                          "desktop field data is not a twin of the mobile item")

    def test_an_unknown_rating_is_undecided(self):
        """A band nobody enumerated must not become a verdict. `rating != "good"` made
        one: an unrecognised band graded as failing, which 0.25.0 would have promoted
        into a `critical` FAIL when SP-113 started reading this verdict. It is dropped
        from the grading and named in `unknown` instead."""
        out = self.parse(self.crux(lcp_category="GLACIAL"))
        self.assertEqual(out["metrics"]["LCP"]["rating"], "glacial")
        self.assertEqual(out["field_cwv"]["verdict"], "unknown")
        self.assertEqual(out["field_cwv"]["unknown"], ["LCP"])
        self.assertEqual(out["field_cwv"]["measured"], ["CLS", "INP"])
        for item in ("SP-108", "SP-112", "SP-113"):
            self.assertEqual(verdict(item, out), NO_DATA, item)

    def test_a_known_failure_is_reported_even_beside_an_unknown_band(self):
        """The asymmetry, and it is the point. One bad metric fails the assessment
        whatever the unrecognised one turns out to be, so the failure is safe to report —
        while a *pass* beside an unknown band is not, which is the case above."""
        out = self.parse(self.crux(lcp_category="GLACIAL", cls_category="SLOW"))
        self.assertEqual(out["field_cwv"]["verdict"], "fail")
        self.assertEqual(out["field_cwv"]["failing"], ["CLS"])
        self.assertEqual(out["field_cwv"]["unknown"], ["LCP"])
        self.assertEqual(verdict("SP-108", out), FAIL)


class DomainSafety(unittest.TestCase):
    """SE-114, SE-116 and TE-171 (critical) read `safe_browsing.*`. The user
    declined a Safe Browsing key, so on a real run these are NO_DATA — which is
    exactly why they need a test: nothing else here has ever exercised them."""

    def setUp(self):
        import domain_safety_check as ds
        self.ds = ds
        self.saved = ds.requests.post

    def tearDown(self):
        self.ds.requests.post = self.saved

    def serve(self, matches, status=200):
        class Resp:
            status_code = status

            def json(self):
                return {"matches": matches}
        self.ds.requests.post = lambda *a, **k: Resp()

    def test_no_key_omits_the_verdict_instead_of_reporting_clean(self):
        out = {"safe_browsing": self.ds.check_safe_browsing(
            "https://example.com/", "", 10)}
        self.assertIs(out["safe_browsing"]["checked"], False)
        self.assertNotIn("clean", out["safe_browsing"])
        for item_id in ("SE-114", "SE-116", "TE-171"):
            self.assertEqual(verdict(item_id, out), NO_DATA, item_id)

    def test_a_clean_domain_passes_all_three(self):
        self.serve([])
        out = {"safe_browsing": self.ds.check_safe_browsing(
            "https://example.com/", "key", 10)}
        self.assertIs(out["safe_browsing"]["clean"], True)
        self.assertEqual(out["safe_browsing"]["threats"], [])
        for item_id in ("SE-114", "SE-116", "TE-171"):
            self.assertEqual(verdict(item_id, out), PASS, item_id)

    def test_a_flagged_domain_fails_all_three(self):
        self.serve([{"threatType": "MALWARE", "platformType": "ANY_PLATFORM"}])
        out = {"safe_browsing": self.ds.check_safe_browsing(
            "https://example.com/", "key", 10)}
        self.assertIs(out["safe_browsing"]["clean"], False)
        for item_id in ("SE-114", "SE-116", "TE-171"):
            self.assertEqual(verdict(item_id, out), FAIL, item_id)

    def test_an_api_error_is_undecided_not_clean(self):
        self.serve([], status=503)
        out = {"safe_browsing": self.ds.check_safe_browsing(
            "https://example.com/", "key", 10)}
        self.assertIs(out["safe_browsing"]["checked"], False)
        self.assertEqual(verdict("SE-116", out), NO_DATA)


class DomainHistory(unittest.TestCase):
    """TE-179 reads its live whois-age rule, including the deliberate warn band."""

    def setUp(self):
        self.check = registry_rule("TE-179")

    def test_an_established_domain_passes(self):
        out = {"whois": {"checked": True, "age_days": 4000}}
        self.assertEqual(verdict("TE-179", out), PASS)
        self.assertIs(evaluate(self.check["assert"], out)[0], True)

    def test_a_young_domain_warns_and_names_both_bands(self):
        out = {"whois": {"checked": True, "age_days": 64}}
        assert_ok, assert_evidence = evaluate(self.check["assert"], out)
        warn_ok, warn_evidence = evaluate(self.check["warn"], out)
        self.assertEqual(verdict("TE-179", out), WARN)
        self.assertIs(assert_ok, False)
        self.assertIs(warn_ok, True)
        self.assertEqual(assert_evidence, "whois.age_days = 64 (want gte 90)")
        self.assertEqual(warn_evidence, "whois.age_days = 64 (want lt 90)")

    def test_ninety_days_is_inclusive_and_passes(self):
        out = {"whois": {"checked": True, "age_days": 90}}
        self.assertEqual(verdict("TE-179", out), PASS)
        self.assertIs(evaluate(self.check["assert"], out)[0], True)

    def test_an_unavailable_whois_binary_is_no_data(self):
        out = {"whois": {"checked": False,
                         "error": "whois binary not available"}}
        self.assertEqual(verdict("TE-179", out), NO_DATA)
        self.assertIsNone(evaluate(self.check["assert"], out)[0])
        self.assertIsNone(evaluate(self.check["warn"], out)[0])

    def test_fail_is_unreachable_because_the_warn_band_is_the_complement(self):
        self.assertEqual(self.check["assert"],
                         {"path": "whois.age_days", "gte": 90})
        self.assertEqual(self.check["warn"],
                         {"path": "whois.age_days", "lt": 90})
        for age in (-1, 0, 64, 89.5, 90, 90.5, 4000):
            out = {"whois": {"checked": True, "age_days": age}}
            assert_ok = evaluate(self.check["assert"], out)[0]
            warn_ok = evaluate(self.check["warn"], out)[0]
            self.assertEqual({assert_ok, warn_ok}, {False, True}, age)
            self.assertNotEqual(verdict("TE-179", out), FAIL, age)


class FaviconDisplayRule(unittest.TestCase):
    """MB-104 distinguishes a measured defect from a measurement that never happened."""

    def setUp(self):
        self.check = registry_rule("MB-104")

    def assert_rule(self, output, expected):
        observed, evidence = evaluate(self.check["assert"], output)
        self.assertIs(observed, expected)
        return evidence

    def test_no_icon_declared_is_a_measured_failure(self):
        evidence = self.assert_rule({"favicon": {"declared": False,
                                                  "displays_at_48px": False}}, False)
        self.assertEqual(evidence, "favicon.displays_at_48px = False")

    def test_a_declared_but_unreachable_icon_is_a_failure(self):
        output = {"favicon": {"declared": True, "url": "https://example.test/icon",
                              "displays_at_48px": False,
                              "reason": "Declared favicon is unreachable: HTTP 404"}}
        self.assert_rule(output, False)
        self.assertEqual(verdict("MB-104", output), FAIL)

    def test_a_64px_icon_passes(self):
        output = {"favicon": {"width": 64, "height": 64, "min_side_px": 64,
                              "displays_at_48px": True}}
        self.assert_rule(output, True)
        self.assertEqual(verdict("MB-104", output), PASS)

    def test_a_32px_icon_fails(self):
        output = {"favicon": {"width": 32, "height": 32, "min_side_px": 32,
                              "displays_at_48px": False}}
        self.assert_rule(output, False)
        self.assertEqual(verdict("MB-104", output), FAIL)

    def test_an_unrecognised_format_is_no_data_not_failure(self):
        output = {"favicon": {"declared": True, "format": None,
                              "reason": "format not recognised"}}
        evidence = self.assert_rule(output, None)
        self.assertEqual(evidence, "favicon.displays_at_48px missing")
        self.assertEqual(verdict("MB-104", output), NO_DATA)

    def test_an_unread_page_is_no_data(self):
        output = {"fetch_error": "connection refused",
                  "favicon": {"reason": "page could not be fetched"}}
        self.assert_rule(output, None)
        self.assertEqual(verdict("MB-104", output), NO_DATA)

    def test_a_resolvable_svg_passes_without_a_raster_size(self):
        output = {"favicon": {"format": "svg", "width": None, "height": None,
                              "displays_at_48px": True}}
        self.assert_rule(output, True)
        self.assertEqual(verdict("MB-104", output), PASS)


class ImageWeightAudit(unittest.TestCase):
    """MB-096 (`responsive_count`) and MB-097 (`modern_format_count`).

    Neither is critical, and both were wrong in the same direction, which is the
    interesting part: they failed sites for using the pattern the documentation
    recommends. The audit read `<img>` attributes only, and the recommended way to
    ship webp puts it in a `<source>` and leaves a png in the `<img>` as the
    fallback for browsers that cannot decode it — so the one thing guaranteed to be
    an old format was the only thing ever inspected.
    """

    def audit(self, body: str) -> dict:
        from image_weight_audit import audit as run
        path = os.path.join(tempfile.mkdtemp(), "page.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"<!doctype html><html><body>{body}</body></html>")
        return run(path)

    PICTURE = """<picture>
      <source type="image/avif" srcset="/i/logo.avif">
      <source type="image/webp" srcset="/i/logo@2x.webp 2x, /i/logo.webp 1x">
      <img src="/i/logo.png" alt="a mark" width="64" height="64">
    </picture>"""

    def test_a_picture_serving_webp_counts_as_a_modern_format(self):
        out = self.audit(self.PICTURE)
        self.assertEqual(out["modern_format_count"], 1,
                         "MB-097 fails a site doing exactly what it asks for")
        self.assertEqual(verdict("MB-097", out), PASS)

    def test_a_source_srcset_counts_as_responsive(self):
        out = self.audit(self.PICTURE)
        self.assertEqual(out["responsive_count"], 1)
        self.assertEqual(verdict("MB-096", out), PASS)

    def test_the_fallback_is_still_reported_as_a_png(self):
        """Both facts, kept apart. The browser gets webp and the `img` is a png,
        and a fix list that conflated them would tell somebody to change the one
        line that is deliberately old."""
        out = self.audit(self.PICTURE)
        self.assertEqual(out["images"][0]["format"], "png")
        self.assertEqual(out["modern_format_on_img_count"], 0)
        self.assertEqual(out["picture_count"], 1)
        self.assertEqual(out["images"][0]["picture_modern_formats"], ["avif", "webp"])

    def test_a_bare_old_format_image_still_fails_both(self):
        """The other direction, which is what stops this being a fix that
        can only ever say yes."""
        out = self.audit('<img src="/i/logo.png" alt="a mark">')
        self.assertEqual(out["modern_format_count"], 0)
        self.assertEqual(out["responsive_count"], 0)
        self.assertEqual(verdict("MB-097", out), FAIL)
        self.assertEqual(verdict("MB-096", out), FAIL)

    def test_an_image_free_page_does_not_fail_responsive_images(self):
        out = self.audit("<p>This page has no images.</p>")
        self.assertEqual(out["image_count"], 0)
        self.assertNotIn("responsive_count", out)
        self.assertEqual(verdict("MB-096", out), NO_DATA)

    def test_an_image_free_page_does_not_fail_modern_formats(self):
        out = self.audit("<p>This page has no images.</p>")
        self.assertEqual(out["image_count"], 0)
        self.assertNotIn("modern_format_count", out)
        self.assertEqual(verdict("MB-097", out), NO_DATA)

    def test_no_modern_source_means_the_raster_advice_still_stands(self):
        out = self.audit("""<picture>
          <source media="(max-width: 600px)" srcset="/i/small.png">
          <img src="/i/logo.png" alt="a mark">
        </picture>""")
        self.assertEqual(out["modern_format_count"], 0)
        self.assertEqual(out["responsive_count"], 1, "a source srcset is a srcset "
                                                     "whatever format it offers")
        self.assertIn("Consider AVIF/WebP for raster image",
                      [i["message"] for i in out["issues"]])

    def test_a_source_with_no_type_is_read_from_its_urls(self):
        """`type` is optional, and a CDN URL is often all there is to go on."""
        out = self.audit("""<picture>
          <source srcset="/i/logo.webp 1x, /i/logo@2x.webp 2x">
          <img src="/i/logo.jpg" alt="a mark">
        </picture>""")
        self.assertEqual(out["modern_format_count"], 1)

    def test_the_sources_are_found_under_either_html_parser(self):
        """The bug inside the bug, and the reason this fix nearly shipped broken.

        `seo_common` prefers `lxml`, and libxml2 predates `<picture>`: it does not
        know `<source>` is a void element, so it makes the `<img>` a *child* of the
        first `<source>`. `html.parser` gives the `img` the `<picture>` as its
        parent, as the spec does. The first version of this checked `img.parent`,
        passed nothing under the parser that actually runs, and would have left
        MB-096/MB-097 exactly as broken as before while looking fixed.

        Which parser gets used is itself decided by whether `lxml` happens to be in
        `sys.modules`, so this is not a hypothetical second branch — it is import
        order deciding how a page is read. Recorded in KNOWN-ISSUES.md.
        """
        from bs4 import BeautifulSoup
        from seo_common import picture_sources
        markup = self.PICTURE
        parents = {}
        for parser in ("lxml", "html.parser"):
            soup = BeautifulSoup(markup, parser)
            img = soup.find("img")
            parents[parser] = img.parent.name
            found = picture_sources(img, "https://example.com/")
            self.assertEqual([s["type"] for s in found],
                             ["image/avif", "image/webp"], parser)
        self.assertEqual(parents, {"lxml": "source", "html.parser": "picture"},
                         "the parsers have stopped disagreeing; if lxml has learned "
                         "about <picture>, this test is the place to find out")

    def test_a_video_source_is_not_an_image_source(self):
        """`<source>` means something else inside `<video>`, and the `img` next to
        one is not part of it."""
        out = self.audit("""<video controls>
          <source src="/v/clip.webm" type="video/webm">
        </video><img src="/i/logo.png" alt="a mark">""")
        self.assertEqual(out["images"][0]["picture_source_count"], 0)
        self.assertEqual(out["modern_format_count"], 0)


class EveryCriticalItemIsCovered(unittest.TestCase):
    """The list this file is measured against.

    Without it, "tests for the critical scripts" quietly means "for the ones
    somebody got round to" — and which ones those were would be invisible.
    """

    # Scripts tested anywhere in `tests/`, not only in this file — `tls_certificate.py`
    # needs a certificate to answer at all, so its cases live in `test_tls_certificate.py`
    # where the TLS harness is. A hand-kept list can claim coverage that does not exist,
    # which is the failure mode this class was written against, so the third test below
    # makes the suite prove each name.
    COVERED = {"parse_html.py", "indexability_matrix.py", "canonical_checker.py",
               "robots_path_tester.py", "security_headers.py", "pagespeed.py",
               "domain_safety_check.py", "tls_certificate.py"}

    def test_every_script_deciding_a_critical_item_has_a_test_class(self):
        with open(REGISTRY, encoding="utf-8") as f:
            items = json.load(f)["items"]
        deciders = {(i.get("check") or {}).get("script")
                    for i in items
                    if i["severity"] == "critical" and (i.get("check") or {}).get("script")}
        self.assertEqual(deciders - self.COVERED, set(),
                         "a script decides a critical item and nothing here tests it")

    def test_the_covered_list_holds_no_scripts_that_stopped_mattering(self):
        with open(REGISTRY, encoding="utf-8") as f:
            items = json.load(f)["items"]
        deciders = {(i.get("check") or {}).get("script")
                    for i in items if i["severity"] == "critical"}
        self.assertEqual(self.COVERED - deciders, set(),
                         "this file tests a script no critical item reads any more")

    def test_every_name_on_the_list_is_actually_exercised_somewhere(self):
        """The list is a claim, and a claim in a set literal costs one line to fake.

        Both tests above read `COVERED` and neither opens a test file, so a script
        added here and tested nowhere would turn this class green while removing the
        coverage it exists to measure. This is the only test that looks.
        """
        tests_dir = os.path.dirname(os.path.abspath(__file__))
        corpus = ""
        for name in sorted(os.listdir(tests_dir)):
            if name.startswith("test_") and name.endswith(".py"):
                with open(os.path.join(tests_dir, name), encoding="utf-8") as f:
                    corpus += f.read()
        unproven = sorted(s for s in self.COVERED
                          if s not in corpus and s[:-3] not in corpus)
        self.assertEqual(unproven, [],
                         "named as covered, but no test file mentions it: " + str(unproven))


if __name__ == "__main__":
    unittest.main()
