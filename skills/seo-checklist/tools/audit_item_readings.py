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

An entry may also carry `second_reading`, the record of a second reader (F03; the plan is
`docs/sprint-20261023-F03-plan.md`): who read it, the session that is the trace, its own
verdict, an optional dispute, and `read`, the digest of what it judged — the item's title,
check and `measures` sentence and the first reading's verdict, reading and shape answers.
A malformed record, or one whose digest is no longer current, fails like a changed rule.
A missing record and a dispute are counted, not failed, until the plan's last batch.

What it does not do: judge meaning. A person decides whether a reading is true; this
guarantees only that nothing changes under a reading unnoticed. It also cannot see a
script whose field changes meaning under an unchanged path — the copy is of the registry,
not of the script. There is deliberately no command that writes the file: a changed rule
is re-read by hand, or the build stays red.

    python tools/audit_item_readings.py           # summary
    python tools/audit_item_readings.py --check   # exit 1 naming every problem
    python tools/audit_item_readings.py --digest CI-001   # what a second reading records as `read`
    python tools/audit_item_readings.py --blind CI-001 CI-002   # the second reader's blind input
    python tools/audit_item_readings.py --open CI-001     # then the first reading it is shown
"""

from __future__ import annotations

import python_floor  # noqa: F401

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
REGISTRY = HERE.parent / "resources/config/checklist.json"
READINGS = HERE / "item-readings.json"
SCRIPTS = HERE.parent / "scripts"
BRIEF = HERE / "second-reading-brief.md"

VERDICTS = ("answers", "measures", "owed")
SECOND_READING = ("reader", "session", "read", "verdict", "dispute")

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

from scope_line import print_scope  # noqa: E402

# What a passing run establishes, and what it does not (openspec/specs/governance/ GOV-6).
ESTABLISHES = (
    "every rule-carrying item has a reading whose copy of its title and rule is "
    "current, which names the path the rule asserts and answers every shape that fires "
    "on the item; every recorded second reading is of the reading as it now stands"
)
DOES_NOT_ESTABLISH = (
    "that any reading is true, which a person decides, that a script's field still "
    "means what it meant when the reading was written, that every item has a second "
    "reading, or that a second reader was independent of the first, which only the "
    "session it names can show"
)



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


def digest(item: dict, entry: dict) -> str:
    """What a second reading judged: change any of it and the record is stale."""
    judged = {"title": item["title"], "check": item["check"],
              "measures": item.get("measures"), "verdict": entry.get("verdict"),
              "reading": entry.get("reading"), "shapes": entry.get("shapes")}
    text = json.dumps(judged, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def sources(items) -> dict[str, str]:
    """The source of every script these items run, by file name."""
    return {item["check"]["script"]: (SCRIPTS / item["check"]["script"]).read_text(
        encoding="utf-8") for item in items}


def blind_input(items: list[tuple[str, dict]], scripts: dict[str, str]) -> str:
    """What a second reader judges before it sees the first reading (the brief's blind
    pass): each item's title, check and `measures` sentence, then each script once."""
    out = []
    for label, item in items:
        out += [f"### Item {label}", f"Title: {item['title']}",
                "Check: " + json.dumps(item["check"], sort_keys=True, ensure_ascii=False),
                "Measures: " + (item.get("measures")
                                or "(none: the item carries no `measures` sentence)"), ""]
    for script in dict.fromkeys(item["check"]["script"] for _, item in items):
        out += [f"### Script {script}", "```python", scripts[script].rstrip("\n"), "```", ""]
    return "\n".join(out)


def open_input(item_id: str, entry: dict) -> str:
    """The first reading, shown to the second reader once its own verdict is written."""
    return "\n".join([f"### Item {item_id}: the first reading",
                      f"Verdict: {entry.get('verdict')}", f"Reading: {entry.get('reading')}",
                      "Shapes: " + json.dumps(entry.get("shapes") or {}, ensure_ascii=False),
                      ""])


