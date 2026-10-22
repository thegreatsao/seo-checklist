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
import shlex
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
                # And the tripwire, which until F04 `offline_env` dropped from
                # `PYTHONPATH`: a child given it by a bare `subprocess.run` ran unwatched.
                self.assertEqual(env.get("SEO_TRIPWIRE"), "1")
                self.assertEqual(env["PYTHONPATH"].split(os.pathsep)[0], harness.TRIPWIRE)

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

    def test_git_is_allowed_no_transport_but_this_disk(self):
        """`git` has transports of its own. Until 0.150.0 two tests of the notebook
        tool ran `git fetch` in this repository on every run: the suite reached
        GitHub and moved the clone's remote refs. It was found on a Mac, where a
        rehearsal of the push gate compares the repository's refs before and after
        and `origin/main` had moved in between.

        `.invalid` never resolves, so without the switch the answer is a failed
        lookup, and with it a refusal that asked nobody."""
        import git_checkout
        self.assertEqual(os.environ.get("GIT_ALLOW_PROTOCOL"), "file")
        done = git_checkout._run_git(
            ["ls-remote", "https://example.invalid/nothing.git"], timeout=60)
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("not allowed", done.stderr)


class TheTripwireHasASwitchOfItsOwn(unittest.TestCase):
    """Until F04 the tripwire read `SEO_LOOPBACK_ONLY`, so a test that cleared the
    guard's switch to exercise its public-address policy stood both layers down for
    itself and for whatever it started. The tripwire's switch is `SEO_TRIPWIRE`, which
    no test has a reason to clear."""

    def test_the_harness_arms_it_for_this_process_and_every_child(self):
        self.assertEqual(os.environ.get("SEO_TRIPWIRE"), "1")
        self.assertEqual(harness.with_tripwire({}).get("SEO_TRIPWIRE"), "1")

    def test_clearing_the_guards_switch_leaves_the_tripwire_armed(self):
        import tripwire
        with mock.patch.dict(os.environ, {"SEO_LOOPBACK_ONLY": ""}):
            with self.assertRaises(tripwire.NetworkTripped):
                socket.getaddrinfo("example.com", 443)

    def test_a_child_whose_guard_is_off_is_still_ended(self):
        child = harness.spawn([sys.executable, "-c",
                               "import socket\n"
                               f"socket.create_connection(({TEST_NET!r}, 80), timeout=0.5)\n"
                               "print('reached')"],
                              env=harness.offline_env(SEO_LOOPBACK_ONLY=""))
        import tripwire
        self.assertEqual(child.returncode, tripwire.EXIT_CODE, child.stderr)
        self.assertNotIn("reached", child.stdout)


