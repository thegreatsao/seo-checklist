#!/usr/bin/env python3
"""
Hreflang Validator

Validates hreflang implementations against all 8 checks defined in
resources/skills/seo-hreflang.md:

  1. Self-referencing tags
  2. Bidirectional return tags
  3. x-default presence
  4. ISO 639-1 language code format
  5. ISO 3166-1 Alpha-2 region code format
  6. Canonical URL alignment
  7. HTTP/HTTPS protocol consistency
  8. Cross-domain / sitemap-based hreflang detection

Usage:
    python hreflang_checker.py https://example.com/page
    python hreflang_checker.py https://example.com/page --json
    python hreflang_checker.py https://example.com/page --verify-returns
"""

import argparse
import json
import re
import sys
import time
from urllib.parse import urlparse, urljoin

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("Error: beautifulsoup4 required. Install with: pip install beautifulsoup4")
    sys.exit(1)

try:
    from lib.safe_http import safe_head
    from seo_common import fetch_html, html_parser
except ImportError:
    from scripts.lib.safe_http import safe_head
    from scripts.seo_common import fetch_html, html_parser


# ---------------------------------------------------------------------------
# Reference data (ISO 639-1 + ISO 3166-1 Alpha-2)
# ---------------------------------------------------------------------------

# Valid ISO 639-1 two-letter language codes (subset — common + frequently misused)
VALID_LANG_CODES = {
    "af", "sq", "am", "ar", "hy", "as", "az", "eu", "be", "bn", "bs", "bg",
    "ca", "ceb", "zh", "co", "hr", "cs", "da", "nl", "en", "eo", "et", "fi",
    "fr", "fy", "gl", "ka", "de", "el", "gu", "ht", "ha", "haw", "he", "hi",
    "hu", "is", "ig", "id", "ga", "it", "ja", "jv", "kn", "kk", "km", "rw",
    "ko", "ku", "ky", "lo", "la", "lv", "lt", "lb", "mk", "mg", "ms", "ml",
    "mt", "mi", "mr", "mn", "my", "ne", "no", "ny", "or", "ps", "fa", "pl",
    "pt", "pa", "ro", "ru", "sm", "gd", "sr", "st", "sn", "sd", "si", "sk",
    "sl", "so", "es", "su", "sw", "sv", "tl", "tg", "ta", "tt", "te", "th",
    "tr", "tk", "uk", "ur", "ug", "uz", "vi", "cy", "xh", "yi", "yo", "zu",
}

# Common wrong codes and their corrections
COMMON_LANG_MISTAKES = {
    "eng": "en",   # ISO 639-2 (3-letter), not valid for hreflang
    "jp": "ja",    # Wrong code for Japanese
    "zh-cn": "zh-Hans",  # Simplified Chinese region variant gone wrong
    "zh-tw": "zh-Hant",  # Traditional Chinese
    "iw": "he",    # Old code for Hebrew
    "in": "id",    # Old code for Indonesian
}

# Valid ISO 3166-1 Alpha-2 region codes (common ones)
VALID_REGION_CODES = {
    "AF", "AL", "DZ", "AD", "AO", "AG", "AR", "AM", "AU", "AT", "AZ",
    "BS", "BH", "BD", "BB", "BY", "BE", "BZ", "BJ", "BT", "BO", "BA",
    "BW", "BR", "BN", "BG", "BF", "BI", "CV", "KH", "CM", "CA", "CF",
    "TD", "CL", "CN", "CO", "KM", "CG", "CD", "CR", "CI", "HR", "CU",
    "CY", "CZ", "DK", "DJ", "DM", "DO", "EC", "EG", "SV", "GQ", "ER",
    "EE", "SZ", "ET", "FJ", "FI", "FR", "GA", "GM", "GE", "DE", "GH",
    "GR", "GD", "GT", "GN", "GW", "GY", "HT", "HN", "HU", "IS", "IN",
    "ID", "IR", "IQ", "IE", "IL", "IT", "JM", "JP", "JO", "KZ", "KE",
    "KI", "KP", "KR", "KW", "KG", "LA", "LV", "LB", "LS", "LR", "LY",
    "LI", "LT", "LU", "MG", "MW", "MY", "MV", "ML", "MT", "MH", "MR",
    "MU", "MX", "FM", "MD", "MC", "MN", "ME", "MA", "MZ", "MM", "NA",
    "NR", "NP", "NL", "NZ", "NI", "NE", "NG", "NO", "OM", "PK", "PW",
    "PA", "PG", "PY", "PE", "PH", "PL", "PT", "QA", "RO", "RU", "RW",
    "KN", "LC", "VC", "WS", "SM", "ST", "SA", "SN", "RS", "SC", "SL",
    "SG", "SK", "SI", "SB", "SO", "ZA", "SS", "ES", "LK", "SD", "SR",
    "SE", "CH", "SY", "TW", "TJ", "TZ", "TH", "TL", "TG", "TO", "TT",
    "TN", "TR", "TM", "TV", "UG", "UA", "AE", "GB", "US", "UY", "UZ",
    "VU", "VE", "VN", "YE", "ZM", "ZW",
    # Common non-sovereign but valid in context
    "HK", "MO", "PR", "GU", "VI", "AS",
}

