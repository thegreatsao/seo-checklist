#!/usr/bin/env python3
"""Check E-E-A-T signals in HTML content."""

from __future__ import annotations

import argparse
import json
import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from seo_common import (
    load_source,
    page_author_names,
    page_nodes,
    parse_html,
    primary_language,
    schema_values,
    under_foreign_credit,
    walk_json,
)


_TERMS_PATH = (Path(__file__).resolve().parent.parent / "resources" / "config" /
               "eeat-terms.json")

# The signal families the vocabulary file carries, named once. It was spelled out in four
# places until 0.116.0 added `contact`: CN-044 asks for a contact page and read
# `trust_links`, where an About, Privacy or Terms link counts, so a page with no contact
# route at all passed it.
CONCEPTS = ("credential", "first_hand", "policy", "trust", "privacy", "contact")
# The families a link can satisfy by its href as well as its text.
HREF_CONCEPTS = ("policy", "trust", "privacy", "contact")


def _load_terms() -> dict:
    """Load and validate the maintained vocabulary once, failing loudly on drift."""
    try:
        with _TERMS_PATH.open(encoding="utf-8") as stream:
            data = json.load(stream)
        if not isinstance(data, dict):
            raise ValueError("top level must be an object")
        if data.get("version") != 1:
            raise ValueError("version must be 1")
        languages = data.get("languages")
        if not isinstance(languages, dict) or "en" not in languages:
            raise ValueError("languages must be an object containing en")
        for locale, concepts in languages.items():
            if not isinstance(locale, str) or not isinstance(concepts, dict):
                raise ValueError("each language must map to an object")
            for concept, fields in concepts.items():
                if concept not in CONCEPTS:
                    raise ValueError(f"unknown concept {concept!r} in {locale}")
                if not isinstance(fields, dict) or not fields:
                    raise ValueError(f"{locale}.{concept} must be a non-empty object")
                for field, terms in fields.items():
                    if field not in {"text", "stem", "href"}:
                        raise ValueError(f"unknown field {field!r} in {locale}.{concept}")
                    if (not isinstance(terms, list) or not terms
                            or not all(isinstance(term, str) and term for term in terms)):
                        raise ValueError(f"{locale}.{concept}.{field} must be non-empty strings")
        for concept in CONCEPTS:
            if not languages["en"].get(concept, {}).get("text"):
                raise ValueError(f"en.{concept}.text is required")
        for concept in HREF_CONCEPTS:
            if not languages["en"][concept].get("href"):
                raise ValueError(f"en.{concept}.href is required")
        return data
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(f"Cannot load E-E-A-T term resource {_TERMS_PATH}: {exc}") from exc


_TERMS = _load_terms()


def _literal_pattern(terms: list[str], *, boundary: str) -> re.Pattern:
    if boundary == "both":
        alternatives = []
        for term in terms:
            # Put the final word boundary before terminal punctuation. This keeps
            # e.g. Russian `к.м.н.` literal while still treating it as a whole word.
            match = re.fullmatch(r"(.*\w)(\W*)", term)
            if not match:
                raise ValueError(f"whole-word term has no word characters: {term!r}")
            word_part, punctuation = match.groups()
            alternatives.append(
                rf"\b{re.escape(word_part)}\b{re.escape(punctuation)}")
        pattern = rf"(?:{'|'.join(alternatives)})"
    elif boundary == "start":
        pattern = rf"\b(?:{'|'.join(re.escape(term) for term in terms)})"
    elif boundary == "none":
        pattern = rf"(?:{'|'.join(re.escape(term) for term in terms)})"
    else:  # Internal API: make an accidental fourth matching mode fail loudly.
        raise ValueError(f"unknown boundary mode {boundary!r}")
    return re.compile(pattern, re.I)


@lru_cache(maxsize=None)
def _patterns_for(locales: frozenset[str]) -> dict[str, dict[str, re.Pattern]]:
    """Compile the signal families in CONCEPTS once for each site language set."""
    patterns = {}
    languages = _TERMS["languages"]
    for concept in CONCEPTS:
        terms_by_field = {"text": [], "stem": [], "href": []}
        for locale in sorted(locales):
            fields = languages[locale].get(concept, {})
            for field in terms_by_field:
                terms_by_field[field].extend(fields.get(field, []))
        concept_patterns = {}
        for field, boundary in (("text", "both"), ("stem", "start"),
                                ("href", "none")):
            if terms_by_field[field]:
                concept_patterns[field] = _literal_pattern(
                    terms_by_field[field], boundary=boundary)
        patterns[concept] = concept_patterns
    return patterns


def _text_matches(patterns: dict[str, re.Pattern], value: str) -> bool:
    """Match either a whole-word literal or a deliberately reviewed prefix stem."""
    return any(patterns[field].search(value) for field in ("text", "stem")
               if field in patterns)


