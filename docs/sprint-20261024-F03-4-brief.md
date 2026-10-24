# F03 batch 4 — the brief for the session that runs it

Written at the end of batch 3 (`docs/sprint-20261024-F03-3.md`, results there). Plan: `docs/sprint-20261023-F03-plan.md`.
The owner's rule holds: batch 4 starts in a fresh session, and only on the owner's reply.

## Where batch 3 left it

- `second readings: 29 of 145 current — 8 agree, 21 disputed` (`parse_html.py`, `rendered_audit.py`, `pagespeed.py`
  done); 116 items in 54 scripts left. `--check` exit 0.
- The blind input shows the `SKILL.md` snippet for the three scripts that read `{rendered_json}`; the digest covers
  the script's source and its producer and is the one `--blind` writes to stderr when the prompt is printed.
- Calibration holds by the owner's scoring; its caveat: only one of seven controls was undisputed, so it says little
  about false alarms.

## Do first, red-first, before any reading of the affected items

1. **The crawl inventory's producer.** `{inventory_json}` is written by `site_crawl.py` and read by eleven scripts
   behind eighteen items (by `check.args`, not by script: `image_weight_audit.py` has six items, one of them over
   the inventory). Give `PRODUCERS` a second kind of producer — a script in `scripts/`, or the function in it that
   writes the inventory — so `--blind` prints it after the reading script and the digest covers it. A guard test
   from the registry, like batch 3's for `{rendered_json}`: every script whose args name `{inventory_json}` has it.
2. **How an assertion is evaluated.** The reader took `none_severity: ["critical", "high"]` literally against issues
   at `error` (AR-146, CN-048) and was wrong: `checklist_runner.py:792` (`SEVERITY_ALIAS`) maps `error` to `high`,
   `warning` to `medium`. The brief must say how each assertion operator in the registry is evaluated, or point the
   reader at the evaluator in `checklist_runner.py` (it is in the scratch copy). A test that the brief names the
   alias. Then decide with the owner whether AR-146 and CN-048 are re-read (their records are current; the wrong
   claim is in the blind reasons, not in the open-pass disputes).
3. **`cwv_metrics.py` (3 items).** Its `{cwv_json}` is written by the agent from trace insights by hand
   (`SKILL.md` "Core Web Vitals from a local trace"): no code to show. Decide whether that section's steps are its
   producer (shown as text), or the items are read without one and the gap stated in the contract.
4. **Re-run calibration** on the same fourteen (two minutes) whenever the reader-facing text of the brief changes,
   as it will by 1–2; the bar as ruled (`docs/sprint-20261024-F03-3.md`, scope 3). If it fails, stop.

## Then the readings — about 40 items

By script, largest group first among those not blocked by 1–3: `domain_safety_check.py` 6, `image_inventory.py` 4,
`gsc_cannibalization.py` 4, `eeat_signal_checker.py` 4, `gsc_links_csv.py` 4, `security_headers.py` 4,
`hreflang_checker.py` 4, `gsc_url_inspection.py` 3, `robots_checker.py` 3, `url_quality.py` 3,
`javascript_render_audit.py` 3, then the inventory scripts once 1 is in (`image_weight_audit.py` 6,
`indexability_matrix.py` 5, `duplicate_content.py` 5, …). One Codex session per script group, blind then open.

## Recipe (batch 3's, which worked)

1. Commit the contract `docs/sprint-YYYYMMDD-F03-4.md` before `./init.sh` (`ci_local` moves untracked files away).
2. Scratch copy: `git archive HEAD skills/seo-checklist/scripts | tar -x -C <scratch>/tree --strip-components=3`.
3. Per group: `{ <brief up to "## Open pass">; audit_item_readings.py --blind ${=ids} 2> <group>-read.txt; } >
   <group>-blind.md` and `{ <"## Open pass" section>; audit_item_readings.py --open ${=ids}; } > <group>-open.md`
   (zsh: `${=ids}` splits the list).
4. From `<scratch>/tree`: `codex exec -m gpt-6.1-sol -c model_reasoning_effort=high -s read-only
   --skip-git-repo-check -C <scratch>/tree -o <answer> - < <group>-blind.md`; take `session id:` from its log; then
   `codex exec resume --skip-git-repo-check <session> -m gpt-6.1-sol -c model_reasoning_effort=high -o <answer> - <
   <group>-open.md`. Judge each run by its answer, not its exit code.
5. Enter each record from the answers with `read` from `<group>-read.txt` (batch 3 used a one-off script in the
   scratchpad; nothing in the repo writes `item-readings.json`), then `--check` exit 0 and the counts in
   `test_the_shipped_file_is_counted` and `test_the_summary_counts_second_readings`.
6. Check every dispute in source before listing it for the owner; mark it confirmed, fact-confirmed with the defect
   the owner's call, or refuted.
7. Codex reviews the batch's diff in a fresh session; fixes red-first; mutations one at a time under `nice -n 15`.
8. Clock out: `nice -n 15 make check` (`ci_local` and `check-arch` green; `make vcr` red by design while F03 is
   `active`), the plan row, `docs/quality-document.md`, `HANDOFF.md`, the batch-5 brief.

## Open for the owner (not this batch's to decide)

- The 21 disputes of batch 3 (`docs/sprint-20261024-F03-3.md`, "Disputes for the owner") — resolved in batch 6 by
  Q2's rule.
- `answers` → `measures` with a statement, or keep, for the `rendered_audit.py` items: MB-103, CN-035, CN-036 (from
  batch 2), now also CN-034, CN-051, MB-094, MB-108.
- MS-031 joins CI-004 and MS-028 as a confirmed defect (last keywords meta wins) — into F15, or its own fix.