# Common region mistakes
COMMON_REGION_MISTAKES = {
    "UK": "GB",   # UK is not a valid ISO 3166-1 code; use GB
    "LA": None,   # Latin America is not a country
    "EU": None,   # European Union is not a country
}

# ---------------------------------------------------------------------------
# Hreflang tag extraction
# ---------------------------------------------------------------------------

def extract_hreflang_from_html(soup: BeautifulSoup, page_url: str) -> list[dict]:
    """
    Extract hreflang tags from <link rel="alternate" hreflang="..."> in <head>.
    Returns list of {lang, url, raw_lang, raw_url}.
    """
    tags = []
    for link in soup.find_all("link", rel="alternate"):
        lang = link.get("hreflang", "").strip()
        href = link.get("href", "").strip()
        if not lang or not href:
            continue
        # Resolve relative URLs
        absolute = urljoin(page_url, href)
        tags.append({
            "lang": lang.lower() if lang != "x-default" else "x-default",
            "raw_lang": lang,
            "url": absolute,
            "raw_url": href,
        })
    return tags


def extract_hreflang_from_http_headers(url: str) -> list[dict]:
    """Check HTTP Link headers for hreflang (used for non-HTML files)."""
    tags = []
    try:
        resp = safe_head(url, timeout=8)
        link_header = resp.headers.get("Link", "")
        if not link_header:
            return []
        # Parse: <url>; rel="alternate"; hreflang="lang"
        for part in link_header.split(","):
            part = part.strip()
            url_match = re.search(r'<([^>]+)>', part)
            hreflang_match = re.search(r'hreflang="([^"]+)"', part)
            rel_match = re.search(r'rel="([^"]+)"', part)
            if url_match and hreflang_match and rel_match and "alternate" in rel_match.group(1):
                tags.append({
                    "lang": hreflang_match.group(1).lower(),
                    "raw_lang": hreflang_match.group(1),
                    "url": url_match.group(1),
                    "raw_url": url_match.group(1),
                    "source": "http_header",
                })
    except Exception:
        pass
    return tags


def locale_page_key(url: str, alternate_urls: list[str]) -> tuple:
    """Group a URL with locale alternates learned from hreflang declarations.

    Exact alternates form one group even across domains. For other routes on the
    same host, remove only a first path segment observed on a root-level alternate;
    this derives `/en/`-style locale prefixes from markup rather than maintaining a
    language-code path heuristic here.
    """
    def normalized(value: str) -> tuple:
        parsed = urlparse(value)
        path = parsed.path.rstrip("/") or "/"
        return (parsed.scheme.lower(), parsed.netloc.lower(), path,
                parsed.params, parsed.query)

    target = normalized(url)
    alternates = {normalized(value) for value in alternate_urls if value}
    if target in alternates:
        return ("hreflang", tuple(sorted(alternates)))

    prefixes_by_host: dict[str, set[str]] = {}
    for _scheme, host, path, _params, _query in alternates:
        parts = [part for part in path.split("/") if part]
        if len(parts) == 1:
            prefixes_by_host.setdefault(host, set()).add(parts[0])

    scheme, host, path, params, query = target
    parts = [part for part in path.split("/") if part]
    if parts and parts[0] in prefixes_by_host.get(host, set()):
        parts = parts[1:]
    return (scheme, host, "/" + "/".join(parts) if parts else "/", params, query)


