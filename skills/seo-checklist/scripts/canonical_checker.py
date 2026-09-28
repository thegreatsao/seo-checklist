#!/usr/bin/env python3
"""Check canonical tags for self/cross-domain/chained targets."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict

import site_crawl
from seo_common import fetch_url, issue, normalize_url, parse_html, read_urls, same_host


# basis: convention — the same hundred target requests as gsc_links_csv.MAX_TARGETS.
MAX_TARGET_FETCHES = 100


def check_canonicals(urls: list[str], timeout: int = 15, check_targets: bool = False) -> dict:
    rows = []
    issues = []
    canonical_to_pages = defaultdict(list)
    for url in urls:
        fetched = fetch_url(url, timeout=timeout, max_bytes=1_500_000)
        row = {"url": normalize_url(url), "status": fetched.get("status"), "final_url": fetched.get("url"), "canonical": None, "verdict": "unknown", "issues": []}
        if fetched.get("text"):
            html = parse_html(fetched["text"], fetched.get("url") or url)
            row["canonical"] = html.get("canonical")
        if not row["canonical"]:
            row["verdict"] = "missing"
            row["issues"].append("missing canonical")
            issues.append(issue("warning", "Missing canonical", row["url"]))
        else:
            canonical = normalize_url(row["canonical"], fetched.get("url") or url)
            row["canonical"] = canonical
            canonical_to_pages[canonical].append(row["url"])
            if canonical == normalize_url(fetched.get("url") or url):
                row["verdict"] = "self_canonical"
            elif not same_host(row["url"], canonical):
                row["verdict"] = "cross_host"
                row["issues"].append("cross-host canonical")
                issues.append(issue("warning", "Cross-host canonical", row["url"], canonical))
            else:
                row["verdict"] = "canonicalized"
            if check_targets:
                target = fetch_url(canonical, timeout=timeout, max_bytes=1_000_000)
                row["canonical_status"] = target.get("status")
                if target.get("status") != 200:
                    row["issues"].append(f"canonical target HTTP {target.get('status')}")
                    issues.append(issue("error", "Canonical target is not 200", row["url"], str(target.get("status"))))
                if target.get("text"):
                    target_html = parse_html(target["text"], target.get("url") or canonical)
                    if target_html.get("canonical") and normalize_url(target_html["canonical"]) != canonical:
                        row["issues"].append("canonical chain detected")
                        issues.append(issue("warning", "Canonical target points elsewhere", row["url"], target_html["canonical"]))
        rows.append(row)
    duplicates = {canonical: pages for canonical, pages in canonical_to_pages.items() if len(pages) > 1}
    return {
        "count": len(rows),
        "rows": rows,
        "duplicate_canonical_targets": duplicates,
        "issues": issues,
        # A page with no canonical and a page nobody could fetch are not the same
        # finding, and "missing canonical" was reported for both — a `critical` verdict
        # (CI-009) about a host that answered nothing.
        "fetch_error": (None if any(row.get("status") == 200 for row in rows)
                        else "no URL could be read"),
    }


def check_inventory(site_url: str, inventory_path: str,
                    timeout: int = 15) -> dict:
    """Check the canonical evidence already held by a shared crawl."""
    inventory = site_crawl.inventory_for(site_url, inventory_path)
    pages = inventory.get("pages") or {}
    rows = []
    issues = []
    canonical_to_pages = defaultdict(list)
    target_cache = {}
    target_fetches = 0
    unchecked_targets = set()

    for key, source in sorted(pages.items()):
        if not source.get("html") or source.get("status") != 200:
            continue
        page_url = source.get("url") or source.get("final_url") or key
        final_url = source.get("final_url") or page_url
        row = {
            "url": normalize_url(page_url),
            "status": source.get("status"),
            "final_url": final_url,
            "canonical": None,
            "verdict": "unknown",
            "issues": [],
        }
        raw_canonical = source.get("canonical")
        if not raw_canonical:
            row["verdict"] = "missing"
            row["issues"].append("missing canonical")
            issues.append(issue("warning", "Missing canonical", row["url"]))
            rows.append(row)
            continue

        canonical = normalize_url(raw_canonical, page_url)
        row["canonical"] = canonical
        canonical_to_pages[canonical].append(row["url"])
        # Against where the page landed as well as where it was asked for, as the
        # page path compares with the fetched URL: an entry that redirects to
        # /home/ and names /home/ is canonical to itself.
        if site_crawl.page_key(canonical, page_url) in {site_crawl.page_key(page_url),
                                                       site_crawl.page_key(final_url)}:
            row["verdict"] = "self_canonical"
            rows.append(row)
            continue
        if not same_host(row["url"], canonical):
            row["verdict"] = "cross_host"
            row["issues"].append("cross-host canonical")
            issues.append(issue("warning", "Cross-host canonical", row["url"],
                                canonical))
        else:
            row["verdict"] = "canonicalized"

        target_key = site_crawl.page_key(canonical, page_url)
        if target_key not in target_cache:
            if target_key in pages:
                target_cache[target_key] = pages[target_key]
            elif target_fetches < MAX_TARGET_FETCHES:
                target_cache[target_key] = fetch_url(
                    canonical, timeout=timeout, max_bytes=1_000_000,
                    respect_robots=True)
                target_fetches += 1
            else:
                target_cache[target_key] = None
        target = target_cache[target_key]
        if target is None:
            row["canonical_status"] = None
            unchecked_targets.add(target_key)
            rows.append(row)
            continue

        target_status = target.get("status")
        row["canonical_status"] = target_status
        if target_status is None or target.get("error_kind") == "robots":
            unchecked_targets.add(target_key)
            rows.append(row)
            continue
        if target_status != 200:
            row["issues"].append(f"canonical target HTTP {target_status}")
            issues.append(issue("error", "Canonical target is not 200",
                                row["url"], str(target_status)))

        target_canonical = target.get("canonical")
        if target_canonical is None and target.get("text"):
            target_html = parse_html(target["text"], target.get("url") or canonical)
            target_canonical = target_html.get("canonical")
        if (target_canonical
                and site_crawl.page_key(target_canonical, canonical) != target_key):
            row["issues"].append("canonical chain detected")
            issues.append(issue("warning", "Canonical target points elsewhere",
                                row["url"], target_canonical))
        rows.append(row)

    duplicates = {canonical: page_urls
                  for canonical, page_urls in canonical_to_pages.items()
                  if len(page_urls) > 1}
    reasons = []
    if (inventory.get("summary") or {}).get("truncated"):
        reasons.append("the shared crawl was truncated")
    if unchecked_targets:
        reasons.append(
            f"{len(unchecked_targets)} canonical target(s) could not be checked")
    out = {
        "count": len(rows),
        "rows": rows,
        "duplicate_canonical_targets": duplicates,
        "issues": issues,
        "fetch_error": (inventory.get("fetch_error")
                        or (None if rows else "no URL could be read")),
        "truncated": bool(reasons),
        "scope": "site",
    }
    if reasons:
        out["truncated_reason"] = "; ".join(reasons)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Check canonical tags")
    parser.add_argument("urls", nargs="*")
    parser.add_argument("--url-file")
    parser.add_argument("--check-targets", action="store_true")
    parser.add_argument("--inventory", default="",
                        help="crawl inventory from site_crawl.py")
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument("--json", "-j", action="store_true")
    args = parser.parse_args()
    if args.inventory:
        if len(args.urls) != 1 or args.url_file:
            parser.error("--inventory requires one positional URL")
        result = check_inventory(args.urls[0], args.inventory, args.timeout)
    else:
        result = check_canonicals(read_urls(args.urls, args.url_file), args.timeout, args.check_targets)
    print(json.dumps(result, indent=2) if args.json else "\n".join(f"{r['verdict']}\t{r['url']}\t{r.get('canonical') or ''}" for r in result["rows"]))


if __name__ == "__main__":
    main()
