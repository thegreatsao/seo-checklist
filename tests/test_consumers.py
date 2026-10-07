"""What another program reads from this plugin, held so that a rename cannot be silent.

`openspec/specs/governance/` GOV-12. Workbench, Anton's dashboard, starts this plugin's
two scripts without a model in between and reads what they leave: both of its builds
(`seo.py` on macOS, `windows/seo.py`, and `core/seo.py` they share). Nothing in this
repository said so. A flag renamed here, or a key in the results file, breaks a button
there, and the suite of this repository stays green while it does.

This module is the list. Every name in it was read out of Workbench's source on
7 October 2026, at its commit `54eddd8` — not out of the list its session sent on
4 October, which was one key short (`started_at`). It is in three parts:

* what Workbench finds by path, read from the tree;
* the command lines its form can compose, given to the two scripts' own parsers;
* one audit and its report, started with the commands `core/seo.py::build` and
  `report_argv` compose, from the working directory Workbench starts them in, and read
  the way `core/seo.py::_facts_of`, `manual_items` and `run_lang` read them.

What it does not hold: that this list is still what Workbench reads. That program is
another repository and no test here can open it. Before changing anything this module
names, tell the Workbench session; when Workbench starts reading something new, the
name is added here. A name removed from here is a decision that Workbench no longer
needs it.
"""
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(ROOT, "skills", "seo-checklist")
SCRIPTS = os.path.join(SKILL, "scripts")
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness  # noqa: E402
import checklist_report as report  # noqa: E402
import checklist_runner as runner  # noqa: E402

# `core/seo.py`: MODES, LANGS, PROFILES, RESULTS, VERDICTS.
MODES = ("page", "live", "archive")
LANGS = ("en", "ru")
PROFILES = ("auto", "default", "local", "ecommerce", "saas", "blog", "media")
RESULTS = "checklist-results.json"
VERDICTS = ("PASS", "FAIL", "WARN", "N/A")
# `seo.py` and `windows/seo.py`: PARTS, the keys of `scores.partition` the bar is drawn from.
PARTITION = ("decided", "waiting_on_you", "needs_a_person", "undecided", "not_applicable")
# `seo.py::version` and `windows/seo.py::version`, the same expression in both.
VERSION = re.compile(r'^version\s*=\s*"([^"]+)"', re.M)
# `core/seo.py::run_lang`, over the first 4096 characters of the HTML report.
HTML_LANG = re.compile(r'<html[^>]*\blang="([a-z]{2})"')

PAGE = ('<!doctype html><html lang="en"><head><title>Fixture page</title>'
        '<meta name="description" content="Enough of a page to audit.">'
        '</head><body><h1>Fixture page</h1><p>Body copy, and enough of it that the '
        'page is not taken for an empty shell: forty visible words is the threshold, '
        'so this paragraph carries a few more than that and says something about '
        'bread, ovens and the people who get up early to use them while it '
        'does.</p></body></html>')


