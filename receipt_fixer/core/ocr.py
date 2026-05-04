from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

import pytesseract
from PIL import Image


def tesseract_install_hint() -> str:
    """Return install instructions appropriate to the current OS."""
    if sys.platform.startswith("win"):
        return (
            "Install Tesseract from:\n"
            "  https://github.com/UB-Mannheim/tesseract/wiki\n"
            "Then add the install folder (e.g. C:\\Program Files\\Tesseract-OCR) "
            "to your PATH."
        )
    if sys.platform == "darwin":
        return (
            "Install Tesseract via Homebrew:\n"
            "  brew install tesseract"
        )
    return (
        "Install Tesseract via your package manager:\n"
        "  Debian/Ubuntu: sudo apt install tesseract-ocr\n"
        "  Fedora:        sudo dnf install tesseract\n"
        "  Arch:          sudo pacman -S tesseract"
    )


def _check_tesseract() -> None:
    if shutil.which("tesseract") is None:
        raise EnvironmentError(
            "Tesseract OCR binary not found.\n\n" + tesseract_install_hint()
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
