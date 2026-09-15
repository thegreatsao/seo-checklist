"""The defects a real trilingual site found, pinned so they cannot come back.

Both were reported by auditing the café — 24 pages, three languages, one of the plainest
link structures a site can have. It collected a `high` failure for its best search
result and a `medium` failure for its navigation menu. Neither defect is visible on a
monolingual fixture, which is why neither was caught by 629 tests:

- `BL-081` asked "does this (target, anchor) pair appear on more than half the crawled
  pages" of the whole site, and a translated site has one menu per language. Three
  languages puts every menu entry on at most a third of the pages, so no pair was
  classified as navigation and the header came back as exact-match anchor spam.
- `GO-134` read `opportunities[]` through a severity gate, so "position 4.2, within
  striking distance" was a `high` failure ranked first in the fix list.

The scope test below is the load-bearing one: it fails on any future rule that asks the
sitewide question only once, however that rule is written.

Two more defects came out of fixing those, and are pinned here too because they share the
cause — a field read by one layer and dropped by the next:

- `anchors_from_inventory` projected five fields per page into the rows the classifier
  reads and `lang` was not one of them, so the fix above did nothing on a live site while
  every unit test of it passed.
- `scores_with` marked synonym items so a defect could not score twice, and nothing in
  `checklist_report.py` read it, so the fix list still printed both twins.

Offline. Everything under test is a pure function over a crawl inventory, a sitemap list
or a graded item list, so nothing here needs a fixture site or a network.
"""
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "skills", "seo-checklist", "scripts")
sys.path.insert(0, SCRIPTS)

import anchor_text_audit  # noqa: E402
import checklist_report  # noqa: E402
import gsc_checker  # noqa: E402


def trilingual(sections=("lt", "en", "ru"), per_section=8) -> tuple[dict, list]:
    """A site with one navigation bar per language, and nothing else.

    Menu targets are shared across languages — `/bbq` is linked from the Lithuanian,
    English and Russian menus — but the anchor is the language's own word, so each
    (target, anchor) pair reaches exactly one section. That is the shape the whole
    defect lives in: shared targets, per-language anchors.
    """
    pages, links = {}, []
    menu = ["bbq", "fishing", "menu", "gallery"]
    for lang in sections:
        prefix = "" if lang == sections[0] else f"/{lang}"
        for n in range(per_section):
            url = f"https://example.com{prefix}/page{n}"
            pages[url] = {"status": 200, "html": True, "lang": lang}
            for target in menu:
                links.append({"source": url,
                              "target": f"https://example.com/{target}",
                              "anchor": f"{lang}-{target}"})
    return pages, links


