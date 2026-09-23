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
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "skills", "seo-checklist", "scripts")
REGISTRY = os.path.join(ROOT, "skills", "seo-checklist", "resources", "config",
                        "checklist.json")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import FixtureSite, _Site, offline_env, spawn  # noqa: E402

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


def run_audit(url: str, out: str, env: dict, artifacts: list[str]) -> dict[str, str]:
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
        return {item_id: row["status"] for item_id, row in rows.items()}
    return {row["id"]: row["status"] for row in rows}


def census(extra_sites) -> dict:
    with open(REGISTRY, encoding="utf-8") as stream:
        registry = json.load(stream)
    items = {i["id"]: i for i in registry["items"]}
    per_site = {}
    labels = []

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
            per_site[f"fixture:{label}"] = run_audit(
                getattr(site, label), os.path.join(site.dir, f"census-{label}.json"),
                site.environment(label), artifacts)
            labels.append(f"fixture:{label}")

    with tempfile.TemporaryDirectory(prefix="seo-census-") as workdir:
        for label, root in extra_sites:
            print(f"  auditing {label}", file=sys.stderr)
            served = _Site(root, os.path.join(workdir, label))
            try:
                per_site[label] = run_audit(
                    served.base + "/", os.path.join(workdir, f"{label}.json"),
                    offline_env(), [])
            finally:
                served.stop()
            labels.append(label)

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


def report(record: dict) -> list[str]:
    lines = []
    rows = record["items"]
    scripted = {k: v for k, v in rows.items() if v["source"] == "script"}
    lines.append(f"{len(rows)} items over {len(record['sites'])} site(s): "
                 f"{', '.join(record['sites'])}")
    lines.append(f"{len(scripted)} are script-backed; the rest are answered by a "
                 f"human, an agent or Search Console and cannot be censused this way.")

    def group(ids, heading):
        hits = {k: v for k, v in scripted.items() if k in ids}
        lines.append("")
        lines.append(f"== {heading}: {len(hits)}")
        for item_id, row in sorted(hits.items()):
            lines.append(f"  {item_id} ({row['severity']:<8}) {row['title']}")
            lines.append(f"      {row['script']}  ->  "
                         f"{', '.join(row['distinct'])}")
        return set(hits)

    never_failed_ids, never_passed_ids, silent_ids = verdict_groups(record)
    never_failed = group(never_failed_ids, "answered somewhere and never FAIL")
    never_passed = group(never_passed_ids, "answered somewhere and never PASS")
    silent = group(silent_ids, "never answered on any site")
    lines.append("")
    lines.append(f"{len(never_failed)} could not be seen failing, "
                 f"{len(never_passed)} could not be seen passing, "
                 f"{len(silent)} never answered at all. None of those is a finding "
                 f"on its own — a small corpus makes all three larger than they are.")
    return lines


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
        if stored != json.loads(json.dumps(record, sort_keys=True)):
            print(f"\n{args.check} is out of step with a fresh census", file=sys.stderr)
            return 1
        print(f"\n{args.check} is in step")
    return 0


if __name__ == "__main__":
    sys.exit(main())
