"""Declared fixture expectations, compared with two real runner audits.

The manifest is the oracle. Its verdicts were written from checklist titles and
fixture construction before this module was run; this file only loads and reports
them. A mismatch is a triage input, not permission to edit either side silently.

Nothing in this module can be run without running the fixtures. `setUpModule`
audits all four origins whichever test is selected, so
`unittest tests.test_fixture_oracle.ManifestContract` — a check that the id sets
and the manifest agree, touching no verdict — answers every undeclared item on the
way. **Commit a new declaration before running anything here at all**, including
the tests that look like they only read the manifest. This cost the ordering proof
for one batch on 2026-08-14; the declarations were written first and git cannot
show it.
"""
from __future__ import annotations

import json
import os
import sys
import unittest
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "skills", "seo-checklist", "scripts")
REGISTRY = os.path.join(
    ROOT, "skills", "seo-checklist", "resources", "config", "checklist.json")
MANIFEST = os.path.join(ROOT, "tests", "fixtures", "expectations.json")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import FixtureSite, spawn  # noqa: E402

HTTP_DECLARED_IDS = {
    "AR-146", "AR-151", "AR-158", "AR-162", "BL-081", "BL-084",
    "BL-086", "BL-087", "CI-004", "CI-008", "CI-019", "CN-034",
    "CN-035", "CN-041", "CN-048", "CN-051", "CN-054", "CN-065",
    "CN-066", "GO-132", "GO-137", "GO-138", "IN-123", "LO-200",
    "MB-093", "MB-094", "MB-096", "MB-097", "MB-103", "MB-104",
    "MD-185", "MS-020", "MS-021", "MS-022", "MS-026", "MS-028",
    "MS-029", "MS-030", "MS-031", "SP-214", "SP-215", "SP-216",
    "SE-117", "TE-166", "TE-168", "TE-172", "TE-174", "TECH-001",
    # Stage 2b, the first six of the sixty-eight decidable items nobody had
    # declared. Five more crawl items were left undeclared on purpose: their
    # verdicts had already been read off a run in the session that would have
    # declared them, and a declaration made after seeing the answer proves
    # nothing. See ROADMAP.md.
    "BL-083", "CI-001", "CI-003", "CI-005", "CI-015", "LO-198",
    "AR-147", "AR-155", "CI-006", "CI-009", "CI-011", "CI-012", "CI-016",
    "GEO-001", "MD-186", "MD-187", "TE-176",
    # Stage 2c: the five crawl items left undeclared above, the twelve fetch
    # items whose verdicts a warn-band measurement had already printed, and
    # the three that were declared and withdrawn. No session that had read
    # those verdicts could declare them; this batch was written by one that
    # had not.
    #
    # MS-033, CN-068 and GO-131 are the withdrawn three, and their `good` side
    # is honest about not being blind: HANDOFF-4 §5.2 records what the sampled
    # run answered. Each is reasoned from /privacy.html, which carries no
    # social tags, no analytics snippet and no byline, and all three are
    # declared *before* the fixture question in KNOWN-ISSUES.md §6 is settled,
    # so repairing the fixture has to disagree with a declaration rather than
    # quietly agree with itself.
    "AR-149", "AR-154", "AR-163", "CI-018", "CN-039", "CN-068", "GEO-008",
    "GO-131", "GO-136", "MB-102", "MD-190", "MS-032", "MS-033", "SP-109",
    "SP-110", "TE-170", "TECH-002",
    # Stage 2d. One is INDETERMINATE on purpose and it is not a shrug: MB-105
    # compares served HTML against a rendered DOM, but both fixture artifacts omit
    # html. The title question this raised was settled in 0.72.0; with no rendered
    # document, there is still nothing to compare and no settled verdict to write.
    #
    # KW-076 was the other, until 0.48.0 gave the registry `--no-autocomplete` and
    # this module a keyword to pass. Its declaration was written before the first run
    # that could answer it, as every declaration here is.
    "AR-152", "CI-013", "CN-036", "GEO-002", "GEO-003", "KW-076", "MB-095",
    "MB-098", "MB-100", "MB-105", "MD-184", "MD-189", "TE-169", "TE-177",
    # Stage 2e. SE-118 is declared on all four origins and means different things on
    # each pair: the HTTP origins have no certificate to judge, and the HTTPS pair is
    # where the item has a subject at all.
    "AR-153", "GEO-004", "GEO-005", "GEO-006", "GEO-007", "GO-143", "GO-144",
    "GO-145", "IN-121", "IN-122", "IN-127", "IN-128", "SE-118", "TE-180",
    "TECH-003",
    # Stage 2f, and the last of the decidable items. These five needed the good tree
    # to be exemplary on every sampled page rather than only on its entry page, so
    # they are declared in the same commit as the repair that makes them true —
    # the shape MS-021 used, where a declaration says what the fixture ought to be
    # and the fixture is moved to match, rather than being written to agree with a
    # tree nobody intended.
    "CN-038", "CN-040", "CN-044", "CN-056", "CN-057",
    # 0.84.0, with the items themselves: the two mobile-layout measures owed since
    # 0.62.0. Both are decided from the hand-written render artifact, which is why
    # they can be declared on the HTTP pair and not on the TLS one — the TLS origins
    # are served without artifacts.
    "MB-107", "MB-108",
}
TLS_DECLARED_IDS = {"AR-150", "CI-014", "SE-115", "SE-117", "SE-118", "SE-120",
                    "TE-175"}
