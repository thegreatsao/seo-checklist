#!/usr/bin/env python3
"""
Check security headers relevant to SEO trust signals.

Validates HTTPS, HSTS, CSP, X-Frame-Options, X-Content-Type-Options,
Referrer-Policy, and Permissions-Policy.

Usage:
    python security_headers.py https://example.com
    python security_headers.py https://example.com --json
"""

import argparse
import ipaddress
import json
import re
import sys
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

try:
    import requests
except ImportError:
    print("Error: requests library required. Install with: pip install requests")
    sys.exit(1)

try:
    from lib.safe_http import default_headers, robots_allows, safe_get
    from redirect_checker import MAX_REDIRECT_HOPS
    import seo_common
    from seo_common import connection_refused, html_parser
except ImportError:
    from scripts.lib.safe_http import default_headers, robots_allows, safe_get
    from scripts.redirect_checker import MAX_REDIRECT_HOPS
    from scripts import seo_common
    from scripts.seo_common import connection_refused, html_parser


# Google Search Central, "HTTP status codes, network and DNS errors": 301 and 308 are
# "a strong signal that the redirect target should be processed", 302, 303 and 307 "a
# weak signal". Its "Redirects and Google Search" goes further for the temporary codes:
# the indexing pipeline "doesn't use the redirect as a signal that the redirect target
# should be canonical" — so a temporary redirect forces HTTPS for visitors and settles
# no canonical protocol, which is why SE-117 warns on it rather than passing.
PERMANENT_REDIRECTS = (301, 308)
TEMPORARY_REDIRECTS = (302, 303, 307)
# Worst first: the order `summarize_http_to_https` reads.
HTTP_TO_HTTPS_OUTCOMES = ("not_redirected", "temporary", "not_listening", "permanent")
# basis: convention — the audited page plus three same-site pages it links to is the
#  sample SE-117 reads for "Across the Site": enough to catch a redirect rule written
#  for one path, few enough that an audit adds at most four plain-HTTP requests. The
#  item's `measures` line says the rest of the site is not requested.
HTTP_SAMPLE_PAGES = 3
# Worst first; TE-175's value_map names exactly these.
PAGE_SECURITY_STATES = ("plain_http", "blocked_content", "upgraded_content", "secure")


# basis: inherited — per-header weights present at import, summing to a 0-100 score. The
#  weights are one project's opinion about which header matters most, and the registry
#  reads the score
SECURITY_HEADERS = {
    "strict-transport-security": {
        "label": "HSTS (Strict-Transport-Security)",
        "weight": 20,
        "description": "Forces browsers to use HTTPS. Prevents downgrade attacks.",
        "recommendation": 'Add header: Strict-Transport-Security: max-age=31536000; includeSubDomains',
    },
    "content-security-policy": {
        "label": "Content-Security-Policy (CSP)",
        "weight": 15,
        "description": "Prevents XSS, clickjacking, and code injection.",
        "recommendation": "Add a Content-Security-Policy header restricting script/style sources.",
    },
    "x-frame-options": {
        "label": "X-Frame-Options",
        "weight": 10,
        "description": "Prevents clickjacking by controlling iframe embedding.",
        "recommendation": "Add header: X-Frame-Options: SAMEORIGIN",
    },
    "x-content-type-options": {
        "label": "X-Content-Type-Options",
        "weight": 10,
        "description": "Prevents MIME-type sniffing.",
        "recommendation": "Add header: X-Content-Type-Options: nosniff",
    },
    "referrer-policy": {
        "label": "Referrer-Policy",
        "weight": 10,
        "description": "Controls how much referrer info is shared.",
        "recommendation": "Add header: Referrer-Policy: strict-origin-when-cross-origin",
    },
    "permissions-policy": {
        "label": "Permissions-Policy",
        "weight": 10,
        "description": "Controls browser feature access (camera, microphone, geolocation).",
        "recommendation": "Add header: Permissions-Policy: camera=(), microphone=(), geolocation=()",
    },
}


# basis: standard — one year of HSTS `max-age`, the minimum hstspreload.org requires
#  for inclusion in the browsers' preload list. Not this project's number and checkable
#  against a published requirement, which is what separates it from the rest here.
HSTS_MIN_MAX_AGE = 31_536_000
# basis: inherited — more than three of the tracked headers absent, present at import.
#  A count over a weighted set, so it double-counts what SECURITY_HEADERS already
#  scores; kept because the finding it raises is about breadth rather than score.
MANY_MISSING_HEADERS = 3


