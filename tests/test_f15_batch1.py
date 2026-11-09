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

    def test_the_head_title_wins_over_an_earlier_svg_one(self):
        html = ("<html><body><svg><title>Icon</title></svg>"
                "<title>The page</title></body></html>")
        self.assertEqual(self.render_raw(html)["raw"]["title"], "The page")

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
                         '<a href="https://example.com:8443/x">Other port</a>')
        out = self.audit(html, html)
        self.assertEqual(out["raw"]["internal_link_count"], 0)
        self.assertEqual(verdict("TE-169", out), FAIL)

    def test_a_link_on_the_page_host_is_internal(self):
        html = page(body='<a href="/shop">Shop</a><a href="https://EXAMPLE.com/x">X</a>')
        self.assertEqual(self.audit(html, html)["raw"]["internal_link_count"], 2)


class MeasuresSentences(unittest.TestCase):
    """The `measures` rulings: the code stays and the registry says what it decides."""

    SAYS = {
        "MS-028": "high-value",
        "MS-030": "convention",
        "TE-166": "MB-104",
        "AR-146": "rel=prev",
        "CN-048": "main",
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
