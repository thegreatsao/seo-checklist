# Registry — what an item is, and what it is allowed to claim

## Purpose

The fixed list of checklist items — what an item is, how the list is generated, where
its titles come from, the language its rules are written in, and the two declarations
that change what a verdict means. It is the denominator every other document in this
suite quantifies over, and the one artifact here that is *generated*, which makes it
cheap to keep honest and easy to lie about in the same breath. This document fixes what
an item is and what it may claim about itself, so that a number computed from the
registry is a number about a known population.

**Capability:** the fixed list of checklist items, how it is generated, where its titles
come from, the language its rules are written in, and the two declarations that change
what a verdict means (C1–C5 of the capability inventory).

This document is normative and is written as though no code existed. Where the
implementation disagrees, the implementation is presumed wrong until this document is
changed by argument. Appendix A records disagreements measured on 26 August 2026, one of
them corrected on the 29th.

Every requirement carries a **Reader** line naming what makes it fail when violated;
Appendix B is the census of those lines. A requirement whose reader is `none` is an
intention, and is counted as one.

**Inherited, not restated:** the eight statuses and when each is required belong to
[`openspec/specs/verdicts/`](../verdicts/spec.md); how weight and the fix order are computed
belong to [`openspec/specs/scoring/`](../scoring/spec.md). This document says what an item *is*,
never what a run does with it.

---

## 1. Why the registry is the contract

Every other document in this suite quantifies over the registry. The score is a fraction
of it, the partition sums to it, the manifest of expected verdicts declares against it,
and the census counts its answers. If the registry can change without anyone noticing —
in its membership, its severities, its rules, or what its items claim to measure — then
every number computed from it is a number about an unknown population.

That is not hypothetical. The registry's own `source` field states a composition that is
wrong and has been for some time, and nothing reads it. Seventeen items judge the
quality of an entity that may legitimately not exist while two declare that boundary.
One item's title promises a reconciliation against a search engine's index and its rule
measures something else.

The registry is also the one artifact here that is **generated**. That makes it cheap to
keep honest and easy to lie about in the same breath: a claim written as a literal in
the generator is reproduced faithfully by the staleness check and is never compared with
the thing it describes.

## 2. What an item is

An item is a question asked of a site, with an id that never changes meaning.

**Mandatory on every item:** `id`, `category`, `category_label`, `title`, `severity`,
`source`, `effort`, `fix`, and `plerdy_ref` (which may be null).

**Present when the item is machine-decided:** `check`, carrying `script`, `args`,
`requires`, and one `assert` rule; optionally `warn`, `applies_when`, `cannot_fail`.

**Present when the item is judged by a model:** `lens`.

**Present when the item is a second spelling of another item's check:** `scores_with`.

### 2.1 Closed vocabularies

| field | values | distribution today |
|---|---|---|
| `source` | script, llm, manual, gsc | 145 / 38 / 31 / 3 |
| `severity` | critical, high, medium, low | 19 / 62 / 102 / 34 |
| `effort` | low, medium, high | 66 / 52 / 99 |
| `lens` | copy, layout, locale, market | 19 / 13 / 3 / 3 |
| `requires` | offline, fetch, crawl, api, gsc, safe_browsing | 28 / 74 / 21 / 11 / 8 / 3 |

72 items carry no `check` and therefore no `requires`: they are the manual, model-judged
and Search-Console items.

## Requirements

### Requirement: REG-1 — the registry is the denominator, and it is versioned by content

The registry SHALL be a fixed list with a stated count and a `registry_version` derived
from the items themselves. Every artifact computed from it MUST carry that version.

**Why:** two numbers about a site are comparable only if they were computed over the
same population. A version a hand can set while the content moves is the failure this
tree has already measured elsewhere; deriving it from the content is what makes the
claim checkable.
**Reader:** partial. `test_registry_is_versioned`, `test_ids_unique` and the item-count
assertion pin the identity, and two changelog tests bind the version to the release
record. But the *if and only if* is held by the generator and its byte-comparison
(REG-2), not by any reader of this requirement: edit a title in the artifact and leave
the version alone, and every reader named here stays green — only `--check` objects. A
requirement whose substance is enforced by a different requirement's reader is partial.

