"""Counts stated in measurement prose, derived again from the tree."""
from __future__ import annotations

import functools
import json
import os
import re
import sys
import unittest
from collections import Counter
from typing import Callable, NamedTuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "skills", "seo-checklist", "scripts")
TOOLS = os.path.join(ROOT, "skills", "seo-checklist", "tools")
REGISTRY = os.path.join(
    ROOT, "skills", "seo-checklist", "resources", "config", "checklist.json")

sys.path.insert(0, SCRIPTS)
sys.path.insert(0, TOOLS)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import audit_reachability  # noqa: E402
import audit_thresholds  # noqa: E402
import checklist_runner  # noqa: E402
import spec_debt  # noqa: E402
import test_fixture_oracle  # noqa: E402
import verdict_census  # noqa: E402


@functools.lru_cache
def registry() -> dict:
    with open(REGISTRY, encoding="utf-8") as stream:
        return json.load(stream)


def registry_items() -> int:
    return len(registry()["items"])


def registry_plus_one() -> int:
    return registry_items() + 1


def plerdy_items() -> int:
    return sum(bool(item.get("plerdy_ref")) for item in registry()["items"])


def extra_items() -> int:
    return sum(not item.get("plerdy_ref") for item in registry()["items"])


@functools.lru_cache
def by_source() -> Counter:
    return Counter(item["source"] for item in registry()["items"])


def distinct_scripts() -> int:
    return len({item["check"]["script"] for item in registry()["items"]
                if (item.get("check") or {}).get("script")})


def launches() -> int:
    """Ask the runner for its launch set with every input available synthetically."""
    items = registry()["items"]
    keys = {
        arg[1:-1]
        for item in items
        for arg in ((item.get("check") or {}).get("args") or [])
        if isinstance(arg, str) and arg.startswith("{") and arg.endswith("}")
    }
    context = {key: f"<{key}>" for key in keys}
    capabilities = {
        (item.get("check") or {}).get("requires", "fetch")
        for item in items if (item.get("check") or {}).get("script")
    }
    plan, skipped = checklist_runner.build_plan(
        items, context, capabilities, "prose-count", has_gsc=True,
        has_safe_browsing=True)
    if skipped:
        raise AssertionError(f"launch derivation unexpectedly skipped {sorted(skipped)}")
    return len(plan)


@functools.lru_cache
def agent_counts() -> tuple[int, int]:
    folder = os.path.join(ROOT, "skills", "seo-checklist", "resources", "agents")
    names = [name for name in os.listdir(folder)
             if name.startswith("seo-llm-") and name.endswith(".md")]
    return (sum("adversary" not in name for name in names),
            sum("adversary" in name for name in names))


@functools.lru_cache
def known_issue_counts() -> dict:
    with open(os.path.join(ROOT, "tests", "known-issues.json"), encoding="utf-8") as stream:
        record = json.load(stream)
    return {
        "entries": record["entry_count"],
        "probed": record["probed_entry_count"],
        "unprobed": record["unprobed_entry_count"],
    }


def declared_items() -> int:
    return test_fixture_oracle.coverage()[0]


def declarations(origin: str) -> int:
    return len(test_fixture_oracle.manifest()["fixtures"][origin])


@functools.lru_cache
def census_groups() -> tuple[set[str], set[str], set[str]]:
    with open(os.path.join(ROOT, "tests", "census.json"), encoding="utf-8") as stream:
        return verdict_census.verdict_groups(json.load(stream))


@functools.lru_cache
def threshold_counts() -> dict[str, int]:
    named, _unnamed = audit_thresholds.scan()
    counts = Counter(row["kind"] for row in named)
    counts["no basis"] = sum(not row["kind"] for row in named)
    counts["counted"] = sum(counts[kind] for kind in audit_thresholds.VERDICT_KINDS)
    return dict(counts)


@functools.lru_cache
def assertion_counts() -> dict[str, int]:
    items = audit_reachability.script_backed(registry())
    proved = audit_reachability.proofs()
    return {"total": len(items), "proved": len(proved),
            "unclaimed": len(items) - len(proved)}


@functools.lru_cache
def specification_counts() -> dict[str, int]:
    record = spec_debt.record()
    totals = record["totals"]
    return {
        "documents": len(record["documents"]),
        "requirements": totals["requirements"],
        "enforced": totals["enforced"],
        "partial": totals["partial"],
        "none": totals["none"],
        "bounded": totals["bounded"],
    }


class Claim(NamedTuple):
    path: str
    name: str
    pattern: str
    derivation: Callable[[], int]
    matches: int = 1


def source(name: str) -> Callable[[], int]:
    return lambda: by_source()[name]


def known(name: str) -> Callable[[], int]:
    return lambda: known_issue_counts()[name]


def census(index: int) -> Callable[[], int]:
    return lambda: len(census_groups()[index])


def threshold(name: str) -> Callable[[], int]:
    return lambda: threshold_counts()[name]


def assertion(name: str) -> Callable[[], int]:
    return lambda: assertion_counts()[name]


def specification(name: str) -> Callable[[], int]:
    return lambda: specification_counts()[name]


