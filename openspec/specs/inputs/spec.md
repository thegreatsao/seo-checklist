# Inputs — what an operator may hand the audit, and what the audit owes them back

## Purpose

Everything the run is given rather than measures — artifacts produced by other tools,
credentials and keys, the Search Console property, and the bundled public suffix list the
property is derived from — C27–C30 of the capability inventory. None of it can be re-taken
by this run, so this capability decides what the audit may believe about somebody else's
claim, and what it must not write back out again. The two halves are mirror images: on the
way in, whether a file is about this page and how old it is; on the way out, that no key
material reaches an artifact an operator mails to a client.

**Capability:** everything the run is given rather than measures — artifacts produced by
other tools, credentials and keys, the Search Console property, and the bundled public
suffix list the property is derived from (C27–C30 of the capability inventory).

This document is normative and is written as though no code existed. Where the
implementation disagrees, the implementation is presumed wrong until this document is
changed by argument. Appendix A records disagreements measured on 4 September 2026.

Every requirement carries a **Reader** line naming what makes it fail when violated;
Appendix B is the census of those lines. A requirement whose reader is `none` is an
intention, and is counted as one.

**Inherited, not restated:** the statuses belong to
[`openspec/specs/verdicts/`](../verdicts/spec.md); how a missing input becomes a plan decision
belongs to [`openspec/specs/run-lifecycle/`](../run-lifecycle/spec.md) RUN-5; what a checker does
with an input it was given belongs to [`openspec/specs/evidence/`](../evidence/spec.md).

---

## 1. An input is a claim by somebody else

Everything in this document arrived from outside the run, and that is the whole of its
difficulty. A crawl the audit performs is evidence; a JSON file an operator exports from
another tool is a *claim* — that these numbers describe this page, that they were measured
recently, that this render is of the same site. The audit cannot check most of it and must
not pretend otherwise.

So the rules here are about provenance rather than correctness. Not "is this Core Web
Vitals export right", which nothing here can know, but: is it about the page we are
auditing, how old is it, was it a lab measurement being read as field data, and does the
report say which. An artifact that silently answers for the wrong page produces a verdict
that is internally consistent, well-evidenced and about somebody else's site.

The second half of the document is the mirror image. Credentials and keys arrive from
outside too, and the obligation runs the other way: the audit must not write them out
again. A run log is built from each script's argv, so a key passed as an argument lands in
it verbatim, and the artifact is a file operators mail to clients.

## 2. What an input is

| input | flag | what it claims |
|---|---|---|
| Core Web Vitals export | `--cwv-json` | field measurements for a page |
| rendered DOM | `--rendered-json` | what a browser produced for a page |
| linking-domains export | `--links-csv` | who links to the site |
| server log | `--server-log` | who requested what, and when |
| primary keyword | `--keyword` | what the site is about |

Credentials are separate: a Search Console service-account key, an IndexNow key, a
PageSpeed key, a Safe Browsing key. Two of those are *paths* to key material and two are
key material.

## Requirements

### Requirement: INP-1 — an artifact about another page is refused, never averaged in

An artifact names, or implies, the page it describes. Where that page is not the page being
audited, the artifact MUST be refused and the items that would have read it SHALL report
`NEEDS_INPUT`, naming both URLs. Noise in a URL — scheme, `www.`, a trailing slash — is not
a different page; a different path is.

**Why:** this is the one artifact defect the audit *can* catch, and the consequence of not
catching it is a verdict that is fully evidenced and entirely wrong. Averaging a foreign
measurement in would be worse than ignoring the file, because the result would look
measured.
**Reader:** enforced. `test_a_different_page_is_a_different_page` and
`test_the_noise_a_url_carries_is_not_a_different_page` pin both directions of the
comparison; `test_an_artifact_from_the_other_site_is_refused_with_the_reason` pins the
refusal end to end, asserting the status and that the evidence names the other origin; and
`test_a_url_is_found_whether_or_not_the_exporter_nested_it` pins the subject extraction
against two export shapes.

#### Scenario: a trace of somebody else's page
- **WHEN** a supplied artifact names a subject URL on another origin than the audited page
- **THEN** every item that would have read it reports `NEEDS_INPUT`
- **AND** the reason names the other origin, and never says the input is missing — which
  would send the operator off to produce a file they have already produced

