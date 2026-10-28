# Live walkthrough runbook (about 15 minutes plus the live change)

Everything below runs offline (recorded or scripted LLM output, fixed clock `2026-10-27`). Exactly one command is optional and live (segment 11). Output lines quoted here were captured from the real commands; lines marked **re-verify** depend on OCR and policy work that may still change, so run them once before presenting.

What the assessors asked for (`obj.txt`), and where each item is shown:

| Requirement (quoted) | Segment |
|---|---|
| "Document Processing: Read a mock visa-application packet and extract specified fields accurately." | 2, 3 |
| "CRM Integration: Call a mock CRM tool to update the appropriate record using the extracted information." | 2, 6, 7, 8 |
| "Document Checklist Validation: Use a document-checklist tool to identify missing requirements." | 4, 9 |
| "Exception Handling: Clearly report missing, conflicting, or unverifiable information without making assumptions or inventing data." | 4, 5, 12 |
| "Failure Scenarios: Demonstrate how the workflow responds when a document is incomplete or a tool call fails." | 4, 6, 7, 8, 9 |
| "explain your implementation, demonstrate the workflow, discuss how you handled failures and edge cases, and make a small change" | whole runbook, section 3 |

## 0. One-time shell setup (paste before starting)

```bash
cd ~/CRM
export TODAY=2026-10-27
# Fault cases 07-13 have no documents of their own (they reuse case01's packet and inject a fault plan), so `make run`
# cannot show them; `make case CASE=<case>` runs one case with its golden fault plan and scripted LLM output and prints the report.
```

`make -s case CASE=case09 | sed -n '/^## Tool calls/,$p'` prints just the tool-call table. The same reports are pre-recorded for 07, 10 and 11a in `docs/demo_output/<case>.md` (fallback, section 6).

## 1. The 30-second pitch (show `docs/architecture.png`)

> "This is an agent for a mock visa workflow. The principle is: the LLM proposes, code disposes. The model does one job: for each document it returns a value, an evidence quote and a page. Everything else is deterministic code: a quote must really be on the page, the value must come from the quote, documents are cross-checked, a single policy table decides what may be written to the CRM, and every tool call goes through one gateway that owns retries, idempotency and the audit log. What it cannot verify, it reports and does not write."

Point at: the single LLM box in the diagram, the gateway box (allowlist, schema, guard, retry, audit), and `visa_agent/policy.yaml` (open it once; it is the only place CRM behaviour is decided).

## 2. Walkthrough (about 14 minutes, in this order)

### Segment 1 (2 min). Happy path: extraction with evidence, then a real CRM write
Requirement: "Read a mock visa-application packet and extract specified fields accurately" and "update the appropriate record using the extracted information".

```bash
make run CASE=mock_data/cases/case01_happy DRY=--dry-run     # extraction + the exact diff, nothing written
make run CASE=mock_data/cases/case01_happy                    # same, then the real write
```
Point at:
- Extracted fields table: every row has a quote and a page, for example `| application_form | surname | MORTON | VERIFIED | "Full name: ERIC MORTON" (p1) |` and `| passport | passport_expiry | 2030-11-16 | VERIFIED | "Date of expiry: 16 NOV 2030" (p1) |`.
- Dry run: `- outcome: Dry run: nothing written to rec-1001.`, `write outcome: DRY_RUN`, and a 7-field patch (`full_name`, `nationality`, `passport_expiry`, `email`, `intended_travel_date`, `bank_closing_balance`, `statement_date`).
- Real run: `- outcome: CRM record rec-1001 written (version 2).` and the tool-call table `checklist.check` -> `crm.find` -> `crm.update` (attempt 1, OK, args carry `expected_version: 1` and an `idempotency_key`) -> `crm.get` (the read-back).
- `cat runs/audit.jsonl`: one JSON line per attempt.

Script: "Every value has a verbatim quote and a page. The write carries the version I read and an idempotency key, and I read the record back afterwards, so 'written' means verified, not assumed. The dry run is the same pipeline minus the one write call."

### Segment 2 (1.5 min). Missing document: reported, not invented
Requirement: "Document Checklist Validation: ... identify missing requirements" and "report missing ... information without making assumptions".

```bash
make run CASE=mock_data/cases/case02_missing_bank
```
Point at:
- `- **MISSING** bank_closing_balance: not found in any document` (also `statement_date`, `account_holder`).
- Checklist: `- missing: bank_statement`.
- CRM: `policy rule: checklist_missing_or_invalid_or_unverifiable; status: INCOMPLETE`, and the patch contains only the 5 fields that are verified, none of the bank fields.

