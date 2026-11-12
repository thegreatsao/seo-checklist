#!/usr/bin/env python3
"""Audit font loading patterns that affect rendering and Core Web Vitals."""

from __future__ import annotations

from lib import python_floor  # noqa: F401

import argparse
import json
import re
from urllib.parse import urlparse

from lib.safe_http import NonStandardPort
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

FONT_EXTENSIONS = (".woff2", ".woff", ".ttf", ".otf", ".eot", ".ttc")

# A closed list of icon font families (F15, the owner's ruling 1 on batch 6's questions,
# 2026-11-11, widened by ruling 1 on batch 7's, 2026-11-12). An icon font hides glyphs,
# not words: Font Awesome ships `font-display: block` so a missing icon shows nothing
# rather than a stray letter. A family is an icon font when, lower-cased with everything
# but letters and digits dropped, it starts with one of these (`Font Awesome 6 Free`,
# `Material Icons Outlined`, `Genericons-Neue`), or is one of `WHOLE_NAME_ONLY` exactly.
# Each name is as the project's published CSS declares it. TECH-002's `measures`
# sentence names three and points here; an icon font not listed is read.
ICON_FONT_FAMILIES = (
    "fontawesome", "lineawesome", "materialicons", "materialsymbols", "glyphicons",
    "bootstrapicons", "dashicons", "ionicons", "eicons",
    # WooCommerce (`star`, `WooCommerce`), Divi (`ETmodules`)
    "star", "woocommerce", "etmodules",
    "materialdesignicons", "boxicons", "tablericons", "simplelineicons", "slick",
    "remixicon", "themify", "icofont", "typicons", "genericons", "foundationicons",
    "linearicons", "feather", "phosphor", "peicon7stroke", "eleganticons",
    # video.js, lightGallery, PrimeIcons, VS Code's codicons, Material Design Iconic Font,
    # and the Fontello and IcoMoon generators' default names (review round 1)
    "videojs", "lg", "primeicons", "codicon", "materialdesigniconic", "fontello", "icomoon",
    # Magento 2's Luma and Blank themes (review round 2)
    "lumaicons", "iconsblanktheme",
    # FlexSlider 2 (MetaSlider's default), feather-webfont's `feather-icons` (round 3)
    "flexslidericon", "feathericons")
# Words a text family can start with: a prefix `star` would take "Stardos Stencil".
WHOLE_NAME_ONLY = frozenset({"star", "slick", "feather", "lg"})


def icon_font(family: str | None) -> bool:
    key = re.sub(r"[^a-z0-9]", "", (family or "").lower())
    return any(key == name if name in WHOLE_NAME_ONLY else key.startswith(name)
               for name in ICON_FONT_FAMILIES)


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
            # A face whose `src` is only `local()` downloads nothing, so it hides no
            # text: next/font's size-adjusted fallback (review round 6). Nor does one
            # inlined whole as `data:` URIs: Swiper's `swiper-icons`, which Elementor
            # and Spectra bundle (F15 batch 7, review round 2).
            "local_only": (not urls and bool(re.search(r"\blocal\s*\(", block, re.I)))
                          or (bool(urls) and all(u.strip().lower().startswith("data:")
                                                 for u in urls)),
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
        if face["local_only"] or icon_font(face["family"]):
            continue
        display = re.sub(r"\s*!important\s*$", "", face["font_display"] or "",
                         flags=re.I).strip().lower()
        # `block` hides the text for up to three seconds, and `auto` is the browser's
        # default, which every major browser makes `block`: both are what a missing
        # value does (F15, TECH-002's ruling).
        if display in ("", "block", "auto"):
            # The item is *Font loading does not block render*, and this is the
            # markup that makes it block: with no `font-display`, the browser
            # hides the text until the font arrives. The other findings in this
            # file cost a round trip or some bytes; this one costs the words on
            # the page, and it is what makes TECH-002's FAIL reachable.
            issues.append({
                "severity": "error",
                "message": ("@font-face missing font-display" if not display else
                            f"@font-face font-display: {display} hides text until the "
                            f"font loads"),
                "evidence": face.get("family"),
                **finding_url,
            })
        elif display not in ("swap", "optional", "fallback"):
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
        if "stylesheet" in rel and href:   # no href, nothing to fetch (an aside)
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

    refused = []
    for href in dict.fromkeys(stylesheets):
        try:
            response = safe_get(href, timeout=timeout)
            response.raise_for_status()
        except Exception as exc:  # noqa: BLE001 — unreadable CSS is audit evidence
            if isinstance(exc, NonStandardPort):
                # Not the site's: the web-ports switch did not ask (HTTP-13). Its fonts
                # are unread, so a clean answer covers only the rest.
                refused.append(href)
                continue
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
            if head.get("error_kind") == "blocked":
                refused.append(font_url)    # its size is unread, not small
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
        "fetch_error_kind": fetched.get("error_kind"),
        "truncated": bool(refused),
        "truncated_reason": (f"{len(refused)} stylesheet(s) or font(s) refused by this "
                             f"audit's guard" if refused else None),
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
    from lib.typed_credential import credentials_beside_argv
    credentials_beside_argv()
    main()
