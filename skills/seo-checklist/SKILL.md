---
name: seo-checklist
description: >
  Deterministic SEO audit against a fixed 217-item registry. Every item gets a
  status and nothing is silently skipped, so two audits of the same site check
  the same things. Use when the user asks for a checklist audit, a full SEO
  checklist, reproducible coverage, a comparison against a previous run, or an
  audit of local site files rather than a live URL.
---

# Checklist Audit

`resources/config/checklist.json` holds **217 items** — the Plerdy 200-point
checklist plus 17 checks it does not cover (GEO/AI search, `llms.txt`, AI-crawler
policy, IndexNow, schema guards, lab Core Web Vitals, rendered mobile layout). Each item names what
answers it: a script and an
assertion over that script's output, a Search Console call, a language-model
judgement, or a human.

The registry is the point. Coverage is a contract, not whatever the model
remembered to run.

## What this tool guarantees, and what you must supply

Every section below is one of two kinds of sentence, and until 0.93.5 they were written
in one voice: a behaviour the tool performs whether or not anybody remembers it, and a
behaviour only the operator can supply. An operator who reads the second as the first
stops checking, and the tool cannot detect that — from inside the run, everything
happened correctly.

One row per section, in the order they appear. `—` means the section makes no claim of
that kind. A row is not a summary of its section; it is the contract, and the section is
the reasoning behind it.

| Section | The tool guarantees | You must |
|---|---|---|
| Run it | every item in the registry gets a status from one command, and nothing is silently skipped | choose the mode and the inputs; a flag you do not pass is scope you did not audit |
| Site profiles | an excluded item reports `N/A` naming the profile; no profile may exclude a `critical` item; an unknown name is an error, never a fallback; a run with no terminal uses `default` and prints what detection would have suggested | ask which profile before the first run of a session unless the request already says, and name the one you chose |
| Auditing several pages | picks are spread arithmetically and are the same on the next run; non-pages are dropped with the reason; the worst verdict wins and the evidence carries the count | say how many pages were looked at — "5 of 214 pages", never "the site" |
| The report | four layers in one file, and every measurement is phrased as a sentence in `measure` | do not paste an item's `evidence` at the reader; ask which language they need before rendering |
| The second reading | the reviewer cannot change a verdict, only withdraw confidence, and cannot touch a script or Search Console answer | dispatch `seo-llm-adversary` before the report goes to anyone |
| Measuring the rendered page | without the artifact those seven items report `NO_DATA`; a desktop render drops the four mobile keys rather than answering them | resize to 375×812, run the snippet, save it with a `source` line, pass `--rendered-json`, and say in `source` what you changed |
| Core Web Vitals from a local trace | an artifact describing a different page is refused, naming both URLs; a `--sample` run does not spread these files across sampled pages | trace the page you are auditing, record mode and viewport in `source`, and never report a lab number as field data or merge it with SP-108 or SP-113 |
| Incoming links | BL-084, BL-086 and BL-087 are answered from the export | export Search Console → Links yourself; the API does not offer it |
| Run modes | anything a mode cannot satisfy is `N/A` and leaves both metrics alone; Search Console without a key is `NO_DATA`, which is a different claim | choose the mode that matches what you actually have |
| A host that is not on the public internet | every request passes an SSRF guard; link-local stays blocked even under `--allow-private`; the flag is recorded on stderr, in the summary, in the JSON and above the report | pass `--allow-private` only for a host you are entitled to audit, and report the result as a staging audit rather than as an audit of the site |
| Which HTML parser read the page | `html_parser` is recorded in every result, and a test asserts the two parsers agree on every field the checklist reads | do not report a verdict as sensitive to which parser is installed |
| When the site cannot be read | no script is run, no score is reported, and every live check is `NO_DATA` with the reason | — |
| Answering the items no script can | neither door can touch a verdict a script reached, and a `PASS` with no reason is refused with its id | give every answer a reason somebody can argue with |
| Statuses | absence of a field is `NO_DATA`, never `PASS`, unless the rule says `missing_is: pass` | read `NEEDS_INPUT` as your own to-do list — it names the flag it wanted |
| Politeness, and what it does not cover | 4 requests/second/host shared across processes, `robots.txt` honoured for discovered URLs, `Crawl-delay` obeyed, one crawl and one fetch per URL | answer a site owner about load with the real numbers, and read `KNOWN-ISSUES.md` before defending one |
| Secrets | values taken from `INDEXNOW_KEY` and `PAGESPEED_API_KEY` are replaced with `<redacted>` throughout the payload | pass every other secret as a credential *path*, because the run log is built from argv and takes an argument verbatim |
| The score, and how much of the registry it speaks for | the score, its weight share and a partition whose buckets add up to the registry | never quote the score without its weight share, and say what is waiting on the reader |
| Search Console | credentials are discovered in a stated order; the default property comes from a bundled Public Suffix List and the run says so when it falls back to a guess; `archive` ignores a key that is present | grant the service account access on the property, and pass `--gsc-property` for a URL-prefix property or when the run says its default is a guess |
| Mandatory: answer the LLM queue | the queue files carry a skeleton of their own item ids, and the merge overwrites only `LLM_PENDING` | read the page rather than the queue file, and answer `N/A` rather than inventing a `PASS` |
| Bundled playbooks | they ship inside the plugin and depend on nothing else being installed | remember that reading a playbook moves no status; doing the work does |
| Deliverables | every result carries the `registry_version` it came from, and `--diff` warns across versions, profiles and modes | — |
| Extending the registry | the build refuses an LLM item with no lens, and `--check` fails on a stale `checklist.json` | edit `tools/build_checklist.py`, never `checklist.json`, and write assert rules only against observed script output |