DECLARED_IDS = {
    "good": HTTP_DECLARED_IDS,
    "broken": HTTP_DECLARED_IDS,
    "good_tls": TLS_DECLARED_IDS,
    "broken_tls": TLS_DECLARED_IDS,
}
ALLOWED = {"PASS", "WARN", "FAIL", "N/A", "INDETERMINATE"}
# The primary keyword handed to every origin, for KW-076. It is the site's own
# subject rather than a word picked to produce a verdict: both trees are the same
# bakery, and `bread` is what the good tree's <title> names and what the broken tree's
# own `keywords` meta lists last. One keyword for one audit, so all four origins get
# the same one — that is what an operator does.
#
# The sample it is judged over is measured, not assumed — and since 0.93.2 it is
# recorded in the manifest rather than here. `openspec/specs/declarations/` DEC-5 says
# in as many words that a comment beside the harness does not make the sample part of
# what a declaration stores, so the pages live in `expectations.json` under `sample`
# and `ADeclarationRecordsWhatItWasReasonedFrom` compares them with what the run took.
# The thing to check before reasoning about `stride()` from the good tree's page list
# is still worth saying out loud: the broken tree has no /about.html.
#
# Safe to pass only since 0.48.0. Before it the registry invoked `article_seo.py`
# without `--no-autocomplete`, so supplying a keyword here would have sent it to
# Google Suggest once per sampled page and taken this suite off loopback.
KEYWORD = "bread"
SITE = None
RESULTS: dict[str, dict[str, str]] = {}
# The pages each origin's run actually sampled, filled in by `audit()`. The manifest
# records the same thing, and `openspec/specs/declarations/` DEC-5 is the requirement
# that the two must agree: a declaration written against three pages and compared
# against a different three is being compared against a different site.
SAMPLES: dict[str, list[str]] = {}


def manifest() -> dict:
    with open(MANIFEST, encoding="utf-8") as stream:
        return json.load(stream)


def audit(label: str, url: str) -> dict[str, str]:
    """Run the unmodified checker against one served fixture.

    Every operator-supplied input this tree ships is handed to the run. The access
    log is the newest of them and it is the only evidence here about the past: the
    other three describe the page as it is now, and `server_log_audit.py` reads what
    crawlers actually did. Without it CI-018 was NEEDS_INPUT on both origins and the
    good/broken comparison measured nothing, which is the same hole
    `tests/fixtures/artifacts/README.md` describes for the other three.

    `FixtureSite` stages artifacts for the HTTP pair only, so the TLS origins get no
    flags at all — which is why CI-018 is declared on `good` and `broken` and nowhere
    else.

    `--keyword` is the one operator input that is not a file, and it goes to all four
    origins because it describes the site rather than the run. See `KEYWORD` above for
    the word and for why passing it at all had to wait for 0.48.0.
    """
    out = os.path.join(SITE.dir, f"oracle-{label}.json")
    artifacts = []
    for flag, filename in (("--rendered-json", "rendered.json"),
                           ("--cwv-json", "cwv.json"),
                           ("--links-csv", "top-linking-sites.csv"),
                           ("--server-log", "access.log")):
        path = SITE.artifact(label, filename)
        if path:
            artifacts += [flag, path]
    proc = spawn(
        [sys.executable, os.path.join(SCRIPTS, "checklist_runner.py"), url,
         "--allow-private", "--sample", "3", "--max-rps", "0",
         "--no-history", "--no-prompt", "--quiet", "--timeout", "120",
         "--keyword", KEYWORD, "--json", out, *artifacts],
        env=SITE.environment(label),
        timeout=900)
    if proc.returncode != 0:
        raise AssertionError(
            f"the {label} oracle audit exited {proc.returncode}\n"
            f"{proc.stdout[-3000:]}\n{proc.stderr[-3000:]}")
    with open(out, encoding="utf-8") as stream:
        payload = json.load(stream)
    # Paths, not URLs: the origin's port is ephemeral, and what a declaration was
    # reasoned from is which pages of the tree were read, not where they were served.
    SAMPLES[label] = [urllib.parse.urlparse(u).path or "/"
                      for u in payload.get("sampled_urls") or []]
    rows = payload["items"]
    if isinstance(rows, dict):
        return {item_id: row["status"] for item_id, row in rows.items()}
    return {row["id"]: row["status"] for row in rows}


