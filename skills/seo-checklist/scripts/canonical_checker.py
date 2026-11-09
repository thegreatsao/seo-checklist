#!/usr/bin/env python3
"""Check canonical tags for self/cross-domain/chained targets."""

from __future__ import annotations

from lib import python_floor  # noqa: F401

import argparse
import ipaddress
import json
from collections import defaultdict
from urllib.parse import urlparse, urlunparse

import site_crawl
from seo_common import (read_as_url, carries_content, comparable_url,
                        declared_canonicals, fetch_url, google_noindex, issue,
                        normalize_url, parse_html, read_urls, refused_kind, same_host)


# basis: convention — the same hundred target requests as gsc_links_csv.MAX_TARGETS.
MAX_TARGET_FETCHES = 100


def url_variants(url: str) -> list[str]:
    """The other spellings a page answers to on most servers: the other scheme, the
    `www.` host or the bare one, and the path with or without its trailing slash.

    CI-009 asks for one canonical URL, so each variant has to redirect to it, declare
    it, or not serve the page at all (the owner's ruling for F15). An IP address has no
    `www.` twin; the root has no slashless one.
    """
    parsed = urlparse(normalize_url(url))
    parsed = parsed._replace(netloc=parsed.netloc.lower())
    host = parsed.hostname or ""
    out = [parsed._replace(scheme="http" if parsed.scheme == "https" else "https")]
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        if host:
            twin = host[4:] if host.startswith("www.") else "www." + host
            out.append(parsed._replace(netloc=parsed.netloc.replace(host, twin, 1)))
    if parsed.path not in ("", "/"):
        path = (parsed.path.rstrip("/") if parsed.path.endswith("/")
                else parsed.path + "/")
        out.append(parsed._replace(path=path))
    return [urlunparse(variant) for variant in out]


def _busy(fetched: dict) -> bool:
    """A 429 or a 503: the server said it is too busy to answer, this time. Another 5xx
    is an answer, and a canonical naming it is broken (TE-176 since 0.128.0)."""
    return fetched.get("status") in (429, 503)


def _page_print(html: dict) -> tuple:
    """(title, text hash) of a parsed page: what tells one page from another."""
    title = " ".join(str(html.get("title") or "").split()).lower()
    soup = html.get("soup")
    text = site_crawl.content_text(soup) if soup is not None else ""
    return title, site_crawl.exact_hash(text) if text.strip() else ""


def _consolidated(fetched: dict, accepted: set, page: tuple) -> bool:
    """Whether a variant's answer leaves one URL serving the page: it was not served
    (no answer, an error status), it landed on an accepted URL, it declares one as its
    only canonical, it asks not to be indexed — or it is another page, not this one
    served twice (review round 1: a soft 404 or a catch-all shell at `/a/` is a defect
    of its own, not `/a` at two URLs). Another page is one declaring a canonical
    elsewhere, or one whose text differs from the page's (`page`); the title decides
    only between two pages with no text, since a site may title every page alike
    (review round 2)."""
    if not carries_content(fetched.get("status")) or not fetched.get("text"):
        return True
    where = fetched.get("url") or ""
    if comparable_url(where) in accepted:
        return True
    html = parse_html(fetched["text"], where)
    declared = declared_canonicals(html, fetched.get("headers"), where)
    if len(declared) == 1 and comparable_url(declared[0]) in accepted:
        return True
    if google_noindex(html.get("meta_robots"), html.get("meta_googlebot"),
                      fetched.get("x_robots_tags")
                      or (fetched.get("headers") or {}).get("x-robots-tag")):
        return True
    if len(declared) == 1 and comparable_url(declared[0]) != comparable_url(where):
        return True     # it names another page as itself
    title, text = _page_print(html)
    if text or page[1]:
        return text != page[1]
    return not (title and title == page[0])


