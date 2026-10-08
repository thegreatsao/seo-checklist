#!/usr/bin/env python3
"""Audit third-party scripts and blocking JavaScript tags."""

from __future__ import annotations

import argparse
import json
from urllib.parse import urlparse

from seo_common import (BeautifulSoup, fetch_url, html_parser, load_source,
                        require_bs4, same_host)


KNOWN_TAGS = {
    "googletagmanager.com": "Google Tag Manager",
    "google-analytics.com": "Google Analytics",
    "googlesyndication.com": "Google Ads",
    "doubleclick.net": "Google Ads",
    "connect.facebook.net": "Meta Pixel",
    "bat.bing.com": "Microsoft Advertising",
    "hotjar.com": "Hotjar",
    "clarity.ms": "Microsoft Clarity",
    "segment.com": "Segment",
    "cdn.segment.com": "Segment",
    "intercom.io": "Intercom",
    "js.stripe.com": "Stripe",
}


# basis: inherited — eight third-party scripts, present at import. Round, and the sort
#  of number a performance blog post quotes; nothing here measured what an eighth tag
#  costs that a seventh did not.
MANY_THIRD_PARTY_SCRIPTS = 8
# basis: inherited — 300KB of third-party JavaScript, present at import.
THIRD_PARTY_BYTES_WARN = 300_000


def _script_category(src: str) -> str | None:
    host = urlparse(src).netloc.lower()
    for domain, label in KNOWN_TAGS.items():
        if host == domain or host.endswith(f".{domain}"):
            return label
    return None


def _is_third_party(src: str, page_url: str) -> bool:
    if not src.startswith(("http://", "https://")):
        return False
    if not page_url.startswith(("http://", "https://")):
        return True
    return not same_host(src, page_url)


def audit(source: str, fetch_scripts: bool = False, timeout: int = 15) -> dict:
    html, url, fetched = load_source(source, timeout=timeout)
    require_bs4()
    soup = BeautifulSoup(html or "", html_parser())
    scripts = []
    issues = []

    for tag in soup.find_all("script"):
        src = tag.get("src") or ""
        row = {
            "src": src,
            "inline": not bool(src),
            "async": tag.has_attr("async"),
            "defer": tag.has_attr("defer"),
            "type": tag.get("type") or "",
            "third_party": _is_third_party(src, url),
            "known_tag": _script_category(src),
            "content_length": None,
            "status": None,
            "blocking": bool(src) and not tag.has_attr("async") and not tag.has_attr("defer") and tag.get("type") != "module",
        }
        if row["third_party"] and row["blocking"]:
            issues.append({"severity": "warning", "message": "Third-party script can block rendering", "url": src})
        if row["third_party"] and not row["known_tag"]:
            issues.append({"severity": "info", "message": "Unclassified third-party script", "url": src})
        if fetch_scripts and src.startswith(("http://", "https://")):
            head = fetch_url(src, method="HEAD", timeout=timeout)
            row["status"] = head.get("status")
            length = head.get("headers", {}).get("content-length")
            row["content_length"] = int(length) if length and length.isdigit() else None
        scripts.append(row)

    third_party = [row for row in scripts if row["third_party"]]
    blocking_third_party = [row for row in third_party if row["blocking"]]
    total_bytes = sum(row["content_length"] or 0 for row in third_party)
    if len(third_party) >= MANY_THIRD_PARTY_SCRIPTS:
        issues.append({"severity": "warning", "message": "Many third-party script tags detected", "evidence": str(len(third_party))})
    if total_bytes > THIRD_PARTY_BYTES_WARN:
        issues.append({"severity": "warning", "message": "Third-party script transfer size is high", "evidence": f"{total_bytes} bytes"})

    return {
        "url": url or source,
        "script_count": len(scripts),
        "third_party_count": len(third_party),
        "blocking_third_party_count": len(blocking_third_party),
        "third_party_bytes": total_bytes if fetch_scripts else None,
        "issues": issues,
        "scripts": scripts,
        "fetch_error": fetched.get("error"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit third-party and blocking script tags")
    parser.add_argument("source", help="URL or local HTML file")
    parser.add_argument("--fetch-scripts", action="store_true", help="HEAD external script URLs for status and byte size")
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument("--json", "-j", action="store_true")
    args = parser.parse_args()

    result = audit(args.source, args.fetch_scripts, args.timeout)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(
            f"Scripts: {result['script_count']}; third-party: {result['third_party_count']}; "
            f"blocking third-party: {result['blocking_third_party_count']}"
        )


if __name__ == "__main__":
    from lib.utf8_streams import utf8_streams
    utf8_streams()
    main()
