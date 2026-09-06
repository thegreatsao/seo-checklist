# Run lifecycle — what a run may attempt, what it must refuse, and what it owes when it refuses

## Purpose

Everything between an operator typing a URL and a graded item existing — the modes that
decide how much of the registry can answer, the plan, the execution and its failure
kinds, the gates that end a run, and the profiles, sampling and shared crawl that narrow
or widen it. This layer assigns every `N/A`, every `NEEDS_INPUT` and almost every
`NO_DATA` in a report, so most of a run is settled here before a checker runs at all.
Its failures are quiet in a particular way: a wrongly refused item prints a row that
looks exactly like a legitimate one, and the score then describes a smaller or different
site than the one that was audited.

**Capability:** everything between an operator typing a URL and a graded item existing —
modes and capability gating, plan construction, execution and failure classification, the
entry gate, the wrong-page guard, redirect adoption, profiles and detection, sampling and
aggregation, and the shared crawl (C9–C18 of the capability inventory).

This document is normative and is written as though no code existed. Where the
implementation disagrees, the implementation is presumed wrong until this document is
changed by argument. Appendix A records disagreements measured on 29 August 2026.

Every requirement carries a **Reader** line naming what makes it fail when violated;
Appendix B is the census of those lines. A requirement whose reader is `none` is an
intention, and is counted as one.

**Inherited, not restated:** the eight statuses and what each means belong to
[`openspec/specs/verdicts/`](../verdicts/spec.md); what an item is and what `requires` may say
belong to [`openspec/specs/registry/`](../registry/spec.md); how a graded item becomes a number
belongs to [`openspec/specs/scoring/`](../scoring/spec.md). This document says what a run *does*,
and it may not redefine a status to make a refusal cheaper.

---

## 1. Why the lifecycle is where the audit is decided

Nine of the eight statuses are assigned here. Every `N/A`, every `NEEDS_INPUT` and almost
every `NO_DATA` in a report is a decision this layer made *before* any checker ran: the
mode did not carry the capability, the input was absent, the page was not the site's, the
crawl failed. The checkers decide `PASS`, `WARN` and `FAIL`. This document decides
everything else, which is most of a run.

That makes its failures quiet in a particular way — though not for the reason an earlier
draft of this paragraph gave, which was that nobody argues with an absence. Some of these
defects are perfectly visible: a wrongly refused item prints a row, and a run that adopts
the wrong host prints a complete report about the wrong site. What they lack is not
visibility but a *reader* — nothing red goes off, and the row that does appear looks
exactly like a legitimate one. The score then describes a smaller or different site than
the one that was audited, and the denominator moves without anyone deciding it should.

Two measured examples, both in Appendix A. A failed shared crawl reports `NEEDS_INPUT` for
every site-wide item, sending the operator to supply a file the run produces itself; the
code's own comment and the message it prints to the operator both say `NO_DATA`, which is
what the requirement says and what the code does not do. And the constant that decides
whether a page is an interstitial is pinned by no test at its value — only by an
inequality against a second constant, so both could move together and nothing would say
so.

## 2. What a run is

A run is six decisions in order, and each one can end it:

1. **Mode** — `live`, `page` or `archive`, resolving to a set of capabilities.
2. **Entry** — one fetch of the requested URL, which also settles the redirect target,
   the profile detection and the guard.
3. **Scope** — a profile, which may exclude categories, scripts and items.
4. **Crawl** — one site crawl, whose inventory is an input to site-wide items.
5. **Plan** — registry items whose `requires` the mode carries and whose inputs exist,
   folded into one entry per distinct script invocation.
6. **Execution** — the planned scripts, in parallel, each with a timeout, each producing
   either a result or a classified failure.

Sampling wraps 5 and 6: page-level items run once per sampled page and are aggregated.

### 2.1 The capability table

| mode | capabilities |
|---|---|
| `live` | `offline`, `fetch`, `crawl`, `api` |
| `page` | `offline`, `fetch`, `api` |
| `archive` | `offline` |

`gsc` and `safe_browsing` are not in any mode's set: they are `api` capabilities gated a
second time by whether their credential exists (RUN-2).

### 2.2 The failure vocabulary

A planned script that produces no usable result fails in exactly one of five ways:
`timeout`, `crash`, `missing`, `bad_output`, `signal`. All five end as `NO_DATA` and none
of them is the same problem: a timeout is retryable, a crash is a defect in a checker, a
missing script is a defect in the registry, `bad_output` is a contract violation, and a
signal is the operating system, not the script.

## Requirements

### Requirement: RUN-1 — a mode is a set of capabilities, and the table is the contract

The three modes and their capability sets in §2.1 are normative. An item SHALL run when
its `requires` is in the running mode's set, and MUST NOT run when it is not. A new mode,
or a change to a set, is a change to this document first.

**Why:** the mode decides how much of the registry can answer at all, so it decides the
denominator every score is a fraction of. Two audits of the same site in different modes
are not comparable, and the report can only say so if the table it is comparing against is
fixed.
**Reader:** enforced. `TheModeTableIsTheContract` holds seven properties over the three
symbols: `test_the_three_modes_carry_exactly_these_capabilities` pins §2.1's table,
transcribed into the test rather than imported, so a change to a set fails until this
document is changed too; `test_every_mode_is_offered_to_an_operator` ties `MODE_HELP` to
it; `test_resolve_mode_hands_back_the_table_row` and
`test_the_default_is_live_and_archive_files_choose_archive` cover the resolution;
`test_a_run_cannot_edit_the_table_it_was_handed` pins that the returned set is a copy; and
`test_an_item_runs_exactly_when_its_requirement_is_in_the_mode` covers the behavioural
half over every mode × capability pair, planned or skipped, with no case left to inference.

Probed on 5 September 2026 with the mutation this line used to name as invisible — `page`
mode silently gaining `crawl`. Two of the seven redden, and `tests/test_registry.py` stays
green, which is exactly what the old reading predicted of it.

`test_the_registry_asks_only_for_capabilities_this_document_accounts_for` settles §6's
question about `VALID_REQUIRES` in the direction §6 argued for: a capability no mode
carries is legitimate — `gsc` and `safe_browsing` are that by design — so the rule is that
every `requires` in the registry is either in some mode's set or is one of the twice-gated
pair. It also asserts the pair is actually asked for by some item, since a second gate over
nothing is a rule describing nothing.

#### Scenario: a mode is widened without the table being widened
- **WHEN** `page` mode gains `crawl` in the code and §2.1 still lists three
  capabilities for it
- **THEN** the contract is broken, whatever the run then produces
- **AND** the table is what a comparison of two audits is checked against, so a set
  that moves silently makes every such comparison meaningless

#### Scenario: an item asks for a capability the mode does not carry
- **WHEN** an item's `requires` is outside the running mode's set
- **THEN** no invocation is planned for it, in every mode × capability pair rather
  than in the one pair a fixture happens to exercise

#### Scenario: the table a run was handed is edited by the run
- **WHEN** a run mutates the capability set `resolve_mode` returned
- **THEN** the next reader of the table sees something this document never wrote,
  so the set handed out is a copy

#### Scenario: a capability no mode carries
- **WHEN** the registry names `gsc` or `safe_browsing`, which are in no mode's set
- **THEN** that is legitimate rather than a gap in the table, because both are gated
  a second time on their credential (RUN-2)
- **AND** a twice-gated capability that no item asks for would be a rule describing
  nothing

### Requirement: RUN-2 — an unsatisfiable requirement is `N/A`; an absent credential is `NEEDS_INPUT`

Two different refusals, and they MUST NOT be spelled alike. An item whose `requires` the
mode does not carry is **out of scope**: it SHALL report `N/A`, naming the mode. An item
whose capability the mode carries but whose credential is absent is **unanswered**: it
SHALL report `NEEDS_INPUT`, naming the flag or environment variable that would supply it.

