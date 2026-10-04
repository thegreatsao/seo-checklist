# Governance — what this repository does to keep itself honest, and what it declines to claim

## Purpose

The machinery that watches the other eleven capabilities — the basis every deciding
constant carries, the recorded ledgers of defects and inert findings, the audits that walk
the registry, the CI matrix, and the reader over these documents themselves.

Everything here is an instrument rather than a behaviour, which is what makes this layer's
failures distinctive: an instrument that has stopped pointing at anything still runs, still
passes, and still reads as coverage. Four calibration checks existed, passed and gated
nothing until this document went looking.

**Capability:** the machinery that watches the tool rather than the site — basis lines on
constants, the calibration reports behind some of them, the recorded ledgers of known
defects and inert findings, the static registry audits, the CI gates, and how the whole
thing is packaged (C38, C39, C42–C45 of the capability inventory).

This document is normative and is written as though no code existed. Where the
implementation disagrees, the implementation is presumed wrong until this document is
changed by argument. Appendix A records disagreements measured on 4 September 2026.

Every requirement carries a **Reader** line naming what makes it fail when violated;
Appendix B is the census of those lines. A requirement whose reader is `none` is an
intention, and is counted as one.

**Inherited, not restated:** the two instruments that measure the audit against served
trees belong to [`openspec/specs/declarations/`](../declarations/spec.md); what the documents in
`openspec/specs/` must contain, and the reader that holds them, are described in this document and
implemented by `tests/test_specs.py`.

---

## 1. The layer that watches the other eleven

Every other document in this suite describes something the audit does to a site. This one
describes what the repository does to itself: the gates that run before a release, the
records of what is known to be wrong, and the audits that walk the registry looking for
rules that cannot fire.

It is written last on purpose, because it is the only place from which the pattern across
the other eleven is visible. Having now censused every layer, one shape has appeared in
six of them, and it is worth stating once here rather than eleven times:

> **A mechanism gets a reader. The list the mechanism runs over does not.**

The severity vocabulary is enforced for four of its five sets and unpinned for `lens`. The
redaction of secrets is enforced from five directions and the set of what counts as a
secret from none. The provenance surface has ten readers and the list of what belongs on it
has none, which is how the response cache came to be missing. The notebook's freshness gate
checked three specs by name and could not see the fourth. The declared-id set of the
fixture manifest is two literals in a test. The checkers' severity words are policed on the
rule side and not on the checker side.

Six instances, six layers, one shape. It is not carelessness — each mechanism was built
carefully, usually after a defect, and each list looked too obvious to guard. The general
rule this document takes from it is GOV-3: **a set that decides behaviour is derived from
the thing it describes, or it has a reader that says what belongs in it.**

## 2. What the machinery is

| instrument | what it watches | gates a release? |
|---|---|---|
| basis lines | every constant a verdict depends on | yes |
| calibration reports | four constants, against recorded data | yes, since this document |
| known-issues ledger | defects somebody decided to keep | yes |
| inert-findings ledger | findings no rule can act on | yes |
| registry audits (`tools/audit_*.py`) | rules that cannot fire, unreachable verdicts, titles, readings; each closes on what it does not establish | yes |
| score-sensitivity report | how much of the score one weight decides | reports only |
| CI matrix | everything above, three Pythons and Windows | — |
| `tests/test_specs.py` | the documents in `openspec/specs/` | yes |

## Requirements

### Requirement: GOV-1 — every number a verdict depends on says what it rests on

A constant that can change a verdict SHALL carry a basis: `standard` (somebody else's published
rule), `measured` (from data recorded in this repository), `convention` (this tree's choice,
stated), or `inherited` (it arrived with the code and nobody here has defended it). A number
that decides only what is printed is marked as such and is not counted among them.

**Why:** the first question a client asks about a `FAIL` is where the line came from. A
threshold with no stated basis cannot be argued with, and the honest answer "we do not know,
it came with the code" is only available if somebody wrote it down.
**Reader:** enforced. `audit_thresholds.py --check` runs in CI and fails when a
verdict-deciding number names no basis. It counts 161 such numbers at 0.144.0 — 19
`standard`, 11 `measured`, 54 `convention`, **77 `inherited`**, 0 without a basis — plus 12
that decide only presentation. No test reads the counts in this paragraph (`evidence`
EVD-6 says what that cost).

#### Scenario: a constant that can change a verdict
- **WHEN** a number in a checker or the runner separates one verdict from another
- **THEN** its source states which of the four bases it has

#### Scenario: a number with no basis
- **WHEN** such a constant carries no stated basis
- **THEN** the gate fails, naming it

