# Run lifecycle — what a run may attempt, what it must refuse, and what it owes when it refuses

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
[`specs/verdicts/`](../verdicts/spec.md); what an item is and what `requires` may say
belong to [`specs/registry/`](../registry/spec.md); how a graded item becomes a number
belongs to [`specs/scoring/`](../scoring/spec.md). This document says what a run *does*,
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

## 3. Requirements

### RUN-1 — a mode is a set of capabilities, and the table is the contract

The three modes and their capability sets are normative. An item runs when its `requires`
is in the running mode's set, and does not when it is not. A new mode, or a change to a
set, is a change to this document first.

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

### RUN-2 — an unsatisfiable requirement is `N/A`; an absent credential is `NEEDS_INPUT`

Two different refusals, and they must not be spelled alike. An item whose `requires` the
mode does not carry is **out of scope**: `N/A`, naming the mode. An item whose capability
the mode carries but whose credential is absent is **unanswered**: `NEEDS_INPUT`, naming
the flag or environment variable that would supply it.

**Why:** the two name different people. Out of scope is the operator's own choice of mode
and needs no action; a missing credential is an action somebody can take, and the report
is where they find out which. Collapsing them either hides work that could be done or
invents work that cannot.
**Reader:** enforced for the two capabilities that have credentials, unread for the rest —
which is `partial`. `test_missing_credentials_is_undecided_not_out_of_scope`,
`test_a_mode_without_network_puts_it_out_of_scope`,
`test_missing_key_in_a_network_mode_needs_input` and
`test_archive_mode_makes_the_api_check_not_applicable` pin both branches for `gsc` and
`safe_browsing`. The general sentence — an item requiring `crawl` in `page` mode — has no
test: nothing feeds an ordinary capability into a mode that lacks it and asserts the
`N/A`.

### RUN-3 — archive mode makes no network call, whatever credentials are present

`archive` carries only `offline`. A credential on disk does not re-enable a capability the
mode excludes, and the run makes zero requests.

**Why:** archive mode is what an operator uses when they must not touch the site — a
client's production host, a system under embargo, a machine with no route. A mode that
quietly makes one API call because a key happened to be present breaks a promise the
operator relied on, and nothing in the report would show it.
**Reader:** **none**, and one test's name suggests otherwise.
`test_archive_mode_claims_nothing_about_a_network_it_never_touched` is a sound test of
something else: it asserts `allow_private` is recorded, that the flag is not echoed to
stdout, and that provenance warnings are empty. It places no credential and asserts no
absence of requests. Its docstring is honest about this; its name is not, and a census
taken from names would credit it with the guarantee.

### RUN-4 — a plan entry is one script with one argument list, and identical invocations fold

Two items that resolve to the same script with the same arguments produce one execution.
The fold is by the invocation, never by the item.

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

### RUN-5 — a missing input names its flag; a refused input says why it was refused

An item whose template names an input the run does not have is `NEEDS_INPUT`, and the
evidence names the flag that would supply it. An input that was supplied and *rejected* —
stale, or describing a different site — carries the reason for the rejection instead, and
the two sentences must not be interchangeable.

**Why:** "you did not give me this" and "what you gave me was not about this site" send
the operator to different actions, and the second is the one people get wrong twice.
**Reader:** partial. `test_a_refused_input_says_something_other_than_missing` pins the
distinction directly — a refused artifact's reason contains its rejection and not the
words "missing input", and the same item with an empty context says "missing input"; and
`test_an_artifact_from_the_other_site_is_refused_with_the_reason` pins it end to end. The
flag-naming half is read through one of the six entries in the supply table: only
`--keyword` is asserted, by
`test_no_keyword_input_stops_the_item_at_the_plan`. The four template keys for Search
Console, link exports and server logs appear in the suite only as fixture input, never as
an assertion about what the plan does with them.

### RUN-6 — every argument a run adds is visible where the verdict is read

