# Test results (generated 2026-10-27; FakeLLM, frozen clock per case)

These offline tests prove the control logic (verification, policy, gateway guards, retries) using scripted LLM output. They do not measure extraction accuracy; that lives in EVAL_RESULTS.md (real model, separate evidence).

16/16 scenarios match their golden. Issues listed are the expected subset vs everything raised.

| # | case | scenario | expected (outcome / status / issues) | actual (outcome / status / issues) | result |
|---|---|---|---|---|---|
| 1 | case01_happy | Happy path | WRITTEN / DATA_UPDATED / none | WRITTEN / DATA_UPDATED / none | PASS |
| 2 | case02_missing_bank | Missing bank statement | WRITTEN / INCOMPLETE / MISSING:bank_closing_balance, MISSING:statement_date | WRITTEN / INCOMPLETE / MISSING:bank_closing_balance, MISSING:statement_date | PASS |
| 3 | case03_name_conflict | Name conflict form vs passport | WRITTEN / NEEDS_REVIEW / CONFLICT:full_name | WRITTEN / NEEDS_REVIEW / CONFLICT:full_name | PASS |
| 4 | case04_passport_expiry | Passport expires <6 months after travel | WRITTEN / INCOMPLETE / INVALID:passport_expiry | WRITTEN / INCOMPLETE / INVALID:passport_expiry | PASS |
| 5 | case05_bad_mrz | Bad MRZ check digit | NO_WRITE / NO_WRITE / INVALID:passport_number | NO_WRITE / identity_unverified / INVALID:passport_number | PASS |
| 6 | case06_no_text_layer | Bank statement is an image-only page | WRITTEN / INCOMPLETE / UNVERIFIABLE:bank_closing_balance, UNVERIFIABLE:statement_date | WRITTEN / INCOMPLETE / UNVERIFIABLE:bank_closing_balance, UNVERIFIABLE:statement_date | PASS |
| 7 | case07_hallucination | LLM returns a value whose quote is not on the page | WRITTEN / INCOMPLETE / UNVERIFIABLE:email | WRITTEN / INCOMPLETE / UNVERIFIABLE:email | PASS |
| 8 | case08a_crm_no_match | CRM has no matching record | NO_WRITE / NO_WRITE / none | NO_WRITE / crm_match_count_not_1 / none | PASS |
| 8 | case08b_crm_multiple | CRM has two matching records (duplicates) | NO_WRITE / NO_WRITE / none | NO_WRITE / crm_match_count_not_1 / none | PASS |
| 9 | case09_crm_503_retry | CRM update 503 twice then OK | WRITTEN / DATA_UPDATED / none | WRITTEN / DATA_UPDATED / none | PASS |
| 10 | case10_timeout_applied | CRM timeout but write applied; retry reuses idempotency key | WRITTEN / DATA_UPDATED / none | WRITTEN / DATA_UPDATED / none | PASS |
| 11 | case11a_version_conflict | CRM update 409 is not retried | WRITE_FAILED / DATA_UPDATED / none | WRITE_FAILED / DATA_UPDATED / none | PASS |
| 11 | case11b_unprocessable | CRM update 422 is not retried | WRITE_FAILED / DATA_UPDATED / none | WRITE_FAILED / DATA_UPDATED / none | PASS |
| 12 | case12_checklist_down | Checklist tool down -> UNKNOWN | WRITTEN / NEEDS_REVIEW / none | WRITTEN / NEEDS_REVIEW / none | PASS |
| 13 | case13_llm_malformed | LLM malformed JSON twice (passport) | NO_WRITE / NO_WRITE / UNVERIFIABLE:passport_expiry, UNVERIFIABLE:passport_number, UNVERIFIABLE:date_of_birth | NO_WRITE / identity_unverified / UNVERIFIABLE:date_of_birth, UNVERIFIABLE:full_name, UNVERIFIABLE:nationality, UNVERIFIABLE:passport_expiry, UNVERIFIABLE:passport_number | PASS |
| 14 | case14_injection | Injection text in bank statement | WRITTEN / NEEDS_REVIEW / none | WRITTEN / NEEDS_REVIEW / none | PASS |
