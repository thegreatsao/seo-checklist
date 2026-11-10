"""F15 batch 5: structured data and content — `schema_required_props.py`,
`rich_results_guard.py`, `video_schema_checker.py`, `local_seo_checker.py`,
`answer_block_scanner.py`, `citation_readiness.py`, `eeat_signal_checker.py`,
`freshness_checker.py`, `entity_checker.py`, `article_seo.py`, `social_meta.py`,
`collection_page_checker.py` — as the owner ruled them (docs/sprint-20261109-F15.md),
and the owner's ruling 2 on batch 4's questions (IN-122: a set naming only the page
itself is N/A).

Each verdict is the item's real rule from the registry, `applies_when` included, over
the script's real output, from a page served on loopback or a crawl of one.
"""
import contextlib
import io
import json
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "skills", "seo-checklist", "scripts")
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness  # noqa: E402
import answer_block_scanner  # noqa: E402
import article_seo  # noqa: E402
import citation_readiness  # noqa: E402
import collection_page_checker  # noqa: E402
import eeat_signal_checker  # noqa: E402
import entity_checker  # noqa: E402
import freshness_checker  # noqa: E402
import hreflang_checker  # noqa: E402
import local_seo_checker  # noqa: E402
import rich_results_guard  # noqa: E402
import schema_required_props  # noqa: E402
import site_crawl  # noqa: E402
import social_meta  # noqa: E402
import video_schema_checker  # noqa: E402
from checklist_runner import FAIL, NA, NO_DATA, PASS, WARN  # noqa: E402
from test_f15_batch3 import crawled, written  # noqa: E402
from test_f15_batch4 import ITEMS, full_verdict, hreflang_page, site_with  # noqa: E402


def run_item(module, item_id: str, routes: dict, path: str = "/", keyword: str = "") -> dict:
    """The item's script run in-process with the registry's own arguments, over a
    loopback site."""
    with site_with(routes) as site:
        url = site.origin + path
        args = [a.replace("{url}", url).replace("{keyword}", keyword)
                for a in ITEMS[item_id]["check"]["args"]]
        saved = sys.argv
        sys.argv = [module.__file__] + args + ["--json"]
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                module.main()
        finally:
            sys.argv = saved
    return json.loads(out.getvalue())


def html(body: str = "", head: str = "", title: str = "A page") -> str:
    return (f"<!doctype html><html lang='en'><head><title>{title}</title>{head}</head>"
            f"<body>{body}</body></html>")


def jsonld(*nodes) -> str:
    return "".join(f'<script type="application/ld+json">{json.dumps(node)}</script>'
                   for node in nodes)


def page_verdict(module, item_id: str, page: str, path: str = "/", keyword: str = "") -> str:
    return full_verdict(item_id, run_item(module, item_id, {path: page}, path, keyword))


# ---------------------------------------------------------------------------
# schema_required_props.py — MS-032, GO-143
# ---------------------------------------------------------------------------

class StructuredData(unittest.TestCase):
    def test_a_page_whose_only_json_ld_does_not_parse_fails_ms_032(self):
        page = html(head='<script type="application/ld+json">{"@type": "Product",</script>')
        self.assertEqual(page_verdict(schema_required_props, "MS-032", page), FAIL)

    def test_a_complete_node_passes_ms_032(self):
        page = html(head=jsonld({"@context": "https://schema.org", "@type": "WebSite",
                                 "name": "Bakery", "url": "https://bakery.test/",
                                 "alternateName": "The Bakery"}))
        self.assertEqual(page_verdict(schema_required_props, "MS-032", page), PASS)

    def test_an_empty_json_ld_block_is_no_block(self):
        """An empty `<script type="application/ld+json">` declares nothing; it is not a
        block that fails to parse."""
        page = html(head='<script type="application/ld+json">  </script>')
        self.assertEqual(page_verdict(schema_required_props, "MS-032", page), NA)
        page = html(head='<script type="application/ld+json"></script>' + jsonld(
            {"@type": "WebSite", "name": "B", "url": "https://b.test/", "alternateName": "Bee"}))
        self.assertEqual(page_verdict(schema_required_props, "MS-032", page), PASS)

    def test_no_json_ld_at_all_is_not_applicable(self):
        self.assertEqual(page_verdict(schema_required_props, "MS-032", html("<p>Hi</p>")), NA)


class WebSiteNode(unittest.TestCase):
    SITE = {"@context": "https://schema.org", "@type": "WebSite", "name": "Bakery",
            "url": "https://bakery.test/", "alternateName": "The Bakery"}

    def go_143(self, node: dict) -> str:
        return page_verdict(schema_required_props, "GO-143", html(head=jsonld(node)))

    def test_a_complete_website_node_passes(self):
        self.assertEqual(self.go_143(self.SITE), PASS)

    def test_a_co_types_recommended_properties_are_not_the_website_nodes(self):
        """`["WebSite", "Organization"]` without a logo: Organization's, not GO-143's."""
        self.assertEqual(self.go_143({**self.SITE, "@type": ["WebSite", "Organization"]}), PASS)

    def test_alternate_name_is_one_of_the_website_nodes_properties(self):
        node = {k: v for k, v in self.SITE.items() if k != "alternateName"}
        self.assertEqual(self.go_143(node), FAIL)

    def test_placeholders_are_matched_by_host(self):
        for url, expected in (("https://www.myexample.com/", PASS),
                              ("https://example.com.au/", PASS),
                              ("https://example.com/", FAIL),
                              ("https://www.example.org/home", FAIL)):
            with self.subTest(url=url):
                self.assertEqual(self.go_143({**self.SITE, "url": url}), expected)

    def test_a_placeholder_in_a_co_types_property_is_not_the_website_nodes(self):
        node = {**self.SITE, "@type": ["WebSite", "Organization"],
                "logo": "https://example.com/logo.png"}
        self.assertEqual(self.go_143(node), PASS)


# ---------------------------------------------------------------------------
# rich_results_guard.py — TE-172
# ---------------------------------------------------------------------------

class RichResultValues(unittest.TestCase):
    def te_172(self, node: dict) -> str:
        return page_verdict(rich_results_guard, "TE-172", html(head=jsonld(node)))

    def test_an_article_with_no_headline_fails(self):
        for kind in ("Article", "NewsArticle", "BlogPosting"):
            with self.subTest(kind=kind):
                self.assertEqual(self.te_172({"@type": kind, "author": "Jane"}), FAIL)
                self.assertEqual(self.te_172({"@type": kind, "headline": "  "}), FAIL)

    def test_an_article_with_a_headline_passes(self):
        self.assertEqual(self.te_172({"@type": "Article", "headline": "Sourdough"}), PASS)

    def test_a_text_property_needs_text(self):
        for name in ([" "], 42, {"@type": "Thing"}):
            with self.subTest(name=name):
                self.assertEqual(self.te_172({"@type": "Product", "name": name,
                                              "offers": {"price": "3"}}), FAIL)

    def test_an_upload_date_needs_a_date(self):
        video = {"@type": "VideoObject", "name": "Bake", "thumbnailUrl": "https://a.test/t.jpg"}
        self.assertEqual(self.te_172({**video, "uploadDate": "yesterday"}), FAIL)
        self.assertEqual(self.te_172({**video, "uploadDate": "2024-03-01T10:00:00+02:00"}), PASS)

    def test_a_thumbnail_needs_a_url(self):
        video = {"@type": "VideoObject", "name": "Bake", "uploadDate": "2024-03-01"}
        self.assertEqual(self.te_172({**video, "thumbnailUrl": "a picture of bread"}), FAIL)
        self.assertEqual(self.te_172({**video, "thumbnailUrl": {
            "@type": "ImageObject", "url": "https://a.test/t.jpg"}}), PASS)


