@echo off
title Arena Code CLI
chcp 65001 >nul 2>&1
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
python "%~dp0arena-cli.py" %*
if %errorlevel% neq 0 (
    echo.
    echo Press any key to close...
    pause >nul
)
