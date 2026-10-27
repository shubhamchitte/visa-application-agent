import json
from pathlib import Path

import pytest
import yaml

from visa_agent.tools.crm import MockCRM
from visa_agent.tools.faults import FaultPlan
from visa_agent.tools.gateway import RetryPolicy, ToolError, ToolGateway
from visa_agent.tools.registry import build_tools

POLICY = yaml.safe_load((Path(__file__).parents[1] / "visa_agent/policy.yaml").read_text())


def rec(id, pp="P1", dob="1990-01-01"):
    return {"id": id, "version": 1, "status": "NEW", "notes": [], "fields": {"passport_number": pp, "date_of_birth": dob}}


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "crm.json"
    p.write_text(json.dumps([rec("R1"), rec("R2", "P2"), rec("R3", "P3"), rec("R4", "P3")]))
    return p


def gw(crm, checklist_faults=None):
    return ToolGateway(tools=build_tools(crm, checklist_faults=checklist_faults), allowlist={"crm.find", "crm.get", "crm.update", "checklist.check"},
                       field_whitelist=set(POLICY["field_whitelist"]), status_allowlist=set(POLICY["allowed_statuses"]),
                       retry=RetryPolicy(sleep=lambda s: None, rand=lambda: 0.5))


UPD = {"id": "R1", "patch": {"email": "a@b.uto"}, "expected_version": 1, "status": "DATA_UPDATED"}


def test_find_no_match_and_multiple(db):
    g = gw(MockCRM(db))
    assert g.call("crm.find", {"passport_no": "NOPE", "dob": "1990-01-01"}) == []
    assert [r["id"] for r in g.call("crm.find", {"passport_no": "P3", "dob": "1990-01-01"})] == ["R3", "R4"]
    assert len(g.call("crm.find", {"passport_no": "P1", "dob": "1990-01-01"})) == 1


def test_update_bumps_version_persists_and_never_creates(db):
    crm = MockCRM(db)
    out = gw(crm).call("crm.update", UPD)
    assert out["version"] == 2 and out["fields"]["email"] == "a@b.uto" and out["status"] == "DATA_UPDATED"
    assert MockCRM(db).get("R1")["version"] == 2
    with pytest.raises(ToolError) as e:
        crm.update("NEW-ID", {"email": "x"}, 1, "k")
    assert e.value.status == 404 and len(crm.records) == 4


def test_503_twice_then_ok_one_write(db):
    crm = MockCRM(db, {"update": FaultPlan("fail_first_n", n=2)})
    g = gw(crm)
    assert g.call("crm.update", UPD)["version"] == 2
    assert crm.writes == 1 and [a["outcome"] for a in g.audit] == ["RETRY", "RETRY", "OK"]


def test_timeout_but_applied_one_write_same_key(db):
    crm = MockCRM(db, {"update": FaultPlan("timeout_but_applied")})
    g = gw(crm)
    out = g.call("crm.update", UPD)
    assert crm.writes == 1 and out["version"] == 2 and len(g.audit) == 2
    assert len(crm.idempotency) == 1


def test_idempotent_rerun_with_fresh_crm_and_gateway(db):
    gw(MockCRM(db)).call("crm.update", UPD)
    crm2 = MockCRM(db)
    assert gw(crm2).call("crm.update", UPD)["version"] == 2 and crm2.writes == 0


@pytest.mark.parametrize("mode,status", [("conflict_409", 409), ("invalid_422", 422)])
def test_4xx_faults_one_attempt(db, mode, status):
    crm = MockCRM(db, {"update": FaultPlan(mode)})
    g = gw(crm)
    with pytest.raises(ToolError) as e:
        g.call("crm.update", UPD)
    assert e.value.status == status and len(g.audit) == 1 and crm.writes == 0


def test_real_version_mismatch_409(db):
    g = gw(MockCRM(db))
    with pytest.raises(ToolError) as e:
        g.call("crm.update", {**UPD, "expected_version": 7})
    assert e.value.status == 409 and len(g.audit) == 1


def test_always_fail_and_tool_down_exhaust_retries(db):
    for plan in (FaultPlan("always_fail"), FaultPlan("tool_down")):
        crm = MockCRM(db, {"update": plan})
        g = gw(crm)
        with pytest.raises(ToolError):
            g.call("crm.update", UPD)
        assert len(g.audit) == 3 and crm.writes == 0


def test_malformed_response_is_error_not_data(db):
    g = gw(MockCRM(db, {"find": FaultPlan("malformed")}))
    with pytest.raises(ToolError, match="malformed"):
        g.call("crm.find", {"passport_no": "P1", "dob": "1990-01-01"})


def test_checklist_ok():
    r = gw(None and None or MockCRM.__new__(MockCRM)).call("checklist.check", {"visa_type": "TOURIST_UTO", "docs_present": ["passport", "application_form", "extra"]})
    assert r == {"required": ["application_form", "passport", "bank_statement"], "present": ["application_form", "passport"], "missing": ["bank_statement"]}


@pytest.mark.parametrize("mode", ["tool_down", "always_fail", "malformed"])
def test_checklist_down_is_error_never_complete(db, mode):
    g = gw(MockCRM(db), checklist_faults=FaultPlan(mode))
    with pytest.raises(ToolError):
        g.call("checklist.check", {"visa_type": "TOURIST_UTO", "docs_present": ["application_form", "passport", "bank_statement"]})


def test_checklist_unknown_visa_type_is_404():
    with pytest.raises(ToolError) as e:
        gw(MockCRM.__new__(MockCRM)).call("checklist.check", {"visa_type": "NOPE", "docs_present": []})
    assert e.value.status == 404