#### Scenario: a number that decides nothing
- **WHEN** a constant affects formatting, ordering of equals, or a message
- **THEN** no basis is owed, because the requirement is about verdicts and not about
  every integer in the tree

### Requirement: GOV-2 — `inherited` is an admission, not a justification

`inherited` licenses no conclusion about whether a number is right. It is the recorded
absence of a decision, and it MUST NOT be cited as anything else.

**Why:** the gate passes with 77 of 146 undefended, which is fine as an accounting and
dangerous as a standard. The category exists so the debt is countable, and it stops working
the moment it reads as a fourth kind of justification.
**Reader:** partial. `tests/test_inherited_basis.py` holds the two halves a test can
reach. The count may not rise — 77 of 146 today, ratcheted downward, which is the second
scenario as an assertion. And no `inherited` line may argue its number: a declaration
carrying a URL or a phrase like "the industry standard" has recorded an absence where
there was a decision, which is the same error as the reverse and harder to notice because
it reads as thoroughness.

The full distribution over all five kinds is recorded in `tests/known-issues.json`,
because a ratchet on one column alone is satisfied by relabelling an `inherited` line
`convention` without arguing it — moving the debt rather than paying it. The two numbers
then move together and the record shows it.

**Partial, and it cannot be more.** The defence rule is a positive search: it finds what
its pattern knows, and an empty result is not proof that nothing argues its number in
words nobody thought of. A test that fires on a phrasing it has been shown to catch is
what it is; `test_the_search_for_a_defence_would_find_one` is that demonstration. And the
first scenario — an undefended number cited as justification in an argument with a client
— happens outside this repository, where nothing here reaches.

Still true, and the reason this is not `enforced`: no consumer distinguishes the kinds.
The gate counts them and treats `inherited` exactly as it treats `standard`.

#### Scenario: an undefended number is cited as justification
- **WHEN** someone argues a threshold is right because it is what the code has always
  used
- **THEN** the argument is empty: `inherited` records the absence of a decision, and an
  absence justifies nothing

#### Scenario: the count of undefended numbers rises
- **WHEN** a new constant is added with `inherited` as its basis
- **THEN** that is a deliberate act and is visible as one, rather than absorbed into a
  total nobody watches

#### Scenario: a basis is upgraded
- **WHEN** somebody measures or argues a number that was `inherited`
- **THEN** its basis changes with the argument, and the change is the record of the
  decision

### Requirement: GOV-3 — a set that decides behaviour is derived, or it has a reader

Where a list, tuple or mapping decides what the tool does, it SHALL be derived from
what it describes or read by something. This covers which words are severities,
which keys are secrets, which documents belong in a manifest, which items owe a declaration
— it is computed from the thing it describes, or a reader states what belongs in it. A
hand-kept list guarded only by the mechanism that consumes it is neither.

**Why:** this is the defect this suite found in six of its eleven layers (§1). A hand-kept
list cannot say what is missing from it, and the reader that would notice the omission is
the same line somebody would have had to edit to avoid it.
**Reader:** partial. `tools/audit_derived_sets.py` enumerates every module-level
upper-case name in `scripts/` and `tools/` bound to a list, tuple, set or dict
**literal** — a collection built by a comprehension or a call is derived, which is what
this requirement asks for, so it is out of scope by construction — and records which of
them a test imports from its module. `tests/test_derived_sets.py` re-takes the census
every run, refuses a stale record, and ratchets the unread column downward.

**Partial, and the label is the honest one twice over.** A ratchet holds "no worse",
not the requirement; and "read" here means *imported*, which is an upper bound on the
membership being asserted. Measured on 6 September 2026: **166 sets, 16 imported by a
test, 150 named by nothing outside the code that consumes them.** A looser match — the
bare name anywhere in the test corpus — reports 44, by crediting `build_checklist.PAGE`
with a test that mentions some other module's `PAGE`. The stricter measure is the one
recorded, because the flattering number is the one that would let this be called
enforced.

**At 0.126.0: 178 sets, 70 read, 108 unread, and none of them in `checklist_runner.py`.**
The runner's sixteen were measured against what each describes before anything was
written (`local/gov3/measure.py`); every relation held, so this was a reader for the
next edit rather than a repair. Where a set had a source, it became a derivation — the
three `requires` gates from one table keyed by every value the registry uses, three
orderings from the `SEVERITIES` and `VERDICTS` tuples, a second copy of the sitemap paths
from `seo_common` — and `tests/test_runner_sets.py` holds each of the rest against the
thing it describes: the registry's vocabularies, the operator language, what scripts
emit, what the classifier does with each member. Probed 11 of 11.