def check_sitemap_hreflang(base_url: str) -> dict:
    """Check /sitemap.xml for xhtml:link hreflang attributes."""
    parsed = urlparse(base_url)
    sitemap_url = f"{parsed.scheme}://{parsed.netloc}/sitemap.xml"
    html, _ = fetch_html(sitemap_url, timeout=8, quiet=True)
    if not html:
        return {"found": False, "url": sitemap_url}

    lang_matches = re.findall(r'hreflang="([^"]+)"', html)

    return {
        # `found` is hreflang attributes, not the `xhtml:link` wrapper. A separate
        # `has_xhtml_link` was computed here and never returned; it would have said
        # nothing `has_xhtml_namespace` does not, because an `xhtml:link` element
        # cannot appear without the namespace that declares it.
        "found": bool(lang_matches),
        "url": sitemap_url,
        "has_xhtml_namespace": "xmlns:xhtml" in html,
        "language_variants_found": list(set(lang_matches)) if lang_matches else [],
        "note": "Sitemap-based hreflang detected." if lang_matches else "No hreflang found in sitemap.",
    }


# ---------------------------------------------------------------------------
# Validation logic (maps 1:1 to seo-hreflang.md checks)
# ---------------------------------------------------------------------------

def validate_lang_code(lang_tag: str) -> dict:
    """
    Validate a single hreflang value with a pragmatic BCP 47 parser.

    Supported shape:
      language[-script][-region][-variant...]

    Examples: en, en-US, zh-Hans, zh-Hant-TW, sr-Cyrl-RS.
    Returns {valid, lang, script, region, variants, issues}.
    """
    raw_tag = (lang_tag or "").strip()
    if raw_tag.lower() == "x-default":
        return {
            "valid": True,
            "lang": "x-default",
            "script": None,
            "region": None,
            "variants": [],
            "issues": [],
        }

    issues = []
    if "_" in raw_tag:
        issues.append("Use hyphens, not underscores, in hreflang values.")

    mistake = COMMON_LANG_MISTAKES.get(raw_tag.lower())
    if mistake:
        issues.append(f"'{raw_tag}' is a common invalid hreflang value. Use '{mistake}' instead.")

    parts = raw_tag.replace("_", "-").split("-")
    lang = parts[0].lower() if parts and parts[0] else ""
    script = None
    region = None
    variants = []
    index = 1

    if not re.fullmatch(r"[A-Za-z]{2,3}", lang or ""):
        issues.append(
            f"Invalid primary language subtag '{parts[0] if parts else ''}'. "
            "Use a 2-3 letter BCP 47 language subtag."
        )
    elif len(lang) == 2 and lang not in VALID_LANG_CODES:
        correction = COMMON_LANG_MISTAKES.get(lang)
        issue = f"Unknown language code '{lang}'."
        if correction:
            issue += f" Did you mean '{correction}'?"
        issues.append(issue)

    if index < len(parts) and re.fullmatch(r"[A-Za-z]{4}", parts[index]):
        script = parts[index].title()
        index += 1

    if index < len(parts) and (
        re.fullmatch(r"[A-Za-z]{2}", parts[index])
        or re.fullmatch(r"\d{3}", parts[index])
    ):
        region = parts[index].upper()
        index += 1

    while index < len(parts):
        part = parts[index]
        if re.fullmatch(r"[A-Za-z0-9]{5,8}", part) or re.fullmatch(r"\d[A-Za-z0-9]{3}", part):
            variants.append(part)
            index += 1
            continue
        if re.fullmatch(r"[A-WY-Za-wy-z0-9]", part):
            issues.append("Extension subtags are valid BCP 47 but are not supported for hreflang targeting.")
            break
        issues.append(f"Invalid or out-of-order BCP 47 subtag '{part}'.")
        index += 1

    if lang == "zh" and not script and region not in {"CN", "SG", "TW", "HK", "MO"}:
        issues.append("'zh' is ambiguous — use 'zh-Hans' or 'zh-Hant' when no clear region is present.")

    if region:
        if region in COMMON_REGION_MISTAKES:
            fix = COMMON_REGION_MISTAKES[region]
            if fix:
                issues.append(f"Region '{region}' is not a valid ISO 3166-1 code. Use '{fix}'.")
            else:
                issues.append(f"'{region}' is not a valid ISO 3166-1 country code for hreflang.")
        elif re.fullmatch(r"[A-Z]{2}", region) and region not in VALID_REGION_CODES:
            issues.append(f"Unknown region code '{region}' — verify against ISO 3166-1 Alpha-2.")

    return {
        "valid": len(issues) == 0,
        "lang": lang,
        "script": script,
        "region": region,
        "variants": variants,
        "issues": issues,
    }


