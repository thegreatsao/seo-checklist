"""The suite leaves nothing in the machine's temporary directory.

`tests/harness.py` `SUITE_TEMP` says what was measured and why. This holds what has to
stay true of it: this process and a child it starts both call that directory the
temporary one, and when a process that imported the harness ends, the directory and
whatever was put in it are gone.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import harness  # noqa: E402


def same(first: str, second: str) -> bool:
    """One directory, however each side spells it: a runner's short name, a symlink."""
    return os.path.realpath(first) == os.path.realpath(second)


class TheSuiteHasATemporaryDirectoryOfItsOwn(unittest.TestCase):

    def test_this_process_calls_it_the_temporary_directory(self):
        self.assertTrue(os.path.isdir(harness.SUITE_TEMP))
        self.assertTrue(same(tempfile.gettempdir(), harness.SUITE_TEMP))
        made = tempfile.mkdtemp()
        self.assertTrue(same(os.path.dirname(made), harness.SUITE_TEMP), made)

    def test_a_child_calls_it_the_temporary_directory_too(self):
        child = harness.spawn([sys.executable, "-c",
                               "import tempfile; print(tempfile.gettempdir())"])
        self.assertEqual(child.returncode, 0, child.stderr)
        self.assertTrue(same(child.stdout.strip(), harness.SUITE_TEMP), child.stdout)

    def test_it_is_gone_when_the_process_ends(self):
        """A second process that imports the harness, told that the temporary directory
        is a sandbox: it makes a directory and a file as a test would, removes neither,
        and ends. Its own root was inside the sandbox, and the sandbox is empty."""
        sandbox = tempfile.mkdtemp()
        env = dict(os.environ, TMPDIR=sandbox, TEMP=sandbox, TMP=sandbox)
        env["PYTHONPATH"] = os.pathsep.join([HERE, env.get("PYTHONPATH", "")])
        leave = ("import os, tempfile, harness\n"
                 "kept = tempfile.mkdtemp()\n"
                 "open(os.path.join(kept, 'left'), 'w').close()\n"
                 "tempfile.NamedTemporaryFile(delete=False).close()\n"
                 "print(harness.SUITE_TEMP)\n"
                 "print(len(os.listdir(harness.SUITE_TEMP)))\n")
        child = harness.spawn([sys.executable, "-c", leave], env=env)
        self.assertEqual(child.returncode, 0, child.stderr)
        root, inside = child.stdout.split()
        self.assertTrue(same(os.path.dirname(root), sandbox),
                        "the child's root was not made where it was told")
        self.assertGreaterEqual(int(inside), 2, "the child left nothing to remove")
        self.assertEqual(os.listdir(sandbox), [])


if __name__ == "__main__":
    unittest.main()