# ---------------------------------------------------------------------------
# video_schema_checker.py — MD-190, MB-102
# ---------------------------------------------------------------------------

VIDEO = {"@context": "https://schema.org", "@type": "VideoObject", "name": "Bake",
         "description": "Shaping a loaf", "thumbnailUrl": "https://a.test/t.jpg",
         "uploadDate": "2024-03-01", "contentUrl": "https://a.test/v.mp4",
         "publisher": {"@type": "Organization", "name": "Crumb"}}


class VideoSeo(unittest.TestCase):
    def test_an_embedded_video_with_no_video_object_fails_md_190(self):
        for player in ('<iframe src="https://www.youtube.com/embed/abc"></iframe>',
                       '<iframe src="https://player.vimeo.com/video/1"></iframe>',
                       '<video controls src="/v.mp4"></video>',
                       '<video controls><source src="/v.mp4"></video>'):
            with self.subTest(player=player):
                self.assertEqual(page_verdict(video_schema_checker, "MD-190", html(player)), FAIL)

    def test_a_background_video_or_no_video_is_not_applicable(self):
        for body in ('<video autoplay muted loop playsinline src="/hero.mp4"></video>',
                     "<p>No video here.</p>"):
            with self.subTest(body=body):
                self.assertEqual(page_verdict(video_schema_checker, "MD-190", html(body)), NA)

    def test_a_complete_video_object_passes(self):
        page = html('<video controls src="/v.mp4"></video>', head=jsonld(VIDEO))
        self.assertEqual(page_verdict(video_schema_checker, "MD-190", page), PASS)

    def test_missing_recommended_properties_warn(self):
        """Google lists `description`, `contentUrl` and `embedUrl` as recommended."""
        for drop in ("description", "contentUrl"):
            node = {k: v for k, v in VIDEO.items() if k != drop}
            with self.subTest(drop=drop):
                page = html(head=jsonld(node))
                self.assertEqual(page_verdict(video_schema_checker, "MD-190", page), WARN)
                self.assertEqual(page_verdict(video_schema_checker, "MB-102", page), WARN)

    def test_missing_required_properties_fail(self):
        node = {k: v for k, v in VIDEO.items() if k != "thumbnailUrl"}
        self.assertEqual(page_verdict(video_schema_checker, "MD-190", html(head=jsonld(node))), FAIL)
        self.assertEqual(page_verdict(video_schema_checker, "MB-102", html(head=jsonld(node))), FAIL)

    def test_a_player_page_that_is_no_video_is_not_one(self):
        """A YouTube subscribe button or a channel page is a frame from a player host,
        not a video the page shows."""
        for frame in ('<iframe src="https://www.youtube.com/subscribe_widget?c=x"></iframe>',
                      '<iframe src="https://www.youtube.com/channel/x"></iframe>'):
            with self.subTest(frame=frame):
                self.assertEqual(page_verdict(video_schema_checker, "MD-190", html(frame)), NA)

    def test_mb_102_stays_on_video_object_nodes(self):
        page = html('<iframe src="https://www.youtube.com/embed/abc"></iframe>')
        self.assertEqual(page_verdict(video_schema_checker, "MB-102", page), NA)


# ---------------------------------------------------------------------------
# local_seo_checker.py — LO-198, LO-200
# ---------------------------------------------------------------------------

def lo_198(page: str) -> str:
    inv, url = crawled({"/": page})
    with harness.allow_loopback():
        out = local_seo_checker.check_local_business_inventory(url, written(inv))
    return full_verdict("LO-198", out)


class LocalBusinessMarkup(unittest.TestCase):
    def test_microdata_and_rdfa_local_businesses_count(self):
        for body in ('<div itemscope itemtype="https://schema.org/Restaurant">'
                     '<span itemprop="name">Crumb</span></div>',
                     '<div itemscope itemtype="http://schema.org/Bakery Store">Crumb</div>',
                     '<div vocab="https://schema.org/" typeof="Dentist">'
                     '<span property="name">Smile</span></div>',
                     '<div typeof="schema:Plumber">Pipes</div>'):
            with self.subTest(body=body):
                self.assertEqual(lo_198(html(body)), PASS)

    def test_an_iri_type_in_json_ld_counts(self):
        page = html(head=jsonld({"@context": "https://schema.org",
                                 "@type": "https://schema.org/Bakery", "name": "Crumb"}))
        self.assertEqual(lo_198(page), PASS)

    def test_another_type_does_not_count(self):
        page = html('<div itemscope itemtype="https://schema.org/Product">Bread</div>')
        self.assertEqual(lo_198(page), FAIL)

    def test_the_inventory_says_its_version(self):
        self.assertEqual(site_crawl.INVENTORY_VERSION, 6)


ADDRESS = {"@type": "PostalAddress", "streetAddress": "1 Mill Lane",
           "addressLocality": "Limassol"}
SHOP = {"@context": "https://schema.org", "@type": "Bakery", "name": "Crumb",
        "telephone": "+357 25 000000", "address": ADDRESS}


class CompleteNap(unittest.TestCase):
    def lo_200(self, node: dict) -> str:
        return page_verdict(local_seo_checker, "LO-200", html(head=jsonld(node)))

    def test_a_complete_nap_passes(self):
        self.assertEqual(self.lo_200(SHOP), PASS)

    def test_whitespace_is_no_value(self):
        for prop in ("name", "telephone"):
            with self.subTest(prop=prop):
                self.assertEqual(self.lo_200({**SHOP, prop: "  "}), FAIL)

    def test_the_address_needs_a_street_and_a_locality(self):
        for address in ({"@type": "PostalAddress"},
                        {**ADDRESS, "streetAddress": " "},
                        {k: v for k, v in ADDRESS.items() if k != "addressLocality"},
                        "1 Mill Lane, Limassol"):
            with self.subTest(address=address):
                self.assertEqual(self.lo_200({**SHOP, "address": address}), FAIL)

    def test_an_address_named_by_id_is_read_where_it_is_defined(self):
        """A graph names the PostalAddress once and points at it (`@id`)."""
        graph = {"@context": "https://schema.org", "@graph": [
            {**SHOP, "address": {"@id": "#addr"}},
            {**ADDRESS, "@id": "#addr"}]}
        self.assertEqual(self.lo_200(graph), PASS)

    def test_a_telephone_list_with_a_number_is_a_telephone(self):
        self.assertEqual(self.lo_200({**SHOP, "telephone": ["+357 25 000000"]}), PASS)

    def test_one_complete_address_in_a_list_is_enough(self):
        self.assertEqual(self.lo_200({**SHOP, "address": [{"@type": "PostalAddress"}, ADDRESS]}),
                         PASS)


