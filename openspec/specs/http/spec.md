# HTTP — what the audit is allowed to ask the network, and what it must not

## Purpose

The acquisition substrate every checker sits on — the SSRF guard and the
private-address allowance, pacing and robots, the response cache, the fetch contract,
and the choice of HTML parser (C19–C23 of the capability inventory). It exists because
an audit owes two things at once to two different parties: the site being audited is
owed politeness, and the machine running the audit is owed a guard against a URL that
came from outside it. Every checker that opens a connection reaches the network through
this one layer, which is what makes a rule stated here stated once — and a hole opened
here open in all of them.

**Capability:** the acquisition substrate every checker sits on — the SSRF guard and the
private-address allowance, pacing and robots, the response cache, the fetch contract, and
the choice of HTML parser (C19–C23 of the capability inventory).

This document is normative and is written as though no code existed. Where the
implementation disagrees, the implementation is presumed wrong until this document is
changed by argument. Appendix A records disagreements measured on 29 August 2026.

Every requirement carries a **Reader** line naming what makes it fail when violated;
Appendix B is the census of those lines. A requirement whose reader is `none` is an
intention, and is counted as one.

**Inherited, not restated:** the eight statuses belong to
[`openspec/specs/verdicts/`](../verdicts/spec.md); when a run may reach the network at all, and what
a gated item reports, belong to [`openspec/specs/run-lifecycle/`](../run-lifecycle/spec.md). This
document says what happens once a request is permitted, and what the audit owes the site it
is asking.

---

## 1. Two obligations, not one

Everything here answers to two parties at once, and they pull in opposite directions.

The **operator's site** is owed politeness. An audit is an unrequested crawl of somebody's
production server: it must pace itself, obey the parts of `robots.txt` that apply to it,
identify itself by a token that can be blocked, and never cost more requests than the
answers need.

The **operator's network** is owed a guard. A tool that fetches a URL a user supplies is a
server-side request forgery engine unless something stops it: the audit runs on a machine
with a route to a cloud metadata service, a Kubernetes API, an internal admin panel. The
URL comes from outside; the credentials are the machine's own.

The two obligations produce the substrate's two hardest rules, and both are asymmetric in a
way that reads as a bug until the reason is stated. `robots.txt` governs URLs the audit
*discovered* and not the URL the operator handed in — because refusing to audit the site
you were asked to audit is not politeness, it is a broken tool, while crawling a site's
private areas because you happened to find a link is exactly what robots is for. And the
private-address allowance is per-run and global rather than per-request, because
fifty-five separate scripts each guard themselves and there is no other way to tell them
all at once.

Both asymmetries fail silently when reversed. That is the argument for writing them down.

## 2. What the substrate is

| layer | what it decides |
|---|---|
| guard | whether this URL may be requested at all |
| pacing | when the request may go out |
| robots | whether a *discovered* URL may be requested |
| cache | whether a request need go out at all |
| fetch | how the response is read, capped, decoded and classified |
| parser | how the bytes become a document |

### 2.1 The closed error vocabulary

A fetch that fails is classified into exactly one of seven kinds: `unresolved`, `refused`,
`timeout`, `tls`, `blocked`, `robots`, `other`. Three of them — `unresolved`, `refused`,
`tls` — mean the thing at the other end is dead rather than unavailable, and that
distinction decides whether a link is reported as broken or merely unchecked.

### 2.2 What is never cached

Failed requests, `POST`, a streamed body nobody read, and a body above the ceiling. What
*is* cached is `GET` and `HEAD`, keyed so that a `HEAD` and a `GET` of one URL are two
questions and a different `Accept` header is a different request.

## Requirements

### Requirement: HTTP-1 — a URL is validated before it is requested, and the address it validated is the address it connects to

Every request MUST pass the guard first. The guard SHALL resolve the host, SHALL refuse
the resolved address if it is private, link-local, reserved, multicast or unspecified, and
the connection SHALL then be pinned to the address that was validated — so a name that
resolves twice cannot answer the check with one address and the request with another.

**Why:** a validate-then-connect gap is the whole of DNS rebinding, and it turns the guard
into decoration. The audited URL is attacker-controlled by construction: it is whatever the
operator was given.
**Reader:** enforced. `tests/test_safe_http.py` holds it in two classes.
`test_dns_rebinding_connects_only_to_the_answer_the_guard_validated`
resolves a name to a public address and then to loopback and asserts one lookup, a
connection to the public address only, and the `Host` header preserved;
`test_redirect_refuses_a_private_second_hop_without_reusing_the_first_pin` pins the redirect
case; `test_resolution_failure_is_refused_before_a_request` asserts that a name that does
not resolve costs no request at all. All three read the path a checker's fetch takes.

The one request the substrate made on its own account was uncovered until 0.94.1, and it
was uncovered because it was also unguarded: `_fetch_robots` called `requests.get`
directly, so every origin's `/robots.txt` — the *first* request the audit makes to any
host — went out with no validation, no pin and unvalidated redirects. The requirement says
*every* request. `TheRobotsFetchGoesThroughTheGuardToo` reads all three halves of that
sentence: a blocked origin is not asked for its rules, the answer the guard validated is
the address the transport uses, and a redirect to a guarded address is not followed. Each
also asserts fail-open survives — a refusal costs no request and yields no policy, rather
than becoming an audit failure.

