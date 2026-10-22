"""`openspec/specs/governance/` GOV-3 for the evidence scripts: every hand-written set
that describes a closed vocabulary is derived from it, or held against it here.

A closed vocabulary is one something outside the set can state in full: a standard, an
API's documented values, the registry, this tool's own outputs. Such a set can be wrong
by omission, and an omission is invisible from the code that consumes it — that is
GOV-3's whole sentence. Each reader below holds a set against what it describes, so a
forgotten member fails here by name. The census (`tests/derived-sets.json`) records
which sets are closed and which are open — a heuristic sample whose completeness is not
defined — and `tests/test_derived_sets.py` refuses an unread closed set.

Written in F04 (batch 4), after reading found the first of them wrong: the hreflang
language set held 108 of the 184 two-letter subtags and the region set 199 of 249, so a
valid `hreflang="fo"` or `"en-GI"` was a High issue.
"""
from __future__ import annotations

import hashlib
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(ROOT, "skills", "seo-checklist")
sys.path.insert(0, os.path.join(SKILL, "scripts"))

import hreflang_checker  # noqa: E402

# The suite's switches and tripwire, also when this module runs alone (GOV-7).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402,F401


class HreflangCodesAreTheStandards(unittest.TestCase):
    """BCP 47, which hreflang is: the language subtag is ISO 639-1 where it has two
    letters and the region is ISO 3166-1 alpha-2, both as the IANA Language Subtag
    Registry carries them."""

    # Read off the registry at File-Date 2026-09-17: the count catches a forgotten or an
    # added member, the digest a swapped one. Re-derive both from the registry, never
    # from the set, when either moves.
    LANGUAGES = (184, "59900d6df10194f0")
    REGIONS = (249, "e1c950d24ceb933a")

    @staticmethod
    def fingerprint(codes) -> tuple[int, str]:
        return len(codes), hashlib.sha256(" ".join(sorted(codes)).encode()).hexdigest()[:16]

    def test_the_language_set_is_the_registry_s_two_letter_subtags(self):
        codes = hreflang_checker.VALID_LANG_CODES
        self.assertTrue(all(len(c) == 2 and c.islower() and c.isalpha() for c in codes))
        self.assertEqual(self.fingerprint(codes), self.LANGUAGES)

    def test_the_region_set_is_iso_3166_1_alpha_2(self):
        codes = hreflang_checker.VALID_REGION_CODES
        self.assertTrue(all(len(c) == 2 and c.isupper() and c.isalpha() for c in codes))
        self.assertEqual(self.fingerprint(codes), self.REGIONS)

    def test_no_mistake_is_a_valid_code(self):
        """A correction table that names a valid code refuses that code before the set
        is consulted — which is how Laos came to read as Latin America."""
        self.assertEqual(set(hreflang_checker.COMMON_REGION_MISTAKES)
                         & hreflang_checker.VALID_REGION_CODES, set())
        self.assertEqual(set(hreflang_checker.COMMON_LANG_MISTAKES)
                         & hreflang_checker.VALID_LANG_CODES, set())

    def test_a_valid_code_the_set_forgot_is_not_an_issue(self):
        for tag in ("fo", "fo-FO", "en-GI", "mk-MK", "ar-PS", "it-VA", "lo-LA", "nl-AW"):
            with self.subTest(tag=tag):
                result = hreflang_checker.validate_lang_code(tag)
                self.assertEqual(result["issues"], [], tag)
                self.assertTrue(result["valid"], tag)



