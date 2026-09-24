"""The suite and CI reach nothing but this machine.

`openspec/specs/governance/` GOV-7. Until 0.124.0 this was said and not done: the
guard in `lib/safe_http.py` refuses *private* addresses unless allowed, and the suite
allows them for its loopback fixtures — which left the whole public internet open.
Measured with a PEP 578 audit hook over one full run: 68 connections to Wikimedia
(a fixture audit's `entity_checker.py` asking Wikidata and Wikipedia about the
fixture's name, and the known-issues probes doing the same) and 6 to Cloudflare, in a
suite whose governance document said it ran offline.

Two layers hold it now, and each is read here:

* the guard refuses any host other than this machine, **before resolving it**, while
  `SEO_LOOPBACK_ONLY` is set — which `tests/harness.py` does for the suite and every
  child, and `ci.yml` does for every job, and `tools/ci_local.py` applies locally;
* a tripwire at the socket (`tests/tripwire/`) catches whatever does not go through
  the guard: it raises in the test process and ends a child, because the scripts
  swallow their own exceptions and a request nobody guarded would otherwise pass as
  "not found".
"""
from __future__ import annotations

import os
import socket
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPTS = os.path.join(ROOT, "skills", "seo-checklist", "scripts")
TOOLS = os.path.join(ROOT, "skills", "seo-checklist", "tools")
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, TOOLS)
sys.path.insert(0, HERE)

import harness  # noqa: E402
from lib import safe_http as sh  # noqa: E402

TEST_NET = "192.0.2.1"          # RFC 5737: documentation-only, routes nowhere


class TheSuiteIsLoopbackOnly(unittest.TestCase):

    def test_the_harness_sets_the_switch_for_this_process_and_its_children(self):
        self.assertEqual(os.environ.get("SEO_LOOPBACK_ONLY"), "1")
        self.assertTrue(sh.loopback_only())
        for name, env in (("offline_env", harness.offline_env()),
                          ("tls_env", harness.tls_env())):
            with self.subTest(env=name):
                self.assertEqual(env.get("SEO_LOOPBACK_ONLY"), "1")

    def test_every_spawned_child_carries_the_tripwire_whatever_env_it_was_given(self):
        """A child started with this process's environment inherits the tripwire
        through `PYTHONPATH`, which `harness` sets on import. `spawn` guarantees it also
        for an environment a test built itself — the case inheritance cannot reach.
        (A test that clears `SEO_LOOPBACK_ONLY` for itself stands both layers down for
        whatever it starts; at 0.124.0 two such children were found by the audit hook
        and given the switch back.)"""
        env = harness.with_tripwire({"PYTHONPATH": SCRIPTS})
        self.assertEqual(env["PYTHONPATH"].split(os.pathsep)[:2],
                         [harness.TRIPWIRE, SCRIPTS])
        probe = harness.spawn([sys.executable, "-c",
                               "import sys; print('tripwire' in sys.modules)"],
                              env={k: v for k, v in os.environ.items()
                                   if k != "PYTHONPATH"})
        self.assertEqual(probe.stdout.strip(), "True", probe.stderr)

    def test_the_workflow_sets_the_switch_for_every_job_and_the_local_gate_reads_it(self):
        import ci_local
        workflow = ci_local.load_workflow()
        self.assertEqual(str((workflow.get("env") or {}).get("SEO_LOOPBACK_ONLY")), "1")
        for job_name, job in workflow["jobs"].items():
            for step in job["steps"]:
                with self.subTest(job=job_name, step=step.get("name", "(unnamed)")):
                    env = ci_local.step_env({}, workflow, job, step)
                    self.assertEqual(env.get("SEO_LOOPBACK_ONLY"), "1")


