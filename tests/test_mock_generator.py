import filecmp
import json
import re
import unicodedata
from pathlib import Path

import fitz
import pytest

from mock_data.generator import build_cases, generate, mrz_check
from visa_agent.schemas import Extraction

COMMITTED = Path(__file__).resolve().parent.parent / "mock_data"


def _norm(s):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", s).casefold()).strip()


def _text(pdf):
    return "\n".join(p.get_text() for p in fitz.open(pdf))


def _mrz_ok(l1, l2):
    assert len(l1) == len(l2) == 44
    n, dob, exp = l2[0:9], l2[13:19], l2[21:27]
    return (mrz_check(n) == l2[9] and mrz_check(dob) == l2[19] and mrz_check(exp) == l2[27]
            and mrz_check(l2[0:10] + l2[13:20] + l2[21:43]) == l2[43])


def _mrz(pdf):
    lines = [l.strip() for l in _text(pdf).splitlines() if re.fullmatch(r"[A-Z0-9<]{44}", l.strip())]
    assert len(lines) == 2
    return lines


def test_mrz_check_digit_known_icao_example():
    assert mrz_check("L898902C3") == "6" and mrz_check("740812") == "2" and mrz_check("120415") == "9"


def test_deterministic_and_matches_committed(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    generate(a); generate(b)
    for root in (b, COMMITTED):
        cmp = filecmp.dircmp(a, root)
        assert not cmp.diff_files
        for sub in (x for x in (a / "cases").iterdir()):
            c = filecmp.dircmp(sub, root / "cases" / sub.name)
            assert not c.diff_files and not c.left_only and not c.right_only, sub.name
    assert filecmp.cmp(a / "crm_seed.json", COMMITTED / "crm_seed.json", shallow=False)


def test_all_15_scenarios_covered():
    assert {c["scenario"] for c in build_cases().values()} == set(range(1, 16))


def test_mrz_valid_except_case5():
    for cid in build_cases():
        pdf = COMMITTED / "cases" / cid / "passport.pdf"
        if pdf.exists():
            assert _mrz_ok(*_mrz(pdf)) is (cid != "case05_bad_mrz"), cid
            assert "SPECIMEN" in _text(pdf) and "UTO" in _text(pdf)


def test_no_text_layer_page_case6():
    assert _text(COMMITTED / "cases/case06_no_text_layer/bank_statement.pdf").strip() == ""


def test_injection_text_in_case14():
    assert "APPROVED" in _text(COMMITTED / "cases/case14_injection/bank_statement.pdf")


def test_fake_llm_quotes_verbatim_except_hallucination():
    for cid in build_cases():
        d = COMMITTED / "cases" / cid
        exp = json.loads((d / "expected.json").read_text())
        packet = COMMITTED / "cases" / exp["packet"]
        script = json.loads((d / "fake_llm.json").read_text())["script"]
        for doc, items in script.items():
            for item in items:
                if isinstance(item, str):
                    continue
                Extraction.model_validate(item)
                page = _norm(_text(packet / f"{doc}.pdf"))
                for f, v in item["fields"].items():
                    ok = _norm(v["evidence_quote"]) in page
                    assert ok is (not (cid == "case07_hallucination" and f == "email")), (cid, doc, f)


def test_goldens_have_tool_log_and_no_approved():
    for cid in build_cases():
        exp = json.loads((COMMITTED / "cases" / cid / "expected.json").read_text())
        assert exp["tool_calls"]["must"] and exp["crm"]["status"] not in ("APPROVED", "REJECTED")
