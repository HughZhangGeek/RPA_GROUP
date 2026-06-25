@echo off
setlocal

if /I "%SESSIONNAME%"=="Console" (
  echo [INFO] Current session is already Console. Nothing to detach.
  exit /b 0
)

if "%SESSIONNAME%"=="" (
  echo [ERROR] SESSIONNAME is empty. Run this script from the active RDP session.
  exit /b 1
)

echo [INFO] Detaching RDP session "%SESSIONNAME%" to console...
echo [INFO] Do not log off. This command should disconnect the RDP window and keep the desktop session alive.

"%windir%\System32\tscon.exe" "%SESSIONNAME%" /dest:console
if errorlevel 1 (
  echo [WARN] Quoted SESSIONNAME failed, retrying without quotes...
  "%windir%\System32\tscon.exe" %SESSIONNAME% /dest:console
)

if errorlevel 1 (
  echo [ERROR] Failed to detach to console. Try running this script as Administrator.
  exit /b 1
)
