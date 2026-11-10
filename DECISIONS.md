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

### [2026-11-10] GO-145 and GEO-005 are N/A on utility pages (privacy, terms, contact)

**Decision:** The owner's ruling 1 on F15 batch 5's questions ("Принимаю, батч 6", 2026-11-10; the F15 contract, "The
owner's rulings on batch 5's questions"). A sampled page that is a privacy, terms or contact page gets N/A from GO-145
and GEO-005 instead of FAIL; every other page keeps the batch 5 rule (a page whose content names no source scores 0).
An about page is not a utility page: it makes claims about the business. The page is classified by its own URL
slug. The plugin classified no page by type, and its href vocabulary (`eeat-terms.json`) read as slug substrings or
prefixes took articles (`/blog/gdpr-compliance-checklist`, `/kontaktlinsen`) for policy pages in F15 batch 6's review,
so the smallest deterministic rule is a closed vocabulary in `citation_readiness.py`: a slug made only of listed
privacy, terms, contact and filler words (and numbers), holding one of the first. Each item's `measures` sentence
states it; the lists' misses are filed in the F15 contract.

**Why:** a privacy policy, terms of service or a contact page makes no factual claim a source could back, so a FAIL
there is a verdict on citations the page never needed; batch 5's rule made the exemplary fixture fail both items on
its privacy page.

**Alternatives rejected:**
- **Keep FAIL everywhere (batch 5's reading):** a high-severity FAIL on every site's privacy page.
- **N/A on any page making no factual claim:** reads claims by a heuristic (`CLAIM_RE`); an about page with no number
  in it would escape the rule the owner meant it to meet.
- **About pages as utility pages:** the owner ruled them out; they make claims about the business.

**Consequences:** census trees whose sampled pages include a privacy, terms or contact page drop that page's FAIL
(the move declared before the run); a site whose only failing sampled page is a utility page moves FAIL → PASS or N/A.
A word missing from the closed lists fails a utility page as before, and a listed word read in an article's slug
makes it N/A; each is a one-word edit with a test.

---

### [2026-11-10] An hreflang set naming only the page itself is N/A for IN-122

**Decision:** The owner's ruling 2 on F15 batch 4's questions ("Принимаю, батч 5", 2026-11-10; the F15 contract, "The
owner's rulings on batch 4's questions"). A page whose hreflang annotations name no URL but its own gets N/A from
IN-122, not FAIL; the codes in it are still checked, so a malformed code on such a page still fails. Three-letter
language codes keep failing (Google documents ISO 639-1). The `measures` sentence says so.

**Why:** IN-122 judges whether alternates point at each other correctly; a set with no other URL has nothing to
compare, so a FAIL would be a verdict on a comparison that never took place. Batch 4's FAIL read the F03 ruling's "no
vacuous pass" as "fail"; N/A is also no pass.

**Alternatives rejected:**
- **FAIL (batch 4's reading):** a verdict about a comparison with nothing on the other side.
- **PASS:** the vacuous pass the F03 ruling forbade.
- **Accepting three-letter codes when no two-letter one exists (`fil`, `yue`):** Google's documentation names ISO
  639-1; the owner kept the stricter reading.

**Consequences:** A census tree whose pages carry a self-only set moves IN-122 FAIL → N/A; the move is declared before
the run.

---

### [2026-11-10] A cross-host canonical alone passes every canonical item; AR-153 and AR-162 are N/A on small sites

**Decision:** The owner's rulings on F15 batch 3's questions ("Принимаю все", 2026-11-10; the F15 contract, "The
owner's rulings on batch 3's questions"). (1) TE-176 and CI-009 no longer fail a canonical that names another host on
its own; its target is still requested, and a target not answering 200 still fails. (3) AR-153 and AR-162 report N/A,
not FAIL, below a minimum page count, the smallest the rule's own arithmetic justifies; each minimum is in the item's
`measures` sentence. BL-081's single generic or empty anchor still flags its target (ruling 2), until F03 batch 6.

**Why:** CI-011's ruling already calls a cross-host canonical legitimate (syndication, a moved section); three items
reading the same declaration three ways told a client one thing was right and wrong at once. A site too small for the
rule's bar to be reachable cannot be judged by it: a FAIL there is the rule's arithmetic, not the site's design.

**Alternatives rejected:**
- **Warn on a cross-host canonical:** still a verdict about a declaration the owner ruled legitimate.
- **A fixed "small site" size for both items:** each rule's bar is different; a shared number would be unjustified
  for at least one of them.
- **Keeping AR-162's orphan and dead-end findings on a small site:** orphans are CI-008's, which still reads them;
  the ruling is N/A for the item.

**Consequences:** CI-009's `cross_host` maps to pass; TE-176's `issues` carries no cross-host entry. A site below the
minimum gets no AR-153 or AR-162 verdict at all.

---

### [2026-11-09] A stale second reading is counted, not failed, until F03 batch 6

**Decision:** `tools/audit_item_readings.py` counts a well-formed second reading whose digest no longer matches as
`stale` (named in the summary) instead of failing `--check`. A malformed record still fails.

**Why:** the owner's ruled order for F03 (the F03 plan, "Batch 3's disputes ruled", item 6) has F15 repair the items F03
read and reach `passing` before batch 6 re-reads them; every repair re-stales a reading, so under the old rule F15 could
never pass `make test`. Batch 6's brief (step 4) already plans `--check` turning strict on stale readings.

**Alternatives rejected:**
- Delete each stale `second_reading` as F15 changes its item: loses Codex's recorded dispute, which batch 6 resolves.
- Re-read each changed item with Codex inside every F15 batch: batch 6's work done seven times.

**Accepted by the owner, 2026-11-09** ("Keep it").

**Consequences:**
- Between F15 batch 1 and batch 6 `--check` is weaker; the summary line carries the stale count and ids.
- Batch 6 must make a stale reading fail again, red first (its brief, step 4).

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
