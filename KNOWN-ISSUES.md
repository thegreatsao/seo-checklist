# Known issues

What is wrong with this plugin as of **0.90.1**, ranked by consequence, with the
evidence for each. Nothing here is a suspicion: every entry was measured against
the tree.

That last sentence was true when each entry was written and stopped being true three
times without anyone noticing, because a release that repairs a defect has no reason to
open this file. Section 6 therefore carries a marker per entry, and
`tests/known-issues.json` records against each marker what the entry claims and — where
the claim can be re-run — a probe that re-runs it.
`python tests/known_issues.py --check` executes every probe and
fails when the tree stops answering what its entry says it answers. Thirty-two of the
forty-nine entries carry a probe; the other seventeen carry a written reason for having
none, and that count is printed, because a ledger where everything is exempt is a
ledger that has stopped working.

**The count in that sentence is the one thing here a probe cannot check**, and it was
wrong by one release for as long as this header said 0.80.0. Both numbers now come from
`python tests/known_issues.py`, which prints them.

This file exists because the audit's one promise — that "we could not check this"
never reads as a verdict — applies to the plugin's own description of itself. A
defect known and unwritten is the same failure one level up.

**Measured on 2026-08-16, and it is the reason the list above stopped growing one
entry at a time.** Three releases that day each removed a verdict that lied on a real
site, and not one of the four defects was caught by the 935-test suite: `CN-057`'s
false PASS needed `Article` markup neither fixture tree carries, the `author-grid`
false byline needed a class no fixture uses, `MB-105`'s machine dependence showed only
on a live site, and `MD-184`'s unreachable FAIL came out of a hand-run over six pages.
All four were found outside the oracle, because the oracle is two trees written to make
these checks fire, and a check written for a fixture and a fixture written for a check
confirm each other and say nothing about the rest of the web.

`tests/verdict_census.py` answers the cheap half of that. It serves every tree this
repository can serve — the four fixture origins, with every operator artifact staged as
the oracle stages them — and records what all 217 items answered, into
`tests/census.json`. It is a measurement, not an oracle: it cannot say which answer was
right, only which answers were ever given. The first reading, over the fixtures alone:

| | count | what it means |
|---|---|---|
| answered somewhere, never FAIL | 33 | a rule that cannot fail, or a case the fixtures do not have |
| answered somewhere, never PASS | 9 | the mirror of the same question |
| never answered anywhere | 30 | mostly honest — Search Console, PageSpeed and Safe Browsing cannot answer offline |

**Telling the two halves of the first row apart is the work, and it is now a closed
list rather than an open hunt.** Two examples from that first reading, both settled by
hand: `MD-184` is a rule that cannot fail — `image_inventory.py` omits `count` on a page
with no images, so the item is PASS or NO_DATA and never anything else. `MS-020` is the
opposite — `len_lte: 60` fails happily on an over-long title, and neither fixture tree
has one. The first is a defect in the registry; the second is a gap in the corpus, and
the corpus is what the census exists to justify building.

**`tests/corpus/failing-shapes/` is the second half of that instrument**, and it settles
the distinction by construction rather than by argument: a tree built to fail as many
items as a static server can express. Whatever starts failing was a corpus gap; whatever
does not is a candidate for the `MD-184` class. Its first reading moved four items —
`MS-020`, `AR-155`, `CI-013` and `TECH-001` — out of the never-failing column and left
seventeen it was aimed at still standing. **Each of those seventeen is now a specific
question rather than a suspicion**, which is the return on the exercise.

Two are already answered, and both are worth reading before the rest:

- **`TECH-002` is fixed in 0.54.0: `font_audit.py` now reads the stylesheets it
  links.** The 0.50.0 repair graded `@font-face` with no `font-display` as `error` but
  left that branch reachable only for inline `<style>` blocks; an external declaration
  still produced no finding and PASS. The script now fetches every linked stylesheet
  through the shared response cache, sends its faces through the same branch as inline
  faces, and names the stylesheet URL on each finding. A file that cannot be read adds
  a `warning` with the URL and reason instead of looking clean. Re-running the same
  three-page measurement gives FAIL for an external blocking face, FAIL for the inline
  face, and PASS for external `font-display: swap`; the corpus census moved only
  `TECH-002` on `failing-shapes`, and the never-FAIL count fell from 29 to 28.
- **`AR-155` fails where `AR-147` and `CI-012` pass, on the same URL through the same
  script.** `/Category_Page/Item_One_FINAL.html` raises `url_quality` flags — enough for
  `AR-155`'s `flags len_eq 0` — while leaving `score >= 70` satisfied for the other two.
  A score that stays passing on a URL its own flags condemn is a question about the
  score, not about the URL.

And one thing the same reading taught at the cost of a census round: **a tree of
deliberate defects can hide its own defects from itself.** The `@font-face` first lived
in `/assets/site.css`, which this tree's own `robots.txt` disallows for `CI-013`, so
nothing looked at the font at all. Moving the stylesheet to the root and re-running is
what turned a guess about `robots.txt` into a finding about the script.

**Measured in 0.18.0, and the answer is uncomfortable.** `measured` is still 0 and that
is the honest count: what `tools/audit_score_sensitivity.py` measured is not the weight
table but the consequence of it being wrong. Re-scored across four real runs from flat
1/1/1/1 to steep 27/9/3/1, the headline moves 0.2, 1.9, 9.3 and **14.6** points. So the
table cannot be written off as decoration, and the driver is not how many items were
decided — it is how far the per-severity pass rates spread, which means the score is
most sensitive to an unexamined number on exactly the sites where severity
discriminates. `EFFORT_COST` came out the other way: dividing by effort changes 2-4 of
the first ten fixes and so earns its place, while the exact ratio does not — 1/2/3 gives
the identical first ten on every run measured.

**Fixed in 0.16.0**: the report's own arithmetic. `Coverage %` added together three
quantities that measure different things — how far the tool reached, how much work the
operator had done, and how much of the checklist was never the audit's job — and then
moved for any of the three without saying which, which is this file's founding
objection applied to the number this file's project reports. It is replaced by the
score's weight share and a partition of the registry that has to add up. `NEEDS_INPUT`
split out of `NO_DATA` on the way, because a partition reconstructed by matching prose
inside an evidence string is a coupling that breaks in silence. Two defects fell out of
the change: the HTML history section had been printing `coverage None%` with no test
over it, and a shared string would not have parsed on the declared 3.10 floor.

**Fixed in 0.15.0**: four of the five open items. The answer-block score no longer
depends on whether a page closes its tags — and the sibling walk that caused it was
hiding a second defect that needed no invalid markup at all. Every number a verdict
rests on now carries a stated basis, which moved `inherited` from 14 to 75 and turned
up two thresholds written twice. `--verify-bots` confirms a crawler by reverse-then-
forward DNS and takes a forged one out of the crawl-budget figures. A supplied
measurement's age is shown and can be bounded. And the Russian report's caveat block —
19 strings, not the six this file claimed — is translated.

**Fixed in 0.14.0**: the HTML parser was chosen by import order, so one machine could
parse a page two ways and two scripts inside one audit could disagree — measured,
decided, recorded in the artifact and overridable. Four of the five site shapes in issue
3 are now exercised live, TLS included. And an evidence script killed by the operating
system no longer reports as a script that failed.

**Fixed in 0.12.0**: issues 4 and 5 — the report says what changed since the previous
audit, and `--fixes` writes the actionable items where a tracker can read them. Both were
data the audit already had and did not hand over.

**Fixed in 0.11.0**: nothing on this list; CI-018 stopped being `manual` and became the
first item answered from a server log. On the way, a robots-refused URL reported as a page
nobody crawled — the 0.4.0 orphan bug written a second time in a new script — and a
robots.txt token counted as a search crawler because of a substring.

**Fixed in 0.10.0**: the rest of issue 1 — a run-scoped response cache means one fetch
per URL, and the fixture audit went from 76 requests to 16 with all 214 verdicts
unchanged. It also made a duplication visible that nothing could count before: two
spellings of one `Accept` header, from the two conventions in this tree, had been
fetching every audited page twice.

**Fixed in 0.9.0**: the crawling half of issue 1 — six independent crawls became one
shared one, and the report finally names the broken URLs instead of counting them. On
the way: twelve more items that graded a site which answered nothing (including three
`critical` ones, invisible to the previous release's sweep because that sweep's script
list was hand-maintained), an item that could not fail and its twin that accused every
site, and five checks that reported a defect in every correct site on the internet.

**Fixed in 0.8.0**: issue 2 below, which was the largest open item after the shared
crawl — every one of the 55 evidence scripts now has a unit test. Writing them found
sixty-two items that graded a site which answered nothing, five more that could not
produce the verdict they claimed, and seven that reported a defect in the site when a
third party was unavailable.

**Fixed in 0.7.0**: the four defects that used to be §6's first four bullets — the
`<picture>` blind spot that failed sites for following the recommendation, a
shape-probing tool that had drifted from the registry it verifies, an undeclared
Python floor, and a linter that never ran — plus an artifact being trusted without
being asked which page it describes.

**Fixed in 0.5.0**, below the line: eighteen items — five of them `critical` —
that were reporting a verdict nothing could have produced, and the two audits that
now stop that family recurring.

**Fixed in 0.4.0**: the SSRF guard having no escape hatch (and with
it, the absence of any live-path test), an address being given a registrable domain,
external-API checks crashing instead of reporting `NO_DATA` on a private host, a
robots-disallowed sitemap URL counted as an orphan, and the report never saying when
it was describing something other than the public site.

**Fixed in 0.3.0**: `--sample` taking the first N sitemap URLs, the report's two
incompatible scales, the crawlers ignoring `robots.txt`, and `broken_links.py`
having no cap.

---

## 1. Closed in 0.10.0 — one fetch per URL

Kept at the top because the shape of it is the useful part, not the fix.

An audit used to ask a seven-page site the same question 37 times. Nothing was written
badly to make that happen: 36 evidence scripts each need the page they are judging,
each runs in its own process, and nothing connected them. It closed in two halves,
because it was two problems wearing one number.

**The site-wide half (0.9.0).** Six scripts walked the same pages independently — 50
pages each for `duplicate_content.py`, `link_profile.py` and `internal_links.py`, 100
for `orphan_pages_from_sitemap.py`, 25 for `anchor_text_audit.py`, and one page's links
for `broken_links.py` — each with its own budget, its own robots handling and its own
idea of what the site was. `site_crawl.py` now writes an inventory and all ten
site-wide items read it.

**The per-page half (0.10.0).** A run-scoped response cache in `lib/safe_http.py`,
where all four of this tree's HTTP seams converge. `SEO_HTTP_CACHE` names a directory;
the runner makes one per run and deletes it afterwards, so a hand-run script caches
nothing and no directory survives to answer a later audit.

Measured against the seven-page fixture, one audit with `--sample 1`, counted at the
server:

| | Requests | The entry URL | The site's inner pages |
|---|---|---|---|
| 0.8.0 | 97 | 37× | 6× each |
| 0.9.0 | 76 | 37× | 2× each |
| 0.10.0 | **16** | **1×** | **1× each** |

Sixteen requests for fifteen distinct `(method, path)` pairs. The one repeat is `HEAD /`
twice, and those are two different questions: `redirect_checker.py` asks with redirects
off because the hop *is* the finding, and the cache/compression check asks with them on.

**Requests were the smaller half of what it cost.** Thirty-seven fetches are
thirty-seven different documents the moment the page is not static — a CMS rotating a
hero image, a deploy landing mid-audit, an A/B test — and items would then disagree
about the page with every one of them right about what it read. That is the same failure
the crawl inventory removed for the site, one level down, and removing it for the page
is the guarantee; the requests are the side effect. `http_cache` is in the artifact so a
reader comparing two verdicts that disagree can tell which kind of run produced them.

The safety argument is in the exclusions, and each one is a way a stored answer would
differ from a live one:

* **Only real responses.** A timeout, a refused connection, a redirect loop and a
  robots.txt refusal are never stored, so one transient failure cannot become every
  item's failure. Any status code *is* an answer, 404 and 503 included.
* **GET and HEAD only.** `indexnow_checker.py` submits URLs; replaying a submission
  from disk would report something that did not happen.
* **The key is what could change the answer** — method, URL, request headers,
  `allow_redirects` — and not what could not. `timeout` is out because it decides
  whether an answer arrives, never what it says. `max_response_bytes` is out because a
  complete body satisfies any cap large enough to hold it, which is what lets callers
  asking for 500KB, 1.5MB, 2MB and 5MB of one page share one entry; a cap *smaller*
  than the stored body is a miss and the request goes out and fails exactly as before,
  because trimming it to fit would be inventing a document.
* **robots.txt is not avoidable through it.** The gate runs before the lookup, and a
  stored redirect chain is re-checked hop by hop on the way out. Otherwise any site
  that redirects could opt out of the rule by being fetched twice.
* **Single-flight.** The runner starts eight workers together; without a lock per key
  they miss together and eight processes fetch the page the cache exists to fetch once.
  Waiting is bounded by the caller's own timeout and running out falls back to
  fetching — a cache must not be able to turn one slow server into a hung audit.

**One consequence to know about.** `elapsed` is restored with the entry rather than
zeroed, because three scripts report response time from it and a zero would be a
fabricated performance number. So TECH-003's TTFB is now the run's single fetch of the
page rather than `lcp_subparts.py`'s own — on the fixture it moved from 1ms to 3ms, the
only one of 214 verdicts whose evidence string changed at all. That is deliberate: one
measurement everything shares beats three scripts reporting three TTFBs for one page.
`--no-http-cache` restores the old behaviour for anyone who wants an isolated timing.

CI asserts a ceiling of 40 requests on the fixture audit at `--sample 3`, and that the
entry URL is fetched once, so a regression fails the build rather than only somebody's
server.

## 2. The tests prove a script's shape, not its thresholds

**Closed in 0.8.0**: all 55 evidence scripts have unit tests, and each asserts *the
field the registry actually reads*, named in the test. The surface has grown since:
measured on 0.80.0, the registry names **58** distinct scripts, and all 58 are named in
a test file. That last is a weaker statement than "has a unit test" on purpose — being
named is what a grep can show, and the two sweeps below are what actually hold the line,
because they take their list from the registry rather than from a list somebody keeps.
The count is not the point — the yield is. Four releases of writing these found, in
order: eighteen assertions that had never fired, two items that failed sites for
serving images the recommended way,
sixty-two items grading a site that refused every connection, and then twelve more of
that family plus five checks that accused every correct site. Roughly one defect per
three tests, and the rate has not fallen off.

Four layers now, each catching what the others cannot:

| Layer | What it proves |
|---|---|
| `test_evidence.py`, `test_evidence_scripts.py`, `test_evidence_apis.py` | a named field answers a named question, in both directions |
| `test_contract.py` — the good/broken pair | a check can tell two whole sites apart, or says in writing why it cannot |
| the dead-origin sweep | nothing is decided about a site that answered nothing |
| the good-site sweep | nothing is decided *against* the site that should pass |

The last two are four lines each and found more than everything above them. Both take
their list of what to cover **from the registry**, which they did not always: 0.8.0's
sweep enumerated a table maintained by hand, so the one crawler nobody had listed and
the seven scripts tested in a different file were exactly the scripts it could not see
— three `critical` items among them. A sweep whose coverage is a list somebody
maintains has the same blind spot as the thing it is checking.

What remains is not coverage but calibration. **A test can show that a threshold
fires; it cannot show the threshold is right.** A site audited at the wrong threshold
gets a confident verdict about the wrong question, which is the failure this suite is
worst at seeing, and nothing automatic can close it — a number's correctness is a
judgement, not an assertion.

**What 0.13.0 opened and 0.15.0 finished is the invisibility.**
`tools/audit_thresholds.py` finds every number a verdict depends on and requires each to
carry a stated basis, checked in CI. 0.13.0 could see 36 of them; 77 more were
comparisons against a bare literal, which cannot carry a basis because there is no name
to hang one on. All of them are named now:

| Basis | 0.13.0 | 0.15.0 | 0.28.1 | What it means |
|---|---|---|---|---|
| `standard` | 4 | 6 | 9 | an external published authority, named — Google's Core Web Vitals bands, the sitemaps.org URL limit, HSTS preload's one-year `max-age`, Flesch's Reading Ease bands |
| `measured` | **0** | **0** | **6** | calibrated against something, and the text says what against |
| `convention` | 18 | 32 | 36 | a judgement made here, stated as one: a round number because a line had to be somewhere |
| `inherited` | 14 | **75** | **66** | arrived with the borrowed code and has not been examined |
| `presentation` | — | 11 | 13 | decides what is printed after the verdict is already computed |
| unnamed | 77 | **0** | **0** | a bare literal, with nowhere to carry a basis at all |

Since 0.27.2, `measured` is enforced as `corpus=<what>; date=<YYYY-MM-DD>;
method=<how>` rather than accepted as free prose. The first calibrated family landed
in 0.28.0: six CSS-minification decisions measured against 527 files and 173 exact
source/minified pairs from 19 pinned packages.

