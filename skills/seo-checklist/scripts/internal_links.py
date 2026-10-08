#!/usr/bin/env python3
"""
Analyze internal link structure of a website.

Link counts per page, anchor text distribution, pages nothing points at, and
internal links that land on a redirect.

Reads the shared crawl inventory (`site_crawl.py`) rather than crawling on its own:
five scripts walking the same pages independently is issue 1 in KNOWN-ISSUES.md.
Without `--inventory` it crawls one for itself, so the CLI still works alone.

Usage:
    python internal_links.py https://example.com
    python internal_links.py https://example.com --inventory inventory.json --json
"""

import argparse
import json
import sys
from collections import Counter
from urllib.parse import urlparse

import site_crawl


# basis: inherited — under three outgoing internal links from a page, present at
#  import. A page with a navigation bar clears this without trying, so it fires on
#  pages rendered client-side or genuinely orphaned in the other direction.
LOW_OUTLINKS = 3
# basis: inherited — over a hundred, present at import. Above it the page is a
#  directory or a tag index rather than a document, and PageRank per link is thin.
HIGH_OUTLINKS = 100
# basis: inherited — a site averaging under five internal links per page, present at
#  import.
LOW_AVERAGE_OUTLINKS = 5

def analyze(inventory: dict, start_url: str) -> dict:
    """Link structure from an inventory. No requests."""
    pages = inventory.get("pages") or {}
    inbound = site_crawl.inbound_map(inventory)
    entry = inventory.get("entry") or site_crawl.page_key(start_url)
    summary = inventory.get("summary") or {}

    result = {
        "start_url": start_url,
        "domain": urlparse(start_url).netloc,
        "pages_crawled": len(pages),
        "total_internal_links": summary.get("internal_links", 0),
        "unique_pages_found": len(inbound),
        "max_depth_reached": max((row.get("depth", 0) for row in pages.values()),
                                 default=0),
        "pages": {},
        "anchor_texts": {},
        "link_distribution": {},
        "orphan_candidates": [],
        "nofollow_links": [],
        "internal_redirects": [],
        "summary": {},
        "issues": [],
        "recommendations": [],
        "error": None,
        # Copied through, never re-derived. One crawl failing has to reach every
        # item that reads this script as NO_DATA with the reason, and the crawl is
        # the only thing that knows.
        "fetch_error": inventory.get("fetch_error"),
        # The crawl says whether it read the whole site. Carried here because
        # every count beside it is a count over what was read, and the item
        # asserting `none of these` cannot tell the difference on its own.
        "truncated": bool((inventory.get("summary") or {}).get("truncated")),
    }

    # Unique targets, not raw `<a>` count: this script has always reported how many
    # *pages* a page links to, and a nav repeated in a header and a footer is one
    # link for that purpose. `link_profile.py` counts the raw links, deliberately —
    # link equity is divided among links, not among destinations.
    out_counts = {key: row.get("unique_internal_out", 0)
                  for key, row in pages.items() if row.get("html")}
    for key, row in sorted(pages.items()):
        result["pages"][key] = {
            "outgoing_links": row.get("unique_internal_out", 0),
            "incoming_links": len({s["source"] for s in inbound.get(key, [])}),
        }

    anchors = Counter(link["anchor"] for row in pages.values()
                      for link in (row.get("links") or [])
                      if link.get("internal") and (link.get("anchor") or "").strip())
    result["anchor_texts"] = dict(anchors.most_common(20))

    result["link_distribution"] = {
        "min": min(out_counts.values()) if out_counts else 0,
        "max": max(out_counts.values()) if out_counts else 0,
        "avg": round(sum(out_counts.values()) / max(1, len(out_counts)), 1),
    }

    for key, sources in sorted(inbound.items()):
        # Distinct source pages. Three links from one page is one page pointing at
        # you, and calling that "well linked" is how a genuinely orphaned page hides.
        pages_linking = len({s["source"] for s in sources})
        if key != entry and pages_linking <= 1:
            result["orphan_candidates"].append({"url": key,
                                                "incoming_links": pages_linking})

    for key, row in sorted(pages.items()):
        for link in row.get("links") or []:
            if link.get("internal") and link.get("nofollow"):
                result["nofollow_links"].append({
                    "url": link["target"], "anchor_text": link["anchor"] or "[no text]",
                    "nofollow": True, "source": key})

    # AR-149's actual subject. The item is titled "Eliminate Internal Redirects" and
    # used to assert that `pages` was non-empty — a condition satisfied by any site
    # that answers at all, so the item could not fail, and its exemption in the
    # contract pair described redirects that nothing was looking for. A link pointing
    # at a URL that redirects is measurable now that one crawl records where every
    # internal target actually landed.
    #
    # Only linked targets count. A sitemap entry that redirects is a sitemap defect
    # and `sitemap_checker.py` reports it; this is about the links on the pages.
    for row in inventory.get("redirected") or []:
        if row.get("linked_from"):
            result["internal_redirects"].append(row)

    no_text = sum(1 for row in pages.values() for link in (row.get("links") or [])
                  if link.get("internal") and not (link.get("anchor") or "").strip())
    low_link_pages = [key for key, count in out_counts.items() if count < LOW_OUTLINKS]
    high_link_pages = [key for key, count in out_counts.items() if count > HIGH_OUTLINKS]

    result["summary"] = {
        "pages": len(pages),
        "internal_links": result["total_internal_links"],
        "internal_redirects": len(result["internal_redirects"]),
        "orphan_candidates": len(result["orphan_candidates"]),
        "nofollow_internal_links": len(result["nofollow_links"]),
        "links_without_anchor_text": no_text,
        "pages_under_three_links": len(low_link_pages),
        "pages_over_hundred_links": len(high_link_pages),
    }

    if result["internal_redirects"]:
        result["issues"].append(
            f"⚠️ {len(result['internal_redirects'])} internal link target(s) redirect "
            f"— link to the destination instead")
    if result["orphan_candidates"]:
        result["issues"].append(
            f"⚠️ {len(result['orphan_candidates'])} potential orphan page(s) "
            f"(≤1 internal link pointing to them)")
    if low_link_pages:
        result["issues"].append(
            f"⚠️ {len(low_link_pages)} page(s) have fewer than 3 internal links")
    if high_link_pages:
        result["issues"].append(
            f"⚠️ {len(high_link_pages)} page(s) have >100 internal links — may dilute "
            f"link equity")
    if result["nofollow_links"]:
        result["issues"].append(
            f"⚠️ {len(result['nofollow_links'])} internal link(s) have nofollow — "
            f"this wastes link equity")
    if no_text:
        result["issues"].append(f"⚠️ {no_text} link(s) have no anchor text")

    if result["internal_redirects"]:
        result["recommendations"].append(
            "Point internal links at the final URL so no hop is spent on a redirect")
    if result["orphan_candidates"]:
        result["recommendations"].append(
            "Add internal links pointing to orphan pages from related content")
    if result["link_distribution"]["avg"] < LOW_AVERAGE_OUTLINKS:
        result["recommendations"].append(
            "Increase internal linking — aim for 3-5 relevant links per 1000 words")

    return result


