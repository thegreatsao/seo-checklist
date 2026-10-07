"""The pre-push gate, which until 0.104.0 nothing in this tree read at all.

`tools/ci_local.py` is what `.githooks/pre-push` runs, and it decides whether a release
leaves this machine. It arrived at 0.102.0 with no test and no CI step of its own — the
one mechanism in the repository whose failure nobody would learn about from a red build,
because it *is* the build's local stand-in. `openspec/specs/governance/` GOV-3 asks that a
mechanism deciding behaviour be read by something; this is that something.

The defect that prompted it is the one the module's own docstring is proudest of refusing.
`tree_hash()` called `git write-tree`, which hashes the **index**, while its docstring said
"the working tree". With fifteen modified and two new files on disk it returned HEAD's tree,
matched a stamp written in the previous session, and printed *"this exact tree already ran
green here. Nothing changed, so nothing is rerun"* over a release it had never seen.

A push can start mid-edit. GOV-11 now requires the gate to compare disk content with
every sent commit before it starts checking; hand runs still verify the disk.
"""
from __future__ import annotations

import os
import re
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "seo-checklist", "tools"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ci_local  # noqa: E402
from harness import spawn  # noqa: E402
import test_git_worktrees  # noqa: E402


class TheStampNamesTheTreeItVerified(unittest.TestCase):
    """The stamp's whole job is to say *which* tree went green here.

    A hash that answers about a different tree than the one on disk does not make the
    gate slower or noisier — it makes it agree, which is worse than having no gate,
    because the agreement is what somebody pushes on.
    """

    PROBE = os.path.join(ROOT, "tests", "fixtures", "ci-local-probe.tmp")

    def tearDown(self):
        if os.path.exists(self.PROBE):
            os.remove(self.PROBE)

    def test_a_file_on_disk_moves_the_hash_before_it_is_added(self):
        """The regression reader. Under `git write-tree` against the real index this
        assertion fails in both directions at once: the two hashes are equal, because
        neither of them was about the working tree."""
        before = ci_local.tree_hash()
        self.assertTrue(before, "the tree hash could not be taken at all")
        with open(self.PROBE, "w", encoding="utf-8") as stream:
            stream.write("a file the index has never heard of\n")
        during = ci_local.tree_hash()
        os.remove(self.PROBE)
        after = ci_local.tree_hash()

        self.assertNotEqual(
            before, during,
            "an untracked file did not move the tree hash, so ci_local would report a "
            "tree it has not seen as already verified — the failure this gate exists "
            "to refuse, in the gate")
        self.assertEqual(before, after,
                         "the hash did not come back when the file went away, so it is "
                         "measuring something other than the tree's content")

    def test_an_ignored_tracked_file_moves_the_hash(self):
        """GOV-11: the stamp includes every tracked file, even one an ignore matches."""
        with tempfile.TemporaryDirectory(prefix="seo-ignored-tracked-") as directory:
            git = test_git_worktrees.GitOwnsTheCheckoutLocations.run_git
            git(directory, "init")
            tracked = os.path.join(directory, "checklist_runner.py")
            with open(tracked, "w", encoding="utf-8") as stream:
                stream.write("first\n")
            git(directory, "add", "checklist_runner.py")
            with open(os.path.join(directory, ".gitignore"), "w", encoding="utf-8") as stream:
                stream.write("checklist*\n")
            git(directory, "add", ".gitignore")
            git(directory, "-c", "user.name=Gate test", "-c",
                "user.email=gate@example.invalid", "commit", "-m", "ignored tracked file")
            index = os.path.join(ci_local.git_directory(directory), "index")
            with open(index, "rb") as stream:
                original = stream.read()
            with mock.patch.object(ci_local, "ROOT", directory):
                before = ci_local.tree_hash()
                self.assertTrue(before)
                with open(tracked, "w", encoding="utf-8") as stream:
                    stream.write("changed\n")
                after = ci_local.tree_hash()
                self.assertTrue(after)
                self.assertNotEqual(before, after)
                self.assertEqual(before, git(directory, "rev-parse", "HEAD^{tree}"))
            with open(index, "rb") as stream:
                self.assertEqual(stream.read(), original)
            self.assertFalse(os.path.exists(os.path.join(directory, ".git", "ci-local-index")))

    def test_taking_the_hash_does_not_disturb_the_real_index(self):
        """The cost of reading the working tree is a throwaway index, and it has to
        stay throwaway: a gate that stages somebody's work as a side effect of checking
        it would be traded away the first time it surprised them."""
        before = ci_local._run_git(["write-tree"], root=ROOT).stdout.strip()
        ci_local.tree_hash()
        after = ci_local._run_git(["write-tree"], root=ROOT).stdout.strip()
        self.assertEqual(before, after, "the real index moved while the hash was taken")
        self.assertFalse(os.path.exists(os.path.join(
            ci_local.git_directory(ROOT), "ci-local-index")),
                         "the scratch index was left behind")


