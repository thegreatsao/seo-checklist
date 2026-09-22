#!/usr/bin/env python3
"""Inventory images for SEO, accessibility, and performance signals."""

from __future__ import annotations

import argparse
import json
import os
import re
from urllib.parse import urlparse

from seo_common import (fetch_url, likely_lcp_candidate, load_html,
                        parse_html)

# `openspec/specs/registry/` REG-6, A.3 and A.9. CI-016 and MD-186 are titled
# *Provide Meaningful Alt Text* and asserted `missing_alt == 0`, which is a different
# question: measured at 0.105.0, a page whose five images read `image1.jpg`,
# `IMG_0042`, `untitled`, `photo` and `x` scored exactly the same as one carrying five
# real descriptions — both PASS. The item could not tell them apart, and A.3 had said
# so in prose since the appendix was written.
#
# These patterns are deliberately conservative. A checker that accuses a site which has
# done the work is worse than one that misses a bad alt, because the first teaches an
# operator to stop reading the report. Each rule below is a form that cannot describe
# an image whatever the image is.
#
# `alt=""` is NOT here and must never be: an empty alt is the *correct* markup for a
# decorative image, which is what CI-016's own `fix` text asks for. It is counted
# separately as `empty_alt` and is not a defect.
PLACEHOLDER_ALT_PATTERNS = (
    # A filename, with or without its extension: "photo-3.jpg", "hero_02.png".
    r"^[\w %()\-]+\.(?:jpe?g|png|gif|webp|avif|svg|bmp|tiff?|ico)$",
    # A camera or asset-pipeline stub, optionally numbered: "IMG_0042", "DSC00123",
    # "untitled", "image 3", "screenshot", "banner".
    r"^(?:img|image|images|photo|photos|pic|picture|pictures|dsc|dscn|scan|"
    r"screenshot|screen[\s_-]?shot|untitled|unnamed|file|asset|banner|thumb|"
    r"thumbnail|placeholder|default|temp|test)[\s_\-]*\d*$",
    # Nothing a reader could read: not one letter anywhere. Covers "123", "--", "1 / 4".
    r"^[\W\d_]+$",
)

# basis: convention — three characters. Below it an alt cannot be a description: "x"
# and "ok" are the measured cases, and three is the shortest string that could
# plausibly be a word at all. Nothing external sets this and no corpus was sampled for
# it, so it is a convention and says so rather than borrowing a standard's authority.
# It is a floor on *length only*: a three-character alt is not thereby meaningful, it
# is merely not refused on this ground.
MIN_MEANINGFUL_ALT = 3

_PLACEHOLDER_ALT = tuple(re.compile(pattern, re.IGNORECASE)
                         for pattern in PLACEHOLDER_ALT_PATTERNS)


def alt_is_placeholder(alt, src: str = "") -> bool:
    """True when `alt` is present and non-empty but describes nothing.

    `None` is a missing alt and `""` is a correct decorative one; neither is this
    script's business here, and both are counted elsewhere. What this names is the
    third case the registry had no word for — an alt that satisfies *"has an alt"*
    and fails *"meaningful"*.
    """
    if not isinstance(alt, str):
        return False
    text = alt.strip()
    if not text:
        return False
    if len(text) < MIN_MEANINGFUL_ALT:
        return True
    if any(pattern.match(text) for pattern in _PLACEHOLDER_ALT):
        return True
    # The alt repeats the file it points at, with or without the extension. Kept
    # apart from the patterns above because it is a comparison, not a shape.
    name = os.path.basename(urlparse(src or "").path)
    if name:
        stem = os.path.splitext(name)[0]
        if text.casefold() in {name.casefold(), stem.casefold()}:
            return True
    return False