#### Scenario: an item changes and the version does not
- **WHEN** a title, a severity or an assertion in the artifact differs from what the
  generator would write, and `registry_version` is left as it was
- **THEN** the requirement is violated, because the version no longer identifies the
  population two numbers were computed over
- **AND** every reader this requirement names stays green, which is why it is filed
  below its own substance

#### Scenario: the stated count and the list disagree
- **WHEN** `item_count` names a number other than the number of items
- **THEN** the registry misdescribes itself, and every fraction taken against the
  stated count is over a denominator that does not exist

#### Scenario: an artifact says which registry produced it
- **WHEN** a run writes its payload, its Markdown report or its HTML report
- **THEN** each names the `registry_version` it was graded against
- **AND** an artifact carrying no version cannot be compared with any other, because
  nothing says whether the two measured the same population

### Requirement: REG-2 — the registry is generated, never edited

`checklist.json` SHALL be a build artifact. An item exists because the generator
declares it. The artifact MUST NOT be edited directly, and CI compares the committed
file with a fresh generation byte for byte.

**Why:** a hand edit that survives one release becomes the source of truth for the next
reader and diverges from the code that is supposed to produce it.
**Reader:** enforced. `test_registry_matches_its_generator` plus the `--check` step on
both Linux and Windows.

#### Scenario: an item is added by hand
- **WHEN** a row is written into the artifact that the generator does not produce
- **THEN** the committed file differs from a fresh generation and the build fails
- **AND** the item does not exist, whatever the artifact says

#### Scenario: a field is edited in place
- **WHEN** a severity or a title is changed in the artifact and the generator is left
  alone
- **THEN** the byte comparison fails, because a real change would also have moved
  `registry_version`

#### Scenario: the generator moves and the artifact does not
- **WHEN** the generator is edited and the committed artifact is left stale
- **THEN** the same comparison fails, in the other direction, and the artifact is not
  the registry until it is regenerated

### Requirement: REG-3 — every field is drawn from a closed vocabulary

The values in §2.1 SHALL be exhaustive: every `source`, `severity`, `effort`, `lens` and
`requires` MUST be one of them. A new value is a change to this document first.

**Why:** every consumer switches on these fields. An unknown `source` or `requires`
silently falls through to a default, and the item is then decided by whichever branch
happens to catch it.
**Reader:** partial — enforced for four of the five.
`test_every_item_has_the_required_fields`
asserts membership in `VALID_SEVERITY`, `VALID_SOURCES` and `VALID_EFFORT`, and
`test_script_items_are_fully_specified` asserts it for `VALID_REQUIRES`. An unrecognised
value in any of those four fails today. Only `lens` is unpinned as a vocabulary:
`test_every_llm_item_has_a_lens` requires the field to exist on a model-judged item and
does not constrain what it says. There is no `VALID_LENS` beside the other four sets, and
the four lens names that appear elsewhere in the tests are written as literals rather than
read from the registry, so an item declaring a fifth lens builds, ships and scores. One
vocabulary of five unheld is what puts this requirement in `partial` rather than
`enforced`, by the rule this document applies to REG-1.

#### Scenario: a value outside a vocabulary the tests read
- **WHEN** an item declares a `severity`, `source`, `effort` or `requires` the table in
  §2.1 does not list
- **THEN** the registry is invalid and the build fails

#### Scenario: a lens nobody enumerated
- **WHEN** a model-judged item declares a `lens` the table does not list
- **THEN** the requirement is violated
- **AND** nothing objects: the field is only required to be non-empty, so the item
  builds, ships and scores while belonging to no agent's slice

#### Scenario: an unknown value reaches a consumer
- **WHEN** a consumer switches on one of these fields and meets a value it does not
  enumerate
- **THEN** the item is decided by whichever default branch catches it, which is the
  harm closing the vocabulary exists to prevent

### Requirement: REG-4 — ids are stable, unique, and never re-used

An id names one question for the life of the registry. A retired item's id MUST NOT be
reassigned, and two items MUST NOT share one. Ids are prefixed, and **a prefix SHALL
belong to exactly one category** — though a category may hold more than one prefix, as
`content` holds `CN` and `CONT`, and `technical` holds `TE` and `TECH`.

