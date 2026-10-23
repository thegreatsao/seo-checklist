"""The census's validator and Safe Browsing stand-ins, and why a real audit never meets them (F05-4).

Offline the loopback-only switch keeps validator.w3.org and Safe Browsing from being asked,
so CI-017, TE-181, SE-114, SE-116 and TE-171 answered NO_DATA or NEEDS_INPUT on every tree
the census serves, and nothing showed any of them able to FAIL. `flagged/` answers both
services' own paths with a recorded answer that fails each item, `cleared/` with one that
passes it, and the two scripts ask them, instead of the real services, only when
`SEO_VALIDATOR_STANDIN` / `SEO_SAFE_BROWSING_STANDIN` name one in a loopback-only process:
the suite and CI are, no real audit is. These tests hold the switch, the guard under it,
that no key reaches a stand-in, and that each recorded answer is the provider's shape.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "seo-checklist", "scripts"))
import harness  # noqa: E402
import domain_safety_check as dsc  # noqa: E402
import html_validator  # noqa: E402
from checklist_runner import evaluate  # noqa: E402

CORPUS = os.path.join(ROOT, "tests", "corpus")
INPUTS = os.path.join(CORPUS, "_inputs")
# Each stand-in tree, and whether its answers pass the five items.
TREES = {"flagged": False, "cleared": True}
NU_ROUTE = "/nu/"
SB_ROUTE = "/v4/threatMatches:find"

# The Nu HTML Checker's JSON output (github.com/validator/validator/wiki/Output-»-JSON,
# read 23 October 2026): the root object's keys and a message's, and the three types.
NU_ROOT = {"messages", "url", "source", "language"}
NU_MESSAGE = {"type", "subType", "message", "extract", "offset", "url", "firstLine",
              "firstColumn", "lastLine", "lastColumn", "hiliteStart", "hiliteLength"}
NU_TYPES = {"info", "error", "non-document-error"}
# Safe Browsing Lookup API v4, `threatMatches:find`
# (developers.google.com/safe-browsing/v4/lookup-api, read 23 October 2026): a match's
# keys and the four threat types this script asks about; no match is `{}`.
SB_ROOT = {"matches"}
SB_MATCH = {"threatType", "platformType", "threatEntryType", "threat",
            "threatEntryMetadata", "cacheDuration"}


def recorded(tree: str, route: str) -> dict:
    with open(os.path.join(CORPUS, tree, "_answers.json"), encoding="utf-8") as stream:
        return json.loads(json.load(stream)[route]["body"])


def items_of(*, script: str = "", requires: str = "") -> list[dict]:
    return [item for item in harness.registry()["items"]
            if (check := item.get("check") or {})
            and (not script or check.get("script") == script)
            and (not requires or check.get("requires") == requires)]


class _Asked(Exception):
    pass


class TheValidatorStandInIsReadOnlyOffline(unittest.TestCase):
    """`SEO_LOOPBACK_ONLY` is the switch: without it the variable is ignored and
    validator.w3.org is asked as before (here, its call is caught before it leaves)."""

    STANDIN = "http://127.0.0.1:9" + NU_ROUTE

    def asked(self, env: dict) -> str:
        urls = []

        def fake(url, **_kwargs):
            urls.append(url)
            raise _Asked

        with mock.patch.dict(os.environ, env), \
                mock.patch.object(html_validator, "safe_get", side_effect=fake), \
                mock.patch.object(html_validator.requests, "get", side_effect=fake), \
                self.assertRaises(_Asked):
            html_validator.validate("http://127.0.0.1:9/")
        return urls[0]

    def test_a_loopback_only_process_asks_the_stand_in(self):
        asked = self.asked({"SEO_LOOPBACK_ONLY": "1", "SEO_VALIDATOR_STANDIN": self.STANDIN})
        self.assertTrue(asked.startswith(self.STANDIN + "?"), asked)

    def test_any_other_process_asks_the_w3c_whatever_its_environment_says(self):
        asked = self.asked({"SEO_LOOPBACK_ONLY": "", "SEO_VALIDATOR_STANDIN": self.STANDIN})
        self.assertTrue(asked.startswith(html_validator.NU_ENDPOINT + "?"), asked)

    def test_without_a_stand_in_a_loopback_only_process_asks_nobody(self):
        with mock.patch.dict(os.environ, {"SEO_LOOPBACK_ONLY": "1",
                                          "SEO_VALIDATOR_STANDIN": ""}):
            out = html_validator.validate("http://127.0.0.1:9/")
        self.assertEqual(out["error_kind"], "blocked")
        self.assertNotIn("errors", out["summary"])

    def test_a_stand_in_that_is_not_this_machine_is_refused_not_asked(self):
        with mock.patch.dict(os.environ, {"SEO_LOOPBACK_ONLY": "1",
                                          "SEO_VALIDATOR_STANDIN":
                                              "https://nu.example.test" + NU_ROUTE}):
            out = html_validator.validate("http://127.0.0.1:9/")
        self.assertEqual(out["error_kind"], "blocked")
        self.assertIn("loopback-only", out["error"])
        self.assertIn("nu.example.test", out["error"])
        self.assertNotIn("errors", out["summary"])


class TheSafeBrowsingStandInIsReadOnlyOffline(unittest.TestCase):
    """The same switch; and a key, when one is set, never goes to the stand-in."""

    STANDIN = "http://127.0.0.1:9" + SB_ROUTE
    KEY = "AIza-not-a-real-key"

    def asked(self, env: dict) -> tuple[str, dict]:
        calls = []

        def fake(url, **kwargs):
            calls.append((url, kwargs))
            raise _Asked

        with mock.patch.dict(os.environ, env), \
                mock.patch.object(dsc, "safe_post", side_effect=fake), \
                mock.patch.object(dsc.requests, "post", side_effect=fake), \
                self.assertRaises(_Asked):
            dsc.check_safe_browsing("http://127.0.0.1:9/", self.KEY, 5)
        return calls[0]

    def test_a_loopback_only_process_asks_the_stand_in_without_the_key(self):
        url, kwargs = self.asked({"SEO_LOOPBACK_ONLY": "1",
                                  "SEO_SAFE_BROWSING_STANDIN": self.STANDIN})
        self.assertEqual(url, self.STANDIN)
        # Every argument, not only the body and headers: `params` or `auth` would put
        # the key on the stand-in's request as surely as the URL would (review of F05-4).
        self.assertNotIn(self.KEY, json.dumps([url, kwargs], default=str))

    def test_any_other_process_asks_google_whatever_its_environment_says(self):
        url, _ = self.asked({"SEO_LOOPBACK_ONLY": "",
                             "SEO_SAFE_BROWSING_STANDIN": self.STANDIN})
        self.assertEqual(url, f"{dsc.SB_ENDPOINT}?key={self.KEY}")

    def test_the_stand_in_needs_no_key(self):
        with mock.patch.dict(os.environ, {"SEO_LOOPBACK_ONLY": "1",
                                          "SEO_SAFE_BROWSING_STANDIN": self.STANDIN}), \
                mock.patch.object(dsc, "safe_post", side_effect=_Asked), \
                self.assertRaises(_Asked):
            dsc.check_safe_browsing("http://127.0.0.1:9/", "", 5)

    def test_a_stand_in_that_is_not_this_machine_is_refused_not_asked(self):
        with mock.patch.dict(os.environ, {"SEO_LOOPBACK_ONLY": "1",
                                          "SEO_SAFE_BROWSING_STANDIN":
                                              "https://sb.example.test" + SB_ROUTE}):
            out = dsc.check_safe_browsing("http://127.0.0.1:9/", self.KEY, 5)
        self.assertIs(out["checked"], False)
        self.assertNotIn("threats", out)
        self.assertIn("loopback-only", out["error"])
        self.assertIn("sb.example.test", out["error"])
        self.assertNotIn(self.KEY, out["error"])

    def test_a_private_host_is_named_only_to_the_stand_in(self):
        """`check`'s private branch keeps whois and the resolver away from a host only
        this machine reaches, and asks Safe Browsing only when the stand-in plays it."""
        seen = []

        def fake(url, **kwargs):
            seen.append(url)
            raise _Asked

        for standin, asked in ((self.STANDIN, [self.STANDIN]), ("", [])):
            seen.clear()
            with self.subTest(standin=standin), \
                    mock.patch.dict(os.environ, {"SEO_LOOPBACK_ONLY": "1",
                                                 "SEO_SAFE_BROWSING_STANDIN": standin}), \
                    mock.patch.object(dsc, "safe_post", side_effect=fake), \
                    mock.patch.object(dsc, "check_uptime", return_value={
                        "checked": True, "reachable": True, "status": 200,
                        "response_ms": 1, "error": None}), \
                    mock.patch.object(dsc, "check_whois") as whois, \
                    mock.patch.object(dsc, "check_neighbors") as neighbors:
                try:
                    dsc.check("http://127.0.0.1:9/")
                except _Asked:
                    pass
                self.assertEqual(seen, asked)
                whois.assert_not_called()
                neighbors.assert_not_called()


class TheRecordedAnswersAreTheProviders(unittest.TestCase):
    """Every key each recorded answer carries is one its provider defines, spelled as
    the provider spells it, so a verdict on either tree is the parser's on a real shape."""

    def test_the_validator_answer_carries_only_nu_s_keys(self):
        for tree in TREES:
            with self.subTest(tree=tree):
                data = recorded(tree, NU_ROUTE)
                self.assertLessEqual(set(data), NU_ROOT)
                for message in data["messages"]:
                    self.assertLessEqual(set(message), NU_MESSAGE)
                    self.assertIn(message["type"], NU_TYPES)

    def test_the_safe_browsing_answer_carries_only_the_v4_keys(self):
        for tree in TREES:
            with self.subTest(tree=tree):
                data = recorded(tree, SB_ROUTE)
                self.assertLessEqual(set(data), SB_ROOT)
                for match in data.get("matches", []):
                    self.assertLessEqual(set(match), SB_MATCH)
                    self.assertIn(match["threatType"], dsc.SB_THREAT_TYPES)
                    self.assertEqual(set(match["threat"]), {"url"})

    def test_the_five_items_are_the_ones_these_stand_ins_answer(self):
        self.assertEqual(sorted(i["id"] for i in items_of(script="html_validator.py")),
                         ["CI-017", "TE-181"])
        self.assertEqual(sorted(i["id"] for i in items_of(requires="safe_browsing")),
                         ["SE-114", "SE-116", "TE-171"])


