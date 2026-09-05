"""Tests for the parts of the runner where a wrong answer is invisible.

The recurring hazard in this codebase is not a crash, it is a confident verdict
built on absent data. These tests exist mostly to pin down the difference
between "failed", "could not be decided" and "out of scope", because every one
of those collapses into a plausible-looking number if it goes wrong.
"""
import argparse
import builtins
import io
import json
import os
import re
import signal
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(ROOT, "skills", "seo-checklist")
SCRIPTS = os.path.join(SKILL, "scripts")
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness  # noqa: E402
import checklist_runner as runner  # noqa: E402
import checklist_report as report  # noqa: E402

from checklist_runner import (  # noqa: E402
    ANCHOR_RE, FAIL, FAILURE_LABEL, GSC_UNAVAILABLE, LLM_PENDING, MANUAL, NA,
    NEEDS_INPUT, open_since, run_series,
    NEEDS_THE_OUTSIDE_WORLD, NO_DATA, PASS, WARN, aggregate_pages, artifact_subject,
    audit_target,
    build_plan, choose_profile, diff_runs, evaluate, grade, is_page_level,
    private_host_skips, reads_artifact, same_page,
    looks_like_a_page, page_guard, profile_excludes, redact, registrable_domain,
    THIN_ENTRY_WORDS, history_path, load_public_suffixes, previous_run,
    psl_snapshot_date, psl_staleness, resolve, run_script,
    run_stamp, score, stride, suffix_label_count, unreachable_skips,
    visible_words,
)
from cwv_metrics import read as cwv_read  # noqa: E402
from rendered_audit import read as rendered_read  # noqa: E402
from detect_profile import detect  # noqa: E402


class Resolve(unittest.TestCase):
    def test_walks_dicts_and_list_indices(self):
        data = {"a": {"b": [{"c": 7}]}}
        self.assertEqual(resolve(data, "a.b.0.c"), 7)

    def test_absent_key_is_distinct_from_none(self):
        from checklist_runner import _MISSING
        self.assertIs(resolve({"a": None}, "a"), None)
        self.assertIs(resolve({"a": None}, "b"), _MISSING)


class Evaluate(unittest.TestCase):
    def test_scalar_comparisons(self):
        self.assertEqual(evaluate({"path": "n", "eq": 3}, {"n": 3})[0], True)
        self.assertEqual(evaluate({"path": "n", "lte": 3}, {"n": 4})[0], False)
        self.assertEqual(evaluate({"path": "n", "gte": 3}, {"n": 3})[0], True)

    def test_absent_field_is_undecided_not_failed(self):
        """The whole design rests on this: silence is not a failure."""
        passed, why = evaluate({"path": "nope", "eq": 1}, {"a": 1})
        self.assertIsNone(passed)
        self.assertIn("nope", why)

    def test_missing_is_makes_absence_the_answer(self):
        self.assertEqual(evaluate({"path": "meta_keywords", "falsy": True,
                                   "missing_is": "pass"}, {})[0], True)
        self.assertEqual(evaluate({"path": "x", "truthy": True,
                                   "missing_is": "fail"}, {})[0], False)

    def test_none_severity_is_case_insensitive(self):
        """gsc_checker.py capitalises severity; a raw comparison would never fire."""
        data = {"issues": [{"severity": "High", "message": "m"}]}
        self.assertEqual(
            evaluate({"path": "issues", "none_severity": ["high"]}, data)[0], False)

    def test_none_severity_missing_array_is_undecided(self):
        self.assertIsNone(
            evaluate({"path": "issues", "none_severity": ["high"]}, {})[0])


class ApplicabilityRules(unittest.TestCase):
    def item(self, item_id="MD-190", scores_with=""):
        item = {"id": item_id, "plerdy_ref": 190, "category": "media",
                "category_label": "Images / Video", "title": "Video SEO",
                "severity": "medium", "source": "script", "effort": "medium",
                "fix": "f", "check": {
                    "script": "video_schema_checker.py", "requires": "fetch",
                    "applies_when": {"path": "videos", "gt": 0},
                    "assert": {"path": "issues", "none_severity":
                               ["critical", "high", "medium"]}}}
        if scores_with:
            item["scores_with"] = scores_with
        return item

    def graded(self, items, data):
        key = ("video_schema_checker.py", ("https://example.com/",))
        plan = {key: [item["id"] for item in items]}
        return grade(items, plan, {key: data}, {}, False)

    def test_a_failed_applicability_rule_is_not_applicable_with_a_reason(self):
        row = self.graded([self.item()], {"videos": 0, "issues": []})[0]
        self.assertEqual(row["status"], NA)
        self.assertEqual(row["evidence"], "no video on the page (`videos = 0`)")

    def test_a_matching_applicability_rule_grades_the_assertion_normally(self):
        row = self.graded([self.item()], {"videos": 1, "issues": []})[0]
        self.assertEqual(row["status"], PASS)

    def test_an_item_without_applies_when_is_unchanged(self):
        item = self.item()
        del item["check"]["applies_when"]
        row = self.graded([item], {"videos": 0, "issues": []})[0]
        self.assertEqual(row["status"], PASS)

    def test_a_twin_pair_becomes_not_applicable_together_and_scores_once(self):
        primary = self.item("MD-190")
        twin = self.item("MB-102", scores_with="MD-190")
        rows = self.graded([primary, twin], {"videos": 0, "issues": []})
        self.assertEqual([row["status"] for row in rows], [NA, NA])
        scored = score(rows)
        self.assertEqual(scored["partition"]["not_applicable"], 2)
        self.assertEqual(scored["applicable"], 0)

    def test_none_matching_scans_nested_structures(self):
        data = {"meta_robots": "index, follow"}
        self.assertEqual(
            evaluate({"path": "meta_robots", "none_matching": "noindex"}, data)[0], True)


class PatternScopedToAField(unittest.TestCase):
    """A finding says what is wrong; a `fix` says what to do about it, in the
    vocabulary of the thing being asked for. Matching the whole element means a
    pattern meant for findings hits the advice instead — which is how two keyword
    items fired on "…containing the primary keyword" inside a remediation string
    and never once looked at a keyword."""

    ISSUES = {"seo_issues": [
        {"severity": "Critical", "area": "H1", "finding": "No H1 tag detected.",
         "fix": "Add a single, descriptive H1 containing the primary keyword."}]}

    def test_unscoped_matching_hits_the_remediation_text(self):
        """The bug, pinned so it cannot come back as a surprise."""
        ok, why = evaluate({"path": "seo_issues",
                            "none_matching": "(?i)h1.*keyword"}, self.ISSUES)
        self.assertFalse(ok)
        self.assertIn("keyword", why)

    def test_scoping_to_the_finding_ignores_the_fix(self):
        ok, why = evaluate({"path": "seo_issues", "field": "finding",
                            "none_matching": "(?i)h1.*keyword"}, self.ISSUES)
        self.assertTrue(ok)
        self.assertIn("finding", why)

    def test_it_still_matches_a_real_finding(self):
        ok, why = evaluate({"path": "seo_issues", "field": "finding",
                            "none_matching": "(?i)no h1"}, self.ISSUES)
        self.assertFalse(ok)
        self.assertIn("No H1", why)

    def test_a_field_no_element_carries_is_undecided(self):
        """Not a pass. An element shape that changed underneath must not read as
        clean — that is the whole failure this file is about."""
        ok, why = evaluate({"path": "seo_issues", "field": "message",
                            "none_matching": "x"}, self.ISSUES)
        self.assertIsNone(ok)
        self.assertIn("message", why)

    def test_an_empty_list_still_passes(self):
        self.assertTrue(evaluate({"path": "seo_issues", "field": "finding",
                                  "none_matching": "x"}, {"seo_issues": []})[0])

    def test_the_two_keyword_items_are_judgements_now(self):
        with open(os.path.join(SCRIPTS, "..", "resources", "config",
                               "checklist.json"), encoding="utf-8") as f:
            by_id = {i["id"]: i for i in json.load(f)["items"]}
        for item_id in ("KW-072", "KW-073"):
            self.assertEqual(by_id[item_id]["source"], "llm", item_id)
            self.assertEqual(by_id[item_id]["lens"], "copy", item_id)


class _Resp:
    """The parts of a response the pacing logic looks at."""

    def __init__(self, status_code, headers):
        self.status_code, self.headers = status_code, headers


class TheSuiteKeepsItsOwnState(unittest.TestCase):
    """This suite must not read or write the directory a real audit uses.

    It did until 0.82.0, and not marginally: a full run left fifteen robots answers in
    `%TEMP%/seo-checklist-rate`, keyed by `127.0.0.1:<port>` and live for half an hour,
    where the next run's fixtures draw from the same ports. The classes that had
    noticed pointed a module constant at their own directory, which their child
    processes could not inherit.

    Asserted as "not the default" rather than as one particular path, because a caller
    who has already chosen a directory keeps it — `harness` sets the floor with
    `setdefault`.
    """

    def test_the_state_directory_is_not_the_one_an_audit_would_use(self):
        import lib.safe_http as sh
        chosen = os.environ.get(sh.RATE_LIMIT_DIR_VAR)
        self.assertTrue(chosen, "the suite left the state directory unnamed")
        self.assertNotEqual(chosen, sh.DEFAULT_RATE_LIMIT_DIR)
        self.assertEqual(sh.rate_limit_dir(), chosen)


class RateLimiting(unittest.TestCase):
    """An audit is a burst by construction: the evidence scripts run concurrently
    and several walk a sitemap inside their own process. This is the only open item
    that could harm somebody else's server rather than the audit's own honesty."""

    def setUp(self):
        self.saved = os.environ.get("SEO_MAX_RPS")
        os.environ.pop("SEO_MAX_RPS", None)
        import lib.safe_http as sh
        self.sh = sh
        self.pacing = harness.own_rate_limit_dir()
        self.dir = self.pacing.__enter__()

    def tearDown(self):
        self.pacing.__exit__(None, None, None)
        if self.saved is None:
            os.environ.pop("SEO_MAX_RPS", None)
        else:
            os.environ["SEO_MAX_RPS"] = self.saved

    def test_pacing_is_on_by_default(self):
        self.assertGreater(self.sh.max_rps(), 0)

    def test_consecutive_requests_to_one_host_are_spaced(self):
        start = time.monotonic()
        for _ in range(4):
            self.sh.pace("example.com", rps=50)
        self.assertGreaterEqual(time.monotonic() - start, 0.05)

    def test_different_hosts_do_not_queue_behind_each_other(self):
        """One slow site must not pace requests to an unrelated API."""
        self.sh.pace("a.example", rps=2)
        start = time.monotonic()
        self.sh.pace("b.example", rps=2)
        self.assertLess(time.monotonic() - start, 0.2)

    def test_the_lock_helper_excludes_and_releases(self):
        path = os.path.join(self.dir, "exclusive.lock")
        first = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
        second = os.open(path, os.O_RDWR)
        try:
            self.assertTrue(self.sh._lock_exclusive(first, blocking=False))
            self.assertFalse(self.sh._lock_exclusive(second, blocking=False))
            self.sh._unlock(first)
            self.assertTrue(self.sh._lock_exclusive(second, blocking=False))
            self.sh._unlock(second)
        finally:
            os.close(first)
            os.close(second)

    # Three processes at 5 rps: each must wait 0.2s behind the one before it, so the
    # run costs ~0.4s. Low enough to keep the suite quick, long enough that process
    # startup jitter cannot manufacture the spacing on its own — startup is tens of
    # milliseconds and the tolerance below is 0.16s.
    PACE_CHILDREN = 3
    PACE_RPS = 5.0

    def _paced_at(self, rps: float) -> list:
        """Start the children together, return the monotonic times they proceeded.

        `time.monotonic()` is CLOCK_MONOTONIC — one clock per boot, not per process —
        which is why the slot file can hold one process's timestamp and another can
        compare against it, and why these numbers are comparable here.
        """
        import subprocess
        # The child is told where the state lives the way the product tells it —
        # through `SEO_RATE_LIMIT_DIR`, inherited from this process. It used to be
        # told with `sh.RATE_LIMIT_DIR = os.environ['PACE_DIR']`, a line that existed
        # only because a module constant cannot be inherited; the test then measured
        # sharing through a mechanism no audit has.
        code = (
            "import os, sys, time\n"
            f"sys.path.insert(0, {SCRIPTS!r})\n"
            "import lib.safe_http as sh\n"
            "sh.pace('shared.example', rps=float(os.environ['PACE_RPS']))\n"
            "print(time.monotonic())\n"
        )
        env = os.environ.copy()
        env["PACE_RPS"] = str(rps)
        procs = [subprocess.Popen([sys.executable, "-c", code], env=env,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  text=True, close_fds=False)
                 for _ in range(self.PACE_CHILDREN)]
        outs = [p.communicate(timeout=60) for p in procs]
        for out, err in outs:
            self.assertTrue(out.strip(), f"a child never paced: {err}")
        return sorted(float(out) for out, _ in outs)

    def test_the_pacing_state_is_shared_between_processes(self):
        """The scripts are separate processes; an in-process limiter would let eight of
        them go at once, which is the burst this exists to stop.

        This test used to assert `os.path.isdir(self.dir) or True` — an expression with
        no false case — and then that *something* had been written to the coordination
        directory, from one process. It never started a second one, so the one property
        it is named for went unmeasured through every release: a limiter that paced each
        process against itself would have passed it. Verified the other way round, by
        giving each child its own state directory: the gaps collapse to 0.00s and the
        assertion below fails.
        """
        times = self._paced_at(self.PACE_RPS)
        # strict=False deliberately: pairing a list with its own tail is one shorter.
        gaps = [b - a for a, b in zip(times, times[1:], strict=False)]
        interval = 1.0 / self.PACE_RPS
        self.assertTrue(all(g >= interval * 0.8 for g in gaps),
                        f"processes did not queue behind each other: gaps {gaps}, "
                        f"expected each >= {interval * 0.8:.2f}s")
        # And they queued *here*, in the directory this test named. Without it the
        # three would have shared the machine-wide one, queued just the same, and the
        # assertion above would have been satisfied by state belonging to nobody.
        self.assertEqual([n for n in os.listdir(self.dir) if n.endswith(".slot")],
                         [os.path.basename(self.sh._slot_path("shared.example"))],
                         "the children did not inherit the state directory")

    def test_pacing_off_lets_the_processes_go_together(self):
        """The other half, so the test above is known to measure pacing rather than
        the cost of starting three interpreters."""
        times = self._paced_at(0)
        self.assertLess(times[-1] - times[0], 1.0 / self.PACE_RPS,
                        "unpaced processes were spaced anyway; the test above cannot "
                        "tell pacing from startup")

    def test_the_state_directory_defaults_to_one_shared_by_the_machine(self):
        """Not per run, and not per process. Pacing is a promise to somebody else's
        server, so two audits started a second apart have to queue behind each other;
        a default that were per run would keep the promise only within one."""
        var = self.sh.RATE_LIMIT_DIR_VAR
        saved = os.environ.pop(var)
        try:
            self.assertEqual(self.sh.rate_limit_dir(), self.sh.DEFAULT_RATE_LIMIT_DIR)
            self.assertEqual(os.path.dirname(self.sh.DEFAULT_RATE_LIMIT_DIR),
                             tempfile.gettempdir())
            os.environ[var] = "   "
            self.assertEqual(self.sh.rate_limit_dir(), self.sh.DEFAULT_RATE_LIMIT_DIR,
                             "a variable set to whitespace named a directory")
        finally:
            os.environ[var] = saved

    def test_the_state_directory_is_read_on_every_use(self):
        """Read, not captured at import. A value captured once is a value a process
        cannot pass to the one it starts, which is what this replaced."""
        first, second = tempfile.mkdtemp(), tempfile.mkdtemp()
        try:
            os.environ[self.sh.RATE_LIMIT_DIR_VAR] = first
            self.assertTrue(self.sh._slot_path("example.com").startswith(first))
            os.environ[self.sh.RATE_LIMIT_DIR_VAR] = second
            self.assertTrue(self.sh._slot_path("example.com").startswith(second))
        finally:
            os.environ[self.sh.RATE_LIMIT_DIR_VAR] = self.dir
            shutil.rmtree(first, ignore_errors=True)
            shutil.rmtree(second, ignore_errors=True)

    def test_zero_switches_pacing_off(self):
        os.environ["SEO_MAX_RPS"] = "0"
        self.assertEqual(self.sh.max_rps(), 0.0)
        start = time.monotonic()
        for _ in range(5):
            self.sh.pace("example.com")
        self.assertLess(time.monotonic() - start, 0.05)

    def test_a_nonsense_limit_falls_back_to_the_default(self):
        """Never to "no limit": a typo in an env var must not silently remove the
        one guard that protects a third party."""
        os.environ["SEO_MAX_RPS"] = "fast please"
        self.assertEqual(self.sh.max_rps(), self.sh.DEFAULT_MAX_RPS)

    def test_a_stale_slot_does_not_park_the_audit(self):
        """monotonic() is per-boot, so a slot file that outlived a reboot can hold
        a value in the future. Waiting it out would look like a hang."""
        path = self.sh._slot_path("example.com")
        os.makedirs(self.dir, exist_ok=True)
        with open(path, "w") as f:
            f.write(str(time.monotonic() + 10_000))
        start = time.monotonic()
        self.sh.pace("example.com", rps=50)
        self.assertLess(time.monotonic() - start, 0.5)

    def test_a_corrupt_slot_never_raises(self):
        """The bug this guards: the slot was opened "a+", and in append mode POSIX
        writes at the end of the file whatever seek() and truncate() say — so two
        updates concatenated, float() raised out of pace(), through safe_get, and
        crashed 36 evidence scripts in one run. A politeness feature must not be
        able to fail an audit."""
        os.makedirs(self.dir, exist_ok=True)
        with open(self.sh._slot_path("example.com"), "w") as f:
            f.write("153761.196713791153761.196978791")
        self.sh.pace("example.com", rps=50)  # must not raise

    def test_a_slot_holding_nonsense_never_raises(self):
        os.makedirs(self.dir, exist_ok=True)
        for junk in ("", "   ", "not a number", "\x00\x01", "1,5"):
            with open(self.sh._slot_path("example.com"), "w") as f:
                f.write(junk)
            self.sh.pace("example.com", rps=50)

    def test_an_unwritable_state_directory_still_paces(self):
        """Unable to co-ordinate is a reason to slow down alone, not to give up."""
        # A merely unusable-looking path is creatable on Windows, so confinement
        # would decide whether this test passes or fails.
        with tempfile.NamedTemporaryFile(dir=self.dir) as blocker:
            os.environ[self.sh.RATE_LIMIT_DIR_VAR] = os.path.join(blocker.name, "nope")
            start = time.monotonic()
            waited = self.sh.pace("example.com", rps=20)
            self.assertGreater(waited, 0)
            self.assertGreaterEqual(time.monotonic() - start, 0.04)

    def test_the_slot_holds_exactly_one_timestamp_after_many_writes(self):
        for _ in range(6):
            self.sh.pace("example.com", rps=200)
        with open(self.sh._slot_path("example.com")) as f:
            float(f.read().strip())  # raises if two updates concatenated again

    def test_retry_after_is_read_in_both_formats(self):
        self.assertEqual(self.sh.retry_after_seconds(_Resp(429, {"Retry-After": "7"})), 7.0)
        future = self.sh.retry_after_seconds(
            _Resp(503, {"Retry-After": "Wed, 21 Oct 2099 07:28:00 GMT"}))
        self.assertGreater(future, 0)

    def test_retry_after_only_applies_to_a_backoff_status(self):
        """Some CDNs send the header on a 200. Sleeping on that would pace the
        audit to somebody else's cache policy."""
        self.assertEqual(self.sh.retry_after_seconds(_Resp(200, {"Retry-After": "7"})), 0.0)

    def test_an_unparseable_retry_after_waits_for_nothing(self):
        """Waiting a made-up interval is not more polite than not waiting."""
        self.assertEqual(self.sh.retry_after_seconds(_Resp(429, {"Retry-After": "soon"})), 0.0)

    def test_a_date_in_the_past_waits_for_nothing(self):
        self.assertEqual(
            self.sh.retry_after_seconds(_Resp(429, {"Retry-After": "Wed, 21 Oct 2020 07:28:00 GMT"})),
            0.0)

    def test_an_absurd_backoff_is_not_waited_out(self):
        """A server saying "come back in an hour" is not worth blocking an audit
        for; the item reports NO_DATA with the reason instead."""
        self.assertLess(self.sh.MAX_RETRY_AFTER_WAIT, 120)
        self.assertGreater(self.sh.retry_after_seconds(_Resp(429, {"Retry-After": "3600"})),
                           self.sh.MAX_RETRY_AFTER_WAIT)


