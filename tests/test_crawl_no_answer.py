"""A crawled page that gave no answer is asked once more, then withheld (F04, H13-c).

Until F04 a page that timed out or whose connection was reset was a row in the crawl like
a page read, so a crawl below its page budget with one such page called itself complete,
and the site-wide items that pass by finding nothing passed over a page nobody read. The
owner's decision (2026-10-21, "retry, then withhold"): a page that gives no answer — the
fetch layer's `timeout` or `refused`, no HTTP status — is requested once more; if that
also gives no answer the crawl is `truncated` and names the pages, as for a page this
audit's guard refused (`openspec/specs/verdicts/` VRD-14). An HTTP status of any kind, a
guard refusal or a robots decline is an answer, and is not asked again.
"""
from __future__ import annotations

import io
import json
import os
import socket
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "skills/seo-checklist/scripts"
REGISTRY = ROOT / "skills/seo-checklist/resources/config/checklist.json"
sys.path.insert(0, str(SCRIPTS))

import checklist_runner as cr  # noqa: E402
import site_crawl  # noqa: E402
from lib import safe_http as sh  # noqa: E402

SITE = "https://site.example/"
HOME = (b'<html><head><title>Home of the example site</title></head><body>'
        b'<a href="/p">p</a> <a href="/q">q</a></body></html>')
PAGE = (b'<html><head><title>%s</title></head><body><p>Some words about %s.</p>'
        b'</body></html>')

# The suite's switches and tripwire, also when this module runs alone (GOV-7).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402,F401


def response(request, status, headers, body: bytes):
    made = sh.requests.Response()
    made.status_code = status
    made.url = request.url
    made.request = request
    made.headers = sh.CaseInsensitiveDict(headers)
    made._content = body
    made._content_consumed = True
    made.raw = io.BytesIO(body)
    return made


def crawl(failures: dict) -> tuple[dict, Counter]:
    """Crawl site.example: `/` links `/p` and `/q`. `failures` maps a path to the
    exceptions its requests raise, in order; past them the path answers 200."""
    asked: Counter = Counter()
    pending = {path: list(errors) for path, errors in failures.items()}

    def send(adapter, request, **_kwargs):
        path = urlparse(request.url).path
        asked[path] += 1
        if pending.get(path):
            error = pending[path].pop(0)
            if isinstance(error, int):
                return response(request, error, {"Content-Type": "text/html"}, b"busy")
            raise error
        if path == "/":
            return response(request, 200, {"Content-Type": "text/html"}, HOME)
        if path in ("/p", "/q"):
            name = path.strip("/").encode()
            return response(request, 200, {"Content-Type": "text/html"},
                            PAGE % (b"Page " + name + b" of the example site", name))
        return response(request, 404, {"Content-Type": "text/html"}, b"")

    public = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
    work = tempfile.mkdtemp(prefix="seo-no-answer-")
    with mock.patch.dict(os.environ, {"SEO_LOOPBACK_ONLY": "", "SEO_HTTP_CACHE": "",
                                      "SEO_MAX_RPS": "0", "SEO_RATE_LIMIT_DIR": work}), \
            mock.patch.object(sh.socket, "getaddrinfo", return_value=public), \
            mock.patch.object(sh._PinnedAdapter, "send",
                              new=lambda adapter, request, **kw: send(adapter, request)):
        return site_crawl.crawl(SITE, use_sitemap=False, workers=1), asked


def timeout():
    return sh.requests.exceptions.ReadTimeout("read timed out")


def reset():
    return sh.requests.exceptions.ConnectionError("connection reset by peer")