**Why:** ids travel outside this repository — into declarations, ledgers, archived runs,
and client reports. A re-used id makes every historical reference silently wrong.
**Reader:** partial. `test_ids_unique` pins uniqueness within a build. Nothing compares
ids against previous releases, so a retirement-and-reuse across versions would pass.

#### Scenario: an id is retired and issued to a different question
- **WHEN** an item is removed in one release and its id is given to a new question in a
  later one
- **THEN** the requirement is violated, and every archived run, declaration and client
  report naming that id becomes silently wrong
- **AND** nothing in the tree objects: uniqueness is checked within one build, and no
  gate compares this build's ids against any earlier release's

#### Scenario: two items share an id in one build
- **WHEN** two rows carry the same id
- **THEN** the build fails

#### Scenario: a prefix appears in two categories
- **WHEN** an item is added under an existing prefix and filed in a different category
- **THEN** the requirement is violated, whether or not that category already holds
  another prefix

### Requirement: REG-5 — a borrowed title says so, and a departure says why

Titles taken from the published source checklist SHALL keep their reference number. An
item with no such origin carries a null reference. A title that departs from its source
MUST carry a written reason, and a departure that is not a departure is an error rather
than a no-op.

**Why:** the registry is partly somebody else's work, and the licence and the
traceability both rest on saying which parts. An override equal to the source title
suggests a change nobody made.
**Reader:** enforced. `test_every_numbered_title_is_referenced_by_exactly_one_item`,
`test_every_override_is_explained_shipped_and_differs_from_its_source`, and
`test_the_builder_refuses_all_invalid_override_shapes`, plus the generator's own refusal.

#### Scenario: an override that repeats its source title
- **WHEN** an override declares a title identical to the source checklist's
- **THEN** the build refuses it, because a departure that departs from nothing records
  a change nobody made

#### Scenario: an override with no reason
- **WHEN** an override carries a title and a blank or absent reason
- **THEN** the build refuses it

#### Scenario: an override on an item that borrowed nothing
- **WHEN** an override names an item whose reference is null
- **THEN** the build refuses it: there is no source title to depart from

#### Scenario: the reason on record explains a title nobody reads
- **WHEN** the override file names a title the shipped artifact does not carry
- **THEN** the requirement is violated, because the traceability points at a departure
  that never reached the registry

### Requirement: REG-6 — an item must measure what its title claims

The rule attached to an item SHALL decide the question the title asks. Where the title
names a subject the rule cannot reach, the item is defective — the title must change, or
the rule must, or the item must declare what it actually settles.

**Why:** the title is what the operator reads, what the report prints and what a client
argues with. An item measuring something adjacent gives a true answer to a question
nobody asked, and it is unfalsifiable from the outside: the verdict looks right because
the measurement is right.
**Reader:** partial. `tools/audit_item_semantics.py` in CI asks whether the rule asserts
what the title says, and `test_mb_105_names_the_comparison_it_asserts` pins one item's
wording to its comparison. The audit reads the assertion's shape, not the meaning of the
subject: GO-137 passes it while reconciling against the audit's own crawl rather than the
search-engine index its title names.

#### Scenario: the rule answers an adjacent question
- **WHEN** a title promises a reconciliation against a search engine's index and the
  rule counts orphan pages in the audit's own crawl
- **THEN** the item is defective, and its verdict is a true answer to a question nobody
  asked

#### Scenario: the rule answers a weaker question than the title asks
- **WHEN** a title states a property of the page and the rule asserts only that at
  least one element on the page has it
- **THEN** the item is defective: a page carrying one conforming element among many
  non-conforming ones passes an item that promised the page

#### Scenario: the rule answers half the title
- **WHEN** a title names two subjects joined by "and" and the rule measures one of them
- **THEN** the item is defective
- **AND** recording the shortfall inside a field a gate reads for another purpose is
  not the declaration this requirement asks for

#### Scenario: the word heuristic is satisfied and the item still misdescribes itself
- **WHEN** the title and the rule share their words while naming different subjects
- **THEN** the CI audit passes and the defect stands, because that audit reads the
  assertion's shape rather than the meaning of the subject

