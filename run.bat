@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PY="

if exist ".venv\Scripts\python.exe" (
  set "PY=.venv\Scripts\python.exe"
)

if not defined PY (
  python -c "import flask, pandas, matplotlib" >nul 2>nul
  if not errorlevel 1 set "PY=python"
)

if not defined PY (
  if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" (
    set "PY=%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
  )
)

if not defined PY (
  python --version >nul 2>nul
  if not errorlevel 1 set "PY=python"
)

if not defined PY (
  echo.
  echo [错误] 没有找到可用的 Python。
  echo 请安装 Python 3.10+，或先执行：
  echo     python -m venv .venv
  echo     .venv\Scripts\pip install -r requirements.txt
  echo.
  pause
  exit /b 1
)

echo 正在启动「数据洞察」...
"%PY%" app.py --open %*
if errorlevel 1 pause