The comment that explained the direct call named a real constraint and it still holds:
`safe_get` consults `robots.txt`, so fetching `robots.txt` through it recurses. The guard
is a mechanism one level below that, and `_validated_url` and `_PinnedAdapter` are both
callable without touching robots at all — which is what the repair does.

#### Scenario: a name that answers the guard and the connection differently
- **WHEN** a host resolves to a public address for the guard's lookup and to loopback for
  the one the transport would make
- **THEN** exactly one lookup happens, and the connection is made to the address the
  guard validated
- **AND** the `Host` header, the SNI name and the certificate check still carry the
  original hostname, so pinning does not quietly weaken TLS

#### Scenario: a redirect onto a private second hop
- **WHEN** a validated first hop answers with a `Location` naming a private address
- **THEN** the second hop is validated in its own right and refused
- **AND** the first hop's pin is not reused for it

#### Scenario: a name with no address costs no request
- **WHEN** the host does not resolve
- **THEN** the call raises before anything goes out, and no server sees a request

#### Scenario: several answers, all of them validated
- **WHEN** the resolver returns more than one address and the first refuses the connection
- **THEN** the remaining addresses are tried in resolver order
- **AND** every one of them is an address this call validated, never one looked up again

### Requirement: HTTP-2 — the private allowance is per-run, narrower than "not public", and announced

`--allow-private` SHALL open the guard for the whole run, not for one script — fifty-five
checkers each guard themselves and a per-call allowance cannot reach them. It permits
loopback, RFC 1918, unique-local and carrier-grade NAT. It MUST NOT permit link-local,
reserved, multicast or unspecified addresses, and no flag may. The run SHALL say it is on.

**Why:** the allowance exists so an operator can audit a staging box or a fixture on
loopback. The addresses it must never reach are exactly the ones an SSRF attack wants —
`169.254.169.254` is a cloud metadata service, not a staging box — so the allowance is a
list, never a switch that means "anything not on the public internet".
**Reader:** partial. The narrowness is enforced from both sides:
`test_link_local_stays_blocked_with_the_allowance_on` and
`test_reserved_multicast_and_unspecified_stay_blocked` pin the refusals *with the allowance
on*, `test_the_allowance_permits_a_fixture_and_a_staging_box` pins the seven permitted
networks, and `test_an_unrecognised_value_does_not_open_the_guard` pins that only four
spellings of yes count. The announcement is pinned once. What is unread is the *per-run*
half, which is the requirement's first clause: nothing asserts that the allowance reaches a
child process. The suite's own docstring concedes the point and defers to CI.

#### Scenario: the allowance does not reach the metadata service
- **WHEN** the allowance is on and the URL resolves to `169.254.169.254`, to another
  link-local address, or to a link-local IPv6 address
- **THEN** the request is refused
- **AND** the refusal says the flag will not help, rather than sending the reader to set
  a flag that is already set

#### Scenario: the allowance does not reach reserved, multicast or unspecified addresses
- **WHEN** the allowance is on and the URL resolves into a reserved or multicast range, or
  to the unspecified address
- **THEN** the request is refused, because nothing legitimate is served there and
  permitting it would only widen the hole

#### Scenario: a staging box and a fixture on loopback
- **WHEN** the allowance is on and the URL resolves into loopback, RFC 1918, unique-local
  or carrier-grade NAT
- **THEN** the request is permitted
- **AND** the run says once, on a surface a single hand-run script also has, which address
  it allowed

#### Scenario: a typo does not open the guard
- **WHEN** the allowance is set to anything but the four spellings of yes — a blank, a
  nonsense word, a trailing space
- **THEN** the guard stays closed, the way an unparseable rate falls back to the default
  rather than to no limit

#### Scenario: the allowance belongs to the run, not to the caller
- **WHEN** a run given the allowance launches its checkers as separate processes
- **THEN** every one of those processes may reach the permitted addresses without being
  told again, because a per-call allowance cannot reach fifty-five scripts that each
  guard themselves

### Requirement: HTTP-3 — a private entry costs coverage, and says so

When the audited host resolves to a private address, every item that would call an outside
service SHALL report `NO_DATA` — never `N/A` — and the report SHALL say the audit ran
against a host only reachable from here.

**Why:** those items are not out of scope; they are unanswerable from where the audit
stands, and the difference is the score's denominator. `N/A` would remove them and lift the
score for a site nobody outside can see.
**Reader:** partial. `test_a_private_host_leaves_the_external_apis_undecided` pins the
status and the reason for all three outside-world capabilities, and
`test_a_private_run_is_named_on_every_surface` pins the report. Two halves are unread: that
the coverage falls rather than the denominator shrinking has no test, and no test observes
`entry_private` true from a real resolution — every test that uses it sets it by hand.

#### Scenario: a host only this machine can reach
- **WHEN** the audited host resolves to a private address
- **THEN** every item whose check needs an outside service — a measurement from another
  network, a reputation lookup, a property's history — reports `NO_DATA` with a reason
  naming the host
- **AND** the items that need only the page itself are left to answer for themselves

#### Scenario: the score is not lifted by what could not be seen
- **WHEN** those items are set aside
- **THEN** they stay in the denominator and the run's coverage falls
- **AND** they are not `N/A`, which would remove them and let a staging audit report the
  same coverage as a live one

#### Scenario: the audit finds out by resolving, not by being told
- **WHEN** a run audits a fixture or a staging box that is genuinely on a private address
- **THEN** it records the entry host as private because that is where the name resolved
- **AND** a public host audited with the allowance on is not recorded as private, and a
  host that does not resolve is unreachable rather than private