class SchemaOrgTypesAreTheVocabulary(unittest.TestCase):
    """The type sets the entity, local and E-E-A-T checks decide by, derived from one
    dated schema.org snapshot (`resources/config/schemaorg-types.json`).

    Written in F04 (batch 4b). Until then `LOCAL_BUSINESS_TYPES` was a hand copy that
    lacked 31 of the 152 `LocalBusiness` types and carried two that are not, and the two
    organization sets held 5 of 188: a hospital's LocalBusiness markup read as none
    (LO-198), and a restaurant naming itself publisher read as no publisher (CN-057)."""

    # Release 30.1 (2026-09-16), as served on 2026-10-22. The counts are the
    # vocabulary's, re-derived from the release file, never from the sets.
    RELEASE = ("30.1", "2026-09-16")
    SOURCE_SHA256 = "0a4b8c4c910fc831ec8695196510973390906a5ee34dc6b862dfec4d21a12f74"
    COUNTS = {"types": 961, "LocalBusiness": 152, "Organization": 188, "Place": 230}

    @classmethod
    def setUpClass(cls):
        from lib import schema_types
        cls.lib = schema_types

    def test_the_snapshot_is_the_release_it_names(self):
        snapshot = self.lib.SNAPSHOT
        self.assertEqual((snapshot["release"], snapshot["date"]), self.RELEASE)
        self.assertEqual(snapshot["sha256"], self.SOURCE_SHA256)
        self.assertEqual(snapshot["source"],
                         "https://schema.org/version/30.1/schemaorg-current-https.jsonld")
        self.assertEqual(len(snapshot["types"]), self.COUNTS["types"])

    def test_each_set_is_every_descendant_of_its_root(self):
        for name, root in (("LOCAL_BUSINESS_TYPES", "LocalBusiness"),
                           ("ORGANIZATION_TYPES", "Organization"),
                           ("PLACE_TYPES", "Place")):
            with self.subTest(root=root):
                types = getattr(self.lib, name)
                self.assertEqual(len(types), self.COUNTS[root])
                self.assertIn(root, types)

    def test_the_types_the_hand_copy_had_wrong(self):
        for name in ("Hospital", "MedicalClinic", "Attorney", "PostOffice",
                     "Dermatology", "VacationRental"):
            self.assertIn(name, self.lib.LOCAL_BUSINESS_TYPES, name)
        for name in ("VeterinaryCare", "SkatingRink"):
            self.assertNotIn(name, self.lib.LOCAL_BUSINESS_TYPES, name)
        self.assertIn("VeterinaryCare", self.lib.ORGANIZATION_TYPES)

    def test_a_hospital_is_a_local_business(self):
        """LO-198 read a hospital's markup as no LocalBusiness at all."""
        from local_seo_checker import find_local_business_nodes
        for schema_type in ("Hospital", "Attorney", "Dermatology", "PostOffice"):
            with self.subTest(schema_type=schema_type):
                self.assertEqual(len(find_local_business_nodes(
                    [{"@type": schema_type, "name": "X"}])), 1)
        self.assertEqual(find_local_business_nodes(
            [{"@type": "VeterinaryCare", "name": "X"}]), [])

    def test_every_organization_type_is_an_entity(self):
        """GEO-006 collected sameAs only from five organization types."""
        from bs4 import BeautifulSoup
        import entity_checker
        for schema_type in ("NGO", "Airline", "Restaurant", "Museum", "Park"):
            with self.subTest(schema_type=schema_type):
                html = ('<script type="application/ld+json">{"@type": "%s", '
                        '"name": "X", "sameAs": ["https://www.wikidata.org/wiki/Q1"]}'
                        '</script>' % schema_type)
                entities = entity_checker.extract_entities_from_schema(
                    BeautifulSoup(html, "html.parser"))
                self.assertEqual([e["type"] for e in entities], [schema_type])
        self.assertIs(entity_checker.ORGANIZATION_TYPES, self.lib.ORGANIZATION_TYPES)
        self.assertIs(entity_checker.PLACE_TYPES, self.lib.PLACE_TYPES)

    def test_every_organization_type_is_a_publisher(self):
        """CN-057 counted a restaurant or a dentist naming itself as no publisher."""
        import eeat_signal_checker
        for schema_type in ("Restaurant", "Dentist", "NGO", "https://schema.org/Store"):
            self.assertTrue(eeat_signal_checker._is_org_type(schema_type), schema_type)
        for schema_type in ("WebPage", "Person", "Article"):
            self.assertFalse(eeat_signal_checker._is_org_type(schema_type), schema_type)



