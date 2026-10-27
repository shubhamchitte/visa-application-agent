"""Step 7: pure function from facts to WritePlan, driven by policy.yaml (docs/ARCHITECTURE.md).
Facts are computed here in code; the rule order and actions come from policy.yaml (first match wins)."""
from typing import Any

from .schemas import Issue, IssueKind, WritePlan


def facts(matches: list[dict[str, Any]] | None, issues: list[Issue], checklist: dict[str, Any] | str,
          injection: bool, identity_fields: list[str]) -> dict[str, bool]:
    kinds = {i.kind for i in issues}
    unknown = checklist == "UNKNOWN"
    return {
        "crm_match_count_not_1": matches is None or len(matches) != 1,
        "injection_detected": injection,
        "identity_conflict": any(i.kind == IssueKind.CONFLICT and i.field in identity_fields for i in issues),
        "checklist_missing_or_invalid_or_unverifiable": (not unknown and bool(checklist.get("missing")))
                                                       or bool(kinds & {IssueKind.INVALID, IssueKind.UNVERIFIABLE}),
        "checklist_unknown": unknown,
        "otherwise": True,
    }


def verified_patch(values: dict[str, str], record: dict[str, Any], issues: list[Issue],
                   whitelist: list[str]) -> tuple[dict[str, str], list[str]]:
    """Whitelisted VERIFIED values that differ from the CRM. Fields with any issue are left out.
    A differing non-empty CRM value is never overwritten: it becomes a note instead."""
    blocked = {i.field for i in issues}
    patch, notes = {}, []
    for k, v in values.items():
        if k not in whitelist or k in blocked:
            continue
        current = record["fields"].get(k)
        if current == v:
            continue
        if current not in (None, ""):
            notes.append(f"CONFLICT {k}: CRM has {current!r}, documents say {v!r}; not overwritten")
        else:
            patch[k] = v
    return patch, notes


def decide(matches: list[dict[str, Any]] | None, values: dict[str, str], issues: list[Issue],
           checklist: dict[str, Any] | str, injection: bool, policy: dict[str, Any]) -> WritePlan:
    """`matches` None means identity not verified (no lookup was made). First matching rule wins.
    Never returns APPROVED/REJECTED (WritePlan's type forbids it); never creates a record."""
    f = facts(matches, issues, checklist, injection, policy["identity_fields"])
    rule = next(r for r in policy["rules"] if f[r["when"]])
    if rule["action"] == "NO_WRITE":
        if matches is None:
            return WritePlan(record_id=None, reason="identity_unverified",
                             notes=["passport number + date of birth not verified from the passport; no CRM lookup"])
        ids = [m["id"] for m in matches]
        return WritePlan(record_id=None, reason=rule["when"],
                         notes=[f"CRM candidates: {', '.join(ids)}" if ids else "no CRM record matches; none created"])
    act, record = rule["action"], matches[0]
    notes = [act["note"]] if act.get("note") else []
    patch = {}
    if act["patch"] == "verified_only":
        patch, conflict_notes = verified_patch(values, record, issues, policy["field_whitelist"])
        notes += conflict_notes
    if isinstance(checklist, dict) and checklist.get("missing"):
        notes.append("missing documents: " + ", ".join(checklist["missing"]))
    notes += [f"{i.kind.value} {i.field}: {i.message}" for i in issues]
    return WritePlan(record_id=record["id"], field_patch=patch, status=act["status"], notes=notes, reason=rule["when"])
