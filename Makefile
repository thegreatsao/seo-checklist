# Thin wrappers over the repo's own commands; no check list lives here.
# `check` is tools/ci_local.py, which reads its steps out of .github/workflows/ci.yml.

PY := $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)

.PHONY: setup dev test format lint check clean vcr verify-feature check-arch e2e session-start session-end session-show clean-check

## setup — install dependencies and initialize the environment/database
setup:
	@[ -x .venv/bin/python ] || python3 -m venv .venv
	.venv/bin/pip install -q -r requirements.txt ruff pyyaml
	git config core.hooksPath .githooks

## dev — start the development server
dev:
	@echo "no dev server: a Claude Code plugin. Run an audit: $(PY) skills/seo-checklist/scripts/checklist_runner.py <url> (README, section Run)"

## test — run the full test suite
test:
	$(PY) -m unittest discover -s tests

## format — run the code formatter
format:
	@echo "no formatter: ruff is configured for lint only (pyproject.toml)"

## lint — Layer 1: lint, type-check, compile (exit non-zero on any violation)
lint:
	$(PY) -m ruff check .

## check — run the full verification pipeline (format check + lint + tests)
## This is the command the agent runs before declaring a task complete.
## Exit 1 on any failure — never silently pass.
check:
	$(PY) skills/seo-checklist/tools/ci_local.py
	@$(MAKE) --no-print-directory check-arch
	@$(MAKE) --no-print-directory vcr

## e2e — run end-to-end / system-level tests (Layer 3 of the verification hierarchy)
## Required when changes cross component boundaries (L10).
e2e:
	@echo "e2e runs inside make check: ci_local.py executes the smoke runs and the live-fixture path from .github/workflows/ci.yml"

## session-start — begin a session trace (L11)
## Usage: make session-start TASK="implement dark mode" FEATURES="F03 F04"
session-start:
	@if [ -z "$(TASK)" ]; then echo "Usage: make session-start TASK=\"description\" [FEATURES=\"F01 F02\"]"; exit 1; fi
	@bash scripts/session-trace.sh start "$(TASK)" $(FEATURES)

## session-end — close the current session trace
## Usage: make session-end OUTCOME=pass|fail|partial [NOTES="..."]
session-end:
	@if [ -z "$(OUTCOME)" ]; then echo "Usage: make session-end OUTCOME=pass|fail|partial [NOTES=\"notes\"]"; exit 1; fi
	@bash scripts/session-trace.sh end "$(OUTCOME)" "$(NOTES)"

## session-show — display the last N session traces (default 1)
## Usage: make session-show [N=3]
session-show:
	@bash scripts/session-trace.sh show $(or $(N),1)

## clean-check — run the idempotent session clean-state verifier (L12)
## Confirms: build passes, no debug artifacts, feature list state, HANDOFF.md updated, startup path exists
clean-check:
	@bash scripts/clean-state-check.sh .

## check-arch — run architectural constraint checks from .harness/arch-rules.json (L10)
## Every code-review finding that reveals a new agent error category should become a rule here.
check-arch:
	@bash scripts/check-arch.sh

## verify-feature — run a feature's verification command and transition state to passing if it passes
## Usage: make verify-feature F=F02
verify-feature:
	@if [ -z "$(F)" ]; then echo "Usage: make verify-feature F=<feature-id>  (e.g. make verify-feature F=F02)"; exit 1; fi
	@bash scripts/verify-feature.sh $(F)

## vcr — verify VCR = 1.0: no features in 'active' state (all activated features must be passing)
## Blocks new task activation when any prior activated feature is not yet passing.
vcr:
	@if [ ! -f feature_list.json ]; then echo "feature_list.json not found — skipping VCR check"; exit 0; fi; \
	 _active=0; _passing=0; \
	 if grep -q '"state".*"active"' feature_list.json 2>/dev/null; then \
	   _active=$$(grep -c '"state".*"active"' feature_list.json); \
	 fi; \
	 if grep -q '"state".*"passing"' feature_list.json 2>/dev/null; then \
	   _passing=$$(grep -c '"state".*"passing"' feature_list.json); \
	 fi; \
	 _activated=$$((_active + _passing)); \
	 if [ "$$_activated" -eq 0 ]; then echo "VCR: no activated features yet — OK"; exit 0; fi; \
	 echo "VCR: $$_passing/$$_activated activated features passing ($$_active active)"; \
	 if [ "$$_active" -gt 0 ]; then \
	   echo "FAIL: VCR < 1.0 — $$_active feature(s) active but not passing. Finish and verify the current task before activating a new one."; \
	   exit 1; \
	 fi; \
	 echo "VCR = 1.0 — all activated features are passing"

## clean — remove build artifacts and compiled output
clean:
	find . -path ./.venv -prune -o -name __pycache__ -type d -exec rm -rf {} +
	rm -rf .ruff_cache
