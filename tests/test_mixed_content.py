"""TE-175 *Secure Pages & Eliminate Errors*, read as what a browser does to an HTTPS page
that asks for something over plain HTTP.

Until 0.121.0 the item counted missing security headers and allowed three — SE-120's and
SE-115's subject counted a second time — and never looked at what the page loads. A page
served over HTTPS whose stylesheet and scripts come over `http://` passed it with the
right headers, and the browser blocks both.

MDN *Mixed content* (last modified 2026-08-15) sorts requests into two kinds, and this
item grades them the way browsers treat them:

* **blockable** — `<script src>`, stylesheet `<link href>`, `<iframe src>`, `<object data>`,
  and `<img srcset>` / `<picture>` sources. Browsers block these outright, so the page is
  broken in a way its author did not see: FAIL.
* **upgradable** — `<img src>`, `<audio src>`, `<video src>`, `<source src>`. Browsers
  rewrite them to https and load them if the host answers; the page depends on something
  it did not ask for correctly: WARN. On an IP-address host they cannot be upgraded and
  are blocked, so they count as blockable.

A page that is itself served over plain HTTP is not a secure page at all: FAIL, and no
subresource is read. Anchors are navigation, not loads, and never count. URLs inside CSS
are not read; the item's `measures` line says so, and names the other errors that are
other items' subjects.
"""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPTS = os.path.join(ROOT, "skills", "seo-checklist", "scripts")
REGISTRY = os.path.join(ROOT, "skills", "seo-checklist", "resources", "config",
                        "checklist.json")
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)

from checklist_runner import FAIL, NO_DATA, PASS, WARN, evaluate  # noqa: E402
from harness import offline_env, served, spawn, tls_env  # noqa: E402
import security_headers as sh  # noqa: E402

SCRIPT = os.path.join(SCRIPTS, "security_headers.py")

PAGE_URL = "https://example.com/page"


def rule() -> dict:
    with open(REGISTRY, encoding="utf-8") as f:
        return {i["id"]: i for i in json.load(f)["items"]}["TE-175"]["check"]


def verdict(output: dict) -> str:
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


def page(body: str) -> str:
    return f"<!doctype html><html><head><title>t</title></head><body>{body}</body></html>"


class TheBrowsersSortIsTheItemsSort(unittest.TestCase):
    """`mixed_content(html, final_url)` is the whole classification."""

    def classify(self, body, final=PAGE_URL):
        return sh.mixed_content(page(body), final)

    def test_blockable_requests(self):
        cases = {
            '<script src="http://cdn.example.com/a.js"></script>': "script",
            '<link rel="stylesheet" href="http://cdn.example.com/a.css">': "link",
            '<iframe src="http://frames.example.com/x"></iframe>': "iframe",
            '<object data="http://cdn.example.com/a.swf"></object>': "object",
            '<img src="/a.png" srcset="http://cdn.example.com/a2.png 2x">': "img",
            '<picture><source srcset="http://cdn.example.com/a.webp"></picture>': "source",
        }
        for body, tag in cases.items():
            with self.subTest(tag=tag):
                found = self.classify(body)
                self.assertEqual([(m["tag"], m["kind"]) for m in found],
                                 [(tag, "blockable")])

    def test_upgradable_requests(self):
        for body, tag in {
            '<img src="http://cdn.example.com/a.png">': "img",
            '<audio src="http://cdn.example.com/a.mp3"></audio>': "audio",
            '<video src="http://cdn.example.com/a.mp4"></video>': "video",
            '<video><source src="http://cdn.example.com/a.mp4"></video>': "source",
        }.items():
            with self.subTest(tag=tag):
                found = self.classify(body)
                self.assertEqual([(m["tag"], m["kind"]) for m in found],
                                 [(tag, "upgradable")])

    def test_an_ip_host_cannot_be_upgraded_so_it_is_blocked(self):
        found = self.classify('<img src="http://93.184.215.14/a.png">')
        self.assertEqual(found[0]["kind"], "blockable")

    def test_what_is_not_a_mixed_load(self):
        body = ('<a href="http://elsewhere.example.com/">a link</a>'
                '<img src="https://cdn.example.com/a.png">'
                '<img src="//cdn.example.com/b.png">'
                '<script src="/local.js"></script>'
                '<link rel="canonical" href="http://example.com/page">'
                '<link rel="alternate" hreflang="lt" href="http://example.com/lt/">'
                '<img src="data:image/png;base64,iVBORw0KGgo=">')
        self.assertEqual(self.classify(body), [])

    def test_a_page_on_plain_http_has_no_mixed_content_to_find(self):
        self.assertEqual(
            self.classify('<script src="http://cdn.example.com/a.js"></script>',
                          final="http://example.com/page"), [])