A run appends three kinds of argument a reader of the registry cannot predict: registry
args, opt-in flags, and a profile's `script_args`. All three land in the recorded
invocation, and a threshold a profile moved is visible beside the verdict it moved.

**Why:** a profile that changes a threshold changes what `PASS` means. A report that shows
the verdict and not the threshold is unfalsifiable from the outside — the number is right
for a rule the reader cannot see.
**Reader:** partial, and the visible half is not the one that matters most.
`test_profile_args_reach_the_plan_as_argv` pins the arguments into the invocation, and
`test_the_moved_threshold_is_in_the_evidence_trail` pins the moved threshold into the
answering script's own summary. Nothing asserts that the run's recorded `profile_args`
reach the artifact, and nothing threads opt-in flags through the plan at all — they are
tested where they are generated and not where they are used.

### RUN-7 — a failed script is `NO_DATA` with a kind, and the kinds are counted apart

Five failure kinds, all `NO_DATA`, none interchangeable. The kind is recorded per item and
the counts are reported per kind.

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

### RUN-8 — nothing runs against an entry the audit could not read, and the absence of a score is the output

When the entry page cannot be read, every item that needs the live site is `NO_DATA` and
no script is executed against it. The run still produces a report; that report has no
score, and says why.

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

### RUN-9 — a wrong page is decided by conjunction, never by one signal

An interstitial is a page carrying a challenge fingerprint **and** under the visible-word
threshold. Either alone is not enough: a long page quoting a vendor's name is an article
about bot protection, and a short page with no fingerprint is a short page.

**Why:** this rule guards the whole audit — a page wrongly called an interstitial ends the
run. Both single-signal versions were tried and both were wrong in production: the
fingerprint alone refuses articles about Cloudflare, and the word count alone refuses
every thin page on the web.
**Reader:** enforced. Three tests pin the three corners:
`test_a_short_article_quoting_a_vendor_string_is_not_a_challenge` (short, marker in prose,
not a challenge), `test_a_content_page_with_the_marker_in_its_markup_survives` (long,
marker in markup, not a challenge) and
`test_script_bulk_does_not_make_a_challenge_look_content_rich` (short, marker, challenge).

### RUN-10 — a soft 404 is decided by title equality, never by containment

A title *segment* equal to a not-found phrase is a soft 404. A title that merely contains
one is not.

**Why:** containment refuses every article whose subject is error pages, and the
containment version shipped. The rule is narrow on purpose and the narrowness is the
requirement.
**Reader:** enforced. `test_an_article_about_404s_is_not_a_soft_404` pins four titles
containing the phrases as substrings and requires all four to pass, and
`test_soft_404_does_not_depend_on_page_size` pins that a matching title decides regardless
of length.

### RUN-11 — the guard records its verdict whether or not it acted

The guard's finding is recorded on every run, including when it is overridden. An
overridden guard makes the run's provenance say so wherever the score is shown.

**Why:** a score computed over an interstitial is not wrong so much as about a different
page, and the only defence is that the report says which page. An override that erases the
suspicion rather than recording it makes the two runs indistinguishable afterwards.
**Reader:** enforced. `test_no_page_guard_records_the_suspicion_instead_of_erasing_it`
pins the recording, `test_the_override_scores_it_and_says_so_everywhere` pins it through a
live run into the output, `test_a_scored_interstitial_says_so` pins it into both renderers,
and `test_an_enforced_guard_is_not_a_caveat` pins the converse — a guard that acted is not
also a warning.

### RUN-12 — a cross-host redirect moves the audit; a same-host hop does not

When the entry redirects to another host, that host is the audited site: the URL sample
and the derived Search Console property follow it. A redirect within the same host leaves
the requested URL as the subject, so the hop is still reported as a finding.