`tests/test_protocol_contract.py` holds this table against the document: every section has
a row, every row names a section, and no row is empty on both sides. What it cannot hold
is whether a row is *true* — that is a reading, and `openspec/specs/operator-protocol/`
OPR-1 records it as the half still unread.

## Run it

```bash
# full audit of a live site
python3 <SKILL_DIR>/scripts/checklist_runner.py <url>

# single live page, no crawling (fast)
python3 <SKILL_DIR>/scripts/checklist_runner.py <url> --mode page

# local copy of a site, no network at all
python3 <SKILL_DIR>/scripts/checklist_runner.py <url> --archive ./site-backup

# compare against the previous run for this domain
python3 <SKILL_DIR>/scripts/checklist_runner.py <url> --diff

# narrow the registry to what this kind of site can be judged on
python3 <SKILL_DIR>/scripts/checklist_runner.py <url> --profile ecommerce

# the shared crawl on its own: which URLs exist, which are broken, what links to them
python3 <SKILL_DIR>/scripts/site_crawl.py <url> --out inventory.json

# judge page-level checks across several pages instead of one
python3 <SKILL_DIR>/scripts/checklist_runner.py <url> --sample 10

# audit a staging site or a locally served copy — off by default, see below
python3 <SKILL_DIR>/scripts/checklist_runner.py http://127.0.0.1:8000/ --allow-private

# answer the incoming-link items from a Search Console Links export
python3 <SKILL_DIR>/scripts/checklist_runner.py <url> --links-csv ~/Downloads/Links.zip

# render the deliverables (add --lang ru for a Russian report)
python3 <SKILL_DIR>/scripts/checklist_report.py checklist-results.json
```

## Site profiles

`--profile` narrows the registry to what a given kind of site can actually be
judged on: `default`, `local`, `ecommerce`, `saas`, `blog`, `media`. An excluded
item reports `N/A` with the profile as the reason and leaves both metrics alone.

**Ask the user which profile to use before the first run of a session, unless
they already said what kind of site it is.** Offer the six names with their
one-line descriptions and let them pick; then pass the answer as `--profile` so
the run is not left guessing. If the user's request already makes it obvious —
"audit my shop", "our SaaS landing page", "the blog" — take that as the answer
and say which profile you chose rather than asking again.

To answer with evidence rather than a guess, run the detector on the entry page
first and put its suggestion in the question:

```bash
python3 <SKILL_DIR>/scripts/detect_profile.py <url> --json
```

It reads structured data, platform fingerprints and cart/pricing markup — never
wording, which is the first thing that lies: a plumber's nav says "shop" and a
store's homepage says "about our family business". Report the suggestion with the
signals behind it and the confidence, and let the user correct it. When the
evidence is thin the detector says so and suggests `default`, which is the right
answer rather than a shrug.

Do not skip the question and default silently. `default` runs the full registry,
so nothing is hidden by it, but a local business audited under `default` collects
storefront failures it can never fix, and the priority list fills with noise.

The runner does the same thing on its own: it fetches the entry page **before**
settling the profile (one request, not two — archive mode uses its local file),
detects, then asks with the suggestion pre-selected so Enter accepts it. The
signals and the confidence are shown, and a close second is flagged as "the guess
is not clear-cut".

`--profile auto` accepts the detection without asking — the one way a heuristic
is allowed to narrow scope, because passing the flag is itself a decision.

Passing any other `--profile` disables the prompt entirely. The script asks only
when a terminal is attached; in CI, cron and background runs it uses `default`,
mentions what detection would have suggested, and prints why it did not act on
it. `--no-prompt` forces that behaviour anywhere.

Exclusions are deliberately conservative, and no profile may exclude a
`critical` item — a test enforces that. Narrowing scope must never become a way
to raise the score by hiding hard failures.

An unknown profile name is an error, not a fallback to `default`: quietly
auditing a store as a blog would drop the storefront checks and lift the score
for the wrong reason. Every non-answer resolves to the **widest** scope, never a
narrower one.

## Auditing several pages

`--sample N` collects up to N same-host URLs — sitemap first, on-page links
second — and runs the **page-level** checks (`requires` of `offline` or `fetch`)
against each. Site-level checks still run once.