def _text_hits(patterns: dict[str, re.Pattern], value: str) -> list[str]:
    return sorted({match.group(0) for field in ("text", "stem")
                   if field in patterns for match in patterns[field].finditer(value)})


# JSON-LD types whose node names an organisation, compared case-insensitively against
# the last path segment of each `@type` so that a full schema.org URL and a bare token
# read the same. Anything ending in `organization` is included, which covers
# NewsMediaOrganization, EducationalOrganization and GovernmentOrganization without
# copying the type tree into this file.
ORG_TYPES = frozenset({"organization", "localbusiness", "corporation", "ngo",
                       "onlinebusiness"})


def _is_org_type(raw) -> bool:
    for value in (raw if isinstance(raw, list) else [raw]):
        token = str(value or "").rsplit("/", 1)[-1].lower()
        if token in ORG_TYPES or token.endswith("organization"):
            return True
    return False


def _credited_nodes(schema_items: list, protected=frozenset()) -> set[int]:
    """Every dict that is, or sits under, an `author` or `reviewedBy` value.

    An organisation the page credits — as its author or as its reviewer — is already
    named as one of those. Counting it a second time as evidence of a publisher would
    let one entity satisfy both halves of an item whose title asks for two: the
    collapse 0.51.0 exists to undo, re-entering through the type test instead of
    through the key set. `reviewedBy` stays here after 0.66.0 took it out of the author
    set, because a third-party review board is still not the site's own identity.

    The outer sweep is `page_nodes`, so a credit written inside somebody else's
    contribution is not treated as a credit at all. The inner one stays `walk_json`: a
    credit that is being read must be read whole.
    """
    credited: set[int] = set()
    for item in schema_items:
        for node in page_nodes(item, protected=protected):
            for key in ("author", "reviewedBy"):
                if key in node:
                    for inner in walk_json(node[key]):
                        credited.add(id(inner))
    return credited


def _publisher_names(parsed: dict, soup) -> list[str]:
    """Who the page says published it.

    Four sources, and the order is evidential rather than functional: a JSON-LD
    `publisher` key is the site saying the word, an organisation node is the site
    naming itself, and the two meta tags are what a site without structured data
    still declares. `og:site_name` is the weakest of them — a site name is not
    always a publisher name — and it is in the vocabulary because it is the only
    machine-readable site identity most pages carry, not because the fixture has it.

    A visible `© 2026 Acme Ltd` footer line is deliberately **not** a source. It is
    the most human-visible publisher statement on the web, and reading it needs a
    second name-extraction parser over unbounded prose: a loose pattern matches
    paragraphs *about* copyright, and a tight one needs a length cap with no measured
    basis. Excluded until something can measure it; the consequence is that a page
    whose only publisher signal is that line reports FAIL.
    """
    schema = parsed.get("page_schema", [])
    protected = parsed.get("page_own_ids", frozenset())
    credited = _credited_nodes(schema, protected=protected)
    names = list(schema_values(schema, {"publisher"}, protected))
    for item in schema:
        for node in page_nodes(item, protected=protected):
            if id(node) in credited:
                continue
            if _is_org_type(node.get("@type")) and node.get("name"):
                names.append(str(node["name"]))
    for tag in soup.find_all("meta"):
        prop = str(tag.get("property") or "").lower()
        name = str(tag.get("name") or "").lower()
        if ((prop in {"og:site_name", "article:publisher"} or name == "copyright")
                and not under_foreign_credit(
                    tag, claimed=parsed.get("foreign_itemref_ids"))):
            if tag.get("content"):
                names.append(str(tag["content"]))
    return names


