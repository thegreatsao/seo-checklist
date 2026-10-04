"""Saved pages and network sources retain the same body, URL and metadata."""
from pathlib import Path
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/seo-checklist/scripts"))
import seo_common as common


class SourceLoading(unittest.TestCase):
    def test_files_hosts_urls_and_filesystem_errors(self):
        previous = os.getcwd()
        with tempfile.TemporaryDirectory() as directory:
            os.chdir(directory)
            try:
                Path("archive.dir").mkdir()
                body = "<html>\u03b1\u0142</html>\r\nsecond line\r"
                expected_body = body.replace("\r\n", "\n").replace("\r", "\n")
                for source in ("page", "page.html", "existing.test", "archive.dir/page.html"):
                    Path(source).write_bytes(body.encode("utf-8"))
                    expected = (expected_body, "", {"url": source, "status": None,
                                                   "headers": {}, "error": None})
                    with self.subTest(file=source), mock.patch.object(common, "fetch_url") as fetch:
                        self.assertEqual(common.load_source(source, timeout=7), expected)
                        self.assertEqual(common.load_html(source, timeout=7), expected)
                        fetch.assert_not_called()
                for source in ("bare.test", "https://bare.test/page", "bare.test/page.html",
                               "missing.html", "archive.dir"):
                    if source == "bare.test/page.html":
                        with self.assertRaises(FileNotFoundError):
                            common.load_source(source)
                        continue
                    for metadata in ({"text": "network body", "url": "https://final.test/",
                                      "status": 200, "headers": {"x": "y"}, "error": None},
                                     {"text": "", "url": "", "error": "refused"}):
                        expected = (metadata["text"], metadata["url"] or common.normalize_url(source),
                                    metadata)
                        for load in (common.load_source, common.load_html):
                            with self.subTest(source=source, load=load.__name__), mock.patch.object(
                                    common, "fetch_url", return_value=metadata) as fetch:
                                self.assertEqual(load(source, timeout=7), expected)
                                fetch.assert_called_once_with(source, timeout=7)
                Path("invalid").write_bytes(b"\xff")
                for source in ("missing", "./archive.dir", "invalid"):
                    errors = []
                    for load in (common.load_source, common.load_html):
                        try:
                            load(source)
                        except (OSError, UnicodeError) as error:
                            errors.append((type(error), error.args))
                    self.assertEqual(len(errors), 2, source)
                    self.assertEqual(errors[0], errors[1], source)
                with mock.patch.object(Path, "is_file", side_effect=PermissionError("stat denied")):
                    for load in (common.load_source, common.load_html):
                        with self.assertRaisesRegex(PermissionError, "stat denied"):
                            load("page.html")
            finally:
                os.chdir(previous)


if __name__ == "__main__":
    unittest.main()
