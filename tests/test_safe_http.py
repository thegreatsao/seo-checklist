"""The SSRF guard and the address-pinned transport behind every safe fetch.

These tests stop at Requests' adapter seam: no case needs DNS or a socket, but the
real URL preparation, redirect loop, cache and pool selection all remain in the path.
"""
from __future__ import annotations

import os
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "skills/seo-checklist/scripts"
sys.path.insert(0, str(SCRIPTS))

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import spawn  # noqa: E402
from lib import safe_http as sh  # noqa: E402


PUBLIC_A = "93.184.216.34"
PUBLIC_B = "8.8.8.8"
LOOPBACK = "127.0.0.1"
METADATA = "169.254.169.254"


def answer(ip: str, port: int = 80):
    """One getaddrinfo-shaped stream address."""
    if ":" in ip:
        return [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", (ip, port, 0, 0))]
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]


def response_for(request, status=200, headers=None, body=b"ok"):
    made = sh.requests.Response()
    made.status_code = status
    made.reason = "OK" if status == 200 else "Found"
    made.url = request.url
    made.request = request
    made.headers = sh.CaseInsensitiveDict(headers or {})
    made._content = body
    made._content_consumed = True
    return made


class PinnedTransport(unittest.TestCase):

    def setUp(self):
        self.saved = {name: os.environ.get(name) for name in
                      ("SEO_ALLOW_PRIVATE", "SEO_HTTP_CACHE", "SEO_MAX_RPS")}
        os.environ.pop("SEO_ALLOW_PRIVATE", None)
        os.environ.pop("SEO_HTTP_CACHE", None)
        os.environ["SEO_MAX_RPS"] = "0"
        sh._announced_private = False

    def tearDown(self):
        for name, value in self.saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        sh._announced_private = False

    def test_dns_rebinding_connects_only_to_the_answer_the_guard_validated(self):
        """Fails on v0.58.0, which discards the first answer and resolves again."""
        lookups = []
        connected = []

        def rebinding(host, port, *args, **kwargs):
            lookups.append(host)
            ip = PUBLIC_A if len(lookups) == 1 else LOOPBACK
            return answer(ip, port)

        def send(adapter, request, **kwargs):
            connected.append(adapter.pool.host)
            self.assertEqual(request.headers["Host"], "rebind.example")
            return response_for(request)

        with mock.patch.object(sh.socket, "getaddrinfo", side_effect=rebinding), \
                mock.patch.object(sh._PinnedAdapter, "send", new=send):
            result = sh.safe_get("http://rebind.example/")

        self.assertEqual(result.url, "http://rebind.example/")
        self.assertEqual(lookups, ["rebind.example"])
        self.assertEqual(connected, [PUBLIC_A])
        self.assertNotIn(LOOPBACK, connected)

    def test_resolution_failure_is_refused_before_a_request(self):
        """The guard failed open for 0.59.0 because changing its error prose moved
        BL-083; the typed failure contract lets 0.60.0 close that one-release hole."""
        attempted = []

        def request(_session, method, url, **kwargs):
            attempted.append((method, url, kwargs["headers"]))
            prepared = sh.requests.Request(
                method, url, headers=kwargs["headers"]).prepare()
            return response_for(prepared)

        error = socket.gaierror(socket.EAI_AGAIN, "authoritative SERVFAIL")
        with mock.patch.object(sh.socket, "getaddrinfo", side_effect=error), \
                mock.patch.object(sh.requests.Session, "request", new=request), \
                mock.patch.object(sh, "_PinnedAdapter") as pinned:
            with self.assertRaises(sh.HostResolutionError) as caught:
                sh.safe_get("https://servfail.example/")

        import seo_common
        self.assertEqual(seo_common.fetch_error_kind(caught.exception), "unresolved")
        self.assertEqual(attempted, [])
        pinned.assert_not_called()

    def test_private_metadata_and_mapped_loopback_answers_stay_blocked(self):
        always_blocked = ("192.0.0.1", METADATA, "::ffff:127.0.0.1")
        for allowed in (False, True):
            if allowed:
                os.environ["SEO_ALLOW_PRIVATE"] = "1"
            else:
                os.environ.pop("SEO_ALLOW_PRIVATE", None)
            for ip in always_blocked:
                with self.subTest(allow_private=allowed, ip=ip), \
                        mock.patch.object(sh.socket, "getaddrinfo",
                                          return_value=answer(ip)):
                    with self.assertRaises(sh.SafeHTTPError):
                        sh.assert_safe_url("http://answer.example/")

    def test_allow_private_still_permits_a_loopback_request(self):
        os.environ["SEO_ALLOW_PRIVATE"] = "1"
        connected = []

        def send(adapter, request, **kwargs):
            connected.append(adapter.pool.host)
            return response_for(request)

        with mock.patch.object(sh.socket, "getaddrinfo",
                               return_value=answer(LOOPBACK)), \
                mock.patch.object(sh._PinnedAdapter, "send", new=send):
            sh.safe_get("http://fixture.example/")

        self.assertEqual(connected, [LOOPBACK])

    def test_redirect_refuses_a_private_second_hop_without_reusing_the_first_pin(self):
        sent = []

        def resolving(host, port, *args, **kwargs):
            return answer(PUBLIC_A if host == "first.example" else METADATA, port)

        def send(adapter, request, **kwargs):
            sent.append((request.url, adapter.pool.host))
            return response_for(
                request, status=302, headers={"Location": "http://second.example/"})

        with mock.patch.object(sh.socket, "getaddrinfo", side_effect=resolving), \
                mock.patch.object(sh._PinnedAdapter, "send", new=send):
            with self.assertRaises(sh.SafeHTTPError):
                sh.safe_get("http://first.example/")

        self.assertEqual(sent, [("http://first.example/", PUBLIC_A)])

    def test_a_caller_session_keeps_the_same_adapter_objects(self):
        caller = sh.requests.Session()
        before = dict(caller.adapters)
        used = []

        def send(adapter, request, **kwargs):
            used.append(adapter)
            return response_for(request)

        with mock.patch.object(sh.socket, "getaddrinfo",
                               return_value=answer(PUBLIC_A)), \
                mock.patch.object(sh._PinnedAdapter, "send", new=send):
            sh.safe_get("http://session.example/", session=caller)

        self.assertEqual(set(caller.adapters), set(before))
        for prefix, adapter in before.items():
            self.assertIs(caller.adapters[prefix], adapter)
        self.assertNotIn(used[0], before.values())

    def test_one_url_keeps_one_cache_slot_when_its_pin_changes(self):
        calls = 0
        answers = iter((PUBLIC_A, PUBLIC_B))

        def resolving(host, port, *args, **kwargs):
            return answer(next(answers), port)

        def send(adapter, request, **kwargs):
            nonlocal calls
            calls += 1
            return response_for(request, body=b"cached")

        with tempfile.TemporaryDirectory() as cache:
            os.environ["SEO_HTTP_CACHE"] = cache
            with mock.patch.object(sh.socket, "getaddrinfo", side_effect=resolving), \
                    mock.patch.object(sh._PinnedAdapter, "send", new=send):
                first = sh.safe_get("http://cache.example/")
                second = sh.safe_get("http://cache.example/")

        self.assertEqual(first.url, "http://cache.example/")
        self.assertEqual(second.url, first.url)
        self.assertEqual(calls, 1)
        self.assertTrue(second.from_cache)

    def test_connection_errors_try_validated_addresses_in_resolver_order(self):
        tried = []

        def send(adapter, request, **kwargs):
            tried.append(adapter.pool.host)
            if adapter.pool.host == PUBLIC_A:
                raise sh.requests.exceptions.ConnectionError("IPv6-shaped first failure")
            return response_for(request)

        infos = answer(PUBLIC_A) + answer(PUBLIC_B)
        with mock.patch.object(sh.socket, "getaddrinfo", return_value=infos), \
                mock.patch.object(sh._PinnedAdapter, "send", new=send):
            sh.safe_get("http://many.example/")

        self.assertEqual(tried, [PUBLIC_A, PUBLIC_B])

    def test_https_pool_uses_the_original_name_for_sni_and_certificate_matching(self):
        adapter = sh._PinnedAdapter("https://tls.example:444/", PUBLIC_A)
        self.addCleanup(adapter.close)
        self.assertEqual(adapter.pool_key, ("https", PUBLIC_A, 444))
        self.assertEqual(adapter.pool.host, PUBLIC_A)
        self.assertEqual(adapter.pool.assert_hostname, "tls.example")
        self.assertEqual(adapter.pool.conn_kw["server_hostname"], "tls.example")