class RetiredSchemaTypesAreOneTable(unittest.TestCase):
    """The schema types Google no longer shows a rich result for, held in one table
    (`lib/schema_types.py`) and read by the three checks that classify a node.

    Written in F04 (batch 4b): there were three copies. `article_seo` and `parse_html()`
    called HowTo deprecated where `rich_results_guard` called it restricted, only the
    guard knew Dataset, and five of the guard's eight names (`CourseInfo`,
    `EstimatedSalary`, `LearningVideo`, `VehicleListing`, `PracticeProblem`) are Google
    feature names, not schema.org types, so no markup could ever match them."""

    @staticmethod
    def classify(type_name: str) -> tuple[str, str, str]:
        import article_seo
        import parse_html
        import rich_results_guard
        page = ('<html><head><script type="application/ld+json">{"@type": "%s"}'
                '</script></head><body></body></html>' % type_name)
        parsed = parse_html.parse_html(page, "https://example.test/")
        issues = rich_results_guard.guard_rich_results([{"@type": type_name}])["issues"]
        guard = ("deprecated" if any(i["severity"] == "error" for i in issues)
                 else "restricted" if issues else "active")
        return (article_seo._describe_schema_node({"@type": type_name})["status"],
                parsed["schema"][0]["status"], guard)

    def test_every_retired_name_is_a_schema_org_type(self):
        from lib import schema_types
        for table in (schema_types.DEPRECATED_TYPES, schema_types.RESTRICTED_TYPES):
            for name in table:
                self.assertIn(name, schema_types.SNAPSHOT["types"], name)

    def test_the_three_checks_classify_every_type_alike(self):
        from lib import schema_types
        for name in (*schema_types.DEPRECATED_TYPES, *schema_types.RESTRICTED_TYPES,
                     "HowTo", "Dataset", "FAQPage", "Article"):
            with self.subTest(type_name=name):
                self.assertEqual(len(set(self.classify(name))), 1, self.classify(name))



class RichResultRequiredPropertiesAreGoogles(unittest.TestCase):
    """`schema_required_props.RICH_RESULT_REQUIRED` against Google's pages for each rich
    result, read 2026-10-22: Product snippet (last updated 2026-09-08) requires `name`
    and one of `review`, `aggregateRating`, `offers`; Video (2026-09-24) requires `name`,
    `thumbnailUrl`, `uploadDate`, with `description` recommended; Review snippet
    (2026-09-08) requires `author`, `reviewRating`, and `itemReviewed` unless the review
    is nested in the item it reviews; Breadcrumb (2026-09-08) requires
    `itemListElement`. Until F04 (batch 4b) the table required `offers` and
    `description`, so a rated product with no offer, a video with no description and a
    product's own nested review were each a TE-172 error, and `schema_required_props`
    kept the same wrong rows for MS-032 (which the first fix in this batch left behind)."""

    GOOGLE = {
        "BreadcrumbList": ("itemListElement",),
        "Product": ("name", ("review", "aggregateRating", "offers")),
        "Review": ("author", "itemReviewed", "reviewRating"),
        "VideoObject": ("name", "thumbnailUrl", "uploadDate"),
    }

    @staticmethod
    def errors(node) -> list[str]:
        """TE-172's errors and MS-032's, which read the same table and must agree."""
        import rich_results_guard
        import schema_required_props
        guard = [i["message"] for i in rich_results_guard.guard_rich_results([node])["issues"]
                 if i["severity"] == "error"]
        validator = [i["message"] for i in
                     schema_required_props.validate_schema_required_props([node])["issues"]
                     if i["severity"] == "error"]
        assert len(guard) == len(validator), (guard, validator)
        return guard

    def test_the_table_is_googles(self):
        import schema_required_props
        self.assertEqual(schema_required_props.RICH_RESULT_REQUIRED, self.GOOGLE)
        self.assertEqual(set(schema_required_props.REQUIRED_PROPS) & set(self.GOOGLE), set())

    def test_a_product_needs_one_of_its_three_not_an_offer(self):
        rating = {"@type": "AggregateRating", "ratingValue": 4, "reviewCount": 3}
        self.assertEqual(self.errors({"@type": "Product", "name": "X",
                                      "aggregateRating": rating}), [])
        self.assertEqual(len(self.errors({"@type": "Product", "name": "X"})), 1)

    def test_a_video_needs_no_description(self):
        self.assertEqual(self.errors({"@type": "VideoObject", "name": "X",
                                      "thumbnailUrl": "https://example.test/t.jpg",
                                      "uploadDate": "2026-01-01"}), [])

    def test_a_value_that_is_only_whitespace_is_missing(self):
        """The validator's rule since before F04, now the guard's too: a property
        written as spaces states nothing."""
        self.assertEqual(len(self.errors({"@type": "Product", "name": "   ",
                                          "offers": {"@type": "Offer"}})), 1)
        self.assertEqual(len(self.errors({"@type": "Product", "name": "X",
                                          "offers": "  "})), 1)

    def test_a_video_s_description_is_recommended(self):
        import schema_required_props
        self.assertIn("description", schema_required_props.RECOMMENDED_PROPS["VideoObject"])

    def test_a_nested_review_names_its_item_by_nesting(self):
        review = {"@type": "Review", "author": {"@type": "Person", "name": "A"},
                  "reviewRating": {"@type": "Rating", "ratingValue": 5}}
        self.assertEqual(self.errors({"@type": "Product", "name": "X",
                                      "review": [review]}), [])
        self.assertEqual(len(self.errors(review)), 1)