CLAIMS = (
    Claim("README.md", "opening registry size", r"One fixed registry of (?P<n>\d+) checks", registry_items),
    Claim("README.md", "registry contract size", r"the contract: (?P<n>\d+) items", registry_items),
    Claim("README.md", "registry contents size", r"(?P<n>\d+) items: the \[Plerdy", registry_items),
    Claim("README.md", "script source row", r"\| a script, asserted against its real output \| (?P<n>\d+) \|", source("script")),
    Claim("README.md", "llm source row", r"\| a language model reading the page \| (?P<n>\d+) \|", source("llm")),
    Claim("README.md", "manual source row", r"\| a human \| (?P<n>\d+) \|", source("manual")),
    Claim("README.md", "gsc source row", r"\| Search Console[^\n]+\| (?P<n>\d+) \|", source("gsc")),
    Claim("README.md", "launch source items", r"Those (?P<n>\d+) items collapse", source("script")),
    Claim("README.md", "unique launches", r"collapse to \*\*(?P<n>\d+) unique process launches", launches),
    Claim("README.md", "launch scripts", r"unique process launches\*\* over (?P<n>\d+) distinct scripts", distinct_scripts),
    Claim("README.md", "non-script items", r"(?P<n>\d+) items cannot be settled by a script", source("llm")),
    Claim("README.md", "per-item translations", r"(?P<n>\d+) would drift out of", registry_items),
    Claim("README.md", "reachability assertions", r"Of (?P<n>\d+) script-backed assertions", assertion("total")),
    Claim("README.md", "proved unreachable assertions", r"assertions, (?P<n>\d+) are proved", assertion("proved")),
    Claim("README.md", "unclaimed assertions", r"the other (?P<n>\d+) are \*\*not claimed either way", assertion("unclaimed")),
    Claim("README.md", "unopposed model judgements", r"(?P<n>\d+) unopposed judgements", source("llm")),
    Claim("README.md", "tested evidence scripts", r"Every one of the (?P<n>\d+) evidence scripts", distinct_scripts),

    Claim(".claude-plugin/plugin.json", "description registry size", r"fixed (?P<n>\d+)-item registry", registry_items),
    Claim(".claude-plugin/plugin.json", "description Plerdy items", r"Plerdy (?P<n>\d+) \+", plerdy_items),
    Claim(".claude-plugin/plugin.json", "description extra items", r"Plerdy \d+ \+ (?P<n>\d+)", extra_items),
    Claim(".claude-plugin/plugin.json", "description evidence scripts", r"(?P<n>\d+) evidence scripts", distinct_scripts),
    Claim(".claude-plugin/plugin.json", "description judgement agents", r"(?P<n>\d+) judgement agents", lambda: agent_counts()[0]),
    Claim("pyproject.toml", "description registry size", r"fixed (?P<n>\d+)-item registry", registry_items),

    Claim("skills/seo-checklist/SKILL.md", "skill registry size", r"holds \*\*(?P<n>\d+) items\*\*", registry_items),
    Claim("skills/seo-checklist/SKILL.md", "skill extra items", r"plus (?P<n>\d+) checks", extra_items),

    Claim("KNOWN-ISSUES.md", "header probed entries", r"(?P<n>\d+) of the \d+\s+entries carry a probe", known("probed")),
    Claim("KNOWN-ISSUES.md", "header total entries", r"\d+ of the (?P<n>\d+)\s+entries carry a probe", known("entries")),
    Claim("KNOWN-ISSUES.md", "header unprobed entries", r"the other (?P<n>\d+) carry a written reason", known("unprobed")),
    Claim("KNOWN-ISSUES.md", "census registry size", r"records what all (?P<n>\d+) items answered", registry_items),

    Claim("tests/corpus/README.md", "corpus declared items", r"has reached (?P<n>\d+) of \d+ items", declared_items),
    Claim("tests/corpus/README.md", "corpus registry size", r"has reached \d+ of (?P<n>\d+) items", registry_items),
    Claim("tests/corpus/README.md", "broken declarations", r"broken` carries (?P<n>\d+) declarations", lambda: declarations("broken")),
    Claim("tests/verdict_census.py", "census declared items", r"has declared (?P<n>\d+) of \d+ items", declared_items),
    Claim("tests/verdict_census.py", "census doc registry size", r"has declared \d+ of (?P<n>\d+) items", registry_items),
    Claim("tests/verdict_census.py", "census all-at-once size", r"for all (?P<n>\d+) at once", registry_items),

    Claim("ROADMAP.md", "specification documents", r"(?P<n>\d+) documents", specification("documents"), 2),
    Claim("ROADMAP.md", "requirements table", r"\| requirements \| (?P<n>\d+) \|", specification("requirements")),
    Claim("ROADMAP.md", "enforced table", r"\| enforced \| (?P<n>\d+) \|", specification("enforced")),
    Claim("ROADMAP.md", "partial table", r"\| partial \| (?P<n>\d+) \|", specification("partial")),
    Claim("ROADMAP.md", "unread table", r"\| unread \| (?P<n>\d+) \|", specification("none")),
    Claim("ROADMAP.md", "bounded table", r"\| bounded \| (?P<n>\d+) \|", specification("bounded")),
    Claim("ROADMAP.md", "never-fail census row", r"\| answered somewhere, never FAIL \| (?P<n>\d+) \|", census(0)),
    Claim("ROADMAP.md", "never-pass census row", r"\| answered somewhere, never PASS \| (?P<n>\d+) \|", census(1)),
    Claim("ROADMAP.md", "silent census row", r"\| never answered anywhere \| (?P<n>\d+) \|", census(2)),
    Claim("ROADMAP.md", "standard threshold row", r"\| standard \| (?P<n>\d+) \|", threshold("standard")),
    Claim("ROADMAP.md", "measured threshold row", r"\| measured \| (?P<n>\d+) \|", threshold("measured")),
    Claim("ROADMAP.md", "convention threshold row", r"\| convention \| (?P<n>\d+) \|", threshold("convention")),
    Claim("ROADMAP.md", "inherited threshold row", r"\| inherited \| (?P<n>\d+) \|", threshold("inherited")),
    Claim("ROADMAP.md", "no-basis threshold row", r"\| no basis \| (?P<n>\d+) \|", threshold("no basis")),
    Claim("ROADMAP.md", "counted thresholds row", r"numbers a verdict depends on\*\* \| \*\*(?P<n>\d+)\*\*", threshold("counted")),
    Claim("ROADMAP.md", "inherited prose", r"`inherited` at (?P<n>\d+) of \d+", threshold("inherited")),
    Claim("ROADMAP.md", "counted-threshold prose", r"`inherited` at \d+ of (?P<n>\d+)", threshold("counted")),
    Claim("ROADMAP.md", "proved assertion prose", r"proves (?P<n>\d+) of the \d+ script-backed", assertion("proved")),
    Claim("ROADMAP.md", "assertion-total prose", r"proves \d+ of the (?P<n>\d+) script-backed", assertion("total")),
    Claim("ROADMAP.md", "unclaimed assertion prose", r"the other (?P<n>\d+) either way", assertion("unclaimed")),
    Claim("ROADMAP.md", "inherited target", r"`inherited` (?P<n>\d+) → 0", threshold("inherited")),
    Claim("ROADMAP.md", "partial target", r"The (?P<n>\d+) `partial` requirements", specification("partial")),
    Claim("ROADMAP.md", "unclaimed target", r"The (?P<n>\d+) unclaimed assertions", assertion("unclaimed")),
    Claim("ROADMAP.md", "never-fail target", r"The census's (?P<n>\d+) and \d+", census(0)),
    Claim("ROADMAP.md", "silent target", r"The census's \d+ and (?P<n>\d+)", census(2)),
    Claim("ROADMAP.md", "registry-size limit", r"(?P<n>\d+) is already past", registry_items),
    Claim("ROADMAP.md", "next registry item", r"Item (?P<n>\d+) adds", registry_plus_one),
)


