"""Release 0.130.0: an entry page that answered an error is evidence, for the items it answers.

**The mechanism nobody modelled.** When the entry page answers >= 400, or answers
something that is not a page, `checklist_runner` makes every live item NO_DATA and runs
nothing (`openspec/specs/run-lifecycle/` RUN-8). That is right for almost every item —
an error page is not the site — and wrong for the few whose question *is* the entry's
answer. Measured on 30.09 (`local/entry-gate/`, outside git: the good tree served with
only `/` changed, the shipped runner against one with the gate removed, eleven entry
states):

* **CI-003** *Page Returns 200 (OK) Status Code* could not fail at all. An entry
  answering >= 400 is stopped by the gate, and on any other status but 200
  `indexability_matrix.py` wrote `fetch_error: "no URL could be read"` — so a readable
  page answering 203 was NO_DATA with a sentence that was false.
* **TE-167** *Monitor Site Uptime* asserts one request was answered below 500. A 5xx
  or a refused connection is exactly what the gate stops first, so it could not fail
  either (and it is `api`, so no loopback fixture ever saw it).
* **CI-015** *Eliminate 5xx Server Errors* was failable on other pages since 0.128.0,
  never on the entry: a 503 home page was NO_DATA.

The gate already made the request these three ask about, so it answers them — no second
request to a server that is failing, which RUN-8's second scenario still forbids. An item
carries `check.entry_answer: {"fails_on": [...], "why": ...}` naming the status classes
(`seo_common.status_class`, Google's *HTTP status codes* page, last updated 2026-02-04)
under which the entry's answer fails it. On a dead entry such an item is FAIL when the
answer is in its list and NO_DATA otherwise: **the gate withholds a pass, never a
failure it measured.** An entry nobody read carries no score (RUN-8's third scenario,
which a run with browser artifacts broke: `SEO Score: 100/100` over eleven artifact
items, on an entry answering 404).

**The set is derived by the operation, not listed.** `TheGateHidesNoFailureItDoesNotAnswer`
serves the entry under 404 and 503 and points at a port nothing listens on, runs the runner
with the gate removed
(`tests/entry_gate_off.py`), and requires every failure the error provokes to be either
answered by the gate or argued in `NOT_THE_ENTRYS_ANSWER` — in both directions, and with
the gate saying exactly what the item's own script says.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SKILL = os.path.join(ROOT, "skills", "seo-checklist")
SCRIPTS = os.path.join(SKILL, "scripts")
RUNNER = os.path.join(SCRIPTS, "checklist_runner.py")
GATE_OFF = os.path.join(HERE, "entry_gate_off.py")
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(SKILL, "tools"))

import harness  # noqa: E402
from harness import allow_loopback, offline_env, served, spawn, tree_served  # noqa: E402
import checklist_runner as cr  # noqa: E402
from registry_verdict import verdict  # noqa: E402
from checklist_runner import (FAIL, NO_DATA, PASS, WARN, build_plan,  # noqa: E402
                              grade, score, unreachable_skips)
import seo_common  # noqa: E402


def items() -> dict:
    return {item["id"]: item for item in harness.registry()["items"]}


def declared() -> dict:
    return {i: it["check"]["entry_answer"] for i, it in items().items()
            if (it.get("check") or {}).get("entry_answer")}


# The classes the entry gate can see a *failing* answer in. The gate also fires on a
# 200 that is not a page (a non-HTML type, an empty body, a challenge, a soft 404), and
# no item may fail on those: the answer was a success, the page was just not the site.
GATE_FAILING_CLASSES = {"client_error", "server_error", "no_answer"}


class StatusClassIsGooglesReading(unittest.TestCase):
    """One classification of an HTTP answer, read by the runner's gate and by the scripts.

    Google, *HTTP status codes, network and DNS errors* (last updated 2026-02-04): for a
    2xx "Google considers the content for processing"; 201 and 202 it waits for; a 204
    means "Google wasn't able to receive any content". So 200 is `ok`, another 2xx is a
    success that is not a plain 200, 204 has nothing to process, and the rest follow the
    first digit. No HTTP answer at all is its own class, because the gate has to tell
    "the server said 503" from "nothing answered".
    """

    EXPECTED = {200: "ok", 201: "other_success", 202: "other_success",
                203: "other_success", 206: "other_success", 204: "no_content",
                301: "redirect", 304: "redirect", 308: "redirect",
                400: "client_error", 404: "client_error", 410: "client_error",
                500: "server_error", 503: "server_error", None: "no_answer",
                99: "unrecognised", 600: "unrecognised"}

    def test_every_status_lands_in_its_class(self):
        got = {status: seo_common.status_class(status) for status in self.EXPECTED}
        self.assertEqual(got, self.EXPECTED)

    def test_the_vocabulary_is_the_classes_and_nothing_else(self):
        self.assertEqual(set(seo_common.STATUS_CLASSES), set(self.EXPECTED.values()))


class IndexabilityReadsEveryAnswer(unittest.TestCase):
    """`indexability_matrix.py` called a page unread unless it answered exactly 200.

    `fetch_error` is for *nothing answered*: a 404 was read, and its status is the
    finding CI-003 exists to report. The blocker follows Google rather than the literal
    200: any 2xx but 204 is content Google processes, so a 203 is not "not indexable".
    CI-003 itself stays with its title: 200 passes, another 2xx warns (met Google, not
    the item), anything else fails.
    """

    PAGE = ('<!doctype html><html lang="en"><head><title>An answer</title></head>'
            '<body><p>Readable.</p></body></html>')

    def read(self, status):
        import indexability_matrix
        body = "" if status == 204 else self.PAGE
        with allow_loopback(), served({"/": (status, {"Content-Type": "text/html"},
                                             body)}) as site:
            return indexability_matrix.evaluate([site.url])

    def test_a_plain_200_passes(self):
        out = self.read(200)
        self.assertEqual(out["rows"][0]["status_class"], "ok")
        self.assertIsNone(out["fetch_error"])
        self.assertEqual(verdict("CI-003", out), PASS)

    def test_another_success_is_read_indexable_and_warns(self):
        out = self.read(203)
        row = out["rows"][0]
        self.assertIsNone(out["fetch_error"], "a 203 page was read; nothing is unread")
        self.assertEqual((row["status"], row["status_class"]), (203, "other_success"))
        self.assertFalse([b for b in row["blockers"] if b.startswith("HTTP")],
                         row["blockers"])
        self.assertEqual(row["verdict"], "indexable")
        self.assertEqual(verdict("CI-003", out), WARN)
        self.assertEqual(verdict("CI-001", out), PASS)

    def test_an_error_is_an_answer_and_fails(self):
        for status, cls in ((404, "client_error"), (503, "server_error")):
            with self.subTest(status=status):
                out = self.read(status)
                row = out["rows"][0]
                self.assertIsNone(out["fetch_error"], f"a {status} was an answer")
                self.assertEqual(row["status_class"], cls)
                self.assertIn(f"HTTP {status}", row["blockers"])
                self.assertEqual(verdict("CI-003", out), FAIL)

    def test_no_content_is_not_indexable(self):
        out = self.read(204)
        row = out["rows"][0]
        self.assertEqual(row["status_class"], "no_content")
        self.assertIn("HTTP 204", row["blockers"])
        self.assertEqual(verdict("CI-003", out), FAIL)

    def test_nothing_answering_is_still_unread(self):
        import indexability_matrix
        port = harness.closed_port()
        with allow_loopback():
            out = indexability_matrix.evaluate([f"http://127.0.0.1:{port}/"], timeout=3)
        self.assertEqual(out["fetch_error"], "no URL could be read")
        self.assertEqual(out["rows"][0]["status_class"], "no_answer")
        self.assertEqual(verdict("CI-003", out), NO_DATA)


class TheGateAnswersWhatItMeasured(unittest.TestCase):
    """`unreachable_skips` with the entry's answer: FAIL where it fails an item, NO_DATA
    everywhere else, and nothing planned either way."""

    ITEMS = [
        {"id": "S", "check": {"requires": "crawl", "script": "s.py", "args": ["{url}"],
                              "entry_answer": {"fails_on": ["client_error",
                                                            "server_error"],
                                               "why": "s"}}},
        {"id": "U", "check": {"requires": "api", "script": "u.py", "args": ["{url}"],
                              "entry_answer": {"fails_on": ["server_error",
                                                            "no_answer"],
                                               "why": "u"}}},
        {"id": "F", "check": {"requires": "fetch", "script": "f.py", "args": ["{url}"]}},
    ]

    def statuses(self, skips):
        return {k: v[0] for k, v in skips.items()}

    def test_a_client_error_fails_what_it_fails_and_nothing_else(self):
        skips = unreachable_skips(self.ITEMS, "HTTP 404", entry_status=404,
                                  requested=True)
        self.assertEqual(self.statuses(skips), {"S": FAIL, "U": NO_DATA, "F": NO_DATA})
        self.assertIn("HTTP 404", skips["S"][1])
        self.assertIn("own request", skips["S"][1])
        self.assertIn("unreachable", skips["U"][1])

    def test_a_server_error_fails_both(self):
        skips = unreachable_skips(self.ITEMS, "HTTP 503", entry_status=503,
                                  requested=True)
        self.assertEqual(self.statuses(skips), {"S": FAIL, "U": FAIL, "F": NO_DATA})
        self.assertIn("HTTP 503", skips["U"][1])

    def test_no_answer_is_its_own_class(self):
        for kind in cr.NO_ANSWER_KINDS:
            with self.subTest(kind=kind):
                reason = f"ConnectionError: {kind}"
                skips = unreachable_skips(self.ITEMS, reason, entry_status=None,
                                          requested=True, entry_error_kind=kind)
                self.assertEqual(self.statuses(skips),
                                 {"S": NO_DATA, "U": FAIL, "F": NO_DATA})
                self.assertIn("did not answer", skips["U"][1])
                self.assertIn(reason, skips["U"][1])

    def test_a_request_that_reached_no_site_answers_nothing(self):
        """A name that does not resolve may be a typo as easily as an outage; our own
        guard refusing an address, robots.txt keeping us out and an unclassified
        failure are not the site's answer either. The CI step "An unreachable site gets
        no score" audits `unreachable.invalid` and holds the live half."""
        self.assertEqual(set(cr.NO_ANSWER_KINDS) & {"unresolved", "blocked", "robots",
                                                    "other"}, set())
        for kind in ("unresolved", "blocked", "robots", "other", ""):
            with self.subTest(kind=kind):
                skips = unreachable_skips(self.ITEMS, "HostResolutionError: x",
                                          entry_status=None, requested=True,
                                          entry_error_kind=kind)
                self.assertEqual(set(self.statuses(skips).values()), {NO_DATA})

    def test_a_success_that_is_the_wrong_page_fails_nothing(self):
        skips = unreachable_skips(self.ITEMS, "soft 404: a 200 response titled 'x'",
                                  wrong_page=True, entry_status=200, requested=True)
        self.assertEqual(set(self.statuses(skips).values()), {NO_DATA})
        self.assertIn("not the site", skips["S"][1])

    def test_a_run_that_asked_nothing_answers_nothing(self):
        """Archive mode reads a saved file. No request was made, so no status exists
        and a missing one must not read as "nothing answered"."""
        for kwargs in ({}, {"entry_status": None}, {"entry_status": 503}):
            with self.subTest(**kwargs):
                skips = unreachable_skips(self.ITEMS, "bot protection", **kwargs)
                self.assertEqual(set(self.statuses(skips).values()), {NO_DATA})

    def test_an_answered_item_is_never_planned(self):
        skips = unreachable_skips(self.ITEMS, "HTTP 503", entry_status=503,
                                  requested=True)
        plan, skipped = build_plan(self.ITEMS, {"url": "https://e.com"},
                                   {"offline", "fetch", "crawl", "api"}, "live", skips,
                                   True)
        self.assertEqual({i for ids in plan.values() for i in ids}, set())
        self.assertEqual(skipped["S"][0], FAIL)

    def test_the_answer_reaches_the_graded_row(self):
        """Through `grade`, over the registry's own declarations."""
        reg = items()
        chosen = [reg[i] for i in sorted(declared())] + [reg["CN-065"]]
        skips = unreachable_skips(chosen, "HTTP 503", entry_status=503, requested=True)
        plan, skipped = build_plan(chosen, {"url": "https://e.com"},
                                   {"offline", "fetch", "crawl", "api"}, "live", skips,
                                   False)
        rows = {r["id"]: r for r in grade(chosen, plan, {}, skipped, False)}
        for item_id in declared():
            self.assertEqual(rows[item_id]["status"], FAIL, rows[item_id])
            self.assertIn("HTTP 503", rows[item_id]["evidence"])
        self.assertEqual(rows["CN-065"]["status"], NO_DATA)


