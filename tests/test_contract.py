"""Every script-backed item, run against a good site and a broken one.

The gap this closes is not "some scripts have no test". It is that a check can be
verified only by *disagreeing with something*. Thirty-three assertions in this
registry's history reported the same verdict on every site ever audited, and each was
found by accident, one family at a time — a regex that matched nothing (§4.12), a
severity vocabulary that could not intersect (0.5.0), a field never emitted (0.5.0), a
rating word only one of two sources uses (0.5.0). Static audits catch each family
*after* somebody names it.

This catches the next family without naming it. Two fixture sites are served on
loopback, one satisfying as much of the registry as a static site can and one
engineered to fail as much as possible, and the whole registry is run against both. A
check that returns the same verdict on both is either measuring something the fixtures
do not differ on — recorded below, per item, with the reason — or it cannot tell the
difference between a good site and a bad one, which is the defect.

Slow by construction: two full audits, ~10s each. Worth it, and it runs in CI.

Offline: loopback only, no egress, no credentials. External-API scripts (PageSpeed,
Safe Browsing, W3C, Search Console) cannot reach a loopback host, so their items
report NO_DATA on both sites by design — those are covered by the stubbed unit tests
in test_evidence.py, and this file asserts that the reason is the honest one.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(ROOT, "skills", "seo-checklist")
SCRIPTS = os.path.join(SKILL, "scripts")
REGISTRY = os.path.join(SKILL, "resources", "config", "checklist.json")
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import FixtureSite, spawn  # noqa: E402

FAIL, PASS, WARN = "FAIL", "PASS", "WARN"
NO_DATA, MANUAL, LLM_PENDING, NA = "NO_DATA", "MANUAL", "LLM_PENDING", "N/A"
NEEDS_INPUT = "NEEDS_INPUT"
DECIDED = (PASS, FAIL, WARN)

SITE = None
RESULTS = {}


def setUpModule():
    """Serve both fixtures and audit each one once. Two runs, not two per test."""
    global SITE
    SITE = FixtureSite().start()
    for name, url in (("good", SITE.good), ("broken", SITE.broken)):
        RESULTS[name] = audit(url, name)


def tearDownModule():
    if SITE:
        SITE.stop()


def audit(url: str, label: str) -> dict:
    """One full audit, through the runner, as an operator would get it.

    The operator-supplied inputs are supplied, so the nine items that read them are
    exercised in both directions rather than reporting NO_DATA on both. All three
    are hand-written and say so — see tests/fixtures/artifacts/README.md for what
    that does and does not verify.

    The access log is the one whose two versions differ on purpose rather than
    incidentally: the good site's log is a crawl that got what it asked for, 304s
    and all, and the broken site's is a crawl budget going nowhere. Supplying only
    one of them would let CI-018 pass by never being asked.
    """
    out = os.path.join(SITE.dir, f"{label}.json")
    artifacts = []
    for flag, filename in (("--cwv-json", "cwv.json"),
                           ("--rendered-json", "rendered.json"),
                           ("--server-log", "access.log")):
        path = SITE.artifact(label, filename)
        if path:
            artifacts += [flag, path]
    proc = spawn(
        [sys.executable, os.path.join(SCRIPTS, "checklist_runner.py"), url,
         "--allow-private", "--max-rps", "0", "--no-history", "--no-prompt",
         "--quiet", "--timeout", "120", "--json", out, *artifacts],
        timeout=900)
    if proc.returncode != 0:
        raise AssertionError(f"the {label} audit exited {proc.returncode}\n"
                             f"{proc.stdout[-3000:]}\n{proc.stderr[-3000:]}")
    with open(out, encoding="utf-8") as f:
        payload = json.load(f)
    payload["_stdout"] = proc.stdout
    return payload


def partial_audit(label: str, url: str, *extra: str) -> dict:
    """One `--only speed` run, for the questions a full audit cannot answer twice.

    Two of the artifact tests need a run configured differently from the two the
    module already did — a crossed artifact, and a sampled run. One category keeps
    that to seconds instead of the ten a full registry pass costs.
    """
    out = os.path.join(SITE.dir, f"{label}.json")
    proc = spawn(
        [sys.executable, os.path.join(SCRIPTS, "checklist_runner.py"), url,
         "--allow-private", "--max-rps", "0", "--no-history", "--no-prompt",
         "--quiet", "--only", "speed", "--timeout", "120", "--json", out, *extra],
        timeout=600)
    if proc.returncode != 0:
        raise AssertionError(f"the {label} run exited {proc.returncode}\n"
                             f"{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}")
    with open(out, encoding="utf-8") as f:
        return json.load(f)


def items(label: str) -> dict:
    return {i["id"]: i for i in RESULTS[label]["items"]}


def registry() -> dict:
    """The registry, indexed by id.

    The runner's graded rows carry the verdict, not the rule that produced it, so
    `requires` and `script` have to come from here. Reading them off the result rows
    silently yielded None for every item — and a filter keyed on None excludes
    nothing, which made a passing test out of an empty comparison.
    """
    with open(REGISTRY, encoding="utf-8") as f:
        return {i["id"]: i for i in json.load(f)["items"]}


REG = registry()


def script_of(item_id: str) -> str:
    return (REG[item_id].get("check") or {}).get("script", "")


def requires_of(item_id: str) -> str:
    return (REG[item_id].get("check") or {}).get("requires", "")


# ---------------------------------------------------------------------------
# Why an item can legitimately answer the same way on both sites.
#
# Every entry is a claim that has to stay true, not a way to quieten the test: the
# reason is checked against the item's own `requires` where that is possible, and a
# stale entry shows up as a test failure of its own below.
# ---------------------------------------------------------------------------

# Whole capabilities no loopback fixture can exercise. A third party cannot reach
# 127.0.0.1, so these are NO_DATA on both sites — verified, not assumed.
UNREACHABLE_REQUIRES = {"api", "gsc", "safe_browsing"}

# Items whose evidence is identical on both fixtures on purpose, with why. Anything
# not listed here has to differ, or the check cannot tell a good site from a bad one.
SAME_ON_BOTH = {
    # The two sites are the same shape by design: both are small, static, and
    # hand-written, so what they share is not something a fixture can vary.
    "AR-158": "neither fixture exposes a breadcrumb-named UI trail; the good entry's "
              "schema alone cannot satisfy a title that requires UI + Schema",
    "AR-146": "neither fixture paginates",
    "CN-055": "neither fixture paginates",
    "IN-121": "neither fixture is multilingual",
    "IN-122": "neither fixture is multilingual",
    "IN-124": "neither fixture is multilingual",
    "IN-125": "neither fixture is multilingual",
    "IN-126": "neither fixture is multilingual",
    "IN-127": "neither fixture is multilingual",
    "IN-128": "neither fixture is multilingual",
    "IN-129": "neither fixture is multilingual",
    "IN-130": "neither fixture is multilingual",
    "MD-188": "neither fixture embeds video",
    "MD-190": "neither fixture embeds video",
    "MB-102": "neither fixture embeds video",
    # Measured 2026-08-14 by the fixture oracle, which declared FAIL for both
    # origins and got PASS for both. The previous reason here was the one on the
    # line below, for a different item: silos have nothing to do with catalogues.
    "AR-153": "topical_cluster_mapper scores a flat five-page tree above its "
              "floor, and scores the duplicate-and-orphan tree there too, so "
              "the silo score does not separate structure from its absence",
    "AR-156": "neither fixture is an ecommerce catalogue",
    "AR-163": "neither fixture has faceted navigation",
    "LO-196": "neither fixture claims a physical location beyond the same address",
    "LO-197": "neither fixture claims a physical location beyond the same address",
    "LO-199": "neither fixture claims a physical location beyond the same address",
    "SE-115": "both fixtures are served over plain HTTP by the same server",
    "SE-117": "both fixtures are served over plain HTTP by the same server",
    "SE-118": "both fixtures are served over plain HTTP by the same server",
    "SE-120": "both fixtures are served by the same header-free http.server",
    "TE-175": "both fixtures are served by the same header-free http.server",
    # `TE-170` and `SP-110` were here until 0.50.0, both for the same reason: the
    # scripts behind them could say only `warning`, so the exemplary tree and the
    # tree built to be slow landed in one band. Grading the two findings that are
    # defects on every site — text served uncompressed, and a parser-blocking script
    # in `<head>` — separated them, and the good origin now compresses. Two entries
    # that read as facts about the fixtures were facts about the severity vocabulary.
    "TE-167": "both fixtures are up; downtime is not something a fixture can show",
    "TE-179": "no loopback fixture host has a whois record, so neither side can be dated",
    "SP-109": "neither fixture loads a third-party script",
    "TECH-002": "neither fixture loads a web font",
    "TECH-003": "the same server answers both, so TTFB does not differ",
    "CO-191": "competitor comparison has no data path at all yet",
    "CO-192": "competitor comparison has no data path at all yet",
    "CO-193": "competitor comparison has no data path at all yet",
    "CO-194": "competitor comparison has no data path at all yet",
    "CO-195": "competitor comparison has no data path at all yet",
    "BL-078": "backlink items need a link index this tool does not have",
    "BL-079": "backlink items need a link index this tool does not have",
    "BL-080": "backlink items need a link index this tool does not have",
    "BL-082": "backlink items need a link index this tool does not have",
    # BL-083 was here until 0.8.0 with the same reason, and the reason was wrong: it
    # reads `external_link_quality.summary.broken_links`, which is measurable without
    # any link index. It answered the same on both sites because a dead host produces
    # no status code and the count only looked for 4xx — so the ordinary form of link
    # rot was invisible. The exemption outlived a defect rather than a limitation.
    "BL-084": "backlink items need a link index this tool does not have",
    "BL-085": "backlink items need a link index this tool does not have",

    # --- The entry page has to stay readable on both sites -------------------
    # A broken entry page is already covered: the runner refuses to score a site it
    # cannot read, and `UnreachableSite` in test_runner.py tests that directly. Making
    # the broken fixture's entry 500 or robots-disallowed would gate the other 140
    # items and this whole file would measure nothing.
    "CI-003": "the entry page must return 200 on both, or the run is gated and no "
              "other item is exercised at all",
    "CI-015": "same: a 5xx entry page stops the audit instead of failing one item",
    "CI-005": "the broken site's own defect is having no robots.txt, and a missing "
              "robots.txt allows everything; one origin cannot both lack robots.txt "
              "and disallow its own entry page",
    "CI-013": "needs a robots.txt to test paths against, which the broken site "
              "deliberately does not have",
    "CI-002": "the broken sitemap is defective but not empty — an empty one would "
              "leave GO-136 and GO-138 with nothing to find",

    # --- Both audits enter at the origin root --------------------------------
    # url_quality judges the URL it was given. Both runs are handed `http://host/`,
    # which is a clean URL by construction. Exercising a bad URL means auditing one,
    # which is a different test — test_evidence.py covers url_quality on ugly input.
    "CI-012": "both audits enter at the origin root, which is a clean URL",
    "AR-147": "both audits enter at the origin root: no query parameters either way",
    "AR-155": "both audits enter at the origin root: no URL flags either way",

    # --- A static file server cannot do this --------------------------------
    "CI-014": "http.server cannot be made to serve a redirect loop",
    "AR-150": "http.server issues no redirects, so the hop count is 0 on both",
    "AR-149": "no internal redirects to find without a server that redirects",
    "MB-105": "both fixture artifacts omit html, so neither entry page has a rendered "
              "document to compare with what was served",
    "TE-169": "both entry pages serve internal links in the HTML, so the raw link "
              "count is non-zero on both",

    # --- One site cannot hold a defect and its opposite ---------------------
    "GO-131": "the broken site needs two GA4 tags for GO-132, so it necessarily has "
              "at least one and passes this",
    "MD-184": "the broken site needs images to fail the image checks, so both have "
              "at least one image",
    "MB-095": "image_weight_audit reports oversize by weight, and neither fixture "
              "ships an image big enough to trip it without bloating the repository",
    "MB-098": "0.93.0 moved this to `srcset_without_sizes_count`, which a fixture "
              "could express — but only by putting an `<img srcset>` in the broken "
              "tree, and that makes `responsive_count` 1 there, which hands MB-096 "
              "and MD-189 a pass on both. Two items would lose their discriminating "
              "power to give this one its",
    "CN-054": "both fixtures expose native image sources, so both are crawlable; "
              "the data-src-only failure direction is covered in test_evidence_scripts",

    # --- Needs an artifact this audit does not produce -----------------------
    # The `--cwv-json` and `--rendered-json` exemptions used to live here and are
    # gone: both files are supplied now (see `audit()` above), so the eight items
    # that read them differ. What is left is the export a human clicks in the
    # Search Console UI, which cannot be reduced to a file in this repository
    # without inventing somebody's backlink profile — a fabricated link graph is
    # the one thing worse than NO_DATA — and the IndexNow key, which is a secret.
    "BL-086": "needs --links-csv, a Search Console UI export",
    "BL-087": "needs --links-csv, a Search Console UI export",
    "GEO-007": "needs an IndexNow key, which is a secret and not a fixture",

    # --- Would take the suite online ----------------------------------------
    # The one exemption worth arguing with. entity_checker verifies sameAs targets by
    # fetching them, so a fixture with a real Wikidata link would make this suite
    # reach the internet — see PLACEHOLDER_EXTERNAL in harness.py for what the
    # fixtures do instead where a link only has to be counted.
    "GEO-006": "sameAs targets are verified by fetching wikipedia/wikidata; an "
               "offline fixture cannot demonstrate them without egress",
    "KW-076": "no keyword is supplied to a fixture run, so neither side is measured",
    "TECH-001": "rich_results_guard emits warnings only for schema types it has "
                "required-property rules for; neither fixture carries one",
    "GO-143": "schema_required_props reports on schemas that are present, so a site "
              "with no WebSite block produces no issue to match — the item cannot "
              "fail on absence, only on a node present and incomplete. `SearchAction` "
              "left this sentence in 0.89.0 with the recommendation that put it here: "
              "the type has no property table of its own, so it never reached a "
              "message except as a WebSite's missing potentialAction",
}

# Warn bands the fixtures exercise the item around but never land in.
#
# The summary line of the oracle counts items, not states, so an item covered on
# both sides can still carry a band nobody has ever seen. Twenty-eight items had a
# band when this was first measured; eleven of them WARN on a fixture, and one —
# CN-048 — turned out to be a band no page could reach at all, which is now
# `audit_reachability.py`'s business rather than a fixture question.
#
# An item that answers the same on both sides is not listed here: `SAME_ON_BOTH`
# already records why the fixtures cannot tell it apart, and a pair that cannot
# make the assertion fail certainly cannot reach what lies past it. One fact, one
# record. What is left is the item the fixtures *do* exercise, past the band and
# into FAIL.
BAND_UNSEEN = {
    "SP-110": "the band needs a medium with no high, and since 0.87.0 the only "
              "medium this script emits is a parser-blocking script outside the "
              "head. Neither fixture has one: the good origin's single head script "
              "is the async gtag loader and the broken origin's is synchronous and "
              "in the head, which is the high the item fails on. The stylesheet that "
              "used to reach this band is graded info, because every site has one",
    "CI-018": "the band needs a log whose worst finding is medium; the broken "
              "fixture's log has 43.8% of bot requests returning nothing indexable, "
              "which is graded above that, so the item fails before the band",
    "GEO-008": "the band needs a limited snippet on rows.0, but each fixture has "
               "one entry: the good entry is full and the broken entry carries "
               "nosnippet and is suppressed. Replacing either declaration would "
               "lose that side; test_evidence.SnippetControls exercises WARN with "
               "max-snippet:120 and data-nosnippet pages against a real server",
    "MS-032": "the band is errors above zero with at most three warnings. Measured "
              "on the fixtures: good is 0 errors and 2 warnings, broken is 3 errors "
              "and 5 warnings, so one passes and the other overshoots",
    "TE-170": "the band needs a medium with no high, and this invocation reaches "
              "only one: a compressed response whose Vary omits accept-encoding. "
              "The good origin compresses and sends Vary: Accept-Encoding, so it "
              "has nothing medium; the broken origin compresses nothing and takes "
              "the high instead. The cache-lifetime medium needs --include-assets, "
              "which TE-170 does not pass",
    "MD-185": "the band needs Large image transfer size, which fires above "
              "LARGE_IMAGE_BYTES = 250,000. The largest image in either tree is "
              "broken/assets/huge.png at 54,606 bytes, kept small on purpose — the "
              "same reason MB-095 is in SAME_ON_BOTH, and not something a fixture "
              "can change without bloating the repository",
}


class BothAuditsRan(unittest.TestCase):
    """If either audit did not really happen, every assertion below is vacuous."""

    def test_neither_audit_crashed_a_script(self):
        for label in ("good", "broken"):
            failures = RESULTS[label]["script_failures"]
            detail = "\n".join(f"  {k}: {v['error']}"
                               for k, v in RESULTS[label]["runs"].items()
                               if v.get("error"))
            self.assertEqual(failures, {}, f"{label}:\n{detail}")

    def test_both_entry_pages_were_read(self):
        for label in ("good", "broken"):
            self.assertTrue(RESULTS[label]["entry_reachable"],
                            f"{label}: {RESULTS[label]['entry_error']}")
            self.assertIsNone(RESULTS[label]["entry_guard"],
                              f"{label} tripped the page guard; the fixture is wrong, "
                              f"not the site")

    def test_both_audits_decided_a_meaningful_share_of_the_registry(self):
        for label in ("good", "broken"):
            decided = RESULTS[label]["scores"]["decided"]
            self.assertGreater(decided, 60, f"{label} decided only {decided} items")

    def test_the_broken_site_scores_worse_than_the_good_one(self):
        """The coarsest possible sanity check, and it would have caught a whole class
        of nonsense: if the score cannot tell these two apart, nothing below matters."""
        good = RESULTS["good"]["scores"]["seo_score"]
        broken = RESULTS["broken"]["scores"]["seo_score"]
        self.assertLess(broken, good, f"good {good}, broken {broken}")


class EveryCheckCanTellTheSitesApart(unittest.TestCase):
    """The point of the file.

    An item that answers identically on a good site and a deliberately broken one is
    either measuring something the fixtures do not differ on — which has to be said
    out loud, per item, in SAME_ON_BOTH — or it cannot distinguish a good site from a
    bad one. There is no third possibility, and for thirty-three items in this
    registry's history the answer was the second one.
    """

    def setUp(self):
        self.good, self.broken = items("good"), items("broken")
        self.script_backed = [i for i in RESULTS["good"]["items"]
                              if REG[i["id"]].get("source") == "script"]

    def differing(self):
        return {i["id"] for i in self.script_backed
                if self.good[i["id"]]["status"] != self.broken[i["id"]]["status"]}

    def test_most_script_items_differ_between_the_two_sites(self):
        differ = self.differing()
        self.assertGreater(len(differ), 30,
                           f"only {len(differ)} of {len(self.script_backed)} items "
                           f"noticed the difference between the fixtures")

    def test_every_item_that_answers_the_same_has_a_stated_reason(self):
        same = []
        for item in self.script_backed:
            item_id = item["id"]
            if item_id in self.differing() or item_id in SAME_ON_BOTH:
                continue
            if requires_of(item_id) in UNREACHABLE_REQUIRES:
                continue          # covered by its own test below
            same.append(f"{item_id} ({item['severity']}, {script_of(item_id)}) "
                        f"{self.good[item_id]['status']} on both — "
                        f"{(self.good[item_id].get('evidence') or '')[:70]}")
        self.assertEqual(same, [], "these items cannot tell the fixtures apart:\n"
                                   + "\n".join(f"  {s}" for s in same))

    def test_no_exemption_outlives_the_reason_for_it(self):
        """A stale exemption is a check nobody is verifying any more, which is the
        same failure as a stale caveat in the docs."""
        stale = sorted(item_id for item_id in SAME_ON_BOTH
                       if item_id in self.differing())
        self.assertEqual(stale, [], "these are listed as indistinguishable and now "
                                    "differ; drop them from SAME_ON_BOTH")

    def test_every_exemption_names_an_item_that_exists(self):
        known = {i["id"] for i in RESULTS["good"]["items"]}
        self.assertEqual(sorted(set(SAME_ON_BOTH) - known), [])


class EveryWarnBandTheFixturesReachHasBeenSeen(unittest.TestCase):
    """A band is a third verdict, and a third verdict nobody has observed is a
    promise rather than a measurement.

    The oracle reports coverage per item, so an item declared on both sides and
    matched on both counts as covered while its WARN has never happened. Of the
    twenty-seven bands in the registry, eleven have produced a WARN on a fixture;
    the rest are either out of the fixtures' reach entirely — an API, a Search
    Console property, a video the fixtures do not embed — or listed above with the
    reason the pair passes the band by.
    """

    def banded(self):
        return [i for i in RESULTS["good"]["items"]
                if (REG[i["id"]].get("check") or {}).get("warn")]

    def states(self, item_id):
        good = {i["id"]: i for i in RESULTS["good"]["items"]}
        broken = {i["id"]: i for i in RESULTS["broken"]["items"]}
        return good[item_id]["status"], broken[item_id]["status"]

    def seen(self):
        return {i["id"] for i in self.banded() if WARN in self.states(i["id"])}

    def test_a_fixture_reaches_some_band(self):
        """Otherwise the rest of this class is about an empty set."""
        self.assertGreater(len(self.seen()), 5)

    def test_every_band_the_fixtures_exercise_is_seen_or_explained(self):
        unexplained = []
        for item in self.banded():
            item_id = item["id"]
            good, broken = self.states(item_id)
            if WARN in (good, broken) or item_id in BAND_UNSEEN:
                continue
            # Same answer on both: SAME_ON_BOTH holds the reason for the whole item,
            # the band included. Undecided on either: the fixtures never got near it.
            if good == broken or not (good in DECIDED and broken in DECIDED):
                continue
            unexplained.append(f"{item_id} ({script_of(item_id)}) {good} -> {broken}, "
                               f"and its warn band has never fired")
        self.assertEqual(unexplained, [], "\n".join(f"  {u}" for u in unexplained))

    def test_no_band_reason_outlives_the_band(self):
        """The twin of `test_no_exemption_outlives_the_reason_for_it`: a band that
        now fires must leave this list, or the list is describing the past."""
        stale = sorted(set(BAND_UNSEEN) & self.seen())
        self.assertEqual(stale, [], "these now WARN on a fixture; drop them from "
                                    "BAND_UNSEEN")

    def test_every_band_reason_names_an_item_that_still_has_a_band(self):
        banded = {i["id"] for i in self.banded()}
        self.assertEqual(sorted(set(BAND_UNSEEN) - banded), [])


class NothingAccusesTheGoodSiteWithoutAReason(unittest.TestCase):
    """Difference is not direction, and this file could not tell them apart.

    `test_every_item_that_answers_the_same_has_a_stated_reason` is satisfied by any
    difference — including a check that fails the good site and passes the broken
    one, which is worse than a check that cannot tell them apart at all. BL-081 was
    in exactly that state: five navigation links carrying the anchor "home" made the
    well-built fixture "exact-match anchor overuse", the broken fixture had no
    repeated anchors to find, and the pair recorded a difference and called it
    working.

    So: no script-backed item may FAIL or WARN on the good site unless this list says
    why. The list is long because the fixture is served by `http.server` over plain
    HTTP and carries a few defects on purpose — every entry is a statement about the
    fixture, and a wrong one shows up as a test that will not go green.
    """

    # Short, and it was longer: the first draft copied the deliberate-defect table out
    # of tests/fixtures/good/README.md, and six of those entries were stale — the
    # orphan and the duplicate description moved to the broken fixture two releases
    # ago and the README still described them. This test found the documentation drift
    # by refusing to accept an exemption nothing needs.
    ACCUSED_ON_PURPOSE = {
        "AR-158": "the good fixture has BreadcrumbList schema but deliberately no "
                  "breadcrumb-named UI trail",
        "SE-115": "served over plain HTTP, where the fixture cannot enable HSTS",
        "SE-117": "served over plain HTTP by http.server: HSTS cannot be present",
        # SE-118 was here until 0.20, when it stopped reading `https` off
        # security_headers.py and started verifying an actual certificate. On an
        # http:// fixture there is no certificate to inspect, so it now resolves to
        # NO_DATA rather than accusing anything, and this test demanded its removal.
        # Worth stating plainly: no fixture in this suite can exercise SE-118 — both
        # sites are plaintext and http.server does not speak TLS. Its only coverage
        # is tests/test_tls_certificate.py, which stands up its own TLS origin.
        "SE-120": "http.server sends no security headers at all",
        # TE-170 was here until 0.50.0, on the same http.server reasoning as TE-175
        # below. It left because the reasoning stopped being true rather than because
        # the item softened: the good origin now serves gzip with Vary and a validator
        # header, so an exemplary tree passes the item about server configuration
        # instead of being excused from it.
        "TE-175": "http.server sends no cache headers and no gzip",
        # SP-110 was here until 0.87.0, and it left because the reasoning stopped
        # being true: a render-blocking stylesheet is how CSS is delivered, not a
        # defect the good fixture carries on purpose, and it is graded `info` now.
        "GEO-006": "entity_checker verifies sameAs targets by fetching them, so a "
                   "fixture with real Wikidata links would take this suite online — "
                   "see PLACEHOLDER_EXTERNAL in harness.py",
    }

    def setUp(self):
        self.good = items("good")
        self.script_backed = [i for i in RESULTS["good"]["items"]
                              if REG[i["id"]].get("source") == "script"]

    def test_no_item_accuses_the_good_fixture_without_a_written_reason(self):
        accused = []
        for item in self.script_backed:
            item_id = item["id"]
            if item_id in self.ACCUSED_ON_PURPOSE:
                continue
            status = self.good[item_id]["status"]
            if status in (FAIL, WARN):
                accused.append(f"{item_id} ({item['severity']}, "
                               f"{script_of(item_id)}) {status} — "
                               f"{(self.good[item_id].get('evidence') or '')[:90]}")
        self.assertEqual(accused, [],
                         "these items report a defect in the fixture the pair calls "
                         "good. Either the check answers backwards, or the fixture "
                         "really is wrong and this list should say so:\n"
                         + "\n".join(f"  {a}" for a in accused))

    def test_every_reason_still_describes_something(self):
        """An accusation that stops happening leaves a reason nobody is checking."""
        stale = sorted(item_id for item_id, _ in self.ACCUSED_ON_PURPOSE.items()
                       if self.good.get(item_id, {}).get("status") not in (FAIL, WARN))
        self.assertEqual(stale, [], "these no longer report anything on the good "
                                    "fixture; drop them from ACCUSED_ON_PURPOSE")


class TheBrokenSiteFailsWhatItWasBuiltToFail(unittest.TestCase):
    """Direction, not just difference.

    `test_every_item_that_answers_the_same` proves a check *moved*; these name what it
    should have moved to. Each line is a defect written into the fixture on purpose,
    so a check that reports it backwards — which is how the CrUX rating bug read a
    fast page as failing — shows up here rather than in a client's report.
    """

    def setUp(self):
        self.good, self.broken = items("good"), items("broken")

    def assertMoved(self, item_id, expect_good, expect_broken):
        self.assertEqual(self.good[item_id]["status"], expect_good,
                         f"{item_id} on the good site: "
                         f"{self.good[item_id].get('evidence')}")
        self.assertIn(self.broken[item_id]["status"], expect_broken,
                      f"{item_id} on the broken site: "
                      f"{self.broken[item_id].get('evidence')}")

    def test_the_page_level_basics(self):
        # title, one h1, viewport, lang, meta description, meta keywords.
        #
        # MS-027 was on this list and is not any more. It asserted `meta_description
        # truthy` — the same field, script and rule as MS-028 — so "write a unique,
        # compelling description" was answered by "a description exists" and could not
        # fail on any page MS-028 passed. Uniqueness is MS-029's job as of 0.22 and
        # compelling is a judgement, so the item went to the copy lens. What it used to
        # cover here is covered by MS-028, which is on this list and always was.
        for item_id in ("MS-026", "CN-065", "MB-093", "IN-123", "MS-028", "MS-031"):
            self.assertMoved(item_id, PASS, (FAIL, WARN))

    def test_noindex_is_reported_as_not_indexable(self):
        for item_id in ("CI-001", "CI-004"):
            self.assertMoved(item_id, PASS, (FAIL,))
        self.assertMoved("GEO-008", PASS, (FAIL,))

    def test_a_canonical_pointing_at_another_domain_fails(self):
        self.assertMoved("CI-009", PASS, (FAIL,))

    def test_a_missing_robots_txt_fails_and_a_present_one_passes(self):
        """Two origins is what makes this testable: robots.txt is per-origin, so one
        document root cannot be both present and absent."""
        self.assertMoved("AR-151", PASS, (FAIL,))

    def test_an_absent_llms_txt_fails(self):
        self.assertMoved("GEO-001", PASS, (FAIL,))

    def test_images_without_alt_text_are_found(self):
        self.assertMoved("MD-186", PASS, (FAIL, WARN))

    def test_a_broken_internal_link_is_found(self):
        self.assertMoved("TE-168", PASS, (FAIL, WARN))

    def test_duplicate_pages_are_found(self):
        self.assertMoved("CN-041", PASS, (FAIL, WARN))

    def test_a_sitemap_full_of_problems_is_reported(self):
        self.assertMoved("GO-136", PASS, (FAIL, WARN))

    def test_the_lab_vitals_face_the_right_way(self):
        """820ms passes LCP and 5200ms fails it.

        Which sounds too obvious to test until you remember what 0.5.0 found:
        SP-107/113 and SE-119 compared a rating to `"fast"`, so a fast page with no
        CrUX sample *failed*. Three assertions read a real measurement and reached
        the opposite verdict, and nothing noticed because no test ever gave them a
        good number and a bad one.
        """
        for item_id in ("SP-214", "SP-215", "SP-216"):
            self.assertMoved(item_id, PASS, (FAIL, WARN))

    def test_the_rendered_page_measurements_are_read_in_both_directions(self):
        """Including MB-094, whose count is derived rather than supplied: neither
        artifact carries `mobile_overlays_covering_content`, so this is also the
        assertion that the derivation from a phone-width viewport happens at all."""
        for item_id in ("CN-034", "CN-035", "CN-051", "MB-094", "MB-103"):
            self.assertMoved(item_id, PASS, (FAIL, WARN))


class UnreachableCapabilitiesSayWhy(unittest.TestCase):
    """PageSpeed, Safe Browsing, the W3C validator and Search Console cannot reach a
    loopback host. That has to arrive as NO_DATA carrying the reason — not as a
    failure of the site, and not as a crash. It is also the one thing 0.4.0 fixed
    that a fixture audit can confirm end to end."""

    def test_external_api_items_are_undecided_with_the_private_host_reason(self):
        for label in ("good", "broken"):
            for item in RESULTS[label]["items"]:
                if requires_of(item["id"]) not in UNREACHABLE_REQUIRES:
                    continue
                self.assertIn(item["status"], (NO_DATA, MANUAL, NA),
                              f"{label} {item['id']}: {item.get('evidence')}")
                if item["status"] == NO_DATA:
                    self.assertIn("only reachable from here",
                                  item.get("evidence") or "",
                                  f"{label} {item['id']} is undecided for the wrong "
                                  f"stated reason")


class ArtifactsMustDescribeTheAuditedPage(unittest.TestCase):
    """A browser artifact is the one input this run cannot verify by re-measuring.

    Nothing else in an audit is like it: every other verdict comes from a request
    this process made, and can be checked by making it again. A trace is a file
    somebody hands over, and the only question available is whether it says which
    page it is about. Ten items are decided from these two files, three of them
    `high`, so an artifact from the wrong page is ten fabricated verdicts — and
    it would look exactly like a clean result.
    """

    def test_both_audits_recorded_what_they_were_handed(self):
        for label in ("good", "broken"):
            recorded = RESULTS[label]["artifacts"] or {}
            self.assertEqual(sorted(recorded), ["cwv_json", "rendered_json"], label)
            for key, entry in recorded.items():
                self.assertTrue(entry["matches_audited_url"],
                                f"{label} {key}: {entry}")

    def test_the_fixture_artifacts_keep_admitting_they_were_written_by_hand(self):
        """`source` is the only thing standing between a fixture and a fabrication.

        These files hold numbers no browser produced. That is defensible for a test
        and indefensible silently, and `source` is where the script, the results and
        the report all read it from — so if this string ever quietly becomes
        "chrome-devtools MCP trace", the fixture has started lying about itself.
        """
        for label in ("good", "broken"):
            for entry in (RESULTS[label]["artifacts"] or {}).values():
                with open(entry["path"], encoding="utf-8") as f:
                    self.assertIn("hand-written", json.load(f)["source"],
                                  f"{label}: {entry['path']}")

    def test_an_artifact_from_the_other_site_is_refused_with_the_reason(self):
        """The end-to-end half of the guard, through the real runner.

        Deliberately a whole run rather than a unit test of `same_page`: the failure
        this prevents is not a comparison returning the wrong boolean, it is three
        passing items in a delivered report. `--only speed` keeps the cost to a few
        seconds.
        """
        crossed = partial_audit("crossed", SITE.good, "--cwv-json",
                                SITE.artifact("broken", "cwv.json"))
        self.assertFalse(crossed["artifacts"]["cwv_json"]["matches_audited_url"],
                         crossed["artifacts"])

        rows = {i["id"]: i for i in crossed["items"]}
        for item_id in ("SP-214", "SP-215", "SP-216"):
            row = rows[item_id]
            self.assertEqual(row["status"], NEEDS_INPUT,
                             f"{item_id} was decided from a trace of another page: "
                             f"{row.get('evidence')}")
            # The reason has to name the other page. "missing input" would send the
            # operator off to produce a file they have already produced.
            self.assertIn("describes", row.get("evidence") or "")
            self.assertIn(SITE.origin("broken"), row.get("evidence") or "")

    def test_one_measured_page_does_not_become_a_verdict_about_four_others(self):
        """A sampled run must leave the artifact items alone.

        Every sampled page inherits the run's context, so the same trace used to be
        read once per URL — and because the reader returns the same numbers every
        time, the aggregate reported "4/4 pages" about pages no browser had opened.
        The assertion is the absence of a page count on those items, next to its
        presence on the others: without the second half this test would also pass
        if sampling had silently stopped happening.
        """
        sampled = partial_audit("sampled", SITE.good, "--sample", "3",
                                "--cwv-json", SITE.artifact("good", "cwv.json"))
        rows = {i["id"]: i for i in sampled["items"]}
        self.assertGreater(len(sampled["sampled_urls"]), 1, sampled["sampled_urls"])

        counted = [i["id"] for i in sampled["items"] if "pages_checked" in i]
        self.assertTrue(counted, "no item carried a page count, so this run did not "
                                 "sample anything and proves nothing")
        for item_id in ("SP-214", "SP-215", "SP-216"):
            self.assertEqual(rows[item_id]["status"], PASS, rows[item_id])
            self.assertNotIn("pages_checked", rows[item_id],
                             f"{item_id} claims a page count, but one trace of one "
                             f"page is all that was measured")

    def test_sampled_evidence_names_every_sampled_url(self):
        """The delivered evidence must contain each page that contributed to the
        aggregate, while the entry-page script mapping stays at the top level."""
        evidence_path = os.path.join(SITE.dir, "sampled-pages-evidence.json")
        sampled = partial_audit("sampled-with-evidence", SITE.good, "--sample", "3",
                                "--evidence-json", evidence_path)
        with open(evidence_path, encoding="utf-8") as stream:
            evidence = json.load(stream)
        self.assertEqual(set(evidence["pages"]), set(sampled["sampled_urls"]))
        self.assertEqual(set(evidence) - {"pages"}, set(sampled["runs"]))


class NothingIsDecidedWithoutEvidence(unittest.TestCase):
    """Every decided item must carry the evidence it was decided on, and every
    undecided one must say why. A status with an empty evidence string is a verdict
    nobody can check — the shape of every bug in this tool's history."""

    def test_every_decided_item_shows_its_evidence(self):
        empty = [f"{label} {i['id']} {i['status']}"
                 for label in ("good", "broken")
                 for i in RESULTS[label]["items"]
                 if i["status"] in DECIDED and not (i.get("evidence") or "").strip()]
        self.assertEqual(empty, [])

    def test_every_undecided_item_states_a_reason(self):
        empty = [f"{label} {i['id']}"
                 for label in ("good", "broken")
                 for i in RESULTS[label]["items"]
                 if i["status"] == NO_DATA and not (i.get("evidence") or "").strip()]
        self.assertEqual(empty, [])

    def test_no_item_is_missing_from_either_run(self):
        with open(REGISTRY, encoding="utf-8") as f:
            expected = {i["id"] for i in json.load(f)["items"]}
        for label in ("good", "broken"):
            self.assertEqual({i["id"] for i in RESULTS[label]["items"]}, expected,
                             f"{label} did not report on every registry item")


