"""Step 4: evidence matcher (docs/ARCHITECTURE.md): quote-in-page AND value-in-quote, else UNVERIFIABLE.
No fuzzy matching: a one-character slip fails on purpose (precision over recall).
OCR pages only: whitespace is not evidence (RapidOCR drops spaces: "09JUN 1970", "DEBORAHDAVIS"), so quote and value
are compared with whitespace removed; every character must still match, and names keep their word-boundary rule."""
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
# OCR pages, whitespace removed (OCR drops spaces: "12NOV2030"); the token is re-spaced before parsing, never guessed: any date layout, in order ("12nov2030", "09.06.1970"); re-spaced before parsing.
OCR_DATE_ANY = re.compile(r"\d{4}-\d{2}-\d{2}|(?<!\d)\d{1,2}[/.]\d{1,2}[/.]\d{4}(?!\d)|(?<!\d)\d{1,2}[a-z]{3,9}\d{4}(?!\d)")


def normalize(text: str) -> str:
    """NFKC, casefold, collapse whitespace, unify dashes/quotes, strip .,;: at edges."""
    t = unicodedata.normalize("NFKC", text).translate(_UNIFY).casefold()
    return re.sub(r"\s+", " ", t).strip().strip(".,;:").strip()


def squash(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _respace(token: str) -> str:
    """"12nov2030" -> "12 nov 2030": a space at each digit/letter boundary, the only spaces OCR drops in a date."""
    return re.sub(r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)", " ", token.replace(" ", ""))


def first_segment(value: str) -> str:
    """Bilingual "A / B" value -> "A". Applied only after the full value verified against the quote."""
    return value.split(" / ")[0].strip()


def find_quote(quote: str, doc: dict[str, Any], cited: int | None) -> dict[str, Any] | None:
    """Page where the normalized quote occurs (whitespace-insensitive on OCR pages): cited page first, then the rest."""
    q = normalize(quote)
    if len(q) < MIN_QUOTE:
        return None
    hit = lambda p: q in normalize(p["text"]) or (p.get("text_source") == "ocr" and squash(q) in squash(normalize(p["text"])))
    return next((p for p in sorted(doc["pages"], key=lambda p: p["page"] != cited) if hit(p)), None)


# A signed amount with an optional currency symbol or code (short list): "-$1,150.00", "$-1,150.00", "UTD 3,200.00", "1.234,50 eur".
MONEY_TOKEN = re.compile(r"(?P<sign>-)?\s?(?P<cur>[$€£¥]|\b(?:usd|eur|gbp|chf|jpy|utd)\b)?\s?(?P<sign2>-)?\s?(?P<num>\d[\d.,]*\d|\d)(?:\s?(?P<cur2>\b(?:usd|eur|gbp|chf|jpy|utd)\b))?")
US_AMOUNT, EU_AMOUNT = re.compile(r"\d{1,3}(,\d{3})*(\.\d{2})?|\d+(\.\d{2})?"), re.compile(r"\d{1,3}(\.\d{3})*,\d{2}")
# str values match whole tokens only; "." continues a token only before a word char ("eric.morton", not "Ltd.").
STR_LEFT, STR_RIGHT = r"(?<![\w@+-])(?<!\w\.)", r"(?![\w@+-]|\.\w)"


def _amount(num: str) -> Decimal | None:
    """1,234.50 or 1234.50 (US) / 1.234,50 (EU: the last separator before exactly 2 digits is the decimal).
    Anything else (e.g. "1.234", "1,23") is ambiguous and parses to None."""
    if US_AMOUNT.fullmatch(num):
        return Decimal(num.replace(",", ""))
    if EU_AMOUNT.fullmatch(num):
        return Decimal(num.replace(".", "").replace(",", "."))
    return None


def money_tokens(text: str) -> list[tuple[Decimal | None, str | None]]:
    """(signed amount, currency) per amount in `text`, in order. A "-" before the currency or the digits keeps the sign."""
    out = []
    for m in MONEY_TOKEN.finditer(text):
        v = _amount(m["num"])
        out.append((v if v is None or not (m["sign"] or m["sign2"]) else -v, m["cur"] or m["cur2"]))
    return out


def _anchored_tail(q: str, labels: list[str], ocr: bool) -> str | None:
    """Text after the first field label in the quote, or None if the quote has none of the labels."""
    t = squash(q) if ocr else q
    needles = [squash(normalize(lab)) if ocr else normalize(lab) for lab in labels]
    hits = [(i, len(n)) for n in needles if (i := t.find(n)) >= 0]
    return t[sum(min(hits)):] if hits else None


def value_in_quote(value: str, quote: str, ftype: str, formats: list[str], declared: str | None = None,
                   ocr: bool = False, cfg: dict[str, Any] | None = None) -> str | None:
    """None if `value` is derivable from `quote` by the per-type parser, else the reason it is not.
    ocr=True (quote found on an OCR page): str/name compare with whitespace removed; dates may lack inner spaces.
    cfg (the fields.yaml entry) may bind the value to its label: `labels` (the quote must contain one, and the value
    must be the first date/amount after it, or the second for `role: end`) and `currency` (allowed currencies)."""
    cfg = cfg or {}
    q = normalize(quote)
    sq = squash if ocr else (lambda t: t)
    idx = 1 if cfg.get("role") == "end" else 0
    if cfg.get("labels"):
        tail = _anchored_tail(q, cfg["labels"], ocr)
        if tail is None:
            return f"quote lacks the field label ({' / '.join(cfg['labels'])})"
        q = tail
    if ftype == "str":
        v = sq(normalize(value))
        return None if v and re.search(STR_LEFT + re.escape(v) + STR_RIGHT, sq(q)) else "value not in quote as a whole token"
    if ftype == "name":  # whole tokens only: "ANN" must not verify against "ANNE"
        v, q = sq(normalize(value)), sq(q)
        return None if v and re.search(rf"(?<!\w){re.escape(v)}(?!\w)", q) else "name not in quote as whole words"
    if ftype == "passport_no":
        v = r"\s?".join(map(re.escape, value.replace(" ", "").upper()))
        return None if v and re.search(rf"(?<![A-Z0-9]){v}(?![A-Z0-9])", quote.upper()) else "value not in quote as a whole token"
    if ftype == "money":
        m = re.fullmatch(r"(-)?\s?(\d+(?:\.\d+)?)", value.strip().replace(",", ""))
        if not m:
            return "value is not a plain signed amount"
        v = Decimal(m[2]) * (-1 if m[1] else 1)
        tokens = money_tokens(q)
        if cfg.get("labels"):
            tokens = tokens[idx:idx + 1]
        hits = [cur for amount, cur in tokens if amount == v]
        if not hits:
            return "amount not in quote" + (" as the first amount after the label" if cfg.get("labels") else "")
        allowed = {c.casefold() for c in cfg.get("currency", [])}
        if allowed and all(c is not None and c not in allowed for c in hits):
            return f"currency {hits[0]!r} is not one of {sorted(allowed)}"
        return None
    if ftype == "date":
        try:
            v = date.fromisoformat(value)
        except ValueError:
            return "value is not an ISO date"
        tokens = ([_respace(m[0]) for m in OCR_DATE_ANY.finditer(squash(q))] if ocr else DATE_TOKEN.findall(q))
        if cfg.get("labels"):  # bound: only the date in the field's position after the label counts
            tokens = tokens[idx:idx + 1]
        ambiguous = False
        for token in tokens:
            parses = parse_date(token, formats, declared)
            if parses == {v}:
                return None
            ambiguous |= v in parses
        return "ambiguous date" if ambiguous else "date not in quote" + (" in its position after the label" if cfg.get("labels") else "")
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
        elif (hit := find_quote(f.evidence_quote, doc, f.page)) is None:
            reason = "quote not found in document"
        else:
            page = hit["page"]
            reason = value_in_quote(f.value, f.evidence_quote, fields_cfg[name]["type"], formats, declared,
                                    ocr=hit.get("text_source") == "ocr", cfg=fields_cfg[name])
        if reason:
            out[name] = Field(evidence_quote=f.evidence_quote, page=f.page, status=FieldStatus.UNVERIFIABLE)
            issues.append(Issue(kind=IssueKind.UNVERIFIABLE, field=name, message=f"{doc['doc_id']}: {reason}",
                                sources=[{"doc": extraction.doc_type, "value": f.value, "page": f.page}]))
        else:
            value = first_segment(f.value) if fields_cfg[name].get("bilingual") else f.value
            out[name] = Field(value=value, evidence_quote=f.evidence_quote, page=page, status=FieldStatus.VERIFIED)
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
