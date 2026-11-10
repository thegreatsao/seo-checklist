#!/usr/bin/env python3
"""
Detect Google Analytics 4 / Tag Manager installation and duplicate tagging.

Duplicate GA4 configuration is the failure this catches: the same measurement
ID configured twice (often once hardcoded and once via GTM) double-counts every
pageview, which silently corrupts every downstream traffic decision.

Usage:
    python ga4_tag_checker.py https://example.com
    python ga4_tag_checker.py https://example.com --json
"""

try:
    from lib import python_floor  # noqa: F401
except ImportError:
    from scripts.lib import python_floor  # noqa: F401

import argparse
import json
import re
import sys
from collections import Counter
from urllib.parse import urljoin

try:
    import requests  # noqa: F401  (kept for the shared dependency error contract)
except ImportError:
    print("Error: requests library required. Install with: pip install requests")
    sys.exit(1)

try:
    from lib.safe_http import safe_get
    from lib.typed_credential import read_as_url
except ImportError:
    from scripts.lib.safe_http import safe_get
    from scripts.lib.typed_credential import read_as_url

try:
    from seo_common import fetch_error_kind
except ImportError:
    from scripts.seo_common import fetch_error_kind

GUARD_REFUSED = "blocked"

# gtag('config', 'G-XXXX') and the gtag.js loader query string both carry the ID.
RE_CONFIG = re.compile(r"""gtag\s*\(\s*['"]config['"]\s*,\s*['"](G-[A-Z0-9]+)['"]""", re.I)
RE_GTAG_SRC = re.compile(r"gtag/js\?id=(G-[A-Z0-9]+)", re.I)
RE_LOADER_URL = re.compile(r"[^\"'\s<>]*")
RE_GTM = re.compile(r"(GTM-[A-Z0-9]+)", re.I)
RE_UA = re.compile(r"(UA-\d{4,}-\d+)")
RE_GTAG_LOADER = re.compile(r"gtag/js\?id=", re.I)
RE_GTM_LOADER = re.compile(r"gtm\.js\?id=|googletagmanager\.com/gtm\.js", re.I)
# A Google tag loaded by ID (GO-131's ruling, F15: "a gtag loader with an ID counts as
# installed"): a GA4 measurement ID or a Google tag ID (`GT-`), which can carry GA4.
RE_GOOGLE_TAG_SRC = re.compile(r"gtag/js\?(?:[^\"'\s<>]*&(?:amp;)?)?id=((?:G|GT)-[A-Z0-9]+)", re.I)
# Where a GTM container's script is fetched from: the loader's own URL when the page
# writes it out (a server-side container on the site's own host included), else Google's.
RE_GTM_SRC = re.compile(r"""((?:https?:)?//[^\s"'<>+]+?/gtm\.js|(?<=["'])/[^\s"'<>+]*?gtm\.js)\?id=""",
                        re.I)
GTM_DEFAULT = "https://www.googletagmanager.com/gtm.js"
RE_MEASUREMENT_ID = re.compile(r"\bG-[A-Z0-9]{4,}\b")
# The container tags that send a page view: the Google tag and the GA4 configuration
# tag. A GA4 event tag (`__gaawe`) sending to the hardcoded ID beside a hardcoded config
# is the ordinary correct setup, not a duplicate (review round 1 of F15 batch 6).
RE_PAGEVIEW_TAG = re.compile(r'"function"\s*:\s*"__(?:googtag|gaawc)"')

# A container ID as GTM writes one, case-sensitive: `RE_GTM` above also reads a
# `gtm-wrapper` class, and asking Google for container GTM-WRAPPER is a 404.
RE_CONTAINER_ID = re.compile(r"\bGTM-[A-Z0-9]{4,}\b")


