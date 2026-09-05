# Inputs — what an operator may hand the audit, and what the audit owes them back

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
[`specs/verdicts/`](../verdicts/spec.md); how a missing input becomes a plan decision
belongs to [`specs/run-lifecycle/`](../run-lifecycle/spec.md) RUN-5; what a checker does
with an input it was given belongs to [`specs/evidence/`](../evidence/spec.md).

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

## 3. Requirements

### INP-1 — an artifact about another page is refused, never averaged in

An artifact names, or implies, the page it describes. Where that page is not the page being
audited, the artifact is refused and the items that would have read it report
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

### INP-2 — an artifact with no stated subject is used and recorded

A file that does not say which page it describes is not refused. It is used, and the fact
that it made no claim is recorded.

**Why:** most exporters do not write the URL, and refusing every such file would make the
feature unusable. The honest position is to accept the operator's implicit claim and to
record that it *was* implicit, so a surprising verdict can be traced back to a file nobody
checked.
**Reader:** partial. `test_an_unreadable_artifact_does_not_raise_here` pins that a file the
subject-reader cannot parse does not end the run. That the absence is *recorded* — and
therefore visible to whoever reads the artifact later — has no test.

### INP-3 — an artifact is as old as it is, and the run says so

The age of every supplied artifact is computed and recorded. A run may be given a maximum
age, and an artifact older than it is refused with its age named.

**Why:** a Core Web Vitals export from March describes a site that has been deployed a
hundred times since. Nothing about the file says it is stale, and the verdict it produces
is indistinguishable from a fresh one.
**Reader:** **none**, and the default makes it matter. The limit is off unless the operator
passes one — `--max-artifact-age` defaults to `0`, meaning no limit — so the shipped
behaviour is that an artifact of any age is accepted. Neither the age computation nor the
limit is named by any test function: an artifact-age check that returned a constant zero
would pass the suite.

### INP-4 — an artifact answers for the page it describes and no other

Artifacts are applied to the page they claim and are never spread across a sample. An item
decided from an artifact keeps the primary page's verdict rather than being aggregated over
sampled pages.

**Why:** one measurement of one page is not a claim about four others. Aggregating it would
manufacture a site-wide verdict out of a single file.
**Reader:** enforced, and by the strongest kind of reader available here — an end-to-end
sampled run asserts that the artifact-backed items carry no per-page count while other
items do, and a second test pins which items read an artifact by comparing the registry
against the runner's own source line.

### INP-5 — a lab measurement is never reported as field data

Where a number was produced by a synthetic run rather than observed from real users, the
report says so, and no item whose title asks about field data is decided from a lab number.

**Why:** the two answer different questions and a client acts differently on each. The
distinction is invisible in the number itself.
**Reader:** **none.** Nothing in the suite distinguishes the two provenances, and
`specs/registry/` records the one item where the confusion has already been measured:
SP-112's title names Core Web Vitals *in Search Console* and its rule reads field data from
the PageSpeed API — the identical rule to SP-108.

### INP-6 — credential discovery is an ordered contract

Credentials are looked for in a stated order, first hit wins, and the order is part of the
contract rather than an implementation detail. The shell environment always outranks a file
on disk.

**Why:** an operator auditing a client's site from that client's directory must not have
their own credentials silently replaced by a `.env` the client shipped. "First hit wins" is
only safe if the first place looked is the one the operator controls most directly.
**Reader:** **none.** The order is stated in prose in two places — the credential finder
and the environment loader's docstring, which lists four sources and says the real shell
environment always wins — and asserted by nothing. Neither function is named in any test
function. A reordering that put a repository `.env` above the process environment would
pass the suite and change which key a run uses.

### INP-7 — key material never reaches a written artifact; paths may

Every secret value is removed from everything the run writes, including the evidence file
and the run log. A *path* to a credential is not a secret and stays readable, because a
reader needs to know which credential was used.

**Why:** the run log is built from each script's argv, so a key passed as an argument lands
in it verbatim, and the artifact is a file operators send to clients. Redaction over the
whole payload rather than the log alone is deliberate: a script that echoes its arguments
into an error message leaks the same key by a route nobody enumerated.
**Reader:** partial, and the split inside it is the point.
`test_secret_values_are_replaced_everywhere` pins
substitution throughout a nested structure, `test_nothing_is_touched_without_secrets` pins
the identity case, `test_an_evidence_file_is_redacted_and_written` pins the written file,
`test_redaction_reaches_sampled_page_evidence` pins the sampled path, and
`test_a_safe_browsing_env_key_never_reaches_written_artifacts` pins the one secret that
arrives from the environment rather than from a flag. What is unread is the *membership* of
the secret set: the two constants naming which keys are secret are named by no test, so a
key added to the run and forgotten here would be written out in full.

### INP-8 — the Search Console property is derived, overridable, and not a URL

