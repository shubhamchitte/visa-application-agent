"""FaultPlan: deterministic fault injection for mock tools. Errors are ToolError, so they map straight onto
the gateway's retry taxonomy (429/5xx/timeout retry; 4xx never)."""
from dataclasses import dataclass
from typing import Any, Callable

from visa_agent.tools.gateway import ToolError

MODES = {"none", "fail_first_n", "always_fail", "timeout_but_applied", "conflict_409", "invalid_422", "malformed", "tool_down"}
MALFORMED = "<<malformed response>>"  # what a broken upstream returns instead of a JSON object


@dataclass
class FaultPlan:
    mode: str = "none"
    n: int = 1          # fail_first_n / timeout_but_applied: how many calls are affected
    status: int = 503   # fail_first_n / always_fail
    calls: int = 0      # calls seen so far (state)

    def __post_init__(self):
        if self.mode not in MODES:
            raise ValueError(f"unknown fault mode {self.mode!r}")

    def run(self, op: Callable[[], Any]) -> Any:
        """Run `op` (the real tool action) under the fault plan."""
        self.calls += 1
        m = self.mode
        if m == "fail_first_n" and self.calls <= self.n:
            raise ToolError(self.status, "injected transient failure")      # op NOT executed
        if m == "always_fail":
            raise ToolError(self.status, "injected permanent failure")
        if m == "tool_down":
            raise ToolError(503, "tool down (connection refused)")
        if m == "conflict_409":
            raise ToolError(409, "injected version conflict")
        if m == "invalid_422":
            raise ToolError(422, "injected validation error")
        if m == "timeout_but_applied" and self.calls <= self.n:
            op()                                                             # server applied the write...
            raise ToolError(None, "injected timeout after apply", timeout=True)  # ...but the client never saw it
        if m == "malformed":
            return MALFORMED
        return op()


def expect_dict(result: Any, tool: str) -> Any:
    """Reject garbage from a tool. 502 (bad gateway) is retryable, like any broken upstream."""
    if not isinstance(result, (dict, list)):
        raise ToolError(502, f"{tool}: malformed response")
    return result


def fault_plan_from_golden(entries: list[dict[str, Any]]) -> dict[str, "FaultPlan"]:
    """Map the golden format [{tool, call: n|"all", fault: {status|timeout,applied}}] to {tool_name: FaultPlan}.
    Keys are full tool names (e.g. "crm.update"); MockCRM wants the op part ("update"). Edit here to add a fault kind."""
    plans: dict[str, FaultPlan] = {}
    by_tool: dict[str, list[dict[str, Any]]] = {}
    for e in entries:
        by_tool.setdefault(e["tool"], []).append(e)
    for tool, es in by_tool.items():
        f = es[0]["fault"]
        if f.get("timeout") and f.get("applied"):
            plans[tool] = FaultPlan("timeout_but_applied", n=len(es))
        elif f.get("timeout"):
            plans[tool] = FaultPlan("tool_down")
        elif f.get("status") == 409:
            plans[tool] = FaultPlan("conflict_409")
        elif f.get("status") == 422:
            plans[tool] = FaultPlan("invalid_422")
        elif any(e["call"] == "all" for e in es):
            plans[tool] = FaultPlan("always_fail", status=f["status"])
        else:
            plans[tool] = FaultPlan("fail_first_n", n=len(es), status=f["status"])
    return plans
