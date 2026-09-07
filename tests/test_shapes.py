"""The four site shapes the live path had never seen.

`KNOWN-ISSUES` item 3 listed them: a cross-host redirect, a real bot-protection
challenge, a site large enough for `--sample` to matter, and TLS — plus a Search
Console property with history, which stays out of reach because it needs a property
Google recognises and a key, neither of which a fixture can be.

Each was "tested with fixtures and never live", and the distinction mattered: the
redirect logic, the page guard and the sampling stride were all exercised by feeding
functions strings, so nothing checked that the *runner* did the right thing with a real
301, a real challenge page or sixty real URLs. Two of the four had already gone wrong
in exactly the gap: the discarded final URL (§4.10) and the guard's first draft calling
a 90-word article an interstitial (§4.9).

TLS is the one that needed new machinery rather than a new fixture. `safe_http` sets
`verify=True` and never relaxes it, so the HTTPS items and every HSTS check had
verdicts from stubs only — the suite could not serve HTTPS at all until the harness
learned to, and it does it by trusting one generated certificate through
`REQUESTS_CA_BUNDLE` rather than by switching verification off.

Still offline: every origin here is loopback.
"""
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "skills", "seo-checklist", "scripts")
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import served, spawn, tls_env  # noqa: E402

RUNNER = os.path.join(SCRIPTS, "checklist_runner.py")
REGISTRY = os.path.join(ROOT, "skills", "seo-checklist", "resources", "config",
                        "checklist.json")

# Imported rather than retyped. This line read
# `PASS, FAIL, WARN, NO_DATA = "PASS", "FAIL", "WARN", "N/A"` until 0.95.2 — the
# fourth name bound to the third status's string, harmless only because nothing had
# used it yet, and a trap for whoever did.
from checklist_runner import FAIL, NA, PASS, WARN  # noqa: E402


def run_audit(url: str, *extra: str, env=None, only: str = "crawling_indexing") -> dict:
    """One audit, through the runner, as an operator would get it.

    `--only` by default: these tests are about what the runner does with a *shape* of
    site, and a full registry pass costs ten seconds per case to re-verify checks that
    other files already cover.
    """
    work = tempfile.mkdtemp(prefix="seo-shape-")
    out = os.path.join(work, "results.json")
    args = [sys.executable, RUNNER, url, "--allow-private", "--max-rps", "0",
            "--no-history", "--no-prompt", "--quiet", "--timeout", "90",
            "--json", out, *extra]
    if only:
        args += ["--only", only]
    # `harness.spawn`, and no `cwd`: see its docstring for the macOS fork crash that
    # makes that the only reliable way to start a child here. Every path passed to the
    # runner is absolute for the same reason.
    proc = spawn(args, env=env, timeout=600)
    if proc.returncode != 0:
        raise AssertionError(f"the audit exited {proc.returncode}\n"
                             f"{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}")
    with open(out, encoding="utf-8") as f:
        payload = json.load(f)
    payload["_stdout"], payload["_stderr"] = proc.stdout, proc.stderr
    return payload


DEFAULT_BODY = ("Body copy with enough words in it that the thin-entry guard stays "
                "quiet, because a guard firing here would stop the audit before the "
                "thing under test ran at all.")


def page(title="A page that satisfies the basics", body="", head="", lang="en"):
    """A page with nothing wrong with it, so a test can break one thing deliberately.

    The default body is a module constant rather than an inline fallback: a multi-line
    expression inside an f-string field is Python 3.12 syntax, the declared floor here
    is 3.10, and CI runs 3.11 — so the first version of this helper would not have
    *parsed* there. `ruff` caught it before CI did, which is the argument for having
    added the linter in 0.7.0.
    """
    return (f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<title>{title}</title>"
            f'<meta name="description" content="Enough of a description to be one, and '
            f'long enough that the length check has something to measure.">{head}</head>'
            f"<body><h1>{title}</h1><p>{body or DEFAULT_BODY}</p></body></html>")