class PrivateAddresses(unittest.TestCase):
    """The escape hatch in the SSRF guard, and the parts of it that must not open.

    Two things depend on this being right in both directions. With no way through,
    the live path — 55 scripts, the shared pacing, five crawlers — can only ever be
    exercised against a real third-party site, which is how a slot-file bug crashed
    36 scripts in production while every test here passed. Opened too far, a crawl
    following links a site controls can be talked into reading cloud instance
    metadata off 169.254.169.254 and putting it in an artifact.
    """

    METADATA = "169.254.169.254"       # AWS/GCP/Azure instance metadata

    def setUp(self):
        import lib.safe_http as sh
        self.sh = sh
        self.saved = os.environ.get("SEO_ALLOW_PRIVATE")
        os.environ.pop("SEO_ALLOW_PRIVATE", None)
        sh._announced_private = False

    def tearDown(self):
        if self.saved is None:
            os.environ.pop("SEO_ALLOW_PRIVATE", None)
        else:
            os.environ["SEO_ALLOW_PRIVATE"] = self.saved
        self.sh._announced_private = False

    def allow(self, value="1"):
        os.environ["SEO_ALLOW_PRIVATE"] = value

    def test_private_addresses_are_blocked_by_default(self):
        """The default is the guarantee: nothing about this change may make an
        unflagged run reach an address it could not reach before."""
        for host in ("127.0.0.1", "10.0.0.5", "192.168.1.10", "[::1]", self.METADATA):
            with self.assertRaises(self.sh.SafeHTTPError, msg=host):
                self.sh.assert_safe_url(f"http://{host}/")

    def test_the_refusal_names_the_way_through(self):
        """A guard with an escape hatch nobody can find is a guard with none. The
        cost of not knowing is real: auditing a site before it launches is the
        moment an audit is worth most."""
        with self.assertRaises(self.sh.SafeHTTPError) as caught:
            self.sh.assert_safe_url("http://127.0.0.1:8000/")
        self.assertIn("--allow-private", str(caught.exception))

    def test_the_allowance_permits_a_fixture_and_a_staging_box(self):
        self.allow()
        for host in ("127.0.0.1:8000", "10.0.0.5", "172.16.4.4", "192.168.1.10",
                     "[::1]:8000", "[fd00::1]", "100.64.1.1"):
            self.sh.assert_safe_url(f"http://{host}/")   # must not raise

    def test_link_local_stays_blocked_with_the_allowance_on(self):
        """The whole reason the allowed set is enumerated rather than derived from
        `ipaddress.is_private`, which is True for 169.254.0.0/16."""
        self.allow()
        for host in (self.METADATA, "169.254.1.1", "[fe80::1]"):
            with self.assertRaises(self.sh.SafeHTTPError, msg=host):
                self.sh.assert_safe_url(f"http://{host}/")

    def test_reserved_multicast_and_unspecified_stay_blocked(self):
        """Nothing legitimate is served there, so allowing them buys nothing."""
        self.allow()
        for host in ("240.0.0.1", "224.0.0.1", "0.0.0.0"):
            with self.assertRaises(self.sh.SafeHTTPError, msg=host):
                self.sh.assert_safe_url(f"http://{host}/")

    def test_the_blocked_message_says_the_flag_will_not_help(self):
        """Pointing at --allow-private when it is already on would send the reader
        to set a flag that cannot change the answer."""
        self.allow()
        with self.assertRaises(self.sh.SafeHTTPError) as caught:
            self.sh.assert_safe_url(f"http://{self.METADATA}/")
        detail = str(caught.exception)
        self.assertIn("stay blocked", detail)
        self.assertIn(self.METADATA, detail)

    def test_an_unrecognised_value_does_not_open_the_guard(self):
        """Same rule as a nonsense SEO_MAX_RPS falling back to the default rather
        than to no limit: a typo must never remove a guard."""
        for value in ("", "0", "no", "false", "please", "1 ", "TRUE"):
            os.environ["SEO_ALLOW_PRIVATE"] = value
            expected = value.strip().lower() in ("1", "true", "yes", "on")
            self.assertEqual(self.sh.allow_private(), expected, repr(value))

    def test_a_public_address_needs_no_flag(self):
        self.sh.assert_safe_url("https://93.184.216.34/")
        self.allow()
        self.sh.assert_safe_url("https://93.184.216.34/")

    def test_the_allowance_announces_itself_once(self):
        """A single evidence script run by hand has no other surface to say it on,
        and an audit of a staging copy that reads like an audit of the live site is
        the same class of lie as a fabricated score."""
        self.allow()
        err = io.StringIO()
        saved, sys.stderr = sys.stderr, err
        try:
            for _ in range(3):
                self.sh.assert_safe_url("http://127.0.0.1:8000/")
        finally:
            sys.stderr = saved
        self.assertEqual(err.getvalue().count("SEO_ALLOW_PRIVATE"), 1,
                         "the allowance must be stated, and stated once")

    def test_an_address_has_no_registrable_domain(self):
        """It invented one. `127.0.0.1` came out as `0.1`, the run built
        `sc-domain:0.1`, and both Search Console scripts crashed on it. A public IP
        would have been quieter and worse: a valid-looking property nobody owns
        answers with nothing, and nothing reads as a site with no search traffic."""
        for host in ("127.0.0.1", "127.0.0.1:8000", "8.8.8.8", "[::1]", "[::1]:8000",
                     "[2001:4860:4860::8888]"):
            self.assertEqual(registrable_domain(host), "", host)
        # And a real host with a port is still a real host — a staging box on :8443
        # is the common case now that one can be audited at all.
        self.assertEqual(registrable_domain("staging.example.co.uk:8443"),
                         "example.co.uk")

    def test_a_private_host_leaves_the_external_apis_undecided(self):
        """PageSpeed measures the page from Google's network, Safe Browsing looks it
        up, Search Console holds history for a property: none of that exists for a
        host on this machine. They crashed instead — and "script failed" sends the
        reader to open a script that is working correctly."""
        items = [{"id": "SP-108", "check": {"script": "pagespeed.py", "requires": "api"}},
                 {"id": "GO-140", "check": {"script": "gsc_checker.py", "requires": "gsc"}},
                 {"id": "SE-114", "check": {"script": "domain_safety_check.py",
                                             "requires": "safe_browsing"}},
                 {"id": "CN-001", "check": {"script": "parse_html.py", "requires": "fetch"}}]
        skips = private_host_skips(items, "127.0.0.1:8000")
        self.assertEqual(sorted(skips), ["GO-140", "SE-114", "SP-108"])
        for status, reason in skips.values():
            # NO_DATA, never N/A: the item applies to this site, it just cannot be
            # answered here. N/A would lift coverage on the one kind of audit that
            # genuinely knows least.
            self.assertEqual(status, NO_DATA)
            self.assertIn("only reachable from here", reason)

    def test_an_explicit_property_can_keep_the_search_console_items(self):
        """Auditing a staging copy against the live site's history is a legitimate
        thing to want, and passing the flag is the operator deciding it."""
        items = [{"id": "GO-140", "check": {"script": "gsc_checker.py", "requires": "gsc"}},
                 {"id": "SP-108", "check": {"script": "pagespeed.py", "requires": "api"}}]
        gate = set(NEEDS_THE_OUTSIDE_WORLD) - {"gsc"}
        self.assertEqual(sorted(private_host_skips(items, "10.0.0.5", gate)), ["SP-108"])

    def test_the_flag_alone_does_not_make_a_host_private(self):
        """`is_private_host` answers where the host resolves, not what was permitted.
        Confusing the two would drop PageSpeed and Search Console from an ordinary
        public audit run with the flag on."""
        self.allow()
        self.assertFalse(self.sh.is_private_host("https://93.184.216.34/"))
        self.assertTrue(self.sh.is_private_host("http://127.0.0.1:8000/"))
        self.assertFalse(self.sh.is_private_host("http://nothing.invalid/"),
                         "an unresolvable host is unreachable, not private")

    def test_a_run_records_and_announces_the_allowance(self):
        """An artifact that does not record it cannot be told apart from an audit of
        the public site, and `--quiet` must not be able to suppress the one line that
        says so. Offline: the host does not resolve, which is enough — the question is
        what the run reports about itself, not what it measured.

        That the allowance also reaches the 55 evidence scripts is proved by the CI
        job that audits a fixture server on loopback: those scripts could not fetch a
        single page without it.
        """
        import subprocess
        work = tempfile.mkdtemp()
        out = os.path.join(work, "results.json")
        try:
            proc = subprocess.run(
                [sys.executable, os.path.join(SCRIPTS, "checklist_runner.py"),
                 "https://nothing-resolves-here.invalid/", "--mode", "page",
                 "--allow-private", "--no-history", "--no-prompt", "--quiet",
                 "--timeout", "20", "--json", out],
                capture_output=True, text=True, timeout=300, close_fds=False)
            self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
            with open(out, encoding="utf-8") as f:
                payload = json.load(f)
            self.assertIs(payload["allow_private"], True)
            self.assertIs(payload["entry_private"], False,
                          "a host that does not resolve is unreachable, not private")
            self.assertIn("--allow-private", proc.stdout,
                          "the run must say so even under --quiet")
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def test_archive_mode_claims_nothing_about_a_network_it_never_touched(self):
        """The flag is inert with no requests to permit, so the caveat would be noise
        dressed as candour. The artifact still records what was asked for."""
        import subprocess
        from checklist_report import provenance_warnings
        site = tempfile.mkdtemp()
        out = os.path.join(site, "results.json")
        with open(os.path.join(site, "index.html"), "w", encoding="utf-8") as f:
            f.write('<!doctype html><html lang="en"><head><title>Fixture page</title>'
                    '<meta name="description" content="Enough of a page to audit.">'
                    '</head><body><h1>Fixture page</h1><p>Body copy, and enough of '
                    'it that the thin-entry warning stays quiet: this assertion is '
                    'about the private-address caveat alone, so any other caveat '
                    'appearing here would pass the test for the wrong reason. Forty '
                    'visible words is the threshold, so this paragraph carries a few '
                    'more than that and says something while it does.</p>'
                    '</body></html>')
        try:
            proc = subprocess.run(
                [sys.executable, os.path.join(SCRIPTS, "checklist_runner.py"),
                 "https://example.com/", "--archive", site, "--allow-private",
                 "--no-history", "--no-prompt", "--quiet", "--json", out],
                capture_output=True, text=True, timeout=300, close_fds=False)
            self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
            with open(out, encoding="utf-8") as f:
                payload = json.load(f)
            self.assertIs(payload["allow_private"], True)
            self.assertNotIn("--allow-private", proc.stdout)
            self.assertEqual(provenance_warnings(payload), [])
        finally:
            shutil.rmtree(site, ignore_errors=True)


class AScriptTheOperatingSystemKilled(unittest.TestCase):
    """A signal death is not a script defect, and used to be reported as one.

    It arrived as `crash` with the message "exit code -11", which sends a reader to
    open a script that never ran a line wrong. Same distinction §4.10 drew between a
    timeout and a crash: all of them end as NO_DATA, and they are not the same problem.

    The cause we have actually diagnosed is macOS killing a forked child inside Apple's
    Network.framework `atfork` handler — it took this suite from green to eight
    failures depending on module order. `run_script` now spawns without forking, so
    this classification is the safety net rather than the fix.
    """

    @unittest.skipUnless(hasattr(signal.Signals, "SIGKILL"),
                         "signal.Signals has no SIGKILL name on this platform")
    def test_a_signal_death_is_its_own_kind_with_the_signal_named(self):
        from checklist_runner import _signal_failure
        out = _signal_failure("parse_html.py", 9, "")
        self.assertEqual(out["error_kind"], "signal")
        self.assertIn("SIGKILL", out["error"])
        self.assertIn("signal", FAILURE_LABEL)

    def test_the_macos_hint_is_narrow(self):
        """A hint that fires on every signal would be a guess wearing a diagnosis. It
        names one cause, only in the shape that cause produces: SIGSEGV, on Darwin,
        with the child dying before it printed anything."""
        import sys as _sys
        from checklist_runner import _signal_failure
        segv = _signal_failure("x.py", 11, "")
        if _sys.platform == "darwin":
            self.assertIn("Network.framework", segv["error"])
        self.assertNotIn("Network.framework", _signal_failure("x.py", 9, "")["error"])
        self.assertNotIn("Network.framework",
                         _signal_failure("x.py", 11, "real stderr")["error"])

    def test_the_runner_does_not_fork_to_start_a_script(self):
        """The fix itself. `close_fds=False` with no `cwd` is what makes CPython choose
        `posix_spawn`; either of those changing puts 55 evidence scripts back on a code
        path macOS kills outright, and the symptom is 55 scripts "crashing" at once."""
        import inspect
        import checklist_runner
        source = inspect.getsource(checklist_runner.run_script)
        self.assertIn("close_fds=False", source)
        self.assertNotIn("cwd=", source)

    # Every condition CPython actually checks before choosing `posix_spawn` over
    # `fork`+`exec`, as three rules over the whole tree rather than one assertion about
    # one function. 0.14.0 guarded `run_script` and `harness.spawn` and left eight other
    # call sites forking, one of them in an evidence script — and the cost was not
    # hypothetical: the openssl child in `harness.tls_context()` died of signal 11 and
    # the `except` around it reported `SkipTest("openssl unavailable")`, so **the TLS
    # site shape 0.14.0 announced as exercised live had never run on macOS at all**,
    # and the message blamed a binary that was installed and working.
    SPAWNS = ("run", "Popen", "call", "check_call", "check_output")

    def _spawn_calls(self):
        """(file, line, call node) for every `subprocess.<spawn>` in the tree."""
        import ast
        found = []
        for folder in (SCRIPTS, os.path.join(SCRIPTS, "lib"),
                       os.path.join(ROOT, "skills", "seo-checklist", "tools"),
                       os.path.dirname(os.path.abspath(__file__))):
            for entry in sorted(os.listdir(folder)):
                if not entry.endswith(".py"):
                    continue
                path = os.path.join(folder, entry)
                with open(path, encoding="utf-8") as f:
                    tree = ast.parse(f.read())
                for node in ast.walk(tree):
                    if (isinstance(node, ast.Call)
                            and isinstance(node.func, ast.Attribute)
                            and node.func.attr in self.SPAWNS
                            and isinstance(node.func.value, ast.Name)
                            and node.func.value.id == "subprocess"):
                        found.append((os.path.basename(path), node.lineno, node))
        return found

    def test_every_child_in_the_tree_is_started_without_forking(self):
        """Rule one: `close_fds=False`, everywhere, not only in the two functions
        somebody remembered."""
        calls = self._spawn_calls()
        self.assertGreater(len(calls), 8, "the scan found almost nothing")
        bad = [f"{name}:{line}" for name, line, node in calls
               if not any(kw.arg == "close_fds" for kw in node.keywords)]
        self.assertEqual(bad, [], "these fork, and macOS kills a forked child inside "
                                  "Apple's atfork handler before it execs")

    def test_no_child_in_the_tree_is_given_a_working_directory(self):
        """Rule two. A `cwd` forces the fork path on its own, whatever `close_fds`
        says. `git -C`, `PYTHONPATH` and absolute paths cover every use it had here."""
        bad = [f"{name}:{line}" for name, line, node in self._spawn_calls()
               if any(kw.arg == "cwd" for kw in node.keywords)]
        self.assertEqual(bad, [], "pass a tool flag or absolute paths instead")

    def test_no_child_is_started_by_a_bare_binary_name(self):
        """Rule three, and the one that made the other two look done while three call
        sites still forked. CPython requires `os.path.dirname(executable)` to be
        non-empty, so `["openssl", ...]` and `["git", ...]` take the fork path however
        carefully everything else is set. `sys.executable` is absolute, which is why
        every call that used it appeared to be fixed. Resolve with `shutil.which`."""
        import ast
        bad = []
        for name, line, node in self._spawn_calls():
            argv = node.args[0] if node.args else None
            if not isinstance(argv, (ast.List, ast.Tuple)) or not argv.elts:
                continue
            first = argv.elts[0]
            if (isinstance(first, ast.Constant) and isinstance(first.value, str)
                    and "/" not in first.value):
                bad.append(f"{name}:{line} {first.value!r}")
        self.assertEqual(bad, [], "a bare name on PATH has no dirname, so CPython "
                                  "forks; resolve it with shutil.which first")


class Robots(unittest.TestCase):
    """robots.txt applies to what the tool discovers, never to what it was given.

    Both halves of that are load-bearing. Ignoring it while crawling somebody's site
    is impolite; applying it to the operator's own URL would refuse the 40-odd checks
    that fetch it and bury a `critical` finding under a collapsed audit."""

    def setUp(self):
        import lib.safe_http as sh
        self.sh = sh
        self.pacing = harness.own_rate_limit_dir()
        self.dir = self.pacing.__enter__()
        self.fetched = []
        self.saved_fetch = sh._fetch_robots

    def tearDown(self):
        self.pacing.__exit__(None, None, None)
        self.sh._fetch_robots = self.saved_fetch

    def serve(self, body):
        def fake(origin):
            self.fetched.append(origin)
            return body
        self.sh._fetch_robots = fake

    def test_a_disallowed_path_is_refused(self):
        self.serve("User-agent: *\nDisallow: /private\n")
        self.assertFalse(self.sh.robots_allows("https://example.com/private/x")[0])
        self.assertTrue(self.sh.robots_allows("https://example.com/public")[0])

    def test_rules_naming_our_token_are_obeyed(self):
        """The trap this guards: RobotFileParser splits the agent at the first "/"
        and lowercases it, so passing our full User-Agent —
        "Mozilla/5.0 (compatible; AgenticSEOSkill/1.0; ...)" — yields "mozilla" and
        a site's rules for us are silently ignored while `*` applies instead."""
        self.serve(f"User-agent: {self.sh.ROBOTS_TOKEN}\nDisallow: /ours\n\n"
                   f"User-agent: *\nDisallow: /theirs\n")
        self.assertFalse(self.sh.robots_allows("https://example.com/ours")[0])
        self.assertTrue(self.sh.robots_allows("https://example.com/theirs")[0])
        self.assertNotIn("/", self.sh.ROBOTS_TOKEN)

    def test_an_absent_or_unreadable_robots_txt_allows(self):
        for body in ("", "   \n", "\x00\xff not robots at all"):
            self.serve(body)
            shutil.rmtree(self.dir, ignore_errors=True)
            self.assertTrue(self.sh.robots_allows("https://example.com/x")[0], body)

    def test_a_fetch_that_raises_allows_rather_than_failing_the_audit(self):
        def boom(origin):
            raise RuntimeError("network gone")
        self.sh._fetch_robots = boom
        self.assertEqual(self.sh.robots_allows("https://example.com/x"), (True, 0.0))

    def test_robots_txt_is_fetched_once_per_origin_and_cached(self):
        """45 evidence scripts in 45 processes would otherwise fetch it 45 times,
        which is the fan-out the pacing slots already exist to avoid."""
        self.serve("User-agent: *\nDisallow: /no\n")
        for _ in range(4):
            self.sh.robots_allows("https://example.com/a")
        self.assertEqual(len(self.fetched), 1)

    def test_a_slower_crawl_delay_is_honoured_and_a_faster_one_ignored(self):
        self.serve(f"User-agent: {self.sh.ROBOTS_TOKEN}\nCrawl-delay: 10\n")
        allowed, delay = self.sh.robots_allows("https://example.com/a")
        self.assertTrue(allowed)
        self.assertEqual(delay, 10.0)
        # 10s between requests is 0.1 rps: slower than the 4 rps default, so it wins.
        self.assertAlmostEqual(self.sh._rate_for(10.0), 0.1)
        # 0.01s would be 100 rps. A site cannot talk us into going faster.
        self.assertEqual(self.sh._rate_for(0.01), self.sh.max_rps())
        self.assertIsNone(self.sh._rate_for(0.0))

    def test_respect_robots_is_off_by_default(self):
        """The signature is the guarantee: a script that fetches the audit target
        cannot be refused by robots.txt unless it deliberately opts in."""
        import inspect
        sig = inspect.signature(self.sh.safe_request)
        self.assertIs(sig.parameters["respect_robots"].default, False)
        self.assertIs(inspect.signature(
            __import__("seo_common").fetch_url).parameters["respect_robots"].default,
            False)

    def test_a_refusal_is_flagged_apart_from_a_failure(self):
        """`orphan_pages_from_sitemap` counts unreachable sitemap URLs as orphans and
        GO-137 fails on one. A robots refusal arriving as a plain error would have
        manufactured that failure out of our own politeness."""
        import seo_common
        saved = seo_common.safe_request

        def refuse(*a, **kw):
            raise self.sh.RobotsDisallowed("robots.txt disallows it")
        seo_common.safe_request = refuse
        try:
            out = seo_common.fetch_url("https://example.com/x", respect_robots=True)
        finally:
            seo_common.safe_request = saved
        self.assertTrue(out["robots_blocked"])
        self.assertIn("robots.txt", out["error"])
        self.assertEqual(out["error_kind"], "robots")

    def inventory(self, sitemap_urls, pages, robots_blocked=()):
        """A crawl inventory in the shape `site_crawl.py` writes one.

        Hand-built rather than crawled, and for the same reason these two tests used
        to stub the per-script crawl: what they are about is the *arithmetic* that
        turns a page set into a list of orphans, which is where the mistake keeps
        being made. `pages` maps a page key to whatever it needs beyond the defaults.
        """
        return {
            "inventory_version": 1,
            "site": "https://e.com/",
            "entry": "https://e.com/",
            "fetch_error": None,
            "pages": {key: dict({"url": key, "status": 200, "html": True,
                                 "final_url": key, "depth": 0, "links": [],
                                 "in_sitemap": key in sitemap_urls}, **extra)
                      for key, extra in pages.items()},
            "robots_blocked": {key: "robots.txt" for key in robots_blocked},
            "sitemap": {"urls": list(sitemap_urls), "off_host": [],
                        "sitemaps_checked": ["https://e.com/sitemap.xml"],
                        "errors": []},
            "summary": {},
        }

    def test_a_robots_skipped_sitemap_url_is_not_an_orphan(self):
        import orphan_pages_from_sitemap as ops
        # The entry is reachable without an inbound link — a visitor and a crawler
        # both start there.
        inv = self.inventory(["https://e.com/", "https://e.com/blocked"],
                             {"https://e.com/": {}},
                             robots_blocked=["https://e.com/blocked"])
        out = ops.find_orphan_pages("https://e.com", inventory=inv)
        self.assertEqual(out["summary"]["orphan_pages"], 0)
        self.assertEqual(out["sitemap_urls_blocked_by_robots"],
                         ["https://e.com/blocked"])
        self.assertIn("sitemap_robots_conflict",
                      [i["type"] for i in out["issues"]])

    def test_an_unlinked_disallowed_sitemap_url_is_not_an_orphan_either(self):
        """The same failure by a different road, and the road that gets travelled.

        The crawl can only record a refusal for a URL it tried, and it tries what the
        site links to — so a disallowed sitemap URL that nothing links to arrived with
        no refusal attached and was counted as an orphan. That is the ordinary case,
        not an edge one: a page is usually unlinked *because* it is blocked. Caught
        against the fixture site the first time the live path could be run at all.
        """
        import orphan_pages_from_sitemap as ops
        # Both `/private/x` and `/real-orphan` are in the sitemap and nothing links
        # to either. The crawl never refused them because it never tried them, so the
        # refusal has to be established here, against robots.txt, or the disallowed
        # one arrives in a client's report as a page the site forgot to link.
        inv = self.inventory(["https://e.com/", "https://e.com/private/x",
                              "https://e.com/real-orphan"],
                             {"https://e.com/": {}})
        saved = ops.robots_allows
        ops.robots_allows = lambda url: ("/private/" not in url, 0.0)
        try:
            out = ops.find_orphan_pages("https://e.com", inventory=inv)
        finally:
            ops.robots_allows = saved
        self.assertEqual(out["orphan_pages"], ["https://e.com/real-orphan"])
        self.assertEqual(out["sitemap_urls_blocked_by_robots"],
                         ["https://e.com/private/x"])


