#!/usr/bin/env python3
"""Measure `detect_profile.py`'s MIN_SCORE against homepages whose kind is known.

    python3 tools/calibrate_profile_detection.py            # fetch, score, rewrite the report
    python3 tools/calibrate_profile_detection.py --check    # offline: re-derive from the report

Under `--profile auto` the detector's answer is the profile the audit runs under, and a
profile other than `default` makes 4 to 7 items N/A. MIN_SCORE is the one number that
decides whether the detector answers at all: below it the answer is `default`, the whole
registry. CLEAR_MARGIN does not reach that answer (it labels the confidence printed), and
the four signal tables are forty-odd weights that a corpus of this size cannot fit one by
one; they are measured here only as a whole, through the answer they produce.

The corpus is a fixed list of public homepages, each labelled with the kind of site it
plainly is. **The labels are a person's judgement**, which is the stated limitation: a
SaaS company's blog-heavy homepage, a publisher that sells, a restaurant that ships — the
list avoids the ambiguous ones rather than resolving them, so it measures the detector on
clear cases and says nothing about borderline ones. Only scores and fired signal names
are stored, never page content.

The selection rule, declared before measuring: a wrong narrowing (a profile other than
`default` that is not the site's kind) costs items that apply, while a missed one costs
nothing but scope the operator can still choose, so MIN_SCORE is the smallest value with
the fewest wrong narrowings. `--check` reads only the committed report and the literal
constant; it does not fetch and does not import the detector.
"""
from __future__ import annotations

import python_floor  # noqa: F401

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

from calibration_common import literal_constants

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
SCRIPTS = os.path.join(SKILL_DIR, "scripts")
REPORT = os.path.join(HERE, "calibration", "profile-detection.json")
DETECTOR = os.path.join(SCRIPTS, "detect_profile.py")

# The order `detect()` ranks ties in, read from the detector rather than copied, so the
# sweep reproduces its answer exactly.
PROFILES = literal_constants(DETECTOR, {"PROFILES"},
                             "could not read PROFILES: {missing}")["PROFILES"]
SWEEP = range(1, 13)
SELECTION_RULE = "smallest MIN_SCORE with the fewest wrong narrowings"

# Labelled by what the site plainly is; `default` is a site none of the five fits.
SITES = (
    ("https://www.allbirds.com/", "ecommerce"),
    ("https://www.gymshark.com/", "ecommerce"),
    ("https://bombas.com/", "ecommerce"),
    ("https://www.everlane.com/", "ecommerce"),
    ("https://www.warbyparker.com/", "ecommerce"),
    ("https://www.glossier.com/", "ecommerce"),
    ("https://colourpop.com/", "ecommerce"),
    ("https://ruggable.com/", "ecommerce"),
    ("https://www.katzsdelicatessen.com/", "local"),
    ("https://www.joespizzanyc.com/", "local"),
    ("https://www.peterluger.com/", "local"),
    ("https://www.gramercytavern.com/", "local"),
    ("https://www.langersdeli.com/", "local"),
    ("https://www.zahavrestaurant.com/", "local"),
    ("https://www.frankpepe.com/", "local"),
    ("https://www.elevenmadisonpark.com/", "local"),
    ("https://slack.com/", "saas"),
    ("https://www.notion.com/", "saas"),
    ("https://asana.com/", "saas"),
    ("https://trello.com/", "saas"),
    ("https://www.dropbox.com/", "saas"),
    ("https://mailchimp.com/", "saas"),
    ("https://www.airtable.com/", "saas"),
    ("https://linear.app/", "saas"),
    ("https://kottke.org/", "blog"),
    ("https://daringfireball.net/", "blog"),
    ("https://waitbutwhy.com/", "blog"),
    ("https://marginalrevolution.com/", "blog"),
    ("https://smittenkitchen.com/", "blog"),
    ("https://minimalistbaker.com/", "blog"),
    ("https://pinchofyum.com/", "blog"),
    ("https://seths.blog/", "blog"),
    ("https://www.bbc.com/news", "media"),
    ("https://www.theguardian.com/international", "media"),
    ("https://www.reuters.com/", "media"),
    ("https://apnews.com/", "media"),
    ("https://www.npr.org/", "media"),
    ("https://www.aljazeera.com/", "media"),
    ("https://www.washingtonpost.com/", "media"),
    ("https://edition.cnn.com/", "media"),
    ("https://www.python.org/", "default"),
    ("https://www.w3.org/", "default"),
    ("https://www.redcross.org/", "default"),
    ("https://www.usa.gov/", "default"),
    ("https://web.mit.edu/", "default"),
    ("https://www.nasa.gov/", "default"),
    ("https://archive.org/", "default"),
    ("https://www.wikipedia.org/", "default"),
)


