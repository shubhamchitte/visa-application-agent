"""Checklist tool: rules/<visa_type>.yaml -> {required, present, missing}."""
from pathlib import Path
from typing import Any

import yaml

from visa_agent.tools.faults import FaultPlan, expect_dict
from visa_agent.tools.gateway import ToolError

RULES_DIR = Path(__file__).parents[2] / "rules"


def check(visa_type: str, docs_present: list[str], rules_dir: Path = RULES_DIR,
          faults: FaultPlan | None = None) -> dict[str, Any]:
    def op() -> dict[str, Any]:
        f = Path(rules_dir) / f"{visa_type}.yaml"
        if not f.is_file():
            raise ToolError(404, f"no rules for visa type {visa_type}")
        required = list(yaml.safe_load(f.read_text())["required_docs"])
        present = [d for d in required if d in set(docs_present)]
        return {"required": required, "present": present, "missing": [d for d in required if d not in present]}
    return expect_dict(faults.run(op) if faults else op(), "checklist.check")
