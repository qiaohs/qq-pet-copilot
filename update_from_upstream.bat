@echo off
setlocal
cd /d "%~dp0"
git diff --quiet
if errorlevel 1 goto uncommitted
git diff --cached --quiet
if errorlevel 1 goto uncommitted
git remote get-url upstream >nul 2>&1
if errorlevel 1 (
    git remote add upstream https://github.com/490720818/qq-pet-copilot.git
    git remote set-url --push upstream no_push://upstream-read-only
)
git fetch upstream main
if errorlevel 1 goto failed
git merge --no-edit upstream/main
if errorlevel 1 goto conflict
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 echo Dependencies were not updated. Run run_windows_real_device.bat after installing Python.
git push origin main
if errorlevel 1 goto failed
echo Upstream changes merged into your fork.
pause
exit /b 0
:uncommitted
echo You have local uncommitted changes. Commit or stash them before updating.
pause
exit /b 1
:conflict
echo Merge conflict: your custom changes remain intact. Ask Codex to resolve it.
echo Do not run the update script again until the conflict is resolved.
pause
exit /b 1
:failed
echo Update failed. Read the error message above. No force push was used.
pause
exit /b 1