def check_self_reference(tags: list[dict], page_url: str) -> dict:
    """Check 1: Self-referencing tag must be present and URL must match canonical."""
    normalized_page = page_url.rstrip("/")
    for tag in tags:
        tag_url = tag["url"].rstrip("/")
        if tag_url == normalized_page:
            return {"passed": True, "detail": "Self-referencing hreflang tag found."}

    return {
        "passed": False,
        "severity": "Critical",
        "finding": "No self-referencing hreflang tag found.",
        "fix": "Add <link rel=\"alternate\" hreflang=\"{lang}\" href=\"{page_url}\"> pointing to this page's own canonical URL.",
    }


def check_x_default(tags: list[dict]) -> dict:
    """Check 3: x-default tag presence."""
    x_defaults = [t for t in tags if t["lang"] == "x-default"]
    if not x_defaults:
        return {
            "passed": False,
            "severity": "High",
            "finding": "No x-default hreflang tag found.",
            "fix": "Add <link rel=\"alternate\" hreflang=\"x-default\" href=\"{fallback_url}\"> pointing to your language selector or primary language version.",
        }
    if len(x_defaults) > 1:
        return {
            "passed": False,
            "severity": "High",
            "finding": f"Multiple x-default tags found ({len(x_defaults)}). Only one is allowed.",
            "fix": "Remove duplicate x-default tags. Keep only one pointing to the language selector or primary version.",
        }
    return {"passed": True, "detail": f"x-default present → {x_defaults[0]['url']}"}


def locale_tokens(lang: str) -> set:
    """The spellings of one hreflang value that can appear inside a URL.

    `de-DE` can be written `de-de`, `de_de` or reduced to either subtag, and all four
    are found in the wild.
    """
    lang = lang.strip().lower()
    parts = {p for p in re.split(r"[-_]", lang) if p}
    return {t for t in parts | {lang, lang.replace("-", "_")} if t}


def locale_lives_in(lang: str, url: str) -> str:
    """Where this alternate carries its own locale: the component that holds its code.

    Read from the tag rather than by comparing alternates with each other, which is the
    second attempt at this. Comparing components finds which one *varies*, and that is
    a different question with the same answer most of the time: `example.com/de/`
    beside `fr.example.com/` varies in the host, so component comparison called the set
    a subdomain structure when one locale is in the path and the other in the host —
    the exact mixture this check exists to name.

    Returns "" when the locale code appears nowhere in the URL. That is a legitimate
    and very common case rather than a defect: the default locale usually sits at the
    root, `https://example.com/` for `en` beside `/de/` and `/fr/`.
    """
    tokens = locale_tokens(lang)
    parsed = urlparse(url)
    host = parsed.netloc.lower().rstrip(".").split(":")[0]
    labels = host.split(".")
    if len(labels) > 1 and labels[-1] in tokens:
        return "ccTLD"
    if len(labels) > 2 and labels[0] in tokens:
        return "subdomain"
    segments = [s for s in parsed.path.split("/") if s]
    if segments and segments[0].lower() in tokens:
        return "subdirectory"
    if parsed.query:
        values = {v.lower() for pair in parsed.query.split("&")
                  for v in pair.split("=")[1:]}
        if values & tokens:
            return "parameter"
    return ""


def _locale_lives_in_path_or_query(lang: str, url: str) -> str:
    """Read a locale without treating its host as the separator.

    A host shared by several locales cannot be what distinguishes those locales.
    Its matching ccTLD or locale-looking subdomain is incidental, so only the path
    and query remain meaningful for alternates on that host.
    """
    tokens = locale_tokens(lang)
    parsed = urlparse(url)
    segments = [s for s in parsed.path.split("/") if s]
    if segments and segments[0].lower() in tokens:
        return "subdirectory"
    if parsed.query:
        values = {v.lower() for pair in parsed.query.split("&")
                  for v in pair.split("=")[1:]}
        if values & tokens:
            return "parameter"
    return ""


