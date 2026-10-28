"""Steps 1-2: read a packet folder into pages (pymupdf, layout-sorted so form values sit under their labels), classify each doc deterministically, scan for injection.
A page under 30 chars is rasterised and OCR'd (env VISA_OCR = auto|rapidocr|tesseract|none; auto = RapidOCR if
installed, else the tesseract CLI if on PATH); with no backend it stays `no_text_layer`.
OCR text is never corrected; only whitespace inside MRZ-shaped lines is removed (checksums then catch misreads)."""
import os
import re
import unicodedata
import shutil
import subprocess
import tempfile
import warnings
from pathlib import Path
from typing import Any

import fitz  # pymupdf

MIN_CHARS = 30
UNCLASSIFIED = "UNCLASSIFIED"
# Doc text is data. Instruction-like phrases are flagged, never obeyed (the LLM has no tools anyway).
# Matched on folded text (NFKC, common Cyrillic/Greek look-alikes -> Latin, casefold, whitespace runs -> one space).
# A signal, not a guarantee: the LLM has no tools and code decides every write; this only routes to human review.
INJECTION_MARKERS = [r"(ignore|disregard|forget|override) (all |any |the )?(previous|prior|above|earlier|preceding) "
                     r"(instructions|guidance|rules|prompts?)", r"system (note|prompt|message) ?:", r"set (the )?status",
                     r"mark (it |this |the application )?(as )?approved", r"you are now",
                     r"ignorez les instructions", r"ignora (las|le) (instrucciones|istruzioni)", r"ignoriere (alle )?(vorherigen )?anweisungen"]
_CONFUSABLES = str.maketrans("аеорсухіјѕԁɡοαν", "aeopcyxijsdgoav")


def _fold(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text).casefold().translate(_CONFUSABLES))


IMAGE_EXTS = {".png", ".jpg", ".jpeg"}
OCR_DPI = 200  # RapidOCR reads the MRZ intact at 150-200 dpi; at 250+ it splits MRZ line 2 (measured on R5)
_MRZ_SPACED = re.compile(r"^[A-Z0-9<\s]{44,60}$")


def _mrz_whitespace(text: str) -> str:
    """Drop whitespace inside lines that are exactly 44 MRZ chars once spaces are removed. No char substitution."""
    out = []
    for ln in text.splitlines():
        squashed = re.sub(r"\s+", "", ln)
        out.append(squashed if _MRZ_SPACED.match(ln.strip()) and len(squashed) == 44 else ln)
    return "\n".join(out)


def _tesseract(png: bytes) -> str | None:
    with tempfile.NamedTemporaryFile(suffix=".png") as f:
        f.write(png)
        f.flush()
        try:
            r = subprocess.run([shutil.which("tesseract") or "tesseract", f.name, "stdout"],
                               capture_output=True, text=True, timeout=120)
        except (OSError, subprocess.SubprocessError) as e:
            warnings.warn(f"tesseract failed: {e}", stacklevel=2)
            return None
    return r.stdout if r.returncode == 0 else None


_RAPID = []  # one cached engine (model load ~0.1 s)


def _rapidocr(png: bytes) -> str | None:
    if not _RAPID:
        from rapidocr_onnxruntime import RapidOCR  # optional extra: pip install '.[ocr]'
        _RAPID.append(RapidOCR())
    result, _ = _RAPID[0](png)
    return "\n".join(r[1] for r in result or [])  # one line per detected box, top-to-bottom as returned


def _has_rapidocr() -> bool:
    try:
        import rapidocr_onnxruntime  # noqa: F401
        return True
    except ImportError:
        return False


def ocr_backend(choice: str | None = None) -> str:
    """VISA_OCR = auto (default) | rapidocr | tesseract | none. auto picks the first one available.
    `choice` (a case's expected.json "ocr") overrides the env, e.g. case06 fixes OCR off."""
    choice = (choice or os.environ.get("VISA_OCR") or "auto").strip().lower()
    if choice == "auto":
        return "rapidocr" if _has_rapidocr() else "tesseract" if shutil.which("tesseract") else "none"
    return choice


