"""RFC 9309 robots.txt matching shared by audits and polite HTTP fetching."""

import os
import random
import re
import sys
import time
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "skills", "seo-checklist", "scripts")
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness  # noqa: E402
from harness import allow_loopback, served  # noqa: E402
from registry_verdict import verdict  # noqa: E402
from checklist_runner import FAIL, NO_DATA, PASS, unread_reason  # noqa: E402
import robots_checker  # noqa: E402
import seo_common  # noqa: E402
from lib import robots_rules, safe_http  # noqa: E402


class EvidenceMatcher(unittest.TestCase):
    def allowed(self, text, url, agent="Googlebot"):
        parsed = seo_common.parse_robots_txt(text)
        return seo_common.robots_allowed(parsed, url, agent)

    def test_specific_group_does_not_merge_wildcard_rules(self):
        """A crawler's own group replaces the wildcard fallback."""
        text = ("User-agent: *\nDisallow: /private/\n"
                "User-agent: Googlebot\nDisallow: /tmp/\n")
        self.assertTrue(self.allowed(text, "https://example.com/private/a")[0])

    def test_wildcard_rule_matches_query(self):
        """Rules match the query as well as the URL path."""
        text = "User-agent: *\nDisallow: /*?\n"
        self.assertFalse(self.allowed(text, "https://example.com/p?sort=1")[0])

    def test_literal_rule_matches_query(self):
        """A literal query prefix participates in robots matching."""
        text = "User-agent: *\nDisallow: /search?q=\n"
        self.assertFalse(self.allowed(text, "https://example.com/search?q=a")[0])

    def test_longer_agent_name_does_not_match_by_substring(self):
        """Googlebot does not select a Googlebot-News group."""
        text = "User-agent: Googlebot-News\nDisallow: /\n"
        self.assertTrue(self.allowed(text, "https://example.com/a")[0])

    def test_empty_user_agent_names_no_crawler(self):
        """An empty user-agent token does not select a group."""
        text = "User-agent:\nDisallow: /\n"
        self.assertTrue(self.allowed(text, "https://example.com/a")[0])

    def test_googlebot_variant_falls_back_to_googlebot(self):
        """A Googlebot variant obeys a Googlebot group when no exact group exists."""
        text = ("User-agent: Googlebot\nDisallow: /images/\n"
                "User-agent: *\nAllow: /\n")
        self.assertFalse(
            self.allowed(text, "https://example.com/images/a", "Googlebot-Image")[0]
        )

    def test_googlebot_variant_falls_back_to_wildcard(self):
        """A Googlebot variant obeys wildcard rules when no Googlebot group exists."""
        text = "User-agent: *\nDisallow: /images/\n"
        self.assertFalse(
            self.allowed(text, "https://example.com/images/a", "Googlebot-Image")[0]
        )

    def test_versioned_user_agent_value_names_its_product(self):
        """A version suffix is not part of a file's user-agent product token."""
        text = "User-agent: Googlebot/2.1\nDisallow: /\n"
        self.assertFalse(self.allowed(text, "https://example.com/a")[0])

    def test_user_agent_tokens_are_case_insensitive(self):
        """Product-token group selection is case-insensitive."""
        text = "user-agent: GOOGLEBOT\nDisallow: /\n"
        self.assertFalse(self.allowed(text, "https://example.com/a")[0])

    def test_robots_txt_is_always_allowed(self):
        """The robots.txt path remains fetchable under a blanket disallow."""
        text = "User-agent: *\nDisallow: /\n"
        allowed, reason = self.allowed(text, "https://example.com/robots.txt")
        self.assertTrue(allowed)
        self.assertEqual(reason, "robots.txt is always allowed")

    def test_utf8_path_matches_percent_encoded_rule(self):
        """UTF-8 path characters compare as their percent-encoded octets."""
        text = "User-agent: *\nDisallow: /%E2%82%AC\n"
        self.assertFalse(self.allowed(text, "https://example.com/€")[0])

    def test_unreserved_escape_matches_literal_rule(self):
        """Percent-encoded unreserved characters compare as literals."""
        text = "User-agent: *\nDisallow: /a~b\n"
        self.assertFalse(self.allowed(text, "https://example.com/a%7Eb")[0])

    def test_trailing_dollar_anchors_before_query(self):
        """A trailing dollar anchors the pattern to the path-and-query end."""
        text = "User-agent: *\nDisallow: /*.pdf$\n"
        self.assertFalse(self.allowed(text, "https://example.com/x.pdf")[0])
        self.assertTrue(self.allowed(text, "https://example.com/x.pdf?y=1")[0])

    def test_allow_wins_an_equal_length_tie(self):
        """Equal-length matching rules choose the least restrictive directive."""
        text = "User-agent: *\nDisallow: /p\nAllow: /p\n"
        self.assertTrue(self.allowed(text, "https://example.com/p")[0])

    def test_empty_rules_do_not_match(self):
        """Empty allow and disallow patterns are ignored."""
        text = "User-agent: *\nDisallow:\nAllow:\n"
        self.assertEqual(
            self.allowed(text, "https://example.com/a"),
            (True, "no matching rule"),
        )

    def test_empty_file_differs_from_no_robots_file(self):
        """An empty robots file is distinct from having no robots.txt response."""
        parsed = seo_common.parse_robots_txt("")
        url = "https://example.com/a"
        self.assertEqual(
            seo_common.robots_allowed(parsed, url),
            (True, "no matching rule"),
        )
        self.assertEqual(
            seo_common.robots_allowed(None, url),
            (True, "no robots.txt"),
        )

    def test_two_groups_for_one_agent_combine(self):
        """Rules from every group naming the selected agent are combined."""
        text = ("User-agent: Googlebot\nDisallow: /one\n"
                "User-agent: Googlebot\nDisallow: /two\n")
        self.assertFalse(self.allowed(text, "https://example.com/one")[0])
        self.assertFalse(self.allowed(text, "https://example.com/two")[0])

    def test_selected_group_supplies_crawl_delay(self):
        """Crawl delay comes from the selected group rather than the wildcard."""
        parsed = robots_rules.parse(
            "User-agent: *\nCrawl-delay: 1\nAllow: /\n"
            "User-agent: Googlebot\nCrawl-delay: 7\n"
        )
        selected = robots_rules.group_for(parsed, "Googlebot")
        self.assertEqual(selected["crawl_delay"], 7.0)
        self.assertEqual(selected["matched"], "googlebot")


