@echo off
chcp 65001 >nul
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-windows.ps1" %*
if errorlevel 1 (
  echo.
  echo 启动失败，请查看上面的错误信息。
  pause
)
endlocal
