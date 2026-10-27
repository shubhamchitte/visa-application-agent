import json
from pathlib import Path

import pytest

from visa_agent.tools.faults import fault_plan_from_golden

CASES = sorted((Path(__file__).resolve().parent.parent / "mock_data" / "cases").glob("*/expected.json"))


@pytest.mark.parametrize("path", CASES, ids=lambda p: p.parent.name)
def test_golden_fault_plan_maps(path):
    entries = json.loads(path.read_text())["fault_plan"]
    plans = fault_plan_from_golden(entries)
    assert set(plans) == {e["tool"] for e in entries}


def test_specific_mappings():
    p = fault_plan_from_golden([{"tool": "crm.update", "call": 1, "fault": {"status": 503}},
                                {"tool": "crm.update", "call": 2, "fault": {"status": 503}}])["crm.update"]
    assert (p.mode, p.n, p.status) == ("fail_first_n", 2, 503)
    assert fault_plan_from_golden([{"tool": "checklist.check", "call": "all", "fault": {"status": 503}}])["checklist.check"].mode == "always_fail"