class NavigationIsAskedPerLanguageSection(unittest.TestCase):
    """`anchor_text_audit.navigation_links` — BL-081's classifier."""

    def test_a_per_language_menu_is_navigation(self):
        """The defect itself. 8 of 24 pages is 33%, under any sitewide share, so the
        whole-site question answers "no navigation here" and every menu link is graded
        as an editorial anchor."""
        pages, links = trilingual()
        chrome = anchor_text_audit.navigation_links(links, pages)
        self.assertEqual(len(chrome), 12, "4 menu entries x 3 languages")

    def test_the_menu_does_not_reach_a_sitewide_share_of_the_whole_crawl(self):
        """Pins *why* the fix is needed rather than the fix's own arithmetic. If this
        ever fails, the fixture stopped reproducing the bug and the test above is
        passing for a reason that has nothing to do with language sections."""
        pages, links = trilingual()
        html = [k for k, r in pages.items() if r["status"] == 200]
        reach = max(len({link["source"] for link in links
                         if (link["target"], link["anchor"]) == pair})
                    for pair in {(link["target"], link["anchor"]) for link in links})
        self.assertLess(reach, len(html) * anchor_text_audit.SITEWIDE_PAGE_SHARE)

    def test_a_monolingual_site_is_unchanged(self):
        """One language is one group, and the group is the whole crawl."""
        pages, links = trilingual(sections=("en",), per_section=10)
        self.assertEqual(len(anchor_text_audit.navigation_links(links, pages)), 4)

    def test_a_site_declaring_no_language_is_one_group(self):
        """An inventory written before `lang` existed, or a site with no `<html lang>`.
        Absence must not split every page into its own section."""
        pages, links = trilingual(sections=("en",), per_section=10)
        for row in pages.values():
            row["lang"] = None
        self.assertEqual(len(anchor_text_audit.navigation_links(links, pages)), 4)

    def test_region_subtags_are_one_section(self):
        """`en-GB` and `en-US` are one navigation. Splitting them would put a site that
        writes both back where it started, with each half under the floor."""
        pages, links = trilingual(sections=("en-GB",), per_section=4)
        more_pages, more_links = trilingual(sections=("en-US",), per_section=4)
        pages.update({k.replace("/page", "/us"): v for k, v in more_pages.items()})
        links += [dict(link, source=link["source"].replace("/page", "/us"),
                       anchor=link["anchor"].replace("en-US-", "en-GB-"))
                  for link in more_links]
        self.assertEqual(len(anchor_text_audit.navigation_links(links, pages)), 4)

    def test_stuffing_cannot_hide_in_a_language_section(self):
        """The thing BL-081 exists for. Five identical links from one page are five
        links from one source, and one page is never more than half of a section."""
        pages, links = trilingual()
        source = next(iter(pages))
        for _ in range(5):
            links.append({"source": source, "target": "https://example.com/money",
                          "anchor": "cheap flights"})
        chrome = anchor_text_audit.navigation_links(links, pages)
        self.assertNotIn(("https://example.com/money", "cheap flights"), chrome)

    def test_a_section_below_the_floor_is_not_generalised_from(self):
        """A two-page language stub is not evidence of a menu, for the same reason two
        pages are not evidence of one site-wide."""
        pages, links = trilingual(sections=("lt",), per_section=8)
        stub, stub_links = trilingual(sections=("de",), per_section=2)
        pages.update(stub)
        links += stub_links
        chrome = anchor_text_audit.navigation_links(links, pages)
        self.assertFalse([p for p in chrome if p[1].startswith("de-")])


class TheLanguageReachesTheClassifier(unittest.TestCase):
    """From an inventory to a verdict, through the projection in between.

    Written because the fix above did not work the first time and the tests above all
    passed anyway. `anchors_from_inventory` copies five fields out of each crawled page
    into the rows the classifier sees, and `lang` was not one of them — so the crawl
    recorded it, `navigation_links` read it, and nothing carried it across. Every page
    arrived declaring nothing, the whole site was one group again, and BL-081 still
    reported 21 overused targets on the live site.

    Calling `navigation_links` directly cannot see that, which is the point: a unit test
    of the function I changed passed while the behaviour I changed it for did not. This
    goes through the same door the runner does.
    """

    def inventory(self) -> dict:
        pages, links = trilingual()
        return {"pages": {url: {"status": 200, "html": True, "lang": row["lang"],
                                "final_url": url, "error": None, "depth": 1,
                                "links": [{"internal": True, "target": link["target"],
                                           "anchor": link["anchor"]}
                                          for link in links if link["source"] == url]}
                          for url, row in pages.items()}}

    def test_lang_survives_the_projection(self):
        crawl = anchor_text_audit.anchors_from_inventory(self.inventory())
        self.assertEqual({anchor_text_audit._lang_key(r) for r in crawl["pages"].values()},
                         {"lt", "en", "ru"})

    def test_a_translated_menu_reaches_the_verdict_as_navigation(self):
        """The end of the chain: BL-081's own field, on a site whose links are fine."""
        result = anchor_text_audit.audit_anchor_text(
            "https://example.com/", inventory=self.inventory())
        self.assertEqual(result["summary"]["overused_exact_match_targets"], 0)
        self.assertGreater(result["summary"]["navigation_links"], 0)


