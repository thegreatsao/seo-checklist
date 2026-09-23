#!/usr/bin/env python3
"""Which findings no registry rule can act on.

Not a test and not a gate. This is a recorded measurement of every
``none_severity`` assertion: the severity vocabulary its script can write, and the
finding text at severities the assertion does not refuse. A finding that changes no
verdict is otherwise a finding nobody has had reason to check.

That has mattered three releases running. In 0.59.0,
the former outbound-link checker called a link dead after matching six phrases in
urllib3's own error prose, and ``BL-083`` turned green. In 0.61.0, letting ``MB-100`` act on its
medium fixed-width finding exposed a detector that matched ``width`` inside
``max-width``. In 0.62.0, ``AR-162``'s dead-end finding was audited before the rule
was allowed to read it and was found sound. Each one was checked only because that
finding happened to be touched; accident is not a review method.

This still must not become a gate. The code cannot tell deliberate advice from a
claim the item must keep: ``MD-185``'s *Consider AVIF/WebP for raster image* belongs
at low forever, while ``MB-100``'s fixed-width finding made a claim its title made
and could not keep. A tool that called both defects would need exemptions, and those
exemptions would make it useless within two releases. Read this record and decide;
do not make its existence a reason to move a verdict.

**And "inert" here means no rule reads it, not that it changes nothing.** Four of
``CI-018``'s entries still appear below and are no longer inert in effect: at 0.97.0
they were found to be *caveats* rather than findings — each says an analysis did not
run — and they now mark the answer ``truncated``, which the runner reads and which
turns the item's pass into ``NO_DATA``. They move a verdict through a different door
from the severity this record measures. Reading the 29 entries once, end to end,
found three kinds and not one: deliberate advice that belongs at low forever, a
genuine site defect parked below the line, and a caveat wearing a finding's costume.
Only the third had a live free pass behind it.

    python tests/inert_findings.py                 # measure and report
    python tests/inert_findings.py --out FILE      # also write the JSON record
    python tests/inert_findings.py --check FILE    # exit 1 if the record is stale
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL_DIR = os.path.join(ROOT, "skills", "seo-checklist")
SCRIPTS = os.path.join(SKILL_DIR, "scripts")
TOOLS = os.path.join(SKILL_DIR, "tools")
REGISTRY = os.path.join(SKILL_DIR, "resources", "config", "checklist.json")

sys.path.insert(0, TOOLS)
# Imported rather than restated. If this instrument and the assertion audit grew
# separate ideas of which severities a script can say, one would eventually record
# a finding the other said did not exist while both looked correct in isolation.
from audit_assertions import SEVERITY_ALIAS, severity_literals  # noqa: E402


def _severity(node: ast.AST | None) -> str | None:
    """Return the runner's severity name for one literal finding write."""
    if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
        return None
    value = node.value.lower()
    return SEVERITY_ALIAS.get(value, value)


def _format_spec(node: ast.AST | None) -> str:
    if not isinstance(node, ast.JoinedStr):
        return ""
    return "".join(_message_text(value) for value in node.values)