**At 0.127.0: 177 sets, 89 read, 88 unread; none in `build_checklist.py` either.** Its
twenty were a different shape: four were already held by a gate reading the *built
registry* — `CANNOT_FAIL` by `audit_reachability.py`'s proofs, `APPLIES_WHEN` by the REG-9
sweep, `SAME_CHECK` by `audit_item_semantics.py`, `LENS` by the build itself — which an
import census cannot see, and `tests/test_build_sets.py` ties each to that reader by name.
Measuring the rest found two tables carrying dead entries: `REQUIRES` for two scripts no
item runs, and an `EFFORT_OVERRIDES` entry equal to its category's default. Both removed;
the registry did not move. `SAME_CHECK` had one direction nothing held — a twin that is
not the same check silently loses its weight — and now it is. Probed 8 of 8.

**At 0.132.0: 180 sets, 98 read, 82 unread; none in `checklist_report.py`.** Of its six,
two had been read all along: `tests/test_report.py` imports `STATUS_ICON` and
`FIX_STATUSES` in a parenthesised import spanning lines, and the census matched an import
on one line (measured with the AST first, `local/gov3/measure_import_blindness.py`; the
second time this census under-counted its own read column — aliases at 0.104.0). The other
four are held by `tests/test_report_sets.py`, and the direction kinds, written out by hand
twice more as the tuples the Markdown and HTML sections iterated, are read off
`DIRECTION_HEADING`. Measuring `EFFORT_OVERRIDES` against what ships found an entry
describing another item — TE-176 carried `high` for "migrate to HTTP/2/3" — and three that
said `low` under a `medium` floor.

**At 0.133.0: 182 sets, 100 read, 82 unread.** Two sets were added and both arrived with a
reader: `checklist_runner.PROFILE_KEYS`, the closed vocabulary of a profile (`registry`
REG-13), and `build_checklist.RETIRED`, empty, held against the registry's whole history
(`registry` REG-4).

**At 0.144.0: 182 sets, 101 read, 81 unread — and the set that moved did not earn it.**
`calibrate_css_minification._RUNTIME` is an empty dict the tool fills when it runs. It is
in the census because it is written as a literal, and it counts as read because a new
test fills it with `mock.patch.dict`: a test file that names a set is all this census can
see. Nothing asserts what belongs in it, and it has no hand-kept members to assert. The
ratchet is 81 for the reason given at 0.104.0 — it holds the best number the instrument
can currently justify — and this paragraph is the record that the number flatters.

Two lists were converted to derivations during this suite's writing — the notebook's spec
manifest, and this document's own reader discovering documents by glob rather than by
name — and neither conversion was required by anything. That is what the census now
makes visible: not that a list is wrong, but that nothing would notice if it were.

#### Scenario: a list decides what the tool does
- **WHEN** a list, tuple or mapping determines behaviour — which words are severities,
  which keys are secrets, which documents belong in a manifest
- **THEN** it is derived from what it describes, or something reads it

#### Scenario: a mechanism guarded and its membership not
- **WHEN** the code that acts on the list is well tested and the list itself is not
- **THEN** the requirement is violated, and this is the shape found in six of the twelve
  layers — the mechanism gets a reader; the list it runs over does not

#### Scenario: the list cannot say what is missing from it
- **WHEN** an entry is forgotten
- **THEN** nothing fires, because the reader that would have noticed is the same line
  that was forgotten — which is why derivation is preferred to a reader over a list

### Requirement: GOV-4 — a ledger records a decision; it never excuses a defect

The known-issues ledger holds defects somebody decided to keep. Each entry SHALL carry
a claim in one sentence and either a probe that measures it or a written reason there is
none. A probe
that disagrees with its record means somebody decides whether the tree moved or the entry is
now wrong, and re-records. It never means "make the probe pass".

**Why:** a ledger that can be edited to match the code is a list of things nobody will fix,
with a green tick beside it. The probe exists so that a defect closing itself is noticed as
loudly as a defect appearing.
**Reader:** enforced, and unusually well. The ledger's own tests assert that every entry is
classified and makes a claim, that an entry without a probe carries a written reason, that
the comparison complains when a recorded value moves, that it complains when an entry is
unclassified, **and** that it is quiet on the record as recorded — the last two being the
pair that distinguishes a working check from one that always fires or never does.

#### Scenario: a defect somebody decided to keep
- **WHEN** an entry is added to the known-issues ledger
- **THEN** it carries a claim in one sentence and either a probe that measures it or a
  written reason there is none

#### Scenario: the tree moves under an entry
- **WHEN** a probe's measurement changes
- **THEN** the check fails, and somebody decides whether the entry is now wrong or the
  tree is

#### Scenario: an entry edited to match the code
- **WHEN** a recorded measurement is changed to agree with new behaviour, with no
  decision recorded