class SearchConsoleIssuesAreNotOpportunities(unittest.TestCase):
    """`gsc_checker.detect_issues` — the field GO-134 should have been reading."""

    def test_a_clean_sitemap_report_is_an_empty_list(self):
        clean = [{"path": "https://example.com/sitemap.xml", "errors": "0",
                  "warnings": "0"}]
        self.assertEqual(gsc_checker.detect_issues(clean), [])

    def test_string_counts_are_read_as_numbers(self):
        """The API returns `"0"`, and every count is truthy as a string. This is the
        whole reason the helper is not `s.get("errors", 0) > 0`."""
        self.assertEqual(gsc_checker.detect_issues(
            [{"path": "s.xml", "errors": "0", "warnings": "0"}]), [])
        errors = gsc_checker.detect_issues(
            [{"path": "s.xml", "errors": "3", "warnings": "0"}])
        self.assertEqual([i["severity"] for i in errors], ["high"])

    def test_warnings_are_medium_so_they_warn_rather_than_fail(self):
        found = gsc_checker.detect_issues(
            [{"path": "s.xml", "errors": "0", "warnings": "2"}])
        self.assertEqual([i["severity"] for i in found], ["medium"])

    def test_an_unreadable_sitemap_report_is_none_not_clean(self):
        """`None` keeps the item at NO_DATA. `[]` would pass it on an answer nobody
        got, which is `missing_is: pass` one field along."""
        self.assertIsNone(gsc_checker.detect_issues([{"error": "403 forbidden"}]))
        self.assertIsNone(gsc_checker.detect_issues("not a list"))

    def test_every_issue_carries_a_finding_and_a_fix(self):
        """What the report prints. An issue without either is a line a reader cannot
        act on."""
        for issue in gsc_checker.detect_issues(
                [{"path": "s.xml", "errors": "1", "warnings": "1"}]):
            self.assertTrue(issue["finding"])
            self.assertTrue(issue["fix"])
            self.assertIn(issue["severity"], ("critical", "high", "medium", "low"))
class OnePieceOfWorkIsOneRow(unittest.TestCase):
    """`checklist_report.twins_folded` — the reader's list, not the score.

    `scores_with` arrived in 0.22.0 and only the scorer read it, so a synonym pair
    counted once in the headline and twice in the list a person works from: one image
    missing an `alt` produced CI-016 at priority 6.0 and MD-186 at 3.0, both `high`.
    """

    def items(self, status="FAIL"):
        return [
            {"id": "CI-016", "status": status, "severity": "high", "effort": "low",
             "category_label": "Crawling & Indexing", "title": "Alt text", "fix": "f",
             "evidence": "missing_alt = 1"},
            {"id": "MD-186", "status": status, "severity": "high", "effort": "low",
             "scores_with": "CI-016", "category_label": "Images / Video",
             "title": "Alt text again", "fix": "f", "evidence": "missing_alt = 1"},
            {"id": "CN-040", "status": status, "severity": "medium", "effort": "low",
             "category_label": "Content", "title": "Privacy policy", "fix": "f",
             "evidence": "0 links"},
        ]

    def test_a_synonym_pair_is_one_row(self):
        folded = checklist_report.twins_folded(self.items())
        self.assertEqual([i["id"] for i in folded], ["CI-016", "CN-040"])

    def test_the_survivor_is_the_item_that_carries_the_weight(self):
        """Not "whichever came first". The scoring id is the one the score, the diff and
        the history all name, so it is the one a reader can look up."""
        reversed_order = list(reversed(self.items()))
        folded = checklist_report.twins_folded(reversed_order)
        self.assertIn("CI-016", [i["id"] for i in folded])
        self.assertNotIn("MD-186", [i["id"] for i in folded])

    def test_the_twin_survives_alone_when_the_scoring_item_is_not_listed(self):
        """CI-016 passing and MD-186 failing is a registry defect, not a reason to drop
        the only row describing real work."""
        items = [i for i in self.items() if i["id"] != "CI-016"]
        folded = checklist_report.twins_folded(items)
        self.assertEqual([i["id"] for i in folded], ["MD-186", "CN-040"])

    def test_items_outside_the_fix_statuses_are_untouched(self):
        """The fold is for lists of work. A PASS, a NO_DATA and an N/A keep their rows
        wherever they are printed."""
        folded = checklist_report.twins_folded(self.items(status="PASS"))
        self.assertEqual(len(folded), 3)

    def test_the_fix_export_folds_and_the_full_log_does_not(self):
        data = {"url": "https://example.com/", "items": self.items()}
        rows = checklist_report.fix_rows(data)
        self.assertEqual([r["id"] for r in rows], ["CI-016", "CN-040"])
        self.assertEqual(len(data["items"]), 3, "fix_rows must not mutate the log")


