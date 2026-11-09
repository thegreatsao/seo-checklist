#!/usr/bin/env python3
"""
Parse HTML and extract SEO-relevant elements.

Usage:
    python parse_html.py page.html
    python parse_html.py page.html --url https://example.com
    python parse_html.py --fetch https://example.com --json
"""

try:
    from lib import python_floor  # noqa: F401
except ImportError:
    from scripts.lib import python_floor  # noqa: F401

import argparse
import json
import os
import re
import sys
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("Error: beautifulsoup4 required. Install with: pip install beautifulsoup4")
    sys.exit(1)

try:
    from article_seo import META_MAX_CHARS, META_MIN_CHARS
    from lib.safe_http import safe_get
    from lib.schema_types import DEPRECATED_TYPES, RESTRICTED_TYPES
except ImportError:
    from scripts.article_seo import META_MAX_CHARS, META_MIN_CHARS
    from scripts.lib.safe_http import safe_get
    from scripts.lib.schema_types import DEPRECATED_TYPES, RESTRICTED_TYPES

from seo_common import (read_as_url, comparable_url, document_title, favicon_href,
                        html_parser, is_responsive_fill_image as _is_responsive_fill_image,
                        issue, url_host, walk_json)


# The band MS-030 reads, in order of length.
META_DESCRIPTION_BANDS = ("short", "fits", "long")


def _fetch_url(url: str, timeout: int = 20) -> dict[str, Any]:
    """Fetch HTML for direct parsing."""
    response = safe_get(
        url,
        timeout=timeout,
        headers={"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"},
    )
    return {
        "url": response.url,
        "content": response.text,
        "headers": dict(response.headers),
        "status_code": response.status_code,
    }


def _schema_items(schema_data: Any) -> list[dict[str, Any]]:
    """Flatten top-level JSON-LD objects and @graph nodes for validation."""
    if isinstance(schema_data, list):
        items: list[dict[str, Any]] = []
        for item in schema_data:
            items.extend(_schema_items(item))
        return items
    if not isinstance(schema_data, dict):
        return []
    items = [schema_data]
    graph = schema_data.get("@graph")
    if isinstance(graph, list):
        items.extend([node for node in graph if isinstance(node, dict)])
    return items


def _is_breadcrumb_type(value: Any) -> bool:
    """Whether a JSON-LD, Microdata or RDFa type names BreadcrumbList."""
    values = value if isinstance(value, (list, tuple)) else [value]
    for raw in values:
        for token in str(raw or "").split():
            if re.search(r"(?:^|[:/#])BreadcrumbList$", token, re.I):
                return True
    return False


def _names_property(tag, name: str) -> bool:
    """Whether a tag's Microdata `itemprop` or RDFa `property` names `name`, bare,
    prefixed (`schema:itemListElement`) or as an IRI."""
    return any(re.search(rf"(?:^|[:/#]){name}$", token)
               for value in (tag.get("itemprop"), tag.get("property"))
               for token in str(value or "").split())


def _item_parts(tag, soup) -> list:
    """An item's element, its descendants, and the elements its Microdata `itemref`
    brings in with theirs."""
    parts = [tag, *tag.find_all(True)]
    for ident in str(tag.get("itemref") or "").split():
        found = soup.find(id=ident)
        if found is not None:
            parts += [found, *found.find_all(True)]
    return parts


def _is_trail_entry(tag, soup) -> bool:
    """An `itemListElement` that names its page or its label: an `item` or `name`
    property with a value: its text, or a `content`, `href` or `value` attribute
    (Codex's reviews of F15 batch 1)."""
    if not _names_property(tag, "itemListElement"):
        return False
    return any((_names_property(part, "name") or _names_property(part, "item"))
               and (part.get_text(strip=True)
                    or any(str(part.get(attr) or "").strip()
                           for attr in ("content", "href", "value")))
               for part in _item_parts(tag, soup))


def _breadcrumb_markup(soup) -> list:
    """The elements of every Microdata or RDFa BreadcrumbList that holds a trail entry:
    the carrier, its descendants and what its `itemref` brings in.

    A carrier with no `itemListElement` is a type with no trail (F15, AR-158): it is
    neither markup Google can show nor a breadcrumb anybody sees.
    """
    carriers = []
    for element in soup.find_all(True):
        if ((element.has_attr("itemscope")
                and _is_breadcrumb_type(element.get("itemtype")))
                or _is_breadcrumb_type(element.get("typeof"))):
            parts = _item_parts(element, soup)
            entries = [part for part in parts if _is_trail_entry(part, soup)]
            if entries:
                # An entry's own `itemref` brings its link in too.
                carriers += parts + [p for entry in entries for p in _item_parts(entry, soup)]
    return carriers


