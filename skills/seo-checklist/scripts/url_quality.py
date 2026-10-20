#!/usr/bin/env python3
"""Analyze URL hygiene and variant risks."""

from __future__ import annotations

from lib import python_floor  # noqa: F401

import argparse
import json
import re
from collections import Counter, defaultdict
from urllib.parse import parse_qs, urlparse

from seo_common import read_urls


FACET_PARAMS = {"sort", "filter", "color", "size", "brand", "price", "min_price", "max_price", "page", "view", "category", "tag"}
TRACKING_PREFIXES = ("utm_", "fbclid", "gclid", "msclkid")


# basis: convention — 115 characters, present at import (F11). Past it a URL is not
#  `short` (AR-147), carries `long_url` (AR-155) and loses 12 points of CI-012's score.
#  No search engine publishes a URL length that costs anything: Google asks for a
#  simple structure and states no number, the sitemap protocol's limit is 2,048
#  characters and HTTP's recommended minimum support is 8,000 octets. A corpus of URLs
#  would show what lengths sites use, not which one loses a click, so the line is a
#  readability judgement. Moving it moves those three items for URLs near it
MAX_URL_CHARS = 115
# basis: convention — more than five path segments, present at import (F11): a proxy
#  for how deep a page sits, which is not click depth from the home page (that is the
#  crawl's `depth`). It decides AR-147, AR-155's `deep_path` and CI-012 the way
#  MAX_URL_CHARS does, and no corpus settles it for the same reason: segments are how a
#  site names its sections, and how many is too many is a readability call
MAX_PATH_SEGMENTS = 5
# basis: convention — at most two query parameters, the number AR-147's rule asserted
#  on `param_count` from import until 0.115.0, kept as a decision (F11). Two leaves a
#  page and a sort, say, and three is where a URL starts reading as a filtered view;
#  Google states no count. It decides AR-147 only (AR-155 flags any parameter)
MAX_SHORT_PARAMS = 2

def analyze_urls(urls: list[str]) -> dict:
    rows = []
    path_variants = defaultdict(list)
    for url in urls:
        parsed = urlparse(url)
        params = parse_qs(parsed.query, keep_blank_values=True)
        path = parsed.path or "/"
        flags = []
        if len(url) > MAX_URL_CHARS:
            flags.append("long_url")
        if any(ch.isupper() for ch in path):
            flags.append("uppercase_path")
        if "_" in path:
            flags.append("underscore_in_path")
        if re.search(r"/(tag|category|author|page)/\d+/?$", path):
            flags.append("thin_archive_pattern")
        if len([seg for seg in path.split("/") if seg]) > MAX_PATH_SEGMENTS:
            flags.append("deep_path")
        if params:
            flags.append("has_parameters")
        if any(key.startswith(TRACKING_PREFIXES) for key in params):
            flags.append("tracking_parameters")
        if any(key in FACET_PARAMS for key in params):
            flags.append("facet_parameters")
        normalized_key = (parsed.netloc.lower().removeprefix("www."), path.lower().rstrip("/") or "/", tuple(sorted(params)))
        path_variants[normalized_key].append(url)
        # AR-147 is titled *Short*, and until 0.115.0 read only `param_count`, so a
        # 300-character URL with no query string passed it. Short is all three bounds.
        short = (len(url) <= MAX_URL_CHARS
                 and len([seg for seg in path.split("/") if seg]) <= MAX_PATH_SEGMENTS
                 and len(params) <= MAX_SHORT_PARAMS)
        rows.append({"url": url, "path": path, "param_count": len(params), "params": sorted(params), "flags": flags, "short": short, "score": max(0, 100 - 12 * len(flags))})

    variants = {str(key): vals for key, vals in path_variants.items() if len(vals) > 1}
    flag_counts = Counter(flag for row in rows for flag in row["flags"])
    return {"count": len(rows), "flag_counts": dict(flag_counts), "variant_groups": variants, "rows": rows}


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze URL quality")
    parser.add_argument("urls", nargs="*")
    parser.add_argument("--url-file")
    parser.add_argument("--json", "-j", action="store_true")
    args = parser.parse_args()
    result = analyze_urls(read_urls(args.urls, args.url_file))
    print(json.dumps(result, indent=2) if args.json else "\n".join(f"{r['score']}\t{','.join(r['flags']) or 'ok'}\t{r['url']}" for r in result["rows"]))


if __name__ == "__main__":
    from lib.utf8_streams import utf8_streams
    utf8_streams()
    from lib.typed_credential import credentials_beside_argv
    credentials_beside_argv()
    main()
