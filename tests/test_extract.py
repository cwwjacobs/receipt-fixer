from decimal import Decimal

import pytest

from receipt_fixer.core.extract import ExtractedReceipt, extract_fields
from receipt_fixer.core.ocr import OcrResult


def make_ocr(text: str, conf: float = 90.0, image_max_dim: int = 0) -> OcrResult:
    return OcrResult(
        raw_text=text,
        confidence=conf,
        word_count=len(text.split()),
        image_max_dim=image_max_dim,
    )


# ---------------------------------------------------------------------------
# Date format coverage
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("WALMART\n05/03/2026\nTOTAL $10.00", "05/03/2026"),
        ("WALMART\n05-03-2026\nTOTAL $10.00", "05/03/2026"),
        ("WALMART\n05/03/26\nTOTAL $10.00", "05/03/2026"),
        ("WALMART\nMay 3, 2026\nTOTAL $10.00", "05/03/2026"),
        ("WALMART\n3 May 2026\nTOTAL $10.00", "05/03/2026"),
        ("WALMART\nMay 3 2026\nTOTAL $10.00", "05/03/2026"),
    ],
)
def test_date_formats_parse(raw, expected):
    result = extract_fields(make_ocr(raw))
    assert result.date == expected


def test_two_digit_year_pivot_2000s():
    # 26 → 2026
    result = extract_fields(make_ocr("VENDOR\n01/15/26\nTOTAL $5.00"))
    assert result.date == "01/15/2026"


def test_latest_date_in_top_half_preferred():
    # Both dates in the top half — pick the chronologically later one.
    text = (
        "VENDOR ABC\n"
        "01/01/2020\n"
        "06/15/2026\n"
        "TOTAL $5.00\n"
        + "filler\n" * 30
    )
    result = extract_fields(make_ocr(text))
    assert result.date == "06/15/2026"


# ---------------------------------------------------------------------------
# Amount priority
# ---------------------------------------------------------------------------

def test_grand_total_beats_total_beats_subtotal():
    text = (
        "WALMART\n"
        "05/03/2026\n"
        "Item A 5.00\n"
        "Item B 5.00\n"
        "SUBTOTAL: $10.00\n"
        "TAX: $1.00\n"
        "TOTAL: $11.00\n"
        "GRAND TOTAL: $11.50\n"
    )
    result = extract_fields(make_ocr(text))
    assert result.amount == Decimal("11.50")


def test_total_beats_subtotal_when_no_grand_total():
    text = (
        "WALMART\n"
        "05/03/2026\n"
        "SUBTOTAL: $10.00\n"
        "TAX: $1.00\n"
        "TOTAL: $11.00\n"
    )
    result = extract_fields(make_ocr(text))
    assert result.amount == Decimal("11.00")


def test_amount_due_priority():
    text = (
        "VENDOR\n"
        "05/03/2026\n"
        "TOTAL: $10.00\n"
        "AMOUNT DUE: $11.00\n"
    )
    result = extract_fields(make_ocr(text))
    assert result.amount == Decimal("11.00")


def test_amount_with_thousands_separator():
    text = "STORE\n05/03/2026\nGRAND TOTAL $1,234.56\n"
    result = extract_fields(make_ocr(text))
    assert result.amount == Decimal("1234.56")


# ---------------------------------------------------------------------------
# Glyph variants — Tesseract often misreads "$" as "S", "*", "&", or drops it.
# Refusal logic is unchanged; only the recognition is loosened.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "glyph",
    ["$", "S", "*", "&", ""],
)
def test_amount_glyph_variants(glyph):
    text = f"VENDOR\n05/03/2026\nTOTAL {glyph} 37.68\n"
    result = extract_fields(make_ocr(text))
    assert result.amount == Decimal("37.68"), f"glyph {glyph!r} failed"


def test_shell_fuel_receipt_real_ocr_shape():
    # The exact OCR shape that triggered chunk 8: FUEL TOTAL line has no
    # cents (just *#), CREDIT line carries the real total with an ampersand
    # standing in for the dollar sign.
    text = (
        "VISA\n"
        "INVOICE 171646\n"
        "PUMP# 7\n"
        "PREMIUM 9.739G\n"
        "PRICE/GAL $3.799\n"
        "FUEL TOTAL *#\n"
        "CREDIT & 37.68\n"
    )
    result = extract_fields(make_ocr(text))
    assert result.amount == Decimal("37.68")


