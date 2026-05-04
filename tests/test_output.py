import csv
import hashlib
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from receipt_fixer.core import output as output_mod
from receipt_fixer.core.output import (
    CSV_HEADERS,
    CsvExistsError,
    CsvRow,
    CsvVerificationError,
    build_verification_receipt,
    sha256_file,
    write_csv,
    write_verification_receipt,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def sample_rows() -> list[CsvRow]:
    return [
        CsvRow(
            file="a.jpg",
            date="2026-05-03",
            vendor="Walmart",
            amount=Decimal("10.00"),
            confidence=92.5,
            reasons="",
        ),
        CsvRow(
            file="b.pdf",
            date=None,
            vendor=None,
            amount=None,
            confidence=12.0,
            reasons="no total/amount keyword found; no date detected",
        ),
        CsvRow.skipped("c.bmp", "unsupported format"),
    ]


def read_csv_rows(path: Path) -> list[list[str]]:
    with path.open("r", newline="", encoding="utf-8") as f:
        return list(csv.reader(f))


# ---------------------------------------------------------------------------
# Happy-path: write_csv writes a well-formed CSV
# ---------------------------------------------------------------------------

def test_write_csv_writes_header_and_rows(tmp_path):
    rows = sample_rows()
    out = tmp_path / "receipts.csv"
    write_csv(rows, out)

    contents = read_csv_rows(out)
    assert contents[0] == CSV_HEADERS
    assert len(contents) == 1 + len(rows)
    # Amount serialized to 2 decimals; empty when None.
    assert contents[1][CSV_HEADERS.index("Amount")] == "10.00"
    assert contents[2][CSV_HEADERS.index("Amount")] == ""
    # Date stays in YYYY-MM-DD or empty.
    assert contents[1][CSV_HEADERS.index("Date")] == "2026-05-03"
    assert contents[2][CSV_HEADERS.index("Date")] == ""


# ---------------------------------------------------------------------------
# Post-write verification
# ---------------------------------------------------------------------------

def test_write_csv_raises_verification_error_when_amount_corrupted(
    tmp_path, monkeypatch
):
    """If write_csv emits a non-Decimal Amount cell, the post-write
    verification must catch it and raise CsvVerificationError."""

    def bad_format_amount(amount):
        return "NOT_A_NUMBER" if amount is not None else ""

    monkeypatch.setattr(output_mod, "_format_amount", bad_format_amount)

    out = tmp_path / "broken.csv"
    with pytest.raises(CsvVerificationError, match="Amount"):
        write_csv(sample_rows(), out)


def test_write_csv_raises_verification_error_when_date_corrupted(
    tmp_path, monkeypatch
):
    """A non-ISO date in the written file must be caught by verification."""

    rows = [
        CsvRow(
            file="a.jpg",
            date="05/03/2026",  # not YYYY-MM-DD; verifier should reject
            vendor="Walmart",
            amount=Decimal("1.00"),
            confidence=80.0,
        )
    ]
    out = tmp_path / "broken_date.csv"
    with pytest.raises(CsvVerificationError, match="Date"):
        write_csv(rows, out)


def test_write_csv_raises_verification_error_on_row_count_mismatch(
    tmp_path, monkeypatch
):
    """If the writer drops a row, the verifier should notice."""

    real_writer = csv.writer

    class DroppingWriter:
        def __init__(self, target):
            self._w = real_writer(target)
            self._calls = 0

        def writerow(self, row):
            self._calls += 1
            # Drop the second data row (3rd writerow call).
            if self._calls == 3:
                return
            self._w.writerow(row)

    def fake_writer(target):
        return DroppingWriter(target)

    monkeypatch.setattr(output_mod.csv, "writer", fake_writer)
    out = tmp_path / "shortened.csv"
    with pytest.raises(CsvVerificationError, match="row count"):
        write_csv(sample_rows(), out)


# ---------------------------------------------------------------------------
# Overwrite protection
# ---------------------------------------------------------------------------

def test_write_csv_refuses_to_overwrite_existing_file(tmp_path):
    out = tmp_path / "exists.csv"
    out.write_text("old content", encoding="utf-8")

    with pytest.raises(CsvExistsError):
        write_csv(sample_rows(), out)

    # Original content untouched.
    assert out.read_text(encoding="utf-8") == "old content"


def test_write_csv_force_true_overwrites(tmp_path):
    out = tmp_path / "exists.csv"
    out.write_text("old content", encoding="utf-8")

    write_csv(sample_rows(), out, force=True)

    contents = read_csv_rows(out)
    assert contents[0] == CSV_HEADERS
    assert len(contents) == 1 + len(sample_rows())


# ---------------------------------------------------------------------------
# Verification receipt + sha256
# ---------------------------------------------------------------------------

def test_sha256_line_appears_in_receipt_when_provided(tmp_path):
    rows = sample_rows()
    csv_path = tmp_path / "receipts.csv"
    text = build_verification_receipt(
        run_dt=datetime(2026, 5, 4, 12, 0, 0),
        input_folder=tmp_path,
        csv_path=csv_path,
        rows=rows,
        csv_sha256="a" * 64,
    )

    assert "INTEGRITY" in text
    assert f"SHA-256 ({csv_path.name}): " + ("a" * 64) in text
    # SUMMARY appears before INTEGRITY, INTEGRITY before PER-FILE DETAIL.
    assert text.index("SUMMARY") < text.index("INTEGRITY") < text.index(
        "PER-FILE DETAIL"
    )


def test_receipt_omits_integrity_section_when_sha_not_provided(tmp_path):
    text = build_verification_receipt(
        run_dt=datetime(2026, 5, 4, 12, 0, 0),
        input_folder=tmp_path,
        csv_path=tmp_path / "receipts.csv",
        rows=sample_rows(),
    )
    assert "INTEGRITY" not in text
    assert "SHA-256" not in text


def test_write_verification_receipt_sha256_matches_file_content(tmp_path):
    rows = sample_rows()
    csv_path = tmp_path / "receipts.csv"
    write_csv(rows, csv_path)

    receipt_path = tmp_path / "receipt.txt"
    write_verification_receipt(
        run_dt=datetime(2026, 5, 4, 12, 0, 0),
        input_folder=tmp_path,
        csv_path=csv_path,
        rows=rows,
        receipt_path=receipt_path,
    )

    # Independently compute the hash and confirm it appears verbatim.
    independent = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    text = receipt_path.read_text(encoding="utf-8")
    assert independent in text
    assert f"SHA-256 ({csv_path.name}): {independent}" in text

    # And sha256_file should agree.
    assert sha256_file(csv_path) == independent
