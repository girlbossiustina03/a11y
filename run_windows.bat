@echo off
rem Launch the A11y desktop companion natively on Windows.
rem Double-click this file, or run: run_windows.bat [--panel] [--admin]
setlocal EnableExtensions EnableDelayedExpansion

rem Windows-side virtual environment, kept on the local disk (faster than the WSL share).
set "VENV=%USERPROFILE%\.venvs\a11y"

rem Keep the SQLite data on the local disk; SQLite locking is unreliable on network shares such as \\wsl.localhost.
if not defined A11Y_DATA_DIR set "A11Y_DATA_DIR=%LOCALAPPDATA%\A11y"

rem pushd also works for UNC paths: it maps a temporary drive letter.
pushd "%~dp0"

if not exist "%VENV%\Scripts\python.exe" (
    echo Creating the Python environment in %VENV% ...
    set "PY_CMD="
    py -3 --version >nul 2>&1 && set "PY_CMD=py -3"
    if not defined PY_CMD (
        python --version >nul 2>&1 && set "PY_CMD=python"
    )
    if not defined PY_CMD (
        if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
            set "PY_CMD="%LOCALAPPDATA%\Programs\Python\Python312\python.exe""
        )
    )
    if not defined PY_CMD goto :no_python
    !PY_CMD! -m venv "%VENV%" || goto :no_python
    "%VENV%\Scripts\python.exe" -m pip install -r requirements.txt || goto :failed
)

rem Optional voice support ("Hey Ally"); the app still works if this step fails.
"%VENV%\Scripts\python.exe" -c "import faster_whisper, kokoro_onnx" >nul 2>&1 || (
    echo Installing voice support...
    "%VENV%\Scripts\python.exe" -m pip install -r requirements-voice.txt
)

"%VENV%\Scripts\python.exe" a11y_desktop.py %*
set "CODE=%ERRORLEVEL%"
popd
exit /b %CODE%

:no_python
echo Python 3.10+ for Windows is required. Install it with: winget install Python.Python.3.12
goto :failed

:failed
popd
pause
exit /b 1