#### Scenario: a URL's noise is not a second page
- **WHEN** the artifact's subject differs from the audited URL only by scheme, a `www.`
  prefix or a trailing slash
- **THEN** the artifact is used, because nobody measures `https://example.com` and means
  something other than `https://example.com/`

#### Scenario: a different path is a different page
- **WHEN** the subject differs in host, in path, or in query — `/about` against `/`,
  `?v=2` against nothing, `staging.` against the bare host
- **THEN** the artifact is refused

#### Scenario: the subject is found whichever shape the exporter used
- **WHEN** an export carries its URL nested inside the payload rather than at the top level
- **THEN** the subject is read from there and compared
- **AND** it is not mistaken for a file that stated no subject at all, which would be
  admitted under INP-2 instead of refused here

### Requirement: INP-2 — an artifact with no stated subject is used and recorded

A file that does not say which page it describes MUST NOT be refused. It SHALL be used, and
the fact that it made no claim SHALL be recorded.

**Why:** most exporters do not write the URL, and refusing every such file would make the
feature unusable. The honest position is to accept the operator's implicit claim and to
record that it *was* implicit, so a surprising verdict can be traced back to a file nobody
checked.
**Reader:** partial. `test_an_unreadable_artifact_does_not_raise_here` pins that a file the
subject-reader cannot parse does not end the run. That the absence is *recorded* — and
therefore visible to whoever reads the artifact later — has no test.

#### Scenario: an export that names no page
- **WHEN** a supplied artifact carries no URL of its own
- **THEN** it is used rather than refused, and the items that read it are decided from it
- **AND** the run records that the file made no claim, rather than recording a claim that
  was checked and matched

#### Scenario: a file the subject-reader cannot parse
- **WHEN** the file is not JSON, or is a list rather than an object, or is not there at all
- **THEN** the subject check reports no subject and the run continues
- **AND** the script that consumes the file reports its own error, naming the offending
  field, rather than being pre-empted by a generic refusal here

#### Scenario: a surprising verdict is traceable to the file nobody checked
- **WHEN** an item was decided from an artifact whose subject was never checked
- **THEN** a reader of the record afterwards can see that it was never checked, rather than
  seeing a verdict indistinguishable from one measured on the audited page

### Requirement: INP-3 — an artifact is as old as it is, and the run says so

The age of every supplied artifact SHALL be computed and recorded. A run may be given a
maximum age, and an artifact older than it MUST be refused with its age named.

**Why:** a Core Web Vitals export from March describes a site that has been deployed a
hundred times since. Nothing about the file says it is stale, and the verdict it produces
is indistinguishable from a fresh one.
**Reader:** enforced. `AnArtifactIsAsOldAsItIs` holds the computation in four ways: the age
is read from the filesystem and counted in whole days, a file written yesterday is a day
old rather than zero, an unreadable file has *no* age rather than a fresh one — `None` and
`0` mean opposite things and only one of them flatters — and an age is never negative, so a
clock that moved cannot make a file fresh forever. Probed on 6 September 2026 by returning
a constant zero, by turning the unreadable case into zero, and by dropping the clamp. Each
reddens; the constant-zero mutation is the one this line used to say would pass the suite.

Both halves that were unread are closed in 0.94.5, and they were different in kind.

The first was a defect in the tree rather than a gap in the tests — A.5. The loop recorded
two of the four inputs an operator may supply, so a link export or a server log had no age
at all and no limit could reject one however old it was. It was pinned as an *absence*,
written to redden the day the sets were reconciled and to say what to put in its place; it
did, and what replaced it is not a wider list but the property that makes the list
irrelevant: every input an operator may supply is a file on disk, so every one can be dated,
and the loop that records them walks that same set. Both halves are asserted, because a loop
widened over a set that has itself narrowed looks identical from inside either one.

The widening had a distinction to preserve. A link export and a server log describe the
site, so `matches_audited_url` is not *unknown* for them — it is inapplicable, and recording
`None` would file them beside a page export whose file forgot to say which page it was. They
carry a path and an age and claim nothing else.

