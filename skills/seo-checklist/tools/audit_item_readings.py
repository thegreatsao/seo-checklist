#!/usr/bin/env python3
"""Every rule-carrying item has a current, recorded reading against its title.

`openspec/specs/registry/` REG-6: the rule attached to an item SHALL decide the question
the title asks. `audit_item_semantics.py` compares words, and all seven items this
repository later repaired by hand — GO-137, BL-083, MB-096, MB-097, MD-189, CI-016,
MD-186 — shared a word with their rule while measuring something else. Each was found by
a person reading the rule against the title, and nothing noticed when a title or a rule
changed under such a reading.

`item-readings.json` beside this file is that reading, for every item whose check runs a
script: the title and the check copied literally, a verdict, a reading that names the
path the rule asserts, and an answer for every shape below that fires on the item. This
tool fails when an item has no reading, when its title or rule no longer matches the
copy, when the reading stops naming the path, when the `measures` verdict and the item's
`measures` field disagree, or when a shape fires with no answer — or an answer is kept for
a shape that no longer fires.

What it does not do: judge meaning. A person decides whether a reading is true; this
guarantees only that nothing changes under a reading unnoticed. It also cannot see a
script whose field changes meaning under an unchanged path — the copy is of the registry,
not of the script. There is deliberately no command that writes the file: a changed rule
is re-read by hand, or the build stays red.

    python tools/audit_item_readings.py           # summary
    python tools/audit_item_readings.py --check   # exit 1 naming every problem
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
REGISTRY = HERE.parent / "resources/config/checklist.json"
READINGS = HERE / "item-readings.json"

VERDICTS = ("answers", "measures", "owed")

# Title words naming a subject only an outside source holds, and the scripts that can
# reach that source. GO-137 said *Indexed* and counted the crawl's own orphans; BL-083
# said *Backlinks* and read the page's outbound links.
EXTERNAL_SUBJECTS = (
    (re.compile(r"\bindex(ed|ing)?\b|\bcoverage\b"),
     lambda script: script.startswith("gsc_")),
    (re.compile(r"\bbacklinks?\b|\breferring\b|\blink profile\b|\binbound\b"),
     lambda script: script in ("gsc_links_csv.py", "link_profile.py")),
    (re.compile(r"\bclicks?\b|\bimpressions?\b|\bctr\b|\brank(s|ing|ings)?\b"
                r"|\bpositions?\b|\bquer(y|ies)\b"),
     lambda script: script.startswith("gsc_")),
    (re.compile(r"\buptime\b|\bblocklist\b|\bsafe.browsing\b|\bneighbou?ring\b"
                r"|\bregistration\b"),
     lambda script: script == "domain_safety_check.py"),
)

# A title joining subjects: MB-097 and MD-189 read one half, and MS-022's parenthetical
# was the condition its rule broke.
COMPOUND = re.compile(r"&| and |\+| vs\.? |/|\(")

# Words a rule can satisfy without measuring: CI-016 and MD-186 said *Meaningful* and
# counted alt attributes that were merely present.
QUALIFIERS = re.compile(
    r"\b(meaningful|descriptive|sufficient|unique|relevant|accurate|correct|valid|clean"
    r"|optimi[sz]e[ds]?|fast|strong|secure|proper|appropriate|quality|readable|clear"
    r"|consistent|complete|compelling)\b")


def _external(item: dict) -> bool:
    title = item["title"].lower()
    script = item["check"]["script"]
    return any(pattern.search(title) and not reachable(script)
               for pattern, reachable in EXTERNAL_SUBJECTS)


def _existential(item: dict) -> bool:
    # *At least one*: MB-096, MB-097 and MD-189 passed a page of a hundred images on one
    # responsive or modern-format image.
    rule = item["check"].get("assert") or {}
    return rule.get("gte") == 1 or rule.get("gt") == 0 or rule.get("len_gte") == 1


def _conjunction(item: dict) -> bool:
    return bool(COMPOUND.search(item["title"]))


def _qualifier(item: dict) -> bool:
    return bool(QUALIFIERS.search(item["title"].lower()))


SHAPES = {
    "external": _external,
    "existential": _existential,
    "conjunction": _conjunction,
    "qualifier": _qualifier,
}


def fired(item: dict) -> set[str]:
    """The shapes a reading of this item must answer."""
    return {name for name, detect in SHAPES.items() if detect(item)}


def rule_items(registry: dict) -> dict[str, dict]:
    return {item["id"]: item for item in registry["items"]
            if (item.get("check") or {}).get("script")}


def problems(registry: dict, readings: dict) -> list[str]:
    """Every way the recorded readings fail to describe the registry, one line each."""
    items = rule_items(registry)
    entries = readings.get("items") or {}
    out = []
    for item_id in sorted(set(items) - set(entries)):
        out.append(f"{item_id}: no reading — a rule-carrying item nobody has read")
    for item_id in sorted(set(entries) - set(items)):
        out.append(f"{item_id}: a reading for an id that carries no rule")
    for item_id in sorted(set(items) & set(entries)):
        item, entry = items[item_id], entries[item_id]
        if entry.get("title") != item["title"]:
            out.append(f"{item_id}: the title changed under its reading")
        if entry.get("check") != item["check"]:
            out.append(f"{item_id}: the rule changed under its reading")
        path = (item["check"].get("assert") or {}).get("path", "")
        if f"`{path}`" not in (entry.get("reading") or ""):
            out.append(f"{item_id}: the reading does not name the asserted path `{path}`")
        verdict = entry.get("verdict")
        if verdict not in VERDICTS:
            out.append(f"{item_id}: verdict {verdict!r} is not one of {', '.join(VERDICTS)}")
        if (verdict == "measures") != bool(item.get("measures")):
            out.append(f"{item_id}: verdict {verdict!r} and the item's `measures` field "
                       "disagree")
        answers = entry.get("shapes") or {}
        shapes = fired(item)
        for shape in sorted(shapes):
            if not str(answers.get(shape) or "").strip():
                out.append(f"{item_id}: the {shape} shape fires and the reading does not "
                           "answer it")
        for shape in sorted(set(answers) - shapes):
            out.append(f"{item_id}: an answer for the {shape} shape, which no longer fires")
    return out


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="exit 1 and name every problem")
    args = parser.parse_args()
    registry, readings = load(REGISTRY), load(READINGS)
    found = problems(registry, readings)
    if found:
        for line in found:
            print(line)
        print(f"{len(found)} problem(s): re-read each named pair and edit "
              f"{READINGS.name} by hand")
        return 1 if args.check else 0
    entries = readings["items"]
    verdicts = Counter(entry["verdict"] for entry in entries.values())
    shapes = Counter(shape for item in rule_items(registry).values()
                     for shape in fired(item))
    print(f"{len(entries)} readings: "
          + ", ".join(f"{verdicts[v]} {v}" for v in VERDICTS))
    print("owed: " + ", ".join(sorted(k for k, e in entries.items()
                                      if e["verdict"] == "owed")))
    print("shapes: " + ", ".join(f"{shapes[s]} {s}" for s in SHAPES))
    return 0


if __name__ == "__main__":
    sys.exit(main())
