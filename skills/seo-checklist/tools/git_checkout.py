"""Ask git about the checkout this tree is in, with nothing of the suite loaded.

Two history gates (`audit_declaration_revisions.py`, `tests/id_history.py`) and the local
push gate (`ci_local.py`) all need the same three answers: is there a repository around
this tree, where does git keep this working tree's private files, and what does a `git`
command print. They are here, apart from the gates, for one reason: `ci_local.py` runs the
suite as a child and hands it its own environment, and a module that imports
`tests/harness.py` has by then put the suite's network tripwire on `PYTHONPATH`. The gate
that imported its helpers from such a module ended the suite's own process at the test
that proves the tripwire raises — found by the first push from a worktree to get as far
as the suite.

In a linked worktree `.git` is a file naming the real directory, so none of these answers
may be read off the filesystem.
"""
from __future__ import annotations

import os
import shutil
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))


class Unreadable(Exception):
    """History could not be read. Never downgraded to a skip — see the module docstring."""



def _git_binary() -> str:
    """`git`, resolved to a path, because a bare name on PATH forks.

    The three rules `test_runner.AScriptTheOperatingSystemKilled` holds, and this
    module broke two of them on its first run: CPython needs a non-empty dirname or it
    takes the fork path, which macOS kills inside Apple's atfork handler before the
    exec. `close_fds=False` and `-C` in place of `cwd` are the other two.
    """
    found = shutil.which("git")
    if not found:
        raise Unreadable(
            "git is not on PATH, so this tree's history cannot be read. DEC-8's gate "
            "compares the manifest with its past and has nothing to compare against")
    return found


def _run_git(args: list[str], *, text: bool = True, root: str | None = None,
             env=None):
    try:
        return subprocess.run(
            [_git_binary(), "-C", ROOT if root is None else root, *args],
            capture_output=True, close_fds=False,
            text=text, **({"encoding": "utf-8", "errors": "replace"} if text else {}),
            **({"env": env} if env is not None else {}))
    except OSError as exc:
        raise Unreadable(f"git would not run: {exc}") from exc


def git(*args: str, root: str | None = None, env=None) -> str:
    done = _run_git(list(args), root=root, env=env)
    if done.returncode != 0:
        raise Unreadable(f"git {' '.join(args)} failed: {done.stderr.strip()}")
    return done.stdout


def leave_the_hook_behind(environment) -> list[str]:
    """Remove from `environment` what git sets to aim a hook at its repository.

    git starts `pre-push` in a linked worktree with `GIT_DIR` naming that worktree's
    private directory (measured, git 2.56.0 for Windows; from a plain checkout it sets
    none, and `pre-commit` is given `GIT_INDEX_FILE` as well). Every process the hook
    starts inherits it, and it outranks `-C`: a `git init` or a `git commit` meant for
    a temp directory is then carried out on the repository under the hook.
    On 3 October 2026 the suite, run by the push gate from a worktree, did exactly
    that with its own fixture repository: the real one was marked bare and took two
    commits it was never meant to see.

    The names are git's own list (`rev-parse --local-env-vars`), asked rather than
    kept, so a variable a later git adds is covered the day it is installed. Returns
    the names removed. A git that will not answer is `Unreadable`, not an empty list:
    carrying on with the hook's environment intact is the failure this exists for.
    """
    try:
        listed = subprocess.run([_git_binary(), "rev-parse", "--local-env-vars"],
                                capture_output=True, close_fds=False,
                                encoding="utf-8", errors="replace")
    except OSError as exc:
        raise Unreadable(f"git would not run: {exc}") from exc
    names = listed.stdout.split()
    if listed.returncode or not names:
        raise Unreadable("git did not say which variables aim it at a repository "
                         f"({listed.stderr.strip() or 'no names printed'})")
    return [name for name in names if environment.pop(name, None) is not None]


def git_directory(root: str | None = None, *, env=None) -> str:
    """Git's per-worktree directory, also when `.git` is a file or we are below ROOT.

    Relative answers belong to the directory git ran in. The common directory would
    share a verification stamp between worktrees whose content need not agree.
    """
    root = ROOT if root is None else root
    inside = _run_git(["rev-parse", "--is-inside-work-tree"], root=root, env=env)
    if inside.returncode or inside.stdout.strip() != "true":
        raise Unreadable(
            f"{root} is not a git checkout, so no history can be walked. This gate "
            f"compares the tree with its past and has nothing to compare against "
            f"({inside.stderr.strip() or inside.stdout.strip()})")
    printed = git("rev-parse", "--git-dir", root=root, env=env).strip()
    return os.path.abspath(os.path.join(root, printed))
