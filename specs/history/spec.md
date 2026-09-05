# History — what two runs of the same site may be said to show

**Capability:** the stored record of past runs, the comparison between the current run and
its predecessor, and the trend across a series (C36 of the capability inventory).

This document is normative and is written as though no code existed. Where the
implementation disagrees, the implementation is presumed wrong until this document is
changed by argument. Appendix A records disagreements measured on 4 September 2026.

Every requirement carries a **Reader** line naming what makes it fail when violated;
Appendix B is the census of those lines. A requirement whose reader is `none` is an
intention, and is counted as one.

**Inherited, not restated:** the statuses belong to
[`specs/verdicts/`](../verdicts/spec.md); the score two runs are compared on belongs to
[`specs/scoring/`](../scoring/spec.md); what a report may show belongs to
[`specs/reporting/`](../reporting/spec.md), which owns the trend section this document
supplies. This document says what a comparison *means*.

---

## 1. The claim a second run makes

One audit describes a site. Two audits describe a site *and* an interval, and the second
claim is the one clients act on: it went up, that item is fixed, this has been broken since
March.

Every one of those sentences is a claim about the world that the tool is not in a position
to make. What it actually knows is that a number it computed in March differs from a number
it computed today. Between the two, the site may have changed — or the registry gained
eight items, or a credential expired, or the operator ran it in a different mode, or a
third-party service was down for ten minutes. Each of those moves the number, and none of
them is the site getting better or worse.

So this document is mostly a list of things a comparison must refuse to say. The dangerous
direction is uniform: every unstated difference makes the tool sound more confident than it
is, and the sentence a client repeats — "our SEO score went from 72 to 96" — is the one with
the fewest caveats attached.

The single most consequential rule is the three-way split in §3's RUN of change classes. A
`PASS` that becomes `NO_DATA` is not a regression. Filing it as one tells a client their
site broke when what broke was the measurement; filing its reverse as an improvement takes
credit for a fix nobody made. The code says this, in an unusually clear comment. Nothing
tests it (Appendix A.1).

## 2. What is stored and where

A run writes one JSON file per audit under a directory keyed by the site's domain, named by
timestamp. The series a trend is computed from is the most recent twelve, and the current
run is excluded from the series used to compute how long something has been open.

The payload of every run carries: the comparison against its predecessor, which run that
predecessor was, the series, and for each still-failing item how long it has been failing.

`--no-history` stops the writing. `--diff` controls only whether the comparison is
*printed* — the comparison happens either way, because the payload carries it.

## 3. Requirements

### HST-1 — a status change is classified as improvement, regression, or loss of evidence

Three classes, not two. A change between two quality verdicts is an improvement or a
regression. A change where either side is not a quality verdict — `PASS` to `NO_DATA`,
`NEEDS_INPUT` to `WARN` — is neither: it is a change in what the audit could see.

**Why:** the two-class version is wrong in both directions and wrong in the expensive way.
`PASS → NO_DATA` reported as a regression tells a client their site broke when a service
was down. `NO_DATA → PASS` reported as an improvement takes credit for a fix nobody made,
and the client learns that the number moves on its own.
**Reader:** enforced. `test_every_pair_of_statuses_is_classified_by_the_rule` sweeps all
sixty-four ordered pairs of the eight statuses, taking the vocabulary from the report's own
`STATUS_ORDER` so a ninth is swept the day it is added, and judging each against a scale
written from this requirement rather than imported from the code. Widening `VERDICT_RANK`
by one entry — putting `NO_DATA` on the quality scale, which is how this breaks — reddens
it six ways, including the two harms named above; `test_losing_the_measurement_is_not_the
_site_getting_worse` and `test_regaining_the_measurement_is_not_a_fix` name them separately
so a failure says which. `test_the_caller_never_asks_about_an_unchanged_status` pins the
`diff_runs` guard that keeps `direction(PASS, PASS)` — which answers `regressed` —
unreachable.

Until 5 September 2026 this read `none`, and correctly: the classifier was called by no
test function, and the renderer tests that appeared to cover it supplied the classification
as fixture data — asserting that a change *labelled* `improved` renders as an improvement,
which reads the renderer and not the rule.

### HST-2 — a comparison across a changed registry says so

Where the two runs were computed over different registry versions, the comparison warns.
The same holds for a change of profile or of mode.

**Why:** the score is a fraction of the registry, so a registry that gained eight items
moves it without the site moving. A profile change moves the denominator; a mode change
moves what could be answered at all. All three produce a number that looks like news.
**Reader:** partial. Four test functions cover the comparison, and two of them pin warnings
directly — that a changed registry version warns, and that a barely-overlapping pair of
runs warns. The profile and mode halves have no test.

### HST-3 — the baseline is named

A comparison states which run it is against, by identity rather than by "the last one".

