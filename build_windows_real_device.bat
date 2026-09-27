@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>&1
if errorlevel 1 goto python_missing
py -3.12 -c "import sys; assert sys.version_info[:2] == (3, 12)" >nul 2>&1
if errorlevel 1 goto python_missing
if not exist ".venv\Scripts\python.exe" (
    py -3.12 -m venv .venv
    if errorlevel 1 goto failed
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
".venv\Scripts\python.exe" build.py
if errorlevel 1 goto failed
if not exist "dist\QQPetCopilot.exe" goto failed
echo.
echo Build succeeded: %CD%\dist\QQPetCopilot.exe
explorer "dist"
pause
exit /b 0
:python_missing
echo Python 3.12 and the Windows py launcher are required.
echo Install Python 3.12, then run this file again.
pause
exit /b 1
:failed
echo Build failed. Read the error message above.
pause
exit /b 1
