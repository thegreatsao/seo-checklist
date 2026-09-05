# Verdicts — the vocabulary every layer shares

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

## 3. Requirements

### VRD-1 — one status per item per run

Every registry item receives exactly one status in every audit. No item is absent from a
report, and no item carries two.

**Why:** a report that omits items cannot be compared with another report, and a
denominator that varies between runs means nothing.
**Reader:** partial. `tests/test_contract.py` compares each fixture run's id set against
all 217 registry ids, which catches omission; set equality would still accept a
duplicate row, so "exactly once" is not fully read.

### VRD-2 — a quality verdict requires a subject and a basis

`PASS`, `WARN` and `FAIL` may be assigned only when the entity whose quality the item
judges exists on this site (VRD-3) and the verdict rests on a stated basis — a
measurement, a person's claim, or a model's judgement, recorded as provenance per §2.1.
That entity is the **subject**. A required feature or a defect that an item forbids is
never the subject: its presence or absence may be the measured fact that decides a rule
about an existing page or site.

An item whose subject does not exist **must not** report `PASS`.

**Why:** `PASS` carries weight in the score, and an item that passes for lack of a
subject awards credit the site never earned — a five-page bakery scoring for *Optimize
E-commerce Category Pages* it does not have. It also reads to the operator as
confirmation that something was checked.
**Reader:** partial. `tests/test_runner.py` requires an item whose applicability subject
is absent to be `N/A` rather than `PASS`, but only through the `applies_when` mechanism,
which most items do not declare — see VRD-3 and Appendix A.1.

### VRD-3 — missing data, a missing subject, and an absent defect are distinct

Absence is resolved by three mechanisms, in this order:

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

### VRD-4 — a missing input is never `N/A` and never a quality verdict

When a named input a check requires was not present, the status is `NEEDS_INPUT`,
whatever the reason. The evidence names a supply route only when one exists. Where no
route exists — for example, for a fetched page or crawl inventory — the evidence names
the cause instead and must not instruct the operator to produce something they cannot.

**Why:** `N/A` removes the item from the applicable set, so reporting a missing input as
`N/A` improves the audit's apparent reach exactly where it is thinnest. A quality
verdict is worse: it claims a decision that never happened.
**Reader:** enforced. Planner tests pin absent and refused artefacts, missing HTML,
missing Search Console credentials and a missing Safe Browsing key to `NEEDS_INPUT`;
they also pin a supply route where one exists and cause-only evidence where none does.

### VRD-5 — `NO_DATA` and `NEEDS_INPUT` split by what failed

`NO_DATA` says the audit tried to make the measurement and could not: the service was
unreachable, the script errored, or the result supplied no decidable value.
`NEEDS_INPUT` says a named argument required to make that attempt was absent. Its cause
belongs in evidence and does not change the status.

**Why:** the two sentences identify different boundaries. A missing argument says the
check never had what it needed to start; `NO_DATA` says it started and no verdict came
back. The evidence, not a second status vocabulary, says who can act on the cause.
**Reader:** partial. Unreachable measurements, execution failures and missing
credentials are each pinned to the right status by tests; the general rule is not read.

### VRD-6 — only quality verdicts carry weight

The score is computed over `PASS`, `WARN` and `FAIL` alone. No other status contributes
to either half of it. A row carrying `scores_with` is the exception among quality
verdicts: it reports its status but contributes no weight, because the row it names
already carries the shared measurement's weight (VRD-17).

**Why:** any other rule lets the score move when nothing about the site changed — for
instance when a credential is supplied or withheld.
**Reader:** enforced. Unit tests pin `N/A`, `NO_DATA`, `LLM_PENDING`, `MANUAL` and
`NEEDS_INPUT` out of the scored set, and pin the three quality outcomes into it.

### VRD-7 — `N/A` leaves the applicable set; the other four remain in it

Two denominators exist and must not be confused:

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

### VRD-8 — a status is derived from structured output, never from prose

A status is decided by reading named fields of a checker's structured result. It is
never decided by matching words in a human-readable message.

**Why:** wording is the first thing that drifts. A pattern aimed at a phrase a checker
no longer emits matches nothing — and a rule that passes when nothing matches passes
every site in silence.
**Reader:** none effective, and the requirement is violated today by four registry rules
(Appendix A.1). The assertion audit asks whether a pattern can still match something; it
does not ask whether a verdict should have come from a pattern at all. It also does not
census `count_matching_lte`, so MB-095 and MB-098 are outside what it inspects even in
principle. The audit therefore stays green on all four violations.

### VRD-9 — an unmapped value is undecided, never a pass

When a checker result contains a value the item's contract does not enumerate, a mapped
failure in the same result outranks it: the status is `FAIL`. Only when no element maps
to failure does the unmapped value make the item `NO_DATA`, with evidence naming the
value.