def integer(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


class WhatWorkbenchFindsByPath(unittest.TestCase):
    """The plugin's place on disk is all Workbench is told; the rest it joins on."""

    def test_the_two_scripts_and_the_registry_are_where_it_looks(self):
        for name in ("checklist_runner.py", "checklist_report.py"):
            self.assertTrue(os.path.isfile(os.path.join(ROOT, "skills", "seo-checklist",
                                                        "scripts", name)), name)
        registry = os.path.join(ROOT, "skills", "seo-checklist", "resources", "config",
                                "checklist.json")
        with open(registry, encoding="utf-8") as f:
            # `item_count`: the number it shows beside the tool's name.
            self.assertGreater(len(json.load(f)["items"]), 0)

    def test_the_version_is_read_out_of_pyproject_by_one_expression(self):
        with open(os.path.join(ROOT, "pyproject.toml"), encoding="utf-8") as f:
            found = VERSION.search(f.read())
        self.assertIsNotNone(found, "Workbench would show v? and never see an update")
        # The same version a report is stamped with, which is the manifest's.
        self.assertEqual(found.group(1), runner.plugin_version())

    def test_an_update_installs_from_requirements_txt_at_the_root(self):
        """Its update is `git pull --ff-only`, then `pip install -r requirements.txt`
        with the checkout as the working directory."""
        self.assertTrue(os.path.isfile(os.path.join(ROOT, "requirements.txt")))


class WhatWorkbenchsFormCanSend(unittest.TestCase):
    """`core/seo.py::build` and `report_argv`, every value the form offers, given to
    the parsers the two scripts parse with."""

    def test_the_runner_takes_every_scope_and_profile(self):
        for mode in MODES:
            for profile in PROFILES:
                with self.subTest(mode=mode, profile=profile):
                    a = runner.build_parser().parse_args(
                        ["https://example.com/", "--json", RESULTS, "--no-prompt",
                         "--mode", mode, "--profile", profile])
                    self.assertEqual((a.mode, a.profile, a.json_out, a.no_prompt),
                                     (mode, profile, RESULTS, True))
        for profile in PROFILES:
            if profile != "auto":  # `auto` is the detector's answer, one of the others
                self.assertEqual(runner.load_profile(profile)["label"] != "", True, profile)

    def test_the_runner_takes_the_rest_of_the_form(self):
        """Free text goes as `--flag=value`, so that text starting with a dash is not
        read as another flag; a brand is given once per name."""
        a = runner.build_parser().parse_args(
            ["https://example.com/", "--json", RESULTS, "--no-prompt", "--mode", "archive",
             "--profile", "auto", "--archive", "copy", "--sample", "50", "--diff",
             "--allow-private", "--brand=Acme", "--brand=-dash first", "--keyword=-x y"])
        self.assertEqual((a.archive, a.sample, a.diff, a.allow_private),
                         ("copy", 50, True, True))
        self.assertEqual(a.brand, ["Acme", "-dash first"])
        self.assertEqual(a.keyword, "-x y")

    def test_the_report_takes_what_it_is_started_with(self):
        for lang in LANGS:
            with self.subTest(lang=lang):
                a = report.build_parser().parse_args(
                    [RESULTS, "--lang", lang, "--html", "CHECKLIST.html", "--markdown",
                     "CHECKLIST-REPORT.md", "--llm-queue", "LLM-QUEUE.md", "--fixes",
                     "fixes.csv", "--manual-answers", "manual-answers.json"])
                self.assertEqual((a.lang, a.html, a.markdown, a.llm_queue, a.fixes,
                                  a.manual_answers),
                                 (lang, "CHECKLIST.html", "CHECKLIST-REPORT.md",
                                  "LLM-QUEUE.md", "fixes.csv", "manual-answers.json"))
                self.assertEqual(report.Lang(lang).code, lang)


class ARunStartedTheWayWorkbenchStartsOne(unittest.TestCase):
    """Two audits of one site and their reports, by Workbench's own commands.

    The working directory is the runs root and each run's files go to
    `<runs>/<domain>/<time>/`, a folder that does not exist when the runner starts.
    A local copy is audited, so nothing is fetched. The second run asks for `--diff`.
    """

    @classmethod
    def setUpClass(cls):
        cls.dir = os.path.realpath(tempfile.mkdtemp())
        cls.addClassCleanup(shutil.rmtree, cls.dir, True)
        cls.runs, copy = os.path.join(cls.dir, "runs"), os.path.join(cls.dir, "copy")
        os.makedirs(cls.runs)
        os.makedirs(copy)
        with open(os.path.join(copy, "index.html"), "w", encoding="utf-8") as f:
            f.write(PAGE)
        here = os.getcwd()
        cls.addClassCleanup(os.chdir, here)
        os.chdir(cls.runs)
        cls.folders, cls.audits, cls.reports = [], [], []
        for stamp, extra, lang in (("20261007-120000", [], "en"),
                                   ("20261007-120500", ["--diff"], "ru")):
            folder = os.path.join(cls.runs, "example.com", stamp)
            cls.folders.append(folder)
            cls.audits.append(harness.spawn(
                [sys.executable, os.path.join(SCRIPTS, "checklist_runner.py"),
                 "https://example.com/", "--json", os.path.join(folder, RESULTS),
                 "--no-prompt", "--mode", "archive", "--profile", "auto",
                 "--archive", copy, *extra, "--brand=Acme", "--keyword=bread"],
                env=harness.offline_env(), timeout=600))
            cls.reports.append(harness.spawn(cls.report_argv(folder, lang),
                                             env=harness.offline_env(), timeout=120))
        # As the runner left them. A test below merges answers into the first run's
        # file, and tests run in the order of their names.
        cls.left = []
        for folder in cls.folders:
            with open(os.path.join(folder, RESULTS), encoding="utf-8") as f:
                cls.left.append(json.load(f))

    @staticmethod
    def report_argv(folder, lang, answers=None):
        argv = [sys.executable, os.path.join(SCRIPTS, "checklist_report.py"),
                os.path.join(folder, RESULTS), "--lang", lang,
                "--html", os.path.join(folder, "CHECKLIST.html"),
                "--markdown", os.path.join(folder, "CHECKLIST-REPORT.md"),
                "--llm-queue", os.path.join(folder, "LLM-QUEUE.md"),
                "--fixes", os.path.join(folder, "fixes.csv")]
        return argv + (["--manual-answers", os.path.join(folder, answers)] if answers else [])

    def results(self, n):
        with open(os.path.join(self.folders[n], RESULTS), encoding="utf-8") as f:
            return json.load(f)

    def test_both_steps_end_the_way_a_job_counts_as_done(self):
        """The runner must exit 0 for the report step to follow; the report may exit 0
        or 1 (`seo.py`: `rc in (0, 1)`), and the run is done when its HTML exists."""
        for audit, made, folder in zip(self.audits, self.reports, self.folders, strict=True):
            self.assertEqual(audit.returncode, 0, audit.stderr[-2000:])
            self.assertIn(made.returncode, (0, 1), made.stderr[-2000:])
            for name in ("CHECKLIST.html", "CHECKLIST-REPORT.md", "fixes.csv", RESULTS):
                self.assertTrue(os.path.isfile(os.path.join(folder, name)), name)

    def test_the_results_hold_what_the_history_row_is_drawn_from(self):
        """`core/seo.py::_facts_of`, key by key and in the types it accepts: a value of
        another type is read there as zero or as nothing, without a word."""
        r = self.left[0]
        for key in ("url", "domain", "mode", "profile"):
            self.assertIsInstance(r[key], str, key)
        self.assertEqual((r["mode"], r["domain"]), ("archive", "example.com"))
        self.assertTrue(integer(r["sample"]))
        datetime.fromisoformat(r["started_at"])
        self.assertIs(r["entry_reachable"], True)
        self.assertIn("entry_error", r)
        self.assertIsInstance(r["allow_private"], bool)
        scores = r["scores"]
        self.assertIsInstance(scores["seo_score"], (int, float))
        self.assertTrue(integer(scores["weight_pct"]) and integer(scores["decided"]))
        self.assertEqual(sorted(scores["partition"]), sorted(PARTITION))
        self.assertTrue(all(integer(v) for v in scores["partition"].values()))
        for key in ("llm_pending", "needs_input"):
            self.assertTrue(integer(scores["waiting_on_you"][key]), key)

    def test_the_second_run_names_the_first_as_what_it_was_compared_with(self):
        """`--diff`, from the working directory both were started in. The history is
        `.seo-runs` there, and a history row skips it because its name starts with a
        dot: the runs root holds that folder and the site's, and nothing else."""
        first, second = self.left
        self.assertIsNone(first["compared_with"])
        self.assertEqual(second["compared_with"]["started_at"], first["started_at"])
        self.assertEqual(second["compared_with"]["seo_score"], first["scores"]["seo_score"])
        self.assertIsInstance(second["diff"], list)
        self.assertEqual(sorted(os.listdir(self.runs)), [".seo-runs", "example.com"])
        self.assertEqual(len(os.listdir(os.path.join(self.runs, ".seo-runs", "example.com"))), 2)

    def test_the_report_says_which_language_it_was_made_in(self):
        """`run_lang` falls back to the report's own `<html lang>` when a run has no
        record of the language it was asked for."""
        for folder, lang in zip(self.folders, ("en", "ru"), strict=True):
            with open(os.path.join(folder, "CHECKLIST.html"), encoding="utf-8") as f:
                found = HTML_LANG.search(f.read(4096))
            self.assertEqual(found and found.group(1), lang)

    def test_an_item_that_needs_a_person_can_be_listed_and_answered(self):
        """`manual_items` and `save_answers`. The answers file is
        `{id: {status, evidence}}` with one of four verdicts; the report merges it
        into the results file it was given, in place, and a merged item is no longer
        `MANUAL` — which is why Workbench keeps the runner's results aside."""
        folder = self.folders[0]
        manual = [i for i in self.left[0]["items"] if i["status"] == "MANUAL"]
        self.assertGreaterEqual(len(manual), len(VERDICTS))
        for row in manual:
            for key in ("id", "title", "category_label", "fix"):
                self.assertIsInstance(row[key], str, key)
                self.assertTrue(row[key], f"{row['id']} has no {key}")
        answers = {row["id"]: {"status": verdict, "evidence": "looked at on the page"}
                   for row, verdict in zip(manual, VERDICTS, strict=False)}  # the first four
        with open(os.path.join(folder, "manual-answers.json"), "w", encoding="utf-8") as f:
            json.dump(answers, f, ensure_ascii=False, indent=2)
        merged = harness.spawn(self.report_argv(folder, "en", "manual-answers.json"),
                               env=harness.offline_env(), timeout=120)
        self.assertIn(merged.returncode, (0, 1), merged.stderr[-2000:])
        after = {i["id"]: i["status"] for i in self.results(0)["items"]}
        self.assertEqual({key: after[key] for key in answers},
                         {key: a["status"] for key, a in answers.items()})
        self.assertEqual(self.results(0)["scores"]["partition"]["needs_a_person"],
                         len(manual) - len(VERDICTS))


if __name__ == "__main__":
    unittest.main()