class AProgramIsStartedOnlyWithItsReasonWritten(unittest.TestCase):
    """The tripwire is a Python audit hook, so a binary a Python process starts is
    beyond it. Until F04 that was the Reader line's "a new binary would be unread":
    `whois` was held only because its caller consults the switch. The hook now sees
    the start itself, and a program that is not Python and not in
    `tripwire.PROGRAMS`, with the reason it reaches nothing, is refused — before it
    runs, so the program need not exist for the refusal to be read."""

    def test_in_this_process_an_unlisted_program_raises_before_it_starts(self):
        import subprocess
        import tripwire
        missing = os.path.join(HERE, "no-such-directory", "whois")
        with self.assertRaises(tripwire.NetworkTripped) as caught:
            subprocess.run([missing], close_fds=False)
        self.assertIn("whois", str(caught.exception))

    def test_a_child_that_starts_an_unlisted_program_is_ended_and_says_why(self):
        missing = os.path.join(HERE, "no-such-directory", "notebooklm")
        child = harness.spawn([sys.executable, "-c",
                               "import subprocess, sys\n"
                               "try:\n"
                               f"    subprocess.run([{missing!r}], close_fds=False)\n"
                               "except Exception:\n"
                               "    pass\n"
                               "print('carried on')"])
        import tripwire
        self.assertEqual(child.returncode, tripwire.EXIT_CODE, child.stderr)
        self.assertNotIn("carried on", child.stdout)
        self.assertIn("notebooklm", child.stderr)

    def test_every_listed_program_says_why_it_reaches_nothing(self):
        import tripwire
        self.assertIn("git", tripwire.PROGRAMS)
        self.assertNotIn("whois", tripwire.PROGRAMS)
        for name, reason in tripwire.PROGRAMS.items():
            with self.subTest(program=name):
                self.assertGreater(len(reason.split()), 5, reason)

    def test_a_python_child_started_with_the_tripwire_left_out_is_refused(self):
        """An environment a test builds from nothing drops both switches, and a child
        given it would run unwatched; `harness.spawn` puts them back, a bare
        `subprocess.run` cannot."""
        import subprocess
        import tripwire
        with self.assertRaises(tripwire.NetworkTripped) as caught:
            subprocess.run([sys.executable, "-c", "pass"], close_fds=False,
                           env={"PATH": os.environ.get("PATH", "")})
        self.assertIn("tripwire", str(caught.exception))

    def test_a_python_child_told_to_skip_its_path_or_its_site_is_refused(self):
        """`-I`, `-E` and `-S` make an interpreter ignore `PYTHONPATH` or skip `site`,
        so the tripwire never loads in it whatever the environment says (review, F04
        batch 5)."""
        import tripwire
        for argv in (["-I", "-c", "pass"], ["-E", "-c", "pass"], ["-S", "-c", "pass"],
                     ["-bI", "-c", "pass"], ["-X", "utf8", "-I", "x.py"]):
            with self.subTest(argv=argv):
                self.assertTrue(tripwire.violation(
                    "subprocess.Popen", (sys.executable, [sys.executable, *argv], None, None)))
        # Review pass 2: a long option's value hid a later flag, and a quoted Windows path
        # with a space split into words that were not options.
        self.assertTrue(tripwire.violation("subprocess.Popen", (
            sys.executable, [sys.executable, "--check-hash-based-pycs", "always", "-I", "-c",
                             "pass"], None, None)))
        self.assertTrue(tripwire.violation("subprocess.Popen", (
            None, '"C:\\Program Files\\Python311\\python.exe" -I -c pass', None, None)))
        for argv in (["-c", "print('-I')"], ["-u", "x.py", "-I"], ["-m", "pip", "-E"]):
            with self.subTest(argv=argv):
                self.assertFalse(tripwire.violation(
                    "subprocess.Popen", (sys.executable, [sys.executable, *argv], None, None)))

    def test_a_relative_path_is_read_from_the_directory_the_child_starts_in(self):
        import tripwire
        env = dict(os.environ, PYTHONPATH="tests/tripwire")
        self.assertTrue(tripwire.violation(
            "subprocess.Popen", (sys.executable, [sys.executable, "-c", "pass"], HERE, env)))
        self.assertFalse(tripwire.violation(
            "subprocess.Popen", (sys.executable, [sys.executable, "-c", "pass"], ROOT, env)))

    def test_an_inherited_environment_is_read_like_a_given_one(self):
        import tripwire
        with mock.patch.dict(os.environ, {"PYTHONPATH": ""}):
            self.assertTrue(tripwire.violation(
                "subprocess.Popen", (sys.executable, [sys.executable, "-c", "pass"], None, None)))

    def test_git_is_started_only_without_a_transport(self):
        """`PROGRAMS` gives git's reason as `GIT_ALLOW_PROTOCOL=file`; the hook holds it."""
        import tripwire
        env = {k: v for k, v in os.environ.items() if k != "GIT_ALLOW_PROTOCOL"}
        self.assertTrue(tripwire.violation("subprocess.Popen", ("/usr/bin/git", ["git"], None, env)))
        self.assertFalse(tripwire.violation(
            "subprocess.Popen", ("/usr/bin/git", ["git"], None, dict(env, GIT_ALLOW_PROTOCOL="file"))))
        # A listed program given an environment that disarms the tripwire would start its
        # own children unwatched (the review's M13 deleted this check and stayed green).
        disarmed = dict(env, GIT_ALLOW_PROTOCOL="file", SEO_TRIPWIRE="")
        self.assertTrue(tripwire.violation("subprocess.Popen",
                                           ("/usr/bin/git", ["git"], None, disarmed)))

    def test_python_is_known_by_its_name_or_its_first_line(self):
        import tripwire
        self.assertTrue(tripwire.is_python(sys.executable))
        self.assertTrue(tripwire.is_python("/usr/bin/python3.11"))
        self.assertTrue(tripwire.is_python(r"C:\Python311\python.exe"))
        self.assertFalse(tripwire.is_python("/usr/bin/whois"))
        script = os.path.join(HERE, "tripwire", "sitecustomize.py")
        self.assertFalse(tripwire.is_python(script))     # no `#!` line


