"""A served fixture site, so an evidence script can be tested through its real path.

Every test written before this one had to stub HTTP by hand, and the seven scripts
covered in 0.5.0 needed four different stubs between them: some fetch through
`seo_common.fetch_url`, some through `lib.safe_http.safe_get`, one posts to Safe
Browsing with `requests.post`, one asks `fetch_robots`. Reproducing that per script
would have made the remaining 44 mostly copied scaffolding — and a stub tests the
seam you thought of, not the request the script makes.

So the fixture is served over real HTTP on loopback instead. The scripts run
unmodified: their own pacing, redirect handling, robots logic and content-type checks
are all in the path, which is the half a stub cannot reach. `--allow-private` (0.4.0)
is what makes this possible at all; before it the SSRF guard refused loopback and
there was nowhere to serve a fixture.

**Still offline.** Loopback only, no egress, no API key, no DNS. A test that needs a
third-party service stubs that one call and says so.

Two sites, so every check can be exercised in both directions:

    good/   a site that satisfies as much of the registry as a static site can
    broken/ the same site with as many checks as possible deliberately failing

A check that only ever sees one of the two is not verified — it is observed agreeing
with the only input it was given, which is how thirty-three assertions in this
registry's history passed forever without being able to fail.

**Each site gets its own port, and that is not incidental.** `robots.txt`, the
sitemap and `llms.txt` live at the root of an *origin*, not inside a directory, so
two roots behind one port would have to share them — and every origin-level check
would then give both sites the same answer. Two origins is what makes `robots_checker`
and `sitemap_checker` testable in both directions at all.

Fixture URLs are written with the literal `http://127.0.0.1:8000`, which is also what
CI serves the good site on. The harness copies each tree to a temp directory and
rewrites that string to the port it actually bound, so nothing depends on a fixed
port being free and the two sites' canonicals point at themselves.

`served()` is the second half, and the one the per-script unit tests use: a throwaway
origin routed from a dict, so a test can say what the site returns for each path —
status, headers and body — without a directory on disk. `FixtureSite` answers "does
this check notice the difference between two whole sites"; `served()` answers "what
exactly does this script do when the header is missing, or the status is 500, or the
sitemap is gzipped". Both run the script through its own HTTP path, which is the point
of neither being a stub.
"""
from __future__ import annotations

import atexit
import gzip
import http.server
import io
import os
import shutil
import socketserver
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, "fixtures")
SCRIPTS = os.path.join(os.path.dirname(HERE), "skills", "seo-checklist", "scripts")
PLACEHOLDER = "http://127.0.0.1:8000"

# The *other* fixture origin, so a page can carry a genuinely external link without
# the suite touching the network. Several checks — outbound citations, external link
# health, cross-host detection — only have something to look at when a link leaves
# the origin, and `broken_links.py` requests every link it finds, so a real
# `https://en.wikipedia.org/...` in a fixture would quietly make this suite online.
# Each site's neighbour is external by host and still on loopback.
PLACEHOLDER_EXTERNAL = "http://127.0.0.1:8001"

TEXTUAL = (".html", ".xml", ".txt", ".css", ".json", ".md")

# Files the operator measures in a browser and hands to the run, rather than
# anything the tool fetches: a performance trace and a rendered-page measurement.
# They live outside both document roots on purpose — an artifact is an input to
# the audit, not a page of the site, and serving one would put it in the crawl.
ARTIFACTS = "artifacts"


def safe_http():
    """`lib.safe_http`, imported the way a test module imports it."""
    if SCRIPTS not in sys.path:
        sys.path.insert(0, SCRIPTS)
    import lib.safe_http as module
    return module