- **THEN** the ledger has become a list of things nobody will fix, which is what this
  requirement forbids

### Requirement: GOV-5 — a ledger does not judge whether a finding is good advice

The inert-findings record says which findings no registry rule can act on. It MUST NOT
be read as saying whether those findings should be acted on, and its existence is not an argument for moving a
verdict.

**Why:** the code cannot tell deliberate advice from a claim an item must keep. A tool that
called both defects would need exemptions, and the exemptions would make it useless within
two releases.
**Reader:** partial. The record is kept in step by a CI gate, and its own header states the
rule at length. That the rule is *followed* — that no verdict moved because something was
listed here — is not the kind of thing a test can hold, and the document says so rather than
pretending otherwise.

#### Scenario: a finding no rule can act on
- **WHEN** a checker reports something no registry rule reads
- **THEN** the inert-findings record says so

#### Scenario: the record used as an argument
- **WHEN** somebody cites the record as grounds for adding a rule, or for not adding one
- **THEN** the citation is out of bounds: the record says what is unread, not what is
  worth reading

### Requirement: GOV-6 — a static audit proves one thing and disclaims the rest

Each audit — every `tools/audit_*.py` — SHALL state what it establishes and what it does
not. None of them argues that a threshold is *right*; they establish that a rule can fire,
that a verdict is reachable or declared unreachable, that a title and its rule have been
read against each other, that every number carries a basis, and that a record is in step
with what it records.

**Why:** four green audits read as "the registry is correct" unless each says what it
checked. The gap between "this rule can produce FAIL" and "this rule produces FAIL on the
right sites" is the whole of `openspec/specs/declarations/`, and a reader who conflates them stops
looking.
**Reader:** partial. `tests/test_audit_scope.py` holds the first scenario for every
`tools/audit_*.py`, found by globbing: each declares `ESTABLISHES` and `DOES_NOT_ESTABLISH`,
no two share a sentence, and a passing run closes on both — the eight gates as the
workflow invokes them, the score-sensitivity report over a results file, the revision
audit's `main` over an agreeing walk. The second scenario is a reader taking a green audit
for a right threshold anyway: the output now says it is not one, and whether that is read
is outside any program, GOV-5's limit.

This line said until 0.125.0 that the disclaimers lived "in their docstrings and in no
test". Measured on a pass: three audits of ten said somewhere in their output what they
did not claim, none last and none read by a test, and `audit_item_semantics.py` ended on
`OK`.

#### Scenario: an audit states its own limits
- **WHEN** a registry audit passes
- **THEN** its output says what that establishes and what it does not

#### Scenario: an audit read as proof of correctness
- **WHEN** a green audit is taken to mean a threshold is right
- **THEN** the claim exceeds the instrument: these audits establish that a rule can fire
  and that a verdict is reachable, never that a number is well chosen

### Requirement: GOV-7 — every gate in the matrix runs offline

The whole CI matrix SHALL run without reaching the internet: the live path is served
from a fixture inside the job.

**Why:** a gate that depends on somebody else's uptime fails for reasons that are not about
the change, and a suite that fails for reasons that are not about the change gets ignored or
re-run until green. That is how a real failure gets merged.
**Reader:** partial. `tests/test_offline.py` holds two layers. `SEO_LOOPBACK_ONLY`, set by
`tests/harness.py` for the suite and every child and by `ci.yml`'s workflow `env` for every
job (which `tools/ci_local.py` applies locally), makes the guard refuse any host but this
machine before resolving it, and keeps `whois` from starting; a tripwire at the socket
(`tests/tripwire/`) raises in the test process and ends a child on any other request, so a
path around the guard fails loudly. Each is probed by breaking it.

This line said until 0.124.0 that the guard "refuses everything but loopback unless the
allowance is set". It refused *private* addresses; the public internet was open, and an
audit hook over one suite run counted 68 connections to Wikimedia and 6 to Cloudflare, from
`entity_checker.py` inside fixture audits and from the known-issues probes. The same hook
after the repair: none outside the tripwire's own tests.

**Partial, for what the tripwire cannot see:** it is a Python audit hook, so a non-Python
child binary is held only if the script starting it consults the switch, as
`domain_safety_check.py` does for `whois` — a new binary would be unread. And a test that
clears the switch for itself stands both layers down for whatever it starts; two did, and
were given it back.

#### Scenario: the matrix runs with no network
- **WHEN** any job in CI runs
- **THEN** it completes without reaching the internet, the live path served from a
  fixture inside the job

#### Scenario: a gate that needs the outside world
- **WHEN** a check would depend on a third-party service being up
- **THEN** it does not belong in the matrix, because a gate that fails for somebody
  else's outage teaches people to ignore it

