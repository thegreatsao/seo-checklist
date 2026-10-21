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

Every request to a URL the operator or the audited site supplied MUST pass the guard first.
The guard SHALL resolve the host, SHALL refuse
the resolved address unless it is globally routable — private, shared (100.64.0.0/10),
link-local, reserved, multicast and unspecified addresses alike — and the connection SHALL
then be pinned to the address that was validated, so a name that resolves twice cannot
answer the check with one address and the request with another. A checker that opens a
socket of its own SHALL connect to the addresses the guard validated, never to the name.

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
`test_shared_address_space_is_private_unless_the_run_allows_it` resolves three addresses
in 100.64.0.0/10, by name and as literals, and requires a refusal without the allowance and
a pass with it. `test_tls_certificate.ConnectsToTheValidatedAddress` resolves a name to a
public address and then to loopback, and requires the one connection `tls_certificate.py`
opens to go to the public address; its second test fails the verifying handshake so the
second pass runs, and requires both connections on the public address and the name, not
the address, as SNI on both. Until 0.172.0 the first stopped before any handshake, so the
second pass and the SNI name were unread: probed by mutation (F13), a second pass that
resolved the name again, or either pass sending the address as SNI, stayed green.

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

**A proxy is never asked, and until 0.149.0 the request was still written for one.** The
pin is the connection: a proxy named in the environment, or in the system settings Python
reads on macOS and Windows, would resolve the name itself and make the validated address
irrelevant, so it is not used. The request SHALL therefore be the one an origin is sent.
It was not. Requests chooses the request target from the proxies it believes are in use,
and for a plain-http URL that target is the whole URL — `GET http://host/path` — which
the pinned connection delivered to the origin. A server that routes on the path answered
404 for a page it has. Nothing held it because no test and no CI job runs with a proxy
configured; it was found by running the suite on a Mac whose system settings name one,
where 249 tests failed on that line. `AProxyInTheEnvironmentIsNotInTheRequest` sets
every proxy variable and no exemption, and requires the path as the origin's request
target and no connection to the proxy, for a page, for the robots fetch and for each hop
of a redirect. An `https` target was not affected — Requests writes it as a path, since a
proxy would be tunnelled through — and `test_the_target_is_the_path_whatever_the_scheme`
asks the adapter for both.

**Globally routable, from 0.167.0.** The list of refused ranges was the list
`ipaddress` has flags for, and shared address space (RFC 6598: carrier NAT, Tailscale) is
neither private nor reserved to it. A public audit could reach a tailnet peer of the machine
running it. The guard now refuses any address that is not `is_global`; the range was
already one of the allowance's networks (HTTP-2), so `--allow-private` still opens it.

**A socket of its own, from 0.167.0.** `tls_certificate.py` reads the certificate over a
socket it opens itself, since the request layer does not hand the certificate back. It
validated the host and then let `socket.create_connection` resolve the name again, which is
the validate-then-connect gap this requirement exists to close. It now connects to
`safe_http.validated_addresses()`, in resolver order; the name still goes to SNI and to
certificate matching, so what is verified is unchanged.

**Not the fixed services.** Two scripts reach a fixed third-party endpoint directly, not
through the guard, and never connect to a URL the site supplied: `html_validator.py` asks the
W3C Nu validator (`validator.w3.org`), which fetches the page itself, and
`domain_safety_check.py` posts to Google Safe Browsing and runs the system `whois` binary on
the domain. Both import the guard, so INV-H1's census, which reads imports and not calls,
passes them: that is the gap its `partial` names. The first sentence of this
requirement said "every request" until 0.172.0, which these do not meet (F13 review).

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

#### Scenario: a proxy is configured
- **WHEN** the environment or the system settings name an HTTP proxy, and nothing
  exempts the host
- **THEN** the proxy receives no connection
- **AND** the origin receives the request it would receive with no proxy configured: the
  path as its target, for the page, for `robots.txt` and for every hop of a redirect

#### Scenario: an address in shared address space
- **WHEN** a host resolves into 100.64.0.0/10, or the URL names such an address, and the
  run has no private allowance
- **THEN** the request is refused, as a private address is
- **AND** with the allowance on it is permitted, because carrier-grade NAT is one of the
  networks the allowance names

#### Scenario: a checker with a socket of its own
- **WHEN** a checker opens its own connection and the name would resolve differently the
  second time
- **THEN** the connection goes to an address the guard validated, not to a second lookup

### Requirement: HTTP-2 — the private allowance is per-run, narrower than "not public", and announced

