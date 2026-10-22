"""`openspec/specs/governance/` GOV-3 for the gates and calibrations in `tools/`: every
hand-written set that describes something this tree states in full is held to it here.

Written in F04 (batch 4b), from a census that counted fourteen of them as named by
nothing. Each describes something closed: the runner's operators, `seo_common.issue()`,
the registry's item ids, the basis-line grammar, the constants a calibration covers, the
debt classes the specs use. Declared before anything ran, and one did not hold:
`audit_assertions.PATTERN_OPS` named two operators the runner does not have and missed
`count_matching_lte`, so a rule's pattern under that operator was never audited.
"""
from __future__ import annotations

import inspect
import os
import re
import string
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(ROOT, "skills", "seo-checklist")
sys.path.insert(0, os.path.join(SKILL, "scripts"))
sys.path.insert(0, os.path.join(SKILL, "tools"))

import harness  # noqa: E402
import checklist_runner as runner  # noqa: E402
import seo_common  # noqa: E402

import audit_assertions  # noqa: E402
import audit_catalogue  # noqa: E402
import audit_item_semantics  # noqa: E402
import audit_reachability  # noqa: E402
import audit_score_sensitivity  # noqa: E402
import audit_thresholds  # noqa: E402
import calibrate_css_minification  # noqa: E402
import calibrate_gsc_sample_floors  # noqa: E402
import calibrate_serp_length  # noqa: E402
import notebook_sync  # noqa: E402
import spec_debt  # noqa: E402

COMPARISONS = ("gte", "gt", "lte", "lt")


def passes(op: str, bound, value) -> bool | None:
    return runner.evaluate({"path": "x", op: bound}, {"x": value})[0]


def basis_lines() -> dict[tuple[str, str], dict]:
    return {(entry["file"], entry["name"]): entry for entry in audit_thresholds.scan()[0]}


class RunnerOperators(unittest.TestCase):

    def test_pattern_ops_are_the_operators_that_compile_a_pattern(self):
        """Derived from the runner's behaviour, not restated: an operator takes a
        pattern exactly when an invalid one makes it raise `re.error`."""
        compiling = set()
        for op in runner.THRESHOLD_OPS:
            bound = ["(", 0] if op == "count_matching_lte" else "("
            try:
                runner.evaluate({"path": "x", op: bound}, {"x": ["a"]})
            except re.error:
                compiling.add(op)
            except (TypeError, ValueError):
                pass
        self.assertEqual(set(audit_assertions.PATTERN_OPS), compiling)

    def test_complements_are_the_comparisons_and_their_negations(self):
        self.assertEqual({left for left, _ in audit_reachability.COMPLEMENTS},
                         set(COMPARISONS))
        for left, right in audit_reachability.COMPLEMENTS:
            for value in (4, 5, 6):
                with self.subTest(pair=(left, right), value=value):
                    self.assertEqual(passes(left, 5, value), not passes(right, 5, value))

    def test_an_empty_band_is_exactly_when_no_value_fails_and_still_warns(self):
        """Every same-direction pair, each lambda checked against a brute force over
        the values around both bounds."""
        lower, upper = ("gte", "gt"), ("lte", "lt")
        pairs = {(a, b) for group in (lower, upper) for a in group for b in group}
        self.assertEqual(set(audit_reachability.EMPTY_BAND), pairs)
        grid = [x / 2 for x in range(0, 21)]
        for (left, right), empty in audit_reachability.EMPTY_BAND.items():
            for a in (3, 5, 7):
                for b in (3, 5, 7):
                    found = any(passes(left, a, v) is False and passes(right, b, v)
                                for v in grid)
                    with self.subTest(pair=(left, right), a=a, b=b):
                        self.assertEqual(bool(empty(a, b)), not found)