class AggregationKeepsVerdictAndMeasureTogether(unittest.TestCase):
    """The worst sampled page decides the verdict, so it has to supply the numbers
    too. It did not: a live report printed "52 characters, no more than 60 is
    acceptable" underneath a FAIL, because the verdict came from a page with 61 and
    the measurement from the entry page. A passing number beside a failing verdict
    is worse than the raw assertion it replaced."""

    def _row(self, status, got, ident="MS-020", url="https://example.com/"):
        return {"id": ident, "title": "t", "category": "meta_structured",
                "category_label": "M", "severity": "high", "status": status,
                "effort": "low", "evidence": f"len(title) = {got}",
                "url": url,
                "check": {"requires": "fetch"},
                "measure": {"op": "len_lte", "kind": "count", "got": got, "want": 60}}

    def test_the_measure_follows_the_worst_page(self):
        primary = [self._row(PASS, 52)]
        pages = [[self._row(PASS, 52)], [self._row(FAIL, 61)]]
        out = aggregate_pages(primary, pages)[0]
        self.assertEqual(out["status"], FAIL)
        self.assertEqual(out["measure"]["got"], 61,
                         "the report would show a passing number under a failure")

    def test_a_single_page_run_is_untouched(self):
        primary = [self._row(PASS, 52)]
        out = aggregate_pages(primary, [[self._row(PASS, 52)]])[0]
        self.assertEqual(out["measure"]["got"], 52)

    def test_aggregate_evidence_names_the_page_that_supplied_the_value(self):
        primary = [self._row(PASS, 52)]
        pages = [[self._row(FAIL, 63, url="https://example.com/a")],
                 [self._row(FAIL, 64, url="https://example.com/b")],
                 [self._row(FAIL, 62, url="https://example.com/c")]]
        evidence = aggregate_pages(primary, pages)[0]["evidence"]
        self.assertTrue(evidence.startswith("3/3 pages:"))
        self.assertIn("https://example.com/a", evidence)
        self.assertIn("values differ", evidence)

    def test_aggregate_evidence_keeps_the_old_shape_when_every_page_decides(self):
        primary = [self._row(PASS, 52)]
        pages = [[self._row(PASS, 52)] for _ in range(3)]
        out = aggregate_pages(primary, pages)[0]
        self.assertTrue(out["evidence"].startswith("3/3 pages:"))
        self.assertEqual(out["status"], PASS)
        self.assertEqual(out["pages_checked"], 3)
        self.assertEqual(out["pages_decided"], 3)
        self.assertEqual(out["pages_matching"], 3)

    def test_aggregate_evidence_names_undecided_pages_in_the_full_sample(self):
        primary = [self._row(PASS, 52)]
        undecided = self._row(runner.NO_DATA, 0)
        pages = ([[self._row(PASS, 52)] for _ in range(5)] +
                 [[dict(undecided)] for _ in range(3)])
        out = aggregate_pages(primary, pages)[0]
        self.assertTrue(out["evidence"].startswith(
            "5/8 pages (3 undecided):"))
        self.assertEqual(out["status"], PASS)
        self.assertEqual(out["pages_checked"], 8)
        self.assertEqual(out["pages_decided"], 5)
        self.assertEqual(out["pages_matching"], 5)

    def test_aggregate_evidence_does_not_claim_difference_when_values_agree(self):
        primary = [self._row(PASS, 52)]
        pages = [[self._row(PASS, 52, url="https://example.com/a")],
                 [self._row(PASS, 52, url="https://example.com/b")]]
        evidence = aggregate_pages(primary, pages)[0]["evidence"]
        self.assertIn("https://example.com/a", evidence)
        self.assertNotIn("values differ", evidence)

    def test_issue_measurement_uses_the_same_severity_alias_as_the_verdict(self):
        rule = {"path": "issues", "none_severity":
                ["critical", "high", "medium"]}
        data = {"issues": [{"severity": "warning", "message": "No local schema"}]}
        self.assertFalse(evaluate(rule, data)[0])
        measure = runner.measurement(rule, data)
        self.assertEqual(measure["got"], 1)
        self.assertEqual(measure["sample"], "No local schema")

    def test_three_of_eight_issue_pages_keep_a_nonpassing_measure_and_sample(self):
        clean = self._row(PASS, 0, ident="LO-200")
        clean["measure"] = {"path": "issues", "op": "none_severity",
                            "kind": "issues", "got": 0, "want": 0,
                            "levels": ["critical", "high", "medium"]}
        issue = self._row(WARN, 1, ident="LO-200", url="https://example.com/gallery")
        issue["evidence"] = "1 issue(s) at medium: No LocalBusiness JSON-LD found"
        issue["measure"] = {"path": "issues", "op": "none_severity",
                            "kind": "issues", "got": 1, "want": 0,
                            "levels": ["critical", "high", "medium"],
                            "sample": "No LocalBusiness JSON-LD found"}
        pages = [[dict(clean)] for _ in range(5)] + [[dict(issue)] for _ in range(3)]
        out = aggregate_pages([clean], pages)[0]
        self.assertEqual(out["status"], WARN)
        self.assertEqual(out["measure"]["got"], 1)
        self.assertIn("sample", out["measure"])
        self.assertEqual(out["pages_matching"], 3)
        self.assertFalse(runner.measure_contradicts_verdict(out))

    def test_each_measure_kind_stays_attached_to_the_worst_page(self):
        for kind, passing, failing in (
                ("count", 0, 2), ("number", 0, 2),
                ("matches", 0, 1), ("issues", 0, 1)):
            with self.subTest(kind=kind):
                primary = self._row(PASS, passing)
                primary["measure"] = {"kind": kind, "op": "lte",
                                      "got": passing, "want": 0}
                bad = self._row(FAIL, failing)
                bad["measure"] = {"kind": kind, "op": "lte",
                                  "got": failing, "want": 0}
                out = aggregate_pages(primary=[primary],
                                      per_page=[[primary], [bad]])[0]
                self.assertEqual(out["measure"]["got"], failing)
                self.assertFalse(runner.measure_contradicts_verdict(out))

    def test_a_nonpass_with_a_passing_measure_is_a_contradiction(self):
        row = self._row(WARN, 0)
        self.assertTrue(runner.measure_contradicts_verdict(row))


class BrowserArtifacts(unittest.TestCase):
    """A trace is the only evidence in an audit that this process cannot re-take.

    Everything else a verdict rests on came from a request made here and can be
    checked by making it again. A performance trace and a rendered-page measurement
    are files handed over from outside, deciding eight items between them — so the
    one question available, whether the file says which page it describes, is worth
    asking carefully. The contract suite covers the end of this path; these cover
    the judgements the comparison itself makes.
    """

    def _artifact(self, payload) -> str:
        path = os.path.join(tempfile.mkdtemp(), "cwv.json")
        with open(path, "w", encoding="utf-8") as f:
            if isinstance(payload, str):
                f.write(payload)
            else:
                json.dump(payload, f)
        return path

    def test_the_noise_a_url_carries_is_not_a_different_page(self):
        for a, b in (("https://example.com", "https://example.com/"),
                     ("http://example.com/", "https://example.com/"),
                     ("https://www.example.com/", "https://example.com/"),
                     ("https://example.com/about", "https://example.com/about/")):
            self.assertTrue(same_page(a, b), f"{a} vs {b}")

    def test_a_different_page_is_a_different_page(self):
        for a, b in (("https://example.com/", "https://example.org/"),
                     ("https://example.com/", "https://example.com/about"),
                     ("https://example.com/?v=2", "https://example.com/"),
                     ("https://example.com/", "https://staging.example.com/")):
            self.assertFalse(same_page(a, b), f"{a} vs {b}")

    def test_an_unreadable_artifact_does_not_raise_here(self):
        """It has to reach the script that reads it.

        Refusing a malformed file in the runner would replace `cwv_metrics.py`'s
        message — which names the offending field and its units — with a generic
        one, and units are the whole reason that script is strict.
        """
        self.assertIsNone(artifact_subject(self._artifact("{not json")))
        self.assertIsNone(artifact_subject(self._artifact([1, 2, 3])))
        self.assertIsNone(artifact_subject("/nonexistent/trace.json"))

    def test_a_url_is_found_whether_or_not_the_exporter_nested_it(self):
        self.assertEqual(artifact_subject(self._artifact({"url": "https://a/"})),
                         "https://a/")
        self.assertEqual(
            artifact_subject(self._artifact({"metrics": {"url": "https://b/"}})),
            "https://b/")
        self.assertIsNone(artifact_subject(self._artifact({"lcp_ms": 1})))
        self.assertIsNone(artifact_subject(self._artifact({"url": "   "})))

    def test_a_refused_input_says_something_other_than_missing(self):
        """Two NO_DATA verdicts, two different instructions to the operator.

        "Missing input" tells them to go and measure the page. That is the wrong
        advice when they already did and the file is about somewhere else — and it
        is the advice the generic branch would give, because a rejected key and an
        absent one look identical from inside `build_plan`.
        """
        item = {"id": "SP-214", "source": "script",
                "check": {"script": "cwv_metrics.py", "args": ["{cwv_json}"],
                          "requires": "offline"}}
        plan, skipped = build_plan([item], {"cwv_json": "/t.json"}, {"offline"},
                                  "page", None, False,
                                  {"cwv_json": "the artifact describes https://b/"})
        self.assertEqual(plan, {})
        status, reason = skipped["SP-214"]
        self.assertEqual(status, NEEDS_INPUT)
        self.assertIn("describes", reason)
        self.assertNotIn("missing input", reason)

        _, absent = build_plan([item], {}, {"offline"}, "page")
        self.assertIn("missing input", absent["SP-214"][1])

    def test_the_items_that_read_an_artifact_are_the_ones_we_think(self):
        """Named by placeholder, not by script, so a new artifact-backed item is
        covered the day it is added rather than the day somebody remembers."""
        with open(os.path.join(ROOT, "skills", "seo-checklist", "resources", "config",
                               "checklist.json"), encoding="utf-8") as f:
            registry = json.load(f)["items"]
        found = {i["id"] for i in registry if reads_artifact(i)}
        # TE-181 joined in 0.45.0: it validates the rendered DOM out of the same
        # rendered-page artifact rather than starting a browser inside the audit.
        # MB-105 joined in 0.53.0: unlike TE-169 and TE-177, it compares the served
        # document with the rendered artifact for this one URL.
        # MB-107 and MB-108 joined in 0.84.0: the two mobile-layout measures owed
        # since 0.62.0, read from the same rendered-page artifact.
        self.assertEqual(found, {"SP-214", "SP-215", "SP-216", "CN-034", "CN-035",
                                 "CN-051", "MB-094", "MB-103", "BL-084", "BL-086",
                                 "BL-087", "CI-018", "MB-105", "TE-181",
                                 "MB-107", "MB-108"})
        # What actually has to hold: an item reading an artifact measured at one URL
        # must never be run against a second page, or it would judge that page on
        # numbers taken somewhere else.
        #
        # This used to be asserted as "such an item is page-level", which was a proxy
        # rather than the property — and it held only while every artifact-reading
        # item happened to be `offline`. TE-181 broke it in 0.45.0 by validating a
        # rendered DOM from the artifact while needing `api` for the W3C checker, and
        # the proxy failed an item that was never at risk.
        #
        # The real guarantee is in the runner's own selection, which drops every
        # artifact reader from the per-page sample whatever its `requires`:
        #
        #     page_items = [i for i in items if is_page_level(i) and not reads_artifact(i)]
        #
        # A site-level artifact reader is likewise safe: it runs once, against the
        # audited URL. So the thing to defend is that line, not the proxy. Reading the
        # source is how this file already pins `run_script`'s call sites.
        with open(os.path.join(ROOT, "skills", "seo-checklist", "scripts",
                               "checklist_runner.py"), encoding="utf-8") as f:
            source = f.read()
        self.assertIn("page_items = [i for i in items if is_page_level(i) "
                      "and not reads_artifact(i)]", source,
                      "the per-page sample no longer excludes artifact readers; an "
                      "item reading a one-page trace could now be run against other "
                      "pages and report the same numbers for each")
        # And the subject guard is what catches an artifact describing a different
        # page altogether, whichever level the item is.
        self.assertIn("the artifact describes", source)


class ValueMap(unittest.TestCase):
    """The structured replacement for matching prose. Its whole point is the
    failure mode: an unlisted value is undecided, where a pattern that matched
    nothing was a pass."""

    RULE = {"path": "rows", "field": "verdict",
            "value_map": {"self_canonical": "pass", "cross_host": "fail"}}

    def test_all_mapped_to_pass(self):
        ok, why = evaluate(self.RULE, {"rows": [{"verdict": "self_canonical"}] * 3})
        self.assertTrue(ok)
        self.assertIn("3", why)

    def test_one_mapped_to_fail_decides_the_item(self):
        ok, why = evaluate(self.RULE, {"rows": [{"verdict": "self_canonical"},
                                                {"verdict": "cross_host"}]})
        self.assertFalse(ok)
        self.assertIn("cross_host", why)

    def test_an_unmapped_value_is_undecided_not_a_pass(self):
        """`unknown` is what canonical_checker emits when it could not tell. A
        pattern would have skipped over it and passed."""
        ok, why = evaluate(self.RULE, {"rows": [{"verdict": "unknown"}]})
        self.assertIsNone(ok)
        self.assertIn("unknown", why)

    def test_a_new_vocabulary_word_is_undecided(self):
        """The reason to enumerate: a value the script starts emitting later, that
        nobody mapped, must not be read as clean."""
        self.assertIsNone(evaluate(self.RULE, {"rows": [{"verdict": "brand_new"}]})[0])

    def test_a_failure_outranks_an_undecided_row(self):
        ok, _ = evaluate(self.RULE, {"rows": [{"verdict": "unknown"},
                                              {"verdict": "cross_host"}]})
        self.assertFalse(ok, "a decided failure must not be softened into NO_DATA")

    def test_a_missing_field_is_undecided(self):
        self.assertIsNone(evaluate(self.RULE, {"rows": [{"url": "x"}]})[0])

    def test_nothing_to_judge_is_undecided(self):
        self.assertIsNone(evaluate(self.RULE, {"rows": []})[0])

    def test_the_path_itself_missing_is_undecided(self):
        self.assertIsNone(evaluate(self.RULE, {})[0])

    def test_it_works_on_a_scalar_too(self):
        rule = {"path": "state", "value_map": {"ok": "pass", "bad": "fail"}}
        self.assertTrue(evaluate(rule, {"state": "ok"})[0])
        self.assertFalse(evaluate(rule, {"state": "bad"})[0])
        self.assertIsNone(evaluate(rule, {"state": "other"})[0])


class Scoring(unittest.TestCase):
    def rows(self, *statuses):
        return [{"id": f"X-{n:03d}", "category": "content",
                 "category_label": "Content", "severity": "high",
                 "status": s, "effort": "low"}
                for n, s in enumerate(statuses)]

    def test_na_leaves_the_score_and_its_reach_alone(self):
        """'We did not crawl' must not read as 'the site failed'."""
        with_na = score(self.rows(PASS, FAIL, NA, NA))
        without = score(self.rows(PASS, FAIL))
        self.assertEqual(with_na["seo_score"], without["seo_score"])
        # N/A is out of the registry's weight as well as out of the score, so the
        # share the score speaks for is unchanged rather than diluted.
        self.assertEqual(with_na["weight_pct"], without["weight_pct"])
        self.assertEqual(with_na["partition"]["not_applicable"], 2)

    def twinned(self, *statuses):
        """`statuses` graded normally, with a final row deferring to the one before."""
        rows = self.rows(*statuses)
        rows[-1]["scores_with"] = rows[-2]["id"]
        return rows

    def test_a_twin_reports_its_status_and_does_not_score_twice(self):
        """`scores_with`: one check, two source numbers, one lot of weight.

        Eight pairs in this registry run the same script with the same arguments and
        the same assertion, because the two checklists merged here both asked. Scoring
        both halves meant one defect pulled the headline down twice — and where the
        twins disagreed on severity, the weight of that defect depended on which of
        them the reader happened to look at.

        The twin is still graded, still counted in the partition, and still appears in
        the report. `weight_pct` matters as much as the score here: dropping the twin
        from the numerator without dropping it from `weight_registry` would report a
        thinner audit for an item that was in fact decided, which inverts what that
        number means.
        """
        plain = score(self.rows(PASS, FAIL))
        pair = score(self.twinned(PASS, FAIL, FAIL))
        self.assertEqual(pair["seo_score"], plain["seo_score"])
        self.assertEqual(pair["weight_pct"], plain["weight_pct"])
        self.assertEqual(pair["weight_decided"], plain["weight_decided"])
        # Reported, not hidden. Three items were decided and the buckets still sum.
        self.assertEqual(pair["partition"]["decided"], 3)
        self.assertEqual(sum(pair["partition"].values()), 3)

    def test_the_pointer_moves_weight_and_never_a_verdict(self):
        """A twin cannot soften its primary. Two items failing one check costs what
        one failing item costs — and still costs something."""
        both_pass = score(self.rows(PASS, PASS))
        pair = score(self.twinned(PASS, FAIL, FAIL))
        self.assertEqual(pair["seo_score"], score(self.rows(PASS, FAIL))["seo_score"])
        self.assertLess(pair["seo_score"], both_pass["seo_score"])

    def test_an_undecided_item_narrows_the_reach_but_not_the_score(self):
        clean = score(self.rows(PASS, PASS))
        murky = score(self.rows(PASS, PASS, NO_DATA))
        self.assertEqual(clean["seo_score"], murky["seo_score"])
        self.assertLess(murky["weight_pct"], clean["weight_pct"])

    def test_every_item_lands_in_exactly_one_bucket(self):
        """The property that replaced the coverage percentage.

        A percentage can be read without noticing what fell out of its denominator;
        a partition cannot, because the rows are printed and they have to add up.
        This is the assertion that keeps them adding up when a status is added —
        which is exactly what 0.16 did, and the old `applicable` denominator would
        have absorbed NEEDS_INPUT silently."""
        s = score(self.rows(PASS, FAIL, WARN, NO_DATA, NEEDS_INPUT,
                            LLM_PENDING, MANUAL, NA))
        p = s["partition"]
        self.assertEqual(sum(p.values()), s["total_items"])
        self.assertEqual(p, {"decided": 3, "waiting_on_you": 2, "needs_a_person": 1,
                             "undecided": 1, "not_applicable": 1})
        self.assertEqual(s["waiting_on_you"], {"llm_pending": 1, "needs_input": 1})

    def test_the_score_says_how_much_of_the_registry_it_speaks_for(self):
        """69/100 over 55% of the weight and over 95% of it are different claims,
        and the old report printed the same 69 for both."""
        half = score(self.rows(PASS, PASS, NO_DATA, NO_DATA))
        self.assertEqual(half["seo_score"], 100)
        self.assertEqual(half["weight_pct"], 50)
        self.assertEqual(score(self.rows(PASS, PASS))["weight_pct"], 100)

    def test_warn_counts_as_half(self):
        self.assertEqual(score(self.rows(WARN))["seo_score"], 50)
        self.assertEqual(score(self.rows(PASS))["seo_score"], 100)
        self.assertEqual(score(self.rows(FAIL))["seo_score"], 0)

    def test_pending_work_does_not_inflate_the_score(self):
        for status in (LLM_PENDING, MANUAL, NEEDS_INPUT):
            s = score(self.rows(PASS, status))
            self.assertEqual(s["seo_score"], 100)
            self.assertLess(s["weight_pct"], 100)


class Diff(unittest.TestCase):
    def run_of(self, statuses, **extra):
        payload = {"items": [{"id": i, "title": i, "status": s}
                             for i, s in statuses.items()]}
        payload.update(extra)
        return payload

    def test_reports_a_real_transition(self):
        prev = self.run_of({"A": PASS, "B": PASS})
        cur = self.run_of({"A": FAIL, "B": PASS})
        changes, note = diff_runs(prev, cur)
        self.assertEqual([(c["id"], c["from"], c["to"]) for c in changes],
                         [("A", PASS, FAIL)])
        self.assertEqual(note, "")

    def test_warns_when_the_registry_changed_underneath(self):
        prev = self.run_of({"A": PASS}, registry_version="aaa")
        cur = self.run_of({"A": PASS}, registry_version="bbb")
        _, note = diff_runs(prev, cur)
        self.assertIn("registry", note)

    def test_warns_when_the_compared_sets_barely_overlap(self):
        """'No status changes' over an empty intersection is false reassurance."""
        prev = self.run_of({"A": PASS, "B": PASS})
        cur = self.run_of({"C": PASS})
        changes, note = diff_runs(prev, cur)
        self.assertEqual(changes, [])
        self.assertIn("not in this one", note)

    def test_warns_when_the_mode_changed(self):
        prev = self.run_of({"A": PASS}, mode="live")
        cur = self.run_of({"A": NA}, mode="archive")
        _, note = diff_runs(prev, cur)
        self.assertIn("mode", note)


class Direction(unittest.TestCase):
    """`direction` decides whether a client is told their site got worse.

    It was called by no test function. The tests that looked like they covered it
    supply the classification as fixture data and assert that a change *labelled*
    `improved` renders as one — which reads the renderer, not the rule. A classifier
    returning `regressed` for every `PASS → NO_DATA` passed the whole suite.
    `specs/history/` HST-1.

    The expectation below is written from the requirement rather than read from the
    implementation: three quality verdicts on one scale, everything else off it. The
    function consults `VERDICT_RANK`; this consults its own table, so widening that
    constant — adding `NO_DATA` to the scale is the obvious way to break this — is a
    disagreement rather than a matching edit on both sides.
    """

    # The document's scale, worst to best, restated here on purpose. Not imported.
    QUALITY = (FAIL, WARN, PASS)

    def expected(self, was, now):
        if was not in self.QUALITY or now not in self.QUALITY:
            return "evidence"
        return ("improved" if self.QUALITY.index(now) > self.QUALITY.index(was)
                else "regressed")

    def test_every_pair_of_statuses_is_classified_by_the_rule(self):
        """All eight statuses against all eight, taken from the report's own tuple so
        a ninth would be swept the day it is added."""
        self.assertEqual(len(report.STATUS_ORDER), 8)
        for was in report.STATUS_ORDER:
            for now in report.STATUS_ORDER:
                if was == now:
                    continue
                with self.subTest(was=was, now=now):
                    self.assertEqual(runner.direction(was, now),
                                     self.expected(was, now))

    def test_losing_the_measurement_is_not_the_site_getting_worse(self):
        """The expensive direction, named separately so a failure says which harm."""
        for lost in (NO_DATA, NEEDS_INPUT, MANUAL, LLM_PENDING, NA):
            with self.subTest(status=lost):
                self.assertEqual(runner.direction(PASS, lost), "evidence",
                                 "a client would be told their site broke when the "
                                 "measurement did")

    def test_regaining_the_measurement_is_not_a_fix(self):
        for lost in (NO_DATA, NEEDS_INPUT, MANUAL, LLM_PENDING, NA):
            with self.subTest(status=lost):
                self.assertEqual(runner.direction(lost, PASS), "evidence",
                                 "the report would take credit for a fix nobody made")

    def test_the_caller_never_asks_about_an_unchanged_status(self):
        """`direction(PASS, PASS)` answers `regressed`, which is nonsense; it is
        unreachable only because `diff_runs` compares first. That guard is the reason
        the nonsense costs nothing, so it is pinned rather than assumed."""
        seen = []
        prev = {"items": [{"id": "A", "title": "A", "status": PASS},
                          {"id": "B", "title": "B", "status": WARN}]}
        cur = {"items": [{"id": "A", "title": "A", "status": PASS},
                         {"id": "B", "title": "B", "status": FAIL}]}
        real = runner.direction
        with mock.patch.object(runner, "direction",
                               lambda w, n: seen.append((w, n)) or real(w, n)):
            diff_runs(prev, cur)
        self.assertEqual(seen, [(WARN, FAIL)])


class Profiles(unittest.TestCase):
    ITEMS = [
        {"id": "LO-196", "category": "local", "severity": "medium",
         "check": {"script": "local_seo_checker.py"}},
        {"id": "CN-001", "category": "content", "severity": "high"},
        {"id": "EC-001", "category": "content", "severity": "low",
         "check": {"script": "product_schema_checker.py"}},
    ]

    def test_category_exclusion(self):
        out = profile_excludes(self.ITEMS, {"exclude_categories": ["local"],
                                            "exclude_scripts": [], "exclude_items": []})
        self.assertEqual(set(out), {"LO-196"})

    def test_script_exclusion(self):
        out = profile_excludes(self.ITEMS, {"exclude_categories": [],
                                            "exclude_scripts": ["product_schema_checker.py"],
                                            "exclude_items": []})
        self.assertEqual(set(out), {"EC-001"})

    def test_excluded_items_never_reach_the_plan(self):
        preskip = {"CN-001": (NA, "profile")}
        items = [{"id": "CN-001", "source": "script",
                  "check": {"script": "parse_html.py", "args": [], "requires": "offline"}}]
        plan, skipped = build_plan(items, {}, {"offline"}, "archive", preskip)
        self.assertEqual(plan, {})
        self.assertIn("CN-001", skipped)


