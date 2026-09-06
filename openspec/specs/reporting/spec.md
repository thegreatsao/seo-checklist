# Reporting — what the audit shows, and what it may not let a reader believe

## Purpose

Every surface a person actually reads — the console summary, the markdown and HTML
reports, the judgement queues, the evidence artifact — and the rules about what those
surfaces may let a reader believe.

This is the only layer a client sees, so it is the only layer where a true number can
still mislead. Most of what follows is not about computing anything: it is about refusing
to show a figure without the thing that makes it interpretable, and about never letting a
claim look better sourced than it is.

**Capability:** every surface the audit produces — the console summary, the Markdown and
HTML reports, the fix list, the model-judgement queue, the merges that fold answers back
in, the evidence artifact, and the language the whole of it is written in (C31–C35 and C37
of the capability inventory).

This document is normative and is written as though no code existed. Where the
implementation disagrees, the implementation is presumed wrong until this document is
changed by argument. Appendix A records disagreements measured on 4 September 2026.

Every requirement carries a **Reader** line naming what makes it fail when violated;
Appendix B is the census of those lines. A requirement whose reader is `none` is an
intention, and is counted as one.

**Inherited, not restated:** the statuses belong to
[`openspec/specs/verdicts/`](../verdicts/spec.md); the score, the weight share, the partition and
the fix ordering belong to [`openspec/specs/scoring/`](../scoring/spec.md); what a verdict was
computed from belongs to [`openspec/specs/evidence/`](../evidence/spec.md) and
[`openspec/specs/inputs/`](../inputs/spec.md). This document says what may be *shown*, and it may
not restate a number's definition in order to display it differently.

---

## 1. The only layer a client reads

Everything else in this suite is read by whoever maintains the tool. This layer is read by
the person paying for the audit, and they read one number and a list.

That changes what a defect is. Elsewhere a defect produces a wrong verdict; here it
produces a *true verdict that is believed to mean something else*. A score printed without
the share of the registry it covers is not wrong — it is 96, and it is 96 of the 60% that
could be measured, and the reader takes it for 96 of everything. An answer a model
produced, printed in the same typeface as a measurement, is not a false claim; it is a
claim whose provenance the reader cannot see. A fix list ordered by severity alone is
correct and useless, because the cheap high-severity work is buried under expensive
critical work nobody will start.

So the requirements here are almost all of one shape: **a number may not appear without
the thing that bounds it.** The score without its coverage, a verdict without who decided
it, a count without its denominator, an aggregate without how many pages it came from.

And it is the least-read layer in the suite. Six of its sections have no test at all
(Appendix A.1), including the console summary — the surface every operator sees on every
run and the only one most of them ever read.

## 2. What the audit produces

| surface | default | who reads it |
|---|---|---|
| console summary | always | the operator, on every run |
| Markdown report | a file | the operator, and often the client |
| HTML report | a file | the client |
| fix list | a file | whoever does the work |
| model-judgement queue | a file, plus one per lens | the agent doing the judging |
| evidence artifact | opt-in | whoever is arguing about a verdict |

Answers come back from two of those — the queue, and a manual pass — and are merged into
the results. The merges are where a claim becomes a verdict, and §3's hardest rules are
about them.

## Requirements

### Requirement: REP-1 — the score never appears without the share of the registry it covers

Wherever the headline number is shown, the proportion of the registry's weight it was
computed over SHALL be shown with it. Nothing MAY print one and omit the other.

**Why:** the number is meaningless without its denominator and looks complete without it.
An audit of a site where two thirds of the checks could not run reports a high score for
the third that could, and the reader has no way to see the difference from an audit that
answered everything.
**Reader:** enforced, by the same three tests that hold
[`openspec/specs/scoring/`](../scoring/spec.md) SCR-4 — this is one rule and this is the layer that
would violate it. Each surface is rendered twice with a different share and required to
change, so nothing depends on where the number is placed, and each of the three renderers
was probed separately. That includes the console summary, which until 5 September 2026 had
no test of any kind (A.1) and is the surface §6 asked whether it was possible to hold at
all.

#### Scenario: any surface that shows the score
- **WHEN** the score appears on the console, in the markdown report, in the HTML report
  or in the artifact