#### Scenario: the reader of the report is told
- **WHEN** a report is produced for such a run
- **THEN** it says this describes a local or staging copy rather than the site a visitor
  or a search engine sees, and that the outside-world items could not be decided at all

### Requirement: HTTP-4 — requests to one host are paced, across processes and across audits

Requests to a host SHALL be spaced by a stated default rate. The state MUST be shared
between processes and between concurrent audits on the machine, so two runs against one
site do not add up to twice the rate. A corrupt, stale or unwritable pacing state SHALL
slow the audit down and MUST NOT stop it.

**Why:** the fan-out is what makes an audit rude: fifty-eight checkers and a crawl against
one server. Per-process pacing would be no pacing at all, since the run is a process tree.
And a pacing mechanism that can fail closed is a mechanism that will one day hang an audit
on a lock file nobody can find.
**Reader:** enforced for the mechanism, unread for the number — `partial`. Three real
subprocesses are asserted to space themselves; different hosts are asserted not to queue
behind each other; a stale slot, a corrupt slot, junk contents and an unwritable directory
are each asserted not to stop the run. The default rate itself is asserted only against its
own constant, so `DEFAULT_MAX_RPS` could be 40 and the suite would stay green.

#### Scenario: separate processes queue behind each other
- **WHEN** several checkers, each its own process, pace themselves against one host
- **THEN** each waits behind the one before it, so the machine's combined rate is the
  configured rate and not a multiple of it
- **AND** they queue in the state the run named, not in whichever directory each process
  picked up for itself

#### Scenario: one slow site does not pace an unrelated one
- **WHEN** a request has just gone to one host and a request to a different host follows
- **THEN** the second is not made to wait behind the first

#### Scenario: the shared state is unusable
- **WHEN** the pacing slot holds a timestamp from before a reboot, two concatenated
  writes, junk, or cannot be written at all
- **THEN** the process paces itself alone and the request goes out
- **AND** nothing raises out of pacing into the thirty-six scripts that called it

#### Scenario: the default rate is a number somebody chose
- **WHEN** the default requests-per-second is changed
- **THEN** something fails that names the value — not an assertion that compares the
  constant with itself and moves with it

### Requirement: HTTP-5 — `robots.txt` governs discovered URLs and never the audited one

A URL the audit found — in a sitemap, in a link, in a crawl — SHALL be fetched only if
robots allows it. The URL the operator handed in MUST be fetched regardless, and a robots
rule forbidding it SHALL be reported as a finding about the site rather than as a refusal
to work.

**Why:** both halves fail silently if reversed. Applying robots to the audited URL turns
"your robots.txt blocks this page" into a tool that produces nothing, and the operator
cannot tell that from a crash. Not applying it to discovered URLs makes the audit crawl
whatever it happens to find, which is what robots exists to prevent.
**Reader:** partial, and the asymmetry itself is unread. `test_a_disallowed_path_is_refused`
and `test_rules_naming_our_token_are_obeyed` pin the discovered half;
`test_an_absent_or_unreadable_robots_txt_allows` and
`test_a_fetch_that_raises_allows_rather_than_failing_the_audit` pin fail-open;
`test_robots_txt_is_fetched_once_per_origin_and_cached` pins the caching; and
`test_a_refusal_is_flagged_apart_from_a_failure` pins that a refusal is not a failure. But
the default that produces the asymmetry is asserted only through the function's *signature*
— that the parameter's default is `False` — and no test shows what breaks when either half
is reversed. That an audited URL blocked by robots yields a `critical` finding rather than
a refusal is pinned as a `FAIL` and not as a severity.

#### Scenario: a URL the audit found for itself
- **WHEN** a sitemap, a link or a crawl yields a URL a robots rule disallows
- **THEN** it is not fetched
- **AND** the refusal is carried as our own restraint, not as the site failing — a
  sitemap URL we politely declined is not an orphan page

#### Scenario: the URL the operator handed in
- **WHEN** the audited URL is disallowed by the site's own `robots.txt`
- **THEN** it is fetched anyway
- **AND** the block is reported as the `critical` item about being blocked from crawling,
  rather than as forty-odd items reporting that they could not look

#### Scenario: the asymmetry reversed
- **WHEN** robots is applied to the audited URL by default
- **THEN** the audit collapses into undecided items with the one finding that mattered
  buried inside them, and the operator cannot tell that outcome from a crash

#### Scenario: a redirect off a permitted path
- **WHEN** a discovered URL that robots allows redirects onto a path robots forbids
- **THEN** the second hop is refused, so a site that redirects cannot make the rule
  trivially avoidable

#### Scenario: there is nothing readable to obey
- **WHEN** `robots.txt` is absent, blank, unparseable, or the fetch for it raises
- **THEN** the URL is allowed and the audit continues, because refusing to look at a site
  whose operator asked for the audit is the worse answer

### Requirement: HTTP-6 — the crawl identifies itself by a token that can be blocked

The audit SHALL send a user agent naming itself, and the robots token MUST be a bare word
a site owner can write a rule against.

**Why:** politeness that cannot be declined is not politeness. A site owner's only lever is
a rule in `robots.txt`, and it only works if the token is stable and matchable.
**Reader:** enforced. `test_rules_naming_our_token_are_obeyed` asserts that a rule naming
the token beats the wildcard, and asserts the token is bare — no slash.
`TheAgentIdentifiesItselfOnTheWire` holds the other end of the same sentence, through a
real request rather than against the constants: the shared agent is what leaves the
substrate, it carries the blockable token and a URL explaining what the tool is, and a
caller supplying its own `User-Agent` cannot take the tool's name off the wire while its
other headers still travel. Probed 6 September 2026 by moving the agent assignment in
`default_headers` above the caller merge — the shape that would make the audit unblockable
by accident — which reddens the third test.

