#!/usr/bin/env python3
"""Reconcile sitemap membership with Google's index in both directions.

URL Inspection answers whether submitted sitemap URLs are indexed. Search
Analytics supplies the reverse evidence: a page that received impressions was
indexed, so it belongs in a sitemap unless the site deliberately excludes it.

Usage:
    python gsc_sitemap_reconcile.py https://example.com/ \
        --property sc-domain:example.com --credentials key.json --json
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timedelta
from urllib.parse import urlparse


def _utf8_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


_utf8_stdout()

# basis: convention — 100 inspections are 5% of the 2000-per-day property quota.
MAX_URLS = 100
# basis: convention — 120s leaves one minute of the runner's default timeout.
TIME_BUDGET_S = 120
# basis: convention — four workers overlap latency far below the 600/minute quota.
INSPECT_WORKERS = 4
# basis: standard — 25000 is Search Analytics' maximum row count per request.
ROW_LIMIT = 25000

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from gsc_checker import build_service
    # The socket bound is imported rather than copied: a second `30` would be one
    # more constant to keep in step with the script it was copied from.
    from gsc_url_inspection import SOCKET_TIMEOUT, classify_coverage
    from seo_common import discover_sitemap_urls, normalize_url, same_host
    from site_crawl import load_sitemap_urls, page_key
except ImportError:
    print("Error: companion SEO checklist scripts must be importable")
    sys.exit(1)


def _base_result(site_url: str, prop: str) -> dict:
    return {
        "site": site_url,
        "property": prop,
        "sitemap_source": None,
        "sitemaps_checked": [],
        "sitemap_errors": [],
        "period": {"start": None, "end": None},
        "not_indexed": [],
        "undecided": [],
        "indexed_not_in_sitemap": [],
        "truncated": False,
        "error": None,
    }


def _fail(result: dict, error: Exception | str, kind: str) -> dict:
    result["error"] = str(error)[:500]
    result["error_kind"] = kind
    result.pop("summary", None)
    result.pop("issues", None)
    return result


def _inspect_sitemap_urls(urls: list[str], prop: str, credentials: str,
                          max_urls: int) -> tuple[list[dict], bool]:
    """Inspect a bounded prefix, building one API service per worker thread."""
    candidates = urls[:max(0, max_urls)]
    if not candidates:
        return [], False

    local = threading.local()

    def inspect_one(url: str) -> dict:
        try:
            if not hasattr(local, "service"):
                local.service = build_service(credentials)
            response = local.service.urlInspection().index().inspect(body={
                "inspectionUrl": url,
                "siteUrl": prop,
                "languageCode": "en-US",
            }).execute()
            state = ((response.get("inspectionResult") or {})
                     .get("indexStatusResult", {}).get("coverageState"))
            return {"url": url, "coverage_state": state,
                    "indexed": classify_coverage(state)}
        except Exception as exc:
            return {"url": url, "error": str(exc)[:300]}

    started = time.monotonic()
    submitted = 0
    stopped_for_time = False
    by_url: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=INSPECT_WORKERS) as pool:
        pending = set()
        while submitted < len(candidates) and len(pending) < INSPECT_WORKERS:
            pending.add(pool.submit(inspect_one, candidates[submitted]))
            submitted += 1

        while pending:
            done, pending = wait(pending, return_when=FIRST_COMPLETED)
            for future in done:
                record = future.result()
                by_url[record["url"]] = record
            for _ in done:
                if submitted >= len(candidates):
                    break
                if time.monotonic() - started >= TIME_BUDGET_S:
                    stopped_for_time = True
                    break
                pending.add(pool.submit(inspect_one, candidates[submitted]))
                submitted += 1
            if (submitted < len(candidates)
                    and time.monotonic() - started >= TIME_BUDGET_S):
                stopped_for_time = True

    return [by_url[url] for url in candidates[:submitted]], stopped_for_time


def _search_analytics_pages(service, prop: str, site_url: str,
                            days: int) -> tuple[set[str], str, str, int]:
    end = datetime.now().date()
    start = end - timedelta(days=days)
    body = {
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "dimensions": ["page"],
        "rowLimit": ROW_LIMIT,
    }
    response = service.searchanalytics().query(siteUrl=prop, body=body).execute()
    rows = response.get("rows", [])
    pages = {
        page_key(row["keys"][0])
        for row in rows
        if row.get("keys") and same_host(site_url, row["keys"][0])
    }
    return pages, start.isoformat(), end.isoformat(), len(rows)


def analyze(site_url: str, prop: str, credentials: str, max_urls: int = MAX_URLS,
            days: int = 28) -> dict:
    result = _base_result(site_url, prop)
    socket.setdefaulttimeout(SOCKET_TIMEOUT)

    try:
        service = build_service(credentials)
    except OSError as exc:
        return _fail(result, exc, "input")
    except Exception as exc:
        return _fail(result, exc, "service")

    try:
        response = service.sitemaps().list(siteUrl=prop).execute()
    except Exception as exc:
        return _fail(result, exc, "service")

    paths = [row["path"] for row in response.get("sitemap", []) if row.get("path")]
    discovered_sources = {}
    if paths:
        result["sitemap_source"] = "submitted"
    else:
        discovered = discover_sitemap_urls(site_url, with_source=True)
        paths = [url for url, _source in discovered]
        discovered_sources = {
            normalize_url(url, site_url): source for url, source in discovered
        }
        result["sitemap_source"] = "discovered"

    sitemap = load_sitemap_urls(site_url, sitemap_urls=paths)
    urls = sitemap.get("urls", [])
    result["sitemaps_checked"] = sitemap.get("sitemaps_checked", [])
    result["sitemap_errors"] = [
        row for row in sitemap.get("errors", [])
        if not (
            discovered_sources.get(normalize_url(row.get("url") or "", site_url))
            == "probed" and row.get("status") in (404, 410)
        )
    ]
    unvisited = sitemap.get("unvisited", [])
    if not urls and result["sitemap_errors"]:
        failed = ", ".join(
            str(row.get("url") or "unknown sitemap")
            for row in result["sitemap_errors"]
        )
        return _fail(result, f"Could not read sitemap(s): {failed}", "unread")

    inspected, stopped_for_time = _inspect_sitemap_urls(
        urls, prop, credentials, max_urls)
    not_indexed = [
        {"url": row["url"], "coverage_state": row["coverage_state"]}
        for row in inspected if row.get("indexed") is False
    ]
    undecided = []
    for row in inspected:
        if "error" in row:
            undecided.append({"url": row["url"], "error": row["error"]})
        elif row.get("indexed") is None:
            undecided.append({"url": row["url"],
                              "coverage_state": row.get("coverage_state")})
    result["not_indexed"] = not_indexed
    result["undecided"] = undecided
    if inspected and all("error" in row for row in inspected):
        return _fail(result, "Every URL Inspection request failed", "service")

    try:
        impression_pages, start, end, analytics_rows = _search_analytics_pages(
            service, prop, site_url, days)
    except Exception as exc:
        return _fail(result, exc, "service")

    sitemap_keys = {page_key(url) for url in urls}
    missing_all = sorted(impression_pages - sitemap_keys)
    result["period"] = {"start": start, "end": end}
    result["indexed_not_in_sitemap"] = missing_all[:50]

    indexed = sum(row.get("indexed") is True for row in inspected)
    sitemap_complete = not result["sitemap_errors"] and not unvisited
    result["summary"] = {
        "sitemap_urls": len(urls),
        "inspected": len(inspected),
        "indexed": indexed,
        "not_indexed": len(not_indexed),
        "undecided": len(undecided),
        "pages_with_impressions": len(impression_pages),
        "indexed_not_in_sitemap": len(missing_all),
        "indexed_not_in_sitemap_counted": sitemap_complete,
        "unreconciled": (len(not_indexed)
                         + (len(missing_all) if sitemap_complete else 0)),
    }

    reasons = []
    if len(urls) > max_urls:
        reasons.append(
            f"inspection was capped at the first {max_urls} of {len(urls)} "
            "sitemap URLs (the per-run cap)")
    if stopped_for_time:
        reasons.append(
            f"the {TIME_BUDGET_S} s time budget stopped inspection after "
            f"{len(inspected)} URLs")
    errored = sum("error" in row for row in inspected)
    unknown = len(undecided) - errored
    if errored:
        reasons.append(
            f"{errored} inspection{'s' if errored != 1 else ''} errored, so "
            "their index status is undecided")
    if unknown:
        reasons.append(
            f"{unknown} inspection{'s' if unknown != 1 else ''} gave no "
            "recognisable coverage state")
    if analytics_rows >= ROW_LIMIT:
        reasons.append(
            f"Search Analytics returned the {ROW_LIMIT}-row maximum, so pages "
            "past it were not compared")
    if result["sitemap_errors"]:
        count = len(result["sitemap_errors"])
        reasons.append(
            f"{count} sitemap{'s' if count != 1 else ''} could not be read, so "
            "indexed pages missing from the sitemap were not counted")
    if unvisited:
        count = len(unvisited)
        reasons.append(
            f"the sitemap walk reached its cap with {count} sitemap"
            f"{'s' if count != 1 else ''} unread, so indexed pages missing from the sitemap were not counted")
    result["truncated"] = bool(reasons)
    if reasons:
        result["truncated_reason"] = "; ".join(reasons)

    issues = []
    if not_indexed:
        issues.append({
            "severity": "medium",
            "type": "sitemap_urls_not_indexed",
            "count": len(not_indexed),
            "finding": f"{len(not_indexed)} sitemap URL(s) are not indexed by Google",
            "fix": "Fix the indexing cause or remove these URLs from the sitemap",
            "urls": [row["url"] for row in not_indexed[:10]],
        })
    if missing_all:
        issues.append({
            "severity": "medium",
            "type": "indexed_not_in_sitemap",
            "count": len(missing_all),
            "finding": f"{len(missing_all)} indexed page(s) are missing from the sitemap",
            "fix": "Add these indexed pages to an appropriate sitemap",
            "urls": missing_all[:10],
        })
    result["issues"] = issues
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reconcile sitemap URLs with Google's index through Search Console")
    parser.add_argument("site_url", help="site URL used to discover and read sitemaps")
    parser.add_argument("--property", default="",
                        help="GSC property (default: sc-domain:<host without www.>)")
    parser.add_argument("--credentials", default="",
                        help="Service account JSON (or GSC_CREDENTIALS_PATH / GV_SA_KEY)")
    parser.add_argument("--max-urls", type=int, default=MAX_URLS)
    parser.add_argument("--days", type=int, default=28)
    parser.add_argument("--json", "-j", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    credentials = (args.credentials or os.environ.get("GSC_CREDENTIALS_PATH")
                   or os.environ.get("GV_SA_KEY")
                   or os.path.expanduser(
                       "~/.config/gcloud/gsc-service-account.json"))
    prop = args.property
    if not prop:
        host = urlparse(args.site_url).netloc
        prop = f"sc-domain:{host[4:] if host.startswith('www.') else host}"

    result = analyze(args.site_url, prop, credentials, args.max_urls, args.days)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return
    if result["error"]:
        print(f"Sitemap reconciliation failed: {result['error']}")
        return
    summary = result["summary"]
    print(f"Sitemap/index reconciliation for {result['property']}")
    print(f"  sitemap URLs:             {summary['sitemap_urls']}")
    print(f"  inspected:                {summary['inspected']}")
    print(f"  sitemap URLs not indexed: {summary['not_indexed']}")
    print(f"  indexed pages not listed: {summary['indexed_not_in_sitemap']}")
    print(f"  unreconciled:             {summary['unreconciled']}")
    if result["truncated"]:
        print(f"  partial input:            {result['truncated_reason']}")


if __name__ == "__main__":
    main()
