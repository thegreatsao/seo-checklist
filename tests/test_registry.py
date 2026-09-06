"""The registry is the audit's contract, so these tests guard the contract.

Most of what can go wrong here fails silently at runtime: a rule pointing at a
JSON path no script emits reports NO_DATA forever and looks like a site problem;
an item whose script was never shipped does the same. Nothing surfaces unless
something checks.
"""
import ast
import contextlib
import datetime
import importlib.util
import io
import json
import math
import os
import re
import statistics
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(ROOT, "skills", "seo-checklist")
SCRIPTS = os.path.join(SKILL, "scripts")
TOOLS = os.path.join(SKILL, "tools")
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness  # noqa: E402

REGISTRY = os.path.join(SKILL, "resources", "config", "checklist.json")
SHAPES = os.path.join(SKILL, "resources", "references", "script-output-shapes.md")
PROFILES = os.path.join(SKILL, "resources", "config", "profiles.json")
TITLE_OVERRIDES = os.path.join(
    SKILL, "resources", "config", "title-overrides.json")

with open(REGISTRY, encoding="utf-8") as f:
    DATA = json.load(f)
ITEMS = DATA["items"]

VALID_SOURCES = {"script", "llm", "manual", "gsc"}
VALID_SEVERITY = {"critical", "high", "medium", "low"}
VALID_EFFORT = {"low", "medium", "high"}
VALID_REQUIRES = {"offline", "fetch", "crawl", "api", "gsc", "safe_browsing"}


class RegistryShape(unittest.TestCase):
    def test_ids_unique(self):
        ids = [i["id"] for i in ITEMS]
        dupes = {i for i in ids if ids.count(i) > 1}
        self.assertEqual(dupes, set(), f"duplicate item ids: {dupes}")

    def test_every_item_has_the_required_fields(self):
        for i in ITEMS:
            for key in ("id", "category", "category_label", "title", "severity",
                        "source", "effort", "fix"):
                self.assertIn(key, i, f"{i.get('id')} missing {key}")
            self.assertIn(i["severity"], VALID_SEVERITY, i["id"])
            self.assertIn(i["source"], VALID_SOURCES, i["id"])
            self.assertIn(i["effort"], VALID_EFFORT, i["id"])

    def test_registry_is_versioned(self):
        self.assertTrue(DATA.get("registry_version"),
                        "results cannot say which registry produced them")
        self.assertEqual(DATA.get("item_count"), len(ITEMS))

    def test_script_items_are_fully_specified(self):
        for i in ITEMS:
            if i["source"] != "script":
                continue
            chk = i.get("check")
            self.assertTrue(chk, f"{i['id']} is source=script with no check block")
            self.assertTrue(chk.get("script"), f"{i['id']} names no script")
            self.assertIn(chk.get("requires"), VALID_REQUIRES, i["id"])
            self.assertTrue(chk.get("assert"), f"{i['id']} has no assert rule")
            self.assertIn("path", chk["assert"], f"{i['id']} assert has no path")

    def test_assert_rules_use_operators_the_runner_implements(self):
        """Checked against the runner's source rather than a list kept here — a
        list in the test drifts, and an operator the runner never sees produces
        a rule that silently reports NO_DATA forever.

        A substring search until 0.93.8, which is weaker than it reads: `"eq"`
        appears in this file's own prose, so a rule naming an operator the evaluator
        does not implement would pass on a mention in a comment. It now compares
        against the vocabulary `AnAssertionLanguageWithOneOperatorPerRule` derives
        from `evaluate()`'s branches.
        """
        vocabulary = operator_vocabulary()
        for i in ITEMS:
            chk = i.get("check") or {}
            for rule in (chk.get("assert"), chk.get("warn"), chk.get("applies_when")):
                if not rule:
                    continue
                for key in set(rule) - {"path", "field", "missing_is", "scope"}:
                    self.assertIn(key, vocabulary,
                                  f"{i['id']} uses operator {key!r}, which "
                                  f"checklist_runner.py does not implement")

    def test_video_applicability_is_narrowly_declared(self):
        declared = {item["id"]: item["check"]["applies_when"]
                    for item in ITEMS if (item.get("check") or {}).get("applies_when")}
        self.assertEqual(declared, {
            "MB-102": {"path": "videos", "gt": 0},
            "MD-190": {"path": "videos", "gt": 0},
        })

    def test_only_safe_browsing_verdicts_require_its_key(self):
        requires = {item["id"]: item["check"]["requires"] for item in ITEMS
                    if (item.get("check") or {}).get("script") ==
                    "domain_safety_check.py"}
        self.assertEqual({item_id for item_id, need in requires.items()
                          if need == "safe_browsing"},
                         {"SE-114", "SE-116", "TE-171"})
        self.assertEqual(requires["TE-167"], "api")
        self.assertEqual(requires["TE-178"], "api")
        self.assertEqual(requires["TE-179"], "api")

    def test_a_rule_does_more_than_name_a_path(self):
        """A rule of only {"path": ...} can never decide anything."""
        for i in ITEMS:
            rule = (i.get("check") or {}).get("assert")
            if rule:
                self.assertGreater(len(set(rule) - {"path", "missing_is"}), 0,
                                   f"{i['id']} asserts nothing about {rule['path']}")

    def test_every_referenced_script_exists(self):
        for i in ITEMS:
            script = (i.get("check") or {}).get("script")
            if script:
                self.assertTrue(os.path.exists(os.path.join(SCRIPTS, script)),
                                f"{i['id']} references missing script {script}")

    def test_every_llm_item_has_a_lens(self):
        """Without a lens an item belongs to no agent and is never answered."""
        for i in ITEMS:
            if i["source"] == "llm":
                self.assertTrue(i.get("lens"), f"{i['id']} has no lens")

    def test_manual_and_llm_items_are_never_low_effort(self):
        for i in ITEMS:
            if i["source"] == "manual":
                self.assertEqual(i["effort"], "high", i["id"])
            if i["source"] == "llm":
                self.assertIn(i["effort"], {"medium", "high"}, i["id"])


class DocsPointAtThingsThatExist(unittest.TestCase):
    """Cross-references between documents rot silently.

    The known-issues list is only useful if the documents that raise a caveat point
    at it, and a relative link that stops resolving is invisible until a reader
    follows it. Both are the documentation form of the failure this whole suite
    guards: something that reads as true and is not."""

    DOCS = ("README.md", "CHANGELOG.md", "CREDITS.md", "KNOWN-ISSUES.md",
            os.path.join("skills", "seo-checklist", "SKILL.md"))

    def _read(self, rel):
        with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
            return f.read()

    def test_every_relative_markdown_link_resolves(self):
        broken = []
        for rel in self.DOCS:
            base = os.path.dirname(os.path.join(ROOT, rel))
            for target in re.findall(r"\]\(([^)#:]+\.md)[^)]*\)", self._read(rel)):
                if not os.path.exists(os.path.join(base, target)):
                    broken.append(f"{rel} -> {target}")
        self.assertEqual(broken, [], f"dead links: {broken}")

    def test_the_caveats_point_at_the_known_issues_list(self):
        """Whoever fixes one of these must find every place that documents it. The
        set of files naming KNOWN-ISSUES.md is that list."""
        self.assertTrue(os.path.exists(os.path.join(ROOT, "KNOWN-ISSUES.md")))
        for rel in ("README.md", "CHANGELOG.md",
                    os.path.join("skills", "seo-checklist", "SKILL.md")):
            self.assertIn("KNOWN-ISSUES.md", self._read(rel),
                          f"{rel} raises caveats but does not point at the list")

    def test_no_document_still_carries_the_retracted_sample_caveat(self):
        """`--sample` spreads its picks across the sitemap as of 0.3.0. The caveat
        that said otherwise was correct when written and is now the wrong thing to
        tell a reader — a stale warning costs the same trust as a missing one."""
        for rel in self.DOCS + ("skills/seo-checklist/scripts/checklist_runner.py",):
            text = self._read(rel)
            self.assertNotIn("document order, not a", text, f"{rel} is out of date")
            self.assertNotIn("is not a sample", text, f"{rel} is out of date")


class EveryThresholdSaysWhatItRestsOn(unittest.TestCase):
    """§2 of KNOWN-ISSUES.md, made checkable.

    Four layers of tests prove a named field answers a named question, that a check
    can tell two sites apart, that nothing is decided about a site which answered
    nothing. **None of them argues with the numbers.** A site audited at the wrong
    threshold gets a confident verdict about the wrong question, which is what this
    suite is worst at seeing, and calibration is not more tests — it is deciding what
    each number rests on and writing it beside the number.

    This is the gate that keeps "beside the number" true. It does not check that a
    threshold is *right*; nothing automatic can. It checks that the basis is stated,
    so a reader who disagrees argues with a claim instead of with a bare integer.
    """

    # The unnamed count is a ceiling rather than a list, for the same reason the
    # request count in CI is: a printed number in a green build is a number nobody
    # reads. It may fall freely and may not rise without somebody deciding to raise
    # it here. 77 at 0.13.0, and **zero** from 0.15.0: every number a comparison in
    # this tree reads now has a name and a stated basis. Kept as a ceiling rather than
    # deleted, because zero is a state to defend and not an achievement to file away —
    # the next bare literal somebody types fails this.
    UNNAMED_CEILING = 0

    def _tool(self):
        sys.path.insert(0, os.path.join(SKILL, "tools"))
        import audit_thresholds
        return audit_thresholds

    def _run_check(self, source):
        at = self._tool()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "thresholds.py")
            with open(path, "w", encoding="utf-8") as f:
                f.write(source)
            stdout, stderr = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                status = at.main(["--check"], paths=[path])
        return status, stdout.getvalue(), stderr.getvalue()

    def test_a_written_basis_is_counted_even_if_the_scan_cannot_see_it(self):
        at = self._tool()
        named, _ = at.scan()
        expected = {
            ("checklist_runner.py", "HISTORY_RUNS"): "convention",
            ("freshness_checker.py", "FUTURE_DATE_TOLERANCE_DAYS"): "standard",
            ("gsc_cannibalization.py", "SHORT_NEAR_BRAND_EDITS"): "convention",
            ("gsc_cannibalization.py", "LONG_NEAR_BRAND_EDITS"): "convention",
            ("seo_common.py", "THIN_CONTENT_WORDS"): "inherited",
            ("server_log_audit.py", "MAX_VERIFIED_ADDRESSES"): "convention",
            ("tls_certificate.py", "DEFAULT_TIMEOUT"): "inherited",
        }
        for (filename, name), kind in expected.items():
            with self.subTest(file=filename, name=name):
                rows = [row for row in named
                        if os.path.basename(row["file"]) == filename
                        and row["name"] == name]
                self.assertEqual(len(rows), 1, rows)
                self.assertEqual(rows[0]["kind"], kind)

    def test_the_inventory_totals_close(self):
        at = self._tool()
        constants = [row for path in at._script_paths()
                     for row in at.numeric_constants(path)]
        named, _ = at.scan()
        uncounted = at.scan_uncounted()
        with_basis = sum(bool(row["kind"]) for row in constants)
        self.assertEqual(len(named), with_basis)
        self.assertEqual(len(named) + len(uncounted), len(constants))

    def test_the_verdict_totals_are_the_recorded_ones(self):
        """Writing a new basis moves this ledger, deliberately and visibly."""
        at = self._tool()
        named, _ = at.scan()
        uncounted = at.scan_uncounted()
        by_kind = {kind: sum(row["kind"] == kind for row in named)
                   for kind in at.KINDS}
        # 0.80.1 judged the four shapes 0.71.0 had listed and left to a person, and five
        # constants moved out of the uncounted listing into `inherited`: both MinHash
        # numbers and the three `detect_profile` weight tables. They are counted among
        # the numbers a verdict depends on because a declared constant is, whatever its
        # conditions — the MinHash pair's own basis line says no assertion reads the
        # field it feeds, and `DEFAULT_MAX_REDIRECTS` stayed uncounted as a fetch budget.
        #
        # 0.88.0 moved eight more in, and moved them the harder direction: not by
        # adding a number but by admitting that eight already there were deciding
        # verdicts. Seven are caps — pages crawled, crawl depth, links checked,
        # images requested, log lines read, sitemap files followed, stylesheets
        # fetched — and the
        # eighth is `ROW_LIMIT`, the 5,000-row GSC page that MS-023 and KW-071 read
        # `eq 0` off. Each bounds the evidence that could have failed an assertion
        # passing by absence, so `inherited` rising from 67 to 75 is the count
        # getting truer, not the tree getting worse. ROADMAP.md wants this number
        # to fall; it can only fall from a number that is honest first.
        #
        # 0.91.0 names two more caps that were still hiding in default arguments:
        # page-derived URLs in `faceted_nav_audit.py` and linked assets in
        # `cache_compression_checker.py`. Both bound the evidence behind an empty
        # `issues` assertion, so `inherited` rising from 75 to 77 is again the
        # inventory getting more honest, not the checks getting worse.
        self.assertEqual(by_kind, {
            "standard": 11,
            "measured": 11,
            "convention": 47,
            "inherited": 77,
            "presentation": 13,
        })
        self.assertEqual(sum(by_kind[kind] for kind in at.VERDICT_KINDS), 146)
        self.assertEqual(len(named), 159)
        self.assertEqual(len(uncounted), 13)
        # 169 -> 170: `external_link_quality.py`'s link cap was a default argument
        # value, which is a place no instrument here can see. Promoting it to a
        # module constant is what made it countable at all.
        # 170 -> 172: the two caps above were also invisible to the module-level
        # constant inventory until they were given names.
        self.assertEqual(sum(len(at.numeric_constants(path))
                             for path in at._script_paths()), 172)

    def test_a_basis_the_scan_cannot_see_is_counted_whatever_the_constant_is(self):
        at = self._tool()
        source = """\
from datetime import timedelta
# basis: convention — a chosen round number, for this test only
WINDOW_DAYS = 3
CUTOFF = today + timedelta(days=WINDOW_DAYS)
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "thresholds.py")
            with open(path, "w", encoding="utf-8") as f:
                f.write(source)
            named, _ = at.scan([path])
        rows = [row for row in named if row["name"] == "WINDOW_DAYS"]
        self.assertEqual(len(rows), 1, rows)
        self.assertEqual(rows[0]["kind"], "convention")

    def test_a_constant_with_no_basis_and_no_comparison_is_listed_not_counted(self):
        at = self._tool()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "thresholds.py")
            with open(path, "w", encoding="utf-8") as f:
                f.write("SOMETHING = 7\n")
            named, _ = at.scan([path])
            uncounted = at.scan_uncounted([path])
            stdout, stderr = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                status = at.main(["--check"], paths=[path])
        self.assertNotIn("SOMETHING", {row["name"] for row in named})
        self.assertIn("SOMETHING", {row["name"] for row in uncounted})
        self.assertEqual(status, 0, stdout.getvalue() + stderr.getvalue())

    def test_a_presentation_basis_the_scan_cannot_see_is_counted_apart(self):
        at = self._tool()
        source = """\