The default property is the domain property for the site's registrable domain. An operator
may override it. A URL-prefix spelling is not the property and requesting one is an error
the report explains rather than a permission problem.

**Why:** this costs a round every time somebody meets it: the API answers a domain property
and refuses the URL, and the refusal reads as missing access. Deriving the right form by
default is what stops the operator debugging their credentials.
**Reader:** partial. The derivation is pinned by the public-suffix tests and by the
redirect test that asserts the property follows a cross-host destination; the override
reaches the plan. The fallback list has no test, and nothing asserts the four distinct
reasons a Search Console item may have no verdict, which is the table the report is
supposed to explain.

### INP-9 — Search Console opportunities are reported and never scored

Queries and pages Search Console suggests are carried into the report and printed outside
the score.

**Why:** they are not verdicts about the site. Scoring them would make the number move with
somebody else's index rather than with the site, and a client's score would change while
they changed nothing.
**Reader:** **none.** The carrying and the printing are implemented; nothing asserts that
the opportunities stay out of the score, and nothing asserts they are printed at all.

### INP-10 — the public suffix list is bundled, dated, and announces its own decay

The list the property is derived from ships with the tool, so a run is reproducible
offline. Its snapshot date is readable. Past a stated age the run says the list is old, and
it says so only when the list actually decided something.

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

* what a checker does with an artifact once it is accepted — `specs/evidence/`;
* how a missing or refused input becomes a plan decision and a status —
  `specs/run-lifecycle/` RUN-5;
* what the report shows about provenance and where — `specs/reporting/`;
* whether an item's title matches the data it reads — `specs/registry/` REG-6, which owns
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
`specs/registry/` says one does, and its rule reads the lab path.

## Appendix A — measured disagreements, 4 September 2026

Observation, not specification. Measured at commit `5c768de`.

### A.1 — the freshness limit is off by default and read by nothing

`--max-artifact-age` defaults to `0`, which the code treats as no limit. So an artifact
exported in March is accepted in September without comment, and every item it decides is
reported as a measurement of the site as it is now.

Neither half has a reader. Searching all 1 280 test functions for the age computation and
for the limit returns nothing: an implementation that computed every artifact's age as zero,
or a comparison that never fired, would pass the whole suite.

This is the gap the capability inventory recorded as G10, and measuring it adds one thing
to the record: the *check* is unread, not merely the default. Turning the default on would
not make the behaviour tested.

### A.2 — the credential discovery order is prose in two files and an assertion in none

The environment loader documents four sources in a fixed order and states that the real
shell environment always wins. The credential finder documents its own four-step order.
Neither function is named by any test function.

The consequence is specific rather than theoretical. The order exists to stop a `.env` in
a client's working directory overriding the operator's own exported credentials — an
operator audits from wherever the client's files are. A reordering that put the file above
the environment would change which credential a run authenticates with, produce a complete
and plausible report about the client's own Search Console property, and redden nothing.

### A.3 — the secret mechanism is well read and its membership is not

Redaction is covered from five directions, including the one secret that arrives through
the environment rather than a flag, and it is applied to the whole payload rather than to
the run log alone — with a comment explaining why, which is the shape of a rule somebody
had already been bitten by.

What no test names is the *set*: the constant listing which context keys hold key material,
and the constant listing the environment variables the Safe Browsing key may arrive under.
A key added to the run and not added to those tuples is written into the evidence file in
full, and the suite stays green. The mechanism is guarded; the list of what to apply it to
is not.

### A.4 — four Search Console behaviours are stated and unread

The fallback property list, the four-reason table for a `gsc` item having no verdict, that
opportunities are printed, and that opportunities stay out of the score — none is named by
any test function. The last is the one worth separating: it is the rule that keeps a
client's score from moving when Google's index moves, and it is the kind of rule that is
obeyed until somebody sums a list that happens to include it.

## Appendix B — how much of this document is enforced

**Probed:** none of these rows by mutation — the executor that had been running mutation
probes ran out of credits partway through this suite of documents. The rows below were
derived by parsing all 1 280 test functions and asking, per symbol, which bodies name it,
then reading those bodies. That is the method Appendix A.1 to A.4 rest on, and its limit is
the one `specs/evidence/` A.4 states: a test can exercise something without naming it, so
`none` here means "named by nothing", which is a lower bound on coverage.

| | requirements |
|---|---|
| **enforced** | INP-1, INP-4 |
| **partial** | INP-2, INP-7, INP-8, INP-10 |
| **none** | INP-3, INP-5, INP-6, INP-9 |
| **opposed** | — none |

Invariants: INV-I3 enforced; INV-I1 and INV-I2 partial; INV-I4 unread.

**Two enforced, four partial, four unread, of ten.**

The split falls along one line, and it is not the line effort would predict. Both enforced
requirements are about a *file* — is it about this page, is it applied to the right page.
Every unread one is about a *policy*: how old is too old, which credential wins, what may
be scored, what counts as field data.

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
