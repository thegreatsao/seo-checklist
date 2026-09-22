#!/usr/bin/env python3
"""Every move a declaration or a fixture made since the epoch, against the record of it.

`openspec/specs/declarations/` DEC-8. When a declaration and a run disagree, somebody
decides which side is wrong; the manifest, the fixture and the checker must not be
edited to make the suite green without that decision being written down. The cheapest
way to make the oracle pass is always to edit the declaration, and it is available at
the exact moment somebody is trying to get a release out.

**This reads history, not intent.** It cannot tell whether a recorded argument is a
good one, and it does not try. What it refuses is the *unrecorded* edit: a `PASS` that
became a `FAIL`, a declaration that quietly left the manifest, or a fixture page edited
under a prediction, with nothing in the tree saying a decision was taken. That much is
mechanical, which is why DEC-8 is buildable and DEC-1 is not.

Three doors, all three measured in this repository's own history before the gate was
written (`local/dec8/expect-moves.txt`):

* **`expect` rewritten** — 79 values moved across 18 commits;
* **a declaration withdrawn** — `8ce2b9b` removed six rather than editing them, which
  is the same resolution through a door a gate watching `expect` cannot see;
* **a fixture edited** — 13 commits touched the served trees, and two of them
  (`ce4446b`, `df7d9bd`) moved declarations in the same commit.

A gate built for the first door alone would have reported full coverage while two of
the three doors it is named after stood open.

## What is compared with what

Two ledgers, and both directions are checked.

*Observed* is derived by walking every commit from `EPOCH` to `HEAD` that touched the
manifest or any served fixture material, plus the working tree as the final state, and
recording each transition between consecutive states. *Recorded* is the manifest's own
`triage` list. A transition with no record is an unrecorded edit. A record with no
transition is a false record — the shape somebody would write to satisfy this gate in
advance — and it reddens too, because a ledger nobody checks the other way is a count
rather than a comparison.

## Why it refuses rather than skips

`actions/checkout@v5` clones to depth 1. A history walk over a shallow clone finds no
commits, agrees with an empty record, and prints a pass — a check whose failure looks
exactly like its success. So an unreachable `EPOCH`, a missing `.git`, or a `git` that
will not run is a **failure** with a named reason, never a skip. The workflow carries
`fetch-depth: 0` on every job that runs this.

    python tools/audit_declaration_revisions.py           # the ledgers
    python tools/audit_declaration_revisions.py --check   # exit 1 if they disagree
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
ROOT = os.path.dirname(os.path.dirname(SKILL_DIR))
TESTS = os.path.join(ROOT, "tests")
MANIFEST_PATH = "tests/fixtures/expectations.json"
FIXTURES_PATH = "tests/fixtures"

sys.path.insert(0, TESTS)
from harness import FixtureSite  # noqa: E402

# The tree as it stood at `0.103.0`, the release before this gate existed. Everything
# before it is history this record does not claim to cover: the 79 moves that came
# first were argued in commit messages and in CHANGELOG entries, and back-filling them
# from those would be writing a record of decisions I did not take. The epoch is what
# makes the claim honest — the ledger is complete from here, and says so.
EPOCH = "9b841021c8f930b10b4015b9925f281fd3d5404e"

# What the decision was. DEC-8 says both triage outcomes are legitimate and only the
# unrecorded edit is not, so the vocabulary has to say "the checker was defective" as
# easily as "the prediction was".
#
# `new-material` is the fourth, added at 0.105.0 the first time this gate met real work.
# Giving the broken fixture an alt of `huge.png`, so that CI-016's new placeholder
# signal is exercised by a served page, moves the digest on both origins built from
# that tree — and no side was wrong. The field was called `side` and the three values
# above were all it had, so the only way to record that edit was to claim the fixture
# had been in error, which is a false entry in the one file whose value is that its
# entries are true. A vocabulary that cannot say what happened produces a record that
# lies, and the gate would still have gone green.
#
# What did NOT change is that the move must be recorded. The requirement is that no
# edit to either side is silent; it was never that every edit is somebody's mistake.
DECISIONS = (
    "prediction-was-wrong",
    "checker-was-wrong",
    "fixture-was-wrong",
    "new-material",
)

KINDS = ("expect", "withdrawal", "fixture")

MIN_ARGUMENT = 40


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


def _run_git(args: list[str], *, text: bool = True):
    try:
        return subprocess.run(
            [_git_binary(), "-C", ROOT, *args], capture_output=True, close_fds=False,
            text=text, **({"encoding": "utf-8", "errors": "replace"} if text else {}))
    except OSError as exc:
        raise Unreadable(f"git would not run: {exc}") from exc


def git(*args: str) -> str:
    done = _run_git(list(args))
    if done.returncode != 0:
        raise Unreadable(f"git {' '.join(args)} failed: {done.stderr.strip()}")
    return done.stdout


def epoch_is_reachable() -> None:
    """Refuse a shallow clone by name, before anything reads as agreement."""
    if not os.path.isdir(os.path.join(ROOT, ".git")):
        raise Unreadable(
            f"{ROOT} is not a git checkout, so no history can be walked. This gate "
            f"compares the tree with its past and has nothing to compare against")
    try:
        kind = git("cat-file", "-t", EPOCH).strip()
    except Unreadable as exc:
        raise Unreadable(
            f"the epoch commit {EPOCH[:8]} is not in this clone ({exc}). A shallow "
            f"checkout finds no commits and agrees with an empty record, which is a "
            f"pass that means nothing — give the job `fetch-depth: 0`") from exc
    if kind != "commit":
        raise Unreadable(f"the epoch {EPOCH[:8]} is a {kind}, not a commit")


def epoch_is_an_ancestor() -> None:
    """A clone deep enough to hold the epoch may still not descend from it."""
    done = _run_git(["merge-base", "--is-ancestor", EPOCH, "HEAD"])
    if done.returncode != 0:
        raise Unreadable(
            f"the epoch {EPOCH[:8]} is not an ancestor of HEAD. This branch does not "
            f"descend from the release the record starts at, so the walk would compare "
            f"two unrelated trees")


def watched_paths() -> tuple[str, ...]:
    """The manifest, plus every fixture directory an origin is actually built from.

    Derived from `FixtureSite.material()` rather than listed here, so that adding an
    origin or moving a tree moves this gate with it. A path named here and nowhere else
    is a path that goes stale in silence.
    """
    trees = {f"{FIXTURES_PATH}/{part}"
             for dirs in FixtureSite.material().values() for part in dirs}
    return (MANIFEST_PATH, *sorted(trees))


def _blob(sha: str, path: str) -> bytes | None:
    """The bytes at a commit, or `None` where that path did not exist there.

    Bytes rather than text on purpose: the digest normalises line endings itself, and
    letting Python decode first would hide the difference this is built to notice.
    """
    done = _run_git(["show", f"{sha}:{path}"], text=False)
    return done.stdout if done.returncode == 0 else None


def _normalise(raw: bytes) -> bytes:
    """Line endings out, so the digest identifies content and not the checkout.

    A byte hash taken through a clone that translates line endings identifies the
    working copy, not the material — which turns every comparison across two machines
    into a false difference and trains the reader to ignore this gate.
    """
    return raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def digest_at(sha: str | None) -> dict[str, str]:
    """Per origin, a digest of the material it serves, at a commit or in the worktree.

    `sha` of `None` reads the files on disk, which is what makes an uncommitted edit
    visible at the moment it is made rather than at the moment it is pushed.
    """
    material = FixtureSite.material()
    out = {}
    for label, dirs in material.items():
        running = hashlib.sha256()
        for part in sorted(dirs):
            base = f"{FIXTURES_PATH}/{part}"
            if sha is None:
                root = os.path.join(ROOT, *base.split("/"))
                files = []
                for here, _sub, names in os.walk(root):
                    for name in names:
                        full = os.path.join(here, name)
                        rel = os.path.relpath(full, ROOT).replace(os.sep, "/")
                        files.append(rel)
                files.sort()
            else:
                listed = git("ls-tree", "-r", "--name-only", sha, "--", base)
                files = sorted(line for line in listed.splitlines() if line.strip())
            for rel in files:
                if sha is None:
                    with open(os.path.join(ROOT, *rel.split("/")), "rb") as stream:
                        raw = stream.read()
                else:
                    raw = _blob(sha, rel)
                    if raw is None:
                        continue
                running.update(rel.encode("utf-8"))
                running.update(b"\x00")
                running.update(_normalise(raw))
                running.update(b"\x00")
        out[label] = running.hexdigest()[:12]
    return out


def manifest_at(sha: str | None) -> dict:
    if sha is None:
        with open(os.path.join(ROOT, *MANIFEST_PATH.split("/")), encoding="utf-8") as s:
            return json.load(s)
    raw = _blob(sha, MANIFEST_PATH)
    if raw is None:
        raise Unreadable(f"{MANIFEST_PATH} does not exist at {sha[:8]}")
    return json.loads(raw.decode("utf-8"))


def _declared(doc: dict) -> dict[tuple[str, str], str]:
    flat = {}
    for label, items in doc.get("fixtures", {}).items():
        for item_id, body in items.items():
            if isinstance(body, dict) and "expect" in body:
                flat[(label, item_id)] = body["expect"]
    return flat


def states() -> list[tuple[str, dict, dict]]:
    """Every state from the epoch to the worktree, oldest first.

    `(label, declarations, digests)`. Only commits that touched watched material are
    read: a release that moved neither cannot have moved a declaration through any of
    the three doors.
    """
    epoch_is_reachable()
    epoch_is_an_ancestor()
    listed = git("log", "--format=%H", "--reverse", f"{EPOCH}..HEAD", "--",
                 *watched_paths())
    shas = [EPOCH, *[line.strip() for line in listed.splitlines() if line.strip()]]
    out = [(sha, _declared(manifest_at(sha)), digest_at(sha)) for sha in shas]
    out.append(("worktree", _declared(manifest_at(None)), digest_at(None)))
    return out


def observed() -> list[dict]:
    """The transition ledger the tree's own history implies."""
    moves = []
    series = states()
    # `strict=False`: pairing a list with its own tail is one shorter by construction,
    # and that is the intent rather than an oversight.
    for (_before, was, was_digest), (_after, now, now_digest) in zip(
            series, series[1:], strict=False):
        for key in sorted(set(was) & set(now)):
            if was[key] != now[key]:
                moves.append({"kind": "expect", "origin": key[0], "item": key[1],
                              "from": was[key], "to": now[key]})
        for key in sorted(set(was) - set(now)):
            moves.append({"kind": "withdrawal", "origin": key[0], "item": key[1],
                          "from": was[key], "to": None})
        for label in sorted(set(was_digest) | set(now_digest)):
            before, after = was_digest.get(label), now_digest.get(label)
            if before != after:
                moves.append({"kind": "fixture", "origin": label, "item": None,
                              "from": before, "to": after})
    return moves