def http_form(url: str) -> str:
    """Return the plain-HTTP form of ``url`` without its fragment."""
    parsed = urlparse(url)
    if parsed.scheme.lower() == "http":
        return url
    hostname = parsed.hostname or ""
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    userinfo = ""
    if "@" in parsed.netloc:
        userinfo = parsed.netloc.rsplit("@", 1)[0] + "@"
    port = parsed.port
    if port not in (None, 443):
        hostname = f"{hostname}:{port}"
    return parsed._replace(scheme="http", netloc=userinfo + hostname,
                           fragment="").geturl()


def walk_http_to_https(url: str, timeout: int = 15) -> dict:
    """Read a bounded plain-HTTP redirect chain, stopping before HTTPS."""
    result = {"url": url, "outcome": "not_redirected", "hops": [], "error": None}
    current = url
    visited = {current}
    for request_number in range(MAX_REDIRECT_HOPS + 1):
        try:
            resp = safe_get(current, timeout=timeout, headers=default_headers(),
                            allow_redirects=False, stream=True)
        except requests.exceptions.RequestException as exc:
            if request_number == 0 and connection_refused(exc):
                result["outcome"] = "not_listening"
            else:
                result["outcome"] = "unread"
                result["error"] = str(exc)
            return result

        try:
            status = resp.status_code
            location = resp.headers.get("Location")
            result["hops"].append({"url": current, "status": status,
                                   "location": location})
        finally:
            resp.close()

        if status not in PERMANENT_REDIRECTS + TEMPORARY_REDIRECTS or not location:
            return result
        target = urljoin(current, location)
        scheme = urlparse(target).scheme.lower()
        if scheme == "https":
            statuses = [hop["status"] for hop in result["hops"]]
            result["outcome"] = ("permanent"
                                 if all(code in PERMANENT_REDIRECTS
                                        for code in statuses)
                                 else "temporary")
            return result
        if scheme != "http" or target in visited:
            return result
        visited.add(target)
        current = target
    return result


def summarize_http_to_https(outcomes) -> str | None:
    """Return the worst decided plain-HTTP outcome, or ``None`` when withheld."""
    if "not_redirected" in outcomes:
        return "not_redirected"
    if "unread" in outcomes:
        return None
    for outcome in HTTP_TO_HTTPS_OUTCOMES:
        if outcome in outcomes:
            return outcome
    return None


def mixed_content(html: str, final_url: str) -> list[dict]:
    """Return plain-HTTP subresources requested by an HTTPS document."""
    if urlparse(final_url).scheme.lower() != "https":
        return []

    soup = BeautifulSoup(html, html_parser())
    found = []
    for element in soup.find_all(True):
        tag = element.name.lower()
        loads = []
        if tag == "script" and element.has_attr("src"):
            loads.append(("src", element["src"], "blockable"))
        elif tag == "link" and element.has_attr("href"):
            rel = element.get("rel") or []
            if isinstance(rel, str):
                rel = rel.split()
            if any(token.lower() == "stylesheet" for token in rel):
                loads.append(("href", element["href"], "blockable"))
        elif tag == "iframe" and element.has_attr("src"):
            loads.append(("src", element["src"], "blockable"))
        elif tag == "object" and element.has_attr("data"):
            loads.append(("data", element["data"], "blockable"))

        if tag in ("img", "source") and element.has_attr("srcset"):
            for candidate in seo_common.srcset_urls(element["srcset"], final_url):
                loads.append(("srcset", candidate, "blockable"))

        if tag in ("img", "audio", "video", "source") and element.has_attr("src"):
            loads.append(("src", element["src"], "upgradable"))

        for attribute, value, kind in loads:
            resolved = urljoin(final_url, value)
            parsed = urlparse(resolved)
            if parsed.scheme.lower() != "http":
                continue
            if kind == "upgradable":
                try:
                    ipaddress.ip_address(parsed.hostname or "")
                except ValueError:
                    pass
                else:
                    kind = "blockable"
            found.append({"url": resolved, "tag": tag, "attribute": attribute,
                          "kind": kind})
    return found


def summarize_page_security(final_url, mixed) -> str:
    """Summarize the page and its mixed subresources, worst first."""
    if urlparse(final_url).scheme.lower() != "https":
        return "plain_http"
    if any(entry["kind"] == "blockable" for entry in mixed):
        return "blocked_content"
    if mixed:
        return "upgraded_content"
    return "secure"


def _history_http_to_https(resp) -> dict:
    """Build the already-walked HTTP variant from a followed response history."""
    hops = []
    for previous in resp.history:
        location = previous.headers.get("Location")
        hops.append({"url": previous.url, "status": previous.status_code,
                     "location": location})
        if location and urlparse(urljoin(previous.url, location)).scheme.lower() == "https":
            break
    outcome = ("permanent"
               if hops and all(hop["status"] in PERMANENT_REDIRECTS for hop in hops)
               else "temporary")
    return {"url": hops[0]["url"] if hops else http_form(resp.url),
            "outcome": outcome, "hops": hops, "error": None}