class TheSummary(unittest.TestCase):

    def test_worst_first(self):
        s = sh.summarize_page_security
        self.assertEqual(s("https://example.com/", []), "secure")
        self.assertEqual(s("https://example.com/", [{"kind": "upgradable"}]),
                         "upgraded_content")
        self.assertEqual(s("https://example.com/", [{"kind": "upgradable"},
                                                    {"kind": "blockable"}]),
                         "blocked_content")
        self.assertEqual(s("http://example.com/", []), "plain_http")
        self.assertEqual(sh.PAGE_SECURITY_STATES,
                         ("plain_http", "blocked_content", "upgraded_content", "secure"))

    def test_the_verdicts(self):
        for state, status in {"secure": PASS, "upgraded_content": WARN,
                              "blocked_content": FAIL, "plain_http": FAIL}.items():
            with self.subTest(state=state):
                self.assertEqual(verdict({"page_security": state}), status)
        self.assertEqual(verdict({}), NO_DATA)

    def test_the_rule_no_longer_counts_headers(self):
        check = rule()
        self.assertEqual(check["script"], "security_headers.py")
        self.assertEqual(check["assert"]["path"], "page_security")
        self.assertEqual(set(check["assert"]["value_map"]), set(sh.PAGE_SECURITY_STATES))
        self.assertEqual(set(check["warn"]["value_map"]), set(sh.PAGE_SECURITY_STATES))
        self.assertNotIn("headers_missing", json.dumps(check))



def run(url: str, env: dict) -> dict:
    proc = spawn([sys.executable, SCRIPT, url, "--json"], env=env, timeout=120)
    assert proc.returncode == 0, f"exited {proc.returncode}: {proc.stderr[-600:]}"
    return json.loads(proc.stdout)


class TheScriptReadsThePageItFetched(unittest.TestCase):
    """The same classification through the script's own fetch, over a real TLS origin."""

    def test_a_blocked_script_fails_and_the_headers_do_not_matter(self):
        body = page('<script src="http://cdn.invalid/a.js"></script>')
        with served({"/": body}, tls=True, plain="redirect") as site:
            out = run(site.url, tls_env())
        self.assertEqual(out["page_security"], "blocked_content")
        self.assertEqual([m["url"] for m in out["mixed_content"]],
                         ["http://cdn.invalid/a.js"])
        self.assertEqual(verdict(out), FAIL)

    def test_a_clean_https_page_passes_with_no_headers_at_all(self):
        with served({"/": page('<img src="/a.png">')}, tls=True, plain="redirect") as site:
            out = run(site.url, tls_env())
        self.assertEqual(len(out["headers_missing"]), 6)
        self.assertEqual(out["page_security"], "secure")
        self.assertEqual(verdict(out), PASS)

    def test_a_plain_http_page_is_not_secure(self):
        with served({"/": page('<img src="/a.png">')}) as site:
            out = run(site.url, offline_env())
        self.assertEqual(out["page_security"], "plain_http")
        self.assertEqual(out["mixed_content"], [])
        self.assertEqual(verdict(out), FAIL)


if __name__ == "__main__":
    unittest.main()