class CertificateVerificationCannotBeTurnedOff(unittest.TestCase):
    """`openspec/specs/http/` HTTP-11. An audit that reports on a site's security while
    accepting any certificate is making a claim it did not check, and the failure is
    silent by construction: everything works better with verification off.

    The guarantee was one unconditional assignment with no test. Two halves are needed
    and the second is the one the requirement's own Reader line asked for — the suite
    runs exactly this shape of census for the HTML parser (`tests/test_parser.py`) and
    ran none for TLS, so a checker reaching past the substrate was unopposed.
    """

    def sent(self, **caller):
        """The kwargs the adapter actually received, whatever the caller asked for."""
        seen = {}

        def send(adapter, request, **kwargs):
            seen.update(kwargs)
            return response_for(request)

        with mock.patch.object(sh.socket, "getaddrinfo",
                               side_effect=lambda h, p, *a, **k: answer(PUBLIC_A, p)), \
                mock.patch.object(sh._PinnedAdapter, "send", new=send):
            sh.safe_get("https://tls.example/", **caller)
        return seen

    def test_a_caller_asking_for_no_verification_is_overruled(self):
        self.assertIs(self.sent(verify=False)["verify"], True)

    def test_verification_is_on_when_nobody_mentions_it(self):
        self.assertIs(self.sent()["verify"], True)

    def test_a_caller_supplying_a_bundle_path_is_also_overruled(self):
        """`verify="/some/ca.pem"` is not laxer than the default, but it is a second
        way for a caller to decide the question, and HTTP-11 says no caller decides
        it. Recorded here so a later relaxation is a deliberate edit to this test."""
        self.assertIs(self.sent(verify="/nonexistent/ca.pem")["verify"], True)

    def test_no_script_turns_verification_off_behind_the_substrate(self):
        """The census. A checker that calls `requests` directly bypasses every
        guarantee here, and this is the one that would be invisible in a report: the
        page fetches, the audit passes, and nothing was verified.

        Structural rather than textual, so `verify = False` spelled any way is caught,
        and a docstring quoting the phrase is not.
        """
        import ast

        def is_off(node):
            return isinstance(node, ast.Constant) and node.value in (False, 0)

        offenders = []
        for path in sorted(SCRIPTS.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    for word in node.keywords:
                        if word.arg == "verify" and is_off(word.value):
                            offenders.append(f"{path.name}:{node.lineno}")
                elif isinstance(node, ast.Assign) and is_off(node.value):
                    for target in node.targets:
                        if getattr(target, "attr", "") == "verify":
                            offenders.append(f"{path.name}:{node.lineno}")
        self.assertEqual(offenders, [],
                         "these disable certificate verification; every request goes "
                         "through lib/safe_http, which sets verify=True and means it")

    # The one place an unverified handshake is legitimate, and why. `tls_certificate.py`
    # decides `valid` on a verifying pass first; the second pass exists only to read a
    # certificate that already failed, so the report can say what was wrong with it. An
    # allowlist of one, named with its reason, because a census whose exceptions are
    # unexplained stops being read.
    UNVERIFIED_ALLOWED = {"tls_certificate.py"}

    def test_no_script_reaches_past_requests_to_turn_verification_off(self):
        """The gap an independent review found in the census above: it recognises
        `verify=False` and nothing else, so a script disabling TLS through an SSL
        context — `ssl._create_unverified_context()`, `check_hostname = False`,
        `verify_mode = ssl.CERT_NONE` — walked past it. `verify=` is one spelling of
        this decision, not the decision.
        """
        import ast

        offenders = []
        for path in sorted(SCRIPTS.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call)
                        and getattr(node.func, "attr", "") == "_create_unverified_context"
                        and path.name not in self.UNVERIFIED_ALLOWED):
                    offenders.append(f"{path.name}:{node.lineno} unverified context")
                if not isinstance(node, ast.Assign):
                    continue
                for target in node.targets:
                    attr = getattr(target, "attr", "")
                    value = node.value
                    if attr == "check_hostname" and isinstance(value, ast.Constant)                             and value.value is False:
                        offenders.append(f"{path.name}:{node.lineno} check_hostname off")
                    if attr == "verify_mode" and getattr(value, "attr", "") == "CERT_NONE":
                        offenders.append(f"{path.name}:{node.lineno} CERT_NONE")
        self.assertEqual(offenders, [],
                         "these turn off certificate verification below the requests "
                         "layer, where the substrate's verify=True cannot reach")

    def test_the_one_allowed_exception_still_decides_its_verdict_on_a_verifying_pass(self):
        """An allowlist entry is a claim about a file, and it goes stale the way every
        other unread list in this repository has. This is the claim: the file that may
        build an unverified context also builds a verifying one and requires a
        certificate."""
        source = (SCRIPTS / "tls_certificate.py").read_text(encoding="utf-8")
        for required in ("ssl.create_default_context()", "context.check_hostname = True",
                         "context.verify_mode = ssl.CERT_REQUIRED"):
            with self.subTest(line=required):
                self.assertIn(required, source,
                              "tls_certificate.py is allowed an unverified handshake "
                              "only because its verdict comes from a verifying one")



