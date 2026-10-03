"""A registry hash alone cannot identify the checks that produced a run."""
import copy
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest import mock
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "seo-checklist" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import harness  # noqa: E402
import checklist_report as report  # noqa: E402
import checklist_runner as runner  # noqa: E402


def shipped_version():
    return json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(
        encoding="utf-8"))["version"]


def results(**extra):
    data = {"url": "https://example.com/", "domain": "example.com",
            "mode": "live", "profile": "default", "items": [], "runs": {},
            "scores": runner.score([]), "entry_reachable": True,
            "registry_version": "registry-a"}
    data.update(extra)
    return data


class PluginVersionRead(unittest.TestCase):
    def read(self, content):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "plugin.json"
            if content is not None:
                path.write_text(content, encoding="utf-8")
            with mock.patch.object(runner, "PLUGIN_JSON", str(path), create=True):
                return runner.plugin_version()

    def test_missing_file_is_unknown(self):
        self.assertEqual(self.read(None), "unknown")

    def test_unreadable_file_is_unknown(self):
        with mock.patch("builtins.open", side_effect=PermissionError("unreadable")):
            self.assertEqual(runner.plugin_version(), "unknown")

    def test_invalid_json_is_unknown(self):
        self.assertEqual(self.read("{broken"), "unknown")

    def test_empty_version_is_unknown(self):
        self.assertEqual(self.read('{"version": ""}'), "unknown")

    def test_numeric_version_is_unknown(self):
        self.assertEqual(self.read('{"version": 3}'), "unknown")

    def test_missing_version_and_non_object_json_are_unknown(self):
        for content in ("{}", "[]", "null", '"text"', "3"):
            with self.subTest(content=content):
                self.assertEqual(self.read(content), "unknown")

    def test_invalid_utf8_is_unknown(self):
        with mock.patch("builtins.open", side_effect=UnicodeDecodeError(
                "utf-8", b"\xff", 0, 1, "invalid")):
            self.assertEqual(runner.plugin_version(), "unknown")

    def test_the_manifest_is_read_on_each_call(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "plugin.json"
            with mock.patch.object(runner, "PLUGIN_JSON", str(path), create=True):
                for version in ("first-version", "second-version"):
                    path.write_text(json.dumps({"version": version}), encoding="utf-8")
                    self.assertEqual(runner.plugin_version(), version)

    def test_the_path_resolves_to_the_plugin_root(self):
        self.assertEqual(Path(runner.PLUGIN_JSON).resolve(),
                         ROOT / ".claude-plugin" / "plugin.json")
        self.assertEqual(runner.plugin_version(), shipped_version())


class PluginComparison(unittest.TestCase):
    def note(self, prev, cur):
        changes, note = runner.diff_runs(results(**prev), results(**cur))
        self.assertEqual(changes, [])
        return note

    def test_different_plugins_explain_changes_with_an_unchanged_registry(self):
        self.assertEqual(self.note({"plugin_version": "before"},
                                   {"plugin_version": "after"}),
                         "previous run was made by plugin before, this one by after; "
                         "a check can change between plugin versions while the registry "
                         "stays the same, so differences may be changes to the checks "
                         "rather than to the site. ")

    def test_a_legacy_previous_run_is_identified_as_unrecorded(self):
        self.assertEqual(self.note({}, {"plugin_version": "after"}),
                         "previous run does not record which plugin version made it, "
                         "this one was made by after; differences may be changes to the "
                         "checks rather than to the site. ")

    def test_equal_plugins_and_equal_registries_have_no_reason(self):
        self.assertEqual(self.note({"plugin_version": "same"},
                                   {"plugin_version": "same"}), "")

    def test_a_current_run_without_a_version_has_no_plugin_reason(self):
        for cur in ({}, {"plugin_version": None}, {"plugin_version": ""}):
            with self.subTest(current=cur):
                self.assertEqual(self.note({"plugin_version": "before"}, cur), "")

    def test_both_absent_have_no_reason(self):
        self.assertEqual(self.note({}, {}), "")

    def test_both_moved_produce_two_sentences_once_in_order(self):
        note = self.note({"plugin_version": "before", "registry_version": "old"},
                         {"plugin_version": "after", "registry_version": "new"})
        sentences = [s for s in note.split(". ") if s]
        self.assertEqual(len(sentences), 2)
        self.assertEqual(note.count("previous run used registry"), 1)
        self.assertEqual(note.count("previous run was made by plugin"), 1)
        self.assertTrue(sentences[0].startswith("previous run used registry old"))
        self.assertTrue(sentences[1].startswith("previous run was made by plugin before"))

    def test_equal_plugins_leave_only_the_registry_reason(self):
        note = self.note({"plugin_version": "same", "registry_version": "old"},
                         {"plugin_version": "same", "registry_version": "new"})
        self.assertIn("previous run used registry", note)
        self.assertNotIn("plugin", note)


class PluginReport(unittest.TestCase):
    def test_markdown_names_the_payload_version_directly_after_registry(self):
        text = report.render_markdown(results(plugin_version="archived-version"))
        self.assertIn("- **Registry:** `registry-a`\n"
                      "- **Plugin:** `archived-version`", text)

    def test_html_names_the_payload_version_beside_registry(self):
        text = report.render_html(results(plugin_version="archived-version"))
        self.assertIn("<code>registry-a</code> &middot; Plugin "
                      "<code>archived-version</code>", text)

    def test_html_escapes_the_payload_version(self):
        text = report.render_html(results(plugin_version='<old&"version>'))
        self.assertIn("<code>&lt;old&amp;&quot;version&gt;</code>", text)

    def test_numeric_payload_version_renders_on_both_surfaces(self):
        data = results(plugin_version=3)
        self.assertIn("- **Plugin:** `3`", report.render_markdown(data))
        self.assertIn("Plugin <code>3</code>", report.render_html(data))

    def test_old_results_render_unknown_on_both_surfaces(self):
        for data in (results(), results(plugin_version=None), results(plugin_version="")):
            with self.subTest(version=data.get("plugin_version")):
                self.assertIn("- **Plugin:** `unknown`", report.render_markdown(data))
                self.assertIn("Plugin <code>unknown</code>", report.render_html(data))
                self.assertNotIn("None", report.render_markdown(data))
                self.assertNotIn("None", report.render_html(data))

    def test_russian_names_the_plugin_on_both_surfaces(self):
        data = results(plugin_version="archived-version")
        lang = report.Lang("ru")
        self.assertIn("- **\u041f\u043b\u0430\u0433\u0438\u043d:** `archived-version`",
                      report.render_markdown(data, lang))
        self.assertIn("\u041f\u043b\u0430\u0433\u0438\u043d <code>archived-version</code>",
                      report.render_html(data, lang))


class PluginRunRecord(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.TemporaryDirectory(prefix="seo-plugin-version-")
        cls.addClassCleanup(cls.work.cleanup)
        launch = ("import os, runpy, sys; os.chdir(sys.argv.pop(1)); "
                  "runpy.run_path(sys.argv.pop(1), run_name='__main__')")
        page = ("<!doctype html><html><head><title>A page for an audit</title></head>"
                "<body><h1>A page for an audit</h1><p>" + "Useful body copy. " * 80
                + "</p></body></html>")
        with harness.served({"/": page, "/robots.txt": (404, "")}) as site:
            domain = urlparse(site.url).netloc
            folder = Path(cls.work.name) / ".seo-runs" / runner.history_folder(domain)
            folder.mkdir(parents=True)
            baseline = results(domain=domain, url=site.url,
                               started_at="2020-01-01T00:00:00+00:00",
                               plugin_version="archived-plugin")
            stored = folder / "baseline.json"
            stored.write_text(json.dumps(baseline), encoding="utf-8")
            cls.payloads = []
            for name in ("recorded", "legacy"):
                if name == "legacy":
                    # Both runs compare against the same stored baseline, with its
                    # version removed for the second; no wall-clock ordering guess.
                    baseline.pop("plugin_version")
                    stored.write_text(json.dumps(baseline), encoding="utf-8")
                out = Path(cls.work.name) / f"{name}.json"
                proc = harness.spawn(
                    [sys.executable, "-c", launch, cls.work.name,
                     str(SCRIPTS / "checklist_runner.py"), site.url,
                     "--allow-private", "--max-rps", "0", "--no-history",
                     "--no-prompt", "--quiet", "--only", "crawling_indexing",
                     "--timeout", "60", "--json", str(out)],
                    env=harness.offline_env(), timeout=300)
                if proc.returncode:
                    raise AssertionError(f"audit exited {proc.returncode}\n{proc.stderr}")
                cls.payloads.append(json.loads(out.read_text(encoding="utf-8")))

    def test_the_payload_version_is_the_shipped_manifest_and_pyproject_version(self):
        expected = shipped_version()
        project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        version = re.search(r'^version = "([^"]+)"', project, re.M)
        self.assertIsNotNone(version)
        self.assertEqual(expected, version.group(1))
        self.assertEqual(self.payloads[0]["plugin_version"], expected)

    def test_the_real_run_version_reaches_markdown_and_html(self):
        data = self.payloads[0]
        expected = shipped_version()
        self.assertIn(f"- **Plugin:** `{expected}`", report.render_markdown(data))
        self.assertIn(f"Plugin <code>{expected}</code>", report.render_html(data))

    def test_history_keeps_each_run_version_and_the_current_version(self):
        history = self.payloads[0]["history"]
        self.assertEqual(history[0]["plugin_version"], "archived-plugin")
        self.assertEqual(history[-1]["plugin_version"], shipped_version())
        self.assertTrue(history[-1]["current"])

    def test_compared_with_keeps_the_baseline_version(self):
        self.assertEqual(self.payloads[0]["compared_with"]["plugin_version"],
                         "archived-plugin")

    def test_a_stored_legacy_run_carries_none_in_history_and_compared_with(self):
        data = self.payloads[1]
        self.assertIsNone(data["history"][0]["plugin_version"])
        self.assertIsNone(data["compared_with"]["plugin_version"])
        old = copy.deepcopy(data)
        old.pop("plugin_version", None)
        self.assertIn("- **Plugin:** `unknown`", report.render_markdown(old))
        self.assertIn("Plugin <code>unknown</code>", report.render_html(old))


if __name__ == "__main__":
    unittest.main()