- **THEN** the share of the weight it covers appears with it

#### Scenario: a surface stops reading the share
- **WHEN** a renderer prints a constant, or a value derived from something other than
  this run
- **THEN** the requirement is violated even though a percentage is still on the page

### Requirement: REP-2 — a page that was not read produces no score line at all

Where the entry page was unreachable or refused by the guard, the report SHALL show no
score. The absence, and its reason, MUST be the output.

**Why:** a score computed over the handful of items that do not need the site is a number
about almost nothing, printed where a real one goes.
**Reader:** enforced. `test_the_score_is_none_when_nothing_was_decided` pins the unit case
and a live run against a challenge page pins it end to end, asserting that the entry is
recorded unreachable and that nothing was scored.

#### Scenario: the site could not be read
- **WHEN** the entry page was unreachable or the guard refused it
- **THEN** no score line is printed on any surface, and the reason the page could not
  be read is what the report shows instead

#### Scenario: a number stands in for the absence
- **WHEN** a surface renders the missing score as `None/100` or as zero
- **THEN** a reader is shown a verdict about the site where the truth is a statement
  about the audit

### Requirement: REP-3 — provenance appears wherever the score does

Whatever makes a run less than a full measurement — a private host, an overridden
guard, a thin entry page, a non-default parser, an artifact that was refused — SHALL be
stated on every surface that shows the score.

**Why:** these are the facts that change what the number is *about*, and a reader who sees
the number without them has been told something untrue by omission.
The list is normative, and it is this:

| warning | payload fields it reads | what it says the number is less than |
|---|---|---|
| `w_parser` | `html_parser` | the pages were read through the fallback substrate |
| `w_http_cache` | `http_cache_hits` | some verdicts describe the page as it was earlier in the run |
| `w_private_host` | `entry_private` | the host is reachable only from the auditing machine |
| `w_private` | `allow_private`, `mode` | a private address could have been reached while crawling |
| `w_guard` | `entry_guard`, `entry_guard_enforced` | the entry page looked like an interstitial and was scored anyway |
| `w_thin` | `entry_thin`, `entry_visible_words`, `entry_reachable` | the entry page may be an empty shell |
| `w_artifacts` | `artifacts` | some verdicts come from measurements supplied with the run |

`w_artifacts_age` is a fragment of the last row rather than a row of its own.

**Reader:** enforced. `tests/test_report.py` holds it in two halves this line used to say
were one. Ten test functions cover `provenance_warnings`, pinning each caveat's presence and —
importantly — its absence when it does not apply, so the surface cannot become noise. That
is the mechanism.

The *membership* is read by `tests/test_report.py::TheProvenanceListIsTheOneThisDocumentNames`,
which walks the function's AST for the warning identifiers it emits and the payload fields
it consults, and holds both against the table above. Adding a caveat without writing it
here reddens, and so does writing one here without adding it — which is the direction that
matters, because the way the last member came to be missing was that nothing anywhere
enumerated them. `openspec/specs/http/` HTTP-8 was that member: the response cache appeared
in no warning and in no test until 0.94.1.

#### Scenario: a run that scored an interstitial
- **WHEN** the page guard was overridden and the entry page was a bot challenge
- **THEN** every surface showing the score says so, so a clean-looking deliverable
  cannot be handed on without the caveat

#### Scenario: a new way of being less than a measurement
- **WHEN** something is added that changes what the verdicts describe — a response
  served from cache, say
- **THEN** it joins the provenance list
- **AND** a mechanism with ten readers whose *membership* has none is how the last one
  came to be missing

### Requirement: REP-4 — a claimed verdict is never shown as a measurement

An answer a person asserted and an answer a script measured are both verdicts and are
not the same kind of thing. Every merged answer SHALL record who decided it, and the
report MUST show that.

**Why:** the audit's authority rests on the reader being able to tell which claims were
checked. A `PASS` a person typed, rendered identically to a `PASS` a checker computed,
spends credibility the tool has not earned.
**Reader:** enforced. `tests/test_report.py::AClaimedVerdictIsNotShownAsAMeasurement` holds
it. What had been missing was the showing rather than the test: The stamp exists and three test functions assert it is set by the merges; measured on
6 September 2026, the report then printed one aggregate sentence — "Of the 2 decided items:
1 answered by a person, on their word" — and rendered the rows identically, so a reader was
told that one of the items was somebody's word and never which one.

