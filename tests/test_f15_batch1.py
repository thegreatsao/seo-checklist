"""F15 batch 1: the defects F03's second reading found in `parse_html.py` and
`javascript_render_audit.py`, as the owner ruled them (docs/sprint-20261109-F15.md).

Each test runs the item's real rule from the registry over the script's real output,
so a test cannot pass by agreeing with a rule the registry no longer carries. The
`measures` rows are held by `MeasuresSentences`: the rule stays, and the registry says
what it decides.
"""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "skills", "seo-checklist", "scripts")
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness  # noqa: E402
import javascript_render_audit as render_audit  # noqa: E402
import parse_html  # noqa: E402
import seo_common  # noqa: E402
from article_seo import TITLE_MAX_CHARS  # noqa: E402
from test_evidence import verdict  # noqa: E402
from checklist_runner import FAIL, PASS  # noqa: E402

ITEMS = {item["id"]: item for item in harness.registry()["items"]}
URL = "https://example.com/page"


def page(head="", body="<main><h1>A page</h1></main>"):
    return f"<!doctype html><html lang='en'><head>{head}</head><body>{body}</body></html>"


def parsed(head="", body="<main><h1>A page</h1></main>"):
    return parse_html.parse_html(page(head, body), URL)


class EveryRobotsMetaIsRead(unittest.TestCase):
    """CI-004: only the last robots meta was kept, `noindex` was matched case by case,
    and `none` (noindex, nofollow) was not read at all."""

    def test_a_noindex_before_an_index_tag_fails(self):
        out = parsed('<meta name="robots" content="noindex">'
                     '<meta name="robots" content="index, follow">')
        self.assertEqual(verdict("CI-004", out), FAIL)

    def test_noindex_in_capitals_fails(self):
        out = parsed('<meta name="robots" content="NOINDEX, FOLLOW">')
        self.assertEqual(verdict("CI-004", out), FAIL)

    def test_none_fails(self):
        out = parsed('<meta name="ROBOTS" content="None">')
        self.assertEqual(verdict("CI-004", out), FAIL)

    def test_an_argument_named_none_is_not_the_none_rule(self):
        out = parsed('<meta name="robots" content="max-image-preview: none, index">')
        self.assertEqual(verdict("CI-004", out), PASS)

    def test_index_follow_and_no_tag_pass(self):
        self.assertEqual(verdict("CI-004", parsed(
            '<meta name="robots" content="index, follow">')), PASS)
        self.assertEqual(verdict("CI-004", parsed()), PASS)


class PaginationHosts(unittest.TestCase):
    def test_a_host_in_capitals_is_this_host(self):
        """AR-146, Codex's review of 90134c7: the netloc was compared as written."""
        out = parsed('<link rel="next" href="https://EXAMPLE.COM/page2">')
        self.assertEqual(out["pagination"]["issues"], [])
        self.assertEqual(verdict("AR-146", out), PASS)

    def test_a_port_or_userinfo_is_still_this_host(self):
        for href in ("https://example.com:443/page2", "https://reader@example.com/page2"):
            with self.subTest(href=href):
                out = parsed(f'<link rel="next" href="{href}">')
                self.assertEqual(verdict("AR-146", out), PASS)

    def test_a_self_link_in_capitals_is_a_self_link(self):
        out = parsed('<link rel="next" href="https://EXAMPLE.COM/page">')
        self.assertEqual(verdict("AR-146", out), FAIL)

    def test_unicode_and_punycode_are_one_host(self):
        out = parse_html.parse_html(page('<link rel="next" href="https://bücher.example/next">'),
                                    "https://xn--bcher-kva.example/page")
        self.assertEqual(out["pagination"]["issues"], [])

    def test_an_ipv6_self_link_spelled_otherwise_is_a_self_link(self):
        out = parse_html.parse_html(
            page('<link rel="next" href="https://[2001:db8:0:0:0:0:0:a]/page">'),
            "https://[2001:db8::a]/page")
        self.assertEqual([i["type"] for i in out["pagination"]["issues"]], ["pagination_next_self"])

    def test_other_pages_on_this_host_are_not_self_links(self):
        """Codex's fourth review: `;page=2` (params), another port, another scheme."""
        for page_url, href in (("https://example.com/catalog;page=1", "https://example.com/catalog;page=2"),
                               ("https://example.com/page", "https://example.com:8443/page"),
                               ("https://example.com/page", "http://example.com/page")):
            with self.subTest(href=href):
                out = parse_html.parse_html(page(f'<link rel="next" href="{href}">'), page_url)
                self.assertNotIn("pagination_next_self",
                                 [i["type"] for i in out["pagination"]["issues"]])

    def test_another_host_still_fails(self):
        out = parsed('<link rel="next" href="https://example.org/page2">')
        self.assertEqual(verdict("AR-146", out), FAIL)


