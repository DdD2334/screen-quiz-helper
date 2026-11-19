@echo off
REM ============================================================
REM  start.bat — one-click launcher for screen-quiz-helper
REM  用法：双击运行；传 --nopause 可跳过结尾暂停
REM ============================================================
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] python not found on PATH.
    pause
    exit /b 1
)

echo [start] launching screen-quiz-helper ...
python main.py
set EXIT_CODE=%ERRORLEVEL%

if not "%EXIT_CODE%"=="0" (
    echo.
    echo [exit] code=%EXIT_CODE%  详细报错见 logs\app.log
)
if not "%~1"=="--nopause" pause
endlocal & exit /b %EXIT_CODE%