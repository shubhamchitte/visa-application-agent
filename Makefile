# uv is the supported path; venv+pip from requirements.lock (pinned) is the fallback when uv is missing.
UV := $(shell command -v uv 2>/dev/null)
PY ?= python3.12
RUN := $(if $(UV),uv run,.venv/bin/python -m)
CLI := $(if $(UV),uv run python,.venv/bin/python) -m visa_agent.cli

.PHONY: setup test smoke demo run run-agent eval-live test-report clean
CASE ?= mock_data/cases/case01_happy
TODAY ?= 2026-10-27
CRM ?= /tmp/visa_crm.json
setup:
ifdef UV
	uv sync
else
	$(PY) -m venv .venv && .venv/bin/pip install -q -r requirements.lock && .venv/bin/pip install -q --no-deps -e .
endif

test:
	$(RUN) pytest -q

smoke:
	$(if $(UV),uv run python,.venv/bin/python) scripts/smoke.py

demo:
	$(CLI) demo

# make run CASE=mock_data/cases/case03_name_conflict [DRY=--dry-run]: offline, FakeLLM from <CASE>/fake_llm.json, scratch CRM
run:
	rm -f $(CRM)
	$(CLI) run $(CASE) --today $(TODAY) --crm $(CRM) $(DRY)

# make run-agent [CASE=mock_data/cases/case14_injection]: agent mode, replays the recorded real-Groq proposals (no network)
run-agent:
	rm -f $(CRM)
	LLM_PROVIDER=replay $(CLI) run $(CASE) --mode agent --today $(TODAY) --crm $(CRM)

eval-live:
	$(CLI) eval --live --record

test-report:
	$(CLI) test-report

clean:
	rm -rf .venv .pytest_cache runs