class APageThatAnswersOnTheRetryIsRead(unittest.TestCase):

    def test_one_timeout_then_an_answer_leaves_the_crawl_complete(self):
        inventory, asked = crawl({"/p": [timeout()]})
        self.assertEqual(asked["/p"], 2)
        self.assertEqual(inventory["pages"][SITE + "p"]["status"], 200)
        self.assertFalse(inventory["summary"]["truncated"], inventory["summary"])
        self.assertEqual(inventory["summary"]["unanswered_pages"], 0)

    def test_a_reset_then_an_answer_likewise(self):
        inventory, asked = crawl({"/q": [reset()]})
        self.assertEqual(asked["/q"], 2)
        self.assertFalse(inventory["summary"]["truncated"])


    def test_a_body_cut_off_then_an_answer_likewise(self):
        # A connection broken while the body was read reaches the crawl as the fetch
        # layer's `other` (requests' ChunkedEncodingError), not `refused`: found by the
        # second review of batch 1, it was asked once and left a row with no content.
        cut = sh.requests.exceptions.ChunkedEncodingError("Response ended prematurely")
        inventory, asked = crawl({"/p": [cut]})
        self.assertEqual(asked["/p"], 2)
        self.assertEqual(inventory["pages"][SITE + "p"]["status"], 200)

    def test_a_body_cut_off_twice_cuts_the_crawl(self):
        cut = sh.requests.exceptions.ChunkedEncodingError("Response ended prematurely")
        inventory, _ = crawl({"/p": [cut, cut]})
        self.assertTrue(inventory["summary"]["truncated"])
        self.assertEqual(inventory["summary"]["unanswered_pages"], 1)

    def test_a_redirect_loop_is_an_answer_and_is_asked_once(self):
        loop = sh.requests.exceptions.TooManyRedirects("Exceeded 30 redirects")
        inventory, asked = crawl({"/p": [loop, loop]})
        self.assertEqual(asked["/p"], 1)
        self.assertEqual(inventory["summary"]["unanswered_pages"], 0)


class APageThatNeverAnswersIsWithheld(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.inventory, cls.asked = crawl({"/p": [timeout(), reset()]})

    def test_it_is_asked_twice_and_no_more(self):
        self.assertEqual(self.asked["/p"], 2)

    def test_the_crawl_is_cut_and_names_it(self):
        summary = self.inventory["summary"]
        self.assertTrue(summary["truncated"], summary)
        self.assertEqual(summary["unanswered_pages"], 1)

    def test_a_site_wide_item_that_passes_by_absence_is_withheld(self):
        path = os.path.join(tempfile.mkdtemp(prefix="seo-no-answer-inv-"), "crawl.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(self.inventory, handle)
        with open(REGISTRY, encoding="utf-8") as f:
            items = [i for i in json.load(f)["items"] if i["id"] == "MS-022"]
        plan, skipped = cr.build_plan(items, {"url": SITE, "inventory_json": path},
                                      set(cr.MODE_CAPS["live"]), "live")
        results = {key: cr._timed(key, 120) for key in plan}
        row = cr.grade(items, plan, results, skipped, False)[0]
        self.assertEqual(row["status"], "NO_DATA", row)
        # The reason is the readers' cap fallback, as for a page the guard refused:
        # they copy the crawl's flag and not why (F04 Queue).
        self.assertIn("only part of the input was read", row["evidence"])


    def test_a_sample_drawn_from_it_names_the_silence_not_a_cap(self):
        # `--sample` reads the crawl's cut to withhold what the cut could decide, and
        # names why; a crawl cut by a silent page is not one stopped at its caps.
        report: dict = {}
        cr.discover_urls(SITE, 2, inventory=self.inventory, report=report)
        cut = report.get("cut", "")
        self.assertIn("gave no answer", cut, report)
        self.assertNotIn("caps", cut, report)


class AnAnswerIsNotAskedAgain(unittest.TestCase):

    def test_the_no_answer_kinds_are_the_fetch_layers_words_for_silence(self):
        # Held against what the fetch layer calls a timeout and a refused or reset
        # connection, and against what it calls an answer it did not like.
        import seo_common
        silent = {seo_common.fetch_error_kind(timeout()),
                  seo_common.fetch_error_kind(reset())}
        self.assertEqual(set(site_crawl.NO_ANSWER_KINDS), silent)
        for answered in (sh.SafeHTTPError("Blocked"),
                         sh.requests.exceptions.SSLError("bad certificate")):
            self.assertNotIn(seo_common.fetch_error_kind(answered),
                             site_crawl.NO_ANSWER_KINDS)

    def test_an_http_error_status_is_asked_once(self):
        inventory, asked = crawl({"/p": [503]})
        self.assertEqual(asked["/p"], 1)
        self.assertEqual(inventory["summary"]["unanswered_pages"], 0)

    def test_a_guard_refusal_is_asked_once(self):
        refused = sh.SafeHTTPError("Blocked: private/internal IP")
        inventory, asked = crawl({"/p": [refused, refused]})
        self.assertLessEqual(asked["/p"], 1)
        self.assertEqual(inventory["summary"]["unanswered_pages"], 0)


if __name__ == "__main__":
    unittest.main()
