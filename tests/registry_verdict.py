"""Registry-backed verdict oracle, independent of the runner's grade function."""
import harness
from checklist_runner import FAIL, NO_DATA, PASS, WARN, evaluate


def registry_rule(item_id: str) -> dict:
    items = {item["id"]: item for item in harness.registry()["items"]}
    return items[item_id]["check"]


def verdict(item_id: str, output: dict) -> str:
    check = registry_rule(item_id)
    ok, _ = evaluate(check["assert"], output)
    if ok is None:
        return NO_DATA
    if ok:
        return PASS
    warn = check.get("warn")
    if warn and evaluate(warn, output)[0]:
        return WARN
    return FAIL
