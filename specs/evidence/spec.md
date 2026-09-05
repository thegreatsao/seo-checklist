# Evidence — what a checker owes, and what may be believed of what it returns

**Capability:** the contract every one of the fifty-eight checkers answers to, the
checkers themselves, and the server-log evidence one of them reads (C24, C25, C26 of the
capability inventory).

This document is normative and is written as though no code existed. Where the
implementation disagrees, the implementation is presumed wrong until this document is
changed by argument. Appendix A records disagreements measured on 4 September 2026.

Every requirement carries a **Reader** line naming what makes it fail when violated;
Appendix B is the census of those lines. A requirement whose reader is `none` is an
intention, and is counted as one.

**Inherited, not restated:** the statuses belong to
[`specs/verdicts/`](../verdicts/spec.md); the assertion language that reads these outputs
belongs to [`specs/registry/`](../registry/spec.md); how a checker is invoked, timed out
and classified when it fails belongs to
[`specs/run-lifecycle/`](../run-lifecycle/spec.md); how it is permitted to reach the
network belongs to [`specs/http/`](../http/spec.md). This document says what the process
must *return* and what may be believed of it.

---

## 1. One contract, not fifty-eight documents

Fifty-eight checkers is too many to specify individually and too many to leave
unspecified. Writing a page each would produce fifty-eight pages stale within a month;
writing none leaves the registry's rules pointing at field names nobody promised.

The resolution this document takes is the one the coverage map argued for: **the contract
is normative here, and the catalogue is generated.** What every checker owes — an
invocation shape, an exit code, a severity vocabulary, defined behaviour when it can fetch
nothing — is written below and does not change when a checker does. What each *particular*
checker emits is machine-probed into
`resources/references/script-output-shapes.md`, because a hand-written catalogue is a
promise nobody keeps and a probed one either matches the tree or fails a gate.

That split is also where this layer's characteristic defect lives. A rule in the registry
reads a path like `summary.thin_pages` out of a checker's JSON. Nothing in the language
of the rule says which checker, which version, or whether the path was ever emitted. The
probe is what makes the path real, and the probe is a snapshot — so the interesting
question for this document is never "is the checker right", which no document can settle
for fifty-eight programs, but **"is anything at all asserting that this checker's answer
is the right one"**. Appendix A.2 answers it: for twenty of the fifty-eight, nothing does
by name, and the fixture oracle carries almost all of them. Almost.

## 2. What a checker is

A checker is a process. The audit runs it with arguments and `--json`, and reads one JSON
document from its standard output. It is not a library, it is not imported, and it does
not decide a verdict — it produces evidence, and the registry's rule decides.

### 2.1 The invocation

`python <script> <args…> --json`, JSON on stdout, exit 0. Exit 0 even when the checker
could not answer: a non-zero exit is a defect in the checker, not a way to say "no".

### 2.2 The universal shape

Almost every checker returns `issues[]`, each carrying `severity` — one of `critical`,
`high`, `medium`, `low` — and `message`. Rules are written against that convention in
preference to per-script fields, because it is the one shape that is shared.

Checkers that speak a different severity vocabulary are normalised in one place, by the
runner: `error` becomes `high`, `warning` and `warn` become `medium`, `info` and `notice`
become `low`. A checker inherited from upstream may say `error`; a rule never has to know
that.

### 2.3 What else the shape carries

* a `0–100` score, on ten checkers;
* `summary` objects, per checker;
* `truncated`, a claim that the input the checker read was capped;
* the shared fetch result, whose `error_kind` is `None` exactly when `error` is `None`.

## 3. Requirements

### EVD-1 — a checker is a process with one output, and exit 0 means "I ran"

One JSON document on standard output, exit 0. A checker that cannot reach the site, cannot
parse the page, or has nothing to say still exits 0 and returns its defined empty shape.