Script: "The checklist tool says the bank statement is absent, so the status is INCOMPLETE and the CRM note says what is missing. The bank fields are not in the patch: no default, no guess."

### Segment 3 (1.5 min). Conflict: both values shown, nothing written
Requirement: "Clearly report ... conflicting ... information".

```bash
make run CASE=mock_data/cases/case03_name_conflict
```
Point at:
- `- **CONFLICT** full_name: documents disagree on full_name (sources: [{'doc': 'application_form', 'value': 'ERIC COMPTON', 'page': 1}, {'doc': 'passport', 'value': 'ERIC MORTON', 'page': 1}])`.
- `policy rule: identity_conflict; status: NEEDS_REVIEW`, `field patch: {}`.
- Realistic version (same behaviour on a dense real-layout form, one letter different): `make run CASE=R2` gives `CHRISTOPHER MARTIS` (form) vs `CHRISTOPHER MARTIN` (passport), `rec-2002`, `NEEDS_REVIEW`, `field patch: {}`.

Script: "I do not pick the passport as the winner even though it is probably right. Identity fields are never auto-resolved: a human decides. The comparison is code, which is why a one-letter difference is caught."

### Segment 4 (1.5 min). Hallucination blocked
Requirement: "without making assumptions or inventing data".

```bash
make -s case CASE=case07 | sed -n '/^## Issues/,/^## Final/p' | cut -c1-170
```
Point at:
- `- **UNVERIFIABLE** email: application_form: quote not found in document (sources: [{'doc': 'application_form', 'value': 'ada.fake@mail.uto', 'page': 1}])`.
- `policy rule: checklist_missing_or_invalid_or_unverifiable; status: INCOMPLETE`, and the email is missing from the patch.
- Open `visa_agent/verify.py`: two checks (quote on the page; value derivable from the quote), exact match, no fuzzy matching.

Script: "Here the scripted model invents an email with a quote that is not on the page. The value is dropped and reported. A model that returns a verbatim but wrong value is caught by the cross-document check instead; that is the one real miss from the live eval (R6), shown in `docs/EVAL_RESULTS.md`."

### Segment 5 (1 min). Prompt injection is data, never an instruction
```bash
make run CASE=mock_data/cases/case14_injection     # or CASE=R6 for the sentence buried in page 3 fine print
```
Point at: `## Flags` -> `- injection_detected`; `policy rule: injection_detected; status: NEEDS_REVIEW`; `field patch: {}`; `note: possible prompt injection in document text`. The status vocabulary contains only DATA_UPDATED, INCOMPLETE, NEEDS_REVIEW (`allowed_statuses` in `policy.yaml`), so "APPROVED" is unreachable.

Script: "The document tried to set the status to APPROVED. The extraction model has no tools, the regex only raises a flag, and the real control is structural: the gateway refuses any status outside the allowlist."

### Segment 6 (2 min). CRM tool through the gateway: 503 retries, then success
Requirement: "Demonstrate how the workflow responds when ... a tool call fails." Proves: retry on 503, attempt numbers, the same idempotency key on every attempt, version check.

```bash
make -s case CASE=case09 | sed -n '/^## Tool calls/,$p' | cut -c1-140
```
Real output:
```
| 3 | crm.update | 1 | RETRY (503: injected transient failure) | ...
| 4 | crm.update | 2 | RETRY (503: injected transient failure) | ...
| 5 | crm.update | 3 | OK | ...
| 6 | crm.get | 1 | OK | `{"id": "rec-1001"}` |
```
and the report ends `write outcome: WRITTEN`, `final CRM status: DATA_UPDATED; version: 2`. Point at the attempt column (1, 2, 3) and that the `idempotency_key` in the args is identical on rows 3, 4 and 5 (`f534048c...8446`). Retries cover only 429, 5xx and timeouts, at most 3 attempts, with backoff and jitter (`visa_agent/tools/gateway.py`).

Script: "Two 503s, then success on attempt 3, and the same idempotency key every time, so a retry can never double-write. The CRM version went 1 to 2 once."

Optional proof of the real version check (not an injected fault): `.venv/bin/python -m pytest -q tests/test_tools.py -k "real_version_mismatch or find_no_match or idempotent_rerun" -v` (find: no match and multiple; update never creates a record; a stale `expected_version` gives 409 in one attempt).

