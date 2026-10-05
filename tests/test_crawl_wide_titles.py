"""Release 0.128.0: four titles about the whole site read the whole crawl.

Found by running this tool on an independently built plugin's fixtures (26.09) and
re-measured on 28.09 before anything moved: the crawl inventory held every fact each
title asks about, and each rule looked somewhere else.

* CI-015 *Eliminate 5xx Server Errors* read the entry page's status. A 5xx entry page
  stops the audit (`test_contract.SAME_ON_BOTH` recorded it), so the rule could not fail
  in any finished audit. It now counts crawled pages answering 5xx.
* MS-026 *Ensure Every Page Has a Title* read the entry page. It now counts crawled
  HTML pages with no title — Google asks for one on every page ("Make sure every page
  on your site has a title specified in the `<title>` element", Search Central,
  *Influencing title links*).
* TE-176 *Fix Canonicalization Issues* read the entry page, and `canonical_checker.py`
  checks a canonical's target only under `--check-targets`, which no item passed: a
  canonical pointing at a 500 was invisible on every page. It now reads every crawled
  page's canonical and the target's status, from the crawl where the crawl has it.
* MD-187 *Fix Broken Images* did read the crawl. An image URL answering `200` with an
  HTML page — a soft 404, the ordinary way a CMS answers a missing file — was "fine".
"""

import json
import os
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "skills", "seo-checklist", "scripts")
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness  # noqa: E402
import site_crawl  # noqa: E402
from checklist_runner import FAIL, NO_DATA, PASS, evaluate  # noqa: E402

SITE = "https://example.test/"


def items() -> dict:
    return {item["id"]: item for item in harness.registry()["items"]}


def verdict(item_id: str, output: dict) -> str:
    ok, _evidence = evaluate(items()[item_id]["check"]["assert"], output)
    return NO_DATA if ok is None else PASS if ok else FAIL


def page(url: str, *, status: int = 200, title: str | None = "A page",
         canonical: str | None = None, links: tuple = (), noindex: bool = False,
         images: tuple = ()) -> dict:
    """One inventory row, with the fields the four readers use."""
    return {
        "url": url, "final_url": url, "status": status, "html": True,
        "title": title, "canonical": canonical, "noindex": noindex,
        "redirect_chain": [], "text_hash": f"hash-{url}", "signature": [],
        "content_words": 400, "meta_description": f"About {url}",
        "images": list(images), "error": None, "error_kind": None,
        "links": [{"target": target, "internal": True, "anchor": "a",
                   "nofollow": False} for target in links],
    }


class Inventories(unittest.TestCase):
    def inventory(self, rows: list[dict], truncated: bool = False) -> str:
        folder = tempfile.TemporaryDirectory(prefix="crawl-wide-")
        self.addCleanup(folder.cleanup)
        path = os.path.join(folder.name, "inventory.json")
        pages = {site_crawl.page_key(row["url"]): row for row in rows}
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"inventory_version": site_crawl.INVENTORY_VERSION,
                       "site": SITE, "entry": SITE, "pages": pages,
                       "summary": {"truncated": truncated}, "fetch_error": None},
                      handle)
        return path


class TheRegistryReadsTheCrawl(unittest.TestCase):
    """Each of the four is a crawl item handed the shared inventory."""

    EXPECTED = {
        "CI-015": ("indexability_matrix.py", {"path": "summary.server_errors", "eq": 0}),
        "MS-026": ("duplicate_content.py",
                   {"path": "summary.missing_title_pages", "eq": 0}),
        "TE-176": ("canonical_checker.py", {"path": "issues", "len_eq": 0}),
        "MD-187": ("image_weight_audit.py", {"path": "broken_image_count", "eq": 0}),
    }

    def test_each_title_about_the_site_runs_over_the_inventory(self):
        registry = items()
        for item_id, (script, rule) in self.EXPECTED.items():
            with self.subTest(item_id=item_id):
                check = registry[item_id]["check"]
                self.assertEqual(check["script"], script)
                self.assertEqual(check["requires"], "crawl")
                self.assertEqual(check["args"][-2:], ["--inventory", "{inventory_json}"])
                self.assertEqual(check["assert"], rule)