class TheRobotsFetchGoesThroughTheGuardToo(unittest.TestCase):
    """`openspec/specs/http/` HTTP-1 says *every* request is validated before it is made
    and connects to the address that was validated. One request in this module was not:
    `_fetch_robots` called `requests.get` directly, so every origin's `/robots.txt` — the
    first request made to any host the audit touches — went out with no guard and no pin.

    The comment on it named a real constraint rather than an oversight: `safe_get` consults
    `robots.txt`, so fetching `robots.txt` through it would recurse. That argues against
    reusing `safe_get`; it does not argue for skipping the guard, which is a separate
    mechanism one level below. `_validated_url` and `_PinnedAdapter` are both callable
    without touching robots at all.

    Three holes, one per test below, in order of what they cost:

    * a host that resolves to an address the guard blocks is contacted anyway. The audit
      refuses to fetch its pages and fetches its `robots.txt` — from a link-local address,
      the metadata service included;
    * the answer the guard would have validated is discarded and the name is resolved
      again by the transport, which is the rebinding case `safe_get` was pinned against in
      0.58.0, still open here;
    * a redirect is followed to wherever it points, so a public `robots.txt` that answers
      302 to `169.254.169.254` reaches it.

    These stop at the same adapter seam as the rest of this file, and each asserts that
    *nothing went out* rather than that an exception was raised: fail-open is deliberate
    here (see `_fetch_robots`), so a blocked origin must yield an empty policy — the
    refusal must cost no request, not turn into an audit failure.
    """

    def setUp(self):
        self.saved = {name: os.environ.get(name) for name in
                      ("SEO_ALLOW_PRIVATE", "SEO_HTTP_CACHE", "SEO_MAX_RPS",
                       "SEO_RATE_LIMIT_DIR")}
        os.environ.pop("SEO_ALLOW_PRIVATE", None)
        os.environ.pop("SEO_HTTP_CACHE", None)
        os.environ["SEO_MAX_RPS"] = "0"
        # Its own state directory, or a cached robots.txt from another test — or another
        # run on this machine — decides the answer and nothing is fetched at all.
        self.state = tempfile.mkdtemp(prefix="seo-robots-guard-")
        os.environ["SEO_RATE_LIMIT_DIR"] = self.state
        sh._announced_private = False

    def tearDown(self):
        for name, value in self.saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        sh._announced_private = False

    def test_a_blocked_origin_is_not_asked_for_its_robots_txt(self):
        """The audit will not fetch this host's pages. It must not fetch its rules."""
        sent = []

        def send(adapter, request, **kwargs):
            sent.append(request.url)
            return response_for(request, body=b"User-agent: *\nDisallow:\n")

        with mock.patch.object(sh.socket, "getaddrinfo",
                               side_effect=lambda *a, **k: answer(METADATA, 80)), \
                mock.patch.object(sh.requests.adapters.HTTPAdapter, "send", new=send):
            text = sh._robots_text_once("http://metadata.example",
                                        "metadata.example",
                                        sh._robots_cache_path("http://metadata.example"))

        self.assertEqual(sent, [], "robots.txt was fetched from a guarded address")
        self.assertEqual(text, "", "a blocked origin must yield no policy, fail-open")

    def test_the_robots_fetch_connects_to_the_answer_the_guard_validated(self):
        """The rebinding case, one request earlier than the one 0.58.0 pinned."""
        lookups, connected = [], []

        def rebinding(host, port, *args, **kwargs):
            lookups.append(host)
            return answer(PUBLIC_A if len(lookups) == 1 else LOOPBACK, port)

        def send(adapter, request, **kwargs):
            connected.append(getattr(getattr(adapter, "pool", None), "host", None))
            return response_for(request, body=b"User-agent: *\nDisallow:\n")

        with mock.patch.object(sh.socket, "getaddrinfo", side_effect=rebinding), \
                mock.patch.object(sh._PinnedAdapter, "send", new=send), \
                mock.patch.object(sh.requests.adapters.HTTPAdapter, "send", new=send):
            sh._robots_text_once("http://rebind.example", "rebind.example",
                                 sh._robots_cache_path("http://rebind.example"))

        self.assertEqual(lookups, ["rebind.example"],
                         "the name was resolved more than once, so the address the "
                         "guard validated is not the address the transport used")
        self.assertEqual(connected, [PUBLIC_A])
        self.assertNotIn(LOOPBACK, connected)

    def test_a_redirect_to_a_blocked_address_is_not_followed(self):
        """A public robots.txt answering 302 to the metadata service is the same hole
        wearing a hop. The second address gets its own validation, exactly as
        `safe_request` gives every hop of a page fetch."""
        sent = []

        def resolve(host, port, *args, **kwargs):
            return answer(PUBLIC_A if host == "public.example" else METADATA, port)

        def send(adapter, request, **kwargs):
            sent.append(request.url)
            if request.url.endswith("/robots.txt") and "public.example" in request.url:
                return response_for(request, status=302,
                                    headers={"Location": "http://metadata.example/x"})
            return response_for(request, body=b"User-agent: *\nDisallow: /\n")

        with mock.patch.object(sh.socket, "getaddrinfo", side_effect=resolve), \
                mock.patch.object(sh._PinnedAdapter, "send", new=send), \
                mock.patch.object(sh.requests.adapters.HTTPAdapter, "send", new=send):
            text = sh._robots_text_once("http://public.example", "public.example",
                                        sh._robots_cache_path("http://public.example"))

        self.assertNotIn("http://metadata.example/x", sent,
                         "a robots.txt redirect reached a guarded address")
        self.assertEqual(text, "", "an unfollowable redirect yields no policy, fail-open")


