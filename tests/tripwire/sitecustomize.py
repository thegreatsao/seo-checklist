"""The suite's network tripwire, installed in every process that has this directory on
its `PYTHONPATH`.

`harness.spawn` puts this directory first on a child's `PYTHONPATH`, and `ci.yml`'s
workflow `env` puts it there for every step, so Python imports this module at start-up
in the evidence script, the runner and every script the runner starts in turn. It
installs `tripwire.install`, which ends the process when anything reaches for a host
other than this machine, or starts a program the tripwire cannot see into.

The guard in `lib/safe_http.py` refuses such hosts first when `SEO_LOOPBACK_ONLY` is
set, so the tripwire fires only on a path that does not go through the guard — a raw
socket, a TLS handshake, a DNS library. That is the case worth being loud about: the
scripts swallow their own exceptions freely, and a request the guard never saw is
exactly the kind nothing else would report. See `openspec/specs/governance/` GOV-7.

When armed it also hands its children what it was given in a form that survives
them: this directory, absolute and first, on `PYTHONPATH` — the workflow's entry is
relative to the repository root, and a child started from another directory would
resolve it to nothing — and `GIT_ALLOW_PROTOCOL=file`, so a git a gate step starts has
no transport but this disk.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tripwire  # noqa: E402

if tripwire.armed():
    rest = [p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep)
            if p and os.path.abspath(p) != HERE]
    os.environ["PYTHONPATH"] = os.pathsep.join([HERE] + rest)
    os.environ.setdefault("GIT_ALLOW_PROTOCOL", "file")
tripwire.install(fatal=True)