**Why:** the two name different people. Out of scope is the operator's own choice of mode
and needs no action; a missing credential is an action somebody can take, and the report
is where they find out which. Collapsing them either hides work that could be done or
invents work that cannot.
**Reader:** enforced. `test_missing_credentials_is_undecided_not_out_of_scope`,
`test_a_mode_without_network_puts_it_out_of_scope`,
`test_missing_key_in_a_network_mode_needs_input` and
`test_archive_mode_makes_the_api_check_not_applicable` pin both branches for `gsc` and
`safe_browsing`, and `test_one_missing_credential_gets_one_status_from_both_boundaries`
holds the second branch against the grader as well as the planner.

The general sentence had no reader until 0.95.0: nothing fed an ordinary capability into a
mode that lacks it. `test_an_ordinary_capability_the_mode_lacks_is_not_a_request_for_input`
sweeps every mode against every capability outside its set rather than writing the one case
the sentence names, because a capability added to one mode's set and not another's is how
this would start answering differently for a mode nobody thought about. Probed by routing
the branch to `NEEDS_INPUT` and by taking the mode out of the reason.

#### Scenario: an ordinary capability the mode lacks
- **WHEN** an item requiring `crawl` is planned under `page` mode, which carries
  `offline`, `fetch` and `api`
- **THEN** it is `N/A`, and the reason names the mode
- **AND** it is not `NEEDS_INPUT`, because no flag supplies a crawl the mode forbids

#### Scenario: the mode could have asked and had no credential
- **WHEN** a Search Console item is planned under `live` with no credentials on disk
- **THEN** it is `NEEDS_INPUT`, naming `GSC_CREDENTIALS_PATH`
- **AND** it is not `N/A`, which would drop it out of the coverage denominator and
  raise coverage exactly where the audit is thinnest

#### Scenario: the mode makes no network calls at all
- **WHEN** the same item is planned under `archive`
- **THEN** it is `N/A` naming the mode, because supplying the credential would change
  nothing

### Requirement: RUN-3 — archive mode makes no network call, whatever credentials are present

`archive` carries only `offline`. A credential on disk MUST NOT re-enable a capability the
mode excludes, and the run SHALL make zero requests.

**Why:** archive mode is what an operator uses when they must not touch the site — a
client's production host, a system under embargo, a machine with no route. A mode that
quietly makes one API call because a key happened to be present breaks a promise the
operator relied on, and nothing in the report would show it.
**Reader:** enforced. `test_a_key_on_disk_does_not_re_enable_search_console_in_archive
_mode` places a real key file and requires `resolve_gsc` to return nothing under
`archive` while returning the same key under `live` — so the gate is read in both
directions rather than by an implementation that always refuses.
`test_the_operator_is_told_the_key_was_ignored` covers the announcement, because silently
dropping a key leaves an operator believing Search Console ran.
`test_archive_plans_nothing_that_could_reach_the_network` sweeps the real registry, not a
fixture, and requires the set of planned items asking for anything but `offline` to be
empty; `test_the_credentials_do_not_change_what_archive_plans` holds the requirement's own
words — *whatever credentials are present* — by planning twice and comparing.

Probed twice: removing the capability gate in `resolve_gsc` reddens two, and letting
`fetch` items through the mode gate reddens the registry sweep.

The sweep carries a vacuity guard, and it earned it on the first run: with an empty context
`build_plan` plans *nothing* under `archive`, because every offline item wants a template
argument, so the assertion would have swept an empty set and passed. The context now
supplies what an archive run actually has in hand.

Until 5 September 2026 this read `none`, with a warning attached that is worth keeping:
`test_archive_mode_claims_nothing_about_a_network_it_never_touched` is a sound test of
something else — `allow_private` recorded, the flag not echoed, provenance warnings empty.
It places no credential and asserts no absence of requests. Its docstring was honest; its
name was not, and a census taken from names would have credited it with the guarantee.

#### Scenario: a credential is on disk and the mode excludes it
- **WHEN** a Search Console key file exists and the mode is `archive`
- **THEN** the run resolves no credential from it
- **AND** the same file under `live` resolves to that key, so the gate is read in
  both directions rather than by an implementation that always refuses

#### Scenario: the plan is asked the same question twice
- **WHEN** an archive run is planned once with every credential present and once with
  none
- **THEN** the two plans are identical, which is what *whatever credentials are
  present* means

#### Scenario: nothing archive plans could reach the network
- **WHEN** the whole registry is planned under `archive`, with the context an archive
  run actually holds
- **THEN** no planned item asks for anything but `offline`
- **AND** the plan is non-empty, or the sweep passed over nothing and proved nothing

#### Scenario: the ignored key is not ignored silently
- **WHEN** a key is dropped because the mode excludes its capability
- **THEN** the operator is told, because silence leaves them believing Search Console
  ran

### Requirement: RUN-4 — a plan entry is one script with one argument list, and identical invocations fold

Two items that resolve to the same script with the same arguments SHALL produce one
execution. The fold MUST be by the invocation, never by the item.

**Why:** the registry deliberately asks some questions twice under different source
numbers, and REG-11 rules on which twin carries the weight. Running the script twice
doubles the cost of every audit and creates the possibility of two answers to one
question — which the report has no way to show.
**Reader:** enforced. `test_two_items_with_one_invocation_run_it_once` asserts one plan
entry carrying both ids; `test_the_same_script_with_different_arguments_is_two_invocations`
asserts two, which is what makes the first mean anything — a fold keyed on the script alone
would satisfy it while silently dropping an argument; and
`test_the_fold_is_by_invocation_and_not_by_item` puts three items across two invocations so
the sharing is by what is run rather than by adjacency. Probed by keying the plan on the
script alone: two of the three redden.

#### Scenario: one question asked twice by the registry
- **WHEN** two items resolve to the same script with the same argument list
- **THEN** one plan entry carries both ids, and the script runs once

#### Scenario: the same script with different arguments
- **WHEN** two items resolve to one script with different argument lists
- **THEN** they are two plan entries
- **AND** a fold keyed on the script alone would satisfy the case above while
  silently dropping one of the two argument lists

#### Scenario: the fold follows what is run, not what is adjacent
- **WHEN** three items resolve across two distinct invocations
- **THEN** the sharing follows the invocation, so which items sit next to each other
  in the registry cannot change the plan

### Requirement: RUN-5 — a missing input names its flag; a refused input says why it was refused

An item whose template names an input the run does not have SHALL be `NEEDS_INPUT`, and
the evidence MUST name the flag that would supply it. An input that was supplied and
*rejected* — stale, or describing a different site — SHALL carry the reason for the
rejection instead, and the two sentences MUST NOT be interchangeable.

**Why:** "you did not give me this" and "what you gave me was not about this site" send
the operator to different actions, and the second is the one people get wrong twice.
**Reader:** enforced. `test_a_refused_input_says_something_other_than_missing` pins the
distinction directly — a refused artifact's reason contains its rejection and not the
words "missing input", and the same item with an empty context says "missing input"; and
`test_an_artifact_from_the_other_site_is_refused_with_the_reason` pins it end to end.
`test_every_key_an_operator_can_fill_names_its_flag_and_asks_for_it` holds the flag-naming
half over the whole supply table rather than the one entry `--keyword` used to stand for,
and asserts the instruction itself reaches the reason, not merely that a reason exists.

The composition of that table is held separately, and had to be: sweeping the entries
proves nothing about a key that has no entry. Deriving the set from the registry's own
templates is what showed two — `indexnow_key` and `gsc_property` — reporting the bare
`missing input '...'` this requirement exists to forbid.

#### Scenario: the input was never supplied
- **WHEN** an item's template names a context key the run does not hold
- **THEN** it is `NEEDS_INPUT` and the reason names the flag that would supply it
- **AND** a reason that says only "missing input" sends the operator to guess which
  of the six supply-table entries it means

#### Scenario: the input was supplied and refused
- **WHEN** an artifact is handed to the run and rejected as stale or as describing a
  different site
- **THEN** the reason is the rejection, and does not contain the words "missing input"
- **AND** the same item with an empty context says "missing input", so the two
  sentences are distinguishable rather than merely both present

#### Scenario: the four keys nobody asserts
- **WHEN** the Search Console, link-export or server-log template keys are absent
- **THEN** each names its own flag, on the same terms as `--keyword`, rather than
  appearing in the suite only as fixture input