class TheRunSaysWhetherItUsedACache(unittest.TestCase):
    """`openspec/specs/http/` HTTP-8. With the cache off two items may describe two states of the
    same document; with it on, a verdict may be about a response fetched earlier in the
    run. Either way the artifact has to say which, because it is the difference between
    "this is the page" and "this was the page a few minutes ago".

    The field was written and read by nothing — the suite mentioned it zero times and
    `--no-http-cache` had no test. What is held here is the recording, and since 0.94.1 the
    other half of the requirement's argument as well: that the cache belongs in the report's
    provenance list beside the parser and the private host and the stale artifact.

    That half was pinned here as an *absence* while it was missing, in a test written to
    fail at the moment it was closed and to say so in its own message. It did, on a real
    audit that answered 69 responses off disk, and the assertion below is what replaced it.
    """

    def test_a_normal_run_records_that_the_cache_was_on(self):
        self.assertIs(RESULTS["good"]["http_cache"], True)

    def test_turning_the_cache_off_is_recorded_too(self):
        """Both directions, because a field hard-coded to `True` would satisfy the
        first test and record nothing."""
        run = partial_audit("nocache", SITE.good, "--no-http-cache")
        self.assertIs(run["http_cache"], False)

    def test_the_reader_of_the_report_is_told_the_cache_answered(self):
        """The end of the chain, on a real audit rather than a constructed payload: this
        run fetched a live fixture site, answered part of it from disk, and the sentence a
        person is handed says so and says how many.

        Counted across processes, which is the half a unit test cannot reach — every
        checker is its own process, so a tally kept in memory would be zero here.
        """
        from checklist_report import provenance_warnings
        data = dict(RESULTS["good"], html_parser="lxml", entry_private=False,
                    allow_private=False, entry_guard="", entry_thin=False,
                    artifacts={})
        self.assertGreater(data["http_cache_hits"], 0,
                           "this audit answered nothing from the cache, so it cannot say "
                           "whether the warning would appear")
        printed = [w for w in provenance_warnings(data) if "cache" in w.lower()]
        self.assertEqual(len(printed), 1, provenance_warnings(data))
        self.assertIn(str(data["http_cache_hits"]), printed[0])

    def test_a_run_without_the_cache_says_nothing_about_it(self):
        """The conditional half. A warning on every run is one a reader learns to skip,
        which is why the parser warning is silent for `lxml` too."""
        from checklist_report import provenance_warnings
        run = partial_audit("nocache-provenance", SITE.good, "--no-http-cache")
        self.assertEqual(run["http_cache_hits"], 0)
        self.assertEqual([w for w in provenance_warnings(run) if "cache" in w.lower()], [])