def inventory(source: str, fetch_images: bool = False, timeout: int = 15) -> dict:
    html, url, fetched = load_html(source, timeout=timeout)
    parsed = parse_html(html, url)
    rows = []
    issues = []
    skipped_no_src = 0
    for idx, img in enumerate(parsed["images"]):
        src = (img.get("src") or "").strip()
        if not src:
            skipped_no_src += 1
            continue
        ext = os.path.splitext(urlparse(src).path)[1].lower().lstrip(".")
        alt = img.get("alt")
        row = {
            "src": src,
            "alt": alt,
            "has_alt": alt is not None,
            "empty_alt": alt == "",
            "placeholder_alt": alt_is_placeholder(alt, src),
            "width": img.get("width"),
            "height": img.get("height"),
            "is_responsive_fill": bool(img.get("is_responsive_fill")),
            "loading": img.get("loading"),
            "srcset": bool(img.get("srcset")),
            "sizes": bool(img.get("sizes")),
            "format": ext,
            "likely_lcp_candidate": likely_lcp_candidate(img, idx),
            "native_source": bool(img.get("native_source")),
            "deferred_source": bool(img.get("deferred_source")),
            "discoverable": bool(img.get("native_source")),
        }
        if not row["has_alt"]:
            issues.append({"severity": "warning", "message": "Image missing alt text", "url": src})
        if not row["is_responsive_fill"] and (not row["width"] or not row["height"]):
            issues.append({"severity": "info", "message": "Image missing explicit dimensions", "url": src})
        if row["likely_lcp_candidate"] and row["loading"] == "lazy":
            issues.append({"severity": "warning", "message": "Likely LCP image is lazy-loaded", "url": src})
        if fetch_images and src.startswith("http"):
            head = fetch_url(src, method="HEAD", timeout=timeout)
            row["status"] = head.get("status")
            row["content_length"] = head.get("headers", {}).get("content-length")
            row["content_type"] = head.get("headers", {}).get("content-type")
        rows.append(row)
    # Native `loading=lazy` with an ordinary `src` remains discoverable; only a
    # JS-deferred source with no native alternative answers CN-054 adversely. LCP
    # performance is graded separately by image_weight_audit.py for MD-185, so this
    # inventory does not retain a second, unread count for it.
    undiscoverable_lazy = sum(1 for r in rows
                              if r["deferred_source"] and not r["discoverable"])
    missing_alt = sum(1 for r in rows if not r["has_alt"])
    empty_alt = sum(1 for r in rows if r["empty_alt"])
    placeholder_alt = sum(1 for r in rows if r["placeholder_alt"])
    out = {"url": url or source,
           "empty_alt": empty_alt, "skipped_no_src": skipped_no_src,
           "summary": {"images": len(rows),
                       "empty_alt": empty_alt, "skipped_no_src": skipped_no_src},
           "issues": issues, "images": rows, "fetch_error": fetched.get("error")}
    # A page with no images is not a page whose images are missing, unlabelled or
    # undiscoverable. These three are the only fields the registry reads as a verdict
    # — MD-184 asserts `count gte 1`, CI-016 and MD-186 assert `missing_alt eq 0`,
    # CN-054 asserts `summary.lazy_lcp_candidates eq 0` — and emitted as 0 they turn
    # "there was nothing here to judge" into a verdict: a FAIL for the first and a
    # free PASS for the other three. An absent key is NO_DATA, so a sampled page with
    # no images stays undecided and the pages that have images decide the item.
    #
    # `image_weight_audit.py:152` already does exactly this with `responsive_count`
    # and `modern_format_count`, and the two scripts disagreeing on the same two
    # fixture pages is how this was found: MD-189 was declared FAIL, came back PASS,
    # and its neighbour MD-184 failed the exemplary fixture. The descriptive counts
    # above stay at 0 — `summary.images` is a fact about the page, not a verdict.
    if rows:
        out["count"] = len(rows)
        out["missing_alt"] = missing_alt
        out["placeholder_alt"] = placeholder_alt
        # What CI-016 and MD-186 ask, in one leaf, because the registry gives a rule
        # one operator over one path. An image with no alt and an image whose alt reads
        # `IMG_0042` both fail *Provide Meaningful Alt Text*, and the two used to be
        # one number and one blind spot. This can only be greater than or equal to
        # `missing_alt`, so nothing that failed before passes now.
        out["alt_not_meaningful"] = missing_alt + placeholder_alt
        out["summary"]["lazy_lcp_candidates"] = undiscoverable_lazy
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Inventory images on a page")
    parser.add_argument("source", help="URL or local HTML file")
    parser.add_argument("--fetch-images", action="store_true")
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument("--json", "-j", action="store_true")
    args = parser.parse_args()
    result = inventory(args.source, args.fetch_images, args.timeout)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        lines = [f"{'missing-alt' if not r['has_alt'] else 'empty-alt' if r['empty_alt'] else 'ok'}\t{r['src']}"
                 for r in result["images"]]
        lines.append(f"empty-alt-count\t{result['empty_alt']}")
        lines.append(f"skipped-no-src\t{result['skipped_no_src']}")
        print("\n".join(lines))


if __name__ == "__main__":
    main()