class AiCrawlerTokensAreOneList(unittest.TestCase):
    """The AI crawler tokens, kept once: `ai_crawler_policy_matrix.AI_CRAWLERS`, which
    carries each token's scope. The list is open — no authority names every AI
    crawler — so what is held here is that every reader asks about the same ones.
    Until F04 (batch 4b) `robots_checker` kept a second list of 13 (two tokens the
    matrix lacks, four it has missing) and `robots_path_tester` a third of nine."""

    def test_every_reader_asks_about_the_matrix_s_tokens(self):
        import ai_crawler_policy_matrix
        import robots_checker
        import robots_path_tester
        tokens = list(ai_crawler_policy_matrix.AI_CRAWLERS)
        self.assertEqual(list(robots_checker.AI_CRAWLERS), tokens)
        self.assertEqual(list(robots_path_tester.DEFAULT_AGENTS),
                         ["Googlebot", "Bingbot", *tokens])



class StandardVocabulariesAsPublished(unittest.TestCase):
    """Each set below against the document that states it in full, as read on
    2026-10-22 (the date beside each is the document's own). A member the source adds
    or drops fails here by name."""

    def test_inputs_whose_control_names_itself(self):
        """HTML's 22 input types; of them, the ones a `<label>` is not how they get a
        name (HTML-AAM): `hidden` is not rendered, `submit`, `reset` and `button` are
        named by their value, `image` by its `alt`."""
        import a11y_seo_checker
        html_types = {"hidden", "text", "search", "tel", "url", "email", "password",
                      "date", "month", "week", "time", "datetime-local", "number",
                      "range", "color", "checkbox", "radio", "file", "submit", "image",
                      "reset", "button"}
        self.assertEqual(len(html_types), 22)
        self.assertEqual(set(a11y_seo_checker.UNLABELLED_INPUT_TYPES),
                         {"hidden", "submit", "reset", "button", "image"} & html_types)

    def test_safe_browsing_threat_types(self):
        """Safe Browsing v4 `ThreatType` (reference last updated 2024-09-18) less
        `THREAT_TYPE_UNSPECIFIED`, which a lookup never asks for."""
        import domain_safety_check
        self.assertEqual(set(domain_safety_check.SB_THREAT_TYPES),
                         {"MALWARE", "SOCIAL_ENGINEERING", "UNWANTED_SOFTWARE",
                          "POTENTIALLY_HARMFUL_APPLICATION"})

    def test_google_favicon_formats(self):
        """Google's favicon page (last updated 2026-08-28): "BMP, GIF, ICO, PNG, JPEG,
        PPM, and TIFF" — each spelled as `image_header` names what it recognises, or a
        format Google accepts could never be credited."""
        import inspect
        import favicon_check
        from lib import image_header
        self.assertEqual(set(favicon_check.GOOGLE_FAVICON_FORMATS),
                         {"bmp", "gif", "ico", "png", "jpeg", "ppm", "tiff"})
        source = inspect.getsource(image_header)
        for name in favicon_check.GOOGLE_FAVICON_FORMATS:
            self.assertIn(f'"{name}"', source, name)

    def test_font_files_are_the_formats_css_names(self):
        """CSS Fonts 4 `format()`: woff2, woff, truetype, opentype, embedded-opentype,
        collection (and svg, left out: `.svg` is an image far more often than a font).
        Until F04 (batch 4b) `.ttc`, a collection, was not a font file here."""
        import font_audit
        self.assertEqual(set(font_audit.FONT_EXTENSIONS),
                         {".woff2", ".woff", ".ttf", ".otf", ".eot", ".ttc"})
        self.assertEqual(font_audit._font_format("https://example.test/a/b.ttc"), "ttc")

    def test_jpeg_frame_markers(self):
        """ITU-T T.81 Table B.1: SOF0–SOF15 are C0–CF less C4 (DHT), C8 (JPG) and CC
        (DAC) — thirteen."""
        from lib import image_header
        self.assertEqual(set(image_header.JPEG_SOF_MARKERS),
                         {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                          0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF})

    def test_search_console_reads_with_the_read_only_scope(self):
        """The Search Console API's two scopes are `webmasters` and
        `webmasters.readonly`; an audit only reads."""
        import gsc_checker
        self.assertEqual(list(gsc_checker.SCOPES),
                         ["https://www.googleapis.com/auth/webmasters.readonly"])

    def test_html_media_types(self):
        """IANA's media types for HTML: `text/html` and `application/xhtml+xml`."""
        import seo_common
        self.assertEqual(set(seo_common.HTML_CTYPES), {"text/html", "application/xhtml+xml"})

    def test_robots_fields_are_the_ones_crawlers_document(self):
        """RFC 9309's three, the sitemap line (Google, last updated 2026-08-31; Yandex),
        Yandex's Clean-param, and Crawl-delay, which Bing reads. `Host` was Yandex's,
        and its robots.txt page no longer lists it (read 2026-10-22): until F04
        (batch 4b) a `Host:` line passed as a directive a crawler reads."""
        import robots_checker
        self.assertEqual(set(robots_checker.KNOWN_ROBOTS_FIELDS),
                         {"user-agent", "allow", "disallow", "sitemap", "clean-param",
                          "crawl-delay"})
        problems = robots_checker.correctness_problems(
            "User-agent: *\nDisallow: /x\nHost: example.test\n", "text/plain")
        self.assertTrue(any("`host`" in p for p in problems), problems)

    def test_the_bom_sniff_is_whatwg_s(self):
        """WHATWG Encoding, BOM sniff (Living Standard, 19 October 2026): EF BB BF is
        UTF-8, FE FF UTF-16BE, FF FE UTF-16LE, and nothing else."""
        from lib import safe_http
        self.assertEqual({bom for bom, _ in safe_http._BOMS},
                         {b"\xef\xbb\xbf", b"\xfe\xff", b"\xff\xfe"})
        for bom, text in ((b"\xfe\xff", "\u00e9".encode("utf-16-be")),
                          (b"\xff\xfe", "\u00e9".encode("utf-16-le"))):
            name = dict(safe_http._BOMS)[bom]
            self.assertEqual((bom + text).decode(name), "\u00e9")

    def test_cacheable_methods(self):
        """RFC 9110 §9.2.3: GET, HEAD and POST are cacheable; POST only with explicit
        freshness and a Content-Location, which a fetch cache keyed by URL cannot
        honour, so it is left out."""
        from lib import safe_http
        self.assertEqual(set(safe_http.CACHEABLE_METHODS), {"GET", "HEAD"})

    def test_an_opt_in_reaches_private_ranges_and_never_link_local(self):
        """Loopback, RFC 1918, RFC 4193 and RFC 6598 — each not globally routable —
        and never link-local, where a cloud's metadata service answers."""
        import ipaddress
        from lib import safe_http
        networks = [ipaddress.ip_network(n) for n in safe_http.PRIVATE_ALLOWED_NETWORKS]
        self.assertEqual({str(n) for n in networks},
                         {"127.0.0.0/8", "::1/128", "10.0.0.0/8", "172.16.0.0/12",
                          "192.168.0.0/16", "fc00::/7", "100.64.0.0/10"})
        for network in networks:
            self.assertFalse(network.network_address.is_global, network)
        for metadata in ("169.254.169.254", "fe80::1"):
            address = ipaddress.ip_address(metadata)
            self.assertFalse(any(address in n for n in networks if n.version == address.version))

    def test_open_graph_requires_four(self):
        """The Open Graph protocol: "The four required properties for every page are"
        og:title, og:type, og:image, og:url; og:description, og:site_name and
        og:locale are optional. Until F04 (batch 4b) og:description was required here.
        The lengths are this tool's conventions, not the protocol's."""
        import social_meta
        self.assertEqual({tag for tag, rule in social_meta.OG_REQUIREMENTS.items()
                          if rule["required"]},
                         {"og:title", "og:type", "og:image", "og:url"})
        self.assertTrue(set(social_meta.OG_REQUIREMENTS) <= {
            "og:title", "og:type", "og:image", "og:url", "og:audio", "og:description",
            "og:determiner", "og:locale", "og:site_name", "og:video"})

    def test_x_card_types(self):
        """X's card types (developer.x.com/cards/markup, found 2026-10-22; the page
        itself answered 402 to a fetch): summary, summary_large_image, app, player."""
        import social_meta
        self.assertEqual(set(social_meta.TWITTER_REQUIREMENTS["twitter:card"]["valid_values"]),
                         {"summary", "summary_large_image", "app", "player"})

    def test_indexnow_engines(self):
        """indexnow.org's `searchengines.json` (read 2026-10-22): each engine's meta
        URL, whose directory is its endpoint. Until F04 (batch 4b) Yep, the Internet
        Archive and Amazonbot were missing and Yandex's host lacked `www`."""
        import indexnow_checker
        published = {
            "bing": "https://www.bing.com/indexnow/meta.json",
            "yandex": "https://www.yandex.com/indexnow/meta.json",
            "seznam": "https://search.seznam.cz/indexnow/meta.json",
            "naver": "https://searchadvisor.naver.com/indexnow/meta.json",
            "yep": "https://indexnow.yep.com/indexnow/meta.json",
            "internetarchive": "https://web-static.archive.org/indexnow/meta.json",
            "amazonbot": "https://indexnow.amazonbot.amazon/indexnow/meta.json",
        }
        self.assertEqual(indexnow_checker.INDEXNOW_ENDPOINTS,
                         {engine: url.removesuffix("/meta.json")
                          for engine, url in published.items()})


