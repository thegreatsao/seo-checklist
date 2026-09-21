#!/usr/bin/env python3
"""
Check for broken links.

With `--inventory` the whole site's **internal** links are read out of the shared
crawl (`site_crawl.py`), which already has a status for every URL it fetched: no
requests, and TE-168 covers the site rather than one page. External link rot is
`external_link_quality.py`'s finding (BL-083) and is not counted twice — a second
script requesting the same third-party URLs is the duplication this shared crawl
exists to remove.

Without an inventory it does what it always did: fetch one page and check every link
on it, internal and external, up to `--max-links`.

Usage:
    python broken_links.py https://example.com
    python broken_links.py https://example.com --inventory inventory.json --json
    python broken_links.py https://example.com --internal-only
"""

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse

import site_crawl
from seo_common import DEAD_FETCH_ERROR_KINDS, fetch_error_kind, html_parser

try:
    import requests
except ImportError:
    print("Error: requests library required. Install with: pip install requests")
    sys.exit(1)

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("Error: beautifulsoup4 library required. Install with: pip install beautifulsoup4")
    sys.exit(1)

try:
    from lib.safe_http import default_headers, safe_get, safe_head
except ImportError:
    from scripts.lib.safe_http import default_headers, safe_get, safe_head


HEADERS = default_headers()


def extract_links(html: str, base_url: str) -> list:
    """Extract all links from HTML content."""
    soup = BeautifulSoup(html, html_parser())
    links = []
    seen = set()

    for tag in soup.find_all("a", href=True):
        href = tag["href"].strip()

        # Skip anchors, javascript, mailto, tel
        if href.startswith(("#", "javascript:", "mailto:", "tel:", "data:")):
            continue

        absolute = urljoin(base_url, href)
        if absolute in seen:
            continue
        seen.add(absolute)

        anchor_text = tag.get_text(strip=True)[:80] or "[no text]"
        links.append({
            "url": absolute,
            "anchor_text": anchor_text,
            "is_internal": urlparse(absolute).netloc == urlparse(base_url).netloc,
        })

    return links


def check_link(link: dict, timeout: int = 10) -> dict:
    """Check a single link's HTTP status."""
    url = link["url"]
    result = {**link, "status": None, "error": None, "error_kind": None,
              "redirect": None, "response_time_ms": None}

    try:
        resp = safe_head(url, timeout=timeout, headers=HEADERS, allow_redirects=True)

        # Some servers reject HEAD, fall back to GET
        if resp.status_code == 405:
            resp = safe_get(url, timeout=timeout, headers=HEADERS,
                            allow_redirects=True, stream=True)

        result["status"] = resp.status_code
        result["response_time_ms"] = round(resp.elapsed.total_seconds() * 1000)

        # Check if redirected
        if resp.history:
            result["redirect"] = {
                "from": url,
                "to": resp.url,
                "hops": len(resp.history),
                "codes": [r.status_code for r in resp.history],
            }

    except requests.exceptions.Timeout as exc:
        result["error"] = "timeout"
        result["error_kind"] = fetch_error_kind(exc)
    except requests.exceptions.ConnectionError as exc:
        result["error"] = "connection_failed"
        result["error_kind"] = fetch_error_kind(exc)
    except requests.exceptions.TooManyRedirects as exc:
        result["error"] = "too_many_redirects"
        result["error_kind"] = fetch_error_kind(exc)
    except requests.exceptions.RequestException as e:
        result["error"] = str(e)[:100]
        result["error_kind"] = fetch_error_kind(e)

    return result


# A page with 300 links used to mean 300 requests, with nothing bounding it. The
# cap exists so the request budget is a property of the tool rather than of
# whatever page it was pointed at — and it is reported, because a truncated check
# that says "300 links, 200 checked" is honest where a silent one is not.
# basis: inherited — 200 links, present at import. TE-168 passes when
#  `summary.broken_or_redirected` is 0, so this cap decides a verdict and not just
#  a runtime; the comment above says the truncation is reported, and `truncated` is
#  now read rather than only printed.
DEFAULT_MAX_LINKS = 200