### Requirement: GOV-8 — a request-count ceiling is raised deliberately or not at all

CI SHALL assert an upper bound on how many requests one audit of the fixture site
makes. The number is a decision and MUST be changed by argument, not by observation.

**Why:** the fan-out is the audit's rudeness, and it grows silently — one more checker, one
more page in the sample. A ceiling that follows the measurement is a record of what
happened, not a limit.
**Reader:** enforced. The live job counts the fixture server's requests and fails above the
ceiling, with a comment in the workflow recording the history — 97, then 201, then 20 for
the same command as the shared crawl and then the response cache landed — and the
instruction to raise it deliberately or not at all.

#### Scenario: an audit gets more expensive
- **WHEN** one audit of the fixture site makes more requests than the ceiling
- **THEN** CI fails

#### Scenario: the ceiling is raised
- **WHEN** the number is changed
- **THEN** it is changed by argument
- **AND** raising it to whatever the run happened to make is the move this requirement
  exists to prevent

### Requirement: GOV-9 — the normative documents are read by something

The documents in `openspec/specs/` SHALL be checked: every requirement carries an
argument and a named reader, the census tabulates them without flattering, every test and tool they name exists,
and no identifier means two things.

**Why:** the documents' whole value is that their census is honest. It has been wrong seven
times across the twelve documents, always in the same direction, and always by the same
mechanism — a `Reader:` line that qualifies its verdict, summarised in the table as though
it did not.
**Reader:** enforced. `tests/test_specs.py` holds twenty-five properties across every document,
discovers documents rather than listing them, and caught four of those seven — REG-3, DEC-7
and DEC-10 were found by hand before it existed — plus one cross-document identifier
collision and the count in this very sentence, which read `fourteen` while the module held
nineteen. A literal beside the thing it counts is REG-12's shape in prose; this one is now
read rather than trusted.

#### Scenario: a requirement with no argument or no reader
- **WHEN** a document states a requirement without a `Why:` or without a `Reader:`
- **THEN** the reader over these documents fails

#### Scenario: a census kinder than its evidence
- **WHEN** a `Reader:` line qualifies its classification and the table repeats the bare
  word
- **THEN** it fails, because that is the defect this suite makes most often

#### Scenario: a document naming a test that no longer exists
- **WHEN** a `Reader:` line cites a test function or a tool path that has been renamed
  or deleted
- **THEN** it fails, rather than continuing to count as coverage

### Requirement: GOV-10 — calibration says which constant it backs, and checks offline in both directions

A calibration report SHALL name the live constants it justifies, and its check MUST
re-read the committed report against those constants, failing if either side moved.

**Why:** a calibration nobody re-reads is a measurement from a date, and the constant it
justified has moved twice since. Checking in both directions is what makes it a gate rather
than a document.
**Reader:** enforced, as of this document. Four reports exist, each with an offline
`--check`, and until now **not one of them ran in CI** — the workflow did not mention
calibration at all. The mechanism had been built and never connected. All four were run
while writing this requirement, all four passed in about a second each, and a CI step now
runs them (Appendix A.1).

#### Scenario: a calibration report and its constant
- **WHEN** a report justifies a live constant
- **THEN** it names that constant, and its check compares the two offline

#### Scenario: either side moves
- **WHEN** the constant changes, or the committed report changes
- **THEN** the check fails — both directions, because a report that quietly follows the
  code justifies nothing

#### Scenario: a check that exists and gates nothing
- **WHEN** a calibration check is written and not wired into the matrix
- **THEN** it passes forever without being run, which is the state all four were in
  until this document looked

### Requirement: GOV-11 — the push gate verifies what the push sends, and a `git` this tree starts reaches the directory it names

The gate a push runs — `.githooks/pre-push`, which starts `tools/ci_local.py` — SHALL
verify the content of the commits being pushed. A push MUST be refused, before any step
runs, when the working tree is not the content of a commit it sends; a push that sends no
commit SHALL NOT be gated. The stamp that lets an unchanged tree through MUST be taken over
every file the commit tracks.

A `git` process this tree starts, in a tool or in a test, SHALL reach the directory its
caller names, whatever a hook left in the environment, and MUST NOT read the standard
input of the process that started it.

**Why:** the gate runs CI's steps over the files on disk, and a push sends commits. Where
the two differ, green says nothing about what left. And git starts a hook with variables
that aim every `git` below it at the repository being pushed, over `-C`: a command meant
for a temp directory is then carried out on the real one.
**Reader:** enforced, as of 0.141.0 — and until then nothing required any of it. The gate
and its hook were named once in these twelve documents, in GOV-7's reader line, and
everything below lived there unread:

- At 0.137.0 the suite, run by the gate from a worktree, built its throwaway repository on
  the real one, which was marked bare and took two commits; and the hash staged into the
  hook's repository. Both were repaired caller by caller — three callers each cleaning
  their own environment, and every other launch left as it was.
- The hook dropped the refs git feeds it, so the gate never knew what was pushed. A push
  that only deleted two branches ran all twenty-seven steps, nineteen minutes (3 October
  2026); a tag pushed with the next release's edits on disk was "verified" on those edits;
  and a push with a modified or an untracked file on disk verified a tree that was not the
  commit that left.
- **The stamp's hash did not contain the runner, the report or the registry.** It was
  staged from an empty index, which obeys the ignore rules even for files the real index
  tracks, and `.gitignore` held `CHECKLIST*` — written for the report's output, and
  matching `checklist_runner.py`, `checklist_report.py` and `checklist.json` wherever the
  filesystem ignores case, which is this machine. An edit to the runner alone after a
  green gate would have been pushed as *"this exact tree already ran green here"*. Found
  by asking why the hash was not the commit's tree on a clean checkout
  (`403cbd6886a5` against `db21326ed09d` at v0.138.0); it is now.

Held by `tests/test_local_gate.py`. `TheGateVerifiesWhatLeaves` builds temp repositories
and hands the gate what git would: a deletion, a clean tree and its own `HEAD`, a modified
tracked file, an untracked one, an ignored one, another ref with other content and with
the same, an annotated tag, several refs of which a later one is not on disk, a run by
hand, and the hook's own launch line executed with a program that records its arguments
and stdin. `EveryGitReachesItsDirectory` derives every place a process is started whose
program is git — tools, tests and the hook — and requires each to be the launcher or a
named exception, failing as well for an exception that no longer starts git; and it starts
each kind of read with a hook's variables naming another repository.
`test_ci_local…test_an_ignored_tracked_file_moves_the_hash` holds the stamp, and
`test_registry.AnAuditDoesNotCommitItself.test_no_tracked_file_is_ignored` the rule that
hid the three files. Probed 3 October 2026, twelve mutations, each caught by the test
written for it (`local/localgate/probe_0141.py`).

**The twelfth is there because the probe of this requirement hung.** A test builds a tree
with `git mktree`, which reads its standard input; the launcher did not say what a child's
standard input was, so the child had its caller's, and where that was a pipe nobody closed
it waited for ever — five minutes, until it was killed. From a terminal the suite would
have done the same. Under the hook it is worse than a wait: the caller's standard input
there is git's list of refs, the thing the gate reads to know what is pushed.
`test_git_neither_waits_on_nor_consumes_the_callers_stdin` keeps a pipe open over the
launcher and requires the command to return and the pipe's bytes to be still unread; the
steps the gate runs are given no standard input either.

Not held. A push through git's own hook is rehearsed by hand against a throwaway bare
repository, not run by a test: in these tests the gate's steps are replaced. The
comparison is made before the steps run, so bytes that change while they run are not
seen. A line of stdin that is not four fields ends the gate with a traceback — the push
is refused, by accident and not by a sentence. And the census reads source: a launch
assembled at run time from a string is not a launch it can see.

#### Scenario: a push that sends no commit
- **WHEN** a push only deletes refs on the remote
- **THEN** the gate says that no commit is being pushed, and runs no step

#### Scenario: an edit that was not committed
- **WHEN** a tracked file on disk differs from the commit being pushed
- **THEN** the push is refused before any step runs, naming the ref
- **AND** the refusal says what to do: commit or stash the edit, or check out what is
  pushed

#### Scenario: a file git has not been told about
- **WHEN** an untracked file that no ignore rule matches lies in the working tree
- **THEN** the push is refused the same way, because a module not yet added can be what
  makes the suite green
- **AND** a file an ignore rule matches does not count

#### Scenario: another ref than the one checked out
- **WHEN** the ref being pushed is not the branch that is checked out
- **THEN** it passes if its commit holds what is on disk — a release is pushed from the
  worktree that verified it, and a tag is read as the commit it names — and is refused if
  it does not
- **AND** with several refs in one push, each is compared before any step runs

#### Scenario: the gate run by hand
- **WHEN** `ci_local.py` is started without the hook
- **THEN** it verifies the working tree as it stands, uncommitted files included, and
  makes no claim about a push

#### Scenario: a tracked file an ignore rule matches
- **WHEN** a file the commit tracks is matched by an ignore rule, and is edited
- **THEN** the stamp's hash moves and the gate runs again
- **AND** no tracked file of this tree is matched by one of its own ignore rules

#### Scenario: a hook's variables name another repository
- **WHEN** `GIT_DIR` and its kin are in the environment and a tool or a test starts `git`
  for a directory
