#!/usr/bin/env python3
"""One crawl of a site, written down once, for every check that needs the whole site.

Six scripts used to walk the same pages independently — `duplicate_content.py` at 50
pages, `link_profile.py` at 50, `internal_links.py` at 50, GO-137's former
sitemap-orphan reader at 100, `anchor_text_audit.py` at 25, and
`broken_links.py` over one page's links — each with its own budget, its own robots
handling and its own idea of what the site is, and each throwing the result away.
That is ~275 fetches of the same pages per audit, measured at 181 on a seven-page
fixture, and five sets of numbers that could disagree about the same site.

This crawls once and writes down what it saw. The pattern is the one this tool
already uses for `cwv_metrics.py` and `rendered_audit.py`: measure, write an
artifact, let the readers read. The difference is who measures — a browser there, us
here — so unlike those two the artifact is verifiable by re-running this script, and
the audit produces it rather than being handed it.

    python site_crawl.py https://example.com --json
    python site_crawl.py https://example.com --out inventory.json

With `--out` the full inventory goes to the file and `--json` prints the summary,
because the summary is the part a caller wants on stdout when the artifact is
already on disk.

**What is one page.** A page key is `scheme://host/path` spelled as requests sends it,
with the trailing slash removed from everything but the root and the query dropped
except a page number (`?page=2`, `PAGE_NUMBER_PARAMS`). So `/a`, `/a/`, `/a?x=1` and
`/caf%C3%A9`/`/café` are one page each, and `/blog?page=2` is its own page, whose
title MS-022 judges. The item that cares about other query variants
(`faceted_nav_audit.py`, AR-163) reads URLs, not this inventory.

**What "reachable" means.** A page reached by following a link from another crawled
page. Fetching a URL out of a sitemap does not make it reachable — `link_profile.py`
uses that distinction, so seeding from the sitemap must not quietly satisfy it.
"""

from __future__ import annotations

from lib import python_floor  # noqa: F401

import argparse
import hashlib
import json
import re
import threading
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urljoin, urlparse, urlunparse

from seo_common import (
    refused_kind,
    SITEMAP_BYTES_BUDGET,
    SITEMAP_URLS_BUDGET,
    as_list,
    carries_content,
    comparable_url,
    declared_canonicals,
    discover_sitemap_urls,
    fetch_url,
    normalize_url,
    parse_html,
    parse_sitemap_xml,
    sitemap_document,
    picture_sources,
    print_json_or_text,
    same_host,
    srcset_urls,
    walk_json,
)

import sys

# Not every caller is the runner. This script prints `ensure_ascii=False` JSON, and a
# bare `python <script> …` on Windows encodes stdout with the ANSI codepage — so a
# Greek query or a Polish name raises UnicodeEncodeError and the script produces
# nothing at all. The runner now hands its children a UTF-8 environment; this is the
# same guarantee for somebody running the script by hand.
def _utf8_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):  # already wrapped, or not a TextIO
            pass


_utf8_stdout()

# Bumped when a reader could be wrong about what a field means. `load()` refuses an
# inventory it does not understand rather than reading a field that has moved.
# 2 adds `lang`. Bumped rather than tolerated as absent: a version-1 inventory cannot
# answer the language question at all, and a reader that treats "no lang recorded" as
# "one language" would put a trilingual site's whole navigation back into the editorial
# link set — silently, which is the failure this counter exists to stop. 3 adds compact
# `schema_nodes`; an older inventory cannot answer a site-wide schema-presence rule.
# 4 adds image references; an older inventory cannot answer a site-wide image rule.
# 5 (F15 batch 3) changes four meanings: page keys keep a page number and spell the
# path as sent, `canonical` is the one usable canonical (`canonicals` all of them, the
# `Link` header's included), an image link's anchor is its alt, and `redirected` is per
# linked spelling (`spellings`) — a version-4 inventory answers MS-022, TE-176, BL-081
# and AR-149 the old way.
INVENTORY_VERSION = 5

# basis: convention — 100 pages, the request budget an audit's crawl runs with (the
#  runner's `--crawl-max-pages` reads it): at the default 4 requests a second it is
#  under a minute of one site's time, and a judgement, not a measurement — nothing
#  about a site says how many of its pages an audit should read. What the number may
#  not do is decide a verdict, and past it none does: at it the crawl sets
#  `summary.truncated`; the fourteen inventory readers that pass by absence carry the
#  flag and the runner turns their PASS into NO_DATA; four withhold a non-PASS that is
#  not a floor — LO-198 (0.169.0), CI-008 and AR-162 (0.170.0), BL-081 (0.171.0); a
#  WARN or FAIL found in the pages read stands and says it is a floor (VRD-14), which
#  is how a warn band (CI-018, CN-039, AR-149, TE-168) reads over a cut crawl; CI-001,
#  CI-003, CI-005 and GEO-008 read the entry row. Under `--sample` the pool drawn from
#  a cut crawl is cut, and `withhold_cut_sample` turns a sampled PASS and an N/A read
#  off the pages into NO_DATA, a pool collapsed to the entry included (F11; F13 had
#  sent it back to `inherited` because it did not). So moving it trades requests and
#  time against how often an answer is withheld, never which answer is given. Driven
#  at its value in `tests/test_coverage_caps.py` `TheCrawlCaps`.
DEFAULT_MAX_PAGES = 100
# basis: convention — three hops from the entry, read by the runner's
#  `--crawl-depth`. It bounds the same items `DEFAULT_MAX_PAGES` does, through the same
#  flag: a page at the limit has its links dropped rather than queued, and a link
#  dropped is an internal target never fetched, which sets `summary.truncated` (since
#  0.88.0; before, the crawl reported itself complete). So it trades the same thing —
#  requests against how often an answer is withheld — and every verdict it could
#  decide, the `--sample` pool's included, is withheld or a floor by the same rules
#  (F11). Pages a sitemap lists enter at depth 0, which is why a site with a sitemap
#  rarely meets it. Driven at its value in `TheCrawlCaps`.
DEFAULT_DEPTH = 3

