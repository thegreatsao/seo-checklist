#!/usr/bin/env python3
"""Read an access log and report what crawlers actually did.

Every other script here asks the site a question. This one reads the answer the
site already gave, thousands of times, to somebody else — and that makes it the
only evidence in the registry about **behaviour** rather than **offering**.
`robots_checker.py` says what the site permits; `ai_crawler_policy_matrix.py` says
what it permits AI crawlers; `sitemap_checker.py` says what it advertises. None of
them can say whether Googlebot came, what it got, or how much of its visit was
spent on pages that no longer exist. No amount of fetching can: the fact is in the
past, and the server's log is the only place it is written down.

Same artifact pattern as `cwv_metrics.py` and `rendered_audit.py`: the operator
supplies the file, this reads it, the registry decides. It measures nothing and
fetches nothing.

    python3 server_log_audit.py /var/log/nginx/access.log.gz \\
        --url https://example.com/ --inventory checklist-results-crawl.json

**The log is the one input that cannot be re-derived, and it is also the one that
can most easily be the wrong log.** A log from a CDN edge that never saw a cache
hit, a log covering four vhosts, a log rotated an hour ago — each produces
confident numbers about nothing. So the output leads with what the file itself
says: which format it was read as, how many lines were unparsable, how long a
window it covers, and whether it recorded a User-Agent at all. An audit reading
this has to be able to distrust it.

Formats: Combined Log Format (the Apache/nginx default), Common Log Format, and
JSON lines. `.gz` is read directly, because a log worth analysing has usually been
rotated.

**Common Log Format has no User-Agent field**, and that is not a detail to paper
over — without it, every question here is unanswerable. A log in that format
reports `error` rather than zero bots, because "no crawler visited" and "this file
cannot say which crawlers visited" are opposite findings and the second must never
be printed as the first.
"""
from __future__ import annotations

import argparse
import collections
import gzip
import io
import json
import os
import re
import socket
import sys
from datetime import datetime, timedelta
from urllib.parse import parse_qsl, urlsplit

try:
    import site_crawl
except ImportError:  # pragma: no cover - path shim, as everywhere else here
    from scripts import site_crawl

# ---------------------------------------------------------------------------
# Who is asking
# ---------------------------------------------------------------------------

# Matched as lowercase substrings of the User-Agent. Split by what the answer is
# used for rather than by who runs the crawler: the crawl-budget verdict is about
# search engines, so an AI crawler pulling 10,000 404s is reported and deliberately
# kept out of that number — it is not Google's crawl budget and calling it that
# would put two claims in one figure.
SEARCH_BOTS = {
    "googlebot": "Googlebot",          # also Googlebot-Image/-Video/-News
    "bingbot": "bingbot",
    "yandexbot": "YandexBot",
    "duckduckbot": "DuckDuckBot",
    "baiduspider": "Baiduspider",
    "applebot": "Applebot",
    "seznambot": "SeznamBot",
    "slurp": "Yahoo! Slurp",
    "petalbot": "PetalBot",
}

# Deliberately not in the list above: "AdsBot-Google" and "Mediapartners-Google"
# crawl for ad quality and AdSense, not for the index, and counting their requests
# as crawl budget would mix a spend nobody can act on into a number that is supposed
# to be actionable. They land in `other`, where they are still visible.
#
# `OAI-AdsBot` is absent for the same reason: it fetches the landing page of a ChatGPT
# ad, so its visits measure ad review and not AI-search visibility, and folding them in
# here would inflate a figure read as reach. Whether it is *allowed* is a robots.txt
# question, and `ai_crawler_policy_matrix.py` answers it.
AI_BOTS = {
    "gptbot": "GPTBot",
    "oai-searchbot": "OAI-SearchBot",
    "chatgpt-user": "ChatGPT-User",
    "claudebot": "ClaudeBot",
    "claude-web": "Claude-Web",
    "anthropic-ai": "anthropic-ai",
    "perplexitybot": "PerplexityBot",
    "ccbot": "CCBot",
    "bytespider": "Bytespider",
    "amazonbot": "Amazonbot",
    "meta-externalagent": "meta-externalagent",
    "cohere-ai": "cohere-ai",
    "diffbot": "Diffbot",
    "youbot": "YouBot",
    "timpibot": "Timpibot",
}

# `Google-Extended` and `Applebot-Extended` are **robots.txt tokens and not
# User-Agents** — nothing ever sends them, so matching them here would define a
# crawler that cannot appear and report zero visits from it forever. They belong in
# `ai_crawler_policy_matrix.py`, which reads robots.txt, and they are named here so
# the omission reads as a decision rather than a gap.
NOT_USER_AGENTS = ("google-extended", "applebot-extended")