class PoliteHttpMatcher(unittest.TestCase):
    def setUp(self):
        self.sh = safe_http
        self.pacing = harness.own_rate_limit_dir()
        self.directory = self.pacing.__enter__()
        self.saved_fetch = self.sh._fetch_robots

    def tearDown(self):
        self.pacing.__exit__(None, None, None)
        self.sh._fetch_robots = self.saved_fetch

    def serve(self, body):
        self.sh._fetch_robots = lambda origin: body

    def test_query_wildcard_is_stable_across_python_versions(self):
        """The polite client blocks a query matched by a wildcard rule."""
        self.serve("User-agent: *\nDisallow: /*?\n")
        self.assertFalse(self.sh.robots_allows("https://example.com/p?a=1")[0])

    def test_longer_disallow_beats_shorter_allow(self):
        """The polite client chooses the longest rule regardless of file order."""
        self.serve("User-agent: *\nAllow: /\nDisallow: /private/\n")
        self.assertFalse(
            self.sh.robots_allows("https://example.com/private/a")[0]
        )

    def test_longer_allow_beats_shorter_disallow(self):
        """The polite client permits a more specific allow regardless of file order."""
        self.serve(
            "User-agent: *\nDisallow: /private/\n"
            "Allow: /private/pub.html\n"
        )
        self.assertTrue(
            self.sh.robots_allows("https://example.com/private/pub.html")[0]
        )

    def test_robots_allows_returns_selected_crawl_delay(self):
        """The polite client returns the crawl delay from its selected group."""
        self.serve(
            f"User-agent: {self.sh.ROBOTS_TOKEN}\nCrawl-delay: 4.5\n"
            "Disallow: /no\n"
        )
        self.assertEqual(
            self.sh.robots_allows("https://example.com/yes"), (True, 4.5)
        )


class OneMatcher(unittest.TestCase):
    def test_scripts_do_not_import_the_version_dependent_parser(self):
        """Every script delegates robots matching to the shared matcher."""
        for root, _, files in os.walk(SCRIPTS):
            for name in files:
                if not name.endswith(".py"):
                    continue
                path = os.path.join(root, name)
                with open(path, encoding="utf-8") as source:
                    text = source.read()
                with self.subTest(file=os.path.relpath(path, SCRIPTS)):
                    self.assertNotIn("urllib.robotparser", text, path)
                    self.assertNotIn("RobotFileParser", text, path)


