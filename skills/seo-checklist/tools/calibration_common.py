"""Pure helpers for calibration tools; no runtime-script imports."""
import ast


def literal_constants(path, names, missing_message, *, first=False):
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=path)
    values = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if (isinstance(target, ast.Name) and target.id in names
                and (not first or target.id not in values)):
            values[target.id] = ast.literal_eval(node.value)
    missing = names - values.keys()
    if missing:
        raise RuntimeError(missing_message.format(missing=sorted(missing)))
    return values


def percentile(values: list[float], fraction: float) -> float:
    """Linearly interpolated percentile, including both endpoints."""
    ordered = sorted(values)
    if not ordered:
        raise ValueError("a distribution cannot be computed from no observations")
    position = (len(ordered) - 1) * fraction
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    weight = position - low
    return ordered[low] * (1 - weight) + ordered[high] * weight
