# Declarations — what a served tree is expected to answer, and what a recording may claim

## Purpose

The two instruments that measure this repository's own checks against trees it serves
itself: a manifest of expected verdicts, written in advance of any run, and a census of
what every item actually answered on every tree there is — C40 and C41 of the capability
inventory.

A prediction and a recording look identical in a file and are worth opposite things. The
manifest is the only artifact here that can be *wrong about the code*, which is the only
kind of artifact that can catch the code being wrong; the census cannot be wrong and can
only be stale, and its value is the range of answers it collects. This document exists to
stop the two being confused, because every way of confusing them spends the manifest and
none of them costs the census anything.

**Capability:** the two instruments that measure this repository's own checks against
trees it serves itself — the fixture corpus with its manifest of expected verdicts, and
the verdict census over every tree there is (C40, C41 of the capability inventory).

This document is normative and is written as though no code existed. Where the
implementation disagrees, the implementation is presumed wrong until this document is
changed by argument. Appendix A records disagreements measured on 29 August 2026.

Every requirement carries a **Reader** line naming what makes it fail when violated;
Appendix B is the census of those lines. A requirement whose reader is `none` is an
intention, and is counted as one.

**Inherited, not restated:** the eight statuses, what each means and who each names,
belong to [`openspec/specs/verdicts/`](../verdicts/spec.md); what an item is and what its rule may
claim belong to [`openspec/specs/registry/`](../registry/spec.md). This document says what may be
*asserted in advance* about a served tree and what may be *recorded* about one, and it
must not redefine a status to make either easier.

---

## 1. Two instruments, and why they are one document

The manifest and the census both audit trees this repository serves over loopback, by the
same runner, with the same flags. They differ in what they are for, and confusing them is
the failure this document exists to prevent.

A **declaration** is a prediction. Somebody read an item's title, read how the fixture was
built, and wrote down what the audit ought to say — before running it. It can be wrong,
and when it disagrees with the run somebody has to decide which side is wrong. That is its
entire value: it is the only thing in this tree that can catch a checker that is
confidently, consistently, reproducibly wrong. Every other gate here asks whether the code
does what the code does.

A **census** is a recording. It runs every item on every tree and writes down what came
back. It predicts nothing and cannot be wrong; it can only be stale. Its value is the
*range*: an item that answered one way on every tree anybody has served is either a rule
that cannot answer differently or a question every site answers alike, and those two are
worth telling apart.

The distinction is not academic, because the failure mode runs one way. A declaration
written from a recording is not worthless — it still pins today's behaviour, so a checker
that changes later will disagree with it. What it cannot do is the one thing the manifest
exists for: it is no evidence that the prediction was right *when it was made*, and none
that the checker is right now, because it was copied from the thing it is supposed to
judge. And it looks identical to one written before the run — the file is the same either
way, and git records the commit, not the reasoning. This tree has already paid for that
once: three declarations were withdrawn and re-declared by a later session because the
first had read the answers, and five crawl items were deliberately left undeclared for the
same reason. So the rules below are asymmetric. A census may be re-recorded freely; a
declaration may not be written by anyone who has seen what it predicts.

They belong in one document for two reasons. The weaker one is that they are read against
each other — the census says what the corpus provoked, the manifest what was expected, and
Appendix A.1 is the gap between them rather than either number. The stronger is that the
two defects worth a normative document at all, DEC-2 and DEC-3, are about a *vocabulary*
that both instruments spend: split them apart and those requirements would have to live in
one half while being about both.

## 2. What each artifact is

### 2.1 A declaration

One prediction, for one item, on one served origin. It carries:

* `expect` — a status from the audit's vocabulary;
* `why` — the argument from the fixture's construction that produces that status.

Declarations are grouped by origin. Four origins are served: `good` and `broken` over
HTTP, `good_tls` and `broken_tls` over TLS. The manifest states the `schema_version`, the
`registry_version` it was declared against, and `declared_from`, a sentence naming its own
provenance.

### 2.2 A census row

One row per registry item, carrying the answer each served tree gave, the sorted set of
distinct answers, and four fields copied from the registry — title, severity, source,
script — so the row can be read beside the registry it came from, and so an archived row
can be read at all. The record states the `registry_version`, the `item_count` and the
list of sites.

### 2.3 The trees

| tree | served as | declarations | why it exists |
|---|---|---|---|
| `fixtures/good` | HTTP + TLS | yes | a site built to satisfy the checks |
| `fixtures/broken` | HTTP + TLS | yes | a site built to violate them |
| `corpus/failing-shapes` | HTTP | **no** | shapes transcribed from real pages, words invented |

The corpus carries no declarations on purpose, and DEC-14 says why.

## Requirements

### Requirement: DEC-1 — a declaration is written before the run, and never from a recording of one

The prediction SHALL precede the measurement, and a declaration MUST NOT be written from
a recording of one. This binds every source of the answer, not only the audit: a census
row, a printed tally, a triage note and a previous session's transcript are all
recordings, and a declaration written from any of them predicts nothing.

Where a session has already seen an item's answer on an origin, that session does not
declare it. It leaves the item undeclared and says so, and a later session that has not
seen it declares it.

**Blindness is a property of inputs, and is evidenced by enumerating them.** A session
qualifies to declare an item when the material it was given can be listed and that list
does not contain the answer: the fixture tree, the item's title and rule, and nothing
derived from a run of it. So the obligation is discharged by *arranging* a declaring
session rather than by attesting to a state of mind — hand a fresh executor the tree and
the titles, withhold the results, the census record and this document's Appendix A, and
require the declarations in its reply. The batch records what it was given. That is what
made the two withheld batches of Stage 2b and 2c sufficient, and it is why "nobody
available has stayed blind" is a scheduling problem rather than a reason to declare
anyway.

**Why:** the manifest is this repository's only instrument that can be wrong about the
code, which is the only kind of instrument that can catch the code being wrong. A
declaration copied from a run cannot disagree with it, so it converts the one falsifiable
artifact here into a second copy of the output. It is not thereby useless — it still
detects a checker that changes later — but a regression pin is not an oracle, and the two
are indistinguishable in the file. The cost is invisible afterwards: the commit proves
when a declaration was written, never from what.
**Reader:** **none**, and unenforceable in principle. `test_metadata_matches_the_registry`
pins the sentence `declared_from: "item title plus fixture construction; never from a
run"`, which stops the *claim* being changed quietly and says nothing about whether it is
true. That is a literal compared with a literal — the shape REG-12 forbids the registry —
and it is the honest limit here rather than a defect to fix: no test can read a mind. What
protects this requirement is that people record when they withheld a declaration and why,
which the id ledger already does in prose. See Appendix A.7, which spends some of it.

