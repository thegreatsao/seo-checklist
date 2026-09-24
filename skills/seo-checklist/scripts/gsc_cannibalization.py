#!/usr/bin/env python3
"""
Detect keyword cannibalization and branded-query ownership from Search Console.

Two checks no crawler can make, because both need real query data:

  cannibalization — one query pulling impressions across several of your URLs.
                    Google has to pick a winner per query; when it keeps
                    switching, every candidate ranks worse than one focused
                    page would.
  branded query   — whether the homepage actually owns the site's own name.

The brand is a name, not a guess from traffic: `--brand` when the operator gives
one, otherwise every name the homepage publishes for itself — `WebSite` and
organisation names and alternate names in JSON-LD, and `og:site_name`. A branded
query is one that carries such a name. With no name to go on the branded block
says so and decides nothing.

Auth is the same service account gsc_checker.py uses.

Usage:
    python gsc_cannibalization.py sc-domain:example.com --credentials key.json --json
    python gsc_cannibalization.py https://example.com/ --credentials key.json --days 28
    python gsc_cannibalization.py sc-domain:example.com --brand "Acme Valley" --json
"""

import argparse
import json
import os
import sys
import unicodedata
from datetime import datetime, timedelta
from urllib.parse import urlparse


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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from bs4 import BeautifulSoup
    from entity_checker import ENTITY_TYPES
    from gsc_checker import build_service
    from hreflang_checker import locale_page_key, run_hreflang_check
    from lib.schema_types import schema_types
    from seo_common import fetch_html, html_parser
except ImportError:
    print("Error: gsc_checker.py must be importable from the same directory")
    sys.exit(1)

# basis: inherited — average position 1.5, present at import. Blocker: one property in one language cannot establish branded-query ownership across markets; this needs many properties across markets.
RANKS_FIRST_POSITION = 1.5
# basis: inherited — 100 impressions, present at import. Blocker: this only splits an already-fired finding into high versus medium severity, so it is a prioritisation convention rather than a search-analytics measurement.
HIGH_SEVERITY_IMPRESSIONS = 100

# basis: inherited — present at import, and the one cap here that decides a verdict.
#  One request, no `startRow`, so a property with more than this many query/page
#  rows in the window is analysed from the first 5000 and MS-023 and KW-071 — both
#  `high` — read `eq 0` off them as "no query on this site splits across URLs".
#  `truncated` below says when that happened; raising it means paginating.
ROW_LIMIT = 5000
# basis: inherited — 10 impressions, present at import. Below it two pages sharing a
#  query is noise rather than cannibalisation, but the number was not measured
MIN_IMPRESSIONS = 10       # below this, page-splitting is noise, not a pattern
# basis: inherited — present at import, and definitional rather than calibratable: one
#  page cannot compete with itself
MIN_PAGES = 2
# basis: convention — two results within three average-position places are close
# enough that the number alone cannot identify a settled winner. This reuses the
# former registry band without claiming that a wider raw spread is worse.
CONTESTED_POSITION_BAND = 3.0
# basis: convention — shorter normalized terms collide with too many ordinary words.
MIN_NEAR_BRAND_LENGTH = 5
# basis: convention — one typo is the precision cap below ten normalized characters.
SHORT_NEAR_BRAND_LENGTH = 10
# basis: convention — one edit catches a dropped or doubled letter in a short term.
SHORT_NEAR_BRAND_EDITS = 1
# basis: convention — two edits allow the same typo rate across longer brand forms.
LONG_NEAR_BRAND_EDITS = 2
# basis: convention — 1000 retains 243 queries whole without unbounded evidence.
QUERY_EVIDENCE_LIMIT = 1000


def fetch_query_page_rows(service, site_url: str, days: int):
    end = datetime.now().date()
    start = end - timedelta(days=days)
    body = {
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "dimensions": ["query", "page"],
        "rowLimit": ROW_LIMIT,
    }
    resp = service.searchanalytics().query(siteUrl=site_url, body=body).execute()
    rows = []
    for r in resp.get("rows", []):
        rows.append({
            "query": r["keys"][0],
            "page": r["keys"][1],
            "clicks": r.get("clicks", 0),
            "impressions": r.get("impressions", 0),
            "position": round(r.get("position", 0), 1),
        })
    return rows, start.isoformat(), end.isoformat()