def recorded() -> list[dict]:
    doc = manifest_at(None)
    return list(doc.get("triage", []))


def _key(row: dict) -> tuple:
    return (row.get("kind"), row.get("origin"), row.get("item"),
            row.get("from"), row.get("to"))


def malformed(rows: list[dict]) -> list[str]:
    """A record that cannot be read is not a record. Checked before it is compared."""
    problems = []
    for index, row in enumerate(rows):
        where = f"triage[{index}]"
        if not isinstance(row, dict):
            problems.append(f"{where} is not an object")
            continue
        if row.get("kind") not in KINDS:
            problems.append(f"{where}: kind {row.get('kind')!r} is not one of "
                            f"{', '.join(KINDS)}")
        if row.get("decided") not in DECISIONS:
            problems.append(f"{where}: decided {row.get('decided')!r} does not say what "
                            f"the decision was; one of {', '.join(DECISIONS)}")
        why = (row.get("why") or "").strip()
        if len(why) < MIN_ARGUMENT:
            problems.append(f"{where}: the argument is {len(why)} characters. A record "
                            f"that says a decision was taken without saying what it "
                            f"rested on is the unrecorded edit with a field filled in")
        if row.get("kind") == "fixture" and row.get("item") is not None:
            problems.append(f"{where}: a fixture move names no item")
        if row.get("kind") in ("expect", "withdrawal") and not row.get("item"):
            problems.append(f"{where}: a {row.get('kind')} move names its item")
    return problems


