@echo off
setlocal
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1" -Action student
set "studentExitCode=%errorlevel%"
if not "%studentExitCode%"=="0" pause
exit /b %studentExitCode%
