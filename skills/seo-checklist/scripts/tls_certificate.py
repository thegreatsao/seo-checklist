#!/usr/bin/env python3
"""Inspect the TLS certificate served for a host: validity, expiry, hostname, chain.

Written for SE-118, which until 0.20 asserted `https == True` — the same field as
SE-117 — so it could not fail independently on any site, and a certificate that
expired yesterday passed it. Both were `critical`. This registry reported that it
verified certificates and never once did.

Nothing here re-implements verification. The handshake is done by `ssl` with
`verify_mode = CERT_REQUIRED` and `check_hostname = True` against the system trust
store, so an expired, self-signed, wrong-host or untrusted-chain certificate fails
the connection and is reported with the reason the library gave. The second pass,
with verification off, exists only to *read* a certificate the first pass rejected:
without it every failure would report the same empty result and "expired" would be
indistinguishable from "connection refused".
"""

from __future__ import annotations

import argparse
import json
import socket
import ssl
import sys
from datetime import datetime, timezone
from urllib.parse import urlparse

# The SSRF guard every other evidence script gets for free by fetching through
# `safe_get`. This one cannot: `ssl` needs the handshake itself, not a response body,
# so it opens its own socket and the guard has to be called by hand. Importing
# `safe_http` costs nothing here — `requests` is optional inside it and
# `assert_safe_url` reaches only `socket` and `ipaddress`, so this file keeps the
# stdlib-only property that lets it run where `requests` is not installed.
try:
    from lib.safe_http import SafeHTTPError, assert_safe_url
except ImportError:
    from scripts.lib.safe_http import SafeHTTPError, assert_safe_url

# basis: convention — the point of asking is to renew before it bites, and a month
# is the shortest notice on which a human process (procurement, a change window)
# reliably fits. Let's Encrypt renews at 30 days remaining for the same reason.
EXPIRY_WARN_DAYS = 30

# basis: inherited — the timeout every other script in this tree passes.
DEFAULT_TIMEOUT = 15


def _parse_not_after(value: str) -> datetime | None:
    """OpenSSL's notAfter, e.g. 'Nov  4 12:00:00 2026 GMT'."""
    try:
        return datetime.strptime(value, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _flatten(pairs: object) -> dict:
    """((('commonName', 'x'),), ...) -> {'commonName': 'x'}"""
    out = {}
    if isinstance(pairs, (list, tuple)):
        for rdn in pairs:
            for entry in rdn if isinstance(rdn, (list, tuple)) else []:
                if isinstance(entry, (list, tuple)) and len(entry) == 2:
                    out[str(entry[0])] = str(entry[1])
    return out


def inspect(url: str, timeout: int = DEFAULT_TIMEOUT) -> dict:
    target = url if "://" in url else f"https://{url}"
    parsed = urlparse(target)
    host = parsed.hostname
    port = parsed.port or 443

    out: dict = {"url": url, "host": host, "port": port, "https": parsed.scheme == "https",
                 "issues": []}
    if not host:
        out["issues"].append({"severity": "critical", "message": "No host in URL"})
        return out

    # An `http` URL has no certificate, so there is nothing here to inspect. Returning
    # without `valid` makes SE-118 NO_DATA, which is the honest reading: SE-117 is the
    # item that says the site is not on HTTPS, and it already fails. Opening TLS against
    # the plaintext port instead would hand back `WRONG_VERSION_NUMBER` — an error about
    # our own request, reported as if it were a fact about the site.
    if parsed.scheme == "http":
        out["reason"] = "URL is http:// — no certificate is served on this scheme"
        return out

    # The runner states the rule for the whole run — "55 scripts in 55 processes each
    # call assert_safe_url for themselves, so the allowance has to travel with them" —
    # and this script was the one that did not. It takes a host and a port straight from
    # argv and hands them to `create_connection`, so `--allow-private` never reached it
    # and loopback, RFC 1918 and the cloud metadata address were all reachable from an
    # audit that had not been given the switch. Guarding here rather than at each
    # `create_connection` covers both passes below: same host, same port.
    #
    # A blocked address is not a fact about a certificate, so this returns without
    # `valid` — NO_DATA to SE-118, the same shape as the refused connection below,
    # rather than a `valid: False` that would read as "this site's certificate is bad".
    try:
        assert_safe_url(target)
    except SafeHTTPError as exc:
        out["error"] = f"SafeHTTPError: {exc}"
        return out

    # Pass one: a verifying handshake. This is the verdict.
    context = ssl.create_default_context()
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    cert = None
    try:
        with socket.create_connection((host, port), timeout=timeout) as raw:
            with context.wrap_socket(raw, server_hostname=host) as tls:
                cert = tls.getpeercert()
                out["tls_version"] = tls.version()
                out["valid"] = True
    except ssl.SSLCertVerificationError as exc:
        out["valid"] = False
        out["verify_error"] = exc.verify_message or str(exc)
        out["issues"].append({"severity": "critical",
                              "message": f"Certificate did not verify: {out['verify_error']}"})
    except (ssl.SSLError, socket.timeout, OSError) as exc:
        # Not a verdict about the certificate — the connection never got that far.
        out["error"] = f"{type(exc).__name__}: {exc}"
        return out

    # Pass two: read a rejected certificate so the report can say *why* it is bad.
    # Never a verdict — `valid` is already decided above and is not touched here.
    if cert is None:
        unverified = ssl._create_unverified_context()  # noqa: SLF001
        try:
            with socket.create_connection((host, port), timeout=timeout) as raw:
                with unverified.wrap_socket(raw, server_hostname=host) as tls:
                    der = tls.getpeercert(binary_form=True)
                    out["tls_version"] = tls.version()
            if der:
                # ssl has no DER parser that does not verify; report what we can.
                out["unverified_bytes"] = len(der)
        except (ssl.SSLError, socket.timeout, OSError):
            pass
        return out

    out["subject"] = _flatten(cert.get("subject"))
    out["issuer"] = _flatten(cert.get("issuer"))
    out["san"] = sorted({v for k, v in cert.get("subjectAltName", ()) if k == "DNS"})
    out["not_before"] = cert.get("notBefore")
    out["not_after"] = cert.get("notAfter")

    not_after = _parse_not_after(cert.get("notAfter", ""))
    if not_after:
        days = (not_after - datetime.now(timezone.utc)).days
        out["days_until_expiry"] = days
        if days < 0:
            # Unreachable through a verifying handshake, which rejects an expired
            # certificate. Kept because a system clock is not a guarantee.
            out["issues"].append({"severity": "critical",
                                  "message": f"Certificate expired {-days} days ago"})
        elif days < EXPIRY_WARN_DAYS:
            out["issues"].append({"severity": "high",
                                  "message": f"Certificate expires in {days} days"})
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect a site's TLS certificate")
    parser.add_argument("url")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    parser.add_argument("--json", "-j", action="store_true")
    args = parser.parse_args()
    result = inspect(args.url, args.timeout)
    print(json.dumps(result, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
