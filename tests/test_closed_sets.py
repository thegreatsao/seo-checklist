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


if __name__ == "__main__":
    unittest.main()
