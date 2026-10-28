# Visa Application Agent

A small, explainable agent for a mock visa workflow. It reads a packet of text-layer PDFs (application form,
passport, bank statement), extracts nine fields with evidence quotes, checks them against a checklist and
a mock CRM, and writes only what it can prove. Missing, conflicting and unverifiable information is
reported, never guessed. The principle is **LLM proposes, code disposes**: the LLM only extracts
`{value, evidence_quote, page}`. Verification, validation, the write decision, retries and the report are
deterministic Python, tested offline. Plain Python, no agent framework, about 2,000 lines of source.

![Architecture: the LLM proposes, code decides](docs/architecture.png)
<sub>Orange = LLM proposes, blue = deterministic code decides. Editable source: [docs/architecture.drawio](docs/architecture.drawio); details in [ARCHITECTURE](docs/ARCHITECTURE.md).</sub>

## Quickstart
Requirements: `make`, Python 3.11+, and internet for the first run (installs pinned packages). No API key needed.

```bash
git clone https://github.com/shubhamchitte/visa-application-agent && cd visa-application-agent
make demo        # first run creates .venv and installs pinned deps; replay mode: no API key, no network
make test        # 168 passed, 2 skipped, offline
make run CASE=R6 # one case; compare with mock_data/realistic/cases/R6_injection_fineprint/expected.json
make run-agent   # agent mode, case14: replays a recorded model run; the plan guard rejects an out-of-plan crm.update
```

**Replay vs live.** Replay serves recorded real Groq responses (`openai/gpt-oss-120b`) keyed to the PDF text, so
the demo is deterministic and offline. For a live run, `cp .env.example .env`, set `GROQ_API_KEY`, and run with
`LLM_PROVIDER=groq` exported or on the command line (`.env` supplies keys and models; its `LLM_PROVIDER` is ignored so offline defaults stay replay/fake; for example `LLM_PROVIDER=groq make eval-live`, which re-records `mock_data/replay/`).
Groq free tier may train on data: use mock data only. Gemini is wired but unverified.

**Scanned packets.** R4 and R5 are image-only scans. They need the optional RapidOCR backend (`make setup-ocr`, about
200 MB, no model download); without it `make demo`, `make test` and the eval skip them. Choose the backend with
`VISA_OCR=auto|rapidocr|tesseract|none`. See [LIMITATIONS](docs/LIMITATIONS.md).

**How to run anything:** [docs/COMMANDS.md](docs/COMMANDS.md) (every command, expected outcome, live Groq).

**Read the output without running anything:** [docs/demo_output/](docs/demo_output/README.md) (every scenario:
fields with quotes, issues, CRM plan, status), [docs/EVAL_RESULTS.md](docs/EVAL_RESULTS.md), and
[docs/sample_docs/](docs/sample_docs/) (page images of the realistic documents).

Other targets: `make test-report` (regenerates docs/TEST_RESULTS.md), `make demo-record` (regenerates
docs/demo_output/), `make smoke`. `make run` uses `TODAY=2026-10-27` and a scratch CRM (`CRM=/tmp/visa_crm.json`);
override on the command line, add `DRY=--dry-run` for the CRM diff only. Per-run reports go to
`runs/<case>/` and the tool-call audit trail to `runs/audit.jsonl` (both gitignored).

## Checks the pipeline performs
Read from the code, in pipeline order. "Issue kind" is `IssueKind` in `visa_agent/schemas.py`; status comes from the first matching rule in `visa_agent/policy.yaml`.

