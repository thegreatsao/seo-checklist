#!/usr/bin/env python3
"""
Parse and analyze robots.txt for SEO and AI crawler management.

Usage:
    python robots_checker.py https://example.com
    python robots_checker.py https://example.com --json
"""

try:
    from lib import python_floor  # noqa: F401
except ImportError:
    from scripts.lib import python_floor  # noqa: F401

import argparse
import json
import sys
from urllib.parse import urlparse

try:
    import requests
except ImportError:
    print("Error: requests library required. Install with: pip install requests")
    sys.exit(1)

try:
    from lib.safe_http import default_headers, safe_get
    from lib import robots_rules
    from lib.typed_credential import scheme_added
except ImportError:
    from scripts.lib.safe_http import default_headers, safe_get
    from scripts.lib import robots_rules
    from scripts.lib.typed_credential import scheme_added

try:
    from ai_crawler_policy_matrix import AI_CRAWLERS
    from seo_common import carries_content, read_as_url, unread_kind
except ImportError:
    from scripts.ai_crawler_policy_matrix import AI_CRAWLERS
    from scripts.seo_common import carries_content, read_as_url, unread_kind


# basis: standard — Google reads the first 500 KiB of a robots.txt and ignores the rest
#  ("How Google interprets the robots.txt specification").
GOOGLE_ROBOTS_MAX_BYTES = 500 * 1024

# Fields a robots.txt line may carry and still mean something to a crawler this audit
# cares about: RFC 9309's three, the sitemap extension, Bing's Crawl-delay and Yandex's
# Clean-param. `Host` was Yandex's and its robots.txt page no longer
# lists it (read 2026-10-22); held by `tests/test_closed_sets.py`.
# Anything else — `Noindex:`, which Google stopped honouring in 2019, is the usual one —
# is a line the site believes does something and does not.
KNOWN_ROBOTS_FIELDS = frozenset({"user-agent", "allow", "disallow", "sitemap",
                                 "crawl-delay", "clean-param"})


def correctness_problems(text: str, content_type: str,
                         paths: list[str] | None = None) -> list[str]:
    """What stops a served robots.txt from saying what its owner means, one line each.

    AR-151 *Provide a Correct robots.txt* asserted `status == 200` until 0.117.0, so a
    file answering 200 with `Disallow: /` for every crawler — or the site's HTML shell
    served at the path — was *correct*.

    `paths` are the site's crawled paths: the whole site is shut to Googlebot only when
    `/` and every one of them is (F15: `Disallow: /$` shuts the home page alone). With
    `paths` None they are unknown, and a disallowed `/` decides nothing here: the caller
    withholds the answer (`fetch_robots_txt`).
    """
    head = text.lstrip()[:200].lower()
    if "html" in (content_type or "").lower() or head.startswith(("<!doctype", "<html")):
        return ["the response is an HTML page, not a robots.txt file"]
    problems = []
    if len(text.encode("utf-8")) > GOOGLE_ROBOTS_MAX_BYTES:
        problems.append("larger than the 500 KiB Google reads; rules past it are ignored")
    in_group = False
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if ":" not in line:
            problems.append(f"line {number} is not a `field: value` line")
            continue
        field, value = (part.strip() for part in line.split(":", 1))
        field = field.lower()
        if field not in KNOWN_ROBOTS_FIELDS:
            problems.append(f"line {number}: `{field}` is not a directive crawlers read")
        elif field == "user-agent":
            in_group = True
            if not value:
                problems.append(f"line {number}: a user-agent line with no name "
                                "matches no crawler")
        elif field in ("allow", "disallow") and not in_group:
            problems.append(f"line {number}: a rule before any user-agent line is ignored")
        elif field == "sitemap" and not value.lower().startswith(("http://", "https://")):
            problems.append(f"line {number}: a sitemap must be an absolute URL")
    parsed = robots_rules.parse(text)
    if paths is not None and not any(
            robots_rules.allowed(parsed, "https://example.invalid" + path, "Googlebot")[0]
            for path in ["/", *paths]):
        problems.append("the whole site is disallowed for Googlebot")
    return problems