class TheTreesServeThem(unittest.TestCase):
    """End to end in-process: each tree served on loopback, both scripts pointed at it,
    each of the five items read through the registry's own assertion — CI-017 by the
    served-mode GET, TE-181 by the rendered-mode POST, the three by Safe Browsing's POST."""

    def outputs(self, tree: str) -> dict[str, dict]:
        with tempfile.TemporaryDirectory() as workdir, harness.allow_loopback():
            site = harness._Site(os.path.join(CORPUS, tree), os.path.join(workdir, tree))
            try:
                with mock.patch.dict(os.environ, {
                        "SEO_VALIDATOR_STANDIN": site.base + NU_ROUTE,
                        "SEO_SAFE_BROWSING_STANDIN": site.base + SB_ROUTE}), \
                        mock.patch.object(html_validator, "safe_get",
                                          wraps=html_validator.safe_get) as get, \
                        mock.patch.object(html_validator, "safe_post",
                                          wraps=html_validator.safe_post) as post:
                    page = site.base + "/"
                    rendered = os.path.join(INPUTS, tree, "rendered.json")
                    out = {"served": html_validator.validate(page),
                           "rendered": html_validator.validate(page, rendered_json=rendered),
                           "safety": dsc.check(page)}
            finally:
                site.stop()
        # The table answers GET and POST alike, so the method and the body are held
        # here (review of F05-4): served mode names the page, rendered mode sends it.
        self.assertEqual(get.call_count, 1)
        self.assertIn("doc=", get.call_args.args[0])
        self.assertEqual(post.call_count, 1)
        with open(rendered, encoding="utf-8") as stream:
            self.assertEqual(post.call_args.kwargs["data"],
                             json.load(stream)["html"].encode("utf-8"))
        return out

    def test_each_item_fails_on_flagged_and_passes_on_cleared(self):
        reads = {"CI-017": "served", "TE-181": "rendered",
                 "SE-114": "safety", "SE-116": "safety", "TE-171": "safety"}
        items = {item["id"]: item for item in harness.registry()["items"]}
        for tree, passes in TREES.items():
            out = self.outputs(tree)
            for part in ("served", "rendered"):
                self.assertIsNone(out[part]["error"], (tree, part))
            self.assertIs(out["safety"]["safe_browsing"]["checked"], True, tree)
            for item_id, part in reads.items():
                with self.subTest(tree=tree, item=item_id):
                    self.assertIs(evaluate(items[item_id]["check"]["assert"], out[part])[0],
                                  passes)


if __name__ == "__main__":
    unittest.main()
