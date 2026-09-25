#!/usr/bin/env python3
"""How much of the headline score is the site, and how much is the weight table.

`SEVERITY_WEIGHT` — critical 10, high 6, medium 3, low 1 — decides the SEO Score,
and `EFFORT_COST` — low 1, medium 2, high 4 — divides it to order the fix list.
Both arrived with borrowed code, neither has been examined here, and their own
`# basis:` lines say `inherited`. The score has been reported to two significant
figures the whole time.

**This does not calibrate them, and calibrating them is not the next step.** A
weight table says how much a critical item matters relative to a low one, and
nothing available here can measure that — it would need outcome data, ranking
against traffic on real properties over time. What *can* be measured today is
whether the answer matters at all: re-score real runs under a spread of plausible
tables and look at how far the headline moves.

Two outcomes, and both close the question:

- **The spread is small.** The table is not doing the work the worry assumed, that
  gets written down, and nobody has to buy outcome data to justify a number that
  turns out not to swing.
- **The spread is large.** The headline is substantially an artifact of a number
  nobody here chose, and it must either be calibrated or stop being the headline.

The diagnostic that explains either answer is the **per-severity pass rate**. A
weighted mean only diverges from an unweighted one when the groups differ, so if a
site passes its critical and its low items at the same rate, no weighting can move
the score and the table is decoration on that run. The spread is the symptom; the
pass-rate table is the cause.

    python3 tools/audit_score_sensitivity.py run.json [run2.json ...]

Reads the artifacts a normal audit already writes. Nothing here re-runs a check.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "scripts")
sys.path.insert(0, SCRIPTS)

from checklist_report import EFFORT_COST  # noqa: E402
from checklist_runner import (FAIL, PASS, SEVERITIES, SEVERITY_WEIGHT,  # noqa: E402
                              VERDICTS as DECIDED, WARN)

# The tables to try. Chosen to bracket what somebody could defend rather than to
# be exhaustive, and the two ends are the ones that carry the argument.
#
# `flat` is the null hypothesis: if the shipped table lands on the same number as
# no weighting at all, then severity weighting is not what produces the score.
# `powers of three` is the steepest curve anybody argues for. If the whole span
# from flat to steep fits inside a couple of points, the choice does not matter.
CANDIDATE_WEIGHTS = {
    "shipped (10/6/3/1)": {"critical": 10, "high": 6, "medium": 3, "low": 1},
    "flat (1/1/1/1)": {"critical": 1, "high": 1, "medium": 1, "low": 1},
    "gentle (8/5/3/1)": {"critical": 8, "high": 5, "medium": 3, "low": 1},
    "near-linear (4/3/2/1)": {"critical": 4, "high": 3, "medium": 2, "low": 1},
    "steep (27/9/3/1)": {"critical": 27, "high": 9, "medium": 3, "low": 1},
}

# The same question for the ordering table. `flat` is again the null hypothesis:
# if ranking by severity-per-effort picks the same work as ranking by severity
# alone, then dividing by effort is ceremony.
CANDIDATE_EFFORTS = {
    "shipped (1/2/4)": {"low": 1, "medium": 2, "high": 4},
    "flat (1/1/1)": {"low": 1, "medium": 1, "high": 1},
    "gentle (1/2/3)": {"low": 1, "medium": 2, "high": 3},
    "steep (1/3/9)": {"low": 1, "medium": 3, "high": 9},
}

# basis: presentation — how many rows of the fix list are compared between two
#  effort tables. Ten is what a person reads before deciding what to do this week,
#  so agreement further down is agreement about work nobody reached.
FIX_LIST_COMPARED = 10

from scope_line import print_scope  # noqa: E402

# What a passing run establishes, and what it does not (openspec/specs/governance/ GOV-6).
ESTABLISHES = (
    "how far the headline score and the head of the fix list move under the candidate "
    "weight and effort tables on the runs given, and the per-severity pass rates "
    "behind it"
)
DOES_NOT_ESTABLISH = (
    "which table is right, which needs outcome data this tool does not have, or that a "
    "small spread on these runs is a small spread on every site"
)



def scored_items(data: dict) -> list[dict]:
    return [i for i in data.get("items", []) if i.get("status") in DECIDED]


def headline(items: list[dict], weights: dict[str, int]) -> float | None:
    """The SEO Score, recomputed. Same arithmetic as `checklist_runner.score`."""
    earned = sum(weights.get(i["severity"], 1) *
                 (1.0 if i["status"] == PASS else 0.5 if i["status"] == WARN else 0.0)
                 for i in items)
    total = sum(weights.get(i["severity"], 1) for i in items)
    return round(100 * earned / total, 1) if total else None


def pass_rates(items: list[dict]) -> dict[str, tuple[int, float | None]]:
    """Credit earned per severity, as a rate. This is the cause; the spread below
    is only the symptom."""
    out = {}
    for sev in SEVERITIES:
        rows = [i for i in items if i["severity"] == sev]
        credit = sum(1.0 if i["status"] == PASS else 0.5 if i["status"] == WARN else 0.0
                     for i in rows)
        out[sev] = (len(rows), round(100 * credit / len(rows), 1) if rows else None)
    return out


def fix_order(items: list[dict], weights: dict[str, int],
              efforts: dict[str, int]) -> list[str]:
    """The fix list, ordered the way the report orders it."""
    actionable = [i for i in items if i["status"] in (FAIL, WARN)]
    return [i["id"] for i in sorted(
        actionable,
        key=lambda i: (-(weights.get(i["severity"], 1)
                         / efforts.get(i.get("effort", "medium"), 2)),
                       i["id"]))]


def report(paths: list[str]) -> int:
    runs = []
    for path in paths:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        items = scored_items(data)
        if not items:
            print(f"{os.path.basename(path)}: nothing decided; skipped")
            continue
        runs.append((os.path.basename(path), data, items))
    if not runs:
        print("no run had a decided item — nothing to be sensitive about")
        return 1

    print("SEVERITY_WEIGHT — what the headline does under other tables\n")
    header = f"{'run':<22}{'items':>6}  " + "".join(f"{n.split()[0]:>13}"
                                                    for n in CANDIDATE_WEIGHTS)
    print(header + f"{'spread':>9}")
    worst = 0.0
    for name, _data, items in runs:
        scores = [headline(items, w) for w in CANDIDATE_WEIGHTS.values()]
        spread = round(max(scores) - min(scores), 1)
        worst = max(worst, spread)
        print(f"{name:<22}{len(items):>6}  "
              + "".join(f"{s:>13}" for s in scores) + f"{spread:>9}")

    print("\nWhy — credit earned per severity, which is what a weighting can act on\n")
    print(f"{'run':<22}" + "".join(f"{s:>22}" for s in SEVERITIES) + f"{'range':>8}")
    for name, _data, items in runs:
        rates = pass_rates(items)
        cells = []
        for sev in SEVERITIES:
            n, rate = rates[sev]
            cells.append(f"{rate}% of {n}" if rate is not None else "—")
        # The driver, printed rather than left for the reader to infer. A weighted
        # mean can only differ from an unweighted one by as much as the groups
        # differ from each other, so this column and the spread column above move
        # together — and the item count does not explain either.
        seen = [r for _, r in rates.values() if r is not None]
        gap = round(max(seen) - min(seen), 1) if seen else 0
        print(f"{name:<22}" + "".join(f"{c:>22}" for c in cells) + f"{gap:>8}")

    print("\nEFFORT_COST — the first "
          f"{FIX_LIST_COMPARED} of the fix list under other tables\n")
    print(f"{'run':<22}{'to fix':>8}  " + "".join(f"{n.split()[0]:>12}"
                                                  for n in CANDIDATE_EFFORTS))
    for name, _data, items in runs:
        base = fix_order(items, SEVERITY_WEIGHT, EFFORT_COST)[:FIX_LIST_COMPARED]
        cells = []
        for efforts in CANDIDATE_EFFORTS.values():
            other = fix_order(items, SEVERITY_WEIGHT, efforts)[:FIX_LIST_COMPARED]
            shared = len(set(base) & set(other))
            cells.append(f"{shared}/{len(base)}" if base else "—")
        total_actionable = len([i for i in items if i["status"] in (FAIL, WARN)])
        print(f"{name:<22}{total_actionable:>8}  " + "".join(f"{c:>12}" for c in cells))

    print(f"\nWidest headline spread across every table and run: {worst} point(s).")
    print("Read it against the range column above, not against the item count: the "
          "table moves the score exactly as far as severity discriminates on that "
          "site, and a site whose critical items are the broken ones is the case "
          "where it moves most.")
    print_scope(ESTABLISHES, DOES_NOT_ESTABLISH)
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Re-score finished runs under other severity and effort tables.")
    ap.add_argument("results", nargs="+", help="checklist-results.json file(s)")
    args = ap.parse_args()
    raise SystemExit(report(args.results))


if __name__ == "__main__":
    main()
