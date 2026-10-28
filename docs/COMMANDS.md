# How to run anything

Run every command from the repository root.

## Requirements
- `make` and Python 3.11+ (or `uv`).
- Internet on the first run only: `make` builds `.venv` and installs the pinned dependencies. After that everything offline works without a network.
- Optional: `tesseract` (`brew install tesseract`) for the scanned cases R4 and R5.

`make run` uses `TODAY=2026-10-27` (a fixed clock, so results are stable) and a scratch CRM at `/tmp/visa_crm.json` that is reset on every run.

## Quick table
| Command | What it does | LLM | Expected outcome |
|---|---|---|---|
| `make test` | pytest suite | FakeLLM / mocks | 177 passed, 2 skipped |
| `make demo` | all demo scenarios (clean cases incl. fault plans 07-13, case15, R1-R7) | FakeLLM for clean cases, replay for R1-R7 | one result per scenario, no error; R4 and R5 print "skipped: not recorded" |
| `make test-report` | regenerates `docs/TEST_RESULTS.md` | FakeLLM / mocks | file rewritten |
| `make demo-record` | regenerates `docs/demo_output/` | replay | files rewritten |
| `make run CASE=mock_data/cases/<case>` | one clean case (table below) | FakeLLM from `<case>/fake_llm.json` | status from that case's `expected.json` |
| `make run CASE=R1` ... `R7` | one realistic case (short name resolves to `mock_data/realistic/cases/R*_*`) | replay (recorded real responses) | see table below |
| `make run-agent` | agent mode on case14 (injection) | replay (recorded proposals) | first `crm.update` REJECTED (plan guard: status 'FLAGGED' is not the planned 'NEEDS_REVIEW'); the retry with the planned status is accepted: `NEEDS_REVIEW`, WRITTEN |
| `make run-agent AGENT_CASE=mock_data/cases/case01_happy` | agent mode on case01 | replay | `DATA_UPDATED`, WRITTEN (CRM version 3): one write with the 7 fields, then a redundant empty update (`patch {}`, status `DATA_UPDATED`) that the plan guard allows; a 404 for visa type "tourist" on `checklist.check` is shown and harmless |
| `LLM_PROVIDER=groq make run CASE=R2` | live extraction | live Groq | see Live LLM below |

Add `DRY=--dry-run` to `make run` to skip the CRM write (outcome DRY_RUN, prints the diff).

## Clean cases: `make run CASE=mock_data/cases/<case>`
Always FakeLLM, even if `LLM_PROVIDER` is set. Compare with `<case>/expected.json`.

| Case | Outcome with `make run` |
|---|---|
| case01_happy | DATA_UPDATED, WRITTEN |
| case02_missing_bank | INCOMPLETE (MISSING bank_closing_balance, statement_date, account_holder), WRITTEN |
| case03_name_conflict | NEEDS_REVIEW (CONFLICT full_name, account_holder, employee_name), WRITTEN |
| case04_passport_expiry | INCOMPLETE (INVALID passport_expiry: under 6 months after travel), WRITTEN |
| case05_bad_mrz | NO_WRITE (identity unverified) |
| case06_no_text_layer | INCOMPLETE (UNVERIFIABLE bank fields), WRITTEN |
| case07_hallucination | needs `make demo` (INCOMPLETE, UNVERIFIABLE email, WRITTEN) |
| case08a_crm_no_match, case08b_crm_multiple | need `make demo` (NO_WRITE) |
| case09_crm_503_retry | needs `make demo` (DATA_UPDATED after 2 retries) |
| case10_timeout_applied | needs `make demo` (DATA_UPDATED, same idempotency key) |
| case11a_version_conflict, case11b_unprocessable | need `make demo` (WRITE_FAILED, 409 / 422 not retried) |
| case12_checklist_down | needs `make demo` (NEEDS_REVIEW, checklist UNKNOWN) |
| case13_llm_malformed | needs `make demo` (NO_WRITE, passport fields UNVERIFIABLE) |
| case14_injection | NEEDS_REVIEW (injection_detected), WRITTEN |
| case15_bank_holder_mismatch | NEEDS_REVIEW (CONFLICT account_holder: bank statement says AMY MORTON), WRITTEN |

## Realistic cases: `make run CASE=R1` ... `R7`
Replay of recorded real responses. Compare with `mock_data/realistic/cases/<case>/expected.json`.

| Case | Outcome |
|---|---|
| R1 | DATA_UPDATED, WRITTEN |
| R2 | NEEDS_REVIEW, CONFLICT full_name (MARTIS vs MARTIN) plus account_holder and employee_name, WRITTEN |
| R3 | INCOMPLETE, bank statement missing, WRITTEN |
| R4 | scanned passport: needs tesseract and is not recorded, so `make run` fails with a "recording stale" error. Not runnable offline |
| R5 | fully scanned: needs tesseract and is not recorded; without tesseract it ends NO_WRITE (identity unverified) |
| R6 | NEEDS_REVIEW, injection_detected, WRITTEN |
| R7 | NEEDS_REVIEW, CONFLICT account_holder (relative's account), WRITTEN |

## Live LLM
1. `cp .env.example .env`, then set `GROQ_API_KEY=` in `.env`.
2. Live extraction on an existing realistic case:
   `LLM_PROVIDER=groq make run CASE=R2`
   Expected: same as replay (NEEDS_REVIEW, CONFLICT full_name).
3. A brand-new folder of PDFs/images:
   `LLM_PROVIDER=groq .venv/bin/python -m visa_agent.cli run <folder> --dry-run [--today YYYY-MM-DD]`
   Prints status and the CRM diff; nothing is written.

Cost and timing: one extraction call per document, so about 4 calls for a full packet (application form, passport, bank statement, employment letter); the employment letter adds one call over a 3-document packet. Expect about 1.5-2 minutes because of Groq free-tier pacing: 8 s between calls, a 60 s wait after a call over 3K tokens, and the run stops after 2 consecutive 429 responses.

`--dry-run` runs everything but skips `crm.update`. `--today` injects the clock for the expiry and travel-date checks (default is the real date). A new folder has no `expected.json`: the CRM seed is `mock_data/crm_seed.json`, so use a passport number that exists there to get a match, otherwise the result is NO_WRITE.

## Where output lands
- `runs/<case>/report.md` and `report.json` (per case); audit trail in `runs/audit.jsonl`.
- Compare against the case's `expected.json` (`mock_data/cases/<case>/` or `mock_data/realistic/cases/<case>/`).
- Pre-recorded outputs for every scenario, readable without running anything: `docs/demo_output/`.

## Gotchas
- Clean cases always use FakeLLM, even with `LLM_PROVIDER` set. R1-R7 use replay.
- Cases 07-13 have no documents of their own (they reuse case01's packet and inject a fault plan from `expected.json`); a bare `make run` on them gives NO_WRITE. Use `make demo` or `make test`.
- R4, R5 and `case06_no_text_layer` involve scanned or text-less PDFs; OCR needs `tesseract`, otherwise those fields stay UNVERIFIABLE.
- A mistyped path silently falls back by basename: `mock_data/realistic/cases/case01_happy` does not exist, so it runs the clean `case01_happy`. Check the first lines of the report.
- A new folder without `LLM_PROVIDER=groq` falls back to replay, finds no recording and fails.
- If a live run fails during a presentation, show the recorded outputs in `docs/demo_output/`.
