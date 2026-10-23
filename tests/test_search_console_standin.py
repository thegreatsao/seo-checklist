"""The census's Search Console stand-in, and why a real audit never meets it (F05-5).

Offline the census had no credentials and every tree it serves is private, so the nine
items over the Search Console scripts answered NEEDS_INPUT or NO_DATA everywhere and
nothing showed any of them able to FAIL. All four scripts get their client from one
function, `gsc_checker.build_service`, and `googleapiclient` is an optional extra no CI job
installs, so the seam is there: in a loopback-only process, with `SEO_SEARCH_CONSOLE_STANDIN`
naming one, `build_service` returns a client speaking the three call chains the scripts use
over Google's own REST paths to the stand-in, before it looks for the extra or opens a key
file. `unindexed/` answers those paths with recorded responses that fail each item,
`indexed/` with ones that pass it. These tests hold the switch, the guard under it, that no
key or token reaches the stand-in, and that each recorded answer is Google's shape.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest import mock
from urllib.parse import quote

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "skills", "seo-checklist", "scripts")
sys.path.insert(0, SCRIPTS)
import harness  # noqa: E402
import gsc_checker  # noqa: E402
from checklist_runner import evaluate  # noqa: E402

CORPUS = os.path.join(ROOT, "tests", "corpus")
# Each stand-in tree, and whether its answers pass the nine items.
TREES = {"unindexed": False, "indexed": True}
PROPERTY = harness.PLACEHOLDER + "/"
SITE = "/webmasters/v3/sites/" + quote(PROPERTY, safe="") + "/"
QUERY_ROUTE = SITE + "searchAnalytics/query"
SITEMAPS_ROUTE = SITE + "sitemaps"
INSPECT_ROUTE = "/v1/urlInspection/index:inspect"

# Google's Search Console API reference (developers.google.com/webmaster-tools/v1, read
# 23 October 2026): each answer's keys, and the enums URL Inspection reports.
QUERY_ROOT = {"rows", "responseAggregationType", "metadata"}
QUERY_ROW = {"keys", "clicks", "impressions", "ctr", "position"}
SITEMAPS_ROOT = {"sitemap"}
SITEMAP = {"path", "lastSubmitted", "isPending", "isSitemapsIndex", "type",
           "lastDownloaded", "warnings", "errors", "contents"}
SITEMAP_CONTENT = {"type", "submitted", "indexed"}
INSPECTION_ROOT = {"inspectionResult"}
INSPECTION = {"inspectionResultLink", "indexStatusResult", "ampResult",
              "mobileUsabilityResult", "richResultsResult"}
INDEX_STATUS = {"sitemap", "referringUrls", "verdict", "coverageState", "robotsTxtState",
                "indexingState", "lastCrawlTime", "pageFetchState", "googleCanonical",
                "userCanonical", "crawledAs"}
ENUMS = {"verdict": {"VERDICT_UNSPECIFIED", "PASS", "PARTIAL", "FAIL", "NEUTRAL"},
         "robotsTxtState": {"ROBOTS_TXT_STATE_UNSPECIFIED", "ALLOWED", "DISALLOWED"},
         "indexingState": {"INDEXING_STATE_UNSPECIFIED", "INDEXING_ALLOWED",
                           "BLOCKED_BY_META_TAG", "BLOCKED_BY_HTTP_HEADER",
                           "BLOCKED_BY_ROBOTS_TXT"},
         "pageFetchState": {"PAGE_FETCH_STATE_UNSPECIFIED", "SUCCESSFUL", "SOFT_404",
                            "BLOCKED_ROBOTS_TXT", "NOT_FOUND", "ACCESS_DENIED",
                            "SERVER_ERROR", "REDIRECT_ERROR", "ACCESS_FORBIDDEN",
                            "BLOCKED_4XX", "INTERNAL_CRAWL_ERROR", "INVALID_URL"},
         "crawledAs": {"CRAWLING_USER_AGENT_UNSPECIFIED", "DESKTOP", "MOBILE"}}


def table(tree: str) -> dict:
    with open(os.path.join(CORPUS, tree, "_answers.json"), encoding="utf-8") as stream:
        return json.load(stream)


def gsc_items() -> list[dict]:
    return [item for item in harness.registry()["items"]
            if (item.get("check") or {}).get("requires") == "gsc"]


class _Asked(Exception):
    pass


class TheStandInIsReadOnlyOffline(unittest.TestCase):
    """`SEO_LOOPBACK_ONLY` is the switch: without it the variable is ignored and the key
    file is read as before (here, by a stand-in for google-auth that records the call)."""

    STANDIN = "http://127.0.0.1:9"
    KEY = "/nowhere/gsc-service-account.json"

    def build(self, env: dict):
        reader = mock.Mock()
        reader.Credentials.from_service_account_file.side_effect = _Asked
        with mock.patch.dict(os.environ, env), \
                mock.patch.object(gsc_checker, "HAS_GSC_DEPS", True), \
                mock.patch.object(gsc_checker, "service_account", reader, create=True):
            try:
                service = gsc_checker.build_service(self.KEY)
            except _Asked:
                service = None
        return service, reader.Credentials.from_service_account_file

    def test_a_loopback_only_process_opens_no_key_file(self):
        service, read = self.build({"SEO_LOOPBACK_ONLY": "1",
                                    "SEO_SEARCH_CONSOLE_STANDIN": self.STANDIN})
        self.assertIsNotNone(service)
        read.assert_not_called()

    def test_the_stand_in_needs_no_extra(self):
        with mock.patch.dict(os.environ, {"SEO_LOOPBACK_ONLY": "1",
                                          "SEO_SEARCH_CONSOLE_STANDIN": self.STANDIN}), \
                mock.patch.object(gsc_checker, "HAS_GSC_DEPS", False):
            self.assertIsNotNone(gsc_checker.build_service(""))

    def test_any_other_process_reads_the_key_whatever_its_environment_says(self):
        service, read = self.build({"SEO_LOOPBACK_ONLY": "",
                                    "SEO_SEARCH_CONSOLE_STANDIN": self.STANDIN})
        self.assertIsNone(service)
        read.assert_called_once()
        self.assertEqual(read.call_args.args[0], self.KEY)

    def test_without_a_stand_in_a_loopback_only_process_reads_the_key(self):
        service, read = self.build({"SEO_LOOPBACK_ONLY": "1",
                                    "SEO_SEARCH_CONSOLE_STANDIN": ""})
        self.assertIsNone(service)
        read.assert_called_once()


class EachCallIsGooglesAndCarriesNoCredential(unittest.TestCase):
    """The three chains the scripts use, each on Google's path and method, with the
    property URL-encoded in the path as Google's client sends it, and nothing a real
    call would carry: no key, no token, no `Authorization`."""

    STANDIN = "http://127.0.0.1:9"

    def call(self, chain) -> tuple[str, str, dict]:
        calls = []

        def fake(method):
            def ask(url, **kwargs):
                calls.append((method, url, kwargs))
                raise _Asked
            return ask

        with mock.patch.dict(os.environ, {"SEO_LOOPBACK_ONLY": "1",
                                          "SEO_SEARCH_CONSOLE_STANDIN": self.STANDIN}), \
                mock.patch.object(gsc_checker, "safe_get", side_effect=fake("GET")), \
                mock.patch.object(gsc_checker, "safe_post", side_effect=fake("POST")), \
                self.assertRaises(gsc_checker.StandInError) as caught:
            chain(gsc_checker.build_service("/nowhere/key.json")).execute()
        self.assertIsInstance(caught.exception.__cause__, _Asked)
        self.assertEqual(len(calls), 1)
        return calls[0]

    def assert_carries_nothing(self, kwargs: dict, expected: set):
        # Exactly these arguments: `params`, `auth` or a header would carry a key or token
        # as surely as the URL would, under any name (review of F05-5).
        self.assertEqual(set(kwargs), expected)

    def test_search_analytics(self):
        body = {"startDate": "2026-09-25", "endDate": "2026-10-23",
                "dimensions": ["query", "page"], "rowLimit": 10}
        method, url, kwargs = self.call(
            lambda s: s.searchanalytics().query(siteUrl=PROPERTY, body=body))
        self.assertEqual((method, url), ("POST", self.STANDIN + QUERY_ROUTE))
        self.assertEqual(kwargs["json"], body)
        self.assert_carries_nothing(kwargs, {"json"})

    def test_the_sitemaps_list(self):
        method, url, kwargs = self.call(lambda s: s.sitemaps().list(siteUrl=PROPERTY))
        self.assertEqual((method, url), ("GET", self.STANDIN + SITEMAPS_ROUTE))
        self.assert_carries_nothing(kwargs, set())

    def test_url_inspection(self):
        body = {"inspectionUrl": PROPERTY, "siteUrl": PROPERTY, "languageCode": "en-US"}
        method, url, kwargs = self.call(
            lambda s: s.urlInspection().index().inspect(body=body))
        self.assertEqual((method, url), ("POST", self.STANDIN + INSPECT_ROUTE))
        self.assertEqual(kwargs["json"], body)
        self.assert_carries_nothing(kwargs, {"json"})

    def test_a_stand_in_that_is_not_this_machine_is_refused_not_asked(self):
        with mock.patch.dict(os.environ, {"SEO_LOOPBACK_ONLY": "1",
                                          "SEO_SEARCH_CONSOLE_STANDIN":
                                              "https://gsc.example.test"}):
            service = gsc_checker.build_service("/nowhere/key.json")
            with self.assertRaises(gsc_checker.StandInError) as caught:
                service.sitemaps().list(siteUrl=PROPERTY).execute()
        self.assertIn("loopback-only", str(caught.exception))
        self.assertIn("gsc.example.test", str(caught.exception))


class AnAnswerTheStandInCannotGiveIsTheServices(unittest.TestCase):
    """A stand-in that answers with something other than JSON is the service failing, as
    `googleapiclient`'s `HttpError` would be, never the operator's key file: requests'
    `JSONDecodeError` is an `OSError`, which every caller reads as `input` (review of
    F05-5)."""

    def test_a_body_that_is_not_json_is_a_stand_in_error(self):
        import requests
        answer = mock.Mock(status_code=200)
        answer.json.side_effect = requests.JSONDecodeError("Expecting value", "<html>", 0)
        with mock.patch.dict(os.environ, {"SEO_LOOPBACK_ONLY": "1",
                                          "SEO_SEARCH_CONSOLE_STANDIN": "http://127.0.0.1:9"}), \
                mock.patch.object(gsc_checker, "safe_get", return_value=answer):
            service = gsc_checker.build_service("/nowhere/key.json")
            with self.assertRaises(gsc_checker.StandInError):
                service.sitemaps().list(siteUrl=PROPERTY).execute()


class TheRecordedAnswersAreGooglesShape(unittest.TestCase):
    """Every key each recorded answer carries is one Google defines, spelled as Google
    spells it, so a verdict on either tree is the parser's on a real shape."""

    def answers(self, tree: str, route: str) -> list[dict]:
        answer = table(tree)[route]
        return [json.loads(a["body"]) for a in (answer, answer.get("else")) if a]

    def test_search_analytics_rows(self):
        for tree in TREES:
            for data in self.answers(tree, QUERY_ROUTE):
                with self.subTest(tree=tree):
                    self.assertLessEqual(set(data), QUERY_ROOT)
                    widths = {len(row["keys"]) for row in data["rows"]}
                    self.assertEqual(len(widths), 1)
                    for row in data["rows"]:
                        self.assertLessEqual(set(row), QUERY_ROW)
                        self.assertLessEqual(row["ctr"], 1.0)

    def test_the_two_dimension_sets_are_told_apart_by_the_request(self):
        for tree in TREES:
            with self.subTest(tree=tree):
                answer = table(tree)[QUERY_ROUTE]
                self.assertEqual(answer["when"], {"dimensions": ["query", "page"]})
                both, pages = (json.loads(a["body"])["rows"] for a in (answer, answer["else"]))
                self.assertEqual({len(r["keys"]) for r in both}, {2})
                self.assertEqual({len(r["keys"]) for r in pages}, {1})

    def test_the_page_rows_are_the_query_rows_summed(self):
        """One property's data seen two ways: per page, the clicks and impressions of its
        queries summed and their positions averaged by impressions (review of F05-5)."""
        for tree in TREES:
            with self.subTest(tree=tree):
                answer = table(tree)[QUERY_ROUTE]
                both, pages = (json.loads(a["body"])["rows"] for a in (answer, answer["else"]))
                for page in pages:
                    rows = [r for r in both if r["keys"][1] == page["keys"][0]]
                    impressions = sum(r["impressions"] for r in rows)
                    self.assertEqual(page["clicks"], sum(r["clicks"] for r in rows))
                    self.assertEqual(page["impressions"], impressions)
                    self.assertAlmostEqual(
                        page["position"],
                        sum(r["position"] * r["impressions"] for r in rows) / impressions,
                        places=1)

    def test_the_sitemaps_list(self):
        for tree in TREES:
            for data in self.answers(tree, SITEMAPS_ROUTE):
                with self.subTest(tree=tree):
                    self.assertLessEqual(set(data), SITEMAPS_ROOT)
                    for sitemap in data["sitemap"]:
                        self.assertLessEqual(set(sitemap), SITEMAP)
                        # int64 travels as a JSON string in Google's discovery APIs.
                        self.assertIsInstance(sitemap["errors"], str)
                        self.assertIsInstance(sitemap["warnings"], str)
                        for content in sitemap["contents"]:
                            self.assertLessEqual(set(content), SITEMAP_CONTENT)

    def test_url_inspection(self):
        for tree in TREES:
            for data in self.answers(tree, INSPECT_ROUTE):
                with self.subTest(tree=tree):
                    self.assertLessEqual(set(data), INSPECTION_ROOT)
                    self.assertLessEqual(set(data["inspectionResult"]), INSPECTION)
                    status = data["inspectionResult"]["indexStatusResult"]
                    self.assertLessEqual(set(status), INDEX_STATUS)
                    for field, values in ENUMS.items():
                        self.assertIn(status[field], values, field)

    def test_the_nine_items_are_the_ones_this_stand_in_answers(self):
        self.assertEqual(sorted(item["id"] for item in gsc_items()),
                         ["CI-002", "CI-010", "GO-134", "GO-135", "GO-137", "GO-139",
                          "KW-070", "KW-071", "MS-023"])


