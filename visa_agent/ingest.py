"""Steps 1-2: read a packet folder into pages (pymupdf, layout-sorted so form values sit under their labels), classify each doc deterministically, scan for injection.
A page under 30 chars is rasterised and OCR'd with the `tesseract` CLI (if installed); otherwise it is `no_text_layer`.
OCR text is never corrected; only whitespace inside MRZ-shaped lines is removed (checksums then catch misreads)."""
import re
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
INJECTION_MARKERS = [r"ignore (all |any )?(previous|prior|above) instructions", r"system (note|prompt)\s*:",
                     r"set (the )?status", r"you are now"]


IMAGE_EXTS = {".png", ".jpg", ".jpeg"}
OCR_DPI = 300
_MRZ_SPACED = re.compile(r"^[A-Z0-9<\s]{44,60}$")


def _mrz_whitespace(text: str) -> str:
    """Drop whitespace inside lines that are exactly 44 MRZ chars once spaces are removed. No char substitution."""
    out = []
    for ln in text.splitlines():
        squashed = re.sub(r"\s+", "", ln)
        out.append(squashed if _MRZ_SPACED.match(ln.strip()) and len(squashed) == 44 else ln)
    return "\n".join(out)


def ocr_png(png: bytes) -> str | None:
    """OCR one PNG via the tesseract CLI. None if tesseract is missing or fails (caller keeps no_text_layer)."""
    exe = shutil.which("tesseract")
    if not exe:
        warnings.warn("tesseract not installed: image-only pages stay no_text_layer (UNVERIFIABLE)", stacklevel=2)
        return None
    with tempfile.NamedTemporaryFile(suffix=".png") as f:
        f.write(png)
        f.flush()
        try:
            r = subprocess.run([exe, f.name, "stdout"], capture_output=True, text=True, timeout=120)
        except (OSError, subprocess.SubprocessError) as e:
            warnings.warn(f"tesseract failed: {e}", stacklevel=2)
            return None
    return _mrz_whitespace(r.stdout) if r.returncode == 0 else None


def _page(n: int, text: str, pix_png) -> dict[str, Any]:
    src = "pdf_text"
    if len(text.strip()) < MIN_CHARS and (ocr := ocr_png(pix_png())) is not None and len(ocr.strip()) >= MIN_CHARS:
        text, src = ocr, "ocr"
    return {"page": n, "text": text, "text_source": src, "no_text_layer": len(text.strip()) < MIN_CHARS}


def ingest(packet: Path) -> list[dict[str, Any]]:
    """Return [{"doc_id", "filename", "no_text_layer", "ocr_used",
    "pages": [{"page", "text", "text_source": "pdf_text"|"ocr", "no_text_layer"}]}]. PNG/JPG = one-page doc."""
    docs = []
    for f in sorted(p for p in Path(packet).iterdir() if p.suffix.lower() in IMAGE_EXTS | {".pdf"}):
        if f.suffix.lower() == ".pdf":
            with fitz.open(f) as d:
                pages = [_page(i + 1, p.get_text(sort=True), lambda p=p: p.get_pixmap(dpi=OCR_DPI).tobytes("png"))
                         for i, p in enumerate(d)]
        else:
            pages = [_page(1, "", lambda f=f: fitz.Pixmap(str(f)).tobytes("png"))]
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
            if any(re.search(m, p["text"], re.IGNORECASE) for p in d["pages"] for m in INJECTION_MARKERS)]