class TheStepsComeFromTheWorkflow(unittest.TestCase):
    """Read out of `ci.yml`, not a copy of it.

    A local gate holding a transcribed list of CI's steps is a second thing to keep in
    step, and the release it misses is the one where somebody added a step to CI. The
    module's design is to parse the workflow; this is what stops that design being
    quietly replaced by a literal.
    """

    def test_every_job_it_knows_about_is_a_job_the_workflow_declares(self):
        with open(ci_local.WORKFLOW, encoding="utf-8") as stream:
            workflow = stream.read()
        jobs = ci_local.load_jobs()
        self.assertTrue(jobs, "no jobs were read out of the workflow")
        for name in jobs:
            with self.subTest(job=name):
                self.assertIn(f"\n  {name}:", workflow,
                              "a job ci_local believes in and the workflow does not "
                              "declare")

    def test_the_suite_is_among_the_steps_it_runs(self):
        """A floor. Every count this module prints would read as good news if the parse
        quietly stopped finding steps, so the one step whose absence would matter most
        is named."""
        scripts = [step.get("run", "") for job in ci_local.load_jobs().values()
                   for step in job.get("steps", [])]
        self.assertTrue(any("unittest discover" in s for s in scripts),
                        "ci_local would not run the suite; the workflow parse is broken")

    def test_the_suite_runs_on_linux_macos_and_windows(self):
        """Read out of `ci.yml`: where every job that runs the suite runs, a matrix
        leg counted as the runner it names.

        The tool is run on all three, and until 0.151.0 CI ran it on two. The third
        was a person's machine: the first afternoon the suite and the push ran on a
        Mac found a request line, a hook git would not start and a `git fetch` in the
        suite. Equal and not a subset, so a platform dropped or added is a decision
        somebody makes here.
        """
        runners = set()
        for job in ci_local.load_jobs().values():
            if not any("unittest discover" in step.get("run", "")
                       for step in job.get("steps", [])):
                continue
            if "matrix" not in str(job["runs-on"]):
                runners.add(job["runs-on"])
                continue
            matrix = job["strategy"]["matrix"]
            runners.update(matrix.get("os", []))
            runners.update(leg["os"] for leg in matrix.get("include", [])
                           if "os" in leg)
        self.assertEqual(sorted(name.split("-")[0] for name in runners),
                         ["macos", "ubuntu", "windows"],
                         f"the suite runs on {sorted(runners)}")

    def test_the_workflow_parser_is_installed_where_this_module_runs(self):
        """Read out of `ci.yml` rather than discovered by a crash.

        This class parses the workflow, and `ci_local.load_jobs()` does it with PyYAML —
        which is deliberately not in `requirements.txt`, because nothing this tool ships
        reads YAML. So the jobs that run the suite have to install it, and a job that
        stops doing so should say *that* rather than surfacing as a `SystemExit` from a
        helper three files away.
        """
        with open(ci_local.WORKFLOW, encoding="utf-8") as stream:
            lines = [line.rstrip("\n") for line in stream]
        job, running = None, {}
        for line in lines:
            if (line.startswith("  ") and not line.startswith("   ")
                    and line.rstrip().endswith(":")):
                job = line.strip().rstrip(":")
                running[job] = []
            elif job:
                running[job].append(line)
        suite_jobs = {name: body for name, body in running.items()
                      if any("unittest discover" in line for line in body)}
        self.assertTrue(suite_jobs, "no job runs the suite; this read the wrong file")
        for name, body in sorted(suite_jobs.items()):
            with self.subTest(job=name):
                self.assertIn("pip install pyyaml", "\n".join(body),
                              f"the {name} job runs this module and installs no YAML "
                              f"reader, so every test here that parses ci.yml dies in "
                              f"an exit call rather than failing by name")


