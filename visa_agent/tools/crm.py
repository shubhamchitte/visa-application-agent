"""Mock CRM (JSON file) with an HTTP-like interface and FaultPlan injection.
File shape: {"records": [{id, version, status, fields, notes}], "idempotency": {key: result}} (a bare list is accepted).
Never creates records."""
import copy
import json
from pathlib import Path
from typing import Any

from visa_agent.tools.faults import FaultPlan, expect_dict
from visa_agent.tools.gateway import ToolError


class MockCRM:
    def __init__(self, path: Path, faults: dict[str, FaultPlan] | None = None):
        self.path, self.faults = Path(path), faults or {}
        raw = json.loads(self.path.read_text())
        self.records: list[dict[str, Any]] = raw if isinstance(raw, list) else raw["records"]
        self.idempotency: dict[str, Any] = {} if isinstance(raw, list) else raw.get("idempotency", {})
        self.writes = 0  # effective writes, for tests

    def _save(self) -> None:
        self.path.write_text(json.dumps({"records": self.records, "idempotency": self.idempotency}, indent=2, sort_keys=True))

    def _run(self, op: str, fn):
        plan = self.faults.get(op) or self.faults.get("*")
        result = plan.run(fn) if plan else fn()
        return expect_dict(result, f"crm.{op}")

    def _record(self, id: str) -> dict[str, Any]:
        for r in self.records:
            if r["id"] == id:
                return r
        raise ToolError(404, f"no record {id}")

    def find(self, passport_no: str, dob: str) -> list[dict[str, Any]]:
        """Exact-key match on passport number + DOB. Returns 0, 1 or many records; the caller decides."""
        return self._run("find", lambda: copy.deepcopy([
            r for r in self.records
            if r["fields"].get("passport_number") == passport_no and r["fields"].get("date_of_birth") == dob]))

    def get(self, id: str) -> dict[str, Any]:
        return self._run("get", lambda: copy.deepcopy(self._record(id)))

    def update(self, id: str, patch: dict[str, str], expected_version: int, idempotency_key: str,
               status: str | None = None, notes: list[str] | None = None) -> dict[str, Any]:
        """409 on version mismatch; a repeated idempotency_key returns the prior result without a second write."""
        return self._run("update", lambda: self._apply(id, patch, expected_version, idempotency_key, status, notes))

    def _apply(self, id, patch, expected_version, key, status, notes):
        if key in self.idempotency:
            return copy.deepcopy(self.idempotency[key])
        rec = self._record(id)
        if not isinstance(patch, dict) or not all(isinstance(v, str) for v in patch.values()):
            raise ToolError(422, "patch must map field -> string")
        if rec["version"] != expected_version:
            raise ToolError(409, f"version mismatch: have {rec['version']}, expected {expected_version}")
        rec["fields"].update(patch)
        if status is not None:
            rec["status"] = status
        rec.setdefault("notes", []).extend(notes or [])
        rec["version"] += 1
        self.idempotency[key] = copy.deepcopy(rec)
        self.writes += 1
        self._save()
        return copy.deepcopy(rec)
