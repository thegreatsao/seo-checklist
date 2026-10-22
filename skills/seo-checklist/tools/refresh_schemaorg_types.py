#!/usr/bin/env python3
"""Refresh the bundled schema.org type hierarchy from one named release.

Bundled rather than fetched at audit time for the reason the Public Suffix List is:
a run must give the same answer offline and next month. The checks that decide by a
type's ancestry (`lib/schema_types.py`: LocalBusiness, Organization, Place) derive
their sets from this file, so a release is taken deliberately and the file says which.

    python3 tools/refresh_schemaorg_types.py 30.1     # download that release and replace
    python3 tools/refresh_schemaorg_types.py --check  # print what the snapshot is

A type is a node with `rdfs:subClassOf` or `@type` `rdfs:Class`. The first half is
not redundant: an enumeration member such as `Dermatology` is typed
`MedicalSpecialty` and is also a subclass of `MedicalBusiness`, and schema.org lists
it among that type's subtypes. Since 30.0 the release also declares other
vocabularies' classes (`gs1:Organization`, `fibo-…`) for its equivalence annotations;
they are not schema.org types and are left out.
"""
from __future__ import annotations

import python_floor  # noqa: F401

import argparse
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
TARGET = os.path.join(SKILL_DIR, "resources", "config", "schemaorg-types.json")
SOURCE = "https://schema.org/version/{release}/schemaorg-current-https.jsonld"

# Below this the download is not the vocabulary (30.1 has 1038).
MIN_TYPES = 800


def hierarchy(graph: list) -> dict[str, list[str]]:
    """`{type: [parent, ...]}` for every schema.org type in a release's graph."""
    out = {}
    for node in graph:
        kinds = node.get("@type")
        kinds = kinds if isinstance(kinds, list) else [kinds]
        if ("rdfs:Class" not in kinds and "rdfs:subClassOf" not in node
                or not node["@id"].startswith("schema:")):
            continue
        parents = node.get("rdfs:subClassOf") or []
        parents = parents if isinstance(parents, list) else [parents]
        out[node["@id"].removeprefix("schema:")] = sorted(
            p["@id"].removeprefix("schema:") for p in parents
            if p.get("@id", "").startswith("schema:"))
    return dict(sorted(out.items()))


def refresh(release: str, date: str) -> int:
    sys.path.insert(0, os.path.join(SKILL_DIR, "scripts"))
    from lib.safe_http import safe_get
    url = SOURCE.format(release=release)
    response = safe_get(url, timeout=60)
    body = response.content
    types = hierarchy(json.loads(body)["@graph"])
    if len(types) < MIN_TYPES:
        print(f"{url} gave {len(types)} types; not replacing the snapshot",
              file=sys.stderr)
        return 1
    snapshot = {"release": release, "date": date, "source": url,
                "sha256": hashlib.sha256(body).hexdigest(), "types": types}
    with open(TARGET, "w", encoding="utf-8") as stream:
        json.dump(snapshot, stream, indent=0, ensure_ascii=False)
        stream.write("\n")
    print(f"wrote {TARGET}: release {release}, {len(types)} types")
    return 0


def check() -> int:
    with open(TARGET, encoding="utf-8") as stream:
        snapshot = json.load(stream)
    print(f"{TARGET}\n  release: {snapshot['release']} ({snapshot['date']})\n"
          f"  source:  {snapshot['source']}\n  types:   {len(snapshot['types'])}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("release", nargs="?", help="schema.org release, e.g. 30.1")
    parser.add_argument("--date", help="the release's date on schema.org/docs/releases.html")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check or not args.release:
        return check()
    if not args.date:
        parser.error("--date is required: the release notes give it, the file does not")
    return refresh(args.release, args.date)


if __name__ == "__main__":
    from utf8_streams import utf8_streams
    utf8_streams()
    raise SystemExit(main())
