"""The recorded verdict census, kept in step with the registry it describes.

`tests/census.json` is a measurement, not a declaration: it records what every item
answered on every tree this repository can serve. Its value is the range — an item
that gave one answer everywhere is either a rule that cannot give another or a
question every site answers the same way, and those two are worth telling apart.

Recomputing it costs four full audits, so this module does not do that. It checks the
cheap invariants that make a stale record impossible to ignore: the census describes
*this* registry, and it describes every item in it. Re-record with

    python tests/verdict_census.py --out tests/census.json

whenever the registry moves, and read the report it prints while you are there.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "seo-checklist", "scripts"))
import harness  # noqa: E402
import verdict_census  # noqa: E402
from checklist_report import STATUS_ORDER  # noqa: E402
CENSUS = os.path.join(ROOT, "tests", "census.json")


def load(path: str) -> dict:
    with open(path, encoding="utf-8") as stream:
        return json.load(stream)


class RecordedCensus(unittest.TestCase):

    def setUp(self):
        self.census = load(CENSUS)
        self.registry = harness.registry()

    def test_it_describes_this_registry(self):
        """A census taken against an older contract describes a checklist that no
        longer exists, and the difference is invisible from inside the file."""
        self.assertEqual(self.census["registry_version"],
                         self.registry["registry_version"],
                         "tests/census.json was taken against a different registry — "
                         "re-record it with tests/verdict_census.py")

    def test_every_item_is_accounted_for(self):
        self.assertEqual(set(self.census["items"]),
                         {i["id"] for i in self.registry["items"]})
        self.assertEqual(self.census["item_count"], self.registry["item_count"])

    def test_what_it_copies_from_the_registry_still_describes_it(self):
        """A census row is two things at once: one answer per served tree, which cost
        an audit each, and four fields copied from the registry, which cost nothing to
        re-read. Until now this module read neither kind. `registry_version` above was
        its whole staleness check — and a stamp cannot drift on its own, because
        `verdict_census.py` takes it from the same registry load the titles come from.
        Which is exactly the trouble: **the one field the suite read was the one field
        an edit could set.**

        Measured rather than reasoned. `tests/census.json` shipped `GO-143` as
        *Provide Complete WebSite Data for the Site Name*, the first of two titles the
        item was given inside 0.89.0, under `registry_version` `b0abf2819da0`. A
        registry carrying that first title hashes to `872e9c3fd2fc`, so no single
        recording can produce the file as it shipped: the content was taken while the
        first title stood and the stamp was moved onto it afterwards, the way the
        release ritual moves a stamp when the registry has changed under a record that
        costs five audits to re-take. The title survived two further releases, and the
        test above passed on every one of them.

        The copies stay — a record that named only ids could not be read beside the
        registry it was taken from, and an archived one could not be read at all. What
        changes is that they are read, in both directions, so an item recorded and no
        longer in the registry and an item in the registry and never recorded both
        fail here and not only in the sibling test above. Re-record with

            python tests/verdict_census.py --out tests/census.json
        """
        items = {item["id"]: item for item in self.registry["items"]}
        for item_id in sorted(set(items) | set(self.census["items"])):
            with self.subTest(item=item_id):
                item = items.get(item_id)
                row = self.census["items"].get(item_id)
                self.assertIsNotNone(
                    item, f"{item_id} is recorded and is not in this registry")
                self.assertIsNotNone(
                    row, f"{item_id} is in this registry and was never censused")
                copied = {"title": item["title"],
                          "severity": item["severity"],
                          "source": item["source"],
                          "script": (item.get("check") or {}).get("script")}
                self.assertEqual(
                    {field: row.get(field) for field in copied}, copied,
                    f"{item_id}: the census copies a registry field that has since "
                    "moved — re-record it with tests/verdict_census.py --out")

    def test_every_item_was_asked_on_every_site(self):
        """A missing answer is the census failing to run an item, not an item
        declining to answer; the two must not be readable as the same thing."""
        sites = set(self.census["sites"])
        self.assertTrue(sites, "the census names no site")
        for item_id, row in self.census["items"].items():
            self.assertEqual(set(row["answers"]), sites, item_id)
            self.assertNotIn("MISSING", row["distinct"], item_id)

    def test_distinct_is_the_set_of_answers_and_not_a_second_opinion(self):
        """`openspec/specs/declarations/` DEC-10, and the hole the `distinct` line
        above left open.

        Forbidding the `MISSING` sentinel in `distinct` and saying nothing about
        `answers` lets a row carry `"fixture:broken": "MISSING"` under a `distinct`
        that omits it, and every census test passes. Measured before this existed:
        the sentinel was put on `CI-004`'s broken answer with `distinct` left saying
        `FAIL, PASS`, and the **whole suite** was green. The expensive gate would
        still have caught it — a fresh recording does not say `MISSING`, so
        `--check` differs — but that gate is DEC-12's, it runs in a job of its own,
        and between recordings the file is read by people whom nothing warned.

        Derived rather than a second list: `distinct` is a summary of `answers`, so
        it is asserted to be exactly that.
        """
        for item_id, row in self.census["items"].items():
            self.assertEqual(sorted(set(row["answers"].values())),
                             sorted(row["distinct"]), item_id)

    def test_every_answer_is_a_status_the_audit_can_emit(self):
        """DEC-10 again, from the other side. Nothing required an answer to be one
        of the eight, so `"BANANA"` passed the whole suite when `distinct` was kept
        in step with it — measured, on `CI-004`.

        The eight come from `checklist_report.STATUS_ORDER`, the runner's own order,
        so a status added or renamed there moves this reader with it. `MISSING` is
        deliberately not among them: `verdict_census.py` writes it when an item was
        not run at all, and DEC-10's whole point is that an unrun item is not an
        unanswered one — so it has to fail here rather than sit in a field nobody
        reads.
        """
        allowed = set(STATUS_ORDER)
        self.assertEqual(len(allowed), 8, "the vocabulary moved; read DEC-3")
        for item_id, row in self.census["items"].items():
            for site, answer in row["answers"].items():
                self.assertIn(answer, allowed, f"{item_id} on {site}")

    def test_no_item_is_recorded_twice(self):
        """DEC-10's third: `json.load` keeps the last of two identical keys and says
        nothing, so a record can hold two rows for one item while the program sees
        one. Read from the raw text, because the defect cannot survive being parsed
        — which is exactly why nothing had noticed it.
        """
        def reject_duplicates(pairs):
            seen = set()
            for key, _ in pairs:
                if key in seen:
                    raise AssertionError(f"{key} is recorded twice")
                seen.add(key)
            return dict(pairs)

        with open(CENSUS, encoding="utf-8") as stream:
            json.load(stream, object_pairs_hook=reject_duplicates)

    def test_a_census_from_a_slow_machine_is_in_step_and_nothing_else_is(self):
        """DEC-12's one narrowing, on the comparison `--check` makes. A fresh census
        that answers the other band for an item whose band is a measured time
        (`harness.CLOCK_READ`) agrees with the record. One in which that item took no
        time does not, and neither does the other band of any other item.

        The fresh census is this record with one answer changed, because a slow
        machine cannot be had at will; the live half was measured once, in
        `local/timed-0155/`.
        """
        other = {"PASS": "FAIL", "FAIL": "PASS"}

        def first_answered(item_id):
            # The first tree that answered with a band, not the first tree: since F06
            # `error-entry` sorts first and times nothing.
            answers = self.census["items"][item_id]["answers"]
            return next((site for site in sorted(answers) if answers[site] in other),
                        sorted(answers)[0])

        def fresh(item_id, answer):
            record = json.loads(json.dumps(self.census))
            row = record["items"][item_id]
            row["answers"][first_answered(item_id)] = answer
            row["distinct"] = sorted(set(row["answers"].values()))
            return record

        self.assertTrue(verdict_census.in_step(self.census, load(CENSUS)))
        timed = [i for i in harness.CLOCK_READ if i in self.census["items"]]
        self.assertTrue(timed, "no timed item is recorded; this reads nothing")
        for item_id in timed:
            answered = self.census["items"][item_id]["answers"][first_answered(item_id)]
            with self.subTest(item=item_id):
                self.assertIn(answered, other, "recorded as never timed")
                self.assertTrue(verdict_census.in_step(
                    self.census, fresh(item_id, other[answered])))
                self.assertFalse(verdict_census.in_step(
                    self.census, fresh(item_id, "NO_DATA")))
        for item_id, row in self.census["items"].items():
            answered = row["answers"][first_answered(item_id)]
            if item_id not in harness.CLOCK_READ and answered in other:
                with self.subTest(item=item_id):
                    self.assertFalse(verdict_census.in_step(
                        self.census, fresh(item_id, other[answered])))

    def test_a_tree_slow_by_construction_holds_its_clock_answer_exactly(self):
        """F05-2. On a tree whose audited page is held back past the budget
        (`harness.SLOW_BY_CONSTRUCTION`) no machine answers PASS, so the record's
        FAIL there is the tree's: the other band is out of step, and the tool counts
        that FAIL as the item able to fail."""
        self.assertTrue(harness.SLOW_BY_CONSTRUCTION, "no tree is slow; this reads nothing")
        for item_id in harness.CLOCK_READ:
            for tree in harness.SLOW_BY_CONSTRUCTION:
                with self.subTest(item=item_id, tree=tree):
                    self.assertEqual(self.census["items"][item_id]["answers"][tree], "FAIL")
                    record = json.loads(json.dumps(self.census))
                    record["items"][item_id]["answers"][tree] = "PASS"
                    self.assertFalse(verdict_census.in_step(self.census, record))


class TheCensusSaysWhereTheEntryGateStopped(unittest.TestCase):
    """F05-2. The runner's entry gate writes the FAIL of an `entry_answer` item without
    its assertion, so the census records the trees it stopped (`entry_reachable`
    false), and `audit_reachability` counts such an item's FAIL only on the others."""

    def setUp(self):
        self.census = load(CENSUS)

    def test_it_names_trees_it_served(self):
        self.assertLessEqual(set(self.census["entry_gated"]), set(self.census["sites"]))
        self.assertIn("error-entry", self.census["entry_gated"])
        self.assertNotIn("fixture:broken", self.census["entry_gated"])

    def test_a_record_that_moved_the_gate_is_out_of_step(self):
        record = json.loads(json.dumps(self.census))
        record["entry_gated"] = sorted(set(record["entry_gated"]) ^ {"no-location"})
        self.assertFalse(verdict_census.in_step(self.census, record))

    def test_every_slow_tree_holds_a_first_byte_back_past_every_budget(self):
        """A name here is a promise about a served tree's table, so it must be one: a
        route held back longer than each `CLOCK_READ` item's budget (its `lte`, in
        ms). Which route the item times is not read here; the census holds that, by
        its exact answer on the tree (review of F05-2)."""
        items = {item["id"]: item for item in harness.registry()["items"]}
        budgets = [items[i]["check"]["assert"]["lte"] for i in harness.CLOCK_READ]
        for tree in harness.SLOW_BY_CONSTRUCTION:
            with self.subTest(tree=tree):
                answers = load(os.path.join(verdict_census.CORPUS, tree, "_answers.json"))
                held = max(row.get("delay", 0) for row in answers.values()) * 1000
                self.assertGreater(held, max(budgets))