### Requirement: RUN-6 — every argument a run adds is visible where the verdict is read

A run appends three kinds of argument a reader of the registry cannot predict: registry
args, opt-in flags, and a profile's `script_args`. All three SHALL land in the recorded
invocation, and a threshold a profile moved MUST be visible beside the verdict it moved.

**Why:** a profile that changes a threshold changes what `PASS` means. A report that shows
the verdict and not the threshold is unfalsifiable from the outside — the number is right
for a rule the reader cannot see.
**Reader:** partial, and the visible half is not the one that matters most.
`test_profile_args_reach_the_plan_as_argv` pins the arguments into the invocation, and
`test_the_moved_threshold_is_in_the_evidence_trail` pins the moved threshold into the
answering script's own summary. Nothing asserts that the run's recorded `profile_args`
reach the artifact, and nothing threads opt-in flags through the plan at all — they are
tested where they are generated and not where they are used.

#### Scenario: a profile moves a threshold
- **WHEN** a profile's `script_args` change the bound an item is judged against
- **THEN** the moved threshold is in the recorded invocation
- **AND** it is echoed in the answering script's own summary, beside the verdict it
  moved

#### Scenario: the verdict is shown and the threshold is not
- **WHEN** a report carries the verdict a moved threshold produced and not the
  threshold
- **THEN** the number is unfalsifiable from the outside: it is right for a rule the
  reader cannot see

#### Scenario: an opt-in flag the run adds
- **WHEN** a run attaches `--verify-returns` or `--verify-bots` to the one script it
  belongs to
- **THEN** the flag is in that script's recorded invocation, not only in the function
  that generated it

### Requirement: RUN-7 — a failed script is `NO_DATA` with a kind, and the kinds are counted apart

Five failure kinds, all of which SHALL be graded `NO_DATA`, and none of which is
interchangeable with another. The kind MUST be recorded per item and the counts reported
per kind.

**Why:** the status says the audit could not answer, which is what the score needs. The
kind says whose problem it is, which is what the next release needs. A run where eleven
items timed out and a run where eleven crashed produce the same score and require entirely
different work.
**Reader:** partial, and thinner than the vocabulary suggests. Every kind is *labelled* —
`test_every_kind_run_script_produces_has_a_label` derives the kinds from the runner's own
source and asserts none is unlabelled, which is a good shape and not a reader of the
statuses. Only `timeout` is followed through to a verdict:
`test_timeout_is_labelled_and_marked_retryable` asserts `NO_DATA`. `crash`, `missing`,
`bad_output` and `signal` are each asserted at the label and never graded, so a change
routing one of them to `PASS` would redden nothing. The per-kind tally has no reader at
all.

#### Scenario: a checker crashes
- **WHEN** a planned script exits non-zero
- **THEN** every item that depended on it is `NO_DATA` carrying the kind `crash`
- **AND** it is not `PASS` or `WARN`, which a change routing the kind past the
  grading branch would produce

#### Scenario: the four kinds that are labelled and never graded
- **WHEN** a run produces `crash`, `missing`, `bad_output` or `signal`
- **THEN** each ends as `NO_DATA`, on the same terms as `timeout`
- **AND** asserting that a kind carries its label says nothing about the status it
  becomes

#### Scenario: the operating system killed the child
- **WHEN** a script is killed by a signal rather than failing
- **THEN** the kind is `signal` and not `crash`, because nothing in the script ran
  wrong and opening it will show nothing

#### Scenario: two runs with the same score and different work
- **WHEN** one run has eleven timeouts and another eleven crashes
- **THEN** the scores are identical and the per-kind tally is what separates them
- **AND** a tally asserted only to be empty is a statement about the fixtures

### Requirement: RUN-8 — nothing runs against an entry the audit could not read, and the absence of a score is the output

When the entry page cannot be read, every item that needs the live site SHALL be `NO_DATA`
and no script SHALL be executed against it. The run still produces a report; that report
MUST carry no score, and MUST say why.

**Why:** a score computed from the handful of items that do not need the site is a number
about almost nothing, printed in the same place as a real one. Refusing to print it is the
finding.
**Reader:** partial. `test_everything_that_reads_the_live_site_is_undecided` and its
siblings pin the statuses, that they are `NO_DATA` rather than `N/A`, that Search Console
still answers, and that the gated items never reach the plan;
`test_the_score_is_none_when_nothing_was_decided` and
`test_a_challenge_page_is_refused_and_nothing_is_scored` pin the missing score in both the
unit and the live path. What is unread is the "nothing runs" half as opposed to "nothing
is planned": no test asserts that execution was skipped, only that the plan was empty.

#### Scenario: the entry page cannot be read
- **WHEN** the entry fetch fails
- **THEN** every item requiring `fetch`, `crawl` or `api` is `NO_DATA` carrying the
  reason
- **AND** it is `NO_DATA` rather than `N/A`, because the items apply and the audit
  simply could not answer them

#### Scenario: nothing planned is not the same as nothing run
- **WHEN** the gated items are absent from the plan
- **THEN** no script is executed against the unreadable entry either
- **AND** an assertion that the plan is empty does not establish this

#### Scenario: a score over the items that did not need the site
- **WHEN** only items needing no live site could be decided
- **THEN** no score is printed, and the report says why
- **AND** printing one puts a number about almost nothing in the same place as a real
  one

#### Scenario: the page loaded and is the wrong page
- **WHEN** the entry is an interstitial or an error page rather than unreachable
- **THEN** the offline checks are gated too, because the file exists and reads
  perfectly and nothing else stops them grading the wrong document

### Requirement: RUN-9 — a wrong page is decided by conjunction, never by one signal

An interstitial SHALL be a page carrying a challenge fingerprint **and** under the
visible-word threshold. Either signal alone MUST NOT end a run: a long page quoting a
vendor's name is an article about bot protection, and a short page with no fingerprint is
a short page.

**Why:** this rule guards the whole audit — a page wrongly called an interstitial ends the
run. Both single-signal versions were tried and both were wrong in production: the
fingerprint alone refuses articles about Cloudflare, and the word count alone refuses
every thin page on the web.
**Reader:** enforced. Three tests pin the three corners:
`test_a_short_article_quoting_a_vendor_string_is_not_a_challenge` (short, marker in prose,
not a challenge), `test_a_content_page_with_the_marker_in_its_markup_survives` (long,
marker in markup, not a challenge) and
`test_script_bulk_does_not_make_a_challenge_look_content_rich` (short, marker, challenge).

#### Scenario: an article about bot protection
- **WHEN** a page carries a vendor's challenge string and enough visible prose to be
  content
- **THEN** it is not an interstitial and the run continues
- **AND** the fingerprint alone would refuse every page whose subject is bot
  protection, and every ordinary page whose host has turned a JS detection on

#### Scenario: a thin page with no fingerprint
- **WHEN** a page is under the visible-word threshold and carries no challenge
  fingerprint
- **THEN** it is a short page, not an interstitial, and the registry's own thin-content
  items are what judge it

#### Scenario: a challenge page that is mostly JavaScript
- **WHEN** a challenge page carries a script body long enough to push a naive word
  count over the threshold
- **THEN** the count is taken over visible text only, and the page is refused
- **AND** counting script bodies would carry every interstitial past the threshold

#### Scenario: the threshold moves without a reader
- **WHEN** the word threshold and the thin-entry threshold are changed together, so
  the inequality between them still holds
- **THEN** the rule that ends runs has changed and nothing says so

### Requirement: RUN-10 — a soft 404 is decided by title equality, never by containment

A title *segment* equal to a not-found phrase SHALL be a soft 404. A title that merely
contains one MUST NOT be.

**Why:** containment refuses every article whose subject is error pages, and the
containment version shipped. The rule is narrow on purpose and the narrowness is the
requirement.
**Reader:** enforced. `test_an_article_about_404s_is_not_a_soft_404` pins four titles
containing the phrases as substrings and requires all four to pass, and
`test_soft_404_does_not_depend_on_page_size` pins that a matching title decides regardless
of length.