def pageview_ids(container: str) -> set[str]:
    """The GA4 IDs a GTM container's page-view tags name.

    Read from the container's `resource` JSON when it parses, so a tag naming its ID
    through a variable (`"vtp_tagId": ["macro", 1]`, a Constant variable) is followed to
    the variable (review round 2); otherwise each such tag's own object is read."""
    found = re.search(r'"resource"\s*:\s*\{', container)
    if found:
        try:
            resource, _end = json.JSONDecoder().raw_decode(container, found.end() - 1)
        except ValueError:
            resource = None
        if isinstance(resource, dict):
            macros = resource.get("macros") or []

            def ids(value, seen=frozenset()) -> set[str]:
                if isinstance(value, str):
                    return {m for m in RE_MEASUREMENT_ID.findall(value.upper())}
                if (isinstance(value, list) and len(value) == 2 and value[0] == "macro"
                        and isinstance(value[1], int) and 0 <= value[1] < len(macros)
                        and value[1] not in seen):
                    return ids(macros[value[1]], seen | {value[1]})
                parts = (value.values() if isinstance(value, dict)
                         else value if isinstance(value, list) else ())
                return set().union(*(ids(part, seen) for part in parts))
            return set().union(*(ids(tag) for tag in resource.get("tags") or []
                                 if isinstance(tag, dict)
                                 and tag.get("function") in ("__googtag", "__gaawc")))
    pageview = set()
    for match in RE_PAGEVIEW_TAG.finditer(container):
        start = container.rfind("{", 0, match.start())
        depth, end = 0, start
        while end < len(container):
            depth += {"{": 1, "}": -1}.get(container[end], 0)
            end += 1
            if depth == 0:
                break
        pageview.update(m.upper() for m in RE_MEASUREMENT_ID.findall(container[start:end]))
    return pageview