### Requirement: REG-7 — the assertion language is closed, and every operator in it is specified

A rule SHALL be a path, **exactly one** operator, and optionally a field and a
`missing_is`.
`assert`, `warn` and `applies_when` are all rules in this sense: one vocabulary, one
evaluator, one test policing which operators may be named. A count of operator usage
that reads only `assert` undercounts the language, and Appendix A.4 made that mistake.
A rule MUST NOT carry two operators: they are an error, not a conjunction, because the
evaluator applies the first branch that matches and the second is silently discarded, so
the rule means whichever the implementation happens to check first. Operators are
enumerated in this document. An operator the language implements but no item uses is
either specified here or removed from the language.

**Why:** the first item written against an unused operator inherits whatever semantics
were never defended. Two of the four unused ones are already surprising: one inspects
only the first matched text, the other stringifies its value before matching.
**Reader:** partial, and thinner than it looks. `test_a_rule_does_more_than_name_a_path`
requires *at least* one operator and `test_assert_rules_use_operators_the_runner_implements`
forbids naming one the runner lacks. Neither forbids **two**: a rule carrying two
operators passes both and is then decided by branch order. No item does this today, which
is why nothing has caught it. Nothing forbids the language from carrying an operator no
item uses and no document describes.

#### Scenario: a rule naming two operators
- **WHEN** one rule carries two operators, such as `eq` beside `gte`
- **THEN** the requirement is violated
- **AND** the evaluator takes whichever branch it reaches first and discards the other
  in silence, so the rule means what the implementation's branch order says
- **AND** nothing objects: one test requires at least one operator and another forbids
  naming one the evaluator lacks, and neither forbids two

#### Scenario: a rule naming an operator the evaluator does not implement
- **WHEN** a rule names a key no branch of the evaluator reads
- **THEN** the rule decides nothing and the item is undecided on every site it is ever
  run against

#### Scenario: an operator no item uses and no section describes
- **WHEN** the evaluator implements an operator that appears in no rule and in no part
  of this document
- **THEN** the requirement is violated: it is specified here or removed from the
  language, and the first item written against it must not inherit semantics nobody
  defended

#### Scenario: the language is counted over `assert` alone
- **WHEN** operator usage is counted without reading `warn` and `applies_when`
- **THEN** the count describes a smaller language than the evaluator implements, and an
  operator in live use reads as unused and removable

### Requirement: REG-8 — absence of data is not a verdict

A rule that finds no value at its path SHALL be undecided. It MUST NOT be read as a
verdict unless the item declares otherwise — `missing_is: pass | fail` — and that
declaration is permitted only where the absence of the field is itself the answer.

**Why:** a parser that never emits a key must not be read as the site being clean. This
is the field-level half of VRD-3, and the declaration is what separates "the site has no
such thing" from "the checker did not look".
**Reader:** partial. `test_a_rule_does_more_than_name_a_path` forbids a bare path, and
the evaluator's tri-state is well covered in the runner tests. Nothing audits whether a
given `missing_is` is *justified* for its item.

#### Scenario: the checker never emitted the key
- **WHEN** a rule resolves its path to nothing and the item declares no `missing_is`
- **THEN** the item is undecided, and the parser's silence is not read as the site
  being clean

#### Scenario: absence declared a pass without warrant
- **WHEN** an item declares `missing_is: pass` for a field whose absence means the
  checker did not look rather than that the site is clean
- **THEN** the requirement is violated, and nothing in the tree says so: the
  declaration's presence is read, its justification is not

#### Scenario: a rule that only names a path
- **WHEN** a rule carries a path and no operator
- **THEN** it can decide nothing at all, and the build refuses it

### Requirement: REG-9 — an item judging an optional entity declares its applicability

> **This requirement's reader is aimed against it.** See the Reader line: satisfying
> REG-9 makes an existing test fail. It is counted separately in Appendix B for that
> reason — an unread requirement is merely unprotected, while this one is opposed.

Where an item judges the quality of something a site may legitimately not have, the item
SHALL declare the condition under which it applies. Absent that declaration, the item
reports success on a site that has none of the thing, which VRD-2 forbids.