#### Scenario: an article whose title contains a not-found phrase
- **WHEN** a title such as *How to fix 404 errors on your site* or *Room 404 | Hotel
  Beispiel* contains a phrase as a substring
- **THEN** it is not a soft 404 and the audit runs
- **AND** containment would refuse every article whose subject is error pages, which
  is the version that shipped

#### Scenario: a title segment that is the phrase
- **WHEN** a title segment, split on the site's own separator, equals a not-found
  phrase
- **THEN** the page is a soft 404

#### Scenario: a templated error page carrying the whole site
- **WHEN** a soft 404 serves the site's nav and footer and is not small
- **THEN** the title still decides it, because word count is not a signal for this
  rule

### Requirement: RUN-11 — the guard records its verdict whether or not it acted

The guard's finding SHALL be recorded on every run, including when it is overridden. An
overridden guard MUST make the run's provenance say so wherever the score is shown.

**Why:** a score computed over an interstitial is not wrong so much as about a different
page, and the only defence is that the report says which page. An override that erases the
suspicion rather than recording it makes the two runs indistinguishable afterwards.
**Reader:** enforced. `test_no_page_guard_records_the_suspicion_instead_of_erasing_it`
pins the recording, `test_the_override_scores_it_and_says_so_everywhere` pins it through a
live run into the output, `test_a_scored_interstitial_says_so` pins it into both renderers,
and `test_an_enforced_guard_is_not_a_caveat` pins the converse — a guard that acted is not
also a warning.

#### Scenario: the guard is overridden
- **WHEN** a run passes `--no-page-guard` over a page the guard found suspicious
- **THEN** the finding is recorded rather than erased, and the run's provenance says
  so wherever the score is shown
- **AND** an override that erases the suspicion makes a run over an interstitial
  indistinguishable afterwards from a run over the site

#### Scenario: the guard acted
- **WHEN** the guard ends the run
- **THEN** it is reported as a refusal, and not also as a caveat attached to a score
  that does not exist

#### Scenario: a scored interstitial reaches both surfaces
- **WHEN** an overridden guard's run is rendered
- **THEN** every renderer that shows the score shows that the page was suspected

### Requirement: RUN-12 — a cross-host redirect moves the audit; a same-host hop does not

When the entry redirects to another host, that host SHALL be the audited site: the URL
sample and the derived Search Console property follow it. A redirect within the same host
MUST leave the requested URL as the subject, so the hop is still reported as a finding.

**Why:** auditing `example.com` and reporting about `www.example.net` under the first
name is a wrong report, not a wrong verdict. But adopting every same-host hop would hide
the redirect itself, which is one of the things being checked.
**Reader:** enforced. `test_another_host_wins`,
`test_a_same_host_hop_keeps_the_requested_url` and `test_www_counts_as_another_host` pin
the rule; `test_the_search_console_property_follows_the_destination` pins the derived
property; and `test_the_sample_follows_the_destination_host` pins the sample, through a
live redirect.

#### Scenario: the entry redirects to another host
- **WHEN** the requested URL lands on a different netloc
- **THEN** the destination is the audited site: the sample and the derived Search
  Console property both follow it
- **AND** keeping the requested URL collapses the sample to the single entry page and
  derives a property the service account has no access to, both of which fail quietly

#### Scenario: `www` is another host
- **WHEN** the redirect only adds or drops `www`
- **THEN** it is a different netloc and the audit moves

#### Scenario: a hop within the same host
- **WHEN** the redirect stays on the requested host
- **THEN** the requested URL remains the subject
- **AND** the redirect checker is still handed the address that redirects, so the hop
  is reported rather than absorbed

### Requirement: RUN-13 — a profile narrows scope to `N/A` naming the profile, never to silence

An item a profile excludes SHALL be reported, as `N/A`, with the profile's own words for
why. It MUST NOT be simply absent, and the reason MUST NOT be a generic phrase.

**Why:** a partition that drops rows stops summing to the registry, and the score becomes
a fraction of a sample nobody chose. Naming the profile is what lets a reader tell "this
does not apply to your kind of site" from "the tool did not look".
**Reader:** enforced. `test_an_excluded_item_carries_the_profiles_words_not_a_shrug` pins
that the reason is the profile's own sentence rather than a shrug, and
`test_no_profile_excludes_a_critical_item` pins the floor.

The status half was unread until 0.95.1: the construction that names the profile beside the
`N/A` had no test, because the one test asserting an excluded item never reaches the plan
supplies its own hand-written reason rather than one the profile produced.
`test_an_excluded_item_is_reported_as_na_naming_the_profile` runs the shipped `local`
profile over the real registry and holds the status, the profile's name and the sentence's
substance for every item it excludes — over the registry rather than a fixture, because the
three exclusion routes each build their own sentence and a fixture exercises only the one it
was written for. `test_no_exclusion_is_a_shrug_in_any_shipped_profile` sweeps every profile
in the file for the fallback phrase. Probed by making the id route return the shrug.

#### Scenario: a profile drops an item from the report
- **WHEN** an item a profile excludes is absent rather than reported
- **THEN** the partition stops summing to the registry, and the score becomes a
  fraction of a sample nobody chose

#### Scenario: an excluded item is reported
- **WHEN** a profile excludes an item by category, by script or by id
- **THEN** the item is `N/A`, and the reason is the profile's own sentence, naming the
  profile
- **AND** a generic phrase such as "excluded by profile" is the one exclusion a reader
  cannot reconstruct, on the surface where narrowing scope has to justify itself

#### Scenario: a profile that excludes a critical item
- **WHEN** a profile's exclusion list would drop an item the registry marks critical
- **THEN** the profile is wrong, because no site type makes a critical item
  unanswerable

### Requirement: RUN-14 — every non-answer resolves to the widest scope

Silence, an unreadable answer, no terminal, end of input, an interrupt: all of them SHALL
resolve to the full registry. A narrower scope MUST be chosen deliberately or not at all.

**Why:** the failure modes of a prompt are all silence, and silence must not be able to
shrink the audit. The dangerous direction is the quiet one — a narrowed scope produces a
higher score over fewer items and looks like good news.
**Reader:** enforced, and the requirement was violated until 0.95.1. The prompt's three
silent exits — end of input, interrupt, and three unrecognised answers — all `return
suggested`, the *detected* profile whenever detection found one. A run whose entry page
looked like a local business, answered by an operator who pressed Ctrl-C, audited under
`local` and reported a higher score over fewer items with nobody having chosen that.

Four tests covered those exits and none of them read this. Every one called the prompt with
no detection argument, so `suggested` was `"default"` and the two branches were
indistinguishable. `test_falls_back_to_the_widest_scope_not_the_narrowest`,
`test_eof_is_treated_as_no_answer`, `test_without_a_terminal_it_does_not_ask` and
`test_no_prompt_flag_skips_the_question` are all sound about the case they construct and
silent about the case where the requirement can be broken.

`test_the_silent_exits_widen_the_audit` sweeps every non-default profile through all three
exits. `test_the_silent_exits_are_not_the_prompt_being_broken` is the floor beside it: a
`choose_profile` returning `"default"` unconditionally would satisfy the first test, so
Enter and the profile's own name are pinned as still narrowing.
`test_the_widening_says_the_suggestion_is_still_available` holds the sentence an operator
gets instead — and its first draft asserted the bare profile name, which the menu printed
above already contains, so the mutation that stopped the sentence naming the suggestion
passed it. It asserts the instruction now. The explicit flag, the non-interactive path and
`--profile auto` were enforced throughout. A.5 records the measurement, and
`openspec/specs/verdicts/` recorded the same defect from the other side as VRD-11.

#### Scenario: end of input, with a profile detected
- **WHEN** detection suggests `local` and the operator's input ends at the prompt
- **THEN** the run audits under `default`, the full registry
- **AND** it does not audit under `local`, which reports a higher score over fewer
  items with nobody having chosen that

#### Scenario: an interrupt, with a profile detected
- **WHEN** detection suggests `local` and the operator interrupts the prompt
- **THEN** the run audits under `default`

