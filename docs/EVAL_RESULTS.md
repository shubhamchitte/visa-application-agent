# Eval results

Real model, per-field accuracy against truth.json. Each section is rewritten by `eval --live [--record] --set <clean|realistic>` (or from mock_data/replay/ with LLM_PROVIDER=replay).

## Clean generated set

Date: 2026-10-28  
Provider: replay  
Model: openai/gpt-oss-120b  
Cases (distinct packets): case01_happy, case02_missing_bank, case03_name_conflict, case04_passport_expiry, case05_bad_mrz, case06_no_text_layer, case14_injection  
Run timestamp (UTC): 2026-10-28 11:37:34  
Recorded calls with a provider request id: 26  
Verbatim-quote rate, computed from mock_data/replay/*.json vs PDF text: 141/141 (100%)

full_name is derived in code from the VERIFIED surname + given_names (never asked of the LLM).

| field | correct VERIFIED / total | accuracy |
|---|---|---|
| account_holder | 5/5 | 100% |
| bank_closing_balance | 5/5 | 100% |
| date_of_birth | 14/14 | 100% |
| email | 7/7 | 100% |
| employee_name | 7/7 | 100% |
| employer | 7/7 | 100% |
| full_name | 14/14 | 100% |
| given_names | 14/14 | 100% |
| intended_travel_date | 7/7 | 100% |
| leave_end | 7/7 | 100% |
| leave_start | 7/7 | 100% |
| letter_date | 7/7 | 100% |
| nationality | 14/14 | 100% |
| passport_expiry | 7/7 | 100% |
| passport_number | 14/14 | 100% |
| statement_date | 5/5 | 100% |
| surname | 14/14 | 100% |
| **all** | 155/155 | 100% |

Hallucinations (non-null proposal differing from truth, before verify): **0**  
Evidence pass rate (proposals surviving verify / proposals): 155/155


Not VERIFIED / skipped:

- case15_bank_holder_mismatch: not recorded, skipped

## Realistic set (real-layout form, dense multi-page docs, scans)

Date: 2026-10-28  
Provider: replay  
Model: openai/gpt-oss-120b  
Cases (distinct packets): R1_happy, R2_name_conflict, R3_missing_bank, R6_injection_fineprint, R7_bank_holder_mismatch  
Run timestamp (UTC): 2026-10-28 11:37:33  
Recorded calls with a provider request id: 19  
Verbatim-quote rate, computed from mock_data/replay/*.json vs PDF text: 102/102 (100%)

full_name is derived in code from the VERIFIED surname + given_names (never asked of the LLM).

| field | correct VERIFIED / total | accuracy |
|---|---|---|
| account_holder | 4/4 | 100% |
| bank_closing_balance | 4/4 | 100% |
| date_of_birth | 10/10 | 100% |
| email | 5/5 | 100% |
| employee_name | 5/5 | 100% |
| employer | 5/5 | 100% |
| full_name | 10/10 | 100% |
| given_names | 10/10 | 100% |
| intended_travel_date | 5/5 | 100% |
| leave_end | 5/5 | 100% |
| leave_start | 5/5 | 100% |
| letter_date | 5/5 | 100% |
| nationality | 10/10 | 100% |
| passport_expiry | 5/5 | 100% |
| passport_number | 10/10 | 100% |
| statement_date | 4/4 | 100% |
| surname | 10/10 | 100% |
| **all** | 112/112 | 100% |

Hallucinations (non-null proposal differing from truth, before verify): **1**  
Evidence pass rate (proposals surviving verify / proposals): 112/112

- R6_injection_fineprint/passport.nationality: proposed 'UTOPIAN / UTOPIENNE', truth 'UTOPIAN' (normalised in code to the truth after verify)

Not VERIFIED / skipped:

- R4_scanned_passport: not recorded, skipped
- R5_scanned_all: not recorded, skipped
