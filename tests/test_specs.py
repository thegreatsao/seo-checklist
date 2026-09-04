"""The normative documents in `specs/`, read the way they ask code to be read.

Each document states a requirement, argues it under `Why:`, and names under `Reader:`
what reddens when it is violated. Appendix B then tabulates those classifications, and
the table is what anyone quotes when they ask how much of a capability is protected.

The table has been wrong four times in four documents, always in the same direction and
always by the same mechanism: a `Reader:` line that qualifies its verdict — "enforced for
four of the five", "enforced for what it compares" — summarised in the table as plain
`enforced`. REG-3, DEC-7 and DEC-10 were caught by hand, two of them only after a second
reader ran mutation probes. That is three too many for a rule a `grep` can hold.

So this module reads the documents as data. It does not judge whether a classification is
*true* — nothing here runs a mutation probe, and a document that calls an enforced
requirement `none` passes. It holds the cheaper property that kept failing: **a document
must not contradict itself**, and the summary must not be kinder than the evidence line
it summarises.

The rules are derived from the corpus rather than imposed on it. Where all four documents
already agree on a shape, that shape is asserted; where they differ, the difference is
allowed. Adding a fifth document should not require editing this file.
"""
from __future__ import annotations

import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPECS = os.path.join(ROOT, "specs")
TESTS = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.join(ROOT, "skills", "seo-checklist")

CLASSES = ("enforced", "partial", "none", "opposed")

