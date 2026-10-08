#!/usr/bin/env python3
"""Check local SEO signals: NAP, LocalBusiness schema, GBP links, reviews, and maps."""

from __future__ import annotations

import argparse
import re
from typing import Any

import site_crawl
from lib.schema_types import is_local_business_type
from schema_required_props import extract_schema_documents, find_schema_nodes, load_source_html
from seo_common import parse_html, print_json_or_text, issue


PHONE_RE = re.compile(r"(\+?\d[\d\s().-]{7,}\d)")
MAP_PATTERNS = ("google.com/maps", "maps.google.", "bing.com/maps", "openstreetmap.org")
GBP_PATTERNS = ("g.page/", "business.google.com", "search.google.com/local/writereview")


def find_local_business_nodes(documents: list) -> list:
    """Every JSON-LD node whose @type is a LocalBusiness or one of its subtypes."""
    return [row for row in find_schema_nodes(documents)
            if is_local_business_type(row.get("types"))]


def check_local_business_inventory(source: str, inventory_path: str) -> dict[str, Any]:
    """Decide LocalBusiness presence across every HTML page in one crawl."""
    inventory = site_crawl.inventory_for(source, inventory_path)
    pages = site_crawl.html_pages(inventory)
    matches = []
    for key, page in pages.items():
        for node in page.get("schema_nodes") or []:
            if is_local_business_type(node.get("types")):
                matches.append({"url": page.get("final_url") or page.get("url") or key,
                                "types": node.get("types") or []})
    issues = []
    if not matches:
        issues.append(issue("warning", "No LocalBusiness JSON-LD found on any "
                            "crawled page (nor any of its subtypes)", source))
    return {
        "source": source,
        "final_url": source,
        "status": None,
        "fetch_error": inventory.get("fetch_error"),
        "scope": "site",
        "pages_checked": len(pages),
        "local_business_nodes": len(matches),
        "local_business_pages": sorted({row["url"] for row in matches}),
        "phones_detected": [],
        "map_embeds": 0,
        "issues": issues,
    }


def check_local_seo(source: str, timeout: int = 15) -> dict[str, Any]:
    html, final_url, fetch = load_source_html(source, timeout=timeout)
    parsed = parse_html(html, final_url or source) if html else {}
    documents, _ = extract_schema_documents(source, timeout=timeout)
    local_nodes = find_local_business_nodes(documents)
    body_text = parsed.get("body_text", "")
    links = parsed.get("links", [])
    phones = sorted(set(match.group(1).strip() for match in PHONE_RE.finditer(body_text)))
    issues = []
    if not local_nodes:
        # LO-198 asks whether the crawl found LocalBusiness data anywhere. On one
        # page its absence is useful context, but there is no NAP here for LO-200
        # to grade and therefore no page-level verdict to raise.
        issues.append(issue("info", "No LocalBusiness JSON-LD found (nor any of "
                            "its subtypes)", final_url or source))
    for row in local_nodes:
        node = row["node"]
        for prop in ("name", "address", "telephone"):
            if not node.get(prop):
                issues.append(issue("error", f"LocalBusiness is missing {prop}", evidence=row["path"]))
        if not node.get("areaServed") and not node.get("serviceArea"):
            issues.append(issue("info", "LocalBusiness is missing service area signal", evidence=row["path"]))
        if node.get("telephone") and phones and str(node["telephone"]).replace(" ", "") not in "".join(phones).replace(" ", ""):
            issues.append(issue("warning", "Schema telephone does not visibly match page phone text", evidence=row["path"]))
    map_embeds = html.count("google.com/maps") + html.count("maps.google.") + html.count("openstreetmap.org") if html else 0
    if not map_embeds and not any(any(pattern in link["href"] for pattern in MAP_PATTERNS) for link in links):
        issues.append(issue("info", "No map embed or map link found", final_url or source))
    if not any(any(pattern in link["href"] for pattern in GBP_PATTERNS) for link in links):
        issues.append(issue("info", "No Google Business Profile/review link found", final_url or source))
    if "review" not in body_text.lower() and not any(row["node"].get("aggregateRating") for row in local_nodes):
        issues.append(issue("info", "No visible reviews or aggregateRating signal found", final_url or source))
    result = {
        "source": source,
        "final_url": final_url or source,
        "status": fetch.get("status"),
        # A page nobody could read has no LocalBusiness markup and no phone number,
        # and reporting that as a finding is how LO-198 and LO-200 — both `high` —
        # described a host that refused every connection as a business with no local
        # signals.
        "fetch_error": (fetch.get("error")
                        or (None if html else "the page could not be read")),
        "local_business_nodes": len(local_nodes),
        "phones_detected": phones,
        "map_embeds": map_embeds,
        "issues": issues,
    }
    if local_nodes:
        result["nap_complete"] = all(
            all(row["node"].get(prop) for prop in ("name", "address", "telephone"))
            for row in local_nodes
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Check local SEO signals")
    parser.add_argument("source", help="URL or HTML file")
    parser.add_argument("--inventory", default="",
                        help="crawl inventory: check LocalBusiness presence across "
                             "the site instead of repeating it per page")
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument("--json", "-j", action="store_true", help="Output JSON")
    args = parser.parse_args()
    if args.inventory:
        result = check_local_business_inventory(args.source, args.inventory)
    else:
        result = check_local_seo(args.source, timeout=args.timeout)
    lines = [
        f"Local SEO check for {args.source}",
        f"LocalBusiness nodes: {result['local_business_nodes']}  Phones: {len(result['phones_detected'])}  Issues: {len(result['issues'])}",
    ] + [f"[{item['severity']}] {item['message']} {item.get('evidence') or ''}" for item in result["issues"][:30]]
    print_json_or_text(result, args.json, lines)


if __name__ == "__main__":
    from lib.utf8_streams import utf8_streams
    utf8_streams()
    main()
