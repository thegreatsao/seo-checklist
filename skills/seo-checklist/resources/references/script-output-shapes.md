<!-- Updated: 2026-09-06 -->
# Script output shapes

<!-- derived: tools/audit_catalogue.py -->
This catalogue documents 59 checkers: the 57 the registry runs, plus 2 it does not name — `detect_profile.py`, `site_crawl.py` — which the runner runs itself before building the plan and whose output the rest of the audit reads.

Only 16 of them are documented as carrying an `issues[]` whose elements have both `severity` and `message` — the convention a rule can rely on. **Check the section before writing a rule.** The other ways this file describes an `issues[]`, counting a script once per way, come to 50 entries:

* **15 emit no root `issues[]`**: `ai_crawler_policy_matrix.py`, `article_seo.py`, `cwv_metrics.py`, `detect_profile.py`, `duplicate_content.py`, `hreflang_checker.py`, `indexability_matrix.py`, `javascript_render_audit.py`, `lcp_subparts.py`, `llms_txt_checker.py`, `pagespeed.py`, `rendered_audit.py`, `robots_path_tester.py`, `site_crawl.py`, `url_quality.py`. A `none_severity` or `len_eq: 0` rule over one of these reads a key that is never there, which is `NO_DATA` forever.
* **22 record an `issues[]` and never say what is in one**: `broken_links.py`, `cache_compression_checker.py`, `canonical_checker.py`, `css_minify_check.py`, `domain_safety_check.py`, `faceted_nav_audit.py`, `font_audit.py`, `ga4_tag_checker.py`, `gsc_cannibalization.py`, `gsc_links_csv.py`, `gsc_url_inspection.py`, `html_validator.py`, `internal_links.py`, `redirect_checker.py`, `rich_results_guard.py`, `robots_checker.py`, `security_headers.py`, `server_log_audit.py`, `social_meta.py`, `tls_certificate.py`, `topical_cluster_mapper.py`, `video_schema_checker.py`. That is a gap in this file rather than a fact about the script — the probe saw the key and captured no element — and a rule naming a field inside one of these is a guess.
* **6 carry the human text under another key**: `entity_checker.py` (`finding`), `gsc_checker.py` (`finding`), `gsc_sitemap_reconcile.py` (`finding`), `indexnow_checker.py` (`finding`), `link_profile.py` (`finding`), `mobile_render_checker.py` (`finding`). `none_matching` with `field: message` matches nothing on these.
* **7 can put a capitalised severity in a dict**: `article_seo.py`, `duplicate_content.py`, `entity_checker.py`, `gsc_checker.py`, `hreflang_checker.py`, `indexnow_checker.py`, `link_profile.py`. `none_severity` compares lowercase, and `SEVERITY_ALIAS` in `tools/audit_assertions.py` is what keeps that from silently clearing a rule.
<!-- /derived -->

