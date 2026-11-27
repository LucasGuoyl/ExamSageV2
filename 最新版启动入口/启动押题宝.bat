@echo off
setlocal DisableDelayedExpansion
chcp 65001 >nul
set "studyDir=%~dp0..\examsage-v2\releases\windows-study-pilot\学生版"
if not exist "%studyDir%\开始学习.bat" goto missing
pushd "%studyDir%" || goto missing
call ".\开始学习.bat"
set "studyExit=%errorlevel%"
popd
exit /b %studyExit%

:missing
echo 找不到押题宝学生版。请把“最新版启动入口”和“examsage-v2”放在同一个项目目录下。
pause
exit /b 1