Aggregation takes the worst verdict, because a check failing on any sampled page
fails for the site, but the evidence always carries the count: `3/8 pages: ...`
never reads the same as every page. When no second URL can be found the run says
so and audits the single page rather than pretending to have sampled.

The picks are spread evenly across the sitemap, not taken from the top, so they
cross whatever the sitemap is grouped by. The step is arithmetic, so an unchanged
sitemap gives the same pages on the next run. **Still say how many pages were
looked at** — "5 of 214 pages" is the honest phrasing, never "the site" — and note
that sampled URLs `robots.txt` disallows are dropped, with the count printed.

Only real pages enter the sample. Candidates come from `<a href>` alone, asset
extensions are rejected by path, and anything whose `Content-Type` is not a page
is dropped at fetch time with the reason printed. This matters more than it
looks: a stylesheet sampled as a page fails every page-level check, and the worst
verdict wins — one asset in the sample would condemn the whole site.

## The report

`checklist_report.py` writes four layers into one HTML file, plain language first
and the machine detail folded underneath. Hand it to whoever owns the site.

```bash
python3 <SKILL_DIR>/scripts/checklist_report.py checklist-results.json --lang ru
```

**Do not paste an item's `evidence` string at the user.** It is the audit trail —
`summary.thin_pages = 6 (want 0)` — and the report already phrases the same
measurement as a sentence from the structured `measure` field. When you summarise a
run in chat, summarise it the way the report does: what was found, why it matters,
what to do.

`--lang` sets the language of everything the report says about itself, including
the plain-language layer and the per-category explanations. Item titles and the
registry's recommendations stay in English unless that language file overrides them
(`item_titles`, `item_fixes`). Ask which language the reader needs before rendering
a report for somebody else.

## The second reading

The LLM queue produces 38 verdicts from one model's reading of one page, and the
report presents them beside measured HTTP statuses with the same confidence. Have
them reviewed before the report goes to anyone:

```bash
python3 <SKILL_DIR>/scripts/checklist_report.py checklist-results.json \
    --llm-review review.json
```

Dispatch `seo-llm-adversary` for it. The reviewer reads the page itself **before**
looking at the verdicts it is reviewing, rules independently, and writes the same
JSON shape as the first pass.

The asymmetry is the design: **it cannot change a verdict, only withdraw
confidence.** Agreement marks the item as checked twice. Disagreement returns it to
`NO_DATA` carrying both readings, and coverage drops — which is what the audit not
knowing looks like. A reviewer that could overwrite a verdict would just be a
second first pass; one that could only agree would be decoration.

It cannot touch script or Search Console verdicts, and it cannot answer an item
the first pass left unanswered. Both are ignored with a message rather than
silently applied.

## Measuring the rendered page

Seven items are answered from what a browser actually laid out, not from HTML: font
size, link distinctness, overlays, and — from a mobile render — tap targets,
horizontal scrolling and clipped text. They are computed values, so markup alone does
not settle them.

Resize to a phone viewport first (375×812), load the page, then run one
`evaluate_script`:

```js
(() => {
  const vw = innerWidth, vh = innerHeight, area = vw * vh;
  const px = v => parseFloat(v) || 0;
  const visible = el => {
    const s = getComputedStyle(el);
    if (s.display === 'none' || s.visibility === 'hidden' || px(s.opacity) === 0) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };

  let small = 0;
  for (const el of document.querySelectorAll('body *')) {
    if (!visible(el)) continue;
    const ownText = [...el.childNodes].some(
      n => n.nodeType === 3 && n.textContent.trim().length > 3);
    if (ownText && px(getComputedStyle(el).fontSize) < 12) small++;
  }

  let indistinct = 0;
  for (const a of document.querySelectorAll('p a, li a, td a, article a')) {
    if (!visible(a) || !a.parentElement) continue;
    const s = getComputedStyle(a), parent = getComputedStyle(a.parentElement);
    const underlined = (s.textDecorationLine || '').includes('underline');
    const bolder = parseInt(s.fontWeight) - parseInt(parent.fontWeight) >= 200;
    if (!underlined && !bolder && s.color === parent.color) indistinct++;
  }

  let overlays = 0;
  for (const el of document.querySelectorAll('body *')) {
    const s = getComputedStyle(el);
    if (s.position !== 'fixed' && s.position !== 'sticky') continue;
    if (!visible(el)) continue;
    const r = el.getBoundingClientRect();
    const covered = Math.max(0, Math.min(r.right, vw) - Math.max(r.left, 0)) *
                    Math.max(0, Math.min(r.bottom, vh) - Math.max(r.top, 0));
    if (covered / area >= 0.25) overlays++;
  }

  let taps = 0;
  for (const el of document.querySelectorAll(
      'a, button, input, select, textarea, [role=button]')) {
    if (!visible(el)) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 48 || r.height < 48) taps++;
  }

  const overflow = Math.max(0, document.documentElement.scrollWidth - vw);

  let clipped = 0;
  for (const el of document.querySelectorAll('h1, h2, h3, p, a, button, li')) {
    if (!visible(el) || !el.textContent.trim()) continue;
    if (el.scrollWidth > el.clientWidth + 1 ||
        el.scrollHeight > el.clientHeight + 1) clipped++;
  }

  return {url: location.href, viewport: {width: vw, height: vh},
          text_nodes_below_12px: small, links_indistinct: indistinct,
          overlays_covering_content: overlays, tap_targets_below_48px: taps,
          horizontal_overflow_px: overflow, text_nodes_clipped: clipped,
          html: document.documentElement.outerHTML};
})()
```

