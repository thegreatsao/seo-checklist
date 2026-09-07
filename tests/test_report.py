"""Tests for the report layer: the merge rules and the prioritisation.

The merge is the one place where a text file can overwrite a machine verdict, so
its boundary is worth pinning down. Prioritisation is the one place where a
ranking claims to know what to do first.
"""
import argparse
import contextlib
import html as html_escape
import io
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(ROOT, "skills", "seo-checklist")
sys.path.insert(0, os.path.join(SKILL, "scripts"))

import checklist_runner as runner  # noqa: E402

from checklist_report import (  # noqa: E402
    FAIL, FIX_STATUSES, LLM_PENDING, MANUAL, NA, NEEDS_INPUT, NO_DATA, PASS,
    STATUS_ICON, STATUS_ORDER, WARN, Lang, apply_llm_review,
    fix_rows, history_section, merge_llm_answers, merge_manual_answers,
    phrase_measure, plain_summary, priority_of, provenance_line, render_html,
    render_llm_queue, render_markdown, why_no_score, write_fixes,
)

I18N = os.path.join(SKILL, "resources", "i18n")


class IssueMeasurePhrasing(unittest.TestCase):
    def row(self, got, sample=""):
        measure = {"kind": "issues", "op": "none_severity", "got": got,
                   "want": 0, "levels": ["critical", "high", "medium"]}
        if sample:
            measure["sample"] = sample
        return item("LO-200", WARN if got else PASS, measure=measure)

    def test_an_issue_names_the_problem_instead_of_its_absence(self):
        text = phrase_measure(self.row(1, "No LocalBusiness JSON-LD found"))
        self.assertIn("1 critical/high/medium issue", text)
        self.assertIn("No LocalBusiness JSON-LD found", text)
        self.assertNotIn("No critical/high/medium issues", text)

    def test_a_clean_site_still_reports_no_issues(self):
        self.assertEqual(phrase_measure(self.row(0)),
                         "No critical/high/medium issues reported.")

    def test_russian_selects_the_issue_and_no_issue_strings_correctly(self):
        issue_text = phrase_measure(self.row(1, "Нет LocalBusiness"), Lang("ru"))
        clean_text = phrase_measure(self.row(0), Lang("ru"))
        self.assertIn("Проблем уровня critical/high/medium: 1", issue_text)
        self.assertIn("Проблем уровня critical/high/medium не найдено", clean_text)


def item(item_id, status, **extra):
    row = {"id": item_id, "title": item_id, "category": "content",
           "category_label": "Content", "severity": "high", "effort": "low",
           "status": status, "evidence": "", "fix": "do the thing"}
    row.update(extra)
    return row


def results(*items):
    return {"url": "https://example.com", "mode": "page", "profile": "default",
            "registry_version": "test", "items": list(items),
            "scores": {}, "runs": {}}


class Merge(unittest.TestCase):
    def test_fills_a_pending_item(self):
        data = results(item("CN-047", LLM_PENDING, source="llm"))
        n = merge_llm_answers(data, {"CN-047": {"status": PASS, "evidence": "clean"}})
        self.assertEqual(n, 1)
        self.assertEqual(data["items"][0]["status"], PASS)

    def test_cannot_overwrite_a_script_verdict(self):
        """An answers file must not be able to talk a failure into a pass."""
        data = results(item("CI-001", FAIL, source="script"))
        n = merge_llm_answers(data, {"CI-001": {"status": PASS, "evidence": "trust me"}})
        self.assertEqual(n, 0)
        self.assertEqual(data["items"][0]["status"], FAIL)

    def test_rejects_a_status_outside_the_vocabulary(self):
        data = results(item("CN-047", LLM_PENDING, source="llm"))
        merge_llm_answers(data, {"CN-047": {"status": "GREAT", "evidence": "x"}})
        self.assertEqual(data["items"][0]["status"], LLM_PENDING)

    def test_na_is_an_acceptable_answer(self):
        data = results(item("CN-060", LLM_PENDING, source="llm"))
        n = merge_llm_answers(data, {"CN-060": {"status": NA,
                                                "evidence": "needs a second fetch"}})
        self.assertEqual(n, 1)
        self.assertEqual(data["items"][0]["status"], NA)


class Priority(unittest.TestCase):
    def test_cheap_work_outranks_equally_severe_expensive_work(self):
        cheap = item("A", FAIL, severity="high", effort="low")
        dear = item("B", FAIL, severity="high", effort="high")
        self.assertGreater(priority_of(cheap), priority_of(dear))

    def test_severity_still_dominates_within_one_effort_level(self):
        crit = item("A", FAIL, severity="critical", effort="medium")
        low = item("B", FAIL, severity="low", effort="medium")
        self.assertGreater(priority_of(crit), priority_of(low))

    def test_a_critical_item_is_never_ranked_below_a_low_one(self):
        """Effort may reorder peers; it must not bury a critical failure."""
        crit = item("A", FAIL, severity="critical", effort="high")
        low = item("B", FAIL, severity="low", effort="low")
        self.assertGreaterEqual(priority_of(crit), priority_of(low))


class Queue(unittest.TestCase):
    def test_lens_split_only_takes_its_own_slice(self):
        data = results(item("A", LLM_PENDING, source="llm", lens="copy"),
                       item("B", LLM_PENDING, source="llm", lens="layout"))
        copy_q = render_llm_queue(data, "copy")
        self.assertIn("### A", copy_q)
        self.assertNotIn("### B", copy_q)
        self.assertIn("seo-llm-copy", copy_q)

    def test_combined_queue_holds_everything(self):
        data = results(item("A", LLM_PENDING, source="llm", lens="copy"),
                       item("B", LLM_PENDING, source="llm", lens="layout"))
        both = render_llm_queue(data)
        self.assertIn("### A", both)
        self.assertIn("### B", both)