# Pacing slots and cached robots.txt answers default to one directory for the whole
# machine, which is right for the product — pacing is a promise to somebody else's
# server, and two audits a second apart have to queue behind each other — and wrong
# for this suite twice over.
#
# **Across runs.** The robots answer is keyed by `scheme://netloc` and nothing else,
# and lives half an hour. Every origin here is `127.0.0.1` plus an ephemeral port,
# and the operating system hands those out again, so a suite started five minutes
# after the last one can be answered by a server that stopped listening then. That is
# how `test_a_cache_hit_still_refuses_a_path_robots_forbids` failed once in 1200 and
# never alone, and pre-seeding `Allow: /` for a fresh server's port reproduces it
# verbatim.
#
# **Within one run, measured.** Logging every origin whose robots path was computed
# across a full suite gave 270 lookups over 21 origins — and one of them,
# `127.0.0.1:59747`, was served by one process at second 0 and by five different ones
# from second 10 to second 14. Two servers, one port, one run, inside a 1800-second
# entry's life.
#
# So the suite gets its own directory, and it travels in the environment, which is
# what lets the child processes these tests start share it instead of falling back to
# the machine's. `setdefault`, so a caller that already chose one keeps it.
SUITE_RATE_LIMIT_DIR = tempfile.mkdtemp(prefix="seo-suite-rate-")
os.environ.setdefault(safe_http().RATE_LIMIT_DIR_VAR, SUITE_RATE_LIMIT_DIR)
atexit.register(shutil.rmtree, SUITE_RATE_LIMIT_DIR, True)


def forget_robots(origin: str) -> None:
    """Drop the cached robots.txt answer for `origin`, if there is one.

    Called when a fixture server stops, which is the rule the directory alone cannot
    state: **an answer must not outlive the server that gave it.** For a real host it
    outliving one request is the point; for a throwaway origin whose port the system
    will hand to the next test it is the defect above.
    """
    module = safe_http()
    path = module._robots_cache_path(origin)
    for name in (path, path + ".lock"):
        try:
            os.remove(name)
        except OSError:
            pass


def substitute(root: str, needle: str, replacement: str) -> None:
    """Rewrite `needle` in every textual file under `root`."""
    for folder, _dirs, files in os.walk(root):
        for name in files:
            if not name.endswith(TEXTUAL):
                continue
            path = os.path.join(folder, name)
            with open(path, encoding="utf-8", errors="replace") as f:
                text = f.read()
            if needle in text:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(text.replace(needle, replacement))


class _Quiet(http.server.SimpleHTTPRequestHandler):
    """SimpleHTTPRequestHandler with a fixed document root and no access log."""

    root = ""
    response_headers: dict[str, str] = {}
    # Whether this origin compresses textual responses the way a competently
    # configured server does. Off by default, and on for the `good` tree only.
    #
    # It is here because half this registry asks about server behaviour, and a
    # fixture pair that answers identically on a server question cannot tell a good
    # site from a bad one. `TE-170` *Configure Server Rewrites & Headers* is the
    # case: uncompressed text is graded `error` since 0.50.0, and with neither
    # origin compressing anything, the exemplary tree failed the item for a property
    # of the test harness. Serving gzip here is the repair; declaring both sides
    # FAIL would have been a note about the harness in place of the fixture doing
    # its job.
    gzip_text = False

    def translate_path(self, path):
        rel = path.split("?", 1)[0].split("#", 1)[0].lstrip("/")
        return os.path.join(self.root,
                            *[p for p in rel.split("/") if p not in ("", ".", "..")])

    def log_message(self, *args):  # noqa: D102 - silence the access log
        pass

    def end_headers(self):
        for key, value in self.response_headers.items():
            self.send_header(key, value)
        super().end_headers()

    def send_head(self):
        """Serve gzip for textual files when the origin offers it and the client asks.

        Content negotiation, both halves: a client that did not send
        `Accept-Encoding: gzip` still gets the plain bytes, because a server that
        compresses regardless is a different defect from the one this models. The
        response carries the compressed length, so `Content-Length` stays truthful —
        `cache_compression_checker.py` reads it, and a size that describes the
        uncompressed file would be a fixture lying about the thing under test.
        """
        if not self.gzip_text:
            return super().send_head()
        # The base class answers validators with `304 Not Modified`, and this
        # fixture's own access log is full of 304s. A server that ignores a validator
        # it just sent is a worse fixture than one that does not compress, so let the
        # base class preserve conditional-request semantics before the gzip path.
        if self.headers.get("If-Modified-Since") or self.headers.get("If-None-Match"):
            return super().send_head()
        accepted = self.headers.get("Accept-Encoding") or ""
        path = self.translate_path(self.path)
        # A request for `/` translates to a directory, and a directory name does not
        # end in `.html`. Resolving the index here rather than testing the raw path
        # is the difference between compressing the fixture and compressing every
        # page of it *except its entry* — which is the one page most items are
        # audited on, and which made the first version of this look like the whole
        # feature did nothing.
        if os.path.isdir(path):
            # A directory requested without its trailing slash is a 301 to the slashed
            # form, and that redirect is load-bearing: the crawler's dedup test asserts
            # it, and serving the index here instead turned a 301 into a 200 and broke
            # a check that has nothing to do with compression. Hand those back to the
            # base class rather than reimplementing its rule.
            if not self.path.split("?", 1)[0].endswith("/"):
                return super().send_head()
            for index in ("index.html", "index.htm"):
                candidate = os.path.join(path, index)
                if os.path.isfile(candidate):
                    path = candidate
                    break
        if "gzip" not in accepted.lower() or not path.endswith(TEXTUAL):
            return super().send_head()
        try:
            with open(path, "rb") as handle:
                body = gzip.compress(handle.read())
                modified = os.fstat(handle.fileno()).st_mtime
        except OSError:
            return super().send_head()
        self.send_response(200)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Vary", "Accept-Encoding")
        # The base class sends this on every file it serves, and dropping it here
        # would have made compression cost the fixture a validator header — a
        # `No validator header` finding introduced by the thing meant to remove a
        # finding. A server that compresses still answers conditional requests.
        self.send_header("Last-Modified", self.date_time_string(int(modified)))
        self.end_headers()
        return io.BytesIO(body)


