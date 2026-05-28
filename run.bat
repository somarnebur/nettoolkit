@echo off
setlocal

pushd "%~dp0" >nul

set "VENV_PY=.venv\Scripts\python.exe"
set "VENV_PYW=.venv\Scripts\pythonw.exe"

if not exist "%VENV_PY%" (
	echo Creating Python virtual environment...
	python -m venv .venv
	if errorlevel 1 goto :error
)

echo Installing/updating dependencies...
"%VENV_PY%" -m pip install -r requirements.txt
if errorlevel 1 goto :error

echo Starting EverflowDownload...
start "" "%VENV_PYW%" "%CD%\run_gui.pyw" %*

popd >nul
exit /b 0

:error
echo.
echo EverflowDownload could not start. Please check the error above.
echo.
pause
popd >nul
exit /b 1
