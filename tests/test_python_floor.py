"""Python 3.11 is the floor: what 3.10 needed is gone, and an older Python is told so.

Anton decided on 15 October 2026 that an old Python needing patches raises the floor
rather than keeping them. 3.10 needed two. `server_log_audit.py` turned a trailing `Z`
into `+00:00` because `datetime.fromisoformat` refuses `Z` before 3.11, and
`test_registry.pyproject_value` read `pyproject.toml` by regex because `tomllib` is
3.11's. Both are gone, and that makes the floor matter: the plugin is installed by
copying, so `requires-python` stops nobody, and 3.10 would now run an audit and read
every `…Z` time of a log as no time at all.

So `scripts/lib/python_floor.py` is the first thing every program imports, and an
older Python is told in one line what it is and what is needed, before the program has
done anything. CI runs nothing below the floor any more, so this cannot be seen there
on a real 3.10; it is seen here by starting every program with the check told that it
is running on the version just below the floor. A real 3.10 is a command in the
release's report.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(ROOT, "skills", "seo-checklist")
SCRIPTS = os.path.join(SKILL, "scripts")
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness  # noqa: E402
from lib import python_floor  # noqa: E402
from test_program_streams import programs as guarded  # noqa: E402
from test_registry import declared_floor, newer_syntax  # noqa: E402

FLOOR = tuple(int(part) for part in python_floor.REQUIRES.split("."))
# The version just below the floor, as the check is told it is running. The micro
# version is any; 3.10.20 is one that exists.
OLDER = f"{FLOOR[0]}.{FLOOR[1] - 1}.20"

# A file started as `python <file> --help` starts it — its own directory first on the
# path, its name `__main__` — after two things are done to the process. When `older`
# is a version, `sys.version_info` says that version, so the real check reads it. And
# an audit hook (PEP 578) stands in front of everything that is work: a request, a
# child process, a file opened to write, a file or directory made, moved or removed.
# The first such event is written down and ends the process there, so a program that
# would go on to crawl a site stops at its first step. What it printed is read as
# `harness.spawn` reads it; what it did, from the answer file.
STARTED = r"""
import collections, json, os, runpy, sys, tempfile
program, answer, older = sys.argv[1], sys.argv[2], sys.argv[3]
# Asked once before the hook: the first answer is found by writing and removing a file
# in each candidate directory, and `lib/safe_http.py` asks it when it is imported. That
# is the standard library looking for a directory, not a module doing work.
tempfile.gettempdir()
WORK = ("socket.connect", "socket.getaddrinfo", "socket.gethostby", "socket.sendto",
        "socket.sendmsg", "subprocess.Popen", "os.system", "os.posix_spawn", "os.spawn",
        "os.exec", "os.fork", "os.startfile", "os.mkdir", "os.remove", "os.rename",
        "os.rmdir", "os.truncate", "os.symlink", "os.link", "shutil.")
WRITES = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC
done = []

def tell(work):
    done.append(True)
    with open(answer, "w", encoding="utf-8") as f:
        json.dump({"work": work}, f)

def hook(event, args):
    if done:
        return
    if event == "open":
        mode, flags = args[1], args[2]
        work = any(c in mode for c in "wax+") if isinstance(mode, str) else \
            isinstance(flags, int) and bool(flags & WRITES)
    else:
        work = event.startswith(WORK)
    if work:
        tell([event, repr(args)[:300]])
        os._exit(0)

if older != "-":
    major, minor, micro = (int(part) for part in older.split("."))
    sys.version_info = collections.namedtuple(
        "version_info", "major minor micro releaselevel serial")(major, minor, micro,
                                                                 "final", 0)
sys.argv = [program, "--help"]
sys.path.insert(0, os.path.dirname(program))
sys.addaudithook(hook)
try:
    runpy.run_path(program, run_name="__main__")
finally:
    if not done:
        tell([])
