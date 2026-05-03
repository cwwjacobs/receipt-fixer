# Tesseract OCR Setup (Windows)

Receipt Fixer uses Tesseract OCR to read text from receipt images. You must
install the Tesseract binary separately — it is not bundled with the Python
package.

## Install

1. Download the installer from the UB-Mannheim builds:
   https://github.com/UB-Mannheim/tesseract/wiki

   Recommended: `tesseract-ocr-w64-setup-5.x.x.exe` (64-bit)

2. Run the installer. The default path is:
   `C:\Program Files\Tesseract-OCR\`

3. Add Tesseract to your PATH:
   - Open **System Properties → Environment Variables**
   - Under **System variables**, select **Path** and click **Edit**
   - Add: `C:\Program Files\Tesseract-OCR`

4. Open a new terminal and verify:
   ```
   tesseract --version
   ```
   You should see `tesseract 5.x.x` or similar.

## Bundled distribution (PyInstaller)

When Receipt Fixer is distributed as a `.exe`, the Tesseract binary and its
language data are bundled automatically. End users do not need to install
Tesseract manually.

## Language data

The default install includes English (`eng`). Receipt Fixer v0 uses English
only. If you need other languages, select them during the Tesseract install
wizard under "Additional language data."