**Two findings, and the second one is why the naming was worth the diff.**

*Six `measured`.* The CSS-minification family is the first real user of the measured
gate. The full inventory now reads standard 9, measured 6, convention 36 and inherited
66; 117 verdict-affecting numbers in all. Another 13 are presentation choices, excluded
because they are read only after the verdict is already computed.

*`inherited` is 66 and not 14.* The unnamed literals were not a random scatter — 59 of
the 77 were already present in the initial commit. So the honest statement is that
**more than half of the numbers this registry's verdicts rest on still carry an
unexamined inherited basis**, and the old 14 read more reassuringly only because 61
more thresholds had nowhere to carry a label. An inventory that undercounts in the
flattering direction is the failure this file exists to prevent, and it did it to itself
for two releases.

`inherited` is assigned from evidence rather than memory: a constant counts as inherited
when `git show <initial commit>` finds it already there. The list includes the ones that
matter most. **`SEVERITY_WEIGHT` — critical 10, high 6, medium 3, low 1 — decides the
SEO Score itself**, and nobody here has asked whether a critical item is worth ten low
ones or three; the score has been reported to two significant figures the whole time.
`EFFORT_COST` divides it to rank what to do first, so the ratio between two unexamined
tables is doing real work. `THIN_CONTENT_THRESHOLDS`'s 300 words is one of the numbers
this section used to name, and its provenance turned out to be exactly what was
suspected: conventional in SEO writing, with no source anybody here can point at. The
whole of `gsc_checker.py`'s opportunity rules read as SEO-blog folklore stated in
numbers — "striking distance" is a phrase, not a measurement.

Three things fell out of the naming pass, each of which is the argument for it:

- **Two thresholds were written twice** — 300 words for thin content, and the
  30-second `Retry-After` ceiling. One number in two places is one number that can be
  revised in one of them. Both have one home now.
- **A check and its own advice disagree.** `article_seo.py` accepts a title of 30-65
  characters while the fix text beside it asks for 50-60, and accepts a meta description
  of 100-165 while advising 120-155. Recorded in the basis lines rather than reconciled:
  which pair is right is a calibration, and that pass was an inventory.
- **The audit tool had two blind spots of its own.** It excluded 100, 1000 and 1024 as
  "units rather than limits", and removing them surfaced eleven comparisons of which ten
  were real thresholds. And it counted equality comparisons on the unnamed side while
  counting only ordering comparisons on the named side, so the two halves of one tool
  disagreed about what a threshold is.

A fifth kind, `presentation`, covers the 13 numbers that decide what is *printed* and
never what is decided, and is kept out of the total above. `SEVERITY_ORDER` is now a
live example: changing which severity is listed first changes the report's order after
the verdicts exist; it cannot make the audit reach a different verdict.

0.9.0 is the evidence that this is not theoretical. Sharing one crawl changed *how
many pages* the anchor-text check reads, and BL-081's threshold — five identical
anchors to one target, 80% of the links to it — went from firing on nothing to firing
on every site with a navigation bar. The check had been reporting the good fixture and
passing the broken one for two releases, and the contract pair recorded that as a
difference and called it working. The fix was a distinction the threshold could not
express: repetition *across* pages is a menu, repetition *within* a page is stuffing.

Two narrower gaps, both measured:

- **Three scripts are exercised only through a stub**: the two Search Console readers
  and the W3C validator. Nothing here can prove they read Google's *real* response
  shape, only the shape they were written for. That is the honest limit of an offline
  suite, and the reason `tools/probe_shapes.py` exists.
- **Structural queries are the one place a parser can change a verdict**, and both
  known sites are now handled rather than pinned: `picture_sources()` copes with either
  DOM, and the answer-block scanner was rewritten against document order in 0.15.0. A
  test asserts the two parsers *agree* — which is a stronger guard than the old pair of
  pinned numbers, because it fails on the next query written against sibling position
  rather than only on the two that were. What still has no guard is a structural query
  nobody has written yet, and the standing lesson is that `find_next_sibling()` and
  `recursive=False` are both questions about where the parser thinks an element ends.

## 3. One site shape is still untested live, and it is the one a fixture cannot be

Four of the five shapes item 3 used to list are exercised live as of 0.14.0, in
`tests/test_shapes.py`: a **cross-host redirect** (two origins, a real 301), a **bot
protection challenge** (a Cloudflare fingerprint served with a 200, refused, plus the
mirror case of an article *about* Cloudflare being audited anyway), a **sixty-page site**
where `--sample` has to choose and the stride has to reach the far end, and **TLS** —
the harness generates a certificate and hands it to the child through
`REQUESTS_CA_BUNDLE`, so `verify=True` stays on and the HTTPS and HSTS items get their
first verdicts from a real handshake.

What remains is **a Search Console property with enough history for the cannibalization
items**. It needs a property Google recognises and a key that can read it; neither is
something a fixture can be, and a test that stubbed the API while claiming live
coverage would be worse than the gap. Those items are covered by stubbed unit tests and
report `NO_DATA` against any fixture, which is the honest answer.

Still true, and worth keeping in view: every origin in the suite is loopback, so
nothing here exercises a slow network, a flaky connection, or a CDN's behaviour under
load.

## 4. Closed in 0.12.0 — the deliverable has history

`.seo-runs/` always stored every run. The comparison was computed only when somebody
passed `--diff`, printed to a terminal, and gone when the terminal closed — so the
report a client received could not say whether the last round of fixes worked, from
data that was already on disk. It is computed whenever a previous run exists now, and
both renderers carry a "Since the previous audit" section: score and coverage
movement, and the items that changed.

The part worth keeping is the third bucket. A change is `improved`, `regressed`, or
**`evidence`** — because `PASS` → `NO_DATA` is not the site getting worse, it is the
run losing the ability to tell, usually a third-party service that was down or a
supplied file that stopped being supplied. Filing that under regressions would tell a
client their site broke when the measurement broke, and the reverse would take credit
for a fix nobody made.

The baseline is named rather than implied: the artifact carries `compared_with` with
the other run's timestamp, registry version, mode, profile and scores. "Since the
previous run" is not a date, and a comparison whose other half is anonymous cannot be
checked by the person being shown it.

**Still one previous run, not a series.** A trend over six months is a different
feature and is not written.

## 5. Closed in 0.12.0 — there is a machine-readable fix list

`--fixes PATH` writes just the actionable items — id, status, severity, effort,
priority, category, title, what to do, evidence — as CSV or JSON, chosen by the
suffix. Ordered the way the report orders them, so a tracker and the report agree
about what to do first.

`FAIL`, `WARN` and `MANUAL` only. `NO_DATA` is not a fix — it is usually work for
whoever runs the audit rather than whoever owns the site — and `LLM_PENDING` is a
question still waiting for an answer; either one would fill somebody's sprint with the
auditor's own unfinished business.

The URL column is called `audited_url` and not `url`, because that is what it is: most
items record no page. A page-level check run over a sample reports the worst page's
verdict without carrying its address, and a site-level check has no single page to
name. A column called `url` would be read as "fix this page".

## 6. Smaller, but they will bite

- **The four shapes this entry singled out are judged, and twenty constants are still
  outside the inventory.** 0.71.0 listed twenty-five module-level numeric constants with
  no basis and named four that looked like thresholds rather than budgets. 0.81.0 answers
  those four by measurement rather than by reading their names:

  - **`site_crawl.MINHASH_FUNCTIONS` and `SHINGLE_WORDS` decide a printed claim, not a
    verdict.** They feed the MinHash signature and nothing else; the signature feeds
    `jaccard_from_minhash`; that feeds `near_duplicates` alone, and **no registry
    assertion reads any near-duplicate field** — the four items over
    `duplicate_content.py` read the exact hash, titles, descriptions and a word count.
    What they do move is the number an operator is shown: over 25/100/400 functions and
    3/5/9-word shingles one page pair estimates 0.68 to 0.81 similar, against a 0.85
    reporting line, while all four asserted fields stay put. Declared `inherited`,
    because 0.1.0 shipped them as default arguments and nobody here has chosen them
    since; the declaration names what would promote them, which is any item pointed at
    `near_duplicate_pairs`;
  - **`safe_http.DEFAULT_MAX_REDIRECTS` is a fetch budget and stays outside the
    inventory.** The two items about redirect chains do not read it: `redirect_checker.py`
    carries its own `max_redirects=10`, so `AR-150` (`total_hops lte 1`) and `CI-014`
    (`has_loop`) are bounded by that and not by this. Past the cap `safe_request` raises
    `TooManyRedirects`, so the page reads as a fetch failure and its items report
    `NO_DATA` — the one thing this number can do to a verdict is withhold it, which is
    the family of `DEFAULT_TIMEOUT` and `DEFAULT_MAX_RESPONSE_BYTES`;
  - **`detect_profile`'s three weight tables decide scope, under a flag somebody typed.**
    Counted: `local` excludes 4 of 215 items, `saas`, `blog` and `media` 7 each,
    `default` and `ecommerce` none, and an excluded item reports N/A. `choose_profile`
    takes the detector's answer only for an explicit `--profile auto`, and with no
    terminal falls back to `default` — the whole registry — saying so on stderr. Declared
    `inherited`, matching `SCHEMA_SIGNALS`, which had carried that argument alone since
    0.71.0 while its three neighbours carried nothing.

  The inventory reads **135 numbers a verdict depends on** and **20 uncounted** after
  those five declarations. The twenty are budgets, versions and buffer sizes by
  inspection, and by inspection is all this entry can say about them: nobody has walked
  them one at a time the way these four were walked.

  One declaration points the other way. `robots_path_tester.py:31` puts
  `# basis: standard` above `_META_ROBOTS`, a regular expression rather than a numeric
  constant. Either describe that justification without the reserved marker, as the
  tool's own error text prescribes, or deliberately widen the convention to cover
  vocabularies. This release changes neither the line nor the vocabulary.

  The scan remains shallow in the three measured ways whose wider simulation was
  rejected: it does not follow an unbased value through an assignment, an argument or
  another file, because doing so caught four based thresholds by dragging eight
  budgets, timeouts and presentation choices into the gate. It also reads `ast.Assign`
  and not `ast.AnnAssign`; there are zero annotated module-level numeric constants
  today, so that hole is waiting rather than leaking. Finally, a blank line ends the
  basis block by design. A separated basis therefore leaves its constant in the
  uncounted listing, visible but not silently claimed.
  <!-- ki: threshold-declarations-unjudged -->

- **Paid in 0.84.0 — two rendered mobile-layout measures owed since 0.62.0.**
  `mobile_render_checker.py` carried an optional Playwright
  branch for horizontal scroll at 390px, tap targets below 44px, and clipped or
  overflowing text. `MB-100` invoked the script with only the URL, no test supplied
  `--render`, Playwright was not installed, and rendered measurement moved in 0.53.0
  to an operator-supplied artifact. Deleting that branch in 0.61.0 therefore cost the
  product nothing: it had never measured or reported any of those three findings in
  a production run.

  Tap targets were already covered better by `MB-103`, which reads
  `tap_targets_below_48px` and follows the current 48px guidance. The other two are
  now in the artifact contract, and **their definitions are the deleted branch's
  rather than a fresh guess** — recovered from `git show 8afea49^`:
  `scrollWidth > innerWidth + 1` for the scroll, and
  `scrollWidth > clientWidth + 1 || scrollHeight > clientHeight + 1` over
  `h1,h2,h3,p,a,button,li` for the clipping. The measurements were never what was
  wrong with that branch; nobody running it was. Two deviations: the clipped-text scan skips
  invisible elements the way the snippet's other four measures do, and skips elements
  with no text — the branch did neither, so an empty `<p>` overflowing its box counted
  as a clipped text node there and the key's own name was false.

  **A measure nothing asserts is a field, not a check**, so this is a registry change
  and not only a contract one: `MB-107` *Page fits the phone viewport without
  horizontal scrolling* (`high`, `horizontal_overflow_px` `lte 1`) and `MB-108` *Text
  is not clipped or cut off at a phone width* (`medium`, `text_nodes_clipped` `eq 0`).
  The registry goes 215 → 217. Both follow `SP-214/215/216`: an operator-supplied
  artifact, so without `--rendered-json` they report NEEDS_INPUT rather than a verdict.
  `MB-093` keeps its own check — a declared viewport is an HTML fact and cannot be read
  from a render — so nothing existing lost coverage to them.

  `lte 1` and not `eq 0` for the overflow: `scrollWidth` and `innerWidth` are integers,
  and one pixel of rounding is not a page that scrolls sideways. That is the tolerance
  the deleted branch used, kept.

  **The cost, priced rather than hidden:** `text-overflow: ellipsis` is a deliberate
  layout choice, and an element truncated that way overflows its box like any other.
  A site that truncates card titles on purpose fails `MB-108`. That is a false fail
  with the count printed beside it, and narrowing it needs a rule for telling
  deliberate truncation from a defect that nothing here can price.
  <!-- ki: rendered-mobile-measures-owed -->

- **The good fixture is exemplary on its entry page and not under sampling.** The two
  suites that run it audit differently: `test_contract.py` runs one page, and
  `test_fixture_oracle.py` runs `--sample 3`, where the worst sampled page decides the
  verdict. `about.html` and `privacy.html` deliberately carry less than the entry page,
  and three items land on that difference — `MS-033` (no Open Graph or Twitter tags
  outside the entry), `GO-131` (no GA4 snippet outside the entry) and `CN-068`
  (authorship signals thin enough on one sampled page to drop the score under its
  threshold). Each passes the good site in the contract suite and fails it in the
  oracle, and **both suites are green**, because one never samples and the other has
  never had these three declared.

  Measured on 2026-08-13 while declaring oracle stage 2b: on the entry page `MS-033`
  scores 85 against a floor of 80, `CN-068` scores 75 against 60, and `GO-131` finds its
  one measurement ID. Sampled, all three are FAIL.

  The open decision is a fixture one, and it is not the same for all three. An exemplary
  site plainly does carry social tags and analytics on every page, which argues for
  repairing the fixture the way `MS-021`'s declaration repaired `about.html`'s title.
  Whether a privacy policy is supposed to carry authorship and experience signals is a
  real question about `CN-068`'s threshold rather than about the fixture. **Declare all
  three before repairing anything** — this note exists because the session that found
  them had already read their verdicts and could no longer declare them honestly.

  Declared on 2026-08-14, all three as FAIL against the good origin, by a session that
  had not read their verdicts — reasoned from `/privacy.html`, which carries no Open
  Graph tag, no analytics snippet and no byline. The fixture decision is still open and
  is now the harder half: repairing the good tree the way `MS-021`'s declaration
  repaired `about.html`'s title means **flipping three declarations to PASS in the same
  commit as the repair**, which is a change that has to argue for itself rather than
  quietly agree with itself.

  **Closed on 2026-08-14, by repairing the tree rather than by moving a threshold.**
  `/about.html` and `/privacy.html` now carry the full Open Graph and Twitter set, the
  same GA4 snippet and single measurement ID, a named `rel=author`, published and
  updated dates, and the site's contact route — everything the entry page carried alone.
  The three FAIL declarations were flipped to PASS in the same commit as the repair,
  which is the shape `MS-021` established: a declaration says what the fixture ought to
  be, and the fixture is moved to match.

  `CN-068`'s threshold was deliberately **not** touched. Lowering a `high` item's floor
  so a fixture goes green is the registry taking instruction from the fixture, which is
  backwards. The repaired policy page now carries an author, dates and a contact, so if
  `CN-068` still comes back FAIL the finding is about the floor and is measured rather
  than guessed.

  **It did fail, and here are the numbers.** On the repaired tree the entry page scores
  75 and both sampled pages score 35, against a floor of 60. The breakdown says why: all
  three report one author, a privacy link and several trust links, and only the entry
  page reports credential markers (3), external citations (3) and first-hand-experience
  markers (2). The missing 25 points are exactly the three signals a policy page has no
  business carrying.

  Two things follow and neither is a threshold tweak. **`CN-068` is a content item
  applied to every page type** — the third instance of that shape this week, beside
  `LO-200` (a page-level rule for a site-level fact, found on the live audit) and
  `MD-184` (which asks every page for an image). A floor no policy page can clear fails
  every real site that has one, because the sample takes the worst page. **And the
  markers are matched literally**: `/about.html` states eleven years in restaurant
  kitchens and four in bread, in plain English, and scores zero for experience, because
  the phrase the scan knows is the entry page's bolded 'years of experience'.

  Deliberately not taken here, because both change live verdicts and one changes the
  registry: scoring `CN-068` per site rather than per sampled page, and widening the
  marker vocabulary. Writing the marker phrases into the fixture to make it green was
  rejected outright — that is shaping the fixture to suit the check, which is the
  failure this tree exists to refuse.

  **Closed in 0.87.0 by moving the floor, which is what the paragraph above refused to
  do — so the difference has to be argued rather than assumed.** What that paragraph
  forbids is moving a number *so that a fixture goes green*. The floor now rests on the
  score's own decomposition: of the six components `eeat_signal_checker.py` awards,
  credentials (20), first-hand experience (20) and external citations (10) are article
  signals, and the editorial-standards component (15) reads 0 on every page of every
  tree here — so the reachable maximum for a site without a standards page is 85 rather
  than 100, and what remains for a page of any type is authors 20 + trust 15 = 35.

  **The test of whether that is a derivation or a rationalisation is what it would have
  done if it disagreed**: had the components summed to 50, the floor would be 50 and
  this fixture's policy pages would still fail, and the entry would say so. The number
  lands on 35 because those pages carry exactly the page-type-neutral components and
  nothing else, which is what makes them policy pages.

  **Measured across the class rather than for this item alone.** Per page over all
  fifteen pages of the three servable trees, five items — `CN-068`, `GO-144`,
  `GEO-004`, `GO-145`, `GEO-005` — were cleared by exactly one page each, the good
  tree's entry page, and all five reported FAIL on *both* fixture origins. An item that
  cannot tell the exemplary tree from the broken one has stopped measuring, which is
  the reading 0.49.0 applied to `MD-184`. After 0.87.0 the oracle's count of items
  opposed across the origins goes 79 → 84.

  **Still not taken, and now for a measured reason.** Scoring per site rather than per
  sampled page was the alternative, and it was not chosen: the decision was Anton's on
  2026-08-20, with both on the table. Widening the marker vocabulary is untouched — the
  `/about.html` sentence about eleven years in kitchens still scores zero for
  experience, and a floor that no longer asks a policy page for experience markers does
  not make the scan read English any better.
  <!-- ki: cn-068-floor-and-the-good-fixture -->

