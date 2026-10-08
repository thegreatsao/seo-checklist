#!/usr/bin/env python3
"""Identify critical request chains and render-blocking resources from HTML."""

from __future__ import annotations

import argparse
import json
import re
from urllib.parse import urlparse

from seo_common import (BeautifulSoup, fetch_url, html_parser, load_source,
                        normalize_url,
                        require_bs4,
                        same_host)


def _is_cross_origin(url: str, page_url: str) -> bool:
    if not url.startswith(("http://", "https://")) or not page_url.startswith(("http://", "https://")):
        return False
    return not same_host(url, page_url)


def _imports_from_css(css: str, base_url: str) -> list[str]:
    imports = []
    for match in re.finditer(r"""@import\s+(?:url\()?["']?([^"') ;]+)""", css or "", flags=re.I):
        imports.append(normalize_url(match.group(1), base_url) if base_url else match.group(1))
    return imports


def audit(source: str, fetch_css: bool = False, timeout: int = 15) -> dict:
    html, url, fetched = load_source(source, timeout=timeout)
    require_bs4()
    soup = BeautifulSoup(html or "", html_parser())
    preloads = set()
    preconnects = set()
    chains = []
    issues = []

    for link in soup.find_all("link", href=True):
        rel = " ".join(link.get("rel") or []).lower()
        href = normalize_url(link.get("href"), url) if url else link.get("href")
        if "preload" in rel or "modulepreload" in rel:
            preloads.add(href)
        if "preconnect" in rel or "dns-prefetch" in rel:
            preconnects.add(urlparse(href).netloc or href)

    for link in soup.find_all("link", href=True):
        rel = " ".join(link.get("rel") or []).lower()
        if "stylesheet" not in rel or link.get("media", "").lower() in ("print", "speech"):
            continue
        href = normalize_url(link.get("href"), url) if url else link.get("href")
        node = {
            "type": "stylesheet",
            "url": href,
            "blocking": True,
            "preloaded": href in preloads,
            "cross_origin": _is_cross_origin(href, url),
            "children": [],
        }
        if fetch_css and href.startswith(("http://", "https://")):
            fetched_css = fetch_url(href, timeout=timeout, max_bytes=500_000)
            for imported in _imports_from_css(fetched_css.get("text") or "", href):
                node["children"].append({"type": "css-import", "url": imported, "blocking": True})
        chains.append(node)
        # `info`, not `warning`, since 0.87.0. A `<link rel="stylesheet">` in the head
        # is how CSS is delivered on the web, and `warning` aliases to medium, which
        # SP-110 asserts against: every page here with an external stylesheet emitted
        # exactly this one issue and nothing else, so the item could report PASS only
        # on a page with no external CSS at all — two of the fifteen this repository
        # serves. 0.50.0 set the rule this line missed: a script grades as an error the
        # one finding that is a defect on every site, and the rest stay advice. The
        # parser-blocking script below is that finding; a stylesheet is not.
        issues.append({"severity": "info", "message": "Render-blocking stylesheet", "url": href})

    for script in soup.find_all("script", src=True):
        src = normalize_url(script.get("src"), url) if url else script.get("src")
        blocking = not script.has_attr("async") and not script.has_attr("defer") and script.get("type") != "module"
        # Where it sits decides what it costs, and until 0.50.0 this did not look.
        # A synchronous script in `<head>` stops the parser before anything has been
        # painted; the same tag before `</body>` blocks a parser that has already
        # emitted the page. Grading both the same left SP-110 with one severity for
        # two different defects — and it is the reason the item could not fail, since
        # `warning` is the only word the whole file had.
        in_head = any(parent.name == "head" for parent in script.parents)
        node = {
            "type": "script",
            "url": src,
            "blocking": blocking,
            "in_head": in_head,
            "preloaded": src in preloads,
            "cross_origin": _is_cross_origin(src, url),
            "children": [],
        }
        chains.append(node)
        if blocking and in_head:
            issues.append({"severity": "error",
                           "message": "Parser-blocking script in <head>",
                           "url": src})
        elif blocking:
            issues.append({"severity": "warning", "message": "Parser-blocking script",
                           "url": src})

    for node in chains:
        if node["cross_origin"]:
            host = urlparse(node["url"]).netloc
            has_preconnect = host in preconnects or f"https://{host}" in preconnects
            node["preconnected"] = has_preconnect
            if not has_preconnect:
                issues.append({"severity": "info", "message": "Cross-origin critical resource lacks preconnect", "url": node["url"]})

    return {
        "url": url or source,
        "critical_request_count": len([node for node in chains if node["blocking"]]),
        "chain_count": len(chains),
        "issues": issues,
        "chains": chains,
        "fetch_error": fetched.get("error"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Identify render-blocking critical request chains")
    parser.add_argument("source", help="URL or local HTML file")
    parser.add_argument("--fetch-css", action="store_true", help="Fetch CSS files to inspect @import chains")
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument("--json", "-j", action="store_true")
    args = parser.parse_args()

    result = audit(args.source, args.fetch_css, args.timeout)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Critical requests: {result['critical_request_count']}; chains: {result['chain_count']}; issues: {len(result['issues'])}")


if __name__ == "__main__":
    from lib.utf8_streams import utf8_streams
    utf8_streams()
    main()
