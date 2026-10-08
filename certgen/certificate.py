"""Certificate rendering.

There is exactly one predefined template (A4 landscape). It is drawn with
ReportLab, a pure-Python PDF library that installs without a system-level
dependency. The template is intentionally simple: the assignment does not
ask for a template editor.
"""
from __future__ import annotations

import os

from reportlab.lib.colors import HexColor, black
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

PAGE_SIZE = landscape(A4)
TITLE_FONT = "Helvetica-Bold"
BODY_FONT = "Helvetica"
ACCENT = HexColor("#1F3A5F")
MIN_FONT_SIZE = 12


def fit_font_size(text: str, font: str, max_size: float, max_width: float, min_size: float = MIN_FONT_SIZE) -> float:
    """Shrink the font size until ``text`` fits in ``max_width`` points (never below ``min_size``)."""
    size = max_size
    while size > min_size and stringWidth(text, font, size) > max_width:
        size -= 1
    return size


def render_certificate(output_path: str, *, recipient_name: str, event_name: str, issued_on: str, certificate_id: str) -> None:
    """Write one certificate PDF to ``output_path``.

    The PDF is written to a temporary file first and then renamed, so a crash
    mid-render never leaves a half-written certificate behind.
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    tmp_path = output_path + ".tmp"

    width, height = PAGE_SIZE
    pdf = canvas.Canvas(tmp_path, pagesize=PAGE_SIZE)
    pdf.setTitle(f"Certificate - {recipient_name}")

    # Decorative double border.
    pdf.setStrokeColor(ACCENT)
    pdf.setLineWidth(4)
    pdf.rect(30, 30, width - 60, height - 60)
    pdf.setLineWidth(1)
    pdf.rect(40, 40, width - 80, height - 80)

    _draw_centered(pdf, "CERTIFICATE OF COMPLETION", height - 130, TITLE_FONT, 34, ACCENT)
    _draw_centered(pdf, "This is to certify that", height - 185, BODY_FONT, 18)
    _draw_fitted(pdf, recipient_name, height - 250, TITLE_FONT, 40, max_width=width - 200)
    _draw_centered(pdf, "has successfully completed", height - 300, BODY_FONT, 18)
    _draw_fitted(pdf, event_name, height - 345, TITLE_FONT, 26, max_width=width - 200)
    _draw_centered(pdf, f"Issued on {issued_on}", height - 400, BODY_FONT, 14)
    _draw_centered(pdf, f"Certificate ID: {certificate_id}", 70, BODY_FONT, 10)

    pdf.showPage()
    pdf.save()
    os.replace(tmp_path, output_path)


def _draw_centered(pdf, text, y, font, size, color=black) -> None:
    pdf.setFillColor(color)
    pdf.setFont(font, size)
    pdf.drawCentredString(PAGE_SIZE[0] / 2, y, text)


def _draw_fitted(pdf, text, y, font, max_size, max_width) -> None:
    size = fit_font_size(text, font, max_size, max_width)
    _draw_centered(pdf, text, y, font, size, ACCENT)
