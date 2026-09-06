#!/usr/bin/env python3
"""Run the checklist registry against a URL and produce per-item statuses.

Coverage is a contract, not a side effect: every item in
resources/config/checklist.json gets a status, and items nobody could answer
are reported as NO_DATA rather than silently dropped.

Each unique (script, args) pair executes exactly once no matter how many
checklist items depend on it — 217 items collapse to 66 process launches.

Usage:
    python3 checklist_runner.py https://example.com
    python3 checklist_runner.py https://example.com --json results.json
    python3 checklist_runner.py https://example.com --diff
    python3 checklist_runner.py https://example.com --only crawling_indexing,speed
"""
from __future__ import annotations

import argparse
import atexit
import hashlib
import ipaddress
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import NamedTuple
from urllib.parse import urljoin, urlparse


# Not every caller is the runner. These scripts print `ensure_ascii=False` JSON, and
# a bare `python gsc_cannibalization.py …` on Windows encodes stdout with the ANSI
# codepage — so a Greek query or a Polish name raises UnicodeEncodeError and the
# script produces nothing at all. The runner now hands its children a UTF-8
# environment; this is the same guarantee for somebody running the script by hand.
def _utf8_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):  # already wrapped, or not a TextIO
            pass


_utf8_stdout()

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)
REGISTRY = os.path.join(SKILL_DIR, "resources", "config", "checklist.json")

sys.path.insert(0, SCRIPT_DIR)


# How an evidence script failed. All four end as NO_DATA — the item is undecided
# either way — but they are not the same problem and the report must not pretend
# they are: a timeout is a run that needed more time, a crash is a defect in the
# script or its arguments. Only one of the two is worth retrying, and a reader
# who cannot tell which one happened cannot know whether to raise --timeout or
# open the script.
# basis: presentation — 120 characters of a requests exception message, cut at a word
#  boundary, and 10 broken URLs listed on the console before the rest are pointed at in
#  the inventory file. Neither number is read before a verdict exists.
ERROR_DETAIL_CHARS = 120
BROKEN_URLS_SHOWN = 10       # basis: presentation — the console listing's length

FAILURE_LABEL = {
    "timeout": "script timed out",
    "crash": "script failed",
    "missing": "script not found",
    "bad_output": "script returned unusable output",
    # A script the operating system killed, which is not the same as a script that
    # failed: nothing in it ran wrong, and opening it will show nothing. See
    # `_signal_failure` for the one cause of this we have actually seen.
    "signal": "script was killed by the operating system",
}


def _signal_failure(script_name: str, signal_number: int, stderr: str) -> dict:
    """A script the OS killed, reported as that rather than as a script defect.

    It used to arrive as `crash` with the message "exit code -11", which sends the
    reader to open a script that never ran a line wrong. The distinction is the same
    one §4.10 drew between a timeout and a crash: all of these end as NO_DATA, and
    they are not the same problem.

    The hint is narrow on purpose — it names the one cause we have diagnosed, and
    only in the exact shape that cause produces (SIGSEGV, on Darwin, with the child
    dying before it could print anything).
    """
    import signal as signal_module
    try:
        name = signal_module.Signals(signal_number).name
    except ValueError:
        name = f"signal {signal_number}"
    hint = ""
    if (signal_number == getattr(signal_module, "SIGSEGV", 11)
            and sys.platform == "darwin" and not stderr):
        hint = ("; on macOS this is usually Apple's Network.framework crashing in a "
                "forked child rather than anything in the script — rerun, and report "
                "it if it persists")
    return {"error": f"[{script_name}] killed by {name}{hint}",
            "error_kind": "signal"}


def run_script(script_name: str, args: list, timeout: int = 120) -> dict:
    """Run an evidence script and capture its JSON output.

    A script that fails is reported, never silently dropped: the caller turns an
    `error` key into NO_DATA with the reason attached, so a broken check is
    visibly undecided rather than quietly absent. `error_kind` travels with it so
    the reason survives into the report — see FAILURE_LABEL.
    """
    script_path = os.path.join(SCRIPT_DIR, script_name)
    if not os.path.exists(script_path):
        return {"error": f"{script_name} is not in {SCRIPT_DIR}",
                "error_kind": "missing"}

    cmd = [sys.executable, script_path] + args + ["--json"]
    try:
        # close_fds=False so CPython takes its `posix_spawn` path instead of
        # `fork` + `exec`, and that is not a micro-optimisation. On macOS, Apple's
        # Network.framework registers a `pthread_atfork` child handler
        # (`nw_settings_child_has_forked`) which dereferences freed state and
        # segfaults *in the child, before exec* once the framework has been
        # initialised in the parent. The runner does its own fetching before
        # spawning 55 scripts, so it is precisely the shape that trips it: every
        # script dies with signal 11, empty output, and a run that reports 55
        # broken scripts. Found in this project's own test suite, where it killed
        # the audits in `tests/test_shapes.py` depending on which module ran first.
        # The cost of the workaround is that a child inherits the parent's open
        # descriptors for the milliseconds before it execs; these children are
        # short-lived and the alternative is losing the evidence layer on one
        # platform.
        # `encoding="utf-8"`, not `text=True` alone. Every evidence script prints
        # `json.dumps(..., ensure_ascii=False)`, which is UTF-8; `text=True` on its
        # own decodes with the *platform's* preferred encoding, and on Windows that
        # is the ANSI codepage. Under cp1252 five bytes have no mapping at all —
        # 0x81, 0x8d, 0x8f, 0x90, 0x9d — and 0x81 is the second byte of Greek ρ
        # (U+03C1, `cf 81`). So a Search Console property serving Greek queries, or
        # any page with a ρ on it, killed `subprocess`'s reader thread with a
        # UnicodeDecodeError, left `result.stdout` as None, and the line below then
        # raised `AttributeError: 'NoneType' object has no attribute 'strip'` — a
        # message naming nothing about encodings, from a script that had run
        # perfectly and written valid JSON.
        #
        # Found on a real audit of a Greek/English site, where four items came back
        # NO_DATA for a defect in the reader. It is not a Greek problem: Cyrillic,
        # CJK and anything else outside Latin-1 hits it the moment one of those five
        # bytes lands in a continuation position. The suite never saw it because
        # every fixture is ASCII.
        # The other half of the same defect, and the worse one: a child's `print`
        # encodes with *its* stdout encoding, which on Windows is the ANSI codepage
        # too. Seven scripts print `ensure_ascii=False` JSON, so on a stock Windows
        # box — no PYTHONIOENCODING set — they cannot emit Greek, Cyrillic or CJK at
        # all: UnicodeEncodeError, exit 1, empty stdout. `site_crawl.py` is one of
        # them, so the whole site-wide layer went with it. Announced through the
        # environment because they are separate processes, the same way `--allow-
        # private` and the pacing slots travel.
        child_env = dict(os.environ, PYTHONIOENCODING="utf-8")
        result = subprocess.run(cmd, capture_output=True, text=True,
                                encoding="utf-8", timeout=timeout, close_fds=False,
                                env=child_env)
        # None, not "", is what a dead reader thread leaves behind, and every branch
        # below used to assume a string. Said once here so a decode failure that
        # survives the line above is reported as itself rather than as whichever
        # attribute happened to be touched first.
        if result.stdout is None or result.stderr is None:
            return {"error": f"[{script_name}] output could not be decoded as UTF-8",
                    "error_kind": "bad_output"}
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout)
        if result.returncode < 0:
            return _signal_failure(script_name, -result.returncode,
                                   result.stderr.strip())
        err_msg = result.stderr.strip() or f"exit code {result.returncode}"
        return {"error": f"[{script_name}] {err_msg}", "error_kind": "crash"}
    except subprocess.TimeoutExpired:
        # Retryable, and worth saying so: the default is a compromise between a
        # slow site and a run that never ends, not a verdict about the site.
        return {"error": f"no result after {timeout}s; retryable with a longer "
                         f"--timeout or fewer --workers",
                "error_kind": "timeout"}
    except json.JSONDecodeError:
        return {"error": f"[{script_name}] stdout is not JSON",
                "error_kind": "bad_output"}
    except Exception as e:  # noqa: BLE001 - surfaced to the caller as NO_DATA
        return {"error": f"[{script_name}] {type(e).__name__}: {e}",
                "error_kind": "crash"}


def open_http_cache() -> str:
    """Open this run's response cache and return its directory, or "" on failure.

    One directory per run, announced to the evidence scripts through the
    environment because they are separate processes — the same reason the pacing
    slots and `--allow-private` travel that way. Two things follow from it being
    per run rather than global, and both are the point:

    * Every item that reports on a URL reports on the same bytes. Before this, 36
      single-page scripts fetched the entry page 36 times, and on a site that is not
      static those were 36 different documents — items disagreeing about a page with
      every one of them right about what it read.
    * Nothing survives the run. There is no cache directory to go stale between
      audits, so a second audit an hour later cannot be answered by the first.

    Removal is registered with `atexit` rather than written at each return, because
    `main` leaves by half a dozen paths and a cache that outlives its run on the
    unusual one is exactly the failure worth preventing. A run killed outright
    leaves the directory behind; `safe_http.CACHE_TTL` is why an entry from it can
    still not answer anything.
    """
    try:
        directory = tempfile.mkdtemp(prefix="seo-http-")
    except OSError as exc:
        # Not fatal, and not silent: without a cache the audit is the audit we
        # shipped in 0.9.0, only slower.
        print(f"  response cache unavailable ({exc}); every script fetches for "
              f"itself", file=sys.stderr)
        return ""
    from lib.safe_http import CACHE_DIR_VAR
    os.environ[CACHE_DIR_VAR] = directory
    atexit.register(shutil.rmtree, directory, ignore_errors=True)
    return directory


# ---------------------------------------------------------------------------
# Is a 200 response actually the page that was asked for?
# ---------------------------------------------------------------------------

# Fingerprints of an interstitial: a bot-protection challenge, a CAPTCHA wall or
# a WAF block page. Each string belongs to the product that serves the challenge,
# not to the site being audited.
#
# Split by *where* the string legitimately appears, which is what separates a
# challenge from an article about challenges. On a challenge page the vendor
# string is machinery — a script src, a form action, an element id — so it lives
# inside a tag. In an article it is prose, inside the text. Searching the whole
# document for `cdn-cgi/challenge-platform` flags every page that explains how
# Cloudflare works, and refusing to audit those is the mirror image of the bug
# this guards against.
CHALLENGE_MARKUP_MARKERS = (
    ("cdn-cgi/challenge-platform", "Cloudflare"),
    ("cf_chl_opt", "Cloudflare"),
    ("cf-browser-verification", "Cloudflare"),
    ("_incapsula_resource", "Imperva Incapsula"),
    ("px-captcha", "PerimeterX"),
    ("captcha.px-cdn.net", "PerimeterX"),
    ("ct.datado.me", "DataDome"),
    ("token.awswaf.com", "AWS WAF"),
    ("sucuri_cloudproxy_js", "Sucuri"),
    ("errors.edgesuite.net", "Akamai"),
    ("distil_r_captcha", "Distil Networks"),
)

# The vendors that name themselves in the visible text of a block page.
CHALLENGE_TEXT_MARKERS = (
    ("incapsula incident id", "Imperva Incapsula"),
    ("sucuri website firewall", "Sucuri"),
    ("generated by cloudfront", "CloudFront"),
)

# Titles an interstitial announces itself with when no vendor string is present.
# Same word-count condition applies.
CHALLENGE_TITLES = (
    "just a moment", "attention required", "checking your browser",
    "access denied", "security check", "are you a robot", "one more step",
    "verify you are human", "please verify you are a human",
    "human verification", "bot verification", "client challenge",
    "ddos protection",
)

# Above this many words of visible prose, a page has content and is not an
# interstitial no matter what strings it contains.
# basis: convention — 120 words. An interstitial is a sentence and a button; above this
#  a page has content whatever vendor strings it carries. Not calibrated against a
#  corpus of challenge pages, because no such corpus was collected
CHALLENGE_MAX_WORDS = 120

# A soft 404 is a 200 response whose own title says it is an error page. Matched
# by equality against a normalized title segment, never by substring: "404"
# appears in the title of every article ever written about broken links, and an
# audit that refuses to run on those is its own kind of wrong.
NOT_FOUND_PHRASES = frozenset({
    "404 error", "error 404", "404 not found", "not found", "page not found",
    "404 page not found", "page not found 404", "this page could not be found",
    "this page does not exist", "page does not exist", "page doesnt exist",
    "nothing found", "no page found", "page unavailable", "file not found",
    "oops that page cant be found", "oops that page can not be found",
    "seite nicht gefunden", "page introuvable", "pagina niet gevonden",
    "pagina no encontrada", "pagina non trovata",
    "страница не найдена", "ошибка 404",
})
# Accepted only as the entire title, because a lone number is also a room, a
# model, a year and a chapter.
NOT_FOUND_EXACT = frozenset({"404", "410", "error", "oops"})

_TAG_RE = re.compile(r"<[^>]+>")
_DROP_BLOCK_RE = re.compile(
    r"<(script|style|noscript|template)\b[^>]*>.*?</\1>", re.S | re.I)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
_TITLE_SPLIT_RE = re.compile(r"\s+[|·•—–]\s+|\s+-\s+")
_KEEP_RE = re.compile(r"[^\w\s]", re.U)


def visible_text(html: str) -> str:
    """What a reader would see. Script and style bodies are dropped first,
    because a challenge page is mostly JavaScript and counting it as text would
    make every interstitial look content-rich."""
    return _TAG_RE.sub(" ", _DROP_BLOCK_RE.sub(" ", html))


def visible_words(html: str) -> int:
    return len(visible_text(html).split())


def markup_only(html: str) -> str:
    """Everything inside tags, with the prose removed: attributes, script srcs,
    element ids. Where a challenge page carries its vendor's name."""
    return " ".join(_TAG_RE.findall(html)).lower()


def _normalize_title(raw: str) -> str:
    return " ".join(_KEEP_RE.sub(" ", raw).lower().split())


def page_guard(html: str) -> tuple[str, str]:
    """Decide whether a 200 response is something other than the page asked for.

    Returns `(kind, detail)` — kind is `bot_challenge`, `soft_404` or `""`.

    This is the hole left open when the reachability gate was added: a challenge
    or a soft 404 answers 200 with well-formed HTML, so every evidence script
    runs happily against a page that is not the site, and the registry grades
    whatever the interstitial happens to contain. Both are common — the audit
    User-Agent is exactly what bot protection is built to stop.
    """
    text = visible_text(html)
    words = len(text.split())
    raw_title = (_TITLE_RE.search(html) or [None, ""])[1]
    title = _normalize_title(raw_title)

    # The word count is the second condition on every branch below, and it is
    # what keeps a real page safe. Cloudflare's JS detections inject
    # `cdn-cgi/challenge-platform` into ordinary content pages, so the marker on
    # its own would condemn a working site the moment it turned that feature on.
    if words <= CHALLENGE_MAX_WORDS:
        markup = markup_only(html)
        for marker, vendor in CHALLENGE_MARKUP_MARKERS:
            if marker in markup:
                return "bot_challenge", (f"bot protection ({vendor}): a 200 "
                                         f"response with {words} words of text "
                                         f"and a {vendor} challenge in its markup")
        lowered_text = text.lower()
        for marker, vendor in CHALLENGE_TEXT_MARKERS:
            if marker in lowered_text:
                return "bot_challenge", (f"bot protection ({vendor}): a 200 "
                                         f"response with {words} words of text, "
                                         f"and {vendor} named in them")
        for phrase in CHALLENGE_TITLES:
            if phrase in title:
                return "bot_challenge", (f"bot protection: a 200 response "
                                         f"titled {raw_title.strip()[:60]!r} "
                                         f"with {words} words of text")

    segments = [_normalize_title(s) for s in _TITLE_SPLIT_RE.split(raw_title)]
    if title in NOT_FOUND_EXACT or any(s in NOT_FOUND_PHRASES for s in segments):
        return "soft_404", (f"soft 404: a 200 response titled "
                            f"{raw_title.strip()[:60]!r}")
    return "", ""


def audit_target(requested: str, final_url: str) -> str:
    """Which URL the rest of the run has to agree on.

    A redirect to another host leaves the requested URL describing nothing that
    was measured: `discover_urls` filters candidates on the old netloc so the
    sample collapses to the single entry page, and `sc-domain:` is derived from a
    domain the service account has no property for. Both fail quietly — a
    one-page sample looks like a small site, and an empty Search Console answer
    looks like a site with no traffic.

    A same-host redirect keeps the requested URL: nothing downstream is confused
    by it, and `redirect_checker.py` is then still handed the address that
    actually redirects, which is the hop it exists to report.
    """
    if final_url and urlparse(final_url).netloc != urlparse(requested).netloc:
        return final_url
    return requested


# Below this many words the entry page carries no content worth auditing. It is
# deliberately *not* treated as unreadable: an interstitial from a vendor the
# guard does not know and a client-rendered shell look identical from here, and
# the second is a real page with a real finding — javascript_render_audit.py and
# the JS-rendering items exist to report it. Refusing to score would hide that
# finding behind a guess. So this warns, names the number, and lets the registry
# do its job.
# basis: convention — 40 words, roughly a headline and a paragraph. Chosen to notice a
#  client-rendered shell, not to judge content: the registry's own thin-content items
#  decide that, at their own threshold
THIN_ENTRY_WORDS = 40


class Fetch(NamedTuple):
    """What one page request produced.

    `error` and `path` are mutually exclusive. `guard` is set whenever the
    response looked like an interstitial or an error page **even when it was not
    enforced**, so `--no-page-guard` records the suspicion instead of erasing it.
    """
    path: str        # temp file holding the HTML, "" when the fetch failed
    error: str       # why it failed, "" on success
    final_url: str   # the URL the request actually ended on, after redirects
    guard: str       # "bot_challenge" | "soft_404" | ""


