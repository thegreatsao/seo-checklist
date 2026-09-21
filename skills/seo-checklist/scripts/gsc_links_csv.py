#!/usr/bin/env python3
"""
Read the Search Console Links report from its CSV export.

The Links report is the one part of Search Console with **no API** — v3 has never
exposed it and there is no v1 equivalent. The data exists only in the web UI,
behind an Export button. So the honest way to get incoming links without paying
for a third-party index is to export the ZIP once a period and point this script
at it.

Export path: Search Console -> Links -> Export (top right) -> Download CSV. The
ZIP contains several sheets; the ones this reads are the top linking sites and
the top linking text (anchors). Either the ZIP or an unpacked CSV works.

What this can and cannot answer: it reports who links to you and with what
anchors, because that is what Google shows. It says nothing about link quality,
toxicity or spam scores — those need a link index this does not have, and a
number invented here would be worse than the silence.

Usage:
    python gsc_links_csv.py ~/Downloads/example.com-Links.zip --json
    python gsc_links_csv.py ~/Downloads/top-linking-sites.csv --json
"""

import argparse
import csv
import io
import json
import os
import re
import zipfile

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

# Google localises the export, so match on shape rather than on English headers.
# basis: inherited — half the backlinks from one domain, present at import. Blocker: backlink concentration is not a search-analytics number, so no volume of Search Console performance data can calibrate it.
TOP1_SHARE_PCT = 50

SITE_SHEETS = ("linking sites", "linking-sites", "ссылающиеся сайты", "sites")
ANCHOR_SHEETS = ("linking text", "linking-text", "anchor", "текст ссылок")
PAGE_SHEETS = ("linked pages", "linked-pages", "top linked", "страницы")

BRANDED_HINT = re.compile(r"^(https?://)?(www\.)?([^./]+)", re.I)