`--allow-private` SHALL open the guard for the whole run, not for one script — fifty-five
checkers each guard themselves and a per-call allowance cannot reach them. It permits
loopback, RFC 1918, unique-local and carrier-grade NAT. It MUST NOT permit link-local,
reserved, multicast or unspecified addresses, and no flag may. The run SHALL say it is on.

**Why:** the allowance exists so an operator can audit a staging box or a fixture on
loopback. The addresses it must never reach are exactly the ones an SSRF attack wants —
`169.254.169.254` is a cloud metadata service, not a staging box — so the allowance is a
list, never a switch that means "anything not on the public internet".
**Reader:** enforced. The narrowness is enforced from both sides:
`test_link_local_stays_blocked_with_the_allowance_on` and
`test_reserved_multicast_and_unspecified_stay_blocked` pin the refusals *with the allowance
on*, `test_the_allowance_permits_a_fixture_and_a_staging_box` pins the seven permitted
networks, and `test_an_unrecognised_value_does_not_open_the_guard` pins that only four
spellings of yes count. The announcement is pinned once. The *per-run* half — the
requirement's first clause — was unread until 0.94.1, and the suite's own docstring
conceded the point and deferred to CI. `ThePrivateEntryIsObservedAndCostsCoverage` audits a
real loopback server and reads a verdict that exists only if a **child** was allowed to
connect: the checkers are separate processes, so an allowance stopping at the runner would
leave the entry reachable — the runner resolves it itself — and every child's fetch
refused.

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
**Reader:** enforced. `test_a_private_host_leaves_the_external_apis_undecided` pins the
status and the reason for all three outside-world capabilities, and
`test_a_private_run_is_named_on_every_surface` pins the report. The two halves that were
unread — every test set `entry_private` by hand, and nothing held the denominator — are read
since 0.94.1 by `ThePrivateEntryIsObservedAndCostsCoverage`, against one real audit of a
loopback server: the flag and the fact are asserted to be different fields, and the weight
of the blocked items is required to still be inside `weight_applicable`.

That last assertion is the one the requirement is built around, and it had to be written
twice. The first version asserted only that coverage was under 100%, which stayed true when
the status was mutated to `N/A` — other items are undecided for their own reasons, so the
percentage alone cannot tell the two statuses apart. Probed 6 September 2026 by that
mutation: it reddens 22 sub-tests of the status assertion, and the denominator falls from
844 to 758, which is the flattering arithmetic stated as a number.

#### Scenario: a host only this machine can reach
- **WHEN** the audited host resolves to a private address
- **THEN** every item whose check needs an outside service — a measurement from another
  network, a reputation lookup, a property's history — reports `NO_DATA` with a reason
  naming the host
- **AND** the items that need only the page itself are left to answer for themselves

#### Scenario: an item whose question no outside service is in
- **WHEN** an item's script also asks outside services but the item reads only a request
  this audit made itself — TE-167, whether one request was answered below 500
- **THEN** the item answers on a private host like any check of the site, because the
  gate is for what needs the outside world, not for a script that also does (F06,
  `test_uptime_is_one_request_of_this_audit_and_is_answered_here`)
- **AND** that script names the private host to no outside service — no Safe Browsing
  lookup with a key set, no whois, no reverse-IP lookup — so answering the item does not undo what
  the gate kept from being asked (`test_a_private_host_is_named_to_no_third_party`)

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
- **AND** an entry that failed is asked as well: a staging host that answered 401 is
  where it resolves, whatever it answered. Until 0.153.0 it was not asked, the record
  said such a host was not private, and the report of that run said the host it audited
  was public — `test_the_run_that_was_refused_still_says_where_the_host_is`

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
**Reader:** enforced. Three real
subprocesses are asserted to space themselves; different hosts are asserted not to queue
behind each other; a stale slot, a corrupt slot, junk contents and an unwritable directory
are each asserted not to stop the run. The number was the gap until 0.94.1 — the one test
that looked like a reader asserts `max_rps()` equals `DEFAULT_MAX_RPS` after an unparseable
environment value, which reads the fallback, both sides moving together.
`TheDefaultRateIsANumberSomebodyChose` names 4.0 where changing the source reddens it, and
measures what the number means rather than restating it: the second request to one host
waits a quarter of a second. Probed by setting the constant to 40, which reddens both.

§5 keeps the *choice* of number outside this document, with whoever measures the cost of a
run. That is about who may change it, and is not an argument against a gate: a calibration
nobody can change by accident is what makes the choice somebody's rather than nobody's.

