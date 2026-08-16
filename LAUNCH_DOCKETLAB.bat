@echo off
title NEATLABS DOCKETLAB
cd /d "%~dp0"

REM  NEATLABS(TM) DOCKETLAB  -  neatlabs.ai  -  info@neatlabs.ai
REM  Apache-2.0  -  github.com/neatlabs-ai/docketlab

REM ---- keys (or set them on the Settings tab, which is easier) ----------
REM  free regulations.gov key: https://api.data.gov/signup/
REM set DL_REGS_KEY=...
REM set ANTHROPIC_API_KEY=sk-ant-...

REM ---- where data lives (survives reinstalls and git pulls) -------------
if "%DL_HOME%"=="" set DL_HOME=%USERPROFILE%\DOCKETLAB_DATA

REM ---- port (change if Windows has reserved 7910) ----------------------
if "%DL_PORT%"=="" set DL_PORT=7910

REM Pick an interpreter ONCE, up front. Retrying a failed run with a
REM different launcher buries the real error under an unrelated one.
set PYEXE=
python -c "import sys" >nul 2>&1 && set PYEXE=python
if "%PYEXE%"=="" (
  py -3 -c "import sys" >nul 2>&1 && set PYEXE=py -3
)
if "%PYEXE%"=="" (
  echo.
  echo No working Python found on PATH.
  echo Install Python 3.11 or newer from python.org, ticking "Add to PATH".
  echo.
  pause
  exit /b 1
)

%PYEXE% -m docketlab serve
if errorlevel 1 (
  echo.
  echo DOCKETLAB exited with an error. Common causes:
  echo   First run              pip install -r requirements.txt
  echo   Already running        close the other DOCKETLAB window
  echo   Port 7910 reserved     set DL_PORT=7911 and try again
  echo.
  pause
)