"""


def every_file() -> list[str]:
    """Every Python file somebody could start: whatever is in the folders programs are."""
    return [os.path.join(folder, name)
            for folder in (SCRIPTS, os.path.join(SCRIPTS, "lib"), os.path.join(SKILL, "tools"))
            for name in sorted(os.listdir(folder)) if name.endswith(".py")]


def start(program: str, older: str, folder: str) -> dict:
    """`program` started once, as `older` (a version) or as it is (`-`)."""
    answer = os.path.join(tempfile.mkdtemp(prefix="start-", dir=folder), "answer.json")
    done = harness.spawn([sys.executable, "-c", STARTED, program, answer, older],
                         env=harness.offline_env(PYTHONDONTWRITEBYTECODE="1"), timeout=300)
    work = None
    if os.path.exists(answer):
        with open(answer, encoding="utf-8") as f:
            work = json.load(f)["work"]
    return {"exit": done.returncode, "stdout": done.stdout, "stderr": done.stderr,
            "work": work}


def refused(seen: dict) -> bool:
    """One line naming both versions, a non-zero exit, nothing printed, nothing done."""
    return (seen["exit"] == 1 and seen["stdout"] == "" and seen["work"] == []
            and seen["stderr"].splitlines() == [
                f"seo-checklist needs Python {python_floor.REQUIRES} or newer; "
                f"this is Python {OLDER}."])


class AnOlderPythonIsToldSoByEveryProgram(unittest.TestCase):
    """`openspec/specs/governance/` INV-G13.

    Which files are programs is not written down. A file with a `__main__` guard is
    one, as `test_program_streams` and the by-hand sweep of `test_url_credentials`
    count them; and so is any file that, started as it is, prints or does something —
    `tools/probe_shapes.py` has no guard and starts a probe of a site. A module that
    only defines things does nothing when started, and it is not asked to refuse.
    """

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.mkdtemp(prefix="seo-floor-")
        cls.addClassCleanup(shutil.rmtree, cls.folder, ignore_errors=True)
        files, cls.guarded = every_file(), set(guarded())
        with ThreadPoolExecutor(max_workers=8) as pool:
            as_is = list(pool.map(lambda path: start(path, "-", cls.folder), files))
        cls.as_is = dict(zip(files, as_is, strict=True))
        cls.programs = [path for path, seen in cls.as_is.items()
                        if path in cls.guarded or seen["stdout"] or seen["work"]]
        with ThreadPoolExecutor(max_workers=8) as pool:
            cls.older = dict(zip(cls.programs, pool.map(
                lambda path: start(path, OLDER, cls.folder), cls.programs), strict=True))

    @staticmethod
    def name(path: str) -> str:
        return os.path.relpath(path, SKILL).replace(os.sep, "/")

    def test_every_program_says_which_python_it_needs_and_does_nothing_else(self):
        self.assertGreater(len(self.programs), 80, "almost no program was found")
        bad = {self.name(path): seen for path, seen in self.older.items()
               if not refused(seen)}
        self.assertEqual(bad, {}, "started on an older Python, these did not stop at "
                                  "`python_floor` with its one line: import it first")

    def test_a_program_without_a_guard_is_found_by_what_it_does(self):
        """The set is wider than the guard: what it adds is seen doing something."""
        unguarded = [path for path in self.programs if path not in self.guarded]
        self.assertTrue(unguarded, "every program has a guard, or none was seen working")
        for path in unguarded:
            with self.subTest(program=self.name(path)):
                self.assertTrue(self.as_is[path]["work"] or self.as_is[path]["stdout"])

    def test_on_this_python_the_check_lets_every_program_start(self):
        """The other half: nothing that is a program was refused as it is."""
        for path in self.programs:
            with self.subTest(program=self.name(path)):
                self.assertNotIn("seo-checklist needs Python", self.as_is[path]["stderr"])

    def test_a_program_parses_on_the_python_it_refuses(self):
        """The check runs only if the file that imports it can be read: a program in
        syntax newer than the version below the floor would stop that version with a
        `SyntaxError` and a traceback instead. So would the check itself."""
        below = (FLOOR[0], FLOOR[1] - 1)
        chain = [os.path.join(SCRIPTS, "lib", "__init__.py"), python_floor.__file__,
                 os.path.join(SKILL, "tools", "python_floor.py")]
        offenders = []
        for path in self.programs + chain:
            with open(path, encoding="utf-8") as f:
                offenders += newer_syntax(f.read(), path, below)
        self.assertEqual(offenders, [])


class TheControlIsSeenBoth(unittest.TestCase):
    """Without these the class above could pass because the question is asked wrongly."""

    def program(self, folder: str, source: str) -> str:
        path = os.path.join(folder, "made_up.py")
        with open(path, "w", encoding="utf-8") as f:
            f.write(source)
        return path

    def test_a_program_that_never_imports_the_check_runs_on(self):
        with tempfile.TemporaryDirectory(prefix="seo-floor-") as folder:
            seen = start(self.program(folder, "import argparse\nif __name__ == '__main__':\n"
                                              "    argparse.ArgumentParser().parse_args()\n"),
                         OLDER, folder)
        self.assertEqual((seen["exit"], seen["work"]), (0, []))
        self.assertIn("usage", seen["stdout"])
        self.assertFalse(refused(seen))

    def test_work_done_before_the_check_is_seen(self):
        with tempfile.TemporaryDirectory(prefix="seo-floor-") as folder:
            seen = start(self.program(folder, "import tempfile\ntempfile.mkstemp()\n"
                                              "from lib import python_floor\n"),
                         OLDER, folder)
        self.assertEqual(seen["work"][0], "open")
        self.assertFalse(refused(seen))

    def test_the_check_alone_refuses_the_older_python(self):
        """The real check, started by itself, is the line the class above requires."""
        with tempfile.TemporaryDirectory(prefix="seo-floor-") as folder:
            self.assertTrue(refused(start(python_floor.__file__, OLDER, folder)))


class TheFloorIsWrittenOnce(unittest.TestCase):

    def test_the_check_compares_with_the_floor_pyproject_declares(self):
        """`requires-python`, ruff's target and CI's lowest legs are held to each other
        by `test_registry` and `test_ci_local`; this ties the fourth to the first."""
        self.assertEqual(python_floor.REQUIRES, declared_floor())


class ALogsTimesEndingInZAreRead(unittest.TestCase):
    """The patch 3.10 needed in `server_log_audit.py`, gone: a JSON log whose ISO times
    end in `Z` is read as the same log with `+00:00`, through the program as the
    operator starts it. On 3.10 without the patch every such time was no time: the
    window unknown, and a `no_timestamps` caveat where the program reads a window of
    twenty days."""

    def run_on(self, folder: str, name: str, text: str) -> dict:
        path = os.path.join(folder, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        done = harness.spawn([sys.executable, os.path.join(SCRIPTS, "server_log_audit.py"),
                              path, "--json"], timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr)
        result = json.loads(done.stdout)
        del result["log_file"]
        return result

    def test_z_is_read_as_utc(self):
        with open(os.path.join(harness.FIXTURES, "logs", "nginx-json.log"),
                  encoding="utf-8") as f:
            offset = f.read()
        zulu = offset.replace('+00:00"', 'Z"')
        self.assertEqual(zulu.count('Z"'), offset.count("\n"),
                         "the fixture's times no longer all end in +00:00")
        with tempfile.TemporaryDirectory(prefix="seo-floor-") as folder:
            with_offset = self.run_on(folder, "offset.log", offset)
            with_z = self.run_on(folder, "zulu.log", zulu)
        self.assertEqual(with_offset["window"]["days"], 20)   # as the program reports it
        self.assertEqual(with_z, with_offset)


if __name__ == "__main__":
    unittest.main()
