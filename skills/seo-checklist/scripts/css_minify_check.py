#!/usr/bin/env python3
"""
Check whether a page's stylesheets are minified.

Minification is judged structurally, not by filename: a file called *.min.css
that still carries comments and one rule per line is not minified, and a hand-
written single-line file is. The heuristic combines newline density, comment
volume and indentation.

Usage:
    python css_minify_check.py https://example.com
    python css_minify_check.py https://example.com --json
"""

import argparse
import json
import re
import sys
from urllib.parse import urljoin

try:
    import requests  # noqa: F401  (kept for the shared dependency error contract)
except ImportError:
    print("Error: requests library required. Install with: pip install requests")
    sys.exit(1)

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("Error: beautifulsoup4 required. Install with: pip install beautifulsoup4")
    sys.exit(1)

try:
    from lib.safe_http import safe_get
except ImportError:
    from scripts.lib.safe_http import safe_get

try:
    from seo_common import html_parser
except ImportError:
    from scripts.seo_common import html_parser

# The three signals of minified CSS are read together. A corpus containing authored
# CSS as well as generated build output matters here: generated source alone is much
# more tightly formatted and would make hand-written CSS look minified.
# basis: measured — corpus=tools/calibration/css-minification.json; date=2026-08-09; method=filename-labelled signal distributions
# 165/174 minified files cross 180. Two source-labelled one-line distribution files
# also cross it, while lowering the boundary would add false positives without fixing
# line-wrapped minified CSS; 180 stays as a deliberately wide boundary.
MINIFIED_BYTES_PER_LINE = 180
# basis: measured — corpus=tools/calibration/css-minification.json; date=2026-08-09; method=comment-conjunct ablation over labelled files
# The conjunct changes only two classifications, both false negatives on minified
# PureCSS carrying large comments. It barely discriminates; 8% is retained, not vindicated.
MINIFIED_COMMENT_SHARE = 0.08
# basis: measured — corpus=tools/calibration/css-minification.json; date=2026-08-09; method=indent-signal distribution over labelled files
# Every file that passes the other two signals has at most two indented lines, so any
# boundary from 3 through 20 gives the same corpus answer. Twenty is arbitrary in it.
MINIFIED_MAX_INDENTED = 20
# basis: measured — corpus=tools/calibration/css-minification.json; date=2026-08-09; method=paired raw-byte and gzip-byte savings
# 10.8% of aggregate raw-byte saving survives gzip; the median of per-package pair
# medians is 7.2% (the pooled pair median is 14.4%). The 20KB threshold remains an
# uncompressed convention pending a separate change to what it counts.
WASTED_BYTES_WARN = 20000

# basis: measured — corpus=tools/calibration/css-minification.json; date=2026-08-09; method=median of per-package medians for paired raw-byte saving
# Across 12 package pipelines the median of paired-file medians is 18.918%; equal
# package weight prevents prolific build variants from becoming extra observations.
MINIFICATION_SAVINGS_FRACTION = 0.189

# basis: inherited — 12 stylesheets, present at import. It decides a verdict rather
#  than only a runtime: TE-174 passes when `unminified_count` is 0, and that count is
#  over the first twelve sheets a page links. A page linking thirty was reported clean
#  from twelve of them. `truncated` says when the cap bit.
MAX_SHEETS = 12
# basis: measured — corpus=tools/calibration/css-minification.json; date=2026-08-09; method=label and classifier results below the byte cutoff
# The 170 sub-2KB files come from only five packages: 98 animate.css single-animation
# fragments plus its two source support files, 41 tachyons source partials, 19 PureCSS
# files, six sanitize.css files and four 98.css files. That is packaging convention,
# not a general small-CSS population; 159 are source-labelled and 11 minified.
SMALL_FILE_BYTES = 2048  # suppress files too small to matter
RE_COMMENT = re.compile(r"/\*.*?\*/", re.S)


def minification_signals(css: str) -> tuple[float, float, int]:
    """Return the three structural signals consumed by ``looks_minified``."""
    if not css.strip():
        return 0.0, 0.0, 0
    lines = css.count("\n") + 1
    ratio = len(css) / lines
    comments = sum(len(m) for m in RE_COMMENT.findall(css))
    comment_pct = comments / len(css) if css else 0
    indented = sum(1 for ln in css.split("\n")[:400] if ln[:2] in ("  ", "\t "))
    return ratio, comment_pct, indented