def test_fuel_total_keyword_matches():
    text = "STATION\n05/03/2026\nFUEL TOTAL $42.10\n"
    result = extract_fields(make_ocr(text))
    assert result.amount == Decimal("42.10")


def test_credit_extracts_when_no_higher_priority():
    text = "VENDOR\n05/03/2026\nCREDIT $25.00\n"
    result = extract_fields(make_ocr(text))
    assert result.amount == Decimal("25.00")


def test_higher_priority_beats_credit():
    # GRAND TOTAL (level 4) beats CREDIT (level 1) on the same receipt.
    text = (
        "VENDOR\n"
        "05/03/2026\n"
        "CREDIT $25.00\n"
        "GRAND TOTAL $26.50\n"
    )
    result = extract_fields(make_ocr(text))
    assert result.amount == Decimal("26.50")


def test_amount_keyword_extracts():
    text = "VENDOR\n05/03/2026\nAMOUNT $19.99\n"
    result = extract_fields(make_ocr(text))
    assert result.amount == Decimal("19.99")


def test_balance_due_beats_total():
    text = (
        "VENDOR\n"
        "05/03/2026\n"
        "TOTAL: $10.00\n"
        "BALANCE DUE: $11.00\n"
    )
    result = extract_fields(make_ocr(text))
    assert result.amount == Decimal("11.00")


# ---------------------------------------------------------------------------
# Comma handling
# ---------------------------------------------------------------------------

def test_thousands_separator_extracts_correctly():
    text = "VENDOR\n05/03/2026\nTOTAL $1,234.56\n"
    result = extract_fields(make_ocr(text))
    assert result.amount == Decimal("1234.56")


def test_suspicious_lone_comma_refuses():
    # "$1,23" is ambiguous (truncated US thousands? European decimal?).
    # The extractor must refuse rather than guess.
    text = "VENDOR\n05/03/2026\nTOTAL $1,23\n"
    result = extract_fields(make_ocr(text))
    assert result.amount is None
    assert any("no total/amount keyword" in r for r in result.reasons)


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------

def test_non_usd_currency_refuses():
    text = "BISTRO\n05/03/2026\nTOTAL €25.00\n"
    result = extract_fields(make_ocr(text))
    assert result.amount is None
    assert any("non-USD" in r for r in result.reasons)


@pytest.mark.parametrize("symbol", ["£", "¥"])
def test_other_non_usd_symbols_refuse(symbol):
    text = f"VENDOR\n05/03/2026\nTOTAL {symbol}25.00\n"
    result = extract_fields(make_ocr(text))
    assert result.amount is None
    assert any("non-USD" in r for r in result.reasons)


def test_multi_total_disagreement_refuses():
    text = (
        "VENDOR\n"
        "05/03/2026\n"
        "TOTAL: $10.00\n"
        "TOTAL: $25.00\n"
    )
    result = extract_fields(make_ocr(text))
    assert result.amount is None
    assert any("disagree" in r for r in result.reasons)


def test_two_cent_disagreement_tolerated():
    # OCR sometimes reads $10.00 vs $10.02; that should be accepted.
    text = (
        "VENDOR\n"
        "05/03/2026\n"
        "TOTAL: $10.00\n"
        "TOTAL: $10.02\n"
    )
    result = extract_fields(make_ocr(text))
    assert result.amount is not None


# ---------------------------------------------------------------------------
# Missing fields
# ---------------------------------------------------------------------------

def test_no_date_returns_none_with_reason():
    text = "WALMART\nGRAND TOTAL $10.00\n"
    result = extract_fields(make_ocr(text))
    assert result.date is None
    assert "no date detected" in result.reasons


def test_no_amount_keyword_returns_none_with_reason():
    text = "WALMART\n05/03/2026\nThanks for shopping\n"
    result = extract_fields(make_ocr(text))
    assert result.amount is None
    assert any("no total/amount keyword" in r for r in result.reasons)


