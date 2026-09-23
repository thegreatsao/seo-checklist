"""RFC 9309 robots.txt matching shared by audits and polite HTTP fetching."""

import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "skills", "seo-checklist", "scripts")
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness  # noqa: E402
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
