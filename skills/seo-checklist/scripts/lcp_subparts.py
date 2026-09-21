#!/usr/bin/env python3
"""Estimate LCP subparts from Lighthouse JSON or lightweight page evidence."""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

try:
    from lib.safe_http import safe_request
except ImportError:
    from scripts.lib.safe_http import safe_request

from seo_common import is_url, load_source, normalize_url, parse_html


# basis: inherited — 100, present at import, and a unit guess rather than a limit:
#  Lighthouse reports network timings in milliseconds, but some versions and some
#  proxies hand back seconds, and a page whose LCP resource genuinely starts within
#  100ms of navigation is rare enough that treating the value as seconds is the safer
#  reading. Wrong for a very fast resource, which is the trade.
MS_IF_ABOVE = 100

def _load_lighthouse(path: str) -> dict:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return payload.get("lighthouseResult", payload)


def _lcp_element_url(lhr: dict) -> str | None:
    details = lhr.get("audits", {}).get("largest-contentful-paint-element", {}).get("details", {})
    for item in details.get("items", []):
        for key in ("url", "source"):
            if item.get(key):
                return item[key]
        node = item.get("node", {})
        snippet = node.get("snippet", "")
        match = re.search(r"""(?:src|href)=["']([^"']+)""", snippet)
        if match:
            return match.group(1)
    return None


def _network_item_for_url(lhr: dict, url: str | None) -> dict | None:
    if not url:
        return None
    items = lhr.get("audits", {}).get("network-requests", {}).get("details", {}).get("items", [])
    for item in items:
        item_url = item.get("url", "")
        if item_url == url or item_url.split("?", 1)[0] == url.split("?", 1)[0]:
            return item
    return None


def subparts_from_lighthouse(path: str) -> dict:
    lhr = _load_lighthouse(path)
    audits = lhr.get("audits", {})
    lcp_ms = audits.get("largest-contentful-paint", {}).get("numericValue")
    ttfb_ms = audits.get("server-response-time", {}).get("numericValue")
    lcp_url = _lcp_element_url(lhr)
    resource = _network_item_for_url(lhr, lcp_url)

    resource_start = resource.get("networkRequestTime") if resource else None
    resource_end = resource.get("networkEndTime") if resource else None
    if isinstance(resource_start, (int, float)) and resource_start < MS_IF_ABOVE:
        resource_start *= 1000
    if isinstance(resource_end, (int, float)) and resource_end < MS_IF_ABOVE:
        resource_end *= 1000

    resource_duration = None
    if isinstance(resource_start, (int, float)) and isinstance(resource_end, (int, float)):
        resource_duration = max(0, resource_end - resource_start)

    resource_delay = None
    if isinstance(resource_start, (int, float)) and isinstance(ttfb_ms, (int, float)):
        resource_delay = max(0, resource_start - ttfb_ms)

    render_delay = None
    if isinstance(lcp_ms, (int, float)):
        known = sum(v for v in (ttfb_ms, resource_delay, resource_duration) if isinstance(v, (int, float)))
        render_delay = max(0, lcp_ms - known)

    return {
        "source": path,
        "mode": "lighthouse-json",
        "lcp_ms": round(lcp_ms) if isinstance(lcp_ms, (int, float)) else None,
        "lcp_element_url": lcp_url,
        "subparts": {
            "ttfb_ms": round(ttfb_ms) if isinstance(ttfb_ms, (int, float)) else None,
            "resource_load_delay_ms": round(resource_delay) if isinstance(resource_delay, (int, float)) else None,
            "resource_load_duration_ms": round(resource_duration) if isinstance(resource_duration, (int, float)) else None,
            "element_render_delay_ms": round(render_delay) if isinstance(render_delay, (int, float)) else None,
        },
        "confidence": "medium" if lcp_ms else "low",
        "notes": ["Computed from Lighthouse audits and network timing where present."],
        "error": None,
    }


