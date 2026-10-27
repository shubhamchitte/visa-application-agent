"""Steps 1-2: read a packet folder into pages (pymupdf), classify each doc deterministically, scan for injection.
Pages under 30 chars are `no_text_layer`. No OCR in must-have."""
import re
from pathlib import Path
from typing import Any

import fitz  # pymupdf

MIN_CHARS = 30
UNCLASSIFIED = "UNCLASSIFIED"
# Doc text is data. Instruction-like phrases are flagged, never obeyed (the LLM has no tools anyway).
INJECTION_MARKERS = [r"ignore (all |any )?(previous|prior|above) instructions", r"system (note|prompt)\s*:",
                     r"set (the )?status", r"you are now"]


def ingest(packet: Path) -> list[dict[str, Any]]:
    """Return [{"doc_id", "filename", "no_text_layer", "pages": [{"page": n, "text": str, "no_text_layer": bool}]}]."""
    docs = []
    for pdf in sorted(Path(packet).glob("*.pdf")):
        with fitz.open(pdf) as d:
            texts = [p.get_text() for p in d]
        pages = [{"page": i + 1, "text": t, "no_text_layer": len(t.strip()) < MIN_CHARS} for i, t in enumerate(texts)]
        docs.append({"doc_id": pdf.stem, "filename": pdf.name, "pages": pages,
                     "no_text_layer": all(p["no_text_layer"] for p in pages)})
    return docs


def _hint_types(filename: str, doc_types: dict[str, Any]) -> set[str]:
    name = filename.lower()
    return {t for t, cfg in doc_types.items() if any(h in name for h in cfg.get("filename_hints", []))}


def classify(doc: dict[str, Any], doc_types: dict[str, Any]) -> tuple[str, list[str]]:
    """Return (doc_type | UNCLASSIFIED, flags). Content keywords decide; filename only breaks ties.
    A filename that points at exactly one *other* type is a disagreement -> UNCLASSIFIED.
    A doc with no text layer is classified by filename alone and flagged `no_text_layer`."""
    hints = _hint_types(doc["filename"], doc_types)
    if doc["no_text_layer"]:
        return (hints.pop() if len(hints) == 1 else UNCLASSIFIED), ["no_text_layer"]
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