#### Scenario: the answer was seen before the prediction was written
- **WHEN** a session has already read what an item answers on an origin — from a run,
  from `tests/census.json`, from a printed tally, from a triage note, or from an earlier
  session's transcript
- **THEN** that session leaves the item undeclared on that origin and records that it
  withheld it and why
- **AND** it does not declare the item, whatever argument it could now construct

#### Scenario: a declaration copied from a recording
- **WHEN** a declaration's `expect` is taken from what the audit answered rather than
  from the item's title and the fixture's construction
- **THEN** the declaration violates this requirement, whatever value it holds
- **AND** the file cannot show the difference, which is why the obligation binds the
  session that wrote it rather than the artifact

#### Scenario: a blind session is arranged
- **WHEN** a fresh executor is handed the fixture tree and the item titles, and the run
  results, the census record and this document's Appendix A are withheld
- **THEN** its declarations satisfy this requirement, and the batch records the list of
  what it was given

#### Scenario: nobody blind is available
- **WHEN** every session that could declare an item has already seen that item's answer
- **THEN** the item stays undeclared
- **AND** the shortage is a scheduling problem, never a reason to declare it anyway

### Requirement: DEC-2 — "no expectation" is the absence of a declaration, not a word in the status field

An item nobody is prepared to predict on an origin SHALL carry **no declaration** for
that origin, and MUST NOT be declared with a word meaning "cannot tell". The status field
holds a prediction about the site; "no prediction exists" is a fact about the manifest,
and the two must not share a field.

**Why:** this is VRD-12's field-level half, and it has already cost fifty-five releases.
A word that only one layer knows cannot be compared with anything, so the comparison that
was meant to read it skips it — and a skipped comparison is indistinguishable from a
passing one. Twenty-seven declarations have been carried, printed in a tally and reported
as coverage while being compared with nothing at all.
**Reader:** **opposed.** `ALLOWED` in `test_fixture_oracle.py` is
`{PASS, WARN, FAIL, N/A, INDETERMINATE}`, and
`test_every_declaration_has_a_supported_verdict_and_reason` asserts membership in it. The
ninth word is therefore *permitted* by the reader, which on its own would make this
requirement unread. What makes it opposed is the other half: two of the statuses an
honest replacement needs are *forbidden*. Take `GEO-007`, whose declared reason is that
the check reads an operator input the audit does not pass — that is the definition of
`NEEDS_INPUT`, it is what the run answers, and writing it into the manifest fails
`test_every_declaration_has_a_supported_verdict_and_reason` today. Probed with `NO_DATA`,
which fails identically; `NEEDS_INPUT` is absent from the same set.

Note what this does *not* cover, because an earlier draft of this line over-claimed it.
For the seventeen of Appendix A.1 the honest declaration is `N/A`, which `ALLOWED` permits;
those repairs fail the *oracle*, not the vocabulary, and an oracle failing is the
instrument working. Removing a declaration is likewise legal, though it must also edit the
pinned id set, which is the intended mechanism rather than an obstacle. The opposition is
narrow — it bites on `GEO-007`'s two declarations for certain, and on `MB-105`'s two and
`TECH-001` if their honest value turns out to be `NO_DATA` — and a reader that permits the
violation and forbids even one form of the repair is opposed rather than merely unread.

#### Scenario: a prediction nobody is prepared to make
- **WHEN** no session that qualifies under DEC-1 will predict an item's status on an
  origin
- **THEN** the manifest carries no entry at all for that item on that origin
- **AND** the withholding and its reason are recorded where the declared set is
  maintained

#### Scenario: the status field is asked to say that nothing is expected
- **WHEN** a declaration's `expect` holds a word that means "cannot tell" rather than a
  status about the served tree
- **THEN** the manifest is in violation, even where every test over it passes

#### Scenario: the honest status is one the vocabulary already has
- **WHEN** an item's declared reason is that the check reads an operator input the audit
  does not pass, which is what `NEEDS_INPUT` means and what the run answers
- **THEN** the declaration says `NEEDS_INPUT`
- **AND** a reader that permits "cannot tell" and rejects `NEEDS_INPUT` opposes this
  requirement rather than failing to read it

#### Scenario: the entry that predicts nothing is counted as coverage
- **WHEN** an entry carrying no prediction is counted in the number quoted for how much
  of the registry is pinned
- **THEN** that number overstates what is pinned by exactly the size of the set nobody
  is comparing

### Requirement: DEC-3 — the declaration vocabulary is the audit's vocabulary, entire and unextended

The set a declaration may draw from SHALL be the eight statuses of
`openspec/specs/verdicts/`, and exactly those. It MUST NOT be a subset chosen because the
fixtures happen not to produce the rest, and MUST NOT be a superset.

**Why:** a subset silently forbids honest predictions — the manifest cannot say "the
checker will not be able to answer here", which is a genuine and checkable claim about a
fixture that provides no such subject. A superset re-introduces DEC-2. Both are the same
error: the manifest's vocabulary drifting away from the thing it is compared against.
**Reader:** partial, and pointed the wrong way. Membership is asserted, so an arbitrary
string fails; but the set it is asserted against is neither the audit's vocabulary nor a
subset of it. It omits `NO_DATA`, `NEEDS_INPUT`, `MANUAL` and `LLM_PENDING`, and adds
`INDETERMINATE`. Nothing derives `ALLOWED` from the status vocabulary, so the two can
drift apart in either direction with the suite green — and have.

#### Scenario: a status the audit can emit is refused to a declaration
- **WHEN** a declaration states one of the eight statuses that the permitted set omits
- **THEN** the declaration is legal, and the reader that rejects it is wrong
- **AND** the manifest is thereby forbidden an honest prediction it is in a position to
  make

#### Scenario: a word the audit never emits
- **WHEN** a declaration states anything outside the eight
- **THEN** it is rejected, whether the word is a typing slip or an invention meaning
  "no prediction"

#### Scenario: the two vocabularies drift apart
- **WHEN** a status is added to or removed from `openspec/specs/verdicts/`
- **THEN** the set a declaration may draw from moves with it
- **AND** a permitted set written as its own literal does not move, and nothing says so

### Requirement: DEC-4 — a declaration carries a reason, and the reason argues from the fixture

`why` SHALL state the construction that produces the expectation: what the tree contains,
what the item's title asks of it, and why the one implies the other. It MUST NOT be a
restatement of the status, and MUST NOT be a note about the run.

