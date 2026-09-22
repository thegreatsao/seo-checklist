"""`openspec/specs/declarations/` DEC-8, carried into the suite rather than left in CI.

The gate lives in `tools/audit_declaration_revisions.py`; this module is what makes it
run on every machine that runs the suite. A gate that exists only as a workflow step is
invisible to the person making the edit it is meant to refuse, which is the whole of
DEC-8's complaint: *nothing surfaces it at the time*.

Four classes, because they fail for different reasons and a reader who sees one red
name should not have to open the tool to learn which door was left open:

* `HistoryIsReadableAtAll` — the refusal that must never become a skip;
* `EveryMoveCarriesItsDecision` — the ledger, both directions;
* `TheStampIsRecomputedNotReadBack` — the fixture digest against the files;
* `TheRecordHasAShape` — a malformed record is not a record.

Probed at 0.104.0 against one mutation per door plus two that attack the gate itself;
`local/dec8/probe-0104.py` holds them and prints which class caught each.
"""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "seo-checklist", "tools"))

import audit_declaration_revisions as revisions  # noqa: E402


class HistoryIsReadableAtAll(unittest.TestCase):
    """The failure that looks like a pass, refused by name.

    `actions/checkout@v5` clones to depth 1. Over a shallow clone the walk finds no
    commits, the observed ledger is empty, an empty record agrees with it, and the gate
    prints a pass — so the one arrangement under which this check is worthless is also
    the one it would have reported as clean. Every job that runs the suite carries
    `fetch-depth: 0`, and `test_the_workflow_gives_the_suite_the_history_it_needs`
    below is what says so.
    """

    def test_the_epoch_is_reachable_from_here(self):
        try:
            revisions.epoch_is_reachable()
            revisions.epoch_is_an_ancestor()
        except revisions.Unreadable as exc:
            self.fail(f"DEC-8's gate cannot read history, so it is checking nothing: "
                      f"{exc}")

    def test_the_workflow_gives_the_suite_the_history_it_needs(self):
        """Read out of `ci.yml`, not recalled.

        A job that runs the suite without `fetch-depth: 0` turns this whole module into
        a green no-op on the one machine whose verdict is the release gate.
        """
        workflow = os.path.join(ROOT, ".github", "workflows", "ci.yml")
        with open(workflow, encoding="utf-8") as stream:
            lines = stream.readlines()

        jobs, current = {}, None
        for line in lines:
            stripped = line.rstrip("\n")
            if (stripped and not stripped.startswith(" ")
                    or (stripped.startswith("  ") and not stripped.startswith("   ")
                        and stripped.rstrip().endswith(":"))):
                if stripped.startswith("  ") and stripped.rstrip().endswith(":"):
                    current = stripped.strip().rstrip(":")
                    jobs[current] = []
                    continue
            if current is not None:
                jobs[current].append(stripped)

        running = {name: body for name, body in jobs.items()
                   if any("unittest discover" in line for line in body)}
        self.assertTrue(running,
                        "no job in ci.yml runs the suite; this test read the wrong file")
        for name, body in sorted(running.items()):
            with self.subTest(job=name):
                text = "\n".join(body)
                self.assertIn("actions/checkout", text, f"{name} does not check out")
                self.assertIn(
                    "fetch-depth: 0", text,
                    f"the {name} job runs the suite over a shallow clone. "
                    f"{HistoryIsReadableAtAll.__doc__.splitlines()[0]}")


class EveryMoveCarriesItsDecision(unittest.TestCase):
    """DEC-8's sentence, as close as a program can get to it.

    What is checked is that a move was *recorded*, not that the recorded argument is a
    good one — the requirement binds the record, and whether prose is true is outside
    any reader, which is the same limit DEC-4 was narrowed to at 0.103.0.

    Both directions, because a ledger checked one way is a count. An unrecorded move is
    the edit the requirement is about; a recorded move that never happened is the
    record somebody wrote ahead of the edit, which would let the next real move land
    against a slot already open.
    """

    def test_no_declaration_or_fixture_moved_without_a_recorded_decision(self):
        problems = revisions.disagreements()
        self.assertEqual(
            problems, [],
            "\n".join(["DEC-8: a move with no decision behind it, or a decision "
                       "behind no move:", *problems]))

    def test_all_three_doors_are_watched(self):
        """The gate's own coverage, against the doors history shows were used.

        Measured before the gate was written (`local/dec8/expect-moves.txt`): 79
        `expect` values moved, `8ce2b9b` withdrew six declarations rather than editing
        them, and 13 commits edited the served trees. A gate built for the first door
        alone would have reported full coverage with two doors open, so the kinds it
        can emit are pinned here rather than left to the tool to agree with itself.
        """
        self.assertEqual(set(revisions.KINDS), {"expect", "withdrawal", "fixture"})

    def test_the_watched_paths_are_derived_from_what_the_harness_serves(self):
        """Not a list beside the harness's list.

        `FixtureSite.material()` decides which directories reach which origin; if this
        gate kept its own copy, moving a tree would leave the copy answering for a
        mapping that no longer exists. That is the shape `audit_error_kinds.py` was
        repaired out of at 0.102.0 and the one `EveryToolGateRunsHereToo` was repaired
        out of at 0.97.1.
        """
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from harness import FixtureSite

        watched = set(revisions.watched_paths())
        for label, dirs in FixtureSite.material().items():
            for part in dirs:
                with self.subTest(origin=label, tree=part):
                    self.assertIn(f"tests/fixtures/{part}", watched)