def fetch_page(url: str, enforce_guard: bool = True) -> Fetch:
    """Fetch page HTML to a temp file.

    The reason a fetch failed is returned rather than swallowed, because the
    caller has to distinguish "this page could not be read" from "this page is
    fine": the first must make every check that reads the site undecided, and it
    can only say so if it knows.

    `safe_get` does not raise on 4xx/5xx, so the status is checked here. A 403
    challenge page and a 404 both return perfectly valid HTML that describes
    something other than the site being audited.
    """
    try:
        from lib.safe_http import safe_get
    except ImportError:
        from scripts.lib.safe_http import safe_get
    try:
        resp = safe_get(url, timeout=15)
    except Exception as e:  # noqa: BLE001 — the reason travels to the caller
        # The exception type carries the diagnosis (ConnectionError, SSLError,
        # Timeout); requests' message carries a nested urllib3 trace that is
        # mostly noise. Keep the type, trim the rest at a word boundary so the
        # report does not print half an identifier.
        detail = " ".join(str(e).split())
        if len(detail) > ERROR_DETAIL_CHARS:
            detail = detail[:ERROR_DETAIL_CHARS].rsplit(" ", 1)[0] + "…"
        return Fetch("", f"{type(e).__name__}: {detail}" if detail
                         else type(e).__name__, "", "")

    # Where the request actually landed. safe_request follows redirects itself and
    # returns the last response, so this is the resolved URL — the one the rest of
    # the run has to agree on.
    final_url = getattr(resp, "url", "") or url
    code = getattr(resp, "status_code", 200)
    if code >= 400:
        return Fetch("", f"HTTP {code}", final_url, "")
    ctype = (getattr(resp, "headers", {}) or {}).get("Content-Type", "")
    if ctype and not any(t in ctype.lower() for t in ("html", "xml", "text/plain")):
        return Fetch("", f"not a page: Content-Type {ctype.split(';')[0]}",
                     final_url, "")
    html = resp.text
    # An empty or non-markup body is not a page either. This catches a server
    # answering 200 with nothing.
    if "<" not in html:
        return Fetch("", f"no HTML in a {len(html)}-byte 200 response",
                     final_url, "")

    kind, detail = page_guard(html)
    if kind and enforce_guard:
        return Fetch("", detail, final_url, kind)

    tmp = tempfile.NamedTemporaryFile(suffix=".html", delete=False,
                                      mode="w", encoding="utf-8")
    tmp.write(html)
    tmp.close()
    return Fetch(tmp.name, "", final_url, kind)

# Statuses
PASS, FAIL, WARN = "PASS", "FAIL", "WARN"
NO_DATA, MANUAL, LLM_PENDING, NA = "NO_DATA", "MANUAL", "LLM_PENDING", "N/A"
# The audit could have decided this and was not given what it needed. Split out of
# NO_DATA in 0.16, because that status was carrying four unrelated sentences at once:
# an input file was not passed, the site served no such field, an external service
# could not reach the host, the script died. Only the first is work for the person
# running the audit, and printing it as "could not decide" reads as a limit of the
# tool rather than a missing argument — thirteen items said that in the measured run
# this split came out of. It is also what makes the report's partition of the registry
# derivable from statuses: reconstructing it by matching "missing input" inside the
# evidence prose, which is how it was first measured, is a coupling that breaks in
# silence the first time a reason is reworded.
NEEDS_INPUT = "NEEDS_INPUT"

# basis: inherited — critical 10 / high 6 / medium 3 / low 1, present at import from
#  Agentic-SEO-Skill. **These weights decide the SEO Score itself.** Nobody here has
#  asked whether a critical item is ten low items or three; what 0.18 measured is not
#  the number but the consequence of getting it wrong, with
#  tools/audit_score_sensitivity.py over four real runs. Re-scored from flat 1/1/1/1
#  to steep 27/9/3/1 the headline moved 0.2, 1.9, 9.3 and 14.6 points — so the table
#  cannot be dismissed as decoration. The driver is not the item count but how far
#  the per-severity pass rates spread: 11.8 points of spread gave 0.2, and 50 gave
#  14.6. It moves the score most on exactly the sites where severity discriminates,
#  which is where the critical items are the broken ones
SEVERITY_WEIGHT = {"critical": 10, "high": 6, "medium": 3, "low": 1}

# The credit a verdict earns against its item's weight. A table since 0.94.0; before
# that the same three numbers were written inline twice — once for the headline and
# once for the category bars — so an edit to one copy moved the score away from the
# bars underneath it silently. That is the defect SCR-1 found in 0.92.0 one level up,
# in the same two sums.
#
# NO_DATA, MANUAL, LLM_PENDING and N/A are absent by construction rather than set to
# zero: they carry no weight at all, and a zero here would put an undecided item in
# the denominator. `score()` selects the rows that may be weighed before consulting
# this table; VRD-6 and VRD-7 own which statuses those are.
# basis: convention — definitional rather than calibratable: a pass earns its weight,
#  a fail earns none, and a warning is the half-credit that makes WARN a verdict
#  rather than a soft FAIL. Any other value for WARN is a different instrument
VERDICT_CREDIT = {PASS: 1.0, WARN: 0.5, FAIL: 0.0}

# Ranking a fix list by severity alone puts a week of content rewriting above a
# one-line meta tag. Dividing by effort answers the question people actually ask
# first — what is worth doing this afternoon.
#
# Here rather than in checklist_report.py, where it lived until 0.94.0: SCR-2 makes
# all three tables one instrument, and an instrument whose parts live in two modules
# cannot be stamped in one place. `checklist_report` re-exports the name it used to
# own, so every importer of it keeps working.
# basis: inherited — low 1 / medium 2 / high 4, present at import. Divides
#  SEVERITY_WEIGHT to rank what to do first. 0.18 measured what that ratio is worth
#  with tools/audit_score_sensitivity.py: *dividing* changes 2-4 of the first ten
#  rows against not dividing at all, so the idea earns its place, while the exact
#  ratio does not — 1/2/3 gives the identical first ten on every run measured, and
#  1/3/9 differs by one row. Whether to divide by effort is the decision; which
#  numbers is not
EFFORT_COST = {"low": 1, "medium": 2, "high": 4}


def scoring_tables() -> dict:
    """The three tables of `openspec/specs/scoring/` §2, as one value.

    Assembled rather than written out again: a fourth copy of these numbers would be
    the thing SCR-2 exists to prevent."""
    return {"severity_weight": dict(SEVERITY_WEIGHT),
            "verdict_credit": dict(VERDICT_CREDIT),
            "effort_cost": dict(EFFORT_COST)}


def scoring_stamp_of(tables: dict) -> str:
    """Twelve hex digits naming one set of scoring tables.

    Takes the tables rather than reading the constants, because the thing worth naming
    is the instrument the *document* makes normative: `openspec/specs/scoring/` §2 is the
    normative text and SCR-14's reader holds the code against it, so a stamp computed
    from either side has to come out the same or the two have drifted. A stamp that
    could only ever be taken from the code would agree with a quiet edit by construction.

    Values are compared as floats: §2 prints `10` for a weight and `1.0` for a credit,
    and a stamp that changed when a number was written `10` instead of `10.0` would name
    the spelling rather than the instrument. Keys are sorted, so the stamp moves when a
    value moves and when a band is added or dropped, and not when a comment above them
    is reworded.
    """
    canonical = {name: {k: float(v) for k, v in rows.items()}
                 for name, rows in tables.items()}
    blob = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


def scoring_stamp() -> str:
    """The stamp of the tables this tree ships.

    Every run artifact carries it, `diff_runs` compares it and `tests/scoring-tables.json`
    declares it. Its whole job is to make a table edit loud: the score is quoted to clients
    and compared across months, so a run scored under an edited table is not comparable
    with an archived one, and until 0.94.0 nothing said so — the two numbers sat in one
    trend line looking like movement in the site.
    """
    return scoring_stamp_of(scoring_tables())


# Two severity vocabularies exist in this tree and only one of them is the
# registry's. Most evidence scripts came from upstream using `seo_common.issue()`,
# whose callers pass error/warning/info; the registry speaks critical/high/medium/
# low. A `none_severity: ["critical","high"]` rule over a script that only ever
# says "error" therefore matched nothing and returned PASS — **thirteen items,
# one of them critical, on every site ever audited.** Exactly the failure §4.12
# found in the regex assertions, in a family the pattern audit did not look at.
#
# Normalising here rather than rewriting 20 upstream scripts: the rule author only
# has to know the registry's four words, and a rule keeps working if a script is
# later brought into line. `error` is high rather than critical because nothing
# upstream reserves a word for "critical" — a script that means critical says so.
SEVERITY_ALIAS = {"error": "high", "warning": "medium", "warn": "medium",
                  "info": "low", "notice": "low"}

# Why a `source: gsc` item stays undecided even with working credentials. None
# of these is missing wiring: the Search Console API has no endpoint for manual
# actions, the Index Coverage report, or mobile-usability signals — the last was
# withdrawn in December 2023. They exist only in the web UI, and calling that
# "not wired yet" would misreport a hard API limit as unfinished work.
GSC_UNAVAILABLE = {
    "GO-141": "Search Console API exposes no manual-actions endpoint — check the UI",
    "GO-142": "Search Console API exposes no Index Coverage endpoint — check the UI",
    "MB-099": "Search Console API exposes no mobile-usability endpoint — check the UI",
}

# Which script capabilities each run mode can satisfy. Anything a mode cannot
# satisfy is reported N/A — excluded from both the score and the coverage
# denominator, because "we did not crawl" is not the same as "the site failed".
MODE_CAPS = {
    "live": {"offline", "fetch", "crawl", "api"},
    "page": {"offline", "fetch", "api"},
    "archive": {"offline"},
}
MODE_HELP = {
    "live": "full audit of a live site (fetch + crawl + external APIs)",
    "page": "single live page, no crawling",
    "archive": "local copy of the site, no network at all",
}

# Scripts that dominate wall-clock; scheduled first so they overlap the rest.
SLOW_FIRST = [
    "duplicate_content.py", "orphan_pages_from_sitemap.py", "pagespeed.py",
    "anchor_text_audit.py", "external_link_quality.py", "sitemap_checker.py",
    "indexability_matrix.py", "broken_links.py",
]


class _Missing:
    def __repr__(self):
        return "<missing>"


_MISSING = _Missing()


# ---------------------------------------------------------------------------
# Assert evaluation
# ---------------------------------------------------------------------------

def resolve(data, path: str):
    """Walk a dotted path. Numeric segments index into lists. Returns _MISSING
    when any segment is absent, so 'key exists but is None' stays distinct
    from 'key not present'."""
    cur = data
    for seg in path.split("."):
        if isinstance(cur, dict):
            if seg not in cur:
                return _MISSING
            cur = cur[seg]
        elif isinstance(cur, list):
            if not seg.isdigit() or int(seg) >= len(cur):
                return _MISSING
            cur = cur[int(seg)]
        else:
            return _MISSING
    return cur


def _texts(value) -> list[str]:
    """Flatten a value into searchable strings — used by none_matching and
    none_severity, which operate over issues[]-style arrays."""
    if value is _MISSING or value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [json.dumps(value, ensure_ascii=False)]
    if isinstance(value, list):
        out = []
        for v in value:
            out.append(json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v))
        return out
    return [str(value)]


def _length(value):
    if isinstance(value, (list, dict, str)):
        return len(value)
    return None


def _named_measure_context(rule: dict, data: dict) -> str:
    """Name a keyword carried beside the asserted measurement, when present."""
    parent_path, separator, _ = rule.get("path", "").rpartition(".")
    if not separator:
        return ""
    parent = resolve(data, parent_path)
    if not isinstance(parent, dict) or "keyword" not in parent:
        return ""
    return f"; keyword = {parent['keyword']!r}"


def evaluate(rule: dict, data: dict) -> tuple[bool | None, str]:
    """Return (passed, evidence). passed is None when the data needed to
    decide is absent — the caller turns that into NO_DATA, never a false PASS.

    A rule may set "missing_is": "pass" | "fail" when the absence of the field
    is itself the answer. Without it, absence stays undecided: a parser that
    never emits a key must not be read as the site being clean."""
    value = resolve(data, rule["path"])

    if value is _MISSING and "missing_is" in rule:
        verdict = rule["missing_is"] == "pass"
        return verdict, f"{rule['path']} absent (treated as {rule['missing_is']})"

    if "none_severity" in rule:
        levels = {SEVERITY_ALIAS.get(s.lower(), s.lower()) for s in rule["none_severity"]}
        if value is _MISSING:
            return None, f"{rule['path']} missing"
        entries = value if isinstance(value, list) else []
        hits = [it for it in entries
                if isinstance(it, dict)
                and SEVERITY_ALIAS.get(str(it.get("severity", "")).lower(),
                                       str(it.get("severity", "")).lower()) in levels]
        if hits:
            msg = hits[0].get("message") or hits[0].get("finding") or ""
            return False, f"{len(hits)} issue(s) at {'/'.join(sorted(levels))}: {msg[:120]}"
        # A non-empty list carrying no severity anywhere cannot be judged by this
        # rule, and saying "no critical issues" about it would be a verdict built on
        # a shape we do not understand. Two scripts emit `issues` as plain strings —
        # security_headers.py was printing "Site not using HTTPS" while the item
        # asserting over it reported PASS on every site ever audited.
        if entries and not any(isinstance(it, dict) and "severity" in it for it in entries):
            return None, (f"{rule['path']} has {len(entries)} entr(y/ies) with no "
                          f"severity field — this rule cannot judge them")
        return True, f"no {'/'.join(sorted(levels))} issues"

    if "none_matching" in rule:
        if value is _MISSING:
            return None, f"{rule['path']} missing"
        rx = re.compile(rule["none_matching"])
        field = rule.get("field")
        if field:
            # Aimed at one field instead of the whole element. Without this the
            # pattern is matched against every value in the dict — including the
            # `fix` string, which is written in the vocabulary of the thing being
            # asked for. Two keyword items fired on "…containing the primary
            # keyword" inside a remediation message and never looked at a keyword.
            elements = value if isinstance(value, list) else [value]
            missing_field = [e for e in elements
                             if not isinstance(e, dict) or field not in e]
            if missing_field and len(missing_field) == len(elements) and elements:
                return None, f"no {field} in any {rule['path']} element"
            hits = [str(e[field]) for e in elements
                    if isinstance(e, dict) and field in e and rx.search(str(e[field]))]
        else:
            hits = [t for t in _texts(value) if rx.search(t)]
        if hits:
            return False, (f"matched {rule['none_matching']!r}"
                           f"{f' in {field}' if field else ''}: {hits[0][:120]}")
        return True, (f"no match for {rule['none_matching']!r}"
                      f"{f' in {field}' if field else ''}")

    if "value_map" in rule:
        # The structured alternative to matching prose. The registry enumerates
        # the script's own vocabulary for a field and says what each value means;
        # a value nobody mapped is NO_DATA, never a pass.
        #
        # This is what regex-over-messages could not do. `none_matching` returns
        # PASS when nothing matches, so a pattern aimed at wording a script never
        # emits — or emits in a different word order — passed every site in
        # silence. Fifteen of this registry's twenty-one such assertions were in
        # that state. Here the failure mode is inverted: an unlisted value is
        # undecided, and the evidence says which value it was.
        if value is _MISSING:
            return None, f"{rule['path']} missing"
        field = rule.get("field")
        elements = value if isinstance(value, list) else [value]
        mapping = {str(k): str(v) for k, v in rule["value_map"].items()}
        fails, unmapped, checked = [], [], 0
        for el in elements:
            if field:
                if not isinstance(el, dict) or field not in el:
                    unmapped.append(f"no {field} in element")
                    continue
                raw = el[field]
            else:
                raw = el
            checked += 1
            verdict = mapping.get(str(raw))
            if verdict == "fail":
                fails.append(str(raw))
            elif verdict != "pass":
                unmapped.append(str(raw))
        label = field or rule["path"]
        if fails:
            return False, f"{len(fails)} of {checked} {label} = {fails[0]!r}"
        if unmapped:
            return None, f"unmapped {label} = {unmapped[0]!r}"
        if not checked:
            return None, f"{rule['path']} produced nothing to judge"
        return True, f"all {checked} {label} value(s) acceptable"

    if "count_matching_lte" in rule:
        pattern, limit = rule["count_matching_lte"]
        if value is _MISSING:
            return None, f"{rule['path']} missing"
        rx = re.compile(pattern)
        n = sum(1 for t in _texts(value) if rx.search(t))
        return n <= limit, f"{n} match(es) for {pattern!r}, limit {limit}"

    if value is _MISSING:
        return None, f"{rule['path']} missing"

    ev = repr(value)[:120]

    if "truthy" in rule:
        return bool(value), (f"{rule['path']} = {ev}"
                             f"{_named_measure_context(rule, data)}")
    if "falsy" in rule:
        return not value, f"{rule['path']} = {ev}"
    if "eq" in rule:
        return value == rule["eq"], f"{rule['path']} = {ev} (want {rule['eq']!r})"
    if "ne" in rule:
        return value != rule["ne"], f"{rule['path']} = {ev}"
    if "contains" in rule:
        texts = _texts(value)
        return (rule["contains"] in texts[0]) if texts else False, f"{rule['path']} = {ev}"
    if "matches" in rule:
        return bool(re.search(rule["matches"], str(value))), f"{rule['path']} = {ev}"

    for op, cmp in (("gte", lambda a, b: a >= b), ("lte", lambda a, b: a <= b),
                    ("gt", lambda a, b: a > b), ("lt", lambda a, b: a < b)):
        if op in rule:
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                return None, f"{rule['path']} = {ev} (not numeric)"
            return cmp(value, rule[op]), f"{rule['path']} = {value} (want {op} {rule[op]})"

    if "between" in rule:
        lo, hi = rule["between"]
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return None, f"{rule['path']} = {ev} (not numeric)"
        return lo <= value <= hi, f"{rule['path']} = {value} (want {lo}-{hi})"

    for op, cmp in (("len_eq", lambda a, b: a == b), ("len_gte", lambda a, b: a >= b),
                    ("len_lte", lambda a, b: a <= b)):
        if op in rule:
            n = _length(value)
            if n is None:
                return None, f"{rule['path']} = {ev} (no length)"
            return cmp(n, rule[op]), f"len({rule['path']}) = {n} (want {op.split('_')[1]} {rule[op]})"

    if "len_between" in rule:
        lo, hi = rule["len_between"]
        n = _length(value)
        if n is None:
            return None, f"{rule['path']} = {ev} (no length)"
        return lo <= n <= hi, f"len({rule['path']}) = {n} (want {lo}-{hi})"

    return None, f"unknown assert: {list(rule)}"


# An assertion that passes because it found none of the bad thing.
#
# The distinction that matters is direction, not shape. `gte 1` and `truthy` also
# pass, but reading *more* of a site can only help them, so a capped input cannot
# fake them — LO-198 finds a LocalBusiness node on the pages it read and finding
# more pages would not take it away. These are the ones a cap can fake, because the
# evidence that would have failed them is exactly what was not read.
#
# **Six spellings, not three.** The first draft of this listed `eq: 0`,
# `none_severity` and `none_matching` and called them "the whole set in this
# registry". They are not: `len_eq: 0`, `len_lte: 0` and `falsy` say the same thing
# about a list or a flag, and twelve items use them — four of them `critical`
# (CI-013, SE-114, SE-116, TE-171) and four `high`. A predicate that decides which
# verdicts a cap can fake, and that reads only some of the ways this registry spells
# "nothing", is the same defect one layer up from the one this release is about.
#
# `lte: 0` is here for a spelling nothing uses today. A ceiling of zero is absence
# under another name, and the cost of covering it in advance is one comparison.
def passes_by_absence(rule: dict) -> bool:
    """True when the only way this rule passes is by finding nothing."""
    return (rule.get("eq") == 0
            or rule.get("lte") == 0
            or rule.get("len_eq") == 0
            or rule.get("len_lte") == 0
            or "falsy" in rule
            or "none_severity" in rule
            or "none_matching" in rule)