# ---------------------------------------------------------------------------
# answer_block_scanner.py — GO-144, GEO-004
# ---------------------------------------------------------------------------

ANSWER = ("Sourdough is a bread leavened by a culture of wild yeast and lactic acid bacteria "
          "kept alive by regular feeding with flour and water, which gives it a sour taste.")
TABLE = "<table><tr><th>Flour</th><th>Water</th></tr><tr><td>500 g</td><td>350 g</td></tr></table>"
MENU = "<nav><ul><li><a href='/a'>A</a></li><li><a href='/b'>B</a></li><li><a href='/c'>C</a></li></ul></nav>"


class AnswerBlocks(unittest.TestCase):
    def both(self, body: str) -> tuple:
        return tuple(page_verdict(answer_block_scanner, item, html(body))
                     for item in ("GO-144", "GEO-004"))

    def test_tables_alone_do_not_pass(self):
        self.assertEqual(self.both(TABLE * 3), (FAIL, FAIL))

    def test_navigation_menus_do_not_pass(self):
        self.assertEqual(self.both(MENU * 4), (FAIL, FAIL))

    def test_navigation_menus_are_not_lists(self):
        out = run_item(answer_block_scanner, "GEO-004", {"/": html(MENU * 4)})
        self.assertEqual(out["lists"], [])

    def test_one_direct_answer_is_enough(self):
        self.assertEqual(self.both(f"<h2>What is sourdough?</h2><p>{ANSWER}</p>"), (PASS, PASS))

    def test_one_definition_is_enough(self):
        self.assertEqual(self.both(f"<p>{ANSWER}</p>"), (PASS, PASS))


# ---------------------------------------------------------------------------
# citation_readiness.py — GO-145, GEO-005
# ---------------------------------------------------------------------------

class CitationSources(unittest.TestCase):
    BYLINE = "<p class='byline'>By Jane Doe</p>"
    HEAD = '<link rel="canonical" href="/">'

    def both(self, body: str) -> tuple:
        page = html(body, head=self.HEAD)
        return tuple(page_verdict(citation_readiness, item, page) for item in ("GO-145", "GEO-005"))

    def test_author_and_canonical_without_a_source_do_not_pass(self):
        self.assertEqual(self.both(self.BYLINE + "<p>Bread is good.</p>"), (FAIL, FAIL))

    def test_a_cited_claim_with_an_author_passes(self):
        body = (self.BYLINE + "<p>A 2023 survey found that 40% of bakers use rye.</p>"
                "<cite>Bakers' Survey 2023</cite>")
        self.assertEqual(self.both(body), (PASS, PASS))


# ---------------------------------------------------------------------------
# eeat_signal_checker.py — CN-057, CN-068
# ---------------------------------------------------------------------------

POLICY = ("<a href='/editorial-policy'>Editorial policy</a><a href='/about'>About us</a>"
          "<a href='https://a.test/1'>x</a><a href='https://b.test/2'>y</a>"
          "<a href='https://c.test/3'>z</a>")


class VisibleAuthorship(unittest.TestCase):
    def cn_057(self, body: str, head: str = "") -> str:
        return page_verdict(eeat_signal_checker, "CN-057", html(body, head=head))

    META = ('<meta name="author" content="Jane Doe">'
            '<meta property="og:site_name" content="Crumb Bakery">')

    def test_meta_tags_alone_do_not_show_anything(self):
        self.assertEqual(self.cn_057("<p>Bread.</p>", head=self.META), FAIL)

    def test_a_visible_byline_and_publisher_pass(self):
        body = ("<p class='byline'>By Jane Doe</p><p>Bread.</p>"
                "<footer>&copy; 2026 Crumb Bakery</footer>")
        self.assertEqual(self.cn_057(body, head=self.META), PASS)

    def test_a_declared_name_shown_in_the_text_passes(self):
        head = jsonld({"@type": "Article", "headline": "Bread",
                       "author": {"@type": "Person", "name": "Jane Doe"},
                       "publisher": {"@type": "Organization", "name": "Crumb Bakery"}})
        body = "<p>Written by Jane Doe for Crumb Bakery.</p>"
        self.assertEqual(self.cn_057(body, head=head), PASS)

    def test_a_hidden_byline_is_not_shown(self):
        body = ("<p class='byline' hidden>By Jane Doe</p>"
                "<footer>&copy; 2026 Crumb Bakery</footer>")
        self.assertEqual(self.cn_057(body, head=self.META), FAIL)


class AuthorRequired(unittest.TestCase):
    def test_no_author_does_not_pass_cn_068(self):
        page = html("<p>Bread.</p>" + POLICY)
        self.assertEqual(page_verdict(eeat_signal_checker, "CN-068", page), FAIL)

    def test_an_author_with_the_same_signals_passes(self):
        page = html("<p class='byline'>By Jane Doe</p><p>Bread.</p>" + POLICY)
        self.assertEqual(page_verdict(eeat_signal_checker, "CN-068", page), PASS)


# ---------------------------------------------------------------------------
# freshness_checker.py — CN-056
# ---------------------------------------------------------------------------

class VisibleDates(unittest.TestCase):
    META = ('<meta property="article:published_time" content="2024-01-03">'
            '<meta property="article:modified_time" content="2025-02-01">')

    def cn_056(self, body: str, head: str = "") -> str:
        return page_verdict(freshness_checker, "CN-056", html(body, head=head))

    def test_metadata_alone_shows_nothing(self):
        self.assertEqual(self.cn_056("<p>Bread.</p>", head=self.META), FAIL)

    def test_two_visible_times_pass(self):
        body = ('<p>Published <time datetime="2024-01-03">3 January 2024</time>, '
                'updated <time datetime="2025-02-01">1 February 2025</time>.</p>')
        self.assertEqual(self.cn_056(body), PASS)

    def test_two_visible_dates_in_the_text_pass(self):
        self.assertEqual(self.cn_056("<p>Published 2024-01-03. Updated Feb 1, 2025.</p>"), PASS)

    def test_one_visible_date_warns(self):
        self.assertEqual(self.cn_056('<p><time datetime="2024-01-03">Jan 3, 2024</time></p>',
                                     head=self.META), WARN)

    def test_an_empty_or_hidden_time_is_not_shown(self):
        for body in ('<time datetime="2024-01-03"></time><time datetime="2025-02-01"></time>',
                     '<div hidden><time datetime="2024-01-03">Jan 3, 2024</time>'
                     '<time datetime="2025-02-01">Feb 1, 2025</time></div>'):
            with self.subTest(body=body):
                self.assertEqual(self.cn_056(body, head=self.META), FAIL)


# ---------------------------------------------------------------------------
# entity_checker.py — GEO-006
# ---------------------------------------------------------------------------

ORG = {"@context": "https://schema.org", "@type": "Organization", "name": "Crumb Bakery",
       "url": "https://crumb.test/"}
NOT_FOUND = {"found": False, "checked": True}
NOT_ASKED = {"found": None, "checked": False, "error": "refused"}
UNCHECKED = {"checked": False, "found": False, "result": None}