class Localisation(unittest.TestCase):
    def test_every_shipped_translation_parses_and_declares_a_language(self):
        for name in os.listdir(I18N):
            if not name.endswith(".json"):
                continue
            with open(os.path.join(I18N, name), encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(data.get("lang"), name[:-5], name)
            for block in ("strings", "statuses", "severities", "efforts"):
                self.assertIn(block, data, f"{name} has no {block}")

    def test_unknown_language_is_refused_rather_than_silently_english(self):
        with self.assertRaises(FileNotFoundError):
            Lang("xx")

    def test_translated_report_renders_and_keeps_the_numbers(self):
        data = results(item("A", FAIL))
        from checklist_runner import score
        data["scores"] = score(data["items"])
        out = render_markdown(data, Lang("ru"))
        self.assertIn("Аудит по чеклисту", out)
        self.assertIn("A", out)

    def test_english_is_the_default_and_needs_no_file(self):
        data = results(item("A", PASS))
        from checklist_runner import score
        data["scores"] = score(data["items"])
        self.assertIn("SEO Checklist Audit", render_markdown(data))

    def test_a_partly_translated_language_names_what_is_still_english(self):
        """A reader cannot tell a layer that was left in English from a layer that
        was considered and kept. The report has to say which.

        Hobbles a copy rather than asserting the shipped file is incomplete. Until
        0.19.0 this test read `Lang("ru")` directly and passed because the two item
        layers were genuinely empty — so completing them broke a test that was
        supposed to be about the *warning*, and a test that fails when the gap it
        describes is closed is a test pinned to a defect."""
        ru = Lang("ru")
        ru.data = dict(ru.data, item_titles={}, item_fixes={})
        reported = ru.untranslated()
        self.assertIn("item titles", reported)
        self.assertIn("recommendations", reported)

    def test_a_fully_translated_language_warns_about_nothing(self):
        """The other half, and the one that makes the warning worth reading: it has
        to be able to go quiet. A caveat that is always printed is a caveat nobody
        reads by the third report."""
        self.assertEqual(Lang("ru").untranslated(), [])

    def test_the_report_chrome_is_counted_rather_than_declared_complete(self):
        """This claim was wrong once, and wrong in the flattering direction.

        `untranslated()` named the two opt-in layers and said nothing about the
        report's own wording, on the assumption that it was complete. Six of the
        fifty-one strings had no Russian at all — the whole "what was audited" block,
        which is the highest-stakes prose in the document — and `t()` falls back to
        English silently, so nothing showed.

        The gap is closed as of 0.15.0: `ru.json` carries all of them, and by then it
        was nineteen rather than six, because 0.12.0's "since the previous audit"
        section arrived untranslated and the count was the only thing that noticed.
        So this test no longer measures the file — it removes a string the report asks
        for and checks that the counter finds it. The old version asserted `missing`
        was non-empty, which would have started failing the moment the work was done,
        and a test that punishes the fix is a test that keeps the defect.
        """
        lang = Lang("ru")
        self.assertEqual(lang.missing_strings(), [],
                         "ru.json is expected complete; add the Russian for these")
        # Every key the report asks for is a key this counter can be asked about.
        with open(os.path.join(SKILL, "scripts", "checklist_report.py"),
                  encoding="utf-8") as f:
            source = f.read()
        for key in ("w_private_host", "since_last", "what_was_audited"):
            self.assertIn(f'"{key}"', source)
            hobbled = Lang("ru")
            hobbled.data["strings"] = {k: v for k, v in lang.data["strings"].items()
                                       if k != key}
            self.assertIn(key, hobbled.missing_strings())
            self.assertTrue(any("report string" in w
                                for w in hobbled.untranslated()))

    def test_english_reports_nothing_untranslated(self):
        self.assertEqual(Lang("en").untranslated(), [])

    def test_a_filled_block_drops_out_of_the_warning(self):
        lang = Lang("ru")
        lang.data["item_titles"] = {"A": "Заголовок"}
        self.assertNotIn("item titles", lang.untranslated())
        lang.data["item_fixes"] = {"A": "Сделать"}
        self.assertNotIn("recommendations", lang.untranslated())

    def test_every_category_in_the_registry_has_a_translated_explanation(self):
        """The category explanation is the layer a non-specialist reads. A missing
        one silently falls back to English in the middle of a translated page,
        which is exactly the ambiguity `untranslated()` exists to remove."""
        with open(os.path.join(SKILL, "resources", "config",
                               "checklist.json"), encoding="utf-8") as f:
            categories = {i["category"] for i in json.load(f)["items"]}
        for name in os.listdir(I18N):
            if not name.endswith(".json"):
                continue
            translated = set(Lang(name[:-5]).data.get("categories", {}))
            missing = sorted(categories - translated)
            self.assertEqual(missing, [], f"{name} is missing: {missing}")


class SecondReading(unittest.TestCase):
    """An unopposed judgement reported with the confidence of a measured status is
    the LLM queue's weak point. The reviewer's power is deliberately asymmetric:
    it can withdraw confidence, never substitute a verdict."""

    def answered(self, status=PASS, evidence="looked fine"):
        row = item("CN-047", status, source="llm(answered)",
                   evidence=f"LLM: {evidence}")
        data = results(row)
        from checklist_runner import score
        data["scores"] = score(data["items"])
        return data

    def test_agreement_corroborates_and_keeps_the_verdict(self):
        data = self.answered(PASS)
        stats = apply_llm_review(data, {"CN-047": {"status": "PASS",
                                                   "evidence": "read it too"}})
        row = data["items"][0]
        self.assertEqual(stats["corroborated"], 1)
        self.assertEqual(row["status"], PASS)
        self.assertTrue(row["corroborated"])
        self.assertIn("second reading agrees", row["evidence"])

    def test_disagreement_returns_the_item_to_undecided(self):
        """Not a winner, not an average. Two careful readings that conflict mean
        the page did not settle the question."""
        data = self.answered(PASS)
        stats = apply_llm_review(data, {"CN-047": {"status": "FAIL",
                                                   "evidence": "the H1 lies"}})
        row = data["items"][0]
        self.assertEqual(stats["contested"], 1)
        self.assertEqual(row["status"], NO_DATA)
        self.assertEqual(row["contested"], {"first": PASS, "second": FAIL})
        self.assertIn("PASS", row["evidence"])
        self.assertIn("FAIL", row["evidence"])

    def test_a_contested_item_narrows_what_the_score_speaks_for(self):
        """Disagreement returns the item to NO_DATA, so the score is computed over
        less of the registry — which is what the audit not knowing looks like."""
        data = self.answered(PASS)
        before = data["scores"]["weight_pct"]
        apply_llm_review(data, {"CN-047": {"status": "FAIL", "evidence": "no"}})
        self.assertLess(data["scores"]["weight_pct"], before)

    def test_it_cannot_touch_a_script_verdict(self):
        """A measurement is not an opinion. Letting a reviewer contest one would
        make every script result negotiable."""
        data = results(item("CI-001", PASS, source="script"))
        from checklist_runner import score
        data["scores"] = score(data["items"])
        stats = apply_llm_review(data, {"CI-001": {"status": "FAIL", "evidence": "x"}})
        self.assertEqual(stats["skipped"], 1)
        self.assertEqual(data["items"][0]["status"], PASS)

    def test_it_cannot_answer_an_unanswered_item(self):
        """That would make the reviewer the primary judge, with nobody deciding to
        promote it."""
        data = results(item("CN-047", LLM_PENDING))
        from checklist_runner import score
        data["scores"] = score(data["items"])
        stats = apply_llm_review(data, {"CN-047": {"status": "PASS", "evidence": "x"}})
        self.assertEqual(stats["skipped"], 1)
        self.assertEqual(data["items"][0]["status"], LLM_PENDING)

    def test_an_invalid_status_is_ignored_not_applied(self):
        data = self.answered(PASS)
        stats = apply_llm_review(data, {"CN-047": {"status": "PROBABLY", "evidence": "x"}})
        self.assertEqual(stats["skipped"], 1)
        self.assertEqual(data["items"][0]["status"], PASS)

    def test_items_the_reviewer_says_nothing_about_are_untouched(self):
        data = self.answered(PASS)
        apply_llm_review(data, {})
        self.assertEqual(data["items"][0]["status"], PASS)
        self.assertNotIn("corroborated", data["items"][0])

    def test_the_queue_tells_the_reader_a_second_pass_exists(self):
        data = results(item("CN-047", LLM_PENDING, lens="copy"))
        out = render_llm_queue(data, "copy")
        self.assertIn("--llm-review", out)
        self.assertIn("seo-llm-adversary", out)


class NoScoreSurvivesEveryRenderer(unittest.TestCase):
    """The runner refuses to print a score when nothing was read. Every surface
    downstream has to refuse it too — the HTML tile printed the literal `None`,
    which reads as a broken tool in the one file that gets handed to a client."""

    def _unread(self):
        from checklist_runner import score
        data = results(item("A", "NO_DATA"))
        data["scores"] = score(data["items"])
        data["entry_reachable"] = False
        data["entry_error"] = "soft 404: a 200 response titled '404 Not Found'"
        return data

    def _reachable_but_undecided(self):
        """The case `openspec/specs/scoring/` A.4 names: the site answered, and no
        item reached a quality verdict. `score()` returns an absent headline for it,
        and every surface printed `None/100` because it asked a different question."""
        from checklist_runner import score
        data = results(item("A", "NO_DATA"))
        data["scores"] = score(data["items"])
        data["entry_reachable"] = True
        data["entry_error"] = ""
        return data

    def test_the_score_is_none_when_nothing_was_decided(self):
        self.assertIsNone(self._unread()["scores"]["seo_score"])

    def test_no_surface_prints_a_number_for_a_reachable_run_that_decided_nothing(self):
        """SCR-3's third scenario. Four surfaces branched on `entry_reachable is
        False` where the question is whether a score exists, and the two differ in
        exactly one direction: a run that read the site and decided nothing. It has a
        reachable entry and an absent score, and each of them rendered `None`.

        `score()` was right throughout — the absence was computed and not delivered,
        which is why a unit test on `score()` could not see it."""
        data = self._reachable_but_undecided()
        md, html_out = render_markdown(data), render_html(data)
        # The spellings a rendered `None` actually takes, not a bare substring
        # search: the Markdown legitimately contains the word in "None of them
        # lowers the score", and an assertion that trips on prose gets loosened by
        # whoever hits it next rather than tightened.
        for spelling in ("None/100", "None%", "None</", ">None<", "| None"):
            with self.subTest(spelling=spelling):
                self.assertNotIn(spelling, md)
                self.assertNotIn(spelling, html_out)

    def test_the_two_reasons_for_an_absent_score_are_different_sentences(self):
        """An unreadable entry is a fact about the site or the network; a reachable
        site that decided nothing is a fact about the audit. Telling the second
        reader the page could not be read would be false, and it is the sentence
        they got.

        Asserted on what each sentence *claims*, not on the two being unequal: the
        first version compared them for inequality and passed a mutation that made
        the undecided branch return the unreadable text, because the two carry
        different error strings and were still unequal."""
        unread, undecided = self._unread(), self._reachable_but_undecided()
        _, _, said = why_no_score(undecided)
        self.assertIn("answered", said)
        self.assertNotIn("entry page", said)
        self.assertNotIn("nothing was measured", said)
        _, _, other = why_no_score(unread)
        self.assertIn("entry page", other)
        self.assertNotIn("answered", other)

    def test_all_three_surfaces_take_the_sentence_from_one_place(self):
        """A helper read by one surface and inlined in the others is how they
        diverged in the first place, and it happened again inside this release: the
        first cut returned the body alone and left each surface to pick its own
        heading from `entry_reachable`. Every string a no-score run shows comes from
        `why_no_score` now, and this holds each surface to it."""
        for data in (self._unread(), self._reachable_but_undecided()):
            headline, title, body = why_no_score(data)
            with self.subTest(reachable=data["entry_reachable"]):
                self.assertEqual(plain_summary(data), [headline])
                md = render_markdown(data)
                self.assertIn(title, md)
                self.assertIn(body, md)
                # Escaped, because the HTML renderer escapes it and an assertion on
                # the raw string would pass only for sentences with no punctuation.
                self.assertIn(html_escape.escape(body), render_html(data))

    def test_a_run_with_a_score_has_no_reason_to_give(self):
        """The floor. A `why_no_score` that answered unconditionally would satisfy
        every assertion above and blank the score on a good run."""
        from checklist_report import why_no_score
        data = results(item("A", PASS))
        from checklist_runner import score
        data["scores"] = score(data["items"])
        self.assertEqual(why_no_score(data), ("", "", ""))

    def test_the_markdown_says_why_instead_of_a_number(self):
        out = render_markdown(self._unread())
        self.assertIn("could not be read", out)
        self.assertNotIn("None/100", out)

    def test_the_html_prints_no_number_at_all(self):
        """Asserted on the intent, not on the wording: no number anywhere, and an
        explanation in its place. The exact sentence has changed once already."""
        from checklist_report import render_html
        out = render_html(self._unread())
        self.assertNotIn(">None<", out)
        self.assertNotIn("None/100", out)
        self.assertIn("could not be read", out)


class WhatWasAudited(unittest.TestCase):
    """Four facts the runner records and prints, and the report never mentioned.

    Each one says the numbers may not describe the page a visitor gets: the run was
    allowed off the public internet, the entry page looked like an interstitial and
    was scored anyway, the page carried almost no text, or some verdicts came from a
    file the operator measured elsewhere. The report is what gets handed to
    somebody, so an omission here is the same failure as printing a score for a site
    that was never read — one surface further along.
    """

    def _scored(self, **extra):
        from checklist_runner import score
        data = results(item("A", PASS), item("B", FAIL))
        data["scores"] = score(data["items"])
        data["entry_reachable"] = True
        data.update(extra)
        return data

    def test_a_private_run_is_named_on_every_surface(self):
        from checklist_report import provenance_warnings, render_html
        data = self._scored(allow_private=True, entry_private=True)
        self.assertTrue(any("only reachable" in w for w in provenance_warnings(data)))
        for out in (render_markdown(data), render_html(data)):
            self.assertIn("--allow-private", out)
            self.assertIn("staging", out)

    def test_the_flag_and_a_private_host_are_different_claims(self):
        """`--allow-private` says what was permitted; `entry_private` says what
        happened. Only the second means the external-API items were undecidable, and
        saying so about a public site would be a caveat on nothing."""
        from checklist_report import provenance_warnings
        permitted = provenance_warnings(self._scored(allow_private=True,
                                                    entry_private=False))
        self.assertEqual(len(permitted), 1)
        self.assertNotIn("could not be decided", permitted[0])
        happened = provenance_warnings(self._scored(allow_private=True,
                                                   entry_private=True))
        self.assertIn("could not be decided", happened[0])

    def test_a_scored_interstitial_says_so(self):
        """A --no-page-guard run produced a clean-looking deliverable that never
        mentioned it had graded a Cloudflare challenge."""
        from checklist_report import provenance_warnings, render_html
        data = self._scored(entry_guard="bot_challenge", entry_guard_enforced=False)
        self.assertTrue(any("bot challenge" in w for w in provenance_warnings(data)))
        self.assertIn("bot challenge", render_html(data))
        self.assertIn("bot challenge", render_markdown(data))

    def test_a_verdict_from_a_supplied_measurement_says_where_it_came_from(self):
        """"LCP 820 ms — PASS" looks identical whether the tool measured it or was
        handed it in a file, and eight items can be decided the second way."""
        from checklist_report import provenance_warnings, render_html
        data = self._scored(artifacts={
            "cwv_json": {"path": "/t/cwv.json", "describes": "https://example.com/",
                         "matches_audited_url": True}})
        self.assertTrue(any("supplied with the run" in w
                            for w in provenance_warnings(data)))
        for out in (render_markdown(data), render_html(data)):
            self.assertIn("cwv", out)

    def test_a_rejected_artifact_is_not_advertised_as_evidence(self):
        """It decided nothing — its items are NO_DATA with the reason — so naming it
        here would tell the reader a measurement was used when it was refused."""
        from checklist_report import provenance_warnings
        data = self._scored(artifacts={
            "cwv_json": {"path": "/t/cwv.json", "describes": "https://other.example/",
                         "matches_audited_url": False}})
        self.assertEqual(provenance_warnings(data), [])

    def test_an_enforced_guard_is_not_a_caveat(self):
        """When the guard stopped the run there is no score to qualify, and the
        unreachable banner already explains itself."""
        from checklist_report import provenance_warnings
        data = self._scored(entry_guard="soft_404", entry_guard_enforced=True)
        self.assertEqual(provenance_warnings(data), [])

    def test_a_thin_page_is_named_but_an_unread_one_is_not(self):
        from checklist_report import provenance_warnings
        thin = self._scored(entry_thin=True, entry_visible_words=12)
        self.assertTrue(any("12" in w for w in provenance_warnings(thin)))
        unread = self._scored(entry_thin=True, entry_visible_words=0,
                             entry_reachable=False)
        self.assertEqual(provenance_warnings(unread), [])

    def test_a_clean_public_run_carries_no_caveat(self):
        from checklist_report import provenance_warnings
        self.assertEqual(provenance_warnings(self._scored()), [])


class HistoryReachesTheFile(unittest.TestCase):
    """`.seo-runs/` held every run and the comparison reached a terminal at best.

    A checklist is a thing people re-run, so the question "did last month's fixes
    work" is the second one a returning reader has — and the report could not answer
    it from data that was already on disk.
    """

    def _data(self, *changes, **extra):
        from checklist_runner import score
        data = results(item("CN-047", FAIL), item("CN-048", PASS))
        # A real `scores` block, because both renderers read more of it than the
        # history section does and a hand-made stub would only test this test.
        data["scores"] = dict(score(data["items"]), seo_score=71, weight_pct=55)
        data["entry_reachable"] = True
        data["compared_with"] = {"started_at": "2026-07-01T09:30:00+00:00",
                                 "seo_score": 64, "weight_pct": 50,
                                 "registry_version": "test"}
        data["diff"] = list(changes)
        data.update(extra)
        return data

    def _change(self, item_id, was, now, direction, severity="high"):
        return {"id": item_id, "title": f"{item_id} title", "from": was, "to": now,
                "direction": direction, "severity": severity, "evidence": ""}

    def test_no_baseline_means_no_section(self):
        """A first audit has nothing to compare with, and an empty "since last time"
        heading would imply there was a last time."""
        from checklist_runner import score
        data = results(item("CN-047", FAIL))
        data["scores"] = score(data["items"])
        data["entry_reachable"] = True
        data["compared_with"] = None
        data["diff"] = None
        self.assertEqual(history_section(data), [])
        self.assertNotIn("Since the previous audit", render_markdown(data, Lang()))

    def test_the_baseline_is_named_not_implied(self):
        """"Since the previous run" is not a date. A comparison whose other half is
        anonymous cannot be checked by the person being shown it."""
        text = "\n".join(history_section(self._data()))
        self.assertIn("2026-07-01T09:30", text)
        self.assertIn("64", text)
        self.assertIn("71", text)

    def test_a_fix_and_a_regression_are_told_apart(self):
        text = "\n".join(history_section(self._data(
            self._change("CN-047", FAIL, PASS, "improved"),
            self._change("CN-048", PASS, FAIL, "regressed"))))
        fixed = text.index("Fixed since then")
        worse = text.index("Got worse")
        self.assertLess(fixed, worse, "the good news should not bury the bad")
        self.assertIn("| CN-047 |", text)
        self.assertIn("| CN-048 |", text)

    def test_losing_the_evidence_is_not_reported_as_a_regression(self):
        """PASS -> NO_DATA is the run losing the ability to tell, not the site
        getting worse. Filing it under regressions would tell a client their site
        broke when the measurement broke."""
        text = "\n".join(history_section(self._data(
            self._change("CN-047", PASS, NO_DATA, "evidence"))))
        self.assertNotIn("Got worse", text)
        self.assertIn("not on the site", text)

    def test_a_changed_registry_is_said_out_loud(self):
        """A score that moved because the checklist changed is not a site that
        moved, and a reader cannot know that unless told."""
        data = self._data(self._change("CN-047", FAIL, PASS, "improved"),
                          diff_note="previous run used registry abc, this one def")
        self.assertIn("registry abc", "\n".join(history_section(data)))

    def test_both_renderers_carry_it(self):
        data = self._data(self._change("CN-047", FAIL, PASS, "improved"))
        self.assertIn("Since the previous audit", render_markdown(data, Lang()))
        html = render_html(data, Lang())
        self.assertIn("Since the previous audit", html)
        self.assertIn("+7", html, "the score movement is not shown")


class TheFixListIsMachineReadable(unittest.TestCase):
    """`checklist-results.json` is the audit log, not a task list. Getting the
    actionable part into a tracker meant parsing the report or filtering the log."""

    def _data(self):
        return results(
            item("A-001", FAIL, severity="critical", effort="low"),
            item("A-002", WARN, severity="medium", effort="high"),
            item("A-003", MANUAL, severity="high"),
            item("A-004", PASS),
            item("A-005", NO_DATA),
            item("A-006", LLM_PENDING, source="llm"),
            item("A-007", NA),
        )

    def test_only_the_actionable_items_are_in_it(self):
        """NO_DATA is not a fix — it is usually work for whoever runs the audit, not
        for whoever owns the site — and LLM_PENDING is a question still waiting for
        an answer. Either one would fill a sprint with the auditor's own business."""
        ids = [r["id"] for r in fix_rows(self._data())]
        self.assertEqual(set(ids), {"A-001", "A-002", "A-003"})

    def test_it_is_ordered_the_way_the_report_orders_it(self):
        rows = fix_rows(self._data())
        self.assertEqual([r["id"] for r in rows][0], "A-001")
        self.assertEqual([r["priority"] for r in rows],
                         sorted((r["priority"] for r in rows), reverse=True))

    def test_the_status_travels_with_the_row(self):
        """A tracker importing these has to be able to tell a failing check from a
        task nobody could automate."""
        by_id = {r["id"]: r for r in fix_rows(self._data())}
        self.assertEqual(by_id["A-003"]["status"], MANUAL)
        self.assertEqual(by_id["A-001"]["status"], FAIL)

    def test_the_url_column_says_what_it_actually_is(self):
        """Most items record no page: a page-level check over a sample reports the
        worst page's verdict without its address, and a site-level check has no page
        to name. A column called `url` would be read as "fix this page"."""
        row = fix_rows(self._data())[0]
        self.assertIn("audited_url", row)
        self.assertNotIn("url", set(row) - {"audited_url"})

    def test_csv_and_json_hold_the_same_rows(self):
        import csv as _csv
        import tempfile
        data = self._data()
        with tempfile.TemporaryDirectory() as d:
            csv_path = write_fixes(os.path.join(d, "f.csv"), data)
            json_path = write_fixes(os.path.join(d, "f.json"), data)
            with open(csv_path, encoding="utf-8-sig", newline="") as f:
                from_csv = [r["id"] for r in _csv.DictReader(f)]
            with open(json_path, encoding="utf-8") as f:
                from_json = [r["id"] for r in json.load(f)]
        self.assertEqual(from_csv, from_json)
        self.assertEqual(from_csv, [r["id"] for r in fix_rows(data)])

    def test_csv_guards_formula_cells_but_json_preserves_them(self):
        import csv as _csv
        import tempfile
        evidence = ["=SUM(1,1)", "+cmd", "-ordinary-dash", "@function", "ordinary"]
        data = results(*(item(f"A-{index}", FAIL, evidence=value)
                         for index, value in enumerate(evidence)))
        with tempfile.TemporaryDirectory() as d:
            csv_path = write_fixes(os.path.join(d, "f.csv"), data)
            json_path = write_fixes(os.path.join(d, "f.json"), data)
            with open(csv_path, encoding="utf-8-sig", newline="") as f:
                csv_rows = {row["id"]: row for row in _csv.DictReader(f)}
            with open(json_path, encoding="utf-8") as f:
                json_rows = {row["id"]: row for row in json.load(f)}
        expected = {f"A-{index}": value for index, value in enumerate(evidence)}
        for item_id, value in expected.items():
            guarded = "'" + value if value[0] in "=+-@" else value
            self.assertEqual(csv_rows[item_id]["evidence"], guarded)
            self.assertEqual(json_rows[item_id]["evidence"], value)
            self.assertEqual(csv_rows[item_id]["priority"],
                             str(json_rows[item_id]["priority"]))
            self.assertFalse(csv_rows[item_id]["priority"].startswith("'"))

    def test_the_csv_opens_in_a_spreadsheet_without_mojibake(self):
        """Excel reads a plain UTF-8 CSV as Latin-1, so a BOM is the difference
        between an item title and a row of garbage. The destination for this file is
        overwhelmingly likely to be somebody's spreadsheet."""
        import tempfile
        data = results(item("A-001", FAIL, title="Заголовок с не-ASCII"))
        with tempfile.TemporaryDirectory() as d:
            path = write_fixes(os.path.join(d, "f.csv"), data)
            with open(path, "rb") as f:
                raw = f.read()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"), "no UTF-8 BOM")
        self.assertIn("Заголовок".encode(), raw)
class EveryStatusReachesEverySurface(unittest.TestCase):
    """A status is not added until every place that lists one knows about it.

    The lesson this class exists for is 0.14.0's: a rule guarded at its own call
    site is guarded at one call site. `NEEDS_INPUT` had to be threaded into an icon
    table, a meaning table, a stylesheet, a bar legend, a filter row and two report
    renderers, and missing any one of them fails in the quietest possible way — the
    count is simply absent from a document nobody diffs against the run.
    """

    def statuses(self):
        """Every status the runner can put on an item, read from the runner rather
        than restated here — a list maintained beside the thing it checks has the
        same blind spot as the thing it checks."""
        sys.path.insert(0, os.path.join(SKILL, "scripts"))
        import checklist_runner as r
        return {r.PASS, r.FAIL, r.WARN, r.NO_DATA, r.NEEDS_INPUT, r.LLM_PENDING,
                r.MANUAL, r.NA}

    def test_the_report_can_name_every_status_the_runner_emits(self):
        missing = self.statuses() - set(STATUS_ICON)
        self.assertFalse(missing, f"no icon for {missing}")
        self.assertEqual(set(STATUS_ORDER), self.statuses())

    def test_a_run_with_every_status_renders_all_of_them(self):
        """Both renderers, one payload, every status present exactly once."""
        rows = [item(f"X-{n}", st) for n, st in enumerate(sorted(self.statuses()))]
        data = results(*rows)
        data["scores"] = {"seo_score": 50, "weight_pct": 40, "decided": 3,
                          "applicable": 7, "total_items": 8,
                          "weight_decided": 12, "weight_applicable": 30,
                          "partition": {"decided": 3, "waiting_on_you": 2,
                                        "needs_a_person": 1, "undecided": 1,
                                        "not_applicable": 1},
                          "waiting_on_you": {"llm_pending": 1, "needs_input": 1},
                          "status_counts": {st: 1 for st in self.statuses()},
                          "by_category": {}}
        md = render_markdown(data)
        html_out = render_html(data)
        for st in self.statuses():
            self.assertIn(STATUS_ICON[st], md, f"{st} missing from the markdown")
            self.assertIn(STATUS_ICON[st], html_out, f"{st} missing from the HTML")

    def test_an_input_nobody_supplied_is_not_somebody_elses_fix(self):
        """NEEDS_INPUT is the auditor's work, so it must not reach the fix list.

        The same rule NO_DATA and LLM_PENDING already follow: filling a client's
        sprint with the auditor's unfinished business is the failure `--fixes` was
        scoped to avoid."""
        self.assertNotIn(NEEDS_INPUT, FIX_STATUSES)
        rows = fix_rows(results(item("A-1", NEEDS_INPUT), item("A-2", FAIL)))
        self.assertEqual([r["id"] for r in rows], ["A-2"])

    def test_neither_renderer_prints_a_missing_number(self):
        """A renamed score key must not surface as the word None to a client.

        0.16 renamed `coverage_pct` and the markdown history section was updated
        while the HTML one was not, because the two call sites hold the same string
        and only one had a test. It rendered "coverage None%" into a delivered
        document and nothing failed. Both renderers are asserted here, over a
        payload that exercises the history section, so the next renamed key cannot
        reach a reader through the untested half.
        """
        data = results(item("A-1", PASS), item("A-2", FAIL))
        from checklist_runner import score
        data["scores"] = score(data["items"])
        data["entry_reachable"] = True
        data["compared_with"] = {"started_at": "2026-07-01T09:30:00+00:00",
                                 "seo_score": 64, "weight_pct": 50,
                                 "registry_version": "test"}
        data["diff"] = [{"id": "A-1", "kind": "improved", "from": FAIL, "to": PASS,
                         "title": "A-1"}]
        for name, text in (("markdown", render_markdown(data)),
                           ("html", render_html(data))):
            self.assertNotIn("None", text, f"{name} printed a missing number")

    def test_the_russian_report_names_the_new_status_and_its_section(self):
        ru = Lang("ru")
        for key in ("needs_input", "needs_input_note", "b_waiting", "score_weight",
                    "partition_note"):
            self.assertNotEqual(ru.t(key, "<english>"), "<english>",
                                f"{key} falls back to English")
        self.assertNotEqual(ru.status(NEEDS_INPUT, "<english>"), "<english>")


class TheQueueAsksForWhatItIsAbout(unittest.TestCase):
    def test_the_skeleton_names_the_items_in_that_file(self):
        """A per-lens queue printed a JSON example for two fixed ids whatever it
        was asking about, so a file about IN-126 and IN-130 showed a skeleton for
        CN-047 and CN-060. A merge keyed on an id that is not pending applies
        nothing, and before 0.16 it said nothing either."""
        data = results(item("IN-126", LLM_PENDING, lens="locale"),
                       item("CN-047", LLM_PENDING, lens="copy"))
        queue = render_llm_queue(data, lens="locale")
        self.assertIn('"IN-126": { "status": "", "evidence": "" }', queue)
        self.assertNotIn("CN-047", queue)


class AnswersFromAPerson(unittest.TestCase):
    """`--manual-answers`, and the guards that keep it from becoming a score dial.

    Thirty-four items — 16% of the registry — had no way back into a run before
    0.16, so the number they sat behind could only fall. Giving a person a way to
    answer them is also giving somebody a way to write PASS thirty-four times, and
    every test here is about the difference.
    """

    def answered(self, *answers):
        data = results(item("LO-199", MANUAL), item("CN-047", FAIL),
                       item("KW-070", LLM_PENDING))
        merged = {}
        for a in answers:
            merged.update(a)
        n = merge_manual_answers(data, merged)
        return data, n, {i["id"]: i for i in data["items"]}

    def test_it_answers_a_manual_item(self):
        data, n, rows = self.answered(
            {"LO-199": {"status": PASS, "evidence": "profile claimed, NAP matches"}})
        self.assertEqual(n, 1)
        self.assertEqual(rows["LO-199"]["status"], PASS)
        self.assertIn("NAP matches", rows["LO-199"]["evidence"])

    def test_a_claimed_verdict_is_never_recorded_as_measured(self):
        """The whole guard. A person's word and a measurement carry the same
        weight in the score, so the only thing that can keep them apart in a
        delivered report is the record of which was which."""
        _, _, rows = self.answered(
            {"LO-199": {"status": PASS, "evidence": "checked in the UI"}})
        self.assertEqual(rows["LO-199"]["decided_by"], "claimed")

    def test_an_answer_with_no_reason_is_refused(self):
        """A PASS with nothing beside it is indistinguishable from a tick made to
        clear the list, and thirty-four of those would move the score with nothing
        for the reader to argue with."""
        for empty in ("", "   ", None):
            _, n, rows = self.answered({"LO-199": {"status": PASS,
                                                   "evidence": empty}})
            self.assertEqual(n, 0, f"accepted evidence {empty!r}")
            self.assertEqual(rows["LO-199"]["status"], MANUAL)

    def test_it_cannot_touch_a_verdict_a_script_reached(self):
        _, n, rows = self.answered({"CN-047": {"status": PASS, "evidence": "trust me"}})
        self.assertEqual(n, 0)
        self.assertEqual(rows["CN-047"]["status"], FAIL)

    def test_it_cannot_answer_the_language_models_queue(self):
        """The two merges are deliberately separate doors. One file that could
        answer both would let a person quietly settle the 36 items the queue
        exists to make somebody actually read the page for."""
        _, n, rows = self.answered({"KW-070": {"status": PASS, "evidence": "fine"}})
        self.assertEqual(n, 0)
        self.assertEqual(rows["KW-070"]["status"], LLM_PENDING)

    def test_an_invalid_status_is_refused(self):
        _, n, _ = self.answered({"LO-199": {"status": "DONE", "evidence": "yes"}})
        self.assertEqual(n, 0)

    def test_the_report_discloses_what_was_not_measured(self):
        """A run where 3 of 109 decided items are somebody's word is a different
        document from one where all 109 were measured, and until 0.16 the two
        printed identically."""
        L = Lang()
        self.assertEqual(provenance_line({"decided": 5, "decided_by": {"measured": 5}}, L), "")
        line = provenance_line({"decided": 5, "decided_by": {"measured": 3, "claimed": 2}}, L)
        self.assertIn("2", line)
        self.assertIn("person", line)

    def test_both_renderers_carry_the_disclosure(self):
        from checklist_runner import score
        data = results(item("A-1", PASS, decided_by="measured"),
                       item("A-2", PASS, decided_by="claimed"))
        data["scores"] = score(data["items"])
        data["entry_reachable"] = True
        self.assertEqual(data["scores"]["decided_by"], {"measured": 1, "claimed": 1})
        for name, text in (("markdown", render_markdown(data)),
                           ("html", render_html(data))):
            self.assertIn("on their word", text, f"{name} hides the claimed verdict")


class TheSensitivityToolMeasuresTheRealScore(unittest.TestCase):
    """`tools/audit_score_sensitivity.py` re-scores finished runs under other weight
    tables. A tool that computed the score its own way would produce a spread about
    a number nobody is shown, so the first thing to pin is that its arithmetic and
    the runner's are the same one."""

    def setUp(self):
        sys.path.insert(0, os.path.join(SKILL, "tools"))
        import audit_score_sensitivity as sens
        self.sens = sens

    def rows(self):
        return [item("A-1", PASS, severity="critical"),
                item("A-2", FAIL, severity="critical"),
                item("A-3", WARN, severity="low"),
                item("A-4", PASS, severity="medium"),
                item("A-5", NO_DATA, severity="high")]

    def test_it_reproduces_the_headline_the_runner_reports(self):
        from checklist_runner import SEVERITY_WEIGHT, score
        items = self.rows()
        self.assertEqual(round(self.sens.headline(self.sens.scored_items(
            {"items": items}), SEVERITY_WEIGHT)), score(items)["seo_score"])

    def test_it_scores_only_what_was_decided(self):
        """NO_DATA must not enter, exactly as it does not enter the real score —
        otherwise every undecided item would read as a failure and the spread would
        be measuring the wrong thing."""
        self.assertEqual([i["id"] for i in self.sens.scored_items({"items": self.rows()})],
                         ["A-1", "A-2", "A-3", "A-4"])

    def test_flat_weights_are_the_unweighted_pass_rate(self):
        """The null hypothesis has to actually be the null hypothesis: under
        1/1/1/1 the score is the plain credit-per-item mean, so a run where the
        shipped table lands on the same number is a run where weighting did
        nothing."""
        items = self.sens.scored_items({"items": self.rows()})
        flat = self.sens.CANDIDATE_WEIGHTS["flat (1/1/1/1)"]
        credit = 1.0 + 0.0 + 0.5 + 1.0
        self.assertEqual(self.sens.headline(items, flat),
                         round(100 * credit / len(items), 1))

    def test_the_pass_rates_add_up_to_the_items_scored(self):
        rates = self.sens.pass_rates(self.sens.scored_items({"items": self.rows()}))
        self.assertEqual(sum(n for n, _ in rates.values()), 4)

    def test_the_fix_order_is_the_one_the_report_uses(self):
        """The effort half compares fix lists, so it has to build the same list the
        report builds — a different ordering would measure a ranking nobody sees."""
        from checklist_report import EFFORT_COST
        from checklist_runner import SEVERITY_WEIGHT
        items = self.sens.scored_items({"items": self.rows()})
        mine = self.sens.fix_order(items, SEVERITY_WEIGHT, EFFORT_COST)
        theirs = [r["id"] for r in fix_rows(results(*items))
                  if r["status"] in (FAIL, WARN)]
        self.assertEqual(mine, theirs)


class TheRegistryIsTranslatedOrTheGapIsCounted(unittest.TestCase):
    """`item_titles` and `item_fixes` against the registry they translate.

    Both were empty from 0.2.0 to 0.18.0, so `--lang ru` produced a document whose
    own prose was Russian and whose 214 item titles and recommendations were not.
    They are complete as of 0.19.0, and this is what keeps them that way: a
    translated title is a second copy of the registry's wording, and a second copy
    drifts the moment either side changes.

    The claim is *computed*. This file has twice declared a completeness it did not
    have — 0.12.0's diff section arrived untranslated after the note was written, and
    the caveat block turned out to be 19 strings while the note said six. Both times
    the error was in the flattering direction.
    """

    def setUp(self):
        with open(os.path.join(SKILL, "resources", "config", "checklist.json"),
                  encoding="utf-8") as f:
            self.ids = {i["id"] for i in json.load(f)["items"]}
        with open(os.path.join(I18N, "ru.json"), encoding="utf-8") as f:
            self.ru = json.load(f)

    def test_every_item_has_a_russian_title_and_recommendation(self):
        for key in ("item_titles", "item_fixes"):
            missing = sorted(self.ids - set(self.ru.get(key) or {}))
            self.assertEqual(missing, [], f"{key} does not cover: {missing[:8]}")

    def test_no_translation_survives_an_item_the_registry_dropped(self):
        """The other direction, and the one nobody notices: a title for an id that
        no longer exists is dead weight that reads as coverage."""
        for key in ("item_titles", "item_fixes"):
            stray = sorted(set(self.ru.get(key) or {}) - self.ids)
            self.assertEqual(stray, [], f"{key} translates ids that are gone: {stray}")

    def test_no_entry_is_blank_or_left_in_english(self):
        """A blank value counts as present to `dict` and falls back to English in the
        report, which is the same silent gap with an extra step."""
        for key in ("item_titles", "item_fixes"):
            for item_id, text in (self.ru.get(key) or {}).items():
                self.assertTrue(str(text).strip(), f"{key}[{item_id}] is blank")
                self.assertRegex(str(text), "[а-яА-ЯёЁ]",
                                 f"{key}[{item_id}] has no Russian in it: {text!r}")

    def test_the_report_uses_them(self):
        ru = Lang("ru")
        first = sorted(self.ids)[0]
        row = {"id": first, "title": "Ensure URL Is Indexed", "fix": "Remove noindex"}
        self.assertNotEqual(ru.title(row), row["title"])
        self.assertNotEqual(ru.fix(row), row["fix"])


class ATranslationIsBoundToTheEnglishItTranslates(unittest.TestCase):
    """The gap `TheRegistryIsTranslatedOrTheGapIsCounted` could not see.

    That class checks a translation exists, is not blank and contains Cyrillic. All
    three stayed green through 0.20 while SE-118's English fix text changed and its
    Russian one did not, because a sentence that has quietly stopped describing the
    English one is still Russian, still present and still non-blank. Its docstring
    had said the risk out loud — *"a second copy drifts the moment either side
    changes"* — and then tested for presence. Presence is not parity.

    `_source_digests` closes it: a hash of the English `(title, fix)` pair, stored
    beside the translation and checked here. Change the English and this fails,
    naming the item, until somebody re-reads the Russian and re-stamps it with
    `tools/i18n_digest.py`.
    """

    def setUp(self):
        sys.path.insert(0, os.path.join(SKILL, "tools"))
        import i18n_digest
        self.mod = i18n_digest

    def test_every_translation_matches_the_english_it_was_written_against(self):
        want = self.mod.english()
        with open(os.path.join(I18N, "ru.json"), encoding="utf-8") as f:
            have = json.load(f).get(self.mod.KEY) or {}
        drifted = sorted(i for i, d in want.items() if have.get(i) != d)
        self.assertEqual(drifted, [],
                         "the English moved and the Russian did not: "
                         f"{drifted[:8]} — re-read them, then run "
                         "tools/i18n_digest.py to stamp them")

    def test_the_digest_moves_when_either_side_of_the_english_moves(self):
        """Both halves, and separately. A digest over the concatenation alone would
        miss a word moved from the end of a title to the start of a fix — which is
        exactly the kind of edit that leaves a translation describing neither."""
        base = self.mod.digest("Add a Favicon", "Serve a favicon at the site root")
        self.assertNotEqual(base, self.mod.digest("Add a Favicon!",
                                                  "Serve a favicon at the site root"))
        self.assertNotEqual(base, self.mod.digest("Add a Favicon",
                                                  "Serve a favicon at the root"))
        self.assertNotEqual(self.mod.digest("ab", "c"), self.mod.digest("a", "bc"))

    def test_an_unstamped_item_is_drift_and_not_a_fresh_start(self):
        """A translation added without recording what it translated is the same
        unverifiable claim as one that has drifted, and reads as coverage."""
        with open(os.path.join(I18N, "ru.json"), encoding="utf-8") as f:
            stamped = set((json.load(f).get(self.mod.KEY) or {}))
        with open(os.path.join(SKILL, "resources", "config", "checklist.json"),
                  encoding="utf-8") as f:
            ids = {i["id"] for i in json.load(f)["items"]}
        self.assertEqual(sorted(ids - stamped), [])


class TheScoreNeverTravelsWithoutItsShare(unittest.TestCase):
    """`openspec/specs/scoring/` SCR-4 and `openspec/specs/reporting/` REP-1, which are one rule.

    69 over 55% of the registry's weight and 69 over 95% are different claims, and the
    number alone does not say which. Every surface printed both and no test would have
    failed if one stopped: current conduct is not enforcement, which is the distinction
    the whole suite's `Reader:` lines exist to keep.

    `openspec/specs/reporting/` §6 asked whether the console can be asserted without pinning its
    layout, since terminal output changes for good reasons constantly. It can, by never
    looking at where the number goes: render each surface twice with a different share
    and require the two to differ. A surface that stopped printing the share stops
    reacting to it, which reddens; a surface that moves it, renames it, or translates it
    does not. The score is checked the same way, because a surface showing neither would
    satisfy the first half vacuously.
    """

    def payload(self, **override):
        rows = [item("A", PASS, severity="high"), item("B", FAIL, severity="high"),
                item("C", NO_DATA, severity="low")]
        data = results(*rows)
        data["scores"] = runner.score(rows)
        data["scores"].update(override)
        data.update(url="https://example.com/", requested_url="", mode="page",
                    gsc_credentials_found=False, script_failures={})
        return data

    def console(self, data):
        args = argparse.Namespace(allow_private=False, diff=False, evidence_json="",
                                  json_out="out.json")
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            runner.print_report(data, args, "", "", "")
        return buffer.getvalue()

    def surfaces(self, data):
        """Every surface the requirement names, and the console is the one that had no
        test of any kind — `openspec/specs/reporting/` A.1 lists `print_report` at zero."""
        return {"markdown": render_markdown(data),
                "html": render_html(data),
                "console": self.console(data)}

    def moved(self, field):
        base = self.payload()
        other = self.payload(**{field: base["scores"][field] + 7})
        return self.surfaces(base), self.surfaces(other)

    def test_every_surface_reacts_to_the_share(self):
        base, other = self.moved("weight_pct")
        for name in base:
            with self.subTest(surface=name):
                self.assertTrue(
                    base[name] != other[name],
                    f"the {name} surface does not read weight_pct, so it can show a "
                    f"score with the denominator torn off")

    def test_every_surface_reacts_to_the_score(self):
        """Otherwise the test above passes on a surface that shows no score at all."""
        base, other = self.moved("seo_score")
        for name in base:
            with self.subTest(surface=name):
                self.assertTrue(base[name] != other[name],
                                f"the {name} surface does not read seo_score")

    def test_the_artifact_carries_both(self):
        """The fourth surface SCR-4 names. A reader of the JSON is in the same position
        as a reader of the report and has nothing else to consult."""
        scores = self.payload()["scores"]
        self.assertIsNotNone(scores["seo_score"])
        self.assertIsNotNone(scores["weight_pct"])



class TheProvenanceListIsTheOneThisDocumentNames(unittest.TestCase):
    """`openspec/specs/reporting/` REP-3, the half that was unread: the mechanism had ten
    readers and its *membership* had none.

    That distinction is not academic — it is how the last member came to be missing.
    Whether a verdict came out of the response cache is exactly the kind of fact this list
    exists for, it was recorded in the artifact from the start, and it appeared in no
    warning and in no test until 0.94.1. Ten tests of a mechanism cannot notice something
    that was never in it, because nothing anywhere enumerated what belonged.

    So the list is enumerated in the document, and this reads the code against it: the
    warning identifiers `provenance_warnings` emits, and the payload fields it consults,
    both taken from its AST rather than by running it. Running it would only show the
    branches a fixture happens to trigger; the question here is what the function *can*
    say, which is a property of its source.

    Both directions fail. A caveat added to the code and not to §REP-3 reddens, and a row
    written in §REP-3 with no branch behind it reddens too — and the second is the one that
    matters, since a document promising a caveat nobody emits is how a reader ends up
    trusting a number that had something to say for itself.
    """

    SPEC = os.path.join(ROOT, "openspec", "specs", "reporting", "spec.md")
    REPORT = os.path.join(SKILL, "scripts", "checklist_report.py")

    # Part of the artifacts row rather than a row of its own: it appends the age of the
    # oldest supplied file to that warning's own sentence, and never appears alone.
    FRAGMENTS = {"w_artifacts_age"}

    @classmethod
    def documented(cls):
        """The table under REP-3, as {warning: {fields}}."""
        import re
        with open(cls.SPEC, encoding="utf-8") as fh:
            text = fh.read()
        start = text.index("### Requirement: REP-3")
        end = text.index("### Requirement: REP-4")
        rows = {}
        for line in text[start:end].splitlines():
            match = re.match(r"^\| `(w_[a-z_]+)` \| ([^|]+) \|", line)
            if match:
                fields = {f.strip(" `") for f in match.group(2).split(",")}
                rows[match.group(1)] = fields
        return rows

    @classmethod
    def implemented(cls):
        """What `provenance_warnings` emits and reads, from its own syntax."""
        import ast
        with open(cls.REPORT, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "provenance_warnings")
        warnings, fields = set(), set()
        for node in ast.walk(fn):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if (node.func.attr == "t" and node.args
                        and isinstance(node.args[0], ast.Constant)):
                    warnings.add(node.args[0].value)
                if (node.func.attr == "get" and isinstance(node.func.value, ast.Name)
                        and node.func.value.id == "data" and node.args
                        and isinstance(node.args[0], ast.Constant)):
                    fields.add(node.args[0].value)
            if (isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name)
                    and node.value.id == "data" and isinstance(node.slice, ast.Constant)):
                fields.add(node.slice.value)
        return warnings - cls.FRAGMENTS, fields

    def test_every_warning_the_code_can_emit_is_named_in_the_document(self):
        emitted, _ = self.implemented()
        self.assertEqual(emitted, set(self.documented()),
                         "the provenance list and openspec/specs/reporting/ REP-3 disagree "
                         "about which caveats exist. Whichever is right, the other is what "
                         "a reader of this project is told")

    def test_every_field_the_document_promises_is_actually_consulted(self):
        """The direction that caught nothing for a year: a row in the table whose fields
        the function never reads is a caveat that cannot fire."""
        _, consulted = self.implemented()
        promised = set().union(*self.documented().values())
        self.assertEqual(promised - consulted, set(),
                         "REP-3 names payload fields the provenance list never reads")

    def test_the_cache_is_in_the_list(self):
        """Named on its own because it is the member the requirement's own scenario uses
        as its example, and because it was absent while ten tests of the mechanism passed.
        `openspec/specs/http/` HTTP-8 is the other half of it."""
        emitted, consulted = self.implemented()
        self.assertIn("w_http_cache", emitted)
        self.assertIn("http_cache_hits", consulted)


