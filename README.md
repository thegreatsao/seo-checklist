# seo-checklist

A deterministic SEO audit for Claude Code. One fixed registry of 217 checks, run
the same way every time, with a status on every item and an honest account of
what could not be decided.

Version 0.93.9 — see [CHANGELOG.md](CHANGELOG.md). The last four verdicts decided by
matching words in a message now read counted fields, and three of them move: GO-138's
`404` matched a 404 and not a 500, so a sitemap of URLs returning 503 passed; MB-095
counted a message its script only emits when told to fetch images, which the registry
never told it to do, so every live run passed a page whose weights were never measured.
Before that, `0.92.0` made the category bars fold twins the way the headline has since
0.22 — six of the nine pairs cross categories, so 36% of `media`'s weight belongs to a
carrier elsewhere — and `0.92.1` corrected fourteen counts stated in prose, none of which
matched the registry, and put a gate behind each one — `0.93.1` did the same for the
one inside `checklist.json` itself, which said the plugin adds 15 checks where it adds
17, and which no gate could see because a constant in the generator is reproduced by the
staleness check and compared with nothing. `0.93.4` counts the rest of them: 166 sets in
`scripts/` and `tools/` decide what this tool does, and sixteen are read by anything, and
`0.93.5` gives `SKILL.md` a contract table saying, per section, what the tool guarantees
and what the operator has to supply. `0.93.6` widens the count ledger past the protocol
and corrects sixteen more numbers about this tree, ten of them in this file and in the
scripts' own docstrings. `0.93.7` puts a ratchet under the 77 thresholds nobody here has
defended, and forbids one of them to argue its own number. `0.93.8` derives the assertion
language's nineteen operators from the evaluator instead of searching its source for a
substring, and refuses a rule that names two of them.

[KNOWN-ISSUES.md](KNOWN-ISSUES.md) is the ranked list of what is still wrong,
measured rather than suspected. Its largest entry closed in two halves: 0.9.0
replaced six independent crawls with one crawl whose record the audit keeps — which
is also what lets the report name the broken URLs rather than count them — and
0.10.0 gave the run a shared response cache, so a URL is fetched once by the whole
audit instead of 37 times by 36 scripts. One audit of the seven-page fixture, one page
audited, went from **97 requests to 16** across the two releases, with all 214 verdicts
unchanged — 214 because that was the registry then.

[ROADMAP.md](ROADMAP.md) says where this stops: 1.0 is defined there as a claim that
can be checked rather than a number, and the file reports the tree's distance from each
of its three clauses with the command that prints it.

## Why it exists

The usual failure of LLM-driven SEO tooling is that the model picks what to run.
Two audits of the same site check different things, and neither tells you what was
skipped — so the score looks like a measurement when it is really a sample of
whatever the model remembered.

This plugin separates the two halves of that problem.

`resources/config/checklist.json` is the contract: 217 items, each naming what
answers it — a script plus an assertion over that script's output, a Search
Console call, a language-model judgement, or a human. Nothing in the registry is
executable; assertions are declarative and interpreted by the runner. Coverage is
therefore a property of the registry, not an accident of the run.

The score never travels alone. It carries the share of the registry's weight it
was computed over, and beneath it every item lands in exactly one bucket named for
whose action moves it:

```
SEO Score 92/100 — over 99 items, 51% of the weight in scope
  decided            99
  waiting on you     55   (38 unanswered LLM items, 17 missing inputs)
  needs a person     34
  undecided          27
  not applicable      2
                   ---- 217 items in the registry
```

Those are real numbers from one run against `tests/fixtures/good` on loopback with
`--sample 3` and no Search Console key, not an illustration.

There was a single `Coverage %` until 0.16 and removing it was the point: it added
together how far the tool reached, how much work the operator had done, and how much
of the checklist was never the audit's job, then moved for any of the three without
saying which. The buckets add up to the registry, so nothing hides in a denominator,
and `waiting on you` is a list of things to do rather than a percentage that blames
nobody.

## What is in the registry