How a held slot is waited for is part of the rate, and on Windows it was wrong until
0.156.0, in the slow direction. The lock was the C runtime's blocking one, which sleeps a
whole second after an attempt that finds the region held and tries ten times. A process
that found the slot held came back after its turn had gone: three processes at five
requests a second proceeded 0.2 s and then 0.8 s apart, where the rate asks for 0.2 and
0.2. The test of shared state passed throughout, since it asks that no gap be shorter
than the interval. And the same lock guards the count of cache hits (HTTP-8), which is
held for microseconds: in an audit of the fixture tree on 6 October 2026, pacing on or
off, 36 to 47 of its 232 locks each cost a second. The lock is now asked for again every
few milliseconds, for the ten seconds the old one would wait, and a process that never
gets it paces alone as before. One audit of that tree took 52 to 54 s at the default rate
and 26 to 28 s after; with pacing off, 41 to 52 s and 23 to 24 s.

What `RateLimiting` holds of this is the mechanism, on Windows, with nothing timed: while
the lock is held the waiter asks again; the mode that sleeps a second is never passed to
the C runtime; each wait between attempts is the stated one, and that number is at most a
tenth of the default interval; a lock that is never released is given up on. The outcome —
what three processes that ask at once are told, and when they proceed — is measured and
not held. A test of it was written first, and with every core busy it was red in one
round of twelve with the limiter right, because a process that asks late is told to wait
for nothing too (INV-G8 of `openspec/specs/governance/`). Not held: on POSIX the lock is
`flock`, which the kernel waits for without a bound.

#### Scenario: a process finds the slot held
- **WHEN** a checker asks for the pacing slot while another holds it and waits out its
  interval
- **THEN** it is let in when the slot is released, with the rest of its own interval
  still to wait
- **AND** it is not put off by a sleep longer than the interval, which makes the
  machine's combined rate lower than the configured one and the audit longer for nothing

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
**Reader:** enforced. `test_a_disallowed_path_is_refused`
and `test_rules_naming_our_token_are_obeyed` pin the discovered half;
`test_an_absent_or_unreadable_robots_txt_allows` and
`test_a_fetch_that_raises_allows_rather_than_failing_the_audit` pin fail-open;
`test_robots_txt_is_fetched_once_per_origin_and_cached` pins the caching; and
`test_a_refusal_is_flagged_apart_from_a_failure` pins that a refusal is not a failure.

The asymmetry itself was unread until 0.94.1: the default that produces it was asserted
through the function's *signature*, which is a fact about Python rather than about what an
operator gets. `TheRobotsAsymmetryIsRead` audits a real server whose `robots.txt` says
`Disallow: /` and asserts the outcome — the entry page is fetched, the ordinary items are
decided from it, and the block arrives as `CI-005` at `critical`, a severity the previous
reader did not hold. A `critical` demoted to `medium` would still fail, still be reported,
and would sink under a dozen cosmetic findings in the fix list. The same URL is then
fetched with `respect_robots=True` against the same server and the same rule, so both
behaviours are held side by side rather than one being inferred from the other.

Probed 6 September 2026 by reversing the default, which produces the third scenario as a
measurement: 0 decided items against 15 undecided, and the entry page unreachable — the
collapse the requirement says an operator cannot tell from a crash.

**"Allows" had no single meaning until 0.109.0.** The politeness check went through
`urllib.robotparser`, and on 3.10.21 and 3.11.16 — two of CI's three interpreters — it
ignored `Disallow: /*?`, let the first matching line win instead of the longest, and could
not see an `Allow` exception inside a disallowed directory; 3.13.15 got all three right.
The evidence scripts used a second matcher with its own five defects. Both now delegate to
`lib/robots_rules.py` (RFC 9309: a crawler's own groups combined, `*` only as a fallback,
path and query, longest match, `allow` on a tie). `test_query_wildcard_is_stable_across_python_versions`,
`test_longer_disallow_beats_shorter_allow` and `test_longer_allow_beats_shorter_disallow`
go through `robots_allows`; probed 23 September 2026 by running them on 3.10 against the
0.108.0 tree, where all three fail and on 3.13 all three pass.
`test_scripts_do_not_import_the_version_dependent_parser` fails if any script imports that
parser again.

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

#### Scenario: the same file on another interpreter
- **WHEN** one `robots.txt` carrying `Disallow: /*?`, or an `Allow` longer than the
  `Disallow` it sits inside, is read by the audit on each Python version CI supports
- **THEN** every version refuses and permits the same URLs, because one matcher in this
  tree decides and the standard library's parser is not consulted

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
- **THEN** the matcher reads only the leading product token, which is the browser name
  at the front, and the site's rule for us is silently ignored while the wildcard applies
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

