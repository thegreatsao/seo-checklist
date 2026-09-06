# Verdicts — the vocabulary every layer shares

## Purpose

What an audit is allowed to say about one checklist item, and when — the eight statuses
every other layer inherits, and the rules that keep them from collapsing into each other.

This is the first document in the suite because every other one consumes it. A registry
rule, a run's refusal, a report's row and a stored comparison are each a single word
about a single item, and if two layers spell that word differently or mean different
things by it, no gate can compare them and every comparison silently passes.

**Capability:** what an audit is allowed to say about one checklist item, and when.

This document is normative and is written as though no code existed. Where the
implementation disagrees, the implementation is presumed wrong until this document is
changed by argument. Appendix A records the disagreements measured on 25 August 2026;
it is an observation about the tree, not part of the specification.

Every requirement carries a **Reader** line naming what makes it fail when violated, and
Appendix B is the census of those lines. A requirement whose reader is `none` is not a
specification yet — it is an intention, and it is listed as one rather than quietly
counted as enforced.

---

## 1. Why a shared vocabulary is the first document

An audit's output is a set of claims about a site. Each claim is one word. If two layers
spell that word differently, or mean different things by it, no gate can compare them
and every comparison silently passes.

This is not hypothetical here. The manifest of expected verdicts uses a word the audit
never emits, so none of those declarations was compared with anything at any point from
`v0.41.0`, the first release carrying the oracle, through `v0.91.0`: fifty-five
releases over about thirteen days and sixteen hours. How many declarations that is, what
they say and what the audit answers instead are
[`openspec/specs/declarations/`](../declarations/spec.md) A.1; the window and how it grew are
Appendix A.2 below.

The vocabulary is therefore specified before the registry, before the runner and before
the oracle, because all three are consumers of it.

## 2. The vocabulary

Exactly eight statuses exist. The list is closed: VRD-12 and INV-2 forbid any layer from
adding a ninth for its own use.

| status | means | who can change the outcome |
|---|---|---|
| `PASS` | the item's rule is satisfied | nobody — this is the good case |
| `WARN` | the rule is not satisfied, and the deviation is below the failure threshold | the site owner |
| `FAIL` | the rule is violated | the site owner |
| `N/A` | the item has no subject on this site, or is out of scope for the run's mode | nobody — the item is not about this site |
| `NO_DATA` | the audit tried to decide and could not | whoever maintains the tool or the service it called |
| `NEEDS_INPUT` | a named input required by the check was not present | whoever controls that input, if anyone |
| `MANUAL` | the question is answerable, but only by a person | the operator, by looking |
| `LLM_PENDING` | the question is for a language model, and no judgement has been made yet | the operator, by running the judgement |

Three of these — `PASS`, `WARN`, `FAIL` — are *verdicts about quality*. The other five
each say something different about **why there is no verdict**, and the value of having
five is that they preserve the cause needed to route the work. A status does not always
name the actor by itself; the unresolved `NEEDS_INPUT` case is recorded in §6. Collapsing
the five causes is the failure this vocabulary exists to prevent.

### 2.1 Status and provenance are separate axes

A quality verdict says *what is true of the site*. It does not say *how that was
established*. Three provenances exist: **measured** by a checker, **claimed** by a
person answering a `MANUAL` item, **model** for a language-model judgement.

The two axes must not be folded together. A definition of `PASS` that requires
measurement would forbid a person from ever answering a `MANUAL` item — which is the
whole purpose of that status — and the tree already ships the alternative: a claimed
verdict is stamped `claimed` and the report is forbidden from presenting it as a
measurement. Provenance travels with the verdict; it does not change which word is used.

## Requirements

### Requirement: VRD-1 — one status per item per run

Every registry item SHALL receive exactly one status in every audit. No item may be
absent from a report, and no item may carry two.

**Why:** a report that omits items cannot be compared with another report, and a
denominator that varies between runs means nothing.
**Reader:** partial. `tests/test_contract.py` compares each fixture run's id set against
all 217 registry ids, which catches omission; set equality would still accept a
duplicate row, so "exactly once" is not fully read.

#### Scenario: every item is answered
- **WHEN** an audit finishes, whatever its mode, profile or reach
- **THEN** the report carries a row for every id in the registry

#### Scenario: an item is answered twice
- **WHEN** two rows in one report carry the same item id
- **THEN** the run is wrong, whether or not the two rows agree
- **AND** comparing id *sets* between report and registry cannot see this, which is why
  the requirement says "exactly one" and not "at least one"

### Requirement: VRD-2 — a quality verdict requires a subject and a basis

`PASS`, `WARN` and `FAIL` may be assigned only when the entity whose quality the item
judges exists on this site (VRD-3) and the verdict rests on a stated basis — a
measurement, a person's claim, or a model's judgement, recorded as provenance per §2.1.
That entity is the **subject**. A required feature or a defect that an item forbids is
never the subject: its presence or absence may be the measured fact that decides a rule
about an existing page or site.

An item whose subject does not exist **MUST NOT** report `PASS`.

**Why:** `PASS` carries weight in the score, and an item that passes for lack of a
subject awards credit the site never earned — a five-page bakery scoring for *Optimize
E-commerce Category Pages* it does not have. It also reads to the operator as
confirmation that something was checked.
**Reader:** partial. `tests/test_runner.py` requires an item whose applicability subject
is absent to be `N/A` rather than `PASS`, but only through the `applies_when` mechanism,
which most items do not declare — see VRD-3 and Appendix A.1.

#### Scenario: the thing being judged is not on the site
- **WHEN** an item judges the quality of an entity the site may legitimately not have,
  and the site does not have it
- **THEN** the item reports `N/A`
- **AND** it does not report `PASS`, which would award score for a subject that never
  existed

