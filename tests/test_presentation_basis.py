"""A `presentation` basis is a claim that no verdict reads the number (F11).

`tools/audit_thresholds.py` takes a basis line at its word, so a number filed as
`presentation` leaves "numbers a verdict depends on" on the line's say-so. F11 moved
twenty-three numbers there because the field each one feeds is read by no registry item —
or, for an entry in `issues`, read by none at the severity the number raises. The claim
stops being true the day an item reads that field, and this is what says so: each row
below names the script, the field, the registry severity of what the number writes there
(None for a field with no severity), and the numbers that rest on it.
"""
from __future__ import annotations

import json
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "seo-checklist", "scripts"))
REGISTRY = os.path.join(ROOT, "skills", "seo-checklist", "resources", "config",
                        "checklist.json")

from checklist_runner import SEVERITY_ALIAS  # noqa: E402

UNREAD = {
    "security_headers.py": [
        ("score", None, ("SECURITY_HEADERS",)),
        ("issues", None, ("MANY_MISSING_HEADERS",)),
    ],
    "domain_safety_check.py": [("issues", "medium", ("SLOW_RESPONSE_MS",)),
                               ("issues", "low", ("YOUNG_DOMAIN_DAYS",))],
    "faceted_nav_audit.py": [
        ("rows", None, ("PARAM_COMBINATION_COUNT",)),
        ("frequent_params", None, ("FREQUENT_PARAM_COUNT",)),
        ("issues", SEVERITY_ALIAS["info"], ("FREQUENT_PARAM_COUNT",))],
    "article_seo.py": [
        ("readability", None, ("SHORT_WORD_LETTERS",)),
        ("extracted_keywords", None, ("MIN_UNIGRAM_COUNT",)),
        ("target_keyword", None, ("MIN_UNIGRAM_COUNT",)),
        ("seo_issues", None, ("BLOG_THIN_WORDS", "MAX_EAGER_IMAGES")),
        ("related_keywords", None, ("MIN_RELATED_KEYWORDS",)),
    ],
    "third_party_script_audit.py": [
        ("issues", None, ("MANY_THIRD_PARTY_SCRIPTS", "THIRD_PARTY_BYTES_WARN"))],
    "html_validator.py": [("issues", None, ("MANY_WARNINGS",))],
    "pagespeed.py": [("opportunities", None, ("MIN_OPPORTUNITY_SAVINGS_MS",))],
    "internal_links.py": [
        ("summary.pages_under_three_links", None, ("LOW_OUTLINKS",)),
        ("summary.pages_over_hundred_links", None, ("HIGH_OUTLINKS",)),
        ("issues", None, ("LOW_OUTLINKS", "HIGH_OUTLINKS")),
        ("recommendations", None, ("LOW_AVERAGE_OUTLINKS",)),
    ],
    "cache_compression_checker.py": [
        ("issues", SEVERITY_ALIAS["info"], ("STATIC_IMMUTABLE_MAX_AGE",)),
        ("resources.issues", SEVERITY_ALIAS["info"], ("STATIC_IMMUTABLE_MAX_AGE",))],
    "duplicate_content.py": [("thin_content", None, ("NEARLY_EMPTY_WORDS",))],
    "freshness_checker.py": [("issues", None, ("STALE_CONTENT_DAYS",))],
    "collection_page_checker.py": [
        ("issues", SEVERITY_ALIAS["info"], ("MIN_PRODUCT_LINKS",))],
    "lcp_subparts.py": [
        (f"subparts.{field}", None, ("MS_IF_ABOVE",))
        for field in ("resource_load_delay_ms", "resource_load_duration_ms",
                      "element_render_delay_ms")],
}


def rules(check: dict) -> list[dict]:
    """Every leaf rule an item's check reads, through `all`/`any`-style nesting."""
    found = []

    def walk(node):
        if isinstance(node, dict):
            if isinstance(node.get("path"), str):
                found.append(node)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk([check.get(k) for k in ("assert", "warn", "applies_when")])
    return found


def _segments(path: str) -> list[str]:
    """A rule path as named segments: list indices (`rows.0.flags`) say nothing about
    which field is read, so they drop out."""
    parts = re.split(r"[.\[\]]+", path)
    return [p for p in parts if p and not p.isdigit()]


def reads(rule: dict, field: str, severity: str | None) -> bool:
    """Whether a rule can see what the number writes at `field`.

    The rule's effective path is its `path`, then its `field` where the runner applies
    one (`none_matching` and `value_map` read `field` of each element under `path`;
    every other operator reads the whole value at `path`, `field` or not). It reads
    `field` when either path contains
    the other: reading `quality` reads `quality.issues`, and reading
    `summary.pages_under_three_links.x` reads the summary field. A `none_severity` rule
    counts only the severities it lists, both sides read through `SEVERITY_ALIAS` as
    the runner does."""
    narrows = rule.get("field") and ("none_matching" in rule or "value_map" in rule)
    effective = _segments(rule["path"]) + ([rule["field"]] if narrows else [])
    wanted = _segments(field)
    shorter = min(len(effective), len(wanted))
    if effective[:shorter] != wanted[:shorter]:
        return False
    counted = rule.get("none_severity")
    if severity and isinstance(counted, list):
        levels = {SEVERITY_ALIAS.get(s.lower(), s.lower()) for s in counted}
        return SEVERITY_ALIAS.get(severity, severity) in levels
    return True


class APresentationNumberFeedsNoVerdict(unittest.TestCase):

    def setUp(self):
        with open(REGISTRY, encoding="utf-8") as handle:
            self.items = json.load(handle)["items"]

    def test_no_item_reads_what_a_presentation_number_writes(self):
        for script, rows in UNREAD.items():
            over = [i for i in self.items
                    if (i.get("check") or {}).get("script") == script]
            self.assertTrue(over, f"no item runs {script}: the census reads nothing")
            for item in over:
                for field, severity, names in rows:
                    with self.subTest(item=item["id"], field=field):
                        hit = [r["path"] for r in rules(item["check"])
                               if reads(r, field, severity)]
                        self.assertFalse(hit, f"{item['id']} reads {field}, which "
                                              f"{', '.join(names)} decide: their "
                                              f"`presentation` basis is no longer true")

    def test_every_name_here_is_filed_as_presentation(self):
        """The census and the basis lines are one claim; neither may move alone."""
        sys.path.insert(0, os.path.join(ROOT, "skills", "seo-checklist", "tools"))
        import audit_thresholds
        named, _ = audit_thresholds.scan()
        kinds = {(os.path.basename(row["file"]), row["name"]): row["kind"]
                 for row in named}
        for script, rows in UNREAD.items():
            for _field, _severity, names in rows:
                for name in names:
                    with self.subTest(name=name):
                        self.assertEqual(kinds.get((script, name)), "presentation")


if __name__ == "__main__":
    unittest.main()