# Stripped before the text is hashed or counted, because a shared navigation and
# footer are most of the words on a small site: leaving them in makes every page a
# near-duplicate of every other and hides the thin ones. `duplicate_content.py` has
# always done this; it lives here now so there is one definition of "the content".
CHROME_TAGS = ("script", "style", "nav", "footer", "header", "aside", "noscript",
               "template")

# basis: convention — 100 hash functions, the 0.1.0 default argument (`num_hashes: int =
#  100`), a constant since 0.9.0. Since F15 (the owner's ruling on F03's CN-041) the
#  near-duplicate pairs reach a verdict: `duplicate_content.py` counts a pair of indexable
#  pages estimated at or over `NEAR_DUPLICATE_SIMILARITY` (0.85) into CN-041's
#  `summary.duplicate_content_findings`, a WARN. The signature is all this feeds, and
#  measured for 0.80.1 the same page pair estimates 0.68 to 0.81 similar across 25/100/400
#  functions and 3/5/9-word shingles — a spread of 0.13 under the line. So the pair decides
#  how sure an estimate is near the line, never an exact copy (the hash, a FAIL); the
#  judgement is that a hundred functions, a few milliseconds a page, is precise enough for
#  a warning. `tests/test_coverage_caps.py` `TheMinHashPairDecidesAWarningOnly` holds
#  that only CN-041 reads a near-duplicate field.
MINHASH_FUNCTIONS = 100
# basis: convention — the other half of the pair above, and the same argument: `k = 5`
#  arrived in 0.1.0 and the 0.68-to-0.81 spread was measured over both numbers together;
#  five-word shingles are the judgement that a shared phrase, not a shared word, is what
#  makes two pages alike. A basis block ends at the constant under it, so this one is
#  written out rather than shared; the two must move together or the spread means nothing.
SHINGLE_WORDS = 5


# A page number is a page of its own (MS-022, the owner's ruling for F15): `/blog?page=2`
# carries its own title and description, and folding it into `/blog` hid exactly the
# duplicate titles a paginated series shows. Only these names, and only with a number:
# every other query (tracking, sorting, filters) still folds into the page, because a
# key per filter would turn a faceted shop into thousands of "pages".
PAGE_NUMBER_PARAMS = ("page", "paged", "pg")


def page_key(url: str, base: str = "", numbered: bool = True) -> str:
    """One spelling per page.

    The root keeps its slash because an empty path is not a path; everything deeper
    loses it, so `/about` and `/about/` are one page. Getting this wrong is not
    subtle in its effects: stripping the root slash unconditionally turned
    `http://example.com/` into a second URL for the same document, both were
    crawled, and every site with a `href="/"` in its navigation — which is every
    site — was told its home page was `Critical` duplicate content.

    The path is spelled as requests sends it (`comparable_url`), so `/café` and
    `/caf%c3%a9` are one page, not two (the 2026-10-24 audit: false CN-041, MS-022,
    CI-008 and CI-018 findings). The query is dropped except a page number
    (`PAGE_NUMBER_PARAMS`), kept as its first `name=digits` pair, lower-cased and as a
    number; page 1 (or 0) is the page itself. `numbered=False` folds the page number
    too, for a comparison with a list that never carries one (GO-137's sitemap).
    """
    return _reduced(url, base, fold_slash=True, numbered=numbered)


def spelling_of(url: str, base: str = "") -> str:
    """A URL as a link spells it: the page key's reduction, its trailing slash kept.

    `/about` and `/about/` are one page and two URLs, and a server may answer one with
    a redirect to the other; AR-149 asks about each spelling a link uses.
    """
    return _reduced(url, base, fold_slash=False, fold_first=False)


def read_twice(pages: dict) -> set:
    """Keys of rows that are another row's page read again, so a reader counts it once.

    A row that redirected lands on a page: when the crawl read that page under its own
    key, or an earlier redirect already landed there, the row is the same document a
    second time — not a page with a title, links or a topic of its own (F15 reviews:
    MS-022, MS-029, CN-041, AR-153 and BL-081 each counted `/old` -> `/new` twice).
    """
    twice, landings = set(), set()
    for key, row in sorted(pages.items()):
        if not row.get("html") or not carries_content(row.get("status")):
            continue
        landed = page_key(row.get("final_url") or row.get("url") or key)
        if landed != key and (landed in pages or landed in landings):
            twice.add(key)
            continue
        landings.add(landed)
    return twice


def as_named(url: str) -> str:
    """A URL as a canonical names a page: requests' spelling, its query included, a
    trailing slash aside (`same_page`)."""
    parsed = urlparse(comparable_url(url))
    return urlunparse(parsed._replace(path=parsed.path.rstrip("/") or "/", fragment=""))


def same_page(a: str, b: str) -> bool:
    """Whether two URLs name one page as a canonical does: the same URL, its query
    included, a trailing slash aside. A page key drops the query, so `?id=2` read as
    `?id=1`'s self (F15); the slash stays folded, as the crawl folds it."""
    return as_named(a) == as_named(b)


def _page_number(value: str) -> int | None:
    """A page number as a number reads it, or None: `²` is a digit to `isdigit` and
    not to `int`, which also refuses a string of 4300+ digits (review round 2)."""
    if not (value.isascii() and value.isdigit()):
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _reduced(url: str, base: str, fold_slash: bool, numbered: bool = True,
             fold_first: bool = True) -> str:
    parsed = urlparse(comparable_url(normalize_url(url, base) if base
                                     else normalize_url(url)))
    path = parsed.path or "/"
    if path != "/" and fold_slash:
        path = path.rstrip("/") or "/"
    # Page 1 is the page itself (`/blog?page=1` serves `/blog` on most paginators),
    # and `?PAGE=02` is page 2 (review round 1).
    number = next((f"{name.lower()}={read}" for name, value
                   in parse_qsl(parsed.query, keep_blank_values=True)
                   if numbered and name.lower() in PAGE_NUMBER_PARAMS
                   and (read := _page_number(value)) is not None), "")
    if fold_first and (number.endswith("=1") or number.endswith("=0")):
        number = ""     # a spelling keeps it: `?page=1` may redirect (review round 4)
    return f"{parsed.scheme}://{parsed.netloc}{path}" + (f"?{number}" if number else "")