class AClaimedVerdictIsNotShownAsAMeasurement(unittest.TestCase):
    """`openspec/specs/reporting/` REP-4, the half that was a defect rather than a gap.

    The stamp existed and three tests asserted the merges set it. Nothing showed it: the
    report printed one aggregate sentence — "Of the 2 decided items: 1 answered by a person,
    on their word" — and the rows themselves were identical. Measured on 6 September 2026, a
    claimed `PASS` and a measured `PASS` rendered as the same Markdown row and the same HTML
    block, so a reader was told that one of the items was somebody's word and never which
    one. That is the whole failure the requirement names: a `PASS` a person typed, rendered
    identically to a `PASS` a checker computed, spends credibility the tool has not earned.

    Three things are asserted, and the third is the one that outlives this release.

    `claimed` and `model` are marked and are marked *differently*, because they are
    different statements — REP-5 requires evidence from a person and asks a model without
    requiring it, and a marker that collapses them loses that.

    `measured` is silent, for the same reason the parser caveat is silent for `lxml`: a
    marker on every row is one a reader stops seeing by the third report.

    And the set of origins each surface marks is derived from what `decided_by` can hold
    rather than written out, so a fourth kind added to the merges cannot quietly render as
    a measurement on one surface while being marked on another. The markers are currently
    written twice — `item_provenance` for the report, an inline mapping for the console
    diff — and that is exactly the shape that put the category bars out of step with the
    headline in 0.92.0.
    """

    ORIGINS = ("measured", "model", "claimed")

    def rendered(self, decided_by):
        data = results(item("A-1", PASS))
        data["items"][0]["decided_by"] = decided_by
        data["items"][0]["evidence"] = "some evidence"
        data["scores"] = runner.score(data["items"])
        return render_markdown(data), render_html(data)

    def row_of(self, markdown):
        rows = [ln for ln in markdown.splitlines() if ln.startswith("| ") and "A-1" in ln]
        self.assertEqual(len(rows), 1, markdown)
        return rows[0]

    def test_a_measured_verdict_carries_no_marker(self):
        md, html_out = self.rendered("measured")
        self.assertNotIn("(", self.row_of(md).split("|")[1],
                         "every row is marked, so no row is")
        self.assertNotIn('class="origin"', html_out)

    def test_a_claimed_verdict_says_so_beside_the_verdict(self):
        md, html_out = self.rendered("claimed")
        self.assertIn("claimed", self.row_of(md))
        self.assertIn('class="origin"', html_out)
        self.assertIn("claimed", html_out)

    def test_a_model_read_verdict_is_marked_and_not_as_a_claim(self):
        """Two different statements about where an answer came from. A person must show
        evidence; a model is asked and not required — REP-5 — and one marker for both
        would put those on the same footing."""
        md, html_out = self.rendered("model")
        row = self.row_of(md)
        self.assertIn("model", row)
        self.assertNotIn("claimed", row)
        self.assertIn('class="origin"', html_out)

    def test_every_origin_the_merges_can_stamp_is_marked_on_every_surface(self):
        """Derived from what `decided_by` can hold, not from a list written here.

        `checklist_runner` stamps `measured` and the two merges in `checklist_report`
        stamp `model` and `claimed` over it; those three are read out of the source below,
        so adding a fourth without teaching the surfaces about it fails here rather than
        rendering as a measurement.
        """
        import ast
        stamped = set()
        for path in (os.path.join(SKILL, "scripts", "checklist_report.py"),
                     os.path.join(SKILL, "scripts", "checklist_runner.py")):
            with open(path, encoding="utf-8") as fh:
                for node in ast.walk(ast.parse(fh.read())):
                    if (isinstance(node, ast.Assign) and len(node.targets) == 1
                            and isinstance(node.targets[0], ast.Subscript)
                            and isinstance(node.targets[0].slice, ast.Constant)
                            and node.targets[0].slice.value == "decided_by"
                            and isinstance(node.value, ast.Constant)):
                        stamped.add(node.value.value)
        self.assertEqual(stamped, set(self.ORIGINS),
                         "the origins this tree can stamp are not the ones the surfaces "
                         "were taught to mark")
        for origin in stamped - {"measured"}:
            with self.subTest(origin=origin):
                md, html_out = self.rendered(origin)
                self.assertNotEqual(self.row_of(md).split("|")[1].strip(), PASS,
                                    "%s renders as a plain measured verdict" % origin)
                self.assertIn('class="origin"', html_out)


