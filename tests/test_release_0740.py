"""Release 0.74.0: MD-187 owns broken images at site-wide scope."""

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "skills", "seo-checklist", "scripts")
REGISTRY = os.path.join(
    ROOT, "skills", "seo-checklist", "resources", "config", "checklist.json")
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness  # noqa: E402
import image_weight_audit  # noqa: E402
import site_crawl  # noqa: E402
from checklist_runner import FAIL, PASS, evaluate  # noqa: E402


def verdict(item_id: str, output: dict) -> str:
    with open(REGISTRY, encoding="utf-8") as handle:
        items = {item["id"]: item for item in json.load(handle)["items"]}
    ok, _evidence = evaluate(items[item_id]["check"]["assert"], output)
    return PASS if ok else FAIL


class CrawlImageReferences(unittest.TestCase):
    def read(self, body: str) -> dict:
        return site_crawl._read_page({
            "url": "https://example.test/path/page.html",
            "status": 200,
            "headers": {"content-type": "text/html"},
            "text": f"<!doctype html><html><body>{body}</body></html>",
        }, "https://example.test/path/page.html",
            "https://example.test/path/page.html", "https://example.test/")

    def test_img_src_is_recorded_as_an_absolute_url(self):
        row = self.read('<img src="../image.png">')
        self.assertEqual(row["images"], ["https://example.test/image.png"])

    def test_srcsets_and_picture_sources_are_deduplicated_in_document_order(self):
        row = self.read("""<picture>
          <source srcset="/one.webp 1x, /two.webp 2x">
          <img src="/fallback.png" srcset="/one.webp 1x, /three.png 2x">
        </picture>""")
        self.assertEqual(row["images"], [
            "https://example.test/one.webp",
            "https://example.test/two.webp",
            "https://example.test/fallback.png",
            "https://example.test/three.png",
        ])

    def test_data_uri_is_not_recorded(self):
        self.assertEqual(self.read('<img src="data:image/gif;base64,AA==">')["images"], [])

    def test_an_img_without_a_source_records_nothing(self):
        self.assertEqual(self.read('<img alt="empty">')["images"], [])

    def test_a_page_without_images_records_an_empty_array(self):
        self.assertEqual(self.read("<p>No images.</p>")["images"], [])

    def test_only_http_and_https_schemes_are_recorded_or_fetched(self):
        schemes = ("blob:x", "file:///x.png", "javascript:x", "mailto:x@y.test")
        body = "".join(f'<img src="{url}">' for url in schemes)
        row = self.read(body)
        self.assertEqual(row["images"], [])
        path = self.inventory({"https://example.test/": row})
        with mock.patch.object(image_weight_audit, "fetch_url") as fetch:
            result = image_weight_audit.audit_inventory(
                "https://example.test/", path)
        fetch.assert_not_called()
        self.assertEqual(result["summary"]["unique_images"], 0)

    def inventory(self, pages: dict) -> str:
        folder = tempfile.TemporaryDirectory(prefix="release-0740-crawl-")
        self.addCleanup(folder.cleanup)
        path = os.path.join(folder.name, "inventory.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({
                "inventory_version": 4,
                "site": "https://example.test/",
                "entry": "https://example.test/",
                "pages": pages,
                "summary": {"truncated": False},
                "fetch_error": None,
            }, handle)
        return path