| Check | Where | What triggers it | Outcome |
|---|---|---|---|
| Classify by content | `ingest.py` `classify` | keyword score per doc type; filename only breaks ties; no/tied keywords, or a filename pointing at exactly one other type | doc `UNCLASSIFIED` (flag `filename_disagrees`); not extracted |
| Duplicate doc type | `orchestrator.py`, `policy.yaml` `duplicate_doc_type` | two docs classify to the same type | the later file is `UNCLASSIFIED` (flag `duplicate_type`) and contributes no fields; status `NEEDS_REVIEW`, no patch (a human picks the document) |
| No text layer / OCR | `ingest.py`, `verify.py`, `orchestrator.py` | page under 30 chars: OCR'd (RapidOCR, else tesseract); no backend or empty result; on OCR pages whitespace is not evidence (quote, names, dates compared without it) | flag `no_text_layer`, doc never sent to the LLM, its fields `UNVERIFIABLE` |
| Injection scan | `ingest.py` `injection_markers` | regex on folded text (NFKC, Cyrillic/Greek look-alikes, whitespace runs collapsed): "ignore/disregard/forget ... previous/earlier instructions/guidance", "system note:", "set status", "mark as approved", "you are now", plus French/Spanish/Italian/German "ignore the instructions" | flag `injection_detected`, status `NEEDS_REVIEW`, no patch |
| LLM output unusable | `extract.py`, `orchestrator.py` | malformed JSON after retry | that doc's fields `UNVERIFIABLE` |
| Quote on the page | `verify.py` `find_quote` | evidence quote (normalised, 3+ chars) absent from the doc | `UNVERIFIABLE`, value dropped |
| Value inside the quote | `verify.py` `value_in_quote` | value not derivable from quote: names and str values as whole tokens ("UTOPIA" not in "UTOPIAN", "morton@mail.uto" not in "eric.morton@mail.uto"), passport number as a whole token, money with its sign (a debit `-$1,150.00` is not 1150.00) and US or EU separators (`1.234,50` = 1234.50; an ambiguous pattern never verifies), ISO date parsed against allowed formats; ambiguous day/month | `UNVERIFIABLE` with the reason ("ambiguous date" if both readings fit) |
| Value bound to its label | `verify.py` `value_in_quote`, `fields.yaml` `labels`/`role`/`currency` | statement_date, bank_closing_balance, letter_date, leave_start, leave_end: the quote lacks the field label ("Statement date", "Closing balance", "Date:", "annual leave"), or the value is not the first date/amount after it (leave_end: the second), or the amount's currency is not `$`/`UTD` | `UNVERIFIABLE` ("quote lacks the field label", "... in its position after the label", "currency ... is not one of") |
| Derived `full_name` | `verify.py` `derive` | given names + surname built in code; every part must be VERIFIED | else `UNVERIFIABLE` (or `MISSING` if no part found) |
| Bilingual nationality | `verify.py` `first_segment` | field marked bilingual, "A / B": full value checked against the quote first, then only "A" kept | `VERIFIED` single-language value |
| MRZ present | `validators.py` `check_mrz` | passport has no two 44-char MRZ lines | `INVALID` passport_number |
| MRZ check digits | `validators.py` | number, DOB, expiry digits and the composite digit fail ICAO 9303 | `INVALID` on that field |
| MRZ equals visual zone | `validators.py` | verified visual value differs from MRZ (number, DOB, expiry; MRZ surname/given names not all in visual name) | `INVALID` |
| Passport expired | `validators.py` `check_dates` | passport expiry <= `today` (injected clock, `--today`) | `INVALID` passport_expiry |
| Passport validity after travel | `validators.py` `check_dates` | not expired, but expiry < travel date + 6 months (`rules/TOURIST_UTO.yaml`) | `INVALID` passport_expiry |
| Travel date in the past | `validators.py` `check_dates` | intended travel date < `today` | `INVALID` intended_travel_date |
| Email format | `validators.py` `validate` (`EMAIL`) | verified email not `local@domain.tld` (dot in the domain), e.g. OCR's `deborah.davis@mailuto` | `INVALID` email, value dropped from the patch |
| Cross-document identity | `validators.py` `cross_doc` | any field VERIFIED in 2+ docs with different normalised values (e.g. form vs passport name) | `CONFLICT`, never auto-resolved; identity fields give `NEEDS_REVIEW` |
| Bank account holder | `validators.py` `cross_doc` (`same_as` in `fields.yaml`) | statement's account holder, normalised like the derived full_name (NFKC, whitespace, casefold; given names first as printed), differs from the form/passport full_name | `CONFLICT` account_holder, identity field: `NEEDS_REVIEW`, no patch |
| Employment letter name | `validators.py` `cross_doc` | letter's employee name differs from the form/passport full_name (same normalisation) | `CONFLICT` employee_name, `NEEDS_REVIEW`, no patch |
| Employment letter age | `validators.py` `check_letter` | letter present and `letter_date` after `--today`, or older than `employment_letter_max_age_days` (90, `rules/TOURIST_UTO.yaml`) | `INVALID` letter_date, `NEEDS_REVIEW` (`review_fields` in `policy.yaml`) |
| Leave covers travel | `validators.py` `check_letter` | letter present and `leave_start` / `leave_end` not VERIFIED (missing or unverifiable), or intended travel date before `leave_start` or after `leave_end` | `INVALID` leave_start / leave_end, `NEEDS_REVIEW` |
| Field not found anywhere | `orchestrator.py` | no value and no other issue for a field | `MISSING` |
| Missing required docs | `tools/checklist.py`, `policy.py` | required doc type (application form, passport, bank statement) not among classified docs | `INCOMPLETE` |
| Checklist down | `orchestrator.py` | checklist tool raises | checklist `UNKNOWN`, status `NEEDS_REVIEW` |
| Identity gate | `orchestrator.py` `identity` | passport number + DOB not VERIFIED from the passport, or INVALID | no CRM lookup, `NO_WRITE` |
| CRM match | `policy.py` | `crm.find` returns 0 or 2+ records, or errors | `NO_WRITE`, never creates a record |
| Policy status | `policy.yaml` | first match wins: injection or identity conflict -> `NEEDS_REVIEW`, no patch; any doc read by OCR (`ocr_used`) -> `NEEDS_REVIEW`, verified fields still patched for a human to confirm against the scan; duplicate doc type -> `NEEDS_REVIEW`, no patch; employment letter check failed -> `NEEDS_REVIEW`; a CONFLICT on a non-identity field (e.g. nationality) -> `NEEDS_REVIEW`, that field not patched; missing doc / INVALID / UNVERIFIABLE -> `INCOMPLETE`; checklist unknown -> `NEEDS_REVIEW`; else `DATA_UPDATED` | only these three statuses exist; never APPROVED/REJECTED |
| Patch rules | `policy.py` `verified_patch` | field not whitelisted, has an issue, or CRM already holds a different non-empty value | not patched; CRM conflict becomes a note |
| Gateway allowlist, args | `tools/gateway.py` | tool not allowlisted, args fail the JSON schema, caller sets `idempotency_key` | `GuardRejected`, audit-logged, never retried |
| Gateway field/status guard | `tools/gateway.py` | write patch outside the field whitelist, or status outside the allowed set | `GuardRejected` |
| Idempotency, version | `gateway.py`, `orchestrator.py` `write` | key = hash of tool + args; `expected_version` sent from the matched record | retries and reruns dedupe; stale version gives 409 `WRITE_FAILED` |
| Nothing to write | `policy.py` `decide` | empty patch, the record already has the planned status and every note (e.g. a rerun) | `NO_WRITE` (rule `no_change`), version not bumped |
| Retries | `gateway.py` `is_retryable` | 429, 5xx, timeout only (3 attempts, backoff, honours Retry-After); 400/404/409/422 are not retried | otherwise `WRITE_FAILED` |
| Read-back | `orchestrator.py` `read_back` | after a write, `crm.get` record differs from the plan (patch or status) | `WRITE_FAILED` |
| Agent plan guard | `agent_mode.py` `plan_guard` | agent `crm.update` with malformed args (args/patch not an object, notes not a list), for another id, with an `expected_version` that is neither the one `crm.find` saw nor one its own writes produced (stale plan), extra patch keys/values, other status, extra notes, an update that changes nothing, or when plan is `NO_WRITE` | rejected, audit-logged, fed back to the model |

