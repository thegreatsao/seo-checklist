#!/usr/bin/env python3
"""Render checklist_runner.py results into readable deliverables.

Produces three artifacts from one results file:
  CHECKLIST-REPORT.md  the audit, grouped by category, dual-metric summary
  CHECKLIST.html       interactive view: filters, and checkboxes for MANUAL items
  LLM-QUEUE.md         the items only a language model can judge

The LLM queue closes the loop: answer it, save the verdicts as JSON, then rerun
with --llm-answers to merge them in and rescore. Without that, LLM_PENDING items
would sit unanswered forever and quietly cap the achievable coverage.

Usage:
    python3 checklist_report.py checklist-results.json
    python3 checklist_report.py checklist-results.json --llm-answers answers.json
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import os
import re
import sys

PASS, FAIL, WARN = "PASS", "FAIL", "WARN"
NO_DATA, MANUAL, LLM_PENDING, NA = "NO_DATA", "MANUAL", "LLM_PENDING", "N/A"
# Split out of NO_DATA in 0.16: the audit would have decided this and was not
# given what it needed. It is the operator's work, not the site's defect and not
# a limit of the tool, and it is the half of "waiting on you" that is not the queue.
NEEDS_INPUT = "NEEDS_INPUT"

# basis: presentation — 60 and 85 choose the colour of a category bar, nothing else. A
#  verdict is already computed by the time either is read, so a reader who disagrees with
#  where amber starts is disagreeing with a stylesheet.
BAR_FAIL_SCORE = 60
BAR_WARN_SCORE = 85          # basis: presentation — the upper band of the pair above
# basis: presentation — how many missing report strings are named before "…", and how
#  many linking pages a broken-URL row lists before "+3". Both are line lengths.
CAVEAT_LIST_SHOWN = 4
LINKED_FROM_SHOWN = 3        # basis: presentation — the same, for a broken-URL row

# basis: presentation — present at import. Only a sort order, so a wrong answer changes
#  what is listed first rather than any verdict.
SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
STATUS_ICON = {PASS: "PASS", FAIL: "FAIL", WARN: "WARN",
               NO_DATA: "NO DATA", NEEDS_INPUT: "NEED INPUT", MANUAL: "MANUAL",
               LLM_PENDING: "LLM", NA: "N/A"}
# Order for every place statuses are listed: the report's status table, the HTML
# legend and its filter buttons. One tuple so a new status cannot be added to two
# of the three and go missing from the third.
STATUS_ORDER = (PASS, WARN, FAIL, NO_DATA, NEEDS_INPUT, LLM_PENDING, MANUAL, NA)
# basis: convention — twenty rows. The opportunity list is as long as the query report
# behind it, and a section nobody scrolls to the end of teaches the reader to skip the
# section. The count and the JSON path are printed when it truncates, so nothing is
# silently dropped.
OPPORTUNITY_LIMIT = 20

def provenance_line(s: dict, L) -> str:
    """How much of the score is a measurement and how much is somebody's word.

    Printed only when the answer is not "all of it". A run with no merged answers
    has nothing to disclose, and a disclosure that is always there is one nobody
    reads by the third report.
    """
    by = s.get("decided_by") or {}
    if not set(by) - {"measured"}:
        return ""
    names = {"measured": L.t("by_measured", "measured here"),
             "model": L.t("by_model", "read by a language model"),
             "claimed": L.t("by_claimed", "answered by a person, on their word")}
    parts = ", ".join(f"{n} {names.get(k, k)}" for k, n in sorted(by.items()))
    return L.t("provenance", "Of the {decided} decided items: {parts}.").format(
        decided=s["decided"], parts=parts)


PARTITION_NOTE = (
    "Every item is in exactly one row and the rows add up to the registry, so "
    "nothing is hidden in a denominator. There is no single coverage percentage on "
    "purpose: it added together how far the tool reached, how much work the operator "
    "had done, and how much of the checklist was never the audit's job, and then "
    "moved for any of the three without saying which.")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def load_scoring():
    from checklist_runner import score  # reuse the single scoring implementation
    return score


from checklist_runner import SEVERITY_WEIGHT  # noqa: E402 — single source of truth


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

I18N_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "resources", "i18n")


class Lang:
    """Report chrome in the reader's language.

    Only the report's own wording is translated. Item titles, evidence and fixes
    stay as the registry wrote them unless a translation file explicitly
    overrides a title — a second, hand-maintained copy of 211 checklist strings
    would drift away from the registry the moment either side changed."""

    def __init__(self, code: str = "en"):
        self.code = code
        self.data = {}
        if code and code != "en":
            path = os.path.join(I18N_DIR, f"{code}.json")
            if not os.path.exists(path):
                raise FileNotFoundError(
                    f"no translation for {code!r}; add {path} or use --lang en")
            with open(path, encoding="utf-8") as f:
                self.data = json.load(f)

    def t(self, key: str, default: str) -> str:
        return self.data.get("strings", {}).get(key, default)

    def status(self, code: str, default: str) -> str:
        return self.data.get("statuses", {}).get(code, default)

    def sev(self, code: str) -> str:
        return self.data.get("severities", {}).get(code, code)

    def effort(self, code: str) -> str:
        return self.data.get("efforts", {}).get(code, code)

    def title(self, item: dict) -> str:
        return self.data.get("item_titles", {}).get(item["id"], item["title"])

    def fix(self, item: dict) -> str:
        """The recommendation, translated when a translation exists.

        Falls back to the registry's own English text rather than leaving a gap: a
        reader who gets the wrong language can still act on it, and a reader who
        gets nothing cannot. `item_fixes` is filled in per language as the need
        arises — 214 pre-written translations would go stale against a generated
        registry, which is the same trap the per-item explanations avoid."""
        return self.data.get("item_fixes", {}).get(item["id"], item.get("fix", ""))

    def category_help(self, key: str) -> str:
        """The plain-language explanation for a category, translated if available.

        Kept in the translation files rather than the code because it is the layer a
        non-specialist actually reads — an English-only explanation of what a
        failure costs is no explanation for the person who has to pay for it."""
        return self.data.get("categories", {}).get(key, CATEGORY_HELP.get(key, ""))

    def untranslated(self) -> list[str]:
        """Which layers of a non-English report will still come out in English.

        A half-translated document is worse than an English one, because the reader
        cannot tell which parts were considered and which were merely left.

        The chrome layer is **counted, not assumed**. This function used to name
        only the two opt-in layers and state that the report's own wording was
        complete — and it was not: 6 of the 51 strings had no translation, and they
        were the whole "what was audited" block, which is the highest-stakes prose in
        the document. `t()` falls back to English for any missing key, silently, so a
        claim about coverage that is not derived from the file is a claim that goes
        stale the next time a string is added. This one is derived.
        """
        if not self.data:
            return []
        out = [name for name, key in (("item titles", "item_titles"),
                                      ("recommendations", "item_fixes"))
               if not self.data.get(key)]
        missing = self.missing_strings()
        if missing:
            out.append(f"{len(missing)} report string(s): {', '.join(missing[:4])}"
                       + (" …" if len(missing) > CAVEAT_LIST_SHOWN else ""))
        return out

    def missing_strings(self) -> list[str]:
        """Keys the report asks `t()` for that this language does not carry.

        Read out of this module's own source, because the alternative is a
        hand-kept list of 51 keys — and a hand-kept list of what a file should
        contain is the thing that just turned out to be wrong.
        """
        if not self.data:
            return []
        with open(os.path.abspath(__file__), encoding="utf-8") as f:
            asked = set(re.findall(r'\bL\.t\(\n?\s*"([a-z_0-9]+)"', f.read()))
        return sorted(asked - set(self.data.get("strings", {})))


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------

# Ranking a fix list by severity alone puts a week of content rewriting above a
# one-line meta tag. Dividing by effort answers the question people actually ask
# first — what is worth doing this afternoon.
# basis: inherited — low 1 / medium 2 / high 4, present at import. Divides
#  SEVERITY_WEIGHT to rank what to do first. 0.18 measured what that ratio is worth
#  with tools/audit_score_sensitivity.py: *dividing* changes 2-4 of the first ten
#  rows against not dividing at all, so the idea earns its place, while the exact
#  ratio does not — 1/2/3 gives the identical first ten on every run measured, and
#  1/3/9 differs by one row. Whether to divide by effort is the decision; which
#  numbers is not
EFFORT_COST = {"low": 1, "medium": 2, "high": 4}


def priority_of(item: dict) -> float:
    """Severity per unit of effort. Higher is more worth doing first."""
    weight = SEVERITY_WEIGHT.get(item.get("severity"), 1)
    return round(weight / EFFORT_COST.get(item.get("effort", "medium"), 2), 2)


def esc_md(text: str) -> str:
    return str(text or "").replace("|", "\\|").replace("\n", " ").strip()


# ---------------------------------------------------------------------------
# Saying it in words
# ---------------------------------------------------------------------------

# One plain sentence per category: what this group of checks is about, and what it
# costs when it is wrong. Written for somebody who runs the business, not the site.
#
# Per category rather than per item, on purpose. Fifteen texts can be kept true;
# 214 would drift out of step with the registry the first time an item changed, and
# a stale explanation attached to a live verdict is worse than none. The specifics
# come from the measurement and the fix, which are generated, so they cannot drift.
CATEGORY_HELP = {
    "crawling_indexing":
        "Whether Google can find, read and store your pages at all. Nothing else on "
        "this list matters if a page never gets into the index.",
    "meta_structured":
        "The title and description Google shows in its results, plus the machine-"
        "readable markup behind them. This is what a searcher reads before deciding "
        "whether to click.",
    "content":
        "Whether each page says something substantial, once, in a way a reader and a "
        "search engine can both follow. Thin or duplicated pages compete with your "
        "own better ones.",
    "keywords":
        "Whether each page targets a distinct search intent. When several pages chase "
        "the same query they split the signal and none of them ranks well.",
    "backlinks":
        "Who links to you from elsewhere. Links remain one of the strongest ranking "
        "signals, and judging their quality needs a link index this audit does not "
        "have — most of these items are for a human.",
    "mobile":
        "How the site behaves on a phone, which is what Google measures and where "
        "most visitors arrive.",
    "speed":
        "How quickly the page becomes usable. Slow pages lose visitors before they "
        "read anything, and speed is a ranking factor in its own right.",
    "security":
        "HTTPS, headers and the basics that keep a browser from warning your "
        "visitors. A warning screen costs the visit outright.",
    "international":
        "Whether Google can tell which language and country each page is for. Wrong "
        "signals send the wrong version to the wrong visitor.",
    "google":
        "What Google's own tools report about the site: indexing state, manual "
        "actions, the queries you actually rank for.",
    "architecture":
        "How pages link to each other. A page buried five clicks deep, or reachable "
        "by no link at all, is a page nobody finds.",
    "technical":
        "Configuration a visitor never sees but a crawler does: redirects, headers, "
        "sitemaps, structured-data validity.",
    "media":
        "Images and video: their weight, their alt text and their markup. Usually the "
        "heaviest thing on a page and the easiest to fix.",
    "competition":
        "How the site stands against the sites it competes with. Judgement work, not "
        "measurement.",
    "local":
        "Everything that makes a business findable in its own town: address, opening "
        "hours, map, reviews, and the markup that ties them together.",
    "geo_ai":
        "Whether AI assistants and AI search can read, quote and attribute your "
        "content. A newer channel than Google, and it reads pages differently.",
}


def phrase_measure(item: dict, L: "Lang | None" = None) -> str:
    """The measurement as a sentence.

    The evidence string stays in the JSON as the audit trail; this is what a reader
    gets. `summary.thin_pages = 6 (want 0)` becomes "Found 6, expected none" — the
    item title already says what was counted, so no vocabulary of JSON paths is
    needed and nothing has to be invented.
    """
    L = L or Lang()
    m = item.get("measure") or {}
    op, kind = m.get("op"), m.get("kind")
    got, want = m.get("got"), m.get("want")

    if m.get("missing") or (not m and item.get("status") == NO_DATA):
        text = L.t("m_missing", "The check ran but produced no value for this.")
    elif kind in ("count", "number") and op in ("eq", "len_eq") and want == 0:
        text = L.t("m_none_expected", "Found {got}; there should be none.").format(got=got)
    elif kind in ("count", "number") and op in ("lte", "len_lte",
                                                "count_matching_lte") and want == 0:
        # "4, and no more than 0 is acceptable" is technically right and reads like
        # a machine. Zero is a different sentence from every other threshold.
        text = L.t("m_none_expected", "Found {got}; there should be none.").format(got=got)
    elif kind in ("count", "number") and op in ("lte", "len_lte", "count_matching_lte"):
        text = L.t("m_at_most", "{got}, and no more than {want} is acceptable.").format(
            got=got, want=want)
    elif kind in ("count", "number") and op in ("gte", "len_gte"):
        text = (L.t("m_none_found", "None found; at least {want} is expected.").format(want=want)
                if not got else
                L.t("m_at_least", "{got}, where at least {want} is expected.").format(
                    got=got, want=want))
    elif kind in ("count", "number") and op == "eq":
        text = L.t("m_exactly", "{got}, where {want} is expected.").format(got=got, want=want)
    elif kind == "flag":
        text = (L.t("m_present", "Present.") if got else L.t("m_absent", "Not found."))
    elif kind == "matches":
        text = (L.t("m_no_match", "Nothing matching was found.") if not got else
                L.t("m_matched", "{got} match(es) found.").format(got=got))
    elif kind == "issues":
        levels = "/".join(m.get("levels") or [])
        text = (L.t("m_no_issues", "No {levels} issues reported.").format(levels=levels)
                if not got else
                L.t("m_issues", "{got} {levels} issue(s) reported.").format(
                    got=got, levels=levels))
    elif kind == "values":
        allowed = ", ".join(str(w) for w in (want or []))
        text = L.t("m_value", "Reported '{got}'; acceptable: {allowed}.").format(
            got=got, allowed=allowed)
    elif got is not None:
        text = L.t("m_reported", "Reported: {got}.").format(got=got)
    else:
        return item.get("evidence", "")

    examples = m.get("examples")
    if examples:
        text += " " + L.t("m_examples", "Namely: {list}.").format(
            list=", ".join(str(e)[:60] for e in examples))
    sample = m.get("sample")
    if sample:
        text += " " + L.t("m_example", "For example: {sample}").format(
            sample=str(sample)[:120])

    decided = item.get("pages_decided")
    matching = item.get("pages_matching")
    if decided and decided > 1 and item.get("status") in (FAIL, WARN):
        text += " " + L.t("m_pages", "Seen on {matching} of {decided} pages checked.").format(
            matching=matching or decided, decided=decided)
    return text


def plain_summary(data: dict, L: "Lang | None" = None) -> list[str]:
    """The three or four sentences that answer "so what?" before any number does."""
    L = L or Lang()
    s = data["scores"]
    c = s["status_counts"]
    broken = c.get(FAIL, 0) + c.get(WARN, 0)
    out = []
    if data.get("entry_reachable") is False:
        return [L.t("p_unreadable",
                    "The page could not be read, so nothing here was measured. "
                    "There is no score for the same reason.")]
    out.append(L.t("p_checked",
                   "We checked {decided} things on this site and {broken} of them "
                   "need work.").format(decided=s["decided"], broken=broken))
    quick = sum(1 for i in data["items"]
                if i["status"] in (FAIL, WARN) and i.get("effort") == "low")
    if quick:
        out.append(L.t("p_quick",
                       "{quick} of those are quick fixes — a setting or a line of "
                       "text, not a rebuild.").format(quick=quick))
    undecided = (c.get(LLM_PENDING, 0) + c.get(MANUAL, 0) + c.get(NO_DATA, 0)
                 + c.get(NEEDS_INPUT, 0))
    if undecided:
        out.append(L.t("p_undecided",
                       "{undecided} more could not be settled by measurement: they "
                       "need a person's judgement, an account we do not have, or "
                       "data that does not exist. They are listed, not hidden.")
                   .format(undecided=undecided))
    return out


# The three buckets a status change falls into, and the third is why this is not
# merely "what changed". `PASS` → `NO_DATA` is not the site getting worse; it is the
# run losing the ability to tell, usually because a third-party service was down or a
# supplied file stopped being supplied. Reporting that as a regression would tell a
# client their site broke when the measurement broke, and the reverse would take
# credit for a fix nobody made.
DIRECTION_HEADING = {
    "improved": ("fixed", "Fixed since then"),
    "regressed": ("regressed", "Got worse"),
    "evidence": ("evidence_changed", "Changed for want of evidence, not on the site"),
}
DIRECTION_NOTE = {
    "improved": ("fixed_note", "These pass now and did not last time."),
    "regressed": ("regressed_note",
                  "These passed last time and do not now — worth looking at first, "
                  "because something changed since the previous audit."),
    "evidence": ("evidence_changed_note",
                 "Neither a fix nor a regression. One run could decide the item and "
                 "the other could not: a service that was unavailable, a "
                 "measurement file supplied to one run and not the other, or a check "
                 "that now declines to answer. The site may not have changed at all."),
}


# What belongs on a task list, and what only looks like it does.
#
# FAIL and WARN are findings somebody fixes. MANUAL is a task for a person and is the
# classic row to assign, so it is here too, carrying its status. NO_DATA and
# LLM_PENDING are **not** fixes: the first is a question this run could not answer —
# usually work for whoever runs the audit, not for whoever owns the site — and the
# second is an item still waiting for a judgement. Putting either in a tracker would
# fill a sprint with the auditor's own unfinished business.
FIX_STATUSES = (FAIL, WARN, MANUAL)

FIX_COLUMNS = ("id", "status", "severity", "effort", "priority", "category",
               "title", "what_to_do", "evidence", "audited_url")


def twins_folded(items: list[dict], keep_status: tuple = FIX_STATUSES) -> list[dict]:
    """One row per piece of work, for the two lists a reader acts on.

    `scores_with` marks an item as a synonym of another: two registry entries asking one
    question, kept because both source checklists asked it, with only one of them
    carrying weight. 0.22 built that so a single defect could not pull the headline down
    twice, and stopped there — the scorer consults `scores_with` and **nothing in this
    file ever did**. So the weight was right and the reader still saw the work twice: one
    image missing an `alt` produced *Provide Meaningful Image Alt Text* (CI-016) at
    priority 6.0 and *Provide Meaningful Alt Text* (MD-186) at 3.0, both `high`, in the
    same "what to do first" list and the same `--fixes` export.

    Two rows for one job is worse in a task list than in a score. A score that is wrong
    is one wrong number; a fix list with a duplicate sends two people to the same image,
    or teaches the reader that the list contains filler.

    Folded only where a reader is being asked to *do* something — the priority list and
    the fix export. The full checklist still prints every item with its own status,
    because the twin genuinely ran and its verdict is part of the audit log; hiding it
    there would make the registry's item count stop adding up.

    The survivor is the item that carries the weight, i.e. the one nothing points at.
    When the twin has the more informative status the fold still keeps the scoring item,
    because that is the one the score, the diff and the history all name.
    """
    # `scores_with` points from the silent twin to the scoring one, so following it once
    # is enough; a chain would be a registry defect and a test forbids it. Which id
    # survives is decided before the walk rather than by list order: the scoring item is
    # the one the score, the diff and the history all name, so a reader who looks it up
    # finds it. Ordering happened to give the right answer here — CI-016 sorts before
    # MD-186 — and "happened to" is not a rule.
    listed = {i["id"] for i in items if i["status"] in keep_status}
    survivor = {}
    for item in items:
        if item["status"] not in keep_status:
            continue
        anchor = item.get("scores_with") or item["id"]
        survivor.setdefault(anchor, anchor if anchor in listed else item["id"])

    folded, taken = [], set()
    for item in items:
        if item["status"] not in keep_status:
            folded.append(item)
            continue
        anchor = item.get("scores_with") or item["id"]
        if anchor in taken or item["id"] != survivor[anchor]:
            continue
        taken.add(anchor)
        folded.append(item)
    return folded


def fix_rows(data: dict) -> list[dict]:
    """The actionable items, flat, ordered the way the report orders them.

    `checklist-results.json` is the full audit log — every item, decided or not, with
    the raw measurement. Getting the actionable part of it into a tracker meant
    parsing the report or filtering the log by hand, so this is the same list the
    report's "What to do first" section shows, in a shape a spreadsheet or an importer
    can read.

    **`audited_url` is the URL the audit was pointed at, not the page with the
    problem.** Most items do not record a page: a page-level check run over a sample
    reports the worst page's verdict without carrying its address, and a site-level
    check has no single page to name. Calling the column what it actually is beats a
    `url` column a reader would reasonably misread as "fix this page".
    """
    rows = []
    for item in twins_folded(data.get("items", [])):
        if item["status"] not in FIX_STATUSES:
            continue
        rows.append({
            "id": item["id"],
            "status": item["status"],
            "severity": item.get("severity", ""),
            "effort": item.get("effort", ""),
            "priority": priority_of(item),
            "category": item.get("category_label", ""),
            "title": item.get("title", ""),
            "what_to_do": item.get("fix", ""),
            "evidence": str(item.get("evidence") or "").replace("\n", " ").strip(),
            "audited_url": data.get("url", ""),
        })
    rows.sort(key=lambda r: (-r["priority"], SEVERITY_ORDER.get(r["severity"], 9),
                             r["id"]))
    return rows


def write_fixes(path: str, data: dict) -> str:
    """Write the fix list as CSV or JSON, chosen by the filename's suffix."""
    rows = fix_rows(data)
    if path.lower().endswith(".json"):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=2)
        return path
    # JSON has no spreadsheet formula semantics, so its branch preserves strings.
    # CSV needs a guard; the accepted cost is that a legitimate leading dash gains an
    # apostrophe in tools that display it.
    # `utf-8-sig` and CRLF, because the overwhelmingly likely destination is
    # somebody's spreadsheet: Excel reads a plain UTF-8 CSV as Latin-1 and turns
    # every non-ASCII character in an item title into mojibake.
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIX_COLUMNS, dialect="excel")
        writer.writeheader()
        writer.writerows({key: "'" + value
                          if isinstance(value, str)
                          and value.startswith(("=", "+", "-", "@", "\t", "\r"))
                          else value
                          for key, value in row.items()}
                         for row in rows)
    return path


