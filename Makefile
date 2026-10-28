# uv is the supported path; venv+pip from requirements.lock (pinned) is the fallback when uv is missing.
UV := $(shell command -v uv 2>/dev/null)
PY ?= $(firstword $(foreach p,python3.12 python3.11 python3,$(shell command -v $(p) 2>/dev/null)))
VENV := $(if $(UV),,.venv)
RUN := $(if $(UV),uv run,.venv/bin/python -m)
CLI := $(if $(UV),uv run python,.venv/bin/python) -m visa_agent.cli

.PHONY: setup test smoke demo demo-record run run-agent eval-live test-report clean
CASE ?= mock_data/cases/case01_happy
AGENT_CASE ?= mock_data/cases/case14_injection
TODAY ?= 2026-10-27
CRM ?= /tmp/visa_crm.json
setup:
ifdef UV
	uv sync
else
	@test -n "$(PY)" || { echo "error: no python3.12/python3.11/python3 on PATH (need >= 3.11, or install uv)"; exit 1; }
	@$(PY) -c 'import sys; sys.exit(sys.version_info < (3, 11))' || { echo "error: $(PY) is $$($(PY) -V 2>&1); need Python >= 3.11 (set PY=... or install uv)"; exit 1; }
	$(PY) -m venv .venv && .venv/bin/pip install -q -r requirements.lock && .venv/bin/pip install -q --no-deps -e .
endif

# venv is created on first use (uv manages its own env, so no prerequisite there)
.venv:
	$(MAKE) setup

test: $(VENV)
	$(RUN) pytest -q

smoke: $(VENV)
	$(if $(UV),uv run python,.venv/bin/python) scripts/smoke.py

demo: $(VENV)
	$(CLI) demo

# writes docs/demo_output/ (replay provider, deterministic, no network)
demo-record: $(VENV)
	LLM_PROVIDER=replay $(CLI) demo --record

# make run CASE=mock_data/cases/case03_name_conflict | CASE=R6 [DRY=--dry-run]: offline, FakeLLM from <CASE>/fake_llm.json, scratch CRM
run: $(VENV)
	rm -f $(CRM)
	$(CLI) run $(CASE) --today $(TODAY) --crm $(CRM) $(DRY)

# make run-agent [AGENT_CASE=mock_data/cases/case01_happy]: agent mode, replays the recorded real-Groq proposals (no network)
run-agent: $(VENV)
	rm -f $(CRM)
	LLM_PROVIDER=replay $(CLI) run $(AGENT_CASE) --mode agent --today $(TODAY) --crm $(CRM)

eval-live:
	$(CLI) eval --live --record

test-report: $(VENV)
	$(CLI) test-report

clean:
	rm -rf .venv .pytest_cache runs