class SearchConsoleIndexingStates(unittest.TestCase):
    """Google's page indexing statuses (support.google.com/webmasters/answer/7440203,
    read 2026-10-22), each on the side Google files it under. The two "warning" ones
    are indexed. Until F04 (batch 4b) "Indexed, though blocked by robots.txt" read as
    not indexed (it holds "blocked"), and "Server error (5xx)", "URL marked
    'noindex'", "Alternate page with proper canonical tag" and "Page indexed without
    content" read as unrecognised, so CI-002 was FAIL or NO_DATA where Google answers."""

    INDEXED = ("Page is indexed", "Submitted and indexed",
               "Indexed, not submitted in sitemap", "Indexed, though blocked by robots.txt",
               "Page indexed without content")
    NOT_INDEXED = (
        "Server error (5xx)", "Redirect error", "URL blocked by robots.txt",
        "URL marked \u2018noindex\u2019", "URL marked 'noindex'", "Soft 404",
        "Blocked due to unauthorized request (401)", "Not found (404)",
        "Blocked due to access forbidden (403)", "URL blocked due to other 4xx issue",
        "Crawled - currently not indexed", "Discovered - currently not indexed",
        "Alternate page with proper canonical tag",
        "Duplicate without user-selected canonical",
        "Duplicate, Google chose different canonical than user", "Page with redirect",
        "URL is unknown to Google")

    def test_every_documented_state_reads_as_google_files_it(self):
        import gsc_url_inspection
        for state in self.INDEXED:
            self.assertIs(gsc_url_inspection.classify_coverage(state), True, state)
        for state in self.NOT_INDEXED:
            self.assertIs(gsc_url_inspection.classify_coverage(state), False, state)
        self.assertIsNone(gsc_url_inspection.classify_coverage("Something new"))

    def test_an_indexed_marker_never_matches_a_state_google_files_as_not_indexed(self):
        """The indexed markers are asked first, so one that also matched a not-indexed
        state would read it as indexed; each must earn its place on a real state."""
        from gsc_url_inspection import INDEXED_MARKERS, NOT_INDEXED_MARKERS
        for marker in INDEXED_MARKERS:
            self.assertTrue(any(marker in s.lower() for s in self.INDEXED), marker)
            self.assertFalse(any(marker in s.lower() for s in self.NOT_INDEXED), marker)
        for marker in NOT_INDEXED_MARKERS:
            self.assertFalse(any(marker in s.lower() and not any(
                m in s.lower() for m in INDEXED_MARKERS) for s in self.INDEXED), marker)


