# F04 plan — the partial requirements and DEC-1, one batch per session

**Feature:** F04 (ROADMAP "What 1.0 requires", item 3), state `active` until the last batch and the release.
**Rule from the owner (2026-10-21):** one batch per session — a batch is finished with its review and fixes, committed,
and the session stops; the next batch starts in a fresh session from this file. No version bump and no tag until the
last batch; then 0.176.0 is released locally in one go (version, CHANGELOG with every verdict move and the ledger
before/after, README counts, tag on the changelog commit, `make verify-feature F=F04`). Heavy commands (make test, make check,
ci_local, mutations, the reviewer's runs) run under `nice -n 15` (the owner, 2026-10-22; `taskpolicy -b` before it took
about 65 minutes a suite), one full run at a time; a single mutation runs only the named test module.

## The list, derived from the specs

From each `openspec/specs/*/spec.md` Appendix B row and `**Reader:**` line at `efce43e` (0.175.0), not from memory:
`spec_debt.py` read **158 requirements: 132 enforced, 21 partial, 1 none, 4 bounded**.

| spec | partial / none at `efce43e` |
|---|---|
| declarations | DEC-4, DEC-8, DEC-9 partial; **DEC-1 none** |
| evidence | EVD-1, EVD-2, EVD-10 |
| governance | GOV-2, GOV-3, GOV-5, GOV-6, GOV-7, GOV-12 |
| http | HTTP-10, HTTP-13 |
| inputs | INP-10 |
| operator-protocol | OPR-1, OPR-4 |
| registry | REG-1, REG-6 |
| verdicts | VRD-2, VRD-3 |

**REG-6 is out of scope**: it is F03's (a second reader of the item readings) and stays `partial`. F04's scope is the
other 20 partial and DEC-1: **21 requirements**.

## Batches, in order

