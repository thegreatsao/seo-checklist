#!/usr/bin/env python3
"""Fetch a page's declared favicon and measure whether it can display at 48 px."""

from __future__ import annotations

import argparse
import json
import sys

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
    from seo_common import favicon_href, html_parser, issue
except ImportError:
    from scripts.seo_common import favicon_href, html_parser, issue

try:
    from lib.image_header import image_header
except ImportError:
    from scripts.lib.image_header import image_header


# basis: standard — Google Search requires favicon dimensions that are a multiple of 48px; this check enforces only that documented 48px floor, on the shorter side.
MIN_FAVICON_SIDE_PX = 48
MAX_ICON_BYTES = 2_000_000


def check(url: str, timeout: int = 15) -> dict:
    result = {
        "url": url,
        "favicon": {
            "declared": None,
            "href": None,
            "url": None,
            "status": None,
            "content_type": None,
            "format": None,
            "width": None,
            "height": None,
            "min_side_px": None,
        },
        "issues": [],
        "fetch_error": None,
    }
    favicon = result["favicon"]
    try:
        page = safe_get(url, timeout=timeout)
    except Exception as exc:  # noqa: BLE001 — an unread page is evidence, not a crash
        reason = f"Page could not be fetched: {str(exc)[:200]}"
        result["fetch_error"] = reason
        favicon["reason"] = reason
        return result
    if page.status_code >= 400:
        reason = f"Page could not be fetched: HTTP {page.status_code}"
        result["fetch_error"] = reason
        favicon["reason"] = reason
        return result

    soup = BeautifulSoup(page.text, html_parser())
    declared = favicon_href(soup)
    resolved = favicon_href(soup, page.url)
    favicon.update({"declared": bool(resolved), "href": declared, "url": resolved})
    if not resolved:
        reason = "No favicon is declared on the page"
        favicon.update({"displays_at_48px": False, "reason": reason})
        result["issues"].append(issue("low", reason, page.url))
        return result

    try:
        response = safe_get(resolved, timeout=timeout, max_response_bytes=MAX_ICON_BYTES)
        favicon["status"] = response.status_code
        favicon["content_type"] = response.headers.get("Content-Type")
    except Exception as exc:  # noqa: BLE001 — a declared but unreachable icon is a defect
        reason = f"Declared favicon is unreachable: {str(exc)[:160]}"
        favicon.update({"displays_at_48px": False, "reason": reason})
        result["issues"].append(issue("low", reason, resolved))
        return result
    if response.status_code >= 400:
        reason = f"Declared favicon is unreachable: HTTP {response.status_code}"
        favicon.update({"displays_at_48px": False, "reason": reason})
        result["issues"].append(issue("low", reason, resolved))
        return result

    measured = image_header(response.content)
    if measured is None:
        favicon["reason"] = "Favicon format is not recognised; dimensions could not be measured"
        return result
    format_name, width, height = measured
    favicon.update({"format": format_name, "width": width, "height": height})
    if format_name == "svg":
        # SVG is vector: once fetched and recognised it can render at 48px regardless
        # of its intrinsic width, height or viewBox.
        favicon.update({
            "displays_at_48px": True,
            "reason": "Favicon is a resolvable SVG and can render at 48x48",
        })
        return result

    min_side = min(width, height)
    displays = min_side >= MIN_FAVICON_SIDE_PX
    reason = (f"Favicon measures {width}x{height}; shorter side {min_side}px "
              f"{'meets' if displays else 'is below'} the {MIN_FAVICON_SIDE_PX}px floor")
    favicon.update({"min_side_px": min_side, "displays_at_48px": displays,
                    "reason": reason})
    if not displays:
        result["issues"].append(issue("low", reason, resolved))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Check whether a favicon can display at 48px")
    parser.add_argument("url", help="Page URL to check")
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument("--json", "-j", action="store_true", help="Output as JSON")
    args = parser.parse_args()
    result = check(args.url, args.timeout)
    if args.json:
        print(json.dumps(result, indent=2))
        return
    print(result["favicon"].get("reason", "No favicon result"))
    for finding in result["issues"]:
        print(f"[{finding['severity']}] {finding['message']}")


if __name__ == "__main__":
    main()
