#!/usr/bin/env python3
"""Probe the real JSON shape of the checklist evidence scripts.

Runs each script exactly the way checklist_runner.run_script() does
(argv + --json), then emits a compact structural skeleton so the
checklist assert rules can be written against reality, not guesses.

The jobs come from the registry itself — same scripts, same argv, same
deduplication — so this tool cannot hold an out-of-date idea of what the registry
asks for. It used to hold one, and it had gone stale in both directions at once.

    python3 probe_shapes.py https://example.com [page.html]

Environment: PROBE_ONLY narrows to named scripts, PROBE_GSC_PROPERTY adds the
Search Console jobs, PROBE_CWV_JSON / PROBE_RENDERED_JSON / PROBE_LINKS_CSV supply
the artifacts, PROBE_INVENTORY_JSON supplies a crawl inventory instead of taking one,
and PROBE_CRAWL=0 skips the crawl (the site-wide items are then unprobeable and
said so on stderr). Anything not supplied is skipped and named rather than probed
with a literal "{gsc_property}" on the command line.

A full probe crawls the target once and hands the inventory to the site-wide
checks, the same way an audit does — so it costs roughly what one audit costs rather
than what six independent crawls cost. Use PROBE_ONLY when only one output contract
changed.
"""
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

SCRIPT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
PY = os.environ.get("PROBE_PYTHON", sys.executable)

URL = sys.argv[1] if len(sys.argv) > 1 else "https://www.plerdy.com/seo-checklist/"
HTML = sys.argv[2] if len(sys.argv) > 2 else ""

# The job list is built from the registry, not held here by hand.
#
# It used to be a literal list, and it had drifted exactly as far as an unchecked
# copy does: it named seven scripts that no longer exist and missed three the
# registry reads — including `cwv_metrics.py` and `rendered_audit.py`, whose output
# shapes this tool exists to verify. A tool that checks the registry against
# reality cannot hold its own private idea of what the registry contains.
#
# `check.args` carries the same `{placeholder}` names the runner fills, so filling
# them the same way is all it takes. A job whose placeholder we have no value for
# is dropped and said out loud, rather than probed with a literal "{gsc_property}"
# on the command line.
REGISTRY = os.path.join(os.path.dirname(SCRIPT_DIR), "resources", "config",
                        "checklist.json")

CTX = {"url": URL}
if HTML:
    CTX["html"] = HTML
for key, env in (("cwv_json", "PROBE_CWV_JSON"), ("rendered_json", "PROBE_RENDERED_JSON"),
                 ("links_csv", "PROBE_LINKS_CSV"), ("indexnow_key", "INDEXNOW_KEY"),
                 ("inventory_json", "PROBE_INVENTORY_JSON")):
    if os.environ.get(env):
        CTX[key] = os.environ[env]


def _child_env() -> dict:
    """The environment a probed script runs in, with `PYTHONPATH` instead of a `cwd`.

    These calls used to pass `cwd=SCRIPT_DIR`, which was never needed for imports — a
    script run by path already has its own directory on `sys.path` — and which forced
    CPython onto `fork`+`exec`, where macOS kills the child inside Apple's atfork
    handler before it execs. `PYTHONPATH` covers the case `cwd` was there for and keeps
    the child on `posix_spawn`.
    """
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (SCRIPT_DIR + os.pathsep + existing) if existing else SCRIPT_DIR
    return env


def build_inventory(path="probe-inventory.json"):
    """Crawl once, the way the runner does before it builds its plan.

    Without this the site-wide items are unprobeable — `{inventory_json}` has no
    value, so they are dropped and named on stderr, and a tool that exists to check
    asserted paths against real output would be silent about exactly the paths a
    release changed. That is how GEO-007 kept reading a field nothing emitted: the
    item needed an input the probe had no way to supply.
    """
    proc = subprocess.run([PY, os.path.join(SCRIPT_DIR, "site_crawl.py"), URL,
                           "--out", path, "--json"],
                          capture_output=True, text=True, encoding="utf-8", timeout=600,
                          env=_child_env(), close_fds=False)
    if proc.returncode != 0:
        print(f"[skip] crawl failed, so the site-wide items cannot be probed: "
              f"{(proc.stderr or '').strip()[-300:]}", file=sys.stderr)
        return ""
    return path


if "inventory_json" not in CTX and os.environ.get("PROBE_CRAWL", "1") != "0":
    inventory = build_inventory()
    if inventory:
        CTX["inventory_json"] = inventory

