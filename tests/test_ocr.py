"""OCR path: tesseract subprocess is mocked (VISA_OCR=tesseract), so these run without tesseract installed.
RapidOCR tests run only when the `ocr` extra is installed."""
import subprocess
from pathlib import Path

import fitz
import pytest

from visa_agent import ingest as ing
from visa_agent.orchestrator import run
from visa_agent.schemas import FieldStatus, IssueKind
from visa_agent.validators import check_mrz

from .test_core import L1, L2, pp_ext, ver
from .test_scenarios import ROOT, setup_case

OCR_TEXT = "PASSPORT\nFull name: ERIC MORTON\n" + L1 + "\n" + L2[:22] + " " + L2[22:]


def fake_tesseract(monkeypatch, text, calls=None):
    monkeypatch.setenv("VISA_OCR", "tesseract")
    monkeypatch.setattr(ing.shutil, "which", lambda _: "/usr/bin/tesseract")

    def _run(args, **kw):
        if calls is not None:
            calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout=text, stderr="")
    monkeypatch.setattr(ing.subprocess, "run", _run)


def blank_pdf(path: Path, text: str = "") -> Path:
    d = fitz.open()
    d.new_page().insert_text((72, 72), text)
    d.save(path)
    return path


def test_ocr_page_fields_verify_and_text_source_recorded(monkeypatch, tmp_path):
    calls = []
    fake_tesseract(monkeypatch, OCR_TEXT, calls)
    blank_pdf(tmp_path / "passport.pdf")
    blank_pdf(tmp_path / "letter.pdf", "This page has a real text layer of more than thirty chars")
    docs = {d["doc_id"]: d for d in ing.ingest(tmp_path)}
    pp = docs["passport"]
    assert pp["pages"][0]["text_source"] == "ocr" and pp["ocr_used"] and not pp["no_text_layer"]
    assert docs["letter"]["pages"][0]["text_source"] == "pdf_text" and not docs["letter"]["ocr_used"]
    assert len(calls) == 1 and calls[0][0] == "/usr/bin/tesseract"
    assert L2 in pp["pages"][0]["text"].splitlines()  # whitespace inside the MRZ line normalised
    f, issues = ver("full_name", "ERIC MORTON", "Full name: ERIC MORTON", 1, pp, doc_type="passport")
    assert f.status == FieldStatus.VERIFIED and issues == []
    assert check_mrz(pp_ext(), pp) == []
    assert "ocr_used" in ing.classify(pp, {"passport": {"keywords": ["passport"]}})[1]


def test_ocr_mrz_misread_fails_checksum_not_corrected(monkeypatch, tmp_path):
    misread = L2.replace("UT7668016", "UT766801O", 1)  # 0 -> O
    fake_tesseract(monkeypatch, OCR_TEXT.replace(L2[:22], misread[:22]))
    blank_pdf(tmp_path / "passport.pdf")
    pp = ing.ingest(tmp_path)[0]
    assert "UT766801O" in pp["pages"][0]["text"]  # not auto-corrected
    issues = check_mrz(pp_ext(), pp)
    assert (IssueKind.INVALID, "passport_number") in {(i.kind, i.field) for i in issues}


def test_png_input_is_single_page_doc(monkeypatch, tmp_path):
    fake_tesseract(monkeypatch, OCR_TEXT)
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 20, 20), False)
    pix.save(tmp_path / "passport.png")
    [d] = ing.ingest(tmp_path)
    assert d["filename"] == "passport.png" and len(d["pages"]) == 1
    assert d["pages"][0]["text_source"] == "ocr"


def test_no_tesseract_keeps_no_text_layer_with_warning(monkeypatch, tmp_path):
    monkeypatch.setenv("VISA_OCR", "tesseract")
    monkeypatch.setattr(ing.shutil, "which", lambda _: None)
    blank_pdf(tmp_path / "passport.pdf")
    with pytest.warns(UserWarning, match="unavailable"):
        [d] = ing.ingest(tmp_path)
    assert d["no_text_layer"] and d["pages"][0]["text_source"] == "pdf_text"


def test_case06_unchanged_when_ocr_unavailable(monkeypatch, tmp_path):
    monkeypatch.setattr(ing.shutil, "which", lambda _: None)
    case = next(p for p in (ROOT / "cases").iterdir() if p.name.startswith("case06"))
    exp, _crm, _gw, llm, deps = setup_case(case, tmp_path)
    with pytest.warns(UserWarning):
        res = run(ROOT / "cases" / exp["packet"], deps, case=exp["case"], ocr=exp.get("ocr"))
    bank = next(d for d in res.docs if d["doc_id"] == "bank_statement")
    assert bank["flags"] == ["no_text_layer"]
    assert all(i.kind == IssueKind.UNVERIFIABLE for i in res.issues if i.field in ("closing_balance",))