def check_eeat(source: str, timeout: int = 15) -> dict:
    html, url, fetched = load_source(source, timeout)
    parsed = parse_html(html, url)
    soup = parsed["soup"]
    body = parsed.get("body_text", "")
    lang = primary_language(parsed, soup)
    locales = frozenset({"en", lang} if lang in _TERMS["languages"] else {"en"})
    patterns = _patterns_for(locales)

    authors = page_author_names(parsed)
    # `reviewedBy` sat in the line above until 0.66.0. A page whose only credit was a
    # review board reported an author, and a page naming a publisher and a reviewer but
    # no author passed CN-057 — an item whose title asks for two parties.
    reviewers = sorted({value.strip()
                        for value in schema_values(parsed.get("page_schema", []),
                                                   {"reviewedBy"},
                                                   parsed.get("page_own_ids", frozenset()))
                        if value and value.strip()})
    publishers = sorted({v.strip() for v in _publisher_names(parsed, soup) if v and v.strip()})

    credential_hits = _text_hits(patterns["credential"], body)
    experience_hits = _text_hits(patterns["first_hand"], body)
    links = parsed.get("links", [])
    policy_links = [
        link for link in links
        if (_text_matches(patterns["policy"], link.get("text", ""))
            or patterns["policy"]["href"].search(link.get("href", "")))
        and not link["foreign_credit"]
    ]
    contact_routes = [
        {"href": tag.get("href", "").strip(),
         "text": tag.get_text(" ", strip=True)[:160],
         "rel": tag.get("rel") or []}
        for tag in soup.find_all("a", href=True)
        if urlparse(tag.get("href", "").strip()).scheme.lower() in {"tel", "mailto"}
        and not under_foreign_credit(
            tag, claimed=parsed.get("foreign_itemref_ids"))
    ]
    trust_links = [
        link for link in links
        if (_text_matches(patterns["trust"], link.get("text", ""))
            or patterns["trust"]["href"].search(link.get("href", "")))
        and not link["foreign_credit"]
    ] + contact_routes
    # Privacy specifically, kept apart from both of the above. `policy_links` means
    # editorial standards — fact-checking, corrections, ethics — while `trust_links`
    # is anything vaguely institutional, an "About" page included. CN-040 asks only
    # whether there is an up-to-date privacy policy, and it was asserting on
    # `policy_links`, which answered a different question in both directions: a site
    # with a proper privacy policy failed unless it also published editorial
    # standards, and a site with an ethics page and no privacy policy passed.
    # A route to the people behind the page: a link named or addressed as contact, or a
    # phone or email link. Not an About, Privacy or Terms link, which `trust_links` keeps
    # counting for CN-068's score.
    contact_links = [
        link for link in links
        if (_text_matches(patterns["contact"], link.get("text", ""))
            or patterns["contact"]["href"].search(link.get("href", "")))
        and not link["foreign_credit"]
    ] + contact_routes
    privacy_links = [
        link for link in links
        if (_text_matches(patterns["privacy"], link.get("text", ""))
            or patterns["privacy"]["href"].search(link.get("href", "")))
        and not link["foreign_credit"]
    ]
    page_host = urlparse(url).netloc if url else ""
    external_citations = [
        link for link in links
        if urlparse(link.get("href", "")).netloc and urlparse(link.get("href", "")).netloc != page_host
        and not link["foreign_credit"]
    ]

    score = 0
    # CN-068 is about authorship/expertise, not publishers — and, since 0.66.0, not
    # reviewers either. A named reviewer earns no score: the visible sentence
    # "Medically reviewed by ..." already scores through the credential vocabulary,
    # measured at +7, so paying the markup as well would bill one fact twice.
    score += 20 if authors else 0
    score += min(20, len(credential_hits) * 7)
    score += min(20, len(experience_hits) * 7)
    score += 15 if policy_links else 0
    score += 15 if trust_links else 0
    score += min(10, len(external_citations) * 2)

    issues = []
    if not authors:
        issues.append({"severity": "warning", "message": "No clear author or byline signal found."})
    if reviewers and not authors:
        # Without this the split silently removes a credit the operator can see in the
        # markup, and the warning above would read as "no reviewer either".
        issues.append({"severity": "info",
                       "message": "Content is credited to a reviewer but names no author."})
    if not publishers:
        issues.append({"severity": "warning", "message": "No publisher or site-identity signal found."})
    if not credential_hits:
        issues.append({"severity": "info", "message": "No visible credential or review language found."})
    if not policy_links:
        issues.append({"severity": "info", "message": "No editorial, review, corrections, or fact-check policy link detected."})
    if not trust_links:
        issues.append({"severity": "warning", "message": "No obvious about/contact/privacy/team trust links detected."})
    if not privacy_links:
        issues.append({"severity": "warning", "message": "No privacy policy link detected."})

    return {
        "url": url or source,
        "score": min(100, score),
        "lang": lang,
        "matched_locales": sorted(locales),
        "signals": {
            "authors": authors[:20],
            "reviewers": reviewers[:20],
            "publishers": publishers[:20],
            # CN-057's title joins two conditions with "and", and one registry rule
            # reads one path, so the pair is emitted as an object the rule can compare
            # whole — the shape AR-158 uses for "breadcrumbs in the UI *and* as
            # BreadcrumbList markup".
            "authorship": {"author": bool(authors), "publisher": bool(publishers)},
            "credential_markers": credential_hits[:20],
            "first_hand_experience_markers": experience_hits[:20],
            "policy_links": policy_links[:20],
            "privacy_links": privacy_links[:20],
            "trust_links": trust_links[:20],
            "contact_links": contact_links[:20],
            "external_citations": len(external_citations),
        },
        "issues": issues,
        "fetch_error": fetched.get("error"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Check visible E-E-A-T signals in a URL or HTML file.")
    parser.add_argument("source", help="URL or local HTML file")
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument("--json", "-j", action="store_true", help="Output JSON")
    args = parser.parse_args()

    result = check_eeat(args.source, args.timeout)
    print(json.dumps(result, indent=2) if args.json else f"Score: {result['score']} Issues: {len(result['issues'])}")


if __name__ == "__main__":
    main()