# A generic crawler signature, for the tail. Not used for any verdict — "something
# automated visited" is not a finding, and a browser preloading pages matches half
# of these. It is here so `bots.other` is a number rather than a shrug.
GENERIC_BOT = re.compile(r"bot\b|crawler|spider|scraper|curl/|wget/|python-requests|"
                         r"headlesschrome|facebookexternalhit|slackbot|"
                         r"whatsapp|telegrambot|semrush|ahrefs|mj12bot|dotbot")


# ---------------------------------------------------------------------------
# Is it really them
# ---------------------------------------------------------------------------

# The domains a search crawler's own addresses reverse-resolve to, as published by the
# operator. Only crawlers with a *documented* rule are here. DuckDuckBot, SeznamBot and
# PetalBot publish address ranges instead of a DNS convention, so a reverse lookup for
# them would either invent a rule or fail every address, and both are worse than saying
# there is no published rule — which is what `no_published_rule` below says.
CRAWLER_DOMAINS = {
    "Googlebot": ("googlebot.com", "google.com"),
    "bingbot": ("search.msn.com",),
    "YandexBot": ("yandex.com", "yandex.ru", "yandex.net"),
    "Baiduspider": ("baidu.com", "baidu.jp"),
    "Applebot": ("applebot.apple.com",),
    "Yahoo! Slurp": ("crawl.yahoo.net",),
}

# basis: convention — 64 distinct addresses per run. Two DNS round trips each, and the
#  number only has to be larger than the address pool a real crawler uses on one site in
#  a week; Googlebot's is a few dozen. Beyond it, addresses are reported as `not_checked`
#  rather than assumed either way.
MAX_VERIFIED_ADDRESSES = 64


class SystemResolver:
    """`socket`, and nothing else. A class so a test can hand in something that does
    not touch the network — which is what keeps this suite offline while the feature
    that needs DNS exists.

    No timeout, and that is not an oversight: `gethostbyaddr` goes through the system
    resolver, which `socket.setdefaulttimeout` does not reach. What bounds this is
    `MAX_VERIFIED_ADDRESSES` and the runner's own per-script timeout.
    """

    @staticmethod
    def reverse(ip: str) -> str:
        return socket.gethostbyaddr(ip)[0]

    @staticmethod
    def forward(host: str) -> list[str]:
        return socket.gethostbyname_ex(host)[2]


class AddressCheck:
    """Reverse-then-forward DNS confirmation of a claimed search crawler.

    Google, Bing and Yandex document the same two-step rule, and the second step is the
    one that matters. A reverse lookup alone trusts whoever controls the PTR record for
    the address, and that is the address's owner — so anybody with a rented block can
    point it at `crawl-203-0-113-1.googlebot.com` and be believed. Confirming that the
    name resolves *back* to the same address closes it, because the forward zone belongs
    to Google.

    Answers, and what each one means:

    * `verified` — reverse and forward agree. It is the crawler it says it is.
    * `forged` — the name is not in the crawler's domain, or does not resolve back.
      Its requests are re-attributed to `other` so they leave the crawl-budget figures.
    * `unresolved` — no PTR record, or DNS failed. **Not treated as forged**: a
      resolver that is down would otherwise turn every crawler on the site into an
      impostor, which is the same failure as reading a third party's outage as a defect
      in the site.
    * `no_published_rule` / `not_checked` — nothing was asked. Same handling as
      `unresolved`, for the same reason.
    """

    def __init__(self, resolver=None, budget: int = MAX_VERIFIED_ADDRESSES):
        self.resolver = resolver or SystemResolver()
        self.budget = budget
        self.cache: dict[tuple[str, str], str] = {}
        self.counts: collections.Counter = collections.Counter()

    def status(self, name: str, ip: str) -> str:
        domains = CRAWLER_DOMAINS.get(name)
        if not domains:
            return "no_published_rule"
        key = (name, ip)
        if key in self.cache:
            return self.cache[key]
        if len(self.cache) >= self.budget:
            return "not_checked"
        verdict = self._resolve(ip, domains)
        self.cache[key] = verdict
        self.counts[verdict] += 1
        return verdict

    def _resolve(self, ip: str, domains: tuple[str, ...]) -> str:
        try:
            host = (self.resolver.reverse(ip) or "").rstrip(".").lower()
        except OSError:
            return "unresolved"
        if not host:
            return "unresolved"
        # On a label boundary, not a substring: `notgooglebot.com` ends with
        # "googlebot.com" and is not Google.
        if not any(host == d or host.endswith("." + d) for d in domains):
            return "forged"
        try:
            addresses = self.resolver.forward(host)
        except OSError:
            return "unresolved"
        return "verified" if ip in addresses else "forged"