A run's cache SHALL be that run's alone. A run MUST NOT remove the cache of a living run
that holds its owner lock. What a dead run left SHALL be removed by the next run that
starts; a directory with no lock beside it — an older release's — only once nothing in it
was written within `CACHE_TTL`.

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

**The cache's life had no reader until 0.138.0, and no rule either.** The directory was
removed by `atexit`, so a run killed outright left it for good — with whatever the site
had answered in it (`inputs` INP-7, *a run that was killed*). A run now holds a lock file
beside its directory for as long as it lives, and every run begins by removing what it can
show to be dead. `test_runner.CacheOwnerLifetime` holds it with real processes: a child
ended by `os._exit` and the start after it
(`test_a_dead_run_leaves_neither_directory_nor_lock`), a living child whose bytes and held
lock a second start leaves alone (`test_a_live_run_keeps_its_bytes_and_its_held_lock`), a
removal the filesystem refuses — replaced and real
(`test_failed_removal_is_silent_keeps_the_lock_and_retries`,
`test_an_open_file_refuses_removal_keeps_the_lock_and_retries`), the lockless directories
of older releases by the age of their files, a directory already standing at the name
(`test_a_directory_collision_retires_only_the_sidecar`), and the names an owner loses
before it has made a directory. Probed 3 October 2026, thirteen mutations, each caught by
the test written for it (`local/cachelock/probe_0137.py`).

What is not held: the order in which the lock file is unlinked and released is the
platform's — on POSIX while the lock is held, on Windows after the descriptor is closed —
and the two tests that run the POSIX order against a real filesystem are skipped on
Windows, so they run only where CI is Linux or macOS. Two sweepers arriving at one dead
name together, and a sweeper killed halfway through a removal, are argued from that order
and run by no test.

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

#### Scenario: another run is alive
- **WHEN** a run starts while another run of this release holds its cache
- **THEN** the other run's directory, its bytes and its lock are as they were

#### Scenario: what a dead run left
- **WHEN** a run was killed, so that nothing it registered for its exit ran, and another
  run starts
- **THEN** the dead run's directory and its lock file are removed before the new run opens
  a cache of its own
- **AND** a lock file whose run died before it made a directory is removed the same way

#### Scenario: the removal is refused
- **WHEN** the filesystem refuses to remove a dead run's directory
- **THEN** the run goes on without a word, the lock file stays beside the directory, and
  the next run to start tries again

#### Scenario: a cache made by a release that took no lock
- **WHEN** a `seo-http-` directory has no lock file beside it
- **THEN** it is left while the directory itself or a file in it was written within
  `CACHE_TTL`, and removed once none was — whether or not its run is alive, because
  nothing on disk can say; that run fetches again and makes its directory anew

#### Scenario: a directory the run did not make
- **WHEN** a directory already stands at the name a run is about to take
- **THEN** the run takes another name and leaves no lock file beside that directory, so no
  later run removes it as a dead run's cache

#### Scenario: no name can be had
- **WHEN** every name the run tries is lost to another process
- **THEN** the run names no cache to its scripts — not an inherited one either — says so,
  and every script fetches for itself

#### Scenario: what is not a cache
- **WHEN** the temp directory holds a file or a directory whose name is not of this kind
- **THEN** it is not touched

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

The absence itself had been pinned rather than left to be rediscovered: the test holding it
was written to fail *at the moment the cache joined the list* and to say in its own message
that it should then be replaced. It did, on a full audit that answered 69 responses off
disk, and `test_the_reader_of_the_report_is_told_the_cache_answered` is what replaced it —
which is why that name no longer appears here. A document naming a test that no longer
exists is what `tests/test_specs.py::ADocumentNamesThingsThatExist` refuses, and it
refused this on the first full run after the replacement.

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
A walk over the sitemaps a site names — the crawl's, `sitemap_checker`'s and
`indexability_matrix`'s — SHALL stop requesting files at a byte budget, SHALL hold no more URLs than a URL budget, and SHALL say what it left unread or
unkept; and a compressed body SHALL be expanded no further than the protocol allows.

