"""Findings 10, 11, 12, 17, 18 and 19 of the repository audit of 2026-11-04 (batch P3).

Each case failed on `008b322`:

* 10 — history: a `--only` run and a run of another page in `--mode page` were taken as
  the baseline and as trend points of a full run or of this page; a stored run that is a
  JSON list, or is not UTF-8, raised out of `previous_run` and `run_series` before the
  run's `--json` was written, on every later run of that site.
* 11 — `calibrate_profile_detection` and `calibrate_paragraph_words` wrote their report
  from a corpus nothing in was read from, and `--check` passed the empty report.
* 12 — `calibrate_font_weight` and five constants of `calibrate_css_minification` wrote
  the live constant as the corpus's `recommended_value`, so `--check` compared the
  constant with itself and any value passed after a re-measure.
* 17 — `audit_score_sensitivity` weighed `scores_with` twins the runner leaves out, and
  listed both halves of a twin in its fix list.
* 18 — `scripts/verify-feature.sh` wrote `passing` for a blank verification command, and
  reported `passing` when the state could not be written.
* 19 — `corpus_fetch` cached whatever answered, an error page included, as the tarball.
"""
from __future__ import annotations

import gzip
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402,F401

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "skills", "seo-checklist", "tools")
sys.path.insert(0, TOOLS)

import checklist_runner  # noqa: E402
from checklist_runner import FAIL, PASS, WARN  # noqa: E402

import audit_score_sensitivity as sens  # noqa: E402
import calibrate_css_minification as css  # noqa: E402
import calibrate_font_weight as font  # noqa: E402
import calibrate_paragraph_words as paragraphs  # noqa: E402
import calibrate_profile_detection as profiles  # noqa: E402
import corpus_fetch  # noqa: E402


def quiet():
    return mock.patch("sys.stdout", new_callable=io.StringIO)


class Scratch(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="seo-p3-")
        self.addCleanup(shutil.rmtree, self.dir, True)


# -- 10: history ------------------------------------------------------------------

def run(started, *, mode="live", url="https://e.com/", only=None, items=(), score=50):
    return {"domain": "e.com", "url": url, "mode": mode, "only": only,
            "started_at": started, "scores": {"seo_score": score},
            "items": [{"id": i, "status": s, "title": i, "severity": "high"}
                      for i, s in items]}


class HistoryComparesLikeRuns(Scratch):
    def setUp(self):
        super().setUp()
        checklist_runner.use_history_dir(self.dir)
        self.addCleanup(checklist_runner.use_history_dir, "")
        self.folder = os.path.join(self.dir, "e.com")
        os.makedirs(self.folder)

    def store(self, name, payload=None, raw=None):
        path = os.path.join(self.folder, name)
        with open(path, "wb") as fh:
            fh.write(raw if raw is not None else json.dumps(payload).encode("utf-8"))
        return path

    def test_an_only_run_is_not_the_baseline_of_a_full_run(self):
        self.store("20261101T100000000Z.json", run("2026-11-01T10:00:00+00:00", score=40))
        self.store("20261102T100000000Z.json",
                   run("2026-11-02T10:00:00+00:00", only=["CI-001"], score=90))
        current = run("2026-11-03T10:00:00+00:00")
        self.assertEqual(checklist_runner.previous_run("e.com", "", like=current)
                         ["scores"]["seo_score"], 40)
        self.assertEqual([r["seo_score"] for r in
                          checklist_runner.run_series("e.com", "", like=current)], [40])

    def test_another_page_is_not_the_baseline_in_page_mode(self):
        self.store("20261101T100000000Z.json",
                   run("2026-11-01T10:00:00+00:00", mode="page",
                       url="https://e.com/a", score=40))
        self.store("20261102T100000000Z.json",
                   run("2026-11-02T10:00:00+00:00", mode="page",
                       url="https://e.com/b", score=90))
        current = run("2026-11-03T10:00:00+00:00", mode="page", url="https://e.com/a")
        self.assertEqual(checklist_runner.previous_run("e.com", "", like=current)
                         ["scores"]["seo_score"], 40)
        self.assertEqual([r["seo_score"] for r in
                          checklist_runner.run_series("e.com", "", like=current)], [40])

    def test_a_streak_does_not_run_through_another_page(self):
        self.store("20261101T100000000Z.json",
                   run("2026-11-01T10:00:00+00:00", mode="page", url="https://e.com/b",
                       items=[("CI-001", FAIL)]))
        current = run("2026-11-03T10:00:00+00:00", mode="page", url="https://e.com/a",
                      items=[("CI-001", FAIL)])
        series = checklist_runner.run_series("e.com", "", like=current)
        self.assertEqual(checklist_runner.open_since(series, current["items"]), [])

    def test_a_list_or_non_utf8_history_file_is_skipped(self):
        self.store("20261101T100000000Z.json", run("2026-11-01T10:00:00+00:00", score=40))
        self.store("20261102T100000000Z.json", [])
        self.store("20261103T100000000Z.json", raw=b'{"domain": "e.com", "x": "\xff"}')
        self.store("20261104T100000000Z.json", {"domain": "e.com", "items": [1]})
        self.store("20261105T100000000Z.json", {"domain": "e.com", "items": "PASS"})
        self.store("20261106T100000000Z.json", {"domain": "e.com", "scores": [90]})
        self.store("20261107T100000000Z.json", {"domain": "e.com", "scoring_tables": "x"})
        self.assertEqual(checklist_runner.previous_run("e.com", "")["scores"]["seo_score"], 40)
        self.assertEqual([r["seo_score"] for r in checklist_runner.run_series("e.com", "")],
                         [40])