**Why:** auditing `example.com` and reporting about `www.example.net` under the first
name is a wrong report, not a wrong verdict. But adopting every same-host hop would hide
the redirect itself, which is one of the things being checked.
**Reader:** enforced. `test_another_host_wins`,
`test_a_same_host_hop_keeps_the_requested_url` and `test_www_counts_as_another_host` pin
the rule; `test_the_search_console_property_follows_the_destination` pins the derived
property; and `test_the_sample_follows_the_destination_host` pins the sample, through a
live redirect.

### RUN-13 — a profile narrows scope to `N/A` naming the profile, never to silence

An item a profile excludes is reported, as `N/A`, with the profile's own words for why.
It is never simply absent, and the reason is never a generic phrase.

**Why:** a partition that drops rows stops summing to the registry, and the score becomes
a fraction of a sample nobody chose. Naming the profile is what lets a reader tell "this
does not apply to your kind of site" from "the tool did not look".
**Reader:** partial. `test_an_excluded_item_carries_the_profiles_words_not_a_shrug` pins
that the reason is the profile's own sentence rather than a shrug, and
`test_no_profile_excludes_a_critical_item` pins the floor. The status half is unread: the
construction that names the profile beside the `N/A` has no test — the one test that
asserts an excluded item never reaches the plan supplies its own hand-written reason
rather than one produced by the profile.

### RUN-14 — every non-answer resolves to the widest scope

Silence, an unreadable answer, no terminal, end of input, an interrupt: all of them mean
the full registry. A narrower scope is only ever chosen deliberately.

**Why:** the failure modes of a prompt are all silence, and silence must not be able to
shrink the audit. The dangerous direction is the quiet one — a narrowed scope produces a
higher score over fewer items and looks like good news.
**Reader:** partial, **and the requirement is violated today.** The prompt's three silent
exits — end of input, interrupt, and three unrecognised answers — all `return suggested`,
which is the *detected* profile whenever detection found one. A run whose entry page looks
like a local business, answered by an operator who presses Ctrl-C, audits under `local`
and reports a higher score over fewer items, with nobody having chosen that.

The tests pass, and they pass for a reason worth naming: every one of them calls the
prompt with no detection argument, so `suggested` is `"default"` and the two branches are
indistinguishable. `test_falls_back_to_the_widest_scope_not_the_narrowest`,
`test_eof_is_treated_as_no_answer`, `test_without_a_terminal_it_does_not_ask` and
`test_no_prompt_flag_skips_the_question` are all sound about the case they construct and
silent about the case where the requirement can be broken. What *is* enforced is the
explicit flag (`test_explicit_flag_is_never_second_guessed`), the non-interactive path, and
that `--profile auto` is the only way detection may narrow without asking. Appendix A.5
records the measurement, and `specs/verdicts/` already recorded the same defect from the
other side as VRD-11.

### RUN-15 — detection suggests, and never decides

A profile detected from the page is a suggestion. It narrows the audit only where the
operator has asked for that in advance, thin evidence resolves to the widest scope, and
the signals behind a suggestion are shown rather than only its conclusion.

**Why:** a heuristic that silently narrows scope is RUN-14's failure with a better excuse.
Showing the signals is what makes the suggestion arguable; a bare answer is a verdict
wearing a suggestion's clothes.
**Reader:** partial. `test_thin_evidence_never_narrows_anything` and
`test_empty_input_is_an_error_not_a_guess` pin the resolution to `default`;
`test_auto_accepts_detection_without_asking` and
`test_detection_does_not_narrow_scope_without_a_terminal` pin the two ways a suggestion may
and may not be adopted. The "shown, not just answered" half is unread — the signals are
read inside one unit test and nothing asserts they reach the operator — and the claim that
detection reads structure rather than wording has no test in either direction.

### RUN-16 — a sampled verdict is the worst page's, and the count is part of the evidence

Where an item is decided over several pages, the reported verdict is the worst of them and
the evidence states how many pages were checked, how many decided, and how many carry the
reported verdict. Site-wide items are not aggregated, and items decided from an operator's
artifact keep the primary page's verdict.

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

