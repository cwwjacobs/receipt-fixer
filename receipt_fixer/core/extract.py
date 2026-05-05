from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date as _date
from decimal import Decimal, InvalidOperation
from typing import Optional

from receipt_fixer.core.ocr import OcrResult


@dataclass
class ExtractedReceipt:
    date: Optional[str] = None       # MM/DD/YYYY
    vendor: Optional[str] = None
    amount: Optional[Decimal] = None
    confidence: float = 0.0
    reasons: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Date extraction
# ---------------------------------------------------------------------------

_MONTHS = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}

_NUMERIC_DATE_RE = re.compile(
    r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{2}|\d{4})\b"
)
_MON_DD_YYYY_RE = re.compile(
    r"\b([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})\b"
)
_DD_MON_YYYY_RE = re.compile(
    r"\b(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})\b"
)


def _try_make_date(year: int, month: int, day: int) -> Optional[_date]:
    if year < 100:
        # 2-digit year pivot: 00–69 → 2000s, 70–99 → 1900s
        year = 2000 + year if year < 70 else 1900 + year
    try:
        return _date(year, month, day)
    except ValueError:
        return None


def _find_dates(text: str) -> list[tuple[_date, int]]:
    """Return list of (date, char_offset) tuples, in document order."""
    found: list[tuple[_date, int]] = []

    for m in _NUMERIC_DATE_RE.finditer(text):
        mm, dd, yy = int(m.group(1)), int(m.group(2)), int(m.group(3))
        d = _try_make_date(yy, mm, dd)
        if d is not None:
            found.append((d, m.start()))

    for m in _MON_DD_YYYY_RE.finditer(text):
        mon = _MONTHS.get(m.group(1).lower())
        if mon is None:
            continue
        d = _try_make_date(int(m.group(3)), mon, int(m.group(2)))
        if d is not None:
            found.append((d, m.start()))

    for m in _DD_MON_YYYY_RE.finditer(text):
        mon = _MONTHS.get(m.group(2).lower())
        if mon is None:
            continue
        d = _try_make_date(int(m.group(3)), mon, int(m.group(1)))
        if d is not None:
            found.append((d, m.start()))

    return found


def _extract_date(text: str) -> Optional[_date]:
    found = _find_dates(text)
    if not found:
        return None
    midpoint = len(text) // 2 if len(text) > 0 else 0
    top_half = [d for d, off in found if off < midpoint]
    if top_half:
        return max(top_half)
    return max(d for d, _ in found)


# ---------------------------------------------------------------------------
# Amount extraction
#
# Keyword priority (higher beats lower; ties at the same priority must agree
# within _AMOUNT_TOLERANCE or the extractor refuses):
#   4: GRAND TOTAL
#   3: TOTAL DUE, BALANCE DUE, AMOUNT DUE
#   2: FUEL TOTAL, TOTAL, BALANCE, CHARGED, AMOUNT, PAID
#   1: CREDIT, AMT, DUE
#   0 (excluded): SUBTOTAL, TAX, TIP
#
# Glyph variants: real-world OCR commonly substitutes "$" with "S", "*", "&",
# or drops it entirely. The amount regex accepts any of these as the optional
# leading currency glyph. The strict refusal logic (require cents, refuse on
# non-USD glyphs €/£/¥, refuse on disagreement) is unchanged.
# ---------------------------------------------------------------------------

_NON_USD_RE = re.compile(r"[€£¥]")

# Two accepted numeric forms:
#   1. US with thousands separator: 1,234.56  /  12,345.67  /  1,234,567.89
#   2. Plain US: 37.68  /  12345.67
# A bare "1,23" form is intentionally NOT matched — it is ambiguous between
# a typo of US thousands and European decimal convention; we refuse rather
# than guess.
_AMOUNT_RE = re.compile(
    r"(?:[\$S\*&])?\s*"
    r"(\d{1,3}(?:,\d{3})+\.\d{2}|\d{1,6}\.\d{2})"
    r"\b"
)

_EXCLUDE_RE = re.compile(r"\b(sub[\s-]?total|tax|tip)\b", re.IGNORECASE)
_GRAND_RE = re.compile(r"\bgrand\s+total\b", re.IGNORECASE)
_DUE_PHRASE_RE = re.compile(
    r"\b(total\s+due|balance\s+due|amount\s+due)\b", re.IGNORECASE
)
_LEVEL2_RE = re.compile(
    r"\b(fuel\s+total|total|balance|charged|amount|paid)\b", re.IGNORECASE
)
_LEVEL1_RE = re.compile(r"\b(credit|amt|due)\b", re.IGNORECASE)