# basis: presentation — how many streak rows are listed before the count stands in
#  for the rest. Long enough that the worst offenders are all visible, short enough
#  that the section is read rather than skimmed.
OPEN_SINCE_SHOWN = 12


def trend_section(data: dict, L: "Lang | None" = None) -> list[str]:
    """The arc across stored runs, and what has been failing through all of them.

    `history_section` answers "what changed since last time". This answers the
    question a site owner actually asks — whether months of work moved anything —
    and it needs no new measurement: `.seo-runs/` has held every run since 0.1.0
    and exactly one of them was ever read.

    The streak list is the part that earns the section. A score can sit at 70 for six
    months while a different item fails each time, so the arc alone cannot say whether
    anything is stuck; "FAIL in all six audits since March" can, and it is a different
    sentence to the person paying for the work than "FAIL".
    """
    L = L or Lang()
    history = data.get("history") or []
    streaks = data.get("open_since") or []
    if len(history) < 2 and not streaks:
        return []
    out = ["", f"## {L.t('over_time', 'Over time')}", ""]
    if len(history) >= 2:
        out += [
            L.t("trend_note",
                "Every audit of this domain that is still on disk, oldest first. "
                "The reach column matters as much as the score: a run that could "
                "decide less of the checklist is not a run that found less wrong."),
            "",
            f"| {L.t('when', 'When')} | {L.t('mode', 'Mode')} | "
            f"{L.t('seo_score', 'SEO Score')} | {L.t('reach', 'Reach')} | "
            f"{L.t('decided', 'Decided')} |",
            "|---|---|---:|---:|---:|",
        ]
        for row in history:
            score = row.get("seo_score")
            out.append(
                f"| {str(row.get('started_at') or '')[:16]}"
                f"{' *(' + L.t('this_run', 'this run') + ')*' if row.get('current') else ''} "
                f"| {row.get('mode') or '?'} "
                f"| {'—' if score is None else score} "
                f"| {row.get('weight_pct', '—')}% "
                f"| {row.get('decided', '—')} |")
        out.append("")
    if streaks:
        out += [
            L.t("open_since_note",
                "Open in every audit since the date shown — counted as an unbroken "
                "run backwards from today, so an item that was fixed and broke again "
                "is not listed here as untouched.").format(),
            "",
            f"| {L.t('audits', 'Audits')} | {L.t('since', 'Since')} | "
            f"{L.t('severity', 'Severity')} | ID | {L.t('item', 'Item')} |",
            "|---:|---|---|---|---|",
        ]
        for row in streaks[:OPEN_SINCE_SHOWN]:
            out.append(f"| {row['runs']} | {str(row.get('since') or '')[:10]} "
                       f"| {L.sev(row['severity'])} | {row['id']} "
                       f"| {esc_md(L.title(row))} |")
        if len(streaks) > OPEN_SINCE_SHOWN:
            out.append("")
            out.append(L.t("open_since_more", "+{n} more open across several audits.")
                       .format(n=len(streaks) - OPEN_SINCE_SHOWN))
        out.append("")
    return out