class ATreeCanNameAPageSpeedStandIn(unittest.TestCase):
    """F05-3. `_inputs/<tree>/pagespeed_standin.txt` names the stand-in's address under
    the usual placeholder; the census rewrites it to the bound port and hands it to the
    run as `SEO_PAGESPEED_STANDIN`, and to no other tree's run."""

    def inputs(self, label):
        with tempfile.TemporaryDirectory() as workdir:
            return verdict_census.corpus_inputs(label, "http://127.0.0.1:4321", workdir)[1]

    def test_the_tree_that_names_one_is_pointed_at_its_own_port(self):
        self.assertEqual(self.inputs("slow-field")["SEO_PAGESPEED_STANDIN"],
                         "http://127.0.0.1:4321/pagespeedonline/v5/runPagespeed")

    def test_no_other_tree_inherits_one(self):
        with mock.patch.dict(os.environ, {"SEO_PAGESPEED_STANDIN": "http://127.0.0.1:9/"}):
            for label in ("page-sound", "went-down"):
                with self.subTest(tree=label):
                    self.assertIsNone(self.inputs(label).get("SEO_PAGESPEED_STANDIN"))


class ATreeCanNameTheValidatorAndSafeBrowsingStandIns(unittest.TestCase):
    """F05-4. `_inputs/<tree>/validator_standin.txt` and `safe_browsing_standin.txt` are
    handed to the run as `SEO_VALIDATOR_STANDIN` and `SEO_SAFE_BROWSING_STANDIN`, pointed
    at the bound port, and to no other tree's run."""

    VARS = {"SEO_VALIDATOR_STANDIN": "http://127.0.0.1:4321/nu/",
            "SEO_SAFE_BROWSING_STANDIN": "http://127.0.0.1:4321/v4/threatMatches:find"}

    def inputs(self, label):
        with tempfile.TemporaryDirectory() as workdir:
            return verdict_census.corpus_inputs(label, "http://127.0.0.1:4321", workdir)[1]

    def test_each_tree_that_names_them_is_pointed_at_its_own_port(self):
        for label in ("flagged", "cleared"):
            env = self.inputs(label)
            for var, value in self.VARS.items():
                with self.subTest(tree=label, var=var):
                    self.assertEqual(env[var], value)

    def test_no_other_tree_inherits_one(self):
        with mock.patch.dict(os.environ, {var: "http://127.0.0.1:9/" for var in self.VARS}):
            for label in ("page-sound", "slow-field"):
                env = self.inputs(label)
                for var in self.VARS:
                    with self.subTest(tree=label, var=var):
                        self.assertIsNone(env.get(var))


