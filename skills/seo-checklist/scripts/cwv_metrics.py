#!/usr/bin/env python3
"""Read Core Web Vitals measured locally from a browser trace.

This script measures nothing. It reads a small JSON file that a trace produced —
in Claude Code, the chrome-devtools MCP: start a performance trace, reload the
page, stop it, and write the numbers out in the shape below. The runner then
treats them like any other evidence, so the registry decides and the report
explains, with no new judgement path.

    {
      "url": "https://example.com/",
      "lcp_ms": 2100,
      "cls": 0.04,
      "tbt_ms": 150,
      "source": "chrome-devtools MCP trace, desktop, 2026-08-03"
    }

Why a file rather than a call: an MCP tool is available to the agent, not to a
subprocess, and a run must be reproducible from its artifacts. The file is the
artifact — it says where the numbers came from, and `--cwv-json` makes the
measurement an explicit act rather than something that silently did or did not
happen.

**This is lab data, and the registry keeps it apart from field data on purpose.**
CrUX (via pagespeed.py) reports what real visitors experienced and is the better
evidence whenever it exists; it simply does not exist for low-traffic URLs, which
is when a controlled local run is the only measurement available. Merging the two
would make one number out of two different claims — exactly what this tool exists
not to do.

Units are required to be explicit. A bare `lcp` of 2.1 could be seconds or
milliseconds, and guessing wrong turns a failing page into a passing one, so the
keys are `lcp_ms`, `tbt_ms`, and unitless `cls`. A missing metric is left out of
the output entirely, which the runner reads as NO_DATA rather than as a pass.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

# Google's "good" thresholds. TBT is a lab stand-in for INP: INP needs a real
# interaction and cannot be measured from a page load at all, so it is named for
# what it is rather than reported as INP.
# basis: standard — Google's published Core Web Vitals bands (LCP 2.5s/4s, CLS
#  0.1/0.25). TBT is a lab stand-in for INP and its 200ms/600ms come from Lighthouse's
#  own scoring, not from a field metric — named as TBT for that reason
THRESHOLDS = {
    "lcp_ms": {"good": 2500, "poor": 4000},
    "cls": {"good": 0.1, "poor": 0.25},
    "tbt_ms": {"good": 200, "poor": 600},
}

METRIC_KEYS = tuple(THRESHOLDS)


def rating(metric: str, value: float) -> str:
    limits = THRESHOLDS[metric]
    if value <= limits["good"]:
        return "good"
    return "needs_improvement" if value <= limits["poor"] else "poor"


def read(path: str) -> dict:
    """Parse the trace file. Raises ValueError with something actionable."""
    if not os.path.exists(path):
        raise ValueError(f"no such file: {path}")
    with open(path, encoding="utf-8") as f:
        try:
            raw = json.load(f)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path} is not JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must hold a JSON object, found {type(raw).__name__}")
    # One level of nesting is tolerated because a trace exporter naturally groups
    # them; nothing else is guessed at.
    metrics = raw.get("metrics") if isinstance(raw.get("metrics"), dict) else raw

    out = {
        "url": raw.get("url") or metrics.get("url"),
        "source": raw.get("source") or metrics.get("source") or "unspecified",
        "measured": [],
        "missing": [],
    }
    for key in METRIC_KEYS:
        value = metrics.get(key)
        if value is None:
            out["missing"].append(key)
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{key} must be a number, found {value!r}. Units are "
                             f"part of the key name: lcp_ms and tbt_ms in "
                             f"milliseconds, cls unitless.")
        if value < 0:
            raise ValueError(f"{key} is negative ({value})")
        # Absent, not zero: a metric nobody measured must not read as a perfect
        # score. The runner reports the item NO_DATA when the key is not there.
        out[key] = value
        out[f"{key}_rating"] = rating(key, value)
        out["measured"].append(key)

    if not out["measured"]:
        raise ValueError(f"{path} carries none of {', '.join(METRIC_KEYS)}")
    out["all_good"] = all(out.get(f"{k}_rating") == "good" for k in out["measured"])
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Report locally traced Core Web Vitals",
                                 epilog=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", help="JSON file written from a browser performance trace")
    ap.add_argument("--json", "-j", action="store_true")
    a = ap.parse_args()

    try:
        result = read(a.path)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1

    if a.json:
        print(json.dumps(result, indent=2))
        return 0

    print(f"Core Web Vitals (lab) for {result['url'] or 'unknown URL'}")
    print(f"  source: {result['source']}")
    for key in result["measured"]:
        print(f"  {key:8} {result[key]:<10} {result[f'{key}_rating']}")
    for key in result["missing"]:
        print(f"  {key:8} not measured")
    return 0


if __name__ == "__main__":
    from lib.utf8_streams import utf8_streams
    utf8_streams()
    sys.exit(main())
