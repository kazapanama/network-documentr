@echo off
echo Building network-documentr...
echo.

.venv\Scripts\python.exe -m PyInstaller --onefile --windowed --name network-documentr --collect-all=docx main.py

if %ERRORLEVEL% == 0 (
    echo.
    echo Build successful^^!  Output: dist\network-documentr.exe
) else (
    echo.
    echo Build FAILED.
)

pause