class TheLensRoutingTableIsDerivedFromWhatItRoutes(unittest.TestCase):
    """`openspec/specs/reporting/` REP-11's unread half: the lens-to-agent table was named
    by no test.

    It is a hand-written mapping that decides which model reads which slice of a page, and
    `openspec/specs/governance/` GOV-3 is about exactly this shape — a list guarded only by
    the mechanism that consumes it. The mechanism has four readers here. The membership had
    none, and a list cannot say what is missing from it: a lens added to the registry with
    no row here routes its items to an agent named `""`, which renders a queue file
    addressed to nobody, and every test of the rendering still passes.

    So both ends are derived rather than restated. The keys come from the registry — the
    lenses items actually carry — and the agent names are checked against the files that
    have to exist for the routing to mean anything. Neither number is written here.
    """

    AGENTS = os.path.join(SKILL, "resources", "agents")

    @classmethod
    def registry_lenses(cls):
        with open(os.path.join(SKILL, "resources", "config", "checklist.json"),
                  encoding="utf-8") as fh:
            items = json.load(fh)["items"]
        return {lens for lens in
                ((item.get("check") or {}).get("lens") or item.get("lens")
                 for item in items) if lens}

    def test_every_lens_the_registry_uses_has_an_agent(self):
        from checklist_report import LENS_AGENTS
        self.assertEqual(set(LENS_AGENTS), self.registry_lenses(),
                         "the lens routing table and the registry disagree about which "
                         "lenses exist. A lens with no row routes its queue to an agent "
                         "named '', addressed to nobody")

    def test_every_agent_it_routes_to_exists_in_the_tree(self):
        """The other end. A row naming an agent that was renamed or removed sends a queue
        to a file nobody can open, and the failure is silent — the queue renders."""
        from checklist_report import LENS_AGENTS
        for lens, (agent, _reads) in sorted(LENS_AGENTS.items()):
            with self.subTest(lens=lens):
                self.assertTrue(
                    os.path.exists(os.path.join(self.AGENTS, agent + ".md")),
                    "%s routes to %s, which is not in resources/agents/" % (lens, agent))

    def test_each_lens_says_what_its_agent_has_to_read(self):
        """The second half of each row is the instruction that makes the split worth
        having — four agents each reading their own slice once, rather than four agents
        re-reading the same body copy. A row with an empty description is a queue whose
        reader is told nothing."""
        from checklist_report import LENS_AGENTS
        for lens, (_agent, reads) in sorted(LENS_AGENTS.items()):
            with self.subTest(lens=lens):
                self.assertTrue(reads.strip())


