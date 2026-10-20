#!/usr/bin/env python3
"""Measure `article_seo.py`'s MIN_PARAGRAPH_WORDS against labelled article bodies.

    python3 tools/calibrate_paragraph_words.py <benchmark-checkout>   # measure, rewrite the report
    python3 tools/calibrate_paragraph_words.py --check                # offline, from the report

KW-076 asks whether the operator's keyword occurs in the page's body text, and that body
is the headings plus every paragraph of more than MIN_PARAGRAPH_WORDS words inside the
CMS's content containers. The cutoff is a classifier — keep a paragraph as body, or drop
it as a caption, a button, a menu line — and a classifier can be scored against pages
whose body somebody else marked. The Zyte (Scrapinghub) article-extraction benchmark is
that: 181 news and blog pages, each with its article body written out by hand
(`ground-truth.json`), public and pinned here by commit.

Method: extract every paragraph `article_seo.extract_content` would consider, with the
cutoff off; call a paragraph body when its whitespace-normalised, lower-cased text occurs
in the page's labelled body; then for each cutoff count body paragraphs kept and dropped
and other paragraphs kept. **Selection rule, written before the run**: the cutoff with
the highest paragraph-level F1 (every paragraph counts once, since the keyword can sit in
any of them), ties to the smaller cutoff. Limitations: news and blog pages only, in
English and a few other languages; a short paragraph can match the body by accident
("Advertisement" inside a sentence), which flatters small cutoffs; the containers are
the CMS-aware ones the script picks, so a page whose container misses its body counts
nothing either way. `--check` reads only the committed report and the literal constant.
"""
from __future__ import annotations

import python_floor  # noqa: F401

import argparse
import gzip
import json
import os
import re
import sys
from datetime import datetime, timezone

from calibration_common import literal_constants

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
SCRIPTS = os.path.join(SKILL_DIR, "scripts")
REPORT = os.path.join(HERE, "calibration", "paragraph-words.json")
CHECKER = os.path.join(SCRIPTS, "article_seo.py")
SOURCE = "https://github.com/scrapinghub/article-extraction-benchmark"
SWEEP = range(0, 21)
SELECTION_RULE = "highest paragraph-level F1, ties to the smaller cutoff"


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def score(pages: list[list[list]]) -> list[dict]:
    """Per cutoff: body paragraphs kept and dropped, other paragraphs kept, and F1."""
    table = []
    for cutoff in SWEEP:
        kept_body = dropped_body = kept_other = 0
        for paragraphs in pages:
            for words, is_body in paragraphs:
                kept = words > cutoff
                if is_body and kept:
                    kept_body += 1
                elif is_body:
                    dropped_body += 1
                elif kept:
                    kept_other += 1
        precision = kept_body / (kept_body + kept_other) if kept_body + kept_other else 0.0
        recall = kept_body / (kept_body + dropped_body) if kept_body + dropped_body else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        table.append({"cutoff": cutoff, "body_kept": kept_body, "body_dropped": dropped_body,
                      "other_kept": kept_other, "precision": round(precision, 4),
                      "recall": round(recall, 4), "f1": round(f1, 4)})
    return table


def select(table: list[dict]) -> int:
    best = max(row["f1"] for row in table)
    return min(row["cutoff"] for row in table if row["f1"] == best)


def _head_commit(checkout: str) -> str:
    """The checkout's commit, read from `.git` rather than by starting git."""
    git = os.path.join(checkout, ".git")
    with open(os.path.join(git, "HEAD"), encoding="utf-8") as fh:
        head = fh.read().strip()
    if not head.startswith("ref: "):
        return head
    ref = head[5:]
    loose = os.path.join(git, *ref.split("/"))
    if os.path.exists(loose):
        with open(loose, encoding="utf-8") as fh:
            return fh.read().strip()
    with open(os.path.join(git, "packed-refs"), encoding="utf-8") as fh:
        for line in fh:
            if line.strip().endswith(" " + ref):
                return line.split()[0]
    return ""


def measure(checkout: str) -> dict:
    sys.path.insert(0, SCRIPTS)
    import article_seo
    from seo_common import parse_html

    with open(os.path.join(checkout, "ground-truth.json"), encoding="utf-8") as fh:
        truth = json.load(fh)
    commit = _head_commit(checkout)
    article_seo.MIN_PARAGRAPH_WORDS = -1   # keep every paragraph; the sweep cuts
    pages, skipped = [], []
    for key in sorted(truth):
        path = os.path.join(checkout, "html", f"{key}.html.gz")
        if not os.path.exists(path):
            skipped.append(key)
            continue
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
            html = fh.read()
        body = _norm(truth[key].get("articleBody") or "")
        parsed = parse_html(html, truth[key].get("url") or "")
        content = article_seo.extract_content(parsed, article_seo.detect_cms(parsed["soup"], truth[key].get("url") or ""))
        pages.append([[len(p.split()), bool(_norm(p)) and _norm(p) in body]
                      for p in content["paragraphs"]])
    table = score(pages)
    return {"generated": datetime.now(timezone.utc).date().isoformat(),
            "source": SOURCE, "commit": commit, "selection_rule": SELECTION_RULE,
            "method": ("article_seo.extract_content with the cutoff off; a paragraph is "
                       "body when its normalised text occurs in the labelled articleBody; "
                       f"cutoffs {SWEEP.start}..{SWEEP.stop - 1}; {SELECTION_RULE}"),
            "pages": pages, "skipped": skipped, "sweep": table,
            "selected_cutoff": select(table)}


def check() -> int:
    with open(REPORT, encoding="utf-8") as fh:
        report = json.load(fh)
    table = score(report["pages"])
    problems = []
    if table != report["sweep"]:
        problems.append("the sweep no longer follows from the stored paragraphs")
    chosen = select(table)
    if chosen != report["selected_cutoff"]:
        problems.append(f"the rule selects {chosen}, the report says {report['selected_cutoff']}")
    constant = literal_constants(CHECKER, {"MIN_PARAGRAPH_WORDS"},
                                 "could not read MIN_PARAGRAPH_WORDS: {missing}")
    if constant["MIN_PARAGRAPH_WORDS"] != chosen:
        problems.append(f"MIN_PARAGRAPH_WORDS is {constant['MIN_PARAGRAPH_WORDS']}, the "
                        f"measurement selects {chosen}")
    for line in problems:
        print(line)
    if not problems:
        print(f"paragraph-words.json is in step: MIN_PARAGRAPH_WORDS {chosen}, "
              f"{len(report['pages'])} pages")
    return 1 if problems else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("checkout", nargs="?", help="a clone of the benchmark repository")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    if a.check:
        return check()
    if not a.checkout:
        ap.error("give the benchmark checkout, or --check")
    report = measure(a.checkout)
    with open(REPORT, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        fh.write("\n")
    for row in report["sweep"]:
        print(row)
    print(f"selected cutoff {report['selected_cutoff']}; {len(report['pages'])} pages, "
          f"{len(report['skipped'])} skipped")
    return 0


if __name__ == "__main__":
    from utf8_streams import utf8_streams
    utf8_streams()
    sys.exit(main())
