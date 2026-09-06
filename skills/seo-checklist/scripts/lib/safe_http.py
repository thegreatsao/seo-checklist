#!/usr/bin/env python3
"""Safe HTTP helpers shared by network-facing SEO scripts."""

from __future__ import annotations

import codecs
import hashlib
import ipaddress
import json
import os
import re
import socket
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlparse, urlunparse

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None

try:
    import msvcrt
except ImportError:  # pragma: no cover - POSIX
    msvcrt = None

try:
    import requests
    from requests.adapters import HTTPAdapter
    from requests.structures import CaseInsensitiveDict
    from urllib3 import HTTPConnectionPool, HTTPSConnectionPool
    _REQUESTS_ERROR = ""
except ImportError:  # pragma: no cover - environment guard
    # Deferred, not fatal. This module is imported transitively by the checklist
    # runner, so exiting here killed `--archive` — a mode that makes no network
    # calls at all and has no business needing an HTTP library installed. The
    # failure now happens when something actually tries to make a request.
    requests = None
    HTTPAdapter = object
    HTTPConnectionPool = HTTPSConnectionPool = None
    CaseInsensitiveDict = dict
    _REQUESTS_ERROR = ("requests library required for network access. "
                       "Install with: pip install requests")


def _require_requests() -> None:
    if requests is None:
        raise RuntimeError(_REQUESTS_ERROR)


AGENTIC_SEO_USER_AGENT = (
    "Mozilla/5.0 (compatible; AgenticSEOSkill/1.0; "
    "+https://github.com/Bhanunamikaze/Agentic-SEO-Skill)"
)
DEFAULT_TIMEOUT = 15
DEFAULT_MAX_REDIRECTS = 5
DEFAULT_MAX_RESPONSE_BYTES = 5 * 1024 * 1024

# `text/xml;q=0.9` is here rather than in `seo_common.fetch_url`, which is where it
# used to live. Two spellings of one header is what that was — the two conventions
# in this tree each wrote their own Accept, differing only by that one media type —
# and the cost was invisible until the response cache made it countable: every
# audited page was fetched twice, once per spelling, because a different Accept is
# a different request and has to be. This list is the union, so no caller loses a
# type it used to advertise, and one page is now one fetch.
DEFAULT_HEADERS = {
    "User-Agent": AGENTIC_SEO_USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml,text/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
}


class SafeHTTPError(requests.exceptions.RequestException if requests else Exception):
    """Raised when a request is blocked by safe HTTP policy.

    Subclasses RequestException so callers can catch either; without requests
    installed there is nothing to subclass and nothing to catch it from."""


class HostResolutionError(SafeHTTPError):
    """Raised when a host has no address to validate or connect to."""


def default_headers(extra: dict | None = None) -> dict:
    """Return request headers with the shared Agentic SEO User-Agent."""
    headers = dict(DEFAULT_HEADERS)
    if extra:
        headers.update(extra)
    headers["User-Agent"] = AGENTIC_SEO_USER_AGENT
    return headers


def normalize_url(url: str, default_scheme: str = "https") -> str:
    """Normalize a user-supplied URL, adding https:// when no scheme exists.

    An empty path becomes `/`, which `seo_common.normalize_url` has always done and
    this one did not. The two forms are not two requests: every HTTP client, this
    one included, puts `/` on the wire for an empty path, so `http://x` and
    `http://x/` are the same GET described two ways. Keeping them distinct cost the
    audit an extra fetch of the site's own home page — once as the entry URL and
    once as a sampled one — and that only became visible when requests became
    countable.
    """
    if not url:
        raise SafeHTTPError("URL is required")
    parsed = urlparse(url)
    if not parsed.scheme:
        url = f"{default_scheme}://{url}"
        parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise SafeHTTPError(f"Invalid URL scheme: {parsed.scheme}")
    if not parsed.hostname:
        raise SafeHTTPError("URL must include a hostname")
    return urlunparse(parsed._replace(path=parsed.path or "/"))


# ---------------------------------------------------------------------------
# Politeness
# ---------------------------------------------------------------------------

# An audit is a burst by construction: the runner launches its evidence scripts
# concurrently, and several of them walk a sitemap or a link list inside their own
# process. Nothing paced any of it, so a small site could take a few hundred
# requests in a couple of seconds from one machine — indistinguishable from
# something worth blocking, and rude regardless of whether anyone notices.
#
# The pacing has to be shared, because the scripts are separate processes and an
# in-process limiter would just let eight of them go at once. The state is a file
# per host holding the last request time, guarded by a lock: cheap, no daemon, and
# it survives a script crashing mid-audit.
DEFAULT_MAX_RPS = 4.0
# Where that file lives, and the robots.txt answers beside it. Machine-wide by
# default and deliberately so: pacing is a promise to somebody else's server, and two
# audits started a second apart have to queue behind each other or the promise is
# only kept per process tree.
DEFAULT_RATE_LIMIT_DIR = os.path.join(tempfile.gettempdir(), "seo-checklist-rate")
RATE_LIMIT_DIR_VAR = "SEO_RATE_LIMIT_DIR"
# basis: convention — 30s. A server that says 'come back in an hour' is not worth
#  waiting for inside an audit; past this the item reports NO_DATA with the reason,
#  which is more useful than a run that appears to hang
MAX_RETRY_AFTER_WAIT = 30.0


def rate_limit_dir() -> str:
    """The directory pacing slots and cached robots.txt answers live in.

    `SEO_RATE_LIMIT_DIR` moves it, and it is read on every use rather than captured
    at import — which is the whole difference from the module constant this replaced.
    That constant could be *assigned* and could not be *inherited*: a caller that set
    it changed its own process and nothing it went on to start, so every child went
    back to the machine-wide directory and read whatever was in it. A caller that
    needs its own state — a sandboxed run, a second audit on one machine, a test
    suite whose origins are recycled loopback ports — has to be able to hand that
    decision to the processes it launches, and the environment is how this tree
    already does it for `SEO_HTTP_CACHE`.
    """
    return os.environ.get(RATE_LIMIT_DIR_VAR, "").strip() or DEFAULT_RATE_LIMIT_DIR


def max_rps() -> float:
    """Requests per second per host. `SEO_MAX_RPS=0` switches pacing off."""
    raw = os.environ.get("SEO_MAX_RPS", "")
    if not raw:
        return DEFAULT_MAX_RPS
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_MAX_RPS
    return max(value, 0.0)


