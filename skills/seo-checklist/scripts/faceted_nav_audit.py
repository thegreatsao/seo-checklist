#!/usr/bin/env python3
"""Detect faceted navigation crawl traps from URLs and optional page fetches.

Takes a *list* of URLs, because a crawl trap is a property of a set: five parameter
variants sharing one path, or one parameter recurring across many URLs. A single URL
can exhibit neither.

Which is what `--from-page` is for. The registry has exactly one URL to give — the
entry point — and passing it alone made AR-163 an item that could not fail on any site
ever audited: `path_explosions` needs five URLs sharing a path and `frequent_params`
needs a parameter seen three times, and one URL supplies one of each. `--from-page`
audits the internal links of the page it is given, which is also the truer form of the
question: a facet becomes a crawl trap when the site *links to* it, because that is how
a crawler finds it.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from urllib.parse import parse_qs, urlparse

try:
    from lib.safe_http import robots_allows
except ImportError:
    from scripts.lib.safe_http import robots_allows

from seo_common import fetch_url, parse_html, read_urls, same_host


# basis: inherited — three query parameters on one URL, present at import. A count, not
#  a judgement about which parameters: three combined facets is where the crawlable
#  variants of a page start multiplying.
PARAM_COMBINATION_COUNT = 3
# basis: inherited — five URL variants of one path, present at import.
PATH_EXPLOSION_VARIANTS = 5
# basis: inherited — a parameter seen on three URLs, present at import, and reported as
#  info rather than a finding: frequency here is evidence for a human, not a verdict.
FREQUENT_PARAM_COUNT = 3
# basis: inherited — present at import as `limit=300` on `urls_from_page`, where the
#  threshold inventory could not see it. It is a threshold and not a budget because
#  AR-163 asserts that `issues` contains no medium-or-worse finding, and this number
#  decides how many page-linked URLs can supply one. Measured for 0.91.0: 299 internal
#  links fill the 300-URL result together with the page and leave nothing unread; a
#  300th internal link is omitted from `rows` and `issues` and must mark the result
#  incomplete rather than move the cap.
MAX_URLS_FROM_PAGE = 300

FACET_KEYS = {"sort", "filter", "color", "size", "brand", "price", "min_price", "max_price", "rating", "page", "view", "availability", "material"}


def audit(urls: list[str], fetch: bool = False, timeout: int = 15) -> dict:
    rows = []
    by_path = defaultdict(list)
    param_counts = Counter()
    for url in urls:
        parsed = urlparse(url)
        params = parse_qs(parsed.query, keep_blank_values=True)
        facet_params = sorted(k for k in params if k.lower() in FACET_KEYS or k.lower().startswith("filter"))
        flags = []
        if len(params) >= PARAM_COMBINATION_COUNT:
            flags.append("parameter_combination")
        if facet_params:
            flags.append("facet_parameters")
        if "sort" in params:
            flags.append("sort_url")
        if "page" in params and len(params) > 1:
            flags.append("paginated_filtered_url")
        row = {"url": url, "path": parsed.path or "/", "params": sorted(params), "facet_params": facet_params, "flags": flags}
        if fetch:
            page = fetch_url(url, timeout=timeout, max_bytes=1_500_000)
            row["status"] = page.get("status")
            if page.get("text"):
                html = parse_html(page["text"], page.get("url") or url)
                row["canonical"] = html.get("canonical")
                row["meta_robots"] = html.get("meta_robots")
                if facet_params and not html.get("canonical"):
                    flags.append("facet_missing_canonical")
                if facet_params and not (html.get("meta_robots") and "noindex" in html["meta_robots"].lower()):
                    flags.append("facet_not_noindexed")
        for key in params:
            param_counts[key] += 1
        by_path[row["path"]].append(url)
        rows.append(row)
    path_explosions = {path: vals for path, vals in by_path.items() if len(vals) >= PATH_EXPLOSION_VARIANTS}
    issues = []
    # *Control* Faceted Navigation, and this is what control means: a facet URL is
    # either canonicalised onto the page it varies, noindexed, or disallowed by
    # robots.txt. The item's own fix text names all three controls. A facet that has
    # none is duplicate content by construction — not a judgement about the site, a
    # fact about the two flags and the robots policy. Until 0.50.0 the only graded
    # finding in this file was the parameter count, so the item's own subject produced
    # no verdict and its FAIL was unreachable.
    uncontrolled = []
    for row in rows:
        if ("facet_missing_canonical" in row["flags"]
                and "facet_not_noindexed" in row["flags"]
                and robots_allows(row["url"])[0]):
            uncontrolled.append(row["url"])
    if uncontrolled:
        issues.append({"severity": "error",
                       "message": "Facet URL is neither canonicalised nor noindexed",
                       "count": len(uncontrolled), "evidence": uncontrolled[:10]})
    if path_explosions:
        issues.append({"severity": "warning", "message": "Multiple parameter variants share the same path", "count": len(path_explosions)})
    frequent_params = {k: v for k, v in param_counts.items() if v >= FREQUENT_PARAM_COUNT}
    if frequent_params:
        issues.append({"severity": "info", "message": "Frequent URL parameters detected", "evidence": frequent_params})
    return {"count": len(rows), "frequent_params": frequent_params, "path_explosions": path_explosions, "rows": rows, "issues": issues}


def urls_from_page(url: str, timeout: int = 15,
                   limit: int = MAX_URLS_FROM_PAGE) -> tuple[list[str], bool]:
    """The page's own internal links, plus the page itself.

    Same-host only: a facet on somebody else's site is not this site's crawl trap.
    Capped, because a category page on a real store can link to thousands of parameter
    combinations — which is the finding, and does not need all of them enumerated.
    """
    page = fetch_url(url, timeout=timeout, max_bytes=2_000_000)
    if not page.get("text"):
        return [url], False
    parsed = parse_html(page["text"], page.get("url") or url)
    found = [url]
    truncated = False
    for link in parsed.get("links") or []:
        href = link.get("href") if isinstance(link, dict) else link
        if href and same_host(href, url):
            if len(found) >= limit:
                truncated = True
                break
            found.append(href)
    return found, truncated


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit faceted navigation URLs",
                                     epilog=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("urls", nargs="*")
    parser.add_argument("--url-file")
    parser.add_argument("--from-page", action="store_true",
                        help="audit the internal links of the given page rather than "
                             "the page alone — a crawl trap is a property of a set of "
                             "URLs, so one URL can never show one")
    parser.add_argument("--fetch", action="store_true", help="Fetch pages for canonical/noindex checks")
    parser.add_argument("--max-urls", type=int, default=MAX_URLS_FROM_PAGE,
                        help="Maximum page-derived URLs to audit, including the page")
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument("--json", "-j", action="store_true")
    args = parser.parse_args()
    urls = read_urls(args.urls, args.url_file)
    truncated = False
    if args.from_page and urls:
        page_urls, truncated = urls_from_page(urls[0], args.timeout, args.max_urls)
        urls = read_urls(page_urls)
    result = audit(urls, args.fetch, args.timeout)
    result["truncated"] = truncated
    print(json.dumps(result, indent=2) if args.json else "\n".join(f"{','.join(r['flags']) or 'ok'}\t{r['url']}" for r in result["rows"]))


if __name__ == "__main__":
    main()
