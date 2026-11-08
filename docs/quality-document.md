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

## `skills/seo-checklist/tools/` — graded 2026-10-24, F03 batch 3 (`audit_item_readings.py` and `second-reading-brief.md` only)

| Dimension | Grade | Basis |
|---|---|---|
| Verification passing | A | `tests.test_item_readings` 54/54; `--check` exit 0 with 29 second readings current; 11 of 11 batch-3 mutations red |
| Agent understandable | B | the docstring and brief say what the reader is shown, including the rendered-page producer, and what the digest leaves out (helpers); the brief does not yet show the crawl inventory's producer or how an assertion operator is evaluated (`docs/sprint-20261024-F03-4-brief.md`) |
| Test stability | A | pure functions over deep copies of the shipped files; temp copies of `scripts/` and `SKILL.md` for the digest tests; one subprocess per CLI test |
| Architecture boundaries | A | `make check-arch` 3/3 |
| Code conventions | A | ruff clean; no command writes the readings file |

Only these two files were read for the grade; the rest of `tools/` is not graded.