def _node_id(base_url: str, ident: str) -> str:
    """A JSON-LD `@id` resolved against the page, or as written when it is no URL any
    parser accepts (`https://[YOUR_DOMAIN]/`, an unexpanded template)."""
    try:
        return urljoin(base_url, ident)
    except ValueError:
        return ident


def _has_trail_entry(entries: Any, nodes: dict | None = None, base_url: str = "") -> bool:
    """Whether a JSON-LD `itemListElement` holds one entry a trail can show: an object
    naming its page (`item`) or its label (`name`). `[null]`, `[{}]` and a string are
    no trail (Codex's review of F15 batch 1)."""
    def named(value, node=False):
        if node and isinstance(value, dict):     # `item` as a node: its `@id` or `url`
            value = value.get("@id") or value.get("url") or value.get("name")
        return isinstance(value, str) and bool(value.strip())

    entries = entries if isinstance(entries, list) else [entries]
    # An entry with an `@id` is that node, every definition of it on the page merged
    # (`nodes`, keyed by the id resolved against the page), its own properties first.
    entries = [{**(nodes or {}).get(_node_id(base_url, entry["@id"]), {}), **entry}
               if isinstance(entry, dict) and isinstance(entry.get("@id"), str) else entry
               for entry in entries]
    return any(isinstance(entry, dict)
               and (named(entry.get("item"), node=True) or named(entry.get("name")))
               for entry in entries)


def _nav_accessible_name(nav, soup) -> str:
    names = [nav.get("aria-label") or "", nav.get("title") or ""]
    for ident in str(nav.get("aria-labelledby") or "").split():
        label = soup.find(id=ident)
        if label:
            names.append(label.get_text(" ", strip=True))
    return " ".join(names)


def _has_breadcrumb_ui(soup, carriers: list) -> bool:
    """Find explicit, machine-detectable markers for a visible breadcrumb trail.

    Accepted markers are a nav landmark whose accessible name says breadcrumb,
    any element whose class or id says breadcrumb, and a Microdata/RDFa
    BreadcrumbList carrier with a trail entry and a link in it — markup on the
    elements a visitor sees. A hand-rolled row of plain links with none of those
    markers is intentionally undetectable here: static HTML cannot distinguish it
    reliably from ordinary navigation.
    """
    if any(part.name == "a" and part.has_attr("href") for part in carriers):
        return True
    if any(re.search(r"breadcrumb", _nav_accessible_name(nav, soup), re.I)
           for nav in soup.find_all("nav")):
        return True
    for element in soup.find_all(True):
        marker = " ".join([str(element.get("id") or ""),
                           " ".join(element.get("class") or [])])
        if re.search(r"breadcrumb", marker, re.I):
            return True
    return False


def _structure_issues(soup) -> list[dict[str, Any]]:
    """Report heading-level skips and missing semantic landmark elements."""
    issues = []
    headings = [(int(element.name[1]), element.get_text(" ", strip=True))
                for element in soup.find_all(re.compile(r"^h[1-6]$", re.I))
                if element.get_text(" ", strip=True)]
    for (previous, _), (current, text) in zip(headings, headings[1:], strict=False):
        if current > previous + 1:
            issues.append(issue(
                "error", f"Heading hierarchy skips from H{previous} to H{current}",
                evidence=text[:120]))

    # `main` is the one landmark whose absence is always a markup defect: every
    # page has main content, so not marking it is a page that failed to say where
    # its content is.
    if not soup.find("main"):
        issues.append(issue("error", "No main landmark element found"))
    # `nav` and `footer` are deliberately not checked for absence. A page with no
    # navigation correctly has no `nav`, and a page with no footer content
    # correctly has no `footer` — penalising that measures page design, not
    # semantic markup, and "Use Hierarchical Headings and Semantic HTML" asks for
    # the second. The honest version of the check would be structural rather than
    # existential: a list of links in a header that is *not* inside a `nav`. That
    # needs a reliable "this looks like navigation" test, which nothing here has,
    # so the check says less rather than guessing.
    return issues


