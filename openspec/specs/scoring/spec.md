# Scoring — the headline number and what it is allowed to mean

## Purpose

How graded items become the one number a client repeats, and what that number is allowed
to mean. Three normative tables — severity weight, verdict credit, effort cost — plus the
partition of the registry that keeps the number honest about what it covers.

The tables are `inherited`: nobody in this project chose the values. That is why almost
every requirement here is about protecting a number somebody else picked, and why a
change to one of them is a release event rather than an edit.

**Capability:** how graded items become a score, a weight share, five buckets and a fix
order (C7, C8 of the capability inventory).

This document is normative and is written as though no code existed. Where the
implementation disagrees, the implementation is presumed wrong until this document is
changed by argument. Appendix A records disagreements measured on 26 August 2026.

Every requirement carries a **Reader** line naming what makes it fail when violated;
Appendix B is the census of those lines. A requirement whose reader is `none` is an
intention, and is counted as one.

**Inherited, not restated:** which statuses exist, and that only `PASS`, `WARN` and
`FAIL` may carry weight, belong to [`openspec/specs/verdicts/`](../verdicts/spec.md) (VRD-6,
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

The release and history obligations in SCR-2 were read by nothing until 0.94.0. SCR-14's
gate had closed the first half — a weight cannot move in the code alone, because §2 of
this document is parsed and held against it — and left the half about people open: a
change made in the code *and* here, together, was silent, and every archived score was
quietly re-based under an instrument nobody had declared.

0.94.0 closes it. The three tables are stamped as one instrument, `tests/scoring-tables.json`
declares which stamp is in force and which release put it there, every run artifact carries
the stamp that scored it, and a comparison whose baseline was scored under another stamp
warns rather than presenting the difference as movement in the site. The stamp is computed
from §2 above rather than from the constants, so this document remains the normative text
and the declaration cannot drift from it in silence.

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

All three are **normative constants of the audit**, not implementation details. The
provenance of severity weight and effort cost is `inherited`: nobody in this project chose
those numbers. Verdict credit is `convention` — a pass earns its weight and a fail earns
none, and WARN at half credit is what makes it a verdict rather than a soft FAIL.

Together they are one **instrument**, named by a stamp: the twelve hex digits
`scoring_stamp_of()` computes from these three tables with every value read as a float, so
the stamp names the numbers and not their spelling. It is `a429e10f43d8` as this document
stands. SCR-2 says what follows from a change to it.

---

## Requirements

### Requirement: SCR-1 — weight is carried per check, never per item

Where several registry items ask one question of one script with one assertion,
exactly one of them SHALL carry the weight. The others report their own status and contribute
nothing to either half of the score or to a category score.

**Why:** otherwise one defect pulls the headline twice, and where the twins disagree on
severity the weight of a single defect depends on which item a reader happens to look
at. Both conditions exist in the registry today: 9 twins across 7 primaries, of which
MB-102/MD-190 and SP-112/SP-108 disagree on severity.
**Reader:** enforced. The headline half is read by
`tests/test_runner.py::Scoring::test_a_twin_reports_its_status_and_does_not_score_twice`,
and `tools/audit_item_semantics.py` in CI refuses any two items sharing script,
arguments and assertion without a recorded ruling. The category half is read by
`tests/test_runner.py::TheCategoryBarIsTheHeadlinesArithmetic`, whose
`test_the_twin_is_weighed_in_the_carriers_category_and_nowhere_else` fails on the
computation this tree shipped until 0.92.0 — six of the nine pairs cross categories, so
the fold moves weight between bars rather than only within one.

#### Scenario: one defect, two registry obligations
- **WHEN** two items resolve to the same script, arguments and assertion
- **THEN** one carries the weight and the other reports its status and contributes
  nothing to either half of the score

#### Scenario: the twins disagree on severity
- **WHEN** the two items are recorded at different severities
- **THEN** the weight is the ruled survivor's, not whichever item a reader looked at
  first

#### Scenario: a category score is asked for
- **WHEN** the same fold is applied to a category rather than to the headline
- **THEN** twins are folded there too
- **AND** the fold applies to that bar's numerator and denominator, not only to the
  headline's

### Requirement: SCR-2 — all three tables are normative, and changing one is a release event

The values in §2 are part of the audit's contract, and a change to any of them SHALL
be treated as a change of instrument:

* must be stated in the release that does it, in those words;
* invalidates comparison with every archived run scored or ordered under the previous
  table;
* requires the run comparison to refuse, or to warn in the report, when the baseline
  used a different table.

**Why:** the score is quoted to clients and compared across months. A table change is a
change of instrument, not of the site, and a trend line spanning one is a lie about the
site.
**Reader:** enforced. `tests/test_scoring_tables.py` holds all three clauses.
`TheDeclaration` reads the release clause: the instrument is stamped, `tests/scoring-tables.json`
declares the stamp in force and the release that set it, and that release's CHANGELOG entry
must carry the marker and the stamp — so a table edit cannot reach `main` without the
release saying so in those words. `AComparisonAcrossTheChange` reads the warning clause
through `diff_runs`, in both directions: a baseline under another stamp is reported as a
change of instrument, and a baseline archived before the stamp existed is reported as
*not establishable* rather than as a change nobody made.
`TheArtifactRecordsTheInstrument` runs a live audit and reads the stamp back out of the
artifact and out of the last point of its own history arc, because a stamp that is not
archived cannot be compared against next month. The values themselves are held against §2
by SCR-14.

#### Scenario: a weight is edited
- **WHEN** any value in any of the three tables changes
- **THEN** the release that does it says so in those words

#### Scenario: a trend spans the change
- **WHEN** a run is compared against an archived run scored under the previous table
- **THEN** the comparison refuses, or the report warns
- **AND** it does not present the difference as movement in the site

#### Scenario: the change is made quietly
- **WHEN** a table value is edited with no declaration and no warning
- **THEN** every score before and after is compared as though it meant the same thing,
  which is the harm this requirement exists to prevent

### Requirement: SCR-3 — the score is a weighted fraction of what was decided

`seo_score` SHALL be 100 × Σ(weight × credit) ÷ Σ(weight), over decided items
excluding twins. When nothing was decided, the score MUST be **absent**, not zero.

**Why:** zero is a verdict about a site; absence is a statement about the audit. A site
that could not be read must not be reported as scoring zero.
**Reader:** partial. Unit tests pin `score()`'s arithmetic and its absent value, and the
unreachable-site CI step asserts that no score line is printed for an unreachable run.
No reader covers a reachable run with nothing decided; both renderers and the console
currently print `None/100` for that case.

#### Scenario: a site with a mix of verdicts
- **WHEN** items are decided `PASS`, `WARN` and `FAIL`
- **THEN** each contributes its severity weight times its verdict credit, over the sum
  of the weights of the decided items

#### Scenario: a site that could not be read
- **WHEN** nothing was decided
- **THEN** the score is absent
- **AND** it is not zero, which would be a verdict about the site rather than a
  statement about the audit

#### Scenario: a reachable site with nothing decided
- **WHEN** the site answered but no item reached a quality verdict
- **THEN** the score is still absent, and no surface renders it as a number

### Requirement: SCR-4 — the score may never appear without its weight share

`weight_pct` — the weight the score was computed over, as a percentage of the weight of
all applicable items — SHALL travel with the score on every surface: console, report,
artifact, and any sentence an operator or agent writes.

**Why:** 69 over 55% of the registry's weight and 69 over 95% are different claims, and
the number alone does not say which one is being made. A score without its share is a
fraction with the denominator torn off.
**Reader:** enforced. `test_every_surface_reacts_to_the_share` renders markdown, HTML and
the runner's console summary twice with a different `weight_pct` and requires each output
to change; `test_every_surface_reacts_to_the_score` does the same for the score, so a
surface that showed neither could not satisfy the first vacuously; and
`test_the_artifact_carries_both` covers the fourth surface. Probed on 5 September 2026 by
taking the share out of each of the three renderers in turn: each reddens its own surface
and only its own.

The method answers the question `openspec/specs/reporting/` §6 asked — whether the console can be
held without pinning terminal output that changes for good reasons. Nothing here looks at
*where* the number goes. A surface that stops printing the share stops reacting to it; one
that moves it, renames it or translates it is untouched.

Until 5 September 2026 this read `none`, and correctly: both renderers printed the two
together, which is the behaviour under audit rather than a reader of it.

#### Scenario: the number appears anywhere
- **WHEN** the score is shown on the console, in the report, in the artifact, or quoted
  in a sentence
- **THEN** the share of the weight it was computed over is shown with it

#### Scenario: the same number over two different reaches
- **WHEN** one run scores 69 over 55% of the weight and another 69 over 95%
- **THEN** the two are different claims, and a reader can tell them apart

#### Scenario: a surface stops reading the share
- **WHEN** a renderer prints a fixed value, or derives the share from something other
  than the run
- **THEN** the requirement is violated even though a percentage still appears

### Requirement: SCR-5 — `N/A` leaves both numerator and denominator

An item that does not apply — to this site, this mode, or this profile — SHALL be
absent from the score and from `weight_applicable`.

**Why:** otherwise narrowing scope would make an audit look thinner rather than
narrower, and the incentive would run the wrong way. This is VRD-7 applied to the number
that replaced coverage.
**Reader:** partial. Unit tests pin `N/A` out of the score and compare reach with and
without `N/A`, but no assertion directly pins the returned `weight_applicable` value.

#### Scenario: an item that does not apply
- **WHEN** an item is `N/A`
- **THEN** it is in neither the numerator nor the denominator

#### Scenario: narrowing does not look like thinning
- **WHEN** a profile or a mode takes items out of scope
- **THEN** the weight share does not fall on that account, because the excluded items
  left the denominator too

### Requirement: SCR-6 — narrowing scope remains a registry partition

Any mechanism that takes an item out of a run — category selection, profile
exclusion, mode capability or applicability — MUST leave the item in the registry and
classify it as `N/A`. Removing rows from the run's item list is forbidden: the five-bucket partition
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

#### Scenario: one category is selected
- **WHEN** a run is narrowed to a single category
- **THEN** every other item appears as `N/A`
- **AND** the five buckets still sum to the whole registry, not to the selected rows

#### Scenario: rows are dropped instead
- **WHEN** a narrowing mechanism removes items from the run's list
- **THEN** the partition sums to the selection, the share is computed over a slice, and
  the score of that slice is reported as the score of the site

### Requirement: SCR-7 — the partition names whose action moves each item

Every item SHALL land in exactly one of five buckets, and the buckets MUST sum to the
registry:

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

#### Scenario: the buckets add up
- **WHEN** the partition is computed for any run
- **THEN** the five bucket counts sum to the registry's item count

#### Scenario: a status appears in two buckets
- **WHEN** any status is counted under more than one bucket
- **THEN** the partition is wrong, whatever the totals happen to say

### Requirement: SCR-8 — `waiting_on_you` keeps its halves visible

The bucket is one question — what is left at the audit boundary — and its two halves,
an unanswered model queue and a missing named input, SHALL be reported separately
beneath it.

**Why:** they share a bucket but require different next steps and may belong to different
actors.
**Reader:** partial. Tests pin the two stored subcounts, but no reader requires every
report surface to present both halves separately beneath the bucket.

#### Scenario: work waiting on two different people
- **WHEN** a run has both `LLM_PENDING` items and `NEEDS_INPUT` items
- **THEN** the bucket total is shown, and the two halves are shown beneath it
- **AND** a reader can tell a judgement nobody has made from a file nobody supplied

### Requirement: SCR-9 — category scores use the headline's arithmetic

Each category score SHALL use the severity-weighted numerator and denominator of
SCR-3 and MUST fold twins by SCR-1. It rounds by SCR-12 and MUST be absent whenever that
category has no weight of its own to divide by — because nothing in it was decided, or
because everything decided in it defers its weight to a carrier elsewhere. Each score
travels with an indication of how severe the worst unresolved `FAIL` or `WARN` item in
the category is, folded or not.

**Why:** category scores sit beside the headline and are read against it. A second scale
or a second treatment of twins can point the reader at the wrong work, and a high score
alone can hide one unresolved critical item.
**Reader:** enforced. `tests/test_runner.py::TheCategoryBarIsTheHeadlinesArithmetic`
holds it. `test_every_bar_is_the_headline_over_the_rows_that_bar_speaks_for` is the
sentence itself: each bar is compared against `score()`'s own headline, run over the
rows that bar speaks for, so the fraction, the fold and the rounding cannot part company
between the two computations without the failure naming the category it happened in.
Each scenario has a case of its own besides.

#### Scenario: a category containing a twin pair
- **WHEN** a category holds two items that share one measurement
- **THEN** the shared measurement is weighed once, exactly as in the headline

#### Scenario: a category with nothing decided
- **WHEN** no item in a category reached a quality verdict
- **THEN** the category score is absent rather than zero

#### Scenario: a category whose decided items all defer their weight
- **WHEN** every decided item in a category is a twin whose carrier sits in another
  category
- **THEN** the category score is absent, because the fold left it nothing to divide by
- **AND** it is not zero, which would read as a verdict on that category rather than on
  the one holding the weight

#### Scenario: the bar hides a critical failure
- **WHEN** a category scores well but holds an unresolved `FAIL` at a high severity
- **THEN** the severity of the worst unresolved item travels with the score

### Requirement: SCR-10 — the score says how much of it was measured

Every run SHALL report how many decided items were `measured`, `claimed` by a person,
or answered by a `model`, and the report MUST show this breakdown whenever anything was
not measured.

**Why:** a score built on ticks is a different object from a score built on
measurements, and the difference must not require reading the item list to discover.
This is the second axis from VRD-2.1, surfaced.
**Reader:** partial. Claimed provenance and both renderers are tested, but model
disclosure is not; the `provenance_warnings` tests read different caveats.

#### Scenario: a score built partly on judgement
- **WHEN** any decided item was claimed by a person or answered by a model
- **THEN** the breakdown is shown, so the number is not read as wholly measured

#### Scenario: a wholly measured run
- **WHEN** every decided item was measured
- **THEN** the breakdown may be omitted, because there is nothing to distinguish

### Requirement: SCR-11 — fix priority is severity per unit of effort

Each fix SHALL have priority `severity weight ÷ effort cost`, highest first.

**Why:** ordering by severity alone puts expensive work above cheap work of nearly equal
value, and the list exists to be worked top-down.
**Reader:** partial. A test pins a cheap item above an equally severe expensive item,
but no reader pins the division or every effort cost. The sensitivity tool's order test
uses synthetic rows and does not establish equivalence on real artifacts.

#### Scenario: cheap work of nearly equal value
- **WHEN** two items share a severity and differ in effort
- **THEN** the cheaper one is ordered first

#### Scenario: a critical item is never buried
- **WHEN** a critical item is expensive and a low item is cheap
- **THEN** the critical item is not ordered below the low one

### Requirement: SCR-12 — all score-like fractions share one rounding and absence rule

The headline score, weight share and category scores SHALL be integers rounded to the
nearest integer, with exact halves rounded to the even integer. Whenever the denominator for
one of those values is zero, that value is absent, never zero.

**Why:** precision and the empty-set result are output semantics, not renderer choices.
Two conforming implementations must not turn the same fraction into different claims,
and zero must remain a verdict rather than a synonym for “nothing to divide by.”
**Reader:** partial. Tests pin several integer examples and `score()` returns an absent
headline for an empty decided set. No reader pins half-to-even behavior, and the current
weight share returns zero when applicable weight is zero.

#### Scenario: an exact half
- **WHEN** a score-like fraction lands exactly on .5
- **THEN** it rounds to the even integer, the same way on every surface

#### Scenario: an empty denominator
- **WHEN** the denominator of any score-like value is zero
- **THEN** that value is absent, never zero

### Requirement: SCR-13 — the fix list has one membership and deterministic order

The fix list SHALL contain `FAIL`, `WARN` and `MANUAL` items, and no others. Twins are folded out so one
piece of work appears once. Rows are ordered by SCR-11 priority, then by severity weight,
then by item id; the first two keys descend and item id ascends. Registry order and the
order in which result rows arrive are not tie-breaks. Two runs over the same results
therefore produce the same fix order.

**Why:** an exported list and a rendered list that disagree are two work plans, and an
unstated tie-break makes changes in input order look like changes in priority.
**Reader:** partial. The machine export uses this membership and tie-break and tests
exercise parts of fix-list filtering and priority. The Markdown and HTML surfaces omit
`MANUAL` and fall back to registry order after priority and severity.

#### Scenario: the same results ordered twice
- **WHEN** two runs are given the same result rows in a different arrival order
- **THEN** the fix list is identical, because registry order and arrival order are not
  tie-breaks

#### Scenario: two items of equal priority
- **WHEN** two rows share a priority
- **THEN** severity weight decides, and then item id ascending

#### Scenario: one piece of work listed twice
- **WHEN** a twin pair both qualify for the list
- **THEN** it appears once

### Requirement: SCR-14 — a change to any normative table must be detectable without reading the diff

All three tables in §2 MUST be under a gate that fails when a value changes without
the SCR-2 release declaration, and the failure MUST name the table and its old and new
value. The gate covers verdict credit as well as severity weight and effort cost.

**Why:** SCR-2 states the obligation and nothing enforces it. A requirement whose
violation is invisible is the failure mode this whole suite exists to prevent, and here
it sits on the number the client repeats and the order they act on.
**Reader:** partial. The three tables are
pinned by `TheNormativeTablesAreReadFromTheDocument`, which parses §2 out of this document
rather than transcribing it, so the only green path is changing the code and the document
together — and that is the moment a reviewer has to notice a release declaration is owed.
Probed in all four directions on 6 September 2026: editing `SEVERITY_WEIGHT`, the verdict
credit, or `EFFORT_COST` each reddens, and so does editing the table in §2 while the code
stands still. Verdict credit is read behaviourally through the headline and through a
category bar — it was inline literals in two sums until 0.94.0 and is `VERDICT_CREDIT`
now, and reading the arithmetic rather than the name survives either spelling. 
`test_the_item_counts_beside_each_table_still_describe_the_registry` holds the counts
printed beside the tables against the registry itself.

What SCR-14 asked for and still does not have is the naming: the gate reddens on a changed
value but does not print the table with its old and new value beside each other, so a
reviewer is stopped and then has to go and find out what moved. The obligation this
requirement pointed at — that the reviewer be told a release declaration is owed — is
held since 0.94.0 by `tests/test_scoring_tables.py`, whose failure message names the
remedy; what is left here is the wording of the report, not the gate.

#### Scenario: a table value moves
- **WHEN** any of the three tables is edited
- **THEN** a gate fails, naming the table, the old value and the new one
- **AND** the failure is what tells a reviewer a release declaration is owed, instead of
  the change resting on somebody noticing a diff

#### Scenario: verdict credit is edited
- **WHEN** the credit for `WARN` changes
- **THEN** the gate fails too, whether the credit is a named table or the inline literals
  it was written as until 0.94.0

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

* which statuses exist and which may carry weight — `openspec/specs/verdicts/`;
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

#### A.1 — the table readers are narrow and the change obligations are unread

`SEVERITY_WEIGHT['medium'] = 3` is pinned indirectly by two tests that assert a concrete
total of 6 for sets of medium items; mutating it to 4 fails them. The priority-relation
test indirectly pins `EFFORT_COST['high']`; mutating it to 1 fails. Concrete single-row
tests exercise the verdict credits. No assertion pins the `critical`, `high` or `low`
severity weights, and none requires a release declaration, invalidates comparison, or
warns that a baseline used a different table.

`tools/audit_score_sensitivity.py` returns non-zero only when no supplied run has a
decided item. A maximal spread is not a failure, so the tool measures without gating.

#### A.2 — the sensitivity witness does not reproduce the shipped arithmetic

The tool does not fold `scores_with` twins. On the three available 217-item artifacts,
its score and the audit's shipped folded score were respectively 55.3 and 56.7,
84.0 and 83.4, and 92.5 and 92.1. Its historical 0.2 / 1.9 / 9.3 / 14.6 outputs
therefore do not measure the current audit arithmetic, whose true table sensitivity is
unmeasured. The tests stay green because they use synthetic rows carrying no
`scores_with`.

#### A.3 — scope narrowing removes or reclassifies rows today

The `--only` category selection filters the item list before planning, so excluded rows
never become `N/A`. On a real artifact the full run scored 57 over 217 rows while a
single-category slice scored 100 over 10.

The profile route also changes the arithmetic. Reclassifying one real run under the
shipped `local` exclusions moved its score from 57 to 58. In a two-row probe, changing a
`high FAIL` to `N/A` moved the score from 14 to 100.

#### A.4 — reachable runs can render an absent score as a number

`score()` correctly returns an absent score when nothing was decided. Both report
renderers and the console branch on reachability instead of score presence, so a
reachable run with only a `NO_DATA` row prints `None/100`. The cited tests cover only the
unreachable subtype.

#### A.5 — the field that carries the worst unresolved severity is named for a status

`worst_open` carries a severity — `critical`, `high`, `medium`, `low` — and its name
reads as though it carried a status. The value is the one SCR-9 asks for; only the name
is wrong, and renaming it changes an output contract, so it is an open question above
rather than a defect to fix here.

The arithmetic half of this entry is closed. Category numerator and denominator
iterated every scored row while the headline folded twins: a probe with a
`critical PASS` primary in `security`, its `critical PASS` twin in `technical`, and a
`low FAIL` in `technical` gave a headline weight of 11 and a technical bar of 91 where
the fold leaves 0. Fixed in 0.92.0 and read by
`tests/test_runner.py::TheCategoryBarIsTheHeadlinesArithmetic`.

#### A.6 — the two fix surfaces disagree

The machine fix export includes `FAIL`, `WARN` and `MANUAL`, and breaks ties by priority,
severity and item id. Markdown and HTML include only `FAIL` and `WARN`, and after
priority and severity fall back to registry order. Both fold twins, but they do not
produce the same membership or deterministic tie-break.

#### A.7 — the code's own count of twins is wrong

A comment immediately after `score()`'s docstring states “Eight duplicate groups in
this registry carry ten `scores_with` twins.” Measured: **9 twins across 7 primaries** —
MD-190, SP-108 (×2), SE-114 (×2), CI-016, MB-096, GO-144, GO-145. Both numbers in the
comment are wrong, in opposite directions.

This is the same defect class as the registry's own `source` string and the operator
protocol's item counts: a claim about the tree, written beside the code it describes,
with nothing reading it.

#### A.8 — SCR-14 is unimplemented

There is no change-control gate on any of the three tables. This is a disagreement, not
future work, because SCR-2 states obligations the tree does not meet today.

**Closed in two steps.** 0.93.x built the gate: `TheNormativeTablesAreReadFromTheDocument`
parses §2 and holds the code against it, so a value cannot move in the code alone. 0.94.0
closed what that left — the obligations about people. Probed on 6 September 2026 by editing
`SEVERITY_WEIGHT['critical']` from 10 to 27 in the code and in §2 together, which is the
edit the 0.93.x gate cannot see: before 0.94.0 the whole suite stayed green, after it three
assertions in `tests/test_scoring_tables.py` fail — the stamp in the tree is not the
declared one, the declared release does not exist, and it does not state the change.

A.1 is closed by the same two steps and is left as measured, for the same reason this
appendix carries a date: it is what was true on 26 August 2026, and rewriting it would
lose the record of how narrow the readers had been.

## Appendix B — how much of this document is enforced

| | requirements |
|---|---|
| **enforced** | SCR-1, SCR-2, SCR-4, SCR-9 |
| **partial** | SCR-3, SCR-5, SCR-6, SCR-7, SCR-8, SCR-10, SCR-11, SCR-12, SCR-13, SCR-14 |
| **none** | — none |

Invariants: all four partial — INV-S4 is read for the single-twin case by a reversed-row
test and unread for the rest.

**Four enforced, ten partial, none unread, of fourteen.**

SCR-2 moved on 6 September 2026, and it is worth saying which part of it had been missing,
because the appendix had twice been wrong in the same direction before. SCR-14's gate was
already refusing a value change made in the code alone; what nothing read was the sentence
about people — that a change is declared in the release that makes it, and that a score
compared across one is not movement in the site. The three clauses now have a reader each,
and the probe is recorded in A.8: editing `SEVERITY_WEIGHT['critical']` from 10 to
27 in code and document together left every test in this tree green before 0.94.0 and
reddens three after it.

Two earlier drafts of this appendix were both wrong, in the same direction. The first
published four enforced, on readers assembled by reading the document. The second
published one, having dropped three. Neither survived an audit that ran the tests and
mutated the values they import: `SCR-1` was read for the headline and unread for the
category half its own sentence covers, and `SCR-4`'s two renderers printed the share
without any assertion requiring them to. Rendering is the behaviour under audit, not a
reader of it — and a census assembled from the document rather than from the tests will
keep making that substitution.

**Two of the three enforced rows are that finding, closed rather than restated.**
SCR-9 and the category half of SCR-1 were one defect: the bars weighed twins the
headline folds, and no test read `by_category` at all. Both closed on 6 September 2026
by one class, and the fix moved live numbers — six of the nine pairs cross categories,
so weight left one bar for another rather than only shrinking.

SCR-4 got its reader on 5 September 2026, and the thing that had made it look untestable — that holding
a console surface means pinning terminal output — turned out to be avoidable: render
twice with a different share and require the output to change, and the assertion never
learns where the number is. Nothing about that method is specific to this requirement, and
it is the obvious tool for the display half of the nine `partial` rows whose computation is
read and whose rendering is not.

The largest gap is not that a table value is unread. It is that the release,
comparability and warning obligations for changing the scoring instrument have no reader
at all, and that the gate which would detect an undeclared change does not exist —
`SCR-2` and `SCR-14`, which cannot be implemented until this suite decides what a scoring
identity is and where an archived run records it.
