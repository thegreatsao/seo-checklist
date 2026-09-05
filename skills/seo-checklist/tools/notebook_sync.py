"""Freshness gate between this repo and a NotebookLM notebook holding its theory.

A notebook built from these documents is a *snapshot* of the repo. It keeps
answering after the repo moves on, and nothing in the answer says so. This
compares the two and refuses to call a stale notebook fresh.

    check   read-only; exits 1 on any divergence, and on anything it could not read
    sync    re-uploads only what diverged, then re-checks through the notebook

`sync` never touches a source whose copy could not be read: replacing a document
because the fetch failed is a remedy for not having looked. An expired session
ends the run where it is first seen rather than becoming a verdict per source.

The stamp is read back out of the notebook, never from a ledger this script
keeps itself: a record written here is not evidence of what the notebook holds.

    SEO_NOTEBOOK_ID    notebook to compare against (or --notebook); required,
                       and per-user, which is why it is not committed
    SEO_NOTEBOOK_CLI   notebooklm-py executable (default: `notebooklm` on PATH)
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# tools/ -> skills/seo-checklist/ -> skills/ -> repo root
REPO = Path(__file__).resolve().parents[3]
STAMP_RE = re.compile(r"sourcesha256([0-9a-f]{64})")

SKILL = Path("skills/seo-checklist")
CHECKLIST_JSON = SKILL / "resources/config/checklist.json"
AGENT_DIR = SKILL / "resources/agents"

# Title is the identity of a source inside the notebook.
FIXED = [
    ("Registry - all 217 checks", "registry", CHECKLIST_JSON),
    ("SKILL - audit procedure", "file", SKILL / "SKILL.md"),
    ("README - project overview", "file", Path("README.md")),
    ("Reference - script output shapes", "file",
     SKILL / "resources/references/script-output-shapes.md"),
    ("Reference - client report structure", "file",
     SKILL / "resources/references/client-report-structure.md"),
    ("Playbook - local SEO", "file", SKILL / "resources/playbooks/local-seo.md"),
    ("Playbook - competitor research", "file",
     SKILL / "resources/playbooks/competitor-research.md"),
    ("LLM reviewer agents - 5 lenses", "agents", AGENT_DIR),
]

SPECS = Path("openspec") / "specs"


def manifest(repo: Path) -> list:
    """Every document this notebook holds, with the specs derived rather than listed.

    The three specs used to be three literals here, and the fourth — `declarations`,
    merged the same day this changed — was invisible to the gate until somebody
    remembered to add a line. That is the defect `openspec/specs/declarations/` calls DEC-6 in
    the manifest it specifies: a hand-kept list cannot say what is missing from it, and
    the reader that would notice is the same list that would have to be edited.

    A spec is `openspec/specs/<name>/spec.md`, its title is `Spec - <name>`, which is what the
    three were called, so the notebook's existing sources keep their identity.
    """
    specs = [(f"Spec - {p.parent.name}", "file", p.relative_to(repo))
             for p in sorted((repo / SPECS).glob("*/spec.md"))]
    return FIXED[:3] + specs + FIXED[3:]


def run(args, timeout=600):
    # close_fds=False for the same reason as everywhere else in this tree: it
    # puts CPython on `posix_spawn` instead of `fork` + `exec`, and a forked
    # child dies inside Apple's atfork handler on macOS. See checklist_runner.py.
    return subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout, close_fds=False)


CONFIG = {"cli": None, "notebook": None}


def resolve_cli(explicit: str | None) -> str:
    cli = explicit or os.environ.get("SEO_NOTEBOOK_CLI") or "notebooklm"
    found = shutil.which(cli) or (cli if Path(cli).exists() else None)
    if not found:
        sys.exit("notebooklm CLI not found: %s\n"
                 "Install notebooklm-py, or set SEO_NOTEBOOK_CLI to its path." % cli)
    return found


def resolve_notebook(explicit: str | None) -> str:
    nb = explicit or os.environ.get("SEO_NOTEBOOK_ID")
    if not nb:
        sys.exit("no notebook given: set SEO_NOTEBOOK_ID or pass --notebook.\n"
                 "`notebooklm list` prints the ids you own.")
    return nb


AUTH_DEAD = re.compile(r"Authentication expired or invalid|notebooklm login", re.I)
AUTH_MESSAGE = (
    "the notebooklm session has expired or was signed out — run `notebooklm login`.\n"
    "Stopped at the first call that said so rather than working through the rest: a\n"
    "run that carries on past a dead session deletes and re-adds against nothing.\n"
    "Run `check` once logged in to see what the notebook actually holds.")


def nlm(*args, timeout=600):
    """One CLI call; a dead session ends the run instead of being reported per source.

    An expired cookie fails every call after it. Reported per source it reads as
    seven documents having gone wrong, and that is the shape that sent `sync` off
    to delete seven good ones. Ended here it reads as one session having gone
    wrong, which is what happened.
    """
    r = run([CONFIG["cli"], *args, "-n", CONFIG["notebook"]], timeout=timeout)
    if r.returncode != 0 and AUTH_DEAD.search((r.stderr or "") + (r.stdout or "")):
        sys.exit(AUTH_MESSAGE)
    return r


def sha(data: bytes) -> str:
    """Hash with line endings normalised.

    Raw bytes are the wrong unit here. `core.autocrlf` rewrites newlines at
    checkout, so the same commit yields CRLF on one clone and LF on another, and
    a byte hash would call every one of those files stale on the machine that
    did not upload it — a gate that cries wolf gets turned off. Normalising is
    what makes the stamp mean "this content", not "this checkout".
    """
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def agent_files(repo: Path):
    return sorted((repo / AGENT_DIR).glob("*.md"))


# ---------------------------------------------------------------- rendering

def render_registry(repo: Path) -> str:
    d = json.loads((repo / CHECKLIST_JSON).read_text(encoding="utf-8"))
    items, cats = d["items"], d["categories"]
    by_cat = {c["key"]: [] for c in cats}
    for i in items:
        by_cat[i["category"]].append(i)

    o = io.StringIO()
    w = o.write
    w("# SEO Checklist - registry of %d checks\n\n" % d["item_count"])
    w("- Registry version: `%s`\n" % d["registry_version"])
    w("- Schema version: %s\n" % d["version"])
    w("- Source of truth: %s\n" % d["source"])
    w("- Generated from `resources/config/checklist.json` of the seo-checklist plugin.\n\n")
    w("Every check has a stable ID (`<PREFIX>-<NNN>`), a severity, an effort estimate\n"
      "and an execution source naming who performs it: `script` (automated), `llm`\n"
      "(model judgement), `manual` (human), `gsc` (Search Console data).\n\n")

    w("## Categories\n\n| Prefix | Category | Checks |\n|---|---|---|\n")
    for c in cats:
        w("| %s | %s | %d |\n" % (c["prefix"], c["label"], len(by_cat[c["key"]])))
    w("| | **Total** | **%d** |\n\n" % len(items))

    for field, order in (("severity", ["critical", "high", "medium", "low"]),
                         ("effort", ["low", "medium", "high"]),
                         ("source", ["script", "llm", "manual", "gsc"])):
        cnt = collections.Counter(i[field] for i in items)
        w("## Distribution by %s\n\n| %s | Checks |\n|---|---|\n" % (field, field))
        for k in order:
            if cnt.get(k):
                w("| %s | %d |\n" % (k, cnt[k]))
        w("\n")

    w("## Checks by category\n\n")
    for c in cats:
        w("### %s - %s (%d checks)\n\n" % (c["prefix"], c["label"], len(by_cat[c["key"]])))
        for i in by_cat[c["key"]]:
            w("#### %s - %s\n\n" % (i["id"], i["title"]))
            w("- Severity: **%s** | Effort: %s | Performed by: %s\n"
              % (i["severity"], i["effort"], i["source"]))
            if i.get("plerdy_ref") is not None:
                w("- Plerdy reference: #%s\n" % i["plerdy_ref"])
            if i.get("lens"):
                w("- Lens: %s\n" % i["lens"])
            if i.get("scores_with"):
                w("- Scores with: %s\n" % i["scores_with"])
            ch = i.get("check")
            if isinstance(ch, dict):
                if ch.get("script"):
                    a = " ".join(ch.get("args", []))
                    w("- Script: `%s`\n" % (ch["script"] + ((" " + a) if a else "")))
                for key, label in (("requires", "Requires"), ("cannot_fail", "Cannot fail")):
                    if ch.get(key):
                        w("- %s: %s\n" % (label, ch[key]))
                for key, label in (("applies_when", "Applies when"), ("warn", "Warn"),
                                   ("assert", "Verdict rule")):
                    if ch.get(key):
                        w("- %s: %s\n" % (label, json.dumps(ch[key], ensure_ascii=False)))
            else:
                w("- No automated check defined (performed by hand or by model).\n")
            if i.get("fix"):
                w("- Fix: %s\n" % i["fix"])
            w("\n")
    return o.getvalue()


def render_agents(repo: Path) -> str:
    o = io.StringIO()
    o.write("# SEO Checklist - LLM reviewer agents\n\n"
            "The five model-driven review lenses the plugin uses for `source: llm` checks.\n\n")
    for f in agent_files(repo):
        o.write("\n---\n\n## %s\n\n%s\n" % (f.stem, f.read_text(encoding="utf-8")))
    return o.getvalue()


def build(kind: str, target: Path, repo: Path) -> tuple[str, str]:
    """Return (document text carrying its stamp, stamp hex).

    The stamp hashes the repo INPUT, never the rendered output, so it says
    which commit's content the notebook is holding.
    """
    if kind == "registry":
        body = render_registry(repo)
        stamp = sha((repo / CHECKLIST_JSON).read_bytes())
    elif kind == "agents":
        body = render_agents(repo)
        stamp = sha(b"".join(f.read_bytes() for f in agent_files(repo)))
    else:
        body = (repo / target).read_text(encoding="utf-8")
        stamp = sha((repo / target).read_bytes())

    lines = body.split("\n")
    at = 1 if lines and lines[0].startswith("# ") else 0
    lines.insert(at, "\nsource-sha256: %s\n" % stamp)
    return "\n".join(lines), stamp


# ------------------------------------------------------------------ notebook

class Unread:
    """The notebook's copy could not be read at all.

    Distinct from `None`, which means the copy was read and carries no stamp.
    Collapsing the two makes a transport failure into a claim about a document —
    the registry's own REG-8 and the verdict vocabulary's NO_DATA say the same
    thing about a rule that finds nothing at its path, and this tool was breaking
    the rule its repo is written to enforce. `sync` acted on the collapsed verdict
    by deleting and re-adding, so an unreadable notebook was answered by emptying
    it.
    """

    __slots__ = ("why",)

    def __init__(self, why: str):
        self.why = why


def notebook_stamps() -> dict:
    """Ask the notebook what it actually holds.

    title -> stamp, or `None` when the copy carries none, or `Unread` when the
    copy could not be read.
    """
    r = nlm("source", "list", "--json")
    if r.returncode != 0:
        sys.exit("source list failed:\n" + (r.stderr or r.stdout))
    payload = json.loads(r.stdout)
    sources = payload.get("sources", payload) if isinstance(payload, dict) else payload
    out = {}
    with tempfile.TemporaryDirectory() as td:
        for s in sources:
            dst = Path(td) / (s["id"] + ".txt")
            g = nlm("source", "fulltext", s["id"], "-o", str(dst), "--force")
            if g.returncode != 0 or not dst.exists():
                out[s["title"]] = Unread(
                    (g.stderr or g.stdout or "no output").strip().splitlines()[0][:120]
                    if (g.stderr or g.stdout) else "the copy came back empty")
                continue
            # Strip every separator: extraction may wrap or space out the hex.
            blob = re.sub(r"[^0-9a-zA-Z]", "",
                          dst.read_text(encoding="utf-8", errors="replace"))
            m = STAMP_RE.search(blob)
            out[s["title"]] = m.group(1) if m else None
    return out


def git_state(repo: Path):
    run(["git", "-C", str(repo), "fetch", "--quiet"], timeout=300)
    head = run(["git", "-C", str(repo), "rev-parse", "--short", "HEAD"]).stdout.strip()
    behind = run(["git", "-C", str(repo), "rev-list", "--count", "HEAD..@{u}"]).stdout.strip()
    return head or "?", behind or "?"


# --------------------------------------------------------------------- verbs

def do_check(repo: Path):
    head, behind = git_state(repo)
    live = notebook_stamps()
    rows, drift = [], []
    for title, kind, target in manifest(repo):
        try:
            _, want = build(kind, target, repo)
        except FileNotFoundError as e:
            # A source the notebook holds but the clone does not. Untracked on
            # the machine that uploaded it, most likely; say so instead of dying.
            rows.append((title, "NO-UPSTREAM", "absent from the clone: %s"
                         % Path(getattr(e, "filename", target)).name))
            drift.append((title, "NO-UPSTREAM", "absent from the clone"))
            continue
        got = live.get(title)
        if title not in live:
            verdict, why = "MISSING", "not in the notebook"
        elif isinstance(got, Unread):
            verdict, why = "UNREAD", "could not read the notebook's copy: %s" % got.why
        elif got is None:
            verdict, why = "UNSTAMPED", "notebook copy carries no stamp"
        elif got != want:
            verdict, why = "STALE", "notebook %s != repo %s" % (got[:12], want[:12])
        else:
            verdict, why = "OK", want[:12]
        rows.append((title, verdict, why))
        if verdict != "OK":
            drift.append((title, verdict, why))

    print("repo %s  HEAD %s  behind origin: %s" % (repo, head, behind))
    if behind not in ("0", "?"):
        print("  ! clone is %s commit(s) behind origin - pull before trusting this" % behind)
    width = max(len(t) for t, _, _ in rows)
    for t, v, why in rows:
        print("  %-9s %-*s  %s" % (v, width, t, why))
    print("\n%d/%d sources match the repo" % (len(rows) - len(drift), len(rows)))
    return drift


def do_sync(repo: Path) -> int:
    drift = do_check(repo)
    if not drift:
        print("\nnothing to sync")
        return 0

    print("\nre-uploading %d source(s)" % len(drift))
    spec = {t: (k, p) for t, k, p in manifest(repo)}
    with tempfile.TemporaryDirectory() as td:
        for title, verdict, _ in drift:
            if verdict == "NO-UPSTREAM":
                print("  skipped  %s: nothing in the clone to upload" % title)
                continue
            if verdict == "UNREAD":
                # Nothing is known about this copy, so replacing it would be a
                # remedy for a failure to look. The verdict stands and `check`
                # still exits 1; a human decides after reading why.
                print("  skipped  %s: its copy could not be read, so there is "
                      "nothing to conclude about it" % title)
                continue
            kind, target = spec[title]
            text, stamp = build(kind, target, repo)
            safe = re.sub(r"[^A-Za-z0-9]+", "-", title).strip("-").lower()
            path = Path(td) / (safe + ".md")
            path.write_text(text, encoding="utf-8", newline="\n")
            if verdict != "MISSING":
                # Checked, because an unchecked delete followed by an add leaves
                # two sources under one title when it fails, and the notebook
                # then answers from whichever it likes.
                d = nlm("source", "delete-by-title", title, "--yes")
                if d.returncode != 0:
                    print("  FAILED   %s: the old copy could not be removed, so the "
                          "new one was not added: %s"
                          % (title, (d.stderr or d.stdout).strip()[:160]))
                    continue
            r = nlm("source", "add", str(path), "--type", "file", "--timeout", "300")
            if r.returncode != 0:
                print("  FAILED   %s: %s" % (title, (r.stderr or r.stdout).strip()[:200]))
                continue
            m = re.search(r"[0-9a-f]{8}-[0-9a-f-]{27}", r.stdout)
            if m:
                nlm("source", "rename", m.group(0), title)
            print("  uploaded %s  %s" % (title, stamp[:12]))

    print("\nre-checking through the notebook")
    return 1 if do_check(repo) else 0


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("verb", choices=["check", "sync"])
    p.add_argument("--repo", type=Path, default=REPO,
                   help="clone to compare against (default: the one holding this script)")
    p.add_argument("--notebook", help="notebook id (default: $SEO_NOTEBOOK_ID)")
    p.add_argument("--cli", help="notebooklm executable (default: $SEO_NOTEBOOK_CLI or PATH)")
    a = p.parse_args()
    if not (a.repo / CHECKLIST_JSON).exists():
        sys.exit("not a seo-checklist clone: %s" % a.repo)
    CONFIG["cli"] = resolve_cli(a.cli)
    CONFIG["notebook"] = resolve_notebook(a.notebook)
    if a.verb == "check":
        return 1 if do_check(a.repo) else 0
    return do_sync(a.repo)


if __name__ == "__main__":
    sys.exit(main())