**Why:** the reason is what a triage reads when the declaration and the run disagree.
"expected PASS because it passes" leaves the reader with two claims and no argument, and
the natural resolution of a disagreement without an argument is to edit the declaration.
**Reader:** partial. `test_every_declaration_has_a_supported_verdict_and_reason` requires
`why` to be a non-empty string after stripping. Nothing reads what it says, and nothing
could mechanically; what a reader *could* check — that it names something in the fixture
tree — nothing does.

#### Scenario: a reason that restates the status
- **WHEN** `why` says "expected PASS because it passes"
- **THEN** the declaration does not satisfy this requirement
- **AND** a check that `why` is a non-empty string accepts it, so the requirement is
  violated with the suite green

#### Scenario: a reason argued from the run rather than the tree
- **WHEN** `why` names what the audit answered, or what a previous run reported, rather
  than what the fixture contains
- **THEN** it is not a reason under this requirement
- **AND** it is evidence that the declaration also violates DEC-1

#### Scenario: a triage has something to weigh
- **WHEN** a declaration and a run disagree and somebody has to decide which is wrong
- **THEN** `why` names what the tree contains and what the item's title asks of it, so
  the triage reads an argument rather than two bare claims
- **AND** the cheap resolution — editing the declaration — is not the only one available

### Requirement: DEC-5 — a declaration records what it was reasoned from, so a moved title makes it visibly unre-read

A declaration derived from an item's title SHALL store that title. When the title moves,
the declaration MUST be mechanically identifiable as one whose basis has changed and which
has not been re-read since.

The basis is not only the title. A declaration is made against the pages the run will
actually visit, which is a *sample* — `--sample 3` today — so the sample is part of what
was reasoned from and moves the same way. `test_fixture_oracle.py` records in a comment
which three pages the current sample picks on each origin, having measured it; a
declaration written against those three and compared against a different three is being
compared against a different site.

**Why:** `declared_from` names two sources: the item title and the fixture construction.
Both move. Today the manifest keeps neither, so a title can be rewritten under 250
predictions and every gate stays green — the release ritual carries the obligation to
re-read both sides by hand, which is a person remembering rather than a file objecting.
The census had exactly this disease and was cured: it copies four registry fields, and
since the 0.89.0 finding its test re-reads all four against the registry rather than
trusting the stamp. The instrument that got bitten was fixed; the one that has not been
bitten yet still carries the defect.
**Reader:** **none.** A declaration carries `expect` and `why` and nothing else.

#### Scenario: a title is rewritten under its predictions
- **WHEN** an item's title changes in the registry and the declarations reasoned from it
  are not re-read
- **THEN** each of those declarations is mechanically identifiable as one whose basis has
  moved
- **AND** no gate reports the manifest as current until they are re-read

#### Scenario: the sample moves under its predictions
- **WHEN** the pages `--sample 3` picks on an origin are not the pages a declaration was
  written against
- **THEN** the declaration is being compared against a different site, and is
  identifiable as unre-read
- **AND** recording the sampled pages in a comment beside the harness does not make them
  part of what the declaration stores

#### Scenario: nothing is stored to compare against
- **WHEN** a declaration carries only `expect` and `why`
- **THEN** a moved title is undetectable from the manifest, and the obligation to re-read
  falls on a person remembering a release ritual

### Requirement: DEC-6 — the declared set is derived from what the harness can reach, not listed by hand

Which items are expected to carry a declaration SHALL follow from the run's own capability
gating: an item the offline harness can answer is an item somebody owes a prediction for.
The obligation MUST be computed; only the *withholding* of a particular declaration is
written down, with its reason.

**Why:** a hand-kept list of ids cannot say what is missing from it. Add a new
`requires: fetch` item to the registry and the manifest simply does not mention it — no
gate objects, and the coverage line keeps reporting a number that is now a smaller fraction
of a larger registry.
**Reader:** partial. `test_both_fixtures_declare_all_items` asserts the manifest's id sets
equal `HTTP_DECLARED_IDS` and `TLS_DECLARED_IDS`, two literals in the test file. That
catches a declaration added or dropped without a deliberate edit, which is real and worth
keeping. It cannot catch the set being wrong: the two literals happen to equal the
offline-reachable script set exactly today (Appendix A.3), and nothing says they must.

#### Scenario: a reachable item is added and nobody notices it is owed
- **WHEN** an item the offline harness can answer is added to the registry and no
  declaration is written for it
- **THEN** the item is reported as owing one
- **AND** the coverage number does not quietly become a smaller fraction of a larger
  registry

#### Scenario: reachability moves without the manifest moving
- **WHEN** an existing item's `requires` changes so that the offline harness can now
  answer it, or can no longer answer it
- **THEN** the set of items owing a declaration changes with it, derived from the
  registry rather than from a list kept beside it

#### Scenario: the set is kept as a literal
- **WHEN** the expected id set is written out by hand where the comparison reads it
- **THEN** adding an item to the manifest and to the literal in one edit passes every
  check
- **AND** the reader that should have objected is the same literal the edit had to touch

#### Scenario: a declaration is withheld on purpose
- **WHEN** a reachable item deliberately carries no declaration, because no blind session
  was available for it
- **THEN** the withholding is written down with its reason
- **AND** it is distinguishable from an item nobody noticed was owed

### Requirement: DEC-7 — every declaration is compared on every run, and a difference stops the suite

No declaration SHALL be exempt from comparison, and any difference between a declaration
and the run MUST stop the suite. A declaration the comparison declines to make is worse
than none, because it is counted as coverage.

**Why:** the manifest's number is quoted as a measure of how much of the registry is
pinned. A declaration that is carried, counted and skipped inflates that number by exactly
the amount nobody is checking.
**Reader:** partial, and the exemption is the defect.
`test_every_settled_declaration_matches_the_real_runner` fails on any difference, and it
prints the fixture, item, both statuses and the reason — proved by probe: a declaration
edited from `PASS` to `FAIL` fails with all five of those. But *settled* is defined as
"not the ninth word", so the twenty-seven skip themselves, and the tally printed at the
end of the module reports them in a column of their own — visible, counted, and compared
with nothing. A reader that holds the comparison for 223 of 250 declarations and lets the
manifest exempt the rest holds part of the substance, not all of it. Removing the
exemption is DEC-2's repair, not a second one.

#### Scenario: the comparison declines to make a comparison
- **WHEN** a declaration carries a value the comparison skips rather than compares
- **THEN** this requirement is violated
- **AND** the declaration is worse than no declaration, because the coverage number
  counts it while nothing checks it

#### Scenario: a declaration disagrees with the run
- **WHEN** a declared `PASS` meets an answered `FAIL` on one origin
- **THEN** the suite fails, naming the origin, the item, both statuses and the
  declaration's reason

