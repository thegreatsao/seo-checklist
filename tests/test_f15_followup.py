"""F15's follow-up: the owner's rulings 1 and 4 on batch 7's questions (2026-11-12,
docs/sprint-20261109-F15.md, "The owner's rulings on batch 7's questions").

1. TECH-002's icon fonts are the families `font_audit.ICON_FONT_FAMILIES` lists, widened
   past what a sentence can name; the `measures` sentence names three and the constant.
4. GO-145 and GEO-005 read a utility word as a utility page only when the slug is the
   first path segment, or when the path sits under `/legal/`.

Each verdict is the item's real rule from the registry over the script's real output.
"""
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "skills", "seo-checklist", "scripts")
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness  # noqa: E402,F401  (the switches and tripwire, run alone)
import citation_readiness  # noqa: E402
from checklist_runner import FAIL, NA, PASS  # noqa: E402
from test_f15_batch4 import ITEMS  # noqa: E402
from test_f15_batch5 import html, page_verdict  # noqa: E402
import test_f15_batch6  # noqa: E402  (by module: an imported TestCase would run here too)
import test_f15_batch7  # noqa: E402

RU = json.load(open(os.path.join(ROOT, "skills", "seo-checklist", "resources", "i18n",
                                 "ru.json"), encoding="utf-8"))["item_measures"]


class IconFontList(unittest.TestCase):
    """Family names as each project's published CSS declares them."""

    def tech(self, family: str) -> str:
        return test_f15_batch7.IconFonts.tech(self, family)

    def test_the_ruled_and_common_families_are_icon_fonts(self):
        for family in ("star", "WooCommerce", "ETmodules", '"Material Design Icons"',
                       "'boxicons'", '"tabler-icons"', "'simple-line-icons'", "'slick'",
                       '"remixicon"', "'themify'", '"IcoFont"', '"typicons"', '"Genericons"',
                       '"Genericons-Neue"', '"foundation-icons"', "'Linearicons-Free'",
                       "'feather'", '"Phosphor"', '"Phosphor-Bold"', "'Pe-icon-7-stroke'",
                       "'ElegantIcons'"):
            with self.subTest(family=family):
                self.assertEqual(self.tech(family), PASS)

    def test_a_word_family_is_matched_whole(self):
        for family in ('"Stardos Stencil"', "Starlight", '"Slick Sans"', "Feathergraphy",
                       "Roboto"):
            with self.subTest(family=family):
                self.assertEqual(self.tech(family), FAIL)

    def test_the_whole_names_are_listed_families(self):
        from font_audit import ICON_FONT_FAMILIES, WHOLE_NAME_ONLY
        self.assertEqual(WHOLE_NAME_ONLY, {"star", "slick", "feather", "lg"})
        self.assertLessEqual(WHOLE_NAME_ONLY, set(ICON_FONT_FAMILIES))

    def test_the_sentence_names_three_and_the_constant(self):
        for sentence in (ITEMS["TECH-002"]["measures"], RU["TECH-002"]):
            with self.subTest(sentence=sentence):
                self.assertIn("ICON_FONT_FAMILIES", sentence)
                for name in ("Font Awesome", "Material Icons", "WooCommerce"):
                    self.assertIn(name, sentence)
                self.assertNotIn("Glyphicons", sentence)
                self.assertLessEqual(len(sentence), 240)


