"""Release 0.129.0: MB-104 reads Google's favicon page, GEO-003 reads named tokens.

Both found by running this tool on an independently built plugin's fixtures (26.09),
re-measured on 28.09, and decided by Anton the same day.

**MB-104** *Ensure Favicon Displays in Mobile SERPs*. The rule enforced a 48 px floor on
the shorter side under a basis line quoting Google as requiring "a multiple of 48px".
Google's favicon page (Search Central, *Define a favicon to show in search results*,
last updated 2026-08-28) says instead: "Your favicon must be a square (1:1 aspect ratio)
that's at least 8x8px. While the minimum size requirement is 8x8px, we recommend using
a favicon that's larger than 48x48px ... Google Search supports the following favicon
file formats: BMP, GIF, ICO, PNG, JPEG, PPM, and TIFF", and that Googlebot-Image must be
able to crawl the favicon and Googlebot the home page. So: **FAIL** when the requirement
is not met (none declared, unreachable, a page instead of an image, not square, under
8 px, or robots.txt keeping Google out); **WARN** when it is met but the icon is not
larger than 48 px or is in a format outside Google's list (SVG, WebP); **PASS** for a
square icon larger than 48 px in a listed format. `lib/image_header.py` learns the three
listed formats it could not read — BMP, PPM, TIFF — which were NO_DATA before.

**GEO-003** *AI crawler policy is explicit*. The rule passed when llms.txt existed and
nothing was restricted, so a robots.txt of `User-agent: *` alone was "explicit". Now a
token is *named* when robots.txt has a group of its own for it (RFC 9309 group
selection, not the `*` fallback), and only tokens that honour robots.txt count: **PASS**
when a named token covers both model training and answer feeding, **WARN** when some
token is named but a scope is not, **FAIL** when none is. llms.txt is GEO-001's and
GEO-002's, and leaves this item.
"""

import os
import struct
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "skills", "seo-checklist", "scripts")
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness  # noqa: E402
from harness import allow_loopback, served  # noqa: E402
from image_fixtures import valid_png as png  # noqa: E402
from registry_verdict import verdict  # noqa: E402
from checklist_runner import FAIL, NO_DATA, PASS, WARN  # noqa: E402


def items() -> dict:
    return {item["id"]: item for item in harness.registry()["items"]}



def bmp(width: int, height: int) -> bytes:
    """BITMAPFILEHEADER + BITMAPINFOHEADER; a negative height is a top-down bitmap."""
    header = struct.pack("<IiiHHIIiiII", 40, width, height, 1, 24, 0, 0, 0, 0, 0, 0)
    return b"BM" + struct.pack("<IHHI", 14 + len(header), 0, 0, 14 + len(header)) + header


def tiff(width: int, height: int, *, big_endian: bool = False, long_type: bool = False) -> bytes:
    order = ">" if big_endian else "<"
    kind, fmt = (4, "I") if long_type else (3, "H")

    def entry(tag, value):
        packed = struct.pack(order + fmt, value)
        return struct.pack(order + "HHI", tag, kind, 1) + packed.ljust(4, b"\0")
    ifd = struct.pack(order + "H", 2) + entry(256, width) + entry(257, height) + b"\0" * 4
    return (b"MM\0*" if big_endian else b"II*\0") + struct.pack(order + "I", 8) + ifd


class TheRegistryAsksGoogleAndTheNamedTokens(unittest.TestCase):
    def test_mb_104_fails_the_requirement_and_warns_below_the_recommendation(self):
        check = items()["MB-104"]["check"]
        self.assertEqual(check["assert"], {"path": "favicon.grade", "value_map": {
            "recommended": "pass", "required_only": "fail", "fails": "fail"}})
        self.assertEqual(check["warn"], {"path": "favicon.grade", "value_map": {
            "recommended": "pass", "required_only": "pass", "fails": "fail"}})

    def test_geo_003_passes_both_scopes_and_warns_on_one(self):
        check = items()["GEO-003"]["check"]
        self.assertEqual(check["assert"], {"path": "policy_grade", "value_map": {
            "explicit": "pass", "partial": "fail", "silent": "fail"}})
        self.assertEqual(check["warn"], {"path": "policy_grade", "value_map": {
            "explicit": "pass", "partial": "pass", "silent": "fail"}})