def comparison() -> tuple[dict[str, dict[str, int]], list[dict[str, str]]]:
    tally = {}
    differences = []
    for label, declarations in manifest()["fixtures"].items():
        counts = {"matched": 0, "disagreed": 0, "indeterminate": 0}
        for item_id, declared in declarations.items():
            expected = declared["expect"]
            if expected == "INDETERMINATE":
                counts["indeterminate"] += 1
                continue
            actual = RESULTS[label][item_id]
            if actual == expected:
                counts["matched"] += 1
            else:
                counts["disagreed"] += 1
                differences.append({
                    "fixture": label,
                    "item": item_id,
                    "expected": expected,
                    "actual": actual,
                    "why": declared["why"],
                })
        tally[label] = counts
    return tally, differences


def coverage() -> tuple[int, int, int]:
    """Unique items, items settled for both site qualities, and opposed items."""
    fixtures = manifest()["fixtures"]
    item_ids = set().union(*(set(row) for row in fixtures.values()))
    settled_both = 0
    opposed = 0
    for item_id in item_ids:
        by_side = {"good": set(), "broken": set()}
        all_settled = set()
        for label, declarations in fixtures.items():
            declared = declarations.get(item_id)
            if not declared or declared["expect"] == "INDETERMINATE":
                continue
            status = declared["expect"]
            all_settled.add(status)
            by_side["good" if label.startswith("good") else "broken"].add(status)
        if all(by_side.values()):
            settled_both += 1
        if len(all_settled) > 1:
            opposed += 1
    return len(item_ids), settled_both, opposed


def setUpModule():
    global SITE
    SITE = FixtureSite().start()
    for label, url in (("good", SITE.good), ("broken", SITE.broken),
                       ("good_tls", SITE.good_tls),
                       ("broken_tls", SITE.broken_tls)):
        RESULTS[label] = audit(label, url)


def tearDownModule():
    try:
        tally, differences = comparison()
        print("\nFixture oracle through stage 3")
        for label in manifest()["fixtures"]:
            counts = tally[label]
            declarations = len(manifest()["fixtures"][label])
            print(f"  {label}: {declarations} declarations — "
                  f"{counts['matched']} matched, "
                  f"{counts['disagreed']} disagreed, "
                  f"{counts['indeterminate']} indeterminate")
        totals = {key: sum(row[key] for row in tally.values())
                  for key in ("matched", "disagreed", "indeterminate")}
        declarations = sum(len(row) for row in manifest()["fixtures"].values())
        print(f"  total: {declarations} declarations — "
              f"{totals['matched']} matched, "
              f"{totals['disagreed']} disagreed, "
              f"{totals['indeterminate']} indeterminate")
        items, settled_both, opposed = coverage()
        print(f"  coverage: {items} items declared, {settled_both} settled on both "
              f"sides, {opposed} opposed across fixture origins")
        print("  differences:")
        if not differences:
            print("    none")
        for row in differences:
            print(f"    {row['fixture']} {row['item']}: expected "
                  f"{row['expected']}, actual {row['actual']} — {row['why']}")
    finally:
        if SITE:
            SITE.stop()