def _second_reading_problems(item_id: str, item: dict, entry: dict) -> list[str]:
    record = entry["second_reading"]
    if not isinstance(record, dict):
        return [f"{item_id}: the second reading is not an object"]
    out = []
    extra = sorted(set(record) - set(SECOND_READING))
    if extra:
        out.append(f"{item_id}: the second reading carries keys it does not define: "
                   + ", ".join(extra))
    for key in ("reader", "session", "read"):
        if not isinstance(record.get(key), str) or not record[key].strip():
            out.append(f"{item_id}: the second reading has no {key}")
    if not isinstance(record.get("dispute", ""), str):
        out.append(f"{item_id}: the second reading's dispute is not text")
    if record.get("verdict") not in VERDICTS:
        out.append(f"{item_id}: second-reading verdict {record.get('verdict')!r} is not "
                   f"one of {', '.join(VERDICTS)}")
    if isinstance(record.get("read"), str) and record["read"].strip() \
            and record["read"] != digest(item, entry):
        out.append(f"{item_id}: the reading changed under its second reading, which "
                   "must be read again")
    return out


def second_readings(registry: dict, readings: dict) -> dict[str, int]:
    """Current second readings, and how many of them agree with the first."""
    items = rule_items(registry)
    counts = {"current": 0, "agree": 0, "disputed": 0}
    for item_id, entry in (readings.get("items") or {}).items():
        record = entry.get("second_reading")
        if (item_id not in items or not isinstance(record, dict)
                or _second_reading_problems(item_id, items[item_id], entry)):
            continue
        counts["current"] += 1
        agrees = (record["verdict"] == entry.get("verdict")
                  and not record.get("dispute", "").strip())
        counts["agree" if agrees else "disputed"] += 1
    return counts


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
        if "second_reading" in entry:
            out.extend(_second_reading_problems(item_id, item, entry))
    return out


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="exit 1 and name every problem")
    parser.add_argument("--digest", metavar="ID",
                        help="print the digest a second reading of ID records as `read`")
    parser.add_argument("--blind", metavar="ID", nargs="+",
                        help="print what the second reader of these items is shown first")
    parser.add_argument("--open", metavar="ID", nargs="+",
                        help="print the first readings it is shown after its own verdict")
    args = parser.parse_args()
    registry, readings = load(REGISTRY), load(READINGS)
    if args.blind or args.open:
        items, entries = rule_items(registry), readings.get("items") or {}
        ids = args.blind or args.open
        unknown = [i for i in ids if i not in items or i not in entries]
        if unknown:
            print(", ".join(unknown) + ": no reading of a rule-carrying item by that id")
            return 1
        if args.blind:
            print(blind_input([(i, items[i]) for i in ids], sources(items[i] for i in ids)))
        else:
            print("\n".join(open_input(i, entries[i]) for i in ids))
        return 0
    if args.digest:
        item = rule_items(registry).get(args.digest)
        entry = (readings.get("items") or {}).get(args.digest)
        if item is None or entry is None:
            print(f"{args.digest}: no reading of a rule-carrying item by that id")
            return 1
        print(digest(item, entry))
        return 0
    found = problems(registry, readings)
    if found:
        for line in found:
            print(line)
        print(f"{len(found)} problem(s): re-read each named pair and edit "
              f"{READINGS.name} by hand")
        if args.check:
            return 1
        print_scope(ESTABLISHES, DOES_NOT_ESTABLISH)
        return 0
    entries = readings["items"]
    verdicts = Counter(entry["verdict"] for entry in entries.values())
    shapes = Counter(shape for item in rule_items(registry).values()
                     for shape in fired(item))
    print(f"{len(entries)} readings: "
          + ", ".join(f"{verdicts[v]} {v}" for v in VERDICTS))
    print("owed: " + ", ".join(sorted(k for k, e in entries.items()
                                      if e["verdict"] == "owed")))
    print("shapes: " + ", ".join(f"{shapes[s]} {s}" for s in SHAPES))
    second = second_readings(registry, readings)
    print(f"second readings: {second['current']} of {len(entries)} current — "
          f"{second['agree']} agree, {second['disputed']} disputed")
    print_scope(ESTABLISHES, DOES_NOT_ESTABLISH)
    return 0


if __name__ == "__main__":
    from utf8_streams import utf8_streams
    utf8_streams()
    sys.exit(main())