`AClaimedVerdictIsNotShownAsAMeasurement` holds all three surfaces. A claimed verdict is
marked beside the verdict, a model-read one is marked *differently* — they are different
statements, and REP-5 is the reason — and a measured one is silent, for the reason the
parser caveat is silent for `lxml`. The set of origins each surface must mark is derived
from what `decided_by` can hold, read out of the two modules that stamp it, so a fourth
kind cannot render as a measurement on one surface while being marked on another. Probed by
collapsing the two markers into one, which reddens the model row.

#### Scenario: a person's answer in the report
- **WHEN** an item was decided by a typed claim rather than a measurement
- **THEN** the report shows that it was claimed, beside the verdict

#### Scenario: the stamp exists and no surface prints it
- **WHEN** the payload records who decided an item and no rendered surface says so
- **THEN** the requirement is unmet, because it is about what a reader is shown

### Requirement: REP-5 — a person must show evidence; a model is asked and not required

A manual answer without a stated reason SHALL be refused, by id, and the refusal
printed. A model's answer without a rationale MAY be accepted, and MUST be recorded as
having none.

**Why:** this asymmetry looks backwards and is deliberate. The manual pass is where an
operator can quietly convert an inconvenient `FAIL` into a `PASS`, and requiring a written
reason is the only friction available. A model's queue is machine-generated and re-runnable,
and refusing an answer for a missing rationale would silently drop items rather than
recording a weak one.
**Reader:** partial, and the halves are unevenly read. `apply_llm_review` has seven test
functions and `merge_llm_answers` four; `merge_manual_answers` — the half that carries the
refusal, and the one an operator can abuse — has **one**. `openspec/specs/verdicts/` records the
consequence as a live VRD-10 violation: a model verdict passes without a rationale while a
human's identical answer is rejected, and only the second is stated as a rule.

#### Scenario: a person answers without saying why
- **WHEN** a manual answer carries no reason
- **THEN** it is refused, the id is named, and the refusal is printed rather than
  swallowed

#### Scenario: a model answers without saying why
- **WHEN** a model answer carries no rationale
- **THEN** it is accepted and recorded as having none
- **AND** the asymmetry is deliberate: a person can quietly overwrite a `FAIL`, and this
  is the door that stops them

### Requirement: REP-6 — no merge may overwrite a verdict a script produced

A merge SHALL only fill a status that was waiting for it. A model's answer MAY replace
`LLM_PENDING` and nothing else; a person's MAY replace `MANUAL` and nothing else. Every
answer that is ignored MUST say why.

**Why:** without this, an answer file is a way to overwrite the audit. The whole value of a
script verdict is that nobody typed it.
**Reader:** partial. Each merge is asserted to act only on its own status — that is the
best-read part of this document — and the ignored-answer path is asserted for the manual
merge. That every ignored answer *prints* a reason is asserted for one merge of the three.

#### Scenario: an answer aimed at a measured verdict
- **WHEN** either merge targets an item a script decided
- **THEN** the measured verdict stands and the answer is reported as ignored, with the
  reason

#### Scenario: an answer aimed at the other queue
- **WHEN** a person answers an `LLM_PENDING` item, or a model a `MANUAL` one
- **THEN** it is refused

### Requirement: REP-7 — the reviewer may lower confidence and may not change the answer

A second reading of a model's answer SHALL either corroborate it or contest it.
Corroboration records agreement. Contesting MUST return the item to undecided, and MUST
NOT substitute the reviewer's verdict.

**Why:** a reviewer who can answer is a second judge, and two judges disagreeing needs a
third. A reviewer who can only withdraw confidence turns disagreement into "nobody knows",
which is true and is the only thing that is.
**Reader:** enforced. Seven test functions cover the review path, pinning agreement setting
corroboration, disagreement returning the item to `NO_DATA`, and the decider stamp being
dropped when it does.