# basis: presentation — a short display window, for this test only
DISPLAY_ROWS = 7
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "thresholds.py")
            with open(path, "w", encoding="utf-8") as f:
                f.write(source)
            named, _ = at.scan([path])
        self.assertEqual([(row["name"], row["kind"]) for row in named],
                         [("DISPLAY_ROWS", "presentation")])
        verdict = [row for row in named if row["kind"] in at.VERDICT_KINDS]
        self.assertEqual(verdict, [])

    def test_a_basis_cut_off_by_a_blank_line_is_listed_not_counted(self):
        at = self._tool()
        source = """\
# basis: convention — deliberately separated from the constant

WINDOW = 7
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "thresholds.py")
            with open(path, "w", encoding="utf-8") as f:
                f.write(source)
            named, _ = at.scan([path])
            uncounted = at.scan_uncounted([path])
        self.assertNotIn("WINDOW", {row["name"] for row in named})
        self.assertIn("WINDOW", {row["name"] for row in uncounted})

    def test_the_uncounted_listing_is_exactly_the_uncounted(self):
        at = self._tool()
        named, _ = at.scan()
        uncounted = at.scan_uncounted()
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            status = at.main(["--uncounted"])
        output = stdout.getvalue()
        self.assertEqual(status, 0, output)
        # The witness was `DEFAULT_MAX_PAGES` until 0.88.0, and it left this listing
        # rather than the listing changing shape: the cap that bounds what every
        # site-wide item can see was given a basis, and so was `DEFAULT_DEPTH`, which
        # caps the same verdicts less visibly. `INVENTORY_VERSION` takes the seat
        # and should keep it: a schema version is not a threshold and will never
        # carry a basis line, so the witness stops moving when a cap is named.
        self.assertRegex(output, r"(?m)^  .*site_crawl\.py:\d+  INVENTORY_VERSION$")
        self.assertIn("\n13 module-level numeric constant(s) not in the inventory\n",
                      output)
        listed = {line.strip() for line in output.splitlines() if line.startswith("  ")}
        for row in named:
            self.assertNotIn(f"{row['file']}:{row['line']}  {row['name']}", listed)
        self.assertEqual(len(listed), len(uncounted))

    def test_the_summary_says_what_it_did_not_count(self):
        at = self._tool()
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            status = at.main([])
        output = stdout.getvalue()
        self.assertEqual(status, 0, output)
        # 20 -> 13. Seven constants got a `# basis:` line in 0.88.0, every one of them
        # a cap standing between a script and the evidence that could have failed an
        # item asserting `none of these`. They did not become thresholds — they were
        # thresholds already, and invisible to this instrument for want of the line
        # that makes a number visible to it.
        self.assertIn("13 module-level numeric constant(s) are not in this inventory",
                      output)
        self.assertIn("1 basis line(s) name something that is not a module-level "
                      "numeric constant", output)

    def test_a_basis_on_something_that_is_not_a_number_is_reported(self):
        at = self._tool()
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            status = at.main(["--check"])
        self.assertEqual(status, 0, stdout.getvalue())
        self.assertIn("robots_path_tester.py:31", stdout.getvalue())

    def test_the_flags_compose(self):
        at = self._tool()
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = at.main(["--uncounted", "--check"])
        self.assertEqual(status, 0, stdout.getvalue() + stderr.getvalue())
        # Same substitution as the listing test above, for the same reason: the
        # witness has to be a constant that is genuinely uncounted, and 0.88.0 named
        # both crawl caps. `INVENTORY_VERSION` is not a threshold at all, which is
        # what makes it a witness that stays.
        self.assertIn("INVENTORY_VERSION", stdout.getvalue())

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "thresholds.py")
            with open(path, "w", encoding="utf-8") as f:
                f.write("# basis: conventions — invalid kind\nSOMETHING = 7\n")
            stdout, stderr = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                status = at.main(["--uncounted", "--check"], paths=[path])
        self.assertNotEqual(status, 0)
        self.assertIn("outside the documented five-kind vocabulary", stdout.getvalue())

    def test_report_path_is_relative_or_falls_back_to_absolute(self):
        at = self._tool()
        inside = os.path.join(at.SKILL, "scripts", "checklist_runner.py")
        self.assertEqual(at._report_path(inside),
                         os.path.relpath(inside, at.SKILL))

        outside = os.path.join(tempfile.gettempdir(), "thresholds.py")
        with mock.patch.object(at.os.path, "relpath", side_effect=ValueError):
            self.assertEqual(at._report_path(outside), os.path.abspath(outside))

    def test_no_named_threshold_is_bare(self):
        at = self._tool()
        named, _ = at.scan()
        self.assertGreater(len(named), 30,
                           "the scan found almost nothing, so this would pass on "
                           "an empty inventory")
        bare = [f"{t['file']}:{t['line']} {t['name']}" for t in named if not t["kind"]]
        self.assertEqual(bare, [], "add a `# basis: kind — why` line above each")

    def test_the_kinds_are_the_documented_five(self):
        at = self._tool()
        named, _ = at.scan()
        self.assertEqual({t["kind"] for t in named} - set(at.KINDS), set())

    def test_a_basis_says_something(self):
        """A kind with no reason after it is a label, not a justification."""
        at = self._tool()
        named, _ = at.scan()
        thin = [t["name"] for t in named if len(t["why"]) < 25]
        self.assertEqual(thin, [], f"these state a kind and no reason: {thin}")

    def test_a_measured_threshold_must_name_what_it_was_measured_against(self):
        bad = """\
# basis: measured — we measured it
LIMIT = 3
def over(value):
    return value > LIMIT
"""
        status, stdout, stderr = self._run_check(bad)
        self.assertNotEqual(status, 0)
        self.assertIn("Measured, but without a reproducible measurement", stdout)
        self.assertIn("corpus=<what was measured>", stderr)

        good = """\
# basis: measured — method=sorted observations; corpus=50 audit runs; date=2026-08-09. Recheck yearly.
LIMIT = 3
def over(value):
    return value > LIMIT
"""
        status, stdout, stderr = self._run_check(good)
        self.assertEqual(status, 0, stdout + stderr)

    def test_a_measured_threshold_needs_a_real_date(self):
        for value in ("last tuesday", "2026-13-01"):
            with self.subTest(date=value):
                source = f"""\
# basis: measured — corpus=50 audit runs; date={value}; method=sorted observations
LIMIT = 3
def over(result):
    return result > LIMIT
