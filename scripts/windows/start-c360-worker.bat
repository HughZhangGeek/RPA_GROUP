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

powershell.exe -NoLogo -ExecutionPolicy Bypass -NoExit -File "%~dp0start-c360-worker.ps1" -WorkDir "%RPA_WORKDIR%"
