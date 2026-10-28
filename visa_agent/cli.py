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
from dotenv import dotenv_values, find_dotenv

from .llm.fake import FakeLLM
from .orchestrator import HERE, Deps, run
from .report import save, to_json, to_markdown
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
    for k, v in dotenv_values(find_dotenv(usecwd=True)).items():  # .env supplies keys/models only, never overriding the environment.
        if k != "LLM_PROVIDER" and v is not None:  # the provider stays per-command (replay/fake) unless exported
            os.environ.setdefault(k, v)
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
    d = sub.add_parser("demo")
    d.add_argument("--record", action="store_true", help="also write deterministic docs/demo_output/ (replay, no network)")
    e = sub.add_parser("eval")
    e.add_argument("--live", action="store_true", help="real provider (LLM_PROVIDER, default gemini)")
    e.add_argument("--record", action="store_true", help="with --live: save responses for replay")
    e.add_argument("--set", choices=["clean", "realistic"], default="clean", help="generated cases or mock_data/realistic")
    e.add_argument("--only", nargs="*", help="case-name prefixes, e.g. R1 R2")
    c = sub.add_parser("case", help="one mock case with its fault plan (e.g. case09), report to stdout")
    c.add_argument("name")
    c.add_argument("--dry-run", action="store_true")
    sub.add_parser("test-report")
    a = ap.parse_args(argv)
    if a.cmd != "run":
        from . import commands
        return getattr(commands, {"test-report": "test_report"}.get(a.cmd, a.cmd))(a)

    if not a.packet.exists():  # short names: R6 -> mock_data/realistic/cases/R6_injection_fineprint, case03 -> ...
        roots = [a.packet.parent, HERE.parent / "mock_data" / "realistic" / "cases", HERE.parent / "mock_data" / "cases"]
        a.packet = next((m for r in roots for m in sorted(r.glob(a.packet.name + "*")) if m.is_dir()), a.packet)
    own_seed = a.packet.parent.parent / "crm_seed.json"  # mock_data/realistic/crm_seed.json for realistic cases
    seed = own_seed if own_seed.exists() else SEED
    if not a.crm.exists():  # a mock case's expected.json says which seed records exist for it
        shutil.copy(seed, a.crm)
        exp = a.packet / "expected.json"
        if exp.exists():
            keep = json.loads(exp.read_text())["crm"]["records_in_seed"]
            recs = [x for x in json.loads(seed.read_text())["records"] if x["id"] in keep]
            a.crm.write_text(json.dumps({"records": recs}, indent=2))
    fake = a.fake_llm or a.packet / "fake_llm.json"
    script = json.loads(fake.read_text())["script"] if fake.exists() else {}
    agent_script = json.loads(a.agent_script.read_text()) if a.agent_script else None
    llm = FakeLLM(a.packet.name, {(a.packet.name, k): v for k, v in script.items()}, agent_script)
    prov = os.getenv("LLM_PROVIDER") or "fake"
    if not fake.exists() and a.mode != "agent":  # realistic packets: no scripted output; replay the recorded real model
        from .llm.replay import make_llm
        llm = make_llm(a.packet.name, a.packet, provider="replay" if prov == "fake" else prov, record=a.record)
        print(f"No fake_llm.json: using {llm.name} ({getattr(llm, 'model', '')})")
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
        exp = a.packet / "expected.json"
        result = run(a.packet, deps, dry_run=a.dry_run, ocr=json.loads(exp.read_text()).get("ocr") if exp.exists() else None)
    out_dir = save(result, Path(os.getenv("AUDIT_DIR", "runs")))
    print(to_json(result) if a.json else to_markdown(result))
    print(f"Report saved: {out_dir}/report.md, report.json")
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
