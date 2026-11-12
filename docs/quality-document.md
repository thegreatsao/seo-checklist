# Quality Document

<!-- L12: Continuous module health scoring.
     A quality document makes codebase degradation visible before it becomes a crisis.
     New sessions read this document and immediately know where to prioritize.
     Fix the lowest-scoring module first.

     FILL IN: Replace example modules with your actual codebase modules.
     Score on each session's clock-out, or at minimum weekly.

     Grades:
       A — Fully passing, clean, stable, compliant, consistent
       B — Minor issues; nothing blocking the agent or breaking the build
       C — Significant issues that slow agent work or produce flaky results
       D — Broken or untrustworthy; fix before activating related features

     Update policy:
     - Immediate: update the relevant module after every feature that touches it
     - Weekly: full sweep — re-score all modules, promote issues to feature_list.json

     Scoring dimensions (rate each A / B / C / D):
       Verification passing  — does the feature's verification command pass?
       Agent understandable  — can a fresh agent session read and act on this module?
       Test stability        — are tests consistently passing (not flaky)?
       Architecture boundaries — no cross-layer violations in .harness/arch-rules.json?
       Code conventions      — consistent naming, no debug artifacts, no stale TODOs?
-->

---

<!-- FILL IN: Replace the examples below. Each module section should be updated
     after each feature that touches it. Aim for all modules at A or B.
     If a module reaches C or D, create a feature_list.json entry to fix it. -->

## Not graded yet

No other module has been scored. The module map is in `AGENTS.md`, "Architecture Boundaries". Grade a module the first
time a feature touches it, from that session's own `make check` and review, not from this file's age.

## `citation_readiness.py` (the owner's ruling on the follow-up's path-rule question) — graded 2026-11-12, F15

Read for the grade: `citation_readiness.py` (`utility_page`, `LANGUAGE_SEGMENT_RE`), `tools/build_checklist.py`
(`MEASURES` for GO-145, GEO-005), `resources/i18n/ru.json`.

| Dimension | Grade | Basis |
|---|---|---|
| Verification passing | A | `tests/test_f15_followup.py` 24 tests, red on `177e7f0` and on each review round's commit before its fix; census declared first, no move; Claude review round 3 "ship"; `make check` on `c1dc011` and `make verify-feature F=F15` in the contract, "Path-rule ruling — results" |
| Agent understandable | A | the comment states the ruling, the language segment's shape and the cases it still takes (`/hi-fi/`) |
| Test stability | A | loopback pages; no network in tests; no timing dependence |
| Architecture boundaries | A | `make check-arch` 3/3; reuses `hreflang_checker`'s code tables, no new module |
| Code conventions | B | ruff clean; the script list (Hans, Hant, Latn, Cyrl) is a regex alternation, which `audit_derived_sets` does not count as a set |

## `font_audit.py` and `citation_readiness.py` (the owner's rulings on batch 7's questions) — graded 2026-11-12, F15 follow-up

Read for the grade: `font_audit.py` (`ICON_FONT_FAMILIES`, `WHOLE_NAME_ONLY`, `icon_font`), `citation_readiness.py`
(`utility_page`), `tools/build_checklist.py` (`MEASURES` for TECH-002, GO-145, GEO-005).

| Dimension | Grade | Basis |
|---|---|---|
| Verification passing | A | `tests/test_f15_followup.py` 15 tests, red on `6e79108` and on each review round's commit before its fix; five census runs, each declared first, none moving; Claude review round 5 "ship"; the final `make check` and `make verify-feature F=F15` in the contract, "Follow-up — results" |
| Agent understandable | A | each family group names the CSS it comes from and the round that added it; the path rule's comment states the ruling and its language-prefix consequence |
| Test stability | A | loopback pages; no network in tests; no timing dependence |
| Architecture boundaries | A | `make check-arch` 3/3; no new module or import |
| Code conventions | A | ruff clean; `ICON_FONT_FAMILIES` and `WHOLE_NAME_ONLY` read by a test (`audit_derived_sets`); no new verdict-deciding number |

## `skills/seo-checklist/scripts/` (Search Console and the links export) — graded 2026-11-11, F15 batch 7

