from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, UnidentifiedImageError

_HIDDEN = {".ds_store", "thumbs.db"}

_PIL_FORMAT_TO_EXT: dict[str, str] = {
    "JPEG": "jpg",
    "PNG": "png",
    "HEIF": "heic",
}

_EXT_TO_EXPECTED_PIL: dict[str, set[str]] = {
    "jpg": {"JPEG"},
    "jpeg": {"JPEG"},
    "png": {"PNG"},
    "heic": {"HEIF"},
}


@dataclass
class ReceiptFile:
    path: Path
    format: str          # "jpg" | "png" | "heic" | "pdf" | "unsupported"
    size_bytes: int
    reason: str = field(default="")


def _detect_pdf(data: bytes) -> bool:
    return data[:5] == b"%PDF-"


def _detect_image(data: bytes) -> str | None:
    """Return PIL format string if bytes are a recognised image, else None."""
    try:
        img = Image.open(io.BytesIO(data))
        img.verify()
        return img.format  # e.g. "JPEG", "PNG", "HEIF"
    except (UnidentifiedImageError, Exception):
        return None


def _classify(p: Path) -> tuple[str, str]:
    """Return (format, reason). reason is empty on success."""
    try:
        data = p.read_bytes()
    except OSError as exc:
        return "unsupported", f"cannot read: {exc}"

    ext = p.suffix.lstrip(".").lower()

    # --- PDF ---
    if _detect_pdf(data):
        return "pdf", ""

    # --- Image via Pillow ---
    pil_fmt = _detect_image(data)
    if pil_fmt is not None:
        canonical = _PIL_FORMAT_TO_EXT.get(pil_fmt)
        if canonical:
            return canonical, ""
        return "unsupported", f"unrecognised image format: {pil_fmt}"

    # --- Nothing matched magic bytes ---
    return "unsupported", f"unrecognised content (extension: .{ext or 'none'})"


def scan_input_folder(path: Path) -> list[ReceiptFile]:
    """
    Walk *path* (non-recursively) and classify every file.
    Hidden files (.DS_Store, Thumbs.db) are silently skipped.
    """
    if not path.is_dir():
        raise NotADirectoryError(f"Not a directory: {path}")

    results: list[ReceiptFile] = []
    for entry in sorted(path.iterdir()):
        if not entry.is_file():
            continue
        if entry.name.lower() in _HIDDEN:
            continue

        fmt, reason = _classify(entry)
        results.append(
            ReceiptFile(
                path=entry,
                format=fmt,
                size_bytes=entry.stat().st_size,
                reason=reason,
            )
        )
    return results