class TheTreesServeThem(unittest.TestCase):
    """End to end: each tree served on loopback, each script started as the runner starts
    it, with the registry's own arguments and a credentials path that does not exist,
    and each of the nine items read through the registry's own assertion."""

    def outputs(self, tree: str) -> dict[str, dict]:
        out = {}
        with tempfile.TemporaryDirectory() as workdir:
            site = harness._Site(os.path.join(CORPUS, tree), os.path.join(workdir, tree))
            try:
                ctx = {"url": site.base + "/", "gsc_property": site.base + "/",
                       "gsc_credentials": os.path.join(workdir, "no-key.json")}
                env = harness.offline_env(SEO_SEARCH_CONSOLE_STANDIN=site.base)
                for item in gsc_items():
                    script = item["check"]["script"]
                    args = [a.format(**ctx) for a in item["check"]["args"]]
                    if (script, *args) in out:
                        continue
                    proc = harness.spawn(
                        [sys.executable, os.path.join(SCRIPTS, script), *args, "--json"],
                        env=env, timeout=120)
                    out[(script, *args)] = json.loads(proc.stdout)
            finally:
                site.stop()
        return out

    def test_each_item_fails_on_unindexed_and_passes_on_indexed(self):
        for tree, passes in TREES.items():
            outputs = self.outputs(tree)
            for item in gsc_items():
                check = item["check"]
                key = next(k for k in outputs if k[0] == check["script"])
                with self.subTest(tree=tree, item=item["id"]):
                    out = outputs[key]
                    self.assertFalse(out.get("error"), out.get("error"))
                    if "applies_when" in check:
                        self.assertIs(evaluate(check["applies_when"], out)[0], True)
                    self.assertIs(evaluate(check["assert"], out)[0], passes)
                    if not passes and "warn" in check:
                        # A FAIL, not the WARN band a count of three or fewer reads as.
                        self.assertIs(evaluate(check["warn"], out)[0], False)


if __name__ == "__main__":
    unittest.main()
