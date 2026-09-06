# Evidence — what a checker owes, and what may be believed of what it returns

## Purpose

What the fifty-eight checker scripts owe the runner, and what the runner is entitled to
assume about anything one of them returns. One contract plus a generated catalogue, not
fifty-eight documents.

The contract exists because the runner cannot read a checker's mind: it launches a
process, reads one JSON document, and grades an item against a path in it. Every rule in
the registry is written against that shape, so a checker that breaks it does not fail
loudly — it produces a verdict about a site from a shape nobody expected.

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
[`openspec/specs/verdicts/`](../verdicts/spec.md); the assertion language that reads these outputs
belongs to [`openspec/specs/registry/`](../registry/spec.md); how a checker is invoked, timed out
and classified when it fails belongs to
[`openspec/specs/run-lifecycle/`](../run-lifecycle/spec.md); how it is permitted to reach the
network belongs to [`openspec/specs/http/`](../http/spec.md). This document says what the process
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

## Requirements

### Requirement: EVD-1 — a checker is a process with one output, and exit 0 means "I ran"

A checker SHALL write one JSON document to standard output and exit 0. A checker that
cannot reach the site, cannot parse the page, or has nothing to say MUST still exit 0 and
return its defined empty shape.

**Why:** the runner classifies a non-zero exit as a crash, which is a defect report about
the checker. A checker that exits non-zero to mean "the site was down" produces a
maintenance ticket instead of a `NO_DATA`, and the two are read by different people.
**Reader:** partial. The five failure kinds and their labels are pinned by the runner's
tests, and every checker is exercised end to end against a real served origin by the
evidence suite, so a checker that exited non-zero on a normal page would fail there. What
is unread is the *empty* case as a contract: nothing asserts that each checker, given
nothing to work with, exits 0 rather than raising — it is asserted for the handful whose
tests construct that case and inherited for the rest.

#### Scenario: the site could not be reached
- **WHEN** a checker cannot fetch what it was asked about
- **THEN** it exits 0 and returns its empty shape, saying so in its own fields
- **AND** it does not exit non-zero, which the runner would classify as a crash and
  report as a defect in the checker rather than a fact about the site

#### Scenario: the checker genuinely broke
- **WHEN** a checker raises rather than returning
- **THEN** a non-zero exit is correct, and the runner is right to call it a crash

#### Scenario: output that is not one JSON document
- **WHEN** anything other than a single JSON document reaches standard output
- **THEN** the contract is broken, whatever the exit code says

### Requirement: EVD-2 — findings speak one severity vocabulary, normalised once

A finding's severity SHALL be `critical`, `high`, `medium` or `low`. Where a checker
inherited another vocabulary, exactly one place translates it, and no rule and no report
MAY see the untranslated word — every consumer MUST see the normalised one.

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

#### Scenario: a checker speaks another vocabulary
- **WHEN** a checker emits a severity word from a vocabulary it inherited
- **THEN** exactly one place translates it, before any rule or report sees it

#### Scenario: a rule written against the untranslated word
- **WHEN** a registry rule names a severity the normalisation would have removed
- **THEN** it can never match, and the item quietly stops deciding anything

#### Scenario: a fifth word appears
- **WHEN** a checker emits a severity outside the four
- **THEN** it is caught rather than passed through, on the checker's side as well as the
  rule's

### Requirement: EVD-3 — the output shape is probed, never described

The catalogue of what each checker emits SHALL be produced by running the checkers and
recording what came back. It MUST NOT be written by hand, and a rule MAY only be written
against a path that appears in it.

**Why:** a hand-written shape is a claim about a program, and it decays the moment the
program changes. The registry's rules are written against these paths; a path that was
never emitted produces `NO_DATA` on every site forever, and looks exactly like a site with
nothing to report.
**Reader:** enforced. `tools/audit_assertions.py` fails the build when a registry rule
names a path the catalogue does not document, and the catalogue is regenerated by
`tools/probe_shapes.py` from the registry's own job list. This is the strongest reader in
the document and the reason the "58 documents" problem is not one.

#### Scenario: a rule names a path no checker emits
- **WHEN** a registry rule asserts on a key absent from the catalogue
- **THEN** the build fails, naming the path
- **AND** the item does not ship reading a field that will never arrive

