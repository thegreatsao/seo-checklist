"""F15 batch 6: security, speed and technical — `domain_safety_check.py`,
`security_headers.py`, `ga4_tag_checker.py`, `html_validator.py`,
`mobile_render_checker.py`, `favicon_check.py`, `a11y_seo_checker.py`,
`css_minify_check.py`, `third_party_script_audit.py`, `critical_request_chain.py`,
`font_audit.py` — as the owner ruled them (docs/sprint-20261109-F15.md), and the
owner's ruling 1 on batch 5's questions (GO-145 and GEO-005 are N/A on utility pages:
privacy, terms, contact).

Each verdict is the item's real rule from the registry, `applies_when` included, over
the script's real output, from a page served on loopback, unless a third-party service
(Safe Browsing, Nu, a GTM container) has to be stood in for.
"""
import contextlib
import io
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

import a11y_seo_checker  # noqa: E402
import checklist_runner  # noqa: E402
import citation_readiness  # noqa: E402
import critical_request_chain  # noqa: E402
import css_minify_check  # noqa: E402
import domain_safety_check  # noqa: E402
import favicon_check  # noqa: E402
import font_audit  # noqa: E402
import ga4_tag_checker  # noqa: E402
import html_validator  # noqa: E402
import mobile_render_checker  # noqa: E402
import security_headers  # noqa: E402
import third_party_script_audit  # noqa: E402
from checklist_runner import FAIL, NA, NO_DATA, PASS, WARN  # noqa: E402
from harness import allow_loopback, served  # noqa: E402
from image_fixtures import valid_png as png  # noqa: E402
from test_f15_batch3 import SITE, inventory, row, written  # noqa: E402
from test_f15_batch4 import ITEMS, full_verdict  # noqa: E402
from test_f15_batch5 import html, page_verdict, run_item  # noqa: E402


def graded(item_id: str, output: dict) -> str:
    """The runner's own verdict for one item over one result: unread, `applies_when`,
    and a pass by absence over a truncated reading, in its order."""
    key = (ITEMS[item_id]["check"]["script"], ())
    return checklist_runner.grade([ITEMS[item_id]], {key: [item_id]}, {key: output},
                                  {}, False)[0]["status"]


# ---------------------------------------------------------------------------
# The owner's ruling 1 on batch 5's questions: GO-145 and GEO-005 on utility pages
# ---------------------------------------------------------------------------

class UtilityPages(unittest.TestCase):
    """A privacy, terms or contact page makes no claim a source could back: N/A. An
    about page makes claims about the business and keeps the rule."""
    BODY = "<p class='byline'>By Jane Doe</p><p>We keep your order details for a year.</p>"

    def both(self, path: str) -> tuple:
        page = html(self.BODY, head='<link rel="canonical" href="' + path + '">')
        return tuple(page_verdict(citation_readiness, item, page, path=path)
                     for item in ("GO-145", "GEO-005"))

    def test_privacy_terms_and_contact_pages_are_not_applicable(self):
        for path in ("/privacy", "/privacy-policy", "/legal/privacy.html", "/privacy/",
                     "/terms", "/terms-of-service", "/terms-and-conditions.html",
                     "/contact", "/contact-us/", "/cookie-policy", "/datenschutz",
                     "/kontakty", "/politika-konfidencialnosti", "/privatumo-politika"):
            with self.subTest(path=path):
                self.assertEqual(self.both(path), (NA, NA))

    def test_an_about_page_and_an_article_keep_the_rule(self):
        for path in ("/about", "/about-us", "/blog/bread", "/", "/blog/terminology",
                     "/contracts", "/blog/protecting-your-starter"):
            with self.subTest(path=path):
                self.assertEqual(self.both(path), (FAIL, FAIL))

    def test_a_utility_word_in_a_folder_or_query_is_not_the_page(self):
        for path in ("/privacy/why-we-bake", "/contact/blog/post", "/shop?page=privacy"):
            with self.subTest(path=path):
                self.assertEqual(self.both(path), (FAIL, FAIL))


# ---------------------------------------------------------------------------
# domain_safety_check.py — SE-114 (fix), SE-116, TE-171, TE-179 (measures), TE-178 (retire)
# ---------------------------------------------------------------------------

