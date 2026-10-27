"""Typed data passed between pipeline steps. Every step returns one of these; no hidden state."""
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field as PField


class FieldStatus(str, Enum):
    PROPOSED = "PROPOSED"          # straight from the LLM, not yet checked
    VERIFIED = "VERIFIED"          # passed both evidence checks (docs/ARCHITECTURE.md)
    UNVERIFIABLE = "UNVERIFIABLE"  # value dropped: evidence did not hold
    MISSING = "MISSING"            # null value and no quote


class Field(BaseModel):
    """One extracted field. Only structure is checked here; a value without a quote/page parses fine
    and verify.py marks that single field UNVERIFIABLE, so one bad field never sinks the whole doc."""
    model_config = ConfigDict(extra="forbid")
    value: str | None = None
    evidence_quote: str | None = None
    page: int | None = PField(default=None, ge=1)
    status: FieldStatus = FieldStatus.PROPOSED

    def has_evidence(self) -> bool:
        return bool(self.evidence_quote) and self.page is not None


class Extraction(BaseModel):
    """LLM output for one document: field name -> Field."""
    model_config = ConfigDict(extra="forbid")
    doc_type: str
    fields: dict[str, Field]


class IssueKind(str, Enum):
    MISSING = "MISSING"
    CONFLICT = "CONFLICT"
    UNVERIFIABLE = "UNVERIFIABLE"
    INVALID = "INVALID"


class Issue(BaseModel):
    kind: IssueKind
    field: str | None = None
    message: str
    sources: list[dict[str, Any]] = []  # e.g. [{"doc": "passport", "value": "...", "page": 1}]


CrmStatus = Literal["DATA_UPDATED", "INCOMPLETE", "NEEDS_REVIEW"]  # never APPROVED/REJECTED


class WritePlan(BaseModel):
    """Output of policy.decide(). record_id None means NO_WRITE."""
    model_config = ConfigDict(extra="forbid")
    record_id: str | None
    field_patch: dict[str, str] = {}
    status: CrmStatus | None = None
    notes: list[str] = []
    reason: str  # which policy row matched


class RunResult(BaseModel):
    case: str
    docs: list[dict[str, Any]] = []  # [{doc_id, doc_type, flags}] incl. UNCLASSIFIED and no_text_layer docs
    extractions: dict[str, Extraction] = {}
    issues: list[Issue] = []
    flags: list[str] = []  # e.g. "injection_detected"
    checklist: dict[str, Any] | Literal["UNKNOWN"] | None = None
    plan: WritePlan | None = None
    write_outcome: Literal["WRITTEN", "NO_WRITE", "WRITE_FAILED", "DRY_RUN"] | None = None
    candidates: list[str] = []                 # CRM record ids returned by crm.find
    record_after: dict[str, Any] | None = None  # read-back after the write attempt
    error: str | None = None                    # tool error that stopped the write, if any
    audit: list[dict[str, Any]] = []
