"""A failure to read the notebook is not a finding about what the notebook holds.

The freshness gate reads each uploaded document's `source-sha256` back out of the
notebook. On 29 August 2026 the Google session expired part-way through that read:
four sources answered, seven did not, and the seven were reported `UNSTAMPED` —
"notebook copy carries no stamp", a claim about the documents. `sync` then acted on
it, and its remedy for a missing stamp is `delete-by-title` followed by `add`. The
deletes went out against a dead session and (almost certainly) failed too, so nothing
was lost; with a cookie still good for writes and not for reads, the tool would have
emptied the notebook it exists to protect.

This is the repo's own rule, broken by one of its tools: REG-8 in `openspec/specs/registry/`
and NO_DATA in `openspec/specs/verdicts/` both say that absence of data is not a verdict. The
value read from a source that could not be fetched is now `Unread`, distinct from the
`None` that means "read, and carries no stamp", and the two lead to different places:
`UNREAD` fails `check` and is skipped by `sync`.

These tests drive the tool with a fake CLI, so they say what it does rather than what
the notebook did that afternoon.
"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "skills", "seo-checklist", "tools")
sys.path.insert(0, TOOLS)

import notebook_sync as N  # noqa: E402

REPO = Path(ROOT)
AUTH_ERROR = ("Unexpected error: Authentication expired or invalid.\n"
              "Run 'notebooklm login' to re-authenticate.")


def result(code=0, out="", err=""):
    return SimpleNamespace(returncode=code, stdout=out, stderr=err)


class FakeCli:
    """Stands in for `notebooklm`, one canned answer per verb.

    `calls` records every invocation, because the point of two of these tests is
    which calls were *not* made.
    """

    def __init__(self, titles, fulltext, add=None, delete=None, list_result=None):
        self.titles = titles          # title -> id
        self.fulltext = fulltext      # id -> stamp string, or a result to return
        self.add = add or result(0, "added 12345678-1234-1234-1234-123456789abc")
        self.delete = delete or result(0, "deleted")
        self.list_result = list_result
        self.calls = []
        # What went down stdin, per call. Recorded rather than dropped: since
        # 0.93.9 the document body travels that way, and a double that ignored it
        # would pass a version that put a 73 KB registry back on the command line.
        self.stdin = []

    def __call__(self, *args, timeout=600, stdin_text=None):
        self.calls.append(args)
        self.stdin.append(stdin_text)
        verb = args[:2]
        if verb == ("source", "list"):
            if self.list_result is not None:
                return self.list_result
            sources = [{"id": i, "title": t} for t, i in self.titles.items()]
            return result(0, json.dumps({"sources": sources}))
        if verb == ("source", "fulltext"):
            answer = self.fulltext[args[2]]
            if not isinstance(answer, str):
                return answer
            Path(args[4]).write_text("source-sha256: %s\n" % answer, encoding="utf-8")
            return result(0, "written")
        if verb == ("source", "delete-by-title"):
            return self.delete
        if verb == ("source", "add"):
            return self.add
        if verb == ("source", "rename"):
            return result(0, "renamed")
        raise AssertionError("unexpected call: %r" % (args,))

    def verbs(self):
        return [" ".join(c[:2]) for c in self.calls]


class StampsSeparateTwoKindsOfSilence(unittest.TestCase):

    def stamps(self, cli):
        old = N.nlm
        N.nlm = cli
        try:
            return N.notebook_stamps()
        finally:
            N.nlm = old

    def test_a_copy_that_was_read_and_carries_no_stamp_is_none(self):
        cli = FakeCli({"Hand-uploaded": "id-1"}, {"id-1": ""})

        def fulltext_without_a_stamp(*args, timeout=600):
            cli.calls.append(args)
            if args[:2] == ("source", "fulltext"):
                Path(args[4]).write_text("no stamp here\n", encoding="utf-8")
                return result(0, "written")
            return FakeCli.__call__(cli, *args, timeout=timeout)

        self.assertIsNone(self.stamps(fulltext_without_a_stamp)["Hand-uploaded"])

    def test_a_copy_that_could_not_be_read_is_unread_and_says_why(self):
        cli = FakeCli({"Spec - registry": "id-1"},
                      {"id-1": result(1, "", "the source is still processing")})
        got = self.stamps(cli)["Spec - registry"]
        self.assertIsInstance(got, N.Unread)
        self.assertIn("processing", got.why)

    def test_the_two_are_not_the_same_value(self):
        """The collapse that caused the incident: `None` for both."""
        self.assertNotIsInstance(None, N.Unread)


class CheckReportsWhatItCouldNotRead(unittest.TestCase):

    def check(self, cli, manifest):
        old_nlm, old_manifest = N.nlm, N.manifest
        N.nlm, N.manifest = cli, lambda repo: manifest
        try:
            with redirect_stdout(io.StringIO()) as buf:
                drift = N.do_check(REPO)
            return drift, buf.getvalue()
        finally:
            N.nlm, N.manifest = old_nlm, old_manifest

    def test_an_unreadable_copy_is_unread_rather_than_unstamped(self):
        manifest = [("README - project overview", "file", Path("README.md"))]
        cli = FakeCli({"README - project overview": "id-1"},
                      {"id-1": result(1, "", "connection reset")})
        drift, printed = self.check(cli, manifest)
        self.assertEqual([v for _, v, _ in drift], ["UNREAD"])
        self.assertIn("UNREAD", printed)
        self.assertNotIn("UNSTAMPED", printed)

    def test_unread_still_fails_the_gate(self):
        """A gate that cannot see must not report fresh."""
        manifest = [("README - project overview", "file", Path("README.md"))]
        cli = FakeCli({"README - project overview": "id-1"},
                      {"id-1": result(1, "", "connection reset")})
        drift, _ = self.check(cli, manifest)
        self.assertTrue(drift, "an unreadable notebook passed the check")


class SyncDoesNotRemedyAFailureToLook(unittest.TestCase):

    def sync(self, cli, manifest):
        old_nlm, old_manifest = N.nlm, N.manifest
        N.nlm, N.manifest = cli, lambda repo: manifest
        try:
            with redirect_stdout(io.StringIO()) as buf:
                code = N.do_sync(REPO)
            return code, buf.getvalue()
        finally:
            N.nlm, N.manifest = old_nlm, old_manifest

    def test_an_unread_source_is_never_deleted(self):
        manifest = [("README - project overview", "file", Path("README.md"))]
        cli = FakeCli({"README - project overview": "id-1"},
                      {"id-1": result(1, "", "connection reset")})
        _, printed = self.sync(cli, manifest)
        self.assertNotIn("source delete-by-title", cli.verbs(),
                         "sync deleted a source it had failed to read")
        self.assertNotIn("source add", cli.verbs())
        self.assertIn("skipped", printed)

    def test_a_stale_source_is_still_replaced(self):
        """The skip must not swallow the case sync exists for."""
        manifest = [("README - project overview", "file", Path("README.md"))]
        cli = FakeCli({"README - project overview": "id-1"}, {"id-1": "0" * 64})
        self.sync(cli, manifest)
        self.assertIn("source delete-by-title", cli.verbs())
        self.assertIn("source add", cli.verbs())

    def test_a_delete_that_fails_stops_the_add(self):
        """Two sources under one title is worse than one stale source: the
        notebook then answers from whichever it likes, and the stamp read back
        is whichever the listing returns first."""
        manifest = [("README - project overview", "file", Path("README.md"))]
        cli = FakeCli({"README - project overview": "id-1"}, {"id-1": "0" * 64},
                      delete=result(1, "", "no such title"))
        _, printed = self.sync(cli, manifest)
        self.assertIn("source delete-by-title", cli.verbs())
        self.assertNotIn("source add", cli.verbs(),
                         "a second copy was added under a title still held by the first")
        self.assertIn("FAILED", printed)


class TheSpecsAreDerivedRatherThanListed(unittest.TestCase):
    """A hand-kept list cannot say what is missing from it.

    Three specs were three literals in this tool. The fourth, `openspec/specs/declarations/`,
    would have reached the notebook only once somebody remembered to add a line — and
    the reader that would have noticed the omission was the same line. That is the
    defect `openspec/specs/declarations/` itself specifies as DEC-6, in the manifest it is about.
    """

    def test_every_spec_in_the_tree_is_in_the_manifest(self):
        on_disk = {p.parent.name for p in (REPO / "openspec" / "specs").glob("*/spec.md")}
        self.assertTrue(on_disk, "no specs found; this test would pass on nothing")
        listed = {t[len("Spec - "):] for t, _, _ in N.manifest(REPO)
                  if t.startswith("Spec - ")}
        self.assertEqual(listed, on_disk)

    def test_a_new_spec_needs_no_edit_to_this_tool(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            for name in ("registry", "brand-new"):
                (repo / "openspec" / "specs" / name).mkdir(parents=True)
                (repo / "openspec" / "specs" / name / "spec.md").write_text("x", encoding="utf-8")
            titles = [t for t, _, _ in N.manifest(repo) if t.startswith("Spec - ")]
        self.assertEqual(titles, ["Spec - brand-new", "Spec - registry"])

    def test_the_existing_three_keep_the_titles_the_notebook_knows_them_by(self):
        """Title is a source's identity inside the notebook. A renamed spec uploads as
        a new source and leaves the old one behind, named by no manifest entry and so
        invisible to `check` — which is worse than the stale copy it replaced."""
        titles = {t for t, _, _ in N.manifest(REPO)}
        for known in ("Spec - registry", "Spec - scoring", "Spec - verdicts"):
            self.assertIn(known, titles)

    def test_a_spec_path_is_relative_to_the_repo_it_was_derived_from(self):
        """`--repo` points the tool at another clone; an absolute path taken from this
        one would read the wrong tree while reporting the right title."""
        for title, _kind, target in N.manifest(REPO):
            if title.startswith("Spec - "):
                self.assertFalse(Path(target).is_absolute(), title)


class TheBodyTravelsOnStdinAndTheCliIsACommand(unittest.TestCase):
    """`notebook_sync.py` reaches NotebookLM two ways it did not before 0.93.9, and
    both are repairs to a run that had already gone wrong once.

    **The CLI is a command, not an executable.** Windows Application Control refused
    `notebooklm.exe` with WinError 4551 while the package behind it stayed usable as
    `python -m notebooklm`. A launcher shim is not the tool, and a gate that can only
    run the shim goes dark for a reason unrelated to what it measures.

    **A source is pasted, not uploaded.** The upload endpoint answered 500 and then
    401 on a session whose every other call worked. `sync` deletes through the working
    path and used to add through the broken one, so it removed three good sources,
    added none, and left four half-registered rows stuck in `preparing`. The paste
    endpoint takes the same session; the body goes down stdin, because Windows caps a
    command line near 32 KB and the registry document is 73 KB.
    """

    def setUp(self):
        self.saved = dict(N.CONFIG)

    def tearDown(self):
        N.CONFIG.update(self.saved)

    def test_a_one_word_setting_still_resolves_through_the_path(self):
        self.assertEqual(N.resolve_cli(sys.executable), [sys.executable])

    def test_a_command_is_split_and_its_arguments_kept(self):
        resolved = N.resolve_cli(f'"{sys.executable}" -m notebooklm')
        self.assertEqual(resolved[1:], ["-m", "notebooklm"])
        self.assertTrue(resolved[0].endswith(os.path.basename(sys.executable)))

    def test_an_unusable_head_is_refused_by_name(self):
        with self.assertRaises(SystemExit) as raised:
            N.resolve_cli("definitely-not-on-this-machine -m notebooklm")
        self.assertIn("definitely-not-on-this-machine", str(raised.exception))

    def test_the_command_reaches_the_child_whole(self):
        """The head alone would run `python source list` and ask the wrong program."""
        seen = {}
        old = N.run
        N.run = lambda args, timeout=600, stdin_text=None: (
            seen.setdefault("args", args), result(0, "{}"))[1]
        try:
            N.CONFIG["cli"] = [sys.executable, "-m", "notebooklm"]
            N.CONFIG["notebook"] = "nb-1"
            N.nlm("source", "list", "--json")
        finally:
            N.run = old
        self.assertEqual(seen["args"][:3], [sys.executable, "-m", "notebooklm"])
        self.assertEqual(seen["args"][3:5], ["source", "list"])


class ASourceIsPastedRatherThanUploaded(unittest.TestCase):

    def setUp(self):
        self.saved = dict(N.CONFIG)
        N.CONFIG["cli"], N.CONFIG["notebook"] = ["notebooklm"], "nb-1"

    def tearDown(self):
        N.CONFIG.update(self.saved)

    def sync(self, cli, manifest):
        old_nlm, old_manifest = N.nlm, N.manifest
        N.nlm, N.manifest = cli, lambda repo: manifest
        try:
            with redirect_stdout(io.StringIO()) as out:
                N.do_sync(REPO)
            return out.getvalue()
        finally:
            N.nlm, N.manifest = old_nlm, old_manifest

    def stale(self):
        """One manifest entry the notebook holds at the wrong stamp."""
        return [("README - project overview", "file", Path("README.md"))]

    def adds(self, cli):
        return [(args, body) for args, body in zip(cli.calls, cli.stdin, strict=True)
                if args[:2] == ("source", "add")]

    def test_the_add_names_the_body_on_stdin_and_not_on_the_command_line(self):
        cli = FakeCli({"README - project overview": "id-1"}, {"id-1": "0" * 64})
        self.sync(cli, self.stale())
        added = self.adds(cli)
        self.assertEqual(len(added), 1)
        args, body = added[0]
        self.assertIn("-", args, "the content argument is not the stdin marker")
        self.assertIn("--type", args)
        self.assertEqual(args[args.index("--type") + 1], "text")
        self.assertTrue(body, "nothing went down stdin")
        self.assertIn("source-sha256:", body)
        for piece in args:
            self.assertLess(len(piece), 200,
                            "a document travelled as an argument; Windows caps the "
                            "command line near 32 KB and the registry is 73 KB")

    def test_the_title_is_given_to_the_add_so_no_rename_follows(self):
        """A rename after an add is a second call that can fail on its own, leaving a
        source under a filename nobody looks for. The paste path takes the title."""
        cli = FakeCli({"README - project overview": "id-1"}, {"id-1": "0" * 64})
        self.sync(cli, self.stale())
        args, _body = self.adds(cli)[0]
        self.assertEqual(args[args.index("--title") + 1], "README - project overview")
        self.assertNotIn("source rename", cli.verbs())

    def test_a_source_the_manifest_does_not_name_is_reported_and_left(self):
        """The renamed twin. `LLM reviewer agents - 5 lenses` became
        `… - 4 lenses and the adversary` in 0.93.6, and because title is identity the
        sync added the new one beside the old and the notebook answered from both.

        Reported, not deleted: this tool cannot tell a leftover from something a person
        added by hand inside NotebookLM, and that edit is the one the gate has always
        said it does not see."""
        cli = FakeCli({"README - project overview": "id-1", "Something I added": "id-2"},
                      {"id-1": "0" * 64, "id-2": "1" * 64})
        printed = self.sync(cli, self.stale())
        self.assertIn("EXTRA", printed)
        self.assertIn("Something I added", printed)
        self.assertNotIn(("source", "delete-by-title", "Something I added", "--yes"),
                         cli.calls)


class ADeadSessionEndsTheRun(unittest.TestCase):

    def setUp(self):
        self.saved = dict(N.CONFIG)
        N.CONFIG["cli"], N.CONFIG["notebook"] = "notebooklm", "nb-1"

    def tearDown(self):
        N.CONFIG.update(self.saved)

    def call(self, answer):
        old = N.run
        N.run = lambda args, timeout=600, stdin_text=None: answer
        try:
            return N.nlm("source", "list", "--json")
        finally:
            N.run = old

    def test_an_expired_session_exits_rather_than_returning_a_failure(self):
        with self.assertRaises(SystemExit) as raised:
            self.call(result(1, "", AUTH_ERROR))
        self.assertIn("notebooklm login", str(raised.exception))

    def test_the_message_says_the_run_stopped_where_it_did(self):
        """`sync` is mid-flight when this fires, so the message must not claim
        that nothing happened — the calls before it already went out."""
        with self.assertRaises(SystemExit) as raised:
            self.call(result(1, "", AUTH_ERROR))
        said = str(raised.exception).lower()
        self.assertIn("stopped at the first call", said)
        self.assertNotIn("nothing was", said)

    def test_an_ordinary_failure_is_returned_for_the_caller_to_judge(self):
        got = self.call(result(1, "", "the source is still processing"))
        self.assertEqual(got.returncode, 1)

    def test_a_success_mentioning_login_is_not_an_expired_session(self):
        """The pattern is only consulted on a failure: a document that happens to
        contain the word must not end the run."""
        got = self.call(result(0, "…run `notebooklm login` to get started…"))
        self.assertEqual(got.returncode, 0)


if __name__ == "__main__":
    unittest.main()
