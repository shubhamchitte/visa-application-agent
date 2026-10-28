"""Golden scenarios: run the full pipeline per mock_data/cases/*/expected.json and compare RunResult,
the gateway audit log (incl. calls that must NOT happen), LLM calls and the rendered report."""
import json
from collections import Counter
from datetime import date
from pathlib import Path

import pytest

from visa_agent.cli import build_gateway
from visa_agent.llm.fake import FakeLLM
from visa_agent.llm.replay import REPLAY_DIR, ReplayLLM
from visa_agent.orchestrator import Deps, run
from visa_agent.report import to_markdown
from visa_agent.tools.crm import MockCRM
from visa_agent.tools.faults import fault_plan_from_golden
from visa_agent.tools.gateway import RetryPolicy

ROOT = Path(__file__).resolve().parents[1] / "mock_data"
CASES = sorted(p.parent for p in (ROOT / "cases").glob("*/expected.json"))
REALISTIC = sorted(p.parent for p in (ROOT / "realistic" / "cases").glob("*/expected.json"))


class Counting:
    """ReplayLLM plus the per-doc call log FakeLLM keeps (the golden checks which docs reached the LLM)."""
    def __init__(self, inner):
        self.inner, self.name, self.calls = inner, inner.name, []

    def extract(self, doc_id, prompt, schema):
        self.calls.append(doc_id)
        return self.inner.extract(doc_id, prompt, schema)


def setup_case(case_dir: Path, tmp_path: Path):
    exp = json.loads((case_dir / "expected.json").read_text())
    seed = json.loads((case_dir.parent.parent / "crm_seed.json").read_text())["records"]
    crm_file = tmp_path / "crm.json"
    crm_file.write_text(json.dumps({"records": [r for r in seed if r["id"] in exp["crm"]["records_in_seed"]]}))
    plans = fault_plan_from_golden(exp["fault_plan"])
    crm = MockCRM(crm_file, {t.split(".", 1)[1]: p for t, p in plans.items() if t.startswith("crm.")})
    gw = build_gateway(crm, checklist_faults=plans.get("checklist.check"),
                       retry=RetryPolicy(sleep=lambda s: None, rand=lambda: 0.5), clock=lambda: "T")
    if exp.get("realistic"):  # no scripted output: replay the recorded real-model responses (no network)
        llm = Counting(ReplayLLM(case_dir.name))
    else:
        script = json.loads((case_dir / "fake_llm.json").read_text())["script"]
        llm = FakeLLM(exp["case"], {(exp["case"], k): v for k, v in script.items()})
    deps = Deps(llm=llm, gateway=gw, today=lambda: date.fromisoformat(exp["clock"]))
    return exp, crm, gw, llm, deps


def _subset(sub, full) -> bool:
    if isinstance(sub, dict):
        return isinstance(full, dict) and all(k in full and _subset(v, full[k]) for k, v in sub.items())
    return sub == full




def _realistic_param(p: Path):
    exp = json.loads((p / "expected.json").read_text())
    if not (REPLAY_DIR / f"{p.name}.json").exists():
        why = "needs OCR (tesseract not installed at record time)" if exp.get("ocr_required") else "not recorded"
        return pytest.param(p, marks=pytest.mark.skip(reason=f"{p.name}: no replay recording ({why})"))
    return p


@pytest.mark.parametrize("case_dir", CASES + [_realistic_param(p) for p in REALISTIC], ids=lambda p: p.name)
def test_scenario(case_dir, tmp_path):
    exp, crm, gw, llm, deps = setup_case(case_dir, tmp_path)
    res = run(case_dir if exp.get("realistic") else ROOT / "cases" / exp["packet"], deps, case=exp["case"])

    got = {(i.kind.value, i.field): i for i in res.issues}
    for e in exp["issues"]:
        assert (e["kind"], e["field"]) in got, f"missing issue {e} in {list(got)}"
        if "sources" in e:
            assert [(s["doc"], s["value"]) for s in got[(e["kind"], e["field"])].sources] == [(s["doc"], s["value"]) for s in e["sources"]]
    assert sorted(res.flags) == sorted(exp["flags"])

    if exp["checklist"] == "UNKNOWN":
        assert res.checklist == "UNKNOWN"
    else:
        for k in ("required", "missing", "docs_present"):
            assert res.checklist[k] == exp["checklist"][k]

    assert res.write_outcome == exp["write_outcome"]
    c = exp["crm"]
    if c["action"] == "NO_WRITE":
        assert res.plan.record_id is None
        if "candidates" in exp:
            assert res.candidates == exp["candidates"]
    else:
        assert (res.plan.record_id, res.plan.status, res.plan.field_patch) == (c["target_record"], c["status"], c["field_patch"])
        notes = " ".join(res.plan.notes)
        assert all(n in notes for n in c["notes_contain"])
        assert MockCRM(crm.path).get(c["target_record"])["version"] == c["version_after"]

    attempts = Counter(a["tool"] for a in gw.audit)
    for m in exp["tool_calls"]["must"]:
        if "times" in m:
            assert attempts[m["tool"]] == m["times"], m["tool"]
        assert attempts[m["tool"]] >= m.get("min_times", 1), m["tool"]
        if "args_subset" in m:
            assert all(_subset(m["args_subset"], a["args"]) for a in gw.audit if a["tool"] == m["tool"])
    for m in exp["tool_calls"]["must_not"]:
        assert attempts[m["tool"]] == 0, f"{m['tool']} must not be called: {m['reason']}"
    if "retry" in exp:
        assert crm.writes == exp["retry"]["effective_writes"]
        if exp["retry"].get("same_idempotency_key"):
            assert len({a["args"]["idempotency_key"] for a in gw.audit if a["tool"] == "crm.update"}) == 1

    assert set(llm.calls) == set(exp["llm_calls"]["expected_doc_ids"])
    assert not set(llm.calls) & set(exp["llm_calls"]["must_not_call"])
    for doc, n in exp.get("llm_calls_per_doc", {}).items():
        assert llm.calls.count(doc) == n

    md = to_markdown(res)
    for s in exp["report"]["must_not_contain"]:
        assert s.lower() not in md.lower(), s
    rec_status = res.record_after["status"] if res.record_after else None
    assert rec_status not in exp["never_status"]


def test_crm_find_failure_is_crm_unavailable_not_no_match(tmp_path):
    from visa_agent.tools.faults import FaultPlan
    exp, crm, gw, llm, deps = setup_case(ROOT / "cases" / "case01_happy", tmp_path)
    crm.faults["find"] = FaultPlan("tool_down")
    res = run(ROOT / "cases" / "case01_happy", deps, case="case01_happy")
    assert (res.plan.reason, res.plan.record_id, res.write_outcome) == ("crm_unavailable", None, "NO_WRITE")
    assert "no CRM record matches" not in to_markdown(res)
    assert not any(a["tool"] == "crm.update" for a in gw.audit)
