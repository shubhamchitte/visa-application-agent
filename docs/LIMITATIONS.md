# Limitations (what this does not prove)

- **The eval set is small and generated.** The eval covers 7 clean generated packets, built by one deterministic
  generator (`mock_data/generator.py`) with synthetic fictional data in one layout per document type. The result in EVAL_RESULTS.md (clean set 115/115 fields correct and VERIFIED, realistic set 65/66 with 1 hallucination (R6 nationality, caught only by the cross-document check); openai/gpt-oss-120b) shows the pipeline works on this distribution. It is not an accuracy estimate for real
  documents, real layouts or other models; do not over-read it. Case 7 (hallucination) and case 13 (malformed
  output) are scripted FakeLLM failures, so they test the guard, not the model.
- **Offline tests prove control logic, not extraction.** The 166 tests (2 skipped) and the 16-row TEST_RESULTS use canned LLM
  output. Only `make eval-live` touches a real model.
- **Gemini is unverified.** The adapter (`llm/gemini.py`) is unit-tested with mocked clients only. It was never
  run against the live API, so the default model id `gemini-3.5-flash-lite` is unconfirmed and no accuracy is
  claimed for it. Groq is the measured provider.
- **OCR is basic and optional.** A page under 30 characters (and any .png/.jpg) is OCR'd with the `tesseract` CLI,
  a system dependency not installed by `make setup`. Without it the page stays `no_text_layer` and its fields
  UNVERIFIABLE (case 6), with a warning. Scanned packets R4 and R5 are skipped without tesseract (not recorded, not evaluated); OCR is covered only by `tests/test_ocr.py`, which mocks the tesseract subprocess. OCR quality on real scans (skew, low resolution, stamps) is unmeasured;
  misreads ('<' vs 'K', 0 vs O) are not corrected, so they surface as UNVERIFIABLE quotes or INVALID MRZ
  checksums, which lowers recall. No layout analysis or vision model.
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
- **Injection defence is heuristic.** A regex marker list (`ingest.py:12`) plus prompt framing. Novel phrasings
  will not be flagged; the real protection is structural (the extraction LLM has no tools, writes are guarded).
- **Other gaps.** Dry-run and the prompt delimiter are covered in `tests/test_safeguards.py`; there is no secret-scanning in CI; the
  a no-secrets-in-history check has not been done (`.env` is gitignored and untracked).
  The source is ~1,800 lines (1,811 by `wc -l` on `visa_agent/`).