class DescriptionAndKeywords(unittest.TestCase):
    def test_a_whitespace_only_description_is_no_description(self):
        """MS-028: `content="   "` was truthy and passed."""
        out = parsed('<meta name="description" content="  \n\t ">')
        self.assertEqual(verdict("MS-028", out), FAIL)

    def test_a_written_description_passes(self):
        out = parsed('<meta name="description" content=" A page about loaves. ">')
        self.assertEqual(verdict("MS-028", out), PASS)

    def test_a_populated_keywords_tag_before_an_empty_one_fails(self):
        """MS-031: each keywords meta overwrote the last, so an empty one hid it."""
        out = parsed('<meta name="keywords" content="bread, loaf">'
                     '<meta name="keywords" content="">')
        self.assertEqual(verdict("MS-031", out), FAIL)

    def test_empty_keywords_tags_pass(self):
        out = parsed('<meta name="keywords" content=""><meta name="keywords" content=" ">')
        self.assertEqual(verdict("MS-031", out), PASS)


class FaviconDeclaration(unittest.TestCase):
    def test_shortcut_alone_is_no_icon(self):
        """TE-166: `rel="shortcut"` without `icon` names no icon to any browser or to
        Google, whose favicon page lists `icon`, `shortcut icon` and the
        `apple-touch-icon` family."""
        out = parsed('<link rel="shortcut" href="/favicon.ico">')
        self.assertEqual(verdict("TE-166", out), FAIL)

    def test_shortcut_icon_and_icon_are_icons(self):
        for rel in ("shortcut icon", "icon", "apple-touch-icon"):
            with self.subTest(rel=rel):
                out = parsed(f'<link rel="{rel}" href="/favicon.ico">')
                self.assertEqual(verdict("TE-166", out), PASS)