def _candidate_lcp_image(parsed: dict) -> dict | None:
    images = parsed.get("images", [])
    prioritized = [
        img for img in images
        if img.get("fetchpriority") == "high" or img.get("loading") in (None, "", "eager")
    ]
    return (prioritized or images or [None])[0]


def _fetch_ttfb(url: str, timeout: int) -> tuple[int | None, dict, str | None]:
    started = time.perf_counter()
    try:
        response = safe_request("GET", normalize_url(url), timeout=timeout, max_response_bytes=2_000_000)
    except Exception as exc:  # noqa: BLE001 - CLI degrades gracefully for network policy/timeouts
        return None, {}, str(exc)
    elapsed_ms = round(response.elapsed.total_seconds() * 1000) if response.elapsed else round((time.perf_counter() - started) * 1000)
    headers = {str(k).lower(): v for k, v in response.headers.items()}
    return elapsed_ms, headers, None


def analyze_source(source: str, timeout: int = 15) -> dict:
    html, final_url, fetched = load_source(source, timeout=timeout)
    parsed = parse_html(html, final_url or source)
    image = _candidate_lcp_image(parsed)
    ttfb_ms = None
    headers = {}
    error = fetched.get("error")
    if is_url(source) and final_url:
        ttfb_ms, headers, timing_error = _fetch_ttfb(final_url, timeout)
        error = error or timing_error

    notes = [
        "Static mode cannot observe the browser's real LCP render timestamp.",
        "Use --lighthouse-json with a saved Lighthouse report for stronger subpart estimates.",
    ]
    if image and image.get("loading") == "lazy":
        notes.append("Likely LCP candidate is lazy-loaded, which can increase resource load delay.")
    if image and image.get("fetchpriority") != "high":
        notes.append("Likely LCP candidate does not use fetchpriority=high.")

    # `fetched` carries `seo_common.fetch_error_kind`'s verdict and this result used
    # to drop it, so a site that refused the connection reached the operator as
    # "script failed". The fetch layer's seven words are not the runner's eight:
    # every one of them except `other` means the request never came back, which is
    # `unread`; `other` is an exception it could not place, and that may be ours.
    #
    # Written as statements rather than one conditional expression because
    # `tools/audit_error_kinds.py` reads assigned literals out of the source, and a
    # kind it cannot read is a kind it cannot count — which is the census's own
    # failure mode, recorded in its docstring.
    out = {
        "source": source,
        "final_url": final_url or source,
        "mode": "static-html",
        "lcp_ms": None,
        "lcp_element_url": image.get("src") if image else None,
        "subparts": {
            "ttfb_ms": ttfb_ms,
            "resource_load_delay_ms": None,
            "resource_load_duration_ms": None,
            "element_render_delay_ms": None,
        },
        "response_headers": headers,
        "confidence": "low",
        "notes": notes,
        "error": error,
    }
    if error:
        out["error_kind"] = "crash"
        if fetched.get("error_kind") != "other":
            out["error_kind"] = "unread"
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Estimate Largest Contentful Paint subparts")
    parser.add_argument("source", nargs="?", help="URL or local HTML file")
    parser.add_argument("--lighthouse-json", help="Path to a Lighthouse JSON report")
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument("--json", "-j", action="store_true")
    args = parser.parse_args()

    if not args.source and not args.lighthouse_json:
        parser.error("provide a source or --lighthouse-json")
    result = subparts_from_lighthouse(args.lighthouse_json) if args.lighthouse_json else analyze_source(args.source, args.timeout)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        parts = result["subparts"]
        print(
            "LCP subparts: "
            f"TTFB={parts['ttfb_ms']}ms, "
            f"delay={parts['resource_load_delay_ms']}ms, "
            f"duration={parts['resource_load_duration_ms']}ms, "
            f"render={parts['element_render_delay_ms']}ms"
        )


if __name__ == "__main__":
    main()