def check(url: str, timeout: int = 15) -> dict:
    result = {
        "url": url,
        "measurement_ids": [],
        "gtm_containers": [],
        "ua_legacy": [],
        "loaders": {"gtag_js": 0, "gtm_js": 0},
        "issues": [],
        "fetch_error": None,
    }
    try:
        page = safe_get(url, timeout=timeout)
    except Exception as exc:
        result["fetch_error"] = str(exc)[:200]
        result["fetch_error_kind"] = fetch_error_kind(exc)
        return result
    if page.status_code >= 400:
        # An error page's tags are not the page's (F15 batch 6's aside).
        result["fetch_error"] = f"the page answered HTTP {page.status_code}"
        return result
    # A commented-out snippet never runs (review round 2: an old tag kept in a comment
    # beside GTM read as a duplicate).
    html = re.sub(r"<!--.*?-->", "", page.text, flags=re.S)

    config_ids = [m.upper() for m in RE_CONFIG.findall(html)]
    # A loader carrying `gtm=` was written by GTM itself, at run time, and saved into a
    # prerendered snapshot: the container's own tag, not a hardcoded one (review round 4).
    src_ids = [m.group(1).upper() for m in RE_GTAG_SRC.finditer(html)
               if "gtm=" not in RE_LOADER_URL.match(html, m.start()).group(0)]
    containers = [m.upper() for m in RE_GTM.findall(html)]
    ua_ids = RE_UA.findall(html)

    result["measurement_ids"] = sorted(set(config_ids) | set(src_ids))
    result["gtm_containers"] = sorted(set(containers))
    result["ua_legacy"] = sorted(set(ua_ids))
    result["loaders"] = {
        "gtag_js": len(RE_GTAG_LOADER.findall(html)),
        "gtm_js": len(RE_GTM_LOADER.findall(html)),
    }
    # GO-131's subject (F15, its ruling): a GA4 ID configured or loaded, a Google tag
    # loaded by its ID, or a GTM container the page loads — GA4 through GTM is GA4. A
    # container ID with no loader beside it is text, not an installation.
    loaded_containers = (sorted(set(RE_CONTAINER_ID.findall(html)))
                         if result["loaders"]["gtm_js"] else [])
    result["installed_by"] = sorted(set(result["measurement_ids"])
                                    | {m.upper() for m in RE_GOOGLE_TAG_SRC.findall(html)}
                                    | set(loaded_containers))

    # Written at the end, and only when decided (GO-132's `withheld_key`).
    duplicates = []
    # A measurement ID configured more than once double-counts pageviews.
    for gid, n in Counter(config_ids).items():
        if n > 1:
            duplicates.append({"id": gid, "count": n, "kind": "gtag_config"})
    # And one *loaded* more than once, which is the ordinary way GA4 ends up installed
    # twice over: a theme ships `gtag/js?id=` and a plugin ships it again, or somebody
    # adds it by hand beside GTM. Only `gtag('config', …)` calls were counted, so the
    # common case reported zero duplicates — and GO-132 "Prevent GA4 Tag Duplication"
    # reads this field, so the item passed the exact situation it exists to catch. The
    # script had already noticed, emitting a "gtag.js loaded 2x" issue further down;
    # the number the registry reads was the one that could not see it.
    for gid, n in Counter(src_ids).items():
        if n > 1 and Counter(config_ids)[gid] <= 1:
            duplicates.append({"id": gid, "count": n, "kind": "gtag_loader"})
    for cid, n in Counter(containers).items():
        if n > 2:  # GTM ships a <script> plus a <noscript> iframe by design.
            duplicates.append({"id": cid, "count": n, "kind": "gtm_container"})
    # A hardcoded tag beside a GTM container that fires the same ID (GO-132's ruling,
    # the case this docstring names). The container's script is read for the hardcoded
    # IDs; one that could not be read leaves `duplicates` unwritten unless another
    # duplicate already decides it, so the item is NO_DATA rather than a pass.
    unread = None
    hardcoded = set(result["measurement_ids"])
    if hardcoded and loaded_containers:
        found = RE_GTM_SRC.search(html)
        base = urljoin(page.url, found.group(1)) if found else GTM_DEFAULT
        for cid in loaded_containers:
            container_url = f"{base}?id={cid}"
            try:
                answer = safe_get(container_url, timeout=timeout)
            except Exception as exc:
                unread = (f"GTM container {cid} not read: {str(exc)[:160]}",
                          fetch_error_kind(exc))
                continue
            if answer.status_code >= 400:
                unread = (f"GTM container {cid} answered HTTP {answer.status_code}", None)
                continue
            fired = pageview_ids(answer.text)
            for gid in sorted(hardcoded & fired):
                duplicates.append({"id": gid, "count": 2,
                                             "kind": "gtm_and_hardcoded",
                                             "container": cid})
    if not unread or duplicates:
        result["duplicates"] = duplicates
    if unread and not duplicates:
        result["duplicates_unread"] = unread[0]
        if unread[1] == GUARD_REFUSED:
            result["withheld"] = {"duplicates": GUARD_REFUSED}

    if not result["measurement_ids"] and not result["gtm_containers"]:
        result["issues"].append({
            "severity": "medium",
            "message": "No GA4 measurement ID or GTM container found on the page",
            "url": url,
        })
    for d in duplicates:
        result["issues"].append({
            "severity": "high",
            "message": f"{d['id']} appears {d['count']}x ({d['kind']}) — pageviews will "
                       f"be double-counted",
            "url": url,
        })
    if len(result["measurement_ids"]) > 1:
        result["issues"].append({
            "severity": "low",
            "message": f"Multiple GA4 properties on one page: "
                       f"{', '.join(result['measurement_ids'])} — intentional only if you "
                       f"deliberately run parallel properties",
            "url": url,
        })
    if result["ua_legacy"]:
        result["issues"].append({
            "severity": "medium",
            "message": f"Legacy Universal Analytics tag(s) still present: "
                       f"{', '.join(result['ua_legacy'])} — UA stopped processing data "
                       f"in July 2023",
            "url": url,
        })
    if result["loaders"]["gtag_js"] > 1:
        result["issues"].append({
            "severity": "medium",
            "message": f"gtag.js loaded {result['loaders']['gtag_js']}x",
            "url": url,
        })
    return result


def main():
    parser = argparse.ArgumentParser(description="Check GA4 / GTM tagging for duplicates")
    parser.add_argument("url", help="URL to check")
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument("--json", "-j", action="store_true", help="Output as JSON")
    args = parser.parse_args()
    args.url = read_as_url(args.url)

    result = check(args.url, args.timeout)

    if args.json:
        print(json.dumps(result, indent=2))
        return

    if result["fetch_error"]:
        print(f"Could not fetch page: {result['fetch_error']}")
        return
    print(f"Analytics tagging for {result['url']}")
    print(f"  GA4 measurement IDs: {', '.join(result['measurement_ids']) or 'none'}")
    print(f"  GTM containers:      {', '.join(result['gtm_containers']) or 'none'}")
    if result["ua_legacy"]:
        print(f"  Legacy UA:           {', '.join(result['ua_legacy'])}")
    print(f"  Duplicates:          {len(result['duplicates']) if 'duplicates' in result else 'unread'}")
    for i in result["issues"]:
        print(f"  [{i['severity']}] {i['message']}")


if __name__ == "__main__":
    from lib.utf8_streams import utf8_streams
    utf8_streams()
    from lib.typed_credential import credentials_beside_argv
    credentials_beside_argv()
    main()