217 items: the [Plerdy 200-point checklist](https://www.plerdy.com/seo-checklist/) plus 17
checks it does not cover — GEO/AI search, `llms.txt`, AI-crawler policy, IndexNow,
schema guards, lab Core Web Vitals from a local trace, and two mobile-layout
measures read from a rendered page.

| Answered by | Items |
|---|---|
| a script, asserted against its real output | 145 |
| a language model reading the page | 38 |
| a human | 31 |
| Search Console, with no API to answer it, so a person opens the UI | 3 |

Those 145 items collapse to **66 unique process launches** over 58 distinct scripts —
the runner deduplicates by script *and* arguments, so `pagespeed.py` runs once, not
six times, and `MB-107` and `MB-108` cost no launch at all: they read the artifact
five other items already read.

Nine items moved from script to judgement in August 2026 as a correction, not a
design change: each asked a script about wording it never emits, so each had been
reporting PASS on every site (see "Assertions that cannot fire"). Five then came
back to being measured, from a rendered page rather than from HTML — font size,
link distinctness, overlays and tap targets are computed values, and a model
reading markup cannot see them. The three that stayed judgements are judgements: a
close keyword variant and a localised title are not measurements.

Every item also carries an `effort` estimate, so the fix list is ranked by
severity **against** effort rather than by severity alone: ranking by severity
alone puts a week of rewriting above a one-line meta tag. Effort is a
per-category heuristic, not a per-item estimate, and the report says so.

Every result records the `registry_version` it came from, and `--diff` warns when
two runs used different registry versions, profiles or modes — otherwise "no
status changes" could mean the checklist itself changed underneath.

## Install

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
```

Core requirements are `requests`, `beautifulsoup4`, `lxml`. Search Console checks
also need `google-auth` and `google-api-python-client`; without them those items
report `NO_DATA` with a reason rather than failing the run. `archive` mode needs
no HTTP library at all, only an HTML parser.

## Run

```bash
S=skills/seo-checklist
python3 $S/scripts/checklist_runner.py https://example.com               # full, live
python3 $S/scripts/checklist_runner.py https://example.com --mode page   # one page
python3 $S/scripts/checklist_runner.py https://example.com --archive ./backup
python3 $S/scripts/checklist_runner.py https://example.com --diff        # vs previous run
python3 $S/scripts/checklist_runner.py https://example.com --profile ecommerce
python3 $S/scripts/checklist_runner.py https://example.com --sample 10   # several pages
python3 $S/scripts/checklist_runner.py https://example.com --links-csv ~/Links.zip
python3 $S/scripts/checklist_runner.py http://localhost:8000/ --allow-private
python3 $S/scripts/checklist_report.py checklist-results.json            # render output
python3 $S/scripts/checklist_report.py checklist-results.json --lang ru  # Russian report
```

### Site profiles

`--profile default|local|ecommerce|saas|blog|media` narrows the registry to what
a given kind of site can be judged on. An excluded item is `N/A` with the profile
as its reason and touches neither metric.

Omit the flag and the run detects the site type first, then asks with that
suggestion pre-selected — Enter accepts it, anything else overrides it. Detection
reads structured data, platform fingerprints and cart/pricing markup rather than
wording, and it runs on the entry page the audit was going to fetch anyway, so it
costs no extra request. Thin evidence produces `default` and says so instead of
guessing.

`--profile auto` accepts the detection without asking. That is the only way a
heuristic narrows scope here, and it takes an explicit flag, because passing it
is a decision.

The prompt appears **only** when a terminal is attached: CI, cron and background
runs use `default` — the full registry — mention what detection would have
suggested, and print why they did not act on it. A question nobody can see is a
hang. `--no-prompt` forces that behaviour anywhere.

Every non-answer — Enter, nonsense, EOF — resolves to `default`, the widest
scope. Guessing a narrower profile would drop checks and lift the score without
anyone deciding to. For the same reason no profile may exclude a `critical` item;
a test enforces it. An unknown name is an error, not a silent fallback.

### Several pages at once

`--sample N` picks N same-host URLs (sitemap first, on-page links second) and runs
the page-level checks against each; site-level checks still run once. The worst
verdict wins, but the evidence carries the count — `1/5 pages: title is 61
characters` is exactly what a single-page audit would have missed.

The picks are spread evenly across the sitemap rather than taken from the top.
Sitemaps are ordered — by section, or by date — so the first N gathers the newest
corner of one category and calls it a sample; an even stride crosses whatever the
sitemap is grouped by. The step is arithmetic, not random, so an unchanged sitemap
yields the same pages next month, which is the constraint the whole tool is built
on. Until 0.3.0 this took the first N and the report still said "5 of 5 pages
checked"; it now spans the site.

The entry URL is always included. Sampled URLs that `robots.txt` disallows are
dropped and the count is printed — those are pages *we* chose to look at, so the
site's instruction to crawlers applies, which is not true of the URL you handed in.

Candidates come from `<a href>` only, asset extensions are rejected by path, and
anything served as a non-page is dropped at fetch time. Because the worst verdict
wins, a single stylesheet in the sample would otherwise fail every page-level
check and condemn the site.

### Redirects to another host

When the entry URL redirects to a **different host**, the destination is what
gets audited, and `requested_url` records what you asked for. Otherwise the run
disagrees with itself: `--sample` filters candidates on the old host and collapses
to a single page, and `sc-domain:` is derived from a domain the service account
has no property for — both of which fail quietly, looking like a small site with
no search traffic.

A same-host hop (`/` → `/en/`, http → https) keeps the URL you gave, so
`redirect_checker.py` still sees the hop it exists to report.

### When a script does not finish

A timeout and a crash both leave the item `NO_DATA`, but they are recorded apart —
`error_kind` per item, `script_failures` for the run, `T` instead of `!` in the
progress line. A timeout means the site was slow and the run is worth repeating
with a longer `--timeout`; a crash means the script is broken and repeating it
changes nothing.

### When the site cannot be read

If the entry page does not load — DNS failure, 4xx/5xx, a non-HTML response —
every check that reads the live site is `NO_DATA` with the reason, no script runs
against it, and **no score is printed at all**. Search Console items still run,
because Google's stored history does not stop existing when a site goes down.

Most evidence scripts exit 0 with an empty result when they cannot fetch
anything, and an empty result satisfies exactly the assertions this registry is
built from. Without the gate, a host that does not resolve scored **61/100 on 40
fabricated passes**.

A page that answers **200 and is not the site** is caught too: a bot-protection
challenge (a vendor fingerprint in the markup plus almost no visible text) or a
soft 404 (a title that *equals* a not-found phrase). Both are treated as
unreadable, and the offline checks are gated as well — the file parses fine, so
nothing else would stop them from grading an interstitial's twelve words. A saved
challenge page in `archive` mode used to produce 6 passes and 10 failures.

Both tests are narrow on purpose. An article that quotes
`cdn-cgi/challenge-platform`, or one titled "How to fix 404 errors", is a real
page and is still audited — refusing it would be the same bug pointing the other
way. `--no-page-guard` overrides the guard and records that it did.

### Incoming links

The Links report is the one part of Search Console with **no API at all**.
`--links-csv` reads the UI export (Search Console → Links → Export) and answers
three items: link concentration, total links, linking root domains. The rest of
the backlinks block stays manual — judging link quality needs a link index this
does not have, and a fabricated toxicity score would be worse than the silence.

| Mode | Reaches | Use when |
|---|---|---|
| `live` | fetch, crawl, external APIs | full audit of a reachable site |
| `page` | fetch, external APIs | one page, much faster |
| `archive` | nothing — local files only | you have a copy of the site, not a URL |

Anything a mode cannot satisfy is `N/A` and drops out of both metrics. "We did not
crawl" must never read as "the site failed".

Deliverables: `CHECKLIST-REPORT.md`, `CHECKLIST.html` (filterable; manual items are
checkboxes persisted in the browser), `LLM-QUEUE*.md`, and
`checklist-results.json`, also archived under `.seo-runs/<domain>/`.

History filenames carry milliseconds, and a run never writes over an existing
file: at second precision two `--only` runs finished inside the same second and
the second one destroyed the first — which is the run `--diff` would have compared
against. `--diff` orders history by the timestamp inside each file rather than by
its name, so a directory holding both filename formats still finds the newest, and
a history file that will not parse is skipped instead of ending the run.

## Search Console

Auth is a **service account**, not user OAuth:

1. In Google Cloud, create a service account and download its JSON key.
2. Enable the Search Console API for that project.
3. In Search Console, add the service account's `client_email` as a user on the property.
4. Save the key as `~/.config/gcloud/gsc-service-account.json`, or point
   `GSC_CREDENTIALS_PATH` at it.

The property defaults to `sc-domain:<registrable domain>` — `www.example.com` is
not a property, `example.com` is. Override with `--gsc-property` for URL-prefix
properties.

The registrable domain comes from a bundled snapshot of the [Public Suffix
List](https://publicsuffix.org/), refreshed with
`tools/refresh_public_suffix_list.py`. It is bundled, not fetched at audit time,
so a run answers the same offline and next month. The seven hard-coded suffixes it
replaced handled `example.co.uk` correctly and every platform domain wrong —
`something.github.io` became `github.io`, `myapp.vercel.app` became `vercel.app` —
so the default property was one nobody owns and every Search Console item came
back empty, which reads as a site with no search traffic.

Seven items are answered from live data: cannibalization, branded-query ownership,
reported opportunities, and — via the URL Inspection API — whether Google indexed
the page and which canonical it picked. That last one earns the setup on its own:
a page can declare `rel=canonical` to itself and still have Google choose a
different URL, and nothing in the page reveals it.

Three items report `MANUAL` even with working credentials, and this is not
missing wiring: **the Search Console API has no endpoint for manual actions, the
Index Coverage report, or mobile-usability signals.** Those exist only in the web
UI; mobile usability was withdrawn from the API in December 2023.

They are `MANUAL` rather than `NO_DATA` because they are answerable today — by a
person opening Search Console. `NO_DATA` says the audit tried and could not
decide, which invites somebody to go fix the tool. Neither is counted as decided,
so the score's weight share is the same either way.

Without a key, those items are `NEEDS_INPUT` in `live` and `page` mode — the run
could have asked, and one argument is what stands in the way — and `N/A` only in
`archive`, which makes no network calls at all. The difference matters: `N/A` is
out of scope entirely, so reporting a missing key that way would shrink what the
score has to speak for precisely where the audit is thinnest. `NEEDS_INPUT` puts
those seven items on the operator's list instead, under their own heading.

Credentials are never transmitted anywhere, and Search Console data is written only
to local files. Values from `INDEXNOW_KEY` and `PAGESPEED_API_KEY` are replaced
with `<redacted>` everywhere in `checklist-results.json` and `.seo-runs/` — the
run log is built from each script's argv, so a key passed as an argument would
otherwise be written out verbatim in the file you hand to a client.

## Answering what no script can

`--llm-answers` merges the model's 36 items, `--manual-answers` the 34 a person has
to look at. Neither can overwrite a verdict a script reached, and neither can answer
the other's items — one file that could do both would let a person quietly settle the
questions the queue exists to make somebody read the page for.

A manual answer needs a reason; a `PASS` with nothing beside it is refused by id.
Every decided item carries `decided_by` (`measured` / `model` / `claimed`), and the
report discloses the mix whenever it is not all measurement:

```
SEO Score 70/100 — over 109 items, 57% of the weight in scope
  of the decided: 3 claimed, 106 measured
```

That line is the guard. Thirty-four items a person can answer is also thirty-four
`PASS`es a person can type, and the only thing that keeps a claim and a measurement
apart in a delivered report is the record of which was which.

## The LLM queue is not optional

38 items cannot be settled by a script — grammar, cloaking, doorway patterns,
translation quality, ad density, whether the page was written for a reader. Left
unanswered they stay `LLM_PENDING` and cap coverage.

The report splits them into one file per **lens** — the evidence an item is
answered from, which is not the same as the checklist category it sits in. Four
agents can work concurrently, each reading its own slice once:

| Queue | Agent | Items |
|---|---|---|
| `LLM-QUEUE-copy.md` | `seo-llm-copy` | 19 |
| `LLM-QUEUE-layout.md` | `seo-llm-layout` | 13 |
| `LLM-QUEUE-locale.md` | `seo-llm-locale` | 3 |
| `LLM-QUEUE-market.md` | `seo-llm-market` | 3 |

Answer each `PASS` / `FAIL` / `WARN` / `N/A` with concrete evidence, then merge:

```bash
python3 skills/seo-checklist/scripts/checklist_report.py checklist-results.json \
    --llm-answers answers.json
```

The merge only overwrites `LLM_PENDING` items; an answer file cannot flip a verdict
a script established. When the page does not support a verdict the answer is `N/A`
— inventing a `PASS` to lift the score corrupts the one metric this exists to
protect.

## The report is written for the person paying for it

Four layers, widest audience first, in one file:

1. **What this means** — three plain sentences before any number: how many things
   were checked, how many need work, how many are quick, and how many could not be
   settled by measurement at all.
2. **Where the problems are** — a bar per category, worst first, with one line
   explaining what that group of checks is about and what it costs when it is wrong.
3. **What to do first** — one card per failing or borderline check: how bad, how
   much work, what was measured *in words*, why it matters, what to do. The
   assertion's own output is folded away under "technical detail", not deleted.
4. **Every check, with its raw evidence** — collapsed. The audit trail, unchanged.

The measurement is phrased from structured data (`measure` on each item: the
operator, the threshold, the observed value, and up to four examples), so
`summary.thin_pages = 6 (want 0)` reads as "Found 6; there should be none" and
`len(allowed_urls) = 4` names the four URLs. Printing an assertion's internals in a
client's report is the same category of mistake as showing them a stack trace: the
old report did it in every row of every table.

Explanations live in the translation files rather than the code, per category
rather than per item — sixteen texts can be kept true, and 217 would drift out of
step with a generated registry the first time an item changed.

**Client-facing reports are English-only in 0.2.0.** `--lang ru` translates the
report's own wording and all sixteen category explanations, but `item_titles` and
`item_fixes` are still empty, so item titles and recommendations come out in the
registry's English — a half-Russian document. The report says which layers are
untranslated on stderr rather than letting the reader work it out. Falling back to
English is deliberate: a reader who gets the wrong language can still act, and a
reader who gets a gap cannot.

## Politeness

An audit is a burst by construction: the runner launches its evidence scripts
concurrently, and several of them walk a sitemap or a link list inside their own
process. Requests are paced to **4 per second per host by default**, shared across
those processes through a lock file — an in-process limiter would simply let eight
scripts go at once. `--max-rps N` changes it, `--max-rps 0` removes it, and
`SEO_MAX_RPS` does the same for a script run on its own.

That lock file, and the cached `robots.txt` answers beside it, live in one directory for
the whole machine — deliberately, because pacing is a promise to somebody else's server
and two audits started a second apart have to queue behind each other rather than each
starting fresh. `SEO_RATE_LIMIT_DIR` names it when a run needs its own: a sandbox with no
writable temp directory, or a harness whose origins are recycled loopback ports. It is
read on every use and inherited by the processes a run starts, which a module constant
was not.

A `429` or `503` carrying `Retry-After` is honoured once, up to 30 seconds. Past
that the request fails and the item reports `NO_DATA` with the reason, which is
more useful than an audit that appears to hang. A `Retry-After` on any other status
is ignored — some CDNs send it on a 200, and sleeping on that would pace the audit
to somebody else's cache policy.

**`robots.txt` is obeyed for pages the tool finds itself** — links it follows,
sitemap entries it samples, and any redirect those land on. It is *not* consulted
for the URL you hand the tool. That asymmetry is deliberate and it is the only
defensible reading: a blanket check would mean that auditing a disallowed page
refuses every one of the 40-odd checks that fetch it, collapsing the audit to
`NO_DATA` and burying the finding that matters — "this page is blocked from
crawling" is a `critical` checklist item, a result rather than a prohibition. You
asked for that URL; robots.txt governs what a crawler discovers on its own.

**Every threshold says what it rests on.** A test can show that a number fires; it
cannot show the number is right, so `tools/audit_thresholds.py` finds each one a verdict
depends on and requires a stated basis — an external standard (named, so you can check
it), something measured, a convention admitted as one, or a number inherited from the
borrowed code and not yet examined. CI refuses a bare one. The count that matters is
**zero `measured`**: no threshold here was arrived at by measurement, and 14 of 36 came
with code from elsewhere — including the severity weights behind the score. That is in
[KNOWN-ISSUES.md](KNOWN-ISSUES.md) §2 with the numbers.

**The report says what changed since last time, and hands over a task list.** Every run
is filed under `.seo-runs/`, and a report now opens a **Since the previous audit** section
with the score and coverage movement and the items that changed — split into what was
fixed, what got worse, and what changed only because one run could decide it and the other
could not. That third bucket matters: `PASS` becoming `NO_DATA` is the measurement losing
its footing, not the site breaking, and it must not be reported as a regression. The
baseline is named, with its date and registry version, so the comparison can be checked.

`--fixes fixes.csv` (or `.json`) writes just the actionable items — id, status, severity,
effort, priority, what to do, evidence — ordered the way the report orders them, for a
tracker. Failing, warning and manual items only: an item nobody could decide is usually
work for whoever runs the audit, not for whoever owns the site.

**Server logs answer the one question fetching cannot.** `--server-log PATH` reads an
access log — combined format, Common Log Format or JSON lines, `.gz` fine — and CI-018
reports what crawlers *did* rather than what the site offers them: how much of the crawl
returned nothing indexable, which URLs took it, which parameters multiplied one page into
dozens, and how many requests came from AI crawlers as opposed to search engines. With the
crawl inventory it also answers the two questions neither half can alone — sitemap URLs no
crawler ever requested, and URLs crawlers request that the site offers nowhere.

It refuses rather than guesses. A log with no User-Agent field (Common Log Format has
none) reports an error instead of zero crawlers, because "no crawler visited" and "this
file cannot say" are opposite findings. `304` responses are not counted as waste — a
conditional request answered "not modified" is the cheapest exchange there is.
Never-crawled findings need a window of at least a week, and percentages need at least 50
crawler requests; below either, the figures are absent rather than computed from nothing.
A week or more of log is worth much more than a day.

**Who a crawler says it is, and who it is.** Classification is a lookup over the
User-Agent, which is a string the client chose — so a scraper announcing itself as
Googlebot spends Google's crawl budget in these figures, and the direction of that error
is always towards *over*-reporting the crawl. `--verify-bots` confirms each claimed search
crawler by the reverse-then-forward DNS check Google, Bing and Yandex document, and
requests from an address that fails are re-attributed out of the crawl-budget numbers
rather than annotated in place. Off by default: it is a network call about a third party.
A DNS failure is *not* read as forgery, and three crawlers that publish address ranges
instead of a DNS convention (DuckDuckBot, SeznamBot, PetalBot) stay claims either way.

```bash
python3 $S/scripts/checklist_runner.py https://example.com/ \
    --server-log /var/log/nginx/access.log --verify-bots
```

**A URL is fetched once per run.** Thirty-six of the evidence scripts need the page
they are judging and each runs in its own process, so the same document used to be
requested 37 times. Responses are now shared through a directory the runner creates
for the run and deletes when it ends — there is no cache between audits, and a script
run by hand caches nothing. Requests are the smaller half of what that fixes: 37
fetches are 37 *different* documents the moment a page is not static, and items would
then disagree about it with every one of them right about what it read. `http_cache`
in the JSON says which kind of run produced the file; `--no-http-cache` goes back to
every script fetching for itself, which is worth doing if a surprising result might be
about the cache — or if you want `lcp_subparts.py` to time its own request rather than
report the run's one fetch of the page.

Never cached: a request that failed (one refused connection must not become every
item's refused connection), a `POST` (`indexnow_checker.py` submits URLs), and a
response nobody has read. A stored redirect chain is re-checked against `robots.txt`
before it is handed over, so the cache cannot become the way around the rule below.

A `Crawl-delay` is honoured when it asks for more patience than `--max-rps`
allows. A `Crawl-delay` that would make us faster is ignored: a site can ask us to
slow down, not to be less careful than we chose to be. Refusals are visible —
`orphan_pages_from_sitemap.py` reports them as `robots_skipped` rather than letting
them count as unreachable pages, because that would turn our own restraint into the
site's defect. `broken_links.py` checks at most 200 links (internal first) and says
when it truncated.

One gap remains, recorded in [KNOWN-ISSUES.md](KNOWN-ISSUES.md): five scripts crawl
independently, so a single audit still fetches the same pages around 275 times.
Pacing limits the rate, not the volume.

## Auditing something that is not public yet

Every outbound request passes an SSRF guard that refuses hosts resolving to private
or internal addresses. `--allow-private` narrows that refusal for one run:

```bash
python3 -m http.server 8000 --directory ./site &
python3 $S/scripts/checklist_runner.py http://127.0.0.1:8000/ --allow-private --sample 5
```

Off by default, and deliberately not "anything that is not public". The permitted
set is loopback, RFC 1918, ULA and CGNAT — a staging box, a container, a Tailscale
host, a fixture server. **Link-local stays blocked with the flag on**, because
`169.254.169.254` is where cloud instance metadata answers and the URLs a crawl
follows come from the site being audited: a site that can talk this tool into
reading credentials off a metadata endpoint is a worse outcome than a staging audit
nobody can run. Reserved, multicast and unspecified ranges are blocked for the same
reason — nothing legitimate is served there.

The run says so on stderr, in the console summary even under `--quiet`, in
`checklist-results.json` as `allow_private`, and in the report above the summary. An
audit of a staging copy that reads like an audit of the live site is the same kind of
lie as a fabricated score.

Two consequences worth expecting:

- **Checks that need an outside service report `NO_DATA`, with the reason.**
  PageSpeed measures the page from Google's network, Safe Browsing looks the URL up
  in an index, a Search Console property cannot exist for an address on your LAN.
  `NO_DATA` and not `N/A`: those items apply to this site, so they stay in the
  coverage denominator and a pre-launch audit honestly reports thinner coverage.
  `--gsc-property` still works if you want the live site's history alongside a
  staging copy — passing it is you deciding that the two belong together.
- **An address has no registrable domain**, so there is no default `sc-domain:`
  property. The run says that rather than deriving one; `127.0.0.1` used to yield
  `sc-domain:0.1`.

For a single evidence script run by hand, `SEO_ALLOW_PRIVATE=1` does the same thing
and announces itself once.

## Measuring the rendered page

Font size, link distinctness, overlays, tap targets, horizontal scrolling and
clipped text are **computed** values: they depend on stylesheets, media queries and
scripts that HTML does not settle. Measure them in a browser (chrome-devtools MCP,
one `evaluate_script` — the snippet is in `SKILL.md`), save the numbers and pass
`--rendered-json`.

`viewport.width` is required, and from a desktop render the four mobile keys are
dropped rather than zeroed: a desktop window that fits its own content answers
nothing about a phone, and a 0 would be a verdict about a viewport nobody looked
at.

**A supplied measurement is the one input an audit cannot check by measuring again.** A
file naming a different page is refused with the reason. Its *age* cannot be verified at
all — every date inside it is the operator's claim — so the report states how many days
ago it was last written, from the filesystem rather than from the file, and
`--max-artifact-age DAYS` refuses one that is older. Off by default: how stale a
measurement may be depends on how often the page changes.

## Assertions that cannot fire

`none_matching` passes when nothing matches. So an assertion aimed at wording its
script does not emit — or emits in a different word order — reports **PASS for
every site, silently, forever**. Fifteen of the registry's twenty-one pattern
assertions were in that state, including a `critical` one about blocking CSS and
JS in robots.txt whose pattern was matching its own script's docstring.

Prefer a counted field, or a `value_map` that enumerates the script's own
vocabulary — where a value nobody mapped is `NO_DATA` rather than a pass:

```python
{"path": "rows", "field": "verdict",
 "value_map": {"self_canonical": "pass", "cross_host": "fail"}}
```

`tools/audit_assertions.py` reports any pattern that cannot match anything its
script emits, a test runs it, and CI fails on it.

### A rule can be alive and still never fail

`KW-076` *Use the Primary Keyword in Body Copy* asserted `target_keyword` truthy,
and `article_seo.py` wrote that field only when it already held something. The rule
ran on every audit, read a real field, and could return PASS or `NO_DATA` and
nothing else — for years, on every site.

A few rules are meant to be that way. `TE-179` prices domain age with a warn band
that is its assertion's exact complement, so an established domain passes, a young
one warns, and no value is left over to fail. In the code the two look identical:
the field is absent, or safe, exactly when the answer would have been bad.

So intent is declared on the item as `check.cannot_fail` — written in `CANNOT_FAIL`
in `build_checklist.py` — naming a **mechanism** from a closed vocabulary.
`tools/audit_reachability.py` re-derives that mechanism from the script's own source
on every run and fails the build three ways: a rule proved unfailable and not
declared, a declaration nothing proves any more, and a declaration naming a
mechanism other than the one proved. The third is the one an exemption list can
never catch, and this repository has watched one rot in exactly that spot.

It proves rather than surveys. Of 145 script-backed assertions, two are proved
unable to fail and the other 141 are **not claimed either way** — the summary line
prints that count instead of implying coverage it does not have.

The same tool audits the other unreachable verdict. A `warn` band fires only when
the assertion has already failed and the warn rule then holds, so a pair with no
room between them promises a middle nobody can reach. `CN-048` *Use Hierarchical
Headings and Semantic HTML* carried the standard "an error-class finding fails
this, a warning-class one only warns" pair over `parse_html.py`, which grades a
heading skip and a missing `<main>` as errors and says nothing milder anywhere.
Unlike an unfailable rule that is never a decision, so it has no declaration — it
is simply an error.

A band that *can* fire and never has is a different question, and the fixture suite
asks it: eleven of the registry's twenty-seven bands have produced a WARN against a
fixture, and any band the two fixtures exercise the item around without ever
landing in must carry a written reason in `BAND_UNSEEN`, which a test drops the
moment the band starts firing.

## Core Web Vitals: field and lab, never merged

`pagespeed.py` reports CrUX **field** data — what real visitors experienced. That
is the better evidence and it answers SP-108 and SP-113 whenever it exists. It does
not exist for low-traffic URLs.

For those, measure the page locally with the chrome-devtools MCP, write the
numbers to a file and pass `--cwv-json`. SP-214/215/216 decide from it and are
`NO_DATA` without it. They are **separate items on purpose**: one controlled run on
your machine is a different claim from what visitors got, and one number standing
for both is the conflation this tool exists to avoid. TBT is reported as a lab
stand-in for INP, named as such, because INP needs a real interaction.

Units live in the key names (`lcp_ms`, `tbt_ms`, unitless `cls`) — a bare `lcp` of
2.1 could be seconds or milliseconds, and guessing wrong turns a failing page into
a passing one, so the file is refused instead.

## A second reading of the LLM verdicts

`--llm-review` folds in an independent second judgement of the same items.
Agreement corroborates. Disagreement returns the item to `NO_DATA` with both
readings recorded, and coverage drops accordingly.

The reviewer cannot change a verdict, cannot touch a script's result, and cannot
answer an item the first pass left unanswered. It withdraws confidence, which is
the one thing 38 unopposed judgements had no way to express.

## Bundled playbooks

The prose half of the audit ships **inside** the plugin. Nothing here depends on
another plugin being installed, because a missing dependency degrades an audit
silently — and a silent degradation is exactly what this tool exists to prevent.

| Playbook | Covers | Items |
|---|---|---|
| `resources/playbooks/local-seo.md` | Business Profile, NAP, citations, reviews | LO-196, LO-199 |
| `resources/playbooks/competitor-research.md` | who actually ranks, with sources | CO-191…195, BL-088 |
| `resources/references/client-report-structure.md` | reshaping the report for a decision | — |

**A playbook tells you how to answer an item; it never answers one.** Reading it
does not move a status — doing the work does. `local-seo.md` cannot read the live
Business Profile, so LO-199 stays `MANUAL`. `competitor-research.md` uses
firecrawl or exa when those MCP servers are configured and falls back to the
built-in `WebSearch`; with no search tool at all, CO-191 is `N/A`, because a
competitor list written from memory is fabrication with a confident tone.
`client-report-structure.md` is presentation only and changes no number.

Two of the three are adapted from MIT-licensed work in
[Everything Claude Code](https://github.com/affaan-m/ECC); provenance and the
full notices are in [CREDITS.md](CREDITS.md).

## Carrying the theory to another machine

The registry, the specs, `SKILL.md` and the playbooks can be loaded into a
NotebookLM notebook and asked questions from any machine. That carries the prose
half: what a check means, how a verdict is decided, how the report is shaped. It
does not carry the run — the scripts execute from a clone, and an audit begun on
one machine is re-run on the other.

The failure mode is specific: **a notebook is a snapshot, and a stale one still
answers.** It will describe a registry version that no longer exists and give no
sign it is out of date. `tools/notebook_sync.py` is the check for that.

```bash
export SEO_NOTEBOOK_ID=<your notebook id>                   # notebooklm list
python3 skills/seo-checklist/tools/notebook_sync.py check   # exits 1 on drift
python3 skills/seo-checklist/tools/notebook_sync.py sync    # re-upload what drifted
```

Each uploaded document carries a `source-sha256` of the repo file it was built
from. `check` reads that stamp **back out of the notebook** and compares it with
a hash computed from the clone right now; a ledger kept on the machine that did
the uploading would agree with itself and prove nothing. Run it before taking on
checklist work and again after closing it — the repo can move while the work is
in progress.

Verdicts are `OK`, `STALE` (the notebook holds an older file), `MISSING` (never
uploaded), `UNSTAMPED` (uploaded by hand, provenance unknown), `NO-UPSTREAM`
— the notebook holds a document this clone does not, which usually means it was
uploaded from a file that was never committed — and `UNREAD`, meaning the copy
could not be fetched at all.

`UNREAD` is the one that has to stay separate. It is not a finding about the
document, so `sync` leaves those alone rather than replacing what it failed to
read; `check` still exits 1, because a gate that cannot see is not a gate that
says fresh. An expired login ends the run at the first call that reports it,
instead of becoming one verdict per source and a remedy that deletes them.

Requires [notebooklm-py](https://github.com/teng-lin/notebooklm-py), which drives
undocumented Google endpoints and is not affiliated with Google.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

Everything runs offline — no live site, no API key, no Search Console property.
The suite guards the parts that fail *silently*: an assert rule using an operator
the runner never implemented, a pattern that cannot fire, a script the registry
names but nobody shipped, an LLM item with no lens, a profile that hides a critical
check, and the boundary between "failed", "could not be decided" and "out of scope"
that every metric here depends on.

Every one of the 58 evidence scripts has tests, and each asserts *the field the
registry actually reads*, named in the test. That is how three releases running found
defects at about one per three tests: 0.5.0's eighteen assertions that had never
fired, 0.7.0's two items that failed a site for serving images the recommended way,
0.8.0's sixty-two items grading a site that answered nothing, and 0.9.0's twelve more
of the same family plus five checks that accused every site on the internet.

Two sweeps carry most of that weight, and both are four lines over a list derived
from the registry rather than hand-maintained:

- **nothing is decided about a site that answered nothing** — every URL-taking script
  pointed at a closed port, and no item may come back PASS, FAIL or WARN;
- **nothing accuses the site the fixture pair calls good** — because "the two sites
  answered differently" was satisfied by a check that failed the good one and passed
  the broken one, which is worse than a check that cannot tell them apart.

Several guard documentation rather than code, because a document that has gone stale
beside working code is its own kind of silent failure: the manifest version must have
a `CHANGELOG.md` entry naming the shipped `registry_version` and must match
`pyproject.toml`, the 200 borrowed titles must record their source in the file that
holds them, every category must have a plain-language explanation in every shipped
language, and the lowest Python in the CI matrix must be the floor `pyproject.toml`
declares. CI runs the suite on 3.10, 3.11 and 3.13, along with `ruff`, the gates and
four offline end-to-end audits, and a job of its own re-takes the recorded verdict
census over all five served trees and compares it with the one in the tree.

**And the pair.** The whole registry is run against two served fixture sites — one
satisfying as much of it as a static site can, one engineered to fail — and every
script-backed item must answer them differently or carry a written reason why it
cannot. A check can only be verified by disagreeing with something, and 33 assertions
in this tool's history reported the same verdict on every site ever audited. CI also
serves `tests/fixtures/good/` and audits it over real HTTP with `--allow-private`:
crawl, sample, pace, aggregate, render. That job fails if *any* evidence script
crashes, and separately asserts the fixture's robots-disallowed sitemap URL comes out
as a robots conflict and **not** as an orphan, which is the arithmetic that was wrong
in 0.3.0.

That job exists because of what its absence cost. The 0.2.0 rate limiter crashed 36
of 56 scripts on its first live run while every offline test passed: a single process
writing to a fresh pacing file never appends twice, so only contention between real
processes could show it. Within an hour of the fixture existing it had found three
more bugs — see the 0.4.0 section of [KNOWN-ISSUES.md](KNOWN-ISSUES.md).

## Extending the registry

```bash
S=skills/seo-checklist
python3 $S/tools/build_checklist.py          # rewrite checklist.json
python3 $S/tools/build_checklist.py --check  # CI: fail if stale
```

Edit `tools/build_checklist.py`, never `checklist.json` directly. Two rules:

1. **Write assertions only against observed script output.** Capture it with
   `tools/probe_shapes.py` and consult
   `resources/references/script-output-shapes.md`. A guessed JSON path produces a
   rule that silently reports `NO_DATA` forever.
2. **Every LLM item needs a lens.** The build refuses without one — otherwise a new
   item belongs to no agent and quietly never gets answered.

Absence of a field is `NO_DATA`, not `PASS`. An item passes on absence only when
its rule says `missing_is: pass`: a parser that never emits a key must not be read
as the site being clean.

## Credits

See [CREDITS.md](CREDITS.md) for provenance and third-party licences: the Plerdy
checklist, the Agentic-SEO evidence scripts, and the two playbooks adapted from
Everything Claude Code.