def geo_006(node: dict, wikidata=NOT_FOUND, kg=UNCHECKED, wikipedia=NOT_FOUND) -> str:
    with mock.patch.object(entity_checker, "check_wikidata", return_value=dict(wikidata)), \
            mock.patch.object(entity_checker, "check_wikipedia", return_value=dict(wikipedia)), \
            mock.patch.object(entity_checker, "check_google_knowledge_graph",
                              return_value=dict(kg)):
        return page_verdict(entity_checker, "GEO-006", html(head=jsonld(node)))


class EntityResolution(unittest.TestCase):
    def test_x_com_is_matched_by_host(self):
        found = entity_checker.analyze_sameas(["https://www.dropbox.com/s/1"])["found"]
        self.assertNotIn("Twitter/X", found)
        found = entity_checker.analyze_sameas(["https://x.com/crumb"])["found"]
        self.assertIn("Twitter/X", found)

    def test_a_wikidata_same_as_resolves_the_entity(self):
        node = {**ORG, "sameAs": ["https://www.wikidata.org/wiki/Q1"]}
        self.assertEqual(geo_006(node), PASS)

    def test_a_wikidata_lookup_resolves_the_entity(self):
        found = {"found": True, "checked": True, "qid": "Q1", "label": "Crumb Bakery",
                 "confidence": "High"}
        self.assertEqual(geo_006(ORG, wikidata=found), PASS)

    def test_a_knowledge_graph_match_resolves_the_entity(self):
        self.assertEqual(geo_006(ORG, kg={"checked": True, "found": True, "name": "Crumb Bakery"}),
                         PASS)

    def test_nothing_found_where_wikidata_answered_fails(self):
        self.assertEqual(geo_006(ORG), FAIL)

    def test_a_lookup_nobody_answered_is_withheld(self):
        self.assertEqual(geo_006(ORG, wikidata=NOT_ASKED), NO_DATA)

    def test_another_entity_named_alike_is_not_this_one(self):
        """A search hit whose label is not the entity's name resolves nothing."""
        found = {"found": True, "checked": True, "qid": "Q9", "label": "Crumb",
                 "confidence": "Medium"}
        self.assertEqual(geo_006(ORG, wikidata=found), FAIL)


# ---------------------------------------------------------------------------
# article_seo.py — KW-076
# ---------------------------------------------------------------------------

class BodyCopy(unittest.TestCase):
    def kw_076(self, body: str) -> str:
        return page_verdict(article_seo, "KW-076", html(body), keyword="rye bread")

    def test_list_table_and_div_text_is_body_copy(self):
        for body in ("<main><h1>Loaves</h1><ul><li>Our rye bread is dark.</li></ul></main>",
                     "<main><h1>Loaves</h1><table><tr><td>rye bread</td></tr></table></main>",
                     "<main><h1>Loaves</h1><div>We bake rye bread daily.</div></main>",
                     "<main><h1>Loaves</h1><p>We bake rye&nbsp;bread daily.</p></main>"):
            with self.subTest(body=body):
                self.assertEqual(self.kw_076(body), PASS)

    def test_a_heading_alone_is_not_body_copy(self):
        self.assertEqual(self.kw_076("<main><h1>Rye bread</h1><p>We bake daily.</p></main>"), FAIL)


# ---------------------------------------------------------------------------
# social_meta.py — MS-033
# ---------------------------------------------------------------------------

def social(drop=()) -> str:
    tags = {"og:title": "Crumb Bakery sourdough", "og:description": "x" * 60,
            "og:image": "https://a.test/i.jpg", "og:url": "https://a.test/",
            "og:type": "website", "og:site_name": "Crumb", "og:locale": "en_GB",
            "twitter:card": "summary_large_image", "twitter:title": "Crumb",
            "twitter:description": "Bread", "twitter:image": "https://a.test/i.jpg",
            "twitter:site": "@crumb", "twitter:creator": "@jane"}
    meta = "".join(f'<meta {"name" if k.startswith("twitter") else "property"}="{k}" '
                   f'content="{v}">' for k, v in tags.items() if k not in drop)
    return html("<p>Bread</p>", head=meta)


class PreviewTags(unittest.TestCase):
    def test_eleven_tags_without_the_preview_ones_fail(self):
        self.assertEqual(page_verdict(social_meta, "MS-033",
                                      social(drop=("og:image", "twitter:card"))), FAIL)
        self.assertEqual(page_verdict(social_meta, "MS-033", social(drop=("og:image",))), FAIL)
        self.assertEqual(page_verdict(social_meta, "MS-033", social(drop=("twitter:card",))), FAIL)

    def test_every_tag_passes(self):
        self.assertEqual(page_verdict(social_meta, "MS-033", social()), PASS)


# ---------------------------------------------------------------------------
# collection_page_checker.py — AR-154
# ---------------------------------------------------------------------------

PRODUCTS = "".join(f"<a href='/products/loaf-{i}'>Loaf {i}</a>" for i in range(5))


class CategoryPages(unittest.TestCase):
    def test_a_home_page_linking_only_the_listing_is_not_a_category_page(self):
        """The dispute's case: a home page whose nav says Products."""
        page = html("<h1>Crumb</h1><nav><a href='/products'>Products</a></nav><p>Hi</p>")
        self.assertEqual(page_verdict(collection_page_checker, "AR-154", page, "/"), NA)

    def test_a_shop_front_listing_products_is_graded(self):
        page = html("<h1>Crumb</h1>" + PRODUCTS)
        self.assertNotEqual(page_verdict(collection_page_checker, "AR-154", page, "/"), NA)

    def test_a_link_to_the_product_listing_is_not_a_product_link(self):
        page = html("<h1>About</h1><a href='/products'>Products</a><a href='/products/'>All</a>")
        self.assertEqual(page_verdict(collection_page_checker, "AR-154", page, "/about"), NA)

    def test_a_category_page_is_graded(self):
        page = html("<h1>Bread</h1>" + PRODUCTS)
        self.assertNotEqual(page_verdict(collection_page_checker, "AR-154", page, "/shop/bread"),
                            NA)


# ---------------------------------------------------------------------------
# hreflang_checker.py — IN-122, the owner's ruling 2 on batch 4's questions
# ---------------------------------------------------------------------------

class SelfOnlyHreflang(unittest.TestCase):
    def in_122(self, routes: dict, verify: bool = True) -> dict:
        with site_with(routes) as site:
            with mock.patch.object(hreflang_checker.time, "sleep"):
                return hreflang_checker.run_hreflang_check(site.origin + "/en",
                                                           verify_returns=verify)

    def test_a_set_naming_only_the_page_itself_is_not_applicable(self):
        for verify in (True, False):
            for pairs in ((("en", "{origin}/en"),),
                          (("en", "{origin}/en"), ("x-default", "{origin}/en"))):
                with self.subTest(verify=verify, pairs=pairs):
                    out = self.in_122({"/en": hreflang_page(*pairs)}, verify)
                    self.assertEqual(full_verdict("IN-122", out), NA)

    def test_a_bad_code_in_a_self_only_set_still_fails(self):
        out = self.in_122({"/en": hreflang_page(("jp", "{origin}/en"))})
        self.assertEqual(full_verdict("IN-122", out), FAIL)

    def test_a_page_with_no_hreflang_is_still_withheld(self):
        out = self.in_122({"/en": html("<p>Hi</p>")})
        self.assertEqual(full_verdict("IN-122", out), NO_DATA)

    def test_a_pair_still_passes(self):
        pair = (("en", "{origin}/en"), ("de", "{origin}/de"))
        out = self.in_122({"/en": hreflang_page(*pair), "/de": hreflang_page(*pair)})
        self.assertEqual(full_verdict("IN-122", out), PASS)


