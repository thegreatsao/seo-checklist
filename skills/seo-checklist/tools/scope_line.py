"""How a passing audit closes: what it established, and what it did not.

`openspec/specs/governance/` GOV-6. Every `tools/audit_*.py` declares the two sentences
as `ESTABLISHES` and `DOES_NOT_ESTABLISH` and prints them through here as the last thing
on a passing run, so a green CI step ends on what it did not check rather than on a
count. `tests/test_audit_scope.py` holds the format, the sentences and the placement.
"""


def print_scope(establishes: str, does_not_establish: str) -> None:
    print()
    print(f"establishes: {establishes}")
    print(f"does not establish: {does_not_establish}")