**Why:** the runner classifies a non-zero exit as a crash, which is a defect report about
the checker. A checker that exits non-zero to mean "the site was down" produces a
maintenance ticket instead of a `NO_DATA`, and the two are read by different people.
**Reader:** partial. The five failure kinds and their labels are pinned by the runner's
tests, and every checker is exercised end to end against a real served origin by the
evidence suite, so a checker that exited non-zero on a normal page would fail there. What
is unread is the *empty* case as a contract: nothing asserts that each checker, given
nothing to work with, exits 0 rather than raising — it is asserted for the handful whose
tests construct that case and inherited for the rest.

### EVD-2 — findings speak one severity vocabulary, normalised once

A finding's severity is `critical`, `high`, `medium` or `low`. Where a checker inherited
another vocabulary, exactly one place translates it, and no rule and no report ever sees
the untranslated word.

**Why:** thirteen rules once asked for `critical` or `high` over checkers that never say
either word, and every one of them reported `PASS` on every site ever audited. A second
translation site would reintroduce that failure in the half of the tree that used the
other one.
**Reader:** partial. The alias map is used by the assertion evaluator and exercised
wherever a rule names a severity, and `tools/audit_assertions.py` fails the build for a
rule asking for a severity its script cannot emit — which is the reader that closed the
original defect. What is unread is uniqueness: nothing forbids a second normalisation
elsewhere, and Appendix A.3 shows two checkers shipping capitalised severities that the
map does not translate at all.

### EVD-3 — the output shape is probed, never described

The catalogue of what each checker emits is produced by running the checkers and recording
what came back. It is not written by hand, and a rule may only be written against a path
that appears in it.

**Why:** a hand-written shape is a claim about a program, and it decays the moment the
program changes. The registry's rules are written against these paths; a path that was
never emitted produces `NO_DATA` on every site forever, and looks exactly like a site with
nothing to report.
**Reader:** enforced. `tools/audit_assertions.py` fails the build when a registry rule
names a path the catalogue does not document, and the catalogue is regenerated by
`tools/probe_shapes.py` from the registry's own job list. This is the strongest reader in
the document and the reason the "58 documents" problem is not one.

### EVD-4 — the catalogue describes this tree, and says so accurately

The catalogue's own account of itself — how many checkers it covers, which of them break
the shared convention and how — is derived from the tree rather than written beside it.

**Why:** the catalogue is the document a rule-writer reads before writing a rule. Its
opening paragraph is where they learn which checkers are exceptions, and an exception it
fails to name is a rule written against a field that is not there.
**Reader:** **none**, and it is wrong today in two ways at once (Appendix A.1). The
document says it covers "all 57 scripts the registry runs" — the registry runs 58 — and it
omits one of the two extra checkers it actually documents. Its account of the deviants
names three scripts and calls them four, and attributes to one script a deviation that
both of them have.

### EVD-5 — `truncated` is a claim about coverage, and it changes verdicts

A checker that read a capped input says so. The claim travels: a rule that would pass *by
absence* over a truncated input is downgraded rather than believed.

**Why:** "no violations found" over half a site is not a finding about the site. This is
the field-level half of the rule `specs/run-lifecycle/` RUN-19 states.
**Reader:** enforced, and the reader is unusually good. A sweep over every registry item
whose rule passes by absence asserts that a truncated input downgrades it; the asymmetry
is pinned in both directions — a defect found in the part that *was* read still fails, and
a failing count is named as a floor; and the set of checkers able to set the flag is
derived from the scripts themselves rather than listed, so a checker that gained the
ability and did not use it would be caught. The one unread half — that the flag propagates
from a real truncated crawl rather than being injected by a test — is not this
requirement's: `specs/run-lifecycle/` RUN-19 states it and records it as unread there.

### EVD-6 — every number a verdict depends on names what it rests on

A threshold in a checker is `standard` (somebody else's published rule), `measured` (from
data recorded here), `convention` (this tree's choice, stated) or `inherited` (it came with
the code and nobody has defended it). Every such number carries its basis in the source,
and no number that decides a verdict may carry none.

