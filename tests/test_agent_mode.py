"""P5.5 agent mode: scripted FakeLLM proposals go through the gateway + WritePlan guard."""
import json

from visa_agent.agent_mode import MAX_STEPS, run_agent
from visa_agent.orchestrator import run
from tests.test_scenarios import ROOT, setup_case

CASE01 = ROOT / "cases" / "case01_happy"


def _agent(tmp_path, script):
    exp, crm, gw, llm, deps = setup_case(CASE01, tmp_path)
    llm.agent_script = script
    return run_agent(CASE01, deps, case=exp["case"]), crm, tmp_path / "crm.json"


def _updates(res, outcome):
    return [a for a in res.audit if a["tool"] == "crm.update" and a["outcome"] == outcome]


def test_out_of_plan_writes_rejected_and_logged(tmp_path):
    seen = []
    def beyond_plan(state, history):
        seen.append(history[-1]["observation"])
        rid = state["plan"]["record_id"]
        return {"tool": "crm.update", "args": {"id": rid, "patch": {"nationality": "XX"}, "expected_version": 1}}
    approve = lambda s, h: {"tool": "crm.update", "args": {"id": s["plan"]["record_id"], "patch": {},
                                                             "expected_version": 1, "status": "APPROVED"}}
    before = (ROOT / "crm_seed.json").read_text()
    res, crm, f = _agent(tmp_path, [approve, beyond_plan, lambda s, h: seen.append(h[-1]["observation"]) or {"done": True}])
    assert len(_updates(res, "REJECTED")) == 2 and not _updates(res, "OK")
    assert all("plan guard" in a["error"] for a in _updates(res, "REJECTED"))
    assert "status 'APPROVED'" in seen[0]["rejected"] and "patch beyond plan" in seen[1]["rejected"]
    assert res.write_outcome == "NO_WRITE"
    seed = {r["id"]: r for r in json.loads(before)["records"]}
    for r in json.loads(f.read_text())["records"]:
        assert r == seed[r["id"]]  # zero writes


def test_agent_following_plan_matches_deterministic(tmp_path):
    def follow(state, history):
        p = state["plan"]
        return {"tool": "crm.update", "args": {"id": p["record_id"], "patch": p["field_patch"], "expected_version": 1,
                                               "status": p["status"], "notes": p["notes"]}}
    (tmp_path / "a").mkdir(), (tmp_path / "d").mkdir()
    res, _, f = _agent(tmp_path / "a", [follow])
    exp, crm, gw, llm, deps = setup_case(CASE01, tmp_path / "d")
    det = run(CASE01, deps, case=exp["case"])
    assert res.write_outcome == det.write_outcome == "WRITTEN"
    strip = lambda p: [{k: v for k, v in r.items() if k != "idempotency"} for r in json.loads(p.read_text())["records"]]
    assert strip(f) == strip(tmp_path / "d" / "crm.json")


def test_step_limit(tmp_path):
    get = lambda s, h: {"tool": "crm.get", "args": {"id": s["plan"]["record_id"]}}
    res, _, _ = _agent(tmp_path, [get] * 20)
    assert "agent_step_limit" in res.flags and res.write_outcome == "NO_WRITE"
    assert len([a for a in res.audit if a["tool"] == "crm.get"]) == MAX_STEPS


def test_agent_readback_reports_partial_write(tmp_path):
    """The agent writes only part of the plan: the real record is read back and the mismatch is reported."""
    def partial(state, history):
        p = state["plan"]
        k = next(iter(p["field_patch"]))
        return {"tool": "crm.update", "args": {"id": p["record_id"], "patch": {k: p["field_patch"][k]}, "expected_version": 1}}
    res, _, _ = _agent(tmp_path, [partial, lambda s, h: {"done": True}])
    assert res.write_outcome == "WRITE_FAILED" and "does not match the plan" in res.error
    assert [a["tool"] for a in res.audit if a["tool"] == "crm.get"][-1] == "crm.get" and res.record_after["version"] == 2


def test_agent_readback_ok_sets_real_version(tmp_path):
    def follow(state, history):
        p = state["plan"]
        return {"tool": "crm.update", "args": {"id": p["record_id"], "patch": p["field_patch"], "expected_version": 1, "status": p["status"], "notes": p["notes"]}}
    res, _, _ = _agent(tmp_path, [follow, lambda s, h: {"done": True}])
    assert res.write_outcome == "WRITTEN" and res.error is None and res.record_after["version"] == 2
