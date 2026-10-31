@echo off
title J.A.R.V.I.S.
cd /d "%~dp0"
if not exist "runtime\python.exe" (
  echo JARVIS runtime not found. Run setup.ps1 first.
  pause
  exit /b 1
)
runtime\python.exe app.py --window
if errorlevel 1 (
  echo.
  echo JARVIS exited. Press any key to close.
  pause >nul
)