class HistoryComparesLikeRunsThroughTheRunner(unittest.TestCase):
    """Codex review 1: the helpers can filter and `main` still not ask them to. One run
    of the runner over stored runs of another page and another selection."""

    def test_the_baseline_and_the_trend_are_this_page_and_selection(self):
        from urllib.parse import urlparse
        page = ("<!doctype html><html><head><title>A page for an audit</title></head>"
                "<body><h1>A page for an audit</h1><p>" + "Useful body copy. " * 80
                + "</p></body></html>")
        launch = ("import os, runpy, sys; os.chdir(sys.argv.pop(1)); "
                  "runpy.run_path(sys.argv.pop(1), run_name='__main__')")
        with tempfile.TemporaryDirectory(prefix="seo-p3-history-") as work, \
                harness.served({"/": page, "/robots.txt": (404, "")}) as site:
            folder = os.path.join(work, ".seo-runs",
                                  checklist_runner.history_folder(urlparse(site.url).netloc))
            os.makedirs(folder)
            same = ["crawling_indexing"]
            for name, started, url, only in (
                    ("a.json", "2020-01-01T00:00:00+00:00", site.url, same),
                    ("b.json", "2021-01-01T00:00:00+00:00", site.url + "other", same),
                    ("c.json", "2022-01-01T00:00:00+00:00", site.url, None)):
                stored = run(started, mode="page", url=url, only=only)
                stored["domain"] = urlparse(site.url).netloc
                with open(os.path.join(folder, name), "w", encoding="utf-8") as fh:
                    json.dump(stored, fh)
            out = os.path.join(work, "out.json")
            proc = harness.spawn(
                [sys.executable, "-c", launch, work,
                 os.path.join(ROOT, "skills", "seo-checklist", "scripts",
                              "checklist_runner.py"),
                 site.url, "--mode", "page", "--only", "crawling_indexing",
                 "--allow-private", "--max-rps", "0", "--no-history", "--no-prompt",
                 "--quiet", "--timeout", "60", "--json", out],
                env=harness.offline_env(), timeout=300)
            self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
            with open(out, encoding="utf-8") as fh:
                payload = json.load(fh)
        self.assertEqual(payload["url"], site.url)
        self.assertEqual(payload["compared_with"]["started_at"], "2020-01-01T00:00:00+00:00")
        self.assertEqual([row["started_at"] for row in payload["history"][:-1]],
                         ["2020-01-01T00:00:00+00:00"], "the last point is this run")