class TheFormatsGoogleListsAreRead(unittest.TestCase):
    def read(self, data):
        from lib.image_header import image_header
        return image_header(data)

    def test_bmp_either_row_order(self):
        self.assertEqual(self.read(bmp(64, 64)), ("bmp", 64, 64))
        self.assertEqual(self.read(bmp(64, -32)), ("bmp", 64, 32))

    def test_ppm_and_the_other_netpbm_headers_with_comments(self):
        self.assertEqual(self.read(b"P6\n# made by hand\n96 96\n255\n" + b"\0" * 9),
                         ("ppm", 96, 96))
        self.assertEqual(self.read(b"P3 16\t 8 255\n0 0 0"), ("ppm", 16, 8))

    def test_tiff_in_both_byte_orders_and_both_integer_types(self):
        for big in (False, True):
            for long_type in (False, True):
                with self.subTest(big_endian=big, long_type=long_type):
                    self.assertEqual(
                        self.read(tiff(128, 128, big_endian=big, long_type=long_type)),
                        ("tiff", 128, 128))

    def test_a_truncated_header_is_not_a_size(self):
        self.assertIsNone(self.read(b"BM\0\0"))
        self.assertIsNone(self.read(b"II*\0\x08\0\0\0"))
        self.assertIsNone(self.read(b"P6\n"))


class AFaviconIsGradedAsGoogleWritesIt(unittest.TestCase):
    PAGE = ('<!doctype html><html><head><title>Icon test</title>'
            '<link rel="icon" href="/icon"></head><body></body></html>')

    def grade(self, body, content_type="image/png", status=200, robots=None,
              page=None):
        import favicon_check
        routes = {"/": page or self.PAGE,
                  "/icon": (status, {"Content-Type": content_type}, body)}
        if robots is not None:
            routes["/robots.txt"] = (200, {"Content-Type": "text/plain"}, robots)
        with allow_loopback(), served(routes) as site:
            return favicon_check.check(site.url)

    def assertGrade(self, result, grade, status):
        self.assertEqual(result["favicon"].get("grade"), grade, result["favicon"])
        self.assertEqual(verdict("MB-104", result), status)

    def test_a_square_icon_larger_than_48_in_a_listed_format_passes(self):
        result = self.grade(png(96, 96))
        self.assertGrade(result, "recommended", PASS)
        self.assertIs(result["favicon"]["square"], True)
        self.assertIs(result["favicon"]["google_format"], True)

    def test_exactly_48_meets_the_requirement_and_not_the_recommendation(self):
        """Google recommends *larger than* 48x48px."""
        self.assertGrade(self.grade(png(48, 48)), "required_only", WARN)

    def test_eight_is_the_floor(self):
        self.assertGrade(self.grade(png(8, 8)), "required_only", WARN)
        self.assertGrade(self.grade(png(7, 7)), "fails", FAIL)

    def test_a_non_square_icon_fails_however_large(self):
        result = self.grade(png(192, 96))
        self.assertGrade(result, "fails", FAIL)
        self.assertIs(result["favicon"]["square"], False)
        self.assertIn("192x96", result["favicon"]["reason"])

    def test_formats_outside_googles_list_warn(self):
        svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"></svg>'
        for body, content_type in ((svg, "image/svg+xml"),
                                   (b"RIFF\0\0\0\0WEBPVP8X" + b"\0" * 4
                                    + b"\0\0\0\0" + (63).to_bytes(3, "little")
                                    + (63).to_bytes(3, "little"), "image/webp")):
            with self.subTest(content_type=content_type):
                result = self.grade(body, content_type)
                self.assertGrade(result, "required_only", WARN)
                self.assertIs(result["favicon"]["google_format"], False)

    def test_the_formats_it_could_not_read_before_are_graded(self):
        self.assertGrade(self.grade(bmp(64, 64), "image/bmp"), "recommended", PASS)
        self.assertGrade(self.grade(tiff(64, 64), "image/tiff"), "recommended", PASS)

    def test_an_icon_url_answering_a_page_fails(self):
        result = self.grade("<!doctype html><title>Not found</title>", "text/html")
        self.assertGrade(result, "fails", FAIL)
        self.assertIn("page", result["favicon"]["reason"])

    def test_robots_keeping_googlebot_image_from_the_icon_fails(self):
        result = self.grade(png(96, 96),
                            robots="User-agent: Googlebot-Image\nDisallow: /icon\n")
        self.assertGrade(result, "fails", FAIL)
        self.assertIn("Googlebot-Image", result["favicon"]["reason"])

    def test_robots_keeping_googlebot_from_the_home_page_fails(self):
        result = self.grade(png(96, 96), robots="User-agent: Googlebot\nDisallow: /\n")
        self.assertGrade(result, "fails", FAIL)
        self.assertIn("Googlebot", result["favicon"]["reason"])

    def test_an_unreadable_image_is_still_no_data(self):
        result = self.grade(b"", "application/octet-stream")
        self.assertNotIn("grade", result["favicon"])
        self.assertEqual(verdict("MB-104", result), NO_DATA)


