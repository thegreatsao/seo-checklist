#!/usr/bin/env python3
"""Map topical clusters and internal-link coverage from URLs, HTML, or CSV."""

from __future__ import annotations

from lib import python_floor  # noqa: F401

import argparse
import csv
import json
import re
from collections import Counter, defaultdict

import site_crawl
from seo_common import load_source, normalize_url, parse_html, read_as_url, refused_kind


STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "your", "you", "how", "what", "why", "are", "was",
    "has", "have", "can", "into", "guide", "best", "top", "page", "home", "about", "contact", "our",
}


def _topic_from_text(text: str) -> str:
    words = [word for word in re.findall(r"[a-z][a-z0-9'-]{2,}", (text or "").lower()) if word not in STOPWORDS]
    if not words:
        return "uncategorized"
    return Counter(words).most_common(1)[0][0]


# basis: convention — a word in more than half of the titles the crawl read is the
#  site's own (a brand, a section name), not one page's topic (F06). The topic below is the
#  most frequent title word, and before this a brand leading every title made the whole
#  site one cluster, so a shop whose product pages do not all link to one another failed
#  AR-153 for a silo it never meant to build. Half is the line between a word most pages
#  share and a word a group of them shares; nothing external sets it, and on a site about
#  one subject it also sets that subject aside, which leaves the item passing — the side
#  this crude a reading should err on.
SITE_WIDE_SHARE = 0.5


def _split_links(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in re.split(r"[\s,;|]+", value) if part.strip()]


