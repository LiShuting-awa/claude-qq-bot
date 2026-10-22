@echo off
cd /d "%~dp0"
set PYTHONUTF8=1
if not exist ".venv\Scripts\python.exe" (
    echo [setup] creating virtual environment...
    python -m venv .venv
    if errorlevel 1 goto :error
    .venv\Scripts\python.exe -m pip install -r requirements.txt
    if errorlevel 1 goto :error
)
if not exist ".env" (
    copy /y ".env.example" ".env" >nul
    echo [setup] .env created. Fill ANTHROPIC_API_KEY then run again.
    pause
    exit /b 1
)
.venv\Scripts\python.exe bot.py
pause
exit /b 0

:error
echo [error] setup failed, check Python and network.
pause
exit /b 1