class _Site:
    """One served fixture tree on its own port.

    Rewriting happens in two passes because the second placeholder needs a port that
    does not exist until the *other* site has bound one: `_rewrite()` fixes this
    site's own URLs at construction, and `link_external()` is called by `FixtureSite`
    once both ports are known.
    """

    def __init__(self, source: str, into: str, *, tls: bool = False,
                 response_headers: dict[str, str] | None = None,
                 gzip_text: bool = False):
        self.dir = shutil.copytree(source, into)
        socketserver.ThreadingTCPServer.allow_reuse_address = True
        # Threading: several evidence scripts fetch concurrently, and a
        # single-threaded server deadlocks the moment one of them holds a connection
        # open while asking for the next page.
        handler = type("Handler", (_Quiet,), {
            "root": self.dir,
            "response_headers": dict(response_headers or {}),
            "gzip_text": gzip_text,
        })
        self.server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), handler)
        self.server.daemon_threads = True
        if tls:
            self.server.socket = tls_context().wrap_socket(self.server.socket,
                                                           server_side=True)
        self.port = self.server.server_address[1]
        self.base = f"{'https' if tls else 'http'}://127.0.0.1:{self.port}"
        self._rewrite()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def _rewrite(self) -> None:
        """Point every absolute URL in this tree at the port we actually got."""
        substitute(self.dir, PLACEHOLDER, self.base)

    def link_external(self, other_base: str) -> None:
        """Point this tree's external-link placeholder at the neighbouring origin."""
        substitute(self.dir, PLACEHOLDER_EXTERNAL, other_base)

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        # The port goes back to the system; the answer this origin gave must not
        # outlive it. See `forget_robots`.
        forget_robots(self.base)