#### Scenario: a rule counts defects and finds none because there is nothing to count
- **WHEN** the rule passes by counting zero violations over an absent subject
- **THEN** that is the same absence, and still not a `PASS`

#### Scenario: the absent thing is the defect rather than the subject
- **WHEN** an item forbids something and the site does not do it
- **THEN** `PASS` is correct: the subject is the page or the site, which exists, and the
  absent thing is the measured fact

### Requirement: VRD-3 — missing data, a missing subject, and an absent defect are distinct

Absence SHALL be resolved by three mechanisms, in this order, and they MUST NOT be
collapsed into one:

* **The data field is missing.** The audit is undecided unless the item declares
  `missing_is: pass | fail`. A parser that never emits a key says nothing about whether
  the site is clean. `missing_is` is the narrow override for cases where absence of the
  field is itself the answer; CI-004 and MS-031 use it.
* **The subject entity is absent.** When the entity whose quality the item judges may
  legitimately not exist, the result is `N/A`, with evidence naming what was sought and
  not found. The item must declare that boundary with an applicability condition. A
  present count of zero can establish this case: MB-102 and MD-190 use `applies_when` to
  say that a page with zero videos has no video subject.
* **The field and subject exist.** The assertion's own shape decides the result, with no
  additional declaration. `eq` and `len_eq` are classified by their operand: against zero
  they forbid, against anything else they require. So `eq: 0`, `len_eq: 0`, `lte`, `lt`,
  `len_lte`, `count_matching_lte`, `none_matching`, `none_severity` and `falsy` forbid
  something, and finding none of it satisfies them; `truthy`, `gte`, `len_gte`, `eq: 200`,
  `len_eq: 1` and their kind require presence, so an empty value violates them. An item
  that forbids a defect and finds none passes correctly; the absent defect is not the
  item's subject.

  `len_eq: 0` is the commonest absence-passing spelling in this registry — nine items use
  it, more than `none_matching` and `count_matching_lte` together — so a classification
  omitting it misreads the registry rather than a corner of it. The threshold forms carry
  a further caveat: `lte: 0.1` and `lte: 2500` forbid *exceeding* a bound in different
  domains, and what counts as the absent thing differs with the domain. This
  classification settles what absence means, never where the bound belongs.

Only the second case requires an applicability declaration. The requirement is narrow:
not every item must declare anything, only an item judging the quality of an entity that
may legitimately not exist.

**Seventeen items owe such a declaration, and two declare one.** A sweep of every item
whose assertion is absence-passing and which declares no applicability found 73
candidates; classifying each against what its checker emits when the population is empty
gives 55 legitimate prohibitions, 17 declaration debts, and one that cannot be classified
at all:

> CI-016, CN-034, CN-035, CN-054, MS-032, BL-081, MB-098, MB-103, MB-108, AR-146,
> AR-154, AR-163, GO-143, TE-172, TE-174, MD-185, MD-186.

The unclassifiable one is CN-036 *Ensure Sufficient Text Contrast*, whose assertion
counts elements carrying inline colour syntax rather than contrast violations, and which
therefore cannot say whether zero means no violation or no text. An applicability
declaration alone would not repair it: the field measures something other than what the
item claims to judge, which is a registry defect of the same kind as GO-137.

Two caveats on that census, both of which narrow it. A checker may already withhold its
verdict field when the population is empty — `image_inventory.py` does this, so CI-016
and MD-186 currently report `NO_DATA` rather than a false `PASS`. The debt stands,
because this requirement calls for `N/A` and `NO_DATA` says something different, but the
harm is smaller than a wrong pass. And the sweep is an over-approximation by
construction: an upper-bound operator does not prove the checker emits a zero-like value
when its subject is absent.

The existing mechanism lives at `item["check"]["applies_when"]`, so it cannot serve a
sourceless item such as LO-199. That schema gap, the classification of all 17, and
CN-036's measurement defect belong to the registry document and are not solved here.

**Why:** a missing field describes the parser, an absent subject limits the item's scope,
and an absent forbidden condition may satisfy the item. Treating those as one kind of
absence either invents clean measurements or awards quality credit for entities the site
does not have.

**A measurement, not a guess about site type.** `N/A` under this requirement is licensed
by evidence from this run — the sampled pages contain no such entity — never by an
inference about what kind of business the site appears to be. Inferring the site's
category is governed separately by VRD-11.
**Reader:** partial. The `applies_when` mechanism is enforced where present — a failed
rule yields `N/A` with a reason and a matching one grades normally — but only two items
of 217, MB-102 and MD-190, declare it, at `item["check"]["applies_when"]`. That location
cannot express applicability for a sourceless item such as LO-199. Neither declaration
completeness nor that sourceless gap has a reader; both belong to the registry document.

#### Scenario: the checker never wrote the field
- **WHEN** an item's assertion reads a key the checker did not emit
- **THEN** the item is undecided, unless it declares `missing_is`
- **AND** silence from a parser is not evidence that the site is clean

#### Scenario: the field is absent and its absence is the answer
- **WHEN** the item declares `missing_is: pass` or `missing_is: fail`
- **THEN** the declared verdict is taken, because the item said in advance what an
  absent field means

#### Scenario: the subject may legitimately not exist
- **WHEN** the entity whose quality the item judges is absent, and the item declares the
  applicability condition that says so
- **THEN** the item reports `N/A`, with evidence naming what was sought

#### Scenario: absence inferred from the kind of business
- **WHEN** `N/A` would rest on what kind of site this appears to be rather than on what
  the sampled pages contain
- **THEN** the requirement is violated; that inference is VRD-11's, and needs consent

### Requirement: VRD-4 — a missing input is never `N/A` and never a quality verdict

