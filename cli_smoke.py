import sys
from pathlib import Path
from collections import Counter

from receipt_fixer.core.scanner import scan_input_folder


def main(folder: str) -> None:
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


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python cli_smoke.py <input_folder>")
        sys.exit(1)
    main(sys.argv[1])
