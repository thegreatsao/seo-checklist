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
    """`specs/http/` HTTP-11. An audit that reports on a site's security while
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


if __name__ == "__main__":
    unittest.main()
