# Building Receipt Fixer

End users do not run this. This document is for the operator producing
release artifacts.

---

## Prerequisites (Linux)

- Python 3.13 (or 3.12). The repo is developed against the .venv it
  ships with; recreate it if absent.
- Tesseract: `sudo apt install tesseract-ocr`
- Poppler (for PDF rasterization via `pdf2image`):
  `sudo apt install poppler-utils`
- Tk: `sudo apt install python3-tk`
- Build dependency: `pip install -r requirements-build.txt`
  (PyInstaller — kept separate from `requirements.txt` so end-user
  development setups stay lean).

Optional: `xvfb-run` (`sudo apt install xvfb`) lets the build script
smoke-test the produced binary headlessly. Without it the smoke step is
recorded as "skipped" rather than failing the build.

---

## Run the build

```
scripts/build_linux.sh
```

The script:

1. Refuses to run unless `pytest` passes.
2. Cleans previous `dist/` and `build/` artifacts.
3. Invokes PyInstaller in one-folder mode (no `--onefile`) so users get
   a transparent, inspectable bundle. The vendored `src/` directory and
   `receipt_fixer/assets/` (when present) are bundled.
4. Drops a click-to-launch shim inside the bundle:
   `dist/Receipt Fixer/Run Receipt Fixer.sh`.
5. Smoke-tests the freshly built binary.
6. Packages the bundle as `dist/Receipt Fixer Linux.tar.gz`.
7. Writes `dist/BUILD_VERIFICATION.txt` with build date, Python /
   PyInstaller versions, SHA-256 of the binary, SHA-256 of the tarball,
   and the smoke-test result.

If any step fails the script aborts with a `FAILURE FOUND` line on
stderr. No partial artifact is shipped.

---

## What gets produced

```
dist/
├── Receipt Fixer/                  ← one-folder bundle (the binary lives here)
│   ├── Receipt Fixer               ← executable
│   ├── Run Receipt Fixer.sh        ← double-click shim
│   └── _internal/                  ← PyInstaller runtime payload
├── Receipt Fixer Linux.tar.gz      ← release artifact (the tarball you ship)
└── BUILD_VERIFICATION.txt          ← provenance + hashes + smoke result
```

End users untar the archive anywhere on their machine and double-click
`Run Receipt Fixer.sh` (or invoke `./Receipt\ Fixer` directly). They
must still install Tesseract themselves; the bundled GUI surfaces an
OS-aware install hint when the binary is missing from PATH.