class PageSpeedVocabularies(unittest.TestCase):
    """The PageSpeed Insights API and CrUX. `strategy` is MOBILE or DESKTOP (the API
    reference, last updated 2024-09-03); CrUX grades a metric FAST, AVERAGE or SLOW;
    the Core Web Vitals are LCP, INP and CLS (web.dev). The reference does not list
    `loadingExperience`'s keys, so each key here is held to a CrUX API metric name
    (developer.chrome.com, last updated 2026-10-13) and its label to the threshold
    table."""

    CRUX_METRICS = {"largest_contentful_paint", "interaction_to_next_paint",
                    "cumulative_layout_shift", "first_contentful_paint",
                    "experimental_time_to_first_byte"}

    def test_the_vocabularies(self):
        import pagespeed
        self.assertEqual(set(pagespeed.VALID_STRATEGIES), {"mobile", "desktop"})
        self.assertEqual(set(pagespeed.CRUX_RATING), {"fast", "average", "slow"})
        self.assertEqual(tuple(pagespeed.KNOWN_RATINGS), tuple(pagespeed.CRUX_RATING.values()))
        self.assertEqual(set(pagespeed.CORE_WEB_VITALS), {"LCP", "INP", "CLS"})
        self.assertEqual(set(pagespeed.PSI_METRIC_MAP.values()), set(pagespeed.CWV_THRESHOLDS))
        names = {key.lower().removesuffix("_ms").removesuffix("_score")
                 for key in pagespeed.PSI_METRIC_MAP}
        self.assertEqual(names, self.CRUX_METRICS)