**Why:** a truncated body is a document with its footer missing, and every checker that
counts elements would answer confidently about a page that does not exist. The same is true
of a mis-decoded one: a page read as ISO-8859-1 has different text, different word counts
and different headings.
**Reader:** partial — the decompression limit is held only as a memory ceiling. A review of
0.172.0 (gpt-6.1-sol, 20 October) replaced the bounded read with `read(60_000_001)`, past the
protocol's 52,428,800, and every test stayed green: the gzip tests require the document invalid
and the peak under 150 MB, which a limit anywhere below about 150 MB also meets. Everything else
below is held. The cap raises rather than truncating, and a smaller cap is asserted to
cost a real refetch. The encoding recovery is covered thoroughly — fourteen tests over
header-versus-meta precedence, BOMs, XML declarations, commented-out metas, and a
declaration past the sniff window that is deliberately *not* read. Both defaults were unread
until 0.94.1, because every test supplied its own limit: `TheCapsAreTheOnesTheSubstrateShips`
names the ceiling and the budget, drives a body past the ceiling with no caller limit at
all, and exhausts the budget hop by hop — asserting in each case that the refusal states the
number it enforced, since a cap that refuses without saying what it was is the silent
truncation one step removed. Probed by setting both constants tenfold, which reddens the two
that name them. The walk budget is held by `tests/test_sitemap_walk_bounds.py` `SizeBudget`:
the crawl and `sitemap_checker` are each given an index of 60,000 URLs and of 36 MB, and
must keep no more than the URL budget, stop requesting files past the byte budget, and name
the cut (`cut` and `unvisited` in the crawl, `truncated_reason` in the checker);
`test_the_indexability_matrix_stops_reading_sitemaps_past_its_byte_budget` holds the third
walker. `test_the_byte_budget_counts_bytes_in_all_three_walkers` serves sitemaps of two-byte
text, whose bytes pass the budget while their characters do not, and requires each walker to
stop; `test_an_error_page_body_counts_against_the_byte_budget` gives the crawl 24 error pages
of 1.5 MB; `test_the_indexability_matrix_holds_no_more_sitemap_urls_than_its_budget` gives
the matrix 60,000 URLs. `TheMatrixSaysWhenItStopped` gives it eleven locations, exactly ten,
none answering, an index, a location refused and a sitemap on another host, and requires
membership `null` with the cause named for each unread case and `true`/`false` otherwise. `test_a_gzipped_sitemap_is_expanded_no_further_than_the_protocol_limit`
expands 200 MB of comment behind 0.9 MB on the wire and requires it returned invalid with
the memory peak under 150 MB (bounded: about 90; unbounded: about 400);
`test_a_gzipped_sitemap_is_not_decompressed_past_the_protocol_limit` reads the outcome only,
and stays green under an unbounded expansion.

**A walk has a budget, from 0.167.0.** One response was capped and a walk over many was
not: 25 sitemaps of up to 8 MB each were read and every `<loc>` kept, and the crawl's page
cap bounds pages fetched, not sitemap URLs held. A walk now stops reading new files once
`SITEMAP_BYTES_BUDGET` (20 MB) has been read and keeps at most `SITEMAP_URLS_BUDGET`
(50,000) URLs, one sitemap file's protocol maximum; `indexability_matrix` took the byte
budget in 0.168.0, and with files left unread it reports a URL's sitemap membership as
unknown rather than false.

**Bytes, and the matrix's URL budget, from 0.172.0.** The byte budget is counted in the
response body's bytes, `fetch_url`'s `bytes`, an error page's as well as a sitemap's: a body
sent with `Content-Encoding: gzip` counts decoded, a `.xml.gz` file served as it is counts
compressed, and its expansion is bounded by the protocol limit. Until then each walker added
the decoded text's length, which is characters — eight sitemaps of UTF-8 text read 48,001,761
bytes and counted 16,001,761, with no cut reported — and the crawl counted nothing for a
response that failed, so 24 error pages of 1.5 MB were read whole. A response that fails
part-way through its body — refused for passing its own 8 MB limit, or cut by the connection
— returns no body and counts nothing, whatever was read before it failed; the file cap (25 in
the crawl and the checker, 10 in the matrix) and the 8 MB limit are what bound those. `--sample`'s sitemap fallback is not
one of the walkers: it tries the conventional sitemap paths until one yields pages and follows
at most `SAMPLE_FALLBACK_SITEMAPS` (three) children of each index it reads, every response under
the ceiling, with no byte budget of its own; an index with more same-host children than that, a
child on another host or a child that could not be read marks the pool cut, and the sampled
verdicts it could decide are withheld (F11, `verdicts` VRD-14). `indexability_matrix` held every URL it read, and
now past `SITEMAP_URLS_BUDGET` reports membership as unknown (`null`), as past the byte
budget. No item reads `in_sitemap`.