#### Scenario: a site owner writes a rule against us
- **WHEN** `robots.txt` carries a group naming the token and a separate wildcard group
- **THEN** the group naming the token decides, and the wildcard's paths do not apply to us

#### Scenario: the token is not a User-Agent string
- **WHEN** the full user agent is offered to the robots matcher instead of the bare token
- **THEN** the matcher splits it at the first `/`, reads it as the browser name at the
  front, and the site's rule for us is silently ignored while the wildcard applies
- **AND** that is the failure the bare token exists to prevent, so the token carries no
  slash

#### Scenario: what actually goes on the wire
- **WHEN** any request leaves the substrate, whatever headers its caller supplied
- **THEN** it carries the shared user agent naming the tool, so the token a site owner
  can block is the token it will see

### Requirement: HTTP-7 — the cache answers questions, never invents them

A cached response SHALL be indistinguishable from the live one it replaced, down to its
redirect chain. Failures, `POST`s, streamed bodies and oversized bodies MUST NOT be stored.
A cache hit MUST still be subject to robots. Two requests that differ in method or in a
header the server may vary on SHALL be two questions.

**Why:** a cache that merges two different questions produces a verdict about a document
nobody fetched. Caching a failure would freeze a transient outage into the run. And a hit
that skipped the robots check would let the cache launder a request the audit is not
allowed to make.
**Reader:** enforced, and unusually well. Restored responses are asserted field by field
including the redirect chain; failures, `POST`s and streams are each asserted never to be
stored; a truncated entry is asserted to be a miss rather than half a page; a smaller cap is
asserted to refetch rather than truncate; `HEAD` and `GET`, and two different `Accept`
values, are asserted to be separate entries; eight concurrent processes are asserted to
produce one request; and `test_a_cache_hit_still_refuses_a_path_robots_forbids` pins the
robots re-check.

#### Scenario: a restored response is the response that was fetched
- **WHEN** a request is answered from the cache
- **THEN** its status, reason, URL, headers, encoding, body and elapsed time are the live
  response's own
- **AND** its redirect chain is restored hop for hop, because the hop count and the
  response time are both reported as findings

#### Scenario: a transient failure is not frozen into the run
- **WHEN** a request is refused, times out, or is stopped by the guard
- **THEN** nothing is stored, and the next caller asks again rather than inheriting one
  outage as every item's outage

#### Scenario: a cache hit does not launder a request robots forbids
- **WHEN** an entry was warmed by a caller that does not consult robots — which is exactly
  how the audit target is fetched — and a later caller asks with robots on
- **THEN** the stored redirect chain is re-checked and the disallowed hop is refused

#### Scenario: half a file on disk is not half a page
- **WHEN** a stored entry is short of the length it says it has, because a write did not
  finish
- **THEN** it is a miss and the request goes out again, rather than a document with its
  end missing being served as the page

#### Scenario: two questions are not one
- **WHEN** one URL is asked with `HEAD` and with `GET`, with two different `Accept` values,
  or with redirects allowed and refused
- **THEN** each is its own entry
- **AND** the caller that asked to see the hop is not answered with the hop's destination

### Requirement: HTTP-8 — the run says whether it used a cache

An artifact SHALL record whether the response cache was on, and the surface a reader is
handed SHALL say so too. With it off, two items may describe two states of the same
document; with it on, a verdict may be about a response fetched earlier in the run.

**Why:** every other thing that changes what a verdict is *about* — the parser, a private
host, an overridden guard, a stale artifact — appears in the report's provenance. The cache
belongs in that list for the same reason: it is the difference between "this is the page"
and "this was the page a few minutes ago".
**Reader:** enforced, and the half that was missing was a defect rather than a gap in the
tests. `test_a_normal_run_records_that_the_cache_was_on` and
`test_turning_the_cache_off_is_recorded_too` hold the requirement's own sentence in both
directions — a field hard-coded to `True` would satisfy the first alone — and
`--no-http-cache` is exercised end to end.

What the **Why** argued for did not exist until 0.94.1: `provenance_warnings` covered the
parser, the private host, the allowance, the guard, the thin entry and the artifacts, and
**not the cache**, so the fact was recorded in the artifact and reached nobody. Closing it
needed a mechanism as well as a test, because the scenario is about a run that *answered
from* the cache and nothing counted hits — only whether the cache was open. A warning on
every cached run would be one a reader learns to skip, which is the same reason the parser
warning is silent for `lxml`.

The count is kept in the shared state directory beside the pacing slots, under the same
lock discipline, because every checker is its own process and a tally in memory reports
zero in the runner that writes the artifact. `TheCacheTellsTheReaderItAnswered` holds the
boundary from both sides — a served entry counts, an entry refused by the cap or by the
robots re-check does not, and a second process reads the same tally — and
`TheReportNamesTheCacheOnlyWhenItAnswered` holds the surface in both directions. Probed by
making the warning fire on `http_cache` instead of on the count, which reddens the silent
case.

