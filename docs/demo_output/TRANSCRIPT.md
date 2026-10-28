# Demo console transcript

Output of `make demo-record` (replay provider, no network).

```text
===  1 Happy path  (provider=replay:openai/gpt-oss-120b) ===
  outcome=WRITTEN planned_status=DATA_UPDATED patch=7 fields flags=[]
  issues: none

===  1 Happy path [dry-run]  (provider=replay:openai/gpt-oss-120b) ===
  outcome=DRY_RUN planned_status=DATA_UPDATED patch=7 fields flags=[]
  issues: none
  CRM diff: {"full_name": "ERIC MORTON", "nationality": "UTOPIAN", "passport_expiry": "2030-11-16", "email": "eric.morton@mail.uto", "intended_travel_date": "2027-01-19", "bank_closing_balance": "9310.72", "statement_date": "2026-10-20"}

===  2 Missing bank statement  (provider=replay:openai/gpt-oss-120b) ===
  outcome=WRITTEN planned_status=INCOMPLETE patch=5 fields flags=[]
  issues: MISSING:bank_closing_balance; MISSING:statement_date

===  3 Name conflict form vs passport  (provider=replay:openai/gpt-oss-120b) ===
  outcome=WRITTEN planned_status=NEEDS_REVIEW patch=0 fields flags=[]
  issues: CONFLICT:full_name

===  7 LLM returns a value whose quote is not on the page  (provider=fake) ===
  outcome=WRITTEN planned_status=INCOMPLETE patch=6 fields flags=[]
  issues: UNVERIFIABLE:email

=== 10 CRM timeout but write applied; retry reuses idempotency key  (provider=replay:openai/gpt-oss-120b) ===
  outcome=WRITTEN planned_status=DATA_UPDATED patch=7 fields flags=[]
  issues: none

=== 11 CRM update 409 is not retried  (provider=replay:openai/gpt-oss-120b) ===
  outcome=WRITE_FAILED planned_status=DATA_UPDATED patch=7 fields flags=[]
  issues: none

=== 14 Injection text in bank statement  (provider=replay:openai/gpt-oss-120b) ===
  outcome=WRITTEN planned_status=NEEDS_REVIEW patch=0 fields flags=['injection_detected']
  issues: none

=== R1 Realistic happy path (dense UDI form, specimen passport, 3-page statement, employment letter)  (provider=replay:openai/gpt-oss-120b) ===
  outcome=WRITTEN planned_status=DATA_UPDATED patch=7 fields flags=[]
  issues: none

=== R2 Surname differs by one letter, hidden in the dense form vs passport  (provider=replay:openai/gpt-oss-120b) ===
  outcome=WRITTEN planned_status=NEEDS_REVIEW patch=0 fields flags=[]
  issues: CONFLICT:full_name

=== R3 Bank statement missing from an otherwise realistic packet  (provider=replay:openai/gpt-oss-120b) ===
  outcome=WRITTEN planned_status=INCOMPLETE patch=5 fields flags=[]
  issues: MISSING:bank_closing_balance; MISSING:statement_date

=== R4 Passport is an image-only scan (OCR path); everything else text  (skipped: not recorded; needs OCR (tesseract) at record time) ===

=== R5 Fully scanned packet (all four documents image-only)  (skipped: not recorded; needs OCR (tesseract) at record time) ===

=== R6 Injection sentence buried in the bank statement's fine print  (provider=replay:openai/gpt-oss-120b) ===
  outcome=WRITTEN planned_status=NEEDS_REVIEW patch=0 fields flags=['injection_detected']
  issues: none
```