class BrokenImageRule(unittest.TestCase):
    def classify(self, status=None, error_kind=None, confirmation=None):
        result = {"status": status, "error_kind": error_kind}
        confirmation = confirmation or {"status": 200, "error_kind": None}
        with mock.patch.object(image_weight_audit, "fetch_url",
                               return_value=confirmation) as fetch:
            state, returned = image_weight_audit._classify_image(
                "https://example.test/image.png", result, 3)
        return state, returned, fetch

    def test_404_and_410_are_broken(self):
        for status in (404, 410):
            with self.subTest(status=status):
                state, _confirmation, fetch = self.classify(status=status)
                self.assertEqual(state, "broken")
                fetch.assert_not_called()

    def test_403_and_405_served_by_get_are_fine(self):
        for status in (403, 405):
            with self.subTest(status=status):
                state, _confirmation, fetch = self.classify(status=status)
                self.assertEqual(state, "fine")
                self.assertEqual(fetch.call_args.kwargs["method"], "GET")
                self.assertEqual(fetch.call_args.kwargs["extra_headers"],
                                 {"Range": "bytes=0-0"})

    def test_500_is_unchecked(self):
        state, _confirmation, fetch = self.classify(status=500)
        self.assertEqual(state, "unchecked")
        fetch.assert_not_called()

    def test_unresolved_and_refused_are_broken(self):
        for error_kind in ("unresolved", "refused"):
            with self.subTest(error_kind=error_kind):
                state, _confirmation, fetch = self.classify(error_kind=error_kind)
                self.assertEqual(state, "broken")
                fetch.assert_not_called()

    def test_timeout_and_every_5xx_are_unchecked(self):
        cases = [(None, "timeout"), (500, None), (503, None)]
        for status, error_kind in cases:
            with self.subTest(status=status, error_kind=error_kind):
                state, _confirmation, _fetch = self.classify(
                    status=status, error_kind=error_kind)
                self.assertEqual(state, "unchecked")

    def test_ranged_get_makes_a_working_403_fine(self):
        fine, _confirmation, _fetch = self.classify(
            status=403, confirmation={"status": 206, "error_kind": None})
        self.assertEqual(fine, "fine")

    def test_ranged_get_makes_a_twice_refused_403_broken(self):
        broken, _confirmation, _fetch = self.classify(
            status=403, confirmation={"status": 403, "error_kind": None})
        self.assertEqual(broken, "broken")


class SiteWideBrokenImages(unittest.TestCase):
    def inventory(self, images_by_page: list[list[str]], *, version=4,
                  truncated=False) -> str:
        pages = {}
        for index, images in enumerate(images_by_page):
            url = f"https://example.test/page-{index}"
            pages[url] = {"url": url, "final_url": url, "html": True,
                          "images": images}
        folder = tempfile.TemporaryDirectory(prefix="release-0740-images-")
        self.addCleanup(folder.cleanup)
        path = os.path.join(folder.name, "inventory.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({
                "inventory_version": version,
                "site": "https://example.test/",
                "entry": "https://example.test/",
                "pages": pages,
                "summary": {"truncated": truncated},
                "fetch_error": None,
            }, handle)
        return path

    @staticmethod
    def response(status=200, error_kind=None):
        return {"status": status, "error_kind": error_kind, "headers": {}}

    def run_with(self, path: str, side_effect, **kwargs):
        with mock.patch.object(image_weight_audit, "fetch_url",
                               side_effect=side_effect) as fetch:
            result = image_weight_audit.audit_inventory(
                "https://example.test/", path, **kwargs)
        return result, fetch

    def test_four_references_to_one_url_make_one_request(self):
        image = "https://example.test/shared.png"
        result, fetch = self.run_with(
            self.inventory([[image, image, image, image]]),
            lambda *_args, **_kwargs: self.response())
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(result["summary"]["images"], 4)
        self.assertEqual(result["summary"]["unique_images"], 1)

    def test_the_site_wide_request_is_head(self):
        image = "https://example.test/a.png"
        _result, fetch = self.run_with(
            self.inventory([[image]]), lambda *_args, **_kwargs: self.response())
        self.assertEqual(fetch.call_args.kwargs["method"], "HEAD")

    def test_broken_row_names_every_referring_page(self):
        image = "https://example.test/dead.png"
        result, _fetch = self.run_with(
            self.inventory([[image], [image]]),
            lambda *_args, **_kwargs: self.response(404))
        self.assertEqual(result["broken"][0]["pages"], [
            "https://example.test/page-0", "https://example.test/page-1"])

    def test_all_unchecked_withholds_the_broken_count(self):
        image = "https://example.test/slow.png"
        result, _fetch = self.run_with(
            self.inventory([[image]]),
            lambda *_args, **_kwargs: self.response(None, "timeout"))
        self.assertNotIn("broken_image_count", result)
        self.assertNotIn("broken_images", result)
        self.assertEqual(result["summary"]["unchecked_images"], 1)

    def test_no_images_withholds_the_broken_count(self):
        result, fetch = self.run_with(self.inventory([[]]),
                                      lambda *_args, **_kwargs: self.response())
        self.assertNotIn("broken_image_count", result)
        fetch.assert_not_called()

    def test_crawl_truncation_is_carried_through(self):
        result, _fetch = self.run_with(self.inventory([[]], truncated=True),
                                       lambda *_args, **_kwargs: self.response())
        self.assertTrue(result["truncated"])

    def test_version_3_inventory_is_refused_not_read_as_clean(self):
        result, fetch = self.run_with(
            self.inventory([["https://example.test/a.png"]], version=3),
            lambda *_args, **_kwargs: self.response())
        self.assertIn("inventory version 3", result["fetch_error"])
        self.assertNotIn("broken_image_count", result)
        fetch.assert_not_called()

    def test_fourth_page_broken_image_fails_md_187(self):
        dead = "https://example.test/fourth-dead.png"
        path = self.inventory([[], [], [], [dead]])
        result, _fetch = self.run_with(
            path, lambda *_args, **_kwargs: self.response(404))
        self.assertEqual(verdict("MD-187", result), FAIL)

    def test_every_broken_image_is_counted_not_just_the_first(self):
        images = [f"https://example.test/dead-{index}.png" for index in range(3)]
        result, fetch = self.run_with(
            self.inventory([[images[0]], [images[1]], [images[2]]]),
            lambda *_args, **_kwargs: self.response(404))
        self.assertEqual(fetch.call_count, 3)
        self.assertEqual(result["broken_image_count"], 3)
        self.assertEqual(result["broken_images"], images)

    def test_site_wide_result_has_no_markup_issues(self):
        image = "https://example.test/a.png"
        result, _fetch = self.run_with(
            self.inventory([[image]]), lambda *_args, **_kwargs: self.response())
        self.assertNotIn("issues", result)

    def test_budget_is_enforced_and_dropped_count_is_reported(self):
        count = image_weight_audit.DEFAULT_MAX_IMAGES + 1
        images = [f"https://example.test/image-{index}.png"
                  for index in range(count)]
        result, fetch = self.run_with(
            self.inventory([images]), lambda *_args, **_kwargs: self.response())
        self.assertEqual(fetch.call_count, image_weight_audit.DEFAULT_MAX_IMAGES)
        self.assertEqual(result["summary"]["images_dropped"], 1)
        self.assertEqual(result["summary"]["images_checked"],
                         image_weight_audit.DEFAULT_MAX_IMAGES)

    def test_budget_spends_requests_on_same_host_images_first(self):
        external = "https://cdn.example.net/external.png"
        internal = "https://example.test/internal.png"
        seen = []

        def answer(url, *_args, **_kwargs):
            seen.append(url)
            return self.response()

        result, _fetch = self.run_with(
            self.inventory([[external, internal]]), answer, max_images=1)
        self.assertEqual(seen, [internal])
        self.assertEqual(result["summary"]["images_dropped"], 1)