class ADeclarationRecordsWhatItWasReasonedFrom(unittest.TestCase):
    """`openspec/specs/declarations/` DEC-5. A declaration stores its basis, so a basis
    that moves is mechanically identifiable rather than remembered.

    `declared_from` names two sources — the item title and the fixture construction —
    and both move. Before 0.93.2 the manifest kept neither, so a title could be
    rewritten under 250 predictions with every gate green, and the obligation to re-read
    lived in a release ritual: a person remembering, rather than a file objecting.

    The census had this disease and was cured after the 0.89.0 finding: it copies four
    registry fields and its test re-reads all four rather than trusting the stamp. This
    is the same repair on the instrument that had not been bitten yet.

    **What the stamp does and does not claim.** The titles here were written in at
    0.93.2 from the registry as it then stood. That records the basis going forward; it
    is not evidence that each `why` was composed against exactly that wording, and this
    class does not pretend otherwise. What it guarantees is that the *next* move is
    visible.
    """

    def test_every_declaration_stores_the_title_it_was_reasoned_from(self):
        with open(REGISTRY, encoding="utf-8") as stream:
            titles = {item["id"]: item["title"]
                      for item in json.load(stream)["items"]}
        for label, declarations in manifest()["fixtures"].items():
            for item_id, declared in declarations.items():
                with self.subTest(fixture=label, item=item_id):
                    self.assertIn("title", declared,
                                  "a declaration with no recorded basis")
                    self.assertEqual(
                        declared["title"], titles[item_id],
                        f"{item_id} was declared against a title the registry no "
                        f"longer carries. Re-read the `why` against the new one, then "
                        f"update the stored title — not the other way round")

    def test_the_manifest_records_the_pages_each_origin_was_declared_against(self):
        """The second basis. A declaration is made against the pages the run visits,
        which is a sample; recording it in a comment beside the harness does not make
        it part of what the declaration stores, which is what the requirement says in
        as many words."""
        sample = manifest().get("sample")
        self.assertIsInstance(sample, dict, "the manifest records no sample")
        self.assertEqual(set(sample), set(DECLARED_IDS),
                         "an origin has declarations and no recorded sample")
        for label, pages in sample.items():
            with self.subTest(fixture=label):
                self.assertTrue(pages, "an empty sample is not a recorded one")
                self.assertEqual(len(pages), len(set(pages)), "a page recorded twice")
                for page in pages:
                    self.assertTrue(page.startswith("/"),
                                    "record the path, not the URL: the port is "
                                    "ephemeral and the tree is what was read")

    def test_the_recorded_sample_is_the_one_the_run_takes(self):
        """Compared against the run, not against the comment that used to hold it.

        `--sample 3` spreads its picks with `stride()` over whatever the crawl found,
        so adding a page to a fixture tree can move which three are read without
        anybody touching a declaration."""
        recorded = manifest().get("sample") or {}
        self.assertTrue(SAMPLES, "no origin was audited; this compares nothing")
        for label, taken in sorted(SAMPLES.items()):
            with self.subTest(fixture=label):
                self.assertEqual(
                    recorded.get(label), taken,
                    f"the {label} run sampled {taken}; the manifest was declared "
                    f"against {recorded.get(label)}. The declarations for this origin "
                    f"describe a different set of pages — re-read them, then record "
                    f"the pages the run now takes")


class ManifestContract(unittest.TestCase):

    def test_metadata_matches_the_registry(self):
        declared = manifest()
        with open(REGISTRY, encoding="utf-8") as stream:
            registry_version = json.load(stream)["registry_version"]
        self.assertEqual(declared["schema_version"], 1)
        self.assertEqual(declared["registry_version"], registry_version)
        self.assertEqual(
            declared["declared_from"],
            "item title plus fixture construction; never from a run")

    def test_both_fixtures_declare_all_items(self):
        fixtures = manifest()["fixtures"]
        self.assertEqual(set(fixtures), set(DECLARED_IDS))
        for label, declarations in fixtures.items():
            self.assertEqual(set(declarations), DECLARED_IDS[label], label)

    def test_every_declaration_has_a_supported_verdict_and_reason(self):
        for label, declarations in manifest()["fixtures"].items():
            for item_id, declared in declarations.items():
                with self.subTest(fixture=label, item=item_id):
                    self.assertIn(declared["expect"], ALLOWED)
                    self.assertTrue(declared["why"].strip())


class FixtureOracle(unittest.TestCase):

    def test_every_settled_declaration_matches_the_real_runner(self):
        """Every settled declaration agrees after the completed triage."""
        _tally, differences = comparison()
        detail = "\n".join(
            f"{row['fixture']} {row['item']}: expected {row['expected']}, "
            f"actual {row['actual']} — {row['why']}"
            for row in differences)
        self.assertEqual(differences, [], detail)


if __name__ == "__main__":
    unittest.main()