Save the object, adding a `source` line that says how it was taken, and pass
`--rendered-json /path/to/rendered.json`.

The `html` key is the serialised DOM after scripts have run. `MB-105` compares its SEO
signals with the served document, and `TE-181` *Validate the Rendered DOM (W3C)* sends
it to the W3C checker. It is captured here rather than
by a browser inside the audit on purpose: a browser started mid-run fetches the page
and its subresources again behind the response cache, which took one audit of the
test fixture from 22 requests to 31. Omit the key and both MB-105 and TE-181 report
`NO_DATA`, which is honest — the other items in this file are unaffected either way.

`viewport.width` is required. From a desktop render the four mobile keys — tap
targets, mobile interstitials, horizontal overflow and clipped text — are
**dropped**, and those items report `NO_DATA`. A desktop window that fits its own
content answers nothing about a phone, and passing one through would be a verdict
about a viewport nobody looked at.

`horizontal_overflow_px` is asserted `lte: 1` rather than `eq: 0`: `scrollWidth` and
`innerWidth` are both integers, and one pixel of rounding is not a page that scrolls
sideways. `text_nodes_clipped` counts an element truncated with `text-overflow:
ellipsis` along with one clipped by accident — telling the two apart needs a rule
nothing here can price, so MB-108 fails a site that truncates card titles on purpose.
That is a false fail with a visible count beside it, not a silent pass.

Adjust the snippet when a site needs it — a cookie banner counted as an overlay is
a true positive, a `sticky` header covering a quarter of a phone screen usually is
too — but say what you changed in `source`. If the MCP is unavailable, skip it:
seven `NO_DATA` items with a stated reason beat seven guesses.

## Core Web Vitals from a local trace

`pagespeed.py` reports **field** data — what real visitors experienced, from CrUX.
That is the better evidence and it answers SP-108 and SP-113 whenever it exists.
It does not exist for low-traffic URLs, and then those items are `NO_DATA` no
matter how slow the page is.

For that case, measure the page yourself with the **chrome-devtools MCP** and hand
the numbers to the run:

1. `performance_start_trace` with a reload, then `performance_stop_trace`.
2. Read LCP, CLS and TBT out of the trace insights.
3. Write them to a file, units in the key names:

```json
{
  "url": "https://example.com/",
  "lcp_ms": 2100,
  "cls": 0.04,
  "tbt_ms": 150,
  "source": "chrome-devtools MCP trace, desktop, 2026-08-03"
}
```

4. Pass it: `--cwv-json /path/to/cwv.json`

SP-214, SP-215 and SP-216 then decide from it; without the file they are
`NO_DATA` naming the missing input. Say which mode and viewport you traced in
`source`, because a desktop trace on a fast connection is not what a phone sees.

**`url` must be the page being audited.** Both artifacts are the only evidence in a
run that nothing here can verify by measuring again — every other verdict comes from
a request this process made. So the run checks the one thing it can: an artifact
describing a different page is refused, and its items report `NO_DATA` naming both
URLs rather than deciding eight items from numbers taken somewhere else. Trailing
slash, scheme and `www.` are treated as noise; a different path is a different page.
Trace the page you are auditing, and re-trace it when you audit another one.

For the same reason a `--sample` run does **not** apply these files to the sampled
pages: one measured page cannot become a verdict about four unmeasured ones. The
artifact items describe the entry URL and say so.

**Do not report these as field data and do not merge them with SP-108 or SP-113.**
They are separate items because they are separate claims: one controlled run on
your machine versus what visitors actually got. TBT is named as a lab stand-in for
INP because INP needs a real interaction and cannot be measured from a page load
at all — reporting it as INP would be a fabrication.

If the MCP is unavailable, skip it. Three `NO_DATA` items with a stated reason are
a smaller lie than three numbers from somewhere else.

## Incoming links

The Links report is the one part of Search Console with **no API at all**, so
`--links-csv` takes the export instead: Search Console → Links → Export. Three
items are answered from it — link concentration (BL-084), total links (BL-086)
and linking root domains (BL-087). The rest of the backlinks block stays manual
because judging link quality needs a link index this does not have, and a
fabricated toxicity score would be worse than the silence.

Scripts need `requests` + `beautifulsoup4` + `lxml`. Search Console additionally
needs `google-auth` and `google-api-python-client`.

## Run modes

