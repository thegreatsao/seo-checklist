#!/usr/bin/env python3
"""Measure `mobile_render_checker.py`'s MAX_FIXED_WIDTH_PX against phone viewport widths.

    python3 tools/calibrate_mobile_viewport.py            # fetch, rewrite the report
    python3 tools/calibrate_mobile_viewport.py --check    # offline: re-derive from the report

MB-100 fails a page that declares a fixed CSS `width` or `min-width` wider than this:
such an element overflows a phone whose layout viewport is narrower, and the page scrolls
sideways. The number's claim is therefore a fact about phones in use — how wide their
viewports are — and that is published: StatCounter's worldwide mobile "screen
resolution" share, which reports the CSS-pixel `screen` size browsers expose.

The selection rule, from the claim itself: the narrowest viewport width the list holds.
A fixed width above it overflows on every phone of that width. The rule was not written
before the data was seen (the earlier value, 390, was checked against the same list
first), which is the stated limitation together with these: StatCounter's sample is the
sites carrying its tracker, its list names the top resolutions and folds the rest into
"Other" (about a third of the share), and a `screen` width is the viewport only for a
page with `width=device-width`, which MB-100 checks first. `--check` reads only the
committed report and the literal constant; it does not fetch.
"""
from __future__ import annotations

import python_floor  # noqa: F401

import argparse
import csv
import io
import json
import os
import sys
from datetime import datetime, timezone

from calibration_common import literal_constants

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
REPORT = os.path.join(HERE, "calibration", "mobile-viewport.json")
CHECKER = os.path.join(SKILL_DIR, "scripts", "mobile_render_checker.py")

# Twelve months, fixed, so a re-run asks for the same window.
SOURCE = ("https://gs.statcounter.com/chart.php?device=Mobile&device_hidden=mobile"
          "&statType_hidden=resolution&region_hidden=ww&granularity=monthly"
          "&statType=Screen%20Resolution&region=Worldwide&fromInt=202509&toInt=202609"
          "&fromMonthYear=2025-09&toMonthYear=2026-09&csv=1")
SELECTION_RULE = "the narrowest viewport width in the list"


def widths(rows: list[dict]) -> list[tuple[int, float]]:
    out = []
    for row in rows:
        name = row["resolution"]
        if "x" in name:
            out.append((int(name.split("x", 1)[0]), row["share"]))
    return out


def derive(rows: list[dict]) -> dict:
    pairs = widths(rows)
    listed = sum(share for _, share in pairs)
    chosen = min(width for width, _ in pairs)

    def narrower(limit: int) -> float:
        return round(100 * sum(s for w, s in pairs if w < limit) / listed, 1)

    return {"selected": chosen, "listed_share": round(listed, 2),
            "share_at_selected": round(100 * sum(s for w, s in pairs if w == chosen)
                                       / listed, 1),
            "share_narrower_than_390": narrower(390),
            "share_narrower_than_375": narrower(375)}


def measure() -> dict:
    sys.path.insert(0, os.path.join(SKILL_DIR, "scripts"))
    from lib.safe_http import safe_get

    text = safe_get(SOURCE, timeout=30).text
    reader = csv.reader(io.StringIO(text))
    header = next(reader)
    rows = [{"resolution": name, "share": float(share)} for name, share in reader]
    return {"generated": datetime.now(timezone.utc).date().isoformat(),
            "source": SOURCE, "header": header, "rows": rows,
            "method": ("StatCounter worldwide mobile screen-resolution share, "
                       f"2025-09..2026-09, CSS pixels; {SELECTION_RULE}"),
            "selection_rule": SELECTION_RULE, "derived": derive(rows)}


def check() -> int:
    with open(REPORT, encoding="utf-8") as fh:
        report = json.load(fh)
    derived = derive(report["rows"])
    problems = []
    if derived != report["derived"]:
        problems.append("the derived numbers no longer follow from the stored rows")
    constant = literal_constants(CHECKER, {"MAX_FIXED_WIDTH_PX"},
                                 "could not read MAX_FIXED_WIDTH_PX: {missing}")
    if constant["MAX_FIXED_WIDTH_PX"] != derived["selected"]:
        problems.append(f"MAX_FIXED_WIDTH_PX is {constant['MAX_FIXED_WIDTH_PX']}, the "
                        f"measurement selects {derived['selected']}")
    for line in problems:
        print(line)
    if not problems:
        print(f"mobile-viewport.json is in step: MAX_FIXED_WIDTH_PX {derived['selected']}")
    return 1 if problems else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true")
    if ap.parse_args().check:
        return check()
    report = measure()
    with open(REPORT, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False, sort_keys=True)
        fh.write("\n")
    print(json.dumps(report["derived"]))
    return 0


if __name__ == "__main__":
    from utf8_streams import utf8_streams
    utf8_streams()
    sys.exit(main())
