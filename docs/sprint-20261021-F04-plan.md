# F04 plan — the partial requirements and DEC-1, one batch per session

**Feature:** F04 (ROADMAP "What 1.0 requires", item 3), state `active` until the last batch and the release.
**Rule from the owner (2026-10-21):** one batch per session — a batch is finished with its review and fixes, committed,
and the session stops; the next batch starts in a fresh session from this file. No version bump and no tag until the
last batch; then 0.176.0 is released locally in one go (version, CHANGELOG with every verdict move and the ledger
before/after, README counts, tag on the changelog commit, `make verify-feature F=F04`). Heavy commands (make test, make check,
ci_local, mutations, the reviewer's runs) run under `nice -n 15` (the owner, 2026-10-22; `taskpolicy -b` before it took
about 65 minutes a suite), one full run at a time; a single mutation runs only the named test module.

## The list, derived from the specs

From each `openspec/specs/*/spec.md` Appendix B row and `**Reader:**` line at `efce43e` (0.175.0), not from memory:
`spec_debt.py` read **158 requirements: 132 enforced, 21 partial, 1 none, 4 bounded**.

| spec | partial / none at `efce43e` |
|---|---|
| declarations | DEC-4, DEC-8, DEC-9 partial; **DEC-1 none** |
| evidence | EVD-1, EVD-2, EVD-10 |
| governance | GOV-2, GOV-3, GOV-5, GOV-6, GOV-7, GOV-12 |
| http | HTTP-10, HTTP-13 |
| inputs | INP-10 |
| operator-protocol | OPR-1, OPR-4 |
| registry | REG-1, REG-6 |
| verdicts | VRD-2, VRD-3 |

**REG-6 is out of scope**: it is F03's (a second reader of the item readings) and stays `partial`. F04's scope is the
other 20 partial and DEC-1: **21 requirements**.

## Batches, in order

