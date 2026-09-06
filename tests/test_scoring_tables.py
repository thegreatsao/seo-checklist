"""SCR-2 — the three scoring tables are one instrument, and changing one is a release event.

`openspec/specs/scoring/` §2 names three tables: severity weight, verdict credit and
effort cost. Between them they decide the headline score a client quotes and the order
of the fix list they work through. SCR-2 says a change to any value is a change of
*instrument*: it must be stated in the release that does it, it invalidates comparison
with every archived run scored under the old table, and a comparison that spans one must
refuse or warn.

SCR-14 closed the first half of that in 0.93.x: `TheNormativeTablesAreReadFromTheDocument`
in `test_runner.py` parses §2 out of the spec and holds the running code against it row by
row, so a weight cannot move in the code alone. What it does not read — and says so in its
own `Reader:` line — is the half about people: that the change is *stated in the release
that does it*, that the archive stops being comparable, and that a comparison spanning the
change warns. A weight could still move in code and document together, silently, with the
whole archive quietly re-based and CI green.

That half is what this file reads, in three classes:

* `TheDeclaration` — the instrument in force has a name, `tests/scoring-tables.json`
  declares it, and the release named there states the change in those words. This is the
  one that fails on a quiet edit;
* `AComparisonAcrossTheChange` — `diff_runs` warns when the baseline was scored under a
  different instrument, and says something different when the baseline is old enough not
  to know;
* `TheArtifactRecordsTheInstrument` — a live run stamps what scored it, or the two above
  have nothing to compare. Live rather than by fixture, for the reason `test_shapes.py`
  gives about the four site shapes: the two readers above hold `diff_runs` and a
  constant, and neither of them proves the *runner* wrote the stamp into the file that
  gets archived.

The declaration deliberately does **not** transcribe the values. §2 is already normative
and SCR-14 already holds the code against it; a fourth copy of the numbers here would be
the hand-written set GOV-3 exists to count, and it would agree with whichever copy was
edited last. What it declares is the stamp — a name for the instrument as a whole, taken
from §2 rather than from the constants, which is a thing a release note can quote and a
run artifact can carry.
"""
import json
import os
import re
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(ROOT, "skills", "seo-checklist")
SCRIPTS = os.path.join(SKILL, "scripts")
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import checklist_runner as runner  # noqa: E402
from checklist_runner import diff_runs  # noqa: E402
from harness import served, spawn  # noqa: E402

RUNNER = os.path.join(SCRIPTS, "checklist_runner.py")

DECLARATION = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "scoring-tables.json")
CHANGELOG = os.path.join(ROOT, "CHANGELOG.md")


def declared() -> dict:
    with open(DECLARATION, encoding="utf-8") as fh:
        return json.load(fh)


def changelog_entry(version: str) -> str | None:
    """The body of one `## <version> — …` section, or None if there is no such heading."""
    with open(CHANGELOG, encoding="utf-8") as fh:
        text = fh.read()
    start = re.search(r"^## %s(?:\s|$).*$" % re.escape(version), text, re.M)
    if not start:
        return None
    rest = text[start.end():]
    nxt = re.search(r"^## ", rest, re.M)
    return rest[:nxt.start()] if nxt else rest


