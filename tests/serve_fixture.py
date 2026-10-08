"""`python -m http.server` with who asked in its log, and the count a step makes of it.

    python tests/serve_fixture.py 8000 tests/fixtures/good > server.log 2>&1 &

A workflow step serves a fixture site, runs one audit of it and counts the requests by
reading the server's log: the entry page is fetched once, nothing three times. The
standard server logs the request line and nothing about who sent it. On the machines
this tool is developed on something else asks freshly opened loopback ports for `/`
every five seconds (`harness.STRANGERS`), and the step counted that as the audit's: on
7 October 2026 a run of the local gate on Windows read five `GET /` where the audit
had sent one, four of them five seconds apart, and a listener put on the empty port
afterwards was asked with `User-Agent: Workbench`. The suite's own fixture servers
have kept such a request apart since 0.135.0; the workflow's had no way to.

So the log line ends with the User-Agent, and `counted` sets aside what
`harness.is_stranger` names and nothing looser: a request with no User-Agent is the
audit's until shown otherwise.

The server itself imports nothing of the suite. `harness` makes two temporary
directories when it is imported and removes them when the process ends, and a step
ends this process by killing it. `counted` imports it, in the step's own short
process.

Everything else is `python -m http.server PORT --directory DIRECTORY` as CPython's own
`__main__` builds it: the same handler, threaded, on IPv6 and IPv4 at once. One request
of the audit's in that run's log came from `::1` and the rest from `127.0.0.1`.
"""
from __future__ import annotations

import collections
import contextlib
import http.server
import re
import socket
import sys

LINE = re.compile(r'"(GET|HEAD) (\S+) HTTP[^"]*" \S+ \S+ "([^"]*)"$')


class Handler(http.server.SimpleHTTPRequestHandler):
    """The standard handler; its request line in the log says who asked."""

    def log_request(self, code="-", size="-"):
        if isinstance(code, http.HTTPStatus):
            code = code.value
        headers = getattr(self, "headers", None)
        self.log_message('"%s" %s %s "%s"', self.requestline, str(code), str(size),
                         (headers.get("User-Agent") if headers else None) or "")


def server_class(directory: str):
    """A threaded server of `directory` that answers on both address families."""

    class DualStackServer(http.server.ThreadingHTTPServer):

        def server_bind(self):
            # An IPv4-only socket has no such option, and that is fine.
            with contextlib.suppress(Exception):
                self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
            return super().server_bind()

        def finish_request(self, request, client_address):
            self.RequestHandlerClass(request, client_address, self, directory=directory)

    return DualStackServer


def counted(lines) -> tuple[collections.Counter, int]:
    """((method, path) -> how many times the audit asked, how many a port probe sent).

    A line this cannot read is not a request line: the server's start-up line, and the
    `code 404, message …` line that goes before the request line of a 404.
    """
    import harness
    seen, strangers = collections.Counter(), 0
    for line in lines:
        found = LINE.search(line.rstrip())
        if not found:
            continue
        if harness.is_stranger(found.group(3)):
            strangers += 1
        else:
            seen[found.group(1, 2)] += 1
    return seen, strangers


if __name__ == "__main__":
    http.server.test(HandlerClass=Handler, ServerClass=server_class(sys.argv[2]),
                     port=int(sys.argv[1]), bind=None)