The second half was the refusal itself, computed inside `main` with no seam a unit test can
reach. `AStaleArtifactIsRefusedByAWholeRun` runs the audit twice against one fixture site
with one file backdated 200 days by `os.utime` — once with `--max-artifact-age 30` and once
without — and reads the difference: the age is recorded either way, the unlimited run still
decides items from it, the limited run decides fewer, the refusal names the input and the
age, and the items that read it say why rather than going quiet. The unlimited run is the
floor under the rest: without it an implementation that refused every artifact would look
like a working limit. Probed by disabling the comparison, which reddens two.

The old text of this line said such a test was worth writing and not written. It is the
paragraph above.

The default still makes all of this matter: `--max-artifact-age` is `0`, meaning no limit,
so the shipped behaviour is that an artifact of any age is accepted. §6 asks whether that
should change.

#### Scenario: every supplied artifact carries its age
- **WHEN** a run is given an artifact of any kind and no maximum age
- **THEN** the record states how old that file is
- **AND** an age of zero means the file was written today, never that nothing looked

#### Scenario: a file exported in March, read in September
- **WHEN** the run was given a maximum age and the artifact is older than it
- **THEN** the artifact is refused and the items that would have read it report
  `NEEDS_INPUT`
- **AND** the reason names the artifact's age and the limit, so the operator can see which
  of the two to change

#### Scenario: a refused artifact decided nothing
- **WHEN** an artifact was refused for its age
- **THEN** no surface describes it as having supplied a measurement to this run

#### Scenario: an age nothing can determine
- **WHEN** the artifact's age cannot be read
- **THEN** the run records the age as unknown rather than as zero — "we cannot tell how old
  this is" must not read as "written today"

### Requirement: INP-4 — an artifact answers for the page it describes and no other

Artifacts SHALL be applied to the page they claim and MUST NOT be spread across a sample.
An item decided from an artifact keeps the primary page's verdict rather than being
aggregated over sampled pages.

**Why:** one measurement of one page is not a claim about four others. Aggregating it would
manufacture a site-wide verdict out of a single file.
**Reader:** enforced, and by the strongest kind of reader available here — an end-to-end
sampled run asserts that the artifact-backed items carry no per-page count while other
items do, and a second test pins which items read an artifact by comparing the registry
against the runner's own source line.

#### Scenario: one measured page does not become a verdict about four others
- **WHEN** a sampled run is given an artifact measured at one URL
- **THEN** the items decided from it carry no per-page count, while the other page-level
  items do
- **AND** the aggregate never reports "4 of 4 pages" about pages nothing opened, which is
  what re-reading the same file once per sampled URL produces

#### Scenario: a new artifact reader is covered the day it is added
- **WHEN** an item's argv names an artifact placeholder
- **THEN** it is kept out of the per-page sample whatever it requires — being page-level
  and offline is a coincidence of the current registry, not the property that protects it

#### Scenario: a site-level item that reads an artifact
- **WHEN** the item is not page-level
- **THEN** it runs once, against the audited URL
- **AND** whether the artifact is about that URL is still INP-1's question, not a reason to
  spread the file across anything

### Requirement: INP-5 — a lab measurement is never reported as field data

Where a number was produced by a synthetic run rather than observed from real users, the
report SHALL say so, and an item whose title asks about field data MUST NOT be decided from
a lab number.

**Why:** the two answer different questions and a client acts differently on each. The
distinction is invisible in the number itself.
**Reader:** partial, and the two clauses are read very differently.

The second clause — an item whose title asks about field data is never decided from a lab
number — is enforced. `test_no_field_titled_item_is_ever_decided_from_a_lab_number` derives
the items that assert on `field_cwv` from the registry rather than listing them, so a fifth
is swept the day it is added, and requires every one to be `NO_DATA` on a lab-only payload;
`test_the_same_items_do_decide_when_there_is_field_data` is the floor under it, without
which the sweep would pass on an implementation that answered `NO_DATA` to everything. Two
of the four were already pinned individually — this is the invariant those two are halves
of, which is the shape this suite has been wrong about before.

