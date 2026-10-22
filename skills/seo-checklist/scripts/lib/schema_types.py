"""Shared schema.org type hierarchy used by entity and local-SEO checks."""

from __future__ import annotations


import json
import os

# schema.org's type hierarchy at one named release, bundled so a run gives the same
# answer offline; `tools/refresh_schemaorg_types.py` replaces it and says which
# release it took. The sets below are derived from it: until F04 (batch 4b)
# `LOCAL_BUSINESS_TYPES` was a hand copy that lacked 31 of the 152 types — Hospital,
# Attorney, PostOffice among them — and carried two that are not LocalBusiness.
# A type newer than the release remains unknown rather than guessed from its spelling.
SNAPSHOT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "resources", "config", "schemaorg-types.json")
with open(SNAPSHOT_PATH, encoding="utf-8") as _stream:
    SNAPSHOT = json.load(_stream)


def descendants(root: str) -> frozenset[str]:
    """`root` and every type that has it as an ancestor in the snapshot."""
    children: dict[str, list[str]] = {}
    for name, parents in SNAPSHOT["types"].items():
        for parent in parents:
            children.setdefault(parent, []).append(name)
    found, todo = set(), [root]
    while todo:
        name = todo.pop()
        if name not in found:
            found.add(name)
            todo.extend(children.get(name, ()))
    return frozenset(found)


LOCAL_BUSINESS_TYPES = descendants("LocalBusiness")
ORGANIZATION_TYPES = descendants("Organization")
PLACE_TYPES = descendants("Place")


def schema_types(value) -> list[str]:
    """Return @type as a list of non-empty strings, preserving source order."""
    values = value if isinstance(value, list) else [value]
    return [item for item in values if isinstance(item, str) and item]


def is_local_business_type(value) -> bool:
    """Return whether any supplied @type is LocalBusiness or a known subtype."""
    return bool(LOCAL_BUSINESS_TYPES.intersection(schema_types(value)))