| Mode | Capabilities | Use when |
|---|---|---|
| `live` (default) | offline + fetch + crawl + external APIs | full audit of a reachable site |
| `page` | offline + fetch + external APIs | one page, no crawl — much faster |
| `archive` | offline only | you have files, not a URL; zero network calls |

Each item declares what it `requires`. Anything a mode cannot satisfy is reported
**`N/A`** and drops out of *both* metrics — "we did not crawl" must never read as
"the site failed".

Search Console is the one capability that can be missing for two different
reasons, and they are not the same status. In `archive` — a mode that promises no
network at all — its items are **`N/A`**, genuinely out of scope. In `live` or
`page` **without a key** they are **`NO_DATA`**: the run could have asked and did
not manage to decide. Calling the second one `N/A` would drop seven items out of
the coverage denominator and raise coverage exactly where the audit is thinnest.

## A host that is not on the public internet

Every request passes an SSRF guard that refuses private and internal addresses.
`--allow-private` narrows that for one run — a staging site before launch, a
container, a fixture served locally. Off by default, and narrower than "not
public": loopback, RFC 1918, ULA and CGNAT only. **Link-local stays blocked**
(`169.254.169.254` is cloud instance metadata, and the URLs a crawl follows come
from the site), as do reserved, multicast and unspecified ranges.

Report it as a staging audit, never as an audit of the site. The run says so on
stderr, in the summary even under `--quiet`, in `checklist-results.json`
(`allow_private`, and `entry_private` for what actually happened), and above the
report's summary.

Two things follow, and both are correct rather than broken:

- **Checks needing an outside service are `NO_DATA` with the reason** — PageSpeed
  measures from Google's network, Safe Browsing looks the URL up, a Search Console
  property cannot exist for an address on a LAN. Not `N/A`: they apply to this
  site, so coverage drops, which is the honest number for a pre-launch audit.
  `--gsc-property` overrides this if the live site's history belongs in the
  comparison.
- **No default `sc-domain:` property**, because an address has no registrable
  domain. Do not invent one; `127.0.0.1` used to become `sc-domain:0.1`.

`SEO_ALLOW_PRIVATE=1` does the same for a single script run by hand.

## Which HTML parser read the page

`lxml`, unless it cannot be imported. `SEO_HTML_PARSER=html.parser` switches it, and
every run records `html_parser` in the results.

You almost never need to touch it. It is worth knowing about in one situation: two runs
of the same site disagree and nothing else explains it. Measured over fifteen document
shapes, every field the checklist reads is identical between the two parsers, and since
0.15.0 so is every structural query: the answer-block scanner was rewritten against
document order and nearest-ancestor ownership, which is what both parsers — and the
browser — agree about. On the markup that used to split them, an unclosed `<p>` with a
wrapper `<div>` and unclosed `<li>`s, both now score 42. A test asserts the agreement
rather than pinning the two numbers, which is the stronger guard: it fails on the next
query written against sibling position, not only on the two that were.

So no verdict here should be reported as sensitive to which parser is installed. What
remains is a structural query nobody has written yet — `find_next_sibling()` and
`recursive=False` are both questions about where the parser thinks an element ends, and
that is why the run records `html_parser` in the artifact.

## When the site cannot be read

If the entry page does not load — DNS failure, 4xx/5xx, a non-HTML response —
every check that reads the live site (`requires` of `fetch`, `crawl` or `api`) is
`NO_DATA` with the reason attached, **no script is run against it, and no score
is reported at all**. Search Console items still run: Google's stored history
does not stop existing because the site is down today.

This is not a nicety. Most evidence scripts exit 0 with a well-formed empty
result when they cannot fetch anything, and an empty result satisfies exactly the
assertions this registry is built from — `errors = 0`, `duplicates = 0`, no match
for a warning pattern. Before the gate, a run against a host that does not
resolve returned **61/100 on 40 fabricated passes**. `missing_is` cannot catch
this: the key is present and its value is zero.

### The page that answers 200 and is not the site

A status code is not enough. A bot-protection challenge and a soft 404 both
answer **200 with well-formed HTML**, so the gate above waves them through and
every script grades the interstitial. The audit User-Agent is exactly what bot
protection exists to stop, which makes this the common case, not the exotic one.

Two signals, each deliberately narrow:

- **Interstitial** — a vendor fingerprint (Cloudflare, Imperva, PerimeterX,
  DataDome, AWS WAF, Sucuri, Akamai) **in the markup**, or one of a short list of
  challenge titles, **and** under 120 words of visible text. Both conditions are
  required. An article explaining Cloudflare quotes `cdn-cgi/challenge-platform`
  in its prose, and Cloudflare's JS detections inject that script into ordinary
  content pages — either one alone would condemn a working page.
- **Soft 404** — the title, or one of its `|`-separated segments, *equals* a
  known not-found phrase. Never a substring: `404` appears in the title of every
  article ever written about broken links.

When either fires the entry page is treated as unreadable — **no score, and the
offline checks are gated too**, because unlike a failed fetch the file is there
and parses fine, so nothing else would stop them from grading its twelve words.