Machine-probed JSON structure of the evidence scripts, captured by running each one
with `--json` against a live URL (https://www.plerdy.com/seo-checklist/, WordPress).
Four keys added in 0.93.0 — `srcset_without_sizes_count`, `large_image_count`,
`invalid_url_count` and `incomplete_nodes_by_type` — were read from a run against the
fixture corpus instead, because the machine that added them cannot reach that URL. The
key names and types are the run's; the notes beside them are not.
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

**A read that failed, at the top of a result (0.173.0):** a script that reports a
`fetch_error` names the fetch layer's kind beside it as `fetch_error_kind`, and one that
reports a top-level `error` names the runner's kind as `error_kind`. The runner records a
`fetch_error` as `unread` unless `fetch_error_kind` is `blocked` — this audit's own guard
refused the request (HTTP-13) — and then as `blocked`. `site_crawl.py` carries the same
`fetch_error_kind` and counts `summary.refused_pages`, a page the guard refused, which makes
the crawl `truncated`; the scripts reading its inventory copy the kind through.

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
| `gsc_sitemap_reconcile.py` | up to 120s — URL Inspection for a bounded sitemap sample, plus one Search Analytics query |
| `pagespeed.py` | ~19s — external PageSpeed API |
| `anchor_text_audit.py` | fast with `--inventory` |
| `indexability_matrix.py`, `sitemap_checker.py`, `broken_links.py` | ~6-8s; the link check also requests bounded external targets from the crawl |
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
`wcag_a_failures` — int — TE-180 (0.117.0): the level-A failures the HTML shows, the
  sum of the three keys below, each counted over its whole list
`wcag_a.images_missing_alt` — int
`wcag_a.unnamed_fields` — int — form fields with no accessible name: `aria-labelledby`
  resolved to the text it names, a blank attribute or label no name; image inputs named
  by `alt`, button inputs by `value` (submit and reset have a default caption); hidden
  inputs, and fields under `aria-hidden="true"`, `hidden` or an inline `display:none` /
  `visibility:hidden`, not counted (F15 batch 6)
`wcag_a.missing_lang` — bool
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
`issues[]` — array
  - item keys: severity, message
`fetch_error` — NoneType

### ai_crawler_policy_matrix.py

`site` — str
`robots_url` — str
`robots_status` — int
`llms_txt_url` — str
`llms_txt_status` — int
`fetch_error` — NoneType or str
`named_scopes.model_training[]` — array of str
`named_scopes.answer_feeding[]` — array of str
`named_scopes.ad_landing_page_review[]` — array of str
`policy_grade` — str  (`explicit` | `partial` | `silent`)
`rows[]` — array
  - item keys: crawler, scope, honours_robots_txt, named, policy, paths,
    llms_txt_available, alignment
  - `honours_robots_txt` is false for a documented user fetcher that generally ignores
    robots.txt; its `policy` is `not_enforced`, while `paths` retains the site's stated
    rules instead of presenting them as restrictions the fetcher will obey.

### anchor_text_audit.py

Reads `--inventory` (see `site_crawl.py`); crawls one for itself without it.

`truncated` — bool — the crawl behind this stopped at its page or depth cap, so every
  count here is over the pages it read
`truncated_reason` — str — present when `truncated` is true: why the overuse count is
  withheld (0.171.0)
`fetch_error` — NoneType or str (the crawl's reason, copied through)
`start_url` — str
`pages_crawled` — int
`links_analyzed` — int — absent when `truncated` is true and no link was read
`summary.unique_targets` — int
`summary.empty_anchors` — int
`summary.generic_anchors` — int
`summary.nofollow_internal_links` — int
`summary.navigation_links` — int (pairs carried by most pages: site chrome)
`summary.editorial_links` — int (the rest, which is what the repetition checks read)
`summary.overused_exact_match_targets` — int — absent when `truncated` is true,
  because overuse is a share that reading more pages can lower
`summary.low_diversity_targets` — int
`summary.unnatural_anchor_targets` — int — read by BL-081 (F15): distinct targets with
  exact-match overuse, low diversity (over a crawl of four pages or more; a pager's
  links and alt-named links left out, and an anchor that is the target's own title not
  counted against variety), or an empty or generic anchor; a redirect row read again is not
  read (`site_crawl.read_twice`); when `truncated`,
  only the empty or generic ones, a floor, and absent if there are none. An image
  link's anchor is its alt (`site_crawl.py`)
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
`answer_blocks` — int — direct answers (after a heading, `<summary>`, `<dt>` or FAQ-question
  element asking something) plus definitions, neither in the page's furniture (a `<nav>`, a
  page-level `<aside>`, `<header>` or `<footer>`): what GO-144 and GEO-004 assert (F15 batch 5).
  A definition opens its paragraph with its term; lists inside `<nav>`, `role=navigation`,
  `<header>` or `<footer>`, and lists of links only, are not counted in `lists`
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
`paragraphs[]` — array — every non-empty `<p>` in the body containers (until 0.174.0,
  only those of more than eight words; KW-076's body text is these and the headings)
`body_copy` — str — not printed; the text `keyword_usage.in_body` reads since F15 batch 5: the
  containers' text with headings, `<nav>`, `<aside>`, and a `<header>`/`<footer>` that is not an
  `<article>`'s, `<main>`'s or `<section>`'s own, taken out
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

With `--inventory` the scope is the whole site's internal and external links. Internal
status is read out of the shared crawl; distinct external targets are requested here.
Without one it fetches a single page and checks every link on it.

`page_url` — str (the site with `--inventory`, the page without)
`scope` — str: `site` (inventory) — absent on the single-page path
`total_links` — int
`checked` — int
`truncated` — bool — the answer rests on less than the whole input: the
  `--max-links` cap bit, or a link answered nothing (`summary.unchecked`,
  `summary.timeout`, `summary.external_unchecked`) and so was neither cleared nor
  found broken; in inventory mode the external cap also sets it
`truncated_reason` — str — present when inventory input or external checking was
  incomplete
`broken[]` — array
  - item keys: url, anchor_text, is_internal, status, error, error_kind, redirect, response_time_ms, linked_from
`redirected[]` — array
`timeout[]` — array
`unchecked[]` — array (targets the crawl did not reach or policy/robots declined;
counted in neither direction)
`external[]` — array, first 50 requested external targets (counts cover all)
  - item keys: url, linked_from, status, final_url, error, error_kind, redirected, broken, unchecked
`healthy` — int
`summary.total` — int
`summary.healthy` — int
`summary.broken` — int — internal plus external broken targets
`summary.redirected` — int
`summary.broken_or_redirected` — int — internal broken + internal redirected +
  external broken; read by TE-168 for its clean PASS band
`summary.timeout` — int
`summary.unchecked` — int
`summary.external_checked` — int
`summary.external_broken` — int
`summary.external_unchecked` — int
`summary.external_redirected` — int — evidence only, not counted by TE-168
`summary.external_links` — int — distinct external targets found
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

With `--inventory` the scope is every crawled HTML page that answered 200. Canonical
targets already present in the crawl are not fetched again; distinct targets outside
the crawl are fetched up to `MAX_TARGET_FETCHES` (100).

Inventory mode adds `scope` (`site`), `truncated`, and, when truncated,
`truncated_reason`. Its `rows[]` use the keys below plus `canonical_status` on
non-self canonicals. `duplicate_canonical_targets` maps targets named by more than
one source page. `truncated_reason` names the number of distinct canonical targets
that could not be checked when there are any.

`count` — int
`rows[]` — array
  - item keys: url, status, final_url, canonical, verdict, signal, issues (`canonicals`
    on a conflict; `canonical_status` once a target is fetched; `variants[]` — url,
    status, final_url, consolidated — under `--variants`)
  - `verdict`: self_canonical, canonicalized, cross_host, missing, conflicting, unknown;
    with `--check-targets` also target_unavailable (the target is not 200) and
    target_unchecked (nothing answered, or a 429/503); with `--variants`
    variant_unchecked (a variant answered 429/503) and variant_unconsolidated (a
    variant serves the same page — its text, or its title when neither has text — without redirecting to,
    declaring or noindexing it; one declaring another canonical is another page) (F15)
  - `signal` (CI-011): consistent, conflicting, noindex_canonicalized,
    canonical_to_noindex, target_unchecked; a cross-host canonical alone is consistent
    (F15)
  - `cross_host` is a canonical on another host, checked like `canonicalized` (its
    target fetched, its variants requested) and no issue on its own; CI-009 maps it to
    pass (F15, the owner's ruling on batch 3's question 1)
`issues[]` — array — no entry for a cross-host canonical alone (TE-176, F15)
`fetch_error` — NoneType or str (no URL answered; CI-009 is `critical`)

### citation_readiness.py

`url` — str
`score` — int
`sourced_score` — int — `score` on a page naming at least one source, 0 on one naming none:
  what GO-145 and GEO-005 assert (F15 batch 5)
`utility_page` — bool — every word of the page's slug (the segment before an `index`
  page) is a privacy, terms or contact word (`UTILITY_WORDS`, a `UTILITY_PHRASES` phrase
  read as one), a filler word (`UTILITY_SLUG_WORDS`) or a number, and one is a utility
  word, and the slug is the first path segment or sits directly under `/pages/`; or,
  whatever the slug, the page sits directly under `/policies/` or anywhere under
  `/legal/` (each read after a leading language segment; the owner's ruling 4 on
  batch 7, widened by the owner's rulings of 2026-11-12 and 2026-11-15): GO-145's and
  GEO-005's `applies_when`, N/A when true (F15 batch 6, the owner's ruling 1 on batch 5)
`citation_capacity` — int — trusted links, cite/blockquote tags, footnote links, schema
  citations, and outbound links in a block that makes a claim or says "Source", or under a
  content heading that is exactly Sources, References, Further reading, Bibliography,
  Citations or Works cited, counted together, each outside the page's furniture (a `<nav>`, a page-level
  `<aside>`, `<header>` or `<footer>`); `citation_signals` still counts every one of them
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
`category_page` — bool — the page links products: AR-154's subject (F15 batch 5). A product
  link names a segment after `/product/`, `/products/` or `/p/`, so a link to the listing
  itself is none
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
`third_party_sheets[]` — array of str — sheets on another registrable domain than the
  page's (where it landed; hrefs resolve against it), listed and not read — a platform's
  CDN domain (Webflow's `website-files.com`) too (F15 batch 7, the owner's ruling)
`checked` — int — the site's own sheets read; 0 makes TE-174 N/A
`unminified_count` — int
`truncated` — bool — the page links or `@import`s, of its own, (from a `<style>` block) more than
  `MAX_SHEETS` stylesheets, so `unminified_count` counts only the first twelve; or a sheet
  could not be read (an error, a 4xx/5xx, a guard refusal), with `truncated_reason`
`fetch_error` — str | null — also when the page answers 4xx/5xx, or no sheet could be read
`wasted_bytes` — int
`issues[]` — array

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
`uptime.error_kind` — str — `blocked` when this audit's guard refused the request; `reachable`
  is then absent, not false
`withheld` — object — `{"uptime.reachable": "blocked"}` when that request was refused, so
  the runner records TE-167's NO_DATA with the guard's kind (F04, HTTP-13); absent otherwise
`safe_browsing.checked` — bool
`safe_browsing.error` — str
`safe_browsing.threats[]` — array of `{type, platform, url}` — absent unless every request
  was answered or one found a threat; `url` is the listed URL (F15 batch 6)
`safe_browsing.urls_asked` — int — with `--inventory`, the entry and every URL the crawl
  read, asked 500 to a request (SE-114, SE-116, TE-171)
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

Every HTML page that answered 200 is read, with body text of its own or none (F15:
pages without text were dropped, and with them the untitled, shared-description and
0-word pages MS-026, MS-029 and CN-039 are about); a page with no text has no hash or
signature and is nobody's duplicate.

`missing_titles[]` is the sorted list of page keys with an empty or whitespace-only
title, including noindex pages. Unlike title duplication, absence is not competition.

`summary.missing_title_pages` — int — the length of `missing_titles`, and what MS-026
  asserts is zero

`truncated` — bool — the crawl behind this stopped at `--max-pages`, so every
  count here is over the pages it read
`fetch_error` — NoneType or str
`pages_analyzed` — int
`exact_duplicates[]` — array — `Critical` groups of indexable canonical pages; an
  `Info` group when a member is noindex or canonicalised (`noindex_urls`,
  `canonicalized_urls`), not counted (F15)
  - item keys: type, severity, urls, finding, fix
`near_duplicates[]` — array — `Warning` for two indexable canonical pages, `Info`
  (`handled_in_pair`) when one is noindex or canonicalised
  - item keys: type, severity, similarity, url_a, url_b, word_count_a, word_count_b, noindex_in_pair, handled_in_pair, finding, fix
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
`summary.exact_duplicate_groups` — int — the `Critical` groups; CN-041's warn band
`summary.duplicate_content_findings` — int — **what CN-041 asserts is zero** (F15):
  exact groups plus `Warning` near-duplicate pairs; absent when the crawl took no
  signatures and no exact group decides it