def _url_structure_reading(tags: list[dict]) -> tuple[str, list[str]]:
    """Return the structure and URLs that make a confident reading impossible."""
    graded: list[tuple[str, str]] = []
    readable: list[tuple[str, str, str]] = []
    unreadable: list[str] = []
    for tag in tags:
        lang, url = (tag.get("lang") or "").strip(), tag.get("url") or ""
        if not lang or not url or lang.lower() == "x-default":
            continue
        graded.append((lang, url))

    locales_by_host: dict[str, set[str]] = {}
    for lang, url in graded:
        host = (urlparse(url).hostname or "").lower()
        locales_by_host.setdefault(host, set()).add(lang.lower())

    for lang, url in graded:
        where = locale_lives_in(lang, url)
        host = (urlparse(url).hostname or "").lower()
        if len(locales_by_host.get(host, set())) > 1 and where in ("ccTLD", "subdomain"):
            where = _locale_lives_in_path_or_query(lang, url)
        if where:
            readable.append((lang, url, where))
        else:
            unreadable.append(url)

    if len(graded) < 2:
        return "single", []
    places = {where for _lang, _url, where in readable}
    if not places:
        return "unmarked", []
    if len(places) > 1:
        return "mixed", [url for _lang, url in graded]

    structure = next(iter(places))
    # An unreadable locale on a host-based scheme does not contradict the scheme:
    # `en-GB` on .uk and `ja` on .jp remain visibly separate hosts even though their
    # hreflang spelling does not match the ccTLD string.
    if structure in ("ccTLD", "subdomain"):
        return structure, []

    if structure == "subdirectory":
        # A subdirectory scheme means one host. Its default locale may omit the
        # prefix throughout its route tree, but that is evidence of this scheme only
        # when the resulting path equals a readable alternate's route after that
        # alternate's own locale prefix is removed.
        hosts = [(urlparse(url).hostname or "").lower()
                 for _lang, url, _where in readable]
        primary_host = hosts[0]
        incompatible = [
            url for (_lang, url, _where), host in zip(readable, hosts, strict=True)
            if host != primary_host
        ]

        def normalised_path(path: str) -> str:
            return (path or "/").rstrip("/") or "/"

        unprefixed_routes = set()
        for (lang, url, _where), host in zip(readable, hosts, strict=True):
            if host != primary_host:
                continue
            path = urlparse(url).path.lstrip("/")
            prefix, separator, remainder = path.partition("/")
            if prefix.lower() in locale_tokens(lang):
                stripped = f"/{remainder}" if separator else "/"
                unprefixed_routes.add(normalised_path(stripped))

        for url in unreadable:
            parsed = urlparse(url)
            same_host = (parsed.hostname or "").lower() == primary_host
            route_match = normalised_path(parsed.path) in unprefixed_routes
            if not (same_host and route_match):
                incompatible.append(url)
        if incompatible:
            return "mixed", incompatible
        return structure, []

    # Parameters already fail IN-127. An unreadable alternate does not establish that
    # it follows even that scheme, so report and name the mixture explicitly.
    if unreadable:
        return "mixed", unreadable
    return structure, []


def url_structure_of(tags: list[dict]) -> str:
    """`ccTLD`, `subdomain`, `subdirectory`, `parameter`, `mixed`, `single`, `unmarked`.

    `x-default` is excluded: it names no locale, so it cannot carry one.

    A region whose ccTLD is spelled differently from its subtag — `en-GB` on `.uk`,
    `ja` on `.jp` — reads as unmarked rather than guessed at. It is compatible with a
    host-based reading. An unprefixed path on the same host is compatible with a
    subdirectory reading only when it equals a readable alternate's path after that
    alternate's locale prefix is removed. Any other unreadable alternate makes the set
    mixed: ignoring it would let one readable URL award a PASS to a contradictory set.
    """
    return _url_structure_reading(tags)[0]