`--no-page-guard` audits the page anyway, for auditing an error page on purpose
or when the guard is wrong about yours. The suspicion is still recorded in
`entry_guard`, and the run says so on every surface: an artifact that scored an
interstitial without admitting it would be the same lie in a new place.

## Answering the items no script can

Two doors, deliberately separate, and neither can touch a verdict a script reached.

```bash
# the model's 38, after the lens agents have read the page
python3 <SKILL_DIR>/scripts/checklist_report.py checklist-results.json \
    --llm-answers answers.json

# the 31 a person has to look at — Search Console UI, Business Profile, a phone call
python3 <SKILL_DIR>/scripts/checklist_report.py checklist-results.json \
    --manual-answers manual.json
```

Each queue file now carries a **skeleton naming its own item ids**, so an agent fills
two fields per line instead of building the structure and possibly the ids. Merging an
id that is not in the right state prints why rather than applying nothing in silence.

`--manual-answers` merges `MANUAL` items only, and **every answer needs a reason**.
A `PASS` with nothing beside it is refused with its id: thirty-one ticks would move
the score with nothing for a reader to argue with. The HTML report's "Needs a person"
section exports the ticked items as a starting file — a tick claims `PASS` and carries
no reason, so the exported evidence says so and has to be replaced before it merges.

**Every decided item records `decided_by`** — `measured`, `model` or `claimed` — and
the report prints the breakdown whenever anything was not measured:

> Of the 109 decided items: 3 answered by a person, on their word, 106 measured here.

Say that line when you summarise a run. A score standing partly on somebody's word is
a different claim from one standing on measurements, and it used to print identically.

## Statuses

`PASS` · `FAIL` · `WARN` (counts as half) · `NO_DATA` (ran, nothing anybody can
supply would decide it) · `NEEDS_INPUT` (would have been decided; the run was not
given the file, key or credentials — the reason names the flag) · `LLM_PENDING` ·
`MANUAL` · `N/A` (out of scope for this mode).

`NEEDS_INPUT` is the operator's to-do list and prints as its own report section,
"What this audit was not given". It was split out of `NO_DATA` in 0.16 because that
status was carrying four sentences at once, and thirteen fixable items on a measured
run were reading as limits of the tool.

Absence of a field is `NO_DATA`, not `PASS`. An item only passes on absence when
its rule sets `missing_is: pass` — a parser that never emits a key must not be
read as the site being clean.

## Politeness, and what it does not cover

Requests are paced to 4/second/host by default, shared across the concurrently
running scripts through a lock file (`--max-rps`, `SEO_MAX_RPS`). `robots.txt` is
honoured for pages the tool **discovers** — followed links, sampled sitemap
entries, redirects those land on — and deliberately not for the URL you were given
to audit: a block on that URL is a `critical` finding to report, not a reason to
audit nothing. `Crawl-delay` is honoured when it asks for more patience than the
configured rate.

The lock file and the cached `robots.txt` answers share one directory for the whole
machine, so that two audits started a second apart pace each other rather than each
starting fresh. `SEO_RATE_LIMIT_DIR` moves it for a run that needs its own, and the
processes that run starts inherit it.

**When a threshold comes up, the basis is beside it.** Every number a verdict depends on
carries a `# basis:` line saying whether it is an external standard, a measurement, a
convention, or inherited from the borrowed code unexamined. If a client argues with a
verdict, that line is the answer — and if the line says `inherited`, the honest answer is
that nobody here chose the number. None of them is `measured`.

**The deliverable carries history and a task list.** A second audit of the same domain
gets a "Since the previous audit" section — score movement and the items that changed,
split into fixed, worse, and changed-for-want-of-evidence. The third split is the one to
keep straight when explaining a report: `PASS` → `NO_DATA` means this run could not tell,
not that the site regressed. `--fixes PATH` writes the failing, warning and manual items as
CSV or JSON for a tracker.

**Server logs, if the operator has one.** `--server-log PATH` is the only evidence here
about what crawlers *did*; everything else asks what the site offers them, and that fact
is in the past. It decides CI-018 — crawl budget spent on non-200s, parameters multiplying
pages, AI crawlers counted apart from search engines — and, with the crawl inventory,
sitemap URLs nothing requested. Ask for a week or more; below that it declines to report
never-crawled URLs, because "never" and "not yet" are the same observation in a one-day
log. A log in Common Log Format records no User-Agent and is refused with that reason
rather than read as zero crawlers.

**One fetch per URL.** Responses are shared across the whole run through a directory
the runner creates and deletes with the run, so the same document is not requested 37
times by 36 single-page scripts. Requests are the smaller half of it: 37 fetches are 37
different documents whenever the page is not static, and items would then disagree
about it while each was right about what it read. Never shared: a failed request, a
`POST`, or a body nobody read; and a stored redirect chain is re-checked against
`robots.txt` before it is handed over. `--no-http-cache` switches it off, and
`http_cache` in the JSON says which kind of run produced the file.