class SafeBrowsingEveryCrawledUrl(unittest.TestCase):
    """SE-114's ruling: every crawled URL is looked up, 500 to a request."""

    def setUp(self):
        guard = mock.patch.dict(os.environ, {"SEO_LOOPBACK_ONLY": "",
                                             "GOOGLE_SAFE_BROWSING_KEY": "key"})
        guard.start()
        self.addCleanup(guard.stop)
        self.asked = []
        for name, value in (("check_uptime", {"checked": True, "reachable": True,
                                              "status": 200, "response_ms": 5,
                                              "error": None}),
                            ("check_whois", {"checked": False, "error": "stubbed"}),
                            ("check_neighbors", {"checked": False, "error": "stubbed"}),
                            ("is_private_host", False)):
            patch = mock.patch.object(domain_safety_check, name, return_value=value)
            patch.start()
            self.addCleanup(patch.stop)

    def answer(self, flagged=(), status=200):
        asked = self.asked

        class Resp:
            status_code = status

            def __init__(self, body):
                self.body = body

            def json(self):
                urls = [e["url"] for e in self.body["threatInfo"]["threatEntries"]]
                return {"matches": [{"threatType": "MALWARE",
                                     "platformType": "ANY_PLATFORM",
                                     "threat": {"url": u}} for u in urls if u in flagged]}

        def post(url, json=None, **kwargs):
            asked.append(json)
            return Resp(json)
        patch = mock.patch.object(domain_safety_check.requests, "post", post)
        patch.start()
        self.addCleanup(patch.stop)

    def run_se(self, item_id: str, rows: list) -> dict:
        path = written(inventory(rows))
        args = [a.replace("{url}", SITE).replace("{inventory_json}", path)
                for a in ITEMS[item_id]["check"]["args"]]
        saved = sys.argv
        sys.argv = ["domain_safety_check.py"] + args + ["--json"]
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                domain_safety_check.main()
        finally:
            sys.argv = saved
        return json.loads(out.getvalue())

    def test_the_three_items_read_the_shared_crawl(self):
        for item_id in ("SE-114", "SE-116", "TE-171"):
            with self.subTest(item=item_id):
                self.assertIn("{inventory_json}", ITEMS[item_id]["check"]["args"])

    def test_a_listed_inner_page_fails_all_three(self):
        inner = SITE + "shop/item"
        self.answer(flagged={inner})
        out = self.run_se("SE-114", [row(SITE), row(inner)])
        looked_up = {e["url"] for body in self.asked
                     for e in body["threatInfo"]["threatEntries"]}
        self.assertIn(inner, looked_up)
        self.assertIn(SITE, looked_up)
        for item_id in ("SE-114", "SE-116", "TE-171"):
            with self.subTest(item=item_id):
                self.assertEqual(full_verdict(item_id, out), FAIL)
        self.assertEqual(out["safe_browsing"]["threats"][0]["url"], inner)

    def test_a_clean_crawl_passes(self):
        self.answer()
        out = self.run_se("SE-114", [row(SITE), row(SITE + "a")])
        self.assertEqual(full_verdict("SE-114", out), PASS)

    def test_five_hundred_urls_to_a_request(self):
        self.answer()
        rows = [row(SITE)] + [row(f"{SITE}p{n}", text="") for n in range(600)]
        out = self.run_se("SE-114", rows)
        self.assertEqual(full_verdict("SE-114", out), PASS)
        sizes = [len(body["threatInfo"]["threatEntries"]) for body in self.asked]
        self.assertEqual(sorted(sizes), [101, 500])

    def test_an_unanswered_batch_withholds_a_clean_answer(self):
        self.answer(status=503)
        out = self.run_se("SE-114", [row(SITE), row(SITE + "a")])
        self.assertEqual(full_verdict("SE-114", out), NO_DATA)


class RetiredNeighbours(unittest.TestCase):
    def test_te_178_has_no_script_assertion_and_an_agent_answers_it(self):
        item = ITEMS["TE-178"]
        self.assertEqual(item["source"], "llm")
        self.assertFalse((item.get("check") or {}).get("script"))
        self.assertTrue(item.get("lens"))


# ---------------------------------------------------------------------------
# security_headers.py — SE-120 (fix), TE-175 (measures)
# ---------------------------------------------------------------------------

SOUND_HEADERS = {"Content-Security-Policy": "default-src 'self'; script-src 'self'",
                 "Permissions-Policy": "camera=(), geolocation=(self)",
                 "Referrer-Policy": "strict-origin-when-cross-origin"}


class HardenedHeaderValues(unittest.TestCase):
    def se_120(self, **overrides) -> str:
        headers = dict(SOUND_HEADERS)
        for name, value in overrides.items():
            name = name.replace("_", "-")
            if value is None:
                headers.pop(name, None)
            else:
                headers[name] = value
        with allow_loopback(), served({"/": (200, headers, html("<p>x</p>"))}) as site:
            out = security_headers.check_security_headers(site.url)
        return full_verdict("SE-120", out)

    def test_sound_values_pass(self):
        self.assertEqual(self.se_120(), PASS)

    def test_unsafe_script_sources_fail(self):
        for csp in ("default-src 'self' 'unsafe-inline'",
                    "script-src 'self' 'unsafe-eval'",
                    "default-src 'none'; script-src 'unsafe-inline' https:"):
            with self.subTest(csp=csp):
                self.assertEqual(self.se_120(**{"Content_Security_Policy": csp}), WARN)

    def test_unsafe_inline_beside_a_nonce_or_hash_is_ignored_by_browsers(self):
        for csp in ("script-src 'nonce-abc' 'unsafe-inline'",
                    "script-src 'sha256-abc=' 'unsafe-inline' 'strict-dynamic'",
                    "script-src 'self'; style-src 'unsafe-inline'"):
            with self.subTest(csp=csp):
                self.assertEqual(self.se_120(**{"Content_Security_Policy": csp}), PASS)

    def test_a_permissions_wildcard_fails(self):
        self.assertEqual(self.se_120(**{"Permissions_Policy": "camera=*, microphone=()"}), WARN)

    def test_unsafe_url_referrer_fails(self):
        self.assertEqual(self.se_120(**{"Referrer_Policy": "unsafe-url"}), WARN)
        # The last policy a browser understands wins.
        self.assertEqual(self.se_120(**{"Referrer_Policy": "unsafe-url, no-referrer"}), PASS)
        self.assertEqual(self.se_120(**{"Referrer_Policy": "no-referrer, unsafe-url"}), WARN)

    def test_two_weak_headers_fail(self):
        self.assertEqual(self.se_120(**{"Referrer_Policy": "unsafe-url",
                                        "Permissions_Policy": "camera=*"}), FAIL)

    def test_a_missing_header_still_counts(self):
        self.assertEqual(self.se_120(**{"Referrer_Policy": None}), WARN)