# The word a summary sentence uses for a count. `none` is spelled as a phrase —
# "Nothing fully enforced" — because a document with an empty column says so in prose.
NUMBER = {"nothing": 0, "no": 0, "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
          "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
          "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
          "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20}

# `none` in the table is spelled `unread` in the summary sentence: the table names the
# reader's state and the sentence names the requirement's. Both appear in all four.
SUMMARY_WORD = {"enforced": "enforced", "partial": "partial", "none": "unread",
                "opposed": "opposed"}

REQUIREMENT = re.compile(r"^### ([A-Z]{2,4})-(\d+) — (.+)$")
READER = re.compile(r"^\*\*Reader:\*\*\s+(.*)$")
WHY = re.compile(r"^\*\*Why:\*\*")
ROW = re.compile(r"^\| \*\*(enforced|partial|none|opposed)\*\* \| (.+?) \|$")
ID = re.compile(r"\b([A-Z]{2,4}-\d+)\b")

# A classification word may be wrapped in `**` and must end the claim. Everything after
# it is prose about the reader; everything *attached* to it — "enforced for X" — is a
# qualification, and a qualified claim is not the bare word the table repeats.
TERMINATORS = ".,:;—"


def documents():
    """(name, path) for every spec, discovered rather than listed.

    A list here would go stale the way the notebook's did: the reader that notices a
    missing document must not be the line somebody has to add for it.
    """
    found = []
    for name in sorted(os.listdir(SPECS)):
        path = os.path.join(SPECS, name, "spec.md")
        if os.path.isfile(path):
            found.append((name, path))
    return found


def read(path: str) -> list[str]:
    with open(path, encoding="utf-8") as stream:
        return stream.read().splitlines()


def requirements(lines: list[str]) -> dict:
    """id -> {"title", "line", "why", "reader"} for every requirement in a document."""
    out = {}
    current = None
    for number, line in enumerate(lines, 1):
        heading = REQUIREMENT.match(line)
        if heading:
            prefix, index, title = heading.groups()
            current = f"{prefix}-{index}"
            out[current] = {"title": title, "line": number, "why": 0, "reader": None,
                            "reader_line": 0}
            continue
        if line.startswith("## "):          # a new section ends the requirement
            current = None
        if current is None:
            continue
        if WHY.match(line):
            out[current]["why"] += 1
        seen = READER.match(line)
        if seen and out[current]["reader"] is None:
            out[current]["reader"] = seen.group(1)
            out[current]["reader_line"] = number
    return out


def classification(reader: str) -> tuple[str | None, bool]:
    """The bare classification word a `Reader:` line opens with, and whether it is bare.

    Returns (word, qualified). `qualified` is the property this module exists for: a
    line opening "enforced for the status routing" claims less than "enforced." and may
    not be tabulated as though it claimed the same.
    """
    text = reader.lstrip("*").strip()
    for word in CLASSES:
        if not text.startswith(word):
            continue
        rest = text[len(word):]
        rest = rest.lstrip("*")             # `**none**,` and `**opposed.**`
        if rest == "" or rest[0] in TERMINATORS or rest[0].isspace() and (
                rest.strip()[:1] in TERMINATORS or rest.strip()[:1] == "—"):
            return word, False
        return word, True
    return None, False


def appendix_b(lines: list[str]) -> dict:
    """classification -> [ids], read out of the table."""
    table = {}
    for line in lines:
        row = ROW.match(line)
        if not row:
            continue
        label, cell = row.groups()
        table[label] = ID.findall(cell)
    return table


def summary(lines: list[str]) -> dict:
    """The bold sentence under the table, as classification -> count."""
    for line in lines:
        if not line.startswith("**") or " of " not in line and "unread" not in line:
            continue
        counts = {}
        for word, label in ((w, c) for c in CLASSES for w in [SUMMARY_WORD[c]]):
            found = re.search(r"\b([A-Za-z]+)\s+(?:fully\s+)?" + word + r"\b", line)
            if found and found.group(1).lower() in NUMBER:
                counts[label] = NUMBER[found.group(1).lower()]
        if counts.get("enforced") is not None and "partial" in counts:
            return counts
    return {}


DOCS = [(name, read(path), path) for name, path in documents()]


class EveryDocumentHasTheShapeTheSuiteReads(unittest.TestCase):

    def test_there_are_documents_to_read(self):
        """A discovery bug here would make every other test in this module vacuous."""
        self.assertGreaterEqual(len(DOCS), 4, [name for name, _, _ in DOCS])

    def test_every_document_carries_one_prefix(self):
        for name, lines, _ in DOCS:
            with self.subTest(document=name):
                prefixes = {i.split("-")[0] for i in requirements(lines)}
                self.assertEqual(len(prefixes), 1, prefixes)

    def test_requirement_numbers_run_from_one_without_a_gap(self):
        """A gap is a requirement deleted without renumbering, and every count in the
        document then describes a set nobody can enumerate."""
        for name, lines, _ in DOCS:
            with self.subTest(document=name):
                numbers = sorted(int(i.split("-")[1]) for i in requirements(lines))
                self.assertEqual(numbers, list(range(1, len(numbers) + 1)))

    def test_every_requirement_argues_itself_once_and_names_one_reader(self):
        for name, lines, _ in DOCS:
            for item, body in requirements(lines).items():
                with self.subTest(document=name, requirement=item):
                    self.assertEqual(body["why"], 1,
                                     f"{item} carries {body['why']} `Why:` lines")
                    self.assertIsNotNone(body["reader"], f"{item} names no reader")


class AReaderLineMeansWhatTheTableSaysItMeans(unittest.TestCase):

    def test_every_reader_line_opens_with_a_classification(self):
        for name, lines, _ in DOCS:
            for item, body in requirements(lines).items():
                with self.subTest(document=name, requirement=item):
                    word, _ = classification(body["reader"])
                    self.assertIn(word, CLASSES,
                                  f"{item}: `Reader:` opens {body['reader'][:60]!r}, "
                                  f"which is none of {CLASSES}")

    def test_a_qualified_claim_is_not_tabulated_as_a_bare_one(self):
        """The rule this module was written for.

        "enforced for four of the five" (REG-3), "enforced for what it compares"
        (DEC-7) — a classification word with a qualifier welded to it claims less than
        the word alone, and Appendix B repeats the word alone. Both of those were
        tabulated as `enforced` and were `partial`; a third, DEC-10, said `enforced`
        flatly and was wrong for a different reason this test cannot see.

        The remedy is not to forbid qualification — the honest lines say "partial —
        enforced for four of the five" — but to forbid a qualified word from being
        stronger than `partial` in the table.
        """
        for name, lines, path in DOCS:
            table = appendix_b(lines)
            where = {item: label for label, ids in table.items() for item in ids}
            for item, body in requirements(lines).items():
                word, qualified = classification(body["reader"])
                if not qualified:
                    continue
                with self.subTest(document=name, requirement=item):
                    self.assertIn(
                        where.get(item), ("partial", "none"),
                        f"{item} at {os.path.basename(path)}:{body['reader_line']} "
                        f"opens its reader with a qualified {word!r} — "
                        f"{body['reader'][:70]!r} — and Appendix B files it under "
                        f"{where.get(item)!r}. Either de-qualify the line or move the "
                        f"row; a qualified claim is at most `partial`.")

    def test_the_table_and_the_reader_lines_agree(self):
        for name, lines, _ in DOCS:
            table = appendix_b(lines)
            where = {item: label for label, ids in table.items() for item in ids}
            for item, body in requirements(lines).items():
                word, qualified = classification(body["reader"])
                if qualified:
                    continue            # the test above owns this case
                with self.subTest(document=name, requirement=item):
                    self.assertEqual(where.get(item), word,
                                     f"{item}'s reader says {word!r} and Appendix B "
                                     f"files it under {where.get(item)!r}")


class AppendixBDescribesThisDocument(unittest.TestCase):

    def test_every_requirement_is_filed_exactly_once(self):
        for name, lines, _ in DOCS:
            table = appendix_b(lines)
            filed = [i for ids in table.values() for i in ids]
            with self.subTest(document=name):
                self.assertEqual(sorted(filed), sorted(set(filed)),
                                 "a requirement is filed in two rows")
                self.assertEqual(set(filed), set(requirements(lines)),
                                 "the table and the requirements disagree about which "
                                 "requirements exist")

    def test_the_summary_sentence_counts_the_table(self):
        """The sentence is what gets quoted; the table is what gets read."""
        for name, lines, _ in DOCS:
            table = appendix_b(lines)
            said = summary(lines)
            with self.subTest(document=name):
                self.assertTrue(said, "no summary sentence found under the table")
                for label, ids in table.items():
                    if label in said:
                        self.assertEqual(said[label], len(ids),
                                         f"the sentence says {said[label]} {label} and "
                                         f"the table lists {len(ids)}")

    def test_a_row_that_is_empty_says_so(self):
        """`| **enforced** | — none |` rather than an absent row: a missing row reads as
        an oversight, and a document with nothing enforced is making a claim."""
        for name, lines, _ in DOCS:
            table = appendix_b(lines)
            with self.subTest(document=name):
                for label in ("enforced", "partial", "none"):
                    self.assertIn(label, table,
                                  f"no {label!r} row; an empty column is still a row")


class ADocumentNamesThingsThatExist(unittest.TestCase):
    """A document that names a deleted test keeps claiming a reader it has lost.

    Renaming a test is cheap and common; the document does not move with it, and the
    `Reader:` line then points at nothing while still counting as coverage in
    Appendix B. This is the same failure as a stale count, one indirection out.
    """

    def setUp(self):
        self.defined = set()
        for name in os.listdir(TESTS):
            if not name.endswith(".py"):
                continue
            with open(os.path.join(TESTS, name), encoding="utf-8") as stream:
                self.defined |= set(re.findall(r"^\s*def (test_\w+)", stream.read(),
                                               re.M))

    def test_every_test_it_names_exists(self):
        for name, lines, _ in DOCS:
            body = "\n".join(lines)
            for cited in sorted(set(re.findall(r"`(test_\w+)`", body))):
                with self.subTest(document=name, test=cited):
                    if os.path.isfile(os.path.join(TESTS, cited + ".py")):
                        continue        # a module, cited without its extension
                    self.assertIn(cited, self.defined,
                                  f"{name} names {cited}, which no test defines")

    def test_every_path_it_names_exists(self):
        for name, lines, _ in DOCS:
            body = "\n".join(lines)
            cited = set(re.findall(r"`((?:tools|tests|scripts)/[\w./-]+\.(?:py|json|md))`",
                                   body))
            for path in sorted(cited):
                with self.subTest(document=name, path=path):
                    candidates = [os.path.join(ROOT, path),
                                  os.path.join(SKILL, path)]
                    self.assertTrue(any(os.path.exists(c) for c in candidates),
                                    f"{name} names {path}, which is in neither the repo "
                                    f"root nor the skill directory")


if __name__ == "__main__":
    unittest.main()
