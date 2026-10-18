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
