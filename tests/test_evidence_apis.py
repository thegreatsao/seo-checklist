"""The five evidence scripts that talk to somebody else, and one that reads an export.

`test_evidence_scripts.py` serves a real origin, because that is better than a stub
wherever the thing being tested is a request. These five cannot be served: three ask
Search Console, one asks the W3C validator, one reads a file a human downloads from
the Search Console UI, and one needs a secret. So the *one* call that leaves the
machine is stubbed, in the module that makes it, and everything on this side of that
call runs unmodified.

That is a weaker test and it is the honest limit rather than a shortcut: nothing here
can prove the plugin reads Google's real response shape correctly, only that it reads
the shape it was written for. What these tests do cover is every line that turns a
response into the field a registry rule asserts on — which is where the last three
defects in this family were.

Offline: no credentials, no network, no API key. `test_evidence_scripts.script_env`
clears them for the subprocess runs; here the stub is the boundary.
"""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(ROOT, "skills", "seo-checklist")
SCRIPTS = os.path.join(SKILL, "scripts")
REGISTRY = os.path.join(SKILL, "resources", "config", "checklist.json")
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from checklist_runner import (  # noqa: E402
    FAIL,
    GSC_CREDENTIALS_ABSENT,
    NA,
    NEEDS_INPUT,
    NO_DATA,
    PASS,
    WARN,
    build_plan,
    evaluate,
    input_truncated,
    passes_by_absence,
)

with open(REGISTRY, encoding="utf-8") as f:
    ITEMS = {i["id"]: i for i in json.load(f)["items"]}


def verdict(item_id: str, output: dict) -> str:
    check = ITEMS[item_id]["check"]
    applies = check.get("applies_when")
    if applies:
        applies_ok, _ = evaluate(applies, output)
        if applies_ok is None:
            return NO_DATA
        if not applies_ok:
            return NA
    ok, _ = evaluate(check["assert"], output)
    if ok is None:
        return NO_DATA
    if ok and passes_by_absence(check["assert"]) and input_truncated(output):
        return NO_DATA
    if ok:
        return PASS
    warn = check.get("warn")
    if warn and evaluate(warn, output)[0]:
        return WARN
    return FAIL


def verdicts(items, output: dict) -> dict:
    """Every item's verdict at once, so a scenario can pin all of them.

    The GSC scenarios used to accept `PASS` **or** `NO_DATA` on their positive
    fixtures and "at least one of the group failed" on their negative ones. Both are
    satisfied by a rule that has stopped deciding anything: a path renamed out from
    under an assertion reports `NO_DATA` forever, which is the exact failure this
    file's docstring says the last three defects in this family were. A full map
    fails on the difference between deciding and not.
    """
    return {i["id"]: verdict(i["id"], output) for i in items}


def tmpfile(name: str, content) -> str:
    path = os.path.join(tempfile.mkdtemp(), name)
    mode = "wb" if isinstance(content, bytes) else "w"
    with open(path, mode, **({} if isinstance(content, bytes)
                             else {"encoding": "utf-8"})) as f:
        f.write(content)
    return path


# ---------------------------------------------------------------------------
# The Search Console Links export: a file, not an API
# ---------------------------------------------------------------------------

