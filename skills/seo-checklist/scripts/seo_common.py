#!/usr/bin/env python3
"""The public shared API for the standalone SEO CLI scripts.

If a script needs one of these helpers, it imports it. A second copy is a defect,
not a convenience; ``test_no_script_carries_its_own_copy_of_a_shared_helper``
enforces that rule for the helpers that have already escaped into copies.

HTTP and source resolution are ``require_requests``, ``fetch_url``,
``fetch_error_kind``, ``fetch_html``, the ``safe_get`` re-export, ``read_urls``,
``load_html``, ``load_source`` and ``is_url``. URL handling is ``normalize_url``,
``origin`` and ``same_host``. HTML and image handling is the ``BeautifulSoup``
dependency handle, ``require_bs4``, ``html_parser``, ``parse_html``,
``primary_language``, ``favicon_href``, ``has_byline_class``,
``page_author_names``, ``page_nodes``, ``under_foreign_credit``,
``foreign_itemref_ids``,
``is_responsive_fill_image``, ``srcset_urls``, ``picture_sources`` and
``likely_lcp_candidate``. Robots and
sitemaps use ``fetch_robots``, ``parse_robots_txt``, ``robots_allowed``,
``discover_sitemap_urls`` and ``parse_sitemap_xml``. JSON-LD uses ``walk_json`` and
``as_list``. Output handling is ``issue`` and ``print_json_or_text``. The shared
policy constants are ``USER_AGENT``,
``HTML_CTYPES``, ``XML_CTYPES``, ``FETCH_ERROR_KINDS``,
``DEAD_FETCH_ERROR_KINDS``, ``BYLINE_CLASS_TOKENS``, ``THIN_CONTENT_WORDS``,
``LCP_MIN_AREA`` and ``CONVENTIONAL_SITEMAP_PATHS``.

Scripts launched directly use ``from seo_common import x``. A script that must also
work when imported as ``scripts.foo`` uses the dual-path ``try/except ImportError``
form and falls back to ``from scripts.seo_common import x``; the package import has
a different module root, so both spellings are necessary there.
"""

from __future__ import annotations

import gzip
import json
import os
import re
import socket
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse, urlunparse

try:
    import requests
except ImportError:  # pragma: no cover - exercised by users without deps
    requests = None

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover - exercised by users without deps
    BeautifulSoup = None

try:
    from lib.safe_http import (AGENTIC_SEO_USER_AGENT, HostResolutionError,
                               RobotsDisallowed, SafeHTTPError, safe_get,
                               safe_request)
    from lib import robots_rules
except ImportError:
    from scripts.lib.safe_http import (AGENTIC_SEO_USER_AGENT,
                                       HostResolutionError, RobotsDisallowed,
                                       SafeHTTPError, safe_get, safe_request)
    from scripts.lib import robots_rules

try:
    from urllib3.exceptions import NameResolutionError as _NameResolutionError
except ImportError:  # pragma: no cover - requests normally supplies urllib3
    _NameResolutionError = None


USER_AGENT = AGENTIC_SEO_USER_AGENT
HTML_CTYPES = ("text/html", "application/xhtml+xml")
XML_CTYPES = ("xml", "text/plain", "application/octet-stream")
FETCH_ERROR_KINDS = (
    "unresolved", "refused", "timeout", "tls", "blocked", "robots", "other",
)
DEAD_FETCH_ERROR_KINDS = ("unresolved", "refused", "tls")


def _has_name_resolution_cause(exc: BaseException) -> bool:
    """Whether a typed exception chain contains a resolver failure.

    Requests wraps urllib3's ``NameResolutionError`` in ``MaxRetryError`` and then
    ``ConnectionError``. Those links live partly in exception arguments and partly
    in urllib3's ``reason`` attribute, so follow both without inspecting prose.
    """
    pending = [exc]
    seen = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, socket.gaierror):
            return True
        if (_NameResolutionError is not None
                and isinstance(current, _NameResolutionError)):
            return True
        linked = (current.__cause__, current.__context__,
                  getattr(current, "reason", None), *current.args)
        pending.extend(item for item in linked if isinstance(item, BaseException))
    return False


def fetch_error_kind(exc: BaseException) -> str:
    """Classify a failed shared fetch from exception types and attributes only."""
    if isinstance(exc, HostResolutionError) or _has_name_resolution_cause(exc):
        return "unresolved"
    if isinstance(exc, RobotsDisallowed):
        return "robots"
    if isinstance(exc, SafeHTTPError):
        return "blocked"
    if requests is not None:
        if isinstance(exc, requests.exceptions.Timeout):
            return "timeout"
        # SSLError subclasses ConnectionError, so the narrower type comes first.
        if isinstance(exc, requests.exceptions.SSLError):
            return "tls"
        if isinstance(exc, requests.exceptions.ConnectionError):
            return "refused"
    return "other"

# Class tokens that name a byline, compared against each whitespace-separated class
# token exactly and case-insensitively, with `_` read as `-`. The substring match this
# replaces treated `<div class="author-grid">` as a byline and handed back the
# wrapper's whole subtree text as a person's name. A closed vocabulary rather than a
# cap on how long that text may be: a wrapper is not told from a byline by its length.
BYLINE_CLASS_TOKENS = frozenset({
    "author", "authors", "byline", "by-line", "author-name", "authorname",
    "post-author", "entry-author", "article-author", "p-author", "author-link",
    "byline-author", "author-byline",
})


def has_byline_class(tag) -> bool:
    """Whether an element's class names it a byline rather than merely mentioning one.

    Compared against each class token exactly, case-insensitively, with `_` read as
    `-`. The substring match this replaces treated `author-grid` on a layout wrapper
    as a byline and handed back the wrapper's whole subtree text as a person's name.
    """
    return any(str(token).lower().replace("_", "-") in BYLINE_CLASS_TOKENS
               for token in (tag.get("class") or []))


def require_requests() -> None:
    if requests is None:
        print("Error: requests library required. Install with: pip install requests", file=sys.stderr)
        sys.exit(1)


