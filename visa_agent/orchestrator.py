"""Linear pipeline: ingest -> classify -> extract -> verify -> validate -> checklist -> decide -> crm -> (report).
Each step returns data; the only side effects go through the ToolGateway."""
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Callable

import yaml

from . import extract as ex, ingest as ing, policy as pol, validators, verify as ver
from .llm.base import LLMClient
from .schemas import Extraction, FieldStatus, Issue, IssueKind, RunResult, WritePlan
from .tools.gateway import GuardRejected, ToolError, ToolGateway

HERE = Path(__file__).parent
VISA_TYPE = "TOURIST_UTO"


@dataclass
class Deps:
    llm: LLMClient
    gateway: ToolGateway
    today: Callable[[], date]


def load_config(rules_dir: Path = HERE.parent / "rules") -> dict[str, Any]:
    y = lambda p: yaml.safe_load(Path(p).read_text())
    return {"fields": y(HERE / "fields.yaml"), "doc_types": y(HERE / "doc_types.yaml"),
            "policy": y(HERE / "policy.yaml"), "rules": y(Path(rules_dir) / f"{VISA_TYPE}.yaml")}


def _unverifiable(fields: list[str], doc_type: str, reason: str) -> list[Issue]:
    return [Issue(kind=IssueKind.UNVERIFIABLE, field=f, message=f"{doc_type}: {reason}") for f in fields]


def merge_values(extractions: dict[str, Extraction], fields_cfg: dict[str, Any]) -> dict[str, str]:
    """One value per field: the first VERIFIED value in fields.yaml source order (conflicts are reported elsewhere)."""
    out = {}
    for name, cfg in fields_cfg.items():
        for d in cfg["source"]:
            f = extractions[d].fields.get(name) if d in extractions else None
            if f and f.status == FieldStatus.VERIFIED:
                out.setdefault(name, f.value)
    return out


def identity(extractions: dict[str, Extraction], issues: list[Issue]) -> tuple[str, str] | None:
    """passport_no + DOB from the PASSPORT only, VERIFIED and not INVALID; else None (-> NO_WRITE)."""
    p = extractions.get("passport")
    invalid = {i.field for i in issues if i.kind == IssueKind.INVALID}
    keys = ("passport_number", "date_of_birth")
    if not p or any(k in invalid or k not in p.fields or p.fields[k].status != FieldStatus.VERIFIED for k in keys):
        return None
    return p.fields["passport_number"].value, p.fields["date_of_birth"].value


def run(packet: Path, deps: Deps, dry_run: bool = False, case: str | None = None, cfg: dict | None = None) -> RunResult:
    cfg = cfg or load_config()
    fields_cfg, formats = cfg["fields"]["fields"], cfg["fields"]["date_formats"]
    res = RunResult(case=case or Path(packet).name)

    # 1-2 ingest, classify, injection scan
    docs = ing.ingest(Path(packet))
    by_type: dict[str, dict[str, Any]] = {}
    for d in docs:
        t, flags = ing.classify(d, cfg["doc_types"])
        if t in by_type:
            t, flags = ing.UNCLASSIFIED, flags + ["duplicate_type"]
        res.docs.append({"doc_id": d["doc_id"], "doc_type": t, "flags": flags})
        if t != ing.UNCLASSIFIED:
            by_type[t] = d
    if ing.injection_markers(docs):
        res.flags.append("injection_detected")

    # 3-4 extract + verify (no LLM call for a doc without a text layer)
    for t, d in by_type.items():
        names = [n for n, c in fields_cfg.items() if t in c["source"]]
        if d["no_text_layer"]:
            res.issues += _unverifiable(names, t, "no text layer (no OCR); not sent to the LLM")
            continue
        ext, err = ex.extract(d, t, names, deps.llm)
        if ext is None:
            res.issues += _unverifiable(names, t, err)
            continue
        ext, issues = ver.verify(ext, d, fields_cfg, formats, cfg["doc_types"][t].get("date_format"))
        res.extractions[t], res.issues = ext, res.issues + issues

    # 5 validate; anything with no value and no other issue is MISSING
    res.issues += validators.validate(res.extractions, by_type, deps.today(), cfg["rules"], fields_cfg)
    values = merge_values(res.extractions, fields_cfg)
    flagged = {i.field for i in res.issues}
    res.issues += [Issue(kind=IssueKind.MISSING, field=n, message="not found in any document")
                   for n in fields_cfg if n not in values and n not in flagged]

    # 6 checklist: a failing tool means UNKNOWN, never "complete"
    docs_present = sorted(by_type)
    try:
        cl = deps.gateway.call("checklist.check", {"visa_type": VISA_TYPE, "docs_present": docs_present})
        res.checklist = {**cl, "docs_present": docs_present}
    except ToolError:  # GuardRejected is a bug, not an outage: let it propagate
        res.checklist = "UNKNOWN"

    # 7 match + decide
    ident = identity(res.extractions, res.issues)
    matches = None
    if ident:
        try:
            matches = deps.gateway.call("crm.find", {"passport_no": ident[0], "dob": ident[1]})
            res.candidates = [m["id"] for m in matches]
        except ToolError as e:  # CRM down is not "no match": say so
            res.error = f"crm.find failed: {e}"
            res.plan = WritePlan(record_id=None, reason="crm_unavailable", notes=[f"CRM lookup failed; nothing written ({e})"])
    if res.plan is None:
        res.plan = pol.decide(matches, values, res.issues, res.checklist, "injection_detected" in res.flags, cfg["policy"])

    # 8 write + read-back
    plan = res.plan
    if plan.record_id is None:
        res.write_outcome = "NO_WRITE"
    elif dry_run:
        res.write_outcome = "DRY_RUN"
    else:
        res.write_outcome = write(deps.gateway, plan, matches[0]["version"], res)
    res.audit = list(deps.gateway.audit)
    return res


def write(gw: ToolGateway, plan, version: int, res: RunResult) -> str:
    args = {"id": plan.record_id, "patch": plan.field_patch, "expected_version": version,
            "status": plan.status, "notes": plan.notes}
    outcome = "WRITTEN"
    try:
        gw.call("crm.update", args)
    except (ToolError, GuardRejected) as e:
        res.error, outcome = f"crm.update failed: {e}", "WRITE_FAILED"
    problem = read_back(gw, plan, res)
    if problem:
        res.error, outcome = (res.error or "") + problem, "WRITE_FAILED"
    return outcome


def read_back(gw: ToolGateway, plan, res: RunResult) -> str | None:
    """crm.get through the gateway; sets res.record_after. Returns a problem text if the record != the full WritePlan."""
    try:
        rec = res.record_after = gw.call("crm.get", {"id": plan.record_id})
    except (ToolError, GuardRejected) as e:
        return f" read-back failed: {e}"
    bad = [k for k, v in plan.field_patch.items() if rec["fields"].get(k) != v] + (["status"] if rec["status"] != plan.status else [])
    return f"read-back does not match the plan: {sorted(bad)}" if bad else None
