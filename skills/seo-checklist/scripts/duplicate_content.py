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

from lib import python_floor  # noqa: F401

import argparse
import itertools
import json
import sys
from collections import defaultdict

import site_crawl
from seo_common import read_as_url, THIN_CONTENT_WORDS, carries_content, normalize_url

# basis: presentation — 100 words, present at import. It picks the `severity` of a thin
#  page's row in `thin_content` (Critical under it, Warning above), and CN-039 counts
#  `summary.thin_pages` whatever their severity; no item reads `thin_content`, so it
#  decides what is printed, never a verdict (F11; held by `tests/test_presentation_basis.py`)
NEARLY_EMPTY_WORDS = 100
# basis: convention — two indexable pages estimated 85 % alike by MinHash are near
#  duplicates, present at import as the 0.1.0 default argument. Since F15 (the owner's
#  ruling on F03's CN-041) near-duplicates reach the assertion: below this a pair is not
#  counted and CN-041 can pass, at or above it the pair makes CN-041 a WARN (an exact copy
#  still FAILs). Nothing external sets the line; an estimate this coarse (the 0.13 spread
#  `site_crawl.MINHASH_FUNCTIONS` measures) should only flag pages most of whose text
#  is the same, which is where 0.85 sits.
NEAR_DUPLICATE_SIMILARITY = 0.85


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

    Every HTML page with content, its own words or none (F15, the owner's rulings on
    F03's MS-026, MS-029, CN-039): a page with no body text of its own — an image
    gallery, a navigation-only page — was dropped here, and with it the untitled page,
    the shared description and the thinnest page these items are about. Such a page
    has no `text_hash` and no signature, so it is never anybody's duplicate.
    """
    pages = {}
    for key, row in sorted((inventory.get("pages") or {}).items()):
        if not row.get("html") or not carries_content(row.get("status")):
            continue
        pages[key] = {
            "url": row.get("url") or key,
            "final_url": row.get("final_url") or row.get("url") or key,
            "word_count": row.get("content_words", 0),
            "text_hash": row.get("text_hash"),
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
    not indexed separately, so its description cannot compete either; CN-041 too
    since F15 (a noindex or canonicalised copy is how a duplicate is handled). A page
    number is a page of its own (`site_crawl.page_key`), so a paginated series sharing
    one title is judged (MS-022, the owner's ruling for F15).

    A canonical is self when it names the URL the page was read at or landed on,
    query included (`site_crawl.same_page`): `normalize_url` of the slash-stripped page
    key against the canonical's own spelling read a trailing-slash site's every
    self-canonical as pointing elsewhere (the 2026-10-24 audit).
    """
    included = {}
    exclusions = {"noindex": 0, "canonicalized": 0}
    for key, page in pages.items():
        if page.get("noindex"):
            exclusions["noindex"] += 1
            continue
        canonical = page.get("canonical")
        named = normalize_url(canonical, page.get("final_url") or key) if canonical else ""
        if canonical and not any(
                site_crawl.same_page(named, page.get(field) or key)
                for field in ("url", "final_url")):
            exclusions["canonicalized"] += 1
            continue
        included[key] = page
    return included, exclusions


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def detect_duplicates(pages: dict,
                      similarity_threshold: float = NEAR_DUPLICATE_SIMILARITY,
                      fetch_error: str | None = None,
                      thin_words: int | None = None,
                      truncated: bool = False, signatures: bool = True) -> dict:
    """
    Detect exact and near-duplicate pages.
    Returns report with exact dupes, near-dupes, and thin content.

    `pages` comes from `pages_from_inventory`: the hash and the signature were
    computed by the crawl that read the page, so nothing here fetches anything.

    Only indexable canonical pages (`_snippet_grouping_pages`) are duplicates of one
    another; a group or pair with a noindex or canonicalised member is listed as
    `Info` and not counted (F15, CN-041: a page and its noindex copy failed while
    the script said "No action required"). `signatures` is the crawl's: without
    them near-duplicates were never looked for, and CN-041's count is withheld
    unless an exact copy already decides it.
    """
    grouping, _ = _snippet_grouping_pages(pages)
    hash_groups = defaultdict(list)
    signature_of = {}

    for url, data in sorted(pages.items()):
        if data.get("text_hash"):
            hash_groups[data["text_hash"]].append(url)
        if data.get("signature"):
            signature_of[url] = data["signature"]

    exact_dupes = []
    for _digest, urls in hash_groups.items():
        if len(urls) > 1:
            indexable_urls = [url for url in urls if url in grouping]
            set_aside = [url for url in urls if url not in grouping]

            if len(indexable_urls) > 1:
                exact_dupes.append({
                    "type": "exact_duplicate",
                    "severity": "Critical",
                    "urls": indexable_urls,
                    "finding": f"{len(indexable_urls)} indexable pages have identical content.",
                    "fix": "Consolidate into a single canonical page and redirect duplicates with 301.",
                })

            if set_aside:
                exact_dupes.append({
                    "type": "exact_duplicate",
                    "severity": "Info",
                    "urls": urls,
                    "noindex_urls": [url for url in set_aside if pages[url]["noindex"]],
                    "canonicalized_urls": [url for url in set_aside
                                           if not pages[url]["noindex"]],
                    "finding": "Identical content includes a noindex or canonicalised page.",
                    "fix": "No action required while the noindex or canonical is intentional.",
                })

    # Step 2: Near-duplicates (MinHash Jaccard)
    near_dupes = []
    for url_a, url_b in itertools.combinations(signature_of, 2):
        sim = site_crawl.jaccard_from_minhash(signature_of[url_a],
                                              signature_of[url_b])
        if sim >= similarity_threshold:
            # Skip if already in exact dupes
            if any(url_a in ed["urls"] and url_b in ed["urls"] for ed in exact_dupes):
                continue
            handled = url_a not in grouping or url_b not in grouping
            near_dupes.append({
                "type": "near_duplicate",
                "severity": "Info" if handled else "Warning",
                "similarity": round(sim, 3),
                "url_a": url_a,
                "url_b": url_b,
                "word_count_a": pages[url_a]["word_count"],
                "word_count_b": pages[url_b]["word_count"],
                "noindex_in_pair": pages[url_a]["noindex"] or pages[url_b]["noindex"],
                "handled_in_pair": handled,
                "finding": (
                    f"Pages are {sim:.0%} similar, but one is noindex or canonicalised."
                    if handled
                    else f"Pages are {sim:.0%} similar — likely near-duplicate content."
                ),
                "fix": (
                    "No action required while the noindex or canonical is intentional."
                    if handled
                    else "Differentiate content significantly, or set one as canonical and noindex the other."
                ),
            })

    exact_count = sum(1 for group in exact_dupes if group["severity"] == "Critical")
    near_count = sum(1 for pair in near_dupes if pair["severity"] == "Warning")

    # Step 3: Thin content
    thin_pages = []
    for url, data in sorted(pages.items()):
        if data["noindex"]:
            continue
        wc = data["word_count"]
        # A per-page-type table stood here until F04 (batch 4b); only its default was
        # ever read, the other four needed a page-type detector that does not exist.
        # `thin_words` is how the number actually moves — passed per site profile, and
        # recorded in `summary` below so a verdict says what it was measured against.
        threshold = thin_words or THIN_CONTENT_WORDS
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
    # This title says every page, and Google's Influencing title links asks for a
    # title specified in the <title> element on every page. Noindex pages stay out
    # of MS-022 because they do not compete; a missing title is not a competition.
    missing_titles = sorted(
        key for key, page in pages.items() if not page.get("title", "").strip())
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
        "missing_titles": missing_titles,
        "summary": {
            "exact_duplicate_groups": exact_count,
            # CN-041's count: exact copies and near-duplicate pairs among indexable
            # pages. Without signatures the pairs were not looked for, so the count is
            # given only when an exact copy decides it anyway.
            **({"duplicate_content_findings": exact_count + near_count}
               if signatures or exact_count else {}),
            "duplicate_title_groups": len(title_groups),
            "near_duplicate_pairs": near_count,
            "thin_pages": len(thin_pages),
            # The number the verdict was reached against. Without it "thin_pages = 14"
            # is unarguable: a reader cannot tell 14 short pages from a threshold set
            # for a different kind of site.
            "thin_words_threshold": thin_words or THIN_CONTENT_WORDS,
            "duplicate_description_groups": len(description_groups),
            "missing_title_pages": len(missing_titles),
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
    parser.add_argument("--threshold", type=float, default=NEAR_DUPLICATE_SIMILARITY,
                        help="Jaccard similarity threshold for near-duplicates "
                             f"(default: {NEAR_DUPLICATE_SIMILARITY})")
    parser.add_argument("--thin-words", type=int, default=0,
                        help="Word count below which a page counts as thin (default: "
                             f"{THIN_CONTENT_WORDS}). Site profiles pass "
                             "this: a local business service page says what it does and "
                             "stops, and the default is written for a page with "
                             "something to explain.")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()
    args.url = read_as_url(args.url)

    inventory = site_crawl.inventory_for(args.url, args.inventory, depth=args.depth,
                                         max_pages=args.max_pages)
    pages = pages_from_inventory(inventory)
    print(f"{len(pages)} page(s) with content. Analyzing...", file=sys.stderr)

    report = detect_duplicates(pages, similarity_threshold=args.threshold,
                               fetch_error=inventory.get("fetch_error"),
                               thin_words=args.thin_words or None,
                               truncated=bool(inventory.get("summary", {}).get("truncated")),
                               signatures=inventory.get("signatures", True) is not False)
    report["fetch_error_kind"] = inventory.get("fetch_error_kind")

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
    from lib.utf8_streams import utf8_streams
    utf8_streams()
    from lib.typed_credential import credentials_beside_argv
    credentials_beside_argv()
    main()
