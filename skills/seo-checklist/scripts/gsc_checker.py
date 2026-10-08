#!/usr/bin/env python3
"""
Google Search Console Data Checker

Connects to the Google Search Console API (v3) to pull performance data,
crawl errors, and sitemaps for a verified property. Outputs JSON for LLM
analysis in the SEO audit pipeline.

Requirements:
    pip install google-api-python-client google-auth-oauthlib
    A service account or OAuth2 credentials JSON file.

Usage:
    python gsc_checker.py https://example.com --credentials creds.json --json
    python gsc_checker.py https://example.com --credentials creds.json --days 28
    python gsc_checker.py https://example.com --credentials creds.json --query "red team"
"""

import argparse
import json
import sys
from datetime import datetime, timedelta

try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    HAS_GSC_DEPS = True
except ImportError:
    HAS_GSC_DEPS = False


# The opportunity rules were all present at import. The two sample floors governing a
# CTR comparison are now justified by binomial precision; the other numbers retain the
# inherited values and name the evidence that would be needed to settle them.
# basis: inherited — positions 4-20, present at import. Blocker: one property in one language cannot establish a cross-market ranking-opportunity band; this needs many properties across markets.
STRIKING_DISTANCE_MIN_POSITION = 4
# basis: inherited — position 20, the far end of the band above. Blocker: one property in one language cannot establish a cross-market ranking-opportunity band; this needs many properties across markets.
STRIKING_DISTANCE_MAX_POSITION = 20
# basis: inherited — fifty impressions gates an average position, so binomial CTR precision does not apply. Blocker: only five pilot queries reached the relevant 50-199 bucket; this needs measured query-level mean-position variation.
STRIKING_DISTANCE_MIN_IMPRESSIONS = 50
# basis: inherited — top three positions, present at import. Blocker: one property in one language cannot establish normal CTR by position across markets; this needs many properties across markets.
TOP_POSITION_MAX = 3
# basis: inherited — five percent CTR, present at import. Blocker: one property's non-monotonic CTR-by-position curve cannot establish normal CTR across markets; this needs many properties across markets.
LOW_CTR_PCT = 5
# basis: measured — corpus=binomial CTR proportion at the declared 5 percent threshold; date=2026-08-10; method=normal-approximation interval with z=1.96, applying the rule that the 95% confidence interval half-width on measured CTR must not exceed the threshold being tested. Minimum 73 impressions, so floor 100 has 27 impressions of headroom.
LOW_CTR_MIN_IMPRESSIONS = 100
# basis: measured — corpus=binomial CTR proportion at the declared 2 percent threshold; date=2026-08-10; method=normal-approximation interval with z=1.96, applying the rule that the 95% confidence interval half-width on measured CTR must not exceed the threshold being tested. Minimum 189 impressions, so floor 200 has 11 impressions of headroom.
HIGH_IMPRESSIONS = 200
# basis: inherited — two percent CTR, present at import. Blocker: one property's non-monotonic CTR-by-position curve cannot establish normal CTR across markets; this needs many properties across markets.
VERY_LOW_CTR_PCT = 2

SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]


# ---------------------------------------------------------------------------
# GSC client
# ---------------------------------------------------------------------------

def build_service(credentials_path: str):
    """Build the Search Console API service."""
    if not HAS_GSC_DEPS:
        print("Error: google-api-python-client and google-auth-oauthlib required.", file=sys.stderr)
        print("Install with: pip install google-api-python-client google-auth-oauthlib", file=sys.stderr)
        sys.exit(1)

    creds = service_account.Credentials.from_service_account_file(
        credentials_path, scopes=SCOPES
    )
    return build("searchconsole", "v1", credentials=creds)


# ---------------------------------------------------------------------------
# Data retrieval
# ---------------------------------------------------------------------------