| batch | requirements | contract | state |
|---|---|---|---|
| 1 | HTTP-10, HTTP-13, INP-10, EVD-10 (+ H13-c) | `docs/sprint-20261021-F04-1.md` | **done**: `4be01d8` (active + contract), `005886e` (code), `f831882` (review 1 fixes), `3d01157` (H13-c + this plan), review 2 fixes in the commit after it (see the contract) |
| 2 | EVD-1, EVD-2, VRD-2, VRD-3, REG-1 | `docs/sprint-20261021-F04-2.md` (`3e847cf`) | **done**: `33e96b7` (batch 1's suffix-list tests in UTC), `216e620` (code), `54916fb` (review 1 fixes), `a6b4853` (review 2 fixes), this plan in the commit after it; `make test` 2570 OK |
| 3 | DEC-1, DEC-4, DEC-8, DEC-9 | `docs/sprint-20261022-F04-3.md` (`f2fec34`) | **done**: `953c5a8` (code), `c82613c` (outcome and mutations), `b692b9d` (review fixes), `c5f0d23` (epoch read at the call: the first full run's one failure), this plan in the commit after it; `make test` 2584 OK |
| 4 | GOV-2, GOV-3, GOV-5, GOV-6 | to write | not started |
| 5 | GOV-7, GOV-12, OPR-1, OPR-4 | to write | not started |
| release | 0.176.0 locally, `make verify-feature F=F04`, rubric | — | after batch 5 |

Spec debt after batch 1: **136 enforced / 17 partial / 1 none / 4 bounded**. After batch 2: **141 enforced / 12
partial / 1 none / 4 bounded** (`tests/spec-debt.json`); all five held in full, none narrowed. After batch 3:
**145 enforced / 9 partial / 0 none / 4 bounded**; DEC-9 held in full, DEC-1, DEC-4 and DEC-8 narrowed, each narrowing
said in its Reader line and filed in the contract's Outcome.

## Decisions already made

- **MD-184 and AR-153** were F06's (0.175.0), decided by the owner there; nothing in F04 reopens them.
- **H13-c** (a crawled page that gave no answer), the owner, 2026-10-21, "C: retry, then withhold": a page whose
  request timed out or whose connection was refused or reset is asked once more; silent twice, the crawl is `truncated`
  and counts it in `summary.unanswered_pages`, and the 14 inventory readers that pass by absence withhold PASS; FAIL and
  WARN stand; an HTTP status, a guard refusal, TLS and robots are not retried. Done in batch 1.
- Review is a separate Claude agent with a fresh context (`model: fable`), read-only, mutating in its own export and
  its own scratch subdirectory — not Codex (the owner's choice for F06, kept for F04).
- Each requirement is held in full where the gap is a defect a user would meet, or narrowed with the narrowed part
  named and filed; never narrowed when the gap is a verdict bug. `enforced` only on mutation evidence.

## Open findings carried over

- Batch 2 (filed in its contract's Outcome and Review): `gsc_url_inspection.py` labels any `OSError` in one `try` —
  `build_service` and the inspection call — `input`, so a network timeout on the Search Console API reads as the
  operator's key file (`gsc_cannibalization` was repaired the same way in batch 2; this one was not its change).
  `measurement()` says `got 0` on an issue at an unknown severity where the verdict is `NO_DATA` (not graded).
  The EVD-2 scan does not read a severity table assembled key by key at run time.
- Batch 2, for the release CHANGELOG: eight checkers' "script failed" reads "an input this check was given could not
  be used" (label only); a model's `N/A` with no evidence is refused and the item stays `LLM_PENDING`; an issue at a
  severity outside the vocabulary (or `null`) reads `NO_DATA` naming it where it read `PASS` (no shipped checker
  writes one); `audit_assertions.py` refuses a rule naming such a word.
- Batch 3 (filed in its contract): DEC-1 does not hold whether a batch's `given` is the whole of what its session saw,
  an amended commit (declare, run, adjust, amend), or the 248 declarations before `BATCH_EPOCH`; DEC-4 does not hold
  that a reason names its tree, that its argument is true, or a run cited in words outside its list; DEC-8 does not
  hold a checker repaired under a standing declaration. Found on the way: a rule's `truthy: false` is read as
  `truthy` (`checklist_runner.py:1053` tests the key); no shipped rule writes it — a registry question.
- Batch 3, for the release CHANGELOG: **no verdict moves.** The manifest is `schema_version` 3: each declaration
  records `basis` (its item's title and rule as one digest), and `batches` records what each declaring session was
  given; `tests/test_fixture_oracle.py` refuses to run a declaration `HEAD` does not hold; three reasons lost
  "corrected from FAIL after the run"; ledger 141/12/1/4 → 145/9/0/4, DEC-1 no longer unread.
- Batch 1: the withheld evidence over a crawl cut by a refused or an unanswered page reads the readers' cap wording
  ("what the cap left out"); naming the cause needs the readers or the runner to carry it.
- Full-suite timing: `taskpolicy -b make test` took 67 minutes on 2026-10-22 (2569 tests), not ~9; budget for it.
  Batch 3's run of 2584 tests took 65 minutes.

## Starting the next batch

```bash
cd ~/seo-checklist-release && git fetch && git status --short --branch
```

Batch 4 is GOV-2, GOV-3, GOV-5, GOV-6 (`openspec/specs/governance/spec.md`); its contract is to write, from
`templates/sprint-contract.md`, with expectations declared and committed before any test is written (as `f2fec34` did
for batch 3). Read each requirement's Reader line and Appendix B row first, and check whether the line is stale
against the code before declaring — batch 2 found two Reader lines stale, batch 3 one (DEC-9), and both batches had
declared forms the measurement contradicted. Confirm each mutation moved what it targets before reading a green
result (batch 3's first census mutation was a no-op). Then implement, mutate, ledgers together (`spec_debt.py --out` / `--check`,
ROADMAP table and item 3, `test_prose_counts`), `nice -n 15 make test` (about 10–15 minutes, with `run_in_background`), commit, review by a fresh
`fable` agent, fixes, commit, update this file, stop.