def check_broken_links(url: str, internal_only: bool = False,
                       max_workers: int = 10, timeout: int = 10,
                       max_links: int = DEFAULT_MAX_LINKS) -> dict:
    """
    Check the links on a page, up to `max_links` of them.

    Args:
        url: Page URL to check
        internal_only: Only check internal links
        max_workers: Concurrent request threads
        timeout: Per-request timeout in seconds
        max_links: Upper bound on links checked; 0 means no bound

    Returns:
        Dictionary with all link check results. `total_links` is what the page has,
        `checked` is what was actually requested, and `truncated` says whether the
        two differ — `summary.broken` counts only what was checked, so a capped run
        can understate and never overstate.
    """
    result = {
        "page_url": url,
        "total_links": 0,
        "checked": 0,
        "truncated": False,
        "broken": [],
        "redirected": [],
        "timeout": [],
        "unchecked": [],
        "healthy": 0,
        "summary": {},
        "issues": [],
        "error": None,
    }

    # Fetch page
    try:
        resp = safe_get(url, timeout=15, headers=HEADERS)
        if resp.status_code != 200:
            # The site answered, and not with the page. Not this script failing.
            result["error"] = f"Failed to fetch page: HTTP {resp.status_code}"
            result["error_kind"] = "unread"
            return result
        html = resp.text
    except requests.exceptions.RequestException as e:
        result["error"] = f"Failed to fetch page: {e}"
        result["error_kind"] = "unread"
        return result

    # Extract links
    links = extract_links(html, url)
    if internal_only:
        links = [link for link in links if link["is_internal"]]

    result["total_links"] = len(links)

    if not links:
        result["issues"].append("⚠️ No links found on page")
        return result

    if max_links and len(links) > max_links:
        # Internal links first: they are the ones this site can actually fix, and a
        # truncated check should spend its budget where the findings are actionable.
        links = sorted(links, key=lambda link: not link["is_internal"])[:max_links]
        result["truncated"] = True
        result["issues"].append(
            f"⚠️ Page has {result['total_links']} links; checked the first "
            f"{max_links} (internal first). Raise --max-links to check them all")

    # Check all links concurrently
    checked = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(check_link, link, timeout): link for link in links}
        for future in as_completed(futures):
            checked.append(future.result())

    result["checked"] = len(checked)

    for link in checked:
        status = link["status"]

        if link["error_kind"]:
            if link["error_kind"] == "timeout":
                result["timeout"].append(link)
            elif link["error_kind"] in DEAD_FETCH_ERROR_KINDS:
                result["broken"].append(link)
            else:
                result["unchecked"].append(link)
        elif status and status >= 400:
            result["broken"].append(link)
        elif link["redirect"]:
            result["redirected"].append(link)
        else:
            result["healthy"] += 1

    # Generate summary
    result["summary"] = {
        "total": result["total_links"],
        "healthy": result["healthy"],
        "broken": len(result["broken"]),
        "redirected": len(result["redirected"]),
        "broken_or_redirected": len(result["broken"]) + len(result["redirected"]),
        "timeout": len(result["timeout"]),
        "unchecked": len(result["unchecked"]),
    }
    # The other way an answer can rest on less than the whole input, and the one the
    # images half of this release closed on its own script: a link that answered
    # nothing was not read either. `broken_or_redirected: 0` over a set where some
    # target never replied is "none found among the ones that replied". Folded into
    # the same flag rather than a second one, because the runner asks a single
    # question — was this whole input read — and the two ways of failing it are not
    # different questions.
    if result["unchecked"] or result["timeout"]:
        result["truncated"] = True

    # Generate issues
    if result["broken"]:
        result["issues"].append(
            f"🔴 {len(result['broken'])} broken link(s) found"
        )
    if result["timeout"]:
        result["issues"].append(
            f"⚠️ {len(result['timeout'])} link(s) timed out"
        )
    if result["redirected"]:
        chains = [link for link in result["redirected"]
                  if link.get("redirect", {}).get("hops", 0) > 1]
        if chains:
            result["issues"].append(
                f"⚠️ {len(chains)} redirect chain(s) detected (>1 hop)"
            )

    return result