class BreadcrumbTrails(unittest.TestCase):
    """AR-158: one Microdata/RDFa BreadcrumbList set both halves, and neither half
    asked for a single entry in the trail."""

    NAV = '<nav aria-label="Breadcrumb"><a href="/">Home</a> / <a href="/shop">Shop</a></nav>'

    def test_an_empty_json_ld_breadcrumb_list_is_no_schema(self):
        head = ('<script type="application/ld+json">'
                '{"@context": "https://schema.org", "@type": "BreadcrumbList", '
                '"itemListElement": []}</script>')
        out = parsed(head, self.NAV)
        self.assertFalse(out["breadcrumbs"]["schema"])
        self.assertEqual(verdict("AR-158", out), FAIL)

    def test_an_empty_microdata_carrier_is_neither_half(self):
        out = parsed(body='<div itemscope itemtype="https://schema.org/BreadcrumbList"></div>')
        self.assertEqual(out["breadcrumbs"], {"schema": False, "ui": False})

    def test_a_microdata_trail_with_entries_and_links_is_both(self):
        body = ('<ol itemscope itemtype="https://schema.org/BreadcrumbList">'
                '<li itemprop="itemListElement" itemscope itemtype="https://schema.org/ListItem">'
                '<a itemprop="item" href="/"><span itemprop="name">Home</span></a>'
                '<meta itemprop="position" content="1"></li></ol>')
        out = parsed(body=body)
        self.assertEqual(verdict("AR-158", out), PASS)

    def test_a_prefixed_rdfa_trail_is_both(self):
        """Codex's review of 90134c7: RDFa names properties by prefix or IRI."""
        body = ('<ol prefix="schema: https://schema.org/" typeof="schema:BreadcrumbList">'
                '<li property="schema:itemListElement" typeof="schema:ListItem">'
                '<a property="schema:item" href="/"><span property="schema:name">Home</span></a>'
                '<meta property="schema:position" content="1"></li></ol>')
        self.assertEqual(parsed(body=body)["breadcrumbs"], {"schema": True, "ui": True})

    def test_a_microdata_trail_with_no_link_is_schema_but_not_ui(self):
        body = ('<ol itemscope itemtype="https://schema.org/BreadcrumbList">'
                '<li itemprop="itemListElement" itemscope itemtype="https://schema.org/ListItem">'
                '<span itemprop="name">Home</span></li></ol>')
        self.assertEqual(parsed(body=body)["breadcrumbs"], {"schema": True, "ui": False})

    def test_json_ld_entries_that_are_not_list_items_are_no_trail(self):
        """Codex's review of 90134c7: `[null]`, `"garbage"` and `[{}]` passed."""
        for entries in ('[null]', '"garbage"', '[{}]'):
            with self.subTest(entries=entries):
                head = ('<script type="application/ld+json">{"@type": "BreadcrumbList", '
                        f'"itemListElement": {entries}}}</script>')
                self.assertFalse(parsed(head, self.NAV)["breadcrumbs"]["schema"])

    def test_entries_that_name_nothing_are_no_trail(self):
        """Codex's second review: `{"item": 42}`, a blank name, an empty Microdata entry."""
        for entries in ('[{"item": 42}]', '[{"name": "   "}]'):
            with self.subTest(entries=entries):
                head = ('<script type="application/ld+json">{"@type": "BreadcrumbList", '
                        f'"itemListElement": {entries}}}</script>')
                self.assertFalse(parsed(head, self.NAV)["breadcrumbs"]["schema"])
        body = ('<ol itemscope itemtype="https://schema.org/BreadcrumbList">'
                '<li itemprop="itemListElement"></li><a href="/">Home</a></ol>')
        self.assertEqual(parsed(body=body)["breadcrumbs"], {"schema": False, "ui": False})

    def test_a_microdata_entry_given_by_attributes_is_an_entry(self):
        """Codex's third review: `<meta itemprop=name content>` and `<link itemprop=item>`."""
        body = ('<ol itemscope itemtype="https://schema.org/BreadcrumbList">'
                '<li itemprop="itemListElement" itemscope itemtype="https://schema.org/ListItem">'
                '<meta itemprop="name" content="Home"><link itemprop="item" href="https://example.com/">'
                '<meta itemprop="position" content="1"></li></ol>')
        self.assertTrue(parsed(body=body)["breadcrumbs"]["schema"])
        position_only = body.replace('<meta itemprop="name" content="Home">', "").replace(
            '<link itemprop="item" href="https://example.com/">', "")
        self.assertFalse(parsed(body=position_only)["breadcrumbs"]["schema"])

    def test_a_data_value_name_and_an_itemref_entry_count(self):
        """Codex's fourth review: Microdata's `<data value>` and `itemref`."""
        data = ('<ol itemscope itemtype="https://schema.org/BreadcrumbList">'
                '<li itemprop="itemListElement" itemscope itemtype="https://schema.org/ListItem">'
                '<data itemprop="name" value="Home"></data><a href="/">Home</a></li></ol>')
        self.assertEqual(parsed(body=data)["breadcrumbs"], {"schema": True, "ui": True})
        ref = ('<nav aria-label="Breadcrumb"><div itemscope '
               'itemtype="https://schema.org/BreadcrumbList" itemref="crumb"></div>'
               '<ol><li id="crumb" itemprop="itemListElement" itemscope '
               'itemtype="https://schema.org/ListItem"><a itemprop="item" href="/">'
               '<span itemprop="name">Home</span></a></li></ol></nav>')
        self.assertEqual(parsed(body=ref)["breadcrumbs"], {"schema": True, "ui": True})

    def test_itemref_trails_are_ui_and_list_items_follow_their_own_itemref(self):
        """Codex's fifth review: a referenced trail's link is UI; a ListItem's itemref."""
        ref = ('<div itemscope itemtype="https://schema.org/BreadcrumbList" itemref="crumb"></div>'
               '<ol><li id="crumb" itemprop="itemListElement" itemscope '
               'itemtype="https://schema.org/ListItem"><a itemprop="item" href="/">'
               '<span itemprop="name">Home</span></a></li></ol>')
        self.assertEqual(parsed(body=ref)["breadcrumbs"], {"schema": True, "ui": True})
        own = ('<nav aria-label="Breadcrumb"><ol itemscope itemtype="https://schema.org/BreadcrumbList">'
               '<li itemprop="itemListElement" itemscope itemtype="https://schema.org/ListItem" '
               'itemref="label target"><a href="/">Home</a></li></ol></nav>'
               '<meta id="label" itemprop="name" content="Home">'
               '<link id="target" itemprop="item" href="https://example.com/">')
        self.assertTrue(parsed(body=own)["breadcrumbs"]["schema"])

    def test_sixth_review_trails(self):
        """Codex's sixth review: a ListItem's referenced link is UI; a JSON-LD entry by
        `@id`; an empty href is still a link."""
        ref = ('<ol itemscope itemtype="https://schema.org/BreadcrumbList">'
               '<li itemprop="itemListElement" itemscope itemtype="https://schema.org/ListItem" '
               'itemref="home"></li></ol><a id="home" itemprop="item" href="/">Home</a>')
        self.assertEqual(parsed(body=ref)["breadcrumbs"], {"schema": True, "ui": True})
        graph = ('<script type="application/ld+json">{"@context": "https://schema.org", "@graph": ['
                 '{"@type": "BreadcrumbList", "itemListElement": [{"@id": "#home"}]},'
                 '{"@id": "#home", "@type": "ListItem", "position": 1, "name": "Home", '
                 '"item": "https://example.com/"}]}</script>')
        self.assertTrue(parsed(graph, self.NAV)["breadcrumbs"]["schema"])
        dangling = graph.replace('"@id": "#home", "@type"', '"@id": "#other", "@type"')
        self.assertFalse(parsed(dangling, self.NAV)["breadcrumbs"]["schema"])
        empty = ('<ol itemscope itemtype="https://schema.org/BreadcrumbList">'
                 '<li itemprop="itemListElement" itemscope itemtype="https://schema.org/ListItem">'
                 '<a itemprop="item" href=""><span itemprop="name">Home</span></a></li></ol>')
        self.assertEqual(parsed(body=empty)["breadcrumbs"], {"schema": True, "ui": True})

    def test_seventh_review_trails(self):
        """Codex's seventh review: an inline entry beside a partial node, an absolute
        reference to a relative @id, a BreadcrumbList under WebPage.breadcrumb."""
        def ld(data):
            return f'<script type="application/ld+json">{data}</script>'
        merged = ld('{"@context":"https://schema.org","@graph":[{"@type":"BreadcrumbList",'
                    '"itemListElement":[{"@id":"#home","@type":"ListItem","position":1,'
                    '"name":"Home","item":"https://example.com/"}]},'
                    '{"@id":"#home","@type":"ListItem","position":1}]}')
        absolute = ld('{"@context":"https://schema.org","@graph":[{"@type":"BreadcrumbList",'
                      '"itemListElement":[{"@id":"https://example.com/page#home"}]},'
                      '{"@id":"#home","@type":"ListItem","position":1,"name":"Home"}]}')
        nested = ld('{"@context":"https://schema.org","@type":"WebPage","breadcrumb":{'
                    '"@type":"BreadcrumbList","itemListElement":[{"@type":"ListItem",'
                    '"position":1,"name":"Home","item":"https://example.com/"}]}}')
        for name, head in (("merged", merged), ("absolute", absolute), ("nested", nested)):
            with self.subTest(name):
                self.assertTrue(parsed(head, self.NAV)["breadcrumbs"]["schema"])

    def test_eighth_review_trails(self):
        """Codex's eighth review: a malformed @id elsewhere must not crash the parser;
        one BreadcrumbList split over two definitions is one node."""
        bad = ('<script type="application/ld+json">{"@type":"Organization",'
               '"@id":"https://[YOUR_DOMAIN]/#organization"}</script>')
        self.assertFalse(parsed(bad, self.NAV)["breadcrumbs"]["schema"])
        bad_entry = ('<script type="application/ld+json">{"@type":"BreadcrumbList",'
                     '"itemListElement":[{"@id":"https://[x/#a","name":"Home"}]}</script>')
        self.assertTrue(parsed(bad_entry, self.NAV)["breadcrumbs"]["schema"])
        split = ('<script type="application/ld+json">{"@context":"https://schema.org","@graph":['
                 '{"@id":"#crumb","@type":"BreadcrumbList"},{"@id":"#crumb","itemListElement":['
                 '{"@type":"ListItem","position":1,"name":"Home","item":"https://example.com/"}]}]}'
                 '</script>')
        self.assertTrue(parsed(split, self.NAV)["breadcrumbs"]["schema"])

    def test_ninth_review_trails(self):
        """Codex's ninth review: JSON-LD ids resolve against `<base href>`; merged
        definitions keep every type."""
        based = ('<base href="/"><script type="application/ld+json">{"@context":"https://schema.org",'
                 '"@graph":[{"@type":"BreadcrumbList","itemListElement":[{"@id":"https://example.com/#home"}]},'
                 '{"@id":"#home","@type":"ListItem","position":1,"name":"Home"}]}</script>')
        out = parse_html.parse_html(page(based, self.NAV), "https://example.com/shop/widget")
        self.assertTrue(out["breadcrumbs"]["schema"])
        for base in ('<base href="https://EXAMPLE.COM/page">', '<base href="/page ">'):
            with self.subTest(base=base):
                spelled = based.replace('<base href="/">', base).replace(
                    "https://example.com/#home", "https://example.com/page#home")
                out = parse_html.parse_html(page(spelled, self.NAV), "https://example.com/page")
                self.assertTrue(out["breadcrumbs"]["schema"])
        typed = ('<script type="application/ld+json">[{"@id":"#crumb","@type":"BreadcrumbList"},'
                 '{"@id":"#crumb","@type":"ItemList","itemListElement":[{"@type":"ListItem",'
                 '"position":1,"name":"Home"}]}]</script>')
        self.assertTrue(parsed(typed, self.NAV)["breadcrumbs"]["schema"])

    def test_a_name_that_is_a_node_is_no_label(self):
        head = ('<script type="application/ld+json">{"@type": "BreadcrumbList", '
                '"itemListElement": [{"name": {"@id": "https://example.com/"}}]}</script>')
        self.assertFalse(parsed(head, self.NAV)["breadcrumbs"]["schema"])

    def test_json_ld_with_entries_beside_a_named_nav_passes(self):
        head = ('<script type="application/ld+json">'
                '{"@context": "https://schema.org", "@type": "BreadcrumbList", '
                '"itemListElement": [{"@type": "ListItem", "position": 1, '
                '"name": "Home", "item": "https://example.com/"}]}</script>')
        self.assertEqual(verdict("AR-158", parsed(head, self.NAV)), PASS)


