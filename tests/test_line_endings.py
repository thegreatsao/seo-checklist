"""Every tracked text file is stored with LF line endings.

0.110.0 shipped `CHANGELOG.md` with two lines ending `\\r\\r\\n`, written by a release
script that turned `\\n` into `\\r\\n` over text that already carried `\\r\\n`. A lone
carriage return is enough for git to classify a file as binary, and a binary file is not
normalised on commit: the whole changelog went into the repository as CRLF, and the
release's diff reported 16,000 changed lines for 40 written. Nothing reddened, because
nothing read how a file is stored. `git ls-files --eol` says it, and this reads that.
"""
from __future__ import annotations

import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "seo-checklist", "tools"))

import ci_local  # noqa: E402

# Binary by nature, not by accident: images and a gzip fixture. Named by extension so a
# new text file cannot hide here, and an empty file (`i/none`) has no line ending to have.
BINARY_SUFFIXES = (".png", ".webp", ".jpg", ".jpeg", ".gif", ".ico", ".avif", ".gz",
                   ".woff", ".woff2", ".ttf", ".pdf", ".zip", ".xlsx")


class EveryTextFileIsStoredWithLF(unittest.TestCase):
    def test_no_tracked_text_file_is_stored_as_crlf_or_as_binary(self):
        listed = subprocess.run(
            [ci_local.resolve("git"), "-C", ROOT, "ls-files", "--eol"],
            capture_output=True, text=True, encoding="utf-8", close_fds=False)
        self.assertEqual(listed.returncode, 0, listed.stderr)
        rows = [line.split("\t", 1) for line in listed.stdout.splitlines() if line]
        self.assertTrue(rows, "git listed no files, so nothing here was checked")
        wrong = []
        for info, path in rows:
            index_eol = info.split()[0]
            if index_eol in ("i/lf", "i/none") or path.lower().endswith(BINARY_SUFFIXES):
                continue
            wrong.append(f"{path} ({index_eol})")
        self.assertEqual(wrong, [], "stored with something other than LF — `i/-text` "
                                    "means git read a stray carriage return as binary")


if __name__ == "__main__":
    unittest.main()