class NoScoreForAnEntryNobodyRead(unittest.TestCase):
    """RUN-8's third scenario: a score over what did not need the site is a number
    about almost nothing. The artifact items and the entry's own answers are still
    decided; there is no headline and no category score."""

    ROWS = [{"id": "A", "status": PASS, "severity": "high", "category": "content",
             "category_label": "Content"},
            {"id": "B", "status": FAIL, "severity": "critical",
             "category": "crawling_indexing", "category_label": "Crawling"},
            {"id": "C", "status": NO_DATA, "severity": "low", "category": "content",
             "category_label": "Content"}]

    def test_no_headline_and_no_category_score(self):
        read = score(self.ROWS)
        unread = score(self.ROWS, entry_error="HTTP 404")
        self.assertIsNotNone(read["seo_score"])
        self.assertIsNone(unread["seo_score"])
        self.assertEqual(unread["decided"], read["decided"])
        self.assertTrue(unread["by_category"])
        for key, cat in unread["by_category"].items():
            self.assertIsNone(cat["score"], key)


class TheRegistryDeclaresWhatTheGateMayAnswer(unittest.TestCase):

    def test_every_declaration_is_well_formed(self):
        self.assertTrue(declared())
        for item_id, answer in declared().items():
            with self.subTest(item=item_id):
                fails_on = set(answer["fails_on"])
                self.assertTrue(fails_on)
                self.assertLessEqual(fails_on, set(seo_common.STATUS_CLASSES))
                self.assertFalse(fails_on & {"ok", "other_success"},
                                 "a success is never the entry failing an item")
                self.assertTrue(answer["why"].strip())
                self.assertIn(items()[item_id]["check"]["requires"],
                              cr.NEEDS_A_LIVE_SITE,
                              "the gate never stops an item that needs no live site")

    def test_the_build_table_is_the_registry(self):
        import build_checklist
        self.assertEqual(set(build_checklist.ENTRY_ANSWERS), set(declared()))

    def test_a_rule_over_the_status_class_fails_where_its_declaration_says(self):
        """Where the item's own rule reads a status class, the declaration is derivable:
        the failing classes the gate can see are exactly those the rule maps to fail."""
        seen = 0
        for item_id, answer in declared().items():
            rule = items()[item_id]["check"]["assert"]
            if not rule.get("path", "").endswith("status_class"):
                continue
            seen += 1
            failing = {c for c, v in rule["value_map"].items() if v == "fail"}
            self.assertEqual(set(answer["fails_on"]), failing & GATE_FAILING_CLASSES,
                             item_id)
        self.assertTrue(seen, "CI-003 reads status_class; the check reached nothing")


