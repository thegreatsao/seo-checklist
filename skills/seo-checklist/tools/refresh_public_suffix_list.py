#!/usr/bin/env python3
"""Refresh the bundled Public Suffix List snapshot.

The list is bundled rather than fetched at audit time for the same reason the
registry is: a run must produce the same answer offline, next month, on somebody
else's machine. That makes the snapshot a dated artifact, so this script exists to
say when it was taken and to replace it deliberately.

    python3 tools/refresh_public_suffix_list.py            # download and replace
    python3 tools/refresh_public_suffix_list.py --check     # report the snapshot's age

The list is only used to derive the default `sc-domain:` Search Console property.
A stale snapshot means a new platform suffix is missing and the property for a
site on it is wrong — visible, and overridable with --gsc-property, but wrong.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

SOURCE = "https://publicsuffix.org/list/public_suffix_list.dat"
HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
TARGET = os.path.join(SKILL_DIR, "resources", "config", "public_suffix_list.dat")
STAMP_HEADER = "// snapshot taken "

# Below this the download is not a public suffix list — a captive portal, an error
# page, a truncated transfer. Replacing a good snapshot with one of those would
# silently narrow every domain to its last two labels.
MIN_RULES = 5000


def rule_count(text: str) -> int:
    return sum(1 for line in text.splitlines()
               if line.strip() and not line.strip().startswith("//"))


def snapshot_date(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.startswith(STAMP_HEADER):
                    return line[len(STAMP_HEADER):].strip()
                if not line.startswith("//"):
                    break
    except OSError:
        return ""
    return ""


def check() -> int:
    if not os.path.exists(TARGET):
        print(f"missing: {TARGET}", file=sys.stderr)
        return 1
    with open(TARGET, encoding="utf-8") as f:
        text = f.read()
    taken = snapshot_date(TARGET) or "unknown"
    print(f"{TARGET}\n  rules: {rule_count(text)}\n  taken: {taken}")
    if taken != "unknown":
        try:
            # The stamp is a plain date, so parsing it yields a naive datetime;
            # subtracting that from an aware one raises rather than comparing.
            when = datetime.fromisoformat(taken).replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - when).days
            print(f"  age:   {age} days")
            if age > 365:
                print("  a year old; new platform suffixes are missing",
                      file=sys.stderr)
        except ValueError:
            pass
    return 0


def refresh() -> int:
    sys.path.insert(0, os.path.join(SKILL_DIR, "scripts"))
    from lib.safe_http import safe_get

    print(f"fetching {SOURCE}", file=sys.stderr)
    text = safe_get(SOURCE, timeout=30, max_response_bytes=8 * 1024 * 1024).text
    count = rule_count(text)
    if count < MIN_RULES:
        print(f"refusing to write: {count} rules, expected at least {MIN_RULES}. "
              f"The download is not a public suffix list.", file=sys.stderr)
        return 1

    today = datetime.now(timezone.utc).date().isoformat()
    header = (f"// Public Suffix List, bundled with seo-checklist.\n"
              f"// Source: {SOURCE}\n"
              f"// Licence: Mozilla Public License 2.0 — see CREDITS.md\n"
              f"{STAMP_HEADER}{today}\n"
              f"// Refresh with: python3 tools/refresh_public_suffix_list.py\n")
    os.makedirs(os.path.dirname(TARGET), exist_ok=True)
    with open(TARGET, "w", encoding="utf-8") as f:
        f.write(header + text)
    print(f"wrote {TARGET}: {count} rules, snapshot {today}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true",
                    help="report the bundled snapshot's size and age, download nothing")
    a = ap.parse_args()
    return check() if a.check else refresh()


if __name__ == "__main__":
    from utf8_streams import utf8_streams
    utf8_streams()
    sys.exit(main())