class TheStampIsRecomputedNotReadBack(unittest.TestCase):
    """DEC-9's disease, deliberately not repeated on the instrument being added.

    A `registry_version` a hand can set while the content stays put is a stamp, not a
    freshness check, and DEC-9 stays `partial` on the manifest for exactly that reason.
    The fixture digest is not that: it is re-derived from the bytes of every file the
    harness serves, with line endings normalised so it identifies the material rather
    than the checkout. A hand that edits the stamp reddens here; a hand that edits a
    page reddens here too, and then has to say why in `triage`.
    """

    def test_the_recorded_digest_is_what_the_material_hashes_to(self):
        problems = revisions.stamp_disagreement()
        self.assertEqual(
            problems, [],
            "\n".join(["the manifest's fixture digest and the fixture material have "
                       "come apart:", *problems]))

    def test_every_served_origin_has_a_digest(self):
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from harness import FixtureSite

        stored = revisions.manifest_at(None).get("fixture_digest") or {}
        self.assertEqual(
            set(stored), set(FixtureSite.material()),
            "an origin the harness serves carries no digest, so its pages can be "
            "edited under a declaration without anything noticing")

    def test_the_digest_ignores_line_endings_and_not_content(self):
        """The normalisation, proved in both directions on a byte string.

        A digest taken over raw bytes identifies the working copy rather than the
        material: through a clone that translates line endings every comparison across
        two machines becomes a false difference, and a gate that cries without cause is
        one the next reader turns off.
        """
        self.assertEqual(revisions._normalise(b"a\r\nb"),
                         revisions._normalise(b"a\nb"))
        self.assertEqual(revisions._normalise(b"a\rb"), revisions._normalise(b"a\nb"))
        self.assertNotEqual(revisions._normalise(b"a\nb"),
                            revisions._normalise(b"a\nc"))


class TheRecordHasAShape(unittest.TestCase):
    """A field filled in is not a decision taken.

    DEC-8 says both outcomes are legitimate — the prediction may have been wrong, or
    the checker may have been — and only the unrecorded edit is not. So a record has to
    be able to say *which*, and one that does not name a side has not recorded the
    thing the requirement asks for. The length floor is the cheapest available refusal
    of an empty `why`; it cannot tell a real argument from forty characters of filler,
    and does not claim to.
    """

    def test_the_vocabulary_can_say_what_actually_happened(self):
        """Four values, and the fourth was added the first time this gate met real work.

        It had three — the prediction was wrong, the checker was wrong, the fixture was
        wrong — which assumes every move is somebody's mistake. At 0.105.0 the broken
        fixture's alt became `huge.png` so that a signal added in the same release is
        exercised by a served page, and no side was wrong. With three values the only
        way to record that edit was to claim the fixture had been in error: **a
        vocabulary that cannot say what happened produces a record that lies, and the
        gate goes green over it.**

        What did not change is that the move must be recorded. DEC-8 asks that no edit
        to either side be silent, never that every edit is a mistake.
        """
        self.assertEqual(
            set(revisions.DECISIONS),
            {"prediction-was-wrong", "checker-was-wrong", "fixture-was-wrong",
             "new-material"})

    def test_the_records_in_the_tree_are_all_readable(self):
        problems = revisions.malformed(revisions.recorded())
        self.assertEqual(problems, [], "\n".join(["a record that cannot be read:",
                                                  *problems]))

    def test_a_record_not_saying_what_was_decided_is_refused(self):
        rows = [{"kind": "expect", "origin": "good", "item": "AR-151",
                 "from": "PASS", "to": "FAIL",
                 "why": "a sentence long enough to clear the floor this gate sets"}]
        self.assertTrue(any("decided" in line for line in revisions.malformed(rows)))

    def test_a_record_with_an_empty_argument_is_refused(self):
        rows = [{"kind": "expect", "origin": "good", "item": "AR-151",
                 "from": "PASS", "to": "FAIL",
                 "decided": "prediction-was-wrong", "why": "fixed"}]
        self.assertTrue(any("argument" in line for line in revisions.malformed(rows)))

    def test_a_record_naming_a_kind_the_gate_cannot_observe_is_refused(self):
        rows = [{"kind": "reconsidered", "origin": "good", "item": "AR-151",
                 "from": "PASS", "to": "FAIL", "decided": "prediction-was-wrong",
                 "why": "a sentence long enough to clear the floor this gate sets"}]
        self.assertTrue(any("kind" in line for line in revisions.malformed(rows)))

    def test_new_material_is_a_decision_the_record_accepts(self):
        """The 0.105.0 case, pinned as a row rather than only as a vocabulary entry.

        A fixture move recorded as `new-material` must pass `malformed`; if it did not,
        the only readable record of that edit would be a false one.
        """
        rows = [{"kind": "fixture", "origin": "broken", "item": None,
                 "from": "aaaaaaaaaaaa", "to": "bbbbbbbbbbbb",
                 "decided": "new-material",
                 "why": "the page was given a case a new check needs, and no side "
                        "was wrong"}]
        self.assertEqual(revisions.malformed(rows), [])


if __name__ == "__main__":
    unittest.main()
