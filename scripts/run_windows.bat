@echo off
REM Receipt Fixer click-to-launch (Windows)
setlocal

set "SCRIPT_DIR=%~dp0"
pushd "%SCRIPT_DIR%.." || exit /b 1
set "REPO_ROOT=%CD%"

set "PYTHONPATH=%REPO_ROOT%\src;%REPO_ROOT%;%PYTHONPATH%"

REM 1) Prefer the project's virtualenv if present.
if exist "%REPO_ROOT%\.venv\Scripts\python.exe" (
    "%REPO_ROOT%\.venv\Scripts\python.exe" "%REPO_ROOT%\receipt_fixer_tk_launcher.py" %*
    set "RC=%ERRORLEVEL%"
    goto :end
)

REM 2) Try the official Windows launcher.
where py >nul 2>&1
if not errorlevel 1 (
    py -3 "%REPO_ROOT%\receipt_fixer_tk_launcher.py" %*
    set "RC=%ERRORLEVEL%"
    goto :end
)

REM 3) Fall back to plain python.
python "%REPO_ROOT%\receipt_fixer_tk_launcher.py" %*
set "RC=%ERRORLEVEL%"

:end
popd
endlocal & exit /b %RC%