def _slot_path(host: str) -> str:
    # The host is not a safe filename (ports, IDN, path-like garbage from a
    # malformed URL), so it is hashed rather than sanitised.
    digest = hashlib.sha256(host.encode("utf-8", "replace")).hexdigest()[:32]
    return os.path.join(rate_limit_dir(), f"{digest}.slot")


def _lock_exclusive(fd, *, blocking: bool) -> bool:
    """Take an exclusive lock on `fd`. Returns whether it was taken."""
    try:
        if fcntl is not None:
            flags = fcntl.LOCK_EX
            if not blocking:
                flags |= fcntl.LOCK_NB
            fcntl.flock(fd, flags)
            return True

        # Windows byte-range locks are mandatory. That is safe here: cache and
        # robots locks are separate sidecar files, while every accessor to a pacing
        # slot takes its lock first. Lock and unlock must use the same offset and
        # length; otherwise unlocking silently misses the region and leaks the lock
        # until the descriptor closes.
        os.lseek(fd, 0, os.SEEK_SET)
        # LK_LOCK retries for about ten seconds and then raises; unlike LOCK_EX it
        # does not wait forever. For pacing, that bounded failure deliberately falls
        # back to this process's own delay instead of hanging the audit.
        mode = msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK
        msvcrt.locking(fd, mode, 1)
        return True
    except OSError:
        return False


def _unlock(fd) -> None:
    if fcntl is not None:
        fcntl.flock(fd, fcntl.LOCK_UN)
        return
    os.lseek(fd, 0, os.SEEK_SET)
    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)


def pace(host: str, rps: float | None = None) -> float:
    """Wait until this process may hit `host` again. Returns the seconds waited.

    Coordinated through a lock file so that concurrent evidence scripts queue
    behind each other instead of each pacing itself. A failure to read or write
    that file is never fatal: being unable to co-ordinate is a reason to slow down
    on our own, not to abandon the request.
    """
    limit = max_rps() if rps is None else rps
    if limit <= 0 or not host:
        return 0.0
    interval = 1.0 / limit
    fd = None
    try:
        # The directory is the slot's own, read once: `rate_limit_dir()` answers from
        # the environment, so creating one directory and then opening a file in
        # whatever the next call says would be two decisions where there is one.
        slot = _slot_path(host)
        os.makedirs(os.path.dirname(slot), exist_ok=True)
        # Deliberately not open(path, "a+"): in append mode POSIX writes at the end
        # of the file whatever seek() and truncate() say, so two updates
        # concatenated into "153761.19671379115376.196978791" and float() raised —
        # out of `pace`, through safe_get, and into 36 evidence scripts at once.
        # pwrite is deliberately not used: it does not exist on Windows, where its
        # absence silently disabled shared coordination instead of failing the
        # request.
        fd = os.open(slot, os.O_RDWR | os.O_CREAT, 0o600)
        if not _lock_exclusive(fd, blocking=True):
            raise OSError("could not lock pacing slot")
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            raw = os.read(fd, 64).decode("ascii", "replace").strip()
            try:
                last = float(raw) if raw else 0.0
            except ValueError:
                # A slot written by an older version, or a torn write. Pacing from
                # zero costs one unpaced request; raising would cost the audit.
                last = 0.0
            now = time.monotonic()
            # A stale slot from a previous run — or a clock that moved — must not
            # park the audit. monotonic() is per-boot, so a value in the future
            # means the file outlived a reboot.
            if last > now or now - last > STALE_PACE_SLOT_SECONDS:
                last = 0.0
            waited = max(0.0, last + interval - now)
            if waited:
                time.sleep(waited)
            os.ftruncate(fd, 0)
            os.lseek(fd, 0, os.SEEK_SET)
            os.write(fd, str(time.monotonic()).encode("ascii"))
            return waited
        finally:
            _unlock(fd)
    except Exception:  # noqa: BLE001
        # Politeness must never be able to fail an audit. Whatever went wrong with
        # the shared state, the safe answer is to pace this process on its own.
        time.sleep(interval)
        return interval
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# robots.txt
# ---------------------------------------------------------------------------

# The bare product token, never the full User-Agent string. `RobotFileParser`
# matches by splitting the agent at the first "/" and lowercasing it, so passing
# our full UA — "Mozilla/5.0 (compatible; AgenticSEOSkill/1.0; ...)" — yields
# "mozilla", and a site that names AgenticSEOSkill explicitly would be silently
# ignored while `*` rules applied instead. Verified against CPython's
# Entry.applies_to; there is a test.
ROBOTS_TOKEN = "AgenticSEOSkill"

# basis: convention — one hour. An operational bound, not a verdict: a pacing slot older
#  than this is treated as belonging to a previous run, because `monotonic()` is per-boot
#  and a file that outlived a reboot would otherwise park the audit. An hour is longer
#  than any audit and shorter than any uptime worth worrying about.
STALE_PACE_SLOT_SECONDS = 3600

# Cached on disk rather than per process. Every evidence script is its own
# process, so an in-process cache would fetch /robots.txt 45 times per audit —
# the same fan-out the pacing slots exist to avoid.
# basis: convention — 30 minutes, long enough to cover one audit of a large site and
#  short enough that a rule changed today is picked up today
ROBOTS_CACHE_TTL = 1800.0
# basis: convention — 512KB. Google's own documented limit is 500KiB and it stops
#  parsing there; this is that rounded up, so we never read less of a file than Google
#  does
ROBOTS_MAX_BYTES = 512 * 1024
# The disk cache is not enough on its own, because the scripts do not start one at a
# time: 45 of them launch inside the same second, all miss a cache nobody has
# written yet, and all fetch. It was five requests on a CI runner and one on a
# developer machine — a difference invisible until the requests were counted, which
# is why the count in CI is an assertion rather than a printout. So the fetch takes
# the same lock the response cache takes, and waits this long for whoever has it.
ROBOTS_FETCH_WAIT = 10.0


class RobotsDisallowed(SafeHTTPError):
    """Raised when robots.txt forbids a URL we discovered ourselves."""


def _take_lock(path: str):
    """An exclusive lock on `path`, or None if somebody else holds it. Never waits.

    Shared by the response cache and the robots.txt fetch because they want the same
    thing: **one process does the work while the others wait for its result.** A
    failure to create or lock the file returns None, which both callers read as "do
    it yourself" — being unable to co-ordinate is a reason to duplicate a request,
    never a reason to fail one.
    """
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    except OSError:
        return None
    try:
        locked = _lock_exclusive(fd, blocking=False)
    except OSError:
        locked = False
    if not locked:
        _close_lock(fd)
        return None
    return fd