- **Fixed in 0.49.0 — `image_inventory.py` emitted `count: 0` for a page it found no
  images on, and four items graded it.** Measured on 2026-08-14 against the good
  fixture: on `/about.html` and `/privacy.html`, which reference no image at all,
  `image_inventory.py` returned `count: 0` while `image_weight_audit.py` omitted
  `responsive_count` from its output altogether. Under `--sample 3` the first produced
  a `medium` FAIL for *Audit Sitewide Image Usage* on the exemplary fixture; the second
  correctly reported nothing and let the entry page decide.

  The oracle found it as a disagreement rather than a crash: `MD-189` was declared FAIL
  for the same reason and came back PASS, and the two scripts differing on identical
  input is the whole of the explanation. This is the class three releases were already
  spent on — a script emitting a default for an input it never measured — surviving in
  one script while its neighbour had the fix.

  The repair withholds the three fields the registry reads as a verdict — `count`,
  `missing_alt` and `summary.lazy_lcp_candidates` — when the page carries no images.
  **`MD-184`'s FAIL was the visible half; the other three were the quiet half**, because
  `missing_alt: 0` and `lazy_lcp_candidates: 0` gave `CI-016`, `MD-186` and `CN-054` a
  free PASS on every image-free page ever audited. Neither fixture verdict moves for
  those three — the sample's worst *decided* page already came from a page with images
  — so nothing here would have shown it. `MD-184` is now PASS on both origins and is
  re-declared accordingly.

  **Fixed in 0.50.0 — a third divergence between the same two scripts.** An `<img>`
  carrying no `src` was skipped by `image_inventory.py` and processed by
  `image_weight_audit.py`, so a page whose only `<img>` had nothing to load was
  `NO_DATA` for the four items over the first script and `FAIL` for `MB-096` and
  `MD-189` over the second. **The 0.49.0 entry called that a decision rather than a
  defect and left it standing; that was wrong, and the wrongness is the useful part.**
  An `<img>` with a `srcset` and no `src` is valid responsive markup and is still
  judged. An `<img>` with none of `src`, `srcset` or a `<picture>` source will never
  load anything, and grading it as an unresponsive legacy-format image reports two
  image defects for a page that has no image there. `image_weight_audit.py` now skips
  exactly that shape and reports the count as `skipped_no_src`, the name its neighbour
  already uses.

  **Answered in 0.85.0, from the title's side rather than the assertion's.** The
  question left standing here was whether `count gte 1` is the assertion *Audit
  Sitewide Image Usage* wants at all: the item agrees with every page that has an
  image and says nothing about pages that do not, which is not an audit of sitewide
  usage — it is a check that images exist somewhere in the sample. The census then
  said the same thing in numbers: `MD-184` answered PASS on all five trees this
  repository can serve, `tests/corpus/failing-shapes/` included. The one FAIL it ever
  produced is the one three paragraphs above — the defect this entry is about — so
  since 0.49.0 *Audit* has named a judgement the item cannot deliver. 0.85.0 renamed it
  *Confirm the Page References at Least One Image* through `title-overrides.json`,
  which is the repair 0.53.0 made for `TE-169` and `TE-177` — bring the title to the
  assertion, not the assertion to the title. *References* and not *uses*: an `<img>`
  with no `src` is skipped before the count, so the assertion is about what the markup
  names.

  **What that does not settle is held outside this entry**, so that a closed narrative
  stops carrying an open question — which is what the paragraph replaced here had
  become. Whether a page with no image should be able to fail something is one of the
  25 never-FAIL items `tests/census.json` counts. What an image-usage item should
  assert over a script handed one URL at a time is a title-versus-assertion question,
  and it sits with the other two of those in the entry immediately below.
  <!-- ki: image-inventory-count-on-a-page-with-no-images -->

- **Two items assert a thinner thing than their titles promise.** Collected rather
  than filed separately, because the shape is the
  point: the assertion is satisfied by markup that does not deliver what the title says.

  | item | title promises | assertion actually requires |
  |---|---|---|
  | `AR-152` | *Block Crawl Strategically with robots.txt* | that `robots.txt` has any
  user-agent group at all |
  | `CN-056` | *Show Publication **and** Updated Dates* | one date of any kind |

  `AR-152` was found on the live audit of 2026-08-14. That sentence pointed at a
  `FINDINGS-REVIEW.md` for the write-up, and there is no such file and never has been
  in this repository's history — so the finding is restated here instead, which is what
  a pointer to nothing was standing in for: the item runs `robots_checker.py` and
  asserts `user_agents` is truthy, which any `robots.txt` with a single `User-agent:`
  line satisfies, whatever it then allows. `CN-056` was found by reading the eight
  declarations that the fixture repair touched. `TE-169` and `TE-177` used to be in
  this table, but 0.53.0 brought their titles to their served-HTML assertions, not the
  assertions to the old titles. The served-versus-rendered comparison those titles
  implied is `MB-105`; scoring that comparison three times would duplicate it. `MD-184`
  was never in this table and belongs to the same shape — 0.85.0 renamed it the same
  way, and the entry above records why. What that rename did not settle belongs here
  with these two: `image_inventory.py` is handed one URL at a time, so no assertion
  over it can be sitewide, and what an image-usage item should assert instead of
  `count gte 1` is open.

  Neither of the two in the table is acted on here, and nor is the question `MD-184`
  left behind: each changes what a live audit reports and the registry. They are
  collected so that the next person deciding what a registry version is worth
  spending can see them together.
  <!-- ki: titles-thinner-than-their-assertions -->

- **Closed in 0.50.0 — the five items that could not fail, and this entry outlived them
  by twenty-nine releases.** A `none_severity` assertion fails when an issue carries a
  severity it grades, then consults the warn band; FAIL arrives only if the band fails
  too. Five items sat over scripts whose whole vocabulary was `warning` and `info`, which
  alias to medium and low, so `SP-110`, `TE-170`, `MD-185`, `AR-163` and `TECH-002` could
  not report FAIL on any site in the world. Two were proven by the oracle rather than
  argued: on 2026-08-14 it declared FAIL for `SP-110` and `TE-170` on the broken fixture
  and the run answered WARN on both origins.

  0.50.0 repaired it in the scripts rather than in the rules — each grades the one finding
  that is a defect on every site as `error`, and the rest stay advice — and gave
  `audit_reachability.py` the fourth mechanism this entry said it lacked,
  `severity_vocabulary`. **Measured on 0.79.0: that mechanism proves zero items today**,
  against the seven it named when it shipped. The paragraph that used to stand here also
  warned "do not ship it as a gate before the oracle has calibrated it"; it has been a
  gate in `ci.yml` since 0.50.0.

  Kept, rewritten rather than deleted, because the entry itself is the finding: **a record
  of a defect is not evidence the defect is still there**, and this one read as open
  through every audit of this file until somebody ran the detector it asked for. What
  `audit_reachability.py` still cannot do is claim reachability — 141 of 143 script-backed
  assertions are not claimed either way, and that number is the honest measure of how much
  of the registry this tool speaks about at all.
  <!-- ki: items-that-could-not-fail -->

- **Closed in 0.43.0, and this entry read as open for the thirty-six releases after
  it.** KW-071 asserts `summary.contested_queries` `eq: 0` with a warn band at `lte: 3`
  — read off the registry, not recalled — and the directional `worst_spread` this entry
  was written about is not in the contract at all. The registry carried `worst_spread`
  at `v0.42.0` and `contested_queries` at `v0.43.0`, which dates it to *Give KW-071 the
  warn band its old rule already had*. The decision this entry called open, between
  becoming the close-competition assertion and moving to evidence that measures
  duplicated copy, was taken in favour of the first. `audit_item_semantics.py` has
  carried the ruling in writing ever since: cannibalisation is keyword duplication seen
  from the SERP side, and `contested_queries` counts queries whose URLs compete in the
  same close position band. What follows is the entry as it stood, kept because being
  wrong here for thirty-six releases is the reason `tests/known_issues.py` exists.

  **KW-071 asks about keyword overuse, while its evidence measures SERP competition.**
  `gsc_cannibalization.py` now reports close non-branded competition honestly as
  `summary.contested_queries` and retains each query's raw position `spread`. A wide
  spread is not treated as ambiguity: position 1.5 beside 11.2 shows a winner, while
  1.2 beside 1.4 is the unsettled shape.

  The registry still points KW-071 at the removed directional `worst_spread`, so the
  item reports `NO_DATA` in 0.37.0 instead of manufacturing a keyword-overuse verdict
  from rank distance. Repointing or retitling it changes the audit contract and
  `registry_version`; this release deliberately does neither. The open decision is
  whether KW-071 should become the close-competition assertion or move to evidence
  that actually measures duplicated or overused copy.
  <!-- ki: kw-071-evidence-and-title -->

- **Closed in 0.36.0: the default locale's whole unprefixed route tree is compatible
  with a subdirectory scheme.** The 0.35.0 repair accepted only the root: `example.lt/`
  beside `/en/` and `/ru/` passed, while `/bbq` beside `/en/bbq` and `/ru/bbq` failed.
  The final rule accepts an unreadable same-host alternate only when its normalized
  path equals a readable alternate's path with that readable alternate's locale prefix
  removed. It compares paths without query strings and treats trailing slashes as
  equivalent.

  This is deliberately narrower than accepting any unmarked same-host path. The
  0.33.0 guard remains: `/about` beside `/fr/` is still `mixed` and fails, because
  stripping `/fr/` produces `/`, not `/about`. An unreadable path under another
  locale's prefix also remains `mixed`; the unreadable path itself is never stripped.
  <!-- ki: default-locale-route-tree -->

- **Narrowed in 0.56.0; declared Lithuanian and Russian now use reviewed E-E-A-T
  vocabularies, while undeclared and other languages remain open.** Measured on two
  structurally identical pages — the same byline, author and publisher JSON-LD,
  credentials, first-person evidence, four institutional links and two citations —
  English scored 82 and passed CN-040, CN-044, CN-057 and CN-068; Lithuanian scored
  24 and failed CN-040, CN-044 and CN-068. Its two credential markers, two first-hand
  markers, three trust links, one privacy link and one editorial-policy link had all
  been invisible. With `lang="lt"`, the Lithuanian twin now finds the same five signal
  counts, scores 82 and returns the same four verdicts. `tel:` and `mailto:` remain
  language-neutral contact routes.

  The maintained term resource carries fully reviewed English, Lithuanian and Russian:
  English preserves the existing vocabulary and remains useful for institutional labels
  left untranslated, while Lithuanian and Russian are the languages this plugin's
  operator audits and reports in. The inherited `/datenschutz` URL fragment stays in
  English to preserve behaviour, but there is no German locale until a full vocabulary
  is reviewed. This is not statistical language detection: a page declaring no language
  is still graded on English alone, and every language beyond those three full
  vocabularies remains where Lithuanian was before this repair. The reader should not
  conclude that translated labels are recognised unless the page declares a reviewed
  language the resource actually carries.

  Credential and first-hand signals still match body prose rather than the place and
  role in which a phrase appears. A page that merely quotes an `expert` therefore gets
  credential credit in English, as it did before 0.56.0; equivalent Lithuanian and
  Russian terms deliberately mirror that weakness rather than inventing a stricter
  cross-language distinction. Fixing it requires grading credentials by where they
  appear, and remains separate work.
  <!-- ki: eeat-vocabulary-by-declared-language -->

- **Narrowed in 0.34.0; inspecting a set of important URLs remains open.** CI-002
  got the right evidence in 0.26.0 — Google's URL Inspection answer — but for eight
  releases kept *Ensure Important Content Is Indexed*, a title that claimed more
  than one inspected URL could answer. It is now *Confirm Google Has Indexed the
  Audited URL* through a declared override, while `plerdy-titles.json` remains a
  faithful record of the inherited wording.

  The site-wide feature is still missing. Inspecting a set of important URLs needs
  a quota policy for 2,000 inspections per property per day, selection rules and
  aggregation; until those exist, no site-wide indexation claim is made. No gate
  caught the over-claim. CI-002 shares vocabulary with its assertion through its fix
  text — "indexed", "indexing" and "Search Console" — so the semantics tool never
  listed it, and a title that over-claims *scope* is invisible to a check that
  compares *subject*. This is the neighbour of the polarity limit recorded directly
  below: the words can identify the right subject while the sentence still promises
  the wrong thing.
  <!-- ki: ci-002-scope-and-title -->

- **A title can name the right subject and still state the wrong side of it, and no
  gate here reads polarity.** `audit_item_semantics.py` answers whether an item
  asserts *about* what its title names. It has never answered whether a PASS means
  what the title says. The two questions come apart when a title is phrased as the
  failure rather than the desired state: subject matches, verdict inverts, and the
  item reports the opposite of what it found.

  GEO-008 shipped that way inside 0.32.0. The draft title was *"This page or marked
  text is restricted in Google AI answers and result snippets together"* over an
  assertion of `rows.0.snippet_controls.restricted` `falsy: true` — so the item
  passed exactly when the page was *not* restricted, while its title told the reader
  it was. The vocabulary check was satisfied, and satisfied by the very word that
  made the title wrong: `restricted` appears on both sides, which is what that check
  is looking for. Corrected by hand before landing to *"Snippet directives leave the
  page usable in AI answers and result snippets"*. Every other one of the 215 titles
  states the desired state; this is one occurrence, not a pattern, and it was caught
  by a person re-reading the item rather than by anything in CI.

  **The cheap heuristic was written and measured, and it is not worth shipping.** The
  rule: when passing requires a path to be absent or bounded — `falsy`, `eq: 0`,
  `lte`, `lt`, `none_matching`, `none_severity` — that path's last segment names the
  defect, so a title repeating that segment names the defect too. Measured against
  the registry:

  - **It is almost all false alarm.** 23 of 215 titles fire, and all 23 are correct —
    *Fix Broken Images* over `broken_image_count == 0`, *Eliminate Internal Duplicate
    Content* over `exact_duplicate_groups == 0`, *Avoid Intrusive Interstitials on
    Mobile*. They name the defect because they are remediation instructions, which is
    the house style for two thirds of this registry.
  - **Suppressing those needs a list fitted to them.** What separates the 23 from the
    defect is grammatical mood, not vocabulary: an imperative verb in first position.
    Adding a 25-verb allowlist plus a negation guard, and requiring the whole final
    path segment rather than one token of it, does catch the 0.32.0 draft and leaves
    2 false positives — SP-214 *LCP within budget in a local trace (lab)* and SP-215
    *CLS within budget*. But the verb list was written by reading the 23 titles it
    must not flag, so it is fitted to them: a future title opening *Prevent* or *Trim*
    is a false alarm on the day it is written.
  - **Its ceiling is a third of the registry, and it misses most phrasings inside
    that.** Only 76 of 217 items assert a negative-polarity path at all — 35.0%. Of
    four plausible ways to write GEO-008's defect, it catches the one that happens to
    reuse the assertion's own word; *suppressed*, *blocked from quoting* and *shut the
    page out of* all pass silently.

  So: more false alarms than findings, one-in-four recall inside a 34.4% ceiling, and
  the one component doing the discriminating overfitted to the corpus it was tuned on.
  **A reliable check is not possible and none is implemented.** Polarity is a claim
  English prose makes about a JSON predicate, and no token-overlap test decides it —
  the same objection §2 makes about vocabulary, one level harder, because here the
  words match and the meaning is still inverted.

  What makes this class distinct from every other registry defect recorded in this
  file: **nothing executable is a witness to it.** A mis-titled item of the 0.20
  family asserts the wrong field, so some fixture eventually disagrees with it. Here
  the script is right, the assertion is right, and both fixtures answer correctly —
  the good one passes, the broken one warns. Only the sentence is wrong, and the test
  suite has no reader. The line is held by reading each new title against its
  assertion at the moment it is written, and by this entry saying that out loud
  rather than leaving CI's silence to be read as coverage.
  <!-- ki: title-polarity-has-no-gate -->