class TheToolsOwnOutputs(unittest.TestCase):

    def test_detectable_profiles_are_the_profiles_file_s(self):
        import json
        import detect_profile
        with open(os.path.join(SKILL, "resources", "config", "profiles.json"),
                  encoding="utf-8") as stream:
            profiles = set(json.load(stream)["profiles"]) - {"default"}
        self.assertEqual(set(detect_profile.PROFILES), profiles)
        self.assertEqual({profile for profile, _w, _l in
                          detect_profile.SCHEMA_SIGNALS.values()} - profiles, set())

    def test_profile_schema_signals_are_schema_org_types(self):
        import detect_profile
        from lib import schema_types
        known = {name.lower() for name in schema_types.SNAPSHOT["types"]}
        self.assertEqual(sorted(set(detect_profile.SCHEMA_SIGNALS) - known), [])

    def test_wasted_crawls_are_status_classes_the_classifier_returns(self):
        import server_log_audit
        returned = {server_log_audit.status_class(code) for code in range(100, 600)}
        self.assertTrue(set(server_log_audit.WASTED) <= returned)
        self.assertEqual(returned - set(server_log_audit.WASTED),
                         {"served", "not_modified", "redirect_permanent",
                          "redirect_temporary"} & returned)



class RetiredSchemaTypesAreGooglesChangelog(unittest.TestCase):
    """The retired table's membership against the Search Central documentation
    changelog (read 2026-10-22), as the owner ruled on 2026-10-22: FAQ rich results "no
    longer appear in Google Search starting May 7, 2026"; How-to documentation was
    removed in September 2023; Dataset markup "is only used by Dataset Search, and not
    Google Search" (2025-11-05); special announcements and fact checks are gone. Nothing
    is restricted to some sites any more. Until F04 (batch 4b) FAQPage and HowTo were
    "restricted" (a warning), so TE-172 passed a page whose FAQ markup Google no longer
    shows, and TECH-001 read the warning count rather than the retired types."""

    def test_the_table_is_the_changelog(self):
        from lib import schema_types
        self.assertEqual(set(schema_types.DEPRECATED_TYPES),
                         {"SpecialAnnouncement", "ClaimReview", "Dataset", "FAQPage", "HowTo"})
        self.assertEqual(dict(schema_types.RESTRICTED_TYPES), {})

    def test_an_faq_page_is_an_error_and_a_retired_type(self):
        import rich_results_guard
        for type_name in ("FAQPage", "HowTo", "Dataset"):
            with self.subTest(type_name=type_name):
                result = rich_results_guard.guard_rich_results([{"@type": type_name}])
                self.assertEqual(result["summary"]["errors"], 1)
                self.assertEqual(result["summary"]["retired_types"], 1)
        live = rich_results_guard.guard_rich_results([{"@type": "Article"}])
        self.assertEqual(live["summary"]["retired_types"], 0)

    def test_tech_001_reads_the_retired_types(self):
        sys.path.insert(0, os.path.join(SKILL, "tools"))
        import build_checklist
        rule = next(item for item in build_checklist.build()
                    if item["id"] == "TECH-001")["check"]["assert"]
        self.assertEqual(rule, {"path": "summary.retired_types", "eq": 0})


