# The corpus

Trees served by `tests/verdict_census.py` alongside the fixture pair. They carry **no
declarations**: the fixture oracle answers "is this verdict right", one hand-written
declaration at a time, and it has reached 121 of 217 items. The corpus answers
the cheaper question — *what range of answers does this item have at all* — and it can
therefore grow for coverage alone, without an oracle round per page.

That separation is the point. `tests/fixtures/broken` carries 116 declarations, so every
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
missing file, and **301** for a directory requested without its trailing slash. It has
no routing table, so a corpus tree cannot serve a 5xx, a redirect chain, a redirect
loop, or a status that varies by user agent. Items that need those — `CI-003`,
`CI-015`, `AR-150`, `CI-014` — stay unexercised by anything here, and the census will
keep reporting them as never seen failing. **That is a limit of the mechanism, not a
finding about the registry**, and it is written here so the next reader of the census
does not have to rediscover it.

Everything a page, a stylesheet, a `robots.txt` or a `sitemap.xml` can say is fair game.

## Trees

- `failing-shapes/` — built to fail as many items as a static tree can. Whatever still
  never fails once this tree is served is a candidate for the `MD-184` class: a rule
  that cannot report FAIL on any site in the world. Whatever starts failing is proved to
  have been a gap in the fixtures rather than argued to be one.