### Segment 7 (2 min). Timeout that was actually applied (idempotency), then 409 and 422
```bash
make -s case CASE=case10 | sed -n '/^## Tool calls/,$p' | cut -c1-150
make -s case CASE=case11a | sed -n '/^## Final/,$p' | cut -c1-150
make -s case CASE=case11b | sed -n '/^## Final/,$p' | cut -c1-150
```
Point at:
- Case 10: `| 3 | crm.update | 1 | RETRY (timeout: injected timeout after apply) |` then `| 4 | crm.update | 2 | OK |` with the same `idempotency_key`. The first call applied the write but the answer was lost; the retry is deduplicated by the key, so there is one effective write (`version: 2`). This is the timeout-applied case ("timeout" is retried; the rule is retry only transient errors).
- Case 11a: `| 3 | crm.update | 1 | ERROR (409: injected version conflict) |`, only one attempt, `write outcome: WRITE_FAILED`, `final CRM status: NEW; version: 1`. No "success" wording anywhere in the report.
- Case 11b: same shape with `ERROR (422: injected validation error)`, one attempt, `WRITE_FAILED`.

Script: "4xx errors are never retried: a 409 means someone else changed the record, a 422 means my payload is wrong, and retrying would not fix either. The record stays at version 1 and the run reports WRITE_FAILED, not success."

### Segment 8 (1 min). CRM lookup failures: no match or several matches
```bash
make -s case CASE=case08a | sed -n '/^## CRM/,/^## Final/p'
make -s case CASE=case08b | sed -n '/^## CRM/,/^## Final/p'
```
Point at: `- candidates from crm.find: none` and `- note: no CRM record matches; none created` (08a); `- candidates from crm.find: rec-1001, rec-1002` (08b); both `policy rule: crm_match_count_not_1`, `write outcome: NO_WRITE`, and the tool table stops after `crm.find` (no `crm.update`).

Script: "The agent never creates a record and never picks one of two. Lookup is by passport number plus date of birth, taken from the passport only."

### Segment 9 (1.5 min). Checklist tool down: UNKNOWN, never "complete"
Requirement: "Use a document-checklist tool" and "when ... a tool call fails".

```bash
make -s case CASE=case12 | sed -n '/^## Checklist/,$p' | cut -c1-150
```
Real output:
```
## Checklist
- UNKNOWN: checklist tool unavailable; document status not established
- policy rule: checklist_unknown; status: NEEDS_REVIEW
- note: checklist unavailable
| 1 | checklist.check | 1 | RETRY (503: injected permanent failure) | ...
| 2 | checklist.check | 2 | RETRY (503: injected permanent failure) | ...
| 3 | checklist.check | 3 | ERROR (503: injected permanent failure) | ...
```
Script: "If the checklist tool is down I do not know whether the packet is complete, so I say UNKNOWN and route to a human. Unknown is not success. Same rule for the CRM: a failed lookup is `crm_unavailable`, never 'no match' (`test_crm_find_failure_is_crm_unavailable_not_no_match`)."

### Segment 10 (1.5 min). Malformed model output and unverifiable identity
```bash
make -s case CASE=case13 | sed -n '/^## Issues/,/^## Final/p' | cut -c1-170
```
Point at: `- **UNVERIFIABLE** surname: passport: LLM output malformed twice: not JSON: ...` (all 7 passport fields), `policy rule: identity_unverified`, `NO_WRITE`, and the tool table has only `checklist.check` (no `crm.find`: no lookup without a verified identity).

Script: "The model is asked once more for valid JSON, then the fields are UNVERIFIABLE. Without a verified passport number and date of birth there is no CRM lookup at all."

### Segment 11 (2 min). Agent mode and the plan guard
Requirement: shows the guards hold even when the model chooses the tool calls (`--mode agent`).

```bash
make run-agent                                                       # replay of a recorded real-model run on case14, no network
make run-agent AGENT_CASE=mock_data/cases/case01_happy               # the happy path in agent mode
.venv/bin/python -m pytest -q tests/test_agent_mode.py -v            # scripted model: out-of-plan writes rejected
```
Real output of the first command (tail):
```
  checklist.check -> OK
  crm.find -> OK
  crm.update -> REJECTED (plan guard: status 'FLAGGED' is not the planned 'NEEDS_REVIEW')
  crm.update -> OK
  crm.get -> OK
  checklist.check -> ERROR (404: no rules for visa type tourist)
  checklist.check -> ERROR (404: no rules for visa type tourist_visa)
```
Point at: the `REJECTED` row (attempt 0: it never reached the CRM), the next `crm.update` accepted with the planned status `NEEDS_REVIEW`, and the harmless 404s where the model guessed visa-type names. The code computes the plan (policy table); the model may only execute that plan.

Script: "In agent mode the model picks the calls. It proposed the status FLAGGED; the plan guard compares every write with the plan code computed and rejected it. A real model also guessed wrong visa types; the checklist tool returned 404 and nothing broke. Deterministic mode is the primary path; agent mode shows the guard working on a real model's proposals."

