#!/usr/bin/env python3
"""Validate required and recommended Schema.org properties in JSON-LD."""

from __future__ import annotations

import argparse
import json
import os
import re
from collections.abc import Iterable
from typing import Any

from seo_common import as_list, issue, load_html, parse_html, print_json_or_text


REQUIRED_PROPS: dict[str, set[str]] = {
    "Article": {"headline", "author", "datePublished"},
    "BlogPosting": {"headline", "author", "datePublished"},
    "BreadcrumbList": {"itemListElement"},
    "FAQPage": {"mainEntity"},
    "HowTo": {"name", "step"},
    "LocalBusiness": {"name", "address", "telephone"},
    "Organization": {"name", "url"},
    "Product": {"name", "offers"},
    "ProductGroup": {"name", "productGroupID", "hasVariant"},
    "Review": {"itemReviewed", "reviewRating", "author"},
    "VideoObject": {"name", "description", "thumbnailUrl", "uploadDate"},
    "WebSite": {"name", "url"},
}

RECOMMENDED_PROPS: dict[str, set[str]] = {
    "Article": {"image", "dateModified", "publisher", "mainEntityOfPage"},
    "BlogPosting": {"image", "dateModified", "publisher", "mainEntityOfPage"},
    # `name`, `position` and `item` belong to each ListItem, not to the list. They
    # were filed under BreadcrumbList, where they never appear on any correct markup
    # in existence — so every site with a working breadcrumb collected three
    # "missing recommended property" warnings, and AR-158 (which matches the string
    # "BreadcrumbList") failed all of them. `iter_schema_nodes` already walks into
    # `itemListElement`, so the entries are checked where they live.
    "ListItem": {"name", "position", "item"},
    "LocalBusiness": {"url", "image", "geo", "openingHoursSpecification", "sameAs", "aggregateRating"},
    "Organization": {"logo", "sameAs", "contactPoint"},
    "Product": {"image", "description", "sku", "brand", "aggregateRating", "review"},
    "ProductGroup": {"variesBy", "brand", "description"},
    "Review": {"reviewBody", "datePublished", "publisher"},
    "VideoObject": {"duration", "contentUrl", "embedUrl", "publisher", "transcript"},
    # `WebSite: {potentialAction}` was here and is gone. It asked every site for the
    # `SearchAction` of the Sitelinks Search Box, and there are two things wrong with
    # that, either of which is enough.
    #
    # The authority, named: Google removed the sitelinks search box from Search
    # starting 21 November 2024, globally and in every language, and took it out of
    # Search Console and the Rich Results Test with it ("Farewell, Sitelinks Search
    # Box", Search Central blog, October 2024). The markup is not read for that
    # feature by anything any more, so asking for it is advice for a result that
    # cannot appear.
    #
    # Deliberately not written with the marker `audit_thresholds` scans for. That
    # prefix belongs to a module-level numeric constant, the tool reads every line
    # carrying it as one, and a first draft of this comment used it for prose — which
    # put this file on the tool's list of basis lines naming something that is not a
    # number, where it said nothing to anybody. A citation is not a threshold, and
    # naming the marker in prose is enough to be counted as using it.
    #
    # The second reason outlives the first: a `SearchAction` declares a search
    # endpoint and a query template. On a site with no site search that is a false
    # statement about the site, and this tool does not ask anyone to publish one. It
    # is the same rule the release before this one drew about verdicts — a claim
    # nobody measured must not be made — applied to the advice rather than the score.
    #
    # `WebSite` itself stays required (`name`, `url`) and stays useful: it is what
    # Google reads for the site name in results, and its live documentation lists
    # exactly those two as required and `alternateName` as optional. `alternateName`
    # is not added here — optional is not recommended, and this table is read as an
    # instruction.
}

PLACEHOLDER_MARKERS = ("REPLACE", "TODO", "INSERT", "example.com", "lorem ipsum")