def history_section(data: dict, L: "Lang | None" = None) -> list[str]:
    """What moved since the previous audit of this domain.

    A checklist is a thing people re-run, and until now the report could not say
    whether the last round of fixes worked. `.seo-runs/` held every run, the runner
    computed the comparison only if asked, printed it to a terminal, and it was gone
    when the terminal closed. Nothing here is measured: it is data that was already
    on disk, put where the reader is.

    The baseline is named rather than implied. "Since the previous run" is not a date,
    and a comparison whose other half is anonymous cannot be checked by the person
    being shown it.
    """
    L = L or Lang()
    base = data.get("compared_with")
    diff = data.get("diff")
    if not base or diff is None:
        return []

    when = str(base.get("started_at") or "")[:16]
    out = ["", f"## {L.t('since_last', 'Since the previous audit')}", ""]
    now = data.get("scores") or {}
    score_then, score_now = base.get("seo_score"), now.get("seo_score")
    if score_then is not None and score_now is not None:
        move = score_now - score_then
        arrow = "→" if move == 0 else ("↑" if move > 0 else "↓")
        out += [L.t("since_scores",
                    "Compared with the run of {when}: score {then} {arrow} {now}, "
                    "over {w_then}% {arrow} {w_now}% of the weight in scope.").format(
                        when=when or "?", then=score_then, now=score_now,
                        arrow=arrow, w_then=base.get("weight_pct"),
                        w_now=now.get("weight_pct")), ""]
    else:
        out += [L.t("since_baseline",
                    "Compared with the run of {when}.").format(when=when or "?"), ""]

    # A score that moved because the checklist changed is not a site that moved, and
    # a reader cannot know that without being told.
    if data.get("diff_note"):
        out += [f"*{esc_md(str(data['diff_note']))}*", ""]

    if not diff:
        out += [L.t("since_nothing",
                    "No item changed status."), ""]
        return out

    for kind in ("improved", "regressed", "evidence"):
        rows = [c for c in diff if c.get("direction") == kind]
        if not rows:
            continue
        key, default = DIRECTION_HEADING[kind]
        nkey, ndefault = DIRECTION_NOTE[kind]
        out += [f"### {L.t(key, default)} ({len(rows)})", "",
                f"*{L.t(nkey, ndefault)}*", "",
                f"| ID | {L.t('item', 'Item')} | {L.t('was', 'Was')} | "
                f"{L.t('now', 'Now')} |", "|---|---|---|---|"]
        for c in sorted(rows, key=lambda r: SEVERITY_ORDER.get(r.get("severity"), 9)):
            out.append(f"| {c['id']} | {esc_md(str(c.get('title', '')))} | "
                       f"{c['from']} | {c['to']} |")
        out.append("")
    return out


def broken_url_section(data: dict, L: "Lang | None" = None) -> list[str]:
    """Which URLs are broken, and which pages link to them.

    The one thing a checklist could never give anybody. TE-168 said "3 broken links"
    and every reader's next question was "which ones?", to which the answer was
    "re-run the script yourself". The shared crawl records a status per URL and the
    pages that point at it, so the fix is an address and an edit rather than an
    investigation.

    Only what the crawl actually checked. A URL beyond the crawl's depth or budget is
    in `unchecked_internal_targets` in the inventory and is not listed here as broken,
    because nobody looked.
    """
    L = L or Lang()
    crawl = data.get("crawl") or {}
    broken = crawl.get("broken") or []
    redirected = crawl.get("redirected") or []
    if not broken and not redirected:
        return []
    out = ["", f"## {L.t('broken_urls', 'Broken and redirecting URLs')}", "",
           L.t("broken_urls_note",
               "From one crawl of the site, so these are addresses rather than "
               "counts. Only URLs the crawl reached are listed: {pages} page(s) "
               "checked.").format(pages=(crawl.get("summary") or {})
                                  .get("pages_fetched", "?")), ""]
    if broken:
        out += [f"### {L.t('broken', 'Broken')} ({len(broken)})", "",
                f"| URL | {L.t('status', 'Status')} | "
                f"{L.t('linked_from', 'Linked from')} |", "|---|---|---|"]
        for row in broken[:50]:
            where = (", ".join(row["linked_from"][:3])
                     + (f" +{len(row['linked_from']) - 3}"
                        if len(row["linked_from"]) > LINKED_FROM_SHOWN else "")
                     if row.get("linked_from")
                     else L.t("sitemap_only", "the sitemap only"))
            status = row.get("status") or esc_md(str(row.get("error") or "no response"))[:60]
            out.append(f"| {esc_md(row['url'])} | {status} | {esc_md(where)} |")
        out.append("")
    if redirected:
        out += [f"### {L.t('redirecting', 'Reached through a redirect')} "
                f"({len(redirected)})", "",
                L.t("redirect_note",
                    "Each of these costs a hop on every visit and every crawl. "
                    "Point the links at the destination."), "",
                f"| URL | → | {L.t('hops', 'Hops')} | "
                f"{L.t('linked_from', 'Linked from')} |", "|---|---|---|---|"]
        for row in redirected[:50]:
            out.append(f"| {esc_md(row['url'])} | {esc_md(row.get('to') or '')} | "
                       f"{row.get('hops', 1)} | {len(row.get('linked_from') or [])} |")
        out.append("")
    return out


def provenance_warnings(data: dict, L: "Lang | None" = None) -> list[str]:
    """What the reader has to know about *what was audited*, before the verdicts.

    Every one of these says the same kind of thing: the page these numbers describe
    may not be the page a visitor gets. The runner records all three and prints
    them; until now none of them reached the report, which is the file that
    actually gets handed to somebody — so a `--no-page-guard` run that scored a
    Cloudflare interstitial produced a clean-looking deliverable that never
    mentioned it. Same failure as printing a score for an unreadable site, one
    surface further along.
    """
    L = L or Lang()
    out = []
    # Only when it is not the default. `lxml` is what a normal run uses, so saying so
    # every time would be noise; a run that fell back to `html.parser` — or was told
    # to use it — read every page through a different substrate, and the structural
    # checks are not equivalent between the two.
    parser = data.get("html_parser")
    if parser and parser not in ("lxml", "unknown"):
        out.append(L.t("w_parser",
                       "Pages were parsed with {parser} rather than lxml. Every field "
                       "the checklist reads is identical between the two, but checks "
                       "that depend on document structure are not — a run with the "
                       "other parser can disagree about them.").format(parser=parser))
    if data.get("entry_private"):
        # The stronger statement, and the only one that is a fact rather than a
        # permission: the host resolved to an address only the auditing machine can
        # reach, so the external-API items could not be decided at all.
        out.append(L.t("w_private_host",
                       "The audited host is only reachable from the machine that ran "
                       "this audit (--allow-private), so this describes a local or "
                       "staging copy, not the site a visitor or a search engine "
                       "sees. Anything that needs an outside service — PageSpeed, "
                       "Search Console, index checks — could not be decided."))
    elif data.get("allow_private") and data.get("mode") != "archive":
        # Not in archive mode: nothing was requested, so there was nothing to permit
        # and nowhere a crawl could have wandered.
        out.append(L.t("w_private",
                       "This audit was allowed to reach a private address "
                       "(--allow-private). The host it audited was public, so the "
                       "verdicts stand — but a staging or local copy may have been "
                       "reached while crawling."))
    guard = data.get("entry_guard")
    if guard and not data.get("entry_guard_enforced"):
        out.append(L.t("w_guard",
                       "The entry page looked like {guard} and was audited anyway "
                       "(--no-page-guard). Every page-level verdict below describes "
                       "that page, not the site.").format(guard=guard.replace("_", " ")))
    if data.get("entry_thin") and data.get("entry_reachable") is not False:
        out.append(L.t("w_thin",
                       "The entry page carried {words} visible words. If the site is "
                       "client-rendered, or behind bot protection this tool does not "
                       "recognise, the page-level verdicts describe an empty shell.")
                   .format(words=data.get("entry_visible_words")))
    # Eight items can be decided from a file the operator measured in a browser
    # instead of from anything this run observed. The verdict is only as good as
    # that file, and a reader looking at "LCP 820 ms — PASS" has no way to tell it
    # apart from a measurement the tool took — so the report says which.
    used = {key: entry for key, entry in (data.get("artifacts") or {}).items()
            if entry.get("matches_audited_url") is not False}
    supplied = sorted(key.replace("_", " ").replace(" json", "") for key in used)
    if supplied:
        # The age is stated rather than implied, and in days, because "only as current
        # as that" is a sentence a reader can nod along to without learning anything.
        # A file written four months ago describing today's URL passes every check this
        # run can make — the age is the one thing that can be shown, so it is shown.
        ages = [entry["age_days"] for entry in used.values()
                if entry.get("age_days") is not None]
        when = ""
        if ages:
            when = " " + L.t("w_artifacts_age",
                             "The oldest was written {days} day(s) ago.").format(
                                 days=max(ages))
        out.append(L.t("w_artifacts",
                       "Some verdicts come from measurements supplied with the run "
                       "({kinds}) rather than from anything it observed itself. They "
                       "describe the page and the moment they were taken, and are "
                       "only as current as that.").format(kinds=", ".join(supplied))
                   + when)
    return out


# Each opportunity's own words, rebuilt from its `type` and its numbers.
#
# `gsc_checker.py` writes `finding` and `fix` as English sentences and 0.23.0 printed them
# straight into the report, so a Russian report carried seven English rows. Item titles and
# registry fixes go through `item_titles` / `item_fixes` in the language file; a string a
# script composed at run time has no such door, and this section was the first time
# anything in a report came from one.
#
# Keyed on `type`, which is a stable identifier, never on the sentence. `position`, `ctr`
# and `impressions` are separate fields beside it, so the sentence is rebuilt rather than
# parsed. An unknown type falls back to whatever the script said, in English — worse than
# a translation, much better than an empty cell.
OPPORTUNITY_PHRASE = {
    "striking_distance": (
        ("opp_striking", "Position {position} with {impressions} impressions — within "
                         "striking distance."),
        ("opp_striking_fix", "Optimise the page for this query: put it in the H1 or an "
                             "H2, answer it in more depth, link to the page from "
                             "elsewhere on the site."),
    ),
    "low_ctr_top_position": (
        ("opp_low_ctr", "Position {position} but only {ctr}% of searchers click — "
                        "something above the result is answering for you."),
        ("opp_low_ctr_fix", "Answer the query in 40-55 words directly under a heading, "
                            "and rewrite the title and description to say what the page "
                            "gives."),
    ),
    "high_impressions_low_ctr": (
        ("opp_high_imps", "{impressions} impressions and {ctr}% clicks — the title and "
                          "description are not earning the click."),
        ("opp_high_imps_fix", "Rewrite the title so it names both the thing and the "
                              "benefit, and make the description promise what the page "
                              "delivers."),
    ),
}


def opportunity_phrase(o: dict, L: "Lang") -> tuple[str, str]:
    """One opportunity's finding and fix, in the reader's language where there is one."""
    phrase = OPPORTUNITY_PHRASE.get(str(o.get("type") or ""))
    if not phrase:
        return str(o.get("finding") or ""), str(o.get("fix") or "")
    (found_key, found_en), (fix_key, fix_en) = phrase
    numbers = {k: o.get(k, "?") for k in ("position", "ctr", "impressions")}
    try:
        found = L.t(found_key, found_en).format(**numbers)
    except (KeyError, IndexError, ValueError):
        # A translation carrying a placeholder this data has no field for must not lose
        # the row. The English sentence the script wrote is still true.
        found = str(o.get("finding") or "")
    return found, L.t(fix_key, fix_en)


