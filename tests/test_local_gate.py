"""GOV-11: the gate verifies pushed content and Git reaches its named directory."""
from __future__ import annotations

import ast
from concurrent.futures import ThreadPoolExecutor
import contextlib
import functools
import io
import os
import re
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'skills/seo-checklist/tools'))
sys.path.insert(0, str(ROOT / 'tests'))

import ci_local
import git_checkout
import notebook_sync
from harness import spawn
import test_git_worktrees


def git_launches():
    """GOV-11: derive Git launches from process arguments, including wrapper callers."""
    found = []
    for folder in ('skills/seo-checklist/tools', 'tests'):
        for path in sorted((ROOT / folder).rglob('*.py')):
            tree = ast.parse(path.read_text(encoding='utf-8-sig'))
            parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
            bindings = {}
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            bindings.setdefault(target.id, []).append(node.value)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not node.args:
                    continue
                name = ast.unparse(node.func)
                if name not in ('subprocess.run', 'subprocess.Popen', 'spawn', 'harness.spawn',
                                'run', 'os.system', 'os.popen'):
                    continue
                args = node.args[0]
                program = args.elts[0] if isinstance(args, (ast.List, ast.Tuple)) and args.elts else args
                pending, seen, starts_git = [program], set(), False
                while pending:
                    program = pending.pop()
                    text = ast.unparse(program)
                    if isinstance(program, ast.Name) and program.id not in seen:
                        seen.add(program.id)
                        pending.extend(bindings.get(program.id, []))
                    elif isinstance(program, (ast.List, ast.Tuple)) and program.elts:
                        pending.append(program.elts[0])
                    elif (text in ("'git'", '"git"') or '_git_binary()' in text
                          or re.search(r"(?:resolve|which)\(['\"]git['\"]\)", text)
                          or (isinstance(program, ast.Constant) and isinstance(program.value, str)
                              and (program.value.replace('\\', '/').rsplit('/', 1)[-1] == 'git.exe'
                                   or re.search(r'\bgit\s', program.value)))):
                        starts_git = True
                if not starts_git:
                    continue
                owner = node
                while owner in parents and not isinstance(owner, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    owner = parents[owner]
                found.append((path.relative_to(ROOT).as_posix(), getattr(owner, 'name', '<module>'),
                              node.lineno, ast.unparse(node)))
    for path in sorted((ROOT / '.githooks').rglob('*')):
        if path.is_file():
            for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
                if not line.lstrip().startswith('#'):
                    for command in re.findall(r'\$\((git [^)]*)\)', line):
                        found.append((path.relative_to(ROOT).as_posix(), command, number, line))
    return found


class TheGateVerifiesWhatLeaves(unittest.TestCase):
    """GOV-11: every requested ref must match the disk before a step runs."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='seo-pushed-')
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        self.git('init')
        (self.repo / 'tracked.txt').write_text('first\n', encoding='utf-8')
        (self.repo / '.gitignore').write_text('ignored.txt\n', encoding='utf-8')
        self.git('add', '.')
        self.git('-c', 'user.name=Gate test', '-c', 'user.email=gate@example.invalid',
                 'commit', '-m', 'first')
        self.head = self.git('rev-parse', 'HEAD')

    def git(self, *args):
        return test_git_worktrees.GitOwnsTheCheckoutLocations.run_git(self.repo, *args)

    def gate(self, sha, ref='refs/heads/release', *, payload=None, pushed=True, hash_value=None):
        with mock.patch.object(ci_local, 'ROOT', str(self.repo)), \
                mock.patch.object(sys, 'argv', ['ci_local.py', *(['--pushed'] if pushed else [])]), \
                mock.patch.object(sys, 'stdin', io.StringIO(
                    f'{ref} {sha} {ref} {"0" * 40}\n' if payload is None else payload)), \
                mock.patch.object(ci_local, 'load_workflow', return_value={
                    'jobs': {'test': {'steps': [{'name': 'witness', 'run': 'witness'}]},
                             'census': {'steps': []}}}), \
                mock.patch.object(ci_local, 'tree_hash', return_value=hash_value), \
                mock.patch.object(ci_local, 'sweep', return_value=[]), \
                mock.patch.object(ci_local, 'run_step', return_value=(True, 0, '')) as step, \
                contextlib.redirect_stdout(io.StringIO()) as output:
            result = ci_local.main()
        return result, step.call_count, output.getvalue()

    def test_deletion_only_runs_no_step(self):
        """GOV-11: a deletion sends no commit and asks for no verification."""
        result, steps, output = self.gate('0' * 40)
        self.assertEqual((result, steps), (0, 0))
        self.assertIn('no commit', output)
        self.assertEqual(len(output.splitlines()), 1)

    def test_clean_head_runs_the_step(self):
        """GOV-11: a clean disk matching the sent HEAD is gated."""
        self.assertEqual(self.gate(self.head)[:2], (0, 1))

    def test_modified_tracked_file_refuses_before_steps(self):
        """GOV-11: unstaged content is not the commit being sent."""
        (self.repo / 'tracked.txt').write_text('modified\n', encoding='utf-8')
        result, steps, output = self.gate(self.head)
        self.assertEqual((result, steps), (1, 0))
        self.assertIn('refs/heads/release', output)
        self.assertIn('tracked', output)
        self.assertIn('commit or stash', output.lower())

    def test_untracked_file_refuses_before_steps(self):
        """GOV-11: an unadded module cannot make the pushed commit pass."""
        (self.repo / 'new.py').write_text('new\n', encoding='utf-8')
        result, steps, output = self.gate(self.head)
        self.assertEqual((result, steps), (1, 0))
        self.assertIn('refs/heads/release', output)
        self.assertIn('untracked', output)
        self.assertIn('commit or stash', output.lower())

    def test_ignored_file_passes(self):
        """GOV-11: ignored debris is outside the verified Git content."""
        (self.repo / 'ignored.txt').write_text('ignored\n', encoding='utf-8')
        self.assertEqual(self.gate(self.head)[:2], (0, 1))

    def test_another_ref_with_other_content_refuses(self):
        """GOV-11: comparison is with the sent SHA, not the checked-out HEAD."""
        tree = self.git('mktree')
        other = self.git('-c', 'user.name=Gate test', '-c', 'user.email=gate@example.invalid',
                         'commit-tree', tree, '-m', 'other')
        self.git('update-ref', 'refs/heads/other', other)
        result, steps, output = self.gate(other, 'refs/heads/other')
        self.assertEqual((result, steps), (1, 0))
        self.assertIn('refs/heads/other', output)
        self.assertIn('check out', output)

    def test_another_ref_with_same_content_passes(self):
        """GOV-11: matching content passes whatever branch is checked out."""
        tree = self.git('rev-parse', 'HEAD^{tree}')
        other = self.git('-c', 'user.name=Gate test', '-c', 'user.email=gate@example.invalid',
                         'commit-tree', tree, '-p', self.head, '-m', 'same content')
        self.git('update-ref', 'refs/heads/same', other)
        self.assertNotEqual(other, self.head)
        self.assertEqual(self.gate(other, 'refs/heads/same')[:2], (0, 1))

    def test_annotated_tag_is_read_as_its_commit(self):
        """GOV-11: the sent object for an annotated tag is peeled to a commit."""
        self.git('-c', 'user.name=Gate test', '-c', 'user.email=gate@example.invalid',
                 'tag', '-a', 'release', '-m', 'release')
        tag = self.git('rev-parse', 'release')
        self.assertNotEqual(tag, self.head)
        self.assertEqual(self.gate(tag, 'refs/tags/release')[:2], (0, 1))

    def test_every_ref_is_checked_before_any_step(self):
        """GOV-11: a deletion and a matching ref cannot hide a later mismatched ref."""
        other = self.git('-c', 'user.name=Gate test', '-c', 'user.email=gate@example.invalid',
                         'commit-tree', self.git('mktree'), '-m', 'other')
        payload = (f'refs/heads/deleted {"0" * 40} refs/heads/deleted {self.head}\n'
                   f'refs/heads/clean {self.head} refs/heads/clean {"0" * 40}\n'
                   f'refs/heads/other {other} refs/heads/other {"0" * 40}\n')
        result, steps, output = self.gate(self.head, payload=payload)
        self.assertEqual((result, steps), (1, 0))
        self.assertIn('refs/heads/other', output)

    def test_hand_run_still_verifies_uncommitted_disk(self):
        """GOV-11: without --pushed the existing disk-checking path remains available."""
        (self.repo / 'tracked.txt').write_text('editing\n', encoding='utf-8')
        (self.repo / 'new.py').write_text('not added\n', encoding='utf-8')
        self.assertEqual(self.gate(self.head, pushed=False)[:2], (0, 1))

    def test_pushed_cache_names_ignored_tracked_content(self):
        """GOV-11: an ignored tracked edit cannot borrow another commit's green stamp."""
        (self.repo / '.gitignore').write_text('tracked.txt\nignored.txt\n', encoding='utf-8')
        self.git('add', '.gitignore')
        self.git('-c', 'user.name=Gate test', '-c', 'user.email=gate@example.invalid',
                 'commit', '-m', 'ignore a tracked file')
        before = self.git('rev-parse', 'HEAD')
        with mock.patch.object(ci_local, 'ROOT', str(self.repo)):
            fingerprint = ci_local.tree_hash()
        self.assertTrue(fingerprint)
        self.assertEqual(self.gate(before, hash_value=fingerprint)[:2], (0, 1))
        (self.repo / 'tracked.txt').write_text('changed ignored tracked content\n', encoding='utf-8')
        self.git('add', '-u')
        self.git('-c', 'user.name=Gate test', '-c', 'user.email=gate@example.invalid',
                 'commit', '-m', 'different pushed content')
        after = self.git('rev-parse', 'HEAD')
        with mock.patch.object(ci_local, 'ROOT', str(self.repo)):
            changed = ci_local.tree_hash()
        self.assertNotEqual(changed, fingerprint)
        self.assertEqual(self.gate(after, hash_value=changed)[:2], (0, 1))
        self.assertEqual(self.gate(after, hash_value=changed)[:2], (0, 0))

    def test_hook_passes_flag_and_stdin_to_the_gate(self):
        """GOV-11: execute the hook's launch line with a harmless receiving program."""
        hook = (ROOT / '.githooks/pre-push').read_text(encoding='utf-8')
        line = hook.splitlines()[-1]
        target = self.repo / 'skills/seo-checklist/tools/ci_local.py'
        target.parent.mkdir(parents=True)
        target.write_text('import sys\nprint(sys.argv[1:])\nprint(sys.stdin.read(), end="")\n',
                          encoding='utf-8')
        payload = f'refs/heads/release {self.head} refs/heads/release {"0" * 40}\n'
        done = spawn([ci_local.resolve('bash'), '-c', line], stdin_text=payload,
                     env=dict(os.environ, py=sys.executable, root=self.repo.as_posix()))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout, "['--pushed']\n" + payload)