def main():
    parser = argparse.ArgumentParser(description="Analyze internal link structure")
    parser.add_argument("url", help="Website URL (usually homepage)")
    parser.add_argument("--inventory", default="",
                        help="crawl inventory from site_crawl.py; crawled here when "
                             "not supplied")
    parser.add_argument("--depth", "-d", type=int, default=2,
                        help="Max crawl depth when crawling here (default: 2)")
    parser.add_argument("--max-pages", "-m", type=int, default=50,
                        help="Max pages to crawl here (default: 50)")
    parser.add_argument("--json", "-j", action="store_true", help="Output as JSON")

    args = parser.parse_args()
    inventory = site_crawl.inventory_for(
        args.url, args.inventory, depth=args.depth, max_pages=args.max_pages,
        signatures=False)
    result = analyze(inventory, args.url)

    if args.json:
        print(json.dumps(result, indent=2, default=str))
        return

    if result["error"]:
        print(f"Error: {result['error']}")
        sys.exit(1)

    print(f"Internal Link Analysis — {result['domain']}")
    print("=" * 50)
    print(f"Pages crawled: {result['pages_crawled']}")
    print(f"Unique pages found: {result['unique_pages_found']}")
    print(f"Total internal links: {result['total_internal_links']}")
    print(f"Max depth reached: {result['max_depth_reached']}")

    dist = result["link_distribution"]
    print(f"\nLinks per page: min={dist['min']}, max={dist['max']}, avg={dist['avg']}")

    if result["internal_redirects"]:
        print(f"\n⚠️ Internal Links That Redirect ({len(result['internal_redirects'])}):")
        for row in result["internal_redirects"][:10]:
            print(f"  • {row['url']} → {row['to']} ({row['hops']} hop(s)), "
                  f"linked from {len(row['linked_from'])} page(s)")

    if result["orphan_candidates"]:
        print(f"\n⚠️ Potential Orphan Pages ({len(result['orphan_candidates'])}):")
        for orphan in result["orphan_candidates"][:10]:
            print(f"  • {orphan['url']} ({orphan['incoming_links']} incoming)")

    if result["anchor_texts"]:
        print("\nTop Anchor Texts:")
        for text, count in list(result["anchor_texts"].items())[:10]:
            print(f"  [{count}x] \"{text}\"")

    if result["nofollow_links"]:
        print(f"\n⚠️ Nofollow Internal Links ({len(result['nofollow_links'])}):")
        for link in result["nofollow_links"][:5]:
            print(f"  • {link['url']} (from {link['source']})")

    if result["issues"]:
        print("\nIssues:")
        for issue in result["issues"]:
            print(f"  {issue}")

    if result["recommendations"]:
        print("\nRecommendations:")
        for rec in result["recommendations"]:
            print(f"  💡 {rec}")


if __name__ == "__main__":
    from lib.utf8_streams import utf8_streams
    utf8_streams()
    main()