def require_bs4() -> None:
    if BeautifulSoup is None:
        print("Error: beautifulsoup4 required. Install with: pip install beautifulsoup4", file=sys.stderr)
        sys.exit(1)


def normalize_url(url: str, base: str | None = None, default_scheme: str = "https") -> str:
    url = (url or "").strip()
    if base:
        url = urljoin(base, url)
    parsed = urlparse(url)
    if not parsed.scheme and not base:
        url = f"{default_scheme}://{url}"
        parsed = urlparse(url)
    if parsed.scheme in ("http", "https"):
        path = parsed.path or "/"
        parsed = parsed._replace(fragment="", path=path)
        return urlunparse(parsed)
    return url


def is_responsive_fill_image(img) -> bool:
    if img.get("data-nimg") == "fill":
        return True
    style = re.sub(r"\s+", "", (img.get("style") or "").lower())
    return "position:absolute" in style and "width:100%" in style and "height:100%" in style


# `srcset` is a comma-separated candidate list where each entry is a URL plus an
# optional descriptor: "logo.avif 1x, logo@2x.avif 2x". Only the URL carries the
# format, so the descriptor has to be dropped before an extension means anything.
def srcset_urls(srcset: str, base_url: str = "") -> list[str]:
    out = []
    for candidate in (srcset or "").split(","):
        url = candidate.strip().split()[0] if candidate.strip() else ""
        if url:
            out.append(normalize_url(url, base_url) if base_url else url)
    return out


def picture_sources(img, base_url: str = "") -> list[dict]:
    """The `<source>` alternatives a `<picture>` offers for this `<img>`.

    Empty for an `img` that stands alone, which is most of them. It has to be a
    `<picture>` specifically: `<source>` also appears inside `<video>` and
    `<audio>`, where it means something else entirely, and the `img` is the only
    thing tying a set of sources to a still image.

    **Any ancestor, not the parent.** libxml2 — which is what `lxml` is, and lxml
    is the parser this module prefers — predates `<picture>` and does not know
    `<source>` is void, so it nests the `<img>` *inside* the first `<source>`
    instead of beside it. Under `html.parser` the same markup gives the `img` the
    `<picture>` as its parent. Walking up finds the same element either way, which
    is the only reason this function does not silently return nothing in production
    while passing its tests. See KNOWN-ISSUES.md — the divergence is wider than
    this function and nothing else structural relies on it yet.
    """
    picture = img.find_parent("picture") if hasattr(img, "find_parent") else None
    if picture is None:
        return []
    out = []
    # Recursive on purpose: under lxml the second `<source>` is a child of the
    # first rather than its sibling, so a non-recursive scan would find one.
    for source in picture.find_all("source"):
        srcset = source.get("srcset") or ""
        out.append({
            "type": (source.get("type") or "").strip().lower() or None,
            "media": source.get("media"),
            "srcset": srcset or None,
            "sizes": source.get("sizes"),
            "urls": srcset_urls(srcset, base_url),
        })
    return out


# basis: inherited — 300 words, present at import from Agentic-SEO-Skill. It lives
# here because two scripts compared against it independently: `duplicate_content.py`
# through THIN_CONTENT_THRESHOLDS and `article_seo.py` through a bare literal, so one
# number had two homes and could be revised in one of them. Its provenance is exactly
# what KNOWN-ISSUES §2 suspected — conventional in SEO writing, with no source anybody
# here can point at.
THIN_CONTENT_WORDS = 300

# Below this many declared pixels an image is not what the Largest Contentful Paint
# measures — it is an icon. A threshold, not a law: 100×100 is the smallest thing that
# could plausibly be the largest paint on a page with any content at all, and Chrome's
# own LCP heuristics discard low-entropy images for the same reason. Written down here
# because it is one of the numbers KNOWN-ISSUES §2 is about.
# basis: convention — 100x100 declared pixels. Chrome's own LCP algorithm discards
#  low-entropy images for the same reason, but the number is ours: decided in 0.9.0
#  after CN-054 and MD-185 called a correctly lazy-loaded 64px logo a deferred LCP image
#  on every site that had one
LCP_MIN_AREA = 100 * 100


def _declared_area(img: dict) -> int | None:
    """Pixels the markup claims, or None when it does not say."""
    try:
        width, height = int(str(img.get("width"))), int(str(img.get("height")))
    except (TypeError, ValueError):
        return None
    return width * height if width > 0 and height > 0 else None


def likely_lcp_candidate(img: dict, index: int) -> bool:
    """Whether this image could be the Largest Contentful Paint.

    One definition, because there were two: `image_inventory.py` and
    `image_weight_audit.py` each held `index == 0 or fetchpriority == "high" or
    loading == "eager"`, and two copies of a heuristic drift.

    Document order is the signal available without a browser, and it is a weak one —
    the first `<img>` in the source is often a logo. So an image that *declares* a
    size too small to be the largest paint is excluded: the good fixture is a page
    whose only image is a 64px loaf mark inside a `<figure>` halfway down, correctly
    lazy-loaded, and two items reported it as a lazy-loaded LCP image. A real
    measurement is `cwv_metrics.py`'s job and it names the element; this is the
    fallback for a run with no browser trace.
    """
    area = _declared_area(img)
    if area is not None and area < LCP_MIN_AREA:
        return False
    return (index == 0
            or img.get("fetchpriority") == "high"
            or img.get("loading") == "eager")


def origin(url: str) -> str:
    parsed = urlparse(normalize_url(url))
    return f"{parsed.scheme}://{parsed.netloc}"


def same_host(a: str, b: str, include_www_variant: bool = True) -> bool:
    host_a = urlparse(normalize_url(a)).netloc.lower()
    host_b = urlparse(normalize_url(b)).netloc.lower()
    if include_www_variant:
        host_a = host_a[4:] if host_a.startswith("www.") else host_a
        host_b = host_b[4:] if host_b.startswith("www.") else host_b
    return host_a == host_b