class ItObeysTheRulesItEnforcesOnEverythingElse(unittest.TestCase):
    """`harness.spawn` exists because a forked child dies on macOS before it execs, and
    `test_runner.AScriptTheOperatingSystemKilled` holds the three rules across
    `scripts/`, `tools/` and `tests/`. This module is in `tools/`, so it is already
    covered there; what is pinned here is the one thing that scan cannot see — that the
    binary it resolves is a real path rather than a name it hopes is on PATH."""

    def test_git_is_resolved_to_a_path(self):
        found = ci_local.resolve("git")
        self.assertTrue(os.path.dirname(found),
                        "a bare name has no dirname, so CPython takes the fork path")
        self.assertTrue(os.path.exists(found), found)

    def test_the_stamp_reader_leaves_a_hooks_repository_behind(self):
        """The reader's two write-tree calls must not write the hook's objects."""
        hook = {"GIT_DIR": "foreign/.git", "GIT_WORK_TREE": "foreign",
                "GIT_INDEX_FILE": "foreign/.git/index", "GIT_COMMON_DIR": "foreign/.git"}
        ci_local.leave_the_hook_behind({})
        with tempfile.TemporaryDirectory(prefix="seo-stamp-reader-") as directory, \
                mock.patch.dict(os.environ, hook), \
                mock.patch.object(ci_local.subprocess, "run") as child, \
                mock.patch.object(ci_local, "tree_hash"), \
                mock.patch.object(ci_local, "git_directory", return_value=directory):
            child.return_value.stdout = "same-tree\n"
            reader = TheStampNamesTheTreeItVerified(
                "test_taking_the_hash_does_not_disturb_the_real_index")
            reader.test_taking_the_hash_does_not_disturb_the_real_index()
            self.assertEqual(child.call_count, 2)
            for call in child.call_args_list:
                environment = call.kwargs.get("env", os.environ)
                self.assertEqual(set(hook).intersection(environment), set())

    def test_the_harness_spawn_this_suite_requires_is_importable_here(self):
        """Named so the import above is not mistaken for an unused one: a test module
        that imports nothing from the harness is a test module somebody will later run
        outside it."""
        self.assertTrue(callable(spawn))


class CIsLegsAreReadOutOfTheWorkflow(unittest.TestCase):
    """`openspec/specs/governance/` INV-G9: the newest Python CI runs the suite on, it
    runs on every platform, and the local gate names the legs it did not run by reading
    them, not by remembering them.

    Until 0.158.0 the newest was 3.13 and the plugin installed on the Mac ran audits on
    3.14, which no leg and no machine had ever run the suite on. And the gate closed
    every run with "the 3.10 and 3.11 matrix legs", a sentence written by hand: on the
    Mac, whose gate ran 3.12, it left 3.13 out, and it would have left 3.14 out too.
    """

    LEGS = [("ubuntu", "3.10"), ("ubuntu", "3.14"), ("macos", "3.14"), ("windows", "3.13")]

    def legs(self):
        return ci_local.suite_legs(ci_local.load_jobs())

    def test_every_python_the_matrix_lists_is_a_leg_on_linux(self):
        """Against the file as text, which is how `TheDeclaredPythonFloorIsExercised`
        reads the same list: two readings of one line have to agree."""
        with open(ci_local.WORKFLOW, encoding="utf-8") as stream:
            listed = re.search(r"python-version: \[([^\]]+)\]", stream.read())
        self.assertEqual([python for runner, python in self.legs() if runner == "ubuntu"],
                         [v.strip().strip('"') for v in listed.group(1).split(",")])

    def test_the_newest_python_is_run_on_every_platform(self):
        """Equal on all three, so a version added to one platform's legs and not to
        the others' is a decision somebody makes here."""
        legs = self.legs()
        newest = max((python for _, python in legs),
                     key=lambda v: tuple(int(part) for part in v.split(".")))
        for runner in ("ubuntu", "macos", "windows"):
            with self.subTest(runner=runner):
                self.assertIn((runner, newest), legs,
                              f"CI runs {newest} and not on {runner}")

    def test_a_run_names_every_leg_but_its_own(self):
        self.assertEqual(
            ci_local.legs_not_run(self.LEGS, "darwin", "3.14"),
            ["  not run: CI's other legs — ubuntu 3.10, 3.14; windows 3.13"])
        self.assertEqual(
            ci_local.legs_not_run(self.LEGS, "linux", "3.10"),
            ["  not run: CI's other legs — ubuntu 3.14; macos 3.14; windows 3.13"])

    def test_a_machine_ci_has_no_leg_for_is_told_so(self):
        """A Mac on 3.12 was where every release was gated, and CI had no such leg."""
        lines = ci_local.legs_not_run(self.LEGS, "darwin", "3.12")
        self.assertEqual(lines[0], "  not run: CI's other legs — ubuntu 3.10, 3.14; "
                                   "macos 3.14; windows 3.13")
        self.assertEqual(len(lines), 2)
        self.assertIn("no macos 3.12 leg", lines[1])

    def test_every_platform_the_gate_can_name_is_one_ci_runs(self):
        """`RUNNER_OF` turns what Python calls this machine into what the workflow
        calls a runner. A name in it that no leg has would make every run on that
        platform say CI has no leg for it."""
        self.assertEqual(sorted(set(ci_local.RUNNER_OF.values())),
                         sorted({runner for runner, _ in self.legs()}))

    def test_the_gate_closes_with_what_it_read(self):
        with open(os.path.join(ROOT, "skills", "seo-checklist", "tools", "ci_local.py"),
                  encoding="utf-8") as stream:
            source = stream.read()
        self.assertIn("legs_not_run(suite_legs(jobs), sys.platform,", source)
        self.assertNotIn("matrix legs, and every platform but this one", source)


if __name__ == "__main__":
    unittest.main()