#### Scenario: the reviewer disagrees
- **WHEN** a second reading contests the answer
- **THEN** the item returns to undecided, and the reviewer's own verdict is not put in
  its place

#### Scenario: the reviewer agrees
- **WHEN** a second reading corroborates the answer
- **THEN** the agreement is recorded and the verdict stands

### Requirement: REP-8 — contesting an answer lowers coverage, and that is intended

An item returned to undecided SHALL leave the scored set. The audit's coverage falls,
and the report MUST say so rather than preserve the number.

**Why:** the alternative is an audit whose score cannot go down when its confidence does,
which is the same defect as scoring an unanswerable item.
**Reader:** partial. The status change is enforced by REP-7's tests, and the scoring rules
that exclude an undecided item are enforced in `openspec/specs/scoring/`. That the *coverage line*
moves — that a reader sees the audit got smaller — is not asserted anywhere.

#### Scenario: a contested answer costs reach
- **WHEN** an item is returned to undecided by a review
- **THEN** it leaves the scored set and the weight share falls
- **AND** the report shows the lower reach rather than holding the earlier number

### Requirement: REP-9 — the fix list is ordered by severity per unit of effort

The list whoever does the work reads SHALL be ordered by what each fix returns for
what it costs, not by severity alone. A cheap high-severity fix MUST outrank an expensive
one of the same severity.

**Why:** an ordering by severity alone puts the whole quarter's work above the afternoon's,
and the afternoon's is what gets done. This is the one place the audit tells somebody what
to do first, so the order is the product.
**Reader:** enforced. `tests/test_report.py::Priority` and `openspec/specs/scoring/`
hold it between them, and closing it took a change in that other document.
Five test functions cover the priority computation, including one pinning that a cheap item
outranks an equally severe expensive one — which reads the *relation*, and was all this row
had. `openspec/specs/scoring/` used to record that no test pinned the effort costs
themselves, so the relation held while the numbers producing it were free to move; SCR-14
and SCR-2 closed that, and the costs are now held against §2 of that document and stamped
as part of the scoring instrument. Probed by setting `EFFORT_COST['high']` to 1, which
reddens three readers across the two documents: the table against the spec, the relation
here, and the instrument's stamp.

#### Scenario: two fixes of equal severity
- **WHEN** one is cheap and one is expensive
- **THEN** the cheap one is listed first

#### Scenario: a critical fix that is expensive
- **WHEN** a critical item costs more than a trivial low one
- **THEN** it is still not buried beneath it

### Requirement: REP-10 — a duplicate question appears once

Where the registry asks one question under two source numbers, the report SHALL fold
them and show the ruled survivor.

**Why:** a client reading the same finding twice concludes the audit is padded, and they are
right. The registry's own rule on which twin carries the weight is `openspec/specs/registry/` REG-11;
this is the display half.
**Reader:** partial. Five test functions cover the folding. The category-level counts are
recorded elsewhere in this suite as counting twins the headline folds, so the fold is read
for one surface and not for all of them.

#### Scenario: one finding, two source numbers
- **WHEN** a twin pair would both appear in a report surface
- **THEN** the survivor is shown once

#### Scenario: a surface that does not fold
- **WHEN** a count elsewhere in the report tallies both halves of a pair
- **THEN** the fold is read for one surface and not for all of them, which is what makes
  this requirement `partial` rather than met

### Requirement: REP-11 — every model-judged item belongs to exactly one lens, and each queue names its own items

The judgement queue is split by lens for throughput. Every item SHALL appear in
exactly one lens's file, and the machine-readable skeleton in each file MUST contain
exactly the ids of that file.

**Why:** an item in two lenses is judged twice and merged twice; an item in none is never
judged and waits forever. A skeleton naming ids that are not in its file was the shipped
defect that produced this rule.
**Reader:** enforced. Four test functions cover the queue rendering, including one pinning
that a per-lens queue's example names that file's real ids rather than two fixed ones.
That every model item has exactly one lens is read on the registry side by
`openspec/specs/registry/`. The lens-to-agent routing table was named by no test until
0.94.2 — a hand-written mapping guarded only by the mechanism that consumes it, which is
`openspec/specs/governance/` GOV-3's shape exactly: a lens added to the registry with no row
routes its queue to an agent named `""`, addressed to nobody, and every test of the
rendering still passes. `TheLensRoutingTableIsDerivedFromWhatItRoutes` derives the keys from
the lenses the registry actually uses and checks each agent against the file that has to
exist for the routing to mean anything. Probed by dropping a lens from the table.