#### Scenario: the skipped declarations are printed instead of compared
- **WHEN** the run prints a column counting the declarations the comparison skipped
- **THEN** the requirement is still violated: visibility in a tally is not comparison,
  and a printed count is what made the exemption survive fifty-five releases

### Requirement: DEC-8 — a mismatch is a triage input, and neither side moves without a recorded reason

When a declaration and a run disagree, somebody SHALL decide which is wrong. Both outcomes
are legitimate: the checker may be defective, or the prediction may be. The manifest, the
fixture and the checker MUST NOT be edited to make the suite green without the decision
being written down.

**Why:** the cheapest way to make this test pass is always to edit the declaration, and
it is available at the exact moment somebody is trying to get a release out. The whole
value of the manifest is spent the first time that happens quietly.
**Reader:** **none.** A declaration edited to match a run is a two-line diff that looks
like every other declaration. `git log -S` finds it afterwards if somebody suspects it;
nothing surfaces it at the time. Fixture pages are under the same rule and the same
absence — the release ritual states that a page is not edited to pass a check, and that
proving a verdict did not move is a separate act.

#### Scenario: the declaration is edited to match the run
- **WHEN** a failing comparison is resolved by rewriting `expect` to whatever the audit
  answered
- **THEN** the requirement is violated unless the decision that the prediction was wrong
  is recorded with its argument
- **AND** the diff is indistinguishable from any other declaration, which is why the rule
  binds the record and not the diff

#### Scenario: the fixture is edited to match the checker
- **WHEN** a fixture page is changed so that a check stops failing
- **THEN** that is the same violation from the other side
- **AND** proving that no declared verdict moved is a separate act, not an inference from
  a green suite

#### Scenario: the checker is the side that is wrong
- **WHEN** triage decides the code is defective rather than the prediction
- **THEN** the declaration stands, the checker is repaired, and the decision is written
  down
- **AND** this outcome is as legitimate as the other; only the unrecorded edit is not

### Requirement: DEC-9 — a record names the registry it was taken against

Both artifacts SHALL state a `registry_version`, and each MUST be read as describing that
registry and no other.

**Why:** a manifest or a census taken against an older contract describes a checklist that
no longer exists, and nothing inside the file shows it.
**Reader:** partial, on both instruments, for the same reason and with different
consequences. `test_metadata_matches_the_registry` and `test_it_describes_this_registry`
each assert the stored string equals the registry's — which forces an edit when the
registry moves and cannot tell an edit of the stamp from a re-recording of the content.
The census closed that hole from the other side by re-reading its copied fields (DEC-11);
the manifest copies nothing, so for it the stamp is still the whole check. This is the
same shape as REG-1: a version a hand can set while the content stays put.

#### Scenario: the registry moves under a record
- **WHEN** the registry changes and a record taken against the previous one is not
  re-taken
- **THEN** the record describes a checklist that no longer exists, and it says so
- **AND** nothing inside the file shows it if the stamp alone is read

#### Scenario: the stamp is moved onto older content
- **WHEN** the recorded `registry_version` is edited to match the registry while the
  content stays as it was taken
- **THEN** the record claims a registry it was not taken against, which is a violation
- **AND** comparing the stored string with the registry's cannot see it, because the one
  field the check reads is the one field the edit set

#### Scenario: an artifact whose only tie to the registry is the stamp
- **WHEN** an artifact states a `registry_version` and copies nothing else from the
  registry
- **THEN** the stamp is the whole check, and a hand that sets it satisfies every gate

### Requirement: DEC-10 — the census asks every item on every tree, and an unrun item is not an unanswered one

Every registry item SHALL be asked on every served tree, and the record MUST distinguish
"this item was not run here" from "this item declined to answer here". A row MUST NOT
disagree with itself: its summary of answers is derived from its answers, every answer is
one of the eight statuses, and no item is described twice.

**Why:** the census's entire output is the range of answers an item gave. An item silently
absent from one tree shrinks its range, and a shrunken range is exactly the signal the
census exists to raise — so a failure of the instrument would be read as a finding about
the registry. The summary is what every reader actually reads, so a summary that can
disagree with the answers under it is the same defect one layer up.
**Reader:** partial, and thinner than the shape of the record suggests.
`test_every_item_was_asked_on_every_site` requires each row's answer *keys* to equal the
site set, and `test_every_item_is_accounted_for` pins the item set and the count. What is
unheld is everything about the values: the `MISSING` sentinel is forbidden only in
`distinct`, not in `answers`, so a row carrying `"fixture:broken": "MISSING"` under a
`distinct` that omits it passes every census test. Probed on `CI-004`, whose `broken`
answer was replaced by the sentinel while its `distinct` was left saying `FAIL, PASS`: all
four tests green. The expensive gate would still catch it — a fresh recording would not
say `MISSING`, so `--check` differs — but that gate is DEC-12's, it runs in a job of its
own, and between recordings the file is read by people whom nothing warns. Nothing requires
`distinct` to equal the set of answers, nothing requires an answer to be one of the eight
statuses, and nothing rejects a duplicate item key, which `json.load` silently collapses
to the last. All three are latent today: the shipped record is consistent, uses exactly
the eight, and has no duplicate keys.

To be plain, because a reader of this line took it for a description: the three are
**required by the paragraph above and unheld by any reader**, which is what `partial`
means here. They are not deferred, and they are not observations. Each is one assertion in
`test_census.py` and none needs a run.

#### Scenario: an item is silently absent from one tree
- **WHEN** the census records no answer for an item on a tree that was served
- **THEN** the record is invalid, and says the item was not run rather than leaving the
  tree out of the row
- **AND** the shrunken range would otherwise read as a finding about the registry when it
  is a failure of the instrument

#### Scenario: a row summarises itself wrongly
- **WHEN** a row's `answers` record the not-run sentinel for one tree and its `distinct`
  omits that value
- **THEN** the row disagrees with itself and the record is invalid
- **AND** forbidding the sentinel in `distinct` alone does not see this, because the
  answer it was derived from is never read

#### Scenario: an answer outside the vocabulary
- **WHEN** a row's `answers` carry a value that is not one of the eight statuses
- **THEN** the row is invalid, whether the value is a sentinel, a typing slip, or a word
  a later layer invented

#### Scenario: one item described twice
- **WHEN** the record carries two entries under one item id
- **THEN** it is invalid
- **AND** a JSON load that keeps the last of the two makes the duplicate disappear before
  any check can see it, so the check has to be over the file rather than over the load

### Requirement: DEC-11 — what a record copies from elsewhere is re-read, never trusted

