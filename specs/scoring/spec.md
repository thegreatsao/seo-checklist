# Scoring — the headline number and what it is allowed to mean

**Capability:** how graded items become a score, a weight share, five buckets and a fix
order (C7, C8 of the capability inventory).

This document is normative and is written as though no code existed. Where the
implementation disagrees, the implementation is presumed wrong until this document is
changed by argument. Appendix A records disagreements measured on 26 August 2026.

Every requirement carries a **Reader** line naming what makes it fail when violated;
Appendix B is the census of those lines. A requirement whose reader is `none` is an
intention, and is counted as one.

**Inherited, not restated:** which statuses exist, and that only `PASS`, `WARN` and
`FAIL` may carry weight, belong to [`specs/verdicts/`](../verdicts/spec.md) (VRD-6,
VRD-7). This document says what is done with them and must not redefine them.

---

## 1. Why this document exists before the others

The score is the one number a client reads and the only one they repeat. The headline
uses severity weights and verdict credits; the fix order also uses effort costs. The
readers for these small tables are narrow and indirect. Two tests assert a concrete
total of 6 for sets of `medium` items, so changing `SEVERITY_WEIGHT['medium']` from 3
fails them. A priority-relation test constrains `EFFORT_COST` only as an inequality —
cheap work must outrank equally severe expensive work — so it fails at 1 and passes at 2,
3 or 5. No test pins the shipped 4. Concrete single-row scores exercise the three verdict
credits. Nothing pins the `critical`, `high` or `low` severity weights — including
`critical`, the most influential value of all.

The release and history obligations in SCR-2 remain wholly unread: nothing requires a
table change to be declared, invalidates comparison with old runs, or warns when a
baseline used another table. This is a smaller finding than “the tables have no
reader,” and it is still the largest enforcement gap in this document.

A CI sensitivity tool reported movements of 0.2, 1.9, 9.3 and 14.6 points under
alternative tables. Those numbers are outputs of a tool that does not fold twins and
therefore does not reproduce the shipped arithmetic; they are not evidence of the true
exposure. How far the shipped score and fix order move under table changes remains
unmeasured. A table edit can nevertheless change scores, fix order and the meaning of
comparisons with archived runs in `.seo-runs/`.

---

## 2. The three tables

### 2.1 Severity weight

| severity | weight | items in the registry |
|---|---:|---:|
| critical | 10 | 19 |
| high | 6 | 62 |
| medium | 3 | 102 |
| low | 1 | 34 |

### 2.2 Verdict credit

| status | credit |
|---|---:|
| `PASS` | 1.0 |
| `WARN` | 0.5 |
| `FAIL` | 0.0 |

### 2.3 Effort cost

| effort | cost | items in the registry |
|---|---:|---:|
| low | 1 | 66 |
| medium | 2 | 52 |
| high | 4 | 99 |

All three are **normative constants of the audit**, not implementation details. Their
provenance is `inherited`: nobody in this project chose them. SCR-2 says what follows
from that.

---

## 3. Requirements

### SCR-1 — weight is carried per check, never per item

Where several registry items ask one question of one script with one assertion, exactly
one of them carries the weight. The others report their own status and contribute
nothing to either half of the score or to a category score.

**Why:** otherwise one defect pulls the headline twice, and where the twins disagree on
severity the weight of a single defect depends on which item a reader happens to look
at. Both conditions exist in the registry today: 9 twins across 7 primaries, of which
MB-102/MD-190 and SP-112/SP-108 disagree on severity.
**Reader:** partial, and the label cannot be stronger while Appendix A stands. The
headline half is read — `tests/test_runner.py` asserts a twin pair scores once, and
`tools/audit_item_semantics.py` in CI refuses any two items sharing script, arguments
and assertion without a recorded ruling. The category half is read by nothing and is
violated today: category sums iterate every scored row, twins included. A requirement
whose own appendix records a live violation of half its sentence is not enforced.

### SCR-2 — all three tables are normative, and changing one is a release event

The values in §2 are part of the audit's contract. Changing any of them:

* must be stated in the release that does it, in those words;
* invalidates comparison with every archived run scored or ordered under the previous
  table;
