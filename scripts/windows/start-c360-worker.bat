@echo off
setlocal

chcp 65001 >nul

set "RPA_WORKDIR=C:\rpa_work\RPA_GROUP"
if not "%~1"=="" set "RPA_WORKDIR=%~1"

if not exist "%RPA_WORKDIR%\" (
  echo [ERROR] RPA workdir not found: %RPA_WORKDIR%
  exit /b 1
)

if not exist "%RPA_WORKDIR%\.local\rpa-worker-env.ps1" (
  echo [ERROR] Missing env file: %RPA_WORKDIR%\.local\rpa-worker-env.ps1
  echo Create the local env file first, then start the worker again.
  exit /b 1
)

cd /d "%RPA_WORKDIR%" || exit /b 1

echo [INFO] Starting CSM C360 RPA worker from %CD%
echo [INFO] Press Ctrl+C in this window to stop the worker.

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -NoExit -Command "$ErrorActionPreference = 'Stop'; Set-Location -LiteralPath '%RPA_WORKDIR%'; . '.\.local\rpa-worker-env.ps1'; $env:PYTHONIOENCODING = 'utf-8'; python -m rpa_platform.worker.c360_worker --verbose"