class ProfilePrompt(unittest.TestCase):
    """The prompt must never be able to hang or narrow scope behind your back."""

    class _Tty(io.StringIO):
        def isatty(self):
            return True

    def ask(self, answer, interactive=True, tty=True):
        stdin, real_input = sys.stdin, builtins.input
        sys.stdin = self._Tty() if tty else io.StringIO()
        builtins.input = lambda prompt="": answer
        try:
            return choose_profile("", interactive)
        finally:
            sys.stdin, builtins.input = stdin, real_input

    def test_explicit_flag_is_never_second_guessed(self):
        self.assertEqual(choose_profile("saas", True), "saas")

    def test_accepts_a_number_or_a_name(self):
        self.assertEqual(self.ask("2"), "local")
        self.assertEqual(self.ask("ecommerce"), "ecommerce")

    def test_enter_means_the_full_registry(self):
        self.assertEqual(self.ask(""), "default")

    def test_without_a_terminal_it_does_not_ask(self):
        """CI, cron and background runs must not block on a question nobody sees."""
        def explode(prompt=""):
            raise AssertionError("prompted with no terminal attached")
        stdin, real_input = sys.stdin, builtins.input
        sys.stdin, builtins.input = io.StringIO(), explode
        try:
            self.assertEqual(choose_profile("", True), "default")
        finally:
            sys.stdin, builtins.input = stdin, real_input

    def test_no_prompt_flag_skips_the_question(self):
        self.assertEqual(self.ask("2", interactive=False), "default")

    def test_falls_back_to_the_widest_scope_not_the_narrowest(self):
        """Every non-answer resolves to `default`. Guessing a narrower profile
        would drop checks and raise the score without anyone deciding to."""
        for answer in ("", "nonsense", "99"):
            self.assertEqual(self.ask(answer), "default")

    def test_eof_is_treated_as_no_answer(self):
        stdin, real_input = sys.stdin, builtins.input
        sys.stdin = self._Tty()

        def eof(prompt=""):
            raise EOFError

        builtins.input = eof
        try:
            self.assertEqual(choose_profile("", True), "default")
        finally:
            sys.stdin, builtins.input = stdin, real_input


class Detection(unittest.TestCase):
    """Detection may suggest, never decide. These pin down both halves."""

    def page(self, body="", head="", jsonld=None):
        ld = (f'<script type="application/ld+json">{json.dumps(jsonld)}</script>'
              if jsonld else "")
        return f"<!doctype html><html><head>{head}{ld}</head><body>{body}</body></html>"

    def test_product_schema_reads_as_a_store(self):
        d = detect(self.page(jsonld={"@type": "Product", "name": "Thing"}))
        self.assertEqual(d["profile"], "ecommerce")

    def test_localbusiness_schema_reads_as_local(self):
        d = detect(self.page(jsonld={"@type": "LocalBusiness", "name": "Cafe"}))
        self.assertEqual(d["profile"], "local")

    def test_graph_containers_and_multi_typed_nodes_are_flattened(self):
        """JSON-LD is legally a node, an array, or a @graph, and @type may be a
        list — a parser that assumes one shape reads most real sites as empty."""
        d = detect(self.page(jsonld={"@graph": [{"@type": ["Organization",
                                                           "LocalBusiness"]}]}))
        self.assertEqual(d["profile"], "local")

    def test_thin_evidence_never_narrows_anything(self):
        d = detect(self.page("<h1>Hello</h1>"))
        self.assertEqual(d["profile"], "default")
        self.assertEqual(d["confidence"], "none")

    def test_empty_input_is_an_error_not_a_guess(self):
        d = detect("")
        self.assertEqual(d["profile"], "default")
        self.assertTrue(d["error"])

    def test_image_paths_do_not_fingerprint_magento(self):
        """`mage/` matches inside `image/`; that alone fingerprinted Magento on
        two sites that have never run it."""
        d = detect(self.page('<img src="/assets/image/hero.png">'))
        self.assertNotIn("Magento", d["signals"]["ecommerce"])

    def test_a_close_second_is_reported_as_low_confidence(self):
        d = detect(self.page(
            head='<link href="/pricing"><a href="/signup">x</a>',
            body='<a href="/pricing">p</a><a href="/signup">s</a>'
                 '<a href="/cart">c</a><a href="/products/x">x</a>'))
        if d["profile"] != "default":
            self.assertIn(d["confidence"], {"low", "high"})


class DetectedProfilePrompt(unittest.TestCase):
    class _Tty(io.StringIO):
        def isatty(self):
            return True

    def ask(self, answer, detected):
        stdin, real_input = sys.stdin, builtins.input
        sys.stdin = self._Tty()
        builtins.input = lambda prompt="": answer
        try:
            return choose_profile("", True, detected)
        finally:
            sys.stdin, builtins.input = stdin, real_input

    def test_enter_accepts_the_detected_profile(self):
        d = {"profile": "local", "confidence": "high", "signals": {"local": ["x"]}}
        self.assertEqual(self.ask("", d), "local")

    def test_the_user_can_override_the_suggestion(self):
        d = {"profile": "local", "confidence": "high", "signals": {"local": ["x"]}}
        self.assertEqual(self.ask("ecommerce", d), "ecommerce")

    def test_auto_accepts_detection_without_asking(self):
        d = {"profile": "saas", "confidence": "high", "signals": {"saas": ["x"]}}

        def explode(prompt=""):
            raise AssertionError("--profile auto must not prompt")

        stdin, real_input = sys.stdin, builtins.input
        sys.stdin, builtins.input = self._Tty(), explode
        try:
            self.assertEqual(choose_profile("auto", True, d), "saas")
        finally:
            sys.stdin, builtins.input = stdin, real_input

    def test_detection_does_not_narrow_scope_without_a_terminal(self):
        """The suggestion is mentioned, never applied, when nobody can confirm."""
        d = {"profile": "ecommerce", "confidence": "high", "signals": {"ecommerce": ["x"]}}
        stdin, real_input = sys.stdin, builtins.input
        sys.stdin = io.StringIO()
        builtins.input = lambda prompt="": "ecommerce"
        try:
            self.assertEqual(choose_profile("", True, d), "default")
        finally:
            sys.stdin, builtins.input = stdin, real_input


class Sampling(unittest.TestCase):
    def row(self, item_id, status, evidence="", requires="fetch"):
        return {"id": item_id, "status": status, "evidence": evidence,
                "check": {"requires": requires}}

    def test_site_level_items_are_not_aggregated(self):
        primary = [self.row("A", PASS, "site ok", requires="crawl")]
        pages = [[self.row("A", FAIL, "page bad", requires="crawl")] for _ in range(3)]
        out = aggregate_pages(primary, pages)
        self.assertEqual(out[0]["status"], PASS)

    def test_worst_page_verdict_wins_and_the_count_is_reported(self):
        primary = [self.row("A", PASS)]
        pages = [[self.row("A", PASS)], [self.row("A", FAIL, "missing title")],
                 [self.row("A", PASS)]]
        out = aggregate_pages(primary, pages)
        self.assertEqual(out[0]["status"], FAIL)
        self.assertIn("1/3 pages", out[0]["evidence"])
        self.assertEqual(out[0]["pages_decided"], 3)

    def test_undecided_pages_do_not_become_a_verdict(self):
        primary = [self.row("A", NO_DATA)]
        pages = [[self.row("A", NO_DATA)], [self.row("A", NO_DATA)]]
        out = aggregate_pages(primary, pages)
        self.assertEqual(out[0]["status"], NO_DATA)

    def test_page_level_classification(self):
        self.assertTrue(is_page_level({"check": {"requires": "fetch"}}))
        self.assertTrue(is_page_level({"check": {"requires": "offline"}}))
        self.assertFalse(is_page_level({"check": {"requires": "crawl"}}))
        self.assertFalse(is_page_level({"check": {"requires": "gsc"}}))


class Stride(unittest.TestCase):
    """A sample taken off the top of an ordered list is not a sample.

    Sitemaps are grouped by section or by date, so `urls[:N]` returns one corner of
    the site — and the report says "5 of 5 pages checked", which reads as
    representative. The stride has to spread out *and* stay reproducible, because
    every other number this tool prints is reproducible."""

    def test_picks_are_spread_across_the_whole_list(self):
        urls = [f"/p{i}" for i in range(100)]
        self.assertEqual(stride(urls, 5), ["/p0", "/p25", "/p50", "/p74", "/p99"])

    def test_both_ends_of_the_sitemap_are_covered(self):
        """The bias being removed: with `[:N]` nothing past index N-1 could ever be
        audited, however large the site. An open-interval step has the same blind
        spot at the other end — it stops a full step short of the last URL."""
        urls = [f"/p{i}" for i in range(1000)]
        for n in (2, 3, 10, 25):
            picked = stride(urls, n)
            self.assertEqual(picked[0], "/p0", n)
            self.assertEqual(picked[-1], "/p999", n)

    def test_the_same_sitemap_yields_the_same_pages(self):
        urls = [f"/p{i}" for i in range(57)]
        self.assertEqual(stride(urls, 7), stride(urls, 7))

    def test_the_first_url_is_always_kept(self):
        """Usually the home page. Dropping it to look statistically tidy would be
        perverse."""
        for n in range(1, 12):
            self.assertEqual(stride([f"/p{i}" for i in range(50)], n)[0], "/p0")

    def test_a_short_list_is_returned_whole_and_in_order(self):
        self.assertEqual(stride(["/a", "/b"], 5), ["/a", "/b"])

    def test_no_duplicates_and_never_over_the_limit(self):
        for size in (1, 2, 3, 9, 40, 41):
            for limit in (1, 2, 5, 40):
                picked = stride([f"/p{i}" for i in range(size)], limit)
                self.assertEqual(len(picked), len(set(picked)))
                self.assertLessEqual(len(picked), min(size, limit))

    def test_asking_for_nothing_returns_nothing(self):
        self.assertEqual(stride(["/a", "/b"], 0), [])


class Domains(unittest.TestCase):
    def test_reduces_to_the_search_console_property(self):
        self.assertEqual(registrable_domain("www.example.com"), "example.com")
        self.assertEqual(registrable_domain("example.com"), "example.com")
        self.assertEqual(registrable_domain("shop.bbc.co.uk"), "bbc.co.uk")

    def test_platform_domains_are_not_swallowed(self):
        """What the seven hard-coded suffixes got wrong, and it is the shape most
        small sites have: the whole host is the registrable domain here, and
        reducing it produced a property nobody owns."""
        for host, expected in (("something.github.io", "something.github.io"),
                               ("myapp.vercel.app", "myapp.vercel.app"),
                               ("site.netlify.app", "site.netlify.app"),
                               ("shop.myshopify.com", "shop.myshopify.com")):
            self.assertEqual(registrable_domain(host), expected, host)

    def test_the_ccTLD_shapes_the_old_heuristic_got_right_still_work(self):
        for host, expected in (("a.b.example.com.br", "example.com.br"),
                               ("www.example.co.il", "example.co.il"),
                               ("x.example.gov.uk", "example.gov.uk")):
            self.assertEqual(registrable_domain(host), expected, host)

    def test_a_port_and_a_trailing_dot_are_ignored(self):
        self.assertEqual(registrable_domain("www.example.com:8443"), "example.com")
        self.assertEqual(registrable_domain("www.example.com."), "example.com")


class PublicSuffixList(unittest.TestCase):
    """The list is bundled, so its absence and its content are both testable
    offline — and both matter: a missing snapshot silently narrows every domain to
    its last two labels."""

    FIXTURE = """// a comment
com
co.uk
*.ck
!www.ck
github.io
"""

    def _rules(self):
        path = os.path.join(tempfile.mkdtemp(), "psl.dat")
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.FIXTURE)
        return load_public_suffixes(path)

    def test_the_parser_sorts_the_three_rule_kinds(self):
        exact, wildcard, exception = self._rules()
        self.assertEqual(exact, {"com", "co.uk", "github.io"})
        self.assertEqual(wildcard, {"*.ck"})
        self.assertEqual(exception, {"www.ck"})

    def test_the_longest_matching_rule_wins(self):
        rules = self._rules()
        self.assertEqual(suffix_label_count(["example", "com"], rules), 1)
        self.assertEqual(suffix_label_count(["x", "example", "co", "uk"], rules), 2)
        self.assertEqual(suffix_label_count(["x", "github", "io"], rules), 2)

    def test_a_wildcard_rule_consumes_a_label(self):
        self.assertEqual(suffix_label_count(["foo", "bar", "ck"], self._rules()), 2)

    def test_an_exception_rule_shortens_the_suffix(self):
        """`!www.ck` against `*.ck` means www.ck is registrable, not a suffix."""
        self.assertEqual(suffix_label_count(["www", "ck"], self._rules()), 1)

    def test_an_unlisted_tld_falls_back_to_the_default_rule(self):
        self.assertEqual(suffix_label_count(["example", "zzz"], self._rules()), 1)

    def test_the_bundled_snapshot_is_present_and_plausible(self):
        """Its absence is not a crash, it is a quiet downgrade to the heuristic
        this replaced — so the shipped file gets an assertion of its own."""
        from checklist_runner import PSL_PATH
        self.assertTrue(os.path.exists(PSL_PATH), f"no snapshot at {PSL_PATH}")
        exact, wildcard, exception = load_public_suffixes(PSL_PATH)
        self.assertGreater(len(exact), 5000)
        self.assertIn("co.uk", exact)
        self.assertIn("github.io", exact, "the private section is missing")
        self.assertTrue(wildcard and exception)

    def test_a_missing_list_falls_back_loudly(self):
        import checklist_runner as cr
        saved_cache, saved_warned = cr._PSL_CACHE, cr._PSL_WARNED
        cr._PSL_CACHE, cr._PSL_WARNED = None, False
        saved_path = cr.PSL_PATH
        cr.PSL_PATH = os.path.join(tempfile.mkdtemp(), "absent.dat")
        err = io.StringIO()
        saved_stderr, sys.stderr = sys.stderr, err
        try:
            # The heuristic's answer, and the warning that it is the heuristic's.
            self.assertEqual(cr.registrable_domain("shop.bbc.co.uk"), "bbc.co.uk")
            self.assertIn("public suffix list not found", err.getvalue())
        finally:
            sys.stderr = saved_stderr
            cr.PSL_PATH = saved_path
            cr._PSL_CACHE, cr._PSL_WARNED = saved_cache, saved_warned


class UnreachableSite(unittest.TestCase):
    """The worst failure this tool can have is grading a site it never read.

    Evidence scripts mostly exit 0 with an empty result when they cannot fetch
    anything, and an empty result satisfies the assertions the registry is built
    from — `errors = 0`, no match for a warning pattern. A run against a host
    that does not resolve once scored 61/100 on 40 passes.
    """

    ITEMS = [
        {"id": "F", "check": {"requires": "fetch", "script": "s.py"}},
        {"id": "C", "check": {"requires": "crawl", "script": "s.py"}},
        {"id": "A", "check": {"requires": "api", "script": "s.py"}},
        {"id": "O", "check": {"requires": "offline", "script": "s.py"}},
        {"id": "G", "check": {"requires": "gsc", "script": "s.py"}},
    ]

    def test_everything_that_reads_the_live_site_is_undecided(self):
        skips = unreachable_skips(self.ITEMS, "HTTP 503")
        for item_id in ("F", "C", "A"):
            self.assertEqual(skips[item_id][0], NO_DATA, item_id)
            self.assertIn("unreachable", skips[item_id][1])

    def test_undecided_not_out_of_scope(self):
        """NO_DATA, never N/A: an unreadable site must cost coverage. N/A would
        drop these out of the denominator and report thin air as full cover."""
        skips = unreachable_skips(self.ITEMS, "HTTP 503")
        self.assertNotIn(NA, {v[0] for v in skips.values()})

    def test_search_console_still_answers(self):
        """Google's stored history does not stop existing because the site is
        down today, so gating it would throw away the only evidence left."""
        self.assertNotIn("G", unreachable_skips(self.ITEMS, "HTTP 503"))

    def test_no_live_site_check_reaches_the_plan(self):
        skips = unreachable_skips(self.ITEMS, "HTTP 503")
        plan, _ = build_plan(self.ITEMS, {}, {"offline", "fetch", "crawl", "api"},
                             "live", skips, True)
        planned = {i for ids in plan.values() for i in ids}
        self.assertEqual(planned & {"F", "C", "A"}, set(),
                         "a script ran against a site that could not be read")

    def test_offline_checks_fall_out_on_their_missing_input(self):
        """Offline items are not gated by reachability — they read a local file,
        not the site. Every one of them takes that file as its first argument,
        so when the fetch failed and there is no HTML to hand them, they drop out
        on the missing input instead.

        NEEDS_INPUT and not NO_DATA even here, and the reason is worth stating: the
        status says an input was absent, not that the operator can conjure it. The
        run already reports the unreachable entry page in its own words, loudly and
        first; an item saying "no HTML" underneath it is a consequence, not a second
        diagnosis. Reporting the two differently would need a status per cause, and
        the causes are already in the reasons."""
        item = [{"id": "O", "check": {"requires": "offline", "script": "parse_html.py",
                                      "args": ["{html}", "--url", "{url}"]}}]
        _, skipped = build_plan(item, {"url": "https://e.com"}, {"offline"}, "live",
                                unreachable_skips(item, "HTTP 503"), False)
        self.assertEqual(skipped["O"][0], NEEDS_INPUT)
        self.assertIn("html", skipped["O"][1])


class SearchConsoleBoundary(unittest.TestCase):
    ITEM = [{"id": "G", "source": "script", "check": {"requires": "gsc", "script": "g.py"}}]

    def test_missing_credentials_is_undecided_not_out_of_scope(self):
        """live mode could have asked Search Console; it just had no key. That
        is NO_DATA. Reporting N/A hides seven items from the coverage
        denominator and raises coverage exactly where the audit is thinnest."""
        _, skipped = build_plan(self.ITEM, {}, {"offline", "fetch", "crawl", "api"},
                                "live", None, False)
        self.assertEqual(skipped["G"][0], NEEDS_INPUT)

    def test_a_mode_without_network_puts_it_out_of_scope(self):
        """archive promises no network at all, so the item genuinely does not
        apply — that one is N/A."""
        _, skipped = build_plan(self.ITEM, {}, {"offline"}, "archive", None, False)
        self.assertEqual(skipped["G"][0], NA)

    def test_credentials_present_means_it_runs(self):
        plan, skipped = build_plan(self.ITEM, {}, {"offline", "fetch", "crawl", "api"},
                                   "live", None, True)
        self.assertEqual(skipped, {})
        self.assertEqual(len(plan), 1)

    def _impossible(self, has_gsc):
        items = [{"id": i, "source": "gsc", "category": "c", "category_label": "C",
                  "title": "t", "severity": "low", "plerdy_ref": 0, "fix": ""}
                 for i in GSC_UNAVAILABLE]
        return grade(items, {}, {}, {}, has_gsc)

    def test_impossible_items_never_blame_missing_credentials(self):
        """Three items have no API endpoint at all. Telling someone without a key
        to set GSC_CREDENTIALS_PATH sends them to configure something that cannot
        decide them — the setup finishes and the status does not move."""
        for has_gsc in (True, False):
            for row in self._impossible(has_gsc):
                self.assertNotIn("GSC_CREDENTIALS_PATH", row["evidence"])
                self.assertIn("no ", row["evidence"].lower())

    def test_impossible_items_are_manual_not_undecided(self):
        """They are answerable today — by a person opening the UI. NO_DATA says
        the audit tried and failed, and invites somebody to fix the tool."""
        for has_gsc in (True, False):
            for row in self._impossible(has_gsc):
                self.assertEqual(row["status"], MANUAL)
                self.assertIn("UI", row["evidence"])

    def test_the_switch_to_manual_does_not_move_coverage(self):
        """Both statuses stay in the denominator and out of the decided count. If
        this ever diverges, the reclassification became a way to lift a number."""
        rows = [{"id": "X", "category": "c", "category_label": "C",
                 "severity": "high", "status": NO_DATA, "effort": "low"}]
        as_no_data = score(rows)
        as_manual = score([dict(rows[0], status=MANUAL)])
        self.assertEqual(as_no_data["weight_pct"], as_manual["weight_pct"])
        self.assertEqual(as_no_data["applicable"], as_manual["applicable"])
        self.assertEqual(as_no_data["decided"], as_manual["decided"])

    def test_a_future_gsc_item_without_an_entry_still_reports_undecided(self):
        """The fallback is not dead code: it is what an item added to the registry
        before anyone writes its reason falls back to."""
        item = [{"id": "GO-999", "source": "gsc", "category": "c",
                 "category_label": "C", "title": "t", "severity": "low",
                 "plerdy_ref": 0, "fix": ""}]
        self.assertEqual(grade(item, {}, {}, {}, True)[0]["status"], NO_DATA)


class SafeBrowsingBoundary(unittest.TestCase):
    ITEM = [{"id": "SE-114", "source": "script",
             "check": {"requires": "safe_browsing",
                       "script": "domain_safety_check.py"}}]

    def test_missing_key_in_a_network_mode_needs_input(self):
        _, skipped = build_plan(self.ITEM, {}, {"offline", "fetch", "crawl", "api"},
                                "live", has_safe_browsing=False)
        self.assertEqual(skipped["SE-114"][0], NEEDS_INPUT)
        self.assertIn("GOOGLE_SAFE_BROWSING_KEY", skipped["SE-114"][1])

    def test_archive_mode_makes_the_api_check_not_applicable(self):
        _, skipped = build_plan(self.ITEM, {}, {"offline"}, "archive",
                                has_safe_browsing=False)
        self.assertEqual(skipped["SE-114"][0], NA)
        self.assertIn("archive", skipped["SE-114"][1])

    def test_either_supported_key_allows_the_check_to_run(self):
        plan, skipped = build_plan(self.ITEM, {}, {"offline", "fetch", "crawl", "api"},
                                   "live", has_safe_browsing=True)
        self.assertEqual(skipped, {})
        self.assertEqual(len(plan), 1)


class TheModeTableIsTheContract(unittest.TestCase):
    """`specs/run-lifecycle/` RUN-1. The mode decides how much of the registry can
    answer at all, so it decides the denominator every score is a fraction of.

    `MODE_CAPS`, `MODE_HELP` and `resolve_mode` were named by no test — a grep over
    `tests/` returned zero for all three. The only enumeration of capabilities anywhere
    in the suite was `VALID_REQUIRES` in `test_registry.py`, a hand-kept copy of the
    vocabulary rather than a reader of the table: it would still have passed if `page`
    mode had silently gained `crawl`.

    The table below is written from §2.1 of that document and not imported, which is the
    whole point — the requirement says a change to a set is a change to the document
    first, and this is what makes that true rather than hoped for.
    """

    # `specs/run-lifecycle/` §2.1, transcribed.
    TABLE = {
        "live": {"offline", "fetch", "crawl", "api"},
        "page": {"offline", "fetch", "api"},
        "archive": {"offline"},
    }
    # Named in §2.1 as `api` capabilities gated a second time by whether a credential
    # exists, and therefore deliberately in no mode's set.
    TWICE_GATED = {"gsc", "safe_browsing"}

    def test_the_three_modes_carry_exactly_these_capabilities(self):
        self.assertEqual(runner.MODE_CAPS, self.TABLE)

    def test_every_mode_is_offered_to_an_operator(self):
        """A mode the table has and the help does not is unreachable; the reverse is a
        promise the runner cannot keep."""
        self.assertEqual(set(runner.MODE_HELP), set(self.TABLE))

    def test_resolve_mode_hands_back_the_table_row(self):
        for mode, caps in self.TABLE.items():
            with self.subTest(mode=mode):
                got = runner.resolve_mode(
                    argparse.Namespace(mode=mode, archive=""))
                self.assertEqual(got, (mode, caps))

    def test_the_default_is_live_and_archive_files_choose_archive(self):
        self.assertEqual(
            runner.resolve_mode(argparse.Namespace(mode="", archive=""))[0], "live")
        self.assertEqual(
            runner.resolve_mode(argparse.Namespace(mode="", archive="/tmp/x"))[0],
            "archive")

    def test_a_run_cannot_edit_the_table_it_was_handed(self):
        """`resolve_mode` returns a set; if it were the table's own, one run narrowing
        its capabilities would narrow every later run in the process."""
        _, caps = runner.resolve_mode(argparse.Namespace(mode="live", archive=""))
        caps.discard("crawl")
        self.assertEqual(runner.MODE_CAPS["live"], self.TABLE["live"])

    def test_an_item_runs_exactly_when_its_requirement_is_in_the_mode(self):
        """The behavioural half. One item per capability per mode, planned or skipped,
        with no case left to inference."""
        for mode, caps in self.TABLE.items():
            for need in sorted(set().union(*self.TABLE.values())):
                with self.subTest(mode=mode, requires=need):
                    item = [{"id": "X-001", "severity": "high", "source": "script",
                             "check": {"script": "s.py", "requires": need,
                                       "assert": {"path": "a", "op": "eq", "value": 1}}}]
                    plan, skipped = build_plan(item, {}, set(caps), mode,
                                               has_gsc=True, has_safe_browsing=True)
                    if need in caps:
                        self.assertEqual(skipped, {})
                        self.assertEqual(len(plan), 1)
                    else:
                        self.assertEqual(skipped["X-001"][0], NA)
                        self.assertIn(need, skipped["X-001"][1])
                        self.assertEqual(len(plan), 0)

    def test_the_registry_asks_only_for_capabilities_this_document_accounts_for(self):
        """The weaker of the two candidate readers `specs/run-lifecycle/` §6 weighed,
        and the one it argued for: a capability no mode carries is legitimate — `gsc`
        and `safe_browsing` are exactly that — so the rule is that every `requires` is
        either in some mode or is one of the twice-gated pair, and nothing else."""
        with open(os.path.join(SKILL, "resources", "config", "checklist.json"),
                  encoding="utf-8") as stream:
            registry = json.load(stream)
        asked = {(i.get("check") or {}).get("requires")
                 for i in registry["items"] if i.get("check")}
        asked.discard(None)
        accounted = set().union(*self.TABLE.values()) | self.TWICE_GATED
        self.assertEqual(sorted(asked - accounted), [])
        self.assertTrue(self.TWICE_GATED <= asked,
                        "the twice-gated capabilities are named by no item, so the "
                        "second gate is describing nothing")