Where a record copies a field it does not own — a title, a severity, a script name — the
copy SHALL be compared with the source, in both directions, by something that runs.

**Why:** the copy is what makes an archived record legible, so it stays. What must not
stay is the assumption that it is current. Measured: `census.json` shipped `GO-143` under
the first of two titles it was given inside one release, stamped with a `registry_version`
the content could not have been taken under — the stamp had been moved onto older content
by hand, and the one field the suite read was the one field an edit could set.
**Reader:** enforced. `test_what_it_copies_from_the_registry_still_describes_it` re-reads
all four copied fields for every item and fails in both directions — recorded and no
longer in the registry, in the registry and never recorded.

#### Scenario: a copied title goes stale
- **WHEN** an item's title changes in the registry and the record keeps the title it was
  taken under
- **THEN** the comparison fails and names the item
- **AND** it fails whether or not the record's `registry_version` was updated

#### Scenario: a row for an item the registry no longer carries
- **WHEN** an item is removed from the registry and its row stays in the record
- **THEN** the comparison fails

#### Scenario: an item the record never saw
- **WHEN** an item exists in the registry and the record carries no row for it
- **THEN** the comparison fails

#### Scenario: the stamp is trusted instead of the content
- **WHEN** only the recorded `registry_version` is compared with the registry's
- **THEN** a record whose content was taken under an earlier registry and re-stamped by
  hand passes, which is the failure this requirement was written from

### Requirement: DEC-12 — a recording is reproducible, and a stale one fails a gate

Re-taking the census on an unchanged tree SHALL produce the same record. A record that
differs from a fresh one MUST fail, in CI, on its own job.

**Why:** a measurement nobody can reproduce is an anecdote. This is also the only thing
standing between the record and a hand edit, since every value in it is plausible.
**Reader:** enforced. `verdict_census.py --check` compares the stored record with a fresh
one and exits 1 on any difference; the `census` job in CI runs exactly that. The
manifest has no equivalent and needs none — it is a prediction, not a recording.

#### Scenario: the record has drifted from the tree
- **WHEN** a fresh census differs from the stored record in any field
- **THEN** the gate exits non-zero and names the record
- **AND** the difference is not waved through for being small, since every value in the
  file is plausible and no other check stands between it and a hand

#### Scenario: a value written in by hand
- **WHEN** a plausible answer is edited into the record without a run behind it
- **THEN** the fresh recording disagrees and the gate catches it
- **AND** this is the only thing that does, which is why the gate exists at all

#### Scenario: nothing has changed
- **WHEN** the census is re-taken over the same registry and the same trees
- **THEN** the two records are equal, field for field

#### Scenario: the same rule asked of the manifest
- **WHEN** reproducibility is demanded of the manifest
- **THEN** it does not apply: a prediction re-derived from a run is exactly what DEC-1
  forbids, and the manifest is checked by the disagreement it was written to produce

### Requirement: DEC-13 — a range is a question, and the instrument's limits are recorded beside its output

An item that gave one answer everywhere SHALL be read as a question for a person, not as a
finding. What the mechanism cannot express MUST be written down where the output is read,
so the next reader does not mistake a limit of the harness for a property of the registry.

**Why:** the census's three headline counts are all inflated by the corpus being small,
and two named limits inflate them further: a static file server answers 200, 404 and a
directory 301, and cannot serve a 5xx, a redirect chain, a redirect loop or a status that
varies by user agent. Four items need exactly those and will never be seen failing here.
Without that written down, each reader re-derives it, and the third one files it as a
defect.
**Reader:** partial, and the unread half is the half the tree does not do.
`test_the_items_it_names_are_items` resolves the four ids the corpus README names against
the census, so a list nobody resolves cannot outlive the ids in it, and
`test_none_of_them_was_ever_seen_failing` holds the claim itself — if one of the four does
fail on some tree, the harness grew a capability the README says it lacks and the sentence
is wrong. Both read the README section rather than retyping it, because the list is
hand-kept and DEC-6's objection applies to it exactly as to the manifest.

What is still absent is the connection this requirement is actually about. The census
output *does* print those ids — as members of the group they inflate, the way it prints
every id in every group — and never marks them as items no tree here can exercise, so a
reader cannot tell them from items that merely did not fail. The census tool has no
reference to the README and no knowledge of any of the four.
`test_the_census_still_knows_nothing_of_the_limit` pins that structurally and is written
to fail on the day somebody closes it.

Probed on 6 September 2026, three ways: renaming one id in the README, marking one of the
four as having failed, and giving the census a reference to the README. Each reddens.

An earlier draft of this reader pinned the wrong absence — it asserted the output did not
name the four ids, which it does. The expected value came from what I assumed `report()`
printed rather than from running it.

#### Scenario: an item that answered the same on every tree
- **WHEN** the census reports an item whose range is a single answer
- **THEN** the output presents it as a question for a person
- **AND** it is not reported as a defect in the registry, because a rule that cannot
  answer otherwise and a question every site answers alike look identical from here

#### Scenario: a limit of the server read as a property of the registry
- **WHEN** an item can only fail on a 5xx, a redirect chain, a redirect loop, or a status
  that varies by user agent, none of which a static file server can produce
- **THEN** the census output itself records that no tree here can exercise that item
- **AND** the reader does not have to find that sentence in a README beside the trees to
  know it

#### Scenario: the list of unexercisable items drifts from the output
- **WHEN** an item joins or leaves the set the harness cannot exercise
- **THEN** what is written beside the output moves with it
- **AND** a hand-kept list of ids in prose does not, which is the same defect DEC-6
  objects to on the manifest

### Requirement: DEC-14 — a corpus tree carries no declarations, and that is what lets it grow

Trees added for coverage SHALL carry no predictions. Adding a page to a declared fixture
moves declared verdicts and costs a review; adding a corpus tree costs a re-recording.

**Why:** the two instruments have different marginal costs and that is the point of having
both. Declaring the corpus would make the cheap instrument as expensive as the dear one,
and the coverage the corpus exists to buy would stop being bought.
**Reader:** partial. `test_both_fixtures_declare_all_items` asserts the manifest's origin
set equals the four fixture labels, so a corpus tree cannot acquire a declaration without
a deliberate edit. As in DEC-6 the reader is a literal: it pins today's four rather than
the rule that a declared origin is a fixture origin.

#### Scenario: a corpus tree acquires a declaration
- **WHEN** a prediction is written for a tree that exists to buy coverage
- **THEN** the manifest is in violation
- **AND** that tree stops being cheap to grow, which is the coverage the corpus exists to
  buy