It holds structurally rather than by care: `field_cwv` is written only inside
`if result["field_data_available"]`, so a lab run cannot reach an item that asserts on it.
Probed on 6 September 2026 by removing that guard, and the failure is the requirement's own
harm in one line — the lab-only payload comes back carrying `field_cwv: verdict pass`, so
all four would report a Core Web Vitals pass earned on a synthetic run.

The first clause — that the report says a number came from a synthetic run — is unread, and
one case of it is a live gap rather than a missing test. `metrics.*.rating` carries CrUX
where field data exists and Lighthouse's lab audits where it does not, and SP-107 and SE-119
decide from it. Their titles do not name field data, so the second clause is satisfied; but
nothing in the report says those two verdicts came from a synthetic run, which is what the
first clause asks for. `openspec/specs/registry/` records the neighbouring confusion:
SP-112's title names Core Web Vitals *in Search Console* and its rule reads the PageSpeed
API — the identical rule to SP-108.

#### Scenario: no real-user sample exists for this page
- **WHEN** the field source has no sample for the audited URL and only a synthetic
  measurement is available
- **THEN** the items whose titles ask about field data report no verdict
- **AND** a fast synthetic result is not reported as real users passing, nor a slow one as
  real users failing

#### Scenario: a synthetic number is printed anyway
- **WHEN** a synthetic figure is shown at all, because it is the only speed signal a
  low-traffic page has
- **THEN** the surface names it as a lab measurement and keeps it outside the score

#### Scenario: an artifact that does not say how it was produced
- **WHEN** an operator's supplied measurement carries no statement of its provenance
- **THEN** the run records the provenance as unstated rather than assuming either one

#### Scenario: a field title over a lab rule
- **WHEN** an item's title asks about field data and the rule it carries reads a synthetic
  number
- **THEN** this requirement is violated, whatever verdict the item happens to report

### Requirement: INP-6 — credential discovery is an ordered contract

Credentials SHALL be looked for in a stated order, first hit wins, and the order is part of
the contract rather than an implementation detail. The shell environment MUST always
outrank a file on disk.

**Why:** an operator auditing a client's site from that client's directory must not have
their own credentials silently replaced by a `.env` the client shipped. "First hit wins" is
only safe if the first place looked is the one the operator controls most directly.
**Reader:** enforced. `test_a_shipped_env_file_cannot_replace_the_operators_own_key`
constructs the exact harm the paragraph above names — a client's `.env` in the directory
the operator is audited from, against the operator's own exported key — and
`test_a_file_supplies_only_what_the_shell_left_unset` holds the other side, since
outranking is not ignoring. `test_the_working_directory_is_searched_before_the_shared
_defaults` pins the file order and `test_the_key_search_prefers_the_flag_then_the
_environment_then_disk` pins the finder's, with
`test_a_named_key_that_does_not_exist_is_skipped_rather_than_returned` covering the case
where a named path is a lie.

Probed twice, on 5 September 2026, with both reorderings this line said would pass the
suite: letting a `.env` overwrite an exported key, and putting the environment ahead of the
flag. Each reddens.

#### Scenario: a client's `.env` in the directory the audit is run from
- **WHEN** the operator has exported a key and the working directory holds a `.env` naming
  the same key
- **THEN** the exported value is the one the run uses
- **AND** the run does not quietly authenticate as the client it is reporting on

#### Scenario: outranking is not ignoring
- **WHEN** a `.env` names a key the shell left unset
- **THEN** the file supplies it, because the order exists to resolve collisions and not to
  make files useless

#### Scenario: the directory the operator chose is searched first
- **WHEN** more than one `.env` could apply
- **THEN** the working directory is read before the shared defaults, and the shared
  defaults still exist — an order over one location is not an order

#### Scenario: a credential named three ways at once
- **WHEN** a key path is given on the flag, in the environment, and on disk
- **THEN** the flag wins, then the environment, then the known defaults
- **AND** a named path that does not exist is skipped rather than returned, so a missing
  credential becomes a status the operator can act on instead of a crash inside a checker

### Requirement: INP-7 — key material never reaches a written artifact; paths may

Every secret value MUST be removed from everything the run writes, including the evidence
file and the run log. A *path* to a credential is not a secret and SHALL stay readable,
because a reader needs to know which credential was used.