def _same_page(a: str, b: str) -> bool:
    """Two URLs naming one page: one scheme, host (`url_host`) and port, and one path,
    params and query as requests sends them, a trailing slash aside."""
    first, second = urlparse(comparable_url(a)), urlparse(comparable_url(b))
    try:
        ports = first.port == second.port
    except ValueError:      # a port no parser accepts names no page
        return False
    return (ports and url_host(a) == url_host(b) and first.scheme == second.scheme
            and first.params == second.params and first.query == second.query
            and first.path.rstrip("/") == second.path.rstrip("/"))


def parse_html(
    html: str,
    base_url: Optional[str] = None,
    headers: Optional[dict[str, Any]] = None,
) -> dict:
    """
    Parse HTML and extract SEO-relevant elements.

    Args:
        html: HTML content to parse
        base_url: Base URL for resolving relative links

    Returns:
        Dictionary with extracted SEO data
    """
    # One decision, in one place: see seo_common.html_parser. This script used to
    # repeat the `"lxml" in sys.modules` test, so the *same page* could be parsed
    # one way by parse_html.py and another by every check that goes through
    # seo_common — within a single audit.
    soup = BeautifulSoup(html, html_parser())
    headers = headers or {}
    header_lookup = {str(k).lower(): v for k, v in headers.items()}
    structured_breadcrumb = _breadcrumb_markup(soup)

    result = {
        "title": None,
        "meta_description": None,
        "meta_robots": None,
        # MS-031 reads the None through its falsy operator when the tag is absent.
        # The key is always emitted, so its absence can only mean the script
        # did not report.
        "meta_keywords": None,
        "x_robots_tag": header_lookup.get("x-robots-tag"),
        "canonical": None,
        "lang": None,
        "charset": None,
        "viewport": None,
        "favicon": None,
        "h1": [],
        "h2": [],
        "h3": [],
        "h4": [],
        "h5": [],
        "h6": [],
        "images": [],
        "links": {
            "internal": [],
            "external": [],
        },
        "pagination": {
            "prev": None,
            "next": None,
            "paginated": False,
            "issues": [],
        },
        "resource_hints": {
            "preload": [],
            "preconnect": [],
            "dns-prefetch": [],
            "prefetch": [],
            "prerender": [],
        },
        "schema": [],
        "breadcrumbs": {
            "schema": bool(structured_breadcrumb),
            "ui": _has_breadcrumb_ui(soup, structured_breadcrumb),
        },
        "issues": _structure_issues(soup),
        "open_graph": {},
        "twitter_card": {},
        "word_count": 0,
        "hreflang": [],
    }

    html_tag = soup.find("html")
    if html_tag:
        result["lang"] = html_tag.get("lang")

    result["title"] = document_title(soup)

    # Meta tags. Every robots and keywords tag is kept (F15, CI-004 and MS-031): when
    # each overwrote the last, `noindex` followed by `index` read as indexable and a
    # populated keywords tag followed by an empty one read as none.
    robots, keywords = [], []
    for meta in soup.find_all("meta"):
        name = meta.get("name", "").lower()
        property_attr = meta.get("property", "").lower()
        content = meta.get("content", "")

        if name == "description":
            # Whitespace is no description (F15, MS-028).
            result["meta_description"] = content.strip()
        elif name == "robots":
            robots.append(content)
        elif name == "keywords":
            keywords.append(content.strip())
        elif name == "viewport":
            result["viewport"] = content

        if meta.get("charset"):
            result["charset"] = meta.get("charset")
        elif meta.get("http-equiv", "").lower() == "content-type":
            charset_match = re.search(r"charset=([^;\s]+)", content, re.I)
            if charset_match:
                result["charset"] = charset_match.group(1)

        # Open Graph
        if property_attr.startswith("og:"):
            result["open_graph"][property_attr] = content

        # Twitter Card
        if name.startswith("twitter:"):
            result["twitter_card"][name] = content

    if robots:
        result["meta_robots"] = ", ".join(robots)
    if keywords:
        result["meta_keywords"] = ", ".join(value for value in keywords if value)

    text = " ".join((result["meta_description"] or "").split())
    if text:
        result["meta_description_chars"] = len(text)
        if len(text) < META_MIN_CHARS:
            result["meta_description_band"] = "short"
        elif len(text) <= META_MAX_CHARS:
            result["meta_description_band"] = "fits"
        else:
            result["meta_description_band"] = "long"

    # Canonical
    canonical = soup.find("link", rel="canonical")
    if canonical:
        href = canonical.get("href")
        result["canonical"] = urljoin(base_url, href) if base_url and href else href

    result["favicon"] = favicon_href(soup, base_url)

    # Hreflang
    for link in soup.find_all("link", rel="alternate"):
        hreflang = link.get("hreflang")
        if hreflang:
            result["hreflang"].append({
                "lang": hreflang,
                "href": urljoin(base_url, link.get("href", "")) if base_url else link.get("href"),
            })

    for rel_name in ("prev", "next"):
        page_link = soup.find("link", rel=rel_name)
        if page_link and page_link.get("href"):
            href = page_link.get("href")
            result["pagination"][rel_name] = urljoin(base_url, href) if base_url else href

    # Whether this page paginates at all, and what is wrong with it if it does.
    #
    # AR-146 used to assert that `pagination` was truthy — and `pagination` is a dict
    # that always holds both keys, so `{"prev": None, "next": None}` is a non-empty
    # dict and the item could not fail on any page ever audited. A page with no
    # `rel=next`/`rel=prev` has no pagination defect and passes; a page that does
    # paginate can now be wrong about it.
    result["pagination"]["paginated"] = any(
        result["pagination"].get(rel) for rel in ("prev", "next"))
    for rel_name in ("prev", "next"):
        href = result["pagination"].get(rel_name)
        if not href:
            continue
        # Hosts compare as hosts (F15 batch 1, Codex's reviews: AR-146 failed
        # `https://EXAMPLE.COM/page2`, `:443` and `reader@` on the page's own host).
        if base_url and urlparse(href).netloc and url_host(href) != url_host(base_url):
            result["pagination"]["issues"].append({
                "severity": "error", "type": f"pagination_{rel_name}_offsite",
                "message": f"rel={rel_name} points at another host: {href}"})
        if base_url and _same_page(href, base_url):
            result["pagination"]["issues"].append({
                "severity": "error", "type": f"pagination_{rel_name}_self",
                "message": f"rel={rel_name} points at this page"})

    for rel_name in result["resource_hints"]:
        for link in soup.find_all("link", rel=rel_name):
            href = link.get("href")
            if href:
                result["resource_hints"][rel_name].append({
                    "href": urljoin(base_url, href) if base_url else href,
                    "as": link.get("as"),
                    "type": link.get("type"),
                    "crossorigin": link.get("crossorigin"),
                })

    # Headings
    for tag in ["h1", "h2", "h3", "h4", "h5", "h6"]:
        for heading in soup.find_all(tag):
            text = heading.get_text(strip=True)
            if text:
                result[tag].append(text)

    # Images
    for img in soup.find_all("img"):
        src = img.get("src", "")
        if base_url and src:
            src = urljoin(base_url, src)
        is_responsive_fill = _is_responsive_fill_image(img)

        result["images"].append({
            "src": src,
            "alt": img.get("alt"),
            "width": img.get("width"),
            "height": img.get("height"),
            "is_responsive_fill": is_responsive_fill,
            "loading": img.get("loading"),
        })

    # Links
    if base_url:
        base_domain = urlparse(base_url).netloc

        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            if not href or href.startswith("#") or href.startswith("javascript:"):
                continue

            full_url = urljoin(base_url, href)
            parsed = urlparse(full_url)

            link_data = {
                "href": full_url,
                "text": a.get_text(strip=True)[:100],
                "rel": a.get("rel", []),
            }

            if parsed.netloc == base_domain:
                result["links"]["internal"].append(link_data)
            else:
                result["links"]["external"].append(link_data)

    # Schema (JSON-LD) — enhanced with type validation
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            schema_data = json.loads(script.string)
        except (json.JSONDecodeError, TypeError):
            result["schema"].append({
                "error": "invalid_json",
                "raw_snippet": (script.string or "")[:120],
            })
            continue

        items = _schema_items(schema_data)
        for item in items or [{}]:
            schema_type = item.get("@type", "Unknown")
            if isinstance(schema_type, list):
                schema_types = schema_type
                primary_type = next((t for t in schema_type if isinstance(t, str)), "Unknown")
            else:
                schema_types = [schema_type]
                primary_type = schema_type

            status = "active"
            note = ""

            if primary_type in DEPRECATED_TYPES:
                status = "deprecated"
                note = f"{primary_type} was deprecated/removed from rich results. Remove or replace."
            elif primary_type in RESTRICTED_TYPES:
                status = "restricted"
                note = f"{primary_type} is restricted to government/healthcare authority sites only."

            result["schema"].append({
                "@type": primary_type,
                "@types": schema_types,
                "@id": item.get("@id"),
                "@context": item.get("@context", schema_data.get("@context", "") if isinstance(schema_data, dict) else ""),
                "status": status,
                "note": note,
                "has_context": bool(item.get("@context") or (isinstance(schema_data, dict) and schema_data.get("@context"))),
                "has_type": bool(item.get("@type")),
                "from_graph": item is not schema_data,
                "raw": item,
            })

    # A BreadcrumbList with no `itemListElement` is no trail (F15, AR-158). Every
    # node is read, nested ones included (`WebPage.breadcrumb`), and an entry given as
    # an `@id` is resolved against every definition of that node on the page.
    found = [node for item in result["schema"] if isinstance(item.get("raw"), dict)
             for node in walk_json(item["raw"])]
    nodes: dict[str, dict] = {}
    for node in found:
        if isinstance(node.get("@id"), str):
            nodes.setdefault(_node_id(base_url or "", node["@id"]), {}).update(node)
    # The merged nodes too: one BreadcrumbList may be split over two definitions.
    result["breadcrumbs"]["schema"] = (
        result["breadcrumbs"]["schema"]
        or any(_is_breadcrumb_type(node.get("@type"))
               and _has_trail_entry(node.get("itemListElement"), nodes, base_url or "")
               for node in [*found, *nodes.values()])
    )

    # Word count (visible text only)
    for element in soup(["script", "style", "nav", "footer", "header"]):
        element.decompose()

    text = soup.get_text(separator=" ", strip=True)
    words = re.findall(r"\b\w+\b", text)
    result["word_count"] = len(words)

    return result