- **Nine Search Console thresholds are examined and deliberately not calibrated.**
  The pilot evidence is one small property, roughly ten thousand impressions over
  sixteen months: 501 query-by-page rows, of which 26 clear 50 impressions, 15 clear
  100 and 10 clear 200. Its CTR-by-position curve is non-monotonic (17.3% at position
  1, 1.8% at position 2 and 9.1% at position 3), direct evidence that a few large rows
  dominate the sample rather than evidence for what CTR is normal. Only five queries
  reach the 50-199-impression bucket relevant to the average-position floor. No query,
  URL, page path, property or client identity is retained; none is needed to understand
  the limitation.

  We refuse to relabel the nine values `measured`, and retain each inherited value,
  for four distinct reasons:

  - **Market claims need many properties.** `STRIKING_DISTANCE_MIN_POSITION` (4),
    `STRIKING_DISTANCE_MAX_POSITION` (20), `TOP_POSITION_MAX` (3), `LOW_CTR_PCT`
    (5), `VERY_LOW_CTR_PCT` (2) and `RANKS_FIRST_POSITION` (1.5) claim something
    about normal ranking or CTR. One property in one language cannot establish that.
  - **The available sample is too thin for mean-position stability.**
    `STRIKING_DISTANCE_MIN_IMPRESSIONS` (50) gates an average position, not a CTR,
    so binomial precision does not apply. It needs a distribution of how far query
    mean positions wander; five relevant queries cannot supply one.
  - **Backlink concentration is not search analytics.** `TOP1_SHARE_PCT` (50) reads
    the Links export. No volume of Search Console performance data can settle it.
  - **Severity is a product decision.** `HIGH_SEVERITY_IMPRESSIONS` (100) splits high
    from medium after cannibalisation has already been found; it does not measure
    whether the finding exists.

  What would settle the market claims is many properties across languages and markets,
  with property-level estimates kept independent. More months from this one property
  would deepen the same sampling bias, not create the missing market evidence.
  <!-- ki: gsc-thresholds-uncalibrated -->

- **Line-wrapped minified CSS reads as unminified.** The pinned corpus labels
  `bulma-1.0.2/css/versions/bulma-prefixed.min.css` as minified, but its line wrapping
  leaves it at only 37.13 bytes per line and 392 indented lines in the first 400. No
  bytes-per-line boundary fixes that conjunction: lowering 180 below 37 still leaves
  the indentation signal false, and it also crosses authored source such as
  `codicons-0.0.36/dist/codicon.css` at 47.09 bytes per line. This needs a different
  signal or classifier shape, not a tuned constant.
  <!-- ki: line-wrapped-minified-css -->

- **`wasted_bytes` counts uncompressed bytes visitors normally do not pay.** Across
  173 source/minified pairs, only 10.824% of the aggregate raw-byte saving survives
  gzip. The median of per-package pair medians is 7.188%; the pooled pair median is
  14.402%, and individual pairs span 1.796%-49.640%. A medium finding at 20KB of raw
  whitespace therefore represents about 2.2KB over the wire at the aggregate rate:
  roughly a ninefold overstatement on a gzip-serving site. The threshold remains
  measured against its current meaning here; redefining the field and its output is a
  separate verdict-changing change.
  <!-- ki: wasted-bytes-before-gzip -->

- **Fixed. The one test that guards somebody else's server never started a second
  process.** `test_the_pacing_state_is_shared_between_processes` opened with
  `self.assertTrue(os.path.isdir(self.dir) or True)` — an expression with no false
  case — and then asserted that one process had written *something* into the
  coordination directory. Cross-process pacing is the whole subject of the test and the
  whole reason the slot file exists, and it went unmeasured through every release: a
  limiter that paced each process against itself would have passed. Now three children
  start together at 5 rps and the gaps between the times they proceed are measured;
  `test_pacing_off_lets_the_processes_go_together` is the other half, so the first is
  known to measure pacing rather than the cost of starting interpreters. Verified
  against the failure mode it names by giving each child its own state directory:
  gaps 0.000s / 0.001s and the assertion fails, against 0.205s / 0.205s for the real
  implementation.
  <!-- ki: pacing-test-never-forked -->

- **Fixed. The GSC scenarios accepted a rule that had stopped deciding.** The positive
  fixtures asserted `verdict in (PASS, NO_DATA)` and the negative ones "at least one
  item in the group failed". A path renamed out from under an assertion reports
  `NO_DATA` forever, which satisfies both — and that is the exact defect this file
  records three times over. All four scenarios now pin the full verdict map:
  `{GO-139: PASS, KW-070: PASS, KW-071: FAIL, MS-023: WARN}` for cannibalisation,
  `{CI-010: PASS, GO-135: FAIL}` for an excluded URL. CI-010 passing on a URL Google
  has not indexed is correct — it asks whether the chosen canonical matches the
  declared one — and pinning it is what makes that a statement rather than an
  accident. Verified by dropping `summary` from the output: KW-071 and MS-023 fall to
  `NO_DATA`, which the old assertion accepted and the map does not.
  <!-- ki: gsc-scenarios-accepted-a-dead-rule -->

- **Fixed. The cache-cleanup test made a claim about the machine, not about the run.**
  It listed the shared temp directory for `seo-http-*` and required none, so a second
  suite running in parallel failed it with nothing wrong here — reproduced on 3.13.
  Snapshotting the directory before and after is not enough: a concurrent run creates
  its cache inside the window, and that still failed. The child now gets its own
  `TMPDIR`, which `mkdtemp` reads, so the only cache that can appear there is the one
  under test; and the test asserts the pacing directory *is* in there, so an empty
  result cannot mean it looked in the wrong place. Verified by running two full suites
  concurrently: both 666 tests, both OK.
  <!-- ki: cache-cleanup-test-claimed-the-machine -->

- **Fixed. Four test files ran 96% of what they defined and said OK.** Found 6 August
  2026 while reading `test_runner.py` for an unrelated reason, and it is a defect of
  the test infrastructure rather than of any test: `if __name__ == "__main__":
  unittest.main()` sat **above** the last class in the file, so `python
  tests/test_runner.py` called `main()` before that class existed and reported *Ran 237
  tests ... OK* for a file defining 246. The AST guard written for it then found the
  same thing in three more files, one of them added the same day:

  | File | Reported | Defines | Hidden |
  |---|---|---|---|
  | `test_runner.py` | 237 | 246 | `HistoryIsASeries` — 9 |
  | `test_registry.py` | 56 | 63 | 2 classes — 7 |
  | `test_report.py` | 50 | 76 | 6 classes — 26 |
  | `test_translated_sites.py` | 14 | 30 | 3 classes — 16 |

  **CI was never affected and that is why it lasted.** `unittest discover` imports a
  module rather than executing it as `__main__`, so the discovery path always collected
  all 665 while the direct path silently dropped 58. Anyone verifying their own work the
  quick way — one file, straight from the shell — got a green run over the tests most
  likely to concern them: the history series, the report surfaces, the translated-site
  classes.

  `ATestFileRunsEverythingItDefines` in `test_registry.py` parses every `test_*.py` and
  fails if any class or function is declared after the `__main__` block. Parsed rather
  than run, because the question is where a statement sits in the module body.

  Independently confirmed by a second reviewer working from the same tree, which is
  also where the count of 237 comes from.
  <!-- ki: test-files-that-ran-part-of-themselves -->

- **Both items closed — CI-019 in 0.21.0, CN-053 in 0.22.0. What stays open is the
  reason neither was caught here first, and it has since caught two more.**

  This entry was left saying `Open` about CI-019 through three releases after it was
  fixed. On the 0.23.0 audit of the same café it reports **PASS**. A file whose purpose
  is an honest ledger of defects carried a stale one, in the section a reader consults
  before defending a verdict — so the correction belongs at the top of the entry rather
  than at the end of it. What follows is the original finding, kept because the reasoning
  is what generalises.

  **CI-019 failed every site that did not sell anything, and its own fix text could not
  satisfy it.** Found on a live audit of a Lithuanian café, 5 August 2026, where
  it reported `high`/FAIL naming `/cart`, `/checkout`, `/login` and `/search`. All four
  return **404**. The site has no shop and no login.

  The item runs `robots_path_tester.py {url} /search /cart /checkout /login` and asserts
  `allowed_urls` is empty. That script fetches **robots.txt and nothing else** — read it:
  `test_paths` calls `fetch_robots`, then `robots_allowed` per path, and never requests
  the path itself. So it cannot know whether the URL exists, and a site answering
  `Allow: /` reports all four as exposed whether they are pages, 404s, or names nobody
  ever used. This is 0.9.0's "five checks accused every correct site", sixth member, and
  the blast radius is larger than any of those: **every brochure, local-business and
  portfolio site on the internet fails a `high` item here.**

  **The second defect is worse than the first and is not fixed by adding a fetch.** The
  title says *Noindex* System & Search Pages and the `fix` says "Set noindex,follow"; the
  assertion tests **robots.txt allow/deny**. Those are different mechanisms and the
  advised one *cannot* satisfy the check — a page carrying `noindex` is still `allowed`
  in robots.txt, so an operator who does exactly what the item tells them still fails it.
  Meanwhile the only remediation that *does* satisfy it, `Disallow:` in robots.txt, stops
  Google fetching the page and therefore from ever seeing the `noindex` — the documented
  way to leave a URL indexed with no content behind it. **The check rewards the fix that
  breaks the thing the item is named after.** That is §2's "a check and its own advice
  disagree", promoted from a recorded inventory item to a verdict shipped against a real
  site.

  **Why the good-site sweep does not catch it — answered, and it is the first of the two
  hypotheses this entry offered.** `tests/fixtures/good/robots.txt` contains
  `Disallow: /search`, `/cart`, `/checkout`, `/login`, under a comment reading *"The paths
  CI-019 exists to keep out of an index."* The fixture was built to satisfy this item. So
  the sweep is not blind in general — it is looking at the one site on the internet where
  CI-019 is meaningful.

  That generalises past CI-019 and is the more useful half: **a fixture constructed to
  pass the registry cannot catch an item that accuses every real site**, because whoever
  built the fixture tuned it for that item. The sweep's guarantee — "nothing is decided
  against a site that should pass" — is narrower than it reads: it holds for the site the
  registry was written against, and says nothing about the ones it was not. Nothing here
  fixes that; a second fixture built *without* consulting the registry would, and is not
  written.

  **0.23.0 is the evidence that this half is the one worth keeping open.** Two more
  defects arrived the same way — from a real site, not from the sweep. `GO-134` graded a
  striking-distance opportunity as a `high` failure, and `BL-081` reported a trilingual
  site's navigation menu as anchor spam because "appears on most pages" was asked once of
  the whole site and a translated site has one menu per language. Neither is visible on a
  monolingual fixture, and no fixture here is multilingual. That is now four items found
  by auditing something the registry was not written against, and zero found by the
  sweep. **The missing fixture is not a nice-to-have; it is where these keep coming
  from.**

  **It was not a single case, and the same run proved it.** CN-053 is titled *Avoid
  Critical Content in iFrames*, its fix text says "Do not hide critical content inside
  iframes", and its assertion is `raw.word_count >= 300`. **It counts words.** Nothing in
  it observes an iframe. The café failed it on three of eight pages for a 293-word page
  and was advised about iframes it does not have. This one is the more dangerous of the
  two: CI-019's mismatch is visible in the evidence, which lists four URLs a reader can
  check, while CN-053's FAIL looks entirely sensible until somebody opens
  `checklist.json`. **Two instances in one audit means 0.20 is about a class, not an
  item** — the whole registry needs the triple checked: does the assertion measure what
  the title names, and does the fix text describe the thing that would satisfy it. That
  is a mechanical audit and belongs in `tools/`.

  **CI-019 closed in 0.21.0. CN-053 is still open.** CI-019 gained `--probe` and now
  asserts `indexable_urls`: the path exists, a crawler may have it, and nothing keeps it
  out of the index — which accepts `noindex` and `Disallow` alike, so the mechanism
  mismatch stops being a choice. The title was not the part that was wrong; it is
  inherited wording and it named the goal correctly the whole time.

  Two things that repair turned up, both about this suite rather than the item:

  - **The fixture pair could not tell CI-019 apart after the fix**, because neither site
    had a system page at all — it had read as a working test for two releases while
    testing nothing, and only `test_contract`'s can-it-distinguish rule caught that. The
    broken fixture now serves `/search/index.html`.
  - **The first probe read `noindex` off a `<meta name="robots">` written inside that new
    fixture's own comment block**, where it is listed among the things the page
    deliberately lacks — so the page built to fail the item passed it. Markup inside a
    comment is not markup. This is the fourth appearance of one mistake in this tree:
    the keyword items fired on their own remediation text in 0.5.0, three assert rules
    matched a port number in 0.19.1, and the runner's soft-404 guard carries the warning
    in writing. Each time it was found by a test that happened to look, never by a rule.
  <!-- ki: ci-019-and-cn-053 -->