When a named input a check requires was not present, the status SHALL be
`NEEDS_INPUT`, whatever the reason. The evidence names a supply route only when one exists. Where no
route exists — for example, for a fetched page or crawl inventory — the evidence names
the cause instead and must not instruct the operator to produce something they cannot.

**Why:** `N/A` removes the item from the applicable set, so reporting a missing input as
`N/A` improves the audit's apparent reach exactly where it is thinnest. A quality
verdict is worse: it claims a decision that never happened.
**Reader:** enforced. Planner tests pin absent and refused artefacts, missing HTML,
missing Search Console credentials and a missing Safe Browsing key to `NEEDS_INPUT`;
they also pin a supply route where one exists and cause-only evidence where none does.

#### Scenario: an input the operator can supply is missing
- **WHEN** a check needs a file or a credential that was not given
- **THEN** the item reports `NEEDS_INPUT`, and the evidence names the flag or variable
  that would supply it

#### Scenario: an input nobody can supply is missing
- **WHEN** the absent input is something the run itself produces, such as a fetched page
  or a crawl inventory
- **THEN** the item still reports `NEEDS_INPUT`, and the evidence names the cause
- **AND** it does not instruct the operator to produce what they cannot

#### Scenario: a missing input dressed as out of scope
- **WHEN** a missing input is reported `N/A`
- **THEN** the requirement is violated: the item leaves the applicable set and the
  audit's reach improves exactly where it is thinnest

### Requirement: VRD-5 — `NO_DATA` and `NEEDS_INPUT` split by what failed

`NO_DATA` SHALL mean the audit tried to make the measurement and could not: the
service was unreachable, the script errored, or the result supplied no decidable value.
`NEEDS_INPUT` SHALL mean a named argument required to make that attempt was absent. Its cause
belongs in evidence and does not change the status.

**Why:** the two sentences identify different boundaries. A missing argument says the
check never had what it needed to start; `NO_DATA` says it started and no verdict came
back. The evidence, not a second status vocabulary, says who can act on the cause.
**Reader:** enforced. Unreachable measurements, execution failures and missing
credentials are each pinned to the right status. The general rule is read at 0.95.0 by
`TheStatusNamesWhoCanAct`, which derives the split from `HOW_TO_SUPPLY` — the tree's record
of which inputs an operator can actually hand a run — rather than from the branch an
absence arrived through, so a key nobody has added yet is decided by the same rule.

The third scenario has two readers, one per direction, and both were written because the
run was violating it. `test_the_dead_entry_gives_every_item_one_status` asserts that one
unreadable entry leaves offline and fetch items under the *same* status, where the offline
ones used to say `NEEDS_INPUT` while every other gated item said `NO_DATA`.
`test_one_missing_credential_gets_one_status_from_both_boundaries` asserts that the planner
and the grader answer an absent Search Console credential with the same status and the same
sentence, which is the row this document's own table carried for eleven releases. Asserting
each side alone is what let both pairs drift: a contradiction between two layers is not
visible from inside either one.

#### Scenario: the attempt was made and produced nothing
- **WHEN** a service is unreachable, a script crashes, or a result carries no decidable
  value
- **THEN** the item reports `NO_DATA`

#### Scenario: the attempt was never possible
- **WHEN** a named argument the check requires was absent
- **THEN** the item reports `NEEDS_INPUT`

#### Scenario: one absence answered two ways in one run
- **WHEN** two layers of a single run classify the same missing thing differently, one
  calling it `NO_DATA` and the other `NEEDS_INPUT`
- **THEN** the requirement is violated, whichever of the two is right

### Requirement: VRD-6 — only quality verdicts carry weight

The score SHALL be computed over `PASS`, `WARN` and `FAIL` alone. No other status may
contribute to either half of it. A row carrying `scores_with` is the exception among quality
verdicts: it reports its status but contributes no weight, because the row it names
already carries the shared measurement's weight (VRD-17).

**Why:** any other rule lets the score move when nothing about the site changed — for
instance when a credential is supplied or withheld.
**Reader:** enforced. Unit tests pin `N/A`, `NO_DATA`, `LLM_PENDING`, `MANUAL` and
`NEEDS_INPUT` out of the scored set, and pin the three quality outcomes into it.

#### Scenario: a credential arrives and the score does not move
- **WHEN** an item changes between `NEEDS_INPUT` and `NO_DATA`, or between `MANUAL` and
  `LLM_PENDING`, with no quality verdict on either side
- **THEN** neither half of the score changes

#### Scenario: a shared measurement is weighed once
- **WHEN** a row carries `scores_with`
- **THEN** it reports its quality status and contributes no weight

### Requirement: VRD-7 — `N/A` leaves the applicable set; the other four remain in it

Two denominators exist and MUST NOT be confused:

* the **scored set** — items carrying `PASS`, `WARN` or `FAIL`, governed by VRD-6;
* the **applicable set** — every item this audit still owes an answer for. `N/A` is
  excluded from it. `NO_DATA`, `NEEDS_INPUT`, `MANUAL` and `LLM_PENDING` remain in it,
  counted as unanswered.

**Why:** the audit's reach must not improve by failing to answer. An item nobody could
answer is still owed; an item that does not apply is not.
**Reader:** enforced. Measured by mutation on 29 August 2026, in all five directions this
requirement names: dropping `NO_DATA`, `NEEDS_INPUT`, `MANUAL` or `LLM_PENDING` out of the
applicable set reddens three, one, two and one test respectively, and keeping `N/A` in it
reddens two. The readers are the same unit tests as VRD-6, plus the coverage-stability
test.

An earlier draft read "enforced for the status routing", and `tests/test_specs.py` was
right to object to that shape even though the classification turned out to be correct: a
qualifier welded to a classification word claims less than the word alone, and nothing in
the document said which was meant. The probe settled it. The qualifier is gone because it
described the evidence rather than the claim.

