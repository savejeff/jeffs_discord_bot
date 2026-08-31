@echo off

rem Creates the project-local Python environment when needed and activates it
rem in the current Command Prompt session.

set "ACTIVATE_VENV_SCRIPT_DIR=%~dp0"
set "ACTIVATE_VENV_DIR=%~dp0.venv"
set "ACTIVATE_VENV_PYTHON=%~dp0.venv\Scripts\python.exe"
set "ACTIVATE_VENV_REQUIREMENTS=%~dp0requirements.txt"

if exist "%ACTIVATE_VENV_DIR%" if not exist "%ACTIVATE_VENV_PYTHON%" (
	echo An incomplete virtual environment exists at %ACTIVATE_VENV_DIR%. 1>&2
	echo Remove it manually and run this script again. 1>&2
	goto :error
)

if exist "%ACTIVATE_VENV_PYTHON%" goto :activate

if not exist "%ACTIVATE_VENV_REQUIREMENTS%" (
	echo Requirements file not found: %ACTIVATE_VENV_REQUIREMENTS% 1>&2
	goto :error
)

python3 --version 2>nul | findstr /b /c:"Python 3." >nul
if not errorlevel 1 goto :create_with_python3

py -3 --version 2>nul | findstr /b /c:"Python 3." >nul
if not errorlevel 1 goto :create_with_launcher

python --version 2>nul | findstr /b /c:"Python 3." >nul
if not errorlevel 1 goto :create_with_python

echo Python 3 was not found. Install it and ensure it is available on PATH. 1>&2
goto :error

:create_with_python3
echo Creating Python virtual environment in %ACTIVATE_VENV_DIR%...
python3 -m venv "%ACTIVATE_VENV_DIR%"
goto :created

:create_with_launcher
echo Creating Python virtual environment in %ACTIVATE_VENV_DIR%...
py -3 -m venv "%ACTIVATE_VENV_DIR%"
goto :created

:create_with_python
echo Creating Python virtual environment in %ACTIVATE_VENV_DIR%...
python -m venv "%ACTIVATE_VENV_DIR%"

:created
if errorlevel 1 (
	echo Python failed to create the virtual environment. 1>&2
	goto :error
)

echo Installing packages from %ACTIVATE_VENV_REQUIREMENTS%...
"%ACTIVATE_VENV_PYTHON%" -m pip install -r "%ACTIVATE_VENV_REQUIREMENTS%"
if errorlevel 1 (
	echo Python failed to install the required packages. 1>&2
	goto :error
)

:activate
call "%ACTIVATE_VENV_DIR%\Scripts\activate.bat"
echo Activated Python virtual environment: %VIRTUAL_ENV%
set "ACTIVATE_VENV_SCRIPT_DIR="
set "ACTIVATE_VENV_DIR="
set "ACTIVATE_VENV_PYTHON="
set "ACTIVATE_VENV_REQUIREMENTS="
exit /b 0

:error
set "ACTIVATE_VENV_SCRIPT_DIR="
set "ACTIVATE_VENV_DIR="
set "ACTIVATE_VENV_PYTHON="
set "ACTIVATE_VENV_REQUIREMENTS="
exit /b 1
