#!/usr/bin/env python3
"""Check compression and caching headers for a page and optional assets."""

from __future__ import annotations

import argparse
import json
import re
from urllib.parse import urlparse

try:
    from lib.safe_http import safe_request
except ImportError:
    from scripts.lib.safe_http import safe_request

from seo_common import (BeautifulSoup, html_parser, is_url, load_source,
                        normalize_url, require_bs4)


# basis: inherited — one week of `max-age` for a fingerprinted static asset, present at
#  import. Round, and the sort of number a CDN's own documentation suggests.
STATIC_MAX_AGE_MIN = 604800
# basis: inherited — 30 days, present at import. Above it a static asset is expected to
#  carry `immutable`, because a month of caching with no fingerprint in the URL is a
#  month of serving a file that has changed.
STATIC_IMMUTABLE_MAX_AGE = 2_592_000
# basis: convention — one kibibyte, the minimum length below which compression plus its
#  header overhead rarely reduces what goes over the wire. Every serious server ships
#  the same knob with a number of this order; none of them measured it here.
COMPRESSIBLE_MIN_BYTES = 1024
# basis: inherited — present at import as `max_assets=25` on `audit`, where the
#  threshold inventory could not see it. It is a threshold and not a budget because
#  TE-170 asserts that `issues` contains no medium-or-worse finding, and this number
#  decides how many linked assets can supply one. Measured for 0.91.0 with a one-asset
#  cap: one distinct linked asset leaves a complete answer, while a second is absent
#  from `resources` and `issues` and must mark the answer incomplete rather than move
#  the cap.
MAX_ASSETS = 25

STATIC_EXTENSIONS = (".css", ".js", ".mjs", ".png", ".jpg", ".jpeg", ".webp", ".avif", ".svg", ".woff2", ".woff")
TEXT_EXTENSIONS = (".html", ".css", ".js", ".mjs", ".json", ".xml", ".svg", ".txt")


def _asset_urls(soup, page_url: str = "") -> list[str]:
    urls = []
    for tag in soup.find_all(["script", "link", "img"], src=True):
        value = tag.get("src")
        urls.append(normalize_url(value, page_url) if page_url and value else value)
    for tag in soup.find_all("link", href=True):
        rel = " ".join(tag.get("rel") or []).lower()
        if any(token in rel for token in ("stylesheet", "preload", "modulepreload", "icon")):
            value = tag.get("href")
            urls.append(normalize_url(value, page_url) if page_url and value else value)
    return [url for url in urls if url and url.startswith(("http://", "https://"))]


def _cache_max_age(cache_control: str | None) -> int | None:
    if not cache_control:
        return None
    match = re.search(r"(?:s-maxage|max-age)=(\d+)", cache_control)
    return int(match.group(1)) if match else None


