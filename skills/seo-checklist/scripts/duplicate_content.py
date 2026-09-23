#!/usr/bin/env python3
"""
Duplicate & Thin Content Detector

Detects near-duplicate pages and thin content across a site using
MinHash / Jaccard similarity and word-count thresholds.

Reads the shared crawl inventory (`site_crawl.py`), which carries each page's word
count, exact content hash and MinHash signature — so this script compares pages
rather than fetching them. Without `--inventory` it crawls one for itself, so the CLI
still works alone.

Usage:
    python duplicate_content.py https://example.com --depth 2 --json
    python duplicate_content.py https://example.com --inventory inventory.json
    python duplicate_content.py https://example.com --threshold 0.85
"""

import argparse
import json
import sys
from collections import defaultdict

import site_crawl
from seo_common import THIN_CONTENT_WORDS, normalize_url

# basis: inherited — 100 words, present at import. Splits a thin page into two
#  severities: under a hundred words the page is closer to empty than to short, which is
#  a different conversation with whoever owns it.
NEARLY_EMPTY_WORDS = 100

# Quality gates from resources/references/quality-gates.md
# basis: inherited — 300 words for a default page, present at import from
#  Agentic-SEO-Skill. One of the five numbers KNOWN-ISSUES §2 names, and its provenance
#  is exactly what §2 suspected: the figure is conventional in SEO writing and has no
#  source anybody here can point at
THIN_CONTENT_THRESHOLDS = {
    "blog_post": 1500,
    "landing_page": 800,
    "product_page": THIN_CONTENT_WORDS,
    "location_page": 350,
    "default": THIN_CONTENT_WORDS,
}


# ---------------------------------------------------------------------------
# Reading pages off the inventory
# ---------------------------------------------------------------------------

def pages_from_inventory(inventory: dict) -> dict:
    """Page evidence projected from inventory rows with readable content.

    Non-200 responses are left out. An error page is HTML and is not content: a 404
    body was being analysed like any other page, so a site with one dead internal
    link collected a `Critical` thin-content finding advising somebody to expand a
    page that does not exist — and it counted against CN-039, the thin-content item.
    A broken link is `internal_links.py`'s finding now, and it is made once.
    """
    pages = {}
    for key, row in sorted((inventory.get("pages") or {}).items()):
        if not row.get("html") or row.get("status") != 200:
            continue
        if not row.get("text_hash"):
            continue
        pages[key] = {
            "word_count": row.get("content_words", 0),
            "text_hash": row["text_hash"],
            "signature": row.get("signature") or [],
            # From the crawl, which reads the `X-Robots-Tag` header as well as the
            # meta tag. The header was invisible to this script before, so a page
            # kept out of the index by a header was still asked for 300 more words.
            "noindex": bool(row.get("noindex")),
            "canonical": row.get("canonical"),
            # Carried for MS-022 and MS-029. Both fields have been in the crawl
            # inventory all along; the old rules borrowed the duplicate-body count
            # instead of measuring duplicate titles and descriptions themselves.
            "title": (row.get("title") or "").strip(),
            "meta_description": (row.get("meta_description") or "").strip(),
        }
    return pages


def duplicate_titles(pages: dict) -> list:
    """Groups of pages sharing one title.

    Compare case-insensitively on collapsed whitespace. Skip absent titles because
    MS-026 reports that separate defect; two missing titles are not evidence that a
    title was duplicated.
    """
    groups = {}
    for key, page in _snippet_grouping_pages(pages)[0].items():
        text = " ".join(page.get("title", "").split()).lower()
        if not text:
            continue
        groups.setdefault(text, []).append(key)
    return [{"type": "duplicate_title", "severity": "high",
             "title": text, "urls": sorted(urls),
             "finding": f"{len(urls)} pages share one title",
             "fix": "Write a distinct title for each page"}
            for text, urls in sorted(groups.items()) if len(urls) > 1]


def duplicate_descriptions(pages: dict) -> list:
    """Groups of pages sharing one meta description.

    Compared case-insensitively on collapsed whitespace: two descriptions differing
    only in a trailing space or a capital are the same description to anyone reading
    a SERP, and treating them as distinct is how a duplicate hides.

    A page with no description is not a duplicate of another page with no description
    — that is MS-028's finding, and counting it here would report one defect twice.
    """
    groups = {}
    for key, page in _snippet_grouping_pages(pages)[0].items():
        text = " ".join(page.get("meta_description", "").split()).lower()
        if not text:
            continue
        groups.setdefault(text, []).append(key)
    return [{"type": "duplicate_meta_description", "severity": "medium",
             "description": text, "urls": sorted(urls),
             "finding": f"{len(urls)} pages share one meta description",
             "fix": "Write a distinct description for each page"}
            for text, urls in sorted(groups.items()) if len(urls) > 1]