**Why:** the run log is built from each script's argv, so a key passed as an argument lands
in it verbatim, and the artifact is a file operators send to clients. Redaction over the
whole payload rather than the log alone is deliberate: a script that echoes its arguments
into an error message leaks the same key by a route nobody enumerated.
**Reader:** enforced, and the split inside it is the point.
`test_secret_values_are_replaced_everywhere` pins
substitution throughout a nested structure, `test_nothing_is_touched_without_secrets` pins
the identity case, `test_an_evidence_file_is_redacted_and_written` pins the written file,
`test_redaction_reaches_sampled_page_evidence` pins the sampled path, and
`test_a_safe_browsing_env_key_never_reaches_written_artifacts` pins the one secret that
arrives from the environment rather than from a flag. The *membership* of the secret set was
unread until 0.94.4 — the two constants naming which keys are secret were named by no test,
so a key added to the run and forgotten there would be written out in full, into the file
operators send to clients.

`tests/test_runner.py::TheSecretSetIsDerivedFromWhatTheRunActuallyCarries` derives it from
the operation: every context value the runner fills from an environment variable whose name
looks like key material must be declared secret, with the pairs read out of the runner's own
syntax so a sixth is covered the day it is written. The reverse direction is read too — a
declared name that is no longer a context key redacts nothing and reads as coverage that is
not there — and a guard assertion refuses the vacuous case where the loop is rewritten and
the derivation returns an empty set. `SAFE_BROWSING_ENV_KEYS` cannot be derived the same way
because the scripts read it themselves, so what is checked there is that the names are live.

Probed 6 September 2026 by adding a `moz_key` / `MOZ_API_KEY` pair and not declaring it,
which names the key and says where it would have been written.

#### Scenario: a key passed as an argument
- **WHEN** a secret was given on the command line, so a script's argv carries it into the
  run log
- **THEN** the value appears nowhere in the written results or the evidence file

#### Scenario: a key that never touched a flag
- **WHEN** a secret arrives only through the environment and a script echoes it into an
  error message
- **THEN** it is removed from the written artifacts too, because redaction covers the whole
  payload rather than the run log alone — the routes out cannot be enumerated in advance

#### Scenario: the path stays readable
- **WHEN** the run authenticated with a credential named by a path
- **THEN** that path survives into the record, because a reader who cannot see which
  credential answered cannot judge the answer

#### Scenario: a secret nobody added to the list
- **WHEN** a new key-valued input reaches the run and is not added to the set of values
  treated as secret
- **THEN** this requirement is violated and the key is written out in full, even though
  every test of the redaction mechanism still passes

### Requirement: INP-8 — the Search Console property is derived, overridable, and not a URL

The default property SHALL be the domain property for the site's registrable domain. An
operator may override it. A URL-prefix spelling is not the property, and requesting one
MUST be explained as the wrong form of property rather than reported as a permission
problem.

**Why:** this costs a round every time somebody meets it: the API answers a domain property
and refuses the URL, and the refusal reads as missing access. Deriving the right form by
default is what stops the operator debugging their credentials.
**Reader:** partial. The derivation is pinned by the public-suffix tests and by the
redirect test that asserts the property follows a cross-host destination; the override
reaches the plan. The fallback list has no test, and nothing asserts the four distinct
reasons a Search Console item may have no verdict, which is the table the report is
supposed to explain.

#### Scenario: the property is the domain, not the host
- **WHEN** the audited host carries `www.` or another subdomain
- **THEN** the derived property is the registrable domain rather than the host as written

#### Scenario: a site on a platform domain
- **WHEN** the host sits under a suffix the hosting platform owns rather than the site's
  owner
- **THEN** the whole host is the registrable domain
- **AND** reducing it to the platform's own domain builds a property nobody owns, which
  answers nothing and reads as a site with no search traffic

#### Scenario: a URL where a property was expected
- **WHEN** the operator supplies a URL-prefix spelling as the property
- **THEN** the run explains that the property must be the domain form
- **AND** it does not present the refusal as missing access, which is the round this
  requirement exists to stop

