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
from checklist_runner import (  # noqa: E402
    FAIL, NA, PASS, WARN, passes_by_absence)


def registry_items():
    """The shipped registry, read once per call site that needs it."""
    with open(REGISTRY, encoding="utf-8") as stream:
        return json.load(stream)["items"]


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
        # `plain="redirect"`: SE-117 asks the page's http:// address from 0.118.0, and a
        # TLS-only port answers that with a broken connection, which is no verdict.
        body = page("A page served over TLS")
        with served({"/": (200, dict(headers, **{"Content-Type": "text/html"}), body)},
                    tls=True, plain="redirect") as site:
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


class ACrawlThatStoppedAtItsPageLimit(unittest.TestCase):
    """`openspec/specs/run-lifecycle/` RUN-19's join, which nothing read until 0.96.5.

    The rule is covered thoroughly and in both directions — a clean answer over a capped
    input is withheld, a defect found in the part that was read still fails, a failing
    count is named as a floor. **Every one of those tests injects `truncated` by hand.**

    Measured by mutation against the suite before this class existed:

    | breakage | |
    |---|---|
    | the crawl never reports that it was capped (`"truncated": False`) | **MISSED** |
    | one checker stops copying the flag out of the inventory | **MISSED** |
    | the grader stops asking (`input_truncated`) | CAUGHT |

    So the rule was guarded and both halves of the path feeding it were not:
    `site_crawl.py` could have stopped reporting truncation altogether and the suite
    would have stayed green. A flag nothing produces is a rule that never fires, and
    "no violations found" over three pages of sixty would have gone back to reading as
    a finding about the site.

    This starts from a real capped crawl and follows it to a verdict, so the three
    links are read as one thing.
    """

    PAGES = 60
    CAP = 3

    def build(self):
        links = "".join(f'<a href="/p{i:02d}.html">p{i:02d}</a> '
                        for i in range(self.PAGES))
        routes = {"/robots.txt": (200, {"Content-Type": "text/plain"},
                                  "User-agent: *\nDisallow:\n")}
        for index in range(self.PAGES):
            routes[f"/p{index:02d}.html"] = page(
                f"Page {index:02d} of a site with sixty of them",
                f"Body copy for page {index:02d}, with enough words to be a page "
                f"rather than a stub. {links}")
        routes["/"] = page("The entry page of a sixty page site",
                           "Every page links to every other, so the crawl has more "
                           f"queued than it may fetch. {links}")
        return routes

    def test_the_crawl_says_it_was_capped_and_the_verdict_follows(self):
        # The whole registry, not one category. The flag is copied **per checker** and
        # nine of them take a crawl inventory, so a narrowed run exercises only the
        # checkers in its own category: a probe that cut the copy out of
        # `duplicate_content.py` read MISSED against a `crawling_indexing` run while
        # the same probe against `site_crawl.py` was caught. Two full audits of a
        # sixty-page site is what closing that costs.
        with served(self.build()) as site:
            payload = run_audit(site.url, "--crawl-max-pages", str(self.CAP), only="")

        summary = (payload.get("crawl") or {}).get("summary") or {}
        self.assertTrue(
            summary.get("truncated"),
            f"a crawl of {self.PAGES} pages capped at {self.CAP} did not report itself "
            f"truncated, so every rule that withholds over a capped input is inert: "
            f"{summary}")

        # The other end of the same path, read by comparing two runs of the same site
        # rather than by matching a sentence: an item that answers `PASS` when the whole
        # site was read, and `NO_DATA` when three pages of sixty were, is the
        # propagation working. Asserting the evidence wording instead would pin a
        # sentence the report is free to rewrite, and the first version of this test
        # did exactly that and failed on "only part of the input was read".
        with served(self.build()) as site:
            whole = run_audit(site.url, "--crawl-max-pages", str(self.PAGES + 10),
                              only="")
        capped_status = {row["id"]: row["status"] for row in payload["items"]}
        whole_status = {row["id"]: row["status"] for row in whole["items"]}

        # Per item, not "at least one". The flag is copied once per checker, and eight
        # of them take an inventory — so "some item was withheld" is satisfied by the
        # seven that still copy it while the eighth quietly stops. Measured: a probe
        # cutting the copy out of `duplicate_content.py` read MISSED against exactly
        # that assertion, twice, once narrowed and once over the whole registry.
        #
        # The candidate set is derived from the registry through the runner's own
        # `passes_by_absence`, so a checker added tomorrow is swept by existing.
        candidates = {item["id"] for item in registry_items()
                      if "{inventory_json}" in ((item.get("check") or {}).get("args")
                                                or [])
                      and passes_by_absence((item.get("check") or {}).get("assert")
                                            or {})}
        self.assertTrue(candidates, "nothing reads an inventory; this test is vacuous")

        # Only the ones that actually decided over the whole site: an item that was
        # `N/A` or `NEEDS_INPUT` there says nothing about propagation either way.
        should_withhold = sorted(i for i in candidates if whole_status.get(i) == PASS)
        self.assertTrue(
            should_withhold,
            f"no inventory-reading item passed over the whole site, so this asserts "
            f"nothing: {sorted((i, whole_status.get(i)) for i in candidates)}")
        kept = {i: capped_status.get(i) for i in should_withhold
                if capped_status.get(i) != "NO_DATA"}
        self.assertEqual(
            kept, {},
            f"these passed over three pages of {self.PAGES} and were not withheld, so "
            f"their checker does not carry the crawl's truncation flag: {kept}")

    def test_an_uncapped_crawl_of_a_small_site_says_nothing_about_truncation(self):
        """The floor. A crawl reporting `truncated` unconditionally would satisfy the
        test above and withhold every clean answer on every site, which is the failure
        mode that makes a caveat worthless."""
        routes = {"/robots.txt": (200, {"Content-Type": "text/plain"},
                                  "User-agent: *\nDisallow:\n"),
                  "/": page("A two page site", 'Small. <a href="/b.html">b</a>'),
                  "/b.html": page("The second page", "Also small, and links nowhere.")}
        with served(routes) as site:
            payload = run_audit(site.url, "--crawl-max-pages", "100",
                                only="crawling_indexing")
        summary = (payload.get("crawl") or {}).get("summary") or {}
        self.assertFalse(summary.get("truncated"),
                         f"a two-page site under a hundred-page cap reported itself "
                         f"truncated: {summary}")