def _group_locale_pages(hits: list, alternate_urls: list[str]) -> list:
    grouped = {}
    for hit in hits:
        key = locale_page_key(hit["page"], alternate_urls)
        grouped.setdefault(key, []).append(hit)
    pages = []
    for members in grouped.values():
        representative = max(members, key=lambda row: row["impressions"])
        impressions = sum(row["impressions"] for row in members)
        weighted = sum(row["position"] * row["impressions"] for row in members
                       if row["position"])
        positioned = sum(row["impressions"] for row in members if row["position"])
        pages.append({
            "page": representative["page"],
            "clicks": sum(row["clicks"] for row in members),
            "impressions": impressions,
            "position": round(weighted / positioned, 1) if positioned else 0,
            "alternates": sorted({row["page"] for row in members}),
        })
    return sorted(pages, key=lambda page: -page["impressions"])


def find_query_spreads(rows: list, alternate_urls: list[str] | None = None) -> list:
    by_query: dict = {}
    for r in rows:
        by_query.setdefault(r["query"], []).append(r)

    out = []
    for query, hits in by_query.items():
        eligible = [hit for hit in hits if hit["impressions"] >= MIN_IMPRESSIONS]
        if len(eligible) < MIN_PAGES:
            continue
        out.append(_query_summary(query, eligible, alternate_urls))
    out.sort(key=lambda c: (-c["impressions"], -c["spread"]))
    return out


def _query_summary(query: str, eligible: list,
                   alternate_urls: list[str] | None = None) -> dict:
    pages = _group_locale_pages(eligible, alternate_urls or [])
    positions = [p["position"] for p in pages if p["position"]]
    return {
        "query": query,
        "pages": pages[:5],
        "page_count": len(pages),
        "clicks": sum(p["clicks"] for p in pages),
        "impressions": sum(p["impressions"] for p in pages),
        # Raw distance between the best and worst logical page positions. A
        # wide value means one page outranks another; it does not by itself
        # mean Google is undecided or that keyword copy is duplicated.
        "spread": round(max(positions) - min(positions), 1) if len(positions) > 1 else 0,
        "positions_compared": len(positions),
    }


def find_cannibalization(rows: list, alternate_urls: list[str] | None = None) -> list:
    """Return query spreads that still contain at least two logical pages."""
    return [row for row in find_query_spreads(rows, alternate_urls)
            if row["page_count"] >= MIN_PAGES]


def _brand_form(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", str(value or "").casefold())
    return "".join(char for char in decomposed
                   if char.isalnum() and not unicodedata.combining(char))


def _bounded_edit_distance(left: str, right: str, limit: int) -> int | None:
    """Return the edit distance when it is no greater than ``limit``."""
    if abs(len(left) - len(right)) > limit:
        return None
    previous = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, 1):
        current = [left_index]
        for right_index, right_char in enumerate(right, 1):
            current.append(min(
                current[-1] + 1,
                previous[right_index] + 1,
                previous[right_index - 1] + (left_char != right_char),
            ))
        if min(current) > limit:
            return None
        previous = current
    distance = previous[-1]
    return distance if distance <= limit else None


def _near_brand_match(query: str, brand_query: str) -> tuple[str, int] | None:
    brand_words = [_brand_form(word) for word in str(brand_query).split()]
    brand_words = [word for word in brand_words if word]
    brand_terms = [_brand_form(brand_query)]
    if len(brand_words) >= 2:
        brand_terms.append("".join(brand_words[:2]))
    brand_terms = list(dict.fromkeys(term for term in brand_terms if term))
    query_terms = [_brand_form(query)]
    query_terms.extend(_brand_form(word) for word in str(query).split())
    query_terms = list(dict.fromkeys(term for term in query_terms if term))

    for brand_term in brand_terms:
        for query_term in query_terms:
            # Precision guard: terms below five are
            # too easily ordinary words; under ten gets one edit, longer terms two.
            # This catches common dropped/doubled letters without making a quiet
            # cannibalization count out of unrelated short queries.
            if min(len(brand_term), len(query_term)) < MIN_NEAR_BRAND_LENGTH:
                continue
            limit = (SHORT_NEAR_BRAND_EDITS
                     if len(brand_term) < SHORT_NEAR_BRAND_LENGTH
                     else LONG_NEAR_BRAND_EDITS)
            distance = _bounded_edit_distance(query_term, brand_term, limit)
            if distance is not None:
                return brand_term, distance
    return None


