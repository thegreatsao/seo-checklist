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
    """Reverse and forward DNS written down: Google's and Bing's addresses confirm both
    ways when `confirm` names the crawler, and nothing else resolves."""

    NAMES = {"66.249.66.1": ("Googlebot", "crawl-66-249-66-1.googlebot.com"),
             "157.55.39.1": ("bingbot", "msnbot-157-55-39-1.search.msn.com")}

    def __init__(self, *confirm):
        self.confirm = set(confirm)

    def reverse(self, ip):
        name, host = self.NAMES.get(ip, (None, None))
        if name not in self.confirm:
            raise OSError("no PTR record")
        return host

    def forward(self, host):
        return [ip for ip, (_, known) in self.NAMES.items() if known == host]


def claimed(checker=None):
    return cr.crawlers_claimed({KEY: sla.audit(str(LOG), checker=checker)})


class TheRecordSaysWhetherTheCountsAreClaims(unittest.TestCase):
    """The good fixture's log: 105 requests from Googlebot's address, 21 from Bing's."""

    def test_an_unverified_log_is_recorded_as_claims(self):
        result = sla.audit(str(LOG))
        self.assertTrue(result["bot_identity"].startswith("claimed"))
        self.assertEqual(cr.crawlers_claimed({KEY: result}), 126)

    def test_a_log_whose_crawlers_were_all_confirmed_is_not(self):
        result = sla.audit(str(LOG), checker=sla.AddressCheck(
            Resolver("Googlebot", "bingbot")))
        self.assertTrue(result["bot_identity"].startswith("confirmed"))
        self.assertIsNone(cr.crawlers_claimed({KEY: result}))

    def test_verification_that_confirmed_nothing_leaves_every_count_a_claim(self):
        # Found by the review of batch 1: with --verify-bots and no address answering,
        # every request stays attributed to the crawler it claimed (an address with no
        # PTR record is not called forged), and the caveat went away with the flag.
        self.assertEqual(claimed(sla.AddressCheck(Resolver())), 126)

    def test_the_counts_left_unconfirmed_are_the_ones_named(self):
        self.assertEqual(claimed(sla.AddressCheck(Resolver("Googlebot"))), 21)

    def test_an_address_past_the_budget_is_still_a_claim(self):
        self.assertEqual(claimed(sla.AddressCheck(Resolver("Googlebot", "bingbot"),
                                                  budget=1)), 21)

    def test_an_ai_crawler_is_a_claim_with_the_flag_or_without_it(self):
        # No AI crawler publishes a DNS rule, so its requests stay claims even when
        # every search crawler is confirmed. The good fixture's log holds none, and the
        # second review of batch 1 dropped "ai" from the count with every test green.
        ai = ('203.0.113.7 - - [01/Jul/2026:02:00:00 +0000] "GET / HTTP/1.1" 200 10 "-" '
              '"Mozilla/5.0 AppleWebKit/537.36; compatible; GPTBot/1.2; '
              '+https://openai.com/gptbot"\n')
        with tempfile.NamedTemporaryFile("w", suffix=".log", delete=False,
                                         encoding="utf-8") as handle:
            handle.write(LOG.read_text(encoding="utf-8") + ai * 3)
            path = handle.name
        self.addCleanup(os.unlink, path)
        key = ("server_log_audit.py", (path,))
        self.assertEqual(cr.crawlers_claimed({key: sla.audit(path)}), 129)
        confirmed = sla.audit(path, checker=sla.AddressCheck(Resolver("Googlebot", "bingbot")))
        self.assertEqual(cr.crawlers_claimed({key: confirmed}), 3)

    def test_a_run_with_no_log_says_nothing(self):
        self.assertIsNone(cr.crawlers_claimed({}))
        self.assertIsNone(cr.crawlers_claimed({KEY: {"__error__": "no log",
                                                     "__error_kind__": "crash"}}))

    def test_the_report_names_it_only_when_it_is_so(self):
        warned = provenance_warnings({"log_crawlers_claimed": 21})
        self.assertTrue(any(CAVEAT in w and "21" in w for w in warned), warned)
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
        self.assertEqual(data["log_crawlers_claimed"], 126)
        for output in (render_markdown(data), render_html(data)):
            self.assertIn(CAVEAT, output)


if __name__ == "__main__":
    unittest.main()
