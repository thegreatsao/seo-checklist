#!/usr/bin/env python3
"""Audit font loading patterns that affect rendering and Core Web Vitals."""

from __future__ import annotations

import argparse
import json
import re
from urllib.parse import urlparse

from seo_common import (
    BeautifulSoup,
    fetch_url,
    html_parser,
    load_source,
    normalize_url,
    require_bs4,
    safe_get,
)


# basis: measured — corpus=tools/calibration/font-weight.json; date=2026-08-10; method=file byte distributions over pinned npm packages.
#  WOFF2 ceiling 34,520 bytes; retained in the empty 66,856-309,828 byte band. It does
#  not detect non-WOFF2 faces — the separate extension check below does.
LARGE_FONT_BYTES = 100_000

FONT_EXTENSIONS = (".woff2", ".woff", ".ttf", ".otf", ".eot")


def _font_format(url: str) -> str:
    path = urlparse(url).path.lower()
    for ext in FONT_EXTENSIONS:
        if path.endswith(ext):
            return ext.lstrip(".")
    return ""


def _extract_font_faces(css: str) -> list[dict]:
    faces = []
    for block in re.findall(r"@font-face\s*{([^}]+)}", css or "", flags=re.I | re.S):
        urls = re.findall(r"""url\(["']?([^)"']+)["']?\)""", block, flags=re.I)
        display_match = re.search(r"font-display\s*:\s*([^;]+)", block, flags=re.I)
        family_match = re.search(r"font-family\s*:\s*([^;]+)", block, flags=re.I)
        faces.append({
            "family": family_match.group(1).strip(" '\"") if family_match else None,
            "font_display": display_match.group(1).strip() if display_match else None,
            "urls": urls,
        })
    return faces


def _record_font_faces(
    css: str,
    *,
    base_url: str,
    stylesheet_url: str | None,
    font_faces: list[dict],
    font_files: list[str],
    issues: list[dict],
) -> None:
    for face in _extract_font_faces(css):
        font_faces.append(face)
        for font_url in face["urls"]:
            font_files.append(normalize_url(font_url, base_url) if base_url else font_url)

        finding_url = {"url": stylesheet_url} if stylesheet_url else {}
        if not face["font_display"]:
            # The item is *Font loading does not block render*, and this is the
            # markup that makes it block: with no `font-display`, the browser
            # hides the text until the font arrives. The other findings in this
            # file cost a round trip or some bytes; this one costs the words on
            # the page, and it is what makes TECH-002's FAIL reachable.
            issues.append({
                "severity": "error",
                "message": "@font-face missing font-display",
                "evidence": face.get("family"),
                **finding_url,
            })
        elif face["font_display"].lower() not in ("swap", "optional", "fallback"):
            issues.append({
                "severity": "info",
                "message": "font-display may delay text rendering",
                "evidence": face["font_display"],
                **finding_url,
            })


def audit(source: str, fetch_fonts: bool = False, timeout: int = 15) -> dict:
    html, url, fetched = load_source(source, timeout=timeout)
    require_bs4()
    soup = BeautifulSoup(html or "", html_parser())
    issues = []

    preloads = []
    preconnects = []
    stylesheets = []
    font_files = []
    font_faces = []

    for link in soup.find_all("link"):
        rel = " ".join(link.get("rel") or []).lower()
        href = link.get("href") or ""
        href = normalize_url(href, url) if href and url else href
        if "preconnect" in rel:
            preconnects.append(href)
        if "stylesheet" in rel:
            stylesheets.append(href)
        if "preload" in rel and (link.get("as") == "font" or _font_format(href)):
            preloads.append({
                "href": href,
                "type": link.get("type"),
                "crossorigin": link.has_attr("crossorigin"),
            })
            if not link.has_attr("crossorigin"):
                issues.append({"severity": "warning", "message": "Preloaded font is missing crossorigin", "url": href})
        if _font_format(href):
            font_files.append(href)

    for style in soup.find_all("style"):
        _record_font_faces(
            style.get_text() or "",
            base_url=url,
            stylesheet_url=None,
            font_faces=font_faces,
            font_files=font_files,
            issues=issues,
        )

    for href in dict.fromkeys(stylesheets):
        try:
            response = safe_get(href, timeout=timeout)
            response.raise_for_status()
        except Exception as exc:  # noqa: BLE001 — unreadable CSS is audit evidence
            issues.append({
                "severity": "warning",
                "message": "Stylesheet could not be fetched",
                "url": href,
                "evidence": str(exc)[:200],
            })
            continue
        _record_font_faces(
            response.text,
            base_url=response.url,
            stylesheet_url=href,
            font_faces=font_faces,
            font_files=font_files,
            issues=issues,
        )

    rows = []
    for font_url in sorted(set(font_files)):
        row = {
            "url": font_url,
            "format": _font_format(font_url),
            "preloaded": any(preload["href"] == font_url for preload in preloads),
            "status": None,
            "content_length": None,
            "cache_control": None,
        }
        if fetch_fonts and font_url.startswith(("http://", "https://")):
            head = fetch_url(font_url, method="HEAD", timeout=timeout)
            row["status"] = head.get("status")
            headers = head.get("headers", {})
            length = headers.get("content-length")
            row["content_length"] = int(length) if length and length.isdigit() else None
            row["cache_control"] = headers.get("cache-control")
            if row["content_length"] and row["content_length"] > LARGE_FONT_BYTES:
                issues.append({"severity": "warning", "message": "Large font file", "url": font_url, "evidence": f"{row['content_length']} bytes"})
        if row["format"] and row["format"] != "woff2":
            issues.append({"severity": "info", "message": "Font is not WOFF2", "url": font_url, "evidence": row["format"]})
        rows.append(row)

    if stylesheets and not preconnects:
        third_party_css = [href for href in stylesheets if href.startswith(("http://", "https://")) and url and urlparse(href).netloc != urlparse(url).netloc]
        if third_party_css:
            issues.append({"severity": "info", "message": "Third-party stylesheet without preconnect", "url": third_party_css[0]})

    return {
        "url": url or source,
        "font_file_count": len(rows),
        "font_face_count": len(font_faces),
        "preload_count": len(preloads),
        "preconnect_count": len(preconnects),
        "issues": issues,
        "fonts": rows,
        "font_faces": font_faces,
        "fetch_error": fetched.get("error"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit font loading for FOIT/FOUT and CWV risk")
    parser.add_argument("source", help="URL or local HTML file")
    parser.add_argument("--fetch-fonts", action="store_true", help="HEAD remote font files for size and cache headers")
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument("--json", "-j", action="store_true")
    args = parser.parse_args()

    result = audit(args.source, args.fetch_fonts, args.timeout)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Fonts: {result['font_file_count']}; @font-face: {result['font_face_count']}; issues: {len(result['issues'])}")


if __name__ == "__main__":
    from lib.utf8_streams import utf8_streams
    utf8_streams()
    main()