class ADeadEntryRunsNothing(unittest.TestCase):
    """`openspec/specs/run-lifecycle/` RUN-8's second scenario, which had no reader.

    The requirement has two halves and only one of them was read. The statuses are
    pinned in five places and the missing score in two, and every one of those reads a
    plan or a report: `test_no_live_site_check_reaches_the_plan` asserts that the plan
    contains no gated item, which is a statement about a dict. A runner that built an
    empty plan and then crawled the site, fetched the sitemap and sampled five pages
    anyway would satisfy it exactly, and the spec says so in its own words — "an
    assertion that the plan is empty does not establish this".

    The origin is the only witness there is, and `Served.requested` already keeps the
    record. Measured over the whole registry against an entry answering 503: the
    origin received **one** request, `GET /`. The assertion below is the requirement's
    own bound rather than that number — the entry, and the robots.txt any fetch is
    entitled to ask for — so a robots request appearing tomorrow is not a failure and
    a sitemap request is.

    Whole registry on the dead run, and one category on the floor, deliberately. The
    claim being made is that *nothing* ran, so narrowing it would leave every script
    outside the selection unwatched; the floor only has to show this origin answers
    more than the entry when it is up, which one category proves as well as twelve.

    **`--sample 5`, and the first draft did not pass it.** There are two gates between a
    dead entry and a request — the crawl's `and not entry_error`, and the sampler's
    `elif entry_error` — and `--sample` defaults to 1, so a run that omits it never
    enters the second branch at all. Measured: removing the sampler's guard against a
    run with no `--sample` read **MISSED**, and the test looked like it held a clause it
    could not reach. With the flag it is CAUGHT, because `discover_urls` then asks the
    dead origin for its sitemap.
    """

    ENTRY_AND_ROBOTS = {"/", "/robots.txt"}

    def up(self):
        return {"/robots.txt": (200, {"Content-Type": "text/plain"},
                                "User-agent: *\nDisallow:\n"),
                "/": page("A site that is up",
                          'Two pages. <a href="/second.html">the second one</a>'),
                "/second.html": page("The second page", "Linked from the entry.")}

    def test_a_dead_entry_leaves_the_origin_alone(self):
        with served({"/": (503, {}, "down")}) as site:
            payload = run_audit(site.url, "--sample", "5", only="")
            asked = site.paths("GET") + site.paths("HEAD")
        self.assertFalse(payload["entry_reachable"], payload.get("entry_error"))
        beyond = sorted(set(asked) - self.ENTRY_AND_ROBOTS)
        self.assertEqual(
            beyond, [],
            f"the entry answered 503 and the run went on asking this origin for "
            f"{beyond}; nothing planned is not nothing run")

    def test_the_same_origin_is_asked_for_more_when_it_is_up(self):
        """The floor. An origin nothing ever fetches from satisfies the test above
        without the run having refused anything, and a runner that fetched only the
        entry on every site would look identical from inside a single case."""
        with served(self.up()) as site:
            payload = run_audit(site.url, "--sample", "3", only="crawling_indexing")
            asked = site.paths("GET") + site.paths("HEAD")
        self.assertTrue(payload["entry_reachable"], payload.get("entry_error"))
        beyond = sorted(set(asked) - self.ENTRY_AND_ROBOTS)
        self.assertTrue(
            beyond,
            f"a reachable two-page site was asked for nothing but its entry, so the "
            f"dead-entry assertion is about an origin nobody fetches from: {asked}")