# What a script says about its own coverage. `truncated` is already the name three
# scripts used for it before this was read by anything; the rest now carry it too.
def input_truncated(data: dict) -> bool:
    """True when the script says the input behind its answer was not read in full."""
    return bool(isinstance(data, dict) and data.get("truncated"))


# Which key of a rule holds the threshold, per operator. Used to report *what was
# compared* as data, so a report can put it in a sentence in any language instead
# of printing the assertion's internals.
#
# The evidence string evaluate() produces still lands in the JSON: it is the audit
# trail, and a reader who wants to know exactly which JSON path decided an item
# should be able to find it. It was never meant to be the sentence a client reads.
# Printing "summary.thin_pages = 6 (want 0)" in a report is the same category of
# mistake as showing a stack trace to a user.
THRESHOLD_OPS = ("eq", "ne", "gte", "lte", "gt", "lt", "between", "len_eq",
                 "len_gte", "len_lte", "len_between", "none_matching",
                 "count_matching_lte", "contains", "matches")


def measurement(rule: dict, data: dict) -> dict:
    """What an assertion compared, as structured data.

    Deliberately decides nothing — the verdict comes from evaluate() and only from
    there. This reads the same `rule["path"]` through the same `resolve()` and
    reports the operator, the threshold and the observed value, so there is no
    second implementation that could disagree about whether an item passed.
    """
    if not rule:
        return {}
    value = resolve(data, rule.get("path", ""))
    out = {"path": rule.get("path", "")}

    for op in THRESHOLD_OPS:
        if op in rule:
            out["op"] = op
            out["want"] = rule[op]
            break
    else:
        for op in ("truthy", "falsy", "none_severity", "value_map"):
            if op in rule:
                out["op"] = op
                break
        else:
            return out

    if value is _MISSING:
        out["missing"] = True
        return out

    op = out["op"]
    if op.startswith("len_"):
        out["got"] = _length(value)
        out["kind"] = "count"
        # What was counted, not just how many. "4 URLs are crawlable" is a
        # statistic; "/search, /cart, /checkout, /login are crawlable" is something
        # somebody can act on this afternoon.
        if isinstance(value, list) and value and all(isinstance(v, str) for v in value):
            out["examples"] = value[:4]
    elif op == "none_matching":
        field = rule.get("field")
        if field:
            elements = value if isinstance(value, list) else [value]
            texts = [str(e[field]) for e in elements
                     if isinstance(e, dict) and field in e]
        else:
            texts = _texts(value)
        rx = re.compile(rule["none_matching"])
        hits = [t for t in texts if rx.search(t)]
        out["got"] = len(hits)
        out["want"] = 0
        out["kind"] = "matches"
        if hits:
            out["sample"] = hits[0][:160]
    elif op == "none_severity":
        levels = {SEVERITY_ALIAS.get(str(lvl).lower(), str(lvl).lower())
                  for lvl in rule["none_severity"]}
        hits = [it for it in (value if isinstance(value, list) else [])
                if isinstance(it, dict)
                and SEVERITY_ALIAS.get(str(it.get("severity", "")).lower(),
                                       str(it.get("severity", "")).lower()) in levels]
        out["got"] = len(hits)
        out["want"] = 0
        out["kind"] = "issues"
        out["levels"] = sorted(levels)
        if hits:
            out["sample"] = str(hits[0].get("message")
                                or hits[0].get("finding") or "")[:160]
    elif op == "value_map":
        field = rule.get("field")
        elements = value if isinstance(value, list) else [value]
        seen = [str(el.get(field)) if field and isinstance(el, dict) else str(el)
                for el in elements]
        bad = [v for v in seen if rule["value_map"].get(v) != "pass"]
        out["kind"] = "values"
        out["got"] = bad[0] if bad else (seen[0] if seen else None)
        out["want"] = sorted(k for k, v in rule["value_map"].items() if v == "pass")
    elif op in ("truthy", "falsy"):
        out["kind"] = "flag"
        out["got"] = bool(value)
        out["want"] = op == "truthy"
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        out["got"] = value
        out["kind"] = "number"
    else:
        out["got"] = str(value)[:160]
        out["kind"] = "value"
    return out


def measure_reports_pass(measure: dict) -> bool | None:
    """Read whether a rendered measure is a passing assertion, when decidable."""
    if not measure or measure.get("missing") or "got" not in measure:
        return None
    got, want, op = measure.get("got"), measure.get("want"), measure.get("op")
    try:
        if op in ("eq", "len_eq"):
            return got == want
        if op in ("ne",):
            return got != want
        if op in ("lte", "len_lte", "count_matching_lte"):
            return got <= want
        if op in ("lt",):
            return got < want
        if op in ("gte", "len_gte"):
            return got >= want
        if op in ("gt",):
            return got > want
        if op in ("between", "len_between"):
            return want[0] <= got <= want[1]
        if op in ("none_matching", "none_severity"):
            return got == 0
        if op in ("truthy", "falsy"):
            return got == want
        if op == "value_map":
            return got in (want or [])
    except (IndexError, TypeError):
        return None
    return None


def measure_contradicts_verdict(item: dict) -> bool:
    """A sampled WARN/FAIL cannot carry a measure that says its assertion passed."""
    return (item.get("status") in (WARN, FAIL)
            and measure_reports_pass(item.get("measure") or {}) is True)


# How a reader supplies an input this run did not have.
#
# `missing input 'cwv_json'` is accurate and nearly useless: it names an internal
# key rather than the flag that fills it, so an item reported NO_DATA for want of a
# file reads as a limitation of the tool instead of a thing the reader can fix with
# one argument. Three of these have been in the report since 0.6.0 saying exactly
# that; the fourth is why they were noticed.
#
# Only the inputs somebody can actually provide belong here. `html` and
# `inventory_json` are produced by the run itself, so their absence is a failure
# already reported with its own reason and a suggestion here would be advice to do
# something impossible.
HOW_TO_SUPPLY = {
    "cwv_json": "pass --cwv-json with a browser performance trace "
                "(see cwv_metrics.py for the shape)",
    "rendered_json": "pass --rendered-json with a rendered-page measurement "
                     "(see rendered_audit.py for the shape)",
    "links_csv": "pass --links-csv with the Links export from Search Console",
    "keyword": "pass --keyword with the primary keyword this page is meant to "
               "rank for",
    "server_log": "pass --server-log with a server access log, ideally a week or "
                  "more of it (see server_log_audit.py)",
    "gsc_credentials": "pass --gsc-credentials, or set GSC_CREDENTIALS_PATH, for a "
                       "service account that can read the property",
}


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

def build_plan(items: list[dict], ctx: dict, caps: set[str], mode: str,
               preskip: dict[str, tuple[str, str]] | None = None,
               has_gsc: bool = False,
               rejected: dict[str, str] | None = None,
               opt_in: dict[str, list[str]] | None = None,
               profile_args: dict[str, list[str]] | None = None,
               has_safe_browsing: bool = False,
               ) -> tuple[dict[tuple, list[str]], dict[str, tuple[str, str]]]:
    """Map each unique (script, args) to the item ids that depend on it.

    Returns (plan, skipped) where skipped maps item id -> (status, reason) for
    checks this run cannot perform. Capability gaps become N/A — genuinely out of
    scope for the mode. Missing inputs become NEEDS_INPUT, which is neither: the
    item applies, the audit would have decided it, and one argument is what stands
    in the way. It is the operator's to-do list and prints as one.

    `rejected` maps a ctx key to why the input we were handed cannot be used.
    "Not supplied" and "supplied and refused" are both NEEDS_INPUT and are not the
    same sentence: the first tells the operator to produce the file, the second
    tells them the file they produced is about something else."""
    plan: dict[tuple, list[str]] = {}
    skipped: dict[str, tuple[str, str]] = dict(preskip or {})
    for it in items:
        if it["id"] in skipped:
            continue
        chk = it.get("check")
        if not chk or not chk.get("script"):
            continue
        need = chk.get("requires", "fetch")
        # Search Console is the one capability that can be absent for two
        # different reasons, and they are not interchangeable. A mode that makes
        # no network calls puts the item genuinely out of scope: N/A. A mode that
        # could have asked but has no key did not manage to decide it: NO_DATA.
        # Reporting the second as N/A drops it out of the coverage denominator
        # and quietly raises coverage exactly where the audit is thinnest.
        if need == "gsc":
            if "api" not in caps:
                skipped[it["id"]] = (NA, f"Search Console needs network access; "
                                         f"{mode} mode makes none")
            elif not has_gsc:
                skipped[it["id"]] = (NEEDS_INPUT, "no Search Console credentials — "
                                                  "set GSC_CREDENTIALS_PATH")
            if it["id"] in skipped:
                continue
        elif need == "safe_browsing":
            if "api" not in caps:
                skipped[it["id"]] = (
                    NA, f"Safe Browsing needs network access; {mode} mode makes none")
            elif not has_safe_browsing:
                skipped[it["id"]] = (
                    NEEDS_INPUT, "no Safe Browsing key — set GOOGLE_SAFE_BROWSING_KEY "
                                 "or SAFE_BROWSING_API_KEY")
            if it["id"] in skipped:
                continue
        elif need not in caps:
            skipped[it["id"]] = (NA, f"needs '{need}'; not available in {mode} mode")
            continue
        args = []
        no_input = ""
        for a in (chk.get("args") or []):
            if isinstance(a, str) and a.startswith("{") and a.endswith("}"):
                key = a[1:-1]
                if key in (rejected or {}):
                    no_input = rejected[key]
                    break
                if key not in ctx:
                    hint = HOW_TO_SUPPLY.get(key, "")
                    no_input = f"missing input '{key}'" + (f" — {hint}" if hint else "")
                    break
                args.append(ctx[key])
            else:
                args.append(a)
        if no_input:
            skipped[it["id"]] = (NEEDS_INPUT, no_input)
            continue
        # Per-run flags, appended to the one script each belongs to. Deliberately not
        # registry args: the registry says what an item needs in order to be decided,
        # while these describe what this run permits or guarantees. Return-tag
        # verification is guaranteed in network modes; bot verification remains an
        # operator opt-in.
        args += (opt_in or {}).get(chk["script"], [])
        # A third kind of argument, and the three are worth keeping apart. Registry args
        # say what an item needs in order to be decided. `opt_in` says what this run is
        # permitted to do. These say what this *kind of site* is measured against: a
        # local business service page is not short for a page with something to explain,
        # and 300 words is the default for the second one. It lands in argv, so it is in
        # the run log, and the script echoes it into its own summary — a moved threshold
        # that no evidence string mentions is worse than the wrong threshold.
        args += (profile_args or {}).get(chk["script"], [])
        plan.setdefault((chk["script"], tuple(args)), []).append(it["id"])
    return plan, skipped


def _timed(key: tuple, timeout: int) -> dict:
    script, args = key
    start = time.time()
    out = run_script(script, list(args), timeout=timeout)
    elapsed = round(time.time() - start, 1)
    if isinstance(out, dict) and out.get("error"):
        return {"__error__": str(out["error"])[:300],
                "__error_kind__": out.get("error_kind", "crash"),
                "__elapsed__": elapsed}
    payload = out if isinstance(out, dict) else {"__value__": out}
    payload["__elapsed__"] = elapsed
    return payload


def lab_performance(results: dict) -> dict:
    """Lighthouse's blended performance score per strategy, lifted out of the payloads.

    Until 0.25.0 this number was a verdict: SP-111 and SP-112 asserted `>= 90` under the
    title *Check Core Web Vitals in Search Console*. It is not Core Web Vitals — it mixes
    Total Blocking Time and Speed Index into one figure — and `>= 90` is a threshold
    nobody here chose. Those items now read `field_cwv.verdict`, which is what Search
    Console's own report shows.

    The number is still worth having, and it exists for pages CrUX has no sample for,
    which is most small sites. So it goes where the Search Console opportunities go:
    printed, attributed, and outside the score. A blended lab score is a hint about where
    to look, and this registry has separate lab items — SP-214 to SP-216, fed from a real
    browser trace — for measuring the page properly.
    """
    out = {}
    for key, payload in results.items():
        if key[0] != "pagespeed.py" or not isinstance(payload, dict):
            continue
        score = payload.get("performance_score")
        if score is None:
            continue
        args = list(key[1])
        strategy = args[args.index("--strategy") + 1] if "--strategy" in args else "?"
        out[strategy] = score
    return out


def gsc_opportunities(results: dict) -> list:
    """The `opportunities[]` gsc_checker.py found, lifted out of its payload.

    Script payloads are not kept in the artifact — they are megabytes and mostly
    duplicated evidence — so anything a reader needs after the run has to be named. This
    is named because it is the one thing in a run that is real work and is not a verdict:
    each entry carries its own `finding` and `fix`, and no item asserts on it.
    """
    for key, payload in results.items():
        if key[0] != "gsc_checker.py" or not isinstance(payload, dict):
            continue
        found = payload.get("opportunities")
        if isinstance(found, list):
            return [o for o in found if isinstance(o, dict)]
    return []


def execute(plan: dict[tuple, list[str]], workers: int, timeout: int, quiet: bool) -> dict:
    """Run every unique job once. Slow jobs are submitted first so they
    overlap the fast ones instead of trailing the pool."""
    order = sorted(plan, key=lambda k: (k[0] not in SLOW_FIRST,
                                        SLOW_FIRST.index(k[0]) if k[0] in SLOW_FIRST else 0))
    results: dict[tuple, dict] = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(_timed, key, timeout): key for key in order}
        done = 0
        for fut in as_completed(futures):
            key = futures[fut]
            results[key] = fut.result()
            done += 1
            if not quiet:
                # A distinct mark for a timeout: watching a run, "T" tells you the
                # site is slow, "!" tells you a script is broken.
                mark = "." if not results[key].get("__error__") else (
                    "T" if results[key].get("__error_kind__") == "timeout" else "!")
                print(f"  [{done}/{len(order)}] {mark} {key[0]}"
                      f" ({results[key]['__elapsed__']}s)", file=sys.stderr)
    return results


# Where a script says "I could not read the thing I was asked about". Two spellings,
# because there are two conventions in the tree and both are load-bearing:
# `fetch_error` for a page that could not be fetched, `error` for a third-party call
# that failed. Both mean the measurement did not happen.
#
# Deliberately *not* the plural forms. `errors` and `fetch_errors` are per-URL lists
# from the crawlers: one refused page out of fifty is a fact about that page, and
# discarding the other forty-nine verdicts because of it would be its own kind of
# dishonesty.
UNREAD_KEYS = ("fetch_error", "error")


def unread_reason(data: dict) -> str:
    """Why this script's output describes nothing, or "" when it describes something."""
    for key in UNREAD_KEYS:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def result_url(key: tuple, data: dict) -> str:
    """Recover the page a script result describes for sampled evidence."""
    for field in ("url", "final_url", "source"):
        value = data.get(field)
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return value
    args = list(key[1]) if len(key) > 1 else []
    if "--url" in args:
        pos = args.index("--url") + 1
        if pos < len(args):
            return args[pos]
    return next((arg for arg in args
                 if isinstance(arg, str) and arg.startswith(("http://", "https://"))), "")


def inapplicable_evidence(rule: dict, data: dict, fallback: str) -> str:
    """State why an applicability condition did not hold without implying failure."""
    path = rule.get("path", "")
    value = resolve(data, path)
    if path == "videos" and value == 0:
        return "no video on the page (`videos = 0`)"
    return f"does not apply: {fallback}"