# ---------------------------------------------------------------------------
# Content fingerprints
# ---------------------------------------------------------------------------

def content_text(soup) -> str:
    """The page's own words, with the site chrome removed.

    Destructive to `soup`: call it after everything else has been read off the
    parse, which is what `_read_page` does.
    """
    for tag in soup(list(CHROME_TAGS)):
        tag.decompose()
    body = soup.find("body")
    return body.get_text(separator=" ", strip=True) if body else ""


def word_count(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text or ""))


def exact_hash(text: str) -> str:
    """SHA-256 of normalized text, for exact-duplicate detection."""
    return hashlib.sha256(re.sub(r"\s+", " ", (text or "").lower().strip())
                          .encode()).hexdigest()


def shingle(text: str, k: int = SHINGLE_WORDS) -> set:
    words = re.findall(r"\b\w+\b", (text or "").lower())
    if len(words) < k:
        return set()
    return {" ".join(words[i:i + k]) for i in range(len(words) - k + 1)}


def minhash_signature(shingles: set, num_hashes: int = MINHASH_FUNCTIONS) -> list:
    """MinHash signature: the comparable form of a page's text.

    The 0.85 similarity threshold was originally calibrated against ASCII-only
    shingles of English fixtures. Keep the hash construction stable while using
    the Unicode word population measured in 0.37.0.
    """
    if not shingles:
        return []
    return [min(int(hashlib.md5(f"{i}:{s}".encode()).hexdigest(), 16)
                for s in shingles)
            for i in range(num_hashes)]


def jaccard_from_minhash(sig1: list, sig2: list) -> float:
    """Estimate Jaccard similarity from two MinHash signatures.

    Return 0.0 when either signature is empty: the pair is not comparable, and
    must not be reported as identical.

    `strict=True` because the estimate is only valid over signatures of the same
    length: `zip` stops at the shorter one while the denominator stays `len(sig1)`,
    so a short signature does not raise — it returns a similarity biased downwards,
    and a pair of duplicate pages quietly falls under the threshold.
    """
    if not sig1 or not sig2:
        return 0.0
    matches = sum(1 for a, b in zip(sig1, sig2, strict=True) if a == b)
    return matches / len(sig1)


# ---------------------------------------------------------------------------
# robots / noindex
# ---------------------------------------------------------------------------

def _directives(value: str | None) -> set[str]:
    if not value:
        return set()
    return {token.strip().lower() for token in re.split(r"[\s,;]+", value)
            if token.strip()}


def has_noindex(meta_robots: str | None, headers: dict | None = None) -> bool:
    """Whether this page asks not to be indexed, by meta tag or header.

    The header matters as much as the tag and is invisible in the HTML, which is
    why it is read here rather than left to each caller: a page kept out of the
    index by `X-Robots-Tag` is not competing for anything, so asking somebody to
    write 300 more words for it is a fix-list entry that should not exist.
    """
    for value in (meta_robots, (headers or {}).get("x-robots-tag")):
        directives = _directives(value)
        if "noindex" in directives or "none" in directives:
            return True
    return False


# ---------------------------------------------------------------------------
# Sitemap
# ---------------------------------------------------------------------------

