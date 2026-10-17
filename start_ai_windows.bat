@echo off
setlocal
cd /d "%~dp0"
set "PWSH=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if not exist "%PWSH%" (
  echo ERROR: Windows PowerShell could not be found.
  echo Please check Windows PowerShell availability.
  pause
  exit /b 1
)
"%PWSH%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_ai_windows.ps1"
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" (
  echo.
  echo AI launcher exited with an error. Review the message above.
)
echo.
pause
exit /b %RESULT%