def fetch_url(
    url: str,
    method: str = "GET",
    timeout: int = 15,
    allow_redirects: bool = True,
    max_bytes: int = 2_000_000,
    extra_headers: dict | None = None,
    respect_robots: bool = False,
) -> dict:
    """Fetch a URL through the shared safe, paced HTTP path.

    Pass `respect_robots=True` for a URL found by crawling, never for the one the
    operator asked about — see `lib.safe_http.safe_request` for why the asymmetry
    matters. A refusal arrives as `result["error"]` naming robots.txt, with
    `result["error_kind"] == "robots"` and `result["robots_blocked"]` True. A
    caller that counts errors as site defects **must** separate those out: a page we
    politely declined to fetch is not a page the site got wrong.
    """
    require_requests()
    url = normalize_url(url)
    parsed = urlparse(url)
    result = {
        "input_url": url,
        "url": url,
        "status": None,
        "headers": {},
        "text": "",
        "bytes": 0,
        "redirect_chain": [],
        "error": None,
        "error_kind": None,
        "robots_blocked": False,
    }
    if parsed.scheme not in ("http", "https"):
        result["error"] = f"Unsupported URL scheme: {parsed.scheme}"
        result["error_kind"] = "blocked"
        return result

    # No Accept of its own any more. It used to send one differing from
    # `default_headers()` by a single media type, and two spellings of one header
    # made every audited page two requests instead of one — invisible until the
    # response cache made it countable. DEFAULT_HEADERS now carries the union, so
    # nothing here advertises less than it did.
    headers = dict(extra_headers) if extra_headers else {}

    try:
        response = safe_request(
            method,
            url,
            headers=headers,
            timeout=timeout,
            allow_redirects=allow_redirects,
            max_response_bytes=max_bytes,
            respect_robots=respect_robots,
        )
        result["url"] = response.url
        result["status"] = response.status_code
        result["headers"] = {str(k).lower(): v for k, v in response.headers.items()}
        result["redirect_chain"] = [r.url for r in response.history]

        if method.upper() != "HEAD":
            result["bytes"] = len(response.content)
            result["text"] = response.text
    except RobotsDisallowed as exc:
        # Flagged, not merely errored. Callers that turn "not fetched" into a site
        # defect have to be able to tell our restraint from the site's problem.
        result["error"] = str(exc)
        result["error_kind"] = fetch_error_kind(exc)
        result["robots_blocked"] = True
    except requests.exceptions.RequestException as exc:
        result["error"] = str(exc)
        result["error_kind"] = fetch_error_kind(exc)
    return result


# basis: standard — RFC 9110 §15.5.6 and §15.6.2: 405 and 501 refuse the method, not
#  the resource; 403 is how a firewall refuses HEAD from an unfamiliar client. A link
#  answering one of these to HEAD has not said it is dead, so GET decides.
HEAD_REFUSED_STATUSES = (403, 405, 501)


def check_link_status(url: str, timeout: int = 15) -> dict:
    """One link's status, HEAD first and GET when HEAD cannot be trusted.

    Two readers — BL-083's backlink targets and TE-168's outbound links — call a
    link broken at status >= 400, so a HEAD refusal must not reach them as the
    link's answer. The copy both inherited from `external_link_quality.py` fell
    back to GET only when a refusal *also* carried an error, and `fetch_url` sets
    no error on a response it received: a page that serves GET and refuses HEAD
    with 405 was a broken link. A request that answered nothing is retried as GET
    too, as before; a dead host answers the same either way.
    """
    head = fetch_url(url, method="HEAD", timeout=timeout, allow_redirects=True,
                     max_bytes=0)
    status = head.get("status")
    if status in HEAD_REFUSED_STATUSES or (status is None and head.get("error")):
        return fetch_url(url, method="GET", timeout=timeout, allow_redirects=True,
                         max_bytes=200_000)
    return head


def read_urls(values: list[str] | None = None, file_path: str | None = None) -> list[str]:
    urls: list[str] = []
    for value in values or []:
        if value:
            urls.append(value.strip())
    if file_path:
        with open(file_path, "r", encoding="utf-8") as fh:
            urls.extend(line.strip() for line in fh if line.strip() and not line.lstrip().startswith("#"))
    seen = set()
    normalized = []
    for url in urls:
        nurl = normalize_url(url)
        if nurl not in seen:
            seen.add(nurl)
            normalized.append(nurl)
    return normalized


def load_html(source: str, timeout: int = 15) -> tuple[str, str, dict]:
    if is_url(source):
        fetched = fetch_url(source, timeout=timeout)
        return fetched.get("text") or "", fetched.get("url") or normalize_url(source), fetched
    with open(source, "r", encoding="utf-8") as fh:
        html = fh.read()
    return html, "", {"url": source, "status": None, "headers": {}, "error": None}


def is_url(value: str) -> bool:
    """Whether `value` names something to fetch rather than something to open.

    A file on disk wins over any spelling: `--source example.com/page.html` is a URL,
    but if that path exists it is the file that was meant. The bare-domain clause is
    what lets `--source example.com` work without a scheme, and the `"/" not in value`
    guard is what stops `blog/post.html` being mistaken for one.

    Two scripts carried this identically. It decides whether a run reaches the network
    at all, which is not a decision that should have had two homes.
    """
    if Path(value).is_file():
        return False
    return urlparse(value).scheme in ("http", "https") or ("." in value and "/" not in value)


def load_source(source: str, timeout: int = 15) -> tuple[str, str, dict]:
    """`load_html`, but a path that exists on disk wins over anything else.

    `load_html` decides by shape: something matching `https?://`, or a dotted token
    with no slash, is treated as a URL. That is right for a bare `example.com` and
    wrong for `./example.com.html` or an archive directory whose name carries a dot —
    both are files, and both would be fetched.

    Eleven scripts carried this same five-line wrapper, byte for byte, because each
    one accepts `--source` as either a URL or a saved page. Written once here so a
    change to how a source is resolved is one change rather than eleven, and so the
    next script that needs it has somewhere to find it.
    """
    path = Path(source)
    if path.is_file():
        return (path.read_text(encoding="utf-8"), "",
                {"url": source, "status": None, "headers": {}, "error": None})
    return load_html(source, timeout=timeout)


