#!/usr/bin/env python3
"""Validate required and recommended Schema.org properties in JSON-LD."""

from __future__ import annotations

from lib import python_floor  # noqa: F401

import argparse
import json
import os
import re
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from seo_common import (read_source, as_list, issue, load_html, parse_html, print_json_or_text,
                        read_as_file)


# Google's required properties per rich result (each page read 2026-10-22; held by
# `tests/test_closed_sets.py`). A tuple inside an entry is "one of these": a Product
# snippet needs a review, a rating or an offer, not an offer. Read by `rich_results_guard`
# (TE-172) and by the validator below (MS-032), which until F04 (batch 4b) kept its own
# rows for these four types and still required `offers` and `description`.
RICH_RESULT_REQUIRED = {
    "BreadcrumbList": ("itemListElement",),
    "Product": ("name", ("review", "aggregateRating", "offers")),
    "Review": ("author", "itemReviewed", "reviewRating"),
    "VideoObject": ("name", "thumbnailUrl", "uploadDate"),
}


# Google's Article page names no required property; `headline` is required here by the
# owner's F03 ruling on TE-172 ("an Article with no headline fails"): without it Google
# has no title of its own to show for the article. Kept apart from Google's table above,
# which `tests/test_closed_sets.py` holds to Google's pages.
RULED_REQUIRED = {
    "Article": ("headline",),
    "BlogPosting": ("headline",),
    "NewsArticle": ("headline",),
}

# The properties of the two tables read by value (F15, TE-172's ruling "by value"):
# text is a non-blank string, a URL an http(s) address or a relative reference with no
# space (or an ImageObject carrying one), a date ISO 8601. Every other property is read as present.
TEXT_PROPS = frozenset({"name", "headline"})
URL_PROPS = frozenset({"thumbnailUrl"})
DATE_PROPS = frozenset({"uploadDate"})


def _is_text(value: Any) -> bool:
    """A non-blank string, or a JSON-LD value object carrying one (`{"@value": …}`)."""
    if isinstance(value, dict) and "@value" in value:
        value = value["@value"]
    return isinstance(value, str) and bool(value.strip())


def _url_value(value: Any) -> bool:
    if isinstance(value, dict):
        return any(_url_value(value.get(key)) for key in ("url", "contentUrl", "@id"))
    if not isinstance(value, str) or not value.strip() or re.search(r"\s", value.strip()):
        return False
    # An http(s) address or a reference resolved against the page; another scheme
    # (`data:`, `javascript:`) is no URL Google fetches a thumbnail from.
    value = value.strip()
    scheme = re.match(r"([A-Za-z][A-Za-z0-9+.-]*):", value)
    return (bool(re.match(r"(?i)https?://[^/]", value)) if scheme
            else not value.startswith("//") or bool(re.match(r"//[^/]", value)))


def _is_date(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def value_ok(node: dict[str, Any], prop: str) -> bool:
    """Whether `prop` carries a value of its kind; a list needs one such entry."""
    if not has_value(node, prop):
        return False
    kind = (_is_text if prop in TEXT_PROPS else _url_value if prop in URL_PROPS
            else _is_date if prop in DATE_PROPS else None)
    if kind is None:
        return True
    return any(kind(entry) for entry in as_list(node[prop]))


def missing_rich_result_props(type_name: str, node: dict, path: str) -> list[str]:
    """What a node lacks of `RICH_RESULT_REQUIRED` and `RULED_REQUIRED`, each as it is
    printed; a property whose value is not of its kind is missing."""
    missing = []
    for prop in RICH_RESULT_REQUIRED.get(type_name, ()) + RULED_REQUIRED.get(type_name, ()):
        if isinstance(prop, tuple):
            if not any(value_ok(node, p) for p in prop):
                missing.append(" or ".join(prop))
        # A review nested in the item it reviews names that item by nesting, and
        # Google says to omit `itemReviewed` there.
        elif not value_ok(node, prop) and not (
                prop == "itemReviewed" and re.search(r"\.reviews?(\[\d+\])?$", path)):
            missing.append(prop)
    return missing


REQUIRED_PROPS: dict[str, set[str]] = {
    "Article": {"headline", "author", "datePublished"},
    "BlogPosting": {"headline", "author", "datePublished"},
    "FAQPage": {"mainEntity"},
    "HowTo": {"name", "step"},
    "LocalBusiness": {"name", "address", "telephone"},
    "Organization": {"name", "url"},
    "ProductGroup": {"name", "productGroupID", "hasVariant"},
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
    # `description` is Google's recommended property (Video page, 2026-09-24), moved here
    # from the required rows in F04 (batch 4b).
    "VideoObject": {"description", "duration", "contentUrl", "embedUrl", "publisher",
                    "transcript"},
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
    # is here by the owner's F03 ruling on GO-143 ("include alternateName"): the item
    # is the site name Google shows, and `alternateName` is the one other property
    # Google reads for it.
    "WebSite": {"alternateName"},
}

PLACEHOLDER_MARKERS = ("REPLACE", "TODO", "INSERT", "lorem ipsum")
# The reserved example domains (RFC 2606), matched as a host: `example.com`,
# `www.example.org/x`, `info@example.net`, but not `myexample.com` or `example.com.au`,
# which a substring search took for placeholders (F15, GO-143's ruling).
PLACEHOLDER_HOST = re.compile(r"(?<![\w.-])(?:[\w-]+\.)*example\.(?:com|org|net)(?![\w-]|\.[\w-])",
                              re.I)

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
        with open(read_as_file(source), "r", encoding="utf-8") as fh:
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
            if (isinstance(item, dict) and item.get("error")
                    and not str(item.get("snippet") or "").strip()):
                continue                  # an empty block declares nothing (F15)
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
                       "fetch": fetch, "invalid_blocks": invalid, "html": html_or_json or ""}