class AnOpportunitySpeaksTheReadersLanguage(unittest.TestCase):
    """`checklist_report.opportunity_phrase`.

    0.23.0 printed `gsc_checker.py`'s English `finding` and `fix` straight into the
    report, so a Russian report carried seven English rows: item titles have a door into
    the language file and a sentence a script composed at run time did not.
    """

    def test_a_known_type_is_rebuilt_from_its_numbers(self):
        found, fix = checklist_report.opportunity_phrase(
            {"type": "striking_distance", "position": 4.2, "impressions": 60,
             "finding": "English from the script", "fix": "English fix"},
            checklist_report.Lang())
        self.assertIn("4.2", found)
        self.assertIn("60", found)
        self.assertNotEqual(found, "English from the script")
        self.assertTrue(fix)

    def test_an_unknown_type_falls_back_to_what_the_script_said(self):
        """Worse than a translation, much better than an empty cell."""
        found, fix = checklist_report.opportunity_phrase(
            {"type": "something_new", "finding": "English from the script",
             "fix": "English fix"}, checklist_report.Lang())
        self.assertEqual(found, "English from the script")
        self.assertEqual(fix, "English fix")

    def test_every_shipped_opportunity_type_has_a_phrase(self):
        """The three `gsc_checker.detect_opportunities` can emit. A type added there
        without one here silently falls back to English."""
        import inspect
        source = inspect.getsource(gsc_checker.detect_opportunities)
        emitted = {line.split('"')[3] for line in source.splitlines()
                   if '"type":' in line}
        self.assertEqual(emitted - set(checklist_report.OPPORTUNITY_PHRASE), set())

    def test_a_translation_with_an_unknown_placeholder_keeps_the_row(self):
        class Broken(checklist_report.Lang):
            def t(self, key, default):
                return "{nonexistent}" if key.startswith("opp_") else default

        found, _ = checklist_report.opportunity_phrase(
            {"type": "striking_distance", "position": 4.2, "impressions": 60,
             "finding": "English from the script"}, Broken())
        self.assertEqual(found, "English from the script")


