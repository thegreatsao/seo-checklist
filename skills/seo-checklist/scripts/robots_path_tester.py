#!/usr/bin/env python3
"""Test URL paths against robots.txt for multiple crawlers.

`--probe` additionally fetches each path robots permits, because "robots.txt does not
disallow it" and "it is an indexable page" are different claims and CI-019 needs the
second one. See `probe_url` for why that distinction was worth a request.

`--discover-assets` reads same-origin stylesheet, script and image references from
the audited page so CI-013 tests real rendering resources rather than invented paths.
"""

from __future__ import annotations

import argparse
import json
import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from seo_common import carries_content, fetch_robots, html_parser, normalize_url, robots_allowed

try:
    from lib.safe_http import default_headers, safe_get
except ImportError:
    from scripts.lib.safe_http import default_headers, safe_get


DEFAULT_AGENTS = ["Googlebot", "Bingbot", "GPTBot", "OAI-SearchBot", "ChatGPT-User", "OAI-AdsBot", "ClaudeBot", "PerplexityBot", "Google-Extended", "Applebot-Extended", "CCBot"]

# basis: standard — the two places a crawler is told not to index a page it has been
# allowed to fetch. `<meta name="robots">` per RFC 9309's surrounding practice and the
# `X-Robots-Tag` header, which applies the same directives to non-HTML responses.
_META_ROBOTS = re.compile(
    r"""<meta\s[^>]*name\s*=\s*["']?robots["']?[^>]*>""", re.I)
_NOINDEX = re.compile(r"\bnone\b|\bnoindex\b", re.I)
# Markup inside a comment is not markup. The first version of this function read
# `noindex` off a `<meta name="robots">` written in the comment block of a fixture page
# explaining that the page deliberately has no such tag — and passed the item it was
# built to fail. Same shape as the keyword items firing on their own remediation text
# in 0.5.0, and as the soft-404 guard's warning that `404` appears in the title of
# every article ever written about broken links.
_COMMENT = re.compile(r"<!--.*?-->", re.S)


def _origin(url: str) -> tuple[str, str, int | None]:
    parsed = urlsplit(url)
    try:
        port = parsed.port
    except ValueError:
        port = None
    if port is None:
        port = 443 if parsed.scheme.lower() == "https" else 80 if parsed.scheme.lower() == "http" else None
    return parsed.scheme.lower(), (parsed.hostname or "").lower(), port


def discover_asset_paths(site: str, timeout: int = 15) -> tuple[list[str], str | None]:
    """Return same-origin stylesheet, script and image paths referenced by the page.

    Same origin means the resolved asset has the page response's scheme, hostname
    and effective port. A CDN or even the same hostname on another scheme/port has
    its own robots.txt and is outside this site's policy.
    """
    try:
        response = safe_get(site, timeout=timeout, headers=default_headers(),
                            allow_redirects=True)
    except Exception as exc:
        return [], f"{type(exc).__name__}: {exc}"
    if response is None:
        return [], "no response"
    status = getattr(response, "status_code", None)
    if status is None or status >= 400:
        return [], f"status {status}"

    page_url = getattr(response, "url", None) or normalize_url(site)
    page_origin = _origin(page_url)
    soup = BeautifulSoup(getattr(response, "text", "") or "", html_parser())
    references = []
    for tag in soup.find_all("link", href=True):
        if "stylesheet" in [str(value).lower() for value in (tag.get("rel") or [])]:
            references.append(tag["href"])
    references.extend(tag["src"] for tag in soup.find_all("script", src=True))
    for tag in soup.find_all("img"):
        if tag.get("src"):
            references.append(tag["src"])
        if tag.get("srcset"):
            references.extend(part.strip().split()[0]
                              for part in tag["srcset"].split(",") if part.strip())
    for tag in soup.find_all("source"):
        if tag.find_parent("picture") and tag.get("srcset"):
            references.extend(part.strip().split()[0]
                              for part in tag["srcset"].split(",") if part.strip())

    paths = set()
    for reference in references:
        resolved = urlsplit(urljoin(page_url, reference))
        if resolved.scheme not in ("http", "https") or _origin(resolved.geturl()) != page_origin:
            continue
        path = resolved.path or "/"
        if resolved.query:
            path += "?" + resolved.query
        paths.add(path)
    return sorted(paths), None


