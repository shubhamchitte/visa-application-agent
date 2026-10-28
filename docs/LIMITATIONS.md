# Limitations (what this does not prove)

- **The eval set is small and generated.** The eval covers 7 clean generated packets, built by one deterministic
  generator (`mock_data/generator.py`) with synthetic fictional data in one layout per document type. The result in EVAL_RESULTS.md (clean set 155/155 fields correct and VERIFIED, realistic set 112/112, with 1 raw bilingual nationality proposal on R6 normalised in code after verify; openai/gpt-oss-120b) shows the pipeline works on this distribution. It is not an accuracy estimate for real
  documents, real layouts or other models; do not over-read it. Case 7 (hallucination) and case 13 (malformed
  output) are scripted FakeLLM failures, so they test the guard, not the model.
- **Offline tests prove control logic, not extraction.** The 226 tests (224 pass and 2 skip without OCR) and the 16-row TEST_RESULTS use canned LLM
  output. Only `make eval-live` touches a real model.
- **Gemini is unverified.** The adapter (`llm/gemini.py`) is unit-tested with mocked clients only. It was never
  run against the live API, so the default model id `gemini-3.5-flash-lite` is unconfirmed and no accuracy is
  claimed for it. Groq is the measured provider.
- **OCR is optional.** A page under 30 characters (and any .png/.jpg) is OCR'd by RapidOCR (`make setup-ocr`) or,
  failing that, the `tesseract` CLI (`VISA_OCR` picks). With neither the page stays `no_text_layer` and its fields
  UNVERIFIABLE (case 6), with a warning; R4/R5 are then skipped. RapidOCR drops spaces ("12NOV2030",
  "DEBORAHDAVIS"), so on OCR pages quotes, names and cross-doc names are compared without whitespace and dates may
  lack their inner spaces; every character must still match. A faithful quote of a misread passes verify: R5's email
  `deborah.davis@mailuto` (the scan says `mail.uto`) is caught only because it fails the email-format check; a
  misread that still looks valid would be written. Any OCR'd document therefore sends the case to NEEDS_REVIEW
  (policy rule `ocr_used`) with the verified fields patched for a human to confirm. OCR dropped R5's leave-dates line. OCR output is
  DPI-sensitive (200 dpi used; 250+ split R5's MRZ line). Only the two mock scans were measured; real scans (skew, low resolution, stamps) are untested;
- **OCR text is not checked in CI.** R4/R5 replay keys hash the OCR text. It is identical across runs and across
  Python 3.11/3.12 on macOS arm64 (onnxruntime 1.23.2), but Linux x86_64 runs different CPU kernels and was not
  measured, so a CI runner could produce different text and a stale recording. CI runs without the extra (R4/R5 skipped).
  misreads ('<' vs 'K', 0 vs O) are not corrected, so they surface as UNVERIFIABLE quotes or INVALID MRZ
  checksums, which lowers recall. No layout analysis or vision model.
- **Label anchoring covers 5 fields.** `labels` in `fields.yaml` bind statement_date, bank_closing_balance,
  letter_date, leave_start and leave_end to their printed label (the quote must contain it; the value must be the
  first or, for leave_end, second date/amount after it). The other fields are unanchored because the realistic
  Schengen form and passport print the label in a column header above the value, so the real model quotes the bare
  value ("31.07.1978", "UTOPIAN"): date_of_birth, passport_number, names (protected by the MRZ check digits,
  MRZ == visual zone and cross-doc equality), passport_expiry (MRZ), nationality and email (whole-token match and
  cross-doc equality only), intended_travel_date and employer (whole-token match only). An LLM could still pick a
  same-type value from a neighbouring column, e.g. the form's country of birth "UTOPIA" for nationality, or the
  departure date for travel. A str value that drops a whole trailing word ("Frank" of "Frank Ltd") still verifies.
  Currency is checked only when the quote prints one (`$` or a code from a short list); a bare amount is accepted.
- **Exact-match evidence favors precision over recall.** A correct value whose quote differs by one character
  (OCR noise, a model that paraphrases) is dropped to UNVERIFIABLE. Real-world recall will be lower than on this
  clean generated text. This is deliberate. Date formats outside `fields.yaml` also fail.
- **Free-tier quota and data use.** Groq free-tier rate limits make live runs slow (8 s pacing in `eval --live`).
  Free-tier providers may use submitted data for training, so only synthetic data should be sent. The demo avoids
  quota by replaying recorded responses.
- **Replay goes stale after prompt changes.** Recordings are keyed by hash(model, prompt, doc). Editing the
  prompt, schema or a field list invalidates them; replay then raises `StaleRecording` (by design) until
  re-recorded with `make eval-live` (needs a key) or you switch to `LLM_PROVIDER=fake`. Adding a field in a live
  change breaks replay for that doc.
- **No auth and no PII encryption.** The mock CRM is a local JSON file; `runs/audit.jsonl` stores arguments in clear
  text (passport numbers, DOB). Single-tenant, no access control, no redaction.
- **Agent mode is demoed via fake/replay only.** `--mode agent`: the LLM proposes tool calls through the guard; scripted FakeLLM in tests; two recorded real-Groq runs are replayed by `make run-agent`. case14: the plan guard rejects an out-of-plan update (notes beyond plan). case01: in 3 live recordings gpt-oss-120b declared done on its first step, so no write happened (NO_WRITE); code never writes on the model's behalf, which is the safe outcome. The deterministic mode is the primary path. Gemini has no `propose_tool_call`. The
  guarantee shown is that the guards hold for arbitrary proposals, not that a real model plans well.
- **Mock-only scope.** One fictional visa type (`TOURIST_UTO`), one applicant per packet, English only, fictional
  rules, a mock CRM that mimics HTTP semantics but is in-process. Fixed tool sequence in the default mode.
- **Injection defence is heuristic.** A regex marker list (`ingest.py` `INJECTION_MARKERS`, matched after NFKC, a small Cyrillic/Greek look-alike fold and whitespace collapsing; English plus one phrase each in French, Spanish/Italian, German) plus prompt framing. Novel phrasings, other languages and look-alikes outside the fold
  will not be flagged; the real protection is structural (the extraction LLM has no tools, writes are guarded).
- **Other gaps.** Dry-run and the prompt delimiter are covered in `tests/test_safeguards.py`; there is no secret-scanning in CI; the
  a no-secrets-in-history check has not been done (`.env` is gitignored and untracked).
  The source is ~2,000 lines (2,025 by `wc -l` on `visa_agent/**/*.py`).
