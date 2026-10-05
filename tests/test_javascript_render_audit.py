"""The render-parity audit distinguishes no measurement, a mismatch and a match."""

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "skills", "seo-checklist", "scripts")
sys.path.insert(0, SCRIPTS)

import harness  # noqa: E402
import javascript_render_audit as render_audit  # noqa: E402
from checklist_runner import evaluate  # noqa: E402

ITEMS = {item["id"]: item for item in harness.registry()["items"]}

MB_105_ASSERTION = ITEMS["MB-105"]["check"]["assert"]
URL = "https://example.com/"
RAW_HTML = """<!doctype html><html><head><title>Raw title</title></head>
<body><h1>Raw heading</h1><a href="/inside">Inside</a></body></html>"""
DIFFERENT_HTML = """<!doctype html><html><head><title>Rendered title</title></head>
<body><h1>Rendered heading</h1></body></html>"""


def audit_with(rendered_html=None, *, artifact=True):
    fetched = {"error": None}
    with tempfile.TemporaryDirectory() as tmp:
        rendered_json = None
        if artifact:
            rendered_json = os.path.join(tmp, "rendered.json")
            with open(rendered_json, "w", encoding="utf-8") as handle:
                json.dump({"html": rendered_html}, handle)
        with mock.patch.object(render_audit, "load_html",
                               return_value=(RAW_HTML, URL, fetched)):
            return render_audit.audit(URL, rendered_json=rendered_json)


class JavascriptRenderParity(unittest.TestCase):
    def test_no_artifact_omits_diffs(self):
        result = audit_with(artifact=False)

        self.assertNotIn("diffs", result)
        self.assertIsNone(result["rendered"])
        self.assertEqual(result["render_error"], "no rendered artifact provided")
        self.assertIn("raw", result)

    def test_mb_105_reports_no_data_without_a_rendered_document(self):
        result = audit_with(artifact=False)

        passed, evidence = evaluate(MB_105_ASSERTION, result)
        self.assertIsNone(passed)
        self.assertEqual(evidence, "diffs missing")

    def test_a_rendered_difference_is_present_and_fails_mb_105(self):
        result = audit_with(DIFFERENT_HTML)

        self.assertIn("diffs", result)
        self.assertGreater(len(result["diffs"]), 0)
        self.assertIs(evaluate(MB_105_ASSERTION, result)[0], False)

    def test_a_matching_render_is_present_and_passes_mb_105(self):
        result = audit_with(RAW_HTML)

        self.assertIn("diffs", result)
        self.assertEqual(result["diffs"], [])
        self.assertIs(evaluate(MB_105_ASSERTION, result)[0], True)


if __name__ == "__main__":
    unittest.main()