Optional live command (needs a key in `.env`, about 2 minutes because of free-tier pacing): `LLM_PROVIDER=groq make run CASE=R2` -> expect the same result as the replay (NEEDS_REVIEW, CONFLICT full_name). Skip it if the network is slow.

### Segment 12 (1 min). Evidence: tests assert what must not happen
Open `docs/TEST_RESULTS.md` (expected vs actual per scenario) and `docs/EVAL_RESULTS.md` (live extraction accuracy, kept separate from the control-logic tests). Run `make test` once while you talk (about 1.5 minutes; the last run was `188 passed, 1 xfailed` **re-verify**).

Script: "The goldens assert the tool-call log too: no `crm.update` when it must not happen, and no 'success' text on WRITE_FAILED. Control logic is proven offline; extraction accuracy is measured separately, and I state that the eval is small."

### Optional (only if asked): scanned documents (OCR)
```bash
make setup-ocr          # once, about 200 MB
make run CASE=R4        # passport is an image-only scan
make run CASE=R5        # all four documents scanned
```
Last captured results, **re-verify** (OCR policy was being changed): R4 `planned_status=NEEDS_REVIEW patch=7 fields`; R5 `NEEDS_REVIEW`, `INVALID:email; MISSING:leave_start; MISSING:leave_end`. Without `make setup-ocr` both are skipped in `make demo`. Policy intent: OCR text is weaker evidence, so a case that used OCR goes to a human with the verified fields pre-filled.

## 3. The live small change (pick one, rehearse all)

Rule: write the test first, watch it fail, make the edit, watch it pass, then run the full suite. The one-test commands run in under a second; the full `make test` takes about 1.5 minutes, so start it and keep talking. Each edit below was rehearsed on a scratch copy of the repo.

**A. Add an injection phrase (safest, about 3 minutes).**
1. In `tests/test_core.py`, `test_injection_scan`, add before the last assert: `assert ing.injection_markers([doc("Please disregard all previous rules.")]) == ["d"]`.
2. `.venv/bin/python -m pytest -q tests/test_core.py -k injection_scan` fails.
3. In `visa_agent/ingest.py`, append `, r"disregard (all |any )?(previous|prior|above)"` to `INJECTION_MARKERS`.
4. Same command: `1 passed`. Full suite unchanged.

**B. Teach the classifier a new bank-statement keyword (about 3 minutes).**
1. Append to `tests/test_core.py`: `def test_classify_new_keyword(): assert ing.classify(doc("Transaction history for the period. Balance carried forward."), DT)[0] == "bank_statement"`.
2. `.venv/bin/python -m pytest -q tests/test_core.py -k new_keyword` fails (the text is UNCLASSIFIED).
3. In `visa_agent/doc_types.yaml` add `"transaction history"` to the `bank_statement` keywords.
4. `.venv/bin/python -m pytest -q tests/test_core.py -k "new_keyword or classify"` gives `5 passed`.

**C. Raise the retry limit from 3 to 5 (shows the tests guard behaviour; about 6 minutes).**
Edit `max_attempts` in `visa_agent/tools/gateway.py` (`RetryPolicy`). Expected failures, which is the point: `test_gives_up_after_max_3_attempts` (rename and change to 5), `test_always_fail_and_tool_down_exhaust_retries` in `tests/test_tools.py`, and the golden `test_scenario[case12_checklist_down]` (its tool-call log lists 3 attempts). Explain each failure, update the expectations, and rerun `tests/test_gateway.py tests/test_tools.py tests/test_scenarios.py`. Do this one only if you are comfortable updating the golden.

Not recommended live: making UNVERIFIABLE block all writes (needs a new `policy.yaml` rule, a new fact in `policy.py`, a changed note, and regenerated goldens for cases 06, 07 and 13). Policy files may still change, so re-read `policy.yaml` before offering it.

After any edit, revert with `git checkout -- <file>` for the files you touched.

## 4. Limitations to state (plainly)

- The eval is small and synthetic (generated packets plus a few realistic ones); it measures extraction on that distribution only.
- Exact-match evidence trades recall for precision: a correct value with a one-character difference in its quote is dropped to UNVERIFIABLE and goes to a human.
- Scanned documents: OCR is optional (`make setup-ocr`); only two mock scans were measured, misreads fail closed (MRZ checksum, email format) but a misread that still looks valid would be written, so any OCR'd case goes to NEEDS_REVIEW. **re-verify** the current R4/R5 wording.
- Injection detection is a regex heuristic; the real protection is structural (no tools for the extraction model, gateway allowlist, status allowlist).
- The audit log holds PII in clear text and there is no authentication; redaction and encryption are the first production steps.
- Agent mode is demonstrated with recorded and scripted model output only; the guard is proven, the model's planning quality is not.
- The CRM and checklist are mocks; one fictional visa type, one applicant per packet.
- Gemini adapter was never run live; Groq is the measured provider.