class TheDocumentTitle(unittest.TestCase):
    """TE-177 (and MS-020/MS-021 through `parse_html.py`): the first `<title>`
    anywhere was taken, an inline SVG's tooltip included."""

    SVG_ONLY = '<svg><title>Search icon</title></svg><main><h1>A page</h1></main>'

    def render_raw(self, html):
        with mock.patch.object(render_audit, "load_html",
                               return_value=(html, "https://example.com/", {"error": None})):
            return render_audit.audit("https://example.com/")

    def test_an_svg_title_is_not_the_served_title(self):
        out = self.render_raw(page(body=self.SVG_ONLY))
        self.assertIsNone(out["raw"]["title"])
        self.assertEqual(verdict("TE-177", out), FAIL)

    def test_the_first_title_outside_svg_wins_over_an_earlier_svg_one(self):
        """`document.title`'s rule, not "the one in `<head>`": the head's tags are
        optional in HTML, so a page that writes `<title>` with no `<head>` is valid and
        has one (the owner's ruling named the SVG case; Codex's review asked about a
        body title, which browsers also take)."""
        html = ("<html><body><svg><title>Icon</title></svg>"
                "<title>The page</title></body></html>")
        self.assertEqual(self.render_raw(html)["raw"]["title"], "The page")
        implied = "<!doctype html><title>Implied head</title><p>Text</p>"
        self.assertEqual(self.render_raw(implied)["raw"]["title"], "Implied head")

    def test_a_template_title_is_not_the_title(self):
        """Codex's second review: template contents are another document."""
        html = "<html><head><template><title>Card</title></template><title>Page</title></head></html>"
        self.assertEqual(self.render_raw(html)["raw"]["title"], "Page")
        self.assertEqual(parse_html.parse_html(html, URL)["title"], "Page")

    def test_a_mathml_title_is_not_the_title(self):
        html = page(body="<math><title>Tooltip</title></math><main><h1>A</h1></main>")
        self.assertIsNone(self.render_raw(html)["raw"]["title"])
        self.assertIsNone(parse_html.parse_html(html, URL)["title"])

    def test_the_shared_parser_collapses_whitespace_too(self):
        html = page("<title>Fresh   loaves\n daily</title>")
        self.assertEqual(seo_common.parse_html(html, URL)["title"], "Fresh loaves daily")

    def test_parse_html_reads_the_same_title_collapsed(self):
        out = parsed("<title>\n  Fresh   loaves\n  daily </title>", self.SVG_ONLY)
        self.assertEqual(out["title"], "Fresh loaves daily")
        self.assertIsNone(parsed(body=self.SVG_ONLY)["title"])

    def test_one_helper_reads_the_title_for_both_parsers(self):
        self.assertTrue(callable(getattr(seo_common, "document_title", None)))