def _close_lock(fd) -> None:
    if fd is None:
        return
    try:
        _unlock(fd)
    except OSError:
        pass
    try:
        os.close(fd)
    except OSError:
        pass


def _robots_cache_path(origin: str) -> str:
    digest = hashlib.sha256(origin.encode("utf-8", "replace")).hexdigest()[:32]
    return os.path.join(rate_limit_dir(), f"{digest}.robots")


def _read_robots_cache(path: str) -> str | None:
    try:
        if time.time() - os.path.getmtime(path) > ROBOTS_CACHE_TTL:
            return None
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def _write_robots_cache(path: str, text: str) -> None:
    try:
        # `path`'s own directory, not whatever `rate_limit_dir()` says now: the caller
        # already decided where this entry goes.
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.{os.getpid()}"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except OSError:
        pass


def _fetch_robots(origin: str) -> str:
    """The robots.txt body, or "" when there is nothing to obey.

    Fail-open on every error, including 5xx. RFC 9309 lets a crawler treat a
    server error as a full disallow, and for an unattended crawler discovering
    content that is the right default — but this is an audit the site's own
    operator asked for, against a URL they supplied. Refusing to look because
    robots.txt returned 503 would turn a transient hiccup into an audit of
    nothing, which is a worse answer than a slightly impolite one. Deliberate,
    and the reason is here so it can be argued with.
    """
    try:
        url, pinned_addresses = _validated_url(urljoin(origin, "/robots.txt"))
        headers = CaseInsensitiveDict(default_headers())
        headers.setdefault("Host", _host_header(url))
        response = None
        with _owned_session() as requester:
            for address in pinned_addresses:
                adapter = _PinnedAdapter(url, address)
                requester.mount(f"{urlparse(url).scheme}://", adapter)
                try:
                    # `allow_redirects=False`, and a redirect is read below as "no
                    # rules". Following one would mean validating the Location's address
                    # before each hop, which is what `safe_request` does for a page; here
                    # the hop is not worth the machinery, because the answer either way is
                    # a policy this audit fails open on. Not following it is what stops a
                    # public robots.txt from bouncing this request to 169.254.169.254.
                    response = requester.get(  # not safe_get: that would recurse into this
                        url,
                        headers=headers,
                        timeout=10,
                        allow_redirects=False,
                        verify=True,
                    )
                    break
                except requests.exceptions.ConnectionError:
                    adapter.close()
        # Every validated address refused the connection. Same answer as an absent
        # robots.txt, for the reason in the docstring: an origin whose rules cannot be
        # fetched is an origin with no rules, and this is an audit its own operator asked
        # for rather than an unattended crawl.
        if response is None:
            return ""
        if response.status_code != 200:
            return ""
        return response.content[:ROBOTS_MAX_BYTES].decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return ""


def _robots_text_once(origin: str, host: str, path: str) -> str:
    """Fetch `/robots.txt` at most once per origin, across the whole run.

    The lock is taken and then the cache read *again* — without that second read, a
    process whose read missed while the holder was still fetching, and whose lock
    then succeeded because the holder had just released, fetches a file already on
    disk. Same shape and same reason as `_CacheSlot.lookup`.

    Running out of patience is not an error: we fetch it ourselves, which is what
    every one of these calls did before there was a lock.
    """
    deadline = time.monotonic() + ROBOTS_FETCH_WAIT
    fd = None
    try:
        while True:
            text = _read_robots_cache(path)
            if text is not None:
                return text
            if fd is not None:
                break
            fd = _take_lock(f"{path}.lock")
            if fd is None and time.monotonic() >= deadline:
                break
            if fd is None:
                time.sleep(_CACHE_POLL)
        pace(host)
        text = _fetch_robots(origin)
        _write_robots_cache(path, text)
        return text
    finally:
        _close_lock(fd)


def robots_policy(url: str):
    """`(RobotFileParser, crawl_delay)` for a URL's origin. Never raises."""
    from urllib.robotparser import RobotFileParser

    parsed = urlparse(url)
    if not parsed.hostname:
        return None, 0.0
    origin = f"{parsed.scheme or 'https'}://{parsed.netloc}"
    path = _robots_cache_path(origin)
    text = _read_robots_cache(path)
    if text is None:
        _require_requests()
        text = _robots_text_once(origin, parsed.hostname, path)
    if not text.strip():
        return None, 0.0
    parser = RobotFileParser()
    try:
        parser.parse(text.splitlines())
        delay = parser.crawl_delay(ROBOTS_TOKEN)
    except Exception:  # noqa: BLE001
        # A robots.txt we cannot parse is not a disallow.
        return None, 0.0
    return parser, float(delay or 0.0)


def robots_allows(url: str) -> tuple[bool, float]:
    """`(allowed, crawl_delay)`. Unreadable or absent robots.txt allows."""
    try:
        parser, delay = robots_policy(url)
    except Exception:  # noqa: BLE001
        return True, 0.0
    if parser is None:
        return True, 0.0
    try:
        return bool(parser.can_fetch(ROBOTS_TOKEN, url)), delay
    except Exception:  # noqa: BLE001
        return True, delay


def retry_after_seconds(response) -> float:
    """How long a 429/503 asked us to wait, 0 when it did not ask.

    Both forms of the header are accepted: delta-seconds and an HTTP date. An
    unparseable value returns 0 rather than a guess — waiting a made-up interval
    is not more polite than not waiting.
    """
    if getattr(response, "status_code", 0) not in (429, 503):
        return 0.0
    raw = ((getattr(response, "headers", {}) or {}).get("Retry-After") or "").strip()
    if not raw:
        return 0.0
    try:
        return max(0.0, float(raw))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return 0.0
    if when is None:
        return 0.0
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())


def _port_for(parsed) -> int:
    if parsed.port:
        return parsed.port
    return 443 if parsed.scheme == "https" else 80


def _is_blocked_ip(ip_text: str) -> bool:
    ip = ipaddress.ip_address(ip_text)
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_reserved
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_unspecified
    )


# ---------------------------------------------------------------------------
# The escape hatch, and why it is this narrow
# ---------------------------------------------------------------------------