# ---------------------------------------------------------------------------
# ga4_tag_checker.py — GO-131, GO-132 (fix); the aside: an error page's body
# ---------------------------------------------------------------------------

GTAG = ('<script async src="https://www.googletagmanager.com/gtag/js?id=G-ABC123"></script>'
        "<script>window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments)}"
        "gtag('js',new Date());gtag('config','G-ABC123');</script>")
GTM = ("<script>(function(w,d,s,l,i){w[l]=w[l]||[];w[l].push({'gtm.start':new Date().getTime(),"
       "event:'gtm.js'});var f=d.getElementsByTagName(s)[0],j=d.createElement(s),"
       "dl=l!='dataLayer'?'&l='+l:'';j.async=true;j.src='{origin}/gtm.js?id='+i+dl;"
       "f.parentNode.insertBefore(j,f);})(window,document,'script','dataLayer','GTM-XYZ9');"
       "</script>")


class AnalyticsInstalled(unittest.TestCase):
    def go(self, item_id: str, head: str, extra=None) -> str:
        routes = {"/": html("<p>x</p>", head=head)}
        routes.update(extra or {})
        return full_verdict(item_id, run_item(ga4_tag_checker, item_id, routes))

    def test_a_loader_with_an_id_and_no_config_is_installed(self):
        head = '<script async src="https://www.googletagmanager.com/gtag/js?id=G-ABC123"></script>'
        self.assertEqual(self.go("GO-131", head), PASS)

    def test_ga4_through_gtm_is_installed(self):
        self.assertEqual(self.go("GO-131", GTM, {"/gtm.js": "var x=1;"}), PASS)

    def test_a_container_id_in_text_is_not_an_installation(self):
        self.assertEqual(self.go("GO-131", "<meta name='description' content='GTM-XYZ9'>"), FAIL)

    def test_nothing_fails(self):
        self.assertEqual(self.go("GO-131", ""), FAIL)

    def test_an_error_page_is_not_read(self):
        out = run_item(ga4_tag_checker, "GO-131", {"/": (404, html("<p>gone</p>", head=GTAG))})
        self.assertEqual(full_verdict("GO-131", out), NO_DATA)
        self.assertEqual(full_verdict("GO-132", out), NO_DATA)


class HardcodedBesideGtm(unittest.TestCase):
    def go(self, container) -> str:
        routes = {"/": html("<p>x</p>", head=GTAG + GTM)}
        if container is not None:
            routes["/gtm.js"] = container
        return full_verdict("GO-132", run_item(ga4_tag_checker, "GO-132", routes))

    def test_the_container_firing_the_hardcoded_id_is_a_duplicate(self):
        self.assertEqual(self.go('var data={"tags":[{"function":"__gaawc",'
                                 '"vtp_measurementId":"G-ABC123"}]};'), FAIL)

    def test_a_container_firing_something_else_is_not(self):
        self.assertEqual(self.go('var data={"vtp_conversionId":"AW-1"};'), PASS)

    def test_a_class_name_is_not_a_container(self):
        routes = {"/": html("<div class='gtm-wrapper'>x</div>", head=GTAG + GTM),
                  "/gtm.js": 'var data={"vtp_conversionId":"AW-1"};'}
        self.assertEqual(full_verdict("GO-132", run_item(ga4_tag_checker, "GO-132", routes)), PASS)

    def test_an_unread_container_is_undecided(self):
        self.assertEqual(self.go((404, "not found")), NO_DATA)

    def test_gtm_alone_reads_no_container(self):
        routes = {"/": html("<p>x</p>", head=GTM)}
        with mock.patch.object(ga4_tag_checker, "safe_get",
                               wraps=ga4_tag_checker.safe_get) as get:
            out = run_item(ga4_tag_checker, "GO-132", routes)
        self.assertEqual(full_verdict("GO-132", out), PASS)
        self.assertEqual(get.call_count, 1)


# ---------------------------------------------------------------------------
# html_validator.py — TE-181 (fix): the doctype put back
# ---------------------------------------------------------------------------