def check_url_structure(tags: list[dict]) -> dict:
    """Check 9: the international URL structure is one of the three Google supports.

    # Google Search Central, "Managing multi-regional and
    # multilingual sites", which lists country-code top-level domains, subdomains and
    # subdirectories as the ways to structure locale URLs and says URL parameters
    # "are not recommended" because they are hard to segment by and users cannot read
    # the locale out of them.

    This is what IN-127 *Use a Clear International URL Structure* was supposed to
    assert through 0.25.0. It asserted `checks.protocol_consistency.passed` instead —
    whether the hreflang set mixes http and https — which is a real defect under
    somebody else's name and says nothing about structure. A site with every locale on
    `?lang=` and one on a subdomain passed it.
    """
    structure, incompatible = _url_structure_reading(tags)
    if structure in ("single", "unmarked"):
        # One alternate, or none whose URL carries its own locale code. There is no
        # structure to read, and inventing a verdict for it is what the old assertion
        # did — so no `passed` key, and the item reports NO_DATA.
        return {"structure": structure,
                "detail": ("Only one locale alternate; no structure to assess."
                           if structure == "single" else
                           "No alternate carries its locale code in the URL, so the "
                           "structure cannot be read from the hreflang set.")}
    if structure == "mixed":
        named = ", ".join(incompatible)
        return {
            "passed": False, "structure": structure, "severity": "Medium",
            "finding": "The hreflang set mixes locale URL schemes, so no single rule "
                       f"says where a locale lives. Conflicting URL(s): {named}",
            "fix": "Pick one of ccTLDs, subdomains or subdirectories and move every "
                   "locale onto it.",
        }
    if structure == "parameter":
        return {
            "passed": False, "structure": structure, "severity": "Medium",
            "finding": "Locales are distinguished by a URL parameter, which Google "
                       "does not recommend and cannot be geo-targeted in Search "
                       "Console.",
            "fix": "Move locales onto subdirectories (/de/), subdomains "
                   "(de.example.com) or country-code domains (example.de).",
        }
    return {"passed": True, "structure": structure,
            "detail": f"Locales are separated by {structure}."}


def check_protocol_consistency(tags: list[dict]) -> dict:
    """Check 7: All URLs in the hreflang set must use the same protocol."""
    protocols = {urlparse(t["url"]).scheme for t in tags if t["url"]}
    if len(protocols) > 1:
        return {
            "passed": False,
            "severity": "Medium",
            "finding": f"Mixed protocols in hreflang set: {', '.join(sorted(protocols))}.",
            "fix": "Standardize all hreflang URLs to HTTPS. Update any remaining HTTP URLs.",
        }
    return {"passed": True, "detail": f"All hreflang URLs use: {list(protocols)[0] if protocols else 'unknown'}"}


def check_lang_codes(tags: list[dict]) -> list[dict]:
    """Checks 4 & 5: Validate each language/region code."""
    issues = []
    for tag in tags:
        if tag["lang"] == "x-default":
            continue
        validation = validate_lang_code(tag["raw_lang"])
        if not validation["valid"]:
            for issue_text in validation["issues"]:
                issues.append({
                    "passed": False,
                    "severity": "High",
                    "lang_tag": tag["raw_lang"],
                    "url": tag["url"],
                    "finding": issue_text,
                    "fix": "Fix the language/region code to use ISO 639-1 + ISO 3166-1 Alpha-2 format.",
                })
    return issues


def check_return_tags(
    tags: list[dict],
    page_url: str,
    verify_remote: bool = False,
    timeout: int = 8,
) -> list[dict]:
    """
    Check 2: Bidirectional return tags.
    If verify_remote=True, fetches each alternate URL and checks for a reciprocal tag.
    Without remote fetch, returns Hypothesis-confidence findings.
    """
    issues = []
    non_self = [t for t in tags if t["url"].rstrip("/") != page_url.rstrip("/")
                and t["lang"] != "x-default"]

    if not non_self:
        return []

    if not verify_remote:
        issues.append({
            "passed": None,  # Cannot confirm without fetching
            "severity": "Info",
            "confidence": "Hypothesis",
            "finding": f"Found {len(non_self)} alternate URL(s). Return tag verification requires --verify-returns flag.",
            "fix": "Run with --verify-returns to fetch each alternate and confirm bidirectional hreflang.",
            "alternates": [t["url"] for t in non_self],
        })
        return issues

    # Remote verification
    for alt_tag in non_self:
        alt_url = alt_tag["url"]
        time.sleep(0.5)  # polite crawl delay
        alt_html, _ = fetch_html(alt_url, timeout=timeout, quiet=True)
        if not alt_html:
            issues.append({
                "passed": None,
                "confidence": "Hypothesis",
                "severity": "Info",
                "finding": f"Could not fetch alternate URL to verify return tag: {alt_url}",
                "fix": "Manually verify that this page links back to the source page with hreflang.",
            })
            continue

        alt_soup = BeautifulSoup(alt_html, html_parser())
        alt_tags = extract_hreflang_from_html(alt_soup, alt_url)
        returns_to_source = any(
            t["url"].rstrip("/") == page_url.rstrip("/") for t in alt_tags
        )

        if not returns_to_source:
            issues.append({
                "passed": False,
                "confidence": "Confirmed",
                "severity": "Critical",
                "lang_tag": alt_tag["lang"],
                "finding": f"Missing return tag on {alt_url} — no hreflang pointing back to {page_url}.",
                "fix": f"Add hreflang tag on {alt_url} that references {page_url}.",
            })
        else:
            issues.append({
                "passed": True,
                "confidence": "Confirmed",
                "lang_tag": alt_tag["lang"],
                "finding": f"Return tag confirmed on {alt_url}",
            })

    return issues