def fetch_html(url: str, timeout: int = 15, quiet: bool = False) -> tuple[str, str]:
    """Fetch a page and say where it ended up. `("", url)` on any failure.

    Three scripts carried this, and the three had drifted into three contracts: two
    returned the body alone and threw the final URL away, one returned both; two
    printed the exception to stderr, one swallowed it. The tuple is the honest
    shape — `hreflang_checker` needs the post-redirect URL to judge whether an
    alternate points back, and a caller that does not need it drops it. `quiet`
    keeps the silent caller silent, because a helper that starts writing to stderr
    inside a per-alternate loop turns one page's audit into forty lines of noise.

    The guard travels with `safe_get`, as it does everywhere else — see
    `lib.safe_http`. Nothing here reaches the network by another route.
    """
    try:
        resp = safe_get(url, timeout=timeout)
        return resp.text, resp.url
    except Exception as exc:  # noqa: BLE001 — an unreachable page is data, not a crash
        if not quiet:
            print(f"Error fetching {url}: {exc}", file=sys.stderr)
        return "", url


def html_parser() -> str:
    """Which parser reads every page in this run. One decision, in one place.

    It used to be `"lxml" if "lxml" in sys.modules else "html.parser"` — which does
    not ask whether lxml is *installed*, only whether something imported it first.
    Two runs on one machine could therefore parse the same page two different ways
    depending on which script pulled lxml in, and at the time the parsers were not
    equivalent: on markup with an unclosed `<p>` — the commonest invalidity there is —
    `answer_block_scanner.py` scored 10 under lxml and 32 under `html.parser`, and
    GO-144 read that score. 0.15.0 removed the divergence at its source by rewriting
    the scanner's structural queries against document order, and both parsers return
    42 on that markup now. The decision below stands on its own anyway: a tool whose
    whole claim is that two runs of one site agree cannot choose its substrate by
    accident of import order, whether or not the substrates currently differ.

    **lxml, when it can be imported.** It is a declared requirement, so it is what
    runs in practice; it tolerates the broken markup real sites serve; and measured
    over the corpus in `tests/test_parser.py`, every field the registry reads comes
    out identical between the two across fifteen document shapes — deep nesting,
    unclosed tags, an SVG `<title>`, templates, fragments. The structural queries
    agree too since 0.15.0, and a test asserts that agreement rather than pinning the
    numbers it used to differ by.

    `SEO_HTML_PARSER` overrides it, and the run records which parser produced its
    verdicts. That pair is what makes a fixture-measured decision safe: an operator
    who suspects the parser on a real site can re-run with the other one and diff
    rather than taking this docstring's word for it.
    """
    choice = (os.environ.get("SEO_HTML_PARSER") or "").strip().lower()
    if choice in ("lxml", "html.parser", "html5lib"):
        return choice
    try:
        import lxml  # noqa: F401 — presence, not use: bs4 names its parser by string
        return "lxml"
    except ImportError:
        # Not a silent downgrade: the substrate under every verdict has changed, and
        # the runner reports which parser ran. The structural checks are the ones
        # that differ — the divergence table in tests/test_parser.py says how.
        return "html.parser"


def _rel_contains(value: Any, token: str) -> bool:
    """Whether a parsed ``rel`` attribute contains one exact token."""
    if not value:
        return False
    if isinstance(value, str):
        values = value.lower().split()
    else:
        values = [str(item).lower() for item in value]
    return token in values


def favicon_href(soup, base_url: str | None = None) -> str | None:
    """Resolve the first icon declaration recognised by every favicon check."""
    for icon in soup.find_all("link"):
        href = icon.get("href")
        rel = icon.get("rel")
        if href and (
            _rel_contains(rel, "icon")
            or _rel_contains(rel, "shortcut")
            or _rel_contains(rel, "apple-touch-icon")
        ):
            return urljoin(base_url, href) if base_url else href
    return None


def walk_json(value):
    """Every dict in a JSON tree, in document order, parents before children.

    Three schema readers each carried this recursion verbatim. Public here — the
    leading underscore in the three copies meant "private to this script", and the
    thing it names is now the shared way this repository walks JSON-LD.
    """
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_json(child)


# Keys whose subtree is somebody else's contribution *to* this page.
CONTRIBUTION_KEYS = frozenset({
    "review", "reviews", "comment", "comments",
    "acceptedAnswer", "suggestedAnswer", "userComments",
})
# Keys whose subtree is what the page is *about*. Its credits belong to the subject
# rather than to the page — but unlike a contribution, a subject is routinely the
# page's own main entity, hoisted into `@graph` and pointed at by `@id`.
SUBJECT_KEYS = frozenset({"itemReviewed", "citation", "isBasedOn"})
FOREIGN_CREDIT_KEYS = CONTRIBUTION_KEYS | SUBJECT_KEYS


def _referenced_ids(value, keys, inside=False, found=None):
    """Every `@id` mentioned anywhere under one of `keys`."""
    if found is None:
        found = set()
    if isinstance(value, dict):
        if inside and isinstance(value.get("@id"), str):
            found.add(value["@id"])
        for key, child in value.items():
            _referenced_ids(child, keys, inside or key in keys, found)
    elif isinstance(value, list):
        for child in value:
            _referenced_ids(child, keys, inside, found)
    return found


