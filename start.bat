@echo off
setlocal EnableDelayedExpansion
title Arena Code CLI
chcp 65001 >nul 2>&1
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1

pushd "%~dp0"

:: 1. Check for Python executable
set "PY_CMD="
where python >nul 2>&1
if not errorlevel 1 (
    set "PY_CMD=python"
) else (
    where py >nul 2>&1
    if not errorlevel 1 (
        set "PY_CMD=py -3"
    )
)

if "%PY_CMD%"=="" (
    echo.
    echo ========================================================
    echo  [!] Python 3 is not found in your system PATH.
    echo      Please install Python 3.10+ from https://python.org
    echo ========================================================
    echo.
    pause
    popd
    exit /b 1
)

:: 2. Launch Arena CLI
%PY_CMD% "arena-cli.py" %*
set "EXIT_CODE=%ERRORLEVEL%"

:: 3. Error trapping: keep window open if crash or error occurred
if %EXIT_CODE% neq 0 (
    echo.
    echo ========================================================
    echo  [!] Arena CLI exited with code: %EXIT_CODE%
    echo ========================================================
    echo  Press any key to close this window...
    pause >nul
)

popd