**Not checked:** the employment letter's authenticity (signature, seal, employer existence) and the bank statement's authenticity are not verified; the letter stays optional in `rules/TOURIST_UTO.yaml` and its checks run only when it is present. Name comparison assumes given names before the surname, as both statement layouts print it.

## What the documents look like
Two packet sets: clean generated PDFs (17 scenarios) and a **realistic set** (`mock_data/realistic/cases/R1..R7`): the
official-layout Schengen application form (6 dense pages, surname and given names in separate boxes), a specimen passport
with MRZ, a 3-page bank statement, an employment letter, and image-only scans.

| Schengen form (page 1) | Passport | Passport (scan) | Bank statement | Employment letter |
|---|---|---|---|---|
| ![form](docs/sample_docs/realistic_application_form.png) | ![passport](docs/sample_docs/realistic_passport.png) | ![scan](docs/sample_docs/realistic_passport_scanned.png) | ![bank](docs/sample_docs/realistic_bank_statement.png) | ![letter](docs/sample_docs/realistic_employment_letter.png) |

## Brief requirement -> deliverable
| Brief requirement | Where |
|---|---|
| 1. Source + setup | this README, `visa_agent/`, `Makefile`, `requirements.lock`, `.env.example` |
| 2. Test cases, expected vs actual | [docs/TEST_RESULTS.md](docs/TEST_RESULTS.md) (generated, 17 scenarios), `tests/` (188 passed, 1 xfailed with `make setup-ocr`; 187 passed, 2 skipped with `VISA_OCR=none`), [docs/EVAL_RESULTS.md](docs/EVAL_RESULTS.md) (live accuracy) |
| 3. Rules and safeguards | [docs/SAFEGUARDS.md](docs/SAFEGUARDS.md): rule -> file:line -> proving test; `visa_agent/policy.yaml` |
| 4. Architecture, tools, decisions, limits | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/LIMITATIONS.md](docs/LIMITATIONS.md) |