def _brand_match(query: str, brand_query: str) -> tuple[str, int] | None:
    """Return the normalized brand term and edit distance that claimed a query."""
    query_form, brand_form = _brand_form(query), _brand_form(brand_query)
    if not query_form or not brand_form:
        return None
    if brand_form in query_form:
        return brand_form, 0
    brand_words = [_brand_form(word) for word in str(brand_query).split()]
    brand_words = [word for word in brand_words if word]
    if len(brand_words) >= 2:
        shorter_brand = "".join(brand_words[:2])
        if shorter_brand in query_form:
            return shorter_brand, 0
    # The inferred brand often includes a location suffix. Preserve a substantial
    # shorter form such as "acme valley" / "acmevalley" as the same brand.
    if query_form in brand_form and len(query_form) >= max(5, len(brand_form) // 2):
        return query_form, 0
    return _near_brand_match(query, brand_query) or _reordered_brand_match(
        query, brand_words)


def _reordered_brand_match(query: str, brand_words: list[str]) -> tuple[str, int] | None:
    """The first two words of a brand, each present in the query in any order.

    People search a name the way they say it: "barber marino" and "marinos barber
    shop" are both the shop published as "Marino Barbero", and neither contains the
    name as a run of letters. Each word is held to the same bounds as a whole-name
    misspelling, and a word shorter than the near-match floor must appear exactly.
    """
    if len(brand_words) < 2:
        return None
    query_words = [_brand_form(word) for word in str(query).split()]
    query_words = [word for word in query_words if word]
    total = 0
    for brand_word in brand_words[:2]:
        best = None
        for query_word in query_words:
            if query_word == brand_word:
                best = 0
                break
            if min(len(brand_word), len(query_word)) < MIN_NEAR_BRAND_LENGTH:
                continue
            limit = (SHORT_NEAR_BRAND_EDITS
                     if len(brand_word) < SHORT_NEAR_BRAND_LENGTH
                     else LONG_NEAR_BRAND_EDITS)
            distance = _bounded_edit_distance(query_word, brand_word, limit)
            if distance is not None and (best is None or distance < best):
                best = distance
        if best is None:
            return None
        total += best
    return "".join(brand_words[:2]), total


def is_branded_query(query: str, brand_query: str) -> bool:
    """Match normalized brand forms and deliberately bounded misspellings."""
    return _brand_match(query, brand_query) is not None


def _any_brand_match(query: str, names: list[str]) -> tuple[str, int] | None:
    """The closest match among every name the brand goes by."""
    matches = [match for match in (_brand_match(query, name) for name in names)
               if match]
    return min(matches, key=lambda match: match[1]) if matches else None


def published_brand_names(html: str) -> list[str]:
    """Every name a homepage publishes for the site or the business behind it.

    `WebSite.name` is what Google reads for the site name; an organisation, a local
    business, a person or a `Brand` names the owner; `alternateName` is the same
    thing said another way; `og:site_name` is the social card's. All are the site's
    own statement of what it is called, which is the only honest source of "branded"
    this script has — a query's traffic says what people search, not whose name it is.
    """
    soup = BeautifulSoup(html or "", html_parser())
    names: list[str] = []

    def add(value) -> None:
        for candidate in (value if isinstance(value, list) else [value]):
            if isinstance(candidate, str) and candidate.strip():
                names.append(" ".join(candidate.split()))

    def visit(node) -> None:
        if isinstance(node, list):
            for child in node:
                visit(child)
            return
        if not isinstance(node, dict):
            return
        types = schema_types(node.get("@type"))
        if "WebSite" in types or any(kind in ENTITY_TYPES for kind in types):
            add(node.get("name"))
            add(node.get("alternateName"))
        visit(node.get("@graph"))

    for script in soup.find_all("script", type="application/ld+json"):
        try:
            visit(json.loads(script.string or ""))
        except (json.JSONDecodeError, TypeError):
            continue
    site_name = soup.find("meta", attrs={"property": "og:site_name"})
    if site_name:
        add(site_name.get("content"))
    return list(dict.fromkeys(names))


def _query_evidence(rows: list, alternate_urls: list[str] | None,
                    spread_brand: list[str]) -> tuple[list, bool]:
    by_query: dict = {}
    for row in rows:
        by_query.setdefault(row["query"], []).append(row)

    evidence = []
    for query, hits in by_query.items():
        eligible = [hit for hit in hits if hit["impressions"] >= MIN_IMPRESSIONS]
        summary = _query_summary(query, eligible, alternate_urls)
        brand_match = _any_brand_match(query, spread_brand)
        is_spread = len(eligible) >= MIN_PAGES
        if is_spread and brand_match:
            bucket = "branded_spread"
        elif summary["page_count"] >= MIN_PAGES:
            bucket = ("contested"
                      if summary["positions_compared"] >= MIN_PAGES
                      and summary["spread"] <= CONTESTED_POSITION_BAND
                      else "cannibalized")
        else:
            bucket = "single_page"
        item = {
            "query": query,
            "brand_form": _brand_form(query),
            "page_count": summary["page_count"],
            "impressions": summary["impressions"],
            "spread": summary["spread"],
            "positions_compared": summary["positions_compared"],
            "bucket": bucket,
        }
        if brand_match:
            item["matched_brand_term"], item["edit_distance"] = brand_match
        evidence.append(item)

    # The human-facing classified lists are bounded to 25 apiece. Put every query
    # that satisfies a classification rule first, so the evidence cap does not
    # inherit those display caps or orphan a classified query.
    evidence.sort(key=lambda item: (
        item["bucket"] == "single_page",
        -item["impressions"],
        item["query"],
    ))
    return evidence[:QUERY_EVIDENCE_LIMIT], len(evidence) > QUERY_EVIDENCE_LIMIT


def homepage_of(site_url: str) -> str:
    """The property's root URL; a domain property is read over https."""
    if site_url.startswith("sc-domain:"):
        return "https://" + site_url[len("sc-domain:"):].strip("/") + "/"
    parsed = urlparse(site_url)
    return f"{parsed.scheme}://{parsed.netloc}/"


def _is_homepage(page: str, homepage: str, alternate_urls: list[str]) -> bool:
    """The root, or a locale alternate of it: `/en/` declared by hreflang beside `/`
    is the homepage in English, not an inner page. A domain property spans hosts, so
    `www.` and the bare host are one homepage."""
    parsed = urlparse(page)
    home = urlparse(homepage)
    same_site = (parsed.netloc.lower().removeprefix("www.")
                 == home.netloc.lower().removeprefix("www."))
    if same_site and parsed.path.rstrip("/") == "":
        return True
    return (locale_page_key(page, alternate_urls)
            == locale_page_key(homepage, alternate_urls)
            and bool(alternate_urls))


def _inferred_brand(rows: list, homepage: str) -> str:
    """The pre-0.122.0 guess, kept for one narrower job: with no published or
    supplied name, the highest-click query counts as the brand *for classifying
    spreads* when the homepage is the page it lands on. It never decides KW-070 or
    GO-139 — that was the defect: a generic head term judged as the site's name."""
    if not rows:
        return ""
    best = max(rows, key=lambda r: r["clicks"])
    owner = max((r for r in rows if r["query"] == best["query"]),
                key=lambda r: r["clicks"])
    return best["query"] if _is_homepage(owner["page"], homepage, []) else ""


def find_branded(rows: list, site_url: str, brand_names: list[str],
                 brand_source: str, alternate_urls: list[str] | None = None,
                 no_brand_reason: str = "") -> dict:
    """Which page Google serves for the site's most-searched branded query.

    Branded means the query carries one of `brand_names` — never "the query with
    the most clicks", which on a site whose head term is generic is not its name.
    The query judged is the branded one with the most impressions: the brand's own
    search, whichever spelling people use. `searched` is false when no query in the
    window carries the name, and KW-070 and GO-139 then do not apply rather than
    failing a site nobody looked up.
    """
    alternate_urls = alternate_urls or []
    if not brand_names:
        return {"checked": False,
                "reason": no_brand_reason or "no brand name to identify branded queries"}
    if not rows:
        return {"checked": False, "reason": "no query data in range"}
    homepage = homepage_of(site_url)
    # A row with no impressions is nobody's search; it cannot make the brand searched.
    branded_rows = [row for row in rows
                    if row["impressions"] > 0
                    and _any_brand_match(row["query"], brand_names)]
    out = {
        "checked": True,
        "brand_names": brand_names,
        "brand_source": brand_source,
        "branded_queries": len({row["query"] for row in branded_rows}),
        "searched": bool(branded_rows),
        "host": urlparse(homepage).netloc,
    }
    if not branded_rows:
        return out
    impressions: dict[str, list[int]] = {}
    for row in branded_rows:
        total = impressions.setdefault(row["query"], [0, 0])
        total[0] += row["impressions"]
        total[1] += row["clicks"]
    query = min(impressions, key=lambda q: (-impressions[q][0], -impressions[q][1], q))
    pages = _group_locale_pages([row for row in branded_rows if row["query"] == query],
                                alternate_urls)
    owner = pages[0]
    owns = any(_is_homepage(page, homepage, alternate_urls)
               for page in owner["alternates"])
    first = 0 < owner["position"] <= RANKS_FIRST_POSITION
    out.update({
        "query": query,
        "owner_page": owner["page"],
        "position": owner["position"],
        "clicks": owner["clicks"],
        "impressions": owner["impressions"],
        "owns_homepage": owns,
        "ranks_first": first,
        "homepage_ranks_first": owns and first,
    })
    return out


def hreflang_alternates(site_url: str) -> list[str]:
    """Read locale alternates with the same parser as the hreflang audit."""
    homepage = (site_url.replace("sc-domain:", "https://", 1)
                if site_url.startswith("sc-domain:") else site_url)
    try:
        report = run_hreflang_check(homepage)
    except Exception:
        return []
    return [tag["url"] for tag in report.get("tags", []) if tag.get("url")]


def brand_from_site(site_url: str) -> tuple[list[str], str]:
    """(names, why none) read off the homepage. A page that could not be read and
    a page that names nothing are different sentences in the report."""
    html, _final = fetch_html(homepage_of(site_url), timeout=12, quiet=True)
    if not html:
        return [], (f"the homepage {homepage_of(site_url)} could not be read, so no "
                    "brand name was found; pass --brand")
    names = published_brand_names(html)
    if not names:
        return [], ("the homepage publishes no WebSite or organisation name and no "
                    "og:site_name; pass --brand")
    return names, ""


def analyze(site_url: str, credentials: str, days: int,
            alternate_urls: list[str] | None = None,
            brand_names: list[str] | None = None, brand_source: str = "",
            no_brand_reason: str = "") -> dict:
    brand_names = list(brand_names or [])
    result = {
        "property": site_url,
        "period": {"start": None, "end": None},
        "queries_analyzed": 0,
        "queries": [],
        "queries_truncated": False,
        # Not the same cap as `queries_truncated`, which trims the evidence list
        # after the counting is done. This one is upstream of every count in
        # `summary`: it says the API answered with a full page of rows, so there
        # were rows this analysis never saw.
        "truncated": False,
        "cannibalized": [],
        "branded_spread": [],
        "contested": [],
        "branded": {},
        # What `branded_spread` was classified by: the brand's names, or — with no
        # name known — the old inference, said as such.
        "spread_brand": {"source": "none", "names": []},
        # Empty, not `{"cannibalized_queries": None, …}`. `eq` and `truthy` read a
        # None as a *failing value* rather than as silence, so pre-seeding the keys
        # turned a revoked token or an exhausted quota into "two of your URLs compete
        # for one query" and "you do not rank first for your own brand" — four
        # fabricated `high` verdicts about a property nobody managed to open. The
        # measurement fills these in on success; an absent key is NO_DATA, which is
        # what "we could not ask" actually is.
        "summary": {},
        "issues": [],
        "error": None,
    }
    try:
        service = build_service(credentials)
        rows, start, end = fetch_query_page_rows(service, site_url, days)
    except Exception as exc:
        result["error"] = str(exc)[:300]
        # And `issues`, for the same reason the summary is empty: an empty list
        # satisfies `none_severity` and reads as "nothing wrong here".
        result.pop("issues", None)
        return result

    result["period"] = {"start": start, "end": end}
    result["truncated"] = len(rows) >= ROW_LIMIT
    result["queries_analyzed"] = len({r["query"] for r in rows})
    result["branded"] = find_branded(rows, site_url, brand_names, brand_source,
                                     alternate_urls, no_brand_reason)
    spreads = find_query_spreads(rows, alternate_urls)
    if brand_names:
        result["spread_brand"] = {"source": brand_source, "names": brand_names}
    else:
        inferred = _inferred_brand(rows, homepage_of(site_url))
        if inferred:
            result["spread_brand"] = {"source": "inferred", "names": [inferred]}
    spread_brand = result["spread_brand"]["names"]
    result["branded_spread"] = [
        spread for spread in spreads
        if _any_brand_match(spread["query"], spread_brand)
    ][:25]
    # Counted whole, then capped for reading. The 25 is a human-facing cap and
    # `script-output-shapes.md` has always said so — it also says
    # `summary.cannibalized_queries = bucket[cannibalized] + bucket[contested]`,
    # over the classified queries rather than over the shortened list. The code
    # took `len()` of the shortened list instead, so a property with sixty
    # cannibalised queries reported twenty-five of them and the document that
    # said otherwise was the only place the real number existed. It cannot fake a
    # PASS — twenty-five is not zero — but it is the measure MS-023 and KW-071
    # print, and a fix list sized from it is short by every query past the cap.
    cannibalized_all = [
        spread for spread in spreads
        if spread["page_count"] >= MIN_PAGES
        and not _any_brand_match(spread["query"], spread_brand)
    ]
    contested_all = [
        spread for spread in cannibalized_all
        if spread["positions_compared"] >= MIN_PAGES
        and spread["spread"] <= CONTESTED_POSITION_BAND
    ]
    result["cannibalized"] = cannibalized_all[:25]
    result["contested"] = contested_all[:25]
    result["summary"] = {
        "cannibalized_queries": len(cannibalized_all),
        "contested_queries": len(contested_all),
    }
    result["queries"], result["queries_truncated"] = _query_evidence(
        rows, alternate_urls, spread_brand)

    for c in result["cannibalized"][:10]:
        result["issues"].append({
            "severity": "high" if c["impressions"] > HIGH_SEVERITY_IMPRESSIONS else "medium",
            "message": f"'{c['query']}' splits across {c['page_count']} URLs "
                       f"({c['impressions']} impressions, rank spread {c['spread']}) — "
                       f"pick one target and consolidate",
        })
    b = result["branded"]
    if b.get("searched") and not b.get("owns_homepage"):
        result["issues"].append({
            "severity": "high",
            "message": f"Branded query '{b['query']}' is served by {b['owner_page']}, "
                       f"not the homepage",
        })
    if b.get("searched") and not b.get("ranks_first"):
        result["issues"].append({
            "severity": "high",
            "message": f"Branded query '{b['query']}' averages position {b['position']}",
        })
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Find keyword cannibalization and branded-query ownership via GSC")
    parser.add_argument("site_url", help="GSC property (sc-domain:example.com or URL)")
    parser.add_argument("--credentials", default="",
                        help="Service account JSON (or GSC_CREDENTIALS_PATH / GV_SA_KEY)")
    parser.add_argument("--days", type=int, default=28)
    parser.add_argument("--brand", action="append", default=[],
                        help="a name the business is searched by; repeat for more. "
                             "Without it the names the homepage publishes are used")
    parser.add_argument("--json", "-j", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    creds = (args.credentials or os.environ.get("GSC_CREDENTIALS_PATH")
             or os.environ.get("GV_SA_KEY")
             or os.path.expanduser("~/.config/gcloud/gsc-service-account.json"))

    names = [name.strip() for name in args.brand if name.strip()]
    source, why_none = "operator", ""
    if not names:
        names, why_none = brand_from_site(args.site_url)
        source = "published"
    result = analyze(args.site_url, creds, args.days,
                     alternate_urls=hreflang_alternates(args.site_url),
                     brand_names=names, brand_source=source,
                     no_brand_reason=why_none)

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    if result["error"]:
        print(f"GSC query failed: {result['error']}")
        return
    print(f"Cannibalization for {result['property']} "
          f"({result['period']['start']}..{result['period']['end']})")
    print(f"  queries analyzed:     {result['queries_analyzed']}")
    print(f"  cannibalized queries: {result['summary']['cannibalized_queries']}")
    b = result["branded"]
    if b.get("searched"):
        print(f"  branded query:        '{b['query']}' -> {b['owner_page']} "
              f"(pos {b['position']}, homepage={b['owns_homepage']})")
    elif b.get("checked"):
        print(f"  branded query:        none searched for {b['brand_names']}")
    else:
        print(f"  branded query:        not checked — {b.get('reason')}")
    for c in result["cannibalized"][:10]:
        print(f"\n  '{c['query']}' — {c['page_count']} URLs, spread {c['spread']}")
        for p in c["pages"][:3]:
            print(f"      pos {p['position']:<5} {p['impressions']:>5} impr  {p['page'][:70]}")


if __name__ == "__main__":
    main()