def crawled_paths(inventory: dict) -> list[str]:
    """Path and query of every URL the shared crawl read or robots.txt refused it.

    A robots.txt is about the paths a site has, and `/` is only one of them (AR-151,
    F15).
    """
    found = set()
    # A row's own URL, not its key: a key folds the trailing slash and the query, and
    # `Allow: /en/` matches `/en/` and not `/en` (F15 review round 1).
    urls = [row.get("url") or key for key, row in (inventory.get("pages") or {}).items()]
    for url in [*urls, *(inventory.get("robots_blocked") or {})]:
        split = urlparse(url)
        found.add((split.path or "/") + (f"?{split.query}" if split.query else ""))
    return sorted(found)


def fetch_robots_txt(url: str, timeout: int = 15, paths: list[str] | None = None) -> dict:
    """Fetch and parse robots.txt from a domain."""
    parsed = urlparse(url)
    if not parsed.scheme:
        url = scheme_added(url)
        parsed = urlparse(url)

    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"

    result = {
        "url": robots_url,
        "status": None,
        "raw": None,
        "user_agents": {},
        "sitemaps": [],
        "crawl_delays": {},
        "ai_crawler_status": {},
        "issues": [],
        "error": None,
    }

    try:
        resp = safe_get(robots_url, timeout=timeout, headers=default_headers())
        result["status"] = resp.status_code

        if resp.status_code == 404:
            result["correctness_problems"] = ["no robots.txt at this origin"]
            result["issues"].append("🔴 No robots.txt found — all crawlers allowed by default")
            # Still check AI crawlers
            for crawler in AI_CRAWLERS:
                result["ai_crawler_status"][crawler] = "allowed (no robots.txt)"
            return result

        if not carries_content(resp.status_code):
            # The site answered, and what it answered means robots.txt could not
            # be read. That is a fact about the site, not about this script.
            result["error"] = f"HTTP {resp.status_code}"
            result["error_kind"] = "unread"
            return result

        result["raw"] = resp.text
        result["correctness_problems"] = correctness_problems(
            resp.text, (resp.headers or {}).get("content-type", ""), paths)
        if paths is None and not robots_rules.allowed(
                robots_rules.parse(resp.text), "https://example.invalid/", "Googlebot")[0]:
            # `/` is shut and nothing says which other paths the site has: whether the
            # whole site is shut is unknown, so a clean answer is withheld (AR-151).
            result["truncated"] = True
            result["truncated_reason"] = (
                "robots.txt disallows / for Googlebot and the site's other paths were "
                "not read, so whether the whole site is shut is not decided")
        _parse_robots(resp.text, result)

    except requests.exceptions.RequestException as e:
        result["error"] = str(e)
        result["error_kind"] = unread_kind(e)

    return result


def _parse_robots(content: str, result: dict):
    """Parse robots.txt content into structured data."""
    parsed = robots_rules.parse(content)
    result["sitemaps"].extend(parsed["sitemaps"])
    token_rules: dict[str, dict[str, list[str]]] = {}
    for group in parsed["groups"]:
        allow = [value for directive, value in group["rules"]
                 if directive == "allow"]
        disallow = [value for directive, value in group["rules"]
                    if directive == "disallow" and value]
        for agent in group["lines"]:
            rules = result["user_agents"].setdefault(
                agent, {"allow": [], "disallow": []}
            )
            rules["allow"].extend(allow)
            rules["disallow"].extend(disallow)
            if group["crawl_delay"] is not None:
                result["crawl_delays"][agent] = group["crawl_delay"]
            token = robots_rules.product_token(agent)
            if token:
                combined = token_rules.setdefault(
                    token, {"allow": [], "disallow": []}
                )
                combined["allow"].extend(allow)
                combined["disallow"].extend(disallow)

    # Analyze AI crawler management
    managed_agents = set(token_rules)

    for crawler in AI_CRAWLERS:
        crawler_token = robots_rules.product_token(crawler)
        if crawler_token in managed_agents:
            rules = token_rules[crawler_token]
            if rules["disallow"] and "/" in rules["disallow"]:
                result["ai_crawler_status"][crawler] = "fully blocked"
            elif rules["disallow"]:
                result["ai_crawler_status"][crawler] = f"partially blocked ({len(rules['disallow'])} paths)"
            elif rules["allow"]:
                result["ai_crawler_status"][crawler] = "explicitly allowed"
            else:
                result["ai_crawler_status"][crawler] = "declared but no rules"
        else:
            # Check wildcard rules
            if "*" in managed_agents:
                wildcard = token_rules["*"]
                if wildcard["disallow"] and "/" in wildcard["disallow"]:
                    result["ai_crawler_status"][crawler] = "blocked by wildcard (*)"
                else:
                    result["ai_crawler_status"][crawler] = "not managed (inherits * rules)"
            else:
                result["ai_crawler_status"][crawler] = "not managed (allowed by default)"

    # Generate issues
    unmanaged = [c for c, s in result["ai_crawler_status"].items()
                 if "not managed" in s or "allowed by default" in s]
    if unmanaged:
        result["issues"].append(
            f"⚠️ {len(unmanaged)} AI crawlers not explicitly managed: {', '.join(unmanaged[:5])}"
        )

    if not result["sitemaps"]:
        result["issues"].append("⚠️ No Sitemap directive found in robots.txt")