**Why:** a threshold with no stated basis cannot be argued with, and a client's first
question about a `FAIL` is where the line came from. `inherited` is an honest answer and
also a debt; the point of naming it is that the debt is countable.
**Reader:** enforced. `tools/audit_thresholds.py --check` runs in CI over every number a
verdict depends on and fails when one names no basis. It reports 146 such numbers today —
11 `standard`, 11 `measured`, 47 `convention`, 77 `inherited`, and **0 with no basis**.
The gate holds the floor; the 77 are the debt it makes visible.

### EVD-7 — something must assert that a checker's answer is right

For every checker, at least one of two things exists: a test that names it and asserts
what it returns for a constructed input, or a settled declaration in the fixture oracle for
an item it decides. A checker with neither is exercised and unjudged: it runs on every
audit, produces a verdict, and nothing anywhere says that verdict is correct.

**Why:** running is not the same as being right. Twenty of the fifty-eight are named by no
test function, and the census shows every one of them producing real verdicts on served
trees — so the suite's green is evidence that they *run*, and evidence of nothing else.
What stands behind them is the oracle, which is a different instrument with a different
cost, and knowing which checkers rest on it is the difference between a covered layer and
a lucky one.
**Reader:** **none.** Nothing computes this. It was computed by hand for Appendix A.2 and
the answer is one checker short of clean, which is exactly the kind of margin that will not
survive the next release unwatched.

### EVD-8 — a log format the audit cannot read is refused by name

Server-log evidence accepts Combined Log Format and its JSON equivalents. Common Log
Format is **refused**, with the reason: it has no User-Agent field, and every question this
evidence answers is a question about which agent made the request.

**Why:** a format that parses but cannot carry the answer is worse than one that fails to
parse. Reading CLF and reporting "no crawler activity" would be a true statement about a
file and a false one about the site.
**Reader:** partial. The parser distinguishes the two formats and the refusal is written
into the checker with its reason; what is unread is the refusal as a *contract* — nothing
asserts that a CLF file produces the refusal rather than an empty result.

### EVD-9 — below a week, "never crawled" is not a finding

Server-log coverage claims require a window of at least seven days, and rate claims require
a minimum volume of requests. Below either, the checker declines to report rather than
reporting an absence.

**Why:** a crawler that visits weekly has not skipped a URL it has not reached yet. An
absence over three days of logs is a statement about the log, and reporting it as a
statement about the site produces work nobody needed to do.
**Reader:** partial. Both constants exist and are named in the source with their reasoning
— seven days for coverage, fifty requests for rates. Whether the decline actually happens
below them is asserted for one of the two.

### EVD-10 — AI crawlers are counted apart from search engines, and verification is opt-in

An AI crawler's requests are reported separately from a search engine's. Confirming that a
request claiming to be a crawler really came from one costs reverse DNS, so it is opt-in
and its absence is stated rather than assumed.

**Why:** the two populations answer different questions — one is about being indexed, the
other about being ingested — and averaging them answers neither. And a user agent string is
a claim by the client: counting unverified claims as crawler traffic is how a log audit
reports a bot problem that is somebody's scraper.
**Reader:** partial. The separation is implemented and exercised; the opt-in flag exists.
Nothing asserts that unverified counts are labelled as unverified where they are read.

## 4. Invariants

* **INV-E1** — every script the registry names is documented in the catalogue.
  *Reader: enforced* — a test asserts the catalogue covers every script the registry runs,
  and a second asserts it covers the ones the runner runs itself. Measured: 58 named, 58
  documented, plus two the runner invokes directly.
* **INV-E2** — no registry rule reads a path the catalogue does not document.
  *Reader: enforced* — `audit_assertions.py`, in CI, and it fails the build rather than
  warning.
* **INV-E3** — `error_kind` is `None` exactly when `error` is `None`, in every checker that
  exposes a fetch result. *Reader: partial* — the failure direction is asserted seven times
  over in `specs/http/`'s vocabulary test; the success direction is asserted nowhere, and
  this invariant is stated in the catalogue's own prose.
* **INV-E4** — a checker's severity words are drawn from the four, after normalisation.
  *Reader: partial* — `audit_assertions.py` fails a rule asking for a severity its script
  cannot emit, which reads the rule side. Nothing reads the checker side, and two checkers
  emit capitalised severities that no alias translates.

