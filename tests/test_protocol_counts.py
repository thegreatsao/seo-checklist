"""Counts stated in prose, checked against the registry that decides them.

`openspec/specs/operator-protocol/` OPR-8. The protocol is what an agent reads before
running anything, so a wrong count there sets a wrong expectation for the whole run: an
operator told to expect 33 model verdicts and handed 38 will assume something went
wrong, or — worse — will not notice.

Fourteen numbers were wrong when this module was written, across six files, and every
one of them had been wrong for long enough that nobody could say which release broke it.
They were not typos. Each was correct once and stayed behind while the registry moved,
which is the failure this module exists to make impossible: a count that no test derives
is a count that is wrong within a release and says nothing. Five of the fourteen were
known — `openspec/specs/operator-protocol/` A.1 lists them — and nine were found by
writing the derivation, including the whole lens table and three of the four agent
descriptions a host matches a task against.

**What this holds and what it does not.** Every claim below names a file, a pattern that
must match exactly once, and a derivation from `checklist.json`. Two of the sweeps are
mechanisms rather than lists — the lens table and the lens agent files are generated from
the set of lenses the registry actually carries, so a new lens fails here until its row
and its agent file exist. The rest is a ledger, and a ledger cannot notice a count
somebody adds in a sentence nobody entered into it. That gap is
`openspec/specs/governance/` GOV-3's, stated in general and unsolved; what is closed here
is that no *known* count can drift, and that a new source or a new lens cannot appear
without forcing an entry.
"""
from __future__ import annotations

import collections
import json
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL_DIR = os.path.join(ROOT, "skills", "seo-checklist")
REGISTRY = os.path.join(SKILL_DIR, "resources", "config", "checklist.json")

UNITS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
         "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
         "seventeen", "eighteen", "nineteen"]
TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
        "seventy": 70, "eighty": 80, "ninety": 90}


def to_int(text: str) -> int:
    """`38`, `thirty-eight` and `Thirty-eight` are one number written three ways.

    Prose picks the form that reads well and the registry has no opinion about it, so
    the comparison happens on the value. A form this cannot parse raises rather than
    returning a default: a claim that silently became unparseable would pass.
    """
    stripped = text.strip().lower()
    if stripped.isdigit():
        return int(stripped)
    if stripped in UNITS:
        return UNITS.index(stripped)
    if stripped in TENS:
        return TENS[stripped]
    if "-" in stripped:
        tens, _, unit = stripped.partition("-")
        if tens in TENS and unit in UNITS[1:10]:
            return TENS[tens] + UNITS.index(unit)
    raise ValueError(f"{text!r} is not a number this module can read")


def registry() -> dict:
    with open(REGISTRY, encoding="utf-8") as stream:
        return json.load(stream)


DATA = registry()
ITEMS = DATA["items"]
BY_SOURCE = collections.Counter(item["source"] for item in ITEMS)
BY_LENS = collections.Counter(item["lens"] for item in ITEMS
                              if item["source"] == "llm" and item.get("lens"))
TWINS = [item for item in ITEMS if item.get("scores_with")]
CARRIERS = {item["scores_with"] for item in TWINS}


def population() -> dict:
    """Every number in the ledger, derived here and nowhere else.

    Named rather than inlined so that a claim cites a population instead of restating
    an arithmetic: `"llm"` is the queue's size wherever the queue's size is stated, and
    one edit here moves every claim that reads it.
    """
    return {
        "items": len(ITEMS),
        "categories": len({item["category"] for item in ITEMS}),
        # The Plerdy split. Four files stated it in three different values before
        # 0.93.1 — 200+17, 200+14 and 200+15 — and the wrong one was inside
        # `checklist.json`'s own `source` field, where `openspec/specs/registry/`
        # REG-12 now forbids a literal outright.
        "borrowed": sum(1 for item in ITEMS if item.get("plerdy_ref") is not None),
        "added": sum(1 for item in ITEMS if item.get("plerdy_ref") is None),
        "llm": BY_SOURCE["llm"],
        "manual": BY_SOURCE["manual"],
        "twins": len(TWINS),
        "carriers": len(CARRIERS),
        **{f"lens:{lens}": count for lens, count in BY_LENS.items()},
    }


