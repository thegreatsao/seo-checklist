#!/usr/bin/env python3
"""Does each item assert what its title says, and does any pair assert the same thing?

Two questions the registry has never been asked, both found by one live audit in
0.20 and neither catchable by the fixture pair — the good fixture is *built* to
satisfy the registry, so an item that accuses every real site passes on it as long
as somebody tuned the fixture for that item. `tests/fixtures/good/robots.txt`
disallows exactly the four paths CI-019 tests, with a comment saying so.

1. DUPLICATES are mechanical and exact: two items sharing script, args and
   assertion are one check scored twice. CI-016/MD-186 do, both `high`, so one
   image missing an `alt` produced two high FAILs on a real site — double weight in
   the headline and two rows in --fixes.

2. VOCABULARY is a heuristic and says so. It compares the words in what an item
   *claims* (title + fix text) against the words in what it *does* (script name +
   assertion path). No overlap is not proof of a defect — plenty of correct items
   name a field nothing in their prose could mention. It is a reading list, and
   REVIEWED below is where a human's answer goes so the list does not have to be
   re-read every run.

Exit 1 on any duplicate, or on an unreviewed vocabulary miss. Reviewing an item is
writing down which of the three is wrong, or that none of them is.

The summary also lists REVIEWED rulings whose items no longer fire the vocabulary
heuristic. That list is informational, never a gate: a ruling normally becomes inert
because its item was repaired, and keeping the history lets later editors see why.

Neither question is about POLARITY, and this tool does not answer it. A title phrased
as the failure state rather than the desired one — GEO-008 in 0.32.0, caught by hand —
shares its assertion's vocabulary perfectly and inverts what a PASS means. The
heuristic for it was measured and rejected: 23 of 217 titles fire and all 23 are
correct, only 34.4% of items assert a bounded path it could read at all, and inside
that it catches only failure-state titles reusing the assertion's own word. See
KNOWN-ISSUES §6 for the numbers. A title's side of its subject is read by a person.
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

REGISTRY = Path(__file__).resolve().parent.parent / "resources/config/checklist.json"

# Words that carry no discriminating meaning in either half of the comparison.
STOP = {
    "a", "an", "and", "are", "as", "at", "be", "by", "check", "checks", "do", "does",
    "for", "from", "has", "have", "in", "is", "it", "not", "of", "on", "or", "own",
    "py", "review", "run", "set", "site", "the", "them", "then", "there", "to", "up",
    "use", "used", "using", "via", "want", "was", "with", "your", "avoid", "ensure",
    "keep", "make", "provide", "raw", "summary", "value", "values", "len", "count",
    "counts", "total", "all", "any", "each", "every", "no", "none", "one", "only",
}

# A vocabulary miss that a human has read and ruled on. The value is the ruling —
# what is wrong, or why nothing is. An id here is not silenced, it is answered.
REVIEWED: dict[str, str] = {
    "CI-019": "DEFECT (0.20). Title and fix say noindex; the assertion tests robots.txt "
              "allow/deny, and the script never fetches the path so a 404 counts as "
              "exposed. Two repairs: existence, and decide which check this is.",
    "CN-053": "DEFECT (0.20). Title and fix are about iframes; the assertion counts "
              "words (raw.word_count >= 300). Nothing in the item observes an iframe.",
    "TE-179": "FIXED (0.44). The 0.21 objection was right that age is not reputation "
              "and that waiting is not a fix. The repaired group makes that distinction: "
              "SE-114, SE-116 and TE-171 assert reputation, while TE-179 measures the "
              "otherwise-uncovered history half as whois.age_days >= 90. A younger "
              "domain warns but can never fail, and an absent age remains NO_DATA.",
    "MB-104": "FIXED (0.44). The title promised a favicon that displays in a mobile "
              "result and the assertion only asked whether a <link rel=icon> existed. "
              "It now fetches the icon and measures it.",
    "GO-134": "FIXED (0.23). A defect from 0.20: 'Resolve Search Console issues' read "
              "`opportunities` through a severity gate, so position 4.0 with 115 "
              "impressions printed as a high failure. An opportunity is not a defect at "
              "any threshold, so it asserts on `issues` instead — errors and warnings "
              "against a submitted sitemap, the only thing the API reports as broken. "
              "The opportunities are reported outside the score and the fix list.",

    # --- Ruled in 0.22, the pass that emptied the unreviewed list -------------
    # Read in one sitting against the registry and each script's output shape. Most
    # are the heuristic doing its job badly rather than the registry doing its job
    # wrongly: `text_nodes_below_12px` really is font size, `overlays_covering_content`
    # really is an intrusive interstitial, and no token-overlap test will ever know
    # that. Those are marked OK. Four are not.

    "CI-002": "FIXED (0.26 evidence, 0.34 title). Was a defect: asserted "
              "summary.urls >= 1, so a sitemap "
              "listing one URL passed a site of five hundred pages, and being in a "
              "sitemap is not being indexed — the floor it checked (a sitemap exists "
              "and is not empty) is GO-136's. It now asserts `indexed` from URL "
              "Inspection, Google's own answer, and its title is now a declared override "
              "that promises only the audited URL. `requires: gsc` keeps the item out "
              "of the sampled-page pass, so one inspection is the whole answer. "
              "Important-URL inspection remains open work — quota policy, selection "
              "and aggregation — rather than a hidden limitation. Not a duplicate of "
              "GO-135 (`issues`, which also covers "
              "robots blocks, fetch failures and canonical conflicts) nor of CI-010 "
              "(`canonical_match`) — a page can be indexed with issues, or unindexed "
              "with a matching canonical, and both are pinned in the 0.26 tests.",
    "SP-111": "FIXED (0.25). Was a defect: titled 'Check Core Web Vitals (Desktop) in "
              "Search Console' and asserted performance_score >= 90, the blended "
              "Lighthouse score, which mixes TBT and Speed Index and is not Core Web "
              "Vitals. It now reads `field_cwv.verdict` with --strategy desktop — CrUX "
              "split by device, which is what Search Console's report shows. Desktop "
              "field data had no item asserting it before, so this is not a duplicate.",
    "SP-112": "FIXED (0.25). The same defect as SP-111 with --strategy mobile, and the "
              "objection to repairing it was right: reading `field_cwv.verdict` makes it "
              "identical to SP-108 in script, args and assertion. That is what "
              "`scores_with` is for — it is declared a twin of SP-108 in SAME_CHECK, "
              "runs once, scores once, and keeps its own title and status. "
              "Reopened in 0.45 as a batch C candidate — 'in Search Console' while "
              "reading PageSpeed reads like a title/evidence mismatch — and closed "
              "again with no code change. The Search Console API exposes search "
              "analytics, sitemaps and URL inspection and has no Core Web Vitals path "
              "at all, so there is no other source to point the item at; the report "
              "Search Console does show is built on CrUX, which is exactly what "
              "`field_cwv` reads. The title names where a site owner sees these "
              "numbers, not where the plugin fetches them.",
    "SP-113": "FIXED (0.25). Titled 'Meet Core Web Vitals Thresholds' (critical) with a "
              "fix text naming all three thresholds, it asserted metrics.LCP.rating — "
              "one metric — so a page failing CLS passed it. Worse, `metrics` carries "
              "CrUX when field data exists and Lighthouse lab audits when it does not, "
              "so the item silently switched data source and awarded a critical PASS on "
              "a lab number for every site CrUX has no sample for. Now `field_cwv."
              "verdict`, a twin of SP-108.",
    "IN-127": "FIXED (0.26; mixed-set false PASS fixed in 0.33). Was a defect: "
              "asserted checks.protocol_consistency.passed "
              "— whether the hreflang set mixes http and https — which is worth "
              "checking and is not URL structure, so a site with every locale on "
              "`?lang=` passed. It now asserts checks.url_structure.passed, which reads "
              "each alternate against its own hreflang code and answers ccTLD, "
              "subdomain, subdirectory, parameter, mixed, single or unmarked. Parameter "
              "and mixed carry `passed: False`; mixed names the conflicting URLs. Only "
              "single and wholly unmarked sets carry no `passed` key, so they are "
              "NO_DATA rather than credited with a structure. Protocol "
              "consistency is still computed and still counted in the severity tally; "
              "no item asserts it now.",

    "CI-015": "OK. rows.0.status < 500 is exactly '5xx server errors', spelled in "
              "numbers instead of words.",
    "MS-021": "OK. title len_gte 30 is the '<30 characters' in the title, as a rule.",
    "CN-034": "OK. text_nodes_below_12px == 0 is 'readable font sizes' measured.",
    "CN-038": "OK on the measurement, and 'balance' is aspiration rather than a "
              "second requirement: freshness score is the only part of it a number "
              "can carry.",
    "CN-044": "OK, weakly. trust_links includes a contact link and also privacy and "
              "terms, so a site with a privacy page and no contact page passes. Worth "
              "a narrower signal one day; not a mismatch between title and assertion.",
    "CN-051": "OK. overlays_covering_content == 0 is an intrusive interstitial, "
              "measured on the rendered page, which is the only place it exists.",
    "KW-071": "OK. Cannibalisation is keyword duplication seen from the SERP side, "
              "and contested_queries counts queries whose URLs compete in the same "
              "close position band.",
    "MB-093": "OK, weakly, and it is `critical`. A viewport meta tag is necessary for "
              "a responsive layout and nowhere near sufficient — a fixed-width page "
              "with the tag passes. The full check needs rendering at two widths.",
    "MB-098": "OK. The pattern counts size and dimension issues, which is the title.",
    "MB-105": "SUPERSEDED (0.72). The ruling this replaces read `diffs` is the "
              "parity between raw and rendered, which is the item — true about "
              "the script and silent about the title, which said Match Desktop. "
              "Saying the assertion matched the item is exactly what let that "
              "mismatch stand, and it stood for as long as the ruling did. The item "
              "is now titled for what it compares and needs no excuse. Kept rather "
              "than deleted, on TE-177's precedent and for TE-177's reason.",
    "SP-107": "OK. FCP is when above-the-fold content appears; the title says so in "
              "English and the assertion says so in an acronym.",
    "SE-116": "OK. An empty safe_browsing.threats list is no hacked content or "
              "malware, as graded by the service that grades it.",
    "IN-128": "OK. hreflang self-reference is the mechanism by which the correct "
              "localised page is served; without it the set does not resolve.",
    "GO-131": "OK. A measurement id present is GA4 installed.",
    "GO-143": "OK as of 0.89.0, and the 0.22 ruling it replaces was wrong twice in "
              "one sentence. It read: sitelinks and the sitelinks search box are "
              "driven by WebSite and SearchAction markup. Sitelinks are algorithmic "
              "and no markup produces them; the search box did rest on that markup "
              "and Google removed it from Search on 21 November 2024. The title now "
              "names the live feature the assertion actually measures — the WebSite "
              "node Google reads for the site name — and `name` and `url` are what "
              "its documentation requires of that node.",
    "AR-153": "OK. topical_cluster_mapper's score is the silo structure, scored.",
    "AR-154": "OK. collection_page_checker is written for category pages.",
    "TE-172": "OK. rich_results_guard's errors are structured data implemented wrongly.",
    "TE-175": "OK on subject. The threshold is another matter — 'at most 3 missing "
              "headers' is a number nobody measured, which is KNOWN-ISSUES §2 and not "
              "this tool's question.",
    "TE-177": "SUPERSEDED (0.53). The 0.22 ruling above read `raw.title` as 'the page "
              "is readable without JavaScript', and that is more than a non-empty "
              "title element proves — a page can carry a title and build every word "
              "of its content in script. The item is now titled for what it asserts, "
              "a title element in the served HTML, and the comparison the old title "
              "implied is MB-105's. Kept rather than deleted because the ruling that "
              "went inert is the one that let the mismatch stand.",
    "TE-180": "OK. a11y_seo_checker's score is WCAG basics, scored.",
    "MD-185": "OK. Image issues at medium and above is 'optimize images'.",
    "GEO-007": "OK. key_valid is IndexNow configured; there is nothing else to be.",
    "TECH-001": "OK, weakly. `summary.warnings` is broader than retired schema types "
                "— any warning fails an item whose title is about HowTo and FAQ "
                "specifically. Real but minor, and narrowing it needs the guard to "
                "classify its own warnings first.",
}


# Suffixes stripped before comparing, longest first. Without this the heuristic
# reported `indexability_matrix.py` as sharing no vocabulary with "Ensure URL Is
# Indexed" — the two words differ by four letters and mean the same thing. Crude on
# purpose: a real stemmer is a dependency, and every pair this needs to catch is a
# regular English plural or participle.
_SUFFIXES = ("ability", "ibility", "ations", "ation", "ising", "izing", "ised",
             "ized", "ing", "ies", "ed", "es", "s")


def _stem(word: str) -> str:
    for suffix in _SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[:-len(suffix)]
    return word


def tokens(text: str) -> set[str]:
    """Words, with snake_case and dotted paths split and camelCase broken up.

    `len > 2` would drop `h1`, `h2` and `ga4`, which are the entire subject of the
    items that name them — and dropping them from the *assertion* side left those
    items with an empty vocabulary, so they could not share a word with anything and
    were flagged no matter what they asserted. A short token carrying a digit is an
    identifier, not noise, and is kept.
    """
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text or "")
    out = set()
    for word in re.split(r"[^a-zA-Z0-9]+", text.lower()):
        if word in STOP:
            continue
        if len(word) > 2 or (len(word) == 2 and any(c.isdigit() for c in word)):
            out.add(_stem(word))
    return out


def assertion_paths(rule: object) -> list[str]:
    """Every `path` in an assertion, including inside any/all branches."""
    found = []
    if isinstance(rule, dict):
        if isinstance(rule.get("path"), str):
            found.append(rule["path"])
        # A `field` names the part of the payload actually read, and a `value_map`'s
        # keys are the script's own vocabulary for the verdict — `indexable`,
        # `not_indexable`. Both are what the item asserts about; leaving them out
        # judged an assertion by its container instead of its content.
        if isinstance(rule.get("field"), str):
            found.append(rule["field"])
        if isinstance(rule.get("value_map"), dict):
            found.extend(k for k in rule["value_map"] if isinstance(k, str))
        # And an `eq` against an object literal, for the same reason. That shape is
        # how this registry expresses a title joining two conditions with "and" —
        # AR-158's `{"schema": true, "ui": true}`, CN-057's `{"author": true,
        # "publisher": true}` — so the object's keys are the conditions the item
        # asserts, and reading only the path judged the assertion by its container.
        # CN-057 named both halves of its title in those keys and was reported as
        # asserting nothing its title mentions.
        if isinstance(rule.get("eq"), dict):
            found.extend(k for k in rule["eq"] if isinstance(k, str))
        for value in rule.values():
            found.extend(assertion_paths(value))
    elif isinstance(rule, list):
        for value in rule:
            found.extend(assertion_paths(value))
    return found


def main() -> int:
    items = json.loads(REGISTRY.read_text())["items"]
    failures = []

    # 1. Duplicates — exact, no judgement involved.
    by_shape = defaultdict(list)
    for item in items:
        check = item.get("check") or {}
        if not check.get("script"):
            continue
        shape = (check["script"],
                 json.dumps(check.get("args"), sort_keys=True),
                 json.dumps(check.get("assert"), sort_keys=True))
        by_shape[shape].append(item)

    print("== items sharing script, args and assertion ==")
    duplicates = {shape: group for shape, group in by_shape.items() if len(group) > 1}
    if not duplicates:
        print("  none")
    for shape, group in sorted(duplicates.items(), key=lambda kv: kv[1][0]["id"]):
        ids = ", ".join(f"{i['id']} ({i['severity']})" for i in group)
        # A group is answered when exactly one member carries the weight and every
        # other points at it. That is a human decision recorded in SAME_CHECK, not a
        # silencing: the twins still run and still report. What is still a failure is
        # a group nobody has ruled on, or one where the pointers disagree about which
        # item survives — two items each deferring to the other would score neither.
        carriers = [i for i in group if not i.get("scores_with")]
        targets = {i["scores_with"] for i in group if i.get("scores_with")}
        declared = len(carriers) == 1 and targets <= {carriers[0]["id"]}
        print(f"  {'[paired]' if declared else '[UNRULED]'} {ids}")
        print(f"      {shape[0]} {shape[1]}  assert {shape[2]}")
        for item in group:
            twin = f"  -> scores with {item['scores_with']}" if item.get("scores_with") else ""
            print(f"      {item['id']}: {item['title']}{twin}")
        if not declared:
            failures.append(f"{ids} are one check scored {len(group)} times")

    # 2. Vocabulary — a heuristic, and the output is a reading list.
    print("\n== items whose assertion shares no vocabulary with their own title ==")
    unreviewed = []
    firing = set()
    for item in items:
        check = item.get("check") or {}
        paths = assertion_paths(check.get("assert"))
        if not check.get("script") or not paths:
            continue
        claims = tokens(item["title"]) | tokens(item.get("fix", ""))
        does = tokens(check["script"]) | {t for p in paths for t in tokens(p)}
        if claims & does:
            continue
        firing.add(item["id"])
        ruling = REVIEWED.get(item["id"])
        mark = "reviewed" if ruling else "UNREVIEWED"
        print(f"  [{mark}] {item['id']} ({item['severity']}) {item['title']}")
        print(f"      {check['script']} asserts {', '.join(sorted(set(paths)))}")
        if ruling:
            print(f"      -> {ruling}")
        else:
            unreviewed.append(item["id"])

    for item_id in unreviewed:
        failures.append(f"{item_id} asserts nothing its title mentions and nobody has ruled on it")

    inert_rulings = sorted(set(REVIEWED) - firing)
    print(f"\nInformational: {len(inert_rulings)} REVIEWED ruling(s) no longer fire: "
          f"{', '.join(inert_rulings) if inert_rulings else 'none'}")

    total = len(items)
    print(f"\n{total} items · {len(duplicates)} duplicate group(s) · "
          f"{len(REVIEWED)} reviewed · {len(unreviewed)} unreviewed")

    if failures:
        print("\nFAIL")
        for line in failures:
            print(f"  - {line}")
        return 1
    print("\nOK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
