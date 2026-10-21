"""`checklist_runner` auditing a served fixture by name — an instrument, never a runner.

`openspec/specs/inputs/` INP-10 asks that a stale public suffix list be announced only
when the list decided something, which is a Search Console property derived from the
audited host's name. Every fixture here is served on `127.0.0.1`, an address has no
registrable domain, and Search Console is skipped before the list is consulted, so no
test reached the branch (one was written against the fixture and deleted on 6 September
2026 for passing without reaching it). This runs the real runner with three things
changed, in its own process: `SEO_TEST_NAME` resolves to this machine, the loopback-only
guard accepts that name, and the host is not taken for one only this machine reaches,
as it would not be under a real name. `SEO_TEST_PSL` replaces the bundled list, and the
key files a machine may happen to hold are not looked for. Nothing else changes.

Written for F04. The scripts the runner starts are separate processes and know nothing
of the name; what is read here is the runner's own output.
"""
import os
import socket
import sys

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "skills", "seo-checklist", "scripts")
sys.path.insert(0, SCRIPTS)

import checklist_runner as runner  # noqa: E402
import lib.safe_http as safe_http  # noqa: E402

NAME = os.environ["SEO_TEST_NAME"]
_resolve = socket.getaddrinfo


def getaddrinfo(host, *args, **kwargs):
    return _resolve("127.0.0.1" if host == NAME else host, *args, **kwargs)


_loopback = safe_http._is_loopback_host
socket.getaddrinfo = getaddrinfo
safe_http._is_loopback_host = lambda host: host == NAME or _loopback(host)
safe_http.is_private_host = lambda url: False
runner.GSC_FALLBACKS = []
if os.environ.get("SEO_TEST_PSL"):
    runner.PSL_PATH = os.environ["SEO_TEST_PSL"]
sys.argv[0] = os.path.join(SCRIPTS, "checklist_runner.py")
sys.exit(runner.main())