class FiveHundredsAnywhereInTheCrawl(Inventories):
    """CI-015 over `indexability_matrix.evaluate_inventory`."""

    def run_over(self, rows, truncated=False):
        import indexability_matrix
        path = self.inventory(rows, truncated)
        with mock.patch.object(indexability_matrix, "fetch_url") as fetch:
            out = indexability_matrix.evaluate_inventory(SITE, path)
        fetch.assert_not_called()  # the crawl already asked; nothing is asked again
        return out

    def test_a_page_answering_5xx_anywhere_fails(self):
        out = self.run_over([
            page(SITE, links=("https://example.test/offers",
                              "https://example.test/gone")),
            page("https://example.test/offers", status=503, title=None),
            page("https://example.test/gone", status=404, title=None),
        ])
        self.assertEqual(out["summary"]["server_errors"], 1)
        self.assertEqual(out["server_errors"], [{
            "url": "https://example.test/offers", "status": 503,
            "linked_from": ["https://example.test/"]}])
        self.assertEqual(verdict("CI-015", out), FAIL)

    def test_a_404_is_not_a_server_error(self):
        out = self.run_over([page(SITE, links=("https://example.test/gone",)),
                             page("https://example.test/gone", status=404)])
        self.assertEqual(out["summary"]["server_errors"], 0)
        self.assertEqual(out["server_errors"], [])
        self.assertEqual(verdict("CI-015", out), PASS)

    def test_the_crawl_says_whether_the_count_covers_the_site(self):
        self.assertFalse(self.run_over([page(SITE)])["truncated"])
        self.assertTrue(self.run_over([page(SITE)], truncated=True)["truncated"])


class EveryPageHasATitle(Inventories):
    """MS-026 over `duplicate_content.py`'s projection of the crawl."""

    def run_over(self, rows):
        import duplicate_content
        inventory = site_crawl.load(self.inventory(rows))
        return duplicate_content.detect_duplicates(
            duplicate_content.pages_from_inventory(inventory))

    def test_one_untitled_page_off_the_entry_fails(self):
        out = self.run_over([page(SITE, title="Home"),
                             page("https://example.test/story", title=None),
                             page("https://example.test/blank", title="   ")])
        self.assertEqual(out["summary"]["missing_title_pages"], 2)
        self.assertEqual(out["missing_titles"], ["https://example.test/blank",
                                                 "https://example.test/story"])
        self.assertEqual(verdict("MS-026", out), FAIL)

    def test_a_noindex_page_still_needs_a_title(self):
        """The title says *every* page. Grouping for MS-022 leaves noindex pages out
        because they do not compete for a query; a missing title is not a
        competition, and nothing in the title narrows it."""
        out = self.run_over([page(SITE, title="Home"),
                             page("https://example.test/p", title=None, noindex=True)])
        self.assertEqual(out["summary"]["missing_title_pages"], 1)

    def test_every_page_titled_passes(self):
        out = self.run_over([page(SITE, title="Home"),
                             page("https://example.test/a", title="About")])
        self.assertEqual(out["summary"]["missing_title_pages"], 0)
        self.assertEqual(verdict("MS-026", out), PASS)


class CanonicalsAcrossTheCrawl(Inventories):
    """TE-176 over `canonical_checker.check_inventory`."""

    def run_over(self, rows, answers=None, truncated=False):
        import canonical_checker
        path = self.inventory(rows, truncated)
        answers = answers or {}

        def fake(url, **_kw):
            if url not in answers:
                raise AssertionError(f"fetched {url}, which the crawl already knew")
            status, error_kind = answers[url]
            return {"url": url, "status": status, "headers": {}, "text": "",
                    "redirect_chain": [], "error": error_kind,
                    "error_kind": error_kind}

        with mock.patch.object(canonical_checker, "fetch_url", side_effect=fake):
            return canonical_checker.check_inventory(SITE, path)

    def test_a_canonical_to_a_crawled_500_fails_without_asking_again(self):
        out = self.run_over([
            page(SITE, canonical="https://example.test/gone/"),
            page("https://example.test/gone", status=500, title=None),
        ])
        self.assertEqual([issue["message"] for issue in out["issues"]],
                         ["Canonical target is not 200"])
        self.assertEqual(out["issues"][0]["severity"], "error")
        self.assertEqual(verdict("TE-176", out), FAIL)

    def test_a_target_the_crawl_did_not_reach_is_asked_once(self):
        out = self.run_over(
            [page(SITE, canonical="https://example.test/elsewhere")],
            answers={"https://example.test/elsewhere": (404, None)})
        self.assertEqual([issue["message"] for issue in out["issues"]],
                         ["Canonical target is not 200"])

    def test_a_target_that_answered_nothing_withholds_a_pass_and_is_not_a_finding(self):
        out = self.run_over(
            [page(SITE, canonical="https://example.test/slow")],
            answers={"https://example.test/slow": (None, "timeout")})
        self.assertEqual(out["issues"], [])
        self.assertTrue(out["truncated"])

    def test_the_whole_crawl_is_read_not_the_entry(self):
        out = self.run_over([
            page(SITE, canonical=SITE),
            page("https://example.test/a", canonical="https://example.test/a"),
            page("https://example.test/b", canonical=None),
        ])
        self.assertEqual(out["count"], 3)
        self.assertEqual([(issue["message"], issue["url"]) for issue in out["issues"]],
                         [("Missing canonical", "https://example.test/b")])

    def test_a_page_naming_where_its_redirect_lands_is_canonical_to_itself(self):
        """The page path compares a canonical with the URL it fetched; the crawl
        path keeps both the asked and the landed URL and must accept either."""
        entry = page(SITE, canonical="https://example.test/home/")
        entry["final_url"] = "https://example.test/home/"
        entry["redirect_chain"] = [SITE]
        out = self.run_over([entry])
        self.assertEqual(out["rows"][0]["verdict"], "self_canonical")
        self.assertEqual(out["issues"], [])

    def test_every_page_self_canonical_passes(self):
        out = self.run_over([
            page(SITE, canonical=SITE),
            page("https://example.test/a", canonical="https://example.test/a/"),
        ])
        self.assertEqual(out["issues"], [])
        self.assertFalse(out["truncated"])
        self.assertEqual(verdict("TE-176", out), PASS)