def _rows_from_csv(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        rows = []
        for row in reader:
            title = row.get("title") or row.get("Title") or ""
            topic = row.get("topic") or row.get("Topic") or _topic_from_text(title)
            cluster = row.get("cluster") or row.get("Cluster") or topic
            rows.append({
                "url": normalize_url(row.get("url") or row.get("URL") or row.get("page") or ""),
                "title": title,
                "topic": topic,
                "cluster": cluster,
                "parent": row.get("parent") or row.get("hub") or row.get("Hub") or "",
                "links": [normalize_url(link) for link in _split_links(row.get("links") or row.get("Links"))],
            })
    return [row for row in rows if row["url"]]


def _row_from_source(source: str, timeout: int) -> dict:
    html, url, fetched = load_source(source, timeout)
    parsed = parse_html(html, url)
    title = parsed.get("title") or " ".join(parsed.get("headings", {}).get("h1", []))
    topic = _topic_from_text(f"{title} {' '.join(sum((v for v in parsed.get('headings', {}).values()), []))}")
    return {
        "url": normalize_url(url or source),
        "title": title,
        "topic": topic,
        "cluster": topic,
        "parent": "",
        "links": [normalize_url(link["href"]) for link in parsed.get("links", [])],
        "error_kind": fetched.get("error_kind"),
    }


def map_inventory(inventory: dict) -> dict:
    """AR-153 over the shared crawl: one row per page read, its topic from its title.

    The crawl records each page's title and links, not its headings, so the topic is the
    most frequent title word once the words most titles share are set aside. A crawl cut
    at its caps does not decide the item: the page it left out can be a topic's hub, so
    the score is withheld (as BL-081's count since 0.171.0).
    """
    pages = site_crawl.html_pages(inventory)
    titles = {key: (row.get("title") or "") for key, row in pages.items()}
    shared = Counter(word for title in titles.values()
                     for word in set(re.findall(r"[a-z][a-z0-9'-]{2,}", title.lower())))
    site_wide = {word for word, n in shared.items()
                 if len(titles) > 1 and n / len(titles) > SITE_WIDE_SHARE}
    rows = []
    for key, row in sorted(pages.items()):
        topic = _topic_from_text(" ".join(
            word for word in re.findall(r"[a-z][a-z0-9'-]{2,}", titles[key].lower())
            if word not in site_wide))
        # A title with no word this pattern reads (empty, non-Latin, only site-wide
        # words) says nothing about the page's topic, so the page is its own cluster
        # rather than one shared "uncategorized" hub (F06 review 3).
        rows.append({"url": normalize_url(key), "title": titles[key], "topic": topic,
                     "cluster": topic if topic != "uncategorized" else key, "parent": "",
                     "links": [normalize_url(link["target"])
                               for link in row.get("links") or [] if link.get("internal")]})
    result = map_clusters(rows)
    result["site_wide_words"] = sorted(site_wide)
    result["fetch_error"] = inventory.get("fetch_error") or (
        None if rows else "the crawl read no page")
    result["fetch_error_kind"] = inventory.get("fetch_error_kind")
    result["truncated"] = bool((inventory.get("summary") or {}).get("truncated"))
    if result["truncated"]:
        result["truncated_reason"] = (
            "the crawl stopped at its page or depth cap, and a page it left out can be "
            "a topic's hub")
        del result["score"]
    return result


def map_clusters(rows: list[dict]) -> dict:
    by_cluster: dict[str, list[dict]] = defaultdict(list)
    known_urls = {row["url"] for row in rows}
    for row in rows:
        by_cluster[row["cluster"] or "uncategorized"].append(row)

    clusters = {}
    issues = []
    for cluster, pages in sorted(by_cluster.items()):
        url_set = {page["url"] for page in pages}
        internal_edges = []
        inbound = Counter()
        outbound_counts = Counter()
        for page in pages:
            for link in page.get("links", []):
                if link in url_set:
                    internal_edges.append({"from": page["url"], "to": link})
                    inbound[link] += 1
                    outbound_counts[page["url"]] += 1

        explicit_hubs = [page for page in pages if page.get("parent") in ("", page["url"]) and re.search(r"(hub|guide|topic|pillar|overview)", page.get("title", ""), re.I)]
        candidate_hub = None
        if explicit_hubs:
            candidate_hub = explicit_hubs[0]["url"]
        elif pages:
            candidate_hub = max(pages, key=lambda page: inbound[page["url"]] + outbound_counts[page["url"]])["url"]

        missing_links = []
        if candidate_hub:
            for page in pages:
                if page["url"] == candidate_hub:
                    continue
                if page["url"] not in [edge["to"] for edge in internal_edges if edge["from"] == candidate_hub]:
                    missing_links.append({"from": candidate_hub, "to": page["url"], "reason": "hub_not_linking_to_spoke"})
                if candidate_hub not in page.get("links", []):
                    missing_links.append({"from": page["url"], "to": candidate_hub, "reason": "spoke_not_linking_to_hub"})

        orphan_candidates = [page["url"] for page in pages if inbound[page["url"]] == 0 and page["url"] in known_urls]
        if len(pages) > 1 and not internal_edges:
            issues.append({"severity": "warning", "message": f"Cluster '{cluster}' has no detected internal links."})
        if orphan_candidates:
            issues.append({"severity": "info", "message": f"Cluster '{cluster}' has {len(orphan_candidates)} orphan candidate(s)."})

        clusters[cluster] = {
            "page_count": len(pages),
            "hub": candidate_hub,
            "topics": sorted({page.get("topic") for page in pages if page.get("topic")}),
            "internal_edges": internal_edges,
            "missing_links": missing_links[:100],
            "orphan_candidates": orphan_candidates,
        }

    total_missing = sum(len(cluster["missing_links"]) for cluster in clusters.values())
    total_edges = sum(len(cluster["internal_edges"]) for cluster in clusters.values())
    score = max(0, 100 - min(60, total_missing * 4) - (20 if total_edges == 0 and len(rows) > 1 else 0))
    # A score of 100 out of zero pages is not a coherent site, it is an empty crawl.
    return {"page_count": len(rows), "cluster_count": len(clusters), "score": score,
            "clusters": clusters, "issues": issues,
            # A row exists for a page that could not be read — with an empty title
            # and no links — and one empty row scored 100 out of one "page". Read
            # means it produced something.
            "fetch_error": (None if any(r.get("title") or r.get("links")
                                        for r in rows)
                            else "no page could be read"),
            "fetch_error_kind": refused_kind(r.get("error_kind") for r in rows)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Map topical clusters from a CSV manifest or URL/local HTML inputs.")
    parser.add_argument("sources", nargs="*", help="URL or local HTML files")
    parser.add_argument("--inventory", default=None,
                        help="crawl inventory from site_crawl.py: map the pages it read "
                             "(one source URL names the site; crawled here when empty)")
    parser.add_argument("--csv", dest="csv_path", help="CSV with url,title,topic,cluster,parent,links columns")
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument("--json", "-j", action="store_true", help="Output JSON")
    args = parser.parse_args()

    if args.inventory is not None:
        if len(args.sources) != 1:
            parser.error("--inventory takes exactly one source: the site's URL")
        site = read_as_url(args.sources[0])
        result = map_inventory(site_crawl.inventory_for(site, args.inventory,
                                                        signatures=False))
    else:
        rows = []
        if args.csv_path:
            rows.extend(_rows_from_csv(args.csv_path))
        rows.extend(_row_from_source(source, args.timeout) for source in args.sources)
        result = map_clusters(rows)
    print(json.dumps(result, indent=2) if args.json
          else f"Score: {result.get('score', 'withheld')} Clusters: {result['cluster_count']}")


if __name__ == "__main__":
    from lib.utf8_streams import utf8_streams
    utf8_streams()
    from lib.typed_credential import credentials_beside_argv
    credentials_beside_argv()
    main()