**Why:** this is the largest measured defect class in the registry — seventeen items owe
such a declaration and two carry one.
**Reader:** opposed. `test_video_applicability_is_narrowly_declared`
pins the declaration set to exactly MB-102 and MD-190 with exactly their condition — so
**satisfying this requirement breaks that test**. Adding the declaration CI-016 owes makes
it fail. That is the correct behaviour for a test that describes the present and the wrong
shape for one that guards a rule: the release closing this debt must turn it from a fixed
membership list into a rule about what a declaration may say. Nothing identifies an item
that owes one, which is why the seventeen are visible only through a hand sweep.

#### Scenario: an item owing a declaration and carrying none
- **WHEN** an item's rule passes by finding none of the thing it forbids, and the
  entity whose quality it judges may legitimately be absent from a site
- **THEN** the item declares the condition under which it applies
- **AND** without that declaration it awards a quality verdict to a site that has none
  of the thing, which is the defect this requirement names

#### Scenario: the declaration is added and the suite reddens
- **WHEN** an applicability condition is added to an item that owes one
- **THEN** the requirement is better satisfied than it was
- **AND** an existing test fails, because it pins the declaration set to a fixed
  membership rather than to a rule about what a declaration may say — which makes the
  test wrong and the addition right

#### Scenario: the item owing a declaration has no `check`
- **WHEN** an item judging an optional entity is answered by a person or a model and
  therefore carries no rule
- **THEN** it still owes the declaration
- **AND** the only mechanism sits inside the rule, so the debt cannot be paid: that is
  a schema gap, not a licence to omit it

#### Scenario: a new item quietly joins the debt
- **WHEN** an item judging an optional entity is added with no condition
- **THEN** the registry accepts it and every gate stays green, because nothing
  identifies which items owe one

### Requirement: REG-10 — a rule that cannot fail is proved, not asserted

An item whose rule can never produce `FAIL` MUST say so and name the mechanism, and the
claim MUST be provable from the checker's source. A proved-but-undeclared rule, a
declared-but-unprovable one, and a declaration naming the wrong mechanism are all errors.

**Why:** an unfailable rule scores a pass on every site forever. Making the claim
explicit turns an invisible defect into a recorded decision.
**Reader:** enforced. `tools/audit_reachability.py` in CI checks all three directions,
and `tests/test_reachability.py` covers the mechanism vocabulary.

#### Scenario: a field written only when it would pass
- **WHEN** a checker writes the field a rule asserts only when that field already holds
  a value the rule accepts
- **THEN** the rule reports a pass or nothing at all, never a failure
- **AND** the item must declare that and name the mechanism, or the build fails

#### Scenario: a declaration that outlived its reason
- **WHEN** a checker changes so that a declared rule can fail again
- **THEN** the declaration is an error and the build fails, rather than sitting inert
  while every entry in it still looks true

#### Scenario: the right conclusion under the wrong mechanism
- **WHEN** a rule still cannot fail, but for a reason other than the one declared
- **THEN** it is an error, because the recorded reason is what the next editor checks
  the code against

#### Scenario: a failing severity the registry's own arguments never reach
- **WHEN** a checker grades a finding at a failing severity inside a branch the
  registry's invocation of that checker does not enter
- **THEN** the rule still cannot fail, and the requirement is violated
- **AND** the proof tool falls silent, because it reads the literal in the source
  rather than whether the line is reachable from the arguments the registry passes

### Requirement: REG-11 — two items sharing one check are ruled on, not left to chance

Where two items resolve to the same script, arguments and assertion, the registry SHALL
record a human ruling: which one carries the weight and why. The survivor MUST NOT be
the weaker of the two.

**Why:** an unruled duplicate doubles a single defect's pull on the headline and makes
the weight depend on which item a reader looks at.
**Reader:** enforced. `test_no_group_sharing_one_check_is_left_unruled`,
`test_a_twin_shares_its_primary_s_check_exactly`,
`test_the_item_that_carries_the_weight_carries_it`,
`test_the_survivor_is_never_the_weaker_of_the_two`, and `audit_item_semantics.py` in CI.

