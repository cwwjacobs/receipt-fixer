from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

import pytesseract
from PIL import Image


def tesseract_install_hint(platform: str | None = None) -> str:
    """Return install instructions appropriate to *platform* (defaults to
    sys.platform). One line per OS so it fits cleanly in messageboxes and
    CLI output."""
    plat = platform if platform is not None else sys.platform
    if plat == "win32" or plat.startswith("win"):
        return (
            "Install Tesseract from "
            "https://github.com/UB-Mannheim/tesseract/wiki"
        )
    if plat == "darwin":
        return "Install Tesseract: brew install tesseract"
    # linux* and anything else
    return "Install Tesseract: sudo apt install tesseract-ocr"


def _check_tesseract() -> None:
    if shutil.which("tesseract") is None:
        raise EnvironmentError(
            "Tesseract OCR binary not found. " + tesseract_install_hint()
        )


@dataclass
class OcrResult:
    raw_text: str
    confidence: float   # 0–100 average over words with confidence > -1
    word_count: int


def extract_text(png_path: Path) -> OcrResult:
    """Run Tesseract on *png_path* and return raw text with file-level confidence."""
    _check_tesseract()
    img = Image.open(png_path)
    data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)

    # Tesseract reports -1 confidence for non-word rows, and sometimes emits
    # rows with positive conf but empty/whitespace text (e.g. on blank-ish
    # images it can return a single conf=95 row with text=''). Both must be
    # filtered, otherwise the confidence average reflects phantom "words" the
    # extractor has no text for.
    scored = [
        (t, c) for t, c in zip(data["text"], data["conf"])
        if c != -1 and t.strip()
    ]

    raw_text = pytesseract.image_to_string(img).strip()
    confidence = sum(c for _, c in scored) / len(scored) if scored else 0.0
    words = [t for t, _ in scored]

    return OcrResult(
        raw_text=raw_text,
        confidence=round(confidence, 2),
        word_count=len(words),
    )
