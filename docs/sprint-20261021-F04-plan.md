# F04 plan — the partial requirements and DEC-1, one batch per session

**Feature:** F04 (ROADMAP "What 1.0 requires", item 3), state `active` until the last batch and the release.
**Rule from the owner (2026-10-21):** one batch per session — a batch is finished with its review and fixes, committed,
and the session stops; the next batch starts in a fresh session from this file. No version bump and no tag until the
last batch; then 0.176.0 is released locally in one go (version, CHANGELOG with every verdict move and the ledger
before/after, README counts, tag on the changelog commit, `make verify-feature F=F04`). Heavy commands run under
`taskpolicy -b`, one at a time; a single mutation runs only the named test module.

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
| 1 | HTTP-10, HTTP-13, INP-10, EVD-10 (+ H13-c) | `docs/sprint-20261021-F04-1.md` | **done**: `4be01d8` (active + contract), `005886e` (code), `f831882` (review 1 fixes), H13-c and review 2 in the commits after them (see the contract) |
| 2 | EVD-1, EVD-2, VRD-2, VRD-3, REG-1 | `docs/sprint-20261021-F04-2.md` (`3e847cf`) | begun, **not committed**: work in progress parked as a patch outside the repository (the owner's handoff names the path) |
| 3 | DEC-1, DEC-4, DEC-8, DEC-9 | to write | not started |
| 4 | GOV-2, GOV-3, GOV-5, GOV-6 | to write | not started |
| 5 | GOV-7, GOV-12, OPR-1, OPR-4 | to write | not started |
| release | 0.176.0 locally, `make verify-feature F=F04`, rubric | — | after batch 5 |

Spec debt after batch 1: **136 enforced / 17 partial / 1 none / 4 bounded** (`tests/spec-debt.json`).

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

- Batch 2, from its notes so far (with the parked patch): EVD-1's census found eight jobs labelled `crash` with nothing
  to work with — four repaired to `input` in the patch; the four Search Console scripts are excused only while the
  `gsc` extra is absent, and their unusable-key path is unread. **E2-c was declared wrong**: `audit_assertions.py`
  does not refuse a rule naming an unknown severity (the patch's test does). **VRD-2/VRD-3 were declared wrong**: the
  sourceless gap was closed at 0.98.0 by `APPLIES_IF` (`applies_if`, shown to the answerer); their Reader lines are
  stale and both look holdable without narrowing. REG-1's tests are written (`reg1_snippet.py` beside the patch) and not
  yet in `tests/test_registry.py`.
- Batch 1: the withheld evidence over a crawl cut by a refused or an unanswered page reads the readers' cap wording
  ("what the cap left out"); naming the cause needs the readers or the runner to carry it.
- Batch 1, EVD-1 adjacent: none other.

## Starting the next batch

```bash
cd ~/seo-checklist-release && git status --short --branch
git apply <the parked b2-wip.patch>     # path in the owner's handoff
cp <the parked test_checker_contract.py and test_severity_vocabulary.py> tests/
```

Then finish batch 2 against its contract: REG-1's tests into `tests/test_registry.py` (red on a hand-edited artifact
first), the five Reader lines and Appendix B rows (VRD-2/VRD-3 corrected to name `APPLIES_IF`, the partition tests,
the merge test and `test_the_question_reaches_the_queue_from_the_registry`), ledgers together (`spec_debt.py --out`,
ROADMAP table and item 3, `test_prose_counts`), the contract's Outcome with the mutations, `taskpolicy -b make test`,
commit, review by a fresh `fable` agent, fixes, commit, update this file, stop.