class FixtureSite:
    """The fixture trees over paired HTTP and HTTPS origins.

    `good`, `broken`, `good_tls`, and `broken_tls` are absolute URLs ending in `/`.
    The HTTPS pair deliberately differs only in response-header policy: `good_tls`
    emits the hardened set and `broken_tls` emits none. The good origins also
    compress textual responses and the broken ones do not, which is the same kind of
    difference one layer down. Use as a context manager or call `start()`/`stop()`.
    """

    GOOD_TLS_HEADERS = {
        "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
        "Content-Security-Policy": "default-src 'self'",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    }

    def __init__(self, source: str = FIXTURES):
        self.source = source
        self.dir = ""
        self._sites: dict[str, _Site] = {}
        self._artifacts: dict[str, str] = {}

    def start(self) -> "FixtureSite":
        self.dir = tempfile.mkdtemp(prefix="seo-fixture-")
        # The fourth column is compression, and it belongs to the good tree for the
        # same reason the hardened header set does: half this registry asks about
        # server behaviour, and a pair that answers identically on a server question
        # cannot tell a good site from a bad one. Both good origins serve gzip to a
        # client that asks; neither broken origin does.
        origins = (
            ("good", "good", False, {}, True),
            ("broken", "broken", False, {}, False),
            ("good_tls", "good", True, self.GOOD_TLS_HEADERS, True),
            ("broken_tls", "broken", True, {}, False),
        )
        for name, source_name, tls, headers, gzip_text in origins:
            src = os.path.join(self.source, source_name)
            if os.path.isdir(src):
                self._sites[name] = _Site(src, os.path.join(self.dir, name), tls=tls,
                                          response_headers=headers,
                                          gzip_text=gzip_text)
                if not tls:
                    self._copy_artifacts(name)
        # Each site's external links point at its same-protocol neighbour, once both
        # ports are known. A site served alone keeps the unbound placeholder, which
        # fails loudly rather than silently reaching the internet.
        for left_name, right_name in (("good", "broken"),
                                      ("good_tls", "broken_tls")):
            if left_name in self._sites and right_name in self._sites:
                left, right = self._sites[left_name], self._sites[right_name]
                left.link_external(right.base)
                right.link_external(left.base)
        return self

    def _copy_artifacts(self, name: str) -> None:
        """Stage this site's browser-measured artifacts, outside its document root.

        The `url` inside each one is rewritten to the port the site actually bound,
        and that is load-bearing rather than tidy: the runner refuses an artifact
        describing a different page than the one being audited, so an unrewritten
        file would arrive as NO_DATA with a reason instead of as evidence.
        """
        src = os.path.join(self.source, ARTIFACTS, name)
        if not os.path.isdir(src):
            return
        dest = shutil.copytree(src, os.path.join(self.dir, f"{ARTIFACTS}-{name}"))
        substitute(dest, PLACEHOLDER, self._sites[name].base)
        self._artifacts[name] = dest

    def artifact(self, name: str, filename: str) -> str:
        """Path to one staged artifact, or "" when this fixture has none."""
        folder = self._artifacts.get(name, "")
        path = os.path.join(folder, filename) if folder else ""
        return path if path and os.path.exists(path) else ""

    def origin(self, name: str) -> str:
        return self._sites[name].base

    def environment(self, name: str) -> dict:
        """Offline child environment, trusting the fixture CA only for TLS origins."""
        return tls_env() if name.endswith("_tls") else offline_env()

    @property
    def good(self) -> str:
        return self._sites["good"].base + "/"

    @property
    def broken(self) -> str:
        return self._sites["broken"].base + "/"

    @property
    def labels(self) -> tuple[str, ...]:
        """The origins this harness actually served, in the order it built them.

        `openspec/specs/declarations/` DEC-14 asks that a declared origin be a
        fixture origin, and until 0.103.0 the only thing standing between a corpus
        tree and a declaration was a `KeyError` from `RESULTS[label]` — a crash that
        sends a reader to repair the harness rather than to remove the declaration.
        Naming the set here is what lets that be an argued refusal instead.
        """
        return tuple(self._sites)

    @property
    def good_tls(self) -> str:
        return self._sites["good_tls"].base + "/"

    @property
    def broken_tls(self) -> str:
        return self._sites["broken_tls"].base + "/"

    def stop(self) -> None:
        for site in self._sites.values():
            site.stop()
        self._sites.clear()
        shutil.rmtree(self.dir, ignore_errors=True)

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()