class OneInvocationIsOneExecution(unittest.TestCase):
    """`specs/run-lifecycle/` RUN-4. The registry asks some questions twice under
    different source numbers on purpose, and REG-11 rules on which twin carries the
    weight. Running the script twice doubles the cost of every audit and creates the
    possibility of two answers to one question, which the report has no way to show.

    Nothing held it: the two assertions on plan size in the suite were both single-item
    cases, which demonstrate nothing about folding.
    """

    def item(self, item_id, *args):
        return {"id": item_id, "severity": "high", "source": "script",
                "check": {"script": "s.py", "requires": "offline", "args": list(args),
                          "assert": {"path": "a", "op": "eq", "value": 1}}}

    def plan_for(self, *items):
        plan, skipped = build_plan(list(items), {}, {"offline"}, "archive")
        self.assertEqual(skipped, {})
        return plan

    def test_two_items_with_one_invocation_run_it_once(self):
        plan = self.plan_for(self.item("A-001"), self.item("B-002"))
        self.assertEqual(len(plan), 1)
        self.assertEqual(sorted(next(iter(plan.values()))), ["A-001", "B-002"])

    def test_the_same_script_with_different_arguments_is_two_invocations(self):
        """The other side, and the one that makes the first meaningful: a fold keyed on
        the script alone would pass the test above and silently drop an argument."""
        plan = self.plan_for(self.item("A-001", "--deep"), self.item("B-002"))
        self.assertEqual(len(plan), 2)
        self.assertEqual(sorted(ids[0] for ids in plan.values()), ["A-001", "B-002"])

    def test_the_fold_is_by_invocation_and_not_by_item(self):
        """Three items, two distinct invocations, and the item that shares goes with
        the one it matches rather than with the one next to it."""
        plan = self.plan_for(self.item("A-001", "--deep"), self.item("B-002"),
                             self.item("C-003", "--deep"))
        self.assertEqual(sorted(sorted(v) for v in plan.values()),
                         [["A-001", "C-003"], ["B-002"]])


class TwoRefusalsHaveAStatedOrder(unittest.TestCase):
    """`specs/run-lifecycle/` RUN-20: scope before capability, capability before input.

    An item can be refused twice over, exactly one reason reaches the report, and the
    status names who can act — so the wrong one sends a reader to work that changes
    nothing. The precedence existed as whatever sequence of `if` statements the run
    performed, and nothing constructed an item with two applicable refusals to see
    which reason came out. Any reordering of the code reclassified items in silence.
    """

    def item(self, requires="crawl", arg="{server_log}"):
        return {"id": "X-001", "severity": "high", "source": "script",
                "check": {"script": "s.py", "requires": requires, "args": [arg],
                          "assert": {"path": "a", "op": "eq", "value": 1}}}

    def test_scope_beats_capability(self):
        """Both answer N/A, so the reason is what distinguishes them: a profile
        exclusion must not be reported as a mode gap."""
        _, skipped = build_plan([self.item(requires="crawl")], {}, {"offline"},
                                "archive",
                                preskip={"X-001": (NA, "excluded by the local profile")})
        self.assertEqual(skipped["X-001"][0], NA)
        self.assertIn("profile", skipped["X-001"][1])
        self.assertNotIn("archive mode", skipped["X-001"][1])

    def test_scope_beats_a_missing_input(self):
        _, skipped = build_plan([self.item(requires="offline")], {}, {"offline"},
                                "archive",
                                preskip={"X-001": (NA, "excluded by the local profile")},
                                rejected={"server_log": "the log is for another site"})
        self.assertEqual(skipped["X-001"][0], NA,
                         "an item nobody was going to ask cannot be waiting on input")

    def test_capability_beats_a_missing_input(self):
        """Supplying the credential would not help, so `NEEDS_INPUT` would be a
        to-do item that cannot be done."""
        _, skipped = build_plan([self.item(requires="crawl")], {}, {"offline"},
                                "archive",
                                rejected={"server_log": "the log is for another site"})
        self.assertEqual(skipped["X-001"][0], NA)
        self.assertIn("crawl", skipped["X-001"][1])

    def test_an_item_that_is_in_scope_and_answerable_is_the_only_one_asked_for_input(self):
        """The floor under the three above: without this they would all pass on an
        implementation that answered N/A to everything."""
        _, skipped = build_plan([self.item(requires="offline")], {}, {"offline"},
                                "archive",
                                rejected={"server_log": "the log is for another site"})
        self.assertEqual(skipped["X-001"][0], NEEDS_INPUT)


class CredentialDiscoveryIsAnOrderedContract(unittest.TestCase):
    """`specs/inputs/` INP-6. The order was stated in prose in two places and asserted
    by nothing; neither function was named in any test. A reordering that put a
    repository `.env` above the process environment would have passed the suite and
    changed which key a run uses.

    The harm the requirement names is specific: an operator auditing a client's site
    from that client's directory must not have their own credentials silently replaced
    by a `.env` the client shipped. That is `test_a_shipped_env_file_cannot_replace_the
    _operators_own_key`, and it is the reason "first hit wins" is only safe when the
    first place looked is the one the operator controls most directly.
    """

    def setUp(self):
        sys.path.insert(0, SCRIPTS)
        import env_loader
        self.loader = env_loader
        self.saved = dict(os.environ)
        self.addCleanup(self.restore)

    def restore(self):
        os.environ.clear()
        os.environ.update(self.saved)
        self.loader._LOADED = False
        self.loader._LOADED_FROM = []

    def write(self, directory, **pairs):
        path = os.path.join(directory, ".env")
        with open(path, "w", encoding="utf-8") as stream:
            for key, value in pairs.items():
                stream.write(f"{key}={value}\n")
        return path

    def test_a_shipped_env_file_cannot_replace_the_operators_own_key(self):
        work = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, work, True)
        self.write(work, PAGESPEED_API_KEY="the-clients-key")
        os.environ["PAGESPEED_API_KEY"] = "the-operators-key"
        here = os.getcwd()
        self.addCleanup(os.chdir, here)
        os.chdir(work)
        self.loader.load_env(force=True)
        self.assertEqual(os.environ["PAGESPEED_API_KEY"], "the-operators-key")

    def test_a_file_supplies_only_what_the_shell_left_unset(self):
        """The other half: outranking is not ignoring."""
        work = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, work, True)
        self.write(work, SEO_TEST_UNSET_KEY="from-the-file")
        os.environ.pop("SEO_TEST_UNSET_KEY", None)
        here = os.getcwd()
        self.addCleanup(os.chdir, here)
        os.chdir(work)
        self.loader.load_env(force=True)
        self.assertEqual(os.environ["SEO_TEST_UNSET_KEY"], "from-the-file")

    def test_the_working_directory_is_searched_before_the_shared_defaults(self):
        """The invocation directory is the one the operator chose deliberately."""
        here = os.getcwd()
        self.addCleanup(os.chdir, here)
        work = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, work, True)
        os.chdir(work)
        found = [str(p) for p in self.loader._candidate_paths()]
        self.assertEqual(os.path.dirname(found[0]), os.path.realpath(work))
        self.assertGreaterEqual(len(found), 2,
                                "the shared defaults are gone, so nothing is ordered")

    def test_the_key_search_prefers_the_flag_then_the_environment_then_disk(self):
        """`find_gsc_credentials` is the second half of the contract, and its order is
        the same shape: what the operator said on this run, then what their shell says,
        then whatever happens to be on the machine."""
        work = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, work, True)
        flag = os.path.join(work, "flag.json")
        env = os.path.join(work, "env.json")
        older = os.path.join(work, "older.json")
        for path in (flag, env, older):
            with open(path, "w", encoding="utf-8") as stream:
                stream.write("{}")
        os.environ["GSC_CREDENTIALS_PATH"] = env
        os.environ["GV_SA_KEY"] = older
        self.assertEqual(runner.find_gsc_credentials(flag), flag)
        self.assertEqual(runner.find_gsc_credentials(""), env)
        os.environ.pop("GSC_CREDENTIALS_PATH")
        self.assertEqual(runner.find_gsc_credentials(""), older)

    def test_a_named_key_that_does_not_exist_is_skipped_rather_than_returned(self):
        """Returning a path to nothing would turn a missing credential into a crash
        deep in a checker instead of a NEEDS_INPUT the operator can act on."""
        os.environ["GSC_CREDENTIALS_PATH"] = os.path.join(tempfile.gettempdir(),
                                                          "definitely-absent.json")
        os.environ.pop("GV_SA_KEY", None)
        self.assertEqual(runner.find_gsc_credentials(""), "")


class OpportunitiesAreCarriedAndNeverScored(unittest.TestCase):
    """`specs/inputs/` INP-9. Search Console's opportunities are work a person can do
    and are not verdicts about the site. Scoring them would make a client's number move
    with somebody else's index while they changed nothing — which is what `GO-134` did
    for four releases, reporting "position 4.0, within striking distance" as a `high`
    failure ranked first in the fix list.

    Both halves were unread: nothing asserted the opportunities stay out of the score,
    and nothing asserted they are carried at all.
    """

    PAYLOAD = {("gsc_checker.py", ()): {
        "opportunities": [{"type": "striking_distance", "query": "cinnamon buns",
                           "position": 4.0, "impressions": 115,
                           "finding": "Position 4.0 with 115 impressions",
                           "fix": "strengthen the page for this query"},
                          "not a dict, and dropped"],
        "issues": []}}

    def test_the_opportunities_are_lifted_out_of_the_payload(self):
        found = runner.gsc_opportunities(self.PAYLOAD)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["query"], "cinnamon buns")

    def test_a_run_without_search_console_carries_an_empty_list_not_a_missing_key(self):
        self.assertEqual(runner.gsc_opportunities({}), [])

    def row(self, item_id, status):
        return {"id": item_id, "title": item_id, "category": "content",
                "category_label": "Content", "severity": "high", "effort": "low",
                "status": status, "evidence": "", "fix": ""}

    def test_the_score_counts_items_and_knows_nothing_of_opportunities(self):
        """The requirement itself, and it has to be asserted over the partition rather
        than over two equal calls: `score` takes items, so handing it the same items
        twice proves nothing. What proves it is that the registry partition sums to the
        item count with fourteen opportunities in the run — an opportunity that leaked
        into any row would break that sum."""
        rows = [self.row("A", PASS), self.row("B", FAIL)]
        scored = runner.score(rows)
        self.assertEqual(scored["total_items"], len(rows))
        self.assertEqual(sum(scored["partition"].values()), len(rows))
        self.assertNotIn("opportunit", json.dumps(scored))

    def test_the_opportunities_are_printed_where_the_score_is_not(self):
        """The other half of the requirement — "reported" — and `opportunity_section`
        was one of the six report sections `specs/reporting/` A.1 records at zero test
        functions."""
        data = {"url": "https://example.com/", "mode": "live", "profile": "default",
                "registry_version": "test", "runs": {},
                "items": [self.row("A", PASS)],
                "gsc_opportunities": runner.gsc_opportunities(self.PAYLOAD)}
        data["scores"] = runner.score(data["items"])
        printed = chr(10).join(report.opportunity_section(data))
        self.assertIn("cinnamon buns", printed)
        self.assertEqual(report.opportunity_section(dict(data, gsc_opportunities=[])),
                         [], "an absent list must print nothing, not an empty heading")


class NetworkOptIns(unittest.TestCase):
    def test_return_tags_are_verified_in_both_network_modes(self):
        for mode in ("live", "page"):
            self.assertEqual(runner.opt_in_flags(mode, False)["hreflang_checker.py"],
                             ["--verify-returns"])

    def test_return_tags_are_never_verified_in_archive_mode(self):
        self.assertNotIn("hreflang_checker.py", runner.opt_in_flags("archive", False))

    def test_verify_bots_remains_an_independent_operator_opt_in(self):
        self.assertNotIn("server_log_audit.py", runner.opt_in_flags("live", False))
        self.assertEqual(runner.opt_in_flags("live", True)["server_log_audit.py"],
                         ["--verify-bots"])


class SecretsStayOutOfTheOutput(unittest.TestCase):
    """checklist-results.json and .seo-runs/ are what gets shared. The run log is
    built from each script's argv, so a key passed as an argument lands in it."""

    def test_secret_values_are_replaced_everywhere(self):
        payload = {"runs": {"indexnow_checker.py --key ABC123": {"error": None}},
                   "items": [{"evidence": "failed: bad key ABC123"}],
                   "nested": [{"deep": {"k": "ABC123"}}]}
        out = redact(payload, ("ABC123",))
        self.assertNotIn("ABC123", json.dumps(out))
        self.assertIn("<redacted>", list(out["runs"])[0])

    def test_nothing_is_touched_without_secrets(self):
        payload = {"runs": {"a.py --flag v": {}}}
        self.assertEqual(redact(payload, ()), payload)


class SampleDiscovery(unittest.TestCase):
    """A sampled asset fails every page-level check, and sampling aggregates on
    the worst verdict — so one stylesheet in the sample condemns the site."""

    def test_assets_are_not_pages(self):
        for url in ("https://e.com/assets/app.css", "https://e.com/logo.png",
                    "https://e.com/f.pdf", "https://e.com/bundle.js"):
            self.assertFalse(looks_like_a_page(url), url)

    def test_real_pages_survive(self):
        for url in ("https://e.com/about", "https://e.com/blog/post?id=7",
                    "https://e.com/", "https://e.com/index.html",
                    "https://e.com/v1.2/guide"):
            self.assertTrue(looks_like_a_page(url), url)

    def test_only_anchors_are_followed(self):
        """The old pattern matched every href in the document, so stylesheets,
        icons and preload hints filled the sample before any real page."""
        html = ('<link rel="stylesheet" href="/app.css">'
                '<link rel="icon" href="/fav.ico">'
                '<a href="/about">a</a>')
        self.assertEqual(ANCHOR_RE.findall(html), ["/about"])

    def test_the_query_string_is_kept(self):
        """Cutting at `?` produced a different URL that frequently 404s, and on
        many sites the query is what makes it a distinct page at all."""
        self.assertEqual(ANCHOR_RE.findall('<a href="/p?id=7#top">x</a>'), ["/p?id=7#top"])


def _page(title="Example", body="Hello there.", head="", extra=""):
    return (f"<!doctype html><html><head><title>{title}</title>{head}</head>"
            f"<body><h1>{title}</h1><p>{body}</p>{extra}</body></html>")


class PageGuard(unittest.TestCase):
    """The hole the reachability gate left open.

    A challenge page and a soft 404 both answer 200 with well-formed HTML, so
    every evidence script runs against a page that is not the site and the
    registry grades whatever the interstitial contains. The gate on status codes
    cannot see either one.
    """

    def test_a_normal_page_passes(self):
        self.assertEqual(page_guard(_page())[0], "")

    def test_cloudflare_challenge_is_caught(self):
        html = _page("Just a moment...", "",
                     extra='<script src="/cdn-cgi/challenge-platform/h/b/orch"></script>')
        kind, detail = page_guard(html)
        self.assertEqual(kind, "bot_challenge")
        self.assertIn("Cloudflare", detail)

    def test_vendor_challenges_are_caught_from_their_markup(self):
        """Where these strings actually live on a block page: a script src, a
        stylesheet href, an element id — never the prose."""
        for tag, vendor in (
                ('<script src="/_Incapsula_Resource?SWJIYLWA=719">', "Imperva"),
                ('<div id="px-captcha"></div>', "PerimeterX"),
                ('<script src="https://ct.datado.me/c.js">', "DataDome"),
                ('<script src="https://token.awswaf.com/x/challenge.js">', "AWS WAF"),
                ('<script src="/sucuri_cloudproxy_js/x.js">', "Sucuri"),
                ('<img src="//errors.edgesuite.net/18.abcd.ip">', "Akamai")):
            kind, detail = page_guard(_page("Blocked", "", extra=tag))
            self.assertEqual(kind, "bot_challenge", tag)
            self.assertIn(vendor.split()[0], detail, tag)

    def test_vendors_that_name_themselves_in_the_text_are_caught_there(self):
        """Imperva and Sucuri print their name on the block page itself, so for
        those two the visible text is the right place to look."""
        for phrase, vendor in (("Incapsula incident ID: 282-31", "Imperva"),
                               ("Access Denied - Sucuri Website Firewall", "Sucuri")):
            kind, detail = page_guard(_page("Blocked", phrase))
            self.assertEqual(kind, "bot_challenge", phrase)
            self.assertIn(vendor, detail, phrase)

    def test_challenge_title_without_a_vendor_string(self):
        self.assertEqual(page_guard(_page("Checking your browser", ""))[0],
                         "bot_challenge")
        self.assertEqual(page_guard(_page("Attention Required!", ""))[0],
                         "bot_challenge")

    def test_a_short_article_quoting_a_vendor_string_is_not_a_challenge(self):
        """The mirror-image failure, and the one an end-to-end run actually hit:
        a 90-word article quoting `cdn-cgi/challenge-platform` in its prose was
        called an interstitial. Word count alone cannot separate the two, because
        real articles are often short. Placement can: on a challenge page the
        vendor string is a script src, in an article it is text."""
        html = _page("How Cloudflare bot protection works",
                     "Cloudflare serves its interstitial from "
                     "cdn-cgi/challenge-platform, which is why a crawler sees "
                     "something different from a browser.")
        self.assertLess(visible_words(html), 120)
        self.assertEqual(page_guard(html)[0], "")

    def test_a_content_page_with_the_marker_in_its_markup_survives(self):
        """Cloudflare's JS detections inject that script into ordinary pages, so
        a marker in the markup cannot condemn a page on its own either — the word
        count is the second condition on every branch."""
        html = _page("A real page", "Words that make this a page. " * 40,
                     extra='<script src="/cdn-cgi/challenge-platform/h/b/jsd"></script>')
        self.assertGreater(visible_words(html), 120)
        self.assertEqual(page_guard(html)[0], "")

    def test_script_bulk_does_not_make_a_challenge_look_content_rich(self):
        """Word counting has to ignore script bodies: a challenge page is mostly
        JavaScript, and counting it would push every one of them over the line."""
        js = "var a=1; function f(){return 'x';} " * 60
        html = _page("Just a moment...", "", extra=f"<script>{js}</script>")
        self.assertLessEqual(visible_words(html), 120)
        self.assertEqual(page_guard(html)[0], "bot_challenge")

    def test_soft_404_is_caught(self):
        for title in ("404 Not Found", "Page not found", "404", "Oops",
                      "Page Not Found | Example Shop", "Страница не найдена",
                      "Nothing found — Example Blog"):
            self.assertEqual(page_guard(_page(title))[0], "soft_404", title)

    def test_an_article_about_404s_is_not_a_soft_404(self):
        """`404` appears in the title of every article ever written about broken
        links. Substring matching would refuse to audit all of them."""
        for title in ("How to fix 404 errors on your site",
                      "The 404 page as a conversion opportunity",
                      "Room 404 | Hotel Beispiel",
                      "Error handling in Django"):
            self.assertEqual(page_guard(_page(title))[0], "", title)

    def test_soft_404_does_not_depend_on_page_size(self):
        """Templated error pages carry the site's whole nav and footer, so they
        are not small — the title is the signal, not the word count."""
        html = _page("404 Not Found", "Try the homepage. " * 200)
        self.assertGreater(visible_words(html), 120)
        self.assertEqual(page_guard(html)[0], "soft_404")