class ACrossHostRedirect(unittest.TestCase):
    """The entry URL redirects to another host, which is what a domain migration, a
    www/non-www canonicalisation and a country redirect all look like.

    §4.10 is the reason this is a shape and not a unit test: `fetch_page` threw away
    the URL the request landed on, so every script was handed the address that
    redirected away — `discover_urls` filtered candidates on the old netloc and the
    sample collapsed to one page, and `sc-domain:` was derived from a domain the
    service account has no property for. Both fail *quietly*.
    """

    def test_the_destination_is_audited_and_the_request_is_recorded(self):
        with served({"/": page("The destination site"),
                     "/second.html": page("A second page on the destination")}) as dest:
            with served({"/": (301, {"Location": dest.url}, "")}) as entry:
                payload = run_audit(entry.url)
        self.assertEqual(payload["url"].rstrip("/"), dest.base,
                         "the audit did not follow the redirect to the destination")
        self.assertEqual(payload["requested_url"].rstrip("/"), entry.base,
                         "the URL that was asked for is not recorded")
        self.assertTrue(payload["entry_reachable"], payload.get("entry_error"))
        self.assertIn("redirected", payload["_stdout"].lower() + payload["_stderr"].lower())

    def test_the_sample_follows_the_destination_host(self):
        """The quiet half: a sample filtered on the old netloc finds nothing and looks
        like a one-page site."""
        with served({"/": page("The destination site",
                               head='<link rel="canonical" href="__DEST__/">'),
                     "/second.html": page("A second page on the destination")}) as dest:
            dest.rewrite("__DEST__", dest.base)
            with served({"/": (301, {"Location": dest.url}, "")}) as entry:
                payload = run_audit(entry.url, "--sample", "3", only="meta_structured")
        for url in payload["sampled_urls"]:
            self.assertTrue(url.startswith(dest.base),
                            f"{url} is not on the audited host")

    def test_a_same_host_redirect_keeps_the_requested_url(self):
        """Deliberate asymmetry: nothing downstream is confused by a same-host hop, and
        `redirect_checker.py` needs to be handed the address that actually redirects —
        it is the hop the item exists to report."""
        with served({"/": (301, {"Location": "/final.html"}, ""),
                     "/final.html": page("The final page")}) as site:
            payload = run_audit(site.url)
        self.assertIsNone(payload["requested_url"])
        self.assertEqual(payload["url"].rstrip("/"), site.base)


class ABotProtectionChallenge(unittest.TestCase):
    """A 200 with well-formed HTML that is not the site.

    The audit User-Agent is exactly what bot protection is built to stop, so this is
    the common case, not an edge one. §4.9's first draft of the guard called a 90-word
    article an interstitial because it searched the whole document and gated only on
    word count; the test that missed it used a fixture long enough to clear the
    threshold. So this pins both directions live: the challenge is refused, and an
    article *about* bot protection is audited.
    """

    CHALLENGE = ("<!doctype html><html><head><title>Just a moment...</title></head>"
                 "<body><h1>Checking your browser before accessing the site</h1>"
                 '<script src="/cdn-cgi/challenge-platform/h/b/orchestrate/chl_page/v1">'
                 "</script></body></html>")

    def test_a_challenge_page_is_refused_and_nothing_is_scored(self):
        with served({"/": self.CHALLENGE}) as site:
            payload = run_audit(site.url)
        self.assertEqual(payload["entry_guard"], "bot_challenge")
        self.assertTrue(payload["entry_guard_enforced"])
        self.assertFalse(payload["entry_reachable"])
        self.assertIsNone(payload["scores"]["seo_score"],
                          "a score was printed for a page that is not the site")
        self.assertEqual(payload["scores"]["decided"], 0)

    def test_the_override_scores_it_and_says_so_everywhere(self):
        """A heuristic that can be wrong must have an override, and an artifact that
        scored an interstitial without admitting it would be the same lie in a new
        place."""
        with served({"/": self.CHALLENGE}) as site:
            payload = run_audit(site.url, "--no-page-guard")
        self.assertEqual(payload["entry_guard"], "bot_challenge")
        self.assertFalse(payload["entry_guard_enforced"])
        self.assertTrue(payload["entry_reachable"])
        self.assertIn("no-page-guard", payload["_stdout"] + payload["_stderr"])

        sys.path.insert(0, SCRIPTS)
        from checklist_report import provenance_warnings
        self.assertTrue(any("bot challenge" in w for w in provenance_warnings(payload)),
                        "the deliverable does not mention what it graded")

    def test_an_article_about_bot_protection_is_still_audited(self):
        """The mirror image, and the bug the unit test missed: a vendor string in prose
        is not machinery. Short *and* about Cloudflare, which is the combination that
        broke the first draft."""
        article = page(
            "How Cloudflare challenges work",
            "Cloudflare serves its interstitial from cdn-cgi/challenge-platform, which "
            "is why a crawler sees something different from a browser. Under a hundred "
            "words on purpose.")
        with served({"/": article}) as site:
            payload = run_audit(site.url)
        self.assertIsNone(payload["entry_guard"])
        self.assertTrue(payload["entry_reachable"])
        self.assertGreater(payload["scores"]["decided"], 0)