class TheHalfTranslatedReportKnowsWhichHalf(unittest.TestCase):
    """`openspec/specs/reporting/` REP-13's derivation, which was a regex over this module's
    own source and is now an AST walk plus three named tables.

    The regex matched `L.t(` followed by at most one newline, so every call formatted
    differently was invisible to it. Measured on 6 September 2026: it found 99 of 138
    literal keys. That is not a latent risk — five of the invisible ones (`broken`, `hops`,
    `now`, `redirecting`, `was`) were genuinely absent from `ru.json`, so a Russian report
    printed the broken-URL table's headers in English while the line whose whole job is to
    say which layers are still English said nothing.

    Replacing it with an AST walk exposed a second layer: six calls take their key from a
    table rather than a literal, and six of those twelve keys — the diff section headings
    and their notes — were missing from `ru.json` too. Eleven English strings in a Russian
    report, and no surface said so.

    Three assertions. The first two are the requirement. The third holds the limit the
    remedy still has, because a limit named in a comment is a limit nobody reads.
    """

    REPORT = os.path.join(SKILL, "scripts", "checklist_report.py")

    # Every `L.t()` whose key is computed rather than written: two in the Markdown diff
    # headings, two in the HTML ones, two in the opportunity phrasing. `missing_strings`
    # covers exactly these by walking DIRECTION_HEADING, DIRECTION_NOTE and
    # OPPORTUNITY_PHRASE, so a seventh means a table it does not know about.
    COMPUTED_CALLS = 6

    def test_a_shipped_language_is_missing_nothing(self):
        self.assertEqual(Lang("ru").missing_strings(), [])

    def test_the_derivation_does_not_depend_on_how_a_call_is_formatted(self):
        """What the regex could not do. Asserted through a key that is only reachable by
        parsing — `w_thin`'s call spans lines — rather than by counting, so the assertion
        survives keys being added and removed."""
        source = open(self.REPORT, encoding="utf-8").read()
        self.assertIn('L.t("w_thin",', source.replace("\n", " ").replace("  ", " "),
                      "the multi-line call this test relies on has been reformatted")
        empty = Lang("ru")
        empty.data = {"strings": {}}
        self.assertIn("w_thin", empty.missing_strings())

    def test_every_computed_key_call_is_one_of_the_tables_that_are_walked(self):
        """The remaining limit, read rather than commented.

        `missing_strings` walks three tables by name. A fourth table-backed call added
        later is invisible to it exactly as the reformatted calls were invisible to the
        regex — the same failure, one level along. This counts the calls whose key is not
        a literal; a seventh means a table nobody taught it about, and the failure says so.
        """
        import ast
        with open(self.REPORT, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        computed = [node for node in ast.walk(tree)
                    if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "t"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "L"
                    and node.args
                    and not isinstance(node.args[0], ast.Constant)]
        self.assertEqual(
            len(computed), self.COMPUTED_CALLS,
            "there are %d L.t() calls with a computed key and missing_strings knows "
            "about %d. If a new one reads from a fourth table, teach missing_strings "
            "that table and raise this number; if it reads from somewhere else, it is "
            "a string that can go untranslated with nothing to say so."
            % (len(computed), self.COMPUTED_CALLS))


class ACategoryBarSaysWhatItsScoreWasComputedFrom(unittest.TestCase):
    """`openspec/specs/reporting/` REP-10, and the repair is not the obvious one.

    The obvious reading — fold the twins out of the category counts — is wrong, and two
    tests in `test_runner.py` say why in their own failure messages: `openspec/specs/scoring/`
    SCR-1 requires a twin to keep reporting its own status, so it is "still decided, still
    counted and still printed". Hiding it would answer this requirement by breaking that one.

    What was actually wrong is narrower and was invisible in the payload: the bar printed
    `decided` beside a `score` computed over a different set. Measured on a live run,
    `media` showed five decided items and a score computed from three, `geo_ai` seven and
    five. Nothing let a reader see the denominator, so "100/100 over 5 items" was a sentence
    the report did not mean.

    `score_population` is that denominator, and the surfaces print it **only when it differs
    from `decided`** — on nine of twelve categories in that run the two agree, and a note on
    every bar is one nobody reads by the second page.
    """

    def rows(self, *specs):
        out = []
        for n, (cat, status, twin_of) in enumerate(specs):
            row = {"id": "X-%d" % n, "title": "x", "status": status, "severity": "high",
                   "category": cat, "category_label": cat.title(), "effort": "low",
                   "evidence": "e", "fix": ""}
            if twin_of:
                row["scores_with"] = twin_of
            out.append(row)
        return out

    def test_the_population_is_the_set_the_score_divided_by(self):
        result = runner.score(self.rows(("media", PASS, None),
                                        ("media", FAIL, "X-0"),
                                        ("media", PASS, None)))
        cat = result["by_category"]["media"]
        self.assertEqual(cat["decided"], 3, "a twin stopped being counted, which SCR-1 "
                                            "requires it to keep doing")
        self.assertEqual(cat["score_population"], 2)
        self.assertEqual(cat["score"], 100, "the twin's FAIL was weighed after all")

    def test_a_category_with_no_twins_reports_the_same_two_numbers(self):
        cat = runner.score(self.rows(("meta", PASS, None),
                                     ("meta", FAIL, None)))["by_category"]["meta"]
        self.assertEqual(cat["score_population"], cat["decided"])

    def test_the_surfaces_say_so_when_the_two_numbers_differ(self):
        data = results(*self.rows(("media", PASS, None),
                                  ("media", FAIL, "X-0"),
                                  ("media", PASS, None)))
        data["scores"] = runner.score(data["items"])
        row = next(ln for ln in render_markdown(data).splitlines()
                   if ln.startswith("| ") and "Media" in ln and "/100" in ln)
        self.assertIn("scored over 2", row,
                      "the bar does not say how many items its score covered")
        self.assertIn("scored over 2", render_html(data),
                      "the HTML bar does not say it either")

    def test_the_surfaces_stay_quiet_when_they_agree(self):
        """Nine of twelve categories on a live run have nothing to disclose here, and a
        note printed on every bar is one a reader learns to skip — the same argument the
        parser caveat and the cache warning make."""
        data = results(*self.rows(("meta", PASS, None), ("meta", FAIL, None)))
        data["scores"] = runner.score(data["items"])
        for surface in (render_markdown(data), render_html(data)):
            self.assertNotIn("ask a question this audit answers", surface)

    def test_the_two_numbers_are_never_inverted(self):
        """`score_population` counts a subset of `decided`, so it cannot exceed it. Asserted
        because the pair is computed by two different comprehensions over two different
        lists, which is how they came to disagree silently in the first place."""
        data = runner.score(self.rows(("media", PASS, None), ("media", FAIL, "X-0"),
                                      ("mobile", PASS, "X-0"), ("mobile", WARN, None),
                                      ("meta", NO_DATA, None)))
        for name, cat in data["by_category"].items():
            with self.subTest(category=name):
                self.assertLessEqual(cat["score_population"], cat["decided"])


class EveryMergeSaysWhyItIgnoredAnAnswer(unittest.TestCase):
    """`openspec/specs/reporting/` REP-6's second sentence: every answer that is ignored
    MUST say why.

    The first sentence — that a merge only fills a status waiting for it — is the
    best-read part of that document. The second was asserted for one merge of the three,
    and the three are not interchangeable: an operator hand-editing `MANUAL-QUEUE.md` and a
    model answering `LLM-QUEUE.md` fail in different ways, and the reviewer pass fails in a
    third. An answer silently dropped is an operator who thinks the audit read their file.

    The set of merges is derived from the module rather than listed, for the reason this
    tree keeps relearning: a fourth merge added later would be covered by a list only if
    somebody remembered to add it, and the omission is invisible from inside the list.
    """

    REPORT = os.path.join(SKILL, "scripts", "checklist_report.py")

    @classmethod
    def merges(cls):
        """Every module-level function that folds an answer file into results.

        Identified by what it does rather than by what it is called: takes `data` and one
        other mapping, and *assigns* an item's status. Renderers also take `data` and walk
        `data["items"]`, and the first version of this test collected them too — reading
        is not merging, and the difference is the assignment.
        """
        import ast
        with open(cls.REPORT, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        found = []
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef):
                continue
            args = [a.arg for a in node.args.args]
            if args[:1] != ["data"] or len(args) != 2:
                continue
            assigns_status = any(
                isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant)
                        and t.slice.value == "status" for t in n.targets)
                for n in ast.walk(node))
            if assigns_status:
                found.append(node.name)
        return found

    def test_the_three_merges_are_the_ones_this_test_knows_about(self):
        self.assertEqual(sorted(self.merges()),
                         ["apply_llm_review", "merge_llm_answers", "merge_manual_answers"],
                         "a merge was added or renamed; the assertions below cover the "
                         "three that existed, and an uncovered merge can drop an "
                         "operator's answer in silence")

    def item_waiting(self, status):
        row = {"id": "Q-1", "title": "q", "status": status, "severity": "high",
               "category": "meta", "category_label": "Meta", "effort": "low",
               "evidence": "e", "fix": ""}
        return {"items": [row], "scores": {}}

    def captured(self, fn, data, answers):
        stream = io.StringIO()
        with contextlib.redirect_stderr(stream):
            fn(data, answers)
        return stream.getvalue()

    def test_an_answer_aimed_at_a_measured_verdict_is_named_by_every_merge(self):
        """The case an operator hits: they answer an item a script has since decided.
        Each merge must refuse it *and say which id*, because a count of ignored answers
        sends them to read the whole file again."""
        from checklist_report import (apply_llm_review, merge_llm_answers,
                                      merge_manual_answers)
        answer = {"Q-1": {"status": PASS, "evidence": "because I say so"}}
        for fn in (merge_llm_answers, merge_manual_answers, apply_llm_review):
            with self.subTest(merge=fn.__name__):
                printed = self.captured(fn, self.item_waiting(FAIL), answer)
                self.assertIn("Q-1", printed,
                              "%s dropped an answer without naming it" % fn.__name__)

    def test_an_invalid_status_is_named_by_every_merge(self):
        """The other way an answer file is wrong, and the one a typo produces."""
        from checklist_report import (apply_llm_review, merge_llm_answers,
                                      merge_manual_answers)
        answer = {"Q-1": {"status": "DONE", "evidence": "typed by hand"}}
        for fn, waiting in ((merge_llm_answers, LLM_PENDING),
                            (merge_manual_answers, MANUAL),
                            (apply_llm_review, PASS)):
            with self.subTest(merge=fn.__name__):
                printed = self.captured(fn, self.item_waiting(waiting), answer)
                self.assertIn("Q-1", printed)
                self.assertIn("DONE", printed,
                              "%s refused the answer without showing what it read"
                              % fn.__name__)