#### Scenario: three unrecognised answers, with a profile detected
- **WHEN** detection suggests `local` and the prompt exhausts its three attempts on
  replies that name no profile
- **THEN** the run audits under `default`

#### Scenario: the prompt is exercised where the defect cannot appear
- **WHEN** the prompt is called with no detection, so the suggestion is already
  `default`
- **THEN** both branches answer `default` and every silent exit looks correct
- **AND** a case built this way reads nothing: the requirement is only read where
  detection found something and the exit still widens

#### Scenario: the operator narrows deliberately
- **WHEN** a profile is named explicitly, or `--profile auto` accepts the detector's
  suggestion
- **THEN** the narrower scope is chosen, because passing the flag is the decision

### Requirement: RUN-15 — detection suggests, and never decides

A profile detected from the page SHALL be a suggestion. It MUST narrow the audit only
where the operator has asked for that in advance, thin evidence SHALL resolve to the
widest scope, and the signals behind a suggestion SHALL be shown rather than only its
conclusion.

**Why:** a heuristic that silently narrows scope is RUN-14's failure with a better excuse.
Showing the signals is what makes the suggestion arguable; a bare answer is a verdict
wearing a suggestion's clothes.
**Reader:** enforced. `test_thin_evidence_never_narrows_anything` and
`test_empty_input_is_an_error_not_a_guess` pin the resolution to `default`;
`test_auto_accepts_detection_without_asking` and
`test_detection_does_not_narrow_scope_without_a_terminal` pin the two ways a suggestion may
and may not be adopted; and from 0.95.1
`test_the_signals_reach_the_operator_and_not_only_the_conclusion` holds the "shown, not just
answered" half, which had been read inside one unit test of `detect` and by nothing on the
surface the operator sees.

The claim that detection reads structure rather than wording had no test in either
direction, and writing one found it false — A.8. Four tests hold it now: prose naming a
platform fingerprints nothing, the same names in markup still do, an inline script still
counts, and link paths, which were always read from `href` alone, still count. The last two
are what stop the first from being a way to switch detection off.

#### Scenario: the evidence is thin
- **WHEN** detection finds nothing conclusive
- **THEN** the resolution is `default`, and the operator is told the evidence was too
  thin to narrow anything

#### Scenario: a suggestion adopted without being asked for
- **WHEN** detection names a profile and neither an explicit flag nor `--profile auto`
  was given
- **THEN** the audit runs under the full registry
- **AND** a heuristic that narrows here is RUN-14's failure with a better excuse

#### Scenario: no terminal to ask at
- **WHEN** a run has no terminal and detection found a profile
- **THEN** the run proceeds under `default` and prints what detection suggested, so
  the operator can accept it deliberately on the next run

#### Scenario: the conclusion is shown and the signals are not
- **WHEN** the operator is given a detected profile without the signals behind it
- **THEN** the suggestion cannot be argued with, which makes it a verdict wearing a
  suggestion's clothes

### Requirement: RUN-16 — a sampled verdict is the worst page's, and the count is part of the evidence

Where an item is decided over several pages, the reported verdict SHALL be the worst of
them and the evidence MUST state how many pages were checked, how many decided, and how
many carry the reported verdict. Site-wide items MUST NOT be aggregated, and items decided
from an operator's artifact SHALL keep the primary page's verdict.

**Why:** the worst page is the honest summary of a site, and a count is what stops it being
read as a claim about every page. Without the count, one bad page out of eight and eight
bad pages out of eight print the same sentence.
**Reader:** enforced. `test_worst_page_verdict_wins_and_the_count_is_reported` pins the
rule and the count; `test_site_level_items_are_not_aggregated` and
`test_undecided_pages_do_not_become_a_verdict` pin the two exclusions;
`test_aggregate_evidence_names_undecided_pages_in_the_full_sample` pins the three-part
count; `test_one_measured_page_does_not_become_a_verdict_about_four_others` pins the
artifact rule end to end; and `test_the_measure_follows_the_worst_page` pins that the
reported measurement belongs to the page that produced the verdict.

#### Scenario: one bad page out of eight
- **WHEN** a page-level item fails on one of eight sampled pages
- **THEN** the reported verdict is the failure, and the evidence states that one page
  of eight carries it
- **AND** without the count, one bad page and eight bad pages print the same sentence

#### Scenario: the measurement and the verdict come from different pages
- **WHEN** the aggregated row keeps the entry page's numbers and the worst page's
  status
- **THEN** the report can print a passing measurement directly under a failing
  verdict, which is worse than printing the raw assertion

#### Scenario: pages that could not be decided
- **WHEN** some sampled pages produced no verdict
- **THEN** they do not become one, and the count says how many were checked, how many
  decided, and how many carry the reported verdict

#### Scenario: one artifact and four other pages
- **WHEN** an item is decided from an operator's artifact about the primary page
- **THEN** it keeps the primary page's verdict, and site-wide items are not aggregated
  at all

### Requirement: RUN-17 — the sample is spread, stable, and made of pages

A sample of N SHALL cover the site rather than its first corner, MUST be the same on two
runs over an unchanged site, and MUST contain pages: assets are dropped by extension,
non-page content types are dropped by their type, and URLs robots disallows are dropped
with a count the operator can see.

**Why:** a sample of the first N URLs measures a sitemap's ordering. Stability is what
makes two audits comparable at all. And a sample silently reduced by robots or by content
type is a smaller audit reported as a full one.
**Reader:** partial. The spread and the stability are enforced —
`test_picks_are_spread_across_the_whole_list` pins exact indices,
`test_both_ends_of_the_sitemap_are_covered`, `test_the_same_sitemap_yields_the_same_pages`
and `test_the_sample_spans_the_site_rather_than_its_first_corner` pin the rest, the last
through a live sixty-page site. The three drop rules are not: the extension filter is
tested through `test_assets_are_not_pages`, and the content-type rejection, the
robots-disallowed count and the message a single-URL run prints have no reader at all.

#### Scenario: the sample is taken from the top
- **WHEN** the first N URLs of a sitemap are sampled
- **THEN** the sample measures the sitemap's ordering rather than the site
- **AND** the picks must span the list, both ends included, so no sample size leaves
  the tail of a large sitemap unreachable

#### Scenario: two runs over an unchanged site
- **WHEN** the same sitemap is sampled twice
- **THEN** the same pages are picked, because two audits that sample differently are
  not comparable

#### Scenario: robots disallows some of the picks
- **WHEN** URLs the sample chose are disallowed by the site's own robots.txt
- **THEN** they are dropped and the count of drops is printed
- **AND** a sample silently reduced is a smaller audit reported as a full one

#### Scenario: something that is not a page
- **WHEN** a candidate is an asset by extension, or answers with a non-page content
  type
- **THEN** it is not sampled, and the extension filter alone does not settle the
  second case

### Requirement: RUN-18 — the shared crawl is an input, never a job, and its failure is `NO_DATA`

The site SHALL be crawled once, before the plan, and its inventory handed to items as an
input. The crawl MUST NOT be named as any registry item's script. When the crawl fails,
every item that would have read the inventory SHALL be `NO_DATA` carrying the crawl's own
reason.

**Why:** the crawl is the most expensive thing a run does and several items need it; making
it a job would either run it many times or make one item's failure another's. And the
status matters: a crawl that failed is the tool's problem, not the operator's — there is no
flag that supplies an inventory, because the run produces it.
**Reader:** enforced. `TheStatusNamesWhoCanAct` holds all three clauses.

The failure status is held in both of its forms — a crawl that ran and was rejected, and an
inventory that was never produced — with the asymmetry beside them, so a blanket `NO_DATA`
that emptied the operator's to-do list reddens too. The status is derived from
`HOW_TO_SUPPLY` rather than from a list naming the crawl, and
`test_the_two_keys_a_run_makes_itself_are_the_ones_outside_the_table` derives that table's
own composition from the registry's templates, which is what a hand list cannot do; writing
it found two suppliable keys the table had never held.

