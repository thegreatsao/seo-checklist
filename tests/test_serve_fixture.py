"""A workflow step that counts an audit's requests counts the audit's, not a port probe's.

`tests/serve_fixture.py` says what was measured and why. The suite's own fixture servers
have kept a probe's request apart since 0.135.0 (`test_harness_strangers`); the server the
workflow starts was `python -m http.server`, whose log does not say who asked, so the
live-path step counted everybody. This holds the server's log line, the count made of
it, and that the workflow uses both.
"""
from __future__ import annotations

import io
import os
import sys
import tempfile
import threading
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "seo-checklist", "tools"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness  # noqa: E402
import ci_local  # noqa: E402
import serve_fixture  # noqa: E402
from test_harness_strangers import PROBES, ask  # noqa: E402

AUDIT = "Mozilla/5.0 (compatible; AgenticSEOSkill/1.0)"


class TheLogSaysWhoAsked(unittest.TestCase):

    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="seo-served-")
        self.addCleanup(folder.cleanup)
        with open(os.path.join(folder.name, "index.html"), "w", encoding="utf-8") as page:
            page.write("<!doctype html><title>served</title>")
        self.server = serve_fixture.server_class(folder.name)(("127.0.0.1", 0),
                                                               serve_fixture.Handler)
        self.url = "http://127.0.0.1:%d" % self.server.server_address[1]
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 10)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def count(self, *requests):
        """Make `requests` — (agent, path, method) — and count the server's log."""
        with mock.patch.object(sys, "stderr", io.StringIO()) as log:
            for agent, path, method in requests:
                ask(self.url, path, agent=agent, method=method)
        return serve_fixture.counted(log.getvalue().splitlines(keepends=True))

    def test_a_port_probe_is_answered_and_is_not_the_audits(self):
        with mock.patch.object(sys, "stderr", io.StringIO()):
            for probe in PROBES:
                self.assertEqual(ask(self.url, agent=probe), 200)
        seen, strangers = self.count(*[(probe, "/", "GET") for probe in PROBES],
                                     (AUDIT, "/", "GET"), (AUDIT, "/", "HEAD"))
        self.assertEqual(dict(seen), {("GET", "/"): 1, ("HEAD", "/"): 1})
        self.assertEqual(strangers, len(PROBES))

    def test_a_request_with_no_user_agent_is_the_audits(self):
        """A script that lost its header is a defect the count has to see."""
        seen, strangers = self.count((None, "/", "GET"), (AUDIT, "/", "GET"))
        self.assertEqual((dict(seen), strangers), ({("GET", "/"): 2}, 0))

    def test_nothing_looser_than_the_probe_is_set_aside(self):
        near = [harness.STRANGERS[0] + "/2", "x " + harness.STRANGERS[0],
                harness.STRANGERS[0].lower()]
        seen, strangers = self.count(*[(agent, "/", "GET") for agent in near])
        self.assertEqual((dict(seen), strangers), ({("GET", "/"): len(near)}, 0))

    def test_a_page_that_is_not_there_is_still_a_request(self):
        """A 404 writes two lines, and the one that is not the request line is not
        counted twice or instead."""
        seen, strangers = self.count((AUDIT, "/llms-full.txt", "GET"))
        self.assertEqual((dict(seen), strangers), ({("GET", "/llms-full.txt"): 1}, 0))


class TheWorkflowCountsThroughIt(unittest.TestCase):

    def test_every_step_that_reads_a_server_log_serves_and_counts_through_it(self):
        """Derived from the steps: one that names `server.log` is one that counts what
        a server it started was asked."""
        readers = [(name, step["run"])
                   for name, job in ci_local.load_workflow()["jobs"].items()
                   for step in job["steps"] if "server.log" in step.get("run", "")]
        self.assertTrue(readers, "no step reads a server's log; this test is vacuous")
        for job, script in readers:
            # What the step runs, without what it says about itself.
            script = "\n".join(line for line in script.splitlines()
                               if not line.lstrip().startswith("#"))
            with self.subTest(job=job):
                self.assertIn("python tests/serve_fixture.py 8000 ", script)
                self.assertNotIn("-m http.server", script,
                                 "the standard server's log does not say who asked")
                self.assertIn('counted(open("server.log"))', script)
                self.assertNotIn("re.search(", script,
                                 "the step reads the log by a pattern of its own again")


if __name__ == "__main__":
    unittest.main()
