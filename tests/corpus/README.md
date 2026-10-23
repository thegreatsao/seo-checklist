# The corpus

Trees served by `tests/verdict_census.py` alongside the fixture pair. They carry **no
declarations**: the fixture oracle answers "is this verdict right", one hand-written
declaration at a time, and it has reached 122 of 217 items. The corpus answers
the cheaper question — *what range of answers does this item have at all* — and it can
therefore grow for coverage alone, without an oracle round per page.

That separation is the point. `tests/fixtures/broken` carries 117 declarations, so every
page added to it moves declared verdicts and costs a review. A corpus tree costs a
census re-record.

## Why the pages are invented rather than copied

The obvious way to fill the gap the fixtures leave is to save real websites. It is also
redistribution of someone else's content into a public repository, so the corpus does
the next best thing: **the markup shapes are transcribed from real pages, the words are
invented.** A shape is a fact about how the web is built and is not anybody's property;
the prose is ours. Where a real site is genuinely needed — a client's, with permission —
it belongs in an operator's own archive, not here.

## What a corpus tree can and cannot express

`tests/harness._Quiet` is a static file server. It answers **200**, **404** for a
missing file, and **301** for a directory requested without its trailing slash. Since
0.128.0 a tree may carry `_answers.json`, a table of fixed answers — a status, a
`Content-Type` and a body per path, a `delay` before the first byte, and since 0.175.0
`headers`, which is how a table answer sends a `Location`. So a tree can now serve an
error entry page (CI-003 fails on `error-entry/`) and a redirect chain (AR-150 fails on
`redirect-chain/`). Since F05 a route may carry `then`, the answer it gives from its second
request on, and a table may name the same server under its other loopback name,
`http://localhost:8000`, rewritten to the bound port like the usual placeholder. It still
cannot serve a status that varies by user agent, and every corpus tree is served over
plain HTTP.

One item still cannot be seen failing here, and **it is not a limit of this server
alone**: `SE-118` fails on a certificate that does not verify, and the runner's own
request for the entry verifies the same certificate and stops on it, so the entry gate
turns the failure into NO_DATA before the item is graded. That is a defect in what a
finished audit can say, recorded in `docs/sprint-20261021-F06.md` with the repair it needs
(the entry gate answering it, as it does CI-003 since 0.130.0). The census marks it in its
own output, which reads this section.

<!-- Only back-ticked ids in this section are read as unable to fail here
     (`verdict_census.unexercisable`); the ids below are named without backticks on purpose. -->
CI-014 has the same gap for one of its failing shapes — an entry that redirects in a loop
is refused by the runner's request, so a loop is never graded — and fails here on another,
a redirect with no `Location` (`no-location/`), so the census sees it failing.

Everything a page, a stylesheet, a `robots.txt` or a `sitemap.xml` can say is fair game.

## Trees

- `failing-shapes/` — built to fail as many items as a static tree can. Whatever still
  never fails once this tree is served is a candidate for the `MD-184` class: a rule
  that cannot report FAIL on any site in the world. Whatever starts failing is proved to
  have been a gap in the fixtures rather than argued to be one.

Added in 0.175.0 (F06), each aimed at items the census had never seen fail or answer;
the comment above each shape names its item.

- `error-entry/` — the entry answers 503 (`CI-003`, `TE-167`).
- `redirect-chain/` — `/` reaches its page through two redirects, and that page holds
  its first byte for a second (`AR-150`, `TECH-003`).
- `site-defects/` — what a crawl finds: overused exact anchors, thin pages, internal
  links that redirect, broken links, no sitemap (`BL-081`, `CN-039`, `AR-149`, `TE-168`,
  `GO-136`).
- `url-shapes/` — one page at a long, deep, mixed-case address (`AR-147`, `CI-012`).
- `no-location/` — the entry answers 301 and names no `Location` (`CI-014`; found by the
  F06 review).
- `went-down/` — the entry redirects to the same server under its other name, whose page
  answers the audit's own request and 503 after it (`TE-167`, F05). The run audits the
  host it landed on, so the uptime check asks that page again instead of reading the
  answer the entry gate judged from the run's response cache, and the assertion fails
  where the gate did not stop the run.
- `page-defects/` and `page-sound/` — one entry page carrying a defect for each
  page-level item that had never failed or answered, and its twin doing each the way the
  item asks, so those items are seen both ways.

`_inputs/<tree>/` holds what an operator would hand the run for that tree — the
`ARTIFACT_FLAGS` files of `verdict_census.py` and an `indexnow_key` — outside the trees,
so nothing in it is ever served.
