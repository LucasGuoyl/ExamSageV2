@echo off
setlocal
title ExamSage v2 - verification 8768
set "EXAMSAGE_CHAT_INSTANCE=verification-8768"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1" -Action serve -Port 8768 -Reload
set "EXAMSAGE_EXIT=%ERRORLEVEL%"
if not "%EXAMSAGE_EXIT%"=="0" pause
exit /b %EXAMSAGE_EXIT%
