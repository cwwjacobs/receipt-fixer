import logging
import sys
import tempfile
from collections import Counter
from pathlib import Path

from receipt_fixer.core.normalize import UnsupportedFormatError, normalize_to_png
from receipt_fixer.core.scanner import scan_input_folder

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")


def main(folder: str, normalize: bool = False) -> None:
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

    if normalize:
        with tempfile.TemporaryDirectory(prefix="receipt_fixer_") as tmp:
            work_dir = Path(tmp)
            ok = skipped = 0
            for rf in files:
                try:
                    out = normalize_to_png(rf, work_dir)
                    print(f"  normalized: {rf.path.name} -> {out.name}")
                    ok += 1
                except UnsupportedFormatError as exc:
                    print(f"  skipped:    {rf.path.name} ({exc})")
                    skipped += 1
            print(f"Normalize complete: {ok} ok, {skipped} skipped.")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Receipt Fixer CLI smoke test")
    parser.add_argument("folder", help="Input folder of receipts")
    parser.add_argument(
        "--normalize",
        action="store_true",
        help="Also normalize each file to PNG in a temp work dir",
    )
    args = parser.parse_args()
    main(args.folder, normalize=args.normalize)
