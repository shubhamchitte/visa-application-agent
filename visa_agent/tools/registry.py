"""Builds the ToolSpecs for the gateway from a MockCRM and checklist settings."""
from functools import partial
from pathlib import Path

from visa_agent.tools.checklist import RULES_DIR, check
from visa_agent.tools.crm import MockCRM
from visa_agent.tools.faults import FaultPlan
from visa_agent.tools.gateway import ToolSpec

_S = {"type": "string"}


def build_tools(crm: MockCRM, rules_dir: Path = RULES_DIR, checklist_faults: FaultPlan | None = None) -> dict[str, ToolSpec]:
    obj = lambda props, req: {"type": "object", "additionalProperties": False, "required": req, "properties": props}
    return {
        "crm.find": ToolSpec("crm.find", obj({"passport_no": _S, "dob": _S}, ["passport_no", "dob"]), crm.find),
        "crm.get": ToolSpec("crm.get", obj({"id": _S}, ["id"]), crm.get),
        "crm.update": ToolSpec("crm.update", obj({
            "id": _S, "expected_version": {"type": "integer"},
            "patch": {"type": "object", "additionalProperties": _S}, "status": _S,
            "notes": {"type": "array", "items": _S}}, ["id", "patch", "expected_version"]), crm.update, writes=True),
        "checklist.check": ToolSpec("checklist.check", obj({"visa_type": _S, "docs_present": {"type": "array", "items": _S}},
                                                           ["visa_type", "docs_present"]),
                                    partial(check, rules_dir=rules_dir, faults=checklist_faults)),
    }