`summary.duplicate_title_groups` — int — **what MS-022 asserts is zero.** The item
  read `exact_duplicates` until 0.43, which counts duplicate page *content* —
  CN-041's verdict — and did not measure titles at all.
`summary.near_duplicate_pairs` — int — the `Warning` pairs
`summary.thin_pages` — int — a page with no words of its own counts
`summary.duplicate_description_groups` — int — **what MS-029 asserts is zero.** That
  item read `exact_duplicate_groups` until 0.22, which counts duplicate page *content*
  — CN-041's verdict — so a site running one description across forty distinct pages
  passed it.
`summary.title_group_exclusions.noindex` — int — pages excluded from title and
  description grouping because they are not indexable
`summary.title_group_exclusions.canonicalized` — int — pages excluded from title and
  description grouping because their canonical names a URL other than the one the page
  was read at or landed on (`comparable_url`; a trailing-slash self-canonical is self,
  F15). A numbered page (`?page=2`) is its own page key, so a series sharing one title
  is a duplicate-title group (MS-022, F15).
`summary.avg_word_count` — int

### eeat_signal_checker.py

`url` — str
`score` — int
`authored_score` — int — `score` on a page naming an author, 0 on one naming none: what
  CN-068 asserts (F15 batch 5)
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
`signals.authors_shown[]`, `signals.publishers_shown[]` — array — the names the page's visible
  text carries; since F15 batch 5 `signals.authorship` is true for a half only when one is shown
`signals.credential_markers[]` — array
`signals.first_hand_experience_markers[]` — array
`signals.policy_links[]` — array
  - locale-aware editorial standards only: fact-checking, corrections, ethics. Not privacy.
`signals.privacy_links[]` — array
  - locale-aware privacy, data protection, GDPR, cookie-policy terms and URL fragments.
    CN-040 reads this; it used to read `policy_links`, which answered a different
    question in both directions.
`signals.trust_links[]` — array
`signals.contact_links[]` — array — CN-044 (0.116.0): links named or addressed as
  contact in the page's languages, plus tel: and mailto: links. Not About, Privacy or
  Terms, which `trust_links` keeps for CN-068
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
`summary.entity_resolution` — str — `resolved` (a Wikidata or Wikipedia `sameAs`, a Wikidata
  item labelled with the entity's name, or a Knowledge Graph match), `unresolved` (Wikidata
  gave no item labelled with a name the page declares), `unnamed` (the name was only cut from the
  `<title>`), `not_asked` (Wikidata could not be asked); the last two unmapped, NO_DATA:
  GEO-006's value map (F15 batch 5).
  A Knowledge Graph hit counts only under the entity's own name
`summary.wikidata_found` — bool | null — null when Wikidata could not be asked (0.124.0)
`summary.wikipedia_found` — bool | null — null when Wikipedia could not be asked
`summary.google_kg_checked` — bool
`summary.google_kg_found` — bool
`summary.total_issues` — int

### faceted_nav_audit.py

`count` — int — every internal URL this page led to, which is what `rows` describes.
  **Not the subject of AR-163**: a page with no faceted navigation still produces rows,
  and this read 1 on a plain page with no parameters anywhere
`faceted_count` — int — rows carrying a filter, sort or facet parameter. AR-163
  declares applicability against this, so an item about controlling faceted navigation
  reports `N/A` on a site that has none instead of passing. Added at 0.96.0 and read
  from a fixture run rather than from the live probe, on the same terms as the four
  keys named at the top of this file
`rows[]` — array
  - item keys: url, path, params, facet_params, flags; with `--fetch` also status,
    refused, canonical, meta_robots, redirected, canonical_elsewhere, noindex
  - a URL that redirects away (`redirected`) — not to another spelling of itself, nor to
    a URL keeping its facet parameters (else, for a non-facet variant, all its
    parameters) — or whose canonical names a URL other than both the one asked for and
    where it landed, is controlled (F15 review rounds 3-6)
  - `facet_missing_canonical` is a facet whose canonical does not name another URL: a
    self-canonical is no control (AR-163, F15); `noindex` is Google's reading
    (`seo_common.google_noindex`: metas, header, `none`)
`path_explosions` — object — paths with `PATH_EXPLOSION_VARIANTS` or more variants none
  of which is controlled (canonicalised elsewhere, noindex, or disallowed) (F15)
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
`favicon.format` — str or NoneType  (png | ico | gif | jpeg | webp | bmp | pbm | pgm | ppm | tiff | svg)
`favicon.width` — int or NoneType
`favicon.height` — int or NoneType
`favicon.min_side_px` — int or NoneType  (raster images only)
`favicon.square` — bool or NoneType  (NoneType when dimensions are unknown)
`favicon.google_format` — bool or NoneType  (NoneType when the format is unknown)
`favicon.grade` — str  (`recommended` | `required_only` | `fails`; absent when
  nothing was measured, except that a missing, blocked or unreachable declaration fails)
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
`font_faces[]` — array — every face; an icon font's (`ICON_FONT_FAMILIES`, F15 batch 7)
  and a `local()`-only or `data:`-only one's (`local_only`, F15 batch 7) `font_display` raise
  no finding
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
`date_signals.shown.published` — bool — since F15 batch 5, a date a visitor sees in the page's
  own content (not its furniture — a page-level header unless it holds every `<h1>` on the page — nor a
  comments section): a `<time>` with text of its own, or a
  date written in the visible text (ISO,
  month or day first in English, German, French, Spanish or Russian, or numeric)
`date_signals.shown.updated` — bool — a shown date later than the publication shown: the
  earliest `<time>` or a date written right after "Published", "Posted" or "Effective" (with
  "Date"/"On" and a colon, and the German, French, Spanish and Russian words) at the start of a
  block of the page's own content, or with neither the earliest written date
`date_signals.sources.published` / `.updated` — str | null — `time` or `text`, naming where
  each shown date was read
`date_signals.declared.published` / `.updated` — str | null — what is declared without being
  shown, read for the score and the age and never for CN-056: published from `meta`,
  `schema` or `time`, updated from `meta` or `schema`
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
`installed_by[]` — array of str — GA4 IDs configured or loaded, Google tag (`G-`, `GT-`)
  IDs a `gtag/js` loader names, GTM containers the page loads, and the `G-` IDs of
  Shopify's Google channel pixel (`google_tag_ids`; its `GT-` tags are Merchant Center's): GO-131's subject (F15 batch 6)
