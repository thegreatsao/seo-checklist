#!/usr/bin/env python3
"""
Link Profile Analyzer

Crawls a site to build an internal/external link graph, identifies orphan
pages, calculates internal link equity distribution, and analyzes anchor
text patterns.

For backlink data from external sources, integrates with GSC API
(if credentials available) or outputs instructions for manual enrichment.

Reads the shared crawl inventory (`site_crawl.py`); crawls one for itself when not
given one, so the CLI still works alone.

Usage:
    python link_profile.py https://example.com --json
    python link_profile.py https://example.com --inventory inventory.json --json
    python link_profile.py https://example.com --gsc-credentials creds.json
"""

import argparse
import json
import sys
from collections import Counter, defaultdict
from urllib.parse import urlparse

import site_crawl


# ---------------------------------------------------------------------------
# Build the graph from the inventory
# ---------------------------------------------------------------------------

# basis: inherited — an average of three internal links per page, present at import.
#  The same number as `internal_links.LOW_OUTLINKS` and asked of a different quantity:
#  that one is per page, this one is the site's mean.
LOW_AVERAGE_INTERNAL_LINKS = 3

def graph_from_inventory(inventory: dict) -> tuple:
    """(graph, crawled, base_domain, robots_refused) — no requests.

    `crawled` is what the crawl actually fetched, and `robots_refused` is what it
    was told not to. Keeping them apart is load-bearing: orphans are computed over
    `crawled`, so a page we politely declined to open used to be reported as a page
    the site failed to link — our own restraint arriving in a client's report as
    their defect, three times in this tree before it stayed fixed.
    """
    graph = {
        "pages": {},
        "all_internal_targets": Counter(),
        "all_external_targets": Counter(),
        "anchor_texts": defaultdict(list),
    }
    pages = inventory.get("pages") or {}
    for key, row in sorted(pages.items()):
        if not row.get("html"):
            continue
        internal = [link for link in row.get("links") or [] if link.get("internal")]
        external = [link for link in row.get("links") or [] if not link.get("internal")]
        graph["pages"][key] = {
            "internal_out": len(internal),
            "external_out": len(external),
            "internal_links": [link["target"] for link in internal[:20]],
        }
        for link in internal:
            graph["all_internal_targets"][link["target"]] += 1
            if link.get("anchor"):
                graph["anchor_texts"][link["target"]].append(link["anchor"])
        for link in external:
            graph["all_external_targets"][link["target"]] += 1

    crawled = set(pages)
    base_domain = urlparse(inventory.get("site") or "").netloc
    robots_refused = set(site_crawl.robots_refused(inventory))
    return graph, crawled, base_domain, robots_refused


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def analyze_link_profile(graph: dict, crawled: set, base_domain: str,
                         robots_refused: set | None = None,
                         entry_url: str = "", fetch_error: str | None = None,
                         truncated: bool = False) -> dict:
    """Produce analysis from the crawled link graph."""
    pages = graph["pages"]
    internal_targets = graph["all_internal_targets"]
    refused = robots_refused or set()

    # Orphan pages: crawled, and nothing internal points at them.
    #
    # Two exclusions, and both were wrong before. A URL robots.txt told us not to
    # fetch is not a page the site failed to link — it is a page we chose not to
    # open, and counting it made our own politeness into the site's defect. And the
    # home page has no inbound internal links by nature, which the old code handled
    # by exempting `min(crawled)` — the lexicographically smallest URL, which is the
    # home page only by luck. On a site where it is not, the home page was reported
    # as an orphan and some arbitrary other page was excused.
    entry = {u for u in (entry_url, entry_url.rstrip("/"), entry_url + "/") if u}
    orphan_pages = []
    for url in sorted(crawled):
        if url in refused or url in entry:
            continue
        if internal_targets.get(url, 0) == 0:
            orphan_pages.append(url)

    # Top linked pages (highest inbound internal links)
    top_linked = internal_targets.most_common(20)

    # Pages with no outbound internal links (dead ends)
    dead_ends = [url for url, data in pages.items() if data["internal_out"] == 0]

    # External link distribution
    external_domains = Counter()
    for url in graph["all_external_targets"]:
        domain = urlparse(url).netloc
        external_domains[domain] += 1

    # Internal link equity (simplified PageRank-like distribution)
    total_pages = len(pages)
    avg_internal_links = (
        sum(d["internal_out"] for d in pages.values()) / max(total_pages, 1)
    )

    # Issues
    issues = []
    if orphan_pages:
        issues.append({
            "type": "orphan_pages",
            "severity": "High",
            "count": len(orphan_pages),
            "finding": f"{len(orphan_pages)} orphan page(s) with zero inbound internal links.",
            "pages": orphan_pages[:10],
            "fix": "Add internal links from relevant content pages to these orphan pages.",
        })

    if dead_ends:
        issues.append({
            "type": "dead_end_pages",
            "severity": "Medium",
            "count": len(dead_ends),
            "finding": f"{len(dead_ends)} page(s) with no outbound internal links (dead ends).",
            "pages": dead_ends[:10],
            "fix": "Add contextual internal links to related content from these pages.",
        })

    if avg_internal_links < LOW_AVERAGE_INTERNAL_LINKS:
        issues.append({
            "type": "low_internal_linking",
            "severity": "High",
            "finding": f"Average internal links per page is only {avg_internal_links:.1f} (target: 5-10).",
            "fix": "Increase internal linking by adding contextual links within content.",
        })

    return {
        # Zero orphans out of zero crawled pages is not a healthy link graph. The
        # crawl's own reason wins when it has one: it knows why nothing was read.
        "fetch_error": fetch_error or (None if total_pages
                                      else "no page could be read"),
        # The crawl says whether it read the whole site. Carried here because
        # every count below is a count over what was read, and the item
        # asserting `none of these` cannot tell the difference on its own.
        "truncated": truncated,
        "pages_crawled": total_pages,
        "total_internal_links": sum(d["internal_out"] for d in pages.values()),
        "total_external_links": sum(d["external_out"] for d in pages.values()),
        "unique_internal_targets": len(internal_targets),
        "unique_external_domains": len(external_domains),
        "avg_internal_links_per_page": round(avg_internal_links, 1),
        # What robots.txt kept out of the graph, so a reader can tell a smaller
        # crawl from a worse site.
        "robots_refused": sorted(refused),
        "orphan_pages": {
            "count": len(orphan_pages),
            "urls": orphan_pages[:15],
        },
        "dead_end_pages": {
            "count": len(dead_ends),
            "urls": dead_ends[:15],
        },
        "top_linked_pages": [
            {"url": url, "inbound_links": count}
            for url, count in top_linked
        ],
        "top_external_domains": [
            {"domain": domain, "links": count}
            for domain, count in external_domains.most_common(15)
        ],
        "issues": issues,
    }