class ProseCountsDescribeThisTree(unittest.TestCase):
    maxDiff = None

    def test_every_bound_count_is_present_once_and_equals_its_derivation(self):
        texts = {}
        for claim in CLAIMS:
            if claim.path not in texts:
                with open(os.path.join(ROOT, *claim.path.split("/")), encoding="utf-8") as stream:
                    texts[claim.path] = stream.read()
            found = list(re.finditer(claim.pattern, texts[claim.path], re.MULTILINE))
            self.assertEqual(
                len(found), claim.matches,
                f"{claim.path} [{claim.name}]: expected {claim.matches} regex "
                f"match(es), found {len(found)}")
            expected = claim.derivation()
            for match in found:
                actual = int(match.group("n"))
                self.assertEqual(
                    actual, expected,
                    f"{claim.path} [{claim.name}]: prose says {actual}, tree derives "
                    f"{expected}")

    def test_the_never_pass_sentence_names_exactly_the_census_set(self):
        path = os.path.join(ROOT, "ROADMAP.md")
        with open(path, encoding="utf-8") as stream:
            text = stream.read()
        pattern = (r"The (?P<n>\w+) that were never seen passing are "
                   r"(?P<body>.+?)invalid URL\.")
        found = list(re.finditer(pattern, text, re.DOTALL))
        self.assertEqual(
            len(found), 1,
            f"ROADMAP.md [never-pass ids]: expected 1 regex match, found {len(found)}")
        match = found[0]
        word_values = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4}
        stated = word_values.get(match.group("n"))
        expected_ids = census_groups()[1]
        self.assertEqual(
            stated, len(expected_ids),
            f"ROADMAP.md [never-pass word count]: prose says {match.group('n')!r}, "
            f"tree derives {len(expected_ids)}")
        actual_ids = set(re.findall(r"`([A-Z]+-\d+)`", match.group("body")))
        self.assertEqual(
            actual_ids, expected_ids,
            f"ROADMAP.md [never-pass ids]: prose names {sorted(actual_ids)}, tree "
            f"derives {sorted(expected_ids)}")


if __name__ == "__main__":
    unittest.main()