def get_performance_data(
    service,
    site_url: str,
    days: int = 28,
    query_filter: str = "",
    row_limit: int = 25,
) -> dict:
    """
    Pull search performance data: impressions, clicks, CTR, position.
    Groups by query and page.
    """
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    body = {
        "startDate": start_date,
        "endDate": end_date,
        "dimensions": ["query", "page"],
        "rowLimit": row_limit,
        "startRow": 0,
    }

    if query_filter:
        body["dimensionFilterGroups"] = [{
            "filters": [{
                "dimension": "query",
                "operator": "contains",
                "expression": query_filter,
            }]
        }]

    try:
        resp = service.searchanalytics().query(siteUrl=site_url, body=body).execute()
        rows = resp.get("rows", [])
        return {
            "period": f"{start_date} to {end_date}",
            "total_rows": len(rows),
            "data": [
                {
                    "query": r["keys"][0],
                    "page": r["keys"][1],
                    "clicks": r.get("clicks", 0),
                    "impressions": r.get("impressions", 0),
                    "ctr": round(r.get("ctr", 0) * 100, 2),
                    "position": round(r.get("position", 0), 1),
                }
                for r in rows
            ],
        }
    except Exception as exc:
        return {"error": str(exc), "period": f"{start_date} to {end_date}"}


def get_sitemaps(service, site_url: str) -> list:
    """List submitted sitemaps and their status."""
    try:
        resp = service.sitemaps().list(siteUrl=site_url).execute()
        return [
            {
                "path": s.get("path"),
                "type": s.get("type"),
                "last_submitted": s.get("lastSubmitted"),
                "last_downloaded": s.get("lastDownloaded"),
                "is_pending": s.get("isPending", False),
                "errors": s.get("errors", 0),
                "warnings": s.get("warnings", 0),
                "contents": s.get("contents", []),
            }
            for s in resp.get("sitemap", [])
        ]
    except Exception as exc:
        return [{"error": str(exc)}]


def get_url_inspection(service, site_url: str, inspect_url: str) -> dict:
    """Inspect a single URL for indexing status."""
    try:
        resp = service.urlInspection().index().inspect(
            body={"inspectionUrl": inspect_url, "siteUrl": site_url}
        ).execute()
        result = resp.get("inspectionResult", {})
        index_status = result.get("indexStatusResult", {})
        mobile = result.get("mobileUsabilityResult", {})
        rich = result.get("richResultsResult", {})

        return {
            "url": inspect_url,
            "verdict": index_status.get("verdict"),
            "coverage_state": index_status.get("coverageState"),
            "crawled_as": index_status.get("crawledAs"),
            "last_crawl_time": index_status.get("lastCrawlTime"),
            "page_fetch_state": index_status.get("pageFetchState"),
            "robots_txt_state": index_status.get("robotsTxtState"),
            "indexing_state": index_status.get("indexingState"),
            "mobile_usability": mobile.get("verdict"),
            "rich_results": rich.get("verdict"),
        }
    except Exception as exc:
        return {"url": inspect_url, "error": str(exc)}


def get_top_pages(service, site_url: str, days: int = 28, limit: int = 20) -> list:
    """Get top pages by clicks."""
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    body = {
        "startDate": start_date,
        "endDate": end_date,
        "dimensions": ["page"],
        "rowLimit": limit,
    }

    try:
        resp = service.searchanalytics().query(siteUrl=site_url, body=body).execute()
        return [
            {
                "page": r["keys"][0],
                "clicks": r.get("clicks", 0),
                "impressions": r.get("impressions", 0),
                "ctr": round(r.get("ctr", 0) * 100, 2),
                "position": round(r.get("position", 0), 1),
            }
            for r in resp.get("rows", [])
        ]
    except Exception as exc:
        return [{"error": str(exc)}]


# ---------------------------------------------------------------------------
# Analysis helpers
# ---------------------------------------------------------------------------