def check_canonical_alignment(soup: BeautifulSoup, tags: list[dict], page_url: str) -> dict:
    """
    Check 6: Hreflang tags should only appear on canonical URLs.
    Warns if a canonical tag points elsewhere, invalidating the hreflang set.
    """
    canonical_tag = soup.find("link", rel="canonical")
    if not canonical_tag:
        return {"passed": None, "confidence": "Hypothesis",
                "finding": "No canonical tag found — cannot verify hreflang/canonical alignment.",
                "fix": "Add a self-referencing canonical tag to confirm this is the canonical URL."}

    canonical_url = canonical_tag.get("href", "").strip()
    if canonical_url and canonical_url.rstrip("/") != page_url.rstrip("/"):
        return {
            "passed": False,
            "severity": "High",
            "confidence": "Confirmed",
            "finding": f"Canonical tag points to a different URL ({canonical_url}). Hreflang on non-canonical pages is ignored by Google.",
            "fix": "Remove hreflang tags from this page OR move them to the canonical URL.",
        }

    return {"passed": True, "detail": f"Canonical URL matches page URL: {canonical_url}"}


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def run_hreflang_check(url: str, verify_returns: bool = False) -> dict:
    """Run all 8 hreflang checks and return a structured report."""
    html, final_url = fetch_html(url, timeout=10, quiet=True)
    if not html:
        return {"error": f"Failed to fetch URL: {url}", "url": url,
                "error_kind": "unread"}

    soup = BeautifulSoup(html, html_parser())
    tags = extract_hreflang_from_html(soup, final_url)

    # Also check HTTP headers (Check 8 — alternative implementation method)
    http_header_tags = extract_hreflang_from_http_headers(final_url)
    implementation_method = "none"
    if tags:
        implementation_method = "html_link_tags"
    elif http_header_tags:
        tags = http_header_tags
        implementation_method = "http_headers"

    # Check sitemap hreflang (Check 8)
    sitemap_info = check_sitemap_hreflang(final_url)
    if sitemap_info["found"] and implementation_method == "none":
        implementation_method = "xml_sitemap"

    results = {
        "url": final_url,
        "implementation_method": implementation_method,
        "hreflang_tags_found": len(tags),
        "tags": tags,
        "sitemap": sitemap_info,
        "checks": {},
        "language_code_issues": [],
        "return_tag_checks": [],
        "summary": {"critical": 0, "high": 0, "medium": 0, "low": 0, "passed": 0},
    }

    if not tags:
        results["checks"]["hreflang_present"] = {
            "passed": False,
            "severity": "Info",
            "finding": "No hreflang tags found (HTML, HTTP headers, or sitemap).",
            "fix": "If this is a single-language site, hreflang is not needed. For multi-language sites, implement hreflang via HTML link tags or sitemap.",
        }
        return results

    # Check 1 — Self-reference
    results["checks"]["self_reference"] = check_self_reference(tags, final_url)

    # Check 3 — x-default
    results["checks"]["x_default"] = check_x_default(tags)

    # Check 7 — Protocol consistency
    results["checks"]["protocol_consistency"] = check_protocol_consistency(tags)

    # Check 9 — International URL structure (what IN-127 reads)
    results["checks"]["url_structure"] = check_url_structure(tags)

    # Check 6 — Canonical alignment
    results["checks"]["canonical_alignment"] = check_canonical_alignment(soup, tags, final_url)

    # Checks 4 & 5 — Language/region code validation
    results["language_code_issues"] = check_lang_codes(tags)

    # Check 2 — Return tags (bidirectional)
    results["return_tag_checks"] = check_return_tags(tags, final_url, verify_remote=verify_returns)
    return_outcomes = [check.get("passed") for check in results["return_tag_checks"]]
    return_summary = {
        "verified": verify_returns,
        "alternates_checked": len(return_outcomes),
    }
    if verify_returns and all(outcome is not None for outcome in return_outcomes):
        return_summary["verified_and_valid"] = all(return_outcomes)
        return_summary["detail"] = (
            f"Verified {len(return_outcomes)} alternate return tag(s); "
            + ("all valid." if all(return_outcomes) else "at least one is missing."))
    elif not verify_returns:
        return_summary["detail"] = "Return tags were not verified."
    else:
        return_summary["detail"] = "At least one alternate could not be verified."
    results["checks"]["return_tags"] = return_summary

    # Tally summary
    sev_map = {"Critical": "critical", "High": "high", "Medium": "medium", "Low": "low"}
    for check in results["checks"].values():
        if check.get("passed") is True:
            results["summary"]["passed"] += 1
        elif check.get("passed") is False:
            sev = check.get("severity", "low")
            results["summary"][sev_map.get(sev, "low")] += 1

    for issue in results["language_code_issues"] + results["return_tag_checks"]:
        if issue.get("passed") is False:
            sev = issue.get("severity", "low")
            results["summary"][sev_map.get(sev, "low")] += 1

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Hreflang Validator — checks all 8 rules from seo-hreflang.md"
    )
    parser.add_argument("url", help="Page URL to validate")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument(
        "--verify-returns",
        action="store_true",
        help="Fetch each alternate URL to verify bidirectional return tags (slower, makes HTTP requests)",
    )
    args = parser.parse_args()

    report = run_hreflang_check(args.url, verify_returns=args.verify_returns)

    if args.json:
        print(json.dumps(report, indent=2))
        return

    if report.get("error"):
        print(f"Error: {report['error']}")
        sys.exit(1)

    print(f"\nHreflang Validation — {report['url']}")
    print("=" * 60)
    print(f"Implementation Method : {report['implementation_method']}")
    print(f"Tags Found            : {report['hreflang_tags_found']}")

    if report["tags"]:
        print("\nDetected Alternates:")
        for tag in report["tags"]:
            validation = validate_lang_code(tag["raw_lang"])
            status = "✅" if validation["valid"] or tag["lang"] == "x-default" else "❌"
            print(f"  {status} [{tag['raw_lang']:12}] {tag['url']}")

    print(f"\nSitemap Hreflang : {'Found' if report['sitemap']['found'] else 'Not found'}")
    if report["sitemap"]["found"]:
        print(f"  Variants: {', '.join(report['sitemap']['language_variants_found'])}")

    print("\nValidation Results:")
    sev_icon = {"Critical": "🔴", "High": "🟠", "Medium": "⚠️", "Low": "ℹ️", "Info": "ℹ️"}

    for name, check in report["checks"].items():
        if check.get("passed") is True:
            print(f"  ✅ {name.replace('_', ' ').title()}: {check.get('detail', 'Pass')}")
        elif check.get("passed") is False:
            icon = sev_icon.get(check.get("severity", "Low"), "⚠️")
            print(f"  {icon} {name.replace('_', ' ').title()}: {check.get('finding', '')}")
            print(f"       Fix: {check.get('fix', '')}")
        else:
            print(f"  ℹ️  {name.replace('_', ' ').title()}: {check.get('finding', '')} (Confidence: {check.get('confidence', 'Hypothesis')})")

    if report["language_code_issues"]:
        print("\nLanguage/Region Code Issues:")
        for issue in report["language_code_issues"]:
            icon = sev_icon.get(issue.get("severity", "High"), "🟠")
            print(f"  {icon} [{issue['lang_tag']}] {issue['finding']}")

    if report["return_tag_checks"]:
        print("\nReturn Tag Checks:")
        for check in report["return_tag_checks"]:
            if check.get("passed") is True:
                print(f"  ✅ [{check.get('lang_tag', '')}] {check['finding']}")
            elif check.get("passed") is False:
                icon = sev_icon.get(check.get("severity", "Critical"), "🔴")
                print(f"  {icon} [{check.get('lang_tag', '')}] {check['finding']}")
            else:
                print(f"  ℹ️  {check['finding']}")

    s = report["summary"]
    total_issues = s["critical"] + s["high"] + s["medium"] + s["low"]
    print(f"\nSummary: {s['passed']} passed, {total_issues} issues")
    print(f"  🔴 Critical: {s['critical']}  🟠 High: {s['high']}  ⚠️ Medium: {s['medium']}  ℹ️ Low: {s['low']}")

    if not args.verify_returns and report["hreflang_tags_found"] > 1:
        print("\nTip: Run with --verify-returns to fetch each alternate URL and confirm bidirectional return tags.")


if __name__ == "__main__":
    main()
