from __future__ import annotations

import io
import logging
from pathlib import Path

import pytest
import pillow_heif
from PIL import Image

from receipt_fixer.core.normalize import UnsupportedFormatError, normalize_to_png
from receipt_fixer.core.scanner import ReceiptFile

pillow_heif.register_heif_opener()


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _make_jpeg_file(path: Path, size=(8, 8)) -> Path:
    img = Image.new("RGB", size, color=(200, 100, 50))
    img.save(path, format="JPEG")
    return path


def _make_png_file(path: Path, size=(8, 8)) -> Path:
    img = Image.new("RGB", size, color=(50, 100, 200))
    img.save(path, format="PNG")
    return path


def _make_heic_file(path: Path, size=(8, 8)) -> Path:
    img = Image.new("RGB", size, color=(10, 20, 30))
    img.save(path, format="HEIF")
    return path


def _make_webp_file(path: Path, size=(8, 8)) -> Path:
    img = Image.new("RGB", size, color=(0, 200, 100))
    img.save(path, format="WEBP")
    return path


def _make_pdf_file(path: Path, pages: int = 1) -> Path:
    """Build a minimal but valid multi-page PDF using only stdlib bytes arithmetic."""
    objects: list[bytes] = []

    # Object 1: Catalog
    objects.append(b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n")

    # Object 2: Pages node — kids are objects 3..3+pages-1
    kids = " ".join(f"{3 + i} 0 R" for i in range(pages))
    objects.append(
        f"2 0 obj\n<< /Type /Pages /Kids [{kids}] /Count {pages} >>\nendobj\n".encode()
    )

    # One Page object per requested page
    for i in range(pages):
        objects.append(
            f"{3 + i} 0 obj\n"
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>\n"
            f"endobj\n".encode()
        )

    # Assemble body and compute xref offsets
    header = b"%PDF-1.4\n"
    body = b""
    offsets: list[int] = []
    for obj in objects:
        offsets.append(len(header) + len(body))
        body += obj

    xref_offset = len(header) + len(body)
    n_objects = len(objects) + 1  # +1 for the free entry

    xref = b"xref\n"
    xref += f"0 {n_objects}\n".encode()
    xref += b"0000000000 65535 f \n"
    for off in offsets:
        xref += f"{off:010d} 00000 n \n".encode()

    trailer = (
        f"trailer\n<< /Size {n_objects} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n"
    ).encode()

    path.write_bytes(header + body + xref + trailer)
    return path


def _receipt(path: Path, fmt: str, reason: str = "") -> ReceiptFile:
    return ReceiptFile(path=path, format=fmt, size_bytes=path.stat().st_size, reason=reason)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_png_roundtrip_dimensions(tmp_path):
    src = _make_png_file(tmp_path / "src.png", size=(16, 24))
    rf = _receipt(src, "png")
    out = normalize_to_png(rf, tmp_path / "work")

    assert out.suffix == ".png"
    with Image.open(out) as img:
        assert img.format == "PNG"
        assert img.size == (16, 24)


def test_jpeg_converts_to_png(tmp_path):
    src = _make_jpeg_file(tmp_path / "src.jpg")
    rf = _receipt(src, "jpg")
    out = normalize_to_png(rf, tmp_path / "work")

    assert out.suffix == ".png"
    with Image.open(out) as img:
        assert img.format == "PNG"


def test_heic_to_png(tmp_path):
    src = _make_heic_file(tmp_path / "src.heic")
    rf = _receipt(src, "heic")
    out = normalize_to_png(rf, tmp_path / "work")

    assert out.suffix == ".png"
    with Image.open(out) as img:
        assert img.format == "PNG"


def test_webp_to_png(tmp_path):
    src = _make_webp_file(tmp_path / "src.webp", size=(16, 24))
    rf = _receipt(src, "webp")
    out = normalize_to_png(rf, tmp_path / "work")

    assert out.suffix == ".png"
    with Image.open(out) as img:
        assert img.format == "PNG"
        assert img.size == (16, 24)


def test_pdf_to_png(tmp_path):
    src = _make_pdf_file(tmp_path / "src.pdf", pages=1)
    rf = _receipt(src, "pdf")
    out = normalize_to_png(rf, tmp_path / "work")

    assert out.suffix == ".png"
    with Image.open(out) as img:
        assert img.format == "PNG"


def test_multipage_pdf_uses_page_1_and_warns(tmp_path, caplog):
    src = _make_pdf_file(tmp_path / "multi.pdf", pages=2)
    rf = _receipt(src, "pdf")

    with caplog.at_level(logging.WARNING, logger="receipt_fixer.core.normalize"):
        out = normalize_to_png(rf, tmp_path / "work")

    assert out.exists()
    assert any("page 1 only" in r.message for r in caplog.records)


def test_unsupported_raises(tmp_path):
    junk = tmp_path / "junk.bin"
    junk.write_bytes(b"\x00\x01\x02")
    rf = _receipt(junk, "unsupported", reason="unrecognised content")

    with pytest.raises(UnsupportedFormatError):
        normalize_to_png(rf, tmp_path / "work")


def test_work_dir_created_if_missing(tmp_path):
    src = _make_png_file(tmp_path / "src.png")
    rf = _receipt(src, "png")
    work = tmp_path / "deep" / "nested" / "work"

    out = normalize_to_png(rf, work)
    assert out.exists()
