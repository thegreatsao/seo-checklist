# Registry — what an item is, and what it is allowed to claim

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
[`specs/verdicts/`](../verdicts/spec.md); how weight and the fix order are computed
belong to [`specs/scoring/`](../scoring/spec.md). This document says what an item *is*,
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

## 3. Requirements

### REG-1 — the registry is the denominator, and it is versioned by content

The registry is a fixed list with a stated count and a `registry_version` derived from
the items themselves. Every artifact computed from it carries that version.

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

### REG-2 — the registry is generated, never edited

`checklist.json` is a build artifact. An item exists because the generator declares it.
Editing the artifact directly is forbidden, and CI compares the committed file with a
fresh generation byte for byte.

**Why:** a hand edit that survives one release becomes the source of truth for the next
reader and diverges from the code that is supposed to produce it.
**Reader:** enforced. `test_registry_matches_its_generator` plus the `--check` step on
both Linux and Windows.

### REG-3 — every field is drawn from a closed vocabulary

The values in §2.1 are exhaustive. A new value is a change to this document first.

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

### REG-4 — ids are stable, unique, and never re-used

An id names one question for the life of the registry. A retired item's id is not
reassigned. Ids are prefixed, and **a prefix belongs to exactly one category** — though
a category may hold more than one prefix, as `content` holds `CN` and `CONT`, and
`technical` holds `TE` and `TECH`.

**Why:** ids travel outside this repository — into declarations, ledgers, archived runs,
and client reports. A re-used id makes every historical reference silently wrong.
**Reader:** partial. `test_ids_unique` pins uniqueness within a build. Nothing compares
ids against previous releases, so a retirement-and-reuse across versions would pass.

### REG-5 — a borrowed title says so, and a departure says why

Titles taken from the published source checklist keep their reference number. An item
with no such origin carries a null reference. A title that departs from its source
carries a written reason, and a departure that is not a departure is an error rather
than a no-op.

**Why:** the registry is partly somebody else's work, and the licence and the
traceability both rest on saying which parts. An override equal to the source title
suggests a change nobody made.
**Reader:** enforced. `test_every_numbered_title_is_referenced_by_exactly_one_item`,
`test_every_override_is_explained_shipped_and_differs_from_its_source`, and
`test_the_builder_refuses_all_invalid_override_shapes`, plus the generator's own refusal.

### REG-6 — an item must measure what its title claims

The rule attached to an item decides the question the title asks. Where the title names
a subject the rule cannot reach, the item is defective — the title must change, or the
rule must, or the item must declare what it actually settles.

**Why:** the title is what the operator reads, what the report prints and what a client
argues with. An item measuring something adjacent gives a true answer to a question
nobody asked, and it is unfalsifiable from the outside: the verdict looks right because
the measurement is right.
**Reader:** partial. `tools/audit_item_semantics.py` in CI asks whether the rule asserts
what the title says, and `test_mb_105_names_the_comparison_it_asserts` pins one item's
wording to its comparison. The audit reads the assertion's shape, not the meaning of the
subject: GO-137 passes it while reconciling against the audit's own crawl rather than the
search-engine index its title names.

### REG-7 — the assertion language is closed, and every operator in it is specified

A rule is a path, **exactly one** operator, and optionally a field and a `missing_is`.
`assert`, `warn` and `applies_when` are all rules in this sense: one vocabulary, one
evaluator, one test policing which operators may be named. A count of operator usage
that reads only `assert` undercounts the language, and Appendix A.4 made that mistake.
Two operators in one rule are an error, not a conjunction: the evaluator applies the
first branch that matches and the second is silently discarded, so the rule means
whichever the implementation happens to check first. Operators are enumerated in this
document. An operator the language implements but no item uses is either specified here
or removed from the language.

**Why:** the first item written against an unused operator inherits whatever semantics
were never defended. Two of the four unused ones are already surprising: one inspects
only the first matched text, the other stringifies its value before matching.
**Reader:** partial, and thinner than it looks. `test_a_rule_does_more_than_name_a_path`
requires *at least* one operator and `test_assert_rules_use_operators_the_runner_implements`
forbids naming one the runner lacks. Neither forbids **two**: a rule carrying two
operators passes both and is then decided by branch order. No item does this today, which
is why nothing has caught it. Nothing forbids the language from carrying an operator no
item uses and no document describes.

### REG-8 — absence of data is not a verdict

A rule that finds no value at its path is undecided. It may be declared otherwise —
`missing_is: pass | fail` — only where the absence of the field is itself the answer.

**Why:** a parser that never emits a key must not be read as the site being clean. This
is the field-level half of VRD-3, and the declaration is what separates "the site has no
such thing" from "the checker did not look".
**Reader:** partial. `test_a_rule_does_more_than_name_a_path` forbids a bare path, and
the evaluator's tri-state is well covered in the runner tests. Nothing audits whether a
given `missing_is` is *justified* for its item.

### REG-9 — an item judging an optional entity declares its applicability