def looks_minified(css: str) -> tuple[bool, float]:
    """Return (minified, bytes_per_line) from the three structural signals."""
    if not css.strip():
        return True, 0.0
    ratio, comment_pct, indented = minification_signals(css)
    # Any one signal alone is weak evidence; together they are decisive.
    minified = (ratio > MINIFIED_BYTES_PER_LINE
                and comment_pct < MINIFIED_COMMENT_SHARE
                and indented < MINIFIED_MAX_INDENTED)
    return minified, round(ratio, 1)


def check(url: str, timeout: int = 15) -> dict:
    result = {
        "url": url,
        "stylesheets": [],
        "checked": 0,
        "unminified_count": 0,
        # Set below, once the page's stylesheets are known.
        "truncated": False,
        "wasted_bytes": 0,
        "issues": [],
        "fetch_error": None,
    }
    try:
        html = safe_get(url, timeout=timeout).text
    except Exception as exc:
        result["fetch_error"] = str(exc)[:200]
        return result

    soup = BeautifulSoup(html, html_parser())
    hrefs = []
    for link in soup.find_all("link"):
        rel = link.get("rel") or []
        rel_text = " ".join(rel if isinstance(rel, list) else [rel]).lower()
        if "stylesheet" not in rel_text:
            continue
        href = link.get("href")
        if href:
            hrefs.append(urljoin(url, href))
    hrefs = list(dict.fromkeys(hrefs))
    result["truncated"] = len(hrefs) > MAX_SHEETS
    hrefs = hrefs[:MAX_SHEETS]

    for href in hrefs:
        row = {"href": href, "bytes": None, "minified": None, "ratio": None,
               "status": None, "error": None}
        try:
            resp = safe_get(href, timeout=timeout)
            row["status"] = resp.status_code
            css = resp.text
            row["bytes"] = len(css.encode("utf-8", errors="ignore"))
            if row["bytes"] < SMALL_FILE_BYTES:
                # Too small to judge, and too small to matter.
                row["minified"] = True
            else:
                row["minified"], row["ratio"] = looks_minified(css)
                if not row["minified"]:
                    result["unminified_count"] += 1
                    result["wasted_bytes"] += int(
                        row["bytes"] * MINIFICATION_SAVINGS_FRACTION)
            result["checked"] += 1
        except Exception as exc:
            row["error"] = str(exc)[:160]
        result["stylesheets"].append(row)

    if not hrefs:
        result["issues"].append({
            "severity": "low",
            "message": "No external stylesheets found (inline or JS-injected CSS "
                       "is not evaluated here)",
            "url": url,
        })
    for row in result["stylesheets"]:
        if row["minified"] is False:
            result["issues"].append({
                "severity": "low",
                "message": f"Unminified CSS ({row['bytes']} bytes, "
                           f"{row['ratio']} bytes/line): {row['href']}",
                "url": row["href"],
            })
    if result["wasted_bytes"] > WASTED_BYTES_WARN:
        result["issues"].append({
            "severity": "medium",
            "message": f"~{result['wasted_bytes'] // 1024} KB recoverable by minifying CSS",
            "url": url,
        })
    return result


def main():
    parser = argparse.ArgumentParser(description="Check whether stylesheets are minified")
    parser.add_argument("url", help="URL to check")
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument("--json", "-j", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    result = check(args.url, args.timeout)

    if args.json:
        print(json.dumps(result, indent=2))
        return

    if result["fetch_error"]:
        print(f"Could not fetch page: {result['fetch_error']}")
        return
    print(f"CSS minification for {result['url']}")
    print(f"  stylesheets checked: {result['checked']}")
    print(f"  unminified:          {result['unminified_count']}")
    if result["wasted_bytes"]:
        print(f"  recoverable:         ~{result['wasted_bytes'] // 1024} KB")
    for row in result["stylesheets"]:
        state = "error" if row["error"] else ("min" if row["minified"] else "NOT MIN")
        print(f"  [{state}] {row['href'][:90]}")


if __name__ == "__main__":
    from lib.utf8_streams import utf8_streams
    utf8_streams()
    main()
