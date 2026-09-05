# Reporting — what the audit shows, and what it may not let a reader believe

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
[`specs/verdicts/`](../verdicts/spec.md); the score, the weight share, the partition and
the fix ordering belong to [`specs/scoring/`](../scoring/spec.md); what a verdict was
computed from belongs to [`specs/evidence/`](../evidence/spec.md) and
[`specs/inputs/`](../inputs/spec.md). This document says what may be *shown*, and it may
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

## 3. Requirements

### REP-1 — the score never appears without the share of the registry it covers

Wherever the headline number is shown, the proportion of the registry's weight it was
computed over is shown with it. Nothing may print one and omit the other.

**Why:** the number is meaningless without its denominator and looks complete without it.
An audit of a site where two thirds of the checks could not run reports a high score for
the third that could, and the reader has no way to see the difference from an audit that
answered everything.
**Reader:** **none**, and it is `specs/scoring/` SCR-4's finding restated here because
this is the layer that would violate it. Both renderers do print the share beside the
score; no test would fail if either stopped.

### REP-2 — a page that was not read produces no score line at all

Where the entry page was unreachable or refused by the guard, the report shows no score.
The absence, and its reason, is the output.

**Why:** a score computed over the handful of items that do not need the site is a number
about almost nothing, printed where a real one goes.
**Reader:** enforced. `test_the_score_is_none_when_nothing_was_decided` pins the unit case
and a live run against a challenge page pins it end to end, asserting that the entry is
recorded unreachable and that nothing was scored.

### REP-3 — provenance appears wherever the score does

Whatever makes a run less than a full measurement — a private host, an overridden guard, a
thin entry page, a non-default parser, an artifact that was refused — is stated on every
surface that shows the score.

**Why:** these are the facts that change what the number is *about*, and a reader who sees
the number without them has been told something untrue by omission.
**Reader:** partial — the mechanism is enforced and its membership is not.
Ten test functions cover
`provenance_warnings`, pinning each caveat's presence and — importantly — its absence when
it does not apply, so the surface cannot become noise. What is missing is a *member* rather
than a mechanism: `specs/http/` HTTP-8 records that whether the response cache was used
appears in no warning and in no test.

### REP-4 — a claimed verdict is never shown as a measurement

An answer a person asserted and an answer a script measured are both verdicts and are not
the same kind of thing. Every merged answer records who decided it, and the report shows
that.

**Why:** the audit's authority rests on the reader being able to tell which claims were
checked. A `PASS` a person typed, rendered identically to a `PASS` a checker computed,
spends credibility the tool has not earned.
**Reader:** partial. The stamp exists and three test functions assert it is set by the
merges. That the *report* displays it — that a reader of the Markdown or the HTML can tell
a claimed verdict from a measured one — has no test.

### REP-5 — a person must show evidence; a model is asked and not required

A manual answer without a stated reason is refused, by id, and the refusal is printed. A
model's answer without a rationale is accepted and recorded as having none.

**Why:** this asymmetry looks backwards and is deliberate. The manual pass is where an
operator can quietly convert an inconvenient `FAIL` into a `PASS`, and requiring a written
reason is the only friction available. A model's queue is machine-generated and re-runnable,
and refusing an answer for a missing rationale would silently drop items rather than
recording a weak one.
**Reader:** partial, and the halves are unevenly read. `apply_llm_review` has seven test
functions and `merge_llm_answers` four; `merge_manual_answers` — the half that carries the
refusal, and the one an operator can abuse — has **one**. `specs/verdicts/` records the
consequence as a live VRD-10 violation: a model verdict passes without a rationale while a
human's identical answer is rejected, and only the second is stated as a rule.

### REP-6 — no merge may overwrite a verdict a script produced

A merge only ever fills a status that was waiting for it. A model's answer may replace
`LLM_PENDING` and nothing else; a person's may replace `MANUAL` and nothing else. Every
answer that is ignored says why.

**Why:** without this, an answer file is a way to overwrite the audit. The whole value of a
script verdict is that nobody typed it.
**Reader:** partial. Each merge is asserted to act only on its own status — that is the
best-read part of this document — and the ignored-answer path is asserted for the manual
merge. That every ignored answer *prints* a reason is asserted for one merge of the three.

### REP-7 — the reviewer may lower confidence and may not change the answer

A second reading of a model's answer either corroborates it or contests it. Corroboration
records agreement. Contesting returns the item to undecided — it does not substitute the
reviewer's verdict.

**Why:** a reviewer who can answer is a second judge, and two judges disagreeing needs a
third. A reviewer who can only withdraw confidence turns disagreement into "nobody knows",
which is true and is the only thing that is.
**Reader:** enforced. Seven test functions cover the review path, pinning agreement setting
corroboration, disagreement returning the item to `NO_DATA`, and the decider stamp being
dropped when it does.

### REP-8 — contesting an answer lowers coverage, and that is intended

An item returned to undecided leaves the scored set. The audit's coverage falls, and the
report says so rather than preserving the number.

**Why:** the alternative is an audit whose score cannot go down when its confidence does,
which is the same defect as scoring an unanswerable item.
**Reader:** partial. The status change is enforced by REP-7's tests, and the scoring rules
that exclude an undecided item are enforced in `specs/scoring/`. That the *coverage line*
moves — that a reader sees the audit got smaller — is not asserted anywhere.

### REP-9 — the fix list is ordered by severity per unit of effort