def _rows(text: str) -> list[list[str]]:
    try:
        dialect = csv.Sniffer().sniff(text[:2048], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    return [r for r in csv.reader(io.StringIO(text), dialect) if r]


def _numeric(cell: str):
    cell = (cell or "").strip().replace(" ", "").replace(" ", "").replace(",", "")
    return int(cell) if cell.isdigit() else None


def parse_sheet(rows: list[list[str]]) -> list[dict]:
    """Two columns: a label and a count. Rows whose second column is not a number
    are treated as headers and dropped rather than guessed at."""
    out = []
    for r in rows:
        if len(r) < 2:
            continue
        n = _numeric(r[1])
        if n is None:
            continue
        out.append({"name": r[0].strip(), "count": n})
    return out


def load(path: str) -> dict:
    """Return {kind: rows} for whatever sheets the export actually contained."""
    sheets: dict[str, list[list[str]]] = {}
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            for name in z.namelist():
                if not name.lower().endswith(".csv"):
                    continue
                sheets[name.lower()] = _rows(z.read(name).decode("utf-8-sig", "replace"))
    else:
        with open(path, encoding="utf-8-sig", errors="replace") as f:
            sheets[os.path.basename(path).lower()] = _rows(f.read())

    def pick(markers):
        for name, rows in sheets.items():
            if any(m in name for m in markers):
                return parse_sheet(rows)
        return []

    found = {
        "sites": pick(SITE_SHEETS),
        "anchors": pick(ANCHOR_SHEETS),
        "pages": pick(PAGE_SHEETS),
    }
    # A single unnamed CSV cannot be classified by filename; treat it as sites,
    # which is the sheet people export most often, and say so in the output.
    if not any(found.values()) and sheets:
        only = parse_sheet(next(iter(sheets.values())))
        found["sites"] = only
        found["_assumed"] = "single unnamed CSV read as the top-linking-sites sheet"
    return found


def analyze(path: str, site: str = "") -> dict:
    result = {
        "source": os.path.abspath(path),
        "site": site,
        "linking_domains": 0,
        "total_links": 0,
        "top_sites": [],
        "anchors": [],
        "top_linked_pages": [],
        "anchor_profile": {"branded": 0, "generic": 0, "other": 0, "classified": 0},
        "concentration": {"top1_share_pct": None, "top10_share_pct": None},
        "note": None,
        "issues": [],
        "error": None,
    }
    if not os.path.exists(path):
        # The export was named and is not there: the person who named it is the
        # one who can fix it, and "script failed" sends them to read our source.
        result["error"] = f"no such file: {path}"
        result["error_kind"] = "input"
        return result
    try:
        found = load(path)
    except Exception as exc:  # noqa: BLE001
        result["error"] = str(exc)[:300]
        return result

    result["note"] = found.get("_assumed")
    sites = found.get("sites") or []
    anchors = found.get("anchors") or []
    result["top_sites"] = sites[:50]
    result["anchors"] = anchors[:50]
    result["top_linked_pages"] = (found.get("pages") or [])[:50]
    result["linking_domains"] = len(sites)
    result["total_links"] = sum(s["count"] for s in sites)

    if sites and result["total_links"]:
        total = result["total_links"]
        result["concentration"]["top1_share_pct"] = round(100 * sites[0]["count"] / total, 1)
        result["concentration"]["top10_share_pct"] = round(
            100 * sum(s["count"] for s in sites[:10]) / total, 1)

    brand = ""
    m = BRANDED_HINT.match(site or "")
    if m:
        brand = m.group(3).lower()
    generic = {"click here", "here", "read more", "more", "link", "website",
               "this site", "visit", "learn more"}
    def squash(s: str) -> str:
        return re.sub(r"[^a-z0-9]", "", s.lower())

    brand_squashed = squash(brand)
    for a in anchors:
        text = a["name"].strip().lower()
        # "river bend" should count as branded for riverbendcafe.example, so
        # compare with spacing and punctuation removed in both directions.
        squashed = squash(text)
        branded = bool(brand_squashed) and bool(squashed) and (
            brand_squashed in squashed or squashed in brand_squashed)
        if branded:
            result["anchor_profile"]["branded"] += a["count"]
        elif text in generic:
            result["anchor_profile"]["generic"] += a["count"]
        else:
            result["anchor_profile"]["other"] += a["count"]
        result["anchor_profile"]["classified"] += a["count"]

    if not sites:
        result["issues"].append({
            "severity": "medium",
            "message": "no linking-sites sheet found in the export — re-export from "
                       "Search Console -> Links -> Export",
        })
    if result["concentration"]["top1_share_pct"] and result["concentration"]["top1_share_pct"] > TOP1_SHARE_PCT:
        result["issues"].append({
            "severity": "high",
            "message": f"{result['concentration']['top1_share_pct']}% of links come from "
                       f"one domain ({sites[0]['name']}) — the profile depends on a "
                       f"single referrer",
        })
    if not brand and site:
        result["issues"].append({
            "severity": "low",
            "message": "could not derive a brand token from --site; anchor "
                       "classification counts everything as 'other'",
        })
    return result


def main():
    ap = argparse.ArgumentParser(
        description="Parse a Search Console Links report export (ZIP or CSV)")
    ap.add_argument("path", help="the exported ZIP, or one CSV from it")
    ap.add_argument("--site", default="", help="site domain, used to spot branded anchors")
    ap.add_argument("--json", "-j", action="store_true", help="Output as JSON")
    args = ap.parse_args()

    result = analyze(args.path, args.site)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return
    if result["error"]:
        print(f"Could not read the export: {result['error']}")
        return
    print(f"Links export: {result['source']}")
    if result["note"]:
        print(f"  note: {result['note']}")
    print(f"  linking domains: {result['linking_domains']}")
    print(f"  total links:     {result['total_links']}")
    c = result["concentration"]
    if c["top1_share_pct"] is not None:
        print(f"  top domain share: {c['top1_share_pct']}%   top 10: {c['top10_share_pct']}%")
    ap_ = result["anchor_profile"]
    if ap_["classified"]:
        print(f"  anchors: branded {ap_['branded']}, generic {ap_['generic']}, "
              f"other {ap_['other']}")
    for s in result["top_sites"][:10]:
        print(f"    {s['count']:>6}  {s['name']}")
    for i in result["issues"]:
        print(f"  [{i['severity']}] {i['message']}")


if __name__ == "__main__":
    main()
