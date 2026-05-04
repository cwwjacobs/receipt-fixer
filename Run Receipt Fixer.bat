@echo off
REM Click-to-launch shim — defers to scripts\run_windows.bat
call "%~dp0scripts\run_windows.bat" %*
exit /b %ERRORLEVEL%
