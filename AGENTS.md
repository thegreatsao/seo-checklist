# seo-checklist-release

This is a Claude Code plugin (Python 3.11+, stdlib plus requests, bs4, lxml) that audits a website against a fixed
217-item SEO registry and writes a client-facing report. It is for whoever runs `/seo`: the same site gives the same
verdicts on every run, and an item it cannot decide says why instead of scoring.

This file is the router for any coding agent (Codex reads it directly; Claude Code reads it through
`CLAUDE.md`). It holds the invariants; details live in the files it links to.

## Startup Workflow (clock-in)

Before touching code:

1. `pwd` — confirm the working directory.
2. Read `HANDOFF.md` from the top: its first section is the current state. It is the owner's, git-ignored, and a
   link to his workspace; a fresh clone has none, and then `ROADMAP.md` and `KNOWN-ISSUES.md` are the state.
3. Read `feature_list.json` and find the feature in state `active`, if any.
4. `git log --oneline -5` and `git status --short`.
5. Run `./init.sh` (setup + `make check`). If the baseline is red, repair it before any new scope.

## State Files

| File | Holds |
|---|---|
| `HANDOFF.md` | Current state, open questions, queue, next steps (git-ignored, see clock-in step 2) |
| `ROADMAP.md`, `KNOWN-ISSUES.md` | The tree's own state; their numbers are held to the code by `tests/test_prose_counts.py` |
| `CHANGELOG.md` | One entry per release |
| `feature_list.json` | Every feature, its state, verification layers and evidence |
| `DECISIONS.md` | Non-obvious decisions with why and rejected alternatives |
| `docs/quality-document.md` | A/B/C/D grade per module |
| `.harness/traces/` | Session traces written by `scripts/session-trace.sh` |

## Working Rules

- **One feature at a time (WIP=1)**: only one feature may be `active`. Finish it to `passing` before activating the next.
- **Stay in scope**: touch only files the active feature needs. A gap noticed on the way goes to `DECISIONS.md` or a new feature, not into this one.
- **Granularity**: each feature must be completable in one session. If it spans sessions, split it.
- You MUST NOT edit a feature's `state` to `passing` by hand. Why: self-declared completion is the failure this harness exists to stop.
- You MUST NOT commit secrets. Why: git history cannot be cleaned, only keys rotated.
- Do not rush when running low on context: stop, update `HANDOFF.md`, commit a clean checkpoint. Skipping verification to finish is a failure, not a finish.

## Feature State Machine

`not_started → active → passing` (and `blocked`). No skipping states.

1. Write a sprint contract from `templates/sprint-contract.md` to `docs/sprint-YYYYMMDD-<id>.md`.
2. Set the feature's `state` to `active`.
3. Implement.
4. `make verify-feature F=<id>` — the script runs the layers and is the only thing that writes `passing` and `evidence`.
5. Score the result against `templates/evaluator-rubric.md`; every dimension must be A or B.

## Definition of Done

A feature is done only when runtime evidence passes — not when code is written or the agent is confident:

- [ ] Target behavior implemented
- [ ] All layers pass through `make verify-feature`
- [ ] Evidence recorded in `feature_list.json`
- [ ] `make check` exits 0 and the repo is restartable from `./init.sh`

## Verification Commands

```bash
./init.sh                     # setup + full check: the startup path
make check                    # full pipeline; the repo is in a consistent state only when it exits 0
make verify-feature F=<id>    # layered verification of one feature
make check-arch               # architecture rules from .harness/arch-rules.json
make e2e                      # layer 3, end-to-end
make clean-check              # clean-state check before ending a session
```

Project commands behind `make check`:
- `skills/seo-checklist/tools/ci_local.py` — runs the steps of `.github/workflows/ci.yml` on this machine: ruff, the
  unittest suite (~9 min), every `tools/audit_*` gate, the offline smoke runs, the live-fixture path. It has no
  list of its own; `--list` shows what it runs and skips. An unchanged tree is instant (stamp in `.git/`).
- `make lint` = `ruff check .`; `make test` = `python -m unittest discover -s tests`.
- Only CI runs the Python floor (3.11) and the Linux and Windows legs: green here does not promise green there.

### Three-layer verification

- **Layer 1 — syntax & static**: lint, type-check, build.
- **Layer 2 — runtime behavior**: tests that run the code.
- **Layer 3 — system confirmation**: end-to-end; the app starts and reaches its ready state, side effects are correct.

Layers must pass in order: do not proceed to layer N+1 if layer N fails. Layer 3 is required when a change crosses
component boundaries.

## Architecture Boundaries

| Path | Holds |
|---|---|
| `skills/seo-checklist/SKILL.md` | What the agent running `/seo` does; shipped |
| `skills/seo-checklist/scripts/` | `checklist_runner.py`, `checklist_report.py` and the evidence scripts; shipped |
| `skills/seo-checklist/tools/` | Generators and gates (`build_checklist.py`, `audit_*.py`, `ci_local.py`); not run by an audit |
| `skills/seo-checklist/resources/` | Agent lenses, config, i18n, playbooks, references |
| `tests/` | The unittest suite and the records the gates hold (`*.json`) |
| `openspec/specs/` | The specification, by capability; changes go through the `opsx` workflows in `.claude/` |

Grades per module: [quality document](docs/quality-document.md).

- The registry is generated: edit `tools/build_checklist.py`, never `checklist.json`.
- An assertion is written only against observed script output (`tools/probe_shapes.py`); absence is `NO_DATA`, not `PASS`.
`make check-arch` enforces the rules in `.harness/arch-rules.json`; a failure prints WHAT / WHY / FIX.
Review-to-automation promotion: every new error category caught in code review becomes a test in `tests/`, or a rule in
`.harness/arch-rules.json` when a grep can say it.

## Observability

- `make session-start TASK="..." FEATURES="<id>"` at the start, `make session-end OUTCOME=pass|fail|partial` at the end.
- Runtime signals (app started, app ready, error) go through `scripts/session-trace.sh signal`.
- The sprint contract states what "done" means before implementation; the evaluator rubric scores it after.

## Tools and Permissions

- Tool permissions for Claude Code live in `.claude/settings.json`. MCP servers the project uses are listed here: none.
- Destructive operations (deleting data, force-push, schema drops) need the owner's explicit approval.

## Commits and Docs

- One logical change per commit (atomic); the repo must be consistent after every commit.
- Commit messages explain why, not just what.
- Update docs in the same commit as the code they describe — no stale docs.
- A release is two commits: `X.Y.0 code: <what changed>`, then `X.Y.0: <same>; changelog, README`, with the version
  bumped wherever it is written (`git grep` the old one), and a tag `vX.Y.0`.
- `git config core.hooksPath .githooks` arms the pre-push hook, which runs `ci_local.py --pushed`.
- The repository is public: no client names, private paths, hosts or keys in any tracked file.

## End of Session (clock-out)

Before closing a session:

1. `make check`, then `make clean-check` (clean-state: build, tests, no debug artifacts, feature list, handoff).
2. Update `HANDOFF.md` (current state with commit hash and test count, next steps, blockers) using the `harness` skill.
3. Update `docs/quality-document.md` for the modules you touched.
4. Commit once the repo is in a safe state.

Periodic cleanup: once a week, sweep for structural drift — stale docs, dead code, rules that no longer fire.

## Escalation

- Architecture decision or unclear requirement: check `DECISIONS.md` and `docs/`, otherwise ask the owner.
- The same verification layer fails three times: record it in `HANDOFF.md` as a blocker and stop.
