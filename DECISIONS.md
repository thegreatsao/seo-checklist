# DECISIONS.md

Inline decision log for non-obvious architectural choices.
For long-lived projects, consider migrating to individual ADR files in `docs/decisions/` — see `docs/decisions/000-template.md`.

Each entry answers: what was decided, why, when, and what alternatives were rejected.

---

## Log

<!-- FILL IN: Add a new entry for each non-obvious decision. Most recent first.
     A decision is worth logging if a future reader (or agent) would otherwise
     make a different choice without knowing why the current one was made. -->

---

### 2026-10-20 A file the page names is excused only for a port refusal; every other guard refusal stays the fetch layer's `blocked`

**Decision:** Where a refused URL is the subject of a result (the page, robots.txt, a sitemap) the runner records
the fetch layer's `blocked` for any `SafeHTTPError` the guard raises — a port the web deployment does not reach, a
private address, a body over a limit. Where it is a file a script grades as the site's (the favicon, a stylesheet,
the IndexNow key file), only `NonStandardPort` leaves the item undecided; a private address or a `data:` href
still fails.

**Why:** a port refusal is ours: Google reaches `:8443` perfectly well. Googlebot cannot fetch a private address
or a `data:` URL either, so for a file the site chose to point at, that refusal describes the site, and excusing it
would turn a true MB-104 or GEO-007 FAIL into NO_DATA. For a subject the kind changes only the label, never the
status, so the fetch layer's single word is right there.

**Alternatives rejected:**
- **One predicate (`fetch_error_kind == "blocked"`) everywhere:** it moved a `data:` favicon from FAIL to NO_DATA
  (found in F14 before the review) and a key file redirecting to a private address likewise (found by the review).
- **A new fetch-layer kind for the port alone:** HTTP-9's vocabulary is closed at seven, and the runner needs one
  word for "our guard stopped it" whatever stopped it.

**Consequences:** `indexability_matrix` and `favicon_check` treat a robots.txt over the 500 KB the audit reads as
unread (CI-005, CI-001 NO_DATA), not as allowing everything. Following a sitemap index's children in the matrix,
rather than reporting membership unknown, is a separate feature.

---

### 2026-10-18 `make check` is `ci_local.py`, not a list of commands

**Decision:** `make check` runs `skills/seo-checklist/tools/ci_local.py`, then `check-arch` and `vcr`. `make e2e` runs
nothing of its own and says so.

**Why:** `ci_local.py` reads its steps out of `.github/workflows/ci.yml`. A Makefile listing the gates would be the
second copy of the check list that this repository has repeatedly found passing after the original moved.

**Alternatives rejected:**
- **One Make target per gate:** drifts from `ci.yml` the first time a step is added there.
- **`make e2e` copying the smoke step:** the same copy, one step long.

**Consequences:**
- A first `make check` takes about ten minutes; an unchanged tree is instant.
- F01's third layer calls `ci_local.py` directly: `make check` includes `vcr`, which fails while the feature it is
  verifying is `active`.

---

### 2026-10-18 `HANDOFF.md` is a git-ignored link to the owner's workspace

**Decision:** `/HANDOFF.md` is ignored; on the owner's Mac it is a symlink to the workspace handoff that already
covers this repository and the web service built on it.

**Why:** the handoff names machines, clients, hosts and paths, and this repository is public. One file, not two
that drift.

**Alternatives rejected:**
- **A tracked `HANDOFF.md`:** a commit per session in a public repo, carrying private detail.
- **`local/handoff.md`:** the kit's `clean-state-check.sh` reads `HANDOFF.md` at the root.

**Consequences:**
- A fresh clone has no handoff; `AGENTS.md` sends it to `ROADMAP.md` and `KNOWN-ISSUES.md`.

---

<!-- TEMPLATE ENTRY — copy this block for each new decision

### [YYYY-MM-DD] [Decision title]

**Decision:**

**Why:**

**Alternatives rejected:**
-

**Consequences:**
-

-->