#### Scenario: there is no property to ask about
- **WHEN** the host is an address, or is reachable only from the machine running the audit
- **THEN** the run says which of those it is
- **AND** the Search Console items report that reason rather than a missing credential —
  four distinct reasons, four distinct sentences

### Requirement: INP-9 — Search Console opportunities are reported and never scored

Queries and pages Search Console suggests SHALL be carried into the report and printed
outside the score; they MUST NOT be scored.

**Why:** they are not verdicts about the site. Scoring them would make the number move with
somebody else's index rather than with the site, and a client's score would change while
they changed nothing.
**Reader:** enforced, in both halves.
`test_the_score_counts_items_and_knows_nothing_of_opportunities` asserts the registry
partition still sums to the item count with opportunities present — an opportunity that
leaked into a row would break that sum — and this had to be written over the partition
rather than by comparing two scoring calls, because `score` takes items and handing it the
same items twice proves nothing. `test_the_opportunities_are_printed_where_the_score_is_not`
holds the "reported" half through `opportunity_section`, one of the six report sections
[`openspec/specs/reporting/`](../reporting/spec.md) A.1 records at zero test functions, and asserts
that an absent list prints nothing rather than an empty heading.
`test_the_opportunities_are_lifted_out_of_the_payload` and
`test_a_run_without_search_console_carries_an_empty_list_not_a_missing_key` cover the
carrying.

#### Scenario: a good result is not presented as a failure
- **WHEN** Search Console reports a query the site already ranks well for
- **THEN** it appears in the report as work worth doing
- **AND** it appears in no item row, no partition line and no fix list, because a query
  ranked fourth graded as a `high` failure tells someone to repair their best page

#### Scenario: the score cannot move with somebody else's index
- **WHEN** a run carries opportunities
- **THEN** the item partition still sums to the number of items, and no scored row came
  from an opportunity
- **AND** a client's number does not change while they changed nothing

#### Scenario: a run with no Search Console at all
- **WHEN** nothing was collected from Search Console
- **THEN** the run carries an empty list rather than a missing key
- **AND** the report prints nothing rather than an empty heading

### Requirement: INP-10 — the public suffix list is bundled, dated, and announces its own decay

The list the property is derived from SHALL ship with the tool, so a run is reproducible
offline. Its snapshot date MUST be readable. Past a stated age the run SHALL say the list
is old, and it MUST say so only when the list actually decided something.

**Why:** fetching the list at run time makes an audit depend on somebody else's uptime and
makes two runs of the same site differ for reasons that are not about the site. A bundled
list is the right trade and it goes stale, so the staleness has to be visible — but a
warning printed on runs where no property was derived is noise, and noise is how a warning
stops being read.
**Reader:** partial. Four test functions pin the staleness computation: that the bundled
snapshot declares its date, that the date is read from the header, and that a snapshot
without one reports an unknown age. The age threshold itself is named by no test, and the
"only when it decided something" clause — the half that keeps the warning meaningful — has
no reader.

#### Scenario: the list is read from disk, never fetched
- **WHEN** a property is derived on a machine with no route to the outside
- **THEN** the bundled snapshot decides it
- **AND** two runs of the same site do not differ because somebody else's service was down

#### Scenario: a snapshot that does not say when it was taken
- **WHEN** the bundled list carries no date, or one that cannot be parsed
- **THEN** the age is reported as unknown, never as zero — "we cannot tell" must not read
  as "fresh", which is the reading that keeps a forgotten snapshot silent

#### Scenario: a snapshot past the stated age
- **WHEN** the list is older than the age this document requires to be visible, and the
  list is what decided the property
- **THEN** the run says the snapshot is old and how old, wherever the reader of that run
  can see it

#### Scenario: a warning about a list that decided nothing
- **WHEN** the operator supplied the property, so the bundled list was not consulted for it
- **THEN** no staleness warning is printed — a warning on runs it did not affect is how a
  warning stops being read

## 4. Invariants

* **INV-I1** — no written artifact contains a secret the run was given.
  *Reader: partial* — the mechanism is enforced from five directions, the membership of the
  secret set from none.
* **INV-I2** — every supplied artifact appears in the run's record of artifacts, whether it
  was used or refused. *Reader: partial* — a refused artifact is asserted to appear with its
  reason; an accepted one is asserted through the items it decided rather than through the
  record.