def page_nodes(value, exclude=FOREIGN_CREDIT_KEYS, hoisted=FOREIGN_CREDIT_KEYS,
               protected=frozenset()):
    """Every dict in a JSON-LD tree except the ones whose credits are not the page's.

    `walk_json` yields the whole graph. That is right for asking what a document
    declares and wrong for asking who wrote it. Measured 2026-08-17:
    `Product -> review -> author` named a shopper as the author of a product page and
    CN-057 — *Show Author and Publisher Clearly* — passed on it; a review of Moby Dick
    reported Herman Melville among its authors.

    Two rules, because two things go wrong:

    * descent stops at any `exclude` key. Exclusion is by the key descended
      through, never by the node's `@type`: a page whose own top-level node is a
      `Review` — an editorial product review — still credits its author, because
      nothing descended into it through `review`;
    * a node is skipped when its `@id` is referenced from under a `hoisted`
      key anywhere in the document. Flattening a page into `@graph` hoists the customer
      review to the top level and leaves `"review": {"@id": "#r1"}` behind, which
      pruning by key alone never reaches.

    Before 0.78.0, the `hoisted` default deliberately excluded `SUBJECT_KEYS` because
    pruning a review page's own product node lost its brand as publisher evidence. That
    decision was reversed because a review site reviewing somebody else's product emits
    identical markup and wrongly credited the manufacturer as its own publisher — a false
    pass, while the loss of the page's own brand is a false fail. The check cannot decide
    and now turns into NO_DATA (never a false PASS). The default is now the wide set plus
    one exemption the page itself declares via `mainEntityOfPage`.

    What this deliberately costs, both measured: a specialist publication's own review
    nested as `Product -> review -> author` loses that author, and an `FAQPage` whose
    accepted answer carries a staff editor loses that editor. Neither is distinguishable
    in structure from the customer-contributed case — schema.org gives both the same key
    — and a page's own author belongs on the page's own node. Hoisting the editorial
    review to the top level, which is what a review site usually emits, keeps the credit.

    All three readers of author, date and entity signals now take the page's own nodes,
    with each caller naming the boundary its fields require. `site_crawl.py` keeps
    `walk_json` because it asks which `@type`s a document declares — a question about
    the document, not about responsibility. That is the distinction to keep in mind
    before adding a fourth caller.

    Known and not handled: a namespaced key such as `"schema:review"` bypasses both
    sets. `walk_json` has always had that hole, JSON-LD needs a context mapping to
    produce it, and closing it needs context expansion this repository does not do.
    """
    excluded_ids = _referenced_ids(value, hoisted) - set(protected)

    def walk(node):
        if isinstance(node, dict):
            if node.get("@id") in excluded_ids:
                return
            yield node
            for key, child in node.items():
                if key not in exclude:
                    yield from walk(child)
        elif isinstance(node, list):
            for child in node:
                yield from walk(child)

    yield from walk(value)


def _nested_under_foreign_credit(tag, keys) -> bool:
    """The DOM half: an ancestor carries a foreign-credit `itemprop`."""
    for ancestor in (tag, *tag.parents):
        itemprop = ancestor.get("itemprop")
        values = [itemprop] if isinstance(itemprop, str) else itemprop or []
        if any(token in keys for value in values for token in value.split()):
            return True
    return False


def _own_and_ancestor_ids(tag) -> set[str]:
    """Every `id` on `tag` or above it — the ids an `itemref` could name to claim it."""
    found = set()
    for element in (tag, *tag.parents):
        value = element.get("id")
        if isinstance(value, str) and value:
            found.add(value)
    return found


def _root_of(tag):
    root = tag
    for parent in tag.parents:
        root = parent
    return root


def foreign_itemref_ids(root, keys=FOREIGN_CREDIT_KEYS) -> frozenset:
    """Every `id` an element under foreign credit claims through `itemref`.

    Microdata does not stop at the DOM. `itemref` on an item names elements elsewhere
    in the document that are also that item's properties, so a comment can own a
    byline nowhere near it in the tree — and the ancestor walk alone then reads that
    byline as the page's own. Measured: a page whose only byline is a commenter's,
    claimed by `itemref`, passes `CN-057` *Show Author and Publisher Clearly*, which
    is `high`, exactly as an honestly authored page does.

    To a fixed point, because an item inside a claimed region can claim further
    elements of its own, and that chain is as foreign as its first link.

    **`itemscope` is deliberately not required**, although the specification permits
    `itemref` only on an element that has it. This is a removal rule, so the two ways
    of being wrong do not cost the same: honouring an invalid `itemref` can drop a
    credit the page deserved — a false fail — while ignoring one hands the page a
    credit that belongs to a commenter. Only the second is a false pass, and a false
    pass on a `high` item is what this boundary exists to prevent.
    """
    owners = root.find_all(attrs={"itemref": True})
    if not owners:
        return frozenset()
    claimed: set[str] = set()
    while True:
        added = False
        for owner in owners:
            tokens = str(owner.get("itemref") or "").split()
            if not tokens or set(tokens) <= claimed:
                continue
            if (_nested_under_foreign_credit(owner, keys)
                    or _own_and_ancestor_ids(owner) & claimed):
                claimed.update(tokens)
                added = True
        if not added:
            return frozenset(claimed)


def under_foreign_credit(tag, keys=FOREIGN_CREDIT_KEYS, claimed=None) -> bool:
    """Whether `tag` sits under a property carrying somebody else's credit.

    Exclusion is by the property descended through, never by the container's
    `itemtype`: an editorial review page is itself a `Review`, and its own author is
    still the page's author. This is removal only, never preference. A declaration
    says what a thing is, not whose it is, so preferring declared credits can promote
    a nested entity's author over the page's own undeclared byline.

    Two ways to be inside somebody else's credit: nested under it, and claimed by it
    through `itemref` — see `foreign_itemref_ids`. The `itemref` question is asked
    only for a tag that could be its target, which is a tag carrying an `id` or having
    an ancestor that does.

    `claimed` is that document's answer, computed once. `parse_html` puts it in
    `foreign_itemref_ids` and every caller that loops over tags passes it, because the
    fallback here scans the whole document per call: measured at 3ms on a
    2400-element page, which is nothing once and a fifth of a second over sixty
    id-bearing bylines. Omitting it stays correct, only slower.

    Not handled, and it is a decision rather than a gap: an element that a *second*
    item claims by `itemref` while it is nested inside a comment stays removed. The
    same person is then declared for both items and nothing in the markup says which
    is meant, so this withholds rather than choosing — the same answer `page_nodes`
    gives an ambiguous graph.
    """
    if _nested_under_foreign_credit(tag, keys):
        return True
    ids = _own_and_ancestor_ids(tag)
    if not ids:
        return False
    if claimed is None:
        claimed = foreign_itemref_ids(_root_of(tag), keys)
    return bool(ids & claimed)


