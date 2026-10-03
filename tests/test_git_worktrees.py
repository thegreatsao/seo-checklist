"""Git owns the locations of a checkout's history and private gate files."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "seo-checklist" / "tools"))
sys.path.insert(0, str(ROOT / "tests"))

import audit_declaration_revisions as revisions
import git_checkout
import id_history
from harness import spawn


def harness_environment() -> dict:
    return dict(os.environ)


class TheGateLeavesTheHookBehind(unittest.TestCase):
    """git aims a hook at its repository through the environment, and the gate runs
    the whole suite from inside one."""

    def test_what_git_sets_for_a_hook_is_removed_and_nothing_else(self):
        environment = {"GIT_DIR": "somewhere/.git", "GIT_WORK_TREE": "somewhere",
                       "GIT_INDEX_FILE": "somewhere/.git/index", "GIT_PREFIX": "",
                       "GIT_COMMON_DIR": "elsewhere/.git",
                       "GIT_AUTHOR_NAME": "kept: it aims git at nothing",
                       "PATH": os.environ.get("PATH", "")}
        removed = git_checkout.leave_the_hook_behind(environment)
        self.assertEqual(sorted(removed), ["GIT_COMMON_DIR", "GIT_DIR", "GIT_INDEX_FILE",
                                           "GIT_PREFIX", "GIT_WORK_TREE"])
        self.assertEqual(sorted(environment), ["GIT_AUTHOR_NAME", "PATH"])

    def test_a_git_that_does_not_answer_is_not_an_empty_list(self):
        with mock.patch.object(git_checkout.subprocess, "run", side_effect=OSError("probe")):
            with self.assertRaisesRegex(git_checkout.Unreadable, "git would not run"):
                git_checkout.leave_the_hook_behind({"GIT_DIR": "x"})

    def test_a_failed_or_empty_git_answer_is_not_an_empty_list(self):
        """Neither a failed command nor an empty success proves cleanup is safe."""
        for returncode, stdout in ((1, "GIT_DIR\n"), (0, ""), (0, " \n")):
            with self.subTest(returncode=returncode, stdout=stdout):
                answer = mock.Mock(returncode=returncode, stdout=stdout, stderr="probe")
                environment = {"GIT_DIR": "x"}
                with mock.patch.object(git_checkout.subprocess, "run", return_value=answer):
                    with self.assertRaisesRegex(git_checkout.Unreadable,
                                                "git did not say which variables"):
                        git_checkout.leave_the_hook_behind(environment)
                self.assertEqual(environment, {"GIT_DIR": "x"})

    def test_the_gate_does_it_before_it_starts_anything(self):
        """Read off the gate's own source: the call is in `main`, and no process is
        started and no step environment built above it."""
        source = (ROOT / "skills" / "seo-checklist" / "tools" / "ci_local.py").read_text(
            encoding="utf-8")
        body = source[source.index("def main() -> int:"):]
        call = body.index("leave_the_hook_behind(os.environ)")
        for later in ("load_workflow()", "tree_hash()", "dict(os.environ", "run_step("):
            with self.subTest(later=later):
                self.assertGreater(body.index(later), call)

    def test_under_a_hooks_environment_a_command_reaches_the_directory_it_names(self):
        """The incident, in a temp directory: two repositories, `GIT_DIR` naming the
        first, a commit meant for the second."""
        with tempfile.TemporaryDirectory(prefix="seo-git-hook-") as base:
            pushed, meant = Path(base, "pushed"), Path(base, "meant")
            for repository in (pushed, meant):
                repository.mkdir()
                GitOwnsTheCheckoutLocations.run_git(repository, "init")
            hooked = dict(os.environ, GIT_DIR=str(pushed / ".git"))
            with mock.patch.dict(os.environ, hooked):
                (meant / "note.txt").write_text("for the second\n", encoding="utf-8")
                GitOwnsTheCheckoutLocations.run_git(meant, "add", "note.txt")
                GitOwnsTheCheckoutLocations.run_git(
                    meant, "-c", "user.name=Hook test",
                    "-c", "user.email=hook@example.invalid", "commit", "-m", "meant")
            self.assertEqual(
                GitOwnsTheCheckoutLocations.run_git(meant, "log", "--format=%s"), "meant")
            self.assertEqual(
                GitOwnsTheCheckoutLocations.run_git(pushed, "rev-list", "--all", "--count"),
                "0", "the repository the hook was aimed at took a commit meant for another")


class GitOwnsTheCheckoutLocations(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="seo-git-worktrees-")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.base = Path(cls.temp.name)
        cls.checkout = cls.base / "checkout"
        cls.linked = cls.base / "linked"
        cls.plain = cls.base / "plain"
        cls.checkout.mkdir()
        cls.plain.mkdir()
        cls.run_git(cls.checkout, "init")
        (cls.checkout / "tracked.txt").write_text("first\n", encoding="utf-8")
        cls.run_git(cls.checkout, "add", "tracked.txt")
        cls.run_git(cls.checkout, "-c", "user.name=Worktree test",
                    "-c", "user.email=worktree@example.invalid", "commit", "-m", "first")
        cls.first = cls.run_git(cls.checkout, "rev-parse", "HEAD")
        cls.run_git(cls.checkout, "worktree", "add", "-b", "linked", str(cls.linked))
        (cls.checkout / "tracked.txt").write_text("second\n", encoding="utf-8")
        cls.run_git(cls.checkout, "add", "tracked.txt")
        cls.run_git(cls.checkout, "-c", "user.name=Worktree test",
                    "-c", "user.email=worktree@example.invalid", "commit", "-m", "second")
        cls.shallow = cls.base / "shallow"
        cls.run_git(cls.base, "clone", "--depth=1", cls.checkout.as_uri(), str(cls.shallow))

    @staticmethod
    def run_git(root, *args):
        # These commands build and change a repository. They must reach the one in
        # the temp directory and no other, whatever this suite was started from: a
        # hook's `GIT_DIR` outranks `-C`, and once sent every one of them to the
        # repository being pushed.
        environment = harness_environment()
        git_checkout.leave_the_hook_behind(environment)
        done = spawn(["git", "-C", str(root), *args], env=environment)
        if done.returncode:
            raise AssertionError(done.stdout + done.stderr)
        return done.stdout.strip()

    def git_dir_reported(self, root):
        printed = self.run_git(root, "rev-parse", "--git-dir")
        return os.path.abspath(os.path.join(root, printed))

    def test_checkout_and_linked_worktree_and_their_subdirectories(self):
        for root in (self.checkout, self.linked):
            subdir = root / "subdirectory"
            subdir.mkdir(exist_ok=True)
            for location in (root, subdir):
                with self.subTest(location=location):
                    self.assertEqual(revisions.git_directory(str(location)),
                                     self.git_dir_reported(location))
        self.assertNotEqual(revisions.git_directory(str(self.checkout)),
                            revisions.git_directory(str(self.linked)))

    def test_a_plain_directory_is_refused_by_name(self):
        with self.assertRaisesRegex(revisions.Unreadable, "is not a git checkout"):
            revisions.git_directory(str(self.plain))
        with mock.patch.object(revisions, "ROOT", str(self.plain)):
            with self.assertRaisesRegex(revisions.Unreadable, "is not a git checkout"):
                revisions.epoch_is_reachable()
        with mock.patch.object(id_history, "ROOT", str(self.plain)):
            with self.assertRaisesRegex(revisions.Unreadable, "is not a git checkout"):
                id_history.first_is_reachable()

    def test_a_bare_repository_is_refused_as_not_a_work_tree(self):
        bare = self.base / "bare"
        bare.mkdir()
        self.run_git(bare, "init", "--bare")
        with self.assertRaisesRegex(revisions.Unreadable, "is not a git checkout"):
            revisions.git_directory(str(bare))

    def test_missing_git_and_a_git_that_will_not_run_fail_by_name(self):
        with mock.patch.object(git_checkout.shutil, "which", return_value=None):
            with self.assertRaisesRegex(revisions.Unreadable, "git is not on PATH"):
                revisions.git_directory(str(self.checkout))
        with mock.patch.object(git_checkout.subprocess, "run", side_effect=OSError("probe")):
            with self.assertRaisesRegex(revisions.Unreadable, "git would not run: probe"):
                revisions.git_directory(str(self.checkout))
        for gate in (revisions.epoch_is_reachable, id_history.first_is_reachable):
            with self.subTest(gate=gate.__name__):
                with mock.patch.object(git_checkout.shutil, "which", return_value=None):
                    with self.assertRaisesRegex(revisions.Unreadable, "git is not on PATH"):
                        gate()

    def test_real_shallow_clone_keeps_both_named_refusals(self):
        self.assertEqual(self.run_git(self.shallow, "rev-parse", "--is-shallow-repository"),
                         "true")
        with mock.patch.object(revisions, "ROOT", str(self.shallow)), \
                mock.patch.object(revisions, "EPOCH", self.first):
            with self.assertRaisesRegex(revisions.Unreadable, "fetch-depth: 0"):
                revisions.epoch_is_reachable()
        with mock.patch.object(revisions, "ROOT", str(self.shallow)), \
                mock.patch.object(id_history, "ROOT", str(self.shallow)), \
                mock.patch.object(id_history, "FIRST", self.first):
            with self.assertRaisesRegex(revisions.Unreadable, "fetch-depth: 0"):
                id_history.first_is_reachable()

    def test_the_hook_finds_the_interpreter_of_the_checkout_a_worktree_came_from(self):
        """The hook's own lines, up to the one that starts the gate, run where a push
        would run them. A linked worktree is added with no `.venv`; the main checkout —
        the one holding the repository's `.git` directory — has the one the suite was
        installed into, and a worktree given a `.venv` of its own uses that."""
        hook = (ROOT / ".githooks" / "pre-push").read_text(encoding="utf-8")
        resolution, announced, _rest = hook.rpartition('echo "pre-push:')
        self.assertTrue(announced, "the hook no longer announces itself where it did")
        bash = shutil.which("bash")
        self.assertTrue(bash, "bash is not on PATH, and the hook is written for it")

        def interpreter(where: Path) -> str:
            script = f"cd '{where.as_posix()}'\n{resolution}printf '%s' \"$py\"\n"
            done = spawn([bash, "-c", script])
            self.assertEqual(done.returncode, 0, done.stderr)
            return os.path.normcase(os.path.realpath(done.stdout.strip()))

        def install(where: Path) -> str:
            # Both layouts, as the hook tries both; the first it finds is the answer.
            for relative in (("Scripts", "python.exe"), ("bin", "python")):
                target = where.joinpath(".venv", *relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("#!/bin/sh\n", encoding="utf-8")
                target.chmod(0o755)
            return os.path.normcase(os.path.realpath(where / ".venv"))

        try:
            mine = install(self.checkout)
            self.assertTrue(interpreter(self.checkout).startswith(mine + os.sep))
            self.assertTrue(interpreter(self.linked).startswith(mine + os.sep),
                            "a push from a linked worktree did not find the checkout's "
                            "interpreter")
            own = install(self.linked)
            self.assertTrue(interpreter(self.linked).startswith(own + os.sep),
                            "a worktree with a virtualenv of its own did not use it")
        finally:
            shutil.rmtree(self.checkout / ".venv", ignore_errors=True)
            shutil.rmtree(self.linked / ".venv", ignore_errors=True)

    def test_the_gate_does_not_load_the_suites_harness(self):
        """`ci_local` hands its own environment to the step that runs the suite.
        `tests/harness.py` puts the network tripwire on `PYTHONPATH` so that every child
        of a *test* is ended when it reaches out; loaded into the gate, it would be
        handed to the suite itself, whose process would then be ended by the test that
        proves the tripwire raises there. It was, on the first push from a worktree to
        get as far as the suite."""
        tools = ROOT / "skills" / "seo-checklist" / "tools"
        child = spawn([sys.executable, "-c",
                       "import sys; sys.path.insert(0, sys.argv[1]); import ci_local; "
                       "print(sorted(name for name in sys.modules "
                       "if name in ('harness', 'audit_declaration_revisions')))",
                       str(tools)])
        self.assertEqual(child.returncode, 0, child.stderr)
        self.assertEqual(child.stdout.strip(), "[]")

    def test_reading_the_gate_starts_no_process_and_no_checkout_is_no_hash(self):
        """The module is imported by tests and by the hook; where there is no checkout
        around it, importing must still work and the hash is simply not taken."""
        tool = self.plain / "skills" / "seo-checklist" / "tools" / "ci_local.py"
        tool.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / "skills" / "seo-checklist" / "tools" / "ci_local.py", tool)
        spec = importlib.util.spec_from_file_location("ci_local_without_a_checkout", tool)
        ci = importlib.util.module_from_spec(spec)
        with mock.patch.object(git_checkout.subprocess, "run",
                               side_effect=AssertionError("import ran a process")):
            spec.loader.exec_module(ci)
        self.assertIsNone(ci.tree_hash())
        with self.assertRaisesRegex(revisions.Unreadable, "is not a git checkout"):
            ci.stamp_path()

    def test_ci_stamp_and_scratch_use_the_reported_git_directory(self):
        for root in (self.checkout, self.linked):
            with self.subTest(root=root):
                tool = root / "skills" / "seo-checklist" / "tools" / "ci_local.py"
                tool.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / "skills" / "seo-checklist" / "tools" / "ci_local.py",
                                tool)
                spec = importlib.util.spec_from_file_location("temporary_ci_local", tool)
                ci = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(ci)
                expected = self.git_dir_reported(root)
                self.assertEqual(ci.stamp_path(), os.path.join(expected, "ci-local-verified"))
                Path(ci.stamp_path()).write_text("verified here\n", encoding="utf-8")
                self.assertEqual(Path(ci.stamp_path()).read_text(encoding="utf-8"), "verified here\n")
                before_index = self.run_git(root, "write-tree")
                scratch = os.path.join(expected, "ci-local-index")
                real_run = ci.subprocess.run
                with mock.patch.object(ci.subprocess, "run", wraps=real_run) as calls:
                    before = ci.tree_hash()
                self.assertTrue(before, "the temporary checkout's hash could not be taken")
                used = [call.kwargs["env"]["GIT_INDEX_FILE"]
                        for call in calls.call_args_list
                        if "GIT_INDEX_FILE" in call.kwargs.get("env", {})]
                self.assertEqual(used, [scratch, scratch])
                self.assertFalse(os.path.exists(scratch), "the scratch index was left behind")
                probe = root / "untracked.txt"
                probe.write_text("not added\n", encoding="utf-8")
                try:
                    self.assertNotEqual(ci.tree_hash(), before)
                finally:
                    probe.unlink()
                self.assertEqual(ci.tree_hash(), before)
                self.assertEqual(self.run_git(root, "write-tree"), before_index)
                self.assertFalse(os.path.exists(scratch), "the scratch index was left behind")

    def test_the_hash_leaves_a_hooks_repository_and_index_behind(self):
        """A caller can ask for a hash without having entered the gate's main."""
        import ci_local

        pushed = self.base / "hash-hook-pushed"
        pushed.mkdir()
        self.run_git(pushed, "init")
        (pushed / "foreign.txt").write_text("belongs to the hook\n", encoding="utf-8")
        with mock.patch.object(ci_local, "ROOT", str(self.checkout)):
            expected = ci_local.tree_hash()
            self.assertTrue(expected)
            before = {p.relative_to(pushed): p.read_bytes()
                      for p in (pushed / ".git").rglob("*") if p.is_file()}
            hook = {"GIT_DIR": str(pushed / ".git"), "GIT_WORK_TREE": str(pushed),
                    "GIT_COMMON_DIR": str(pushed / ".git"),
                    "GIT_INDEX_FILE": str(pushed / ".git" / "index")}
            for environment in ({"GIT_DIR": hook["GIT_DIR"]}, hook):
                with self.subTest(variables=sorted(environment)):
                    with mock.patch.dict(os.environ, environment):
                        observed = ci_local.tree_hash()
                        self.assertEqual(observed, expected,
                                         "the hash answered about the hook's repository")
                        self.assertEqual({k: os.environ[k] for k in environment}, environment,
                                         "hashing changed the caller's environment")
                    after = {p.relative_to(pushed): p.read_bytes()
                             for p in (pushed / ".git").rglob("*") if p.is_file()}
                    self.assertEqual(after, before, "hashing wrote into the hook's repository")


if __name__ == "__main__":
    unittest.main()