* **INV-I3** — an item is never decided from an artifact describing a different page.
  *Reader: enforced* — INP-1's end-to-end refusal test.
* **INV-I4** — the property a Search Console item addresses is the one the report names.
  *Reader:* **none.** Nothing compares the property used against the property printed.

## 5. What this document does not decide

* what a checker does with an artifact once it is accepted — `openspec/specs/evidence/`;
* how a missing or refused input becomes a plan decision and a status —
  `openspec/specs/run-lifecycle/` RUN-5;
* what the report shows about provenance and where — `openspec/specs/reporting/`;
* whether an item's title matches the data it reads — `openspec/specs/registry/` REG-6, which owns
  the SP-112 finding INP-5 points at;
* how often the bundled list should be refreshed. This document requires the age to be
  visible; the number is calibration.

## 6. Open questions

**Should a stale artifact be refused or reported?** INP-3 gives the operator a limit and
defaults it off, which means the shipped behaviour is "accept anything". The alternative —
a default limit — refuses files that were fine, on a run the operator may not be able to
repeat. A third option is neither: accept any age and put it in the provenance line beside
the verdict, so the reader decides. What would settle it: whether an artifact's age already
reaches the report, which INV-I2 says is only half-recorded.

**Is "shell environment wins" a security rule or a convenience?** INP-6 treats it as the
former, and the reasoning — auditing a client's site from the client's directory — is
concrete. If it is a security rule, a repository `.env` supplying a *credential path* is
also a risk, and the discovery order does not distinguish path-valued from key-valued
settings. What would settle it: deciding whether the audit should refuse to read
credentials from any file it did not own before the run started.

**What does the audit owe a lab number?** INP-5 forbids reporting one as field data and
nothing implements the distinction, because the artifacts do not carry it. Adding it means
either trusting an exporter's own label or inferring it from which tool produced the file.
What would settle it: whether any current item's title actually asks for field data —
`openspec/specs/registry/` says one does, and its rule reads the lab path.

## Appendix A — measured disagreements, 4 September 2026

Observation, not specification. Measured at commit `5c768de`.

#### A.1 — the freshness limit is off by default and read by nothing

`--max-artifact-age` defaults to `0`, which the code treats as no limit. So an artifact
exported in March is accepted in September without comment, and every item it decides is
reported as a measurement of the site as it is now.

Neither half has a reader. Searching all 1 280 test functions for the age computation and
for the limit returns nothing: an implementation that computed every artifact's age as zero,
or a comparison that never fired, would pass the whole suite.

This is the gap the capability inventory recorded as G10, and measuring it adds one thing
to the record: the *check* is unread, not merely the default. Turning the default on would
not make the behaviour tested.

#### A.2 — the credential discovery order is prose in two files and an assertion in none

The environment loader documents four sources in a fixed order and states that the real
shell environment always wins. The credential finder documents its own four-step order.
Neither function is named by any test function.

The consequence is specific rather than theoretical. The order exists to stop a `.env` in
a client's working directory overriding the operator's own exported credentials — an
operator audits from wherever the client's files are. A reordering that put the file above
the environment would change which credential a run authenticates with, produce a complete
and plausible report about the client's own Search Console property, and redden nothing.

#### A.3 — the secret mechanism is well read and its membership is not

Redaction is covered from five directions, including the one secret that arrives through
the environment rather than a flag, and it is applied to the whole payload rather than to
the run log alone — with a comment explaining why, which is the shape of a rule somebody
had already been bitten by.

What no test names is the *set*: the constant listing which context keys hold key material,
and the constant listing the environment variables the Safe Browsing key may arrive under.
A key added to the run and not added to those tuples is written into the evidence file in
full, and the suite stays green. The mechanism is guarded; the list of what to apply it to
is not.

#### A.4 — four Search Console behaviours are stated and unread

The fallback property list, the four-reason table for a `gsc` item having no verdict, that
opportunities are printed, and that opportunities stay out of the score — none is named by
any test function. The last is the one worth separating: it is the rule that keeps a
client's score from moving when Google's index moves, and it is the kind of rule that is
obeyed until somebody sums a list that happens to include it.