- **Closed in two halves — the weight in 0.22.0, the reader's own list in 0.24.0.** The
  header below said "both halves score" and was half stale for two releases: `scores_with`
  stopped the double weight, and **nothing in `checklist_report.py` ever read that field**,
  so the priority list and the `--fixes` export kept printing both twins. On the 0.23.0
  audit one image missing an `alt` still produced *Provide Meaningful Image Alt Text* at
  priority 6.0 and *Provide Meaningful Alt Text* at 3.0, both `high`, four rows apart in
  the same list. A wrong score is one wrong number; a task list with a duplicate sends two
  people to the same image. `twins_folded()` now folds synonyms in the two places a reader
  is asked to *act* — and deliberately nowhere else: the full checklist still prints every
  item with its own status, because the twin ran and its verdict is part of the log.

  The original finding follows. **Four items were two items, written twice, and both
  halves scored.** `CI-017` and
  `TE-181` are both titled *Validate HTML (W3C)*, both call `html_validator.py` with the
  same arguments, and both assert `summary.errors == 0`; they differ in category and in
  the wording of the fix. `CI-016` and `MD-186` are the same pair for alt text —
  one `image_inventory.py`, one `missing_alt == 0`, `high` on both. On the café audit two
  validation errors produced two FAILs and **one image missing an `alt` produced two
  `high` FAILs.**

  Under `SEVERITY_WEIGHT` that is one defect carrying double weight in the headline
  number, and in `--fixes` it is two rows for one piece of work. The duplication arrives
  honestly — the Plerdy source lists the same requirement under two of its own headings,
  and `plerdy_ref` is load-bearing — so deleting an id is not obviously right. But the
  score must not double-count: either one id decides and the other mirrors its verdict
  without contributing weight, or they merge and the mapping records that two source
  numbers point at one check.

  **Counted, and it is eleven groups rather than two.** `tools/audit_item_semantics.py`
  compares script, args and assertion across all 214: CI-016/MD-186, CI-017/TE-181,
  GO-144/GEO-004, GO-145/GEO-005, MB-097/MD-189, MB-102/MD-190, MB-104/TE-166,
  MS-027/MS-028, MS-029/CN-041, SE-116/TE-171, SE-117/SE-118. Three pairs mix severities,
  so **the weight one defect carries depends on which twin the reader looks at.** Two was
  never a count — it was how many a single audit happened to fail on, and nothing in this
  tree had ever asked.

  **One of the eleven is a different and worse defect than the other ten.** `SE-117`
  *Force HTTPS Sitewide* and `SE-118` *Valid TLS Certificate (HTTPS)* are both `critical`
  and both assert `https == True`. Those are not one requirement written twice — they are
  two requirements sharing one assertion, and the second **cannot fail independently on
  any site**. A site with HTTPS forced and a certificate that expired yesterday passes
  both. SE-118 sits in the registry weighing `critical` and checks nothing SE-117 does
  not, so the fix is neither a merge nor a mirrored verdict: it needs evidence of its own
  — `notAfter`, the chain, the hostname match — and until it has that, this registry has
  never once verified a certificate.

  **Closed in 0.20.0 for SE-118, leaving ten.** It now runs `tls_certificate.py` and
  reads `valid`, set by a handshake with `CERT_REQUIRED` and `check_hostname`. The other
  ten groups are untouched, and the count above is what the tool reported before the fix
  — it reports ten today. Three things the repair turned up that are worth more than the
  repair:

  - **No fixture in this suite can exercise SE-118.** Both fixture sites are plaintext
    and `http.server` does not speak TLS, so SE-118 had to leave `ACCUSED_ON_PURPOSE`
    and its only coverage is a dedicated module that stands up its own TLS origin. This
    is §3's problem wearing different clothes: the four test layers all run against
    origins the suite can build, and a certificate is not one of them.
  - **The i18n parity tests cannot see a stale translation.** They check that every item
    has a Russian title and fix, that neither is blank, and that each contains Cyrillic.
    SE-118's English fix text changed and its Russian one did not; all three tests stayed
    green, because a sentence that has quietly stopped describing the English one is
    still Russian, still present and still non-blank. The class's own docstring predicted
    exactly this — *"a second copy drifts the moment either side changes"* — and then
    tested for presence. Presence is not parity. A real guard has to bind the translation
    to the English text it was written against; a hash beside each entry would do it, at
    the cost of 428 more lines in `ru.json`. **Built in 0.22.0** —
    `tools/i18n_digest.py` stores a digest of the English `(title, fix)` beside each
    translation, a test reads it and CI runs `--check`. Deliberately not a digest of the
    translation: improving Russian wording should not require re-stamping anything, and
    only a change on the English side is a reason to re-read the Russian. An item with
    no digest counts as drift rather than as a fresh start.
  - **`EveryCriticalItemIsCovered` measured coverage against a set literal** and never
    opened a test file, so a script named there and tested nowhere read as covered. The
    class exists to stop coverage meaning "the ones somebody got round to" and had the
    same hole one level up. A third test now makes the suite prove each name.

  **Closed in 0.22.0, and it was two problems.** Two of the ten were never duplicates:
  they were two requirements sharing one assertion because the second had never been
  written, which is SE-118's defect again. `MS-027` *Write Unique, Compelling Meta
  Descriptions* and `MS-028` *Fill Missing* both asserted `meta_description truthy`, so
  MS-027 could not fail on any page MS-028 passed; and `MS-029` *Eliminate Duplicate
  Meta Descriptions* read the duplicate **content** count, so a site running one
  description across forty distinct pages passed it. MS-028 keeps the presence check.
  MS-029 gets `duplicate_description_groups`, computed from the crawl inventory, which
  has carried `meta_description` per page since 0.9.0 with nothing reading it. MS-027
  went to the copy lens: uniqueness is now MS-029's, and *compelling* is a judgement no
  assertion makes.

  The other eight are real synonyms and now carry weight once. A `scores_with` pointer,
  decided by hand in `SAME_CHECK` and guarded five ways, names the item that scores —
  the higher-severity one, so nothing is quietly downgraded. The twin still runs and
  still reports; it is out of `weight_registry` as well as the score, so the denominator
  matches. **`SP-111`/`SP-112` were a ninth pair nobody had counted**, found while ruling
  on the vocabulary list: both asserted `performance_score >= 90` under the title *Check
  Core Web Vitals in Search Console*, and pointing either at the right evidence would make
  it identical to SP-108. **Closed in 0.25.0, and the objection was the answer.** Identical
  is what `scores_with` is for: SP-112 and SP-113 are declared twins of SP-108, SP-111 takes
  the desktop call that nothing asserted before, and `SAME_CHECK` gained a list value to
  hold a group of three instead of a pair.

  **MB-104 left the MB-104/TE-166 group in 0.44.0.** It now fetches the icon and
  measures whether its shorter side reaches 48px, rather than mirroring TE-166's
  declaration-only check. `tools/audit_item_semantics.py` now reports eight duplicate
  groups; TE-166 keeps the original declaration check and MB-104 carries its own weight.

  **MD-189 moved from the MB-097 group to the MB-096 group in 0.45.0.** Its title names
  modern formats and responsive images, two facts already measured separately by MB-097
  and MB-096. MD-189 now reads the responsive count and defers to MB-096, whose title
  names that shared assertion exactly; MB-097 carries the modern-format weight itself.
  `tools/audit_item_semantics.py` still reports eight duplicate groups. A conjunction
  would raise the theme from 6 to 9 weight points and charge a missing modern format to
  both MD-189 and MB-097, so `scores_with` cannot make that aggregate honest.
  <!-- ki: duplicate-twin-items -->

- **All four rulings are closed. Three Core Web Vitals items in 0.25.0, `CI-002` and
  `IN-127` in 0.26.0.** The entry below is the original finding; the paragraphs after it
  record what each repair cost.

  Both of the last two were deferred on the same argument — "that is a new check, not a
  new assertion" — and both were one check each. `CI-002` now asserts `indexed` from URL
  Inspection instead of counting sitemap entries, which makes it Google's answer rather
  than the site's own claim, and `NO_DATA` without a `gsc` capability rather than a `high`
  PASS for owning a sitemap. `IN-127` now asserts `checks.url_structure.passed`, computed
  by reading each alternate against its own hreflang code. Two things fell out of the
  work and are worth naming here:

  - **`indexed` could not carry an assertion when one arrived.** It was pre-seeded with
    `None` in `gsc_url_inspection.py`, two lines under a comment explaining why
    `canonical_match` must not be, and `truthy` reads `None` as a failing value. The
    first run of the new test reported a page as not indexed, at `high`, for a property
    nobody could open. A field nothing reads is a field nobody has checked.
  - **Protocol consistency lost its grader.** It was what `IN-127` asserted, it is still
    computed and still counted in the severity tally, and no item asserts it now. No item
    in this registry is titled for it, and an ungraded signal is a smaller problem than an
    item grading it under the wrong name — but it is a gap, recorded rather than tidied
    away.

  The
  42 unreviewed misses are 0. Fourteen were the tool's own fault: `len(w) > 2` dropped
  `h1`, `h2` and `ga4`, and dropping them from the *assertion* side left those items
  with an empty vocabulary, unable to share a word with anything they asserted. The
  heuristic now keeps short tokens carrying a digit, stems regular English endings, and
  reads `field` and `value_map` keys as part of what an item asserts.

  The 28 that survived are each answered in writing in `REVIEWED`, and four are real:

  - **`SP-111` and `SP-112`** assert `performance_score >= 90` — the blended Lighthouse
    score, which mixes TBT and Speed Index and is not Core Web Vitals. `pagespeed.py`
    already computes the right thing in `field_cwv`, from CrUX, which is the data
    Search Console shows. Neither item reads it. There are **five** Core Web Vitals
    items in this registry and three of them measure something else: `SP-113` *Meet
    Core Web Vitals Thresholds* (`critical`) asserts `metrics.LCP.rating` alone — one
    of the three. Repairing them is a redesign of the group, not four edits, which is
    why 0.22 recorded it instead of doing it in the pass that found it.

    **Repaired in 0.25.0, and it was a smaller redesign than it looked.** All three read
    `field_cwv.verdict`; SP-111 takes the desktop call, SP-112 and SP-113 are twins of
    SP-108. Two things fell out of it that the entry above did not anticipate. `metrics`
    carries CrUX when there is field data and **Lighthouse lab audits when there is not**,
    so SP-113 was a field item on large sites and a lab item on small ones without saying
    which — a `critical` PASS about Core Web Vitals earned on a lab number, for every site
    CrUX has never sampled. Those sites now read `NO_DATA`, which is a breaking change and
    the honest verdict. And `field_cwv_verdict` graded an unrecognised CrUX band as failing
    (`rating != "good"`), which only mattered once a `critical` item read it: it would have
    turned SP-113's `NO_DATA` on an unknown band into a FAIL about a page nobody measured.
    A failure among graded metrics is now reported and a *pass* beside an unknown band is
    not.
  - **`CI-002`** *Ensure Important Content Is Indexed* asserted `summary.urls >= 1`. A
    sitemap listing one URL passed a site of five hundred pages, and being in a sitemap
    is not being indexed. The floor it actually checked is GO-136's. **Fixed in 0.26.0**
    — see the top of this entry.
  - **`IN-127`** *Use a Clear International URL Structure* asserted whether the hreflang
    set mixes http and https. Worth checking, and it is not URL structure —
    subdirectory against subdomain against ccTLD is what the title names. **Fixed in
    0.26.0** — see the top of this entry.

  Two more are weak rather than wrong and are written down as such: `MB-093` grades a
  `critical` "responsive layout" on the presence of a viewport meta tag, which a
  fixed-width page can carry; `CN-044` accepts any trust link for "a clear contact
  page", so a site with a privacy policy and no contact page passes.
  <!-- ki: four-rulings-closed -->

- **Closed — TE-179 in 0.21.0, GO-134 in 0.23.0. Two items reported something that is
  not a defect of the site, and one of them could not be acted on at all.**

  `TE-179` *Review Domain History & Reputation* asserts `whois.age_days >= 90`. The café's
  domain was 58 days old, so it failed. **A new domain is not a reputation problem and
  there is no work that closes this item** — it resolves itself in a month, and until then
  it occupies a line in the fix list. A task nobody can do teaches the reader to skim the
  list, which is the one thing a prioritised list cannot survive.

  `GO-134` *Resolve Search Console Issues* reads `opportunities` through
  `none_severity: [critical, high]`, and on this site it fired on **"Position 4.0 with 115
  impressions — within striking distance"**. Ranking fourth is good news, printed as a
  `high` failure. §2 already says `gsc_checker.py`'s opportunity rules are SEO folklore
  stated in numbers, but that is about whether the thresholds are right; this is narrower
  and does not depend on them. **The field is called `opportunities`. An opportunity is
  not a failure at any threshold**, and reading one through a severity gate turns the
  best finding in the report into the item a client is told to fix first.

  **TE-179 closed in 0.21.0. GO-134 in 0.23.0. The shared question was answered
  correctly in 0.21.0 and then applied to only one of them: this registry does not need a
  status meaning "worth knowing but not actionable".**

  The two items looked like one missing bucket and are not. TE-179's defect was never
  that a true fact had nowhere to go — it was that `age_days` is neither history nor
  reputation. Its own script already reports reputation; age was a proxy reached for
  because the real signal needs a key. It now asserts `safe_browsing.threats`, so a clean
  domain passes at any age, a listed one fails at any age, and with no
  `GOOGLE_SAFE_BROWSING_KEY` the field is absent — `NO_DATA`, "we could not look", which
  this vocabulary has always been able to say.

  GO-134 fails the premise instead. Every entry in `opportunities[]` carries its own
  `finding` and `fix`, so that work is real and a person can do it; what is wrong is the
  name and the weight, and both are inherited.

  So the bucket has no occupants. A new status would have cost the runner, the report,
  the HTML, the CSV, both translations, the score partition, the diff buckets and the
  every-status-reaches-every-surface test, in order to make two miscategorised assertions
  comfortable. **What was missing was not a status. It was a correct assertion.**

  **0.23.0 wrote that assertion, and the last sentence of this entry was what kept it
  from being written for two releases.** "Changing a `high` to something else is a
  threshold decision" was true and beside the point: nothing about GO-134 needed a
  severity changed. Reading the wrong field is not a calibration question, and no value
  of `high`, `medium` or `low` makes a good search result into a defect. Held under §2's
  discipline against tuning numbers by feel, an item went on printing a site's best
  result as its worst problem — the discipline protecting the defect it was written to
  catch.

  `gsc_checker.py` now emits `issues[]` from the sitemap report, which is the one place
  the Search Console API says a thing is **wrong**, and GO-134 asserts on that. The
  opportunities are reported outside the score, the partition and the fix list, under
  *Worth knowing: what Search Console suggests*. That section is what "no new status"
  actually required and nobody built: the answer was never that this data has nowhere to
  go, only that where it goes is not a verdict. Reopen this on the evidence of an item
  that genuinely has nowhere to go — not on these two.

  **0.44.0 reopened and re-answered the TE-179 half only.** The 0.21.0 objections remain
  true: age is not reputation, and a young domain must not FAIL work that nobody can
  perform. What was not on the table then is that SE-114, SE-116 and TE-171 already
  assert reputation three times while no item asserts domain history. TE-179 therefore
  returns to `whois.age_days >= 90` with its exact complement as a warning band: a young
  domain WARNs at half of one `low` point, an older domain passes, an absent age is
  `NO_DATA`, and FAIL is unreachable.

  This is not a repeal of the general ruling and does not create a status meaning "worth
  knowing but not actionable". GO-134's list of unattached findings still belongs in
  prose outside the score, partition and fix list. Domain age is a scalar with an item
  already named for it, so its evidence belongs on that row.
  <!-- ki: te-179-and-go-134 -->

- **Closed in 0.19.1 — and it was never a flake.** `none_matching` over an `issues[]`
  array without a `field` matches the whole serialised issue, URLs included, so
  GO-138's `404` matched the *port* of a test origin that bound 40455. The
  nondeterminism was an ephemeral port sometimes containing three digits, and every
  theory built from the "flaky test" framing — DNS, the parallel runner, shared
  rate-limit state — was wrong. It is a registry defect: a sitemap listing
  `/blog/404-errors-explained` fails GO-138 on any site, and GO-143's `WebSite` was one
  `/website-design` URL from the same. **Third occurrence of one mistake** — the
  keyword items fired on their own remediation text in 0.5.0, which is why `field`
  exists, and the soft-404 guard says "never a substring" in writing. Neither was ever
  turned on the rules. The entry below is what it replaced; it is kept because the
  useful part is the shape: printing the payload cost four lines and settled in one
  firing what three rounds of reasoning got wrong.
  <!-- ki: go-138-was-never-a-flake -->

- **One test is not deterministic, in a suite whose whole premise is that it is.**
  `test_go_138_needs_the_urls_fetched_to_find_anything` failed once on CI under 3.10
  and passed on a re-run of the same commit; 15 local runs of the full suite and of
  that module alone produced 0 failures. It asserts that a sitemap check run *without*
  `--fetch-urls` cannot report a 404, a redirect or a noindex, and it saw one.
  Reading `sitemap_checker.py` settles what it cannot be: all three of those issues
  are emitted inside the `if fetch_urls` branch, and that run does not pass the flag.
  The parallel runner was the obvious suspect and is not — `run()` returns its key
  with its payload and shares no path between the four concurrent `sitemap_checker`
  runs. **Not diagnosed, and deliberately not guessed at**: the assertion now prints
  the issues it actually saw, so the next occurrence names its own cause instead of
  costing another hour of theory. Until then the honest statement is that one verdict
  in this suite has been observed to depend on something nobody here has identified,
  which is the same class of defect as the parser divergence 0.14.0 pinned as a fact
  — and the lesson from that one is that recording the symptom is not the same as
  understanding it.
  <!-- ki: go-138-nondeterminism-as-first-written -->

- **Closed in 0.15.0 — the answer-block score.** `answer_block_scanner.py` found the
  answer to a heading with `find_next_sibling()`, which asks the parser where the
  heading's parent ends, and that is the one question the two parsers answer
  differently. Three queries were rewritten against document order and nearest-ancestor
  ownership, which is what both parsers — and the browser — agree about. Kept here
  because of what it turned into: 0.14.0 *pinned* the 10-against-32 as a fact, and a
  verdict that depends on which library is installed is not a fact worth recording. And
  the sibling walk was hiding a second defect that needed no invalid markup at all — a
  `<div>` between the heading and the paragraph, which is every themed CMS there is, was
  itself read as the answer, so the word count was the whole section's. **The bug that
  gets written down instead of fixed is the bug whose neighbour never gets found.**
  <!-- ki: answer-block-score-and-the-parser -->
- **macOS kills a forked child inside Apple's own framework, and the runner forks 55 of
  them.** Once Network.framework has been initialised in a process, `fork()` runs its
  `pthread_atfork` child handler — `nw_settings_child_has_forked` — which dereferences
  freed state and segfaults *in the child, before it execs*. Nothing of the child's own
  code has run, so the failure is silent: signal 11, no stdout, no stderr. It surfaced
  in this project's own suite, where `tests/test_shapes.py` passed alone and its audits
  died under `discover` depending only on which module ran first; the crash report names
  the chain outright. `run_script` and `harness.spawn` now start children through
  `posix_spawn`, which does not fork, and a signal death is classified as `signal` with
  the signal named rather than as `crash` with "exit code -11". What is *not* fixed: the
  trade is that a child inherits this process's descriptors for the moment before exec.
  **The 0.14.0 note that "the workaround holds while nothing reintroduces a `cwd=` or
  `close_fds=True`" was already wrong when it was written**: eight other call sites in
  this tree still forked, because `posix_spawn` also requires
  `os.path.dirname(executable)` to be non-empty and a bare `openssl` or `git` has none.
  The openssl child in the TLS harness died of signal 11 and reported itself as
  `SkipTest("openssl unavailable")`, so the site shape 0.14.0 called *exercised live* had
  never run on macOS — 4 local skips against Linux CI's 1, which nobody read. Closed in
  0.15.0 as three AST-checked rules over every `subprocess` call in the tree —
  `close_fds=False`, no `cwd=`, no bare binary name. The lesson kept here: **a workaround
  guarded at its own call site is guarded at one call site**, and a diagnostic that names
  the wrong cause is worse than no diagnostic.
  <!-- ki: macos-kills-a-forked-child -->
