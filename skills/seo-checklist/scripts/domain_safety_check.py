#!/usr/bin/env python3
"""
Check domain safety and reputation: reachability, Safe Browsing, WHOIS age,
and the hosting IP.

Every sub-check reports its own `checked` flag and omits its verdict key when
it could not run. That is deliberate: the checklist runner turns a missing key
into NO_DATA, so an unconfigured API key can never be mistaken for "the domain
is clean".

Safe Browsing needs a free API key (Google Cloud console -> Safe Browsing API):
    export GOOGLE_SAFE_BROWSING_KEY=...

Usage:
    python domain_safety_check.py https://example.com
    python domain_safety_check.py https://example.com --json
"""

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

try:
    import requests
except ImportError:
    print("Error: requests library required. Install with: pip install requests")
    sys.exit(1)

try:
    from lib.safe_http import default_headers, loopback_only, safe_get
except ImportError:
    from scripts.lib.safe_http import default_headers, loopback_only, safe_get

# basis: inherited — three labels, present at import, and definitional rather than
#  calibratable: a whois lookup needs the registrable domain, and a multi-label public
#  suffix (.co.uk, .com.br) is the only case where that is three labels rather than two.
SECOND_LEVEL_LABELS = 3
# basis: inherited — 3 seconds to first byte, present at import. Well above anything a
#  Core Web Vitals band would allow, so this is a reachability smell rather than a
#  performance verdict; the performance items measure that properly.
SLOW_RESPONSE_MS = 3000
# basis: inherited — 90 days, present at import. A domain younger than a quarter is
#  reported as still accumulating trust, which is an SEO-folklore claim rather than
#  something measured here, and the finding is `low` for that reason.
YOUNG_DOMAIN_DAYS = 90

SB_ENDPOINT = "https://safebrowsing.googleapis.com/v4/threatMatches:find"
REDACTED = "<redacted>"
SB_THREAT_TYPES = ["MALWARE", "SOCIAL_ENGINEERING", "UNWANTED_SOFTWARE",
                   "POTENTIALLY_HARMFUL_APPLICATION"]
RE_CREATED = re.compile(
    r"(?:creation date|created(?:\s+on)?|registered(?:\s+on)?|domain_dateregistered)"
    r"\s*:?\s*(\d{4}-\d{2}-\d{2}|\d{2}[-/]\w{3}[-/]\d{4})", re.I)


def check_uptime(url: str, timeout: int) -> dict:
    out = {"checked": True, "reachable": False, "status": None,
           "response_ms": None, "error": None}
    start = time.time()
    try:
        resp = safe_get(url, timeout=timeout)
        out["status"] = resp.status_code
        out["response_ms"] = int((time.time() - start) * 1000)
        out["reachable"] = resp.status_code < 500
    except Exception as exc:
        out["error"] = str(exc)[:200]
    return out


def check_safe_browsing(url: str, api_key: str, timeout: int) -> dict:
    """Without a key the verdict keys are omitted entirely, so the checklist
    reports NO_DATA rather than a clean bill of health."""
    if not api_key:
        return {"checked": False,
                "error": "no API key (set GOOGLE_SAFE_BROWSING_KEY)"}
    body = {
        "client": {"clientId": "agentic-seo", "clientVersion": "1.0"},
        "threatInfo": {
            "threatTypes": SB_THREAT_TYPES,
            "platformTypes": ["ANY_PLATFORM"],
            "threatEntryTypes": ["URL"],
            "threatEntries": [{"url": url}],
        },
    }
    try:
        resp = requests.post(f"{SB_ENDPOINT}?key={api_key}", json=body,
                             headers=default_headers({"Content-Type": "application/json"}),
                             timeout=timeout)
    except requests.RequestException as exc:
        # requests includes the complete request URL in connection errors, including
        # its key query parameter. Nothing returned by this function may carry it.
        error = f"Safe Browsing unreachable: {exc}".replace(api_key, REDACTED)
        return {"checked": False, "error": error[:200]}

    if resp.status_code != 200:
        return {"checked": False,
                "error": f"Safe Browsing returned HTTP {resp.status_code}"}

    matches = resp.json().get("matches", [])
    threats = [{"type": m.get("threatType"), "platform": m.get("platformType")}
               for m in matches]
    return {"checked": True, "clean": not threats, "threats": threats, "error": None}


def registrable_domain(host: str) -> str:
    """Reduce a hostname to what a registry will actually answer for.

    Querying whois for `www.example.com` returns the TLD's own record instead
    of the domain's, which silently yields a 40-year-old "creation date".
    Multi-label public suffixes (.co.uk, .com.br) keep three labels."""
    labels = host.strip(".").split(".")
    if len(labels) <= 2:
        return host
    second_level = {"co", "com", "net", "org", "gov", "edu", "ac"}
    keep = (SECOND_LEVEL_LABELS
            if labels[-2] in second_level and len(labels) >= SECOND_LEVEL_LABELS
            else 2)
    return ".".join(labels[-keep:])


