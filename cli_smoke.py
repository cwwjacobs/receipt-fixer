import logging
import sys
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Optional

from receipt_fixer.core.normalize import UnsupportedFormatError, normalize_to_png
from receipt_fixer.core.scanner import scan_input_folder

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")


def _fmt_amount(amount) -> str:
    if amount is None:
        return "-"
    return f"${amount:.2f}"


def _print_extract_row(name: str, extracted) -> None:
    date = extracted.date or "-"
    vendor = extracted.vendor or "-"
    amount = _fmt_amount(extracted.amount)
    conf = f"{extracted.confidence:.1f}"
    reasons = "; ".join(extracted.reasons) if extracted.reasons else "-"
    print(f"  {name:<28} {date:<11} {vendor:<30} {amount:>10} {conf:>6}  {reasons}")


def main(
    folder: str,
    normalize: bool = False,
    ocr: bool = False,
    extract: bool = False,
    csv_path: Optional[str] = None,
    receipt_path: Optional[str] = None,
    force: bool = False,
) -> None:
    path = Path(folder)
    files = scan_input_folder(path)

    counts: Counter[str] = Counter(f.format for f in files)
    total = len(files)

    parts = [f"{v} {k}" for k, v in sorted(counts.items()) if k != "unsupported"]
    unsupported = counts.get("unsupported", 0)
    if unsupported:
        exts = ", ".join(
            f.path.suffix or "(no ext)"
            for f in files
            if f.format == "unsupported"
        )
        parts.append(f"{unsupported} unsupported ({exts})")

    summary = ", ".join(parts) if parts else "none"
    print(f"Found {total} files: {summary}")

    write_output = csv_path is not None
    if write_output:
        extract = True  # CSV writing implies running the full pipeline

    csv_rows = []

    if normalize or ocr or extract:
        if ocr or extract:
            from receipt_fixer.core.ocr import _check_tesseract, extract_text
            try:
                _check_tesseract()
            except EnvironmentError as exc:
                print(f"ERROR: {exc}")
                sys.exit(1)
        if extract:
            from receipt_fixer.core.extract import extract_fields
            from receipt_fixer.core.output import CsvRow

        if extract:
            header = (
                f"  {'File':<28} {'Date':<11} {'Vendor':<30} "
                f"{'Amount':>10} {'Conf':>6}  Reasons"
            )
            print(header)
            print("  " + "-" * (len(header) - 2))

        with tempfile.TemporaryDirectory(prefix="receipt_fixer_") as tmp:
            work_dir = Path(tmp)
            norm_ok = norm_skip = 0
            for rf in files:
                try:
                    out = normalize_to_png(rf, work_dir)
                    norm_ok += 1
                    if normalize:
                        print(f"  normalized: {rf.path.name} -> {out.name}")
                    if extract:
                        result = extract_text(out)
                        ex = extract_fields(result)
                        _print_extract_row(rf.path.name, ex)
                        if write_output:
                            csv_rows.append(CsvRow.from_extracted(rf.path.name, ex))
                    elif ocr:
                        result = extract_text(out)
                        print(
                            f"  [{rf.path.name}] conf={result.confidence:.1f}% "
                            f"words={result.word_count}"
                        )
                        print(f"    {result.raw_text[:200]!r}")
                except UnsupportedFormatError as exc:
                    norm_skip += 1
                    print(f"  skipped: {rf.path.name} ({exc})")
                    if write_output:
                        csv_rows.append(CsvRow.skipped(rf.path.name, str(exc)))

            if normalize:
                print(f"Normalize complete: {norm_ok} ok, {norm_skip} skipped.")

    if write_output:
        from receipt_fixer.core.output import (
            CsvExistsError,
            write_csv,
            write_verification_receipt,
        )

        out_csv = Path(csv_path)
        try:
            write_csv(csv_rows, out_csv, force=force)
        except CsvExistsError as exc:
            print(f"ERROR: {exc}")
            sys.exit(2)

        out_receipt = Path(receipt_path) if receipt_path else out_csv.with_suffix(
            out_csv.suffix + ".receipt.txt"
        )
        write_verification_receipt(
            run_dt=datetime.now(),
            input_folder=path,
            csv_path=out_csv,
            rows=csv_rows,
            receipt_path=out_receipt,
        )
        print(f"Wrote CSV:     {out_csv}")
        print(f"Wrote receipt: {out_receipt}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Receipt Fixer CLI smoke test")
    parser.add_argument("folder", help="Input folder of receipts")
    parser.add_argument(
        "--normalize",
        action="store_true",
        help="Normalize each file to PNG in a temp work dir",
    )
    parser.add_argument(
        "--ocr",
        action="store_true",
        help="Scan + normalize + OCR each file and print extracted text",
    )
    parser.add_argument(
        "--extract",
        action="store_true",
        help="Run the full pipeline (scan + normalize + OCR + field extraction)",
    )
    parser.add_argument(
        "--csv",
        dest="csv_path",
        default=None,
        help="Write extracted rows to this CSV path (implies --extract)",
    )
    parser.add_argument(
        "--receipt",
        dest="receipt_path",
        default=None,
        help="Write verification receipt to this path "
        "(default: <csv>.receipt.txt next to the CSV)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the CSV if it already exists",
    )
    args = parser.parse_args()
    main(
        args.folder,
        normalize=args.normalize,
        ocr=args.ocr,
        extract=args.extract,
        csv_path=args.csv_path,
        receipt_path=args.receipt_path,
        force=args.force,
    )
