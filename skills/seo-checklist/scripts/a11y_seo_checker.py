#!/usr/bin/env python3
"""Accessibility checks with direct SEO/UX impact."""

from __future__ import annotations

import argparse
import json
import re

from seo_common import load_html, parse_html


# HTML input types that are either not rendered (`hidden`) or whose
#  accessible name comes from their own value or alt attribute (`submit`, `button`,
#  `reset`, `image`), per the HTML-AAM accessible-name computation.
UNLABELLED_INPUT_TYPES = frozenset({"hidden", "submit", "button", "reset", "image"})


def checker(source: str, timeout: int = 15) -> dict:
    html, url, fetched = load_html(source, timeout=timeout)
    parsed = parse_html(html, url)
    soup = parsed["soup"]
    issues = []
    h1_count = len(parsed["headings"]["h1"])
    if h1_count != 1:
        issues.append({"severity": "warning", "message": f"Expected one H1, found {h1_count}"})
    if not parsed.get("lang"):
        issues.append({"severity": "warning", "message": "Missing html lang attribute"})
    if not parsed.get("viewport"):
        issues.append({"severity": "warning", "message": "Missing viewport meta tag"})
    missing_alt = [img.get("src") or "" for img in soup.find_all("img") if img.get("alt") is None]
    for src in missing_alt[:25]:
        issues.append({"severity": "warning", "message": "Image missing alt attribute", "url": src})
    inputs = soup.find_all(["input", "select", "textarea"])
    labelled = 0
    for field in inputs:
        field_id = field.get("id")
        if field.get("aria-label") or field.get("aria-labelledby") or field.get("title"):
            labelled += 1
        elif field_id and soup.find("label", attrs={"for": field_id}):
            labelled += 1
    if inputs and labelled < len(inputs):
        issues.append({"severity": "warning", "message": f"{len(inputs) - labelled} form field(s) appear unlabeled"})
    if parsed["landmarks"]["main"] == 0:
        issues.append({"severity": "info", "message": "No <main> landmark found"})
    generic_anchors = [a.get_text(" ", strip=True) for a in soup.find_all("a", href=True) if re.fullmatch(r"(click here|read more|more|learn more)", a.get_text(" ", strip=True).lower())]
    if generic_anchors:
        issues.append({"severity": "info", "message": f"{len(generic_anchors)} generic link text instance(s)"})
    # Contrast is not measured here, and the key that pretended to is gone. Until
    # 0.101.0 this counted elements whose *inline* style named both a colour and a
    # background, and CN-036 asserted that count was zero. The name said
    # `inline_contrast_candidates` — candidates for a check nobody performed — but
    # the assertion read it as a verdict, so the item was anti-correlated with its
    # own title: #eeeeee on #ffffff set in a stylesheet is 1.1:1 and passed, while
    # #000000 on #ffffff written inline is 21:1 and failed. Contrast is a computed
    # value; it belongs with the other computed ones in `rendered_audit.py`, which
    # is where CN-036 now reads it.
    # TE-180 *Meet Accessibility (WCAG) Basics* asserted `score >= 80` until 0.117.0:
    # a hundred less eight per issue, so two level-A failures passed, while an H1 count
    # other than one — not a WCAG requirement — cost the same. It now counts the level-A
    # failures this HTML shows, each over its whole list rather than the capped issues:
    # an image with no alt (1.1.1), a form field with no accessible name (1.3.1, 4.1.2),
    # and no page language (3.1.1).
    #
    # A field's name can come from aria-label, aria-labelledby, title, a label[for], or
    # a <label> wrapping it. Hidden inputs are not rendered, and submit, button, reset
    # and image inputs take their name from their value or alt, so none of those needs
    # a label; the score above still counts them the old way.
    unnamed_fields = 0
    for field in inputs:
        if (field.name == "input"
                and (field.get("type") or "").lower() in UNLABELLED_INPUT_TYPES):
            continue
        field_id = field.get("id")
        if (field.get("aria-label") or field.get("aria-labelledby") or field.get("title")
                or field.find_parent("label")
                or (field_id and soup.find("label", attrs={"for": field_id}))):
            continue
        unnamed_fields += 1
    wcag_a = {"images_missing_alt": len(missing_alt),
              "unnamed_fields": unnamed_fields,
              "missing_lang": not parsed.get("lang")}
    return {
        "url": url or source,
        "wcag_a": wcag_a,
        "wcag_a_failures": (wcag_a["images_missing_alt"] + wcag_a["unnamed_fields"]
                            + int(wcag_a["missing_lang"])),
        "score": max(0, 100 - 8 * len(issues)),
        "checks": {
            "h1_count": h1_count,
            "lang": parsed.get("lang"),
            "viewport": bool(parsed.get("viewport")),
            "images_missing_alt": len(missing_alt),
            "form_controls": len(inputs),
            "labeled_controls": labelled,
            "landmarks": parsed["landmarks"],
        },
        "issues": issues,
        "fetch_error": fetched.get("error"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Check accessibility signals relevant to SEO")
    parser.add_argument("source", help="URL or local HTML file")
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument("--json", "-j", action="store_true")
    args = parser.parse_args()
    result = checker(args.source, args.timeout)
    print(json.dumps(result, indent=2) if args.json else f"Score: {result['score']} Issues: {len(result['issues'])}")


if __name__ == "__main__":
    main()
