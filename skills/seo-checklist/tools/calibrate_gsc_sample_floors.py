#!/usr/bin/env python3
"""Calibrate Search Console CTR sample floors with binomial precision.

    python3 tools/calibrate_gsc_sample_floors.py
    python3 tools/calibrate_gsc_sample_floors.py --check

Both modes are offline. The default command derives a report from literal constants;
``--check`` compares the committed report with those constants and rechecks its
arithmetic. No corpus, credentials, property identifier, query or URL is read.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

from calibration_common import literal_constants


HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
SCRIPTS = os.path.join(SKILL_DIR, "scripts")
REPORT = os.path.join(HERE, "calibration", "gsc-sample-floors.json")

Z_SCORE = 1.96
CONFIDENCE_LEVEL_PCT = 95
TABLE_IMPRESSIONS = (10, 50, 100, 200, 500, 1000)
PAIRS = (
    {
        "name": "top-position-low-ctr",
        "script": "gsc_checker.py",
        "threshold_constant": "LOW_CTR_PCT",
        "floor_constant": "LOW_CTR_MIN_IMPRESSIONS",
    },
    {
        "name": "high-impressions-very-low-ctr",
        "script": "gsc_checker.py",
        "threshold_constant": "VERY_LOW_CTR_PCT",
        "floor_constant": "HIGH_IMPRESSIONS",
    },
)
UNCALIBRATED_FLOORS = (
    {
        "script": "gsc_checker.py",
        "constant": "STRIKING_DISTANCE_MIN_IMPRESSIONS",
        "reference_threshold_pct": 5,
        "reason": (
            "gates average position rather than CTR; binomial precision does not "
            "calibrate it"
        ),
    },
    {
        "script": "gsc_cannibalization.py",
        "constant": "MIN_IMPRESSIONS",
        "reference_threshold_pct": 5,
        "reason": (
            "gates per-page evidence for a multi-page pattern rather than a CTR "
            "comparison; the 5 percent column is illustrative only"
        ),
    },
)


def _literal_constants(script_name: str, names: set[str]) -> dict[str, int | float]:
    return literal_constants(os.path.join(SCRIPTS, script_name), names,
                             f"could not read {script_name} constants: {{missing}}")


def _constants() -> dict[str, dict[str, int | float]]:
    wanted: dict[str, set[str]] = {}
    for pair in PAIRS:
        wanted.setdefault(pair["script"], set()).update(
            (pair["threshold_constant"], pair["floor_constant"])
        )
    for floor in UNCALIBRATED_FLOORS:
        wanted.setdefault(floor["script"], set()).add(floor["constant"])
    return {script: _literal_constants(script, names)
            for script, names in wanted.items()}


def ci_half_width(threshold_fraction: float, impressions: int) -> float:
    return Z_SCORE * math.sqrt(
        threshold_fraction * (1 - threshold_fraction) / impressions
    )


def required_minimum(threshold_fraction: float) -> int:
    raw = ((Z_SCORE / threshold_fraction) ** 2
           * threshold_fraction * (1 - threshold_fraction))
    return math.ceil(raw)


def _rounded(value: float) -> float:
    return round(value, 6)


def build_report() -> dict:
    constants = _constants()
    pairs = []
    thresholds = []
    for spec in PAIRS:
        script_constants = constants[spec["script"]]
        threshold_pct = script_constants[spec["threshold_constant"]]
        floor = script_constants[spec["floor_constant"]]
        threshold_fraction = threshold_pct / 100
        minimum = required_minimum(threshold_fraction)
        pairs.append({
            **spec,
            "threshold_pct": threshold_pct,
            "threshold_fraction": threshold_fraction,
            "floor_impressions": floor,
            "required_minimum_impressions": minimum,
            "headroom_impressions": floor - minimum,
            "delivered_ci_half_width_fraction": _rounded(
                ci_half_width(threshold_fraction, floor)),
            "delivered_ci_half_width_percentage_points": _rounded(
                ci_half_width(threshold_fraction, floor) * 100),
            "satisfies_precision_rule": floor >= minimum,
        })
        thresholds.append(threshold_pct)

    uncalibrated = []
    roles_by_impressions: dict[int, list[str]] = {}
    for spec in UNCALIBRATED_FLOORS:
        floor = constants[spec["script"]][spec["constant"]]
        reference_fraction = spec["reference_threshold_pct"] / 100
        uncalibrated.append({
            **spec,
            "floor_impressions": floor,
            "illustrative_ci_half_width_percentage_points": _rounded(
                ci_half_width(reference_fraction, floor) * 100),
            "status": "not_calibrated_by_this_method",
        })
        roles_by_impressions.setdefault(floor, []).append(
            f"{spec['script']}:{spec['constant']} (uncalibrated)"
        )
    for pair in pairs:
        roles_by_impressions.setdefault(pair["floor_impressions"], []).append(
            f"{pair['script']}:{pair['floor_constant']} (calibrated)"
        )

    table = []
    for impressions in TABLE_IMPRESSIONS:
        table.append({
            "impressions": impressions,
            "constant_roles": roles_by_impressions.get(impressions, []),
            "ci_half_width_percentage_points": {
                str(threshold_pct): _rounded(
                    ci_half_width(threshold_pct / 100, impressions) * 100)
                for threshold_pct in sorted(set(thresholds), reverse=True)
            },
        })

    return {
        "precision_rule": {
            "name": "ci_half_width_not_greater_than_tested_ctr_threshold",
            "confidence_level_pct": CONFIDENCE_LEVEL_PCT,
            "z_score": Z_SCORE,
            "model": "normal-approximation binomial proportion interval",
            "half_width_formula": "z * sqrt(p * (1 - p) / n)",
            "minimum_formula": "ceil((z / p)^2 * p * (1 - p))",
            "requirement": (
                "The 95% confidence interval half-width on measured CTR must not "
                "exceed the threshold being tested."
            ),
        },
        "pairs": pairs,
        "uncalibrated_floors": uncalibrated,
        "half_width_table": table,
        "privacy": (
            "Arithmetic only: no property, query, URL, page path, client name, "
            "credential or private corpus is an input."
        ),
    }


def write_report() -> int:
    report = build_report()
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(f"wrote {REPORT}: {len(report['pairs'])} calibrated CTR floors")
    return 0


def check_report() -> int:
    try:
        with open(REPORT, encoding="utf-8") as fh:
            report = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"unreadable calibration report: {exc}", file=sys.stderr)
        return 1

    current = build_report()
    failed = report != current
    if failed:
        print("committed GSC calibration report differs from declared constants or arithmetic",
              file=sys.stderr)
    report_pairs = {row.get("floor_constant"): row for row in report.get("pairs", [])}
    current_pairs = {row["floor_constant"]: row for row in current["pairs"]}
    for name, actual in current_pairs.items():
        expected = report_pairs.get(name, {})
        agrees = expected == actual
        print(f"{name}: constant={actual['floor_impressions']}; "
              f"report={expected.get('floor_impressions')}; "
              f"required={actual['required_minimum_impressions']}; "
              f"agree={'yes' if agrees else 'no'}")
    return int(failed)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true",
                        help="compare the committed report with constants; offline")
    args = parser.parse_args()
    return check_report() if args.check else write_report()


if __name__ == "__main__":
    sys.exit(main())
