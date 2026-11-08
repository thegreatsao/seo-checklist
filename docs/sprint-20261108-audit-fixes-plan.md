# Audit fixes of 2026-11-04 — plan (findings 1–20)

The owner, 2026-11-08: "Чини 1-20 сабчатами" — fix all twenty findings of the second repo audit, in separate
sessions. The audit read snapshot `d1424fd` plus `~/Claude/seo-web`; its findings were reproduced by fresh-context
Claude reviewers (Codex was out of credits). The full text of each finding is in the workspace handoff,
`~/Claude/Advanced SEO - Plugin/HANDOFF.md`, section "2026-11-04 20:18", part 6. This file is the state; the
batch rows below are updated by the session that runs them.

## Rules for every batch

- One fresh session per batch. Plugin batches run one after another on `main` in `~/seo-checklist-release`
  (they share `tests/census.json`, the fixture expectations, KNOWN-ISSUES and CHANGELOG); the seo-web batch runs
  in parallel in its own repository.
- Red first: a test that fails on the current code, then the fix, then green. Every fix that moves a registry
  verdict updates `tests/census.json` and `tests/fixtures/expectations.json` in the same commit, with the moved
  rows declared before the run (AGENTS.md).
- F03 stays `active` and its state is not touched: do not change `feature_list.json` states. A fix that changes a
  script whose source is in a second reading's digest leaves that reading stale; never re-enter `read` from
  `--digest`. List each stale reading in the batch row for the owner.
- Review: Codex (`-m gpt-6.1-sol -c model_reasoning_effort=high`, brief in a file, stdin from the file). If Codex
  answers "out of credits", a fresh-context Claude agent reviews instead; say which one did.
- Heavy runs under `nice -n 15`, one suite at a time; commit before mutation scripts.
- No push, no tag, no version bump: release is a separate step the owner asks for.
- At the end: `ci_local` + `check-arch` (VCR is red by design while F03 is active), this file's row, the repo
  `HANDOFF.md`, a local commit. Then start the next plugin batch as a new session from its row below; if the app
  refuses, say so in the report.

## Batches

| batch | where | findings | state |
|---|---|---|---|
| W | `~/Claude/seo-web` | 1 NUL in a URL wedges a job `running` (`server.py:98-102, 384-385, 413, 447-449`); 3 `engine.sb` allows Unix sockets (tmux escape), signals and `/private/tmp`; 4 (service half) no memory limit on a job; 13 the jailed engine writes the folder unjailed code trusts (`job.json.tmp`, report symlinks, unescaped score at `server.py:1066`); 14 per-IP limit per full IPv6 address (`server.py:1111`); 15 a dead worker leaves its audit alive without a deadline (`server.py:414, 139-141`); 20 `local/server.log` unbounded, fed before Turnstile, keeps URLs (`server.py:1208`) | done 2026-11-08: seo-web 368d16f (local, unpushed); 1, 3, 4 (service), 13, 14, 15, 20 fixed red-first; 51 tests OK; Codex 2 passes; live: restart ok, two real audits done; not closed: a hijacked engine can setsid() out of the memory/deadline/recover bounds (needs a VM or another user); recover() misses a group where only whois survived; local/engine-home shared and writable; /private/var/folders not closed in engine.sb |
| P1 | `~/seo-checklist-release` | 2 robots wildcard regex backtracks (`lib/robots_rules.py:111-117`); 4 (engine half) robots.txt read whole before its cap (`lib/safe_http.py:513-532`, stream to `ROBOTS_MAX_BYTES`); 5 an unread robots.txt (5xx, 429, no answer) reads as no rules (`indexability_matrix.py:164-173`, `ai_crawler_policy_matrix.py:81,125`); 6 sitemap parsing: gzip by content bytes, catch `ValueError, LookupError, OSError, EOFError, zlib.error`, no mojibake (`seo_common.py:440, 1244-1255`) | done 2026-11-08: `2951b86`, `059ed5b`, `9c82e20` (local, unpushed); 2, 4 (engine half), 5, 6 fixed red-first (red on `dec5aa2`: 2 one hostile rule 5.2 s; 4 a 64 MB gzip bomb peaked at 138 MB; 5 all four unread cases (503, 500, 429, no answer) read as no rules; 6 gzip as `application/gzip` invalid in all three walkers, Shift_JIS and bad gzip raised, latin-1 mojibake); census and expectations: no row move declared before the run, none moved (census step green); Codex 3 passes: fix first (5: redirect body read before the cap, urllib3 floor, matcher still quadratic, a bad `<loc>` raised, gzip BOM overruled) → fixed, red-first where testable; fix first (2: HTML sniffer read `<meta charset>` in XML, missed a long declaration) → fixed; ship; `ci_local` 27/27 on `9c82e20` (629 s, Tests 564.5 s), `check-arch` 3/3; stale second readings: none (29 of 145 current; no script backing one changed, helpers are outside the digest); not closed: the `urllib3>=2.6.0` floor is held by no test; UTF-32 sitemaps unread (inherited) |
| P2 | `~/seo-checklist-release` | 7 `sitemap_checker.py:129-137,168,263` guessed names on a catch-all site, GO-138 truncation past `--max-urls`; 8 CI-001/CI-009 misreads (raw UTF-8 self-canonical, `googlebot` meta, agent-scoped X-Robots-Tag, `Link` header, `rel="Canonical"`, conflicting canonicals: `indexability_matrix.py:193-197`, `seo_common.py:1028`, `canonical_checker.py:30-35`); 9 CI-011 cannot see noindex + canonical elsewhere (`canonical_checker.py:36-47`, registry, census); 16 orphan count both ways (`link_profile.py:72-73,109-113`) | — |
| P3 | `~/seo-checklist-release` | 10 history compares unlike runs and a bad file loses the run (`checklist_runner.py:2352-2570, 4326`); 11 calibration from an empty corpus overwrites the report and `--check` stays green (`calibrate_profile_detection.py:196-251`, `calibrate_paragraph_words.py:155-177`); 12 font and five CSS constants compared with themselves (`calibrate_font_weight.py:173,229-235`, `calibrate_css_minification.py:290-341,516`); 17 `audit_score_sensitivity.py:98-108` ignores `scores_with` twins; 18 `scripts/verify-feature.sh` writes `passing` on a blank command and reports it when `jq` could not write; 19 `corpus_fetch.py:44-52` caches an error page | — |

Done = all four rows committed with their tests, each finding either fixed or stated as not fixed with the reason;
the owner then decides on a release (plugin) and on a `./serve.sh restart` already done for seo-web.