def agents(name: str) -> str:
    return os.path.join(SKILL_DIR, "resources", "agents", name)


# (path, pattern with exactly one group, population key, what the sentence is for).
# The pattern is the anchor: it must match exactly once, so a sentence that is reworded
# or deleted fails loudly rather than leaving the claim unchecked.
LEDGER = [
    (os.path.join(SKILL_DIR, "SKILL.md"),
     r"holds \*\*(\d+) items\*\*", "items",
     "the size of the registry, in the paragraph that introduces it"),
    (os.path.join(SKILL_DIR, "SKILL.md"),
     r"the Plerdy (\d+)-point\n?checklist", "borrowed",
     "the borrowed half of the registry, where it is introduced"),
    (os.path.join(SKILL_DIR, "SKILL.md"),
     r"checklist plus (\d+) checks it does not cover", "added",
     "the half this plugin adds, in the same sentence"),
    (os.path.join(SKILL_DIR, "resources", "config", "plerdy-titles.json"),
     r"The (\d+) items added by this plugin", "added",
     "the titles file's own note about what it does not hold"),
    (os.path.join(ROOT, "CREDITS.md"),
     r"The (\d+) additional items", "added",
     "the attribution, which is the sentence saying whose work the rest is"),
    (os.path.join(ROOT, "README.md"),
     r"\[Plerdy (\d+)-point checklist\]", "borrowed",
     "the borrowed half, in the README's account of the contract"),
    (os.path.join(ROOT, "README.md"),
     r"plus (\d+)\nchecks it does not cover", "added",
     "the added half, in the same sentence"),
    (os.path.join(SKILL_DIR, "SKILL.md"),
     r"The LLM queue produces (\d+) verdicts", "llm",
     "what the operator is told to expect back from the model"),
    (os.path.join(SKILL_DIR, "SKILL.md"),
     r"# the model's (\d+), after the lens agents", "llm",
     "the same number, in the comment above the command that merges them"),
    (os.path.join(SKILL_DIR, "SKILL.md"),
     r"# the (\d+) a person has to look at", "manual",
     "the size of the by-hand queue, above the command that merges it"),
    (os.path.join(SKILL_DIR, "SKILL.md"),
     r"refused with its id: ([a-z]+(?:-[a-z]+)?) ticks would move", "manual",
     "the same number, arguing why a tick needs a reason"),
    (os.path.join(SKILL_DIR, "SKILL.md"),
     r"deliberate: (\d+) category agents would", "categories",
     "why the queue splits by lens and not by category"),
    (os.path.join(SKILL_DIR, "scripts", "checklist_report.py"),
     r"([A-Za-z]+(?:-[a-z]+)?) items rest on one language model's reading", "llm",
     "the sentence explaining why a second reading exists"),
    (os.path.join(SKILL_DIR, "scripts", "checklist_runner.py"),
     r"([A-Za-z]+) duplicate groups in this", "carriers",
     "how many checks are asked twice, in the scorer that folds them"),
    (os.path.join(SKILL_DIR, "scripts", "checklist_runner.py"),
     r"carry ([a-z]+) `scores_with` twins", "twins",
     "how many items defer their weight, in the same comment"),
    (agents("seo-llm-adversary.md"),
     r"([A-Za-z]+(?:-[a-z]+)?) items in this audit rest on", "llm",
     "what the second reader is told it is reviewing"),
    (agents("seo-llm-market.md"),
     r"^([A-Za-z]+) items, each cheap to answer badly", "lens:market",
     "the market lens describing its own workload"),
]


def read(path: str) -> str:
    with open(path, encoding="utf-8") as stream:
        return stream.read()