def links_from_inventory(inventory: dict) -> dict:
    """Every internal link in the crawl, with the status the crawl already saw.

    Same output shape as `check_broken_links`, so the item reading it does not have
    to know which path produced the answer — `scope` says which one did.
    """
    pages = inventory.get("pages") or {}
    inbound = site_crawl.inbound_map(inventory)
    result = {
        "page_url": inventory.get("site") or "",
        "scope": "internal",
        "total_links": inventory.get("summary", {}).get("unique_internal_targets", 0),
        "checked": 0,
        "truncated": bool(inventory.get("summary", {}).get("truncated")),
        "broken": [],
        "redirected": [],
        "timeout": [],
        "unchecked": [],
        "healthy": 0,
        "summary": {},
        "issues": [],
        "error": None,
        "fetch_error": inventory.get("fetch_error"),
    }

    def anchor_for(target: str) -> str:
        for source in inbound.get(target, []):
            if source.get("anchor"):
                return source["anchor"][:80]
        return "[no text]"

    for target in sorted(inbound):
        row = pages.get(target)
        entry = {"url": target, "anchor_text": anchor_for(target),
                 "is_internal": True, "status": None, "error": None,
                 "error_kind": None,
                 "redirect": None, "response_time_ms": None,
                 "linked_from": sorted({s["source"] for s in inbound[target]})}
        if row is None:
            # Beyond the crawl's depth or budget. Counted apart from healthy and
            # apart from broken: this run does not know, and `summary.broken` must
            # only ever hold what was actually checked.
            result["unchecked"].append(entry)
            continue
        result["checked"] += 1
        entry["status"] = row.get("status")
        entry["error"] = row.get("error")
        entry["error_kind"] = row.get("error_kind")
        if row.get("redirect_chain"):
            entry["redirect"] = {"from": target, "to": row.get("final_url"),
                                 "hops": len(row["redirect_chain"]),
                                 "codes": []}
        if row.get("robots_blocked"):
            result["unchecked"].append(entry)
            result["checked"] -= 1
        elif entry["error_kind"] in DEAD_FETCH_ERROR_KINDS:
            result["broken"].append(entry)
        elif entry["error_kind"]:
            result["unchecked"].append(entry)
            result["checked"] -= 1
        elif entry["error"]:
            # An inventory written before error_kind existed cannot prove what the
            # failure meant. Keep it out of both verdict directions.
            result["unchecked"].append(entry)
            result["checked"] -= 1
        elif (entry["status"] or 0) >= 400:
            result["broken"].append(entry)
        elif entry["redirect"]:
            result["redirected"].append(entry)
        else:
            result["healthy"] += 1

    result["summary"] = {
        "total": result["total_links"],
        "healthy": result["healthy"],
        "broken": len(result["broken"]),
        "redirected": len(result["redirected"]),
        "broken_or_redirected": len(result["broken"]) + len(result["redirected"]),
        "timeout": 0,
        "unchecked": len(result["unchecked"]),
    }
    # Same rule on the whole-site path: a link target the crawl never reached is a
    # target nobody looked at, and TE-168 is `high`.
    if result["unchecked"]:
        result["truncated"] = True
    if result["broken"]:
        result["issues"].append(f"🔴 {len(result['broken'])} broken internal link(s) "
                                f"found across {result['checked']} checked")
    if result["redirected"]:
        result["issues"].append(f"⚠️ {len(result['redirected'])} internal link(s) "
                                f"point at a URL that redirects")
    if result["unchecked"]:
        result["issues"].append(f"⚠️ {len(result['unchecked'])} internal link "
                                f"target(s) were not reached by the crawl and are "
                                f"not counted either way")
    return result


def main():
    parser = argparse.ArgumentParser(description="Check for broken links")
    parser.add_argument("url", help="Page URL to check")
    parser.add_argument("--inventory", default="",
                        help="crawl inventory from site_crawl.py: check the whole "
                             "site's internal links instead of one page's links")
    parser.add_argument("--json", "-j", action="store_true", help="Output as JSON")
    parser.add_argument("--internal-only", "-i", action="store_true",
                        help="Only check internal links")
    parser.add_argument("--workers", "-w", type=int, default=10,
                        help="Concurrent workers (default: 10)")
    parser.add_argument("--timeout", "-t", type=int, default=10,
                        help="Per-link timeout in seconds (default: 10)")
    parser.add_argument("--max-links", type=int, default=DEFAULT_MAX_LINKS,
                        help=f"Maximum links to check, internal first; 0 for no "
                             f"limit (default: {DEFAULT_MAX_LINKS})")

    args = parser.parse_args()
    if args.inventory:
        result = links_from_inventory(site_crawl.inventory_for(args.url,
                                                               args.inventory))
    else:
        result = check_broken_links(args.url, internal_only=args.internal_only,
                                    max_workers=args.workers, timeout=args.timeout,
                                    max_links=args.max_links)

    if args.json:
        print(json.dumps(result, indent=2))
        return

    if result["error"]:
        print(f"Error: {result['error']}")
        sys.exit(1)

    print(f"Broken Link Check — {result['page_url']}")
    print("=" * 50)
    s = result["summary"]
    print(f"Total: {s['total']} | ✅ Healthy: {s['healthy']} | "
          f"🔴 Broken: {s['broken']} | ↪️ Redirected: {s['redirected']} | "
          f"⏱️ Timeout: {s['timeout']}")

    if result["broken"]:
        print("\n🔴 Broken Links:")
        for link in result["broken"]:
            status = link["status"] or link["error"]
            loc = "internal" if link["is_internal"] else "external"
            print(f"  [{status}] ({loc}) {link['url']}")
            print(f"         anchor: \"{link['anchor_text']}\"")

    if result["redirected"]:
        chains = [link for link in result["redirected"]
                  if link.get("redirect", {}).get("hops", 0) > 1]
        if chains:
            print("\n⚠️ Redirect Chains (>1 hop):")
            for link in chains:
                r = link["redirect"]
                print(f"  {link['url']}")
                print(f"    → {r['to']} ({r['hops']} hops: {r['codes']})")

    if result["timeout"]:
        print("\n⏱️ Timed Out:")
        for link in result["timeout"]:
            print(f"  {link['url']}")

    if result["issues"]:
        print("\nIssues:")
        for issue in result["issues"]:
            print(f"  {issue}")


if __name__ == "__main__":
    main()