class EveryGateStepIsWatched(unittest.TestCase):
    """The guard's switch reached every step of the workflow and the tripwire only
    the `Tests` step, until F04: the smoke runs, the live path and every `tools/` gate
    ran with nothing under the guard. And one gate step fetched its program from the
    npm registry on every run, which is a gate that fails for npm's outage."""

    @classmethod
    def setUpClass(cls):
        import ci_local
        cls.ci_local = ci_local
        cls.workflow = ci_local.load_workflow()

    def run_steps(self):
        for job_name, job in self.workflow["jobs"].items():
            for step in job["steps"]:
                if "run" in step:
                    yield job_name, job, step

    def test_every_gate_step_arms_the_tripwire_and_only_an_install_disarms_it(self):
        for job_name, job, step in self.run_steps():
            with self.subTest(job=job_name, step=step.get("name", "(unnamed)")):
                env = self.ci_local.step_env({}, self.workflow, job, step)
                if self.ci_local.only_installs(step["run"]):
                    self.assertEqual(env.get("SEO_TRIPWIRE", ""), "",
                                     "an install reaches its package index by design")
                else:
                    self.assertEqual(env.get("SEO_TRIPWIRE"), "1")
                    self.assertIn("tests/tripwire",
                                  env.get("PYTHONPATH", "").split(os.pathsep))

    def test_a_gate_step_names_no_program_that_fetches(self):
        """The hook cannot see a step's own shell lines, so they are read: a word
        list, and the narrowing GOV-7's Reader line names."""
        import re
        # `npx --offline` runs a package from npm's cache and never asks the registry.
        fetchers = re.compile(r"\bnpx\b(?!\s+--offline\b)|\bnpm\s+(?:install|i|ci|exec)\b|\bpip3?\s+install\b"
                              r"|-m\s+pip\s+install\b|\bwget\b"
                              r"|\bgit\s+(?:fetch|pull|clone|push|ls-remote|submodule)\b")
        remote = re.compile(r"https?://(?!127\.0\.0\.1[:/]|localhost[:/]|\[::1\])")
        for job_name, _job, step in self.run_steps():
            if self.ci_local.only_installs(step["run"]):
                continue
            for line in step["run"].splitlines():
                line = line.strip()
                if line.startswith("#"):
                    continue
                with self.subTest(job=job_name, step=step.get("name"), line=line):
                    self.assertIsNone(fetchers.search(line))
                    if re.search(r"\bcurl\b", line):
                        self.assertIsNone(remote.search(line))

    def test_warming_npx_is_an_install_and_running_a_package_is_not(self):
        """`npx --offline` reads npx's own cache, which `npm install -g` does not fill
        (npm 12: a full packument where npx asks for the abbreviated one, and no
        `_npx` tree) and `npm cache add` fills without the dependencies. Running the
        pin once, for its version, in the install step is what fills it — and only a
        line that does nothing else may pass for an install, or a gate could hide in
        one (review, F04 batch 5)."""
        installs = self.ci_local.installs
        self.assertTrue(installs("npx -y @fission-ai/openspec@1.12.0 --version"))
        self.assertTrue(installs("npx --yes @fission-ai/openspec@1.12.0 --version"))
        self.assertFalse(installs("npx -y @fission-ai/openspec@1.12.0 validate --all"))
        self.assertFalse(installs("npx --offline -y @fission-ai/openspec@1.12.0 --version"))

    def test_the_package_a_gate_runs_offline_is_the_one_the_install_warmed(self):
        import re
        spec = re.compile(r"npx\s+(?:--offline\s+)?(?:-y|--yes)\s+(\S+)")
        for job_name, job in self.workflow["jobs"].items():
            warmed, run = set(), set()
            for step in job["steps"]:
                for line in (step.get("run") or "").splitlines():
                    found = spec.search(line)
                    if found and not line.strip().startswith("#"):
                        (warmed if self.ci_local.installs(line) else run).add(found.group(1))
            with self.subTest(job=job_name):
                self.assertLessEqual(run, warmed, "a gate runs a package nothing cached")

    def test_a_gate_steps_python_and_its_children_load_the_tripwire(self):
        """Started the way a gate step starts it — from the repository root with the
        workflow's relative `PYTHONPATH` — and its child from another directory, which
        a relative path alone would not reach."""
        import tempfile
        step = next(s for _, _, s in self.run_steps() if s.get("name") == "Tests")
        job = self.workflow["jobs"]["test"]
        base = {k: v for k, v in os.environ.items()
                if k not in ("PYTHONPATH", "SEO_TRIPWIRE", "GIT_ALLOW_PROTOCOL",
                             "SEO_LOOPBACK_ONLY")}
        env = self.ci_local.step_env(base, self.workflow, job, step)
        elsewhere = tempfile.mkdtemp()
        self.addCleanup(os.rmdir, elsewhere)
        line, extra = self.probe(elsewhere)
        ok, _, out = self.ci_local.run_step("probe", line, {**env, **extra})
        self.assertTrue(ok, out)
        self.assertEqual(out.split(), ["True", "True", "file"], out)

    @staticmethod
    def probe(elsewhere: str) -> tuple[str, dict]:
        """The step line and the environment it adds."""
        # The parent moves before it starts the child, so the child starts in another
        # directory: a relative entry on its `PYTHONPATH` would resolve to nothing there.
        child = "import os, sys; print('tripwire' in sys.modules, os.environ.get('GIT_ALLOW_PROTOCOL'))"
        probe = ("import os, subprocess, sys; print('tripwire' in sys.modules); "
                 "os.chdir(os.environ['PROBE_DIR']); "
                 f"print(subprocess.run([sys.executable, '-c', {child!r}], "
                 "capture_output=True, text=True, close_fds=False).stdout.strip())")
        return f"{shlex.quote(sys.executable)} -c {shlex.quote(probe)}", {"PROBE_DIR": elsewhere}

    def test_the_probe_survives_a_windows_command_line(self):
        r"""CI's Windows legs ran the probe with each doubled backslash halved on its way
        from bash to python.exe: `os.chdir('C:\\Users\\…')` arrived as
        `os.chdir('C:\Users\…')`, a SyntaxError. A path in an environment variable
        never crosses that command line."""
        line, extra = self.probe(r"C:\Users\RUNNER~1\AppData\Local\Temp\tmpoymqk8gf")
        source = shlex.split(line)[2].replace("\\\\", "\\")
        compile(source, "<probe>", "exec")

    def test_every_lint_step_passes_under_the_tripwire(self):
        """Run as the gate runs it, on every leg. Until 0.176.1 the Windows leg ran
        `python -m ruff check .`, whose `__main__` starts the ruff binary from a Python
        that has the tripwire, and the tripwire refused it: CI's first run of 0.176.0
        ended there on Windows. The Linux leg's shell starts ruff, as Windows' now does."""
        base = {k: v for k, v in os.environ.items()
                if k not in ("PYTHONPATH", "SEO_TRIPWIRE", "GIT_ALLOW_PROTOCOL",
                             "SEO_LOOPBACK_ONLY")}
        base["PATH"] = os.path.dirname(sys.executable) + os.pathsep + base.get("PATH", "")
        lint = [(name, job, step) for name, job, step in self.run_steps()
                if step.get("name") == "Lint"]
        self.assertEqual({name for name, _, _ in lint}, {"test", "test-windows"})
        for job_name, job, step in lint:
            with self.subTest(job=job_name):
                env = self.ci_local.step_env(base, self.workflow, job, step)
                ok, _, out = self.ci_local.run_step("Lint", step["run"], env)
                self.assertTrue(ok, out)


