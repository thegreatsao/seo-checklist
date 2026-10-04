"""URL-list inputs keep their first normalized occurrence."""
import os
from pathlib import Path
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/seo-checklist/scripts"
sys.path.insert(0, str(SCRIPTS))

from seo_common import read_urls


class URLInputs(unittest.TestCase):
    def test_values_and_file_share_normalization_and_order(self):
        with tempfile.TemporaryDirectory() as work:
            path = os.path.join(work, "urls.txt")
            Path(path).write_text("# ignored\n  # ignored too\n\nhttps://e.test/a\ne.test/b\n",
                                  encoding="utf-8")
            self.assertEqual(read_urls([" e.test/a ", "", None, "https://e.test/a"], path),
                             ["https://e.test/a", "https://e.test/b"])
        self.assertEqual(read_urls(), [])
        self.assertEqual(read_urls([]), [])


if __name__ == "__main__":
    unittest.main()