def _check_url(url: str, timeout: int) -> dict:
    row = {
        "url": url,
        "status": None,
        "content_type": None,
        "content_encoding": None,
        "cache_control": None,
        "etag": None,
        "vary": None,
        "content_length": None,
        "issues": [],
        "error": None,
    }
    try:
        response = safe_request("HEAD", normalize_url(url), timeout=timeout, max_response_bytes=0)
    except Exception as exc:  # noqa: BLE001 - network and policy errors should be reported, not fatal
        row["error"] = str(exc)
        return row

    headers = {str(k).lower(): v for k, v in response.headers.items()}
    row.update({
        "status": response.status_code,
        "content_type": headers.get("content-type"),
        "content_encoding": headers.get("content-encoding"),
        "cache_control": headers.get("cache-control"),
        "etag": headers.get("etag"),
        "vary": headers.get("vary"),
    })
    length = headers.get("content-length")
    row["content_length"] = int(length) if length and length.isdigit() else None

    path = urlparse(url).path.lower()
    is_static = path.endswith(STATIC_EXTENSIONS)
    is_text = path.endswith(TEXT_EXTENSIONS) or (row["content_type"] and any(t in row["content_type"] for t in ("text/", "javascript", "json", "xml", "svg")))
    if is_text and row["content_encoding"] not in ("br", "gzip", "deflate"):
        # The one finding here that is a misconfiguration on every server and for
        # every visitor when the response is large: text sent uncompressed costs bytes
        # on every request, and the repair is one directive in the server config,
        # which is the item's own subject. The rest of this file is graded on how much
        # it costs — a missing validator header is a round trip, `immutable` is an
        # optimisation — so they stay `warning` and `info`. Before 0.50.0 nothing here
        # said `error`, which is exactly why TE-170 could not report FAIL on any site.
        # A known large response is therefore `error`, a known small response is no
        # finding because compression overhead can outweigh it, and an unknown length
        # is `warning` because the high-severity premise cannot be proved.
        message = "Compressible response is not Brotli/gzip encoded"
        if row["content_length"] is None:
            row["issues"].append({"severity": "warning",
                                  "message": f"{message} (length unknown)"})
        elif row["content_length"] > COMPRESSIBLE_MIN_BYTES:
            row["issues"].append({"severity": "error", "message": message})
    max_age = _cache_max_age(row["cache_control"])
    if is_static and (max_age is None or max_age < STATIC_MAX_AGE_MIN):
        row["issues"].append({"severity": "warning", "message": "Static asset cache lifetime is short or missing"})
    if is_static and row["cache_control"] and "immutable" not in row["cache_control"].lower() and max_age and max_age >= STATIC_IMMUTABLE_MAX_AGE:
        row["issues"].append({"severity": "info", "message": "Long-lived static asset can use immutable"})
    if not row["etag"] and "last-modified" not in headers:
        row["issues"].append({"severity": "info", "message": "No validator header (ETag or Last-Modified)"})
    if row["content_encoding"] and row["vary"] and "accept-encoding" not in row["vary"].lower():
        row["issues"].append({"severity": "warning", "message": "Compressed response should vary on Accept-Encoding"})
    return row


def audit(source: str, include_assets: bool = False, timeout: int = 15,
          max_assets: int = MAX_ASSETS) -> dict:
    if not is_url(source):
        html, url, fetched = load_source(source, timeout=timeout)
        require_bs4()
        soup = BeautifulSoup(html or "", html_parser())
        return {
            "url": source,
            "resources_checked": 0,
            "issues": [{"severity": "info", "message": "Header checks require HTTP(S); local HTML was parsed for asset discovery only."}],
            "resources": [],
            "asset_count": len(_asset_urls(soup, url)),
            "fetch_error": fetched.get("error"),
            "truncated": False,
        }

    html, url, fetched = load_source(source, timeout=timeout)
    resources = [_check_url(url or source, timeout)]
    truncated = False
    if include_assets and html:
        require_bs4()
        soup = BeautifulSoup(html or "", html_parser())
        seen = {resources[0]["url"]}
        for asset in _asset_urls(soup, url):
            if asset in seen:
                continue
            if len(resources) - 1 >= max_assets:
                truncated = True
                break
            seen.add(asset)
            resources.append(_check_url(asset, timeout))
    issues = []
    for row in resources:
        for item in row["issues"]:
            issues.append({**item, "url": row["url"]})
        if row["error"]:
            issues.append({"severity": "info", "message": "Could not fetch headers", "url": row["url"], "evidence": row["error"]})
    return {
        "url": url or source,
        "resources_checked": len(resources),
        "issues": issues,
        "resources": resources,
        "fetch_error": fetched.get("error"),
        "truncated": truncated,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Check cache and compression headers")
    parser.add_argument("source", help="URL or local HTML file")
    parser.add_argument("--include-assets", action="store_true", help="Also check linked CSS/JS/images/fonts")
    parser.add_argument("--max-assets", type=int, default=MAX_ASSETS)
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument("--json", "-j", action="store_true")
    args = parser.parse_args()

    result = audit(args.source, args.include_assets, args.timeout, args.max_assets)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Resources checked: {result['resources_checked']}; issues: {len(result['issues'])}")


if __name__ == "__main__":
    main()