### RUN-17 — the sample is spread, stable, and made of pages

A sample of N covers the site rather than its first corner, is the same on two runs over an
unchanged site, and contains pages: assets are dropped by extension, non-page content types
are dropped by their type, and URLs robots disallows are dropped with a count the operator
can see.

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

### RUN-18 — the shared crawl is an input, never a job, and its failure is `NO_DATA`

The site is crawled once, before the plan, and its inventory is handed to items as an
input. No registry item may name the crawl as its script. When the crawl fails, every item
that would have read the inventory is `NO_DATA` carrying the crawl's own reason.

**Why:** the crawl is the most expensive thing a run does and several items need it; making
it a job would either run it many times or make one item's failure another's. And the
status matters: a crawl that failed is the tool's problem, not the operator's — there is no
flag that supplies an inventory, because the run produces it.
**Reader:** partial, and the half that is held is held by accident. Making a registry item
name `site_crawl.py` reddens the registry generator and the census snapshot — not because
anything forbids it, but because the crawl is not among the scripts those readers expect,
so the "never a job" clause has a reader that was built for something else and would stop
holding the moment the crawl were added to a list. Nothing asserts the failure status,
which is how Appendix A.1's defect survived: the run reports `NEEDS_INPUT`, while the
code's own comment, the message it prints and the capability inventory all say `NO_DATA`.
Running the crawl twice reddens nothing.

### RUN-19 — a clean answer over a truncated input is withheld

Where a checker's input was capped — a crawl that stopped at its page limit, a listing that
was cut — an answer that would pass *by absence* is downgraded to `NO_DATA`, and a failure
found in the part that was read still fails, named as a floor.

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

### RUN-20 — when two refusals apply to one item, the order is stated

An item can be refused twice over: excluded by a profile *and* gated by an unreadable
entry; out of scope for the mode *and* missing its input; carrying an artifact that was
rejected *and* a template key that is absent. Exactly one of those reasons reaches the
report, and which one is a decision this document makes rather than an accident of the
order the code happens to check them in.

The order is: **scope before capability, capability before input.** An item a profile
excluded is `N/A` even if its input is also missing, because it was never going to be
asked. An item the mode cannot carry is `N/A` even if a credential is also absent, because
supplying the credential would not help. Only an item that is in scope and answerable
reports `NEEDS_INPUT`.

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

* what each checker emits and what its thresholds rest on — `specs/evidence/`;
* how the fetched bytes are obtained, cached and paced — `specs/http/`;
* what an operator-supplied artifact must contain and how stale it may be —
  `specs/inputs/`;
* how a graded run becomes a score, a partition and a fix order — `specs/scoring/`;
* what the report shows and in what order — `specs/reporting/`;
* whether `DEFAULT_MAX_PAGES = 100` and `DEFAULT_DEPTH = 3` are the right numbers. This
  document requires the cap to be visible in the verdicts it changes (RUN-19); what the cap
  should be is a decision about the price of a run.

## 6. Open questions

**Should the mode table be derived from the registry, or the registry checked against the
table?** RUN-1 has no reader, and the two candidate readers are different documents'
work: a test that `MODE_CAPS`'s union equals the `requires` vocabulary would tie this
document to `specs/registry/` §2.1, while a test that every `requires` value appears in
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

### A.1 — a failed crawl reports the wrong status, and three places say so

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

This is a VRD-5 violation, and it is the mirror of the one `specs/verdicts/` already
records. That document's Appendix A names VRD-5 broken in one direction — missing Search
Console credentials, which are genuinely `NEEDS_INPUT`, reported as `NO_DATA`. This is the
other direction: a crawl that ran and failed, which is genuinely `NO_DATA`, reported as
`NEEDS_INPUT`. The two statuses are swapped in the two places a run decides them.

