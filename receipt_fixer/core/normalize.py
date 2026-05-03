from __future__ import annotations

import logging
import shutil
from pathlib import Path

import pillow_heif
from PIL import Image, ImageOps
from pdf2image import convert_from_bytes

from receipt_fixer.core.scanner import ReceiptFile

pillow_heif.register_heif_opener()

log = logging.getLogger(__name__)

PDF_DPI = 300


class UnsupportedFormatError(ValueError):
    """Raised when normalize_to_png receives a ReceiptFile with format='unsupported'."""


def _fix_orientation(img: Image.Image) -> Image.Image:
    """Apply EXIF orientation tag so the image is upright."""
    return ImageOps.exif_transpose(img)


def normalize_to_png(receipt_file: ReceiptFile, work_dir: Path) -> Path:
    """
    Convert *receipt_file* to a deskewed/oriented PNG in *work_dir*.
    Returns the path to the output PNG.

    PDF: rasterizes page 1 at 300 DPI; warns if the file has multiple pages.
    HEIC: decoded via pillow-heif, then saved as PNG.
    JPEG/PNG: EXIF orientation applied, then saved as PNG.
    Unsupported: raises UnsupportedFormatError.
    """
    if receipt_file.format == "unsupported":
        raise UnsupportedFormatError(
            f"Cannot normalize unsupported file: {receipt_file.path} "
            f"({receipt_file.reason})"
        )

    work_dir.mkdir(parents=True, exist_ok=True)
    out_path = work_dir / (receipt_file.path.stem + ".png")

    if receipt_file.format == "pdf":
        raw = receipt_file.path.read_bytes()
        pages = convert_from_bytes(raw, dpi=PDF_DPI)
        if len(pages) > 1:
            log.warning(
                "Multi-page PDF '%s' has %d pages — using page 1 only.",
                receipt_file.path.name,
                len(pages),
            )
        img = pages[0]
        img.save(out_path, format="PNG")
        return out_path

    # JPEG, PNG, HEIC — all openable by Pillow after heif registration
    img = Image.open(receipt_file.path)
    img = _fix_orientation(img)
    img.save(out_path, format="PNG")
    return out_path
