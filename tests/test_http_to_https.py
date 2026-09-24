"""SE-117 *Force HTTPS Across the Site (Single Canonical Protocol)*, and the one request
that decides it: the page's own `http://` address.

Until 0.118.0 the item asserted `https` — whether the audited URL *ended* on https — and
nothing in the tree ever asked the `http://` address. A site serving every page over
both protocols passed, which is the defect the title names: two protocols, no
canonical one, nothing forced. `test_a_site_answering_plain_http_fails_where_the_old_rule_passed_it`
is that site, and it keeps the old field in view so the difference stays readable.

**The `http://` form keeps an explicit port.** `https://host/` becomes `http://host/` —
port 443 to port 80 — but `https://host:8443/` becomes `http://host:8443/`, because a
server told to answer plain HTTP on its TLS port (nginx's `error_page 497`) is the only
thing a non-default port's plain counterpart can mean. That is also what lets this be
tested at all: the harness serves TLS and plain HTTP on one port, chosen by the first
byte of each connection, so `plain=` decides what the plain side of an origin does.

**Four outcomes and a withheld one**, graded by the registry's own `value_map`:
`permanent` (301/308 to https) passes; `temporary` (302/303/307 — Google's *weak*
canonical signal) and `not_listening` (nothing accepts the connection, which
hstspreload.org accepts of a preloaded host) warn; `not_redirected` — content, an
error page, a loop or a Location-less redirect over plain HTTP — fails. A connection
that was accepted and then broken is `unread`, and a site whose only doubt is an unread
page gets no verdict rather than a guessed one.

**Across the site** is the audited page plus up to `HTTP_SAMPLE_PAGES` same-origin pages
it links to, robots.txt permitting. The item's `measures` line says the rest is not
requested.
"""
import json
import os
import socket
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPTS = os.path.join(ROOT, "skills", "seo-checklist", "scripts")
REGISTRY = os.path.join(ROOT, "skills", "seo-checklist", "resources", "config",
                        "checklist.json")
SCRIPT = os.path.join(SCRIPTS, "security_headers.py")
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)

from checklist_runner import FAIL, NO_DATA, PASS, WARN, evaluate  # noqa: E402
from harness import allow_loopback, offline_env, served, spawn, tls_env  # noqa: E402
import security_headers as sh  # noqa: E402

OUTCOMES = {"permanent", "temporary", "not_listening", "not_redirected"}


def rule() -> dict:
    with open(REGISTRY, encoding="utf-8") as f:
        return {i["id"]: i for i in json.load(f)["items"]}["SE-117"]["check"]


def verdict(output: dict) -> str:
    """SE-117's real rule over a real output, graded the way the runner grades."""
    check = rule()
    ok, _ = evaluate(check["assert"], output)
    if ok is None:
        return NO_DATA
    if ok:
        return PASS
    warn = check.get("warn")
    if warn and evaluate(warn, output)[0]:
        return WARN
    return FAIL


def run(url: str, env: dict) -> dict:
    proc = spawn([sys.executable, SCRIPT, url, "--json"], env=env, timeout=120)
    assert proc.returncode == 0, f"exited {proc.returncode}: {proc.stderr[-600:]}"
    return json.loads(proc.stdout)


def page(*hrefs: str) -> str:
    links = "".join(f'<a href="{h}">link</a>\n' for h in hrefs)
    return f"<!doctype html><html><head><title>t</title></head><body>{links}</body></html>"


