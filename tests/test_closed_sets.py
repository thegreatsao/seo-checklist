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



class SchemaOrgTypesAreTheVocabulary(unittest.TestCase):
    """The type sets the entity, local and E-E-A-T checks decide by, derived from one
    dated schema.org snapshot (`resources/config/schemaorg-types.json`).

    Written in F04 (batch 4b). Until then `LOCAL_BUSINESS_TYPES` was a hand copy that
    lacked 31 of the 152 `LocalBusiness` types and carried two that are not, and the two
    organization sets held 5 of 188: a hospital's LocalBusiness markup read as none
    (LO-198), and a restaurant naming itself publisher read as no publisher (CN-057)."""

    # Release 30.1 (2026-09-16), as served on 2026-10-22. The counts are the
    # vocabulary's, re-derived from the release file, never from the sets.
    RELEASE = ("30.1", "2026-09-16")
    SOURCE_SHA256 = "0a4b8c4c910fc831ec8695196510973390906a5ee34dc6b862dfec4d21a12f74"
    COUNTS = {"types": 961, "LocalBusiness": 152, "Organization": 188, "Place": 230}

    @classmethod
    def setUpClass(cls):
        from lib import schema_types
        cls.lib = schema_types

    def test_the_snapshot_is_the_release_it_names(self):
        snapshot = self.lib.SNAPSHOT
        self.assertEqual((snapshot["release"], snapshot["date"]), self.RELEASE)
        self.assertEqual(snapshot["sha256"], self.SOURCE_SHA256)
        self.assertEqual(snapshot["source"],
                         "https://schema.org/version/30.1/schemaorg-current-https.jsonld")
        self.assertEqual(len(snapshot["types"]), self.COUNTS["types"])

    def test_each_set_is_every_descendant_of_its_root(self):
        for name, root in (("LOCAL_BUSINESS_TYPES", "LocalBusiness"),
                           ("ORGANIZATION_TYPES", "Organization"),
                           ("PLACE_TYPES", "Place")):
            with self.subTest(root=root):
                types = getattr(self.lib, name)
                self.assertEqual(len(types), self.COUNTS[root])
                self.assertIn(root, types)

    def test_the_types_the_hand_copy_had_wrong(self):
        for name in ("Hospital", "MedicalClinic", "Attorney", "PostOffice",
                     "Dermatology", "VacationRental"):
            self.assertIn(name, self.lib.LOCAL_BUSINESS_TYPES, name)
        for name in ("VeterinaryCare", "SkatingRink"):
            self.assertNotIn(name, self.lib.LOCAL_BUSINESS_TYPES, name)
        self.assertIn("VeterinaryCare", self.lib.ORGANIZATION_TYPES)

    def test_a_hospital_is_a_local_business(self):
        """LO-198 read a hospital's markup as no LocalBusiness at all."""
        from local_seo_checker import find_local_business_nodes
        for schema_type in ("Hospital", "Attorney", "Dermatology", "PostOffice"):
            with self.subTest(schema_type=schema_type):
                self.assertEqual(len(find_local_business_nodes(
                    [{"@type": schema_type, "name": "X"}])), 1)
        self.assertEqual(find_local_business_nodes(
            [{"@type": "VeterinaryCare", "name": "X"}]), [])

    def test_every_organization_type_is_an_entity(self):
        """GEO-006 collected sameAs only from five organization types."""
        from bs4 import BeautifulSoup
        import entity_checker
        for schema_type in ("NGO", "Airline", "Restaurant", "Museum", "Park"):
            with self.subTest(schema_type=schema_type):
                html = ('<script type="application/ld+json">{"@type": "%s", '
                        '"name": "X", "sameAs": ["https://www.wikidata.org/wiki/Q1"]}'
                        '</script>' % schema_type)
                entities = entity_checker.extract_entities_from_schema(
                    BeautifulSoup(html, "html.parser"))
                self.assertEqual([e["type"] for e in entities], [schema_type])
        self.assertIs(entity_checker.ORGANIZATION_TYPES, self.lib.ORGANIZATION_TYPES)
        self.assertIs(entity_checker.PLACE_TYPES, self.lib.PLACE_TYPES)

    def test_every_organization_type_is_a_publisher(self):
        """CN-057 counted a restaurant or a dentist naming itself as no publisher."""
        import eeat_signal_checker
        for schema_type in ("Restaurant", "Dentist", "NGO", "https://schema.org/Store"):
            self.assertTrue(eeat_signal_checker._is_org_type(schema_type), schema_type)
        for schema_type in ("WebPage", "Person", "Article"):
            self.assertFalse(eeat_signal_checker._is_org_type(schema_type), schema_type)


if __name__ == "__main__":
    unittest.main()
