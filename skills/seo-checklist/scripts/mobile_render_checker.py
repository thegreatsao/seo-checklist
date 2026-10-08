#!/usr/bin/env python3
"""Check mobile rendering risks in static HTML."""

from __future__ import annotations

import argparse
import json
import re
import sys

try:
    from seo_common import load_html, parse_html
except ImportError:
    from scripts.seo_common import load_html, parse_html

# basis: inherited — 390 CSS pixels, present at import. The viewport width of the
#  iPhone 14/15 class of device, so a fixed width above it guarantees a horizontal
#  scrollbar on the commonest phone; it is a device fact rather than a judgement, but
#  which device is the judgement.
MAX_FIXED_WIDTH_PX = 390

def _static_checks(source: str, timeout: int = 15) -> dict:
    html, final_url, fetched = load_html(source, timeout=timeout)
    parsed = parse_html(html, final_url)
    # `seo_common.parse_html` returns `viewport` at the top level; there is no
    # `meta` dict and never was, so this read `""` on every page ever audited and
    # reported a missing viewport at `critical` severity for all of them. A
    # fabricated FAIL rather than a fabricated PASS, which is why nobody noticed:
    # the item looked strict, not broken.
    viewport = parsed.get("viewport") or ""
    text = re.sub(r"\s+", " ", html or "")

    issues = []
    if "width=device-width" not in viewport.lower():
        issues.append({
            "severity": "critical",
            "finding": "Missing or incomplete viewport meta tag.",
            "fix": "Add `<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">`.",
        })

    # This used to match max-width; an inert finding hid the false positive, and
    # letting the finding decide is what surfaced it.
    fixed_width_hits = re.findall(
        r"(?<![-\w])(?:min-width|width)\s*:\s*(\d{3,})px", text, flags=re.I)
    wide_values = [int(value) for value in fixed_width_hits if int(value) > MAX_FIXED_WIDTH_PX]
    if wide_values:
        issues.append({
            "severity": "warning",
            "finding": f"Found {len(wide_values)} fixed-width CSS declarations wider than common mobile viewports.",
            "fix": "Replace fixed widths with responsive max-width, min(), clamp(), grid, or flex constraints.",
        })

    sticky_hits = len(re.findall(r"position\s*:\s*(fixed|sticky)", text, flags=re.I))
    if sticky_hits:
        issues.append({
            "severity": "info",
            "finding": f"Found {sticky_hits} fixed/sticky positioning declaration(s).",
            "fix": "Verify sticky headers, banners, and chat widgets do not cover mobile content or CTAs.",
        })

    return {
        "source": source,
        "url": final_url or source,
        "fetch": fetched,
        # "Missing viewport meta tag" is a `critical` finding, and it was being made
        # about pages that were never fetched: no HTML means no viewport tag either
        # way. MB-100 reported a critical mobile defect for a refused connection.
        "fetch_error": fetched.get("error"),
        "viewport_meta": viewport,
        "fixed_width_values": wide_values[:25],
        "sticky_position_count": sticky_hits,
        "rendered": None,
        "issues": issues,
    }


def check_mobile_render(source: str, timeout: int = 15) -> dict:
    report = _static_checks(source, timeout=timeout)
    report["summary"] = {
        "issues": len(report["issues"]),
        "critical": sum(1 for issue in report["issues"] if issue["severity"] == "critical"),
        "warning": sum(1 for issue in report["issues"] if issue["severity"] == "warning"),
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Check mobile rendering risks")
    parser.add_argument("source", help="URL or local HTML file")
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument("--json", "-j", action="store_true")
    args = parser.parse_args()

    report = check_mobile_render(args.source, timeout=args.timeout)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"Mobile render issues: {report['summary']['issues']}")
        for issue in report["issues"]:
            print(f"- [{issue['severity']}] {issue['finding']}")
    return 0


if __name__ == "__main__":
    from lib.utf8_streams import utf8_streams
    utf8_streams()
    sys.exit(main())
