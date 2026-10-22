@echo off
rem Start Spend Gate.bat
rem Double-click to set up and open the AI Agent Spend Gate app on Windows.
rem
rem It only finds Python and runs start.py, which does the real setup
rem (packages, LLM, Decider 2B). A .bat file isn't blocked by PowerShell's
rem script policy, so no Set-ExecutionPolicy is needed.
title AI Agent Spend Gate
cd /d "%~dp0"

rem Find Python: the "py" launcher first, then "python".
set "PYTHON="
py -3 --version >nul 2>&1 && set "PYTHON=py -3"
if not defined PYTHON (
    python --version >nul 2>&1 && set "PYTHON=python"
)
if not defined PYTHON (
    echo Python 3.10 or newer is needed, and it wasn't found.
    echo Download it from https://www.python.org/downloads/
    echo During the install, tick "Add python.exe to PATH". Then double-click this file again.
    echo.
    pause
    exit /b 1
)

%PYTHON% start.py %*

rem Keep the window open if something went wrong, so the message stays readable.
if errorlevel 1 (
    echo.
    echo The app stopped. The message above says what to do next.
    pause
)
