#!/usr/bin/env python3
"""Compare served HTML against a rendered-page artifact's DOM."""

from __future__ import annotations

import argparse
import json

from html_validator import rendered_document
from seo_common import load_html, parse_html


def summarize(html: str, url: str) -> dict:
    parsed = parse_html(html, url)
    return {
        "title": parsed["title"],
        "meta_description": parsed["meta_description"],
        "canonical": parsed["canonical"],
        "h1_count": len(parsed["headings"]["h1"]),
        "internal_link_count": len([link for link in parsed["links"]
              if url and link["href"].startswith(url.split("/", 3)[0] + "//"
                                                 + url.split("/")[2])]) if url.startswith("http") else len(parsed["links"]),
        # Compare everything the served and rendered documents declare.
        "schema_count": len(parsed["schema"]),
        "word_count": parsed["word_count"],
    }


def audit(source: str, timeout: int = 15, rendered_json: str | None = None) -> dict:
    raw_html, final_url, fetched = load_html(source, timeout=timeout)
    raw = summarize(raw_html, final_url or source)
    rendered_html = None
    if rendered_json is not None:
        rendered_html, render_error = rendered_document(rendered_json)
    else:
        render_error = "no rendered artifact provided"

    # A browser launched inside an audit fetches the page again — and its
    # subresources — behind the shared response cache's back, which is exactly what
    # the CI request-discipline gate forbids: one audited page, one fetch. It also
    # made this same page FAIL here on a measured 795-versus-953 word-count diff and
    # NO_DATA on every runner without Playwright. The rendered document therefore
    # comes only from the operator-supplied artifact.
    rendered = summarize(rendered_html, final_url) if rendered_html else None
    result = {
        "url": final_url or source,
        "raw": raw,
        "rendered": rendered,
        "render_error": render_error,
        "fetch_error": fetched.get("error"),
    }
    if rendered is not None:
        diffs = []
        for key in raw:
            if raw.get(key) != rendered.get(key):
                diffs.append({"field": key, "raw": raw.get(key), "rendered": rendered.get(key)})
        result["diffs"] = diffs
    # Match mobile_render_checker.py's `available: False` shape: when rendering did
    # not happen, omit its measurement so the runner reports NO_DATA rather than PASS.
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare raw HTML and rendered DOM SEO signals")
    parser.add_argument("source", help="URL or local HTML file")
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument("--rendered-json", help="Rendered-page artifact containing html")
    parser.add_argument("--json", "-j", action="store_true")
    args = parser.parse_args()
    result = audit(args.source, args.timeout, args.rendered_json)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        diff_count = len(result["diffs"]) if "diffs" in result else "unavailable"
        print(f"Diffs: {diff_count}; render_error={result['render_error']}")


if __name__ == "__main__":
    from lib.utf8_streams import utf8_streams
    utf8_streams()
    main()