## 5. What this document does not decide

* what any *particular* checker should measure, or where its line should fall. This
  document requires the line to name its basis (EVD-6); it does not adjudicate the number,
  and `audit_thresholds.py` counting 77 `inherited` is the measure of how much of that is
  undecided;
* whether an item measures what its title claims — `specs/registry/` REG-6;
* how a checker's output becomes a status — `specs/registry/` and `specs/verdicts/`;
* what a declaration about a checker's answer may claim — `specs/declarations/`;
* how the checkers are permitted to reach the network — `specs/http/`.

## 6. Open questions

**Should the catalogue be generated in CI rather than by hand?** EVD-3's reader fails the
build when a rule outruns the catalogue, which is the important direction. The catalogue
itself is regenerated by running a tool against a live URL, by a person, when they remember
— and its opening paragraph is now wrong in two ways (A.1), which is what that arrangement
produces. Generating it in CI needs a live site, which is the reason it is not. What would
settle it: whether the fixture server can stand in for the live URL for shape purposes,
since a shape is about keys rather than values.

**What is the contract for a checker that can answer partly?** `truncated` covers a capped
input. A checker that read the page but could not reach a sub-resource — a stylesheet, an
image, a linked page — has no way to say "this answer is about four of the six things you
asked about". Today it either omits them silently or reports them as findings. What would
settle it: whether any current rule would change its verdict if it knew, which is
answerable from the catalogue.

**Is `inherited` a basis or the absence of one?** EVD-6 accepts four bases and 77 of 146
numbers claim the fourth, which means the gate passes while more than half the thresholds
in the tree are undefended. Treating `inherited` as a failure would redden CI today and for
a long time; treating it as a basis is what allows the number to stay at 77 for releases at
a stretch. What would settle it: a ratchet — `inherited` permitted but never permitted to
*increase*, which is the shape this tree already uses for its other debts.

## Appendix A — measured disagreements, 4 September 2026

Observation, not specification. Measured at commit `f81f0a3`, registry `b0abf2819da0`.

### A.1 — the catalogue's account of itself is wrong in two ways

The first paragraph of `script-output-shapes.md` is what a rule-writer reads before writing
a rule. It says:

> All 57 scripts the registry runs are documented here, plus `site_crawl.py` …

Measured: the registry names **58** scripts, and `site_crawl.py` is not among them. The
document contains **60** sections — the 58, plus `site_crawl.py`, plus `detect_profile.py`,
which its own sentence does not mention. So the count is one low and the list of extras is
one short.

The same paragraph accounts for the deviants:

> Four of them break the `issues[].severity` + `message` convention … `gsc_checker.py` and
> `indexnow_checker.py` capitalise severity, `indexnow_checker.py` uses `finding` instead
> of `message`, and `robots_path_tester.py` emits no `issues[]` at all.

Measured: **three** scripts deviate, not four, and `gsc_checker.py` uses `finding` as well
— the sentence attributes to one script a deviation both of them have. A rule-writer
reading it would expect `gsc_checker.py` to carry `message`.

| script | capitalised severity | `finding` instead of `message` | no `issues[]` |
|---|---|---|---|
| `gsc_checker.py` | yes | **yes** — undocumented | — |
| `indexnow_checker.py` | yes | yes | — |
| `robots_path_tester.py` | — | — | yes |

Nothing reads any of it. This is the same shape as the registry's own `source` string
(REG-12) and the four drifted counts in the census tooling: a number written beside the
thing it counts, reproduced faithfully by every gate, compared with nothing.

### A.2 — twenty checkers are exercised and unjudged, and one is neither

Counted three ways, because the obvious count is misleading.

**Named by a test function:** 38 of 58. The other **20** appear inside no test function in
the suite. Median mentions across all 58 is one.

**Exercised:** all 20 of them. The recorded census has every one producing real verdicts on
served trees — `FAIL` and `PASS` for most, three answers for some. So the suite's green
does say they run; it does not say anything about whether they run correctly.

