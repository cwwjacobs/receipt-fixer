"""Tests for pure helpers used by the Tk GUI.

We test only the helpers — not the Tk widgets — so these run headless.
"""
from __future__ import annotations

from receipt_fixer.gui.app import (
    NOT_DO_SECTION_HEADING,
    _extract_readme_section,
)


SAMPLE_README = """\
# Receipt Fixer

Intro paragraph.

---

## What it does

- One
- Two

---

## What it does NOT do

- **No cloud.** All processing is local.
- **No AI.** Rule-based parsing.
- **No tax advice.** Decide what's deductible yourself.

---

## Supported v0 path

Stuff after.
"""


def test_extracts_named_section_only():
    body = _extract_readme_section(SAMPLE_README, NOT_DO_SECTION_HEADING)
    assert "No cloud" in body
    assert "No AI" in body
    assert "No tax advice" in body
    # Must not bleed into adjacent sections.
    assert "What it does" not in body or "What it does NOT do" not in body
    assert "Supported v0 path" not in body
    assert "Stuff after" not in body


def test_strips_horizontal_rules():
    body = _extract_readme_section(SAMPLE_README, NOT_DO_SECTION_HEADING)
    for line in body.splitlines():
        assert line.strip() != "---"


def test_returns_empty_when_section_absent():
    body = _extract_readme_section(SAMPLE_README, "Nonexistent Section")
    assert body == ""


def test_gui_log_uses_same_sha256_label_as_receipt_file():
    """Both the GUI verification log and the .receipt.txt file must use the
    'SHA-256 (<csv.name>): <hash>' shape so users see one consistent label.

    Asserted by inspecting the GUI source (not by running Tk), and by
    cross-checking the receipt-builder's output."""
    import inspect
    from datetime import datetime
    from pathlib import Path

    from receipt_fixer.core.output import build_verification_receipt
    from receipt_fixer.gui import app as gui_app

    src = inspect.getsource(gui_app)
    assert 'f"SHA-256 ({csv_path.name}): {csv_sha}"' in src, (
        "GUI must use 'SHA-256 (<csv.name>): <hash>' format, mirroring "
        "the .receipt.txt file. Update receipt_fixer/gui/app.py if this "
        "intentionally changed."
    )

    csv_path = Path("/tmp/example.csv")
    text = build_verification_receipt(
        run_dt=datetime(2026, 1, 1),
        input_folder=csv_path.parent,
        csv_path=csv_path,
        rows=[],
        csv_sha256="b" * 64,
    )
    assert f"SHA-256 ({csv_path.name}): {'b' * 64}" in text