- **Closed in 0.15.0, and still a claim by default.** `--verify-bots` does the
  reverse-then-forward DNS check Google, Bing and Yandex document, and re-attributes a
  forged crawler's requests out of the crawl-budget figures rather than annotating them
  in place. What is *not* closed is the default: without the flag, `bot_identity` still
  says the identity is a claim, because the flag is a network call about a third party
  and this project does not make those without being asked. Three crawlers —
  DuckDuckBot, SeznamBot, PetalBot — publish address ranges rather than a DNS
  convention, so they answer `no_published_rule` and remain claims even with the flag;
  inventing a rule for them would report every visit they make as forged.
  <!-- ki: verify-bots-and-the-default-claim -->
- **The rendered-page artifacts are the one input that cannot be checked by
  re-measuring**, and 0.15.0 got as close as that allows. 0.7.0 closed the part that
  could be checked: an artifact naming a different page is refused with the reason. The
  age is now stated in the report in days and `--max-artifact-age` refuses one that is
  too old — off by default, because how stale a measurement may be depends on how often
  the page changes and there is no honest default for that. The age comes from the
  filesystem's mtime and not from any timestamp inside the file, which is the whole of
  what it adds: everything an artifact says about itself is the operator's claim. **Still
  not verifiable** — `touch` exists — only visible and boundable, which is as far as
  re-measuring cannot reach.
  <!-- ki: rendered-artifacts-cannot-be-re-measured -->
- **The page guard is fingerprint-based**, so an interstitial from a vendor it does
  not recognise still gets through. Deliberate: an unknown interstitial and a
  client-rendered shell are indistinguishable from the HTML, and the second is a
  real finding, so the run warns with the visible word count instead of refusing to
  score.
  <!-- ki: page-guard-is-fingerprint-based -->
- **Closed in 0.19.0 — the Russian report is Russian throughout.** All 214 item
  titles and all 214 recommendations were translated, and the registry has grown by one
  since: **215** of 215 titles and 215 of 215 recommendations carry Russian today, with
  no untranslated id. The claim is computed by a test against `checklist.json` rather
  than declared in the file. That matters here more than the translation does:
  this file has twice asserted a completeness it did
  not have, both times in the flattering direction. What no test can catch is a
  translation that has drifted in meaning from the item it translates — a translated
  title is a second copy of the registry's wording, and only the ids are checkable.
  The stale entry below is what it replaced.
  <!-- ki: russian-report-is-russian-throughout -->

- **A Russian report still carries English item titles.** The report's own 100 strings
  are fully translated as of 0.15.0. The 19 that were not — and this file said six,
  because 0.12.0's "Since the previous audit" section arrived untranslated after the
  claim was written — were the "what was audited" caveat block, the highest-stakes prose
  in the document, silently falling back to English. What remains is `item_titles` and
  `item_fixes`: 214 titles and their recommendations, which is a translation project
  rather than a code change. The stderr warning names both layers rather than implying
  the report is fully Russian, and that counting — added in 0.7.0 — is the only reason
  either gap was ever visible.
  <!-- ki: russian-report-english-titles-as-first-written -->

- **Freshness has a boundary for foreign microdata dates, not a general answer to
  which dates are about the page.** Measured on 2026-08-17, a page whose only date is
  a `<time>` inside `<div class="comment">` still reports that date at `age_days: 2725`;
  the equivalent `h-cite` and `p-comment` spellings have the same unpriced shape. A
  second top-level `itemscope` with no `itemprop` is also still read, because choosing
  which top-level item is the page needs a primary-item rule this synthetic corpus
  cannot price. Most widely, `body_text` is still the whole page: a newer written date
  in a comment, sidebar card or event prose can win through `DATE_RE` even when markup
  correctly puts it outside the page's item.

  Fixing those three holes needs a measured container vocabulary, a defensible
  primary-item rule, and a body region tied to that item. None can be calibrated here
  without a representative network corpus, so 0.70.0 filters only the exact
  `FOREIGN_CREDIT_KEYS` boundary already shared with JSON-LD. That rule has a known
  cost rather than another detectable hole: a template that nests the page's own
  `dateModified` inside `itemprop="isBasedOn"` loses it, because the markup says the
  date belongs to the source work and no `itemprop` reader can infer the opposite.

  A declared-role vocabulary is not the repair. The measured counterexample was a
  fresh bare page date of 2026-08-01 beside an archive card's declared
  `datePublished` of 2018-05-10: promoting the declared role changed the score from
  100 to 55 and failed CN-038. A later repair must establish what a date is about,
  not merely what role it declares; 0.70.0 therefore only removes provably foreign
  dates and never promotes one.
  <!-- ki: freshness-and-foreign-dates -->

- **Closed in 0.83.0 — the HTML credit boundary followed DOM nesting and not
  microdata's `itemref`.** One of the two directions this entry named was a false pass
  on a `high` item; the other turns out not to be a defect, and the difference is
  measured rather than argued.

  **The direction that was wrong.** `itemref` names elements elsewhere in the document
  that are also an item's properties, so a comment can own a byline nowhere near it in
  the DOM. Through the runner's own `evaluate()`, on a page carrying a publisher and no
  author of its own:

  | page | `authors` | `CN-057` |
  |---|---|---|
  | no byline at all | `[]` | FAIL |
  | commenter's byline nested in the comment | `[]` | FAIL |
  | **commenter's byline claimed by the comment through `itemref`** | `['D Petras']` | **PASS** |
  | page's own byline, outside any comment | `['M Kazlauskiene']` | PASS |

  The third row is the defect: a page with no author of its own passing *Show Author and
  Publisher Clearly* — `high` — with the same verdict as the honest fourth row.
  `under_foreign_credit` now resolves `itemref` to a fixed point, so a chain of claims is
  as foreign as its first link, and `itemscope` is deliberately not required: for a
  removal rule, honouring an invalid `itemref` costs a false fail while ignoring one
  costs a false pass.

  **The direction that was not wrong.** The entry said the page's own byline is dropped
  "even though the article claims it by reference". The markup it cited —
  `<div itemprop="comment"><span id="b1" class="author">M Kazlauskiene</span></div>
  <article itemscope itemref="b1"></article>` — claims the *element* and no property:
  `b1` carries no `itemprop`, and a referenced element with none contributes nothing to
  the item that named it. Spelled so that it does carry one, the same person is declared
  for both items and nothing says which was meant. That is ambiguity, and this tree
  answers ambiguity by withholding, exactly as `page_nodes` does for a graph it cannot
  resolve. Preferring the outer claim would let any `itemscope` on the page rescue a
  commenter by naming their id — a false pass built to repair a false fail.

  That decision is a test rather than a paragraph: installing the preference flips
  `test_a_byline_two_items_both_claim_stays_withheld`, which is how it was checked.
  <!-- ki: credit-boundary-ignores-itemref -->

- **Comments named only by class remain invisible to the foreign-credit boundary.**
  A comment container convention such as `<div class="comment">` carries no
  `itemprop`, so its nested HTML byline is still read as the page's author. This is
  unchanged from 0.70.0, which rejected a container-name dictionary because this
  corpus provides **no measurable error rate** for that convention. The deliberate
  boundary therefore removes only the six structurally declared foreign properties.
  <!-- ki: class-named-comments-are-invisible -->

- **Closed in 0.75.0.** Re-measured on the page this entry names: an unauthored article
  whose only `mailto:` and `/privacy` links belong to a commenter now reports
  `privacy_links` **0**, `trust_links` **0** and `policy_links` **0**, so neither CN-040
  nor CN-044 passes on somebody else's privacy policy. `parsed["links"]` carries a
  `foreign_credit` flag, which is what the sentence below said was missing; the readers
  filter on it rather than re-deriving the boundary from a tag they no longer hold.
  The original, kept because the entry outlived its repair by four releases:

  **The same page's privacy and trust links still have no foreign-credit boundary.**
  Measured on the unauthored page used for 0.73.0, with the commenter's only links an
  `<a href="mailto:...">` and an `<a href="/privacy">`: `signals.privacy_links` and
  `signals.trust_links` each accept the commenter's link, so `CN-040` and `CN-044`, both
  `medium`, **PASS**. Those readers use `parsed["links"]`, whose dicts no longer retain
  the source tag needed by `under_foreign_credit`; repairing them is not another call
  to the helper shipped here.
  <!-- ki: privacy-and-trust-links-boundary -->

- **Closed in 0.77.0, both halves.** `extract_content` reads `page_author_names` and
  `declared_publication_dates` and keeps no private answer of its own. Re-measured on
  the two shapes below: `author-grid` produces `authors: []` and `publish_date: ''`,
  `published-widget` the same, and across all **12** HTML fixtures **0** disagree with
  the shared answers, against the one this entry recorded. The date half got the shared
  definition the entry said did not exist. The original follows:

  **`article_seo.py` has private, weaker author and publication-date answers beside
  the shared ones.** Its `extract_content` uses substring class matching. Measured in
  both directions for both fields: `<div class="author-grid"><p>Meet the
  team</p><p>Recipes by many hands</p></div>` produces `author: 'Meet the teamRecipes by
  many hands'` while `page_author_names` returns `[]`; `<div
  class="published-widget"><p>Newsletter</p><p>Sign up</p></div>` produces
  `publish_date: 'NewsletterSign up'`. Across all **12** HTML fixtures, **11** author
  answers agree and `tests/fixtures/good/blog/first-post.html` does not: its JSON-LD
  author is `A Fixture`, `page_author_names` returns `['A Fixture']`, and
  `article_seo.py` returns `''` plus *No author attribution detected.* Both fixture
  pages with real dates likewise return `publish_date: ''` there while
  `freshness_checker.py` reports `2026-08-01` and `2026-07-01`. The author half could
  adopt the shared definition; the date half has no shared `page_dates` equivalent, so
  changing only one of the adjacent six lines would leave the duplication half-fixed.
  <!-- ki: article-seo-private-answers -->

- **`FOREIGN_CREDIT_KEYS` is deliberately narrower than every subject relation.**
  It contains **ten** keys, counted rather than recalled: `acceptedAnswer`, `comment`,
  `comments`, `review`, `reviews`, `suggestedAnswer` and `userComments` from
  `CONTRIBUTION_KEYS`, and `citation`, `isBasedOn` and `itemReviewed` from
  `SUBJECT_KEYS`. It does not contain `about`, `mentions` or `hasPart`.
  Measured before and after 0.73.0, an Article whose `itemprop="about"` Book contains
  `<span class="author">Herman Melville</span>` returns `['Herman Melville']`. That is
  not a traversal failure: the JSON-LD half has used exactly the same ten-key width
  since 0.66.0. Widening the set changes both spellings and live JSON-LD verdicts, so it
  needs its own release and measurement rather than a one-sided HTML exception.

  **The constant is not the only place this width is decided, as of 0.86.0.** A reader
  may name its own set at the call site, and the entity reader in
  `citation_readiness.py` now does: `CONTRIBUTION_KEYS | {"citation"}`, because a page
  is not about the works it cites, while `itemReviewed` and `isBasedOn` — what a page
  *is* about — stay. So this entry's ten keys are the shared default and the answer for
  the DOM half, not a single width every reader takes.
  <!-- ki: foreign-credit-keys-width -->

- **`entity_checker.py` reads the same graph with no boundary and a top-level-only
  scan, and `GEO-006` is graded on what it finds.** The item asserts
  `summary.sameas_missing_critical eq 0`, counted over four platforms — Wikidata,
  Wikipedia, LinkedIn and Twitter/X, four rather than five because `twitter.com` and
  `x.com` are two domains under one name and `missing` is keyed by name. Measured on
  2026-08-20, three readings and each one is a different defect:

  | markup | entities extracted | what the item then sees |
  |---|---|---|
  | a reviewed `Organization` hoisted into `@graph`, carrying all four links | `Them` | `0` missing — **PASS on somebody else's identity** |
  | the page's own `Organization` nested under `publisher`, same four links | none | `4` missing — **FAIL on a page that is anchored** |
  | a reviewed `Product` with all four links, nested or hoisted | none | `Product` is not one of the 132 `ENTITY_TYPES` |

  `extract_entities_from_schema` walks the top level and `@graph` members and matches
  on `@type`; it never consults `page_nodes`, so nothing tells it whose entity it is
  reading. This is the fourth reader of a page's JSON-LD, and the docstring of
  `page_nodes` names the danger in as many words — *that is the distinction to keep in
  mind before adding a fourth caller*. The other three took the boundary across 0.66.0
  to 0.86.0; this one never did.

  Not taken here, and the reason is that the three readings above are three different
  repairs — a boundary, a deeper scan, and a type set — with one live `medium` verdict
  between them. `citation_readiness` covers none of this: 0.86.0 measured that its own
  entity component is what credits a reviewed `Product`, and that `GEO-006` cannot see
  that product at all.
  <!-- ki: entity-checker-reads-the-graph-unbounded -->

- **Closed in 0.88.0 — a mostly-refused run reported a clean count.** The withholding
  fired only when no status at all was collected, so a hundred images of which
  ninety-nine timed out and one answered `200` emitted `broken_image_count: 0` and
  `MD-187` PASSed. The entry said suppressing it above some share of unchecked images
  would need that share and the corpus gives it no basis. That was right, and it was
  the wrong question. **No share is needed, because the asymmetry does the work:** a
  count of zero over an incomplete check is not a count of the page at any share,
  while a count above zero is a defect that a timeout elsewhere cannot undo. So the
  clean answer is withheld whenever anything went unchecked or was dropped past
  `--max-images`, and the failing answer always stands. The probe runs the entry's
  own scenario — a hundred images, ninety-nine refusing — and reads the key's absence.
  <!-- ki: a-mostly-refused-run-reports-a-clean-count -->

- **Closed in 0.89.0 — `GO-143` asked every site to publish a claim that was not
  true.** The item failed any page whose `WebSite` node lacked `potentialAction`, so
  the remedy it printed was: declare a `SearchAction` naming a search endpoint and a
  query template. On a site with no site search that is a false statement about the
  site, published in markup, to earn a result **that can no longer appear** — Google
  removed the Sitelinks Search Box from Search starting 21 November 2024, globally and
  in every language, and took it out of Search Console and the Rich Results Test with
  it. The recorded ruling in `audit_item_semantics.py` said "sitelinks and the
  sitelinks search box are driven by WebSite and SearchAction markup", which was wrong
  twice: sitelinks are algorithmic and no markup produces them, and the search box had
  been gone for over a year when this was read.

  **What was left is real, so the item was retitled rather than deleted** — the
  `MD-184` shape. `WebSite` is what Google reads for the site name in results, its
  documentation lists `name` and `url` as that type's required properties, and those
  two are exactly what `schema_required_props.py` requires. The item now says so:
  *Complete Every WebSite Node Google Reads for the Site Name*. Measured either way — a `WebSite`
  with name and url passes, one missing either fails, and the retired markup is
  neither asked for nor penalised.

  **The exemplary fixture was publishing the same false claim.**
  `tests/fixtures/good/index.html` declared a `SearchAction` targeting `/search?q=`, a
  path that tree has never served. Removed: a fixture that models good practice cannot
  model this, and it is not an edit that makes a check pass — the item passes on
  `name` and `url` either way.
  <!-- ki: go-143-asked-for-a-claim-that-was-not-true -->

- **Closed in 0.90.0 — one Greek letter took four items off a real audit.** The run
  said `[gsc_cannibalization.py] AttributeError: 'NoneType' object has no attribute
  'strip'`, and the script it named had run perfectly and written 42 KB of valid JSON.
  `subprocess.run(..., text=True)` decodes with the platform's preferred encoding; on
  Windows that is the ANSI codepage, and under cp1252 five bytes have no mapping at all
  — `0x81`, `0x8d`, `0x8f`, `0x90`, `0x9d`. `0x81` is the second byte of Greek **ρ**
  (U+03C1, `cf 81`), so one ρ killed the reader thread, `stdout` came back `None`, and
  the next line raised on it. Greek words without a ρ came through; the English half of
  the same site never triggered it. That is the whole of the apparent intermittency.

  **The child half was worse and was found by checking the other direction.** `print`
  encodes with the child's own stdout encoding, also the ANSI codepage, and seven
  scripts print `ensure_ascii=False` JSON — so with no `PYTHONIOENCODING` set they emit
  nothing at all, `UnicodeEncodeError`, exit 1. `site_crawl.py` is one of them, so the
  site-wide layer goes with it. Both halves are repaired where each is decided, and the
  probe measures both without needing a console.

  **Nothing here could have caught it**: every fixture in this repository is ASCII,
  including the tree the Windows CI job audits end to end.
  <!-- ki: a-greek-rho-killed-the-evidence-layer -->

