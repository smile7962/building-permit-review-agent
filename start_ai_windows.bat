@echo off
chcp 65001 >nul
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_ai_windows.ps1"
if errorlevel 1 (
  echo.
  echo AI 실행 중 오류가 발생했습니다. 위 메시지를 확인하세요.
)
pause