def test_no_vendor_returns_none_with_reason():
    text = "(555) 123-4567\n123 Main St\n10001\n05/03/2026\nTOTAL $10.00\n"
    result = extract_fields(make_ocr(text))
    assert result.vendor is None
    assert "no vendor detected" in result.reasons


# ---------------------------------------------------------------------------
# Vendor extraction
# ---------------------------------------------------------------------------

def test_vendor_takes_first_clean_line():
    text = (
        "WALMART\n"
        "STORE #1234\n"
        "(555) 867-5309\n"
        "05/03/2026\n"
        "TOTAL $5.00\n"
    )
    result = extract_fields(make_ocr(text))
    assert result.vendor == "WALMART"


def test_vendor_skips_address_and_phone_lines():
    text = (
        "(555) 867-5309\n"
        "TARGET\n"
        "123 Main St\n"
        "05/03/2026\n"
        "TOTAL $5.00\n"
    )
    result = extract_fields(make_ocr(text))
    assert result.vendor == "TARGET"


def test_vendor_trimmed_to_60_chars():
    long_name = "A" * 100
    text = f"{long_name}\n05/03/2026\nTOTAL $5.00\n"
    result = extract_fields(make_ocr(text))
    assert result.vendor is not None
    assert len(result.vendor) == 60


# ---------------------------------------------------------------------------
# Confidence scoring
# ---------------------------------------------------------------------------

def test_confidence_starts_at_ocr_confidence():
    text = "WALMART\n05/03/2026\nTOTAL $10.00\n"
    result = extract_fields(make_ocr(text, conf=80.0))
    assert result.confidence == 80.0


def test_confidence_penalised_for_missing_date():
    text = "WALMART\nGRAND TOTAL $10.00\n"
    result = extract_fields(make_ocr(text, conf=90.0))
    assert result.confidence == 70.0  # 90 − 20


def test_confidence_penalised_for_missing_amount():
    text = "WALMART\n05/03/2026\nThanks\n"
    result = extract_fields(make_ocr(text, conf=90.0))
    assert result.confidence == 60.0  # 90 − 30


def test_confidence_penalised_for_junk_vendor():
    # All-numeric vendor → junk
    text = "12345\n05/03/2026\nTOTAL $5.00\n"
    result = extract_fields(make_ocr(text, conf=90.0))
    assert result.confidence == 80.0  # 90 − 10


def test_confidence_floor_at_zero():
    text = "Thanks for shopping\n"
    result = extract_fields(make_ocr(text, conf=10.0))
    assert result.confidence >= 0.0


def test_returns_extracted_receipt_dataclass():
    result = extract_fields(make_ocr("VENDOR\n05/03/2026\nTOTAL $5.00"))
    assert isinstance(result, ExtractedReceipt)


# ---------------------------------------------------------------------------
# Low-resolution hint — diagnostic, not a refusal. Pipeline still runs.
# ---------------------------------------------------------------------------

def test_small_image_surfaces_low_res_reason():
    text = "VENDOR\n05/03/2026\nTOTAL $5.00\n"
    result = extract_fields(make_ocr(text, image_max_dim=200))
    assert any("image too small" in r for r in result.reasons)
    # Hint, not refusal: extraction still runs and produces fields.
    assert result.amount == Decimal("5.00")
    assert result.date == "05/03/2026"


def test_large_image_no_low_res_reason():
    text = "VENDOR\n05/03/2026\nTOTAL $5.00\n"
    result = extract_fields(make_ocr(text, image_max_dim=1200))
    assert not any("image too small" in r for r in result.reasons)


def test_unknown_dim_does_not_trigger_low_res_reason():
    # image_max_dim=0 means the caller didn't populate it; do not warn.
    text = "VENDOR\n05/03/2026\nTOTAL $5.00\n"
    result = extract_fields(make_ocr(text, image_max_dim=0))
    assert not any("image too small" in r for r in result.reasons)


def test_threshold_boundary():
    # 499 → warns, 500 → does not.
    text = "VENDOR\n05/03/2026\nTOTAL $5.00\n"
    assert any("image too small" in r for r in extract_fields(make_ocr(text, image_max_dim=499)).reasons)
    assert not any("image too small" in r for r in extract_fields(make_ocr(text, image_max_dim=500)).reasons)