class EveryTestModuleImportsTheHarness(unittest.TestCase):
    """A module run alone has the switches and the tripwire only if it imports
    `tests/harness.py`; under `discover` another module's import covered it. Until F04
    twenty did not."""

    def test_every_test_module_imports_the_harness(self):
        import re
        missing = []
        for name in sorted(os.listdir(HERE)):
            if name.startswith("test_") and name.endswith(".py"):
                with open(os.path.join(HERE, name), encoding="utf-8") as f:
                    if not re.search(r"^\s*(?:import harness\b|from harness import\b)",
                                     f.read(), re.M):
                        missing.append(name)
        self.assertEqual(missing, [])


class AThirdPartyServiceIsNotAskedEither(unittest.TestCase):
    """Two scripts call `requests` directly because they address a fixed service, not
    the audited site, so the guard never saw them. Until F04 `html_validator.py` asked
    validator.w3.org on every run of the suite where its child lacked the tripwire —
    found when the tripwire began refusing such children — and in the live-path gate
    step, which had none. Under the switch both say they did not ask."""

    def refuse(self, *args, **kwargs):
        raise AssertionError(f"asked {args[0] if args else kwargs}")

    def test_the_html_validator_is_not_asked(self):
        import html_validator
        with mock.patch.object(html_validator.requests, "get", side_effect=self.refuse), \
                mock.patch.object(html_validator.requests, "post", side_effect=self.refuse):
            out = html_validator.validate("http://127.0.0.1:9/")
        self.assertEqual(out["error_kind"], "blocked")
        self.assertIn("loopback-only", out["error"])
        self.assertNotIn("errors", out.get("summary", {}))

    def test_safe_browsing_is_not_asked_even_with_a_key(self):
        import domain_safety_check
        with mock.patch.object(domain_safety_check.requests, "post", side_effect=self.refuse):
            out = domain_safety_check.check_safe_browsing("https://example.com/", "k", 5)
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