#### Scenario: an item nobody could answer is still owed
- **WHEN** an item reports `NO_DATA`, `NEEDS_INPUT`, `MANUAL` or `LLM_PENDING`
- **THEN** it stays in the applicable set and counts as unanswered
- **AND** the audit's reach does not improve by failing to answer

#### Scenario: an item that does not apply is not owed
- **WHEN** an item reports `N/A`
- **THEN** it leaves the applicable set

#### Scenario: the two denominators are not interchangeable
- **WHEN** the scored set and the applicable set are compared on one run
- **THEN** they differ by exactly the items that are unanswered rather than unscored

### Requirement: VRD-8 — a status is derived from structured output, never from prose

A status SHALL be decided by reading named fields of a checker's structured result.
It MUST NOT be decided by matching words in a human-readable message.

**Why:** wording is the first thing that drifts. A pattern aimed at a phrase a checker
no longer emits matches nothing — and a rule that passes when nothing matches passes
every site in silence.
**Reader:** enforced.
`tests/test_registry.py::AVerdictComesFromAFieldAndNeverFromASentence` sweeps every
rule in the registry and fails on any pattern aimed at the `issues` list or at a
`message` field. The set of pattern operators is read out of `evaluate()` — the branches
that reach `re.compile` — rather than listed in the test, so an operator added to the
evaluator is in scope the day it is added; `count_matching_lte` was outside the
assertion audit's census even in principle, which is how MB-095 and MB-098 survived
four releases of being looked at.

Two of its tests exist to stop the sweep passing for the wrong reason: one fails if the
evaluator has no pattern operators left to find, and one pins CI-004, which matches
`noindex` against `meta_robots` and is legal — a machine token in a vocabulary the
machine defines is a field, and a test that could not tell that from prose would be
satisfied by deleting every regex in the tree.

#### Scenario: a rule reads a field
- **WHEN** an item's assertion names a key of the checker's structured output
- **THEN** the verdict follows that field's value

#### Scenario: a rule reads a sentence
- **WHEN** an item's assertion matches a pattern against prose intended for a human,
  such as an `issues` message
- **THEN** the requirement is violated, whatever the pattern currently matches

#### Scenario: a pattern over a value written for a machine
- **WHEN** an assertion matches a pattern against a field whose vocabulary the emitting
  machine defines, such as `meta_robots`
- **THEN** the requirement is satisfied, because what it forbids is prose and not
  regular expressions

#### Scenario: the checker rewords its message
- **WHEN** a checker changes the wording of a message a rule was matching
- **THEN** the pattern matches nothing, the rule passes, and the site is never checked —
  which is why this is forbidden rather than discouraged

### Requirement: VRD-9 — an unmapped value is undecided, never a pass

When a checker result contains a value the item's contract does not enumerate, a mapped
failure in the same result SHALL outrank it: the status is `FAIL`. Only when no element maps
to failure does the unmapped value make the item `NO_DATA`, with evidence naming the
value.

**Why:** treating anything unrecognised as acceptable makes every future vocabulary
change raise scores silently.
**Reader:** enforced. Evaluator tests pin an unmapped scalar and row to undecided and
pin a mixed result containing an unmapped value and mapped failure to failure.

#### Scenario: a value the contract does not enumerate
- **WHEN** a checker result contains a value the item's contract does not name, and
  nothing else in the result maps to failure
- **THEN** the item is `NO_DATA`, with evidence naming the value

#### Scenario: an unrecognised value beside a recognised failure
- **WHEN** the same result carries both an unmapped value and a mapped failure
- **THEN** the item is `FAIL`

#### Scenario: a vocabulary grows
- **WHEN** a checker begins emitting a value no item was written to expect
- **THEN** scores do not rise, because the unrecognised value is undecided rather than
  acceptable

### Requirement: VRD-10 — every status carries evidence

No status SHALL be emitted without a sentence saying what was decided, or what was
sought and not found, or which input was missing. This includes `PASS`.

**Why:** a bare status cannot be triaged, and a `PASS` with no evidence is
indistinguishable from a `PASS` for lack of a subject — which is how the Appendix A.1
violations went unnoticed.
**Reader:** partial, and what remains is shipped behaviour rather than a missing test.
The coverage half is closed since 0.94.2:
`tests/test_contract.py::EveryStatusCarriesEvidenceIncludingTheTwoNobodyChecked` runs the
whole registry against both fixture sites and requires evidence on every status. The two
that had gone unchecked — `NEEDS_INPUT` and `LLM_PENDING` — are 55 of the 217 items on a
live run, so the unchecked pair was a quarter of the registry; both carried evidence
already, and nothing required them to.

What is still open is Appendix B's other charge: this requirement is violated by shipped
behaviour in two places — the LLM answer merge, and the GSC status/evidence mismatch —
which no test can close by asserting, because the tree does the wrong thing there today.
Those are repairs, and until they are made this row stays `partial` however well the eight
statuses are covered.

The status set is derived from `STATUS_ORDER` rather than listed, which is the point and
not a convenience: the previous check named the statuses it covered, and a list cannot say
what is absent from it. A ninth status is covered here the day it joins that tuple, and a
second assertion refuses a status a run emits that no surface can render. Probed by
emptying the reason on the `NEEDS_INPUT` path, which reddens with ten named items.

#### Scenario: a passing item says what it checked
- **WHEN** an item reports `PASS`
- **THEN** it carries evidence, because a bare `PASS` cannot be told apart from a `PASS`
  awarded for lack of a subject

#### Scenario: every one of the eight
- **WHEN** any of the eight statuses is emitted, including `NEEDS_INPUT` and
  `LLM_PENDING`
- **THEN** evidence travels with it