## 5. Likely questions, short answers

- **Where does the LLM stop and code decide?** At extraction. `policy.decide` and `policy.yaml` produce the write plan; the gateway enforces it (allowlist, schema, field whitelist, status allowlist).
- **The CRM timed out but the write was applied. Is a retry safe?** Yes: the gateway derives the idempotency key from the tool and arguments, the CRM returns the original result, and a read-back confirms (case 10).
- **What if the model invents a plausible value?** The quote must be on the page and the value must come from the quote; otherwise UNVERIFIABLE. A verbatim but wrong value is caught by the cross-document check.
- **Why no agent framework?** Hidden control flow; I wanted every decision visible and testable.
- **Why is the model not choosing the writes?** Regulated write path: code computes the plan, in agent mode the guard rejects any deviation.
- **Why retry only 429, 5xx and timeouts?** Those are transient. 4xx means the request is wrong or the record changed; retrying cannot fix it.
- **What happens on a version conflict?** 409, one attempt, WRITE_FAILED, record unchanged.
- **How would you scale this?** Real CRM client behind the same gateway, queue per packet, redacted audit store, per-visa-type rule files (already `rules/<TYPE>.yaml`), and a bigger real-document eval.
- **How do you know extraction is accurate?** `docs/EVAL_RESULTS.md` (live runs, recorded); stated as small and synthetic.
- **Why is the status never APPROVED?** `allowed_statuses` has three values; the gateway rejects anything else.

## 6. Fallback plan if something fails live

1. Do not debug in front of them. Say: "this is the recorded output of the same command" and open the file.
2. Pre-recorded reports (identical format, no run needed): `docs/demo_output/case01_happy.md`, `case01_happy_dry.md`, `case02_missing_bank.md`, `case03_name_conflict.md`, `case07_hallucination.md`, `case10_timeout_applied.md`, `case11a_version_conflict.md`, `case14_injection.md`, `R2_name_conflict.md`, `R6_injection_fineprint.md`; console summary in `docs/demo_output/TRANSCRIPT.md`; every expected outcome in `docs/TEST_RESULTS.md`.
3. For cases 09, 12, 13 and agent mode there is no recorded file: show `mock_data/cases/<case>/expected.json` (`fault_plan`, `tool_calls`) and run the matching tests: `.venv/bin/python -m pytest -q tests/test_scenarios.py -k "case09 or case12 or case13" -v` and `tests/test_agent_mode.py -v`.
4. If the live change breaks something unexpectedly: `git checkout -- <file>` and carry on with another option.
5. If a live LLM call hangs: Ctrl-C and use the replay equivalent (every segment above is already replay).

## 7. Pre-flight checklist (the evening before, and 10 minutes before)

- [ ] Fresh clone in a new folder (not your working copy): `git clone <repo> /tmp/walkthrough && cd /tmp/walkthrough`, then `make setup` (needs internet once).
- [ ] `make test` is green (about 1.5 minutes; note the count).
- [ ] `make demo` finishes without error (it always replays, whatever `LLM_PROVIDER` says in `.env`); skim the output once.
- [ ] Test `make -s case CASE=case09 | tail -8`.
- [ ] Optional live command: `GROQ_API_KEY` set in `.env`; run `LLM_PROVIDER=groq make run CASE=R2` once beforehand. If it is slow, skip it.
- [ ] Optional OCR: `make setup-ocr`, then `make run CASE=R4` and `make run CASE=R5` (**re-verify** the outcomes).
- [ ] Open in tabs before starting: `docs/architecture.png`, `visa_agent/policy.yaml`, `visa_agent/verify.py`, `visa_agent/tools/gateway.py`, `docs/TEST_RESULTS.md`, `docs/EVAL_RESULTS.md`, `docs/demo_output/`.
- [ ] `rm -f runs/audit.jsonl` so the audit trail starts clean; terminal font large; two terminal tabs (one for the long `make test`).
- [ ] `git status` clean (so `git checkout -- <file>` after the live change restores the state).
- [ ] Close other apps and notifications; charge and plug in; test screen sharing; have this file open on a second screen.

Timing guide: pitch 0.5 min, segments 1-12 about 14 minutes, live change about 5 minutes.
