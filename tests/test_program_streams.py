"""A program writes UTF-8 to a pipe, whatever codepage the machine it is started on has.

`scripts/lib/utf8_streams.py` says what was measured and why. The runner tells the
scripts it starts what to write; somebody who starts one by hand tells it nothing, and
on Windows a pipe or a file then gets the machine's ANSI codepage. Thirteen programs
died of their own `--help` under two of the fourteen such codepages, and none under the
one this is developed on, so nothing here had seen it.

This holds the outcome and not a spelling: every file with a `__main__` guard in
`scripts/`, `scripts/lib/` and `tools/` is started, in an environment that names ASCII
for its streams, and asked what its streams write once it has got as far as its
argument parser. A program that names UTF-8 when it is imported and one that names it
under its guard both pass; one that names nothing says `ascii`.
"""
from __future__ import annotations

import ast
from concurrent.futures import ThreadPoolExecutor
import io
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(ROOT, "skills", "seo-checklist")
sys.path.insert(0, os.path.join(SKILL, "scripts"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness  # noqa: E402
from lib.utf8_streams import utf8_streams  # noqa: E402

# Started as `python <program> --help` would start it — its own directory first on the
# path, its name `__main__` — and stopped where the parser prints its help and leaves.
# What the streams write by then goes to a file: nothing of the child's is read
# through a pipe, so nothing here depends on how this side would have decoded it.
STARTED = r"""
import os, runpy, sys
program, answer = sys.argv[1], sys.argv[2]
sys.argv = [program, "--help"]
sys.path.insert(0, os.path.dirname(program))
said = ""
try:
    runpy.run_path(program, run_name="__main__")
except SystemExit:
    pass
except BaseException as error:
    said = " " + type(error).__name__
with open(answer, "w", encoding="utf-8") as f:
    f.write(f"{sys.stdout.encoding} {sys.stderr.encoding}{said}")
"""


def programs() -> list[str]:
    """Every file under the plugin that somebody can start: it has a `__main__` guard."""
    found = []
    for folder in ("scripts", os.path.join("scripts", "lib"), "tools"):
        for entry in sorted(os.listdir(os.path.join(SKILL, folder))):
            path = os.path.join(SKILL, folder, entry)
            if not entry.endswith(".py"):
                continue
            with open(path, encoding="utf-8") as f:
                tree = ast.parse(f.read())
            if any(isinstance(node, ast.If) and "__name__" in ast.unparse(node.test)
                   for node in tree.body):
                found.append(path)
    return found


class AProgramWritesUtf8WhateverTheMachine(unittest.TestCase):

    def started(self, program: str) -> str:
        answer = os.path.join(self.folder, os.path.basename(program) + ".txt")
        subprocess.run([sys.executable, "-c", STARTED, program, answer],
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, close_fds=False, timeout=180,
                       env=dict(harness.with_tripwire(harness.offline_env()),
                                PYTHONIOENCODING="ascii"))
        if not os.path.exists(answer):
            return "it did not get as far as answering"
        with open(answer, encoding="utf-8") as f:
            return f.read()

    def test_every_program_names_utf8_for_its_streams_when_it_is_started(self):
        every = programs()
        self.assertGreater(len(every), 70, "the scan found almost no program")
        with tempfile.TemporaryDirectory(prefix="seo-streams-") as self.folder:
            with ThreadPoolExecutor(max_workers=8) as pool:
                answers = list(pool.map(self.started, every))
        bad = {os.path.relpath(program, SKILL).replace(os.sep, "/"): answer
               for program, answer in zip(every, answers, strict=True)
               if answer != "utf-8 utf-8"}
        self.assertEqual(bad, {}, "started with an environment that names ASCII, these "
                                  "still write it: call `utf8_streams()` first under "
                                  '`if __name__ == "__main__":`')

    def test_the_control_names_nothing_and_writes_what_the_environment_says(self):
        """Without this the test above could pass because the question is asked
        wrongly: a program that names nothing has to be seen answering `ascii`."""
        with tempfile.TemporaryDirectory(prefix="seo-streams-") as self.folder:
            silent = os.path.join(self.folder, "silent.py")
            with open(silent, "w", encoding="utf-8") as f:
                f.write("import argparse\n"
                        "if __name__ == '__main__':\n"
                        "    argparse.ArgumentParser().parse_args()\n")
            self.assertEqual(self.started(silent), "ascii ascii")

    def test_a_stream_that_cannot_be_told_is_left_alone(self):
        """`pythonw` has no stdout at all, and a caller may have put anything there."""
        for stand_in in (None, io.StringIO(), object()):
            with self.subTest(stream=type(stand_in).__name__):
                with mock.patch.object(sys, "stdout", stand_in), \
                        mock.patch.object(sys, "stderr", stand_in):
                    utf8_streams()

    def test_the_tools_have_the_scripts_function_and_not_one_of_their_own(self):
        done = harness.spawn([sys.executable, "-c",
                              "import sys; sys.path.insert(0, sys.argv[1]); import utf8_streams; "
                              "print(utf8_streams.utf8_streams.__code__.co_filename)",
                              os.path.join(SKILL, "tools")])
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(os.path.normcase(os.path.realpath(done.stdout.strip())),
                         os.path.normcase(os.path.realpath(
                             os.path.join(SKILL, "scripts", "lib", "utf8_streams.py"))))


if __name__ == "__main__":
    unittest.main()
