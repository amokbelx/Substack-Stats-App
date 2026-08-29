@echo off
REM Double-click this ONCE to start the local dashboard server, then
REM leave this window open in the background. After that, everything
REM happens in your browser at http://localhost:8765/dashboard.html
REM Bookmark that URL - that's the one to use from now on.

cd /d "%~dp0"

where python >nul 2>nul
if %errorlevel%==0 (
    python "Substack App - Local Server.py"
) else (
    where py >nul 2>nul
    if %errorlevel%==0 (
        py "Substack App - Local Server.py"
    ) else (
        echo ERROR: Could not find "python" or "py" on your PATH.
        echo.
        echo Fix: install Python from python.org, making sure to check
        echo "Add python.exe to PATH" during install, then try again.
        pause
    )
)
