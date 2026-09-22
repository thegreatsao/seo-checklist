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

It survived a release because the hook's own moment is the one moment the two agree: at
`git push` everything is committed, so index and working tree are the same tree and the
answer is right. Every hand run mid-edit — which the README documents — was answering
about the last commit.
"""
from __future__ import annotations

import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "seo-checklist", "tools"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ci_local  # noqa: E402
from harness import spawn  # noqa: E402


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

    def test_taking_the_hash_does_not_disturb_the_real_index(self):
        """The cost of reading the working tree is a throwaway index, and it has to
        stay throwaway: a gate that stages somebody's work as a side effect of checking
        it would be traded away the first time it surprised them."""
        before = subprocess.run(
            [ci_local.resolve("git"), "-C", ROOT, "write-tree"],
            capture_output=True, text=True, close_fds=False).stdout.strip()
        ci_local.tree_hash()
        after = subprocess.run(
            [ci_local.resolve("git"), "-C", ROOT, "write-tree"],
            capture_output=True, text=True, close_fds=False).stdout.strip()
        self.assertEqual(before, after, "the real index moved while the hash was taken")
        self.assertFalse(os.path.exists(os.path.join(ROOT, ".git", "ci-local-index")),
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

    def test_the_harness_spawn_this_suite_requires_is_importable_here(self):
        """Named so the import above is not mistaken for an unused one: a test module
        that imports nothing from the harness is a test module somebody will later run
        outside it."""
        self.assertTrue(callable(spawn))


if __name__ == "__main__":
    unittest.main()