class ContestingAnAnswerIsVisibleInTheCoverage(unittest.TestCase):
    """`openspec/specs/reporting/` REP-8: an item returned to undecided leaves the scored
    set, the audit's coverage falls, and the report must say so rather than preserve the
    number.

    The status change is enforced by REP-7's tests and the scoring rules by
    `openspec/specs/scoring/`. What nothing asserted is the sentence this requirement is
    actually about — that a reader *sees* the audit got smaller. An audit whose score cannot
    go down when its confidence does is the same defect as scoring an unanswerable item, one
    level along.
    """

    def rows(self, *statuses):
        return [{"id": "C-%d" % n, "title": "c", "status": s, "severity": "high",
                 "category": "meta", "category_label": "Meta", "effort": "low",
                 "evidence": "e", "fix": ""} for n, s in enumerate(statuses)]

    def test_a_contested_item_leaves_the_scored_set_and_the_coverage_falls(self):
        before = runner.score(self.rows(PASS, PASS, PASS))
        after = runner.score(self.rows(PASS, PASS, NO_DATA))
        self.assertEqual(before["weight_pct"], 100)
        self.assertLess(after["weight_pct"], before["weight_pct"],
                        "the coverage did not fall when an answer was withdrawn, so the "
                        "audit reports the same reach with less of it decided")
        self.assertEqual(after["decided"], 2)

    def test_the_reader_is_shown_the_smaller_number(self):
        """Through the rendered surface, not the payload: the requirement is about what a
        reader sees, and a field nobody prints is the shape REP-4 and HTTP-8 were."""
        data = results(*self.rows(PASS, PASS, NO_DATA))
        data["scores"] = runner.score(data["items"])
        pct = data["scores"]["weight_pct"]
        self.assertLess(pct, 100)
        for surface in (render_markdown(data), render_html(data)):
            self.assertIn(str(pct), surface,
                          "the surface does not carry the share of the registry this "
                          "score covered")