"Never a job" had only an accidental reader until 0.95.0 — naming `site_crawl.py` as an
item's script reddened the registry generator and the census snapshot, because the crawl is
absent from the scripts those readers expect, which would stop holding the moment somebody
added it to that list. `test_the_crawl_is_an_input_and_not_a_job` asserts the clause itself.

"Once, before the plan" is a claim about what did not happen, and the suite counts no
requests here. `test_the_crawl_runs_once_and_before_the_plan` holds the shape that makes
twice impossible instead: one call site in the runner, ahead of every `build_plan` call —
the run builds two plans, the second per sampled page. Probed by inserting a second crawl
and by building a plan ahead of it.

#### Scenario: the crawl fails
- **WHEN** the shared crawl returns an error
- **THEN** every item that would have read the inventory is `NO_DATA`, carrying the
  crawl's own reason
- **AND** it is not `NEEDS_INPUT`: there is no flag that supplies an inventory the run
  produces itself, so that status asks the operator for something only the tool can
  give

#### Scenario: the crawl as a registry item
- **WHEN** a registry item names the crawl as its script
- **THEN** the crawl either runs once per item that wants it or makes one item's
  failure another's
- **AND** a reader that only knows the crawl is absent from a list of expected scripts
  stops holding the moment somebody adds it to that list

#### Scenario: two items read the inventory
- **WHEN** several site-wide items need the crawl's inventory
- **THEN** the site is crawled once, before the plan, and the inventory is handed to
  each as an input

### Requirement: RUN-19 — a clean answer over a truncated input is withheld

Where a checker's input was capped — a crawl that stopped at its page limit, a listing that
was cut — an answer that would pass *by absence* SHALL be downgraded to `NO_DATA`, and a
failure found in the part that was read MUST still fail, named as a floor.

**Why:** "no violations found" over half a site is not a finding about the site. But a
violation found in half a site is still a violation, so the downgrade must be asymmetric or
it destroys real findings.
**Reader:** partial, and the untested half is the join. The rule itself is covered
thoroughly and in both directions: `test_a_clean_answer_over_a_capped_input_is_withheld`
sweeps every registry item that passes by absence,
`test_a_defect_found_in_the_part_that_was_read_still_fails` and
`test_a_failing_count_over_a_capped_input_is_named_as_a_floor` pin the asymmetry, and
`test_every_reporter_can_actually_set_the_flag` derives the reporters from the scripts
themselves. Every one of those injects the flag by hand. No test starts from a crawl that
truncated and follows the flag through to a verdict, so the propagation the requirement
names — from the crawl to the rule — is unread.

#### Scenario: nothing found in the half that was read
- **WHEN** a rule that passes by absence answers over an input the checker says was
  capped
- **THEN** the answer is withheld as `NO_DATA`, because the cap that stopped the
  reading is the cap that would have stopped the finding

#### Scenario: a defect found in the part that was read
- **WHEN** the same capped input yields a violation
- **THEN** the verdict stands, and the count beside it is named as a floor rather than
  a total
- **AND** a symmetric downgrade would lose a true finding to a cap

#### Scenario: the truncation comes from the crawl rather than from a fixture
- **WHEN** a crawl stops at its page limit and a site-wide item then passes by absence
- **THEN** the withholding still happens, because the requirement is about the
  propagation and not only about the flag
- **AND** a case that sets the flag by hand reads the rule and never the path to it

#### Scenario: an answer that passes by presence
- **WHEN** a rule that requires something finds it, over a capped input
- **THEN** it is not downgraded: the cap cannot have hidden what was found

### Requirement: RUN-20 — when two refusals apply to one item, the order is stated

An item can be refused twice over: excluded by a profile *and* gated by an unreadable
entry; out of scope for the mode *and* missing its input; carrying an artifact that was
rejected *and* a template key that is absent. Exactly one of those reasons reaches the
report, and which one is a decision this document makes rather than an accident of the
order the code happens to check them in.

The order SHALL be: **scope before capability, capability before input.** An item a profile
excluded is `N/A` even if its input is also missing, because it was never going to be
asked. An item the mode cannot carry is `N/A` even if a credential is also absent, because
supplying the credential would not help. Only an item that is in scope and answerable MAY
report `NEEDS_INPUT`.

**Why:** the status names who can act, and the wrong one sends a reader to work that
changes nothing. Today the precedence exists — it is whatever sequence of `if` statements
the run performs — and it is nowhere stated, so nobody can tell an intended order from an
emergent one, and any reordering of the code silently reclassifies items.
**Reader:** enforced. Four tests, one per pair and one floor:
`test_scope_beats_capability` — both answer `N/A`, so the reason is the discriminator and a
profile exclusion may not be reported as a mode gap; `test_scope_beats_a_missing_input` and
`test_capability_beats_a_missing_input` — an item nobody was going to ask, and an item no
credential would help, are `N/A` rather than a to-do nobody can do; and
`test_an_item_that_is_in_scope_and_answerable_is_the_only_one_asked_for_input`, without
which all three would pass on an implementation that answered `N/A` to everything.

Probed by making the profile skip stop short-circuiting, so scope is applied last instead
of first: an excluded item comes back `NEEDS_INPUT`, and a profile exclusion is relabelled
"needs 'crawl'; not available in archive mode". That is the silent reclassification the
requirement was written about, and it now costs two red tests.

#### Scenario: excluded by a profile and gated by the mode
- **WHEN** a profile excludes an item whose capability the mode also does not carry
- **THEN** the reported reason is the profile's, because both answer `N/A` and the
  reason is the only discriminator
- **AND** relabelling a profile exclusion as a mode gap tells the operator to change
  something that was never going to be asked

#### Scenario: excluded by a profile and missing its input
- **WHEN** a profile excludes an item whose template key is also absent
- **THEN** it is `N/A` with the profile's reason, not `NEEDS_INPUT`

#### Scenario: out of scope for the mode and missing a credential
- **WHEN** the mode cannot carry an item's capability and its credential is absent too
- **THEN** it is `N/A`, because supplying the credential would not help

#### Scenario: in scope and answerable
- **WHEN** an item is neither excluded nor gated, and one input is missing
- **THEN** it is the only case that reports `NEEDS_INPUT`
- **AND** without this case, an implementation answering `N/A` to everything satisfies
  the other three

## 4. Invariants

* **INV-L1** — every registry item ends a run with exactly one status, whether it was
  planned, skipped, gated or excluded. *Reader: enforced, by a reader this document first
  credited to the wrong test.* Dropping an item from grading was probed: the partition test
  stayed green and the **fixture oracle** errored, because a declared id it indexes had no
  row. The invariant is held, by an instrument built for something else.
* **INV-L2** — no item is both planned and skipped. *Reader: partial* — allowing preskipped
  items into the plan reddens both the profile test and the unreachable-plan test, so the
  rule is held for the two paths that produce skips; no assertion states the intersection
  is empty in general.
* **INV-L3** — the entry page is fetched exactly once, and the guard, the redirect target
  and the profile detection are all decided from that one fetch. *Reader: partial.* A
  duplicated `fetch_page()` call leaves every named unit test green, but CI's live path
  counts the fixture server's requests and asserts exactly one entry `GET` — so the
  *arithmetic* half is read, in CI rather than in the suite. The *sharing* half is unread:
  nothing asserts that the guard, the redirect target and the detection are decided from
  one returned object rather than from three.
* **INV-L4** — every child process is started without forking and with a decoded stdout.
  *Reader: partial, and the fork half is thinner than it reads.* The AST walk asserts that
  every spawn in the tree **names** `close_fds`, never what it is set to: changing
  `close_fds=False` to `close_fds=True` throughout leaves every named process test green.
  The `cwd=` and bare-binary rules are genuinely enforced, and the decoded-stdout half is
  pinned separately by the mocked `None` becoming `bad_output`.

## 5. What this document does not decide

* what each checker emits and what its thresholds rest on — `openspec/specs/evidence/`;
* how the fetched bytes are obtained, cached and paced — `openspec/specs/http/`;
* what an operator-supplied artifact must contain and how stale it may be —
  `openspec/specs/inputs/`;
