@echo off
REM =============================================================================
REM skipper.bat — Windows batch wrapper for Skipperbot PowerShell launcher
REM =============================================================================
REM This batch file calls the PowerShell script, handling execution policy.
REM You can add this directory to your PATH to run 'skipper' from anywhere.
REM =============================================================================

setlocal enabledelayedexpansion
cd /d "%~dp0\.."

REM Get the directory where this batch file is located (should be scripts/)
set SCRIPT_DIR=%~dp0

REM Call the PowerShell script with the provided arguments
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%skipper.ps1" %*
exit /b %errorlevel%
