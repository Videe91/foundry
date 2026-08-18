"""Packet: P-009 — Family Four: xAI (Grok) Adapter.

One job: the inline fixtures the smoke run sends as attachments — a 16x16 PNG,
a minimal one-page PDF, and a tiny markdown file — built without any image,
PDF, or markdown library.

Split from smoke.py under the R-017 precedent so both stay under the ceiling.

Version: 0.9.1
"""

from __future__ import annotations

import base64
from pathlib import Path

# 16x16 8-bit greyscale checker, 82 bytes. NOT 1x1: xAI rejects images under
# 8x8 ("Image dimensions 1x1 are too small"), where Anthropic, OpenAI, and
# Gemini all accepted a single pixel (T-006). A shared fixture must satisfy
# the strictest family, so this one clears the only stated minimum with margin.
TINY_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAAAAAA6mKC9AAAAGUlEQVR42mNgAIL/"
    "QIBMkypAqX4YGATuAADA/X+BdAueyAAAAABJRU5ErkJggg=="
)
_PDF_STREAM = b"BT /F1 24 Tf 20 100 Td (Foundry P-004) Tj ET"
TINY_MARKDOWN = "# Foundry test\nP-006"


def tiny_pdf_bytes() -> bytes:
    """Build a minimal one-page PDF by hand — no library, no dependency."""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(_PDF_STREAM)).encode("ascii") + b" >>\nstream\n"
        + _PDF_STREAM + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    for number, body in enumerate(objects, start=1):
        out += str(number).encode("ascii") + b" 0 obj\n" + body + b"\nendobj\n"
    out += b"trailer\n<< /Root 1 0 R /Size 6 >>\n%%EOF\n"
    return bytes(out)


def write_attachment_fixtures(directory: str) -> tuple[Path, Path, Path]:
    """Write one fixture of each kind into a directory, newest kind last."""
    base = Path(directory)
    png_path = base / "pixel.png"
    pdf_path = base / "page.pdf"
    md_path = base / "notes.md"
    png_path.write_bytes(base64.b64decode(TINY_PNG_BASE64))
    pdf_path.write_bytes(tiny_pdf_bytes())
    md_path.write_text(TINY_MARKDOWN, encoding="utf-8")
    return png_path, pdf_path, md_path
