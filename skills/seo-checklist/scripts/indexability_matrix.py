#!/usr/bin/env python3
"""Build per-URL indexability verdicts."""

from __future__ import annotations

from lib import python_floor  # noqa: F401

import argparse
import json
import re

from bs4 import BeautifulSoup, NavigableString

import site_crawl
from seo_common import (read_as_url,
    SITEMAP_BYTES_BUDGET,
    SITEMAP_URLS_BUDGET,
    carries_content,
    discover_sitemap_urls,
    fetch_robots,
    fetch_url,
    html_parser,
    parse_html,
    parse_sitemap_xml,
    read_urls,
    refused_kind,
    robots_allowed,
    normalize_url,
    same_host,
    status_class,
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


def urls_from_sitemaps(site: str, timeout: int, unread: list[str] | None = None,
                       robots: dict | None = None) -> set[str] | None:
    """Every URL the site's own sitemaps list, or None when any of them was left unread
    or unkept: a URL missing from the ones held is then not known to be missing.
    `unread`, when given, receives why.

    The budgets returned None from 0.168.0 and 0.172.0. Four other ways of not reading
    a sitemap did not, and each reported `in_sitemap: false` about URLs nobody had
    looked for (F14): a location past the tenth, never requested; an index, whose
    children this does not follow; a location that gave no answer (refused by this
    audit's guard, timed out, a 5xx); a sitemap on another host. A location that
    answers 4xx, or a document that is not a sitemap, lists nothing Google could read
    either, so it stays an answer. `robots`, when the caller already read it, is the one
    discovery reads; a robots.txt that gave no answer may declare sitemaps nobody saw.
    """
    why = unread if unread is not None else []
    urls = set()
    read_bytes = 0
    if robots is not None:
        status = (robots.get("fetch") or {}).get("status")
        if status is None or status >= 500 or status == 429:
            why.append("robots.txt gave no answer, so the sitemaps it declares are "
                       "unknown: " + str((robots.get("fetch") or {}).get("error")
                                         or f"HTTP {status}"))
        locations = discover_sitemap_urls(site, timeout=timeout, robots=robots)
    else:
        locations = discover_sitemap_urls(site, timeout=timeout)
    past = locations[10:]
    if past:
        why.append(f"{len(past)} sitemap location(s) past the tenth not read: "
                   + ", ".join(past))
    for sm in locations[:10]:
        if not same_host(site, sm):
            # Never requested: see site_crawl.load_sitemap_urls.
            why.append(f"a sitemap on another host is not requested: {sm}")
            continue
        if read_bytes >= SITEMAP_BYTES_BUDGET:
            why.append(f"the sitemap byte budget ({SITEMAP_BYTES_BUDGET} bytes) was "
                       f"spent before {sm}")
            return None
        fetched = fetch_url(sm, timeout=timeout, max_bytes=8_000_000)
        read_bytes += fetched.get("bytes") or 0     # the body, not its characters
        status = fetched.get("status")
        if not carries_content(status):
            if status is None or status >= 500 or status == 429:
                why.append(f"{sm} gave no sitemap to read: "
                           f"{fetched.get('error') or f'HTTP {status}'}")
            continue
        parsed = parse_sitemap_xml(fetched.get("text") or "", sm)
        if parsed["type"] == "sitemapindex":
            why.append(f"{sm} is an index; its {len(parsed['sitemaps'])} sitemap(s) "
                       f"are not read")
            continue
        urls.update(row["loc"] for row in parsed["urls"])
        if len(urls) > SITEMAP_URLS_BUDGET:
            why.append(f"the sitemap URL budget ({SITEMAP_URLS_BUDGET}) was reached")
            return None
    return None if why else urls


def evaluate(urls: list[str], site: str | None = None, timeout: int = 15) -> dict:
    base = site or (urls[0] if urls else "")
    robots = fetch_robots(base, timeout=timeout) if base else {"parsed": None}
    # Unread, not empty: a robots.txt this audit's guard refused allows nothing and
    # forbids nothing we know of, and `robots_allowed` would read it as allowing all.
    robots_refused = (robots.get("fetch") or {}).get("error_kind") == "blocked"
    unread: list[str] = []
    sitemap_urls = urls_from_sitemaps(base, timeout, unread, robots) if base else set()
    rows = []
    for url in urls:
        url = normalize_url(url)
        allowed, robots_rule = robots_allowed(robots.get("parsed"), url, "Googlebot")
        if robots_refused:
            allowed = None
            robots_rule = f"robots.txt not requested: {robots['fetch'].get('error')}"
        fetched = fetch_url(url, timeout=timeout, max_bytes=1_500_000)
        fetched_status_class = status_class(fetched.get("status"))
        headers = fetched.get("headers", {})
        xrobots = headers.get("x-robots-tag") or headers.get("X-Robots-Tag")
        html = {}
        ctype = headers.get("content-type", "")
        html_text = (fetched.get("text") or "") if "html" in ctype else ""
        if html_text:
            html = parse_html(html_text, fetched.get("url") or url)
        snippets = snippet_controls(html_text, xrobots)
        blockers = []
        if allowed is False:
            blockers.append("robots.txt disallow")
        # Google's HTTP-status guidance treats 2xx content other than 204 as
        # processable, so those answers do not make the page non-indexable.
        if fetched_status_class not in ("ok", "other_success"):
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
            "status_class": fetched_status_class,
            "robots_allowed": allowed,
            "robots_rule": robots_rule,
            "meta_robots": html.get("meta_robots"),
            "x_robots_tag": xrobots,
            "snippet_controls": snippets,
            "canonical": html.get("canonical"),
            "in_sitemap": None if sitemap_urls is None else url in sitemap_urls,
            "redirects": fetched.get("redirect_chain", []),
            # Indexable only if nothing blocks it and robots.txt was read: a blocker
            # found stands, but no blocker over an unread robots.txt is unknown.
            "verdict": ("not_indexable" if blockers
                        else None if allowed is None else "indexable"),
            "blockers": blockers,
            "error": fetched.get("error"),
            "error_kind": fetched.get("error_kind"),
        })
        if allowed is None:
            # Absent rather than null: CI-005 reads it truthy, and null would fail
            # the site on a file nobody read. Absent is NO_DATA (`robots_rule` says why).
            del rows[-1]["robots_allowed"]
    return {
        "site": normalize_url(base) if base else None,
        "count": len(rows),
        # Nothing answered at all. Three `critical` items read `rows.0` — is this page
        # indexable, does it return 200, does robots.txt allow it — and against a host
        # that refused every connection they once reported "not indexable" and
        # "robots.txt allows it" as verdicts. Until 0.130.0 this also called every
        # answer but 200 unread, so CI-003 could not fail: a 404 is an answer, and its
        # status is the finding CI-003 reports. Only the absence of every answer makes
        # the URL unread.
        "fetch_error": (None if any(row["status"] is not None for row in rows)
                         else "no URL could be read"),
        "fetch_error_kind": refused_kind(row["error_kind"] for row in rows),
        # Why `in_sitemap` is null on every row, or null when it is known (HTTP-10).
        "sitemap_membership_unknown": "; ".join(unread) or None,
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
        if status_class(status) == "server_error":
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
        "fetch_error_kind": inventory.get("fetch_error_kind"),
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
    args.urls = [read_as_url(url) for url in args.urls]
    args.site = read_as_url(args.site)
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
            if result["sitemap_membership_unknown"]:
                print(f"Sitemap membership unknown: {result['sitemap_membership_unknown']}")


if __name__ == "__main__":
    from lib.utf8_streams import utf8_streams
    utf8_streams()
    from lib.typed_credential import credentials_beside_argv
    credentials_beside_argv()
    main()