# ---------------------------------------------------------------------------
# Review round 1
# ---------------------------------------------------------------------------

class ReviewRound1(unittest.TestCase):
    def test_a_microdata_video_object_is_a_video_object(self):
        page = html('<div itemscope itemtype="https://schema.org/VideoObject">'
                    '<meta itemprop="name" content="Bake">'
                    '<meta itemprop="thumbnailUrl" content="https://a.test/t.jpg">'
                    '<meta itemprop="uploadDate" content="2024-03-01">'
                    '<iframe src="https://www.youtube.com/embed/abc123"></iframe></div>')
        self.assertNotEqual(page_verdict(video_schema_checker, "MD-190", page), FAIL)

    def test_dates_shown_in_ordinary_spellings_are_dates(self):
        cn_056 = VisibleDates.cn_056
        for body in ("<p>Published Jan. 12, 2026. Updated Feb. 3, 2026.</p>",
                     "<p>Published Sept 5, 2025. Updated Oct 1, 2025.</p>",
                     "<p>Published 12.01.2026. Updated 03.02.2026.</p>",
                     "<p>Published 12/01/2026. Updated 13/02/2026.</p>",
                     "<p>Veröffentlicht 12. Januar 2026, aktualisiert 3. Februar 2026.</p>",
                     "<p>Опубликовано 12 января 2026, обновлено 3 февраля 2026.</p>"):
            with self.subTest(body=body):
                self.assertEqual(cn_056(self, body), PASS)

    def test_an_ordinary_sentence_is_no_definition(self):
        for text in ("Free delivery within Cyprus is available on every order over fifty euros, "
                     "and orders placed before noon leave the bakery the same afternoon by courier.",
                     "Welcome to our family bakery where every loaf is shaped by hand from flour "
                     "milled down the road and baked in a wood oven before the sun comes up."):
            with self.subTest(text=text[:20]):
                page = html(f"<h1>Shipping</h1><p>{text}</p>")
                self.assertEqual(page_verdict(answer_block_scanner, "GO-144", page), FAIL)
                self.assertEqual(page_verdict(answer_block_scanner, "GEO-004", page), FAIL)

    def test_a_name_guessed_from_the_title_resolves_nothing(self):
        """`Home | Crumb Bakery` names no entity; Wikidata's item labelled Home is not it."""
        found = {"found": True, "checked": True, "qid": "Q16870856", "label": "Home",
                 "confidence": "High"}
        with mock.patch.object(entity_checker, "check_wikidata", return_value=found), \
                mock.patch.object(entity_checker, "check_wikipedia", return_value=dict(NOT_FOUND)), \
                mock.patch.object(entity_checker, "check_google_knowledge_graph",
                                  return_value={"checked": True, "found": True, "name": "Home"}):
            verdict = page_verdict(entity_checker, "GEO-006", html("<p>Bread</p>",
                                                                  title="Home | Crumb Bakery"))
        # Not resolved; since review round 3 withheld rather than failed (a guess is no
        # entity to judge).
        self.assertEqual(verdict, NO_DATA)

    def test_go_143s_fix_names_alternate_name(self):
        self.assertIn("alternateName", ITEMS["GO-143"]["fix"])


class ReviewRound2(unittest.TestCase):
    FAQ_ANSWER = ("Yes, within fourteen days of delivery if the loaf is unopened, and we will refund "
                  "the full price to the card you paid with, no questions asked at all.")

    def test_a_knowledge_graph_hit_on_another_name_resolves_nothing(self):
        node = {**ORG, "name": "Olive Tree Bakery Limassol"}
        self.assertEqual(geo_006(node, kg={"checked": True, "found": True, "name": "Limassol"}),
                         FAIL)
        self.assertEqual(geo_006(node, kg={"checked": True, "found": True,
                                           "name": "Olive Tree Bakery Limassol"}), PASS)

    def test_an_autoplaying_video_without_controls_is_a_background(self):
        page = html('<video autoplay loop playsinline src="/hero.mp4"></video>')
        self.assertEqual(page_verdict(video_schema_checker, "MD-190", page), NA)

    def test_a_name_shown_with_typographic_punctuation_is_shown(self):
        head = ('<meta name="author" content="Ann O\'Neil">'
                '<meta property="og:site_name" content="Jane\'s Kitchen">')
        body = "<p>By Ann O&#8217;Neil</p><footer>&copy; Jane&#8217;s Kitchen</footer>"
        self.assertEqual(VisibleAuthorship.cn_057(self, body, head=head), PASS)

    def test_ordinal_dates_are_dates(self):
        for body in ("<p>Published March 3rd, 2025. Updated April 2nd, 2025.</p>",
                     "<p>Published 3rd March 2025. Updated 21st April 2025.</p>",
                     "<p>Publié le 1er janvier 2025, mis à jour le 2 février 2025.</p>"):
            with self.subTest(body=body):
                self.assertEqual(VisibleDates.cn_056(self, body), PASS)

    def test_faq_markup_is_a_question_and_answer_block(self):
        for body in (f'<strong class="schema-faq-question">Can I return an item?</strong>'
                     f'<p class="schema-faq-answer">{self.FAQ_ANSWER}</p>',
                     f"<details><summary>Can I return an item?</summary><p>{self.FAQ_ANSWER}</p>"
                     f"</details>",
                     f"<dl><dt>Can I return an item?</dt><dd>{self.FAQ_ANSWER}</dd></dl>"):
            with self.subTest(body=body[:30]):
                self.assertEqual(page_verdict(answer_block_scanner, "GO-144", html(body)), PASS)

    def test_a_definition_may_open_with_a_non_ascii_term(self):
        text = ("Café au lait is a drink of strong coffee and hot milk in equal parts, served in a "
                "wide cup at breakfast in most French homes.")
        self.assertEqual(page_verdict(answer_block_scanner, "GO-144", html(f"<p>{text}</p>")), PASS)

    def test_a_language_tagged_name_is_a_name(self):
        node = {"@type": "Product", "name": {"@value": "Rye loaf", "@language": "en"},
                "offers": {"price": "3"}}
        self.assertEqual(page_verdict(rich_results_guard, "TE-172", html(head=jsonld(node))), PASS)

    def test_a_numeric_telephone_is_a_telephone(self):
        self.assertEqual(CompleteNap.lo_200(self, {**SHOP, "telephone": 35725000000}), PASS)

    def test_an_article_header_is_body_copy(self):
        body = ("<main><article><header><h1>Loaves</h1><p>Our rye bread is dark.</p></header>"
                "<p>Baked daily.</p></article></main>")
        self.assertEqual(BodyCopy.kw_076(self, body), PASS)