def main():
    parser = argparse.ArgumentParser(description="Analyze robots.txt for SEO and AI crawlers")
    parser.add_argument("url", help="Website URL or domain")
    parser.add_argument("--inventory", default="",
                        help="crawl inventory from site_crawl.py: its paths are tested "
                             "for a site shut to Googlebot (AR-151)")
    parser.add_argument("--json", "-j", action="store_true", help="Output as JSON")

    args = parser.parse_args()
    args.url = read_as_url(args.url)
    paths, capped = None, ""
    if args.inventory:
        try:
            import site_crawl
        except ImportError:
            from scripts import site_crawl
        inventory = site_crawl.inventory_for(args.url, args.inventory)
        # An unread crawl leaves the site's paths unknown, and only the whole-site
        # question needs them: a 404, an HTML page or a bad line is a problem whatever
        # the crawl did (F15 review round 1).
        if not inventory.get("fetch_error"):
            paths = crawled_paths(inventory)
            if (inventory.get("summary") or {}).get("truncated"):
                capped = ("the crawl stopped at its page or depth cap, so the site has "
                          "paths whose rules were not tested")
    result = fetch_robots_txt(args.url, paths=paths)
    if capped and "correctness_problems" in result:
        result["truncated"] = True
        result["truncated_reason"] = "; ".join(filter(None, [
            result.get("truncated_reason"), capped]))

    if args.json:
        # Exclude raw content from JSON for brevity
        output = {k: v for k, v in result.items() if k != "raw"}
        print(json.dumps(output, indent=2))
        return

    if result["error"]:
        print(f"Error: {result['error']}")
        sys.exit(1)

    print(f"robots.txt Analysis — {result['url']}")
    print("=" * 50)
    print(f"Status: {result['status']}")

    if result["sitemaps"]:
        print(f"\nSitemaps ({len(result['sitemaps'])}):")
        for sm in result["sitemaps"]:
            print(f"  • {sm}")

    print(f"\nUser-Agents ({len(result['user_agents'])}):")
    for agent, rules in result["user_agents"].items():
        allow_count = len(rules["allow"])
        disallow_count = len(rules["disallow"])
        print(f"  {agent}: {disallow_count} disallow, {allow_count} allow")

    if result["crawl_delays"]:
        print("\nCrawl Delays:")
        for agent, delay in result["crawl_delays"].items():
            print(f"  {agent}: {delay}s")

    print("\nAI Crawler Management:")
    for crawler, status in result["ai_crawler_status"].items():
        icon = "✅" if "blocked" in status else "⚠️" if "not managed" in status else "ℹ️"
        print(f"  {icon} {crawler}: {status}")

    if result["issues"]:
        print(f"\nIssues ({len(result['issues'])}):")
        for issue in result["issues"]:
            print(f"  {issue}")


if __name__ == "__main__":
    from lib.utf8_streams import utf8_streams
    utf8_streams()
    from lib.typed_credential import credentials_beside_argv
    credentials_beside_argv()
    main()
