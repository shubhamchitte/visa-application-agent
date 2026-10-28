"""Step 4: evidence matcher (docs/ARCHITECTURE.md): quote-in-page AND value-in-quote, else UNVERIFIABLE.
No fuzzy matching: a one-character slip fails on purpose (precision over recall)."""
import re
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from .schemas import Extraction, Field, FieldStatus, Issue, IssueKind
from .validators import parse_date

_UNIFY = str.maketrans({**dict.fromkeys("‐‑‒–—―−", "-"),
                        **dict.fromkeys("‘’‚‛′", "'"), **dict.fromkeys("“”„‟″", '"')})
MIN_QUOTE = 3
DATE_TOKEN = re.compile(r"\d{4}-\d{2}-\d{2}|\d{1,2}[/.]\d{1,2}[/.]\d{4}|\d{1,2} [a-z]{3,9} \d{4}")
MONEY_TOKEN = re.compile(r"\d[\d,]*(?:\.\d+)?")


def normalize(text: str) -> str:
    """NFKC, casefold, collapse whitespace, unify dashes/quotes, strip .,;: at edges."""
    t = unicodedata.normalize("NFKC", text).translate(_UNIFY).casefold()
    return re.sub(r"\s+", " ", t).strip().strip(".,;:").strip()


def find_quote(quote: str, doc: dict[str, Any], cited: int | None) -> int | None:
    """Page number where the normalized quote occurs: the cited page first, then any other page of the doc."""
    q = normalize(quote)
    if len(q) < MIN_QUOTE:
        return None
    pages = sorted(doc["pages"], key=lambda p: p["page"] != cited)
    return next((p["page"] for p in pages if q in normalize(p["text"])), None)


def _money(s: str) -> Decimal | None:
    try:
        return Decimal(s.replace(",", ""))
    except InvalidOperation:
        return None


def value_in_quote(value: str, quote: str, ftype: str, formats: list[str], declared: str | None = None) -> str | None:
    """None if `value` is derivable from `quote` by the per-type parser, else the reason it is not."""
    q = normalize(quote)
    if ftype == "str":
        return None if normalize(value) in q else "value not in quote"
    if ftype == "name":  # whole tokens only: "ANN" must not verify against "ANNE"
        v = normalize(value)
        return None if v and re.search(rf"(?<!\w){re.escape(v)}(?!\w)", q) else "name not in quote as whole words"
    if ftype == "passport_no":
        return None if value.replace(" ", "").upper() in quote.replace(" ", "").upper() else "value not in quote"
    if ftype == "money":
        v = _money(re.sub(r"[^\d.,\-]", "", value))
        return None if v is not None and v in {_money(t) for t in MONEY_TOKEN.findall(q)} else "amount not in quote"
    if ftype == "date":
        try:
            v = date.fromisoformat(value)
        except ValueError:
            return "value is not an ISO date"
        ambiguous = False
        for token in DATE_TOKEN.findall(q):
            parses = parse_date(token, formats, declared)
            if parses == {v}:
                return None
            ambiguous |= v in parses
        return "ambiguous date" if ambiguous else "date not in quote"
    raise ValueError(f"unknown field type {ftype}")


def verify(extraction: Extraction, doc: dict[str, Any], fields_cfg: dict[str, Any], formats: list[str],
           declared: str | None = None) -> tuple[Extraction, list[Issue]]:
    """Mark each field VERIFIED/UNVERIFIABLE/MISSING; drop unverified values. Records the page actually found."""
    out, issues = {}, []
    for name, f in extraction.fields.items():
        if f.value is None:
            out[name] = Field(status=FieldStatus.MISSING)
            continue
        reason, page = None, None
        if not f.has_evidence():
            reason = "no evidence quote"
        elif (page := find_quote(f.evidence_quote, doc, f.page)) is None:
            reason = "quote not found in document"
        else:
            reason = value_in_quote(f.value, f.evidence_quote, fields_cfg[name]["type"], formats, declared)
        if reason:
            out[name] = Field(evidence_quote=f.evidence_quote, page=f.page, status=FieldStatus.UNVERIFIABLE)
            issues.append(Issue(kind=IssueKind.UNVERIFIABLE, field=name, message=f"{doc['doc_id']}: {reason}",
                                sources=[{"doc": extraction.doc_type, "value": f.value, "page": f.page}]))
        else:
            out[name] = Field(value=f.value, evidence_quote=f.evidence_quote, page=page, status=FieldStatus.VERIFIED)
    return Extraction(doc_type=extraction.doc_type, fields=out), issues


def derive(ext: Extraction, fields_cfg: dict[str, Any]) -> tuple[Extraction, list[Issue]]:
    """Derived fields (fields.yaml `derived`, e.g. full_name = given_names + surname): never asked of the LLM.
    VERIFIED only if every part is VERIFIED; MISSING if no part has a value; else UNVERIFIABLE."""
    fields, issues = dict(ext.fields), []
    for name, cfg in fields_cfg.items():
        if not cfg.get("derived") or ext.doc_type not in cfg["source"]:
            continue
        parts = [fields.get(p) or Field(status=FieldStatus.MISSING) for p in cfg["derived"]]
        if all(p.status == FieldStatus.VERIFIED for p in parts):
            quotes = list(dict.fromkeys(p.evidence_quote for p in parts))
            fields[name] = Field(value=" ".join(p.value.strip() for p in parts), evidence_quote=" | ".join(quotes),
                                 page=parts[0].page, status=FieldStatus.VERIFIED)
        elif all(p.status == FieldStatus.MISSING for p in parts):
            fields[name] = Field(status=FieldStatus.MISSING)
        else:
            fields[name] = Field(status=FieldStatus.UNVERIFIABLE)
            issues.append(Issue(kind=IssueKind.UNVERIFIABLE, field=name,
                                message=f"{ext.doc_type}: derived from {' + '.join(cfg['derived'])}, not all VERIFIED"))
    return Extraction(doc_type=ext.doc_type, fields=fields), issues