class RenderedDoctype(unittest.TestCase):
    def validate(self, payload: dict):
        sent = []

        class Resp:
            status_code = 200
            headers = {}

            def json(self):
                return {"messages": []}

        def post(url, data=None, **kwargs):
            sent.append(data.decode("utf-8"))
            return Resp()
        folder = tempfile.mkdtemp(prefix="f15-b6-")
        path = os.path.join(folder, "rendered.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        with mock.patch.dict(os.environ, {"SEO_LOOPBACK_ONLY": ""}), \
                mock.patch.object(html_validator.requests, "post", post), \
                mock.patch.object(html_validator, "pace"):
            out = html_validator.validate("https://example.test/", rendered_json=path)
        return out, sent

    def test_the_snippet_records_the_doctype(self):
        skill = open(os.path.join(ROOT, "skills", "seo-checklist", "SKILL.md"),
                     encoding="utf-8").read()
        self.assertIn("document.doctype", skill)

    def test_the_recorded_doctype_is_sent_first(self):
        out, sent = self.validate({"html": "<html><head><title>x</title></head></html>",
                                   "doctype": "<!DOCTYPE html>"})
        self.assertTrue(sent[0].startswith("<!DOCTYPE html>"), sent[0][:40])
        self.assertEqual(full_verdict("TE-181", out), PASS)

    def test_a_page_with_no_doctype_is_sent_without_one(self):
        _, sent = self.validate({"html": "<html></html>", "doctype": ""})
        self.assertEqual(sent, ["<html></html>"])

    def test_a_document_carrying_its_own_doctype_is_sent_as_is(self):
        _, sent = self.validate({"html": "<!doctype html><html></html>"})
        self.assertEqual(sent, ["<!doctype html><html></html>"])

    def test_an_old_artifact_without_the_key_is_not_validated(self):
        out, sent = self.validate({"html": "<html><head></head></html>"})
        self.assertEqual(sent, [])
        self.assertEqual(full_verdict("TE-181", out), NO_DATA)


# ---------------------------------------------------------------------------
# mobile_render_checker.py — MB-100 (fix; sentence)
# ---------------------------------------------------------------------------

VIEWPORT = '<meta name="viewport" content="width=device-width, initial-scale=1">'


class MediaQueriesAreNotWidths(unittest.TestCase):
    def mb(self, extra: str, body: str = "<p>x</p>") -> str:
        return page_verdict(mobile_render_checker, "MB-100", html(body, head=VIEWPORT + extra))

    def test_a_min_width_media_query_passes(self):
        for css in ("<style>@media (min-width: 768px){.a{color:red}}</style>",
                    "<style>@media screen and (min-width:1024px) and (max-width: 1400px)"
                    "{.a{float:left}}</style>",
                    '<link rel="stylesheet" href="/w.css" media="(min-width: 900px)">',
                    "<style>@container (min-width: 600px){.c{display:grid}}</style>",
                    "<style>@media (min-width: 992px){.container{width: 960px}}</style>",
                    "<style>@media screen and (min-width: 62em){.container{width: 960px}}</style>",
                    "<style>@media (width >= 768px){.container{width: 720px}}</style>",
                    "<style>@media (min-width: 768px){@media (min-width: 1200px){.c{width:1140px}}"
                    ".d{width:700px}}</style>"):
            with self.subTest(css=css):
                self.assertEqual(self.mb(css), PASS)

    def test_sizes_attribute_is_not_a_width(self):
        self.assertEqual(self.mb("", '<img src="a.jpg" alt="a" sizes="(min-width: 900px) 50vw">'),
                         PASS)

    def test_a_fixed_width_still_fails(self):
        for css in ("<style>.wrap{width: 1024px}</style>",
                    "<style>@media (max-width: 767px){.wrap{min-width: 980px}}</style>",
                    "<style>@media not all and (min-width: 768px){.wrap{width: 980px}}</style>",
                    "<style>@media (min-width: 300px){.wrap{width: 980px}}</style>",
                    '<div style="min-width: 800px">x</div>',
                    "<p>A smiley :(</p><style>.wrap{width: 1024px}</style><p>end)</p>"):
            with self.subTest(css=css):
                in_head = css.startswith("<style")
                self.assertEqual(self.mb(css if in_head else "", "<p>x</p>" if in_head else css),
                                 FAIL)


# ---------------------------------------------------------------------------
# favicon_check.py — MB-104 (fix): the icon origin's robots.txt
# ---------------------------------------------------------------------------

class IconOriginRobots(unittest.TestCase):
    def grade(self, page_robots: str, icon_robots: str) -> str:
        robots = lambda text: (200, {"Content-Type": "text/plain"}, text)  # noqa: E731
        with allow_loopback(), \
                served({"/robots.txt": robots(icon_robots),
                        "/icons/fav.png": (200, {"Content-Type": "image/png"},
                                           png(96, 96))}) as icons:
            page = ('<!doctype html><html><head><title>t</title><link rel="icon" href="'
                    + icons.url.rstrip("/") + '/icons/fav.png"></head><body></body></html>')
            with served({"/": page, "/robots.txt": robots(page_robots)}) as site:
                out = favicon_check.check(site.url)
        return full_verdict("MB-104", out)

    def test_the_page_origins_rules_do_not_govern_another_origins_icon(self):
        self.assertEqual(self.grade("User-agent: *\nDisallow: /icons/\n",
                                    "User-agent: *\nAllow: /\n"), PASS)

    def test_the_icon_origins_rules_do(self):
        self.assertEqual(self.grade("User-agent: *\nAllow: /\n",
                                    "User-agent: Googlebot-Image\nDisallow: /icons/\n"), FAIL)


# ---------------------------------------------------------------------------
# a11y_seo_checker.py — TE-180 (fix)
# ---------------------------------------------------------------------------

class AccessibleNames(unittest.TestCase):
    def failures(self, body: str) -> int:
        out = run_item(a11y_seo_checker, "TE-180", {"/": html(body)})
        return out["wcag_a"]["unnamed_fields"]

    def test_aria_labelledby_is_resolved_to_text(self):
        self.assertEqual(self.failures('<span id="l">Email</span>'
                                       '<input type="email" aria-labelledby="l">'), 0)
        self.assertEqual(self.failures('<input type="email" aria-labelledby="nowhere">'), 1)
        self.assertEqual(self.failures('<span id="e"> </span>'
                                       '<input type="email" aria-labelledby="e">'), 1)
        self.assertEqual(self.failures('<span id="a">First</span><span id="b"></span>'
                                       '<input aria-labelledby="b a">'), 0)

    def test_an_empty_label_is_no_name(self):
        for body in ('<input aria-label="  ">', '<input title="">',
                     '<label for="q"> </label><input id="q">',
                     '<label><input name="q"></label>',
                     '<label><select><option>One</option></select></label>'):
            with self.subTest(body=body):
                self.assertEqual(self.failures(body), 1)

    def test_a_named_field_passes(self):
        for body in ('<label for="q">Search</label><input id="q">',
                     '<label>Search <input name="q"></label>',
                     '<input aria-label="Search">', '<input title="Search">',
                     '<input type="hidden" name="t">', '<input type="submit">',
                     '<input type="reset">', '<input type="submit" value="Send">',
                     '<input type="button" value="Open">',
                     '<input type="image" src="go.png" alt="Go">'):
            with self.subTest(body=body):
                self.assertEqual(self.failures(body), 0)

    def test_image_and_button_inputs_are_read(self):
        for body in ('<input type="image" src="go.png">', '<input type="image" src="go.png" alt="">',
                     '<input type="button">', '<input type="button" value=" ">',
                     '<input type="submit" value="">'):
            with self.subTest(body=body):
                self.assertEqual(self.failures(body), 1)

    def test_the_item_fails_on_one(self):
        self.assertEqual(page_verdict(a11y_seo_checker, "TE-180",
                                      html('<input type="image" src="go.png">')), FAIL)


# ---------------------------------------------------------------------------
# css_minify_check.py — TE-174 (fix); the aside: a sheet's status
# ---------------------------------------------------------------------------

UNMINIFIED = "/* a comment */\n" + "".join(
    f".rule-{n} {{\n  color: red;\n  margin: 0 auto;\n}}\n" for n in range(120))


class StylesheetsRead(unittest.TestCase):
    def te(self, head: str, routes: dict) -> dict:
        routes = dict(routes)
        routes["/"] = html("<p>x</p>", head=head)
        return run_item(css_minify_check, "TE-174", routes)

    def test_an_unread_sheet_is_not_a_minified_one(self):
        out = self.te('<link rel="stylesheet" href="/ok.css"><link rel="stylesheet" href="/gone.css">',
                      {"/ok.css": (200, {"Content-Type": "text/css"}, "a{b:c}" * 500)})
        self.assertTrue(out["truncated"])
        self.assertEqual(graded("TE-174", out), NO_DATA)

    def test_an_error_pages_body_is_not_judged_as_css(self):
        out = self.te('<link rel="stylesheet" href="/gone.css">',
                      {"/gone.css": (404, UNMINIFIED)})
        self.assertEqual(out["unminified_count"], 0)
        self.assertEqual(graded("TE-174", out), NO_DATA)

    def test_a_style_import_is_read(self):
        out = self.te("<style>@import url('/big.css');</style>",
                      {"/big.css": (200, {"Content-Type": "text/css"}, UNMINIFIED)})
        self.assertEqual(graded("TE-174", out), FAIL)
        out = self.te('<style>@import "/big.css" screen;</style>',
                      {"/big.css": (200, {"Content-Type": "text/css"}, UNMINIFIED)})
        self.assertEqual(graded("TE-174", out), FAIL)


# ---------------------------------------------------------------------------
# third_party_script_audit.py — SP-109 (fix)
# ---------------------------------------------------------------------------

class ThirdPartyScripts(unittest.TestCase):
    def sp(self, head: str) -> str:
        return page_verdict(third_party_script_audit, "SP-109", html("<p>x</p>", head=head))

    def test_a_protocol_relative_script_on_another_host_is_third_party(self):
        self.assertEqual(self.sp('<script src="//cdn.example.test/a.js"></script>'
                                 '<script src="//cdn.example.test/b.js"></script>'
                                 '<script src="//cdn.example.test/c.js"></script>'), FAIL)
        self.assertEqual(self.sp('<script src="//cdn.example.test/a.js"></script>'), WARN)

    def test_a_data_block_is_not_executed(self):
        for kind in ("text/plain", "application/ld+json", "text/template", "text/x-handlebars"):
            with self.subTest(kind=kind):
                self.assertEqual(self.sp(f'<script type="{kind}" src="https://cdn.example.test/a"></script>'),
                                 PASS)

    def test_javascript_types_still_block(self):
        for kind in ("text/javascript", "application/javascript", "TEXT/JAVASCRIPT; charset=utf-8",
                     "application/x-javascript", ""):
            with self.subTest(kind=kind):
                self.assertEqual(self.sp(f'<script type="{kind}" src="https://cdn.example.test/a"></script>'),
                                 WARN)


# ---------------------------------------------------------------------------
# font_audit.py — TECH-002 (fix); the aside: a <link> with no href
# ---------------------------------------------------------------------------

class FontDisplayBlock(unittest.TestCase):
    def tech(self, display: str) -> str:
        face = "@font-face{font-family:X;src:url(/x.woff2) format('woff2');%s}" % display
        return page_verdict(font_audit, "TECH-002", html("<p>x</p>", head=f"<style>{face}</style>"))

    def test_block_and_auto_are_a_missing_value(self):
        for display in ("font-display: block", "font-display:BLOCK ", "font-display: auto",
                        "font-display: block !important", ""):
            with self.subTest(display=display):
                self.assertEqual(self.tech(display), FAIL)

    def test_swap_optional_fallback_pass(self):
        for display in ("font-display: swap", "font-display: optional", "font-display: fallback"):
            with self.subTest(display=display):
                self.assertEqual(self.tech(display), PASS)

    def test_a_link_with_no_href_is_not_fetched(self):
        routes = {"/": html("<p>x</p>", head='<link rel="stylesheet">')}
        with mock.patch.object(font_audit, "safe_get", wraps=font_audit.safe_get) as get:
            out = run_item(font_audit, "TECH-002", routes)
        self.assertEqual(get.call_count, 0)
        self.assertEqual(full_verdict("TECH-002", out), PASS)


# ---------------------------------------------------------------------------
# Review round 1 (a fresh-context Claude reviewer), each red first
# ---------------------------------------------------------------------------

class ReviewRound1(unittest.TestCase):
    def test_an_article_whose_slug_holds_a_utility_word_keeps_the_rule(self):
        body = UtilityPages.BODY
        for path in ("/blog/how-to-choose-contact-lenses", "/blog/data-privacy-laws-2026",
                     "/blog/gdpr-compliance-checklist", "/blog/privacy-tips-for-parents",
                     "/blog/seo-terms-explained", "/blog/contactless-payments-guide",
                     "/shop/hibiscus-sabdariffa-tea", "/blog/pravila-pitaniya"):
            with self.subTest(path=path):
                page = html(body, head='<link rel="canonical" href="' + path + '">')
                self.assertEqual(page_verdict(citation_readiness, "GO-145", page, path=path),
                                 FAIL)

    def test_page_mode_asks_safe_browsing_about_the_page(self):
        items = [ITEMS[i] for i in ("SE-114", "SE-116", "TE-171")]
        plan, skipped = checklist_runner.build_plan(
            items, {"url": SITE}, set(checklist_runner.MODE_CAPS["page"]), "page",
            has_safe_browsing=True)
        self.assertEqual(skipped, {})
        self.assertEqual(list(plan), [("domain_safety_check.py", (SITE,))])

    def test_sp_110_does_not_fail_a_data_block(self):
        for kind in ("text/plain", "application/ld+json"):
            with self.subTest(kind=kind):
                page = html("<p>x</p>", head=f'<script type="{kind}" '
                                             'src="https://cdn.example.net/stats.js"></script>')
                self.assertEqual(page_verdict(critical_request_chain, "SP-110", page), PASS)
        page = html("<p>x</p>", head='<script src="https://cdn.example.net/stats.js"></script>')
        self.assertEqual(page_verdict(critical_request_chain, "SP-110", page), FAIL)

    def go_132(self, container: str) -> str:
        routes = {"/": html("<p>x</p>", head=GTAG + GTM), "/gtm.js": container}
        return full_verdict("GO-132", run_item(ga4_tag_checker, "GO-132", routes))

    def test_a_gtm_event_tag_to_the_hardcoded_id_is_no_duplicate(self):
        self.assertEqual(self.go_132(
            'var data={"tags":[{"function":"__gaawe","vtp_eventName":"cta_click",'
            '"vtp_measurementIdOverride":"G-ABC123","tag_id":7}]};'), PASS)

    def test_a_gtm_google_tag_or_config_to_the_hardcoded_id_is_one(self):
        for tag in ('{"function":"__googtag","vtp_tagId":"G-ABC123","tag_id":3}',
                    '{"function":"__gaawc","vtp_measurementId":"G-ABC123","vtp_sendPageView":true}'):
            with self.subTest(tag=tag):
                self.assertEqual(self.go_132('var data={"tags":[' + tag + ']};'), FAIL)

    def test_a_label_named_by_an_images_alt_names_its_field(self):
        out = run_item(a11y_seo_checker, "TE-180", {"/": html(
            '<label><img src="a.png" alt="Search"><input type="search" name="q"></label>'
            '<span id="n" aria-label="Email"></span><input aria-labelledby="n">')})
        self.assertEqual(out["wcag_a"]["unnamed_fields"], 0)

    def test_print_and_wide_container_rules_never_apply_on_a_phone(self):
        for css in ("@media print { .page { width: 1000px } }",
                    "@media screen and (min-width:992px), print {.c{width:960px}}",
                    "@container (min-width:700px) {.c{width:680px}}",
                    "@container card (min-width: 40em) {.c{width:600px}}"):
            with self.subTest(css=css):
                self.assertEqual(page_verdict(mobile_render_checker, "MB-100",
                                              html("<p>x</p>", head=VIEWPORT + f"<style>{css}</style>")),
                                 PASS)
        self.assertEqual(page_verdict(mobile_render_checker, "MB-100", html(
            "<p>x</p>", head=VIEWPORT + "<style>@media screen, print {.c{width:960px}}</style>")),
            FAIL)

    def test_a_quoted_import_url_is_read_whole(self):
        url = "/css2?family=Roboto:wght@400;700&display=swap"
        seen = []

        def css():
            seen.append(True)
            return UNMINIFIED
        out = run_item(css_minify_check, "TE-174", {
            "/": html("<p>x</p>", head=f"<style>@import url('{url}');</style>"),
            url: (200, {"Content-Type": "text/css"}, css)})
        self.assertEqual([row["href"].split("/", 3)[-1] for row in out["stylesheets"]],
                         [url.lstrip("/")])

    def test_se_120_says_a_csp_that_does_not_restrict_scripts_is_a_gap(self):
        self.assertIn("restricting scripts", ITEMS["SE-120"]["measures"])


class ReviewRound2(unittest.TestCase):
    SB = ("SE-114", "SE-116", "TE-171")

    def plan(self, ctx, rejected=None):
        return checklist_runner.build_plan(
            [ITEMS[i] for i in self.SB], ctx, set(checklist_runner.MODE_CAPS["live"]), "live",
            rejected=rejected, has_safe_browsing=True)

    def test_live_mode_without_a_crawl_asks_about_the_entry(self):
        for ctx, rejected in (({"url": SITE}, None),
                              ({"url": SITE}, {"inventory_json": "the shared crawl read nothing"})):
            with self.subTest(rejected=rejected):
                plan, skipped = self.plan(ctx, rejected)
                self.assertEqual(skipped, {})
                self.assertEqual(list(plan), [("domain_safety_check.py", (SITE,))])

    def test_a_crawl_item_still_needs_its_crawl(self):
        plan, skipped = checklist_runner.build_plan(
            [ITEMS["TE-176"]], {"url": SITE}, set(checklist_runner.MODE_CAPS["live"]), "live",
            rejected={"inventory_json": "the shared crawl read nothing"})
        self.assertEqual(skipped["TE-176"][0], NO_DATA)

    def both(self, path: str) -> str:
        page = html(UtilityPages.BODY, head='<link rel="canonical" href="' + path + '">')
        return page_verdict(citation_readiness, "GO-145", page, path=path)

    def test_a_compound_word_is_not_a_utility_word(self):
        for path in ("/kontaktlinsen", "/contactless", "/privacyscreen", "/cookiecutter",
                     "/termsheet", "/cookie-recipes", "/policy", "/blog/data-2026"):
            with self.subTest(path=path):
                self.assertEqual(self.both(path), FAIL)

    def test_ordinary_utility_slugs_are_read(self):
        for path in ("/privacy-policy-2", "/terms-of-sale", "/terms-of-business",
                     "/website-terms", "/politika-konfidentsialnosti",
                     "/politika-konfidenczialnosti", "/contact/index.html", "/contacts",
                     "/kontaktai", "/datenschutzerklaerung", "/polzovatelskoe-soglashenie",
                     "/privatumo-politika", "/taisykles", "/agb"):
            with self.subTest(path=path):
                self.assertEqual(self.both(path), NA)

    def test_a_google_tag_naming_its_id_through_a_constant_variable_is_read(self):
        container = ('var data = {"resource": {"version": "5", "macros": ['
                     '{"function": "__e"}, {"function": "__c", "vtp_value": "G-ABC123"}], '
                     '"tags": [{"function": "__googtag", "vtp_tagId": ["macro", 1], '
                     '"tag_id": 2}]}};')
        routes = {"/": html("<p>x</p>", head=GTAG + GTM), "/gtm.js": container}
        self.assertEqual(full_verdict("GO-132", run_item(ga4_tag_checker, "GO-132", routes)),
                         FAIL)

    def test_a_commented_out_snippet_is_not_installed(self):
        routes = {"/": html("<p>x</p>", head="<!-- old tag " + GTAG + " -->" + GTM),
                  "/gtm.js": 'var data={"tags":[{"function":"__googtag","vtp_tagId":"G-ABC123"}]};'}
        out = run_item(ga4_tag_checker, "GO-132", routes)
        self.assertEqual(full_verdict("GO-132", out), PASS)
        self.assertNotIn("G-ABC123", out["measurement_ids"])

    def test_min_device_width_is_a_wide_only_query(self):
        page = html("<p>x</p>", head=VIEWPORT + "<style>@media only screen and "
                    "(min-device-width: 768px){.container{width:960px}}</style>")
        self.assertEqual(page_verdict(mobile_render_checker, "MB-100", page), PASS)

    def se_120(self, **overrides) -> str:
        return HardenedHeaderValues.se_120(self, **overrides)

    def test_a_script_wildcard_and_an_allowlist_wildcard_are_gaps(self):
        for csp in ("script-src *", "default-src 'self' https:", "script-src 'self' data:"):
            with self.subTest(csp=csp):
                self.assertEqual(self.se_120(**{"Content_Security_Policy": csp}), WARN)
        self.assertEqual(self.se_120(**{"Content_Security_Policy":
                                        "script-src 'nonce-a' 'strict-dynamic' https:"}), PASS)
        self.assertEqual(self.se_120(**{"Permissions_Policy": "geolocation=(self *)"}), WARN)


# ---------------------------------------------------------------------------
# The sets the batch adds, held to their sources
# ---------------------------------------------------------------------------

class TheSetsAreHeld(unittest.TestCase):
    def test_each_set_is_what_its_source_says(self):
        from citation_readiness import UTILITY_SLUG_WORDS, UTILITY_WORDS
        import eeat_signal_checker
        # Every privacy and contact href fragment eeat-terms.json holds as one word is a
        # utility word, and the terms ones among its trust fragments (review round 2: the
        # fragments are href substrings; the slug words are their whole-word forms).
        fragments = {stem.strip("/") for concepts in
                     eeat_signal_checker._TERMS["languages"].values()
                     for concept in ("privacy", "contact")
                     for stem in concepts.get(concept, {}).get("href", [])}
        self.assertLessEqual({"privacy", "gdpr", "datenschutz", "bdar", "contact", "kontakt",
                              "terms", "salygos", "usloviya", "pravila"}, UTILITY_WORDS)
        for fragment in fragments:
            with self.subTest(fragment=fragment):
                words = fragment.split("-")
                self.assertTrue(any(w in UTILITY_WORDS or any(u.startswith(w) for u in UTILITY_WORDS)
                                    for w in words), fragment)
        self.assertEqual(len(UTILITY_WORDS), 40)
        self.assertEqual(UTILITY_WORDS & UTILITY_SLUG_WORDS, set())
        # Filler words name no kind of page: none is a subject an article is about.
        self.assertEqual(UTILITY_SLUG_WORDS, {
            "our", "the", "of", "and", "us", "use", "service", "services", "conditions",
            "notice", "statement", "policy", "policies", "page", "info", "information",
            "form", "sale", "sales", "business", "website", "site", "politika",
            "ispolzovaniya", "obrabotki", "polzovatelskoe", "publichnaya", "naudojimo",
            "duomenu"})
        from security_headers import (CSP_ANY_SOURCE, CSP_INLINE_OVERRIDES,
                                      HARDENING_HEADERS, REFERRER_POLICIES)
        # A source expression matching every host: the wildcard, and a bare scheme
        # (CSP Level 3, "source expressions"); review round 2.
        self.assertEqual(CSP_ANY_SOURCE, {"*", "http:", "https:", "data:"})
        # SE-120's title names these three headers.
        self.assertEqual(HARDENING_HEADERS, ("content-security-policy", "permissions-policy",
                                             "referrer-policy"))
        # CSP Level 3: a nonce, a hash (the three digests CSP names) or 'strict-dynamic'
        # makes 'unsafe-inline' ignored for scripts.
        self.assertEqual(set(CSP_INLINE_OVERRIDES), {"'nonce-", "'sha256-", "'sha384-",
                                                     "'sha512-", "'strict-dynamic'"})
        # W3C Referrer Policy, the eight policy tokens.
        self.assertEqual(REFERRER_POLICIES, {
            "no-referrer", "no-referrer-when-downgrade", "same-origin", "origin",
            "strict-origin", "origin-when-cross-origin", "strict-origin-when-cross-origin",
            "unsafe-url"})
        from third_party_script_audit import JAVASCRIPT_TYPES
        # WHATWG MIME Sniffing, "JavaScript MIME type" (16 essences), plus no type.
        self.assertEqual(len(JAVASCRIPT_TYPES - {""}), 16)
        self.assertIn("", JAVASCRIPT_TYPES)
        self.assertNotIn("module", JAVASCRIPT_TYPES)
        self.assertNotIn("text/plain", JAVASCRIPT_TYPES)


# ---------------------------------------------------------------------------
# The sentences
# ---------------------------------------------------------------------------

class MeasuresSentences(unittest.TestCase):
    SAYS = {
        "SE-114": "the crawl read",
        "SE-116": "SEO spam",
        "TE-171": "Safe Browsing only",
        "TE-179": "creation date",
        "SE-120": "unsafe-url",
        "TE-175": "served HTML",
        "GO-131": "Tag Manager",
        "GO-132": "container",
        "TE-181": "doctype",
        "MB-100": "tap targets",
        "TE-180": "aria-labelledby",
        "TE-174": "@import",
        "SP-109": "text/plain",
        "SP-110": "parser-blocking",
        "TECH-002": "block",
        "GO-145": "privacy",
        "GEO-005": "privacy",
    }

    def test_each_ruled_item_states_what_its_rule_decides(self):
        for item_id, words in self.SAYS.items():
            with self.subTest(item=item_id):
                self.assertIn(words, ITEMS[item_id].get("measures", ""))


if __name__ == "__main__":
    unittest.main()