def _snippet_grouping_pages(pages: dict) -> tuple[dict, dict]:
    """Indexable canonical pages and the reasons other pages cannot compete.

    MS-029 inherits the same boundary because a canonicalized or noindex variant is
    not indexed separately, so its description cannot compete either. Pagination is
    deliberately still included: the inventory records neither rel=prev/next nor a
    page number, so this script cannot distinguish a series from a duplicate.
    """
    included = {}
    exclusions = {"noindex": 0, "canonicalized": 0}
    for key, page in pages.items():
        if page.get("noindex"):
            exclusions["noindex"] += 1
            continue
        canonical = page.get("canonical")
        if canonical and normalize_url(canonical, key) != normalize_url(key):
            exclusions["canonicalized"] += 1
            continue
        included[key] = page
    return included, exclusions


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def detect_duplicates(pages: dict, similarity_threshold: float = 0.85,
                      fetch_error: str | None = None,
                      thin_words: int | None = None,
                      truncated: bool = False) -> dict:
    """
    Detect exact and near-duplicate pages.
    Returns report with exact dupes, near-dupes, and thin content.

    `pages` comes from `pages_from_inventory`: the hash and the signature were
    computed by the crawl that read the page, so nothing here fetches anything.
    """
    hash_groups = defaultdict(list)
    signatures = {}

    for url, data in sorted(pages.items()):
        hash_groups[data["text_hash"]].append(url)
        if data.get("signature"):
            signatures[url] = data["signature"]

    exact_dupes = []
    for _digest, urls in hash_groups.items():
        if len(urls) > 1:
            indexable_urls = [url for url in urls if not pages[url]["noindex"]]
            noindex_urls = [url for url in urls if pages[url]["noindex"]]

            if len(indexable_urls) > 1:
                exact_dupes.append({
                    "type": "exact_duplicate",
                    "severity": "Critical",
                    "urls": indexable_urls,
                    "finding": f"{len(indexable_urls)} indexable pages have identical content.",
                    "fix": "Consolidate into a single canonical page and redirect duplicates with 301.",
                })

            if noindex_urls:
                exact_dupes.append({
                    "type": "exact_duplicate",
                    "severity": "Info",
                    "urls": urls,
                    "noindex_urls": noindex_urls,
                    "finding": "Identical content includes at least one noindex page.",
                    "fix": "No action required for duplicate-content risk while noindex is intentional.",
                })

    # Step 2: Near-duplicates (MinHash Jaccard)
    near_dupes = []
    urls = list(signatures.keys())
    checked = set()

    for i in range(len(urls)):
        for j in range(i + 1, len(urls)):
            pair = (urls[i], urls[j])
            if pair in checked:
                continue
            checked.add(pair)

            sim = site_crawl.jaccard_from_minhash(signatures[urls[i]],
                                                  signatures[urls[j]])
            if sim >= similarity_threshold:
                # Skip if already in exact dupes
                if any(urls[i] in ed["urls"] and urls[j] in ed["urls"] for ed in exact_dupes):
                    continue
                noindex_in_pair = (pages[urls[i]]["noindex"]
                                   or pages[urls[j]]["noindex"])
                near_dupes.append({
                    "type": "near_duplicate",
                    "severity": "Info" if noindex_in_pair else "Warning",
                    "similarity": round(sim, 3),
                    "url_a": urls[i],
                    "url_b": urls[j],
                    "word_count_a": pages[urls[i]]["word_count"],
                    "word_count_b": pages[urls[j]]["word_count"],
                    "noindex_in_pair": noindex_in_pair,
                    "finding": (
                        f"Pages are {sim:.0%} similar, but at least one page is noindex."
                        if noindex_in_pair
                        else f"Pages are {sim:.0%} similar — likely near-duplicate content."
                    ),
                    "fix": (
                        "No action required for duplicate-content risk while noindex is intentional."
                        if noindex_in_pair
                        else "Differentiate content significantly, or set one as canonical and noindex the other."
                    ),
                })

    # Step 3: Thin content
    thin_pages = []
    for url, data in sorted(pages.items()):
        if data["noindex"]:
            continue
        wc = data["word_count"]
        # Only `["default"]` is ever read: the other four entries in
        # THIN_CONTENT_THRESHOLDS need a page-type detector that does not exist, so
        # `location_page: 350` and its neighbours have been unreachable since import.
        # `thin_words` is how the number actually moves — passed per site profile, and
        # recorded in `summary` below so a verdict says what it was measured against.
        threshold = thin_words or THIN_CONTENT_THRESHOLDS["default"]
        if wc < threshold:
            thin_pages.append({
                "type": "thin_content",
                "severity": "Warning" if wc >= NEARLY_EMPTY_WORDS else "Critical",
                "url": url,
                "word_count": wc,
                "threshold": threshold,
                "finding": f"Only {wc} words (minimum: {threshold}).",
                "fix": f"Expand content to at least {threshold} words of substantive, unique content, or noindex if low-value.",
            })

    grouping_pages, title_group_exclusions = _snippet_grouping_pages(pages)
    title_groups = duplicate_titles(grouping_pages)
    description_groups = duplicate_descriptions(grouping_pages)
    return {
        # An empty crawl is not a site with no duplicates. Without this the runner
        # cannot tell "nothing is wrong" from "nothing was read", and four items —
        # two of them `high` — graded the emptiness as a pass. The crawl's own
        # reason wins when it has one: it knows why nothing was read.
        "fetch_error": fetch_error or (None if pages else "no page could be read"),
        # The crawl says whether it read the whole site. Carried here because
        # every count below is a count over what was read, and the item
        # asserting `none of these` cannot tell the difference on its own.
        "truncated": truncated,
        "pages_analyzed": len(pages),
        "exact_duplicates": exact_dupes,
        "near_duplicates": near_dupes,
        "thin_content": thin_pages,
        "duplicate_titles": title_groups,
        "duplicate_descriptions": description_groups,
        "summary": {
            "exact_duplicate_groups": len(exact_dupes),
            "duplicate_title_groups": len(title_groups),
            "near_duplicate_pairs": len(near_dupes),
            "thin_pages": len(thin_pages),
            # The number the verdict was reached against. Without it "thin_pages = 14"
            # is unarguable: a reader cannot tell 14 short pages from a threshold set
            # for a different kind of site.
            "thin_words_threshold": thin_words or THIN_CONTENT_THRESHOLDS["default"],
            "duplicate_description_groups": len(description_groups),
            "title_group_exclusions": title_group_exclusions,
            "avg_word_count": round(
                sum(p["word_count"] for p in pages.values()) / max(1, len(pages))
            ),
        },
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Duplicate & Thin Content Detector (MinHash / Jaccard similarity)"
    )
    parser.add_argument("url", help="Start URL to crawl")
    parser.add_argument("--inventory", default="",
                        help="crawl inventory from site_crawl.py; crawled here when "
                             "not supplied")
    parser.add_argument("--depth", type=int, default=2, help="Crawl depth (default: 2)")
    parser.add_argument("--max-pages", type=int, default=50, help="Max pages to crawl (default: 50)")
    parser.add_argument("--threshold", type=float, default=0.85,
                        help="Jaccard similarity threshold for near-duplicates (default: 0.85)")
    parser.add_argument("--thin-words", type=int, default=0,
                        help="Word count below which a page counts as thin (default: "
                             f"{THIN_CONTENT_THRESHOLDS['default']}). Site profiles pass "
                             "this: a local business service page says what it does and "
                             "stops, and the default is written for a page with "
                             "something to explain.")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    inventory = site_crawl.inventory_for(args.url, args.inventory, depth=args.depth,
                                         max_pages=args.max_pages)
    pages = pages_from_inventory(inventory)
    print(f"{len(pages)} page(s) with content. Analyzing...", file=sys.stderr)

    report = detect_duplicates(pages, similarity_threshold=args.threshold,
                               fetch_error=inventory.get("fetch_error"),
                               thin_words=args.thin_words or None,
                               truncated=bool(inventory.get("summary", {}).get("truncated")))

    if args.json:
        print(json.dumps(report, indent=2))
        return

    print("\nDuplicate & Thin Content Report")
    print("=" * 60)
    print(f"Pages Analyzed    : {report['pages_analyzed']}")
    print(f"Avg Word Count    : {report['summary']['avg_word_count']}")

    if report["exact_duplicates"]:
        print(f"\nExact Duplicates ({report['summary']['exact_duplicate_groups']} groups):")
        for group in report["exact_duplicates"]:
            print(f"  🔴 {len(group['urls'])} identical pages:")
            for url in group["urls"]:
                print(f"     - {url}")
            print(f"     Fix: {group['fix']}")

    if report["near_duplicates"]:
        print(f"\nNear-Duplicates ({report['summary']['near_duplicate_pairs']} pairs):")
        for pair in report["near_duplicates"]:
            print(f"  ⚠️  {pair['similarity']:.0%} similar:")
            print(f"     A: {pair['url_a']} ({pair['word_count_a']} words)")
            print(f"     B: {pair['url_b']} ({pair['word_count_b']} words)")
            print(f"     Fix: {pair['fix']}")

    if report["thin_content"]:
        print(f"\nThin Content ({report['summary']['thin_pages']} pages):")
        for page in sorted(report["thin_content"], key=lambda x: x["word_count"]):
            icon = "🔴" if page["severity"] == "Critical" else "⚠️"
            print(f"  {icon} {page['url']} — {page['word_count']} words (min: {page['threshold']})")

    if not report["exact_duplicates"] and not report["near_duplicates"] and not report["thin_content"]:
        print("\n✅ No duplicate or thin content issues detected.")


if __name__ == "__main__":
    main()