class ASampleMadeOfPages(unittest.TestCase):
    """`openspec/specs/run-lifecycle/` RUN-17's three drop rules, two of which had no
    reader at all and one of which is reachable only where nothing was looking.

    The spread and the stability are enforced. Of the three ways a candidate leaves the
    sample, only the extension filter is read — `test_assets_are_not_pages` covers it as
    a function. The content-type rejection, the robots-disallowed count and the message
    a single-URL run prints had nothing.

    **Two of them live under `--mode page`, and the first measurement of them was
    wrong.** A `live` run crawls, and `discover_urls` then takes its candidates out of
    the crawl inventory, which has already dropped what is not HTML and already honoured
    robots. Run under `live`, a sitemap listing a PDF and a robots-disallowed section
    produces exactly the right sample and prints nothing — which reads as the two rules
    working and is in fact the two rules never being reached. `page` mode has no `crawl`
    capability, the sitemap fallback is used, and both fire. A test written against the
    first measurement would have passed for the wrong reason for as long as it lived.
    """

    ALLOW_ALL = (200, {"Content-Type": "text/plain"}, "User-agent: *\nDisallow:\n")

    @staticmethod
    def sitemap(*paths):
        return (200, {"Content-Type": "application/xml"},
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                + "".join(f"<url><loc>__BASE__{p}</loc></url>" for p in paths)
                + "</urlset>")

    def test_a_candidate_the_extension_filter_kept_is_dropped_on_its_type(self):
        """The scenario's own second half: "the extension filter alone does not settle
        the second case". `/report` has no extension, so `looks_like_a_page` keeps it
        and it is sampled; what removes it is the `application/pdf` it answers with.

        Asserted on the ASCII of the message rather than the whole line: the runner
        joins the URL to the reason with an em dash, and this suite's captured stderr
        is not read back as UTF-8 on every host.
        """
        from checklist_runner import looks_like_a_page
        routes = {"/robots.txt": self.ALLOW_ALL,
                  "/": page("The entry page",
                            "Its sitemap lists a report with no extension. " * 4),
                  "/report": (200, {"Content-Type": "application/pdf"},
                              "%PDF-1.4 and not a page"),
                  "/real.html": page("A real second page",
                                     "Enough words here to be a page, not a stub."),
                  "/sitemap.xml": self.sitemap("/report", "/real.html")}
        with served(routes) as site:
            site.rewrite("__BASE__", site.base)
            report_url = f"{site.base}/report"
            self.assertTrue(
                looks_like_a_page(report_url),
                "the extension filter already rejects this URL, so the content-type "
                "rule is not what this test is reading")
            payload = run_audit(site.url, "--mode", "page", "--sample", "3",
                                only="meta_structured")
        self.assertIn(report_url, payload["sampled_urls"],
                      "the candidate never reached the fetch, so nothing here reads "
                      "the content-type rejection")
        noise = payload["_stdout"] + payload["_stderr"]
        self.assertIn("not a page: Content-Type application/pdf", noise,
                      "a non-page content type was sampled and the run did not say so")

    def test_a_page_of_the_right_type_survives_the_same_run(self):
        """The floor for the rule above. A sampler that dropped every candidate would
        satisfy it, and would report a one-page audit of a site with a sitemap."""
        routes = {"/robots.txt": self.ALLOW_ALL,
                  "/": page("The entry page", "Its sitemap lists one real page. " * 4),
                  "/real.html": page("A real second page",
                                     "Enough words here to be a page, not a stub."),
                  "/sitemap.xml": self.sitemap("/real.html")}
        with served(routes) as site:
            site.rewrite("__BASE__", site.base)
            payload = run_audit(site.url, "--mode", "page", "--sample", "3",
                                only="meta_structured")
            fetched = site.paths("GET")
        self.assertIn("/real.html", fetched,
                      "a page of the right type was not fetched either")
        self.assertNotIn("not a page", payload["_stdout"] + payload["_stderr"])

    def test_the_count_of_robots_drops_is_the_number_of_picks_robots_took(self):
        """RUN-17's third scenario. The count is not read against a number written
        here — that is the shape A.13 names — but against the same site sampled twice,
        once with the section disallowed and once without. The picks are identical
        across the pair because `stride` runs before the robots filter and the sitemap
        does not move, which is this requirement's own stability clause doing the work.

        So: (what the permissive run sampled) minus (what the restrictive run sampled)
        is how many picks robots took, and that is the number the run has to print.
        """
        def routes(disallow):
            out = {"/robots.txt": (200, {"Content-Type": "text/plain"},
                                   f"User-agent: *\n{disallow}\n"),
                   "/": page("The entry page",
                             "A sitemap, and a section robots keeps to itself. " * 4),
                   "/open.html": page("The page robots allows",
                                      "Enough words here to be a page, not a stub."),
                   "/sitemap.xml": self.sitemap(
                       *[f"/private/p{i}.html" for i in range(4)], "/open.html")}
            for i in range(4):
                out[f"/private/p{i}.html"] = page(
                    f"Private page {i}", "Nothing should ever sample this one.")
            return out

        sampled, closed_noise, closed_fetched = {}, "", []
        for label, disallow in (("open", "Disallow:"),
                                ("closed", "Disallow: /private/")):
            with served(routes(disallow)) as site:
                site.rewrite("__BASE__", site.base)
                payload = run_audit(site.url, "--mode", "page", "--sample", "5",
                                    only="meta_structured")
                sampled[label] = [u.replace(site.base, "") or "/"
                                  for u in payload["sampled_urls"]]
                if label == "closed":
                    closed_noise = payload["_stdout"] + payload["_stderr"]
                    closed_fetched = site.paths("GET")

        taken = len(sampled["open"]) - len(sampled["closed"])
        self.assertGreater(
            taken, 0,
            f"robots took nothing out of the sample, so there is no count to read: "
            f"{sampled}")
        self.assertIn(f"{taken} sampled URL(s) skipped: robots.txt disallows them",
                      closed_noise,
                      f"robots took {taken} of the picks and the run did not say so; "
                      f"a sample silently reduced is a smaller audit reported as a "
                      f"full one. sampled={sampled}")
        self.assertEqual(
            [p for p in closed_fetched if p.startswith("/private/")], [],
            "a disallowed URL was counted as dropped and fetched anyway")

    def test_a_site_with_nothing_to_discover_says_so_and_audits_one_page(self):
        """The third of RUN-17's unread messages. `--sample 5` against a site with no
        sitemap and no internal links must not report a five-page audit of one page."""
        lonely = page("A page that links nowhere",
                      "No sitemap and no anchors anywhere on this site. " * 6)
        with served({"/": lonely}) as site:
            payload = run_audit(site.url, "--sample", "5", only="meta_structured")
        self.assertEqual(payload["sampled_urls"], [])
        self.assertIn("--sample found no other URLs", payload["_stderr"],
                      "a one-page audit was run under --sample 5 without saying so")

    def test_a_site_with_something_to_discover_does_not(self):
        """The floor. A `discover_urls` that always returned `[]` would satisfy the
        test above on every site in the world."""
        with served({"/robots.txt": self.ALLOW_ALL,
                     "/": page("The entry page",
                               'It links onward. <a href="/second.html">second</a>'),
                     "/second.html": page("The second page",
                                          "Enough words to be a page, not a stub.")
                     }) as site:
            payload = run_audit(site.url, "--sample", "5", only="meta_structured")
        self.assertGreater(len(payload["sampled_urls"]), 1, payload["sampled_urls"])
        self.assertNotIn("--sample found no other URLs", payload["_stderr"])