#### Scenario: a page is added to a declared fixture
- **WHEN** a page is added to one of the four declared fixture origins
- **THEN** declared verdicts may move, and the change costs a review of every declaration
  the new page can reach

#### Scenario: a page is added to the corpus
- **WHEN** a page is added to a corpus tree
- **THEN** the change costs a re-recording of the census and nothing else

#### Scenario: the rule is pinned as today's list of origins
- **WHEN** the declared origin set is asserted equal to the four fixture labels that
  exist today
- **THEN** a corpus tree cannot acquire a declaration by accident
- **AND** the rule that a declared origin is a fixture origin is still held by nothing, so
  a fifth fixture origin and a first declared corpus tree fail the same way

## 4. Invariants

* **INV-D1** — every declared id exists in the registry. *Reader: enforced twice, and one
  of the two says nothing.* An id added to the manifest alone fails
  `test_both_fixtures_declare_all_items` against the pinned literal, with a readable
  message. An id added to the manifest *and* the literal together gets past that and
  raises `KeyError` inside `comparison()`, because it indexes the run's results by the
  declared id. Both were probed. The second path fails, which is what matters, and fails
  without naming the problem, which is why it is written down here.
* **INV-D2** — the manifest's two HTTP origins declare the same id set, and its two TLS
  origins declare the same id set. *Reader: enforced* — `DECLARED_IDS` maps both HTTP
  labels to one literal and both TLS labels to another, so the equality is structural
  rather than asserted.
* **INV-D3** — both instruments audit an origin by the same command. *Reader:* **none.**
  The flag list appears twice, in `test_fixture_oracle.audit` and
  `verdict_census.run_audit`, as two literals that are identical today. Nothing compares
  them, and the census's own docstring rests on their being equal: "the numbers here and
  the numbers there come from the same path".
* **INV-D4** — no item is both declared and outside what the harness can reach, and no
  reachable item is undeclared. *Reader:* **none.** True today (Appendix A.3) and held by
  nothing: the pinned literals of DEC-6 fix the id set, not its relation to reachability,
  so the invariant breaks by editing the *registry* rather than the manifest. Probed in
  both directions — moving a declared item's `requires` from `crawl` to `api`, and moving
  an undeclared item's from `api` to `fetch`, each left every named and every plausible
  cheap reader green.

## 5. What this document does not decide

* what each status means and who it names — `openspec/specs/verdicts/`;
* what an item is, what its rule may claim, and how applicability is declared —
  `openspec/specs/registry/`;
* how a run turns `requires` into capability gating, which is what makes 22 items
  undeclarable here — `openspec/specs/run-lifecycle/`;
* the ledgers of known issues and inert findings, which are records of decisions rather
  than of measurements — `openspec/specs/governance/`;
* whether any *particular* declaration is right. This document says how a prediction is
  written, compared and withdrawn; it does not adjudicate one.

## 6. Open questions

**Does a withheld declaration need a place to live?** DEC-1 obliges a session that has
seen an answer to withhold, and DEC-2 obliges the withholding to be structural — no
declaration at all. Both are satisfied by deleting the entry and editing the id ledger,
where today's reasons live as code comments. Whether the reason belongs in the manifest
instead, as an explicit "withheld, and why", is open. Against it: a withheld entry in a
file of predictions is a place for the ninth word to grow back. What would settle it:
whether anyone ever needs to query the withheld set.

**When a fixture provides no subject, what is the answer?** Not hypothetical, and not
small: seventeen declarations argue "no subject" in prose, and the audit answers that one
condition `PASS` or `WARN` six times and `NO_DATA` eleven times (Appendix A.1). By the
inherited definitions all seventeen should be `N/A`, and the registry already has the
mechanism — an `applies_when` condition, which exactly two items carry.

This document cannot settle it alone, and should not want to. Whether changing what
seventeen checkers emit is a defect repair or a vocabulary decision belongs to
[`openspec/specs/verdicts/`](../verdicts/spec.md); which items owe an applicability condition
belongs to [`openspec/specs/registry/`](../registry/spec.md) REG-9, whose hand sweep found the
three `PASS`-side items and none of the five behind the eleven `NO_DATA` ones.
What this document contributes is the observation that both symptoms are one condition,
which no sweep from the registry side would have produced. What would settle it: reading
those seventeen checkers to see whether each *could* distinguish an absent subject from a
failed measurement — work none of the three documents has done.

The declaration side has a smaller version of the same question. A declaration of
`NO_DATA` argued from construction — no rendered document to compare, as `MB-105` has —
belongs. A declaration of `NO_DATA` written because the checker is weak silently pins the
weakness as correct, and the two are written identically. What would settle that: whether
a declaration may carry its reason's *class* as a field rather than only in prose.

**Should the corpus be declared after all, for the items the fixtures cannot reach?**
DEC-14 says no on cost grounds, and the cost is real. But `failing-shapes` exists to make
items fail that the fixtures never made fail, and nothing predicts what it should do — so
the trees built to find unfailable rules are themselves outside the only instrument that
could be wrong. What would settle it: whether the census's range signal has ever been
wrong in a way a declaration would have caught.

## Appendix A — measured disagreements, 29 August 2026

Observation, not specification. Measured at commit `413210f`, registry `b0abf2819da0`,
manifest `schema_version` 1, `tests/census.json` in step with a fresh census.

#### A.1 — twenty-seven declarations of two hundred and fifty are compared with nothing

`INDETERMINATE` appears in 27 declarations: 11 on `good`, 14 on `broken`, 2 on
`broken_tls`. `comparison()` counts them into a column of their own and `continue`s. They
have been carried, printed and counted as coverage since `v0.41.0`.

What the audit actually answers for those 27, read from `tests/census.json`, which audits
the same four origins by the same flags:

| answered | count | items |
|---|---:|---|
| `PASS` | 9 | AR-146 ×2, AR-163 ×2, GO-137 (`good`), AR-154 (`good`), TECH-001 (`broken`), AR-150 and CI-014 (`broken_tls`) |
| `WARN` | 2 | AR-154 and GO-137, both on `broken` |
| `FAIL` | 1 | MB-097 on `broken` |
| `NO_DATA` | 13 | IN-121, IN-122, IN-127, IN-128, MB-105, SE-118 on both HTTP origins; LO-200 on `broken` |
| `NEEDS_INPUT` | 2 | GEO-007 on both HTTP origins |

Sorting them by what the run answered is the obvious cut and it is the wrong one. Sort
them by what the *declarations say* instead, and seventeen of the twenty-seven turn out to
state one and the same condition, in their own words:

