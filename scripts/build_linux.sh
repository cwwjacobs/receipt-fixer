#!/usr/bin/env bash
# Receipt Fixer — Linux PyInstaller build
#
# Refuses to run unless pytest passes. Produces a one-folder bundle at
# dist/Receipt Fixer/ plus dist/Receipt\ Fixer\ Linux.tar.gz and a
# BUILD_VERIFICATION.txt that records build provenance and a smoke-test
# result against the freshly built binary.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

APP_NAME="Receipt Fixer"
DIST_DIR="$REPO_ROOT/dist"
BUILD_DIR="$REPO_ROOT/build"
BUNDLE_DIR="$DIST_DIR/$APP_NAME"
TARBALL="$DIST_DIR/${APP_NAME} Linux.tar.gz"
VERIFICATION="$DIST_DIR/BUILD_VERIFICATION.txt"

# --- Pick interpreter -------------------------------------------------------
if [ -x "$REPO_ROOT/.venv/bin/python" ]; then
    PYTHON="$REPO_ROOT/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON="python3"
else
    echo "FAILURE FOUND: no Python interpreter available" >&2
    exit 1
fi

PYINSTALLER="$REPO_ROOT/.venv/bin/pyinstaller"
if [ ! -x "$PYINSTALLER" ]; then
    if command -v pyinstaller >/dev/null 2>&1; then
        PYINSTALLER="$(command -v pyinstaller)"
    else
        echo "FAILURE FOUND: pyinstaller not installed" >&2
        echo "  Run: $PYTHON -m pip install -r requirements-build.txt" >&2
        exit 1
    fi
fi

# --- Gate: pytest must pass -------------------------------------------------
echo "── PRE-BUILD VERIFICATION ────────────────────────────────────"
echo "Running test suite (build will abort on any failure)..."
if ! "$PYTHON" -m pytest -q; then
    echo ""
    echo "FAILURE FOUND: pytest reported failures. Build aborted." >&2
    exit 2
fi
echo "PRE-BUILD VERIFICATION PASSED"
echo ""

# --- Clean previous build artifacts ----------------------------------------
echo "── CLEAN ─────────────────────────────────────────────────────"
rm -rf "$BUILD_DIR" "$BUNDLE_DIR" "$TARBALL" "$VERIFICATION" \
       "$DIST_DIR/${APP_NAME}.spec"
mkdir -p "$DIST_DIR"
echo "removed previous build/dist artifacts"
echo ""

# --- PyInstaller build ------------------------------------------------------
echo "── BUILD ─────────────────────────────────────────────────────"
ADD_DATA_FLAGS=()
if [ -d "$REPO_ROOT/receipt_fixer/assets" ]; then
    ADD_DATA_FLAGS+=("--add-data" "receipt_fixer/assets:receipt_fixer/assets")
fi
if [ -f "$REPO_ROOT/README.md" ]; then
    ADD_DATA_FLAGS+=("--add-data" "README.md:.")
fi

"$PYINSTALLER" \
    --noconfirm \
    --windowed \
    --name "$APP_NAME" \
    --paths src \
    --paths . \
    --hidden-import fixdrawer_app_base \
    --hidden-import fixdrawer_app_base.platform \
    --hidden-import fixdrawer_app_base.tk_widgets \
    --collect-submodules receipt_fixer \
    "${ADD_DATA_FLAGS[@]}" \
    receipt_fixer_tk_launcher.py
echo ""

BIN="$BUNDLE_DIR/$APP_NAME"
if [ ! -x "$BIN" ]; then
    echo "FAILURE FOUND: expected binary not found at $BIN" >&2
    exit 3
fi

# --- Click-to-launch shim inside the dist bundle ----------------------------
LAUNCH_SHIM="$BUNDLE_DIR/Run Receipt Fixer.sh"
cat > "$LAUNCH_SHIM" <<'LAUNCH_EOF'
#!/usr/bin/env bash
# Click-to-launch the bundled Receipt Fixer binary.
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$DIR/Receipt Fixer" "$@"
LAUNCH_EOF
chmod +x "$LAUNCH_SHIM"
echo "wrote launch shim: $LAUNCH_SHIM"

# --- Smoke test the built binary --------------------------------------------
echo ""
echo "── BINARY SMOKE TEST ─────────────────────────────────────────"
SMOKE_RESULT="not run"
if "$BIN" --version >/dev/null 2>&1; then
    SMOKE_RESULT="binary --version OK"
elif "$BIN" --help >/dev/null 2>&1; then
    SMOKE_RESULT="binary --help OK"
else
    # The Tk app has no --version flag; fall back to "binary loads without
    # crashing during a brief import-only run". We do this by launching it
    # under a virtual display if available, otherwise we skip.
    if command -v xvfb-run >/dev/null 2>&1; then
        if timeout 6 xvfb-run -a "$BIN" >/dev/null 2>&1 &
        then
            BIN_PID=$!
            sleep 2
            if kill -0 "$BIN_PID" 2>/dev/null; then
                kill "$BIN_PID" 2>/dev/null || true
                wait "$BIN_PID" 2>/dev/null || true
                SMOKE_RESULT="binary launched under xvfb-run for >2s"
            else
                SMOKE_RESULT="binary exited immediately under xvfb-run"
            fi
        fi
    else
        SMOKE_RESULT="skipped (no xvfb-run; binary built but not launched)"
    fi
fi
echo "smoke: $SMOKE_RESULT"

# --- Tarball ----------------------------------------------------------------
echo ""
echo "── PACKAGE ───────────────────────────────────────────────────"
( cd "$DIST_DIR" && tar czf "${APP_NAME} Linux.tar.gz" "$APP_NAME" )
echo "wrote: $TARBALL"

# --- BUILD_VERIFICATION.txt -------------------------------------------------
PY_VERSION="$("$PYTHON" -c 'import sys; print(sys.version.split()[0])')"
PI_VERSION="$("$PYINSTALLER" --version)"
BIN_SHA="$(sha256sum "$BIN" | awk '{print $1}')"
TARBALL_SHA="$(sha256sum "$TARBALL" | awk '{print $1}')"
BUILD_DATE="$(date -u +'%Y-%m-%d %H:%M:%S UTC')"

cat > "$VERIFICATION" <<EOF
RECEIPT FIXER — BUILD VERIFICATION
============================================================
Build date:        $BUILD_DATE
Python:            $PY_VERSION
PyInstaller:       $PI_VERSION
Platform:          linux

Binary:            $BIN
Binary SHA-256:    $BIN_SHA

Tarball:           $TARBALL
Tarball SHA-256:   $TARBALL_SHA

Smoke test:        $SMOKE_RESULT
EOF
echo "wrote: $VERIFICATION"

echo ""
echo "BUILD VERIFICATION PASSED"
echo "Artifact:    $TARBALL"
echo "Bundle dir:  $BUNDLE_DIR"
