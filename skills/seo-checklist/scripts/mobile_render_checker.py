#!/usr/bin/env python3
"""Check mobile rendering risks in static HTML."""

from __future__ import annotations

try:
    from lib import python_floor  # noqa: F401
except ImportError:
    from scripts.lib import python_floor  # noqa: F401

import argparse
import json
import re
import sys

try:
    from seo_common import read_source, load_html, parse_html
except ImportError:
    from scripts.seo_common import read_source, load_html, parse_html

# basis: measured — corpus=tools/calibration/mobile-viewport.json (StatCounter worldwide mobile screen resolutions, 2025-09..2026-09, CSS pixels); date=2026-10-20; method=the narrowest viewport width the list holds, 360, a quarter of its share, since a fixed width above it overflows every phone that wide. It was 390 (F11), so a 361-390px column passed MB-100 while overflowing on 25.7% (at 361px) to 48.9% (at 390px) of the listed share, which StatCounter counts in page views, not phones. The list folds a third of its share into "Other", and the rule was chosen after the earlier value was checked against it.
MAX_FIXED_WIDTH_PX = 360

# A container query too: a container at least 700px wide cannot sit on a 360px screen.
RE_MEDIA = re.compile(r"@(?:media|container)\b([^{;]*)\{", re.I)
# A lower bound on the viewport width: `min-width: 768px`, `48em`, or `width >= 768px`.
RE_MIN_WIDTH = re.compile(
    r"min-width\s*:\s*([\d.]+)\s*(px|r?em)\b|\bwidth\s*>=?\s*([\d.]+)\s*(px|r?em)\b"
    r"|([\d.]+)\s*(px|r?em)\s*<=?\s*width\b", re.I)


def _wide_only(prelude: str) -> bool:
    """Whether a media query's every alternative needs a viewport wider than
    MAX_FIXED_WIDTH_PX, or is for print or speech, so nothing inside it applies on the
    narrowest phone (review round 1: `@media print` widths failed MB-100)."""
    def floor(alternative: str) -> float:
        if re.search(r"\bnot\b", alternative, re.I):
            return 0.0
        if re.match(r"\s*(?:only\s+)?(?:print|speech)\b", alternative, re.I):
            return float("inf")
        floors = [0.0]
        for match in RE_MIN_WIDTH.finditer(alternative):
            value, unit = [part for part in match.groups() if part]
            floors.append(float(value) * (1 if unit.lower() == "px" else 16))
        return max(floors)
    return all(floor(alt) > MAX_FIXED_WIDTH_PX for alt in prelude.split(","))


def phone_css(text: str) -> str:
    """`text` without the @media blocks that never apply on a 360px phone (F15, MB-100's
    ruling): a `.container{width:960px}` inside `@media (min-width: 992px)` is how a
    responsive page sizes its desktop column, not a width a phone overflows."""
    kept, pos = [], 0
    while True:
        found = RE_MEDIA.search(text, pos)
        if not found:
            kept.append(text[pos:])
            return "".join(kept)
        depth, end = 1, found.end()
        while end < len(text) and depth:
            depth += {"{": 1, "}": -1}.get(text[end], 0)
            end += 1
        if _wide_only(found.group(1)):
            kept.append(text[pos:found.start()])
            pos = end
        else:
            kept.append(text[pos:found.end()])
            pos = found.end()


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
    #
    # A width inside parentheses is a media or container query's feature, or a `sizes`
    # or `media` attribute's condition — `@media (min-width: 768px)` is how responsive
    # CSS is written, and it failed MB-100 (F15, its ruling). A declaration is never
    # parenthesised, so the parenthesised text goes first, innermost out; a group that
    # spans a brace or a semicolon is not a condition (a stray "(" in prose would
    # otherwise swallow the rule after it).
    declarations = phone_css(text)
    while True:
        stripped = re.sub(r"\([^(){};]*\)", " ", declarations)
        if stripped == declarations:
            break
        declarations = stripped
    fixed_width_hits = re.findall(
        r"(?<![-\w])(?:min-width|width)\s*:\s*(\d{3,})px", declarations, flags=re.I)
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
        "fetch_error_kind": fetched.get("error_kind"),
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
    args.source = read_source(args.source)

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
    from lib.typed_credential import credentials_beside_argv
    credentials_beside_argv()
    sys.exit(main())