def closed_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class TheHttpAddressIsAsked(unittest.TestCase):
    """Whole-script runs over a TLS origin whose plain side each test decides."""

    def test_a_permanent_redirect_passes_and_asks_the_sampled_pages_too(self):
        body = page("/a", "/b", "/c", "/d")
        routes = {p: body for p in ("/", "/a", "/b", "/c", "/d")}
        with served(routes, tls=True, plain="redirect") as site:
            out = run(site.url, tls_env())
            plain = site.plain_paths()
            entry_gets = site.paths("GET").count("/")
        self.assertEqual(out["http_to_https"], "permanent", out.get("http_variants"))
        self.assertEqual(verdict(out), PASS)
        # The entry's own http address, then the first three links in document order:
        # `/d` is the fourth and is never asked.
        self.assertEqual(plain, ["/", "/a", "/b", "/c"])
        self.assertEqual([v["outcome"] for v in out["http_variants"]], ["permanent"] * 4)
        # The walk stops at the first https Location rather than following it back to
        # the TLS side, so the entry is fetched over TLS exactly once, by the main read.
        self.assertEqual(entry_gets, 1)

    def test_a_site_answering_plain_http_fails_where_the_old_rule_passed_it(self):
        body = page("/a", "/b")
        with served({"/": body, "/a": body, "/b": body}, tls=True, plain="serve") as site:
            out = run(site.url, tls_env())
            plain = site.plain_paths()
        self.assertIs(out["https"], True)          # the field SE-117 read until 0.118.0
        self.assertEqual(out["http_to_https"], "not_redirected")
        self.assertEqual(verdict(out), FAIL)
        # One page answering over plain HTTP already decides the site; the sample is
        # not asked after that.
        self.assertEqual(plain, ["/"])
        self.assertEqual(out["http_variants"][0]["hops"][0]["status"], 200)

    def test_a_temporary_redirect_is_a_warning(self):
        with served({"/": page()}, tls=True,
                    plain={"/": (302, {"Location": "SELF/"}, "")}) as site:
            site.rewrite("SELF")
            out = run(site.url, tls_env())
        self.assertEqual(out["http_to_https"], "temporary")
        self.assertEqual(verdict(out), WARN)

    def test_a_sampled_page_answering_plain_http_fails_the_site(self):
        body = page("/a", "/b")
        plain = {"/": (301, {"Location": "SELF/"}, ""),
                 "/a": (301, {"Location": "SELF/a"}, ""),
                 "/b": "served over plain HTTP"}
        with served({"/": body, "/a": body, "/b": body}, tls=True, plain=plain) as site:
            site.rewrite("SELF")
            out = run(site.url, tls_env())
            asked = site.plain_paths()
        self.assertEqual(asked, ["/", "/a", "/b"])
        self.assertEqual([v["outcome"] for v in out["http_variants"]],
                         ["permanent", "permanent", "not_redirected"])
        self.assertEqual(out["http_to_https"], "not_redirected")
        self.assertEqual(verdict(out), FAIL)

    def test_a_temporary_redirect_on_a_sampled_page_warns(self):
        body = page("/a")
        plain = {"/": (301, {"Location": "SELF/"}, ""),
                 "/a": (307, {"Location": "SELF/a"}, "")}
        with served({"/": body, "/a": body}, tls=True, plain=plain) as site:
            site.rewrite("SELF")
            out = run(site.url, tls_env())
        self.assertEqual(out["http_to_https"], "temporary")
        self.assertEqual(verdict(out), WARN)

    def test_a_plain_http_loop_and_a_redirect_without_location_are_not_redirects(self):
        for plain in ({"/": (301, {"Location": "/x"}, ""),
                       "/x": (301, {"Location": "/"}, "")},
                      {"/": (301, {}, "")}):
            with self.subTest(plain=plain):
                with served({"/": page()}, tls=True, plain=plain) as site:
                    out = run(site.url, tls_env())
                self.assertEqual(out["http_to_https"], "not_redirected")
                self.assertEqual(verdict(out), FAIL)

    def test_only_same_origin_links_robots_permits_are_sampled(self):
        body = page("/private/x", "#top", "mailto:a@example.invalid",
                    "http://127.0.0.1:9/elsewhere", "https://example.invalid/",
                    "/", "/a#part", "/a", "/b?q=1")
        routes = {"/": body, "/a": body, "/b": body, "/private/x": body,
                  "/robots.txt": (200, {"Content-Type": "text/plain"},
                                  "User-agent: *\nDisallow: /private/\n")}
        with served(routes, tls=True, plain="redirect") as site:
            out = run(site.url, tls_env())
            asked = site.plain_paths()
        # `/private/` is disallowed, the fragment and the mail link are not pages, the
        # two other origins are not this site, `/` is the entry itself and `/a#part` is
        # `/a`. What is left, in document order, is `/a` and `/b?q=1`.
        self.assertEqual(asked, ["/", "/a", "/b?q=1"])
        self.assertEqual(out["http_to_https"], "permanent")

    def test_a_connection_accepted_and_broken_withholds_the_verdict(self):
        """The TLS port closes a plain connection unanswered, as a TLS-only listener
        does. Nothing was said over plain HTTP, so there is nothing to grade."""
        with served({"/": page()}, tls=True, plain=None) as site:
            out = run(site.url, tls_env())
        self.assertNotIn("http_to_https", out)
        self.assertEqual(verdict(out), NO_DATA)
        self.assertEqual(out["http_variants"][0]["outcome"], "unread")
        self.assertTrue(out["http_variants"][0]["error"])
        # A broken plain side is not a failed audit: the header items still decide.
        self.assertIsNone(out["error"])
        self.assertIn("strict-transport-security", out["header_values"])

    def test_a_page_served_over_plain_http_needs_no_second_request(self):
        with served({"/": page("/a"), "/a": page()}) as site:
            out = run(site.url, offline_env())
            gets = site.paths("GET")
        self.assertIs(out["https"], False)
        self.assertEqual(out["http_to_https"], "not_redirected")
        self.assertEqual(verdict(out), FAIL)
        self.assertEqual(gets.count("/"), 1)
        self.assertNotIn("/a", gets)

    def test_an_http_address_that_redirects_is_read_from_its_own_chain(self):
        """Audited as `http://`: the main read already walked the chain, so the
        outcome comes from its history and the address is not asked twice. The TLS
        side refuses plain HTTP, so a second walk would come back `unread`."""
        with served({"/": page()}, tls=True, plain=None) as secure:
            with served({"/": (301, {"Location": secure.url}, "")}) as entry:
                out = run(entry.url, tls_env())
                entry_gets = entry.paths("GET").count("/")
        self.assertIs(out["https"], True)
        self.assertEqual(out["http_to_https"], "permanent", out.get("http_variants"))
        self.assertEqual(entry_gets, 1)