5. **Two items say "branded query" and nothing here identifies one.** `KW-070`
   (`high`, *Own Your Branded Query (Homepage Ranks #1)*) asserts
   `branded.owns_homepage`, and `GO-139` (`low`, *Monitor & Improve Brand SERPs*)
   asserts `branded.ranks_first`. Both read a block that `find_branded` fills, and its
   docstring states the method without disguise: **"The highest-click query is treated
   as the brand term."** There is no brand detection — no site name, no `WebSite.name`,
   no `Organization.name`, no operator-supplied string. The top query by clicks is
   assumed to be the brand.

   **Measured on a real property rather than argued.** On a barbershop with 663
   impressions across 184 queries in 28 days, the top-click query is `barber paphos` —
   a head generic term. The queries that *are* branded — `marino barbero`,
   `marinos barber shop`, `barber marino` — carry **zero impressions between them**. So
   `KW-070` failed the site for not owning a query that is not its brand, and `GO-139`
   with it. The underlying fact is real and worth reporting — the site's head term is
   served by `/en/` rather than the homepage, at position 3.1 — but it is not the fact
   either title names.

   **This is the `GO-143` shape, one release later**: a title promising something the
   assertion does not measure. It is recorded rather than repaired because the repair
   is a registry decision with more than one honest answer — take the brand from the
   `WebSite`/`Organization` name the site already publishes, take it from an operator
   flag, or retitle both items for the head term they actually grade. The first two
   move live verdicts on every property; the third changes what two `high`-adjacent
   items claim. The probe records what the current method returns for a property whose
   brand and head term differ, so the day somebody chooses, the difference is visible.
   <!-- ki: the-branded-query-is-whatever-got-the-most-clicks -->

3. **The schema property tables are advice, and nobody has re-read them against the
   documentation they claim to follow.** `schema_required_props.py` carries
   `REQUIRED_PROPS` and `RECOMMENDED_PROPS` for eleven and twelve types; `MS-032`
   (`high`) reads the error count off the first and `TE-172`/`TECH-001` sit beside
   them. `GO-143`'s entry was in the second table and was wrong — not merely stale but
   an instruction to publish something untrue — and the release that found it checked
   one other type before stopping:

   * Google's Article documentation states **there are no required properties** for
     `Article`/`NewsArticle`/`BlogPosting`; this repository grades a missing
     `headline`, `author` or `datePublished` as an **error**, which is what `MS-032`
     counts;
   * its recommended list for the same types is `author`, `dateModified`,
     `datePublished`, `headline`, `image` — and this repository recommends
     `mainEntityOfPage` and `publisher`, which are not on it.

   Two of the two types examined diverge, so the remaining twenty-one have not been
   cleared by anything. **The divergence is not automatically a defect**: treating
   `headline` and `author` as required is a defensible editorial position for a
   checklist, and Google's word for a property is not the only word. What is missing
   is that nobody wrote down which it is, per type, and the file reads as though it
   were quoting an authority. The probe records both tables so a change to either is
   visible; closing this needs a reading per type, not a patch.
   <!-- ki: the-schema-property-tables-have-not-been-re-read -->

4. **Placeholder text in structured data decides almost nothing, and 0.89.0 made that
   slightly worse.** `schema_required_props.py` reports an unfilled template — `TODO`,
   `REPLACE`, `INSERT`, `example.com`, `[SHOUTED TEXT]` — as a **warning**, and two
   items read this script, and **neither can fail on one**. `MS-032` (`high`) asserts
   `summary.errors eq 0`; a placeholder is not an error, so the assertion passes and
   the `summary.warnings lte 3` band beside it is never consulted — the runner reads a
   warn band only when the assertion has already failed, so that band softens a page
   that has errors and does not judge one that has none. Measured: a `Product` with
   four unfilled properties produces **seven warnings, zero errors, and `MS-032`
   PASS**. `GO-143` (`low`) catches a placeholder only when it sits on a `WebSite`
   node, which is exactly its subject and not a general answer.

   **What 0.89.0 removed was one accidental exception to that.** The placeholder branch
   names any node's type whether or not that type has a property table, so a
   `SearchAction` carrying `REPLACE_ME` in its target emitted *SearchAction property
   'target' appears to contain placeholder text* — which `GO-143`'s old
   `(?i)WebSite|SearchAction` matched. That coverage was a side effect of a pattern
   written for the sitelinks search box, and it is gone with the pattern. Removing it
   was right: a placeholder inside search markup is not a fact about the site name, and
   this item is now titled for the site name. **Recorded because it is a loss, not
   because it was a mistake.**

   The general question is the one nobody has answered: an unfilled template published
   in structured data is a defect on any site, at any count, and no item here fails on
   one. Whether that belongs to `MS-032` as an error, to a new item, or to the warn
   band is a registry decision that moves live verdicts. The probe measures the current
   answer for a placeholder on a `WebSite` node, for four on a `Product`, and for the
   `SearchAction` case this release stopped catching.
   <!-- ki: a-placeholder-in-structured-data-almost-never-decides -->

- **Closed in 0.88.0 — a truncated crawl decided a whole site from part of it.**
  `site_crawl` caps pages and `broken_links.py` caps links, both reporting
  `truncated`, and nothing read it. The runner now withholds any verdict that passes
  *by absence* — `eq 0`, `none_severity`, `none_matching`, the three ways this
  registry says "we found none of the bad thing" — when the script says its input was
  capped. A FAIL is untouched, and an item that passes by *presence* is untouched:
  `LO-198` finds a LocalBusiness node on the pages it read, and reading more pages
  cannot take it away.

  **The entry said twelve and the command recorded beside it printed eleven; both
  numbers were about different sets and the real count is twenty.** Twelve is right
  for the entry's own subject — the items handed the crawl inventory whose assertion
  is a clean verdict. The command asked for `requires: crawl` plus a literal `eq 0`,
  which drops `CI-018` and `AR-162` (clean verdicts spelled `none_severity`) and adds
  `BL-083`, which never reads the inventory. `BL-083` belongs anyway, for a worse
  reason: `external_link_quality.py` caps at 200 distinct outbound links and was the
  one cap here that did not report itself at all, so a page with 500 of them had 300
  never requested and read as clean. Asking the same question of every cap rather
  than of the crawl found six more — GSC's 5,000-row page under `MS-023` and `KW-071`,
  the sitemap index walk that stops at 25 files under `GO-136` and `GO-138`, the
  stylesheet list under `TE-174`, and `MD-185` beside `MD-187`.

  **Twenty items, eleven of them `high`.** The predicate deciding which verdicts a
  cap can fake read three of the six ways this registry spells *nothing*; widening it
  to `len_eq: 0`, `len_lte: 0` and `falsy` brought in `CI-014`. Eight of the caps
  behind these items were invisible to `audit_thresholds` for want of a `# basis:`
  line, and naming them moved that ledger from 136 verdict-deciding numbers to 144 and
  `inherited` from 67 to 75 — the count becoming honest, not the tree getting worse.
  <!-- ki: a-truncated-crawl-decides-the-whole-site -->

- **Closed in 0.91.0 — the other caps have been read, and two of them answered for
  what they had not read.** Twenty-three scripts stood behind an item that passes by
  absence and said nothing about capping their own input. The question for each was one
  thing: whether the slice or row limit stands upstream of the number the item reads, or
  downstream of it. Upstream is the defect; downstream is `html_validator.py`, read in
  0.88.0.

  **Twenty-one are downstream or have no cap at all**, and the probe holds the reading
  per script rather than this paragraph — a list written twice is a list that drifts.
  Two were upstream:

  * `faceted_nav_audit.py` under `AR-163` (`medium`): `urls_from_page` stopped at 300
    page-derived URLs and `audit()` then built `rows` and `issues` from that list alone.
    The registry calls it `--from-page --fetch`, so this was live — a category page
    linking past the cap passed the item on findings nobody looked for;
  * `cache_compression_checker.py` under `TE-170` (`medium`): `max_assets = 25` stopped
    the asset walk before `issues` was assembled. **Unreachable as invoked** — the
    registry passes no `--include-assets`, so the loop never runs — and repaired anyway,
    because a cap that is wrong on a path nothing takes is wrong on the day something
    does.

  Both now report `truncated`, which is the whole repair: the 0.88.0 rule reaches an
  assertion only when the script says its input was cut, and a clean verdict over a cut
  input becomes `NO_DATA`. Both numbers moved from a default argument into a module
  constant with a basis line, so the threshold inventory can see them: 144 verdict-
  deciding numbers became 146 and `inherited` 75 became 77, the count getting truer
  rather than the tree getting worse.

  **How the reading was done, because a clearance is only worth its method.** An
  executor read all twenty-three against the single question and wrote one file per
  script; every `critical` and `high` one was then re-read here against the code, and
  in the rest every cap-shaped construct — a slice, a `break`, a `MAX_*` — was
  enumerated rather than eyeballed, because "this script has no cap" is a claim of
  absence and an impression cannot support one. Two readings survived that check by
  changing: `a11y_seo_checker.py` does slice findings rather than input, and
  `entity_checker.py` head-checks only the first three profiles — but `CN-036` reads a
  contrast count and `GEO-006` a missing-profile count, so neither slice can reach a
  verdict.
  <!-- ki: the-other-caps-have-not-been-read -->

2. **Two numbers nobody decided now decide whether fifteen items answer at all.**
   Before 0.88.0 `DEFAULT_MAX_PAGES = 100` and `DEFAULT_DEPTH = 3` bounded work: past
   them the crawl stopped and the items graded what it had. They now bound *answers* —
   a site past either reports `truncated`, and the items fed by that crawl say
   `NO_DATA` instead of `PASS`. That is the correct behaviour for the numbers as they
   stand, and it is the first time either number has been load-bearing, so neither has
   ever been examined as one. Both are `inherited`: present at import, chosen by nobody
   here.

   **It said twenty until 0.91.0, and twenty was never this entry's number.** The probe
   collected every item whose script reports truncation and whose assertion passes by
   absence, under a name saying these two crawl numbers silence them — but `CI-014`
   stops at `MAX_REDIRECT_HOPS`, `TE-174` at `MAX_SHEETS`, `MS-023` and `KW-071` at a
   Search Console row page, and `MD-185` at its own limit. None of those five is fed by
   the crawl. The set is now derived from `requires: crawl` in the registry and the
   other seven are recorded beside it as silenced by a cap that is not one of these
   two — which is where `AR-163` and `TE-170` joined in 0.91.0. Adding them made the
   miscount visible; it did not cause it.

   **The two do not bite alike, and the difference was measured rather than assumed.**
   Pages a sitemap lists enter the crawl at depth 0, so on a site with a sitemap the
   depth limit rarely applies at all — the good fixture reads five pages at `depth=1`
   and at `depth=3` and reports itself complete both times. Without a sitemap it
   applies immediately: a five-page chain at `depth=2` reads three pages and leaves one
   internal target unfetched. The page budget is the blunter of the two, and any site
   past a hundred pages meets it.

   **What is open is not the mechanism but the numbers**, and raising either costs
   requests linearly against a site's own budget. `--crawl-max-pages` and `--depth` are
   both operator flags, so the answer today is that a large site is audited honestly by
   somebody who raises them; whether that should be the default is a decision about
   what this tool costs to run, not about what is true.
   <!-- ki: the-crawl-defaults-now-decide-whether-items-answer -->

- **Closed in 0.82.0 — one test's robots.txt could answer another test's question for
  half an hour.** Found on the acceptance run for 0.80.0:
  `test_a_cache_hit_still_refuses_a_path_robots_forbids` reported *RobotsDisallowed not
  raised*, and did not reproduce in eight runs of its class and its module alone. It was
  not a flake. `safe_http.RATE_LIMIT_DIR` was `%TEMP%/seo-checklist-rate`, one directory
  for the whole machine; the robots entry in it is keyed by `scheme://netloc` alone and
  lives `ROBOTS_CACHE_TTL` — 1800 seconds. Every loopback origin in this suite is
  `http://127.0.0.1:` plus an ephemeral port, and the operating system hands those out
  again.

  **Measured, not reasoned.** Serving the test's own routes on a fresh port raises
  `RobotsDisallowed`. Writing `User-agent: *\nAllow: /` into the cache path for that
  same origin first — which is exactly what an earlier test on a recycled port leaves
  behind — reproduces the failure verbatim.

  **How large it actually was, counted rather than described.** The entry said two
  robots entries, from the two tests that start children. Snapshotting the shared
  directory around a full suite says **fifteen**, and the directory on the machine this
  was measured on had accumulated 3451 of them — each answerable for 1800 seconds after
  it is written, which is longer than a whole run takes. And it was not only
  across runs: logging every origin whose robots path was computed, across one run,
  gave 270 lookups over 21 origins — with `127.0.0.1:59747` served by one process at
  second 0 and by five different ones from second 10 to second 14. Two servers, one
  port, one run, well inside a 1800-second entry's life. So per-run isolation would not
  have been enough, and the shape of the repair follows from that number.

  **What closed it, in three parts.** `RATE_LIMIT_DIR` is gone as a module constant —
  a constant is what a caller can assign and a child cannot inherit — replaced by
  `rate_limit_dir()`, which reads `SEO_RATE_LIMIT_DIR` on every use and otherwise
  answers the same machine-wide default as before. The suite names its own directory
  once, and every child it starts inherits it. And a fixture server drops its origin's
  answer when it stops, which is the rule the directory alone cannot state: *an answer
  must not outlive the server that gave it.* For a real host, outliving one request is
  the point of the cache; for a throwaway origin whose port the system will hand to the
  next test, it was this defect.

  Each of the three has a test that fails when it is removed, verified by removing it:
  ignoring the environment fails three, a `forget_robots` that does nothing fails
  `test_a_stopped_fixture_leaves_no_answer_behind_it`, and a suite that stops naming
  its own directory fails `test_the_state_directory_is_not_the_one_an_audit_would_use`.
  <!-- ki: one-test-robots-answers-another -->

- **Closed in 0.81.0 — the walk that stops early stops answering.** When the chain runs
  past the cap, `has_loop` is now removed from the output rather than left at `False`, and
  `truncated` says why. Measured through the runner's own `evaluate()` on four chains: one
  ending after 3 hops gives CI-014 PASS; a loop closing at hop 3 reports the loop; a loop
  closing at hop 12 and an honest 12-hop chain both give **NO_DATA** — the walk did not
  reach the end, so nobody knows. `AR-150` still fails all three long chains on
  `total_hops lte 1`, which is honest: ten hops is a floor, and a floor above one is
  enough to fail. The cap is a module constant now, `MAX_REDIRECT_HOPS`, with a basis
  line, so the inventory can see the number it could not see before.

  Removed and not set to `None`: the runner reads an absent path as NO_DATA and a null one
  as a pass, because `not None` is True. The difference between the two spellings is the
  whole repair, which is why the test asserts the key is absent rather than falsy.

  Two branches withhold, not one. The other is a network error mid-chain: no verdict rests
  on it, because the runner replaces a result carrying `error` before any rule reads it,
  but the artifact is read by people too and on its own it would have said "no loop" about
  a chain nobody finished. And the boundary is tested from both sides: a chain of ten
  redirects that ends in a page reports `total_hops` 10 with `truncated` false and CI-014
  PASS, so a repair keyed on the count rather than on why the walk stopped fails that test
  — which is how it was checked, by installing that repair and watching it go red.

  The original follows:

  **A redirect loop that closes past the tenth hop reports as no loop at all, and
  `CI-014` passes the site.** `redirect_checker.check_redirects` walks the chain itself
  with `max_redirects: int = 10` — a default argument, so the threshold inventory, which
  reads module-level assignments, cannot see it. `CI-014` is `high` and asserts `has_loop`
  falsy.

  Measured on 2026-08-19 against a local server, three chains: a loop closing at hop 3
  gives `has_loop True`, `total_hops 3`; the same loop closing at hop 12 gives
  **`has_loop False`**, `total_hops 10`, *Too many redirects (>10)*; and a plain 12-hop
  chain that never loops gives the identical answer. So the two cases the item exists to
  tell apart become indistinguishable exactly where the walk stops, and the verdict it
  produces there is the passing one.

  `AR-150` still fails both — it asserts `total_hops lte 1` — so a site with a deep loop
  is not scored clean overall. That is a second rule catching it by accident, not this
  one being right. The honest repair is a withheld verdict rather than a louder one:
  when the walk stops at the cap, whether a loop exists is unknown, and `NO_DATA` is what
  this tree says when it does not know. That changes a live verdict and a script's output
  shape, so it needs its own release, and the number needs a basis wherever it ends up.

  Found by an independent reading of the 0.80.1 declarations, from the sentence saying
  `DEFAULT_MAX_REDIRECTS` does not govern these two items: it does not, and the number
  that does had never been looked at.
  <!-- ki: a-loop-past-the-tenth-hop-is-no-loop -->

- **Closed in 0.90.2 — a record can be stale under a stamp that says it is current.**
  `tests/census.json` shipped `GO-143` as *Provide Complete WebSite Data for the Site
  Name*, a title no item in this checklist has ever carried into a release. It was the
  first of two attempts inside 0.89.0: the census was re-recorded while it stood, an
  independent reader called it a promise the item does not keep — an imperative to
  publish something reads as a check that it exists, and this item never fails on
  absence — and the second title went into the registry alone. 0.90.0 and 0.90.1 passed
  over it. `tests/known-issues.json` had the right title the whole time, because the
  probe under the `GO-143` entry reads it out of the registry on every run: two ledgers
  disagreeing with each other, with a reader for neither pair.

  **The stamp is where it hid, and it did not get stale by itself.** A census takes its
  `registry_version` from the same registry load its titles come from, so nothing the
  tool writes can hold one from each. The shipped file holds one from each: the first
  title under `b0abf2819da0`, while a registry carrying that title hashes to
  `872e9c3fd2fc`. The content was recorded while the first title stood and the stamp was
  moved onto it afterwards — which is what a release does when the registry has changed
  under a record that costs five audits to re-take. The same commit did it to
  `tests/inert-findings.json` on its own, `66d1b2037c32` to `b0abf2819da0`, one line;
  that record happened to be right.

  **So the one field the suite read was the one field an edit could set**, and that is
  the finding rather than the wrong title. The reader that compares contents,
  `verdict_census.py --check`, costs five audits, is not in CI, and is run by hand at the
  start of a session; that is exactly where this surfaced, two releases late.

  **What was cheap all along.** Four fields of a census row — title, severity, source and
  script — are copies of the registry, and only the answers beside them need a run.
  `test_census.py` now re-reads all four against the registry on every suite, and
  `test_inert_findings.py` does the same for the two fields its record copies. The probe
  re-reads the ledgers as they ship and then, once per copied field, a census with that
  field moved: a comparison that has stopped comparing reports zero exactly like a tree
  that is in step, and one moved title witnesses one field of four.

  **The half that costs a run is read too, because the cost was assumed.** The verdicts
  beside the copies were left to a hand-run command on the argument that five audits are
  too much for CI. Measured: 101 seconds for all five trees. `verdict_census.py --check`
  is a CI job from this release and `tests/inert_findings.py --check` a step in both
  existing ones, so a recorded ledger that stops describing this tree now fails on the
  push rather than at the start of somebody's session. Neither says a verdict is right —
  that is the oracle's question and a person's; they say the record is not lying about
  what this tree answers.
  <!-- ki: a-census-copied-a-title-no-item-has -->

---

## Fixed in 0.9.0

Found by replacing six crawls with one, and by two four-line sweeps that the release
also taught to derive their own coverage.

- **The crawling half of issue 1.** `site_crawl.py` crawls once into an inventory; the
  ten site-wide items read it. 97 → 72 requests for one audited page of the fixture,
  and the site's inner pages went from six fetches each to two. The report now lists
  broken URLs with the pages that link to them.
- **AR-149 could not fail, and had been NO_DATA on every site for a release.** The item
  is titled "Eliminate Internal Redirects" and asserted that `internal_links.pages` was
  non-empty — true of any site that answers. Then 0.8.0 introduced a `fetch_error` set
  unconditionally (the check ran before the field it tested was filled), so the item
  was NO_DATA everywhere; its contract exemption said "no internal redirects to find
  without a server that redirects", which was true, unrelated, and hid both defects.
  It now reads `summary.internal_redirects`, which the shared crawl can measure.
- **Twelve more items graded a site that answered nothing**, three of them `critical`:
  `indexability_matrix.py` reported a page "not indexable" and robots.txt "allows it",
  `canonical_checker.py` reported a missing canonical, `local_seo_checker.py` reported
  a business with no local signals, and `orphan_pages_from_sitemap.py` reported no
  orphan pages — all about a host that refused every connection. Every one was outside
  0.8.0's sweep, because that sweep's script list was maintained by hand.
- **AR-146 could not fail either.** It asserted `pagination` was truthy, and
  `pagination` is a dict that always holds both keys — `{"prev": None, "next": None}`
  is a non-empty dict. Its twin CN-055 asserted `pagination.next` was truthy, so every
  page that is not part of a paginated series — nearly every page audited — was told to
  "make infinite scroll crawlable". AR-146 now reads a pagination `issues` list;
  CN-055 became an LLM item, because nothing here observes scroll behaviour.
- **Five checks accused every correct site.** `schema_required_props.py` asked for
  `name`, `position` and `item` *on the BreadcrumbList*, where no correct markup puts
  them (they belong to each `ListItem`), and its placeholder detector tested `"["`
  against a JSON dump of the value — so every property whose value was a list or an
  object was "placeholder text". AR-158 failed every site with a working breadcrumb,
  twice over. `image_inventory.py` and `image_weight_audit.py` treated the first `<img>`
  in document order as the LCP candidate regardless of size, so CN-054 and MD-185
  reported a correctly lazy-loaded 64px logo as a deferred LCP image.
- **The W3C validator answering "I could not fetch your page" was read as "no
  errors".** Nu reports that as `type: non-document-error` with a 200, so CI-017 and
  TE-181 said the HTML validated on any page the validator could not reach — a 403
  aimed at its user agent, a timeout, a TLS problem. The same family as the outage
  0.8.0 fixed, one step further in: the service answered, and the answer was not about
  the page.
- **The good fixture had a dead internal link on purpose**, planted before the pair
  existed and invisible while TE-168 checked one page's links. A site-wide check found
  it immediately and warned about the fixture the pair calls good.

## Fixed in 0.8.0

Found by writing the last 43 scripts' tests. The first one written found nothing; the
one written *last* found sixty-two items, which is worth remembering next time the
cheap sweeping test gets postponed for the careful per-script ones.

- **62 items graded a site that answered nothing.** A script that fetched nothing
  exits 0 and returns its defaults, and the defaults grade. The entry-reachability
  gate catches a site dead *before* an audit; nothing caught one that stops answering
  *during* it. Fixed in the runner for every script at once, plus twelve scripts that
  recorded no failure for the runner to read.
- **GEO-007 read `key_valid`, a field never emitted** — NO_DATA on every site,
  including one hosting its IndexNow key correctly. It outlived MS-031 because the
  item needs a secret to run, so nothing ever probed its output.
- **GO-132 could not see the ordinary GA4 duplicate** (two copies of the loader, which
  is how a theme and a plugin collide), **BL-083 could not see a dead domain** (no
  status code means no `status >= 400`), and **AR-163 could not fail at all** (a crawl
  trap needs a set of URLs; the registry passed one).
- **Seven items reported a site defect when a third party was unavailable.** `None`
  pre-seeded into a summary reads as a failing value to `eq` and `truthy`; an empty
  `issues` list reads as "nothing wrong" to `none_severity`. A busy W3C validator
  became "your HTML has errors"; an expired token became "you do not rank first for
  your own brand".
- **A 404 page was analysed as thin content**, so one dead internal link produced a
  `Critical` finding advising somebody to expand a page that does not exist.
- **`entity_checker.py` dropped the address half of its own NAP check**, and
  `jaccard_from_minhash` compared signatures without `strict`, which would bias
  similarity downwards and lose duplicate pages rather than raising.

## Fixed in 0.7.0

Two of these were found by supplying the fixture pair with the artifacts it had been
withholding, and two by turning on a linter that had been sitting in
`requirements.txt` unused. Both are the same lesson as every other release here:
the defects are not where anybody was looking.

- **An artifact was trusted without being asked which page it describes.** A
  `--cwv-json` or `--rendered-json` file decides eight items, two of them `high`, and
  it is the only evidence in an audit that cannot be checked by measuring again. A
  trace of a staging copy, or of yesterday's URL, produced eight confident verdicts
  about a page nobody measured — and looked like a clean result. Now refused with the
  reason, which is a different sentence from "missing input": one tells the operator
  to measure, the other tells them the file they made is about somewhere else.
- **A single measured page became a verdict about every sampled page.** `--sample`
  runs inherit the run context, so the same file was read once per URL and the
  aggregate said "4/4 pages" about pages no browser had opened.
- **MB-096 and MB-097 failed sites for following the recommendation.** The image
  audit read `<img>` attributes only, so a `<picture>` offering webp through
  `<source>` with a png fallback in the `<img>` — the recommended pattern — counted
  as having no modern format and no `srcset`. The one guaranteed-old thing in that
  markup was the only thing inspected.
- **The tool that finds drift had drifted.** `probe_shapes.py` held its job list by
  hand and named seven scripts that no longer exist while missing three the registry
  reads. Jobs now come from the registry.
- **The Python floor was undeclared, and then unexercised.** `>=3.10` is now stated
  and CI runs it, tied together by a test that also measures the claim against the
  tree's syntax.
- **Two half-implemented checks, found by the linter's first run.**
  `entity_checker.py` computed whether a street address is visible and dropped it, so
  only the phone half of "visible phone/address" was ever reported;
  `hreflang_checker.py` computed an `xhtml:link` flag it never returned.
- **The report claimed its own wording was fully translated.** Six of 51 strings were
  not, and they were the caveat block. The warning now counts instead of asserting.

## Fixed in 0.5.0

Found by writing the first tests the evidence layer has ever had. Every one had been
reporting the same verdict on every site ever audited, and the count is the point:
after 0.1.0 removed fifteen dead regex assertions, eighteen more were sitting in two
families the pattern audit could not see.

- **Five `critical` items could not fail.** CI-009 asked for `critical`/`high` issues
  from a script whose whole vocabulary is `warning`/`error`. CI-001 "is this URL
  indexed" asserted the same field, with the same rule, as CI-005 "does robots.txt
  block it" — so `noindex` passed it. SP-107/SP-113/SE-119 compared a rating to
  `"fast"`, a word only CrUX uses, so a fast page with no CrUX sample **failed**.
  SP-108 asserted that field data exists, failing every site too small to be sampled.
- **Ten more items** asked for `critical`/`high` over scripts that only say
  `error`/`warning`/`info`. The runner now maps the two vocabularies onto each other
  and those items carry a `warn` rule, so an error fails and a warning warns.
- **Two items read prose that has no severity at all.** `robots_checker.py` and
  `security_headers.py` append plain strings to `issues`; the latter was printing
  "Site not using HTTPS" while TE-175 reported PASS. Both now read structured fields.
- **One item read a field that was never emitted.** MS-031 asserted `meta_keywords`
  with `missing_is: pass`, and `parse_html.py` had no such key.
- **`tools/audit_assertions.py` now audits severity rules and asserted paths**, not
  only patterns, so each of the three families fails the build instead of the audit.

## Fixed in 0.4.0

Every one of these except the first was found *by* the first, within an hour of it
existing. That is the argument for the feature, and it is the fourth session running
in which looking at output beat reading code.

- **The SSRF guard had no escape hatch**, so no fixture site could be served locally
  and the live path could only ever be exercised against a real third-party site.
  That is how 0.2.0's rate limiter crashed 36 of 56 scripts with every test passing.
  `--allow-private` is off by default and deliberately narrower than "not public":
  loopback, RFC 1918, ULA and CGNAT only, with **link-local still blocked** because
  cloud instance metadata answers at 169.254.169.254 and the URLs a crawl follows
  come from the site. CI now serves `tests/fixtures/site/` and fails if any evidence
  script crashes.
- **An address was given a registrable domain.** `127.0.0.1` became `0.1`, the run
  built `sc-domain:0.1`, and both Search Console scripts crashed. On a public IP it
  would have been quieter and worse: a valid-looking property nobody owns answers
  with nothing, and nothing reads as a site with no search traffic — the same failure
  as the pre-0.2.0 `something.github.io` → `github.io` bug, through a new door.
- **External-API checks crashed on a private host** instead of reporting `NO_DATA`.
  PageSpeed measures from Google's network and a Search Console property cannot exist
  for an address on a LAN; neither is a defect in the site or the tool, and "script
  failed" sends the reader to open a script that works. `NO_DATA`, not `N/A`: the
  items apply, so coverage drops — which is the honest thing for a staging audit.
- **A robots-disallowed sitemap URL was counted as an orphan.** 0.3.0 subtracted the
  refusals the crawl recorded, and a crawl only tries what the site links to, so a
  disallowed URL that nothing links to arrived with no refusal attached. That is the
  ordinary case: a page is usually unlinked *because* it is blocked. The claim in the
  0.3.0 notes below was therefore true only for linked URLs.
- **The report never said when it was not describing the public site.** A
  `--no-page-guard` run produced a clean-looking deliverable that never mentioned it
  had scored a Cloudflare interstitial. The runner recorded and printed it; the file
  handed to a client did not. Now three facts — private host, scored interstitial,
  content-free entry page — appear above the summary on every surface.

## Fixed in 0.3.0

Kept because the reasoning is the useful part, and because a reader who saw the old
warning deserves to find out what happened to it.

- **`--sample N` took the first N sitemap URLs in document order.** Sitemaps are
  ordered by section or by date, so that gathered one corner of the site while the
  report said "5 of 5 pages checked". Now spread by an arithmetic stride across the
  whole list — still reproducible, since the step is not random.
- **The report showed two scales.** The per-category score was an unweighted pass
  rate next to a severity-weighted headline: one category read 25 where its weighted
  score was 42, and the bars were *ordered* by the unweighted number. Both now use
  the same weighting, and each bar carries the worst open severity, because no single
  number can show "one failing critical in an otherwise clean category".
- **The crawlers ignored `robots.txt`.** Now honoured for pages the tool discovers
  itself — followed links, sampled sitemap entries, and any redirect they land on —
  and deliberately *not* for the URL the operator supplies, since a blanket check
  would refuse the 40-odd scripts that fetch it and bury a `critical` finding under a
  collapsed audit. `Crawl-delay` is obeyed when it asks for more patience than
  `--max-rps`, ignored when it would ask for less.
- **`broken_links.py` had no cap.** Now 200 links, internal first, and it reports
  when it truncated.

The subtle part of the robots change: `orphan_pages_from_sitemap.py` computes
orphans as `sitemap − reachable`, so a URL we declined to fetch would have dropped
out of `reachable` and been reported as an orphan — GO-137 fails on one. Refusals
are tracked separately and subtracted, and a sitemap listing robots-blocked URLs is
now its own finding, which is the sharper one anyway.

That held only for URLs the crawl actually tried, which is the half of the problem
0.3.0 could see. See the 0.4.0 list above for the other half.

## Not defects

Recorded here because they get mistaken for defects:

- **10 of the 15 backlink items are `MANUAL`.** Judging link quality needs a link
  index this plugin does not have. A fabricated toxicity score is worse than
  silence.
- **31% of the registry is not machine-decided** (35 `llm`, 32 `manual`). The
  distribution is what matters: **1 of 19 `critical` items** is not
  machine-decided, against 59% of the `low` ones. The un-automatable residue sits
  where it costs least.
- **Coverage below 100% on a real run.** That is the metric working. An audit that
  reported 100% coverage would be hiding the questions it could not answer.

## Fixed in 0.33.0

- **A guard checked the shape of an entry point only when one existed.** The AST
  test required an existing `if __name__ == "__main__"` block to come last, but did
  not require test files to have that block. `test_evidence_apis.py` and
  `test_evidence_scripts.py` therefore exited successfully after running zero tests
  directly, while discovery kept CI green. This is the same absence-pattern failure
  already recorded in §6 for `meta_keywords`: validating a present value says
  nothing when the whole value is missing. The guard now requires the entry point in
  every test file as well as checking its position; both files run their full suites
  directly.

## Fixed in 0.35.0

- **A host shared by several locales was allowed to classify itself as their
  separator.** A Lithuanian root on `.lt` read as `ccTLD` beside `/en/` and `/ru/`,
  producing a false `mixed` failure. Host-based readings are now discarded whenever
  that host carries more than one locale; the path and query decide those alternates,
  while genuinely separate ccTLDs and cross-host mixtures keep their old verdicts.
- **The registry broke its founding principle: “nothing to check” was scored as
  “fine.”** MB-102 and MD-190 passed pages with no video because an empty issue list
  satisfied both assertions. The new, optional `applies_when` rule makes exactly
  those two items N/A when `videos = 0`, with the reason in evidence; their
  `SAME_CHECK` relationship still makes video SEO carry score weight only once.
- **A missing Safe Browsing key looked like failed measurement.** SE-114, SE-116,
  TE-171 and TE-179 now distinguish a networkless mode (N/A) from a network-capable
  run missing either supported environment variable (NEEDS_INPUT). TE-167 uptime and
  TE-178 neighbours remain runnable without the key; TE-179's title mismatch remains
  deliberately out of scope.
- **Sample evidence described a set by one member.** `aggregate_pages` already took
  the verdict and measurement from the same worst page, but then prefixed that one
  value with `N/M pages`, implying all matching pages agreed. This is the second
  repair to the same line. Evidence now names the page that supplied the value and
  says when the matching values differ. The general pattern is the defect: one member
  cannot describe a set unless agreement was actually checked.
- **IN-122 promised hreflang return tags without requesting their verification.**
  Network modes now append `--verify-returns` through the per-run flag path; archive
  mode still makes no network calls. The assertion reads a dedicated
  `verified_and_valid` result, so the evidence states that verification happened
  instead of inferring it from a zero critical-issue summary.
- **The image inventory treated accessible and nonexistent images as defects.** An
  absent `alt` attribute is counted separately from deliberate `alt=""`; `<img>`
  elements without `src` are excluded, and both empty-alt and skipped counts are
  reported rather than hidden.
- **Contact detection equated English words with contactability.** `tel:` and
  `mailto:` are now language-neutral trust links, while the broader multilingual
  limitation remains recorded in §6 instead of being fitted to one live site.
