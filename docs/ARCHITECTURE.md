# Architecture

## Principle: LLM proposes, code disposes
The LLM does one job: for one document, return `{value, evidence_quote, page}` per field (`extract.py:47`).
Everything else is deterministic and testable offline: classification, evidence verification, validation,
record matching, the write decision, retries, the report. The LLM's status always restarts at `PROPOSED`
(`extract.py:41`); only `verify.py` can mark a field `VERIFIED`. Its confidence is never used.

## Pipeline (`orchestrator.py:57` `run`)
```
packet/*.pdf
  |
  1 INGEST     pymupdf text per page; page <30 chars -> 300dpi raster + tesseract CLI OCR (text_source=ocr, flag ocr_used); no tesseract/empty OCR = no_text_layer; .png/.jpg = 1-page doc ingest.py:16
  2 CLASSIFY   content keywords decide, filename only breaks ties; else UNCLASSIFIED    ingest.py:33
    + injection scan (regex markers on doc text -> flag)                                 ingest.py:56
  3 EXTRACT    LLM, 1 call/doc, JSON schema out; malformed -> 1 re-ask -> UNVERIFIABLE  extract.py:47   <-- only LLM step
  4 VERIFY     quote-in-page AND value-in-quote, exact match; fail -> value dropped      verify.py:66
  5 VALIDATE   MRZ check digits, MRZ==visual, expiry rules (injected clock), cross-doc   validators.py:108
               equality -> Issue{MISSING|CONFLICT|UNVERIFIABLE|INVALID}
  6 CHECKLIST  gateway "checklist.check"; tool failure -> UNKNOWN, never "complete"      orchestrator.py:97
  7 DECIDE     identity from passport only -> crm.find -> policy.yaml table -> WritePlan policy.py:42 (pure function)
  8 WRITE      gateway "crm.update" (expected_version, idempotency key), then read-back  orchestrator.py:128
  9 REPORT     JSON + Markdown rendered from RunResult, templates only (no LLM prose)    report.py:17

 every tool call:  allowlist -> JSON-schema args -> field/status guard -> retry loop -> runs/audit.jsonl   (tools/gateway.py:114)
 deps injected:    LLMClient (groq | gemini | fake | replay), ToolGateway, clock
```
Write policy (`policy.yaml:6-18`, first match wins): CRM matches != 1 -> NO_WRITE; injection -> NEEDS_REVIEW,
no patch; identity conflict -> NEEDS_REVIEW, no patch; checklist missing / INVALID / UNVERIFIABLE -> INCOMPLETE
with a verified-only patch; checklist UNKNOWN -> NEEDS_REVIEW; else DATA_UPDATED. APPROVED and REJECTED do
not exist as statuses (`policy.yaml:2`, `schemas.py:49`).

## ToolGateway and agent mode: why deterministic is the default
Tools (`crm.find`, `crm.get`, `crm.update`, `checklist.check`; `tools/registry.py:13`) exist only behind
`ToolGateway`: JSON-schema spec, arg validation, allowlist, field whitelist, status allowlist, retry policy,
audit log. In the default mode the orchestrator, not the LLM, sequences the calls. On a regulated write path a
fixed sequence is safer, cheaper and testable call-for-call (each scenario asserts the tool-call log,
including calls that must not happen).

`--mode agent` (`agent_mode.py`) shows the guards do not depend on that choice. The deterministic pipeline runs
first in dry-run to produce verified state and the WritePlan. Then the LLM proposes tool calls (max 6 steps,
`agent_mode.py:12`), seeing tool specs and verified state, never raw document text. Each call passes the same
gateway, and `plan_guard` (`agent_mode.py:15`) rejects any `crm.update` that goes beyond the plan (other record,
extra field or value, other status, extra notes). Rejections are audit-logged and returned to the LLM as
observations. Summary: the LLM proposes tool calls through the gateway and plan guard; the tests use a scripted FakeLLM; two recorded real-Groq runs are replayed by `make run-agent`. case14: the plan guard rejects an out-of-plan update (notes beyond plan). case01: in 3 live recordings gpt-oss-120b declared done on its first step, so no write happened (NO_WRITE); code never writes on the model's behalf. The deterministic mode is the primary path.

## Key decisions and alternatives rejected
| Decision | Rejected alternative | Why |
|---|---|---|
| Exact-match evidence (normalize, then substring); no fuzzy match | edit distance, LLM-as-judge | A one-character slip should fail to UNVERIFIABLE, not pass. Precision over recall in a regulated flow. |
| Doc classification by content keywords | LLM classification | No hallucination surface, deterministic, unit-tested. |
| Report rendered from state by templates | LLM summary | A summary can claim more than the state shows. |
| Plain Python, one orchestrator function | LangGraph / agent framework | Hidden control flow, slower to change live; the pipeline is linear. |
| `policy.yaml` decision table | rules scattered in code | One place to change behaviour; one test row per rule (`tests/test_core.py:146`). |
| Fixed tool sequence by default | LLM-planned tool use | Same guard either way, but the fixed path is deterministic. Agent mode is the opt-in. |
| Idempotency key = hash(tool, args incl. expected_version), set by the gateway | caller-supplied key | A caller cannot choose or forge it (`gateway.py:138`); retries and reruns dedupe. |
| Mock CRM never creates records; match on exact passport no. + DOB | fuzzy name matching | Wrong-person writes are worse than no write. |
| Mock data generated deterministically; goldens derived from `truth.json`, not from the code under test | hand-written goldens | Golden and implementation cannot share a bug (`mock_data/generator.py` header). |
| ReplayLLM keyed by hash(model, prompt, doc); stale entry raises | silently degrade on a miss | A changed prompt must stop the demo, not hide behind fields marked unverifiable (`replay.py:14`). |

## LLM split
| Use | Provider | Status |
|---|---|---|
| Field extraction (one doc per call, strict JSON schema, temperature 0) | **Groq `openai/gpt-oss-120b`** (`llm/groq.py`) | Measured by `make eval-live`; full numbers in EVAL_RESULTS.md: clean set 115/115 fields correct and VERIFIED; realistic set 66/66 (1 raw bilingual nationality proposal on R6, normalised in code after verify). Caveat: clean synthetic packets from one generator, no OCR noise; this is not real-world accuracy. |
| Same interface | **Gemini** (`llm/gemini.py`, default `gemini-3.5-flash-lite`) | Wired and unit-tested with mocked clients (error mapping, malformed output). **Never run against the live API**, so no accuracy claim. |
| Control-logic tests | `FakeLLM` (canned per case) | 168 passed, 2 skipped (offline), frozen clock. |
| Demo / quota safety | `ReplayLLM` (recordings of real Groq output in `mock_data/replay/`) | `make demo` default. |

Provider is chosen by `LLM_PROVIDER` (`llm/replay.py:44`). Errors map to RateLimited / Transient / Malformed /
Fatal (`llm/base.py`); only the first two retry, honoring Retry-After.

## Tool contracts
- `crm.find(passport_no, dob) -> [record]` exact match, 0..n results; the caller decides.
- `crm.get(id)`; `crm.update(id, patch, expected_version, [status, notes])` -> 409 on version mismatch, 422 on bad patch,
  repeated idempotency key returns the prior result without a second write (`tools/crm.py:44-65`). No create exists.
- `checklist.check(visa_type, docs_present) -> {required, present, missing}`; rules in `rules/TOURIST_UTO.yaml`.
- Faults (503, timeout-but-applied, 409, 422, tool down) are injected through `FaultPlan` (`tools/faults.py`).
