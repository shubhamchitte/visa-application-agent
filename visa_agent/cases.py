"""Run one mock case end to end against a temp CRM with its golden fault plan (used by demo / eval / test-report)."""
import json
from datetime import date
from pathlib import Path

from .cli import SEED, build_gateway
from .orchestrator import Deps, run
from .tools.crm import MockCRM
from .tools.faults import fault_plan_from_golden
from .tools.gateway import RetryPolicy

CASES = Path(__file__).resolve().parents[1] / "mock_data" / "cases"


def run_case(name: str, make_llm, tmp: Path, dry_run: bool = False):
    """Return (expected, result, llm). `make_llm(case, case_dir, packet_name)` builds the client."""
    exp = json.loads((CASES / name / "expected.json").read_text())
    seed = json.loads(SEED.read_text())["records"]
    crm_file = tmp / f"{name}_crm.json"
    crm_file.write_text(json.dumps({"records": [r for r in seed if r["id"] in exp["crm"]["records_in_seed"]]}))
    plans = fault_plan_from_golden(exp["fault_plan"])
    crm = MockCRM(crm_file, {t.split(".", 1)[1]: p for t, p in plans.items() if t.startswith("crm.")})
    gw = build_gateway(crm, checklist_faults=plans.get("checklist.check"),
                       retry=RetryPolicy(sleep=lambda s: None, rand=lambda: 0.5), clock=lambda: "T")
    llm = make_llm(exp["case"], CASES / name, exp["packet"])
    res = run(CASES / exp["packet"], Deps(llm=llm, gateway=gw, today=lambda: date.fromisoformat(exp["clock"])),
              dry_run=dry_run, case=exp["case"])
    return exp, res, llm