def load_sitemap_urls(site_url: str, sitemap_urls: list[str] | None = None,
                      timeout: int = 15, max_sitemaps: int = 25,
                      fetch=fetch_url, include_fetch_targets: bool = False) -> dict:
    """Every URL the site's sitemaps list, as page keys.

    `fetch` is injectable only so the crawl can count its own requests; there is no
    second HTTP path here.
    """
    queue = list(dict.fromkeys(
        sitemap_urls or discover_sitemap_urls(site_url, timeout=timeout)))
    seen_sitemaps: set[str] = set()
    urls: list[str] = []
    errors: list[dict] = []
    # A sitemap on another host is named and never requested: robots.txt and a
    # sitemap index are the audited site's words, and following them off the site
    # made this walk a GET proxy to any public host and port. The www variant and
    # the other scheme are the same site, as everywhere else here (`same_host`).
    off_host_sitemaps: list[str] = []
    read_bytes, dropped_urls = 0, 0

    while queue and len(seen_sitemaps) < max_sitemaps:
        if read_bytes >= SITEMAP_BYTES_BUDGET:
            break
        sitemap_url = normalize_url(queue.pop(0), site_url)
        if sitemap_url in seen_sitemaps or sitemap_url in off_host_sitemaps:
            continue
        if not same_host(site_url, sitemap_url):
            off_host_sitemaps.append(sitemap_url)
            continue
        seen_sitemaps.add(sitemap_url)
        fetched = fetch(sitemap_url, timeout=timeout, max_bytes=8_000_000, keep_body=True)
        # The body's bytes, not its characters, and an error page's too (HTTP-10).
        read_bytes += fetched.get("bytes") or 0
        if not carries_content(fetched.get("status")) or not fetched.get("text"):
            errors.append({"url": sitemap_url, "status": fetched.get("status"),
                           "error": fetched.get("error"),
                           "error_kind": fetched.get("error_kind")})
            continue
        parsed = parse_sitemap_xml(sitemap_document(fetched), sitemap_url)
        if parsed.get("error"):
            errors.append({"url": sitemap_url, "error": parsed["error"]})
            continue
        queue.extend(item["loc"] for item in parsed.get("sitemaps", []))
        locs = [item["loc"] for item in parsed.get("urls", [])]
        room = max(0, SITEMAP_URLS_BUDGET - len(urls))
        urls.extend(locs[:room])
        dropped_urls += max(0, len(locs) - room)

    # A sitemap listing another host's URLs is a real defect and it is
    # `sitemap_checker.py`'s to report. Here they are only kept out of the way: a
    # crawl that followed them would leave the site it was asked about, and leaving
    # them in `urls` would make each one look like an orphan — an off-host URL is
    # unreachable by internal link by definition, so link-profile readers would
    # fault every site whose sitemap has one, for the wrong reason.
    deduped, off_host, seen = [], [], set()
    fetch_targets: dict[str, str] = {}
    for url in urls:
        discovered = normalize_url(url, site_url)
        key = page_key(discovered)
        if key in seen:
            continue
        seen.add(key)
        # The URL as listed: a key is punycode, and an IDN site named in Unicode is
        # still its own host (review round 4).
        if same_host(comparable_url(site_url), comparable_url(discovered)):
            deduped.append(key)
            fetch_targets[key] = discovered
        else:
            off_host.append(key)
    unvisited, queued = [], set()
    for candidate in queue:
        sitemap_url = normalize_url(candidate, site_url)
        if not same_host(site_url, sitemap_url):
            if sitemap_url not in off_host_sitemaps:
                off_host_sitemaps.append(sitemap_url)
        elif sitemap_url not in seen_sitemaps and sitemap_url not in queued:
            queued.add(sitemap_url)
            unvisited.append(sitemap_url)
    cut = []
    if read_bytes >= SITEMAP_BYTES_BUDGET and unvisited:
        cut.append(f"the sitemap byte budget ({SITEMAP_BYTES_BUDGET} bytes) was spent "
                   f"with {len(unvisited)} sitemap(s) unread")
    if dropped_urls:
        cut.append(f"the sitemap URL budget ({SITEMAP_URLS_BUDGET}) was reached and "
                   f"{dropped_urls} listed URL(s) were not kept")
    result = {"sitemaps_checked": sorted(seen_sitemaps), "urls": deduped,
              "off_host": off_host, "errors": errors,
              "unvisited": unvisited, "off_host_sitemaps": off_host_sitemaps,
              "cut": cut}
    if include_fetch_targets:
        # Crawl-only transport detail, removed before the inventory is written.
        # The first sitemap spelling wins when `/about` and `/about/` share a
        # page key: one fetch is enough, and first-seen keeps the crawl stable.
        result["_fetch_targets"] = fetch_targets
    return result


# ---------------------------------------------------------------------------
# The crawl
# ---------------------------------------------------------------------------

def _read_page(fetched: dict, key: str, discovered_url: str, site_url: str,
               signatures: bool = True) -> dict:
    """Everything worth writing down about one fetched page, from one parse."""
    row = {
        "url": discovered_url,
        "final_url": fetched.get("url") or discovered_url,
        "status": fetched.get("status"),
        "content_type": (fetched.get("headers") or {}).get("content-type", ""),
        "redirect_chain": fetched.get("redirect_chain") or [],
        "bytes": fetched.get("bytes") or 0,
        "error": fetched.get("error"),
        "error_kind": fetched.get("error_kind"),
        # The connection broke while the body was read (`fetch_url`); with a timeout
        # and a refused connection, what makes a page one that gave no answer (F04).
        "cut_off": bool(fetched.get("cut_off")),
        "robots_blocked": bool(fetched.get("robots_blocked")),
        "title": None,
        "meta_description": None,
        "meta_robots": None,
        "canonical": None,
        "canonicals": [],
        "noindex": False,
        "content_words": 0,
        "text_hash": None,
        "signature": None,
        "internal_out": 0,
        "unique_internal_out": 0,
        "external_out": 0,
        "links": [],
        "images": [],
        "html": False,
        # One compact row per parseable JSON-LD node. Site-wide schema checks need
        # the types, not a second fetch of every page or the full raw payload.
        "schema_nodes": [],
        # The declared `<html lang>`. Free — the parse below already produced it — and
        # it is what lets a reader tell one language section of a site from another
        # without inferring anything from URL shape. anchor_text_audit.py needs it:
        # "this pair appears on most pages" is false of a menu that exists once per
        # language, and on a trilingual site no menu entry reaches a third of the crawl.
        # Measured rather than guessed, which is the only reason it belongs here.
        "lang": None,
    }
    row["redirected"] = bool(row["redirect_chain"])
    text = fetched.get("text") or ""
    if not carries_content(fetched.get("status")) or not text:
        return row
    if "html" not in row["content_type"] and row["content_type"]:
        # An audit of a PDF or a stylesheet is not a page audit. Recorded with its
        # status — a link to it is still a link that resolves — but not parsed.
        return row

    parsed = parse_html(text, row["final_url"])
    row["html"] = True
    row["title"] = parsed.get("title")
    row["meta_description"] = parsed.get("meta_description")
    row["meta_robots"] = parsed.get("meta_robots")
    # Every canonical the response declares, the `Link` header's included, as
    # `declared_canonicals` reads them (TE-176, the owner's ruling for F15): the first
    # `<link>` alone hid a header canonical and a conflict. `canonical` is the one a
    # crawler can use — none when two disagree, as Google ignores them all then.
    row["canonicals"] = declared_canonicals(parsed, fetched.get("headers"),
                                            row["final_url"])
    row["canonical"] = row["canonicals"][0] if len(row["canonicals"]) == 1 else None
    row["lang"] = parsed.get("lang")
    row["noindex"] = has_noindex(parsed.get("meta_robots"), fetched.get("headers"))
    # Inventory every @type the document declares, including contributed blocks.
    for document in parsed.get("schema") or []:
        for node in walk_json(document):
            if not isinstance(node, dict):
                continue
            types = [value for value in as_list(node.get("@type"))
                     if isinstance(value, str)]
            if types:
                row["schema_nodes"].append({"types": types})

    # One requestable URL per image reference, in document order. The parser has
    # already built the soup, and the shared helpers keep srcset and picture parsing
    # identical to the page-level image audits.
    seen_images = set()

    def record_image(candidate: str) -> None:
        resolved = urljoin(row["final_url"], candidate)
        if urlparse(resolved).scheme not in ("http", "https"):
            return
        if resolved not in seen_images:
            seen_images.add(resolved)
            row["images"].append(resolved)

    for img in parsed["soup"].find_all("img"):
        # `<source>` precedes the fallback `<img>` in valid picture markup.
        for source in picture_sources(img, row["final_url"]):
            for candidate in source["urls"]:
                record_image(candidate)
        if img.get("src"):
            record_image(img["src"])
        for candidate in srcset_urls(img.get("srcset") or ""):
            record_image(candidate)

    # Every `<a>`, with nothing deduplicated. The first version of this collapsed
    # repeats of the same (target, anchor) within a page — which is exactly the shape
    # of anchor stuffing, so five identical links to one URL became one link and
    # BL-081 stopped being able to see the thing it exists for. Readers that want
    # unique targets ask for them: `unique_internal_out` here, `inbound_map` there.
    for link in parsed.get("links") or []:
        href = link.get("href") or ""
        if not href:
            continue
        internal = same_host(site_url, href)
        target = page_key(href, row["final_url"]) if internal else normalize_url(
            href, row["final_url"])
        rel = [str(v).lower() for v in (link.get("rel") or [])]
        row["links"].append({
            "target": target,
            # Private crawl state: retain what the page actually linked so the
            # queue fetches it, while `target` remains the dedup/orphan key. Removed
            # by `_finish`; the public link contract continues to expose page keys.
            "_fetch_url": normalize_url(href, row["final_url"]),
            # Its text, else what names it: an image link's alt (`parse_html`).
            "anchor": (link.get("name") or link.get("text") or "").strip(),
            # Named by an image's alt or `aria-label`, not by text: a card's image link
            # beside its title link is one choice of words, not two (BL-081, F15).
            "alt_named": not (link.get("text") or "").strip()
                         and bool((link.get("name") or "").strip()),
            "rel": rel,
            "nofollow": "nofollow" in rel,
            "internal": internal,
        })
    internal = [link for link in row["links"] if link["internal"]]
    row["internal_out"] = len(internal)
    row["unique_internal_out"] = len({link["target"] for link in internal})
    row["external_out"] = len(row["links"]) - row["internal_out"]

    # Last, because it strips the chrome out of the soup we just read the links from.
    text = content_text(parsed["soup"])
    row["content_words"] = word_count(text)
    row["text_hash"] = exact_hash(text) if text.strip() else None
    if signatures and text.strip():
        row["signature"] = minhash_signature(shingle(text))
    return row