The absence itself had been pinned rather than left to be rediscovered:
`test_the_provenance_list_still_omits_the_cache` was written to fail *at the moment the
cache joined the list* and to say in its own message that it should then be replaced. It
did, on a full audit that answered 69 responses off disk, and
`test_the_reader_of_the_report_is_told_the_cache_answered` is what replaced it.

#### Scenario: the artifact says the cache was on
- **WHEN** a run that could fetch anything completes
- **THEN** the payload records that the response cache was on

#### Scenario: the artifact says it was off
- **WHEN** the same run is given `--no-http-cache`
- **THEN** the payload records that it was off, so a field hard-coded to on cannot pass
  for a recording

#### Scenario: the reader of the report is told too
- **WHEN** a report is produced for a run that answered any item from the cache
- **THEN** the provenance list names the cache, beside the parser, the private host, the
  overridden guard, the thin entry page and the supplied artifacts
- **AND** a reader can tell "this is the page" from "this was the page a few minutes ago"
  without opening the JSON

### Requirement: HTTP-9 — a failed fetch is classified into a closed vocabulary, and the classification travels

Seven kinds, no others. Every failure SHALL carry both a message and a kind, and a fetch
that succeeded MUST carry neither. Downstream, the three kinds that mean "nothing is there"
SHALL produce a broken link and the rest an unchecked one.

**Why:** the message is for a person and drifts; the kind is for the code and must not. A
link reported as broken because the audit was blocked is a false accusation about somebody
else's site.
**Reader:** enforced. `test_the_closed_vocabulary_is_produced_from_exception_types` asserts
the seven kinds in order and all seven exception mappings, and
`test_unresolved_is_broken_and_blocked_is_unchecked` pins the downstream split.
`ASuccessfulFetchCarriesNoFailure` reads the other half of the `iff` through
`seo_common.fetch_url`, where the fields are written: a plain 200, a 404 — a successful
fetch of an error page, which is where the two ideas are easiest to confuse — and a
subtest over four statuses asserting the fields travel together or not at all. Probed
6 September 2026 by setting a kind on any status ≥ 400, the shape a consumer of
`broken_links.py` would turn into a false accusation about somebody else's site, which
reddens three.

#### Scenario: every failure carries a kind
- **WHEN** a fetch fails
- **THEN** it carries a kind that is one of the seven, decided by the exception's type
  rather than by its wording

#### Scenario: a resolver failure wrapped in a connection error
- **WHEN** the transport reports a connection error whose cause is a name that does not
  resolve
- **THEN** the kind is `unresolved`, taken from the typed chain and not from the prose

#### Scenario: our own restraint is not the site's defect
- **WHEN** a link could not be checked because the guard stopped us or `robots.txt`
  forbade it
- **THEN** it is reported as unchecked
- **AND** it is not counted as broken, which would be a false accusation about somebody
  else's site

#### Scenario: a fetch that worked claims nothing
- **WHEN** a fetch succeeds
- **THEN** both the message and the kind are absent, so no stale classification can
  survive into a successful result

### Requirement: HTTP-10 — a cap is a stated condition, never a silent truncation

A response larger than the ceiling, or larger than a caller's own limit, SHALL raise rather
than return a shortened body. A declared encoding MUST be honoured; where nothing is
declared the bytes are sniffed, and what is found past the sniff window MUST NOT be read.

**Why:** a truncated body is a document with its footer missing, and every checker that
counts elements would answer confidently about a page that does not exist. The same is true
of a mis-decoded one: a page read as ISO-8859-1 has different text, different word counts
and different headings.
**Reader:** partial. The cap raises rather than truncating, and a smaller cap is asserted to
cost a real refetch. The encoding recovery is covered thoroughly — fourteen tests over
header-versus-meta precedence, BOMs, XML declarations, commented-out metas, and a
declaration past the sniff window that is deliberately *not* read. What is unread is the
default ceiling itself, which no test exercises, and the redirect budget, which no test
exhausts.

#### Scenario: a body over the ceiling
- **WHEN** a response grows past the caller's limit while it is being read
- **THEN** the read stops and raises, and no shortened body is returned, decoded or stored

#### Scenario: a caller that wants less than what is already stored
- **WHEN** a complete stored body is larger than a later caller's own cap
- **THEN** the request goes out again and fails exactly as it would have without a cache,
  rather than the stored body being trimmed to fit

#### Scenario: the server names the encoding
- **WHEN** `Content-Type` carries a charset, with or without spaces around the `=`
- **THEN** it decides, even where the document declares something else — a disagreement is
  a site defect for an item to report, not something to paper over here

#### Scenario: the server names none
- **WHEN** a markup or text response arrives with no charset and the document declares one
  in a BOM, an XML declaration or a `<meta>`
- **THEN** that declaration decides, rather than the old HTTP default that would render
  every heading and word count as mojibake
- **AND** a declaration that is commented out, names a codec that does not exist, or sits
  past the sniff window does not decide, because a guess that rewrites a page's text is
  what this rule refuses

#### Scenario: the redirect budget runs out
- **WHEN** a chain is longer than the configured number of hops
- **THEN** the call raises rather than following one more, or handing back the last hop as
  though it were the destination

### Requirement: HTTP-11 — TLS verification is never relaxed

Certificate verification MUST be on for every request the substrate makes, and no caller
SHALL be able to turn it off.