Two kinds of evidence, kept separate on purpose: the offline tests prove the **control logic** with canned LLM
output (they do not measure extraction). The live eval measures **extraction** with a real model
(Groq `openai/gpt-oss-120b`; see [docs/EVAL_RESULTS.md](docs/EVAL_RESULTS.md)): clean set 155/155 fields correct and VERIFIED, 0 hallucinations; realistic set 153/158 (97%): R1-R3, R6, R7 112/112, scans R4 23/23 and R5 18/23. One raw proposal was wrong: on R6 the model returned the bilingual passport value 'UTOPIAN / UTOPIENNE'. It is verbatim, so it passes verify; code then keeps the first segment ('UTOPIAN'). A genuine nationality mismatch still raises CONFLICT (tested). Scans (RapidOCR): R4 is fully correct; R5 loses 5 fields to OCR: the email is misread as 'mailuto' (faithful to the OCR text, so it verifies; the email-format check then flags it INVALID and it is not written), two names come back unspaced ('DEBORAHDAVIS', compared whitespace-free on OCR docs), and the leave dates are MISSING because OCR dropped that line.

Agent mode (`--mode agent`): the LLM proposes tool calls through the gateway and the plan guard. Tests use a scripted FakeLLM. Two recorded real-Groq runs are replayed by `make run-agent` (default case14; `make run-agent AGENT_CASE=mock_data/cases/case01_happy` for case01). case14: the plan guard rejects an out-of-plan update (`crm.update -> REJECTED (plan guard: notes beyond plan)`) after the planned update has been written. case01: in the latest recording gpt-oss-120b wrote the planned update and then a second, empty-patch update that the plan guard allowed (subset of the plan); earlier recordings declared done on the first step with no write. Code never writes on the model's behalf. The deterministic mode is the primary path; agent mode is secondary.

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
mock_data/                generator.py (deterministic), cases/ (17 packets + goldens), replay/, crm_seed.json
tests/                    scenarios (goldens), gateway, verify, policy, adapters, agent mode
docs/                     ARCHITECTURE SAFEGUARDS LIMITATIONS DEMO TEST_RESULTS EVAL_RESULTS
```

## Docs
[Architecture diagram](docs/architecture.png) | [ARCHITECTURE](docs/ARCHITECTURE.md) | [SAFEGUARDS](docs/SAFEGUARDS.md) | [LIMITATIONS](docs/LIMITATIONS.md) |
[COMMANDS](docs/COMMANDS.md) | [DEMO](docs/DEMO.md) | [TEST_RESULTS](docs/TEST_RESULTS.md) | [EVAL_RESULTS](docs/EVAL_RESULTS.md) |