def crawl(site_url: str, depth: int = DEFAULT_DEPTH,
          max_pages: int = DEFAULT_MAX_PAGES, timeout: int = 15,
          workers: int = 5, sitemap_urls: list[str] | None = None,
          use_sitemap: bool = True, signatures: bool = True) -> dict:
    """Crawl once and return the inventory.

    Breadth-first from the entry URL, with the sitemap's URLs as additional seeds so
    a page nothing links to still gets a status — `discovered_by` keeps the two
    apart, because a sitemap-only page is exactly what an orphan is.

    robots.txt governs every URL except the entry: the operator asked about that one,
    and everything else we found ourselves. A refusal shrinks the crawl and is
    recorded as a refusal, never as a page the site got wrong — that mistake has been
    made three times in this tree and each time it turned our own politeness into the
    site's defect.
    """
    site_url = normalize_url(site_url)
    entry = page_key(site_url)
    counter = {"requests": 0}
    lock = threading.Lock()

    def _fetch(url: str, **kw) -> dict:
        with lock:
            counter["requests"] += 1
        return fetch_url(url, **kw)

    sitemap = ({"sitemaps_checked": [], "urls": [], "off_host": [], "errors": [],
                "unvisited": [], "off_host_sitemaps": [], "cut": [],
                "_fetch_targets": {}}
               if not use_sitemap
               else load_sitemap_urls(site_url, sitemap_urls=sitemap_urls,
                                      timeout=timeout, fetch=_fetch,
                                      include_fetch_targets=True))
    sitemap_fetch_targets = sitemap.pop("_fetch_targets", {})
    sitemap_set = set(sitemap["urls"])

    pages: dict[str, dict] = {}
    robots_blocked: dict[str, str] = {}
    queue: deque = deque([(entry, site_url, 0, "entry")])
    queued = {entry}
    for key in sitemap["urls"]:
        if key not in queued:
            queued.add(key)
            queue.append((key, sitemap_fetch_targets.get(key, key), 0, "sitemap"))

    def fetch_one(job: tuple) -> tuple:
        key, discovered_url, page_depth, source = job
        # `respect_robots` off for the entry only. See the docstring: the asymmetry
        # is deliberate and load-bearing.
        fetched = _fetch(discovered_url, timeout=timeout, max_bytes=2_000_000,
                         respect_robots=source != "entry")
        if gave_no_answer(fetched):
            # Asked once more, then withheld (F04, the owner's decision on H13-c): a
            # timeout or a reset is often the moment rather than the page. A second
            # silence leaves the page unread and the crawl cut (`_finish`).
            fetched = _fetch(discovered_url, timeout=timeout, max_bytes=2_000_000,
                             respect_robots=source != "entry")
        return job, fetched

    while queue and len(pages) < max_pages:
        batch = []
        while queue and len(batch) < workers and len(pages) + len(batch) < max_pages:
            job = queue.popleft()
            if job[0] in pages or job[0] in robots_blocked:
                continue
            batch.append(job)
        if not batch:
            break

        # Submit in parallel, read in submission order.
        # `as_completed` would make the page set depend on which request finished first
        # once `max_pages` bites, and an inventory that differs between two runs of the
        # same site is one nobody can diff.
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            for future in [pool.submit(fetch_one, job) for job in batch]:
                (key, discovered_url, page_depth, source), fetched = future.result()
                if fetched.get("robots_blocked"):
                    robots_blocked[key] = fetched.get("error") or "robots.txt"
                    continue
                row = _read_page(fetched, key, discovered_url, site_url, signatures)
                row["depth"] = page_depth
                row["discovered_by"] = source
                row["in_sitemap"] = key in sitemap_set
                pages[key] = row
                if page_depth >= depth:
                    continue
                for link in row["links"]:
                    if not link["internal"]:
                        continue
                    target = link["target"]
                    if target not in queued and len(queued) < max_pages * 4:
                        queued.add(target)
                        queue.append((target, link["_fetch_url"], page_depth + 1,
                                      "link"))

    spellings = _linked_spellings(pages, _fetch, timeout, max_pages)
    return _finish(site_url, entry, pages, robots_blocked, sitemap, sitemap_set,
                   counter["requests"], depth, max_pages, bool(queue), signatures,
                   spellings)