class _Routed(http.server.BaseHTTPRequestHandler):
    """Serve a routing table, and remember what was asked for."""

    routes: dict = {}
    seen: list = []

    protocol_version = "HTTP/1.1"          # so keep-alive works and nothing hangs

    def _resolve(self):
        path = self.path.split("#", 1)[0]
        # Exact match first, then the same path without its query. A script that
        # appends `?` to a URL is asking for the same document.
        for candidate in (path, path.split("?", 1)[0]):
            if candidate in self.routes:
                return self.routes[candidate]
        return None

    def _respond(self, body_too: bool):
        type(self).seen.append((self.command, self.path))
        found = self._resolve()
        if found is None:
            self.send_response(404)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", "9")
            self.end_headers()
            if body_too:
                self.wfile.write(b"not found")
            return

        status, headers, body = found
        raw = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(status)
        sent = {k.lower() for k in headers}
        if "content-type" not in sent:
            self.send_header("Content-Type", "text/html; charset=utf-8")
        for key, value in headers.items():
            self.send_header(key, value)
        # Always, and computed rather than taken from `headers`: a wrong length is
        # a hang, and a test that hangs is worse than one that fails.
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        if body_too:
            self.wfile.write(raw)

    def do_GET(self):
        self._respond(True)

    def do_HEAD(self):
        self._respond(False)

    def do_POST(self):
        # The body is read and discarded rather than ignored: with keep-alive an
        # unread body becomes the next request's first line, and the symptom is a
        # test that hangs somewhere else. Answered at all so `requested` can show
        # that a submission went out — a POST is the one thing the response cache
        # must never replay from disk.
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length > 0:
            self.rfile.read(length)
        self._respond(True)

    def log_message(self, *args):
        pass


class Served:
    """A throwaway origin whose every response a test decides.

    Routes map a path to what the server returns. Values are written the shortest way
    that is unambiguous:

        "/"             : "<html>…"                     → 200, text/html
        "/robots.txt"   : (200, "User-agent: *")        → 200, text/html
        "/x"            : (301, {"Location": "/y"}, "") → status, headers, body

    Anything not routed is a real 404 — which is usually what a test wants, because
    "the site does not have a robots.txt" is a case, not an oversight.

    `requested` is what the server actually received, so a test can assert the thing
    no output field shows: that a script honoured a `Disallow`, or fetched the entry
    URL once rather than nine times.
    """

    def __init__(self, routes: dict, tls: bool = False):
        self.routes = {path: _normalise(value) for path, value in routes.items()}
        handler = type("Handler", (_Routed,), {"routes": self.routes, "seen": []})
        self.handler = handler
        socketserver.ThreadingTCPServer.allow_reuse_address = True
        # Threading, for the same reason FixtureSite needs it: several of these
        # scripts fetch concurrently, and a single-threaded server deadlocks the
        # moment one worker holds a connection while another asks for a page.
        self.server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), handler)
        self.server.daemon_threads = True
        self.tls = tls
        if tls:
            # HTTPS matters here for one reason: `safe_http` sets `verify=True` and
            # never relaxes it, so until something in this suite could speak TLS, the
            # HTTPS items and every HSTS check had verdicts from stubs only. The CA is
            # handed to the script through `REQUESTS_CA_BUNDLE` — see `tls_env` — which
            # keeps certificate *verification* switched on while trusting one cert for
            # one test. Disabling verification instead would have made the test pass
            # while removing the property it is testing.
            self.server.socket = tls_context().wrap_socket(self.server.socket,
                                                           server_side=True)
        self.port = self.server.server_address[1]
        self.base = f"{'https' if tls else 'http'}://127.0.0.1:{self.port}"
        self.url = self.base + "/"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def rewrite(self, needle: str, replacement: str = "") -> "Served":
        """Point a placeholder in the routed bodies and headers at this origin.

        Needed because a canonical, a sitemap entry and a `Location` header all have
        to name the port, and the port does not exist until the socket is bound. Same
        two-pass shape as `_Site._rewrite`, for the same reason.
        """
        replacement = replacement or self.base
        for path, (status, headers, body) in list(self.routes.items()):
            if isinstance(body, str):
                body = body.replace(needle, replacement)
            headers = {k: (v.replace(needle, replacement) if isinstance(v, str) else v)
                       for k, v in headers.items()}
            self.routes[path] = (status, headers, body)
        return self

    @property
    def requested(self) -> list:
        return list(self.handler.seen)

    def paths(self, method: str = "GET") -> list:
        return [p for m, p in self.handler.seen if m == method]

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        # The port goes back to the system; the answer this origin gave must not
        # outlive it. See `forget_robots`.
        forget_robots(self.base)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.stop()


