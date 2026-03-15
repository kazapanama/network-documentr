@echo off
echo Building ShowRunDoc...
echo.

.venv\Scripts\python.exe -m PyInstaller --onefile --windowed --name ShowRunDoc --collect-all=docx main.py

if %ERRORLEVEL% == 0 (
    echo.
    echo Build successful^^!  Output: dist\ShowRunDoc.exe
) else (
    echo.
    echo Build FAILED.
)

pause