class TheGuardRefusesBeforeResolving(unittest.TestCase):

    def test_a_public_name_is_refused_without_a_dns_query(self):
        """A DNS query is itself a request to somebody else's server, so the refusal
        has to come first. `getaddrinfo` is replaced by something that fails the test
        if it is called at all."""
        def resolver_called(*args, **kwargs):
            raise AssertionError(f"resolved {args[0]!r} before refusing it")
        with mock.patch.object(sh.socket, "getaddrinfo", side_effect=resolver_called):
            with self.assertRaises(sh.LoopbackOnly) as caught:
                sh.assert_safe_url("https://www.wikidata.org/w/api.php")
        self.assertIn("SEO_LOOPBACK_ONLY", str(caught.exception))

    def test_the_refusal_is_a_blocked_fetch_not_an_unresolved_host(self):
        import seo_common
        self.assertEqual(seo_common.fetch_error_kind(sh.LoopbackOnly("x")), "blocked")
        out = seo_common.fetch_url("https://example.com/")
        self.assertEqual(out["error_kind"], "blocked")
        self.assertIn("loopback-only", out["error"])

    def test_this_machine_is_still_reachable(self):
        with mock.patch.dict(os.environ, {"SEO_ALLOW_PRIVATE": "1"}):
            with harness.served({"/": "<html><body>here</body></html>"}) as site:
                self.assertEqual(sh.safe_get(site.url, timeout=5).status_code, 200)
        self.assertTrue(sh._is_loopback_host("localhost"))
        self.assertTrue(sh._is_loopback_host("::1"))
        self.assertFalse(sh._is_loopback_host("10.0.0.5"))

    def test_the_switch_off_leaves_the_public_policy_as_it_was(self):
        with mock.patch.dict(os.environ, {"SEO_LOOPBACK_ONLY": ""}):
            self.assertFalse(sh.loopback_only())
            with mock.patch.object(sh.socket, "getaddrinfo", return_value=[
                    (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]):
                self.assertEqual(sh.assert_safe_url("https://example.com/"),
                                 "https://example.com/")


class TheTripwireCatchesWhatTheGuardNeverSaw(unittest.TestCase):

    def test_in_this_process_a_name_lookup_raises(self):
        import tripwire
        with self.assertRaises(tripwire.NetworkTripped):
            socket.getaddrinfo("example.com", 443)
        socket.getaddrinfo("127.0.0.1", 80)          # this machine
        socket.getaddrinfo("93.184.216.34", 80)      # a literal: no request is made

    def test_a_child_that_connects_out_is_ended_and_says_why(self):
        child = harness.spawn([sys.executable, "-c",
                               "import socket\n"
                               f"socket.create_connection(({TEST_NET!r}, 80), timeout=0.5)\n"
                               "print('reached')"])
        import tripwire
        self.assertEqual(child.returncode, tripwire.EXIT_CODE, child.stderr)
        self.assertNotIn("reached", child.stdout)
        self.assertIn(f"connected to {TEST_NET}:80", child.stderr)

    def test_a_child_that_swallows_the_error_is_ended_anyway(self):
        """The reason a child is ended rather than raised at: `entity_checker.py`'s
        lookups caught every exception into "not found" until 0.124.0."""
        child = harness.spawn([sys.executable, "-c",
                               "import socket\n"
                               "try:\n"
                               "    socket.getaddrinfo('www.wikidata.org', 443)\n"
                               "except Exception:\n"
                               "    pass\n"
                               "print('carried on')"])
        import tripwire
        self.assertEqual(child.returncode, tripwire.EXIT_CODE, child.stderr)
        self.assertNotIn("carried on", child.stdout)


class AChildBinaryTheTripwireCannotSee(unittest.TestCase):

    def test_whois_is_never_started_in_a_loopback_only_process(self):
        """`domain_safety_check.py` runs the system `whois`, which the tripwire —
        a Python audit hook — cannot see, and which always asks a registry."""
        import domain_safety_check
        with mock.patch.object(domain_safety_check.subprocess, "run") as started:
            out = domain_safety_check.check_whois("example.com", timeout=5)
        started.assert_not_called()
        self.assertFalse(out["checked"])
        self.assertIn("loopback-only", out["error"])


class ALookupNotAskedIsNotALookupThatFoundNothing(unittest.TestCase):
    """What the switch changes on a fixture audit: `entity_checker.py`'s Wikidata and
    Wikipedia lookups are refused, and until 0.124.0 a refused lookup read exactly
    like an empty one."""

    def test_a_refused_lookup_says_not_asked(self):
        import entity_checker
        for lookup in (entity_checker.check_wikidata, entity_checker.check_wikipedia):
            with self.subTest(lookup=lookup.__name__):
                out = lookup("Fixture Bakery")
                self.assertIsNone(out["found"])
                self.assertFalse(out["checked"])
                self.assertIn("loopback-only", out["error"])

    def test_the_report_says_it_could_not_ask_and_claims_no_absence(self):
        import entity_checker
        page = ('<html><head><script type="application/ld+json">'
                '{"@type": "Organization", "name": "Fixture Bakery"}'
                '</script></head><body>Fixture Bakery</body></html>')
        with mock.patch.dict(os.environ, {"SEO_ALLOW_PRIVATE": "1"}):
            with harness.served({"/": page}) as site:
                report = entity_checker.run_entity_check(site.url)
        findings = [issue["finding"] for issue in report["issues"]]
        self.assertIsNone(report["summary"]["wikidata_found"])
        self.assertIsNone(report["summary"]["wikipedia_found"])
        self.assertTrue(any("could not be asked" in f for f in findings), findings)
        self.assertFalse(any(f.startswith(("No Wikidata entry", "No Wikipedia article"))
                             for f in findings), findings)


if __name__ == "__main__":
    unittest.main()
