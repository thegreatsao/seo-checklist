# F05 plan — the unclaimed assertions, claimed by detectors, one batch per session

**Feature:** F05 (ROADMAP "What 1.0 requires", item 4), state `active` from batch 1, `passing` since batch 5's `make verify-feature F=F05` on `f5149a6`; the release is not done.
**Rule from the owner (carried from F04):** one batch per session — a batch is finished with its review and fixes,
committed, and the session stops; the next batch starts in a fresh session from this file. No version bump and no tag
until the last batch. Heavy commands (`make test`, `make check`, `ci_local`, mutations, the reviewer's runs) run under
`nice -n 15`, one full run at a time; commit before any mutation script (its `git checkout` restore wiped uncommitted
work once); a killed `ci_local` leaves `live.json` and `server.log` in the root, so stage named paths.

## The list, derived from the tool

Measured on `5bdba06` (0.176.2), 2026-10-23, from `audit_reachability.script_backed()` and `proofs()`, not from memory:
**145 script-backed assertions; 2 proved unable to report FAIL (TE-178 `path_never_emitted`, TE-179
`warn_complement`), both declared; 143 not claimed either way.** The tool's four detectors prove only *unable*; nothing
in it can say *able*, so every one of the 143 needs a claim of the other kind or a new proof of the first.

What each would need a detector to see, read against `tests/census.json` (the verdicts every served tree gave, which
the CI `census` job and `ci_local` re-derive from five audits and compare on every run), the fixture oracle
(`tests/fixtures/expectations.json`) and each script's source:

| group | n | what proves it | detector extension | batch |
|---|---|---|---|---|
| **A — seen to fail** | **116** | the recorded census holds a `FAIL` for the item on at least one served tree, through the registry's own arguments. 84 of them are also declared `FAIL` by the oracle and re-run by `make test` | `observed_failures`: read the census; a `FAIL` the runner gave is the claim. Plus the contradiction check: an item proved unable *and* seen to fail is a finding | 1 |
| **B — seen to fail, maybe by the gate** | 4 | CI-001, CI-003, CI-015, TE-167 carry `entry_answer`, so the runner's entry gate can write their `FAIL` without the assertion (`checklist_runner.py`, the entry-gate block). Their census `FAIL`s: CI-003 and TE-167 only where the entry fails (`error-entry`, and `no-location` for CI-003); CI-015 also on `fixture:broken` and `fixture:broken_tls`; CI-001 also there and on `page-defects` | the census records where each verdict came from (gate or assertion), or the detector reads the tree's entry status; then `observed_failures` claims the ones the assertion failed | 2 |
| **A′ — seen to fail, by the clock** | 1 | TECH-003 (`lcp_subparts.py`, `subparts.ttfb_ms`): census `FAIL` on `redirect-chain`, but the census check holds a `harness.CLOCK_READ` item's answer only as "timed", so the recorded `FAIL` is the recording machine's and nothing re-derives it. Found in batch 1: the classification above counted it in A | a served tree whose first byte is slow by construction (a delay the fixture server adds), so the `FAIL` is the tree's, and TECH-003 leaves `CLOCK_READ` for that tree, or the census holds it beyond "timed" | 2 |
| **C — the entry gate hides it** | 1 | SE-118 (`tls_certificate.py`, `valid` truthy): census `NO_DATA`/`PASS` only; the TLS failure stops the run at the gate | none in this tool: ROADMAP item 5 ("SE-118 needs the entry gate to answer it") owns it; `tests/test_entry_answers.py` is the reader of that mechanism | — |
| **D1 — PageSpeed** | 7 | MB-095, SP-107, SP-108, SP-111, SP-112, SP-113, SE-119 (`pagespeed.py`, `requires: api`): census `NO_DATA` everywhere, no key offline | a census tree serving a recorded PageSpeed response on loopback (the script's `PSI_API` constant needs an override under the offline switch), so the runner reaches the assertion with the registry's arguments | 3 |
| **D2 — HTML validator, Safe Browsing** | 5 | CI-017, TE-181 (`html_validator.py`); SE-114, SE-116, TE-171 (`domain_safety_check.py` `safe_browsing.threats`): refused under `SEO_LOOPBACK_ONLY` by design since F04-5 | as D1: a loopback stand-in per service, admitted by the offline switch only for the census | 4 |
| **D3 — Search Console** | 9 | CI-002, CI-010, GO-135 (`gsc_url_inspection.py`); MS-023, KW-070, KW-071, GO-139 (`gsc_cannibalization.py`); GO-134 (`gsc_checker.py`); GO-137 (`gsc_sitemap_reconcile.py`): census `NEEDS_INPUT`/`NO_DATA` | the scripts call `googleapiclient`'s `build_service`; a stand-in is a recorded discovery document plus responses, or an injected service under the offline switch. The largest of the four; may split | 5 |

116 + 1 + 4 + 1 + 7 + 5 + 9 = 143. **Why not source-shape proofs of reachability.** This tool's own history is the reason:
the retired fourth detector was wrong four times out of four reading values from source, and 0.50.0's `if fetch:` put
a failing severity in source that the registry's arguments never reached. A `FAIL` the runner gave on a served tree is
the one proof that takes the registry's own invocation into account, so every group above is claimed by a run, and the
groups that no offline run reaches (D) get a run they can reach rather than an argument.

## Batches, in order

| batch | groups | contract | state |
|---|---|---|---|
| 1 | A (116): `observed_failures`, the contradiction check, summary line, prose counts, REG-10 | `docs/sprint-20261023-F05-1.md` | **done**: `9f62895` (active + plan + contract), `f01fff8` (code), `3189206` (review fixes), this plan in the commit after it; 143 → 27 unclaimed; `make test` 2685 OK (6 skipped) on `f01fff8`; `ci_local` 27/27 on `3189206` |
| 2 | B (4) and A′ (1): verdict provenance in the census; a slow-by-construction tree | `docs/sprint-20261023-F05-2.md` | **done**: `fcb039e` (contract), `60ed85b` (code), `48fceed` (review: TE-167 by `went-down/`), this plan in the commit after it; 27 → 22 unclaimed; `make test` 2695 OK (6 skipped) and `ci_local` 27/27 on `48fceed` |
| 3 | D1 (7): PageSpeed stand-in | `docs/sprint-20261023-F05-3.md` | **done**: `1e3a62f` (contract), `c53765d` (code), `4268584` (review fixes), this plan in the commit after it; 22 → 15 unclaimed; `make test` 2707 OK (6 skipped) and `ci_local` 27/27 on `4268584` |
| 4 | D2 (5): validator and Safe Browsing stand-ins | `docs/sprint-20261023-F05-4.md` | **done**: `d73de17` (contract), `22b02a1` (code), `b32c0f6` (review fixes), this plan in the commit after it; 15 → 10 unclaimed; `make test` 2725 OK (6 skipped) on `22b02a1`; `ci_local` 27/27 on `b32c0f6` |
| 5 | D3 (9): Search Console stand-in (not split: one seam, `gsc_checker.build_service`) | `docs/sprint-20261023-F05-5.md` | **done**: `e6c9c16` (contract), `2845510` (code), `f5149a6` (review fixes), this plan in the commit after it; 10 → 1 unclaimed (SE-118); `make test` 2746 OK (6 skipped) and `ci_local` 27/27 on `f5149a6` |
| release | version, CHANGELOG, README, tag | — | **done locally, not pushed**: `7272960` (code: review fix), `8f53791` (0.177.0 changelog, README, versions; tag `v0.177.0`); `make test` 2748 OK (6 skipped) and `make check` exit 0 (`ci_local` 27/27, arch 3/3, VCR 1.0) on `8f53791`. F05's evidence stays `f5149a6`; verify-feature was not re-run |

## Done criterion — decided by the owner, 2026-10-23 ("Ruling Q2: A")

**F05 is done when `audit_reachability.py` prints at most 1 unclaimed assertion, and that one is SE-118 (ROADMAP item
5's).** Every claim is derived on each run from a record a gate re-derives (the census) or from source (the four
existing proofs); no claim is written by hand. Alternative, smaller: stop after batch 2 at **22 unclaimed**, every one
of them a credential-gated check, and narrow F05 in ROADMAP to "every assertion an offline run can reach", naming D1–D3
as waiting on stand-in services.

## Decisions already made

- **A FAIL the recorded census saw is F05's reachability proof** (the owner, 2026-10-23, "Ruling Q1: A"): batch 1 stays as built; later batches claim their groups by a run the census can reach, not by a source argument.
- **F05 is done at ≤1 unclaimed, and that one is SE-118** (the owner, 2026-10-23, "Ruling Q2: A"), with loopback stand-ins for PageSpeed, the HTML validator, Safe Browsing and Search Console in batches 3–5; the smaller alternative (stop at 22) is rejected.
- One batch per session, the plan file carries state (the owner's F04 rule, carried by the starting session).
- Only `make verify-feature F=F05` writes `passing`.
- Review is a separate Claude agent with a fresh context, read-only, in its own scratchpad subdirectory (`fable` stays
  the named reviewer until the owner changes it; the rule is a fresh context, not a different model).
- A detector that claims a real rule unable to FAIL is a finding, reported, never silently declared in `CANNOT_FAIL`.
- Every new claim is proven by a fixture rule the detector must classify, red before the extension, green after.

## Open findings carried over

- Batch 1 (filed in its contract's Review): `main()` reads the shipped census and harness whatever `--registry` says;
  `observed_failures()` returns `{}` silently on a census of another registry (the suite reddens, the tool's step
  does not). For the release CHANGELOG: no verdict moves; see the contract's last paragraph.
- Batch 2: nothing open. For the release CHANGELOG: no runner verdict moves; the census gains `entry_gated` and
  the `went-down/` tree; see the batch-2 contract's last paragraph.
- Batch 3: one low finding filed, not fixed (pre-existing): the console prints CrUX's CLS percentile unscaled (`38`
  for 0.38); no verdict reads it. For the release CHANGELOG: no verdict of a real audit moves; the census gains
  `slow-field/` and `fast-field/`; see the batch-3 contract's last paragraph. Batch 4 can reuse the mechanism: a
  script's stand-in variable in `checklist_runner.STAND_INS`, read under `loopback_only()` by the script and the
  runner's private-host gate, and an `_inputs/<tree>/` file `corpus_inputs` turns into it.
- Batch 4: one low finding filed, not fixed (a refused Safe Browsing stand-in carries no `error_kind`), and three
  pre-existing ones out of scope (Nu warnings counted as info; `check_safe_browsing`'s unguarded `resp.json()`; the
  public branch resolving the host under the switch). For the release CHANGELOG: no verdict of a real audit moves;
  the census gains `flagged/` and `cleared/` and its server answers a table POST; see the batch-4 contract's last
  paragraph. Batch 5 can reuse `verdict_census.STANDIN_INPUTS` (one line per stand-in file) and `_Quiet.do_POST`;
  the Search Console scripts call `googleapiclient`, not `safe_http`, so their stand-in needs a different seam.
- Batch 5: two low findings filed, not fixed (a census URL with userinfo would send its Basic credential to the
  stand-in, the audited origin; a `when` answer with no `else` resets instead of 404). For the release CHANGELOG: no
  verdict of a real audit moves; the census gains `unindexed/` and `indexed/`; see the batch-5 contract's last
  paragraph. F05 is `passing` (verify-feature on `f5149a6`); the one unclaimed assertion is SE-118.
- Release review (fresh-context Claude agent, read-only, on `5bdba06..865c3f2`, the first release commit, later
  rebuilt as `7272960` + `8f53791`). Nothing high.
  - **medium, fixed in `7272960`:** `pagespeed.py` sent the key to whatever endpoint it asked, the stand-in included;
    the suite clears `PAGESPEED_API_KEY`, but `env_loader` also reads `~/.agentic-seo/.env`, so every census run on
    `slow-field/`/`fast-field/` on such a machine sent the real key to the loopback tree server. Reproduced by the
    reviewer through `verdict_census.corpus_inputs` + `run_audit` with a fake key. F05-3's "low, no action" filing of
    this path was wrong: the suite and the census set the switch themselves. New test red before, green after.
  - **low, fixed in `8f53791`:** README's version line said four of the seven trees serve recorded answers (six do);
    the CHANGELOG heading said every claim is "by a run" (two are proofs from source).
  - **low, filed in the CHANGELOG entry:** `env_loader` copies any `.env` line into the environment, so a `.env`
    naming `SEO_LOOPBACK_ONLY` and a stand-in points that script at a local port; "never by a real audit" holds for
    the shell environment only. No key reaches a stand-in after the fix.