class TheAgentIdentifiesItselfOnTheWire(unittest.TestCase):
    """`openspec/specs/http/` HTTP-6. Politeness that cannot be declined is not politeness:
    a site owner's only lever is a `robots.txt` rule, and it works only if the token this
    audit sends is stable and matchable.

    The token half was read — a rule naming it beats the wildcard, and it carries no slash
    so the matcher cannot read it as a browser name. What no test named was the other end
    of the same sentence: what actually leaves the substrate. `AGENTIC_SEO_USER_AGENT` and
    `DEFAULT_HEADERS` were named by nothing, so the header could have been emptied, renamed
    or overridden per-caller and the suite would have stayed green while every rule written
    against us stopped matching.

    Asserted through a real request rather than against the constants, and with a caller
    supplying its own headers, because that is the case that would break it: `fetch_url`
    passes `extra_headers` straight through, and a caller passing its own `User-Agent`
    must not be able to take the tool's name off the wire.
    """

    def setUp(self):
        self.saved = {name: os.environ.get(name) for name in
                      ("SEO_ALLOW_PRIVATE", "SEO_HTTP_CACHE", "SEO_MAX_RPS")}
        os.environ.pop("SEO_ALLOW_PRIVATE", None)
        os.environ.pop("SEO_HTTP_CACHE", None)
        os.environ["SEO_MAX_RPS"] = "0"

    def tearDown(self):
        for name, value in self.saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    def sent_headers(self, **kwargs):
        seen = []

        def send(adapter, request, **rest):
            seen.append(request.headers)
            return response_for(request)

        with mock.patch.object(sh.socket, "getaddrinfo",
                               side_effect=lambda *a, **k: answer(PUBLIC_A, 80)), \
                mock.patch.object(sh._PinnedAdapter, "send", new=send), \
                mock.patch.object(sh, "robots_allows", return_value=(True, 0.0)):
            sh.safe_get("http://public.example/page", **kwargs)
        self.assertEqual(len(seen), 1)
        return seen[0]

    def test_a_request_carries_the_shared_user_agent(self):
        self.assertEqual(self.sent_headers()["User-Agent"], sh.AGENTIC_SEO_USER_AGENT)

    def test_the_user_agent_names_the_tool_and_where_to_read_about_it(self):
        """The token a site owner blocks has to be findable in the string they see in
        their log, and the string has to say what the thing is."""
        agent = sh.AGENTIC_SEO_USER_AGENT
        self.assertIn(sh.ROBOTS_TOKEN, agent)
        self.assertIn("+http", agent, "the agent names no page explaining what it is")

    def test_a_callers_own_user_agent_does_not_replace_it(self):
        """`default_headers` sets the agent *after* merging the caller's extras, and this
        is the assertion that says so — a caller that could rename the agent could make
        the audit unblockable by accident."""
        headers = self.sent_headers(headers={"User-Agent": "Something/1.0",
                                             "X-Caller": "kept"})
        self.assertEqual(headers["User-Agent"], sh.AGENTIC_SEO_USER_AGENT)
        self.assertEqual(headers["X-Caller"], "kept",
                         "the caller's other headers must still travel")