### Requirement: VRD-11 — narrowing the registry by site type needs consent, given in advance or on sight

An audit may infer that a site is of a kind for which some items do not apply, and may
act on that inference only with the operator's consent. Consent takes exactly two forms:

* **in advance** — the operator selects automatic scoping for this run, accepting
  whatever category is detected;
* **on sight** — the operator is shown the detected category and confirms it.

Absent both, the audit SHALL run the full registry. Silence is never consent.

**Why:** dropping checks raises the score without anyone choosing that. The detection is
structural evidence, but the scoping is a decision and belongs to a person — who may
delegate it deliberately, which is what the first form is.
**Reader:** partial. Tests pin explicit automatic delegation, confirmation on sight,
non-interactive fallback to the full registry, and the rule that no profile drops a
critical item. They do not cover a detected non-default profile followed by EOF,
interruption, or three invalid answers; Appendix A.1 records those violations.

#### Scenario: consent given in advance
- **WHEN** the operator selects automatic scoping for the run
- **THEN** the detected category is applied, because delegation is a decision they made

#### Scenario: consent given on sight
- **WHEN** the operator is shown the detected category and confirms it
- **THEN** the detected category is applied

#### Scenario: the operator says nothing
- **WHEN** a category is detected and the operator ends the prompt without answering —
  end of input, an interrupt, or repeated unrecognised replies
- **THEN** the audit runs the full registry
- **AND** it does not fall back to the detected category, which would narrow the audit,
  raise the score, and name a profile nobody chose

#### Scenario: no terminal to ask at
- **WHEN** the run is non-interactive and no scoping was requested in advance
- **THEN** the audit runs the full registry

### Requirement: VRD-12 — the outcome vocabulary is closed, and "no expectation" is not a status

The outcome vocabulary SHALL remain closed at eight, and no layer may introduce a
ninth. This binds every consumer: runner, registry, report renderer, and the manifest of
expected verdicts.

A layer that needs to say **"no expectation is recorded here"** must express it
structurally — by carrying no declaration for that item — never by inventing a word and
placing it where a status belongs. The two are not interchangeable: a status describes
the site, while "no expectation" describes the declaration, and a document that stores
the second in the first's field cannot be compared against a run at all.

**Why:** a word that exists in only one layer cannot be compared with any other. Whatever
comparison was meant to read it will either crash or — far more likely — skip it, and a
skipped comparison is indistinguishable from a passing one. That is Appendix A.2, and it
hid whichever Appendix A.1 violations existed in each release from comparison throughout
the `v0.41.0` to `v0.91.0` window.
**Reader:** partial, and violated today. Answer merges reject words outside the closed
vocabulary and report surfaces are tested against all eight statuses, but the fixture
oracle explicitly permits and skips the ninth word. The design of the replacement — how
a declarations manifest represents absence of expectation — belongs to
[`openspec/specs/declarations/`](../declarations/spec.md) and is settled there by DEC-2; the
withdrawal itself is owed by whichever release removes the word.

#### Scenario: a layer invents a word
- **WHEN** any consumer writes a status outside the eight
- **THEN** the requirement is violated, whether or not anything currently reads that
  field

#### Scenario: a layer needs to say it expects nothing
- **WHEN** a declaration manifest has no expectation for an item
- **THEN** it carries no declaration for that item
- **AND** it does not write a ninth word into the status field, which describes the site
  rather than the declaration

#### Scenario: the invented word is skipped rather than rejected
- **WHEN** a comparison meets a status it does not recognise and continues past it
- **THEN** the skipped comparison is indistinguishable from a passing one, which is the
  harm this requirement exists to prevent

**Composition and transition.** The five requirements below are about statuses that
come from more than one place — several sampled pages, a capped input, an answer arriving
after the fact, a second reading, a shared measurement.

### Requirement: VRD-13 — a decided page outranks an undecided page in a sample

When sampled pages are combined for one item, undecided rows SHALL be dropped if any
sampled page carries a quality verdict. The worst remaining status wins, in the order
`FAIL` > `WARN` > `PASS`. If no sampled page carries a quality verdict, the item remains
undecided.

**Why:** one page with a measured defect is enough to establish that defect; a page the
audit could not judge must not erase it. Among decided pages, reporting anything but the
worst result hides a finding already measured.
**Reader:** enforced. Aggregation tests mix decided and undecided pages, pin `FAIL` and
`WARN` over `PASS`, and keep an all-undecided sample at `NO_DATA`.

#### Scenario: one page shows the defect and another could not be read
- **WHEN** a sample mixes a quality verdict with undecided rows
- **THEN** the undecided rows are dropped and the worst quality verdict wins

#### Scenario: no page could be judged
- **WHEN** every sampled page is undecided
- **THEN** the item stays undecided

### Requirement: VRD-14 — truncation withholds only a clean absence assertion

When an assertion passes because the sought defect is absent but its input is marked
truncated, that `PASS` SHALL become `NO_DATA`. A `WARN` or `FAIL` established in the part that
was read survives, and its evidence says the reported measurement is a floor.

**Why:** a truncated input cannot prove that nothing exists beyond its cap, but a defect
already found remains a defect. Withholding both would discard evidence; keeping both
would turn an incomplete search into a clean bill of health.
**Reader:** enforced. Tests census every absence-passing assertion over capped input,
pin the `PASS` to `NO_DATA` transition, preserve both `WARN` and `FAIL`, and require floor
evidence for the surviving non-pass.

#### Scenario: a clean bill of health over a capped search
- **WHEN** an assertion passes by finding none of the thing it forbids, and the input
  says it was truncated
- **THEN** the `PASS` becomes `NO_DATA`

#### Scenario: a defect found in the part that was read
- **WHEN** a `WARN` or `FAIL` was established before the cap
- **THEN** it survives, and its evidence says the reported measurement is a floor

