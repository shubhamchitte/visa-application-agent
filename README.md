# Visa Application Agent

A small, explainable agent for a mock visa workflow. It reads a packet of text-layer PDFs (application form,
passport, bank statement), extracts nine fields with evidence quotes, checks them against a checklist and
a mock CRM, and writes only what it can prove. Missing, conflicting and unverifiable information is
reported, never guessed. The principle is **LLM proposes, code disposes**: the LLM only extracts
`{value, evidence_quote, page}`. Verification, validation, the write decision, retries and the report are
deterministic Python, tested offline. Plain Python, no agent framework, about 1,600 lines of source.

## Quickstart
Needs Python 3.11+ (3.12 preferred). No API key is needed for tests or the demo.

```bash
make setup        # uv sync, or venv + pip install -r requirements.lock when uv is missing
make test         # 150 tests, offline, ~2s (FakeLLM, frozen clock)
make test-report  # regenerates docs/TEST_RESULTS.md (expected vs actual, 16 scenarios)
make demo         # 8 scenarios with ReplayLLM (recorded real Groq output), no network
make smoke        # one end-to-end check
make run CASE=mock_data/cases/case03_name_conflict   # one packet, offline (FakeLLM); add DRY=--dry-run for the CRM diff only
make run-agent CASE=mock_data/cases/case14_injection # agent mode, replays the recorded real-Groq tool proposals
```

`make run` and `make run-agent` use `TODAY=2026-10-27` and a scratch CRM (`CRM=/tmp/visa_crm.json`, reset each run); override either on the command line. The same thing by hand (offline, canned LLM output from `<packet>/fake_llm.json`):

```bash
uv run python -m visa_agent.cli run mock_data/cases/case01_happy --dry-run --today 2026-10-27   # prints the exact CRM diff
uv run python -m visa_agent.cli run mock_data/cases/case03_name_conflict --today 2026-10-27      # real write to ./crm_state.json
uv run python -m visa_agent.cli run mock_data/cases/case01_happy --mode agent --agent-script calls.json  # agent mode; calls.json = JSON list of scripted tool calls
```
Use `.venv/bin/python -m visa_agent.cli ...` if uv is not installed. `--today` freezes the clock
(passport-expiry rules depend on it). The tool-call audit trail is appended to `runs/audit.jsonl` (gitignored; `AUDIT_DIR` overrides).

Optional, real provider: `cp .env.example .env`, set `GROQ_API_KEY`, then `LLM_PROVIDER=groq make eval-live`.
This runs the live eval over the mock packets, writes `docs/EVAL_RESULTS.md` and records responses into
`mock_data/replay/`. Free tier: Groq limits are low, so the eval paces itself (8 s per call). Free-tier data
may be used by the provider for training: use mock data only. Gemini is wired (`LLM_PROVIDER=gemini`) but unverified.

## Brief requirement -> deliverable
| Brief requirement | Where |
|---|---|
| 1. Source + setup | this README, `visa_agent/`, `Makefile`, `requirements.lock`, `.env.example` |
| 2. Test cases, expected vs actual | [docs/TEST_RESULTS.md](docs/TEST_RESULTS.md) (generated, 16 scenarios), `tests/` (150 tests), [docs/EVAL_RESULTS.md](docs/EVAL_RESULTS.md) (live accuracy) |
| 3. Rules and safeguards | [docs/SAFEGUARDS.md](docs/SAFEGUARDS.md): rule -> file:line -> proving test; `visa_agent/policy.yaml` |
| 4. Architecture, tools, decisions, limits | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/LIMITATIONS.md](docs/LIMITATIONS.md) |

Two kinds of evidence, kept separate on purpose: the offline tests prove the **control logic** with canned LLM
output (they do not measure extraction). The live eval measures **extraction** with a real model
(Groq `openai/gpt-oss-120b`, 7 clean generated packets; see [docs/EVAL_RESULTS.md](docs/EVAL_RESULTS.md)): 87/87 fields correct and VERIFIED, 0 hallucinations, 87/87 evidence quotes verbatim, 26 recorded calls with provider request ids. Caveat: clean synthetic packets from one generator, no OCR noise; this is not real-world accuracy.

Agent mode (`--mode agent`): the LLM proposes tool calls through the gateway and the plan guard. Tests use a scripted FakeLLM; recorded real-Groq runs exist for case01 and case14 (`make run-agent`). In those runs the real model proposed out-of-plan statuses (READY_FOR_SUBMISSION, REVIEW_PENDING) and every one was rejected, with zero out-of-plan writes.

## Repo layout
```
visa_agent/
  cli.py commands.py      run | demo | eval | test-report
  orchestrator.py         the linear pipeline (steps 1-9)
  ingest.py extract.py    PDF text, classification, injection scan; one LLM call per doc
  verify.py validators.py evidence matcher; MRZ check digits, date rules, cross-doc equality
  policy.py policy.yaml   the write-decision table (single place to change behaviour)
  fields.yaml doc_types.yaml
  agent_mode.py           optional LLM tool-proposing loop, still bounded by the same guards
  tools/                  gateway.py (allowlist, schema, guards, retry, audit), crm.py, checklist.py, faults.py, registry.py
  llm/                    base.py fake.py replay.py groq.py gemini.py
rules/TOURIST_UTO.yaml    checklist rules (fictional "Utopia" visa)
mock_data/                generator.py (deterministic), cases/ (16 packets + goldens), replay/, crm_seed.json
tests/                    scenarios (goldens), gateway, verify, policy, adapters, agent mode
docs/                     ARCHITECTURE SAFEGUARDS LIMITATIONS DEMO TEST_RESULTS EVAL_RESULTS
```

## Docs
[ARCHITECTURE](docs/ARCHITECTURE.md) | [SAFEGUARDS](docs/SAFEGUARDS.md) | [LIMITATIONS](docs/LIMITATIONS.md) |
[DEMO](docs/DEMO.md) | [TEST_RESULTS](docs/TEST_RESULTS.md) | [EVAL_RESULTS](docs/EVAL_RESULTS.md) |