class ReviewRound3(unittest.TestCase):
    def test_one_time_element_is_one_date(self):
        for body in ('<p><time datetime="2026-03-05T09:00:00+00:00">05/03/2026</time></p>',
                     '<p><time datetime="2026-03-04T23:30:00Z">5 March 2026</time></p>'):
            with self.subTest(body=body):
                self.assertEqual(VisibleDates.cn_056(self, body), WARN)

    def test_query_routed_product_links_are_product_links(self):
        for href in ("/index.php?route=product/product&product_id={}", "/product.php?id={}"):
            with self.subTest(href=href):
                links = "".join(f"<a href='{href.format(i)}'>Loaf {i}</a>" for i in range(6))
                page = html("<h1>Bread</h1>" + links)
                self.assertNotEqual(page_verdict(collection_page_checker, "AR-154", page,
                                                 "/index.php"), NA)

    def test_a_source_in_the_page_furniture_is_no_source(self):
        head = '<link rel="canonical" href="/">'
        byline = "<p class='byline'>By Jane Doe</p><p>Bread is good for you.</p>"
        for furniture in ("<footer><a href='https://www.cysec.gov.cy/'>Licensed by CySEC</a></footer>",
                          "<nav><a href='/references'>References</a></nav>",
                          "<aside><blockquote>Best bread in town!</blockquote></aside>"):
            with self.subTest(furniture=furniture[:20]):
                page = html(byline + furniture, head=head)
                self.assertEqual(page_verdict(citation_readiness, "GO-145", page), FAIL)
        page = html(byline + "<blockquote>A quoted study says so.</blockquote>", head=head)
        self.assertEqual(page_verdict(citation_readiness, "GO-145", page), PASS)

    def test_a_footer_question_is_not_the_pages_answer(self):
        cta = ("<footer><h3>Have a question?</h3><p>Write to the bakery at any time and the person who "
               "bakes the bread will answer you within a day, usually the same morning, by email or "
               "telephone.</p></footer>")
        page = html("<h1>Privacy</h1><p>We keep nothing.</p>" + cta)
        self.assertEqual(page_verdict(answer_block_scanner, "GO-144", page), FAIL)

    def test_a_language_tagged_business_name_is_a_name(self):
        self.assertEqual(CompleteNap.lo_200(self, {**SHOP, "name": {"@value": "Crumb",
                                                                    "@language": "en"}}), PASS)

    def test_a_typed_reference_to_a_defined_node_is_that_node(self):
        graph = {"@context": "https://schema.org", "@graph": [
            {"@type": "WebPage", "@id": "https://a.test/#page",
             "mainEntity": {"@type": "Article", "@id": "https://a.test/#article"}},
            {"@type": "Article", "@id": "https://a.test/#article", "headline": "Rye"}]}
        self.assertEqual(page_verdict(rich_results_guard, "TE-172", html(head=jsonld(graph))), PASS)

    def test_a_lazy_player_is_a_video(self):
        for frame in ('<iframe data-src="https://www.youtube.com/embed/abc"></iframe>',
                      '<iframe src="about:blank" data-lazy-src="https://player.vimeo.com/video/1">'
                      '</iframe>'):
            with self.subTest(frame=frame[:30]):
                self.assertEqual(page_verdict(video_schema_checker, "MD-190", html(frame)), FAIL)

    def test_a_name_only_guessed_from_the_title_is_withheld(self):
        with mock.patch.object(entity_checker, "check_wikidata",
                               return_value={"found": True, "checked": True, "label": "Home"}), \
                mock.patch.object(entity_checker, "check_wikipedia", return_value=dict(NOT_FOUND)), \
                mock.patch.object(entity_checker, "check_google_knowledge_graph",
                                  return_value=dict(UNCHECKED)):
            verdict = page_verdict(entity_checker, "GEO-006", html("<p>Bread</p>",
                                                                  title="Home | Crumb Bakery"))
        self.assertEqual(verdict, NO_DATA)


class ReviewRound4(unittest.TestCase):
    CLAIM = "<p class='byline'>By Jane Doe</p><p>A 2023 survey found that 40% of bakers use rye.</p>"

    def go_145(self, body: str) -> str:
        return page_verdict(citation_readiness, "GO-145",
                            html(body, head='<link rel="canonical" href="/">'))

    def test_a_source_however_its_href_is_spelled_is_a_source(self):
        for href in ("https://www.cdc.gov", "https://www.cdc.gov/flu/vaccines/#effect", "/sources/"):
            with self.subTest(href=href):
                self.assertEqual(self.go_145(f"<main>{self.CLAIM}<a href='{href}'>Source</a></main>"),
                                 PASS)

    def test_an_articles_own_aside_is_its_content(self):
        body = (f"<main><article>{self.CLAIM}<aside class='sources'>"
                f"<a href='https://www.cdc.gov/flu/vaccines'>CDC</a></aside></article></main>")
        self.assertEqual(self.go_145(body), PASS)

    def test_a_menu_named_main_is_no_body_copy(self):
        for menu in ('<div id="mainmenu">', '<div class="header-content">'):
            with self.subTest(menu=menu):
                body = (f"{menu}<ul><li><a href='/r'>Rye bread</a></li></ul></div>"
                        "<div id='content'><h1>Rye bread</h1><p>We bake daily.</p></div>")
                self.assertEqual(BodyCopy.kw_076(self, body), FAIL)

    def test_a_cited_or_listed_article_needs_no_headline(self):
        for node in ({"@type": "BlogPosting", "headline": "Rye", "citation": [
                         {"@type": "Article", "name": "A study", "url": "https://a.test/s"}]},
                     {"@type": "ItemList", "itemListElement": [
                         {"@type": "ListItem", "position": 1, "item": {
                             "@type": "BlogPosting", "name": "Rye", "url": "https://a.test/r"}}]}):
            with self.subTest(node=node["@type"]):
                self.assertEqual(page_verdict(rich_results_guard, "TE-172", html(head=jsonld(node))),
                                 PASS)
        page = html(head=jsonld({"@type": "WebPage", "mainEntity": {"@type": "Article"}}))
        self.assertEqual(page_verdict(rich_results_guard, "TE-172", page), FAIL)


