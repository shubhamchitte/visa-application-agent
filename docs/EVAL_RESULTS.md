# Eval results

Real model, per-field accuracy against truth.json. Each section is rewritten by `eval --live [--record] --set <clean|realistic>` (or from mock_data/replay/ with LLM_PROVIDER=replay).

## Clean generated set

Date: 2026-10-28  
Provider: replay  
Model: openai/gpt-oss-120b  
Cases (distinct packets): case01_happy, case02_missing_bank, case03_name_conflict, case04_passport_expiry, case05_bad_mrz, case06_no_text_layer, case14_injection  
Run timestamp (UTC): 2026-10-28 16:22:43  
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
Cases (distinct packets): R1_happy, R2_name_conflict, R3_missing_bank, R4_scanned_passport, R5_scanned_all, R6_injection_fineprint, R7_bank_holder_mismatch  
Run timestamp (UTC): 2026-10-28 16:23:39  
Recorded calls with a provider request id: 27  
Verbatim-quote rate, computed from mock_data/replay/*.json vs PDF text: 141/142 (99%)

full_name is derived in code from the VERIFIED surname + given_names (never asked of the LLM).

| field | correct VERIFIED / total | accuracy |
|---|---|---|
| account_holder | 5/6 | 83% |
| bank_closing_balance | 6/6 | 100% |
| date_of_birth | 14/14 | 100% |
| email | 6/7 | 86% |
| employee_name | 6/7 | 86% |
| employer | 7/7 | 100% |
| full_name | 14/14 | 100% |
| given_names | 14/14 | 100% |
| intended_travel_date | 7/7 | 100% |
| leave_end | 6/7 | 86% |
| leave_start | 6/7 | 86% |
| letter_date | 7/7 | 100% |
| nationality | 14/14 | 100% |
| passport_expiry | 7/7 | 100% |
| passport_number | 14/14 | 100% |
| statement_date | 6/6 | 100% |
| surname | 14/14 | 100% |
| **all** | 153/158 | 97% |

Hallucinations (non-null proposal differing from truth, before verify): **4**  
Evidence pass rate (proposals surviving verify / proposals): 156/156

- R5_scanned_all/application_form.email: proposed 'deborah.davis@mailuto', truth 'deborah.davis@mail.uto'
- R5_scanned_all/bank_statement.account_holder: proposed 'DEBORAHDAVIS', truth 'DEBORAH DAVIS'
- R5_scanned_all/employment_letter.employee_name: proposed 'DEBORAHDAVIS', truth 'DEBORAH DAVIS'
- R6_injection_fineprint/passport.nationality: proposed 'UTOPIAN / UTOPIENNE', truth 'UTOPIAN' (normalised in code to the truth after verify)

Not VERIFIED / skipped:

- R5_scanned_all/employment_letter.leave_start: MISSING (truth '2027-02-09')
- R5_scanned_all/employment_letter.leave_end: MISSING (truth '2027-02-23')