class TheProtocolsCountsComeFromTheRegistry(unittest.TestCase):

    def test_the_ledger_still_points_at_sentences_that_exist(self):
        """Run before the values are compared, because a pattern that matches nothing
        makes every assertion about it vacuously true. This is the half that catches a
        rewording; the next one catches a drift."""
        for path, pattern, key, why in LEDGER:
            with self.subTest(file=os.path.basename(path), claim=why):
                found = re.findall(pattern, read(path), re.M)
                self.assertEqual(
                    len(found), 1,
                    f"{pattern!r} matched {len(found)} times in "
                    f"{os.path.relpath(path, ROOT)}; the ledger entry for {key!r} no "
                    f"longer names a sentence in that file")

    def test_every_stated_count_is_the_one_the_registry_holds(self):
        """The claim itself. Fourteen numbers in six files were wrong on 6 September
        2026, the largest by eight."""
        counts = population()
        for path, pattern, key, why in LEDGER:
            with self.subTest(file=os.path.basename(path), claim=why):
                found = re.search(pattern, read(path), re.M)
                self.assertIsNotNone(found)
                self.assertEqual(
                    to_int(found.group(1)), counts[key],
                    f"{os.path.relpath(path, ROOT)} states {found.group(1)!r} where the "
                    f"registry holds {counts[key]} — {why}")

    def test_the_queue_table_names_every_lens_and_states_its_size(self):
        """A sweep over the lenses the registry carries, not over a list written here.

        The protocol's table is what an operator reads to decide how many agents to run
        and what each one is for. A lens with no row is work nobody is dispatched to do,
        and the check that would have caught it cannot be a list of four names."""
        text = read(os.path.join(SKILL_DIR, "SKILL.md"))
        self.assertTrue(BY_LENS, "no lens carries an item; the registry shape moved")
        for lens, size in sorted(BY_LENS.items()):
            with self.subTest(lens=lens):
                row = re.search(r"\| `LLM-QUEUE-%s\.md` \|[^|]+\| (\d+) —" % lens, text)
                self.assertIsNotNone(row, f"no queue-table row for the {lens!r} lens")
                self.assertEqual(int(row.group(1)), size)
        rows = re.findall(r"\| `LLM-QUEUE-([a-z]+)\.md` \|", text)
        self.assertEqual(sorted(rows), sorted(BY_LENS),
                         "the table names a lens the registry does not carry")

    def test_every_lens_has_an_agent_that_states_its_own_size(self):
        """The same sweep over the agent files. An agent's `description:` is what a host
        matches against a task, so the number in it is read before the file is."""
        for lens, size in sorted(BY_LENS.items()):
            with self.subTest(lens=lens):
                path = agents(f"seo-llm-{lens}.md")
                self.assertTrue(os.path.exists(path),
                                f"the {lens!r} lens has items and no agent file")
                stated = re.search(r"^description: Judges the (\d+) checklist items",
                                   read(path), re.M)
                self.assertIsNotNone(
                    stated, f"{os.path.basename(path)} does not state how many items "
                            f"the {lens!r} lens holds")
                self.assertEqual(int(stated.group(1)), size)

    def test_the_populations_are_the_registrys_own_and_they_sum(self):
        """A derivation nobody checks is a second place for the same error.

        `source` partitions the registry, so the four counts add to the item count; if a
        fifth source appears, this fails and the ledger above has to say whether the
        protocol states its size."""
        counts = population()
        self.assertEqual(sum(BY_SOURCE.values()), counts["items"])
        self.assertEqual(sorted(BY_SOURCE), ["gsc", "llm", "manual", "script"])
        self.assertEqual(sum(BY_LENS.values()), counts["llm"],
                         "an llm item carries no lens, so the lens rows no longer "
                         "account for the queue the protocol promises")

    def test_a_number_this_module_cannot_read_is_an_error_and_not_a_zero(self):
        """`to_int` is the only place a claim's form is interpreted, and a silent
        default there would turn every unparseable claim into a passing one."""
        self.assertEqual(to_int("38"), 38)
        self.assertEqual(to_int("Thirty-eight"), 38)
        self.assertEqual(to_int(" thirty "), 30)
        self.assertEqual(to_int("Two"), 2)
        for text in ("", "several", "thirty-ten", "a dozen", "3.5"):
            with self.subTest(text=text):
                self.assertRaises(ValueError, to_int, text)


if __name__ == "__main__":
    unittest.main()
