# F03 batch 5 — the brief for the session that runs it

Written at the end of batch 4 (`docs/sprint-20261108-F03-4.md`, results there). Plan: `docs/sprint-20261023-F03-plan.md`.
The owner's rule holds: batch 5 starts in a fresh session, and only on the owner's reply.

## Where batch 4 left it

- `second readings: 71 of 145 current — 20 agree, 51 disputed`; 74 items in 43 scripts left. `--check` exit 0.
- The blind input now shows `site_crawl.py` whole after any of the eleven scripts that read the crawl inventory
  (`PRODUCERS`, held from the registry by `test_every_script_reading_the_crawl_inventory_names_its_producer`), and
  the digest covers it. The brief names `evaluate()` and `SEVERITY_ALIAS` in `checklist_runner.py`.
- `cwv_metrics.py` is read without a producer: its input is typed from Chrome's trace insights and its docstring
  carries the shape (contract scope 3). Say so in the batch-5 contract when its three items are read.
- Calibration holds under the current brief (twice in batch 4); re-run it only if the reader-facing text changes.
- Batch 4's 30 disputes (24 confirmed, 6 fact confirmed) wait for the owner's ruling, like batch 3's. They change no
  item here.

## The readings — the remaining 74, which closes the reading part of F03

By script, largest group first: `image_weight_audit.py` 6, `duplicate_content.py` 5, `indexability_matrix.py` 5,
`canonical_checker.py` 3, `cwv_metrics.py` 3, then fourteen scripts of 2 (`answer_block_scanner.py`,
`citation_readiness.py`, `freshness_checker.py`, `ga4_tag_checker.py`, `html_validator.py`, `link_profile.py`,
`llms_txt_checker.py`, `local_seo_checker.py`, `redirect_checker.py`, `rich_results_guard.py`,
`robots_path_tester.py`, `schema_required_props.py`, `sitemap_checker.py`, `video_schema_checker.py`) and
twenty-four of 1. The scripts of one item may share a Codex session in groups of three to five, with no inventory reader
grouped with another (each prints all of `site_crawl.py`). `image_weight_audit.py`'s MB-096, MB-097 and MD-189 are
calibration pairs in their `v0.104.0` form; read them now as they stand.

## Recipe (batch 4's, which worked)

1. Commit the contract `docs/sprint-YYYYMMDD-F03-5.md` before any `ci_local` run (it moves untracked files away).
2. Reader's tree: `git archive HEAD skills/seo-checklist/scripts | tar -x -C <scratch>/tree --strip-components=3`.
3. Per group (batch 4's `run.sh`): the brief up to `## Open pass` + `audit_item_readings.py --blind ${=ids} 2>
   <group>/read.txt` → `blind.md`; the `## Open pass` section + `--open ${=ids}` → `open.md`; `codex exec -m
   gpt-6.1-sol -c model_reasoning_effort=high -s read-only --skip-git-repo-check -C <scratch>/tree -o <answer> - <
   blind.md`, then `codex exec resume --skip-git-repo-check <session> …` with `open.md`. Four groups in parallel
   took about four minutes. Judge each run by its answer, not its exit code; check every id in the command.
4. Enter from the answers (batch 4's one-off script: verdict from the blind answer, dispute from the open answer
   when not `none`, `read` from `read.txt`), then `--check` exit 0 and the two count tests moved.
5. Check every dispute in source before listing it: batch 4 used four Claude subagents, one per group set, each
   given the dispute file and told to mark confirmed / fact confirmed / refuted with `file:line` and a passing input,
   and spot-checked four of their claims itself.
6. Codex reviews the batch's diff in a fresh session; fixes red first.
7. Clock out: `nice -n 15 make check` (`ci_local`, `check-arch`; `make vcr` red by design while F03 is `active`), the
   plan row, `docs/quality-document.md`, `HANDOFF.md`. Then, by the plan's order, F03 goes `blocked` on F15, which
   repairs every confirmed defect and `measures` sentence of batches 3–5 as the owner rules them.

## Wait

- `pgrep -f ci_local.py` matches the shell that runs it: a wait loop on it never ends. Use
  `ps -axo command | grep -c "[t]ools/ci_local.py"` or wait on a stamp.