class PageModeCompatibility(unittest.TestCase):
    def test_page_mode_uses_the_shared_broken_rule(self):
        folder = tempfile.TemporaryDirectory(prefix="release-0740-page-rule-")
        self.addCleanup(folder.cleanup)
        path = os.path.join(folder.name, "page.html")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write('<html><body><img src="https://example.test/image.png">'
                         '</body></html>')
        cases = (
            ("404", [{"status": 404, "error_kind": None, "headers": {}}], 1, 0),
            ("410", [{"status": 410, "error_kind": None, "headers": {}}], 1, 0),
            ("403 served", [
                {"status": 403, "error_kind": None, "headers": {}},
                {"status": 206, "error_kind": None, "headers": {}},
            ], 0, 0),
            ("403 refused", [
                {"status": 403, "error_kind": None, "headers": {}},
                {"status": 403, "error_kind": None, "headers": {}},
            ], 1, 0),
            ("500", [{"status": 500, "error_kind": None, "headers": {}}], 0, 1),
            ("unresolved", [
                {"status": None, "error_kind": "unresolved", "headers": {}},
            ], 1, 0),
        )
        for label, responses, broken, unchecked in cases:
            with self.subTest(label=label), mock.patch.object(
                    image_weight_audit, "fetch_url", side_effect=responses):
                result = image_weight_audit.audit(path, fetch_images=True)
            self.assertEqual(result["unchecked_image_count"], unchecked)
            # The subject here is the classification — which answers make an image
            # broken and which leave it unestablished — and that has not moved. What
            # moved in 0.88.0 is how a page with an unestablished image reports the
            # count: it does not. The `500` case is this at n=1, and it is the entry
            # this release closed, spelled small. One image, one server error, no
            # broken image found and none ruled out, and the old output said
            # `broken_image_count: 0` — "no broken images on this page" drawn from
            # zero usable readings. An absent key is NO_DATA, which is the answer.
            if unchecked:
                self.assertNotIn("broken_image_count", result, label)
            else:
                self.assertEqual(result["broken_image_count"], broken)

    def test_page_mode_only_adds_unchecked_image_count(self):
        folder = tempfile.TemporaryDirectory(prefix="release-0740-page-")
        self.addCleanup(folder.cleanup)
        path = os.path.join(folder.name, "page.html")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write('<!doctype html><html><body><img src="logo.png" alt="logo" '
                         'width="10" height="20"></body></html>')
        result = image_weight_audit.audit(path)
        self.assertEqual(result.pop("unchecked_image_count"), 0)
        self.assertEqual(result, {
            "url": path,
            "image_count": 1,
            "skipped_no_src": 0,
            "images_status_checked": 0,
            "known_image_bytes": None,
            "modern_format_on_img_count": 0,
            "srcset_on_img_count": 0,
            "picture_count": 0,
            "issues": [
                {"severity": "info", "message": "Consider AVIF/WebP for raster image",
                 "url": "logo.png", "evidence": "png"},
                {"severity": "info", "message": "Image has no srcset",
                 "url": "logo.png"},
            ],
            "images": [{
                "src": "logo.png", "format": "png", "width": "10", "height": "20",
                "loading": None, "fetchpriority": None, "srcset": False,
                "sizes": False, "picture_source_count": 0,
                "picture_srcset": False, "picture_modern_formats": [],
                "likely_lcp_candidate": False, "status": None,
                "content_length": None, "content_type": None,
                # Added in 0.93.0, when MB-098 stopped deciding from issue prose.
                # False here for the reason the field exists: this `<img>` declares
                # no `srcset`, so no `sizes` is owed. An `srcset` in `x` descriptors
                # would also be False — only width descriptors need one.
                "sizes_required_and_absent": False,
                "responsive": False, "modern_format": False,
            }],
            # Added in 0.88.0. The page path had two halves of one rule and was
            # doing only one: it withheld `broken_image_count` when something went
            # unchecked, and said nothing beside a count it did emit. A page whose
            # images all answered — this one has nothing to fetch at all — reports
            # False, which is why it belongs in the pinned shape rather than beside
            # `unchecked_image_count` in the pop above.
            "truncated": False,
            "fetch_error": None,
            "modern_format_count": 0,
            "responsive_count": 0,
            # 0.93.0. Emitted whenever the page has images, because it is read from
            # markup and needs no network — unlike `large_image_count`, which is
            # absent here and above, since `known_image_bytes` is None and a page
            # nobody fetched must not report a clean weight.
            "srcset_without_sizes_count": 0,
        })


