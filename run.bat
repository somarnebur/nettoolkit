@echo off
setlocal

pushd "%~dp0" >nul

set "VENV_PY=.venv\Scripts\python.exe"
set "VENV_PYW=.venv\Scripts\pythonw.exe"

echo Loading pre-requisites...

if not exist "%VENV_PY%" (
	python -m venv .venv >nul 2>nul
	if errorlevel 1 goto :error
)

"%VENV_PY%" -m pip install -q --disable-pip-version-check -r requirements.txt >nul 2>nul
if errorlevel 1 goto :error

echo Starting NetToolkit...
start "" "%VENV_PYW%" "%CD%\run_gui.pyw" %*

popd >nul
exit /b 0

:error
echo.
echo NetToolkit could not start. Please check the error above.
echo.
pause
popd >nul
exit /b 1