def classify_agent(ua: str) -> tuple[str, str]:
    """`(kind, name)` for a User-Agent. Kind is search / ai / other / human.

    "human" means only that nothing here recognised a crawler in the string, which
    is not the same as a person — a User-Agent is a claim the client makes about
    itself and this function is a lookup table, not a verification. See
    `bot_identity` in the output for what that costs.
    """
    low = (ua or "").lower()
    if not low or low == "-":
        return "human", ""
    # Before the search table, and that order is load-bearing:
    # `applebot-extended` contains `applebot`, so substring matching counted a
    # robots.txt token that no client ever sends as Apple's search crawler — and
    # therefore as search crawl budget. Whatever sends this string, it is not the
    # crawler it names, so it goes in `other` where it is visible and decides nothing.
    for token in NOT_USER_AGENTS:
        if token in low:
            return "other", token
    for needle, name in SEARCH_BOTS.items():
        if needle in low:
            return "search", name
    for needle, name in AI_BOTS.items():
        if needle in low:
            return "ai", name
    if GENERIC_BOT.search(low):
        return "other", _other_name(low)
    return "human", ""


def _other_name(low: str) -> str:
    """A short label for an unrecognised crawler, so the tail is readable."""
    match = re.search(r"([a-z0-9._-]*(?:bot|crawler|spider)[a-z0-9._-]*)", low)
    return match.group(1)[:40] if match else "unidentified crawler"


# ---------------------------------------------------------------------------
# Reading the file
# ---------------------------------------------------------------------------

# Combined Log Format:
#   127.0.0.1 - frank [10/Oct/2000:13:55:36 -0700] "GET /a HTTP/1.0" 200 2326
#       "http://ref/" "Mozilla/5.0 ..."
# Common Log Format is the same without the last two fields. One expression reads
# both: the trailing group is optional, and its absence is what tells us the file
# cannot answer anything about crawlers.
_CLF = re.compile(
    r'^(?P<ip>\S+) \S+ \S+ \[(?P<time>[^\]]+)\] '
    r'"(?P<method>[A-Z_]+) (?P<path>\S*) *(?P<proto>[^"]*)" '
    r'(?P<status>\d{3}) (?P<bytes>\S+)'
    r'(?: "(?P<referer>[^"]*)" "(?P<ua>[^"]*)")?'
)

# nginx JSON logs have no agreed key names, so the common spellings are accepted.
# A key this map does not know is a field this script cannot read, and the count of
# lines it could not understand is in the output rather than swallowed.
JSON_KEYS = {
    "path": ("request_uri", "uri", "request", "path", "url"),
    "status": ("status", "response_code", "status_code"),
    "ua": ("http_user_agent", "user_agent", "agent", "useragent"),
    "ip": ("remote_addr", "client_ip", "ip", "remote_ip"),
    "time": ("time_local", "time_iso8601", "timestamp", "time", "@timestamp"),
    "method": ("request_method", "method", "verb"),
}

CLF_TIME = "%d/%b/%Y:%H:%M:%S %z"
# basis: inherited — one million log lines, present at import. CI-018 passes when
#  nothing in `issues` reaches medium, and a log longer than this is read from its
#  first million lines, so the cap decides that verdict. `truncated` already said so
#  and nothing read it until now.
DEFAULT_MAX_LINES = 1_000_000


def _open(path: str):
    if path.endswith(".gz"):
        return io.TextIOWrapper(gzip.open(path, "rb"), encoding="utf-8",
                               errors="replace")
    return open(path, encoding="utf-8", errors="replace")


def _first(row: dict, names: tuple) -> str:
    for name in names:
        if name in row and row[name] not in (None, ""):
            return str(row[name])
    return ""


def parse_json_line(line: str) -> dict | None:
    try:
        row = json.loads(line)
    except ValueError:
        return None
    if not isinstance(row, dict):
        return None
    path = _first(row, JSON_KEYS["path"])
    status = _first(row, JSON_KEYS["status"])
    if not path or not status.isdigit():
        return None
    # Some formats put the whole request line in `request`; take the middle field.
    if " " in path:
        parts = path.split()
        path = parts[1] if len(parts) >= 2 else parts[0]
    # A JSON log either carries one of the User-Agent spellings or it does not;
    # unlike CLF there is no positional field to be missing, so presence of the key
    # is the whole question.
    ua = _first(row, JSON_KEYS["ua"])
    return {"ip": _first(row, JSON_KEYS["ip"]), "path": path,
            "status": int(status), "ua": ua,
            "method": _first(row, JSON_KEYS["method"]) or "GET",
            "time": _first(row, JSON_KEYS["time"]),
            "has_ua_field": any(k in row for k in JSON_KEYS["ua"])}


def parse_clf_line(line: str) -> dict | None:
    match = _CLF.match(line)
    if not match:
        return None
    row = match.groupdict()
    return {"ip": row["ip"], "path": row["path"], "status": int(row["status"]),
            "ua": row["ua"] or "", "method": row["method"],
            "time": row["time"] or "", "has_ua_field": row["ua"] is not None}