def lab_performance_lines(data: dict, L: "Lang") -> list[str]:
    """Lighthouse's blended score, named for what it is and kept out of the score.

    Until 0.25.0 SP-111 and SP-112 asserted `performance_score >= 90` under the title
    *Check Core Web Vitals in Search Console*, so a site whose real users were entirely
    inside the thresholds — LCP 1974ms, INP 159ms, CLS 0.00 — was told twice, at `high`,
    to fix Core Web Vitals. The number stays because it is the only speed signal that
    exists for a page CrUX has no sample for; what it stops being is a verdict.
    """
    lab = data.get("lab_performance") or {}
    if not lab:
        return []
    scores = ", ".join(f"{strategy} {score}" for strategy, score in sorted(lab.items()))
    return ["", L.t("lab_perf",
                    "**Lighthouse performance score (lab): {scores}.** Not Core Web "
                    "Vitals and not scored here — it blends Total Blocking Time and "
                    "Speed Index into one figure, measured once from Google's network "
                    "rather than from your visitors. Read it as a hint about where to "
                    "look; the Core Web Vitals verdict is the field data above."
                    ).format(scores=scores), ""]


def opportunity_section(data: dict, L: "Lang | None" = None) -> list[str]:
    """Search Console's opportunities — worth knowing, and not a verdict about anything.

    This is what the registry could not say for four releases. `GO-134` asserted over
    `opportunities[]` through a severity gate, so "Position 4.0 with 115 impressions —
    within striking distance" was reported as a `high` failure and ranked first in the fix
    list: a site's best result, presented as its worst problem. The roadmap read that as a
    missing *status* — something between PASS and FAIL meaning "worth knowing" — and
    costing every surface a new status was the reason it stayed open.

    It was not a status. A status is a verdict about an item, and there is no item here to
    have a verdict about: nobody is failing anything by ranking fourth. What was missing
    was a place in the deliverable for a finding that is neither. So the item now asserts
    on what Search Console reports as broken, and the opportunities are printed here —
    outside the score, outside the partition, outside `--fixes`, and stated as such in the
    text so no reader has to infer it.
    """
    L = L or Lang()
    opportunities = [o for o in (data.get("gsc_opportunities") or [])
                     if isinstance(o, dict) and o.get("finding")]
    lab = data.get("lab_performance") or {}
    if not opportunities and not lab:
        return []
    if not opportunities:
        # The lab score alone still needs the section, and needs a heading that does not
        # promise Search Console suggestions it does not have.
        return [f"## {L.t('worth_knowing', 'Worth knowing')}", ""] + \
            lab_performance_lines(data, L)
    out = [f"## {L.t('opportunities', 'Worth knowing: what Search Console suggests')}", "",
           L.t("opportunities_note",
               "Not defects, and deliberately not scored. Every line is a query this "
               "site already ranks for, where Google's own numbers say there is more to "
               "win — so there is nothing here to fix and nothing here that failed. They "
               "are outside the score, the item partition and the fix list, because a "
               "good result graded as a failure is how a report tells someone to repair "
               "their best page."), "",
           f"| {L.t('query', 'Query')} | {L.t('page', 'Page')} | {L.t('finding', 'What it says')} "
           f"| {L.t('what_to_do', 'What to do')} |", "|---|---|---|---|"]
    for o in opportunities[:OPPORTUNITY_LIMIT]:
        found, fix = opportunity_phrase(o, L)
        out.append(f"| {esc_md(str(o.get('query') or '—'))} "
                   f"| {esc_md(str(o.get('page') or '—'))} "
                   f"| {esc_md(found)} "
                   f"| {esc_md(fix or '—')} |")
    out += lab_performance_lines(data, L)
    if len(opportunities) > OPPORTUNITY_LIMIT:
        out.append("")
        out.append(L.t("opportunities_more",
                       "{shown} of {total} shown; the rest are in "
                       "`gsc_opportunities` in the JSON.").format(
                           shown=OPPORTUNITY_LIMIT, total=len(opportunities)))
    out.append("")
    return out


def render_markdown(data: dict, L: Lang | None = None) -> str:
    s = data["scores"]
    mode = data.get("mode", "live")
    L = L or Lang()
    sampled = data.get("sampled_urls") or []
    out = [
        f"# {L.t('report_title', 'SEO Checklist Audit')}",
        "",
        f"- **{L.t('page', 'URL')}:** {data['url']}",
        f"- **{L.t('mode', 'Mode')}:** `{mode}`"
        + (f" (archive: `{data['archive']}`)" if data.get("archive") else ""),
        f"- **{L.t('profile', 'Profile')}:** `{data.get('profile', 'default')}`",
        f"- **{L.t('generated', 'Run at')}:** {data.get('started_at', '')}",
        f"- **{L.t('registry', 'Registry')}:** `{data.get('registry_version', 'unknown')}`",
        f"- **Search Console:** "
        f"{'found' if data.get('gsc_credentials_found') else 'not configured'}",
    ]
    if len(sampled) > 1:
        out.append(f"- **{L.t('sampled_pages', 'Pages sampled')}:** {len(sampled)}")
    if data.get("only"):
        out.append(f"- **{L.t('scope', 'Scope')}:** "
                   f"`--only {','.join(data['only'])}` — "
                   + L.t("only_note", "a slice of the registry, not a full audit"))
    out += ["", f"## {L.t('summary', 'Summary')}", ""]
    # Above the plain summary, not below it: "this is not the public site" changes
    # what every sentence after it means.
    for line in provenance_warnings(data, L):
        out += [f"> **{L.t('what_was_audited', 'What was audited')}** — {line}", ""]
    # The answer to "so what?" goes above the metrics, not below them. A reader who
    # stops after three lines should still leave with the truth.
    out += [line for line in plain_summary(data, L)] + [""]

    # An unreachable entry page means no site was read, so there is no score to
    # print. Showing one anyway — even a low one — would present the absence of
    # evidence as a measurement, which is the failure this whole report exists
    # to avoid.
    if data.get("entry_reachable") is False:
        out += [
            f"> **{L.t('unreachable_title', 'The site could not be read')}** — "
            + L.t("unreachable_body",
                  "the entry page returned no usable page ({err}). Every check "
                  "that reads the live site is NO_DATA. No score is reported, "
                  "because nothing was measured.").format(
                      err=data.get("entry_error") or "unknown error"),
            "",
        ]
    else:
        p, w = s["partition"], s["waiting_on_you"]
        out += [
            f"**{L.t('seo_score', 'SEO Score')} {s['seo_score']}/100** — "
            + L.t("score_weight",
                  "over {decided} decided items, {pct}% of the weight in scope")
              .format(decided=s["decided"], pct=s["weight_pct"]),
            "",
        ] + ([provenance_line(s, L), ""] if provenance_line(s, L) else []) + [
            L.t("score_note",
                "The share of the weight travels with the score because it is the "
                "claim you can check: the same 69 over 55% of the registry and over "
                "95% of it are not the same statement about a site."),
            "",
            f"| {L.t('bucket', 'Where the registry went')} | "
            f"{L.t('count', 'Count')} | {L.t('who_moves_it', 'Who moves it')} |",
            "|---|---:|---|",
            f"| {L.t('b_decided', 'Decided')} | {p['decided']} | "
            f"{L.t('b_decided_who', 'the score is computed over these')} |",
            f"| {L.t('b_waiting', 'Waiting on you')} | {p['waiting_on_you']} | "
            + L.t("b_waiting_who",
                  "{llm} awaiting a language-model verdict, {inp} awaiting an input "
                  "only you can supply").format(llm=w["llm_pending"],
                                                inp=w["needs_input"]) + " |",
            f"| {L.t('b_person', 'Needs a person')} | {p['needs_a_person']} | "
            f"{L.t('b_person_who', 'answerable, but by a human rather than here')} |",
            f"| {L.t('b_undecided', 'Undecided')} | {p['undecided']} | "
            + L.t("b_undecided_who", "nobody: the site served no such field, or a "
                                     "service could not be reached") + " |",
        ] + ([f"| {L.t('b_na', 'Not applicable')} | {p['not_applicable']} | "
              f"{L.t('b_na_who', 'out of scope for this mode or profile')} |"]
             if p["not_applicable"] else []) + [
            f"| **{L.t('b_total', 'The registry')}** | **{s['total_items']}** | |",
            "",
            L.t("partition_note", PARTITION_NOTE),
            "",
        ]
    out += [
        f"| {L.t('status', 'Status')} | {L.t('count', 'Count')} | {L.t('meaning', 'Meaning')} |",
        "|---|---|---|",
    ]
    meaning = {
        PASS: L.status(PASS, "check passed"),
        FAIL: L.status(FAIL, "check failed — actionable"),
        WARN: L.status(WARN, "borderline, counts as half"),
        NO_DATA: L.status(NO_DATA, "could not be determined — the site served no "
                                   "such field, a service was unreachable, or the "
                                   "check failed"),
        NEEDS_INPUT: L.status(NEEDS_INPUT, "the audit would have decided this and "
                                           "was not given what it needed — see the "
                                           "reason on the item"),
        LLM_PENDING: L.status(LLM_PENDING, "needs a language-model judgement — "
                                           "see LLM-QUEUE.md"),
        MANUAL: L.status(MANUAL, "needs a human — see the Manual section"),
        NA: L.status(NA, f"not applicable in `{mode}` mode; excluded from both metrics"),
    }
    for st in STATUS_ORDER:
        n = s["status_counts"].get(st, 0)
        if n:
            out.append(f"| {STATUS_ICON[st]} | {n} | {meaning[st]} |")

    out += ["", f"### {L.t('by_category', 'By category')}", "",
            f"| {L.t('category', 'Category')} | {L.t('score', 'Score')} | "
            f"{L.t('decided', 'Decided')} | {L.t('failed', 'Failed')} |", "|---|---|---|---|"]
    for cat in s["by_category"].values():
        c = cat["counts"]
        sc = f"{cat['score']}/100" if cat["score"] is not None else "—"
        out.append(f"| {cat['label']} | {sc} | {cat['decided']} | {c.get(FAIL, 0)} |")

    # Folded, because this list asks the reader to do things and a synonym pair is one
    # thing. The full checklist below still prints both halves with their own statuses.
    fails = sorted((i for i in twins_folded(data["items"], (FAIL, WARN))
                    if i["status"] in (FAIL, WARN)),
                   key=lambda i: (-priority_of(i), SEVERITY_ORDER.get(i["severity"], 9)))
    if fails:
        quick = [i for i in fails if i.get("effort") == "low"]
        out += ["", f"## {L.t('do_first', 'What to do first')}", "",
                L.t("do_first_note",
                    "Ordered by how much each matters against how much work it is "
                    "— {quick} of the {total} are quick.").format(
                        quick=len(quick), total=len(fails)), ""]
        # One block per item rather than a row in a seven-column table. The table
        # led with a computed priority float and three jargon columns before it
        # reached the problem, and put the raw assertion in the evidence column.
        current = ""
        for i in fails:
            if i["category_label"] != current:
                current = i["category_label"]
                out += [f"### {current}", ""]
                note = L.category_help(i.get("category", ""))
                if note:
                    out += [f"*{note}*", ""]
            badges = f"{L.sev(i['severity'])} · {L.effort(i.get('effort', 'medium'))}"
            out += [f"**{L.title(i)}**  ",
                    f"`{badges}`  ",
                    f"{phrase_measure(i, L)}  ",
                    f"{L.t('what_to_do', 'What to do')}: {L.fix(i)}", ""]

    # After the fix list and before the broken URLs: "did last month's work land" is
    # the second question a returning reader has, and the first is always "what do I
    # do now".
    out += history_section(data, L)
    out += trend_section(data, L)
    out += broken_url_section(data, L)

    out += ["", f"## {L.t('full_checklist', 'Full checklist')}", ""]
    by_cat: dict[str, list] = {}
    for i in data["items"]:
        by_cat.setdefault(i["category_label"], []).append(i)
    for label, items in by_cat.items():
        out += [f"### {label}", "",
                f"| {L.t('status', 'Status')} | {L.t('sev', 'Sev')} | ID | "
                f"{L.t('item', 'Item')} | {L.t('evidence', 'Evidence')} |",
                "|---|---|---|---|---|"]
        for i in sorted(items, key=lambda x: (x["status"] != FAIL,
                                              SEVERITY_ORDER.get(x["severity"], 9))):
            out.append(f"| {STATUS_ICON[i['status']]} | {L.sev(i['severity'])} | {i['id']} | "
                       f"{esc_md(L.title(i))} | {esc_md(i['evidence'])} |")
        out.append("")

    manual = [i for i in data["items"] if i["status"] == MANUAL]
    if manual:
        out += [f"## {L.t('requires_human', 'Requires a human')}", "",
                L.t("manual_note", "These cannot be scripted. Nothing here "
                                   "counts against the score."), ""]
        for i in sorted(manual, key=lambda x: SEVERITY_ORDER.get(x["severity"], 9)):
            out.append(f"- [ ] **{i['id']}** ({L.sev(i['severity'])}) "
                       f"{L.title(i)} — {L.fix(i)}")
        out.append("")

    # Its own section, and that is the whole point of splitting the status. These
    # items are not a limit of the audit and not a defect of the site — they are the
    # arguments this run was not given, and folding them in with the undetermined
    # ones is how thirteen fixable items read as "could not be determined" for
    # fifteen releases.
    needs = [i for i in data["items"] if i["status"] == NEEDS_INPUT]
    if needs:
        out += [f"## {L.t('needs_input', 'What this audit was not given')}", "",
                L.t("needs_input_note",
                    "Each of these would have been decided if the run had been "
                    "handed one more thing. They are work for whoever runs the "
                    "audit, not for whoever owns the site, and the reason names the "
                    "argument that fills it."), "",
                f"| ID | {L.t('item', 'Item')} | {L.t('why', 'Why')} |", "|---|---|---|"]
        for i in sorted(needs, key=lambda x: SEVERITY_ORDER.get(x["severity"], 9)):
            out.append(f"| {i['id']} | {esc_md(i['title'])} | {esc_md(i['evidence'])} |")
        out.append("")

    blocked = [i for i in data["items"] if i["status"] == NO_DATA]
    if blocked:
        out += [f"## {L.t('undetermined', 'Undetermined')}", "",
                L.t("undetermined_note",
                    "Checks that ran and could not produce a verdict, with nothing "
                    "anybody could supply to change that. None of them lowers the "
                    "score; all of them narrow what it speaks for."), "",
                f"| ID | {L.t('item', 'Item')} | {L.t('why', 'Why')} |", "|---|---|---|"]
        for i in blocked:
            out.append(f"| {i['id']} | {esc_md(i['title'])} | {esc_md(i['evidence'])} |")
        out.append("")

    out += opportunity_section(data, L)

    errs = {k: v["error"] for k, v in data.get("runs", {}).items() if v.get("error")}
    if errs:
        out += [f"## {L.t('script_errors', 'Script errors')}", "",
                f"| {L.t('script', 'Script')} | {L.t('error', 'Error')} |", "|---|---|"]
        for k, v in errs.items():
            out.append(f"| `{esc_md(k)}` | {esc_md(v)[:160]} |")
        out.append("")

    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# LLM queue
