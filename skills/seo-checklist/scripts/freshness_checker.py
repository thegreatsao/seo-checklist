#!/usr/bin/env python3
"""Check content freshness signals and stale references."""

from __future__ import annotations

import argparse
import json
import re
from datetime import date, datetime, timedelta

from seo_common import (
    FOREIGN_CREDIT_KEYS,
    declared_publication_dates,
    declared_publication_dates_by_source,
    load_source,
    page_nodes,
    parse_html,
    under_foreign_credit,
)


# basis: inherited — 730 days, present at import. Two years is the point at which a
#  visible date is reported as old; it is a round number and nothing here measured what
#  staleness costs a given kind of page.
STALE_CONTENT_DAYS = 730

# basis: standard — civil time spans UTC+14 to UTC-12 in the IANA time zone database,
#  twenty-six hours, so a page legitimately published "now" can carry a date two
#  calendar days ahead of the date this checker computes. Three days would admit a
#  scheduled post, which is a date for something not published yet.
#
#  This said `measured` with a corpus, a date and a method until the gate that reads it
#  demanded those three fields and they had to be invented to satisfy it. Nothing here
#  was measured: the number comes from a published standard, and saying so is the whole
#  point of the field.
FUTURE_DATE_TOLERANCE_DAYS = 2

DATE_RE = re.compile(
    r"\b(?:20\d{2}|19\d{2})[-/](?:0?[1-9]|1[0-2])[-/](?:0?[1-9]|[12]\d|3[01])\b|"
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+"
    r"(?:0?[1-9]|[12]\d|3[01]),?\s+(?:20\d{2}|19\d{2})\b",
    re.I,
)
YEAR_RE = re.compile(r"\b(20\d{2}|19\d{2})\b")
STAT_RE = re.compile(r"\b(\d+(?:\.\d+)?%|\$[\d,.]+|\d[\d,.]+\s+(?:users|customers|people|studies|respondents|pages))\b", re.I)


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    value = value.strip()
    for candidate in (value, value[:10]):
        try:
            return datetime.fromisoformat(candidate.replace("Z", "+00:00")).date()
        except ValueError:
            pass
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b %d %Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _schema_dates(schema_items: list, protected=frozenset()) -> dict[str, list[str]]:
    dates = {"dateModified": []}
    for item in schema_items:
        for node in page_nodes(item, hoisted=FOREIGN_CREDIT_KEYS, protected=protected):
            if isinstance(node.get("dateModified"), str):
                dates["dateModified"].append(node["dateModified"])
    return dates


def _time_dates(soup, claimed=None) -> list[str]:
    """The page's own `<time>` values.

    A `<time>` under an `itemprop` naming a foreign credit belongs to whatever that
    property points at: a commenter, a reviewed book, a cited paper. Line 60 has read
    JSON-LD dates through `page_nodes` since 0.67.0 for exactly this reason, and until
    0.70.0 the HTML half of the same function had no boundary, so a schema.org-marked
    comment dated the page.

    By the property descended through, never by the container's `itemtype`: an editorial
    review page is itself a `Review` and its own `datePublished` is its own.

    The traversal now lives in `seo_common` because 0.73.0 needed a second caller.
    """
    return [
        tag.get("datetime") or tag.get_text(" ", strip=True)
        for tag in soup.find_all("time")
        if not under_foreign_credit(tag, claimed=claimed)
    ]