class History(unittest.TestCase):
    """Two runs in one second used to write the same file, so the history lost the
    entry the next diff would have compared against."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.cwd = os.getcwd()
        os.chdir(self.dir)

    def tearDown(self):
        os.chdir(self.cwd)
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_the_stamp_is_sub_second(self):
        self.assertRegex(run_stamp(), r"^\d{8}T\d{9}Z$")

    def test_two_runs_in_one_stamp_do_not_share_a_file(self):
        stamp = run_stamp()
        first = history_path("e.com", stamp)
        with open(first, "w", encoding="utf-8") as f:
            json.dump({"marker": 1}, f)
        second = history_path("e.com", stamp)
        self.assertNotEqual(first, second)
        with open(first, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["marker"], 1,
                             "the earlier run was overwritten")

    def test_the_newest_run_wins_regardless_of_filename_format(self):
        """A directory holding both stamp formats must still order correctly. By
        name every legacy file outranks every current one, because `-` in an ISO
        timestamp sorts below `0`."""
        os.makedirs(os.path.join(".seo-runs", "e.com"))
        for name, started in (("20260803T094000Z.json", "2026-08-03T09:40:00+00:00"),
                              ("20260803T094100500Z.json", "2026-08-03T09:41:00.5+00:00")):
            with open(os.path.join(".seo-runs", "e.com", name), "w", encoding="utf-8") as f:
                json.dump({"started_at": started, "name": name}, f)
        self.assertEqual(previous_run("e.com", "")["name"], "20260803T094100500Z.json")

    def test_a_corrupt_history_file_is_skipped_not_fatal(self):
        """A broken record of an old run is no reason to abandon the current one."""
        os.makedirs(os.path.join(".seo-runs", "e.com"))
        with open(os.path.join(".seo-runs", "e.com", "20260803T094000Z.json"), "w") as f:
            f.write("{not json")
        with open(os.path.join(".seo-runs", "e.com", "20260803T093000Z.json"), "w") as f:
            json.dump({"started_at": "2026-08-03T09:30:00+00:00", "name": "good"}, f)
        self.assertEqual(previous_run("e.com", "")["name"], "good")

    def test_the_current_run_is_excluded(self):
        os.makedirs(os.path.join(".seo-runs", "e.com"))
        path = os.path.join(".seo-runs", "e.com", "20260803T094000Z.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"started_at": "2026-08-03T09:40:00+00:00"}, f)
        self.assertIsNone(previous_run("e.com", path))

    def test_an_unparseable_name_without_a_timestamp_never_wins(self):
        os.makedirs(os.path.join(".seo-runs", "e.com"))
        for name in ("notes.json", "20260803T094000Z.json"):
            with open(os.path.join(".seo-runs", "e.com", name), "w", encoding="utf-8") as f:
                json.dump({"name": name}, f)
        self.assertEqual(previous_run("e.com", "")["name"], "20260803T094000Z.json")


class LabCoreWebVitals(unittest.TestCase):
    """Lab metrics from a browser trace. The risks are units and silence: a
    misread unit turns a failing page into a passing one, and a metric nobody
    measured must not read as a perfect score."""

    def _file(self, payload):
        path = os.path.join(tempfile.mkdtemp(), "cwv.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write(payload if isinstance(payload, str) else json.dumps(payload))
        return path

    def test_good_metrics_are_rated(self):
        out = cwv_read(self._file({"url": "https://e.com/", "lcp_ms": 2100,
                                   "cls": 0.04, "tbt_ms": 150}))
        self.assertEqual(out["lcp_ms_rating"], "good")
        self.assertTrue(out["all_good"])

    def test_the_thresholds_are_googles(self):
        out = cwv_read(self._file({"lcp_ms": 2600, "cls": 0.2, "tbt_ms": 700}))
        self.assertEqual(out["lcp_ms_rating"], "needs_improvement")
        self.assertEqual(out["cls_rating"], "needs_improvement")
        self.assertEqual(out["tbt_ms_rating"], "poor")

    def test_an_unmeasured_metric_is_absent_not_zero(self):
        """Absent is NO_DATA to the runner. Zero would be a perfect score for a
        measurement nobody took."""
        out = cwv_read(self._file({"lcp_ms": 2100}))
        self.assertNotIn("cls", out)
        self.assertEqual(out["missing"], ["cls", "tbt_ms"])
        self.assertIsNone(evaluate({"path": "cls", "lte": 0.1}, out)[0])

    def test_all_good_covers_only_what_was_measured(self):
        out = cwv_read(self._file({"lcp_ms": 2100}))
        self.assertTrue(out["all_good"], "one good metric, and only one was taken")
        self.assertEqual(out["measured"], ["lcp_ms"])

    def test_a_value_with_units_in_it_is_refused(self):
        """"2.1s" cannot be compared with anything, and coercing it would invent a
        number. The file is rejected with the key naming convention explained."""
        with self.assertRaises(ValueError) as caught:
            cwv_read(self._file({"lcp_ms": "2.1s"}))
        self.assertIn("must be a number", str(caught.exception))

    def test_a_file_with_no_metrics_at_all_is_refused(self):
        with self.assertRaises(ValueError):
            cwv_read(self._file({"lcp": 2.1}))

    def test_a_negative_value_is_refused(self):
        with self.assertRaises(ValueError):
            cwv_read(self._file({"lcp_ms": -5}))

    def test_a_missing_file_says_so(self):
        with self.assertRaises(ValueError) as caught:
            cwv_read("/nowhere/cwv.json")
        self.assertIn("no such file", str(caught.exception))

    def test_broken_json_says_so(self):
        with self.assertRaises(ValueError) as caught:
            cwv_read(self._file("{not json"))
        self.assertIn("not JSON", str(caught.exception))

    def test_one_level_of_nesting_is_tolerated(self):
        out = cwv_read(self._file({"url": "https://e.com/",
                                   "metrics": {"lcp_ms": 900, "cls": 0.01,
                                               "tbt_ms": 20}}))
        self.assertEqual(out["measured"], ["lcp_ms", "cls", "tbt_ms"])

    def test_the_registry_keeps_lab_and_field_apart(self):
        """Separate items because they are separate claims. If a lab item ever
        started answering SP-108 or SP-113, one number would stand for both a
        controlled run and what real visitors got."""
        with open(os.path.join(SCRIPTS, "..", "resources", "config",
                               "checklist.json"), encoding="utf-8") as f:
            items = json.load(f)["items"]
        by_id = {i["id"]: i for i in items}
        for lab in ("SP-214", "SP-215", "SP-216"):
            self.assertEqual(by_id[lab]["check"]["script"], "cwv_metrics.py")
        for field in ("SP-108", "SP-113"):
            self.assertEqual(by_id[field]["check"]["script"], "pagespeed.py")


class LocalBusinessSubtypes(unittest.TestCase):
    """Found by the first live audit, not by review. `find_schema_nodes(docs,
    "LocalBusiness")` compares @type as a string, so a restaurant publishing
    `Restaurant` — which is a LocalBusiness — was reported as having no local
    schema, producing a `high` FAIL on LO-198 that was pure fabrication."""

    def _nodes(self, schema_type):
        from local_seo_checker import find_local_business_nodes
        return find_local_business_nodes([{"@type": schema_type, "name": "X"}])

    def test_the_base_type_matches(self):
        self.assertEqual(len(self._nodes("LocalBusiness")), 1)

    def test_a_subtype_matches(self):
        """The live case: a restaurant site scored a fabricated failure on this."""
        for schema_type in ("Restaurant", "Hotel", "Bakery", "Dentist", "Plumber",
                            "ClothingStore", "Campground", "CafeOrCoffeeShop"):
            self.assertEqual(len(self._nodes(schema_type)), 1, schema_type)

    def test_an_unrelated_type_does_not_match(self):
        for schema_type in ("Article", "Product", "WebSite", "Person",
                            "BreadcrumbList", "Organization"):
            self.assertEqual(self._nodes(schema_type), [], schema_type)

    def test_a_type_array_matches_on_any_member(self):
        from local_seo_checker import find_local_business_nodes
        nodes = find_local_business_nodes(
            [{"@type": ["Organization", "Restaurant"], "name": "X"}])
        self.assertEqual(len(nodes), 1)

    def test_an_unknown_subtype_reports_missing_rather_than_guessing(self):
        """The list is a snapshot of a hierarchy that keeps growing, so it will go
        stale. Failing towards "no schema found" is the visible direction —
        accepting anything with "Business" in the name would not be."""
        self.assertEqual(self._nodes("SomeFutureBusinessType"), [])

    def test_a_tourist_attraction_is_a_place_not_a_local_business(self):
        self.assertEqual(self._nodes("TouristAttraction"), [])


class EntityAddressesAndNap(unittest.TestCase):
    def soup(self, body="", nodes=()):
        from bs4 import BeautifulSoup
        blocks = "".join(
            f'<script type="application/ld+json">{json.dumps(node)}</script>'
            for node in nodes)
        return BeautifulSoup(f"<html><body>{body}{blocks}</body></html>",
                             "html.parser")

    def entities(self, body="", nodes=()):
        from entity_checker import extract_entities_from_schema
        return extract_entities_from_schema(self.soup(body, nodes))

    def nap(self, body="", nodes=()):
        from entity_checker import check_nap_consistency
        soup = self.soup(body, nodes)
        return check_nap_consistency(soup, self.entities(body, nodes))

    def test_restaurant_in_a_graph_and_type_lists_are_entities(self):
        nodes = ({"@graph": [
            {"@type": "Restaurant", "name": "R"},
            {"@type": ["Restaurant", "LocalBusiness"], "name": "L"},
            {"@type": "Organization", "name": "O"},
            {"@type": "WebSite", "name": "W"},
        ]},)
        found = self.entities(nodes=nodes)
        self.assertEqual([row["type"] for row in found],
                         ["Restaurant", "Restaurant", "Organization"])

    def test_a_structured_address_visible_on_the_page_has_no_address_issue(self):
        node = {"@type": "Restaurant", "name": "Acme Valley",
                "telephone": "+370 600 00000",
                "address": {"@type": "PostalAddress",
                            "streetAddress": "Kaimynų gatvė 2, Rudiliai"}}
        issues = self.nap("Kaimynų gatvė 2, Rudiliai +370 600 00000", (node,))
        self.assertFalse([i for i in issues if "address" in i["finding"].lower()])

    def test_a_schema_address_missing_from_visible_text_is_a_mismatch(self):
        node = {"@type": "Restaurant", "name": "R",
                "address": {"@type": "PostalAddress",
                            "streetAddress": "Kaimynų gatvė 2"}}
        findings = [i["finding"] for i in self.nap("Welcome", (node,))]
        self.assertTrue(any("not visible" in finding.lower() for finding in findings))
        self.assertFalse(any("no street address detected" in finding.lower()
                             for finding in findings))

    def test_no_structured_address_is_reported_as_undetermined(self):
        node = {"@type": "LocalBusiness", "name": "R"}
        findings = [i["finding"] for i in self.nap("Welcome", (node,))]
        self.assertTrue(any("could not be determined" in finding.lower()
                            for finding in findings))

    def test_the_existing_english_shape_keeps_its_clean_address_verdict(self):
        node = {"@type": "LocalBusiness", "name": "Cafe",
                "address": {"@type": "PostalAddress",
                            "streetAddress": "123 Main Street"}}
        issues = self.nap("Visit Cafe at 123 Main Street", (node,))
        self.assertFalse([i for i in issues if "address" in i["finding"].lower()])

    def test_nap_reports_the_live_shape_locality_disagreement_with_both_types(self):
        nodes = (
            {"@type": "Restaurant", "name": "Acme Valley",
             "telephone": "+37060000000",
             "address": {"@type": "PostalAddress",
                         "streetAddress": "Kaimynų gatvė 2, Rudiliai",
                         "addressLocality": "Molėtų r. sav.", "postalCode": "33171"}},
            {"@type": "Organization", "name": "Acme Valley",
             "telephone": "+37060000000",
             "address": {"@type": "PostalAddress",
                         "streetAddress": "Kaimynų g. 2, Rudiliai",
                         "addressLocality": "Molėtų r.", "postalCode": "33171"}},
        )
        issues = self.nap("Kaimynų gatvė 2, Rudiliai Kaimynų g. 2, Rudiliai", nodes)
        warning = next(i for i in issues if i["severity"] == "Warning"
                       and "addressLocality" in i["finding"])
        self.assertIn("Restaurant", warning["finding"])
        self.assertIn("Organization", warning["finding"])
        self.assertIn("Molėtų r. sav.", warning["finding"])
        self.assertIn("Molėtų r.", warning["finding"])
        self.assertFalse(any("streetAddress" in i["finding"] for i in issues))

    def test_shared_nap_keys_compare_names_across_the_live_three_node_shape(self):
        nodes = (
            {"@id": "https://example.com/#restaurant", "@type": "Restaurant",
             "name": "Fixture Orchard", "telephone": "+37060000000",
             "sameAs": ["https://social.example/fixture-orchard"],
             "address": {"@type": "PostalAddress", "streetAddress": "One",
                         "addressLocality": "North District"}},
            {"@id": "https://example.com/#attraction",
             "@type": "TouristAttraction",
             "name": "Fixture Orchard — Lakeside Family Park",
             "telephone": "+37060000000",
             "sameAs": ["https://example.com/#restaurant",
                        "https://social.example/fixture-orchard"],
             "address": {"@type": "PostalAddress", "streetAddress": "One",
                         "addressLocality": "North District"}},
            {"@type": "Organization", "name": "Fixture Orchard",
             "telephone": "+37060000000",
             "sameAs": ["https://social.example/fixture-orchard"],
             "address": {"@type": "PostalAddress", "streetAddress": "One",
                         "addressLocality": "Northern District"}},
        )
        findings = [issue["finding"] for issue in
                    self.nap("One North District Northern District +37060000000",
                             nodes)
                    if "differs" in issue["finding"]]
        self.assertEqual(sum("addressLocality" in finding for finding in findings), 2)
        self.assertEqual(sum("NAP name" in finding for finding in findings), 2)
        self.assertEqual(len(findings), 4)

    def test_equal_phone_identifies_one_business_despite_other_disagreements(self):
        nodes = (
            {"@id": "https://example.com/#one", "@type": "Restaurant",
             "name": "Fixture Orchard", "telephone": "111",
             "address": {"@type": "PostalAddress", "streetAddress": "One",
                         "addressLocality": "North"}},
            {"@id": "https://example.com/#two", "@type": "Organization",
             "name": "Another Business", "telephone": "111",
             "address": {"@type": "PostalAddress", "streetAddress": "Two",
                         "addressLocality": "South"}},
        )
        self.assertTrue(any("NAP name differs" in issue["finding"]
                            for issue in self.nap("One Two 111", nodes)))

    def test_equal_normalized_street_and_locality_identify_one_business(self):
        nodes = (
            {"@type": "Restaurant", "name": "Fixture Orchard", "telephone": "111",
             "address": {"@type": "PostalAddress",
                         "streetAddress": "Kaimynų g. 2",
                         "addressLocality": "Molėtų r. sav."}},
            {"@type": "Organization", "name": "Another Business", "telephone": "222",
             "address": {"@type": "PostalAddress",
                         "streetAddress": "Kaimynų gatvė 2",
                         "addressLocality": "Molėtų r sav"}},
        )
        self.assertTrue(any("NAP name differs" in issue["finding"]
                            for issue in self.nap("111 222", nodes)))

    def test_equal_street_in_different_localities_does_not_identify(self):
        nodes = (
            {"@type": "Restaurant", "name": "Fixture Orchard",
             "address": {"@type": "PostalAddress", "streetAddress": "Market St 1",
                         "addressLocality": "Vilnius"}},
            {"@type": "Organization", "name": "Another Business",
             "address": {"@type": "PostalAddress", "streetAddress": "Market St 1",
                         "addressLocality": "Kaunas"}},
        )
        self.assertFalse(any("NAP name differs" in issue["finding"]
                             for issue in self.nap(nodes=nodes)))

    def test_text_addresses_without_explicit_localities_do_not_identify(self):
        nodes = (
            {"@type": "Restaurant", "name": "Fixture Orchard",
             "address": "Kaimynų g. 2, Rudiliai"},
            {"@type": "Organization", "name": "Another Business",
             "address": "Kaimynų gatvė 2, Rudiliai"},
        )
        self.assertFalse(any("NAP name differs" in issue["finding"]
                             for issue in self.nap(nodes=nodes)))

    def test_text_and_structured_addresses_do_not_raise_or_identify(self):
        nodes = (
            {"@type": "Restaurant", "name": "Fixture Orchard",
             "address": "Kaimynų g. 2, Rudiliai"},
            {"@type": "Organization", "name": "Another Business",
             "address": {"@type": "PostalAddress",
                         "streetAddress": "Kaimynų g. 2, Rudiliai"}},
        )
        self.assertFalse(any("NAP name differs" in issue["finding"]
                             for issue in self.nap(nodes=nodes)))

    def test_absent_addresses_do_not_raise_or_identify(self):
        nodes = (
            {"@type": "Restaurant", "name": "Fixture Orchard"},
            {"@type": "Organization", "name": "Another Business"},
        )
        self.assertFalse(any("NAP name differs" in issue["finding"]
                             for issue in self.nap(nodes=nodes)))

    def test_shared_social_profile_does_not_identify_one_business(self):
        nodes = (
            {"@id": "https://example.com/#one", "@type": "Restaurant",
             "name": "Fixture Orchard", "telephone": "111",
             "sameAs": ["https://social.example/shared"],
             "address": {"@type": "PostalAddress", "streetAddress": "One"}},
            {"@id": "https://example.com/#two", "@type": "Organization",
             "name": "Another Business", "telephone": "222",
             "sameAs": ["https://social.example/shared"],
             "address": {"@type": "PostalAddress", "streetAddress": "Two"}},
        )
        self.assertFalse(any("NAP name differs" in issue["finding"]
                             for issue in self.nap("One Two 111 222", nodes)))

    def test_same_type_with_different_phone_and_street_is_not_name_compared(self):
        nodes = (
            {"@type": "Restaurant", "name": "Fixture Orchard", "telephone": "111",
             "address": {"@type": "PostalAddress", "streetAddress": "One"}},
            {"@type": "Restaurant", "name": "Another Business", "telephone": "222",
             "address": {"@type": "PostalAddress", "streetAddress": "Two"}},
        )
        self.assertFalse(any("NAP name differs" in issue["finding"]
                             for issue in self.nap("One Two 111 222", nodes)))

    def test_same_type_nodes_with_different_names_still_warn(self):
        nodes = (
            {"@id": "https://example.com/#restaurant-one", "@type": "Restaurant",
             "name": "Fixture Orchard", "telephone": "12345678",
             "address": {"@type": "PostalAddress", "streetAddress": "One"}},
            {"@id": "https://example.com/#restaurant-two", "@type": "Restaurant",
             "name": "Fixture Orchard Dining", "telephone": "12345678",
             "address": {"@type": "PostalAddress", "streetAddress": "One"}},
        )
        issues = self.nap("One 12345678", nodes)
        name_issue = next(issue for issue in issues
                          if "NAP name differs" in issue["finding"])
        self.assertEqual(name_issue["severity"], "Warning")

    def test_equal_or_explicitly_linked_ids_compare_names(self):
        identities = (
            ({"@id": "https://example.com/#place"},
             {"@id": "https://example.com/#place"}),
            ({"@id": "https://example.com/#place"},
             {"@id": "https://example.com/#organization",
              "sameAs": ["https://example.com/#place"]}),
        )
        for left_identity, right_identity in identities:
            with self.subTest(identity=left_identity):
                nodes = (
                    {"@type": "Restaurant", "name": "Fixture Orchard",
                     "telephone": "111",
                     "address": {"@type": "PostalAddress", "streetAddress": "One"},
                     **left_identity},
                    {"@type": "Organization", "name": "Fixture Orchard Company",
                     "telephone": "222",
                     "address": {"@type": "PostalAddress", "streetAddress": "Two"},
                     **right_identity},
                )
                issues = self.nap("One Two 111 222", nodes)
                self.assertTrue(any("NAP name differs" in issue["finding"]
                                    for issue in issues), issues)

    def test_idless_node_can_link_to_the_other_nodes_id(self):
        nodes = (
            {"@id": "https://example.com/#restaurant", "@type": "Restaurant",
             "name": "Fixture Orchard", "telephone": "111"},
            {"@type": "Organization", "name": "Fixture Orchard Cafe",
             "telephone": "222",
             "sameAs": ["https://example.com/#restaurant"]},
        )
        self.assertTrue(any("NAP name differs" in issue["finding"]
                            for issue in self.nap("111 222", nodes)))

    def test_equal_and_single_entity_nap_have_no_disagreement(self):
        node = {"@type": "Restaurant", "name": "R", "telephone": "12345678",
                "address": {"@type": "PostalAddress",
                            "streetAddress": "Kaimynų gatvė 2"}}
        single = self.nap("Kaimynų gatvė 2 12345678", (node,))
        double = self.nap("Kaimynų gatvė 2 12345678", (node, dict(node)))
        self.assertFalse([i for i in single + double
                          if i["severity"] == "Warning" and "differs" in i["finding"]])

    def test_tourist_attraction_address_participates_in_nap_only(self):
        nodes = (
            {"@type": "Restaurant", "name": "R",
             "address": {"@type": "PostalAddress", "streetAddress": "One"}},
            {"@type": "TouristAttraction", "name": "R",
             "address": {"@type": "PostalAddress", "streetAddress": "Two"}},
        )
        issues = self.nap("One Two", nodes)
        self.assertTrue(any("TouristAttraction" in i["finding"] for i in issues))


class RenderedPageMeasurements(unittest.TestCase):
    """Seven items are measured from a rendered page rather than judged. The thing
    that makes that honest is refusing to answer what the render cannot: a desktop
    window says nothing about tap targets, and a window that fits its own content
    says nothing about whether a phone would have to scroll sideways."""

    def _file(self, payload):
        path = os.path.join(tempfile.mkdtemp(), "rendered.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write(payload if isinstance(payload, str) else json.dumps(payload))
        return path

    MOBILE = {"url": "https://e.com/", "viewport": {"width": 375, "height": 812},
              "text_nodes_below_12px": 0, "links_indistinct": 2,
              "overlays_covering_content": 0, "tap_targets_below_48px": 3,
              "horizontal_overflow_px": 0, "text_nodes_clipped": 0}

    def test_a_mobile_render_answers_everything(self):
        out = rendered_read(self._file(self.MOBILE))
        self.assertEqual(out["viewport_class"], "mobile")
        for key in ("text_nodes_below_12px", "links_indistinct",
                    "overlays_covering_content", "tap_targets_below_48px",
                    "mobile_overlays_covering_content", "horizontal_overflow_px",
                    "text_nodes_clipped"):
            self.assertIn(key, out["measured"], key)

    def test_a_desktop_render_drops_the_mobile_metrics(self):
        """Not zeroed. A 0 would be a verdict about a viewport nobody looked at,
        and the runner reads the absent key as NO_DATA."""
        desktop = dict(self.MOBILE, viewport={"width": 1280, "height": 800})
        out = rendered_read(self._file(desktop))
        self.assertEqual(out["viewport_class"], "desktop")
        for key in ("tap_targets_below_48px", "mobile_overlays_covering_content",
                    "horizontal_overflow_px", "text_nodes_clipped"):
            self.assertNotIn(key, out, key)
        self.assertIsNone(evaluate({"path": "tap_targets_below_48px", "eq": 0}, out)[0])
        self.assertIsNone(evaluate({"path": "horizontal_overflow_px", "lte": 1}, out)[0])
        self.assertIsNone(evaluate({"path": "text_nodes_clipped", "eq": 0}, out)[0])
        self.assertTrue(any("mobile render" in m for m in out["missing"]))

    def test_the_desktop_metrics_still_answer_from_a_desktop_render(self):
        desktop = dict(self.MOBILE, viewport={"width": 1280}, links_indistinct=5)
        out = rendered_read(self._file(desktop))
        self.assertFalse(evaluate({"path": "links_indistinct", "eq": 0}, out)[0])

    def test_a_file_without_a_viewport_is_refused(self):
        """Without it there is no way to know which questions the file can answer,
        and the mobile ones would silently be answered from a desktop window."""
        with self.assertRaises(ValueError) as caught:
            rendered_read(self._file({k: v for k, v in self.MOBILE.items()
                                      if k != "viewport"}))
        self.assertIn("viewport.width", str(caught.exception))

    def test_the_mobile_overlay_count_is_derived_not_invented(self):
        payload = dict(self.MOBILE, overlays_covering_content=2)
        payload.pop("tap_targets_below_48px")
        out = rendered_read(self._file(payload))
        self.assertEqual(out["mobile_overlays_covering_content"], 2)

    def test_an_unmeasured_metric_stays_absent(self):
        out = rendered_read(self._file({"viewport": {"width": 375},
                                        "links_indistinct": 1}))
        self.assertNotIn("text_nodes_below_12px", out)
        self.assertIn("text_nodes_below_12px", out["missing"])

    def test_a_non_count_is_refused(self):
        with self.assertRaises(ValueError):
            rendered_read(self._file({"viewport": {"width": 375},
                                      "links_indistinct": "a few"}))

    def test_a_file_with_no_metrics_is_refused(self):
        with self.assertRaises(ValueError):
            rendered_read(self._file({"viewport": {"width": 375}}))

    def test_the_two_owed_mobile_measures_decide_their_items(self):
        """Owed since 0.62.0, when 0.61.0 deleted the Playwright branch that took
        them. The definitions are that branch's: `scrollWidth` past `innerWidth`,
        and text overflowing its own box in either axis.

        `lte: 1` and not `eq: 0` for the overflow, because both numbers are integers
        and one pixel of rounding is not a page that scrolls sideways — so the
        tolerance is asserted here in both directions rather than assumed.
        """
        fits = dict(self.MOBILE, horizontal_overflow_px=0, text_nodes_clipped=0)
        rounding = dict(self.MOBILE, horizontal_overflow_px=1)
        scrolls = dict(self.MOBILE, horizontal_overflow_px=2)
        clipped = dict(self.MOBILE, text_nodes_clipped=1)
        overflow = {"path": "horizontal_overflow_px", "lte": 1}
        clip = {"path": "text_nodes_clipped", "eq": 0}
        self.assertTrue(evaluate(overflow, rendered_read(self._file(fits)))[0])
        self.assertTrue(evaluate(overflow, rendered_read(self._file(rounding)))[0])
        self.assertFalse(evaluate(overflow, rendered_read(self._file(scrolls)))[0])
        self.assertTrue(evaluate(clip, rendered_read(self._file(fits)))[0])
        self.assertFalse(evaluate(clip, rendered_read(self._file(clipped)))[0])

    def test_the_registry_uses_it_for_the_seven_items(self):
        with open(os.path.join(SCRIPTS, "..", "resources", "config",
                               "checklist.json"), encoding="utf-8") as f:
            by_id = {i["id"]: i for i in json.load(f)["items"]}
        for item_id in ("CN-034", "CN-035", "CN-051", "MB-094", "MB-103",
                        "MB-107", "MB-108"):
            self.assertEqual(by_id[item_id]["source"], "script", item_id)
            self.assertEqual(by_id[item_id]["check"]["script"], "rendered_audit.py",
                             item_id)

    def test_the_three_judgement_items_stayed_judgements(self):
        """A close keyword variant and a localised title are not computed values —
        moving them to a measurement would be inventing one."""
        with open(os.path.join(SCRIPTS, "..", "resources", "config",
                               "checklist.json"), encoding="utf-8") as f:
            by_id = {i["id"]: i for i in json.load(f)["items"]}
        for item_id in ("KW-074", "KW-075", "LO-197"):
            self.assertEqual(by_id[item_id]["source"], "llm", item_id)
            self.assertTrue(by_id[item_id].get("lens"), item_id)


class ThinEntryPage(unittest.TestCase):
    """A page with no prose is flagged, not refused.

    An interstitial from a vendor the guard does not recognise and a
    client-rendered shell are indistinguishable from here — and the second is a
    real page with a real finding that the JS-rendering items exist to report.
    Refusing to score would hide that finding behind a guess; scoring silently
    would present a shell's verdicts as the site's. So: audit, and say the number.
    """

    def test_the_threshold_is_lower_than_the_challenge_one(self):
        """Two different questions. The challenge guard asks "is this page an
        interstitial", and needs room for a challenge's own prose; this asks "is
        there anything here to audit at all"."""
        from checklist_runner import CHALLENGE_MAX_WORDS
        self.assertLess(THIN_ENTRY_WORDS, CHALLENGE_MAX_WORDS)

    def test_a_shell_is_thin_and_an_article_is_not(self):
        shell = ('<!doctype html><html><head><title>App</title></head>'
                 '<body><div id="root"></div><script>var a=1;</script></body></html>')
        self.assertLess(visible_words(shell), THIN_ENTRY_WORDS)
        article = _page("Real", "Words that make this a page. " * 20)
        self.assertGreaterEqual(visible_words(article), THIN_ENTRY_WORDS)

    def test_a_shell_is_not_treated_as_an_interstitial(self):
        """It carries no vendor fingerprint and no challenge title, so the guard
        must leave it alone — otherwise the audit refuses every SPA."""
        shell = ('<!doctype html><html><head><title>App</title></head>'
                 '<body><div id="root"></div></body></html>')
        self.assertEqual(page_guard(shell)[0], "")