class ReviewRound5(unittest.TestCase):
    def test_an_article_in_a_json_ld_array_needs_a_headline(self):
        for doc in ([{"@context": "https://schema.org", "@type": "Article", "author": "Jane"}],
                    [{"@context": "https://schema.org", "@graph": [{"@type": "Article"}]}]):
            with self.subTest(doc=str(doc)[:40]):
                page = html(head=f'<script type="application/ld+json">{json.dumps(doc)}</script>')
                self.assertEqual(page_verdict(rich_results_guard, "TE-172", page), FAIL)

    def test_an_earlier_date_in_the_story_is_no_update(self):
        body = ("<article><p>Published <time datetime='2024-05-01'>May 1, 2024</time></p>"
                "<p>On March 3, 2024, the council voted to keep the market open.</p></article>")
        self.assertEqual(VisibleDates.cn_056(self, body), WARN)
        body = ("<article><p>Published <time datetime='2024-05-01'>May 1, 2024</time>. "
                "Updated June 2, 2024.</p></article>")
        self.assertEqual(VisibleDates.cn_056(self, body), PASS)

    def test_a_link_beside_the_claim_it_sources_is_a_source(self):
        claim = "<p class='byline'>By Jane Doe</p><p>Bakers prefer rye in winter.</p>"
        for link in ("<p>A 2023 study found that 40% of bakers use rye "
                     "(<a href='https://www.nature.com/articles/x'>Nature</a>).</p>",
                     "<p>Source: <a href='https://www.reuters.com/x'>Reuters</a></p>"):
            with self.subTest(link=link[:30]):
                page = html(f"<main><article>{claim}{link}</article></main>",
                            head='<link rel="canonical" href="/">')
                self.assertEqual(page_verdict(citation_readiness, "GO-145", page), PASS)
        page = html(f"<main><article>{claim}<p>Follow us on "
                    f"<a href='https://www.facebook.com/crumb'>Facebook</a>.</p></article></main>",
                    head='<link rel="canonical" href="/">')
        self.assertEqual(page_verdict(citation_readiness, "GO-145", page), FAIL)

    def test_an_iri_typed_video_object_is_a_video_object(self):
        for kind in ("https://schema.org/VideoObject", "schema:VideoObject"):
            with self.subTest(kind=kind):
                page = html('<iframe src="https://www.youtube.com/embed/abc"></iframe>',
                            head=jsonld({**VIDEO, "@type": kind}))
                self.assertEqual(page_verdict(video_schema_checker, "MD-190", page), PASS)


class ReviewRound6(unittest.TestCase):
    def test_a_labelled_publication_before_an_update_time_passes(self):
        for body in ("<p>Published May 1, 2024. Last updated <time datetime='2024-06-02'>"
                     "June 2, 2024</time>.</p>",
                     "<p>Effective date: January 1, 2024. Last updated: <time datetime='2025-03-03'>"
                     "March 3, 2025</time></p>"):
            with self.subTest(body=body[:30]):
                self.assertEqual(VisibleDates.cn_056(self, body), PASS)

    def test_links_under_a_sources_heading_are_sources(self):
        for heading in ("Sources", "References", "Further reading"):
            with self.subTest(heading=heading):
                body = (f"<main><article><p class='byline'>By Jane Doe</p><p>Rye is back.</p>"
                        f"<h2>{heading}</h2><ul><li><a href='https://www.bbc.co.uk/news/rye'>"
                        f"BBC News: Why rye is back</a></li></ul></article></main>")
                page = html(body, head='<link rel="canonical" href="/">')
                self.assertEqual(page_verdict(citation_readiness, "GO-145", page), PASS)

    def test_a_video_widget_in_the_page_furniture_is_not_the_pages_video(self):
        for widget in ("<aside class='widget'><iframe src='https://www.youtube.com/embed/abc'>"
                       "</iframe></aside>",
                       "<footer><video controls src='/promo.mp4'></video></footer>"):
            with self.subTest(widget=widget[:20]):
                page = html("<main><article><p>Bread.</p></article></main>" + widget)
                self.assertEqual(page_verdict(video_schema_checker, "MD-190", page), NA)

    def test_an_iri_typed_article_is_held_to_its_table(self):
        for kind in ("https://schema.org/Article", "schema:Article"):
            with self.subTest(kind=kind):
                page = html(head=jsonld({"@type": kind, "author": "Jane"}))
                self.assertEqual(page_verdict(rich_results_guard, "TE-172", page), FAIL)


class ReviewRound7(unittest.TestCase):
    def test_a_hero_video_in_the_page_header_is_the_pages(self):
        for hero in ("<header class='hero'><h1>Acme demo</h1>"
                     "<iframe src='https://www.youtube.com/embed/abc'></iframe></header>",
                     "<main><div role='banner' class='hero'>"
                     "<iframe src='https://player.vimeo.com/video/1'></iframe></div></main>"):
            with self.subTest(hero=hero[:20]):
                page = html(hero + "<main><p>Text.</p></main>")
                self.assertEqual(page_verdict(video_schema_checker, "MD-190", page), FAIL)

    def test_a_labelled_date_from_another_document_is_no_publication(self):
        time = "<p><time datetime='2024-05-01'>May 1, 2024</time></p>"
        for other in ("<p>The report, published March 3, 2024, said rye was back.</p>",
                      "<ul><li><a href='/rye'>Rye</a> Posted March 2, 2024</li></ul>",
                      "SIDEBAR"):
            with self.subTest(other=other[:25]):
                body = f"<main><article>{time}{other}</article></main>"
                if other == "SIDEBAR":    # a page-level sidebar's post list
                    body = (f"<main><article>{time}</article></main>"
                            f"<aside><p>Posted April 2, 2024</p></aside>")
                self.assertEqual(VisibleDates.cn_056(self, body), WARN)

    def test_a_title_case_label_is_a_label(self):
        for label in ("Effective Date:", "Published Date:", "Posted On:"):
            with self.subTest(label=label):
                body = (f"<p>{label} January 1, 2024.</p><p>Last updated: "
                        f"<time datetime='2025-03-03'>March 3, 2025</time></p>")
                self.assertEqual(VisibleDates.cn_056(self, body), PASS)

    def test_a_topic_heading_is_no_sources_list(self):
        for heading, href in (("Sources of protein", "https://shop.test/whey"),
                              ("Notes", "https://www.amazon.com/dp/x")):
            with self.subTest(heading=heading):
                body = (f"<main><article><p class='byline'>By Jane Doe</p><p>Rye is back.</p>"
                        f"<h2>{heading}</h2><ul><li><a href='{href}'>Buy it here</a></li></ul>"
                        f"</article></main>")
                page = html(body, head='<link rel="canonical" href="/">')
                self.assertEqual(page_verdict(citation_readiness, "GO-145", page), FAIL)
        body = ("<header><h2>Sources</h2></header><main><article><p class='byline'>By Jane Doe</p>"
                "<p>Rye is back.</p><ul><li><a href='https://shop.test/x'>Buy</a></li></ul>"
                "</article></main>")
        page = html(body, head='<link rel="canonical" href="/">')
        self.assertEqual(page_verdict(citation_readiness, "GO-145", page), FAIL)


class ReviewRound8(unittest.TestCase):
    POST = "<main><article><p>Posted on <time datetime='2024-05-01'>May 1, 2024</time></p>"

    def test_dates_in_the_page_furniture_or_comments_are_not_the_pages(self):
        for extra in ("</article></main><aside><p>Recent: <time datetime='2025-02-01'>Feb 1, 2025</time>"
                      "</p></aside>",
                      "</article></main><aside><p><time datetime='2023-01-01'>Jan 1, 2023</time></p></aside>",
                      "</article></main><footer><p>Site last updated 2025-01-02</p></footer>",
                      "<div id='comments'><p>Ann, <time datetime='2025-03-01'>March 1, 2025</time></p>"
                      "</div></article></main>"):
            with self.subTest(extra=extra[:40]):
                self.assertEqual(VisibleDates.cn_056(self, self.POST + extra), WARN)
        top = "<header><p>Monday, November 10, 2026</p></header>"
        self.assertEqual(VisibleDates.cn_056(self, top + self.POST + "</article></main>"), WARN)

    def test_a_page_with_no_date_of_its_own_shows_none(self):
        body = ("<main><h1>About</h1><p>We bake.</p></main><aside>"
                "<p><time datetime='2024-01-01'>Jan 1, 2024</time></p>"
                "<p><time datetime='2024-02-01'>Feb 1, 2024</time></p></aside>")
        self.assertEqual(VisibleDates.cn_056(self, body), FAIL)

    def test_many_outbound_links_are_read_in_one_pass(self):
        import time as clock
        links = "".join(f"<li><a href='https://site{i}.test/'>Site {i}</a></li>" for i in range(2000))
        body = (f"<main><article><p class='byline'>By Jane Doe</p><h2>Sources</h2><ul>{links}</ul>"
                f"</article></main>")
        started = clock.monotonic()
        page_verdict(citation_readiness, "GO-145", html(body, head='<link rel="canonical" href="/">'))
        self.assertLess(clock.monotonic() - started, 3.0)


