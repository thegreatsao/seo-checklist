<!-- Updated: 2026-08-16 -->
# Script output shapes

All 57 scripts the registry runs are documented here, plus `site_crawl.py`, which
the runner runs itself before building the plan and whose inventory the site-wide
checks read. Four of them break the
`issues[].severity` + `message` convention the rest share — `gsc_checker.py` and
`indexnow_checker.py` capitalise severity, `indexnow_checker.py` uses `finding`
instead of `message`, and `robots_path_tester.py` emits no `issues[]` at all.
Check the section before writing a rule.

Machine-probed JSON structure of the evidence scripts, captured by running each one
with `--json` against a live URL (https://www.plerdy.com/seo-checklist/, WordPress).
The Search Console scripts were probed separately against a private property the key
is verified on (`sc-domain:<client-domain>`), since they address a property rather than
the audited URL. Which property is deliberately not written down: it belongs to a
client, and nothing in these shapes depends on whose site it was. `checklist.json` assert rules are written against these paths —
re-probe with `tools/probe_shapes.py` after changing any script's output contract.

```bash
python3 tools/probe_shapes.py <url>                       # everything
PROBE_ONLY=html_validator.py,ga4_tag_checker.py \
    python3 tools/probe_shapes.py <url>                   # just what changed
PROBE_GSC_PROPERTY=sc-domain:example.com \
    python3 tools/probe_shapes.py <url>                   # include GSC scripts
```

**Universal pattern:** almost every script returns an `issues[]` array whose items carry
`severity` (`critical`/`high`/`medium`/`low`) plus `message`. Checklist rules lean on this
rather than on per-script bespoke fields wherever possible.

**Shared fetch result:** `error_kind` is `None` when `error` is `None`; otherwise it is
one of the closed vocabulary `unresolved`, `refused`, `timeout`, `tls`, `blocked`,
`robots`, `other`. Scripts that expose a shared fetch result retain the kind beside
the existing human-readable `error`; no reader has to classify library prose.

**Scripts exposing a 0-100 `score`:** security_headers, social_meta, eeat_signal_checker,
freshness_checker, answer_block_scanner, citation_readiness, a11y_seo_checker,
topical_cluster_mapper, llms_txt_checker (`quality.score`), pagespeed (`performance_score`).

## Runtime (single page, cold)

Times below are for a script run on its own. Inside an audit most of them are faster,
because the run shares one response per URL: a script that would fetch the entry page
reads it from the run's cache instead. That is also why a number measured here does not
add up to the audit's wall time.

| Script | Note |
|---|---|
| `site_crawl.py` | one crawl for all site-wide checks; the budget is `--crawl-max-pages` (100) |
| `duplicate_content.py` | fast with `--inventory`: it compares hashes the crawl computed |
| `orphan_pages_from_sitemap.py` | fast with `--inventory`: sitemap membership against the crawl's link graph |
| `pagespeed.py` | ~19s — external PageSpeed API |
| `anchor_text_audit.py` | fast with `--inventory` |
| `external_link_quality.py` | ~10s — checks every outbound link |
| `indexability_matrix.py`, `sitemap_checker.py`, `broken_links.py` | ~6-8s |
| everything else | < 1.5s |

Slow scripts must run first in the pool so they overlap the fast ones.

**Two scripts ask for the same URL twice on purpose,** and a change that "fixes" it
would delete a finding: `redirect_checker.py` sends `HEAD` with redirects *off*
because the hop is what it reports, while `hreflang_checker.py` and
`cache_compression_checker.py` send `HEAD` with them on. Those are different requests
and get different cache entries. CI asserts that nothing else asks twice.

**`lcp_subparts.py` reports the run's fetch, not its own.** `elapsed` travels with a
cached response — three scripts read response time from it, and a zero would be a
fabricated performance number — so TECH-003's TTFB is the one request the audit made
for that page. Use `--no-http-cache` for an isolated timing.

## Scripts needing extra required args

| Script | Missing | Handling |
|---|---|---|
| `robots_path_tester.py` | positional `paths` | CI-019 passes `/search /cart /checkout /login`; CI-013 uses `--discover-assets` |
| `indexnow_checker.py` | `--key` | optional; `NO_DATA` unless key configured |

---

## Per-script structure

### a11y_seo_checker.py

`url` — str
`score` — int
`checks.h1_count` — int
`checks.lang` — str
`checks.viewport` — bool
`checks.images_missing_alt` — int
`checks.form_controls` — int
`checks.labeled_controls` — int
`checks.landmarks.main` — int
`checks.landmarks.nav` — int
`checks.landmarks.header` — int
`checks.landmarks.footer` — int
`checks.inline_contrast_candidates` — int
`issues[]` — array
  - item keys: severity, message
`fetch_error` — NoneType

### ai_crawler_policy_matrix.py

`site` — str
`robots_url` — str
`robots_status` — int
`llms_txt_url` — str
`llms_txt_status` — int
`rows[]` — array
  - item keys: crawler, scope, honours_robots_txt, policy, paths,
    llms_txt_available, alignment
  - `honours_robots_txt` is false for a documented user fetcher that generally ignores
    robots.txt; its `policy` is `not_enforced`, while `paths` retains the site's stated
    rules instead of presenting them as restrictions the fetcher will obey.

### anchor_text_audit.py

Reads `--inventory` (see `site_crawl.py`); crawls one for itself without it.

`truncated` — bool — the crawl behind this stopped at `--max-pages`, so every
  count here is over the pages it read
`fetch_error` — NoneType or str (the crawl's reason, copied through)
`start_url` — str
`pages_crawled` — int
`links_analyzed` — int
`summary.unique_targets` — int
`summary.empty_anchors` — int
`summary.generic_anchors` — int
`summary.nofollow_internal_links` — int
`summary.navigation_links` — int (pairs carried by most pages: site chrome)
`summary.editorial_links` — int (the rest, which is what the repetition checks read)
`summary.overused_exact_match_targets` — int
`summary.low_diversity_targets` — int
`top_anchor_texts[]` — array
  - item keys: anchor, count
`targets[]` — array
  - item keys: target, total_internal_links, editorial_links, unique_anchor_texts, diversity_ratio, top_anchor, top_anchor_count
`examples.empty_anchors[]` — array
  - item keys: source, target, anchor, rel, nofollow
`examples.generic_anchors[]` — array
`examples.nofollow_internal_links[]` — array
  - item keys: source, target, anchor, rel, nofollow
`examples.overused_exact_match_targets[]` — array
  - item keys: target, total_internal_links, editorial_links, unique_anchor_texts, diversity_ratio, top_anchor, top_anchor_count
`examples.low_diversity_targets[]` — array
`issues[]` — array
  - item keys: severity, type, count, message
`fetch_errors[]` — array (per-URL; not the whole-crawl verdict)

### answer_block_scanner.py

`url` — str
`score` — int
`questions[]` — array
`direct_answers[]` — array
`definitions[]` — array
`lists[]` — array
  - item keys: type, items, sample
`tables[]` — array
`issues[]` — array
  - item keys: severity, message
`fetch_error` — NoneType

### article_seo.py

`url` — str
`cms_detected` — str
`title` — str
`meta_description` — str
`og_description` — str
`authors[]` — array
`publish_date` — str
`labels[]` — array
`headings.h1[]` — array
`headings.h2[]` — array
`headings.h3[]` — array
`paragraphs[]` — array
`images[]` — array
  - item keys: src, alt, width, height, loading
`structured_data[]` — array
  - item keys: @type, @context, status, note, has_context, has_type, raw
`readability.flesch_reading_ease` — float
`readability.fkgl` — float
`readability.grade_label` — str
`readability.word_count` — int
`readability.sentence_count` — int
`readability.avg_sentence_length` — float
`readability.avg_syllables_per_word` — float
`target_keyword` — str, absent when no primary keyword can be determined
`keyword_usage.keyword` — str
`keyword_usage.in_body` — bool
`keyword_usage.body_occurrences` — int
`keyword_usage.in_title` — bool

The `keyword_usage` object is absent when no `--keyword` was supplied, because no
usage measurement happened.

`extracted_keywords[]` — array
`related_keywords[]` — array
`seo_issues[]` — array
  - item keys: severity, area, finding, fix

`related_keywords` is Google Suggest's answer when the script is run by hand, and the
page's own extracted terms when it is run by the audit: **KW-076 passes
`--no-autocomplete`**, because a check that asserts `keyword_usage.in_body` has no use
for suggestions and every sampled page would otherwise send the operator's keyword to
a third party.

### broken_links.py

With `--inventory` the scope is the whole site's **internal** links, read out of the
shared crawl with no requests; `scope` says which path produced the answer. Without
one it fetches a single page and checks every link on it, internal and external.

`page_url` — str (the site with `--inventory`, the page without)
`scope` — str: `internal` (inventory) — absent on the single-page path
`total_links` — int
`checked` — int
`truncated` — bool — the answer rests on less than the whole input: the
  `--max-links` cap bit, or a link answered nothing (`summary.unchecked`,
  `summary.timeout`) and so was neither cleared nor found broken
`broken[]` — array
  - item keys: url, anchor_text, is_internal, status, error, error_kind, redirect, response_time_ms, linked_from
`redirected[]` — array
`timeout[]` — array
`unchecked[]` — array (targets the crawl did not reach or policy/robots declined;
counted in neither direction)
`healthy` — int
`summary.total` — int
`summary.healthy` — int
`summary.broken` — int
`summary.redirected` — int
`summary.broken_or_redirected` — int — read by TE-168 for its clean PASS band
`summary.timeout` — int
`summary.unchecked` — int
`issues[]` — array
`error` — NoneType
`fetch_error` — NoneType or str

### cache_compression_checker.py

`url` — str
`resources_checked` — int
`issues[]` — array
`resources[]` — array
  - item keys: url, status, content_type, content_encoding, cache_control, etag, vary, content_length, issues, error
`fetch_error` — NoneType
`truncated` — bool — distinct linked assets after `MAX_ASSETS` remained unchecked,
  so `issues` covers only the page and the assets before the cap

### canonical_checker.py

`count` — int
`rows[]` — array
  - item keys: url, status, final_url, canonical, verdict, issues
`issues[]` — array
`fetch_error` — NoneType or str (no URL answered; CI-009 is `critical`)

### citation_readiness.py

`url` — str
`score` — int
`factual_claims` — int
`claim_samples[]` — array
`citation_signals.external_links` — int
  - reported, and since 0.87.0 not counted as capacity to cite: an ordinary outbound
    link is not a source for the claim above it. The broken fixture's entry page took
    23 of the 35 coverage points from two of them
`citation_signals.trusted_external_links` — int
  - a subset of the above, and these do count: a link to a .gov or a university is a
    source whether or not the author wrapped it in a `<cite>`
`citation_signals.cite_or_blockquote_tags` — int
`citation_signals.footnote_links` — int
  - matched on `rel` tokens and the URL *path*. A query string is not read, because
    `utm_source` is not a source
`citation_signals.schema_citations` — int
  - how many works the page's own nodes declare they cite, counted into
    `citation_capacity` beside the three DOM sources above. A `citation` inside a
    customer's review is not one of them; the count is read through the same boundary
    as the entity signals below
`entity_signals.types[]` — array
`entity_signals.names[]` — array
  - names from the page's own entities, not the author signal read by
    `seo_common.page_author_names`
`entity_signals.sameAs[]` — array
  - signals from the page's own entities: contributor subtrees and hoisted contributor
    nodes are excluded, and so is `citation` since 0.86.0 — a page is not about the
    works it cites, and four cited DOIs took the whole 20-point component. The subject
    the page reviews or is based on stays: `itemReviewed` and `isBasedOn` are what a
    page is about, which is 0.68's reason for keeping them
  - the `mainEntityOfPage` exemption is threaded here as it is in the author, reviewer
    and date readers, so a node the page declares as its own subject survives being
    claimed by a contribution key
`issues[]` — array
  - item keys: severity, message
`fetch_error` — NoneType

### collection_page_checker.py

`source` — str
`final_url` — str
`status` — int
`word_count` — int
`filter_parameters[]` — array
`product_links_detected` — int
`issues[]` — array
  - item keys: severity, message, url, evidence

### critical_request_chain.py

`url` — str
`critical_request_count` — int
`chain_count` — int
`issues[]` — array
  - item keys: severity, message, url
`chains[]` — array
  - item keys: type, url, blocking, preloaded, cross_origin, children
`fetch_error` — NoneType

### css_minify_check.py

`url` — str
`stylesheets[]` — array
  - item keys: href, bytes, minified (bool), ratio (float — bytes per line, the
    minification heuristic), status, error
`checked` — int
`unminified_count` — int
`truncated` — bool — the page links more than `MAX_SHEETS` stylesheets, so
  `unminified_count` counts only the first twelve
`wasted_bytes` — int
`issues[]` — array
`fetch_error` — str | null

Observed on plerdy: 5 stylesheets checked, 3 unminified, 51999 wasted bytes.

### detect_profile.py

Not run by the registry — the runner calls it in-process before the profile
question, and it is also a standalone CLI. Requires `offline`: it reads HTML you
already have (`--html`) or fetches one page.

`url` — str
`profile` — str, one of the profile names or `default`
`confidence` — str (`high` / `low` / `none`)
`scores` — object, one int per profile (`ecommerce`, `local`, `saas`, `blog`, `media`)
`signals` — object, one array of human-readable reasons per profile
`runner_up` — object | null — `{profile, score}` when the top two are close
`error` — str | null

`profile` is `default` with confidence `none` whenever the top score falls below
the threshold: thin evidence produces a refusal to narrow anything, not a guess.
`runner_up` is populated only when the margin is small, which is what turns the
suggestion from `high` to `low` confidence.

Observed on a lakeside resort: `local` at 8 (Restaurant schema, opening hours,
click-to-call), `ecommerce` at 2 (price markup), confidence `high`.

### domain_safety_check.py

`url` — str
`domain` — str
`uptime.checked` — bool
`uptime.reachable` — bool
`uptime.status` — int
`uptime.response_ms` — int
`uptime.error` — str | null
`safe_browsing.checked` — bool
`safe_browsing.error` — str
`whois.checked` — bool
`whois.created` — str (`YYYY-MM-DD`)
`whois.registrar` — str
`whois.queried` — str — the registrable domain actually queried, which is not the
  audited host: asking whois about `www.plerdy.com` returns the `.com` zone record
`whois.age_days` — int
`neighbors.checked` — bool
`neighbors.ip` — str
`issues[]` — array

Two fields are **never** populated without extra setup, and no rule should assume
them. `safe_browsing.matches` appears only when `GOOGLE_SAFE_BROWSING_KEY` is set —
unobserved, so do not write rules against its shape. `neighbors.suspicious` is
deliberately never fabricated, because enumerating co-hosted domains needs a paid
reverse-IP service. Both report `checked: false` with a reason instead.

### duplicate_content.py

Reads `--inventory` (see `site_crawl.py`): the word count, the content hash and the
MinHash signature are computed by the crawl, so this script compares pages rather
than fetching them.

`truncated` — bool — the crawl behind this stopped at `--max-pages`, so every
  count here is over the pages it read
`fetch_error` — NoneType or str
`pages_analyzed` — int
`exact_duplicates[]` — array
  - item keys: type, severity, urls, finding, fix
`near_duplicates[]` — array
  - item keys: type, severity, similarity, url_a, url_b, word_count_a, word_count_b, noindex_in_pair, finding, fix
`thin_content[]` — array
  - item keys: type, severity, url, word_count, threshold, finding, fix
`duplicate_titles[]` — array — groups of pages sharing one title, compared on
  collapsed whitespace and case. Pages with **no** title are not counted as
  duplicates of each other — that is MS-026's finding.
  - item keys: type, severity, title, urls, finding, fix
`duplicate_descriptions[]` — array — groups of pages sharing one meta description,
  compared on collapsed whitespace and case, since two descriptions differing by a
  trailing space are one description to anyone reading a SERP. Pages with **no**
  description are not counted as duplicates of each other — that is MS-028's finding
  and counting it here would report one defect under two items.
  - item keys: type, severity, description, urls, finding, fix
`summary.exact_duplicate_groups` — int
`summary.duplicate_title_groups` — int — **what MS-022 asserts is zero.** The item
  read `exact_duplicates` until 0.43, which counts duplicate page *content* —
  CN-041's verdict — and did not measure titles at all.
`summary.near_duplicate_pairs` — int
`summary.thin_pages` — int
`summary.duplicate_description_groups` — int — **what MS-029 asserts is zero.** That
  item read `exact_duplicate_groups` until 0.22, which counts duplicate page *content*
  — CN-041's verdict — so a site running one description across forty distinct pages
  passed it.
`summary.avg_word_count` — int

### eeat_signal_checker.py

`url` — str
`score` — int
`lang` — str | None — declared primary language subtag, or null when none is declared
`matched_locales[]` — array — sorted vocabularies used: English plus a carried declared locale
`signals.authors[]` — array
  - people only since 0.51.0: `meta[name=author]`, `rel=author`, an exact byline class
    token, and JSON-LD `author`. `publisher` used to be read into this same list, so a
    page naming no human passed CN-057.
  - the page's **own** credits since 0.66.0. An `author` reached through a contribution
    key (`review`, `reviews`, `comment`, `comments`, `acceptedAnswer`,
    `suggestedAnswer`, `userComments`) or a subject key (`itemReviewed`, `citation`,
    `isBasedOn`) belongs to whoever contributed it, not to the page, and so does a node
    whose `@id` is referenced from under a contribution key. A product page carrying one
    customer review used to report the shopper as its author and pass CN-057.
`signals.reviewers[]` — array
  - JSON-LD `reviewedBy` only, separate from `authors` since 0.66.0. A page whose only
    credit was a review board reported an author, and a page naming a publisher and a
    reviewer but no author passed CN-057. No registry rule reads this field; it is
    evidence for the operator, and the measurement anyone repricing a reviewer signal
    into the score would start from.
`signals.publishers[]` — array
  - JSON-LD `publisher`, organisation-typed nodes not credited as author or reviewer,
    `og:site_name`, `article:publisher`, `meta[name=copyright]`. Read over the same
    page-own sweep as `authors`, so an organisation named inside a customer review is
    not the site's identity either.
`signals.authorship` — object — read by CN-057
  - `author` / `publisher` — bool — the two halves of *Show Author and Publisher
    Clearly*. Re-probed 2026-08-15 against the same WordPress page as the rest of this
    file: `authors []`, `publishers ['Plerdy', …2]`, `authorship {author: False,
    publisher: True}` — a checklist article with no byline, which is the verdict the
    item's title asks for.
`signals.credential_markers[]` — array
`signals.first_hand_experience_markers[]` — array
`signals.policy_links[]` — array
  - locale-aware editorial standards only: fact-checking, corrections, ethics. Not privacy.
`signals.privacy_links[]` — array
  - locale-aware privacy, data protection, GDPR, cookie-policy terms and URL fragments.
    CN-040 reads this; it used to read `policy_links`, which answered a different
    question in both directions.
`signals.trust_links[]` — array
  - the loosest of the three: locale-aware institutional links, an "About" page
    included, plus language-neutral `tel:` and `mailto:` routes.
  - these three arrays hold the page's own links; a credit written inside somebody
    else's contribution is not one.
  - all three arrays use English plus the page's declared carried locale; an
    undeclared or uncarried language uses English alone.
  - item keys (all three arrays): href, text, rel
`signals.external_citations` — int
`issues[]` — array
  - item keys: severity, message
`fetch_error` — NoneType

### entity_checker.py

`url` — str
`entity_name` — str
`entities_in_schema[]` — array
  - item keys: type, name, url, sameAs, logo, description, identifier
`sameas_analysis.issues[]` — array
`sameas_analysis.total_found` — int
`sameas_analysis.total_missing_critical` — int
`wikidata.found` — bool
`wikidata.qid` — NoneType
`wikidata.url` — NoneType
`wikipedia.found` — bool
`wikipedia.url` — NoneType
`google_kg.checked` — bool
`google_kg.found` — bool
`google_kg.result` — NoneType
`nap_issues[]` — array
`issues[]` — array
  - item keys: severity, area, finding, fix
`summary.entities_found` — int
`summary.sameas_count` — int
`summary.sameas_missing_critical` — int
`summary.wikidata_found` — bool
`summary.wikipedia_found` — bool
`summary.google_kg_checked` — bool
`summary.google_kg_found` — bool
`summary.total_issues` — int

### external_link_quality.py

`sources[]` — array
`pages[]` — array
  - item keys: url, status, error, error_kind
`summary.external_links_found` — int
`summary.unique_external_links` — int
`summary.checked_links` — int
`summary.broken_links` — int
`summary.unreachable_links` — int
`summary.unchecked_links` — int
`summary.redirecting_links` — int
`summary.low_trust_pattern_links` — int
`summary.commercial_rel_review` — int
`top_external_hosts[]` — array
  - item keys: host, count
`links[]` — array
  - item keys: source, url, anchor, rel, nofollow, sponsored, ugc, host, low_trust_pattern, status, final_url, redirect_chain, error, error_kind
`issues[]` — array
  - item keys: severity, type, count, message
`errors[]` — array — item keys: url, status, error, error_kind

### faceted_nav_audit.py

`count` — int
`rows[]` — array
  - item keys: url, path, params, facet_params, flags
`issues[]` — array
`truncated` — bool — internal URLs after `MAX_URLS_FROM_PAGE` remained unaudited,
  so `rows` and `issues` cover only the page-derived URLs before the cap

### favicon_check.py

`url` — str
`favicon.declared` — bool or NoneType
`favicon.href` — str or NoneType  (the href as declared in the page)
`favicon.url` — str or NoneType  (resolved against the fetched page URL)
`favicon.status` — int or NoneType
`favicon.content_type` — str or NoneType
`favicon.format` — str or NoneType  (png | ico | gif | jpeg | webp | svg)
`favicon.width` — int or NoneType
`favicon.height` — int or NoneType
`favicon.min_side_px` — int or NoneType  (raster images only)
`favicon.displays_at_48px` — bool  (absent when the page was not fetched or the
  fetched icon's format was not recognised, so an unmade measurement stays NO_DATA)
`favicon.reason` — str
`issues[]` — array
  - item keys: severity, message, url, evidence
`truncated` — bool — the answer rests on less than the whole input: more distinct
  external links than `--max-links`, so the ones past it were never requested, or
  a requested link answered nothing (`summary.unchecked_links`). A dead host is
  not here — that is a finding, and it is already counted as broken
`fetch_error` — NoneType or str

### font_audit.py

`url` — str
`font_file_count` — int
`font_face_count` — int
`preload_count` — int
`preconnect_count` — int
`issues[]` — array
`fonts[]` — array
`font_faces[]` — array
`fetch_error` — NoneType

### freshness_checker.py

`url` — str
`score` — int
`latest_date` — str
`age_days` — int
  - both are computed from dates that are not in the future, while `dates[]` still
    carries every parsed date, including future dates
`dates[]` — array
  - item keys: source, raw, date
  - schema and `<time>` dates come from the page's own nodes; contributions and subjects
    are excluded whether nested under their key or, for schema dates, hoisted into
    `@graph`
`old_years[]` — array
`stale_stat_sentences` — int
`schema_date_mismatch` — bool
`issues[]` — array
  - item keys: severity, message
`fetch_error` — NoneType

### ga4_tag_checker.py

`url` — str
`measurement_ids[]` — array of str (e.g. `G-15X5JYHSHC`)
`gtm_containers[]` — array of str
`ua_legacy[]` — array of str — retired `UA-` properties still on the page
`duplicates[]` — array — the same ID configured more than once
`loaders.gtag_js` — int
`loaders.gtm_js` — int
`issues[]` — array
`fetch_error` — str | null

### gsc_cannibalization.py

Requires `gsc` capability. Probed against the private property described at the top
of this file.

`property` — str
`period.start` / `period.end` — str (`YYYY-MM-DD`)
`queries_analyzed` — int
`queries[]` — array, capped at 1,000 with every classified query first
  - item keys: query, brand_form, page_count, impressions, spread,
    positions_compared,
    bucket (`cannibalized`, `contested`, `branded_spread`, or `single_page`)
  - matched brand queries also carry matched_brand_term and edit_distance
  - the buckets are exclusive;
    `summary.cannibalized_queries = bucket[cannibalized] + bucket[contested]`
  - `single_page` is the catch-all for fewer than two eligible logical pages, not
    a claim that exactly one page exists; a query can carry `page_count: 0`
  - query, page_count, impressions and spread deliberately repeat classified-list
    data so readers do not need a join; brand_form deliberately exposes the
    normalized verdict rather than requiring readers to reproduce normalization
`queries_truncated` — bool — the evidence list was shortened after counting
`truncated` — bool — the API answered with a full page of rows (`ROW_LIMIT`),
  so there were query/page rows this analysis never saw. Upstream of every
  count in `summary`, unlike `queries_truncated`, which is downstream of them
`cannibalized[]` — array, capped at 25 for human-facing output; the cap is on
  the listing only — `summary.cannibalized_queries` counts them all
  - item keys: query, pages[] (page, clicks, impressions, position), page_count,
    clicks, impressions, spread (float — max minus min position),
    positions_compared
`branded_spread[]` / `contested[]` — arrays with the same item shape and
human-facing 25-entry cap
`branded.checked` — bool
`branded.query` / `branded.owner_page` / `branded.host` — str
`branded.position` — float
`branded.clicks` — int
`branded.owns_homepage` — bool
`branded.ranks_first` — bool
`summary.cannibalized_queries` — int
`summary.contested_queries` — int
`issues[]` — array
`error` — str | null

When the range holds no query data, `branded` collapses to
`{checked: false, reason: "..."}` and the sub-fields are absent — so rules on
`branded.*` yield `NO_DATA`, not a verdict.

### gsc_checker.py

Requires `gsc` capability.

`site_url` — str
`days` — int
`performance.period` — str (`YYYY-MM-DD to YYYY-MM-DD`)
`performance.total_rows` — int
`performance.data[]` — array
  - item keys: query, page, clicks, impressions, ctr, position
`opportunities[]` — array
  - item keys: type, severity, query, page, position, impressions, finding, fix
`top_pages[]` — array
  - item keys: page, clicks, impressions, ctr, position
`sitemaps[]` — array
  - item keys: path, type, last_submitted, last_downloaded, is_pending, errors,
    warnings, contents[]
`issues[]` — array  (**probed empty**: the property's one sitemap reports
  `errors = "0"`, `warnings = "0"`, so there was nothing to list. Item keys are from
  `detect_issues` in the script and are exercised by
  `tests/test_translated_sites.py`, not by this probe — the only entry here whose
  item keys a probe has not seen.)
  - item keys: type, severity, sitemap, finding, fix, plus `errors` or `warnings`
`issues` — **absent entirely** when the sitemap report could not be read, so the item
  reading it is `NO_DATA` rather than passing on an empty answer. `detect_issues`
  returns `None` for that case and the key is omitted; an empty array means "read it,
  nothing wrong".

**Severity here is capitalised** (`"High"`, not `"high"`) — unlike every other
script — *except* in `issues[]`, which 0.23.0 added in the lower case the rest of the
tree uses. `none_severity` lowercases both sides, so both match; a rule written with a
raw string comparison would silently never fire on one of them.

`errors` and `warnings` in `sitemaps[]` are **strings** (`"0"`), which is why
`detect_issues` coerces them: `s.get("errors", 0) > 0` is true for `"0"`.

### gsc_links_csv.py

Requires `offline` — it reads a file you exported, so even `archive` mode can use
it. Probed against a two-sheet export (top linking sites, top linking text).

`source` — str, absolute path of the export
`site` — str, whatever was passed as `--site`
`linking_domains` — int
`total_links` — int
`top_sites[]` / `anchors[]` / `top_linked_pages[]` — arrays, capped at 50
  - item keys: name, count
`anchor_profile.branded` / `.generic` / `.other` / `.classified` — int
`concentration.top1_share_pct` — float | null
`concentration.top10_share_pct` — float | null
`note` — str | null, set when a single unnamed CSV had to be guessed at
`issues[]` — array
`error` — str | null

The Links report has **no API** — not in v3, not in v1. This parses the UI export
and nothing else, which is why the incoming-link items report `NO_DATA` until
`--links-csv` is passed. Both `concentration` fields are null when the export
carried no linking-sites sheet, so rules on them stay undecided rather than
passing on an empty file.

### gsc_url_inspection.py

Requires `gsc` capability. Addresses a page, so it takes both the URL and the
property. Quota: 2000 inspections per property per day.

`inspected_url` / `property` — str
`verdict` — str (`PASS` / `NEUTRAL` / `FAIL`)
`coverage_state` — str — prose, not an enum (`"Submitted and indexed"`)
`indexing_state` — str (`INDEXING_ALLOWED`, `BLOCKED_BY_META_TAG`, …)
`robots_txt_state` — str (`ALLOWED` / `DISALLOWED`)
`page_fetch_state` — str (`SUCCESSFUL`, …)
`last_crawl_time` — str (ISO-8601 with `Z`)
`crawled_as` — str (`MOBILE` / `DESKTOP`)
`google_canonical` / `user_canonical` — str | null
`canonical_match` — bool, **absent** when the page declares no canonical
`indexed` — bool, **absent** when the coverage wording is unrecognised or the API
  never answered
`sitemaps[]` — array of str
`referring_urls` — int
`rich_results_verdict` — str | null
`issues[]` — array
`error` — str | null

Both fields are **omitted**, not null, when they have no answer: `canonical_match` when
the page declares no canonical — there is nothing to disagree with — and `indexed` when
the coverage wording is unrecognised or the API never answered, because an unfamiliar
string must not be read as "not indexed". The distinction is the whole point and it is
not cosmetic: `truthy` reads `null` as a **failing value**, so a pre-seeded `None`
reports a defect about a page nobody measured. `canonical_match` was fixed for that
reason; `indexed` carried the same defect unnoticed until 0.26.0 pointed CI-002 at it,
because until then no rule read it. Absent, both land on `NO_DATA`.

### hreflang_checker.py

`url` — str
`implementation_method` — str
`hreflang_tags_found` — int
`tags[]` — array
  - item keys: lang, raw_lang, url, raw_url
`sitemap.found` — bool
`sitemap.url` — str
`sitemap.has_xhtml_namespace` — bool
`sitemap.language_variants_found[]` — array
`sitemap.note` — str
`checks.self_reference.passed` — bool
`checks.self_reference.detail` — str
`checks.x_default.passed` — bool
`checks.x_default.detail` — str
`checks.protocol_consistency.passed` — bool
`checks.protocol_consistency.detail` — str
`checks.url_structure.passed` — bool — **absent** when `structure` is `single`, so a
  page with one alternate is `NO_DATA` rather than credited with a structure
`checks.url_structure.structure` — str (`ccTLD` / `subdomain` / `subdirectory` /
  `parameter` / `mixed` / `single`)
`checks.url_structure.detail` — str, on the passing and the `single` cases
`checks.url_structure.finding` / `.fix` / `.severity` — str, on the failing two
`checks.canonical_alignment.passed` — bool
`checks.canonical_alignment.detail` — str
`checks.return_tags.verified` — bool
`checks.return_tags.alternates_checked` — int
`checks.return_tags.verified_and_valid` — bool — **absent** when verification was not
  requested or any alternate could not be fetched, so IN-122 reports `NO_DATA`
  instead of inferring validity from an incomplete check
`checks.return_tags.detail` — str
`language_code_issues[]` — array
`return_tag_checks[]` — array
  - item keys: passed, severity, confidence, finding, fix, alternates
`summary.critical` — int
`summary.high` — int
`summary.medium` — int
`summary.low` — int
`summary.passed` — int

### html_validator.py

W3C Nu validator (`validator.w3.org/nu/`) — free, no key.

`url` — str
`source` — str (`served` / `rendered`) — CI-017 validates what the server sent;
  TE-181 passes `--rendered-json` and validates the DOM recorded in a rendered-page
  artifact. That is the same artifact `rendered_audit.py` reads, with an added `html`
  key holding the serialised DOM. **No browser runs inside the audit**: one launched
  mid-run fetches the page and its subresources again behind the response cache, which
  took a fixture audit from 22 requests to 31 and asked for the entry URL three times.
`render_error` — str | null — why there was no document to validate: the artifact was
  unreadable, was not JSON, was not an object, or recorded measurements without `html`.
`summary.errors` — int — **absent** when `--rendered-json` was given but the artifact
  yielded no document. TE-181 asserts `eq: 0` on it, and an absent key is NO_DATA: a
  DOM that was never built cannot pass or fail validation. Without the flag at all the
  placeholder is unresolved and the runner reports NEEDS_INPUT before the script runs.
`summary.warnings` — int
`summary.info` — int
`messages[]` — array, capped at 40
  - item keys: type (`error`/`info`/`warning`), subType, message, line, extract
`issues[]` — array
`error` — str | null

Observed on plerdy: 484 errors, 0 warnings, 517 info. Counts in the hundreds are
normal for a WordPress theme, so rules should target `summary.errors` thresholds
rather than demanding zero.

### rendered_audit.py

Reads a JSON file of measurements taken from a rendered page (chrome-devtools MCP
`evaluate_script`); takes no URL and makes no request. Registry args:
`["{rendered_json}"]`, so without `--rendered-json` the placeholder is unresolved
and CN-034/035/051, MB-094, MB-103, MB-107 and MB-108 report NEEDS_INPUT — the
item applies and one file is what stands in the way, which is not the same as the
site having served no such field.

`url` — str or null
`source` — str — `"unspecified"` when the file did not say
`viewport.width` — number — **required**; the file is refused without it
`viewport_class` — str — `mobile` when width ≤ 480, else `desktop`
`measured[]` / `missing[]` — arrays of str
`text_nodes_below_12px` — int — CN-034
`links_indistinct` — int — CN-035 (neither underlined, nor bolder, nor a different
  colour from the parent)
`overlays_covering_content` — int — CN-051 (fixed/sticky elements covering ≥25% of
  the viewport)
`tap_targets_below_48px` — int — MB-103, **mobile renders only**
`mobile_overlays_covering_content` — int — MB-094, **mobile renders only**; derived
  from `overlays_covering_content`
`horizontal_overflow_px` — int — MB-107, **mobile renders only**; how far
  `documentElement.scrollWidth` exceeds `innerWidth`, floored at 0. Asserted `lte: 1`
  and not `eq: 0` because both are integers and one pixel of rounding is not a page
  that scrolls sideways
`text_nodes_clipped` — int — MB-108, **mobile renders only**; headings, paragraphs,
  links, buttons and list items whose own content overflows their box in either axis.
  A deliberate `text-overflow: ellipsis` is counted, which is a known false fail

From a desktop render the four mobile keys are dropped rather than zeroed, and the
`missing[]` entry says how wide the render was. A desktop window cannot answer a
question about tap targets, and a 0 would be a verdict about a viewport nobody
looked at.

### cwv_metrics.py

Reads a JSON file written from a browser performance trace (chrome-devtools MCP);
takes no URL and makes no request. Registry args: `["{cwv_json}"]`, so without
`--cwv-json` the placeholder is unresolved and SP-214/215/216 report NEEDS_INPUT.

`url` — str or null (whatever the trace file recorded)
`source` — str — free text describing the trace; `"unspecified"` when absent
`measured[]` — array of str — which metrics the file carried
`missing[]` — array of str — which it did not
`lcp_ms` — int/float — **absent** when not measured
`cls` — float — absent when not measured
`tbt_ms` — int/float — absent when not measured
`<metric>_rating` — str — `good` | `needs_improvement` | `poor`
`all_good` — bool — over the measured metrics only

Absent rather than zero, deliberately: a metric nobody measured must not read as a
perfect score. Units live in the key names because a bare `lcp` of 2.1 could be
seconds or milliseconds, and guessing wrong turns a failing page into a passing
one — the script refuses the file instead.

### image_inventory.py

`url` — str
`count` — int — **absent on a page with no images**
`missing_alt` — int — **absent on a page with no images**
`summary.images` — int
`summary.lazy_lcp_candidates` — int — CN-054's compatibility path: JS-deferred images
  with `data-src`/`data-srcset` but no native `src`, `srcset`, or `<picture>` source.
  Native `loading=lazy` remains discoverable and does not increment this count.
  **Absent on a page with no images.**

Those three are the fields the registry reads as a verdict, and since 0.49.0 a page
with no images emits none of them, so the four items over this script report `NO_DATA`
there rather than a FAIL for MD-184 and a free PASS for CI-016, MD-186 and CN-054. The
descriptive counts stay: `summary.images` is 0 because the page has none, which is a
fact about the page rather than a claim about its images. Same rule, same reason, as
`responsive_count` and `modern_format_count` in `image_weight_audit.py` below.
`issues[]` — array
  - item keys: severity, message, url
`images[]` — array
  - item keys: src, alt, has_alt, width, height, is_responsive_fill, loading, srcset, sizes, format, likely_lcp_candidate
    `likely_lcp_candidate` comes from `seo_common.likely_lcp_candidate`: first in
    document order, or `fetchpriority=high`, or `loading=eager` — and never an image
    whose *declared* size is under 100×100, because an icon is not the largest paint.
    One definition, shared with `image_weight_audit.py`.
`fetch_error` — NoneType

### image_weight_audit.py

With `--inventory` the scope is every distinct image URL in the shared crawl.
Without one it audits one page's image markup and optional fetched bytes.

`url` — str
`image_count` — int
`images_status_checked` — int — 0 unless `--fetch-images` was passed
`unchecked_image_count` — int — fetched images whose failure did not prove absence
`broken_image_count` — int — **absent** when no HTTP status or definitive dead-network
  result was collected. MD-187 asserts `eq: 0` on it, and an absent key is NO_DATA:
  reporting 0 because nothing was learned would turn "we did not look" into "nothing
  is broken". `None` would be worse still — an equality assertion reads it as a
  failure.
`broken_images[]` — array of str — absent under the same condition
`known_image_bytes` — NoneType
`modern_format_count` — int — absent when the page has no images; otherwise, images
  the browser can obtain in avif or webp, counting
  a `<picture><source type="image/webp">` as well as an `img` whose own src is one.
  MB-097 reads this and carries the modern-format weight. Until 0.7.0 only the `img`
  was read, so the recommended pattern
  — modern format in a `<source>`, png fallback in the `<img>` — counted as no modern
  format at all and failed the item it exists to satisfy.
`responsive_count` — int — absent when the page has no images; otherwise, images
  with a `srcset`, on the `img` or on a `<source>`
  beside it. MB-096 and MD-189 read this; MD-189 defers to MB-096 so the shared
  responsive-image fact carries weight once. The count was wrong in the same direction.
`modern_format_on_img_count` — int — the narrow count: `img` src only
`srcset_on_img_count` — int — the narrow count: `img` attribute only
`picture_count` — int — images wrapped in a `<picture>` carrying a `<source>`
`truncated` — bool — an image on this page answered nothing, so the counts above are
  over the images that did. `broken_image_count` is withheld outright when nothing
  broken was found; this is the other half, said beside a count that *was* emitted
  because something broken was found and is therefore a floor
`issues[]` — array
  - item keys: severity, message, url
`images[]` — array
  - item keys: src, format, width, height, loading, fetchpriority, srcset, sizes,
    picture_source_count, picture_srcset, picture_modern_formats, responsive,
    modern_format, likely_lcp_candidate, status, content_length, content_type
`fetch_error` — NoneType

Inventory mode:

`url` — str
`summary.pages_with_images` / `.pages_without_images` — int
`summary.images` — int — the sum of each page's **distinct** references, not every
  reference: the crawl de-duplicates per page, so four `<img>` tags pointing at one
  URL on one page count once here
`summary.unique_images` / `.images_checked` — int
`summary.unchecked_images` / `.images_dropped` — int
`broken_image_count` — int — absent when no image check produced usable evidence
`broken_images[]` — array of str — absent under the same condition
`broken[]` — array
  - item keys: url, status, error_kind, pages
`truncated` — bool — true for any of three reasons: the crawl behind this was capped,
  an image answered nothing, or an image sat past `--max-images` and was never asked.
  `broken_image_count` and `broken_images` are absent whenever one of the last two
  applies and nothing broken was found
`fetch_error` — NoneType or str

### indexability_matrix.py

`site` — str
`count` — int
`fetch_error` — NoneType or str (no URL answered; three `critical` items read `rows.0`)
`rows[]` — array
  - item keys: url, final_url, status, robots_allowed, robots_rule, meta_robots, x_robots_tag, snippet_controls, canonical, in_sitemap, redirects, verdict, blockers, error
`rows[].snippet_controls` — object
  - keys: restricted, nosnippet, nosnippet_sources, max_snippet,
    max_snippet_sources, data_nosnippet_count, data_nosnippet_sources,
    snippet_availability
  - `snippet_availability` is `full`, `limited` for a positive cap or one or more
    `data-nosnippet` elements, or `suppressed` for `nosnippet`, a zero cap, or a page
    with no visible text left outside its `data-nosnippet` elements; the key is absent
    when neither a document nor an `X-Robots-Tag` was read
  - `max_snippet` is the effective integer: -1 is unlimited, 0 suppresses the
    snippet, and the smallest non-negative value wins when sources disagree

### indexnow_checker.py

Requires `--key`; the registry passes `{indexnow_key}` and the item reports
`NO_DATA` when none is configured. IndexNow keys are self-issued — you invent the
string and prove ownership by serving `<key>.txt` from the site root.

`url` — str
`key` — str, truncated in the output (`0000...dead`)
`checks.key_file` / `checks.meta_tag` / `checks.robots_txt` — objects
  - keys: passed (bool | null), severity, finding, fix
`issues[]` — array
  - item keys: passed, severity, finding, fix
`summary.passed` / `summary.failed` / `summary.info` — int
`key_valid` — bool — the roll-up GEO-007 reads: True only when `/<key>.txt` is served
  and contains the key. Added in 0.8.0; it had never been emitted, so GEO-007 reported
  NO_DATA on every site including one with a correctly hosted key. The meta tag and
  the robots.txt reference are optional in the protocol and do not affect it.

**No `message` field, and severity is capitalised** (`"Critical"`, `"Info"`) — this
script predates the `issues[].severity` + `message` convention the rest follow.
`passed: null` means the check is informational, not that it failed.

### internal_links.py

Reads `--inventory` (see `site_crawl.py`). `pages` is keyed by page URL, so the paths
below are examples rather than a schema.

`truncated` — bool — the crawl behind this stopped at `--max-pages`, so every
  count here is over the pages it read
`fetch_error` — NoneType or str
`start_url` — str
`domain` — str
`pages_crawled` — int
`total_internal_links` — int
`unique_pages_found` — int
`max_depth_reached` — int
`pages.<url>.outgoing_links` — int (distinct internal targets)
`pages.<url>.incoming_links` — int (distinct pages linking here)
`anchor_texts.<anchor>` — int (top 20)
`link_distribution.min` / `.max` — int
`link_distribution.avg` — float
`orphan_candidates[]` — array
  - item keys: url, incoming_links
`nofollow_links[]` — array
  - item keys: url, anchor_text, nofollow, source
`internal_redirects[]` — array — AR-149's subject
  - item keys: url, to, hops, linked_from
`summary.pages` — int
`summary.internal_links` — int
`summary.internal_redirects` — int — read by AR-149
`summary.orphan_candidates` — int
`summary.nofollow_internal_links` — int
`summary.links_without_anchor_text` — int
`summary.pages_under_three_links` — int
`summary.pages_over_hundred_links` — int
`issues[]` — array of str
`recommendations[]` — array of str
`error` — NoneType

### javascript_render_audit.py

`url` — str
`raw.title` — str
`raw.meta_description` — str
`raw.canonical` — str
`raw.h1_count` — int
`raw.internal_link_count` — int
`raw.schema_count` — int
`raw.word_count` — int
`rendered` — object or null — null unless the supplied rendered-page artifact carried
  a non-empty `html` string; otherwise it has the same fields as `raw`
`diffs[]` — array — **absent** unless a rendered document existed. MB-105 asserts
  `len_eq: 0` on it, and an absent key is NO_DATA: an empty array would claim parity
  for documents that were never compared.
`render_error` — str or null — exactly one of `no rendered artifact provided`,
  `rendered artifact could not be read: <OSError>`, `rendered artifact is not JSON:
  <JSONDecodeError>`, `rendered artifact is not an object`, or `rendered artifact
  carries no \`html\`; the trace recorded measurements but not the document`; null
  when the artifact supplied a rendered document
`fetch_error` — NoneType

### lcp_subparts.py

`source` — str
`final_url` — str
`mode` — str
`lcp_ms` — NoneType
`lcp_element_url` — str
`subparts.ttfb_ms` — int
`subparts.resource_load_delay_ms` — NoneType
`subparts.resource_load_duration_ms` — NoneType
`subparts.element_render_delay_ms` — NoneType
`response_headers.date` — str
`response_headers.content-type` — str
`response_headers.transfer-encoding` — str
`response_headers.connection` — str
`response_headers.cf-ray` — str
`response_headers.cf-cache-status` — str
`response_headers.age` — str
`response_headers.last-modified` — str
`response_headers.link` — str
`response_headers.server` — str
`response_headers.strict-transport-security` — str
`response_headers.vary` — str
`response_headers.cf-apo-via` — str
`response_headers.alt-svc` — str
`response_headers.cf-edge-cache` — str
`response_headers.permissions-policy` — str
`response_headers.referrer-policy` — str
`response_headers.x-content-type-options` — str
`response_headers.x-frame-options` — str
`response_headers.speculation-rules` — str
`response_headers.server-timing` — str
`response_headers.report-to` — str
`response_headers.nel` — str
`response_headers.content-encoding` — str
`confidence` — str
`notes[]` — array
`error` — NoneType

### link_profile.py

Reads `--inventory` (see `site_crawl.py`). `total_internal_links` counts every `<a>`,
not distinct targets — link equity divides among links.

`truncated` — bool — the crawl behind this stopped at `--max-pages`, so every
  count here is over the pages it read
`fetch_error` — NoneType or str
`pages_crawled` — int
`total_internal_links` — int
`total_external_links` — int
`unique_internal_targets` — int
`unique_external_domains` — int
`avg_internal_links_per_page` — float
`robots_refused[]` — array (kept out of the orphan arithmetic on purpose)
`orphan_pages.count` — int — read by CI-008
`orphan_pages.urls[]` — array
`dead_end_pages.count` — int
`dead_end_pages.urls[]` — array
`top_linked_pages[]` — array
  - item keys: url, inbound_links
`top_external_domains[]` — array
  - item keys: domain, links
`issues[]` — array — read by AR-162
  - item keys: type, severity, count, finding, pages, fix
`site_url` — str

### llms_txt_checker.py

`url` — str
`full_url` — str
`exists` — bool
`full_exists` — bool
`status` — int
`full_status` — int
`parsed.title` — NoneType
`parsed.description` — NoneType
`parsed.sections[]` — array
`parsed.links[]` — array
`quality.score` — int
`quality.issues[]` — array
`quality.suggestions[]` — array
`error` — NoneType

### local_seo_checker.py

With `--inventory`, LO-198 uses site scope without refetching pages. The fields below
remain present, and the site path additionally emits `scope`, `pages_checked`, and
`local_business_pages[]`. Without the inventory, LO-200 keeps the single-page shape.

`source` — str
`final_url` — str
`status` — int or NoneType
`fetch_error` — NoneType or str (the page could not be read; LO-198 and LO-200 are `high`)
`local_business_nodes` — int
`nap_complete` — bool: true when every LocalBusiness node has name, address, and telephone; written only for a page carrying at least one LocalBusiness node, so a page with none reports no key and the item answers NO_DATA
`scope` — str: `site` (inventory only)
`pages_checked` — int (inventory only)
`local_business_pages[]` — array (inventory only)
`phones_detected[]` — array
`map_embeds` — int
`issues[]` — array
  - item keys: severity, message, url, evidence

### mobile_render_checker.py

`source` — str
`url` — str
`fetch.input_url` — str
`fetch.url` — str
`fetch.status` — int
`fetch.headers.date` — str
`fetch.headers.content-type` — str
`fetch.headers.transfer-encoding` — str
`fetch.headers.connection` — str
`fetch.headers.cf-ray` — str
`fetch.headers.cf-cache-status` — str
`fetch.headers.age` — str
`fetch.headers.last-modified` — str
`fetch.headers.link` — str
`fetch.headers.server` — str
`fetch.headers.strict-transport-security` — str
`fetch.headers.vary` — str
`fetch.headers.cf-apo-via` — str
`fetch.headers.alt-svc` — str
`fetch.headers.cf-edge-cache` — str
`fetch.headers.permissions-policy` — str
`fetch.headers.referrer-policy` — str
`fetch.headers.x-content-type-options` — str
`fetch.headers.x-frame-options` — str
`fetch.headers.speculation-rules` — str
`fetch.headers.server-timing` — str
`fetch.headers.report-to` — str
`fetch.headers.nel` — str
`fetch.headers.content-encoding` — str
`fetch.text` — str
`fetch.bytes` — int
`fetch.redirect_chain[]` — array
`fetch.error` — NoneType
`viewport_meta` — str
`fixed_width_values[]` — array
`sticky_position_count` — int
`issues[]` — array
  - item keys: severity, finding, fix
`summary.issues` — int

### orphan_pages_from_sitemap.py

Reads `--inventory` (see `site_crawl.py`). **Reachable means linked-to**, not fetched:
the shared crawl seeds from the sitemap, so "we got a status for it" would make every
sitemap URL reachable and this check vacuous.

`site` — str
`truncated` — bool — the crawl behind this stopped at `--max-pages`, so
  `summary.orphan_pages` is over the pages it read
`fetch_error` — NoneType or str
`summary.sitemaps_checked` — int
`summary.sitemap_urls` — int
`summary.reachable_pages` — int
`summary.orphan_pages` — int — read by GO-137
`summary.discovered_not_in_sitemap` — int
`summary.robots_skipped` — int
`summary.sitemap_urls_blocked_by_robots` — int
`sitemaps_checked[]` — array
`orphan_pages[]` — array
`discovered_not_in_sitemap[]` — array
`robots_skipped[]` — array
`sitemap_urls_blocked_by_robots[]` — array
`reachable_pages[]` — array
  - item keys: url, status, final_url, depth, in_sitemap
`issues[]` — array
  - item keys: severity, type, count, message
`errors.sitemap[]` — array
`errors.crawl[]` — array

### pagespeed.py

`url` — str
`strategy` — str
`performance_score` — int
`metrics.LCP.value` — int
`metrics.LCP.unit` — str
`metrics.LCP.label` — str
`metrics.LCP.rating` — str  (good | needs-improvement | poor)
`metrics.LCP.crux_category` — str  (field data only: fast | average | slow)
`metrics.INP.value` — int
`metrics.INP.unit` — str
`metrics.INP.label` — str
`metrics.INP.rating` — str
`metrics.CLS.value` — int
`metrics.CLS.unit` — str
`metrics.CLS.label` — str
`metrics.CLS.rating` — str
`metrics.FCP.value` — int
`metrics.FCP.unit` — str
`metrics.FCP.label` — str
`metrics.FCP.rating` — str
`metrics.TTFB.value` — int
`metrics.TTFB.unit` — str
`metrics.TTFB.label` — str
`metrics.TTFB.rating` — str
`field_cwv.verdict` — str  (field data only: pass | fail | unknown; the key is absent
  when CrUX has no sample. `unknown` means nothing failed but a band was not
  recognised — no `value_map` maps it, so the item reads `NO_DATA` rather than claiming
  a pass over a metric nobody here can grade)
`field_cwv.measured[]` — array  (which of LCP, INP, CLS the verdict is over)
`field_cwv.failing[]` — array
`field_cwv.unknown[]` — array  (present only when a rating fell outside
  good | needs-improvement | poor)
`opportunities[]` — array
  - item keys: title, savings_ms, description
`diagnostics[]` — array
  - item keys: title, score, display
`field_data_available` — bool
`error` — NoneType

### parse_html.py

`title` — str
`meta_description` — str
`meta_robots` — str
`meta_keywords` — NoneType
`x_robots_tag` — NoneType
`canonical` — str
`lang` — str
`charset` — str
`viewport` — str
`favicon` — str
`h1[]` — array
`h2[]` — array
`h3[]` — array
`h4[]` — array
`h5[]` — array
`h6[]` — array
`images[]` — array
  - item keys: src, alt, width, height, is_responsive_fill, loading
`links.internal[]` — array
  - item keys: href, text, rel
`links.external[]` — array
  - item keys: href, text, rel
`pagination.prev` — NoneType or str
`pagination.next` — NoneType or str
`pagination.paginated` — bool
`pagination.issues[]` — array — read by AR-146
  - item keys: severity, type, message
`resource_hints.preload[]` — array
`resource_hints.preconnect[]` — array
`resource_hints.dns-prefetch[]` — array
`resource_hints.prefetch[]` — array
`resource_hints.prerender[]` — array
`schema[]` — array
  - item keys: @type, @types, @id, @context, status, note, has_context, has_type, from_graph, raw
`breadcrumbs` — object — read by AR-158
  - `schema` / `ui` — bool — parseable markup and an explicit UI marker
`issues[]` — array — heading-level skips and missing main/nav/footer landmarks
  - item keys: severity, message, url, evidence
`open_graph.og:locale` — str
`open_graph.og:site_name` — str
`open_graph.og:type` — str
`open_graph.og:title` — str
`open_graph.og:description` — str
`open_graph.og:url` — str
`open_graph.og:image` — str
`open_graph.og:image:secure_url` — str
`open_graph.og:image:width` — str
`open_graph.og:image:height` — str

### redirect_checker.py

`url` — str
`final_url` — str
`chain[]` — array
  - item keys: step, url, status, time_ms, final
`total_hops` — int
`total_time_ms` — int
`has_loop` — bool — CI-014, **absent when `truncated`**: the walk stopped at ten hops
  and whether the rest of the chain loops was never seen. Absent rather than null,
  because a null satisfies `falsy` and would pass the item it must not.
`truncated` — bool
`has_mixed_protocol` — bool
`issues[]` — array
`error` — NoneType

### rich_results_guard.py

`nodes` — int
`rows[]` — array
  - item keys: path, types, issues
`issues[]` — array
`summary.errors` — int
`summary.warnings` — int
`source` — str
`final_url` — str

### robots_checker.py

`url` — str
`status` — int
`user_agents.*.allow[]` — array
`user_agents.*.disallow[]` — array
`sitemaps[]` — array
`ai_crawler_status.GPTBot` — str
`ai_crawler_status.OAI-SearchBot` — str
`ai_crawler_status.ChatGPT-User` — str
`ai_crawler_status.OAI-AdsBot` — str
`ai_crawler_status.ClaudeBot` — str
`ai_crawler_status.PerplexityBot` — str
`ai_crawler_status.Google-Extended` — str
`ai_crawler_status.Applebot-Extended` — str
`ai_crawler_status.Bytespider` — str
`ai_crawler_status.CCBot` — str
`ai_crawler_status.anthropic-ai` — str
`ai_crawler_status.FacebookBot` — str
`ai_crawler_status.Amazonbot` — str
`issues[]` — array
`error` — NoneType

### robots_path_tester.py

Takes positional paths after the URL or discovers the audited page's own same-origin
stylesheets, scripts and images with `--discover-assets`. The registry uses it twice,
and the two uses need different evidence. CI-013 discovers assets and passes
`--agent Googlebot`; same-origin means an exact scheme, hostname and effective-port
match after resolving the reference against the final page URL, so a third-party CDN
is governed by its own robots.txt. CI-019 passes `/search /cart /checkout /login`
**and `--probe`**, because "robots.txt does not
disallow it" and "it is an indexable page" are different claims and only the second one
is an accusation.

`site` — str
`robots_url` — str
`robots_status` — int
`allowed_urls[]` — array of str — every tested URL at least one agent may fetch.
  **Absent** when `robots_status` is neither 200 nor 404: a 500 or a timeout says
  nothing about what is allowed, and an empty list would read as "nothing is
  exposed". It is also absent when there are no paths to test. Added because the previous
  assertion matched `allowed.*true` as text, and `allowed` and `true` never land in
  the same string of a nested dict — so it matched nothing and passed every site.
  CI-019 asserted it was empty until 0.20 and no longer does: this field is computed
  from robots.txt alone, so a site with no cart was accused of exposing `/cart`.
`blocked_urls[]` — array of str — **what CI-013 asserts is empty.** Same-origin page
  assets Googlebot cannot fetch. Absent when asset discovery finds no blockable
  reference or robots.txt cannot be read, so either empty input or an unavailable
  policy produces NO_DATA rather than a critical PASS.
`discovered_assets[]` — array of str — normalized same-origin paths found by
  `--discover-assets`, including query strings because robots rules can match them.

Under `--probe` only, and absent without it:

`indexable_urls[]` — array of str — **what CI-019 asserts is empty.** Tested URLs that
  are permitted by robots.txt, answered 2xx/3xx, and carry no `noindex` in a
  `<meta name="robots">` or an `X-Robots-Tag`. A 404 or 410 is not an indexable page
  and does not appear. Comments are stripped before the meta tag is looked for —
  markup inside a comment is not markup.
`unprobed_urls[]` — array of str — permitted URLs whose fetch failed or answered 5xx.
  Deliberately neither list: an unreachable page is not proven absent and not proven
  indexable, so a network failure cannot read as a clean site.
`rows[].probe` — object, present only for permitted paths (a disallowed path is out of
  the index already and fetching it would spend a request to learn nothing)
  - `probed` — bool (always true when the key exists)
  - `status` — int or null
  - `exists` — bool or null (null when the probe could not tell)
  - `noindex` — bool or null
  - `error` — str or null
`rows[]` — array, one per path
  - item keys: url, decisions, allowed_for
  - `decisions.<agent>.allowed` — bool
  - `decisions.<agent>.rule` — str (`"no matching rule"` when nothing matched)
  - `allowed_for[]` — the agents allowed to fetch this URL
  - agents: Googlebot, Bingbot, GPTBot, OAI-SearchBot, ChatGPT-User, OAI-AdsBot, …

**No `issues[]` and no `summary`** — unlike almost every other script. Rules have
to walk `rows[].decisions` directly; there is no aggregate to assert against.

### schema_required_props.py

`schema_nodes` — int
`checked_type` — NoneType
`rows[]` — array
  - item keys: path, types, missing_required, missing_recommended, placeholder_properties
`issues[]` — array
  - item keys: severity, message, url, evidence
`summary.errors` — int
`summary.warnings` — int
`source` — str
`final_url` — str

### security_headers.py

`url` — str
`score` — int
`https` — bool
`headers_present.HSTS (Strict-Transport-Security)` — str
`headers_present.X-Frame-Options` — str
`headers_present.X-Content-Type-Options` — str
`headers_present.Referrer-Policy` — str
`headers_present.Permissions-Policy` — str
`headers_missing.Content-Security-Policy (CSP)` — str
`header_values.strict-transport-security` — str — empty when absent
`header_values.x-frame-options` — str — empty when absent
`header_values.x-content-type-options` — str — empty when absent
`header_values.referrer-policy` — str — empty when absent
`header_values.permissions-policy` — str — empty when absent
`issues[]` — array
`recommendations[]` — array
`error` — NoneType

### server_log_audit.py

The only script here that reports what crawlers **did** rather than what the site
offers them, and the only one whose evidence no run could ever collect for itself:
the fact is in the past. The operator supplies the log (`--server-log`), this reads
it, CI-018 decides. Same artifact pattern as `cwv_metrics.py`.

`log_file` / `base_url` — str
`format` — str — `combined` / `common` / `json` / `unknown`
`lines_read` / `lines_parsed` / `lines_unparsed` — int
`truncated` — bool (`--max-lines` reached)
`user_agent_recorded` — NoneType or bool
`error` — NoneType or str — **set, and everything else left empty, when the log
  cannot answer**: no such file, nothing parsed, or Common Log Format, which records
  no User-Agent. "No crawler visited" and "this file cannot say" are opposite
  findings and the second is never printed as the first
`bot_identity` — str — a fixed sentence saying the User-Agent is a claim, not proof
`window.first` / `.last` — NoneType or str (ISO 8601)
`window.days` — NoneType or int (rounded up, so a partial day is 1 and never 0)
`by_status_class` — object — counts over every request, bots and humans
`search` / `ai` — object — the same counts for search and AI crawlers only
  - class keys: `served`, `not_modified`, `redirect_permanent`, `redirect_temporary`,
    `rate_limited`, `gone`, `client_error`, `server_error`. **`not_modified` is not
    waste** — a 304 is the cheapest exchange there is
`bots.<label>` — object — `kind` (`search`/`ai`/`other`), `requests`, `distinct_ips`,
  `by_status_class`
`top_crawled[]` / `top_wasted[]` / `parameters[]` — array (≤20)
`never_crawled` — NoneType or array — **NoneType when the window is under 7 days**,
  because below that "never crawled" and "not crawled yet" are the same thing. An
  empty array would read as "we looked and there were none"
`crawled_not_offered` — NoneType or array — same gate
`robots_disallowed_hits[]` — array — paths robots.txt refuses that crawlers still asked
  for; needs `--inventory`
`summary.search_bot_requests` / `.ai_bot_requests` / `.search_bot_urls` — int
`summary.wasted_requests` / `.redirect_requests` / `.not_modified_requests` /
  `.server_error_requests` — int
`summary.rates_meaningful` — bool — false under 50 search-bot requests, and the
  percentages below are then **absent** rather than computed from nothing
`summary.wasted_pct` / `.redirect_pct` / `.server_error_pct` — float, only when
  `rates_meaningful`
`summary.days` / `.search_requests_per_day` — int / float
`summary.never_crawled_count` / `.crawled_not_offered_count` — int, only with an
  inventory and a long enough window
`issues[]` — `severity` (`high`/`medium`/`low`) + `type` + `message`

Every threshold behind those severities is a constant at the top of the script with
its justification beside it, and each says plainly that it is a convention rather
than a measurement — see §2 of KNOWN-ISSUES.md.

### site_crawl.py

Not a registry item's script — the runner runs it once before it builds the plan and
hands the file to the site-wide checks. Written down here because those checks'
output contracts derive from it, so a change here moves them at once.

`inventory_version` — int (a reader refuses a version it does not know)
`site` / `entry` — str
`crawled_at` — str (ISO 8601, UTC)
`depth` / `max_pages` — int
`signatures` — bool
`fetch_error` — NoneType or str — copied through by every reader
`summary.requests` — int — what the crawl cost, which is the point of it existing
`summary.pages_fetched` / `.pages_html` / `.pages_broken` / `.pages_redirected` — int
`summary.robots_blocked` — int
`summary.internal_links` / `.external_links` — int (every `<a>`, not distinct targets)
`summary.unique_internal_targets` / `.unique_external_targets` — int
`summary.unchecked_internal_targets` — int (beyond depth or budget: counted neither way)
`summary.sitemaps_checked` / `.sitemap_urls` / `.sitemap_urls_off_host` — int
`summary.reachable_pages` — int (linked-to, not fetched)
`summary.truncated` — bool
`pages.<key>` — object, one per deduplicated page; the key is the page key and
  `url` is the first discovered spelling that was fetched
  - `url`, `final_url`, `status`, `content_type`, `redirect_chain[]`, `redirected`,
    `bytes`, `error`, `error_kind`, `robots_blocked`, `html`, `depth`, `discovered_by`
    (`entry`/`sitemap`/`link`), `in_sitemap`
  - `title`, `meta_description`, `meta_robots`, `canonical`, `noindex`
    (meta **and** `X-Robots-Tag`)
  - `content_words`, `text_hash`, `signature[]` (MinHash, 100 values)
  - `internal_out`, `unique_internal_out`, `external_out`
  - `schema_nodes[]` — one object per parseable JSON-LD node; item key: `types[]`
  - `links[]` — item keys: target, anchor, rel, nofollow, internal
  - `images[]` — array
`reachable[]` — array of page keys
`unchecked_internal_targets[]` — array
`robots_blocked.<key>` — str
`sitemap.urls[]` / `.off_host[]` / `.sitemaps_checked[]` / `.errors[]` — a fetch
error item retains `error_kind` beside `error`
`broken[]` — array — item keys: url, status, error, error_kind, linked_from
`redirected[]` — array — item keys: url, to, hops, linked_from
`external_targets.<url>[]` — array — item keys: source, anchor, nofollow

A page key is `scheme://host/path`: query dropped, trailing slash kept only on the
root. `--out PATH` writes the inventory to a file and prints the summary instead.

### sitemap_checker.py

`site` — str
`sitemaps_checked[]` — array
  - item keys: url, status, final_url, redirects, type, url_count, sitemap_count, error, error_kind
`urls[]` — array
  - item keys: url, lastmod, changefreq, priority, checks (status, final_url, redirects,
    error and error_kind when `--fetch-urls` requests the URL)
`summary.sitemaps` — int
`summary.urls` — int
`summary.indexes` — int
`summary.issues` — int
`issues[]` — array
  - item keys: severity, message, url, evidence

### social_meta.py

`url` — str
`score` — int
`og_tags.og:locale` — str
`og_tags.og:site_name` — str
`og_tags.og:type` — str
`og_tags.og:title` — str
`og_tags.og:description` — str
`og_tags.og:url` — str
`og_tags.og:image` — str
`og_tags.og:image:secure_url` — str
`og_tags.og:image:width` — str
`og_tags.og:image:height` — str
`twitter_tags.twitter:card` — str
`twitter_tags.twitter:title` — str
`twitter_tags.twitter:description` — str
`twitter_tags.twitter:image` — str
`og_present[]` — array
`og_missing[]` — array
`twitter_present[]` — array
`twitter_missing[]` — array
`issues[]` — array
`recommendations[]` — array
`preview.title` — str
`preview.description` — str
`preview.image` — str
`preview.site_name` — str
`error` — NoneType

### third_party_script_audit.py

`url` — str
`script_count` — int
`third_party_count` — int
`blocking_third_party_count` — int
`third_party_bytes` — NoneType
`issues[]` — array
  - item keys: severity, message, url
`scripts[]` — array
  - item keys: src, inline, async, defer, type, third_party, known_tag, content_length, status, blocking
`truncated` — bool — the sitemap index walk stopped at `MAX_SITEMAPS_FOLLOWED`
  with files still queued, so `issues` is over the files that were read
`fetch_error` — NoneType

### topical_cluster_mapper.py

`page_count` — int
`cluster_count` — int
`score` — int
`clusters.seo.page_count` — int
`clusters.seo.hub` — str
`clusters.seo.topics[]` — array
`clusters.seo.internal_edges[]` — array
`clusters.seo.missing_links[]` — array
`clusters.seo.orphan_candidates[]` — array
`issues[]` — array

### tls_certificate.py

SE-118 reads `valid`, and the point of that field is that a handshake set it —
`CERT_REQUIRED` and `check_hostname` against the system trust store — not a look at
the scheme. Three shapes, and the difference between them is the whole contract:

- **verified** — `valid: true`, plus the certificate's own fields below.
- **rejected** — `valid: false` and `verify_error`, with a `critical` issue carrying
  the library's reason. Expired, self-signed, wrong host, untrusted chain.
- **nothing to look at** — `valid` **absent**, so the assertion lands on `NO_DATA`
  and not `FAIL`. Either `error` (the connection never reached a certificate) or
  `reason` (the URL is `http://`, so no certificate is served on this scheme). "We
  could not look" and "we looked and it is invalid" are different claims, and only
  the second one is an accusation.

`url` / `host` — str
`port` — int
`https` — bool
`valid` — bool — **absent** when no certificate was seen; see above
`tls_version` — str — e.g. `TLSv1.3`
`subject.commonName` — str
`issuer.countryName` / `issuer.organizationName` / `issuer.commonName` — str
`san[]` — array of str — DNS names on the certificate
`not_before` / `not_after` — str — OpenSSL format, e.g. `Nov  1 02:12:37 2026 GMT`
`days_until_expiry` — int — a `high` issue under 30 days
`verify_error` — str — only when `valid` is false
`error` — str — only when the handshake never completed
`reason` — str — only when the URL is `http://`
`issues[]` — array

### url_quality.py

`count` — int
`rows[]` — array
  - item keys: url, path, param_count, params, flags, score

### video_schema_checker.py

`videos` — int
`rows[]` — array
`issues[]` — array
`source` — str
`final_url` — str