# The SSRF guard had no way out, and that cost two different things.
#
# The one a client notices: a site cannot be audited before it is public, which is
# the moment an audit is worth most. The one this plugin paid itself: no fixture
# site can be served locally, so the live path — 55 evidence scripts, the shared
# pacing, five crawlers — could only ever be exercised against a real third party.
# That is how a slot-file bug crashed 36 scripts in a live run while every test in
# the suite passed.
#
# So the allowance exists, off by default, and it is deliberately *not* "anything
# that is not public". The set is enumerated rather than derived from
# `ipaddress`'s flags, because `is_private` is True for 169.254.0.0/16 — where
# cloud instance metadata answers (169.254.169.254) — and the URLs a crawler
# follows come from the site being audited. A site that can talk this tool into
# reading credentials off a metadata endpoint is a worse outcome than a staging
# audit nobody can run. Reserved, multicast and unspecified ranges are absent for
# the same reason: nothing legitimate is served there, so allowing them buys
# nothing and widens the hole.
PRIVATE_ALLOWED_NETWORKS = (
    "127.0.0.0/8", "::1/128",                          # loopback — a fixture server
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",   # RFC 1918 — a staging box
    "fc00::/7",                                        # RFC 4193 — its IPv6 form
    "100.64.0.0/10",                                   # RFC 6598 — CGNAT, Tailscale
)
_PRIVATE_ALLOWED = tuple(ipaddress.ip_network(n) for n in PRIVATE_ALLOWED_NETWORKS)

_TRUE = ("1", "true", "yes", "on")
_announced_private = False


def allow_private() -> bool:
    """Whether this process may reach a private address. Off unless asked.

    An unrecognised value is off, like a nonsense `SEO_MAX_RPS` falls back to the
    default rather than to no limit: a typo must not be able to remove a guard.
    """
    return os.environ.get("SEO_ALLOW_PRIVATE", "").strip().lower() in _TRUE


def _is_allowed_private(ip_text: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_text)
    except ValueError:
        return False
    return any(ip in net for net in _PRIVATE_ALLOWED)


def _announce_private(ip_text: str) -> None:
    """Say it once per process, on stderr.

    The runner announces the flag and records it in the artifact, but a single
    evidence script run by hand has no other surface to say it on — and an audit
    of a staging copy that reads like an audit of the live site is the same class
    of lie as a fabricated score.
    """
    global _announced_private
    if _announced_private:
        return
    _announced_private = True
    print(f"  private address allowed: {ip_text} (SEO_ALLOW_PRIVATE) — "
          f"this host is not on the public internet", file=sys.stderr)


def _guard_ip(ip_text: str) -> None:
    """Raise `SafeHTTPError` unless this address may be reached.

    Propagates `ValueError` when `ip_text` is not an address at all; the caller
    decides what that means (a hostname resolves, a resolved IP does not).
    """
    if not _is_blocked_ip(ip_text):
        return
    if allow_private() and _is_allowed_private(ip_text):
        _announce_private(ip_text)
        return
    if allow_private():
        why = (" — link-local, reserved and multicast ranges stay blocked even "
               "with --allow-private: cloud instance metadata answers at "
               "169.254.169.254 and the URLs a crawl follows come from the site")
    else:
        why = (" — pass --allow-private (or SEO_ALLOW_PRIVATE=1) to audit a local "
               "or staging site")
    raise SafeHTTPError(
        f"Blocked: URL resolves to private/internal IP ({ip_text}){why}")


def is_private_host(url: str) -> bool:
    """Whether this URL's host is one only we can reach.

    Keyed on where the host actually resolves, never on whether the allowance was
    passed: `--allow-private` on a public site changes nothing about that site, and
    a caller that confused the two would misreport an ordinary audit. False when
    the name does not resolve — that is "unreachable", a question the reachability
    gate already answers, and answering it twice with different words would put two
    reasons on one item.
    """
    try:
        parsed = urlparse(normalize_url(url))
    except SafeHTTPError:
        return False
    host = parsed.hostname
    if not host:
        return False
    if _is_allowed_private(host):
        return True
    try:
        infos = socket.getaddrinfo(host, _port_for(parsed), type=socket.SOCK_STREAM)
    except socket.gaierror:
        return False
    return any(_is_allowed_private(info[4][0]) for info in infos)