def disagreements() -> list[str]:
    """Both directions: an unrecorded move, and a record of a move that never happened."""
    seen = observed()
    record = recorded()
    problems = malformed(record)
    if problems:
        return problems

    pending = {}
    for row in record:
        pending.setdefault(_key(row), []).append(row)

    for move in seen:
        key = _key(move)
        if pending.get(key):
            pending[key].pop()
            continue
        what = (f"{move['origin']} {move['item']}" if move["item"]
                else f"the {move['origin']} fixture material")
        problems.append(
            f"unrecorded {move['kind']}: {what} went {move['from']} -> {move['to']} "
            f"and the manifest's `triage` does not say what was decided or why. "
            f"Every outcome is legitimate — the prediction may have been wrong, the "
            f"checker may have been, or this may be new material for a check that did "
            f"not exist ({', '.join(DECISIONS)}); record which, and the argument")

    for key, leftovers in sorted(pending.items(), key=lambda pair: str(pair[0])):
        for _row in leftovers:
            kind, origin, item, was, now = key
            what = f"{origin} {item}" if item else f"the {origin} fixture material"
            problems.append(
                f"recorded {kind} that never happened: {what} is recorded as going "
                f"{was} -> {now}, and no commit between the epoch and this tree did "
                f"that. A record written ahead of the edit is not a record of a "
                f"decision")
    return problems


