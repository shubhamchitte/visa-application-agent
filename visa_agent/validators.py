"""Step 5: deterministic checks: MRZ check digits, MRZ==visual, dates, expiry, cross-doc equality."""
import calendar
import re
from datetime import date, datetime
from typing import Any

from .schemas import Extraction, FieldStatus, Issue, IssueKind

MRZ_LINE = re.compile(r"^[A-Z0-9<]{44}$")


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


def _norm(value: str, ftype: str) -> str:
    if ftype == "passport_no":
        return value.replace(" ", "").upper()
    return " ".join(value.split()).casefold()


def cross_doc(extractions: dict[str, Extraction], fields_cfg: dict[str, Any]) -> list[Issue]:
    """Any field verified in 2+ docs must agree (names normalized). Never auto-resolved: CONFLICT with both sources."""
    issues = []
    for name, cfg in fields_cfg.items():
        srcs = [(d, extractions[d].fields[name]) for d in cfg["source"]
                if d in extractions and name in extractions[d].fields and extractions[d].fields[name].status == FieldStatus.VERIFIED]
        if len({_norm(f.value, cfg["type"]) for _, f in srcs}) > 1:
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


def validate(extractions: dict[str, Extraction], docs: dict[str, dict[str, Any]], today: date,
             rules: dict[str, Any], fields_cfg: dict[str, Any]) -> list[Issue]:
    """Return INVALID/CONFLICT issues. `today` comes from the injected clock."""
    issues = cross_doc(extractions, fields_cfg)
    if "passport" in extractions:
        issues += check_mrz(extractions["passport"], docs["passport"])
    values = {}
    for name, cfg in fields_cfg.items():
        for d in cfg["source"]:
            f = extractions.get(d) and extractions[d].fields.get(name)
            if f and f.status == FieldStatus.VERIFIED:
                values.setdefault(name, f.value)
    return issues + check_dates(values, today, rules)