class TheWalkAndTheSummary(unittest.TestCase):
    """The pieces the script is built from, without a whole run."""

    def test_a_port_nothing_listens_on_is_not_listening(self):
        with allow_loopback():
            walked = sh.walk_http_to_https(f"http://127.0.0.1:{closed_port()}/")
        self.assertEqual(walked["outcome"], "not_listening", walked)
        self.assertEqual(verdict({"http_to_https": "not_listening"}), WARN)

    def test_the_summary_takes_the_worst_decided_outcome(self):
        summarize = sh.summarize_http_to_https
        cases = [
            ([], None),
            (["permanent"], "permanent"),
            (["permanent", "not_listening"], "not_listening"),
            (["not_listening", "temporary"], "temporary"),
            (["permanent", "temporary", "unread"], None),
            (["unread", "not_redirected"], "not_redirected"),
            (["permanent", "not_redirected", "temporary"], "not_redirected"),
        ]
        for outcomes, expected in cases:
            with self.subTest(outcomes=outcomes):
                self.assertEqual(summarize(outcomes), expected)

    def test_the_http_form_keeps_a_port_it_was_given(self):
        cases = {
            "https://example.com/a?b=1": "http://example.com/a?b=1",
            "https://example.com:443/": "http://example.com/",
            "https://127.0.0.1:8443/x": "http://127.0.0.1:8443/x",
            "https://[::1]:8443/": "http://[::1]:8443/",
            "https://[::1]/": "http://[::1]/",
            "http://example.com/": "http://example.com/",
        }
        for given, expected in cases.items():
            with self.subTest(url=given):
                self.assertEqual(sh.http_form(given), expected)

    def test_the_sample_size_is_a_counted_constant(self):
        self.assertEqual(sh.HTTP_SAMPLE_PAGES, 3)

    def test_the_codes_are_googles_strong_and_weak_signals(self):
        """Google Search Central, *HTTP status codes, network and DNS errors*: 301 and
        308 are a strong signal that the target should be processed, 302, 303 and 307 a
        weak one — and *Redirects and Google Search* says a temporary redirect is not
        used as a canonical signal at all. A code in neither is not a redirect this item
        accepts."""
        self.assertEqual(sh.PERMANENT_REDIRECTS, (301, 308))
        self.assertEqual(sh.TEMPORARY_REDIRECTS, (302, 303, 307))
        # Worst first: the order the summary reads them in.
        self.assertEqual(sh.HTTP_TO_HTTPS_OUTCOMES,
                         ("not_redirected", "temporary", "not_listening", "permanent"))


class TheRuleNamesEveryOutcome(unittest.TestCase):

    def test_every_outcome_the_script_emits_is_graded_and_nothing_else(self):
        check = rule()
        self.assertEqual(check["args"], ["{url}"])
        self.assertEqual(check["requires"], "fetch")
        self.assertEqual(check["assert"]["path"], "http_to_https")
        self.assertEqual(set(sh.HTTP_TO_HTTPS_OUTCOMES), OUTCOMES)
        self.assertEqual(set(check["assert"]["value_map"]), OUTCOMES)
        self.assertEqual(set(check["warn"]["value_map"]), OUTCOMES)
        expected = {"permanent": PASS, "temporary": WARN, "not_listening": WARN,
                    "not_redirected": FAIL}
        for value, status in expected.items():
            with self.subTest(value=value):
                self.assertEqual(verdict({"http_to_https": value}), status)
        # An outcome the rule does not name is undecided, and so is its absence.
        self.assertEqual(verdict({"http_to_https": "unread"}), NO_DATA)
        self.assertEqual(verdict({"https": True}), NO_DATA)


if __name__ == "__main__":
    unittest.main()