class ReviewRound9(unittest.TestCase):
    def test_a_post_date_in_a_hero_header_with_the_h1_is_the_pages(self):
        clean_blog = ("<header class='masthead'><div class='post-heading'><h1>Rye</h1>"
                      "<span class='meta'>Posted by Jane on August 24, 2023</span></div></header>"
                      "<article><p>Bread.</p></article>")
        beautiful = ("<header class='header-section'><h1>First post</h1>"
                     "<span class='post-meta'>Posted on February 26, 2020</span>"
                     "<span class='post-meta'>Last updated: March 3, 2021</span></header>"
                     "<main><p>Bread.</p></main>")
        self.assertEqual(VisibleDates.cn_056(self, clean_blog), WARN)
        self.assertEqual(VisibleDates.cn_056(self, beautiful), PASS)

    def test_a_logo_h1_beside_the_articles_own_h1_is_no_hero(self):
        """Review round 10: a site header whose logo is an <h1>, with a top bar's today."""
        body = ("<header class='site-header'><div class='top-bar'><span class='date'>"
                "Tuesday, November 10, 2026</span></div><h1 class='site-title'><a href='/'>Daily</a>"
                "</h1></header><main><article><h1>Council votes</h1><p>Posted on "
                "<time datetime='2025-03-01'>March 1, 2025</time></p></article></main>")
        self.assertEqual(VisibleDates.cn_056(self, body), WARN)

    def test_cn_056s_sentence_says_what_it_leaves_out(self):
        self.assertIn("furniture", ITEMS["CN-056"]["measures"])


# ---------------------------------------------------------------------------
# The sets batch 5 wrote, held to their sources (GOV-3)
# ---------------------------------------------------------------------------

class TheSetsAreHeld(unittest.TestCase):
    def test_each_set_is_what_its_source_says(self):
        from answer_block_scanner import DEFINITION_TERM_PREPOSITIONS, SIGNAL_POINTS
        from freshness_checker import LABELLED_BLOCKS, MONTH_NAMES
        # The elements a byline or a policy's date line is written in.
        self.assertEqual(set(LABELLED_BLOCKS), {"p", "div", "li", "dd", "dt", "td", "small", "span"})
        from article_seo import BODY_COPY_EXCLUDED
        from schema_required_props import (DATE_PROPS, REFERENCE_KEYS, RULED_REQUIRED,
                                           TEXT_PROPS, URL_PROPS)
        # A bare reference carries only these (JSON-LD's own keywords for a node's type,
        # identity and vocabulary).
        self.assertEqual(REFERENCE_KEYS, {"@type", "@id", "@context"})
        from social_meta import PREVIEW_TAGS
        from video_schema_checker import PLAYER_HOSTS, PLAYER_PATHS
        # The owner's TE-172 ruling: an Article with no headline fails, its two
        # subtypes Google documents with it alike.
        self.assertEqual(RULED_REQUIRED, {"Article": ("headline",), "BlogPosting": ("headline",),
                                          "NewsArticle": ("headline",)})
        # Every property of the two required tables, each read by its kind or as present.
        self.assertEqual(TEXT_PROPS, {"name", "headline"})
        self.assertEqual(URL_PROPS, {"thumbnailUrl"})
        self.assertEqual(DATE_PROPS, {"uploadDate"})
        tabled = {p for table in (schema_required_props.RICH_RESULT_REQUIRED, RULED_REQUIRED)
                  for props in table.values()
                  for prop in props for p in (prop if isinstance(prop, tuple) else (prop,))}
        self.assertLessEqual(TEXT_PROPS | URL_PROPS | DATE_PROPS, tabled)
        # MS-033's ruling names the two tags; each is one of the script's own tags.
        self.assertEqual(PREVIEW_TAGS, ("og:image", "twitter:card"))
        self.assertIn("og:image", social_meta.OG_REQUIREMENTS)
        self.assertIn("twitter:card", social_meta.TWITTER_REQUIREMENTS)
        # Headings h1-h6 and the page furniture the fallback container would read.
        self.assertEqual(BODY_COPY_EXCLUDED, {f"h{n}" for n in range(1, 7)}
                         | {"nav", "header", "footer", "aside", "title"})
        # The embed hosts of the video players a page carries; an open sample, each a
        # host whose embed URL is a player.
        self.assertEqual(set(PLAYER_HOSTS), {"youtube.com", "youtube-nocookie.com",
                                             "player.vimeo.com", "fast.wistia.net",
                                             "fast.wistia.com", "dailymotion.com",
                                             "player.twitch.tv"})
        # The hosts that serve other frames too, each one of the players, with the path
        # its embed URL takes.
        self.assertEqual(PLAYER_PATHS, {"youtube.com": "/embed/", "youtube-nocookie.com": "/embed/",
                                        "dailymotion.com": "/embed/"})
        self.assertLessEqual(set(PLAYER_PATHS), set(PLAYER_HOSTS))
        # Twelve months, each named in English, German, French, Spanish and Russian.
        self.assertEqual(sorted(set(MONTH_NAMES.values())), list(range(1, 13)))
        for word in ("january", "januar", "janvier", "enero", "января", "sept", "dec"):
            self.assertIn(word, MONTH_NAMES)
        # Prepositions and relatives that open a clause, not a term.
        self.assertLessEqual({"within", "to", "for", "with", "where"}, DEFINITION_TERM_PREPOSITIONS)
        # Still the four signals `score` adds; since F15 batch 5 it decides no verdict.
        self.assertEqual(set(SIGNAL_POINTS), {"direct_answer", "definition", "list", "table"})


# ---------------------------------------------------------------------------
# The sentences
# ---------------------------------------------------------------------------

class MeasuresSentences(unittest.TestCase):
    SAYS = {
        "MS-032": "not checked",
        "MB-102": "required properties",
        "AR-154": "not judged",
        "IN-122": "only the page itself",
        "GO-145": "source",
        "GEO-005": "source",
        "GO-144": "direct answer",
        "GEO-004": "direct answer",
        "CN-057": "visible",
        "CN-056": "visible",
        "CN-068": "author",
        "MS-033": "twitter:card",
        "GEO-006": "Wikidata",
        "KW-076": "headings",
    }

    def test_each_ruled_item_states_what_its_rule_decides(self):
        for item_id, words in self.SAYS.items():
            with self.subTest(item=item_id):
                self.assertIn(words, ITEMS[item_id].get("measures", ""))


if __name__ == "__main__":
    unittest.main()
