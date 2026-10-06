"""The harness counts what the audit asked, not what a port probe did.

`tests/harness.py` `STRANGERS` says what was measured and why. This holds the three things
that have to stay true of it: the probe is answered, it is not in `requested`, and nothing
looser than its exact User-Agent is waved through — a request with no User-Agent at all is
the audit's until proved otherwise, because a script that lost its header is a defect the
request counts must still see.
"""
from __future__ import annotations

import http.client
import os
import sys
import unittest
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness  # noqa: E402
from harness import served  # noqa: E402

# As it arrived on the Mac the push gate runs on, 6 October 2026.
MAC_PROBE = "Workbench%20Native/1.4.2 CFNetwork/3896.100.1.1.1 Darwin/27.0.0"
PROBES = (*harness.STRANGERS, MAC_PROBE)


def ask(url: str, path: str = "/", agent: str | None = None, method: str = "GET") -> int:
    parsed = urlparse(url)
    connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=10)
    try:
        connection.putrequest(method, path, skip_accept_encoding=True)
        if agent is not None:
            connection.putheader("User-Agent", agent)
        connection.putheader("Connection", "close")
        connection.endheaders()
        response = connection.getresponse()
        response.read()
        return response.status
    finally:
        connection.close()


class APortProbeIsNotTheAudit(unittest.TestCase):

    def test_the_probe_is_answered_and_kept_apart(self):
        with served({"/": "<!doctype html><title>t</title>"}) as site:
            for agent in PROBES:
                self.assertEqual(ask(site.url, agent=agent), 200)
            self.assertEqual(site.requested, [])
            self.assertEqual(site.strangers, [("GET", "/")] * len(PROBES))

    def test_everything_else_is_counted(self):
        with served({"/": "<!doctype html><title>t</title>"}) as site:
            ask(site.url)                                   # no User-Agent at all
            ask(site.url, agent="")
            ask(site.url, agent="Workbench/2")
            ask(site.url, agent="workbench")
            ask(site.url, agent="Mozilla/5.0 (compatible; Workbench)")
            # The Mac's probe is a shape, three version numbers and all of it:
            # a part of it, or it with anything before or after, is not it.
            ask(site.url, agent="Workbench%20Native/1.4.2")
            ask(site.url, agent=MAC_PROBE.replace("%20", " "))
            ask(site.url, agent=MAC_PROBE + " curl/8")
            ask(site.url, agent="curl/8 " + MAC_PROBE)
            ask(site.url, "/missing", agent="curl/8")
            ask(site.url, agent="curl/8", method="HEAD")
            self.assertEqual(site.requested,
                             [("GET", "/")] * 9 + [("GET", "/missing"), ("HEAD", "/")])
            self.assertEqual(site.strangers, [])

    def test_two_origins_do_not_share_a_list(self):
        with served({"/": "a"}) as first, served({"/": "b"}) as second:
            ask(first.url, agent=harness.STRANGERS[0])
            ask(second.url, agent="curl/8")
            self.assertEqual((first.requested, first.strangers), ([], [("GET", "/")]))
            self.assertEqual((second.requested, second.strangers), ([("GET", "/")], []))

    def test_the_plain_side_of_a_tls_origin_keeps_them_apart_too(self):
        with served({"/": "a"}, tls=True, plain="redirect") as site:
            plain = "http://" + urlparse(site.url).netloc + "/"
            self.assertEqual(ask(plain, agent=harness.STRANGERS[0]), 301)
            self.assertEqual(site.plain_requested, [])
            self.assertEqual(ask(plain, agent="curl/8"), 301)
            self.assertEqual(site.plain_requested, [("GET", "/")])

    def test_the_list_names_exact_user_agents(self):
        for agent in harness.STRANGERS:
            self.assertIsInstance(agent, str)
            self.assertTrue(agent.strip() and agent == agent.strip(), repr(agent))


if __name__ == "__main__":
    unittest.main()