Read for the grade: `gsc_cannibalization.py` (`analyze`, the brand that sets queries aside; `_inferred_brand` gone),
`gsc_links_csv.py` (`load`/`pick`, the single-CSV guess, `analyze`'s sort and absent keys), `gsc_checker.py`,
`gsc_sitemap_reconcile.py` (read for their sentences), `font_audit.py` (`ICON_FONT_FAMILIES`, `icon_font`,
`local_only`), `css_minify_check.py` (`own_sheet`, the landed URL), `tools/build_checklist.py` (`MEASURES`).

| Dimension | Grade | Basis |
|---|---|---|
| Verification passing | A | `make check` on `d281c6e` and `266127e` (ci_local 27/27, check-arch 3/3, vcr red by design); `make verify-feature F=F15` on `266127e`, all three layers PASS, 3439 tests; 37 tests in `tests/test_f15_batch7.py`, each review round red on the commit before it; five census runs, each declared first, none moving; Claude review round 5 "ship" |
| Agent understandable | B | each rule names its ruling and the round that shaped it; the links export's guesses (a named file with no count column, a lone CSV) need their comments to be read right |
| Test stability | A | Search Console stood in by `_Query`; loopback pages; exports written to temp directories; no timing dependence |
| Architecture boundaries | A | `make check-arch` 3/3; `css_minify_check` imports the runner's `registrable_domain` rather than a third copy |
| Code conventions | A | ruff clean; `ICON_FONT_FAMILIES` held by a test (`audit_derived_sets`, unread closed sets 0); no new verdict-deciding number (139) |

## `skills/seo-checklist/scripts/` (security, speed and technical) — graded 2026-11-10, F15 batch 6

Read for the grade: `domain_safety_check.py` (`crawled_urls`, `check_safe_browsing`), `security_headers.py`
(`hardening_gaps`, `_csp_weakness`), `ga4_tag_checker.py` (`installed_by`, `pageview_ids`, `strip_inert_scripts`,
container loads), `html_validator.py` (`with_doctype`), `mobile_render_checker.py` (`phone_css`, `_wide_only`),
`favicon_check.py` (per-origin robots.txt), `a11y_seo_checker.py` (`accessible_name`, `_hidden`, `_text`),
`css_minify_check.py` (`RE_IMPORT`, unread sheets), `third_party_script_audit.py` (`_classic_script`),
`critical_request_chain.py`, `font_audit.py`, `citation_readiness.py` (`utility_page`), `checklist_runner.build_plan`
(`--inventory` dropped where no crawl was read).

| Dimension | Grade | Basis |
|---|---|---|
| Verification passing | A | `make check` on `78fc08d` (ci_local 27/27, check-arch 3/3, vcr red by design); 101 tests in `tests/test_f15_batch6.py`, each review round red on the commit before it; fourteen census runs, each declared first (run 1 missed went-down's moves, recorded); Claude review round 13 "ship" |
| Agent understandable | B | each rule names its item and the round that shaped it; GO-132's split between what is installed (the whole page) and what is counted twice (without serialised copies), and the slug vocabulary, are readable only with their comments |
| Test stability | A | loopback pages; Safe Browsing, Nu and GTM containers stood in or mocked; no timing dependence |
| Architecture boundaries | A | `make check-arch` 3/3 |
| Code conventions | A | ruff clean; new sets held by `TheSetsAreHeld`; one new verdict-deciding number (`SB_MAX_ENTRIES`, a standard: 139) |

## `skills/seo-checklist/scripts/` (structured data and content) — graded 2026-11-10, F15 batch 5

Read for the grade: `schema_required_props.py` (`missing_rich_result_props`, `value_ok`, `find_schema_nodes`,
`validate_schema_required_props`), `rich_results_guard.py`, `video_schema_checker.py` (`page_videos`, `_widget`),
`local_seo_checker.py` (`nap_gaps`), `lib/schema_types.py` (`schema_org_name`, `markup_types`), `site_crawl.py`'s
`schema_nodes`, `answer_block_scanner.py` (`_asks_a_question`, `_is_definition`, `_is_menu`), `citation_readiness.py`
(sources), `eeat_signal_checker.py`, `freshness_checker.py` (`shown_dates_in`, `labelled_publications`, the furniture
reading), `entity_checker.py` (resolution), `article_seo.py` (`body_copy`, `_names_content`), `social_meta.py`,
`collection_page_checker.py`, `hreflang_checker.py` (`self_only`), `seo_common.py` (`visible_text`, `shown_in`,
`in_page_furniture`).

| Dimension | Grade | Basis |
|---|---|---|
| Verification passing | A | `make check` on `1b24a6b` (ci_local 27/27, check-arch 3/3, vcr red by design); 116 tests in `tests/test_f15_batch5.py`, each review round red on the commit before it; twelve census runs, each declared first, each matched; Claude review round 11 "ship" |
| Agent understandable | B | each rule names its item and the round that shaped it; CN-056's "the page's own dates" and the definition and source readings are heuristics stacked over eleven rounds, readable only with their comments |
| Test stability | A | loopback pages and crawls; lookups mocked; two timing guards with wide margins |
| Architecture boundaries | A | `make check-arch` 3/3 |
| Code conventions | A | ruff clean; new sets held by `TheSetsAreHeld`; one new verdict-deciding number (`DEFINITION_TERM_MAX_WORDS`, a convention: 138) |

## `skills/seo-checklist/scripts/` (robots, sitemaps, redirects, URLs) — graded 2026-11-10, F15 batch 4

Read for the grade: `robots_checker.py` (`correctness_problems`, `crawled_paths`, `main`), `lib/robots_rules.py`
(`parse`), `robots_path_tester.py` (`css_imports`, `discover_assets`, `probe_url`, `test_paths`), `sitemap_checker.py`,
`seo_common.py` (`_sitemap_problems`, `google_robots_directives`), `indexability_matrix.py` (`snippet_controls`),
`redirect_checker.py` (`walk`), `gsc_url_inspection.py`, `hreflang_checker.py` (`validate_lang_code`,
`check_return_tags`, `run_hreflang_check`), `faceted_nav_audit.py` (`_facet_items`, `_spelling`, `audit`),
`indexnow_checker.py` (`check_key_file`), and the batch-3 readers rulings 1 and 3 touched (`canonical_checker.py`,
`link_profile.py`, `topical_cluster_mapper.py`, `site_crawl.py`'s `robots_blocked_urls`).

| Dimension | Grade | Basis |
|---|---|---|
| Verification passing | A | `make check` on the batch's last commit (contract, batch 4 results); 83 tests in `tests/test_f15_batch4.py`, each review round red on the commit before it; 31 reverts of the batch's fixes each caught; Claude review round 7 "ship" |
| Agent understandable | B | each rule names its item and the round that shaped it; AR-163's redirect control took four rounds (redirect away, another spelling, kept facet or query parameters) and now rests on two small helpers whose interplay is the rule |
| Test stability | A | loopback sites and hand-built inventories; the two repeated-header tests patch `fetch_url` to report two `X-Robots-Tag` values, which a served route cannot send |
| Architecture boundaries | A | `make check-arch` 3/3 |
| Code conventions | A | ruff clean; derived sets and the threshold ledger moved only by declared constants (`MIN_PAGES_FOR_HUBS`, `MIN_PAGES_FOR_AVERAGE`, `MAX_STYLESHEETS_READ`, `SCRIPT_ADVICE`, `_RULES_WITH_ARGUMENT`) |

## `skills/seo-checklist/scripts/` (crawl inventory readers) — graded 2026-11-10, F15 batch 3

Read for the grade: `site_crawl.py` (`page_key`, `_reduced`, `read_twice`, `same_page`, `_linked_spellings`,
`_finish`), `duplicate_content.py` (`pages_from_inventory`, `_snippet_grouping_pages`, `detect_duplicates`),
`canonical_checker.py` (`check_canonicals`, `_consolidated`, `check_inventory`), `link_profile.py`,
`internal_links.py`, `topical_cluster_mapper.py` (`map_inventory`), `anchor_text_audit.py` (`names_its_title`,
`audit_anchor_text`), `server_log_audit.py` (`_key`), `gsc_sitemap_reconcile.py`.

| Dimension | Grade | Basis |
|---|---|---|
| Verification passing | A | `make check` on the batch's last commit (contract, batch 3 results); 82 tests in `tests/test_f15_batch3.py`, each review round red on the commit before it; Claude review round 9 "ship" |
| Agent understandable | B | each rule names its item and the review round that shaped it; the self-canonical and BL-081 decisions now span several small guards (aliases, `read_at`, title anchors, pager and alt links) whose order matters, and their limits are listed in the contract rather than in one place |
| Test stability | A | hand-built inventories and loopback crawls; no clock or network outside loopback |
| Architecture boundaries | A | `make check-arch` 3/3 |
| Code conventions | A | ruff clean; derived sets and the threshold ledger moved only by declared constants (`PAGE_NUMBER_PARAMS`, `CANONICAL_ARGS`, `NEAR_DUPLICATE_SIMILARITY`, the MinHash pair) |

## `skills/seo-checklist/scripts/` (images, rendered page, PageSpeed) — graded 2026-11-09, F15 batch 2

Read for the grade: the rendered-page snippet in `SKILL.md` (`rgb`, `bgOf`, the contrast and link loops),
`rendered_audit.py` (`read`, `WITHHELD_BESIDE`), `pagespeed.py` (`_above_fold`, `field_cwv_verdict`),
`image_inventory.py` (`inventory`, `_first_candidate`), `image_weight_audit.py` (`_responsive`, `_classify_image`,
`audit`), `seo_common.py` (`image_carries_meaning`, `_in_furniture`, `_real`, the noscript twins).

| Dimension | Grade | Basis |
|---|---|---|
| Verification passing | A | `make check` on the batch's last commit (see the contract's batch 2 results); 73 tests in `tests/test_f15_batch2.py`, each review round red on the commit before it; Claude review round 9 "ship" (Codex was out of credits) |
| Agent understandable | B | each rule names its item and the review round that shaped it; the snippet's link loop and `_responsive`'s source order are small but dense, and the heuristics they settle on (running text, what a phone matches) are listed as limits in the contract rather than in one place in the code |
| Test stability | A | pure functions and a Node stand-in DOM; skipped where `node` is absent (CI has it) |
| Architecture boundaries | A | `make check-arch` 3/3 |
| Code conventions | A | ruff clean; derived sets and the threshold ledger moved only by declared constants (`MEANINGFUL_IMAGE_MIN_PX`, `UNTYPED`, `FIELD_PASS_NEEDS`, `WITHHELD_BESIDE`, the landmark tuples) |

## `skills/seo-checklist/scripts/` and `tools/audit_item_readings.py` — graded 2026-11-09, F15 batch 1

Read for the grade: `parse_html.py` (meta loop, `_breadcrumb_markup`, `_item_parts`, `_is_trail_entry`,
`_has_trail_entry`, `_node_id`, `_same_page`, pagination), `javascript_render_audit.py` (`_directives`, `summarize`),
`seo_common.py` (`document_title`, `url_host`, `favicon_href`, `parse_html`'s meta join), `tools/audit_item_readings.py`
(`stale_second_readings`, `second_readings`), `tools/build_checklist.py` (CI-004, MS-020, `MEASURES`).

| Dimension | Grade | Basis |
|---|---|---|
| Verification passing | A | `ci_local` 27/27 on `1cc00e5` (2026-11-09, Tests 574 s); 54 tests in `tests/test_f15_batch1.py`, each round red on the commit before it; Codex's eleventh round "ship" |
| Agent understandable | B | each helper names the item and the review that shaped it; AR-158's entry rules (Microdata, RDFa, JSON-LD `@id`, `itemref`) are now a small reader of three syntaxes in one script, which a reader has to hold together |
| Test stability | A | pure functions over HTML strings; the render tests write one temporary artifact |
| Architecture boundaries | A | `make check-arch` 3/3 |
| Code conventions | A | ruff clean; `tests/derived-sets.json` moved only by `MEASURES` (31 → 38) |

## `skills/seo-checklist/tools/` and `scripts/verify-feature.sh` — graded 2026-11-08, audit-fix batch P3

Read for the grade: `calibrate_css_minification.py` (`_reads_minified`, `_misreads`, `_fewest_jointly`,
`check_report`), `calibrate_font_weight.py` (`_empty_band`, `check_report`), `calibrate_paragraph_words.py`,
`calibrate_profile_detection.py`, `calibrate_serp_length.py` and `calibrate_gsc_sample_floors.py` (`check_report`),
`calibration_common.thin_corpus`, `corpus_fetch.py`, `audit_score_sensitivity.py`, `scripts/verify-feature.sh`, and in
`scripts/checklist_runner.py` `stored_run`, `same_audit`, `previous_run`, `run_series`.

| Dimension | Grade | Basis |
|---|---|---|
| Verification passing | A | `ci_local` 27/27 on `e3daacc` (2026-11-08, 607 s); 30 tests in `tests/test_audit_fixes_p3.py`, every fix red on the commit before it; Codex's third pass left one point, the `MIN_SCORE` divergence, closed after 0.178.0 by the owner's ruling (`--check` fails it, red-first) |
| Agent understandable | B | each check prints what holds its constant (band, misreads, measured capacity, precision rule) or that it is judgement; `_reads_minified` mirrors `looks_minified` and is held to it by a test, a second copy of one rule |
| Test stability | B | pure functions over copies of the committed reports; one runner subprocess against a served fixture; the verify-feature tests need `bash` and `jq` on PATH |
| Architecture boundaries | A | `make check-arch` 3/3 |
| Code conventions | A | ruff clean; no new upper-case module constant (`tests/derived-sets.json` unchanged) |

## `skills/seo-checklist/scripts/` — graded 2026-11-08, audit-fix batch P2 (canonical, noindex, sitemap names, orphans)

Read for the grade: `seo_common.py` (`comparable_url`, `google_robots_rules`, `google_noindex`, `_link_canonicals`,
`declared_canonicals`, `parse_html`'s canonicals, `fetch_url`'s `x_robots_tags`), `lib/safe_http.py` (`header_values`,
cache entry version 2), `canonical_checker.py` (`check_canonicals`), `indexability_matrix.py` (`evaluate`),
`sitemap_checker.py`, `link_profile.py`.

| Dimension | Grade | Basis |
|---|---|---|
| Verification passing | A | `ci_local` 27/27 on `b598ab9` (2026-11-08, 605 s); every fix red on the commit before it (52 tests in `tests/test_audit_fixes_p2.py`); Codex's fifth pass "ship" |
| Agent understandable | B | each helper cites the Google or RFC text it follows; `comparable_url` leans on requests' `prepare()`, so what "the same URL" means lives partly in a dependency |
| Test stability | B | one test bounds time (1 s for 100,000 `<` in a Link header, linear in practice); the rest are pure functions over fakes |
| Architecture boundaries | A | `make check-arch` 3/3 |
| Code conventions | A | ruff clean; no new module constant left unread (`tests/derived-sets.json` unchanged) |

## `skills/seo-checklist/scripts/` — graded 2026-11-08, audit-fix batch P1 (robots.txt and sitemap reading only)

Read for the grade: `lib/robots_rules.py` (`_matches`), `lib/safe_http.py` (`_fetch_robots`), `seo_common.py`
(`robots_unread`, `fetch_url`'s `keep_body`, `sitemap_document`, `parse_sitemap_xml`), `indexability_matrix.py`,
`ai_crawler_policy_matrix.py`, and the sitemap reads of `sitemap_checker.py` and `site_crawl.py`.

| Dimension | Grade | Basis |
|---|---|---|
| Verification passing | A | `ci_local` 27/27 on `9c82e20` (2026-11-08, 629 s); every fix red on the commit before it; Codex's third pass "ship" |
| Agent understandable | B | each fix says why in its comment and in HTTP-5/HTTP-10; `fetch_url`'s `keep_body` is one more option a reader must know sitemaps need |
| Test stability | B | two tests bound time (1 s for a hostile rule) and two bound memory (16 MB peak); generous margins, but timing and tracemalloc depend on the machine and urllib3 |
| Architecture boundaries | A | `make check-arch` 3/3 |
| Code conventions | A | ruff clean; no new module constant left unread (`tests/derived-sets.json` unchanged) |

The rest of `scripts/` is not graded.

## `skills/seo-checklist/tools/` — graded 2026-11-08, F03 batch 5 (`audit_item_readings.py`, `second-reading-brief.md` and `item-readings.json` only)

| Dimension | Grade | Basis |
|---|---|---|
| Verification passing | A | `tests.test_item_readings` 60/60; `--check` exit 0 with all 145 second readings current (batch 5, no code change; batch 4's 5 of 5 mutations red, its review fix red first); Codex's review of batch 5's records: ship |
| Agent understandable | A | the docstring and brief say what the reader is shown — the rendered-page snippet, `site_crawl.py` for the crawl inventory's eleven readers, the evaluator and its severity alias — and what the digest leaves out (helpers, the brief); `cwv_metrics.py`'s missing producer is stated with its reason |
| Test stability | A | pure functions over deep copies of the shipped files; temp copies of `scripts/` and `SKILL.md` for the digest tests; one subprocess per CLI test |
| Architecture boundaries | A | `make check-arch` 3/3 |
| Code conventions | A | ruff clean; no command writes the readings file |

Only these files were read for the grade; the rest of `tools/` is not graded. What the readings file holds is graded by no row here: 112 of its 145 second readings dispute the first, and those wait for the owner (`docs/sprint-20261108-F03-5.md`).