**One crawl, kept.** Before the plan is built, the runner runs `site_crawl.py` once
and hands the inventory to the site-wide checks — status, canonical, noindex, word
count, content hash and every link for each URL it reached. Six scripts used to crawl
independently; on a seven-page fixture that was 97 requests for one audited page and is
now 16, with the response cache below taking most of the rest. The inventory is written
beside the results (`*-crawl.json`, or
`--crawl-json PATH`), because it is the audit's record of which URLs exist and which
are broken. `--crawl-depth` (3) and `--crawl-max-pages` (100) are the whole crawl
budget now, not one of six.

Pacing bounds the rate, not the volume, and one audit of a large site is still a crawl
plus a fetch of every sampled page. If a site owner asks about load, that is the honest
answer. `KNOWN-ISSUES.md` in the plugin root ranks what is still wrong — read it before
defending a number.

## Secrets

`checklist-results.json` and everything under `.seo-runs/` is what gets shared —
with a client, in a ticket, in a repo — and the run log is built from each
script's argv, so a key passed as an argument lands in it verbatim. Values taken
from `INDEXNOW_KEY` and `PAGESPEED_API_KEY` are replaced with `<redacted>`
throughout the payload before anything is written. Credential *paths* are not
secrets and stay readable.

## The score, and how much of the registry it speaks for

**There is no `Coverage %` as of 0.16.** It divided decided items by applicable
ones, which added together three unrelated quantities — how far the tool reached,
how much work the operator had done, and how much of the checklist was never the
audit's job — so it moved for any of the three without saying which. That is this
project's own objection to a single SEO score, one level down.

Two things replace it, and **both must be reported**:

- **SEO Score with its weight share** — `69/100 over 106 items, 55% of the weight
  in scope`. Never quote the score alone: 69 over 55% and 69 over 95% are different
  claims about a site, and only the second one is an audit.
- **The partition** — every item in exactly one bucket, named for whose action moves
  it, and the buckets add up to the registry:

| Bucket | Who moves it |
|---|---|
| decided | — the score is computed over these |
| waiting on you | the operator: unanswered `LLM_PENDING`, plus `NEEDS_INPUT` |
| needs a person | `MANUAL` — answerable, but by a human rather than here; `--manual-answers` merges what they answered |
| undecided | nobody: `NO_DATA` — no such field, service unreachable, check failed |
| not applicable | `N/A` — out of scope for this mode or profile |

When you summarise a run in chat, give the score **with** its weight share and say
what is waiting on the reader. "69/100" on its own is the number this design exists
to stop.

The **per-category** scores use the same severity weighting as the headline score,
so they are comparable with it and with each other. A category still cannot show
"one failing critical" in a number, so each bar also carries the worst open
severity — quote that, not just the score, when a category looks fine at 85.

## Search Console

Auth is a **service account**, not user OAuth. Credentials are discovered in
order: `--gsc-credentials` → `GSC_CREDENTIALS_PATH` → `GV_SA_KEY` →
`~/.config/gcloud/gsc-service-account.json`. Grant access by adding the service
account's `client_email` as a user on the property.

The property defaults to `sc-domain:<registrable domain>` — note that
`www.example.com` is not a property, `example.com` is. Override with
`--gsc-property` for URL-prefix properties.

The registrable domain is derived from a bundled Public Suffix List snapshot, so a
site on a platform domain gets its own property: `something.github.io` is the
registrable domain, not `github.io`. If the snapshot is missing the run falls back
to a heuristic **and says so** — that message means the default property is a
guess and `--gsc-property` is worth passing.

```bash
python3 <SKILL_DIR>/scripts/checklist_runner.py https://example.com/page \
    --gsc-property sc-domain:example.com
```

Eight items are answered from live GSC data: MS-023 and KW-071 (cannibalization),
KW-070 and GO-139 (branded-query ownership), GO-134 (reported opportunities), and
CI-002, CI-010 and GO-135 through the URL Inspection API — whether Google has the page
at all, Google's chosen canonical, and the page's indexing state. CI-010 is the one worth the setup: a page can declare
`rel=canonical` to itself and still have Google pick another URL, and nothing in
the page reveals the disagreement.

Three items report `MANUAL` even with valid credentials, and that is not missing
wiring — **the Search Console API exposes no endpoint for manual actions
(GO-141), the Index Coverage report (GO-142), or mobile-usability signals
(MB-099).** Those exist only in the web UI; mobile usability was withdrawn from
the API in December 2023. The Links report is UI-only too, which is why backlinks
stay manual.

`MANUAL`, not `NO_DATA`: a person can answer all three today in the UI, and that
is what `MANUAL` means everywhere else in this registry. `NO_DATA` would say the
audit tried and failed, sending the reader to fix a tool that is working. Neither
status is counted as decided, so coverage does not move.

GSC is offered only by modes allowed to reach external services. In `archive`
mode a key sitting on disk is ignored and those items report `N/A` — "no network
calls at all" has to hold even when credentials happen to be present.

