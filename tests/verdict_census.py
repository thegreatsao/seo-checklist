#!/usr/bin/env python3
"""What every item actually reports, across every site we can serve.

Not a test and not an oracle. The fixture oracle answers "is this verdict right",
one declaration at a time, and it has declared 122 of 217 items. This answers a
different and cheaper question — **what range of answers does this item have at all**
— and it answers it for all 217 at once.

The question matters because a rule that cannot fail looks exactly like a rule that
always holds, and both look like a green suite. `KW-076` asserted a field its script
wrote only when it already held something, so it reported PASS or NO_DATA for years.
`MD-184` asserts `count >= 1` over a script that omits `count` when a page has no
images, so it reports PASS or NO_DATA and never FAIL — found by hand on 2026-08-16,
after three releases of looking for that shape one item at a time.

A census does not know which answer is right. It knows which answers were ever
given, and an item that gave one answer on every site anybody has served is worth a
person's attention. Read the report as a list of questions, not findings.

    python tests/verdict_census.py                 # serve every corpus site, tabulate
    python tests/verdict_census.py --out FILE      # also write the JSON record
    python tests/verdict_census.py --check FILE    # exit 1 if the record is stale

Each site is served over loopback and audited exactly as the oracle audits its
fixtures, so the numbers here and the numbers there come from the same path.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "skills", "seo-checklist", "scripts")
REGISTRY = os.path.join(ROOT, "skills", "seo-checklist", "resources", "config",
                        "checklist.json")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import (PLACEHOLDER, FixtureSite, _Site, across_runs,  # noqa: E402
                     offline_env, spawn, substitute)

# The operator-supplied inputs, exactly as the fixture oracle hands them over. The
# first census run omitted these and reported 43 items as "never answered on any
# site" — a statement about the instrument, not about the registry: `rendered_audit`,
# `cwv_metrics`, `gsc_links_csv` and `server_log_audit` answer only when their file is
# supplied, and the fixture tree ships all four. A census that leaves an input out
# measures its own harness.
ARTIFACT_FLAGS = (("--rendered-json", "rendered.json"),
                  ("--cwv-json", "cwv.json"),
                  ("--links-csv", "links"),
                  ("--server-log", "access.log"))

# Every tree this repository can serve. The two fixture trees are here for the same
# reason the corpus is: they are sites, and the census is about what items answer on
# sites. They are not the point — a tree written to make the checks fire cannot
# report a check that only real-world markup reaches — but they cost nothing to
# include and they anchor the table against the oracle's own numbers.
FIXTURES = os.path.join(ROOT, "tests", "fixtures")
CORPUS = os.path.join(ROOT, "tests", "corpus")
# A corpus tree's operator-supplied inputs, beside the trees rather than in them so they
# are never served: `_inputs/<tree>/` holds any of the `ARTIFACT_FLAGS` files,
# `indexnow_key` for the key an operator sets in INDEXNOW_KEY (F06), and a
# `*_standin.txt` for the address of each stand-in service the tree serves
# (`STANDIN_INPUTS`, F05-3 and F05-4). Without these the items that read an artifact or
# a key could answer on no corpus tree, which is the first census's mistake again: a
# statement about the instrument, not the registry.
INPUTS = os.path.join(CORPUS, "_inputs")
# Each `_inputs/<tree>/` file naming a stand-in the tree serves, and the variable the
# census hands it to the run as.
STANDIN_INPUTS = (("pagespeed_standin.txt", "SEO_PAGESPEED_STANDIN"),
                  ("validator_standin.txt", "SEO_VALIDATOR_STANDIN"),
                  ("safe_browsing_standin.txt", "SEO_SAFE_BROWSING_STANDIN"),
                  ("search_console_standin.txt", "SEO_SEARCH_CONSOLE_STANDIN"))
# Each `_inputs/<tree>/` file holding a value the operator types, and its runner flag:
# the Search Console property a staging copy is pointed at (F05-5), without which the
# runner sets Search Console aside on a host only this machine reaches.
VALUE_FLAGS = (("--gsc-property", "gsc_property.txt"),)

# The keyword an operator would supply. One word for every site, as an operator has
# one site in mind — see `test_fixture_oracle.KEYWORD` for why passing one at all had
# to wait for `--no-autocomplete`.
KEYWORD = "bread"


def corpus_sites() -> list[tuple[str, str]]:
    """(label, document root) for every corpus tree, which the fixtures are not."""
    found = []
    if os.path.isdir(CORPUS):
        for name in sorted(os.listdir(CORPUS)):
            path = os.path.join(CORPUS, name)
            if os.path.isdir(path) and os.path.isfile(os.path.join(path, "index.html")):
                found.append((name, path))
    return found


def corpus_inputs(label: str, base: str, workdir: str) -> tuple[list[str], dict]:
    """(runner flags, environment) for one corpus tree, staged and pointed at `base`."""
    source = os.path.join(INPUTS, label)
    if not os.path.isdir(source):
        return [], offline_env()
    staged = shutil.copytree(source, os.path.join(workdir, f"_inputs-{label}"))
    substitute(staged, PLACEHOLDER, base)
    flags = []
    for flag, filename in ARTIFACT_FLAGS:
        path = os.path.join(staged, filename)
        if os.path.exists(path):
            flags += [flag, path]
    for flag, filename in VALUE_FLAGS:
        path = os.path.join(staged, filename)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as stream:
                flags += [flag, stream.read().strip()]
    extra = {}
    key = os.path.join(staged, "indexnow_key")
    if os.path.exists(key):
        with open(key, encoding="utf-8") as stream:
            extra["INDEXNOW_KEY"] = stream.read().strip()
    # The address of each stand-in the tree serves, which its script asks instead of the
    # real service in a loopback-only process (F05-3, F05-4, F05-5).
    for filename, var in STANDIN_INPUTS:
        standin = os.path.join(staged, filename)
        if os.path.exists(standin):
            with open(standin, encoding="utf-8") as stream:
                extra[var] = stream.read().strip()
    return flags, offline_env(**extra)


def run_audit(url: str, out: str, env: dict,
              artifacts: list[str]) -> tuple[dict[str, str], bool]:
    """(status per item, whether the runner's entry gate let the run go on)."""
    proc = spawn(
        [sys.executable, os.path.join(SCRIPTS, "checklist_runner.py"), url,
         "--allow-private", "--sample", "3", "--max-rps", "0",
         "--no-history", "--no-prompt", "--quiet", "--timeout", "120",
         "--keyword", KEYWORD, "--json", out, *artifacts],
        env=env, timeout=900)
    if not os.path.exists(out):
        raise RuntimeError(f"no result file for {url}\n{proc.stderr[-2000:]}")
    with open(out, encoding="utf-8") as stream:
        data = json.load(stream)
    rows = data["items"]
    if isinstance(rows, dict):
        statuses = {item_id: row["status"] for item_id, row in rows.items()}
    else:
        statuses = {row["id"]: row["status"] for row in rows}
    return statuses, data["entry_reachable"]


def census(extra_sites) -> dict:
    with open(REGISTRY, encoding="utf-8") as stream:
        registry = json.load(stream)
    items = {i["id"]: i for i in registry["items"]}
    per_site = {}
    labels = []
    # The trees whose entry the runner's gate stopped. On those the gate writes the
    # FAIL of an `entry_answer` item without its assertion; everywhere else a FAIL is
    # the assertion's, which is what `audit_reachability` claims (F05-2).
    gated = []

    # The fixture trees go through `FixtureSite`, not through a bare server, so the
    # census sees exactly what the oracle sees: four origins, the TLS pair among them,
    # and every operator-supplied artifact staged and rewritten to the bound port.
    with FixtureSite() as site:
        for label in ("good", "broken", "good_tls", "broken_tls"):
            artifacts = []
            for flag, filename in ARTIFACT_FLAGS:
                path = site.artifact(label, filename)
                if path:
                    artifacts += [flag, path]
            print(f"  auditing fixture:{label}", file=sys.stderr)
            per_site[f"fixture:{label}"], reached = run_audit(
                getattr(site, label), os.path.join(site.dir, f"census-{label}.json"),
                site.environment(label), artifacts)
            labels.append(f"fixture:{label}")
            if not reached:
                gated.append(f"fixture:{label}")

    with tempfile.TemporaryDirectory(prefix="seo-census-") as workdir:
        for label, root in extra_sites:
            print(f"  auditing {label}", file=sys.stderr)
            served = _Site(root, os.path.join(workdir, label))
            try:
                artifacts, env = corpus_inputs(label, served.base, workdir)
                per_site[label], reached = run_audit(
                    served.base + "/", os.path.join(workdir, f"{label}.json"),
                    env, artifacts)
            finally:
                served.stop()
            labels.append(label)
            if not reached:
                gated.append(label)

    rows = {}
    for item_id, item in items.items():
        answers = {label: statuses.get(item_id, "MISSING")
                   for label, statuses in per_site.items()}
        rows[item_id] = {
            "title": item["title"],
            "severity": item["severity"],
            "source": item["source"],
            "script": (item.get("check") or {}).get("script"),
            "answers": answers,
            "distinct": sorted(set(answers.values())),
        }
    return {"registry_version": registry["registry_version"],
            "item_count": registry["item_count"],
            "sites": labels,
            "entry_gated": sorted(gated),
            "items": rows}


# Statuses that are a verdict about the site rather than a statement that nobody
# could answer. An item whose whole range is one of these, across every site, is
# either a rule that cannot say anything else or a question every site answers the
# same way — and the two are not distinguishable from here.
VERDICTS = {"PASS", "FAIL", "WARN"}


def verdict_groups(record: dict) -> tuple[set[str], set[str], set[str]]:
    """Script-backed ids that never fail, never pass, or never answer."""
    scripted = {k: v for k, v in record["items"].items()
                if v["source"] == "script"}
    never_failed = {
        k for k, row in scripted.items()
        if "FAIL" not in row["distinct"] and set(row["distinct"]) & VERDICTS
    }
    never_passed = {
        k for k, row in scripted.items()
        if "PASS" not in row["distinct"] and set(row["distinct"]) & VERDICTS
    }
    silent = {
        k for k, row in scripted.items()
        if not (set(row["distinct"]) & VERDICTS)
    }
    return never_failed, never_passed, silent


# What an item that answers on no tree here would need, named per script — and, for the
# one script whose items need different services, per the field the item reads (F06).
# Only an item the runner itself withholds from a host only we can reach
# (`checklist_runner.NEEDS_THE_OUTSIDE_WORLD`, read off its `requires`) can carry one:
# an item outside that gate that never answers could answer offline, so it is a defect,
# and `test_census` fails on it rather than reading a reason here.
EXTERNAL_INPUT = {
    "gsc_url_inspection.py": "Search Console URL Inspection for a verified property",
    "gsc_checker.py": "Search Console for a verified property",
    "gsc_sitemap_reconcile.py": "Search Console's sitemap report for a verified property",
    "gsc_cannibalization.py": "Search Console search analytics for a verified property",
    "pagespeed.py": "PageSpeed Insights, which loads the URL from Google's network",
    "html_validator.py": "the W3C Nu HTML Checker, a service on the public internet",
    "domain_safety_check.py:safe_browsing": "a Google Safe Browsing API key",
    "domain_safety_check.py:whois": "whois, which asks a registry on the public internet "
                                    "about a registered domain",
    "domain_safety_check.py:neighbors": "a paid reverse-IP service this project does not "
                                        "buy (check.cannot_fail)",
}


def external_input(item: dict) -> str | None:
    """The input no served tree can supply, or None when the item could answer here."""
    if SCRIPTS not in sys.path:
        sys.path.insert(0, SCRIPTS)
    from checklist_runner import NEEDS_THE_OUTSIDE_WORLD
    check = item.get("check") or {}
    if check.get("requires", "fetch") not in NEEDS_THE_OUTSIDE_WORLD:
        return None
    path = str((check.get("assert") or {}).get("path") or "")
    script = check.get("script") or ""
    return (EXTERNAL_INPUT.get(f"{script}:{path.split('.')[0]}")
            or EXTERNAL_INPUT.get(script))


def unexercisable() -> list[str]:
    """The ids the corpus README names as unable to fail on any tree here (DEC-13).

    Read from the README rather than kept here, because the README is where the reason
    is written, and a second list would be the drift DEC-6 objects to."""
    import re
    with open(os.path.join(CORPUS, "README.md"), encoding="utf-8") as stream:
        text = stream.read()
    start = text.index("## What a corpus tree can and cannot express")
    end = text.find("\n## ", start + 1)
    section = text[start:end if end != -1 else len(text)]
    return sorted(set(re.findall(r"`([A-Z]{2,4}-\d+)`", section)))


def report(record: dict) -> list[str]:
    lines = []
    rows = record["items"]
    scripted = {k: v for k, v in rows.items() if v["source"] == "script"}
    lines.append(f"{len(rows)} items over {len(record['sites'])} site(s): "
                 f"{', '.join(record['sites'])}")
    lines.append(f"{len(scripted)} are script-backed; the rest are answered by a "
                 f"human, an agent or Search Console and cannot be censused this way.")

    with open(REGISTRY, encoding="utf-8") as stream:
        registry = {i["id"]: i for i in json.load(stream)["items"]}
    limited = set(unexercisable())

    def group(ids, heading, why=None):
        hits = {k: v for k, v in scripted.items() if k in ids}
        lines.append("")
        lines.append(f"== {heading}: {len(hits)}")
        for item_id, row in sorted(hits.items()):
            lines.append(f"  {item_id} ({row['severity']:<8}) {row['title']}")
            lines.append(f"      {row['script']}  ->  "
                         f"{', '.join(row['distinct'])}")
            reason = why(item_id) if why else None
            if reason:
                lines.append(f"      {reason}")
        return set(hits)

    def cannot_fail_here(item_id):
        if item_id in limited:
            return ("no tree here can show this failing: tests/corpus/README.md, "
                    "'What a corpus tree can and cannot express'")
        return None

    def needs(item_id):
        found = external_input(registry[item_id]) if item_id in registry else None
        return (f"needs {found}" if found
                else "COULD ANSWER HERE AND DID NOT: no external input is named for it")

    never_failed_ids, never_passed_ids, silent_ids = verdict_groups(record)
    never_failed = group(never_failed_ids, "answered somewhere and never FAIL",
                         cannot_fail_here)
    never_passed = group(never_passed_ids, "answered somewhere and never PASS")
    silent = group(silent_ids, "never answered on any site", needs)
    lines.append("")
    lines.append(f"{len(never_failed)} could not be seen failing, "
                 f"{len(never_passed)} could not be seen passing, "
                 f"{len(silent)} never answered at all. None of those is a finding "
                 f"on its own — a small corpus makes all three larger than they are.")
    return lines


def as_held(record: dict) -> dict:
    """`record` as a census taken on another machine, or at another hour, can hold it.

    The record says what each item answered where it was recorded, in the audit's
    own words. For an item whose band is a time the run measured that word is the
    recording machine's (`harness.CLOCK_READ`): with every time to first byte five
    seconds longer `--check` refused a tree nothing was wrong with. So two records
    are compared on such an answer as far as that the item was timed — except on a
    tree that holds its first byte back past the budget (`harness.
    SLOW_BY_CONSTRUCTION`), where the answer is the tree's and is held exactly.
    """
    held = json.loads(json.dumps(record, sort_keys=True))
    for item_id, row in held["items"].items():
        row["answers"] = {site: across_runs(item_id, answer, site)
                          for site, answer in row["answers"].items()}
        row["distinct"] = sorted(set(row["answers"].values()))
    return held


def in_step(stored: dict, fresh: dict) -> bool:
    return as_held(stored) == as_held(fresh)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", help="write the JSON record here")
    ap.add_argument("--check", help="compare against this record and exit 1 on drift")
    args = ap.parse_args()

    record = census(corpus_sites())
    print("\n".join(report(record)))

    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(record, stream, indent=2, ensure_ascii=False, sort_keys=True)
            stream.write("\n")
        print(f"\nwrote {args.out}")
    if args.check:
        with open(args.check, encoding="utf-8") as stream:
            stored = json.load(stream)
        if not in_step(stored, record):
            print(f"\n{args.check} is out of step with a fresh census", file=sys.stderr)
            return 1
        print(f"\n{args.check} is in step")
    return 0


if __name__ == "__main__":
    sys.exit(main())