`duplicates[]` — array — the same ID configured or loaded more than once, a container
  whose script is loaded twice (a `gtm.js?id=` URL or GTM's snippet; a mention elsewhere is
  not a load), or a hardcoded ID that a GTM container beside it names in its
  Google tag or GA4 configuration tag, a Constant variable followed (`kind:
  gtm_and_hardcoded`, the container's script read; an event tag is not one). IDs are read
  with HTML comments removed; duplicates are counted with JSON data-block scripts and
  Next.js flight payloads removed too, while `installed_by` reads them (a `next/script`
  tag is served only there). **Absent** when such a
  container could not be read and nothing else is duplicated, so GO-132 is NO_DATA
`duplicates_unread` — str — why, when `duplicates` is absent
`withheld` — object — `{"duplicates": "blocked"}` when the guard refused the container
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
  so there may be query/page rows this analysis never saw. Upstream of every
  count in `summary`, unlike `queries_truncated`, which is downstream of them
`cannibalized[]` — array, capped at 25 for human-facing output; the cap is on
  the listing only — `summary.cannibalized_queries` counts them all
  - item keys: query, pages[] (page, clicks, impressions, position), page_count,
    clicks, impressions, spread (float — max minus min position),
    positions_compared
`branded_spread[]` / `contested[]` — arrays with the same item shape and
human-facing 25-entry cap
`spread_brand.source` — str (`operator`, `published`, or `none`) — what
  `branded_spread` was classified by; with `none` no query is set aside as branded (F15
  batch 7: the highest-click query is no longer inferred as the brand)
`spread_brand.names[]` — array of str
`branded.checked` — bool
`branded.brand_names[]` — array of str — `--brand` values, or the names the
  homepage publishes (`WebSite`/organisation `name` and `alternateName`,
  `og:site_name`)
`branded.brand_source` — str (`operator` or `published`)
`branded.branded_queries` — int — distinct queries carrying a brand name
`branded.searched` — bool — at least one did, in the window
`branded.host` — str
`branded.query` / `branded.owner_page` — str — the branded query with the most
  impressions, and the page (locale alternates grouped) serving it most
`branded.position` — float
`branded.clicks` / `branded.impressions` — int
`branded.owns_homepage` — bool — the root, or a locale alternate of it
`branded.ranks_first` — bool
`branded.homepage_ranks_first` — bool — both of the above
`summary.cannibalized_queries` — int
`summary.contested_queries` — int — absent over a full page of rows (`truncated`, 0.174.0):
  a page past the cap can end a contest, so the count is not a floor; `truncated_reason`
  says why. `summary.cannibalized_queries` stays: a row past the cap only adds a page to
  a split, and since F15 batch 7 no brand is inferred from the rows, so it is a floor
`issues[]` — array
`error` — str | null

With no brand name — none supplied, none published, or the homepage unreadable —
or no query data in the range, `branded` collapses to
`{checked: false, reason: "..."}` and the sub-fields are absent — so rules on
`branded.*` yield `NO_DATA`, with the reason, not a verdict. When a name is known
but no query in the window carries it, `searched` is false and the query fields
are absent. Over a full page of rows (`truncated`, 0.174.0) `searched`, `ranks_first` and
`homepage_ranks_first` are absent and `branded.reason` says the brand's rows may be past
the cap, so KW-070 and GO-139 are `NO_DATA` with that reason; the query and page read
stay as evidence.

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

Requires `offline` by default — it reads a file you exported, so even `archive` mode
can use it. BL-083 adds `--check-targets` and therefore requires `fetch`. Probed
against a two-sheet export (top linking sites, top linking text).

`source` — str, absolute path of the export
`site` — str, whatever was passed as `--site`
`linking_domains` — int — rows of the linking-sites sheet; absent when the export has
  no such sheet (F15 batch 7), so BL-084, BL-086 and BL-087 are NO_DATA
`total_links` — int — the sheet's link counts summed; absent with it
`top_sites[]` / `anchors[]` / `top_linked_pages[]` — arrays, capped at 50; `top_sites`
  largest first, whatever the export's order (F15 batch 7, BL-084)
  - item keys: name, count
`anchor_profile.branded` / `.generic` / `.other` / `.classified` — int
`concentration.top1_share_pct` — float | null
`concentration.top10_share_pct` — float | null
`note` — str | null, set when a single unnamed CSV had to be guessed at
`issues[]` — array
`error` — str | null
`error_kind` — str (`input`) when the named export is missing
`targets.linked_pages` — int — same-host page rows; read by BL-083 (applies_when)
`targets.off_host` — int
`targets.checked` — int
`targets.broken_count` — int — read by BL-083
`targets.broken[]` — array
  - item keys: url, status, error_kind, incoming_links
`targets.unchecked[]` — array
  - item keys: url, error, error_kind
`targets.redirected[]` — array
  - item keys: url, final_url
`truncated` — bool — present with `--check-targets`; true when the 100-target cap
  bites or any requested target is unchecked
`truncated_reason` — str — present when `truncated` is true

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
`canonical_match` — bool, **absent** when the page declares no canonical; the two
  URLs compared as sent (`seo_common.comparable_url`), so `/page` and `/page/` differ (CI-010, F15)
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
`checks.return_tags.self_only` — bool — every URL in the set is the page itself and every code
  is valid: IN-122 is N/A (the owner's ruling 2 on F15 batch 4's questions)
`checks.return_tags.verified_and_valid` — bool — **absent** when verification was not
  requested or any alternate could not be fetched, so IN-122 reports `NO_DATA`
  instead of inferring validity from an incomplete check. False, whatever the returns,
  when `language_code_issues` is not empty (with or without `--verify-returns`), or, under
  `--verify-returns`, when the set names no URL but the page itself; an x-default on
  another URL is verified like an alternate (IN-122, F15)
`language_code_issues[]` — codes outside Google's ISO 639-1 / ISO 3166-1 alpha-2 format:
  `jp`, `jp-JP`, any three-letter language (`eng-US`, `jpn`, and `fil`, which has no
  two-letter code), an unknown or numeric region (`es-419`), a malformed tag; one issue
  per code; a valid code's better spelling (`zh-CN` -> `zh-Hans`, bare
  `zh`) is `validate_lang_code`'s `advice` and not listed (F15 review round 1)
`checks.return_tags.detail` — str
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
  unreadable, was not JSON, was not an object, recorded measurements without `html`, or
  has no `doctype` key beside an `html` without one (F15 batch 6: `doctype` is put back in
  front of `html` before validation, `""` for a page that declares none).
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
`text_nodes_below_contrast` — int — CN-036; elements carrying their own text whose
  computed colour, composited over the element's and its ancestors' background colours
  down to the nearest opaque one, falls under the WCAG AA floor — 3:1 for large text
  (24px, or 18.66px bold), 4.5:1 otherwise.
  Until 0.101.0 CN-036 read `checks.inline_contrast_candidates` from
  `a11y_seo_checker.py`, a count of elements whose *inline* style named a colour and
  a background: a page at 1.16:1 set in a stylesheet scored 0 and passed, one at 21:1
  written inline scored 1 and failed. **Withheld** when it is 0 and
  `text_nodes_contrast_unmeasured` is not 0 or is absent (F15), so CN-036 reads NO_DATA
  there; a count above 0 always stands
`text_nodes_contrast_unmeasured` — int — text over a CSS background image or
  gradient, which has no colour to compare with, or whose colour or background is
  outside `rgb()` (`oklch()`, `color()`, `lab()`); an `<img>` behind the text is not
  detected (F15; until then it was scored against the
  colour behind the image). A file from the snippet before F15 has no such key
`links_indistinct` — int — CN-035: links in running text (the nearest block around
  the link holds text outside its links) that are not underlined, not bolder, have no background of their own, and
  are in the text's colour or under 3:1 against it (WCAG G183). **Withheld** at 0 when
  `links_contrast_unmeasured` is not 0 or is absent (F15).
`links_contrast_unmeasured` — int — links whose colour or whose text's colour is outside
  `rgb()` and differs from the other, so no ratio is read. Until F15 only `p a, li a, td a,
  article a` were read, and any colour difference at all made a link distinct
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
`placeholder_alt` — int — **absent on a page with no images**. Images whose alt is
  present and non-empty and still describes nothing: a filename, a camera or
  asset stub (`IMG_0042`, `untitled`, `banner`), fewer than three characters, or
  not one letter anywhere. `alt=""` is never counted here — an empty alt is the
  correct markup for a decorative image and is `empty_alt`.
`empty_alt_meaningful` — int — **absent on a page with no images**. Images with an
  empty (or whitespace) alt that carry meaning: a link's only content however it is
  marked, or an image declared at least
  `MEANINGFUL_IMAGE_MIN_PX` (200) on each side outside nav, aside, a page-level header
  or footer (one inside article, aside, main, nav or section is content), and their
  ARIA roles; nothing inside a `hidden` or `aria-hidden` link or wrapper counts
  (`seo_common.image_carries_meaning`, F15)
`alt_not_meaningful` — int — **absent on a page with no images**. `missing_alt +
  placeholder_alt + empty_alt_meaningful` (the last since F15), and what CI-016 and
  MD-186 assert since 0.105.0. Both halves fail the question
  those items are titled for, and a rule gets one operator over one path, so the
  sum is the leaf rather than two asserts. It can only be greater than or equal
  to `missing_alt`.
`summary.images` — int — images with any source: `src`, `data-src`, `srcset`, a
  `<picture>` source or `data-srcset` (F15: srcset- and picture-only images, and
  data-srcset-only ones, were skipped as having no `src`)