- **THEN** the command reads and writes that directory: every launch goes through one
  launcher, which removes the names git itself lists
- **AND** an environment handed to the launcher on purpose is used as given — the
  throwaway index is one

#### Scenario: a launch that goes round the launcher
- **WHEN** a tool or a test starts `git` by itself
- **THEN** the census fails, and it fails as well for a listed exception that no longer
  starts `git`
- **AND** the hook's own two reads are the exception: they mean the repository being
  pushed

#### Scenario: a `git` that reads its standard input
- **WHEN** a tool or a test starts a `git` command that reads standard input, from a
  process whose own input is still open
- **THEN** the command is given an empty input and returns, and what waits in the caller's
  input is still there to be read
- **AND** the steps the gate runs are given no standard input either

## 4. Invariants

* **INV-G1** — every gate CI runs is runnable locally with the same command.
  *Reader: partial* — the workflow is a list of shell lines, and `local/live_path.sh`
  reproduces the live one by hand; nothing asserts the two agree.
* **INV-G2** — no gate writes into the tracked tree. *Reader: enforced* — a test reads the
  default output paths out of the tools' own argparse definitions and asserts `git
  check-ignore` covers every one, having twice been added to after an output escaped.
* **INV-G3** — the Python floor CI tests is the floor the package declares.
  *Reader:* **none.** The matrix names 3.10, 3.11 and 3.13 and the package requires ≥3.10;
  nothing compares them, and a package that raised its floor would keep being tested on the
  old one.
* **INV-G4** — every ledger entry names a marker that exists in the tree.
  *Reader: enforced* — the ledger's `--check` resolves each entry's probe by name and fails
  on one it cannot find.

## 5. What this document does not decide

* what any threshold should be — GOV-1 requires a basis, not a value;
* whether a known issue should be fixed. The ledger records the decision; the roadmap
  argues it;
* what the fixture oracle and the census measure — `openspec/specs/declarations/`;
* how a release is cut, versioned and tagged. That is the operator's procedure and lives
  with the packaging, not with the gates;
* which capability each document owns — `local/sdd/COVERAGE-MAP.md`, which is a working
  file rather than a normative one.

## 6. Open questions

**Should `inherited` be allowed to increase?** GOV-2 says the category is an admission.
Seventy-seven of 146 is a large admission, and the gate passes at any number. A ratchet —
`inherited` permitted but never permitted to rise — is the shape this tree already uses for
other debts, costs nothing to add, and would make every new undefended constant a
deliberate act. What would settle it: whether the count is stable enough to ratchet against,
which nobody has measured across releases.

**Why is calibration not a gate?** GOV-10 is unread because the four checks exist and CI
does not run them. Each is offline and fast. The likeliest reason is that they were written
alongside the reports and nobody added the step — which is exactly the failure mode a
governance document should catch, and the reason this one found it is that it went looking
for the connection rather than the tool. What would settle it: running them, which costs
seconds.

**Is a suite-wide debt total worth computing?** Every document here ends with a census, and
the eleven censuses are not summed anywhere. The coverage map says the total should be "a
number rather than a feeling". A tool that read every Appendix B and printed the totals
would take an afternoon and would make the debt a tracked quantity. What would settle it:
whether anyone would act on the number, or whether it would become a metric to manage.

## Appendix A — measured disagreements, 4 September 2026

Observation, not specification. Measured at commit `9010dbc`.

#### A.1 — four calibration checks exist and none of them gates anything

`tools/calibration/` holds four committed reports — CSS minification, font weight, Search
Console sample floors, SERP length — and each has an offline `--check` that compares the
report against the live constants. Searching the CI workflow for the word `calibration`
returns **zero** matches.

So the arrangement was: a measurement taken, a report committed, a checker written to keep
them in step, and nothing running it. The constants those reports justify could move, and
the only thing that would have noticed was somebody running the check by hand.

This is a different shape from the rest of the suite's findings, and the difference made it
cheap. Elsewhere the reader is missing; here the reader existed, offline and fast, and was
not wired up. All four were run:

| check | result |
|---|---|
| CSS minification | `constant=0.189; corpus=0.189; agree=yes` |
| font weight | `constant=100000; corpus=100000; agree=yes` |
| Search Console sample floors | `constant=100; report=100; required=73; agree=yes` |
| SERP length | `META_MIN_CHARS 100/100, META_MAX_CHARS 144/144; agree=yes` |

Four passes, four exit zeros, under five seconds together. They now run in CI, in the
`test` job beside the threshold audit. The finding is not that a constant had drifted — none
had — but that nothing would have said so.

#### A.2 — the inventory's own basis counts are wrong

The capability inventory records the distribution as *"inherited 77, convention 47,
standard 14, presentation 14, measured 13"*. The tool reports:

| kind | inventory | measured |
|---|---:|---:|
| inherited | 77 | 77 |
| convention | 47 | 47 |
| standard | **14** | **11** |
| measured | **13** | **11** |
| presentation | **14** | **13** |

Three of five wrong. The two large ones are right, which is how the error survived: the
numbers that get quoted are the ones that were checked.

This is the sixth count in this tree found stating something the tree does not — after the
registry's own `source` string, two counts in the corpus README, two in the census
docstring, the shapes reference's account of itself, and the guard's marker count. All six
have the same form: a number written beside the thing it counts, reproduced faithfully, read
by nobody. GOV-3 is the general rule; this is the sixth instance of its absence.

#### A.3 — 150 of 166 behaviour-deciding sets are named by nothing

Measured 6 September 2026 by `tools/audit_derived_sets.py`, recorded in
`tests/derived-sets.json`. The population is module-level upper-case names in `scripts/`
and `tools/` bound to a collection **literal**; a set built by a comprehension or a call
is derived and out of scope. "Read" is the strictest available measure — a test imports
the name from its module — and is still an upper bound, since importing a name is not
asserting what belongs in it.

| module | unread |
|---|---:|
| `checklist_runner` | 24 |
| `build_checklist` | 21 |
| `checklist_report` | 9 |
| `server_log_audit` | 6 |
| `calibrate_serp_length` | 5 |
| `detect_profile` | 5 |
| `pagespeed` | 5 |

The first two are the ones that matter: the runner's sets decide which modes exist, what
each capability permits, and which statuses are terminal, and the builder's decide the
registry's shape. Both are the kind of set whose forgotten entry is invisible from the
consuming code, which is the whole sentence of GOV-3.

The census moved by two the moment its own reader was written — `LITERALS` and one
neighbour left the unread column because a test imported them. That is worth recording
rather than tidying away: the measure is of *this* tree including its tests, and a
reader that changes what it measures is a reader that is really reading.

#### A.4 — the ledger is the best-guarded instrument in the repository

Recorded because the suite's findings are otherwise uniformly negative, and this one is not.

`tests/test_known_issues.py` asserts that the comparison complains when a recorded value
moves **and** that it is quiet on the record as recorded. That pair is rare: the first alone
passes on a check that always fires, the second alone passes on a check gutted to return
nothing, and one of this repository's own test docstrings says exactly that — a
`differences()` returning `[]` would leave every other test green and the gate permanently
silent, "which is worse than not having the gate: it reads as a checked claim."

It also asserts something no other instrument here does: that the file is still asking more
questions than it is guarding, counted over entries rather than probes, because counting it
over probes made repair the thing that failed.

That is the standard the rest of this layer is measured against, and it is the reason GOV-4
is the only `enforced` requirement in this document that covers a whole capability rather
than one mechanism inside one.

## Appendix B — how much of this document is enforced

**Probed:** GOV-1 and GOV-10 by running the tools — the threshold gate reports its five
counts and zero without a basis; the calibration search over the workflow returns nothing.
GOV-8 and INV-G2 by reading the workflow and the test that reads argparse defaults. The
rest were derived by reading the gates and their tests.

| | requirements |
|---|---|
| **enforced** | GOV-1, GOV-4, GOV-8, GOV-9, GOV-10, GOV-11 |
| **partial** | GOV-2, GOV-3, GOV-5, GOV-6, GOV-7 |
| **none** | — none |
| **opposed** | — none |

Invariants: INV-G2 and INV-G4 enforced; INV-G1 partial; INV-G3 unread.

**Six enforced, five partial, none unread, of eleven.**

The two unread requirements are the two that ask the machinery to be *governed* rather than
to govern. GOV-2 asks that an admission not become a justification; GOV-3 asks that lists be
derived. Each is a rule about the rules, and each is exactly the kind of thing with no
natural place to fail.

GOV-10 was the third until writing it closed it. That is worth recording as method rather
than as luck: the requirement was drafted `none`, the check it named took a second to run,
and running it turned a documented gap into a CI step in the same sitting. Most of what
these documents find cannot be closed that cheaply; this one could, and the only reason it
had not been was that nobody asked whether the tool was connected to anything.

That is the honest summary of this layer, and of the suite. What this repository does well
is build an instrument after a defect and wire it in: the ledger, the threshold gate, the
request ceiling, the registry audits, the byte-comparison on the generated registry. What it
does not do is come back and ask whether the instrument is still pointed at anything —
which is how four calibration checks came to exist and never run, and how six counts came to
describe a tree that had moved. The other eleven documents are, collectively, the first
time anybody asked.