def check_security_headers(url: str, timeout: int = 15) -> dict:
    """
    Check security headers for a URL.

    Args:
        url: URL to check
        timeout: Request timeout in seconds

    Returns:
        Dictionary with security header analysis
    """
    parsed = urlparse(url)
    if not parsed.scheme:
        url = f"https://{url}"
        parsed = urlparse(url)

    result = {
        "url": url,
        "score": 0,
        "https": False,
        "headers_present": {},
        "headers_missing": {},
        "header_values": {},
        "hsts_enabled": False,
        "hsts_disabled_reason": None,
        "hardening_missing": [],
        "http_variants": [],
        "mixed_content": [],
        "issues": [],
        "recommendations": [],
        "error": None,
    }

    try:
        resp = safe_get(url, timeout=timeout, headers=default_headers(), allow_redirects=True)

        # Check HTTPS
        if resp.url.startswith("https://"):
            result["https"] = True
            result["score"] += 25
        else:
            result["issues"].append("🔴 Site not using HTTPS — critical for SEO and trust")
            result["recommendations"].append("Migrate to HTTPS and set up 301 redirects from HTTP")

        # Check each security header
        response_headers = {k.lower(): v for k, v in resp.headers.items()}
        hsts_value = response_headers.get("strict-transport-security")
        if hsts_value:
            if not result["https"]:
                result["hsts_disabled_reason"] = (
                    "Strict-Transport-Security is ignored when delivered over HTTP"
                )
            else:
                match = re.search(r"(?:^|;)\s*max-age\s*=\s*([^;\s]+)",
                                  hsts_value, re.I)
                if not match:
                    result["hsts_disabled_reason"] = "HSTS has no max-age directive"
                else:
                    try:
                        # RFC 6797 section 6.1 lets a directive value be a
                        # quoted-string: `max-age="31536000"` is as valid as the bare form.
                        max_age = int(match.group(1).strip('"'))
                    except ValueError:
                        result["hsts_disabled_reason"] = "HSTS max-age is not an integer"
                    else:
                        if max_age > 0:
                            result["hsts_enabled"] = True
                        else:
                            result["hsts_disabled_reason"] = (
                                "HSTS max-age must be greater than zero"
                            )

        hardening_headers = {
            "content-security-policy", "permissions-policy", "referrer-policy"
        }
        result["hardening_missing"] = sorted(hardening_headers - response_headers.keys())

        for header_key, header_info in SECURITY_HEADERS.items():
            if header_key in response_headers:
                value = response_headers[header_key]
                result["headers_present"][header_info["label"]] = value
                result["header_values"][header_key] = value
                result["score"] += header_info["weight"]

                # Validate HSTS specifics
                if header_key == "strict-transport-security":
                    if "max-age=" in value.lower():
                        try:
                            max_age = int(value.lower().split("max-age=")[1].split(";")[0].strip())
                            if max_age < HSTS_MIN_MAX_AGE:
                                result["issues"].append(
                                    f"⚠️ HSTS max-age is {max_age}s — recommend at least 31536000 (1 year)"
                                )
                        except (ValueError, IndexError):
                            pass
                    if "includesubdomains" not in value.lower():
                        result["issues"].append("⚠️ HSTS missing includeSubDomains directive")
            else:
                # A response was received, so an absent header is measured absence,
                # not missing evidence. Keep every tracked path present: registry
                # assertions such as SE-115's `truthy` can then fail normally while
                # an actual fetch error remains distinguishable through `error`.
                result["header_values"][header_key] = ""
                result["headers_missing"][header_info["label"]] = header_info["description"]
                result["recommendations"].append(
                    f"{header_info['label']}: {header_info['recommendation']}"
                )

        # Cap score at 100
        result["score"] = min(result["score"], 100)

        # Summary issues
        missing_count = len(result["headers_missing"])
        if missing_count > MANY_MISSING_HEADERS:
            result["issues"].append(f"🔴 {missing_count} security headers missing — poor security posture")
        elif missing_count > 0:
            result["issues"].append(f"⚠️ {missing_count} security header(s) missing")

        content_type = response_headers.get("content-type", "").split(";", 1)[0].lower()
        if (content_type in ("text/html", "application/xhtml+xml")
                and urlparse(resp.url).scheme.lower() == "https"):
            result["mixed_content"] = mixed_content(resp.text, resp.url)
        result["page_security"] = summarize_page_security(
            resp.url, result["mixed_content"])
        for entry in result["mixed_content"]:
            if entry["kind"] == "blockable":
                result["issues"].append(
                    f"🔴 Blocked mixed content: {entry['tag']} {entry['url']}"
                )
            else:
                result["issues"].append(
                    f"⚠️ Mixed content a browser upgrades: "
                    f"{entry['tag']} {entry['url']}"
                )

        final = resp.url
        variants = result["http_variants"]
        if final.lower().startswith("http://"):
            variants.append({"url": final, "page": url,
                             "outcome": "not_redirected", "hops": [],
                             "error": None})
        elif (urlparse(url).scheme.lower() == "http"
              and final.lower().startswith("https://")):
            variant = _history_http_to_https(resp)
            variant["page"] = url
            variants.append(variant)
        else:
            variant = walk_http_to_https(http_form(url), timeout)
            variant["page"] = url
            variants.append(variant)

        if (not any(variant["outcome"] == "not_redirected" for variant in variants)
                and content_type in ("text/html", "application/xhtml+xml")):
            soup = BeautifulSoup(resp.text, html_parser())
            final_page = urlparse(final)._replace(fragment="").geturl()
            final_netloc = urlparse(final).netloc.lower()
            seen_pages = {final_page}
            walked = 0
            for anchor in soup.find_all("a", href=True):
                candidate = urlparse(urljoin(final, anchor["href"]))
                candidate = candidate._replace(fragment="").geturl()
                parsed_candidate = urlparse(candidate)
                if (parsed_candidate.scheme.lower() != "https"
                        or parsed_candidate.netloc.lower() != final_netloc
                        or candidate in seen_pages):
                    continue
                seen_pages.add(candidate)
                if not robots_allows(candidate)[0]:
                    continue
                variant = walk_http_to_https(http_form(candidate), timeout)
                variant["page"] = candidate
                variants.append(variant)
                walked += 1
                if variant["outcome"] == "not_redirected" or walked >= HTTP_SAMPLE_PAGES:
                    break

        summary = summarize_http_to_https([variant["outcome"] for variant in variants])
        if summary is not None:
            result["http_to_https"] = summary

        recommend_redirect = False
        for variant in variants:
            if variant["outcome"] == "not_redirected":
                result["issues"].append(
                    f"🔴 http:// address answers without redirecting to HTTPS: "
                    f"{variant['url']}"
                )
                recommend_redirect = True
            elif variant["outcome"] == "temporary":
                status = next((hop["status"] for hop in variant["hops"]
                               if hop["status"] in TEMPORARY_REDIRECTS),
                              variant["hops"][0]["status"])
                result["issues"].append(
                    f"⚠️ http:// address redirects to HTTPS with a temporary "
                    f"{status}: {variant['url']}"
                )
        if recommend_redirect:
            result["recommendations"].append(
                "Redirect every http:// URL to its https:// form with a 301"
            )

    except requests.exceptions.RequestException as e:
        result["error"] = str(e)
        result["error_kind"] = "unread"

    return result