**Judged:** 31 of the 33 registry items behind those 20 checkers carry a *settled*
declaration in the fixture oracle. That is what stands behind this layer — not the unit
suite but the instrument `specs/declarations/` specifies, one hand-written prediction at a
time.

Which leaves exactly one checker with neither:

| checker | item | why nothing judges it |
|---|---|---|
| `collection_page_checker.py` | `AR-154` | named by no test; its only declarations are `INDETERMINATE` on both origins |

`AR-154` is one of the twenty-seven declarations `specs/declarations/` A.1 found compared
with nothing — one of the seventeen whose written reason is "the fixture has no subject for
this item", because the fixture is a five-page bakery with no category page. So the single
checker in this tree that nothing asserts anything about is the one whose declaration was
parked under the ninth word. Two documents found the same hole from opposite ends, and it
is one item wide.

### A.3 — two checkers speak a severity vocabulary nothing translates

`SEVERITY_ALIAS` maps `error`, `warning`, `warn`, `info` and `notice` onto the four. It
does not map `High`, `Medium` or `Critical`, and `gsc_checker.py` and
`indexnow_checker.py` emit exactly those.

The evaluator lowercases before looking a severity up, so the capitalised words resolve to
themselves and land inside the vocabulary by accident rather than by translation. It works.
Nothing states that it works, and nothing would fail if a checker emitted `Warning` — which
lowercases to `warning`, which the alias maps to `medium`, so that one would work too, for
a different reason. Three spellings, two mechanisms, one of them unwritten.

### A.4 — the method behind A.2, and its limit

The three counts above were computed by parsing every test file into its 1 280 test
functions and asking, for each of the 58 checkers, how many function bodies name it. That
measures naming, not exercise, which is why the census and the oracle were consulted
separately.

Its limit is worth stating because it bounds the finding. A test can exercise a checker
without naming it — through the runner, through a fixture-wide sweep, through the evidence
suite's real served origin — and such a test would count as zero here. So "named by no test
function" is a lower bound on coverage, not an upper one, and A.2's claim is deliberately
the narrow one: nothing asserts these checkers' answers *by name*. The one-checker
intersection with the oracle is the claim that survives either reading.

## Appendix B — how much of this document is enforced

**Probed:** EVD-3 — deleting one checker's whole section from the catalogue makes
`audit_assertions.py` exit 1, naming three now-unseen paths, and reddens a test in
`test_registry.py`. EVD-6 — the gate reports 146 numbers a verdict depends on, none
without a basis. INV-E1 — reconciled by counting: 58 named, 58 documented, two extra.
A.2's three counts were computed by parsing all 1 280 test functions, then cross-read
against the recorded census and the fixture manifest.

**Derived, not probed:** the five `partial` rows and the two `none` rows. Each names which
half it believes unread.

| | requirements |
|---|---|
| **enforced** | EVD-3, EVD-5, EVD-6 |
| **partial** | EVD-1, EVD-2, EVD-8, EVD-9, EVD-10 |
| **none** | EVD-4, EVD-7 |
| **opposed** | — none |

Invariants: INV-E1 and INV-E2 enforced; INV-E3 and INV-E4 partial.

**Three enforced, five partial, two unread, of ten.**

This is the best-read layer in the suite so far, and the reason is specific enough to be
worth copying. Its three enforced requirements are all held by *generated* readers — a
catalogue produced by probing, an auditor that walks every rule against it, a threshold
census that classifies every number a verdict depends on. None of them is a test somebody
wrote about a case they thought of; each is a derivation over the whole population, which
is why none of them has the coverage gaps the hand-written tests have.

The two unread requirements are the two that ask the layer to describe *itself*: whether
the catalogue's own account is true (EVD-4), and whether anything judges each checker
(EVD-7). Both were computed by hand for Appendix A, both found something, and neither has
a reader — which is the same sentence this suite has now written about the registry's
`source` string, the census tooling's four counts, and the notebook's spec list. Four
instances is not a coincidence; a derivation is only as good as the question somebody
thought to derive.