class ASiteLargeEnoughToSample(unittest.TestCase):
    """Sixty pages, so `--sample` has to choose — and so the choice can be checked.

    Until 0.3.0 sampling took the first N URLs in sitemap document order, which
    gathers one corner of a site while the report says "5 of 5 pages checked". The
    stride that replaced it was itself wrong at first: it stepped `i * len/limit`,
    which stops a whole step short of the end, so the last 100 URLs of a 1,000-URL
    sitemap could never be audited at any sample size. Both bugs are about *which*
    pages, which is only visible on a site big enough for the answer to differ.
    """

    PAGES = 60

    def build(self):
        routes = {}
        locs = []
        for index in range(self.PAGES):
            path = f"/p{index:02d}.html"
            # The last page carries a title over the 60-character limit, so the worst
            # page is the one furthest from the entry — a sample that stops short of
            # the end reports the site as clean.
            title = ("A title long enough to break the sixty character limit that "
                     "MS-020 measures" if index == self.PAGES - 1
                     else f"Page {index:02d} of a site with sixty of them")
            routes[path] = page(title, f"Body copy for page {index:02d}, with enough "
                                       "words to be a page rather than a stub.")
            locs.append(f"<url><loc>__BASE__{path}</loc></url>")
        routes["/"] = page("The entry page of a sixty page site",
                           "One page links to the sitemap and the rest are found there.")
        routes["/sitemap.xml"] = (
            200, {"Content-Type": "application/xml"},
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            + "".join(locs) + "</urlset>")
        routes["/robots.txt"] = (200, {"Content-Type": "text/plain"},
                                 "User-agent: *\nDisallow:\n"
                                 "Sitemap: __BASE__/sitemap.xml\n")
        return routes

    def test_the_sample_spans_the_site_rather_than_its_first_corner(self):
        with served(self.build()) as site:
            site.rewrite("__BASE__", site.base)
            payload = run_audit(site.url, "--sample", "5", only="meta_structured")
        sampled = payload["sampled_urls"]
        self.assertEqual(len(sampled), 5, sampled)
        # The entry page is always included, and the far end of the sitemap has to be
        # reachable: the first stride bug made the tail unauditable at any sample size.
        self.assertIn(f"{site.base}/p{self.PAGES - 1:02d}.html", sampled)
        indices = sorted(int(u.rsplit("/p", 1)[1][:2]) for u in sampled if "/p" in u)
        self.assertGreater(max(indices) - min(indices), self.PAGES // 2,
                           f"the picks cluster instead of spanning: {indices}")

    def test_the_worst_page_decides_and_the_count_is_reported(self):
        """The worst sampled page supplies the verdict *and* the measurement: a live
        run once printed "52 characters, no more than 60 is acceptable" above a FAIL,
        because the verdict came from the worst page and the number from the entry."""
        with served(self.build()) as site:
            site.rewrite("__BASE__", site.base)
            payload = run_audit(site.url, "--sample", "5", only="meta_structured")
        item = {i["id"]: i for i in payload["items"]}["MS-020"]
        self.assertIn(item["status"], (FAIL, WARN), item.get("evidence"))
        self.assertIn("pages", (item.get("evidence") or ""),
                      "the evidence does not say how many pages it saw")
        self.assertRegex(item.get("evidence") or "", r"6[1-9]|7\d|8\d|9\d|\d{3}",
                         "the measurement is not the worst page's")


