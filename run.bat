@echo off
cd /d %~dp0
if not exist .venv (
  echo Creating virtual environment...
  python -m venv .venv
)
call .venv\Scripts\activate.bat
pip install -q -r requirements.txt
echo.
echo SiteMemory running at http://localhost:8000
echo.
python backend\app.py
pause
