@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo  ShowRunDoc ^| PyInstaller build
echo ============================================================
echo.

REM ── 1. Check / create venv ───────────────────────────────────────────────
echo [1/3] Checking virtual environment...
if not exist ".venv\Scripts\python.exe" (
    echo Virtual environment not found. Creating...
    python -m venv .venv
    if errorlevel 1 (
        echo ERROR: Failed to create virtual environment. Exiting.
        exit /b 1
    )
    echo Installing dependencies...
    .venv\Scripts\pip install -r requirements.txt
    if errorlevel 1 (
        echo ERROR: pip install failed. Exiting.
        exit /b 1
    )
) else (
    echo       OK.
)
echo.

REM ── 2. Clean previous build ───────────────────────────────────────────────
echo [2/3] Building ShowRunDoc.exe...
if exist "dist\ShowRunDoc.exe" del /q "dist\ShowRunDoc.exe"

if exist "showrun.ico" (
    set ICO=--icon="showrun.ico"
) else (
    set ICO=
)

.venv\Scripts\pyinstaller ^
    --onefile ^
    --windowed ^
    --name "ShowRunDoc" ^
    %ICO% ^
    --hidden-import="docx" ^
    --hidden-import="docx.oxml" ^
    --hidden-import="docx.oxml.ns" ^
    --hidden-import="lxml" ^
    --hidden-import="lxml.etree" ^
    --collect-all="docx" ^
    main.py

echo.

REM ── 3. Result ─────────────────────────────────────────────────────────────
echo [3/3] Checking result...
if exist "dist\ShowRunDoc.exe" (
    echo.
    echo  SUCCESS: dist\ShowRunDoc.exe created.
    for %%F in ("dist\ShowRunDoc.exe") do echo  Size   : %%~zF bytes
    echo.
    echo  Run: dist\ShowRunDoc.exe
) else (
    echo  FAILED: dist\ShowRunDoc.exe not found.
    echo  Check the output above for errors.
    exit /b 1
)

endlocal
pause