def ocr_png(png: bytes, choice: str | None = None) -> tuple[str, str] | None:
    """(text, backend) for one PNG, or None if no backend is available or it fails (caller keeps no_text_layer)."""
    backend = ocr_backend(choice)
    if backend not in ("rapidocr", "tesseract") or (backend == "tesseract" and not shutil.which("tesseract")):
        warnings.warn(f"OCR off or unavailable (backend {backend!r}; `make setup-ocr`, or tesseract on PATH): "
                      "image-only pages stay no_text_layer (UNVERIFIABLE)", stacklevel=2)
        return None
    text = _rapidocr(png) if backend == "rapidocr" else _tesseract(png)
    return None if text is None else (_mrz_whitespace(text), backend)


def _page(n: int, text: str, pix_png, ocr: str | None = None) -> dict[str, Any]:
    src, backend = "pdf_text", None
    if len(text.strip()) < MIN_CHARS and (got := ocr_png(pix_png(), ocr)) and len(got[0].strip()) >= MIN_CHARS:
        (text, backend), src = got, "ocr"
    return {"page": n, "text": text, "text_source": src, "ocr_backend": backend,
            "no_text_layer": len(text.strip()) < MIN_CHARS}


def ingest(packet: Path, ocr: str | None = None) -> list[dict[str, Any]]:
    """Return [{"doc_id", "filename", "no_text_layer", "ocr_used",
    "pages": [{"page", "text", "text_source": "pdf_text"|"ocr", "ocr_backend": "rapidocr"|"tesseract"|None, "no_text_layer"}]}]. PNG/JPG = one-page doc."""
    docs = []
    for f in sorted(p for p in Path(packet).iterdir() if p.suffix.lower() in IMAGE_EXTS | {".pdf"}):
        if f.suffix.lower() == ".pdf":
            with fitz.open(f) as d:
                pages = [_page(i + 1, p.get_text(sort=True), lambda p=p: p.get_pixmap(dpi=OCR_DPI).tobytes("png"), ocr)
                         for i, p in enumerate(d)]
        else:
            pages = [_page(1, "", lambda f=f: fitz.Pixmap(str(f)).tobytes("png"), ocr)]
        docs.append({"doc_id": f.stem, "filename": f.name, "pages": pages,
                     "no_text_layer": all(p["no_text_layer"] for p in pages),
                     "ocr_used": any(p["text_source"] == "ocr" for p in pages)})
    return docs


def _hint_types(filename: str, doc_types: dict[str, Any]) -> set[str]:
    name = filename.lower()
    return {t for t, cfg in doc_types.items() if any(h in name for h in cfg.get("filename_hints", []))}


def classify(doc: dict[str, Any], doc_types: dict[str, Any]) -> tuple[str, list[str]]:
    """Return (doc_type | UNCLASSIFIED, flags). Content keywords decide; filename only breaks ties.
    A filename that points at exactly one *other* type is a disagreement -> UNCLASSIFIED.
    A doc with no text layer is classified by filename alone and flagged `no_text_layer`; OCR docs get `ocr_used`."""
    hints = _hint_types(doc["filename"], doc_types)
    if doc["no_text_layer"]:
        return (hints.pop() if len(hints) == 1 else UNCLASSIFIED), ["no_text_layer"]
    t, flags = _classify_text(doc, doc_types, hints)
    return t, flags + ["ocr_used"] * bool(doc.get("ocr_used"))


def _classify_text(doc: dict[str, Any], doc_types: dict[str, Any], hints: set[str]) -> tuple[str, list[str]]:
    text = " ".join(p["text"] for p in doc["pages"]).casefold()
    scores = {t: sum(k.casefold() in text for k in cfg["keywords"]) for t, cfg in doc_types.items()}
    best = max(scores.values())
    if best == 0:
        return UNCLASSIFIED, []
    top = {t for t, s in scores.items() if s == best}
    if len(top) > 1:
        top &= hints  # tie-breaker
    if len(top) != 1:
        return UNCLASSIFIED, []
    winner = top.pop()
    if len(hints) == 1 and winner not in hints:
        return UNCLASSIFIED, ["filename_disagrees"]
    return winner, []


def injection_markers(docs: list[dict[str, Any]]) -> list[str]:
    """Return the doc_ids whose text contains an instruction-like marker."""
    return [d["doc_id"] for d in docs
            if any(re.search(m, _fold(p["text"])) for p in d["pages"] for m in INJECTION_MARKERS)]