An earlier draft added that each error was invisible from the other document. That is not
true and worth correcting rather than deleting: `specs/verdicts/` states the general
boundary that both violate, so this defect was in scope for it and was simply not found.
What the two cases show is narrower and still worth having — a rule stated once in the
document that owns a vocabulary is not a sweep of the places that vocabulary is used, and
the sweep is what finds the second instance.

The operator consequence is the sharper half. `NEEDS_INPUT` means "a named input was
absent" and sends its reader to supply one. There is no flag that supplies an inventory:
the run produces it. So the report asks the operator for something only the tool can give,
which is exactly the confusion VRD-5 exists to prevent.

### A.2 — the interstitial threshold is pinned only against another threshold

`CHALLENGE_MAX_WORDS` is 120 and `THIN_ENTRY_WORDS` is 40. One test asserts the second is
less than the first. No test asserts either value. Every other test that exercises the
guard writes `120` as a literal of its own, so the constant and the tests that depend on it
could disagree, and moving both constants together — preserving the inequality — reddens
nothing at all.

The rule this constant decides is RUN-9's conjunction, which ends runs. A threshold that
can move without a reader is the shape `specs/scoring/` calls G1 for the severity weights,
one layer down.

### A.3 — the guard's fingerprint sets are large and thinly exercised

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

### A.4 — four of the five failure kinds are never graded

`FAILURE_LABEL` names `timeout`, `crash`, `missing`, `bad_output` and `signal`. Each is
asserted to *carry its label*. Only `timeout` is asserted to *become `NO_DATA`*. A change
routing `crash` to `PASS` — or to `WARN` — would pass the suite.

The per-kind tally RUN-7 requires has no reader in either form: the one assertion on the
failure dictionary asserts that it is empty, which is a statement about the fixtures.

### A.5 — the profile prompt narrows the audit on every silent exit

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

`specs/verdicts/` Appendix A already lists this among the shipped violations of VRD-11.
This document credited it as `enforced` until an audit ran the probe, which is the same
error the suite has now made four times: a classification taken from tests that pass
rather than from a mutation that should fail.

### A.6 — the survey that produced this appendix

Appendices A.1 through A.4 came from a reader census over C9–C18 that named, for each
behaviour the inventory says a spec must state, the tests that assert it and the greps that
establish an absence. It reported forty behaviours with no reader. This document does not
publish all forty: a list of that size is read as a mood rather than a defect list, and
each entry needs the mutation probe none of them has had. The four above are the ones
verified by hand against the tree — the crawl status by reading the branch it routes
through, the constants by importing them and counting, the failure kinds by reading the
assertions.

The other thirty-six are recorded where a debt of that shape belongs, in the reader lines
of §3: every `partial` and every `none` in Appendix B names which half is unheld.

## Appendix B — how much of this document is enforced

Every line below was measured by mutation — break the thing, run the readers, record what
reddened. The first draft of this appendix was written from the tests instead, and an
independent audit moved four rows: RUN-14 from `enforced` (it is violated today, A.5),
RUN-18 from `none` (one clause has an accidental reader), INV-L4 from `enforced` (the AST
walk reads a keyword's presence, not its value) and INV-L3 from `none` (CI counts
requests, even though the suite does not).

| | requirements |
|---|---|
| **enforced** | RUN-1, RUN-4, RUN-9, RUN-10, RUN-11, RUN-12, RUN-16, RUN-20 |
| **partial** | RUN-2, RUN-5, RUN-6, RUN-7, RUN-8, RUN-13, RUN-14, RUN-15, RUN-17, RUN-18, RUN-19 |
| **none** | RUN-3 |
| **opposed** | — none |

Invariants: INV-L1 enforced; INV-L2, INV-L3 and INV-L4 partial.

**Eight enforced, eleven partial, one unread, of twenty.**

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
items, same statuses, same score. The five enforced requirements are all ones whose
violation changes a verdict somebody reads.