class PageRunsAreNeverFlattenedIntoSiteRuns(unittest.TestCase):
    """`openspec/specs/reporting/` REP-12 as a rule rather than as a shape.

    Five test functions already cover the artifact's shape, and the `__`-prefixed internal
    keys are asserted stripped. What was read only incidentally is the sentence the
    requirement exists for: this is the file somebody opens when they are arguing with a
    verdict, and flattening a sampled page's run into the site's would make it impossible to
    tell which page produced which number — the one question it is opened to answer.

    Asserted here as a property over constructed runs rather than as a snapshot of one
    artifact's keys: a shape test passes as long as today's fixture has the shape, and says
    nothing about a page run whose script name collides with a site run's, which is exactly
    when flattening would happen and exactly what a real sampled audit produces.
    """

    def key(self, script, *args):
        """A run key as the runner builds it: the script, then the argv it was given.

        Written out rather than borrowed from a helper because the collision this class is
        about is a property of that shape — `run_label` joins the script to its arguments,
        so two runs of one script differ only by what follows.
        """
        return (script, (script, *args))

    def run_of(self, **fields):
        return dict({"issues": [], "url": "https://example.test/"}, **fields)

    def test_a_page_run_never_lands_in_the_site_section(self):
        """The collision case. Both sections hold a run from the same script — the site's
        of the entry page, the page section's of a sampled URL — and the artifact must keep
        them apart rather than let the second overwrite the first."""
        site = {self.key("meta_check.py", "https://example.test/"):
                self.run_of(url="https://example.test/", title="home")}
        pages = {"https://example.test/a": {
            "meta_check.py https://example.test/a":
                self.run_of(url="https://example.test/a", title="a")}}
        artifact = runner.evidence_artifact(site, pages)
        label = "meta_check.py https://example.test/"
        self.assertEqual(artifact[label]["title"], "home",
                         "a sampled page's run overwrote the site's run of one script")
        self.assertEqual(
            artifact["pages"]["https://example.test/a"]
                    ["meta_check.py https://example.test/a"]["title"], "a")

    def test_the_page_section_exists_exactly_when_sampling_happened(self):
        """`None` and `{}` are different statements — no sampling, versus sampling that
        produced nothing — and collapsing them would make an empty sample look like a run
        that never sampled."""
        site = {self.key("meta_check.py", "https://example.test/"): self.run_of()}
        self.assertNotIn("pages", runner.evidence_artifact(site, None))
        self.assertEqual(runner.evidence_artifact(site, {})["pages"], {})

    def test_internal_keys_are_stripped_from_every_section(self):
        """Asserted for both sections rather than one: the stripping happens in
        `evidence_runs`, which the page section does not go through, so a `__`-prefixed key
        inside a page run is a different code path from the same key inside a site run."""
        site = {self.key("meta_check.py", "https://example.test/"):
                self.run_of(__error__=None, __elapsed__=1.5)}
        artifact = runner.evidence_artifact(site, None)
        kept = artifact["meta_check.py https://example.test/"]
        self.assertEqual([k for k in kept if k.startswith("__")], [])

    def test_a_failed_run_keeps_its_summary_rather_than_disappearing(self):
        """The reason someone opens this file is often that a check failed. A run that
        errored has no parsed output to keep, and dropping it would leave the reader with
        an item reporting NO_DATA and nothing to read about why."""
        site = {self.key("meta_check.py", "https://example.test/"):
                self.run_of(__error__="boom", __elapsed__=0.2)}
        artifact = runner.evidence_artifact(site, None)
        label = "meta_check.py https://example.test/"
        self.assertIn(label, artifact)
        self.assertEqual(artifact[label]["error"], "boom",
                         "a failed run lost the reason it failed, so the artifact cannot "
                         "say what happened")

if __name__ == "__main__":
    unittest.main()