def main():
    parser = argparse.ArgumentParser(description="Parse HTML for SEO analysis")
    parser.add_argument("file", nargs="?", help="HTML file to parse")
    parser.add_argument("--url", "-u", help="Base URL for resolving links")
    parser.add_argument("--fetch", help="Fetch and parse a URL directly")
    parser.add_argument("--timeout", "-t", type=int, default=20, help="Fetch timeout in seconds")
    parser.add_argument("--json", "-j", action="store_true", help="Output as JSON")

    args = parser.parse_args()
    args.url = read_as_url(args.url)
    args.fetch = read_as_url(args.fetch)

    headers = {}
    final_url = args.url

    if args.fetch:
        try:
            fetched = _fetch_url(args.fetch, timeout=args.timeout)
        except Exception as exc:
            print(f"Error fetching {args.fetch}: {exc}", file=sys.stderr)
            sys.exit(1)
        if fetched.get("error"):
            print(f"Error fetching {args.fetch}: {fetched['error']}", file=sys.stderr)
            sys.exit(1)
        html = fetched.get("content") or ""
        headers = fetched.get("headers") or {}
        final_url = args.url or fetched.get("url") or args.fetch
    elif args.file:
        real_path = os.path.realpath(args.file)
        if not os.path.isfile(real_path):
            print(f"Error: File not found: {args.file}", file=sys.stderr)
            sys.exit(1)
        with open(real_path, "r", encoding="utf-8") as f:
            html = f.read()
    else:
        html = sys.stdin.read()

    result = parse_html(html, final_url, headers=headers)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Title: {result['title']}")
        print(f"Meta Description: {result['meta_description']}")
        print(f"Canonical: {result['canonical']}")
        print(f"H1 Tags: {len(result['h1'])}")
        print(f"H2 Tags: {len(result['h2'])}")
        print(f"Images: {len(result['images'])}")
        print(f"Internal Links: {len(result['links']['internal'])}")
        print(f"External Links: {len(result['links']['external'])}")
        print(f"Schema Blocks: {len(result['schema'])}")
        print(f"Word Count: {result['word_count']}")


if __name__ == "__main__":
    from lib.utf8_streams import utf8_streams
    utf8_streams()
    from lib.typed_credential import credentials_beside_argv
    credentials_beside_argv()
    main()
