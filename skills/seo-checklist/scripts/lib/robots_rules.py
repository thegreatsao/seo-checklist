"""Match robots.txt rules in one place so evidence checks and the polite HTTP client
give the same answer. A local implementation avoids Python-version differences and
RFC 9309 mismatches while keeping every supported interpreter consistent.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit


_PRODUCT_TOKEN = re.compile(r"[A-Za-z_-]+")
_PERCENT_ESCAPE = re.compile(r"%([0-9A-Fa-f]{2})")
_UNRESERVED = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
)


def product_token(value: str) -> str:
    """Return the RFC product token used to select a robots.txt group."""
    stripped = value.strip()
    if stripped.startswith("*"):
        return "*"
    match = _PRODUCT_TOKEN.match(stripped)
    return match.group(0).lower() if match else ""


def parse(text: str) -> dict:
    """Parse the directives needed for group selection and rule matching."""
    source = text or ""
    if source.startswith("\ufeff"):
        source = source[1:]
    groups: list[dict] = []
    sitemaps: list[str] = []
    current: dict | None = None
    for raw_line in re.split(r"\r\n|\r|\n", source):
        line = raw_line.split("#", 1)[0]
        if ":" not in line:
            continue
        raw_name, raw_value = line.split(":", 1)
        name = raw_name.strip().lower()
        value = raw_value.strip()
        if name == "user-agent":
            if current is None or current["rules"]:
                current = {
                    "agents": [],
                    "lines": [],
                    "rules": [],
                    "crawl_delay": None,
                }
                groups.append(current)
            token = product_token(value)
            if token:
                current["agents"].append(token)
            current["lines"].append(value)
        elif name in ("allow", "disallow"):
            if current is not None:
                current["rules"].append((name, value))
        elif name == "crawl-delay":
            if current is None or current["crawl_delay"] is not None:
                continue
            try:
                delay = float(value)
            except ValueError:
                continue
            if delay >= 0:
                current["crawl_delay"] = delay
        elif name == "sitemap":
            sitemaps.append(value)
    return {"groups": groups, "sitemaps": sitemaps}


def group_for(parsed: dict | None, agent: str) -> dict:
    """Select and combine the groups that apply to *agent*."""
    if parsed is None:
        return {"rules": [], "crawl_delay": None, "matched": None}
    token = product_token(agent)
    groups = parsed.get("groups", [])
    selected = [group for group in groups if token in group.get("agents", [])]
    matched = token if selected else None
    if not selected and token.startswith("googlebot-"):
        # Google's documented user-agent precedence: Googlebot-Image
        # and Googlebot-News obey a googlebot group when they have none of their own.
        selected = [group for group in groups
                    if "googlebot" in group.get("agents", [])]
        matched = "googlebot" if selected else None
    if not selected:
        selected = [group for group in groups if "*" in group.get("agents", [])]
        matched = "*" if selected else None
    rules = [rule for group in selected for rule in group.get("rules", [])]
    delay = next((group.get("crawl_delay") for group in selected
                  if group.get("crawl_delay") is not None), None)
    return {"rules": rules, "crawl_delay": delay, "matched": matched}


def _normalise(value: str) -> str:
    encoded = "".join(
        character if character.isascii() and character.isprintable()
        else "".join(f"%{byte:02X}" for byte in character.encode("utf-8"))
        for character in value
    )

    def replace(match: re.Match) -> str:
        byte = int(match.group(1), 16)
        character = chr(byte)
        return character if character in _UNRESERVED else f"%{byte:02X}"

    return _PERCENT_ESCAPE.sub(replace, encoded)


def _matches(pattern: str, target: str) -> bool:
    anchored = pattern.endswith("$")
    body = pattern[:-1] if anchored else pattern
    expression = re.escape(body).replace(r"\*", ".*")
    if anchored:
        expression += "$"
    return re.match(expression, target) is not None


def allowed(parsed: dict | None, url: str, agent: str) -> tuple[bool, str]:
    """Return whether *agent* may fetch *url*, plus the winning-rule evidence."""
    if parsed is None:
        return True, "no robots.txt"
    split = urlsplit(url)
    target = split.path or "/"
    if target == "/robots.txt":
        return True, "robots.txt is always allowed"
    if split.query:
        target += "?" + split.query
    target = _normalise(target)
    matches = []
    for directive, pattern in group_for(parsed, agent)["rules"]:
        if not pattern:
            continue
        normalised = _normalise(pattern)
        if _matches(normalised, target):
            matches.append((len(normalised), directive == "allow", directive, pattern))
    if not matches:
        return True, "no matching rule"
    _, _, directive, pattern = max(matches, key=lambda row: (row[0], row[1]))
    return directive == "allow", f"{directive}: {pattern}"
