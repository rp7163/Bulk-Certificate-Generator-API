import os

from certgen.certificate import fit_font_size, render_certificate
from reportlab.pdfbase.pdfmetrics import stringWidth


def test_render_writes_a_pdf_and_leaves_no_temp_file(tmp_path):
    out = tmp_path / "job" / "1.pdf"
    render_certificate(
        str(out),
        recipient_name="Asha Patel",
        event_name="Python Workshop",
        issued_on="2026-10-08",
        certificate_id="abc123",
    )
    assert out.exists()
    assert out.read_bytes().startswith(b"%PDF")
    assert not os.path.exists(str(out) + ".tmp")


def test_very_long_name_still_renders(tmp_path):
    out = tmp_path / "long.pdf"
    render_certificate(
        str(out),
        recipient_name="A" * 120,
        event_name="B" * 200,
        issued_on="2026-10-08",
        certificate_id="x",
    )
    assert out.read_bytes().startswith(b"%PDF")


def test_fit_font_size_keeps_short_text_at_max_size():
    assert fit_font_size("Asha", "Helvetica-Bold", 40, max_width=500) == 40


def test_fit_font_size_shrinks_long_text_to_fit():
    text = "A" * 30  # too wide at 40pt, but fits once the font is smaller
    size = fit_font_size(text, "Helvetica-Bold", 40, max_width=500)
    assert size < 40
    assert stringWidth(text, "Helvetica-Bold", size) <= 500


def test_fit_font_size_never_goes_below_minimum():
    size = fit_font_size("A" * 1000, "Helvetica-Bold", 40, max_width=50)
    assert size == 12
