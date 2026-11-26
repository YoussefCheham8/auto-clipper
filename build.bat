@echo off
setlocal
cd /d "%~dp0"

echo [1/2] Installing dependencies...
python -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto :fail

echo [2/2] Building Auto-Clipper.exe...
python -m PyInstaller --noconfirm --clean Auto-Clipper.spec
if errorlevel 1 goto :fail

echo.
echo Done: %~dp0dist\Auto-Clipper.exe
exit /b 0

:fail
echo.
echo Build failed.
exit /b 1