def check_canonicals(urls: list[str], timeout: int = 15, check_targets: bool = False,
                     variants: bool = False) -> dict:
    rows = []
    issues = []
    canonical_to_pages = defaultdict(list)
    for url in urls:
        fetched = fetch_url(url, timeout=timeout, max_bytes=1_500_000)
        row = {"url": normalize_url(url), "status": fetched.get("status"), "final_url": fetched.get("url"), "canonical": None, "verdict": "unknown", "issues": [],
               "error_kind": fetched.get("error_kind")}
        html = (parse_html(fetched["text"], fetched.get("url") or url)
                if fetched.get("text") else {})
        # The `Link` header's and every `<link rel=canonical>`'s (finding 8).
        canonicals = declared_canonicals(html, fetched.get("headers"),
                                         fetched.get("url") or url)
        noindex = google_noindex(html.get("meta_robots"), html.get("meta_googlebot"),
                                 fetched.get("x_robots_tags")
                                 or (fetched.get("headers") or {}).get("x-robots-tag"))
        target_noindex = False
        target_unanswered = False
        elsewhere = False       # a single canonical naming another URL
        if not canonicals:
            row["verdict"] = "missing"
            row["issues"].append("missing canonical")
            issues.append(issue("warning", "Missing canonical", row["url"]))
        elif len(canonicals) > 1:
            # Google ignores them all ("When more than one is specified, all
            # rel=canonical links will be ignored", Search Central blog, 2013-04):
            # the page declares no canonical it can use.
            row["verdict"] = "conflicting"
            row["canonicals"] = canonicals
            row["issues"].append("conflicting canonicals")
            issues.append(issue("warning", "Conflicting canonicals", row["url"],
                                ", ".join(canonicals)))
        else:
            canonical = canonicals[0]
            row["canonical"] = canonical
            canonical_to_pages[canonical].append(row["url"])
            if comparable_url(canonical) == comparable_url(fetched.get("url") or url):
                row["verdict"] = "self_canonical"
            elif not same_host(row["url"], canonical):
                row["verdict"] = "cross_host"
                row["issues"].append("cross-host canonical")
                issues.append(issue("warning", "Cross-host canonical", row["url"], canonical))
            else:
                row["verdict"] = "canonicalized"
            elsewhere = row["verdict"] != "self_canonical"
            # The target is requested (CI-009, CI-011: the owner's rulings for F15): a
            # canonical naming a page that does not answer 200, or one asking not to be
            # indexed, consolidates into nothing. The page itself needs no second ask.
            if check_targets and elsewhere:
                target = fetch_url(canonical, timeout=timeout, max_bytes=1_000_000)
                row["canonical_status"] = target.get("status")
                target_html = (parse_html(target["text"], target.get("url") or canonical)
                               if target.get("text") else {})
                if target.get("status") is None or _busy(target):
                    # Nothing answered, or a server too busy to (429, 503): neither
                    # broken nor indexable is known (review round 5).
                    target_unanswered = True
                    if row["verdict"] == "canonicalized":
                        row["verdict"] = "target_unchecked"
                    row["issues"].append("canonical target not answered")
                elif not carries_content(target.get("status")):
                    if row["verdict"] == "canonicalized":
                        row["verdict"] = "target_unavailable"
                    row["issues"].append(f"canonical target HTTP {target.get('status')}")
                    issues.append(issue("error", "Canonical target is not 200", row["url"], str(target.get("status"))))
                else:
                    target_noindex = bool(google_noindex(
                        target_html.get("meta_robots"), target_html.get("meta_googlebot"),
                        target.get("x_robots_tags")
                        or (target.get("headers") or {}).get("x-robots-tag")))
                    if target_noindex:
                        row["issues"].append("canonical target is noindex")
                        issues.append(issue("error", "Canonical target is noindex",
                                            row["url"], canonical))
                if target_html.get("canonical") and normalize_url(target_html["canonical"]) != canonical:
                    row["issues"].append("canonical chain detected")
                    issues.append(issue("warning", "Canonical target points elsewhere", row["url"], target_html["canonical"]))
            if variants and row["verdict"] in ("self_canonical", "canonicalized"):
                accepted = {comparable_url(canonical),
                            comparable_url(fetched.get("url") or url)}
                page_print = _page_print(html)
                row["variants"] = []
                for variant in url_variants(fetched.get("url") or url):
                    if comparable_url(variant) in accepted:
                        continue
                    answer = fetch_url(variant, timeout=timeout, max_bytes=1_000_000)
                    ok = None if _busy(answer) else _consolidated(answer, accepted,
                                                                  page_print)
                    row["variants"].append({"url": variant, "status": answer.get("status"),
                                            "final_url": answer.get("url"),
                                            "consolidated": ok})
                    if ok is False:
                        row["issues"].append(f"variant {variant} serves the page")
                        issues.append(issue("error", "URL variant serves the page "
                                            "without consolidating", row["url"], variant))
                if any(v["consolidated"] is False for v in row["variants"]):
                    row["verdict"] = "variant_unconsolidated"
                elif any(v["consolidated"] is None for v in row["variants"]):
                    # A variant too busy to answer is unread, not consolidated.
                    row["verdict"] = "variant_unchecked"
        # CI-011's question: do the page's indexing signals agree? noindex beside a
        # canonical naming another URL asks Google both to drop the page and to fold
        # it into that one (finding 9); a canonical naming a noindex page folds it
        # into a page kept out of the index (F15). A canonical on another host is a
        # legitimate declaration (syndication) and is no mixed signal on its own.
        row["signal"] = ("conflicting" if row["verdict"] == "conflicting"
                         else "noindex_canonicalized" if noindex and elsewhere
                         else "canonical_to_noindex" if target_noindex
                         else "target_unchecked" if target_unanswered
                         else "consistent")
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
        "fetch_error": (None if any(carries_content(row.get("status")) for row in rows)
                        else "no URL could be read"),
        "fetch_error_kind": refused_kind(row.get("error_kind") for row in rows),
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
        if not source.get("html") or not carries_content(source.get("status")):
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
        # Every canonical the crawl read, the `Link` header's included (TE-176, the
        # owner's ruling for F15); two that disagree are none Google can use.
        declared = source.get("canonicals")
        if declared is None:
            declared = [source["canonical"]] if source.get("canonical") else []
        if not declared:
            row["verdict"] = "missing"
            row["issues"].append("missing canonical")
            issues.append(issue("warning", "Missing canonical", row["url"]))
            rows.append(row)
            continue
        if len(declared) > 1:
            row["verdict"] = "conflicting"
            row["canonicals"] = declared
            row["issues"].append("conflicting canonicals")
            issues.append(issue("warning", "Conflicting canonicals", row["url"],
                                ", ".join(declared)))
            rows.append(row)
            continue

        canonical = normalize_url(declared[0], page_url)
        row["canonical"] = canonical
        canonical_to_pages[canonical].append(row["url"])
        # Against where the page landed as well as where it was asked for, as the
        # page path compares with the fetched URL: an entry that redirects to
        # /home/ and names /home/ is canonical to itself. With the query, not by page
        # key: a key drops it, so `?id=1` naming `?id=2` read as self (F15).
        if any(site_crawl.same_page(canonical, where)
               for where in (page_url, final_url, key)):
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

        # The crawl's row answers for the target only when it was read at that URL.
        target_key = comparable_url(canonical)
        if target_key not in target_cache:
            crawled_row = pages.get(site_crawl.page_key(canonical, page_url))
            if crawled_row and any(
                    site_crawl.same_page(canonical, crawled_row.get(field) or "")
                    for field in ("url", "final_url")):
                target_cache[target_key] = crawled_row
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
        if (target_status is None or target.get("error_kind") == "robots"
                or _busy(target)):
            unchecked_targets.add(target_key)
            rows.append(row)
            continue
        if not carries_content(target_status):
            row["issues"].append(f"canonical target HTTP {target_status}")
            issues.append(issue("error", "Canonical target is not 200",
                                row["url"], str(target_status)))

        target_canonical = target.get("canonical")
        if target_canonical is None and target.get("text"):
            target_html = parse_html(target["text"], target.get("url") or canonical)
            target_canonical = target_html.get("canonical")
        if (target_canonical
                and not site_crawl.same_page(normalize_url(target_canonical, canonical),
                                             canonical)
                and not site_crawl.same_page(normalize_url(target_canonical, canonical),
                                             target.get("final_url") or target.get("url")
                                             or canonical)):
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
        "fetch_error_kind": inventory.get("fetch_error_kind"),
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
    parser.add_argument("--variants", action="store_true",
                        help="also request the other scheme, the www/bare host and the "
                             "trailing-slash twin of each URL (CI-009)")
    parser.add_argument("--inventory", default="",
                        help="crawl inventory from site_crawl.py")
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument("--json", "-j", action="store_true")
    args = parser.parse_args()
    args.urls = [read_as_url(url) for url in args.urls]
    if args.inventory:
        if len(args.urls) != 1 or args.url_file:
            parser.error("--inventory requires one positional URL")
        result = check_inventory(args.urls[0], args.inventory, args.timeout)
    else:
        result = check_canonicals(read_urls(args.urls, args.url_file), args.timeout,
                                  args.check_targets, args.variants)
    print(json.dumps(result, indent=2) if args.json else "\n".join(f"{r['verdict']}\t{r['url']}\t{r.get('canonical') or ''}" for r in result["rows"]))


if __name__ == "__main__":
    from lib.utf8_streams import utf8_streams
    utf8_streams()
    from lib.typed_credential import credentials_beside_argv
    credentials_beside_argv()
    main()
