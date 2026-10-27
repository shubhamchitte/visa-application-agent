"""`--mode agent` (P5.5): the LLM proposes tool calls in a bounded loop; code still decides what may be written.
The LLM sees tool specs + verified state only (never raw document text). Every call goes through the
ToolGateway, and a crm.update must also be a subset of the deterministic WritePlan, else it is rejected,
audit-logged and fed back as an observation."""
from pathlib import Path
from typing import Any

from .orchestrator import Deps, load_config, merge_values, read_back, run
from .schemas import RunResult, WritePlan
from .tools.gateway import GuardRejected, ToolError

MAX_STEPS = 6


def plan_guard(args: dict[str, Any], plan: WritePlan) -> str | None:
    """Reason to reject a crm.update that goes beyond the plan, or None if it is within it."""
    if plan.record_id is None:
        return "plan is NO_WRITE"
    if args.get("id") != plan.record_id:
        return f"id {args.get('id')!r} is not the planned record {plan.record_id!r}"
    extra = {k: v for k, v in (args.get("patch") or {}).items() if plan.field_patch.get(k) != v}
    if extra:
        return f"patch beyond plan: {sorted(extra)}"
    if args.get("status") not in (None, plan.status):
        return f"status {args.get('status')!r} is not the planned {plan.status!r}"
    if not set(args.get("notes") or []) <= set(plan.notes):
        return "notes beyond plan"
    return None


def agent_state(res: RunResult, cfg: dict) -> dict[str, Any]:
    return {"verified_fields": merge_values(res.extractions, cfg["fields"]["fields"]),
            "issues": [i.model_dump(mode="json") for i in res.issues], "checklist": res.checklist,
            "candidates": res.candidates, "plan": res.plan.model_dump(mode="json")}


def run_agent(packet: Path, deps: Deps, case: str | None = None, max_steps: int = MAX_STEPS) -> RunResult:
    cfg = load_config()
    res = run(packet, deps, dry_run=True, case=case, cfg=cfg)  # verified state + the plan; no write
    gw, plan, state = deps.gateway, res.plan, agent_state(res, cfg)
    history: list[dict[str, Any]] = []
    res.write_outcome = "NO_WRITE"
    for _ in range(max_steps):
        call = deps.llm.propose_tool_call(state, gw.specs(), history)
        if call.get("done"):
            break
        name, args = call.get("tool"), call.get("args") or {}
        why = plan_guard(args, plan) if name == "crm.update" else None
        try:
            if why:
                gw._log(name, args, attempt=0, outcome="REJECTED", error=f"plan guard: {why}")
                raise GuardRejected(f"plan guard: {why}")
            obs = {"ok": gw.call(name, args)}
            if name == "crm.update":
                res.write_outcome = "WRITTEN"
                problem = read_back(gw, plan, res)  # verify the real record against the full plan, not the agent's claim
                if problem:
                    res.write_outcome, res.error = "WRITE_FAILED", f"agent write incomplete or wrong:{problem}"
                    obs["readback"] = problem
        except (GuardRejected, ToolError) as e:
            obs = {"rejected" if isinstance(e, GuardRejected) else "error": str(e)}
            if name == "crm.update" and isinstance(e, ToolError):
                res.write_outcome, res.error = "WRITE_FAILED", f"crm.update failed: {e}"
        history.append({"call": {"tool": name, "args": args}, "observation": obs})
    else:
        res.flags.append("agent_step_limit")
    res.audit = list(gw.audit)
    return res