class FacetParametersAreOneList(unittest.TestCase):
    """The facet and filter parameter names, kept once in `seo_common.FACET_PARAMS` (an
    open list: no standard names every shop's filters). The owner's ruling, 2026-10-22:
    the union of the three lists the checkers kept, less `page` and `p`, which are
    pagination — Google asks each page of a sequence to carry its own canonical, so a
    `?page=2` that keeps its query in its canonical is right, not a filtered URL."""

    def test_every_checker_reads_the_one_list(self):
        import collection_page_checker
        import faceted_nav_audit
        import seo_common
        import url_quality
        self.assertIs(collection_page_checker.FILTER_PARAMS, seo_common.FACET_PARAMS)
        self.assertIs(faceted_nav_audit.FACET_KEYS, seo_common.FACET_PARAMS)
        self.assertIs(url_quality.FACET_PARAMS, seo_common.FACET_PARAMS)
        self.assertEqual(set(seo_common.FACET_PARAMS), {
            "sort", "filter", "color", "size", "brand", "price", "min_price",
            "max_price", "view", "category", "tag", "rating", "availability", "material"})

    def test_a_page_number_is_not_a_facet(self):
        import faceted_nav_audit
        import url_quality
        page = "https://shop.example.test/shoes?page=2"
        self.assertNotIn("facet_parameters", url_quality.analyze_urls([page])["rows"][0]["flags"])
        self.assertEqual(faceted_nav_audit.audit([page])["rows"][0]["facet_params"], [])
        rated = "https://shop.example.test/shoes?rating=4"
        self.assertIn("facet_parameters", url_quality.analyze_urls([rated])["rows"][0]["flags"])
        tagged = "https://shop.example.test/shoes?category=boots"
        self.assertEqual(faceted_nav_audit.audit([tagged])["rows"][0]["facet_params"],
                         ["category"])


if __name__ == "__main__":
    unittest.main()
