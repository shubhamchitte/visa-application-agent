# Realistic mock packets

Build: `python scripts/fetch_forms.py && python -m mock_data.realistic.build` (deterministic; verified by building twice and diffing).
Needs pypdf, numpy, pillow, pymupdf, reportlab, faker (pinned in pyproject.toml and requirements.lock).
Output: `cases/R1..R6/` (`<doc_type>.pdf`, `truth.json`, `expected.json`, optional `images/` scan samples),
`crm_seed.json` (rec-2001..2006 one per case, plus decoy rec-9901), previews in `docs/sample_docs/realistic_*.png`.
No `fake_llm.json`: the form has separate surname / given-name boxes, so there is no single verbatim quote for full_name;
use a real or replayed LLM. Goldens reuse `mock_data.generator` helpers only (never `visa_agent`).

## Documents
- application_form: the official UDI Schengen PDF (not committed; `real_samples/raw/` is gitignored). Widgets are located
  by (page, name, rect) because names repeat ("Surname at birth..." is both field 1 and 2; "Valid until", "Cash" also repeat).
  Filled values are drawn from the widget rects, checkboxes get an X, then all widgets and /AcroForm are removed (flattened;
  text layer stays). Dates are dd.mm.yyyy, email is inside the address field (field 19), as on the real form.
- passport: 1 page, 612x432 pt, guilloche background (vector, no text), photo box, bilingual labels, SPECIMEN watermark,
  TD3 MRZ in Courier-Bold with charspacing (check digits via the existing generator code).
- bank_statement: 3 pages, 47 rows, running balance, closing balance == truth, summary box, page x of y, fine print.
- employment_letter: letterhead, ref no., salary, role, start date, approved leave = travel dates, signature and seal.
- Scans: 200 dpi render, rotation +-1.3 deg, blur, noise, vignette, specks, then JPEG-embedded image-only PDF.
  `images/` holds page-1 JPG (and a PNG for the passport) for the loose-image path. Do not move them into the packet root:
  ingest reads every .pdf/.png/.jpg in the folder.

## Cases
R1 happy. R2 form surname differs by one letter from passport (CONFLICT, NEEDS_REVIEW, no patch). R3 bank statement absent
(INCOMPLETE; chosen over "stale statement" because TOURIST_UTO has no max-age rule). R4 passport image-only. R5 all four image-only.
R4/R5 `expected.json` assume OCR succeeds (same outcome as R1 plus `ocr_required`); `expected_without_ocr` holds the safe fallback
(passport fields UNVERIFIABLE, NO_WRITE). R6 injection sentence buried mid-paragraph in the last-page fine print.

## Known gap (visa_agent not touched)
`doc_types.yaml` form keywords ("visa application form", "intended date of travel") do not occur in the real UDI form
("Application for Schengen Visa", "Intended date of arrival"), so classification falls back to the filename hint
(`application_form.pdf`). Adding "application for schengen visa" to the keywords would fix it.
