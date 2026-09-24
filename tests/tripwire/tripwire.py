"""Refuse, at the socket, every host that is not this machine.

An audit hook (PEP 578) sees `socket.connect` and `socket.getaddrinfo` before either
touches the network. A connection to an address outside loopback, or the resolution
of a name that is not `localhost`, is a request to somebody else's server — the DNS
query included — and the suite promises none (`openspec/specs/governance/` GOV-7).

Resolving an address literal is not a request and is let through, because tests of
the guard's own policy classify public and private literals without reaching them.

In a child the violation ends the process with `EXIT_CODE` after saying why on
stderr, because the scripts catch their own exceptions and a raised error could be
swallowed into a plausible "not found". In the test process it raises, so the test
that reached out fails and is named.
"""
from __future__ import annotations

import ipaddress
import os
import sys

EXIT_CODE = 97
ENV = "SEO_LOOPBACK_ONLY"
_installed = False


class NetworkTripped(RuntimeError):
    """Something in the suite reached for a host other than this machine."""


def _is_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        return False
    return True


def _is_loopback(host) -> bool:
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    if not isinstance(host, str) or not host:
        return True          # a Unix socket path or an empty bind is not a remote host
    if host.lower() in ("localhost", "localhost."):
        return True
    try:
        return ipaddress.ip_address(host.split("%", 1)[0]).is_loopback
    except ValueError:
        return False


def violation(event: str, args) -> str:
    """The sentence for a request this process may not make, or "" when it may."""
    if os.environ.get(ENV, "").strip().lower() not in ("1", "true", "yes", "on"):
        return ""
    if event == "socket.getaddrinfo":
        host = args[0]
        if isinstance(host, bytes):
            host = host.decode("ascii", "replace")
        if isinstance(host, str) and host and not _is_literal(host) and not _is_loopback(host):
            return f"resolved {host!r}"
    elif event == "socket.connect":
        address = args[1]
        if isinstance(address, tuple) and address and not _is_loopback(address[0]):
            return f"connected to {address[0]}:{address[1] if len(address) > 1 else '?'}"
    return ""


def install(fatal: bool) -> None:
    """Add the hook once. Audit hooks cannot be removed, so it reads the environment
    on every event: a test that clears `SEO_LOOPBACK_ONLY` to exercise the guard's
    public-address policy switches the tripwire off with it."""
    global _installed
    if _installed:
        return
    _installed = True

    def hook(event, args):
        if event not in ("socket.connect", "socket.getaddrinfo"):
            return
        said = violation(event, args)
        if not said:
            return
        message = (f"network tripwire: {os.path.basename(sys.argv[0] or 'python')} "
                   f"{said} while {ENV} is set")
        if fatal:
            sys.stderr.write(message + "\n")
            sys.stderr.flush()
            os._exit(EXIT_CODE)
        raise NetworkTripped(message)

    sys.addaudithook(hook)
