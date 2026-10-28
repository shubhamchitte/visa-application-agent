"""Step 5: deterministic checks: MRZ check digits, MRZ==visual, dates, expiry, cross-doc equality."""
import calendar
import re
import unicodedata
from datetime import date, datetime
from typing import Any

from .schemas import Extraction, FieldStatus, Issue, IssueKind

MRZ_LINE = re.compile(r"^[A-Z0-9<]{44}$")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")  # local@domain.tld


def parse_date(token: str, formats: list[str], declared: str | None = None) -> set[date]:
    """All dates `token` can mean under `formats`. More than one = ambiguous (e.g. 03/04/1990),
    unless the doc's declared format parses it, which then wins."""
    def p(fmt: str) -> date | None:
        try:
            return datetime.strptime(token, fmt).date()
        except ValueError:
            return None
    if declared and (d := p(declared)):
        return {d}
    return {d for d in map(p, formats) if d}


def add_months(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    y, m = d.year + y, m + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def mrz_check_digit(s: str) -> int:
    """ICAO 9303: digits as-is, A-Z = 10-35, '<' = 0; weights 7,3,1 repeating; sum mod 10."""
    val = lambda c: int(c) if c.isdigit() else (ord(c) - 55 if c.isalpha() else 0)
    return sum(val(c) * (7, 3, 1)[i % 3] for i, c in enumerate(s)) % 10


def find_mrz(doc: dict[str, Any]) -> tuple[str, str] | None:
    lines = [ln.strip() for p in doc["pages"] for ln in p["text"].splitlines() if MRZ_LINE.match(ln.strip())]
    return (lines[0], lines[1]) if len(lines) >= 2 else None


def check_mrz(passport: Extraction, doc: dict[str, Any]) -> list[Issue]:
    """TD3 line 2: number[0:9]+cd[9], dob[13:19]+cd[19], expiry[21:27]+cd[27]. Each must pass its check digit
    and equal the visual-zone value; the composite digit [43] covers [0:10]+[13:20]+[21:43]."""
    mrz = find_mrz(doc)
    if not mrz:
        return [Issue(kind=IssueKind.INVALID, field="passport_number", message="passport has no machine-readable zone")]
    line1, line2 = mrz
    issues = []
    if mrz_check_digit(line2[0:10] + line2[13:20] + line2[21:43]) != int(line2[43] if line2[43].isdigit() else -1):
        issues.append(Issue(kind=IssueKind.INVALID, field="passport_number", message="MRZ composite check digit fails"))
    verified = lambda f: passport.fields[f].value if f in passport.fields and passport.fields[f].status == FieldStatus.VERIFIED else None
    for field, start, end in (("passport_number", 0, 9), ("date_of_birth", 13, 19), ("passport_expiry", 21, 27)):
        raw, cd = line2[start:end], line2[end]
        if not cd.isdigit() or mrz_check_digit(raw) != int(cd):
            issues.append(Issue(kind=IssueKind.INVALID, field=field, message=f"MRZ check digit fails for {raw!r}"))
            continue
        visual = verified(field)
        if visual is None:
            continue
        mrz_val = raw.replace("<", "") if field == "passport_number" else raw
        vis_val = visual.replace(" ", "").upper() if field == "passport_number" else date.fromisoformat(visual).strftime("%y%m%d")
        if mrz_val != vis_val:
            issues.append(Issue(kind=IssueKind.INVALID, field=field, message=f"MRZ {raw!r} != visual {visual!r}",
                                sources=[{"doc": "passport", "value": visual, "zone": "visual"}, {"doc": "passport", "value": raw, "zone": "MRZ"}]))
    name = verified("full_name")
    if name:
        mrz_names = [t for t in re.split(r"<+", line1[5:]) if t]
        if not all(t in name.upper().split() for t in mrz_names):
            issues.append(Issue(kind=IssueKind.INVALID, field="full_name", message=f"MRZ name {mrz_names} != visual {name!r}"))
    return issues


def _norm(value: str, ftype: str, ocr: bool = False) -> str:
    if ftype == "passport_no":
        return value.replace(" ", "").upper()
    return ("" if ocr and ftype == "name" else " ").join(unicodedata.normalize("NFKC", value).split()).casefold()


def cross_doc(extractions: dict[str, Extraction], fields_cfg: dict[str, Any], ocr_docs: set[str] = frozenset()) -> list[Issue]:
    """Any field verified in 2+ docs must agree (names normalized). Never auto-resolved: CONFLICT with both sources.
    Name parts (`part_of`) are compared once, through the derived full_name built from the normalised parts.
    A `same_as` field (bank account holder, letter employee name) is compared with that field's verified values.
    If any source is an OCR doc, names compare without whitespace (OCR drops spaces: "DEBORAHDAVIS"); letters must match."""
    def verified(name: str, docs: list[str]) -> list[tuple[str, Any]]:
        return [(d, extractions[d].fields[name]) for d in docs
                if d in extractions and name in extractions[d].fields and extractions[d].fields[name].status == FieldStatus.VERIFIED]
    issues = []
    for name, cfg in fields_cfg.items():
        if cfg.get("part_of"):
            continue
        srcs = verified(name, cfg["source"])
        if srcs and (ref := cfg.get("same_as")):
            srcs = verified(ref, fields_cfg[ref]["source"]) + srcs
        ocr = any(d in ocr_docs for d, _ in srcs)
        if len({_norm(f.value, cfg["type"], ocr) for _, f in srcs}) > 1:
            issues.append(Issue(kind=IssueKind.CONFLICT, field=name, message=f"documents disagree on {name}",
                                sources=[{"doc": d, "value": f.value, "page": f.page} for d, f in srcs]))
    return issues


def check_dates(values: dict[str, str], today: date, rules: dict[str, Any]) -> list[Issue]:
    """Expiry rules against the injected clock: not expired, and valid N months after travel."""
    issues = []
    expiry, travel = values.get("passport_expiry"), values.get("intended_travel_date")
    if expiry and date.fromisoformat(expiry) <= today:
        issues.append(Issue(kind=IssueKind.INVALID, field="passport_expiry", message=f"passport expired on {expiry}"))
    elif expiry and travel:
        months = rules.get("passport_min_validity_months_after_travel", 6)
        if date.fromisoformat(expiry) < add_months(date.fromisoformat(travel), months):
            issues.append(Issue(kind=IssueKind.INVALID, field="passport_expiry",
                                message=f"passport expires {expiry}, less than {months} months after travel {travel}"))
    if travel and date.fromisoformat(travel) < today:
        issues.append(Issue(kind=IssueKind.INVALID, field="intended_travel_date", message=f"travel date {travel} is in the past"))
    return issues


def check_letter(values: dict[str, str], today: date, rules: dict[str, Any], letter_present: bool = True) -> list[Issue]:
    """Employment letter (optional doc): not dated in the future, not older than N days, and its leave period covers
    the travel date. Runs only when the letter is present; then an unproven leave date is INVALID, not skipped."""
    issues = []
    if not letter_present:
        return issues
    letter, start, end, travel = (values.get(k) for k in ("letter_date", "leave_start", "leave_end", "intended_travel_date"))
    max_age = rules.get("employment_letter_max_age_days")
    if letter and date.fromisoformat(letter) > today:
        issues.append(Issue(kind=IssueKind.INVALID, field="letter_date", message=f"employment letter dated {letter} is in the future"))
    elif letter and max_age is not None and (today - date.fromisoformat(letter)).days > max_age:
        issues.append(Issue(kind=IssueKind.INVALID, field="letter_date",
                            message=f"employment letter dated {letter} is older than {max_age} days"))
    if rules.get("employment_letter_leave_must_cover_travel"):
        for field, value, bad in (("leave_start", start, travel and start and start > travel),
                                  ("leave_end", end, travel and end and end < travel)):
            if not value:
                issues.append(Issue(kind=IssueKind.INVALID, field=field,
                                    message=f"{field} not verified from the letter; leave cannot be shown to cover travel"))
            elif bad:
                issues.append(Issue(kind=IssueKind.INVALID, field=field,
                                    message=f"approved leave {start or '?'} to {end or '?'} does not cover travel {travel}"))
    return issues


def validate(extractions: dict[str, Extraction], docs: dict[str, dict[str, Any]], today: date,
             rules: dict[str, Any], fields_cfg: dict[str, Any]) -> list[Issue]:
    """Return INVALID/CONFLICT issues. `today` comes from the injected clock."""
    issues = cross_doc(extractions, fields_cfg, {t for t, d in docs.items() if d.get("ocr_used")})
    if "passport" in extractions:
        issues += check_mrz(extractions["passport"], docs["passport"])
    values = {}
    for name, cfg in fields_cfg.items():
        for d in cfg["source"]:
            f = extractions.get(d) and extractions[d].fields.get(name)
            if f and f.status == FieldStatus.VERIFIED:
                values.setdefault(name, f.value)
    if values.get("email") and not EMAIL.match(values["email"]):
        issues.append(Issue(kind=IssueKind.INVALID, field="email", message=f"email {values['email']!r} is not local@domain.tld"))
    return issues + check_dates(values, today, rules) + check_letter(values, today, rules, "employment_letter" in docs)
