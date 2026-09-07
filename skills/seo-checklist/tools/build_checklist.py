#!/usr/bin/env python3
"""Generate resources/config/checklist.json — the checklist registry.

The registry is the single source of truth for audit coverage: every item
names who answers it (a bundled script, the LLM, Search Console, or a human)
and, for script-backed items, a declarative assert rule.

Assert rules are written against real script output captured in
resources/references/script-output-shapes.md. Regenerate that file with
tools/probe_shapes.py before changing rules here.

Usage:
    python3 tools/build_checklist.py [--out PATH] [--check]

--check exits non-zero if the generated registry differs from the one on
disk, so CI can catch a stale checklist.json.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
# The runner's own definition, imported rather than restated: the gate below and the
# rule the runner applies at grading time have to be the same set, or an item can owe a
# declaration to one and not the other.
sys.path.insert(0, os.path.join(SKILL_DIR, "scripts"))
from checklist_runner import passes_by_absence  # noqa: E402

DEFAULT_OUT = os.path.join(SKILL_DIR, "resources", "config", "checklist.json")
TITLE_OVERRIDES = os.path.join(
    SKILL_DIR, "resources", "config", "title-overrides.json")

# --------------------------------------------------------------------------
# Categories — mirror the 15 Plerdy sections, id-prefixed for stable item ids.
# --------------------------------------------------------------------------

CATEGORIES = [
    ("crawling_indexing", "CI", "Crawling & Indexing", (1, 19)),
    ("meta_structured", "MS", "Meta & Structured Data", (20, 33)),
    ("content", "CN", "Content", (34, 68)),
    ("keywords", "KW", "Keyword Analysis", (69, 77)),
    ("backlinks", "BL", "Backlinks", (78, 92)),
    ("mobile", "MB", "Mobile", (93, 106)),
    ("speed", "SP", "Speed", (107, 113)),
    ("security", "SE", "Security", (114, 120)),
    ("international", "IN", "International & Multilingual", (121, 130)),
    ("google", "GO", "Google", (131, 145)),
    ("architecture", "AR", "Website Architecture", (146, 164)),
    ("technical", "TE", "Technical SEO Checks", (165, 183)),
    ("media", "MD", "Images / Video", (184, 190)),
    ("competition", "CO", "Competition Analysis", (191, 195)),
    ("local", "LO", "Local SEO", (196, 200)),
]

# --------------------------------------------------------------------------
# Assert vocabulary (interpreted by checklist_runner.py):
#   eq / ne / gt / gte / lt / lte      scalar comparison
#   truthy / falsy                     boolean-ish
#   len_eq / len_gte / len_lte         length of list or string
#   len_between: [lo, hi]              inclusive length range
#   between: [lo, hi]                  inclusive numeric range
#   matches: "regex"                   regex search on str(value)
#   contains: "substr"                 substring / list membership
#   none_severity: ["critical","high"] no issues[] entry at those severities
#   none_matching: "regex"             no issues[] entry whose message matches
#     + field: "finding"               match that field only, not the whole entry
#   count_matching_lte: ["regex", n]   at most n matching issues
#   value_map: {value: pass|fail}      enumerate the script's own vocabulary for
#                                      a field; an unlisted value is NO_DATA.
#                                      Optional "field" projects a list of dicts.
# A pattern may not decide a verdict from a human-readable message at all —
# `openspec/specs/verdicts/` VRD-8, held by
# `tests/test_registry.py::AVerdictComesFromAFieldAndNeverFromASentence`. Wording is
# the first thing that drifts, and `none_matching` passes when nothing matches, so a
# pattern aimed at wording a script no longer emits passes every site in silence:
# fifteen assertions here were in that state and four survived to 0.93.0. Use a
# counted field or `value_map`. Run tools/audit_assertions.py after touching one; a
# test runs it too.
# `path` uses dots; `[]` is not needed — lists are handled by len_*/none_*.
# Optional "warn" block uses the same vocabulary; it is evaluated only when
# the main assert fails, turning FAIL into WARN.
# Optional "applies_when" uses that vocabulary against the same script output. A
# false condition is N/A rather than a PASS awarded for an empty result set.
# --------------------------------------------------------------------------

S = "script"
L = "llm"
G = "gsc"
M = "manual"


# Most evidence scripts came from upstream and report through `seo_common.issue()`,
# whose callers say error/warning/info; the registry speaks critical/high/medium/
# low. `checklist_runner.SEVERITY_ALIAS` maps the first onto the second (error ->
# high, warning -> medium, info -> low) so a rule only has to know one vocabulary.
# Before that mapping existed, thirteen items asked for critical/high over scripts
# that never say either word, and every one of them reported PASS on every site
# ever audited — the §4.12 failure in a family the pattern audit did not cover.
#
# These two helpers are the shape almost every issues[] rule wants: an
# error-class finding fails the item, a warning-class one only warns, and info is
# informational. Passing ISSUES_ANY() without the matching warn= turns a warning
# into a FAIL, which is a decision, not a default — say why if you make it.
def ISSUES_ANY(path="issues"):
    return {"path": path, "none_severity": ["critical", "high", "medium"]}


def NOTHING_SERIOUS(path="issues"):
    return {"path": path, "none_severity": ["critical", "high"]}


# pagespeed.py merged CrUX's FAST/AVERAGE/SLOW and Lighthouse's
# good/needs-improvement/poor into one `rating` field, so `eq: "fast"` could only
# be satisfied by field data — and CrUX has none for a low-traffic URL. A page with
# a perfect Lighthouse LCP was rated `good`, the rule wanted `fast`, and two
# critical items reported FAIL on a fast page. The script speaks one vocabulary
# now; these map it, so a band nobody enumerated is NO_DATA instead of a verdict.
def RATING(metric):
    return {"path": f"metrics.{metric}.rating",
            "value_map": {"good": "pass", "needs-improvement": "fail",
                          "poor": "fail"}}


def RATING_WARN(metric):
    return {"path": f"metrics.{metric}.rating",
            "value_map": {"good": "pass", "needs-improvement": "pass",
                          "poor": "fail"}}


PAGE = ["{url}"]
# A rendered artifact is a statement about one URL, so an item that reads it
# cannot be sampled across pages; items that read only the served document must
# use PAGE so the runner can sample them. html_validator.py is the precedent:
# CI-017 uses PAGE while TE-181 receives the rendered artifact.
JSRENDER = ["{url}", "--rendered-json", "{rendered_json}"]
HTMLARG = ["{html}", "--url", "{url}"]
# The site-wide checks read one crawl instead of running six of their own.
# `{inventory_json}` is produced by the runner before the plan is built (see
# `checklist_runner.main`), so unlike the browser artifacts nobody has to supply it —
# but it can be missing for the same reasons any input can, and then these items are
# NO_DATA carrying the crawl's own reason rather than a verdict about a site nothing
# read.
CRAWLARG = ["{url}", "--inventory", "{inventory_json}"]
# GSC scripts address a Search Console property, not the audited URL — the two
# differ whenever you audit a page on a property you access by domain.
GSCARG = ["{gsc_property}", "--credentials", "{gsc_credentials}"]
# The Links report has no API at all, so incoming links come from a CSV the user
# exports from the Search Console UI. Without --links-csv these items report
# NO_DATA with that instruction rather than guessing.
LINKSARG = ["{links_csv}", "--site", "{url}"]
# URL Inspection is the one GSC call that addresses a page rather than a
# property, so it needs both.
INSPECTARG = ["{url}", "--property", "{gsc_property}",
              "--credentials", "{gsc_credentials}"]

# What each script needs in order to produce an answer. The runner uses this to
# decide, per run mode, whether an item is answerable (run it), not applicable
# (N/A — never counted against the score), or blocked (NO_DATA).
#   offline   parses a local HTML file; works on an archive with no network
#   fetch     requests the single target URL
#   crawl     requests many URLs (slow; meaningless against a single file)
#   api       calls a third-party service (PageSpeed, W3C, Safe Browsing)
#   gsc       needs Google Search Console credentials
REQUIRES = {
    "parse_html.py": "offline",
    # Reads a file a trace already produced, so it needs no network of its own —
    # the measurement happened before the run, and the run must not pretend to be
    # taking it.
    "cwv_metrics.py": "offline",
    "rendered_audit.py": "offline",
    "readability.py": "offline",
    "pagespeed.py": "api",
    "html_validator.py": "api",
    "domain_safety_check.py": "api",
    "duplicate_content.py": "crawl",
    "internal_links.py": "crawl",
    "anchor_text_audit.py": "crawl",
    "orphan_pages_from_sitemap.py": "crawl",
    # Reads two files and fetches nothing, but one of them is the shared crawl's
    # inventory, so it can only run where a crawl happened.
    "server_log_audit.py": "crawl",
    "link_profile.py": "crawl",
    "external_link_quality.py": "crawl",
    "broken_links.py": "crawl",
    "sitemap_checker.py": "crawl",
    "indexability_matrix.py": "crawl",
    "competitor_gap.py": "crawl",
    # Reads a file the user exported; no network, so even archive mode can use it.
    "gsc_links_csv.py": "offline",
    "gsc_checker.py": "gsc",
    "gsc_url_inspection.py": "gsc",
    "gsc_cannibalization.py": "gsc",
}
DEFAULT_REQUIRES = "fetch"

# A script-wide requirement is usually the honest one, but domain_safety_check.py
# mixes ordinary network checks with one keyed third-party service. Only the three
# items whose assertions read Safe Browsing need that credential; uptime and server
# neighbours must keep running without it.
ITEM_REQUIRES = {
    # The same script still answers LO-200 per page. LO-198 passes the shared crawl
    # explicitly and is deliberately site-level, so its requirement cannot be the
    # script-wide default.
    "LO-198": "crawl",
    "MD-187": "crawl",
    "SE-114": "safe_browsing",
    "SE-116": "safe_browsing",
    "TE-171": "safe_browsing",
}

# Empty evidence is not positive evidence.
#
# An item whose rule passes by finding none of the thing it forbids awards a quality
# verdict to a site that has none of the thing — `openspec/specs/registry/` REG-9 and
# `openspec/specs/verdicts/` VRD-2. Measured on a four-line text-only page served for
# the purpose: with no structured data MS-032 and TE-172 passed "Implement & Validate
# Structured Data" and "Implement Structured Data Correctly"; with no stylesheet TE-174
# passed "Minify & Optimize CSS"; with no anchors BL-081 passed "Keep Anchor Text
# Natural and Varied"; with no images MD-185 passed "Optimize Images"; with no
# pagination AR-146 passed "Check Pagination"; and AR-154 returned a **WARN** about a
# page that is not a category page at all.
#
# Every item whose assertion `passes_by_absence` must therefore appear in exactly one of
# the two tables below, and `subject_is_declared_for_every_absence_passing_item` derives
# the candidate set from the built registry and fails the build otherwise. That is what
# makes this a rule rather than a list: an item added tomorrow joins the sweep by
# existing, and the build refuses it until somebody has decided which table it belongs
# in. Before 0.96.0 nothing identified an item that owed a declaration, which is why
# seventeen of them went unnoticed for the life of the registry.
APPLIES_WHEN = {
    "MB-102": {"path": "videos", "gt": 0},
    "MD-190": {"path": "videos", "gt": 0},
    # Images. `image_inventory.py` already withholds `count`, `missing_alt` and
    # `summary.lazy_lcp_candidates` on a page with no images, so these three reported
    # NO_DATA rather than a free pass — the debt was the status, not the pass. The
    # descriptive `summary.images` stays at 0 and is what makes the subject decidable.
    "CI-016": {"path": "summary.images", "gt": 0},
    "MD-186": {"path": "summary.images", "gt": 0},
    "CN-054": {"path": "summary.images", "gt": 0},
    # `image_weight_audit.py` counts before it judges. MB-098's own field is withheld
    # on a page with no images; MD-185 reads `issues` and passed on an empty list.
    "MB-098": {"path": "image_count", "gt": 0},
    "MD-185": {"path": "image_count", "gt": 0},
    # Structured data. A page that declares no schema has nothing for either of these
    # to validate, and both returned `summary.errors` 0 — a pass for "implement
    # structured data" awarded to a page that implements none.
    "MS-032": {"path": "schema_nodes", "gt": 0},
    "GO-143": {"path": "schema_nodes", "gt": 0},
    "TE-172": {"path": "nodes", "gt": 0},
    "TECH-001": {"path": "nodes", "gt": 0},
    # Anchors. `links_analyzed` is 0 on a page with no links, and 0 overused targets
    # out of 0 anchors is not a finding about anchor text.
    "BL-081": {"path": "links_analyzed", "gt": 0},
    # A paginated series. `pagination.paginated` is the checker's own answer to
    # whether there is one; without it `pagination.issues` is empty by construction.
    "AR-146": {"path": "pagination.paginated", "truthy": True},
    # A category page. Without one, `collection_page_checker.py` reports thin copy and
    # a missing description about whatever page it was given — two `warning` issues,
    # which `SEVERITY_ALIAS` reads as `medium`, so the item returned WARN about a page
    # it should never have judged. The only free-pass entry here that was not a pass.
    "AR-154": {"path": "product_links_detected", "gt": 0},
    # Faceted URLs. `count` is `len(rows)` over every internal URL and read 1 on a page
    # with no facets at all, so the subject needed a count of its own — see
    # `faceted_count` in `faceted_nav_audit.py`.
    "AR-163": {"path": "faceted_count", "gt": 0},
    # Stylesheets. A page linking none has no CSS to minify, and `unminified_count`
    # was 0 out of `checked` 0.
    "TE-174": {"path": "checked", "gt": 0},
}

# Why an absence-passing item needs no applicability declaration: the entity whose
# quality it judges cannot legitimately be absent from a site, so finding none of the
# forbidden thing is a real pass rather than an empty one.
#
# Prose rather than a flag, because the claim is arguable and the next person has to be
# able to argue with it. A wrong entry here is a free pass nobody can see, so each names
# the subject rather than asserting the conclusion.
SUBJECT_ALWAYS_PRESENT = {
    # The page's own directives and markup. Every page has a `meta robots`, a set of
    # headings and a DOM, present or absent by the author's choice — which is the
    # finding, not a missing subject.
    "CI-004": "every page has indexing directives, present or absent by choice",
    "MS-031": "every page either carries meta keywords or does not; that is the finding",
    "CI-017": "every page has markup for the validator to read",
    "TE-181": "every rendered page has a DOM for the validator to read",
    "CN-048": "every page has a heading structure, even an empty one",
    "AR-155": "every page has a URL, which is what this judges",
    "CN-036": "every page has text; what this counts is not contrast — see REG-6",
    # The site's own crawl and link graph. A site always has pages and a shape.
    "CI-008": "every crawled site has a link graph; orphans are a property of it",
    "AR-162": "the same link graph, judged for strength rather than for orphans",
    "AR-149": "every crawled site has internal links, redirecting or not",
    "TE-168": "every crawled site has links to check",
    "CI-013": "every site has a robots policy, permissive or not",
    "CI-019": "the same policy, read for what it leaves indexable",
    "GO-136": "every site is asked for a sitemap; its absence is the finding",
    "GO-138": "the same sitemap, read for invalid URLs",
    "GO-137": "the crawl and the sitemap both exist whenever this runs",
    "MS-022": "every crawled site has titles to compare",
    "MS-029": "every crawled site has descriptions to compare, present or empty",
    "CN-039": "every crawled site has pages, and their thinness is the finding",
    "CN-041": "the same pages, compared for duplication",
    "TE-176": "every page has a canonical decision, made or omitted",
    "CI-014": "every requested URL has a redirect chain, possibly of length zero",
    # The response, and the server behind it. A run that got here got a response.
    "TE-170": "every response carries headers, and their absence is the finding",
    "SP-109": "every page loads some set of third-party scripts, possibly empty",
    "SP-110": "every page has a request chain; its shape is the finding",
    "TECH-002": "every page loads fonts or does not, and either is a finding here",
    "CN-051": "every rendered page has overlays or has none; zero is a real pass",
    "MB-094": "the same overlays, on a mobile render",
    "CN-034": "every page has text nodes to measure",
    # The weakest entry here, and it says so. A page with no links is possible, and
    # zero indistinct links out of zero is not a finding about hyperlinks. What stops
    # this being a declaration debt is that `rendered_audit.py` reports no total for
    # links, so there is no field to declare against — a schema gap rather than a
    # judgement. Recorded here so the gap is visible instead of the item looking settled.
    "CN-035": "every page has links or has none; the render reports no total to "
              "declare against, so the subject cannot be stated as a condition",
    "MB-103": "a rendered mobile page has tap targets; a desktop trace omits the key",
    "MB-108": "a rendered mobile page has text; a desktop trace omits the key",
    "MB-100": "every page renders on a phone, well or badly",
    "MB-105": "every page has a rendered and an unrendered form to compare",
    "MD-187": "the key is withheld unless statuses were collected, so zero means "
              "checked and sound rather than nothing looked at",
    # Answers from a service. The service was asked; an empty answer is its answer.
    "SE-114": "Safe Browsing answered; an empty threat list is that answer",
    "SE-116": "the same answer, read for hacked content",
    "TE-171": "the same answer, read as a blocklist check",
    "TE-178": "the neighbour lookup answered; an empty list is that answer",
    "GO-132": "the page either carries duplicate GA4 tags or does not",
    "GO-134": "Search Console answered; no issues is that answer",
    "GO-135": "URL Inspection answered for this URL",
    "MS-023": "Search Console answered with the queries this site ranks for",
    "KW-071": "the same queries, read for contested ones",
    "BL-083": "the backlink export was supplied and read; none broken is a finding",
    "CI-018": "a server log was supplied and parsed; no issues is a finding about it",
    "GEO-006": "every entity check asks about this site's own identity",
}

# Items whose rule cannot report FAIL, and are meant not to.
#
# KW-076 could not fail on any site for years and nothing noticed, because a rule
# that always passes looks exactly like a rule that always holds.
# `tools/audit_reachability.py` now proves unreachability from the script's source
# and checks it against this table in three directions: a proved rule that is not
# here fails the build, an entry here that is no longer provable fails the build,
# and an entry naming a different mechanism than the one proved fails the build.
# That last one is the difference between this and an exemption list — the reason
# is anchored to a token the code has to keep earning, rather than to prose nobody
# re-reads. `mechanism` must be one of `audit_reachability.MECHANISMS`.
#
# Adding an entry is a claim that a site cannot be wrong in the way the item's
# title names. Make sure that is what you mean before writing one.
CANNOT_FAIL = {
    "TE-178": {
        "mechanism": "path_never_emitted",
        "why": "check_neighbors() resolves the hosting IP and stops there. Judging "
               "the neighbours needs a paid reverse-IP service this project does "
               "not buy, and a fabricated `suspicious` would be worse than no "
               "answer, so the field is deliberately never written and the item is "
               "NO_DATA everywhere until that input exists.",
    },
    "TE-179": {
        "mechanism": "warn_complement",
        "why": "0.44.0 gave this item the domain-history half of its title through "
               "whois age: established passes, younger than 90 days warns, an "
               "absent age is NO_DATA. The warn band is the assertion's exact "
               "complement on purpose — a young domain is worth pricing, not a "
               "defect to fix — and the ruling that no 'worth knowing' status "
               "exists still stands. ROADMAP.md records the reasoning.",
    },
}

# How much work a fix costs, so that priority can weigh severity against effort
# instead of ranking by severity alone. These are per-category heuristics, not
# per-item estimates: a meta tag is a config edit, a rewrite is not, and an
# outreach campaign is not a code change at all. Anything finer would be a
# fabricated precision.
EFFORT_BY_CATEGORY = {
    "crawling_indexing": "low", "meta_structured": "low", "security": "low",
    "technical": "low", "google": "low",
    "mobile": "medium", "speed": "medium", "media": "medium", "keywords": "medium",
    "content": "high", "international": "high", "architecture": "high",
    "backlinks": "high", "competition": "high", "local": "high",
    "geo_ai": "medium",
}
# Outliers where the category default is plainly wrong for a specific item.
EFFORT_OVERRIDES = {
    "CN-047": "low",    # fix spelling
    "CN-064": "low",    # add a call to action
    "MS-031": "low",    # drop meta keywords
    "AR-160": "low",    # footer links
    "TE-176": "high",   # migrate to HTTP/2/3 — infrastructure, not a page edit
    "SP-107": "high",   # Core Web Vitals work is rarely a quick fix
    "SP-108": "high",
    "SP-109": "high",
}
# A human-facing task is never "low" no matter what its category says.
EFFORT_FLOOR_BY_SOURCE = {"manual": "high", "llm": "medium"}
EFFORT_RANK = {"low": 0, "medium": 1, "high": 2}


def effort_for(entry: dict) -> str:
    e = EFFORT_OVERRIDES.get(entry["id"]) or EFFORT_BY_CATEGORY.get(entry["category"], "medium")
    floor = EFFORT_FLOOR_BY_SOURCE.get(entry["source"])
    if floor and EFFORT_RANK[floor] > EFFORT_RANK[e]:
        e = floor
    return e


# ref -> (severity, source, script, args, assert_rule, fix, warn)
MAP: dict[int, tuple] = {}


def item(ref, sev, source, script=None, args=None, rule=None, fix="", warn=None):
    MAP[ref] = (sev, source, script, args, rule, fix, warn)


# --- 1. Crawling & Indexing -------------------------------------------------
# This asserted `rows.0.robots_allowed` — the same field, with the same rule, as
# CI-005 below. So "ensure the URL is indexed" was answered by "robots.txt does not
# block it", and a page marked `noindex`, or served with `X-Robots-Tag: noindex`, or
# canonicalised to somewhere else, passed a critical item about being indexed. The
# script already weighs all of those into `verdict` and nothing in the registry read
# it. Whether Google has *actually* indexed the URL is CI-010/GO-135 via URL
# Inspection; this item is everything the page itself can be asked.
item(1, "critical", S, "indexability_matrix.py", PAGE,
     {"path": "rows", "field": "verdict",
      "value_map": {"indexable": "pass", "not_indexable": "fail"}},
     "Remove noindex, allow crawling in robots.txt, add internal links, submit the URL in GSC")
# Indexation is a fact only Google holds, so this item now asks Google. It asserted
# `summary.urls >= 1` from sitemap_checker — one URL present in a sitemap, which is
# submission and not indexation, and passed any site with a sitemap at all however much
# of it Google had dropped.
#
# The narrowing is deliberate and is the honest half of the trade: URL Inspection
# answers for **one** page, the audited one, while the title says "content". Whole-site
# coverage is the Index Coverage report, which the Search Console API has never exposed,
# and every available substitute is worse than a narrow truth — counting pages with
# impressions would fail every indexed page nobody has searched for yet. `indexed` is
# null when the coverage wording is unrecognised, and the item is NO_DATA without a
# `gsc` capability, which is what "nobody measured this" should look like.
item(2, "high", S, "gsc_url_inspection.py", INSPECTARG,
     {"path": "indexed", "truthy": True},
     "Get the page indexed: remove noindex, allow crawling, then request indexing in "
     "Search Console. Submit only valuable templates — categories, product pages, "
     "articles")
item(3, "critical", S, "indexability_matrix.py", PAGE,
     {"path": "rows.0.status", "eq": 200},
     "Canonical URL must return 200 OK across all variants (http/https, www/non-www)")
item(4, "critical", S, "parse_html.py", HTMLARG,
     {"path": "meta_robots", "none_matching": "noindex", "missing_is": "pass"},
     "Indexable pages should be set to index, follow")
item(5, "critical", S, "indexability_matrix.py", PAGE,
     {"path": "rows.0.robots_allowed", "truthy": True},
     "Remove the blocking rule from robots.txt")
item(6, "medium", S, "robots_checker.py", PAGE,
     {"path": "sitemaps", "len_gte": 1},
     "Add a Sitemap: https://example.com/sitemap.xml line to robots.txt")
item(7, "medium", M, fix="Submit the sitemap in Google Search Console and Bing Webmaster Tools")
item(8, "high", S, "link_profile.py", CRAWLARG,
     {"path": "orphan_pages.count", "eq": 0},
     "Eliminate orphan pages: add 1-2 contextual internal links to each")
# canonical_checker.py never emits a `critical` or `high` issue — it says
# "warning" and "error" — so the old none_severity rule could not fire and this
# critical item passed on every site ever audited. Its `verdict` field has a
# closed vocabulary, so map that instead. `missing` fails here and passes in
# CI-011 on purpose: this item is "serve content at a single canonical URL", and
# declaring no canonical at all is the failure it names. `unknown` is deliberately
# unmapped — it means the script could not read the page, which is NO_DATA.
item(9, "critical", S, "canonical_checker.py", PAGE,
     {"path": "rows", "field": "verdict",
      "value_map": {"self_canonical": "pass", "canonicalized": "pass",
                    "cross_host": "fail", "missing": "fail"}},
     "Self-canonical on the primary version, 301 from duplicates")
# A page can point rel=canonical at itself and still have Google pick another
# URL. Nothing in the page reveals the disagreement — only URL Inspection does.
# When the page declares no canonical there is nothing to compare, so the script
# leaves canonical_match null and the item stays NO_DATA.
item(10, "high", S, "gsc_url_inspection.py", INSPECTARG,
     {"path": "canonical_match", "truthy": True},
     "Align the declared canonical with the one Google selected, or work out why "
     "Google prefers a different URL")
item(11, "high", S, "canonical_checker.py", PAGE,
     # canonical_checker emits one of five verdicts and never the words
     # "mismatch" or "conflict", so the old pattern passed every page. Mapping
     # its actual vocabulary also fixes the other half: "unknown" means the
     # script could not tell, which is NO_DATA, not a pass.
     {"path": "rows", "field": "verdict",
      "value_map": {"self_canonical": "pass", "missing": "pass",
                    "canonicalized": "pass", "cross_host": "fail"}},
     "Do not combine noindex with a canonical pointing elsewhere")
item(12, "medium", S, "url_quality.py", PAGE,
     {"path": "rows.0.score", "gte": 70},
     "Keep URLs short, readable, lowercase, words separated by hyphens")
# robots_checker.py reports sitemaps and syntax; it never says anything about
# CSS, JS or images, so this critical item passed on every site ever audited —
# the pattern was matching the script's own module docstring, which mentions
# both. robots_path_tester now discovers the audited page's own rendering assets
# and asks whether Googlebot may fetch them. A literal path proves only that
# robots.txt does not happen to name that invented path. `blocked_urls` is omitted
# when the page references no same-origin CSS, JS or image, so emptiness cannot earn
# a critical PASS for a page that supplied nothing to test.
item(13, "critical", S, "robots_path_tester.py",
     ["{url}", "--discover-assets", "--agent", "Googlebot"],
     {"path": "blocked_urls", "len_eq": 0},
     "Do not block critical CSS/JS/images in robots.txt - Google must be able to render the page")
item(14, "high", S, "redirect_checker.py", PAGE,
     {"path": "has_loop", "falsy": True},
     "Use 301/308 for permanent and 302/307 for temporary; remove chains and loops",
     {"path": "total_hops", "lte": 2})
item(15, "critical", S, "indexability_matrix.py", PAGE,
     {"path": "rows.0.status", "lt": 500},
     "Set up uptime and log alerts, resolve 5xx errors reported in GSC")
item(16, "high", S, "image_inventory.py", PAGE,
     {"path": "missing_alt", "eq": 0},
     "Descriptive alt on informative images, empty alt on decorative ones")
item(17, "medium", S, "html_validator.py", PAGE,
     {"path": "summary.errors", "eq": 0},
     "Fix W3C validation errors - they affect rendering and parsing")
# The only item in the registry that no amount of fetching could ever answer, so it
# was `manual` until something could read the evidence. `server_log_audit.py` reads a
# log the operator supplies — every other check asks the site what it *offers*, and
# this is the one that says what crawlers *did*.
#
# `{inventory_json}` is required rather than optional, which means the item is
# NO_DATA in `page` and `archive` mode even with a log. The two findings worth having
# — sitemap URLs no crawler requested, and URLs crawlers request that the site does
# not offer — are subtractions between the log and the crawl, and neither half is
# useful alone. Anyone with a server log is auditing a live site, where the crawl runs.
#
# ISSUES_ANY with the NOTHING_SERIOUS warn band, so the script's own three severities
# carry through: high fails, medium warns, low is informational. The thresholds behind
# them are in the script beside the numbers they judge, stated as the conventions they
# are — see §2 of KNOWN-ISSUES.md for why that matters here more than most.
item(18, "medium", S, "server_log_audit.py",
     ["{server_log}", "--url", "{url}", "--inventory", "{inventory_json}"],
     ISSUES_ANY(), warn=NOTHING_SERIOUS(),
     fix="Stop the crawl waste the log shows: fix or 410 the URLs in top_wasted, "
         "canonicalise or disallow the parameterised ones, and add internal links "
         "to sitemap URLs nothing crawled")
item(19, "high", S, "robots_path_tester.py",
     ["{url}", "/search", "/cart", "/checkout", "/login", "--probe"],
     # Two repairs, 0.20. The first was 0.13: `allowed` and `true` sit in different
     # fields of a nested dict, so they never appeared in one string, the pattern never
     # fired, and every site passed. That was fixed by flattening to `allowed_urls`.
     #
     # Which produced the opposite defect and a worse one. `allowed_urls` is computed
     # from robots.txt alone — the script never fetched the paths — so a site is
     # accused of exposing `/cart` when it has no cart, because nothing disallows a
     # page that does not exist. Every small site fails this, and it took a live audit
     # to notice: the fixture's robots.txt had been written to satisfy the assertion,
     # and a fixture built to pass the registry cannot catch an item that accuses
     # everyone.
     #
     # The second repair is the mechanism repair, and it goes the other way round from
     # how it first looked. Plerdy's title says `noindex` and the fix said `noindex`;
     # the assertion said robots.txt `Disallow`. Those are not the same instrument and
     # they conflict — a path blocked in robots.txt is never crawled, so its `noindex`
     # is never read. The title was not the thing that was wrong: it is inherited
     # wording (`plerdy-titles.json`, a record of someone else's checklist and not ours
     # to rewrite) and it described the goal correctly all along. `indexable_urls` is
     # that goal made checkable — the path exists, a crawler may fetch it, and nothing
     # keeps it out of the index. Either mechanism satisfies it. Absent when robots.txt
     # could not be read, and a path whose probe failed lands in `unprobed_urls`
     # instead, so a network error cannot read as a clean site.
     {"path": "indexable_urls", "len_lte": 0},
     "Keep internal search and system pages out of the index: noindex,follow on the "
     "page, or Disallow in robots.txt, and exclude them from sitemaps")

# --- 2. Meta & Structured Data ---------------------------------------------
item(20, "high", S, "parse_html.py", HTMLARG,
     {"path": "title", "len_lte": 60},
     "Shorten the title so it is not truncated in the SERP (~60 characters)")
item(21, "medium", S, "parse_html.py", HTMLARG,
     {"path": "title", "len_gte": 30},
     "Titles under 30 characters are usually too vague to match intent")
item(22, "high", S, "duplicate_content.py", CRAWLARG,
     {"path": "summary.duplicate_title_groups", "eq": 0},
     "Crawl for duplicate titles, then differentiate or canonicalize them")
item(23, "high", S, "gsc_cannibalization.py", GSCARG,
     {"path": "summary.cannibalized_queries", "eq": 0},
     "Find queries in GSC where multiple URLs compete; pick the target and consolidate the rest",
     {"path": "summary.cannibalized_queries", "lte": 3})
item(24, "medium", L, fix="Lead the title with the main topic")
item(25, "medium", L, fix="The title must accurately describe the page content and intent")
item(26, "critical", S, "parse_html.py", HTMLARG,
     {"path": "title", "truthy": True},
     "Every page needs a title")
# Three items about meta descriptions that were two assertions between them. MS-027
# and MS-028 both asserted `meta_description truthy` — the same field, the same script,
# the same rule — so "write a unique, compelling description" was answered by "a
# description exists", and MS-027 could not fail on any page MS-028 passed. MS-029,
# about *duplicate descriptions*, read `summary.exact_duplicate_groups`, which counts
# duplicate page **content**: a different requirement borrowing CN-041's verdict.
#
# Split so each asserts what its own title says. MS-028 keeps the presence check, which
# is exactly what it asks for. MS-029 gets evidence of its own — the crawl inventory has
# carried `meta_description` per page since 0.9.0 and nothing read it. And MS-027 is not
# a script item at all: "unique" is now MS-029's job, and **compelling** is a judgement
# no assertion makes. Leaving it as a presence check let the registry claim it had
# graded the copy. The copy lens grades copy.
item(27, "high", L, fix="Write a description that earns the click: specific to this "
                        "page, distinct from every other, and true to what is on it")
item(28, "medium", S, "parse_html.py", HTMLARG,
     {"path": "meta_description", "truthy": True},
     "Fill in meta descriptions, high-value pages first")
item(29, "medium", S, "duplicate_content.py", CRAWLARG,
     {"path": "summary.duplicate_description_groups", "eq": 0},
     "Give each page its own meta description — these are shared across pages")
item(30, "low", S, "parse_html.py", HTMLARG,
     {"path": "meta_description", "len_between": [120, 165]},
     "Keep meta descriptions around 150-160 characters")
item(31, "low", S, "parse_html.py", HTMLARG,
     {"path": "meta_keywords", "falsy": True, "missing_is": "pass"},
     "Remove meta keywords - search engines ignore it")
item(32, "high", S, "schema_required_props.py", PAGE,
     {"path": "summary.errors", "eq": 0},
     "Add required schema properties and validate with the Rich Results Test",
     {"path": "summary.warnings", "lte": 3})
item(33, "medium", S, "social_meta.py", PAGE,
     {"path": "score", "gte": 80},
     "Fill in Open Graph and Twitter Card tags")

# --- 3. Content -------------------------------------------------------------
# a11y_seo_checker.py checks H1 count, lang, viewport, alt text, labels,
# landmarks and generic link text — it has never looked at font size, link styling
# or tap targets. The three items that asked it to were matching wording it cannot
# emit, so they passed on every site.
#
# These are computed values: they depend on stylesheets, media queries and scripts
# that HTML alone does not settle, so a model reading markup is a weaker answer
# than it looks. rendered_audit.py reads what a browser measured instead. Without
# --rendered-json the placeholder is unresolved and they report NO_DATA.
RENDERED = ["{rendered_json}"]
item(34, "medium", S, "rendered_audit.py", RENDERED,
     {"path": "text_nodes_below_12px", "eq": 0},
     "Readable font size across all breakpoints")
item(35, "medium", S, "rendered_audit.py", RENDERED,
     {"path": "links_indistinct", "eq": 0},
     "Links must be visually distinct from body text")
item(36, "medium", S, "a11y_seo_checker.py", PAGE,
     {"path": "checks.inline_contrast_candidates", "eq": 0},
     "Text contrast at WCAG AA or better (4.5:1)")
item(37, "low", L, fix="Separate primary from supplementary content visually and semantically")
item(38, "medium", S, "freshness_checker.py", PAGE,
     {"path": "score", "gte": 70},
     "Refresh evergreen material and balance it with new content")
item(39, "high", S, "duplicate_content.py", CRAWLARG,
     {"path": "summary.thin_pages", "eq": 0},
     "Consolidate or expand thin pages",
     {"path": "summary.thin_pages", "lte": 5})
     # `signals.privacy_links`, not `policy_links`: the latter means editorial
     # standards (fact-checking, corrections, ethics), so this item — "Publish an
     # Up-to-Date Privacy Policy" — was answering a different question in both
     # directions. A site with a proper privacy policy failed unless it also
     # published editorial standards; a site with an ethics page and no privacy
     # policy passed. Found by the good/broken fixture audit, which is what a check
     # that agrees with every site it has ever seen looks like from outside.
item(40, "medium", S, "eeat_signal_checker.py", PAGE,
     {"path": "signals.privacy_links", "len_gte": 1},
     "Publish an up-to-date privacy policy and link to it")
item(41, "high", S, "duplicate_content.py", CRAWLARG,
     {"path": "summary.exact_duplicate_groups", "eq": 0},
     "Eliminate internal duplicates: consolidate or canonicalize")
item(42, "medium", L, fix="Review external duplicates and syndication, agree on a canonical to the source")
item(43, "high", L, fix="Remove scraped or lightly-rewritten third-party content")
item(44, "medium", S, "eeat_signal_checker.py", PAGE,
     {"path": "signals.trust_links", "len_gte": 1},
     "Provide a clear, easy-to-find contact page")
item(45, "medium", M, fix="Run a content gap analysis against competitors")
item(46, "medium", L, fix="Review copy quality and content classification")
item(47, "medium", L, fix="Check grammar and spelling")
# `ISSUES_ANY()` with no `warn=`, and this is the decision the note on those helpers
# asks to be said out loud. The pair means "an error-class finding fails this, a
# warning-class one only warns", and `parse_html.py` has no warning-class finding:
# `_structure_issues` grades a heading skip and a missing `<main>` as `error`, and
# the script says nothing else anywhere. The band could not fire on any page ever
# built — `audit_reachability.py` proves it from the script's own vocabulary — so it
# promised a middle verdict that did not exist. Removing it changes no verdict.
#
# The other repair is real and is not this one: grade a heading skip below a missing
# landmark inside `_structure_issues`, which would make a band live and turn some of
# today's FAILs into WARNs. That is a pricing decision about a `high` item, and it
# belongs to whoever makes it rather than to the audit that found the dead band.
item(48, "high", S, "parse_html.py", HTMLARG,
     ISSUES_ANY(),
     "Use hierarchical headings and semantic HTML")
item(49, "medium", L, fix="Target topics and queries, not isolated keywords")
item(50, "high", L, fix="Follow Google Search Essentials - quality and spam policies")
# mobile_render_checker.py reports viewport, fixed widths and sticky positioning.
# It says nothing about interstitials, and the two items asking it for them matched
# nothing. What makes a dialog intrusive is how much of the viewport it covers —
# a measurement, once something has actually laid the page out.
item(51, "high", S, "rendered_audit.py", RENDERED,
     {"path": "overlays_covering_content", "eq": 0},
     "Remove intrusive interstitials, especially on mobile")
item(52, "medium", L, fix="Limit heavy advertising above the fold")
# This asserted `raw.word_count >= 300`. **It counted words.** Nothing in the item
# observed an iframe — `javascript_render_audit.py` reports no iframe signal of any
# kind — so a café was told to stop hiding content in iframes it does not have, on
# three of eight pages, because one of them ran to 293 words. Worse than CI-019's
# mismatch, which at least listed URLs a reader could check: this FAIL reads as
# entirely sensible until somebody opens `checklist.json`.
#
# It does not become a script item with a better field, because the question is not
# "is there an iframe" — embeds are normal and fine. It is whether the content that
# matters is inside one, and that is a judgement about what matters. The layout lens
# reads the page and can see both.
item(53, "medium", L, fix="Keep the content this page is about in the page, not inside "
                          "an embedded frame a crawler may not credit to it")
item(54, "high", S, "image_inventory.py", PAGE,
     # The script does detect this, and says "Likely LCP image is lazy-loaded" —
     # LCP before lazy, so a pattern requiring lazy first never matched. Counting
     # the flag the script already computes needs no wording at all.
     {"path": "summary.lazy_lcp_candidates", "eq": 0},
     "Lazy-loaded content must remain discoverable by crawlers")
# This asserted `pagination.next` was truthy, so every page that is not itself part
# of a paginated series — which is nearly every page ever audited — was told to "make
# infinite scroll crawlable". A `medium` accusation, in the content category, on
# almost every site, and its twin AR-146 had the opposite defect (see below).
#
# LLM rather than script: the item is about whether a page loads more content on
# scroll *without* offering paginated URLs. Nothing here observes scroll behaviour,
# and `rel=next` being absent is not evidence of infinite scroll — it is the normal
# state of an unpaginated page.
item(55, "medium", L,
     fix="Make infinite scroll crawlable via paginated URLs")
item(56, "medium", S, "freshness_checker.py", PAGE,
     {"path": "dates", "len_gte": 1},
     "Show publication and updated dates")
# This asserted `signals.authors len_gte 1`, so the "and Publisher" half of the title
# was never required — and `eeat_signal_checker.py` made that weaker rule worse by
# putting publisher names in the author list. Read the pair whole so neither half can
# stand in for the other.
item(57, "high", S, "eeat_signal_checker.py", PAGE,
     {"path": "signals.authorship", "eq": {"author": True, "publisher": True}},
     "Show author and publisher clearly")
item(58, "low", L, fix="Check whether the content risks being flagged by SafeSearch")
item(59, "high", L, fix="Remove hidden text added to manipulate rankings")
item(60, "critical", L, fix="Do not serve different content to crawlers and users (cloaking)")
item(61, "high", L, fix="Remove doorway pages - query-targeted pages with no standalone value")
item(62, "medium", L, fix="Reduce ad density")
item(63, "medium", L, fix="Do not overuse pop-ups")
item(64, "low", L, fix="Use clear, explicit calls to action")
item(65, "critical", S, "parse_html.py", HTMLARG,
     {"path": "h1", "len_eq": 1},
     "Exactly one H1 per page")
item(66, "medium", S, "parse_html.py", HTMLARG,
     {"path": "h2", "len_gte": 2},
     "Structure the copy with H2 subheadings")
item(67, "high", L, fix="Publish people-first content; AI assistance is fine when the result helps a human")
# The floor is the sum of the score components a page of any type can carry, read
# out of eeat_signal_checker's own arithmetic: authors 20 + trust 15. The other four
# components are not page-type-neutral. Credentials (20), first-hand experience (20)
# and external citations (10) are article signals — a privacy policy has no business
# carrying them, and they are exactly the 40 points that separate the good fixture's
# entry page from its policy pages. `policy 15` is editorial standards — fact-checking,
# corrections, ethics — and is 0 on every page of every tree here, so the reachable
# maximum for a site with no standards page is 85 rather than 100.
#
# Measured before it moved: at 60 this item passed one page in the fifteen this
# repository can serve, and reported FAIL on both fixture origins — an item that cannot
# tell the exemplary tree from the broken one has stopped measuring. A page-level check
# aggregates on the worst sampled page, so a floor above 35 asks a policy page for a
# byline's worth of expertise and fails every real site that has one.
item(68, "high", S, "eeat_signal_checker.py", PAGE,
     {"path": "score", "gte": 35},
     "Strengthen authorship and E-E-A-T: author, credentials, first-hand experience, sourced claims")

# --- 4. Keyword analysis ----------------------------------------------------
item(69, "high", M, fix="Run keyword research and set position benchmarks")
item(70, "high", S, "gsc_cannibalization.py", GSCARG,
     {"path": "branded.owns_homepage", "truthy": True},
     "Confirm the homepage ranks first for the branded query")
# `worst_spread` disappeared when the script split multi-URL queries into broad
# cannibalization and the narrower close-position contest. MS-023 already owns
# the broad `cannibalized_queries` count; this item measures the distinct close
# contest that is evidence of duplication or overuse.
#
# The warn band is not decoration. The rule this replaced was `worst_spread lte 3`,
# so the item already tolerated a little before it failed; repointing it at a count
# with `eq 0` alone quietly made a `high` item fail on a single contested query.
# MS-023 grades the broader `cannibalized_queries` on the same script with `lte 3`,
# and a narrower signal cannot honestly be stricter than the broader one.
item(71, "high", S, "gsc_cannibalization.py", GSCARG,
     {"path": "summary.contested_queries", "eq": 0},
     "Find keyword overuse and duplication across URLs",
     {"path": "summary.contested_queries", "lte": 3})
# article_seo.py has no keyword finding at all — its seo_issues describe presence
# and length, and the word "keyword" appears only inside remediation text. Both
# patterns were matching that: KW-072 and KW-073 reported a keyword problem
# whenever the title or the H1 had *any* problem, and said nothing when the keyword
# was genuinely missing. Whether a title leads with the topic, and whether an H1
# carries the primary keyword or a close variant, are the same copy judgement their
# H2 and meta-description twins already are.
item(72, "high", L, fix="Put the primary topic in the title")
item(73, "high", L, fix="Include the primary keyword in the H1")
# article_seo.py advises on title and H1 keywords but emits nothing about
# keywords in an H2 or in the meta description, so both items passed unread.
# Judging a "close variant" is a copy question anyway — a regex cannot see that
# "running shoes" and "shoes for runners" are the same intent.
item(74, "medium", L, fix="Include the primary keyword or a close variant in an H2")
item(75, "medium", L,
     fix="Include the primary keyword in the meta description - it affects CTR")
# The old rule asserted an echo of article_seo.py's own keyword extraction, so it
# could not fail. The keyword is now an operator input and this item reports
# NEEDS_INPUT without it. Assert `in_body`, not `target_keyword`, because the title
# asks whether the keyword occurs in body copy rather than whether one was named.
#
# `--no-autocomplete` because without it the script asks Google Suggest for related
# terms — once per sampled page, sending the operator's keyword to a third party for
# a field (`related_keywords`) no item asserts. `article_seo.py` is `fetch` in
# REQUIRES above, and `fetch` says "requests the single target URL"; the flag is what
# makes that true. Every direct test of this script has passed it since the keyword
# input landed, so the audit path was the only caller still making the request.
item(76, "medium", S, "article_seo.py",
     ["{url}", "--keyword", "{keyword}", "--no-autocomplete"],
     {"path": "keyword_usage.in_body", "truthy": True},
     "The primary keyword should appear naturally in body copy")
item(77, "medium", L, fix="Include the primary keyword in the opening paragraph")

# --- 5. Backlinks -----------------------------------------------------------
item(78, "high", M, fix="Assess backlink quality and authority (needs an external service or a GSC CSV export)")
item(79, "high", M, fix="Identify spammy referring domains")
item(80, "medium", M, fix="Disavow only on clear spam - not as routine hygiene")
item(81, "medium", S, "anchor_text_audit.py", CRAWLARG,
     {"path": "summary.overused_exact_match_targets", "eq": 0},
     "Diversify anchors, remove exact-match over-optimization",
     {"path": "summary.overused_exact_match_targets", "lte": 10})
item(82, "medium", M, fix="Monitor and reclaim lost backlinks")
item(83, "medium", S, "external_link_quality.py", PAGE,
     {"path": "summary.broken_links", "eq": 0},
     "Fix broken links: update the URL or add a redirect")
item(84, "medium", S, "gsc_links_csv.py", LINKSARG,
     {"path": "concentration.top1_share_pct", "lte": 50},
     "Diversify referrers: one domain supplying most links makes rankings hostage "
     "to a single relationship",
     {"path": "concentration.top1_share_pct", "lte": 65})
item(85, "low", M, fix="Do not optimize for domain age - it is not a ranking factor")
item(86, "low", S, "gsc_links_csv.py", LINKSARG,
     {"path": "total_links", "gte": 1},
     "Export Search Console -> Links periodically so the trend is visible; the "
     "count matters far less than who the links come from")
item(87, "medium", S, "gsc_links_csv.py", LINKSARG,
     {"path": "linking_domains", "gte": 5},
     "Grow the number of distinct referring domains — root domains move rankings, "
     "repeat links from the same site much less")
item(88, "high", M, fix="Earn topically relevant backlinks to the target URL")
item(89, "high", M, fix="Verify the disavow file does not contain valuable links")
item(90, "low", M, fix="Create and maintain social profiles where the audience actually is")
item(91, "low", M, fix="Publish LinkedIn articles and maintain the company page")
item(92, "low", M, fix="Pitch and appear on relevant podcasts")

# --- 6. Mobile --------------------------------------------------------------
item(93, "critical", S, "parse_html.py", HTMLARG,
     {"path": "viewport", "truthy": True},
     "Responsive, mobile-first layout")
item(94, "high", S, "rendered_audit.py", RENDERED,
     {"path": "mobile_overlays_covering_content", "eq": 0},
     "Remove intrusive interstitials on mobile")
item(95, "medium", S, "image_weight_audit.py", ["{url}", "--fetch-images"],
     # `large_image_count` is the same measurement the pattern was reaching for —
     # images whose transfer size exceeds LARGE_IMAGE_BYTES — taken from the count
     # instead of from the sentence announcing it. The key is absent when no
     # transfer size was learned, so a page nobody fetched is NO_DATA rather than
     # light.
     #
     # Which is why this item moved onto `--fetch-images`, MD-185's invocation. On
     # `PAGE` no image is ever requested, `content_length` is None on every row, and
     # the item was NO_DATA on every live run — a question about transfer weight
     # asked of a run that transferred nothing. It costs no extra launch and no extra
     # request: MD-185 already fetches these images, and the runner groups by
     # (script, args). The old pattern hid this by answering PASS instead.
     {"path": "large_image_count", "lte": 5},
     "Reduce mobile page weight")
item(96, "medium", S, "image_weight_audit.py", PAGE,
     {"path": "responsive_count", "gte": 1},
     "Use srcset/sizes for responsive images")
item(97, "medium", S, "image_weight_audit.py", PAGE,
     {"path": "modern_format_count", "gte": 1},
     "Move to WebP/AVIF and compress images")
item(98, "medium", S, "image_weight_audit.py", PAGE,
     # `(?i)size|dimension` over issue messages caught two unrelated findings —
     # "Large image transfer size" and "Responsive image has srcset but no sizes" —
     # and their union was nobody's measurement. It is what a pattern happened to
     # match, and a structured rule cannot reproduce an accident.
     #
     # The half kept is the one this item is titled for. `sizes` is what tells the
     # browser which `srcset` candidate to take; without it the browser guesses from
     # its own default and a phone can be served the desktop file. The other half is
     # MB-095's question and is still asked there, once.
     #
     # `eq: 0`, not the old rule's `lte: 10`. That ten counted matching *issue
     # messages*; carried over to a count of images it would need eleven of them
     # offering width-described candidates with no `sizes` before the page said
     # anything, which is a rule that cannot fire on any real page. One such image
     # is a defect.
     #
     # The corpus still cannot express it. An `<img srcset>` added to the broken tree
     # makes `responsive_count` 1 there, which hands MB-096 and MD-189 a pass on both
     # fixtures — two items losing their discriminating power to give one item its.
     # So this stays in `SAME_ON_BOTH`, now for a reason that is true.
     {"path": "srcset_without_sizes_count", "eq": 0},
     "Serve properly sized images")
item(99, "medium", G, fix="Review mobile signals in Google Search Console")
item(100, "medium", S, "mobile_render_checker.py", PAGE,
     {"path": "issues", "none_severity": ["critical", "high", "medium"]},
     "Fix mobile UX issues")
item(101, "low", L, fix="Keep mobile navigation within thumb reach")
item(102, "low", S, "video_schema_checker.py", PAGE,
     ISSUES_ANY(),
     "Optimize video for mobile", warn=NOTHING_SERIOUS())
# Only answerable from a mobile render; rendered_audit.py drops the key when the
# recorded viewport is a desktop window, so this is NO_DATA rather than a verdict
# about a viewport nobody looked at.
item(103, "medium", S, "rendered_audit.py", RENDERED,
     {"path": "tap_targets_below_48px", "eq": 0},
     "Increase tap targets to 48x48 CSS pixels")
# MB-104 left TE-166's synonym group in 0.44 because its title promises an icon
# that displays, not merely a declaration. It now fetches and measures the icon: an
# unreachable declaration is FAIL because the declared resource is defective, while
# an unrecognised format is NO_DATA because no size was measured. A resolvable SVG
# passes as a scalable vector. The separate measurement now carries weight 1; as
# TE-166's scores_with twin it carried 0.
item(104, "low", S, "favicon_check.py", PAGE,
     {"path": "favicon.displays_at_48px", "truthy": True},
     "Serve a favicon that resolves and is at least 48x48 - a declared icon returning 404 shows nothing in a mobile result")
item(105, "high", S, "javascript_render_audit.py", JSRENDER,
     {"path": "diffs", "len_eq": 0},
     "Put the title, description, canonical, H1s, internal links, schema and body text in the served HTML, not only in what JavaScript builds")
item(106, "medium", M, fix="Test on real devices before and after release")

# --- 7. Speed ---------------------------------------------------------------
item(107, "high", S, "pagespeed.py", ["{url}", "--strategy", "mobile"],
     RATING("FCP"),
     "Speed up above-the-fold rendering", warn=RATING_WARN("FCP"))
# The old rule asserted that field data *exists*, which is a different question
# from the one in the title and answers it wrongly: CrUX publishes nothing for a
# low-traffic URL, so every small site failed a critical item for being small.
# `field_cwv` is emitted only when there is field data, so its absence is NO_DATA.
item(108, "critical", S, "pagespeed.py", ["{url}", "--strategy", "mobile"],
     {"path": "field_cwv.verdict", "value_map": {"pass": "pass", "fail": "fail"}},
     "Bring real-user LCP, INP and CLS inside the Core Web Vitals thresholds")
item(109, "medium", S, "third_party_script_audit.py", PAGE,
     {"path": "blocking_third_party_count", "eq": 0},
     "Remove render-blocking third-party scripts",
     {"path": "blocking_third_party_count", "lte": 2})
item(110, "medium", S, "critical_request_chain.py", PAGE,
     ISSUES_ANY(),
     "Shorten the critical request chain", warn=NOTHING_SERIOUS())
# SP-111 to SP-113 asserted the wrong field under the right title, which is GO-134's
# defect in the speed group: `performance_score` is Lighthouse's blended lab number, it
# mixes TBT and Speed Index, and it is not Core Web Vitals. Search Console's CWV report is
# CrUX split by device, and `field_cwv.verdict` is exactly that — so the title and the
# assertion now agree, and the threshold a verdict rests on is Google's rather than the
# unmeasured `>= 90` this registry inherited.
#
# The blended score did not need a better threshold; it needed to stop being a verdict. It
# is reported outside the score, beside the Search Console opportunities, for the reason
# that section exists: worth knowing is not the same claim as failing.
#
# Desktop field data is the one genuinely new thing here — nothing in the registry asserted
# it before. SP-112 and SP-113 become the same call as SP-108 and are declared twins in
# SAME_CHECK above rather than counted three times.
item(111, "high", S, "pagespeed.py", ["{url}", "--strategy", "desktop"],
     {"path": "field_cwv.verdict", "value_map": {"pass": "pass", "fail": "fail"}},
     "Bring desktop Core Web Vitals into the green")
item(112, "high", S, "pagespeed.py", ["{url}", "--strategy", "mobile"],
     {"path": "field_cwv.verdict", "value_map": {"pass": "pass", "fail": "fail"}},
     "Bring mobile Core Web Vitals into the green")
# The fix text has always named all three thresholds; the rule tested one of them, so a
# page failing CLS passed an item titled "Meet Core Web Vitals Thresholds". `field_cwv`
# grades LCP, INP and CLS together, which is what both the title and the fix promised.
item(113, "critical", S, "pagespeed.py", ["{url}", "--strategy", "mobile"],
     {"path": "field_cwv.verdict", "value_map": {"pass": "pass", "fail": "fail"}},
     "LCP < 2.5s, INP < 200ms, CLS < 0.1")

# --- 8. Security ------------------------------------------------------------
# `threats`, not `matches`: `matches` is the key in Google's raw response and the
# script never re-emits it under that name. `audit_assertions.py` caught the difference,
# which is what it is for — and it is already in that tool's PATH_EXEMPT, since a field
# that needs a key is absent from a keyless probe without being wrong.
item(114, "critical", S, "domain_safety_check.py", PAGE,
     {"path": "safe_browsing.threats", "len_eq": 0},
     "Scan the site for malicious code via Safe Browsing")
item(115, "medium", S, "security_headers.py", PAGE,
     {"path": "header_values.strict-transport-security", "truthy": True},
     "Enable HSTS")
item(116, "critical", S, "domain_safety_check.py", PAGE,
     {"path": "safe_browsing.threats", "len_eq": 0},
     "Confirm there is no hacked content or malware")
item(117, "critical", S, "security_headers.py", PAGE,
     {"path": "https", "truthy": True},
     "Force HTTPS sitewide with a single canonical protocol")
# SE-118 asserted `https` — SE-117's field, from SE-117's script — until 0.20, so two
# `critical` items shared one assertion and this one could not fail independently on any
# site. A certificate that expired yesterday passed it, because the URL still began
# `https`. `tls_certificate.py` does a verifying handshake instead: expiry, trust chain
# and hostname are the library's verdict rather than a scheme string, and `valid` is only
# ever True after one succeeded.
item(118, "critical", S, "tls_certificate.py", PAGE,
     {"path": "valid", "truthy": True},
     "Maintain a valid TLS certificate — unexpired, trusted, issued for this hostname")
item(119, "medium", S, "pagespeed.py", ["{url}", "--strategy", "mobile"],
     RATING("CLS"),
     "The cookie banner must not cause layout shift", warn=RATING_WARN("CLS"))
item(120, "medium", S, "security_headers.py", PAGE,
     {"path": "score", "gte": 80},
     "Configure CSP, Permissions-Policy and Referrer-Policy")

# --- 9. International -------------------------------------------------------
item(121, "medium", S, "hreflang_checker.py", PAGE,
     {"path": "checks.x_default.passed", "truthy": True},
     "Configure geo-targeting signals, including x-default")
item(122, "high", S, "hreflang_checker.py", PAGE,
     {"path": "checks.return_tags.verified_and_valid", "truthy": True},
     "Valid hreflang with return tags")
item(123, "medium", S, "parse_html.py", HTMLARG,
     {"path": "lang", "truthy": True},
     "Declare the page language in html lang")
# redirect_checker.py reports loops, chains and missing Location headers. A
# forced geo redirect only shows itself to a request from another country, which
# no single fetch from one machine can produce — so this is a human with a VPN,
# not a script and not a language model reading one page.
item(124, "medium", M, fix="Do not force geo or language redirects")
item(125, "low", M, fix="Define target international markets and audiences")
item(126, "medium", L, fix="Translations must be high quality and human-reviewed")
# Reads the structure it is named for. It asserted `checks.protocol_consistency.passed`
# — whether the hreflang set mixes http and https — a real defect under the wrong
# title, which a site running every locale on `?lang=` passed.
#
# `check_url_structure` classifies the set as ccTLD, subdomain, subdirectory,
# parameter, mixed or single, and grades the last three: parameter and mixed fail,
# single carries no `passed` key at all, so a page with one alternate is NO_DATA rather
# than credited with a structure it does not have. Protocol consistency stays in the
# output and in the severity tally; no item asserts it now, and an ungraded signal is
# the smaller problem — see KNOWN-ISSUES §6.
item(127, "medium", S, "hreflang_checker.py", PAGE,
     {"path": "checks.url_structure.passed", "truthy": True},
     "Put every locale on one of the three structures Google supports — "
     "subdirectories (/de/), subdomains (de.example.com) or country-code domains "
     "(example.de) — not on a URL parameter and not on a mixture")
item(128, "medium", S, "hreflang_checker.py", PAGE,
     {"path": "checks.self_reference.passed", "truthy": True},
     "Serve the correct localized page")
item(129, "low", M, fix="Earn local backlinks in target markets")
item(130, "low", L, fix="Clarify the site type: multilingual, multiregional, or both")

# --- 10. Google -------------------------------------------------------------
item(131, "medium", S, "ga4_tag_checker.py", PAGE,
     {"path": "measurement_ids", "len_gte": 1},
     "Install and configure Google Analytics 4")
item(132, "medium", S, "ga4_tag_checker.py", PAGE,
     {"path": "duplicates", "len_eq": 0},
     "Remove duplicate GA4/GTM tags")
item(133, "high", M, fix="Set up Google Search Console as a domain property")
# `opportunities` was the wrong field to read. "Position 4.0 with 115 impressions —
# within striking distance" is the site's best result, and a severity gate printed it as
# the first thing a client should fix. No calibration of those thresholds could have
# repaired that: an opportunity is not a defect at any number, so the defect was the
# field, not the numbers in it. `issues` is what Search Console reports as *broken* —
# errors and warnings against a submitted sitemap, the only such report the API exposes
# (manual actions, Index Coverage and mobile usability have no endpoint, which is why
# GO-141, GO-142 and MB-099 are MANUAL). The opportunities did not lose their home: the
# report carries them outside the score and outside the fix list, because they are work
# without being failure.
item(134, "high", S, "gsc_checker.py", GSCARG,
     ISSUES_ANY(),
     "Resolve what Search Console reports as broken: errors against a submitted sitemap",
     warn=NOTHING_SERIOUS())
item(135, "medium", S, "gsc_url_inspection.py", INSPECTARG,
     {"path": "issues", "none_severity": ["critical", "high"]},
     "Resolve what URL Inspection reports: blocked indexing, failed fetch, or a "
     "coverage state that keeps the page out of the index")
item(136, "high", S, "sitemap_checker.py", PAGE,
     ISSUES_ANY(),
     "Keep XML sitemaps clean", warn=NOTHING_SERIOUS())
item(137, "medium", S, "orphan_pages_from_sitemap.py", CRAWLARG,
     {"path": "summary.orphan_pages", "eq": 0},
     "Reconcile indexed pages against sitemap contents",
     {"path": "summary.orphan_pages", "lte": 50})
# `--fetch-urls`, without which this item could only ever pass. The 404, redirect and
# noindex issues its pattern looks for are emitted only when sitemap_checker actually
# requests the URLs it found, and nothing asked it to — so "remove invalid URLs from
# sitemaps" reported PASS for a sitemap made entirely of dead links. It was hidden
# behind a second bug: the phantom "Sitemap returned HTTP 404" from probing
# conventional filenames matched the same pattern, so the item read FAIL everywhere
# for a reason that had nothing to do with the sitemap's contents. Fixing that
# revealed this. Capped at 25 URLs: enough to find dead entries, not a second crawl.
item(138, "medium", S, "sitemap_checker.py",
     ["{url}", "--fetch-urls", "--max-urls", "25"],
     # `field` is not optional here, and 0.19.0 is the third time this tree has
     # learned it. Without it the pattern is matched against the whole serialised
     # issue — `severity`, `message`, `url`, `evidence` — so "404" hit the *port* of
     # a test origin that bound 40455 and reported a clean sitemap as full of dead
     # URLs. On a real site `/blog/404-errors-explained` in a sitemap does the same
     # thing. The soft-404 guard in the runner already carries this lesson in
     # writing ("Never a substring: `404` appears in the title of every article ever
     # written about broken links") and the keyword items learned it in 0.5.0; the
     # rules were never audited for it.
     # Replaced by the count in 0.93.0, and the pattern was narrower than every
     # reading of it: the message is "Sitemap URL returns HTTP {status}", so `404`
     # matched a 404 and nothing else. A sitemap whose URLs returned 500 or 503
     # passed this item outright. `invalid_url_count` is status >= 400, a redirect
     # chain, or meta noindex, over the URLs actually read.
     {"path": "invalid_url_count", "eq": 0},
     "Remove invalid URLs from sitemaps")
item(139, "low", S, "gsc_cannibalization.py", GSCARG,
     {"path": "branded.ranks_first", "truthy": True},
     "Monitor and improve the brand SERP")
item(140, "low", M, fix="Add a Google News sitemap if the site qualifies")
item(141, "critical", G, fix="Check for manual actions in Search Console")
item(142, "high", G, fix="Resolve crawl and indexing issues")
item(143, "low", S, "schema_required_props.py", PAGE,
     # Scoped for the same reason as GO-138, and this one was waiting to fire on
     # any site with `/website-design` in a URL the checker reported on.
     #
     # `SearchAction` left the pattern in 0.89.0, and not because it was dead. The
     # first draft of this comment said it could only reach a message as a `WebSite`'s
     # missing `potentialAction`; that was wrong twice. The message for a missing
     # recommended property reads "WebSite is missing recommended property
     # 'potentialAction'" and contains neither the word `SearchAction` nor anything
     # matching it. And the placeholder branch names *any* node's type, whether or not
     # that type has a property table — so a `SearchAction` carrying `REPLACE_ME` in
     # its target emitted "SearchAction property 'target' appears to contain
     # placeholder text", which the old pattern matched and the new one does not.
     #
     # It is removed anyway, deliberately: a placeholder inside search markup is not a
     # fact about the site name, and this item is now titled for the site name. An
     # assertion that fires on something its title does not name is the defect this
     # release exists to fix, and keeping the alternative would have re-created it one
     # line below the repair. What left with it is recorded rather than dropped —
     # placeholder text in structured data is a warning, and `MS-032` reaches it only
     # above three warnings. See KNOWN-ISSUES, "placeholder text in structured data".
     # 0.93.0 moved the same question off the message and onto the count. The map
     # carries one entry per schema type present, so an absent key means the page has
     # no `WebSite` node at all — which is what `missing_is: pass` preserves, exactly
     # as the pattern did by matching nothing.
     {"path": "incomplete_nodes_by_type.WebSite", "eq": 0, "missing_is": "pass"},
     "Give the WebSite node a name and a url; Google reads both for the site name "
     "shown in results")
# 32 is one direct answer (20) plus one definition (12) — the two strongest of the four
# signals answer_block_scanner scores, the one a snippet can be lifted from verbatim and
# the one that says what the subject is. Unlike item 68's, this derivation is not about
# page types: all four signals are content-structure signals and none of them belongs to
# an article the way a credential marker does. It is the level a page that structures its
# content at all reaches.
#
# At 70 the item needed at least four signals, because the three strongest sum to 60;
# the cheapest four are three direct answers and a list, which is an FAQ page, asked of
# every sampled page including a privacy policy.
#
# And a floor is a number rather than a requirement: four lists reach 40 and clear this
# without a direct answer anywhere. The derivation says where the line sits, not which
# signals a page must carry. GEO-004 is its twin and carries the same floor.
item(144, "medium", S, "answer_block_scanner.py", PAGE,
     {"path": "score", "gte": 32},
     "Optimize for featured snippets: direct answers, lists, tables")
# 25 is author (15) plus canonical (10) — the two components of citation_readiness's
# score that any page type can carry. Claim coverage (35), trusted links (20) and
# sameAs (20) are article and entity signals. GEO-005 is its twin and carries the same
# floor.
item(145, "high", S, "citation_readiness.py", PAGE,
     {"path": "score", "gte": 25},
     "Optimize for AI Overviews and zero-click: citability, facts, sources")

# --- 11. Website Architecture ----------------------------------------------
# The mirror image of CN-055's defect. This asserted `pagination` was truthy, and
# `pagination` is a dict that always contains both keys — `{"prev": None, "next":
# None}` is a *non-empty dict*, so it is truthy on every page in existence and the
# item could not fail. Its exemption in the contract pair said "neither fixture
# paginates", which is true and was not the reason it passed.
#
# What is checkable without judgement: a `rel=next` or `rel=prev` that points at
# another host, or at the page itself. A page with no pagination has no pagination
# defect, so it passes — that is the honest answer rather than a manufactured one.
item(146, "medium", S, "parse_html.py", HTMLARG,
     NOTHING_SERIOUS("pagination.issues"),
     "Fix rel=next/prev: same host, and never pointing at the page itself")
item(147, "medium", S, "url_quality.py", PAGE,
     {"path": "rows.0.param_count", "lte": 2},
     "Short descriptive URLs without excess parameters")
item(148, "low", M, fix="Visualize the site architecture")
# This asserted `pages` was non-empty — satisfied by any site that answers at all,
# so an item titled "Eliminate Internal Redirects" could not fail, and its exemption
# in the contract pair blamed a fixture that "does not redirect" for a rule that
# never looked. It also hid a real defect for a release: `internal_links.py` set
# `fetch_error` unconditionally, so the item was NO_DATA everywhere, and "same on
# both fixtures" stayed true through the change.
#
# The shared crawl records where every internal target actually landed, so the item
# can now be asked its own question. `warn` because a redirected internal link is a
# wasted hop rather than a broken page: three is untidy, thirty is a migration nobody
# finished.
item(149, "medium", S, "internal_links.py", CRAWLARG,
     {"path": "summary.internal_redirects", "eq": 0},
     "Point internal links at the final URL instead of a redirect",
     warn={"path": "summary.internal_redirects", "lte": 3})
item(150, "high", S, "redirect_checker.py", PAGE,
     {"path": "total_hops", "lte": 1},
     "Remove redirect chains and loops")
# robots_checker.py appends plain strings to `issues`, never dicts, so no severity
# rule can read them and this item passed on every site ever audited. What it can
# answer structurally is the item's own verb — *provide* a robots.txt: `status` is
# 200 when one exists, 404 when it does not, and absent when the request itself
# failed, which is NO_DATA rather than a verdict. The Sitemap directive and the
# per-agent rules are already AR-152 and item 6.
item(151, "high", S, "robots_checker.py", PAGE,
     {"path": "status", "eq": 200},
     "Correct robots.txt")
item(152, "medium", S, "robots_checker.py", PAGE,
     {"path": "user_agents", "truthy": True},
     "Block low-value sections from crawling deliberately")
item(153, "medium", S, "topical_cluster_mapper.py", PAGE,
     {"path": "score", "gte": 70},
     "Build topic hubs (silos)")
item(154, "medium", S, "collection_page_checker.py", PAGE,
     ISSUES_ANY(),
     "Optimize e-commerce category pages", warn=NOTHING_SERIOUS())
item(155, "low", S, "url_quality.py", PAGE,
     {"path": "rows.0.flags", "len_eq": 0},
     "Consistent, descriptive URL slugs")
item(156, "medium", M, fix="Helpful 404 page with navigation and search")
item(157, "low", L, fix="Use tag pages deliberately rather than generating duplicates")
item(158, "medium", S, "parse_html.py", HTMLARG,
     {"path": "breadcrumbs", "eq": {"schema": True, "ui": True}},
     "Breadcrumbs in the UI and as BreadcrumbList markup")
item(159, "low", L, fix="Simplify primary navigation")
item(160, "low", L, fix="Optimize footer navigation")
item(161, "medium", L, fix="Clear header and mobile menus")
item(162, "high", S, "link_profile.py", CRAWLARG,
     {"path": "issues", "none_severity": ["critical", "high", "medium"]},
     "Strengthen internal linking, remove orphans")
# `--from-page`, not the bare URL. A crawl trap is a property of a set of URLs —
# five parameter variants on one path, or a parameter recurring across many — so
# handing this script the entry URL alone made the item unable to fail on any site:
# one URL yields one path and each parameter counted once, and both thresholds need
# more. With the flag it audits the internal links of the page, which is also the
# truer question, since a facet becomes a trap when the site links to it.
#
# `--fetch` for the same reason, added in 0.50.0. The fix text has always said
# "canonical, noindex, robots", and those three are exactly what the script declines
# to look at without the flag: `facet_missing_canonical` and `facet_not_noindexed`
# are computed inside `if fetch:` and were never reached, so the item graded a
# parameter count and called it faceted-navigation control. Grading the uncontrolled
# facet without passing this would have been worse than leaving it alone — the
# reachability gate reads severity literals, so a finding that exists and can never
# run would have silenced the gate while changing nothing.
item(163, "medium", S, "faceted_nav_audit.py", ["{url}", "--from-page", "--fetch"],
     ISSUES_ANY(),
     "Control faceted navigation: canonical, noindex, robots", warn=NOTHING_SERIOUS())
item(164, "medium", M, fix="Handle out-of-stock products via 301/410 plus clear UX")

# --- 12. Technical SEO Checks ----------------------------------------------
item(165, "low", L, fix="Choose subdomains or subdirectories deliberately")
item(166, "low", S, "parse_html.py", HTMLARG,
     {"path": "favicon", "truthy": True},
     "Add a favicon")
item(167, "medium", S, "domain_safety_check.py", PAGE,
     {"path": "uptime.reachable", "truthy": True},
     "Set up uptime monitoring")
item(168, "high", S, "broken_links.py", CRAWLARG,
     {"path": "summary.broken_or_redirected", "eq": 0},
     "Fix broken and redirected links",
     {"path": "summary.broken", "lte": 3})
item(169, "high", S, "javascript_render_audit.py", PAGE,
     {"path": "raw.internal_link_count", "gte": 1},
     "Put internal links in the served HTML so a crawler has somewhere to go before JavaScript runs")
item(170, "medium", S, "cache_compression_checker.py", PAGE,
     ISSUES_ANY(),
     "Configure server rewrites and cache/compression headers", warn=NOTHING_SERIOUS())
item(171, "critical", S, "domain_safety_check.py", PAGE,
     {"path": "safe_browsing.threats", "len_eq": 0},
     "Check the domain against blocklists and Safe Browsing")
item(172, "high", S, "rich_results_guard.py", PAGE,
     {"path": "summary.errors", "eq": 0},
     "Implement structured data correctly, JSON-LD only")
item(173, "medium", M, fix="Fix browser console errors (chrome-devtools MCP: list_console_messages)")
item(174, "low", S, "css_minify_check.py", PAGE,
     {"path": "unminified_count", "eq": 0},
     "Minify and optimize CSS")
# security_headers.py also emits `issues` as strings — it was printing "Site not
# using HTTPS" and "6 security headers missing" while this item reported PASS. Its
# `headers_missing` is a dict of the security headers absent from the response, so
# the rule uses the script's own bar for "poor security posture": more than three
# of the six missing. HTTPS itself is SE-117/SE-118, so this item owns the headers.
item(175, "high", S, "security_headers.py", PAGE,
     {"path": "headers_missing", "len_lte": 3},
     "Secure pages and eliminate errors")
item(176, "high", S, "canonical_checker.py", PAGE,
     {"path": "issues", "len_eq": 0},
     "Fix canonicalization issues")
item(177, "medium", S, "javascript_render_audit.py", PAGE,
     {"path": "raw.title", "truthy": True},
     "Put the page title in the served HTML, not only in what JavaScript builds")
item(178, "low", S, "domain_safety_check.py", PAGE,
     {"path": "neighbors.suspicious", "len_eq": 0},
     "Audit neighboring sites on the same server IP")
# 0.44 deliberately reverses 0.21's TE-179 ruling. That ruling correctly objected that
# age is neither a full registration history nor reputation, and that a FAIL whose only
# remedy is waiting pollutes a prioritised fix list. The decision changes because
# reputation remains asserted three times by SE-114, SE-116 and TE-171 while no other
# item measures even one domain-history fact; this scalar now costs only a WARN — half
# of one low-severity point — rather than a FAIL.
#
# `lt 90` is the exact complement of `gte 90`, so FAIL is unreachable on purpose; no
# gate checks numeric reachability, which makes that choice important to record here.
# An absent age remains NO_DATA because the runner consults `warn` only after a false
# assertion. Removing TE-179's per-item credential restores the script's `api` requires,
# keeping whois unavailable on loopback and the item outside the fixture-decidable set.
#
# GO-134's `opportunity_section` remains the right precedent for a list of findings with
# no item to attach to. Domain age is a single scalar with an item already named for it;
# routing it to prose would leave that row asking for an unrelated Safe Browsing key while
# a later section reported the age. The item should say what its own evidence measured.
item(179, "low", S, "domain_safety_check.py", PAGE,
     {"path": "whois.age_days", "gte": 90},
     "A young domain is a fact to plan around, not a defect: expect slower trust "
     "accumulation and no quick ranking wins. Check a domain's registration history "
     "before buying it.",
     warn={"path": "whois.age_days", "lt": 90})
item(180, "medium", S, "a11y_seo_checker.py", PAGE,
     {"path": "score", "gte": 80},
     "Meet WCAG accessibility basics")
# CI-017 validates the bytes Nu fetches from the server; TE-181 validates the DOM a
# browser builds after scripts run. Those are two documents that can independently be
# valid or invalid, so the pair now carries 6 weight points rather than 3. Unlike the
# rejected MD-189 conjunction, this does not charge one fact twice: it measures two
# different facts.
#
# The DOM comes from the same rendered-page artifact `rendered_audit.py` reads, not
# from a browser launched mid-audit. A browser inside the run fetches the page and its
# subresources again, behind the response cache: measured on the fixture site that took
# one audit from 22 requests to 31 and asked for the entry URL three times, which the
# CI request-discipline step exists to forbid. Without the artifact the placeholder is
# unresolved and the item reports NEEDS_INPUT; with an artifact that recorded no
# document, `summary` is omitted and it reports NO_DATA. Neither passes a DOM nobody
# built.
item(181, "medium", S, "html_validator.py",
     ["{url}", "--rendered-json", "{rendered_json}"],
     {"path": "summary.errors", "eq": 0},
     "Fix W3C validation errors in the rendered DOM")
item(182, "low", M, fix="Show a compliant cookie banner")
item(183, "high", M, fix="Handle migrations, parameters and status codes correctly")

# --- 13. Images / Video -----------------------------------------------------
item(184, "medium", S, "image_inventory.py", PAGE,
     {"path": "count", "gte": 1},
     "Reference at least one image with a src in the served HTML")
# `--fetch-images` since 0.50.0, and the band is why. Grading the lazy LCP candidate
# `error` left `Large image transfer size` as the only `warning` this script can raise,
# and it reads `content_length`, which `_local_size` returns `None` for over http —
# so on a live site nothing medium could happen and the warn band promised a middle
# verdict no site could reach. The item is *Optimize Images*: weight is its subject,
# measuring bytes is what makes the middle verdict real rather than decorative.
# MD-185 therefore pays for its own sampled-page HEAD requests; MD-187 separately
# pays for its bounded site-wide sweep.
item(185, "medium", S, "image_weight_audit.py", ["{url}", "--fetch-images"],
     ISSUES_ANY(),
     "Optimize images", warn=NOTHING_SERIOUS())
item(186, "high", S, "image_inventory.py", PAGE,
     {"path": "missing_alt", "eq": 0},
     "Meaningful alt text on informative images")
item(187, "high", S, "image_weight_audit.py",
     # Broken images cannot be found without asking for each distinct URL, so this
     # item pays for the bounded site-wide HEAD sweep. `broken_image_count` is absent
     # when no usable result was collected, which the runner reads as NO_DATA rather
     # than "none broken".
     CRAWLARG,
     {"path": "broken_image_count", "eq": 0},
     "Fix broken images")
item(188, "low", L, fix="Use original contextual images, limit stock photography")
# MD-189 names two halves which MB-096 and MB-097 measure separately. It takes
# the responsive half and defers to MB-096 so that one fact is charged once. A
# conjunction was rejected: it would raise this theme from 6 to 9 weight points
# and make one missing-modern-format defect fail both MD-189 and MB-097.
item(189, "medium", S, "image_weight_audit.py", PAGE,
     {"path": "responsive_count", "gte": 1},
     "Modern formats and responsive images")
item(190, "medium", S, "video_schema_checker.py", PAGE,
     ISSUES_ANY(),
     "Implement video SEO essentials: VideoObject, thumbnail, transcript", warn=NOTHING_SERIOUS())

# --- 14. Competition --------------------------------------------------------
item(191, "medium", L, fix="Identify the top 3-5 competitors in the SERP")
item(192, "medium", M, fix="Benchmark yourself against competitors on key metrics")
item(193, "medium", M, fix="Document each competitor's top 10 keywords")
item(194, "low", M, fix="Track competitors' average positions")
item(195, "medium", M, fix="List top-ranking keywords across all players")

# --- 15. Local SEO ----------------------------------------------------------
item(196, "medium", L, fix="Determine whether the site needs local traffic")
# local_seo_checker.py reports LocalBusiness schema, map embeds, review links
# and phone consistency — never the title tag. Whether a title is localised for
# its city and service is a market judgement.
item(197, "medium", L, fix="Localized title tags")
item(198, "high", S, "local_seo_checker.py", CRAWLARG,
     {"path": "local_business_nodes", "gte": 1},
     "Implement LocalBusiness structured data")
item(199, "high", M, fix="Create and optimize the Google Business Profile — follow resources/playbooks/local-seo.md")
item(200, "high", S, "local_seo_checker.py", PAGE,
     {"path": "nap_complete", "truthy": True},
     "Complete name, address and telephone on every LocalBusiness structured-data node")

# --------------------------------------------------------------------------
# Beyond Plerdy — what the toolkit checks that the 200-point list does not.
# --------------------------------------------------------------------------

EXTRA = [
    ("GEO-001", "geo_ai", "llms.txt present and well-formed", "high", S,
     "llms_txt_checker.py", PAGE, {"path": "exists", "truthy": True},
     "Publish /llms.txt describing the site and mapping its key sections"),
    ("GEO-002", "geo_ai", "llms.txt quality score", "medium", S,
     "llms_txt_checker.py", PAGE, {"path": "quality.score", "gte": 60},
     "Flesh out llms.txt: title, description, sections, links"),
    ("GEO-003", "geo_ai", "AI crawler policy is explicit", "medium", S,
     "ai_crawler_policy_matrix.py", PAGE,
     # The matrix reports an `alignment` per crawler and never the words "not
     # managed". Allowing everything while publishing no llms.txt is precisely
     # the policy this item calls inexplicit.
     {"path": "rows", "field": "alignment",
      "value_map": {"documented": "pass", "robots_only": "pass",
                    "allowed_without_llms_txt": "fail"}},
     "Declare per-token rules for training, answer retrieval and ad review. Treat "
     "ClaudeBot as training; handle Claude-User and Claude-SearchBot separately. "
     "PerplexityBot feeds search, while Perplexity-User generally ignores robots.txt. "
     "Google-Extended covers Gemini training and grounding, not AI Overviews or AI "
     "Mode. Applebot-Extended controls training; Applebot answer use follows "
     "nosnippet"),
    # The floor moves with its twin GO-144; the derivation is written there.
    ("GEO-004", "geo_ai", "Answer blocks present for AEO", "medium", S,
     "answer_block_scanner.py", PAGE, {"path": "score", "gte": 32},
     "Add direct answers, definitions, lists and tables for featured snippets"),
    # The floor moves with its twin GO-145; the derivation is written there.
    ("GEO-005", "geo_ai", "Content is citation-ready for AI search", "high", S,
     "citation_readiness.py", PAGE, {"path": "score", "gte": 25},
     "Back factual claims with sources, add cite/blockquote, populate sameAs"),
    ("GEO-006", "geo_ai", "Entity is resolvable (Wikidata / KG)", "medium", S,
     "entity_checker.py", PAGE, {"path": "summary.sameas_missing_critical", "eq": 0},
     "Populate sameAs with key profiles and establish a Wikidata link"),
    ("GEO-007", "geo_ai", "IndexNow configured", "low", S,
     "indexnow_checker.py", ["{url}", "--key", "{indexnow_key}"],
     {"path": "key_valid", "truthy": True},
     "Configure IndexNow for instant reindexing in Bing/Yandex"),
    # Stated as the desired state, like every other title in this registry: the item
    # reads PASS as "the title is true of this page". Phrased as the failure instead —
    # "this page is restricted…" — a PASS would assert the opposite of what it found.
    # Full availability passes, a limited snippet warns, and total suppression fails.
    ("GEO-008", "geo_ai",
     "Snippet directives leave the page usable in AI answers and result snippets",
     "medium", S, "indexability_matrix.py", PAGE,
     {"path": "rows.0.snippet_controls.snippet_availability",
      "value_map": {"full": "pass", "limited": "fail", "suppressed": "fail"}},
     "Review the reported nosnippet, max-snippet or data-nosnippet source. The same "
     "directive restricts Google's AI answers and ordinary result snippets; there is "
     "no setting that separates them",
     {"path": "rows.0.snippet_controls.snippet_availability",
      "value_map": {"full": "pass", "limited": "pass", "suppressed": "fail"}}),
    ("TECH-001", "technical", "Modern schema types only (no HowTo/FAQ misuse)", "high", S,
     "rich_results_guard.py", PAGE, {"path": "summary.warnings", "eq": 0},
     "Remove HowTo (deprecated) and FAQPage outside gov/health sites"),
    ("TECH-002", "technical", "Font loading does not block render", "low", S,
     "font_audit.py", PAGE, ISSUES_ANY(),
     "Preload key fonts, use font-display: swap", NOTHING_SERIOUS()),
    ("TECH-003", "technical", "LCP subparts within budget", "medium", S,
     "lcp_subparts.py", PAGE, {"path": "subparts.ttfb_ms", "lte": 800},
     "Reduce TTFB and LCP resource load delay"),
    ("CONT-001", "content", "No content decay on key pages", "medium", M,
     None, None, None,
     "Track pages losing traffic (requires a GSC export)"),
    # Lab Core Web Vitals from a local browser trace, kept apart from the CrUX
    # field data pagespeed.py reports (SP-108, SP-113). Field data is the better
    # evidence and wins whenever it exists — it just does not exist for
    # low-traffic URLs, which is when a controlled run is the only measurement
    # available. One number made out of both claims is the conflation this
    # registry refuses. Without --cwv-json the file placeholder is unresolved and
    # all three report NO_DATA with that as the reason.
    ("SP-214", "speed", "LCP within budget in a local trace (lab)", "medium", S,
     "cwv_metrics.py", ["{cwv_json}"], {"path": "lcp_ms", "lte": 2500},
     "Reduce the largest contentful paint below 2.5s: server response, render-blocking "
     "resources, image weight"),
    ("SP-215", "speed", "CLS within budget in a local trace (lab)", "medium", S,
     "cwv_metrics.py", ["{cwv_json}"], {"path": "cls", "lte": 0.1},
     "Reserve space for images, ads and embeds; avoid inserting content above existing "
     "content"),
    ("SP-216", "speed", "Main thread not blocked in a local trace (TBT, lab proxy for INP)",
     "medium", S, "cwv_metrics.py", ["{cwv_json}"], {"path": "tbt_ms", "lte": 200},
     "Break up long tasks and defer third-party JavaScript. INP needs a real "
     "interaction and cannot be measured from a page load, so TBT stands in for it"),
    # The two mobile-layout measures owed since 0.62.0, when 0.61.0 deleted the
    # Playwright branch that took them. Same shape as the three lab-vitals items
    # above: an operator-supplied artifact, so without `--rendered-json` both report
    # NEEDS_INPUT rather than a verdict. `MB-093` keeps its own check — a declared
    # viewport is an HTML fact and cannot be read from a render — so nothing existing
    # loses coverage to these.
    #
    # `lte 1` and not `eq 0`: `scrollWidth` and `innerWidth` are integers, and the
    # branch these definitions come from compared `scrollWidth > innerWidth + 1`. One
    # pixel of rounding is not a page that scrolls sideways.
    ("MB-107", "mobile", "Page fits the phone viewport without horizontal scrolling",
     "high", S, "rendered_audit.py", RENDERED,
     {"path": "horizontal_overflow_px", "lte": 1},
     "Constrain what is wider than the screen at a phone width — media, tables, "
     "navigation and code blocks are the usual four"),
    ("MB-108", "mobile", "Text is not clipped or cut off at a phone width",
     "medium", S, "rendered_audit.py", RENDERED,
     {"path": "text_nodes_clipped", "eq": 0},
     "Let headings, paragraphs, links, buttons and list items wrap instead of "
     "overflowing their box; a deliberate ellipsis counts here too, so give the text "
     "room rather than hiding the overflow"),
]


def load_titles() -> dict[int, str]:
    """Read item titles from the extracted Plerdy checklist titles file.

    Keys that are not item numbers are metadata — `_source` records where the 200
    titles came from, which the file has to carry itself: it is the basis of the
    contract, and provenance kept only in CREDITS.md is provenance that walks away
    the first time the file is copied."""
    path = os.path.join(SKILL_DIR, "resources", "config", "plerdy-titles.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    return {int(k): v for k, v in raw.items() if k.lstrip("-").isdigit()}


def load_title_overrides() -> dict[str, dict]:
    """Read deliberate departures from borrowed Plerdy titles.

    Underscore-prefixed keys are metadata, just as they are in the source title
    file. Validation happens after the complete item list exists, so a typo cannot
    silently create an override that reaches no item.
    """
    if not os.path.exists(TITLE_OVERRIDES):
        return {}
    with open(TITLE_OVERRIDES, encoding="utf-8") as f:
        raw = json.load(f)
    return {key: value for key, value in raw.items() if not key.startswith("_")}


def title_override_problems(items: list[dict], titles: dict[int, str],
                            overrides: dict[str, dict]) -> list[str]:
    """Name every override that cannot be a meaningful source-title departure."""
    known = {item["id"]: item for item in items}
    problems = []
    for item_id, override in overrides.items():
        item = known.get(item_id)
        if item is None:
            problems.append(f"{item_id}: no registry item has this id")
            continue
        if item["plerdy_ref"] is None:
            problems.append(f"{item_id}: item has no Plerdy source title to override")
            continue
        title = override.get("title") if isinstance(override, dict) else None
        why = override.get("why") if isinstance(override, dict) else None
        if not str(title or "").strip():
            problems.append(f"{item_id}: override title is blank")
        if not str(why or "").strip():
            problems.append(f"{item_id}: override reason is blank")
        if title == titles.get(item["plerdy_ref"]):
            problems.append(f"{item_id}: override title matches its Plerdy source title")
    return problems


# Which evidence answers an LLM item, which is not the same question as which
# checklist category it sits in. Grouping by lens lets one agent read one slice
# of the page once; grouping by category would make four agents re-read the same
# body copy. Every llm item must appear here — main() refuses to build otherwise,
# so a new item cannot silently fall out of the dispatch.
LENS = {
    "copy": ["MS-024", "MS-025", "MS-027", "CN-037", "CN-042", "CN-043", "CN-046",
             "CN-047", "CN-049", "CN-050", "CN-058", "CN-064", "CN-067",
             "KW-072", "KW-073", "KW-074", "KW-075", "KW-077", "MD-188"],
    "layout": ["CN-052", "CN-053", "CN-055", "CN-059", "CN-060", "CN-061", "CN-062",
               "CN-063", "MB-101", "AR-157", "AR-159", "AR-160", "AR-161"],
    # TE-165 (subdomain vs subdirectory) is filed under technical, but the
    # decision is almost always driven by language/region targeting.
    "locale": ["IN-126", "IN-130", "TE-165"],
    "market": ["CO-191", "LO-196", "LO-197"],
}
LENS_OF = {eid: lens for lens, ids in LENS.items() for eid in ids}


# Pairs that run one script with one set of arguments and one assertion, because the
# two source checklists merged here asked the same question twice. The key is the item
# that keeps the weight; the value is the twin that stops carrying it. Both still run
# and both still report a status — a reader looking up either source title should find
# an answer — but the score counts the check once.
#
# Two harms, and the second is the reason this is not merely tidy. A single defect
# pulled the headline down twice. And where the twins disagree on severity — MB-102
# `low` against MD-190 `medium` — the weight of one defect depended on which of them
# the reader happened to look at. The survivor is the one with the higher severity, so
# nothing is quietly downgraded; where they tie, the lower id keeps it.
#
# Deliberately not on this list: pairs that *look* like synonyms but are two
# requirements sharing one assertion because the second was never written. Those are
# defects, not duplicates, and 0.22 repaired the two it had — MS-027/MS-028 and
# MS-029/CN-041. Adding a pair here is a claim that one check genuinely answers both
# titles; check that before you do it.
#
# MB-104 left the TE-166 group in 0.44. Its new checker fetches and measures the
# declared icon, so "displays in mobile SERPs" and "declares a favicon" are no longer
# one check; MB-104 runs and scores independently.
SAME_CHECK = {
    "CI-016": "MD-186",   # "Provide Meaningful Image Alt Text" / "...Alt Text"
    "GO-144": "GEO-004",  # featured snippets / answer blocks for AEO
    "GO-145": "GEO-005",  # AI Overviews / citation-ready content
    "MB-096": "MD-189",   # both medium; MB-096's title exactly names this assertion
    "MD-190": "MB-102",   # video SEO (medium) over "Optimize Video for Mobile" (low)
    # One Safe Browsing response, expressed three ways in the source checklists.
    # All three read the same threats list. The critical pair ties on severity, so
    # the lower id SE-114 carries the weight; SE-116 and TE-171 are twins of that
    # same primary, never a chain. TE-179 left this group in 0.44 to measure the
    # otherwise-uncovered domain-history half of its title through whois age.
    "SE-114": ["SE-116", "TE-171"],
    # Three entries for one measurement, and the registry asked the question three times
    # because the source checklists did. SP-108 *Pass Core Web Vitals (Field Data)* is the
    # one that says what it measures; SP-112 asks it again per device and SP-113 asks it
    # again by name. All three now read `field_cwv.verdict` from the same mobile call, so
    # the plan runs it once and the score counts it once. Both twins keep their status and
    # their own title: a reader looking up "Meet Core Web Vitals Thresholds" gets an
    # answer. Severity ties at `critical` and the lower id keeps the weight, which is
    # SP-108 either way.
    "SP-108": ["SP-112", "SP-113"],
}
# A primary may carry more than one twin: `str` for the pairs, `list` for a group.
SCORES_WITH = {twin: primary
               for primary, twins in SAME_CHECK.items()
               for twin in ([twins] if isinstance(twins, str) else twins)}


def build(titles: dict[int, str] | None = None,
          overrides: dict[str, dict] | None = None) -> list[dict]:
    titles = load_titles() if titles is None else titles
    overrides = load_title_overrides() if overrides is None else overrides
    out: list[dict] = []
    for key, prefix, label, (lo, hi) in CATEGORIES:
        for ref in range(lo, hi + 1):
            sev, source, script, args, rule, fix, warn = MAP.get(
                ref, ("medium", M, None, None, None, "", None))
            item_id = f"{prefix}-{ref:03d}"
            override = overrides.get(item_id)
            title = titles.get(ref, f"Item {ref}")
            if isinstance(override, dict):
                title = override.get("title", title)
            entry = {
                "id": item_id,
                "plerdy_ref": ref,
                "category": key,
                "category_label": label,
                "title": title,
                "severity": sev,
                "source": source,
            }
            if source == S:
                entry["check"] = {
                    "script": script,
                    "args": args,
                    "requires": ITEM_REQUIRES.get(
                        item_id, REQUIRES.get(script, DEFAULT_REQUIRES)),
                    "assert": rule,
                }
                if item_id in APPLIES_WHEN:
                    entry["check"]["applies_when"] = APPLIES_WHEN[item_id]
                if warn:
                    entry["check"]["warn"] = warn
                if item_id in CANNOT_FAIL:
                    entry["check"]["cannot_fail"] = CANNOT_FAIL[item_id]
            if source == L:
                entry["lens"] = LENS_OF.get(entry["id"], "")
            entry["effort"] = effort_for(entry)
            entry["fix"] = fix
            if entry["id"] in SCORES_WITH:
                entry["scores_with"] = SCORES_WITH[entry["id"]]
            out.append(entry)

    for row in EXTRA:
        # An optional tenth element is a `warn` rule, so an entry here can
        # separate "a warning" from "a failure" the way item() can.
        eid, cat, title, sev, source, script, args, rule, fix = row[:9]
        warn = row[9] if len(row) > 9 else None
        label = "GEO / AI Search" if cat == "geo_ai" else next(
            (known for k, _p, known, _r in CATEGORIES if k == cat), "Beyond Plerdy")
        entry = {
            "id": eid,
            "plerdy_ref": None,
            "category": cat,
            "category_label": label,
            "title": title,
            "severity": sev,
            "source": source,
        }
        if source == S:
            entry["check"] = {
                "script": script,
                "args": args,
                "requires": ITEM_REQUIRES.get(
                    eid, REQUIRES.get(script, DEFAULT_REQUIRES)),
                "assert": rule,
            }
            if eid in APPLIES_WHEN:
                entry["check"]["applies_when"] = APPLIES_WHEN[eid]
            if warn:
                entry["check"]["warn"] = warn
            if eid in CANNOT_FAIL:
                entry["check"]["cannot_fail"] = CANNOT_FAIL[eid]
        if source == L:
            entry["lens"] = LENS_OF.get(entry["id"], "")
        entry["effort"] = effort_for(entry)
        entry["fix"] = fix
        if entry["id"] in SCORES_WITH:
            entry["scores_with"] = SCORES_WITH[entry["id"]]
        out.append(entry)
    return out


def subject_is_declared_for_every_absence_passing_item(items: list[dict]) -> list[str]:
    """Every item that can pass by finding nothing has said what its subject is.

    `openspec/specs/registry/` REG-9 asked for this and nothing could enforce it,
    because nothing identified which items owed a declaration — the seventeen were
    visible only through a hand sweep, and a hand sweep cannot say what it missed.

    The candidate set is derived from the built registry through the runner's own
    `passes_by_absence`, so this is a rule and not a membership list: an item added
    tomorrow is swept by existing, and the build refuses it until somebody has decided
    whether its subject can be absent. Deciding is the part no derivation can do; being
    made to decide is the part this does.
    """
    complaints = []
    for item in items:
        check = item.get("check") or {}
        rule = check.get("assert")
        if not rule or not passes_by_absence(rule):
            continue
        declared = bool(check.get("applies_when"))
        excused = item["id"] in SUBJECT_ALWAYS_PRESENT
        if declared and excused:
            complaints.append(f"{item['id']} both declares applicability and claims "
                              f"its subject is always present")
        elif not declared and not excused:
            complaints.append(
                f"{item['id']} ({item['title']}) passes by finding nothing and says "
                f"nothing about its subject: add `applies_when` to APPLIES_WHEN, or "
                f"say in SUBJECT_ALWAYS_PRESENT why the subject cannot be absent")
    for item_id in sorted(SUBJECT_ALWAYS_PRESENT):
        if item_id not in {i["id"] for i in items}:
            complaints.append(f"{item_id} is excused and is not in the registry")
    return complaints


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate the SEO checklist registry")
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--check", action="store_true",
                    help="Exit 1 if the on-disk registry is stale")
    a = ap.parse_args()

    titles = load_titles()
    overrides = load_title_overrides()
    items = build(titles, overrides)
    override_problems = title_override_problems(items, titles, overrides)
    if override_problems:
        for problem in override_problems:
            print(f"Invalid title override: {problem}", file=sys.stderr)
        return 1
    unlensed = [i["id"] for i in items if i["source"] == L and not i.get("lens")]
    if unlensed:
        print(f"LLM items with no lens: {', '.join(unlensed)} — add them to LENS, "
              "otherwise no agent is responsible for answering them",
              file=sys.stderr)
        return 1
    undeclared = subject_is_declared_for_every_absence_passing_item(items)
    if undeclared:
        for line in undeclared:
            print(line, file=sys.stderr)
        return 1
    # A content hash of the items, so a result file can say which registry it was
    # produced from. Without it, two runs whose item sets differ silently compare
    # as if they measured the same thing.
    registry_version = hashlib.sha256(
        json.dumps(items, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:12]
    payload = {
        "version": 1,
        "registry_version": registry_version,
        "item_count": len(items),
        # Derived, not written. This field said "(200) + 15" for releases while the
        # tree held 200 + 17, and no gate could see it: `--check` compares the
        # generator against its own output, so a literal is reproduced faithfully and
        # compared with nothing. `openspec/specs/registry/` REG-12 forbids the shape
        # rather than auditing the value, and
        # `tests/test_registry.py::TheRegistryStatesNothingAboutItselfItCannotProve`
        # fails if this line ever becomes a constant again.
        "source": "Plerdy SEO Checklist (%d) + %d beyond-Plerdy checks" % (
            sum(1 for i in items if i.get("plerdy_ref") is not None),
            sum(1 for i in items if i.get("plerdy_ref") is None)),
        "categories": [{"key": k, "prefix": p, "label": label}
                       for k, p, label, _ in CATEGORIES]
                      + [{"key": "geo_ai", "prefix": "GEO", "label": "GEO / AI Search"}],
        "items": items,
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"

    if a.check:
        if not os.path.exists(a.out):
            print("checklist.json missing — run without --check", file=sys.stderr)
            return 1
        with open(a.out, encoding="utf-8") as f:
            if f.read() != text:
                print("checklist.json is stale — regenerate it", file=sys.stderr)
                return 1
        print("checklist.json up to date")
        return 0

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(text)

    by_source: dict[str, int] = {}
    for i in items:
        by_source[i["source"]] = by_source.get(i["source"], 0) + 1
    scripts = {i["check"]["script"] for i in items if i.get("check")}
    print(f"Wrote {a.out}")
    print(f"  items: {len(items)}")
    for k in sorted(by_source):
        print(f"  {k:<7} {by_source[k]}")
    print(f"  unique scripts referenced: {len(scripts)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