def _linked_spellings(pages: dict, fetch, timeout: int, budget: int) -> dict:
    """Every internal link's own spelling of a page the crawl read under another one.

    The crawl fetches one spelling per page key, so a 301 `/about/` linked beside a
    200 `/about` was never asked for (AR-149, the owner's ruling for F15). Each such
    spelling is fetched once, up to `budget` of them (the page budget); past it a
    spelling is recorded unchecked, which withholds AR-149's pass. A spelling that is
    where a page landed is not asked again: it answered at the end of a chain.
    """
    known = {}
    for row in pages.values():
        known[spelling_of(row["url"])] = True
        if not str(row.get("status") or "").startswith("3"):
            known[spelling_of(row["final_url"])] = True
    wanted: dict[str, str] = {}
    for row in pages.values():
        for link in row["links"]:
            if not link["internal"] or link["target"] not in pages:
                continue
            spelled = spelling_of(link["_fetch_url"])
            if spelled not in known:
                wanted.setdefault(spelled, link["target"])
    spellings = {}
    for count, (spelled, key) in enumerate(sorted(wanted.items())):
        if count >= budget:
            spellings[spelled] = {"key": key, "status": None, "unchecked": True}
            continue
        fetched = fetch(spelled, timeout=timeout, max_bytes=2_000_000,
                        respect_robots=True)
        spellings[spelled] = {
            "key": key, "status": fetched.get("status"),
            "final_url": fetched.get("url") or spelled,
            "redirect_chain": fetched.get("redirect_chain") or [],
            "error_kind": fetched.get("error_kind"),
            # A refusal, a silence or a server too busy to say (429, 5xx) is a spelling
            # nobody read, not a redirect absent (F15 review round 3).
            "unchecked": bool(fetched.get("robots_blocked") or gave_no_answer(fetched)
                              or fetched.get("error_kind") == "blocked"
                              or fetched.get("status") == 429
                              or (fetched.get("status") or 0) >= 500),
        }
    return spellings