class PublicSuffixStaleness(unittest.TestCase):
    """The snapshot is a dated artifact, and its age only mattered when somebody
    thought to ask. A stale list is missing suffixes registered since it was taken,
    and the only symptom is a Search Console property that answers nothing."""

    def _snapshot(self, header):
        path = os.path.join(tempfile.mkdtemp(), "psl.dat")
        with open(path, "w", encoding="utf-8") as f:
            f.write(header + "com\nco.uk\n")
        return path

    def test_the_bundled_snapshot_declares_its_date(self):
        taken, age = psl_staleness()
        self.assertRegex(taken, r"^\d{4}-\d{2}-\d{2}$")
        self.assertGreaterEqual(age, 0)

    def test_the_date_is_read_from_the_header(self):
        path = self._snapshot("// snapshot taken 2020-01-01\n")
        self.assertEqual(psl_snapshot_date(path), "2020-01-01")
        self.assertGreater(psl_staleness(path)[1], 365)

    def test_a_snapshot_without_a_date_reports_unknown_age(self):
        """-1, not 0: "we cannot tell how old this is" must not read as "fresh"."""
        self.assertEqual(psl_staleness(self._snapshot("// no stamp here\n")), ("", -1))

    def test_an_unparseable_date_keeps_the_text_and_drops_the_age(self):
        taken, age = psl_staleness(self._snapshot("// snapshot taken last Tuesday\n"))
        self.assertEqual((taken, age), ("last Tuesday", -1))


class WrongPageWidensTheGate(unittest.TestCase):
    """A page that read fine and is the wrong page is not the same as a page that
    could not be read, and the offline checks are where the difference shows."""

    ITEMS = [
        {"id": "F", "check": {"requires": "fetch", "script": "s.py"}},
        {"id": "O", "check": {"requires": "offline", "script": "s.py"}},
        {"id": "G", "check": {"requires": "gsc", "script": "s.py"}},
    ]

    def test_offline_checks_are_gated_when_the_page_is_wrong(self):
        """An interstitial parses perfectly, so the offline scripts grade its 12
        words as the site. In archive mode that produced 6 passes and 10 failures
        before this gate existed."""
        skips = unreachable_skips(self.ITEMS, "soft 404", wrong_page=True)
        self.assertEqual(skips["O"][0], NO_DATA)
        self.assertIn("not the site", skips["O"][1])

    def test_offline_checks_are_not_gated_when_the_fetch_merely_failed(self):
        """There is no HTML to hand them in that case, so they already drop out on
        their missing input, with a reason that says which input."""
        self.assertNotIn("O", unreachable_skips(self.ITEMS, "HTTP 503"))

    def test_search_console_answers_either_way(self):
        for kwargs in ({}, {"wrong_page": True}):
            self.assertNotIn("G", unreachable_skips(self.ITEMS, "x", **kwargs))


class CrossHostRedirect(unittest.TestCase):
    """`fetch_page` used to discard the URL it actually landed on."""

    def test_another_host_wins(self):
        self.assertEqual(audit_target("https://old.com/", "https://new.com/"),
                         "https://new.com/")

    def test_a_same_host_hop_keeps_the_requested_url(self):
        """So redirect_checker.py still sees the hop it exists to report; nothing
        downstream is confused by a path-only redirect."""
        self.assertEqual(audit_target("https://e.com/a", "https://e.com/b"),
                         "https://e.com/a")

    def test_www_counts_as_another_host(self):
        """discover_urls filters on netloc, so www.example.com vs example.com is
        the difference between an eight-page sample and a one-page one."""
        self.assertEqual(audit_target("https://e.com/", "https://www.e.com/"),
                         "https://www.e.com/")

    def test_no_final_url_changes_nothing(self):
        self.assertEqual(audit_target("https://e.com/", ""), "https://e.com/")

    def test_the_search_console_property_follows_the_destination(self):
        """The bug this fixes: sc-domain: was derived from the domain that
        redirected away, and Search Console answered nothing for it."""
        dest = audit_target("https://old.com/", "https://shop.new.co.uk/")
        from urllib.parse import urlparse as _p
        self.assertEqual(registrable_domain(_p(dest).netloc), "new.co.uk")


class FetchCarriesTheDestination(unittest.TestCase):
    """fetch_page against a stubbed transport — the guard and the final URL are
    decided here, so they are worth pinning without a network."""

    class _Resp:
        def __init__(self, text, url, code=200, ctype="text/html"):
            self.text, self.url, self.status_code = text, url, code
            self.headers = {"Content-Type": ctype}

    def _fetch(self, resp, **kw):
        import lib.safe_http as sh
        from checklist_runner import fetch_page
        original = sh.safe_get
        sh.safe_get = lambda url, **_: resp
        try:
            return fetch_page("https://asked.example/", **kw)
        finally:
            sh.safe_get = original

    def test_the_final_url_is_reported(self):
        out = self._fetch(self._Resp(_page(), "https://landed.example/en/"))
        self.assertEqual(out.final_url, "https://landed.example/en/")
        self.assertEqual(out.error, "")
        os.unlink(out.path)

    def test_a_challenge_page_is_an_error_not_a_page(self):
        html = _page("Just a moment...", "")
        out = self._fetch(self._Resp(html, "https://asked.example/"))
        self.assertEqual(out.path, "")
        self.assertEqual(out.guard, "bot_challenge")
        self.assertIn("bot protection", out.error)

    def test_no_page_guard_records_the_suspicion_instead_of_erasing_it(self):
        """An escape hatch that forgets why it was needed is how a challenge page
        ends up scored as a site with nobody able to tell afterwards."""
        html = _page("Just a moment...", "")
        out = self._fetch(self._Resp(html, "https://asked.example/"),
                          enforce_guard=False)
        self.assertTrue(out.path)
        self.assertEqual(out.error, "")
        self.assertEqual(out.guard, "bot_challenge")
        os.unlink(out.path)


class ScriptFailureKind(unittest.TestCase):
    """A timeout and a crash both end as NO_DATA, and until now the report could
    not tell you which. Only one of the two is worth retrying."""

    ITEM = [{"id": "X", "source": "script", "severity": "high", "category": "c",
             "category_label": "C", "plerdy_ref": "", "title": "t",
             "check": {"script": "s.py", "assert": {"path": "n", "eq": 1}}}]

    def _graded(self, result):
        plan = {("s.py", ("s.py",)): ["X"]}
        return grade(self.ITEM, plan, {("s.py", ("s.py",)): result}, {}, False)[0]

    def test_timeout_is_labelled_and_marked_retryable(self):
        row = self._graded({"__error__": "no result after 180s; retryable",
                            "__error_kind__": "timeout"})
        self.assertEqual(row["status"], NO_DATA)
        self.assertEqual(row["error_kind"], "timeout")
        self.assertIn("timed out", row["evidence"])

    def test_crash_is_labelled_a_failure(self):
        row = self._graded({"__error__": "[s.py] Traceback", "__error_kind__": "crash"})
        self.assertEqual(row["error_kind"], "crash")
        self.assertIn("script failed", row["evidence"])

    def test_an_unlabelled_error_is_treated_as_a_crash(self):
        """Older history and any script path that forgets to set a kind must not
        be silently reported as a timeout — a crash is the honest default."""
        row = self._graded({"__error__": "something"})
        self.assertEqual(row["error_kind"], "crash")

    def test_every_kind_run_script_produces_has_a_label(self):
        """The labels live next to the code that raises them; a list kept in a
        test drifts exactly the way the bug did."""
        with open(os.path.join(SCRIPTS, "checklist_runner.py"), encoding="utf-8") as f:
            src = f.read()
        kinds = set(re.findall(r'"error_kind":\s*"(\w+)"', src))
        self.assertTrue(kinds)
        self.assertEqual(kinds - set(FAILURE_LABEL), set())

    def test_a_missing_script_says_so(self):
        out = run_script("definitely_not_a_script.py", [])
        self.assertEqual(out["error_kind"], "missing")


class EvidenceArtifact(unittest.TestCase):
    """The compact run summary must be joinable to a complete evidence file."""

    def test_the_parser_accepts_an_evidence_path(self):
        args = runner.build_parser().parse_args(
            ["https://example.com", "--evidence-json", "evidence.json"])
        self.assertEqual(args.evidence_json, "evidence.json")

    def test_successful_outputs_are_kept_under_the_same_keys_as_runs(self):
        results = {
            ("ok.py", ("ok.py", "https://example.com")):
                {"summary": {"errors": 2}, "issues": ["a", "b"],
                 "__elapsed__": 0.25},
            ("broken.py", ("broken.py", "https://example.com")):
                {"__elapsed__": 0.5, "__error__": "traceback",
                 "__error_kind__": "crash"},
        }
        runs = runner.summarize_runs(results)
        evidence = runner.evidence_runs(results)
        self.assertEqual(set(evidence), set(runs))
        self.assertEqual(evidence["ok.py https://example.com"]["issues"], ["a", "b"])
        self.assertEqual(evidence["broken.py https://example.com"],
                         runs["broken.py https://example.com"])

    def test_an_evidence_file_is_redacted_and_written(self):
        directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, directory, True)
        path = os.path.join(directory, "evidence.json")
        secret = "/tmp/credentials.json"
        runner.write_evidence(path, {"x": {"credential": secret}}, (secret,))
        with open(path, encoding="utf-8") as stream:
            self.assertEqual(json.load(stream), {"x": {"credential": "<redacted>"}})

    def test_a_safe_browsing_env_key_never_reaches_written_artifacts(self):
        directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, directory, True)
        results_path = os.path.join(directory, "results.json")
        evidence_path = os.path.join(directory, "evidence.json")
        secret = "safe-browsing-secret-value"
        old_google = os.environ.get("GOOGLE_SAFE_BROWSING_KEY")
        old_alias = os.environ.pop("SAFE_BROWSING_API_KEY", None)
        os.environ["GOOGLE_SAFE_BROWSING_KEY"] = secret
        self.addCleanup(self._restore_env, "GOOGLE_SAFE_BROWSING_KEY", old_google)
        self.addCleanup(self._restore_env, "SAFE_BROWSING_API_KEY", old_alias)
        results = {
            ("domain_safety_check.py",
             ("domain_safety_check.py", "https://example.com")): {
                 "error": f"request failed for ?key={secret}", "__elapsed__": 0.1}}
        secrets = runner.artifact_secrets({})
        payload = runner.redact({"runs": runner.summarize_runs(results)}, secrets)
        with open(results_path, "w", encoding="utf-8") as stream:
            json.dump(payload, stream)
        runner.write_evidence(
            evidence_path, runner.evidence_artifact(results), secrets)
        for path in (results_path, evidence_path):
            with open(path, encoding="utf-8") as stream:
                self.assertNotIn(secret, stream.read(), path)

    @staticmethod
    def _restore_env(name, value):
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value

    def test_safe_browsing_request_errors_replace_the_key(self):
        import domain_safety_check as safety
        secret = "safe-browsing-secret-value"
        saved = safety.requests.post

        def fail(*_args, **_kwargs):
            raise safety.requests.RequestException(
                f"connection failed for {safety.SB_ENDPOINT}?key={secret}")

        safety.requests.post = fail
        try:
            out = safety.check_safe_browsing("https://example.com", secret, 10)
        finally:
            safety.requests.post = saved
        self.assertNotIn(secret, out["error"])
        self.assertIn("?key=<redacted>", out["error"])

    def test_sampled_pages_are_nested_without_changing_site_level_runs(self):
        site_results = {
            ("site.py", ("site.py", "https://example.com")):
                {"summary": {"errors": 0}, "__elapsed__": 0.1},
        }
        site_evidence = runner.evidence_runs(site_results)
        pages = {
            "https://example.com/": {"page.py https://example.com/": {"count": 0}},
            "https://example.com/about": {
                "page.py https://example.com/about": {"count": 1}},
        }
        artifact = runner.evidence_artifact(site_results, pages)
        self.assertEqual({key: value for key, value in artifact.items()
                          if key != "pages"}, site_evidence)
        self.assertEqual(set(artifact["pages"]), set(pages))

    def test_a_skipped_sampled_page_keeps_its_reason(self):
        skipped = {"https://example.com/missing": {
            "skipped": True, "reason": "HTTP 404"}}
        artifact = runner.evidence_artifact({}, skipped)
        self.assertEqual(artifact["pages"], skipped)

    def test_a_non_sampled_run_omits_the_pages_key(self):
        artifact = runner.evidence_artifact({})
        self.assertNotIn("pages", artifact)

    def test_redaction_reaches_sampled_page_evidence(self):
        directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, directory, True)
        path = os.path.join(directory, "evidence.json")
        secret = "/tmp/page-credentials.json"
        artifact = runner.evidence_artifact({}, {
            "https://example.com/": {"page.py": {"credential": secret}}})
        runner.write_evidence(path, artifact, (secret,))
        with open(path, encoding="utf-8") as stream:
            self.assertNotIn(secret, json.dumps(json.load(stream)))


class UnicodeMinHash(unittest.TestCase):
    def setUp(self):
        import site_crawl
        self.crawl = site_crawl

    def similarity(self, left, right):
        return self.crawl.jaccard_from_minhash(
            self.crawl.minhash_signature(self.crawl.shingle(left)),
            self.crawl.minhash_signature(self.crawl.shingle(right)))

    def test_different_russian_texts_are_not_near_duplicates(self):
        left = "собирайте спелую чернику летом всей семьёй сегодня"
        right = "покормите дружелюбных животных в контактном зоопарке сегодня"
        self.assertLess(self.similarity(left, right), 0.85)

    def test_the_same_russian_text_is_identical(self):
        text = "собирайте спелую чернику летом всей семьёй сегодня"
        self.assertEqual(self.similarity(text, text), 1.0)

    def test_lithuanian_diacritics_stay_in_consecutive_shingles(self):
        text = "mėlynės auga mūsų gražioje sodyboje prie ežero"
        shingles = self.crawl.shingle(text)
        self.assertIn("mėlynės auga mūsų gražioje sodyboje", shingles)

    def test_wordless_texts_are_not_comparable(self):
        self.assertEqual(self.crawl.shingle("!!!"), set())
        self.assertEqual(self.similarity("!!!", "..."), 0.0)


