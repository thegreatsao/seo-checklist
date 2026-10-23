"""The census's PageSpeed stand-in, and why a real audit never meets it (F05-3).

Offline the guard refuses Google, so MB-095, SP-107, SP-108, SP-111, SP-112, SP-113 and
SE-119 answered NO_DATA on every tree the census serves, and nothing showed any of them
able to FAIL. `slow-field/` answers the API's own path with a recorded PageSpeed
Insights v5 response for a slow page, `fast-field/` with one for a fast page, and
`pagespeed.py` asks them, instead of Google, only when `SEO_PAGESPEED_STANDIN` names one
in a loopback-only process: the suite and CI are, no real audit is. These tests hold the three halves: the switch, the guard under it, and
that the recorded answer is the API's shape rather than one written to suit the parser.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "seo-checklist", "scripts"))
import harness  # noqa: E402
import pagespeed  # noqa: E402
from checklist_runner import evaluate  # noqa: E402

CORPUS = os.path.join(ROOT, "tests", "corpus")
# Each stand-in tree, and the verdict its answer gives every PageSpeed item: the census
# sees each of them both ways, as `page-defects/` and `page-sound/` do for page items.
TREES = {"slow-field": False, "fast-field": True}
ROUTE = "/pagespeedonline/v5/runPagespeed"

# Field names from Google's discovery document for the API
# (`pagespeedonline.googleapis.com/$discovery/rest?version=v5`, read 23 October 2026):
# the properties of `PagespeedApiPagespeedResponseV5`, `PagespeedApiLoadingExperienceV5`,
# `UserPageLoadMetricV5`, `Bucket`, `LighthouseResultV5` and `LighthouseAuditResultV5`.
RESPONSE_V5 = {"kind", "captchaResult", "id", "loadingExperience",
               "originLoadingExperience", "analysisUTCTimestamp", "lighthouseResult",
               "version"}
LOADING_EXPERIENCE_V5 = {"id", "metrics", "overall_category", "initial_url",
                         "origin_fallback"}
METRIC_V5 = {"metricId", "distributions", "median", "percentile", "category",
             "formFactor"}
BUCKET_V5 = {"min", "max", "proportion"}
LIGHTHOUSE_V5 = {"runtimeError", "runWarnings", "audits", "timing", "fetchTime",
                 "finalUrl", "fullPageScreenshot", "environment", "stackPacks",
                 "categoryGroups", "configSettings", "requestedUrl", "i18n",
                 "finalDisplayedUrl", "lighthouseVersion", "userAgent", "entities",
                 "mainDocumentUrl", "categories"}
AUDIT_V5 = {"id", "title", "description", "score", "scoreDisplayMode", "displayValue",
            "explanation", "errorMessage", "warnings", "details", "numericValue",
            "numericUnit", "metricSavings"}
# CrUX's three bands as the API spells them; `CRUX_RATING` reads them lower-cased.
CRUX_CATEGORIES = {"FAST", "AVERAGE", "SLOW"}


def recorded(tree: str) -> dict:
    with open(os.path.join(CORPUS, tree, "_answers.json"), encoding="utf-8") as stream:
        return json.loads(json.load(stream)[ROUTE]["body"])


def pagespeed_items() -> list[dict]:
    return [item for item in harness.registry()["items"]
            if (item.get("check") or {}).get("script") == "pagespeed.py"]


class TheStandInIsReadOnlyOffline(unittest.TestCase):
    """`SEO_LOOPBACK_ONLY` is the switch: set by `tests/harness.py` and `ci.yml`, never by
    the runner or the skill. Without it the variable is ignored and Google is asked."""

    def asked(self, env: dict) -> str:
        urls = []

        def fake(url, **_kwargs):
            urls.append(url)
            raise pagespeed.requests.exceptions.ConnectionError("not asked")

        with mock.patch.dict(os.environ, env), \
                mock.patch.object(pagespeed, "safe_get", side_effect=fake):
            pagespeed.get_pagespeed("http://127.0.0.1:9/", "mobile")
        return urls[0]

    def test_a_loopback_only_process_asks_the_stand_in(self):
        standin = "http://127.0.0.1:9" + ROUTE
        self.assertEqual(self.asked({"SEO_LOOPBACK_ONLY": "1",
                                     "SEO_PAGESPEED_STANDIN": standin}), standin)

    def test_any_other_process_asks_google_whatever_its_environment_says(self):
        self.assertEqual(self.asked({"SEO_LOOPBACK_ONLY": "",
                                     "SEO_PAGESPEED_STANDIN": "http://127.0.0.1:9" + ROUTE}),
                         pagespeed.PSI_API)

    def test_a_stand_in_that_is_not_this_machine_is_refused_not_asked(self):
        """The guard, not the script, keeps the stand-in on loopback: a name it
        refuses is never resolved, and the item reads a service error (NO_DATA)."""
        with mock.patch.dict(os.environ, {"SEO_LOOPBACK_ONLY": "1",
                                          "SEO_PAGESPEED_STANDIN":
                                              "https://psi.example.test" + ROUTE}):
            out = pagespeed.get_pagespeed("http://127.0.0.1:9/", "mobile")
        self.assertEqual(out["error_kind"], "service")
        self.assertIn("loopback-only", out["error"])


class TheRecordedAnswerIsTheApiS(unittest.TestCase):
    """Every key the recorded response carries is one the v5 API defines, spelled as it
    spells it, so a verdict on either tree is the parser's verdict on a real shape."""

    def test_it_carries_only_keys_the_api_defines(self):
        for tree in TREES:
            with self.subTest(tree=tree):
                self.check_shape(recorded(tree))

    def check_shape(self, data):
        self.assertEqual(data["kind"], "pagespeedonline#result")
        self.assertLessEqual(set(data), RESPONSE_V5)
        for name in ("loadingExperience", "originLoadingExperience"):
            with self.subTest(part=name):
                self.assertLessEqual(set(data[name]), LOADING_EXPERIENCE_V5)
                for metric_name, metric in data[name]["metrics"].items():
                    self.assertIn(metric_name, pagespeed.PSI_METRIC_MAP)
                    self.assertLessEqual(set(metric), METRIC_V5)
                    self.assertIn(metric["category"], CRUX_CATEGORIES)
                    self.assertIsInstance(metric["percentile"], int)
                    for bucket in metric["distributions"]:
                        self.assertLessEqual(set(bucket), BUCKET_V5)
                    self.assertAlmostEqual(
                        sum(b["proportion"] for b in metric["distributions"]), 1.0)
        lighthouse = data["lighthouseResult"]
        self.assertLessEqual(set(lighthouse), LIGHTHOUSE_V5)
        for audit_id, audit in lighthouse["audits"].items():
            with self.subTest(audit=audit_id):
                self.assertLessEqual(set(audit), AUDIT_V5)
                self.assertEqual(audit["id"], audit_id)

    def test_each_pagespeed_item_fails_on_one_and_passes_on_the_other(self):
        """Through the registry's own assertion, and past its warn band: a slow page
        that only warned would leave the item's FAIL unseen."""
        for (tree, passes), strategy in [(t, s) for t in TREES.items()
                                         for s in pagespeed.VALID_STRATEGIES]:
            out = pagespeed.parse_pagespeed_response(recorded(tree), "http://127.0.0.1:9/",
                                                     strategy)
            for item in pagespeed_items():
                check = item["check"]
                if strategy not in check["args"]:
                    continue
                with self.subTest(tree=tree, item=item["id"], strategy=strategy):
                    self.assertIs(evaluate(check["assert"], out)[0], passes)
                    if check.get("warn") and not passes:
                        self.assertIs(evaluate(check["warn"], out)[0], False)

    def test_every_pagespeed_item_is_one_of_the_seven(self):
        self.assertEqual(sorted(i["id"] for i in pagespeed_items()),
                         ["MB-095", "SE-119", "SP-107", "SP-108", "SP-111", "SP-112",
                          "SP-113"])


class TheTreeServesIt(unittest.TestCase):
    """End to end in-process: the tree served on loopback, the script pointed at it."""

    def test_the_script_reads_the_served_stand_in_as_slow(self):
        with tempfile.TemporaryDirectory() as workdir, harness.allow_loopback():
            site = harness._Site(os.path.join(CORPUS, "slow-field"),
                                 os.path.join(workdir, "slow-field"))
            try:
                with mock.patch.dict(os.environ,
                                     {"SEO_PAGESPEED_STANDIN": site.base + ROUTE}):
                    out = pagespeed.get_pagespeed(site.base + "/", "desktop")
            finally:
                site.stop()
        self.assertIsNone(out["error"])
        self.assertEqual(out["field_cwv"]["verdict"], "fail")
        self.assertEqual(out["page_weight"], "enormous")


if __name__ == "__main__":
    unittest.main()