class AProfileMeasuresItsOwnKindOfSite(unittest.TestCase):
    """`local` moves the thin-content threshold and drops two editorial items.

    Both were reported on the café audit as defects of the site and are properties of the
    checklist: 300 words is the inherited default for a page with something to explain, and
    publication dates and author bylines are editorial-content signals. A service page for a
    physical business says what it does, what it costs and where it is, and then stops.
    """

    def setUp(self):
        sys.path.insert(0, SCRIPTS)
        import checklist_runner
        import duplicate_content
        self.runner = checklist_runner
        self.dupes = duplicate_content
        with open(os.path.join(ROOT, "skills", "seo-checklist", "resources", "config",
                               "profiles.json"), encoding="utf-8") as f:
            self.local = json.load(f)["profiles"]["local"]

    def pages(self):
        """The café's own shape: three near-empty galleries, five normal service pages."""
        sizes = {"/gallery": 83, "/en/gallery": 94, "/ru/gallery": 87,
                 "/menu": 189, "/blueberries": 220, "/petting-zoo": 232,
                 "/bbq": 273, "/fishing": 297}
        return {f"https://example.com{path}": {
                    "word_count": words, "noindex": False, "text_hash": str(words),
                    "signature": None, "title": path, "meta_description": path}
                for path, words in sizes.items()}

    def test_the_default_threshold_calls_every_service_page_thin(self):
        """Why the number had to move: 8 of 8 pages fail, and the finding is useless."""
        report = self.dupes.detect_duplicates(self.pages())
        self.assertEqual(report["summary"]["thin_pages"], 8)
        self.assertEqual(report["summary"]["thin_words_threshold"], 300)

    def test_the_local_threshold_keeps_the_pages_a_person_would_call_thin(self):
        report = self.dupes.detect_duplicates(self.pages(), thin_words=150)
        thin = sorted(p["url"].rsplit("/", 1)[-1] for p in report["thin_content"])
        self.assertEqual(thin, ["gallery", "gallery", "gallery"])
        self.assertEqual(report["summary"]["thin_words_threshold"], 150)

    def test_the_moved_threshold_is_in_the_evidence_trail(self):
        """A verdict reached against a changed number must say the number. Otherwise
        "thin_pages = 3" cannot be argued with by anybody reading the report."""
        report = self.dupes.detect_duplicates(self.pages(), thin_words=150)
        self.assertIn("thin_words_threshold", report["summary"])

    def test_the_local_profile_passes_its_threshold_to_the_script(self):
        self.assertEqual(self.local["script_args"]["duplicate_content.py"],
                         ["--thin-words", "150"])

    def test_profile_args_reach_the_plan_as_argv(self):
        """Not a config a script reads on its own: it lands in argv, so it lands in the
        run log, and two runs of one site with different profiles are two plan keys."""
        items = [{"id": "CN-039", "source": "script", "severity": "high",
                  "check": {"script": "duplicate_content.py", "requires": "crawl",
                            "args": ["{url}"]}}]
        ctx = {"url": "https://example.com/"}
        plan, skipped = self.runner.build_plan(
            items, ctx, {"offline", "fetch", "crawl"}, "live",
            profile_args={"duplicate_content.py": ["--thin-words", "150"]})
        self.assertEqual(skipped, {})
        (script, args), = plan.keys()
        self.assertEqual(script, "duplicate_content.py")
        self.assertEqual(list(args), ["https://example.com/", "--thin-words", "150"])

    def test_opt_in_flags_reach_the_plan_as_argv(self):
        """The other half of RUN-6, and the one that had no reader anywhere.

        Opt-in flags were tested where they are *generated* — `opt_in_flags()` returns
        the right mapping for a mode — and nowhere where they are *used*. A second
        reader over the requirement proposed the breakage that shows it: delete
        `args += (opt_in or {}).get(chk["script"], [])` from `build_plan` and every
        named RUN-6 test stays green.

        The consequence is not cosmetic. `--verify-returns` is what makes the hreflang
        checker fetch the other side of a pair; without it the checker answers a
        narrower question under the same item id, and the recorded invocation — which
        is what a reader consults to find out what was actually asked — shows a run
        nobody performed.
        """
        items = [{"id": "IN-121", "source": "script", "severity": "high",
                  "check": {"script": "hreflang_checker.py", "requires": "fetch",
                            "args": ["{url}"]}}]
        plan, skipped = self.runner.build_plan(
            items, {"url": "https://example.com/"}, {"offline", "fetch", "crawl"},
            "live", opt_in=self.runner.opt_in_flags("live", verify_bots=False))
        self.assertEqual(skipped, {})
        (script, args), = plan.keys()
        self.assertEqual(script, "hreflang_checker.py")
        self.assertEqual(list(args), ["https://example.com/", "--verify-returns"])

    def test_archive_mode_adds_no_opt_in_flag_and_the_plan_shows_it(self):
        """The floor. A `build_plan` appending the flags unconditionally would satisfy
        the test above, and would make an archive run claim it verified returns it never
        fetched — which is why `opt_in_flags` withholds the flag in that mode."""
        items = [{"id": "IN-121", "source": "script", "severity": "high",
                  "check": {"script": "hreflang_checker.py", "requires": "offline",
                            "args": ["{url}"]}}]
        plan, _ = self.runner.build_plan(
            items, {"url": "https://example.com/"}, {"offline"}, "archive",
            opt_in=self.runner.opt_in_flags("archive", verify_bots=False))
        (_script, args), = plan.keys()
        self.assertEqual(list(args), ["https://example.com/"])

    def test_the_two_editorial_items_are_out_of_scope_with_a_reason(self):
        self.assertEqual(self.local["exclude_items"], ["CN-056", "CN-057"])
        for item_id in ("CN-056", "CN-057"):
            reason = self.local["exclude_item_reasons"][item_id]
            self.assertIn("editorial", reason)

    def test_an_excluded_item_carries_the_profiles_words_not_a_shrug(self):
        """`excluded by profile` told a reader nothing, on the surface where narrowing
        scope has to justify itself."""
        items = [{"id": "CN-056", "category": "content", "severity": "medium",
                  "check": {"script": "freshness_checker.py"}}]
        excluded = self.runner.profile_excludes(items, self.local)
        self.assertIn("publication", excluded["CN-056"])
        self.assertNotEqual(excluded["CN-056"], "excluded by profile")


