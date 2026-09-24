"""The suite's network tripwire, installed in every child `tests/harness.py` spawns.

`harness.spawn` puts this directory first on a child's `PYTHONPATH`, so Python imports
this module at start-up in the evidence script, the runner and every script the runner
starts in turn. It installs `tripwire.install`, which ends the process when anything
reaches for a host other than this machine.

The guard in `lib/safe_http.py` refuses such hosts first when `SEO_LOOPBACK_ONLY` is
set, so the tripwire fires only on a path that does not go through the guard — a raw
socket, a TLS handshake, a DNS library. That is the case worth being loud about: the
scripts swallow their own exceptions freely, and a request the guard never saw is
exactly the kind nothing else would report. See `openspec/specs/governance/` GOV-7.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tripwire  # noqa: E402

tripwire.install(fatal=True)