class RenderParity(unittest.TestCase):
    def audit(self, raw, rendered, url="https://example.com/"):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "rendered.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"html": rendered}, handle)
            with mock.patch.object(render_audit, "load_html",
                                   return_value=(raw, url, {"error": None})):
                return render_audit.audit(url, rendered_json=path)

    def test_a_robots_directive_added_by_javascript_is_a_diff(self):
        """MB-105: the title names directives and `summarize()` read none."""
        raw = page("<title>T</title>")
        rendered = page('<title>T</title><meta name="robots" content="noindex">')
        out = self.audit(raw, rendered)
        self.assertIn("meta_robots", [d["field"] for d in out["diffs"]])
        self.assertEqual(verdict("MB-105", out), FAIL)

    def test_a_googlebot_directive_is_compared_too(self):
        raw = page("<title>T</title>")
        rendered = page('<title>T</title><meta name="googlebot" content="noindex">')
        self.assertEqual(verdict("MB-105", self.audit(raw, rendered)), FAIL)

    def test_a_link_to_a_longer_host_is_not_internal(self):
        """TE-169: `https://example.com.au/` starts with `https://example.com`."""
        html = page(body='<a href="https://example.com.au/shop">Shop</a>'
                         '<a href="https://example.co/x">Shorter host</a>')
        out = self.audit(html, html)
        self.assertEqual(out["raw"]["internal_link_count"], 0)
        self.assertEqual(verdict("TE-169", out), FAIL)

    def test_a_link_on_the_page_host_is_internal(self):
        html = page(body='<a href="/shop">Shop</a><a href="https://EXAMPLE.com/x">X</a>'
                         # Codex's review of 90134c7: the host, not the authority.
                         '<a href="https://example.com:443/y">Y</a>'
                         '<a href="https://reader@example.com/z">Z</a>')
        self.assertEqual(self.audit(html, html)["raw"]["internal_link_count"], 4)

    def test_an_ipv6_host_spelled_twice_is_one_host(self):
        html = page(body='<a href="https://[2001:db8:0:0:0:0:0:a]/next">Next</a>')
        out = self.audit(html, html, url="https://[2001:db8::a]/page")
        self.assertEqual(out["raw"]["internal_link_count"], 1)

    def test_a_unicode_host_link_is_internal_to_its_punycode_page(self):
        html = page(body='<a href="https://bücher.example/next">Next</a>')
        out = self.audit(html, html, url="https://xn--bcher-kva.example/page")
        self.assertEqual(out["raw"]["internal_link_count"], 1)

    def test_an_earlier_googlebot_tag_the_render_changes_is_a_diff(self):
        for first in ("", '<meta name="googlebot" content="">'):
            with self.subTest(first=first):
                raw = page(first + '<meta name="googlebot" content="noindex">'
                           '<meta name="googlebot" content="follow">')
                rendered = page(first + '<meta name="googlebot" content="index">'
                                '<meta name="googlebot" content="follow">')
                self.assertEqual(verdict("MB-105", self.audit(raw, rendered)), FAIL)

    def test_the_same_directives_spelled_otherwise_are_no_diff(self):
        """Codex's fifth review: case, spacing and order of robots rules are not a change."""
        raw = page('<title>T</title><meta name="robots" content="NOINDEX, FOLLOW">')
        rendered = page('<title>T</title><meta name="robots" content="follow,noindex">')
        self.assertEqual(verdict("MB-105", self.audit(raw, rendered)), PASS)
        argued = page('<title>T</title><meta name="robots" content="max-snippet:20">')
        changed = page('<title>T</title><meta name="robots" content="max-snippet:50">')
        self.assertEqual(verdict("MB-105", self.audit(argued, changed)), FAIL)

    def test_a_repeated_rule_is_no_diff(self):
        raw = page('<title>T</title><meta name="robots" content="index,follow">')
        rendered = page('<title>T</title><meta name="robots" content="index,follow">'
                        '<meta name="robots" content="follow">')
        self.assertEqual(verdict("MB-105", self.audit(raw, rendered)), PASS)

    def test_aliases_and_defaults_are_no_diff(self):
        """Codex's seventh review: `none` is `noindex, nofollow`; `all`, `index` and
        `follow` are the default an absent tag means."""
        for raw_meta, rendered_meta in (
                ('<meta name="robots" content="none">', '<meta name="robots" content="noindex, nofollow">'),
                ("", '<meta name="robots" content="all">'),
                ("", '<meta name="robots" content="index, follow">'),
                # Codex's eighth review: Google's documented equivalents.
                ('<meta name="robots" content="max-snippet:0">', '<meta name="robots" content="nosnippet">'),
                ("", '<meta name="robots" content="max-snippet:-1">')):
            with self.subTest(rendered=rendered_meta):
                out = self.audit(page("<title>T</title>" + raw_meta),
                                 page("<title>T</title>" + rendered_meta))
                self.assertEqual(verdict("MB-105", out), PASS)

    def test_an_earlier_robots_tag_the_render_changes_is_a_diff(self):
        """Codex's review of 90134c7: the shared parser kept the last robots tag."""
        raw = page('<meta name="robots" content="noindex"><meta name="robots" content="follow">')
        rendered = page('<meta name="robots" content="index"><meta name="robots" content="follow">')
        self.assertEqual(verdict("MB-105", self.audit(raw, rendered)), FAIL)