def _finish(site_url: str, entry: str, pages: dict, robots_blocked: dict,
            sitemap: dict, sitemap_set: set, requests: int, depth: int,
            max_pages: int, more_queued: bool, signatures: bool,
            spellings: dict | None = None) -> dict:
    spellings = spellings or {}
    inbound: dict[str, list] = defaultdict(list)
    external_targets: dict[str, list] = defaultdict(list)
    # Who links each spelling: a redirect is the links' defect only for the spelling
    # they use (AR-149: a sitemap's `/about/` 301 is not a link's when links say `/about`).
    by_spelling: dict[str, set] = defaultdict(set)
    for key, row in pages.items():
        for link in row["links"]:
            (inbound if link["internal"] else external_targets)[link["target"]].append(
                {"source": key, "anchor": link["anchor"],
                 "nofollow": link["nofollow"]})
            if link["internal"]:
                by_spelling[spelling_of(link.pop("_fetch_url", None)
                                        or link["target"])].add(key)
            link.pop("_fetch_url", None)

    internal_targets = set(inbound)
    unchecked = sorted(internal_targets - set(pages) - set(robots_blocked))
    # A page this audit's guard refused is a key in `pages` and was never read, so the
    # subtraction above cannot see it (HTTP-13): a redirect to another port left the
    # crawl reporting itself complete, and MS-022, CN-041 and AR-149 passed over it.
    refused = sorted(key for key, row in pages.items()
                     if row.get("error_kind") == "blocked")
    # A page that gave no answer twice is the same gap from the site's side: a row,
    # never read (F04, H13-c). Below the page budget the crawl called itself complete
    # and MS-022 and the other readers that pass by finding nothing passed over it.
    unanswered = sorted(key for key, row in pages.items() if gave_no_answer(row))
    # Reachable means linked-to, not fetched. The entry counts because it is where a
    # visitor and a crawler both start.
    reachable = {entry} | {key for key, sources in inbound.items() if sources}

    broken = []
    for key in sorted(pages):
        row = pages[key]
        if row["robots_blocked"]:
            continue
        if row["error"] or (row["status"] or 0) >= 400:
            broken.append({
                "url": row["url"],
                "status": row["status"],
                "error": row["error"],
                "error_kind": row.get("error_kind"),
                "linked_from": sorted({s["source"] for s in inbound.get(key, [])}),
            })
    redirected = [{"url": pages[key]["url"], "to": pages[key]["final_url"],
                   "hops": len(pages[key]["redirect_chain"]),
                   "linked_from": sorted(by_spelling.get(spelling_of(pages[key]["url"]),
                                                         ()))}
                  for key in sorted(pages) if pages[key]["redirected"]]
    redirected += [{"url": spelled, "to": row["final_url"],
                    "hops": len(row["redirect_chain"]),
                    "linked_from": sorted(by_spelling.get(spelled, ()))}
                   for spelled, row in sorted(spellings.items())
                   if row.get("redirect_chain")]
    unchecked_spellings = sorted(spelled for spelled, row in spellings.items()
                                 if row.get("unchecked"))

    html_pages = [row for row in pages.values() if row["html"]]
    return {
        "inventory_version": INVENTORY_VERSION,
        "site": site_url,
        "entry": entry,
        "crawled_at": datetime.now(timezone.utc).isoformat(),
        "depth": depth,
        "max_pages": max_pages,
        "signatures": signatures,
        # Nothing was read at all. Every script reading this inventory copies it
        # through, so the runner turns one crawl failure into NO_DATA for all
        # items rather than confident verdicts about nothing.
        "fetch_error": None if html_pages else "no page could be crawled",
        "fetch_error_kind": (None if html_pages
                             else refused_kind(row.get("error_kind")
                                               for row in pages.values())),
        "summary": {
            "requests": requests,
            "pages_fetched": len(pages),
            "pages_html": len(html_pages),
            "pages_broken": len(broken),
            "pages_redirected": len(redirected),
            # Linked spellings past the budget or never answered (AR-149 withholds).
            "unchecked_spellings": len(unchecked_spellings),
            "robots_blocked": len(robots_blocked),
            "internal_links": sum(row["internal_out"] for row in pages.values()),
            "external_links": sum(row["external_out"] for row in pages.values()),
            "unique_internal_targets": len(internal_targets),
            "unique_external_targets": len(external_targets),
            "unchecked_internal_targets": len(unchecked),
            "sitemaps_checked": len(sitemap["sitemaps_checked"]),
            "sitemap_urls": len(sitemap_set),
            "sitemap_urls_off_host": len(sitemap.get("off_host") or ()),
            "reachable_pages": len(reachable),
            # The cap bit, not a judgement: a truncated crawl understates every
            # count above and a reader has to be able to tell.
            #
            # `unchecked` is the third way, and it was missing until 0.88.0 — which
            # made this flag wrong in the one direction that matters. Links from a
            # page sitting at `--depth` are never queued, so on a site deeper than
            # the limit the queue empties on its own: `more_queued` is False, the
            # page budget is untouched, and the crawl reported itself complete
            # having read part of the site. Measured on a five-page chain at
            # `depth=2`: three pages read, one internal target never fetched,
            # `truncated` False. It is exactly the subtraction the orphan check
            # already makes — `internal_targets - pages - robots_blocked` — so a
            # page refused on purpose is politeness and does not count here.
            "refused_pages": len(refused),
            "unanswered_pages": len(unanswered),
            #
            # `len(pages) >= max_pages` stays on its own, as the cautious side of the
            # budget (F11's second review): a page that gave no answer — a timeout —
            # is a row in `pages` like a page read, so `unchecked` cannot see it, and
            # dropping the clause let a crawl of exactly the budget with one such page
            # call itself complete and pass MS-022 over the page it never read. At the
            # budget an answer is withheld that a crawl one page larger would give; that
            # is the trade the cap's basis line names, not a verdict the cap decides.
            "truncated": (more_queued or len(pages) >= max_pages
                          or bool(unchecked) or bool(refused) or bool(unanswered)),
        },
        "pages": pages,
        "reachable": sorted(reachable),
        "unchecked_internal_targets": unchecked,
        "robots_blocked": {key: why for key, why in sorted(robots_blocked.items())},
        "sitemap": sitemap,
        "broken": broken,
        "redirected": redirected,
        "spellings": spellings,
        "external_targets": {url: sources for url, sources
                             in sorted(external_targets.items())},
    }


# ---------------------------------------------------------------------------
# Reading one back
# ---------------------------------------------------------------------------

# The fetch layer's kinds for a request nothing answered: no status, no refusal of ours.
# A guard refusal, a robots decline, a TLS failure and any HTTP status are answers.
NO_ANSWER_KINDS = ("timeout", "refused")


def gave_no_answer(fetched: dict) -> bool:
    return (fetched.get("status") is None
            and (fetched.get("error_kind") in NO_ANSWER_KINDS
                 or bool(fetched.get("cut_off"))))