def _normalise(value) -> tuple:
    if isinstance(value, (str, bytes)):
        return (200, {}, value)
    if len(value) == 2:
        status, rest = value
        if isinstance(rest, dict):
            return (status, rest, "")
        return (status, {}, rest)
    return tuple(value)


class allow_loopback:
    """Let the SSRF guard through, and switch pacing off, for the duration.

    A context manager rather than a fixture-wide setting: these are process
    environment variables read at call time, and a test that leaves them set changes
    the behaviour of every test that runs after it in the same process — including the
    ones whose whole point is that loopback is refused by default.
    """

    VARS = {"SEO_ALLOW_PRIVATE": "1", "SEO_MAX_RPS": "0"}

    def __enter__(self):
        self.saved = {k: os.environ.get(k) for k in self.VARS}
        os.environ.update(self.VARS)
        return self

    def __exit__(self, *exc):
        for key, was in self.saved.items():
            if was is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = was


class own_rate_limit_dir:
    """A pacing-and-robots directory nothing outside this scope writes to.

    Same shape and the same reason as `allow_loopback`: an environment variable read
    at call time, restored on exit so a test cannot decide where the next one keeps
    its state. The suite-wide directory above is the floor; this is for the classes
    that want their own — the pacing tests, whose whole subject is what is in those
    files, and the cache tests, whose recycled ports are what made this necessary.
    """

    def __enter__(self) -> str:
        self.path = tempfile.mkdtemp(prefix="test-rate-")
        self.var = safe_http().RATE_LIMIT_DIR_VAR
        self.saved = os.environ.get(self.var)
        os.environ[self.var] = self.path
        return self.path

    def __exit__(self, *exc):
        if self.saved is None:
            os.environ.pop(self.var, None)
        else:
            os.environ[self.var] = self.saved
        shutil.rmtree(self.path, ignore_errors=True)


def served(routes: dict, tls: bool = False) -> Served:
    """`with served({...}) as site:` — see `Served`. `tls=True` serves it over HTTPS."""
    return Served(routes, tls=tls)


_TLS = {}


def tls_context():
    """A TLS context for 127.0.0.1, from a certificate generated once per process.

    `openssl` rather than a bundled key pair: a committed certificate expires, and a
    test that starts failing on a date nobody chose is worse than one that skips when a
    tool is absent. Raises `unittest.SkipTest` when openssl is not on PATH, so the
    HTTPS shape reports itself as unexercised rather than silently not running.
    """
    import ssl
    import unittest
    if "context" in _TLS:
        return _TLS["context"]
    folder = tempfile.mkdtemp(prefix="seo-tls-")
    cert, key = os.path.join(folder, "cert.pem"), os.path.join(folder, "key.pem")
    # Through `spawn`, and this call is why the rule is tree-wide rather than a note
    # on two functions. It used to be a bare `subprocess.run`, so the openssl child
    # forked, hit Apple's atfork handler and died of signal 11 — and the `except`
    # below turned that into `SkipTest("openssl unavailable")`. openssl was installed
    # and fine. **So the TLS shape 0.14.0 announced as "exercised live" had never once
    # run on the machine it was written on**, and the message named the wrong cause,
    # which is the failure this whole tree is built to refuse.
    try:
        proc = spawn(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                      "-keyout", key, "-out", cert, "-days", "2",
                      "-subj", "/CN=127.0.0.1",
                      "-addext", "subjectAltName=IP:127.0.0.1"],
                     env=os.environ.copy(), timeout=120)
    except OSError as exc:
        raise unittest.SkipTest(f"openssl could not be run, so the HTTPS shape "
                                f"cannot be served: {exc}") from exc
    if proc.returncode != 0:
        # Named apart from "not installed", because they call for opposite responses:
        # one is a machine without openssl, the other is a bug in this harness.
        raise unittest.SkipTest(
            f"openssl exited {proc.returncode} generating a test certificate, so the "
            f"HTTPS shape cannot be served: {(proc.stderr or '').strip()[:300]}")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    _TLS.update(context=context, cert=cert)
    return context