def test_backend_choice(monkeypatch):
    monkeypatch.setattr(ing, "_has_rapidocr", lambda: False)
    monkeypatch.setattr(ing.shutil, "which", lambda _: None)
    monkeypatch.delenv("VISA_OCR", raising=False)
    assert ing.ocr_backend() == "none"
    monkeypatch.setattr(ing.shutil, "which", lambda _: "/usr/bin/tesseract")
    assert ing.ocr_backend() == "tesseract"
    monkeypatch.setattr(ing, "_has_rapidocr", lambda: True)
    assert ing.ocr_backend() == "rapidocr"
    monkeypatch.setenv("VISA_OCR", "none")
    assert ing.ocr_backend() == "none" and ing.ocr_backend("tesseract") == "tesseract"  # case override wins


OCR_PAGE = {"doc_id": "passport", "pages": [{"page": 1, "text_source": "ocr", "text":
            "Date ofbirth\n09JUN 1970\n12NOV2030\nAccount holder\nDEBORAHDAVIS\nASHLEYANNE"}]}


def test_ocr_dropped_spaces_dates_and_names():
    from visa_agent.verify import find_quote, value_in_quote
    from .test_core import FORMATS
    assert find_quote("09 JUN 1970", OCR_PAGE, 1)["page"] == 1  # whitespace is not evidence on OCR pages
    assert find_quote("09 JUN 1970", {**OCR_PAGE, "pages": [{**OCR_PAGE["pages"][0], "text_source": "pdf_text"}]}, 1) is None
    assert value_in_quote("2030-11-12", "12NOV2030", "date", FORMATS, ocr=True) is None
    assert value_in_quote("1970-06-09", "09JUN 1970", "date", FORMATS, ocr=True) is None
    assert value_in_quote("2030-11-12", "12NOV2030", "date", FORMATS) == "date not in quote"  # text pages unchanged
    assert value_in_quote("2030-11-13", "12NOV2030", "date", FORMATS, ocr=True) == "date not in quote"
    assert value_in_quote("2030-11-12", "112NOV20301", "date", FORMATS, ocr=True) == "date not in quote"  # no digit runs
    assert value_in_quote("DEBORAH DAVIS", "DEBORAHDAVIS", "name", FORMATS, ocr=True) is None
    assert value_in_quote("ANN", "ASHLEYANNE", "name", FORMATS, ocr=True) is not None  # whole-word rule kept
    assert value_in_quote("DEBORAH DAVIS", "DEBORAHDAVIS", "name", FORMATS) is not None
    assert value_in_quote("UT4279522", "Passport.No. UT4279522", "passport_no", FORMATS, ocr=True) is None


@pytest.mark.skipif(not ing._has_rapidocr(), reason="RapidOCR not installed (`make setup-ocr`)")
def test_rapidocr_reads_r4_passport_mrz():
    case = ROOT / "realistic" / "cases" / "R4_scanned_passport"
    [pp] = [d for d in ing.ingest(case, "rapidocr") if d["doc_id"] == "passport"]
    page = pp["pages"][0]
    assert page["text_source"] == "ocr" and page["ocr_backend"] == "rapidocr"
    assert "UT42795228UT07006090M3011124<<<<<<<<<<<<<<00" in page["text"].splitlines()
    assert "UT4279522" in page["text"] and "MALDONADO" in page["text"]


def test_cross_doc_names_ignore_whitespace_only_with_ocr_source():
    from visa_agent.schemas import Extraction, Field
    from visa_agent.validators import cross_doc
    from .test_core import FIELDS
    v = lambda s: Field(value=s, evidence_quote=s, page=1, status=FieldStatus.VERIFIED)
    ex = {"passport": Extraction(doc_type="passport", fields={"full_name": v("DEBORAH DAVIS")}),
          "bank_statement": Extraction(doc_type="bank_statement", fields={"account_holder": v("DEBORAHDAVIS")})}
    assert [i.field for i in cross_doc(ex, FIELDS)] == ["account_holder"]  # text PDFs: still a CONFLICT
    assert cross_doc(ex, FIELDS, {"bank_statement"}) == []
    ex["bank_statement"].fields["account_holder"] = v("DEBORAHDAVID")
    assert [i.field for i in cross_doc(ex, FIELDS, {"bank_statement"})] == ["account_holder"]