class ASuccessfulFetchCarriesNoFailure(unittest.TestCase):
    """`openspec/specs/http/` HTTP-9's `iff`, read from the side nothing read.

    Every failure carries a message and a kind, and seven tests assert that direction over
    all seven exception types. The other direction — that a fetch which *succeeded* carries
    neither — was unasserted, and it is the half a downstream consumer depends on:
    `broken_links.py` and everything like it decide "broken" from the presence of the
    field, so a success that left a stale kind behind would report a working URL as a false
    accusation about somebody else's site.

    Read through `seo_common.fetch_url`, which is where the two fields are written, and in
    the three shapes a success can take: a plain 200, a redirect chain, and a 404 — which
    is a *successful fetch of an error page*, not a failed fetch, and is exactly where the
    two ideas are easiest to confuse.
    """

    def setUp(self):
        self.saved = {name: os.environ.get(name) for name in
                      ("SEO_HTTP_CACHE", "SEO_MAX_RPS")}
        os.environ.pop("SEO_HTTP_CACHE", None)
        os.environ["SEO_MAX_RPS"] = "0"

    def tearDown(self):
        for name, value in self.saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    def fetched(self, status=200, headers=None):
        import seo_common

        def send(adapter, request, **kwargs):
            return response_for(request, status=status, headers=headers)

        with mock.patch.object(sh.socket, "getaddrinfo",
                               side_effect=lambda *a, **k: answer(PUBLIC_A, 80)), \
                mock.patch.object(sh._PinnedAdapter, "send", new=send), \
                mock.patch.object(sh, "robots_allows", return_value=(True, 0.0)):
            return seo_common.fetch_url("http://public.example/page")

    def test_a_plain_success_sets_neither_field(self):
        result = self.fetched()
        self.assertEqual(result["status"], 200)
        self.assertIsNone(result.get("error"))
        self.assertIsNone(result.get("error_kind"))

    def test_an_error_status_is_still_a_successful_fetch(self):
        """A 404 is the server answering, not the fetch failing. Filing it as a failure
        would turn every soft-404 audit into a report about this tool's own connectivity."""
        result = self.fetched(status=404)
        self.assertEqual(result["status"], 404)
        self.assertIsNone(result.get("error"))
        self.assertIsNone(result.get("error_kind"))

    def test_the_two_fields_travel_together_or_not_at_all(self):
        """The `iff` as one assertion rather than two: whatever the outcome, a kind
        without a message or a message without a kind is a shape no consumer handles."""
        for status in (200, 301, 404, 500):
            with self.subTest(status=status):
                result = self.fetched(status=status)
                self.assertEqual(result.get("error") is None,
                                 result.get("error_kind") is None)