#### Scenario: a pass by presence
- **WHEN** an item passes because it found something it requires, over a truncated input
- **THEN** the `PASS` stands, because reading more pages cannot take it away

### Requirement: VRD-15 — answers may replace only their own pending status

A language-model answer MAY replace only `LLM_PENDING`, and a person's answer MAY
replace only `MANUAL`. An answer path MUST NOT overwrite a measured verdict, and MUST NOT
answer the other path's queue.

**Why:** an answer is a transition from a named kind of pending work, not a general
permission to rewrite the report. Keeping the doors separate preserves measured results
and the provenance of each judgement.
**Reader:** enforced. Merge tests pin both allowed transitions, reject overwriting a
script verdict, and reject a person's attempt to answer `LLM_PENDING`.

#### Scenario: an answer fills its own queue
- **WHEN** a model answer arrives for an `LLM_PENDING` item, or a person's answer for a
  `MANUAL` one
- **THEN** the status is replaced

#### Scenario: an answer reaches for a measured verdict
- **WHEN** either answer path targets an item a script already decided
- **THEN** the measured verdict stands

#### Scenario: an answer reaches for the other queue
- **WHEN** a person's answer targets `LLM_PENDING`, or a model's targets `MANUAL`
- **THEN** it is refused

### Requirement: VRD-16 — a disagreeing second model reading returns to `NO_DATA`

When a second model reading disagrees with a model verdict already assigned to an
item, the item SHALL become `NO_DATA`. The report records both statuses; it does not choose either
reading as the winner.

**Why:** disagreement is evidence that the question was not settled, not a basis for
silently preferring the first or second answer.
**Reader:** enforced. Review tests pin agreement to corroboration, disagreement to
`NO_DATA` with both statuses recorded, and the resulting reduction in scored reach.

#### Scenario: the second reading agrees
- **WHEN** a review confirms the verdict already assigned
- **THEN** the verdict stands, corroborated

#### Scenario: the second reading disagrees
- **WHEN** a review contradicts the verdict already assigned
- **THEN** the item becomes `NO_DATA`, both statuses are recorded, and neither reading is
  named the winner
- **AND** the scored reach falls, which is the cost of an unsettled question

### Requirement: VRD-17 — `scores_with` reports twice and carries weight once

A row carrying `scores_with` SHALL be graded and reported with its quality status, and
MUST contribute no weight. The row it names carries the shared measurement's weight.

**Why:** synonym items remain visible as two registry obligations, while one defect from
one shared check changes the headline score only once.
**Reader:** enforced. Scoring tests pin the twin's reported decided status, partition
membership, zero additional score effect and unchanged weight coverage.

#### Scenario: two obligations, one measurement
- **WHEN** two registry items resolve to one shared check and one carries `scores_with`
- **THEN** both are reported with their quality status
- **AND** the headline score and the weight coverage move exactly as they would for one

#### Scenario: the twin is still an item
- **WHEN** the partition of the registry is counted
- **THEN** the twin appears in it, decided, rather than vanishing because it carries no
  weight

## 4. Invariants

* **INV-1** — the report's partition of the registry sums to the item count, with every
  item in exactly one row. *Reader: partial, as VRD-1.*
* **INV-2** — the statuses any layer may declare are a subset of §2. *Reader: partial;
  answer merges and report surfaces read subsets, while the fixture oracle enforces the
  violation.*
* **INV-3** — each status has exactly one definition, shared by every layer, with one
  artifact owning it. Today the runner, the report renderer and the fixture oracle each
  keep their own constants. *Reader: partial; runner and report constants are tested for
  synchrony, but no test establishes one owner or one definition.*
* **INV-4** — no status transition is silent: a change between two runs of the same tree
  is reported. *Reader: partial; comparison is enforced for items present in both saved
  runs, but a run may omit history and dropped items are only noted.*

## 5. What this document does not decide

This list is also the routing table for Appendix A: where a violation of a requirement
here has a mechanism, the mechanism is described in the document named below and cited
from the appendix rather than repeated in it.

* which items exist, what each measures, whether a title matches its measurement, which
  subjects may legitimately not exist, and how applicability is declared for checked
  and sourceless items — [`openspec/specs/registry/`](../registry/spec.md), REG-6 and REG-9;
* how expected verdicts are declared, compared, and how absence of expectation is
  represented — [`openspec/specs/declarations/`](../declarations/spec.md), which also owns what
  the census can and cannot see. VRD-12 was blocked on that document; it now exists, and
  DEC-2 is the answer — "no expectation" is the absence of a declaration, not a ninth
  word;
* what a run does when an operator does not answer, and how a profile is chosen —
  [`openspec/specs/run-lifecycle/`](../run-lifecycle/spec.md), RUN-14;
* the thresholds separating `WARN` from `FAIL` for any item, and what a threshold must
  rest on — [`openspec/specs/evidence/`](../evidence/spec.md), EVD-6;
* the weights by which quality verdicts produce a score —
  [`openspec/specs/scoring/`](../scoring/spec.md).

## 6. Open questions

* **Should `NEEDS_INPUT` name an actor?** Under VRD-4 the status means a required input
  was absent, whatever the reason, so routing information about who can act now lives
  only in the evidence. It remains open whether the status set is too coarse or whether
  evidence should carry that load. A status-design decision that either refines the
  vocabulary or makes the routing duty of evidence explicit would settle it.
A second question that stood here — where an applicability condition lives for an item
with no `check` block, so that a sourceless item such as LO-199 can have a boundary at
all — was carried over to [`openspec/specs/registry/`](../registry/spec.md) §6 when that document
was written, and is asked there. It is a schema question, not a vocabulary one; this
document only requires that whatever answer is chosen produce `N/A` and not a quality
verdict.