**Why:** treating anything unrecognised as acceptable makes every future vocabulary
change raise scores silently.
**Reader:** enforced. Evaluator tests pin an unmapped scalar and row to undecided and
pin a mixed result containing an unmapped value and mapped failure to failure.

### VRD-10 — every status carries evidence

No status is emitted without a sentence saying what was decided, or what was sought and
not found, or which input was missing. This includes `PASS`.

**Why:** a bare status cannot be triaged, and a `PASS` with no evidence is
indistinguishable from a `PASS` for lack of a subject — which is how the Appendix A.1
violations went unnoticed.
**Reader:** partial. Evidence is checked for `PASS`, `WARN`, `FAIL`, `N/A`, `NO_DATA` and
`MANUAL`; it is not checked for `NEEDS_INPUT` or `LLM_PENDING`.

### VRD-11 — narrowing the registry by site type needs consent, given in advance or on sight

An audit may infer that a site is of a kind for which some items do not apply, and may
act on that inference only with the operator's consent. Consent takes exactly two forms:

* **in advance** — the operator selects automatic scoping for this run, accepting
  whatever category is detected;
* **on sight** — the operator is shown the detected category and confirms it.

Absent both, the audit runs the full registry. Silence is never consent.

**Why:** dropping checks raises the score without anyone choosing that. The detection is
structural evidence, but the scoping is a decision and belongs to a person — who may
delegate it deliberately, which is what the first form is.
**Reader:** partial. Tests pin explicit automatic delegation, confirmation on sight,
non-interactive fallback to the full registry, and the rule that no profile drops a
critical item. They do not cover a detected non-default profile followed by EOF,
interruption, or three invalid answers; Appendix A.1 records those violations.

### VRD-12 — the outcome vocabulary is closed, and "no expectation" is not a status

No layer may introduce a ninth status. This binds every consumer: runner, registry,
report renderer, and the manifest of expected verdicts.

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

## 3.1 Composition and transition requirements

### VRD-13 — a decided page outranks an undecided page in a sample

When sampled pages are combined for one item, undecided rows are dropped if any sampled
page carries a quality verdict. The worst remaining status wins, in the order
`FAIL` > `WARN` > `PASS`. If no sampled page carries a quality verdict, the item remains
undecided.

**Why:** one page with a measured defect is enough to establish that defect; a page the
audit could not judge must not erase it. Among decided pages, reporting anything but the
worst result hides a finding already measured.
**Reader:** enforced. Aggregation tests mix decided and undecided pages, pin `FAIL` and
`WARN` over `PASS`, and keep an all-undecided sample at `NO_DATA`.

### VRD-14 — truncation withholds only a clean absence assertion

When an assertion passes because the sought defect is absent but its input is marked
truncated, that `PASS` becomes `NO_DATA`. A `WARN` or `FAIL` established in the part that
was read survives, and its evidence says the reported measurement is a floor.

**Why:** a truncated input cannot prove that nothing exists beyond its cap, but a defect
already found remains a defect. Withholding both would discard evidence; keeping both
would turn an incomplete search into a clean bill of health.
**Reader:** enforced. Tests census every absence-passing assertion over capped input,
pin the `PASS` to `NO_DATA` transition, preserve both `WARN` and `FAIL`, and require floor
evidence for the surviving non-pass.

### VRD-15 — answers may replace only their own pending status

A language-model answer may replace only `LLM_PENDING`, and a person's answer may
replace only `MANUAL`. Neither answer path may overwrite a measured verdict, and neither
may answer the other path's queue.

**Why:** an answer is a transition from a named kind of pending work, not a general
permission to rewrite the report. Keeping the doors separate preserves measured results
and the provenance of each judgement.
**Reader:** enforced. Merge tests pin both allowed transitions, reject overwriting a
script verdict, and reject a person's attempt to answer `LLM_PENDING`.

### VRD-16 — a disagreeing second model reading returns to `NO_DATA`

When a second model reading disagrees with a model verdict already assigned to an item,
the item becomes `NO_DATA`. The report records both statuses; it does not choose either
reading as the winner.

**Why:** disagreement is evidence that the question was not settled, not a basis for
silently preferring the first or second answer.
**Reader:** enforced. Review tests pin agreement to corroboration, disagreement to
`NO_DATA` with both statuses recorded, and the resulting reduction in scored reach.

### VRD-17 — `scores_with` reports twice and carries weight once

A row carrying `scores_with` is graded and reported with its quality status, but
contributes no weight. The row it names carries the shared measurement's weight.

**Why:** synonym items remain visible as two registry obligations, while one defect from
one shared check changes the headline score only once.
**Reader:** enforced. Scoring tests pin the twin's reported decided status, partition
membership, zero additional score effect and unchanged weight coverage.

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