#### Scenario: an item in two lenses
- **WHEN** one item appears in more than one lens's queue
- **THEN** it is judged twice and merged twice

#### Scenario: an item in none
- **WHEN** an item is model-judged and appears in no lens file
- **THEN** it waits forever, and nothing says so

#### Scenario: a skeleton naming ids the file does not contain
- **WHEN** the machine-readable block lists ids that are not in its own file
- **THEN** whoever answers the queue answers about items they were not shown — the
  shipped defect that produced this rule

### Requirement: REP-12 — the evidence artifact is a different document from the run log

The opt-in artifact SHALL record what each script returned. Internal keys MUST be
stripped, page runs MUST be kept separate from site runs rather than flattened, and the
page section MUST exist exactly when sampling occurred.

**Why:** this is the file somebody opens when they are arguing with a verdict. Flattening
sampled runs into site runs would make it impossible to tell which page produced which
number, which is the question it exists to answer.
**Reader:** partial. Five test functions cover the artifact's shape, and redaction reaching
it is separately enforced by `openspec/specs/inputs/` INP-7. That the internal `__`-prefixed keys are
stripped is asserted; that page runs are never flattened is asserted through the shape and
not as a rule.

#### Scenario: somebody argues with a verdict
- **WHEN** a reader opens the artifact to see what a script actually returned
- **THEN** page runs and site runs are distinguishable, so they can tell which page
  produced which number

#### Scenario: internal keys
- **WHEN** the artifact is written
- **THEN** keys the run used for its own bookkeeping are stripped

### Requirement: REP-13 — a half-translated report says which layers are English

Item titles and recommended fixes SHALL stay in English unless a translation
overrides them. Where a report is partly translated, it MUST say so, and the count of what
remains untranslated MUST be derived rather than maintained by hand.

**Why:** a report that is 90% in the reader's language reads as complete, and the English
that remains reads as an oversight rather than a design decision. A hand-maintained count
is wrong within two releases, which is the reason the derivation exists.
**Reader:** enforced. `tests/test_report.py::TheHalfTranslatedReportKnowsWhichHalf` holds the
derivation, and the gap it closed was a live defect in two layers.
Sixteen test functions exercise the language layer and a CI gate fails the build when a
translation drifts from its English source — that half was always well held. The derivation
of what is *missing* was a regex over the module's own source matching `L.t(` followed by at
most one newline: measured on 6 September 2026 it saw **99 of 138** literal keys, and five of
the invisible ones were genuinely absent from `ru.json`, so a Russian report printed the
broken-URL table's headers in English while the line whose job is to say which layers are
English said nothing.

Replacing the regex with an AST walk exposed the second layer: six calls take their key from
a table rather than a literal, and six of those twelve keys — the diff section headings and
their notes — were missing from `ru.json` too. Eleven English strings in a Russian report,
none of them reported. Both layers are fixed and `Lang("ru").missing_strings()` is empty over
150 asked-for keys.

`TheHalfTranslatedReportKnowsWhichHalf` holds all three parts: a shipped language is missing
nothing, the derivation survives a call being reformatted, and — the part that outlives this
release — the number of `L.t()` calls with a computed key equals the number the three walked
tables account for. A fourth table-backed call is the same failure one level along, and
counting them is how a reader finds out.

#### Scenario: a report mostly in the reader's language
- **WHEN** the strings are translated and the item titles are not
- **THEN** the report says which layers remain in English

#### Scenario: the count of what is missing
- **WHEN** that count is shown
- **THEN** it is derived from the translation files rather than maintained by hand, so
  it cannot be right today and wrong in two releases

## 4. Invariants

* **INV-P1** — every item in the results appears exactly once on every surface that lists
  items. *Reader: partial* — the partition sums are asserted; per-surface uniqueness is not.