def probe_url(url: str, timeout: int = 15) -> dict:
    """Does this URL exist, and if so is it kept out of the index?

    CI-019 asks whether a site exposes `/search`, `/cart`, `/checkout`, `/login` to an
    index. Reading robots.txt alone cannot answer that: a café with no cart at all has
    nothing disallowing `/cart`, so the path counts as permitted and the site is
    accused over a page it does not have. That is not a hypothetical — it is how this
    item failed a real audit, and the fixture could not catch it because the fixture's
    robots.txt was written to satisfy the assertion.

    A 404 or 410 means there is no page to keep out. A `noindex`, in the meta tag or
    the `X-Robots-Tag` header, means the page exists and is already handled — by the
    mechanism this item's own title names.
    """
    out = {"probed": True, "status": None, "exists": None, "noindex": None,
           "error": None}
    try:
        resp = safe_get(url, timeout=timeout, headers=default_headers(),
                        allow_redirects=True)
    except Exception as exc:                       # network, DNS, TLS, refusal
        out["error"] = f"{type(exc).__name__}: {exc}"
        return out
    if resp is None:
        out["error"] = "no response"
        return out

    out["status"] = getattr(resp, "status_code", None)
    # Anything that is not a served page is not an indexable page. A 5xx is not a
    # denial either — it says the server could not answer, so `exists` stays None and
    # the URL is left out of the verdict rather than counted in it.
    if out["status"] in (404, 410):
        out["exists"] = False
        return out
    if out["status"] is None or out["status"] >= 500:
        out["error"] = f"status {out['status']}"
        return out
    out["exists"] = 200 <= out["status"] < 400

    header = ""
    try:
        header = resp.headers.get("X-Robots-Tag", "") or ""
    except Exception:
        header = ""
    body = ""
    if out["exists"]:
        try:
            body = resp.text or ""
        except Exception:
            body = ""
    tags = " ".join(_META_ROBOTS.findall(_COMMENT.sub(" ", body)))
    out["noindex"] = bool(_NOINDEX.search(header) or _NOINDEX.search(tags))
    return out


def test_paths(site: str, paths: list[str], agents: list[str], timeout: int = 15,
               probe: bool = False) -> dict:
    robots = fetch_robots(site, timeout=timeout)
    rows = []
    for path in paths:
        url = normalize_url(path, site)
        decisions = {}
        for agent in agents:
            allowed, rule = robots_allowed(robots.get("parsed"), url, agent)
            decisions[agent] = {"allowed": allowed, "rule": rule}
        row = {"url": url, "decisions": decisions,
               "allowed_for": sorted(a for a, d in decisions.items() if d["allowed"])}
        # Only paths robots permits are worth a request: a disallowed path is already
        # out of the index, and fetching it to prove that would spend the budget to
        # learn nothing.
        if probe and row["allowed_for"]:
            row["probe"] = probe_url(url, timeout=timeout)
        rows.append(row)
    # The paths these tests exist to keep out of the index, flattened into one
    # list. A checklist assertion can then say "this must be empty" instead of
    # matching text across a nested structure — where "allowed" and "true" never
    # land in the same string, so the pattern never fired and every site passed.
    reachable = sorted({row["url"] for row in rows if row["allowed_for"]})
    status = robots["fetch"].get("status")
    unreachable_robots = not (carries_content(status) or status == 404)
    out = {"site": normalize_url(site), "robots_url": robots["url"],
           "robots_status": robots["fetch"].get("status"), "rows": rows}
    # No robots.txt answer means no verdict: a 500 or a timeout says nothing about
    # what is allowed, and an empty list would read as "nothing is exposed".
    if paths and not unreachable_robots:
        out["allowed_urls"] = reachable
        out["blocked_urls"] = sorted(
            row["url"] for row in rows if not row["allowed_for"])
    if probe and not unreachable_robots:
        # What CI-019 actually asks: pages that exist, that a crawler may fetch, and
        # that carry no directive keeping them out of the index. A path missing from
        # the site does not appear here, and neither does one that answers with
        # `noindex` — which is the mechanism this item's title has always named.
        #
        # A URL whose probe errored is in neither list. `indexable_urls` would make it
        # an accusation and `unprobed_urls` records it instead, so a network failure
        # cannot quietly read as a clean site.
        indexable, unprobed = [], []
        for row in rows:
            p = row.get("probe")
            if not row["allowed_for"]:
                continue
            if p is None or p.get("error") or p.get("exists") is None:
                unprobed.append(row["url"])
            elif p["exists"] and not p["noindex"]:
                indexable.append(row["url"])
        out["indexable_urls"] = sorted(indexable)
        out["unprobed_urls"] = sorted(unprobed)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Test paths against robots.txt")
    parser.add_argument("site")
    parser.add_argument("paths", nargs="*")
    parser.add_argument("--discover-assets", action="store_true",
                        help="Discover same-origin stylesheet, script and image paths "
                             "from the audited page")
    parser.add_argument("--agent", action="append", help="Crawler user-agent; repeatable")
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument("--probe", action="store_true",
                        help="Fetch each permitted path to see whether it exists and "
                             "whether it carries noindex")
    parser.add_argument("--json", "-j", action="store_true")
    args = parser.parse_args()
    if not args.paths and not args.discover_assets:
        parser.error("provide one or more paths or use --discover-assets")
    paths = args.paths
    discovery_error = None
    if args.discover_assets:
        paths, discovery_error = discover_asset_paths(args.site, args.timeout)
    if discovery_error:
        result = {"site": normalize_url(args.site), "rows": [],
                  "asset_discovery_error": discovery_error,
                  "error": f"asset discovery failed: {discovery_error}"}
    elif not paths:
        result = {"site": normalize_url(args.site), "rows": []}
        if args.discover_assets:
            result["discovered_assets"] = []
    else:
        result = test_paths(args.site, paths, args.agent or DEFAULT_AGENTS,
                            args.timeout, probe=args.probe)
        if args.discover_assets:
            result["discovered_assets"] = paths
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for row in result["rows"]:
            print(row["url"])
            for agent, decision in row["decisions"].items():
                print(f"  {agent}: {'allowed' if decision['allowed'] else 'blocked'} ({decision['rule']})")


if __name__ == "__main__":
    from lib.utf8_streams import utf8_streams
    utf8_streams()
    main()
