"""Top-level launcher used by click-to-run scripts and PyInstaller.

Mirrors the Seller CSV Fixer launcher entry point. Adds the vendored
`src/` directory and the repo root to sys.path before importing the
app, so it works both in dev and inside a frozen bundle.
"""
from __future__ import annotations

import sys
from pathlib import Path


def _bootstrap_path() -> None:
    here = Path(__file__).resolve()
    repo_root = here.parent
    src_dir = repo_root / "src"
    for candidate in (src_dir, repo_root):
        if candidate.is_dir() and str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))


_bootstrap_path()

from receipt_fixer.gui.app import main  # noqa: E402

if __name__ == "__main__":
    main()