#### Scenario: the catalogue is edited by hand
- **WHEN** a section is written rather than probed
- **THEN** it describes what somebody believed, which is the thing this requirement
  exists to prevent

#### Scenario: a checker's shape changes
- **WHEN** a checker starts or stops emitting a key
- **THEN** regenerating the catalogue shows it, and any rule left pointing at the old
  path fails

### Requirement: EVD-4 — the catalogue describes this tree, and says so accurately

The catalogue's own account of itself — how many checkers it covers, which of them
break the shared convention and how — SHALL be derived from the tree rather than written
beside it.

**Why:** the catalogue is the document a rule-writer reads before writing a rule. Its
opening paragraph is where they learn which checkers are exceptions, and an exception it
fails to name is a rule written against a field that is not there.
**Reader:** enforced. `tools/audit_catalogue.py` derives the account and writes it
into the file between two markers; `--check` runs in CI and in
`tests/test_registry.py::TheCatalogueDescribesThisTree`, which also asks the questions
the gate cannot ask about itself — that the classes partition the documented set, that
none of them is empty because the parser went blind, and that three known deviants land
where reading the script puts them rather than where the file says.

The counts come from `checklist.json` and the `###` headings. The convention classes come
from the catalogue's own body, the `item keys:` line under each `issues[]`, because that
line is the evidence a rule-writer would act on. Severity *case* cannot come from there —
the probe records keys, not values — so it comes from the same AST read
`tools/audit_assertions.py` performs in CI, with the case kept.

#### Scenario: the catalogue counts itself
- **WHEN** the catalogue states how many checkers it documents
- **THEN** that number is computed from the registry and the tree at generation time

#### Scenario: a checker is added
- **WHEN** the registry gains a script
- **THEN** the stated count moves with it, without anyone editing a sentence

#### Scenario: the count is a literal
- **WHEN** the number is typed into the prose beside the thing it counts
- **THEN** it is wrong within a release and nothing says so — which is the state this
  requirement records as its own violation

### Requirement: EVD-5 — `truncated` is a claim about coverage, and it changes verdicts

A checker that read a capped input SHALL say so. The claim travels: a rule that would
pass *by absence* over a truncated input MUST be downgraded rather than believed.

**Why:** "no violations found" over half a site is not a finding about the site. This is
the field-level half of the rule `openspec/specs/run-lifecycle/` RUN-19 states.
**Reader:** enforced, and the reader is unusually good. A sweep over every registry item
whose rule passes by absence asserts that a truncated input downgrades it; the asymmetry
is pinned in both directions — a defect found in the part that *was* read still fails, and
a failing count is named as a floor; and the set of checkers able to set the flag is
derived from the scripts themselves rather than listed, so a checker that gained the
ability and did not use it would be caught. The one unread half — that the flag propagates
from a real truncated crawl rather than being injected by a test — is not this
requirement's: `openspec/specs/run-lifecycle/` RUN-19 states it and records it as unread there.

#### Scenario: half a site, nothing found
- **WHEN** a checker caps its input and a rule passes because it found none of the thing
  it forbids
- **THEN** the pass is downgraded, because absence over part of a site is not a finding
  about the site

#### Scenario: a defect found before the cap
- **WHEN** the same truncated input yielded a real finding
- **THEN** the finding survives, and its count is named as a floor

#### Scenario: a checker that caps and does not say so
- **WHEN** a checker limits what it read and returns no truncation claim
- **THEN** every absence it reports is believed, which is the failure this requirement
  exists to prevent

### Requirement: EVD-6 — every number a verdict depends on names what it rests on

