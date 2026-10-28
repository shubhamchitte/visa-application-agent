# Demo script (~10 min)

Setup once: `make setup && make test`. `make demo` runs the scenarios below with ReplayLLM (recorded Groq output,
no network); case 7 uses FakeLLM because the scenario is a scripted LLM misbehaviour (`commands.py:16`).
`CLI="uv run python -m visa_agent.cli"` (or `.venv/bin/python -m visa_agent.cli`). Always pass `--today 2026-10-27`.
Use a scratch CRM per case: `--crm /tmp/x.json` (copied fresh from the seed). Audit trail: `runs/audit.jsonl` (gitignored; delete between cases).

1. **(1 min) Architecture.** Show the diagram in ARCHITECTURE.md. Say "LLM proposes, code disposes". Open `visa_agent/policy.yaml`.
2. **(2 min) Happy path.** `$CLI run mock_data/cases/case01_happy --dry-run --today 2026-10-27 --crm /tmp/a.json`: extracted fields with quotes and the exact CRM diff (7 fields, DATA_UPDATED). Rerun without `--dry-run`: record written at version 2; `cat runs/audit.jsonl` shows checklist.check -> crm.find -> crm.update -> crm.get (read-back).
3. **(1.5 min) Missing doc, then conflict.** `make demo` output for case 2 (INCOMPLETE, MISSING bank fields, absent from patch). Then `$CLI run mock_data/cases/case03_name_conflict ...`: CONFLICT full_name with both values and sources, empty patch, NEEDS_REVIEW.
4. **(1.5 min) Hallucination.** Case 7 in the demo: email dropped (UNVERIFIABLE). Open `verify.py:25` and `:41`: the two checks, no fuzzy matching.
5. **(2 min) Faults.** Case 10 (timeout but applied): `pytest -k case10 -s` or show the golden `mock_data/cases/case10_timeout_applied/expected.json` (`retry`: 1 effective write, same idempotency key). Case 11a (409): demo shows WRITE_FAILED, 1 attempt, no "success" text.
6. **(1.5 min, optional) Agent mode.** `make run-agent` replays a recorded real-Groq run of case14 (no network). The audit prints `crm.update -> REJECTED (plan guard: notes beyond plan)`: the plan guard blocked an out-of-plan update. For case01 (`make run-agent AGENT_CASE=mock_data/cases/case01_happy`) the model declared done on its first step in 3 live recordings, so nothing is written (NO_WRITE); code never writes on the model's behalf. Deterministic mode is the primary path. The tests use a scripted FakeLLM: `uv run pytest tests/test_agent_mode.py -v`.
7. **(1 min) Injection.** `$CLI run mock_data/cases/case14_injection ...`: flag `injection_detected`, NEEDS_REVIEW, empty patch.
8. **(1 min) Evidence.** Open `docs/TEST_RESULTS.md` (generated, 16/16, expected vs actual) and `docs/EVAL_RESULTS.md` (live eval, separate evidence). Name the limitation that worries you most: exact-match recall on messy real documents.

Likely questions: why no framework (hidden control flow); why is the LLM not choosing writes (regulated write path); what if the LLM lies (verify.py drops it); retried write twice? (idempotency key, `gateway.py:63`).

## Rehearsed live changes (test first, each under 10 min)
Run `uv run pytest -q` before and after.

**A. Unverifiable blocks all writes (described only, not applied).** Today an UNVERIFIABLE issue gives INCOMPLETE with a verified-only patch (the unverifiable field is just left out). The change makes it NO_WRITE.
Test first: in `tests/test_core.py` add a `test_policy_rows` row `([REC], [issue(IssueKind.UNVERIFIABLE, "email")], OK_CL, False, "any_unverifiable", None)`. The expected reason is the rule's `when` key (`decide` sets `reason=rule["when"]`), so it is `any_unverifiable`, not a free-form name. It fails now (reason is `checklist_missing_or_invalid_or_unverifiable`).
Edit 1, `visa_agent/policy.yaml`: add `- when: any_unverifiable` / `action: NO_WRITE` after the `identity_conflict` rule and before `checklist_missing_or_invalid_or_unverifiable`.
Edit 2, `visa_agent/policy.py`, `facts()`: add `"any_unverifiable": IssueKind.UNVERIFIABLE in kinds`. Optionally drop `IssueKind.UNVERIFIABLE` from the `checklist_missing_or_invalid_or_unverifiable` fact (it can no longer reach it).
Edit 3 (the policy note tweak), `visa_agent/policy.py`, NO_WRITE branch of `decide`: the note is built from `matches`, so this rule would print "CRM candidates: rec-1001", which is misleading. Make the note depend on the rule: for `any_unverifiable` use `"unverifiable field(s) in the documents; nothing written, needs human review"`; keep the candidates text for `crm_match_count_not_1`. The plan has `record_id=None`, so the orchestrator reports NO_WRITE.
Then: goldens for cases 06, 07, 13 (the ones with UNVERIFIABLE issues) change to NO_WRITE and need regenerating by hand in `expected.json` (outcome, crm.action, tool log without `crm.update`); rerun `make test` and `make test-report`.

**B. Retry max 5 / no retry on 429.** Test first: `tests/test_gateway.py` `test_gives_up_after_max_3_attempts` (change to 5) and `test_retry_classification` (429 -> False).
Touch: `visa_agent/tools/gateway.py:38` (`max_attempts`), `:32` (drop `err.status == 429`). Note LLM 429s retry via `RateLimited.retryable` in `llm/base.py`, unaffected.

**C. Add field `place_of_birth`.** Test first: `tests/test_core.py` `test_value_parsers`-style test, plus a new field in a case's `fake_llm.json` (generated: `mock_data/generator.py`, then `python -m mock_data.generator`).
Touch: `visa_agent/fields.yaml` (`place_of_birth: {type: str, identity: false, source: [passport]}`), `visa_agent/policy.yaml:3` (whitelist). The prompt changes, so replay recordings go stale: use `LLM_PROVIDER=fake` for the demo after this change.

**D. Employment letter required if bank balance is low.** Test first: new scenario-style test in `tests/test_tools.py` for `checklist.check` with a balance argument, or a `test_policy_rows` row for a new fact.
Touch: `rules/TOURIST_UTO.yaml` (e.g. `employment_letter_required_if_balance_below: 5000`), `visa_agent/tools/checklist.py` (read it, add `bank_balance` param), `visa_agent/tools/registry.py:22` (schema), `visa_agent/orchestrator.py:97-98` (pass the merged `bank_closing_balance`). The `docs_present` flow already surfaces `missing` to the policy.