### A.1 — items contradicting these requirements

Observed values in the table are for the `good` and `broken` HTTP origins only.

| item | title | `good` | `broken` | breaks | should be |
|---|---|---|---|---|---|
| AR-146 | Check Pagination | `PASS` | `PASS` | VRD-2, VRD-3 | `N/A` |
| AR-154 | Optimize E-commerce Category Pages | `PASS` | `WARN` | VRD-2, VRD-3 | `N/A` |
| AR-163 | Control Faceted Navigation | `PASS` | `PASS` | VRD-2, VRD-3 | `N/A` |
| MB-095, MB-098 | image weight and dimensions | — | — | VRD-8 | verdict from structured fields |
| GO-138, GO-143 | invalid URLs, organisation schema | — | — | VRD-8 | verdict from structured fields |

The first three items ask for quality of an entity neither fixture tree contains, and
none declares an applicability condition, which is why they answer success instead of
`N/A`. Why an item without such a condition falls through to success is
[`openspec/specs/registry/`](../registry/spec.md) REG-9, which also holds the list of items owing
one; that the same absent subject leaves by a second exit, `NO_DATA`, on eleven further
items is [`openspec/specs/declarations/`](../declarations/spec.md) A.1. Both are that debt seen
from inside this vocabulary: one condition, three words, none of them `N/A`.

The last four decide their verdict by matching regexes against prose `issues` messages,
including `(?i)404|redirect|noindex` and `(?i)WebSite`.

Three other shipped paths violate these requirements:

| path | observed behaviour | breaks | should be |
|---|---|---|---|
| LLM answer merge | an empty rationale becomes a scored quality verdict with `LLM: no rationale given` | VRD-10 | refuse the answer until it says what was decided |
| interactive `choose_profile` | EOF, `KeyboardInterrupt`, and three invalid answers return the detected profile | VRD-11 | run the full registry because silence is not consent |
| `gsc` grading without credentials | the grader assigns `NO_DATA` with evidence instructing the operator to set credentials, while the planner classifies missing GSC credentials as `NEEDS_INPUT` elsewhere in the same run | VRD-5; VRD-10 evidence/status mismatch | use `NEEDS_INPUT` with evidence that describes the missing input |

The manual answer path already refuses an empty rationale, so the enforceable VRD-10
rule exists next door to the LLM violation. The three silent exits, the four tests that
cover them and the probe that established which branch each takes are
[`openspec/specs/run-lifecycle/`](../run-lifecycle/spec.md) A.5.

The GSC contradiction is split across two sites in
`skills/seo-checklist/scripts/checklist_runner.py`: `build_plan` assigns
`NEEDS_INPUT` to planned checks requiring GSC at lines 1021–1027, while `grade` assigns
`NO_DATA` and the credential instruction to `source: gsc` items at lines 1242–1260 unless
they are listed in `GSC_UNAVAILABLE`. The two boundaries therefore classify the same
missing credential differently within one run, and the grader's instruction describes a
missing input while its status says an attempted measurement returned no data.

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

### A.2 — the violation of VRD-12, and how long it has been running

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

### A.3 — the census entry these findings re-read

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
| **enforced** | VRD-4, VRD-6, VRD-7, VRD-9, VRD-13, VRD-14, VRD-15, VRD-16, VRD-17 |
| **partial** | VRD-1, VRD-2, VRD-3, VRD-5, VRD-10, VRD-11, VRD-12 |
| **none** | VRD-8 |

Invariants: INV-1, INV-2, INV-3 and INV-4 partial; INV-2 is violated.

**Nine enforced, seven partial, one unread.** Seven requirements are violated by shipped
behaviour or declarations while nothing reddens: VRD-2 and VRD-3 by the seventeen missing
applicability declarations; VRD-5 by the grader classifying missing GSC credentials as
`NO_DATA`; VRD-8 by four registry rules; VRD-10 by the LLM answer merge and the GSC
status/evidence mismatch; VRD-11 by the profile prompt's silent exits; and VRD-12 by the
manifest. The totals are recomputed from the readers named above: E1 leaves VRD-3
partial because declaration completeness is unread, E2 leaves VRD-10 partial because
two statuses remain uncovered, and E3 confirms that VRD-5's general rule is only
partially read.

An earlier draft of this appendix published `5 none / 3 partial / 4 enforced` and was
wrong in both directions: it claimed no reader for VRD-2 through VRD-5, which the
`applies_when`, missing-input and unreachable-measurement tests read at least in part,
and claimed readers for VRD-8 and the old VRD-9 that did not constrain what those
requirements said. The manifest and answer-path tests also make VRD-12 partial rather
than unread. A census of readers assembled by reading the document rather than the tests
is worth nothing — which is the same failure the document is about, committed by the
document about itself.