class TheTreesOwnVocabularies(unittest.TestCase):

    def test_convention_is_what_issue_always_writes(self):
        required = tuple(name for name, param in
                         inspect.signature(seo_common.issue).parameters.items()
                         if param.default is inspect.Parameter.empty)
        self.assertEqual(tuple(audit_catalogue.CONVENTION), required)

    def test_every_ruling_is_on_an_item_in_the_registry(self):
        ids = {item["id"] for item in harness.registry()["items"]}
        self.assertEqual(sorted(set(audit_item_semantics.REVIEWED) - ids), [])

    def test_candidate_efforts_are_the_runner_s_table_and_alternatives_to_it(self):
        candidates = audit_score_sensitivity.CANDIDATE_EFFORTS
        self.assertEqual(candidates["shipped (1/2/4)"], runner.EFFORT_COST)
        for name, efforts in candidates.items():
            self.assertEqual(set(efforts), set(runner.EFFORT_COST), name)

    def test_a_measured_line_carries_exactly_the_measured_keys(self):
        """The grammar GOV-1 gives a `measured` basis, held against every such line in
        the tree rather than against the parser that reads them."""
        lines = 0
        for path in audit_thresholds._script_paths():
            with open(path, encoding="utf-8") as stream:
                for line in stream:
                    found = re.search(r"#\s*basis:\s*measured\s*[—-]\s*(.*)", line)
                    if found:
                        lines += 1
                        keys = {part.split("=", 1)[0].strip().lower()
                                for part in found.group(1).split(";") if "=" in part}
                        self.assertEqual(keys, set(audit_thresholds.MEASURED_KEYS), line)
        self.assertGreaterEqual(lines, 14)

    def test_the_debt_classes_are_the_ones_the_specs_use(self):
        used = set()
        for name in os.listdir(spec_debt.SPECS):
            path = os.path.join(spec_debt.SPECS, name, "spec.md")
            if os.path.exists(path):
                with open(path, encoding="utf-8") as stream:
                    used |= set(re.findall(r"^\| \*\*([a-z]+)\*\* \|", stream.read(), re.M))
        self.assertEqual(used, set(spec_debt.CLASSES))
        # The Appendix B row pattern reads the same five, not a copy of them.
        for name in (*spec_debt.CLASSES, "settled"):
            self.assertEqual(bool(spec_debt.ROW.match(f"| **{name}** | X |")),
                             name in spec_debt.CLASSES, name)

    def test_every_fixed_notebook_source_is_in_this_tree(self):
        for title, kind, path in notebook_sync.FIXED:
            with self.subTest(title=title):
                where = os.path.join(ROOT, path)
                self.assertTrue(os.path.isdir(where) if kind == "agents"
                                else os.path.isfile(where), where)


class CalibrationsCoverTheirConstants(unittest.TestCase):
    """Each calibration names the constants it measures. Held both ways: each name is
    a basis-lined constant in the script, and each constant whose `measured` basis
    cites the calibration's corpus is named."""

    def covered(self, script: str, corpus: str) -> set[str]:
        return {name for (file, name), entry in basis_lines().items()
                if file == f"scripts/{script}" and entry["kind"] == "measured"
                and corpus in self.line(file, entry["line"])}

    @staticmethod
    def line(file: str, number: int) -> str:
        """The comment block above a constant, where its basis line is."""
        with open(os.path.join(SKILL, file), encoding="utf-8") as stream:
            lines = stream.read().splitlines()
        block, index = [], number - 2
        while index >= 0 and lines[index].lstrip().startswith("#"):
            block.insert(0, lines[index])
            index -= 1
        return "\n".join(block)

    def check(self, script: str, names, corpus: str):
        lined = {name for (file, name) in basis_lines() if file == f"scripts/{script}"}
        self.assertEqual(sorted(set(names) - lined), [])
        covered = self.covered(script, corpus)
        self.assertTrue(covered, f"no measured line in {script} cites {corpus}")
        self.assertEqual(sorted(covered - set(names)), [])

    def test_css_minification(self):
        self.check("css_minify_check.py", calibrate_css_minification.CONSTANT_NAMES,
                   "tools/calibration/css-minification.json")

    def test_serp_length(self):
        self.check("article_seo.py", calibrate_serp_length.CONSTANT_NAMES,
                   "tools/calibration/serp-length.json")

    def test_gsc_sample_floors(self):
        pairs = calibrate_gsc_sample_floors.PAIRS
        floors = calibrate_gsc_sample_floors.UNCALIBRATED_FLOORS
        lined = set(basis_lines())
        for pair in pairs:
            for key in ("threshold_constant", "floor_constant"):
                self.assertIn((f"scripts/{pair['script']}", pair[key]), lined)
        for floor in floors:
            self.assertIn((f"scripts/{floor['script']}", floor["constant"]), lined)
        self.assertEqual({p["floor_constant"] for p in pairs},
                         self.covered("gsc_checker.py", "binomial CTR proportion"))

    def test_the_letter_frequencies_are_the_published_table(self):
        """The English letter frequencies as Lewand (2000) gives them and Wikipedia's
        "Letter frequency" tabulates: every letter once, summing to 100 per cent."""
        table = calibrate_serp_length.ENGLISH_LETTER_FREQUENCY
        self.assertEqual(sorted(table), list(string.ascii_lowercase))
        self.assertAlmostEqual(sum(table.values()), 100.0, delta=0.01)
        self.assertEqual((table["e"], table["t"], table["z"]), (12.702, 9.056, 0.074))


if __name__ == "__main__":
    unittest.main()
