#!/usr/bin/env python3
"""Which KNOWN-ISSUES entries still describe this tree.

`KNOWN-ISSUES.md` is the one file in this repository that claims things about the
code and is read by nothing. Every other claim here has a reader: the registry has
`build_checklist --check`, the translations have `i18n_digest --check`, the
thresholds have `audit_thresholds`, and the verdicts have two ledgers. A defect
written down and then repaired leaves its entry standing, and the entry keeps
reading as open for as long as nobody re-runs it by hand.

That is not a hypothesis. Measured on 0.79.0, three entries described a tree that no
longer existed: the privacy and trust links got their boundary in 0.75.0, the private
author and date answers went in 0.77.0, and KW-071 was repointed at
`summary.contested_queries` in 0.43.0 — `v0.42.0` carries the old field and `v0.43.0`
the new one. Each entry outlived its repair because the release that fixed the code had
no reason to open this file.

So each entry in section 6 carries a marker — `<!-- ki: slug -->` — and this
instrument holds a probe beside it. The probe re-runs the entry's own measurement and
records what the tree answers today. `--check` fails when an answer moves, which is
the moment somebody has to decide whether the entry is now wrong or the tree is.

    python tests/known_issues.py                    # measure and report
    python tests/known_issues.py --out FILE         # refresh the record
    python tests/known_issues.py --check FILE       # exit 1 if the record is stale

**What this cannot do.** It does not read prose, and it must not start. The probe is
written by the person writing the entry and asserts nothing about whether the entry's
English is true; it asserts that the number the entry quotes is the number the tree
still produces. An entry whose claim has no executable witness — the polarity one says
so in as many words — carries `why` instead of a probe, and the count of those is
printed, because a ledger where everything is exempt is a ledger that has stopped
working.

The scope is section 6, deliberately, and it is not the whole file. Sections 1 and 4
and 5 are closed narratives; sections 2 and 3 each end on a standing limitation, and
those two are outside this reading — said here so the boundary is a decision somebody
made rather than a place nobody looked. All three of the stale entries found in 0.80.0
were in section 6, which is where entries written in the present tense collect.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import date
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL_DIR = os.path.join(ROOT, "skills", "seo-checklist")
SCRIPTS = os.path.join(SKILL_DIR, "scripts")
TOOLS = os.path.join(SKILL_DIR, "tools")
REGISTRY = os.path.join(SKILL_DIR, "resources", "config", "checklist.json")
KNOWN_ISSUES = os.path.join(ROOT, "KNOWN-ISSUES.md")
RECORD = os.path.join(ROOT, "tests", "known-issues.json")

sys.path.insert(0, SCRIPTS)
sys.path.insert(0, TOOLS)

MARKER = re.compile(r"^<!-- ki: ([a-z0-9-]+) -->$")
# An entry opens either as a bullet or as a numbered item, and in both cases its
# first words are bold. Nothing else in the file starts a line that way. The `*`
# spelling of a bullet is here although this file does not use it: a scan that knows
# one spelling reports an absence it never looked for.
ENTRY = re.compile(r"^(?:[-*] |\d+\. )\*\*")
SECTION = re.compile(r"^## ")
STATES = ("open", "closed", "history")

# Every probe pins whatever would otherwise move on its own. A date is the obvious
# one: an age in days is a different number tomorrow, and a gate that reddens
# overnight teaches people to re-record it without reading.
PINNED_TODAY = date(2026, 8, 19)
PAGE_URL = "https://example.test/p"
CANONICAL = '<link rel="canonical" href="%s">' % PAGE_URL

_PROBES = {}


def probe(name):
    def register(fn):
        _PROBES[name] = fn
        return fn
    return register


def _registry() -> dict:
    with open(REGISTRY, encoding="utf-8") as stream:
        return json.load(stream)


def _items_by_id() -> dict:
    return {item["id"]: item for item in _registry()["items"]}


def _page(body: str) -> str:
    return ('<!doctype html><html lang="en"><head><title>T</title>'
            + CANONICAL + "</head><body>" + body + "</body></html>")


def _temp_page(body: str) -> str:
    handle = tempfile.NamedTemporaryFile("w", suffix=".html", delete=False,
                                         encoding="utf-8")
    handle.write(_page(body))
    handle.close()
    return handle.name


# A script that can *set* the truncation key, not one that mentions it.
# Mentioning enrolls `checklist_runner.py`, which reads the flag and writes it
# nowhere: the reader would count as a reporter. The same expression is in
# `tests/test_evidence_scripts.py`, where a script that carries the key and
# cannot set it is a failure rather than a silent member of this list.
_CAN_SET_TRUNCATED = re.compile(r'\["truncated"\]\s*=\s*(?!False\b)'
                                r'|"truncated"\s*:\s*(?!False\b)')


def _truncation_reporters() -> list:
    """Every script that can tell the runner its input was capped."""
    found = []
    for name in sorted(os.listdir(SCRIPTS)):
        if not name.endswith(".py"):
            continue
        with open(os.path.join(SCRIPTS, name), encoding="utf-8") as stream:
            if _CAN_SET_TRUNCATED.search(stream.read()):
                found.append(name)
    return found

def _fixture_jsonld(tree: str, page: str) -> list:
    """Every JSON-LD block a fixture page actually publishes."""
    path = os.path.join(ROOT, "tests", "fixtures", tree, page)
    with open(path, encoding="utf-8") as stream:
        html = stream.read()
    blocks = []
    for raw in re.findall(
            r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
            html, re.S):
        try:
            blocks.append(json.loads(raw))
        except ValueError:
            continue
    return blocks

# ── the probes ────────────────────────────────────────────────────────────────

@probe("threshold_declarations")
def _threshold_declarations() -> dict:
    import audit_thresholds

    named, unnamed = audit_thresholds.scan()
    return {
        "counted": len([t for t in named if t["kind"] != "presentation"]),
        "presentation": len([t for t in named if t["kind"] == "presentation"]),
        # The split, not just the total. `tests/test_inherited_basis.py` ratchets
        # `inherited` downward, and a ratchet alone is satisfied by relabelling a line
        # `convention` without arguing it — which moves the debt rather than paying it.
        # Recording all five makes that visible as the two numbers moving together.
        "basis": {kind: len([t for t in named if t["kind"] == kind])
                  for kind in sorted(audit_thresholds.KINDS)},
        # The names, not the count. The entry is about four particular constants, and
        # a count of 25 survives judging those four while four others arrive.
        "uncounted": sorted(row["name"] for row in audit_thresholds.scan_uncounted()),
        "unnamed": len(unnamed),
        # Separators are normalised because this record is compared on three
        # platforms. A path recorded as `scripts\\robots_path_tester.py` is a
        # disagreement about Windows, not about the tree.
        "non_numeric_basis": sorted(
            "%s:%s" % (row["file"].replace(os.sep, "/"), row["line"])
            for row in audit_thresholds.scan_non_numeric_basis()),
    }


@probe("rendered_mobile_metrics")
def _rendered_mobile_metrics() -> dict:
    """Which mobile measures the rendered contract carries, and who reads them.

    The list alone would not have closed this entry: a measure nothing asserts is a
    field, not a check. So the items reading each one are measured beside it, taken
    from the registry rather than named here.
    """
    import rendered_audit

    with open(REGISTRY, encoding="utf-8") as stream:
        items = json.load(stream)["items"]
    readers = {}
    for item in items:
        rule = (item.get("check") or {}).get("assert") or {}
        path = rule.get("path")
        if path in rendered_audit.MOBILE_METRICS:
            readers.setdefault(path, []).append(item["id"])
    # Sorted, not as declared: the claim is about which measures exist, and an order
    # that came from a set would move on its own and teach people to re-record.
    return {"mobile_metrics": sorted(rendered_audit.MOBILE_METRICS),
            "items_asserting_each": {key: sorted(value)
                                     for key, value in sorted(readers.items())}}


@probe("cn_068_scores_on_the_good_fixture")
def _cn_068_scores() -> dict:
    import eeat_signal_checker

    good = os.path.join(ROOT, "tests", "fixtures", "good")
    scores = {}
    for name in ("index.html", "about.html", "privacy.html"):
        path = os.path.join(good, name)
        if os.path.exists(path):
            scores[name] = eeat_signal_checker.check_eeat(path)["score"]
    item = _items_by_id().get("CN-068", {})
    floor = ((item.get("check") or {}).get("assert") or {}).get("gte")
    return {"scores": scores, "floor": floor}


@probe("thin_assertions")
def _thin_assertions() -> dict:
    """Both halves of the gap, because either half can be the repair.

    The entry says a title promises more than its assertion requires. Recording only
    the assertion would let somebody bring the title down to the assertion — the other
    way to close it — and leave this reading green on an entry that had become false.
    """
    items = _items_by_id()
    return {item_id: {"title": items[item_id]["title"],
                      "assert": (items[item_id]["check"] or {}).get("assert")}
            for item_id in ("AR-152", "CN-056")}


@probe("entity_checker_reads_the_graph_unbounded")
def _entity_checker_reads_the_graph_unbounded() -> dict:
    """All three halves, because any one of them could be repaired alone.

    The entry says `entity_checker.py` reads the JSON-LD graph with no foreign-credit
    boundary and a top-level-only scan. Recording only the false PASS would let
    somebody add `Product` to the type set and leave this green while a reviewed
    company still supplied the page's identity; recording only the type set would miss
    the reverse. So the reading is: what a reviewed organisation contributes, what a
    page's own nested publisher contributes, and how many critical platforms the item
    is counting.
    """
    import entity_checker
    from bs4 import BeautifulSoup

    def entities(document):
        html = ('<html><head><script type="application/ld+json">'
                + json.dumps(document) + '</script></head><body></body></html>')
        return entity_checker.extract_entities_from_schema(
            BeautifulSoup(html, "html.parser"))

    links = ["https://www.wikidata.org/wiki/Q_them",
             "https://en.wikipedia.org/wiki/Them",
             "https://www.linkedin.com/company/them",
             "https://x.com/them"]
    reviewed_org = {"@graph": [{"@type": "Review", "itemReviewed": {"@id": "#o"}},
                               {"@id": "#o", "@type": "Organization",
                                "name": "Them", "sameAs": links}]}
    reviewed_product = {"@type": "Review",
                        "itemReviewed": {"@type": "Product", "name": "X100",
                                         "sameAs": links}}
    own_nested = {"@type": "Article",
                  "publisher": {"@type": "Organization", "name": "Us",
                                "sameAs": links}}
    item = _items_by_id().get("GEO-006", {})
    return {
        "geo_006_assert": (item.get("check") or {}).get("assert"),
        # By name and deduplicated, because that is how `missing` is keyed:
        # twitter.com and x.com are two domains under one name, so the list of
        # entries is five and the number the item counts is four.
        "critical_or_high_platforms": sorted(
            {info["name"] for info in entity_checker.SAMEAS_PLATFORMS.values()
             if info["priority"] in ("Critical", "High")}),
        "missing_critical_with_no_entities":
            entity_checker.analyze_sameas([])["total_missing_critical"],
        "missing_critical_from_a_reviewed_organisation":
            entity_checker.analyze_sameas(links)["total_missing_critical"],
        "entities_from_a_reviewed_organisation":
            [entity["name"] for entity in entities(reviewed_org)],
        "entities_from_a_reviewed_product":
            [entity["name"] for entity in entities(reviewed_product)],
        "entities_from_the_pages_own_nested_publisher":
            [entity["name"] for entity in entities(own_nested)],
        "product_is_an_entity_type": "Product" in entity_checker.ENTITY_TYPES,
    }


@probe("severity_vocabulary_proofs")
def _severity_vocabulary_proofs() -> dict:
    import audit_reachability

    proved = sorted(item_id for item_id, proof in audit_reachability.proofs().items()
                    if proof.get("mechanism") == "severity_vocabulary")
    return {"items_proved": proved}


@probe("kw_071_assertion")
def _kw_071_assertion() -> dict:
    """The item, and the whole registry's use of the field it used to assert.

    The entry says `worst_spread` is gone from the contract, which is a claim about
    215 items and not about one: attaching the old field to a different item would
    leave a KW-071-only reading green.
    """
    item = _items_by_id()["KW-071"]
    with open(REGISTRY, encoding="utf-8") as stream:
        whole = stream.read()
    return {"title": item["title"],
            "assert": item["check"].get("assert"),
            "warn": item["check"].get("warn"),
            "items_naming_worst_spread": [
                other["id"] for other in _registry()["items"]
                if "worst_spread" in json.dumps(other.get("check") or {})],
            "worst_spread_anywhere_in_the_registry": "worst_spread" in whole}


@probe("eeat_reviewed_languages")
def _eeat_reviewed_languages() -> dict:
    """The reviewed vocabularies, and what a page in an unreviewed language is graded on.

    Listing the three languages says nothing about the half of the entry that matters:
    that everything outside them is graded on English alone. Two identical pages, one
    declaring a reviewed language and one declaring German, answer that by scoring the
    same — the German page is being read with the English vocabulary.
    """
    import eeat_signal_checker

    body = ('<h1>Our kitchen</h1><p>Reviewed by a certified expert with fifteen years '
            'of experience. In our own tests we baked this every week.</p>'
            '<a href="/privacy">Privacy policy</a><a href="/about">About us</a>'
            '<a href="mailto:hello@example.test">Contact</a>')
    read = {}
    for lang in ("en", "de", "lt"):
        page = _page(body).replace('<html lang="en">', '<html lang="%s">' % lang)
        handle = tempfile.NamedTemporaryFile("w", suffix=".html", delete=False,
                                             encoding="utf-8")
        handle.write(page)
        handle.close()
        result = eeat_signal_checker.check_eeat(handle.name)
        signals = result["signals"]
        read[lang] = {"score": result["score"],
                      "credential_markers": len(signals["credential_markers"]),
                      "privacy_links": len(signals["privacy_links"]),
                      "trust_links": len(signals["trust_links"])}
    return {"languages": sorted(eeat_signal_checker._TERMS["languages"]),
            "one_english_page_read_under_each_declared_language": read}


@probe("ci_002_title")
def _ci_002_title() -> dict:
    """The title and what the item is run with.

    The open half is that no site-wide indexation claim is made, and a title alone
    cannot witness that: the arguments are where a set of URLs would have to appear.
    """
    item = _items_by_id()["CI-002"]
    return {"title": item["title"],
            "script": item["check"]["script"],
            "args": item["check"]["args"]}


@probe("negative_polarity_share")
def _negative_polarity_share() -> dict:
    """The share the polarity entry quotes, with the definition its prose gives.

    "Passing requires a path to be absent or bounded" is the whole rule, and it has
    nine spellings in this registry. The entry quoted 74 of 215 and left the
    spellings to the reader, so the number could not be re-derived from the file it
    describes — recovering it took a search over candidate definitions. That is the
    defect this instrument exists to stop, applied to itself.
    """
    def bounded(block) -> bool:
        if not isinstance(block, dict):
            return False
        return bool(block.get("falsy") or block.get("none_matching")
                    or block.get("none_severity")
                    or block.get("eq") == 0 or block.get("len_eq") == 0
                    or "lt" in block or "lte" in block or "len_lte" in block
                    or "count_matching_lte" in block)

    items = _registry()["items"]
    negative = [item for item in items
                if any(bounded((item.get("check") or {}).get(block))
                       for block in ("assert", "warn"))]
    return {"items": len(items), "negative_polarity": len(negative)}


@probe("gsc_threshold_values")
def _gsc_threshold_values() -> dict:
    import gsc_cannibalization
    import gsc_checker
    import gsc_links_csv

    import audit_thresholds

    wanted = {
        "STRIKING_DISTANCE_MIN_POSITION": gsc_checker,
        "STRIKING_DISTANCE_MAX_POSITION": gsc_checker,
        "STRIKING_DISTANCE_MIN_IMPRESSIONS": gsc_checker,
        "TOP_POSITION_MAX": gsc_checker,
        "LOW_CTR_PCT": gsc_checker,
        "VERY_LOW_CTR_PCT": gsc_checker,
        "RANKS_FIRST_POSITION": gsc_cannibalization,
        "HIGH_SEVERITY_IMPRESSIONS": gsc_cannibalization,
        "TOP1_SHARE_PCT": gsc_links_csv,
    }
    # The value alone is the weaker half of the claim. "Deliberately not calibrated"
    # is about the basis each one declares, and relabelling one `measured` without
    # touching its value is exactly the move this entry says has not been made.
    kind = {row["name"]: row["kind"] for row in audit_thresholds.scan()[0]}
    return {name: {"value": getattr(module, name), "basis": kind.get(name)}
            for name, module in sorted(wanted.items())}


def _css_calibration() -> dict:
    path = os.path.join(TOOLS, "calibration", "css-minification.json")
    with open(path, encoding="utf-8") as stream:
        return json.load(stream)


@probe("css_minification_corpus")
def _css_minification_corpus() -> dict:
    data = _css_calibration()
    distributions = data["signal_distributions"]["bytes_per_line"]["by_package"]
    return {
        "pairs": data["counts"]["pairs"],
        "bulma_minified_min": distributions["bulma"]["minified"]["min"],
        "codicons_source_median": distributions["@vscode/codicons"]["source"]["p50"],
    }


@probe("wasted_bytes_definition")
def _wasted_bytes_definition() -> dict:
    """What the field counts, not only what the corpus measured.

    The corpus figures are the entry's evidence; its claim is about the shipped
    field. Redefining `wasted_bytes` to charge for compressed bytes would leave a
    corpus-only reading green, so the fraction it multiplies, the threshold it
    reports against and the fields it declares are recorded beside them.
    """
    import ast

    import css_minify_check

    # The arithmetic itself, read out of the script rather than restated here. The
    # constants and the declared fields both survive a rewrite that keeps the names
    # and charges for compressed bytes instead; this expression does not.
    source = os.path.join(SCRIPTS, "css_minify_check.py")
    with open(source, encoding="utf-8") as stream:
        tree = ast.parse(stream.read())
    accumulations = sorted(
        ast.unparse(node.value) for node in ast.walk(tree)
        if isinstance(node, ast.AugAssign)
        and isinstance(node.target, ast.Subscript)
        and isinstance(node.target.slice, ast.Constant)
        and node.target.slice.value == "wasted_bytes")

    shapes = os.path.join(SKILL_DIR, "resources", "references", "script-output-shapes.md")
    with open(shapes, encoding="utf-8") as stream:
        text = stream.read()
    section = text.split("### css_minify_check.py", 1)[1].split("\n### ", 1)[0]
    fields = re.findall(r"^`([^`]+)`", section, flags=re.M)
    return {
        "pairs": _css_calibration()["counts"]["pairs"],
        "savings_fraction": css_minify_check.MINIFICATION_SAVINGS_FRACTION,
        "warn_threshold": css_minify_check.WASTED_BYTES_WARN,
        "what_the_field_accumulates": accumulations,
        "declared_fields": fields,
    }


@probe("redirect_walk_cap")
def _redirect_walk_cap() -> dict:
    """The cap the two redirect items actually answer under, and where it lives.

    Read off the function's signature rather than a constant, because that is the
    whole finding: a default argument is invisible to a scan that reads module-level
    assignments, and this one decides whether `has_loop` can be true at all.
    """
    import inspect

    import audit_thresholds
    import redirect_checker

    signature = inspect.signature(redirect_checker.check_redirects)
    basis = {row["name"]: row["kind"] for row in audit_thresholds.scan()[0]}
    items = _items_by_id()
    source = inspect.getsource(redirect_checker.check_redirects)
    return {
        "cap": signature.parameters["max_redirects"].default,
        "cap_is_a_named_constant":
            signature.parameters["max_redirects"].default
            == getattr(redirect_checker, "MAX_REDIRECT_HOPS", None),
        "cap_basis": basis.get("MAX_REDIRECT_HOPS"),
        # The repair itself, not a symptom of it: every branch that leaves the walk
        # unfinished must stop answering. A `has_loop = False` there is the false PASS
        # this entry was written about, and a `None` is the same thing spelled
        # differently. Two branches withhold — the cap and the network error — and the
        # count is recorded because a third way to stop early would have to join them.
        "branches_that_withhold_has_loop":
            source.count('result.pop("has_loop", None)'),
        "ci_014_assert": items["CI-014"]["check"].get("assert"),
        "ar_150_assert": items["AR-150"]["check"].get("assert"),
    }


@probe("go_138_matches_a_field")
def _go_138_matches_a_field() -> dict:
    return {"assert": _items_by_id()["GO-138"]["check"].get("assert")}


@probe("russian_item_coverage")
def _russian_item_coverage() -> dict:
    path = os.path.join(SKILL_DIR, "resources", "i18n", "ru.json")
    with open(path, encoding="utf-8") as stream:
        russian = json.load(stream)
    ids = {item["id"] for item in _registry()["items"]}
    # Both maps by id, not by length. Two maps of the right size can disagree about
    # which items they cover, and the entry claims coverage.
    return {
        "registry_items": len(ids),
        "item_titles": len(russian["item_titles"]),
        "item_fixes": len(russian["item_fixes"]),
        "ids_with_no_title": sorted(ids - set(russian["item_titles"])),
        "ids_with_no_fix": sorted(ids - set(russian["item_fixes"])),
        "translated_ids_not_in_the_registry":
            sorted((set(russian["item_titles"]) | set(russian["item_fixes"])) - ids),
    }


@probe("freshness_foreign_dates")
def _freshness_foreign_dates() -> dict:
    import freshness_checker

    stamp = '<time datetime="2019-03-01">1 March 2019</time>'
    shapes = {
        "class_named_comment": '<h1>H</h1><p>Body.</p><div class="comment">%s</div>' % stamp,
        "h_cite_comment": '<h1>H</h1><p>Body.</p><div class="h-cite">%s</div>' % stamp,
        "declared_itemprop_comment": (
            '<article itemscope itemtype="https://schema.org/Article"><h1>H</h1>'
            '<p>Body.</p><div itemprop="comment" itemscope '
            'itemtype="https://schema.org/Comment">%s</div></article>' % stamp),
    }
    out = {}
    for label, body in shapes.items():
        result = freshness_checker.check_freshness(_temp_page(body), today=PINNED_TODAY)
        out[label] = {"age_days": result["age_days"], "latest_date": result["latest_date"]}
    return out


@probe("credit_boundary_and_itemref")
def _credit_boundary_and_itemref() -> dict:
    """Both directions of the `itemref` boundary, and the credit it must not take.

    The third case is why the first two are readable. A rule that stopped crediting
    anybody would empty the first two lists as well and look like the repair, so the
    page's own byline is measured beside a claimed one — with an `itemref` in the same
    document, so the removal path is running.
    """
    import seo_common

    def authors(body):
        return seo_common.page_author_names(
            seo_common.parse_html(_page(body), PAGE_URL))

    referenced_out = ('<div itemprop="comment" itemref="c1"></div>'
                      '<span id="c1" class="author">D Petras</span>')
    nested_claimed = ('<div itemprop="comment"><span id="b1" class="author">'
                      'M Kazlauskiene</span></div><article itemscope itemref="b1"></article>')
    chained = ('<div itemprop="comment" itemscope itemref="w1"></div>'
               '<div id="w1" itemscope itemref="w2"></div>'
               '<div id="w2"><span class="author">D Petras</span></div>')
    own_beside_claimed = ('<div itemprop="comment" itemscope itemref="c1"></div>'
                          '<span class="author">M Kazlauskiene</span>'
                          '<span id="c1" class="author">D Petras</span>')
    return {
        "referenced_byline_outside_the_comment": authors(referenced_out),
        "page_byline_nested_in_the_comment": authors(nested_claimed),
        "byline_claimed_through_a_chain": authors(chained),
        "page_byline_beside_a_claimed_one": authors(own_beside_claimed),
    }


@probe("class_named_comment_author")
def _class_named_comment_author() -> dict:
    import seo_common

    body = '<div class="comment"><span class="author">D Petras</span></div>'
    return {"authors": seo_common.page_author_names(
        seo_common.parse_html(_page(body), PAGE_URL))}


@probe("privacy_and_trust_links_boundary")
def _privacy_and_trust_links_boundary() -> dict:
    import eeat_signal_checker

    body = ('<article itemscope itemtype="https://schema.org/Article">'
            '<h1>Unauthored</h1><p>Body text about the topic.</p>'
            '<div itemprop="comment" itemscope itemtype="https://schema.org/Comment">'
            '<span class="author">D Petras</span>'
            '<a href="mailto:commenter@example.com">write me</a>'
            '<a href="/privacy">Privacy policy</a></div></article>')
    signals = eeat_signal_checker.check_eeat(_temp_page(body))["signals"]
    return {
        "authors": signals["authors"],
        "privacy_links": len(signals["privacy_links"]),
        "trust_links": len(signals["trust_links"]),
        "policy_links": len(signals["policy_links"]),
    }


@probe("article_seo_shares_the_answers")
def _article_seo_shares_the_answers() -> dict:
    import article_seo
    import seo_common

    shapes = {
        "author_grid": ('<div class="author-grid"><p>Meet the team</p>'
                        '<p>Recipes by many hands</p></div><h1>H</h1><p>Body.</p>'),
        "published_widget": ('<div class="published-widget"><p>Newsletter</p>'
                             '<p>Sign up</p></div><h1>H</h1><p>Body.</p>'),
    }
    out = {}
    for label, body in shapes.items():
        parsed = seo_common.parse_html(_page(body), PAGE_URL)
        content = article_seo.extract_content(parsed, "unknown")
        out[label] = {"authors": content["authors"], "publish_date": content["publish_date"]}

    fixtures = sorted((os.path.join(folder, name)
                       for folder, _, names in os.walk(os.path.join(ROOT, "tests", "fixtures"))
                       for name in names if name.endswith(".html")))
    divergent = []
    for path in fixtures:
        with open(path, encoding="utf-8", errors="replace") as stream:
            parsed = seo_common.parse_html(stream.read(), "")
        content = article_seo.extract_content(parsed, "unknown")
        dates = seo_common.declared_publication_dates(parsed)
        if (content["authors"] != seo_common.page_author_names(parsed)
                or content["publish_date"] != (dates[0] if dates else "")):
            divergent.append(os.path.relpath(path, ROOT).replace(os.sep, "/"))
    out["fixtures"] = len(fixtures)
    out["divergent_fixtures"] = divergent
    return out


@probe("shared_robots_cache")
def _shared_robots_cache() -> dict:
    """Whether one test's robots.txt can still answer another test's question.

    Three facts made it possible, and no one of them was the defect: the directory was
    machine-wide, the key is the origin and nothing else, and the entry outlives the
    server by half an hour. 0.82.0 moved the first and, for fixture origins, the third.
    So this now measures the repair rather than the defect — what would have to come
    back for the entry to reopen.

    The key is deliberately still measured: it did *not* move, and a change to it —
    a run id, a pid, the served routes — is a different tree than the one this entry
    was closed against.
    """
    import tempfile as _tempfile

    import lib.safe_http as safe

    origin = "http://127.0.0.1:49152"
    var = safe.RATE_LIMIT_DIR_VAR
    saved = os.environ.get(var)
    try:
        os.environ[var] = os.path.join(_tempfile.gettempdir(), "probe-rate-dir")
        honours_environment = safe.rate_limit_dir() == os.environ[var]
        os.environ.pop(var, None)
        default = safe.rate_limit_dir()
    finally:
        if saved is None:
            os.environ.pop(var, None)
        else:
            os.environ[var] = saved

    with open(os.path.join(ROOT, "tests", "harness.py"), encoding="utf-8") as stream:
        harness_source = stream.read()
    return {
        "cache_dir_is_the_machine_temp_dir":
            os.path.dirname(default) == _tempfile.gettempdir(),
        "directory_is_read_from_the_environment": honours_environment,
        # A module constant is exactly what a caller could assign and a child process
        # could not inherit. Its absence is the repair; its return is the defect.
        "module_constant_that_cannot_be_inherited": hasattr(safe, "RATE_LIMIT_DIR"),
        "robots_cache_ttl_seconds": safe.ROBOTS_CACHE_TTL,
        # The filename, so that a key scheme which started including anything beyond
        # the origin — a run id, a pid, the served routes — moves this value.
        "cache_file_for_one_fixed_origin":
            os.path.basename(safe._robots_cache_path(origin)),
        # The other half: a suite that names its own directory, and fixture servers
        # that drop their answer when they stop, so a recycled port finds nothing.
        # Either spelling — the variable's own name or the constant holding it — so
        # this moves when the harness stops naming it at all, not when it renames it.
        "suite_names_its_own_directory":
            var in harness_source or "RATE_LIMIT_DIR_VAR" in harness_source,
        "fixture_servers_forget_their_origin":
            harness_source.count("forget_robots(self.base)"),
    }


@probe("foreign_credit_keys")
def _foreign_credit_keys() -> dict:
    import seo_common

    body = ('<article itemscope itemtype="https://schema.org/Article">'
            '<div itemprop="about" itemscope itemtype="https://schema.org/Book">'
            '<span class="author">Herman Melville</span></div></article>')
    return {
        "keys": sorted(seo_common.FOREIGN_CREDIT_KEYS),
        "author_of_a_book_the_page_is_about":
            seo_common.page_author_names(seo_common.parse_html(_page(body), PAGE_URL)),
    }


@probe("a_truncated_crawl_decides_the_whole_site")
def _a_truncated_crawl_decides_the_whole_site() -> dict:
    """Which items would call a site clean from the part of it that was read.

    Measured through `grade()`, which is where the withholding lives — `evaluate()`
    answers about a dict and would answer the same before 0.88.0. The reachable set
    is taken from the registry and from the scripts' own source rather than listed
    here, so an item added over one of these scripts joins the count without anybody
    remembering to add it.
    """
    import checklist_runner as runner

    reporters = _truncation_reporters()
    covered, still_deciding = [], []
    for item in _items_by_id().values():
        rule = (item.get("check") or {}).get("assert")
        if not rule or not runner.passes_by_absence(rule):
            continue
        script = item["check"]["script"]
        if script not in reporters:
            continue
        covered.append(item["id"])
        parts = rule["path"].split(".")
        payload, node = {}, None
        node = payload
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = 0 if rule.get("eq") == 0 else []
        payload["truncated"] = True
        key = (script, ())
        row = runner.grade([item], {key: [item["id"]]}, {key: payload}, {}, False)[0]
        if row["status"] != runner.NO_DATA:
            still_deciding.append("%s=%s" % (item["id"], row["status"]))
    return {
        "scripts_that_report_a_cap": reporters,
        "items_covered": sorted(covered),
        "high_among_them": sorted(
            i for i in covered if _items_by_id()[i]["severity"] == "high"),
        # The whole claim, and it has to stay empty.
        "still_deciding_over_a_capped_input": sorted(still_deciding),
    }


@probe("a_mostly_refused_run_reports_a_clean_count")
def _a_mostly_refused_run_reports_a_clean_count() -> dict:
    """A hundred images, ninety-nine of which answered nothing.

    The entry's own scenario, run rather than described. `broken_image_count` has to
    be absent — an absent key is NO_DATA, and NO_DATA is the honest answer about a
    page that was looked at once.
    """
    import image_weight_audit

    rows = [{"src": "https://example.test/i%d.png" % n} for n in range(100)]

    def one(url, timeout):
        n = int(url.rsplit("i", 1)[1].split(".")[0])
        if n == 0:
            return "ok", {"status": 200}, ""
        return "unchecked", {"status": None, "error_kind": "timeout"}, ""

    inventory = {
        "site": "https://example.test/",
        "summary": {"truncated": False},
        "pages": {"p": {"url": "https://example.test/",
                        "images": [r["src"] for r in rows]}},
    }
    with mock.patch.object(image_weight_audit, "_check_image", one),          mock.patch.object(image_weight_audit.site_crawl, "inventory_for",
                           lambda *a, **k: inventory):
        out = image_weight_audit.audit_inventory("https://example.test/", "ignored")
    return {
        "images_checked": out["summary"]["images_checked"],
        "unchecked": out["summary"]["unchecked_images"],
        "reports_broken_image_count": "broken_image_count" in out,
    }


@probe("the_other_caps_have_not_been_read")
def _the_other_caps_have_not_been_read() -> dict:
    """The scripts behind a passes-by-absence item that still say nothing about a cap.

    Recorded as a list of names with the items that read them, not as a count: the
    point of the entry is which ones were left, and a count of twelve survives one
    being read while another arrives. `html_validator.py` is named separately because
    it was read and cleared — the distinction between "not looked at" and "looked at
    and fine" is the one this ledger exists to keep.
    """
    import checklist_runner as runner

    reports = set(_truncation_reporters())
    # Every entry here is a reading somebody did, in the form "what was read". The
    # two things this ledger exists to keep apart are "not looked at" and "looked at
    # and fine", so a script leaves `not_yet_read` only by acquiring a sentence
    # saying where its cap stands relative to the number an item reads.
    #
    # Twenty-one of these were read for 0.91.0, and the reading has a provenance
    # worth recording: an executor read all twenty-three against one question and
    # wrote a file per script; every `critical` and `high` one was then re-read here
    # against the code, and every cap-shaped construct in the rest — a slice, a
    # `break`, a `MAX_*`, an `islice` — was enumerated rather than eyeballed, because
    # a claim that a script has no cap is a claim of absence. Two of the
    # twenty-three were upstream and are repaired in this release, which is why they
    # are not here: they report truncation now and leave this list through
    # `reports`.
    cleared = {
        # Read in 0.88.0 and found sound: `MAX_MESSAGES` trims `messages` after
        # `counts` has already been incremented, so `summary.errors` is the whole
        # number. Kept here rather than dropped, because "looked at and fine" and
        # "not looked at" are the two things this ledger exists to keep apart.
        "html_validator.py": "counts before the message cap",

        # 0.91.0. Downstream of the number the item reads: the slice shortens what a
        # person is shown after the count or the verdict was taken over everything.
        "a11y_seo_checker.py":
            "slices findings, not input, and CN-036 reads a contrast count instead",
        "collection_page_checker.py": "slices the printed lines, not `issues`",
        "font_audit.py": "slices an error string only",
        "ga4_tag_checker.py": "slices an error string only",
        "gsc_url_inspection.py": "its only break ends a retry loop on success",
        "mobile_render_checker.py":
            "counts every wide value, then slices the evidence list",
        "rich_results_guard.py": "counts the whole `issues` before slicing the lines",
        "schema_required_props.py":
            "counts errors and warnings whole, then slices the lines",
        "video_schema_checker.py": "slices the printed lines, not `issues`",
        "domain_safety_check.py": "slices error text; no input is cut",
        "entity_checker.py":
            "head-checks the first three profiles, but GEO-006 reads the missing "
            "count, not those findings",
        "gsc_checker.py":
            "GO-134 reads the sitemap report, which is not paged; the row and page "
            "caps sit on `performance`, which nothing asserts",
        "parse_html.py":
            "the four items read whole fields; every slice is on evidence text",

        # 0.91.0. No cap of any kind, established by enumerating slices, breaks and
        # `MAX_*` constants in each file rather than by reading for an impression.
        "canonical_checker.py": "no cap",
        "critical_request_chain.py": "no cap",
        "image_inventory.py": "no cap",
        "javascript_render_audit.py": "no cap",
        "rendered_audit.py": "no cap; its one constant is a viewport width",
        "robots_path_tester.py": "no cap",
        "third_party_script_audit.py": "no cap",
        "url_quality.py": "no cap; its constants are the rule, not a limit on input",
    }
    unread: dict[str, list[str]] = {}
    for item in _items_by_id().values():
        rule = (item.get("check") or {}).get("assert")
        if not rule or not runner.passes_by_absence(rule):
            continue
        script = item["check"]["script"]
        if script in reports or script in cleared:
            continue
        unread.setdefault(script, []).append(item["id"])
    return {
        "cleared_by_reading": cleared,
        # Not all of these have a cap — some were never examined either way, which
        # is the claim: the list is of readings not done, not of defects found.
        "not_yet_read": {name: sorted(ids) for name, ids in sorted(unread.items())},
    }


@probe("the_crawl_defaults_now_decide_whether_items_answer")
def _the_crawl_defaults_now_decide_whether_items_answer() -> dict:
    """The two numbers, and how many verdicts each one silences past its limit.

    The count is taken by grading, not by counting the registry: the claim is about
    what a run reports, and an item can read one of these scripts without passing by
    absence. Both numbers are read from `site_crawl` rather than repeated here, so an
    entry that says "a hundred pages" cannot outlive a default that moved.

    **The split is the repair 0.91.0 made to this probe.** It used to return one list —
    every item whose script reports truncation and whose assertion passes by absence —
    under a name that says *these two crawl numbers silence them*. That was already
    wider than the claim: `CI-014` stops at `MAX_REDIRECT_HOPS`, `TE-174` at
    `MAX_SHEETS`, `MS-023` and `KW-071` at a Search Console row page, and none of the
    three has anything to do with how many pages the crawl read. Adding two per-page
    caps in 0.91.0 made the same error visible rather than causing it. What the crawl
    decides is now derived from `requires: crawl` in the registry, and what a script's
    own cap decides is beside it, named as such.
    """
    import checklist_runner as runner
    import site_crawl

    reporters = set(_truncation_reporters())
    silenced = []
    by_own_cap = []
    for item in _items_by_id().values():
        rule = (item.get("check") or {}).get("assert")
        if not rule or not runner.passes_by_absence(rule):
            continue
        script = item["check"]["script"]
        if script not in reporters:
            continue
        fed_by_the_crawl = item["check"].get("requires") == "crawl"
        parts = rule["path"].split(".")
        payload: dict = {}
        node = payload
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = 0 if rule.get("eq") == 0 else []
        payload["truncated"] = True
        key = (script, ())
        row = runner.grade([item], {key: [item["id"]]}, {key: payload}, {}, False)[0]
        if row["status"] != runner.NO_DATA:
            continue
        (silenced if fed_by_the_crawl else by_own_cap).append(item["id"])
    return {
        "max_pages": site_crawl.DEFAULT_MAX_PAGES,
        "depth": site_crawl.DEFAULT_DEPTH,
        "both_bases": "inherited",
        "items_silenced_past_either_limit": sorted(silenced),
        # Same withholding, decided by a cap neither of these two numbers reaches:
        # nothing here is fed by the shared crawl. The list above is what these two
        # *can* silence rather than what only they silence — a crawl-fed script may
        # cap its own input as well, and then either number can be the one that
        # stopped the reading.
        "items_silenced_by_a_cap_other_than_these_two": sorted(by_own_cap),
    }


@probe("go_143_asked_for_a_claim_that_was_not_true")
def _go_143_asked_for_a_claim_that_was_not_true() -> dict:
    """What the item asks for now, graded rather than described.

    Three shapes through `grade()`: the two properties Google's site-name
    documentation requires, one of them missing, and the retired markup. The last is
    the entry's own subject — it has to be neither asked for nor penalised.
    """
    import checklist_runner as runner
    import schema_required_props

    def verdict(node: dict) -> str:
        html = ('<!doctype html><html lang="en"><head><title>t</title>'
                '<script type="application/ld+json">' + json.dumps(node)
                + "</script></head><body><h1>h</h1></body></html>")
        handle = tempfile.NamedTemporaryFile("w", suffix=".html", delete=False,
                                             encoding="utf-8")
        handle.write(html)
        handle.close()
        documents, meta = schema_required_props.extract_schema_documents(handle.name)
        data = schema_required_props.validate_schema_required_props(
            documents, None, meta.get("invalid_blocks"))
        item = _items_by_id()["GO-143"]
        key = (item["check"]["script"], ())
        return runner.grade([item], {key: ["GO-143"]}, {key: data}, {}, False)[0]["status"]

    base = {"@context": "https://schema.org", "@type": "WebSite",
            "name": "Example", "url": "https://example.test/"}
    retired = dict(base, potentialAction={
        "@type": "SearchAction",
        "target": "https://example.test/?q={search_term_string}",
        "query-input": "required name=search_term_string"})
    return {
        "title": _items_by_id()["GO-143"]["title"],
        "recommends_anything_for_website":
            sorted(schema_required_props.RECOMMENDED_PROPS.get("WebSite", ())),
        "required_of_website":
            sorted(schema_required_props.REQUIRED_PROPS.get("WebSite", ())),
        "name_and_url": verdict(base),
        "url_missing": verdict({k: v for k, v in base.items() if k != "url"}),
        "with_the_retired_searchaction": verdict(retired),
        # Read out of the JSON-LD itself, not out of the file's text: the comment
        # left in place of the removed markup names `SearchAction`, and a substring
        # search over the whole file would find it and call the fixture unrepaired.
        "fixture_still_publishes_a_searchaction": any(
            "SearchAction" in json.dumps(block)
            for block in _fixture_jsonld("good", "index.html")),
    }


@probe("the_schema_property_tables_have_not_been_re_read")
def _the_schema_property_tables_have_not_been_re_read() -> dict:
    """Both tables, whole, plus the two divergences that were actually verified.

    Recorded as the tables themselves rather than as a count: the entry is about
    what they say, and a count of twenty-three survives one type being corrected
    while another drifts. The `verified_against_google` block is small on purpose —
    it holds only what somebody read, and it is the part that should grow.
    """
    import schema_required_props as props

    return {
        "required": {name: sorted(values)
                     for name, values in sorted(props.REQUIRED_PROPS.items())},
        "recommended": {name: sorted(values)
                        for name, values in sorted(props.RECOMMENDED_PROPS.items())},
        "verified_against_google": {
            "WebSite": "corrected in 0.89.0: name and url required, nothing "
                       "recommended; the sitelinks search box is gone",
            "Article": "diverges — Google documents no required properties for "
                       "Article/NewsArticle/BlogPosting and does not list "
                       "mainEntityOfPage or publisher among the recommended; read "
                       "in 0.89.0 and deliberately not acted on",
        },
        # Parenthesised: `a | b - c` binds as `a | (b - c)`, which left both read
        # types in the list of unread ones on the first run of this probe.
        "types_not_read": sorted(
            (set(props.REQUIRED_PROPS) | set(props.RECOMMENDED_PROPS))
            - {"WebSite", "Article"}),
    }


@probe("a_placeholder_in_structured_data_almost_never_decides")
def _a_placeholder_in_structured_data_almost_never_decides() -> dict:
    """What one unfilled property does to the two items that read this script.

    Graded, not reasoned: the claim is about verdicts. One placeholder and four are
    both measured, because the whole point is that the answer changes only in bulk.
    The `SearchAction` row is the coverage 0.89.0 removed with GO-143's old pattern;
    it is here so the removal cannot be forgotten, and it is expected to be quiet.
    """
    import checklist_runner as runner
    import schema_required_props

    def verdicts(node: dict) -> dict:
        html = ('<!doctype html><html lang="en"><head><title>t</title>'
                '<script type="application/ld+json">' + json.dumps(node)
                + "</script></head><body><h1>h</h1></body></html>")
        handle = tempfile.NamedTemporaryFile("w", suffix=".html", delete=False,
                                             encoding="utf-8")
        handle.write(html)
        handle.close()
        documents, meta = schema_required_props.extract_schema_documents(handle.name)
        data = schema_required_props.validate_schema_required_props(
            documents, None, meta.get("invalid_blocks"))
        out = {"warnings": data["summary"]["warnings"],
               "errors": data["summary"]["errors"]}
        for item_id in ("MS-032", "GO-143"):
            item = _items_by_id()[item_id]
            key = (item["check"]["script"], ())
            out[item_id] = runner.grade(
                [item], {key: [item_id]}, {key: data}, {}, False)[0]["status"]
        return out

    one = {"@context": "https://schema.org", "@type": "WebSite",
           "name": "TODO", "url": "https://example.test/"}
    four = {"@context": "https://schema.org", "@type": "Product",
            "name": "TODO", "sku": "REPLACE", "description": "lorem ipsum",
            "brand": "INSERT", "offers": {"@type": "Offer", "price": "1"}}
    search = {"@context": "https://schema.org", "@type": "SearchAction",
              "target": "REPLACE_ME"}
    return {
        "one_placeholder": verdicts(one),
        "four_placeholders": verdicts(four),
        "a_searchaction_placeholder": verdicts(search),
    }


@probe("a_greek_rho_killed_the_evidence_layer")
def _a_greek_rho_killed_the_evidence_layer() -> dict:
    """Both halves, measured without needing a console in a particular codepage.

    The parent half is driven with a `stdout` of None — what a dead reader thread
    leaves behind — so it answers the same on every platform. The child half is read
    off the scripts: a script printing `ensure_ascii=False` puts raw UTF-8 on stdout
    and has to say so itself, because the runner's environment only covers a child.
    """
    import subprocess as sp
    from unittest import mock as _mock

    import checklist_runner as runner

    class _DeadReader:
        returncode = 0
        stdout = None
        stderr = None

    with _mock.patch.object(sp, "run", return_value=_DeadReader()):
        undecodable = runner.run_script("detect_profile.py", ["--html", __file__])

    prints_raw, unguarded = [], []
    for name in sorted(os.listdir(SCRIPTS)):
        if not name.endswith(".py"):
            continue
        with open(os.path.join(SCRIPTS, name), encoding="utf-8") as stream:
            text = stream.read()
        if "ensure_ascii=False" in text:
            prints_raw.append(name)
            if "_utf8_stdout()" not in text:
                unguarded.append(name)

    with open(os.path.join(SCRIPTS, "checklist_runner.py"), encoding="utf-8") as stream:
        source = stream.read()
    return {
        # The byte, named, so the entry cannot drift from the thing it is about.
        "greek_rho_utf8": "ρ".encode("utf-8").hex(),
        "parent_reads_utf8": 'encoding="utf-8"' in source.split("subprocess.run(", 1)[1][:300],
        "children_get_utf8_stdout": 'PYTHONIOENCODING="utf-8"' in source,
        "a_dead_reader_is_reported_as": undecodable.get("error_kind"),
        "scripts_printing_raw_utf8": prints_raw,
        # Has to stay empty.
        "of_those_without_their_own_guarantee": unguarded,
    }


@probe("the_branded_query_is_whatever_got_the_most_clicks")
def _the_branded_query_is_whatever_got_the_most_clicks() -> dict:
    """What the brand block returns when the brand and the head term differ.

    Built from rows rather than from a live property: the claim is about the method,
    and a method that picks by clicks answers the same on invented rows as on real
    ones. The rows are shaped like the property that exposed this — a generic head
    term carrying every click, and the actual brand name carrying none.
    """
    import gsc_cannibalization

    rows = [
        {"query": "barber paphos", "page": "https://example.test/en/",
         "clicks": 4, "impressions": 109, "position": 3.1},
        {"query": "barbers near me", "page": "https://example.test/en/",
         "clicks": 2, "impressions": 84, "position": 2.8},
        # The brand, and what a brand looks like in Search Console for a small
        # business: known to the people who already know it, invisible to search.
        {"query": "marino barbero", "page": "https://example.test/",
         "clicks": 0, "impressions": 0, "position": 0.0},
    ]
    branded = gsc_cannibalization.find_branded(rows, "sc-domain:example.test")
    items = _items_by_id()
    return {
        "method": "highest-click query",
        "picked_as_the_brand": branded.get("query"),
        "the_actual_brand_is_in_the_rows": any(
            r["query"] == "marino barbero" for r in rows),
        "owns_homepage": branded.get("owns_homepage"),
        "ranks_first": branded.get("ranks_first"),
        "items_reading_it": {
            item_id: items[item_id]["title"]
            for item_id in ("KW-070", "GO-139")
        },
    }


@probe("a_census_copied_a_title_no_item_has")
def _a_census_copied_a_title_no_item_has() -> dict:
    """Whether the two recorded ledgers still copy this registry faithfully.

    Both records carry, beside the measurement that cost a run, a handful of fields
    lifted straight out of the registry, and both stamp themselves with the
    `registry_version` their tool read at the time. The stamp is where this hid: it
    comes from the same registry load as the fields beside it, so it cannot drift on
    its own — and that made it the one field in the file an edit could set, which is
    the field the suite was reading.

    Counting disagreements is not enough on its own — a comparison that has stopped
    comparing reports zero exactly like a tree that is in step. So the same reading is
    made once against the ledgers as they ship, and then once per copied field against
    a census with that field moved. The first has to be empty and each of the others
    has to name the row and the field it broke, or the reading is not reading that
    field. One title moved is not enough to witness four fields being read.
    """
    registry = _registry()
    items = {item["id"]: item for item in registry["items"]}

    def disagreements(rows: dict, fields: tuple[str, ...]) -> list[str]:
        found = []
        for item_id, row in sorted(rows.items()):
            item = items.get(item_id)
            if item is None:
                found.append(item_id)
                continue
            for field in fields:
                if field == "script":
                    registered = (item.get("check") or {}).get("script")
                else:
                    registered = item.get(field)
                if row.get(field) != registered:
                    found.append(f"{item_id}.{field}")
        return found

    with open(os.path.join(ROOT, "tests", "census.json"), encoding="utf-8") as stream:
        census = json.load(stream)
    with open(os.path.join(ROOT, "tests", "inert-findings.json"),
              encoding="utf-8") as stream:
        inert = json.load(stream)

    census_fields = ("title", "severity", "source", "script")
    # This entry's own subject while it is in the registry, and the first row
    # otherwise: a probe that raises KeyError on a deleted item reports a crash where
    # it should report a reading.
    moved = "GO-143" if "GO-143" in census["items"] else min(census["items"])

    def with_one_field_moved(field: str) -> dict:
        copy = {k: dict(v) for k, v in census["items"].items()}
        was = copy[moved][field]
        # A value of the same kind and not the same value, whatever the field holds:
        # `script` is None for the items no script answers.
        copy[moved][field] = (was + ".") if isinstance(was, str) else "moved"
        return copy

    return {
        "census_rows": len(census["items"]),
        "census_fields_read": list(census_fields),
        "census_rows_that_disagree": disagreements(census["items"], census_fields),
        "inert_rows": len(inert["items"]),
        "inert_rows_that_disagree": disagreements(inert["items"],
                                                  ("title", "script")),
        "the_row_moved_to_test_the_reading": moved,
        "the_reading_sees_each_field_move": {
            field: disagreements(with_one_field_moved(field), census_fields)
            for field in census_fields
        },
        "both_records_stamp_this_registry": [
            census["registry_version"] == registry["registry_version"],
            inert["registry_version"] == registry["registry_version"],
        ],
    }


@probe("a_run_under_a_ported_host_cannot_be_filed_on_windows")
def _a_run_under_a_ported_host_cannot_be_filed_on_windows() -> dict:
    """Whether a run is still filed under its netloc, character for character.

    The mechanism, not the crash: the crash is what the mechanism costs on one
    platform, and a probe that measured it would answer differently on Linux and on
    Windows, so the record could not be in step on both. What is measured instead is
    platform-independent and is the thing a fix would change — the directory a run
    goes into is the URL's netloc verbatim, and a netloc may contain a colon.

    `example.com` is used for the live call because it is a legal directory name
    everywhere; the ported netlocs are derived rather than typed, so this keeps
    reading if `urlparse` ever normalises one of them away.
    """
    import checklist_runner as runner
    from urllib.parse import urlparse

    with tempfile.TemporaryDirectory() as tmp:
        here = os.getcwd()
        os.chdir(tmp)
        try:
            filed = runner.history_path("example.com", "20260905-000000-000000")
        finally:
            os.chdir(here)

    forbidden = ':*?"<>|'
    ported = [urlparse(u).netloc for u in ("http://localhost:3000/",
                                           "http://127.0.0.1:8000/",
                                           "http://[::1]:8080/")]
    return {
        "directory_a_run_is_filed_in": os.path.basename(os.path.dirname(filed)),
        "the_netloc_is_used_verbatim":
            os.path.basename(os.path.dirname(filed)) == "example.com",
        "netlocs_a_port_produces": ported,
        "characters_windows_forbids_in_a_path_component": sorted(
            {c for n in ported for c in n if c in forbidden}),
        "callers_building_the_same_path": sorted(
            name for name in ("history_path", "previous_run", "run_series")
            if hasattr(runner, name)),
    }


# ── the file, the record, and the comparison ──────────────────────────────────

def entries_in_the_file(path: str = KNOWN_ISSUES) -> list[dict]:
    """Every section 6 entry, in file order, with the marker that closes it.

    The marker sits at the end of the entry and indented into it, which is the one
    placement that changes nothing about how the file renders: an HTML comment at
    column 0 between two list items ends the list, and two of these entries are a
    numbered pair whose numbering that would restart.

    An entry with no marker is reported with `slug: None`, not skipped. A scan that
    passes silently over what it cannot read is the failure this whole file is about.
    """
    with open(path, encoding="utf-8") as stream:
        lines = stream.read().splitlines()
    found, in_section = [], False
    for number, line in enumerate(lines, start=1):
        if SECTION.match(line):
            in_section = line.startswith("## 6.")
            continue
        if not in_section:
            continue
        if ENTRY.match(line):
            found.append({"slug": None, "line": number, "lead": line.strip()[:90]})
            continue
        match = MARKER.match(line.strip())
        if match and found:
            if found[-1]["slug"] is not None:
                found.append({"slug": match.group(1), "line": number,
                              "lead": "second marker on one entry"})
            else:
                found[-1]["slug"] = match.group(1)
    return found


def measure(names: list[str] | None = None) -> dict:
    return {name: _PROBES[name]() for name in (names or sorted(_PROBES))}


def build(previous: dict | None = None) -> dict:
    """Refresh the record, keeping every judgement a person wrote into it."""
    previous = previous or {}
    old = previous.get("entries", {})
    entries = {}
    for found in entries_in_the_file():
        slug = found["slug"]
        if slug is None:
            continue
        kept = dict(old.get(slug, {}))
        kept.setdefault("state", "unclassified")
        kept.setdefault("claim", "")
        kept.setdefault("probe", None)
        if kept["probe"]:
            kept["measured"] = _PROBES[kept["probe"]]()
        else:
            kept.pop("measured", None)
            kept.setdefault("why", "")
        entries[slug] = kept
    probed = [e for e in entries.values() if e["probe"]]
    return {
        "entry_count": len(entries),
        "probed_entry_count": len(probed),
        "unprobed_entry_count": len(entries) - len(probed),
        "entries": entries,
    }


def differences(record: dict) -> list[str]:
    """Every way the record and the file can have come apart, named."""
    problems = []
    found = entries_in_the_file()
    unmarked = [f for f in found if f["slug"] is None]
    for entry in unmarked:
        problems.append("KNOWN-ISSUES.md:%d has no `<!-- ki: slug -->` marker: %s"
                        % (entry["line"], entry["lead"]))
    slugs = [f["slug"] for f in found if f["slug"]]
    duplicates = sorted({slug for slug in slugs if slugs.count(slug) > 1})
    for slug in duplicates:
        problems.append("marker %r is used more than once" % slug)

    recorded = record.get("entries", {})
    for slug in sorted(set(slugs) - set(recorded)):
        problems.append("entry %r is in KNOWN-ISSUES.md and not in the record" % slug)
    for slug in sorted(set(recorded) - set(slugs)):
        problems.append("entry %r is in the record and not in KNOWN-ISSUES.md" % slug)

    # A probe nothing references is a probe that stopped being a witness without
    # anybody deciding to stop witnessing.
    referenced = {entry.get("probe") for entry in recorded.values() if entry.get("probe")}
    for name in sorted(set(_PROBES) - referenced):
        problems.append("probe %r is defined and no entry uses it" % name)

    for slug in sorted(set(slugs) & set(recorded)):
        entry = recorded[slug]
        if entry.get("state") not in STATES:
            problems.append("entry %r has state %r, which is not one of %s"
                            % (slug, entry.get("state"), ", ".join(STATES)))
        if not entry.get("claim"):
            problems.append("entry %r records no claim" % slug)
        name = entry.get("probe")
        if not name:
            if not entry.get("why"):
                problems.append("entry %r has neither a probe nor a reason for having none"
                                % slug)
            continue
        if name not in _PROBES:
            problems.append("entry %r names probe %r, which does not exist" % (slug, name))
            continue
        now = _PROBES[name]()
        if now != entry.get("measured"):
            problems.append(
                "entry %r no longer measures what it recorded.\n"
                "      recorded: %s\n"
                "      measured: %s"
                % (slug, json.dumps(entry.get("measured"), sort_keys=True),
                   json.dumps(now, sort_keys=True)))
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Re-run what KNOWN-ISSUES section 6 says about this tree",
        epilog=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", metavar="FILE", help="write the refreshed record")
    parser.add_argument("--check", metavar="FILE", nargs="?", const=RECORD,
                        help="exit 1 if the record and the tree disagree")
    args = parser.parse_args(argv)

    if args.check:
        with open(args.check, encoding="utf-8") as stream:
            record = json.load(stream)
        problems = differences(record)
        for problem in problems:
            print("  " + problem)
        if problems:
            print("\n%d disagreement(s) between KNOWN-ISSUES.md and the tree it describes."
                  "\nRead the entry, decide whether the tree moved or the entry is now "
                  "wrong, then re-record with\n  python tests/known_issues.py --out %s"
                  % (len(problems), os.path.relpath(args.check, ROOT).replace(os.sep, "/")))
            return 1
        print("%d entries, %d with a probe, all in step with the tree."
              % (record["entry_count"], record["probed_entry_count"]))
        return 0

    previous = {}
    if os.path.exists(RECORD):
        with open(RECORD, encoding="utf-8") as stream:
            previous = json.load(stream)
    record = build(previous)
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(record, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
        print("wrote %s" % os.path.relpath(args.out, ROOT).replace(os.sep, "/"))

    by_state = {}
    for entry in record["entries"].values():
        by_state[entry["state"]] = by_state.get(entry["state"], 0) + 1
    print("%d entries in section 6:" % record["entry_count"])
    for state in sorted(by_state):
        print("  %-14s %3d" % (state, by_state[state]))
    print("\n%d carry a probe; %d carry a written reason for having none."
          % (record["probed_entry_count"], record["unprobed_entry_count"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
