#!/usr/bin/env python3
"""Build per-URL indexability verdicts."""

from __future__ import annotations

import argparse
import json
import re

from bs4 import BeautifulSoup, NavigableString

import site_crawl
from seo_common import (
    discover_sitemap_urls,
    fetch_robots,
    fetch_url,
    html_parser,
    parse_html,
    parse_sitemap_xml,
    read_urls,
    robots_allowed,
    normalize_url,
)


MAX_SNIPPET_RE = re.compile(r"\bmax-snippet\s*:\s*(-?\d+)", re.I)
NOSNIPPET_RE = re.compile(r"\bnosnippet\b", re.I)


def snippet_controls(html_text: str, x_robots_tag: str | None) -> dict:
    """Snippet restrictions Google reads from this response, with their sources."""
    directives = []
    data_nosnippet_count = 0
    visible_text_outside_data_nosnippet = False
    if html_text:
        soup = BeautifulSoup(html_text, html_parser())
        for tag in soup.find_all("meta"):
            name = str(tag.get("name") or "").strip().lower()
            if name in ("robots", "googlebot"):
                directives.append((f"meta {name}", str(tag.get("content") or "")))
        data_nosnippet_count = len(soup.find_all(attrs={"data-nosnippet": True}))
        visible_text_outside_data_nosnippet = any(
            type(text) is NavigableString
            and bool(text.strip())
            and text.find_parent(["script", "style", "template", "head"]) is None
            and text.find_parent(attrs={"data-nosnippet": True}) is None
            for text in soup.find_all(string=True)
        )
    if x_robots_tag:
        directives.append(("x-robots-tag", str(x_robots_tag)))

    nosnippet_sources = sorted({source for source, value in directives
                                 if NOSNIPPET_RE.search(value)})
    max_snippets = [
        {"source": source, "value": int(match.group(1))}
        for source, value in directives
        for match in MAX_SNIPPET_RE.finditer(value)
    ]
    limited = [entry["value"] for entry in max_snippets if entry["value"] >= 0]
    if limited:
        # Multiple directives combine at the most restrictive value. In particular,
        # zero suppresses the snippet; -1 means unlimited and cannot override it.
        effective_max = min(limited)
    elif any(entry["value"] == -1 for entry in max_snippets):
        effective_max = -1
    else:
        effective_max = max_snippets[0]["value"] if max_snippets else None

    controls = {
        "restricted": bool(nosnippet_sources or limited or data_nosnippet_count),
        "nosnippet": bool(nosnippet_sources),
        "nosnippet_sources": nosnippet_sources,
        "max_snippet": effective_max,
        "max_snippet_sources": max_snippets,
        "data_nosnippet_count": data_nosnippet_count,
        "data_nosnippet_sources": (["html data-nosnippet attribute"]
                                    if data_nosnippet_count else []),
    }
    if html_text or x_robots_tag is not None:
        if (nosnippet_sources or effective_max == 0
                or (data_nosnippet_count
                    and not visible_text_outside_data_nosnippet)):
            controls["snippet_availability"] = "suppressed"
        elif limited or data_nosnippet_count:
            controls["snippet_availability"] = "limited"
        else:
            controls["snippet_availability"] = "full"
    return controls


def urls_from_sitemaps(site: str, timeout: int) -> set[str]:
    urls = set()
    for sm in discover_sitemap_urls(site, timeout=timeout)[:10]:
        fetched = fetch_url(sm, timeout=timeout, max_bytes=8_000_000)
        parsed = parse_sitemap_xml(fetched.get("text") or "", sm)
        urls.update(row["loc"] for row in parsed["urls"])
    return urls


