import json
from pathlib import Path

import pytest
import yaml

from visa_agent.llm.base import Fatal, Malformed, RateLimited, Transient
from visa_agent.tools.gateway import GuardRejected, idempotency_key, validate_args, RetryPolicy, ToolError, ToolGateway, ToolSpec, is_retryable

POLICY = yaml.safe_load((Path(__file__).parents[1] / "visa_agent/policy.yaml").read_text())
UPDATE_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["id", "patch", "expected_version"],
    "properties": {"id": {"type": "string"}, "expected_version": {"type": "integer"},
                   "patch": {"type": "object", "additionalProperties": {"type": "string"}},
                   "status": {"type": "string"}},
}


class FlakyUpdate:
    """Raises the queued errors in order, then succeeds. Records every call's kwargs."""
    def __init__(self, *errors):
        self.errors, self.calls = list(errors), []

    def __call__(self, **kw):
        self.calls.append(kw)
        if self.errors:
            raise self.errors.pop(0)
        return {"version": kw["expected_version"] + 1}


def make_gw(handler, sleeps=None, tmp_path=None):
    return ToolGateway(
        tools={"crm.update": ToolSpec("crm.update", UPDATE_SCHEMA, handler, writes=True)},
        allowlist={"crm.update"}, field_whitelist=set(POLICY["field_whitelist"]),
        status_allowlist=set(POLICY["allowed_statuses"]),
        retry=RetryPolicy(sleep=(sleeps.append if sleeps is not None else lambda s: None), rand=lambda: 0.5),
        audit_path=(tmp_path / "audit.jsonl") if tmp_path else None,
        run_id="run-test", clock=lambda: "2026-10-27T00:00:00Z")


ARGS = {"id": "R1", "patch": {"email": "a@b.uto"}, "expected_version": 3, "status": "DATA_UPDATED"}


@pytest.mark.parametrize("err,expected", [
    (ToolError(429), True), (ToolError(503), True), (ToolError(500), True), (ToolError(None, timeout=True), True),
    (TimeoutError(), True), (ToolError(400), False), (ToolError(404), False), (ToolError(409), False),
    (ToolError(422), False), (ValueError(), False),
    (RateLimited(), True), (Transient(), True), (Malformed(), False), (Fatal(), False),
])
def test_retry_classification(err, expected):
    assert is_retryable(err) is expected


def test_503_twice_then_ok_reuses_idempotency_key():
    h = FlakyUpdate(ToolError(503), ToolError(503))
    assert make_gw(h).call("crm.update", ARGS) == {"version": 4}
    assert len(h.calls) == 3
    assert {c["idempotency_key"] for c in h.calls} == {idempotency_key("crm.update", ARGS)}


def test_timeout_retry_uses_same_key():
    h = FlakyUpdate(ToolError(None, timeout=True))
    make_gw(h).call("crm.update", ARGS)
    assert h.calls[0]["idempotency_key"] == h.calls[1]["idempotency_key"]


class DedupingCRM:
    """Applies each idempotency key once, like the P2 mock CRM will."""
    def __init__(self):
        self.applied: dict[str, dict] = {}

    def __call__(self, **kw):
        return self.applied.setdefault(kw["idempotency_key"], {"version": kw["expected_version"] + 1})


def test_rerun_with_fresh_gateway_writes_once():
    crm = DedupingCRM()
    make_gw(crm).call("crm.update", ARGS)
    make_gw(crm).call("crm.update", ARGS)  # second CLI run of the same packet
    assert len(crm.applied) == 1


def test_different_args_get_different_key():
    assert idempotency_key("crm.update", ARGS) != idempotency_key("crm.update", {**ARGS, "expected_version": 4})


def test_unsupported_schema_keyword_raises():
    with pytest.raises(ValueError, match="pattern"):
        validate_args({"type": "string", "pattern": "^A"}, "B")


@pytest.mark.parametrize("status", [409, 422])
def test_4xx_not_retried(status):
    h = FlakyUpdate(ToolError(status))
    with pytest.raises(ToolError):
        make_gw(h).call("crm.update", ARGS)
    assert len(h.calls) == 1


def test_gives_up_after_max_3_attempts():
    h = FlakyUpdate(*[ToolError(503)] * 5)
    with pytest.raises(ToolError):
        make_gw(h).call("crm.update", ARGS)
    assert len(h.calls) == 3


def test_retry_after_honored_and_jitter_bounded():
    sleeps = []
    make_gw(FlakyUpdate(ToolError(429, retry_after=2.0), ToolError(503)), sleeps).call("crm.update", ARGS)
    assert sleeps == [2.0, 0.5 * 2 * 0.5]  # Retry-After, then base*2^(n-1)*jitter


def test_rejects_approved_status_and_logs_it():
    h = FlakyUpdate()
    gw = make_gw(h)
    with pytest.raises(GuardRejected, match="APPROVED"):
        gw.call("crm.update", {**ARGS, "status": "APPROVED"})
    assert h.calls == []
    assert gw.audit[-1]["outcome"] == "REJECTED"


def test_rejects_non_whitelisted_field():
    h = FlakyUpdate()
    with pytest.raises(GuardRejected, match="not whitelisted"):
        make_gw(h).call("crm.update", {**ARGS, "patch": {"visa_decision": "yes"}})
    assert h.calls == []


@pytest.mark.parametrize("name,args", [
    ("crm.delete", {"id": "R1"}),
    ("crm.update", {"id": "R1", "patch": {}}),                                 # missing expected_version
    ("crm.update", {**ARGS, "expected_version": "3"}),                         # wrong type
    ("crm.update", {**ARGS, "create": True}),                                  # unknown arg
    ("crm.update", {**ARGS, "idempotency_key": "caller-chosen"}),              # key is gateway-owned
])
def test_rejects_bad_calls(name, args):
    h = FlakyUpdate()
    with pytest.raises(GuardRejected):
        make_gw(h).call(name, args)
    assert h.calls == []


def test_audit_jsonl_has_one_line_per_attempt(tmp_path):
    make_gw(FlakyUpdate(ToolError(503)), tmp_path=tmp_path).call("crm.update", ARGS)
    lines = (tmp_path / "audit.jsonl").read_text().splitlines()
    assert len(lines) == 2 and '"RETRY"' in lines[0] and '"OK"' in lines[1]
    entry = json.loads(lines[0])
    assert entry["run_id"] == "run-test" and entry["ts"] == "2026-10-27T00:00:00Z"