#### A.5 — the run records the age of two supplied artifacts of four

Found on 5 September 2026 while writing INP-3's scenarios, and verified by reading
`skills/seo-checklist/scripts/checklist_runner.py`.

`ARTIFACT_CTX_KEYS` is `PAGE_ARTIFACT_KEYS + ("links_csv", "server_log")` — four file
inputs, all four listed in §2 as inputs an operator supplies. The loop that records an
artifact's subject, its age and whether it describes the audited URL iterates
`PAGE_ARTIFACT_KEYS` alone:

    for key in PAGE_ARTIFACT_KEYS:
        ...
        artifacts[key] = {"path": ..., "describes": ..., "age_days": age}

So a supplied link export or server log has no recorded age, no recorded subject, and no
entry in the run's record of artifacts at all — and `--max-artifact-age` cannot reject
one however old it is. That is INP-3 violated for half the inputs it governs rather than
merely unread, and INV-I2 violated the same way.

The two that are recorded are the two a *page* measurement comes from, which is why the
constant is named as it is. The requirement is about supplied inputs, not about page
inputs, and the two sets were allowed to drift apart because nothing reads either.

#### A.6 — an artifact refused for age is still reported as having supplied measurements

`provenance_warnings` builds the set it describes to the reader as every artifact whose
`matches_audited_url` is not `False`. An artifact rejected for being too old has
`matches_audited_url: True` — its URL did match; its age is what disqualified it — so it
stays in that set. The report then tells the reader that some verdicts come from
measurements supplied with the run, and states the age of the oldest, about a file that
decided nothing.

Latent today only because the freshness limit is off by default (A.1). The release that
turns the limit on turns this on with it, and the two must be fixed together.

## Appendix B — how much of this document is enforced

**Probed:** INP-3 and INP-7 by mutation on 6 September 2026 — adding an undeclared credential to the
context reddens the membership reader by name. The rest were not: the executor that had been
running mutation probes ran out of credits partway through this suite of documents. The rows below were
derived by parsing all 1 280 test functions and asking, per symbol, which bodies name it,
then reading those bodies. That is the method Appendix A.1 to A.4 rest on, and its limit is
the one `openspec/specs/evidence/` A.4 states: a test can exercise something without naming it, so
`none` here means "named by nothing", which is a lower bound on coverage.

| | requirements |
|---|---|
| **enforced** | INP-1, INP-3, INP-4, INP-6, INP-7, INP-9 |
| **partial** | INP-2, INP-5, INP-8, INP-10 |
| **none** | — none |
| **opposed** | — none |

Invariants: INV-I3 enforced; INV-I1 and INV-I2 partial; INV-I4 unread.

**Six enforced, four partial, nothing unread, of ten.**

The split fell along one line, and it was not the line effort would predict. Both enforced
requirements were about a *file* — is it about this page, is it applied to the right page.
Every unread one was about a *policy*: how old is too old, which credential wins, what may
be scored, what counts as field data.

Two of those four policies were decided and read on 5 September 2026, and the observation
below is what made them cheap rather than what made them hard. A policy has no artifact to
construct, so the test has to assert an ordering or an absence — and once that is said out
loud, the tests write themselves: for INP-6 an ordering, asserted by constructing the
collision the requirement was written about, and for INP-9 an absence, asserted over the
partition sum rather than over the number. What was missing was never the technique. It was
somebody deciding that the current answer is the intended one, which is what a normative
document is.

INP-7 straddles the line and is the clearest case of it. Removing secrets from a payload is
file-shaped, and it is enforced from five directions. Deciding *which* keys are secret is
policy-shaped — a list somebody maintains — and it is read by nothing. One requirement, one
mechanism, and the half that has to be remembered is the unguarded one.

That is a coherent difference rather than an accident. A rule about a file can be tested by
constructing the file, and every one of these was — a foreign artifact, a nested export, a
sampled run, a payload full of keys. A rule about policy has no artifact to construct: the
test would have to assert an ordering, a default, or an absence, and each of those needs
somebody to decide that the current answer is the intended one. Four of these ten policies
have never been decided; they have only been implemented.