`summary.lazy_lcp_candidates` — int — CN-054's compatibility path: JS-deferred images
  with `data-src`/`data-srcset` but no native `src`, `srcset`, or `<picture>` source;
  a `data:` placeholder `src` or `srcset` beside them is no native source, and a
  `<noscript>` `<img>` with the deferred URL is one (F15).
  Native `loading=lazy` remains discoverable and does not increment this count.
  **Absent on a page with no images.**

`alt_not_meaningful` is the field the registry reads as a verdict for the alt-text
pair, alongside `count` and `summary.lazy_lcp_candidates`, and since 0.49.0 a page
with no images emits none of them, so the four items over this script report `NO_DATA`
there rather than a FAIL for MD-184 and a free PASS for CI-016, MD-186 and CN-054. The
descriptive counts stay: `summary.images` is 0 because the page has none, which is a
fact about the page rather than a claim about its images. Same rule, same reason, as
`responsive_count` and `modern_format_count` in `image_weight_audit.py` below.
`issues[]` — array
  - item keys: severity, message, url
`images[]` — array
  - item keys: src, alt, has_alt, empty_alt, placeholder_alt, empty_alt_meaningful,
    width, height, is_responsive_fill, loading, srcset, sizes, format,
    likely_lcp_candidate, native_source, deferred_source, discoverable
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
  whose candidate set a phone ends up with — the first `<source>` that can match at
  any width (a `min-width`, `width >=` or `print` source is skipped: a phone matches
  none),
  else the `img` — offers width descriptors (`w`), or with a `max-width` `<source>`
  before it (F15: any `srcset`, a density or format-only
  one too, and an `img` srcset behind a format-only `<source>`). Read by nothing since 0.108.0, when MB-096 and MD-189 moved to the
  per-image count below; kept as evidence. The count was wrong in the same direction.
`modern_format_on_img_count` — int — the narrow count: `img` src only
`srcset_on_img_count` — int — the narrow count: `img` attribute only
`srcset_without_sizes_count` — int — absent when the page has no images; otherwise,
  images offering width-described candidates with no `sizes` to choose between them.
  MB-098 asserts `eq: 0`. Only `w` descriptors count: an `srcset` in `x` descriptors
  needs no `sizes`, and until 0.93.0 both the count and the `issues[]` message said
  otherwise, reporting correct markup as a defect
`large_image_count` — int — **absent** when no transfer size was learned, which on a
  page nobody fetched is every image. MB-095 asserts `lte: 5` and is invoked with
  `--fetch-images` for exactly this reason: without it the key never appears and the
  item is NO_DATA. Emitting 0 instead would report a light page from zero readings
`large_without_srcset_count` — int — emitted only with `--fetch-images` on a page with
  images: images wider than `LARGE_IMAGE_WIDTH_PX` (1280), read from each image's own
  header, that are not `responsive` (above). MB-096 asserts `eq: 0`. An image whose
  width was not learned is in no count and sets `truncated`
`large_legacy_or_unresponsive_count` — int — same conditions: images wider than 1280
  px that are not `responsive` or have no WebP/AVIF offer. MD-189 asserts `eq: 0`, both
  halves of its title (F15; until then it read `large_without_srcset_count` and scored
  with MB-096)
`legacy_or_heavy_count` — int — same conditions: images wider than 1280 px with no
  WebP/AVIF offer, or any image over `LARGE_IMAGE_BYTES`. MB-097 asserts `eq: 0` — its
  title's format half and compression half
`image_width_unknown_count` — int — same conditions: images, not broken, whose width
  could not be learned (not an image format this reads, or a JPEG whose frame header
  lies past `IMAGE_HEADER_BYTES`)
`picture_count` — int — images wrapped in a `<picture>` carrying a `<source>`

A fetched image is broken (MD-187) when it answers dead, 404/410, a 204/205, or a 2xx
declaring a type outside `image/*`; an untyped, `application/octet-stream` or
`binary/octet-stream` 2xx is read for an image header and is unchecked when none is found (F15: any non-text 2xx
was fine). A large image with no modern format is a `warning` in `issues[]` (F15:
`info`), as an image over `LARGE_IMAGE_BYTES` is, so MD-185 does not pass an image
MB-097 fails.
`truncated` — bool — an image on this page answered nothing, or (with
  `--fetch-images`) an image's width or byte size went unlearned, so the counts above
  are over the images that did. `broken_image_count` is withheld outright when nothing
  broken was found; this is the other half, said beside a count that *was* emitted
  because something broken was found and is therefore a floor
`issues[]` — array
  - item keys: severity, message, url
`images[]` — array
  - item keys: src, format, width, height, loading, fetchpriority, srcset, sizes,
    sizes_required_and_absent, picture_source_count, picture_srcset,
    picture_modern_formats, responsive, modern_format, likely_lcp_candidate, status,
    content_length, content_type, intrinsic_width, intrinsic_height, large
`truncated_reason` — str — present when `truncated` came from an unlearned width or size
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
  - item keys: url, status, error_kind, content_type, pages
`truncated` — bool — true for any of three reasons: the crawl behind this was capped,
  an image answered nothing, or an image sat past `--max-images` and was never asked.
  `broken_image_count` and `broken_images` are absent whenever one of the last two
  applies and nothing broken was found
`fetch_error` — NoneType or str

### indexability_matrix.py

