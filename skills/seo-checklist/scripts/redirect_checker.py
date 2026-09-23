#!/usr/bin/env python3
"""
Check redirect chains for a URL.

Follows the full redirect chain, reports each hop (status + destination),
detects mixed HTTP/HTTPS, redirect loops, and chain length issues.

Usage:
    python redirect_checker.py https://example.com
    python redirect_checker.py https://example.com http://example.com --json
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
    from lib.safe_http import default_headers, safe_head
except ImportError:
    from scripts.lib.safe_http import default_headers, safe_head


HEADERS = default_headers()

# basis: standard — Google's crawlers follow up to 10 redirect hops by default ("HTTP
#  status codes, network and DNS errors", Google Search Central). A walk that reaches it
#  has gone as far as Googlebot will. It is a threshold and not a budget, because
#  `CI-014` asserts the result of this walk. Measured for 0.81.0: a
#  loop closing at hop 3 gives `has_loop True`; before this release the same loop closing
#  at hop 12 gave `has_loop False`, indistinguishable from a chain of twelve hops that
#  never loops, and the item passed. Raising it would move the line rather than remove it,
#  so the release changed the answer at the line instead of the number.
MAX_REDIRECT_HOPS = 10


def check_redirects(url: str, max_redirects: int = MAX_REDIRECT_HOPS,
                    timeout: int = 10) -> dict:
    """
    Follow and analyze the redirect chain for a URL.

    Args:
        url: URL to check
        max_redirects: Maximum redirects to follow
        timeout: Request timeout in seconds

    Returns:
        Dictionary with redirect chain analysis
    """
    parsed = urlparse(url)
    if not parsed.scheme:
        url = f"https://{url}"

    result = {
        "url": url,
        "final_url": None,
        "chain": [],
        "total_hops": 0,
        "total_time_ms": 0,
        "has_loop": False,
        "truncated": False,
        "has_mixed_protocol": False,
        "issues": [],
        "redirect_issues": [],
        "error": None,
    }

    seen = set()
    current = url

    try:
        for i in range(max_redirects + 1):
            if current in seen:
                result["has_loop"] = True
                result["issues"].append(f"🔴 Redirect loop detected at: {current}")
                result["redirect_issues"].append({
                    "severity": "error",
                    "type": "redirect_loop",
                    "message": f"Redirect loop detected at {current}",
                    "url": current,
                })
                break
            seen.add(current)

            resp = safe_head(current, timeout=timeout, headers=HEADERS,
                             allow_redirects=False)

            hop = {
                "step": i + 1,
                "url": current,
                "status": resp.status_code,
                "time_ms": round(resp.elapsed.total_seconds() * 1000),
            }

            if resp.status_code in (301, 302, 303, 307, 308):
                location = resp.headers.get("Location", "")
                if not location:
                    hop["error"] = "Redirect with no Location header"
                    result["chain"].append(hop)
                    result["issues"].append(f"🔴 Redirect at step {i+1} has no Location header")
                    result["redirect_issues"].append({
                        "severity": "error",
                        "type": "redirect_without_location",
                        "message": f"Redirect status {resp.status_code} has no Location header",
                        "url": current,
                    })
                    break

                # Resolve relative URLs
                if not urlparse(location).scheme:
                    from urllib.parse import urljoin
                    location = urljoin(current, location)

                hop["redirect_to"] = location
                hop["redirect_type"] = {
                    301: "permanent (301)",
                    302: "temporary (302)",
                    303: "see other (303)",
                    307: "temporary (307)",
                    308: "permanent (308)",
                }.get(resp.status_code, f"unknown ({resp.status_code})")

                result["chain"].append(hop)
                result["total_time_ms"] += hop["time_ms"]
                current = location
            else:
                # Final destination
                hop["final"] = True
                result["chain"].append(hop)
                result["final_url"] = current
                result["total_time_ms"] += hop["time_ms"]
                break
        else:
            # The walk ran out of hops; the chain did not end. Whether what comes
            # after it loops is unknown, and `has_loop: False` is the one answer this
            # must not give: CI-014 asserts it falsy, so "we stopped looking" would
            # read as "there is no loop" — a PASS on a chain nobody followed to its
            # end. Removed rather than set to None, because the runner turns an
            # absent path into NO_DATA and a null one into a pass: `not None` is True.
            result["truncated"] = True
            result.pop("has_loop", None)
            result["issues"].append(
                f"🔴 Too many redirects (>{max_redirects}) — the walk stopped before "
                f"the chain ended, so whether it loops is unknown"
            )
            result["redirect_issues"].append({
                "severity": "error",
                "type": "too_many_redirects",
                "message": (
                    f"The redirect walk reached the {max_redirects}-hop limit "
                    "documented for Googlebot"
                ),
                "url": current,
            })

    except requests.exceptions.RequestException as e:
        # The same withholding as at the cap, for the same reason: the walk stopped in
        # the middle and what follows it was never seen. No verdict rests on this line —
        # the runner replaces a result carrying `error` before any rule reads it, so
        # CI-014 is already NO_DATA here — but the artifact is read by people too, and
        # on its own it would say "no loop" about a chain nobody followed.
        result["error"] = str(e)
        result["error_kind"] = "unread"
        result["truncated"] = True
        result.pop("has_loop", None)
        # The runner replaces any result carrying `error` with NO_DATA, so a partial
        # issue list must not look like the walk completed and found its answer.
        result.pop("redirect_issues", None)

    result["total_hops"] = max(0, len(result["chain"]) - 1)

    # Check for mixed protocol
    protocols = set()
    for hop in result["chain"]:
        protocols.add(urlparse(hop["url"]).scheme)
    if "http" in protocols and "https" in protocols:
        result["has_mixed_protocol"] = True
        result["issues"].append("⚠️ Mixed HTTP/HTTPS in redirect chain")

    # Check chain length
    if result["total_hops"] > 2:
        result["issues"].append(
            f"🔴 Long redirect chain ({result['total_hops']} hops) — degrades crawl efficiency"
        )
    elif result["total_hops"] > 1:
        result["issues"].append(
            f"⚠️ Redirect chain has {result['total_hops']} hops — aim for max 1"
        )

    if ("redirect_issues" in result and result["total_hops"] > 1
            and not result.get("has_loop")):
        result["redirect_issues"].append({
            "severity": "warning",
            "type": "redirect_chain",
            "message": f"Redirect chain has {result['total_hops']} hops",
            "url": url,
        })

    # Google treats these temporary redirect codes as weak canonical signals. Preserve
    # the older human-readable 302 advice while giving CI-014 one structured issue per
    # temporary hop, including 303 and 307.
    for hop in result["chain"]:
        if "redirect_issues" in result and hop["status"] in (302, 303, 307):
            result["redirect_issues"].append({
                "severity": "warning",
                "type": "temporary_redirect",
                "message": (
                    f"Temporary redirect status {hop['status']} is a weak signal to Google"
                ),
                "url": hop["url"],
            })
        if hop["status"] == 302:
            result["issues"].append(
                f"⚠️ Temporary redirect (302) at step {hop['step']} — "
                f"use 301 for permanent moves to preserve link equity"
            )

    return result


def main():
    parser = argparse.ArgumentParser(description="Check redirect chains")
    parser.add_argument("urls", nargs="+", help="URL(s) to check")
    parser.add_argument("--json", "-j", action="store_true", help="Output as JSON")

    args = parser.parse_args()

    results = []
    for url in args.urls:
        results.append(check_redirects(url))

    if args.json:
        output = results if len(results) > 1 else results[0]
        print(json.dumps(output, indent=2))
        return

    for result in results:
        if result["error"]:
            print(f"Error checking {result['url']}: {result['error']}")
            continue

        print(f"Redirect Chain — {result['url']}")
        print("=" * 50)

        if not result["chain"]:
            print("  No response received")
            continue

        for hop in result["chain"]:
            status = hop["status"]
            time_ms = hop["time_ms"]

            if hop.get("final"):
                icon = "✅" if 200 <= status < 300 else "🔴"
                print(f"  {icon} [{status}] {hop['url']} ({time_ms}ms) — FINAL")
            else:
                redirect_type = hop.get("redirect_type", "")
                print(f"  ↪️ [{status}] {hop['url']} ({time_ms}ms)")
                print(f"       → {hop.get('redirect_to', '?')} ({redirect_type})")

        print(f"\nTotal hops: {result['total_hops']} | Total time: {result['total_time_ms']}ms")

        if result["issues"]:
            print("\nIssues:")
            for issue in result["issues"]:
                print(f"  {issue}")
        print()


if __name__ == "__main__":
    main()