## Appendix A — measured disagreements, 25 August 2026

Observation, not specification. Measured on `v0.91.0`. The origin columns in A.1 cover
the two HTTP fixture origins; TLS observations are discussed outside that table rather
than presented as additional origin columns.

This document was written first, when it was the only one, and its appendix accordingly
described the mechanism behind each violation as well as the violation itself. Eleven
other documents now exist and own those mechanisms. What stays here is the disagreement
with a requirement of *this* document; the anatomy and the counts are cited, never
restated, because a count stated in two places is a count that will disagree with itself.
That is not a worry, it is the measurement in
[`openspec/specs/declarations/`](../declarations/spec.md) A.6: four counts drifted in the two
files whose own subject is measurement, and [`openspec/specs/registry/`](../registry/spec.md)
REG-12 records the same shape three more times.

#### A.1 — items contradicting these requirements

Observed values in the table are for the `good` and `broken` HTTP origins only.

| item | title | `good` | `broken` | breaks | should be |
|---|---|---|---|---|---|
| AR-146 | Check Pagination | `PASS` | `PASS` | VRD-2, VRD-3 | `N/A` |
| AR-154 | Optimize E-commerce Category Pages | `PASS` | `WARN` | VRD-2, VRD-3 | `N/A` |
| AR-163 | Control Faceted Navigation | `PASS` | `PASS` | VRD-2, VRD-3 | `N/A` |
| MB-095, MB-098 | image weight and dimensions | — | — | VRD-8 | *closed in 0.93.0* |
| GO-138, GO-143 | invalid URLs, organisation schema | — | — | VRD-8 | *closed in 0.93.0* |

The first three items ask for quality of an entity neither fixture tree contains, and
none declares an applicability condition, which is why they answer success instead of
`N/A`. Why an item without such a condition falls through to success is
[`openspec/specs/registry/`](../registry/spec.md) REG-9, which also holds the list of items owing
one; that the same absent subject leaves by a second exit, `NO_DATA`, on eleven further
items is [`openspec/specs/declarations/`](../declarations/spec.md) A.1. Both are that debt seen
from inside this vocabulary: one condition, three words, none of them `N/A`.

The last four decided their verdict by matching regexes against prose `issues`
messages, including `(?i)404|redirect|noindex` and `(?i)WebSite`. All four read counted
fields as of 0.93.0, and the repair moved live verdicts in three of them:

* **GO-138** matched `404` against the message "Sitemap URL returns HTTP {status}", so
  it asked about one status code and passed a sitemap of URLs returning 500 or 503. It
  now reads `invalid_url_count` — status at or above 400, a redirect chain, or meta
  noindex — over the URLs actually read, and is absent when the run fetched nothing, so
  an audit that never looked answers `NO_DATA` instead of `PASS`.
* **MB-095** counted messages matching `(?i)large|oversize|weight`, none of which the
  script emits without `--fetch-images`, which the registry did not pass. Every live run
  of this item passed on a page whose image weights were never measured. It reads
  `large_image_count` and moved onto MD-185's existing invocation, which already
  fetches — no extra launch and no extra request.
* **MB-098** counted `(?i)size|dimension`, which caught "Large image transfer size" and
  "Responsive image has srcset but no sizes" together. Their union was nobody's
  measurement; it is what a pattern happened to match. It reads
  `srcset_without_sizes_count`, the half its title names, and at `eq 0` rather than the
  old rule's ten — a ten counted over images would need eleven bad ones before the page
  said anything. The other half is MB-095's question and is still asked there, once.
* **GO-143** reads `incomplete_nodes_by_type.WebSite`, with `missing_is: pass` standing
  in for what the pattern did by matching nothing. This one did not move: the count
  reproduces the old answer on both fixtures.

The checker that fed MB-098 was wrong in the same direction and was corrected with it:
it reported a missing `sizes` for any `srcset`, where only width descriptors need one.
An `srcset` in `x` descriptors is correct markup and was being reported as a defect.

Two other shipped paths violate these requirements. A third — `gsc` grading without
credentials — was fixed at 0.95.0 and its row is gone; what it was, and why it took a
document about the run lifecycle finding the same swap from the other side to close it, is
[`openspec/specs/run-lifecycle/`](../run-lifecycle/spec.md) A.7. The remedy is the one this
table named: `NEEDS_INPUT`, with the sentence the planner already used, now written once so
the two boundaries cannot answer differently again.

| path | observed behaviour | breaks | should be |
|---|---|---|---|
| LLM answer merge | an empty rationale becomes a scored quality verdict with `LLM: no rationale given` | VRD-10 | refuse the answer until it says what was decided |
| interactive `choose_profile` | EOF, `KeyboardInterrupt`, and three invalid answers return the detected profile | VRD-11 | run the full registry because silence is not consent |

The manual answer path already refuses an empty rationale, so the enforceable VRD-10
rule exists next door to the LLM violation. The three silent exits, the four tests that
cover them and the probe that established which branch each takes are
[`openspec/specs/run-lifecycle/`](../run-lifecycle/spec.md) A.5.

The GSC contradiction was split across two sites in
`skills/seo-checklist/scripts/checklist_runner.py`: `build_plan` assigned `NEEDS_INPUT` to
planned checks requiring GSC, while `grade` assigned `NO_DATA` and the credential
instruction to `source: gsc` items unless they were listed in `GSC_UNAVAILABLE`. The two
boundaries classified the same missing credential differently within one run, and the
grader's instruction described a missing input while its status said an attempted
measurement returned no data.