**Why:** an audit that reports on a site's security while accepting any certificate is
making a claim it did not check. The failure is silent by construction — everything works
better with verification off.
**Reader:** enforced, in the two halves this line used to say were both missing.
`test_a_caller_asking_for_no_verification_is_overruled` and
`test_verification_is_on_when_nobody_mentions_it` capture what the adapter actually
received and require `True` whatever the caller asked for;
`test_a_caller_supplying_a_bundle_path_is_also_overruled` covers the other way a caller can
try to decide the question. Probed by weakening the unconditional assignment to a
`setdefault`, which reddens two of them.

`test_no_script_turns_verification_off_behind_the_substrate` is the census this line asked
for — the shape `tests/test_parser.py` already ran for the HTML parser and nothing ran for
TLS. It walks the AST of every script and refuses `verify=False` as a keyword or an
attribute assignment, so a checker calling `requests` directly is caught by structure
rather than by spelling, and a docstring quoting the phrase is not. Probed by adding such a
call to a checker: it fails naming the file and line.

#### Scenario: a caller asks for no verification
- **WHEN** a caller passes verification off
- **THEN** the request still goes out with it on, whatever the caller asked for

#### Scenario: a caller supplies its own bundle
- **WHEN** a caller passes a path where the decision would be taken instead of a boolean
- **THEN** it is overruled too, because the question is not the caller's to decide

#### Scenario: nobody mentions it
- **WHEN** no caller says anything about verification
- **THEN** it is on
- **AND** weakening the unconditional assignment into one that merely supplies a default
  is a failure rather than a tidy-up

#### Scenario: a script that goes around the substrate
- **WHEN** any script turns verification off directly — as a keyword on a request or as an
  attribute on a session
- **THEN** a census over the tree refuses it by structure, naming the file and the line
- **AND** a docstring quoting the phrase is not mistaken for one

#### Scenario: a script turns it off below the request layer
- **WHEN** a script builds an SSL context that does not check the hostname, or sets the
  verify mode to none, or asks for an unverified context outright
- **THEN** the census refuses that too, because `verify=` is one spelling of the decision
  and not the decision
- **AND** the one file allowed an unverified handshake is allowed it only because its
  verdict comes from a verifying one first

### Requirement: HTTP-12 — no verdict may depend on which HTML parser ran

Two parsers are available and they disagree about malformed markup. No field any registry
rule reads MAY differ between them, the choice SHALL be made in one place, and the run
SHALL record which parser produced its verdicts.

**Why:** the guarantee cannot come from the libraries — they genuinely differ, and one of
the differences is pinned in the suite as a known divergence. It can only come from a test
over a corpus, which means it holds for the shapes in the corpus and is a promise about the
rest. Recording the choice is what makes a future disagreement diagnosable.
**Reader:** enforced. Agreement is enforced across fifteen
document shapes for every field a rule reads; the single choice point is enforced by two AST
censuses — one asserting the parser name appears in no other file, one asserting every
`BeautifulSoup(` call names the shared choice. The recording half was the gap until
6 September 2026, and its shape is worth keeping: the test *named* for the recording
asserts that two functions return the same string, which reads the label and not the field.
`TheRecordedParserReachesTheArtifactAndTheReader` runs the audit twice, once under each
parser, and reads `html_parser` out of both artifacts — so the recording has to follow the
choice rather than merely exist — then reads the report surface in both directions: a
fallback run says so on its face, and a default run does not, because a caveat printed
every time is one a reader learns to skip. Probed by hard-coding the recorded field to
`lxml`, which reddens two of the four.

#### Scenario: the parsers disagree and no verdict moves
- **WHEN** a document shape the two parsers genuinely read differently is parsed with each
- **THEN** every field a registry rule reads is equal between them
- **AND** the divergences that remain are ones no rule reads

#### Scenario: a script that decides for itself
- **WHEN** a script picks its parser from what happens to be imported already, or names a
  parser without going through the shared choice
- **THEN** a census over the tree refuses it, because two entry points inside one audit
  could otherwise read one page two ways

#### Scenario: a typo in the override
- **WHEN** the parser override names something that is not a parser
- **THEN** the shared choice falls back to the preferred one rather than quietly changing
  what the run measures

#### Scenario: the run says which parser produced its verdicts
- **WHEN** two runs of one site disagree about a structural field
- **THEN** the parser each used can be read out of its own artifact
- **AND** a report produced by the fallback parser says so on its face, which is what makes
  the disagreement diagnosable

## 4. Invariants

* **INV-H1** — every script that can open a connection goes through the guard.
  *Reader: partial* — an AST census asserts that every script importing a networking module
  also imports the guard, with three written exemptions and a test that the exemptions are
  not stale. It asserts imports, not use: a script could import the guard and call
  `requests` directly.
* **INV-H2** — a cached response is byte-identical to the response it replaced.
  *Reader: enforced* — seven fields plus the header mapping and the redirect chain are
  compared between a live and a restored response.
* **INV-H3** — the audit makes no request the guard did not validate, including redirects.
  *Reader: enforced* — the pinned adapter is asserted to try validated addresses in resolver
  order, to refuse a private second hop without reusing the first pin, and to keep the
  original name for SNI and certificate matching.
* **INV-H4** — pacing state is machine-wide, so concurrent audits pace each other.
  *Reader: partial* — the default directory is asserted to be under the machine's temp
  directory and to be read on every use, and the record of known issues pins the same three
  properties. Nothing runs two audits at once and measures the combined rate.

## 5. What this document does not decide

* when a run may reach the network at all, and what a gated item reports —
  `openspec/specs/run-lifecycle/`;