class TheDeclaration(unittest.TestCase):
    """A table may not move without a person restating it here and in the release.

    Every assertion below names the remedy in its failure message, because the person
    who trips this test is usually not the person who wrote it, and "assertion failed"
    would leave them to guess whether the tree or the declaration is wrong. Neither is
    wrong by default: the test asserts they agree, and which one to move is a decision
    about whether the instrument really changed.
    """

    HOWTO = ("\n\nIf the change is intended: put the stamp printed above into "
             "tests/scoring-tables.json, move the old stamp to `supersedes`, set "
             "`declared_in` to the release making the change, and write "
             "'%s <old stamp> -> <new stamp>' into that release's CHANGELOG entry. "
             "Every archived run scored under the old table stops being comparable, "
             "which is the cost this declaration exists to make visible.")

    def setUp(self):
        self.d = declared()
        self.howto = self.HOWTO % self.d["marker"]

    def test_the_stamp_in_the_tree_is_the_declared_one(self):
        self.assertEqual(
            runner.scoring_stamp(), self.d["stamp"],
            "the scoring tables in scripts/checklist_runner.py are not the declared "
            "ones. The tree now stamps %s, tests/scoring-tables.json declares %s.%s"
            % (runner.scoring_stamp(), self.d["stamp"], self.howto))

    def test_the_stamp_names_the_tables_the_document_makes_normative(self):
        """The stamp is computed here from §2 of the spec, not from the constants.

        Taken from the code, it would be a digest of whatever the code currently says,
        and would agree with a quiet edit as long as the author updated this file —
        which is the failure mode a declaration exists to prevent. §2 is the normative
        text; SCR-14's reader already holds the code against it row by row, so a stamp
        anchored there is a name for the instrument both halves agree on.
        """
        from test_runner import TheNormativeTablesAreReadFromTheDocument as Doc
        by_heading = Doc.tables()
        document = {"severity_weight": by_heading["severity weight"],
                    "verdict_credit": by_heading["verdict credit"],
                    "effort_cost": by_heading["effort cost"]}
        self.assertEqual(runner.scoring_stamp_of(document), self.d["stamp"],
                         "openspec/specs/scoring/ §2 and tests/scoring-tables.json "
                         "disagree about which instrument is in force." + self.howto)

    def test_the_spec_prints_the_stamp_it_is_in_force_under(self):
        """§2 names the stamp in prose, so a reader of the document knows which
        instrument it describes without running anything. Prose is a copy, and an
        uncompared copy drifts — this is the comparison."""
        with open(os.path.join(ROOT, "openspec", "specs", "scoring", "spec.md"),
                  encoding="utf-8") as fh:
            spec = fh.read()
        self.assertIn(self.d["stamp"], spec,
                      "openspec/specs/scoring/ §2 does not print the stamp %s that "
                      "tests/scoring-tables.json declares" % self.d["stamp"])

    def test_the_declaring_release_exists_in_the_changelog(self):
        entry = changelog_entry(self.d["declared_in"])
        self.assertIsNotNone(
            entry,
            "tests/scoring-tables.json says the tables were declared in %s, and "
            "CHANGELOG.md has no entry for that version. A table change nobody can "
            "read about in the release notes is the quiet edit SCR-2 forbids."
            % self.d["declared_in"])

    def test_the_release_names_the_instrument_it_put_in_force(self):
        """Whatever else it says, the release has to name the stamp.

        This is the assertion an author cannot satisfy by copying last release's
        paragraph forward: the stamp is the one string in it that moves when the
        instrument does.
        """
        entry = changelog_entry(self.d["declared_in"]) or ""
        self.assertIn(self.d["stamp"], entry,
                      "CHANGELOG entry %s names no stamp %s, so a reader cannot tell "
                      "which instrument it put in force."
                      % (self.d["declared_in"], self.d["stamp"]))

    def test_a_release_that_changed_the_tables_says_so_in_those_words(self):
        """SCR-2's first clause, read literally: *stated in the release that does it*.

        Conditional on `supersedes`, because the clause is about a change. The first
        declaration named an instrument that already existed and moved no value, and a
        release that announced a table change it did not make would be the same kind of
        false statement in the other direction. From the second declaration on, the
        marker and both stamps are owed: a reader of the release has to be able to see
        which archived runs stopped being comparable, and against what.
        """
        old = self.d["supersedes"]
        if old is None:
            self.skipTest("the first declaration changed no value; nothing to declare")
        entry = changelog_entry(self.d["declared_in"]) or ""
        self.assertNotEqual(old, self.d["stamp"],
                            "`supersedes` repeats the current stamp, which would mean "
                            "the release declared a change it did not make")
        self.assertIn(self.d["marker"], entry,
                      "CHANGELOG entry %s does not contain the marker %r, so the "
                      "release does not state that it changed the instrument."
                      % (self.d["declared_in"], self.d["marker"]))
        self.assertIn(old, entry,
                      "CHANGELOG entry %s does not name the superseded stamp %s, so "
                      "it does not say which archived runs stopped being comparable."
                      % (self.d["declared_in"], old))

    def test_the_declaration_covers_exactly_the_tables_the_stamp_covers(self):
        """A fourth table added to `scoring_tables()` and not to the declaration would
        change the stamp and be caught; one added to neither would be an unstamped part
        of the instrument, and this is the assertion that says the two sets are the
        same set rather than merely agreeing today."""
        self.assertEqual(sorted(runner.scoring_tables()), sorted(self.d["covers"]),
                         "the stamp covers a different set of tables than the "
                         "declaration says it does")


