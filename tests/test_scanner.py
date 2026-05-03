import io
import struct
from pathlib import Path

import pytest
from PIL import Image

from receipt_fixer.core.scanner import scan_input_folder


# ---------------------------------------------------------------------------
# Helpers to build minimal valid file bytes
# ---------------------------------------------------------------------------

def _make_jpeg() -> bytes:
    buf = io.BytesIO()
    img = Image.new("RGB", (1, 1), color=(255, 0, 0))
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _make_png() -> bytes:
    buf = io.BytesIO()
    img = Image.new("RGB", (1, 1), color=(0, 255, 0))
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_pdf() -> bytes:
    # Minimal valid-header PDF (not renderable, but passes magic-byte check)
    return b"%PDF-1.4\n%%EOF\n"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_empty_folder(tmp_path):
    assert scan_input_folder(tmp_path) == []


def test_not_a_directory(tmp_path):
    f = tmp_path / "file.jpg"
    f.write_bytes(_make_jpeg())
    with pytest.raises(NotADirectoryError):
        scan_input_folder(f)


def test_mixed_folder_counts(tmp_path):
    (tmp_path / "a.jpg").write_bytes(_make_jpeg())
    (tmp_path / "b.jpg").write_bytes(_make_jpeg())
    (tmp_path / "c.png").write_bytes(_make_png())
    (tmp_path / "d.pdf").write_bytes(_make_pdf())
    (tmp_path / "e.txt").write_bytes(b"not a receipt")

    results = scan_input_folder(tmp_path)
    fmt_counts = {r.format: 0 for r in results}
    for r in results:
        fmt_counts[r.format] += 1

    assert fmt_counts["jpg"] == 2
    assert fmt_counts["png"] == 1
    assert fmt_counts["pdf"] == 1
    assert fmt_counts["unsupported"] == 1
    assert len(results) == 5


def test_jpeg_extension_with_wrong_content_is_flagged(tmp_path):
    bad = tmp_path / "fake.jpg"
    bad.write_bytes(b"this is definitely not a jpeg")

    results = scan_input_folder(tmp_path)
    assert len(results) == 1
    assert results[0].format == "unsupported"
    assert results[0].reason != ""


def test_hidden_files_skipped(tmp_path):
    (tmp_path / ".DS_Store").write_bytes(b"mac metadata")
    (tmp_path / "Thumbs.db").write_bytes(b"windows metadata")
    (tmp_path / "receipt.jpg").write_bytes(_make_jpeg())

    results = scan_input_folder(tmp_path)
    assert len(results) == 1
    assert results[0].format == "jpg"


def test_size_bytes_populated(tmp_path):
    data = _make_jpeg()
    (tmp_path / "r.jpg").write_bytes(data)

    results = scan_input_folder(tmp_path)
    assert results[0].size_bytes == len(data)


def test_unsupported_has_reason(tmp_path):
    (tmp_path / "junk.bin").write_bytes(b"\x00\x01\x02\x03")

    results = scan_input_folder(tmp_path)
    assert results[0].format == "unsupported"
    assert results[0].reason


def test_pdf_without_pdf_extension_detected(tmp_path):
    (tmp_path / "sneaky.jpg").write_bytes(_make_pdf())

    results = scan_input_folder(tmp_path)
    assert results[0].format == "pdf"