def detect_opportunities(performance_data: list) -> list:
    """
    Identify SEO opportunities from GSC performance data.
    - High impressions, low CTR → title/meta optimization needed
    - Position 4-20 → "striking distance" keywords
    - Position 1-3 with low CTR → Featured Snippet opportunity
    """
    opportunities = []

    for row in performance_data:
        pos = row.get("position", 0)
        ctr = row.get("ctr", 0)
        imps = row.get("impressions", 0)

        if (STRIKING_DISTANCE_MIN_POSITION <= pos <= STRIKING_DISTANCE_MAX_POSITION
                and imps >= STRIKING_DISTANCE_MIN_IMPRESSIONS):
            opportunities.append({
                "type": "striking_distance",
                "severity": "High",
                "query": row["query"],
                "page": row["page"],
                "position": pos,
                "impressions": imps,
                "finding": f"Position {pos} with {imps} impressions — within striking distance.",
                "fix": "Optimize content for this query. Add keyword to H1/H2, expand content depth, build internal links.",
            })
        elif (pos <= TOP_POSITION_MAX and ctr < LOW_CTR_PCT
              and imps >= LOW_CTR_MIN_IMPRESSIONS):
            opportunities.append({
                "type": "low_ctr_top_position",
                "severity": "Medium",
                "query": row["query"],
                "page": row["page"],
                "position": pos,
                "ctr": ctr,
                "impressions": imps,
                "finding": f"Position {pos} but only {ctr}% CTR — a Featured Snippet may be stealing clicks.",
                "fix": "Optimize for Featured Snippet (40-55 word answer after H2). Improve title tag and meta description.",
            })
        elif imps >= HIGH_IMPRESSIONS and ctr < VERY_LOW_CTR_PCT:
            opportunities.append({
                "type": "high_impressions_low_ctr",
                "severity": "Medium",
                "query": row["query"],
                "page": row["page"],
                "ctr": ctr,
                "impressions": imps,
                "finding": f"{imps} impressions but {ctr}% CTR — title/meta not compelling.",
                "fix": "Rewrite title tag with keyword + benefit. Add numbers, power words, or year to title.",
            })

    return opportunities


def detect_issues(sitemaps: list) -> list | None:
    """What Search Console reports as *broken*, which is not what it reports as *possible*.

    `opportunities[]` and this list are different claims and used to be the same field.
    GO-134 asserted `none_severity` over the opportunities, so "Position 4.0 with 115
    impressions — within striking distance" arrived as a `high` failure: the site's best
    result, printed as the first thing to fix. An opportunity is not a defect at any
    threshold, so no calibration of those numbers could have fixed it — the assertion was
    reading the wrong field.

    This is the field it should have been reading. Of everything the Search Console API
    exposes, the sitemap report is the only place it says a thing is *wrong*: a count of
    errors and warnings Google recorded against a sitemap the owner submitted. Manual
    actions, Index Coverage and mobile usability are the other three, and none of them has
    an endpoint — that is why GO-141, GO-142 and MB-099 are `MANUAL` and not wired here.

    Returns `None` — not `[]` — when the sitemap list could not be read, so the item
    reports `NO_DATA` rather than passing on an empty answer. An unreadable report is not
    a clean one, and `missing_is: pass` is exactly the mistake this registry is built to
    avoid.
    """
    if not isinstance(sitemaps, list) or any(
            isinstance(s, dict) and s.get("error") for s in sitemaps):
        return None
    issues = []
    for s in sitemaps:
        if not isinstance(s, dict):
            continue
        path = s.get("path") or "(unnamed sitemap)"
        # The API returns these as strings ("0"), and `int("0")` is the whole reason
        # this is not `s.get("errors", 0) > 0`: every count would be truthy.
        errors = _as_int(s.get("errors"))
        warnings = _as_int(s.get("warnings"))
        if errors:
            issues.append({
                "type": "sitemap_errors",
                # Search Console calls these errors, and an
                # error means Google did not read part of a sitemap the owner submitted.
                "severity": "high",
                "sitemap": path,
                "errors": errors,
                "finding": f"{errors} error(s) against submitted sitemap {path}.",
                "fix": "Open Search Console -> Sitemaps, read the errors for this file, "
                       "and fix or resubmit it.",
            })
        if warnings:
            issues.append({
                "type": "sitemap_warnings",
                # A warning is Google reporting something it
                # read anyway, which is why it does not fail the item on its own.
                "severity": "medium",
                "sitemap": path,
                "warnings": warnings,
                "finding": f"{warnings} warning(s) against submitted sitemap {path}.",
                "fix": "Read the warnings in Search Console -> Sitemaps; they are usually "
                       "URLs Google could read but chose not to index.",
            })
    return issues