* **INV-P2** — no surface shows a status outside the eight. *Reader: enforced* — the
  renderers are tested against all eight and the merges reject words outside the vocabulary.
* **INV-P3** — the evidence artifact and the run log describe the same runs.
  *Reader: enforced* — a test asserts the two key sets are equal and that a broken entry
  appears identically in both.
* **INV-P4** — a surface never states a number the results do not contain.
  *Reader:* **none.** Every section computes its own display values, and nothing compares a
  rendered figure against the payload it came from.

## 5. What this document does not decide

* how the score, the weight share and the partition are computed — `openspec/specs/scoring/`;
* what a status means — `openspec/specs/verdicts/`;
* what an item's title says or whether it is right — `openspec/specs/registry/`;
* what the operator protocol obliges the *agent* driving the tool to do with a report —
  `openspec/specs/operator-protocol/`;
* which language the tool should ship. This document requires a partial translation to
  declare itself; which translations exist is a product decision.

## 6. Open questions

**Should the console summary be tested at all?** It is the surface every operator sees on
every run and it has no test (A.1). Testing terminal output is famously brittle — it
changes for good reasons constantly — which is presumably why nobody did. But the two
things REP-1 and REP-2 require of it are not brittle: that a score never appears without
its share, and that no score appears at all when nothing was read. What would settle it:
whether those two can be asserted against the printed text without pinning its layout.

**Is "who decided it" a status, a field or a rendering?** REP-4 requires the report to show
it, and today it is a field the merges stamp and the renderers may or may not surface.
Making it part of the status vocabulary was rejected in `openspec/specs/verdicts/` — a status
describes the site, not the audit — which leaves it as a field somebody must remember to
render. What would settle it: whether any surface currently omits it, which nothing checks.

**What does a contested answer cost?** REP-8 says coverage falls and calls that intended.
It is intended, and it also means a reviewer can lower a site's score by disagreeing, with
no way for the report to distinguish "we could not answer" from "we answered and then
doubted it". Both are `NO_DATA`. What would settle it: whether the two need to be
distinguishable to the client, or only to whoever re-runs the audit.

## Appendix A — measured disagreements, 4 September 2026

Observation, not specification. Measured at commit `cfa4e8d`, by parsing all 1 280 test
functions in the suite and asking, for each reporting symbol, how many function bodies name
it.

#### A.1 — six report sections and four display constants have no test

| symbol | test functions naming it |
|---|---:|
| `print_report` — the console summary | **0** |
| `plain_summary` | **0** |
| `trend_section` | **0** |
| `broken_url_section` | **0** |
| `opportunity_section` | **0** |
| `lab_performance_lines` | **0** |
| `CATEGORY_HELP` | **0** |
| `BROKEN_URLS_SHOWN`, `ERROR_DETAIL_CHARS` | **0** |
| `BAR_FAIL_SCORE`, `BAR_WARN_SCORE` | **0** |
| `LENS_AGENTS` | **0** |

For contrast, in the same census: `render_markdown` 11, `provenance_warnings` 10,
`render_html` 8, `fix_rows` 8, `apply_llm_review` 7.

The console summary is the one to sit with. It is printed on every run, it is the only
output most operators read, and it is the surface REP-1 and REP-2 are about. Nothing
asserts anything about it.

The four display constants are a smaller version of the same shape as
`openspec/specs/http/` A.2: numbers that decide what a reader sees — how many broken URLs are
listed, how much of an error is quoted, where the bars change colour — pinned by nothing.

#### A.2 — the merge a person can abuse is the least tested of the three

| merge | test functions |
|---|---:|
| `apply_llm_review` | 7 |
| `merge_llm_answers` | 4 |
| `merge_manual_answers` | **1** |

The manual merge is the one that converts a typed claim into a verdict, and it carries the
rule REP-5 exists for: an answer without a written reason is refused by id. One test
function names it.

This is the asymmetry the capability inventory recorded as G18, and measuring it sharpens
the point: the ordering is exactly inverted from the risk. The reviewer, who cannot change
an answer, has seven readers. The person, who can, has one.

#### A.3 — the rationale rule runs the other way from the evidence rule

Reading the two merges side by side:

* a manual answer's reason is read, stripped, and **an empty one is refused** — the item is
  skipped and reported;
* a model answer's reason is read, stripped, and an empty one becomes the literal string
  `no rationale given`, which is then shown as the item's evidence.

REP-5 states this asymmetry as intended and gives the argument for it. It is recorded here
because `openspec/specs/verdicts/` reaches the opposite conclusion from the same code — it lists
"the LLM answer merge" among VRD-10's live violations, on the ground that a model verdict
passing without justification while a human's is rejected is a difference the status
vocabulary does not license.

Both documents are looking at the same two functions. One says the asymmetry is a designed
defence against an operator quietly overwriting a `FAIL`; the other says it is a verdict
whose provenance the vocabulary cannot express. They are not obviously reconcilable, and
neither has a test that would decide it. This is the first place in the suite where two
normative documents disagree about the same behaviour, and it is recorded rather than
resolved because resolving it is a decision about what the tool owes a reader, not a
measurement.

## Appendix B — how much of this document is enforced

**Probed:** REP-3, REP-4, REP-9, REP-11 and REP-13, by mutation, on 6 September 2026 — deleting the cache branch
from `provenance_warnings` reddens the membership reader from both sides, and — setting `EFFORT_COST['high']` to 1
reddens three readers across two documents. The rest were derived by parsing the 1 280 test
functions and reading the bodies that name each symbol: the executor running mutation probes
for this suite ran out of credits partway through. The limit is the one
`openspec/specs/evidence/` A.4 states: a test can exercise something without naming it, so `none`
means "named by nothing" — a lower bound on coverage, not an upper one. For the console
summary that bound is unusually tight, because there is no plausible way to exercise
`print_report` without naming it.

| | requirements |
|---|---|
| **enforced** | REP-1, REP-2, REP-3, REP-4, REP-7, REP-9, REP-11, REP-13 |
| **partial** | REP-5, REP-6, REP-8, REP-10, REP-12 |
| **none** | — none |
| **opposed** | — none |

Invariants: INV-P2 and INV-P3 enforced; INV-P1 partial; INV-P4 unread.

**Eight enforced, five partial, nothing unread, of thirteen.**

REP-9 moved without a line of work in this document: its gap was a sentence about another
one — the effort costs the ordering divides by were pinned by nothing — and closing SCR-2
and SCR-14 in `openspec/specs/scoring/` closed it here. Worth recording because a census
that only re-reads its own document cannot see a row move for that reason, and this one
was found by grepping the other document's name after it changed.

Ten partial is the highest count in the suite and it is not a coincidence of writing. Nine
of the ten have the same shape: the *computation* is read and the *display* is not.
The merges are asserted to set a decider stamp and nothing asserts a report shows it. The
twin fold is asserted and the category counts that ignore it are not. The priority relation
is asserted and the numbers behind it are not. Coverage is asserted to fall and no test
watches the line that says so.

The tenth, REP-3, is a different shape and one the suite keeps producing: the provenance
mechanism is enforced from ten directions and the *list* of what belongs in it is guarded by
nothing, which is how the response cache came to be absent from it. That pairing —
a mechanism with readers, a membership without — is now the fourth instance across these
documents, after the lens vocabulary, the secret set and the severity words.

The nine are one gap nine times, and it has a name in this suite already: behaviour is not
a reader of behaviour. REP-1 was the tenth instance and the clearest — both renderers
printed the weight share beside the score, and printing it is not the same as being
required to. The distance between this layer's tests and this layer's obligations is
exactly the distance between "the function returns the right value" and "the reader is not
misled", and the second is what the client pays for.

REP-1 was closed on 5 September 2026, and how is worth more than that it was. The reason
this layer's displays go unread is that asserting on rendered text means pinning rendered
text, which is brittle for good reasons and gets abandoned. The way round it is to assert
nothing about the text at all: change the value upstream, render twice, and require the two
to differ. That reads "this surface shows this number" without knowing a single thing about
how. It cost three tests, it caught all three renderers under separate probes, and it took
the console summary from no test of any kind to a held one. The nine remaining `partial`
rows are the same shape as the one just closed, and now have a method that fits them.