"""
                status, stdout, stderr = self._run_check(source)
                self.assertNotEqual(status, 0)
                self.assertIn("date", stdout)
                self.assertIn("date=<YYYY-MM-DD>", stderr)

    def test_a_basis_kind_outside_the_vocabulary_is_an_error_not_a_silent_drop(self):
        for declaration, detail in (("external standard — published elsewhere", "external"),
                                    ("", "no basis kind follows the colon")):
            with self.subTest(declaration=declaration or "bare"):
                status, stdout, stderr = self._run_check(f"# basis: {declaration}\n")
                self.assertNotEqual(status, 0)
                self.assertIn("outside the documented five-kind vocabulary", stdout)
                self.assertIn(detail, stdout)
                self.assertIn("standard|measured|convention|inherited|presentation", stderr)

    def test_the_unnamed_count_has_not_grown(self):
        at = self._tool()
        _, unnamed = at.scan()
        self.assertLessEqual(
            len(unnamed), self.UNNAMED_CEILING,
            f"{len(unnamed)} comparisons against a bare number, up from "
            f"{self.UNNAMED_CEILING}. A threshold with no name cannot carry a basis, "
            f"so name it — or raise this ceiling deliberately and say why")

    def test_a_sort_order_is_presentation_not_a_verdict_number(self):
        at = self._tool()
        named, _ = at.scan()
        severity_order = [t for t in named if t["name"] == "SEVERITY_ORDER"]
        self.assertEqual(len(severity_order), 1, severity_order)
        self.assertEqual(severity_order[0]["kind"], "presentation")
        verdict_inventory = [t["name"] for t in named
                             if t["kind"] in at.VERDICT_KINDS]
        self.assertNotIn("SEVERITY_ORDER", verdict_inventory)

    def test_the_two_copies_of_googles_cwv_bands_agree(self):
        """`cwv_metrics` reads a local trace and `pagespeed` reads CrUX, and each
        holds its own copy of the published bands. Two copies of one standard drift,
        and the drift would show up as a lab run and a field run disagreeing about a
        page that had not changed."""
        sys.path.insert(0, SCRIPTS)
        import cwv_metrics
        import pagespeed
        lab = cwv_metrics.THRESHOLDS
        field = pagespeed.CWV_THRESHOLDS
        # Only the two metrics both tables really hold. `tbt_ms` and `INP` are
        # deliberately not paired: TBT is a lab stand-in for INP measured from a page
        # load, and asserting they match would be asserting that two different
        # measurements are the same one.
        shared = {"LCP": "lcp_ms", "CLS": "cls"}
        compared = 0
        for field_key, lab_key in shared.items():
            self.assertIn(field_key, field, "pagespeed renamed a CWV key")
            self.assertIn(lab_key, lab, "cwv_metrics renamed a CWV key")
            for band in ("good", "poor"):
                a, b = lab[lab_key][band], field[field_key][band]
                self.assertEqual(a, b, f"{field_key} {band}: lab {a} vs field {b}")
                compared += 1
        # The first version of this test used lowercase keys, matched nothing, and
        # passed — which is the failure it exists to catch, one level up.
        self.assertEqual(compared, 4)

    def test_a_measured_css_threshold_matches_its_committed_measurement(self):
        report_path = os.path.join(TOOLS, "calibration", "css-minification.json")
        with open(report_path, encoding="utf-8") as f:
            report = json.load(f)
        sys.path.insert(0, SCRIPTS)
        import css_minify_check

        self.assertEqual(len(report["constants"]), 6,
                         "the report no longer covers the full CSS threshold family")
        for name, evidence in report["constants"].items():
            self.assertTrue(hasattr(css_minify_check, name), name)
            self.assertEqual(getattr(css_minify_check, name), evidence["value"],
                             f"{name} drifted away from its committed measurement")

    def test_a_measured_css_constant_is_not_dominated_by_one_package(self):
        report_path = os.path.join(TOOLS, "calibration", "css-minification.json")
        with open(report_path, encoding="utf-8") as f:
            report = json.load(f)
        sys.path.insert(0, SCRIPTS)
        import css_minify_check

        by_package = report["pair_statistics"]["by_package"]
        self.assertGreater(len(by_package), 1,
                           "pair evidence collapsed to one build pipeline")
        evidence = report["constants"]["MINIFICATION_SAVINGS_FRACTION"]
        package_level = evidence["estimators"]["package_level"]
        weights = [row["weight_fraction"]
                   for row in package_level["by_package"].values()]
        self.assertAlmostEqual(sum(weights), 1.0, places=5)
        self.assertLessEqual(max(weights), 0.5,
                             "one package supplies a majority of estimator weight")

        raw_by_package = {}
        for pair in report["pairs"]:
            raw_by_package.setdefault(pair["package"], []).append(
                pair["saving_fraction"])
        independently_computed = statistics.median(
            statistics.median(values) for values in raw_by_package.values())
        self.assertAlmostEqual(package_level["value"], independently_computed,
                               places=6)
        self.assertEqual(css_minify_check.MINIFICATION_SAVINGS_FRACTION,
                         round(independently_computed, 3))
        pooled = statistics.median(
            pair["saving_fraction"] for pair in report["pairs"])
        self.assertNotEqual(css_minify_check.MINIFICATION_SAVINGS_FRACTION,
                            round(pooled, 3),
                            "the constant reverted to the package-dominated pool")

    def test_the_calibration_report_names_a_real_corpus(self):
        report_path = os.path.join(TOOLS, "calibration", "css-minification.json")
        with open(report_path, encoding="utf-8") as f:
            report = json.load(f)
        self.assertGreater(len(report["manifest"]), 0)
        datetime.datetime.strptime(report["generated"], "%Y-%m-%d")
        for entry in report["manifest"]:
            self.assertTrue(entry.get("version"), entry)
            self.assertRegex(entry.get("sha256", ""), r"^[0-9a-f]{64}$", entry)
            self.assertGreater(entry.get("css_file_count", 0), 0, entry)

    def test_the_font_threshold_matches_its_committed_measurement(self):
        report_path = os.path.join(TOOLS, "calibration", "font-weight.json")
        with open(report_path, encoding="utf-8") as f:
            report = json.load(f)
        sys.path.insert(0, SCRIPTS)
        import font_audit

        self.assertEqual(font_audit.LARGE_FONT_BYTES,
                         report["constant"]["value"],
                         "LARGE_FONT_BYTES drifted away from its measurement")

    def test_the_font_calibration_report_names_a_real_corpus(self):
        report_path = os.path.join(TOOLS, "calibration", "font-weight.json")
        with open(report_path, encoding="utf-8") as f:
            report = json.load(f)
        self.assertGreater(len(report["manifest"]), 0)
        datetime.datetime.strptime(report["generated"], "%Y-%m-%d")
        self.assertEqual({entry.get("arm") for entry in report["manifest"]},
                         {"A", "B"},
                         "both subsetted/control and full-face arms are required")
        for entry in report["manifest"]:
            self.assertTrue(entry.get("version"), entry)
            self.assertRegex(entry.get("sha256", ""), r"^[0-9a-f]{64}$", entry)

    def test_the_serp_length_thresholds_match_their_committed_measurement(self):
        report_path = os.path.join(TOOLS, "calibration", "serp-length.json")
        with open(report_path, encoding="utf-8") as f:
            report = json.load(f)
        sys.path.insert(0, SCRIPTS)
        import article_seo

        measured = {name: row for name, row in report["constants"].items()
                    if row["basis"] == "measured"}
        self.assertEqual(set(measured), {"TITLE_MAX_CHARS", "META_MAX_CHARS"})
        for name, evidence in measured.items():
            self.assertEqual(getattr(article_seo, name), evidence["value"],
                             f"{name} drifted away from its committed measurement")
            self.assertEqual(evidence["value"], evidence["recommended_value"],
                             f"{name} does not implement the measured capacity")

    def test_the_serp_constants_come_from_one_selection_rule(self):
        report_path = os.path.join(TOOLS, "calibration", "serp-length.json")
        with open(report_path, encoding="utf-8") as f:
            report = json.load(f)
        sys.path.insert(0, SCRIPTS)
        import article_seo

        self.assertEqual(report.get("selection_rule"),
                         "ordinary composition in Arial")
        fonts = {font["name"]: font for font in report["fonts"]}
        measured = {name for name, row in report["constants"].items()
                    if row["basis"] == "measured"}
        self.assertEqual(measured, {"TITLE_MAX_CHARS", "META_MAX_CHARS"})
        for name in measured:
            decision = report["calibration_decisions"][name]
            self.assertEqual(decision["font"], "Arial", name)
            self.assertEqual(decision["mix"], "ordinary_title_case", name)
            selected_capacity = fonts[decision["font"]]["measurements"][
                decision["surface"]]["composition_mixes"][decision["mix"]][
                    "characters_budget_holds"]
            alternatives = decision["alternatives"]
            expected_mixes = {
                mix: row["characters_budget_holds"]
                for mix, row in fonts["Arial"]["measurements"][
                    decision["surface"]]["composition_mixes"].items()
            }
            expected_fonts = {
                font_name: font["measurements"][decision["surface"]][
                    "composition_mixes"]["ordinary_title_case"][
                        "characters_budget_holds"]
                for font_name, font in fonts.items()
            }
            self.assertEqual(alternatives["capacities_by_mix_in_arial"],
                             expected_mixes, name)
            self.assertEqual(
                alternatives["capacities_for_ordinary_composition_by_font"],
                expected_fonts, name)
            self.assertEqual(decision["capacity"], selected_capacity, name)
            self.assertEqual(report["constants"][name]["value"],
                             selected_capacity, name)
            self.assertEqual(getattr(article_seo, name), selected_capacity, name)

    def test_the_serp_report_names_its_assumed_inputs(self):
        report_path = os.path.join(TOOLS, "calibration", "serp-length.json")
        with open(report_path, encoding="utf-8") as f:
            report = json.load(f)

        inputs = report["inputs"]
        self.assertEqual(inputs["pixel_budgets"]["status"],
                         "assumed_input_not_google_published")
        self.assertEqual(inputs["pixel_budgets"]["surfaces"], {
            "desktop_title": 600,
            "desktop_description": 920,
            "mobile_description": 680,
        })
        self.assertEqual(inputs["english_letter_frequency"]["status"],
                         "declared_input_not_finding")
        self.assertEqual(len(inputs["english_letter_frequency"]["percentages"]), 26)
        self.assertGreater(len(report["fonts"]), 1,
                           "one font cannot show font-choice sensitivity")
        self.assertGreater(len(inputs["composition_mixes"]), 1,
                           "one composition cannot show text sensitivity")
        for font in report["fonts"]:
            self.assertRegex(font["sha256"], r"^[0-9a-f]{64}$", font)

    def test_the_gsc_floors_match_their_committed_measurement(self):
        report_path = os.path.join(
            TOOLS, "calibration", "gsc-sample-floors.json")
        with open(report_path, encoding="utf-8") as f:
            report = json.load(f)
        sys.path.insert(0, SCRIPTS)
        import gsc_checker

        self.assertEqual(
            {pair["floor_constant"] for pair in report["pairs"]},
            {"LOW_CTR_MIN_IMPRESSIONS", "HIGH_IMPRESSIONS"},
            "the report no longer covers both calibrated GSC CTR floors")
        for pair in report["pairs"]:
            name = pair["floor_constant"]
            self.assertEqual(getattr(gsc_checker, name),
                             pair["floor_impressions"],
                             f"{name} drifted away from its measurement")

    def test_a_gsc_floor_delivers_the_precision_it_claims(self):
        report_path = os.path.join(
            TOOLS, "calibration", "gsc-sample-floors.json")
        with open(report_path, encoding="utf-8") as f:
            report = json.load(f)

        rule = report["precision_rule"]
        self.assertEqual(
            rule["name"],
            "ci_half_width_not_greater_than_tested_ctr_threshold")
        for pair in report["pairs"]:
            p = pair["threshold_fraction"]
            n = pair["floor_impressions"]
            half_width = rule["z_score"] * math.sqrt(p * (1 - p) / n)
            self.assertAlmostEqual(
                half_width, pair["delivered_ci_half_width_fraction"], places=6,
                msg=f"{pair['floor_constant']} reports the wrong half-width")
            self.assertLessEqual(
                half_width, p,
                f"{pair['floor_constant']} does not satisfy {rule['name']}")
            independently_required = math.ceil(
                (rule["z_score"] / p) ** 2 * p * (1 - p))
            self.assertEqual(independently_required,
                             pair["required_minimum_impressions"])

    def test_the_title_advice_matches_the_title_check(self):
        sys.path.insert(0, SCRIPTS)
        import article_seo

        def title_fix(title):
            content = {"title": title, "meta_description": "m" * 120,
                       "h1": ["Heading"], "images": [], "authors": ["Author"],
                       "publish_date": "2026-08-10"}
            issues = article_seo.detect_seo_issues(
                content, [], {"word_count": article_seo.BLOG_THIN_WORDS})
            return next(issue["fix"] for issue in issues if issue["area"] == "Title")

        minimum = article_seo.TITLE_MIN_CHARS
        maximum = article_seo.TITLE_MAX_CHARS
        self.assertEqual(title_fix(""),
                         f"Add a descriptive title tag ({minimum}-{maximum} characters).")
        self.assertEqual(title_fix("x" * (minimum - 1)),
                         f"Expand title to at least {minimum} characters with the "
                         "primary keyword near the start.")
        self.assertEqual(title_fix("x" * (maximum + 1)),
                         f"Keep title at or below {maximum} characters.")

    def test_the_measured_basis_lines_point_at_the_report(self):
        path = os.path.join(SCRIPTS, "css_minify_check.py")
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
        measured = [(lineno, line) for lineno, line in enumerate(lines, 1)
                    if "basis: measured" in line]
        self.assertEqual(len(measured), 6, measured)
        self.assertEqual(self._tool().basis_issues(path), [],
                         "use audit_thresholds.py's measured-basis validator")
        for lineno, line in measured:
            self.assertIn("corpus=tools/calibration/css-minification.json", line,
                          f"line {lineno} does not name the committed report")


class AnAuditDoesNotCommitItself(unittest.TestCase):
    """Every file a run writes by default must be ignored by git.

    An audit writes its results beside itself, and this checkout is the obvious place
    to run one, so an output nobody listed in `.gitignore` ends up in a commit. Two
    did: `checklist-results-crawl.json`, whose name is *derived* from the `--json`
    path rather than declared, so adding the crawl inventory in 0.9.0 added an output
    no list mentioned; and the by-lens LLM queues, derived the same way from
    `--llm-queue`.

    Read out of the argparse defaults rather than listed here, because a list in a
    test drifts exactly the way `.gitignore` drifted. `git check-ignore` answers the
    question, because reimplementing gitignore matching would be testing this test.

    A run is not the only thing that writes here. `tools/probe_shapes.py` writes two
    files and only one of them was listed, so its crawl inventory got committed twice:
    a fixture-server crawl in 0.9.0 and a client site's in 0.25.0. This test named the
    audit's outputs and no tool's, so the probe's filenames are now read the same way,
    out of the tool's own literals.
    """

    def _defaults(self, script: str) -> dict:
        with open(os.path.join(SCRIPTS, script), encoding="utf-8") as f:
            src = f.read()
        return dict(re.findall(r'add_argument\("--([a-z-]+)"[^)]*?default="([^"]+)"',
                               src))

    def _probe_outputs(self) -> set:
        """Filenames the probe writes, taken from `probe_shapes.py`.

        The probe declares neither through argparse: the skeleton is a literal at the
        `open()` call, the inventory a default argument. A `probe-*.json` literal in
        that file is a file the tool writes, and that is close enough to the real rule
        to catch the next one.
        """
        with open(os.path.join(TOOLS, "probe_shapes.py"), encoding="utf-8") as f:
            src = f.read()
        return set(re.findall(r'"(probe-[a-z0-9-]+\.json)"', src))

    def outputs(self) -> set:
        runner = self._defaults("checklist_runner.py")
        report = self._defaults("checklist_report.py")
        results, queue = runner["json"], report["llm-queue"]
        stem = queue[:-3] if queue.endswith(".md") else queue
        names = {results, report["markdown"], report["html"], queue,
                 # The derived one, spelled the way checklist_runner derives it.
                 os.path.splitext(results)[0] + "-crawl.json"}
        names |= {f"{stem}-{lens}.md"
                  for lens in ("copy", "layout", "locale", "market")}
        names |= self._probe_outputs()
        return names

    def test_every_default_output_is_ignored(self):
        found = self.outputs()
        self.assertIn("checklist-results.json", found,
                      "the defaults were not read; this test would pass on nothing")
        self.assertIn("probe-raw.json", found,
                      "the probe's literals were not read; the half of this test "
                      "that was added because it missed a file would miss it again")
        # `git -C` rather than `cwd=`, and through `harness.spawn` so the binary is
        # resolved to an absolute path: both a `cwd` and a bare executable name put the
        # child on CPython's fork path, where macOS kills it before it execs.
        proc = harness.spawn(["git", "-C", ROOT, "check-ignore", "-v", *sorted(found)],
                             env=os.environ.copy())
        if proc.returncode == 128:
            self.skipTest("not a git checkout")
        ignored = {line.rsplit("\t", 1)[-1] for line in proc.stdout.splitlines()}
        self.assertEqual(sorted(found - ignored), [],
                         "a run writes these into the checkout and git would offer "
                         "to commit them; add them to .gitignore")

    def test_none_of_them_is_already_committed(self):
        """The same check from the other end. A pattern added to `.gitignore` does
        nothing for a file already in the index, and that was the second half of the
        mistake: the ignore list and the index both had to be fixed.

        Compared by basename, because `git ls-files` prints paths and this test used to
        hold filenames — so it could only ever see an output committed at the top of
        the checkout. `skills/seo-checklist/probe-inventory.json` was committed one
        directory down and matched nothing here.
        """
        proc = harness.spawn(["git", "-C", ROOT, "ls-files"], env=os.environ.copy())
        if proc.returncode != 0:
            self.skipTest("not a git checkout")
        tracked = {os.path.basename(p) for p in proc.stdout.split()}
        self.assertEqual(sorted(self.outputs() & tracked), [],
                         "this is a file some run or tool wrote, committed by "
                         "accident; remove it from the index")


class ATestFileRunsEverythingItDefines(unittest.TestCase):
    """`if __name__ == "__main__": unittest.main()` must be the last statement.

    In `test_runner.py` it was not: it sat above `HistoryIsASeries`, so running that
    file directly executed `main()` before the class existed and reported "Ran 237
    tests ... OK" for a file that defines 246. Nine tests about run history — the
    feature 0.19.0 added — were invisible to anyone checking their work that way, and
    `unittest discover` imports the module rather than running it as `__main__`, so CI
    collected all 246 and had nothing to report. A green run that quietly covers 96%
    of what it names is worse than a red one.

    Checked by parsing rather than by running the files: the question is where a
    statement sits in the module body, which is exactly what an AST says.
    """

    def files(self) -> list:
        here = os.path.dirname(os.path.abspath(__file__))
        found = sorted(f for f in os.listdir(here) if f.startswith("test_")
                       and f.endswith(".py"))
        self.assertGreater(len(found), 5, "no test files found; this would pass on "
                                          "nothing")
        return [os.path.join(here, f) for f in found]

    def test_every_test_file_has_a_main_block(self):
        missing = []
        for path in self.files():
            with open(path, encoding="utf-8") as f:
                tree = ast.parse(f.read())
            main_blocks = [node for node in tree.body
                           if isinstance(node, ast.If)
                           and "__name__" in ast.dump(node.test)]
            if not main_blocks:
                tests = sum(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                            and node.name.startswith("test_")
                            for node in ast.walk(tree))
                missing.append(f"{os.path.basename(path)} ({tests} tests)")
        self.assertEqual(missing, [], "direct execution runs zero tests in: "
                                     + ", ".join(missing))

    def test_the_main_block_is_the_last_statement(self):
        late = []
        for path in self.files():
            with open(path, encoding="utf-8") as f:
                body = ast.parse(f.read()).body
            for i, node in enumerate(body):
                if not (isinstance(node, ast.If) and ast.dump(node.test).find(
                        "__name__") != -1):
                    continue
                after = [n for n in body[i + 1:]
                         if isinstance(n, (ast.ClassDef, ast.FunctionDef))]
                if after:
                    late.append(f"{os.path.basename(path)}: "
                                f"{', '.join(n.name for n in after)} defined after "
                                f"line {node.lineno}")
        self.assertEqual(late, [], "these are skipped when the file is run directly; "
                                   "move the __main__ block to the end")


class AnAssertionLanguageWithOneOperatorPerRule(unittest.TestCase):
    """`openspec/specs/registry/` REG-7. A rule is a path, **exactly one** operator, and
    optionally a field and a `missing_is`.

    Two operators are an error rather than a conjunction: `evaluate()` applies the first
    branch that matches and discards the second in silence, so the rule means whichever
    the implementation happens to reach first. Nothing forbade it — one test required at
    least one operator and another forbade naming one the evaluator lacks, and neither
    forbade two. No item does it today, which is why nothing had caught it, and why the
    day it happens the verdict changes with a refactor of branch order.

    The vocabulary is derived from `evaluate()` rather than listed. The test that
    replaced a substring search over the runner's source is the other half of this: `eq`
    appears in that file's prose, so the old check passed on a mention in a comment.
    """

    def rules(self):
        for item in ITEMS:
            check = item.get("check") or {}
            for where in ("assert", "warn", "applies_when"):
                rule = check.get(where)
                if rule:
                    yield item["id"], where, rule

    def test_the_vocabulary_is_found_and_has_the_three_shapes_in_it(self):
        """A floor under every count below. The first draft of the scan knew one of the
        three code shapes and found twelve of nineteen — and an undercount here reads as
        "sixty-five rules name no operator", which is alarming and wrong, rather than as
        a broken scan."""
        vocabulary = operator_vocabulary()
        self.assertGreaterEqual(len(vocabulary), 19)
        for shape, operator in (("bare `if`", "truthy"),
                                ("comparator loop", "gte"),
                                ("length loop", "len_gte"),
                                ("written out singly", "between")):
            with self.subTest(shape=shape):
                self.assertIn(operator, vocabulary)

    def test_every_rule_names_exactly_one_operator(self):
        """The requirement. Zero cannot decide anything; two mean whatever branch order
        says."""
        vocabulary = operator_vocabulary()
        for item_id, where, rule in self.rules():
            with self.subTest(item=item_id, rule=where):
                named = sorted(set(rule) & vocabulary)
                self.assertEqual(
                    len(named), 1,
                    f"{item_id}'s `{where}` names {named or 'no operator'}; a rule is a "
                    f"path and exactly one operator, and the evaluator takes the first "
                    f"branch it reaches")

    def test_a_rule_carries_nothing_the_language_does_not_define(self):
        """The rest of a rule's keys, held as a closed set for the same reason as the
        operators: a key nobody implements is a rule that means less than it looks."""
        allowed = operator_vocabulary() | {"path", "field", "missing_is", "scope"}
        for item_id, where, rule in self.rules():
            with self.subTest(item=item_id, rule=where):
                self.assertEqual(sorted(set(rule) - allowed), [])

    def test_the_operators_no_item_uses_are_the_ones_the_document_names(self):
        """REG-7's last sentence: an operator the language implements and no item uses
        is either specified in that document or removed from the language. Both sides
        are derived — the unused set from the registry and the evaluator, the named set
        from the document's own appendix — so neither can drift past the other.

        The set moved in 0.93.0 without anybody noticing: `count_matching_lte` lost its
        last two users when MB-095 and MB-098 stopped counting matches in prose, and the
        appendix still said four.
        """
        vocabulary = operator_vocabulary()
        used = set()
        for _item_id, _where, rule in self.rules():
            used |= set(rule) & vocabulary
        unused = vocabulary - used

        with open(os.path.join(ROOT, "openspec", "specs", "registry", "spec.md"),
                  encoding="utf-8") as stream:
            document = stream.read()
        start = document.index("#### A.4 — ")
        end = document.index("## Appendix B", start)
        section = document[start:end]
        # Only the bullets. The section also discusses `gt` in prose, to record that an
        # earlier count read it as unused by looking at `assert` blocks alone — and a
        # harvest over the whole section would take that word back in and undo the
        # lesson the paragraph exists to keep.
        named = {word for word in re.findall(r"^- `([a-z_]+)`", section, re.M)}
        self.assertLessEqual(named, vocabulary,
                             "the appendix bullets name something that is not an "
                             "operator this evaluator implements")

        self.assertEqual(sorted(named), sorted(unused),
                         "the appendix and the tree disagree about which operators no "
                         "item uses")


class TheCatalogueDescribesThisTree(unittest.TestCase):
    """`openspec/specs/evidence/` EVD-4. The shapes catalogue's account of itself is
    computed from the tree, not written beside it.

    That opening paragraph is what a rule-writer reads before writing a rule — it is
    where they learn which checkers are exceptions — and every clause of it was wrong.
    It said "all 57 scripts the registry runs" where the registry runs 58; it named
    `site_crawl.py` as the only extra where `detect_profile.py` is documented too; it
    said four scripts break the `issues[].severity` + `message` convention where the
    file itself describes forty-nine departures from it across four kinds; and it said
    `gsc_checker.py` capitalises severity in `issues[]`, where its `issues[]` are
    lowercase and its `opportunities[]` are the capitalised ones.

    `tools/audit_catalogue.py` derives the block and `--check` fails when it is stale.
    This class runs that gate and then asks the questions the gate cannot ask about
    itself.
    """

    @classmethod
    def tool(cls):
        sys.path.insert(0, TOOLS)
        import audit_catalogue
        return audit_catalogue

    def test_the_block_in_the_file_is_the_one_the_tree_produces(self):
        """The gate, run here as well as in CI. It lives in the workflow as a step, and
        a step is invisible to `unittest discover` — which is how four registry paths
        reached a branch without appearing in this file at all, and failed on CI after
        the local suite was green."""
        tool = self.tool()
        with open(tool.CATALOGUE, encoding="utf-8") as stream:
            held = tool.current(stream.read())
        self.assertIsNotNone(held, "the derived block's markers are gone")
        self.assertEqual(held.strip(), tool.block(tool.measure()).strip(),
                         "run tools/audit_catalogue.py")

    def test_every_documented_script_is_classified_exactly_once(self):
        """A partition, not a set of overlapping lists — except `capitalised`, which is
        a fact about values and cuts across the other three. Without this the tool
        could quietly drop a script from its own account and the block would still
        match the file."""
        facts = self.tool().measure()
        classified = (facts["conforming"] + facts["no_issues"] + facts["unseen"]
                      + [script for script, _key in facts["other_key"]])
        self.assertEqual(sorted(classified), facts["documented"])
        self.assertEqual(len(classified), len(set(classified)))
        self.assertLessEqual(set(facts["capitalised"]), set(facts["documented"]))

    def test_it_documents_every_script_the_registry_runs(self):
        """The claim the count is made of. A registry script with no section is a rule
        written against a shape nobody wrote down."""
        facts = self.tool().measure()
        self.assertEqual(facts["undocumented"], [])
        self.assertEqual(sorted(facts["registry_scripts"]),
                         sorted({(item.get("check") or {}).get("script")
                                 for item in ITEMS
                                 if (item.get("check") or {}).get("script")}))

    def test_the_classes_are_not_empty_by_accident(self):
        """Four counts that would all read as "nothing to report" if the parser stopped
        finding `issues[]` entries. This is the floor: the file does contain sections of
        each kind, and a change that makes the tool blind fails here rather than
        publishing a clean paragraph."""
        facts = self.tool().measure()
        for name in ("conforming", "no_issues", "unseen", "other_key", "capitalised"):
            with self.subTest(group=name):
                self.assertTrue(facts[name], f"{name} is empty; the parser is blind")

    def test_a_known_deviant_lands_where_reading_the_script_puts_it(self):
        """Three anchors, each checked against the script rather than against the
        catalogue, so a wrong classification cannot be made true by editing the file the
        tool reads."""
        facts = self.tool().measure()
        by_script = dict(facts["other_key"])
        self.assertEqual(by_script.get("indexnow_checker.py"), "finding")
        self.assertIn("robots_path_tester.py", facts["no_issues"])
        self.assertIn("indexnow_checker.py", facts["capitalised"])
        self.assertNotIn("gsc_checker.py", [])
        # The clause the old paragraph got backwards, pinned in both directions.
        self.assertIn("gsc_checker.py", facts["capitalised"])
        self.assertIn("Critical", self.tool().severity_cases("indexnow_checker.py"))
        self.assertNotIn(
            "message", dict(facts["other_key"]).values(),
            "a script filed as using another key is filed for using `message`")


class EveryToolGateRunsHereToo(unittest.TestCase):
    """The workflow's tool steps, run by the suite.

    Eight gates live in `.github/workflows/ci.yml` as `run:` steps, and `unittest
    discover` runs none of them. On 6 September 2026 a release added four registry
    paths, passed 1370 local tests, and failed on CI because
    `tools/audit_assertions.py` refuses a path no script is documented as emitting —
    a gate built to catch exactly that defect, invisible from the machine that made it.

    This class is not a second implementation of those gates. It runs the same
    commands, so the answer here and the answer there cannot differ, and the cost is a
    few seconds.
    """

    GATES = (
        ("build_checklist.py", ["--check"]),
        ("audit_assertions.py", []),
        ("audit_reachability.py", []),
        ("audit_item_semantics.py", []),
        ("audit_catalogue.py", ["--check"]),
        ("audit_derived_sets.py", ["--check",
                                   os.path.join(ROOT, "tests", "derived-sets.json")]),
        ("i18n_digest.py", ["--check"]),
        ("audit_thresholds.py", ["--check"]),
        # Absolute, because the child gets no `cwd`: a working directory forces
        # CPython onto the fork path, which macOS kills before the exec. The workflow
        # passes the relative path from the repository root and reaches the same file.
        ("spec_debt.py", ["--check", os.path.join(ROOT, "tests", "spec-debt.json")]),
    )

    # Workflow steps this class deliberately does not run, each with the reason it
    # cannot be one. `calibrate_*.py --check` is not here because the workflow spells
    # those with a shell variable and the scan above cannot see them; they are four
    # more gates worth adding the day somebody makes them addressable.
    NOT_HERE = {
        # Asserts the snapshot's age, so it reddens on a calendar rather than on a
        # change — a suite that failed on the passage of time would be ignored.
        "refresh_public_suffix_list.py",
        # Needs a live results file the workflow produces earlier in the same job.
        "audit_score_sensitivity.py",
        # Re-probes every script against a live URL; this suite does not leave
        # loopback.
        "probe_shapes.py",
        # Pushes to a notebook, which is an outward-facing action and not a gate.
        "notebook_sync.py",
    }

    def test_the_gates_this_class_runs_are_the_gates_the_workflow_runs(self):
        """Derived from the workflow, so a gate added there and not here fails rather
        than being quietly unrun. The exceptions are enumerated above with a reason
        each, because a list of exemptions nobody has to justify grows until it is the
        whole set."""
        with open(os.path.join(ROOT, ".github", "workflows", "ci.yml"),
                  encoding="utf-8") as stream:
            workflow = stream.read()
        in_ci = set(re.findall(r"tools/([a-z0-9_]+\.py)", workflow))
        mine = {name for name, _args in self.GATES}
        self.assertEqual(
            sorted(in_ci - mine - set(self.NOT_HERE)),
            [], "a workflow gate this class does not run")
        self.assertEqual(sorted(mine - in_ci), [],
                         "this class runs a gate the workflow does not")

    def test_every_gate_passes(self):
        for name, args in self.GATES:
            with self.subTest(gate=name):
                proc = harness.spawn(
                    [sys.executable, os.path.join(TOOLS, name), *args])
                self.assertEqual(
                    proc.returncode, 0,
                    f"tools/{name} {' '.join(args)} exited {proc.returncode}\n"
                    f"{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}")


def operator_vocabulary() -> set[str]:
    """Every operator `evaluate()` implements, read out of its branches.

    Three code shapes carry them and a scan that knows one of the three undercounts:
    a bare `if "truthy" in rule:`, a `for op, cmp in (("gte", ...), ...)` whose body
    tests `op in rule`, and the pair `between` / `len_between` written out singly.
    The first draft of this function found twelve of nineteen and reported that
    sixty-five rules named no operator at all, which is how the gap was noticed.

    Derived rather than listed because `openspec/specs/registry/` REG-7 makes the
    language closed: a list here would be a second copy of the vocabulary, and the
    copy that drifts is always the one nothing runs.
    """
    with open(os.path.join(SCRIPTS, "checklist_runner.py"), encoding="utf-8") as f:
        tree = ast.parse(f.read())
    evaluate = next(node for node in ast.walk(tree)
                    if isinstance(node, ast.FunctionDef) and node.name == "evaluate")

    def names_a_rule_key(test):
        return (isinstance(test, ast.Compare) and len(test.ops) == 1
                and isinstance(test.ops[0], ast.In)
                and isinstance(test.left, ast.Constant)
                and isinstance(test.left.value, str)
                and isinstance(test.comparators[0], ast.Name)
                and test.comparators[0].id == "rule")

    found: set[str] = set()
    for node in ast.walk(evaluate):
        if isinstance(node, ast.If) and names_a_rule_key(node.test):
            found.add(node.test.left.value)
        if isinstance(node, ast.For):
            body = "\n".join(ast.unparse(statement) for statement in node.body)
            if "in rule" not in body:
                continue
            for element in getattr(node.iter, "elts", []):
                first = getattr(element, "elts", [None])[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    found.add(first.value)
    return found


class TheRegistryStatesNothingAboutItselfItCannotProve(unittest.TestCase):
    """`openspec/specs/registry/` REG-12. A field describing the registry's own
    composition, provenance or size is computed from the items — never written into the
    generator as a constant.

    The staleness gate cannot see a lie that lives in the generator. `--check` rebuilds
    the payload and compares it with the file, so a literal is reproduced byte for byte
    and compared with nothing at all. That is how `source` came to read
    "Plerdy SEO Checklist (200) + 15 beyond-Plerdy checks" through release after
    release while 17 items carried a null `plerdy_ref`, with CI green the whole time —
    and while two other files in this tree stated the same fact as 14 and as 17.

    So this class does two things. It recomputes every self-describing field from the
    items, which catches a wrong value; and it walks the generator's payload literal
    and refuses a constant, which catches the *shape* that made the wrong value
    invisible. The second is the requirement: a value that happens to be right today
    and is checked by nothing is the state this document is about.
    """

    SELF_DESCRIBING = ("registry_version", "item_count", "source", "categories")

    @classmethod
    def payload_literal(cls):
        """The `payload = {...}` dict in `build_checklist.py`, as syntax.

        Read rather than executed: the question is what the generator *writes down*,
        and running it would answer the other question — what the value happens to be
        on this checkout.
        """
        with open(os.path.join(TOOLS, "build_checklist.py"), encoding="utf-8") as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            if (isinstance(node, ast.Assign)
                    and any(getattr(t, "id", None) == "payload" for t in node.targets)
                    and isinstance(node.value, ast.Dict)):
                return {k.value: v for k, v in zip(node.value.keys, node.value.values, strict=True)
                        if isinstance(k, ast.Constant)}
        return {}

    def test_the_generator_still_has_a_payload_this_can_read(self):
        """Every assertion below is about keys of that dict. If the dict moves or is
        renamed, they all pass over nothing."""
        payload = self.payload_literal()
        self.assertTrue(payload, "no `payload = {...}` literal in build_checklist.py")
        missing = [k for k in self.SELF_DESCRIBING if k not in payload]
        self.assertEqual(missing, [], "the generator no longer writes these keys")
        self.assertIn("items", payload)

    def test_no_self_describing_field_is_a_constant_in_the_generator(self):
        """The requirement itself, and the reason it is about shape and not value.

        Any constant, of any type. The first draft of this test looked for a string
        containing a digit, which is the shape `source` had, and an independent reading
        of it found the hole in one pass: `"item_count": 217` is an integer constant,
        `isinstance(217, str)` is False, and it walks through — correct on the day it is
        written, reproduced by `--check`, and compared with nothing until the day it
        stops being correct. That is the requirement's own sentence, so the test now
        refuses the category rather than the example.

        `version` is exempt and is checked below: a schema number is a fact about the
        file format rather than about the items, so nothing in the items could
        contradict it.
        """
        payload = self.payload_literal()
        for key in self.SELF_DESCRIBING:
            with self.subTest(field=key):
                value = payload[key]
                self.assertNotIsInstance(
                    value, ast.Constant,
                    f"{key!r} is written as the constant "
                    f"{getattr(value, 'value', None)!r}. Compute it from `items`: a "
                    f"constant is reproduced by --check and compared with nothing")

    def test_the_schema_version_is_the_one_field_allowed_to_be_a_constant(self):
        """Named so the exemption is a decision rather than an omission. `version`
        describes the file's shape, which the items cannot be asked about."""
        value = self.payload_literal()["version"]
        self.assertIsInstance(value, ast.Constant)
        self.assertEqual(value.value, DATA["version"])

    def test_the_size_it_states_is_the_size_it_has(self):
        self.assertEqual(DATA["item_count"], len(ITEMS))

    def test_the_composition_it_states_is_the_composition_it_has(self):
        """`source` is prose with two numbers in it, and both are claims about the
        items. Read out of the sentence rather than compared to a rebuilt sentence, so
        a reworded `source` still has to be true."""
        stated = [int(n) for n in re.findall(r"\d+", DATA["source"])]
        borrowed = sum(1 for item in ITEMS if item.get("plerdy_ref") is not None)
        added = sum(1 for item in ITEMS if item.get("plerdy_ref") is None)
        self.assertEqual(
            stated, [borrowed, added],
            f"`source` reads {DATA['source']!r}; the items say {borrowed} carry a "
            f"`plerdy_ref` and {added} do not")
        self.assertEqual(borrowed + added, len(ITEMS))

    def test_the_categories_it_declares_are_the_categories_it_uses(self):
        """A declared category with no items is a claim about scope that no item
        supports, and an item in an undeclared category has no label to be rendered
        under."""
        declared = [c["key"] for c in DATA["categories"]]
        self.assertEqual(len(declared), len(set(declared)), "a category is declared twice")
        self.assertEqual(sorted(declared), sorted({item["category"] for item in ITEMS}))
        for entry in DATA["categories"]:
            with self.subTest(category=entry["key"]):
                here = [item for item in ITEMS if item["category"] == entry["key"]]
                borrowed = {item["id"].split("-")[0] for item in here
                            if item["plerdy_ref"] is not None}
                self.assertLessEqual(
                    borrowed, {entry["prefix"]},
                    "a borrowed item carries a prefix its category does not declare; "
                    "its id is generated from that prefix, so this cannot happen by "
                    "accident")
                # `geo_ai` has no borrowed items at all, so the check above passes
                # over an empty set there. This is the half that keeps a declared
                # prefix from naming nothing.
                self.assertIn(entry["prefix"],
                              {item["id"].split("-")[0] for item in here},
                              "no item in this category carries the prefix it "
                              "declares")

    def test_the_only_ids_outside_their_declared_prefix_are_the_added_ones(self):
        """`prefix` is true of the borrowed block and not of the whole category.

        Ids in the Plerdy range are generated as `{prefix}-{ref:03d}`, so they cannot
        drift. The items added here choose their own id, and four of them chose a
        prefix their category does not declare: `TECH-001` through `TECH-003` sit in
        `technical`, which declares `TE`, and `CONT-001` sits in `content`, which
        declares `CN`.

        Not renamed. An id is the contract — archived runs, the census, the defect
        ledger and the playbooks all name these — and a rename to tidy a label would
        cost more than the label is worth. Enumerated instead, so a fifth cannot
        appear unnoticed and so the reader of `prefix` knows what it does not cover.
        """
        declared = {c["key"]: c["prefix"] for c in DATA["categories"]}
        strays = sorted(item["id"] for item in ITEMS
                        if item["id"].split("-")[0] != declared[item["category"]])
        self.assertEqual(strays, ["CONT-001", "TECH-001", "TECH-002", "TECH-003"])
        for item_id in strays:
            with self.subTest(item=item_id):
                item = next(i for i in ITEMS if i["id"] == item_id)
                self.assertIsNone(item["plerdy_ref"],
                                  "a borrowed item cannot have a stray prefix: its id "
                                  "is generated from the declared one")

    def test_the_version_stamp_is_the_hash_of_the_items_it_ships_with(self):
        """`registry_version` is what a stored result names to say which contract it
        was measured against. Recomputed here from the items on disk, so a hand-edited
        `checklist.json` — the one edit `--check` would catch only if somebody ran it —
        cannot keep a stamp that belongs to a different item set."""
        import hashlib
        expected = hashlib.sha256(
            json.dumps(ITEMS, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()[:12]
        self.assertEqual(DATA["registry_version"], expected)


class AVerdictComesFromAFieldAndNeverFromASentence(unittest.TestCase):
    """`openspec/specs/verdicts/` VRD-8. A status is read from a named field of a
    checker's structured result, never from words in a message written for a person.

    Wording is the first thing that drifts, and the pattern operators fail in the
    direction that hides it: `none_matching` **passes** when nothing matches, so a
    pattern aimed at a phrase a checker no longer emits passes every site in silence.
    Fifteen assertions in this registry were in that state when `value_map` was added;
    four survived to 0.93.0, and one of those four was narrower than anyone reading it
    believed — GO-138 matched `404` against "Sitemap URL returns HTTP {status}", so a
    sitemap of URLs returning 500 passed the item outright.

    The operator set is read out of the evaluator rather than listed here. A new
    pattern operator added to `checklist_runner.py` is in scope for this test the day
    it is added, which is the difference between a rule and a note about a rule.
    """

    PROSE = ("issues", "message")

    @classmethod
    def pattern_operators(cls):
        """Every assert operator whose branch in `evaluate()` compiles a regex.

        Derived by walking the function's `if "<op>" in rule:` branches and asking
        which of them reach `re.compile`. Listing them here instead would make this
        test a description of the evaluator as it stood the day it was written.
        """
        with open(os.path.join(SCRIPTS, "checklist_runner.py"), encoding="utf-8") as f:
            tree = ast.parse(f.read())
        found = set()
        for node in ast.walk(tree):
            if not (isinstance(node, ast.FunctionDef) and node.name == "evaluate"):
                continue
            for branch in ast.walk(node):
                if not isinstance(branch, ast.If):
                    continue
                test = branch.test
                if not (isinstance(test, ast.Compare)
                        and isinstance(test.ops[0], ast.In)
                        and isinstance(test.left, ast.Constant)
                        and isinstance(test.left.value, str)):
                    continue
                body = "\n".join(ast.unparse(stmt) for stmt in branch.body)
                if "re.compile" in body:
                    found.add(test.left.value)
        return found

    def test_the_evaluator_still_has_operators_that_match_patterns(self):
        """Without this the sweep below passes on an empty set, which is what it
        would do the day somebody renames `none_matching` and this module keeps
        reporting that no rule matches prose."""
        operators = self.pattern_operators()
        self.assertTrue(operators, "no pattern operator found in evaluate(); either "
                                   "they are gone — delete this class — or the scan "
                                   "stopped seeing them")
        self.assertIn("none_matching", operators)
        self.assertIn("count_matching_lte", operators)

    def test_no_rule_decides_a_verdict_by_matching_a_message(self):
        """The requirement. A pattern may be used; it may not be aimed at prose.

        Prose here is the `issues` list — whose elements are serialised whole when no
        `field` narrows them, message included — and any `message` field by name.
        """
        operators = self.pattern_operators()
        offenders = []
        for item in ITEMS:
            rule = (item.get("check") or {}).get("assert") or {}
            for block in (rule, rule.get("warn") or {}, rule.get("applies_when") or {}):
                if not any(op in block for op in operators):
                    continue
                segments = str(block.get("path", "")).split(".")
                target = [block.get("field") or ""] + segments
                if any(name in self.PROSE for name in target):
                    offenders.append(f"{item['id']}: {json.dumps(block)}")
        self.assertEqual(
            offenders, [],
            "these rules decide a verdict by matching a pattern against text written "
            "for a person; give the checker a counted field or a `value_map` over its "
            "own vocabulary instead — " + "; ".join(offenders))

    def test_a_pattern_over_a_machine_token_is_still_allowed(self):
        """The rule forbids prose, not regular expressions, and a test that cannot
        tell them apart would be satisfied by deleting every pattern in the tree.

        CI-004 matches `noindex` against `meta_robots`, which is a value the page
        emits for a machine in a vocabulary the machine defines. That is a field, and
        it stays legal."""
        by_id = {item["id"]: item for item in ITEMS}
        rule = by_id["CI-004"]["check"]["assert"]
        self.assertEqual(rule["path"], "meta_robots")
        self.assertIn("none_matching", rule)
        self.assertIn("none_matching", self.pattern_operators())

    def test_the_four_that_were_repaired_read_counts_now(self):
        """Named, because a sweep that has never had anything to find cannot say
        whether it would. These are the four the specification's appendix listed, and
        each is pinned at the field that replaced its pattern — so a revert is a
        failure here rather than a silent return."""
        by_id = {item["id"]: item for item in ITEMS}
        for item_id, path in (("MB-095", "large_image_count"),
                              ("MB-098", "srcset_without_sizes_count"),
                              ("GO-138", "invalid_url_count"),
                              ("GO-143", "incomplete_nodes_by_type.WebSite")):
            with self.subTest(item=item_id):
                rule = by_id[item_id]["check"]["assert"]
                self.assertEqual(rule["path"], path)
                self.assertFalse([op for op in self.pattern_operators() if op in rule])


class VersionAndChangelog(unittest.TestCase):
    """A changelog nobody is forced to update is a changelog that lies. The failure
    mode is always the same one: the version moves and the entry does not."""

    def setUp(self):
        with open(os.path.join(ROOT, ".claude-plugin", "plugin.json"),
                  encoding="utf-8") as f:
            self.manifest = json.load(f)
        with open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8") as f:
            self.changelog = f.read()

    def test_the_manifest_version_has_a_changelog_entry(self):
        version = self.manifest["version"]
        self.assertRegex(version, r"^\d+\.\d+\.\d+$")
        headings = re.findall(r"^## (\d+\.\d+\.\d+)", self.changelog, re.M)
        self.assertTrue(headings, "CHANGELOG.md has no version headings")
        self.assertEqual(headings[0], version,
                         f"plugin.json says {version}, newest CHANGELOG entry is "
                         f"{headings[0]}")

    def test_the_registry_version_in_the_newest_entry_is_the_shipped_one(self):
        """The entry states which contract it shipped. If the registry is
        regenerated without a changelog line, that claim silently goes stale."""
        newest = self.changelog.split("\n## ")[1]
        self.assertIn(DATA["registry_version"], newest,
                      f"registry is {DATA['registry_version']}; the newest "
                      f"CHANGELOG entry does not mention it")

    def test_pyproject_states_the_same_version_as_the_manifest(self):
        """Two files naming a version is one more chance for them to disagree, and
        the manifest is the one a plugin host reads."""
        self.assertEqual(pyproject_value(r'^version = "([^"]+)"'),
                         self.manifest["version"])

    def test_the_readme_names_the_shipped_version(self):
        """It said 0.5.0 while 0.7.0 shipped — two releases behind, in the first
        paragraph a reader sees, because nothing checked. The version in the manifest
        is a fact about the code; the one in the README is a promise to the reader,
        and only one of them was being kept."""
        with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as f:
            stated = re.search(r"^Version (\d+\.\d+\.\d+)", f.read(), re.M)
        self.assertTrue(stated, "README.md no longer states a version")
        self.assertEqual(stated.group(1), self.manifest["version"])


def pyproject_value(pattern: str) -> str:
    """One value out of pyproject.toml, by regex.

    Not `tomllib`: that arrived in 3.11 and the floor this very file asserts is
    3.10, so parsing the file properly would make the test unrunnable on the
    version it exists to defend.
    """
    with open(os.path.join(ROOT, "pyproject.toml"), encoding="utf-8") as f:
        found = re.search(pattern, f.read(), re.M)
    assert found, f"pyproject.toml has no {pattern}"
    return found.group(1)


class TheDeclaredPythonFloorIsExercised(unittest.TestCase):
    """A `requires-python` nothing runs is a guess with a colon in it.

    The floor is real and the failure it prevents is ugly: `duplicate_content.py`,
    `link_profile.py` and `pagespeed.py` annotate with PEP 604 unions without
    `from __future__ import annotations`, so on 3.9 the annotation is evaluated at
    import and raises `TypeError: unsupported operand type(s) for |`. That happens
    before a single check runs, and the message says nothing about SEO or about a
    Python version being too old.
    """

    def matrix_versions(self):
        with open(os.path.join(ROOT, ".github", "workflows", "ci.yml"),
                  encoding="utf-8") as f:
            line = re.search(r"python-version: \[([^\]]+)\]", f.read())
        self.assertTrue(line, "the CI matrix no longer lists python versions")
        return [v.strip().strip('"') for v in line.group(1).split(",")]

    def test_ci_runs_the_lowest_version_the_project_claims_to_support(self):
        floor = pyproject_value(r'requires-python = ">=([\d.]+)"')
        versions = sorted(self.matrix_versions(),
                          key=lambda v: tuple(int(p) for p in v.split(".")))
        self.assertEqual(versions[0], floor,
                         f"pyproject.toml claims >={floor} and CI's lowest is "
                         f"{versions[0]}; one of the two is wrong")

    def test_ruff_targets_the_same_floor(self):
        floor = pyproject_value(r'requires-python = ">=([\d.]+)"')
        target = pyproject_value(r'target-version = "py(\d+)"')
        self.assertEqual(target, floor.replace(".", ""),
                         "ruff would suggest rewrites for a version this project "
                         "does not require, or miss ones it does")

    def test_the_floor_is_not_lower_than_the_syntax_in_the_tree(self):
        """Measured from the source rather than trusted, because the way this claim
        breaks is somebody using a newer feature in a script nobody re-reads."""
        floor = tuple(int(p) for p in
                      pyproject_value(r'requires-python = ">=([\d.]+)"').split("."))
        offenders = []
        for folder in (SCRIPTS, os.path.join(SKILL, "tools"),
                       os.path.dirname(os.path.abspath(__file__))):
            for name in sorted(os.listdir(folder)):
                if not name.endswith(".py"):
                    continue
                path = os.path.join(folder, name)
                with open(path, encoding="utf-8") as f:
                    source = f.read()
                tree = ast.parse(source, path)
                future = any(isinstance(n, ast.ImportFrom) and n.module == "__future__"
                             and any(a.name == "annotations" for a in n.names)
                             for n in tree.body)
                for node in ast.walk(tree):
                    # 3.10: `X | Y` evaluated at runtime, which an annotation is
                    # unless the __future__ import postpones it.
                    annotation = None
                    if isinstance(node, (ast.AnnAssign, ast.arg)):
                        annotation = getattr(node, "annotation", None)
                    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        annotation = node.returns
                    if annotation is not None and not future:
                        for sub in ast.walk(annotation):
                            if isinstance(sub, ast.BinOp) and isinstance(sub.op, ast.BitOr):
                                if floor < (3, 10):
                                    offenders.append(f"{name}:{node.lineno} PEP 604")
                                break
                    # 3.10: zip(strict=), and the match statement.
                    if isinstance(node, ast.Match) and floor < (3, 10):
                        offenders.append(f"{name}:{node.lineno} match")
                    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                            and node.func.id == "zip" and floor < (3, 10)
                            and any(k.arg == "strict" for k in node.keywords)):
                        offenders.append(f"{name}:{node.lineno} zip(strict=)")
        self.assertEqual(offenders, [], "these need a higher floor than declared")


class ChecklistProvenance(unittest.TestCase):
    """The 200 borrowed titles have to say where they came from, in the file that
    holds them. CREDITS.md is the licence record; this is the one that survives the
    file being copied out on its own."""

    def setUp(self):
        self.path = os.path.join(SKILL, "resources", "config", "plerdy-titles.json")
        with open(self.path, encoding="utf-8") as f:
            self.raw = json.load(f)

    def test_the_titles_file_names_its_source(self):
        src = self.raw.get("_source")
        self.assertIsInstance(src, dict, "plerdy-titles.json has no _source block")
        self.assertIn("plerdy.com/seo-checklist", src.get("url", ""))
        self.assertRegex(src.get("retrieved", ""), r"^\d{4}-\d{2}-\d{2}$")

    def test_metadata_keys_do_not_reach_the_generator(self):
        """`load_titles` used to call int() on every key, so any note added to this
        file would have crashed the build rather than documenting it."""
        sys.path.insert(0, os.path.join(SKILL, "tools"))
        import build_checklist
        titles = build_checklist.load_titles()
        self.assertEqual(len(titles), 200)
        self.assertTrue(all(isinstance(k, int) for k in titles))
        self.assertEqual(titles[1], "Ensure URL Is Indexed")

    def test_override_metadata_keys_do_not_reach_the_generator(self):
        sys.path.insert(0, os.path.join(SKILL, "tools"))
        import build_checklist
        overrides = build_checklist.load_title_overrides()
        self.assertEqual(set(overrides),
                         # GO-143 joined in 0.89.0: the inherited title named the
                         # Sitelinks Search Box, which Google removed from Search on
                         # 21 November 2024, and sitelinks, which no markup produces.
                         {"CI-002", "GO-143", "LO-200", "MB-105", "MD-184", "TE-169",
                          "TE-177", "TE-181"})
        self.assertNotIn("_comment", overrides)

    def test_every_numbered_title_is_referenced_by_exactly_one_item(self):
        """plerdy_ref is the trace back to the source line, so the mapping has to be
        a bijection over 1..200 — and the 17 items this plugin added must not claim
        a reference they do not have."""
        numbered = sorted(int(k) for k in self.raw if k.lstrip("-").isdigit())
        refs = [i["plerdy_ref"] for i in ITEMS if i["plerdy_ref"] is not None]
        self.assertEqual(numbered, list(range(1, 201)))
        self.assertEqual(sorted(refs), numbered)
        added = [i["id"] for i in ITEMS if i["plerdy_ref"] is None]
        self.assertEqual(len(added), 17, f"unexpected unreferenced items: {added}")


class DeliberateTitleOverrides(unittest.TestCase):
    """A local title may narrow a borrowed one, but never silently."""

    def setUp(self):
        with open(TITLE_OVERRIDES, encoding="utf-8") as f:
            self.raw = json.load(f)
        with open(os.path.join(SKILL, "resources", "config", "plerdy-titles.json"),
                  encoding="utf-8") as f:
            self.source_titles = json.load(f)
        self.overrides = {key: value for key, value in self.raw.items()
                          if not key.startswith("_")}

    def test_every_override_is_explained_shipped_and_differs_from_its_source(self):
        known = {item["id"]: item for item in ITEMS}
        problems = []
        for item_id, override in self.overrides.items():
            if item_id not in known:
                problems.append(f"{item_id}: no such registry item")
                continue
            title = str(override.get("title") or "").strip()
            why = str(override.get("why") or "").strip()
            if not title:
                problems.append(f"{item_id}: empty title")
            if not why:
                problems.append(f"{item_id}: no reason")
            if known[item_id]["title"] != override.get("title"):
                problems.append(f"{item_id}: shipped registry ignored the override")
            ref = known[item_id]["plerdy_ref"]
            original = self.source_titles.get(str(ref))
            if not original:
                problems.append(f"{item_id}: source title is missing")
            if original == override.get("title"):
                problems.append(f"{item_id}: override repeats the source title")
        self.assertEqual(problems, [])

    def test_mb_105_names_the_comparison_it_asserts(self):
        item = next(item for item in ITEMS if item["id"] == "MB-105")
        title = item["title"]
        self.assertNotIn("Desktop", title)
        self.assertNotIn("mobile", title.lower())
        self.assertIn("Served", title)
        self.assertIn("Rendered", title)

    def test_mb_105_fix_names_the_fields_the_script_compares(self):
        from javascript_render_audit import summarize

        item = next(item for item in ITEMS if item["id"] == "MB-105")
        fix = item["fix"].lower()
        fields = summarize("<html><head></head><body></body></html>",
                           "https://example.com/")
        wording = {
            "meta_description": "description",
            "h1_count": "h1s",
            "internal_link_count": "internal links",
            "schema_count": "schema",
            "word_count": "body text",
        }
        self.assertIn("served html", fix)
        for field in fields:
            phrase = wording.get(field, field.removesuffix("_count").replace("_", " "))
            self.assertIn(phrase, fix, f"the fix does not name {field}")

    def test_the_three_raw_versus_rendered_items_agree_on_which_one_compares(self):
        for item_id in ("TE-169", "TE-177"):
            self.assertIn("MB-105", self.overrides[item_id]["why"])
        self.assertIn("TE-169", self.overrides["MB-105"]["why"])
        self.assertIn("TE-177", self.overrides["MB-105"]["why"])

    def test_the_builder_refuses_all_invalid_override_shapes(self):
        sys.path.insert(0, os.path.join(SKILL, "tools"))
        import build_checklist
        titles = build_checklist.load_titles()
        items = build_checklist.build(titles, {})
        cases = {
            "unknown id": ({"NO-999": {"title": "Different", "why": "Reason"}},
                           "NO-999: no registry item"),
            "unborrowed item": ({"GEO-001": {"title": "Different", "why": "Reason"}},
                                "GEO-001: item has no Plerdy source title"),
            "blank title": ({"CI-002": {"title": " ", "why": "Reason"}},
                            "CI-002: override title is blank"),
            "blank reason": ({"CI-002": {"title": "Different", "why": " "}},
                             "CI-002: override reason is blank"),
            "source title": ({"CI-002": {"title": titles[2], "why": "Reason"}},
                             "CI-002: override title matches its Plerdy source title"),
        }
        for label, (overrides, expected) in cases.items():
            with self.subTest(label):
                problems = build_checklist.title_override_problems(
                    items, titles, overrides)
                self.assertTrue(any(expected in problem for problem in problems),
                                problems)


class RegistryDocs(unittest.TestCase):
    def test_every_script_the_registry_runs_is_documented(self):
        """Assert rules must be written against observed output, and the shapes
        file is where that observation is recorded."""
        with open(SHAPES, encoding="utf-8") as f:
            doc = f.read()
        scripts = {(i.get("check") or {}).get("script") for i in ITEMS} - {None}
        undocumented = sorted(s for s in scripts if f"### {s}" not in doc)
        self.assertEqual(undocumented, [], f"undocumented: {undocumented}")

    def test_a_script_the_runner_runs_itself_is_documented_too(self):
        """`site_crawl.py` is named by no registry item — the runner runs it before
        it builds the plan and hands the result to ten items that are. A gate derived
        only from the registry cannot see it, and that shape of blind spot has cost
        this tree twice: `probe_shapes.py` had no input for the one item it could not
        probe, and the dead-origin sweep took its script list from a table that was
        missing the one crawler nobody had listed.
        """
        with open(SHAPES, encoding="utf-8") as f:
            doc = f.read()
        with open(os.path.join(SKILL, "scripts", "checklist_runner.py"),
                  encoding="utf-8") as f:
            runner = f.read()
        named = set(re.findall(r'run_script\(\s*"([^"]+\.py)"', runner))
        self.assertTrue(named, "run_script is no longer called with a literal name; "
                               "this test needs rewriting rather than deleting")
        undocumented = sorted(s for s in named if f"### {s}" not in doc)
        self.assertEqual(undocumented, [], f"undocumented: {undocumented}")

    def test_every_documented_script_exists(self):
        """The other direction, and the one nothing was checking.

        The two tests above ask whether every script has a section. Neither asks
        whether every section has a script, so a section outlives the script it
        describes and nothing says so: `audit_assertions.py` only follows paths for
        scripts the *registry* names, and a section nothing points at is read by
        nobody. Seven had accumulated by 0.26 — `product_schema_checker.py`,
        `review_schema_checker.py`, `readability.py` and `x_robots_header_checker.py`
        with full output shapes, three more in the missing-args table.

        The `readability.py` section is why this is worth a gate rather than a
        cleanup. It listed `has_loop` and `has_mixed_protocol`, which are
        `redirect_checker`'s fields — so it was not merely describing a script that
        had gone, it was describing it wrongly, and an assertion written against it
        would have been written against nothing.
        """
        with open(SHAPES, encoding="utf-8") as f:
            doc = f.read()
        documented = set(re.findall(r"^### (\S+\.py)$", doc, re.M))
        self.assertTrue(documented, "no '### <script>.py' sections found; the "
                                    "reference changed shape and this test with it")
        missing = sorted(s for s in documented
                         if not os.path.exists(os.path.join(SCRIPTS, s)))
        self.assertEqual(missing, [], f"documented but not on disk: {missing}")


class NetworkAccessGoesThroughTheGuard(unittest.TestCase):
    """Every script that can open a connection must be able to be stopped.

    The runner states the rule beside the switch that carries it — "55 scripts in 55
    processes each call assert_safe_url for themselves, so the allowance has to travel
    with them" — and `--allow-private` is one decision for a whole run precisely
    because a run that reaches a private address in one script and not another cannot
    be described honestly in an artifact.

    Scripts pick the guard up transitively by fetching through `safe_get`. A script
    that opens its own socket does not, and `tls_certificate.py` did exactly that
    until 0.27: host and port straight from argv into `socket.create_connection`, with
    the flag never reaching it. Nothing showed it, because the script kept returning a
    well-formed result. This is that defect as a class rather than as one file.
    """

    # Modules that can open a connection. `urllib.parse` is deliberately absent:
    # urlparse and urljoin are string handling, nearly every script imports them, and
    # a gate that flags them is a gate somebody switches off within a week.
    NETWORK_MODULES = ("socket", "ssl", "requests", "httpx", "urllib.request",
                       "http.client", "ftplib", "smtplib")

    # Exemptions, each with the reason written down. A bare list would rot into a
    # place to put things; the reason is what a future reader argues with.
    ALLOWED = {
        "lib/safe_http.py":
            "is the guard. assert_safe_url lives here.",
        "server_log_audit.py":
            "resolves IP addresses read out of an operator's log file (reverse and "
            "forward DNS, for --verify-bots). It fetches no URL and takes no host "
            "from a page, so there is no request for the guard to refuse.",
        "gsc_url_inspection.py":
            "talks to Search Console through google-api-client, which owns its own "
            "transport and trust. The socket import sets a global timeout so a hung "
            "API call cannot stall the run.",
    }

    def _scripts(self):
        for name in sorted(os.listdir(SCRIPTS)):
            if name.endswith(".py"):
                yield name, os.path.join(SCRIPTS, name)
        lib = os.path.join(SCRIPTS, "lib")
        for name in sorted(os.listdir(lib)):
            if name.endswith(".py"):
                yield f"lib/{name}", os.path.join(lib, name)

    def _network_imports(self, path):
        with open(path, encoding="utf-8") as f:
            source = f.read()
        found = set()
        reaches_guard = False
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            else:
                continue
            for name in names:
                if name == "safe_http" or name.endswith(".safe_http"):
                    reaches_guard = True
                if any(name == m or name.startswith(m + ".")
                       for m in self.NETWORK_MODULES):
                    found.add(name)
        return found, reaches_guard

    def test_a_script_that_can_open_a_connection_reaches_the_guard(self):
        """Import `lib.safe_http`, or be exempt in writing. There is no third case."""
        unguarded = {}
        for name, path in self._scripts():
            imports, reaches_guard = self._network_imports(path)
            if not imports or name in self.ALLOWED:
                continue
            if not reaches_guard:
                unguarded[name] = sorted(imports)
        self.assertEqual(unguarded, {}, (
            f"these reach the network without reaching the guard: {unguarded}. "
            f"Either fetch through lib.safe_http (safe_get, or assert_safe_url "
            f"before opening the socket yourself), or add the script to ALLOWED "
            f"above with the reason it cannot."))

    def test_the_exemption_list_has_no_stale_entries(self):
        """An allow-list nobody prunes stops being a list of exceptions and becomes a
        place to put things. A script that no longer needs the exemption — because it
        moved to `safe_http`, or stopped touching the network at all — has to come
        off, or the next reader inherits a permission nobody granted."""
        stale = []
        for name in sorted(self.ALLOWED):
            path = os.path.join(SCRIPTS, name)
            if not os.path.exists(path):
                stale.append(f"{name} (no such script)")
                continue
            imports, reaches_guard = self._network_imports(path)
            if not imports:
                stale.append(f"{name} (imports nothing that opens a connection)")
            elif name != "lib/safe_http.py" and reaches_guard:
                stale.append(f"{name} (now goes through safe_http)")
        self.assertEqual(stale, [], f"exemptions no longer needed: {stale}")


class Profiles(unittest.TestCase):
    def setUp(self):
        with open(PROFILES, encoding="utf-8") as f:
            self.profiles = json.load(f)["profiles"]

    def test_default_profile_excludes_nothing(self):
        d = self.profiles["default"]
        self.assertEqual(d["exclude_categories"], [])
        self.assertEqual(d["exclude_scripts"], [])
        self.assertEqual(d["exclude_items"], [])

    def test_profiles_reference_real_categories_scripts_and_items(self):
        cats = {i["category"] for i in ITEMS}
        scripts = {(i.get("check") or {}).get("script") for i in ITEMS} - {None}
        ids = {i["id"] for i in ITEMS}
        for name, p in self.profiles.items():
            for c in p["exclude_categories"]:
                self.assertIn(c, cats, f"{name} excludes unknown category {c}")
            for s in p["exclude_scripts"]:
                self.assertIn(s, scripts, f"{name} excludes unused script {s}")
            for i in p["exclude_items"]:
                self.assertIn(i, ids, f"{name} excludes unknown item {i}")

    def test_every_excluded_item_says_why(self):
        """An exclusion by category names the category and one by script names the
        script. An exclusion by id has nothing a reader can reconstruct, so the profile
        has to say it: narrowing scope is the one operation in this tool that raises the
        score, and it must argue for itself on the surface where it happens."""
        for name, p in self.profiles.items():
            reasons = p.get("exclude_item_reasons") or {}
            for i in p["exclude_items"]:
                self.assertIn(i, reasons, f"{name} excludes {i} with no reason given")
                self.assertGreater(len(reasons[i]), 30,
                                   f"{name}'s reason for {i} is too short to be one")
            for i in reasons:
                self.assertIn(i, p["exclude_items"],
                              f"{name} explains {i}, which it does not exclude")

    def test_profile_script_args_name_scripts_the_registry_uses(self):
        """A threshold moved for a script no item runs moves nothing, silently."""
        scripts = {(i.get("check") or {}).get("script") for i in ITEMS} - {None}
        for name, p in self.profiles.items():
            for script, extra in (p.get("script_args") or {}).items():
                self.assertIn(script, scripts,
                              f"{name} passes args to unused script {script}")
                self.assertTrue(extra, f"{name} passes an empty arg list to {script}")
                self.assertTrue(all(isinstance(a, str) for a in extra))

    def test_a_profile_that_moves_a_threshold_explains_it(self):
        for name, p in self.profiles.items():
            if p.get("script_args"):
                self.assertGreater(len(p.get("script_args_note", "")), 60,
                                   f"{name} moves a threshold without saying why")

    def test_no_profile_excludes_a_critical_item(self):
        """Profiles narrow scope; they must not be a way to hide hard failures."""
        sys.path.insert(0, SCRIPTS)
        from checklist_runner import profile_excludes
        for name, p in self.profiles.items():
            excluded = profile_excludes(ITEMS, p)
            crit = [i["id"] for i in ITEMS
                    if i["id"] in excluded and i["severity"] == "critical"]
            self.assertEqual(crit, [], f"profile {name} hides critical items {crit}")


class BundledPlaybooks(unittest.TestCase):
    """The playbooks are bundled so the plugin is self-contained. That only holds
    if the files exist, the items they claim still exist, and none of them is
    allowed to move a status on its own."""

    def setUp(self):
        path = os.path.join(SKILL, "resources", "config", "playbooks.json")
        with open(path, encoding="utf-8") as f:
            self.playbooks = json.load(f)["playbooks"]

    def test_every_playbook_file_is_present(self):
        """A self-contained plugin cannot point at a file it does not ship."""
        for name, p in self.playbooks.items():
            self.assertTrue(os.path.exists(os.path.join(SKILL, p["path"])),
                            f"{name} points at missing {p['path']}")

    def test_every_referenced_item_exists(self):
        ids = {i["id"] for i in ITEMS}
        for name, p in self.playbooks.items():
            for item_id in p["items"]:
                self.assertIn(item_id, ids, f"{name} references unknown {item_id}")

    def test_every_playbook_states_what_it_cannot_decide(self):
        """A playbook that does not say where it stops will be read as a verdict."""
        for name, p in self.playbooks.items():
            self.assertTrue(p.get("leaves_status"), f"{name} has no leaves_status")

    def test_documented_in_the_skill(self):
        with open(os.path.join(SKILL, "SKILL.md"), encoding="utf-8") as f:
            doc = f.read()
        for name, p in self.playbooks.items():
            self.assertIn(os.path.basename(p["path"]), doc,
                          f"{name} is configured but never documented")

    def test_nothing_instructs_the_reader_to_install_another_plugin(self):
        """Self-containment is the point: the audit must not tell anyone to go
        fetch a skill from somewhere else. Attribution in CREDITS.md and in the
        playbook headers is provenance, not a dependency, and is exempt."""
        offenders = []
        for base, _dirs, files in os.walk(SKILL):
            for f in files:
                if not f.endswith(".md"):
                    continue
                path = os.path.join(base, f)
                with open(path, encoding="utf-8") as fh:
                    for n, line in enumerate(fh, 1):
                        if line.lstrip().startswith(("<!--", "Bundled playbook")):
                            continue
                        if "skill is installed" in line or "install the" in line.lower():
                            offenders.append(f"{os.path.relpath(path, SKILL)}:{n}")
        self.assertEqual(offenders, [], f"external dependency implied at {offenders}")

    def test_borrowed_material_is_attributed(self):
        """Two playbooks are adapted from MIT-licensed work; the notice has to
        travel with them."""
        credits = os.path.join(ROOT, "CREDITS.md")
        self.assertTrue(os.path.exists(credits), "CREDITS.md is missing")
        with open(credits, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("MIT License", text)
        for name in ("competitor-research", "client-report-structure"):
            self.assertIn(name, text, f"{name} is not attributed in CREDITS.md")


class GeneratorIsInStep(unittest.TestCase):
    def test_registry_matches_its_generator(self):
        r = subprocess.run([sys.executable,
                            os.path.join(SKILL, "tools", "build_checklist.py"),
                            "--check"], capture_output=True, text=True,
                           close_fds=False)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class ProbeCoversWhatTheRegistryReads(unittest.TestCase):
    """`tools/probe_shapes.py` is how the asserted paths get checked against real
    output. It used to hold its own list of scripts, and an unchecked copy of a
    list is a list that is wrong: it named seven scripts that no longer exist and
    missed three the registry reads — `cwv_metrics.py`, `rendered_audit.py` and
    `gsc_links_csv.py`, which between them decide eleven items. The tool for
    finding drift had drifted, in both directions, and nothing said so.

    Now the jobs are derived from the registry, and these tests are what keeps that
    true rather than merely true today."""

    def jobs(self, ctx):
        spec = importlib.util.spec_from_file_location(
            "probe_shapes", os.path.join(SKILL, "tools", "probe_shapes.py"))
        # Not imported: importing it *runs* the probe, against the network. Only the
        # one definition is taken, compiled out of the shipped source, which keeps
        # this test offline while still reading the code that ships.
        with open(spec.origin, encoding="utf-8") as f:
            source = f.read()
        start = source.index("def registry_jobs(")
        end = source.index("\nJOBS = registry_jobs")
        namespace = {"json": json, "os": os, "sys": sys,
                     "REGISTRY": os.path.join(SKILL, "resources", "config",
                                              "checklist.json")}
        exec(compile(source[start:end], spec.origin, "exec"), namespace)
        return namespace["registry_jobs"](ctx)

    def registry_scripts(self, placeholders_available):
        with open(os.path.join(SKILL, "resources", "config", "checklist.json"),
                  encoding="utf-8") as f:
            items = json.load(f)["items"]
        out = set()
        for item in items:
            check = item.get("check") or {}
            if not check.get("script"):
                continue
            needed = {a[1:-1] for a in check.get("args") or []
                      if isinstance(a, str) and a.startswith("{") and a.endswith("}")}
            if needed <= placeholders_available:
                out.add(check["script"])
        return out

    FULL_CTX = {"url": "https://example.com/", "html": "/tmp/p.html",
                "gsc_property": "sc-domain:example.com",
                "gsc_credentials": "/tmp/k.json", "cwv_json": "/tmp/cwv.json",
                "rendered_json": "/tmp/r.json", "links_csv": "/tmp/l.csv",
                "indexnow_key": "k", "inventory_json": "/tmp/inv.json"}

    def test_every_script_the_registry_names_is_probed(self):
        probed = {script for script, _ in self.jobs(self.FULL_CTX)}
        expected = self.registry_scripts(set(self.FULL_CTX))
        self.assertEqual(expected - probed, set())

    def test_every_probed_script_exists_on_disk(self):
        missing = sorted({script for script, _ in self.jobs(self.FULL_CTX)
                          if not os.path.exists(os.path.join(SKILL, "scripts", script))})
        self.assertEqual(missing, [], "the probe would report these as __missing__ "
                                      "and nothing else would notice")

    def test_a_job_whose_input_is_absent_is_dropped_not_probed_with_a_placeholder(self):
        """The old list hard-coded a `[URL]` argv per script, so a check needing a
        credential path had no way to be skipped — it was simply not listed, which
        is why three of them never were."""
        jobs = self.jobs({"url": "https://example.com/"})
        for script, args in jobs:
            for arg in args:
                self.assertFalse(arg.startswith("{") and arg.endswith("}"),
                                 f"{script} would be probed with {arg} as a literal")
        scripts = {script for script, _ in jobs}
        self.assertNotIn("gsc_checker.py", scripts)
        self.assertNotIn("cwv_metrics.py", scripts)

    def test_the_jobs_are_deduplicated_the_way_the_runner_deduplicates(self):
        """17 items read one `parse_html.py` run. A probe that ran it 17 times would
        be reporting on a different workload than the one it is meant to describe."""
        jobs = self.jobs(self.FULL_CTX)
        self.assertEqual(len(jobs), len({(s, tuple(a)) for s, a in jobs}))
        self.assertEqual(sum(1 for s, _ in jobs if s == "parse_html.py"), 1)


class NoAssertionThatCanNeverFire(unittest.TestCase):
    """`none_matching` passes when nothing matches, so a pattern aimed at wording
    its script cannot emit reports PASS for every site, silently, forever.

    Fifteen of the registry's twenty-one pattern assertions were in that state:
    three asked an accessibility checker about font sizes it never measures, two
    asked a mobile checker about interstitials it never looks for, one wanted
    "lazy" before "LCP" in a message that says "LCP image is lazy-loaded", and one
    — a `critical` item about blocking CSS and JS in robots.txt — was matching its
    own script's module docstring.
    """

    def test_every_pattern_assertion_can_match_its_script(self):
        sys.path.insert(0, os.path.join(SKILL, "tools"))
        from audit_assertions import audit
        dead = audit(REGISTRY)
        detail = "; ".join(f"{d['id']} {d['script']} {d['op']}={d['pattern']!r}"
                           for d in dead)
        self.assertEqual(dead, [], f"assertions that always pass: {detail}")

    def test_the_audit_notices_a_pattern_nobody_can_emit(self):
        """The guard has to be able to fail, or it is decoration. A registry whose
        assertion looks for a string no script contains must be reported."""
        sys.path.insert(0, os.path.join(SKILL, "tools"))
        from audit_assertions import audit
        import tempfile
        fake = dict(DATA, items=[{
            "id": "ZZ-001", "category": "content", "category_label": "C",
            "title": "t", "severity": "low", "source": "script", "effort": "low",
            "fix": "", "check": {"script": "parse_html.py", "args": [],
                                 "requires": "offline",
                                 "assert": {"path": "issues",
                                            "none_matching": "quantum entanglement"}}}])
        path = os.path.join(tempfile.mkdtemp(), "fake.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(fake, f)
        self.assertEqual([d["id"] for d in audit(path)], ["ZZ-001"])

    def test_remediation_text_does_not_count_as_something_the_script_emits(self):
        """The gap that let KW-072 and KW-073 through this guard for a whole tier:
        their pattern matched a `fix` string, so the tool saw a live assertion."""
        sys.path.insert(0, os.path.join(SKILL, "tools"))
        from audit_assertions import emittable_strings
        strings = emittable_strings("article_seo.py")
        advice = [t for t in strings if "primary keyword" in t.lower()]
        self.assertEqual(advice, [], f"remediation text counted as output: {advice[:1]}")
        self.assertTrue(any("No H1 tag detected" in t for t in strings),
                        "findings must still count")

    def test_page_derived_paths_are_exempt_and_few(self):
        """A pattern over a value that comes from the page is checking the site,
        not the script's wording — but the exemption list is a way to silence the
        guard, so it stays short and explicit."""
        sys.path.insert(0, os.path.join(SKILL, "tools"))
        from audit_assertions import PAGE_DERIVED
        self.assertLessEqual(len(PAGE_DERIVED), 5)
        for script, _path in PAGE_DERIVED:
            self.assertTrue(os.path.exists(os.path.join(SCRIPTS, script)), script)


class GradedRowsCarryWhatTheReportRanksOn(unittest.TestCase):
    """The report claims its fix list is ranked by severity against effort. That
    was false for every run: `grade()` did not copy `effort` onto the row, so
    priority_of fell back to "medium" for all 214 items and the ranking collapsed
    to severity alone. The effort column printed "?" and nobody read it as a bug."""

    def test_effort_survives_grading(self):
        from checklist_runner import grade
        item = [{"id": "X-001", "plerdy_ref": 1, "category": "content",
                 "category_label": "C", "title": "t", "severity": "high",
                 "source": "manual", "effort": "low", "fix": ""}]
        self.assertEqual(grade(item, {}, {}, {}, False)[0]["effort"], "low")

    def test_effort_changes_the_ranking(self):
        """If it did not, carrying the field would be decoration."""
        sys.path.insert(0, SCRIPTS)
        from checklist_report import priority_of
        cheap = priority_of({"severity": "high", "effort": "low"})
        dear = priority_of({"severity": "high", "effort": "high"})
        self.assertGreater(cheap, dear)

    def test_every_registry_item_declares_an_effort(self):
        for i in ITEMS:
            self.assertIn(i.get("effort"), VALID_EFFORT, i["id"])
class APatternNeverReadsAnAddress(unittest.TestCase):
    """`none_matching` over an `issues[]` array must name the field it searches.

    Without `field` the pattern is matched against the whole serialised issue —
    severity, message, url, evidence — so it can fire on text the check never
    reasoned about. GO-138's `404` matched the *port* of a test origin that bound
    40455 and reported a clean sitemap as full of dead URLs; on a real site a
    sitemap containing `/blog/404-errors-explained` does the same. GO-143's
    `WebSite` was one `/website-design` URL away from the same failure.

    Three occurrences now: the keyword items fired on their own remediation text in
    0.5.0, the soft-404 guard carries "never a substring" in writing, and these
    rules were never audited against either lesson. A rule, not a memory.
    """

    def test_every_issue_pattern_names_the_field_it_searches(self):
        loose = []
        for item in DATA["items"]:
            rule = ((item.get("check") or {}).get("assert") or {})
            if "none_matching" not in rule:
                continue
            # Only arrays of issue dicts are at risk. A path that resolves to a
            # plain string — `meta_robots` — has one thing to match and no
            # neighbouring URL to match by accident.
            if rule.get("path") == "issues" and not rule.get("field"):
                loose.append(f"{item['id']} ({rule['none_matching']})")
        self.assertEqual(loose, [], "these match the whole issue, URLs included: "
                                    + ", ".join(loose))

    def test_the_named_field_is_one_the_scripts_emit(self):
        """A `field` that no issue carries makes the rule match nothing and pass
        every site — the failure `audit_assertions.py` exists for, arrived at from
        the other direction."""
        for item in DATA["items"]:
            rule = ((item.get("check") or {}).get("assert") or {})
            if rule.get("path") == "issues" and rule.get("field"):
                self.assertIn(rule["field"], ("message", "type", "severity"),
                              f"{item['id']} searches an unknown issue field")


class OneCheckCarriesWeightOnce(unittest.TestCase):
    """`scores_with`: nine twins across the seven duplicate groups it exists for.

    Two source checklists are merged into this registry and both of them ask some
    questions. Each group runs one script with one set of arguments and one assertion
    — `CI-016` *Provide Meaningful Image Alt Text* and `MD-186` *Provide Meaningful Alt
    Text* are one question written twice. Until 0.22 both halves scored, which did two
    things: a single defect pulled the headline down twice, and where the twins
    disagreed on severity the weight of one defect depended on which of them a reader
    happened to look at.

    The twin still runs and still reports. It does not carry weight. What these tests
    guard is that the pointer is not a way to make an item disappear: every twin must
    point at an item that exists, that shares its exact check, and that carries the
    weight itself.
    """

    def twins(self):
        return [i for i in ITEMS if i.get("scores_with")]

    @staticmethod
    def shape(item):
        check = item.get("check") or {}
        return (check.get("script"), json.dumps(check.get("args"), sort_keys=True),
                json.dumps(check.get("assert"), sort_keys=True))

    def test_every_pointer_names_an_item_that_exists(self):
        ids = {i["id"] for i in ITEMS}
        for item in self.twins():
            self.assertIn(item["scores_with"], ids,
                          f"{item['id']} defers to an id that is not in the registry")

    def test_safe_browsing_is_one_flat_group(self):
        by_id = {item["id"]: item for item in ITEMS}
        self.assertIsNone(by_id["SE-114"].get("scores_with"))
        for item_id in ("SE-116", "TE-171"):
            self.assertEqual(by_id[item_id].get("scores_with"), "SE-114")
            self.assertEqual(self.shape(by_id[item_id]), self.shape(by_id["SE-114"]))

    def test_md_189_uses_responsive_measurement_and_defers_to_mb_096(self):
        by_id = {item["id"]: item for item in ITEMS}
        self.assertEqual(by_id["MD-189"]["check"]["assert"],
                         {"path": "responsive_count", "gte": 1})
        self.assertEqual(by_id["MD-189"].get("scores_with"), "MB-096")

    def test_mb_097_carries_the_modern_format_measurement(self):
        by_id = {item["id"]: item for item in ITEMS}
        self.assertEqual(by_id["MB-097"]["check"]["assert"],
                         {"path": "modern_format_count", "gte": 1})
        self.assertIsNone(by_id["MB-097"].get("scores_with"))

    def test_image_format_and_responsive_theme_keeps_six_weight_points(self):
        from checklist_runner import SEVERITY_WEIGHT

        ids = {"MB-096", "MB-097", "MD-189"}
        items = [item for item in ITEMS if item["id"] in ids]
        self.assertEqual({item["id"] for item in items}, ids)
        weight = sum(SEVERITY_WEIGHT[item["severity"]] for item in items
                     if not item.get("scores_with"))
        self.assertEqual(weight, 6)

    def test_served_html_and_rendered_dom_are_distinct_checks(self):
        by_id = {item["id"]: item for item in ITEMS}
        served = by_id["CI-017"]
        rendered = by_id["TE-181"]

        self.assertEqual(served["title"], "Validate HTML (W3C)")
        self.assertEqual(served["fix"],
                         "Fix W3C validation errors - they affect rendering and parsing")
        self.assertEqual(served["check"], {
            "script": "html_validator.py",
            "args": ["{url}"],
            "requires": "api",
            "assert": {"path": "summary.errors", "eq": 0},
        })
        self.assertEqual(rendered["title"], "Validate the Rendered DOM (W3C)")
        # The DOM arrives in an artifact rather than from a browser started mid-audit:
        # one launched inside the run refetches the page and its subresources behind
        # the response cache, which the CI request-discipline step forbids.
        self.assertEqual(rendered["check"]["args"],
                         ["{url}", "--rendered-json", "{rendered_json}"])
        self.assertEqual(rendered["check"]["requires"], "api")
        self.assertEqual(rendered["check"]["assert"], served["check"]["assert"])
        self.assertNotEqual(self.shape(rendered), self.shape(served))
        self.assertIsNone(rendered.get("scores_with"))

    def test_served_html_and_rendered_dom_carry_six_weight_points(self):
        from checklist_runner import SEVERITY_WEIGHT

        items = [item for item in ITEMS if item["id"] in {"CI-017", "TE-181"}]
        self.assertEqual(len(items), 2)
        weight = sum(SEVERITY_WEIGHT[item["severity"]] for item in items
                     if not item.get("scores_with"))
        self.assertEqual(weight, 6)

    def test_a_twin_shares_its_primary_s_check_exactly(self):
        """The claim `scores_with` makes is *this is the same check*. If the shapes
        differ, two different questions are being asked and one of them stopped
        counting — which is not a merge, it is a deletion with a friendly name."""
        by_id = {i["id"]: i for i in ITEMS}
        for item in self.twins():
            primary = by_id[item["scores_with"]]
            self.assertEqual(self.shape(item), self.shape(primary),
                             f"{item['id']} defers to {primary['id']} but they do not "
                             f"run the same check")

    def test_the_item_that_carries_the_weight_carries_it(self):
        """No chains and no cycles. A twin pointing at another twin would leave the
        pair scoring nothing at all, and nothing in the score would say so."""
        by_id = {i["id"]: i for i in ITEMS}
        for item in self.twins():
            primary = by_id[item["scores_with"]]
            self.assertIsNone(primary.get("scores_with"),
                              f"{item['id']} -> {primary['id']} -> "
                              f"{primary.get('scores_with')}: nothing scores")

    def test_the_survivor_is_never_the_weaker_of_the_two(self):
        """Where the twins disagree on severity, dropping the higher one would lower
        the registry's own weighting of a defect by an accident of which id was typed
        first. MB-102 (low) and MD-190 (medium) are the pair this is about."""
        order = ["low", "medium", "high", "critical"]
        by_id = {i["id"]: i for i in ITEMS}
        for item in self.twins():
            primary = by_id[item["scores_with"]]
            self.assertGreaterEqual(order.index(primary["severity"]),
                                    order.index(item["severity"]),
                                    f"{item['id']} ({item['severity']}) defers to "
                                    f"{primary['id']} ({primary['severity']})")

    def test_no_group_sharing_one_check_is_left_unruled(self):
        """The other direction: a new item that silently duplicates an existing
        assertion. `tools/audit_item_semantics.py` is the CI step for this; the test
        is here so the suite fails first and names the pair."""
        by_shape = {}
        for item in ITEMS:
            if not (item.get("check") or {}).get("script"):
                continue
            by_shape.setdefault(self.shape(item), []).append(item)
        for group in by_shape.values():
            if len(group) < 2:
                continue
            carriers = [i for i in group if not i.get("scores_with")]
            ids = ", ".join(i["id"] for i in group)
            self.assertEqual(len(carriers), 1,
                             f"{ids} run one check; exactly one must carry the weight")
            self.assertTrue(all(i["scores_with"] == carriers[0]["id"]
                                for i in group if i.get("scores_with")),
                            f"{ids} share a check but do not agree which one scores")


if __name__ == "__main__":
    unittest.main()