def grade(items: list[dict], plan: dict, results: dict, skipped: dict,
          has_gsc: bool) -> list[dict]:
    key_for = {}
    for key, ids in plan.items():
        for i in ids:
            key_for[i] = key

    graded = []
    for it in items:
        # `effort` has to travel with the row. It did not, so every graded item
        # arrived at the report without it, priority_of fell back to "medium" for
        # all 214, and the fix list ranked by severity alone — the exact thing the
        # effort estimate was added to prevent. The report printed "?" in its
        # effort column for a year of runs and nobody read it as a defect.
        row = {k: it[k] for k in ("id", "plerdy_ref", "category", "category_label",
                                  "title", "severity", "source")}
        # Defaulted rather than required, so a hand-built item cannot raise here;
        # a registry test asserts every real item declares one.
        row["effort"] = it.get("effort", "medium")
        row["fix"] = it.get("fix", "")
        # Set on the second of two items that run the same script with the same args
        # and the same assertion — one requirement listed twice by the source
        # checklists this registry merges. It still runs and still reports; it does
        # not carry weight a second time. See `score` and SAME_CHECK in
        # tools/build_checklist.py, which is where a human decided each pairing.
        if it.get("scores_with"):
            row["scores_with"] = it["scores_with"]
        src = it["source"]

        if it["id"] in skipped and skipped[it["id"]][0] == NA:
            row.update(status=NA, evidence=skipped[it["id"]][1])
        elif src == "manual":
            row.update(status=MANUAL, evidence="requires a human")
        elif src == "llm":
            row["lens"] = it.get("lens", "")
            row.update(status=LLM_PENDING, evidence="awaiting LLM judgement")
        elif src == "gsc":
            # The reason these are undecided does not depend on credentials, so
            # neither does the message. Telling someone without a key to go set
            # GSC_CREDENTIALS_PATH sends them to configure something that cannot
            # help: the API has no endpoint for any of these three.
            #
            # MANUAL, not NO_DATA. NO_DATA says the audit tried and could not
            # decide, which invites somebody to fix the tool; these three are
            # answerable today, by a person opening the Search Console UI. That
            # is what MANUAL means, and it is what the other 31 manual items say.
            # Coverage is unmoved either way — both statuses stay in the
            # denominator and out of the decided count — so this buys honesty
            # about *who* has to act, not a better number.
            if it["id"] in GSC_UNAVAILABLE:
                row.update(status=MANUAL, evidence=GSC_UNAVAILABLE[it["id"]])
            else:
                row.update(status=NO_DATA,
                           evidence="needs Search Console" if has_gsc else
                                    "no GSC credentials — set GSC_CREDENTIALS_PATH")
        elif it["id"] in skipped:
            st, why = skipped[it["id"]]
            row.update(status=st, evidence=why)
            if it.get("check"):
                row["script"] = it["check"]["script"]
        else:
            key = key_for.get(it["id"])
            if key is None:
                row.update(status=NO_DATA, evidence="check not runnable")
            else:
                data = results.get(key, {})
                row["script"] = key[0]
                subject = result_url(key, data)
                if subject:
                    row["url"] = subject
                if "__error__" in data:
                    kind = data.get("__error_kind__", "crash")
                    row.update(status=NO_DATA, error_kind=kind,
                               evidence=f"{FAILURE_LABEL.get(kind, FAILURE_LABEL['crash'])}: "
                                        f"{data['__error__'][:160]}")
                elif unread_reason(data):
                    # The script ran, exited 0, and read nothing. Not a crash, and not
                    # handled until now: a script that fetched nothing still emits its
                    # defaults — `score: 0`, `missing_alt: 0`, `issues: []` — and those
                    # defaults grade. Sixty-two items produced a confident PASS or FAIL
                    # about a host that refused every connection, which is the failure
                    # that once scored an unresolvable domain 61/100, one layer in.
                    #
                    # The entry-reachability gate stops the wholly-dead case before any
                    # scoring. This is the case that gate cannot see: a site that
                    # answers the entry request and then stops — rate limiting, a WAF
                    # tripping after N requests, a deploy during an audit.
                    row.update(status=NO_DATA, error_kind="unread",
                               evidence=f"the site could not be read: "
                                        f"{unread_reason(data)[:160]}")
                else:
                    applies = it["check"].get("applies_when")
                    applies_ok, applies_ev = (evaluate(applies, data)
                                              if applies else (True, ""))
                    if applies_ok is None:
                        row.update(status=NO_DATA, evidence=applies_ev)
                    elif not applies_ok:
                        row.update(status=NA,
                                   evidence=inapplicable_evidence(applies, data,
                                                                 applies_ev))
                    else:
                        row["measure"] = measurement(it["check"]["assert"], data)
                        ok, ev = evaluate(it["check"]["assert"], data)
                        if ok is None:
                            row.update(status=NO_DATA, evidence=ev)
                        elif (ok and passes_by_absence(it["check"]["assert"])
                              and input_truncated(data)):
                            # Found none of it — in the part that was read. The
                            # cap that stopped the reading is the same cap that
                            # would have stopped the finding, so this PASS is a
                            # claim about the whole site made from part of it.
                            #
                            # Fourth time this repository has drawn the line here
                            # and the first time in the runner rather than in one
                            # script: 0.49.0 withheld `image_inventory`'s count,
                            # 0.50.0 `image_weight_audit`'s, and 0.87.0 twice in
                            # the citation score. A FAIL is untouched — a defect
                            # found in part of a site is still a defect, and
                            # withholding it would lose a true finding to a cap.
                            row.update(status=NO_DATA,
                                       evidence=f"{ev}, but only part of the input "
                                                f"was read: this says nothing about "
                                                f"what the cap left out")
                        elif ok:
                            row.update(status=PASS, evidence=ev)
                        else:
                            warn_rule = it["check"].get("warn")
                            w_ok = False
                            w_ev = ""
                            if warn_rule:
                                w_ok, w_ev = evaluate(warn_rule, data)
                            # The verdict stands on a capped input — a defect found
                            # in part of a site is a defect — but the number beside
                            # it is a floor rather than a total, and printing it bare
                            # is the same false precision this release is about.
                            # "3 thin pages" read off three pages of seven is at
                            # least three. Said in the evidence rather than in the
                            # measure, because the measure is what the script
                            # returned and that has not changed.
                            partial = (" — counted over the part of the input that "
                                       "was read, so this is a floor"
                                       if input_truncated(data) else "")
                            if w_ok:
                                row.update(status=WARN,
                                           evidence=f"{ev}; within warn range "
                                                    f"({w_ev}){partial}")
                            else:
                                row.update(status=FAIL, evidence=f"{ev}{partial}")
        # Where the verdict came from, recorded on every item that has one.
        #
        # Set here rather than at each branch above so a path added later cannot
        # produce a verdict with no provenance: everything that reaches this point
        # with a verdict was produced by this process measuring something. The two
        # merges in checklist_report.py stamp `model` and `claimed` over it, and
        # those are the two that matter — a report where 30 of 106 decided items are
        # somebody's word is a different document from one where all 106 were
        # measured, and until 0.16 it printed identically.
        if row["status"] in (PASS, FAIL, WARN):
            row["decided_by"] = "measured"
        graded.append(row)
    return graded


def score(graded: list[dict]) -> dict:
    """SEO Score counts only items that were actually decided, and says over how
    much of the registry's weight it was computed.

    There is no `Coverage %` any more, and removing it was the point. It divided
    decided items by applicable ones, which added together three quantities that
    measure different things: how far the tool reached, how much work the operator
    had done, and how much of the registry was never the audit's job to answer. A
    figure that moves for three unrelated reasons cannot be attributed by the person
    reading it — coverage falling from 62% to 50% read as the site becoming harder to
    measure when it could equally mean nobody answered the queue this time. That is
    the same objection this project raises to a single SEO score, one level down, and
    it was in every report from 0.1.0 to 0.15.0.

    Two things replace it.

    `weight_pct` travels with the score, because it is the claim a reader has to be
    able to check: 69/100 computed over 55% of the registry's weight is a different
    statement from the same 69 over 95%, and nothing in the old pair of numbers said
    which one you were holding.

    `partition` puts every item in exactly one bucket named for **whose action moves
    it**, and the buckets sum to the registry — so no item can hide in a denominator,
    and a test asserts the sum. Percentages named nobody; `waiting_on_you` is a list
    of things to do."""
    scored = [g for g in graded if g["status"] in (PASS, FAIL, WARN)]
    applicable = [g for g in graded if g["status"] != NA]

    # Weight is carried per *check*, not per item. Seven duplicate groups in this
    # registry carry nine `scores_with` twins: one script, one set of arguments and one
    # assertion under multiple source numbers. "Provide Meaningful Image Alt Text" and
    # "Provide Meaningful Alt Text" are one question asked twice, and until 0.22 both
    # halves scored. That did two things: it doubled
    # a single defect's pull on the headline, and where the twins disagreed on severity
    # it made the weight of one defect depend on which of them a reader happened to
    # look at. The second item still runs and still reports its own status; it is left
    # out of these sums and out of `weight_registry`, so the denominator matches.
    weighed = [g for g in scored if not g.get("scores_with")]
    earned = sum(SEVERITY_WEIGHT[g["severity"]] * VERDICT_CREDIT[g["status"]]
                 for g in weighed)
    total = sum(SEVERITY_WEIGHT[g["severity"]] for g in weighed)

    by_cat: dict[str, dict] = {}
    for g in graded:
        c = by_cat.setdefault(g["category"], {"label": g["category_label"], "counts": {}})
        c["counts"][g["status"]] = c["counts"].get(g["status"], 0) + 1
    # Weighted by severity, exactly like seo_score above, and for the reason the
    # report needs: these numbers sit next to the headline score and get read
    # against it. An unweighted pass rate put them on a second scale — one category
    # showed 25 where its weighted score was 42 — and the report orders its bars by
    # this number, so the unweighted version could point a reader at five failing
    # `low` items while a failing `critical` sat further down the page.
    #
    # Over `weighed`, not `scored`, for the same reason and one level down: until
    # 0.92.0 these sums iterated every scored row, so a twin was folded out of the
    # headline and left in the bar underneath it. Six of the nine pairs here cross
    # categories, so the shared measurement is weighed in the carrier's category and
    # in no other — SCR-1 says the twin "contributes nothing to either half of the
    # score or to a category score". A category whose only decided item is a twin has
    # no weight of its own left and its score is absent, which is the same sentence
    # SCR-3 makes about the headline: zero is a verdict, absence is not.
    #
    # `worst_open` below stays over every scored row on purpose. It counts unresolved
    # items rather than weighing them, and a category that has just lost an item's
    # weight to its carrier is precisely the one whose reader still needs telling
    # that something in it is open.
    for key, c in by_cat.items():
        cs = c["counts"]
        dec = cs.get(PASS, 0) + cs.get(FAIL, 0) + cs.get(WARN, 0)
        c["decided"] = dec
        # Protect the reader from a score whose denominator is invisible when twins
        # carry their weight in another category but remain decided in this one.
        cat_weighed = [g for g in weighed if g["category"] == key]
        c["score_population"] = len(cat_weighed)
        earned_c = sum(SEVERITY_WEIGHT[g["severity"]] * VERDICT_CREDIT[g["status"]]
                       for g in cat_weighed)
        total_c = sum(SEVERITY_WEIGHT[g["severity"]] for g in cat_weighed)
        c["score"] = round(100 * earned_c / total_c) if total_c else None
        # What the bar cannot show: a single failing critical in an otherwise clean
        # category still scores well, so the count travels with the score.
        c["worst_open"] = next((s for s in ("critical", "high", "medium", "low")
                               if any(g["severity"] == s and g["status"] in (FAIL, WARN)
                                      for g in scored if g["category"] == key)), None)

    counts: dict[str, int] = {}
    for g in graded:
        counts[g["status"]] = counts.get(g["status"], 0) + 1

    # The weight the score was computed over, against the weight of the whole
    # registry. `total` above is the same sum, but it is the denominator *inside*
    # the score and says nothing about what was left out of it.
    # Over the applicable items, not the whole registry: an N/A item is out of
    # scope for this mode or profile, and counting it here would make narrowing
    # scope look like a thinner audit. N/A drops out of both numbers, as it always
    # has — this is that rule, applied to the number that replaced coverage.
    weight_registry = sum(SEVERITY_WEIGHT[g["severity"]] for g in applicable
                          if not g.get("scores_with"))

    # Every item lands in exactly one bucket, and the buckets sum to the registry.
    # Derived from statuses alone — see NEEDS_INPUT for why that mattered enough to
    # add a status for it.
    partition = {
        # The score is computed over these.
        "decided": len(scored),
        # The operator's to-do list: a queue nobody answered, a file nobody passed.
        # One bucket because it is one question — what is left for the person who
        # ran this — and its two halves are counted separately underneath.
        "waiting_on_you": counts.get(LLM_PENDING, 0) + counts.get(NEEDS_INPUT, 0),
        # Answerable, but not here and not by a script: the Search Console UI, or
        # somebody looking at the thing.
        "needs_a_person": counts.get(MANUAL, 0),
        # Nobody's to-do. The site served no such field, an external service could
        # not reach the host, the script died. Distinguishing those further would
        # need a status per cause and they do not earn one.
        "undecided": counts.get(NO_DATA, 0),
        # Out of scope for this mode or profile, and out of both numbers above.
        "not_applicable": counts.get(NA, 0),
    }
    # How much of the score is a measurement and how much is somebody's word.
    # Only meaningful once answers can be merged in — before 0.16 every decided
    # item was measured because nothing else could decide one.
    provenance: dict[str, int] = {}
    for g in scored:
        provenance[g.get("decided_by") or "measured"] = \
            provenance.get(g.get("decided_by") or "measured", 0) + 1
    return {
        "seo_score": round(100 * earned / total) if total else None,
        "decided_by": provenance,
        # How much of the registry the score speaks for. Always printed beside it;
        # a score without it is a fraction with the denominator torn off.
        "weight_pct": round(100 * total / weight_registry) if weight_registry else 0,
        "weight_decided": total,
        "weight_applicable": weight_registry,
        "partition": partition,
        "waiting_on_you": {"llm_pending": counts.get(LLM_PENDING, 0),
                           "needs_input": counts.get(NEEDS_INPUT, 0)},
        "decided": len(scored),
        "applicable": len(applicable),
        "total_items": len(graded),
        "status_counts": counts,
        "by_category": by_cat,
    }


# Context values that must never reach a file. checklist-results.json and
# everything under .seo-runs/ is what gets shared — with a client, in a ticket,
# in a repo — and the run log is built from each script's argv, so a key passed
# as an argument lands in it verbatim. Paths are not secrets and stay readable;
# the key material does not.
SECRET_CTX_KEYS = ("indexnow_key", "pagespeed_key")
SAFE_BROWSING_ENV_KEYS = ("GOOGLE_SAFE_BROWSING_KEY", "SAFE_BROWSING_API_KEY")
REDACTED = "<redacted>"


def redact(value, secrets: tuple[str, ...]):
    """Replace every secret value anywhere in a JSON-serialisable structure.

    Applied to the whole payload rather than to the run log alone: a script that
    echoes its arguments into an error message leaks the same key by a different
    route, and there is no way to enumerate those routes in advance."""
    if not secrets:
        return value
    if isinstance(value, str):
        for s in secrets:
            if s:
                value = value.replace(s, REDACTED)
        return value
    if isinstance(value, dict):
        return {redact(k, secrets): redact(v, secrets) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, secrets) for v in value]
    return value


def artifact_secrets(ctx: dict) -> tuple[str, ...]:
    """Secrets removed from shared results, including subprocess-only env keys."""
    return (tuple(ctx[k] for k in SECRET_CTX_KEYS if ctx.get(k))
            + tuple(value for key in SAFE_BROWSING_ENV_KEYS
                    if (value := os.environ.get(key))))


# What an unreachable entry page makes undecidable. `gsc` is deliberately absent:
# Search Console serves Google's stored history, which is still answerable when
# the site is down right now. Everything else here reads the live site — directly
# (fetch, crawl) or through an API that fetches it for us (PageSpeed, W3C).
NEEDS_A_LIVE_SITE = {"fetch", "crawl", "api"}


# What a *wrong* entry page makes undecidable — everything the reachability gate
# covers, plus the offline checks. When the fetch simply failed there is no HTML
# to hand an offline script and it drops out on its missing input; when the page
# loaded but is an interstitial or an error page, the file exists and reads
# perfectly, so nothing stops those scripts from grading the wrong document. In
# archive mode that is not hypothetical: a saved challenge page scored 6 passes
# and 10 failures on its 12 words of text.
NEEDS_THE_RIGHT_PAGE = NEEDS_A_LIVE_SITE | {"offline"}


def unreachable_skips(items: list[dict], reason: str,
                      wrong_page: bool = False) -> dict[str, tuple[str, str]]:
    """Mark every check that reads the live site as undecided.

    Without this the audit grades a site it never saw. Most evidence scripts exit
    0 with a well-formed empty result when they cannot fetch anything, and an
    empty result satisfies exactly the assertions this registry is full of —
    `errors = 0`, `duplicates = 0`, no match for a warning pattern. Against a
    host that does not resolve, 29 of 42 scripts returned success and the run
    scored 61/100 on 40 fabricated passes. `missing_is` cannot catch it: the key
    is present, and its value is zero.

    `wrong_page` widens the gate to the offline checks, for the case where a page
    was read successfully and is the wrong page — see NEEDS_THE_RIGHT_PAGE.
    """
    gate = NEEDS_THE_RIGHT_PAGE if wrong_page else NEEDS_A_LIVE_SITE
    label = "entry page is not the site" if wrong_page else "entry page unreachable"
    out = {}
    for it in items:
        need = (it.get("check") or {}).get("requires", "fetch")
        if need in gate:
            out[it["id"]] = (NO_DATA, f"{label} ({reason})")
    return out


# What a host only we can reach makes undecidable. Every one of these needs a
# third party to fetch the URL or to have a history for it: PageSpeed Insights
# measures the page from Google's own network, Safe Browsing looks the URL up in
# an index, IndexNow submits it, and a Search Console property cannot exist for an
# address on somebody's LAN. None of that is a defect in the site or in the tool,
# and none of it becomes possible by trying harder.
NEEDS_THE_OUTSIDE_WORLD = {"api", "gsc", "safe_browsing"}


def private_host_skips(items: list[dict], host: str,
                       gate: set | None = None) -> dict[str, tuple[str, str]]:
    """Mark the external-API checks undecided when the site is not public.

    `NO_DATA`, not `N/A`, and the distinction is the usual one: these items apply
    perfectly well to this site, they simply cannot be answered while it is only
    reachable from here. Leaving the coverage denominator would lift coverage on a
    staging audit — the one kind of audit that genuinely knows least — and a
    pre-launch report claiming the same coverage as a live one would be the exact
    overstatement this tool exists not to make.

    Found by running it: pointed at a fixture server, `pagespeed.py` crashed twice
    with `HTTP 400` and the two Search Console scripts crashed on a property
    derived from an IP. "Script failed" sends the reader to open a working script.
    """
    gate = NEEDS_THE_OUTSIDE_WORLD if gate is None else gate
    out = {}
    for it in items:
        need = (it.get("check") or {}).get("requires", "fetch")
        if need in gate:
            out[it["id"]] = (NO_DATA, f"{host} is only reachable from here, so no "
                                      f"external service can measure it or hold "
                                      f"history for it")
    return out


def run_stamp() -> str:
    """A history filename that two runs cannot share.

    Second precision was not enough: `--only` runs finish in under a second, so
    a run could overwrite the one before it and the history silently lost an
    entry — the file it would have been compared against. Milliseconds, at fixed
    width so the names still sort chronologically among themselves.
    """
    now = datetime.now(timezone.utc)
    return now.strftime("%Y%m%dT%H%M%S") + f"{now.microsecond // 1000:03d}Z"


def history_path(domain: str, stamp: str) -> str:
    """Where this run is filed, without ever landing on an existing file.

    A stamp collision is now vanishingly unlikely, but "unlikely" is how the
    second-precision version was justified too, and the cost of being wrong is
    destroying a previous audit.
    """
    d = os.path.join(os.getcwd(), ".seo-runs", domain)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f"{stamp}.json")
    n = 2
    while os.path.exists(path):
        path = os.path.join(d, f"{stamp}-{n}.json")
        n += 1
    return path


EPOCH = datetime.min.replace(tzinfo=timezone.utc)