def schema_values(schema_items: list, keys: set[str], protected=frozenset()) -> list[str]:
    values = []
    for item in schema_items:
        for node in page_nodes(item, protected=protected):
            for key in keys:
                value = node.get(key)
                if isinstance(value, str):
                    values.append(value)
                elif isinstance(value, dict) and value.get("name"):
                    values.append(str(value["name"]))
                elif isinstance(value, list):
                    values.extend(str(v.get("name") if isinstance(v, dict) else v) for v in value)
    return [value for value in values if value and value != "None"]


def page_author_names(parsed: dict) -> list[str]:
    """Who the page says wrote it: `meta[name=author]` and `rel=author`, an exact
    byline class token with text, and JSON-LD `author` over the page's own nodes.

    One definition because two scripts needed the same answer and gave different ones.
    Until 0.69.0 `citation_readiness` asked whether the page carried *any* JSON-LD
    `name`, so a product's name and a reviewed book's title were author signals worth
    fifteen points while `meta[name=author]` was not read at all. `eeat_signal_checker`
    answered all six measured cases correctly, and this is that code.

    Not the same question as `signals.authorship.author`, which is a verdict about a
    page; this is the list that verdict is taken from.
    """
    soup = parsed["soup"]
    claimed = parsed.get("foreign_itemref_ids")
    author_meta = [
        tag.get("content") or tag.get_text(" ", strip=True)
        for tag in soup.find_all(["meta", "span", "a"], attrs={"name": "author"})
        + soup.find_all(["a", "span"], rel=lambda value: value and "author" in value)
        if not under_foreign_credit(tag, claimed=claimed)
    ]
    class_authors = [
        tag.get_text(" ", strip=True)
        for tag in soup.find_all(class_=True)
        if has_byline_class(tag)
        and tag.get_text(strip=True)
        and not under_foreign_credit(tag, claimed=claimed)
    ]
    schema_authors = schema_values(parsed.get("page_schema", []), {"author"}, parsed.get("page_own_ids", frozenset()))
    return sorted({value.strip() for value in author_meta + class_authors + schema_authors if value and value.strip()})


def declared_publication_dates_by_source(parsed) -> dict[str, list[str]]:
    """Publication dates the page declares in schema, meta and microdata.

    A bare ``<time>`` is not read because it does not declare which kind of date it
    carries; callers must not infer publication from nearby prose.

    Dates use the wider `hoisted=FOREIGN_CREDIT_KEYS` boundary. Measured on a graph
    where `citation` references a hoisted paper dated 1998-01-01, the default
    `CONTRIBUTION_KEYS` returns that date while `FOREIGN_CREDIT_KEYS` excludes it. A
    nested citation is excluded either way, so only the hoisted spelling exposes the
    difference. `page_author_names` deliberately takes the narrower default: pruning a
    hoisted subject would cost an editorial review page its publisher.
    """
    dates = {"schema": [], "meta": [], "microdata": []}
    for item in parsed.get("page_schema", []):
        for node in page_nodes(item, hoisted=FOREIGN_CREDIT_KEYS, protected=parsed.get("page_own_ids", frozenset())):
            value = node.get("datePublished")
            if isinstance(value, str):
                dates["schema"].append(value)

    soup = parsed["soup"]
    claimed = parsed.get("foreign_itemref_ids")
    for tag in soup.find_all("meta"):
        names = (tag.get("property"), tag.get("name"))
        content = tag.get("content")
        if (any(isinstance(value, str) and value.lower() == "article:published_time"
                for value in names)
                and not under_foreign_credit(tag, claimed=claimed)
                and content):
            dates["meta"].append(content)

    for tag in soup.find_all(itemprop=True):
        itemprop = tag.get("itemprop")
        values = [itemprop] if isinstance(itemprop, str) else itemprop or []
        if (any(token == "datePublished" for value in values for token in value.split())
                and not under_foreign_credit(tag, claimed=claimed)):
            value = tag.get("datetime") or tag.get("content") or tag.get_text(" ", strip=True)
            if value:
                dates["microdata"].append(value)
    return dates


def declared_publication_dates(parsed) -> list[str]:
    """Flatten declared dates in source-precedence order without re-reading the page."""
    return [value for values in declared_publication_dates_by_source(parsed).values() for value in values]


def as_list(value: Any) -> list[Any]:
    """A JSON-LD value as a list, whether it arrived as one, as a scalar, or not at all.

    Schema.org permits a bare value anywhere a list is allowed, so every reader of
    JSON-LD needs this and two of them had written it — with `None` folding to `[]`
    rather than `[None]`, which is the part worth having in one place.
    """
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def page_own_ids(page_schema, base_url: str = "", canonical: str | None = None) -> frozenset:
    """`@id`s the document declares to be what *this* page is about.

    `page_nodes` prunes a node whose `@id` is referenced from under a foreign-credit key,
    and since 0.78.0 that includes the subject keys. This is the one exemption: a page may
    say which node is its own subject, and the two spellings run in opposite directions.
    `mainEntityOfPage` points *from* the subject *to* the page, so the **carrier** is the
    subject; `mainEntity` points *from* the page *to* the subject, so the **value** is.

    **Anchored to this page, and that is the whole point.** A cited work routinely carries
    `mainEntityOfPage` naming its own canonical page. Reading that as a claim about the
    page in hand re-admits a foreign node and hands back its author — measured, and the
    reason the unanchored version of this rule was scored and rejected.

    Comparison goes through `normalize_url` against both `base_url` and `canonical`.
    Measured, so that the limits are not guessed at: `normalize_url` resolves a relative
    reference against the base and supplies a scheme to a bare host, and does **not**
    reconcile a trailing slash, a scheme, or host case. Both anchors are kept because a
    page whose canonical differs from its fetch URL by a slash is then matched by one of
    them. What is left over — a document naming its page with a different scheme or host
    case — gets no exemption, which is a false fail and the safe side of this release.

    Empty values are dropped before normalising, and must be: `normalize_url("")` is
    `'https:///'`, and so is `normalize_url("/", "")`. A local file has no `base_url`, so
    without the filter every page would carry a bogus anchor and any node claiming `"/"`
    would be wrongly protected.
    """
    anchors = {normalize_url(url) for url in (base_url, canonical) if url}
    if not anchors:
        return frozenset()
    # A relative claim is resolved against the fetch URL when there is one and against the
    # canonical otherwise. A local file has no fetch URL, which is how every file-based
    # test in this suite runs, and `"/p"` has to resolve to something for those to mean
    # anything.
    base = base_url or canonical or ""

    def names_this_page(value) -> bool:
        return isinstance(value, str) and normalize_url(value, base) in anchors

    own_ids = set()
    for item in page_schema or []:
        for node in walk_json(item):
            node_id = node.get("@id")
            declared = node.get("mainEntityOfPage")
            if isinstance(declared, dict):
                claims = [declared.get("@id"), declared.get("url")]
            else:
                claims = [declared]
            if any(names_this_page(claim) for claim in claims) and isinstance(node_id, str):
                own_ids.add(node_id)

            if names_this_page(node_id) or names_this_page(node.get("url")):
                subject = node.get("mainEntity")
                subject_id = subject.get("@id") if isinstance(subject, dict) else subject
                if isinstance(subject_id, str):
                    own_ids.add(subject_id)
    return frozenset(own_ids)