class TheTablesAreUsedAndNotOnlyDeclared(unittest.TestCase):
    """A declaration guards a constant; it does not prove the constant is the one the
    score is computed with. Until 0.94.0 the verdict credits were not a table at all —
    the same three numbers were written inline twice, once for the headline and once for
    the category bars — so a declaration of them could have been true while the
    arithmetic used something else."""

    def rows(self, *statuses):
        return [{"id": "X%d" % n, "title": "x", "status": s, "severity": "critical",
                 "category": "c", "category_label": "C"}
                for n, s in enumerate(statuses)]

    def test_the_credit_table_covers_exactly_the_statuses_that_carry_weight(self):
        """Which statuses may be weighed belongs to `specs/verdicts/` VRD-6 and VRD-7,
        and scoring must not restate it. So the set is derived from `score()` — a status
        carries weight exactly when a single row bearing it comes back `decided` — and
        compared with the table's keys.

        Written this way because a hand-kept membership list is the thing GOV-3 counts:
        a table missing `WARN` would score every warning as a failure, and no list can
        say what is absent from it. `NO_DATA` appearing here would be the opposite
        defect, an undecided item in the denominator.
        """
        from checklist_runner import VERDICT_CREDIT
        every = (runner.PASS, runner.WARN, runner.FAIL, runner.NO_DATA,
                 runner.MANUAL, runner.LLM_PENDING, runner.NA)
        carries = {s for s in every if runner.score(self.rows(s))["decided"]}
        self.assertEqual(set(VERDICT_CREDIT), carries)

    def test_the_effort_table_covers_every_effort_the_registry_uses(self):
        """Derived from the registry rather than from the table, for the same reason: an
        item whose effort has no cost would be priced by the `medium` fallback in
        `priority_of`, and it would sit in the fix list looking like a decision somebody
        made."""
        from checklist_runner import EFFORT_COST
        with open(os.path.join(SKILL, "resources", "config", "checklist.json"),
                  encoding="utf-8") as fh:
            items = json.load(fh)["items"]
        self.assertEqual(set(EFFORT_COST), {i["effort"] for i in items})

    def test_the_headline_is_the_credit_table_applied_to_the_weight_table(self):
        graded = self.rows(runner.PASS, runner.WARN, runner.FAIL)
        w = runner.SEVERITY_WEIGHT["critical"]
        expected = round(100 * sum(runner.VERDICT_CREDIT[s] for s in
                                   (runner.PASS, runner.WARN, runner.FAIL)) / (3 * w) * w)
        self.assertEqual(runner.score(graded)["seo_score"], expected)

    def test_the_category_bar_uses_the_same_credits_as_the_headline(self):
        """They were two independent copies of 1.0/0.5/0.0 until 0.94.0, and an edit to
        one would have moved a bar away from the headline above it silently."""
        graded = self.rows(runner.PASS, runner.WARN, runner.FAIL)
        result = runner.score(graded)
        self.assertEqual(result["by_category"]["c"]["score"], result["seo_score"])


