#!/usr/bin/env python3
"""
Validate a page against the W3C Nu HTML Checker.

Uses the free public validator.w3.org/nu endpoint — no API key. Invalid markup
degrades rendering, accessibility and parsing, which is why Plerdy's checklist
raises it in three separate places.

Usage:
    python html_validator.py https://example.com
    python html_validator.py https://example.com --rendered-json rendered.json
    python html_validator.py https://example.com --json
"""

import argparse
import json
import sys
import time
from urllib.parse import urlencode

try:
    import requests
except ImportError:
    print("Error: requests library required. Install with: pip install requests")
    sys.exit(1)

try:
    from lib.safe_http import (MAX_RETRY_AFTER_WAIT, default_headers, pace,
                               retry_after_seconds)
except ImportError:
    from scripts.lib.safe_http import (MAX_RETRY_AFTER_WAIT, default_headers, pace,
                                       retry_after_seconds)

NU_ENDPOINT = "https://validator.w3.org/nu/"
# basis: inherited — more than 10 validation warnings, present at import. Warnings are
#  advisory in Nu's own output, so this is a "the page has a pattern of them" line rather
#  than a count anybody calibrated.
MANY_WARNINGS = 10
# basis: inherited — 40, present at import. A cap on how much of Nu's answer is carried
#  forward, not a verdict: a page with more than 40 validation errors is already failing
#  the item
MAX_MESSAGES = 40


def rendered_document(path: str) -> tuple[str | None, str | None]:
    """The serialised DOM out of a rendered-page artifact, or why there is none.

    Deliberately read from an artifact rather than rendered here. A browser launched
    inside an audit fetches the page again — and its subresources — behind the shared
    response cache's back, which is exactly what the CI request-discipline gate
    forbids: one audited page, one fetch. Measured on the fixture site, rendering from
    inside the run took an audit from 22 requests to 31 and asked for the entry URL
    three times. The measurement belongs outside the run, like `cwv_metrics.py`'s
    trace; `SKILL.md` carries the snippet that writes one.
    """
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except OSError as exc:
        return None, f"rendered artifact could not be read: {exc}"
    except json.JSONDecodeError as exc:
        return None, f"rendered artifact is not JSON: {exc}"
    if not isinstance(payload, dict):
        return None, "rendered artifact is not an object"
    document = payload.get("html")
    if not isinstance(document, str) or not document.strip():
        return None, ("rendered artifact carries no `html`; the trace recorded "
                      "measurements but not the document")
    return document, None


