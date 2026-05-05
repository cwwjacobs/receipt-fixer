"""Tests for the OS-aware Tesseract install hint.

These run regardless of whether the Tesseract binary is present, because
the helper is a pure string function — the user sees its output exactly
when Tesseract is *missing*.
"""
from __future__ import annotations

import receipt_fixer.core.ocr as ocr_mod
from receipt_fixer.core.ocr import tesseract_install_hint


def test_linux_hint_is_apt():
    hint = tesseract_install_hint(platform="linux")
    assert "apt install tesseract-ocr" in hint
    assert "brew" not in hint
    assert "UB-Mannheim" not in hint


def test_macos_hint_is_brew():
    hint = tesseract_install_hint(platform="darwin")
    assert "brew install tesseract" in hint
    assert "apt" not in hint
    assert "UB-Mannheim" not in hint


def test_windows_hint_is_ub_mannheim():
    hint = tesseract_install_hint(platform="win32")
    assert "UB-Mannheim/tesseract" in hint
    assert "apt" not in hint
    assert "brew" not in hint


def test_default_uses_sys_platform(monkeypatch):
    monkeypatch.setattr(ocr_mod.sys, "platform", "darwin")
    assert "brew install tesseract" in tesseract_install_hint()
    monkeypatch.setattr(ocr_mod.sys, "platform", "linux")
    assert "apt install tesseract-ocr" in tesseract_install_hint()
    monkeypatch.setattr(ocr_mod.sys, "platform", "win32")
    assert "UB-Mannheim" in tesseract_install_hint()