def answer(scores: dict, min_score: int) -> str:
    """`detect()`'s profile for these scores at this MIN_SCORE (CLEAR_MARGIN aside)."""
    ranked = sorted(((p, scores.get(p, 0)) for p in PROFILES), key=lambda kv: -kv[1])
    best, best_score = ranked[0]
    return best if best_score >= min_score else "default"


def sweep(rows: list[dict]) -> list[dict]:
    out = []
    for value in SWEEP:
        correct = wrong = missed = 0
        for row in rows:
            got = answer(row["scores"], value)
            if got == row["label"]:
                correct += 1
            elif got == "default":
                missed += 1
            else:
                wrong += 1
        out.append({"min_score": value, "correct": correct,
                    "wrong_narrowings": wrong, "missed": missed})
    return out


def select(table: list[dict]) -> int:
    fewest = min(row["wrong_narrowings"] for row in table)
    return min(row["min_score"] for row in table if row["wrong_narrowings"] == fewest)


def measure() -> dict:
    sys.path.insert(0, SCRIPTS)
    from detect_profile import detect
    from lib.safe_http import safe_get

    rows, unread = [], []
    for url, label in SITES:
        try:
            response = safe_get(url, timeout=20)
            html = response.text
            status = response.status_code
        except Exception as exc:  # noqa: BLE001 - a site that will not answer is recorded
            unread.append({"url": url, "label": label, "error": str(exc)[:160]})
            continue
        if status != 200 or not html:
            unread.append({"url": url, "label": label, "error": f"HTTP {status}"})
            continue
        found = detect(html, url)
        rows.append({"url": url, "label": label, "status": status,
                     "sha256": hashlib.sha256(html.encode("utf-8", "replace")).hexdigest(),
                     "scores": found["scores"],
                     "signals": {p: s for p, s in found["signals"].items() if s}})
    table = sweep(rows)
    return {
        "generated": datetime.now(timezone.utc).date().isoformat(),
        "method": ("fetch each labelled homepage once through lib.safe_http, score it with "
                   "detect_profile.detect, and re-derive the answer at every MIN_SCORE in "
                   f"{SWEEP.start}..{SWEEP.stop - 1}; {SELECTION_RULE}"),
        "limitation": ("labels are a person's judgement on clear cases; borderline sites "
                       "are left out, so this says nothing about them; one fetch per site, "
                       "so a page that changes moves its row"),
        "selection_rule": SELECTION_RULE,
        "sites": rows,
        "unread": unread,
        "sweep": table,
        "selected_min_score": select(table),
        # What the tree runs with, which is a decision recorded beside the rule's pick
        # rather than assumed to be it (F11: the rule picks a value at which the
        # detector almost always answers `default`).
        "in_force_min_score": literal_constants(
            DETECTOR, {"MIN_SCORE"}, "could not read MIN_SCORE: {missing}")["MIN_SCORE"],
    }


def check() -> int:
    with open(REPORT, encoding="utf-8") as fh:
        report = json.load(fh)
    table = sweep(report["sites"])
    problems = []
    if table != report["sweep"]:
        problems.append("the sweep no longer follows from the stored scores")
    chosen = select(table)
    if chosen != report["selected_min_score"]:
        problems.append(f"the rule selects {chosen}, the report says "
                        f"{report['selected_min_score']}")
    constant = literal_constants(DETECTOR, {"MIN_SCORE"},
                                 "could not read MIN_SCORE: {missing}")["MIN_SCORE"]
    if constant != report["in_force_min_score"]:
        problems.append(f"detect_profile.MIN_SCORE is {constant}, the report records "
                        f"{report['in_force_min_score']} in force")
    for line in problems:
        print(line)
    if not problems:
        print(f"profile-detection.json is in step: MIN_SCORE {constant} in force, the "
              f"rule selects {chosen}, {len(report['sites'])} sites")
    return 1 if problems else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    if a.check:
        return check()
    report = measure()
    with open(REPORT, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False, sort_keys=True)
        fh.write("\n")
    for row in report["sweep"]:
        print(row)
    print(f"selected MIN_SCORE {report['selected_min_score']}; "
          f"{len(report['sites'])} read, {len(report['unread'])} unread")
    return 0


if __name__ == "__main__":
    from utf8_streams import utf8_streams
    utf8_streams()
    sys.exit(main())