class UtilityPathRule(unittest.TestCase):

    def both(self, path: str) -> tuple:
        page = html(test_f15_batch6.UtilityPages.BODY, head='<link rel="canonical" href="' + path + '">')
        return tuple(page_verdict(citation_readiness, item, page, path=path)
                     for item in ("GO-145", "GEO-005"))

    def test_a_utility_word_below_the_top_level_is_a_content_page(self):
        for path in ("/glossary/terms", "/blog/privacy", "/help/contact", "/en/privacy",
                     "/privacy/cookies", "/docs/terms-of-service", "/terms/a/apr.asp",
                     "/glossary/terms/amp"):
            with self.subTest(path=path):
                self.assertEqual(self.both(path), (FAIL, FAIL))

    def test_top_level_and_legal_pages_stay_utility_pages(self):
        for path in ("/terms", "/privacy-policy/", "/contact/index.html", "/legal",
                     "/legal/", "/legal/terms", "/legal/privacy-policy.html",
                     "/legal/cookies/amp", "/LEGAL/Terms", "/legal/en/privacy"):
            with self.subTest(path=path):
                self.assertEqual(self.both(path), (NA, NA))

    def test_legal_holds_utility_words_only(self):
        for path in ("/legal/how-we-bake", "/legal/blog/post"):
            with self.subTest(path=path):
                self.assertEqual(self.both(path), (FAIL, FAIL))

    def test_the_sentences_state_the_path_rule(self):
        for item_id in ("GO-145", "GEO-005"):
            for sentence in (ITEMS[item_id]["measures"], RU[item_id]):
                with self.subTest(item=item_id, sentence=sentence):
                    self.assertIn("/legal/", sentence)
                    self.assertLessEqual(len(sentence), 240)


class ReviewRound1(unittest.TestCase):

    def both(self, path: str) -> tuple:
        return UtilityPathRule.both(self, path)

    def test_a_front_controller_or_amp_prefix_is_not_a_segment(self):
        """Joomla's default URLs and WordPress PATHINFO permalinks put the page after
        `index.php`; an AMP prefix mirrors the `/amp` suffix already dropped."""
        for path in ("/index.php/privacy-policy", "/index.php/contact/", "/amp/privacy",
                     "/index.php/legal/terms"):
            with self.subTest(path=path):
                self.assertEqual(self.both(path), (NA, NA))
        for path in ("/index.php/blog/privacy", "/amp/glossary/terms"):
            with self.subTest(path=path):
                self.assertEqual(self.both(path), (FAIL, FAIL))

    def test_a_legal_file_is_no_legal_folder(self):
        for path in ("/legal.html/privacy", "/legal.php/terms"):
            with self.subTest(path=path):
                self.assertEqual(self.both(path), (FAIL, FAIL))

    def test_more_common_icon_fonts(self):
        """As video.js, lightGallery, PrimeIcons, VS Code's codicons, Material Design
        Iconic Font and the Fontello and IcoMoon generators declare them."""
        for family in ("VideoJS", "lg", "primeicons", "codicon",
                       "'Material-Design-Iconic-Font'", "fontello", "icomoon"):
            with self.subTest(family=family):
                self.assertEqual(IconFontList.tech(self, family), PASS)
        for family in ("Lgothic", '"LG Smart"'):
            with self.subTest(family=family):
                self.assertEqual(IconFontList.tech(self, family), FAIL)


class ReviewRound2(unittest.TestCase):

    def test_magentos_default_icon_fonts(self):
        """Luma's `@icons__font-name` and the Blank theme's, emitted with
        `font-display: block` by Magento 2's `_icons.less`."""
        for family in ("'luma-icons'", "'icons-blank-theme'"):
            with self.subTest(family=family):
                self.assertEqual(IconFontList.tech(self, family), PASS)

    def test_every_trailing_index_and_amp_segment_is_dropped(self):
        for path in ("/privacy/amp/index.html", "/contact/index.php/amp"):
            with self.subTest(path=path):
                self.assertEqual(UtilityPathRule.both(self, path), (NA, NA))
        self.assertEqual(UtilityPathRule.both(self, "/glossary/terms/amp/index.html"),
                         (FAIL, FAIL))


class ReviewRound3(unittest.TestCase):

    def test_flexslider_and_the_feather_webfont(self):
        """FlexSlider 2's arrows (MetaSlider's default slider) and feather-webfont's
        `feather-icons`, as their published CSS declares them."""
        for family in ("flexslider-icon", '"feather-icons"'):
            with self.subTest(family=family):
                self.assertEqual(IconFontList.tech(self, family), PASS)
        self.assertEqual(IconFontList.tech(self, "Feathergraphy"), FAIL)


if __name__ == "__main__":
    unittest.main()
