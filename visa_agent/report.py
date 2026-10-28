"""Step 9: render JSON and Markdown from RunResult with templates (no LLM prose).
Wording is deliberately flat: it states outcomes and never claims more than the state shows."""
import json
from pathlib import Path

from .schemas import RunResult

_OUTCOME = {
    "WRITTEN": "CRM record {id} written (version {v}).",
    "WRITE_FAILED": "CRM write FAILED for {id}; record left at version {v}. Error: {err}",
    "NO_WRITE": "No CRM write.",
    "DRY_RUN": "Dry run: nothing written to {id}.",
}


def _calls(r: RunResult) -> list[dict]:
    """Tool-call log without wall-clock fields (ts, run_id), so reports are reproducible."""
    return [{k: v for k, v in a.items() if k not in ("ts", "run_id")} for a in r.audit]


def to_json(result: RunResult) -> str:
    d = json.loads(result.model_dump_json(exclude={"audit", "matched_version"}))
    d["tool_calls"] = _calls(result)
    return json.dumps(d, indent=2)


def save(result: RunResult, base: Path) -> Path:
    """Write <base>/<case>/report.md and report.json; returns the directory."""
    d = Path(base) / result.case
    d.mkdir(parents=True, exist_ok=True)
    (d / "report.md").write_text(to_markdown(result))
    (d / "report.json").write_text(to_json(result) + "\n")
    return d


def to_markdown(r: RunResult) -> str:
    out = [f"# Visa packet report: {r.case}", ""]
    out += ["## Documents", "| file | type | flags |", "|---|---|---|"]
    out += [f"| {d['doc_id']} | {d['doc_type']} | {', '.join(d['flags']) or '-'} |" for d in r.docs]
    out += ["", "## Extracted fields", "| doc | field | value | evidence state | quote (page) |", "|---|---|---|---|---|"]
    for doc, ext in r.extractions.items():
        for name, f in ext.fields.items():
            quote = f'"{f.evidence_quote}" (p{f.page})' if f.evidence_quote else "-"
            out.append(f"| {doc} | {name} | {f.value if f.value is not None else '(null)'} | {f.status.value} | {quote} |")
    out += ["", "## Issues"]
    out += [f"- **{i.kind.value}** {i.field or ''}: {i.message}" + (f" (sources: {i.sources})" if i.sources else "")
            for i in r.issues] or ["- none"]
    if r.flags:
        out += ["", "## Flags"] + [f"- {f}" for f in r.flags]
    out += ["", "## Checklist"]
    if r.checklist == "UNKNOWN" or r.checklist is None:
        out.append("- UNKNOWN: checklist tool unavailable; document status not established")
    else:
        out.append(f"- required: {', '.join(r.checklist['required'])}")
        out.append(f"- missing: {', '.join(r.checklist['missing']) or 'none'}")
    out += ["", "## CRM"]
    if r.candidates or r.plan and r.plan.record_id is None:
        out.append(f"- candidates from crm.find: {', '.join(r.candidates) or 'none'}")
    if r.plan:
        out.append(f"- policy rule: {r.plan.reason}; status: {r.plan.status or '-'}")
        out.append(f"- field patch: {r.plan.field_patch if r.plan.field_patch else '{}'}")
        out += [f"- note: {n}" for n in r.plan.notes]
    rec = r.record_after or {}
    rid = r.plan.record_id if r.plan else None
    out.append("- outcome: " + _OUTCOME.get(r.write_outcome or "NO_WRITE", "").format(id=rid, v=rec.get("version", "?"), err=r.error))
    final = rec.get("status") if r.write_outcome in ("WRITTEN", "WRITE_FAILED") else None
    out += ["", "## Final", f"- write outcome: {r.write_outcome}",
            f"- final CRM status: {final or '-'}; version: {rec.get('version', '-')}"]
    out += ["", "## Tool calls", "| # | tool | attempt | outcome | args |", "|---|---|---|---|---|"]
    out += [f"| {n} | {a['tool']} | {a['attempt']} | {a['outcome']}{' (' + a['error'] + ')' if a.get('error') else ''} | "
            f"`{json.dumps(a['args'], sort_keys=True).replace('|', '/')}` |" for n, a in enumerate(_calls(r), 1)] or ["| - | none | | | |"]
    return "\n".join(out) + "\n"
