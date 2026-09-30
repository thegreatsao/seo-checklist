#!/usr/bin/env python3
"""Audit internal anchor text quality and diversity.

Reads the shared crawl inventory (`site_crawl.py`); crawls one for itself when not
given one, so the CLI still works alone.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict

import site_crawl
from seo_common import (carries_content, normalize_url, primary_language,
                        print_json_or_text)


# basis: convention — four pages. Below it "this anchor appears on most pages" is a
# statement about two or three documents, and the sitewide-link rule this feeds cannot
# tell a navigation menu from a coincidence. A floor, not a calibration.
MIN_PAGES_FOR_SITEWIDE = 4
# basis: convention — half the crawled pages. "Sitewide" has no sharper definition
# available here: a footer link on 60% of a site is the same thing as one on 95%, and
# the number only has to sit above what an editorial link plausibly reaches.
SITEWIDE_PAGE_SHARE = 0.5
# basis: convention — five links carrying one anchor, and 80% of that target's links
# being that anchor. Both halves are needed: the share alone fires on a target with two
# links, and the count alone fires on any well-linked page. 0.9.0 is why the pair
# exists — the count alone reported every navigation bar as anchor spam.
EXACT_MATCH_MIN_LINKS = 5
EXACT_MATCH_SHARE = 0.8   # basis: convention — the share half of the pair above
# basis: convention — three editorial links, below a third of them distinct. A
# diversity ratio only means something once there are enough links to divide, which is
# what the count is doing beside it.
DIVERSITY_MIN_LINKS = 3
DIVERSITY_FLOOR = 0.34   # basis: convention — the ratio half of the pair above

GENERIC_ANCHORS = {
    "",
    "click here",
    "here",
    "learn more",
    "read more",
    "more",
    "this",
    "link",
    "website",
    "page",
    "continue reading",
}


def anchors_from_inventory(inventory: dict) -> dict:
    """Every internal link the crawl saw, as (source, target, anchor, rel)."""
    pages, links, fetch_errors = {}, [], []
    for key, row in sorted((inventory.get("pages") or {}).items()):
        pages[key] = {
            "url": key,
            "status": row.get("status"),
            "final_url": row.get("final_url"),
            "error": row.get("error"),
            "depth": row.get("depth"),
            # Carried because `navigation_links` groups by it. This projection is why
            # the language fix did not work the first time: the field was recorded by
            # the crawl, read by the classifier, and dropped in between — so every page
            # arrived declaring nothing and the whole site was one group again. A
            # projection that silently narrows what a reader can ask is the same class
            # of bug as the one being fixed.
            "lang": row.get("lang"),
        }
        if row.get("error") or not carries_content(row.get("status")) or not row.get("html"):
            fetch_errors.append({"url": key, "status": row.get("status"),
                                 "error": row.get("error")})
            continue
        for link in row.get("links") or []:
            if not link.get("internal"):
                continue
            links.append({
                "source": key,
                "target": link["target"],
                "anchor": link.get("anchor") or "",
                "rel": link.get("rel") or [],
                "nofollow": bool(link.get("nofollow")),
            })
    return {"pages": pages, "links": links, "fetch_errors": fetch_errors}


def _pair(link: dict) -> tuple:
    return (link["target"], " ".join((link.get("anchor") or "").lower().split()))


def navigation_links(links: list[dict], pages: dict) -> set:
    """The (target, anchor) pairs that are site chrome rather than editorial links.

    A pair carried by most of the crawled pages is a navigation bar or a footer. The
    distinction did not exist while each script ran its own small crawl, and the
    shared crawl is what forced it: reading the whole site instead of 25 pages at
    depth 1 made every navigation entry look like exact-match anchor spam, so BL-081
    warned about the header on a site whose links were fine. Repetition across pages
    is a menu; repetition within one page is stuffing, and that is what this item is
    for.

    Deliberately requires a crawl worth generalising from. On two pages "most pages"
    means nothing, and a link on both of them is as likely to be editorial.

    **"Most pages" is asked once per language section, not only once per site.** A
    translated site has one menu per language, so on a trilingual site of 24 pages no
    menu entry appears on more than 8 of them — 33%, under any share worth calling
    sitewide. The whole-site question then answers "no navigation here", every one of
    the 489 menu links is graded as editorial, and BL-081 reports the header as
    exact-match anchor spam on a site whose links are fine. That is the same failure
    the docstring above describes, one level up: the earlier fix taught the check that
    repetition across pages is a menu, and it still could not see a menu that repeats
    across a *section*.

    The grouping is the page's declared `<html lang>`, recorded by the crawl. Measured,
    not inferred from URL shape, because `/en/` is a convention and `lang` is a
    statement. Pages that declare nothing group together under one key, which is what a
    monolingual site is — so nothing about a single-language site changes.

    Stuffing still cannot hide in here. A pair with one source page has a reach of one,
    and one is never more than half of a group that must hold at least four pages to be
    asked about at all.
    """
    html_pages = [key for key, row in pages.items()
                  if carries_content(row.get("status"))]
    if len(html_pages) < MIN_PAGES_FOR_SITEWIDE:
        return set()
    sources: dict[tuple, set] = defaultdict(set)
    for link in links:
        sources[_pair(link)].add(link["source"])

    groups: dict[str, set] = defaultdict(set)
    for key in html_pages:
        groups[_lang_key(pages[key])].add(key)
    # The whole crawl is one of the groups asked, so a footer link that does cross every
    # language is still chrome. Sections too small to generalise from are dropped rather
    # than answered — the floor means the same thing here as it does site-wide.
    scopes = [set(html_pages)] + [pages_in for pages_in in groups.values()
                                  if len(pages_in) >= MIN_PAGES_FOR_SITEWIDE]

    chrome = set()
    for pair, srcs in sources.items():
        for scope in scopes:
            if len(srcs & scope) > len(scope) * SITEWIDE_PAGE_SHARE:
                chrome.add(pair)
                break
    return chrome


def _lang_key(row: dict) -> str:
    """The language section a page belongs to, from what it declares.

    Only the primary subtag: `en-GB` and `en-US` are one navigation, and a site that
    writes one of each is not two sections. A page declaring nothing gets `""`, which
    is a real group — on a monolingual site every page lands in it.
    """
    return primary_language(row) or ""


def audit_anchor_text(start_url: str, inventory: dict | None = None, depth: int = 1,
                      max_pages: int = 25, timeout: int = 15,
                      inventory_path: str = "") -> dict:
    if inventory is None:
        inventory = site_crawl.inventory_for(
            start_url, inventory_path, depth=depth, max_pages=max_pages,
            timeout=timeout, signatures=False)
    crawl = anchors_from_inventory(inventory)
    links = crawl["links"]
    navigation = navigation_links(links, crawl["pages"])
    editorial = [link for link in links
                 if _pair(link) not in navigation]
    by_target: dict[str, list[str]] = defaultdict(list)
    text_counter = Counter()
    generic = []
    empty = []
    nofollow = []

    for link in links:
        text = (link.get("anchor") or "").strip()
        normalized_text = " ".join(text.lower().split())
        by_target[link["target"]].append(text)
        if text:
            text_counter[normalized_text] += 1
        if not text:
            empty.append(link)
        elif normalized_text in GENERIC_ANCHORS:
            generic.append(link)
        if link.get("nofollow"):
            nofollow.append(link)

    # Repetition *within* a page is anchor stuffing; repetition *across* pages is a
    # navigation bar. The two look identical in a link count and they are not the same
    # finding, so the repetition checks run over editorial links only.
    editorial_by_target: dict[str, list[str]] = defaultdict(list)
    for link in editorial:
        editorial_by_target[link["target"]].append((link.get("anchor") or "").strip())

    target_rows = []
    overused_exact = []
    low_diversity = []
    for target, anchors in sorted(by_target.items()):
        editorial_anchors = editorial_by_target.get(target, [])
        normalized = [" ".join(a.lower().split()) for a in editorial_anchors
                      if a.strip()]
        total = len(anchors)
        unique = len(set(normalized))
        diversity_ratio = round(unique / max(1, len(normalized)), 2) if normalized else 0
        top_anchor, top_count = ("", 0)
        if normalized:
            top_anchor, top_count = Counter(normalized).most_common(1)[0]
        row = {
            "target": target,
            "total_internal_links": total,
            "editorial_links": len(editorial_anchors),
            "unique_anchor_texts": unique,
            "diversity_ratio": diversity_ratio,
            "top_anchor": top_anchor,
            "top_anchor_count": top_count,
        }
        target_rows.append(row)
        if top_count >= EXACT_MATCH_MIN_LINKS and \
                top_count / max(1, len(normalized)) >= EXACT_MATCH_SHARE:
            overused_exact.append(row)
        if len(editorial_anchors) >= DIVERSITY_MIN_LINKS and \
                diversity_ratio < DIVERSITY_FLOOR:
            low_diversity.append(row)

    issues = []
    if empty:
        issues.append({"severity": "error", "type": "empty_anchor", "count": len(empty), "message": "Internal links with empty anchor text"})
    if generic:
        issues.append({"severity": "warning", "type": "generic_anchor", "count": len(generic), "message": "Generic internal anchor text is overused"})
    if nofollow:
        issues.append({"severity": "warning", "type": "internal_nofollow", "count": len(nofollow), "message": "Internal links use nofollow"})
    if overused_exact:
        issues.append({"severity": "warning", "type": "exact_match_overuse", "count": len(overused_exact), "message": "Targets have highly repetitive anchor text"})
    if low_diversity:
        issues.append({"severity": "info", "type": "low_anchor_diversity", "count": len(low_diversity), "message": "Targets have low anchor diversity"})

    return {
        # Zero overused anchors across zero crawled pages is not a clean link
        # profile. `fetch_errors` (plural) stays per-URL; this is the whole-crawl
        # verdict the runner needs to tell silence from a pass, and it now comes
        # from the crawl rather than being re-derived — one place decides whether
        # the site was read at all.
        "fetch_error": inventory.get("fetch_error") or (
            None if len(crawl["fetch_errors"]) < len(crawl["pages"])
            else "no page could be read"),
        # The crawl says whether it read the whole site. Carried here because
        # every count beside it is a count over what was read, and the item
        # asserting `none of these` cannot tell the difference on its own.
        "truncated": bool((inventory.get("summary") or {}).get("truncated")),
        "start_url": normalize_url(start_url),
        "pages_crawled": len(crawl["pages"]),
        "links_analyzed": len(links),
        "summary": {
            "unique_targets": len(by_target),
            "empty_anchors": len(empty),
            "generic_anchors": len(generic),
            "nofollow_internal_links": len(nofollow),
            # What was set aside as site chrome, so a reader can see the
            # subtraction rather than wonder where the nav went.
            "navigation_links": len(links) - len(editorial),
            "editorial_links": len(editorial),
            "overused_exact_match_targets": len(overused_exact),
            "low_diversity_targets": len(low_diversity),
        },
        "top_anchor_texts": [{"anchor": text, "count": count} for text, count in text_counter.most_common(25)],
        "targets": target_rows,
        "examples": {
            "empty_anchors": empty[:20],
            "generic_anchors": generic[:20],
            "nofollow_internal_links": nofollow[:20],
            "overused_exact_match_targets": overused_exact[:20],
            "low_diversity_targets": low_diversity[:20],
        },
        "issues": issues,
        "fetch_errors": crawl["fetch_errors"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit internal anchor text diversity and quality")
    parser.add_argument("url", help="Website URL to crawl")
    parser.add_argument("--inventory", default="",
                        help="crawl inventory from site_crawl.py; crawled here when "
                             "not supplied")
    parser.add_argument("--depth", type=int, default=1, help="Internal crawl depth (default: 1)")
    parser.add_argument("--max-pages", type=int, default=25, help="Maximum pages to crawl (default: 25)")
    parser.add_argument("--timeout", type=int, default=15, help="Request timeout in seconds")
    parser.add_argument("--json", "-j", action="store_true", help="Output JSON")
    args = parser.parse_args()

    result = audit_anchor_text(args.url, depth=args.depth, max_pages=args.max_pages,
                              timeout=args.timeout, inventory_path=args.inventory)
    lines = [
        f"Anchor text audit for {result['start_url']}",
        f"Pages crawled: {result['pages_crawled']}  Links analyzed: {result['links_analyzed']}",
        (
            "Issues: "
            f"empty={result['summary']['empty_anchors']} "
            f"generic={result['summary']['generic_anchors']} "
            f"nofollow={result['summary']['nofollow_internal_links']} "
            f"exact_match_targets={result['summary']['overused_exact_match_targets']}"
        ),
    ]
    lines.extend(f"[{issue['severity']}] {issue['message']}: {issue['count']}" for issue in result["issues"])
    print_json_or_text(result, args.json, lines)


if __name__ == "__main__":
    main()
