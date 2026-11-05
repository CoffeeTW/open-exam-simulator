@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run run.bat once first to install PySide6.
  pause
  exit /b 1
)
set QT_QPA_PLATFORM=offscreen
set PYTHONIOENCODING=utf-8
".venv\Scripts\python.exe" -m unittest discover -s tests -t . -v > test-results.txt 2>&1
set RESULT=%errorlevel%
type test-results.txt
echo.
echo Exit code: %RESULT%  (results saved to test-results.txt)
pause
