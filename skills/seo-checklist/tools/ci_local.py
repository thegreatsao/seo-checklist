#!/usr/bin/env python3
"""Run the CI workflow's own steps locally, before a push spends minutes on them.

The steps are **read from `.github/workflows/ci.yml`**, not retyped here. A local
copy of a check list is the defect this repository keeps finding in itself: the
copy passes while the original moved, and the reader that would have noticed is
the line somebody would have had to edit to avoid it. So this tool has no list.

What it deliberately does not do, and says so on every run:

* it runs one Python — the interpreter it was started with — where the `test` job
  runs a 3.10/3.11/3.13 matrix. The floor is a real floor (three scripts use PEP
  604 unions with no `__future__` import), so a green local run does not promise
  a green 3.10 leg;
* it skips `uses:` steps, which are checkout and setup, and names each one;
* it skips a step whose every line installs a package, because this machine runs
  out of its checked-out venv and re-running pip on each push buys nothing. That
  is derived from what the step's lines *are*, not from a list of step names here
  — a list of names would rot the moment CI renamed one;
* `test-windows` and `test` overlap heavily by design; running both locally is
  the same work twice, so `--job` picks.

A step it cannot run is a failure, not a skip. The whole value of a pre-push gate
is that green means something, and a gate that quietly drops what it could not
execute is worth less than no gate at all.
"""
from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
WORKFLOW = os.path.join(ROOT, ".github", "workflows", "ci.yml")
# Written on success, read to make the second push of an unchanged tree free. It
# lives in .git/ so it never travels: a stamp that can cross machines is a claim
# about a tree this machine never built.
STAMP = os.path.join(ROOT, ".git", "ci-local-verified")


# This file prints em dashes and the step names CI wrote, and a Windows console
# defaults to cp1252, where that is a UnicodeEncodeError rather than a dash. A
# gate that dies on its own report is not a gate.
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