class TheBuilderRefusesABadEntryAnswer(unittest.TestCase):
    """`build_checklist.entry_answer_problems`, each refusal naming its id, and the
    shipped table refused by none of them."""

    def test_each_bad_shape_is_refused_by_name(self):
        import build_checklist
        items = build_checklist.build()
        good = {"fails_on": ["server_error"], "why": "a reason"}
        cases = {
            "unknown id": ("NO-999", good),
            "rule-less item": ("CN-037", good),
            "empty list": ("CI-003", {"fails_on": [], "why": "a reason"}),
            "unknown class": ("CI-003", {"fails_on": ["teapot"], "why": "a reason"}),
            "a success": ("CI-003", {"fails_on": ["ok"], "why": "a reason"}),
            "blank reason": ("CI-003", {"fails_on": ["server_error"], "why": " "}),
        }
        for label, (item_id, answer) in cases.items():
            with self.subTest(label):
                problems = build_checklist.entry_answer_problems(
                    items, {item_id: answer})
                self.assertTrue(problems, label)
                self.assertTrue(all(p.startswith(f"{item_id}:") for p in problems),
                                problems)

    def test_the_shipped_table_is_accepted(self):
        import build_checklist
        self.assertEqual(
            build_checklist.entry_answer_problems(build_checklist.build()), [])


