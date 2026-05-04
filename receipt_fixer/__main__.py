"""Entry point for `python -m receipt_fixer`.

Bootstraps sys.path so the vendored `fixdrawer_app_base` package
under `<repo>/src` resolves whether the user launches the module
from the repo root or from a click-to-run script.
"""
from __future__ import annotations

import sys
from pathlib import Path


def _bootstrap_path() -> None:
    here = Path(__file__).resolve()
    repo_root = here.parent.parent
    src_dir = repo_root / "src"
    if src_dir.is_dir() and str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))


_bootstrap_path()

from receipt_fixer.gui.app import main  # noqa: E402

if __name__ == "__main__":
    main()
