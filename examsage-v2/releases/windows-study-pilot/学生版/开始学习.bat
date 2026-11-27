@echo off
setlocal DisableDelayedExpansion
set "runtime=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%runtime%" goto ready
echo Codex desktop Python runtime was not found.
echo Open the included student guide for requirements.
pause
exit /b 1
:ready
"%runtime%" -I -B -X utf8 "%~dp0kit.py" study
set "result=%errorlevel%"
pause
exit /b %result%