* requires the run comparison to refuse, or to warn in the report, when the baseline
  used a different table.

**Why:** the score is quoted to clients and compared across months. A table change is a
change of instrument, not of the site, and a trend line spanning one is a lie about the
site.
**Reader:** partial. Two tests indirectly pin `SEVERITY_WEIGHT['medium'] = 3` through a
concrete total of 6, and a priority-relation test indirectly pins
`EFFORT_COST` as an inequality rather than a value; concrete single-row tests exercise the
verdict credits. Nothing pins the `critical`, `high` or `low` severity weights, and no
reader enforces any of the release, comparability or warning obligations. This smaller finding remains the largest
enforcement gap in this document.

### SCR-3 — the score is a weighted fraction of what was decided

`seo_score` = 100 × Σ(weight × credit) ÷ Σ(weight), over decided items excluding twins.
When nothing was decided, the score is **absent**, not zero.

**Why:** zero is a verdict about a site; absence is a statement about the audit. A site
that could not be read must not be reported as scoring zero.
**Reader:** partial. Unit tests pin `score()`'s arithmetic and its absent value, and the
unreachable-site CI step asserts that no score line is printed for an unreachable run.
No reader covers a reachable run with nothing decided; both renderers and the console
currently print `None/100` for that case.

### SCR-4 — the score may never appear without its weight share

`weight_pct` — the weight the score was computed over, as a percentage of the weight of
all applicable items — travels with the score on every surface: console, report,
artifact, and any sentence an operator or agent writes.

**Why:** 69 over 55% of the registry's weight and 69 over 95% are different claims, and
the number alone does not say which one is being made. A score without its share is a
fraction with the denominator torn off.
**Reader:** none. Both renderers do print the two together, but that is the behaviour
under audit, not a reader of it: no assertion fails if either renderer or the console
drops the share. Current conduct is not enforcement, and the distinction is exactly what
this document's Reader lines exist to keep.

### SCR-5 — `N/A` leaves both numerator and denominator

An item that does not apply — to this site, this mode, or this profile — is absent from
the score and from `weight_applicable`.

**Why:** otherwise narrowing scope would make an audit look thinner rather than
narrower, and the incentive would run the wrong way. This is VRD-7 applied to the number
that replaced coverage.
**Reader:** partial. Unit tests pin `N/A` out of the score and compare reach with and
without `N/A`, but no assertion directly pins the returned `weight_applicable` value.

### SCR-6 — narrowing scope remains a registry partition

Any mechanism that takes an item out of a run — category selection, profile exclusion,
mode capability or applicability — must leave the item in the registry and classify it
as `N/A`. Removing rows from the run's item list is forbidden: the five-bucket partition
must sum to the registry, not merely to the selected rows. Narrowing by site type also
requires the advance or on-sight consent specified by VRD-11.

These rules can require narrowing to be visible and consented to. They cannot require a
chosen profile to be true of the site; that claim remains outside what scoring can
verify.

**Why:** the documented route to a better-looking audit is a narrower one, and the only
defence available here is that narrowing is visible and scores nothing. A `high` item
excluded by a profile is a scoping decision a reader must be able to see.
**Reader:** partial. Registry and profile tests govern some exclusions and forbid a
profile from excluding a `critical` item. They do not enforce the full-registry
partition across every narrowing mechanism, and category selection violates it today.

### SCR-7 — the partition names whose action moves each item

Every item lands in exactly one of five buckets, and the buckets sum to the registry:

| bucket | statuses | whose move |
|---|---|---|
| `decided` | `PASS`, `WARN`, `FAIL` | nobody — this is the answer |
| `waiting_on_you` | `LLM_PENDING` | the operator, by running the judgement |
| `waiting_on_you` | `NEEDS_INPUT` | whoever controls the named missing input, if anyone |
| `needs_a_person` | `MANUAL` | a person, by looking |
| `undecided` | `NO_DATA` | whoever maintains the tool or the service |
| `not_applicable` | `N/A` | nobody — out of scope |

The buckets are derived from statuses alone, never from prose in the evidence. The
`NEEDS_INPUT` row does not settle the inherited open question of whether the status
itself should name an actor.