* how a graded run becomes a score, a partition and a fix order — `openspec/specs/scoring/`;
* what the report shows and in what order — `openspec/specs/reporting/`;
* whether `DEFAULT_MAX_PAGES = 100` and `DEFAULT_DEPTH = 3` are the right numbers. This
  document requires the cap to be visible in the verdicts it changes (RUN-19); what the cap
  should be is a decision about the price of a run.

## 6. Open questions

**Should the mode table be derived from the registry, or the registry checked against the
table?** *Settled 5 September 2026 in the direction this question argued for — RUN-1's
reader takes the weaker of the two options and says why. Kept because the reasoning is
what justifies the choice.* RUN-1 had no reader, and the two candidate readers are
different documents'
work: a test that `MODE_CAPS`'s union equals the `requires` vocabulary would tie this
document to `openspec/specs/registry/` §2.1, while a test that every `requires` value appears in
some mode would allow a capability no mode carries. What would settle it: whether a
capability that no mode can satisfy is ever legitimate — `gsc` and `safe_browsing` are
exactly that today, gated a second time, which suggests the answer is yes and the test
must be the weaker one.

**Is the entry fetch one request, one attempt, or one returned object?** INV-L3 says the
guard, the redirect target and the detection all come from one fetch, which is what makes
detection free. A redirect is more than one request; a cache hit is fewer; `--sample`
fetches more pages afterwards. The invariant is really "no *extra* request for detection",
which is not what it says. And the counting half is already settled by an instrument this
document did not know it had: CI asserts exactly one entry `GET` against the fixture
server. What is not settled is the sharing half — that one returned object feeds all three
decisions, rather than three lookups that happen to cost one request because the cache is
warm. What would settle it: deciding whether the invariant is about requests or about the
object, and pointing the existing counter at whichever it is.

**Are the guard's fingerprint sets a vocabulary or an implementation detail?** Five sets
decide whether a run ends (A.3): fifty-five entries between them, none named by a test,
about a third exercised by a fixture. Treating them as a vocabulary — enumerated here,
changed by argument — is what this suite does for every other closed set, and it is
plainly too heavy for a list that grows whenever a vendor ships a new interstitial.
Treating them as an implementation detail leaves the two thresholds and fifty-five strings
deciding whether a site gets audited at all, read by nobody. What would settle it: whether
an entry has ever been *removed* — an append-only list needs a weaker rule than one that
can silently lose a vendor.

**What counts as the same host?** RUN-12 turns on "same host", and the tree decides it by
comparing netlocs. That makes `example.com:443` and `example.com` different hosts, and a
change of case or an IDN spelling likewise. Whether a redirect that only normalises the
spelling should move the audit is undecided, and the answer changes which URL a report is
about.

**What should a run do when the crawl truncates rather than fails?** RUN-18 covers failure
and RUN-19 covers a truncated *input*, but the case where the crawl reaches its page limit
on a large site is neither: the inventory is real, complete for what it covers, and silent
about the rest. Today it sets the flag and RUN-19's downgrade applies. Whether that is
right for a site of ten thousand pages, where every audit is truncated and every
absence-based item is therefore `NO_DATA` forever, is undecided.

## Appendix A — measured disagreements, 29 August 2026

Observation, not specification. Measured at commit `9f8bb6c`, registry `b0abf2819da0`.

#### A.1 — a failed crawl reports the wrong status, and three places say so

**Fixed at 0.95.0**, in both directions at once — see A.7. The measurement is kept because
the shape it names is the point, and because the fix was not the one this entry implies.

When `site_crawl.py` returns an error, the runner sets a rejection reason for
`{inventory_json}`, and `build_plan`'s rejection branch assigns
`skipped[item] = (NEEDS_INPUT, reason)`. Every site-wide item therefore ends the run as
`NEEDS_INPUT`.

Three statements in the tree say it is `NO_DATA`:

| where | what it says |
|---|---|
| the comment above the branch | "NO_DATA with this reason for every site-wide item" |
| the message printed to the operator | "the site-wide checks report NO_DATA" |
| `local/sdd/inventory/CAPABILITIES.md`, C18 | "Failure → every site-wide item `NO_DATA`" |

This is a VRD-5 violation, and it is the mirror of the one `openspec/specs/verdicts/` already
records. That document's Appendix A names VRD-5 broken in one direction — missing Search
Console credentials, which are genuinely `NEEDS_INPUT`, reported as `NO_DATA`. This is the
other direction: a crawl that ran and failed, which is genuinely `NO_DATA`, reported as
`NEEDS_INPUT`. The two statuses are swapped in the two places a run decides them.

An earlier draft added that each error was invisible from the other document. That is not
true and worth correcting rather than deleting: `openspec/specs/verdicts/` states the general
boundary that both violate, so this defect was in scope for it and was simply not found.
What the two cases show is narrower and still worth having — a rule stated once in the
document that owns a vocabulary is not a sweep of the places that vocabulary is used, and
the sweep is what finds the second instance.

The operator consequence is the sharper half. `NEEDS_INPUT` means "a named input was
absent" and sends its reader to supply one. There is no flag that supplies an inventory:
the run produces it. So the report asks the operator for something only the tool can give,
which is exactly the confusion VRD-5 exists to prevent.

#### A.2 — the interstitial threshold is pinned only against another threshold

`CHALLENGE_MAX_WORDS` is 120 and `THIN_ENTRY_WORDS` is 40. One test asserts the second is
less than the first. No test asserts either value. Every other test that exercises the
guard writes `120` as a literal of its own, so the constant and the tests that depend on it
could disagree, and moving both constants together — preserving the inequality — reddens
nothing at all.

The rule this constant decides is RUN-9's conjunction, which ends runs. A threshold that
can move without a reader is the shape `openspec/specs/scoring/` calls G1 for the severity weights,
one layer down.

#### A.3 — the guard's fingerprint sets are large and thinly exercised

| set | entries | entries with a fixture |
|---|---:|---:|
| `CHALLENGE_MARKUP_MARKERS` | 11 | 7 |
| `CHALLENGE_TEXT_MARKERS` | 3 | 2 |
| `CHALLENGE_TITLES` | 13 | 2 |
| `NOT_FOUND_PHRASES` | 24 | ~5 |
| `NOT_FOUND_EXACT` | 4 | 2 |

None of the five constants is named by any test; each is exercised only through fixtures
that happen to contain some of its entries. An entry deleted from any of them reddens
nothing unless it is one of the sixteen with a fixture.

The capability inventory records `CHALLENGE_MARKUP_MARKERS` as having seven entries. It
has eleven. That is the REG-12 shape again — a count written beside the thing it counts,
read by nobody — and it is the second inventory number this document found wrong while
being written.

#### A.4 — four of the five failure kinds are never graded

`FAILURE_LABEL` names `timeout`, `crash`, `missing`, `bad_output` and `signal`. Each is
asserted to *carry its label*. Only `timeout` is asserted to *become `NO_DATA`*. A change
routing `crash` to `PASS` — or to `WARN` — would pass the suite.

The per-kind tally RUN-7 requires has no reader in either form: the one assertion on the
failure dictionary asserts that it is empty, which is a statement about the fixtures.

#### A.5 — the profile prompt narrows the audit on every silent exit

**Fixed at 0.95.1.** The three exits resolve to `default` and say so, naming the two flags
that narrow deliberately. The measurement is kept because the reason four tests missed it
is the point.

`choose_profile` ends its prompt loop three ways that are not answers — end of input, an
interrupt, and three unrecognised replies — and all three `return suggested`. `suggested`
is the detected profile whenever detection found one, so:

| what the operator does | detection found | audit runs under |
|---|---|---|
| presses Ctrl-D | nothing | `default` — correct |
| presses Ctrl-D | `local` | **`local`** |
| presses Ctrl-C | `local` | **`local`** |
| types three unrecognised answers | `local` | **`local`** |

RUN-14 forbids all three of the shaded rows: a non-answer must resolve to the widest
scope. The consequence is the quiet direction — fewer items, a higher score, and a report
that names a profile nobody chose.

