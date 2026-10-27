# Eval results

Date: 2026-10-27  
Provider: groq  
Model: openai/gpt-oss-120b  
Cases (distinct packets): case01_happy, case02_missing_bank, case03_name_conflict, case04_passport_expiry, case05_bad_mrz, case06_no_text_layer, case14_injection

Run timestamp (UTC): 2026-10-27 10:03:50  
Recorded calls with a provider request id: 26  
Verbatim-quote rate, computed from mock_data/replay/*.json vs PDF text: 87/87 (100%)

| field | correct VERIFIED / total | accuracy |
|---|---|---|
| bank_closing_balance | 5/5 | 100% |
| date_of_birth | 14/14 | 100% |
| email | 7/7 | 100% |
| full_name | 14/14 | 100% |
| intended_travel_date | 7/7 | 100% |
| nationality | 14/14 | 100% |
| passport_expiry | 7/7 | 100% |
| passport_number | 14/14 | 100% |
| statement_date | 5/5 | 100% |
| **all** | 87/87 | 100% |

Hallucinations (non-null proposal differing from truth, before verify): **0**  
Evidence pass rate (proposals surviving verify / proposals): 87/87