class RegistryScope(unittest.TestCase):
    def items(self) -> dict:
        with open(REGISTRY, encoding="utf-8") as handle:
            return {item["id"]: item for item in json.load(handle)["items"]}

    def test_md_187_is_the_site_wide_image_item(self):
        check = self.items()["MD-187"]["check"]
        self.assertEqual(check["requires"], "crawl")
        self.assertIn("{inventory_json}", check["args"])

    def test_the_other_six_image_items_remain_page_level(self):
        items = self.items()
        for item_id in ("MB-095", "MB-096", "MB-097", "MB-098", "MD-185", "MD-189"):
            with self.subTest(item_id=item_id):
                check = items[item_id]["check"]
                self.assertEqual(check["requires"], "fetch")
                self.assertNotIn("{inventory_json}", check["args"])

    def test_md_185_still_fetches_image_bytes(self):
        self.assertIn("--fetch-images", self.items()["MD-185"]["check"]["args"])

    def test_md_187_still_fails_broken_and_passes_good_fixture_origins(self):
        with harness.allow_loopback(), harness.FixtureSite() as fixture:
            answers = {}
            for name, site_url in (("good", fixture.good), ("broken", fixture.broken)):
                inventory = site_crawl.crawl(site_url, workers=1)
                folder = tempfile.TemporaryDirectory(prefix=f"release-0740-{name}-")
                self.addCleanup(folder.cleanup)
                path = os.path.join(folder.name, "inventory.json")
                with open(path, "w", encoding="utf-8") as handle:
                    json.dump(inventory, handle)
                answers[name] = verdict(
                    "MD-187", image_weight_audit.audit_inventory(site_url, path))
        self.assertEqual(answers, {"good": PASS, "broken": FAIL})


if __name__ == "__main__":
    unittest.main()