class ATreeAnswersAPostFromItsTable(unittest.TestCase):
    """F05-4. Rendered-mode validation and Safe Browsing both POST, and
    `SimpleHTTPRequestHandler` answers no POST (501). A served tree answers one from its
    `_answers.json` and refuses every other POST as before."""

    def test_a_table_route_answers_and_nothing_else_does(self):
        import requests
        with tempfile.TemporaryDirectory() as workdir:
            site = harness._Site(os.path.join(verdict_census.CORPUS, "flagged"),
                                 os.path.join(workdir, "flagged"))
            try:
                with requests.Session() as session:
                    session.trust_env = False
                    answered = session.post(site.base + "/v4/threatMatches:find",
                                            json={"threatInfo": {}}, timeout=5)
                    refused = session.post(site.base + "/", data=b"x", timeout=5)
                    after = session.get(site.base + "/", timeout=5)
            finally:
                site.stop()
        self.assertEqual(answered.status_code, 200)
        self.assertEqual(answered.json()["matches"][0]["threatType"], "SOCIAL_ENGINEERING")
        self.assertEqual(refused.status_code, 501)
        self.assertEqual(after.status_code, 200)


class TheHarnessSaysWhatItCannotExercise(unittest.TestCase):
    """`openspec/specs/declarations/` DEC-13. An item that gave one answer everywhere is
    a question for a person, and what the mechanism cannot express has to be written
    where the output is read — otherwise each reader re-derives it and the third one
    files it as a defect.

    Until 0.175.0 the third clause was pinned as an absence: the census output printed
    the ids the corpus README named among the items they inflate and never said why. It
    now says so beside each of them, reading the README section rather than a list of
    its own (`verdict_census.unexercisable`). F06 moved all three the README named
    (CI-003, AR-150, CI-014) out of it by serving their shape (`error-entry/`,
    `redirect-chain/`, `no-location/`), and SE-118 entered it: its failure is hidden by
    the entry gate, not by the server. Only back-ticked ids in that section are read, so
    the section names the others without backticks.
    """

    def setUp(self):
        with open(CENSUS, encoding="utf-8") as stream:
            self.census = json.load(stream)

    def test_the_items_it_names_are_items(self):
        """A list of ids nobody resolves is a list that outlives the ids in it."""
        named = verdict_census.unexercisable()
        self.assertTrue(named, "the README section names no ids; this test is vacuous")
        missing = [i for i in named if i not in self.census["items"]]
        self.assertEqual(missing, [],
                         "the corpus README names items the registry does not have")

    def test_none_of_them_was_ever_seen_failing(self):
        """The claim itself. If one of these does fail on some tree, the harness grew a
        capability the README says it lacks, and the sentence is now wrong."""
        for item_id in verdict_census.unexercisable():
            with self.subTest(item=item_id):
                distinct = self.census["items"][item_id]["distinct"]
                self.assertNotIn(
                    "FAIL", distinct,
                    f"{item_id} failed somewhere, so the corpus can express what the "
                    f"README says it cannot — update the README, not this test")

    def test_the_census_marks_them_where_it_prints_them(self):
        """DEC-13's third clause: the output itself records that no tree here can show
        the item failing, on the item's own lines, and marks nothing else so."""
        lines = verdict_census.report(self.census)
        marked = {lines[n - 2].split()[0] for n, line in enumerate(lines)
                  if line.strip().startswith("no tree here can show this failing")}
        never_failed = verdict_census.verdict_groups(self.census)[0]
        self.assertEqual(marked, set(verdict_census.unexercisable()) & never_failed)
        self.assertTrue(marked, "nothing is marked; this reads nothing")