# ---------------------------------------------------------------------------

# Which agent answers which lens, and what each one has to read. Splitting the
# queue this way means each agent reads its own slice of the page once; splitting
# by checklist category would have four agents re-reading the same body copy.
LENS_AGENTS = {
    "copy": ("seo-llm-copy", "the body text: prose quality, originality, intent match"),
    "layout": ("seo-llm-layout", "the rendered page furniture: ads, pop-ups, navigation, menus"),
    "locale": ("seo-llm-locale", "language and region targeting, translation quality"),
    "market": ("seo-llm-market", "competitive and geographic positioning"),
}


def render_llm_queue(data: dict, lens: str = "") -> str:
    pending = [i for i in data["items"] if i["status"] == LLM_PENDING]
    if lens:
        pending = [i for i in pending if i.get("lens") == lens]
    agent, reads = LENS_AGENTS.get(lens, ("", ""))
    out = [
        f"# LLM judgement queue{f' — {lens}' if lens else ''}",
        "",
        f"Page under audit: {data['url']}",
        "",
    ]
    if lens:
        out += [f"Assigned agent: `{agent}`. Read {reads}.", ""]
    out += [
        f"{len(pending)} checklist items need a judgement no script can make. Read the actual "
        "page content, then rule on each one. Do not guess from the URL or from this file alone — "
        "if the page does not give you enough to decide, answer `N/A` and say why.",
        "",
        "For each item answer with one of:",
        "",
        "- `PASS` — the page clearly satisfies it",
        "- `FAIL` — the page clearly violates it (say exactly where)",
        "- `WARN` — partially satisfied",
        "- `N/A` — not applicable to this page, or undecidable from the content",
        "",
        "Save the verdicts as JSON and merge them back. Every id below is one this "
        "file is asking about — fill in the two fields and change nothing else:",
        "",
        "```json",
        "{",
    ] + [
        # The real ids, not an example. The example used to name CN-047 and CN-060
        # whatever the file was for, so a per-lens queue asking about IN-126 and
        # IN-130 showed a skeleton for two items that were not in it — an invitation
        # to answer somebody else's slice, or to mistype an id into a merge that
        # silently applies nothing. A template that cannot be pasted wrong is worth
        # more than a shorter one.
        f'  "{i["id"]}": {{ "status": "", "evidence": "" }}'
        + ("," if n < len(pending) - 1 else "")
        for n, i in enumerate(pending)
    ] + [
        "}",
        "```",
        "",
        "```bash",
        "python3 checklist_report.py checklist-results.json --llm-answers answers.json",
        "```",
        "",
        "Then have a second reader go through the same items independently and "
        "merge that with `--llm-review review.json`. Where the two agree the "
        "verdict says so; where they disagree the item returns to `NO_DATA` "
        "carrying both readings, because two careful readings that conflict mean "
        "the page did not settle it. The reviewer cannot overwrite a verdict — "
        "see `resources/agents/seo-llm-adversary.md`.",
        "",
        "---",
        "",
    ]
    by_cat: dict[str, list] = {}
    for i in pending:
        by_cat.setdefault(i["category_label"], []).append(i)
    for label, items in by_cat.items():
        out += [f"## {label}", ""]
        for i in sorted(items, key=lambda x: SEVERITY_ORDER.get(x["severity"], 9)):
            out += [f"### {i['id']} ({i['severity']})", "",
                    f"**{i['title']}**", "",
                    f"What good looks like: {i['fix']}", ""]
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

CSS = """
:root{--bg:#fff;--fg:#1a1a1a;--mut:#666;--line:#e3e3e3;--card:#fafafa;
--pass:#1a7f37;--fail:#c1121f;--warn:#b06000;--none:#6b6b6b;--na:#9a9a9a}
@media(prefers-color-scheme:dark){:root{--bg:#111;--fg:#eee;--mut:#9a9a9a;--line:#2c2c2c;
--card:#191919;--pass:#3fb950;--fail:#f85149;--warn:#d29922;--none:#8b949e;--na:#6e6e6e}}
*{box-sizing:border-box}body{margin:0;padding:2rem 1rem;background:var(--bg);color:var(--fg);
font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1080px;margin:0 auto}h1{font-size:1.6rem;margin:0 0 .3rem}
.sub{color:var(--mut);margin-bottom:1.5rem;font-size:.9rem}
.metrics{display:flex;gap:1rem;flex-wrap:wrap;margin-bottom:.75rem}
.metric{flex:1 1 220px;background:var(--card);border:1px solid var(--line);
border-radius:10px;padding:1rem}.metric b{display:block;font-size:2rem;line-height:1.1}
.metric span{color:var(--mut);font-size:.85rem}
.note{color:var(--mut);font-size:.85rem;margin:0 0 1.5rem;max-width:70ch}
.bar{display:flex;height:9px;border-radius:5px;overflow:hidden;margin:1rem 0 1.5rem}
.bar i{display:block}
.filters{display:flex;gap:.4rem;flex-wrap:wrap;margin-bottom:1.25rem}
.filters button{background:var(--card);color:var(--fg);border:1px solid var(--line);
border-radius:999px;padding:.3rem .8rem;cursor:pointer;font-size:.85rem}
.filters button[aria-pressed=true]{background:var(--fg);color:var(--bg);border-color:var(--fg)}
h2{font-size:1.05rem;margin:1.75rem 0 .5rem;padding-bottom:.3rem;border-bottom:1px solid var(--line)}
.row{display:grid;grid-template-columns:80px 62px 1fr;gap:.6rem;padding:.55rem .4rem;
border-bottom:1px solid var(--line);align-items:start}
.row:last-child{border-bottom:0}
.st{font-size:.7rem;font-weight:700;letter-spacing:.03em;padding-top:.15rem}
.PASS{color:var(--pass)}.FAIL{color:var(--fail)}.WARN{color:var(--warn)}
.NO_DATA,.LLM_PENDING,.NEEDS_INPUT{color:var(--none)}.MANUAL{color:var(--fg)}.NA{color:var(--na)}
.sev{font-size:.7rem;color:var(--mut);padding-top:.2rem}
.ttl{font-weight:500}.ev{color:var(--mut);font-size:.83rem;margin-top:.15rem;word-break:break-word}
.fix{font-size:.83rem;margin-top:.2rem}
.row.done .ttl{opacity:.45;text-decoration:line-through}
label.chk{display:inline-flex;gap:.4rem;align-items:center;cursor:pointer}
.hidden{display:none}
h3{font-size:.95rem;margin:1.25rem 0 .4rem;color:var(--mut)}
small{font-size:.55em;font-weight:400;color:var(--mut)}

/* Layer 1 — the plain answer, before any number */
.hero{margin-bottom:2rem}
/* What was audited, when it may not be the public site. Above the summary
   because it changes what every sentence after it means. */
.caveat{border-left:3px solid var(--warn);background:var(--card);padding:.7rem .9rem;
margin:0 0 1rem;font-size:.9rem;max-width:70ch;border-radius:0 6px 6px 0}
.caveat b{color:var(--warn)}
.plain p{font-size:1.15rem;line-height:1.5;margin:.2rem 0 .6rem;max-width:60ch}
.metric.warnbox b{color:var(--fail)}
.legend{display:flex;gap:1rem;flex-wrap:wrap;font-size:.78rem;color:var(--mut);
margin:-1rem 0 0}
.legend span{display:inline-flex;align-items:center;gap:.35rem}
.legend i{width:9px;height:9px;border-radius:2px;display:inline-block}

/* Layer 2 — where the problems are */
.catrow{display:grid;grid-template-columns:minmax(120px,1.4fr) 3fr 68px 1.6fr;
gap:.75rem;align-items:center;padding:.3rem 0;font-size:.9rem}
.catname{font-weight:500}
.cattrack{background:var(--line);border-radius:999px;height:8px;overflow:hidden}
.cattrack i{display:block;height:100%;border-radius:999px}
.cattrack .pass{background:var(--pass)}.cattrack .warn{background:var(--warn)}
.cattrack .fail{background:var(--fail)}
.catnum{text-align:right;font-variant-numeric:tabular-nums}
.catmeta{color:var(--mut);font-size:.8rem}
.cathelp{color:var(--mut);font-size:.83rem;margin:.1rem 0 .9rem;max-width:78ch;
padding-left:.1rem}
@media(max-width:640px){.catrow{grid-template-columns:1fr 60px;grid-auto-rows:auto}
.cattrack{grid-column:1/-1}.catmeta{grid-column:1/-1}}

/* Layer 3 — one card per thing to fix */
.card{background:var(--card);border:1px solid var(--line);border-left:3px solid var(--fail);
border-radius:8px;padding:.85rem 1rem;margin:.6rem 0}
.card.WARN{border-left-color:var(--warn)}
.cardhead{display:flex;gap:.4rem;align-items:center;flex-wrap:wrap;margin-bottom:.35rem}
.card h3{margin:.1rem 0 .35rem;font-size:1rem;color:var(--fg)}
.badge{font-size:.7rem;text-transform:uppercase;letter-spacing:.04em;
border-radius:999px;padding:.12rem .5rem;border:1px solid var(--line);color:var(--mut)}
.badge.sev-critical,.badge.sev-high{color:var(--fail);border-color:var(--fail)}
.badge.sev-medium{color:var(--warn);border-color:var(--warn)}
.badge.eff{color:var(--mut)}
.cardhead .cat{font-size:.75rem;color:var(--mut);margin-left:auto}
.found{margin:.1rem 0 .4rem;font-weight:500}
.why{color:var(--mut);font-size:.86rem;margin:.1rem 0 .5rem;max-width:78ch}
.do{margin:.2rem 0 .1rem;font-size:.9rem}
details.tech{margin-top:.5rem}
details.tech summary{cursor:pointer;color:var(--mut);font-size:.78rem}
.techbody{font-size:.78rem;color:var(--mut);padding:.4rem 0 0;word-break:break-word}

/* Layer 4 — folded machine detail */
details.fold{border-top:1px solid var(--line);padding:.6rem 0}
details.fold>summary{cursor:pointer;font-weight:500;font-size:.95rem}
details.fold .count{color:var(--mut);font-weight:400;font-size:.85rem}
details.fold[open]>summary{margin-bottom:.75rem}
.foot{color:var(--mut);font-size:.78rem;margin-top:2rem}
code{font-size:.9em;background:var(--card);padding:.05rem .3rem;border-radius:4px}
"""