# -- 11: a calibration from an empty corpus -----------------------------------------

class AnEmptyCorpusWritesNothing(Scratch):
    def test_paragraph_words_refuses_an_empty_checkout(self):
        checkout = os.path.join(self.dir, "bench")
        os.makedirs(os.path.join(checkout, ".git"))
        with open(os.path.join(checkout, ".git", "HEAD"), "w") as fh:
            fh.write("0" * 40)
        with open(os.path.join(checkout, "ground-truth.json"), "w") as fh:
            json.dump({"page-1": {"url": "https://e.com/", "articleBody": "x"}}, fh)
        report = os.path.join(self.dir, "paragraph-words.json")
        shutil.copy(paragraphs.REPORT, report)
        with open(report, encoding="utf-8") as fh:
            before = fh.read()
        with mock.patch.object(paragraphs, "REPORT", report), quiet(), \
                mock.patch("sys.stderr", new_callable=io.StringIO), \
                mock.patch.object(sys, "argv", ["calibrate", checkout]):
            self.assertNotEqual(paragraphs.main(), 0)
        with open(report, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), before)

    def test_paragraph_words_check_fails_an_empty_report(self):
        report = os.path.join(self.dir, "paragraph-words.json")
        with open(paragraphs.REPORT, encoding="utf-8") as fh:
            data = json.load(fh)
        data["skipped"] = sorted(str(i) for i in range(len(data["pages"])))
        data["pages"] = []
        data["sweep"] = paragraphs.score([])
        data["selected_cutoff"] = paragraphs.select(data["sweep"])
        data["quarter_short_false_selects"] = paragraphs.sensitivity([])
        with open(report, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        with mock.patch.object(paragraphs, "REPORT", report), quiet(), \
                mock.patch.object(paragraphs, "literal_constants",
                                  return_value={"MIN_PARAGRAPH_WORDS":
                                                data["selected_cutoff"]}):
            self.assertEqual(paragraphs.check(), 1)

    def test_paragraph_words_check_fails_pages_without_paragraphs(self):
        """Codex review 1: every page there and none with a paragraph is no corpus."""
        report = os.path.join(self.dir, "paragraph-words.json")
        with open(paragraphs.REPORT, encoding="utf-8") as fh:
            data = json.load(fh)
        data["pages"] = [[] for _ in data["pages"]]
        data["skipped"] = []
        data["sweep"] = paragraphs.score(data["pages"])
        data["selected_cutoff"] = paragraphs.select(data["sweep"])
        data["quarter_short_false_selects"] = paragraphs.sensitivity(data["pages"])
        with open(report, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        with mock.patch.object(paragraphs, "REPORT", report), quiet(), \
                mock.patch.object(paragraphs, "literal_constants",
                                  return_value={"MIN_PARAGRAPH_WORDS":
                                                data["selected_cutoff"]}):
            self.assertEqual(paragraphs.check(), 1)

    def test_profile_detection_refuses_when_no_site_answered(self):
        report = os.path.join(self.dir, "profile-detection.json")
        shutil.copy(profiles.REPORT, report)
        with open(report, encoding="utf-8") as fh:
            before = fh.read()
        from lib import safe_http
        with mock.patch.object(profiles, "REPORT", report), quiet(), \
                mock.patch("sys.stderr", new_callable=io.StringIO), \
                mock.patch.object(safe_http, "safe_get", side_effect=OSError("offline")), \
                mock.patch.object(sys, "argv", ["calibrate"]):
            self.assertNotEqual(profiles.main(), 0)
        with open(report, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), before)

    def test_profile_detection_check_fails_an_empty_report(self):
        report = os.path.join(self.dir, "profile-detection.json")
        with open(profiles.REPORT, encoding="utf-8") as fh:
            data = json.load(fh)
        data["unread"] += [{"url": s["url"], "label": s["label"], "error": "offline"}
                           for s in data["sites"]]
        data["sites"] = []
        data["sweep"] = profiles.sweep([], data["profile_excludes"])
        data["selected_min_score"] = profiles.select(data["sweep"])
        with open(report, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        with mock.patch.object(profiles, "REPORT", report), quiet():
            self.assertEqual(profiles.check(), 1)


# -- 12: a constant compared with itself ----------------------------------------------

class ACalibratedConstantIsHeldToTheCorpus(Scratch):
    """A re-measure writes the report from the corpus and the live constant. A check
    that compares the constant with a `recommended_value` the measure copied from the
    constant passes every value; these move a constant out of what the stored corpus
    supports and write the report as a re-measure under it would."""

    def font_check(self, constant):
        with open(font.REPORT, encoding="utf-8") as fh:
            data = json.load(fh)
        data["constant"]["value"] = data["constant"]["recommended_value"] = constant
        report = os.path.join(self.dir, "font-weight.json")
        with open(report, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        with mock.patch.object(font, "REPORT", report), \
                mock.patch.object(font, "_offline_constant", return_value=constant), \
                quiet(), mock.patch("sys.stderr", new_callable=io.StringIO):
            return font.check_report()

    def test_a_font_threshold_outside_the_empty_band_fails(self):
        self.assertEqual(self.font_check(500_000), 1)
        self.assertEqual(self.font_check(10_000), 1)

    def test_a_font_threshold_inside_the_empty_band_passes(self):
        self.assertEqual(self.font_check(200_000), 0)

    def css_check(self, name, value, **more):
        """The report a re-measure under `name = value` writes: the classifier's answers
        and every constant's evidence taken under the live values."""
        with open(css.REPORT, encoding="utf-8") as fh:
            data = json.load(fh)
        live = dict(css._offline_constants(), **{name: value}, **more)
        for row in data["files"]:
            row["classifier_minified"] = (
                row["bytes_per_line"] > live["MINIFIED_BYTES_PER_LINE"]
                and row["comment_share"] < live["MINIFIED_COMMENT_SHARE"]
                and row["indented_lines_first_400"] < live["MINIFIED_MAX_INDENTED"])
        with mock.patch.dict(css._RUNTIME, live):
            data["constants"] = css._constant_evidence(data["files"], data["pairs"])
        report = os.path.join(self.dir, "css-minification.json")
        with open(report, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        out = io.StringIO()
        with mock.patch.object(css, "REPORT", report), \
                mock.patch("sys.stdout", out), \
                mock.patch("sys.stderr", new_callable=io.StringIO):
            return css.check_report(live), out.getvalue()

    def test_a_classifier_threshold_the_corpus_rejects_fails(self):
        for name, value in (("MINIFIED_BYTES_PER_LINE", 300),
                            ("MINIFIED_BYTES_PER_LINE", 40),
                            ("MINIFIED_MAX_INDENTED", 2)):
            with self.subTest(name=name, value=value):
                self.assertEqual(self.css_check(name, value)[0], 1)

    def test_two_thresholds_broken_together_fail(self):
        """Codex review 1: each threshold held at the other's broken value read as the
        best that value allows, so both vouched for each other."""
        self.assertEqual(self.css_check("MINIFIED_BYTES_PER_LINE", 1_000_000_000,
                                        MINIFIED_MAX_INDENTED=0)[0], 1)

    def test_the_offline_rule_is_the_classifier_s(self):
        """Codex review 1: `looks_minified` calls a blank stylesheet minified."""
        import css_minify_check
        live = css._offline_constants()
        for text in ("", " \n\t", "a{b:c}", "a {\n  b: c;\n}\n" * 30,
                     "/* x */" * 400 + "a{b:c}", "a{b:c}" * 200):
            with self.subTest(text=text[:20]):
                ratio, comments, indented = css_minify_check.minification_signals(text)
                row = {"bytes_per_line": ratio, "comment_share": comments,
                       "indented_lines_first_400": indented}
                self.assertEqual(css._reads_minified(row, live),
                                 css_minify_check.looks_minified(text)[0])

    def test_a_report_edited_by_hand_fails(self):
        """GOV-10's other direction: the stored evidence follows from the stored rows."""
        with open(css.REPORT, encoding="utf-8") as fh:
            data = json.load(fh)
        data["constants"]["MINIFIED_MAX_INDENTED"]["classifier_misreads"]["fewest"] = 99
        report = os.path.join(self.dir, "css-minification.json")
        with open(report, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        with mock.patch.object(css, "REPORT", report), quiet(), \
                mock.patch("sys.stderr", new_callable=io.StringIO):
            self.assertEqual(css.check_report(css._offline_constants()), 1)
        with open(font.REPORT, encoding="utf-8") as fh:
            data = json.load(fh)
        data["constant"]["empty_band"] = [1, 2]
        report = os.path.join(self.dir, "font-weight.json")
        with open(report, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        with mock.patch.object(font, "REPORT", report), quiet(), \
                mock.patch("sys.stderr", new_callable=io.StringIO):
            self.assertEqual(font.check_report(), 1)

    def test_a_retained_constant_does_not_claim_the_corpus_chose_it(self):
        for name in ("MINIFIED_COMMENT_SHARE", "WASTED_BYTES_WARN", "SMALL_FILE_BYTES"):
            with self.subTest(name=name):
                code, out = self.css_check(name, 7)
                line = next(ln for ln in out.splitlines() if ln.startswith(name + ":"))
                self.assertNotIn("corpus=7", line)
                self.assertNotIn("agree=yes", line)


# -- 17: scores_with twins ------------------------------------------------------------

class SensitivityLeavesTwinsOut(unittest.TestCase):
    def rows(self):
        def item(id_, status, severity, **extra):
            return {"id": id_, "status": status, "severity": severity, "effort": "low",
                    "title": id_, "category": "c", "category_label": "C", **extra}
        return [item("A-1", PASS, "critical"),
                item("A-2", FAIL, "low"),
                item("A-3", FAIL, "low", scores_with="A-2"),
                item("A-4", WARN, "high")]

    def test_the_headline_matches_the_runner_with_a_twin(self):
        from checklist_runner import SEVERITY_WEIGHT, score
        items = self.rows()
        self.assertEqual(round(sens.headline(sens.scored_items({"items": items}),
                                             SEVERITY_WEIGHT)),
                         score(items)["seo_score"])

    def test_the_fix_list_names_a_twin_once(self):
        from checklist_report import EFFORT_COST, plan_order
        from checklist_runner import SEVERITY_WEIGHT
        items = sens.scored_items({"items": self.rows()})
        self.assertEqual(sens.fix_order(items, SEVERITY_WEIGHT, EFFORT_COST),
                         [i["id"] for i in plan_order(self.rows())])

    def test_a_run_whose_only_decided_rows_are_twins_is_skipped(self):
        """Codex review 1: no weighed row means no headline, not a crash."""
        twin = self.rows()[2]
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "twins.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"items": [twin]}, fh)
            with quiet() as out:
                self.assertEqual(sens.report([path]), 1)
        self.assertIn("only scores_with twins", out.getvalue())

    def test_pass_rates_count_what_the_weights_act_on(self):
        rates = sens.pass_rates(sens.scored_items({"items": self.rows()}))
        self.assertEqual(rates["low"], (1, 0.0))


# -- 18: verify-feature.sh ------------------------------------------------------------

class VerifyFeatureWritesOnlyWhatPassed(Scratch):
    SCRIPT = os.path.join(ROOT, "scripts", "verify-feature.sh")

    def feature_list(self, feature, folder=None):
        path = os.path.join(folder or self.dir, "feature_list.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump([{"id": "F99", "state": "active", "behavior": "b", **feature}], fh)
        return path

    def run_script(self, path, env=None):
        return subprocess.run([shutil.which("bash"), self.SCRIPT, "F99", path],
                              capture_output=True, text=True, encoding="utf-8",
                              close_fds=False,
                              env=dict(env or os.environ, PYTHONIOENCODING="utf-8"))

    def state(self, path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)[0]["state"]

    def test_a_blank_command_does_not_pass(self):
        for feature in ({"verification": ""}, {"verification": "   "},
                        {"layers": [{"label": "L1", "cmd": ""}]},
                        {"layers": [{"label": "L1", "cmd": "true"},
                                    {"label": "L2", "cmd": " \t"}]},
                        {"layers": [{"label": "L1"}]}):
            with self.subTest(feature=feature):
                path = self.feature_list(feature)
                result = self.run_script(path)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertEqual(self.state(path), "active")

    def test_a_real_command_still_passes(self):
        path = self.feature_list({"layers": [{"label": "L1", "cmd": "true"}]})
        result = self.run_script(path)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.state(path), "passing")

    def test_an_unwritable_state_is_not_reported_as_passing(self):
        folder = os.path.join(self.dir, "locked")
        os.makedirs(folder)
        path = self.feature_list({"verification": "true"}, folder)
        os.chmod(folder, 0o555)
        self.addCleanup(os.chmod, folder, 0o755)
        result = self.run_script(path)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertNotIn("now passing", result.stdout)
        self.assertEqual(self.state(path), "active")

    def test_a_failed_jq_write_is_not_reported_as_passing(self):
        real = shutil.which("jq")
        bin_dir = os.path.join(self.dir, "bin")
        os.makedirs(bin_dir)
        shim = os.path.join(bin_dir, "jq")
        with open(shim, "w") as fh:
            fh.write('#!/bin/sh\ncase "$*" in *map\\(*) exit 3;; esac\n'
                     f'exec "{real}" "$@"\n')
        os.chmod(shim, 0o755)
        path = self.feature_list({"verification": "true"})
        env = dict(os.environ, PATH=bin_dir + os.pathsep + os.environ["PATH"])
        result = self.run_script(path, env)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertNotIn("now passing", result.stdout)
        self.assertEqual(self.state(path), "active")


# -- 19: corpus_fetch caches an error page ----------------------------------------------

class Answer:
    def __init__(self, status, content):
        self.status_code, self.content = status, content


def tarball():
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        data = b"a{}"
        info = tarfile.TarInfo("package/a.css")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class CorpusFetchCachesOnlyATarball(Scratch):
    def fetch(self, answer):
        from lib import safe_http
        with mock.patch.object(safe_http, "safe_get", return_value=answer), \
                mock.patch("sys.stderr", new_callable=io.StringIO):
            return corpus_fetch.fetch_package("pkg", "1.0.0", lambda _p: True,
                                              cache_dir=self.dir)

    def cached(self):
        return os.listdir(self.dir)

    def test_an_error_page_is_not_cached(self):
        for answer in (Answer(404, b"<html>Not found</html>"),
                       Answer(503, gzip.compress(b"busy")),
                       Answer(200, b"<html>captive portal</html>")):
            with self.subTest(status=answer.status_code):
                with self.assertRaises(RuntimeError):
                    self.fetch(answer)
                self.assertEqual(self.cached(), [])

    def test_an_error_page_cached_before_the_fix_is_fetched_again(self):
        """Codex review 1: a cache an earlier version poisoned stayed poisoned."""
        with open(os.path.join(self.dir, "pkg-1.0.0.tgz"), "wb") as fh:
            fh.write(b"<html>Not found</html>")
        _manifest, files = self.fetch(Answer(200, tarball()))
        self.assertEqual(files, {"package/a.css": b"a{}"})

    def test_a_tarball_is_cached_and_read_back(self):
        manifest, files = self.fetch(Answer(200, tarball()))
        self.assertEqual(files, {"package/a.css": b"a{}"})
        self.assertEqual(len(self.cached()), 1)
        again, _ = corpus_fetch.fetch_package("pkg", "1.0.0", lambda _p: True,
                                              cache_dir=self.dir)
        self.assertEqual(again["sha256"], manifest["sha256"])


if __name__ == "__main__":
    unittest.main()