The list whoever does the work reads is ordered by what each fix returns for what it costs,
not by severity alone. A cheap high-severity fix outranks an expensive one of the same
severity.

**Why:** an ordering by severity alone puts the whole quarter's work above the afternoon's,
and the afternoon's is what gets done. This is the one place the audit tells somebody what
to do first, so the order is the product.
**Reader:** partial. Five test functions cover the priority computation, including one
pinning that a cheap item outranks an equally severe expensive one — which reads the
*relation*. `specs/scoring/` records that no test pins the effort costs themselves, so the
relation holds and the numbers producing it are free to move.

### REP-10 — a duplicate question appears once

Where the registry asks one question under two source numbers, the report folds them and
shows the ruled survivor.

**Why:** a client reading the same finding twice concludes the audit is padded, and they are
right. The registry's own rule on which twin carries the weight is `specs/registry/` REG-11;
this is the display half.
**Reader:** partial. Five test functions cover the folding. The category-level counts are
recorded elsewhere in this suite as counting twins the headline folds, so the fold is read
for one surface and not for all of them.

### REP-11 — every model-judged item belongs to exactly one lens, and each queue names its own items

The judgement queue is split by lens for throughput. Every item appears in exactly one
lens's file, and the machine-readable skeleton in each file contains exactly the ids of
that file.

**Why:** an item in two lenses is judged twice and merged twice; an item in none is never
judged and waits forever. A skeleton naming ids that are not in its file was the shipped
defect that produced this rule.
**Reader:** partial. Four test functions cover the queue rendering, including one pinning
that a per-lens queue's example names that file's real ids rather than two fixed ones.
That every model item has exactly one lens is read on the registry side by
`specs/registry/` and not here; the lens-to-agent routing table is named by no test.

### REP-12 — the evidence artifact is a different document from the run log

The opt-in artifact records what each script returned. Internal keys are stripped, page
runs are kept separate from site runs rather than flattened, and the page section exists
exactly when sampling occurred.

**Why:** this is the file somebody opens when they are arguing with a verdict. Flattening
sampled runs into site runs would make it impossible to tell which page produced which
number, which is the question it exists to answer.
**Reader:** partial. Five test functions cover the artifact's shape, and redaction reaching
it is separately enforced by `specs/inputs/` INP-7. That the internal `__`-prefixed keys are
stripped is asserted; that page runs are never flattened is asserted through the shape and
not as a rule.

### REP-13 — a half-translated report says which layers are English

Item titles and recommended fixes stay in English unless a translation overrides them.
Where a report is partly translated, it says so, and the count of what remains untranslated
is derived rather than maintained by hand.

**Why:** a report that is 90% in the reader's language reads as complete, and the English
that remains reads as an oversight rather than a design decision. A hand-maintained count
is wrong within two releases, which is the reason the derivation exists.
**Reader:** partial. Sixteen test functions exercise the language layer and a CI gate fails
the build when a translation drifts from its English source — that half is well held. The
derivation of what is missing is read by one test, and `local/sdd/inventory/GAPS.md` records
that the derivation itself is a regex over the module's own source that a reformatted call
would silently drop out of.

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

* how the score, the weight share and the partition are computed — `specs/scoring/`;
* what a status means — `specs/verdicts/`;
* what an item's title says or whether it is right — `specs/registry/`;
* what the operator protocol obliges the *agent* driving the tool to do with a report —
  `specs/operator-protocol/`;
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
Making it part of the status vocabulary was rejected in `specs/verdicts/` — a status
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

### A.1 — six report sections and four display constants have no test

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
`specs/http/` A.2: numbers that decide what a reader sees — how many broken URLs are
listed, how much of an error is quoted, where the bars change colour — pinned by nothing.

### A.2 — the merge a person can abuse is the least tested of the three

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

### A.3 — the rationale rule runs the other way from the evidence rule

Reading the two merges side by side:

* a manual answer's reason is read, stripped, and **an empty one is refused** — the item is
  skipped and reported;
* a model answer's reason is read, stripped, and an empty one becomes the literal string
  `no rationale given`, which is then shown as the item's evidence.

REP-5 states this asymmetry as intended and gives the argument for it. It is recorded here
because `specs/verdicts/` reaches the opposite conclusion from the same code — it lists
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

**Probed:** none by mutation. The executor running mutation probes for this suite ran out
of credits partway through, so every row below was derived by parsing the 1 280 test
functions and reading the bodies that name each symbol. The limit is the one
`specs/evidence/` A.4 states: a test can exercise something without naming it, so `none`
means "named by nothing" — a lower bound on coverage, not an upper one. For the console
summary that bound is unusually tight, because there is no plausible way to exercise
`print_report` without naming it.

| | requirements |
|---|---|
| **enforced** | REP-2, REP-7 |
| **partial** | REP-3, REP-4, REP-5, REP-6, REP-8, REP-9, REP-10, REP-11, REP-12, REP-13 |
| **none** | REP-1 |
| **opposed** | — none |

Invariants: INV-P2 and INV-P3 enforced; INV-P1 partial; INV-P4 unread.

**Two enforced, ten partial, one unread, of thirteen.**

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
a reader of behaviour. Both renderers print the weight share beside the score, and REP-1 is
`none` because printing it is not the same as being required to. The distance between this
layer's tests and this layer's obligations is exactly the distance between "the function
returns the right value" and "the reader is not misled" — and the second is what the client
pays for.