class TheRecordDoesNotDependOnHowItWasInvoked(unittest.TestCase):
    """`--diff` decides whether the comparison is *printed*, never whether it exists.

    `openspec/specs/history/` HST-8. The artifact is what a later run and a later reader work
    from, so a comparison that appears only when somebody passed a flag makes the
    record depend on how the tool was invoked that day. Nothing asserted this, and the
    flag was named by no test function.

    Two runs are needed, and history is written under `os.getcwd()`, so this moves the
    process's own directory rather than the child's: `harness.spawn` passes no `cwd` on
    purpose — giving one makes CPython fork, which segfaults on macOS — and the child
    inherits ours. `--only speed` keeps each pass to seconds.

    **Skipped on Windows, and the skip is the finding.** Writing this is what found
    `a-run-under-a-ported-host-cannot-be-filed-on-windows`: the fixture is served on
    `127.0.0.1:<port>`, `history_path` files a run under that netloc verbatim, and
    Windows rejects a colon in a path component — so the runner dies *after* finishing
    the audit. Every other invocation of the runner in this suite and in CI passes
    `--no-history`, which is exactly why nobody had met it. The skip goes when the
    release deciding how a ported host is filed lands; until then HST-8 is read on three
    of the five CI jobs and unread on the other two, which is what `openspec/specs/history/` now
    says.
    """

    @unittest.skipIf(os.name == "nt",
                     "history_path cannot make a directory named "
                     "'127.0.0.1:<port>' on Windows — known issue "
                     "a-run-under-a-ported-host-cannot-be-filed-on-windows")
    def test_the_payload_carries_the_comparison_though_nobody_asked_to_see_it(self):
        return self.check()

    def audit_into(self, out_name):
        out = os.path.join(SITE.dir, out_name)
        proc = spawn(
            [sys.executable, os.path.join(SCRIPTS, "checklist_runner.py"), SITE.good,
             "--allow-private", "--max-rps", "0", "--no-prompt", "--quiet",
             "--only", "speed", "--timeout", "120", "--json", out],
            timeout=600)
        if proc.returncode != 0:
            raise AssertionError(f"{out_name} exited {proc.returncode}\n"
                                 f"{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}")
        with open(out, encoding="utf-8") as f:
            payload = json.load(f)
        return payload, proc.stdout

    def check(self):
        home = os.getcwd()
        self.addCleanup(os.chdir, home)
        work = tempfile.mkdtemp(prefix="seo-history-")
        self.addCleanup(shutil.rmtree, work, True)
        os.chdir(work)

        first, _ = self.audit_into("history-first.json")
        self.assertIsNone(first["diff"], "nothing to compare the first run against")
        self.assertIsNone(first["compared_with"])

        second, stdout = self.audit_into("history-second.json")
        self.assertIsNotNone(second["diff"],
                             "the second run did not record a comparison; a reader of "
                             "the artifact cannot tell whether the last round of fixes "
                             "worked")
        self.assertIsNotNone(second["compared_with"])
        self.assertEqual(second["compared_with"]["started_at"], first["started_at"],
                         "the comparison does not name the run it was made against")

        # The content, not just the key. An independent review of this test pointed out
        # that `is not None` passes on a comparison with a wrong or garbage body, which
        # is the one thing an integration test is well placed to catch and this one was
        # not catching. Two audits of one unchanged fixture have nothing to report, so
        # the body must be exactly empty — a comparison inventing changes, or carrying
        # some other run's, fails here.
        self.assertEqual(second["diff"], [],
                         "two audits of an unchanged fixture reported status changes")
        before = {i["id"]: i["status"] for i in first["items"]}
        after = {i["id"]: i["status"] for i in second["items"]}
        self.assertEqual(
            sorted(i for i in before if before[i] != after.get(i)), [],
            "the fixture answered differently on the second pass, so the empty diff "
            "above is not evidence of anything; this test needs a stable fixture")
        for field in ("registry_version", "mode", "profile"):
            self.assertEqual(second["compared_with"][field], first[field],
                             f"the comparison misreports the previous run's {field}")

        # The other half of the requirement: the flag was not passed, so nothing about
        # the comparison was printed — and the record carries it anyway.
        self.assertNotIn("Changed since previous run", stdout)
        self.assertNotIn("Diff:", stdout)