def _validated_url(url: str) -> tuple[str, tuple[str, ...]]:
    """Validate URL scheme and reject hosts resolving to private/internal IPs.

    `SEO_ALLOW_PRIVATE=1` — the runner's `--allow-private` — permits the narrow
    set in `PRIVATE_ALLOWED_NETWORKS` and nothing else. See the comment there for
    what stays blocked with the allowance on, and why. The address tuple preserves
    resolver order so the transport tries only answers validated by this call.
    """
    normalized = normalize_url(url)
    parsed = urlparse(normalized)
    hostname = parsed.hostname

    try:
        _guard_ip(hostname)
    except ValueError:
        pass          # a name, not an address — resolution below decides

    try:
        infos = socket.getaddrinfo(hostname, _port_for(parsed), type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise HostResolutionError(f"Could not resolve host: {hostname}") from exc

    resolved_ips = tuple(dict.fromkeys(info[4][0] for info in infos))
    if not resolved_ips:
        raise HostResolutionError(
            f"Could not resolve host ({hostname}): resolver returned no addresses")
    for ip_text in resolved_ips:
        try:
            _guard_ip(ip_text)
        except ValueError as exc:
            raise SafeHTTPError(f"Blocked: could not validate resolved IP ({ip_text})") from exc

    return normalized, resolved_ips


def assert_safe_url(url: str) -> str:
    """Compatibility wrapper for validation-only callers."""
    normalized, _resolved_ips = _validated_url(url)
    return normalized


# How far into a document to look for its own encoding declaration. The HTML spec
# tells a browser to give up after 1024 bytes; this doubles that because a `<head>`
# padded with preload hints can push the `<meta>` past 1KB, and reading 2KB of a body
# we have already downloaded costs nothing.
ENCODING_SNIFF_BYTES = 2048

_META_CHARSET = re.compile(rb"""<meta[^>]+?charset\s*=\s*["']?\s*([a-zA-Z0-9_\-:.]+)""",
                           re.IGNORECASE)
_XML_ENCODING = re.compile(rb"""<\?xml[^>]+?encoding\s*=\s*["']([a-zA-Z0-9_\-:.]+)["']""",
                           re.IGNORECASE)
_BOMS = ((b"\xef\xbb\xbf", "utf-8-sig"), (b"\xff\xfe", "utf-16"), (b"\xfe\xff", "utf-16"))
# `charset=` with optional spaces around the `=`. A plain substring test misses
# `text/html; charset = utf-8`, which `requests` itself parses happily — and missing it
# means overwriting an encoding the server did name, which is the one thing this must
# never do.
_HEADER_CHARSET = re.compile(r"charset\s*=", re.IGNORECASE)
# Comments are stripped before the prescan. The HTML spec has a browser skip comments
# and script content when sniffing, and a commented-out `<meta charset>` — the shape a
# template leaves behind — would otherwise decide how the live page is read.
_COMMENT = re.compile(rb"<!--.*?-->", re.DOTALL)


def _declared_encoding(head: bytes) -> str | None:
    """The encoding the document states for itself, or None if it states none.

    Deliberately only what is *declared* — a BOM, an XML declaration, or a `<meta>`.
    Character-set detection is not consulted: `apparent_encoding` guesses, and a guess
    that silently rewrites a page's text is the kind of measurement this repository
    keeps having to apologise for. A document that declares nothing keeps whatever
    `requests` decided, which is the behaviour every caller has had until now.
    """
    for bom, name in _BOMS:
        if head.startswith(bom):
            return name
    head = _COMMENT.sub(b"", head)
    found = _XML_ENCODING.search(head) or _META_CHARSET.search(head)
    if not found:
        return None
    name = found.group(1).decode("ascii", "ignore").strip()
    try:
        codecs.lookup(name)
    except (LookupError, ValueError):
        return None
    return name


def _honour_declared_encoding(response) -> None:
    """Let the document's own charset win when the server named none.

    `requests` reads the charset out of `Content-Type`, and when a `text/*` response
    carries none it falls back to ISO-8859-1 — the old HTTP default. A server that
    sends bare `text/html` and lets `<meta charset="utf-8">` speak for the page is
    therefore decoded as latin-1, and every title, heading and word count downstream
    is mojibake: `—` arrives as `â\x80\x94`. Browsers honour the meta; so must we, or
    the audit reports text the site never served.

    Only touched when the header is silent. If the server named a charset it wins,
    even if the document disagrees — disagreeing with the server is a site defect for
    an item to report, not something to paper over here.
    """
    ctype = response.headers.get("Content-Type", "") or ""
    if _HEADER_CHARSET.search(ctype):
        return
    kind = ctype.split(";", 1)[0].strip().lower()
    # JSON is UTF-8 by RFC 8259 and `response.json()` handles it; binary types have no
    # text to get wrong. Only markup and plain text are in scope.
    if kind and not (kind.startswith("text/") or kind in
                     ("application/xhtml+xml", "application/xml")):
        return
    declared = _declared_encoding(response.content[:ENCODING_SNIFF_BYTES])
    if declared:
        response.encoding = declared


def _consume_capped(response, max_response_bytes: int | None):
    if max_response_bytes is None:
        response._content = response.content
        return response

    chunks = []
    total = 0
    for chunk in response.iter_content(chunk_size=65536):
        if not chunk:
            continue
        total += len(chunk)
        if total > max_response_bytes:
            response.close()
            raise SafeHTTPError(f"Response exceeded {max_response_bytes} byte safety limit")
        chunks.append(chunk)
    response._content = b"".join(chunks)
    response._content_consumed = True
    return response


# ---------------------------------------------------------------------------
# The run-scoped response cache
# ---------------------------------------------------------------------------

# One audit of a seven-page site fetched the entry URL 37 times. Nothing was
# written badly to make that happen: 36 evidence scripts each need the page they
# are judging, each is its own process, and nothing connected them. The shared
# crawl (0.9.0) removed the site-wide half of the same problem and left this as the
# largest measurable waste — 37 requests for one document, paced four a second, so
# nine seconds of an audit spent asking a server a question it already answered.
#
# Requests are the smaller half of what it cost. **Thirty-seven fetches are
# thirty-seven different documents** whenever the page is not static: a CMS
# rotating a hero image, a deploy landing mid-audit, an A/B test. Items would then
# disagree about the page and every one of them would be right about what it read,
# which is precisely the failure the crawl inventory removed for the site. This
# removes it for the page: every item that reports on a URL now reports on the same
# bytes, and that is the guarantee, with the saved requests as the side effect.
#
# It is still a cache, so the way it fails is by answering with something that is
# no longer true — the one failure this tool exists to refuse. Hence:
#
#   * **Off unless a run turns it on.** `SEO_HTTP_CACHE` names the directory; the
#     runner makes one per run and deletes it afterwards. A script run by hand
#     caches nothing, and there is no shared cache that could outlive an audit and
#     feed the next one a stale page.
#   * **Only real responses.** A timeout, a refused connection, a redirect loop and
#     a robots.txt refusal are not answers and are never stored, so one transient
#     failure cannot become every item's failure. Any status code *is* an answer,
#     including 404 and 503 — and re-asking a server that just said 503 thirty-six
#     more times is the opposite of the politeness the pacing exists for.
#   * **GET and HEAD only.** Never POST: `indexnow_checker` submits URLs, and
#     replaying a submission from disk would report something that did not happen.
CACHE_DIR_VAR = "SEO_HTTP_CACHE"
# basis: convention — 15 minutes, and it is belt to the per-run directory's braces: the
#  directory is deleted when the run ends, so nothing should ever be this old. A run
#  killed with SIGKILL leaves one behind, and an entry from it must not be able to
#  answer anything
CACHE_TTL = 900.0
# basis: convention — 8MB, above the 5MB response cap, so the cap decides what is
#  fetched and this only decides what is worth writing to disk
CACHE_MAX_BODY = 8 * 1024 * 1024
CACHEABLE_METHODS = ("GET", "HEAD")
# In the key, so a change to what an entry contains cannot be read by code
# expecting the old shape. A mismatch is a miss, not an error.
CACHE_ENTRY_VERSION = 1
_CACHE_POLL = 0.05


def cache_dir() -> str:
    """The directory this run caches responses in, or "" when caching is off."""
    return os.environ.get(CACHE_DIR_VAR, "").strip()


def _cache_key(method: str, url: str, headers: dict, allow_redirects: bool,
               kwargs: dict) -> str:
    """A digest of everything that could change the response, and nothing else.

    `timeout` is absent: it decides whether an answer arrives, never what the
    answer says, and a caller with a longer patience should be allowed to use what
    a shorter one managed to get. `max_response_bytes` is absent because a complete
    body satisfies any cap large enough to hold it — `_cap_allows` decides that per
    lookup, which is what lets the entry URL's callers share one entry despite
    asking for 1.5MB, 2MB and 5MB of it.

    `allow_redirects` is in: with it off the response *is* the redirect, and
    serving the destination to a caller that asked for the hop would hide the hop.

    Anything else a caller passes goes in by `repr`. An argument this function has
    never heard of has to make the key *differ*; a repr that is unstable across
    processes (an object's address, say) costs an extra request, which is the
    failure that leaves the answer correct.
    """
    material = "\n".join([
        str(CACHE_ENTRY_VERSION), method, url, str(bool(allow_redirects)),
        repr(sorted((str(k).lower(), str(v)) for k, v in headers.items())),
        repr(sorted((str(k), repr(v)) for k, v in kwargs.items() if k != "verify")),
    ])
    return hashlib.sha256(material.encode("utf-8", "replace")).hexdigest()[:40]


def _read_entry(path: str) -> dict | None:
    """The stored response, or None when there is nothing usable at `path`.

    Every failure is None — a half-written file, an entry from another version, one
    older than the TTL. A cache that can raise would put a defect of its own in
    front of 36 scripts at once.

    The stored byte count is checked against the body actually on disk. A length
    that does not match is a torn write, and serving half a document as though it
    were the page is the exact lie this module is arranged to prevent.
    """
    try:
        if time.time() - os.path.getmtime(path) > CACHE_TTL:
            return None
        with open(path, "rb") as f:
            blob = f.read()
    except OSError:
        return None
    head, _, body = blob.partition(b"\n")
    try:
        meta = json.loads(head.decode("ascii"))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(meta, dict) or meta.get("v") != CACHE_ENTRY_VERSION:
        return None
    if meta.get("bytes") != len(body):
        return None
    meta["body"] = body
    return meta


def _write_entry(path: str, meta: dict, body: bytes) -> None:
    """Write one entry, atomically. Never raises.

    JSON header line, then the raw body — deliberately not pickle. A reader of a
    pickled entry executes whatever the writer put there, and this directory's
    whole job is to be read by 36 other processes.
    """
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.{os.getpid()}"
        with open(tmp, "wb") as f:
            # ensure_ascii, so the header cannot contain a raw newline and the
            # partition above always finds the real boundary.
            f.write(json.dumps(meta, ensure_ascii=True).encode("ascii"))
            f.write(b"\n")
            f.write(body)
        os.replace(tmp, path)
    except (OSError, TypeError, ValueError):
        # A header that will not serialise means no entry, not a failed request.
        try:
            os.unlink(f"{path}.{os.getpid()}")
        except OSError:
            pass


def _cap_allows(meta: dict, max_response_bytes: int | None) -> bool:
    """Whether a caller's size cap can accept the stored body.

    Stored bodies are complete by construction — `_consume_capped` raises rather
    than truncating — so the only question is whether this caller asked for less
    than the whole thing. When it did, this is a miss and the request goes out and
    raises exactly as it would have without a cache. Truncating the stored body to
    fit would be inventing a document.
    """
    if max_response_bytes is None:
        return True
    return int(meta.get("bytes", 0)) <= max_response_bytes


def _hop_from(entry: dict):
    """One redirect in a restored chain. Callers read `.url` and `.status_code`."""
    hop = requests.Response()
    hop.status_code = entry.get("status")
    hop.url = entry.get("url", "")
    hop.headers = CaseInsensitiveDict(entry.get("headers", {}))
    hop._content = b""
    hop._content_consumed = True
    return hop


def _response_from_entry(meta: dict):
    """A `requests.Response` a caller cannot tell from the one that was fetched.

    `elapsed` is restored rather than zeroed, and that is not cosmetic: three
    scripts report response time from it (`broken_links`, `redirect_checker`,
    `lcp_subparts`). A restored elapsed is a real measurement of a real request to
    that URL, which is what those scripts claim to report. Zero would be a
    fabricated performance number, and `None` would crash them.
    """
    response = requests.Response()
    response.status_code = meta.get("status")
    response.reason = meta.get("reason") or ""
    response.url = meta.get("url", "")
    response.headers = CaseInsensitiveDict(meta.get("headers", {}))
    response.encoding = meta.get("encoding")
    response.elapsed = timedelta(seconds=float(meta.get("elapsed") or 0.0))
    response._content = meta.get("body", b"")
    response._content_consumed = True
    response.history = [_hop_from(h) for h in meta.get("chain", ())]
    # Not part of `requests`; a marker for tests and for anyone reading a trace.
    response.from_cache = True
    return response


def _entry_from_response(response, asked: dict) -> dict:
    return {
        "v": CACHE_ENTRY_VERSION,
        # What was asked, beside what came back. The key is a digest and a digest
        # cannot be read, so without this an audit that fetched a page three times
        # gives no way to find out why — and "why are there three entries for one
        # URL" is the question this cache exists to answer. `url` below is where the
        # request landed; `asked` is what went out.
        "asked": asked,
        "status": response.status_code,
        "reason": response.reason or "",
        "url": response.url,
        "headers": dict(response.headers),
        "encoding": response.encoding,
        "elapsed": response.elapsed.total_seconds() if response.elapsed else 0.0,
        "chain": [{"status": h.status_code, "url": h.url, "headers": dict(h.headers)}
                  for h in (response.history or ())],
    }


def _robots_permits_entry(meta: dict) -> None:
    """Raise if a stored redirect chain crosses a path robots.txt forbids.

    The requested URL was gated before the lookup; its redirect hops were not, and
    a cache hit must not become a way to follow a redirect the live path would have
    refused. Without this, any site that redirects could opt out of the rule by
    being fetched twice. robots.txt is itself cached on disk, so the re-check costs
    nothing.
    """
    hops = [h.get("url", "") for h in meta.get("chain", ())] + [meta.get("url", "")]
    for hop in hops[1:]:
        allowed, _ = robots_allows(hop)
        if not allowed:
            raise RobotsDisallowed(
                f"robots.txt disallows {hop} (redirected from {hops[0]})")


class _CacheSlot:
    """One key's place in the run cache, and the right to be who fetches it.

    Lookup and single-flight are one object because they are one decision: either
    this process has the answer or it is the process that goes and gets it while
    the others wait. Without the waiting the cache would save almost nothing here —
    the runner starts eight workers at once, they miss together, and eight
    processes fetch the page the cache exists to fetch once.

    Waiting is bounded by the caller's own timeout, and running out is not an
    error: it falls back to fetching, which is what every one of these calls did
    before this cache existed. A cache must not be able to turn one slow server
    into an audit that hangs.
    """

    def __init__(self, directory: str, key: str, deadline: float, asked: dict):
        self.path = os.path.join(directory, f"{key}.resp")
        self.lock_path = f"{self.path}.lock"
        self.deadline = deadline
        self.asked = asked
        self.fd = None

    def _try_lock(self) -> bool:
        self.fd = _take_lock(self.lock_path)
        return self.fd is not None

    def lookup(self, max_response_bytes: int | None) -> dict | None:
        """The stored entry, or None — in which case this process must fetch.

        The loop is the single-flight: read, then try to become the fetcher, then
        wait for whoever already is. A holder that dies releases the lock without
        writing an entry, and the next waiter takes it — the fallback is another
        request, never a wedge.

        **The read is repeated after the lock is taken**, and that is not belt and
        braces. Without it, a process whose read misses while the writer is still
        fetching, and whose lock then succeeds because the writer has just
        released, goes and fetches a page that is already on disk. It cost one
        duplicate GET of the entry URL in one measured run out of two — a race that
        only ever costs a request, which is exactly why nothing would have found it
        later.
        """
        while True:
            meta = _read_entry(self.path)
            if meta is not None:
                # Present but too large for this caller's cap: a miss that no
                # amount of waiting improves, and not ours to replace.
                return meta if _cap_allows(meta, max_response_bytes) else None
            if self.fd is not None:
                return None          # we hold the lock and there is nothing: ours
            if not self._try_lock():
                if time.monotonic() >= self.deadline:
                    return None
                time.sleep(_CACHE_POLL)

    def store(self, response, body: bytes) -> None:
        if len(body) > CACHE_MAX_BODY:
            return
        meta = _entry_from_response(response, self.asked)
        meta["bytes"] = len(body)
        _write_entry(self.path, meta, body)

    def close(self) -> None:
        fd, self.fd = self.fd, None
        _close_lock(fd)


def _cache_slot(method: str, url: str, headers: dict, kwargs: dict, *,
                allow_redirects: bool, stream: bool, session, timeout):
    """The slot for this request, or None when it must not be cached at all.

    Each exclusion is a way a restored response would differ from a real one: a
    body nobody has read (`stream`), a request that changes something on the server
    (anything but GET and HEAD), and a session whose cookie jar a replayed response
    would not update. Nothing in this tree passes `session` today; it is excluded
    anyway, because a cache that has to be re-examined whenever somebody adds an
    argument is a cache nobody will re-examine.
    """
    directory = cache_dir()
    if not directory or stream or session is not None:
        return None
    if method not in CACHEABLE_METHODS:
        return None
    key = _cache_key(method, url, headers, allow_redirects, kwargs)
    try:
        patience = float(timeout or 0.0)
    except (TypeError, ValueError):
        patience = float(DEFAULT_TIMEOUT)
    asked = {"method": method, "url": url, "headers": dict(headers),
             "allow_redirects": bool(allow_redirects)}
    return _CacheSlot(directory, key, time.monotonic() + max(patience, 1.0), asked)


class _PinnedAdapter(HTTPAdapter):
    """A Requests adapter whose pool connects to one validated address."""

    def __init__(self, url: str, address: str):
        super().__init__()
        parsed = urlparse(url)
        port = _port_for(parsed)
        self.pool_key = (parsed.scheme, address, port)
        pool_kwargs = {
            "port": port,
            "maxsize": self._pool_maxsize,
            "block": self._pool_block,
            "retries": self.max_retries,
        }
        if parsed.scheme == "https":
            # The pool host is the validated IP, but SNI and certificate matching
            # both use the URL's original hostname. TLS is never checked against
            # the IP and verification remains enabled by safe_request below.
            pool_kwargs.update(
                assert_hostname=parsed.hostname,
                server_hostname=parsed.hostname,
            )
            self.pool = HTTPSConnectionPool(address, **pool_kwargs)
        else:
            self.pool = HTTPConnectionPool(address, **pool_kwargs)

    def get_connection_with_tls_context(self, request, verify, proxies=None, cert=None):
        """Requests >=2.32 adapter hook; the pool is already pinned."""
        return self.pool

    def get_connection(self, url, proxies=None):
        """Requests 2.31 adapter hook; retained for the declared dependency floor."""
        return self.pool

    def close(self):
        self.pool.close()
        super().close()


def _owned_session(template=None):
    """Return a request session whose adapters this module alone may mutate."""
    owned = requests.Session()
    if template is None:
        return owned

    # Preserve caller policy and state without borrowing the object itself: mounting
    # a pin on a shared session would race the crawler's other worker threads.
    owned.headers.update(template.headers)
    owned.cookies.update(template.cookies)
    owned.auth = template.auth
    owned.proxies.update(template.proxies)
    owned.hooks = {event: list(callbacks) for event, callbacks in template.hooks.items()}
    owned.params.update(template.params)
    owned.stream = template.stream
    owned.verify = template.verify
    owned.cert = template.cert
    owned.max_redirects = template.max_redirects
    owned.trust_env = template.trust_env
    return owned


def safe_request(
    method: str,
    url: str,
    *,
    headers: dict | None = None,
    timeout: int | float = DEFAULT_TIMEOUT,
    allow_redirects: bool = True,
    max_redirects: int = DEFAULT_MAX_REDIRECTS,
    max_response_bytes: int | None = DEFAULT_MAX_RESPONSE_BYTES,
    stream: bool = False,
    session=None,
    respect_robots: bool = False,
    **kwargs,
):
    """
    Execute an HTTP request with SSRF guards, redirect checks, TLS verification,
    timeouts, and a response-size cap.

    `respect_robots` is opt-in, and the asymmetry is the design: **robots.txt
    governs URLs we discovered ourselves, not the URL the operator handed us.**

    Pass it when following links, walking a sitemap or expanding a crawl. Leave it
    off for the audit target. A blanket check here would be worse than none: if the
    requested page is disallowed, every one of the 40-odd scripts that fetches
    `{url}` would be refused, the audit would collapse to NO_DATA everywhere, and
    the finding that actually matters — "this page is blocked from crawling", a
    `critical` checklist item — would be buried under the wreckage instead of
    reported. The operator asked for this URL; the block is a result, not a
    prohibition.

    A `Crawl-delay` in robots.txt is honoured when it is *slower* than the
    configured rate. Faster is ignored — the site cannot talk us into being less
    polite than we chose to be.

    When `SEO_HTTP_CACHE` names a directory, an identical GET or HEAD made earlier
    in the same run is answered from it instead of going out again. See the cache
    section above for what "identical" means and what is never stored. The robots
    gate runs *before* the lookup, and a stored redirect chain is re-checked against
    robots.txt on the way out, so caching cannot become a way around either.
    """
    _require_requests()
    current, pinned_addresses = _validated_url(url)
    request_headers = default_headers(headers)
    requester = _owned_session(session)
    history = []
    method = method.upper()
    kwargs["verify"] = True
    robots_delay = 0.0
    if respect_robots:
        allowed, robots_delay = robots_allows(current)
        if not allowed:
            raise RobotsDisallowed(f"robots.txt disallows {current} for {ROBOTS_TOKEN}")

    slot = _cache_slot(method, current, request_headers, kwargs,
                       allow_redirects=allow_redirects, stream=stream,
                       session=session, timeout=timeout)
    try:
        if slot is not None:
            meta = slot.lookup(max_response_bytes)
            if meta is not None:
                if respect_robots:
                    _robots_permits_entry(meta)
                return _response_from_entry(meta)

        for _ in range(max_redirects + 1):
            response = _paced_request(requester, method, current, request_headers,
                                      timeout, kwargs, pinned_addresses, robots_delay)

            if not (allow_redirects and response.is_redirect):
                response.history = history
                return _finish(response, slot, method, stream, max_response_bytes)

            location = response.headers.get("Location")
            if not location:
                response.history = history
                return _finish(response, slot, method, stream, max_response_bytes)

            response.close()
            history.append(response)
            if len(history) > max_redirects:
                raise requests.exceptions.TooManyRedirects(
                    f"Too many redirects (max {max_redirects})")

            next_url, next_addresses = _validated_url(urljoin(current, location))
            if respect_robots:
                # A redirect can land on a path robots.txt forbids, and following it
                # because the first hop was allowed would make the rule trivially
                # avoidable by any site that redirects.
                allowed, robots_delay = robots_allows(next_url)
                if not allowed:
                    raise RobotsDisallowed(
                        f"robots.txt disallows {next_url} (redirected from {current})")
            if response.status_code == 303 and method not in ("GET", "HEAD"):
                method = "GET"
                kwargs.pop("data", None)
                kwargs.pop("json", None)
            current = next_url
            pinned_addresses = next_addresses

        raise requests.exceptions.TooManyRedirects(f"Too many redirects (max {max_redirects})")
    finally:
        # Whatever happened, stop making the other processes wait for us. An
        # exception on the way out is why this is a `finally`: a request that failed
        # stores nothing, and the next waiter has to be free to try it itself.
        if slot is not None:
            slot.close()


def _finish(response, slot, method: str, stream: bool,
            max_response_bytes: int | None):
    """Hand back the response that ends a request, storing it if we may.

    The body is read here rather than inside the cache, because this is the one
    place that knows what "the body" is: empty for HEAD, unread for a stream, and
    otherwise whatever `_consume_capped` allowed through. A stream is never stored —
    the caller has not read it yet, and a cache cannot store what nobody has seen.
    """
    if method == "HEAD":
        response.close()
        # A HEAD has no body, and a restored one has none either. Deliberately not
        # `response.content`: the connection is closed and reading it now would be
        # asking for bytes that were never going to arrive.
        if slot is not None:
            slot.store(response, b"")
        return response
    if stream:
        return response
    _consume_capped(response, max_response_bytes)
    # Before the cache stores it: `_entry_from_response` records `response.encoding`,
    # and a restored response has to decode the same way the live one did.
    _honour_declared_encoding(response)
    if slot is not None:
        slot.store(response, response.content)
    return response


def _rate_for(crawl_delay: float) -> float | None:
    """Requests/second for a host, respecting a slower `Crawl-delay` if asked.

    Returns None to mean "use the configured default". A delay that would make us
    *faster* than the configured rate is ignored: robots.txt can ask for more
    patience, never for less.
    """
    if crawl_delay <= 0:
        return None
    asked = 1.0 / crawl_delay
    configured = max_rps()
    if configured <= 0:
        return None          # pacing switched off deliberately; leave it off
    return min(asked, configured)


def _host_header(url: str) -> str:
    """The authority Requests would send when connecting by hostname."""
    return urlparse(url).netloc.rsplit("@", 1)[-1]


def _paced_request(requester, method, url, headers, timeout, kwargs,
                   pinned_addresses: tuple[str, ...], crawl_delay: float = 0.0):
    """One request, paced before it goes out and retried once if asked to back off.

    The retry is deliberately single and bounded. A server that answers 429 has
    told us we are going too fast, and hammering it again — or waiting out an
    hour-long Retry-After inside an audit — are both worse than letting the item
    report NO_DATA with the reason attached.
    """
    rate = _rate_for(crawl_delay)
    pace(urlparse(url).hostname or "", rate)
    request_headers = CaseInsensitiveDict(headers)
    request_headers.setdefault("Host", _host_header(url))
    if not pinned_addresses:
        # The guard cannot validate an address its resolver cannot find, so this
        # temporarily retains the legacy Requests lookup and carries no pin.
        # Closing the hole waits for 0.60.0's machine-readable fetch-error kind;
        # changing only the error prose here moved BL-083's declared verdict.
        response = requester.request(
            method, url, headers=request_headers, timeout=timeout,
            allow_redirects=False, stream=True, **kwargs)
    else:
        response = None
        last_error = None
        prefix = f"{urlparse(url).scheme}://"
        for address in pinned_addresses:
            adapter = _PinnedAdapter(url, address)
            requester.mount(prefix, adapter)
            try:
                response = requester.request(
                    method, url, headers=request_headers, timeout=timeout,
                    allow_redirects=False, stream=True, **kwargs)
                break
            except requests.exceptions.ConnectionError as exc:
                last_error = exc
                adapter.close()
        if response is None:
            raise last_error
    wait = retry_after_seconds(response)
    if 0 < wait <= MAX_RETRY_AFTER_WAIT:
        response.close()
        time.sleep(wait)
        pace(urlparse(url).hostname or "", rate)
        response = requester.request(method, url, headers=request_headers, timeout=timeout,
                                     allow_redirects=False, stream=True, **kwargs)
    return response


def safe_get(url: str, **kwargs):
    return safe_request("GET", url, **kwargs)


def safe_head(url: str, **kwargs):
    return safe_request("HEAD", url, **kwargs)


def safe_post(url: str, **kwargs):
    return safe_request("POST", url, **kwargs)