class ASoftNotFoundImageIsBroken(Inventories):
    """MD-187: an image URL answering a page is not an image."""

    def classify(self, head, confirmation=None):
        import image_weight_audit
        with mock.patch.object(image_weight_audit, "fetch_url",
                               return_value=confirmation or {}) as fetch:
            state, _returned = image_weight_audit._classify_image(
                "https://example.test/photo.png", head, 3)
        return state, fetch

    def test_a_2xx_carrying_text_is_broken(self):
        for content_type in ("text/html", "text/html; charset=utf-8", "TEXT/PLAIN"):
            with self.subTest(content_type=content_type):
                state, fetch = self.classify(
                    {"status": 200, "headers": {"content-type": content_type}})
                self.assertEqual(state, "broken")
                fetch.assert_not_called()

    def test_a_2xx_carrying_anything_else_is_fine(self):
        """Only text is evidence. Object stores serve images as
        `application/octet-stream`, and a missing header says nothing."""
        for headers in ({"content-type": "image/png"},
                        {"content-type": "image/svg+xml"},
                        {"content-type": "application/octet-stream"}, {}):
            with self.subTest(headers=headers):
                state, _fetch = self.classify({"status": 200, "headers": headers})
                self.assertEqual(state, "fine")

    def test_a_refused_head_confirmed_by_a_page_is_broken(self):
        state, fetch = self.classify(
            {"status": 405, "headers": {}},
            confirmation={"status": 200, "error_kind": None,
                          "headers": {"content-type": "text/html"}})
        self.assertEqual(state, "broken")
        self.assertEqual(fetch.call_args.kwargs["method"], "GET")

    def test_the_site_wide_count_names_what_the_image_url_answered(self):
        import image_weight_audit
        path = self.inventory([page(SITE, images=("https://example.test/missing.png",))])
        head = {"url": "https://example.test/missing.png", "status": 200,
                "headers": {"content-type": "text/html; charset=utf-8"},
                "error": None, "error_kind": None}
        with mock.patch.object(image_weight_audit, "fetch_url", return_value=head):
            out = image_weight_audit.audit_inventory(SITE, path)
        self.assertEqual(out["broken_image_count"], 1)
        self.assertEqual(out["broken"][0]["status"], 200)
        self.assertEqual(out["broken"][0]["content_type"], "text/html; charset=utf-8")
        self.assertEqual(verdict("MD-187", out), FAIL)


class TheBrokenOriginServesBothDefects(unittest.TestCase):
    """The broken tree carries a 500 and a soft 404, so each rule above is exercised by
    a served page as well as by a unit. A static file server cannot answer either; the
    tree's `_answers.json` says what to answer instead, and is itself never served —
    it is part of the tree's bytes, so `fixture_digest` moves when it does."""

    def fetch(self, url, method="GET"):
        request = urllib.request.Request(url, method=method)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, response.headers.get("Content-Type")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.headers.get("Content-Type")

    def test_the_answers_are_served_and_the_table_is_not(self):
        with harness.allow_loopback(), harness.FixtureSite() as fixture:
            broken, good = fixture.broken, fixture.good
            for method in ("GET", "HEAD"):
                with self.subTest(method=method):
                    status, _type = self.fetch(broken + "server-error.html", method)
                    self.assertEqual(status, 500)
                    status, content_type = self.fetch(
                        broken + "assets/soft-404.png", method)
                    self.assertEqual(status, 200)
                    self.assertTrue(content_type.startswith("text/html"), content_type)
            self.assertEqual(self.fetch(broken + "_answers.json")[0], 404)
            self.assertEqual(self.fetch(good + "server-error.html")[0], 404)

    def test_the_crawl_reaches_both(self):
        with harness.allow_loopback(), harness.FixtureSite() as fixture:
            inventory = site_crawl.crawl(fixture.broken, workers=1)
        statuses = {key.rsplit("/", 1)[-1]: row.get("status")
                    for key, row in inventory["pages"].items()}
        self.assertEqual(statuses.get("server-error.html"), 500)
        images = {image for row in inventory["pages"].values()
                  for image in row.get("images") or ()}
        self.assertTrue(any(image.endswith("/assets/soft-404.png") for image in images))


if __name__ == "__main__":
    unittest.main()