class AComparisonAcrossTheChange(unittest.TestCase):
    """SCR-2's third clause: a comparison spanning a table change refuses or warns."""

    def run_of(self, **extra):
        payload = {"items": [{"id": "A", "title": "A", "status": runner.PASS}]}
        payload.update(extra)
        return payload

    def test_a_baseline_under_another_instrument_is_warned_about(self):
        _, note = diff_runs(self.run_of(scoring_tables={"stamp": "0000aaaa1111"}),
                            self.run_of(scoring_tables={"stamp": "2222bbbb3333"}))
        self.assertIn("0000aaaa1111", note)
        self.assertIn("2222bbbb3333", note)
        self.assertIn("not comparable", note)

    def test_a_baseline_from_before_the_stamp_says_it_cannot_be_established(self):
        """Different sentence on purpose. A run archived before 0.94.0 carries no stamp,
        and reporting that as "the tables changed" would accuse an edit nobody made."""
        _, note = diff_runs(self.run_of(),
                            self.run_of(scoring_tables={"stamp": "2222bbbb3333"}))
        self.assertIn("cannot be established", note)
        self.assertNotIn("the instrument changed", note)

    def test_the_same_instrument_says_nothing(self):
        same = {"stamp": "2222bbbb3333"}
        _, note = diff_runs(self.run_of(scoring_tables=same),
                            self.run_of(scoring_tables=same))
        self.assertEqual(note, "")

    def test_two_reasons_are_stated_once_each(self):
        """The bug this replaces: the note was built by string concatenation whose last
        branch rebuilt it as `note + <mode sentence> + '. ' + note`, so a run that
        changed both the registry and the mode told the client about the registry twice.

        Every test of `diff_runs` before 0.94.0 moved exactly one axis, so none of them
        ever held two sentences at once. The assertion is over the invariant — no
        sentence appears twice — rather than over the pair that happened to collide.
        """
        _, note = diff_runs(
            self.run_of(registry_version="aaa", mode="live", profile="shop",
                        scoring_tables={"stamp": "0000aaaa1111"}),
            self.run_of(registry_version="bbb", mode="page", profile="blog",
                        scoring_tables={"stamp": "2222bbbb3333"}))
        sentences = [s.strip() for s in note.split(". ") if s.strip()]
        self.assertEqual(len(sentences), len(set(sentences)),
                         "a reason is stated more than once: %r" % note)
        self.assertEqual(len(sentences), 4,
                         "expected one sentence for each of registry, profile, mode and "
                         "scoring tables: %r" % note)


class TheArtifactRecordsTheInstrument(unittest.TestCase):
    """One live audit: the file that reaches `.seo-runs/` says what scored it.

    Everything above this class reads a constant or a pure function. Neither would
    notice a runner that computed the stamp and forgot to put it in the payload, and
    the payload is the whole mechanism — a stamp that is not archived cannot be
    compared against next month, which is the obligation SCR-2 is about.
    """

    PAGE = ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<title>A page that satisfies the basics</title>"
            "<meta name=\"description\" content=\"Enough of a page for the runner to "
            "reach the end and write an artifact.\"></head><body><h1>A page</h1>"
            "<p>Body copy with enough words in it that the thin-entry guard stays quiet, "
            "because a guard firing here would stop the audit before the thing under "
            "test ran at all.</p></body></html>")

    @classmethod
    def setUpClass(cls):
        work = tempfile.mkdtemp(prefix="seo-scoring-")
        out = os.path.join(work, "results.json")
        with served({"/": cls.PAGE}) as site:
            proc = spawn([sys.executable, RUNNER, site.url, "--allow-private",
                          "--max-rps", "0", "--no-history", "--no-prompt", "--quiet",
                          "--timeout", "90", "--json", out, "--only", "crawling_indexing"],
                         timeout=600)
        if proc.returncode != 0:
            raise AssertionError("the audit exited %s\n%s\n%s"
                                 % (proc.returncode, proc.stdout[-2000:],
                                    proc.stderr[-2000:]))
        with open(out, encoding="utf-8") as fh:
            cls.payload = json.load(fh)

    def test_the_run_carries_the_stamp_of_the_tables_that_scored_it(self):
        self.assertEqual(self.payload["scoring_tables"]["stamp"], runner.scoring_stamp())

    def test_the_run_carries_the_tables_themselves(self):
        """Whole, not only the digest: an archived run has to be able to say what it was
        scored with after the tree has moved on, and a stamp is not reversible."""
        got = {k: v for k, v in self.payload["scoring_tables"].items() if k != "stamp"}
        self.assertEqual(got, runner.scoring_tables())

    def test_the_arc_stamps_its_own_last_point(self):
        """`run_series` stamps the archived points. The current run is appended
        separately, and an unstamped last point would read as a run from before the
        stamp existed — on every report, forever."""
        current = [p for p in self.payload["history"] if p.get("current")]
        self.assertEqual(len(current), 1)
        self.assertEqual(current[0]["scoring_stamp"], runner.scoring_stamp())


if __name__ == "__main__":
    unittest.main()