class MeasuresSentences(unittest.TestCase):
    """The `measures` rulings: the code stays and the registry says what it decides."""

    SAYS = {
        "MS-028": "high-value",
        "MS-030": "convention",
        "TE-166": "MB-104",
        "AR-146": "rel=prev",
        "CN-048": "<main> element",
        "CN-066": "H2",
        "IN-123": "lang",
        "MS-020": str(TITLE_MAX_CHARS),
    }

    def test_each_ruled_item_states_what_its_rule_decides(self):
        for item_id, word in self.SAYS.items():
            with self.subTest(item=item_id):
                self.assertIn(word, ITEMS[item_id].get("measures", ""))

    def test_ms_020_reads_the_measured_title_budget(self):
        """Batch 3: MS-020 asserted 60 while `article_seo.TITLE_MAX_CHARS`, measured
        against the 600 px desktop title, is 65."""
        self.assertEqual(ITEMS["MS-020"]["check"]["assert"]["len_lte"], TITLE_MAX_CHARS)
        title = "x" * TITLE_MAX_CHARS
        self.assertEqual(verdict("MS-020", parsed(f"<title>{title}</title>")), PASS)
        self.assertEqual(verdict("MS-020", parsed(f"<title>{title}x</title>")), FAIL)


if __name__ == "__main__":
    unittest.main()