class WildcardMatchingIsLinear(unittest.TestCase):
    """Finding 2 of the 2026-11-04 audit: `_matches` compiled a rule to a regular expression,
    and `Disallow: /*a*a*a*a*a*a*a*b` against a path of sixty `a` backtracked for seconds
    (eight stars, sixteen), holding a crawl of a hostile site to its timeout. The site
    writes the rule, so the matcher must answer in time linear in what it is given."""

    @staticmethod
    def regex_reading(pattern, target):
        """The matcher until 0.177.0, kept as the definition of the answers."""
        anchored = pattern.endswith("$")
        body = pattern[:-1] if anchored else pattern
        expression = re.escape(body).replace(r"\*", ".*") + ("$" if anchored else "")
        return re.match(expression, target) is not None

    def test_a_hostile_wildcard_rule_is_answered_at_once(self):
        parsed = robots_rules.parse("User-agent: *\nDisallow: /" + "*a" * 7 + "*b\n")
        start = time.perf_counter()
        answer = robots_rules.allowed(parsed, "https://example.com/" + "a" * 60, "Googlebot")
        elapsed = time.perf_counter() - start
        self.assertEqual(answer, (True, "no matching rule"))
        self.assertLess(elapsed, 1.0, f"{elapsed:.2f} s for one rule")

    def test_a_long_literal_after_a_star_is_answered_at_once(self):
        """The review of the first fix: a two-pointer match retried the literal after
        each star from every position, 3.3 s for this rule."""
        pattern, target = "/*" + "a" * 8000 + "b", "/" + "a" * 16000
        start = time.perf_counter()
        self.assertFalse(robots_rules._matches(pattern, target))
        self.assertTrue(robots_rules._matches(pattern + "*", target + "b"))
        elapsed = time.perf_counter() - start
        self.assertLess(elapsed, 1.0, f"{elapsed:.2f} s for two matches")

    def test_it_gives_the_regex_reading_on_every_short_case(self):
        rng = random.Random(20261108)
        for _ in range(20_000):
            pattern = "".join(rng.choice("ab*/$") for _ in range(rng.randint(1, 7)))
            target = "/" + "".join(rng.choice("ab/$*") for _ in range(rng.randint(0, 8)))
            with self.subTest(pattern=pattern, target=target):
                self.assertEqual(robots_rules._matches(pattern, target),
                                 self.regex_reading(pattern, target))


class AnUnreadRobotsTxtDecidesNothing(unittest.TestCase):
    """Finding 5 of the 2026-11-04 audit: a robots.txt that answered 5xx or 429, or did not
    answer, was read as one with no rules, so CI-001 and CI-005 passed and GEO-003 failed
    over a file nobody read. It is unread, as a robots.txt the guard refused already was
    (HTTP-13); a 404 is still an answer, and still means no rules."""

    PAGE = ("<!doctype html><html lang=\"en\"><head><title>Page</title></head>"
            "<body><p>Text.</p></body></html>")

    @staticmethod
    def slow():
        time.sleep(2.5)
        return "User-agent: *\nDisallow:\n"

    UNREAD = {"503": (503, {"Content-Type": "text/plain"}, "busy"),
              "500": (500, {"Content-Type": "text/plain"}, "broken"),
              "429": (429, {"Content-Type": "text/plain"}, "slow down"),
              "no answer": (200, {"Content-Type": "text/plain"}, slow)}

    def run_both(self, robots):
        import ai_crawler_policy_matrix
        import indexability_matrix
        routes = {"/": self.PAGE}
        if robots is not None:
            routes["/robots.txt"] = robots
        with allow_loopback(), harness.own_rate_limit_dir(), served(routes) as site:
            return (indexability_matrix.evaluate([site.url], timeout=1),
                    ai_crawler_policy_matrix.matrix(site.url, timeout=1))

    def test_an_unanswered_robots_txt_leaves_ci_001_ci_005_and_geo_003_undecided(self):
        for label, robots in self.UNREAD.items():
            with self.subTest(robots=label):
                index, ai = self.run_both(robots)
                row = index["rows"][0]
                self.assertNotIn("robots_allowed", row, row["robots_rule"])
                self.assertIn("robots.txt", row["robots_rule"])
                self.assertEqual(verdict("CI-001", index), NO_DATA)
                self.assertEqual(verdict("CI-005", index), NO_DATA)
                self.assertTrue(unread_reason(ai), "GEO-003 graded an unread robots.txt")

    def test_an_absent_robots_txt_is_still_an_answer_with_no_rules(self):
        index, ai = self.run_both(None)
        self.assertEqual(verdict("CI-001", index), PASS)
        self.assertEqual(verdict("CI-005", index), PASS)
        self.assertEqual(unread_reason(ai), "")
        self.assertEqual(verdict("GEO-003", ai), FAIL)


class RobotsCheckerParser(unittest.TestCase):
    def result(self):
        return {
            "user_agents": {},
            "sitemaps": [],
            "crawl_delays": {},
            "ai_crawler_status": {},
            "issues": [],
        }

    def test_all_user_agent_lines_receive_the_group_rules(self):
        """Every user-agent line in one group receives that group's rules."""
        result = self.result()
        robots_checker._parse_robots(
            "User-agent: GPTBot\nUser-agent: CCBot\nDisallow: /\n", result
        )
        self.assertEqual(result["user_agents"]["GPTBot"]["disallow"], ["/"])
        self.assertEqual(result["user_agents"]["CCBot"]["disallow"], ["/"])
        self.assertEqual(result["ai_crawler_status"]["GPTBot"], "fully blocked")
        self.assertEqual(result["ai_crawler_status"]["CCBot"], "fully blocked")

    def test_ai_crawler_lookup_uses_product_tokens(self):
        """AI crawler management lookup is case-insensitive by product token."""
        result = self.result()
        robots_checker._parse_robots(
            "user-agent: gptbot\nDisallow: /\n", result
        )
        self.assertEqual(result["ai_crawler_status"]["GPTBot"], "fully blocked")


if __name__ == "__main__":
    unittest.main()