class NarrowingIsAPartitionOfTheRegistry(unittest.TestCase):
    """`openspec/specs/scoring/` SCR-6 and SCR-7, on a narrowed live run.

    The documented route to a better-looking audit is a narrower one, and the only
    defence available is that narrowing is visible and scores nothing. `--only`
    filtered the item list before planning until 0.95.2, so the rows it dropped never
    became `N/A`: the five buckets summed to the selection rather than to the
    registry, and the score of that slice was printed where the score of the site
    goes. Measured on a real artifact, a full run scored 57 over 217 rows while a
    single-category slice scored 100 over 10.

    SCR-7's own gap was that nothing asserted the sum against the registry's real
    item count on a narrowed run. This is that run, and the id check belongs to it:
    the requirement says an id-set check is needed because a sum alone still passes
    if one row is counted twice.
    """

    ONLY = "security"

    @classmethod
    def setUpClass(cls):
        with served({"/": page("A small site",
                               "Some words that make this a real page. " * 8)}) as site:
            cls.payload = run_audit(site.url, only=cls.ONLY)
        with open(REGISTRY, encoding="utf-8") as f:
            cls.registry = json.load(f)["items"]

    def test_a_narrowed_run_still_reports_every_item_once(self):
        ids = [i["id"] for i in self.payload["items"]]
        self.assertEqual(len(ids), len(self.registry))
        self.assertEqual(sorted(set(ids)), sorted(i["id"] for i in self.registry))

    def test_the_buckets_sum_to_the_registry(self):
        p = self.payload["scores"]["partition"]
        self.assertEqual(sum(p.values()), len(self.registry))
        self.assertEqual(self.payload["scores"]["total_items"], len(self.registry))

    def test_every_row_outside_the_selection_says_the_selection_dropped_it(self):
        outside = [i for i in self.payload["items"] if i["category"] != self.ONLY]
        self.assertTrue(outside, "the selection excluded nothing to read")
        for row in outside:
            with self.subTest(item=row["id"]):
                self.assertEqual(row["status"], NA)
                self.assertIn("--only", row["evidence"])
                self.assertIn(row["category"], row["evidence"])

    def test_the_selected_category_is_the_one_that_was_actually_run(self):
        """The floor. Marking everything `N/A` would satisfy the three assertions
        above and audit nothing, so the selected rows have to carry real verdicts."""
        inside = [i for i in self.payload["items"] if i["category"] == self.ONLY]
        self.assertTrue(inside)
        self.assertEqual([i["id"] for i in inside if i["status"] == NA], [],
                         "the selected category was excluded too")
        self.assertTrue(any(i["status"] in (PASS, FAIL, WARN) for i in inside),
                        "nothing in the selected category reached a verdict")


class HttpsAndHsts(unittest.TestCase):
    """The shape that needed a certificate.

    Everything else in this suite is HTTP, so `security_headers.py`'s `https` field and
    every HSTS check had only stubbed verdicts — and a stub cannot tell you whether
    `verify=True` and a real handshake let the request through at all.
    """

    HSTS = {"Strict-Transport-Security": "max-age=31536000; includeSubDomains",
            "Content-Security-Policy": "default-src 'self'",
            "X-Frame-Options": "SAMEORIGIN",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "strict-origin-when-cross-origin",
            "Permissions-Policy": "camera=()"}

    def audit_over_tls(self, headers):
        body = page("A page served over TLS")
        with served({"/": (200, dict(headers, **{"Content-Type": "text/html"}), body)},
                    tls=True) as site:
            return run_audit(site.url, env=tls_env(), only="security")

    def test_a_real_handshake_satisfies_the_https_items(self):
        payload = self.audit_over_tls(self.HSTS)
        statuses = {i["id"]: i["status"] for i in payload["items"]}
        for item_id in ("SE-117", "SE-118"):
            self.assertEqual(statuses.get(item_id), PASS,
                             {i["id"]: i.get("evidence") for i in payload["items"]})

    def test_a_site_with_no_security_headers_differs(self):
        """Both directions over the same transport, so the difference is the headers
        and not the fact that TLS worked at all."""
        with_headers = self.audit_over_tls(self.HSTS)
        without = self.audit_over_tls({})
        scored = {p["url"]: {i["id"]: i["status"] for i in p["items"]}
                  for p in (with_headers, without)}
        self.assertNotEqual(*list(scored.values()),
                            "the security items cannot tell the two apart")

    def test_the_run_reports_the_scheme_it_actually_used(self):
        payload = self.audit_over_tls(self.HSTS)
        self.assertTrue(payload["url"].startswith("https://"), payload["url"])
        self.assertTrue(payload["entry_reachable"], payload.get("entry_error"))


class WhatStaysUnexercised(unittest.TestCase):
    """The fifth shape, named so it cannot be quietly forgotten.

    A Search Console property with enough history for the cannibalization items needs a
    property Google recognises and a service-account key that can read it. Neither is
    something a fixture can be, and a test that pretended otherwise would be asserting
    against a stub while claiming live coverage. It stays in KNOWN-ISSUES as the one
    remaining shape, and this test is the link between that sentence and this file.
    """

    def test_the_known_issues_entry_still_names_it(self):
        with open(os.path.join(ROOT, "KNOWN-ISSUES.md"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn("Search Console property", text,
                      "the remaining unexercised shape is no longer recorded")


if __name__ == "__main__":
    unittest.main()
