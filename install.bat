@echo off
REM Keys.ai one-command installer for Windows (double-click me).
REM Runs the bootstrap with whatever Python is on PATH.
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 install.py %*
) else (
    python install.py %*
)
if %errorlevel% neq 0 (
    echo.
    echo Install finished with errors - read the messages above.
    pause
)
