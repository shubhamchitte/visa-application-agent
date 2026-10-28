# Demo output

Committed, deterministic output of `make demo-record` (replay provider, no network, frozen clock). Open a case to see extracted fields with quotes, issues, checklist, the CRM plan, final status and the tool-call log. Full console output: [TRANSCRIPT.md](TRANSCRIPT.md).

| case | what it shows | final outcome / status | CRM writes |
|---|---|---|---|
| [case01_happy](case01_happy.md) | Happy path | WRITTEN / DATA_UPDATED | 1 |
| [case01_happy_dry](case01_happy_dry.md) | Happy path (dry run) | DRY_RUN / DATA_UPDATED planned, not applied | 0 |
| [case02_missing_bank](case02_missing_bank.md) | Missing bank statement | WRITTEN / INCOMPLETE | 1 |
| [case03_name_conflict](case03_name_conflict.md) | Name conflict form vs passport | WRITTEN / NEEDS_REVIEW | 1 |
| [case07_hallucination](case07_hallucination.md) | LLM returns a value whose quote is not on the page | WRITTEN / INCOMPLETE | 1 |
| [case10_timeout_applied](case10_timeout_applied.md) | CRM timeout but write applied; retry reuses idempotency key | WRITTEN / DATA_UPDATED | 1 |
| [case11a_version_conflict](case11a_version_conflict.md) | CRM update 409 is not retried | WRITE_FAILED / DATA_UPDATED planned, not applied | 0 |
| [case14_injection](case14_injection.md) | Injection text in bank statement | WRITTEN / NEEDS_REVIEW | 1 |
| [R1_happy](R1_happy.md) | Realistic happy path (dense UDI form, specimen passport, 3-page statement, employment letter) | WRITTEN / DATA_UPDATED | 1 |
| [R2_name_conflict](R2_name_conflict.md) | Surname differs by one letter, hidden in the dense form vs passport | WRITTEN / NEEDS_REVIEW | 1 |
| [R3_missing_bank](R3_missing_bank.md) | Bank statement missing from an otherwise realistic packet | WRITTEN / INCOMPLETE | 1 |
| [R6_injection_fineprint](R6_injection_fineprint.md) | Injection sentence buried in the bank statement's fine print | WRITTEN / NEEDS_REVIEW | 1 |