# Search Console addresses a property the caller has access to, which is not
# derivable from the audited URL — probe those only when one is named.
GSC_PROPERTY = os.environ.get("PROBE_GSC_PROPERTY", "")
GSC_CREDENTIALS = (os.environ.get("GSC_CREDENTIALS_PATH")
                   or os.environ.get("GV_SA_KEY")
                   or os.path.expanduser("~/.config/gcloud/gsc-service-account.json"))
if GSC_PROPERTY:
    CTX["gsc_property"] = GSC_PROPERTY
    CTX["gsc_credentials"] = GSC_CREDENTIALS


def registry_jobs(ctx):
    """(script, args) for every registry check we can supply the inputs for.

    Deduplicated by (script, args) the way `checklist_runner.build_plan` does, so
    the 217 items collapse to the same handful of runs a real audit performs — and
    the shapes come back from the same command lines.
    """
    with open(REGISTRY, encoding="utf-8") as f:
        items = json.load(f)["items"]

    jobs, seen, unfillable = [], set(), {}
    for item in items:
        check = item.get("check") or {}
        script = check.get("script")
        if not script:
            continue
        args, missing = [], ""
        for arg in check.get("args") or []:
            if isinstance(arg, str) and arg.startswith("{") and arg.endswith("}"):
                key = arg[1:-1]
                if key not in ctx:
                    missing = key
                    break
                args.append(str(ctx[key]))
            else:
                args.append(str(arg))
        if missing:
            unfillable.setdefault(missing, set()).add(script)
            continue
        key = (script, tuple(args))
        if key not in seen:
            seen.add(key)
            jobs.append((script, args))
    for name, scripts in sorted(unfillable.items()):
        print(f"[skip] no {{{name}}}: {', '.join(sorted(scripts))}", file=sys.stderr)
    return jobs


JOBS = registry_jobs(CTX)

# Probing every script costs a minute of wall clock and a lot of traffic, so
# allow narrowing to the ones whose output contract actually changed.
ONLY = {s.strip() for s in os.environ.get("PROBE_ONLY", "").split(",") if s.strip()}
if ONLY:
    JOBS = [j for j in JOBS if j[0] in ONLY]


def skeleton(obj, depth=0, max_depth=3):
    """Compact structural summary: keys and types, arrays collapsed to first element."""
    pad = "  " * depth
    if depth > max_depth:
        return f"{pad}..."
    if isinstance(obj, dict):
        if not obj:
            return f"{pad}{{}}"
        lines = []
        for k, v in list(obj.items())[:25]:
            if isinstance(v, (dict, list)):
                lines.append(f"{pad}{k}:")
                lines.append(skeleton(v, depth + 1, max_depth))
            else:
                val = repr(v)
                if len(val) > 70:
                    val = val[:70] + "…"
                lines.append(f"{pad}{k} = {val}")
        if len(obj) > 25:
            lines.append(f"{pad}… +{len(obj) - 25} more keys")
        return "\n".join(lines)
    if isinstance(obj, list):
        if not obj:
            return f"{pad}[] (empty)"
        return f"{pad}[{len(obj)} items] first:\n" + skeleton(obj[0], depth + 1, max_depth)
    return f"{pad}{obj!r}"


def run(job):
    script, args = job
    path = os.path.join(SCRIPT_DIR, script)
    if not os.path.exists(path):
        return script, {"__missing__": True}, 0.0
    start = time.time()
    try:
        r = subprocess.run([PY, path] + args + ["--json"],
                           capture_output=True, text=True, encoding="utf-8", timeout=180,
                           env=_child_env(), close_fds=False)
        elapsed = round(time.time() - start, 1)
        if r.returncode == 0 and r.stdout.strip():
            try:
                return script, json.loads(r.stdout), elapsed
            except json.JSONDecodeError:
                return script, {"__badjson__": r.stdout[:300]}, elapsed
        return script, {"__error__": (r.stderr.strip() or f"exit {r.returncode}")[:300]}, elapsed
    except subprocess.TimeoutExpired:
        return script, {"__timeout__": True}, round(time.time() - start, 1)


results = {}
with ThreadPoolExecutor(max_workers=8) as ex:
    for script, payload, elapsed in ex.map(run, JOBS):
        results[script] = payload
        flag = next((k for k in ("__missing__", "__error__", "__timeout__", "__badjson__") if k in payload), None)
        print(f"[{'FAIL' if flag else ' ok '}] {script:<34} {elapsed:>5}s {flag or ''}", file=sys.stderr)

out = []
for script, payload in results.items():
    out.append("=" * 78)
    out.append(script)
    out.append("=" * 78)
    out.append(skeleton(payload))
    out.append("")
print("\n".join(out))

with open("probe-raw.json", "w") as f:
    json.dump(results, f, indent=2, default=str)
