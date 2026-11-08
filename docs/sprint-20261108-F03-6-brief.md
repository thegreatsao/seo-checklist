# F03 batch 6 — the brief for the session that closes F03

Written at the end of batch 5 (`docs/sprint-20261108-F03-5.md`, results there). Plan: `docs/sprint-20261023-F03-plan.md`.
The owner's rule holds: batch 6 starts in a fresh session, and only on the owner's reply. It cannot start before F15
is `passing`.

## Where batch 5 left it

- `second readings: 145 of 145 current — 33 agree, 112 disputed`; `--check` exit 0. Every rule-carrying item has a
  second reading; the reading part of F03 is closed.
- Disputes waiting for the owner's ruling: batch 4's 30 (`docs/sprint-20261108-F03-4.md`) and batch 5's 61 (its
  contract's table). Batch 3's are ruled (plan, "Batch 3's disputes ruled").
- F03 is still `active`. By the plan's order it goes `blocked` when F15 is activated, and F15 repairs every confirmed
  defect and `measures` sentence of batches 3–5 as the owner rules them.

## Before this batch: the order

1. The owner rules batch 4's and batch 5's disputes: the confirmed as defects or not, and each "fact confirmed" defect
   or not — as batch 3's were ruled (plan, "Batch 3's disputes ruled": a narrower rule with no `measures` sentence is a
   defect repaired by a sentence; a false-FAIL side or a recorded convention may be ruled no defect).
2. F03 `blocked` on F15; F15 `active`, repairs, `make verify-feature F=F15` writes `passing`. Each repair re-stales the
   second readings of the items whose script, rule, title, `measures` sentence or first reading it changes.

## Batch 6

1. Contract `docs/sprint-YYYYMMDD-F03-6.md`, committed before any `ci_local` run.
2. **Re-read every stale item** by batch 4's recipe (batch 5's `run.sh` and `enter.py` pattern: blind, then open in
   the same Codex session; one script per group, single-item scripts in groups of three to five, no two inventory
   readers in one group). The summary then counts what F15 left disputed.
3. **The `resolution` record** (the plan's Q2, ruled): a sixth key of `second_reading`, written by hand from the
   owner's ruling — who ruled, the date, for which side, the reason. `SECOND_READING` and
   `test_the_record_defines_the_five_keys_the_plan_names` change with it, red first. A resolved dispute counts as
   resolved; an unresolved one is red.
4. **`--check` turns strict**: a missing second reading, a stale one and an unresolved dispute each fail it, each
   proven by a mutated readings file the audit must name, red before and green after.
5. Resolve what is left by the owner's rulings, including SP-108 and SP-113 (ruled no defect in batch 3, resolved
   here for the first reading with that reason) and every "no defect" ruling from batches 4–5.
6. REG-6's Reader line → `enforced`; ROADMAP item 2 and the partial count (`tests/test_prose_counts.py`, 1 → 0);
   KNOWN-ISSUES; then `make verify-feature F=F03`, which alone writes `passing`.
7. Codex reviews the diff in a fresh session; fixes red first. Clock out as batch 5 did.

## Wait

- `pgrep -f ci_local.py` matches the shell that runs it: a wait loop on it never ends. Use
  `ps -axo command | grep -c "[t]ools/ci_local.py"` or wait on a stamp.