def parse_html(html: str, base_url: str = "") -> dict:
    require_bs4()
    soup = BeautifulSoup(html or "", html_parser())
    # Once, and here rather than on demand: `under_foreign_credit` otherwise scans the
    # whole document for every tag that carries an `id`. Taken before the `script`,
    # `style` and `template` removal below, so an `itemref` inside a `<template>` is
    # still read — which errs towards removing a credit rather than granting one, the
    # direction this boundary is allowed to be wrong in.
    foreign_itemref = foreign_itemref_ids(soup)

    def text_or_none(tag):
        return tag.get_text(" ", strip=True) if tag else None

    title = text_or_none(soup.find("title"))
    meta = {}
    for tag in soup.find_all("meta"):
        key = (tag.get("name") or tag.get("property") or tag.get("http-equiv") or "").strip().lower()
        if key:
            meta[key] = tag.get("content", "")

    canonical_tag = soup.find("link", rel=lambda value: value and "canonical" in value)
    canonical = canonical_tag.get("href") if canonical_tag else None
    if canonical and base_url:
        canonical = normalize_url(canonical, base_url)

    links = []
    for tag in soup.find_all("a", href=True):
        href = tag.get("href", "").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:", "data:")):
            continue
        abs_url = normalize_url(href, base_url) if base_url else href
        links.append({
            "href": abs_url,
            "text": tag.get_text(" ", strip=True)[:160],
            "rel": tag.get("rel") or [],
            "foreign_credit": under_foreign_credit(tag, claimed=foreign_itemref),
        })

    images = []
    for img in soup.find_all("img"):
        native_src = img.get("src") or ""
        deferred_src = img.get("data-src") or ""
        src = native_src or deferred_src
        if src and base_url:
            src = normalize_url(src, base_url)
        sources = picture_sources(img, base_url)
        is_responsive_fill = is_responsive_fill_image(img)
        images.append({
            "src": src,
            "alt": img.get("alt"),
            "width": img.get("width"),
            "height": img.get("height"),
            "is_responsive_fill": is_responsive_fill,
            "loading": img.get("loading"),
            "srcset": img.get("srcset"),
            "sizes": img.get("sizes"),
            "fetchpriority": img.get("fetchpriority"),
            "decoding": img.get("decoding"),
            # Native `src`/`srcset` and picture sources are discoverable without
            # running page JavaScript. A `data-src`/`data-srcset`-only image is a
            # deferred instruction to JS, not an image source a crawler can follow.
            "native_source": bool(native_src or img.get("srcset")
                                  or any(source.get("srcset") for source in sources)),
            "deferred_source": bool(deferred_src or img.get("data-srcset")),
            # What the browser may pick *instead* of `src`. Reading only the `img`
            # made a site doing this right look like a site doing nothing: the
            # recommended way to serve webp is a `<picture>` whose `<source>`
            # offers the modern format and whose `<img>` keeps a png fallback for
            # old browsers — so the fallback was the only thing the audit ever
            # saw, and MB-096/MB-097 failed the pattern they exist to encourage.
            "picture_sources": sources,
        })

    schema = []
    page_schema = []
    for script in soup.find_all("script", type=lambda v: v and "ld+json" in v):
        raw = script.string or script.get_text() or ""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = {"error": "invalid_json", "snippet": raw[:160]}
        schema.append(data)
        if not under_foreign_credit(script, claimed=foreign_itemref):
            # Share the same object with schema; neither list is mutated by readers.
            page_schema.append(data)

    for element in soup(["script", "style", "noscript", "template"]):
        element.decompose()
    body_text = soup.get_text(" ", strip=True)
    words = re.findall(r"\b[\w'-]+\b", body_text)

    return {
        "title": title,
        "meta_description": meta.get("description"),
        "meta_robots": meta.get("robots"),
        "viewport": meta.get("viewport"),
        "canonical": canonical,
        "lang": (soup.html.get("lang") if soup.html else None),
        "headings": {f"h{i}": [h.get_text(" ", strip=True) for h in soup.find_all(f"h{i}") if h.get_text(strip=True)] for i in range(1, 7)},
        "links": links,
        "images": images,
        "schema": schema,
        "page_schema": page_schema,
        "page_own_ids": page_own_ids(page_schema, base_url, canonical),
        "foreign_itemref_ids": foreign_itemref,
        "word_count": len(words),
        "body_text": body_text,
        "forms": len(soup.find_all("form")),
        "landmarks": {
            "main": len(soup.find_all("main")),
            "nav": len(soup.find_all("nav")),
            "header": len(soup.find_all("header")),
            "footer": len(soup.find_all("footer")),
        },
        "labels": len(soup.find_all("label")),
        "inputs": len(soup.find_all(["input", "select", "textarea"])),
        "buttons": len(soup.find_all(["button"])) + len(soup.find_all("a", role="button")),
        "soup": soup,
    }