class AnAiCrawlerPolicyIsExplicitWhenItNamesTheCrawler(unittest.TestCase):
    LLMS = "# Site\n\n> A site.\n\n## Pages\n- [Home](/): the home page\n"

    def matrix(self, robots=None, llms=True):
        import ai_crawler_policy_matrix as matrix
        routes = {"/": "<!doctype html><title>x</title>"}
        if robots is not None:
            routes["/robots.txt"] = (200, {"Content-Type": "text/plain"}, robots)
        if llms:
            routes["/llms.txt"] = (200, {"Content-Type": "text/plain"}, self.LLMS)
        with allow_loopback(), served(routes) as site:
            return matrix.matrix(site.url)

    def test_a_wildcard_policy_with_an_llms_txt_names_nothing(self):
        """The cross-test's finding: this passed as `documented`."""
        out = self.matrix("User-agent: *\nDisallow: /private/\n")
        self.assertEqual(out["policy_grade"], "silent")
        self.assertFalse(any(row["named"] for row in out["rows"]))
        self.assertEqual(verdict("GEO-003", out), FAIL)

    def test_no_robots_txt_is_silence(self):
        self.assertEqual(verdict("GEO-003", self.matrix(None, llms=False)), FAIL)

    def test_one_scope_named_warns_and_says_which(self):
        out = self.matrix("User-agent: *\nDisallow:\n\nUser-agent: GPTBot\nDisallow: /\n")
        self.assertEqual(out["policy_grade"], "partial")
        self.assertEqual(out["named_scopes"]["model_training"], ["GPTBot"])
        self.assertEqual(out["named_scopes"]["answer_feeding"], [])
        self.assertEqual(verdict("GEO-003", out), WARN)

    def test_both_scopes_named_passes_whatever_each_decides(self):
        out = self.matrix("User-agent: gptbot\nDisallow: /\n\n"
                          "User-agent: OAI-SearchBot\nAllow: /\n")
        self.assertEqual(out["policy_grade"], "explicit")
        self.assertEqual(verdict("GEO-003", out), PASS)

    def test_a_token_that_ignores_robots_txt_names_nothing(self):
        """Perplexity-User generally ignores robots.txt; a rule for it is a wish."""
        out = self.matrix("User-agent: GPTBot\nDisallow: /\n\n"
                          "User-agent: Perplexity-User\nDisallow: /\n")
        self.assertEqual(out["named_scopes"]["answer_feeding"], [])
        self.assertEqual(out["policy_grade"], "partial")


if __name__ == "__main__":
    unittest.main()