# ---------------------------------------------------------------------------
# GSC backlink integration (optional)
# ---------------------------------------------------------------------------

def get_gsc_backlinks(credentials_path: str, site_url: str) -> dict:
    """Pull external links from Google Search Console (if available)."""
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        scopes = ["https://www.googleapis.com/auth/webmasters.readonly"]
        creds = service_account.Credentials.from_service_account_file(
            credentials_path, scopes=scopes
        )
        service = build("searchconsole", "v1", credentials=creds)

        resp = service.links().list(siteUrl=site_url).execute()
        return {
            "available": True,
            "external_links": resp.get("externalLinks", [])[:20],
            "internal_links_sample": resp.get("internalLinks", [])[:10],
        }
    except ImportError:
        return {"available": False, "reason": "google-api-python-client not installed."}
    except Exception as exc:
        return {"available": False, "reason": str(exc)}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Link Profile Analyzer — crawls site, builds link graph, identifies issues"
    )
    parser.add_argument("url", help="Site URL to analyze")
    parser.add_argument("--inventory", default="",
                        help="crawl inventory from site_crawl.py; crawled here when "
                             "not supplied")
    parser.add_argument("--max-pages", type=int, default=50,
                        help="Max pages to crawl here (default: 50)")
    parser.add_argument("--gsc-credentials", default="",
                        help="Path to GSC service account credentials (optional). Falls back to GSC_CREDENTIALS_PATH env var or .env file.")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    from env_loader import get_env
    gsc_credentials = args.gsc_credentials or get_env("GSC_CREDENTIALS_PATH")

    inventory = site_crawl.inventory_for(args.url, args.inventory,
                                         max_pages=args.max_pages, signatures=False)
    graph, crawled, base_domain, robots_refused = graph_from_inventory(inventory)

    print("Analyzing link profile...", file=sys.stderr)
    report = analyze_link_profile(graph, crawled, base_domain, robots_refused,
                                  entry_url=inventory.get("entry") or args.url,
                                  fetch_error=inventory.get("fetch_error"),
                                  truncated=bool(inventory.get("summary", {})
                                                 .get("truncated")))
    report["site_url"] = args.url

    # Optional GSC backlinks
    if gsc_credentials:
        print("Fetching GSC backlinks...", file=sys.stderr)
        report["gsc_backlinks"] = get_gsc_backlinks(gsc_credentials, args.url)

    if args.json:
        print(json.dumps(report, indent=2, default=str))
        return

    print(f"\nLink Profile Analysis — {args.url}")
    print("=" * 60)
    print(f"Pages crawled            : {report['pages_crawled']}")
    print(f"Total internal links     : {report['total_internal_links']}")
    print(f"Total external links     : {report['total_external_links']}")
    print(f"Unique internal targets  : {report['unique_internal_targets']}")
    print(f"Unique external domains  : {report['unique_external_domains']}")
    print(f"Avg internal links/page  : {report['avg_internal_links_per_page']}")

    orph = report["orphan_pages"]
    if orph["count"]:
        print(f"\n🔴 Orphan Pages ({orph['count']}):")
        for u in orph["urls"][:5]:
            print(f"  - {u}")

    dead = report["dead_end_pages"]
    if dead["count"]:
        print(f"\n⚠️  Dead-End Pages ({dead['count']}):")
        for u in dead["urls"][:5]:
            print(f"  - {u}")

    if report["top_linked_pages"]:
        print("\nTop Linked Pages:")
        for p in report["top_linked_pages"][:10]:
            print(f"  [{p['inbound_links']:>3}] {p['url']}")

    if report["issues"]:
        print(f"\nIssues ({len(report['issues'])}):")
        for issue in report["issues"]:
            icon = "🔴" if issue["severity"] == "High" else "⚠️"
            print(f"  {icon} [{issue['type']}] {issue['finding']}")
            print(f"     Fix: {issue['fix']}")


if __name__ == "__main__":
    from lib.utf8_streams import utf8_streams
    utf8_streams()
    main()