def load_workflow() -> dict:
    try:
        import yaml
    except ImportError:
        sys.exit("PyYAML is needed to read the workflow and is not installed.\n"
                 "It is not in requirements.txt because nothing shipped needs it:\n"
                 "    python -m pip install pyyaml")
    with open(WORKFLOW, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_jobs() -> dict:
    return load_workflow()["jobs"]


def step_env(base: dict, workflow: dict, job: dict, step: dict) -> dict:
    """The environment CI gives this step: the workflow's `env`, then the job's, then
    the step's own, each over the last — GitHub's order.

    Read rather than restated, like the steps themselves. Until 0.124.0 the workflow
    had no `env` at all and this ignored the key; the first one it gained,
    `SEO_LOOPBACK_ONLY`, is a guarantee about the run, and a local gate running the
    same steps without it would be a different run passing under the same name.
    """
    env = dict(base)
    for layer in (workflow, job, step):
        env.update({str(k): str(v) for k, v in (layer.get("env") or {}).items()})
    return env


def only_installs(script: str) -> bool:
    """True when every line of the step installs something.

    Derived from the lines, so a renamed or reworded install step is still
    recognised and a step that installs *and* checks something is not.
    """
    lines = [ln.strip() for ln in script.splitlines()]
    lines = [ln for ln in lines if ln and not ln.startswith("#")]
    return bool(lines) and all(
        ln.startswith(("pip ", "python -m pip ", "py -m pip ")) for ln in lines)


# Three rules this tree holds every child process to, and
# `test_every_child_in_the_tree_is_started_without_forking` and its two siblings
# are what say so: `close_fds=False`, no `cwd=`, and no bare binary name — a name
# with no dirname makes CPython fork, and macOS kills a forked child inside
# Apple's atfork handler before it execs. So the directory is passed as a flag
# (`git -C`) or as a `cd` inside the script, and the binaries are resolved here.
def resolve(binary: str) -> str:
    found = shutil.which(binary)
    if not found:
        sys.exit(f"{binary} is not on PATH, and these steps are written for it")
    return found


def tree_hash() -> str | None:
    """The content of the **working tree**, including files not yet added.

    This read `git write-tree` against the real index until 0.104.0, and that hashes
    the *index* — so with fifteen modified and two new files on disk it returned HEAD's
    tree and the stamp from the previous session matched. `ci_local.py` printed
    *"this exact tree already ran green here. Nothing changed, so nothing is rerun"*
    over a release it had never seen, which is the failure shape this whole file is
    built to refuse: a check whose failure is indistinguishable from its success.

    It was invisible because the hook's own moment is the one moment the two agree.
    At `git push` everything is committed, so index and working tree are the same
    tree and the answer is right. The README documents running this by hand, and
    every such run mid-edit was answering about the last commit.

    A throwaway index keeps the real one untouched: `git add -A` into it stages the
    working tree as it stands, `.gitignore` still applies, and `write-tree` then names
    the content on disk. An unchanged tree is still instant, because committing does
    not change the bytes the hash is taken over.
    """
    git = resolve("git")
    scratch = os.path.join(ROOT, ".git", "ci-local-index")
    env = dict(os.environ, GIT_INDEX_FILE=scratch)
    try:
        if os.path.exists(scratch):
            os.remove(scratch)
        staged = subprocess.run([git, "-C", ROOT, "add", "-A"], capture_output=True,
                                text=True, close_fds=False, env=env)
        if staged.returncode != 0:
            return None
        r = subprocess.run([git, "-C", ROOT, "write-tree"], capture_output=True,
                           text=True, close_fds=False, env=env)
        return r.stdout.strip() if r.returncode == 0 else None
    finally:
        if os.path.exists(scratch):
            os.remove(scratch)


def run_step(name: str, script: str, env: dict) -> tuple[bool, float, str]:
    started = time.time()
    # The workflow's steps assume the repository root, and `cwd=` is the one way
    # of arriving there this tree forbids — so the script says it itself.
    at_root = f"cd {shlex.quote(ROOT)}\n{script}"
    # `text=True` alone decodes with the console's codepage, which on Windows is
    # cp1252: a step printing an em dash then kills the reader thread and the run
    # dies with a TypeError about None, having said nothing about the step. Named
    # explicitly so a gate cannot be defeated by a character in somebody's output.
    proc = subprocess.run([resolve("bash"), "-euo", "pipefail", "-c", at_root],
                          env=env, capture_output=True, close_fds=False,
                          encoding="utf-8", errors="replace")
    return proc.returncode == 0, time.time() - started, proc.stdout + proc.stderr


def untracked() -> set[str]:
    r = subprocess.run([resolve("git"), "-C", ROOT, "status", "--porcelain",
                        "--untracked-files=all"],
                       capture_output=True, close_fds=False,
                       encoding="utf-8", errors="replace")
    return {ln[3:] for ln in r.stdout.splitlines() if ln.startswith("?? ")}


def sweep(before: set[str]) -> list[str]:
    """Move what this run dropped into the tree out of the way.

    CI's smoke steps write `dead.json`, `live.html` and a dozen others beside the
    checkout, which costs nothing on a runner that is thrown away and leaves this
    working tree dirty after every push. `.gitignore` here is deliberately made of
    shapes rather than filenames, and a list of these names would be the second
    kind — so they are moved instead, into `local/`, which is already outside git.

    Moved and not deleted, and only paths that were absent when the run started:
    each one appeared during it, and a file somebody happened to create meanwhile
    is recoverable rather than gone.
    """
    landed = sorted(untracked() - before)
    if not landed:
        return []
    dest = os.path.join(ROOT, "local", "ci-local-debris")
    os.makedirs(dest, exist_ok=True)
    moved = []
    for rel in landed:
        src = os.path.join(ROOT, rel)
        if not os.path.isfile(src):
            continue
        target = os.path.join(dest, rel.replace("/", "__"))
        os.replace(src, target)
        moved.append(rel)
    return moved


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--job", default="test,census",
                    help="comma-separated jobs, or 'all'. The default runs "
                         "`test` and `census`: `test-windows` is a subset of "
                         "`test`, which on this machine already runs on Windows")
    ap.add_argument("--keep-going", action="store_true",
                    help="run every step instead of stopping at the first red one")
    ap.add_argument("--list", action="store_true", help="name the steps and exit")
    ap.add_argument("--no-cache", action="store_true",
                    help="ignore the stamp from a previous green run")
    a = ap.parse_args()

    workflow = load_workflow()
    jobs = workflow["jobs"]
    wanted = list(jobs) if a.job == "all" else [j.strip() for j in a.job.split(",")]
    for job in wanted:
        if job not in jobs:
            sys.exit(f"no job {job!r} in ci.yml; it has {', '.join(jobs)}")

    steps = [(job, s) for job in wanted for s in jobs[job]["steps"]]
    if a.list:
        for job, s in steps:
            if "run" not in s:
                kind = f"not run ({s.get('uses', '?')})"
            elif only_installs(s["run"]):
                kind = "not run (installs packages)"
            else:
                kind = "run"
            print(f"  {job:<14} {s.get('name', '(unnamed)'):<52} {kind}")
        return 0

    here = tree_hash()
    if here and not a.no_cache and os.path.exists(STAMP):
        with open(STAMP, encoding="utf-8") as f:
            if f.read().strip() == f"{','.join(wanted)} {here}":
                print(f"ci_local: this exact tree ({here[:12]}) already ran {','.join(wanted)} "
                      f"green here. Nothing changed, so nothing is rerun.")
                return 0

    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    # CI calls the interpreter `python`; on Windows the venv ships `python.exe`
    # but a bare `python` may be a store stub, so the running one is named.
    env["PATH"] = os.path.dirname(sys.executable) + os.pathsep + env["PATH"]

    runnable = [(j, s) for j, s in steps
                if "run" in s and not only_installs(s["run"])]
    skipped = [(j, s) for j, s in steps
               if "run" not in s or only_installs(s["run"])]
    print(f"ci_local: {len(runnable)} runnable step(s) from {', '.join(wanted)}; "
          f"one interpreter ({sys.version.split()[0]}), not the CI matrix.\n")

    before = untracked()
    failures, total = [], 0.0
    for job, step in runnable:
        name = step.get("name", "(unnamed)")
        ok, took, output = run_step(name, step["run"],
                                    step_env(env, workflow, jobs[job], step))
        total += took
        print(f"  {'ok  ' if ok else 'FAIL'}  {took:6.1f}s  {job}: {name}")
        if not ok:
            failures.append((job, name))
            print("\n".join("        " + ln for ln in output.strip().splitlines()[-40:]))
            if not a.keep_going:
                break

    moved = sweep(before)
    print(f"\n  {total:.0f}s total")
    if moved:
        print(f"  moved to local/ci-local-debris/: {', '.join(moved)}")
    for job, step in skipped:
        why = step.get("uses") or "installs packages; this machine has its venv"
        print(f"  not run: {job}: {step.get('name') or step.get('uses')} — {why}")
    for job in jobs:
        if job not in wanted:
            print(f"  not run: the whole {job} job")
    print("  not run: the 3.10 and 3.11 matrix legs")

    if failures:
        print(f"\n{len(failures)} step(s) failed. Nothing was pushed.")
        return 1
    if here:
        with open(STAMP, "w", encoding="utf-8") as f:
            f.write(f"{','.join(wanted)} {here}\n")
    print("\nEvery step this machine can run is green.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