def _as_int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Google Search Console Data Checker — pulls GSC data for LLM analysis"
    )
    parser.add_argument("site_url", help="GSC property URL (e.g., https://example.com)")
    parser.add_argument("--credentials", default="", help="Path to service account JSON credentials file. Falls back to GSC_CREDENTIALS_PATH env var or .env file.")
    parser.add_argument("--days", type=int, default=28, help="Performance data lookback period (default: 28)")
    parser.add_argument("--query", default="", help="Filter by query keyword")
    parser.add_argument("--inspect", default="", help="URL to inspect for indexing status")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    from env_loader import get_env
    credentials_path = args.credentials or get_env("GSC_CREDENTIALS_PATH")
    if not credentials_path:
        parser.error("GSC credentials required. Pass --credentials <path> or set GSC_CREDENTIALS_PATH in your environment / .env file.")
    service = build_service(credentials_path)

    report = {
        "site_url": args.site_url,
        "days": args.days,
    }

    # Performance data
    perf = get_performance_data(service, args.site_url, days=args.days, query_filter=args.query)
    report["performance"] = perf

    # Opportunities
    if "data" in perf:
        report["opportunities"] = detect_opportunities(perf["data"])

    # Top pages
    report["top_pages"] = get_top_pages(service, args.site_url, days=args.days)

    # Sitemaps
    report["sitemaps"] = get_sitemaps(service, args.site_url)

    # What Search Console reports as broken, kept apart from what it reports as
    # possible. Omitted entirely when the sitemap report could not be read.
    sitemap_issues = detect_issues(report["sitemaps"])
    if sitemap_issues is not None:
        report["issues"] = sitemap_issues

    # URL inspection (if requested)
    if args.inspect:
        report["url_inspection"] = get_url_inspection(service, args.site_url, args.inspect)

    if args.json:
        print(json.dumps(report, indent=2, default=str))
        return

    print(f"\nGoogle Search Console Report — {args.site_url}")
    print("=" * 60)
    print(f"Period: {perf.get('period', 'N/A')}")

    if "data" in perf:
        print(f"\nTop Queries ({len(perf['data'])} results):")
        for row in perf["data"][:10]:
            print(f"  [{row['position']:>5.1f}] {row['query'][:40]:<40} "
                  f"clicks={row['clicks']:<5} imps={row['impressions']:<6} CTR={row['ctr']}%")

    if report.get("opportunities"):
        print(f"\nOpportunities ({len(report['opportunities'])}):")
        for opp in report["opportunities"][:10]:
            print(f"  ⚡ [{opp['type']}] {opp['query'][:40]} — {opp['finding']}")

    if report.get("issues"):
        print(f"\nIssues Search Console reports ({len(report['issues'])}):")
        for issue in report["issues"]:
            print(f"  ! [{issue['severity']}] {issue['finding']}")

    if report.get("sitemaps"):
        print(f"\nSitemaps ({len(report['sitemaps'])}):")
        for sm in report["sitemaps"]:
            if "error" in sm:
                print(f"  ❌ Error: {sm['error']}")
            else:
                print(f"  📄 {sm['path']} — errors: {sm['errors']}, warnings: {sm['warnings']}")


if __name__ == "__main__":
    from lib.utf8_streams import utf8_streams
    utf8_streams()
    main()