| batch | requirements | contract | state |
|---|---|---|---|
| 1 | HTTP-10, HTTP-13, INP-10, EVD-10 (+ H13-c) | `docs/sprint-20261021-F04-1.md` | **done**: `4be01d8` (active + contract), `005886e` (code), `f831882` (review 1 fixes), `3d01157` (H13-c + this plan), review 2 fixes in the commit after it (see the contract) |
| 2 | EVD-1, EVD-2, VRD-2, VRD-3, REG-1 | `docs/sprint-20261021-F04-2.md` (`3e847cf`) | **done**: `33e96b7` (batch 1's suffix-list tests in UTC), `216e620` (code), `54916fb` (review 1 fixes), `a6b4853` (review 2 fixes), this plan in the commit after it; `make test` 2570 OK |
| 3 | DEC-1, DEC-4, DEC-8, DEC-9 | `docs/sprint-20261022-F04-3.md` (`f2fec34`) | **done**: `953c5a8` (code), `c82613c` (outcome and mutations), `b692b9d` (review fixes), `c5f0d23` (epoch read at the call: the first full run's one failure), this plan in the commit after it; `make test` 2584 OK |
| 4 | GOV-2, GOV-5, GOV-6 (GOV-3 begun, moved to 4b) | `docs/sprint-20261022-F04-4.md` (`d673af8`) | **done**: `905d362` (GOV-2, GOV-5, GOV-6), `3229589` (GOV-3's census widened, hreflang sets), `436a4c3` (outcome and mutations), `ef5ca4e` (review fixes), this plan in the commit after it; `make test` 2593 OK on `ef5ca4e` (717 s) |
| 4b | GOV-3 | `docs/sprint-20261022-F04-4b.md` (`75f3c9b`) | **done**: `454c37e`, `a61e85e`, `b3b8c68`, `81c46a1`, `8561cc0`, `8c06814`, `b05a06d`, `bd77ea0` (the owner's three rulings), `47500ec` (ledgers), `744c5a5` (census re-taken), `5949c15` (review 1 fixes), `de454ca` (outcome, review 1), `0024ece` (review 2 fixes), this plan in the commit after it; `make test` 2648 OK (6 skipped) on `0024ece` (741 s) |
| 5 | GOV-7, GOV-12, OPR-1, OPR-4 | to write | not started |
| release | 0.176.0 locally, `make verify-feature F=F04`, rubric | — | after batch 5 |

Spec debt after batch 1: **136 enforced / 17 partial / 1 none / 4 bounded**. After batch 2: **141 enforced / 12
partial / 1 none / 4 bounded** (`tests/spec-debt.json`); all five held in full, none narrowed. After batch 3:
**145 enforced / 9 partial / 0 none / 4 bounded**; DEC-9 held in full, DEC-1, DEC-4 and DEC-8 narrowed, each narrowing
said in its Reader line and filed in the contract's Outcome. After batch 4: **148 enforced / 6 partial / 0 none / 4
bounded**; GOV-2, GOV-5 and GOV-6 narrowed to the half a program reaches, each narrowing said in its Reader line;
GOV-3 still partial. After batch 4b: **149 enforced / 5 partial / 0 none / 4 bounded**; GOV-3 enforced, narrowed (an
open set's completeness is a convention; "read" for a closed set is a reader a person wrote; the census's blind spots;
a snapshot is right as of its date), said in its Reader line.

## Decisions already made

- **MD-184 and AR-153** were F06's (0.175.0), decided by the owner there; nothing in F04 reopens them.
- **H13-c** (a crawled page that gave no answer), the owner, 2026-10-21, "C: retry, then withhold": a page whose
  request timed out or whose connection was refused or reset is asked once more; silent twice, the crawl is `truncated`
  and counts it in `summary.unanswered_pages`, and the 14 inventory readers that pass by absence withhold PASS; FAIL and
  WARN stand; an HTTP status, a guard refusal, TLS and robots are not retried. Done in batch 1.
- Review is a separate Claude agent with a fresh context (`model: fable`), read-only, mutating in its own export and
  its own scratch subdirectory — not Codex (the owner's choice for F06, kept for F04).
- Each requirement is held in full where the gap is a defect a user would meet, or narrowed with the narrowed part
  named and filed; never narrowed when the gap is a verdict bug. `enforced` only on mutation evidence.
- **GOV-3 is its own batch, 4b** (the starting session, 2026-10-22, on the owner's one-batch-per-session rule): holding
  it means reading ~100 sets against their sources, and the first ones read that way move live verdicts.
- **schema.org type sets** (the owner, 2026-10-22, "Синхронизировать"): `LOCAL_BUSINESS_TYPES` and
  `ORGANIZATION_TYPES` are derived from a dated schema.org hierarchy snapshot, with a test holding them to it; each
  verdict move gets a red test first and a CHANGELOG line.
- **Any other closed set that is a standard vocabulary** — ISO, schema.org, IANA and the like (the owner, 2026-10-22,
  "То же правило"): synced to a dated snapshot of its source without asking him, red test, fix, CHANGELOG line. Ask
  only where the source itself is ambiguous.
- **Batch 4b's three rulings** (the owner, 2026-10-22, all "A", relayed by the starting session): **Q1** FAQPage and
  HowTo are synced to deprecated (FAQ rich results gone from 2026-05-07, How-to since September 2023); TECH-001 reads
  `summary.retired_types` (nodes of a deprecated or restricted type) so it keeps failing them, and TE-172 fails them
  as an error. **Q2** Dataset stays retired, with Google's 2025-11-05 wording ("only used by Dataset Search, and not
  Google Search") as the reason. **Q3** the three facet lists are one, `seo_common.FACET_PARAMS`: their union less
  `page` and `p`, which are pagination; pagination keys stay where a checker reads pagination.
- **An `Unreleased` CHANGELOG heading** (batch 4b's own call, for the release session to keep or fold): `bd77ea0`
  moved the registry, and `test_registry` requires the newest CHANGELOG entry to name the shipped registry version.
  With no version bump allowed before the release, `CHANGELOG.md` gained `## Unreleased — F04, until 0.176.0 is cut`
  naming `abf465b3f75d`; the 0.176.0 entry replaces it, written from the notes below.
- The reviewer rule is a fresh context, not a different model (the owner, 2026-10-22: "another agent without the old
  memory"); `fable` stays the named reviewer until he changes it.

## Open findings carried over

- Batch 2 (filed in its contract's Outcome and Review): `gsc_url_inspection.py` labels any `OSError` in one `try` —
  `build_service` and the inspection call — `input`, so a network timeout on the Search Console API reads as the
  operator's key file (`gsc_cannibalization` was repaired the same way in batch 2; this one was not its change).
  `measurement()` says `got 0` on an issue at an unknown severity where the verdict is `NO_DATA` (not graded).
  The EVD-2 scan does not read a severity table assembled key by key at run time.
- Batch 2, for the release CHANGELOG: eight checkers' "script failed" reads "an input this check was given could not
  be used" (label only); a model's `N/A` with no evidence is refused and the item stays `LLM_PENDING`; an issue at a
  severity outside the vocabulary (or `null`) reads `NO_DATA` naming it where it read `PASS` (no shipped checker
  writes one); `audit_assertions.py` refuses a rule naming such a word.
- Batch 3 (filed in its contract): DEC-1 does not hold whether a batch's `given` is the whole of what its session saw,
  an amended commit (declare, run, adjust, amend), or the 248 declarations before `BATCH_EPOCH`; DEC-4 does not hold
  that a reason names its tree, that its argument is true, or a run cited in words outside its list; DEC-8 does not
  hold a checker repaired under a standing declaration. Found on the way: a rule's `truthy: false` is read as
  `truthy` (`checklist_runner.py:1053` tests the key); no shipped rule writes it — a registry question.
- Batch 3, for the release CHANGELOG: **no verdict moves.** The manifest is `schema_version` 3: each declaration
  records `basis` (its item's title and rule as one digest), and `batches` records what each declaring session was
  given; `tests/test_fixture_oracle.py` refuses to run a declaration `HEAD` does not hold; three reasons lost
  "corrected from FAIL after the run"; ledger 141/12/1/4 → 145/9/0/4, DEC-1 no longer unread.
- Batch 1: the withheld evidence over a crawl cut by a refused or an unanswered page reads the readers' cap wording
  ("what the cap left out"); naming the cause needs the readers or the runner to carry it.
- Batch 4 (filed in its contract): GOV-2 does not hold an undefended number cited to a client, a basis stated in prose
  anywhere in the tree, or a defence phrased in words its search does not know; GOV-5 does not hold a person citing
  the record, and reads one level of import; GOV-6 reads the two declared sentences, not the rest of an audit's
  output. Found on the way: `test_known_issues`' quiet-on-record test fails when `test_prose_counts` runs first in
  the same process (`cache_dir_is_the_machine_temp_dir`), pre-existing on `HEAD` before the batch; the full suite
  runs them in the other order. `rich_results_guard`'s `Dataset` entry makes Dataset markup an error under item 172;
  whether it is right was not checked.
- Batch 4, for the release CHANGELOG: **no status moves.** `hreflang_checker.py` no longer reports a valid ISO 639-1 /
  ISO 3166-1 code as "Unknown language/region code" (High) — 76 languages and 50 regions were missing, the sets are
  now the IANA registry's (File-Date 2026-09-17) — and no longer refuses `LA` (Laos) as "Latin America";
  `summary.high` drops with it; no rule reads either. `SKILL.md` no longer tells the agent that no threshold is
  `measured` (14 are). The crawl caps' known-issues probe reads their basis lines. The derived-sets census counts
  `scripts/lib/`, sets inside functions and `frozenset({...})`: 183 → 209 sets, unread 80 → 99. Ledger 145/9/0/4 →
  148/6/0/4.
- Batch 4b (filed in its contract's Outcome and Review): `schema_required_props`' other tables (Article, Organization,
  LocalBusiness, … and the recommended rows of Product, Review, VideoObject) stay the open known issue
  `the_schema_property_tables_have_not_been_re_read`; `server_log_audit.AI_BOTS` is a separate list of User-Agent
  substrings, read; the nested-review exemption also accepts `reviews`, which is not a schema.org property
  (pre-existing, both checks alike); the validator labels a multi-typed node's errors with its first type; a node
  typed `["Product", "VideoObject"]` gets the shared `name` counted once by MS-032 and twice by TE-172 (both FAIL).
  The order-dependent `one-test-robots-answers-another` failure of `test_known_issues` (above, batch 4) also appears
  when `test_closed_sets` and `test_evidence_scripts` run before it in one process.
- Batch 4b, for the release CHANGELOG — **verdicts move**, each with a red test first:
  - **schema.org types derived from release 30.1** (2026-09-16, bundled, `tools/refresh_schemaorg_types.py`):
    LO-198 / LO-200 FAIL → PASS for a Hospital, Attorney, PostOffice, PoliceStation, FireStation, MedicalClinic,
    VacationRental or one of the 21 medical specialties; PASS → FAIL for a node typed only `VeterinaryCare` (a
    MedicalOrganization) or `SkatingRink` (no such type); GEO-006 collects `sameAs` from every Organization (188) and
    Place (230) type, not 5 and 2; CN-057 / CN-068 credit a Restaurant, Dentist, NGO, Store… publisher.
  - **retired schema types, one table** (`lib/schema_types.py`): TE-172 PASS → FAIL and TECH-001 stays FAIL on
    FAQPage and HowTo (owner, Q1); TECH-001 PASS → FAIL on SpecialAnnouncement, ClaimReview, Dataset, which it never
    read; TE-172 FAIL → PASS on markup typed `CourseInfo`, `EstimatedSalary`, `LearningVideo`, `VehicleListing` or
    `PracticeProblem`, which are Google feature names, not types. Registry `abf465b3f75d`: TECH-001 asserts
    `summary.retired_types eq 0`; its fix text and Russian translation changed. Corpus: TE-172 on `failing-shapes`
    PASS → FAIL (its HowTo).
  - **Google's required properties** (Product snippet, Video, Review snippet, Breadcrumb, read 2026-10-22), one table
    read by both checks: TE-172 and MS-032 FAIL → PASS on a Product with a rating or a review and no offer, a
    VideoObject without description, a review nested in its product; both FAIL on a required value that is only
    whitespace (TE-172 newly); MS-032 counts a VideoObject without description as one more warning.
  - **Search Console indexing states** (Google's page indexing report): CI-002 FAIL → PASS on "Indexed, though
    blocked by robots.txt"; NO_DATA → PASS on "Page indexed without content" and "Page is indexed"; NO_DATA → FAIL
    on "Server error (5xx)", "URL marked 'noindex'", "Alternate page with proper canonical tag", "URL is unknown to
    Google", with GO-135's critical "not indexed" issue.
  - **robots.txt fields**: AR-151 PASS → FAIL on a `Host:` line (no crawler documents it any more).
  - **facets** (owner, Q3): AR-154, AR-163, AR-155, CI-012 toward PASS on `?page=` / `?p=` URLs; toward FAIL where
    a URL carries a facet name only another checker had (url_quality gains rating, availability, material;
    faceted_nav category, tag; collection_page view, category, tag, rating, availability, material).
  - **fonts**: TECH-002 PASS → FAIL on a page preloading a `.ttc` font without `crossorigin`; a `.ttc` over 100 KB
    is a "large font" warning.
  - **AI crawlers, one list** (the policy matrix's 15): CI-019 asks about six more agents (moves only where
    robots.txt names one); robots_checker's `ai_crawler_status` gains Claude-User, Claude-SearchBot,
    Perplexity-User, Applebot and loses anthropic-ai, FacebookBot (output only).
  - **Output only**: `og:description` is not "required" (Open Graph's four are; MS-033's score does not move);
    IndexNow gains Yep, the Internet Archive, Amazonbot, and Yandex's host gains `www`; detect_profile drops the
    non-type `SaaSApplication` (no stored calibration site fired it); article_seo / parse_html's schema status
    follows the one table.
  - **Tools**: `audit_assertions.PATTERN_OPS` named two operators the runner lacks and missed `count_matching_lte`
    (no rule uses it); `spec_debt`'s row pattern reads `CLASSES`; `THIN_CONTENT_THRESHOLDS` deleted (four
    unreachable entries): counted thresholds 131 → 130, convention 97 → 96.
  - **GOV-3**: `tests/open-sets.json` records the 43 open sets with why; the census writes each reason and counts
    `unread_closed` (0, ceiling 0). Census 209 / 110 / 99 → 194 / 151 / 43. Ledger 148/6/0/4 → 149/5/0/4.
- Full-suite timing: `taskpolicy -b make test` took 67 minutes on 2026-10-22 (2569 tests), not ~9; budget for it.
  Batch 3's run of 2584 tests took 65 minutes. Under `nice -n 15` batch 4's 2593 took 12.6 minutes, 4b's 2648 12.4.

## Starting the next batch

```bash
cd ~/seo-checklist-release && git fetch && git status --short --branch
```

Batch 5 is GOV-7, GOV-12, OPR-1 and OPR-4 (`openspec/specs/governance/spec.md`, `openspec/specs/operator-protocol/`);
its contract is to write, from `templates/sprint-contract.md`, with expectations declared and committed before any
test is written (as `75f3c9b` did for 4b). It starts from 4b's last commit: spec debt **149 / 5 / 0 / 4** (`partial`:
GOV-7, GOV-12, OPR-1, OPR-4, and REG-6, which is F03's); the census at 194 sets, 151 read, 43 unread, all open
(`UNREAD_AT_MOST = 43`, `UNREAD_CLOSED_AT_MOST = 0`): a set batch 5 adds must be derived, read, or recorded open in
`tests/open-sets.json`. The registry is `abf465b3f75d` and `CHANGELOG.md` carries the `Unreleased` heading (above);
the release writes 0.176.0 from the batch notes in this file.

Lessons 4b paid for, for the next batch:
- A registry change moves five records at once — `tests/fixtures/expectations.json` (each moved item's `basis`, and
  `registry_version`, re-declared and committed before the oracle runs), `tests/census.json` and
  `tests/inert-findings.json` (re-taken with `tests/verdict_census.py --out` / `tests/inert_findings.py --out`, not
  edited), `resources/i18n/ru.json` (`tools/i18n_digest.py`), `tools/item-readings.json` — and a CHANGELOG entry
  naming the version. The first full run found three of them.
- A constant with a basis line moves `test_registry`'s totals too (the fifth ledger; `b05a06d`).
- One concept fixed in one copy leaves the other copy disagreeing (review 1's HIGH: MS-032 kept the rows TE-172 lost):
  grep the concept, not the name, before calling a duplicate unified.
- Do not edit test files while a full suite runs: the census reads the test corpus.

Read each requirement's Reader line and Appendix B row first, and check whether the line is stale
against the code before declaring — batch 2 found two Reader lines stale, batch 3 one (DEC-9), and both batches had
declared forms the measurement contradicted (4b: Place 209 declared, 230 real; two sets declared holding were
wrong). Confirm each mutation moved what it targets before reading a green
result (batch 3's first census mutation was a no-op). Then implement, mutate, ledgers together (`spec_debt.py --out` / `--check`,
ROADMAP table and item 3, `test_prose_counts`), `nice -n 15 make test` (about 10–15 minutes, with `run_in_background`), commit, review by a fresh
`fable` agent, fixes, commit, update this file, stop.
