#!/usr/bin/env python3
"""The shapes catalogue's account of itself, computed from the tree.

`openspec/specs/evidence/` EVD-4. `resources/references/script-output-shapes.md` opens
with a paragraph telling a rule-writer how many checkers it covers and which of them
break the `issues[].severity` + `message` convention the rest share. That paragraph is
the first thing read before a rule is written, and every clause of it was wrong:

* it said "all 57 scripts the registry runs"; the registry runs **58**;
* it said the only extra was `site_crawl.py`; `detect_profile.py` is documented too;
* it said "four of them" break the convention; measured below, it is many more;
* it said `gsc_checker.py` capitalises severity in `issues[]`; its `issues[]` severities
  are lowercase and its *`opportunities[]`* are the capitalised ones.

Nothing could have caught any of it, which is the requirement: the account is derived
here and written into the file between two markers, and `--check` fails when the file
and the tree disagree.

    python tools/audit_catalogue.py            # rewrite the derived block
    python tools/audit_catalogue.py --check    # exit 1 if it is stale

**What is derived from what.** The counts come from `checklist.json` and from the `###`
headings. The convention classes come from the catalogue's *own body* — the `item keys:`
line under each `issues[]` entry — because that line is what the probe recorded and is
therefore the same evidence a rule-writer would act on. The severity *case* cannot come
from there, since the probe records keys and not values; it comes from the same AST read
`tools/audit_assertions.py` uses in CI, with the case kept.

A section whose `issues[]` carries no `item keys:` line is its own class and is reported
as one: the probe saw the key and never saw an element, so the document does not say
what an element looks like, and a rule written against it is written against nothing.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
SKILL = os.path.join(ROOT, "skills", "seo-checklist")
SCRIPTS = os.path.join(SKILL, "scripts")
REGISTRY = os.path.join(SKILL, "resources", "config", "checklist.json")
CATALOGUE = os.path.join(SKILL, "resources", "references", "script-output-shapes.md")

OPEN = "<!-- derived: tools/audit_catalogue.py -->"
CLOSE = "<!-- /derived -->"

CONVENTION = ("severity", "message")


def registry_scripts() -> set[str]:
    with open(REGISTRY, encoding="utf-8") as stream:
        items = json.load(stream)["items"]
    return {(item.get("check") or {}).get("script")
            for item in items if (item.get("check") or {}).get("script")}


def sections(text: str) -> dict[str, str]:
    """`### name.py` heading to the body under it, up to the next heading."""
    out: dict[str, str] = {}
    current, buffer = None, []
    for line in text.splitlines():
        heading = re.match(r"^### ([A-Za-z0-9_]+\.py)$", line)
        if heading:
            if current:
                out[current] = "\n".join(buffer)
            current, buffer = heading.group(1), []
        elif line.startswith("### ") or line.startswith("## "):
            if current:
                out[current] = "\n".join(buffer)
            current, buffer = None, []
        elif current is not None:
            buffer.append(line)
    if current:
        out[current] = "\n".join(buffer)
    return out


def issue_keys(body: str) -> list[str] | None:
    """The item keys of a root `issues[]`, or None when the section has no root
    `issues[]` at all.

    An empty list means the entry is there and the document never says what is in it.
    Only a root-level entry counts: a nested `resources[].issues` is a different field
    with the same name, and a rule pointing at `issues` does not reach it.
    """
    lines = body.splitlines()
    for index, line in enumerate(lines):
        if not line.startswith("`issues[]`") and not line.startswith("`issues`"):
            continue
        for following in lines[index + 1:]:
            if following.startswith("`") or not following.strip():
                break
            keys = re.search(r"item keys: (.+)$", following.strip())
            if keys:
                return [k.strip() for k in keys.group(1).split(",")]
        return []
    return None


def severity_cases(script: str) -> set[str]:
    """Every severity string the script can put in a dict, with its case kept.

    The same AST read `audit_assertions.severity_literals` performs — a regex over the
    source finds every word in the file, which is the mistake that cleared fifteen dead
    patterns in that tool's first version — except that this one does not lowercase, so
    it can answer the question the catalogue's paragraph asks.
    """
    with open(os.path.join(SCRIPTS, script), encoding="utf-8") as stream:
        tree = ast.parse(stream.read())
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values, strict=True):
                if (isinstance(key, ast.Constant)
                        and str(key.value).lower() == "severity"
                        and isinstance(value, ast.Constant)
                        and isinstance(value.value, str)):
                    out.add(value.value)
        if isinstance(node, ast.Call):
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            if (name == "issue" and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)):
                out.add(node.args[0].value)
            for keyword in node.keywords:
                if (keyword.arg == "severity"
                        and isinstance(keyword.value, ast.Constant)
                        and isinstance(keyword.value.value, str)):
                    out.add(keyword.value.value)
    return out


def measure() -> dict:
    with open(CATALOGUE, encoding="utf-8") as stream:
        text = stream.read()
    documented = sections(text)
    named = registry_scripts()

    conforming, no_issues, other_key, unseen = [], [], [], []
    for script in sorted(documented):
        keys = issue_keys(documented[script])
        if keys is None:
            no_issues.append(script)
        elif not keys:
            unseen.append(script)
        elif all(k in keys for k in CONVENTION):
            conforming.append(script)
        else:
            text_key = next((k for k in keys if k in ("finding", "text", "detail")), "")
            other_key.append((script, text_key or "no text key at all"))

    capitalised = sorted(
        script for script in documented
        if os.path.exists(os.path.join(SCRIPTS, script))
        and any(value != value.lower() for value in severity_cases(script)))

    return {
        "documented": sorted(documented),
        "registry_scripts": sorted(named),
        "extra": sorted(set(documented) - named),
        "undocumented": sorted(named - set(documented)),
        "conforming": conforming,
        "no_issues": no_issues,
        "unseen": unseen,
        "other_key": other_key,
        "capitalised": capitalised,
    }


def names(values) -> str:
    return ", ".join(f"`{v}`" for v in values)


def block(facts: dict) -> str:
    """The paragraph, in the voice the rest of the file is written in."""
    lines = [
        f"This catalogue documents {len(facts['documented'])} checkers: the "
        f"{len(facts['registry_scripts'])} the registry runs, plus "
        f"{len(facts['extra'])} it does not name — {names(facts['extra'])} — which the "
        f"runner runs itself before building the plan and whose output the rest of the "
        f"audit reads.",
        "",
    ]
    if facts["undocumented"]:
        lines += [
            f"**{len(facts['undocumented'])} script(s) the registry runs are not "
            f"documented here at all**: {names(facts['undocumented'])}. A rule written "
            f"against one of those is written against nothing this file describes.",
            "",
        ]
    deviant = (len(facts["no_issues"]) + len(facts["unseen"])
               + len(facts["other_key"]) + len(facts["capitalised"]))
    lines += [
        f"Only {len(facts['conforming'])} of them are documented as carrying an "
        f"`issues[]` whose elements have both `severity` and `message` — the "
        f"convention a rule can rely on. **Check the section before writing a rule.** "
        f"The other ways this file describes an `issues[]`, counting a script once per "
        f"way, come to {deviant} entries:",
        "",
        f"* **{len(facts['no_issues'])} emit no root `issues[]`**: "
        f"{names(facts['no_issues'])}. A `none_severity` or `len_eq: 0` rule over one "
        f"of these reads a key that is never there, which is `NO_DATA` forever.",
        f"* **{len(facts['unseen'])} record an `issues[]` and never say what is in "
        f"one**: {names(facts['unseen'])}. That is a gap in this file rather than a "
        f"fact about the script — the probe saw the key and captured no element — and "
        f"a rule naming a field inside one of these is a guess.",
    ]
    if facts["other_key"]:
        pairs = ", ".join(f"`{s}` (`{k}`)" for s, k in facts["other_key"])
        lines.append(
            f"* **{len(facts['other_key'])} carry the human text under another key**: "
            f"{pairs}. `none_matching` with `field: message` matches nothing on these.")
    lines.append(
        f"* **{len(facts['capitalised'])} can put a capitalised severity in a dict**: "
        f"{names(facts['capitalised'])}. `none_severity` compares lowercase, and "
        f"`SEVERITY_ALIAS` in `tools/audit_assertions.py` is what keeps that from "
        f"silently clearing a rule.")
    return "\n".join(lines)


def current(text: str) -> str | None:
    found = re.search(re.escape(OPEN) + r"\n(.*?)\n" + re.escape(CLOSE), text, re.S)
    return found.group(1) if found else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="exit 1 if the derived block is stale")
    args = parser.parse_args()

    with open(CATALOGUE, encoding="utf-8") as stream:
        text = stream.read()
    fresh = block(measure())
    held = current(text)

    if held is None:
        print(f"{os.path.relpath(CATALOGUE, ROOT)} has no derived block. Add\n"
              f"  {OPEN}\n  {CLOSE}\naround the opening paragraph and run this again.",
              file=sys.stderr)
        return 1

    if args.check:
        if held.strip() == fresh.strip():
            print("the catalogue's account of itself is in step with the tree")
            return 0
        print("the catalogue's account of itself is stale. It says:\n", file=sys.stderr)
        print(held, file=sys.stderr)
        print("\nThe tree says:\n", file=sys.stderr)
        print(fresh, file=sys.stderr)
        print("\nRun tools/audit_catalogue.py to rewrite it.", file=sys.stderr)
        return 1

    newline = "\r\n" if "\r\n" in text else "\n"
    body = text.replace("\r\n", "\n")
    body = re.sub(re.escape(OPEN) + r"\n.*?\n" + re.escape(CLOSE),
                  OPEN + "\n" + fresh + "\n" + CLOSE, body, count=1, flags=re.S)
    with open(CATALOGUE, "w", encoding="utf-8", newline=newline) as stream:
        stream.write(body)
    print(f"rewrote the derived block in {os.path.relpath(CATALOGUE, ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