#### Scenario: a new item silently duplicates an existing check
- **WHEN** two items name the same script, the same arguments and the same assertion,
  and neither defers to the other
- **THEN** the build fails and names the pair, because one defect would otherwise pull
  twice on the headline

#### Scenario: the weight is left with the weaker of the two
- **WHEN** the item carrying the weight is the lower-severity member of the pair
- **THEN** the requirement is violated: the registry's own weighting of one defect
  would depend on which id was typed first

#### Scenario: a twin pointing at a twin
- **WHEN** a deferring item names a primary that itself defers
- **THEN** nothing in the group carries weight, the score says nothing about it, and
  the build fails

#### Scenario: the ruling records which and not why
- **WHEN** the registry carries the pointer and the reason for it lives only in the
  generator's comments
- **THEN** the ruling is incomplete: this requirement asks the registry to record which
  one carries the weight *and why*, and a reason that does not reach the artifact
  cannot be read by anyone working from it

### Requirement: REG-12 — the registry may not state anything about itself that nothing checks

Fields describing the registry's own composition, provenance or size SHALL be derived
from the items, and MUST NOT be written as literals in the generator. A literal is
reproduced faithfully by the staleness check and compared with nothing.

**Why:** the staleness mechanism cannot see a lie that lives in the generator. This is
how `source` came to claim a composition that has been wrong for releases while CI stayed
green, and it is the same shape as three other drifted counts in this tree.
**Reader:** enforced.
`tests/test_registry.py::TheRegistryStatesNothingAboutItselfItCannotProve` does both
halves. It recomputes every self-describing field from the items — the item count, both
numbers inside `source`, the category set with its prefixes, and the version stamp as a
fresh hash — which catches a wrong value; and it parses the generator's `payload`
literal and refuses a string constant carrying a digit, which catches the shape that
made the wrong value invisible. The second is the requirement: a value that is right
today and read by nothing is the state this document is about. `version` is exempt and
named as exempt, because a schema number is a fact about the file format rather than
about the items.

#### Scenario: a composition claim written as a literal
- **WHEN** a field describing the registry's own composition is a constant in the
  generator rather than a value computed from the items
- **THEN** the requirement is violated
- **AND** the staleness check cannot see it, because the only comparison in force is
  between the generator and its own output

#### Scenario: the literal and the items disagree
- **WHEN** the items say one thing about their own provenance and the literal beside
  them says another
- **THEN** every gate stays green, because the only comparison in force is between the
  generator and its own output — which is why this is forbidden rather than audited

#### Scenario: a size claim that can be recomputed
- **WHEN** the stated item count is computed from the list at generation time
- **THEN** the requirement is satisfied for that field, because a later reader can
  recompute it and find the disagreement

### Requirement: REG-13 — effort and severity are claims about the item, not about a run

`severity` states how much the question matters; `effort` states what answering the
finding costs the site owner. Neither is a property of a run: both values MUST NOT
change with the mode, the profile, the reach, or the verdict the item receives.

**Why:** both feed the score and the fix order, and a value that moves with the run makes
two audits of the same site incomparable for reasons that have nothing to do with the
site.
**Reader:** partial. `test_manual_and_llm_items_are_never_low_effort` and
`test_every_registry_item_declares_an_effort` pin presence and one floor;
`test_effort_survives_grading` pins that grading does not alter it. Nothing forbids a
profile from carrying a severity override, which is currently possible only because no
profile does it.

#### Scenario: a profile carries a severity of its own
- **WHEN** a profile declares a severity or an effort for an item it does not exclude
- **THEN** the requirement is violated
- **AND** nothing refuses it: a profile is validated for the keys it uses, not closed
  against the ones it must not carry

#### Scenario: the graded row loses the field
- **WHEN** a row is built from a registry item for the report
- **THEN** it carries that item's own `effort` and `severity`
- **AND** a row that drops one of them makes the fix list rank on the other alone while
  still claiming to weigh the two against each other

#### Scenario: two audits of one site under two profiles
- **WHEN** the same item is graded twice, in two modes or under two profiles
- **THEN** its severity and effort are identical in both, so the two runs differ only
  by what was measured