def check_whois(domain: str, timeout: int) -> dict:
    """Uses the system whois binary. Registries format dates inconsistently, so
    a parse failure reports checked=False rather than guessing an age."""
    out = {"checked": False, "created": None, "registrar": None, "error": None}
    # whois always asks a registry's server, so a loopback-only process never
    # starts it — the guard in `safe_http` cannot see a child binary, and a CI runner
    # with whois installed would otherwise query the registries about 127.0.0.1.
    if loopback_only():
        out["error"] = "whois not asked: this process is loopback-only (SEO_LOOPBACK_ONLY)"
        return out
    binary = shutil.which("whois")
    if not binary:
        out["error"] = "whois binary not available"
        return out
    queried = registrable_domain(domain)
    out["queried"] = queried
    try:
        # `close_fds=False` is what makes CPython choose `posix_spawn` over
        # `fork`+`exec`, and on macOS a forked child dies inside Apple's own atfork
        # handler before it execs — signal 11, no output. This is the only evidence
        # script that starts a child process, so it is the only one outside the runner
        # that has to say so.
        proc = subprocess.run([binary, queried], capture_output=True, text=True, encoding="utf-8",
                              timeout=timeout, close_fds=False)
    except (subprocess.TimeoutExpired, OSError) as exc:
        out["error"] = f"whois failed: {exc}"[:200]
        return out

    text = proc.stdout or ""
    raws = RE_CREATED.findall(text)
    if not raws:
        out["error"] = "creation date not found in whois output"
        return out

    # whois for a .com prints the registry's own TLD record (Creation Date
    # 1985-01-01) before the domain's, so the first match is routinely the
    # wrong one. Every candidate is parsed and the newest wins — a domain
    # cannot predate the zone it sits in.
    parsed = []
    for raw in raws:
        for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d/%b/%Y"):
            try:
                parsed.append(datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc))
                break
            except ValueError:
                continue
    if not parsed:
        out["error"] = f"unparsed creation date(s): {', '.join(raws[:3])}"
        return out
    created = max(parsed)

    reg = re.search(r"registrar:\s*(.+)", text, re.I)
    out.update(checked=True,
               created=created.date().isoformat(),
               age_days=(datetime.now(timezone.utc) - created).days,
               registrar=reg.group(1).strip()[:120] if reg else None)
    return out


def check_neighbors(domain: str) -> dict:
    """Resolves the hosting IP. Enumerating co-hosted domains needs a paid
    reverse-IP service, so `suspicious` is deliberately never fabricated —
    the checklist item stays NO_DATA until such a source is wired in."""
    out = {"checked": False, "ip": None, "error": None}
    try:
        out["ip"] = socket.gethostbyname(domain)
    except OSError as exc:
        out["error"] = f"DNS resolution failed: {exc}"[:160]
        return out
    out["error"] = ("reverse-IP lookup needs a third-party service; "
                    "co-hosted domains not enumerated")
    return out


def check(url: str, timeout: int = 20) -> dict:
    domain = urlparse(url).netloc.split(":")[0]
    api_key = (os.environ.get("GOOGLE_SAFE_BROWSING_KEY")
               or os.environ.get("SAFE_BROWSING_API_KEY") or "")

    result = {
        "url": url,
        "domain": domain,
        "uptime": check_uptime(url, timeout),
        "safe_browsing": check_safe_browsing(url, api_key, timeout),
        "whois": check_whois(domain, timeout),
        "neighbors": check_neighbors(domain),
        "issues": [],
    }

    up = result["uptime"]
    if not up["reachable"]:
        result["issues"].append({
            "severity": "critical",
            "message": f"Site not reachable: {up['error'] or 'HTTP ' + str(up['status'])}",
            "url": url,
        })
    elif up["response_ms"] and up["response_ms"] > SLOW_RESPONSE_MS:
        result["issues"].append({
            "severity": "medium",
            "message": f"Slow response: {up['response_ms']} ms",
            "url": url,
        })

    sb = result["safe_browsing"]
    if sb.get("checked") and sb.get("threats"):
        kinds = ", ".join(t["type"] for t in sb["threats"])
        result["issues"].append({
            "severity": "critical",
            "message": f"Google Safe Browsing flags this URL: {kinds}",
            "url": url,
        })
    elif not sb.get("checked"):
        result["issues"].append({
            "severity": "low",
            "message": f"Safe Browsing not checked — {sb.get('error')}",
            "url": url,
        })

    who = result["whois"]
    if who.get("checked") and who.get("age_days") is not None and who["age_days"] < YOUNG_DOMAIN_DAYS:
        result["issues"].append({
            "severity": "low",
            "message": f"Domain is only {who['age_days']} days old — expect slower "
                       f"trust accumulation",
            "url": url,
        })
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Check domain reachability, Safe Browsing status, and WHOIS age")
    parser.add_argument("url", help="URL to check")
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--json", "-j", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    result = check(args.url, args.timeout)

    if args.json:
        print(json.dumps(result, indent=2))
        return

    print(f"Domain safety for {result['domain']}")
    up = result["uptime"]
    print(f"  reachable:     {up['reachable']} (HTTP {up['status']}, {up['response_ms']} ms)")
    sb = result["safe_browsing"]
    state = "clean" if sb.get("clean") else (sb.get("error") or "THREATS FOUND")
    print(f"  safe browsing: {state}")
    who = result["whois"]
    print(f"  domain age:    {who.get('age_days', '?')} days"
          f" (created {who.get('created') or 'unknown'})")
    print(f"  hosting IP:    {result['neighbors'].get('ip') or 'unresolved'}")
    for i in result["issues"]:
        print(f"  [{i['severity']}] {i['message']}")


if __name__ == "__main__":
    main()