# `[SHOUTED TEXT IN BRACKETS]` is what an unfilled template looks like. The marker
# list used to contain a bare `"["`, tested against `json.dumps` of the property
# value — so **every property whose value is a list or an object** was reported as
# placeholder text. A correct `itemListElement` was "placeholder text", and AR-158
# (which matches the string "BreadcrumbList") failed every site with a working
# breadcrumb. Two accuse-everybody defects in the same six lines.
PLACEHOLDER_BRACKETS = re.compile(r"\[[A-Z][A-Z0-9 _/-]{2,}\]")


def schema_type_names(value: Any) -> list[str]:
    names = []
    for item in as_list(value):
        if isinstance(item, str):
            names.append(item)
    return names


def iter_schema_nodes(data: Any, path: str = "$") -> Iterable[tuple[str, dict[str, Any]]]:
    """Yield every JSON-LD object, including @graph and nested entity objects."""
    if isinstance(data, list):
        for index, item in enumerate(data):
            yield from iter_schema_nodes(item, f"{path}[{index}]")
        return
    if not isinstance(data, dict):
        return
    yield path, data
    graph = data.get("@graph")
    if isinstance(graph, list):
        for index, item in enumerate(graph):
            yield from iter_schema_nodes(item, f"{path}.@graph[{index}]")
    for key, value in data.items():
        if key in {"@context", "@graph"}:
            continue
        if isinstance(value, dict):
            yield from iter_schema_nodes(value, f"{path}.{key}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                if isinstance(item, dict):
                    yield from iter_schema_nodes(item, f"{path}.{key}[{index}]")


def load_source_html(source: str, timeout: int = 15) -> tuple[str, str, dict[str, Any]]:
    """Load local files before falling back to seo_common URL detection."""
    if os.path.isfile(source):
        with open(source, "r", encoding="utf-8") as fh:
            return fh.read(), source, {"url": source, "status": None, "headers": {}, "error": None}
    return load_html(source, timeout=timeout)


def extract_schema_documents(source: str, timeout: int = 15) -> tuple[list[Any], dict[str, Any]]:
    html_or_json, final_url, fetch = load_source_html(source, timeout=timeout)
    text = (html_or_json or "").strip()
    documents: list[Any] = []
    if text.startswith("{") or text.startswith("["):
        try:
            documents.append(json.loads(text))
        except json.JSONDecodeError:
            pass
    invalid = []
    if not documents and html_or_json:
        parsed = parse_html(html_or_json, final_url or source)
        # Validate every type the document declares, including contributed blocks.
        for item in parsed.get("schema", []):
            if isinstance(item, dict) and item.get("error"):
                # Dropped silently before. A block of JSON-LD that does not parse is
                # not an absence of structured data, and reporting it as one made
                # `summary.errors = 0` — a PASS for MS-032 — on a page whose schema
                # Google cannot read at all. The §4.1 shape: an empty result
                # satisfying a rule that counts problems.
                invalid.append(item)
            else:
                documents.append(item)
    return documents, {"source": source, "final_url": final_url or source,
                       "fetch": fetch, "invalid_blocks": invalid}


def find_schema_nodes(documents: list[Any], schema_type: str | None = None) -> list[dict[str, Any]]:
    rows = []
    for doc_index, doc in enumerate(documents):
        for path, node in iter_schema_nodes(doc, f"$[{doc_index}]"):
            types = schema_type_names(node.get("@type"))
            if not types:
                continue
            if schema_type and schema_type not in types:
                continue
            rows.append({"path": path, "types": types, "node": node})
    return rows


def has_value(node: dict[str, Any], prop: str) -> bool:
    if prop not in node:
        return False
    value = node[prop]
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return bool(value)
    return True


def contains_placeholder(value: Any) -> bool:
    """Whether a property value looks like an unfilled template.

    Strings only, walked into lists and objects. Serialising the whole value and
    searching that is what made a JSON array match a `"["` marker.
    """
    if isinstance(value, str):
        upper = value.upper()
        return (any(marker.upper() in upper for marker in PLACEHOLDER_MARKERS)
                or bool(PLACEHOLDER_BRACKETS.search(value)))
    if isinstance(value, dict):
        return any(contains_placeholder(item) for item in value.values())
    if isinstance(value, list):
        return any(contains_placeholder(item) for item in value)
    return False


def validate_schema_required_props(documents: list[Any], schema_type: str | None = None,
                                   invalid_blocks: list | None = None) -> dict[str, Any]:
    rows = []
    issues = []
    for block in (invalid_blocks or []):
        issues.append({
            "severity": "error",
            "path": "$",
            "message": "JSON-LD block does not parse; Google reads none of it",
            "evidence": (block.get("snippet") or block.get("raw_snippet") or "")[:160],
        })
    nodes = find_schema_nodes(documents, schema_type)
    for row in nodes:
        node = row["node"]
        primary_type = row["types"][0]
        required = set()
        recommended = set()
        for type_name in row["types"]:
            required.update(REQUIRED_PROPS.get(type_name, set()))
            recommended.update(RECOMMENDED_PROPS.get(type_name, set()))
        missing_required = sorted(prop for prop in required if not has_value(node, prop))
        missing_recommended = sorted(prop for prop in recommended if not has_value(node, prop))
        placeholders = sorted(prop for prop, value in node.items() if contains_placeholder(value))
        for prop in missing_required:
            issues.append(issue("error", f"{primary_type} is missing required property '{prop}'", evidence=row["path"]))
        for prop in missing_recommended:
            issues.append(issue("warning", f"{primary_type} is missing recommended property '{prop}'", evidence=row["path"]))
        for prop in placeholders:
            issues.append(issue("warning", f"{primary_type} property '{prop}' appears to contain placeholder text", evidence=row["path"]))
        rows.append(
            {
                "path": row["path"],
                "types": row["types"],
                "missing_required": missing_required,
                "missing_recommended": missing_recommended,
                "placeholder_properties": placeholders,
            }
        )
    # One entry per schema type present on the page, counting the nodes of that
    # type this checker found something to say about. A type with nothing wrong
    # still gets a key, at zero: the difference between "the WebSite node is
    # complete" and "there is no WebSite node" is a verdict an item may want to
    # draw, and an absent key is the only way to say the second.
    #
    # This exists so an item can ask about one type without matching that type's
    # name against a human-readable message. `GO-143` did, with `(?i)WebSite`, and
    # a pattern aimed at wording is a verdict that passes in silence the day the
    # wording changes.
    incomplete: dict[str, int] = {}
    for row in rows:
        wrong = bool(row["missing_required"] or row["missing_recommended"]
                     or row["placeholder_properties"])
        for type_name in row["types"]:
            incomplete[type_name] = incomplete.get(type_name, 0) + int(wrong)
    return {
        "schema_nodes": len(nodes),
        "invalid_blocks": len(invalid_blocks or []),
        "checked_type": schema_type,
        "incomplete_nodes_by_type": incomplete,
        "rows": rows,
        "issues": issues,
        "summary": {
            "errors": sum(1 for item in issues if item["severity"] == "error"),
            "warnings": sum(1 for item in issues if item["severity"] == "warning"),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate required/recommended JSON-LD properties")
    parser.add_argument("source", help="URL, HTML file, or JSON-LD file")
    parser.add_argument("--type", dest="schema_type", help="Limit checks to one schema type, e.g. Product")
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument("--json", "-j", action="store_true", help="Output JSON")
    args = parser.parse_args()

    documents, meta = extract_schema_documents(args.source, timeout=args.timeout)
    result = validate_schema_required_props(documents, args.schema_type,
                                            meta.get("invalid_blocks"))
    result.update({"source": args.source, "final_url": meta["final_url"],
                   "fetch_error": (meta.get("fetch") or {}).get("error")})
    lines = [
        f"Schema required properties for {args.source}",
        f"Nodes checked: {result['schema_nodes']}  Errors: {result['summary']['errors']}  Warnings: {result['summary']['warnings']}",
    ] + [f"[{item['severity']}] {item['message']} {item.get('evidence') or ''}" for item in result["issues"][:30]]
    print_json_or_text(result, args.json, lines)


if __name__ == "__main__":
    main()