## 4. Invariants

* **INV-R1** — `item_count` equals the number of items, and `registry_version` changes
  if and only if an item changes. *Reader: partial* — `test_registry_is_versioned` pins
  the count and the field's presence; the *if and only if* is held by REG-2's byte
  comparison, not by any reader of this invariant. It read `enforced` while REG-1 called
  the same fact `partial`, which is one document giving one fact two verdicts two
  sections apart.
* **INV-R2** — every script an item names exists, and every script the registry runs is
  described in the output-shape contract. *Reader: enforced —
  `test_every_referenced_script_exists`, `test_every_script_the_registry_runs_is_documented`.*
* **INV-R3** — no item is both `scores_with` and a primary for another item.
  *Reader: partial* — `test_the_item_that_carries_the_weight_carries_it` and
  `test_no_group_sharing_one_check_is_left_unruled` together forbid the chain in
  practice, without asserting the invariant in that form.
* **INV-R4** — every item is answerable in principle by its declared `source`: a
  `script` item names a script, an `llm` item names a lens, a `manual` item names
  neither. *Reader: partial — the positive halves are pinned, the negative ones are not.*

## 5. What this document does not decide

* what each of the 58 checkers emits and what its thresholds rest on — `openspec/specs/evidence/`;
* how a run turns `requires` into capability gating — `openspec/specs/run-lifecycle/`;
* how declarations of expected verdicts are written against the registry —
  `openspec/specs/declarations/`;
* which severity or effort a *particular* item deserves. This document requires the
  fields to be stable and closed; it does not adjudicate their values, and no calibration
  exists that would.

## 6. Open questions

**Where does an applicability condition live for an item with no `check`?** REG-9 obliges
an item judging an optional entity to declare its boundary, and the only mechanism sits
inside `check`. An item whose source is `manual` or `llm` has nowhere to put it. What
would settle it: deciding whether applicability is a property of the rule or of the item.

**Should the unused operators be removed or specified?** REG-7 permits either. Removing
them is cheaper and narrows the language; specifying them keeps a door open that nobody
has asked for. What would settle it: whether any pending item needs a comparison the
current set cannot express.

**Is a prefix a category or a generation?** `CONT`, `TECH` and `GEO` mark items added
beyond the source checklist rather than a distinct subject. Today they read as both.
What would settle it: deciding whether provenance belongs in the id at all, given that
`plerdy_ref` already carries it.

## Appendix A — measured disagreements, 26 August 2026

Observation, not specification. Measured at commit `11e3899`, registry `b0abf2819da0`.
A.4 was re-measured on 29 August 2026 at commit `2a5b549` over the same registry version
and corrected; the rest stands as first measured, and the distributions in §2.1 were
re-derived from the artifact on the same day and agree.

#### A.1 — the registry misstated its own composition

Closed in 0.93.1. `source` read *"Plerdy SEO Checklist (200) + 15 beyond-Plerdy
checks"*. Measured: **17** items carry a null `plerdy_ref`. The operator protocol said
17; the titles file's own note said 14; `CREDITS.md` said 14. Four statements of one
fact in three values, and the one inside the registry was a literal in the generator, so
the staleness check reproduced it and CI stayed green.

`source` is now computed from the items. The other three are held by
`tests/test_protocol_counts.py`, which derives the split and reads it out of each
sentence — the same ledger that holds the queue sizes, extended rather than duplicated.

Found while writing the reader, and left as it is: four ids carry a prefix their
category does not declare — `TECH-001` through `TECH-003` in `technical`, which declares
`TE`, and `CONT-001` in `content`, which declares `CN`. All four are added items, which
choose their own id; a borrowed item's id is generated from the declared prefix and
cannot drift. Renaming them would move the contract every archived run, the census, the
defect ledger and the playbooks name, to tidy a label used only as a section heading in
the notebook export. The four are enumerated in the reader instead, so a fifth cannot
appear unnoticed.

#### A.2 — seventeen items owe an applicability declaration; two carry one

CI-016, CN-034, CN-035, CN-054, MS-032, BL-081, MB-098, MB-103, MB-108, AR-146, AR-154,
AR-163, GO-143, TE-172, TE-174, MD-185, MD-186. The declared two are MB-102 and MD-190.

