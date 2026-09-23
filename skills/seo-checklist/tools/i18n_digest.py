#!/usr/bin/env python3
"""Bind each translation to the English text it was written against.

The parity tests in `test_report.py` check that every item has a Russian title and
fix, that neither is blank, and that each contains Cyrillic. All three stayed green
through 0.20 while SE-118's English fix changed and its Russian one did not, because
a sentence that has quietly stopped describing the English one is still Russian,
still present and still non-blank. **Presence is not parity.** The class's own
docstring had predicted it — *"a second copy drifts the moment either side
changes"* — and then tested for presence.

What that test could not see, this makes visible: a digest of the English `(title,
fix)` pair, or `(title, fix, measures)` triple for an item that qualifies what its
rule checks, stored beside the translation. Change the English and the digest no
longer matches, so the build fails and names the item. Re-run without `--check` once
the translation has actually been revisited.

The digest is deliberately not of the *translation*. A translator improving Russian
wording should not have to touch anything here; only a change on the English side is
a reason to re-read the Russian.

    python tools/i18n_digest.py --check    # exit 1 and name every drifted item
    python tools/i18n_digest.py            # stamp the current English, after review
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
REGISTRY = SKILL / "resources/config/checklist.json"
I18N = SKILL / "resources/i18n"

# The key the digests live under. Leading underscore so it sorts with `_comment` and
# reads as metadata rather than as a fifth translated surface.
KEY = "_source_digests"


def digest(title: str, fix: str, measures: str | None = None) -> str:
    """12 hex chars over the English pair or measures-bearing triple, unit-separated.

    Separated rather than concatenated: without it, moving a word from the end of a
    title to the start of a fix would leave the digest unchanged, which is exactly
    the kind of edit that makes a translation wrong.
    """
    parts = [title, fix]
    if measures is not None:
        parts.append(measures)
    raw = "\x1f".join(parts).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:12]


def english() -> dict[str, str]:
    items = json.loads(REGISTRY.read_text(encoding="utf-8"))["items"]
    return {i["id"]: digest(i.get("title", ""), i.get("fix", ""), i.get("measures"))
            for i in items}


def catalogues() -> list[Path]:
    return sorted(p for p in I18N.glob("*.json") if p.stem != "en")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="exit 1 on drift instead of stamping it")
    args = ap.parse_args()

    want = english()
    drifted: list[str] = []

    for path in catalogues():
        data = json.loads(path.read_text(encoding="utf-8"))
        have = data.get(KEY) or {}
        lang = data.get("lang", path.stem)

        for item_id, expected in sorted(want.items()):
            if have.get(item_id) != expected:
                # An item with no digest at all is drift too, not a fresh start: it
                # means a translation was added without recording what it translated.
                drifted.append(f"{lang}/{item_id}"
                               + ("" if item_id in have else " (never stamped)"))

        stale = sorted(set(have) - set(want))
        drifted.extend(f"{lang}/{i} (translates an id the registry dropped)"
                       for i in stale)

        if not args.check:
            data[KEY] = want
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")

    if args.check and drifted:
        print(f"{len(drifted)} translation(s) no longer match the English they were "
              f"written against:")
        for row in drifted[:40]:
            print(f"  {row}")
        if len(drifted) > 40:
            print(f"  ... and {len(drifted) - 40} more")
        print("\nRe-read each Russian string against the current English, then run "
              "this without --check to stamp them.")
        return 1

    if args.check:
        print(f"{len(want)} items - every translation matches its English source")
    else:
        print(f"stamped {len(want)} items across "
              f"{len(catalogues())} catalogue(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