def _parse_time(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.strptime(raw, CLF_TIME)
    except ValueError:
        pass
    try:
        # ISO 8601, with or without a zone. `Z` is not accepted by fromisoformat
        # before 3.11 and the floor here is 3.10.
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# What a status code means for a crawl
# ---------------------------------------------------------------------------

# The classification the whole verdict rests on, so it is a table rather than a
# chain of comparisons.
#
# **304 is not waste, and getting that wrong is the obvious way to write this check
# badly.** A conditional request answered "not modified" is the cheapest possible
# exchange: the crawler kept its copy, the server sent no body, and both saved the
# work. Counting it against the site would penalise exactly the behaviour that
# `cache_compression_checker.py` asks for two items away.
def status_class(status: int) -> str:
    if status == 304:
        return "not_modified"
    if 200 <= status < 300:
        return "served"
    if status in (301, 308):
        return "redirect_permanent"
    if 300 <= status < 400:
        return "redirect_temporary"
    if status == 429:
        return "rate_limited"
    if status in (404, 410):
        return "gone"
    if 400 <= status < 500:
        return "client_error"
    return "server_error"


# Spent to no purpose: the crawler asked, and got nothing it could index. Redirects
# are excluded on purpose — a hop costs budget but usually delivers the page, so it
# is reported separately rather than folded into a number called waste.
WASTED = ("gone", "client_error", "server_error", "rate_limited")

# Thresholds, and what each rests on. §2 of KNOWN-ISSUES.md is about numbers nobody
# justified, so these say plainly what they are: **conventions, not measurements.**
# None is calibrated against a corpus of real sites, because no such corpus was
# available to calibrate against. What makes them usable is that they are round,
# they are stated here, and every figure they judge is in the output beside them —
# so a reader who disagrees can see the measurement and substitute their own number
# instead of arguing with a verdict whose basis is invisible.
# basis: convention — a fifth of the crawl returning nothing indexable. Round, and not
#  calibrated against a corpus of real logs, because none was available
WASTE_HIGH_PCT = 20.0      # a fifth of the crawl returning nothing indexable
# basis: convention — 5%, the point below which a handful of 404s is ordinary rather
#  than a pattern. Same standing as WASTE_HIGH_PCT above
WASTE_WARN_PCT = 5.0
# basis: convention — a fifth of the crawl spent on hops rather than pages
REDIRECT_WARN_PCT = 20.0   # a fifth of the crawl spent on hops
# basis: convention — 1%. Deliberately low, because a page that answers 5xx to a crawler
#  often enough gets dropped from the index — but any 5xx at all is still reported, at
#  medium, so the low bar does not become the only bar
SERVER_ERROR_HIGH_PCT = 1.0
# basis: convention — 50 requests. Below it a percentage is arithmetic rather than
#  evidence: three requests and one 404 is not '33% waste'
MIN_REQUESTS_FOR_RATES = 50
# basis: convention — 7 days. Google revisits an important page within days and a deep
#  one within weeks, so below a week 'never crawled' and 'not crawled yet' are the same
#  observation. The number is a convention; the refusal to answer below it is not
MIN_DAYS_FOR_COVERAGE = 7
TOP_N = 20


# ---------------------------------------------------------------------------
# Cross-referencing the crawl inventory
# ---------------------------------------------------------------------------

def _inventory_facts(path: str) -> dict:
    """What the site offers, from the shared crawl — or empty when unavailable.

    Composed rather than re-crawled: `site_crawl.py` already wrote down which URLs
    the sitemap lists, which pages exist, and which paths robots.txt refuses. The
    log says what crawlers did with them, and every interesting finding here is in
    the difference between the two.
    """
    try:
        inv = site_crawl.load(os.path.expanduser(path))
    except (OSError, ValueError) as exc:
        # `load` also refuses an inventory whose version it does not know, which is
        # the answer that matters: a file of the wrong shape read leniently gives
        # empty sets, and empty sets here mean "the site offers nothing", which
        # would turn every crawled URL into a finding.
        return {"error": f"inventory unreadable: {exc}"}
    pages = inv.get("pages") or {}
    return {
        "site": inv.get("site") or "",
        "known": {_key(u) for u in pages},
        "sitemap": {_key(u) for u in site_crawl.sitemap_urls(inv)},
        "robots_refused": {_key(u) for u in site_crawl.robots_refused(inv)},
        "html": {_key(u) for u, p in pages.items()
                 if isinstance(p, dict) and p.get("status") == 200},
    }


def _key(url: str) -> str:
    """A URL reduced to the path a log line would carry. Query dropped.

    Matches `site_crawl.page_key`'s treatment on purpose: the two have to agree
    about what one page is, or the set arithmetic below compares two vocabularies
    and reports the difference between them as a finding about the site.
    """
    parsed = urlsplit(url)
    path = parsed.path or "/"
    return path if path == "/" else path.rstrip("/")


def _log_key(path: str) -> str:
    return _key(urlsplit(path).path or "/")


# ---------------------------------------------------------------------------
# The audit
# ---------------------------------------------------------------------------

def audit(log_path: str, inventory_path: str = "", base_url: str = "",
          max_lines: int = DEFAULT_MAX_LINES, checker: "AddressCheck | None" = None
          ) -> dict:
    result = {
        "log_file": log_path,
        "base_url": base_url,
        "format": "unknown",
        "lines_read": 0,
        "lines_parsed": 0,
        "lines_unparsed": 0,
        "truncated": False,
        # Why, when there is a why. Declared here rather than only where it is set,
        # so a reader of the output shape sees it exists on every run.
        "truncated_reason": "",
        "user_agent_recorded": None,
        "window": {"first": None, "last": None, "days": None},
        "bot_identity": "claimed, not verified — a User-Agent is what the client "
                        "says it is; confirming Googlebot needs a reverse DNS "
                        "lookup, which --verify-bots makes and this run did not",
        "address_checks": {},
        "bots": {},
        "by_status_class": {},
        "search": {},
        "ai": {},
        "top_wasted": [],
        "top_crawled": [],
        "parameters": [],
        "never_crawled": None,
        "crawled_not_offered": None,
        "robots_disallowed_hits": [],
        "summary": {},
        "issues": [],
        "error": None,
    }

    if not os.path.exists(os.path.expanduser(log_path)):
        result["error"] = f"no such log file: {log_path}"
        return result

    counts: dict[str, collections.Counter] = collections.defaultdict(
        collections.Counter)
    address_checks: dict[str, collections.Counter] = collections.defaultdict(
        collections.Counter)
    per_bot: dict[str, dict] = {}
    wasted: collections.Counter = collections.Counter()
    crawled: collections.Counter = collections.Counter()
    params: collections.Counter = collections.Counter()
    search_paths: set[str] = set()
    ua_seen_field = False
    ua_missing_field = False
    first_at = last_at = None

    try:
        with _open(os.path.expanduser(log_path)) as fh:
            for line in fh:
                if result["lines_read"] >= max_lines:
                    result["truncated"] = True
                    break
                line = line.strip()
                result["lines_read"] += 1
                if not line:
                    continue
                row = parse_json_line(line) if line[:1] == "{" else parse_clf_line(line)
                if row is None:
                    result["lines_unparsed"] += 1
                    continue
                if result["format"] == "unknown":
                    result["format"] = "json" if line[:1] == "{" else (
                        "combined" if row["has_ua_field"] else "common")
                result["lines_parsed"] += 1
                if row["has_ua_field"]:
                    ua_seen_field = True
                else:
                    ua_missing_field = True

                when = _parse_time(row["time"])
                if when is not None:
                    if first_at is None or when < first_at:
                        first_at = when
                    if last_at is None or when > last_at:
                        last_at = when

                kind, name = classify_agent(row["ua"])
                if checker is not None and kind == "search" and row["ip"]:
                    verdict = checker.status(name, row["ip"])
                    address_checks[name][verdict] += 1
                    if verdict == "forged":
                        # Re-attributed rather than annotated. The whole cost of an
                        # unverified identity was that a scraper's 404s counted as
                        # Google's crawl budget, and leaving the requests in `search`
                        # with a note beside them would leave that number wrong.
                        kind, name = "other", f"{name} (address not confirmed)"
                klass = status_class(row["status"])
                counts["all"][klass] += 1
                counts[kind][klass] += 1
                if kind == "human":
                    continue

                label = name or "unidentified crawler"
                bucket = per_bot.setdefault(
                    label, {"kind": kind, "requests": 0, "ips": set(),
                            "by_status_class": collections.Counter()})
                bucket["requests"] += 1
                bucket["by_status_class"][klass] += 1
                if row["ip"]:
                    bucket["ips"].add(row["ip"])

                if kind != "search":
                    continue
                key = _log_key(row["path"])
                search_paths.add(key)
                crawled[key] += 1
                if klass in WASTED:
                    wasted[(key, row["status"])] += 1
                query = urlsplit(row["path"]).query
                for param, _value in parse_qsl(query, keep_blank_values=True):
                    params[param] += 1
    except OSError as exc:
        result["error"] = f"could not read {log_path}: {exc}"
        return result

    if not result["lines_parsed"]:
        result["error"] = (
            f"nothing in {os.path.basename(log_path)} parsed as an access log "
            f"({result['lines_read']} line(s) read). Supported: Combined Log "
            f"Format, Common Log Format, JSON lines")
        return result

    result["user_agent_recorded"] = ua_seen_field
    if not ua_seen_field:
        # The whole point of the file, absent. Reported as an error rather than as
        # zero crawlers: "no bot visited this site" and "this log cannot say" are
        # opposite findings, and printing the second as the first is the exact
        # failure this tool exists to refuse.
        result["error"] = (
            "this log records no User-Agent, so it cannot say which crawlers "
            "visited — it looks like Common Log Format. Reconfigure the server to "
            "log combined format and re-run once it has a week of data")
        return result
    if ua_missing_field:
        result["issues"].append({
            "severity": "low", "type": "mixed_format",
            "message": "some lines carry no User-Agent field; those requests are "
                       "counted in the totals but attributed to no crawler"})

    if checker is not None:
        result["address_checks"] = {name: dict(c) for name, c in
                                    sorted(address_checks.items())}
        tally = checker.counts
        result["bot_identity"] = (
            f"confirmed by reverse-then-forward DNS: {tally['verified']} address(es) "
            f"verified, {tally['forged']} not the crawler they claimed, "
            f"{tally['unresolved']} with no usable PTR record. A crawler with no "
            f"published DNS rule, and any address beyond the "
            f"{checker.budget}-address budget, is still a claim")
        forged = sum(c.get("forged", 0) for c in address_checks.values())
        if forged:
            result["issues"].append({
                "severity": "medium", "type": "forged_crawler",
                "message": f"{forged} request(s) claimed to be a search crawler from "
                           f"address(es) that are not — re-attributed to 'other', so "
                           f"the crawl-budget figures above exclude them"})

    _window(result, first_at, last_at)
    result["by_status_class"] = dict(counts["all"])
    result["bots"] = {
        label: {"kind": b["kind"], "requests": b["requests"],
                "distinct_ips": len(b["ips"]),
                "by_status_class": dict(b["by_status_class"])}
        for label, b in sorted(per_bot.items(),
                               key=lambda kv: -kv[1]["requests"])}
    result["search"] = dict(counts["search"])
    result["ai"] = dict(counts["ai"])
    result["top_crawled"] = [{"path": p, "hits": n}
                             for p, n in crawled.most_common(TOP_N)]
    result["top_wasted"] = [{"path": p, "status": s, "hits": n}
                            for (p, s), n in wasted.most_common(TOP_N)]
    result["parameters"] = [{"parameter": p, "hits": n}
                            for p, n in params.most_common(TOP_N)]

    if inventory_path:
        _compare_with_inventory(result, inventory_path, search_paths, crawled)

    _rates(result, len(search_paths))
    _findings(result)
    return result


# A caveat is not a finding about the site, and it must not read as one.
#
# Every branch below declines to report something — which is right, and is what
# `openspec/specs/evidence/` EVD-9 asks for: an absence over three days of logs is a
# statement about the log. What EVD-9 does not say is what the *verdict* should then
# be, and CI-018 passes by finding nothing at medium or above. So an analysis that
# never ran and a site with nothing wrong produced the identical `PASS`.
#
# `truncated` is the runner's name for "this answer does not cover its subject", and
# it already meant exactly that here for the line cap — `DEFAULT_MAX_LINES` says so in
# its own basis line. The runner turns a pass-by-absence over a truncated input into
# `NO_DATA` (`openspec/specs/verdicts/` VRD-14), which is the honest answer: the item
# applies, and this log could not settle it.
#
# Which caveats belong here is derived from `_findings`, not chosen: a caveat marks
# the answer incomplete when it suppresses a finding that could otherwise have reached
# the severity CI-018's rule reads.
#
#   no_timestamps        -> the window is unknown, so window_too_short follows
#   window_too_short     -> sitemap_urls_never_crawled (medium) cannot be raised
#   inventory_unreadable -> that one and disallowed_paths_crawled (medium)
#   too_few_requests     -> crawl_budget_wasted, server_errors_to_crawlers and
#                           crawl_spent_on_redirects, all medium or high
#
# `mixed_format` is deliberately not here: unattributed requests move the totals but
# suppress no finding outright, and a log whose sample fell below the rate floor says
# so through `too_few_requests` already.
def _incomplete(result: dict, kind: str, message: str) -> None:
    """Record a caveat, and say the answer no longer covers its whole subject.

    The reason travels with the flag. The runner's withheld-verdict sentence used to
    say "what the cap left out" unconditionally, which is a true description of a
    line cap and a false one of a three-day window — and it is the sentence the
    operator reads under a `NO_DATA`. Every caveat that reaches here is already a
    plain-English explanation, so it is the reason, verbatim.
    """
    result["issues"].append({"severity": "low", "type": kind, "message": message})
    result["truncated"] = True
    said = result.get("truncated_reason") or ""
    result["truncated_reason"] = f"{said}; {message}" if said else message


def _window(result: dict, first_at, last_at) -> None:
    if first_at is None or last_at is None:
        _incomplete(result, "no_timestamps",
                    "no line carried a timestamp this script could read, so "
                    "the window is unknown and rates per day are not reported")
        return
    span = last_at - first_at
    result["window"] = {
        "first": first_at.isoformat(), "last": last_at.isoformat(),
        # Rounded up, so a log covering part of a day is one day rather than zero:
        # dividing by zero days is how a request count becomes infinity per day.
        "days": max(1, -(-span // timedelta(days=1)))}


def _compare_with_inventory(result: dict, inventory_path: str,
                            search_paths: set, crawled) -> None:
    """The three findings that need both halves: the log and what the site offers."""
    facts = _inventory_facts(inventory_path)
    if facts.get("error"):
        _incomplete(result, "inventory_unreadable",
                    f"{facts['error']}; the log was read on its own, so "
                    f"never-crawled and unoffered-URL findings are absent")
        return

    hits = [{"path": p, "hits": crawled[p]}
            for p in sorted(facts["robots_refused"] & search_paths)]
    result["robots_disallowed_hits"] = hits

    days = result["window"]["days"]
    if not days or days < MIN_DAYS_FOR_COVERAGE:
        # Left as None rather than as an empty list, because an empty list reads as
        # "we looked and there were none". A one-day log would otherwise report
        # every URL on the site as never crawled.
        _incomplete(result, "window_too_short",
                    f"the log covers {days or 'an unknown number of'} day(s); "
                    f"coverage findings need at least {MIN_DAYS_FOR_COVERAGE} "
                    f"days, because below that 'never crawled' and 'not crawled "
                    f"yet' are the same thing")
        return

    never = sorted(facts["sitemap"] - search_paths - facts["robots_refused"])
    result["never_crawled"] = [{"path": p} for p in never[:TOP_N]]
    result["summary"]["never_crawled_count"] = len(never)

    unoffered = sorted(search_paths - facts["known"] - facts["sitemap"])
    result["crawled_not_offered"] = [{"path": p, "hits": crawled[p]}
                                     for p in unoffered[:TOP_N]]
    result["summary"]["crawled_not_offered_count"] = len(unoffered)


def _rates(result: dict, distinct_urls: int) -> None:
    search = result["search"]
    total = sum(search.values())
    wasted = sum(search.get(k, 0) for k in WASTED)
    redirects = search.get("redirect_permanent", 0) + search.get(
        "redirect_temporary", 0)
    days = result["window"]["days"]
    summary = result["summary"]
    summary.update({
        "search_bot_requests": total,
        "ai_bot_requests": sum(result["ai"].values()),
        "search_bot_urls": distinct_urls,
        "wasted_requests": wasted,
        "redirect_requests": redirects,
        "not_modified_requests": search.get("not_modified", 0),
        "server_error_requests": search.get("server_error", 0),
        "robots_disallowed_hits": len(result["robots_disallowed_hits"]),
        "days": days,
    })
    # `rates_meaningful` is the gate every percentage below sits behind, and it is a
    # field rather than a silence so a registry rule can read it.
    summary["rates_meaningful"] = total >= MIN_REQUESTS_FOR_RATES
    if summary["rates_meaningful"]:
        summary["wasted_pct"] = round(100.0 * wasted / total, 1)
        summary["redirect_pct"] = round(100.0 * redirects / total, 1)
        summary["server_error_pct"] = round(
            100.0 * search.get("server_error", 0) / total, 1)
    if days:
        summary["search_requests_per_day"] = round(total / days, 1)


def _findings(result: dict) -> None:
    issues = result["issues"]
    summary = result["summary"]
    total = summary.get("search_bot_requests", 0)

    if not total:
        issues.append({
            "severity": "medium", "type": "no_search_bot_traffic",
            "message": "no search-engine crawler appears in this log. Either the "
                       "window predates discovery, the log is from a host or vhost "
                       "the crawlers do not reach, or the site is not being "
                       "crawled — the three need different fixes, so check which "
                       "before acting"})
        return

    if not summary.get("rates_meaningful"):
        _incomplete(result, "too_few_requests",
                    f"{total} search-bot request(s) is too few to express as "
                    f"percentages, so shares are omitted; the counts stand")
    else:
        waste = summary["wasted_pct"]
        if waste >= WASTE_HIGH_PCT:
            issues.append({
                "severity": "high", "type": "crawl_budget_wasted",
                "message": f"{waste}% of search-bot requests returned nothing "
                           f"indexable ({summary['wasted_requests']} of {total}). "
                           f"See top_wasted for where it went"})
        elif waste >= WASTE_WARN_PCT:
            issues.append({
                "severity": "medium", "type": "crawl_budget_wasted",
                "message": f"{waste}% of search-bot requests returned nothing "
                           f"indexable ({summary['wasted_requests']} of {total})"})
        if summary["server_error_pct"] >= SERVER_ERROR_HIGH_PCT:
            issues.append({
                "severity": "high", "type": "server_errors_to_crawlers",
                "message": f"{summary['server_error_requests']} request(s) from "
                           f"search crawlers got a 5xx "
                           f"({summary['server_error_pct']}%). A page that answers "
                           f"5xx often enough gets dropped from the index"})
        elif summary["server_error_requests"]:
            issues.append({
                "severity": "medium", "type": "server_errors_to_crawlers",
                "message": f"{summary['server_error_requests']} request(s) from "
                           f"search crawlers got a 5xx"})
        if summary["redirect_pct"] >= REDIRECT_WARN_PCT:
            issues.append({
                "severity": "medium", "type": "crawl_spent_on_redirects",
                "message": f"{summary['redirect_pct']}% of search-bot requests "
                           f"were answered with a redirect. Link and list the "
                           f"destinations directly"})

    if result["robots_disallowed_hits"]:
        issues.append({
            "severity": "medium", "type": "disallowed_paths_crawled",
            "message": f"search crawlers requested "
                       f"{len(result['robots_disallowed_hits'])} path(s) robots.txt "
                       f"disallows. Either the rule arrived after they were "
                       f"discovered, or something links to them, or the crawler is "
                       f"not the one it claims to be"})

    never = summary.get("never_crawled_count")
    if never:
        issues.append({
            "severity": "medium", "type": "sitemap_urls_never_crawled",
            "message": f"{never} URL(s) in the sitemap were never requested by a "
                       f"search crawler in {summary.get('days')} day(s). A page no "
                       f"crawler visits cannot rank"})
    unoffered = summary.get("crawled_not_offered_count")
    if unoffered:
        issues.append({
            "severity": "low", "type": "crawled_not_offered",
            "message": f"crawlers requested {unoffered} URL(s) the crawl found "
                       f"neither linked nor in the sitemap — old URLs, external "
                       f"links, or pages reachable only from outside the site"})

    params = result["parameters"]
    if params and total and params[0]["hits"] >= max(10, total * 0.1):
        issues.append({
            "severity": "medium", "type": "parameter_crawl",
            "message": f"?{params[0]['parameter']} accounts for "
                       f"{params[0]['hits']} search-bot request(s). Parameterised "
                       f"URLs multiply the crawl without adding pages; canonicalise "
                       f"or disallow them"})


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Report what crawlers did, from a server access log",
        epilog=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("log", help="access log; .gz is read directly")
    ap.add_argument("--url", default="", help="the site the log belongs to, "
                                             "recorded in the output")
    ap.add_argument("--inventory", default="", help="crawl inventory from "
                                                    "site_crawl.py, for the "
                                                    "never-crawled comparison")
    ap.add_argument("--max-lines", type=int, default=DEFAULT_MAX_LINES,
                    help=f"stop after N lines (default {DEFAULT_MAX_LINES}); "
                         f"truncation is reported in the output")
    ap.add_argument("--verify-bots", action="store_true",
                    help="confirm each claimed search crawler by reverse-then-forward "
                         "DNS. Off by default: it is the only network call this script "
                         "makes, and a run without it reports crawler identity as the "
                         "claim it is. Requests from an address that fails the check "
                         "are re-attributed out of the crawl-budget figures")
    ap.add_argument("--json", "-j", action="store_true")
    a = ap.parse_args()

    result = audit(a.log, a.inventory, a.url, a.max_lines,
                   checker=AddressCheck() if a.verify_bots else None)

    if a.json:
        print(json.dumps(result, indent=2))
        return 0

    if result["error"]:
        print(f"Cannot report on {a.log}:\n  {result['error']}", file=sys.stderr)
        return 1
    w = result["window"]
    print(f"Access log: {result['log_file']} ({result['format']})")
    print(f"  {result['lines_parsed']} line(s) parsed, "
          f"{result['lines_unparsed']} unreadable"
          f"{', truncated' if result['truncated'] else ''}")
    print(f"  window: {w['first']} to {w['last']} ({w['days']} day(s))")
    s = result["summary"]
    print(f"  search crawlers: {s.get('search_bot_requests', 0)} request(s) "
          f"across {s.get('search_bot_urls', 0)} URL(s)")
    if s.get("rates_meaningful"):
        print(f"    wasted {s['wasted_pct']}% · redirects {s['redirect_pct']}% · "
              f"304s {s.get('not_modified_requests', 0)}")
    print(f"  AI crawlers: {s.get('ai_bot_requests', 0)} request(s)")
    for label, b in list(result["bots"].items())[:8]:
        print(f"    {label:24} {b['requests']:>7}  ({b['kind']}, "
              f"{b['distinct_ips']} IP(s))")
    for issue in result["issues"]:
        print(f"  [{issue['severity']}] {issue['message']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