A further item, CN-036, cannot be classified either way: its assertion counts elements
carrying inline colour syntax rather than contrast violations, so zero does not
distinguish "no violation" from "no text". That is a REG-6 defect, not a REG-9 one.

#### A.3 — nine items measure something other than their title

A sample of twenty items, read rule against title, found nine mismatches. They are not
one defect: three kinds sit here, and only the first is a wrong answer.

**The rule answers a different question.**

| item | title promises | rule measures |
|---|---|---|
| GO-137 | reconciliation against a search engine's index | orphan pages in the audit's own crawl |
| CN-036 | sufficient text contrast | count of elements carrying inline colour syntax |
| SP-112 | Core Web Vitals *in Search Console* | field data from the PageSpeed API — the identical rule to SP-108 |

**The rule answers a weaker question than the title asks.**

| item | title promises | rule measures |
|---|---|---|
| CI-016, MD-186 | *meaningful* alt text | that no `alt` attribute is missing |
| MB-096 | responsive images, as a property of the page | that at least one responsive image exists |
| MB-097 | optimised formats and compression | that at least one modern-format image exists |

A page carrying a hundred images, one of them responsive and ninety-nine not, satisfies
MB-096. Alt text reading `image1.jpg` satisfies CI-016.

**The rule answers half the title.**

| item | title promises | rule measures |
|---|---|---|
| MD-189 | modern formats **and** responsive images | responsive images only |
| TE-179 | domain history **and** reputation | whois age ≥ 90 days |

TE-179 is the instructive one. Its `cannot_fail` declaration states in its own words that
release 0.44.0 "gave this item the domain-history half of its title through whois age".
The tree therefore records the REG-6 defect at the site of the defect, in a field a CI
gate reads for a different purpose entirely — and nothing reads it as the admission it is.

**Not defects, though an earlier reading suspected them:** AR-146, AR-154 and AR-163 do
measure what their titles ask. Their problem is applicability (REG-9), not aboutness, and
conflating the two would have sent the repair to the wrong place.

#### A.4 — four operators are implemented and unused

`ne`, `between`, `contains`, `matches`. No item uses any of them. `contains`
inspects only the first matched text and `matches` stringifies its value before matching
— semantics no item has had to defend.

`gt` reads as a fifth and is not one. MB-102 and MD-190 use it, in their `applies_when`
conditions rather than in an `assert` — the same vocabulary, the same evaluator, the same
test. Removing it as unused would take with it the only two applicability declarations in
the registry, which is the thing REG-9 wants seventeen more of. The count was taken over
`assert` blocks alone, which is why it read five; REG-7 now says what a rule is so the
next count is taken over all three.

## Appendix B — how much of this document is enforced

| | requirements |
|---|---|
| **enforced** | REG-2, REG-5, REG-10, REG-11, REG-12 |
| **partial** | REG-1, REG-3, REG-4, REG-6, REG-7, REG-8, REG-13 |
| **none** | — none |
| **opposed** | REG-9 |

Invariants: INV-R2 enforced; INV-R1, INV-R3 and INV-R4 partial.

**Five enforced, seven partial, none unread, one opposed, of thirteen.**

`opposed` is a fourth category this document introduces, and it earns its place: REG-9's
reader does not merely fail to protect the requirement, it fires when the requirement is
met. A fixed-membership test pinning the two existing applicability declarations makes
the seventeen owed ones impossible to add without changing it. An unread requirement is
unprotected; an opposed one is barricaded, and the distinction changes what the closing
release has to do first.

An earlier draft called this the best-governed capability in the suite, and the census
does not support it: `verdicts/` has nine of seventeen enforced against four of thirteen
here. What is distinctive about this document is not its coverage but the shape of what
remains, and the shape is consistent: the readers cover *structure* — that a field
exists, that a value is in a vocabulary, that a script exists, that a duplicate is ruled
on — and stop at *meaning*.
Nothing checks that an item measures its title, that an applicability declaration is
owed, or that the registry's account of itself is true. Nine items answer a question
other than the one they name, and every gate stays green.