def stamp_disagreement() -> list[str]:
    """The stored digest, re-computed from the material rather than read back.

    DEC-9's shape, avoided: a version a hand can set while the content stays put. This
    compares the stamp with a fresh reading of the files it claims to describe, so an
    edited stamp reddens exactly as loudly as an edited page.
    """
    stored = manifest_at(None).get("fixture_digest")
    if not isinstance(stored, dict):
        return ["the manifest records no `fixture_digest`, so a fixture edit reaches "
                "no reader at all"]
    fresh = digest_at(None)
    if stored == fresh:
        return []
    out = []
    for label in sorted(set(stored) | set(fresh)):
        if stored.get(label) != fresh.get(label):
            out.append(f"the recorded digest for {label} is {stored.get(label)} and "
                       f"the material on disk hashes to {fresh.get(label)}")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="exit 1 if the record and the history disagree")
    args = parser.parse_args()

    try:
        series = states()
        seen = observed()
    except Unreadable as exc:
        print(f"cannot read history: {exc}", file=sys.stderr)
        return 1

    print(f"epoch {EPOCH[:8]}, {len(series) - 1} state(s) after it, "
          f"ending in the working tree")
    print(f"watched: {', '.join(watched_paths())}")
    print()
    print(f"observed {len(seen)} move(s):")
    for move in seen:
        what = f"{move['origin']} {move['item']}" if move["item"] else \
            f"{move['origin']} (fixture material)"
        print(f"  {move['kind']:<11} {what:<24} {move['from']} -> {move['to']}")
    if not seen:
        print("  none")
    print()
    print(f"recorded {len(recorded())} decision(s)")
    print()

    problems = stamp_disagreement() + disagreements()
    for line in problems:
        print(f"  {line}", file=sys.stderr)
    if not problems:
        print("every move since the epoch carries a recorded decision, and every "
              "recorded decision names a move that happened")
    return 1 if (args.check and problems) else 0


if __name__ == "__main__":
    raise SystemExit(main())
