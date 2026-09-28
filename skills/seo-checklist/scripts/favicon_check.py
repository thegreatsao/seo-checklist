#!/usr/bin/env python3
"""Fetch a page's declared favicon and grade it against Google's requirements."""

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
    from seo_common import (favicon_href, fetch_robots, html_parser, issue,
                            origin, robots_allowed)
except ImportError:
    from scripts.seo_common import (favicon_href, fetch_robots, html_parser, issue,
                                    origin, robots_allowed)

try:
    from lib.image_header import image_header
except ImportError:
    from scripts.lib.image_header import image_header


# basis: standard — Google's favicon page says a favicon "must be a square (1:1 aspect ratio) that's at least 8x8px."
REQUIRED_MIN_SIDE_PX = 8
# basis: standard — Google's favicon page says "we recommend using a favicon that's larger than 48x48px".
RECOMMENDED_SIDE_ABOVE_PX = 48
# Google's "Define a favicon to show in search results" page lists these formats.
GOOGLE_FAVICON_FORMATS = frozenset({"bmp", "gif", "ico", "png", "jpeg", "ppm", "tiff"})
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
            "square": None,
            "google_format": None,
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
        favicon.update({"grade": "fails", "reason": reason})
        result["issues"].append(issue("low", reason, page.url))
        return result

    robots = fetch_robots(page.url, timeout=timeout)
    parsed_robots = robots.get("parsed")
    if parsed_robots is not None:
        for agent, target in (("Googlebot", origin(page.url) + "/"),
                              ("Googlebot-Image", resolved)):
            allowed, _rule = robots_allowed(parsed_robots, target, agent)
            if not allowed:
                reason = f"{agent} may not fetch {target} under robots.txt"
                favicon.update({"grade": "fails", "reason": reason})
                result["issues"].append(issue("low", reason, target))
                return result

    try:
        response = safe_get(resolved, timeout=timeout, max_response_bytes=MAX_ICON_BYTES)
        favicon["status"] = response.status_code
        favicon["content_type"] = response.headers.get("Content-Type")
    except Exception as exc:  # noqa: BLE001 — a declared but unreachable icon is a defect
        reason = f"Declared favicon is unreachable: {str(exc)[:160]}"
        favicon.update({"grade": "fails", "reason": reason})
        result["issues"].append(issue("low", reason, resolved))
        return result
    if response.status_code >= 400:
        reason = f"Declared favicon is unreachable: HTTP {response.status_code}"
        favicon.update({"grade": "fails", "reason": reason})
        result["issues"].append(issue("low", reason, resolved))
        return result

    media_type = (response.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
    if media_type.startswith("text/"):
        reason = f"Declared favicon answers a page ({media_type}), not an image"
        favicon.update({"grade": "fails", "reason": reason})
        result["issues"].append(issue("low", reason, resolved))
        return result

    measured = image_header(response.content)
    if measured is None:
        favicon["reason"] = "Favicon format is not recognised; dimensions could not be measured"
        return result
    format_name, width, height = measured
    square = width == height if width is not None and height is not None else None
    google_format = format_name in GOOGLE_FAVICON_FORMATS
    min_side = None if format_name == "svg" else min(width, height)
    dimensions = (f"{width if width is not None else 'unknown'}x"
                  f"{height if height is not None else 'unknown'}")
    favicon.update({"format": format_name, "width": width, "height": height,
                    "min_side_px": min_side, "square": square,
                    "google_format": google_format})

    if square is False:
        grade = "fails"
        reason = (f"Favicon measures {dimensions} in {format_name} format; it is not "
                  "square and fails Google's required tier")
    elif min_side is not None and min_side < REQUIRED_MIN_SIDE_PX:
        grade = "fails"
        reason = (f"Favicon measures {dimensions} in {format_name} format; its shorter "
                  f"side is below Google's required {REQUIRED_MIN_SIDE_PX}px tier")
    elif not google_format:
        grade = "required_only"
        reason = (f"Favicon measures {dimensions} in {format_name} format; it meets "
                  "Google's required tier but its format is outside Google's list")
    elif min_side is not None and min_side > RECOMMENDED_SIDE_ABOVE_PX:
        grade = "recommended"
        reason = (f"Favicon measures {dimensions} in {format_name} format; it meets "
                  f"Google's recommended tier above {RECOMMENDED_SIDE_ABOVE_PX}px")
    else:
        grade = "required_only"
        reason = (f"Favicon measures {dimensions} in {format_name} format; it meets "
                  "Google's required tier but not the recommendation above "
                  f"{RECOMMENDED_SIDE_ABOVE_PX}px")
    favicon.update({"grade": grade, "reason": reason})
    if grade == "fails":
        result["issues"].append(issue("low", reason, resolved))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Grade a favicon against Google's requirements")
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
