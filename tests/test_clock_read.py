"""Release 0.154.0: a verdict that rests on this run's clock is the machine's to give.

TECH-003 holds `subparts.ttfb_ms`, how long the run's fetch of a page waited for its
first byte, against 800 ms. A fixture tree decides what a page says; it does not decide
that number. Two whole-audit comparisons held the band anyway, as part of "the same
bytes get the same verdicts", and on a loaded machine the two runs of a pair landed in
two bands: `local/ponytail-audit/suite-probe-logs/`, 4 October 2026, seven suites at
once. And no test had ever seen the item fail.

`harness.CLOCK_READ` names such items and `harness.across_runs` is how two live runs are
compared on one. Three readers here. The table. The budget, held on numbers nobody
measured. And the derivation by the operation: the good tree with `/` answered at once,
and the same answer held back for longer than any budget — every item in the set fails
by the time it measured, and no verdict outside the set moves, so an item that begins
to read a clock is found here, on a machine at rest, and not by a busy one.
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPTS = os.path.join(ROOT, "skills", "seo-checklist", "scripts")
RUNNER = os.path.join(SCRIPTS, "checklist_runner.py")
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)

import harness  # noqa: E402
from harness import CLOCK_READ, TIMED, across_runs, offline_env, spawn, tree_served  # noqa: E402
from checklist_runner import FAIL, NA, NO_DATA, PASS, WARN  # noqa: E402
from registry_verdict import verdict  # noqa: E402

# Seconds the late origin holds `/` back: past both numbers `pagespeed.py` names for a
# time to first byte, 800 and 1800 ms. A wait can only add to what the client measures.
DELAY = 2.0


class TheSetAndTheComparison(unittest.TestCase):

    def test_every_entry_is_a_script_item_and_says_what_it_times(self):
        items = {item["id"]: item for item in harness.registry()["items"]}
        for item_id, why in CLOCK_READ.items():
            with self.subTest(item=item_id):
                self.assertEqual(items[item_id]["source"], "script")
                self.assertTrue(why.strip())

    def test_a_timed_item_is_compared_on_having_been_timed(self):
        for item_id in CLOCK_READ:
            with self.subTest(item=item_id):
                self.assertEqual([across_runs(item_id, s) for s in (PASS, WARN, FAIL)],
                                 [TIMED] * 3)
                self.assertEqual([across_runs(item_id, s) for s in (NO_DATA, NA)],
                                 [NO_DATA, NA],
                                 "a run that stopped measuring has to stay a difference")

    def test_every_other_item_is_compared_on_its_verdict(self):
        others = [item["id"] for item in harness.registry()["items"]
                  if item["id"] not in CLOCK_READ]
        self.assertTrue(others)
        for status in (PASS, WARN, FAIL, NO_DATA, NA):
            self.assertEqual({across_runs(item_id, status) for item_id in others},
                             {status})


class TheBudgetIsHeldWithoutAClock(unittest.TestCase):
    """What a live run cannot show at will: the band, on a number nobody measured."""

    def test_tech_003_passes_at_its_budget_and_fails_one_past_it(self):
        def at(ms):
            return verdict("TECH-003", {"subparts": {"ttfb_ms": ms}})
        self.assertEqual([at(0), at(800), at(801)], [PASS, PASS, FAIL])

    def test_tech_003_is_undecided_when_no_time_was_taken(self):
        self.assertEqual(verdict("TECH-003", {"subparts": {}}), NO_DATA)


class ASiteAnsweringLateMovesOnlyWhatReadsTheClock(unittest.TestCase):
    """Both origins answer `/` from one table entry, so the wait is the one difference."""

    RESULTS: dict = {}

    @classmethod
    def audit(cls, label, delay):
        def answers(site_dir):
            with open(os.path.join(site_dir, "index.html"), encoding="utf-8") as f:
                return {"/": {"status": 200, "content_type": "text/html; charset=utf-8",
                              "body": f.read(), "delay": delay}}
        with tree_served("good", answers) as site:
            arts = tree_served.artifacts(site, "good", os.path.join(cls.work, label))
            extra = []
            for flag, name in (("--rendered-json", "rendered.json"),
                               ("--cwv-json", "cwv.json"), ("--links-csv", "links"),
                               ("--server-log", "access.log")):
                extra += [flag, os.path.join(arts, name)]
            out = os.path.join(cls.work, f"{label}.json")
            proc = spawn([sys.executable, RUNNER, site.url, "--allow-private",
                          "--max-rps", "0", "--no-history", "--no-prompt", "--quiet",
                          "--timeout", "120", "--json", out, *extra],
                         env=offline_env(), timeout=900)
        if proc.returncode != 0 or not os.path.exists(out):
            raise AssertionError(f"{label} exited {proc.returncode}\n"
                                 f"{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}")
        with open(out, encoding="utf-8") as f:
            payload = json.load(f)
        return label, {r["id"]: (r["status"], r.get("evidence") or "")
                       for r in payload["items"]}

    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.mkdtemp(prefix="seo-clock-")
        with ThreadPoolExecutor(max_workers=2) as pool:
            cls.RESULTS = dict(pool.map(lambda r: cls.audit(*r),
                                        (("prompt", 0), ("late", DELAY))))

    def test_every_timed_item_fails_on_the_late_site_by_the_time_it_measured(self):
        for item_id in CLOCK_READ:
            with self.subTest(item=item_id):
                status, evidence = self.RESULTS["late"][item_id]
                self.assertEqual(status, FAIL, evidence)
                measured = [int(n) for n in re.findall(r"= (\d+)", evidence)]
                self.assertTrue(measured and min(measured) >= DELAY * 1000,
                                f"no time of {DELAY} s or more in: {evidence}")

    def test_every_timed_item_is_timed_on_the_prompt_site(self):
        """Timed, and no more: whether it passed there is the machine's."""
        for item_id in CLOCK_READ:
            with self.subTest(item=item_id):
                status, evidence = self.RESULTS["prompt"][item_id]
                self.assertEqual(across_runs(item_id, status), TIMED, evidence)

    def test_no_other_verdict_moves(self):
        prompt, late = self.RESULTS["prompt"], self.RESULTS["late"]
        moved = {i: (prompt[i][0], late[i][0], late[i][1][:100]) for i in prompt
                 if i not in CLOCK_READ and prompt[i][0] != late[i][0]}
        self.assertEqual(moved, {},
                         f"an entry answered {DELAY} s late moved these verdicts, and "
                         "`harness.CLOCK_READ` does not name them: an item that reads "
                         "this run's clock belongs there")


if __name__ == "__main__":
    unittest.main()