Both now read one named sentence, `GSC_CREDENTIALS_ABSENT`, and
`test_one_missing_credential_gets_one_status_from_both_boundaries` compares the two
boundaries rather than each of them. Naming the string is half of it and the weaker half:
the earlier line references in this paragraph had already gone stale, which is the same
failure one layer up — a record of where a thing lives, kept by hand, beside the thing.

**Not in this table, and why.** GO-137 *Reconcile Indexed Pages vs. Sitemaps* answers
`PASS` and `WARN`, and an earlier draft of this document called that a VRD-4 violation
for want of a search-engine index inventory. That was wrong: the item's `inventory_json`
is produced by the run's own crawl, not supplied by an operator, so VRD-4 does not reach
it. What the item actually shows is a title that names one measurement and a rule that
performs another — a registry defect, held by
[`openspec/specs/registry/`](../registry/spec.md) REG-6.

**Also not in this table.** AR-150 and CI-014 answer `PASS` on `broken_tls`, and that is
correct under VRD-3: their rules forbid redirect chains and loops, and the origin has
none. What their declarations recorded is a limit of the harness rather than a wrong
verdict, and a limit of the instrument belongs beside the instrument's output —
[`openspec/specs/declarations/`](../declarations/spec.md) DEC-13.

#### A.2 — the violation of VRD-12, and how long it has been running

The expected-verdict manifest declares `INDETERMINATE`, which no audit code emits. Its
reader skips such declarations instead of comparing them. What the ninth word is hiding
today — how many declarations carry it, what each of them says, and which status the
audit answers instead — is [`openspec/specs/declarations/`](../declarations/spec.md) A.1, and is
not repeated here. What this section owns is the *duration*, because that is what makes a
closed vocabulary worth specifying before anything else.

No comparison read any of them, however many existed at the time. At `v0.41.0` the
manifest carried 42 declarations, 8 using the ninth word; at `v0.48.0`, 246 and 28; at
`v0.84.0`, 250 and 27.

Only four of today's twelve contradictions date from `v0.41.0`. AR-146 on both HTTP
origins and AR-150 and CI-014 on `broken_tls` begin at `v0.42.0`; AR-154 and AR-163 on
both HTTP origins begin at `v0.48.0`. The unread window remains `v0.41.0` through
`v0.91.0`, fifty-five releases over about thirteen days and sixteen hours; the number
of unread declarations changed within it.

#### A.3 — the census entry these findings re-read

AR-146, AR-150, AR-154, AR-163, CI-014 and GO-137 all sit in the census class
*answered somewhere, never FAIL* — a count kept by `tests/census.json` and reported
against clause 1 of `ROADMAP.md`, which is where its current value lives. Under this
document those six split three ways: AR-146, AR-154 and AR-163 are rules handed no subject that answered success;
AR-150 and CI-014 are correct verdicts over a thin corpus; GO-137 measures something
other than its title. One census row, three meanings — and only a document like this
one separates them.

Note what that implies about the census as an instrument. Three of the seventeen items
owing an applicability declaration surface in that class; the other fourteen do not,
because the fixture corpus never puts them in a position to answer differently. The count
is therefore a floor on this class of defect and never a measure of it — the general form
of that, and the requirement that an instrument publish its own limits, is
[`openspec/specs/declarations/`](../declarations/spec.md) DEC-13.

## Appendix B — how much of this document is enforced

Compiled by analysis of the tree, and spot-checked by hand on VRD-3, VRD-6, VRD-8 and
VRD-11.

| | requirements |
|---|---|
| **enforced** | VRD-4, VRD-5, VRD-6, VRD-7, VRD-8, VRD-9, VRD-13, VRD-14, VRD-15, VRD-16, VRD-17 |
| **partial** | VRD-1, VRD-2, VRD-3, VRD-10, VRD-11, VRD-12 |
| **none** | — none |

Invariants: INV-1, INV-2, INV-3 and INV-4 partial; INV-2 is violated.

**Eleven enforced, six partial, none unread.** Five requirements are violated by shipped
behaviour or declarations while nothing reddens: VRD-2 and VRD-3 by the seventeen missing
applicability declarations; VRD-10 by the LLM answer merge; VRD-11 by the profile prompt's
silent exits; and VRD-12 by the manifest.

VRD-5 left that list at 0.95.0, by repairing the tree in both directions rather than by
recording either. The grader now answers an absent credential with the planner's status and
the planner's sentence, which also closes VRD-10's half of that row; and the general rule —
which of the two statuses an absence becomes — is read for the first time, derived from the
table of inputs an operator can supply. That derivation is what found the second violation,
in a place neither this document nor its appendix had looked: one unreadable entry page was
leaving offline items `NEEDS_INPUT` and every other gated item `NO_DATA`, the third
scenario again, in a run where nobody had asked about Search Console at all. VRD-8 left that list
in 0.93.0, and it is the one entry here closed by repairing the tree rather than by
writing a test: the four rules now read counted fields, and the sweep that holds them
would redden on a revert. The totals are recomputed from the readers named above: E1 leaves VRD-3
partial because declaration completeness is unread, E2's two-status gap is closed in 0.94.2 — evidence is now required on all
eight, derived from `STATUS_ORDER` — and VRD-10 stays partial for the LLM answer merge
rather than for coverage. E3 said VRD-5's general rule was only partially read, and stayed
true for six releases after it was written; it is the entry that moved.

An earlier draft of this appendix published `5 none / 3 partial / 4 enforced` and was
wrong in both directions: it claimed no reader for VRD-2 through VRD-5, which the
`applies_when`, missing-input and unreachable-measurement tests read at least in part,
and claimed readers for VRD-8 and the old VRD-9 that did not constrain what those
requirements said. The manifest and answer-path tests also make VRD-12 partial rather
than unread. A census of readers assembled by reading the document rather than the tests
is worth nothing — which is the same failure the document is about, committed by the
document about itself.