def primary_language(parsed: dict, soup=None) -> str | None:
    """Return the primary declared language subtag, without guessing.

    Read ``<html lang>`` from ``parsed["lang"]`` first, then a
    ``content-language`` meta declaration, then ``og:locale``. The two meta
    fallbacks exist for pages that omit ``<html lang>``; callers that intentionally
    read only their existing ``lang`` field omit ``soup`` so their input scope does
    not broaden.
    """
    raw = parsed.get("lang")
    if not raw and soup is not None:
        raw = next((tag.get("content") for tag in soup.find_all("meta")
                    if str(tag.get("http-equiv") or "").strip().lower()
                    == "content-language" and tag.get("content")), None)
    if not raw and soup is not None:
        raw = next((tag.get("content") for tag in soup.find_all("meta")
                    if str(tag.get("property") or "").strip().lower() == "og:locale"
                    and tag.get("content")), None)
    if not raw:
        return None
    primary = re.split(r"[-_]", str(raw).strip(), maxsplit=1)[0].lower()
    return primary or None


def issue(severity: str, message: str, url: str | None = None, evidence: str | None = None) -> dict:
    return {"severity": severity, "message": message, "url": url, "evidence": evidence}


def parse_robots_txt(content: str) -> dict:
    parsed = robots_rules.parse(content)
    crawl_delays: dict[str, float] = {}
    for group in parsed["groups"]:
        if group["crawl_delay"] is not None:
            for agent in group["agents"]:
                crawl_delays[agent] = group["crawl_delay"]
    parsed["crawl_delays"] = crawl_delays
    return parsed


def robots_allowed(parsed_robots: dict | None, url: str, user_agent: str = "*") -> tuple[bool, str]:
    return robots_rules.allowed(parsed_robots, url, user_agent)


def fetch_robots(site_url: str, timeout: int = 15) -> dict:
    robots_url = origin(site_url) + "/robots.txt"
    fetched = fetch_url(robots_url, timeout=timeout, max_bytes=500_000)
    parsed = parse_robots_txt(fetched.get("text") or "") if fetched.get("status") == 200 else None
    return {"url": robots_url, "fetch": fetched, "parsed": parsed}


# Conventional filenames worth trying when nothing declares a sitemap. They are
# guesses, and a guess that misses says nothing about the site — see
# `discover_sitemap_urls`.
CONVENTIONAL_SITEMAP_PATHS = ("/sitemap.xml", "/sitemap_index.xml",
                              "/sitemap-index.xml")


def discover_sitemap_urls(site_url: str, timeout: int = 15,
                          with_source: bool = False):
    """Sitemap URLs to try, declared ones first.

    With `with_source=True`, yields `(url, source)` where source is `"declared"`
    (named in robots.txt, or passed in by the caller) or `"probed"` (a conventional
    filename we guessed at).

    **The distinction decides whether a 404 is a finding.** A declared sitemap that
    does not load is a real defect: the site says it is there. A probed filename
    that 404s means only that this site does not use that name — which is true of
    almost every site, since these three names are alternatives, not a set. Treating
    the miss as an error made `sitemap_checker` report two errors against every site
    that has exactly one sitemap, and those errors failed GO-136 (`none_severity`)
    and GO-138 (whose pattern matches the literal "404" in the message). A clean
    sitemap could not pass either item.
    """
    base = origin(site_url)
    robots = fetch_robots(site_url, timeout=timeout)
    declared = list((robots.get("parsed") or {}).get("sitemaps", []))
    pairs, seen = [], set()
    for candidate, source in ([(c, "declared") for c in declared]
                              + [(base + p, "probed")
                                 for p in CONVENTIONAL_SITEMAP_PATHS]):
        url = normalize_url(candidate, base)
        if url not in seen:
            seen.add(url)
            pairs.append((url, source))
    return pairs if with_source else [url for url, _ in pairs]


def parse_sitemap_xml(xml_text: str, sitemap_url: str = "") -> dict:
    text = xml_text or ""
    if text[:2] == "\x1f\x8b":
        text = gzip.decompress(text.encode("latin1")).decode("utf-8", errors="replace")
    try:
        root = ET.fromstring(text.encode("utf-8"))
    except ET.ParseError as exc:
        return {"type": "invalid", "urls": [], "sitemaps": [], "error": str(exc)}

    def local(tag: str) -> str:
        return tag.split("}", 1)[-1]

    urls = []
    children = list(root)
    if local(root.tag) == "sitemapindex":
        for sm in root:
            loc = sm.findtext("{*}loc") or sm.findtext("loc")
            if loc:
                urls.append({"loc": normalize_url(loc, sitemap_url), "lastmod": sm.findtext("{*}lastmod") or sm.findtext("lastmod")})
        return {"type": "sitemapindex", "urls": [], "sitemaps": urls, "error": None}

    if local(root.tag) == "urlset" or any(local(child.tag) == "url" for child in children):
        for node in root.findall("{*}url") or root.findall("url"):
            loc = node.findtext("{*}loc") or node.findtext("loc")
            if not loc:
                continue
            urls.append({
                "loc": normalize_url(loc, sitemap_url),
                "lastmod": node.findtext("{*}lastmod") or node.findtext("lastmod"),
                "changefreq": node.findtext("{*}changefreq") or node.findtext("changefreq"),
                "priority": node.findtext("{*}priority") or node.findtext("priority"),
            })
        return {"type": "urlset", "urls": urls, "sitemaps": [], "error": None}

    return {"type": "unknown", "urls": [], "sitemaps": [], "error": f"Unknown root element: {root.tag}"}


def print_json_or_text(result: dict, as_json: bool, text_lines: Iterable[str]) -> None:
    if as_json:
        print(json.dumps(result, indent=2, sort_keys=False))
    else:
        for line in text_lines:
            print(line)
