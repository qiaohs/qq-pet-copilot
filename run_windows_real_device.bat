@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    where py >nul 2>&1
    if errorlevel 1 goto python_missing
    py -3.12 -c "import sys; assert sys.version_info[:2] == (3, 12)" >nul 2>&1
    if errorlevel 1 goto python_missing
    py -3.12 -m venv .venv
    if errorlevel 1 goto failed
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 goto failed
)
rem 日常启动使用 pythonw 并立即释放 CMD，只在任务栏保留 GUI 窗口。
start "" ".venv\Scripts\pythonw.exe" main.py
if errorlevel 1 goto failed
exit /b 0
:python_missing
echo Python 3.12 and the Windows py launcher are required.
pause
exit /b 1
:failed
echo Startup failed. Read the error message above.
pause
exit /b 1
