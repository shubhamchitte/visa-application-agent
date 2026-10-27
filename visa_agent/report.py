"""Step 9: render JSON and Markdown from RunResult with templates (no LLM prose).
Wording is deliberately flat: it states outcomes and never claims more than the state shows."""
from .schemas import RunResult

_OUTCOME = {
    "WRITTEN": "CRM record {id} written (version {v}).",
    "WRITE_FAILED": "CRM write FAILED for {id}; record left at version {v}. Error: {err}",
    "NO_WRITE": "No CRM write.",
    "DRY_RUN": "Dry run: nothing written to {id}.",
}


def to_json(result: RunResult) -> str:
    return result.model_dump_json(indent=2, exclude={"audit"})


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
    return "\n".join(out) + "\n"