* what each checker does with the document it is given — `openspec/specs/evidence/`;
* how an operator-supplied artifact is validated — `openspec/specs/inputs/`;
* which provenance warnings the report shows and how — `openspec/specs/reporting/`, which owns the
  surface HTTP-8 says the cache belongs in;
* what the numbers should be. This document requires the rate, the caps and the timeouts to
  be stated and read; `DEFAULT_MAX_RPS = 4.0`, `DEFAULT_TIMEOUT = 15` and the rest are
  calibration, and belong with whoever measures the cost of a run.

## 6. Open questions

**Is a constant with no reader a defect or a cost?** Eleven constants in this substrate
have no test at their value: the default rate, both cache lifetimes and ceilings, the
robots cache lifetime and byte cap, the stale-slot horizon, the default timeout, the
redirect budget and the response ceiling. Pinning a number in a test is cheap and makes
every future change deliberate; it also freezes calibration into the suite, and this tree
has a whole document about thresholds whose basis nobody recorded. What would settle it: a
rule about *which* numbers must be pinned — plausibly those a verdict depends on, which is
the distinction `audit_thresholds.py` already draws for the checkers and has never been
applied to the substrate.

**Should the parser guarantee be a corpus or a property?** HTTP-12's agreement is asserted
over fifteen document shapes. Nothing says what happens when a rule reads a field the
corpus does not exercise, and nothing adds a shape when a rule is added. What would settle
it: whether the fields a rule reads can be enumerated from the registry — they can, and the
corpus could then be checked for covering them, which would turn a fixed corpus into a
derived obligation.

**Does the audit owe `robots.txt` its `Crawl-delay` when the operator is in a hurry?**
Today a stricter crawl delay is honoured and a laxer one ignored, which is the polite
reading. There is no way for an operator to say "this is my own site, go faster", and the
rate is a machine-wide default. What would settle it: whether an audit of your own
infrastructure is a different act from an audit of somebody else's — which is the same
question `--allow-private` already answers yes to.

## Appendix A — measured disagreements, 29 August 2026

Observation, not specification. Measured at commit `fcff201`.

#### A.1 — the artifact records whether a cache was used, and nothing anywhere reads it

`http_cache` is written into every results payload. Searching the whole test suite for the
string returns nothing. The report's provenance warnings — the surface whose entire job is
to say what might make a verdict less than it looks — cover the parser, the private host,
the allowance, the guard, a thin entry page and the artifacts, and do not mention the cache.
`--no-http-cache` has no test either.

The field is therefore a claim nobody makes and nobody checks. It is the third instance of
the shape this suite keeps finding: a value recorded beside the thing it describes, faithful
at the moment it was written, compared with nothing afterwards.

**Closed 6 September 2026.** Measured again at that date the search returns readers in three
files, and the missing surface exists: a run that answered from the cache says so, with the
count. What the closing needed that was not obvious from this measurement is that the cache
had to learn to *count*, not merely to be on — the requirement is about answers off disk,
and nothing distinguished those from an open cache that missed everything.

#### A.2 — eleven constants decide behaviour and none is pinned at its value

| constant | value | what a test asserts |
|---|---|---|
| `DEFAULT_MAX_RPS` | 4.0 | equal to itself, after a bad environment value |
| `MAX_RETRY_AFTER_WAIT` | 30.0 | that it is under 120, and that a 3600 s hint exceeds it |
| `STALE_PACE_SLOT_SECONDS` | 3600 | nothing; the stale-slot test writes its own 10 000 |
| `ROBOTS_CACHE_TTL` | 1800.0 | its value, in the known-issues ledger — not in a test |
| `ROBOTS_MAX_BYTES` | 512 KiB | nothing |
| `CACHE_TTL` | 900.0 | nothing |
| `CACHE_MAX_BODY` | 8 MiB | nothing |
| `CACHEABLE_METHODS` | `GET`, `HEAD` | both exercised behaviourally, the tuple never named |
| `DEFAULT_TIMEOUT` | 15 | appears as a *key* in an exemption table |
| `DEFAULT_MAX_REDIRECTS` | 5 | appears in a comment |
| `DEFAULT_MAX_RESPONSE_BYTES` | 5 MiB | nothing; the cap test passes its own limit |

Two of these are worth separating from the rest. `DEFAULT_MAX_RPS` has a test that *looks*
like a reader — it asserts `max_rps()` equals `DEFAULT_MAX_RPS` after an unparseable
environment value — and is a reader of the fallback, not of the number: both sides move
together. And `ROBOTS_CACHE_TTL`'s only assertion lives in the ledger of known issues,
which is a record of decisions rather than a gate on behaviour.

#### A.3 — six tests are named for more than they assert

Found while censusing the substrate's readers, and listed because a reader census assembled
from test *names* would credit every one of them:

| test | what the name claims | what the body asserts |
|---|---|---|
| `test_the_run_records_which_parser_produced_its_verdicts` | the run records the parser | two functions return the same string; no artifact is opened |
| `test_both_html_parsing_entry_points_agree` | two entry points agree | the two names are the same function object |
| `test_respect_robots_is_off_by_default` | behaviour under the default | the parameter's declared default, by signature introspection |
| `test_an_absurd_backoff_is_not_waited_out` | the wait does not happen | the returned value exceeds the cap; nothing asserts nobody sleeps for it |
| `test_the_state_directory_is_not_the_one_an_audit_would_use` | a property of the audit | a property of the test suite's own environment |
| `test_one_url_keeps_one_cache_slot_when_its_pin_changes` | the pin changed | one request and a cache hit; the changing pin is arranged and never asserted |

