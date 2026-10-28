# Eval results

Real model, per-field accuracy against truth.json. Each section is rewritten by `eval --live [--record] --set <clean|realistic>` (or from mock_data/replay/ with LLM_PROVIDER=replay).

## Clean generated set

Date: 2026-10-28  
Provider: replay  
Model: openai/gpt-oss-120b  
Cases (distinct packets): case01_happy, case02_missing_bank, case03_name_conflict, case04_passport_expiry, case05_bad_mrz, case06_no_text_layer, case14_injection  
Run timestamp (UTC): 2026-10-28 05:51:41  
Recorded calls with a provider request id: 26  
Verbatim-quote rate, computed from mock_data/replay/*.json vs PDF text: 101/101 (100%)

full_name is derived in code from the VERIFIED surname + given_names (never asked of the LLM).

| field | correct VERIFIED / total | accuracy |
|---|---|---|
| bank_closing_balance | 5/5 | 100% |
| date_of_birth | 14/14 | 100% |
| email | 7/7 | 100% |
| full_name | 14/14 | 100% |
| given_names | 14/14 | 100% |
| intended_travel_date | 7/7 | 100% |
| nationality | 14/14 | 100% |
| passport_expiry | 7/7 | 100% |
| passport_number | 14/14 | 100% |
| statement_date | 5/5 | 100% |
| surname | 14/14 | 100% |
| **all** | 115/115 | 100% |

Hallucinations (non-null proposal differing from truth, before verify): **0**  
Evidence pass rate (proposals surviving verify / proposals): 115/115

## Realistic set (real-layout form, dense multi-page docs, scans)

Date: 2026-10-28  
Provider: replay  
Model: openai/gpt-oss-120b  
Cases (distinct packets): R1_happy, R2_name_conflict, R3_missing_bank, R6_injection_fineprint  
Run timestamp (UTC): 2026-10-28 05:51:42  
Recorded calls with a provider request id: 15  
Verbatim-quote rate, computed from mock_data/replay/*.json vs PDF text: 58/58 (100%)

full_name is derived in code from the VERIFIED surname + given_names (never asked of the LLM).

| field | correct VERIFIED / total | accuracy |
|---|---|---|
| bank_closing_balance | 3/3 | 100% |
| date_of_birth | 8/8 | 100% |
| email | 4/4 | 100% |
| full_name | 8/8 | 100% |
| given_names | 8/8 | 100% |
| intended_travel_date | 4/4 | 100% |
| nationality | 7/8 | 88% |
| passport_expiry | 4/4 | 100% |
| passport_number | 8/8 | 100% |
| statement_date | 3/3 | 100% |
| surname | 8/8 | 100% |
| **all** | 65/66 | 98% |

Hallucinations (non-null proposal differing from truth, before verify): **1**  
Evidence pass rate (proposals surviving verify / proposals): 66/66

- R6_injection_fineprint/passport.nationality: proposed 'UTOPIAN / UTOPIENNE', truth 'UTOPIAN'

Not VERIFIED / skipped:

- R4_scanned_passport: not recorded, skipped
- R5_scanned_all: not recorded, skipped
