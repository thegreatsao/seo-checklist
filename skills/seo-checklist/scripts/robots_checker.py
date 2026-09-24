#!/usr/bin/env python3
"""
Parse and analyze robots.txt for SEO and AI crawler management.

Usage:
    python robots_checker.py https://example.com
    python robots_checker.py https://example.com --json
"""

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
except ImportError:
    from scripts.lib.safe_http import default_headers, safe_get
    from scripts.lib import robots_rules


# AI crawlers to check for explicit management
AI_CRAWLERS = [
    "GPTBot",
    "OAI-SearchBot",
    "ChatGPT-User",
    "OAI-AdsBot",
    "ClaudeBot",
    "PerplexityBot",
    "Google-Extended",
    "Applebot-Extended",
    "Bytespider",
    "CCBot",
    "anthropic-ai",
    "FacebookBot",
    "Amazonbot",
]

# Standard crawlers for reference
STANDARD_CRAWLERS = [
    "Googlebot",
    "Bingbot",
    "Yandex",
    "Baiduspider",
    "DuckDuckBot",
]


# basis: standard — Google reads the first 500 KiB of a robots.txt and ignores the rest
#  ("How Google interprets the robots.txt specification").
GOOGLE_ROBOTS_MAX_BYTES = 500 * 1024

# Fields a robots.txt line may carry and still mean something to a crawler this audit
# cares about: RFC 9309's three, the sitemap extension, and the ones Bing and Yandex read.
# Anything else — `Noindex:`, which Google stopped honouring in 2019, is the usual one —
# is a line the site believes does something and does not.
KNOWN_ROBOTS_FIELDS = frozenset({"user-agent", "allow", "disallow", "sitemap",
                                 "crawl-delay", "host", "clean-param"})


def correctness_problems(text: str, content_type: str) -> list[str]:
    """What stops a served robots.txt from saying what its owner means, one line each.

    AR-151 *Provide a Correct robots.txt* asserted `status == 200` until 0.117.0, so a
    file answering 200 with `Disallow: /` for every crawler — or the site's HTML shell
    served at the path — was *correct*.
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
        elif field in ("allow", "disallow") and not in_group:
            problems.append(f"line {number}: a rule before any user-agent line is ignored")
        elif field == "sitemap" and not value.lower().startswith(("http://", "https://")):
            problems.append(f"line {number}: a sitemap must be an absolute URL")
    parsed = robots_rules.parse(text)
    if not robots_rules.allowed(parsed, "https://example.invalid/", "Googlebot")[0]:
        problems.append("the whole site is disallowed for Googlebot")
    return problems


def fetch_robots_txt(url: str, timeout: int = 15) -> dict:
    """Fetch and parse robots.txt from a domain."""
    parsed = urlparse(url)
    if not parsed.scheme:
        url = f"https://{url}"
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

        if resp.status_code != 200:
            # The site answered, and what it answered means robots.txt could not
            # be read. That is a fact about the site, not about this script.
            result["error"] = f"HTTP {resp.status_code}"
            result["error_kind"] = "unread"
            return result

        result["raw"] = resp.text
        result["correctness_problems"] = correctness_problems(
            resp.text, (resp.headers or {}).get("content-type", ""))
        _parse_robots(resp.text, result)

    except requests.exceptions.RequestException as e:
        result["error"] = str(e)
        result["error_kind"] = "unread"

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
    parser.add_argument("--json", "-j", action="store_true", help="Output as JSON")

    args = parser.parse_args()
    result = fetch_robots_txt(args.url)

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
    main()