None of them is a bad test. Each asserts something true and worth asserting. The defect is
in the census, not in the suite — which is exactly why `Reader:` lines in this document name
what a body asserts rather than what a test is called.

#### A.4 — the guarantee with the strongest wording has the weakest reader

HTTP-11 — verification is never relaxed — is implemented as an unconditional overwrite of
whatever the caller passed, which is the strongest form the code can take. It has no test at
all, and no census forbids `verify=False` elsewhere in the tree, though the suite runs
precisely that shape of census twice for the HTML parser: one AST walk asserting the parser
name appears in only one file, another asserting every parse names the shared choice.

The two censuses that exist were written after a defect. The one that does not exist guards
the property whose failure is silent and total.

#### A.5 — the substrate makes one request that does not pass its own guard

Found on 5 September 2026 while writing HTTP-1's scenarios, and verified by reading the
chain end to end.

`robots_allows(url)` calls `robots_policy`, which calls `_robots_text_once`, which calls
`_fetch_robots(origin)`:

    response = requests.get(  # not safe_get: that would recurse into this
        urljoin(origin, "/robots.txt"), ...

The comment is honest about why — routing robots through `safe_request` would recurse,
since `safe_request` consults robots — and the fetch is paced and cached. What it is not
is guarded. No `_validated_url`, no address check, no pinned adapter. So HTTP-1's first
clause, *every request passes the guard first*, is false for a request the substrate makes
against every origin it touches; and its second clause is worse off than that, because
`_fetch_robots` resolves the host again on its own. A name that answers the guard with a
public address and the robots fetch with a private one reaches the private one — which is
the validate-then-connect gap HTTP-1 exists to close, and which
`test_dns_rebinding_connects_only_to_the_answer_the_guard_validated` pins for the audit's
own fetches and not for this one.

`_robots_permits_entry` widens the surface rather than creating it: on a cache hit it calls
`robots_allows(hop)` for every stored redirect hop, so one cached entry can trigger an
unguarded fetch per origin in the chain.

The recursion the comment avoids is real, so the fix is not "call `safe_get`". It is to
validate and pin the address without consulting robots — the guard and the politeness
check are separable, and only one of them recurses.

This is why HTTP-1 moves from `enforced` to `partial` in Appendix B. The reader is good and
covers the path it was written for; the requirement says *every* request, and one request
is outside it.

## Appendix B — how much of this document is enforced

Four rows were measured by mutation and the rest were derived from a census of what each
test body asserts. The distinction is stated because it is the difference between a
classification and a guess, and this suite has been wrong four times in the guessing
direction.

**Probed:** HTTP-1 — replacing the pinned adapter with a plain one fails six of the nine
guard tests. HTTP-7 — making a cache hit skip the robots re-check fails one test, which is
the clause the Reader line singles out. HTTP-11 — turning the unconditional `verify = True`
into a `setdefault`, so a caller may relax it, left 319 tests green when this was written
and reddens two of its four readers now. HTTP-8 — as of 5 September 2026 the recording is read in both directions and the
provenance omission is pinned as an absence; before that, the string
`http_cache` appears nowhere under `tests/`.

**Derived, not probed:** the five `partial` rows. Each names which half it believes is
unread; that half was established by reading the asserting test's body and by greps for the
absences, not by breaking the code. A `partial` that is really an `enforced` or a `none` is
the error this method leaves open, and the halves are where to look first.

| | requirements |
|---|---|
| **enforced** | HTTP-1, HTTP-6, HTTP-7, HTTP-8, HTTP-9, HTTP-11, HTTP-12 |
| **partial** | HTTP-2, HTTP-3, HTTP-4, HTTP-5, HTTP-10 |
| **none** | — none |
| **opposed** | — none |

Invariants: INV-H2 and INV-H3 enforced; INV-H1 and INV-H4 partial.

**Seven enforced, five partial, nothing unread, of twelve.**

HTTP-1 moved on 6 September 2026, and the half that was missing turned out to be a hole
rather than a gap in the tests: the `robots.txt` fetch skipped the guard entirely, so the
first request to any host was the one request nothing protected. Three tests now hold it,
each written red first — a blocked origin was contacted, the validated answer was
discarded and the name resolved again, and a redirect to `169.254.169.254` was followed.

The first two enforced are the cache and the pinned connection, and they have in common
something worth noticing: both were built *after* a specific failure was understood, and
both were written with their tests. The two unread ones — that the run says whether it
cached, and that TLS verification is never relaxed — were the two whose violation produces
no visible symptom at all. A run that quietly reused a stale response and a run that quietly accepted a bad
certificate both produce a clean, complete, confident report.

HTTP-11 was closed on 5 September 2026, and what it needed was named in its own Reader
line: this suite already ran a census of exactly that shape for the HTML parser and had
never run one for TLS. Writing it took the AST walk `tests/test_parser.py` already uses.
The lesson is not that the census was hard — it is that a requirement can sit at `none` for
want of a technique the repository is already fluent in, and nothing notices until
something reads the requirements one at a time and asks what each would need.

That is the pattern across this substrate rather than a coincidence of effort. Nine of the
twelve requirements here are about something *not* happening — no unvalidated connection, no
cached failure, no truncated body, no relaxed verification, no parser-sensitive verdict — and
the four best-read requirements are the four where the absence has a visible consequence a
test can name. Where the absence is invisible, the reader is a constant nobody pinned or a
census nobody wrote.
