@echo off
echo Building network-documentr...
echo.

.venv\Scripts\python.exe -m PyInstaller --onefile --windowed --name network-documentr --icon "assets\app_icon.ico" --collect-all=docx --collect-all=tkinterdnd2 --add-data "assets;assets" main.py

if %ERRORLEVEL% == 0 (
    echo.
    echo Build successful^^!  Output: dist\network-documentr.exe
) else (
    echo.
    echo Build FAILED.
)

pause
