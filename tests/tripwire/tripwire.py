"""Refuse, at the socket, every host that is not this machine — and every program
that is not Python and has no written reason to be started.

An audit hook (PEP 578) sees `socket.connect` and `socket.getaddrinfo` before either
touches the network. A connection to an address outside loopback, or the resolution
of a name that is not `localhost`, is a request to somebody else's server — the DNS
query included — and the suite promises none (`openspec/specs/governance/` GOV-7).

Resolving an address literal is not a request and is let through, because tests of
the guard's own policy classify public and private literals without reaching them.

A program a Python process starts is beyond the hook, so the start itself is the
event read: a Python child carries this module through `PYTHONPATH`, and any other
program must be in `PROGRAMS` with the reason it reaches nothing. Until F04 the
Reader line said "a new binary would be unread"; it is refused instead, before it
runs. A child started with an environment that leaves the tripwire out is refused
too, because it would run unwatched.

The switch is `SEO_TRIPWIRE`, its own. Until F04 it was the guard's
`SEO_LOOPBACK_ONLY`, and a test that cleared that to exercise the guard's
public-address policy disarmed both layers for itself and everything it started.

In a child the violation ends the process with `EXIT_CODE` after saying why on
stderr, because the scripts catch their own exceptions and a raised error could be
swallowed into a plausible "not found". In the test process it raises, so the test
that reached out fails and is named.
"""
from __future__ import annotations

import ipaddress
import os
import re
import sys

EXIT_CODE = 97
ENV = "SEO_TRIPWIRE"
HERE = os.path.dirname(os.path.abspath(__file__))
_installed = False
_fatal = True

# The programs other than Python that the suite and the gates start, each with what
# keeps it on this machine. A program not here is refused before it runs.
PROGRAMS = {
    "git": "the suite and the gates set GIT_ALLOW_PROTOCOL=file, so a git started here "
           "has no transport but this disk",
    "bash": "tools/ci_local.py runs the workflow's own lines with it, and a test reads "
            "every gate step's lines for a program that fetches",
    "openssl": "tests/harness.py makes a self-signed certificate for 127.0.0.1 with it, "
               "which opens no connection",
    "node": "test_report runs the report's own script with it, over a page this suite "
            "wrote to disk",
}


class NetworkTripped(RuntimeError):
    """Something in the suite reached for a host other than this machine."""


def armed(env=None) -> bool:
    value = (os.environ if env is None else env).get(ENV, "")
    return str(value).strip().lower() in ("1", "true", "yes", "on")


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


def _name(path) -> str:
    if isinstance(path, bytes):
        path = os.fsdecode(path)
    name = re.split(r"[\\/]", str(path))[-1].lower()
    return name[:-4] if name.endswith(".exe") else name


def is_python(path) -> bool:
    """A Python interpreter, by being this one, by its name, or by a `#!` line that
    names python — the shape of a script on `PATH` such as a stand-in CLI."""
    if isinstance(path, bytes):
        path = os.fsdecode(path)
    path = str(path)
    if re.fullmatch(r"pythonw?[\d.]*", _name(path)):
        return True
    try:
        if os.path.realpath(path) == os.path.realpath(sys.executable):
            return True
        with open(path, "rb") as f:
            first = f.readline(200)
    except OSError:
        return False
    return first.startswith(b"#!") and b"python" in first


# The suite's other fence: `tests/hand_capture/` answers every request on this machine
# and ends a child that gets past it, for the tests that must run a program with the
# guard off to see what it would send (`test_url_credentials`). Its `sitecustomize`
# takes this one's place on `PYTHONPATH`, and it is armed by `SEO_CAPTURE_LOG`.
CAPTURE = os.path.join(os.path.dirname(HERE), "hand_capture")


def _fenced(env) -> bool:
    """The child's environment loads this tripwire, armed, or the capture fence."""
    paths = {os.path.abspath(p) for p in str(env.get("PYTHONPATH", "")).split(os.pathsep) if p}
    return (HERE in paths and armed(env)) or (CAPTURE in paths
                                              and bool(env.get("SEO_CAPTURE_LOG")))


def _started(program, env) -> str:
    if program is None:
        return ""
    if is_python(program):
        if env is not None and not _fenced(env):
            return (f"started {_name(program)} with an environment that leaves the "
                    "tripwire out")
        return ""
    if _name(program) not in PROGRAMS:
        return (f"started {_name(program)!r}, a program the tripwire cannot see into "
                "and tripwire.PROGRAMS does not name")
    if env is not None and not armed(env):
        return f"started {_name(program)} with an environment that leaves the tripwire out"
    return ""


def _program(executable, args):
    if executable is not None:
        return executable
    if isinstance(args, (list, tuple)) and args:
        return args[0]
    if isinstance(args, (str, bytes)):
        text = os.fsdecode(args).strip()
        if text.startswith('"'):
            return text[1:].split('"', 1)[0]
        return text.split()[0] if text else None
    return None


def violation(event: str, args) -> str:
    """The sentence for a request this process may not make, or "" when it may."""
    if not armed():
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
    elif event == "subprocess.Popen":
        executable, argv, _cwd, env = args
        return _started(_program(executable, argv), env)
    elif event in ("os.posix_spawn", "os.exec"):
        return _started(args[0], args[2])
    elif event == "os.spawn":
        return _started(args[1], args[3])
    elif event == "os.system":
        return _started(_program(None, args[0]), None)
    return ""


EVENTS = ("socket.connect", "socket.getaddrinfo", "subprocess.Popen", "os.posix_spawn",
          "os.exec", "os.spawn", "os.system")


def install(fatal: bool) -> None:
    """Add the hook once; `fatal` is the last caller's. Audit hooks cannot be removed,
    so it reads the environment on every event. `sitecustomize` installs it fatal in
    every process; `tests/harness.py` then makes it raise in the test process."""
    global _installed, _fatal
    _fatal = fatal
    if _installed:
        return
    _installed = True

    def hook(event, args):
        if event not in EVENTS:
            return
        said = violation(event, args)
        if not said:
            return
        message = (f"network tripwire: {os.path.basename(sys.argv[0] or 'python')} "
                   f"{said} while {ENV} is set")
        if _fatal:
            sys.stderr.write(message + "\n")
            sys.stderr.flush()
            os._exit(EXIT_CODE)
        raise NetworkTripped(message)

    sys.addaudithook(hook)