class EveryStatusCarriesEvidenceIncludingTheTwoNobodyChecked(unittest.TestCase):
    """`openspec/specs/verdicts/` VRD-10: no status is emitted without a sentence saying
    what was decided, what was sought and not found, or which input was missing.

    Evidence was checked for six of the eight. `NEEDS_INPUT` and `LLM_PENDING` were not —
    and they are 55 of the 217 items on a real run, so the unchecked pair is a quarter of
    the registry. Both carry evidence today; nothing required them to.

    The status set is derived from `STATUS_ORDER` rather than listed here, and that is the
    point rather than a convenience. The reason these two were missed is that the original
    check named the statuses it covered, and a list cannot say what is absent from it —
    the comment above `STATUS_ORDER` makes the same argument about the three places
    statuses are rendered. A ninth status added to that tuple is covered here the day it
    is added.
    """

    def test_every_status_the_report_can_render_is_covered_by_this_test(self):
        """Guards the guard: if a status is emitted by a run and is not in `STATUS_ORDER`,
        the loop below would skip it silently."""
        from checklist_report import STATUS_ORDER
        seen = {i["status"] for label in ("good", "broken")
                for i in RESULTS[label]["items"]}
        self.assertEqual(seen - set(STATUS_ORDER), set(),
                         "a run produced a status no surface knows how to render")

    def test_no_item_of_any_status_is_emitted_without_evidence(self):
        from checklist_report import STATUS_ORDER
        for status in STATUS_ORDER:
            rows = [(label, i["id"]) for label in ("good", "broken")
                    for i in RESULTS[label]["items"] if i["status"] == status]
            with self.subTest(status=status, seen=len(rows)):
                if not rows:
                    self.skipTest("neither fixture run produced %s" % status)
                empty = [f"{label} {item_id}" for label, item_id in rows
                         if not (dict((i["id"], i) for i in RESULTS[label]["items"])
                                 [item_id].get("evidence") or "").strip()]
                self.assertEqual(empty, [], "%s items with no evidence" % status)

if __name__ == "__main__":
    unittest.main()