The four tests that cover this call the prompt with no detection argument, which makes
`suggested` equal `"default"` and the two branches identical. They are not wrong; they
construct the only case in which the defect cannot appear. Measured by calling the
function directly with a detection dict, after a first probe that proved nothing because
it ran without a terminal and never reached the prompt at all.

`openspec/specs/verdicts/` Appendix A already lists this among the shipped violations of VRD-11.
This document credited it as `enforced` until an audit ran the probe, which is the same
error the suite has now made four times: a classification taken from tests that pass
rather than from a mutation that should fail.

#### A.7 — what fixing A.1 turned out to be, 6 September 2026

A.1 reads as a one-line fix: route the crawl's rejection to `NO_DATA`. Doing that would
have been a list of one key, and a list of one key reads nothing about the second.

The status now follows `HOW_TO_SUPPLY`, the table that already recorded which ctx keys an
operator can fill — its own comment names `html` and `inventory_json` as the two a run
produces for itself. Deriving the rule from that table rather than from the branch an
absence arrived through cost nothing and read three more things:

* **an offline item under a dead entry.** `test_offline_checks_fall_out_on_their_missing_input`
  pinned `NEEDS_INPUT` there, with a docstring from 0.16.0 arguing for it. The argument's
  evidence half still holds and is unchanged; its status half does not. 0.16.0 split
  `NEEDS_INPUT` out of `NO_DATA` so one section could mean *waiting on you*, and an item
  that lost its HTML to a 503 is nobody's unfinished business. It also meant one dead entry
  produced two statuses in one run — the fetch items `NO_DATA`, the offline ones
  `NEEDS_INPUT` — which is VRD-5's third scenario verbatim, unnoticed because each side had
  a test and neither could see the other. `test_the_dead_entry_gives_every_item_one_status`
  now asserts the pair;
* **two keys the supply table never held.** `indexnow_key` and `gsc_property` are named by
  registry templates and set by one environment variable and one flag. Neither had an
  entry, so each printed the bare `missing input '...'` that the table's own comment calls
  accurate and nearly useless — and, once the status follows the table, each would have
  begun telling an operator they could not supply it. Found by comparing the table against
  the registry's templates, not by reading it;
* **the other direction of the same swap.** `openspec/specs/verdicts/` A.1 recorded a
  `source: gsc` item graded `NO_DATA` while carrying the sentence of a missing input, and
  the planner calling the identical absence `NEEDS_INPUT` a few hundred lines away. That is
  this defect mirrored, and it was in the same release for the same reason: both are the
  question *who can act on this*, answered twice by one run.

The general lesson is the one A.1 already half-states. A status is a claim about the reader,
so the rule that assigns it belongs beside the record of what readers can do — and where
that record is a set, the set's composition needs a reader of its own.

#### A.8 — the detector's own claim about itself was false, 7 September 2026

RUN-15 says the signals behind a suggestion must be shown, and `detect_profile.py`'s
docstring makes a second claim beside it: signals are structural "because wording is the
first thing that lies". Nothing read either. The first was merely unread. The second was
wrong.

`PLATFORM_SIGNALS` and `MARKUP_SIGNALS` were matched with `re.search(pattern, lower)` where
`lower` was the whole document lowercased — prose included. Measured before the fix:

| page | detected |
|---|---|
| an article titled *Why we left WooCommerce*, mentioning WooCommerce and Magento in running text, whose only link is `/about` | `ecommerce`, **high** confidence, signals `['WooCommerce', 'Magento']` |
| a page whose visible text reads "our opening hours" and whose markup says nothing | `local` +3 |

`PATH_SIGNALS` was never affected: it is matched against the joined `href` values, which is
structure. The docstring's own example — "a plumber's site says *shop* in the nav" —
described a case the code deliberately treats as a real signal, so that sentence was the
one to correct rather than the behaviour.

The patterns are matched against `structure()` now: every opening tag rebuilt from its name
and attributes, plus the contents of `script` and `style`, because a theme announces itself
in inline JS and code is not wording either. The harm was bounded — detection only
suggests, and VRD-11 requires consent before it narrows — which is exactly why it survived:
a wrong suggestion accepted by an operator pressing Enter produces a narrowed audit that
looks like a decision somebody made.

Worth naming beside `test_image_paths_do_not_fingerprint_magento`, which fixed a
false-positive fingerprint by narrowing the *pattern*. This is the same class one level up:
the patterns were right and the haystack was wrong.

#### A.6 — the survey that produced this appendix

Appendices A.1 through A.4 came from a reader census over C9–C18 that named, for each
behaviour the inventory says a spec must state, the tests that assert it and the greps that
establish an absence. It reported forty behaviours with no reader. This document does not
publish all forty: a list of that size is read as a mood rather than a defect list, and
each entry needs the mutation probe none of them has had. The four above are the ones
verified by hand against the tree — the crawl status by reading the branch it routes
through, the constants by importing them and counting, the failure kinds by reading the
assertions.

The other thirty-six are recorded where a debt of that shape belongs, in the reader lines
of the requirements section: every `partial` and every `none` in Appendix B names which
half is unheld.

## Appendix B — how much of this document is enforced

Every line below was measured by mutation — break the thing, run the readers, record what
reddened. The first draft of this appendix was written from the tests instead, and an
independent audit moved four rows: RUN-14 from `enforced` (it is violated today, A.5),
RUN-18 from `none` (one clause has an accidental reader), INV-L4 from `enforced` (the AST
walk reads a keyword's presence, not its value) and INV-L3 from `none` (CI counts
requests, even though the suite does not).

| | requirements |
|---|---|
| **enforced** | RUN-1, RUN-2, RUN-3, RUN-4, RUN-5, RUN-9, RUN-10, RUN-11, RUN-12, RUN-13, RUN-14, RUN-15, RUN-16, RUN-18, RUN-20 |
| **partial** | RUN-6, RUN-7, RUN-8, RUN-17, RUN-19 |
| **none** | — none |
| **opposed** | — none |

Invariants: INV-L1 enforced; INV-L2, INV-L3 and INV-L4 partial.

**Fifteen enforced, five partial, nothing unread, of twenty.**

RUN-13, RUN-14 and RUN-15 moved at 0.95.1 — the whole profile layer in one release,
because they are one subject: a profile is a decision, and an operator has to be able to
see what it rests on and what it cost. Two of the three were violated in the shipped tree,
and the second violation was found by writing the test the third one asked for. A.5 and A.8
record both.

RUN-2, RUN-5 and RUN-18 moved at 0.95.0. Both were held for one key and read nothing about the
rest of a set; both were closed by deriving the set instead of listing it, and both found a
second defect while being closed. RUN-2 was the same shape one layer along and cost one
sweep: its two credential capabilities were read and the general sentence behind them was
not. A.7 records what that cost and what it caught. RUN-18
keeps a clause with only an accidental reader, which is why its line says enforced *for the
status* rather than plainly — the qualification `openspec/specs/reporting/`'s convention
requires whenever the word is not the whole truth.

The shape is different from the documents before it. `verdicts/` and `registry/` are unread
where they make *claims about meaning*; this document is unread where it makes claims about
**what did not happen**. RUN-3 (no request was made), RUN-4 (the script ran once, not
twice), RUN-20 (the other refusal did not win), and half of INV-L3 (there was no second
fetch) are all negatives, and a negative needs an instrument that counts rather than an
assertion that reads a value.

An earlier draft added that the suite has no such instrument. It does, and the correction
is more interesting than the claim: the fixture harness counts requests, and CI asserts a
request fan-out ceiling and exactly one entry `GET` — with a comment saying a number in a
green build is a number nobody reads. So the instrument exists, in the live path, and not
one requirement in this document is wired to it. The gap is not capability; it is that
counting was built to watch a total and never pointed at a rule.

That is also why the unread requirements are the ones with the quietest failures. An audit
that made a network call in archive mode, ran a script twice, or reported the wrong one of
two applicable refusals produces a report indistinguishable from a correct one — same
items, same statuses, same score. The enforced requirements are, with few exceptions,
the ones whose violation changes a verdict somebody reads — and where that stopped being
true is where the readers were written this week rather than earned by a defect.
