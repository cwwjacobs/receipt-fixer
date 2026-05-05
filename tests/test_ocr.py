from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------------------
# Skip entire module if Tesseract binary is not installed
# ---------------------------------------------------------------------------

tesseract_missing = shutil.which("tesseract") is None

pytestmark = pytest.mark.skipif(
    tesseract_missing,
    reason="Tesseract binary not installed — skipping OCR tests",
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

_TTF_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/Library/Fonts/Arial.ttf",
    "C:/Windows/Fonts/arial.ttf",
)


def _load_font():
    for candidate in _TTF_CANDIDATES:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size=32)
    return ImageFont.load_default()


def _make_text_png(path: Path, text: str, size=(600, 120)) -> Path:
    """Render *text* onto a white PNG at a size Tesseract can reliably read.

    PIL's default bitmap font is too small for Tesseract to consistently
    pick up punctuation like decimal points; we use a TTF when one is
    available on the system."""
    img = Image.new("RGB", size, color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.text((20, 30), text, fill=(0, 0, 0), font=_load_font())
    img.save(path, format="PNG")
    return path


def _make_blank_png(path: Path, size=(100, 100)) -> Path:
    img = Image.new("RGB", size, color=(255, 255, 255))
    img.save(path, format="PNG")
    return path


# ---------------------------------------------------------------------------
# Tests (only run when Tesseract is present)
# ---------------------------------------------------------------------------

def test_known_text_extracted(tmp_path):
    from receipt_fixer.core.ocr import extract_text

    png = _make_text_png(tmp_path / "receipt.png", "TOTAL $42.00")
    result = extract_text(png)

    assert "TOTAL" in result.raw_text
    assert "42.00" in result.raw_text


def test_confidence_in_range(tmp_path):
    from receipt_fixer.core.ocr import extract_text

    png = _make_text_png(tmp_path / "receipt.png", "TOTAL $42.00")
    result = extract_text(png)

    assert 0.0 <= result.confidence <= 100.0


def test_empty_image_no_crash(tmp_path):
    from receipt_fixer.core.ocr import extract_text

    png = _make_blank_png(tmp_path / "blank.png")
    result = extract_text(png)

    assert isinstance(result.raw_text, str)
    assert 0.0 <= result.confidence <= 100.0
    assert result.word_count == 0


def test_word_count_positive_for_text_image(tmp_path):
    from receipt_fixer.core.ocr import extract_text

    png = _make_text_png(tmp_path / "receipt.png", "TOTAL $42.00")
    result = extract_text(png)

    assert result.word_count > 0


def test_blank_image_does_not_report_phantom_confidence(tmp_path):
    # Regression: Tesseract sometimes emits a single conf=95 / text=''
    # row for blank-ish images. If those rows feed the average we get a
    # high confidence with zero words — which then lands at exactly 45.0
    # after the extractor's date/total penalties.
    from receipt_fixer.core.ocr import extract_text

    png = _make_blank_png(tmp_path / "blank.png")
    result = extract_text(png)

    if result.word_count == 0:
        assert result.confidence == 0.0