> **This requirement's reader is aimed against it.** See the Reader line: satisfying
> REG-9 makes an existing test fail. It is counted separately in Appendix B for that
> reason — an unread requirement is merely unprotected, while this one is opposed.

Where an item judges the quality of something a site may legitimately not have, the item
declares the condition under which it applies. Absent that declaration, the item reports
success on a site that has none of the thing, which VRD-2 forbids.

**Why:** this is the largest measured defect class in the registry — seventeen items owe
such a declaration and two carry one.
**Reader:** opposed. `test_video_applicability_is_narrowly_declared`
pins the declaration set to exactly MB-102 and MD-190 with exactly their condition — so
**satisfying this requirement breaks that test**. Adding the declaration CI-016 owes makes
it fail. That is the correct behaviour for a test that describes the present and the wrong
shape for one that guards a rule: the release closing this debt must turn it from a fixed
membership list into a rule about what a declaration may say. Nothing identifies an item
that owes one, which is why the seventeen are visible only through a hand sweep.

### REG-10 — a rule that cannot fail is proved, not asserted

An item whose rule can never produce `FAIL` must say so and name the mechanism, and the
claim must be provable from the checker's source. A proved-but-undeclared rule, a
declared-but-unprovable one, and a declaration naming the wrong mechanism are all errors.

**Why:** an unfailable rule scores a pass on every site forever. Making the claim
explicit turns an invisible defect into a recorded decision.
**Reader:** enforced. `tools/audit_reachability.py` in CI checks all three directions,
and `tests/test_reachability.py` covers the mechanism vocabulary.

### REG-11 — two items sharing one check are ruled on, not left to chance

Where two items resolve to the same script, arguments and assertion, the registry records
a human ruling: which one carries the weight and why. The survivor is never the weaker of
the two.

**Why:** an unruled duplicate doubles a single defect's pull on the headline and makes
the weight depend on which item a reader looks at.
**Reader:** enforced. `test_no_group_sharing_one_check_is_left_unruled`,
`test_a_twin_shares_its_primary_s_check_exactly`,
`test_the_item_that_carries_the_weight_carries_it`,
`test_the_survivor_is_never_the_weaker_of_the_two`, and `audit_item_semantics.py` in CI.

### REG-12 — the registry may not state anything about itself that nothing checks

Fields describing the registry's own composition, provenance or size are derived from
the items, never written as literals in the generator. A literal is reproduced faithfully
by the staleness check and compared with nothing.

**Why:** the staleness mechanism cannot see a lie that lives in the generator. This is
how `source` came to claim a composition that has been wrong for releases while CI stayed
green, and it is the same shape as three other drifted counts in this tree.
**Reader:** **none.** No test reads `source`. This requirement is the remedy for
Appendix A.1 and is not implemented.

### REG-13 — effort and severity are claims about the item, not about a run

`severity` states how much the question matters; `effort` states what answering the
finding costs the site owner. Neither may vary by run, mode, profile or verdict.

**Why:** both feed the score and the fix order, and a value that moves with the run makes
two audits of the same site incomparable for reasons that have nothing to do with the
site.
**Reader:** partial. `test_manual_and_llm_items_are_never_low_effort` and
`test_every_registry_item_declares_an_effort` pin presence and one floor;
`test_effort_survives_grading` pins that grading does not alter it. Nothing forbids a
profile from carrying a severity override, which is currently possible only because no
profile does it.

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

* what each of the 58 checkers emits and what its thresholds rest on — `specs/evidence/`;
* how a run turns `requires` into capability gating — `specs/run-lifecycle/`;
* how declarations of expected verdicts are written against the registry —
  `specs/declarations/`;
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

### A.1 — the registry misstates its own composition

`source` reads *"Plerdy SEO Checklist (200) + 15 beyond-Plerdy checks"*. Measured: **17**
items carry a null `plerdy_ref`. The operator protocol says 17; the titles file's own
note says 14. Three numbers for one fact, and the one inside the registry is a literal in
the generator, so the staleness check reproduces it and CI stays green. This is REG-12's
violation and the reason that requirement exists.

### A.2 — seventeen items owe an applicability declaration; two carry one

CI-016, CN-034, CN-035, CN-054, MS-032, BL-081, MB-098, MB-103, MB-108, AR-146, AR-154,
AR-163, GO-143, TE-172, TE-174, MD-185, MD-186. The declared two are MB-102 and MD-190.

A further item, CN-036, cannot be classified either way: its assertion counts elements
carrying inline colour syntax rather than contrast violations, so zero does not
distinguish "no violation" from "no text". That is a REG-6 defect, not a REG-9 one.

### A.3 — nine items measure something other than their title

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

### A.4 — four operators are implemented and unused

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
| **enforced** | REG-2, REG-5, REG-10, REG-11 |
| **partial** | REG-1, REG-3, REG-4, REG-6, REG-7, REG-8, REG-13 |
| **none** | REG-12 |
| **opposed** | REG-9 |

Invariants: INV-R2 enforced; INV-R1, INV-R3 and INV-R4 partial.

**Four enforced, seven partial, one unread, one opposed, of thirteen.**

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