class TheCacheTellsTheReaderItAnswered(unittest.TestCase):
    """`openspec/specs/http/` HTTP-8. A run records whether the response cache was on, and
    the surface a person is handed says so too.

    The recording half was read from 0.93.x. The other half was a defect rather than a gap:
    `provenance_warnings` covered the parser, the private host, the allowance, the guard,
    the thin entry and the artifacts, and not the cache — so the one fact that separates
    "this is the page" from "this was the page a few minutes ago" sat in the JSON and
    reached nobody. `test_the_provenance_list_still_omits_the_cache` in `test_contract.py` pinned that
    absence and was written to fail at the moment it was closed; it did, and
    `test_the_reader_of_the_report_is_told_the_cache_answered` replaced it.

    What the requirement asks for is narrower than "the cache was on", and the distinction
    is the whole point: a warning printed on every cached run is one a reader learns to
    skip. So the count is of responses actually *handed back* from disk, and these tests
    hold that boundary from both sides — a hit counts, and an entry refused by either replay
    gate does not, because a refused entry never answered anybody.

    The tally lives in the shared state directory beside the pacing slots, because the
    checkers are separate processes and a module global would report zero on every real run.
    Each test gets its own directory: the counter is machine-wide by construction, and two
    audits at once are a known imprecision recorded in the payload comment rather than a
    thing to pretend away.
    """

    def setUp(self):
        self.saved = {name: os.environ.get(name) for name in
                      ("SEO_ALLOW_PRIVATE", "SEO_HTTP_CACHE", "SEO_MAX_RPS",
                       "SEO_RATE_LIMIT_DIR")}
        os.environ.pop("SEO_ALLOW_PRIVATE", None)
        os.environ["SEO_MAX_RPS"] = "0"
        self.state = tempfile.mkdtemp(prefix="seo-hits-")
        self.cache = tempfile.mkdtemp(prefix="seo-cache-")
        os.environ["SEO_RATE_LIMIT_DIR"] = self.state
        os.environ["SEO_HTTP_CACHE"] = self.cache

    def tearDown(self):
        for name, value in self.saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    def fetch(self, **kwargs):
        """One `safe_get` against a public address, served from the adapter seam."""
        def send(adapter, request, **rest):
            return response_for(request, headers={"Cache-Control": "max-age=600"},
                                body=b"<html><body>hello</body></html>")

        with mock.patch.object(sh.socket, "getaddrinfo",
                               side_effect=lambda *a, **k: answer(PUBLIC_A, 80)), \
                mock.patch.object(sh._PinnedAdapter, "send", new=send), \
                mock.patch.object(sh, "robots_allows", return_value=(True, 0.0)):
            return sh.safe_get("http://public.example/page", **kwargs)

    def test_a_response_served_from_disk_is_counted(self):
        before = sh.cache_hit_count()
        self.fetch()
        self.assertEqual(sh.cache_hit_count(), before,
                         "the first fetch was a miss and must not count")
        self.fetch()
        self.assertEqual(sh.cache_hit_count(), before + 1,
                         "the second fetch was answered from disk and was not counted")

    def test_an_entry_the_caller_will_not_accept_is_not_a_hit(self):
        """`_cap_allows` refuses a stored body larger than a later caller's own limit, and
        the request goes out again. Counting that as a hit would tell a reader the verdict
        came from a cached response when it came from a fresh one."""
        self.fetch()
        before = sh.cache_hit_count()
        # It refuses rather than trimming, and refuses exactly as an uncached run would
        # have — HTTP-10's own scenario. What matters here is that the stored entry was
        # not counted as an answer on the way past.
        with self.assertRaises(sh.SafeHTTPError):
            self.fetch(max_response_bytes=4)
        self.assertEqual(sh.cache_hit_count(), before)

    def test_an_entry_robots_no_longer_permits_is_not_a_hit(self):
        """HTTP-7: a cache hit is re-checked against `robots.txt`, because the rules may
        have changed since the response was stored. A refusal is our restraint, not an
        answer, and provenance must not claim otherwise."""
        self.fetch(respect_robots=True)
        before = sh.cache_hit_count()
        # `respect_robots` is off by default — HTTP-5's asymmetry, since the audited URL
        # is one the operator handed us — so the case worth holding is the one a crawl
        # takes, where it is on and the stored entry is re-checked on the way out.
        with self.assertRaises(sh.RobotsDisallowed):
            with mock.patch.object(sh.socket, "getaddrinfo",
                                   side_effect=lambda *a, **k: answer(PUBLIC_A, 80)), \
                    mock.patch.object(sh, "robots_allows", return_value=(False, 0.0)):
                sh.safe_get("http://public.example/page", respect_robots=True)
        self.assertEqual(sh.cache_hit_count(), before)

    def test_the_tally_is_shared_rather_than_per_process(self):
        """The reason it is a file at all. Every checker is its own process, so a count
        kept in memory would be zero in the runner that writes the artifact."""
        self.fetch()
        self.fetch()
        code = ("import sys; sys.path.insert(0, %r); "
                "from lib.safe_http import cache_hit_count; print(cache_hit_count())"
                % str(SCRIPTS))
        proc = spawn([sys.executable, "-c", code], timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(int(proc.stdout.strip()), sh.cache_hit_count())


class TheReportNamesTheCacheOnlyWhenItAnswered(unittest.TestCase):
    """The surface half of HTTP-8, held in both directions.

    One direction is the defect this closed: a run whose verdicts came off disk said
    nothing. The other is why the branch is conditional — the parser warning is silent for
    `lxml` for the same reason, and a provenance list that warns about every run trains its
    reader to stop reading it.
    """

    def warnings(self, **payload):
        sys.path.insert(0, str(SCRIPTS))
        from checklist_report import provenance_warnings
        return provenance_warnings(dict({"html_parser": "lxml"}, **payload))

    def cache_lines(self, **payload):
        return [w for w in self.warnings(**payload) if "cache" in w.lower()]

    def test_a_run_that_answered_from_the_cache_says_so_and_says_how_often(self):
        lines = self.cache_lines(http_cache=True, http_cache_hits=3)
        self.assertEqual(len(lines), 1, self.warnings(http_cache=True, http_cache_hits=3))
        self.assertIn("3", lines[0])

    def test_a_cached_run_that_answered_nothing_from_it_is_silent(self):
        """`http_cache` true and no hits is the ordinary first audit of a site: the cache
        was open and everything missed. Nothing about those verdicts is older than the run,
        so there is nothing to warn about."""
        self.assertEqual(self.cache_lines(http_cache=True, http_cache_hits=0), [])

    def test_a_run_with_no_cache_field_at_all_is_silent(self):
        """Artifacts written before the count existed, read by a later report."""
        self.assertEqual(self.cache_lines(), [])

if __name__ == "__main__":
    unittest.main()