def evaluate(urls: list[str], site: str | None = None, timeout: int = 15) -> dict:
    base = site or (urls[0] if urls else "")
    robots = fetch_robots(base, timeout=timeout) if base else {"parsed": None}
    sitemap_urls = urls_from_sitemaps(base, timeout) if base else set()
    rows = []
    for url in urls:
        url = normalize_url(url)
        allowed, robots_rule = robots_allowed(robots.get("parsed"), url, "Googlebot")
        fetched = fetch_url(url, timeout=timeout, max_bytes=1_500_000)
        headers = fetched.get("headers", {})
        xrobots = headers.get("x-robots-tag") or headers.get("X-Robots-Tag")
        html = {}
        ctype = headers.get("content-type", "")
        html_text = (fetched.get("text") or "") if "html" in ctype else ""
        if html_text:
            html = parse_html(html_text, fetched.get("url") or url)
        snippets = snippet_controls(html_text, xrobots)
        blockers = []
        if not allowed:
            blockers.append("robots.txt disallow")
        if fetched.get("status") != 200:
            blockers.append(f"HTTP {fetched.get('status')}")
        if html.get("meta_robots") and "noindex" in html["meta_robots"].lower():
            blockers.append("meta robots noindex")
        if xrobots and "noindex" in xrobots.lower():
            blockers.append("x-robots-tag noindex")
        if html.get("canonical") and normalize_url(html["canonical"]) != normalize_url(fetched.get("url") or url):
            blockers.append("canonicalized to different URL")
        rows.append({
            "url": url,
            "final_url": fetched.get("url"),
            "status": fetched.get("status"),
            "robots_allowed": allowed,
            "robots_rule": robots_rule,
            "meta_robots": html.get("meta_robots"),
            "x_robots_tag": xrobots,
            "snippet_controls": snippets,
            "canonical": html.get("canonical"),
            "in_sitemap": url in sitemap_urls,
            "redirects": fetched.get("redirect_chain", []),
            "verdict": "indexable" if not blockers else "not_indexable",
            "blockers": blockers,
            "error": fetched.get("error"),
        })
    return {
        "site": normalize_url(base) if base else None,
        "count": len(rows),
        # No URL answered at all. Three `critical` items read `rows.0` — is this page
        # indexable, does it return 200, does robots.txt allow it — and against a host
        # that refused every connection they reported "not indexable" and "robots.txt
        # allows it" as *verdicts*. Not indexable is a claim about a page; nothing was
        # read here. This script was outside the dead-origin sweep because the sweep
        # took its list from one test file's run table and the seven scripts behind the
        # nineteen critical items are tested in another.
        "fetch_error": (None if any(row["status"] == 200 for row in rows)
                        else "no URL could be read"),
        "rows": rows,
    }


def evaluate_inventory(site_url: str, inventory_path: str) -> dict:
    """Report server errors already recorded by the shared crawl."""
    inventory = site_crawl.inventory_for(site_url, inventory_path)
    pages = inventory.get("pages") or {}
    inbound = site_crawl.inbound_map(inventory)
    server_errors = []
    for key, row in pages.items():
        status = row.get("status")
        if isinstance(status, int) and 500 <= status <= 599:
            server_errors.append({
                "url": row.get("url"),
                "status": status,
                "linked_from": sorted(
                    edge["source"] for edge in inbound.get(key, [])),
            })
    server_errors.sort(key=lambda row: row["url"])
    truncated = bool((inventory.get("summary") or {}).get("truncated"))
    out = {
        "site": inventory.get("site"),
        "server_errors": server_errors,
        "summary": {
            "pages": len(pages),
            "server_errors": len(server_errors),
        },
        "truncated": truncated,
        "fetch_error": (inventory.get("fetch_error")
                        or ("no page could be read" if not pages else None)),
    }
    if truncated:
        out["truncated_reason"] = "the shared crawl was truncated"
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate an indexability matrix")
    parser.add_argument("urls", nargs="*")
    parser.add_argument("--url-file")
    parser.add_argument("--site", help="Site URL for robots/sitemap context")
    parser.add_argument("--inventory", default="",
                        help="crawl inventory from site_crawl.py")
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument("--json", "-j", action="store_true")
    args = parser.parse_args()
    if args.inventory:
        site = args.site or (args.urls[0] if args.urls else "")
        result = evaluate_inventory(site, args.inventory)
    else:
        urls = read_urls(args.urls, args.url_file)
        result = evaluate(urls, args.site, args.timeout)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if args.inventory:
            for row in result["server_errors"]:
                print(f"{row['status']}\t{row['url']}")
            print(f"Server errors: {result['summary']['server_errors']}")
        else:
            for row in result["rows"]:
                print(f"{row['verdict']}\t{row['status']}\t{row['url']}\t{', '.join(row['blockers'])}")


if __name__ == "__main__":
    main()
