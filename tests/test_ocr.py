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

def _make_text_png(path: Path, text: str, size=(400, 100)) -> Path:
    """Render *text* onto a white PNG large enough for Tesseract to read."""
    img = Image.new("RGB", size, color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    # Use default bitmap font — always available, no font files needed
    draw.text((10, 30), text, fill=(0, 0, 0))
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