def check_freshness(source: str, timeout: int = 15, today: date | None = None) -> dict:
    today = today or date.today()
    cutoff = today + timedelta(days=FUTURE_DATE_TOLERANCE_DAYS)
    html, url, fetched = load_source(source, timeout)
    parsed = parse_html(html, url)
    soup = parsed["soup"]
    body = parsed.get("body_text", "")

    meta_dates = {}
    for tag in soup.find_all("meta"):
        key = (tag.get("property") or tag.get("name") or "").lower()
        if (key in {"article:published_time", "article:modified_time", "date",
                    "last-modified", "dc.date"}
                and not under_foreign_credit(
                    tag, claimed=parsed.get("foreign_itemref_ids"))):
            meta_dates[key] = tag.get("content")
    time_dates = _time_dates(soup, parsed.get("foreign_itemref_ids"))
    schema_dates = _schema_dates(parsed.get("page_schema", []), protected=parsed.get("page_own_ids", frozenset()))
    publication_dates = declared_publication_dates_by_source(parsed)

    def parsed_values(values):
        return [parsed_date for value in values if (parsed_date := _parse_date(value))]

    published_by_source = {
        "meta": parsed_values([
            meta_dates.get(key)
            for key in ("article:published_time", "date", "dc.date")
        ]),
        "schema": parsed_values(
            publication_dates["schema"] + publication_dates["microdata"]),
        "time": parsed_values(time_dates),
    }
    updated_by_source = {
        "meta": parsed_values([
            meta_dates.get(key)
            for key in ("article:modified_time", "last-modified")
        ]),
        "schema": parsed_values(schema_dates["dateModified"]),
    }
    parsed_time_dates = published_by_source["time"]
    if parsed_time_dates and any(value > min(parsed_time_dates)
                                 for value in parsed_time_dates):
        updated_by_source["time"] = parsed_time_dates

    published_source = next(
        (name for name in ("meta", "schema", "time") if published_by_source[name]),
        None,
    )
    updated_source = next(
        (name for name in ("meta", "schema", "time") if updated_by_source.get(name)),
        None,
    )
    date_signals = {
        "shown": {
            "published": published_source is not None,
            "updated": updated_source is not None,
        },
        "sources": {
            "published": published_source,
            "updated": updated_source,
        },
    }

    parsed_dates = []
    for source_name, values in {
        "meta": list(meta_dates.values()),
        "time": time_dates,
        "schema_published": publication_dates["schema"],
        "schema_modified": schema_dates["dateModified"],
        "body": DATE_RE.findall(body),
    }.items():
        for raw in values:
            parsed_date = _parse_date(raw)
            if parsed_date:
                parsed_dates.append({"source": source_name, "raw": raw, "date": parsed_date.isoformat()})

    future = [item for item in parsed_dates if _parse_date(item["date"]) > cutoff]
    non_future = [_parse_date(item["date"]) for item in parsed_dates
                  if _parse_date(item["date"]) <= cutoff]
    modified_dates = [_parse_date(value) for value in schema_dates["dateModified"] + [meta_dates.get("article:modified_time")]]
    modified_dates = [value for value in modified_dates if value and value <= cutoff]
    published_dates = [_parse_date(value) for value in declared_publication_dates(parsed)]
    published_dates = [value for value in published_dates if value and value <= cutoff]
    latest = max(non_future or modified_dates or published_dates or [], default=None)

    old_years = sorted({int(year) for year in YEAR_RE.findall(body) if int(year) <= today.year - 3})
    stale_stat_count = 0
    for sentence in re.split(r"(?<=[.!?])\s+", body):
        if STAT_RE.search(sentence) and any(str(year) in sentence for year in old_years):
            stale_stat_count += 1

    mismatch = False
    if modified_dates and published_dates and max(modified_dates) < max(published_dates):
        mismatch = True

    age_days = (today - latest).days if latest else None
    score = 100
    if latest is None:
        score -= 35
    elif age_days is not None:
        score -= min(45, max(0, age_days - 365) // 30)
    score -= min(25, stale_stat_count * 5)
    score -= 15 if mismatch else 0

    issues = []
    if latest is None:
        issues.append({"severity": "warning", "message": "No parseable published or modified date found."})
    elif age_days and age_days > STALE_CONTENT_DAYS:
        issues.append({"severity": "warning", "message": f"Latest visible freshness date is {age_days} days old."})
    if stale_stat_count:
        issues.append({"severity": "warning", "message": f"{stale_stat_count} statistic sentence(s) reference old years."})
    if mismatch:
        issues.append({"severity": "warning", "message": "dateModified appears older than datePublished."})
    if future:
        sample = [str(item["raw"]) for item in future[:3]]
        issues.append({
            "severity": "info",
            "message": f"{len(future)} date(s) on this page are more than "
                       f"{FUTURE_DATE_TOLERANCE_DAYS} days in the future and were read as "
                       f"content rather than as publication dates: {', '.join(sample)}",
        })

    return {
        "url": url or source,
        "score": max(0, score),
        "latest_date": latest.isoformat() if latest else None,
        "age_days": age_days,
        "dates": parsed_dates[:50],
        "date_signals": date_signals,
        "old_years": old_years,
        "stale_stat_sentences": stale_stat_count,
        "schema_date_mismatch": mismatch,
        "issues": issues,
        "fetch_error": fetched.get("error"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Check published/modified dates, stale stats, and freshness mismatches.")
    parser.add_argument("source", help="URL or local HTML file")
    parser.add_argument("--today", help="Override current date as YYYY-MM-DD for deterministic tests")
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument("--json", "-j", action="store_true", help="Output JSON")
    args = parser.parse_args()
    today = _parse_date(args.today) if args.today else None

    result = check_freshness(args.source, args.timeout, today)
    print(json.dumps(result, indent=2) if args.json else f"Score: {result['score']} Latest: {result['latest_date']}")


if __name__ == "__main__":
    main()
