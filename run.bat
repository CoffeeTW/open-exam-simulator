@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [Open Exam Simulator] First run: creating virtual environment and installing PySide6 ...
  py -3 -m venv .venv 2>nul || python -m venv .venv
  if not exist ".venv\Scripts\python.exe" (
    echo Python 3.10 or later was not found. Install it from https://www.python.org/downloads/ and run again.
    pause
    exit /b 1
  )
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 (
    echo Failed to install PySide6. Check the network connection, delete the .venv folder and run again.
    rmdir /s /q .venv
    pause
    exit /b 1
  )
)
start "" ".venv\Scripts\pythonw.exe" -m oes %*
