"""MB-095 *Keep Mobile Page Weight Light*, and the one number that answers it: the bytes
Lighthouse's mobile run downloaded.

Until 0.119.0 the item counted images over 250 KB and allowed five — so a page of 5 MB of
JavaScript and small images passed, and so did five 240 KB images. Page weight, the bytes a
phone downloads, was never totalled. `pagespeed.py --strategy mobile` already runs for the
Core Web Vitals items with the same arguments, and its Lighthouse result carries the
`total-byte-weight` audit: every resource the page requested in a mobile run, the ones
scripts add included. That is the title, and it costs no extra request.

The bands are Lighthouse's own, from its documentation of that audit ("Avoid enormous
network payloads", developer.chrome.com, last updated 2019-05-02): *aim to keep your total
byte size below 1,600 KiB* — what a 3G connection downloads with Time to Interactive at ten
seconds — and *Lighthouse flags pages whose total network requests exceed 5,000 KiB*.
Below the first is `light`; up to the second is `heavy`, a warning; past it is `enormous`.

No network: `parse_pagespeed_response` is the whole contract, as for the other PSI items.
"""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPTS = os.path.join(ROOT, "skills", "seo-checklist", "scripts")
REGISTRY = os.path.join(ROOT, "skills", "seo-checklist", "resources", "config",
                        "checklist.json")
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)

from checklist_runner import FAIL, NO_DATA, PASS, WARN, evaluate  # noqa: E402
import pagespeed as ps  # noqa: E402

KIB = 1024


def rule() -> dict:
    with open(REGISTRY, encoding="utf-8") as f:
        return {i["id"]: i for i in json.load(f)["items"]}["MB-095"]["check"]


def verdict(output: dict) -> str:
    check = rule()
    ok, _ = evaluate(check["assert"], output)
    if ok is None:
        return NO_DATA
    if ok:
        return PASS
    warn = check.get("warn")
    if warn and evaluate(warn, output)[0]:
        return WARN
    return FAIL


def payload(total_bytes=None, audit=True):
    audits = {"largest-contentful-paint": {"numericValue": 1500}}
    if audit:
        audits["total-byte-weight"] = ({} if total_bytes is None
                                       else {"numericValue": total_bytes})
    return {"lighthouseResult": {"categories": {"performance": {"score": 0.9}},
                                 "audits": audits}}


def parse(data, strategy="mobile"):
    return ps.parse_pagespeed_response(data, "https://example.com/", strategy)


class ThePageWeightIsLighthousesTotal(unittest.TestCase):

    def test_the_total_is_carried_in_bytes(self):
        out = parse(payload(1_234_567.8))
        self.assertEqual(out["total_byte_weight"], 1_234_567)

    def test_the_bands_are_lighthouses_published_lines(self):
        cases = [
            (0, "light", PASS),
            (1600 * KIB - 1, "light", PASS),
            (1600 * KIB, "heavy", WARN),       # "below 1,600 KiB" is the target
            (5000 * KIB, "heavy", WARN),       # "exceed 5,000 KiB" is what is flagged
            (5000 * KIB + 1, "enormous", FAIL),
        ]
        for total, band, status in cases:
            with self.subTest(total=total):
                out = parse(payload(total))
                self.assertEqual(out["page_weight"], band)
                self.assertEqual(verdict(out), status)

    def test_a_page_the_old_rule_passed_fails(self):
        """Six megabytes of scripts and no image over 250 KB: `large_image_count` was
        zero and the item passed."""
        out = parse(payload(6 * 1024 * KIB))
        self.assertEqual(out["page_weight"], "enormous")
        self.assertEqual(verdict(out), FAIL)

    def test_no_audit_no_verdict(self):
        for data in (payload(audit=False), payload(None), payload("12 MB"), payload(-1),
                     {"lighthouseResult": {}}, {}):
            with self.subTest(data=data):
                out = parse(data)
                self.assertNotIn("page_weight", out)
                self.assertNotIn("total_byte_weight", out)
                self.assertEqual(verdict(out), NO_DATA)

    def test_the_constants_are_the_documented_numbers(self):
        self.assertEqual(ps.PAGE_WEIGHT_TARGET_KIB, 1600)
        self.assertEqual(ps.PAGE_WEIGHT_FLAG_KIB, 5000)
        self.assertEqual(ps.PAGE_WEIGHT_BANDS, ("light", "heavy", "enormous"))


class TheRuleReadsTheMobileRun(unittest.TestCase):

    def test_the_rule_is_the_shared_mobile_invocation(self):
        check = rule()
        self.assertEqual(check["script"], "pagespeed.py")
        self.assertEqual(check["args"], ["{url}", "--strategy", "mobile"])
        self.assertEqual(check["assert"]["path"], "page_weight")
        self.assertEqual(set(check["assert"]["value_map"]), set(ps.PAGE_WEIGHT_BANDS))
        self.assertEqual(set(check["warn"]["value_map"]), set(ps.PAGE_WEIGHT_BANDS))
        # The same arguments as the Core Web Vitals items, so one PSI call serves all.
        with open(REGISTRY, encoding="utf-8") as f:
            items = {i["id"]: i for i in json.load(f)["items"]}
        self.assertEqual(check["args"], items["SP-107"]["check"]["args"])
        self.assertEqual(check["requires"], items["SP-107"]["check"]["requires"])


if __name__ == "__main__":
    unittest.main()