| declarations | the reason, quoted | run answers |
|---|---|---|
| `AR-146` ×2 | "the fixture contains no paginated series" | `PASS`, `PASS` |
| `AR-154` ×2 | "needs a category page to judge; this fixture is a five-page bakery with no collection, listing or category page anywhere" | `PASS`, `WARN` |
| `AR-163` ×2 | "needs facets; no page here exposes a filter, sort or facet URL" | `PASS`, `PASS` |
| `IN-121`, `IN-122`, `IN-127`, `IN-128` ×2 | "the fixture has no international dimension for this item to judge" | `NO_DATA` ×8 |
| `SE-118` ×2 | "there is no certificate to call valid or invalid" | `NO_DATA` ×2 |
| `LO-200` on `broken` | "has no subject in this fixture" | `NO_DATA` |

Seventeen declarations say *the fixture has no subject for this item*. That sentence is the
definition of `N/A` in [`openspec/specs/verdicts/`](../verdicts/spec.md): "the item has no subject
on this site". The audit answers that one condition **`PASS` or `WARN` six times,
`NO_DATA` eleven times, and `N/A` not once.**

The audit is perfectly capable of saying `N/A` — four declarations in this manifest expect
it and get it. Those four are `MB-102` and `MD-190`, which are the only two items in the
registry carrying an `applies_when` condition. An item with such a condition answers `N/A`
when its subject is absent; an item without one falls through to whatever its rule happens
to compute over nothing, which is `PASS` when the rule counts violations and finds none,
and `NO_DATA` when the rule reads a field the script never wrote.

So the ninth word has been hiding a single, systematic defect seventeen times over, and
splitting it into two symptoms that look unrelated. The six `PASS`/`WARN` cases are
exactly [REG-9](../registry/spec.md)'s harm — "the item reports success on a site that has
none of the thing" — and **all three of those items are already named** in that document's
list of seventeen owing an applicability declaration. The eleven `NO_DATA` cases are the
same absent subject taking a different exit, and **not one of those items appears in the
seventeen**, because a hand sweep of the registry looks for the false `PASS`, and a
`NO_DATA` does not look like a defect from that side. Read from this side instead —
through what somebody wrote down at the moment they declined to declare — the debt is
larger than the sweep found, and the sweep's blind spot has a shape.

Every one of the seventeen would fail the oracle if it were declared `N/A` today. That
failure is the instrument working: it would be pointing at six items whose applicability
debt is already recorded, and five whose is not.

The remaining ten are a residue rather than a group:

* `AR-150` and `CI-014` on `broken_tls` — "the shared TLS entry has no chain" / "has no
  loop". A first draft counted these among the seventeen and was wrong: the subject of
  both items is the site's redirect behaviour, which exists on that origin and happens to
  be clean, so the `PASS` both receive is true rather than vacuous. What the reasons
  actually record is that the harness cannot *build* a chain — a limit on what the fixture
  can exercise, not an absent subject. They belong to DEC-13, and to the four items
  `corpus/README.md` already names as unexercisable here.

* `GEO-007` ×2 — "the check reads `{indexnow_key}`, an operator input the oracle does not
  pass". The run answers `NEEDS_INPUT`, which is a status meaning exactly that. These two
  are the only declarations where the ninth word was written over a word that already
  fitted.
* `GO-137` ×2 — "the fixture supplies a sitemap but no search-engine index inventory to
  reconcile against it". The run answers `PASS` and `WARN`, because — per REG-6 — the rule
  reconciles against the audit's own crawl rather than the index its title names. The
  declaration refused for the right reason and the item answers a different question.
* `MB-105` ×2 — "no rendered document and nothing to compare". The item's subject *is* a
  comparison, so an absent artifact can be read as an absent subject or as an audit that
  could not decide. Genuinely undecided, and the case that makes §6's second question a
  question.
* `MB-097` on `broken` — "a 54 KB PNG of simple line art may already be efficiently
  compressed, and no quality target or alternative encoding is supplied". A judgement call
  about a threshold, which is the one honest use of "I decline" in the whole set, and the
  only contradiction where the run answers `FAIL`.
* `TECH-001` on `broken` — "its only HowTo appears inside unparseable JSON-LD and cannot be
  classified". The run answers `PASS`. The one declaration in the twenty-seven that no
  other document in this suite has anything to say about.

Two of the twelve contradictions are the reverse, and they are the most interesting rows
here. `AR-150` *Remove Redirect Chains and Loops* and `CI-014` *Use Correct Redirect Codes
(No Chains/Loops)* answer `PASS` on `broken_tls` — and `corpus/README.md` already records
that no tree this repository serves can produce a redirect chain or a loop, because the
static server has no routing table. The `PASS` is true and empty: it certifies the absence
of a thing the fixture cannot contain. The declaration's `INDETERMINATE` was reaching for
that, and DEC-13 is where it belongs — a limit of the mechanism, stated once, beside the
output — rather than in a status field on 27 predictions.

#### A.2 — the permitted vocabulary is neither the audit's nor a subset of it

`ALLOWED = {"PASS", "WARN", "FAIL", "N/A", "INDETERMINATE"}`. Against the eight statuses
of `openspec/specs/verdicts/`: four are missing — `NO_DATA`, `NEEDS_INPUT`, `MANUAL`,
`LLM_PENDING` — and one is invented. Two of the four missing are precisely the words
fifteen of the twenty-seven need, so **the repair that DEC-2 and DEC-3 require fails a
test that passes today**. That is what puts DEC-2 in `opposed` rather than `none`.

The omission of `MANUAL` and `LLM_PENDING` is not itself a defect: no manual or
model-judged item is declared, because none is reachable by the offline harness. It is a
defect that `ALLOWED` is a literal rather than a derivation, so nothing says which of the
five omissions are principled.

#### A.3 — the declared set is exactly right, and is maintained by hand

The union of declared ids is 123. The registry holds 145 script items, of which 22 require
`gsc`, `api` or `safe_browsing` and cannot be answered offline. 145 − 22 = 123, and the two
sets are equal — every offline-reachable script item is declared on at least one origin,
and nothing else is. Broken out: `requires` of `offline` 28, `fetch` 74, `crawl` 21.

That equality is held by two literals in a test file. A new `requires: fetch` item would
be undeclared, and the reader that would notice is the same literal that would have to be
edited to add it. Per origin: 118 on each HTTP origin, 7 on each TLS origin, overlapping in
`SE-117` and `SE-118`.