A threshold in a checker SHALL be `standard` (somebody else's published rule),
`measured` (from data recorded here), `convention` (this tree's choice, stated) or
`inherited` (it came with the code and nobody has defended it). Every such number MUST
carry its basis in the source,
and no number that decides a verdict may carry none.

**Why:** a threshold with no stated basis cannot be argued with, and a client's first
question about a `FAIL` is where the line came from. `inherited` is an honest answer and
also a debt; the point of naming it is that the debt is countable.
**Reader:** enforced. `tools/audit_thresholds.py --check` runs in CI over every number a
verdict depends on and fails when one names no basis. It reports 146 such numbers today —
11 `standard`, 11 `measured`, 47 `convention`, 77 `inherited`, and **0 with no basis**.
The gate holds the floor; the 77 are the debt it makes visible.

#### Scenario: a number decides a verdict
- **WHEN** a threshold in a checker separates one verdict from another
- **THEN** the source states which of the four kinds of basis it has

#### Scenario: a number with no basis at all
- **WHEN** a threshold carries no stated basis
- **THEN** the gate fails, because a number a client can be shown must be arguable

#### Scenario: an undefended number is honest about being undefended
- **WHEN** a threshold came with the code and nobody has justified it
- **THEN** `inherited` is the correct answer, and it licenses no conclusion beyond
  "this is what it has always been"

### Requirement: EVD-7 — something must assert that a checker's answer is right

For every checker, at least one of two things SHALL exist: a test that names it and
asserts what it returns for a constructed input, or a settled declaration in the fixture
oracle for an item it decides. A checker with neither is exercised and unjudged: it runs on every
audit, produces a verdict, and nothing anywhere says that verdict is correct.

**Why:** running is not the same as being right. Twenty of the fifty-eight are named by no
test function, and the census shows every one of them producing real verdicts on served
trees — so the suite's green is evidence that they *run*, and evidence of nothing else.
What stands behind them is the oracle, which is a different instrument with a different
cost, and knowing which checkers rest on it is the difference between a covered layer and
a lucky one.
**Reader:** enforced, and writing it corrected the hand count it replaces.
`test_no_checker_runs_on_every_audit_with_nothing_judging_it` computes the union rather
than searching for it: a checker is judged if a test body names it — as a filename *or* as
the module it imports — or names a RUNS key that runs it, or decides an item the oracle
predicts with a word the audit can emit. The answer is **58 of 58**, not 57.

Three exclusions make that number mean something, and each was a false credit until it was
made. Module level is excluded, because the RUNS table names every script there and
scheduling is not judging. Files that are not `test_*.py` are excluded, because
`known_issues.py` keeps a per-script cap table and a ledger's bookkeeping asserts nothing
about an answer. Docstrings and comments are stripped, because this reader's own docstring
names `collection_page_checker.py` while explaining it — the reader was, briefly, crediting
a checker for being discussed by the reader.

Probed by deleting `class CollectionPage`, the only thing that judges `AR-154`: the reader
reddens naming `collection_page_checker.py`, and it is the only single deletion that does.
`test_the_fixture_key_indirection_is_load_bearing` pins that at least one checker is judged
*only* through a RUNS key, so the resolution cannot be simplified away without the failure
that follows saying why.

#### Scenario: a checker with a test
- **WHEN** a test constructs an input and asserts what the checker returns for it
- **THEN** the checker is judged

#### Scenario: a checker with a settled declaration
- **WHEN** the fixture oracle predicts a verdict, in a word the audit can emit, for an
  item the checker decides
- **THEN** the checker is judged, by a different instrument at a different cost

#### Scenario: a checker with neither
- **WHEN** no test names it and every declaration for its items declines to predict
- **THEN** it runs on every audit, produces a verdict, and nothing anywhere says the
  verdict is right

#### Scenario: judged through a name it is never called by
- **WHEN** a test reaches a checker through a fixture key rather than its filename
- **THEN** it is judged nonetheless, and a census that searched for the filename would
  have reported it uncovered

### Requirement: EVD-8 — a log format the audit cannot read is refused by name

Server-log evidence SHALL accept Combined Log Format and its JSON equivalents. Common
Log Format MUST be **refused**, with the reason: it has no User-Agent field, and every question this
evidence answers is a question about which agent made the request.

**Why:** a format that parses but cannot carry the answer is worse than one that fails to
parse. Reading CLF and reporting "no crawler activity" would be a true statement about a
file and a false one about the site.
**Reader:** partial. The parser distinguishes the two formats and the refusal is written
into the checker with its reason; what is unread is the refusal as a *contract* — nothing
asserts that a CLF file produces the refusal rather than an empty result.

#### Scenario: a log without a user agent
- **WHEN** an operator supplies Common Log Format
- **THEN** it is refused, and the refusal says the format has no User-Agent field

#### Scenario: a refusal that reads as an absence
- **WHEN** an unreadable log produces "no crawler activity" instead of a refusal
- **THEN** the operator is told something false about their site rather than something
  true about their file

### Requirement: EVD-9 — below a week, "never crawled" is not a finding

Server-log coverage claims SHALL require a window of at least seven days, and rate
claims a minimum volume of requests. Below either, the checker MUST decline to report
rather than report an absence.

**Why:** a crawler that visits weekly has not skipped a URL it has not reached yet. An
absence over three days of logs is a statement about the log, and reporting it as a
statement about the site produces work nobody needed to do.
**Reader:** partial. Both constants exist and are named in the source with their reasoning
— seven days for coverage, fifty requests for rates. Whether the decline actually happens
below them is asserted for one of the two.

#### Scenario: three days of log
- **WHEN** the supplied window is shorter than seven days
- **THEN** the checker declines to claim anything about crawl coverage

#### Scenario: a page absent from a short window
- **WHEN** a page does not appear in a three-day log
- **THEN** that is not reported as "never crawled", because the window is too short for
  the absence to mean anything

### Requirement: EVD-10 — AI crawlers are counted apart from search engines, and verification is opt-in

An AI crawler's requests SHALL be reported separately from a search engine's.
Confirming that a request claiming to be a crawler really came from one costs reverse DNS,
so it MAY be opt-in, and where it was not done the report MUST say so rather than let the
reader assume it was.

**Why:** the two populations answer different questions — one is about being indexed, the
other about being ingested — and averaging them answers neither. And a user agent string is
a claim by the client: counting unverified claims as crawler traffic is how a log audit
reports a bot problem that is somebody's scraper.
**Reader:** partial. The separation is implemented and exercised; the opt-in flag exists.
Nothing asserts that unverified counts are labelled as unverified where they are read.

#### Scenario: two kinds of crawler in one log
- **WHEN** a log contains both search-engine and AI-crawler requests
- **THEN** they are counted and reported apart

#### Scenario: verification was not requested
- **WHEN** reverse-DNS confirmation is off
- **THEN** the report says the user-agent strings were taken at their word
- **AND** it does not present unverified counts as verified ones

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
  over in `openspec/specs/http/`'s vocabulary test; the success direction is asserted nowhere, and
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
* whether an item measures what its title claims — `openspec/specs/registry/` REG-6;
* how a checker's output becomes a status — `openspec/specs/registry/` and `openspec/specs/verdicts/`;
* what a declaration about a checker's answer may claim — `openspec/specs/declarations/`;
* how the checkers are permitted to reach the network — `openspec/specs/http/`.

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

#### A.1 — the catalogue's account of itself was wrong in every clause

Closed in 0.93.3. The first paragraph of `script-output-shapes.md` is what a rule-writer
reads before writing a rule. It said:

> All 57 scripts the registry runs are documented here, plus `site_crawl.py` … Four of
> them break the `issues[].severity` + `message` convention … `gsc_checker.py` and
> `indexnow_checker.py` capitalise severity, `indexnow_checker.py` uses `finding` instead
> of `message`, and `robots_path_tester.py` emits no `issues[]` at all.

Measured: the registry names **58** scripts. The document holds **60** sections — those
58, plus `site_crawl.py` and `detect_profile.py`, and the sentence named one of the two.
The convention clause is the interesting half:

| the file's own body says | scripts |
|---|---|
| `issues[]` with `severity` **and** `message` | 18 |
| no root `issues[]` at all | 15 |
| an `issues[]` and no record of what is in one | 22 |
| the human text under another key (`finding`) | 5 |
| a severity the source can capitalise | 7 |

Four was not an undercount by one. It was the count of the scripts the sentence itself
named.

**And an earlier draft of this appendix made the same mistake one level up.** It reported
"three scripts deviate, not four" — having checked the three the sentence named, found
the fourth was a double-count, and stopped. Correcting a list's arithmetic without asking
whether the list is complete leaves the reader with a number that is now right about the
wrong set. The derivation enumerates instead: it classifies every documented section, and
`test_every_documented_script_is_classified_exactly_once` fails if the classes stop
covering them.

Two of the five rows are gaps in this file rather than facts about the scripts. Twenty-two
sections record an `issues[]` and never say what an element looks like — the probe saw the
key and captured no element — so a rule naming a field inside one of those is a guess, and
the paragraph now says so where it used to say nothing.

#### A.2 — twenty checkers are exercised and unjudged, and none is unjudged

**Corrected 5 September 2026. This heading used to end "and one is neither", and the
paragraph naming that one was wrong.** The count behind it looked for each script's
filename inside test function bodies. `collection_page_checker.py` is judged in both
directions by `class CollectionPage`, which reaches it through the RUNS keys `collection`
and `collection_bad` and never types the script's name — so the search could not see it,
and reported the only gap in the layer. Three more — `indexability_matrix.py`,
`local_seo_checker.py`, `security_headers.py` — are written `import security_headers as sh`
rather than `"security_headers.py"`, and the same search would have missed them too had it
been asked. The corrected figure is **58 of 58 judged**, now computed by EVD-7's reader
rather than by hand.

The rest of this section is kept as written, because its reasoning about the twenty is
still right and because the way it went wrong is itself the finding.

Counted three ways, because the obvious count is misleading.

**Named by a test function:** 38 of 58. The other **20** appear inside no test function in
the suite. Median mentions across all 58 is one.

**Exercised:** all 20 of them. The recorded census has every one producing real verdicts on
served trees — `FAIL` and `PASS` for most, three answers for some. So the suite's green
does say they run; it does not say anything about whether they run correctly.

**Judged:** 31 of the 33 registry items behind those 20 checkers carry a *settled*
declaration in the fixture oracle. That is what stands behind this layer — not the unit
suite but the instrument `openspec/specs/declarations/` specifies, one hand-written prediction at a
time.

This is where the original concluded "which leaves exactly one checker with neither", and
named `collection_page_checker.py` / `AR-154`. It does not.

`AR-154` is genuinely one of the twenty-seven declarations
[`openspec/specs/declarations/`](../declarations/spec.md) A.1 found compared with nothing — one of
the seventeen whose written reason is "the fixture has no subject for this item", because
the fixture is a five-page bakery with no category page. And its checker is genuinely named
by no test. Both halves were true.

The conclusion drawn from them was not, and that is the part worth keeping. Two documents
appeared to find one hole from opposite ends, and the agreement read as corroboration:
*unpredicted* from the declaration side, *unnamed* from the test side, and the conjunction
taken for *unjudged*. Neither side was wrong about its own half; the conjunction was, and it
made the most convincing finding in this document the only false one.

#### A.3 — two checkers speak a severity vocabulary nothing translates

`SEVERITY_ALIAS` maps `error`, `warning`, `warn`, `info` and `notice` onto the four. It
does not map `High`, `Medium` or `Critical`, and `gsc_checker.py` and
`indexnow_checker.py` emit exactly those.

The evaluator lowercases before looking a severity up, so the capitalised words resolve to
themselves and land inside the vocabulary by accident rather than by translation. It works.
Nothing states that it works, and nothing would fail if a checker emitted `Warning` — which
lowercases to `warning`, which the alias maps to `medium`, so that one would work too, for
a different reason. Three spellings, two mechanisms, one of them unwritten.

#### A.4 — the method behind A.2, and its limit

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
| **enforced** | EVD-3, EVD-4, EVD-5, EVD-6, EVD-7 |
| **partial** | EVD-1, EVD-2, EVD-8, EVD-9, EVD-10 |
| **none** | — none |
| **opposed** | — none |

Invariants: INV-E1 and INV-E2 enforced; INV-E3 and INV-E4 partial.

**Five enforced, five partial, none unread, of ten.**

This is the best-read layer in the suite so far, and the reason is specific enough to be
worth copying. Its three enforced requirements are all held by *generated* readers — a
catalogue produced by probing, an auditor that walks every rule against it, a threshold
census that classifies every number a verdict depends on. None of them is a test somebody
wrote about a case they thought of; each is a derivation over the whole population, which
is why none of them has the coverage gaps the hand-written tests have.

The two requirements that ask the layer to describe *itself* were the unread ones: whether
the catalogue's own account is true (EVD-4), and whether anything judges each checker
(EVD-7). Both were computed by hand for Appendix A, both found something, and neither had
a reader. EVD-7 has one now, and the first thing it did was overturn what the hand count
found — the layer is clean, and the gap the document reported did not exist. EVD-4's hand
count stands and is a defect in the catalogue's own prose rather than a missing reader — which is the same sentence this suite has now written about the registry's
`source` string, the census tooling's four counts, and the notebook's spec list. Four
instances is not a coincidence; a derivation is only as good as the question somebody
thought to derive.
