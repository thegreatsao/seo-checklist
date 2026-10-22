#!/usr/bin/env python3
"""Guardrail checks for rich-result eligibility and retired schema types."""

from __future__ import annotations

from lib import python_floor  # noqa: F401

import argparse
import re
from typing import Any

from lib.schema_types import DEPRECATED_TYPES, RESTRICTED_TYPES
from schema_required_props import extract_schema_documents, find_schema_nodes, schema_type_names
from seo_common import read_source, issue, print_json_or_text


# Google's required properties per rich result (each page read 2026-10-22; held by
# `tests/test_closed_sets.py`). A tuple inside an entry is "one of these": a Product
# snippet needs a review, a rating or an offer, not an offer.
RICH_RESULT_REQUIRED = {
    "BreadcrumbList": ("itemListElement",),
    "Product": ("name", ("review", "aggregateRating", "offers")),
    "Review": ("author", "itemReviewed", "reviewRating"),
    "VideoObject": ("name", "thumbnailUrl", "uploadDate"),
}


def _missing_required(type_name: str, node: dict, path: str) -> list[str]:
    """What a node lacks of `RICH_RESULT_REQUIRED`, each as it is printed."""
    missing = []
    for prop in RICH_RESULT_REQUIRED.get(type_name, ()):
        if isinstance(prop, tuple):
            if not any(node.get(p) for p in prop):
                missing.append(" or ".join(prop))
        # A review nested in the item it reviews names that item by nesting, and
        # Google says to omit `itemReviewed` there.
        elif not node.get(prop) and not (
                prop == "itemReviewed" and re.search(r"\.reviews?(\[\d+\])?$", path)):
            missing.append(prop)
    return missing


def guard_rich_results(documents: list[Any],
                       invalid_blocks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    rows = []
    issues = []
    for block in (invalid_blocks or []):
        error = block.get("error") or "unknown_error"
        issues.append(issue(
            "error",
            f"JSON-LD block did not parse ({error})",
            evidence=(block.get("snippet") or "")[:120],
        ))
    for row in find_schema_nodes(documents):
        node = row["node"]
        type_names = schema_type_names(node.get("@type"))
        row_issues = []
        for type_name in type_names:
            if type_name in DEPRECATED_TYPES:
                row_issues.append(issue("error", f"{type_name} is deprecated/restricted: {DEPRECATED_TYPES[type_name]}", evidence=row["path"]))
            if type_name in RESTRICTED_TYPES:
                row_issues.append(issue("warning", f"{type_name} has eligibility limits: {RESTRICTED_TYPES[type_name]}", evidence=row["path"]))
            for prop in _missing_required(type_name, node, row["path"]):
                row_issues.append(issue("error", f"{type_name} missing rich-result property '{prop}'", evidence=row["path"]))
        rows.append({"path": row["path"], "types": type_names, "issues": row_issues})
        issues.extend(row_issues)
    result = {
        "nodes": len(rows),
        "rows": rows,
        "issues": issues,
        "summary": {
            "errors": sum(1 for item in issues if item["severity"] == "error"),
            "warnings": sum(1 for item in issues if item["severity"] == "warning"),
            # Nodes carrying a type Google no longer shows a rich result for, or shows
            # only for some sites: what TECH-001 asks, apart from the other errors and
            # warnings this guard counts.
            "retired_types": sum(1 for row in rows if set(row["types"])
                                 & (set(DEPRECATED_TYPES) | set(RESTRICTED_TYPES))),
            "invalid_blocks": len(invalid_blocks or []),
        },
    }
    if invalid_blocks:
        result["truncated"] = True
        result["truncated_reason"] = (
            f"{len(invalid_blocks)} JSON-LD block(s) did not parse, so any type "
            "inside them was not classified"
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Warn about rich-result eligibility risks in JSON-LD")
    parser.add_argument("source", help="URL, HTML file, or JSON-LD file")
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument("--json", "-j", action="store_true", help="Output JSON")
    args = parser.parse_args()
    args.source = read_source(args.source)
    documents, meta = extract_schema_documents(args.source, timeout=args.timeout)
    result = guard_rich_results(documents, meta.get("invalid_blocks"))
    result.update({"source": args.source, "final_url": meta["final_url"],
                   "fetch_error": (meta.get("fetch") or {}).get("error"),
                   "fetch_error_kind": (meta.get("fetch") or {}).get("error_kind")})
    lines = [
        f"Rich results guard for {args.source}",
        f"Nodes: {result['nodes']}  Errors: {result['summary']['errors']}  "
        f"Warnings: {result['summary']['warnings']}  "
        f"Invalid blocks: {result['summary']['invalid_blocks']}",
    ] + [f"[{item['severity']}] {item['message']} {item.get('evidence') or ''}" for item in result["issues"][:30]]
    print_json_or_text(result, args.json, lines)


if __name__ == "__main__":
    from lib.utf8_streams import utf8_streams
    utf8_streams()
    from lib.typed_credential import credentials_beside_argv
    credentials_beside_argv()
    main()