class AProfileThatMovedAThreshold(unittest.TestCase):
    """`openspec/specs/run-lifecycle/` RUN-6's remaining half: the artifact.

    Two of the three kinds of appended argument are now read where they are used, and
    the moved threshold is pinned into the answering script's own summary. What nothing
    asserted is the sentence the requirement actually ends on — that the moved
    threshold is visible *beside the verdict it moved*, which for anybody reading the
    JSON means `profile_args`. A reader consulting the artifact to find out what was
    asked had no guarantee the answer was in it: the field could have stopped being
    written and every named test would have stayed green.

    The expected value is read out of `profiles.json`, not typed here. A profile that
    changes its threshold tomorrow moves this test with it, and a test carrying the
    number by hand would go on asserting the old one.
    """

    PROFILES = os.path.join(ROOT, "skills", "seo-checklist", "resources", "config",
                            "profiles.json")

    @classmethod
    def setUpClass(cls):
        with open(cls.PROFILES, encoding="utf-8") as stream:
            cls.profiles = json.load(stream)["profiles"]
        cls.moved = sorted(name for name, body in cls.profiles.items()
                           if (body or {}).get("script_args"))

    def audit(self, *extra):
        with served({"/": page("A small site",
                               "Some words that make this a real page. " * 8)}) as site:
            return run_audit(site.url, *extra, only="meta_structured")

    def test_a_profile_that_moves_a_threshold_records_it_in_the_artifact(self):
        self.assertTrue(self.moved,
                        "no shipped profile moves a script argument, so this test "
                        "asserts nothing; RUN-6's third clause needs a new subject")
        for name in self.moved:
            with self.subTest(profile=name):
                payload = self.audit("--profile", name)
                self.assertEqual(payload["profile"], name)
                self.assertEqual(payload["profile_args"],
                                 self.profiles[name]["script_args"],
                                 f"the {name} profile moved a threshold and the "
                                 f"artifact does not say which")

    def test_a_profile_that_moves_nothing_records_nothing(self):
        """The floor, and the half that makes the field mean something: a runner
        writing the same mapping on every run would satisfy the test above while
        telling every reader their thresholds had moved."""
        unmoved = sorted(set(self.profiles) - set(self.moved))
        self.assertTrue(unmoved, "every profile moves a threshold")
        payload = self.audit("--profile", unmoved[0])
        self.assertEqual(payload["profile"], unmoved[0])
        self.assertIsNone(payload["profile_args"],
                          f"the {unmoved[0]} profile moves no script argument and the "
                          f"artifact claims it moved one")


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
