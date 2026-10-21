"""EVD-10: a crawler count taken from User-Agent strings says so where it is read.

`server_log_audit.py` writes `bot_identity` on every run — "claimed, not verified" unless
`--verify-bots` confirmed the addresses — and until F04 nothing read it: no line of the
runner or the report named it, so the deliverable presented CI-018's crawler counts with
no word that a User-Agent is what the client says it is. The second scenario of EVD-10
was violated by shipped behaviour. It is now a provenance row (`reporting` REP-3),
present when a log was read without verification and absent when it was verified.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from harness import FIXTURES, SCRIPTS, offline_env, spawn, substitute, tree_served

sys.path.insert(0, SCRIPTS)
import checklist_runner as cr  # noqa: E402
import server_log_audit as sla  # noqa: E402
from checklist_report import provenance_warnings, render_html, render_markdown  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tests" / "fixtures" / "artifacts" / "good" / "access.log"
KEY = ("server_log_audit.py", (str(LOG), "--url", "http://127.0.0.1:8000/"))
CAVEAT = "User-Agent"


class Resolver:
    """Google's address confirmed both ways; nothing else resolves."""

    def reverse(self, ip):
        if ip.startswith("66.249."):
            return f"crawl-{ip.replace('.', '-')}.googlebot.com"
        raise OSError("no PTR record")

    def forward(self, host):
        return [host[len("crawl-"):].split(".")[0].replace("-", ".")]


class TheRecordSaysWhetherTheCountsAreClaims(unittest.TestCase):

    def test_an_unverified_log_is_recorded_as_claims(self):
        result = sla.audit(str(LOG))
        self.assertTrue(result["bot_identity"].startswith("claimed"))
        self.assertIs(cr.crawlers_claimed({KEY: result}), True)

    def test_a_verified_log_is_not(self):
        result = sla.audit(str(LOG), checker=sla.AddressCheck(Resolver()))
        self.assertTrue(result["bot_identity"].startswith("confirmed"))
        self.assertIsNone(cr.crawlers_claimed({KEY: result}))

    def test_a_run_with_no_log_says_nothing(self):
        self.assertIsNone(cr.crawlers_claimed({}))
        self.assertIsNone(cr.crawlers_claimed({KEY: {"__error__": "no log",
                                                     "__error_kind__": "crash"}}))

    def test_the_report_names_it_only_when_it_is_so(self):
        self.assertTrue(any(CAVEAT in w for w in
                            provenance_warnings({"log_crawlers_claimed": True})))
        self.assertFalse(any(CAVEAT in w for w in provenance_warnings({})))


class ARunWithALog(unittest.TestCase):
    """The whole path: the runner reads the log with the crawl, and both reports of the
    run say the counts are claims."""

    def test_both_reports_of_a_run_with_an_unverified_log_say_so(self):
        with tempfile.TemporaryDirectory(prefix="seo-claim-") as directory:
            work = Path(directory)
            with tree_served("good") as site:
                artifacts = work / "artifacts"
                shutil.copytree(Path(FIXTURES, "artifacts", "good"), artifacts)
                substitute(str(artifacts), "http://127.0.0.1:8000", site.base)
                target = work / "results.json"
                child = spawn([sys.executable, os.path.join(SCRIPTS, "checklist_runner.py"),
                               site.url, "--allow-private", "--max-rps", "0",
                               "--no-history", "--no-prompt", "--quiet", "--timeout", "120",
                               "--only", "crawling_indexing", "--json", str(target),
                               "--server-log", str(artifacts / "access.log")],
                              env=offline_env(), timeout=300)
                self.assertEqual(child.returncode, 0, child.stdout + child.stderr)
                data = json.loads(target.read_text(encoding="utf-8"))
        ci018 = next(row for row in data["items"] if row["id"] == "CI-018")
        self.assertIn(ci018["status"], ("PASS", "WARN", "FAIL"), ci018)
        self.assertIs(data["log_crawlers_claimed"], True)
        for output in (render_markdown(data), render_html(data)):
            self.assertIn(CAVEAT, output)


if __name__ == "__main__":
    unittest.main()