**Why:** "since the previous audit" is ambiguous the moment two audits happen on one day,
or a run is deleted, or the operator has two machines. A reader who cannot identify the
baseline cannot check the claim.
**Reader:** partial. Three test functions cover the recorded baseline, including that a
report with no baseline prints no trend section and that neither renderer prints a missing
number. That the baseline is *named* where the comparison is shown is asserted for the
absence case and not the presence case.

### HST-4 — the current run is not part of its own history

The series a trend is computed from, and the streak that says how long an item has been
failing, exclude the run being reported.

**Why:** including it makes every first run a one-run trend and shifts every streak by one.
The error is small, constant, and invisible — which is why it needs a rule rather than
care.
**Reader:** enforced. `test_the_current_run_is_excluded` and
`test_the_current_run_is_excluded_by_name` pin it from two directions — by content and by
filename — and nine test functions cover the series construction, including that it is
ordered by the timestamp inside the file rather than by the name.

### HST-5 — a streak counts consecutive failures and breaks when the item passed

"Open since" is the length of the current unbroken run of failures. An item that failed,
was fixed, and broke again is not described as having been broken the whole time.

**Why:** this is the number that goes in the sentence "this has been broken since March",
and the version that ignores the fix in between is a false statement about the client's own
work.
**Reader:** enforced. Three test functions pin the arithmetic, including the fixed-and-broke-
again case and that an item passing now is not listed at all.

### HST-6 — history is per site, and two runs in one second do not collide

Runs are stored under the site they describe, and two runs that start within the same clock
tick get separate files.

**Why:** a collision loses an audit silently. A shared directory across sites would compare
one client's run against another's, which is worse than losing it.
**Reader:** partial. `test_two_runs_in_one_stamp_do_not_share_a_file` pins the collision
case. The per-site keying is exercised by every test that writes history and asserted by
none.

### HST-7 — a corrupt stored run is skipped, never fatal

A history file that cannot be read is ignored, and the run continues.

**Why:** an audit that dies because a file from three months ago is truncated has made an
old accident into a current outage. The comparison is a convenience; the audit is the
product.
**Reader:** enforced. `test_a_corrupt_history_file_is_skipped_not_fatal` pins it, and
`test_the_newest_run_wins_regardless_of_filename_format` pins that selection does not depend
on a naming convention.

### HST-8 — printing the comparison is optional; computing it is not

The payload carries the comparison whether or not the operator asked to see it.

**Why:** the artifact is what a later run and a later reader work from. A comparison that
exists only when a flag was passed makes the record depend on how somebody invoked the tool
that day.
**Reader:** enforced. `test_the_payload_carries_the_comparison_though_nobody_asked_to_see_it`
audits one served fixture twice without `--diff`, and asserts that the first run records no
comparison, that the second records one naming the first run's `started_at`, and that
nothing about it was printed. Making the comparison conditional on the flag reddens it.

It is skipped on Windows, which is a defect in the tree rather than a weakness in the
requirement, and writing this test is what found it: `history_path` files a run under
`os.getcwd()/.seo-runs/<netloc>` with the netloc used verbatim, so a fixture served on
`127.0.0.1:<port>` produces a directory name containing a colon, and Windows raises
`NotADirectoryError` **after the audit has finished** — losing the whole run. Recorded as
`a-run-under-a-ported-host-cannot-be-filed-on-windows`, with a probe. The reason it went
unseen is the reason this requirement went unread: **every invocation of the runner in this
suite and in CI passes `--no-history`**, all six in `ci.yml`, so the history subsystem this
document is about has never run end to end in CI on any platform.

## 4. Invariants

* **INV-HS1** — a run compares against a run of the same site. *Reader:* **none.** The
  directory keying makes it true; nothing asserts it.
* **INV-HS2** — the series is ordered by when each run happened, not by filename.
  *Reader: enforced* — asserted directly, and separately for the newest-run selection.
* **INV-HS3** — every item in the comparison exists in both runs, or is reported as added or
  removed rather than as changed. *Reader: partial* — the barely-overlapping case warns;
  nothing asserts the per-item treatment.
* **INV-HS4** — no stored run is modified after it is written. *Reader:* **none.** Nothing
  writes to an existing history file, and nothing forbids it.

## 5. What this document does not decide

* how the score being compared is computed — `specs/scoring/`;
* how the trend is displayed, or the wording of the section —
  `specs/reporting/`, which owns the surface;
* what a status means — `specs/verdicts/`;
* how long history should be kept, or how large the series should be. This document
  requires the series to exclude the current run and be ordered by time; twelve is
  calibration.

## 6. Open questions

**Should a loss of evidence be visible in the score, or only in the comparison?** HST-1
keeps `PASS → NO_DATA` out of the regression class, which is right for the sentence a client
reads. But the score does fall, because an item that cannot be answered leaves the scored
set — so the number goes down while the comparison says nothing got worse. Both are correct
and together they read as a contradiction. What would settle it: whether the trend section
should state the coverage change beside the score change, which is
`specs/reporting/` REP-8's territory and unread there too.