JS = """
const key = 'seo-checklist-' + document.body.dataset.domain;
const saved = JSON.parse(localStorage.getItem(key) || '{}');
document.querySelectorAll('input[type=checkbox][data-id]').forEach(cb => {
  if (saved[cb.dataset.id]) { cb.checked = true; cb.closest('.row').classList.add('done'); }
  cb.addEventListener('change', () => {
    saved[cb.dataset.id] = cb.checked;
    localStorage.setItem(key, JSON.stringify(saved));
    cb.closest('.row').classList.toggle('done', cb.checked);
  });
});
const exportBtn = document.getElementById('export-manual');
if (exportBtn) exportBtn.addEventListener('click', () => {
  // A tick says "passes" and cannot say anything else, so the evidence field is
  // seeded rather than invented: it states what actually happened, which is that
  // somebody ticked a box. Merging refuses an answer whose reason is empty, and
  // this string is deliberately not good enough to leave as it is.
  const out = {};
  document.querySelectorAll('input[type=checkbox][data-id]').forEach(cb => {
    if (cb.checked) out[cb.dataset.id] = {
      status: 'PASS',
      evidence: 'ticked in the HTML report on ' + new Date().toISOString().slice(0, 10)
                + ' — replace this with what was checked'};
  });
  const n = Object.keys(out).length;
  if (!n) { alert('Nothing is ticked yet.'); return; }
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([JSON.stringify(out, null, 2)],
                                        {type: 'application/json'}));
  a.download = 'manual-answers.json';
  a.click();
  URL.revokeObjectURL(a.href);
});
document.querySelectorAll('.filters button').forEach(b => {
  b.addEventListener('click', () => {
    const active = b.dataset.f;
    document.querySelectorAll('.filters button').forEach(o =>
      o.setAttribute('aria-pressed', o === b));
    document.querySelectorAll('.row').forEach(r =>
      r.classList.toggle('hidden', active !== 'ALL' && r.dataset.st !== active));
    document.querySelectorAll('section').forEach(s =>
      s.classList.toggle('hidden', !s.querySelector('.row:not(.hidden)')));
  });
});
"""


def _badges(item: dict, L: Lang) -> str:
    sev = html.escape(L.sev(item["severity"]))
    eff = html.escape(L.effort(item.get("effort", "medium")))
    return (f'<span class="badge sev-{item["severity"]}">{sev}</span>'
            f'<span class="badge eff">{eff}</span>')


def _card(item: dict, L: Lang) -> str:
    """One thing to fix, as a reader needs it: what, how bad, what it costs, what to
    do — and the machine detail folded away rather than deleted."""
    why = L.category_help(item.get("category", ""))
    tech = html.escape(item.get("evidence", ""))
    script = html.escape(str(item.get("script", "")))
    detail = (f'<summary>{html.escape(L.t("technical_detail", "Technical detail"))}</summary>'
              f'<div class="techbody"><code>{item["id"]}</code>'
              + (f' &middot; <code>{script}</code>' if script else "")
              + f'<div>{tech}</div></div>')
    return (f'<article class="card {item["status"]}" data-st="{item["status"]}">'
            f'<div class="cardhead">{_badges(item, L)}'
            f'<span class="cat">{html.escape(item["category_label"])}</span></div>'
            f'<h3>{html.escape(L.title(item))}</h3>'
            f'<p class="found">{html.escape(phrase_measure(item, L))}</p>'
            + (f'<p class="why">{html.escape(why)}</p>' if why else "")
            + (f'<p class="do"><b>{html.escape(L.t("what_to_do", "What to do"))}:</b> '
               f'{html.escape(L.fix(item))}</p>' if item.get("fix") else "")
            + f'<details class="tech">{detail}</details></article>')


