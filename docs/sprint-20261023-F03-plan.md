# F03 plan — every item reading checked by a second reader, one batch per session

**Feature:** F03 (ROADMAP "What 1.0 requires", item 2; `openspec/specs/registry/` REG-6, the one `partial`
requirement left), state `active` from batch 1.
**Rule from the owner (carried from F04/F05):** one batch per session — a batch is finished with its review and fixes,
committed, and the session stops; the next batch starts in a fresh session from this file, on the owner's reply. No
version bump and no tag until after the last batch (the release is its own step). Heavy commands (`make test`,
`make check`, `ci_local`, mutations, the reviewer's runs) run under `nice -n 15`, one full run at a time; commit before
any mutation script (its `git checkout` restore wiped uncommitted work once); a killed `ci_local` leaves `live.json` and
`server.log` in the root, so stage named paths.

## Where REG-6 stands, measured

On `0b97a4b` (0.177.0), 2026-10-23: `skills/seo-checklist/tools/item-readings.json` holds **145 readings** — one per
rule-carrying item, across 57 scripts — **114 `answers`, 31 `measures`, 0 `owed`**; `audit_item_readings.py --check`
exits 0. Every reading was written by the session that wrote or repaired the item (0.114.0–0.176.0), and nothing has
read any of them since. The tool says so itself (`DOES_NOT_ESTABLISH`: "that any reading is true, which a person
decides"), and REG-6's Reader line keeps the requirement `partial` for that one reason.

## What "checked by someone other than its author" means, as a property a test can see

1. **Where the second reading lives.** In the reading's own entry, as `second_reading`, so a diff shows both readings
   side by side and no second file has to be kept in step with the first:

   ```json
   "second_reading": {
     "reader": "codex gpt-6.1-sol high",
     "session": "<the Codex session id that produced it>",
     "read": "<digest of what it read>",
     "verdict": "answers | measures | owed",
     "dispute": "<optional: what the second reader says the first reading gets wrong>"
   }
   ```

2. **What makes it current.** `read` is a digest of everything the second reader judged: the item's title, check and
   `measures` sentence (from the registry) and the first reading's verdict, reading and shape answers. Any change to
   any of them makes the second reading stale and the audit names the item — the same rule the first reading already
   lives under ("a changed rule is re-read by hand, or the build stays red"), one level up. From batch 3 the digest
   also covers what the reader was shown of the code — the script's source and, for a script that reads another
   program's JSON, that program — and is taken when `--blind` prints the input, not when the answer is entered.
   **Trade-off:** an edit to a script re-stales every item that script backs (F15's `parse_html.py` repair sends all
   14 back to Codex). Imported helpers are left out, so a helper's edit re-stales nothing; the tool's
   `DOES_NOT_ESTABLISH` says so. The tool prints the digest
   (`--digest ID`); it never writes the file.

3. **What makes it count as independent.** The owner's ruling (2026-10-23, in the F03 planning session: "Чеки кодексу
   отдавай" — give the checks to Codex): **the second reader is Codex** (`-m gpt-6.1-sol -c
   model_reasoning_effort=high`), a different model from the Claude sessions that wrote the readings, run with a fresh
   context and a brief kept in the repo. The record names the reader and the Codex session id, which is the trace a
   person can open; no program can prove from a string who wrote it, and the tool's `DOES_NOT_ESTABLISH` says so.

4. **Agreement and dispute.** A second reading agrees when its verdict equals the first reading's and it carries no
   `dispute`. Otherwise it is disputed. What a dispute does is question 2 below.

5. **What the audit fails on.** From batch 1: a `second_reading` that is malformed (missing or empty `reader`,
   `session`, `read`; a verdict outside the three; a key the record does not define) or stale (`read` is not the
   current digest). Counted but not failing until the last batch: readings with no second reading, and disputes. The
   last batch turns both into failures, and from then on a new or changed reading is red until Codex has read it.

## Batches, in order

| batch | what | contract | state |
|---|---|---|---|
| 1 | The instrument: the `second_reading` record, its digest, every malformed or stale record named by `--check`, `--digest ID`, the summary line (`N of 145 second-read: A agree, D disputed`), `ESTABLISHES`/`DOES_NOT_ESTABLISH`, REG-6's Reader line. No second reading is written | `docs/sprint-20261023-F03-1.md` | **done**: `1155f47` (active + plan + contract), `22c5f62` (code), `f084a3a` (Codex review fixes), `062830b` (suite-rule and derived-set fixes found by `make check`), this plan in the commit after it; `ci_local` 27/27 on `062830b` (Tests step 557 s), arch 3/3; `make check` exit 2 only at VCR, because F03 is `active` |
| 2 | The reader, calibrated: the brief in the repo (`tools/second-reading-brief.md`, shaped by Q1); a command that prints one item's brief input; **calibration** — Codex reads the seven pairs `TheShapesWouldHaveExposedEveryItemRepairedByHand` holds as they stood at `v0.104.0`, mixed with seven current items, blind to which is which; the threshold of Q4 must hold before any real reading counts; then the first real second readings, script by script from the largest group (`parse_html.py` 14, `rendered_audit.py` 8, …), about 25 items | `docs/sprint-20261023-F03-2.md` | **stopped at calibration**: brief, `--blind`/`--open` built and reviewed (`7cd8fb2`, `097dde1`, `ff5ca41`, `66f13d0`, `0a6ee2a`, `423657f`); Codex called 7/7 defective pairs `owed` but left 2/7 controls undisputed (bar 6) — two disputes are confirmed defects (CI-004, MS-028), three a blind-input gap (`rendered_audit.py`'s numbers come from a `SKILL.md` snippet); no second reading entered; `ci_local` 27/27 on `423657f`; waits for the owner: brief rewrite, how the bar scores a confirmed dispute |
| 3 | The brief rewritten and calibration re-run (the owner's answers to batch 2's questions); then, if the bar holds, batch 2's 29 second readings and more, script by script | `docs/sprint-20261024-F03-3.md` | **done**: `5f80d43`, `b517dde` (contract, with two digest findings on batches 1–2 the owner sent in), `8afd2f8` (the producer shown; the digest covers source and producer and is taken at `--blind`), `251f159` (calibration holds: 7/7 called, 1 undisputed + 6 source-confirmed findings among the controls; 29 second readings, 8 agree, 21 disputed), `5f390f7` (Codex review: four medium, two low, all fixed); 11/11 mutations red; next: `docs/sprint-20261024-F03-4-brief.md` |
| 4 | Second readings, ~40 items | `-F03-4.md` | — |
| 5 | Second readings, the rest (~40) | `-F03-5.md` | — |
| 6 | Close: every dispute resolved as Q2 rules; `--check` fails on a missing second reading and on an unresolved dispute; REG-6 `enforced`, ROADMAP item 2 and the partial count (`tests/test_prose_counts.py`), KNOWN-ISSUES; `make verify-feature F=F03` | `-F03-6.md` | — |

Each reading batch hands its disputes to the owner as one list (item, first verdict, second verdict, the dispute) and
does not resolve them itself. Batches 3–5 may merge if Codex's per-item cost turns out small; batch 2 measures it.

## Done criterion — decided by the owner, 2026-10-23 (Q5: all 145)

**F03 is done when every one of the 145 rule-carrying items carries a current second reading by Codex, no dispute is
unresolved, `audit_item_readings.py --check` fails on a missing, stale or disputed second reading, REG-6's Reader line
says `enforced`, and `make verify-feature F=F03` passes.** The partial count in ROADMAP goes 1 → 0.

## Questions for the owner (Anton) — all six answered 2026-10-23: the recommended option of each (see Decisions)

Batch 1 depends on none of them: it builds the record and its checks, which every answer below needs, and writes no
second reading. Batch 2 starts only once Q1–Q4 are answered.

1. **Blind or open?** (a) **Blind, then open — recommended.** Codex first gets the title, the check, the `measures`
   sentence and the script's source, not the first reading, and writes its own verdict; only then is it shown the
   first reading and asked whether it disputes anything in it. A verdict reached without seeing the answer is the
   only kind that can disagree for its own reasons. Cost: two prompts per item. (b) Open: Codex sees the first reading
   and confirms or disputes it — cheaper, and anchored on the answer it is checking.
2. **A disputed reading.** (a) **Recommended:** red until resolved, and only the owner resolves one — by ruling for
   one side with a written reason recorded in the entry (`resolution`), or by having the item or the reading changed,
   which makes the second reading stale and sends it back to Codex. During batches 2–5 disputes are counted, not red,
   and listed for the owner at the end of each batch. (b) Treat a disputed reading as `owed` (the way `--llm-review`
   treats a contested LLM verdict: it withdraws confidence), counted, never red.
3. **After F03: does a changed reading wait for Codex before the build is green?** (a) **Recommended: yes.** Otherwise
   REG-6 is enforced on the day F03 closes and partial again on the first rule change. Cost: every release that
   touches a rule, title or `measures` sentence runs Codex on those items before its commit. (b) No: a stale or
   missing second reading is counted and reported, never red — REG-6 then stays `partial`, with the gap stated.
4. **Calibration threshold.** The seven `v0.104.0` pairs are the only items this repo knows to have been defective.
   (a) **Recommended:** Codex must call all seven defective (verdict `owed` or a dispute naming the defect) and leave
   at least six of the seven current controls undisputed, or no real reading counts and the brief is rewritten.
   (b) A looser bar, e.g. five of seven.
5. **The done criterion above**: all 145, or a sample (say one item per script, 57)? Recommended: all 145 — REG-6
   is about every item, and a sample leaves the requirement `partial` by its own wording.
6. **Authorship of the existing 145.** Every reading was committed under one git identity; the plan assumes Claude
   sessions wrote them all (so Codex is a different model for every one). If any was written by Codex, the fresh
   context of the second run is what makes it independent (the earlier ruling: fresh context, not necessarily another
   model). Recommended: record nothing per entry; a future reading Codex writes is second-read by a fresh Claude
   session, and the record's `reader` says so.

## Decisions already made

- **Q1–Q6 ruled by the owner, 2026-10-23** ("F03: accept the recommended answers to Q1–Q6"): (1) blind, then open —
  Codex writes its own verdict from title, check, `measures` and the script's source before it sees the first
  reading, then is shown it and asked for a dispute; (2) a dispute is red until the owner resolves it (a recorded
  `resolution`, or the item or reading changed, which re-stales the record) — counted, not red, during batches 2–5 and
  listed for the owner at the end of each; (3) after F03 a new or changed reading is red until Codex has read it;
  (4) calibration bar: Codex calls all seven `v0.104.0` pairs defective and leaves at least six of seven current
  controls undisputed, or no real reading counts and the brief is rewritten; (5) done = all 145; (6) the 145 are taken
  as Claude's, nothing recorded per entry, and a future reading Codex writes is second-read by a fresh Claude session.

- **Batch 2's calibration questions ruled by the owner, 2026-10-24** ("F03: take the recommended options"): (1) the
  blind input shows the code that produces the JSON a script reads, where that code is not the script (first case:
  `rendered_audit.py`'s numbers come from the browser snippet in `SKILL.md`); (2) a control dispute that the source
  confirms is scored as a finding, not as the reader's miss, and calibration is re-run on the same fourteen items
  with the rewritten brief; (3) CI-004 and MS-028, confirmed defective by that calibration, are repaired as their own
  feature (F15), not inside F03.

- **The second reader is Codex** (`gpt-6.1-sol`, reasoning effort high), and so is the review of each batch's code
  (the owner, 2026-10-23, F03 planning session: "Чеки кодексу отдавай"). This replaces the F05 practice of a fresh
  Claude reviewer for this feature.
- A reviewer needs a fresh context (no memory of the work); not necessarily another model (earlier ruling, carried).
- One batch per session, the plan file carries state; each next batch starts on the owner's reply.
- Only `make verify-feature F=F03` writes `passing`.
- There is no command that writes `item-readings.json`; a second reading is entered by hand from Codex's answer.
- Every new check is proven by a mutated readings file the audit must name, red before the change, green after.

## Open findings carried over

- Batch 1: Codex's review of `22c5f62` (gpt-6.1-sol, high, read-only): one medium (a non-string `reader`/`session`
  passed and was counted current) and one low (the key-order test did not exercise `sort_keys`), both fixed red-first
  in `f084a3a`. The follow-up `062830b` was not re-reviewed: it changes a test's subprocess call to the suite's rules
  and re-records `tests/derived-sets.json`. For the release CHANGELOG: no verdict moves; `audit_item_readings.py`
  gains the `second_reading` record, `--digest`, and a summary line.
- `make check` cannot exit 0 while a feature is `active` (its last gate, `make vcr`, fails by design); batches report
  `ci_local` and `check-arch`, as F05's did.
