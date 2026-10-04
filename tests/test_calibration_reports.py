"""The calibration tools reproduce their committed reports without rewriting them."""
import os
import subprocess
import sys
import unittest

TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "skills", "seo-checklist", "tools")


class CalibrationReports(unittest.TestCase):
    def test_each_report_still_matches_its_measurement(self):
        for name in ("css_minification", "font_weight", "gsc_sample_floors", "serp_length"):
            with self.subTest(tool=name):
                result = subprocess.run(
                    [sys.executable, os.path.join(TOOLS, f"calibrate_{name}.py"), "--check"],
                    capture_output=True, text=True, encoding="utf-8", close_fds=False)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