def run_time(payload: dict, name: str) -> datetime:
    """When a stored run happened, as something orderable.

    `started_at` first, the filename stamp second. Both are parsed rather than
    compared as text: an ISO timestamp and a compact stamp sort against each
    other by accident of punctuation — `2026-08-03T…` always precedes
    `20260803T…` because `-` is below `0` — so a mixed directory would rank
    every legacy file above every current one.
    """
    started = str(payload.get("started_at") or "")
    if started:
        try:
            parsed = datetime.fromisoformat(started)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    stamp = name.split(".")[0].split("-")[0]
    for fmt in ("%Y%m%dT%H%M%S%fZ", "%Y%m%dT%H%M%SZ"):
        try:
            return datetime.strptime(stamp, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return EPOCH


def previous_run(domain: str, exclude: str) -> dict | None:
    """The most recent earlier run for this domain.

    Ordered by the timestamp *inside* each file rather than by its name. The name
    format has already changed once (seconds to milliseconds), and a directory
    holding both would sort wrongly by name for any run inside the same second —
    which is exactly the pair a diff is most likely to want.

    A history file that will not parse is skipped, not fatal: a corrupt record of
    an old run is no reason to abandon the current one.
    """
    d = os.path.join(os.getcwd(), ".seo-runs", domain)
    if not os.path.isdir(d):
        return None
    skip = os.path.basename(exclude) if exclude else ""
    best, best_key = None, EPOCH
    for name in sorted(f for f in os.listdir(d) if f.endswith(".json") and f != skip):
        try:
            with open(os.path.join(d, name), encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        key = run_time(payload, name)
        if key >= best_key:
            best, best_key = payload, key
    return best


# basis: convention — how many stored runs the trend reads. Twelve is a year of
#  monthly audits or a quarter of weekly ones, which is the span somebody asks "has
#  this moved" about; the cost of a larger number is reading more files, not a worse
#  answer, so it is a default rather than a limit.
HISTORY_RUNS = 12


def run_series(domain: str, exclude: str, limit: int = HISTORY_RUNS) -> list[dict]:
    """The arc of this domain's audits, oldest first, one compact record each.

    `previous_run` answers "what changed since last time", and that is a different
    question from the one a site owner actually asks — whether six months of work
    moved anything. Every run since 0.1.0 has been stored in `.seo-runs/`; until now
    exactly one of them was ever read.

    Compact on purpose. A stored run is a megabyte and mostly evidence strings, and a
    trend needs five numbers per run plus the per-item statuses. Carrying whole
    payloads into the artifact would multiply the deliverable by the length of the
    history, which is the wrong direction for a file people email.

    Ordered by the timestamp *inside* each file, for the reason `previous_run`
    documents: the name format has already changed once. An unreadable history file
    is skipped rather than fatal — a corrupt record of an old audit is no reason to
    abandon this one.
    """
    d = os.path.join(os.getcwd(), ".seo-runs", domain)
    if not os.path.isdir(d):
        return []
    skip = os.path.basename(exclude) if exclude else ""
    rows = []
    for name in sorted(f for f in os.listdir(d) if f.endswith(".json") and f != skip):
        try:
            with open(os.path.join(d, name), encoding="utf-8") as fh:
                payload = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        scores = payload.get("scores") or {}
        rows.append((run_time(payload, name), {
            "started_at": payload.get("started_at"),
            "registry_version": payload.get("registry_version"),
            # The arc is the place a table change does the most damage: a trend line
            # is read as the site moving. Carried per point so the reader can see
            # which stretch of it was scored with which instrument.
            "scoring_stamp": (payload.get("scoring_tables") or {}).get("stamp"),
            "mode": payload.get("mode"),
            "profile": payload.get("profile"),
            "seo_score": scores.get("seo_score"),
            "weight_pct": scores.get("weight_pct"),
            "decided": scores.get("decided"),
            "statuses": {i["id"]: i["status"] for i in payload.get("items", [])},
        }))
    rows.sort(key=lambda r: r[0])
    return [r[1] for r in rows[-limit:]]


# basis: convention — a sort order for the streak list, definitional in the same way
#  VERDICT_RANK is: critical before low is the only ordering severity can have
SEVERITY_ORDER_KEY = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def open_since(series: list[dict], current: list[dict]) -> list[dict]:
    """For each item failing now, the oldest run in which it was already failing.

    This is the part of a trend worth printing. "FAIL" and "FAIL in every audit since
    March" are different sentences to the person who owns the site, and only the
    second one says the fix keeps not happening. A score line cannot carry it: a site
    can hold the same score for six months while a different item fails each time.

    Deliberately a *consecutive* streak counted backwards from now, not a total. An
    item that failed, was fixed, and broke again is not an item nobody has touched,
    and reporting it as one would be an accusation the data does not support.
    """
    out = []
    for item in current:
        if item["status"] not in (FAIL, WARN):
            continue
        streak, first = 0, None
        for past in reversed(series):
            if past["statuses"].get(item["id"]) not in (FAIL, WARN):
                break
            streak += 1
            first = past["started_at"]
        if streak:
            out.append({"id": item["id"], "title": item["title"],
                        "severity": item["severity"], "status": item["status"],
                        "runs": streak + 1, "since": first})
    out.sort(key=lambda r: (-r["runs"], SEVERITY_ORDER_KEY.get(r["severity"], 9)))
    return out


# Where a status sits on the pass/fail scale, for saying whether a change was an
# improvement. Only these three are on it: NO_DATA, MANUAL, LLM_PENDING and N/A are
# not worse or better verdicts, they are the absence of one.
# basis: convention — definitional rather than calibratable: FAIL < WARN < PASS is the
#  only ordering those three can have. NO_DATA and MANUAL are deliberately absent — they
#  are the absence of a verdict, not a worse one
VERDICT_RANK = {FAIL: 0, WARN: 1, PASS: 2}


def direction(was: str, now: str) -> str:
    """`improved`, `regressed` or `evidence` for one status change.

    The third is the one worth having. `PASS` becoming `NO_DATA` is not the site
    getting worse — it is the run losing the ability to tell, usually because a
    third-party service was down or a file stopped being supplied. Filing that under
    "regressed" would make a client's report say their site broke when what broke was
    the measurement, and the reverse — `NO_DATA` becoming `PASS` — would take credit
    for a fix nobody made.
    """
    before, after = VERDICT_RANK.get(was), VERDICT_RANK.get(now)
    if before is None or after is None:
        return "evidence"
    return "improved" if after > before else "regressed"


def diff_runs(prev: dict, cur: dict) -> tuple[list[dict], str]:
    """Status changes between two runs, plus a warning when the runs are not
    comparable. Only the intersection of the two item sets can be compared, so
    a `--only` run against a full one, or `page` against `live`, would otherwise
    report "no status changes" while saying nothing about everything it dropped
    — silence that reads as reassurance."""
    old = {i["id"]: i["status"] for i in prev.get("items", [])}
    out = []
    for i in cur["items"]:
        was = old.get(i["id"])
        if was and was != i["status"]:
            out.append({"id": i["id"], "title": i["title"], "from": was,
                        "to": i["status"], "direction": direction(was, i["status"]),
                        "severity": i.get("severity", "medium"),
                        "category_label": i.get("category_label", ""),
                        "evidence": i.get("evidence", "")})

    # One sentence per reason the two runs may not be comparable, joined once.
    #
    # Accumulated into a list rather than onto a string, because the string version
    # printed the registry sentence twice whenever the mode had also changed: its
    # last branch rebuilt `note` as `note + <mode sentence> + ". " + note`. Every
    # test here moved exactly one axis, so no test ever held two sentences at once
    # and the duplication survived from 0.15.0 to 0.94.0 — a client's report saying
    # the same thing twice, in the paragraph whose whole job is to be believed.
    reasons = []
    pv, cv = prev.get("registry_version"), cur.get("registry_version")
    if pv and cv and pv != cv:
        reasons.append(f"previous run used registry {pv}, this one {cv}; the item set "
                       f"itself changed, so differences may be edits to the checklist "
                       f"rather than to the site")
    dropped = len(set(old) - {i["id"] for i in cur["items"]})
    if dropped:
        reasons.append(f"{dropped} item(s) from the previous run are not in this one; "
                       f"the diff covers only the {len(old) - dropped} they share")
    if prev.get("profile") and prev["profile"] != cur.get("profile"):
        reasons.append(f"previous run used --profile {prev['profile']}, this one "
                       f"{cur.get('profile')}; scope differs")
    if prev.get("mode") and prev["mode"] != cur.get("mode"):
        reasons.append(f"previous run used --mode {prev['mode']}, this one "
                       f"{cur.get('mode')}; status changes may reflect the mode, "
                       f"not the site")

    # SCR-2: the score is quoted to clients and read across months, so a baseline
    # scored under a different table is a change of instrument and not movement in
    # the site. The two cases are different sentences on purpose — a run archived
    # before 0.94.0 carries no stamp at all, and reporting that as "the tables
    # changed" would accuse an edit nobody made.
    ps, cs = prev.get("scoring_tables"), cur.get("scoring_tables")
    pstamp = (ps or {}).get("stamp")
    cstamp = (cs or {}).get("stamp")
    if pstamp and cstamp and pstamp != cstamp:
        reasons.append(f"previous run scored under scoring tables {pstamp}, this one "
                       f"{cstamp}; the instrument changed, so the two scores are not "
                       f"comparable and any difference between them is not movement "
                       f"in the site")
    elif cstamp and not pstamp:
        reasons.append("the previous run does not record which scoring tables it used, "
                       "so whether the two scores are comparable cannot be established")

    return out, ". ".join(reasons) + (". " if reasons else "")


# Portable default first; the second entry is one machine's pre-existing key and
# is kept only so that setup keeps working. Anyone else should use the generic
# path or set GSC_CREDENTIALS_PATH — nothing here is specific to an account.
GSC_FALLBACKS = [
    "~/.config/gcloud/gsc-service-account.json",
    "~/.config/gcloud/gv-sa-key.json",
]


PROFILES = os.path.join(SKILL_DIR, "resources", "config", "profiles.json")


def load_profile(name: str) -> dict:
    """Read one site profile. An unknown name is an error rather than a silent
    fallback to `default`: quietly auditing an online store as a blog would drop
    the storefront checks and raise the score for the wrong reason."""
    with open(PROFILES, encoding="utf-8") as f:
        profiles = json.load(f)["profiles"]
    if name not in profiles:
        raise KeyError(f"unknown profile {name!r}; known: {', '.join(sorted(profiles))}")
    return profiles[name]


def all_profiles() -> dict:
    with open(PROFILES, encoding="utf-8") as f:
        return json.load(f)["profiles"]


def detect_profile(html_path: str, url: str) -> dict:
    """Pre-run guess at the site type, used only to pre-fill the question."""
    empty = {"profile": "default", "confidence": "none", "signals": {}, "scores": {}}
    if not html_path or not os.path.exists(html_path):
        return empty
    try:
        from detect_profile import detect
        with open(html_path, encoding="utf-8", errors="replace") as f:
            return detect(f.read(), url)
    except Exception:  # noqa: BLE001 — a failed guess must never stop the audit
        return empty


def describe_detection(d: dict) -> str:
    why = ", ".join(d.get("signals", {}).get(d["profile"], [])[:3])
    return f"{d['profile']} ({d['confidence']} confidence" + (f": {why})" if why else ")")


def choose_profile(explicit: str, interactive: bool, detected: dict | None = None) -> str:
    """Resolve which profile to run under.

    An explicit --profile always wins; `--profile auto` accepts the detector's
    suggestion without asking, which is the one way detection is allowed to
    narrow scope on its own — because passing it is a decision.

    Otherwise ask, but only when there is a person at the terminal to answer:
    prompting unconditionally would hang CI, cron and every backgrounded run on a
    question nobody can see. Without a terminal the run proceeds under `default`
    — the full registry — and says so. Detection never silently narrows anything:
    a heuristic that drops checks and lifts the score, with nobody deciding to,
    is the exact failure this registry exists to prevent.
    """
    profiles = all_profiles()
    names = list(profiles)
    detected = detected or {"profile": "default", "confidence": "none", "signals": {}}

    if explicit == "auto":
        print(f"  profile: {describe_detection(detected)} — detected, --profile auto",
              file=sys.stderr)
        return detected["profile"]
    if explicit:
        return explicit
    if not interactive or not sys.stdin.isatty():
        note = (f" Detection suggests {describe_detection(detected)}; pass "
                f"--profile auto to accept it."
                if detected["profile"] != "default" else "")
        print("  profile: default (not specified; no terminal to ask)." + note,
              file=sys.stderr)
        return "default"

    print("\nWhich kind of site is this? The profile decides which checks apply;"
          "\nanything out of scope is reported N/A instead of counting against you.\n",
          file=sys.stderr)
    suggested = detected["profile"]
    for n, name in enumerate(names, 1):
        p = profiles[name]
        mark = " <- detected" if name == suggested and suggested != "default" else ""
        print(f"  {n}. {name:<10} {p['label']} — {p['note']}{mark}", file=sys.stderr)
    if suggested != "default":
        why = ", ".join(detected.get("signals", {}).get(suggested, [])[:4])
        print(f"\n  Detected: {suggested} ({detected['confidence']} confidence)"
              + (f" from {why}" if why else ""), file=sys.stderr)
        if detected.get("runner_up"):
            print(f"  Close second: {detected['runner_up']['profile']} — the guess "
                  f"is not clear-cut, check it.", file=sys.stderr)
        default_label = f"Enter for {suggested}"
    else:
        print("\n  Detected: nothing conclusive; the evidence was too thin to "
              "narrow anything.", file=sys.stderr)
        default_label = "Enter for default"
    print(file=sys.stderr)

    for _ in range(3):
        try:
            raw = input(f"Profile [number, name, or {default_label}]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n  profile: {suggested}", file=sys.stderr)
            return suggested
        if not raw:
            return suggested
        if raw.isdigit() and 1 <= int(raw) <= len(names):
            return names[int(raw) - 1]
        if raw in profiles:
            return raw
        print(f"  {raw!r} is not one of: {', '.join(names)}", file=sys.stderr)
    print(f"  profile: {suggested}", file=sys.stderr)
    return suggested


def profile_excludes(items: list[dict], profile: dict) -> dict[str, str]:
    """item id -> why the profile puts it out of scope."""
    cats = set(profile.get("exclude_categories", []))
    scripts = set(profile.get("exclude_scripts", []))
    ids = set(profile.get("exclude_items", []))
    # Why this profile drops this id, in the profile's own words. An item excluded by
    # category names the category and one excluded by script names the script; an item
    # excluded by id used to say only "excluded by profile" — the one exclusion a reader
    # cannot reconstruct, on the only surface where narrowing scope has to justify itself.
    reasons = profile.get("exclude_item_reasons") or {}
    out = {}
    for it in items:
        script = (it.get("check") or {}).get("script")
        if it["id"] in ids:
            out[it["id"]] = reasons.get(it["id"], "excluded by profile")
        elif it["category"] in cats:
            out[it["id"]] = f"category {it['category']} does not apply to this site type"
        elif script and script in scripts:
            out[it["id"]] = f"{script} does not apply to this site type"
    return out


SITEMAP_PATHS = ("/sitemap.xml", "/sitemap_index.xml")

# Extensions that are certainly not pages. A stylesheet or a PDF sampled as a
# page fails every page-level check, and because sampling aggregates on the
# worst verdict, one asset in the sample condemns the whole site.
ASSET_EXTENSIONS = {
    ".css", ".js", ".mjs", ".json", ".xml", ".rss", ".atom", ".txt", ".map",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".svg", ".ico", ".bmp",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".csv",
    ".zip", ".gz", ".tar", ".rar", ".7z", ".dmg", ".exe", ".apk",
    ".mp3", ".mp4", ".webm", ".avi", ".mov", ".wav", ".ogg", ".m4a",
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
}

# Anchors only. The old pattern matched every `href=` in the document, which
# includes <link rel="stylesheet">, <link rel="icon"> and every preload hint —
# so the sample filled up with assets before reaching a single real page.
ANCHOR_RE = re.compile(r'<a\b[^>]*?\bhref\s*=\s*["\']([^"\']+)["\']', re.I)
LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>")


def looks_like_a_page(url: str) -> bool:
    """Reject by extension only. The authoritative check is the Content-Type on
    fetch; this just avoids spending a request to learn what the path already
    says."""
    path = urlparse(url).path
    dot = path.rfind(".")
    slash = path.rfind("/")
    if dot < 0 or dot < slash:  # no extension at all
        return True
    return path[dot:].lower() not in ASSET_EXTENSIONS


def stride(urls: list[str], limit: int) -> list[str]:
    """Spread `limit` picks evenly across `urls`, keeping the first.

    Sitemaps are ordered — by section, or by date — so taking the first N gathers
    one corner of the site and calls it a sample. An even stride over the whole
    list crosses every section a sitemap happens to be grouped by, and because the
    step is arithmetic rather than random, two runs over an unchanged sitemap still
    pick the same pages. Reproducibility is the constraint here, which is why this
    is not `random.sample` with a seed: no state, nothing to store, nothing to
    explain in the report.

    The first URL is always kept — for a sitemap that leads with the home page,
    dropping it would be perverse.
    """
    if limit <= 0:
        return []
    if len(urls) <= limit:
        return list(urls)
    if limit == 1:
        return [urls[0]]
    # Spread across the closed interval, so the first and the **last** URL are both
    # picked. A plain `i * len/limit` step starts at 0 and stops a whole step short
    # of the end, which leaves the tail of a large sitemap unreachable at any sample
    # size — the same blind spot as taking the first N, moved to the other end.
    last = len(urls) - 1
    picked, seen = [], set()
    for i in range(limit):
        u = urls[round(i * last / (limit - 1))]
        if u not in seen:
            seen.add(u)
            picked.append(u)
    return picked


def discover_urls(base_url: str, limit: int, inventory: dict | None = None) -> list[str]:
    """Pick up to `limit` same-host URLs, sitemap first, on-page links second.

    With an `inventory` from the shared crawl, the candidates come out of it and this
    costs nothing: the crawl already fetched the sitemap, followed the links and
    honoured robots.txt, so re-doing all three here was the same site answering the
    same questions twice.

    The picks are spread across the whole list by `stride()` rather than taken from
    the top, so the set spans the site instead of its newest corner, and stays the
    same across runs. On-page links are used only when no sitemap answers.

    URLs that `robots.txt` disallows are dropped: these are pages *we* chose to
    look at, not the URL the operator asked about, so the site's own instruction to
    crawlers applies. The entry URL is always kept — a robots block on it is a
    finding to report, not a reason to audit nothing.

    Returns [] when neither source yields anything — the caller then audits the
    single entry URL and says so, rather than claiming to have looked wider."""
    try:
        from lib.safe_http import robots_allows, safe_get
    except ImportError:
        from scripts.lib.safe_http import robots_allows, safe_get
    host = urlparse(base_url).netloc
    found: list[str] = []

    def same_host(u: str) -> bool:
        return urlparse(u).netloc == host

    if inventory:
        # 200-only: a sampled URL that turns out to be a 404 fails every page-level
        # check, and the worst page decides the verdict.
        found = [key for key, row in sorted((inventory.get("pages") or {}).items())
                 if row.get("html") and row.get("status") == 200
                 and same_host(key) and looks_like_a_page(key)]

    for path in SITEMAP_PATHS if not found else ():
        if found:
            break
        try:
            xml = safe_get(f"{urlparse(base_url).scheme}://{host}{path}", timeout=15).text
        except Exception:
            continue
        locs = LOC_RE.findall(xml)
        # A sitemap index points at more sitemaps; follow one level.
        nested = [u for u in locs if u.endswith(".xml")]
        pages = [u for u in locs if not u.endswith(".xml")]
        for n in nested[:3]:
            try:
                pages += LOC_RE.findall(safe_get(n, timeout=15).text)
            except Exception:
                pass
        # Sitemaps list PDFs and images too — the same extension filter applies.
        found += [u for u in pages if same_host(u) and looks_like_a_page(u)]

    if not found:
        try:
            html = safe_get(base_url, timeout=15).text
            for h in ANCHOR_RE.findall(html):
                # Drop the fragment, keep the query: `?id=7` is usually what
                # makes the URL a distinct page, and cutting it produced a
                # different address that frequently 404s.
                h = h.split("#", 1)[0].strip()
                if not h or h.startswith(("mailto:", "tel:", "javascript:", "data:")):
                    continue
                u = h if h.startswith("http") else urljoin(base_url, h)
                if same_host(u) and looks_like_a_page(u):
                    found.append(u)
        except Exception:
            pass

    # Deduplicate before striding, or the step lands repeatedly on the same page in
    # a sitemap that lists a URL under several paths.
    unique, seen_raw = [], set()
    for u in found:
        norm = u.rstrip("/") or u
        if norm != (base_url.rstrip("/") or base_url) and norm not in seen_raw:
            seen_raw.add(norm)
            unique.append(norm)

    # `limit - 1` because the entry URL takes one of the slots below.
    candidates = stride(unique, max(limit - 1, 0))
    allowed = [u for u in candidates if robots_allows(u)[0]]
    if len(allowed) < len(candidates):
        print(f"  {len(candidates) - len(allowed)} sampled URL(s) skipped: "
              f"robots.txt disallows them", file=sys.stderr)

    seen, out = set(), []
    for u in [base_url] + allowed:
        u = u.rstrip("/") or u
        if u not in seen:
            seen.add(u)
            out.append(u)
        if len(out) >= limit:
            break
    return out


PAGE_LEVEL = {"offline", "fetch"}


def is_page_level(item: dict) -> bool:
    """True when the check judges one page rather than the whole site."""
    return (item.get("check") or {}).get("requires", "fetch") in PAGE_LEVEL


# Inputs the operator hands us rather than ones we collect: a browser trace, a
# rendered-page measurement, a Search Console export, a server log. None can be
# re-taken by this run, which is what separates them from every other check.
#
# Two describe one URL at one moment, and those are the ones whose subject the
# guard checks. Link exports and server logs describe a whole site and have no
# subject to check — asking whether either "describes the audited page" is not a
# question about them. All four remain artifact inputs so an item that reads one
# stays out of the per-page sample, where it would reuse the same file per page.
PAGE_SUBJECT_ARTIFACT_KEYS = ("cwv_json", "rendered_json")
ARTIFACT_CTX_KEYS = PAGE_SUBJECT_ARTIFACT_KEYS + ("links_csv", "server_log")


def ctx_keys_of(item: dict) -> set[str]:
    """The `{placeholder}` names an item's argv asks for."""
    return {a[1:-1] for a in ((item.get("check") or {}).get("args") or [])
            if isinstance(a, str) and a.startswith("{") and a.endswith("}")}


def reads_artifact(item: dict) -> bool:
    return bool(ctx_keys_of(item) & set(ARTIFACT_CTX_KEYS))


def artifact_subject(path: str) -> str | None:
    """The URL an artifact claims to describe, or None when it does not say.

    Read leniently and on purpose: this is a guard, not a parser. The scripts
    that consume these files do their own validation and report their own
    errors, so an unreadable artifact must not raise here — it has to reach
    `cwv_metrics.py` and be refused there, where the message names the field.
    """
    try:
        with open(os.path.expanduser(path), encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    nested = raw.get("metrics") if isinstance(raw.get("metrics"), dict) else {}
    url = raw.get("url") or nested.get("url")
    return url if isinstance(url, str) and url.strip() else None


def artifact_age_days(path: str) -> int | None:
    """How long ago the file was last written, in whole days, or None if unreadable.

    The filesystem's own record and **not** a timestamp inside the file. That
    distinction is the whole of what this adds: everything an artifact says about
    itself is the operator's claim, including any date it carries, so a trace of
    yesterday's staging build can describe today's URL and say so. An mtime is still
    forgeable — `touch` exists — but it is not forgeable by *writing JSON*, which is
    what producing one of these files involves, and a stale file usually goes stale by
    being left alone rather than by anybody deciding to lie.

    So this does not make the age verifiable. It makes it **visible and boundable**,
    which is as far as re-measuring cannot reach.
    """
    try:
        mtime = os.path.getmtime(os.path.expanduser(path))
    except OSError:
        return None
    return max(0, int((time.time() - mtime) // 86400))


def same_page(a: str, b: str) -> bool:
    """Whether two URLs name the same page, for the purpose of trusting a file.

    Deliberately narrow. Scheme, a bare trailing slash and a `www.` prefix are
    noise — nobody traces `https://example.com` and means something other than
    `https://example.com/`, and the two hosts redirect to each other on nearly
    every site there is. A different host or a different path is a different
    page, and a measurement taken there is not evidence about this one.
    """
    def key(u: str) -> tuple[str, str, str, str]:
        p = urlparse(u.strip())
        return (p.netloc.lower().removeprefix("www."), p.path.rstrip("/"),
                p.params, p.query)
    return key(a) == key(b)


# basis: convention — definitional: aggregating a page-level check across sampled pages
#  takes the worst verdict, so FAIL must outrank WARM and WARN outrank PASS
STATUS_RANK = {FAIL: 3, WARN: 2, PASS: 1}


def aggregate_pages(primary: list[dict], per_page: list[list[dict]]) -> list[dict]:
    """Fold per-page verdicts into one row per item.

    The worst verdict wins, because a check that fails on any sampled page fails
    for the site — but the evidence always carries the count, so "3 of 8 pages"
    never reads the same as "every page". Site-level items keep the primary
    run's verdict untouched."""
    by_id: dict[str, list[dict]] = {}
    for page in per_page:
        for row in page:
            by_id.setdefault(row["id"], []).append(row)

    out = []
    for row in primary:
        runs = by_id.get(row["id"], [])
        if not is_page_level(row) or len(runs) < 2:
            out.append(row)
            continue
        decided = [r for r in runs if r["status"] in STATUS_RANK]
        if not decided:
            row = dict(row, pages_checked=len(runs))
            out.append(row)
            continue
        worst = max(decided, key=lambda r: STATUS_RANK[r["status"]])
        bad = [r for r in decided if r["status"] == worst["status"]]
        # The measurement has to come from the same page as the verdict. It did
        # not: the row kept the entry page's numbers while the status came from
        # the worst sampled page, so a report could say "52 characters, 60 is the
        # limit" directly under a FAIL — a passing number beside a failing verdict,
        # which is worse than printing the raw assertion.
        detail = worst["evidence"]
        if worst.get("url"):
            detail = f"{worst['url']}: {detail}"
        if len({r["evidence"] for r in bad}) > 1:
            detail += "; values differ"
        coverage = f"{len(bad)}/{len(runs)} pages"
        if len(decided) != len(runs):
            coverage += f" ({len(runs) - len(decided)} undecided)"
        row = dict(row, status=worst["status"],
                   evidence=f"{coverage}: {detail}",
                   measure=worst.get("measure", row.get("measure")),
                   pages_checked=len(runs),
                   pages_decided=len(decided),
                   pages_matching=len(bad))
        if measure_contradicts_verdict(row):
            raise AssertionError(
                f"{row['id']} sampled {row['status']} carries a passing measure")
        out.append(row)
    return out


def opt_in_flags(mode: str, verify_bots: bool) -> dict[str, list[str]]:
    """Flags attached to script runs by mode or explicit operator permission."""
    flags: dict[str, list[str]] = {}
    if mode != "archive":
        flags["hreflang_checker.py"] = ["--verify-returns"]
    if verify_bots:
        flags["server_log_audit.py"] = ["--verify-bots"]
    return flags


PSL_PATH = os.path.join(SKILL_DIR, "resources", "config", "public_suffix_list.dat")
_PSL_CACHE: tuple[frozenset, frozenset, frozenset] | None = None
_PSL_WARNED = False


def load_public_suffixes(path: str = ""):
    """Parse the Public Suffix List into (exact, wildcard, exception) rule sets.

    The path is resolved at call time, not frozen into the default argument: a
    default binds once at import and then cannot be pointed anywhere else, which
    makes the missing-list branch untestable and any override silently ignored.

    Both sections are kept. The private section is the one that matters most
    here: `github.io`, `vercel.app`, `myshopify.com` and their kind are exactly
    the hosts a small site sits on, and only the private section names them.
    """
    exact, wildcard, exception = set(), set(), set()
    with open(path or PSL_PATH, encoding="utf-8") as f:
        for line in f:
            rule = line.strip().lower()
            if not rule or rule.startswith("//"):
                continue
            if rule.startswith("!"):
                exception.add(rule[1:])
            elif rule.startswith("*."):
                wildcard.add(rule)
            else:
                exact.add(rule)
    return frozenset(exact), frozenset(wildcard), frozenset(exception)


# basis: convention — the Public Suffix List changes continuously, so any staleness line
#  is arbitrary. A year is long enough that the warning means the snapshot was forgotten
#  rather than merely not refreshed this week
PSL_STALE_DAYS = 365


def html_parser() -> str:
    """Which parser the evidence scripts will read pages with, for the record.

    Imported lazily and defensively: the runner is deliberately importable without
    bs4 or lxml so `--archive` can run on a bare checkout, and this is only needed to
    fill one field in the artifact. An unimportable `seo_common` records "unknown"
    rather than failing the run over a label.
    """
    try:
        from seo_common import html_parser as choose
        return choose()
    except Exception:  # noqa: BLE001 — a missing label must not fail an audit
        return "unknown"


def psl_snapshot_date(path: str = "") -> str:
    """The date recorded in the bundled list's header, "" when there is none."""
    try:
        with open(path or PSL_PATH, encoding="utf-8") as f:
            for line in f:
                if line.startswith("// snapshot taken "):
                    return line.split("taken", 1)[1].strip()
                if not line.startswith("//"):
                    break
    except OSError:
        return ""
    return ""


def psl_staleness(path: str = "") -> tuple[str, int]:
    """(snapshot date, age in days). Age is -1 when the date cannot be read.

    Worth saying during an audit and not only when somebody thinks to run
    --check: a stale list is missing the platform suffixes registered since it was
    taken, and the only symptom is a Search Console property that answers nothing.
    """
    taken = psl_snapshot_date(path)
    if not taken:
        return "", -1
    try:
        when = datetime.fromisoformat(taken).replace(tzinfo=timezone.utc)
    except ValueError:
        return taken, -1
    return taken, (datetime.now(timezone.utc) - when).days


def public_suffixes():
    """The parsed list, or None when it is not on disk. Loaded once per process."""
    global _PSL_CACHE
    if _PSL_CACHE is None:
        try:
            _PSL_CACHE = load_public_suffixes()
        except OSError:
            return None
    return _PSL_CACHE


def suffix_label_count(labels: list[str], rules) -> int:
    """How many trailing labels form the public suffix, per the PSL algorithm."""
    exact, wildcard, exception = rules
    best = 1  # the implicit default rule, `*`
    for i in range(len(labels)):
        candidate = labels[i:]
        joined = ".".join(candidate)
        if joined in exception:
            # An exception rule says this is *not* a public suffix; the prevailing
            # rule is the same one minus its leftmost label.
            best = max(best, len(candidate) - 1)
        elif joined in exact:
            best = max(best, len(candidate))
        elif len(candidate) > 1 and "*." + ".".join(candidate[1:]) in wildcard:
            best = max(best, len(candidate))
    return best


def registrable_domain(host: str) -> str:
    """Reduce a hostname to the domain a Search Console property is keyed on:
    `www.example.com` is not a `sc-domain:` property, `example.com` is.

    Uses the bundled Public Suffix List. The seven hard-coded suffixes this
    replaced got the common ccTLD shapes right (`example.co.uk`, `example.com.br`)
    and every platform domain wrong: `something.github.io` became `github.io`,
    `myapp.vercel.app` became `vercel.app`. The default property was then one
    nobody owns, and every Search Console item came back empty — which reads as a
    site with no search traffic rather than as a property that does not exist.
    """
    host = (host or "").strip().lower().rstrip(".")
    # A bracketed IPv6 literal is full of colons, so the port cannot be split off
    # before the brackets are.
    if host.startswith("["):
        bare = host[1:host.index("]")] if "]" in host else host[1:]
    else:
        bare = host.split(":")[0]
    # An address has no registrable domain, and the label arithmetic below is happy
    # to invent one: 127.0.0.1 came out as "0.1", which built the property
    # `sc-domain:0.1` and crashed the two Search Console scripts handed it. On a
    # public IP it would have been quieter and worse — a syntactically valid
    # property nobody owns answers with nothing, and nothing reads as a site with
    # no search traffic. Found the first time the live path was pointed at a
    # fixture server, which is what --allow-private exists to make possible.
    try:
        ipaddress.ip_address(bare)
        return ""
    except ValueError:
        pass
    labels = [part for part in bare.split(".") if part]
    if len(labels) <= 2:
        return ".".join(labels)

    rules = public_suffixes()
    if rules is None:
        # Say so rather than guess quietly: the fallback is the old heuristic, and
        # it is wrong about exactly the hosts people run small sites on.
        global _PSL_WARNED
        if not _PSL_WARNED:
            _PSL_WARNED = True
            print(f"  public suffix list not found at {PSL_PATH}; falling back to "
                  f"a heuristic. Pass --gsc-property if the default looks wrong.",
                  file=sys.stderr)
        second_level = {"co", "com", "net", "org", "gov", "edu", "ac"}
        keep = 3 if labels[-2] in second_level else 2
        return ".".join(labels[-keep:])

    keep = suffix_label_count(labels, rules) + 1
    return ".".join(labels[-keep:]) if keep <= len(labels) else ".".join(labels)


def find_gsc_credentials(explicit: str) -> str:
    """Locate a Search Console service account key. Checked in order: the flag,
    GSC_CREDENTIALS_PATH, GV_SA_KEY, then known local defaults. Returns "" when
    none exists, which downgrades GSC items to NO_DATA rather than failing."""
    for cand in (explicit, os.environ.get("GSC_CREDENTIALS_PATH", ""),
                 os.environ.get("GV_SA_KEY", ""), *GSC_FALLBACKS):
        if cand and os.path.isfile(os.path.expanduser(cand)):
            return os.path.expanduser(cand)
    return ""


def run_label(key: tuple) -> str:
    """Return the stable label used to join compact and full run artifacts."""
    return f"{key[0]} {' '.join(str(x) for x in key[1][1:])}".strip()


def summarize_runs(results: dict) -> dict:
    """Keep only timing and failure state in the email-sized results artifact."""
    return {
        run_label(key): {
            "elapsed": value.get("__elapsed__"),
            "error": value.get("__error__"),
            "error_kind": value.get("__error_kind__"),
        }
        for key, value in results.items()
    }


def evidence_runs(results: dict) -> dict:
    """Keep each successful parsed output; retain the run summary for failures."""
    summaries = summarize_runs(results)
    out = {}
    for key, value in results.items():
        label = run_label(key)
        if value.get("__error__"):
            out[label] = summaries[label]
        else:
            out[label] = {k: v for k, v in value.items()
                          if not str(k).startswith("__")}
    return out


def evidence_artifact(results: dict, pages: dict | None = None) -> dict:
    """Build the evidence artifact without flattening page runs into site runs.

    ``pages=None`` means no sampling occurred and deliberately omits the ``pages``
    key, preserving the pre-sampling artifact shape. An empty mapping means a
    sampled run had no page output and is retained so absence is still explicit.
    """
    out = evidence_runs(results)
    if pages is not None:
        out["pages"] = pages
    return out


def write_evidence(path: str, evidence: dict, secrets: tuple[str, ...] = ()) -> None:
    """Write a complete, redacted evidence artifact without changing its shape."""
    with open(os.path.expanduser(path), "w", encoding="utf-8") as stream:
        json.dump(redact(evidence, secrets), stream, ensure_ascii=False, indent=2)


def archive_entry(archive_dir: str, entry: str) -> str:
    """Pick the HTML file to analyse inside a local site copy."""
    root = os.path.expanduser(archive_dir)
    if not os.path.isdir(root):
        return ""
    if entry:
        p = entry if os.path.isabs(entry) else os.path.join(root, entry)
        return p if os.path.isfile(p) else ""
    for name in ("index.html", "index.htm"):
        p = os.path.join(root, name)
        if os.path.isfile(p):
            return p
    for dirpath, _dirs, files in os.walk(root):
        for f in sorted(files):
            if f.lower().endswith((".html", ".htm")):
                return os.path.join(dirpath, f)
    return ""


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Run the SEO checklist registry against a URL")
    ap.add_argument("url")
    ap.add_argument("--registry", default=REGISTRY)
    ap.add_argument("--json", dest="json_out", default="checklist-results.json")
    ap.add_argument("--only", default="", help="comma-separated category keys")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--timeout", type=int, default=180)
    ap.add_argument("--diff", action="store_true", help="compare against the previous run")
    ap.add_argument("--no-history", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--mode", choices=sorted(MODE_CAPS), default="",
                    help="; ".join(f"{k}: {v}" for k, v in MODE_HELP.items())
                         + " (default: archive when --archive is given, else live)")
    ap.add_argument("--archive", default="",
                    help="directory holding a local copy of the site")
    ap.add_argument("--entry", default="",
                    help="entry HTML inside --archive (default: index.html, else first *.html)")
    ap.add_argument("--gsc-credentials", default="",
                    help="service account JSON; falls back to GSC_CREDENTIALS_PATH, "
                         "GV_SA_KEY, then ~/.config/gcloud/gsc-service-account.json")
    ap.add_argument("--max-rps", type=float, default=None, metavar="N",
                    help="requests per second per host, across all evidence "
                         "scripts (default 4). 0 removes the pacing. An audit is a "
                         "burst by construction — the scripts run concurrently and "
                         "several walk a sitemap inside their own process.")
    ap.add_argument("--allow-private", action="store_true",
                    help="permit hosts on loopback, RFC 1918, ULA or CGNAT "
                         "addresses — a staging site before launch, or a fixture "
                         "served locally. Off by default. Link-local stays "
                         "blocked either way (cloud instance metadata). Recorded "
                         "in the results and printed in the report: an audit of a "
                         "private copy is not an audit of the public site.")
    ap.add_argument("--cwv-json", default="",
                    help="JSON file of Core Web Vitals from a local browser trace "
                         "(chrome-devtools MCP). Lab data, reported separately from "
                         "the CrUX field data PageSpeed provides. Without it the "
                         "three lab items report NEEDS_INPUT.")
    ap.add_argument("--rendered-json", default="",
                    help="JSON of measurements taken from the rendered page "
                         "(chrome-devtools MCP). Answers font size, link "
                         "distinctness, overlays and — from a mobile render — tap "
                         "targets. Without it those items report NEEDS_INPUT.")
    ap.add_argument("--crawl-json", default="", metavar="PATH",
                    help="where to write the crawl inventory the site-wide checks "
                         "read (default: alongside --json, as *-crawl.json). It is "
                         "the audit's record of which URLs exist and which are "
                         "broken, so it is kept rather than discarded.")
    ap.add_argument("--evidence-json", default="", metavar="PATH",
                    help="where to write every evidence script's parsed JSON "
                         "output. Keys match the compact runs summary so the two "
                         "artifacts can be joined without embedding bulky evidence "
                         "in the emailed checklist results.")
    ap.add_argument("--crawl-depth", type=int, default=3, metavar="N",
                    help="link depth for the shared crawl (default: 3)")
    ap.add_argument("--crawl-max-pages", type=int, default=100, metavar="N",
                    help="page budget for the shared crawl (default: 100). It is "
                         "one crawl for all the site-wide checks now, so this is "
                         "the audit's whole crawl budget rather than one of six.")
    ap.add_argument("--links-csv", default="",
                    help="Search Console Links report export (ZIP or CSV). The "
                         "Links report has no API, so incoming-link items stay "
                         "NEEDS_INPUT without it.")
    ap.add_argument("--keyword", default="",
                    help="primary keyword this page is meant to rank for. KW-076 "
                         "stays NEEDS_INPUT without it.")
    ap.add_argument("--profile", default="",
                    help="site profile: default, local, ecommerce, saas, blog, "
                         "media, or 'auto' to accept the detector's suggestion. "
                         "Asked interactively when omitted and a terminal is "
                         "attached; otherwise default (the full registry).")
    ap.add_argument("--no-prompt", action="store_true",
                    help="never ask for a profile, even on a terminal")
    ap.add_argument("--history-limit", type=int, default=HISTORY_RUNS, metavar="N",
                    help=f"how many stored runs the trend reads (default: "
                         f"{HISTORY_RUNS}). The report shows score and reach over "
                         f"that span, and how long each open item has been failing.")
    ap.add_argument("--server-log", default="",
                    help="server access log (combined format or JSON lines, .gz "
                         "fine). The only evidence here about what crawlers "
                         "actually did rather than what the site offers them; "
                         "CI-018 is NEEDS_INPUT without it. A week or more of log is "
                         "worth much more than a day.")
    ap.add_argument("--no-http-cache", action="store_true",
                    help="fetch every URL again in every script instead of once "
                         "per run. Slower, more requests, and the page-level "
                         "items may then be reporting on different copies of a "
                         "page that changed mid-audit — use it to check whether "
                         "the cache is what a surprising result is about.")
    ap.add_argument("--no-page-guard", action="store_true",
                    help="audit the entry page even when it looks like a bot "
                         "challenge or a soft 404. The suspicion is still "
                         "recorded; use this when auditing an error page on "
                         "purpose, or when the guard is wrong about your page.")
    ap.add_argument("--sample", type=int, default=1, metavar="N",
                    help="audit N pages instead of one; page-level checks are "
                         "aggregated across them, site-level checks run once")
    ap.add_argument("--max-artifact-age", type=int, default=0, metavar="DAYS",
                    help="refuse a --cwv-json or --rendered-json file last written "
                         "more than DAYS ago. Off by default, because there is no "
                         "honest default: how stale a measurement may be depends on "
                         "how often the page changes. The age is recorded and shown "
                         "either way.")
    ap.add_argument("--verify-bots", action="store_true",
                    help="confirm every claimed search crawler in a --server-log by "
                         "reverse-then-forward DNS. Off by default because it is a "
                         "network call about a third party, and without it the crawl "
                         "figures rest on a User-Agent string the client chose. "
                         "Recorded in the artifact either way.")
    ap.add_argument("--gsc-property", default="",
                    help="Search Console property (default: sc-domain:<registrable domain>). "
                         "Must be one the service account can read — it is not always the "
                         "same string as the audited URL.")
    return ap


def resolve_mode(a) -> tuple[str, set[str]]:
    mode = a.mode or ("archive" if a.archive else "live")
    if a.archive and mode != "archive":
        print(f"--archive given but --mode {mode}: archive files will be ignored",
              file=sys.stderr)
    return mode, set(MODE_CAPS[mode])


def resolve_gsc(a, caps, mode) -> str:
    gsc_path = find_gsc_credentials(a.gsc_credentials)
    # Search Console is an external API, so it is offered only by modes allowed
    # to reach external services at all. Without this gate a key that merely
    # happens to sit on disk pulls `archive` — documented as making no network
    # calls whatsoever — into querying Google about the audited property.
    if gsc_path and "api" not in caps:
        if not a.quiet:
            print(f"  GSC credentials found, but {mode} mode makes no network "
                  f"calls; Search Console items report N/A", file=sys.stderr)
        return ""
    return gsc_path


def print_report(payload, a, hist, crawl_path, diff_note) -> None:
    mode = payload["mode"]
    audit_url = payload["url"]
    entry_error = payload.get("entry_error") or ""
    entry_guard = payload.get("entry_guard") or ""
    s = payload["scores"]
    print(f"\nMode: {mode}   GSC: {'yes' if payload['gsc_credentials_found'] else 'no'}")
    if entry_error:
        print(f"UNREACHABLE: {audit_url} could not be read — {entry_error}.")
        print(f"No score: nothing about this site was measured. "
              f"{s['decided']}/{s['total_items']} items decided.")
    else:
        print(f"SEO Score: {s['seo_score']}/100 — over {s['decided']} items, "
              f"{s['weight_pct']}% of the weight in scope")
    # The partition, not a percentage. Every item is in one line and the lines add
    # up to the registry, which is the property a reader can check by eye.
    p, w = s["partition"], s["waiting_on_you"]
    waiting = ""
    if p["waiting_on_you"]:
        halves = [f"{w['llm_pending']} unanswered LLM item(s)" if w["llm_pending"] else "",
                  f"{w['needs_input']} missing input(s)" if w["needs_input"] else ""]
        waiting = "   (" + ", ".join(h for h in halves if h) + ")"
    print(f"  decided          {p['decided']:>4}")
    print(f"  waiting on you   {p['waiting_on_you']:>4}{waiting}")
    print(f"  needs a person   {p['needs_a_person']:>4}")
    print(f"  undecided        {p['undecided']:>4}")
    if p["not_applicable"]:
        print(f"  not applicable   {p['not_applicable']:>4}")
    print(f"  {'':<15}  ---- {s['total_items']} items in the registry")
    if payload["requested_url"]:
        print(f"Redirected: {payload['requested_url']} -> {audit_url} "
              f"(another host; the destination was audited)")
    if a.allow_private and mode != "archive":
        # Printed even under --quiet, which suppresses the header: the one line a
        # reader needs to know this is not the public site must not be optional.
        # Archive mode is excluded because it makes no requests at all, and a
        # caveat about a network the run never touched is noise dressed as candour.
        print("Private addresses allowed (--allow-private): this run could reach a "
              "host that is not on the public internet. If it did, these verdicts "
              "describe a local or staging copy, not what a visitor sees.")
    if entry_guard and not entry_error:
        print(f"WARNING: the entry page looks like {entry_guard.replace('_', ' ')} "
              f"and was audited anyway (--no-page-guard). Every verdict above "
              f"describes that page, not the site.")
    if payload["script_failures"]:
        parts = ", ".join(f"{n} {kind}" for kind, n in payload["script_failures"].items())
        print(f"Script failures: {parts}"
              + ("  — timeouts are retryable: raise --timeout or lower --workers"
                 if "timeout" in payload["script_failures"] else ""))
    c = payload.get("crawl")
    if c and c.get("broken"):
        print(f"\nBroken URLs ({len(c['broken'])}):")
        for row in c["broken"][:10]:
            where = (f" — linked from {row['linked_from'][0]}"
                     + (f" and {len(row['linked_from']) - 1} other page(s)"
                        if len(row["linked_from"]) > 1 else "")
                     if row.get("linked_from") else " — in the sitemap only")
            print(f"  [{row['status'] or 'no response'}] {row['url']}{where}")
        if len(c["broken"]) > BROKEN_URLS_SHOWN:
            print(f"  … {len(c['broken']) - BROKEN_URLS_SHOWN} more in {c['inventory']}")
    print(f"\nResults: {os.path.abspath(a.json_out)}")
    if payload.get("evidence_path"):
        print(f"Evidence: {os.path.abspath(os.path.expanduser(a.evidence_json))}")
    elif any(row.get("measure") for row in payload.get("items", [])):
        print("Full script evidence was reduced to checklist measures; rerun with "
              "--evidence-json PATH to keep the parsed outputs.")
    if crawl_path and os.path.exists(crawl_path):
        print(f"Crawl:   {os.path.abspath(crawl_path)}")
    if hist:
        print(f"History: {hist}")
    if a.diff:
        d = payload.get("diff")
        if d is None:
            print("Diff: no previous run for this domain")
        elif not d:
            print("Diff: no status changes since the previous run")
        else:
            print(f"\nChanged since previous run ({len(d)}):")
            origins = {i["id"]: i.get("decided_by") or "measured"
                       for i in payload.get("items", [])}
            for c in d:
                # Without this, a claimed PASS in the item list borrows the authority
                # of an identically printed measured PASS.
                origin = origins.get(c["id"], "measured")
                marker = {"claimed": " (claimed)",
                          "model": " (model-read)"}.get(origin, "")
                print(f"  {c['from']} -> {c['to']}{marker}  "
                      f"{c['id']} {c['title']}")
        if diff_note:
            print(f"Diff scope: {diff_note}")


def main() -> int:
    a = build_parser().parse_args()

    # Passed to the evidence scripts through the environment, because they are
    # separate processes and the pacing they share is keyed on it.
    if a.max_rps is not None:
        os.environ["SEO_MAX_RPS"] = str(a.max_rps)
    # Same reason: 55 scripts in 55 processes each call assert_safe_url for
    # themselves, so the allowance has to travel with them. Deliberately one
    # switch for the whole run rather than a per-script flag — a run that reaches
    # a private address in one script and not another would be impossible to
    # describe honestly in the artifact.
    if a.allow_private:
        os.environ["SEO_ALLOW_PRIVATE"] = "1"

    mode, caps = resolve_mode(a)

    http_cache = ""
    http_cache_baseline = 0
    if caps & {"fetch", "crawl", "api"} and not a.no_http_cache:
        http_cache = open_http_cache()
        if http_cache:
            from lib.safe_http import cache_hit_baseline
            http_cache_baseline = cache_hit_baseline()

    gsc_path = resolve_gsc(a, caps, mode)

    with open(a.registry, encoding="utf-8") as f:
        registry = json.load(f)
    items = registry["items"]
    registry_version = registry.get("registry_version", "unknown")
    if a.only:
        keep = {c.strip() for c in a.only.split(",") if c.strip()}
        items = [i for i in items if i["category"] in keep]
        if not items:
            print(f"No items match --only {a.only}", file=sys.stderr)
            return 2

    stamp = run_stamp()

    if not a.quiet:
        print(f"Checklist audit: {a.url}", file=sys.stderr)
        print(f"  mode: {mode} — {MODE_HELP[mode]}", file=sys.stderr)
        print(f"  GSC: {gsc_path or 'no credentials found'}", file=sys.stderr)
        print(f"  registry: {len(items)} items "
              f"(version {registry_version})", file=sys.stderr)
        if mode != "archive":
            from lib.safe_http import max_rps
            rps = max_rps()
            print(f"  rate limit: {rps} request(s)/second per host"
                  if rps else "  rate limit: OFF — every script goes as fast as it can",
                  file=sys.stderr)
            print("  response cache: one fetch per URL for this run"
                  if http_cache else
                  "  response cache: OFF (--no-http-cache) — every script fetches "
                  "for itself, and two of them may read different copies of a page "
                  "that changes",
                  file=sys.stderr)
            if a.allow_private:
                print("  private addresses: ALLOWED (--allow-private) — loopback, "
                      "RFC 1918, ULA and CGNAT; link-local stays blocked",
                      file=sys.stderr)

    # The entry page is fetched before the profile is settled so detection can
    # read it — one request, not two, and archive mode gets the same treatment.
    temp_html = ""
    entry_error = ""
    entry_guard = ""
    entry_words = -1
    audit_url = a.url
    if mode == "archive":
        html_path = archive_entry(a.archive, a.entry)
        if not html_path:
            print(f"No HTML entry point found in {a.archive!r}", file=sys.stderr)
            return 2
        if not a.quiet:
            print(f"  entry: {html_path}", file=sys.stderr)
        # A saved copy can be a challenge page too — somebody archives a site
        # they were blocked from and the audit grades the interstitial.
        with open(html_path, encoding="utf-8", errors="replace") as f:
            entry_html = f.read()
        entry_guard, guard_detail = page_guard(entry_html)
        entry_words = visible_words(entry_html)
        if entry_guard and not a.no_page_guard:
            entry_error = guard_detail
    else:
        fetched = fetch_page(a.url, enforce_guard=not a.no_page_guard)
        html_path, entry_error, entry_guard = fetched.path, fetched.error, fetched.guard
        temp_html = html_path
        # Audit the URL the request actually landed on when the host changed.
        # Otherwise every script is handed the address that redirected away:
        # discover_urls filters on the old netloc and the sample collapses to one
        # page, and the Search Console property is derived from a domain the
        # service account cannot read. A same-host redirect keeps the requested
        # URL, so redirect_checker.py can still see the hop it is there to report.
        audit_url = audit_target(a.url, fetched.final_url)
        if audit_url != a.url:
            print(f"  redirected to another host: {a.url} -> {audit_url}\n"
                  f"  auditing the destination; Search Console property and the "
                  f"URL sample follow it", file=sys.stderr)
        if html_path:
            with open(html_path, encoding="utf-8", errors="replace") as f:
                entry_words = visible_words(f.read())
        if entry_error:
            print(f"\n  ENTRY PAGE UNREACHABLE: {entry_error}\n"
                  f"  Every check that reads the live site reports NO_DATA. "
                  f"Nothing about this site was measured.", file=sys.stderr)
        elif entry_guard:
            print(f"\n  WARNING: the entry page looks like "
                  f"{entry_guard.replace('_', ' ')}, audited anyway "
                  f"(--no-page-guard). Every verdict below describes that page.",
                  file=sys.stderr)

    # A page with no prose is audited, not refused — but the reader has to know,
    # because every page-level verdict below then describes an empty shell.
    if not entry_error and 0 <= entry_words < THIN_ENTRY_WORDS:
        print(f"\n  WARNING: the entry page carries {entry_words} visible "
              f"word(s). If the site is client-rendered or behind bot protection this "
              f"guard does not recognise, the page-level verdicts describe the "
              f"shell, not the content. The JS-rendering items report on it.",
              file=sys.stderr)

    domain = urlparse(audit_url).netloc or "unknown"
    # Whether the audited host is one only this machine can reach. Keyed on where
    # it resolves, not on whether --allow-private was passed: the flag permits a
    # private address, it does not make a public site private, and treating the two
    # as the same thing would drop the external-API checks on an ordinary audit.
    entry_private = False
    if mode != "archive" and not entry_error:
        from lib.safe_http import is_private_host
        entry_private = is_private_host(audit_url)

    derived = registrable_domain(urlparse(audit_url).netloc)
    gsc_property = a.gsc_property or (f"sc-domain:{derived}" if derived else "")
    # Two ways there is no property to ask about, both of which used to produce one
    # anyway. Neither is a missing credential, so neither may report itself as one.
    if gsc_path and not gsc_property:
        if not a.quiet:
            print(f"  Search Console skipped: {domain} is an address, and an address "
                  f"has no registrable domain to build a property from. Pass "
                  f"--gsc-property if a property covers this host.", file=sys.stderr)
        gsc_path = ""
    elif gsc_path and entry_private and not a.gsc_property:
        if not a.quiet:
            print(f"  Search Console skipped: {domain} is only reachable from here, "
                  f"so no property can cover it. Pass --gsc-property to query the "
                  f"live site's history against this copy.", file=sys.stderr)
        gsc_path = ""
    if gsc_path and not a.quiet:
        print(f"  GSC property: {gsc_property}", file=sys.stderr)
        # Only when a property was actually derived from the list: a stale snapshot
        # is missing suffixes registered since it was taken, and the only symptom
        # is a property that answers nothing.
        if not a.gsc_property:
            taken, age = psl_staleness()
            if age > PSL_STALE_DAYS:
                print(f"  public suffix list snapshot is {age} days old "
                      f"({taken}); refresh it with "
                      f"tools/refresh_public_suffix_list.py, or pass "
                      f"--gsc-property if that property looks wrong",
                      file=sys.stderr)

    # Only worth parsing while the answer is still open: an explicit --profile
    # other than `auto` has already decided.
    detected = detect_profile(html_path, audit_url) if a.profile in ("", "auto") else {}
    try:
        a.profile = choose_profile(a.profile, not (a.no_prompt or a.quiet), detected)
        profile = load_profile(a.profile)
    except KeyError as exc:
        print(exc, file=sys.stderr)
        if temp_html and os.path.exists(temp_html):
            os.unlink(temp_html)
        return 2
    excluded = profile_excludes(items, profile)
    preskip = {i: (NA, f"{why} ({a.profile})") for i, why in excluded.items()}
    # A profile exclusion is a scoping decision and outranks reachability: an
    # item that does not apply to this site type is N/A whether or not the page
    # loaded. Everything else the live site would have answered is undecided.
    if entry_error:
        # A page that read fine and is the wrong page also takes the offline
        # checks with it: the file is there and parses, so nothing else would
        # stop them from grading an interstitial's 12 words as a site.
        for item_id, skip in unreachable_skips(
                items, entry_error, wrong_page=bool(entry_guard)).items():
            preskip.setdefault(item_id, skip)
    elif entry_private:
        gate = set(NEEDS_THE_OUTSIDE_WORLD)
        if a.gsc_property:
            # An explicit property is a decision, the way `--profile auto` is: the
            # operator is saying this history belongs to this audit — a staging copy
            # of a live site is the obvious case — so the Search Console items are
            # left to answer for themselves rather than pre-empted here.
            gate.discard("gsc")
        for item_id, skip in private_host_skips(items, domain, gate).items():
            preskip.setdefault(item_id, skip)
    if not a.quiet and excluded:
        print(f"  profile: {a.profile} — {profile['label']}; "
              f"{len(excluded)} item(s) out of scope", file=sys.stderr)

    ctx = {"url": audit_url}
    if html_path:
        ctx["html"] = html_path
    if gsc_path:
        ctx["gsc_credentials"] = gsc_path
        ctx["gsc_property"] = gsc_property
    if a.links_csv:
        ctx["links_csv"] = os.path.expanduser(a.links_csv)
    if a.keyword:
        ctx["keyword"] = a.keyword
    if a.server_log:
        ctx["server_log"] = os.path.expanduser(a.server_log)
    if a.cwv_json:
        ctx["cwv_json"] = os.path.expanduser(a.cwv_json)
    if a.rendered_json:
        ctx["rendered_json"] = os.path.expanduser(a.rendered_json)
    for k, env in (("indexnow_key", "INDEXNOW_KEY"), ("pagespeed_key", "PAGESPEED_API_KEY")):
        if os.environ.get(env):
            ctx[k] = os.environ[env]

    # An artifact is the one input nothing in this run can verify by re-measuring.
    # Page artifacts can be checked against the audited URL; every artifact can at
    # least be dated. A stale site-level file can decide several site verdicts from
    # an obsolete crawl or traffic window, so the age limit must leave those items
    # NEEDS_INPUT instead of quietly grading the current site from old evidence.
    artifacts, rejected = {}, {}
    for key in ARTIFACT_CTX_KEYS:
        if key not in ctx:
            continue
        path = ctx[key]
        age = artifact_age_days(path)
        artifact = {"path": path, "age_days": age}
        matches = None
        if key in PAGE_SUBJECT_ARTIFACT_KEYS:
            claimed = artifact_subject(path)
            matches = None if not claimed else same_page(claimed, audit_url)
            artifact.update(describes=claimed, matches_audited_url=matches)
        # Site-level records deliberately omit subject and match: those fields are
        # not unknown, they are inapplicable. The report's `is not False` filter
        # still carries these records into its supplied-evidence warning.
        artifacts[key] = artifact
        if a.max_artifact_age and age is not None and age > a.max_artifact_age:
            if key in PAGE_SUBJECT_ARTIFACT_KEYS:
                rejected[key] = (
                    f"the artifact was last written {age} day(s) ago, over the "
                    f"{a.max_artifact_age}-day limit this run was given — "
                    f"re-measure the page")
            else:
                kind = {"links_csv": "link export",
                        "server_log": "server log"}[key]
                rejected[key] = (
                    f"the {kind} at {path} was last written {age} day(s) ago, over "
                    f"the {a.max_artifact_age}-day limit this run was given — "
                    f"supply a current file")
            print(f"  --{key.replace('_', '-')} ignored: {path} was written "
                  f"{age} day(s) ago", file=sys.stderr)
        elif key in PAGE_SUBJECT_ARTIFACT_KEYS and matches is False:
            rejected[key] = (f"the artifact describes {claimed}, not {audit_url} — "
                             f"re-measure the page being audited")
            print(f"  --{key.replace('_', '-')} ignored: it describes {claimed}, "
                  f"not {audit_url}", file=sys.stderr)
        elif key in PAGE_SUBJECT_ARTIFACT_KEYS and matches is None:
            # Allowed, because a file with no `url` predates this check and is
            # more likely careless than wrong. Recorded, because a reader of the
            # report is then the only one who can judge it.
            print(f"  --{key.replace('_', '-')}: the file does not say which URL "
                  f"it describes, so it cannot be checked against this audit",
                  file=sys.stderr)

    # One crawl, before the plan, for every check that needs the whole site.
    #
    # Six scripts used to walk the same pages independently — issue 1 in
    # KNOWN-ISSUES.md, measured at 181 requests against a seven-page fixture. They
    # read this instead. It runs here rather than as one of the planned jobs because
    # its output is another job's *input*, which is a thing the plan has no way to
    # express: `run_script` returns a dict, and what the six need is a file.
    crawl = None
    crawl_path = ""
    crawl_pages = None
    if "crawl" in caps and not entry_error:
        crawl_path = a.crawl_json or (
            os.path.splitext(a.json_out)[0] + "-crawl.json")
        if not a.quiet:
            print(f"  crawling once for the site-wide checks "
                  f"(depth {a.crawl_depth}, up to {a.crawl_max_pages} pages)",
                  file=sys.stderr)
        # Its own timeout: a 100-page crawl at the default 4 rps takes longer than a
        # single-page script has any business taking, and being killed for that would
        # take all site-wide items down with it.
        crawl = run_script("site_crawl.py",
                           [audit_url, "--out", crawl_path,
                            "--depth", str(a.crawl_depth),
                            "--max-pages", str(a.crawl_max_pages)],
                           timeout=max(a.timeout * 3, 300))
        why = crawl.get("error") or crawl.get("fetch_error")
        if why:
            # NO_DATA with this reason for every site-wide item, rather than verdicts
            # about a site nothing read.
            rejected["inventory_json"] = f"the shared crawl read nothing: {why}"
            print(f"  crawl failed: {why}\n"
                  f"  the site-wide checks report NO_DATA", file=sys.stderr)
        else:
            ctx["inventory_json"] = crawl_path
            # Read back for `--sample`: the crawl already knows which URLs exist and
            # which of them are pages, so discovering them again is a request the
            # site should not have to answer twice.
            try:
                with open(crawl_path, encoding="utf-8") as f:
                    crawl_pages = json.load(f)
            except (OSError, json.JSONDecodeError):
                crawl_pages = None
            s = crawl.get("summary") or {}
            if not a.quiet:
                print(f"  crawled {s.get('pages_fetched')} page(s) in "
                      f"{s.get('requests')} request(s); "
                      f"{s.get('pages_broken')} broken, "
                      f"{s.get('pages_redirected')} redirecting"
                      + (f"; truncated at --crawl-max-pages {a.crawl_max_pages}"
                         if s.get("truncated") else ""), file=sys.stderr)

    opt_in = opt_in_flags(mode, a.verify_bots)
    secrets = artifact_secrets(ctx)
    has_safe_browsing = any(os.environ.get(key) for key in SAFE_BROWSING_ENV_KEYS)
    prof_args = {k: list(v) for k, v in (profile.get("script_args") or {}).items()}
    plan, skipped = build_plan(items, ctx, caps, mode, preskip, bool(gsc_path),
                               rejected, opt_in, prof_args,
                               has_safe_browsing=has_safe_browsing)
    if prof_args and not a.quiet:
        for script, extra in sorted(prof_args.items()):
            print(f"  profile {a.profile}: {script} {' '.join(extra)}", file=sys.stderr)
    if not a.quiet:
        script_backed = sum(1 for i in items if i["source"] == "script")
        print(f"  {script_backed} script-backed items -> {len(plan)} unique runs"
              f" ({len(skipped)} skipped in this mode)", file=sys.stderr)

    results = execute(plan, a.workers, a.timeout, a.quiet)

    if temp_html and os.path.exists(temp_html):
        os.unlink(temp_html)

    graded = grade(items, plan, results, skipped, bool(gsc_path))

    sampled_urls: list[str] = []
    if a.sample > 1:
        if mode == "archive":
            print("  --sample ignored: archive mode audits the files you point it at",
                  file=sys.stderr)
        elif entry_error:
            print("  --sample skipped: the entry page could not be read, so there "
                  "is nothing to discover URLs from", file=sys.stderr)
        else:
            sampled_urls = discover_urls(audit_url, a.sample, inventory=crawl_pages)
            if len(sampled_urls) < 2:
                print("  --sample found no other URLs (no sitemap, no internal "
                      "links); auditing the single page", file=sys.stderr)
                sampled_urls = []

    page_evidence: dict[str, dict] | None = None
    if sampled_urls:
        # Artifact-backed items are page-level and still must not be sampled. The
        # file describes one URL; re-running the same reader against four other
        # pages produces four more copies of the same numbers, and the aggregate
        # then reports "4/4 pages" about pages nobody measured. Excluded here, so
        # those items keep the primary run's verdict about the page the artifact
        # is actually about.
        page_items = [i for i in items if is_page_level(i) and not reads_artifact(i)]
        per_page = []
        page_evidence = {}
        if not a.quiet:
            print(f"  sampling {len(sampled_urls)} pages for "
                  f"{len(page_items)} page-level checks", file=sys.stderr)
        for n, page_url in enumerate(sampled_urls, 1):
            page = fetch_page(page_url)
            page_html = page.path
            if page.error:
                # Dropped rather than graded. A sampled URL that turns out to be
                # an asset, an error page or a challenge would otherwise fail
                # every page-level check, and the worst verdict wins.
                print(f"  [{n}/{len(sampled_urls)}] skipped {page_url} — {page.error}",
                      file=sys.stderr)
                page_evidence[page_url] = {"skipped": True, "reason": page.error}
                continue
            pctx = dict(ctx, url=page_url, html=page_html)
            pplan, pskip = build_plan(page_items, pctx, caps, mode, preskip,
                                      bool(gsc_path), opt_in=opt_in,
                                      profile_args=prof_args,
                                      has_safe_browsing=has_safe_browsing)
            presults = execute(pplan, a.workers, a.timeout, True)
            per_page.append(grade(page_items, pplan, presults, pskip, bool(gsc_path)))
            page_evidence[page_url] = evidence_runs(presults)
            if os.path.exists(page_html):
                os.unlink(page_html)
            if not a.quiet:
                print(f"  [{n}/{len(sampled_urls)}] {page_url}", file=sys.stderr)
        if per_page:
            graded = aggregate_pages(graded, per_page)

    http_cache_hits = 0
    if http_cache:
        from lib.safe_http import cache_hit_count
        http_cache_hits = max(0, cache_hit_count() - http_cache_baseline)

    payload = {
        "url": audit_url,
        "domain": domain,
        "mode": mode,
        "archive": os.path.expanduser(a.archive) if mode == "archive" else None,
        "gsc_credentials_found": bool(gsc_path),
        "gsc_property": gsc_property if gsc_path else None,
        # Which measured-elsewhere files this run was handed, what page each one
        # claims to describe, and whether that is the page we audited. Belongs in
        # the artifact for the same reason `entry_guard` does: a run decided partly
        # from numbers a browser took at some other time is not the same document
        # as one decided entirely from what these scripts observed.
        "artifacts": artifacts or None,
        # The shared crawl: what it cost, what it found, and where the record is.
        # `broken` is the thing the report could never give anyone before — which
        # URLs are broken and which pages link to them, rather than a verdict about
        # the site.
        "crawl": None if not crawl else {
            "inventory": crawl_path,
            "depth": a.crawl_depth,
            "max_pages": a.crawl_max_pages,
            "error": crawl.get("error") or crawl.get("fetch_error"),
            "summary": crawl.get("summary"),
            "broken": crawl.get("broken"),
            "redirected": crawl.get("redirected"),
        },
        "started_at": datetime.now(timezone.utc).isoformat(),
        "registry_schema": registry.get("version"),
        "registry_version": registry_version,
        # Which instrument scored this run. SCR-2: the three tables are normative
        # constants, an edit to any of them is a change of instrument, and a score
        # carries no meaning across one. Stored whole and not only as the stamp, so
        # an archived run can still say what it was scored with after the tables in
        # the tree have moved on.
        "scoring_tables": {"stamp": scoring_stamp(), **scoring_tables()},
        "profile": a.profile,
        # Which slice of the registry this run covered. Without it a `--only`
        # run is indistinguishable in .seo-runs/ from a full one, and its score
        # — computed over a handful of categories — reads as a collapse.
        "only": sorted(keep) if a.only else None,
        "entry_reachable": not entry_error,
        "entry_error": entry_error or None,
        # What the entry page looked like, whether or not it stopped the run. A
        # `--no-page-guard` run that scored a challenge page must say so in the
        # artifact, or the file is the same lie the guard exists to prevent.
        "entry_guard": entry_guard or None,
        "entry_guard_enforced": bool(entry_guard) and not a.no_page_guard,
        # The URL as asked for, when it is not the URL that was audited.
        "requested_url": a.url if audit_url != a.url else None,
        # Visible-word count of the entry page, and how old the suffix list that
        # picked the Search Console property is. Both are the kind of thing a
        # reader can only judge if the artifact says it.
        "entry_visible_words": entry_words if entry_words >= 0 else None,
        "entry_thin": 0 <= entry_words < THIN_ENTRY_WORDS,
        # Whether this run was allowed off the public internet. It belongs in the
        # artifact for the same reason `entry_guard` does: a pre-launch audit of a
        # staging box and an audit of the live site produce the same-shaped file,
        # and only one of them describes what a visitor or a crawler gets.
        "allow_private": bool(a.allow_private),
        "verify_bots": bool(a.verify_bots),
        # Whether the page-level items all read the same bytes. With the cache off
        # each script fetches for itself, so on a site that changes mid-audit two
        # items can describe two different documents — a reader comparing verdicts
        # that disagree needs to know which kind of run this was.
        "http_cache": bool(http_cache),
        # Enabled is not used: this counts responses that really came from disk.
        # The baseline excludes an earlier run without resetting a counter another
        # audit on this machine may be updating at the same time.
        "http_cache_hits": http_cache_hits,
        # Whether the host actually turned out to be one only we can reach. The
        # flag says what was permitted; this says what happened, and it is the one
        # that decides whether "no external service could measure this" is true.
        "entry_private": entry_private,
        "public_suffix_snapshot": psl_snapshot_date() or None,
        # Which parser read every page. It belongs beside the suffix snapshot for the
        # same reason: both are substrate the verdicts rest on, chosen by this run
        # rather than by the site. `lxml` and `html.parser` agree on every field the
        # registry reads (fifteen document shapes, tests/test_parser.py) and, since
        # 0.15.0, on every structural query too — GO-144's score used to be 10 under
        # one and 32 under the other on markup with an unclosed `<p>`, and both give
        # 42 now that the scanner asks about document order rather than about where a
        # parent ends. Recorded anyway: a reader comparing two runs that differ has to
        # be able to rule this out, the guarantee is a test rather than a property of
        # the libraries, and until 0.14.0 the choice was made by import order and
        # recorded nowhere.
        "html_parser": html_parser(),
        # What the profile changed about how this site was measured, as opposed to
        # which items it took out of scope. A threshold moved silently is a verdict
        # nobody can argue with.
        "profile_args": prof_args or None,
        "sample": a.sample,
        "sampled_urls": sampled_urls,
        "evidence_path": a.evidence_json or None,
        "scores": score(graded),
        "runs": summarize_runs(results),
        # Timeouts and crashes both land in NO_DATA; counted apart so a run that
        # was merely too slow does not read as a plugin full of broken scripts.
        "script_failures": {
            kind: sum(1 for v in results.values()
                      if v.get("__error_kind__") == kind)
            for kind in FAILURE_LABEL
            if any(v.get("__error_kind__") == kind for v in results.values())
        },
        # Search Console's opportunities: work a person can do, carried in the artifact
        # because no item asserts on them any more and nothing else in a run knows about
        # them. GO-134 used to read this field through a severity gate, so "position 4.0
        # with 115 impressions" arrived as a high failure — the site's best result,
        # printed as the first thing to fix. Deleting the assertion without keeping the
        # data would have thrown away the most useful thing GSC returns, so it lives
        # here instead and the report prints it outside the score and the fix list.
        "gsc_opportunities": gsc_opportunities(results),
        # Reported, never scored — see lab_performance(). In the artifact because no item
        # asserts on it any more and nothing else in a run would remember it.
        "lab_performance": lab_performance(results) or None,
        "items": graded,
    }

    payload = redact(payload, secrets)

    if a.evidence_json:
        write_evidence(a.evidence_json, evidence_artifact(results, page_evidence),
                       secrets)

    hist = ""
    if not a.no_history:
        hist = history_path(domain, stamp)
        with open(hist, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    # Computed whenever there is a previous run, not only under `--diff`.
    #
    # `--diff` used to gate the comparison itself, so the answer to "did anything
    # improve" existed only if somebody had asked for it in advance, was printed to a
    # terminal, and was gone when the terminal closed. A checklist is a thing people
    # re-run, and the report a client receives could not say whether their last round
    # of fixes worked. The data was already on disk in `.seo-runs/`; nothing had to be
    # measured again to answer it. `--diff` now decides whether it is *printed* here,
    # which is what it was always for.
    diff_note = ""
    prev = previous_run(domain, hist)
    if prev:
        payload["diff"], diff_note = diff_runs(prev, payload)
        payload["diff_note"] = diff_note
        ps = prev.get("scores") or {}
        # What it was compared against, named in the artifact. A diff whose baseline
        # is anonymous cannot be checked by the person reading it, and "since the
        # previous run" is not a date.
        payload["compared_with"] = {
            "started_at": prev.get("started_at"),
            "registry_version": prev.get("registry_version"),
            "scoring_stamp": (prev.get("scoring_tables") or {}).get("stamp"),
            "mode": prev.get("mode"),
            "profile": prev.get("profile"),
            "seo_score": ps.get("seo_score"),
            "weight_pct": ps.get("weight_pct"),
            "decided": ps.get("decided"),
        }
    else:
        payload["diff"] = None
        payload["compared_with"] = None

    # The arc, not just the last step. `.seo-runs/` has held every run since 0.1.0 and
    # exactly one of them was ever read; the question a site owner asks is whether
    # months of work moved anything, and the data to answer it was already on disk.
    #
    # The per-run status maps are dropped before writing: they are what `open_since`
    # is computed from, and carrying them into the artifact would multiply a file
    # people email by the length of the history.
    series = run_series(domain, hist, limit=a.history_limit)
    payload["open_since"] = open_since(series, payload["items"])
    # This run is the last point on its own arc. Excluded from `run_series` because
    # `open_since` counts the streak *before* today and adds the current verdict
    # itself; leaving it out of the printed history as well showed a reader a trend
    # that stopped a month before the report in their hands.
    payload["history"] = [{k: v for k, v in row.items() if k != "statuses"}
                          for row in series] + [{
        "started_at": payload.get("started_at"),
        "registry_version": payload.get("registry_version"),
        # Same key the earlier points carry, or the arc would end on a point that
        # looks like a run from before the stamp existed.
        "scoring_stamp": payload["scoring_tables"]["stamp"],
        "mode": payload.get("mode"), "profile": payload.get("profile"),
        "seo_score": payload["scores"].get("seo_score"),
        "weight_pct": payload["scores"].get("weight_pct"),
        "decided": payload["scores"].get("decided"),
        "current": True,
    }]

    with open(a.json_out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print_report(payload, a, hist, crawl_path, diff_note)
    return 0


if __name__ == "__main__":
    sys.exit(main())