def main():
    parser = argparse.ArgumentParser(description="Check security headers for SEO")
    parser.add_argument("url", help="URL to check")
    parser.add_argument("--json", "-j", action="store_true", help="Output as JSON")

    args = parser.parse_args()
    result = check_security_headers(args.url)

    if args.json:
        print(json.dumps(result, indent=2))
        return

    if result["error"]:
        print(f"Error: {result['error']}")
        sys.exit(1)

    print(f"Security Headers — {result['url']}")
    print("=" * 50)

    # HTTPS status
    https_icon = "✅" if result["https"] else "🔴"
    print(f"{https_icon} HTTPS: {'Yes' if result['https'] else 'No'}")
    print(f"HTTP → HTTPS: {result.get('http_to_https') or 'unknown'}")
    print(f"Page security: {result['page_security']}")
    print(f"Security Score: {result['score']}/100")

    if result["headers_present"]:
        print(f"\n✅ Present ({len(result['headers_present'])}):")
        for header, value in result["headers_present"].items():
            print(f"  {header}: {value[:80]}")

    if result["headers_missing"]:
        print(f"\n❌ Missing ({len(result['headers_missing'])}):")
        for header, desc in result["headers_missing"].items():
            print(f"  {header}")
            print(f"    → {desc}")

    if result["issues"]:
        print("\nIssues:")
        for issue in result["issues"]:
            print(f"  {issue}")

    if result["recommendations"]:
        print("\nRecommendations:")
        for rec in result["recommendations"][:5]:
            print(f"  💡 {rec}")


if __name__ == "__main__":
    main()