class EveryItemThatNeverAnswersNamesWhatItNeeds(unittest.TestCase):
    """F06 (ROADMAP "What 1.0 requires", item 5). "Mostly honest — Search Console,
    PageSpeed and Safe Browsing cannot answer offline" was prose over 35 items, and
    twelve of them could answer on a tree this repository serves: they lacked a page
    shape, an artifact or a key the census never passed, and one (TE-167) sat behind the
    private-host gate for a question no third party is in.

    Now the reason is a reader, not a sentence. An item that answers on no tree must be
    one the runner itself withholds from a host only we can reach, and the census must
    name the external input it waits for (`verdict_census.external_input`). An item that
    could answer offline and does not fails here, by name.
    """

    def setUp(self):
        self.census = load(CENSUS)
        self.items = {i["id"]: i for i in harness.registry()["items"]}

    def test_each_names_an_external_input(self):
        silent = verdict_census.verdict_groups(self.census)[2]
        self.assertTrue(silent, "nothing is silent; this reads nothing")
        unexcused = sorted(i for i in silent
                           if not verdict_census.external_input(self.items[i]))
        self.assertEqual(unexcused, [],
                         "these answered on no tree and need no input from outside: "
                         "give the corpus the shape, the artifact or the key they need")

    def test_no_reason_outlives_its_items(self):
        """A named service that no item behind the gate reads is a reason for nothing."""
        used = set()
        for item in self.items.values():
            check = item.get("check") or {}
            path = str((check.get("assert") or {}).get("path") or "")
            for key in (f"{check.get('script')}:{path.split('.')[0]}", check.get("script")):
                if key in verdict_census.EXTERNAL_INPUT and \
                        verdict_census.external_input(item):
                    used.add(key)
                    break
        self.assertEqual(sorted(set(verdict_census.EXTERNAL_INPUT) - used), [])

    def test_an_item_the_runner_answers_here_is_never_excused(self):
        """The excuse is read through the runner's own gate, so an item moved out from
        under it — TE-167 in F06 — loses the excuse with it."""
        self.assertIsNone(verdict_census.external_input(self.items["TE-167"]))
        self.assertIsNotNone(verdict_census.external_input(self.items["SP-108"]))


if __name__ == "__main__":
    unittest.main()
