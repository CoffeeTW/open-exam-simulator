@echo off
setlocal
cd /d "%~dp0"
set LOG=build-log.txt
echo Open Exam Simulator build log > %LOG%
if not exist ".venv\Scripts\python.exe" (
  echo Run run.bat once first to create the Python environment.
  echo ERROR: .venv not found >> %LOG%
  pause
  exit /b 1
)
set PY=.venv\Scripts\python.exe

echo [1/6] Installing PyInstaller ...
echo [1/6] pip install pyinstaller >> %LOG%
"%PY%" -m pip install --upgrade "pyinstaller>=6.10" >> %LOG% 2>&1
if errorlevel 1 goto :fail

echo [2/6] Running tests ...
echo [2/6] tests >> %LOG%
set QT_QPA_PLATFORM=offscreen
set PYTHONIOENCODING=utf-8
"%PY%" -m unittest discover -s tests -t . >> %LOG% 2>&1
if errorlevel 1 goto :fail
set QT_QPA_PLATFORM=

echo [3/6] Creating icon ...
echo [3/6] icon >> %LOG%
set ICONARG=
"%PY%" tools\make_icon.py build\app.ico >> %LOG% 2>&1
if exist build\app.ico set ICONARG=--icon build\app.ico

echo [4/6] Building EXE (this takes a few minutes) ...
echo [4/6] pyinstaller >> %LOG%
if exist dist\OpenExamSimulator rmdir /s /q dist\OpenExamSimulator
"%PY%" -m PyInstaller --noconfirm --clean --windowed --name OpenExamSimulator %ICONARG% ^
  --paths . --add-data "samples;samples" ^
  --exclude-module tkinter --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtWebEngineWidgets ^
  --exclude-module PySide6.Qt3DCore --exclude-module PySide6.QtQuick --exclude-module PySide6.QtQml ^
  --exclude-module PySide6.QtMultimedia --exclude-module PySide6.QtPdf ^
  launcher.py >> %LOG% 2>&1
if errorlevel 1 goto :fail
if not exist dist\OpenExamSimulator\OpenExamSimulator.exe goto :fail

echo [5/6] Self-test of the EXE ...
echo [5/6] self-test >> %LOG%
if exist dist\selftest.txt del dist\selftest.txt
start "" /wait dist\OpenExamSimulator\OpenExamSimulator.exe --self-test "%CD%\dist\selftest.txt"
set SELFTEST=%errorlevel%
if exist dist\selftest.txt type dist\selftest.txt >> %LOG%
if not "%SELFTEST%"=="0" goto :fail

echo [6/6] Creating zip ...
echo [6/6] zip >> %LOG%
copy /y README.md dist\OpenExamSimulator\ >nul
copy /y LICENSE dist\OpenExamSimulator\LICENSE.txt >nul
copy /y THIRD_PARTY_NOTICES.md dist\OpenExamSimulator\ >nul
copy /y CHANGELOG.md dist\OpenExamSimulator\ >nul
if exist dist\OpenExamSimulator-win64.zip del dist\OpenExamSimulator-win64.zip
powershell -NoProfile -Command "Compress-Archive -Path 'dist\OpenExamSimulator' -DestinationPath 'dist\OpenExamSimulator-win64.zip' -Force" >> %LOG% 2>&1

echo BUILD OK >> %LOG%
echo.
echo Done. Program: dist\OpenExamSimulator\OpenExamSimulator.exe
echo       Zip:     dist\OpenExamSimulator-win64.zip
pause
exit /b 0

:fail
echo BUILD FAILED >> %LOG%
echo.
echo Build failed. See build-log.txt for details.
pause
exit /b 1
