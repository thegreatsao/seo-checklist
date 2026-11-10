#!/usr/bin/env python3
"""Accessibility checks with direct SEO/UX impact."""

from __future__ import annotations

from lib import python_floor  # noqa: F401

import argparse
import json
import re

from seo_common import load_html, parse_html


# Inputs never rendered, so never named.
UNRENDERED_INPUT_TYPES = frozenset({"hidden"})
# Inputs whose name is their own text, not a label (HTML-AAM): `submit` and `reset`
# have a default caption when `value` is absent, `button` has none; `image` is named by
# its `alt` (WCAG H36), which F15 batch 6 reads instead of skipping all four.
DEFAULT_CAPTION_INPUT_TYPES = frozenset({"submit", "reset"})
VALUE_NAMED_INPUT_TYPES = frozenset({"submit", "reset", "button"})


def _text(tag) -> str:
    """A label's own text: what it says, not what the controls inside it hold, with an
    image's `alt` read as its text (review round 1: an icon label named nothing)."""
    if (tag.get("aria-label") or "").strip():
        return tag["aria-label"].strip()
    parts = []
    for piece in tag.descendants:
        if isinstance(piece, str):
            if not piece.find_parent(["select", "textarea", "option", "script", "style"]):
                parts.append(str(piece))
        elif piece.name == "img" and (piece.get("alt") or "").strip():
            parts.append(piece["alt"])
    return " ".join(parts).strip()


def accessible_name(field, soup) -> str:
    """The field's accessible name, or "" (F15, TE-180's ruling): `aria-labelledby`
    resolved to the text of the elements it names, an empty or blank attribute or
    label being no name, and image and button inputs named by their `alt` or value."""
    ids = (field.get("aria-labelledby") or "").split()
    if ids:
        named = " ".join(_text(target) for target in
                         (soup.find(id=ref) for ref in ids) if target is not None).strip()
        if named:
            return named
    if (field.get("aria-label") or "").strip():
        return field["aria-label"].strip()
    kind = (field.get("type") or "").lower() if field.name == "input" else ""
    if kind == "image":
        if (field.get("alt") or "").strip():
            return field["alt"].strip()
    elif kind in VALUE_NAMED_INPUT_TYPES:
        if field.has_attr("value"):
            if field["value"].strip():
                return field["value"].strip()
        elif kind in DEFAULT_CAPTION_INPUT_TYPES:
            return kind.capitalize()
    else:
        field_id = field.get("id")
        labels = list(field.find_parents("label", limit=1))
        if field_id:
            labels += soup.find_all("label", attrs={"for": field_id})
        for label in labels:
            if _text(label):
                return _text(label)
    return (field.get("title") or "").strip()


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
    # A field's name can come from aria-labelledby, aria-label, a label[for] or a
    # <label> wrapping it, title, and for image and button inputs their alt or value
    # (`accessible_name`). Hidden inputs are not rendered; the score above still counts
    # fields the old way.
    unnamed_fields = sum(
        1 for field in inputs
        if not (field.name == "input"
                and (field.get("type") or "").lower() in UNRENDERED_INPUT_TYPES)
        and not accessible_name(field, soup))
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
        "fetch_error_kind": fetched.get("error_kind"),
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
    from lib.utf8_streams import utf8_streams
    utf8_streams()
    from lib.typed_credential import credentials_beside_argv
    credentials_beside_argv()
    main()