**Why:** percentages name nobody. A partition that says who has to act is a work list;
one that reports coverage is a number to argue about. Deriving it from statuses is what
makes it checkable — reconstructing it by matching words in evidence broke silently the
first time a reason was reworded.
**Reader:** partial. `tests/test_runner.py` asserts the buckets sum to the number of
graded rows and pins the mapping for all eight statuses. Nothing asserts the sum against
the registry's real item count on a narrowed live run, and an id-set check would still
pass if a row appeared twice.

### SCR-8 — `waiting_on_you` keeps its halves visible

The bucket is one question — what is left at the audit boundary — and its two halves,
an unanswered model queue and a missing named input, are reported separately beneath
it.

**Why:** they share a bucket but require different next steps and may belong to different
actors.
**Reader:** partial. Tests pin the two stored subcounts, but no reader requires every
report surface to present both halves separately beneath the bucket.

### SCR-9 — category scores use the headline's arithmetic

Each category score uses the severity-weighted numerator and denominator of SCR-3 and
folds twins by SCR-1. It rounds by SCR-12 and is absent when that category has nothing
decided. Each score travels with an indication of how severe the worst unresolved
`FAIL` or `WARN` item in the category is.

**Why:** category scores sit beside the headline and are read against it. A second scale
or a second treatment of twins can point the reader at the wrong work, and a high score
alone can hide one unresolved critical item.
**Reader:** **none.** Nothing asserts on `by_category`; the current computation counts
twins that the headline folds.

### SCR-10 — the score says how much of it was measured

Every run reports how many decided items were `measured`, `claimed` by a person, or
answered by a `model`, and the report must show this breakdown whenever anything was not
measured.

**Why:** a score built on ticks is a different object from a score built on
measurements, and the difference must not require reading the item list to discover.
This is the second axis from VRD-2.1, surfaced.
**Reader:** partial. Claimed provenance and both renderers are tested, but model
disclosure is not; the `provenance_warnings` tests read different caveats.

### SCR-11 — fix priority is severity per unit of effort

Each fix has priority `severity weight ÷ effort cost`, highest first.

**Why:** ordering by severity alone puts expensive work above cheap work of nearly equal
value, and the list exists to be worked top-down.
**Reader:** partial. A test pins a cheap item above an equally severe expensive item,
but no reader pins the division or every effort cost. The sensitivity tool's order test
uses synthetic rows and does not establish equivalence on real artifacts.

### SCR-12 — all score-like fractions share one rounding and absence rule

The headline score, weight share and category scores are integers rounded to the nearest
integer, with exact halves rounded to the even integer. Whenever the denominator for
one of those values is zero, that value is absent, never zero.

**Why:** precision and the empty-set result are output semantics, not renderer choices.
Two conforming implementations must not turn the same fraction into different claims,
and zero must remain a verdict rather than a synonym for “nothing to divide by.”
**Reader:** partial. Tests pin several integer examples and `score()` returns an absent
headline for an empty decided set. No reader pins half-to-even behavior, and the current
weight share returns zero when applicable weight is zero.

### SCR-13 — the fix list has one membership and deterministic order

The fix list contains `FAIL`, `WARN` and `MANUAL` items. Twins are folded out so one
piece of work appears once. Rows are ordered by SCR-11 priority, then by severity weight,
then by item id; the first two keys descend and item id ascends. Registry order and the
order in which result rows arrive are not tie-breaks. Two runs over the same results
therefore produce the same fix order.

**Why:** an exported list and a rendered list that disagree are two work plans, and an
unstated tie-break makes changes in input order look like changes in priority.
**Reader:** partial. The machine export uses this membership and tie-break and tests
exercise parts of fix-list filtering and priority. The Markdown and HTML surfaces omit
`MANUAL` and fall back to registry order after priority and severity.

### SCR-14 — a change to any normative table must be detectable without reading the diff

All three tables in §2 must be under a gate that fails when a value changes without the
SCR-2 release declaration, and the failure must name the table and its old and new
value. The gate covers verdict credit as well as severity weight and effort cost.

**Why:** SCR-2 states the obligation and nothing enforces it. A requirement whose
violation is invisible is the failure mode this whole suite exists to prevent, and here
it sits on the number the client repeats and the order they act on.
**Reader:** **none.** This remedy is not implemented. It belongs to the release that
closes G1.