def render_html(data: dict, L: Lang | None = None) -> str:
    """Four layers, widest audience first.

    The old report was one flat run of 214 equal-weight table rows whose evidence
    column printed the assertion's internals — `summary.thin_pages = 6 (want 0)`.
    Informative to whoever wrote the registry, opaque to whoever owns the site.
    Nothing is removed here: the plain layer comes first, the machine layer is
    folded underneath it, and the full checklist stays as the audit trail.
    """
    L = L or Lang()
    s = data["scores"]
    mode = data.get("mode", "live")
    counts = s["status_counts"]
    unreadable = data.get("entry_reachable") is False

    seg = [(FAIL, "var(--fail)"), (WARN, "var(--warn)"), (PASS, "var(--pass)"),
           (NO_DATA, "var(--none)"), (NEEDS_INPUT, "var(--none)"),
           (LLM_PENDING, "var(--none)"),
           (MANUAL, "var(--line)"), (NA, "var(--na)")]
    total = sum(counts.values()) or 1
    bar = "".join(f'<i style="width:{100 * counts.get(k, 0) / total:.2f}%;background:{c}" '
                  f'title="{STATUS_ICON[k]}: {counts.get(k, 0)}"></i>'
                  for k, c in seg if counts.get(k))

    parts = [f'<div class="wrap"><h1>{html.escape(L.t("report_title", "SEO Checklist Audit"))}'
             f' &mdash; {html.escape(data.get("domain", ""))}</h1>',
             f'<p class="sub">{html.escape(data["url"])} &middot; <code>{mode}</code>'
             f' &middot; {html.escape(str(data.get("profile", "default")))}'
             f' &middot; {html.escape(str(data.get("started_at", ""))[:16])}</p>']

    # -- Layer 1: what this means, in sentences, before any number ---------------
    parts.append('<section class="hero">')
    parts += [f'<p class="caveat"><b>{html.escape(L.t("what_was_audited", "What was audited"))}'
              f'</b> — {html.escape(line)}</p>'
              for line in provenance_warnings(data, L)]
    parts.append('<div class="plain">'
                 + "".join(f"<p>{html.escape(line)}</p>" for line in plain_summary(data, L))
                 + "</div>")
    if unreadable:
        parts.append(f'<div class="metrics"><div class="metric"><b>&mdash;</b><span>'
                     f'{html.escape(L.t("no_score", "No score: the entry page could not be read"))}'
                     f'</span></div></div>')
    else:
        parts += [
            '<div class="metrics">',
            f'<div class="metric"><b>{s["seo_score"]}<small>/100</small></b>'
            f'<span>{html.escape(L.t("m_score_help", "Of the checks that could be decided, how many passed — weighted by how much each matters"))}</span></div>',
            f'<div class="metric"><b>{s["weight_pct"]}<small>%</small></b>'
            f'<span>{html.escape(L.t("m_weight_help", "How much of the registry that score speaks for, by weight: {decided} of {total} items decided").format(decided=s["decided"], total=s["total_items"]))}</span></div>',
            f'<div class="metric warnbox"><b>{counts.get(FAIL, 0) + counts.get(WARN, 0)}</b>'
            f'<span>{html.escape(L.t("m_broken_help", "Checks that need work"))}</span></div>',
            f'<div class="metric"><b>{s["partition"]["waiting_on_you"]}</b>'
            f'<span>{html.escape(L.t("m_waiting_help", "Waiting on you: {llm} unanswered language-model items, {inp} missing inputs").format(llm=s["waiting_on_you"]["llm_pending"], inp=s["waiting_on_you"]["needs_input"]))}</span></div>',
            "</div>",
            (f'<p class="note claimed">{html.escape(provenance_line(s, L))}</p>'
             if provenance_line(s, L) else ""),
            f'<p class="note">{html.escape(L.t("partition_note", PARTITION_NOTE))}</p>',
        ]
    parts.append(f'<div class="bar">{bar}</div><div class="legend">'
                 + "".join(f'<span><i style="background:{c}"></i>'
                           f'{STATUS_ICON[k]} {counts.get(k, 0)}</span>'
                           for k, c in seg if counts.get(k))
                 + "</div></section>")

    # -- Layer 2: where the problems are, as bars ------------------------------
    cats = [(key, cat) for key, cat in s["by_category"].items() if cat["decided"]]
    # Severity-weighted score, then the worst open severity as the tie-break: two
    # categories on 80 are not equally urgent if one of them is holding a failing
    # critical. Same ordering the fix list below uses, so the two layers agree
    # about what to look at first.
    cats.sort(key=lambda kv: (kv[1]["score"] if kv[1]["score"] is not None else 101,
                              SEVERITY_ORDER.get(kv[1].get("worst_open"), 9)))
    if cats:
        parts.append(f'<section><h2>{html.escape(L.t("where", "Where the problems are"))}</h2>')
        for key, cat in cats:
            score = cat["score"]
            tone = ("fail" if score < BAR_FAIL_SCORE
                    else ("warn" if score < BAR_WARN_SCORE else "pass"))
            failed = cat["counts"].get(FAIL, 0) + cat["counts"].get(WARN, 0)
            parts.append(
                f'<div class="catrow"><div class="catname">{html.escape(cat["label"])}</div>'
                f'<div class="cattrack"><i class="{tone}" style="width:{score}%"></i></div>'
                f'<div class="catnum">{score}<small>/100</small></div>'
                f'<div class="catmeta">'
                + html.escape(L.t("cat_meta", "{decided} checked, {failed} need work")
                              .format(decided=cat["decided"], failed=failed))
                + (f' · <b>{html.escape(L.sev(cat["worst_open"]))}</b>'
                   if cat.get("worst_open") in ("critical", "high") else "")
                + "</div></div>")
            help_text = L.category_help(key)
            if help_text and failed:
                parts.append(f'<p class="cathelp">{html.escape(help_text)}</p>')
        parts.append("</section>")

    # -- Layer 3: what to do, as cards ------------------------------------------
    todo = sorted((i for i in twins_folded(data["items"], (FAIL, WARN))
                   if i["status"] in (FAIL, WARN)),
                  key=lambda i: (-priority_of(i), SEVERITY_ORDER.get(i["severity"], 9)))
    if todo:
        quick = [i for i in todo if i.get("effort") == "low"]
        parts.append(f'<section><h2>{html.escape(L.t("do_first", "What to do first"))}</h2>'
                     f'<p class="note">'
                     + html.escape(L.t("do_first_note",
                                       "Ordered by how much each matters against how much "
                                       "work it is — {quick} of the {total} are quick.")
                                   .format(quick=len(quick), total=len(todo)))
                     + "</p>" + "".join(_card(i, L) for i in todo) + "</section>")

    # -- Did the last round of work land? ----------------------------------------
    # The data was in `.seo-runs/` all along and reached a terminal at best. A
    # checklist is a thing people re-run, and a report that cannot say whether
    # anything improved makes the reader diff two PDFs by eye.
    base, diff = data.get("compared_with"), data.get("diff")
    if base and diff is not None:
        when = html.escape(str(base.get("started_at") or "?")[:16])
        then, cur = base.get("seo_score"), s.get("seo_score")
        head = [f'<section><h2>'
                f'{html.escape(L.t("since_last", "Since the previous audit"))}</h2>']
        if then is not None and cur is not None:
            arrow = "→" if cur == then else ("↑" if cur > then else "↓")
            tone = "pass" if cur > then else ("fail" if cur < then else "")
            head.append('<p class="note">'
                        + html.escape(L.t("since_scores",
                            "Compared with the run of {when}: score {then} {arrow} "
                            "{now}, over {w_then}% {arrow} {w_now}% of the weight "
                            "in scope.").format(
                                when=when, then=then, now=cur, arrow=arrow,
                                w_then=base.get("weight_pct"),
                                w_now=s.get("weight_pct")))
                        + f'</p><div class="metrics"><div class="metric {tone}">'
                        f'<b>{cur - then:+d}</b><span>'
                        + html.escape(L.t("m_score_move",
                                          "Score movement since that run"))
                        + '</span></div></div>')
        else:
            head.append('<p class="note">'
                        + html.escape(L.t("since_baseline",
                            "Compared with the run of {when}.").format(when=when))
                        + '</p>')
        if data.get("diff_note"):
            head.append(f'<p class="caveat">{html.escape(str(data["diff_note"]))}</p>')
        body = []
        for kind in ("improved", "regressed", "evidence"):
            rows = [c for c in diff if c.get("direction") == kind]
            if not rows:
                continue
            key, default = DIRECTION_HEADING[kind]
            nkey, ndefault = DIRECTION_NOTE[kind]
            cells = "".join(
                f'<tr><td>{c["id"]}</td>'
                f'<td>{html.escape(str(c.get("title", "")))}</td>'
                f'<td>{html.escape(c["from"])} → {html.escape(c["to"])}</td></tr>'
                for c in sorted(rows,
                                key=lambda r: SEVERITY_ORDER.get(r.get("severity"), 9)))
            body.append(
                f'<h3>{html.escape(L.t(key, default))} '
                f'<span class="count">{len(rows)}</span></h3>'
                f'<p class="note">{html.escape(L.t(nkey, ndefault))}</p>'
                f'<table><thead><tr><th>ID</th>'
                f'<th>{html.escape(L.t("item", "Item"))}</th>'
                f'<th>{html.escape(L.t("change", "Change"))}</th></tr></thead>'
                f'<tbody>{cells}</tbody></table>')
        if not diff:
            body.append('<p class="note">'
                        + html.escape(L.t("since_nothing", "No item changed status."))
                        + '</p>')
        parts.append("".join(head) + "".join(body) + "</section>")

    # -- The arc, and what has been open through all of it -----------------------
    history, streaks = data.get("history") or [], data.get("open_since") or []
    if len(history) >= 2 or streaks:
        block = [f'<section><h2>{html.escape(L.t("over_time", "Over time"))}</h2>']
        if len(history) >= 2:
            rows = "".join(
                f'<tr><td>{html.escape(str(r.get("started_at") or "")[:16])}'
                f'{" <b>(" + html.escape(L.t("this_run", "this run")) + ")</b>" if r.get("current") else ""}</td>'
                f'<td>{html.escape(str(r.get("mode") or "?"))}</td>'
                f'<td>{"&mdash;" if r.get("seo_score") is None else r["seo_score"]}</td>'
                f'<td>{r.get("weight_pct", "&mdash;")}%</td>'
                f'<td>{r.get("decided", "&mdash;")}</td></tr>' for r in history)
            block.append(
                f'<p class="note">{html.escape(L.t("trend_note", "Every audit of this domain that is still on disk, oldest first. The reach column matters as much as the score: a run that could decide less of the checklist is not a run that found less wrong."))}</p>'
                f'<table><thead><tr><th>{html.escape(L.t("when", "When"))}</th>'
                f'<th>{html.escape(L.t("mode", "Mode"))}</th>'
                f'<th>{html.escape(L.t("seo_score", "SEO Score"))}</th>'
                f'<th>{html.escape(L.t("reach", "Reach"))}</th>'
                f'<th>{html.escape(L.t("decided", "Decided"))}</th></tr></thead>'
                f'<tbody>{rows}</tbody></table>')
        if streaks:
            rows = "".join(
                f'<tr><td>{r["runs"]}</td>'
                f'<td>{html.escape(str(r.get("since") or "")[:10])}</td>'
                f'<td>{html.escape(L.sev(r["severity"]))}</td>'
                f'<td>{r["id"]}</td>'
                f'<td>{html.escape(L.title(r))}</td></tr>'
                for r in streaks[:OPEN_SINCE_SHOWN])
            more = ""
            if len(streaks) > OPEN_SINCE_SHOWN:
                more = ('<p class="note">' + html.escape(
                    L.t("open_since_more", "+{n} more open across several audits.")
                    .format(n=len(streaks) - OPEN_SINCE_SHOWN)) + "</p>")
            block.append(
                f'<p class="note">{html.escape(L.t("open_since_note", "Open in every audit since the date shown — counted as an unbroken run backwards from today, so an item that was fixed and broke again is not listed here as untouched."))}</p>'
                f'<table><thead><tr><th>{html.escape(L.t("audits", "Audits"))}</th>'
                f'<th>{html.escape(L.t("since", "Since"))}</th>'
                f'<th>{html.escape(L.t("severity", "Severity"))}</th><th>ID</th>'
                f'<th>{html.escape(L.t("item", "Item"))}</th></tr></thead>'
                f'<tbody>{rows}</tbody></table>{more}')
        parts.append("".join(block) + "</section>")

    # -- The addresses, not the counts -------------------------------------------
    # Above the folded machine layer, because "which URL" is what a reader does
    # something about. One crawl produced it; before that the report could only say
    # how many links were broken.
    crawl = data.get("crawl") or {}
    if crawl.get("broken") or crawl.get("redirected"):
        rows = []
        for row in (crawl.get("broken") or [])[:50]:
            where = (", ".join(row["linked_from"][:2]) if row.get("linked_from")
                     else L.t("sitemap_only", "the sitemap only"))
            status = row.get("status") or (row.get("error") or "no response")[:60]
            rows.append(f"<tr><td><code>{html.escape(row['url'])}</code></td>"
                        f"<td>{html.escape(str(status))}</td>"
                        f"<td>{html.escape(where)}</td></tr>")
        for row in (crawl.get("redirected") or [])[:50]:
            rows.append(f"<tr><td><code>{html.escape(row['url'])}</code></td>"
                        f"<td>→ {html.escape(row.get('to') or '')} "
                        f"({row.get('hops', 1)})</td>"
                        f"<td>{len(row.get('linked_from') or [])}</td></tr>")
        parts.append(
            f'<section><h2>'
            f'{html.escape(L.t("broken_urls", "Broken and redirecting URLs"))}</h2>'
            f'<p class="note">'
            + html.escape(L.t("broken_urls_note",
                              "From one crawl of the site, so these are addresses "
                              "rather than counts. Only URLs the crawl reached are "
                              "listed: {pages} page(s) checked.")
                          .format(pages=(crawl.get("summary") or {})
                                  .get("pages_fetched", "?")))
            + "</p><table><thead><tr><th>URL</th>"
            + f'<th>{html.escape(L.t("status", "Status"))}</th>'
            + f'<th>{html.escape(L.t("linked_from", "Linked from"))}</th></tr></thead>'
            + f'<tbody>{"".join(rows)}</tbody></table></section>')

    # -- Layer 4: the machine layer, folded --------------------------------------
    def fold(title: str, body: str, count: int) -> str:
        return (f'<details class="fold"><summary>{html.escape(title)} '
                f'<span class="count">{count}</span></summary>{body}</details>')

    manual = [i for i in data["items"] if i["status"] == MANUAL]
    if manual:
        rows = "".join(
            f'<div class="row" data-st="MANUAL"><div class="st MANUAL">{STATUS_ICON[MANUAL]}</div>'
            f'<div class="sev">{html.escape(L.sev(i["severity"]))}<br>{i["id"]}</div>'
            f'<div><div class="ttl"><label class="chk">'
            f'<input type="checkbox" data-id="{i["id"]}">'
            f'<span>{html.escape(L.title(i))}</span></label></div>'
            f'<div class="fix">{html.escape(L.fix(i))}</div></div></div>'
            for i in sorted(manual, key=lambda x: SEVERITY_ORDER.get(x["severity"], 9)))
        rows += (f'<div class="row"><div class="st"></div><div class="sev"></div>'
                 f'<div><button id="export-manual" type="button">'
                 f'{html.escape(L.t("export_manual", "Export ticked items as answers"))}'
                 f'</button> <span class="ev">'
                 + html.escape(L.t("export_manual_note",
                                   "Writes the ticked items as a --manual-answers "
                                   "file. A tick is a claim that the item passes and "
                                   "nothing more: it carries no reason, so add one "
                                   "per item before merging, and write any FAIL by "
                                   "hand. The run records these as claimed, never as "
                                   "measured."))
                 + '</span></div></div>')
        parts.append(fold(L.t("requires_human", "Needs a person"),
                          '<p class="note">'
                          + html.escape(L.t("manual_note",
                                            "These cannot be scripted. Nothing here counts "
                                            "against the score. Tick them off as you go — "
                                            "the ticks are remembered in this browser."))
                          + f"</p>{rows}", len(manual)))

    pending = [i for i in data["items"] if i["status"] == LLM_PENDING]
    if pending:
        rows = "".join(
            f'<div class="row" data-st="LLM_PENDING">'
            f'<div class="st LLM_PENDING">{STATUS_ICON[LLM_PENDING]}</div>'
            f'<div class="sev">{html.escape(L.sev(i["severity"]))}<br>{i["id"]}</div>'
            f'<div class="ttl">{html.escape(L.title(i))}</div></div>' for i in pending)
        parts.append(fold(L.t("awaiting_judgement", "Awaiting a reading of the page"),
                          '<p class="note">'
                          + html.escape(L.t("pending_note",
                                            "Questions no script can settle — wording, "
                                            "layout, intent. They lower coverage until "
                                            "someone answers them."))
                          + f"</p>{rows}", len(pending)))

    needs = [i for i in data["items"] if i["status"] == NEEDS_INPUT]
    if needs:
        rows = "".join(
            f'<div class="row" data-st="NEEDS_INPUT">'
            f'<div class="st NEEDS_INPUT">{STATUS_ICON[NEEDS_INPUT]}</div>'
            f'<div class="sev">{html.escape(L.sev(i["severity"]))}<br>{i["id"]}</div>'
            f'<div><div class="ttl">{html.escape(L.title(i))}</div>'
            f'<div class="ev">{html.escape(i.get("evidence", ""))}</div></div></div>'
            for i in sorted(needs, key=lambda x: SEVERITY_ORDER.get(x["severity"], 9)))
        parts.append(fold(L.t("needs_input", "What this audit was not given"),
                          '<p class="note">'
                          + html.escape(L.t("needs_input_note",
                                            "Each of these would have been decided if "
                                            "the run had been handed one more thing. "
                                            "They are work for whoever runs the audit, "
                                            "not for whoever owns the site, and the "
                                            "reason names the argument that fills it."))
                          + f"</p>{rows}", len(needs)))

    blocked = [i for i in data["items"] if i["status"] == NO_DATA]
    if blocked:
        rows = "".join(
            f'<div class="row" data-st="NO_DATA"><div class="st NO_DATA">{STATUS_ICON[NO_DATA]}</div>'
            f'<div class="sev">{html.escape(L.sev(i["severity"]))}<br>{i["id"]}</div>'
            f'<div><div class="ttl">{html.escape(L.title(i))}</div>'
            f'<div class="ev">{html.escape(i.get("evidence", ""))}</div></div></div>'
            for i in blocked)
        parts.append(fold(L.t("undetermined", "Could not be determined"),
                          '<p class="note">'
                          + html.escape(L.t("undetermined_note",
                                            "Checks that ran and could not reach a verdict. "
                                            "Each lowers coverage; none lowers the score. "
                                            "This list is the honest part of the audit."))
                          + f"</p>{rows}", len(blocked)))

    # Deliberately not a `row` with a `data-st`: the status filters below are a filter
    # over items, and an opportunity is not an item. Giving it a status class would put
    # it back inside the thing this section exists to keep it out of.
    opportunities = [o for o in (data.get("gsc_opportunities") or [])
                     if isinstance(o, dict) and o.get("finding")]
    if opportunities:
        phrased = [(o, *opportunity_phrase(o, L))
                   for o in opportunities[:OPPORTUNITY_LIMIT]]
        rows = "".join(
            f'<div class="row"><div class="sev">GSC</div>'
            f'<div><div class="ttl">{html.escape(str(o.get("query") or "—"))}</div>'
            f'<div class="ev">{html.escape(found)} '
            f'&middot; {html.escape(str(o.get("page") or ""))}<br>'
            f'{html.escape(fix)}</div></div></div>'
            for o, found, fix in phrased)
        parts.append(fold(
            L.t("opportunities", "Worth knowing: what Search Console suggests"),
            '<p class="note">'
            + html.escape(L.t("opportunities_note",
                              "Not defects, and deliberately not scored. Every line is a "
                              "query this site already ranks for, where Google's own "
                              "numbers say there is more to win — so there is nothing "
                              "here to fix and nothing here that failed. They are "
                              "outside the score, the item partition and the fix list, "
                              "because a good result graded as a failure is how a report "
                              "tells someone to repair their best page."))
            + f"</p>{rows}", len(opportunities)))

    by_cat: dict[str, list] = {}
    for i in data["items"]:
        by_cat.setdefault(i["category_label"], []).append(i)
    full = ['<div class="filters"><button data-f="ALL" aria-pressed="true">'
            + html.escape(L.t("all", "All")) + "</button>"]
    for st in (FAIL, WARN, PASS, NO_DATA, NEEDS_INPUT, LLM_PENDING, MANUAL, NA):
        if counts.get(st):
            full.append(f'<button data-f="{st}">{STATUS_ICON[st]} ({counts[st]})</button>')
    full.append("</div>")
    for label, items in by_cat.items():
        full.append(f"<h3>{html.escape(label)}</h3>")
        for i in sorted(items, key=lambda x: (x["status"] != FAIL,
                                              SEVERITY_ORDER.get(x["severity"], 9))):
            cls = i["status"].replace("/", "").replace(" ", "_")
            full.append(
                f'<div class="row" data-st="{i["status"]}">'
                f'<div class="st {cls}">{STATUS_ICON[i["status"]]}</div>'
                f'<div class="sev">{html.escape(L.sev(i["severity"]))}<br>{i["id"]}</div>'
                f'<div><div class="ttl">{html.escape(L.title(i))}</div>'
                f'<div class="ev">{html.escape(i.get("evidence", ""))}</div></div></div>')
    parts.append(fold(L.t("full_checklist", "Every check, with its raw evidence"),
                      "".join(full), s["total_items"]))

    parts.append(f'<p class="foot">{html.escape(L.t("foot", "Registry"))} '
                 f'<code>{html.escape(str(data.get("registry_version", "")))}</code>'
                 f' &middot; {s["total_items"]} '
                 + html.escape(L.t("items_word", "items")) + "</p></div>")

    return ('<!doctype html><html lang="' + html.escape(L.code or "en") + '"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>SEO &mdash; {html.escape(data.get("domain", ""))}</title>'
            f"<style>{CSS}</style></head>"
            f'<body data-domain="{html.escape(data.get("domain", ""))}">'
            + "".join(parts) + f"<script>{JS}</script></body></html>")