def _message_text(node: ast.AST) -> str:
    """Render a finding expression as readable text, preserving f-string slots."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts = []
        for value in node.values:
            if isinstance(value, ast.FormattedValue):
                conversion = "" if value.conversion == -1 else f"!{chr(value.conversion)}"
                spec = _format_spec(value.format_spec)
                suffix = f":{spec}" if spec else ""
                parts.append(f"{{{ast.unparse(value.value)}{conversion}{suffix}}}")
            else:
                parts.append(_message_text(value))
        return "".join(parts)
    return "{" + ast.unparse(node) + "}"


def _helpers(tree: ast.AST) -> dict[str, tuple[str, str]]:
    """Module functions that write one finding for their caller.

    ``name -> (severity, parameter holding the message)``.

    A script that appends its findings inline is read by the walk below. A script
    that routes them through a helper is not: the helper's body carries the severity
    and a *parameter* where the text should be, so the walk records the literal
    ``{message}`` once and loses every real sentence the callers passed.

    That is not hypothetical. `server_log_audit.py` moved four caveats behind
    `_incomplete()` at 0.97.0 and this record lost all four in the same commit,
    replacing them with a single `{message}` — an entry describing a finding no
    script emits. CI caught it because the `--check` gate runs there; nothing local
    did.

    So helpers are resolved rather than named: any module-level function whose body
    appends a dict with a literal severity and a message that is one of its own
    parameters. `issue(severity, message)` is handled separately below because its
    severity comes from the caller too.
    """
    helpers: dict[str, tuple[str, str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        names = {arg.arg for arg in node.args.args}
        for inner in ast.walk(node):
            if not isinstance(inner, ast.Dict):
                continue
            fields = {
                str(key.value).lower(): value
                for key, value in zip(inner.keys, inner.values, strict=True)
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            }
            severity = _severity(fields.get("severity"))
            message = fields.get("message") or fields.get("finding")
            if (severity and isinstance(message, ast.Name)
                    and message.id in names):
                helpers[node.name] = (severity, message.id)
    return helpers


def _helper_message(node: ast.Call, param: str, tree: ast.AST) -> ast.AST | None:
    """The text one call handed a helper, positionally or by keyword."""
    for keyword in node.keywords:
        if keyword.arg == param:
            return keyword.value
    for defined in ast.walk(tree):
        if isinstance(defined, ast.FunctionDef) and defined.name == (
                getattr(node.func, "id", None) or getattr(node.func, "attr", None)):
            names = [arg.arg for arg in defined.args.args]
            if param in names:
                index = names.index(param)
                if index < len(node.args):
                    return node.args[index]
    return None


def finding_messages(script: str) -> dict[str, list[str]]:
    """Finding text grouped by the literal severity written beside it."""
    path = os.path.join(SCRIPTS, script)
    with open(path, encoding="utf-8") as stream:
        tree = ast.parse(stream.read())

    helpers = _helpers(tree)
    # The helpers' own bodies are skipped: the dict in there says `{message}`, which
    # is a parameter and not a finding. Their callers supply the real text.
    inside_helper = {
        inner
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name in helpers
        for inner in ast.walk(node)
    }

    found: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name in helpers:
                severity, param = helpers[name]
                message = _helper_message(node, param, tree)
                if message is not None:
                    found.setdefault(severity, set()).add(_message_text(message))
                continue
        if node in inside_helper:
            continue
        severity = None
        message = None
        if isinstance(node, ast.Dict):
            fields = {
                str(key.value).lower(): value
                for key, value in zip(node.keys, node.values, strict=True)
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            }
            severity = _severity(fields.get("severity"))
            message = fields.get("message") or fields.get("finding")
        elif isinstance(node, ast.Call):
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            if name == "issue":
                severity = _severity(node.args[0] if node.args else None)
                if len(node.args) > 1:
                    message = node.args[1]
                else:
                    keywords = {keyword.arg: keyword.value for keyword in node.keywords}
                    message = keywords.get("message") or keywords.get("finding")
        if severity and message is not None:
            found.setdefault(severity, set()).add(_message_text(message))
    return {severity: sorted(messages) for severity, messages in sorted(found.items())}


def measure() -> dict:
    with open(REGISTRY, encoding="utf-8") as stream:
        registry = json.load(stream)

    rows = {}
    for item in registry["items"]:
        check = item.get("check") or {}
        assertion = check.get("assert") or {}
        if not isinstance(assertion, dict) or "none_severity" not in assertion:
            continue

        script = check["script"]
        vocabulary = severity_literals(script)
        refuses = {
            SEVERITY_ALIAS.get(value.lower(), value.lower())
            for value in assertion["none_severity"]
        }
        inert = vocabulary - refuses
        messages = finding_messages(script)
        missing_messages = inert - set(messages)
        if missing_messages:
            missing = ", ".join(sorted(missing_messages))
            raise RuntimeError(f"{script} has no finding text for {missing}")

        findings = [
            {"severity": severity, "message": message}
            for severity in sorted(inert)
            for message in messages[severity]
        ]
        rows[item["id"]] = {
            "title": item["title"],
            "script": script,
            "path": assertion.get("path"),
            "refuses": sorted(refuses),
            "script_severities": sorted(vocabulary),
            "inert_findings": findings,
        }

    return {
        "registry_version": registry["registry_version"],
        "none_severity_item_count": len(rows),
        "inert_item_count": sum(bool(row["inert_findings"]) for row in rows.values()),
        "items": rows,
    }


def report(record: dict) -> list[str]:
    rows = record["items"]
    inert = {item_id: row for item_id, row in rows.items() if row["inert_findings"]}
    lines = [
        f"{len(rows)} none_severity item(s); {len(inert)} carry findings their rule "
        "cannot act on"
    ]
    for item_id, row in inert.items():
        lines.append(f"  {item_id} {row['script']} — {row['title']}")
        for finding in row["inert_findings"]:
            lines.append(f"      {finding['severity']}: {finding['message']}")
    lines.append("\nThis is a measurement, not a gate; inert advice and inert defects "
                 "require human judgment.")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", help="write the JSON record here")
    parser.add_argument("--check", help="compare against this record and exit 1 on drift")
    args = parser.parse_args()

    record = measure()
    print("\n".join(report(record)))

    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(record, stream, indent=2, ensure_ascii=False, sort_keys=True)
            stream.write("\n")
        print(f"\nwrote {args.out}")
    if args.check:
        with open(args.check, encoding="utf-8") as stream:
            stored = json.load(stream)
        if stored != json.loads(json.dumps(record, sort_keys=True)):
            print(f"\n{args.check} is out of step with a fresh measurement",
                  file=sys.stderr)
            return 1
        print(f"\n{args.check} is in step")
    return 0


if __name__ == "__main__":
    sys.exit(main())
