"""`detect_profile.py`'s CLEAR_MARGIN decides what is printed, not the profile (F11).

`--profile auto` runs under the detector's `profile` whatever its `confidence`, so the
margin between the best and the second score — which sets `confidence` and `runner_up` —
reaches the prompt and the stderr line only. That is the `presentation` claim on its
basis line, held here by asking `choose_profile` and `detect` directly: the day auto
starts to require a confident answer, the margin decides scope and this goes red.
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "seo-checklist", "scripts"))

import checklist_runner  # noqa: E402
import detect_profile  # noqa: E402

# Shopify (4) and a cart link (3) for ecommerce, a pricing page (3) for saas: 7 against 3.
PAGE = ('<html><head><link rel="stylesheet" href="https://cdn.shopify.com/t.css"></head>'
        '<body><a href="/cart">cart</a><a href="/pricing">pricing</a></body></html>')


class TheMarginDecidesNoProfile(unittest.TestCase):

    def test_auto_runs_the_answer_whatever_its_confidence(self):
        for confidence in ("high", "low"):
            with self.subTest(confidence=confidence):
                detected = {"profile": "ecommerce", "confidence": confidence,
                            "signals": {"ecommerce": ["Shopify"]}, "runner_up": None}
                self.assertEqual(
                    checklist_runner.choose_profile("auto", False, detected), "ecommerce")

    def test_the_margin_moves_the_confidence_and_not_the_answer(self):
        answers = set()
        for margin in (1, 4, 50):
            with self.subTest(margin=margin), \
                    mock.patch.object(detect_profile, "CLEAR_MARGIN", margin):
                found = detect_profile.detect(PAGE)
                answers.add(found["profile"])
        self.assertEqual(answers, {"ecommerce"})
        with mock.patch.object(detect_profile, "CLEAR_MARGIN", 50):
            self.assertEqual(detect_profile.detect(PAGE)["confidence"], "low")


class AScoreOfFourIsNotEnough(unittest.TestCase):
    """F11, Anton's decision: MIN_SCORE 5, measured. A byline, article timestamps and a
    blog link score `blog` 4 — python.org's homepage in the corpus, the one answer at 4
    that made applicable items N/A (`blog` excludes 8). At 5 it is `default`."""

    PAGE = ('<html><body><a rel="author" href="/team">Team</a>'
            '<time datetime="2026-10-01">1 Oct</time><a href="/blog">Blog</a></body></html>')

    def test_a_page_that_scores_four_is_not_narrowed(self):
        found = detect_profile.detect(self.PAGE)
        self.assertEqual(found["scores"]["blog"], 4, found["signals"])
        self.assertEqual(found["profile"], "default")
        self.assertEqual(checklist_runner.choose_profile("auto", False, found), "default")


if __name__ == "__main__":
    unittest.main()
