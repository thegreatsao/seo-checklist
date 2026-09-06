#!/usr/bin/env python3
"""One crawl of a site, written down once, for every check that needs the whole site.

Six scripts used to walk the same pages independently — `duplicate_content.py` at 50
pages, `link_profile.py` at 50, `internal_links.py` at 50,
`orphan_pages_from_sitemap.py` at 100, `anchor_text_audit.py` at 25, and
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

**What is one page.** A page key is `scheme://host/path` with the query dropped and
the trailing slash removed from everything but the root. So `/a`, `/a/` and `/a?x=1`
are one page here. That is what the six scripts already did separately, and it is
what makes `?page=2` not a duplicate of `?page=3` — the item that cares about query
variants (`faceted_nav_audit.py`, AR-163) reads URLs, not this inventory.

**What "reachable" means.** A page reached by following a link from another crawled
page. Fetching a URL out of a sitemap does not make it reachable — that distinction
is the whole of GO-137, so seeding from the sitemap must not quietly satisfy it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import threading
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

from seo_common import (
    as_list,
    discover_sitemap_urls,
    fetch_url,
    normalize_url,
    parse_html,
    parse_sitemap_xml,
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
INVENTORY_VERSION = 4

# basis: inherited — 100 pages, present at import, and the widest-reaching number
#  here: every site-wide item reads this crawl, and nine of them pass by finding
#  none of something. Raising it costs requests linearly; leaving it means a site
#  past 100 pages is judged on 100 of them, which is why `summary.truncated` now
#  withholds those verdicts instead of only annotating them.
DEFAULT_MAX_PAGES = 100
# basis: inherited — three hops from the entry, present at import. It bounds the same
#  nineteen verdicts `DEFAULT_MAX_PAGES` does, and less visibly: a page at the limit
#  has its links dropped rather than queued, so the crawl stops without any budget
#  being spent. Pages a sitemap lists enter at depth 0 and are unaffected, which is
#  why a site with a sitemap rarely meets this number at all.
DEFAULT_DEPTH = 3

# Stripped before the text is hashed or counted, because a shared navigation and
# footer are most of the words on a small site: leaving them in makes every page a
# near-duplicate of every other and hides the thin ones. `duplicate_content.py` has
# always done this; it lives here now so there is one definition of "the content".
CHROME_TAGS = ("script", "style", "nav", "footer", "header", "aside", "noscript",
               "template")

# basis: inherited — present at import: both arrived in 0.1.0 as default arguments
#  (`num_hashes: int = 100`, `k: int = 5`) and became constants in 0.9.0, when six crawls
#  became one. Measured for 0.80.1 rather than left as a name: they feed the MinHash
#  signature and nothing else, the signature feeds `jaccard_from_minhash`, and that feeds
#  `near_duplicates` alone. **No registry assertion reads any near-duplicate field** — the
#  four items over `duplicate_content.py` read the exact hash (CN-041), titles (MS-022),
#  descriptions (MS-029) and a word count (CN-039), and none of those passes through here.
#  What they do decide is a claim printed about the site: across 25/100/400 functions and
#  3/5/9-word shingles the same page pair estimates 0.68 to 0.81 similar — a spread of
#  0.13 under a 0.85 reporting line. The four asserted fields were measured across the same
#  nine settings and did not move, which the code also guarantees: none of them is computed
#  from a signature. Pointing any item at `near_duplicate_pairs` promotes both of these to
#  thresholds, and this line with them.
MINHASH_FUNCTIONS = 100
# basis: inherited — the other half of the pair above, and the same argument: `k = 5`
#  arrived in 0.1.0, nothing here chose it, and the 0.68-to-0.81 spread was measured over
#  both numbers together. A basis block ends at the constant under it, so this one is
#  written out rather than shared; the two must move together or the spread means nothing.
SHINGLE_WORDS = 5


def page_key(url: str, base: str = "") -> str:
    """One spelling per page.

    The root keeps its slash because an empty path is not a path; everything deeper
    loses it, so `/about` and `/about/` are one page. Getting this wrong is not
    subtle in its effects: stripping the root slash unconditionally turned
    `http://example.com/` into a second URL for the same document, both were
    crawled, and every site with a `href="/"` in its navigation — which is every
    site — was told its home page was `Critical` duplicate content.
    """
    parsed = urlparse(normalize_url(url, base) if base else normalize_url(url))
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/") or "/"
    return f"{parsed.scheme}://{parsed.netloc}{path}"


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
    sig = []
    for i in range(num_hashes):
        min_hash = float("inf")
        for s in shingles:
            h = int(hashlib.md5(f"{i}:{s}".encode()).hexdigest(), 16)
            if h < min_hash:
                min_hash = h
        sig.append(min_hash)
    return sig


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

    while queue and len(seen_sitemaps) < max_sitemaps:
        sitemap_url = normalize_url(queue.pop(0), site_url)
        if sitemap_url in seen_sitemaps:
            continue
        seen_sitemaps.add(sitemap_url)
        fetched = fetch(sitemap_url, timeout=timeout, max_bytes=8_000_000)
        if fetched.get("status") != 200 or not fetched.get("text"):
            errors.append({"url": sitemap_url, "status": fetched.get("status"),
                           "error": fetched.get("error"),
                           "error_kind": fetched.get("error_kind")})
            continue
        parsed = parse_sitemap_xml(fetched["text"], sitemap_url)
        if parsed.get("error"):
            errors.append({"url": sitemap_url, "error": parsed["error"]})
            continue
        queue.extend(item["loc"] for item in parsed.get("sitemaps", []))
        urls.extend(item["loc"] for item in parsed.get("urls", []))

    # A sitemap listing another host's URLs is a real defect and it is
    # `sitemap_checker.py`'s to report. Here they are only kept out of the way: a
    # crawl that followed them would leave the site it was asked about, and leaving
    # them in `urls` would make each one look like an orphan — an off-host URL is
    # unreachable by internal link by definition, so GO-137 would fail every site
    # whose sitemap has one, for the wrong reason.
    deduped, off_host, seen = [], [], set()
    fetch_targets: dict[str, str] = {}
    for url in urls:
        discovered = normalize_url(url, site_url)
        key = page_key(discovered)
        if key in seen:
            continue
        seen.add(key)
        if same_host(site_url, key):
            deduped.append(key)
            fetch_targets[key] = discovered
        else:
            off_host.append(key)
    result = {"sitemaps_checked": sorted(seen_sitemaps), "urls": deduped,
              "off_host": off_host, "errors": errors}
    if include_fetch_targets:
        # Crawl-only transport detail, removed before the inventory is written.
        # The first sitemap spelling wins when `/about` and `/about/` share a
        # page key: one fetch is enough, and first-seen keeps the crawl stable.
        result["_fetch_targets"] = fetch_targets
    return result


# ---------------------------------------------------------------------------
# The crawl
# ---------------------------------------------------------------------------

class _Ordered:
    """Submit in parallel, read in submission order.

    `as_completed` would make the page set depend on which request finished first
    once `max_pages` bites, and an inventory that differs between two runs of the
    same site is one nobody can diff.
    """

    def __init__(self, workers: int):
        self._pool = ThreadPoolExecutor(max_workers=max(1, workers))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._pool.shutdown(wait=True)
        return False

    def map(self, fn, items):
        for future in [self._pool.submit(fn, item) for item in items]:
            yield future.result()


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
        "robots_blocked": bool(fetched.get("robots_blocked")),
        "title": None,
        "meta_description": None,
        "meta_robots": None,
        "canonical": None,
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
    if fetched.get("status") != 200 or not text:
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
    row["canonical"] = parsed.get("canonical")
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
            "anchor": (link.get("text") or "").strip(),
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

        with _Ordered(workers) as pool:
            for (key, discovered_url, page_depth, source), fetched in pool.map(
                    fetch_one, batch):
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

    return _finish(site_url, entry, pages, robots_blocked, sitemap, sitemap_set,
                   counter["requests"], depth, max_pages, bool(queue), signatures)


def _finish(site_url: str, entry: str, pages: dict, robots_blocked: dict,
            sitemap: dict, sitemap_set: set, requests: int, depth: int,
            max_pages: int, more_queued: bool, signatures: bool) -> dict:
    inbound: dict[str, list] = defaultdict(list)
    external_targets: dict[str, list] = defaultdict(list)
    for key, row in pages.items():
        for link in row["links"]:
            (inbound if link["internal"] else external_targets)[link["target"]].append(
                {"source": key, "anchor": link["anchor"],
                 "nofollow": link["nofollow"]})
            link.pop("_fetch_url", None)

    internal_targets = set(inbound)
    unchecked = sorted(internal_targets - set(pages) - set(robots_blocked))
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
                   "linked_from": sorted({s["source"] for s in inbound.get(key, [])})}
                  for key in sorted(pages) if pages[key]["redirected"]]

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
        "summary": {
            "requests": requests,
            "pages_fetched": len(pages),
            "pages_html": len(html_pages),
            "pages_broken": len(broken),
            "pages_redirected": len(redirected),
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
            "truncated": (more_queued or len(pages) >= max_pages
                          or bool(unchecked)),
        },
        "pages": pages,
        "reachable": sorted(reachable),
        "unchecked_internal_targets": unchecked,
        "robots_blocked": {key: why for key, why in sorted(robots_blocked.items())},
        "sitemap": sitemap,
        "broken": broken,
        "redirected": redirected,
        "external_targets": {url: sources for url, sources
                             in sorted(external_targets.items())},
    }


# ---------------------------------------------------------------------------
# Reading one back
# ---------------------------------------------------------------------------

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
    crawl of some other host decides thirteen items — eight of them `high` — from
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
# That bug shipped once, in `orphan_pages_from_sitemap.py` before 0.4.0, and it was
# written again in `server_log_audit.py`, which looked for `sitemap.robots_blocked`
# for something that lives at the top level. A shared accessor can only be
# misspelled in every caller at once, which is a failure somebody notices.
def sitemap_urls(inventory: dict) -> list[str]:
    """Every URL the site's sitemaps listed, as page keys."""
    return list((inventory.get("sitemap") or {}).get("urls") or ())


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
        lines.append(f"Truncated at --max-pages {inventory['max_pages']}: every "
                     f"count above understates the site")
    for row in inventory["broken"][:25]:
        lines.append(f"  broken: {row['url']} "
                     f"[{row['status'] or row['error']}] "
                     f"linked from {len(row['linked_from'])} page(s)")
    print_json_or_text(result, args.json, lines)


if __name__ == "__main__":
    main()
