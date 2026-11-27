@echo off
setlocal DisableDelayedExpansion
chcp 65001 >nul
set "studyDir=%~dp0examsage-v2\releases\windows-study-pilot\学生版"
if not exist "%studyDir%\Start ExamSage.bat" goto missing
call "%studyDir%\Start ExamSage.bat"
exit /b %errorlevel%
:missing
echo Cannot find the student kit. Extract the full repository, then open Start ExamSage.bat again.
pause
exit /b 1
