#!/usr/bin/env python3
"""Discover and validate XML sitemaps."""

from __future__ import annotations

import argparse
import re
from datetime import datetime, timezone

from seo_common import (
    discover_sitemap_urls,
    fetch_url,
    issue,
    normalize_url,
    parse_html,
    parse_sitemap_xml,
    print_json_or_text,
    same_host,
)

try:
    from lib.safe_http import is_private_host
except ImportError:
    from scripts.lib.safe_http import is_private_host


# basis: standard — 50,000 URLs per sitemap file, the limit stated in the sitemaps.org
#  protocol. Google documents the same figure alongside a 50MB uncompressed cap.
MAX_URLS_PER_SITEMAP = 50_000
# basis: inherited — 25 sitemap files followed, present at import. The reason it is not
#  larger is that a sitemap index can point at itself. It was recorded here as "an
#  operational cap rather than a verdict"; that was wrong. GO-136 is `high` and passes
#  by finding no issue at or above medium, so on a site whose index lists more than 25
#  files the walk stopped, said nothing, and the item read a clean sitemap set off the
#  first 25. `truncated` below is the half that was missing, not a new cap.
MAX_SITEMAPS_FOLLOWED = 25

def check_sitemaps(site_url: str, sitemap_urls: list[str] | None = None, fetch_urls: bool = False, timeout: int = 15, max_urls: int = 100) -> dict:
    # A URL the caller supplied, or one robots.txt declares, is one the site claims
    # exists — failing to load it is a defect. A conventional filename we merely
    # guessed at is not: `/sitemap_index.xml` is an alternative to `/sitemap.xml`,
    # not a companion, so its absence is the normal case. `probed` keeps the two
    # apart; before it, every site with exactly one sitemap collected two "Sitemap
    # returned HTTP 404" errors and could not pass GO-136 or GO-138.
    if sitemap_urls:
        probed = set()
    else:
        pairs = discover_sitemap_urls(site_url, timeout=timeout, with_source=True)
        sitemap_urls = [url for url, _ in pairs]
        probed = {url for url, source in pairs if source == "probed"}
    result = {
        "site": normalize_url(site_url),
        "sitemaps_checked": [],
        "urls": [],
        "summary": {"sitemaps": 0, "urls": 0, "indexes": 0, "issues": 0,
                    "probed_absent": 0},
        "issues": [],
    }
    queue = list(dict.fromkeys(sitemap_urls))
    seen_sitemaps = set()
    seen_urls = set()

    # Recorded before the walk so the loop below can end either way without the
    # caller having to reconstruct which way it ended.
    while queue and len(seen_sitemaps) < MAX_SITEMAPS_FOLLOWED:
        sm_url = normalize_url(queue.pop(0), site_url)
        if sm_url in seen_sitemaps:
            continue
        seen_sitemaps.add(sm_url)
        fetched = fetch_url(sm_url, timeout=timeout, max_bytes=8_000_000)
        entry = {
            "url": sm_url,
            "status": fetched.get("status"),
            "final_url": fetched.get("url"),
            "redirects": fetched.get("redirect_chain", []),
            "type": None,
            "url_count": 0,
            "sitemap_count": 0,
            "error": fetched.get("error"),
            "error_kind": fetched.get("error_kind"),
        }
        if fetched.get("status") != 200:
            if sm_url in probed:
                # Not there, and nothing said it would be. Recorded so the run is
                # inspectable, but it is not an issue and must not read as one.
                entry["absent"] = True
                result["summary"]["probed_absent"] += 1
            else:
                result["issues"].append(issue("error", f"Sitemap returned HTTP {fetched.get('status')}", sm_url, fetched.get("error")))
            result["sitemaps_checked"].append(entry)
            continue
        parsed = parse_sitemap_xml(fetched.get("text") or "", sm_url)
        entry["type"] = parsed["type"]
        entry["error"] = parsed["error"]
        if parsed["error"]:
            entry["error_kind"] = "other"
        entry["url_count"] = len(parsed["urls"])
        entry["sitemap_count"] = len(parsed["sitemaps"])
        if parsed["error"]:
            result["issues"].append(issue("error", f"Invalid sitemap XML: {parsed['error']}", sm_url))
        if parsed["type"] == "sitemapindex":
            result["summary"]["indexes"] += 1
            queue.extend(item["loc"] for item in parsed["sitemaps"])
        if parsed["type"] == "urlset" and len(parsed["urls"]) > MAX_URLS_PER_SITEMAP:
            result["issues"].append(issue("error", "Sitemap exceeds 50,000 URL limit", sm_url, str(len(parsed["urls"]))))

        for row in parsed["urls"]:
            loc = row["loc"]
            if loc in seen_urls:
                result["issues"].append(issue("warning", "Duplicate URL in sitemap set", loc))
                continue
            seen_urls.add(loc)
            url_entry = {"url": loc, **{k: v for k, v in row.items() if k != "loc"}, "checks": {}}
            if not loc.startswith("https://") and not is_private_host(loc):
                # Skipped for private hosts: a staging site or a local fixture on
                # http:// is not making an SEO mistake, and warning about it would
                # be the only reason a clean sitemap could not pass GO-136 there.
                # For anything publicly routable the warning stands.
                result["issues"].append(issue("warning", "Sitemap URL is not HTTPS", loc))
            if not same_host(site_url, loc):
                result["issues"].append(issue("warning", "Sitemap URL is cross-host", loc))
            if not row.get("lastmod"):
                result["issues"].append(issue("info", "Sitemap URL missing lastmod", loc))
            elif not re.match(r"^\d{4}-\d{2}-\d{2}", row["lastmod"]):
                result["issues"].append(issue("warning", "Sitemap lastmod is not ISO-like", loc, row["lastmod"]))
            elif row["lastmod"][:10] > datetime.now(timezone.utc).date().isoformat():
                result["issues"].append(issue("warning", "Sitemap lastmod is in the future", loc, row["lastmod"]))

            if fetch_urls and len(result["urls"]) < max_urls:
                page = fetch_url(loc, timeout=timeout, max_bytes=1_000_000)
                url_entry["checks"]["status"] = page.get("status")
                url_entry["checks"]["final_url"] = page.get("url")
                url_entry["checks"]["redirects"] = page.get("redirect_chain", [])
                url_entry["checks"]["error"] = page.get("error")
                url_entry["checks"]["error_kind"] = page.get("error_kind")
                if page.get("status") and page["status"] >= 400:
                    result["issues"].append(issue("error", f"Sitemap URL returns HTTP {page['status']}", loc))
                if page.get("redirect_chain"):
                    result["issues"].append(issue("warning", "Sitemap URL redirects", loc, " -> ".join(page["redirect_chain"] + [page.get("url", "")])))
                ctype = page.get("headers", {}).get("content-type", "")
                if page.get("text") and "html" in ctype:
                    html = parse_html(page["text"], page.get("url") or loc)
                    url_entry["checks"]["meta_robots"] = html.get("meta_robots")
                    url_entry["checks"]["canonical"] = html.get("canonical")
                    if html.get("meta_robots") and "noindex" in html["meta_robots"].lower():
                        result["issues"].append(issue("error", "Sitemap URL has meta noindex", loc, html["meta_robots"]))
                    if html.get("canonical") and normalize_url(html["canonical"]) != normalize_url(page.get("url") or loc):
                        result["issues"].append(issue("warning", "Canonical does not match sitemap URL", loc, html["canonical"]))
            result["urls"].append(url_entry)
        result["sitemaps_checked"].append(entry)

    # A queue with anything still in it means the walk stopped at the cap rather
    # than at the end of the index. Read by the runner, which withholds GO-136's
    # and GO-138's clean verdict rather than reading it off the files that fit.
    result["truncated"] = bool(queue)
    result["summary"]["sitemaps"] = len(result["sitemaps_checked"])
    result["summary"]["loaded"] = sum(1 for e in result["sitemaps_checked"]
                                      if e.get("status") == 200)
    result["summary"]["urls"] = len(result["urls"])
    # No sitemap anywhere *is* a finding, and downgrading the probe misses must not
    # swallow it. This is the one case where absence is the site's problem: nothing
    # declared a sitemap and none of the conventional names answered.
    # ...unless nothing answered at all. Every attempt refused at the connection is
    # not a site without a sitemap, it is a site we never reached — and reporting the
    # first as the second put "No sitemap found" plus a failing CI-002 on any origin
    # that dropped connections mid-audit.
    reached = [e for e in result["sitemaps_checked"] if e.get("status") is not None]
    if not reached and result["sitemaps_checked"]:
        result["fetch_error"] = ("no sitemap location could be reached: "
                                 + (result["sitemaps_checked"][0].get("error")
                                    or "connection failed"))
    if not result["summary"]["loaded"] and not result.get("fetch_error"):
        result["issues"].append(issue(
            "error", "No sitemap found",
            result["site"],
            f"tried {len(result['sitemaps_checked'])} location(s): "
            + ", ".join(e["url"] for e in result["sitemaps_checked"][:5])))
    result["summary"]["issues"] = len(result["issues"])
    # The structured form of "is there an invalid URL in the sitemap". Present only
    # when URLs were actually probed: without `--fetch-urls` no `status` is
    # collected, and a count of zero over URLs nobody requested says the sitemap is
    # clean when nothing about it was read.
    #
    # This replaced a regex over issue messages, `(?i)404|redirect|noindex`, which
    # asked a narrower question than anyone intended — the message for a bad status
    # is "Sitemap URL returns HTTP {status}", so `404` matched a 404 and nothing
    # else. A sitemap of URLs returning 500 or 503 passed the item outright.
    # The clean answer is withheld whenever a probe failed, and the failing answer
    # always stands: a count of zero taken over the URLs that happened to answer is
    # not a statement about the sitemap, while a URL found returning 500 is a defect
    # no unreachable neighbour undoes. `image_weight_audit.py` argues the same
    # asymmetry at greater length for `broken_image_count`.
    read = [row for row in result["urls"] if row["checks"].get("status") is not None]
    unread = [row for row in result["urls"]
              if row["checks"].get("status") is None and row["checks"].get("error")]
    invalid = sum(1 for row in read
                  if row["checks"]["status"] >= 400
                  or row["checks"].get("redirects")
                  or "noindex" in (row["checks"].get("meta_robots") or "").lower())
    if invalid or (read and not unread):
        result["invalid_url_count"] = invalid
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Discover and validate XML sitemaps")
    parser.add_argument("site", help="Site URL")
    parser.add_argument("--sitemap", action="append", help="Explicit sitemap URL; can be repeated")
    parser.add_argument("--fetch-urls", action="store_true", help="Fetch sitemap URLs for status/noindex/canonical checks")
    parser.add_argument("--max-urls", type=int, default=100, help="Max sitemap URLs to fetch when --fetch-urls is used")
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument("--json", "-j", action="store_true", help="Output JSON")
    args = parser.parse_args()
    result = check_sitemaps(args.site, args.sitemap, args.fetch_urls, args.timeout, args.max_urls)
    lines = [
        f"Sitemap check for {result['site']}",
        f"Sitemaps: {result['summary']['sitemaps']}  URLs: {result['summary']['urls']}  Issues: {result['summary']['issues']}",
    ] + [f"[{i['severity']}] {i['message']}: {i.get('url') or ''}" for i in result["issues"][:25]]
    print_json_or_text(result, args.json, lines)


if __name__ == "__main__":
    main()
