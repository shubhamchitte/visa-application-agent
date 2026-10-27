"""CLI: `run <packet> [--dry-run] ...` | `demo` | `eval [--live] [--record]` | `test-report`.
`run` is offline (FakeLLM from <packet>/fake_llm.json); demo/eval pick the provider via LLM_PROVIDER."""
import argparse
import json
import os
import shutil
import sys
from datetime import date
from pathlib import Path

import yaml

from .llm.fake import FakeLLM
from .orchestrator import HERE, Deps, run
from .report import to_json, to_markdown
from .tools.crm import MockCRM
from .tools.gateway import ToolGateway
from .tools.registry import build_tools

SEED = HERE.parent / "mock_data" / "crm_seed.json"


def build_gateway(crm: MockCRM, checklist_faults=None, **kw) -> ToolGateway:
    policy = yaml.safe_load((HERE / "policy.yaml").read_text())
    tools = build_tools(crm, checklist_faults=checklist_faults)
    return ToolGateway(tools=tools, allowlist=set(tools), field_whitelist=set(policy["field_whitelist"]),
                       status_allowlist=set(policy["allowed_statuses"]), **kw)


def _audit_path() -> Path:
    p = Path(os.getenv("AUDIT_DIR", "runs")) / "audit.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="visa_agent")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("packet", type=Path)
    r.add_argument("--dry-run", action="store_true")
    r.add_argument("--crm", type=Path, default=Path("crm_state.json"), help="working CRM file (copied from the seed if absent)")
    r.add_argument("--fake-llm", type=Path, help="default: <packet>/fake_llm.json")
    r.add_argument("--today", type=date.fromisoformat, default=date.today())
    r.add_argument("--mode", choices=["deterministic", "agent"], default="deterministic")
    r.add_argument("--agent-script", type=Path, help="agent mode: JSON list of scripted tool calls (offline demo)")
    r.add_argument("--record", action="store_true", help="agent mode with LLM_PROVIDER=groq: save to mock_data/replay/agent_<case>.json")
    r.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    sub.add_parser("demo")
    e = sub.add_parser("eval")
    e.add_argument("--live", action="store_true", help="real provider (LLM_PROVIDER, default gemini)")
    e.add_argument("--record", action="store_true", help="with --live: save responses for replay")
    sub.add_parser("test-report")
    a = ap.parse_args(argv)
    if a.cmd != "run":
        from . import commands
        return getattr(commands, {"test-report": "test_report"}.get(a.cmd, a.cmd))(a)

    if not a.crm.exists():  # a mock case's expected.json says which seed records exist for it
        shutil.copy(SEED, a.crm)
        exp = a.packet / "expected.json"
        if exp.exists():
            keep = json.loads(exp.read_text())["crm"]["records_in_seed"]
            recs = [x for x in json.loads(SEED.read_text())["records"] if x["id"] in keep]
            a.crm.write_text(json.dumps({"records": recs}, indent=2))
    script = json.loads((a.fake_llm or a.packet / "fake_llm.json").read_text())["script"]
    agent_script = json.loads(a.agent_script.read_text()) if a.agent_script else None
    llm = FakeLLM(a.packet.name, {(a.packet.name, k): v for k, v in script.items()}, agent_script)
    prov = os.getenv("LLM_PROVIDER") or "fake"
    if a.mode == "agent" and prov != "fake" and not agent_script:  # real/replayed agent: recordings are agent_<case>.json
        from .llm.replay import make_llm
        llm = make_llm(a.packet.name, a.packet, f"agent_{a.packet.name}", provider=prov, record=a.record)
    label = "agent (fake, scripted)" if isinstance(llm, FakeLLM) else f"agent ({prov}{', replayed ' + llm.model if prov == 'replay' else ''})"
    gw = build_gateway(MockCRM(a.crm), audit_path=_audit_path())
    deps = Deps(llm=llm, gateway=gw, today=lambda: a.today)
    if a.mode == "agent":
        from .agent_mode import run_agent
        print(f"Mode: {label}")
        result = run_agent(a.packet, deps)
    else:
        result = run(a.packet, deps, dry_run=a.dry_run)
    print(to_json(result) if a.json else to_markdown(result))
    if a.mode == "agent":
        print("Agent tool calls (gateway audit; REJECTED = plan guard / allowlist blocked it):")
        for x in result.audit:
            print(f"  {x['tool']} -> {x['outcome']}" + (f" ({x['error']})" if x.get("error") else ""))
    if a.dry_run and result.plan and result.plan.record_id:
        print("Dry-run CRM diff:", json.dumps({"id": result.plan.record_id, "status": result.plan.status,
                                                "patch": result.plan.field_patch}, indent=2))
    return 0 if result.write_outcome != "WRITE_FAILED" else 1


if __name__ == "__main__":
    sys.exit(main())
