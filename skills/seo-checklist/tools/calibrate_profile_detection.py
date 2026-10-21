#!/usr/bin/env python3
"""Measure `detect_profile.py`'s MIN_SCORE against homepages whose kind is known.

    python3 tools/calibrate_profile_detection.py            # fetch, score, rewrite the report
    python3 tools/calibrate_profile_detection.py --check    # offline: re-derive from the report

Under `--profile auto` the detector's answer is the profile the audit runs under, and a
profile other than `default` makes 4 or 8 items N/A (`ecommerce` none). MIN_SCORE is the one number that
decides whether the detector answers at all: below it the answer is `default`, the whole
registry. CLEAR_MARGIN does not reach that answer (it labels the confidence printed), and
the four signal tables are forty-odd weights that a corpus of this size cannot fit one by
one; they are measured here only as a whole, through the answer they produce.

The corpus is a fixed list of public homepages, each labelled with the kind of site it
is. **The labels are a person's judgement**, which is the stated limitation, and some are
ambiguous: three restaurants labelled `local` also run an online shop, and the detector
answering `ecommerce` for them is arguably right. Only scores and fired signal names are
stored, never page content.

The cost the rule weighs is items lost: an answer whose profile excludes an item the
labelled kind's profile keeps makes an applicable item N/A. A wrong answer that excludes
nothing more (`ecommerce` excludes nothing, like `default`) costs nothing but a label, and
an abstention costs only scope the operator can still choose. The rule, declared before
the first measurement and corrected after F11's review (which found the first version
counting every wrong label as a lost item): MIN_SCORE is the smallest value with the
fewest harmful narrowings. The exclusions are taken from the runner's `profile_excludes`
at measuring time and stored. `--check` reads only the committed report and the literal
constants; it does not fetch and does not import the detector. It fails when the signal
tables have changed since the scores were taken, since the stored scores then describe a
different detector.
"""
from __future__ import annotations

import python_floor  # noqa: F401

import argparse
import ast
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
SELECTION_RULE = "smallest MIN_SCORE with the fewest harmful narrowings"


def _tables() -> set[str]:
    """Every `*_SIGNALS` table the detector assigns, and PROFILES, read off its source."""
    with open(DETECTOR, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=DETECTOR)
    names = {target.id for node in tree.body if isinstance(node, ast.Assign)
             for target in node.targets if isinstance(target, ast.Name)}
    return {name for name in names if name.endswith("_SIGNALS")} | {"PROFILES"}

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


def signature() -> str:
    """The detector the scores describe: its signal tables, as written."""
    tables = literal_constants(DETECTOR, _tables(), "could not read the tables: {missing}")
    blob = json.dumps({k: tables[k] for k in sorted(tables)}, sort_keys=True, default=list)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def sweep(rows: list[dict], excludes: dict) -> list[dict]:
    out = []
    for value in SWEEP:
        correct = harmful = wrong_label = abstained = 0
        for row in rows:
            got = answer(row["scores"], value)
            if got == row["label"]:
                correct += 1
                continue
            if got == "default":
                abstained += 1
            else:
                wrong_label += 1
            if set(excludes[got]) - set(excludes[row["label"]]):
                harmful += 1
        out.append({"min_score": value, "correct": correct,
                    "harmful_narrowings": harmful, "wrong_label": wrong_label,
                    "abstained": abstained})
    return out


def select(table: list[dict]) -> int:
    fewest = min(row["harmful_narrowings"] for row in table)
    return min(row["min_score"] for row in table if row["harmful_narrowings"] == fewest)


def profile_exclusions() -> dict:
    """Which items each profile makes N/A, from the runner, at measuring time."""
    sys.path.insert(0, SCRIPTS)
    import checklist_runner as runner
    with open(runner.REGISTRY, encoding="utf-8") as fh:
        items = json.load(fh)["items"]
    return {name: sorted(runner.profile_excludes(items, profile))
            for name, profile in runner.all_profiles().items()}


def derived(rows: list[dict], excludes: dict) -> dict:
    table = sweep(rows, excludes)
    return {"sweep": table, "selected_min_score": select(table),
            "profile_excludes": excludes, "detector_signature": signature()}


def description() -> dict:
    """What the report says about how it was made, the same on a measure and a rescore."""
    return {
        "method": ("fetch each labelled homepage once through lib.safe_http, score it with "
                   "detect_profile.detect, and re-derive the answer at every MIN_SCORE in "
                   f"{SWEEP.start}..{SWEEP.stop - 1}; a harmful narrowing is an answer whose "
                   "profile excludes an item the label's profile keeps; " + SELECTION_RULE),
        "limitation": ("labels are a person's judgement, and three restaurants labelled local "
                       "also run a shop, so ecommerce for them is arguably right; one fetch "
                       "per site, so a page that changes moves its row; 39 sites"),
        "selection_rule": SELECTION_RULE,
    }


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
    return {
        "generated": datetime.now(timezone.utc).date().isoformat(),
        **description(),
        "sites": rows,
        "unread": unread,
        **derived(rows, profile_exclusions()),
        # What the tree runs with, which is a decision recorded beside the rule's pick
        # rather than assumed to be it (F11: adopting the pick moved `--profile auto`
        # verdicts, and the owner decided it; 5 since 0.174.0).
        "in_force_min_score": literal_constants(
            DETECTOR, {"MIN_SCORE"}, "could not read MIN_SCORE: {missing}")["MIN_SCORE"],
    }


def check() -> int:
    with open(REPORT, encoding="utf-8") as fh:
        report = json.load(fh)
    table = sweep(report["sites"], report["profile_excludes"])
    problems = []
    if report["detector_signature"] != signature():
        problems.append("the detector's signal tables changed since the scores were taken; "
                        "measure again")
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
    ap.add_argument("--rescore", action="store_true",
                    help="re-derive the sweep and exclusions from the stored scores, "
                         "without fetching")
    a = ap.parse_args()
    if a.check:
        return check()
    if a.rescore:
        with open(REPORT, encoding="utf-8") as fh:
            report = json.load(fh)
        # The stored scores were taken under one detector; re-deriving them under
        # another would sign old measurements with the new tables (F11's review).
        if report.get("detector_signature") != signature():
            print("the signal tables changed since the scores were taken; measure again "
                  "rather than rescore", file=sys.stderr)
            return 1
        report.update(derived(report["sites"], profile_exclusions()), **description())
        for stale in ("wrong_narrowings",):
            report.pop(stale, None)
    else:
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