class LinksExport(unittest.TestCase):
    """BL-083 `targets.broken_count`, BL-084 concentration, and BL-086/087.

    The Links report has no API — a human clicks Export in the UI — which is why
    these three items are `NO_DATA` on every run that does not supply the file, and
    why the contract pair exempts them. The reader itself needs no network at all, so
    there is no excuse for it to be untested.
    """

    SITES = ("Top linking sites,Linking pages\n"
             "partner.example,30\n"
             "directory.example,26\n"
             "forum.example,9\n"
             "blog.example,4\n"
             "news.example,3\n")

    def setUp(self):
        import gsc_links_csv
        self.mod = gsc_links_csv
        self.saved_fetch = gsc_links_csv.seo_common.fetch_url
        self.calls = []

        def fetch(url, **kwargs):
            self.calls.append((url, kwargs))
            return {"status": 200, "url": url, "redirect_chain": [],
                    "error": None, "error_kind": None}

        gsc_links_csv.seo_common.fetch_url = fetch

    def tearDown(self):
        self.mod.seo_common.fetch_url = self.saved_fetch

    def analyze(self, name="top-linking-sites.csv", content=None, site=""):
        return self.mod.analyze(tmpfile(name, content or self.SITES), site)

    def directory(self, pages: str | None = None) -> str:
        folder = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, folder, True)
        with open(os.path.join(folder, "top-linking-sites.csv"), "w",
                  encoding="utf-8") as stream:
            stream.write(self.SITES)
        if pages is not None:
            with open(os.path.join(folder, "top-linked-pages.csv"), "w",
                      encoding="utf-8") as stream:
                stream.write("Target page,Incoming links,Linking sites\n" + pages)
        return folder

    def check(self, pages: str, site="https://example.test/") -> dict:
        return self.mod.analyze(self.directory(pages), site, check_targets=True)

    def responses(self, mapping):
        def fetch(url, **kwargs):
            self.calls.append((url, kwargs))
            return mapping[url]
        self.mod.seo_common.fetch_url = fetch

    def test_a_page_that_refuses_head_and_serves_get_is_not_a_broken_backlink(self):
        """`fetch_url` sets no error on a response it received, so the fallback
        inherited from `external_link_quality.py` — GET only when a 403/405 *also*
        carried an error — never fired, and a live page behind a server that refuses
        HEAD was a dead backlink. Each refusal status, then the GET that settles it."""
        for refused in (403, 405, 501):
            with self.subTest(head=refused):
                methods = []

                def fetch(url, method="GET", methods=methods, refused=refused,
                          **kwargs):
                    methods.append(method)
                    return {"status": refused if method == "HEAD" else 200,
                            "url": url, "redirect_chain": [],
                            "error": None, "error_kind": None}

                self.mod.seo_common.fetch_url = fetch
                out = self.check("https://example.test/live,5,2\n")
                self.assertEqual(methods, ["HEAD", "GET"])
                self.assertEqual(out["targets"]["broken_count"], 0)
                self.assertEqual(verdict("BL-083", out), PASS)

    def test_a_page_that_refuses_head_and_answers_get_with_404_is_broken(self):
        def fetch(url, method="GET", **kwargs):
            return {"status": 405 if method == "HEAD" else 404, "url": url,
                    "redirect_chain": [], "error": None, "error_kind": None}

        self.mod.seo_common.fetch_url = fetch
        out = self.check("https://example.test/gone,5,2\n")
        self.assertEqual(out["targets"]["broken"][0]["status"], 404)
        self.assertEqual(verdict("BL-083", out), FAIL)

    def test_a_spread_link_profile_passes_all_three(self):
        out = self.analyze()
        self.assertEqual(out["total_links"], 72)
        self.assertEqual(out["linking_domains"], 5)
        self.assertEqual(verdict("BL-086", out), PASS)
        self.assertEqual(verdict("BL-087", out), PASS)
        self.assertEqual(verdict("BL-084", out), PASS)

    def test_one_domain_supplying_most_of_the_links_is_a_concentration(self):
        out = self.analyze(content="Top linking sites,Linking pages\n"
                                   "one.example,900\n"
                                   "two.example,10\n")
        self.assertGreater(out["concentration"]["top1_share_pct"], 50)
        self.assertEqual(verdict("BL-084", out), FAIL)
        self.assertEqual(verdict("BL-087", out), FAIL)

    def test_a_header_row_is_dropped_rather_than_counted_as_a_domain(self):
        """The shape check that lets this work in any language: Google localises the
        export, so a row is a header when its second column is not a number, not when
        it says "Top linking sites"."""
        out = self.analyze(content="Сайты со ссылками,Связывающие страницы\n"
                                   "partner.example,42\n"
                                   "directory.example,18\n")
        self.assertEqual(out["linking_domains"], 2)
        self.assertEqual(out["total_links"], 60)

    def test_a_zip_of_sheets_is_read_the_same_way(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("top-linking-sites.csv", self.SITES)
            archive.writestr("top-linking-text.csv",
                             "Link text,Links\nfixture bakery,30\nsourdough,12\n")
        out = self.analyze("example.com-Links.zip", buffer.getvalue())
        self.assertEqual(out["linking_domains"], 5)
        self.assertTrue(out["anchors"])

    def test_an_empty_export_is_undecided_rather_than_zero_links(self):
        """`total_links: 0` from an empty file would read as "this site has no
        backlinks", which is a verdict. The absence of data is not that."""
        out = self.analyze(content="Top linking sites,Linking pages\n")
        self.assertEqual(verdict("BL-086", out), FAIL)
        self.assertIsNone(out["concentration"]["top1_share_pct"])
        self.assertEqual(verdict("BL-084", out), NO_DATA)

    def test_directory_targets_that_all_answer_are_a_backlink_pass(self):
        out = self.check("https://example.test/,9,4\n"
                         "https://example.test/about,3,2\n")
        self.assertEqual(out["targets"]["checked"], 2)
        self.assertEqual(verdict("BL-083", out), PASS)

    def test_a_404_target_fails_with_its_incoming_link_count(self):
        target = "https://example.test/gone"
        self.responses({target: {"status": 404, "url": target,
                                 "redirect_chain": [], "error": None,
                                 "error_kind": None}})
        out = self.check(f"{target},17,4\n")
        self.assertEqual(verdict("BL-083", out), FAIL)
        self.assertEqual(out["targets"]["broken"], [{
            "url": target, "status": 404, "error_kind": None,
            "incoming_links": 17,
        }])

    def test_a_redirect_is_the_fix_not_a_failure(self):
        target = "https://example.test/old"
        final = "https://example.test/new"
        self.responses({target: {"status": 200, "url": final,
                                 "redirect_chain": [final], "error": None,
                                 "error_kind": None}})
        out = self.check(f"{target},8,3\n")
        self.assertEqual(verdict("BL-083", out), PASS)
        self.assertEqual(out["targets"]["redirected"],
                         [{"url": target, "final_url": final}])

    def test_a_timeout_is_unchecked_and_withholds_only_a_clean_pass(self):
        slow = "https://example.test/slow"
        gone = "https://example.test/gone"
        timeout = {"status": None, "url": slow, "redirect_chain": [],
                   "error": "late", "error_kind": "timeout"}
        self.responses({slow: timeout})
        out = self.check(f"{slow},8,3\n")
        self.assertEqual(out["targets"]["broken_count"], 0)
        self.assertEqual(len(out["targets"]["unchecked"]), 1)
        self.assertTrue(out["truncated"])
        self.assertEqual(verdict("BL-083", out), NO_DATA)

        self.calls.clear()
        self.responses({slow: timeout,
                        gone: {"status": 404, "url": gone,
                               "redirect_chain": [], "error": None,
                               "error_kind": None}})
        out = self.check(f"{slow},8,3\n{gone},4,1\n")
        self.assertEqual(verdict("BL-083", out), FAIL)

    def test_dead_dns_is_broken(self):
        target = "https://example.test/dead"
        self.responses({target: {"status": None, "url": target,
                                 "redirect_chain": [], "error": "no address",
                                 "error_kind": "unresolved"}})
        out = self.check(f"{target},5,2\n")
        self.assertEqual(out["targets"]["broken_count"], 1)
        self.assertEqual(verdict("BL-083", out), FAIL)

    def test_off_host_rows_are_not_requested(self):
        out = self.check("https://elsewhere.test/page,9,4\n"
                         "https://example.test/about,3,2\n")
        self.assertEqual(out["targets"]["off_host"], 1)
        self.assertEqual(out["targets"]["checked"], 1)
        self.assertEqual([call[0] for call in self.calls],
                         ["https://example.test/about"])

    def test_only_the_first_hundred_targets_are_requested(self):
        rows = "".join(
            f"https://example.test/{index},{200-index},1\n"
            for index in range(self.mod.MAX_TARGETS + 2))
        out = self.check(rows)
        self.assertEqual(len(self.calls), self.mod.MAX_TARGETS)
        self.assertEqual(self.calls[0][0], "https://example.test/0")
        self.assertEqual(self.calls[-1][0], "https://example.test/99")
        self.assertTrue(out["truncated"])
        self.assertIn("per-run cap", out["truncated_reason"])

    def test_no_pages_sheet_is_not_applicable_and_missing_input_is_no_data(self):
        out = self.mod.analyze(self.directory(), "https://example.test/",
                               check_targets=True)
        self.assertEqual(out["targets"]["linked_pages"], 0)
        self.assertEqual(verdict("BL-083", out), NA)

        missing = self.mod.analyze(os.path.join(tempfile.gettempdir(),
                                                "absent-links-export.csv"),
                                   "https://example.test/", check_targets=True)
        self.assertNotIn("targets", missing)
        self.assertEqual(missing["error_kind"], "input")
        self.assertEqual(verdict("BL-083", missing), NO_DATA)

    def test_without_the_flag_nothing_is_requested_and_old_verdicts_hold(self):
        out = self.mod.analyze(
            self.directory("https://example.test/,9,4\n"),
            "https://example.test/")
        self.assertNotIn("targets", out)
        self.assertEqual(self.calls, [])
        self.assertEqual(verdicts(
            [ITEMS[item] for item in ("BL-084", "BL-086", "BL-087")], out),
            {"BL-084": PASS, "BL-086": PASS, "BL-087": PASS})


# ---------------------------------------------------------------------------
# The W3C validator
# ---------------------------------------------------------------------------

class HtmlValidator(unittest.TestCase):
    """CI-017 checks served HTML; TE-181 checks the rendered DOM.

    The renderer and both Nu request methods are stubbed. Everything that turns a
    response into counts and a registry verdict is real.
    """

    def setUp(self):
        import html_validator
        self.mod = html_validator
        self.saved_get = html_validator.requests.get
        self.saved_post = html_validator.requests.post
        self.get_calls = []
        self.post_calls = []
        self.artifacts = tempfile.TemporaryDirectory()

        def unexpected(*_args, **_kwargs):
            raise AssertionError("an unstubbed Nu request was attempted")

        html_validator.requests.get = unexpected
        html_validator.requests.post = unexpected

    def tearDown(self):
        self.mod.requests.get = self.saved_get
        self.mod.requests.post = self.saved_post
        self.artifacts.cleanup()

    def serve(self, messages, status=200, method="get"):
        class Response:
            status_code = status
            headers = {"Content-Type": "application/json"}
            text = json.dumps({"messages": messages})

            def json(self):
                return {"messages": messages}

        calls = self.get_calls if method == "get" else self.post_calls

        def answer(*args, **kwargs):
            calls.append((args, kwargs))
            return Response()

        setattr(self.mod.requests, method, answer)

    def artifact(self, payload, name="rendered.json"):
        """Write a rendered-page artifact and return its path.

        `payload` is written verbatim so a test can supply one that recorded
        measurements but no document, which is the case TE-181 must not pass.
        """
        path = os.path.join(self.artifacts.name, name)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        return path

    def render(self, html="<!doctype html><html><body></body></html>"):
        return self.artifact({"url": "https://example.com/",
                              "viewport": {"width": 390, "height": 844},
                              "html": html})

    def test_a_clean_document_reports_no_errors(self):
        self.serve([])
        out = self.mod.validate("https://example.com/")
        self.assertEqual(out["source"], "served")
        self.assertEqual(out["summary"]["errors"], 0)
        self.assertEqual(verdict("CI-017", out), PASS)
        self.assertEqual(len(self.get_calls), 1)
        self.assertEqual(self.post_calls, [])

    def test_errors_and_warnings_are_counted_apart(self):
        """Apart, because one of these two items reads each. Collapsing them would
        make a document with fifty warnings and no errors indistinguishable from a
        broken one."""
        self.serve([
            {"type": "error", "message": "Stray end tag div.", "lastLine": 12},
            {"type": "error", "message": "Duplicate ID footer.", "lastLine": 40},
            {"type": "warning", "message": "Empty heading.", "lastLine": 7},
        ])
        out = self.mod.validate("https://example.com/")
        self.assertEqual(out["summary"]["errors"], 2)
        self.assertEqual(out["summary"]["warnings"], 1)
        self.assertEqual(verdict("CI-017", out), FAIL)

    def test_a_validator_outage_is_undecided_rather_than_clean(self):
        """The failure this family keeps producing: a service that answers with
        nothing, read as a site with nothing wrong. `errors` must be absent, not 0.
        """
        def boom(*a, **k):
            raise self.mod.requests.RequestException("503 Service Unavailable")
        self.mod.requests.get = boom
        out = self.mod.validate("https://example.com/")
        self.assertTrue(out.get("error"))
        self.assertEqual(verdict("CI-017", out), NO_DATA)

    def test_the_validator_failing_to_fetch_the_page_is_not_a_clean_document(self):
        """The same failure one step further in, and it needs no outage to happen.

        Nu answers 200 with a `non-document-error` when *it* could not read the URL —
        a 403 aimed at its user agent, a timeout, a TLS problem, a host it cannot
        reach. That is not a document error, so `errors` was 0 and two items reported
        "your HTML validates" about a page the validator never saw. Found by pointing
        the dead-origin sweep at a real validator by accident, which is also why that
        sweep now leaves the API scripts alone.
        """
        self.serve([{"type": "non-document-error", "subType": "io",
                     "message": "HTTP resource not retrievable. "
                                "The HTTP status from the remote server was: 403."}])
        out = self.mod.validate("https://example.com/")
        self.assertIn("could not read the page", out.get("error") or "")
        self.assertEqual(out["summary"], {})
        self.assertEqual(verdict("CI-017", out), NO_DATA)

    def test_a_warning_alongside_a_fetch_problem_is_still_read(self):
        """Only an answer that is *entirely* non-document errors means the document
        was not seen. A page that validated and also produced one odd transport
        message is a page that validated."""
        self.serve([{"type": "non-document-error", "subType": "warning",
                     "message": "The Content-Type was text/html with no charset."},
                    {"type": "error", "message": "Stray end tag div.", "lastLine": 3}])
        out = self.mod.validate("https://example.com/")
        self.assertIsNone(out.get("error"))
        self.assertEqual(out["summary"]["errors"], 1)

    def test_a_clean_rendered_dom_posts_the_document_and_passes(self):
        document = "<!doctype html><html><body><p>rendered</p></body></html>"
        path = self.render(document)
        self.serve([], method="post")

        out = self.mod.validate("https://example.com/", rendered_json=path)

        self.assertEqual(out["source"], "rendered")
        self.assertIsNone(out["render_error"])
        self.assertEqual(out["summary"]["errors"], 0)
        self.assertEqual(verdict("TE-181", out), PASS)
        self.assertEqual(self.get_calls, [])
        self.assertEqual(len(self.post_calls), 1)
        args, kwargs = self.post_calls[0]
        self.assertEqual(args, ("https://validator.w3.org/nu/?out=json",))
        self.assertEqual(kwargs["data"], document.encode("utf-8"))
        self.assertEqual(kwargs["headers"]["Content-Type"],
                         "text/html; charset=utf-8")

    def test_an_invalid_rendered_dom_fails(self):
        path = self.render("<html><body><p></body></html>")
        self.serve([{"type": "error", "message": "Unclosed element p."}],
                   method="post")

        out = self.mod.validate("https://example.com/", rendered_json=path)

        self.assertEqual(out["summary"]["errors"], 1)
        self.assertEqual(verdict("TE-181", out), FAIL)

    def test_an_artifact_without_a_document_is_no_data_and_never_calls_nu(self):
        """The shape that matters: a trace that recorded measurements but not the DOM.

        `summary.errors == 0` here would claim the rendered document is valid when no
        rendered document exists — the defect MB-105 shipped with for two releases.
        """
        path = self.artifact({"url": "https://example.com/",
                              "viewport": {"width": 390, "height": 844},
                              "tap_targets_below_48px": 0})

        out = self.mod.validate("https://example.com/", rendered_json=path)

        self.assertNotIn("summary", out)
        self.assertIn("carries no `html`", out["render_error"])
        self.assertEqual(verdict("TE-181", out), NO_DATA)
        self.assertEqual(self.get_calls, [])
        self.assertEqual(self.post_calls, [])

    def test_an_unreadable_or_malformed_artifact_is_no_data_with_the_reason(self):
        missing = os.path.join(self.artifacts.name, "not-there.json")
        malformed = os.path.join(self.artifacts.name, "bad.json")
        with open(malformed, "w", encoding="utf-8") as handle:
            handle.write("{not json")
        listy = self.artifact(["not", "an", "object"], name="listy.json")

        for path, expected in ((missing, "could not be read"),
                               (malformed, "is not JSON"),
                               (listy, "not an object")):
            with self.subTest(os.path.basename(path)):
                out = self.mod.validate("https://example.com/", rendered_json=path)

                self.assertNotIn("summary", out)
                self.assertIn(expected, out["render_error"])
                self.assertEqual(verdict("TE-181", out), NO_DATA)
                self.assertEqual(self.get_calls, [])
                self.assertEqual(self.post_calls, [])

    def test_an_empty_document_in_the_artifact_is_not_a_document(self):
        for blank in ("", "   \n"):
            with self.subTest(repr(blank)):
                path = self.render(blank)
                out = self.mod.validate("https://example.com/", rendered_json=path)
                self.assertNotIn("summary", out)
                self.assertEqual(verdict("TE-181", out), NO_DATA)
                self.assertEqual(self.post_calls, [])

    def test_validating_the_served_page_never_reads_an_artifact(self):
        """CI-017 must be untouched by any of this."""
        self.serve([])
        out = self.mod.validate("https://example.com/")
        self.assertEqual(out["source"], "served")
        self.assertIsNone(out["render_error"])
        self.assertEqual(verdict("CI-017", out), PASS)
        self.assertEqual(self.post_calls, [])
        self.assertEqual(len(self.get_calls), 1)


# ---------------------------------------------------------------------------
# Search Console
# ---------------------------------------------------------------------------

class _Query:
    """The two call chains these scripts use, and nothing else.

    `service.searchanalytics().query(...).execute()` and
    `service.urlInspection().index().inspect(...).execute()`. Written out rather than
    produced by a mocking library so that a change in either chain fails here loudly
    instead of being absorbed by an auto-generated attribute.
    """

    def __init__(self, rows=None, inspection=None, sitemaps=None, inspections=None):
        self._rows = rows or []
        self._inspection = inspection or {}
        self._inspections = inspections
        self._sitemaps = sitemaps or {}
        self.calls = []

    # searchanalytics
    def searchanalytics(self):
        return self

    def query(self, siteUrl=None, body=None):  # noqa: N803 - Google's spelling
        self.calls.append(("query", siteUrl, body))
        return _Executable({"rows": self._rows})

    # urlInspection
    def urlInspection(self):  # noqa: N802 - Google's spelling
        return self

    def index(self):
        return self

    def inspect(self, body=None):
        self.calls.append(("inspect", body))
        payload = (self._inspections.get(body["inspectionUrl"], {})
                   if self._inspections is not None else self._inspection)
        return _Executable(payload)

    # sitemaps
    def sitemaps(self):
        return self

    def list(self, siteUrl=None):  # noqa: N803
        return _Executable(self._sitemaps)


class _Executable:
    def __init__(self, payload):
        self.payload = payload

    def execute(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class SitemapReconciliation(unittest.TestCase):
    """GO-137's two-way Search Console reconciliation and runner routing."""

    SITE = "https://example.com/"
    PROP = "sc-domain:example.com"

    def setUp(self):
        import gsc_sitemap_reconcile
        self.mod = gsc_sitemap_reconcile
        self.saved_service = self.mod.build_service
        self.saved_load = self.mod.load_sitemap_urls
        self.saved_discover = self.mod.discover_sitemap_urls

    def tearDown(self):
        self.mod.build_service = self.saved_service
        self.mod.load_sitemap_urls = self.saved_load
        self.mod.discover_sitemap_urls = self.saved_discover

    @staticmethod
    def inspection(state):
        return {"inspectionResult": {"indexStatusResult": {
            "coverageState": state,
        }}}

    @staticmethod
    def rows(*pages):
        return [{"keys": [page], "clicks": 1, "impressions": 2,
                 "ctr": 0.5, "position": 1.0} for page in pages]

    def reconcile(self, urls, states=None, rows=None, submitted=True,
                  errors=None, discovered=None, unvisited=None, max_urls=100):
        inspections = {
            url: (state if isinstance(state, Exception)
                  else self.inspection(state))
            for url, state in (states or {}).items()
        }
        service = _Query(
            rows=rows or [],
            inspections=inspections,
            sitemaps={"sitemap": ([{"path": "https://example.com/sitemap.xml"}]
                                   if submitted else [])},
        )
        self.mod.build_service = lambda *a, **k: service
        self.mod.discover_sitemap_urls = lambda *a, **k: list(discovered or [])
        self.mod.load_sitemap_urls = lambda *a, **k: {
            "urls": list(urls),
            "sitemaps_checked": list(k.get("sitemap_urls") or []),
            "errors": list(errors or []),
            "unvisited": list(unvisited or []),
        }
        out = self.mod.analyze(self.SITE, self.PROP, "/dev/null", max_urls, 28)
        return out, service

    def test_indexed_sitemap_matching_impression_pages_passes(self):
        urls = [self.SITE, self.SITE + "about"]
        out, _ = self.reconcile(
            urls,
            states={url: "Submitted and indexed" for url in urls},
            rows=self.rows(*urls),
        )
        self.assertEqual(out["summary"]["unreconciled"], 0)
        self.assertEqual(verdict("GO-137", out), PASS)

    def test_a_sitemap_url_google_has_not_indexed_fails(self):
        urls = [self.SITE, self.SITE + "waiting"]
        out, _ = self.reconcile(urls, states={
            urls[0]: "Submitted and indexed",
            urls[1]: "Crawled - currently not indexed",
        }, rows=self.rows(*urls))
        self.assertEqual(out["summary"]["not_indexed"], 1)
        self.assertEqual(out["not_indexed"][0]["url"], urls[1])
        self.assertEqual(verdict("GO-137", out), FAIL)

    def test_an_indexed_same_host_page_missing_from_the_sitemap_fails(self):
        urls = [self.SITE]
        missing = self.SITE + "missing"
        out, _ = self.reconcile(
            urls,
            states={urls[0]: "Submitted and indexed"},
            rows=self.rows(urls[0], missing, "https://other.example/page"),
        )
        self.assertEqual(out["summary"]["indexed_not_in_sitemap"], 1)
        self.assertEqual(out["indexed_not_in_sitemap"], [missing])
        self.assertEqual(verdict("GO-137", out), FAIL)

    def test_no_submitted_or_discovered_sitemap_is_not_applicable(self):
        out, _ = self.reconcile([], submitted=False, discovered=[])
        self.assertEqual(out["summary"]["sitemap_urls"], 0)
        self.assertEqual(verdict("GO-137", out), NA)

    def test_probed_names_that_are_absent_are_not_sitemap_errors(self):
        candidates = [
            (self.SITE + "sitemap.xml", "probed"),
            (self.SITE + "sitemap_index.xml", "probed"),
        ]
        out, _ = self.reconcile(
            [], submitted=False, discovered=candidates,
            errors=[{"url": url, "status": 404} for url, _ in candidates],
        )
        self.assertEqual(out["sitemap_errors"], [])
        self.assertEqual(out["summary"]["sitemap_urls"], 0)
        self.assertEqual(verdict("GO-137", out), NA)

    def test_probed_misses_do_not_disable_the_reverse_comparison(self):
        sitemap = self.SITE + "sitemap.xml"
        probes = [(sitemap, "probed"),
                  (self.SITE + "sitemap_index.xml", "probed"),
                  (self.SITE + "sitemap-index.xml", "probed")]
        listed = self.SITE + "listed"
        missing = self.SITE + "missing"
        out, _ = self.reconcile(
            [listed], submitted=False, discovered=probes,
            states={listed: "Submitted and indexed"},
            rows=self.rows(listed, missing),
            errors=[{"url": url, "status": 404} for url, _ in probes[1:]],
        )
        self.assertEqual(out["sitemap_errors"], [])
        self.assertTrue(out["summary"]["indexed_not_in_sitemap_counted"])
        self.assertEqual(out["summary"]["unreconciled"], 1)
        self.assertEqual(verdict("GO-137", out), FAIL)

    def test_an_unreadable_submitted_sitemap_is_no_data(self):
        sitemap = "https://example.com/sitemap.xml"
        out, _ = self.reconcile(
            [], errors=[{"url": sitemap, "error": "connection reset"}])
        self.assertNotIn("summary", out)
        self.assertEqual(out["error_kind"], "unread")
        self.assertEqual(verdict("GO-137", out), NO_DATA)

    def test_a_partial_sitemap_read_withholds_a_reverse_direction_failure(self):
        listed = self.SITE + "listed"
        missing = self.SITE + "missing"
        out, _ = self.reconcile(
            [listed], states={listed: "Submitted and indexed"},
            rows=self.rows(listed, missing),
            errors=[{"url": self.SITE + "second.xml", "status": 503}],
        )
        self.assertEqual(out["summary"]["indexed_not_in_sitemap"], 1)
        self.assertFalse(out["summary"]["indexed_not_in_sitemap_counted"])
        self.assertEqual(out["summary"]["unreconciled"], 0)
        self.assertTrue(out["truncated"])
        self.assertIn("could not be read", out["truncated_reason"])
        self.assertEqual(verdict("GO-137", out), NO_DATA)

    def test_a_partial_sitemap_read_still_counts_not_indexed_urls(self):
        listed = self.SITE + "listed"
        missing = self.SITE + "missing"
        out, _ = self.reconcile(
            [listed], states={listed: "Crawled - currently not indexed"},
            rows=self.rows(listed, missing),
            errors=[{"url": self.SITE + "second.xml", "status": 503}],
        )
        self.assertEqual(out["summary"]["unreconciled"], 1)
        self.assertFalse(out["summary"]["indexed_not_in_sitemap_counted"])
        self.assertEqual(verdict("GO-137", out), FAIL)

    def test_an_unvisited_sitemap_withholds_the_reverse_direction(self):
        listed = self.SITE + "listed"
        missing = self.SITE + "missing"
        unread = [self.SITE + "child-a.xml", self.SITE + "child-b.xml"]
        out, _ = self.reconcile(
            [listed], states={listed: "Submitted and indexed"},
            rows=self.rows(listed, missing), unvisited=unread,
        )
        self.assertEqual(out["summary"]["indexed_not_in_sitemap"], 1)
        self.assertFalse(out["summary"]["indexed_not_in_sitemap_counted"])
        self.assertEqual(out["summary"]["unreconciled"], 0)
        self.assertTrue(out["truncated"])
        self.assertIn("reached its cap with 2 sitemaps unread",
                      out["truncated_reason"])
        self.assertEqual(verdict("GO-137", out), NO_DATA)

    def test_sitemap_loader_names_children_left_unread_at_its_cap(self):
        import site_crawl

        root = self.SITE + "index.xml"
        children = [self.SITE + "child-a.xml", self.SITE + "child-b.xml"]
        xml = ("<sitemapindex xmlns=\"http://www.sitemaps.org/schemas/"
               "sitemap/0.9\">" + "".join(
                   f"<sitemap><loc>{url}</loc></sitemap>" for url in children
               ) + "</sitemapindex>")

        def fetch(url, **_kwargs):
            self.assertEqual(url, root)
            return {"status": 200, "text": xml}

        sitemap = site_crawl.load_sitemap_urls(
            self.SITE, sitemap_urls=[root], max_sitemaps=1, fetch=fetch)
        self.assertEqual(sitemap["unvisited"], children)

    def test_service_and_input_failures_are_not_verdicts(self):
        for exception, kind in ((RuntimeError("denied"), "service"),
                                (OSError("missing key"), "input")):
            with self.subTest(kind):
                def refuse(*a, error=exception, **k):
                    raise error
                self.mod.build_service = refuse
                out = self.mod.analyze(self.SITE, self.PROP, "/missing.json")
                self.assertNotIn("summary", out)
                self.assertNotIn("issues", out)
                self.assertEqual(out["error_kind"], kind)
                self.assertEqual(verdict("GO-137", out), NO_DATA)

    def test_the_per_run_cap_blocks_only_a_clean_pass(self):
        urls = [self.SITE + str(i) for i in range(3)]
        clean, _ = self.reconcile(
            urls,
            states={url: "Submitted and indexed" for url in urls},
            rows=self.rows(*urls),
            max_urls=2,
        )
        self.assertTrue(clean["truncated"])
        self.assertIn("per-run cap", clean["truncated_reason"])
        self.assertEqual(verdict("GO-137", clean), NO_DATA)

        broken, _ = self.reconcile(
            urls,
            states={urls[0]: "Crawled - currently not indexed",
                    urls[1]: "Submitted and indexed",
                    urls[2]: "Submitted and indexed"},
            rows=self.rows(*urls),
            max_urls=2,
        )
        self.assertEqual(verdict("GO-137", broken), FAIL)

    def test_one_inspection_error_is_undecided_and_truncated(self):
        urls = [self.SITE, self.SITE + "error"]
        out, _ = self.reconcile(
            urls,
            states={urls[0]: "Submitted and indexed",
                    urls[1]: RuntimeError("quota")},
            rows=self.rows(*urls),
        )
        self.assertEqual(out["summary"]["undecided"], 1)
        self.assertTrue(out["truncated"])
        self.assertIn("inspection errored", out["truncated_reason"])
        self.assertEqual(verdict("GO-137", out), NO_DATA)

    def test_only_the_sitemap_prefix_is_inspected_and_pages_are_the_dimension(self):
        urls = [self.SITE + str(i) for i in range(4)]
        out, service = self.reconcile(
            urls,
            states={url: "Submitted and indexed" for url in urls},
            rows=self.rows(*urls),
            max_urls=2,
        )
        inspected = {call[1]["inspectionUrl"] for call in service.calls
                     if call[0] == "inspect"}
        self.assertEqual(inspected, set(urls[:2]))
        query = next(call for call in service.calls if call[0] == "query")
        self.assertEqual(query[2]["dimensions"], ["page"])
        self.assertEqual(verdict("GO-137", out), NO_DATA)

    def test_runner_routes_missing_credentials_and_archive_mode(self):
        item = ITEMS["GO-137"]
        context = {"url": self.SITE, "gsc_property": self.PROP,
                   "gsc_credentials": "/missing.json"}
        plan, skipped = build_plan([item], context, {"api"}, "live",
                                   has_gsc=False)
        self.assertEqual(plan, {})
        self.assertEqual(skipped["GO-137"],
                         (NEEDS_INPUT, GSC_CREDENTIALS_ABSENT))

        plan, skipped = build_plan([item], context, {"offline"}, "archive",
                                   has_gsc=True)
        self.assertEqual(plan, {})
        self.assertEqual(skipped["GO-137"][0], NA)


class Cannibalization(unittest.TestCase):
    """The four items reading `gsc_cannibalization.py`.

    Two URLs competing for one query is the thing this measures, and it cannot be
    measured from a page: it needs a property's history. Which is why these are
    `NO_DATA` without credentials — and why the arithmetic that turns rows into a
    verdict had never been exercised.
    """

    def setUp(self):
        import gsc_cannibalization
        self.mod = gsc_cannibalization
        self.saved = gsc_cannibalization.build_service

    def tearDown(self):
        self.mod.build_service = self.saved

    def rows(self, triples):
        return [{"keys": list(keys), "clicks": clicks, "impressions": impressions,
                 "ctr": 0.05, "position": position}
                for keys, clicks, impressions, position in triples]

    def analyze(self, rows, alternate_urls=None, brand=None, source="operator"):
        self.mod.build_service = lambda *a, **k: _Query(rows=rows)
        return self.mod.analyze("https://example.com/", "/dev/null", 90,
                                alternate_urls=alternate_urls, brand_names=brand,
                                brand_source=source if brand else "",
                                no_brand_reason="the homepage publishes no WebSite or "
                                                "organisation name and no og:site_name; "
                                                "pass --brand")

    def items_for(self):
        return [i for i in ITEMS.values()
                if (i.get("check") or {}).get("script") == "gsc_cannibalization.py"]

    def test_one_url_per_query_is_not_cannibalisation(self):
        out = self.analyze(self.rows([
            (("fixture bakery", "https://example.com/"), 400, 2000, 1.1),
            (("sourdough starter", "https://example.com/starter"), 90, 1000, 3.1),
            (("proofing times", "https://example.com/guide"), 40, 600, 5.4),
        ]), brand=["Fixture Bakery"])
        self.assertEqual(out["cannibalized"], [])
        self.assertEqual(verdicts(self.items_for(), out),
                         {"GO-139": PASS, "KW-070": PASS, "KW-071": PASS,
                          "MS-023": PASS})

    def test_two_urls_ranking_for_one_query_are_found(self):
        out = self.analyze(self.rows([
            (("fixture bakery", "https://example.com/"), 400, 2000, 1.1),
            (("sourdough starter", "https://example.com/starter"), 50, 900, 4.2),
            (("sourdough starter", "https://example.com/blog/starter"), 30, 800, 6.9),
            (("sourdough starter", "https://example.com/faq"), 5, 400, 18.0),
        ]), brand=["Fixture Bakery"])
        self.assertTrue(out["cannibalized"])
        found = out["cannibalized"][0]
        self.assertEqual(found["query"], "sourdough starter")
        self.assertGreaterEqual(found["page_count"], 2)
        self.assertGreaterEqual(len(found["pages"]), 2)
        # Pinned per item rather than "something failed": which one fails is the
        # content of the check. KW-071 now counts only close-position contests, so
        # the widely separated third URL keeps this broad cannibalization out of its
        # narrower duplication/overuse verdict. MS-023 still counts the split query.
        self.assertEqual(verdicts(self.items_for(), out),
                         {"GO-139": PASS, "KW-070": PASS, "KW-071": PASS,
                          "MS-023": WARN})

    def test_an_owned_brand_and_its_variants_move_to_branded_spread(self):
        out = self.analyze(self.rows([
            (("acme valley riverside", "https://example.com/"), 400, 2000, 1.2),
            (("acme valley riverside", "https://example.com/menu"), 30, 500, 1.4),
            (("acme valley riversidė", "https://example.com/"), 90, 600, 1.1),
            (("acme valley riversidė", "https://example.com/gallery"), 10, 100, 2.0),
            (("acmevalley reviews", "https://example.com/"), 50, 400, 1.3),
            (("acmevalley reviews", "https://example.com/reviews"), 8, 80, 4.0),
        ]))
        self.assertEqual(out["cannibalized"], [])
        self.assertEqual({row["query"] for row in out["branded_spread"]},
                         {"acme valley riverside", "acme valley riversidė",
                          "acmevalley reviews"})
        self.assertEqual(out["summary"]["contested_queries"], 0)

    def test_a_one_edit_brand_misspelling_moves_to_branded_spread(self):
        out = self.analyze(self.rows([
            (("fixture orchard riverside", "https://example.com/"), 400, 2000, 1.2),
            (("fixture orchard riverside", "https://example.com/menu"), 30, 500, 1.4),
            (("fixture orchrd", "https://example.com/"), 50, 400, 1.3),
            (("fixture orchrd", "https://example.com/reviews"), 8, 80, 2.0),
        ]))
        self.assertEqual(out["cannibalized"], [])
        self.assertEqual({row["query"] for row in out["branded_spread"]},
                         {"fixture orchard riverside", "fixture orchrd"})

    def test_a_five_character_nonbrand_two_edits_away_stays_cannibalized(self):
        out = self.analyze(self.rows([
            (("orchard", "https://example.com/"), 400, 2000, 1.2),
            (("orchid", "https://example.com/a"), 50, 400, 1.3),
            (("orchid", "https://example.com/b"), 30, 300, 1.6),
        ]))
        self.assertEqual([row["query"] for row in out["cannibalized"]], ["orchid"])

    def test_a_four_character_real_word_is_never_near_matched(self):
        """`acne` is one edit from the inferred `acme` brand and a real word.
        No longer candidate can provide this guard for a distance-one matcher by
        definition, so the explicit short-term floor is the discriminating case."""
        out = self.analyze(self.rows([
            (("acme", "https://example.com/"), 400, 2000, 1.2),
            (("acne", "https://example.com/a"), 50, 400, 1.3),
            (("acne", "https://example.com/b"), 30, 300, 1.6),
        ]))
        self.assertEqual([row["query"] for row in out["cannibalized"]], ["acne"])

    def test_eleven_query_shape_keeps_only_two_real_contests(self):
        triples = [
            (("fixture orchard riverside", "https://example.com/"), 500, 3000, 1.0),
            (("fixture orchard riverside", "https://example.com/info"), 40, 400, 1.3),
        ]
        brand_queries = [
            "fixture orchard", "fixtureorchard", "fixture orchard reviews",
            "fixture orchard menu", "fixture orchrd", "fixture orchard photos",
        ]
        for index, query in enumerate(brand_queries):
            triples.extend([
                ((query, "https://example.com/"), 30, 200, 1.2),
                ((query, f"https://example.com/brand-{index}"), 10, 80, 1.8),
            ])
        for index, query in enumerate(("family lunch", "lakeside activities")):
            triples.extend([
                ((query, f"https://example.com/topic-{index}"), 20, 150, 3.0),
                ((query, f"https://example.com/guide-{index}"), 15, 120, 4.0),
            ])
        triples.extend([
            (("opening hours", "https://example.com/hours"), 8, 60, 2.0),
            (("directions", "https://example.com/contact"), 7, 50, 2.5),
        ])
        out = self.analyze(self.rows(triples))
        self.assertEqual(out["queries_analyzed"], 11)
        self.assertEqual(len(out["queries"]), 11)
        self.assertFalse(out["queries_truncated"])
        self.assertEqual(out["summary"], {"cannibalized_queries": 2,
                                          "contested_queries": 2})
        self.assertIn("fixture orchrd",
                      {row["query"] for row in out["branded_spread"]})
        bucket_counts = {
            bucket: sum(row["bucket"] == bucket for row in out["queries"])
            for bucket in ("branded_spread", "cannibalized", "contested", "single_page")
        }
        self.assertEqual(bucket_counts, {"branded_spread": 7, "cannibalized": 0,
                                         "contested": 2, "single_page": 2})
        self.assertEqual(bucket_counts["cannibalized"] + bucket_counts["contested"],
                         out["summary"]["cannibalized_queries"])
        misspelling = next(row for row in out["queries"]
                           if row["query"] == "fixture orchrd")
        self.assertEqual(misspelling["brand_form"], "fixtureorchrd")
        self.assertEqual(misspelling["matched_brand_term"], "fixtureorchard")
        self.assertEqual(misspelling["edit_distance"], 1)
        single = next(row for row in out["queries"]
                      if row["query"] == "opening hours")
        self.assertEqual(single, {
            "query": "opening hours", "brand_form": "openinghours",
            "page_count": 1, "impressions": 60, "spread": 0,
            "positions_compared": 1,
            "bucket": "single_page",
        })

    def test_query_evidence_caps_after_every_classified_query(self):
        triples = [
            (("fixture orchard", "https://example.com/"), 500, 3000, 1.0),
            (("fixture orchard", "https://example.com/info"), 40, 400, 1.3),
        ]
        for index in range(30):
            triples.extend([
                ((f"fixture orchard variant {index}", "https://example.com/"),
                 20, 200, 2.0),
                ((f"fixture orchard variant {index}",
                  f"https://example.com/variant-{index}"), 5, 100, 2.5),
            ])
        triples.extend(
            ((f"unclassified query {index}", f"https://example.com/{index}"),
             0, 20, 5.0)
            for index in range(1001)
        )
        out = self.analyze(self.rows(triples))
        self.assertEqual(out["queries_analyzed"], 1032)
        self.assertEqual(len(out["queries"]), 1000)
        self.assertTrue(out["queries_truncated"])
        self.assertEqual(len(out["branded_spread"]), 25)
        self.assertEqual(out["queries"][0]["query"], "fixture orchard")
        self.assertEqual(out["queries"][0]["bucket"], "branded_spread")
        self.assertEqual(sum(row["bucket"] == "branded_spread"
                             for row in out["queries"]), 31)
        self.assertFalse(any(row["bucket"] == "single_page"
                             and row["page_count"] >= 2
                             for row in out["queries"]))

    def test_a_brand_the_homepage_does_not_own_still_cannibalizes(self):
        out = self.analyze(self.rows([
            (("acme valley", "https://example.com/other"), 400, 2000, 1.2),
            (("acme valley", "https://example.com/"), 30, 500, 2.0),
        ]))
        # With no name known, the top query is a brand only if the homepage is where
        # it lands — here it is not, so nothing is inferred and the split counts.
        self.assertEqual(out["spread_brand"], {"source": "none", "names": []})
        self.assertEqual([row["query"] for row in out["cannibalized"]],
                         ["acme valley"])

    def test_a_named_brand_split_across_pages_is_a_branded_spread(self):
        """The same rows with the name known: a search for the business that lands
        on two of its pages is not two pages competing for a topic. Whether the
        homepage owns it is KW-070's question, and it is asked there."""
        out = self.analyze(self.rows([
            (("acme valley", "https://example.com/other"), 400, 2000, 1.2),
            (("acme valley", "https://example.com/"), 30, 500, 2.0),
        ]), brand=["Acme Valley"])
        self.assertEqual(out["cannibalized"], [])
        self.assertEqual([row["query"] for row in out["branded_spread"]], ["acme valley"])
        self.assertEqual(self.brand_verdicts(out), {"KW-070": FAIL, "GO-139": PASS})

    def test_hreflang_alternates_count_as_one_logical_page(self):
        out = self.analyze(self.rows([
            (("acme valley", "https://example.com/"), 400, 2000, 1.2),
            (("acme valley", "https://example.com/en/"), 30, 500, 1.4),
            (("acme valley", "https://example.com/ru/"), 20, 300, 1.5),
        ]), alternate_urls=["https://example.com/", "https://example.com/en/",
                            "https://example.com/ru/"])
        self.assertEqual(out["cannibalized"], [])
        self.assertEqual(out["branded_spread"][0]["page_count"], 1)

    def test_close_nonbrand_competition_is_contested_but_a_wide_spread_is_not(self):
        out = self.analyze(self.rows([
            (("fixture bakery", "https://example.com/"), 500, 3000, 1.0),
            (("close query", "https://example.com/a"), 40, 500, 1.2),
            (("close query", "https://example.com/b"), 30, 400, 1.4),
            (("wide query", "https://example.com/a"), 20, 300, 1.5),
            (("wide query", "https://example.com/c"), 10, 200, 11.2),
        ]))
        self.assertEqual(out["summary"]["contested_queries"], 1)
        self.assertEqual([row["query"] for row in out["contested"]], ["close query"])
        self.assertNotIn("worst_spread", out["summary"])

    BRAND_ITEMS = ("KW-070", "GO-139")

    def brand_verdicts(self, out):
        return {item_id: verdict(item_id, out) for item_id in self.BRAND_ITEMS}

    def test_a_generic_head_term_is_not_the_brand(self):
        """The property that exposed the defect, in shape: the highest-click query is
        `barber paphos`, served by an inner page, and the shop's own name is served by
        the homepage at position 1. Before 0.122.0 both items failed the site over
        `barber paphos`; they are about the name."""
        out = self.analyze(self.rows([
            (("barber paphos", "https://example.com/en/services"), 40, 300, 3.1),
            (("marino barbero", "https://example.com/"), 6, 20, 1.0),
            (("barber marino", "https://example.com/"), 2, 8, 1.2),
            (("marinos barber shop", "https://example.com/"), 1, 5, 1.0),
        ]), brand=["Marino Barbero"], source="published")
        branded = out["branded"]
        self.assertEqual(branded["query"], "marino barbero")
        self.assertEqual(branded["branded_queries"], 3)
        self.assertEqual(branded["brand_source"], "published")
        self.assertTrue(branded["homepage_ranks_first"])
        self.assertEqual(self.brand_verdicts(out), {"KW-070": PASS, "GO-139": PASS})
        self.assertFalse(any("barber paphos" in issue["message"]
                             for issue in out["issues"]))

    def test_the_most_searched_branded_query_is_judged_not_the_most_clicked(self):
        """Impressions, not clicks: a brand search nobody clicked through is still
        the brand's own search, and the one that says whether the name is owned."""
        out = self.analyze(self.rows([
            (("acme valley", "https://example.com/about"), 0, 400, 2.4),
            (("acme valley reviews", "https://example.com/"), 30, 60, 1.0),
        ]), brand=["Acme Valley"])
        self.assertEqual(out["branded"]["query"], "acme valley")
        self.assertFalse(out["branded"]["owns_homepage"])
        self.assertEqual(self.brand_verdicts(out), {"KW-070": FAIL, "GO-139": FAIL})

    def test_the_homepage_must_be_served_and_rank_first(self):
        """KW-070's title is a conjunction and so is its rule; GO-139 asks only that
        the site ranks first, with whatever page."""
        served_low = self.analyze(self.rows([
            (("acme valley", "https://example.com/"), 50, 400, 3.1),
        ]), brand=["Acme Valley"])
        self.assertTrue(served_low["branded"]["owns_homepage"])
        self.assertEqual(self.brand_verdicts(served_low),
                         {"KW-070": FAIL, "GO-139": FAIL})
        inner_first = self.analyze(self.rows([
            (("acme valley", "https://example.com/contact"), 50, 400, 1.0),
        ]), brand=["Acme Valley"])
        self.assertEqual(self.brand_verdicts(inner_first),
                         {"KW-070": FAIL, "GO-139": PASS})

    def test_a_locale_alternate_of_the_homepage_is_the_homepage(self):
        out = self.analyze(self.rows([
            (("acme valley", "https://example.com/en/"), 50, 400, 1.1),
        ]), alternate_urls=["https://example.com/", "https://example.com/en/"],
            brand=["Acme Valley"])
        self.assertTrue(out["branded"]["owns_homepage"])
        self.assertEqual(self.brand_verdicts(out), {"KW-070": PASS, "GO-139": PASS})
        unrelated = self.analyze(self.rows([
            (("acme valley", "https://example.com/en/"), 50, 400, 1.1),
        ]), brand=["Acme Valley"])
        self.assertFalse(unrelated["branded"]["owns_homepage"],
                         "/en/ with no hreflang set is an inner page")

    def test_a_brand_nobody_searched_does_not_apply(self):
        """A demand gap, not a ranking defect: with no branded query in the window
        there is nothing for the homepage to own. The cannibalisation items still
        decide."""
        out = self.analyze(self.rows([
            (("barber paphos", "https://example.com/"), 40, 300, 1.1),
        ]), brand=["Marino Barbero"])
        self.assertFalse(out["branded"]["searched"])
        self.assertNotIn("owns_homepage", out["branded"])
        self.assertEqual(self.brand_verdicts(out), {"KW-070": NA, "GO-139": NA})
        self.assertEqual(verdict("MS-023", out), PASS)

    def test_no_brand_name_is_undecided_and_names_the_flag(self):
        """The highest-click query is never promoted to the brand for these two
        items. The evidence carries the script's reason, so the reader is told which
        flag supplies what is missing rather than that a key is absent."""
        out = self.analyze(self.rows([
            (("fixture bakery", "https://example.com/"), 400, 2000, 1.1),
        ]))
        self.assertFalse(out["branded"]["checked"])
        self.assertEqual(self.brand_verdicts(out), {"KW-070": NO_DATA, "GO-139": NO_DATA})
        ok, evidence = evaluate(ITEMS["KW-070"]["check"]["applies_when"], out)
        self.assertIsNone(ok)
        self.assertIn("pass --brand", evidence)
        self.assertEqual(out["spread_brand"]["source"], "inferred")

    def test_reordered_and_plural_forms_of_a_name_are_branded(self):
        match = self.mod._any_brand_match
        for query in ("marino barbero", "barber marino", "marinos barber shop",
                      "marino barbero paphos", "marinobarbero"):
            with self.subTest(query=query):
                self.assertIsNotNone(match(query, ["Marino Barbero"]))
        for query in ("barber paphos", "best barber", "marina bay"):
            with self.subTest(query=query):
                self.assertIsNone(match(query, ["Marino Barbero"]))

    def test_the_names_a_homepage_publishes_are_read(self):
        html = """<html><head>
          <meta property="og:site_name" content="Marino Barber Shop">
          <script type="application/ld+json">{"@context": "https://schema.org",
            "@graph": [
              {"@type": "WebSite", "name": "Marino Barbero", "url": "/"},
              {"@type": ["HairSalon"], "name": "Marino  Barbero",
               "alternateName": ["Barber Marino"]},
              {"@type": "WebPage", "name": "Home"}]}</script>
          <script type="application/ld+json">{not json</script>
        </head><body></body></html>"""
        self.assertEqual(self.mod.published_brand_names(html),
                         ["Marino Barbero", "Barber Marino", "Marino Barber Shop"])
        self.assertEqual(self.mod.published_brand_names("<html><title>x</title></html>"),
                         [])

    def test_no_credentials_is_undecided_and_says_so(self):
        """Not an empty history. A property nobody could open and a property with no
        traffic produce the same-shaped result and mean opposite things, and only one
        of them is a fact about the site."""
        def refuse(*a, **k):
            raise RuntimeError("credentials file not found")
        self.mod.build_service = refuse
        out = self.mod.analyze("https://example.com/", "/nonexistent.json", 90)
        self.assertTrue(out.get("error"))
        self.assertEqual(out["queries"], [])
        self.assertFalse(out["queries_truncated"])
        for item in self.items_for():
            self.assertEqual(verdict(item["id"], out), NO_DATA, item["id"])


class UrlInspection(unittest.TestCase):
    """The three items reading `gsc_url_inspection.py` — Google's own answer about
    whether a URL is indexed, which is the only place that answer exists.

    CI-002 joined them in 0.26.0 and immediately found that `indexed` was pre-seeded
    with `None` in the result, two lines under a comment explaining why
    `canonical_match` must not be: a `truthy` rule reads `None` as a failing value, so
    a property nobody could open reported the page as **not indexed** at `high`. The
    field is assigned only when the coverage wording is recognised, and
    `test_no_credentials_is_undecided` is the test that says so.
    """

    def setUp(self):
        import gsc_url_inspection
        self.mod = gsc_url_inspection
        self.saved = gsc_url_inspection.build_service

    def tearDown(self):
        self.mod.build_service = self.saved

    def inspect(self, verdict_text, coverage_state):
        payload = {"inspectionResult": {
            "indexStatusResult": {
                "verdict": verdict_text,
                "coverageState": coverage_state,
                "robotsTxtState": "ALLOWED",
                "indexingState": "INDEXING_ALLOWED",
                "lastCrawlTime": "2026-07-20T00:00:00Z",
                "googleCanonical": "https://example.com/",
                "userCanonical": "https://example.com/",
            }}}
        self.mod.build_service = lambda *a, **k: _Query(inspection=payload)
        return self.mod.analyze("https://example.com/", "https://example.com/",
                                "/dev/null", "en")

    def items_for(self):
        return [i for i in ITEMS.values()
                if (i.get("check") or {}).get("script") == "gsc_url_inspection.py"]

    def test_an_indexed_url_passes(self):
        out = self.inspect("PASS", "Submitted and indexed")
        self.assertEqual(verdicts(self.items_for(), out),
                         {"CI-002": PASS, "CI-010": PASS, "GO-135": PASS})

    def test_a_url_google_has_excluded_does_not(self):
        """CI-010 passing here is correct and is the reason to pin both. It asks
        whether Google's chosen canonical matches the declared one, which this URL
        answers yes to while not being indexed at all — a different question. An
        assertion of "at least one item failed" would have been satisfied by GO-135
        alone and would equally have been satisfied if CI-010 had stopped deciding.
        """
        out = self.inspect("FAIL", "Discovered - currently not indexed")
        self.assertEqual(verdicts(self.items_for(), out),
                         {"CI-002": FAIL, "CI-010": PASS, "GO-135": FAIL})

    def test_no_credentials_is_undecided(self):
        def refuse(*a, **k):
            raise RuntimeError("no credentials")
        self.mod.build_service = refuse
        out = self.mod.analyze("https://example.com/", "https://example.com/",
                               "/nonexistent.json", "en")
        self.assertTrue(out.get("error"))
        for item in self.items_for():
            self.assertEqual(verdict(item["id"], out), NO_DATA, item["id"])

    def test_text_output_survives_a_response_without_canonicals(self):
        payload = {"inspectionResult": {"indexStatusResult": {
            "verdict": "PASS",
            "coverageState": "Submitted and indexed",
            "robotsTxtState": "ALLOWED",
            "indexingState": "INDEXING_ALLOWED",
            "pageFetchState": "SUCCESSFUL",
        }}}
        self.mod.build_service = lambda *a, **k: _Query(inspection=payload)
        saved_argv = sys.argv
        sys.argv = ["gsc_url_inspection.py", "https://example.com/",
                    "--property", "sc-domain:example.com"]
        output = io.StringIO()
        try:
            with contextlib.redirect_stdout(output):
                self.mod.main()
        finally:
            sys.argv = saved_argv
        self.assertIn("canon match:   unknown", output.getvalue())


class SearchConsoleSummary(unittest.TestCase):
    """`gsc_checker.py`, which is the one that builds the service every other Search
    Console script borrows."""

    def setUp(self):
        import gsc_checker
        self.mod = gsc_checker

    def test_the_property_string_is_passed_through_untouched(self):
        """The bug this guards is not hypothetical: a run built `sc-domain:0.1` from
        `127.0.0.1`, and a property nobody owns answers with nothing, which reads as a
        site with no search traffic. The registrable-domain fix lives in the runner;
        this asserts the script does not re-derive one of its own.
        """
        service = _Query(rows=[{"keys": ["q", "https://example.com/"], "clicks": 1,
                                "impressions": 2, "ctr": 0.5, "position": 1.0}])
        # `get_performance_data`, not `fetch_search_analytics`. This test skipped itself
        # for eleven releases on `hasattr(mod, "fetch_search_analytics")` — a name the
        # module never had — and said so as "gsc_checker has no single-call entry point to
        # exercise", which was false: `main()` calls this one. A probe for a function that
        # does not exist reports the *subject* as missing, and the suite printed
        # "OK (skipped=1)" over an untested call into Search Console.
        result = self.mod.get_performance_data(service, "sc-domain:example.com", days=28)
        self.assertEqual(service.calls[0][1], "sc-domain:example.com")
        self.assertEqual([r["query"] for r in result["data"]], ["q"])


if __name__ == "__main__":
    unittest.main()
