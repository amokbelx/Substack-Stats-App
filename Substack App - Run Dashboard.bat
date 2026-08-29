@echo off
REM Double-click this to pull fresh Substack stats and open the
REM dashboard, without needing to open a terminal yourself.

cd /d "%~dp0"

where python >nul 2>nul
if %errorlevel%==0 (
    python "Substack App - Main.py"
) else (
    where py >nul 2>nul
    if %errorlevel%==0 (
        py "Substack App - Main.py"
    ) else (
        echo ERROR: Could not find "python" or "py" on your PATH.
        echo.
        echo Fix: install Python from python.org, making sure to check
        echo "Add python.exe to PATH" during install, then try again.
    )
)

echo.
echo ============================================
echo Done. Press any key to close this window.
echo ============================================
pause >nul