def validate(url: str, timeout: int = 45, rendered_json: str | None = None) -> dict:
    rendered = rendered_json is not None
    result = {
        "url": url,
        "source": "rendered" if rendered else "served",
        # Empty until the validator answers. `{"errors": None}` is not silence:
        # `eq: 0` reads a None as a failing value, so an outage or a 429 from a free
        # service reported "your HTML has validation errors" — CI-017 and TE-181,
        # invented out of the validator being busy. An absent key is NO_DATA.
        "messages": [],
        "issues": [],
        "error": None,
        "render_error": None,
    }
    document = None
    if rendered:
        document, render_error = rendered_document(rendered_json)
        result["render_error"] = render_error
        if document is None:
            # No DOM means no validation result. In particular, do not add an empty
            # summary: summary.errors == 0 would turn a missing artifact into a PASS
            # for TE-181, claiming a rendered document was valid without one existing.
            result["error"] = f"no rendered document to validate: {render_error}"
            return result

    # Once there is a document for Nu to inspect, preserve the served-mode output
    # shape while it answers. Validator failures leave this empty and therefore
    # remain NO_DATA under the existing assertion semantics.
    result["summary"] = {}
    query = urlencode({"out": "json"} if rendered else {"doc": url, "out": "json"})
    headers = default_headers({"Accept": "application/json"})
    if rendered:
        headers["Content-Type"] = "text/html; charset=utf-8"

    def ask_nu():
        if rendered:
            return requests.post(f"{NU_ENDPOINT}?{query}",
                                 data=document.encode("utf-8"), headers=headers,
                                 timeout=timeout)
        return requests.get(f"{NU_ENDPOINT}?{query}", headers=headers, timeout=timeout)

    # This is the one script that calls requests directly rather than through
    # safe_request, because it addresses a fixed third-party endpoint rather than
    # the audited site. It still has to be paced: the W3C validator is a free
    # service. Served mode asks it to fetch the URL; rendered mode sends the DOM.
    try:
        pace("validator.w3.org")
        resp = ask_nu()
        wait = retry_after_seconds(resp)
        if 0 < wait <= MAX_RETRY_AFTER_WAIT:
            time.sleep(wait)
            pace("validator.w3.org")
            resp = ask_nu()
    except requests.RequestException as exc:
        # The validator is a service this check depends on. Whether it is unreachable,
        # answers with a status, answers with something that is not JSON, or declines
        # the page outright, the audited site is not what failed and neither is this
        # script.
        result["error"] = f"validator unreachable: {exc}"
        result["error_kind"] = "service"
        return result

    if resp.status_code != 200:
        result["error"] = f"validator returned HTTP {resp.status_code}"
        result["error_kind"] = "service"
        return result

    try:
        payload = resp.json()
    except ValueError:
        result["error"] = "validator returned non-JSON output"
        result["error_kind"] = "service"
        return result

    messages = payload.get("messages", [])
    # Nu answered, about nothing. `non-document-error` is how it reports that *it*
    # could not fetch or decode the URL — a 403 aimed at its user agent, a timeout, a
    # TLS problem, a host it cannot reach. None of those is a document error, so
    # `errors` came out 0 and CI-017 and TE-181 reported "your HTML validates" about a
    # page the validator never saw. The same shape as the outage guarded against
    # above, one step further in: the service answered, and the answer was not about
    # the page.
    blocked = [m for m in messages if m.get("type") == "non-document-error"]
    if blocked and len(blocked) == len(messages):
        detail = (blocked[0].get("message") or blocked[0].get("subType")
                  or "no detail given")
        result["error"] = f"validator could not read the page: {detail[:160]}"
        result["error_kind"] = "service"
        return result

    counts = {"error": 0, "warning": 0, "info": 0}
    for m in messages:
        kind = m.get("type", "info")
        # Nu reports fatal parse failures as type=error subType=fatal.
        bucket = "error" if kind == "error" else ("warning" if kind == "warning" else "info")
        counts[bucket] += 1
        if len(result["messages"]) < MAX_MESSAGES:
            result["messages"].append({
                "type": kind,
                "subType": m.get("subType", ""),
                "message": m.get("message", "")[:300],
                "line": m.get("lastLine"),
                "extract": (m.get("extract") or "").strip()[:160],
            })

    result["summary"] = {"errors": counts["error"], "warnings": counts["warning"],
                         "info": counts["info"]}

    if counts["error"]:
        first = next((m for m in result["messages"] if m["type"] == "error"), {})
        result["issues"].append({
            "severity": "medium",
            "message": f"{counts['error']} HTML validation error(s); first: "
                       f"{first.get('message', '')[:160]}",
            "url": url,
        })
    if counts["warning"] > MANY_WARNINGS:
        result["issues"].append({
            "severity": "low",
            "message": f"{counts['warning']} HTML validation warnings",
            "url": url,
        })
    return result


def main():
    parser = argparse.ArgumentParser(description="Validate HTML via the W3C Nu checker")
    parser.add_argument("url", help="URL to validate")
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument("--rendered-json",
                        help="Validate the DOM recorded in a rendered-page artifact "
                             "instead of the HTML the server sends")
    parser.add_argument("--json", "-j", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    result = validate(args.url, args.timeout, args.rendered_json)

    if args.json:
        print(json.dumps(result, indent=2))
        return

    if result["error"]:
        print(f"Could not validate: {result['error']}")
        return
    s = result["summary"]
    print(f"W3C validation for {result['url']}")
    print(f"  errors:   {s['errors']}")
    print(f"  warnings: {s['warnings']}")
    for m in result["messages"][:15]:
        line = f" (line {m['line']})" if m["line"] else ""
        print(f"  [{m['type']}]{line} {m['message'][:120]}")


if __name__ == "__main__":
    main()