REFERENCE_KEYS = frozenset({"@type", "@id", "@context"})


def find_schema_nodes(documents: list[Any], schema_type: str | None = None) -> list[dict[str, Any]]:
    """Every typed node, except a bare reference — `{"@type", "@id"}` and nothing else —
    to a node the documents define in full under the same `@id` (F15 batch 5's review:
    a WebPage's `mainEntity` pointing at its Article is that Article, not a second one
    with no headline)."""
    defined = {node["@id"] for doc in documents for _, node in iter_schema_nodes(doc)
               if isinstance(node.get("@id"), str) and set(node) - REFERENCE_KEYS}
    rows = []
    for doc_index, doc in enumerate(documents):
        for path, node in iter_schema_nodes(doc, f"$[{doc_index}]"):
            types = schema_type_names(node.get("@type"))
            if not types:
                continue
            if not set(node) - REFERENCE_KEYS and node.get("@id") in defined:
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
                or bool(PLACEHOLDER_HOST.search(value))
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
        rich_missing = set()
        for type_name in row["types"]:
            required.update(REQUIRED_PROPS.get(type_name, set()))
            recommended.update(RECOMMENDED_PROPS.get(type_name, set()))
            rich_missing.update(missing_rich_result_props(type_name, node, row["path"]))
        missing_required = sorted({prop for prop in required if not has_value(node, prop)}
                                  | rich_missing)
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
    #
    # Per type, by that type's own properties (F15, GO-143's ruling): a node typed
    # `["WebSite", "Organization"]` is not an incomplete WebSite for lacking the
    # Organization's logo. A type with no table of its own is judged by every finding,
    # as before.
    incomplete: dict[str, int] = {}
    for row in rows:
        for type_name in row["types"]:
            own = (REQUIRED_PROPS.get(type_name, set()) | RECOMMENDED_PROPS.get(type_name, set())
                   | {p for prop in RICH_RESULT_REQUIRED.get(type_name, ())
                      + RULED_REQUIRED.get(type_name, ())
                      for p in (prop if isinstance(prop, tuple) else (prop,))})
            findings = (row["missing_required"] + row["missing_recommended"]
                        + row["placeholder_properties"])
            if own:
                findings = [prop for prop in findings
                            if prop in own or set(prop.split(" or ")) <= own]
            incomplete[type_name] = incomplete.get(type_name, 0) + int(bool(findings))
    result = {
        "schema_nodes": len(nodes),
        "invalid_blocks": len(invalid_blocks or []),
        # What MS-032 applies to: a page whose only JSON-LD does not parse has no
        # node and still has structured data Google cannot read (F15, the ruling).
        "nodes_and_invalid_blocks": len(nodes) + len(invalid_blocks or []),
        "checked_type": schema_type,
        "incomplete_nodes_by_type": incomplete,
        "rows": rows,
        "issues": issues,
        "summary": {
            "errors": sum(1 for item in issues if item["severity"] == "error"),
            "warnings": sum(1 for item in issues if item["severity"] == "warning"),
        },
    }
    # MS-032's warn band, withheld when a JSON-LD block does not parse: Google reads
    # none of that block, so the page fails rather than warns (F15, MS-032's ruling).
    if not invalid_blocks:
        result["summary"]["warnings_if_every_block_parses"] = result["summary"]["warnings"]
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate required/recommended JSON-LD properties")
    parser.add_argument("source", help="URL, HTML file, or JSON-LD file")
    parser.add_argument("--type", dest="schema_type", help="Limit checks to one schema type, e.g. Product")
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument("--json", "-j", action="store_true", help="Output JSON")
    args = parser.parse_args()
    args.source = read_source(args.source)

    documents, meta = extract_schema_documents(args.source, timeout=args.timeout)
    result = validate_schema_required_props(documents, args.schema_type,
                                            meta.get("invalid_blocks"))
    result.update({"source": args.source, "final_url": meta["final_url"],
                   "fetch_error": (meta.get("fetch") or {}).get("error"),
                   "fetch_error_kind": (meta.get("fetch") or {}).get("error_kind")})
    lines = [
        f"Schema required properties for {args.source}",
        f"Nodes checked: {result['schema_nodes']}  Errors: {result['summary']['errors']}  Warnings: {result['summary']['warnings']}",
    ] + [f"[{item['severity']}] {item['message']} {item.get('evidence') or ''}" for item in result["issues"][:30]]
    print_json_or_text(result, args.json, lines)


if __name__ == "__main__":
    from lib.utf8_streams import utf8_streams
    utf8_streams()
    from lib.typed_credential import credentials_beside_argv
    credentials_beside_argv()
    main()