`site` — str
`count` — int
`fetch_error` — NoneType or str (no URL answered; three `critical` items read `rows.0`)
`fetch_error_kind` — NoneType or `blocked` (every URL refused by this audit's guard)
`sitemap_membership_unknown` — NoneType or str — why `in_sitemap` is null on every row
`rows[]` — array
  - item keys: url, final_url, status, status_class, robots_allowed, robots_rule, meta_robots, x_robots_tag, snippet_controls, canonical, in_sitemap, redirects, verdict, blockers, error, error_kind
`rows[].robots_allowed` — bool; absent when this audit's guard refused robots.txt
  (`robots_rule` says so), so CI-005 is NO_DATA rather than read off an unread file (0.173.0)
`rows[].verdict` — `indexable`, `not_indexable`, or null when no blocker was found and
  robots.txt was not read (0.173.0)
`rows[].in_sitemap` — bool or null — null when the sitemap byte budget left files unread
  or the sitemaps listed more than `SITEMAP_URLS_BUDGET` URLs (0.172.0), and from 0.173.0
  when a location past the tenth, an index's children, a location with no answer or a
  sitemap on another host went unread; read by no item
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
  - an `X-Robots-Tag` rule counts only unscoped or for `googlebot:`, each header value
    read on its own (GEO-008, F15: `bingbot: nosnippet` is Bing's)

With `--inventory`, no URL is fetched. The alternate output shape is:

`server_errors[]` — array, sorted by URL
  - item keys: url, status, linked_from
`summary.pages` — int
`summary.server_errors` — int — what CI-015 asserts is zero
`truncated` — bool
`truncated_reason` — str — present when the shared crawl was truncated

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
  as text (`text/plain`, or no content type) and is the key alone, a BOM and
  surrounding whitespace aside (F15; it accepted any body containing the key). Added in 0.8.0; it had never been emitted, so GEO-007 reported
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
`pages_read` — int — HTML pages, a redirect row read again counted once
`internal_urls` — int — distinct internal URLs the crawl found: the pages read and every
  internal URL they link (files and robots-refused paths included), each where it lands
`too_few_pages_for_average` — bool — a whole crawl (not `truncated`) that found fewer
  `internal_urls` than `MIN_PAGES_FOR_AVERAGE` (4), where no page can link 3 distinct
  others; AR-162 is N/A on it (F15, the owner's ruling on batch 3's question 3)
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
`internal_redirects[]` — array — AR-149's subject: each linked spelling that
  redirects, `linked_from` the pages whose links use that spelling (F15: a linked
  `/about/` is fetched beside the `/about` the crawl read)
  - item keys: url, to, hops, linked_from
`truncated_reason` — str — also set when a linked spelling went unfetched
  (`site_crawl` `summary.unchecked_spellings`), which withholds AR-149's pass
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
`raw.meta_robots` — NoneType or str — every robots tag's rules, lower-cased, sorted, once
  each, `none` expanded and the defaults (`all`, `index`, `follow`) dropped, so a
  respelling is no diff; `None` when nothing is left. Read by MB-105's comparison, from F15
`raw.meta_googlebot` — NoneType or str — the same, for `<meta name="googlebot">`
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

`truncated` — bool — the crawl behind this stopped at its page or depth cap, so every
  count here is over the pages it read
`truncated_reason` — str — present when `truncated` is true: why the orphan count and
  the site-average finding are withheld (0.170.0)
`fetch_error` — NoneType or str
`pages_crawled` — int
`total_internal_links` — int
`total_external_links` — int
`unique_internal_targets` — int
`unique_external_domains` — int
`avg_internal_links_per_page` — float — distinct other pages linked to, averaged (F15,
  AR-162; repeated and self links do not count)
`robots_refused[]` — array (kept out of the orphan arithmetic on purpose)
`orphan_pages.count` — int — read by CI-008; absent when `truncated` is true, because
  an orphan is a page no page *read* links to. Only the home page is credited unlinked,
  not a deep entry URL (F15)
`orphan_pages.urls[]` — array; absent with the count
`orphan_pages.reason` — str — present instead of the two above when `truncated` is true
`dead_end_pages.count` — int — pages linking to no other page (self-links do not count)
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
`well_formed` — bool — GEO-001: a 200 whose first line is a `# ` title and
  which is not an HTML page, the one element the llms.txt format requires. False on a
  404; **absent** on any other status, so the item reads NO_DATA (0.115.0)
`well_formed_reason` — str | null — why it is false
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
`local_business_nodes` — int; absent on the inventory path when the crawl was truncated and found none, so LO-198 answers NO_DATA rather than failing on pages never read
`nap_complete` — bool: true when every LocalBusiness node has name, address, and telephone; written only for a page carrying at least one LocalBusiness node, so a page with none reports no key and the item answers NO_DATA
  Since F15 batch 5: name and telephone as non-blank text, and an address that is a
  PostalAddress with `streetAddress` and `addressLocality`
`scope` — str: `site` (inventory only)
`pages_checked` — int (inventory only)
`local_business_pages[]` — array (inventory only)
`truncated` — bool: the crawl's `summary.truncated` (inventory only)
`truncated_reason` — str: why `local_business_nodes` is absent (inventory only, written with it absent)
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

### gsc_sitemap_reconcile.py

Requires `gsc` capability. URL Inspection checks a deterministic, quota-bounded
prefix of sitemap URLs; Search Analytics supplies the reverse set of pages known to
have received impressions. A clean result over truncated input is `NO_DATA`. When a
sitemap read is incomplete, reverse-direction evidence is published but not counted;
a not-indexed finding in the sitemap URLs that were read remains a failure.

`site` — str
`property` — str
`sitemap_source` — str (`submitted` / `discovered`) | null
`sitemaps_checked[]` — array of str
`sitemap_errors[]` — array
  - item keys: url, status, error, error_kind
`period.start` / `period.end` — str (`YYYY-MM-DD`) | null
`not_indexed[]` — array, not capped
  - item keys: url, coverage_state
`undecided[]` — array, not capped
  - item keys: url, plus coverage_state or error
`indexed_not_in_sitemap[]` — array of str, capped at 50 after counting
`summary.sitemap_urls` — int — read by GO-137 (applies_when)
`summary.inspected` — int
`summary.indexed` — int
`summary.not_indexed` — int
`summary.undecided` — int
`summary.pages_with_impressions` — int
`summary.indexed_not_in_sitemap` — int
`summary.indexed_not_in_sitemap_counted` — bool — false when sitemap errors or the
  sitemap-walk cap make the reverse comparison incomplete
`summary.unreconciled` — int — read by GO-137
`summary` — absent when a required service call fails, every inspection errors, or
  submitted/discovered sitemaps exist but none can be read
`truncated` — bool — true for the per-run inspection cap, time budget, undecided
  inspections, a full Search Analytics result page, or an incomplete sitemap read
`truncated_reason` — str, absent when `truncated` is false
`issues[]` — array
  - item keys: severity, type, count, finding, fix, urls[]
`issues` — absent whenever `summary` is absent
`error` — str | null
`error_kind` — str (`input` / `service` / `unread`), present only with an error

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
`field_cwv.measured[]` — array  (which of LCP, INP, CLS the verdict is over; a `pass`
  needs LCP and CLS among them, F15)
`above_fold.rating` — str  (good | needs-improvement | poor) — SP-107: the worse of
  `above_fold.FCP` and `above_fold.LCP`, each `{rating, source}` copied from `metrics`,
  so both from CrUX or, for a page CrUX has no sample of, both from Lighthouse — never
  one of each, since the report names lab numbers only on a page with no field data
  (INP-5). Absent when neither paint is known, and when one is good and the other
  unknown — a pass needs both (F15: SP-107 read FCP alone)
`field_cwv.failing[]` — array
`field_cwv.unknown[]` — array  (present only when a rating fell outside
  good | needs-improvement | poor)
`opportunities[]` — array
  - item keys: title, savings_ms, description
`diagnostics[]` — array
  - item keys: title, score, display
`field_data_available` — bool
`total_byte_weight` — int — Lighthouse's `total-byte-weight`: the bytes of every resource
  the page requested in this run (mobile emulation under `--strategy mobile`). Absent
  when the audit or a non-negative number is missing. From 0.119.0
`page_weight` — str — `light` (below `PAGE_WEIGHT_TARGET_KIB`, 1,600 KiB), `heavy` (up to
  `PAGE_WEIGHT_FLAG_KIB`, 5,000 KiB), `enormous` (above it); absent with
  `total_byte_weight`. MB-095 reads it
`error` — NoneType

### parse_html.py

`title` — str
`meta_description` — str
`meta_description_chars` — int — its length with whitespace collapsed; absent when the
  description is missing or empty (MS-028's subject). From 0.120.0
`meta_description_band` — str — `short` (under `article_seo.META_MIN_CHARS`, 100),
  `fits` (up to `META_MAX_CHARS`, 144, the calibrated desktop snippet), `long`; absent
  with `meta_description_chars`. MS-030 reads it
`meta_robots` — str — every `<meta name="robots">` content, joined with `, ` (F15: only the
  last was kept); `None` when the page has none. CI-004 reads it
`meta_keywords` — NoneType — every keywords tag's non-empty content, joined (F15). MS-031
  reads it
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
  - `schema` / `ui` — bool — parseable markup with a trail entry (F15), and an explicit UI
    marker; a Microdata/RDFa trail alone is UI only with a link in it
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
`walk` — str — AR-150 (F15): `direct`, `one_hop`, `chain` (two or more hops, or the
  ten-hop cap reached), or `loop` (`/a` -> `/a` and `/a` -> `/b` -> `/a` included);
  absent when the walk stopped on an error
`total_time_ms` — int
`has_loop` — bool — CI-014, **absent when `truncated`**: the walk stopped at ten hops
  and whether the rest of the chain loops was never seen. Absent rather than null,
  because a null satisfies `falsy` and would pass the item it must not.
`truncated` — bool
`has_mixed_protocol` — bool
`issues[]` — array
`redirect_issues[]` — array — present whenever the walk completes, including a capped
  walk; absent only when `error` is set
  - item keys: severity, type, message, url
  - errors report loops, the documented ten-hop cap, and redirects without `Location`;
    warnings report multi-hop chains and each 302/303/307 temporary redirect
`error` — NoneType

### rich_results_guard.py

`nodes` — int
`rows[]` — array
  - item keys: path, types, issues
`issues[]` — array
`summary.errors` — int
`summary.warnings` — int
`summary.invalid_blocks` — int
`summary.retired_types` — int (written from the code in F04 batch 4b, not from a probe run: nodes whose type is in `lib/schema_types` `DEPRECATED_TYPES` or `RESTRICTED_TYPES`)
`truncated` — bool
`truncated_reason` — str
`source` — str
`final_url` — str

### robots_checker.py

`url` — str
`status` — int
`correctness_problems[]` — array of str — AR-151 (0.117.0): an HTML page at the path,
  over 500 KiB, a line that is not `field: value`, an unread directive, a rule before any
  user-agent, a relative sitemap, a `User-agent:` line with no name (F15), or the whole
  site disallowed for Googlebot — `/` and every path of the `--inventory` crawl (F15;
  each crawled row's own URL and each refused URL as asked, `robots_blocked_urls`, not
  their keys); on a 404 the one entry "no robots.txt at this
  origin"; **absent** on any other status. Without readable crawled paths (no
  `--inventory`, or one unread or another site's) a disallowed `/` adds no problem and
  sets `truncated`; on a capped crawl every path read being shut is likewise withheld
  (no problem, `truncated`), while an open path read or any other problem stands
`user_agents.*.allow[]` — array
`user_agents.*.disallow[]` — array
`sitemaps[]` — array — an empty `Sitemap:` line is no entry (CI-006, F15)
`ai_crawler_status.GPTBot` — str
`ai_crawler_status.OAI-SearchBot` — str
`ai_crawler_status.ChatGPT-User` — str
`ai_crawler_status.OAI-AdsBot` — str
`ai_crawler_status.ClaudeBot` — str
`ai_crawler_status.Claude-User` — str
`ai_crawler_status.Claude-SearchBot` — str
`ai_crawler_status.PerplexityBot` — str
`ai_crawler_status.Perplexity-User` — str
`ai_crawler_status.Google-Extended` — str
`ai_crawler_status.Applebot` — str
`ai_crawler_status.Applebot-Extended` — str
`ai_crawler_status.CCBot` — str
`ai_crawler_status.Bytespider` — str
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
  `--discover-assets`, including query strings because robots rules can match them,
  and the stylesheets same-origin sheets and `<style>` blocks `@import` (CI-013, F15).
`unread_stylesheets[]` — array of str — same-origin stylesheets that answered neither
  content nor 404/410 (or past `MAX_STYLESHEETS_READ`), so their imports are unknown;
  with them `truncated` is true and the runner withholds CI-013's PASS (F15).

Under `--probe` only, and absent without it:

`indexable_urls[]` — array of str — **what CI-019 asserts is empty.** Tested URLs that
  are permitted by robots.txt, answered 2xx/3xx, and carry no `noindex` in a
  `<meta name="robots">` or an `X-Robots-Tag`. A 404 or 410 is not an indexable page
  and does not appear. Comments are stripped before the meta tag is looked for —
  markup inside a comment is not markup.
`unprobed_urls[]` — array of str — permitted URLs whose fetch failed or answered 5xx or
  429 (F15 review round 2).
  Deliberately neither list: an unreachable page is not proven absent and not proven
  indexable, so a network failure cannot read as a clean site. Any of them sets
  `truncated` and names them in `truncated_reason`, so CI-019's PASS is withheld (F15).
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
`nodes_and_invalid_blocks` — int — MS-032's subject: typed nodes plus JSON-LD blocks that do
  not parse (F15 batch 5)
`invalid_blocks` — int
`checked_type` — NoneType
`incomplete_nodes_by_type` — object — one entry per schema type present on the page,
  counting the nodes of that type with a missing required or recommended property or a
  placeholder value — since F15 batch 5 among that type's own properties only (a
  co-type's are not its), `alternateName` among WebSite's. A type with nothing wrong still gets a key, at zero, so an absent
  key means the page declares no node of that type — which is what GO-143's
  `missing_is: pass` answers on `incomplete_nodes_by_type.WebSite`
`rows[]` — array
  - item keys: path, types, missing_required, missing_recommended, placeholder_properties
`issues[]` — array
  - item keys: severity, message, url, evidence
`summary.errors` — int
`summary.warnings` — int
`summary.warnings_if_every_block_parses` — int — `summary.warnings`, absent when a block does
  not parse, so MS-032's warn band cannot soften that failure (F15 batch 5)
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
`hsts_enabled` — bool — true only when the final URL is HTTPS and a present HSTS header
  has an integer `max-age` greater than zero
`hsts_disabled_reason` — str | null — why a present HSTS header did not enable HSTS;
  null when enabled or when the header is absent
`hardening_missing[]` — sorted array of missing `content-security-policy`,
  `permissions-policy`, and `referrer-policy` header names
`hardening_gaps[]` — array of str, one `<header>: <why>` per hardening header missing or
  weak: a CSP letting scripts run inline or through eval (`'unsafe-inline'` with no nonce,
  hash or `'strict-dynamic'`), a Permissions-Policy feature `=*`, a Referrer-Policy whose
  last known token is `unsafe-url`. SE-120 reads it (F15 batch 6)
`http_to_https` — str — the worst decided answer the `http://` addresses gave:
  `permanent` (301/308 to https), `temporary` (302/303/307 on the way to https),
  `not_listening` (the connection was refused), `not_redirected` (a page, an error, a
  loop, a redirect with no Location or an http-only chain). **Absent** when an address
  was `unread` and none was `not_redirected`, so SE-117 is NO_DATA rather than guessed.
  From 0.118.0; the same port is kept for an `https://` URL that names one
`http_variants[]` — one per `http://` address asked, in the order asked: the audited
  page's, then up to `HTTP_SAMPLE_PAGES` (3) same-origin pages it links to that
  robots.txt permits. Empty only when the main read failed
`http_variants[].url` — str — the `http://` address
`http_variants[].page` — str — the page it is the address of
`http_variants[].outcome` — str — one of the four above, or `unread`
`http_variants[].hops[]` — `{url, status, location}` per plain-HTTP response, up to the
  first `https://` Location, which is not requested. Empty for a page whose own read
  ended on `http://`, and for `not_listening` / `unread`
`http_variants[].error` — str | null — why an address is `unread`
`withheld` — object — `{"http_to_https": "blocked"}` when `http_to_https` is absent because
  this audit's guard refused every address left `unread`, so the runner records SE-117's NO_DATA
  with the guard's kind (F04, HTTP-13); absent otherwise
`page_security` — str — what a browser does to the page, worst first: `plain_http` (the
  page itself ended on http://), `blocked_content` (a blockable request over http://),
  `upgraded_content` (only upgradable ones), `secure`. From 0.121.0; TE-175 reads it
`mixed_content[]` — `{url, tag, attribute, kind}` per http:// load on an https page, in
  document order; `kind` is MDN's: `blockable` (script src, stylesheet link href, iframe
  src, object data, img/source srcset) or `upgradable` (img/audio/video/source src, but
  `blockable` on an IP-address host). Empty on a plain-HTTP page and on a non-HTML response
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
`truncated` — bool — **this answer does not cover its whole subject.** Six causes:
  `--max-lines` reached, a window under 7 days, an inventory that would not load, a
  crawl inventory that stopped at its page or depth cap (0.170.0), a sitemap list the
  crawl's walk did not read whole — a budget, the file cap, a sitemap on another host or
  one with no answer (`sitemap_set_incomplete`, 0.174.0) — or a sample under the
  rate floor. Each silences a finding CI-018 would otherwise read, so a
  clean answer here is not a clean bill of health and the runner withholds the `PASS`
`truncated_reason` — str — why, in the checker's own words; `""` when nothing was
  withheld. The runner prints it under the withheld verdict instead of blaming a cap
`user_agent_recorded` — NoneType or bool
`error` — NoneType or str — **set, and everything else left empty, when the log
  cannot answer**: no such file, nothing parsed, or Common Log Format, which records
  no User-Agent. "No crawler visited" and "this file cannot say" are opposite
  findings and the second is never printed as the first
`bot_identity` — str — a fixed sentence saying the User-Agent is a claim, not proof
`crawler_requests_unconfirmed` — int | null — requests counted as a search or AI crawler whose
  address was not confirmed: all of them without `--verify-bots`, and with it every one with no
  usable PTR record, no published DNS rule, or past the address budget; null until a log was read.
  The runner carries it to both reports (`w_log_claimed`, F04)
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
  empty array would read as "we looked and there were none". Over a crawl that stopped
  at its cap, taken over the sitemap URLs the crawl fetched only (0.171.0)
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
`summary.refused_pages` — int — pages this audit's guard refused (0.173.0); each makes the crawl `truncated`
`summary.unanswered_pages` — int — pages that gave no answer twice: timed out, connection refused or reset,
  or the body cut off while it was read; each is asked once more and, silent again, makes the crawl
  `truncated` (F04)
`summary.truncated` — bool
`summary.unchecked_spellings` — int — linked spellings past the budget or never
  answered (F15; AR-149 withholds its pass)
`pages.<key>` — object, one per deduplicated page; the key is the page key and
  `url` is the first discovered spelling that was fetched
  - `url`, `final_url`, `status`, `content_type`, `redirect_chain[]`, `redirected`,
    `bytes`, `error`, `error_kind`, `cut_off` (the body broke off while read, F04),
    `robots_blocked`, `html`, `depth`, `discovered_by`
    (`entry`/`sitemap`/`link`), `in_sitemap`
  - `title`, `meta_description`, `meta_robots`, `canonical`, `noindex`
    (meta **and** `X-Robots-Tag`); `canonicals[]` — every canonical declared, the
    `Link` header's included (`declared_canonicals`); `canonical` is the one usable
    canonical, `null` when there are none or two that disagree (F15, TE-176)
  - `content_words`, `text_hash`, `signature[]` (MinHash, 100 values)
  - `internal_out`, `unique_internal_out`, `external_out`
  - `schema_nodes[]` — one object per parseable JSON-LD node; item key: `types[]`; since
    F15 batch 5 also one per Microdata item and RDFa resource, with `format: "markup"`
  - `links[]` — item keys: target, anchor, rel, nofollow, internal, alt_named; `anchor`
    is the link's text, else its `aria-label` or its images' alt (`alt_named` true then;
    F15, BL-081)
  - `images[]` — array
`reachable[]` — array of page keys
`unchecked_internal_targets[]` — array
`robots_blocked.<key>` — str
`robots_blocked_urls.<key>` — str — the URL a refused key was asked as (a key folds the
  trailing slash; AR-151 tests this one, F15 review round 2)
`sitemap.urls[]` / `.off_host[]` / `.sitemaps_checked[]` / `.unvisited[]` /
`.errors[]` — `unvisited` contains normalised sitemap URLs left unread when the
sitemap-walk cap is reached; a fetch error item retains `error_kind` beside `error`
`broken[]` — array — item keys: url, status, error, error_kind, linked_from
`redirected[]` — array — item keys: url, to, hops, linked_from — one per redirecting
  spelling, `linked_from` the pages whose links use that spelling (F15, AR-149)
`spellings.<url>` — object — a linked spelling of a crawled page other than the one
  fetched for it, fetched once: key, status, final_url, redirect_chain, error_kind,
  unchecked
`external_targets.<url>[]` — array — item keys: source, anchor, nofollow

A page key is `scheme://host/path` spelled as requests sends it (`/café` and
`/caf%C3%A9` are one), the query dropped except a page number (`?page=2`,
`PAGE_NUMBER_PARAMS`; page 1 is the page itself), trailing slash kept only on the root. Inventory version 6 (F15 batch 5: `schema_nodes` also carries Microdata and RDFa items, each `{types, format: "markup"}`). `--out PATH` writes the inventory to a file and prints the summary instead.

### sitemap_checker.py

`site` — str
`sitemaps_checked[]` — array
  - item keys: url, status, final_url, redirects, type, url_count, sitemap_count, error, error_kind
`urls[]` — array
  - item keys: url, lastmod, changefreq, priority, checks (status, final_url, redirects,
    error and error_kind when `--fetch-urls` requests the URL)
`robots[]` — array, one per consulted origin, sorted by origin
  - item keys: url, status, read
  - `read` is false when robots.txt answered nothing, 429, or 5xx; a 4xx other than
    429 is read as no restrictions
`blocked_by_robots[]` — array, sorted by URL
  - item keys: url, rule
`summary.sitemaps` — int
`summary.urls` — int
`summary.indexes` — int
`summary.issues` — int
`summary.blocked_by_robots` — int
`truncated` — bool — the sitemap walk stopped at `MAX_SITEMAPS_FOLLOWED`, or at
  least one consulted robots.txt could not be read
`truncated_reason` — str — present when robots.txt could not be read; names every
  unread robots response and also says when the sitemap walk hit its cap
`invalid_url_count` — int — **absent** unless URLs were read, and absent again when any
  probe failed and none of the ones that answered was invalid. An unread robots.txt
  also withholds the key unless another invalid URL was found. A URL is invalid at a
  status of 400 or above, on a redirect chain, on a noindex Google obeys
  (`seo_common.google_noindex`: robots or googlebot meta, the `X-Robots-Tag` unscoped or
  for `googlebot:`, `none` included; F15, `checks.noindex` lists where), or when
  robots.txt disallows it for Googlebot. GO-138 asserts `eq: 0`; before 0.93.0 it matched
  `(?i)404|redirect|noindex` against the messages, and since the message reads
  "Sitemap URL returns HTTP {status}", a sitemap of URLs answering 500 passed
`issues[]` — array
  - item keys: severity, message, url, evidence
  - an `error` "Invalid sitemap: …" for a sitemap that parsed but is not valid: an
    entry with no `<loc>`, a root other than `<urlset>`/`<sitemapindex>` or outside
    `http://www.sitemaps.org/schemas/sitemap/0.9`, or one listing nothing (GO-136, F15;
    `seo_common.parse_sitemap_xml`'s `problems`)

### social_meta.py

`url` — str
`score` — int
`preview_score` — int — `score` on a page carrying `og:image` and `twitter:card`, 0 otherwise:
  what MS-033 asserts (F15 batch 5)
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
    — `src` resolved against the page (a `//host` script is read on its host); `blocking`
    only for a classic script (a JavaScript `type` or none), never a data block (F15 batch 6)
`truncated` — bool — the sitemap index walk stopped at `MAX_SITEMAPS_FOLLOWED`
  with files still queued, so `issues` is over the files that were read
`fetch_error` — NoneType

### topical_cluster_mapper.py

`page_count` — int
`too_few_pages_for_hubs` — bool — a whole crawl (not `truncated`) of fewer pages answering
  with content (an error page is none) than `MIN_PAGES_FOR_HUBS` (4), where a word two titles share is on more than half of them
  and no subtopic can form; AR-153 is N/A on it (F15, the owner's ruling on batch 3's
  question 3)
`cluster_count` — int
`hub_count` — int — clusters of two or more pages (F15)
`score` — int — 0 when a site of more than one page has no hub (AR-153, F15)
`clusters.seo.page_count` — int
`clusters.seo.hub` — str, or null for a one-page cluster (not a hub, F15)
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
`error_kind` — str — `blocked` or `unresolved`, only when the guard refused the address
  or port before any connection (0.172.0; the runner recorded `crash` before)
`reason` — str — only when the URL is `http://`
`issues[]` — array

### url_quality.py

`count` — int
`rows[]` — array
  - item keys: url, path, param_count, params, flags, short, score
  - `short` — bool — AR-147: at most `MAX_URL_CHARS` characters, `MAX_PATH_SEGMENTS`
    path segments and `MAX_SHORT_PARAMS` query parameters (0.115.0)

### video_schema_checker.py

`videos` — int
`page_videos[]` — array — the videos the page shows: a `<video>` with a source (not one without
  controls that autoplays, muted or not, or is a muted loop) and a player `<iframe>`/`<embed>`
  (its `src`, or a lazy `data-src`/`data-lazy-src`; a Microdata/RDFa VideoObject declares one),
  none in a page-level `<aside>` or `<footer>` (a sidebar or site-footer widget); a hero in the
  page's header is the page's
`video_signals` — int — the larger of `videos` and `page_videos`: MD-190's subject (F15 batch 5)
`rows[]` — array
`issues[]` — array
`source` — str
`final_url` — str