class ALocaleLivesInOnePartOfTheURL(unittest.TestCase):
    """IN-127 *Use a Clear International URL Structure*, which read protocol consistency.

    Through 0.25.0 the item asserted `checks.protocol_consistency.passed` — whether the
    hreflang set mixes http and https. That is a real defect and it is not this item's:
    a site running every locale on `?lang=` passed *Use a Clear International URL
    Structure* as long as it used https for all of them.

    # basis: external standard — Google Search Central, "Managing multi-regional and
    # multilingual sites": ccTLDs, subdomains and subdirectories are the structures it
    # supports, and URL parameters "are not recommended".
    """

    def setUp(self):
        import hreflang_checker
        self.mod = hreflang_checker

    def tags(self, *urls):
        return [{"lang": f"l{n}", "url": u} for n, u in enumerate(urls)]

    def verdict(self, tags):
        """The item's own answer, through the runner's evaluator rather than by
        reading `passed` — the wiring between the script and the rule is half of what
        broke here before."""
        import checklist_runner
        with open(os.path.join(ROOT, "skills", "seo-checklist", "resources", "config",
                               "checklist.json"), encoding="utf-8") as f:
            rule = {i["id"]: i for i in json.load(f)["items"]}["IN-127"]["check"]
        out = {"checks": {"url_structure": self.mod.check_url_structure(tags)}}
        ok, _ = checklist_runner.evaluate(rule["assert"], out)
        return {None: "NO_DATA", True: "PASS", False: "FAIL"}[ok]

    def structures(self):
        return {
            "ccTLD": ("https://example.de/", "https://example.fr/"),
            "subdomain": ("https://de.example.com/", "https://fr.example.com/"),
            "subdirectory": ("https://example.com/de/", "https://example.com/fr/"),
            "parameter": ("https://example.com/?lang=de",
                          "https://example.com/?lang=fr"),
        }

    def langs(self, urls, langs=("de", "fr")):
        return [{"lang": lang, "url": url}
                for lang, url in zip(langs, urls, strict=True)]

    def test_each_supported_structure_is_recognised(self):
        for expected, urls in self.structures().items():
            self.assertEqual(self.mod.url_structure_of(self.langs(urls)), expected,
                             urls)

    def test_the_default_locale_at_the_root_does_not_confuse_the_reading(self):
        """The commonest shape there is: English at `/`, everything else under its
        code. The English URL carries no locale, which is not a defect and must not
        make the set unreadable."""
        tags = [{"lang": "en", "url": "https://example.com/"},
                {"lang": "de", "url": "https://example.com/de/"},
                {"lang": "fr", "url": "https://example.com/fr/"}]
        self.assertEqual(self.mod.url_structure_of(tags), "subdirectory")

    def test_a_matching_cctld_with_locale_folders_is_a_subdirectory_scheme(self):
        tags = [{"lang": "lt", "url": "https://example.lt/"},
                {"lang": "en", "url": "https://example.lt/en/"},
                {"lang": "ru", "url": "https://example.lt/ru/"}]
        self.assertEqual(self.mod.url_structure_of(tags), "subdirectory")
        self.assertEqual(self.verdict(tags), "PASS")

    def test_an_unprefixed_default_locale_inner_page_matches_prefixed_routes(self):
        tags = [{"lang": "lt", "url": "https://example.lt/bbq"},
                {"lang": "en", "url": "https://example.lt/en/bbq/"},
                {"lang": "ru", "url": "https://example.lt/ru/bbq"}]
        self.assertEqual(self.mod.url_structure_of(tags), "subdirectory")
        self.assertEqual(self.verdict(tags), "PASS")

    def test_separate_matching_cctlds_remain_a_cctld_scheme(self):
        tags = [{"lang": "de", "url": "https://example.de/"},
                {"lang": "fr", "url": "https://example.fr/"}]
        self.assertEqual(self.mod.url_structure_of(tags), "ccTLD")
        self.assertEqual(self.verdict(tags), "PASS")

    def test_a_cctld_mixed_with_another_hosts_subdirectory_stays_mixed(self):
        tags = [{"lang": "de", "url": "https://example.de/"},
                {"lang": "fr", "url": "https://example.com/fr/"}]
        result = self.mod.check_url_structure(tags)
        self.assertEqual(result["structure"], "mixed")
        self.assertIs(result["passed"], False)
        for tag in tags:
            self.assertIn(tag["url"], result["finding"])

    def test_two_locales_on_one_matching_cctld_use_their_paths(self):
        tags = [{"lang": "de", "url": "https://example.de/"},
                {"lang": "en", "url": "https://example.de/en/"}]
        self.assertEqual(self.mod.url_structure_of(tags), "subdirectory")
        self.assertEqual(self.verdict(tags), "PASS")

    def test_a_region_spelled_differently_from_its_domain_is_not_guessed_at(self):
        """`en-GB` on `.uk`, `ja` on `.jp`: the code and the domain do not match as
        strings, and no table here maps one to the other. Alone, that set reads as
        unmarked and the item declines to answer — which is the limit stated rather
        than a structure invented. One readable alternate is enough to decide.
        """
        alone = [{"lang": "en-GB", "url": "https://example.uk/"},
                 {"lang": "ja", "url": "https://example.jp/"}]
        self.assertEqual(self.mod.url_structure_of(alone), "unmarked")
        self.assertEqual(self.verdict(alone), "NO_DATA")
        with_one_readable = alone + [{"lang": "fr", "url": "https://example.fr/"}]
        self.assertEqual(self.mod.url_structure_of(with_one_readable), "ccTLD")

    def test_an_unreadable_host_mixed_with_a_subdirectory_fails(self):
        tags = [{"lang": "en-GB", "url": "https://example.uk/"},
                {"lang": "fr", "url": "https://example.com/fr/"}]
        result = self.mod.check_url_structure(tags)
        self.assertEqual(result["structure"], "mixed")
        self.assertIs(result["passed"], False)
        self.assertIn("https://example.uk/", result["finding"])
        self.assertEqual(self.verdict(tags), "FAIL")

    def test_an_unreadable_nonroot_path_mixed_with_a_subdirectory_fails(self):
        tags = [{"lang": "en", "url": "https://example.com/about"},
                {"lang": "fr", "url": "https://example.com/fr/"}]
        result = self.mod.check_url_structure(tags)
        self.assertEqual(result["structure"], "mixed")
        self.assertIs(result["passed"], False)
        self.assertIn("https://example.com/about", result["finding"])
        self.assertEqual(self.verdict(tags), "FAIL")

    def test_an_unreadable_path_under_another_locale_prefix_stays_mixed(self):
        tags = [{"lang": "lt", "url": "https://example.com/en/bbq"},
                {"lang": "en", "url": "https://example.com/en/other"},
                {"lang": "ru", "url": "https://example.com/ru/bbq"}]
        result = self.mod.check_url_structure(tags)
        self.assertEqual(result["structure"], "mixed")
        self.assertIs(result["passed"], False)
        self.assertIn("https://example.com/en/bbq", result["finding"])
        self.assertEqual(self.verdict(tags), "FAIL")

    def test_x_default_names_no_locale_and_is_not_counted(self):
        tags = [{"lang": "x-default", "url": "https://example.com/"},
                {"lang": "de", "url": "https://example.com/de/"}]
        self.assertEqual(self.mod.url_structure_of(tags), "single")

    def test_the_three_google_supports_pass(self):
        for name in ("ccTLD", "subdomain", "subdirectory"):
            self.assertEqual(self.verdict(self.langs(self.structures()[name])),
                             "PASS", name)

    def test_a_parameter_fails(self):
        self.assertEqual(self.verdict(self.langs(self.structures()["parameter"])),
                         "FAIL")

    def test_a_mixture_fails_where_comparing_components_called_it_a_subdomain(self):
        """German in the path, French on a subdomain. Both alternates differ from each
        other in the host, so a reading based on *which component varies* answers
        "subdomain" and passes the item. Reading each tag against its own locale gives
        two places and one verdict: mixed."""
        tags = [{"lang": "de", "url": "https://example.com/de/"},
                {"lang": "fr", "url": "https://fr.example.com/"}]
        self.assertEqual(self.mod.url_structure_of(tags), "mixed")
        self.assertEqual(self.verdict(tags), "FAIL")

    def test_one_alternate_decides_nothing(self):
        """No `passed` key at all, so the item is NO_DATA. A site with one alternate
        has no structure, and crediting it with one is the failure this item is being
        repaired for."""
        one = [{"lang": "de", "url": "https://example.com/de/"}]
        single = self.mod.check_url_structure(one)
        self.assertNotIn("passed", single)
        self.assertEqual(single["structure"], "single")
        self.assertEqual(self.verdict(one), "NO_DATA")

    def test_mixed_protocols_no_longer_decide_this_item(self):
        """The old assertion, kept as a test so the repair cannot quietly undo itself.
        These two differ in protocol and share a structure; the item is about the
        structure, and the protocol defect belongs to a check of its own."""
        tags = [{"lang": "de", "url": "http://example.com/de/"},
                {"lang": "fr", "url": "https://example.com/fr/"}]
        self.assertIs(self.mod.check_protocol_consistency(tags)["passed"], False)
        self.assertEqual(self.verdict(tags), "PASS")


if __name__ == "__main__":
    unittest.main()
