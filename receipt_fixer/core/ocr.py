from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

import pytesseract
from PIL import Image

_WINDOWS_INSTALL_MSG = (
    "Tesseract OCR binary not found.\n"
    "Install it from: https://github.com/UB-Mannheim/tesseract/wiki\n"
    "Then add the install folder (e.g. C:\\Program Files\\Tesseract-OCR) to PATH."
)


def _check_tesseract() -> None:
    if shutil.which("tesseract") is None:
        raise EnvironmentError(_WINDOWS_INSTALL_MSG)


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

    # Tesseract reports -1 confidence for non-word rows; filter those out
    word_confs = [c for c in data["conf"] if c != -1]
    words = [
        t for t, c in zip(data["text"], data["conf"])
        if c != -1 and t.strip()
    ]

    raw_text = pytesseract.image_to_string(img).strip()
    confidence = sum(word_confs) / len(word_confs) if word_confs else 0.0

    return OcrResult(
        raw_text=raw_text,
        confidence=round(confidence, 2),
        word_count=len(words),
    )