## 4. Invariants

* **INV-S1** — the five buckets sum to the number of registry items, each item in
  exactly one. *Reader: partial, as SCR-7.*
* **INV-S2** — `weight_decided ≤ weight_applicable`, and both exclude twins and `N/A`.
  *Reader: partial. Tests read the component rules but not the universal inequality.*
* **INV-S3** — the score is absent, never zero, when no item was decided. *Reader:
  partial, as SCR-3.*
* **INV-S4** — *Reader: partial.* A reversed-row test requires the scoring primary rather
  than the first row to survive twin folding; the multi-twin case is unread. Apart from
  the tie-break stated next, the score and the fix order depend
  on statuses, severities, efforts, the three tables and the twin relation, and on
  nothing else. Evidence text, category, run mode, profile and the order rows happen to
  arrive in may not affect them. Fix-order ties use severity weight and item id exactly
  as SCR-13 states. *Reader: none.*

## 5. What this document does not decide

* which statuses exist and which may carry weight — `specs/verdicts/`;
* which severity or effort a given item carries, and which items are twins — the
  registry contract;
* visual presentation. The scoring semantics required by SCR-3, SCR-4, SCR-8 and SCR-10
  remain owned here even while the reporting contract is absent;
* the storage or rendering mechanism for history comparison. SCR-2's scoring-identity,
  refusal and warning obligations remain owned here even while the history contract is
  absent;
* whether the inherited values in §2 are the *right* numbers. This document makes them
  normative and requires a gate; it does not defend them. Measuring them against real
  audits would be the work of a calibration, and none exists.

## 6. Open questions

**Is a table change a version bump?** SCR-2 requires it to be declared, but not what
that means mechanically — a registry version, a plugin version, or a stamp inside every
archived run. The archived runs are the constraint: they carry `registry_version`
already and would need a scoring identity too for a trend to be checkable. What would
settle it: deciding whether `.seo-runs/` comparability is a promise or a convenience.

**Do the twins' severities need to agree?** SCR-1 makes the primary's weight decide, so
a disagreement is currently harmless to the score — but MB-102 is `low` where MD-190 is
`medium`, and the two halves are shown to the reader with different urgency for one
question. What would settle it: whether a twin's severity is a claim about the question
or about the item.

**Should `worst_open` be renamed?** SCR-9 requires an indication of the worst unresolved
item's severity. The current field carries that severity, but its name sounds like a
status. Renaming it would change an output contract and must be decided with the
reporting and artifact consumers, not by this document alone.

**Does `waiting_on_you` still name the right actor?** The bucket was named when both its
statuses meant work for the operator who ran the audit. `NEEDS_INPUT` now means only that
a named input was absent — the input may be controlled by somebody else, or by nobody, as
when a fetch failed. The bucket then addresses a reader who cannot act. What would settle
it: the open question in `verdicts/` about whether `NEEDS_INPUT` should name an actor at
all. Until then this document keeps the name and the reader keeps the discrepancy.

**Does `MANUAL` belong in a remediation list?** SCR-13 takes the broader membership of the
machine-readable export, which includes items awaiting a person's judgement alongside
items known to be wrong. A list headed "fix these" containing "look at this" is a product
decision, not an arithmetic one. What would settle it: whether the export's audience is
somebody doing the work or somebody planning it.

## Appendix A — measured disagreements, 26 August 2026

Observation, not specification. Measured at commit `625faa4`, registry `b0abf2819da0`.

### A.1 — the table readers are narrow and the change obligations are unread

`SEVERITY_WEIGHT['medium'] = 3` is pinned indirectly by two tests that assert a concrete
total of 6 for sets of medium items; mutating it to 4 fails them. The priority-relation
test indirectly pins `EFFORT_COST['high']`; mutating it to 1 fails. Concrete single-row
tests exercise the verdict credits. No assertion pins the `critical`, `high` or `low`
severity weights, and none requires a release declaration, invalidates comparison, or
warns that a baseline used a different table.

