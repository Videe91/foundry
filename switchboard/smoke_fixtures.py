"""Packet: P-005 — Anthropic Polish: Cache Fix + Streaming.

One job: the inline binary fixtures the smoke run sends as attachments — a 1x1
PNG and a minimal one-page PDF, both built without any image or PDF library.

Split from smoke.py under the R-017 precedent so both stay under the ceiling.

Version: 0.5.0
"""

from __future__ import annotations

TINY_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8"
    "BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
_PDF_STREAM = b"BT /F1 24 Tf 20 100 Td (Foundry P-004) Tj ET"


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
