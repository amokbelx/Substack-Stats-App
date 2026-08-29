@echo off
REM Double-click to refresh just the last 7 days of posts/notes/comments,
REM instead of the full historical pull. Much faster for a quick check-in.

cd /d "%~dp0"

where python >nul 2>nul
if %errorlevel%==0 (
    python "Substack App - Main.py" --recent 7
) else (
    where py >nul 2>nul
    if %errorlevel%==0 (
        py "Substack App - Main.py" --recent 7
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