**What is the identity of a run?** HST-3 requires the baseline to be named, and today a run
is identified by its timestamp and the domain directory it sits in. Two audits of the same
site in different modes, or under different profiles, are different measurements sharing an
identity. HST-2 warns when they are compared; nothing prevents the second overwriting the
first as "the previous run". What would settle it: whether mode and profile belong in the
stored run's identity rather than in a warning about it.

## Appendix A — measured disagreements, 4 September 2026

Observation, not specification. Measured at commit `64d2ddc`, by parsing all 1 280 test
functions and asking which bodies name each symbol.

### A.1 — the classifier that decides what a client is told is called by no test

`direction()` turns a pair of statuses into `improved`, `regressed` or `evidence`. Searching
every test function for a call to it returns nothing. The single grep hit is a test *name*
that contains the word "direction" and is about a certificate check.

What looks like coverage is not. `tests/test_report.py` builds change records by hand —
`self._change("CN-047", FAIL, PASS, "improved")` — and asserts that a change already
labelled `improved` renders as one. That reads the renderer. The rule that produces the
label has no reader at all, and `VERDICT_RANK`, the table it consults, is named by no test
either.

So the classification a client's report rests on — your site got worse, versus we could not
tell this time — is defined only by code, and the code is unusually explicit about why it
matters:

> `PASS` becoming `NO_DATA` is not the site getting worse — it is the run losing the
> ability to tell … Filing that under "regressed" would make a client's report say their
> site broke when what broke was the measurement.

A comment that argues its case that clearly is a rule somebody thought hard about. Nothing
holds it. This is the gap the capability inventory recorded as G11, and the measurement adds
the sharpest form of it: the two-class regression the comment warns against would pass the
whole suite.

### A.2 — the parts of history that are well read are the mechanical ones

| symbol | test functions |
|---|---:|
| `run_series` | 9 |
| `previous_run` | 5 |
| `diff_runs` | 4 |
| `open_since` | 3 |
| `compared_with` | 3 |
| `history_path` | 1 |
| `HISTORY_RUNS` | 1 |
| `direction()` | **0** |
| `VERDICT_RANK` | **0** |
| `--diff` | **0** |

The distribution is the finding. Reading files, ordering them, excluding the current one,
surviving a corrupt one, counting a streak — all well covered, some from two directions.
What is uncovered is the one function that turns two statuses into a sentence about the
client's site.

That is the same shape three other documents in this suite have now recorded from their own
side: the machinery is tested and the *judgement* it feeds is not. Here the judgement is a
single function with a three-line body.

## Appendix B — how much of this document is enforced

**Probed:** HST-1 by mutation, 5 September 2026 — `NO_DATA` added to `VERDICT_RANK`, which
reddens the sweep six ways. The other rows were derived by parsing the test functions and
reading the bodies that name each symbol, then reading the implementation; the executor
that had been running mutation probes for this suite ran out of credits before it reached
them.

| | requirements |
|---|---|
| **enforced** | HST-1, HST-4, HST-5, HST-7, HST-8 |
| **partial** | HST-2, HST-3, HST-6 |
| **none** | — none |
| **opposed** | — none |

Invariants: INV-HS2 enforced; INV-HS3 partial; INV-HS1 and INV-HS4 unread.

**Five enforced, three partial, nothing unread, of eight.**

The enforced requirements were all about *files*: exclude this one, skip that broken one,
count the run of them. The unread ones were about *meaning*: what a change is, and whether
the record exists when nobody asked to see it. That is the same line `specs/inputs/` found
between files and policies, and this document was the smallest and clearest instance of it
— eight requirements, one function at the centre, and the function was the unread one.

It was also the cheapest gap in the suite, and it was closed on 5 September 2026 by the
test this appendix described: `direction()` takes two strings and returns one of three, so
the reader is a table of pairs — sixty-four of them, since the vocabulary is eight statuses
wide and the interesting cases are exactly the ones a smaller table would omit. That it did
not exist for fifty-five releases stands as the most direct evidence available that this
suite's coverage followed what was easy to reach from a fixture rather than what a wrong
answer costs.

HST-8 went the same day and cost more than it looked. Reading it needs two real runs
against one host, which is the one thing nothing in this repository had ever done: all six
runner invocations in `ci.yml` pass `--no-history`, so the subsystem this document
specifies had never executed end to end under any gate. The first attempt to run it did not
fail an assertion — it crashed, in `history_path`, on a directory named after a netloc with
a port in it, which Windows will not create. Eighteen releases of a defect that destroys a
finished audit, standing behind a flag every test passed.

That is the same shape as HST-1 seen from the other side. HST-1 was unread because the
function was never called; HST-8 was unread because the *path* was never taken. Both look
identical from a green suite, and both were found by asking what a requirement would need
in order to be read at all — which is the question a census of readers answers and a count
of tests does not.