class EveryGitReachesItsDirectory(unittest.TestCase):
    """GOV-11: cleanup belongs to the launcher, with deliberate environments preserved."""

    def test_git_neither_waits_on_nor_consumes_the_callers_stdin(self):
        """GOV-11: mktree gets EOF while the caller keeps its own input pipe open."""
        with tempfile.TemporaryDirectory(prefix='seo-git-stdin-') as base:
            self.assertEqual(git_checkout._run_git(['init'], root=base).returncode, 0)
            ready = Path(base, 'ready')
            script = '''import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import git_checkout
try:
    done = git_checkout._run_git(['mktree'], root=sys.argv[2], timeout=2)
finally:
    Path(sys.argv[3]).touch()
assert done.returncode == 0, done.stderr
print(done.stdout.strip())
print(sys.stdin.buffer.readline().decode().strip())
'''
            read_fd, write_fd = os.pipe()
            with os.fdopen(read_fd, 'rb') as reader, os.fdopen(write_fd, 'wb', buffering=0) as writer, \
                    mock.patch.object(git_checkout.subprocess, 'run',
                                      functools.partial(git_checkout.subprocess.run, stdin=reader)), \
                    ThreadPoolExecutor(max_workers=1) as worker:
                child = worker.submit(spawn, [sys.executable, '-c', script,
                                             str(ROOT / 'skills/seo-checklist/tools'), base,
                                             str(ready)], timeout=15)
                deadline = time.monotonic() + 10
                while not ready.exists() and not child.done() and time.monotonic() < deadline:
                    time.sleep(0.01)
                writer.write(b'refs still belong to the caller\n')
                done = child.result(timeout=20)
            self.assertTrue(ready.exists(), 'the launcher did not finish with an open input pipe')
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(done.stdout.splitlines(),
                             ['4b825dc642cb6eb9a060e54bf8d69288fbee4904',
                              'refs still belong to the caller'])

    def test_every_git_launch_is_the_launcher_or_a_justified_exception(self):
        """GOV-11: derive operations and compare exceptions in both directions."""
        exceptions = {
            ('skills/seo-checklist/tools/git_checkout.py', 'leave_the_hook_behind'):
                'asks the repository-independent Git variable vocabulary; cannot recurse into cleanup',
            ('.githooks/pre-push', 'git rev-parse --show-toplevel'):
                'must read the repository Git selected for this push',
            ('.githooks/pre-push', 'git rev-parse --path-format=absolute --git-common-dir'):
                'must find the interpreter for the repository being pushed',
        }
        launches = git_launches()
        keys = {(path, owner) for path, owner, _line, _operation in launches}
        launcher = ('skills/seo-checklist/tools/git_checkout.py', '_run_git')
        self.assertIn(launcher, keys)
        self.assertEqual(keys - {launcher} - exceptions.keys(), set(), launches)
        self.assertEqual(exceptions.keys() - keys, set(), 'an exception no longer starts Git')
        self.assertTrue(all(exceptions.values()), 'every exception needs an argument')
        vocabulary = [ast.parse(operation, mode='eval').body.args[0].elts[1:]
                      for path, owner, _line, operation in launches
                      if (path, owner) == ('skills/seo-checklist/tools/git_checkout.py', 'leave_the_hook_behind')]
        self.assertEqual([[arg.value for arg in args] for args in vocabulary],
                         [['rev-parse', '--local-env-vars']], 'only the vocabulary query is exempt')

    def test_each_read_kind_ignores_a_foreign_hooks_repository(self):
        """GOV-11: git(), git_directory and notebook state reach the given temp checkout."""
        with tempfile.TemporaryDirectory(prefix='seo-git-reads-') as base:
            meant, foreign = Path(base, 'meant'), Path(base, 'foreign')
            for repo, text in ((meant, 'meant'), (foreign, 'foreign')):
                repo.mkdir()
                test_git_worktrees.GitOwnsTheCheckoutLocations.run_git(repo, 'init')
                (repo / 'note.txt').write_text(text, encoding='utf-8')
                test_git_worktrees.GitOwnsTheCheckoutLocations.run_git(repo, 'add', '.')
                test_git_worktrees.GitOwnsTheCheckoutLocations.run_git(
                    repo, '-c', 'user.name=Gate test', '-c', 'user.email=gate@example.invalid',
                    'commit', '-m', text)
            # A local remote makes the real fetch offline and gives the state read an upstream.
            test_git_worktrees.GitOwnsTheCheckoutLocations.run_git(meant, 'remote', 'add', 'local', str(meant))
            test_git_worktrees.GitOwnsTheCheckoutLocations.run_git(meant, 'fetch', '--quiet')
            branch = git_checkout.git('branch', '--show-current', root=str(meant)).strip()
            test_git_worktrees.GitOwnsTheCheckoutLocations.run_git(meant, 'branch', '--set-upstream-to', f'local/{branch}')
            head = git_checkout.git('rev-parse', '--short', 'HEAD', root=str(meant)).strip()
            hook = {'GIT_DIR': str(foreign / '.git'), 'GIT_WORK_TREE': str(foreign),
                    'GIT_INDEX_FILE': str(foreign / '.git/index'), 'GIT_COMMON_DIR': str(foreign / '.git')}
            before = {p.relative_to(foreign): p.read_bytes() for p in foreign.rglob('*') if p.is_file()}
            with mock.patch.dict(os.environ, hook):
                self.assertEqual(git_checkout.git('log', '-1', '--format=%s', root=str(meant)).strip(), 'meant')
                self.assertEqual(git_checkout.git_directory(str(meant)), str(meant / '.git'))
                self.assertEqual(notebook_sync.git_state(meant), (head, '0'))
                self.assertEqual({k: os.environ[k] for k in hook}, hook)
            self.assertEqual({p.relative_to(foreign): p.read_bytes() for p in foreign.rglob('*') if p.is_file()}, before)

    def test_an_explicit_environment_is_used_exactly_as_given(self):
        """GOV-11: the throwaway index is intentional, not a hook override to remove."""
        git_checkout.leave_the_hook_behind({})
        env = {'GIT_INDEX_FILE': 'intentional-index', 'GIT_DIR': 'intentional-directory'}
        with mock.patch.object(git_checkout.subprocess, 'run') as launch:
            git_checkout._run_git(['write-tree'], root=str(ROOT), env=env)
        self.assertIs(launch.call_args.kwargs['env'], env)
        self.assertEqual(env, {'GIT_INDEX_FILE': 'intentional-index', 'GIT_DIR': 'intentional-directory'})

    def test_git_names_are_asked_once_per_process(self):
        """GOV-11: repeated launches reuse Git's vocabulary without caching the environment."""
        with mock.patch.object(git_checkout.leave_the_hook_behind, '_names', None, create=True), \
                mock.patch.object(git_checkout.subprocess, 'run', return_value=mock.Mock(
                    returncode=0, stdout='GIT_DIR\n', stderr='')) as launch:
            for _ in range(3):
                env = {'GIT_DIR': 'hook', 'PATH': 'kept'}
                git_checkout.leave_the_hook_behind(env)
                self.assertEqual(env, {'PATH': 'kept'})
            self.assertEqual(launch.call_count, 1)
            self.assertEqual(launch.call_args.kwargs['stdin'], git_checkout.subprocess.DEVNULL)


if __name__ == '__main__':
    unittest.main()