Coverage as the module prints it: 123 items declared, 108 settled on both sides, 84 opposed
across origins. The last two exclude the twenty-seven; **the first does not.** `coverage()`
counts an item as declared if any origin mentions it at all, and ten of the 123 —
`AR-146`, `AR-154`, `AR-163`, `GEO-007`, `GO-137`, `IN-121`, `IN-122`, `IN-127`, `IN-128`,
`MB-105` — carry nothing but the ninth word on every origin that mentions them. 113 items
have at least one declaration that is ever compared. The headline number of this instrument
overstates its own coverage by ten items, and it is the number quoted when anyone asks how
much of the registry is pinned.

#### A.4 — the manifest keeps no record of what it was reasoned from

`declared_from` names the item title and the fixture construction. A declaration stores
`expect` and `why`. Neither the title nor any fixture identity is stored, so a title
rewrite leaves 250 predictions pointing at a question that has changed, with every gate
green and only the release ritual — a person, remembering — obliging anyone to re-read
them.

The census stores the title and, since the finding recorded in `test_census.py`, re-reads
it. Two instruments, one disease, one cure applied. The cure was applied to the one that
had already produced a wrong file.

#### A.5 — the audit invocation exists twice

`test_fixture_oracle.audit` and `verdict_census.run_audit` each spell out
`--allow-private --sample 3 --max-rps 0 --no-history --no-prompt --quiet --timeout 120
--keyword bread`, plus the four artifact flags. The two lists are identical today and
nothing compares them. The census's docstring asserts the equality as a fact — "the
numbers here and the numbers there come from the same path" — and it is a fact about two
copies of a literal.

#### A.6 — the prose around both instruments states counts that have drifted

Neither instrument's own documentation has been re-read since the registry grew:

| file | says | tree says |
|---|---|---|
| `tests/corpus/README.md` | "reached 121 of 215 items in a year" | 123 of 217 |
| `tests/corpus/README.md` | "`fixtures/broken` carries 116 declarations" | 118 |
| `tests/verdict_census.py` docstring | "took a year to declare 121 of 215 items" | 123 of 217 |
| `tests/verdict_census.py` docstring | "answers it for all 215 at once" | 217 |

Four numbers, all understating, all in files whose subject is measurement. This is the
REG-12 shape in prose rather than in a field: a count written as a literal beside the
thing it counts, reproduced faithfully by every gate, compared with nothing. It is
recorded here rather than fixed in passing because the fix belongs with whichever release
closes DEC-6 — the same derivation that computes who owes a declaration computes both
numbers.

#### A.7 — this appendix spent the blindness it describes

A.1's table is per item and per origin. Writing it required reading what the audit answers
for all 27, so no session that has read this document can honestly write a blind
declaration for those items on those origins.

`openspec/specs/verdicts/` A.2 already published the aggregate — 9 `PASS`, 2 `WARN`, 1 `FAIL`, 13
`NO_DATA`, 2 `NEEDS_INPUT` — so the count was spent before today; the mapping was not, and
now is. It was spent deliberately: the twelve contradictions cannot be triaged without
knowing which items they are, and a document that named the disease without naming the
cases would have left the next session to spend the same blindness over again to find them.

An earlier draft of this appendix drew a line here: the twelve contradictions withdrawn,
the other fifteen replaced in place with the status the run gives, on the ground that an
argument from construction survives its author having seen the answer. That line does not
hold, for two reasons found by the audit of this document. It is an exception to DEC-1
invented at the point where DEC-1 is inconvenient, and DEC-1 admits no exception it cannot
check. And the group it was drawn around is not a group at all: eleven of those fifteen
argue `N/A` in prose while the run says `NO_DATA`, so writing the run's answer into them
would have been the purest form of the thing DEC-1 forbids — copying a recording over an
argument that disagreed with it, and erasing the larger part of the finding above in
the process.

What follows instead, and it follows from DEC-1 rather than from regret: **all
twenty-seven are withdrawn** — removed from the manifest and from the id ledger, each with
its reason recorded — and re-declared afterwards by a reader who has not seen this
appendix. That reader is obtainable: this tree has done it twice, in the withheld batches
of Stage 2b and 2c, by handing a session the fixture tree and the item title and not the
answers. Publishing the mapping does not make an honest re-declaration impossible; it
makes it something that has to be arranged rather than assumed.

The alternative — leaving A.1 as an aggregate, so that nobody's blindness is spent — was
considered and rejected. A defect list that will not name its cases is the shape this
suite already has a word for: nothing acts on it, and the next session spends the same
blindness rediscovering which items are affected.

Nothing is owed to the census by any of this. Withdrawing a declaration changes what was
predicted, never what was answered, so the twenty-seven rows in `census.json` stand
unaltered and need no re-recording. The two instruments come apart cleanly here, which is
the practical form of §1's distinction: only one of them has anything to withdraw.

## Appendix B — how much of this document is enforced

Every line below was measured by mutation — break the thing, run the named reader, record
what reddened — not by reading the tests. Two classifications in the first draft of this
document were wrong in the direction that flatters it, and both were `enforced` claims
resting on a reader that holds part of the substance: DEC-7, which compares 223 of 250
declarations, and DEC-10, whose reader inspects the keys of a row and nothing about its
values.

| | requirements |
|---|---|
| **enforced** | DEC-11, DEC-12 |
| **partial** | DEC-3, DEC-4, DEC-6, DEC-7, DEC-9, DEC-10, DEC-13, DEC-14 |
| **none** | DEC-1, DEC-5, DEC-8 |
| **opposed** | DEC-2 |

Invariants: INV-D1 and INV-D2 enforced; INV-D3 and INV-D4 unread.

**Two enforced, eight partial, three unread, one opposed, of fourteen.**

One thing does fall cleanly along the line between the instruments, and it is worth
stating in the direction that survives: **both enforced requirements belong to the census,
and not one belongs to the manifest.** Nothing the manifest owes — that a prediction
preceded the run, that it recorded what it was reasoned from, that a disagreement was
triaged rather than edited away — is held by anything. The converse is not clean, and an
earlier draft claimed it was: DEC-13 is a census requirement with no reader at all.

The asymmetry is structural rather than an accident of effort. A recording can be checked
by re-taking it, which is why DEC-12 is the cheapest enforced requirement here and the
strongest. A prediction cannot be checked by anything except the disagreement it was
written to produce, and a disagreement the manifest is permitted to exempt itself from is
the fifty-five releases of Appendix A.1.

Which is the argument for the three requirements that *can* be mechanised and are not.
DEC-5, so a moved title marks its declarations unre-read. DEC-6 with INV-D4, so the set of
items owing a declaration is computed from reachability rather than remembered in two
literals. DEC-10's unheld half, so a record cannot summarise itself wrongly. None is
expensive, and each converts a discipline people follow into a discipline a file objects
to.