`tools/audit_score_sensitivity.py` returns non-zero only when no supplied run has a
decided item. A maximal spread is not a failure, so the tool measures without gating.

### A.2 — the sensitivity witness does not reproduce the shipped arithmetic

The tool does not fold `scores_with` twins. On the three available 217-item artifacts,
its score and the audit's shipped folded score were respectively 55.3 and 56.7,
84.0 and 83.4, and 92.5 and 92.1. Its historical 0.2 / 1.9 / 9.3 / 14.6 outputs
therefore do not measure the current audit arithmetic, whose true table sensitivity is
unmeasured. The tests stay green because they use synthetic rows carrying no
`scores_with`.

### A.3 — scope narrowing removes or reclassifies rows today

The `--only` category selection filters the item list before planning, so excluded rows
never become `N/A`. On a real artifact the full run scored 57 over 217 rows while a
single-category slice scored 100 over 10.

The profile route also changes the arithmetic. Reclassifying one real run under the
shipped `local` exclusions moved its score from 57 to 58. In a two-row probe, changing a
`high FAIL` to `N/A` moved the score from 14 to 100.

### A.4 — reachable runs can render an absent score as a number

`score()` correctly returns an absent score when nothing was decided. Both report
renderers and the console branch on reachability instead of score presence, so a
reachable run with only a `NO_DATA` row prints `None/100`. The cited tests cover only the
unreachable subtype.

### A.5 — category arithmetic counts twins and its field name misleads

Category numerator and denominator iterate over all scored rows even though the
headline folds twins. A probe with a `critical PASS` primary in `security`, its
`critical PASS` twin in `technical`, and a `low FAIL` in `technical` produced a headline
weight of 11 and a technical category score of 91. Folding by SCR-1 leaves only the low
failure in that category, for a score of 0.

The current `worst_open` field carries a severity, not a status. The value is useful,
but the name does not say what it contains.

### A.6 — the two fix surfaces disagree

The machine fix export includes `FAIL`, `WARN` and `MANUAL`, and breaks ties by priority,
severity and item id. Markdown and HTML include only `FAIL` and `WARN`, and after
priority and severity fall back to registry order. Both fold twins, but they do not
produce the same membership or deterministic tie-break.

### A.7 — the code's own count of twins is wrong

A comment immediately after `score()`'s docstring states “Eight duplicate groups in
this registry carry ten `scores_with` twins.” Measured: **9 twins across 7 primaries** —
MD-190, SP-108 (×2), SE-114 (×2), CI-016, MB-096, GO-144, GO-145. Both numbers in the
comment are wrong, in opposite directions.

This is the same defect class as the registry's own `source` string and the operator
protocol's item counts: a claim about the tree, written beside the code it describes,
with nothing reading it.

### A.8 — SCR-14 is unimplemented

There is no change-control gate on any of the three tables. This is a disagreement, not
future work, because SCR-2 states obligations the tree does not meet today.

## Appendix B — how much of this document is enforced

| | requirements |
|---|---|
| **enforced** | — none |
| **partial** | SCR-1, SCR-2, SCR-3, SCR-5, SCR-6, SCR-7, SCR-8, SCR-10, SCR-11, SCR-12, SCR-13 |
| **none** | SCR-4, SCR-9, SCR-14 |

Invariants: all four partial — INV-S4 is read for the single-twin case by a reversed-row
test and unread for the rest.

**Nothing fully enforced, eleven partial, three unread, of fourteen.**

Two earlier drafts of this appendix were both wrong, in the same direction. The first
published four enforced, on readers assembled by reading the document. The second
published one, having dropped three. Neither survived an audit that ran the tests and
mutated the values they import: `SCR-1` is read for the headline and unread for the
category half its own sentence covers, and `SCR-4`'s two renderers print the share
without any assertion requiring them to. Rendering is the behaviour under audit, not a
reader of it — and a census assembled from the document rather than from the tests will
keep making that substitution.

The largest gap is not that a table value is unread. It is that the release,
comparability and warning obligations for changing the scoring instrument have no reader
at all, and that the gate which would detect an undeclared change does not exist —
`SCR-2` and `SCR-14`, which cannot be implemented until this suite decides what a scoring
identity is and where an archived run records it.
