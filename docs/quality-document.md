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

## `skills/seo-checklist/tools/` — graded 2026-10-23, F03 batch 2 (`audit_item_readings.py` and `second-reading-brief.md` only)

| Dimension | Grade | Basis |
|---|---|---|
| Verification passing | A | `tests.test_item_readings` 41/41; `--check` exit 0 in `ci_local`; 9 of 9 batch-2 mutations red |
| Agent understandable | B | the docstring says what the tool fails on and what it does not establish; the plan file carries F03's state; the brief does not yet show the code that produces the JSON a script like `rendered_audit.py` reads (batch 2's calibration) |
| Test stability | A | pure functions over deep copies of the shipped files; one subprocess per CLI test |
| Architecture boundaries | A | `make check-arch` 3/3 |
| Code conventions | A | ruff clean; no command writes the readings file |

Only these two files were read for the grade; the rest of `tools/` is not graded.