# Disagreement tolerance: a few cents.
_AMOUNT_TOLERANCE = Decimal("0.02")


def _extract_amount(text: str) -> tuple[Optional[Decimal], list[str]]:
    if _NON_USD_RE.search(text):
        return None, ["non-USD currency detected"]

    candidates: list[tuple[int, Decimal]] = []  # (priority, value)
    for line in text.splitlines():
        # Exclusion list always wins: a line containing SUBTOTAL/TAX/TIP is
        # never used (unless it ALSO says GRAND TOTAL, which is defensive).
        if _EXCLUDE_RE.search(line) and not _GRAND_RE.search(line):
            continue

        if _GRAND_RE.search(line):
            priority = 4
        elif _DUE_PHRASE_RE.search(line):
            priority = 3
        elif _LEVEL2_RE.search(line):
            priority = 2
        elif _LEVEL1_RE.search(line):
            priority = 1
        else:
            continue

        for am in _AMOUNT_RE.finditer(line):
            try:
                value = Decimal(am.group(1).replace(",", ""))
            except InvalidOperation:
                continue
            candidates.append((priority, value))

    if not candidates:
        return None, ["no total/amount keyword found"]

    max_p = max(p for p, _ in candidates)
    top = [v for p, v in candidates if p == max_p]

    if max(top) - min(top) > _AMOUNT_TOLERANCE:
        return None, ["multiple totals disagree"]

    return top[0], []


# ---------------------------------------------------------------------------
# Vendor extraction
# ---------------------------------------------------------------------------

_PHONE_RE = re.compile(r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}")
_STORE_NUM_RE = re.compile(r"\bstore\s*#\s*\d+\b", re.IGNORECASE)
_ZIP_RE = re.compile(r"\b\d{5}(?:-\d{4})?\b")
_STREET_RE = re.compile(
    r"\b\d+\s+[A-Za-z].*?\b("
    r"st|street|ave|avenue|blvd|boulevard|rd|road|dr|drive|"
    r"ln|lane|way|hwy|highway|ct|court|pl|place"
    r")\b\.?",
    re.IGNORECASE,
)


def _looks_like_address(line: str) -> bool:
    return bool(
        _PHONE_RE.search(line)
        or _STREET_RE.search(line)
        or _ZIP_RE.search(line)
        or _STORE_NUM_RE.search(line)
    )


def _extract_vendor(text: str) -> Optional[str]:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for line in lines[:3]:
        if _looks_like_address(line):
            continue
        return line[:60]
    return None


def _vendor_looks_junky(vendor: str) -> bool:
    letters = sum(1 for c in vendor if c.isalpha())
    if letters < 3:
        return True
    if len(vendor) > 50:
        return True
    return False


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

# Below this threshold, OCR struggles regardless of content. Surface the
# image-size diagnosis as a reason so the user sees *why* fields are blank
# rather than guessing the input is unrecognizable.
_LOW_RES_THRESHOLD = 500
_LOW_RES_REASON = (
    "image too small for reliable OCR (recommend ~1000px+ on the long edge)"
)


def extract_fields(ocr_result: OcrResult) -> ExtractedReceipt:
    text = ocr_result.raw_text
    reasons: list[str] = []

    if 0 < ocr_result.image_max_dim < _LOW_RES_THRESHOLD:
        reasons.append(_LOW_RES_REASON)

    parsed_date = _extract_date(text)
    if parsed_date is None:
        date_str: Optional[str] = None
        reasons.append("no date detected")
    else:
        date_str = parsed_date.strftime("%m/%d/%Y")

    amount, amount_reasons = _extract_amount(text)
    reasons.extend(amount_reasons)

    vendor = _extract_vendor(text)
    if vendor is None:
        reasons.append("no vendor detected")

    confidence = float(ocr_result.confidence)
    if date_str is None:
        confidence -= 20
    if amount is None:
        confidence -= 30
    if vendor is not None and _vendor_looks_junky(vendor):
        confidence -= 10
        reasons.append("vendor looks like junk")

    confidence = max(0.0, min(100.0, confidence))

    return ExtractedReceipt(
        date=date_str,
        vendor=vendor,
        amount=amount,
        confidence=round(confidence, 2),
        reasons=reasons,
    )
