"""The calibration tools reproduce their committed reports without rewriting them."""
import importlib
import json
import os
import subprocess
import tempfile
import sys
import unittest
from unittest import mock

TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "skills", "seo-checklist", "tools")


class CalibrationReports(unittest.TestCase):
    def test_each_report_still_matches_its_measurement(self):
        for name in ("css_minification", "font_weight", "gsc_sample_floors", "serp_length"):
            with self.subTest(tool=name):
                result = subprocess.run(
                    [sys.executable, os.path.join(TOOLS, f"calibrate_{name}.py"), "--check"],
                    capture_output=True, text=True, encoding="utf-8", close_fds=False,
                    env=dict(os.environ, PYTHONIOENCODING="utf-8"))
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_literal_readers_preserve_values_duplicates_and_errors(self):
        sys.path.insert(0, TOOLS)
        for name, script, reader, wanted, error, first in (
            ("css_minification", "css_minify_check.py", "_offline_constants", None,
             "could not read classifier constants: {missing}", False),
            ("serp_length", "article_seo.py", "_offline_constants", None,
             "could not read SERP constants: {missing}", False),
            ("font_weight", "font_audit.py", "_offline_constant", {"LARGE_FONT_BYTES"},
             "could not read LARGE_FONT_BYTES", True),
            ("gsc_sample_floors", "fixture.py", "_literal_constants", {"A", "B"},
             "could not read fixture.py constants: {missing}", False),
        ):
            tool = importlib.import_module("calibrate_" + name)
            wanted = set(tool.CONSTANT_NAMES) if wanted is None else wanted
            names = sorted(wanted)
            call = getattr(tool, reader)
            args = (script, wanted) if name == "gsc_sample_floors" else ()
            with self.subTest(tool=name), tempfile.TemporaryDirectory() as tmp, \
                    mock.patch.object(tool, "SCRIPTS", tmp):
                path = os.path.join(tmp, script)
                def source(text, path=path):
                    with open(path, "w", encoding="utf-8") as stream:
                        stream.write(text)
                source("\n".join(f"{key} = {i + 1}" for i, key in enumerate(names))
                       + f"\n{names[0]} = 99\nIGNORED = object()\n"
                       + f"def nested():\n    {names[0]} = 200\n")
                expected = {key: i + 1 for i, key in enumerate(names)}
                if not first:
                    expected[names[0]] = 99
                self.assertEqual(call(*args), expected[names[0]] if first else expected)
                source("\n".join(f"{key}: int = 1" for key in names)
                       + "\n" + " = ".join(names + ["ALSO", "2"]))
                with self.assertRaises(RuntimeError) as caught:
                    call(*args)
                self.assertEqual(str(caught.exception), error.format(missing=names))
                source(f"{names[0]} = object()")
                with self.assertRaises(ValueError):
                    call(*args)
                if first:
                    source(f"{names[0]} = 1\n{names[0]} = object()")
                    self.assertEqual(call(), 1)

    def test_offline_checks_load_no_runtime_scripts(self):
        for name in ("css_minification", "font_weight", "gsc_sample_floors", "serp_length"):
            with self.subTest(tool=name):
                program = (
                    "import contextlib,io,json,pathlib,runpy,sys; "
                    "path=pathlib.Path(sys.argv[1]); sys.path.insert(0,str(path.parent)); "
                    "sys.argv=[str(path),'--check']; "
                    "tool=runpy.run_path(str(path)); "
                    "buffer=io.StringIO(); "
                    "\nwith contextlib.redirect_stdout(buffer): status=tool['main']()\n"
                    "scripts=path.parent.parent/'scripts'; "
                    "loaded=[n for n,m in sys.modules.items() "
                    "if getattr(m,'__file__',None) and scripts in "
                    "pathlib.Path(m.__file__).resolve().parents]; "
                    "print(json.dumps({'status':status,'runtime':loaded}))"
                )
                result = subprocess.run(
                    [sys.executable, "-c", program,
                     os.path.join(TOOLS, f"calibrate_{name}.py")],
                    capture_output=True, text=True, encoding="utf-8", close_fds=False,
                    env=dict(os.environ, PYTHONIOENCODING="utf-8"))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout), {"status": 0, "runtime": []})

    def test_percentiles_reproduce_rounded_corpus_reports(self):
        sys.path.insert(0, TOOLS)
        import calibrate_css_minification as css
        import calibrate_font_weight as font
        for tool in (css, font):
            with self.subTest(tool=tool.__name__):
                with self.assertRaisesRegex(ValueError,
                                            "a distribution cannot be computed from no observations"):
                    tool._percentile([], 0.5)
                self.assertEqual(tool._percentile([7], 0.9), 7.0)
                self.assertEqual([tool._percentile([30, 10, 20], f)
                                  for f in (0, 0.1, 0.5, 0.9, 1)], [10, 12, 20, 28, 30])
                with open(tool.REPORT, encoding="utf-8") as stream:
                    expected = json.load(stream)
                def measure(spec, expected=expected, tool=tool):
                    package = spec["package"]
                    manifest = next(row for row in expected["manifest"]
                                    if row["package"] == package)
                    files = [row for row in expected["files"] if row["package"] == package]
                    if tool is font:
                        return dict(manifest), files
                    pairs = [row for row in expected["pairs"] if row["package"] == package]
                    return dict(manifest), files, pairs
                with mock.patch.object(tool, "_measure_package", side_effect=measure):
                    if tool is css:
                        with mock.patch.dict(css._RUNTIME, css._offline_constants(), clear=True):
                            actual = tool.build_report()
                    else:
                        actual = tool.build_report()
                actual["generated"] = expected["generated"]
                self.assertEqual(actual, expected)

    def test_archive_display_paths_are_kept_in_emitted_measurements(self):
        sys.path.insert(0, TOOLS)
        import calibrate_css_minification as css
        import calibrate_font_weight as font
        for tool in (css, font):
            for package in ("pkg", "@scope/pkg"):
                for member, suffix in (("package/assets/a", "assets/a"),
                                       ("assets/a", "assets/a"), ("package", ""), ("", ""),
                                       ("package/package/a", "package/a"),
                                       ("/package/a", "/package/a")):
                    with self.subTest(tool=tool.__name__, package=package, member=member):
                        expected = "/package/a" if suffix.startswith("/") else (
                            "pkg-1.0/" + suffix if suffix else "pkg-1.0")
                        self.assertEqual(tool._display_path(package, "1.0", member), expected)
                raw = ({"package/assets/a.css": b"source source source",
                        "package/assets/a.min.css": b"min"} if tool is css else
                       {"package/assets/a.woff2": b"font"})
                fetched = ({"sha256": "hash", "file_count": len(raw)}, raw)
                spec = {"package": package, "version": "1.0", "group": "A", "arm": "A"}
                with mock.patch.object(tool, "fetch_package", return_value=fetched), \
                        mock.patch.dict(css._RUNTIME, {
                            "looks_minified": lambda text: (text == "min", 10),
                            "minification_signals": lambda text: (10, 0, 0)}, clear=True):
                    measured = tool._measure_package(spec)
                self.assertEqual([row["path"] for row in measured[1]],
                                 ["pkg-1.0/" + name.removeprefix("package/")
                                  for name in sorted(raw)])
                if tool is css:
                    self.assertEqual(measured[2][0]["source"], "pkg-1.0/assets/a.css")
                    self.assertEqual(measured[2][0]["minified"], "pkg-1.0/assets/a.min.css")


if __name__ == "__main__":
    unittest.main()