## Mandatory: answer the LLM queue

`checklist_report.py` writes `LLM-QUEUE.md` — items no script can judge (grammar,
cloaking, doorway pages, translation quality, ad density, people-first content).
**These are not optional.** Left alone they stay `LLM_PENDING` and cap coverage.

It also writes one file per **lens** — the evidence an item is answered from,
which is not the same as the checklist category it sits in. Four agents can run
concurrently, each reading its own slice of the page once:

| Queue file | Agent | Items |
|---|---|---|
| `LLM-QUEUE-copy.md` | [seo-llm-copy](resources/agents/seo-llm-copy.md) | 19 — prose quality, originality, intent match, keyword placement |
| `LLM-QUEUE-layout.md` | [seo-llm-layout](resources/agents/seo-llm-layout.md) | 13 — ads, pop-ups, cloaking, navigation |
| `LLM-QUEUE-locale.md` | [seo-llm-locale](resources/agents/seo-llm-locale.md) | 3 — translation, language/region targeting |
| `LLM-QUEUE-market.md` | [seo-llm-market](resources/agents/seo-llm-market.md) | 3 — competitors, local-traffic need, localized titles |

Splitting by lens rather than by category is deliberate: 16 category agents would
have four of them re-reading the same body copy. Answering the combined
`LLM-QUEUE.md` in one pass is equally valid — the split is for throughput, not
for correctness.

1. Read the actual page content — do not rule from the URL or the queue file alone.
2. Answer each item `PASS` / `FAIL` / `WARN` / `N/A`, with a concrete reason.
3. When the page does not support a verdict, answer `N/A` and say so. Never invent
   a `PASS` to raise the number.
4. Save verdicts as `{"<id>": {"status": "...", "evidence": "..."}}` and merge:
   `checklist_report.py checklist-results.json --llm-answers answers.json`

The merge only overwrites `LLM_PENDING` items — it cannot flip a verdict a script
already established.

## Bundled playbooks

The prose half of the audit ships **inside** the plugin, so it behaves the same
on any machine. Nothing here depends on another plugin being installed. Map:
[playbooks.json](resources/config/playbooks.json); provenance and licences:
`CREDITS.md`.

| Playbook | Use it for | Items |
|---|---|---|
| [local-seo.md](resources/playbooks/local-seo.md) | Business Profile, NAP, citations, reviews | LO-196, LO-199 |
| [competitor-research.md](resources/playbooks/competitor-research.md) | who actually ranks, with sources | CO-191…195, BL-088 |
| [client-report-structure.md](resources/references/client-report-structure.md) | reshaping the report for a decision | — |

**A playbook tells you how to answer an item. It never answers one.** Reading a
playbook does not move a status; doing the work does.

**local-seo** — read when the profile is `local`, or when `seo-llm-market`
answers LO-196 `PASS`. It cannot read the live Business Profile, so LO-199 stays
`MANUAL`; what changes is that the person doing the work gets categories, photo
cadence and citation targets instead of an item title.

**competitor-research** — read while answering CO-191. It uses firecrawl or exa
if those MCP servers are configured and falls back to `WebSearch`/`WebFetch` if
not. If no search tool is available at all, CO-191 is `N/A` — a competitor list
assembled from memory is fabrication with a confident tone.

**client-report-structure** — read when the audit is going to a client. It is
**presentation only**: no status, score or coverage number changes because a
report was reshaped. Run it after the LLM queue is answered.

## Deliverables

- `CHECKLIST-REPORT.md` — summary, priority actions, full checklist, manual items, undetermined items
- `CHECKLIST.html` — filterable view; `MANUAL` items are checkboxes persisted in localStorage
- `LLM-QUEUE.md` + one file per lens — the model's work list
- `checklist-results.json` — machine-readable; also archived to `.seo-runs/<domain>/<timestamp>.json`

Every result carries the `registry_version` it was produced from. `--diff` warns
when two runs came from different registry versions, profiles or modes — without
that, "no status changes" could mean the checklist itself changed underneath.

Priority actions are ranked by severity **against effort**, not severity alone:
ranking by severity puts a week of rewriting above a one-line meta tag. Effort is
a per-category heuristic, not a per-item estimate.

## Extending the registry

```bash
python3 <SKILL_DIR>/tools/build_checklist.py          # rewrite checklist.json
python3 <SKILL_DIR>/tools/build_checklist.py --check  # CI: fail if stale
python3 -m unittest discover -s tests                 # registry + runner + report
```

Edit `tools/build_checklist.py`, never `checklist.json` directly. Two rules:

1. **Write assert rules only against observed script output.** Capture it with
   `tools/probe_shapes.py` and consult
   [script-output-shapes.md](resources/references/script-output-shapes.md).
   A guessed JSON path produces a rule that silently reports `NO_DATA` forever.
2. **Every LLM item needs a lens.** The build refuses without one — otherwise a
   new item belongs to no agent and quietly never gets answered.