**Every sitemap the matrix did not read, from 0.173.0** (F14). It reads at most ten sitemap
locations, and past the tenth, never requested, it reported `in_sitemap: false`; so it did for
an index, whose children it does not follow, for a location that gave no answer (refused by
this audit's guard, timed out, a 5xx or 429), and for a sitemap on another host. Each now makes
membership `null` on every row, and `sitemap_membership_unknown` names why, the budgets
included; it is `null` when membership is known. A location that answers 4xx, or a document
that is not a sitemap, lists nothing Google could read and stays an answer, so a site with no
sitemap at any location reads `false`. In the crawl and the
checker the URL budget bounds what is held, not what is requested: past it they go on reading
files, bounded by the byte budget and the file cap, so a broken or invalid sitemap past it is
still reported, and the URLs they list are counted as dropped. Stopping there would have
turned the checker's FAIL on such a file into a withheld verdict. A `.xml.gz` body is expanded to at most the protocol's 50 MB
(`SITEMAP_MAX_UNCOMPRESSED`), so 8 MB on the wire cannot become gigabytes in memory. The
stop is stated the way a cap is: what was cut is named, and the checker's result is
`truncated`, which withholds a clean verdict over it (`openspec/specs/verdicts/` VRD-14).

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

#### Scenario: a sitemap walk past its budget
- **WHEN** the sitemaps a site names hold more URLs than the URL budget, or more bytes than
  the byte budget
- **THEN** the walk keeps no more URLs than the URL budget, and requests no new file once the
  byte budget, counted in bytes, has been read
- **AND** what it cut is named in its result, rather than the part read standing for the set
- **AND** `indexability_matrix` reports membership as unknown and names the cut in
  `sitemap_membership_unknown`

#### Scenario: the matrix stops at its tenth sitemap
- **WHEN** a site names more than ten sitemap locations, or one the matrix does not read (an
  index, a location with no answer, a sitemap on another host)
- **THEN** `in_sitemap` is `null` on every row, not `false`, and the output names why
- **AND** with every location read, or none answering but 4xx, membership is `true` or `false`

#### Scenario: a compressed sitemap that expands past the protocol limit
- **WHEN** a gzipped sitemap decompresses past 50 MB
- **THEN** expansion stops there and the file is returned invalid, saying why

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

### Requirement: HTTP-13 — what the audited site names is not a licence to ask anyone else

A sitemap SHALL be requested only on the audited host — its `www.` variant and the other
scheme count as the same site, another port does not — and one named on another host,
whether by `robots.txt` or by a sitemap index, SHALL be listed and never requested. That holds
for every path that reads a sitemap: the three walkers and `--sample`'s own fallback. The
crawl and `sitemap_checker` SHALL name such sitemaps in `off_host_sitemaps`, and the
checker's result SHALL be `truncated` while it has any. A process held to the web ports
(`SEO_STANDARD_PORTS_ONLY`) SHALL refuse any port but 80 and 443 before the name is
resolved, for the entry URL, every redirect hop and every discovered URL alike, and the
refusal SHALL classify as `blocked`.

**Why:** the audit also runs behind a public web form, for anyone, so the audited site and
everything its `robots.txt` and sitemaps say is a stranger's input. A sitemap fetched on any
public host and port made the audit a GET proxy aimed wherever a site pointed it; a page
linking to `host:8443` had the engine connect there and report the status, a port prober
running from the operator's address. Google accepts a sitemap declared on another host, so
an unread one is not a defect, and a checker that said "No sitemap found" for it, or passed
a clean set over it, would be reporting the part it read as the whole. The port rule sits in
the guard because the guard is the one place every request passes: a same-host rule on
redirects would not have closed it, since a page can link to the port directly.
**Reader:** partial — one clause is held on fewer paths than it names. The `www.` variant
is held as the same site only for the crawl: a checker changed to refuse it leaves every
`OffHostSitemaps` test green. The rest is held. `tests/test_port_refusal_census.py` holds the
`blocked` clause on every path a script reaches: `ThePageItselfIsRefused` runs every job the
registry plans with its page on another port and requires each row it feeds to be `NO_DATA`,
never `unread` or `crash` and, where the script failed, `blocked` under its label;
`AFurtherURLIsRefused` serves the page and refuses every further URL — the key file, the
favicon, the stylesheet, robots.txt, llms.txt, the sitemaps — and requires that no item be
decided by the refusal; `PartsTheCensusDoesNotReach` holds one file refused among several read;
`FoundByTheReviewOf0173` the paths the census page cannot show — a page read and its HEAD
refused, robots.txt read and the paths behind it refused, a facet URL, a font, a crawled page
and a whole crawl refused, the timing request refused after the page was read, a key file
behind a private address that still fails; `TheRunnersOwnRequests` the entry's kind in the
artifact and `--sample`'s fallback. `tests/test_sitemap_walk_bounds.py` `OffHostSitemaps` hands each of
the three walkers sitemaps on other hosts and ports and requires that none is requested:
the crawl lists them in `off_host_sitemaps` and keeps only the audited host's URLs, the
`www.` variant and the other scheme are requested as the same site, and `sitemap_checker`
lists one named by `robots.txt` or by an index, does not say "No sitemap found", and is
`truncated` naming it; `test_another_port_on_the_audited_host_is_another_host` holds the
port clause for the crawl and the checker, and
`test_the_sample_fallback_requests_no_index_child_off_the_audited_host` the fallback, both
what it requests and the stderr line naming what it refused.
`test_evidence_apis.SitemapReconciliation.test_a_walk_cut_by_its_budget_or_by_host_withholds_the_reverse_direction`
reads what GO-137 does with such a walk. `test_safe_http.TheWebDeploymentReachesOnlyTheWebPorts`
holds the switch in four directions: another port is refused with no lookup made and
classifies as `blocked`, a redirect to another port is not followed, both web ports are
fetched whether named or not, and with the switch off any port is fetched.
`test_tls_certificate.APortRefusalIsBlocked` holds the one script with a socket of its own,
through the runner.

**Two paths it missed, until 0.172.0** (F13, found by an independent review of F10). With no
crawl, `--sample` reads the conventional sitemap paths itself and requested up to three of an
index's children on any host and port; it now refuses the ones off the host and names them on
stderr. And `tls_certificate.py` kept the guard's refusal as text and dropped its kind, so the
runner recorded a port refusal as `crash`; it now carries `blocked` (`unresolved` for a name
with no address). The Reader line above had said `enforced` over both, and over the port
clause, which no test read.

**Every refused path, from 0.173.0** (F14, found by the review of 0.172.0). The guard
classified the refusal as `blocked` and the scripts lost it: twenty-six reported it as a
`fetch_error`, which the runner records as `unread`; eight wrote `unread` themselves; three
recorded `crash`; and where the refused URL was a file a script grades, the refusal became a
verdict — GEO-007 failed on an IndexNow key "not found", MB-104 on a favicon "unreachable",
TE-174 went N/A over a stylesheet it never read, TECH-002 warned "Stylesheet could not be
fetched", CI-005 and CI-001 passed on a robots.txt read as allowing everything, TE-167 failed
the site as down. Each now carries the kind, or leaves its item undecided with the cause.
A census found them, by running every planned job with the switch on; the two scripts the
review named were two of thirty-nine. The review of this release's first build found the paths
that page could not show — a page read and its HEAD refused, robots.txt read and the paths behind
it refused, one crawled page refused, a whole crawl refused — and a key file behind a private
address excused with the port's refusal; each is held now. Its second pass found a favicon's own
defect withheld behind a refused robots.txt and a matrix batch failing CI-001 on a refused row;
both held too.

**Not held, and said here so that it is not found again as a surprise.** A sitemap on the
audited host that redirects elsewhere is still followed, as every fetch follows a redirect,
each hop through the guard (HTTP-1); the site can make the audit request a public URL that
way. With the switch set, requests to other public sites on the web ports remain, because
checking outbound links means making them. The switch is off by default, so an operator
auditing a staging site on `:8080` by hand is not refused; a public deployment sets it.
`indexability_matrix` names an off-host sitemap only in `sitemap_membership_unknown`, and no
item reads it; `--sample`'s fallback names one on stderr only. A page the guard refused leaves
the crawl `truncated`, so the site-wide items withhold their clean verdict; a page that timed
out does not, and is a partial crawl rather than a refusal's kind. `domain_safety_check` reads
several subjects in one result, so its refused uptime request is NO_DATA by an absent key
rather than `blocked`, and `security_headers` names `blocked` on its refused http variant's row
while SE-117 is NO_DATA the same way: the runner keeps one kind per result. Run by hand only,
and not held: `parse_html.py --fetch`, `detect_profile.py` with a URL,
`canonical_checker.py --check-targets`.

#### Scenario: a sitemap named on another host
- **WHEN** `robots.txt` or a sitemap index names a sitemap on another host or port
- **THEN** it is not requested, and the crawl and the checker list it in `off_host_sitemaps`
- **AND** the checker does not say no sitemap was found, and its clean verdict is withheld

#### Scenario: the same site under another name
- **WHEN** a sitemap sits on the `www.` variant of the audited host, or under the other
  scheme
- **THEN** it is requested as the audited site's own

#### Scenario: a process held to the web ports
- **WHEN** `SEO_STANDARD_PORTS_ONLY` is set and a URL, a redirect hop or a discovered link
  names a port other than 80 or 443
- **THEN** the request is refused before the name is resolved, and the failure is `blocked`
- **AND** a link refused this way is reported unchecked, not broken (HTTP-9)
- **AND** a page or a file a script reads refused this way leaves the item it decides
  `NO_DATA` with the kind `blocked`, or withholds a clean verdict over the part read, and is
  never the site's defect or a clean answer

#### Scenario: the switch is off
- **WHEN** `SEO_STANDARD_PORTS_ONLY` is not set
- **THEN** a URL on any port is requested, through the guard as before

## 4. Invariants

* **INV-H1** — every script that can open a connection goes through the guard.
  *Reader: partial* — an AST census asserts that every script importing a networking module
  also imports the guard, with three written exemptions and a test that the exemptions are
  not stale. It asserts imports, not use: a script could import the guard and call
  `requests` directly.
* **INV-H2** — a cached response is byte-identical to the response it replaced.
  *Reader: enforced* — seven fields plus the header mapping and the redirect chain are
  compared between a live and a restored response.
* **INV-H3** — the audit makes no request to a URL the operator or the site supplied that the
  guard did not validate, including redirects (the fixed services HTTP-1 names are outside it).
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

Six rows were measured by mutation and the rest were derived from a census of what each
test body asserts. The distinction is stated because it is the difference between a
classification and a guess, and this suite has been wrong four times in the guessing
direction.

**Probed:** HTTP-1 — replacing the pinned adapter with a plain one fails six of the nine
guard tests. HTTP-7 — making a cache hit skip the robots re-check fails one test, which is
the clause the Reader line singles out. HTTP-11 — turning the unconditional `verify = True`
into a `setdefault`, so a caller may relax it, left 319 tests green when this was written
and reddens two of its four readers now. HTTP-8 — as of 5 September 2026 the recording is read in both directions and the
provenance omission is pinned as an absence; before that, the string
`http_cache` appears nowhere under `tests/`. HTTP-10 and HTTP-13, and HTTP-1's own-socket
half (20 October 2026, F13): the clauses F13 changed, broken in turn — a walker counting characters, the
matrix holding every URL, the crawl skipping an error page's bytes, an unbounded expansion, a port read as the same host, the sample
fallback following any host or not naming what it refused, the TLS refusal's kind dropped, a second TLS pass resolving the
name, the address sent as SNI — and each reddens the test the Reader line names.

**Derived, not probed:** nothing now. Every row above was probed by mutation before it
was moved, which is the method this appendix distinguishes from a guess, and the guessing
direction had been wrong four times. Each names which half it believes is
unread; that half was established by reading the asserting test's body and by greps for the
absences, not by breaking the code. A `partial` that is really an `enforced` or a `none` is
the error this method leaves open, and the halves are where to look first.

| | requirements |
|---|---|
| **enforced** | HTTP-1, HTTP-2, HTTP-3, HTTP-4, HTTP-5, HTTP-6, HTTP-7, HTTP-8, HTTP-9, HTTP-11, HTTP-12 |
| **partial** | HTTP-10, HTTP-13 |
| **none** | — none |
| **opposed** | — none |

Invariants: INV-H2 and INV-H3 enforced; INV-H1 and INV-H4 partial.

**Eleven enforced, two partial, nothing unread, of thirteen.** HTTP-10 and HTTP-13 moved to
`partial` in 0.172.0: the review of that release mutated three clauses their Reader lines called
held — the decompression limit raised past the protocol's, `www.` refused by the checker, a port
refusal reported as something other than `blocked` by two scripts — and no test went red.

HTTP-13 joined on 20 October 2026 (F10), written for behaviour 0.167.0 and 0.168.0 had
shipped with its tests and without a requirement: what a site's own word may make the
audit request. It entered `enforced` because each clause was already held by a test seen
red on the code before it, not by a probe run for this document — and that was wrong in three
places, found by an independent review and probed by mutation in F13 (0.172.0): two paths
requested what the requirement forbids, and the port clause had no reader. HTTP-1 and HTTP-10
had the same defect from the same release: a claim written as held where the test stayed
green under the violation.

Closed on 6 September 2026, and the shape of what was left is worth recording. Nine of the
ten `partial` rows were not missing tests of their mechanisms — those were thorough. What
was missing, every time, was one of three things: a *number* nothing named (the rate, the
two caps), a *fact recorded and never carried* to the person reading the report (the parser,
the cache), or an *asymmetry asserted through a signature* rather than through the outcome
it produces (robots, the private allowance). Only HTTP-1 was an actual hole in the code,
and it was the one nobody had probed.

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