class OneFetchPerUrl(unittest.TestCase):
    """The response cache, and the ways a cache could lie.

    Its purpose is stated in the direction that matters: not "fewer requests" but
    **every item that reports on a URL reports on the same bytes**. Thirty-seven
    fetches of one page are thirty-seven documents the moment the page is not
    static, and items would then disagree with each other while each one was right
    about what it read.

    So the interesting tests here are not the hit-rate ones. They are the ones that
    fix what may never be answered from disk: a request that failed, a request that
    changes something on the server, a body nobody read, and a redirect chain into
    a path robots.txt forbids.
    """

    def setUp(self):
        import lib.safe_http as sh
        self.sh = sh
        self.dir = tempfile.mkdtemp(prefix="test-http-cache-")
        self.saved = os.environ.get(sh.CACHE_DIR_VAR)
        # Robots answers are keyed by `scheme://netloc` and live half an hour, while
        # every origin here is 127.0.0.1 plus an ephemeral port the operating system
        # hands out again. Without a directory of its own, the robots.txt an earlier
        # test served can answer this one's question:
        # `test_a_cache_hit_still_refuses_a_path_robots_forbids` failed exactly that
        # way once in a full suite and never alone, and pre-seeding `Allow: /` for the
        # port a fresh server got reproduces it verbatim.
        #
        # It now covers this class's children too — the two tests below that start
        # processes — because the directory travels in `SEO_RATE_LIMIT_DIR` and they
        # inherit this process's environment. While it was a module constant they
        # could not be told, which is the half `one-test-robots-answers-another` kept
        # open until 0.82.0.
        self.pacing = harness.own_rate_limit_dir()
        self.pacing_dir = self.pacing.__enter__()
        self.loopback = harness.allow_loopback()
        self.loopback.__enter__()

    def tearDown(self):
        self.loopback.__exit__(None, None, None)
        self.pacing.__exit__(None, None, None)
        if self.saved is None:
            os.environ.pop(self.sh.CACHE_DIR_VAR, None)
        else:
            os.environ[self.sh.CACHE_DIR_VAR] = self.saved
        shutil.rmtree(self.dir, ignore_errors=True)

    def _on(self):
        os.environ[self.sh.CACHE_DIR_VAR] = self.dir

    PAGE = "<html><head><title>One</title></head><body><p>only once</p></body></html>"

    def test_nothing_is_cached_unless_a_run_asks_for_it(self):
        """The default is no cache at all. A script run by hand a minute after the
        last one must read the site, not a directory left behind by an audit."""
        with harness.served({"/": self.PAGE}) as site:
            self.sh.safe_get(site.url)
            self.sh.safe_get(site.url)
            self.assertEqual(len(site.paths("GET")), 2)
        self.assertEqual(os.listdir(self.dir), [])

    def test_the_same_url_is_fetched_once(self):
        with harness.served({"/": self.PAGE}) as site:
            self._on()
            self.sh.safe_get(site.url)
            self.sh.safe_get(site.url)
            self.assertEqual(len(site.paths("GET")), 1)

    def test_a_restored_response_is_the_response_that_was_fetched(self):
        """Field by field, because a caller cannot be asked to know which it got.
        `elapsed` is in the list on purpose: three scripts report response time
        from it, so a zero there would be a fabricated performance number."""
        with harness.served({"/": self.PAGE}) as site:
            self._on()
            live = self.sh.safe_get(site.url)
            cached = self.sh.safe_get(site.url)
            self.assertFalse(getattr(live, "from_cache", False))
            self.assertTrue(getattr(cached, "from_cache", False))
            for field in ("text", "content", "status_code", "url", "encoding",
                          "reason", "elapsed"):
                self.assertEqual(getattr(cached, field), getattr(live, field), field)
            self.assertEqual(dict(cached.headers), dict(live.headers))

    def test_a_redirect_chain_survives_intact(self):
        """`redirect_chain` and the hop count are checklist evidence, not
        decoration: an item reports the number of hops it found."""
        with harness.served({"/hop": (301, {"Location": "/"}, ""),
                             "/": self.PAGE}) as site:
            self._on()
            live = self.sh.safe_get(site.base + "/hop")
            # Two requests so far: the hop and the page it points at. The entry
            # covers the whole chain, so asking again costs nothing.
            self.assertEqual(len(site.paths("GET")), 2)
            cached = self.sh.safe_get(site.base + "/hop")
            self.assertEqual([(h.status_code, h.url) for h in cached.history],
                             [(h.status_code, h.url) for h in live.history])
            self.assertEqual(cached.url, live.url)
            self.assertEqual(len(site.paths("GET")), 2)

    def test_a_404_is_an_answer_and_is_kept(self):
        with harness.served({"/": self.PAGE}) as site:
            self._on()
            first = self.sh.safe_get(site.base + "/nope")
            second = self.sh.safe_get(site.base + "/nope")
            self.assertEqual((first.status_code, second.status_code), (404, 404))
            self.assertEqual(site.paths("GET").count("/nope"), 1)

    def test_a_failure_is_never_kept(self):
        """One refused connection must not become every item's refused connection.
        A cached error would turn a transient failure into a whole-audit failure,
        and NO_DATA on 106 items is not more honest for being consistent."""
        import socket
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        dead = probe.getsockname()[1]
        probe.close()
        self._on()
        import requests
        for _ in range(2):
            with self.assertRaises(requests.exceptions.RequestException):
                self.sh.safe_get(f"http://127.0.0.1:{dead}/", timeout=3)
        self.assertEqual([n for n in os.listdir(self.dir) if n.endswith(".resp")], [])

    def test_a_post_goes_out_every_time(self):
        """`indexnow_checker` submits URLs. Replaying a submission from disk would
        report a thing that did not happen — or hide one that needed to."""
        with harness.served({"/ping": "ok"}) as site:
            self._on()
            self.sh.safe_post(site.base + "/ping", data={"n": "1"})
            self.sh.safe_post(site.base + "/ping", data={"n": "1"})
            self.assertEqual(len([m for m, _ in site.requested if m == "POST"]), 2)

    def test_a_stream_is_not_stored(self):
        """Nobody has read the body yet, and a cache cannot store what no one has
        seen — it would write an empty document and serve it as the page."""
        with harness.served({"/": self.PAGE}) as site:
            self._on()
            self.sh.safe_get(site.url, stream=True).close()
            self.assertEqual([n for n in os.listdir(self.dir) if n.endswith(".resp")], [])

    def test_head_and_get_are_different_questions(self):
        with harness.served({"/": self.PAGE}) as site:
            self._on()
            self.sh.safe_head(site.url)
            body = self.sh.safe_get(site.url)
            self.assertEqual(len(site.paths("HEAD")), 1)
            self.assertEqual(len(site.paths("GET")), 1)
            self.assertIn("only once", body.text)

    def test_a_hop_a_caller_wanted_to_see_is_not_answered_with_its_destination(self):
        """`redirect_checker` asks with redirects off because the hop *is* the
        finding. Handing it the 200 at the end would delete the thing it reports."""
        with harness.served({"/hop": (301, {"Location": "/"}, ""),
                             "/": self.PAGE}) as site:
            self._on()
            self.sh.safe_get(site.base + "/hop")
            hop = self.sh.safe_get(site.base + "/hop", allow_redirects=False)
            self.assertEqual(hop.status_code, 301)

    def test_a_smaller_cap_refetches_rather_than_truncating(self):
        """Callers ask for between 500KB and 5MB of the same page. A stored body
        larger than this caller's cap is a miss and the request goes out and fails
        exactly as it would have — trimming the stored body to fit would be
        inventing a document."""
        with harness.served({"/": self.PAGE}) as site:
            self._on()
            whole = self.sh.safe_get(site.url)
            with self.assertRaises(self.sh.SafeHTTPError):
                self.sh.safe_get(site.url, max_response_bytes=10)
            self.assertEqual(len(site.paths("GET")), 2)
            # And a cap the stored body does fit inside is still a hit.
            again = self.sh.safe_get(site.url, max_response_bytes=None)
            self.assertEqual(again.content, whole.content)
            self.assertEqual(len(site.paths("GET")), 2)

    def test_a_different_accept_is_a_different_request(self):
        """Servers may negotiate on it, so it has to be in the key — which is why
        two spellings of one Accept header used to cost every page an extra
        fetch. See `test_there_is_one_accept_header`."""
        with harness.served({"/": self.PAGE}) as site:
            self._on()
            self.sh.safe_get(site.url)
            self.sh.safe_get(site.url, headers={"Accept": "text/plain"})
            self.assertEqual(len(site.paths("GET")), 2)

    def test_there_is_one_accept_header(self):
        """`seo_common.fetch_url` used to send its own, differing from
        `default_headers()` by one media type. Both were reasonable; together they
        made every audited page two requests instead of one, and nothing could see
        it until the requests were countable. A second spelling must not come back
        by being locally sensible somewhere."""
        import seo_common
        with open(seo_common.__file__, encoding="utf-8") as f:
            src = f.read()
        self.assertNotIn('"Accept":', src,
                         "fetch_url is overriding Accept again; put the media type "
                         "in DEFAULT_HEADERS so one page stays one request")

    def test_the_origin_with_and_without_a_slash_is_one_request(self):
        """`http://x` and `http://x/` are one GET described two ways — every client
        puts `/` on the wire for an empty path. Keeping them apart fetched the
        site's home page twice, once as the entry URL and once as a sampled one."""
        with harness.served({"/": self.PAGE}) as site:
            self._on()
            bare = self.sh.safe_get(site.base)
            slashed = self.sh.safe_get(site.base + "/")
            self.assertEqual(len(site.paths("GET")), 1)
            self.assertEqual(bare.url, slashed.url)

    def test_normalising_agrees_with_seo_common(self):
        """The two normalisers used to disagree about exactly this, which is how a
        URL got two cache keys. Same input, same answer, or the disagreement comes
        back somewhere nothing counts requests."""
        import seo_common
        for url in ("http://example.com", "https://example.com",
                    "http://example.com/a", "https://example.com/a?b=1"):
            self.assertEqual(self.sh.normalize_url(url),
                             seo_common.normalize_url(url), url)

    def test_a_torn_entry_is_a_miss_not_a_half_page(self):
        """Serving half a document as though it were the page is the exact failure
        this cache must not have, so the stored length is checked against the body
        actually on disk."""
        with harness.served({"/": self.PAGE}) as site:
            self._on()
            self.sh.safe_get(site.url)
            entry = [n for n in os.listdir(self.dir) if n.endswith(".resp")][0]
            path = os.path.join(self.dir, entry)
            with open(path, "rb") as f:
                blob = f.read()
            with open(path, "wb") as f:
                f.write(blob[:len(blob) - 20])          # a write that did not finish
            self.assertIsNone(self.sh._read_entry(path))
            served_again = self.sh.safe_get(site.url)
            self.assertIn("only once", served_again.text)
            self.assertEqual(len(site.paths("GET")), 2)

    def test_a_cache_hit_still_refuses_a_path_robots_forbids(self):
        """A cached redirect chain must not become the way around robots.txt.
        Without re-checking the hops, any site that redirects could opt out of the
        rule by being fetched twice — once by something that does not consult
        robots.txt, and then from disk by something that does."""
        with harness.served({
            "/robots.txt": (200, {"Content-Type": "text/plain"},
                            "User-agent: *\nDisallow: /private/\n"),
            "/open": (301, {"Location": "/private/page.html"}, ""),
            "/private/page.html": self.PAGE,
        }) as site:
            self._on()
            # Warmed by a caller that does not consult robots.txt — the audit
            # target is fetched exactly this way, by design.
            self.assertEqual(self.sh.safe_get(site.base + "/open").status_code, 200)
            with self.assertRaises(self.sh.RobotsDisallowed):
                self.sh.safe_get(site.base + "/open", respect_robots=True)

    def test_robots_txt_is_fetched_once_however_many_ask(self):
        """It does not go through the response cache — `_fetch_robots` cannot, or it
        would recurse — and its own disk cache had no lock, so 45 scripts starting
        together all missed it and all fetched. Five requests on a CI runner, one on
        a developer machine: a difference only a counted request shows."""
        import subprocess
        with harness.served({"/": self.PAGE, "/a": self.PAGE,
                             "/robots.txt": (200, {"Content-Type": "text/plain"},
                                             "User-agent: *\nAllow: /\n")}) as site:
            code = ("import sys; sys.path.insert(0, %r);"
                    "from lib.safe_http import safe_get;"
                    "print(safe_get(%r, respect_robots=True).status_code)"
                    % (SCRIPTS, site.base + "/a"))
            env = harness.offline_env(**{self.sh.CACHE_DIR_VAR: self.dir})
            # The robots cache is keyed on the origin and lives in the rate-limit
            # directory rather than the run's response cache, so the six children have
            # to agree about which directory that is: they inherit this test's through
            # `SEO_RATE_LIMIT_DIR`, which `offline_env` copies from this process. This
            # test used to rely instead on `served()` handing out a port nothing had
            # ever seen — an assumption an operating system that recycles ports
            # withdraws, and one this suite was measured breaking within a single run.
            procs = [subprocess.Popen([sys.executable, "-c", code], env=env,
                                      stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE, text=True,
                                      close_fds=False)
                     for _ in range(6)]
            outs = [p.communicate(timeout=60) for p in procs]
            self.assertEqual([o.strip() for o, _ in outs], ["200"] * 6,
                             [e for _, e in outs])
            self.assertEqual(site.paths("GET").count("/robots.txt"), 1)

    def test_a_child_process_caches_robots_where_it_was_told_to(self):
        """The half of `one-test-robots-answers-another` that stayed open until 0.82.0.

        A test could point the state directory at its own and the processes it started
        could not be told, because the directory was a module constant. So every child
        went on writing robots answers into `%TEMP%/seo-checklist-rate`, keyed by
        `127.0.0.1:<port>` and good for half an hour — and a full suite left fifteen of
        them there, measured by snapshotting the directory around a run.
        """
        import subprocess
        with harness.served({"/a": self.PAGE,
                             "/robots.txt": (200, {"Content-Type": "text/plain"},
                                             "User-agent: *\nAllow: /\n")}) as site:
            entry = os.path.basename(self.sh._robots_cache_path(site.base))
            # This origin's answer in the *machine-wide* directory, before and after.
            # Existence alone proves nothing: that directory is where every child of
            # every suite run wrote until this release, and it still holds thousands
            # of them — 3451 on the machine this was measured on, one of which can
            # belong to this very port. What this test can say is that nothing touched
            # it now.
            shared = os.path.join(self.sh.DEFAULT_RATE_LIMIT_DIR, entry)
            before = os.path.getmtime(shared) if os.path.exists(shared) else None
            code = ("import sys; sys.path.insert(0, %r);"
                    "from lib.safe_http import safe_get;"
                    "print(safe_get(%r, respect_robots=True).status_code)"
                    % (SCRIPTS, site.base + "/a"))
            proc = subprocess.Popen([sys.executable, "-c", code],
                                    env=harness.offline_env(),
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    text=True, close_fds=False)
            out, err = proc.communicate(timeout=60)
            self.assertEqual(out.strip(), "200", err)
            self.assertIn(entry, os.listdir(self.pacing_dir),
                          "the child did not inherit the state directory")
            after = os.path.getmtime(shared) if os.path.exists(shared) else None
            self.assertEqual(after, before,
                             "the child answered into the machine-wide directory")

    def test_a_stopped_fixture_leaves_no_answer_behind_it(self):
        """An answer must not outlive the server that gave it.

        For a real host, outliving one request is the whole point of the cache. For a
        throwaway origin it is the defect: ports are recycled *inside* one run —
        logging every origin whose robots path was computed across a full suite gave
        `127.0.0.1:59747` served by one process at second 0 and by five others from
        second 10 to second 14, well inside a 1800-second entry's life.
        """
        with harness.served({"/a": self.PAGE,
                             "/robots.txt": (200, {"Content-Type": "text/plain"},
                                             "User-agent: *\nAllow: /\n")}) as site:
            self.sh.safe_get(site.base + "/a", respect_robots=True)
            entry = self.sh._robots_cache_path(site.base)
            self.assertTrue(os.path.exists(entry), "nothing was cached to forget")
        self.assertFalse(os.path.exists(entry),
                         "the next test to draw this port would be answered by this "
                         "server, which has stopped listening")

    def test_eight_processes_asking_at_once_make_one_request(self):
        """The runner starts eight workers together, so without single-flight they
        all miss together and eight processes fetch the page the cache exists to
        fetch once. Separate processes, because that is what the audit is: an
        in-process cache would be no cache at all here."""
        import subprocess
        with harness.served({"/": self.PAGE}) as site:
            code = ("import sys; sys.path.insert(0, %r);"
                    "from lib.safe_http import safe_get;"
                    "print(len(safe_get(%r).text))" % (SCRIPTS, site.url))
            env = harness.offline_env(**{self.sh.CACHE_DIR_VAR: self.dir})
            procs = [subprocess.Popen([sys.executable, "-c", code], env=env,
                                      stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE, text=True,
                                      close_fds=False)
                     for _ in range(8)]
            outs = [p.communicate(timeout=60) for p in procs]
            self.assertEqual([o.strip() for o, _ in outs],
                             [str(len(self.PAGE))] * 8,
                             [e for _, e in outs])
            self.assertEqual(len(site.paths("GET")), 1)

    def test_the_runner_removes_its_cache_when_the_run_ends(self):
        """Per run, not global, is the whole reason a stale page cannot be served:
        there must be no directory left for a later audit to read.

        Run from a temp directory, and not for tidiness: an audit writes its results
        beside itself, so a test that runs the runner from the checkout writes into
        the checkout. This one did, and `checklist-results-crawl.json` reached a
        commit because of it.
        """
        # The working directory is set **inside** the child, after exec, rather than by
        # `cwd=`. This test genuinely needs one — the point is where the runner puts its
        # output when nobody tells it — and `cwd=` is the one argument that forces
        # CPython onto the fork path all on its own, where macOS kills the child before
        # it runs a line. `runpy` with `__main__` gives the runner the same argv and the
        # same `if __name__` entry it gets from the shell.
        launch = ("import os, runpy, sys; os.chdir(sys.argv.pop(1)); "
                  "runpy.run_path(sys.argv.pop(1), run_name='__main__')")
        # The cache goes to `mkdtemp(prefix="seo-http-")`, so it can only be found by
        # that prefix — and this test used to look for it in the *shared* temp
        # directory, which made the assertion a claim about the machine rather than
        # about this run: a second suite in parallel, or any audit anybody else
        # started, failed it with nothing wrong here. It did, on 3.13. Giving the
        # child its own `TMPDIR` is what makes the question answerable: `mkdtemp`
        # reads it, so the only `seo-http-*` that can appear in there is this run's.
        # Snapshotting the shared directory before and after is not enough — a
        # concurrent run creates its cache inside the window.
        sandbox = tempfile.mkdtemp()
        env = harness.offline_env()
        env["TMPDIR"] = sandbox
        # This one child is deliberately *not* told where the pacing state goes: the
        # witness below is that it put its default there, and the default is read from
        # its own `gettempdir()`. Every other child in this file inherits the suite's
        # directory instead.
        env.pop(self.sh.RATE_LIMIT_DIR_VAR, None)
        with harness.served({"/": self.PAGE, "/robots.txt": (404, "")}) as site:
            out = harness.spawn(
                [sys.executable, "-c", launch, self.dir,
                 os.path.join(SCRIPTS, "checklist_runner.py"),
                 site.url, "--allow-private", "--max-rps", "50", "--no-history",
                 "--no-prompt", "--quiet", "--only", "crawling_indexing",
                 "--timeout", "60"],
                env=env, timeout=300)
            self.assertEqual(out.returncode, 0, out.stderr[-2000:])
        # Proof that the child really did treat `sandbox` as its temp directory, so an
        # empty list below cannot mean "looked in the wrong place": pacing writes
        # `seo-checklist-rate/` into `gettempdir()` and nothing removes it.
        self.assertIn("seo-checklist-rate", os.listdir(sandbox),
                      "the child did not use the sandbox as its temp directory")
        left = [d for d in os.listdir(sandbox) if d.startswith("seo-http-")]
        self.assertEqual(left, [], "a run's response cache outlived the run")


class HistoryIsASeries(unittest.TestCase):
    """`.seo-runs/` held every run since 0.1.0 and exactly one was ever read.

    The pair comparison answers "what changed since last time". A site owner asks
    whether months of work moved anything, and until 0.19 the data to answer that
    was on disk and unread.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cwd = os.getcwd()
        os.chdir(self.tmp)
        self.dir = os.path.join(self.tmp, ".seo-runs", "example.com")
        os.makedirs(self.dir)

    def tearDown(self):
        os.chdir(self.cwd)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, name, when, score, statuses):
        payload = {"started_at": when, "mode": "live", "registry_version": "test",
                   "scores": {"seo_score": score, "weight_pct": 50, "decided": 9},
                   "items": [{"id": i, "status": st} for i, st in statuses.items()]}
        with open(os.path.join(self.dir, name), "w", encoding="utf-8") as f:
            json.dump(payload, f)

    def seed(self):
        self.write("a.json", "2026-04-01T09:00:00+00:00", 50,
                   {"X-1": FAIL, "X-2": FAIL, "X-3": PASS})
        self.write("b.json", "2026-05-01T09:00:00+00:00", 60,
                   {"X-1": FAIL, "X-2": PASS, "X-3": PASS})
        self.write("c.json", "2026-06-01T09:00:00+00:00", 70,
                   {"X-1": FAIL, "X-2": FAIL, "X-3": PASS})

    def test_it_reads_every_stored_run_oldest_first(self):
        self.seed()
        series = run_series("example.com", "")
        self.assertEqual([r["seo_score"] for r in series], [50, 60, 70])

    def test_it_is_ordered_by_the_timestamp_inside_the_file(self):
        """Not by filename. The name format has already changed once, so a directory
        holding both sorts wrongly by name — the same reason `previous_run` gives."""
        self.write("zzz.json", "2026-01-01T09:00:00+00:00", 10, {"X-1": PASS})
        self.seed()
        self.assertEqual([r["seo_score"] for r in run_series("example.com", "")],
                         [10, 50, 60, 70])

    def test_the_current_run_is_excluded_by_name(self):
        self.seed()
        series = run_series("example.com", os.path.join(self.dir, "c.json"))
        self.assertEqual([r["seo_score"] for r in series], [50, 60])

    def test_a_corrupt_history_file_is_skipped_rather_than_fatal(self):
        """A bad record of an old audit is no reason to abandon this one."""
        self.seed()
        with open(os.path.join(self.dir, "bad.json"), "w", encoding="utf-8") as f:
            f.write("{not json")
        self.assertEqual(len(run_series("example.com", "")), 3)

    def test_it_reads_no_more_than_the_limit(self):
        self.seed()
        self.assertEqual([r["seo_score"] for r in run_series("example.com", "", 2)],
                         [60, 70])

    def test_the_streak_counts_back_from_now_and_includes_this_run(self):
        self.seed()
        series = run_series("example.com", "")
        rows = {r["id"]: r for r in open_since(
            series, [{"id": "X-1", "status": FAIL, "title": "one", "severity": "high"},
                     {"id": "X-2", "status": FAIL, "title": "two", "severity": "low"}])}
        # X-1 failed in all three stored runs and fails now: four audits.
        self.assertEqual(rows["X-1"]["runs"], 4)
        self.assertEqual(rows["X-1"]["since"], "2026-04-01T09:00:00+00:00")

    def test_an_item_that_was_fixed_and_broke_again_is_not_called_untouched(self):
        """The streak is consecutive, not a total. X-2 failed, passed, failed — an
        accusation that nobody has touched it is one the data does not support."""
        self.seed()
        rows = {r["id"]: r for r in open_since(
            run_series("example.com", ""),
            [{"id": "X-2", "status": FAIL, "title": "two", "severity": "low"}])}
        self.assertEqual(rows["X-2"]["runs"], 2)
        self.assertEqual(rows["X-2"]["since"], "2026-06-01T09:00:00+00:00")

    def test_an_item_that_passes_now_is_not_listed_at_all(self):
        self.seed()
        self.assertEqual(open_since(run_series("example.com", ""),
                                    [{"id": "X-3", "status": PASS, "title": "three",
                                      "severity": "low"}]), [])

    def test_no_history_is_not_an_error(self):
        self.assertEqual(run_series("nowhere.example", ""), [])


# Last statement in the file, and that is load-bearing rather than stylistic: this
# block sat above `HistoryIsASeries`, so `python tests/test_runner.py` called
# `unittest.main()` before those nine tests existed and reported 237 passing out of
# 246 as a full run. `unittest discover` imports the module instead of executing it as
# `__main__`, so CI was never affected and never said anything. There is a test that
# this block is last in every test file.
class TextOutsideLatin1SurvivesTheEvidenceLayer(unittest.TestCase):
    """A Greek query killed four items of a real audit, and named an AttributeError.

    `subprocess.run(text=True)` decodes with the *platform's* preferred encoding, and
    on Windows that is the ANSI codepage. Under cp1252 five bytes have no mapping at
    all — 0x81, 0x8d, 0x8f, 0x90, 0x9d — and 0x81 is the second byte of Greek ρ
    (U+03C1, `cf 81`). The reader thread died, `stdout` came back None, and the first
    attribute touched raised `AttributeError: 'NoneType' object has no attribute
    'strip'` — a message with nothing in it about encodings, from a script that had
    run perfectly. The child half was worse: `print` encodes with the ANSI codepage
    too, so on a stock Windows box seven scripts could not emit the text at all.

    Every fixture in this suite is ASCII, which is why nothing here saw it. These
    tests are the ones that would have.
    """

    GREEK = "κουρείο πάφος"          # carries ρ, the byte cp1252 cannot decode
    POLISH = "Zażółć gęślą jaźń"     # ę is U+0119; its UTF-8 tail is 0x99

    def test_a_dead_reader_thread_is_reported_as_itself(self):
        """The half that fails on every platform, because it needs no encoding at all.

        A decode failure inside `subprocess` leaves `stdout` as None. Before this was
        guarded, every branch below assumed a string and the run was filed under
        whichever attribute happened to be touched first.
        """
        import subprocess as sp

        class Dead:
            returncode = 0
            stdout = None
            stderr = None

        with mock.patch.object(sp, "run", return_value=Dead()):
            out = run_script("detect_profile.py", ["--html", __file__])
        self.assertEqual(out.get("error_kind"), "bad_output", out)
        self.assertIn("could not be decoded", out.get("error", ""))
        self.assertNotIn("AttributeError", out.get("error", ""))

    def _greek_links_export(self) -> str:
        """A Search Console links export whose anchors are Greek and Polish.

        `gsc_links_csv.py` is the vehicle because it is one of the seven scripts that
        print `ensure_ascii=False`, it echoes text straight out of its input, and it
        needs no network, no server and no credentials — so this test measures the
        encoding path and nothing else. A first attempt used `detect_profile.py`,
        which does not return any of the page's words: it passed on the broken code
        as readily as on the repaired one.
        """
        handle = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False,
                                             encoding="utf-8", newline="")
        handle.write("Linking text,Links\n"
                     f"{self.GREEK},12\n"
                     f"{self.POLISH},7\n")
        handle.close()
        self.addCleanup(os.unlink, handle.name)
        return handle.name

    def test_a_script_reads_and_returns_text_outside_latin_1(self):
        """End to end through `run_script`, with the operator's own PYTHONIOENCODING
        taken away — because relying on it is exactly the defect."""
        export = self._greek_links_export()
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PYTHONIOENCODING", None)
            out = run_script("gsc_links_csv.py", [export])
        self.assertIsNone(out.get("error"), out)
        printed = json.dumps(out, ensure_ascii=False)
        self.assertIn(self.GREEK, printed,
                      "the Greek anchor did not survive the trip through the runner")
        self.assertIn(self.POLISH, printed)

    def test_every_script_printing_raw_unicode_can_encode_it(self):
        """Derived from the operation, not from a list.

        A script that prints `ensure_ascii=False` puts raw UTF-8 on stdout and needs
        its own guarantee that stdout can carry it — the runner's environment covers
        a child, and nothing covers somebody running the script by hand. Reading the
        set from the source means a new such script joins this test without anybody
        remembering to add it.
        """
        unguarded = []
        for name in sorted(os.listdir(SCRIPTS)):
            if not name.endswith(".py"):
                continue
            with open(os.path.join(SCRIPTS, name), encoding="utf-8") as handle:
                text = handle.read()
            if "ensure_ascii=False" in text and "_utf8_stdout()" not in text:
                unguarded.append(name)
        self.assertEqual(unguarded, [],
                         "these print raw UTF-8 and never reconfigure stdout, so on "
                         "a Windows console they raise UnicodeEncodeError instead: "
                         f"{unguarded}")

    def test_the_runner_hands_its_children_a_utf8_environment(self):
        """The child half, asserted where it is decided rather than by running a
        console this suite does not have."""
        with open(os.path.join(SCRIPTS, "checklist_runner.py"), encoding="utf-8") as h:
            source = h.read()
        self.assertIn('PYTHONIOENCODING="utf-8"', source)
        self.assertIn('encoding="utf-8"', source.split("subprocess.run(", 1)[1][:300])


if __name__ == "__main__":
    unittest.main()
