#!/usr/bin/env python3
"""Audit image weight, responsive image usage, and broken-image risk.

An image is judged by everything the browser could choose for it, not by the
`<img>` tag alone. The distinction is the whole of MB-096 and MB-097: the way
this is supposed to be done is a `<picture>` that offers avif or webp through
`<source>` and keeps a png in the `<img>` for browsers that cannot take either,
so reading only the `<img>` sees the fallback, misses the modern format, and
fails the site precisely for following the recommendation.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from urllib.parse import urlparse

import site_crawl
from seo_common import (
    DEAD_FETCH_ERROR_KINDS,
    fetch_url,
    likely_lcp_candidate,
    load_source,
    parse_html,
    same_host,
)


MODERN_FORMATS = {"avif", "webp"}
RASTER_FORMATS = {"jpg", "jpeg", "png", "gif"}
# A `<source>` declares its format twice over, in `type` and in its URLs, and the
# two disagree often enough to be worth reading both: `type` is what the browser
# actually dispatches on, and a CDN URL with no extension has nothing else.
MODERN_MIME = {f"image/{fmt}" for fmt in MODERN_FORMATS}

# basis: inherited — 250KB, present at import from Agentic-SEO-Skill. One of the five
#  numbers KNOWN-ISSUES §2 names, and until 0.13.0 it was not even a constant: an inline
#  `> 250_000` in the middle of a loop, which is why no inventory of thresholds could
#  find it. A number nothing can name is a number nobody can argue with
LARGE_IMAGE_BYTES = 250_000


def _needs_sizes(srcset: str | None) -> bool:
    """Does this `srcset` require a `sizes` attribute to be answerable?

    Only width descriptors do. `srcset="a.png 1x, a@2x.png 2x"` names candidates by
    device pixel ratio, the browser already knows its own, and `sizes` is ignored —
    so demanding one there reports a defect on correct markup. With `w` descriptors
    the browser has no way to know how wide the image will be laid out, defaults to
    `100vw`, and a phone can be handed the desktop file.
    """
    if not srcset:
        return False
    return any(part.strip().endswith("w")
               and part.strip().rsplit(" ", 1)[-1][:-1].isdigit()
               for part in srcset.split(",") if " " in part.strip())

# A crawl can contain one query-stringed tracking pixel per page. The site-wide
# audit bounds distinct image requests just as broken_links.py bounds link requests,
# and reports the part it did not check.
# basis: inherited — 200 distinct image URLs, present at import. MD-187 is `high`
#  and passes when `broken_image_count` is 0, so the cap decides that verdict: the
#  images past it are exactly the ones that could have failed it.
DEFAULT_MAX_IMAGES = 200


def _extension(src: str) -> str:
    return os.path.splitext(urlparse(src).path)[1].lower().lstrip(".")


def _modern_sources(sources: list[dict]) -> list[str]:
    """The `<source>` formats in this `<picture>` that count as modern."""
    found = []
    for source in sources or []:
        if source.get("type") in MODERN_MIME:
            found.append(source["type"].split("/", 1)[1])
            continue
        for url in source.get("urls") or []:
            ext = _extension(url)
            if ext in MODERN_FORMATS:
                found.append(ext)
                break
    return found


def _local_size(src: str, html_source: str) -> int | None:
    if src.startswith(("http://", "https://", "data:")):
        return None
    base = Path(html_source).resolve().parent if Path(html_source).exists() else Path.cwd()
    candidate = (base / src.lstrip("/")).resolve()
    try:
        if candidate.is_file():
            return candidate.stat().st_size
    except OSError:
        return None
    return None


def _classify_image(url: str, result: dict, timeout: int) -> tuple[str, dict | None]:
    """Return broken/fine/unchecked, confirming ambiguous HEAD responses once."""
    error_kind = result.get("error_kind")
    if error_kind in DEAD_FETCH_ERROR_KINDS:
        return "broken", None
    status = result.get("status")
    if status in (404, 410):
        return "broken", None
    if status in (401, 403, 405):
        confirmation = fetch_url(
            url,
            method="GET",
            timeout=timeout,
            extra_headers={"Range": "bytes=0-0"},
        )
        confirmed_kind = confirmation.get("error_kind")
        confirmed_status = confirmation.get("status")
        if confirmed_kind in DEAD_FETCH_ERROR_KINDS:
            return "broken", confirmation
        if isinstance(confirmed_status, int) and confirmed_status // 100 in (2, 3):
            return "fine", confirmation
        if confirmed_status in (401, 403, 404, 405, 410):
            return "broken", confirmation
        return "unchecked", confirmation
    if isinstance(status, int) and status // 100 in (2, 3):
        return "fine", None
    return "unchecked", None


def _check_image(url: str, timeout: int) -> tuple[str, dict, dict | None]:
    head = fetch_url(url, method="HEAD", timeout=timeout)
    state, confirmation = _classify_image(url, head, timeout)
    return state, head, confirmation


def audit(source: str, fetch_images: bool = False, timeout: int = 15) -> dict:
    html, url, fetched = load_source(source, timeout=timeout)
    parsed = parse_html(html, url)
    images = []
    issues = []
    checks = []
    skipped_no_source = 0

    for index, img in enumerate(parsed["images"]):
        src = img.get("src") or ""
        ext = _extension(src)
        sources = img.get("picture_sources") or []
        modern_sources = _modern_sources(sources)
        # An `<img>` with no `src`, no `srcset` and no `<picture>` source is not an
        # image the browser will ever load — it is broken markup, and grading it as
        # "not responsive, not a modern format" reports two image defects for a page
        # that has no image there. `image_inventory.py` has always skipped these and
        # counted them as `skipped_no_src`; this file graded them, so one page could
        # be NO_DATA for the four items over that script and FAIL for MB-096 and
        # MD-189 over this one. Two scripts, one page, opposite answers.
        if not src and not img.get("srcset") and not sources:
            skipped_no_source += 1
            continue
        likely_lcp = likely_lcp_candidate(img, index)
        row = {
            "src": src,
            "format": ext,
            "width": img.get("width"),
            "height": img.get("height"),
            "loading": img.get("loading"),
            "fetchpriority": img.get("fetchpriority"),
            "srcset": bool(img.get("srcset")),
            "sizes": bool(img.get("sizes")),
            # Width descriptors anywhere the browser may choose from — the `<img>`
            # itself or any `<source>` above it — with no `sizes` on the element
            # carrying them. See `_needs_sizes`: an `x`-descriptor srcset without
            # `sizes` is correct markup and used to be reported as a defect.
            "sizes_required_and_absent": (
                (_needs_sizes(img.get("srcset")) and not img.get("sizes"))
                or any(_needs_sizes(s.get("srcset")) and not s.get("sizes")
                       for s in sources)),
            # Kept apart from `srcset` and `format` rather than folded into them.
            # "This img declares a srcset" and "a sibling source does" are different
            # facts about the markup, and a reader handed a fix list needs to know
            # which one is true before editing anything.
            "picture_source_count": len(sources),
            "picture_srcset": any(s.get("srcset") for s in sources),
            "picture_modern_formats": modern_sources,
            "likely_lcp_candidate": likely_lcp,
            "status": None,
            "content_length": _local_size(src, source),
            "content_type": None,
        }
        # What the browser can actually end up with, which is what both items are
        # about. The `img` is the fallback in a `<picture>`, not the answer.
        row["responsive"] = row["srcset"] or row["picture_srcset"]
        row["modern_format"] = ext in MODERN_FORMATS or bool(modern_sources)
        if fetch_images and src.startswith(("http://", "https://")):
            state, head, confirmation = _check_image(src, timeout)
            checks.append((row, state, head, confirmation))
            row["status"] = head.get("status")
            headers = head.get("headers", {})
            length = headers.get("content-length")
            row["content_length"] = int(length) if length and length.isdigit() else None
            row["content_type"] = headers.get("content-type")

        # Deferring the largest paint is the one finding in this file that is a defect
        # on every site and in every layout: the browser is told to wait for the image
        # the page is judged on. Everything else here is advice whose weight depends
        # on the page, which is why they stay `warning` and `info` — and why, before
        # 0.50.0, MD-185's FAIL was unreachable on every site there has ever been.
        if likely_lcp and row["loading"] == "lazy":
            issues.append({"severity": "error", "message": "Likely LCP image is lazy-loaded", "url": src})
        if likely_lcp and row["fetchpriority"] != "high":
            issues.append({"severity": "info", "message": "Likely LCP image lacks fetchpriority=high", "url": src})
        if ext in RASTER_FORMATS and not modern_sources:
            issues.append({"severity": "info", "message": "Consider AVIF/WebP for raster image", "url": src, "evidence": ext})
        if not row["responsive"]:
            issues.append({"severity": "info", "message": "Image has no srcset", "url": src})
        if row["sizes_required_and_absent"]:
            issues.append({"severity": "info", "message": "Responsive image has srcset but no sizes", "url": src})
        if row["content_length"] and row["content_length"] > LARGE_IMAGE_BYTES:
            issues.append({"severity": "warning", "message": "Large image transfer size", "url": src, "evidence": f"{row['content_length']} bytes"})
        images.append(row)

    known_bytes = sum(row["content_length"] or 0 for row in images)
    # A structured count for "Fix Broken Images", emitted only when a status or a
    # definitive dead-network result was collected. Reporting 0 broken because
    # nothing was learned is the difference between "no broken images" and "we did
    # not look": the key is absent instead, which the runner reads as NO_DATA.
    checked = [row for row in images if isinstance(row.get("status"), int)]
    broken = [row for row, state, _head, _confirmation in checks
              if state == "broken"]
    unchecked = [row for row, state, _head, _confirmation in checks
                 if state == "unchecked"]
    out = {
        "url": url or source,
        "image_count": len(images),
        # Reported rather than swallowed, and named as `image_inventory.py` names it:
        # a page whose only `<img>` has nothing to load is now undecided by both
        # scripts, and a reader who wants to know why has the count.
        "skipped_no_src": skipped_no_source,
        "images_status_checked": len(checked),
        "unchecked_image_count": len(unchecked),
        "known_image_bytes": known_bytes if fetch_images or any(row["content_length"] for row in images) else None,
        # The same two counts restricted to the `<img>` tag, which is what these
        # used to mean. Kept because they are the honest way to say "the fallback
        # is a png and that is fine": dropping them would leave no way to tell a
        # `<picture>` serving webp from an `<img src="x.webp">`.
        "modern_format_on_img_count": sum(1 for row in images
                                          if row["format"] in MODERN_FORMATS),
        "srcset_on_img_count": sum(1 for row in images if row["srcset"]),
        "picture_count": sum(1 for row in images if row["picture_source_count"]),
        "issues": issues,
        "images": images,
        # Said as well as acted on. Withholding the clean count by omitting the key
        # covers the PASS; this covers the other half, which omitting cannot reach:
        # when something *was* found broken the count is emitted and is a floor, and
        # the runner needs the flag to say so beside the FAIL. `broken_links.py` sets
        # it for the same pair of reasons; this script was doing only one of them.
        "truncated": bool(unchecked),
        "fetch_error": fetched.get("error"),
    }
    # An image-free page is not a page serving unresponsive, legacy-format images.
    # Omit these verdict inputs so a sampled page with nothing to optimize is
    # undecided and pages that actually contain images decide the site-level item.
    if images:
        out["modern_format_count"] = sum(1 for row in images
                                          if row["modern_format"])
        out["responsive_count"] = sum(1 for row in images if row["responsive"])
        # An image offering width-described candidates without a `sizes` attribute
        # gives the browser no rule for choosing between them, so it assumes the
        # image is as wide as the viewport — which is how a page with responsive
        # markup still ships the desktop file to a phone. Derivable from markup
        # alone, so it is emitted whenever there are images at all.
        out["srcset_without_sizes_count"] = sum(
            1 for row in images if row["sizes_required_and_absent"])
    # Emitted only when transfer sizes were actually learned. A page nobody fetched
    # has `content_length: None` on every row, and counting those as "not large"
    # would report a clean weight for a page nothing was measured on — the same
    # asymmetry `broken_image_count` argues below.
    if out["known_image_bytes"] is not None:
        out["large_image_count"] = sum(
            1 for row in images
            if (row["content_length"] or 0) > LARGE_IMAGE_BYTES)
    # Present only when usable evidence exists. Emitting 0 — or None, which an
    # equality assertion reads as a failure rather than as silence — would turn "we
    # did not look" into a verdict either way. An absent key is NO_DATA by design.
    #
    # `broken or not unchecked` is the second half, and it is the asymmetry that
    # makes this safe to apply without a threshold. A hundred images where
    # ninety-nine time out and one answers 200 used to report `broken_image_count:
    # 0` — "no broken images" drawn from one image out of a hundred. The share that
    # ought to trigger that has no basis in this corpus, so this does not use one: a
    # count of zero over an incomplete check is not a count of the page at any share,
    # while a count above zero is a real defect that a timeout elsewhere cannot undo.
    # So the clean answer is withheld whenever anything went unchecked, and the
    # failing answer always stands.
    if (checked or broken) and (broken or not unchecked):
        out["broken_image_count"] = len(broken)
        # `row["src"]`, not `row["url"]` — the row has no "url" key, so this raised
        # KeyError and killed the whole script. It could only fire on a page that
        # actually had a broken image, which is the one page MD-187 exists for: any
        # site with no broken images ran fine and reported 0, so the crash stayed
        # invisible until a fixture was built with a 404 image in it.
        out["broken_images"] = [row["src"] for row in broken]
    return out


def audit_inventory(site_url: str, inventory_path: str, timeout: int = 15,
                    max_images: int = DEFAULT_MAX_IMAGES) -> dict:
    """Check every distinct image URL recorded by the shared crawl once."""
    inventory = site_crawl.inventory_for(site_url, inventory_path)
    pages = inventory.get("pages") or {}
    references: dict[str, list[str]] = {}
    total_references = 0
    pages_with_images = 0
    for page in pages.values():
        page_images = page.get("images") or []
        if page_images:
            pages_with_images += 1
        total_references += len(page_images)
        page_url = page.get("url") or page.get("final_url") or ""
        for image_url in page_images:
            referring_pages = references.setdefault(image_url, [])
            if page_url and page_url not in referring_pages:
                referring_pages.append(page_url)

    ordered = list(references)
    ordered.sort(key=lambda image_url: not same_host(site_url, image_url))
    dropped = 0
    if max_images and len(ordered) > max_images:
        dropped = len(ordered) - max_images
        ordered = ordered[:max_images]

    broken = []
    broken_urls = []
    unchecked = 0
    usable_evidence = False
    for image_url in ordered:
        state, head, _confirmation = _check_image(image_url, timeout)
        if isinstance(head.get("status"), int) or state == "broken":
            usable_evidence = True
        if state == "unchecked":
            unchecked += 1
        elif state == "broken":
            broken_urls.append(image_url)
            broken.append({
                "url": image_url,
                "status": head.get("status"),
                "error_kind": head.get("error_kind"),
                "pages": references[image_url],
            })

    out = {
        "url": inventory.get("site") or site_url,
        "summary": {
            "pages_with_images": pages_with_images,
            "pages_without_images": len(pages) - pages_with_images,
            "images": total_references,
            "unique_images": len(references),
            "images_checked": len(ordered),
            "unchecked_images": unchecked,
            "images_dropped": dropped,
        },
        "broken": broken,
        # Three ways this answer can rest on less than the site: the crawl was
        # capped, an image answered nothing, or an image sat past `--max-images` and
        # was never asked. The first was already here; the other two were acting on
        # the clean count below and saying nothing beside a failing one.
        "truncated": bool(inventory.get("summary", {}).get("truncated")
                          or unchecked or dropped),
        "fetch_error": inventory.get("fetch_error"),
    }
    # The same rule on the whole-site path, where there are two ways to fall short
    # of the site: an image that answered nothing, and an image past `--max-images`
    # that was never asked. Both leave "no broken images" a claim about the part
    # that answered, so both withhold it; a broken image found stands either way.
    if usable_evidence and (broken or not (unchecked or dropped)):
        out["broken_image_count"] = len(broken)
        out["broken_images"] = broken_urls
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit image weight and responsive-image performance")
    parser.add_argument("source", help="URL or local HTML file")
    parser.add_argument("--inventory", default="",
                        help="crawl inventory from site_crawl.py: check images "
                             "across the whole site")
    parser.add_argument("--fetch-images", action="store_true", help="HEAD remote images for status and byte size")
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument("--max-images", type=int, default=DEFAULT_MAX_IMAGES,
                        help=f"Maximum distinct image URLs to check, same-host "
                             f"first; 0 for no limit (default: {DEFAULT_MAX_IMAGES})")
    parser.add_argument("--json", "-j", action="store_true")
    args = parser.parse_args()

    if args.inventory:
        result = audit_inventory(args.source, args.inventory, args.timeout,
                                 args.max_images)
    else:
        result = audit(args.source, args.fetch_images, args.timeout)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if args.inventory:
            summary = result["summary"]
            print(f"Images: {summary['images']} references, "
                  f"{summary['unique_images']} unique; "
                  f"broken: {result.get('broken_image_count', 'n/a')}; "
                  f"unchecked: {summary['unchecked_images']}; "
                  f"dropped: {summary['images_dropped']}")
        else:
            print(f"Images: {result['image_count']}; responsive: "
                  f"{result.get('responsive_count', 'n/a')}; "
                  f"issues: {len(result['issues'])}")


if __name__ == "__main__":
    main()