def load(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        inventory = json.load(fh)
    version = inventory.get("inventory_version")
    if version != INVENTORY_VERSION:
        raise ValueError(f"inventory version {version!r}, expected "
                         f"{INVENTORY_VERSION}: {path}")
    return inventory


def inventory_for(site_url: str, path: str = "", **kw) -> dict:
    """The inventory for this site: the artifact if given one, else crawl now.

    Two entry points, one implementation. The artifact is checked against the site
    it is supposed to describe, for the same reason the browser artifacts are: a
    crawl of some other host decides sixteen items — two `critical`, nine `high` — from
    observations nobody made about this one. A mismatch is `fetch_error`, which
    every reader propagates, so it lands as NO_DATA with the reason rather than as a
    verdict.
    """
    if not path:
        return crawl(site_url, **kw)
    try:
        inventory = load(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {"inventory_version": INVENTORY_VERSION, "site": site_url,
                "pages": {}, "summary": {}, "fetch_error":
                f"the crawl inventory could not be read: {exc}"}
    if not same_host(inventory.get("site") or "", site_url):
        return dict(inventory, fetch_error=(
            f"the crawl inventory describes {inventory.get('site')!r}, not "
            f"{site_url!r}"))
    return inventory


def inbound_map(inventory: dict) -> dict[str, list]:
    """target -> [{source, anchor, nofollow}], computed rather than stored.

    Stored twice is stored wrong eventually: the per-page `links` are the record and
    this is a view of them.
    """
    inbound: dict[str, list] = defaultdict(list)
    for key, row in (inventory.get("pages") or {}).items():
        for link in row.get("links") or []:
            if link.get("internal"):
                inbound[link["target"]].append({
                    "source": key, "anchor": link.get("anchor") or "",
                    "nofollow": bool(link.get("nofollow"))})
    return inbound


def html_pages(inventory: dict) -> dict[str, dict]:
    """The pages that returned HTML — the ones with content to analyse."""
    return {key: row for key, row in (inventory.get("pages") or {}).items()
            if row.get("html")}


# The next two exist so these key names live where they are written instead of in
# every reader. Three scripts subtract robots-refused URLs from a set, and getting
# the key wrong does not raise: it reads as an empty set, the subtraction quietly
# does nothing, and the tool reports **its own politeness as the site's defect**.
# That bug shipped once in the former sitemap-orphan reader before 0.4.0, and it was
# written again in `server_log_audit.py`, which looked for `sitemap.robots_blocked`
# for something that lives at the top level. A shared accessor can only be
# misspelled in every caller at once, which is a failure somebody notices.
def sitemap_urls(inventory: dict) -> list[str]:
    """Every URL the site's sitemaps listed, as page keys."""
    return list((inventory.get("sitemap") or {}).get("urls") or ())


def sitemap_incomplete(inventory: dict) -> str:
    """Why the sitemap set this crawl was seeded from is not the whole list, or "".

    The walk's limits cut the set without setting `summary.truncated` (F11): a byte or
    URL budget, files past the file cap, a sitemap on another host, a file that gave no
    HTTP answer. A sitemap the site serves broken (a 404, XML that does not parse) is
    the site's answer, not a cut: a search engine reads nothing from it either.
    """
    sitemap = inventory.get("sitemap") or {}
    parts = list(sitemap.get("cut") or ())
    unvisited = sitemap.get("unvisited") or ()
    if unvisited and not parts:
        parts.append(f"{len(unvisited)} sitemap file(s) past the walk's file cap were "
                     f"not read")
    off_host = sitemap.get("off_host_sitemaps") or ()
    if off_host:
        parts.append(f"{len(off_host)} sitemap(s) on another host were not requested")
    # A fetch failure carries `status`; a parse failure has none to carry.
    unanswered = [e for e in sitemap.get("errors") or ()
                  if isinstance(e, dict) and "status" in e and e["status"] is None]
    if unanswered:
        parts.append(f"{len(unanswered)} sitemap(s) gave no answer")
    return "; ".join(parts)


def robots_refused(inventory: dict) -> dict[str, str]:
    """URL -> why the crawl did not fetch it. Ours to explain, not the site's fault."""
    return dict(inventory.get("robots_blocked") or {})


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Crawl a site once into an inventory every site-wide check reads")
    parser.add_argument("url", help="Site URL to crawl")
    parser.add_argument("--depth", type=int, default=DEFAULT_DEPTH,
                        help=f"link depth from the entry (default: {DEFAULT_DEPTH})")
    parser.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES,
                        help=f"page budget (default: {DEFAULT_MAX_PAGES})")
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument("--workers", type=int, default=5,
                        help="concurrent fetches (the shared rate limit still applies)")
    parser.add_argument("--no-sitemap", action="store_true",
                        help="crawl links only; do not seed from the sitemap")
    parser.add_argument("--no-signatures", action="store_true",
                        help="skip the MinHash signatures; near-duplicate detection "
                             "needs them, nothing else does")
    parser.add_argument("--out", default="",
                        help="write the inventory here; --json then prints the summary")
    parser.add_argument("--json", "-j", action="store_true", help="Output JSON")
    args = parser.parse_args()

    inventory = crawl(args.url, depth=args.depth, max_pages=args.max_pages,
                      timeout=args.timeout, workers=args.workers,
                      use_sitemap=not args.no_sitemap,
                      signatures=not args.no_signatures)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(inventory, fh, ensure_ascii=False)
        result = {k: inventory[k] for k in
                  ("inventory_version", "site", "entry", "crawled_at", "depth",
                   "max_pages", "fetch_error", "summary")}
        result["inventory"] = args.out
        result["broken"] = inventory["broken"]
        result["redirected"] = inventory["redirected"]
    else:
        result = inventory

    s = inventory["summary"]
    lines = [
        f"Crawled {inventory['site']} — {s['pages_fetched']} page(s), "
        f"{s['requests']} request(s)",
        f"HTML: {s['pages_html']}  broken: {s['pages_broken']}  "
        f"redirected: {s['pages_redirected']}  robots-blocked: {s['robots_blocked']}",
        f"Internal links: {s['internal_links']} to {s['unique_internal_targets']} "
        f"target(s), {s['unchecked_internal_targets']} not checked",
        f"Sitemap URLs: {s['sitemap_urls']}  reachable by link: {s['reachable_pages']}",
    ]
    if s["truncated"]:
        # Named by what cut it: a refused or silent page is not a cap (F04 review).
        why = [f"{s[key]} page(s) {words}" for key, words in
               (("refused_pages", "refused by this audit's guard"),
                ("unanswered_pages", "gave no answer, asked twice")) if s.get(key)]
        cause = "; ".join(why) or "at --max-pages %d" % inventory["max_pages"]
        lines.append(f"Truncated ({cause}): every count above understates the site")
    for row in inventory["broken"][:25]:
        lines.append(f"  broken: {row['url']} "
                     f"[{row['status'] or row['error']}] "
                     f"linked from {len(row['linked_from'])} page(s)")
    print_json_or_text(result, args.json, lines)


if __name__ == "__main__":
    from lib.typed_credential import credentials_beside_argv
    credentials_beside_argv()
    main()
