from __future__ import annotations

import csv
import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional, Sequence

from receipt_fixer.core.extract import ExtractedReceipt


CSV_HEADERS = ["File", "Date", "Vendor", "Amount", "Confidence", "Reasons"]

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MMDDYYYY_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")


class CsvVerificationError(Exception):
    """Raised when post-write verification of a CSV fails."""


class CsvExistsError(Exception):
    """Raised when write_csv would overwrite an existing file without force=True."""


@dataclass
class CsvRow:
    file: str
    date: Optional[str] = None          # YYYY-MM-DD or None
    vendor: Optional[str] = None
    amount: Optional[Decimal] = None
    confidence: Optional[float] = None  # 0..100
    reasons: str = ""

    @classmethod
    def from_extracted(
        cls, filename: str, extracted: ExtractedReceipt
    ) -> "CsvRow":
        return cls(
            file=filename,
            date=_mmddyyyy_to_iso(extracted.date),
            vendor=extracted.vendor,
            amount=extracted.amount,
            confidence=extracted.confidence,
            reasons="; ".join(extracted.reasons),
        )

    @classmethod
    def skipped(cls, filename: str, reason: str) -> "CsvRow":
        return cls(file=filename, reasons=reason)


def _mmddyyyy_to_iso(date_str: Optional[str]) -> Optional[str]:
    if not date_str:
        return None
    m = _MMDDYYYY_RE.match(date_str)
    if not m:
        return None
    mm, dd, yyyy = m.groups()
    try:
        return datetime(int(yyyy), int(mm), int(dd)).strftime("%Y-%m-%d")
    except ValueError:
        return None


def _format_amount(amount: Optional[Decimal]) -> str:
    if amount is None:
        return ""
    return f"{amount:.2f}"


def _format_confidence(conf: Optional[float]) -> str:
    if conf is None:
        return ""
    return f"{conf:.1f}"


def write_csv(
    rows: Sequence[CsvRow],
    csv_path: Path,
    *,
    force: bool = False,
) -> None:
    """Write rows to csv_path, then re-open the file and verify its integrity.

    Refuses to overwrite an existing file unless force=True. Raises
    CsvVerificationError if the written file fails post-write checks.
    """
    csv_path = Path(csv_path)
    if csv_path.exists() and not force:
        raise CsvExistsError(
            f"refusing to overwrite existing file: {csv_path} "
            f"(pass force=True to overwrite)"
        )

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_HEADERS)
        for row in rows:
            writer.writerow([
                row.file,
                row.date or "",
                row.vendor or "",
                _format_amount(row.amount),
                _format_confidence(row.confidence),
                row.reasons or "",
            ])

    _verify_written_csv(csv_path, expected_data_rows=len(rows))


def _verify_written_csv(csv_path: Path, *, expected_data_rows: int) -> None:
    try:
        with csv_path.open("r", newline="", encoding="utf-8") as f:
            all_rows = list(csv.reader(f))
    except OSError as exc:
        raise CsvVerificationError(
            f"could not re-open written CSV at {csv_path} for verification: {exc}"
        ) from exc

    if not all_rows:
        raise CsvVerificationError("written CSV is empty (no header row)")

    header = all_rows[0]
    if header != CSV_HEADERS:
        raise CsvVerificationError(
            f"header mismatch: expected {CSV_HEADERS}, got {header}"
        )

    expected_total = 1 + expected_data_rows
    if len(all_rows) != expected_total:
        raise CsvVerificationError(
            f"row count mismatch: expected header + {expected_data_rows} "
            f"data rows ({expected_total} total), got {len(all_rows)}"
        )

    amount_idx = CSV_HEADERS.index("Amount")
    date_idx = CSV_HEADERS.index("Date")

    for line_no, row in enumerate(all_rows[1:], start=2):
        if len(row) != len(CSV_HEADERS):
            raise CsvVerificationError(
                f"row {line_no}: expected {len(CSV_HEADERS)} columns, "
                f"got {len(row)}"
            )

        amount_cell = row[amount_idx]
        if amount_cell != "":
            try:
                Decimal(amount_cell)
            except InvalidOperation as exc:
                raise CsvVerificationError(
                    f"row {line_no}: Amount {amount_cell!r} is not a Decimal"
                ) from exc

        date_cell = row[date_idx]
        if date_cell != "":
            if not _ISO_DATE_RE.match(date_cell):
                raise CsvVerificationError(
                    f"row {line_no}: Date {date_cell!r} is not YYYY-MM-DD"
                )
            try:
                datetime.strptime(date_cell, "%Y-%m-%d")
            except ValueError as exc:
                raise CsvVerificationError(
                    f"row {line_no}: Date {date_cell!r} "
                    f"is not a valid calendar date"
                ) from exc


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def build_verification_receipt(
    *,
    run_dt: datetime,
    input_folder: Path,
    csv_path: Path,
    rows: Sequence[CsvRow],
    csv_sha256: Optional[str] = None,
) -> str:
    total = len(rows)
    fully = sum(
        1 for r in rows if r.amount is not None and r.date is not None
    )
    partial = sum(
        1 for r in rows
        if (r.amount is not None) ^ (r.date is not None)
    )
    failed = total - fully - partial

    sep = "-" * 60
    lines: list[str] = []
    lines.append("RECEIPT FIXER VERIFICATION")
    lines.append("=" * 60)
    lines.append(f"Run: {run_dt.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Input folder: {input_folder}")
    lines.append(f"Output CSV:   {csv_path}")
    lines.append("")

    lines.append("SUMMARY")
    lines.append(sep)
    lines.append(f"  Total files:           {total}")
    lines.append(f"  Fully extracted:       {fully}")
    lines.append(f"  Partial:               {partial}")
    lines.append(f"  Failed / empty:        {failed}")
    lines.append("")

    if csv_sha256 is not None:
        lines.append("INTEGRITY")
        lines.append(sep)
        lines.append(f"  SHA-256 ({csv_path.name}): {csv_sha256}")
        lines.append("")

    lines.append("PER-FILE DETAIL")
    lines.append(sep)
    for r in rows:
        date = r.date or "-"
        vendor = r.vendor or "-"
        amount = f"${r.amount:.2f}" if r.amount is not None else "-"
        conf = f"{r.confidence:.1f}" if r.confidence is not None else "-"
        reasons = r.reasons or "-"
        lines.append(f"  {r.file}")
        lines.append(
            f"    date={date}  vendor={vendor}  "
            f"amount={amount}  conf={conf}"
        )
        lines.append(f"    reasons: {reasons}")
    lines.append("")

    return "\n".join(lines)


def write_verification_receipt(
    *,
    run_dt: datetime,
    input_folder: Path,
    csv_path: Path,
    rows: Sequence[CsvRow],
    receipt_path: Path,
) -> None:
    csv_sha256 = sha256_file(csv_path)
    text = build_verification_receipt(
        run_dt=run_dt,
        input_folder=input_folder,
        csv_path=csv_path,
        rows=rows,
        csv_sha256=csv_sha256,
    )
    receipt_path = Path(receipt_path)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(text, encoding="utf-8")