# Failures an error entry provokes that the gate is right to withhold, each argued.
# Every member must still be provoked (the reader below), so a line here cannot
# outlive its reason.
NOT_THE_ENTRYS_ANSWER = {
    "BL-083": "reads the link export's most-linked pages. The entry is one of them in "
              "this fixture, so its error fails the item truly, but the gate reads no "
              "export and what the other targets answer takes requests a dead entry is "
              "not asked",
    "GO-138": "counts sitemap URLs that do not answer 200. The entry is listed in this "
              "fixture's sitemap, but the sitemap is a request a dead entry is not "
              "asked, so the gate cannot know it",
    "LO-198": "reads LocalBusiness markup from the pages the crawl could read. A page "
              "answering an error is not read, so an error entry leaves nothing to "
              "find, which says nothing about the site: the failure the gate exists to "
              "withhold",
}

# `dead` is a port nothing listens on: the entry that did not answer at all.
STATES = {"s404": 404, "s503": 503, "dead": None}


class TheGateHidesNoFailureItDoesNotAnswer(unittest.TestCase):
    """The derivation, by the operation. Seven audits: the good tree with `/` changed
    only in its status — the gate removed on the plain tree and on 404 and 503, the
    shipped runner on 404 (with the page artifacts, so the score has something to be
    computed over) and on 503 — and both runners against a port nothing listens on."""

    RESULTS: dict = {}

    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.mkdtemp(prefix="seo-entry-answers-")
        runs = [("baseline", "off", None), ("s404", "off", 404), ("s503", "off", 503),
                ("s404", "on", 404), ("s503", "on", 503), ("dead", "off", None),
                ("dead", "on", None)]
        with ThreadPoolExecutor(max_workers=3) as pool:
            for key, result in zip(runs, pool.map(lambda r: cls.audit(*r), runs), strict=True):
                cls.RESULTS[key[:2]] = result

    @classmethod
    def audit(cls, state, gate, status):
        def answers(site_dir):
            if status is None:
                return {}
            with open(os.path.join(site_dir, "index.html"), encoding="utf-8") as f:
                return {"/": {"status": status,
                              "content_type": "text/html; charset=utf-8",
                              "body": f.read()}}
        tag = f"{state}-{gate}"
        if state == "dead":
            return cls.launch(tag, gate, harness.dead_url(), [])
        with tree_served("good", answers) as site:
            arts = tree_served.artifacts(site, "good", os.path.join(cls.work, tag))
            # Every artifact where the gate is off, so what the tree can provoke is
            # provoked; the page artifacts on the dead 404, so a score has something
            # to be computed over; nothing on the dead 503.
            names = (("--rendered-json", "rendered.json"), ("--cwv-json", "cwv.json"))
            if gate == "off":
                names += (("--links-csv", "links"), ("--server-log", "access.log"))
            elif state == "s503":
                names = ()
            extra = [arg for flag, name in names
                     for arg in (flag, os.path.join(arts, name))]
            return cls.launch(tag, gate, site.url, extra)

    @classmethod
    def launch(cls, tag, gate, url, extra):
        out = os.path.join(cls.work, f"{tag}.json")
        program = GATE_OFF if gate == "off" else RUNNER
        proc = spawn([sys.executable, program, url, "--allow-private",
                      "--max-rps", "0", "--no-history", "--no-prompt",
                      "--timeout", "120", "--json", out, *extra],
                     env=offline_env(), timeout=900)
        if proc.returncode != 0 or not os.path.exists(out):
            raise AssertionError(f"{tag} exited {proc.returncode}\n"
                                 f"{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}")
        with open(out, encoding="utf-8") as f:
            payload = json.load(f)
        rows = payload["items"]
        rows = rows.values() if isinstance(rows, dict) else rows
        return {"payload": payload, "stdout": proc.stdout,
                "items": {r["id"]: (r["status"], r.get("evidence") or "") for r in rows}}

    def status(self, state, gate, item_id):
        return self.RESULTS[(state, gate)]["items"][item_id][0]

    def provoked(self, state):
        base = {i for i, (s, _) in self.RESULTS[("baseline", "off")]["items"].items()
                if s == FAIL}
        return {i for i, (s, _) in self.RESULTS[(state, "off")]["items"].items()
                if s == FAIL} - base

    def test_the_runs_are_the_runs_they_claim_to_be(self):
        self.assertTrue(self.RESULTS[("baseline", "off")]["payload"]["entry_reachable"])
        self.assertIn("ConnectionError",
                      self.RESULTS[("dead", "on")]["payload"]["entry_error"] or "")
        for state in STATES:
            self.assertTrue(self.RESULTS[(state, "off")]["payload"]["entry_reachable"])
            self.assertFalse(self.RESULTS[(state, "on")]["payload"]["entry_reachable"])

    def test_every_failure_the_gate_withholds_is_answered_or_argued(self):
        answered = set(declared())
        for state in STATES:
            with self.subTest(state=state):
                unexplained = sorted(self.provoked(state) - answered
                                     - set(NOT_THE_ENTRYS_ANSWER))
                detail = [f"{i}: {self.RESULTS[(state, 'off')]['items'][i][1][:100]}"
                          for i in unexplained]
                self.assertEqual(detail, [],
                                 "an error entry provokes these failures and the gate "
                                 "turns them into NO_DATA: answer them "
                                 "(`check.entry_answer`) or argue them in "
                                 "NOT_THE_ENTRYS_ANSWER")

    def test_no_argument_outlives_its_failure(self):
        provoked = set().union(*(self.provoked(s) for s in STATES))
        self.assertEqual(sorted(set(NOT_THE_ENTRYS_ANSWER) - provoked), [])
        self.assertFalse(set(NOT_THE_ENTRYS_ANSWER) & set(declared()))

    def test_the_gate_says_what_the_items_own_script_says(self):
        for item_id in declared():
            for state in STATES:
                with self.subTest(item=item_id, state=state):
                    off = self.status(state, "off", item_id)
                    on = self.status(state, "on", item_id)
                    self.assertEqual(on == FAIL, off == FAIL,
                                     f"gate {on}, script {off}: "
                                     f"{self.RESULTS[(state, 'on')]['items'][item_id][1]}")
                    if on != FAIL:
                        self.assertEqual(on, NO_DATA)

    def test_every_answer_fires_somewhere_and_names_the_status(self):
        for item_id in declared():
            with self.subTest(item=item_id):
                fired = [(s, self.RESULTS[(s, "on")]["items"][item_id][1])
                         for s in STATES if self.status(s, "on", item_id) == FAIL]
                self.assertTrue(fired, f"{item_id} never failed on an error entry")
                for state, evidence in fired:
                    self.assertIn(f"HTTP {STATES[state]}" if STATES[state]
                                  else "did not answer", evidence)

    def test_an_entry_nobody_read_is_not_scored(self):
        """With browser artifacts, which decided eleven items and printed 100/100."""
        run = self.RESULTS[("s404", "on")]
        decided = [i for i, (s, _) in run["items"].items() if s in (PASS, WARN, FAIL)]
        self.assertTrue(decided, "the artifacts decided nothing; the case is not built")
        self.assertIsNone(run["payload"]["scores"]["seo_score"])
        self.assertIn("UNREACHABLE:", run["stdout"])
        self.assertIn("No score:", run["stdout"])
        self.assertNotIn("SEO Score:", run["stdout"])


if __name__ == "__main__":
    unittest.main()
