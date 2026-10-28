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
REALISTIC = CASES.parent / "realistic" / "cases"  # real-layout packets (own crm_seed.json one level up, no fake_llm.json)


def packet_dir(case_dir: Path, exp: dict) -> Path:
    return case_dir if exp.get("realistic") else CASES / exp["packet"]


def run_case(name: str | Path, make_llm, tmp: Path, dry_run: bool = False):
    """Return (expected, result, llm). `name` = clean case name or a case dir. `make_llm(case, case_dir, packet_name)`."""
    d = Path(name) if isinstance(name, Path) else CASES / name
    exp = json.loads((d / "expected.json").read_text())
    seed_file = d.parent.parent / "crm_seed.json"
    seed = json.loads((seed_file if seed_file.exists() else SEED).read_text())["records"]
    crm_file = tmp / f"{d.name}_crm.json"
    crm_file.write_text(json.dumps({"records": [r for r in seed if r["id"] in exp["crm"]["records_in_seed"]]}))
    plans = fault_plan_from_golden(exp["fault_plan"])
    crm = MockCRM(crm_file, {t.split(".", 1)[1]: p for t, p in plans.items() if t.startswith("crm.")})
    gw = build_gateway(crm, checklist_faults=plans.get("checklist.check"),
                       retry=RetryPolicy(sleep=lambda s: None, rand=lambda: 0.5), clock=lambda: "T")
    llm = make_llm(exp["case"], d, Path(exp["packet"]).name)
    res = run(packet_dir(d, exp), Deps(llm=llm, gateway=gw, today=lambda: date.fromisoformat(exp["clock"])),
              dry_run=dry_run, case=exp["case"])
    return exp, res, llm