def tls_env(**extra) -> dict:
    """`offline_env` plus the one certificate the HTTPS fixture is signed with.

    Both variables: `requests` reads `REQUESTS_CA_BUNDLE`, and anything falling through
    to `ssl` reads `SSL_CERT_FILE`. Verification stays on — this widens trust to one
    self-signed certificate rather than turning the check off.
    """
    tls_context()
    return offline_env(REQUESTS_CA_BUNDLE=_TLS["cert"], SSL_CERT_FILE=_TLS["cert"],
                       **extra)


def spawn(args, env=None, timeout=600, stdin_text=None):
    """`subprocess.run` for a child process, on the one code path that survives macOS.

    Every test module that runs a script or an audit goes through here, and the reason
    is a platform bug rather than tidiness. CPython uses `fork` + `exec` whenever
    `close_fds` is true or a `cwd` is given, and on macOS Apple's Network.framework
    installs a `pthread_atfork` child handler — `nw_settings_child_has_forked` — that
    dereferences freed state and segfaults **in the child, before it execs**, once the
    framework has been initialised anywhere in the parent. The crash report says it
    plainly:

        fork → _pthread_atfork_child_handlers → nw_settings_child_has_forked
             → nw_path_release_globals → NEFlowDirectorDestroy → os_log → SIGSEGV

    Nothing in the child's own code has run at that point, so the failure is silent:
    signal 11, empty stdout, empty stderr. It took this suite from green to eight
    failures depending only on which module ran first — `tests/test_shapes.py` passed
    alone and its audits died under `discover`, because by then some earlier module had
    touched the framework.

    `close_fds=False` with no `cwd` is what makes CPython choose `posix_spawn`, which
    does not fork and therefore never runs those handlers. A child inherits this
    process's descriptors for the moment before exec; in a test suite that costs
    nothing, and `checklist_runner.run_script` now does the same thing for the same
    reason.

    There is deliberately no `cwd` parameter. It had one, unused, and an unused
    parameter that silently reopens the bug is worse than no parameter: a child that
    needs a working directory should be given a tool flag that takes one (`git -C`) or
    absolute paths.
    """
    # The condition nobody reads until it bites. CPython chooses `posix_spawn` only
    # when `os.path.dirname(executable)` is non-empty — a bare `"openssl"` or `"git"`
    # goes back through `fork`+`exec` however carefully everything else is set, and on
    # macOS that child dies before it execs. 0.14.0's fix worked for every call that
    # passed `sys.executable`, which is absolute, and silently did nothing for the
    # calls that named a binary on `PATH`.
    args = list(args)
    if args and isinstance(args[0], str) and not os.path.dirname(args[0]):
        import shutil
        args[0] = shutil.which(args[0]) or args[0]
    kwargs = {"capture_output": True, "text": True, "timeout": timeout,
              "env": env or offline_env()}
    if stdin_text is not None:
        kwargs["input"] = stdin_text
    import subprocess
    # `close_fds` spelled out at the call rather than folded into `kwargs`, so the
    # tree-wide rule in `test_runner.py` can see it. A guard that a helper can hide
    # from is a guard that stops at the helper.
    return subprocess.run(args, close_fds=False, **kwargs)


def offline_env(**extra) -> dict:
    """The environment an evidence script gets in these tests.

    `SEO_ALLOW_PRIVATE` because the fixture is on loopback and the guard is doing its
    job. `SEO_MAX_RPS=0` because pacing is a courtesy to somebody else's server and
    there is nobody else here — four requests a second would make the suite take
    minutes to be polite to itself. Every credential is cleared: a machine that
    happens to have a Search Console key must not make these tests do something a
    CI runner cannot.
    """
    env = dict(os.environ)
    env.update({
        "SEO_ALLOW_PRIVATE": "1",
        "SEO_MAX_RPS": "0",
        "PYTHONPATH": os.path.join(os.path.dirname(HERE), "skills", "seo-checklist",
                                   "scripts"),
    })
    for key in ("GSC_CREDENTIALS_PATH", "GV_SA_KEY", "GOOGLE_SAFE_BROWSING_KEY",
                "PAGESPEED_API_KEY", "INDEXNOW_KEY"):
        env.pop(key, None)
    env.update(extra)
    return env