# ---------------------------------------------------------------------------

def merge_llm_answers(data: dict, answers: dict) -> int:
    """Fold LLM verdicts into the results and rescore. Only LLM_PENDING items
    may be overwritten — an answer file must not be able to flip a verdict a
    script already established."""
    valid = {PASS, FAIL, WARN, NA}
    applied = 0
    for item in data["items"]:
        a = answers.get(item["id"])
        if not a:
            continue
        if item["status"] != LLM_PENDING:
            print(f"  ignoring {item['id']}: it is {item['status']}, and only "
                  f"{LLM_PENDING} items can be answered here", file=sys.stderr)
            continue
        st = str(a.get("status", "")).upper()
        if st not in valid:
            print(f"  skipping {item['id']}: invalid status {a.get('status')!r}", file=sys.stderr)
            continue
        item["status"] = st
        item["evidence"] = f"LLM: {str(a.get('evidence') or '').strip() or 'no rationale given'}"
        item["source"] = "llm(answered)"
        item["decided_by"] = "model"
        applied += 1
    if applied:
        data["scores"] = load_scoring()(data["items"])
    return applied


def merge_manual_answers(data: dict, answers: dict) -> int:
    """Fold a person's answers into the results and rescore.

    The mirror of `merge_llm_answers`, and deliberately built to the same shape:
    only `MANUAL` items may be overwritten, so this file cannot flip a verdict a
    script established any more than an LLM answer file can. Thirty-four items —
    16% of the registry — were unanswerable by anything before this, not because
    nobody knew the answer but because there was no way to hand one back.

    Two guards, and they are the point rather than paperwork.

    **Evidence is required.** An LLM answer without a rationale degrades to "no
    rationale given" and the reader can weigh it; a human `PASS` with nothing beside
    it is indistinguishable from a tick made to clear the list, and thirty-four of
    those would move the score with no way to argue. An answer that says nothing is
    refused with its id.

    **The verdict is stamped `claimed`.** It is not a measurement and the report
    must never present it as one — see the provenance line in the summary. This is
    the same asymmetry the adversary reviewer runs on: what a second reader may do
    to a verdict is bounded by what that reader actually saw.
    """
    valid = {PASS, FAIL, WARN, NA}
    applied = 0
    for item in data["items"]:
        a = answers.get(item["id"])
        if not a:
            continue
        if item["status"] != MANUAL:
            print(f"  ignoring {item['id']}: it is {item['status']}, and only "
                  f"{MANUAL} items can be answered here", file=sys.stderr)
            continue
        st = str(a.get("status", "")).upper()
        if st not in valid:
            print(f"  skipping {item['id']}: invalid status {a.get('status')!r}",
                  file=sys.stderr)
            continue
        why = str(a.get("evidence") or "").strip()
        if not why:
            print(f"  skipping {item['id']}: a claimed verdict needs a reason beside "
                  f"it, and this one has none", file=sys.stderr)
            continue
        item["status"] = st
        item["evidence"] = f"answered by a person: {why}"
        item["source"] = "manual(answered)"
        item["decided_by"] = "claimed"
        applied += 1
    if applied:
        data["scores"] = load_scoring()(data["items"])
    return applied


def apply_llm_review(data: dict, review: dict) -> dict:
    """Fold a second, independent judgement into answers the first pass produced.

    Thirty-eight items rest on one language model's reading of one page, unopposed. A
    second reader cannot make those verdicts more accurate on its own — but it can
    say when they are not reliable, and that is the part the score has no way to
    express otherwise.

    Agreement corroborates: the verdict stands and says it was checked twice.
    Disagreement does **not** pick a winner and does not average them. Two
    competent readings that conflict mean the page did not settle the question, so
    the item goes back to NO_DATA carrying both opinions. The reviewer therefore
    has a veto over confidence and no vote on the answer — which is deliberate: a
    reviewer that could overwrite a verdict is just a second first pass, and one
    that could only agree is decoration.

    Returns counts, so the caller can report what the second pass actually did.
    """
    valid = {PASS, FAIL, WARN, NA}
    stats = {"corroborated": 0, "contested": 0, "skipped": 0}
    for item in data["items"]:
        second = review.get(item["id"])
        if not second:
            continue
        verdict = str(second.get("status", "")).upper()
        if verdict not in valid:
            print(f"  review of {item['id']}: invalid status "
                  f"{second.get('status')!r}", file=sys.stderr)
            stats["skipped"] += 1
            continue
        # Only an answered LLM item can be reviewed. A script's verdict is not up
        # for discussion, and an item the first pass never answered would make the
        # reviewer the primary judge without anyone deciding that.
        if item.get("source") != "llm(answered)":
            print(f"  review of {item['id']}: not an answered LLM item "
                  f"({item.get('source')}, {item['status']}) — ignored",
                  file=sys.stderr)
            stats["skipped"] += 1
            continue

        note = str(second.get("evidence", "")).strip() or "no rationale given"
        if verdict == item["status"]:
            item["corroborated"] = True
            item["evidence"] = f"{item['evidence']} | second reading agrees: {note}"
            stats["corroborated"] += 1
        else:
            item["contested"] = {"first": item["status"], "second": verdict}
            item["evidence"] = (f"contested: first reading said {item['status']} "
                                f"({item['evidence']}); second said {verdict} "
                                f"({note})")
            item["status"] = NO_DATA
            item.pop("decided_by", None)
            item["source"] = "llm(contested)"
            stats["contested"] += 1
    if stats["contested"]:
        data["scores"] = load_scoring()(data["items"])
    return stats


def write(path: str, text: str) -> str:
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return os.path.abspath(path)


def main() -> int:
    ap = argparse.ArgumentParser(description="Render checklist audit deliverables")
    ap.add_argument("results", help="checklist-results.json from checklist_runner.py")
    ap.add_argument("--markdown", default="CHECKLIST-REPORT.md")
    ap.add_argument("--html", default="CHECKLIST.html")
    ap.add_argument("--llm-queue", default="LLM-QUEUE.md")
    ap.add_argument("--llm-answers", default="", help="JSON of LLM verdicts to merge back")
    ap.add_argument("--manual-answers", default="", metavar="PATH",
                    help="JSON of verdicts a person reached, {id: {status, "
                         "evidence}}. Merges into MANUAL items only, and each needs "
                         "a reason — a claimed verdict with nothing beside it is "
                         "refused. Export a starting file from the HTML report's "
                         "'Needs a person' section.")
    ap.add_argument("--llm-review", default="",
                    help="JSON of a second, independent judgement over the same "
                         "items. Agreement corroborates the verdict; disagreement "
                         "returns the item to NO_DATA carrying both readings. The "
                         "reviewer cannot overwrite a verdict or answer an "
                         "unanswered item.")
    ap.add_argument("--fixes", default="",
                    help="write just the actionable items — id, severity, effort, "
                         "priority, what to do — to this path. `.json` gives JSON, "
                         "anything else CSV. For a tracker, so nobody has to parse "
                         "the report or filter the full audit log by hand.")
    ap.add_argument("--no-html", action="store_true")
    ap.add_argument("--lang", default="en",
                    help="language for the report chrome (en, ru); item titles "
                         "stay in the registry's wording unless translated")
    a = ap.parse_args()

    with open(a.results, encoding="utf-8") as f:
        data = json.load(f)

    if a.llm_answers:
        with open(a.llm_answers, encoding="utf-8") as f:
            answers = json.load(f)
        n = merge_llm_answers(data, answers)
        with open(a.results, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"Merged {n} LLM verdict(s) into {a.results}")

    if a.manual_answers:
        with open(a.manual_answers, encoding="utf-8") as f:
            answered = json.load(f)
        n = merge_manual_answers(data, answered)
        with open(a.results, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"Merged {n} answer(s) from a person into {a.results}; "
              f"each is recorded as claimed rather than measured")

    if a.llm_review:
        with open(a.llm_review, encoding="utf-8") as f:
            review = json.load(f)
        stats = apply_llm_review(data, review)
        with open(a.results, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"Second reading: {stats['corroborated']} corroborated, "
              f"{stats['contested']} contested (back to NO_DATA), "
              f"{stats['skipped']} ignored")
        if stats["contested"]:
            print("  Coverage drops by the contested items, and it should: two "
                  "readings that disagree did not settle the question.")

    try:
        lang = Lang(a.lang)
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 2
    gaps = lang.untranslated()
    if gaps:
        print(f"--lang {lang.code}: {' and '.join(gaps)} are not translated yet and "
              f"will appear in English. The report is English-only for client "
              f"delivery until they are filled in.", file=sys.stderr)
    written = [("Report", write(a.markdown, render_markdown(data, lang)))]
    if not a.no_html:
        written.append(("HTML", write(a.html, render_html(data, lang))))
    if a.fixes:
        rows = fix_rows(data)
        written.append((f"Fix list ({len(rows)})", write_fixes(a.fixes, data)))

    pending_items = [i for i in data["items"] if i["status"] == LLM_PENDING]
    pending = len(pending_items)
    if pending:
        written.append(("LLM queue", write(a.llm_queue, render_llm_queue(data))))
        # One file per lens, so each agent gets exactly its own slice. Items with
        # no lens (a registry written before lenses existed) stay in the combined
        # queue rather than being dropped from the split.
        stem = a.llm_queue[:-3] if a.llm_queue.endswith(".md") else a.llm_queue
        for lens in sorted({i.get("lens") for i in pending_items if i.get("lens")}):
            agent = LENS_AGENTS.get(lens, ("?", ""))[0]
            written.append((f"  -> {agent}",
                            write(f"{stem}-{lens}.md", render_llm_queue(data, lens))))
        stray = [i["id"] for i in pending_items if not i.get("lens")]
        if stray:
            print(f"No lens for {', '.join(stray)} — only in the combined queue",
                  file=sys.stderr)

    s = data["scores"]
    p = s["partition"]
    if s.get("seo_score") is None:
        print(f"\nNo SEO Score: {data.get('entry_error') or 'the site could not be read'}"
              f"\n{s['decided']}/{s['total_items']} items decided")
    else:
        print(f"\nSEO Score {s['seo_score']}/100 — over {s['decided']} items, "
              f"{s['weight_pct']}% of the weight in scope")
    by = s.get("decided_by") or {}
    if set(by) - {"measured"}:
        print("  of the decided: "
              + ", ".join(f"{n} {kind}" for kind, n in sorted(by.items())))
    print(f"  decided {p['decided']} · waiting on you {p['waiting_on_you']} · "
          f"needs a person {p['needs_a_person']} · undecided {p['undecided']}"
          + (f" · N/A {p['not_applicable']}" if p["not_applicable"] else ""))
    for line in provenance_warnings(data, lang):
        print(f"  ! {line}")
    for label, path in written:
        print(f"  {label}: {path}")
    if pending:
        print(f"\n{pending} item(s) still need an LLM verdict — answer LLM-QUEUE.md, "
              f"then rerun with --llm-answers")
    return 0


if __name__ == "__main__":
    sys.exit(main())
