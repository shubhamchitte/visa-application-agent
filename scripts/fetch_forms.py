"""Download the official blank forms used by mock_data/realistic/build.py to a gitignored path.

The PDFs are third-party government publications and are NOT committed (real_samples/raw/ is in .gitignore).
Run: python scripts/fetch_forms.py [--force]
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.request
from pathlib import Path

DEST = Path(__file__).resolve().parent.parent / "real_samples" / "raw"
FORMS = {
    "schengen_udi.pdf": "https://udi.no/globalassets/global/skjemaer/application-for-schengen-visa.pdf",
}


def fetch(force: bool = False) -> list[Path]:
    DEST.mkdir(parents=True, exist_ok=True)
    out = []
    for name, url in FORMS.items():
        path = DEST / name
        if path.exists() and not force:
            print(f"have {path}")
        else:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (mock-data fetch)"})
            with urllib.request.urlopen(req, timeout=60) as r:  # follows the 301 to the canonical URL
                data = r.read()
            if not data.startswith(b"%PDF"):
                sys.exit(f"{url} did not return a PDF")
            path.write_bytes(data)
            print(f"downloaded {path} ({len(data)} bytes, sha256 {hashlib.sha256(data).hexdigest()[:12]})")
        out.append(path)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    fetch(ap.parse_args().force)
