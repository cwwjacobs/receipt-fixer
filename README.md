# Receipt Fixer

A local Windows desktop tool that converts a folder of receipt images and PDFs into a verified CSV — no cloud, no subscription, no nonsense.

Part of the [FixDrawer.shop](https://fixdrawer.shop) product line.

---

## What it does

- Accepts a folder of receipt images (JPG, PNG, HEIC) and PDFs
- Runs OCR locally using Tesseract
- Extracts: Date, Vendor, Amount, SourceFile, Confidence
- Writes a CSV you can open in Excel or import into accounting software
- Writes a verification receipt (plain-text log) next to the output so you can audit every decision
- Flags low-confidence extractions rather than silently guessing
- Runs 100% on your machine — nothing leaves your computer

---

## What it does NOT do

- **No cloud.** All processing is local. No files are uploaded anywhere.
- **No AI.** Uses rule-based OCR parsing, not a language model.
- **No categorization.** It does not tag receipts as "meals" or "travel" etc.
- **No tax advice.** It extracts data; you decide what's deductible.
- **No multi-currency.** USD only in v0.
- **No line-item parsing.** One row per receipt: total amount only.
- **No guessing.** If a field cannot be extracted with sufficient confidence, it is left blank and flagged — never fabricated.

---

## Supported v0 path

```
receipts_in/   (folder of images/PDFs)
      |
      v
  Receipt Fixer
      |
      v
receipts_out/output.csv
receipts_out/output_verification.txt
```

**Output CSV columns:**

| Column | Description |
|---|---|
| Date | Date on the receipt (YYYY-MM-DD) |
| Vendor | Merchant name |
| Amount | Total charged (USD) |
| SourceFile | Original filename |
| Confidence | LOW / MEDIUM / HIGH per row |

---

## Requirements

- Windows 10 or 11
- Tesseract OCR installed (download from [UB Mannheim](https://github.com/UB-Mannheim/tesseract/wiki))
- Python 3.13+ (for development builds)

---

## Development setup

```
pip install -r requirements.txt
python cli_smoke.py
pytest
```
