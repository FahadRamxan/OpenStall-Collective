@echo off
rem Test mode for recording the video's clips: a fresh demo world in video\test-mode.db, the API on port 8000.
for %%I in ("%~dp0..") do set "KIT=%%~fI"
set "KIT_FWD=%KIT:\=/%"
cd /d "%KIT%\.."
set OPENSTALL_MODE=fake
set OPENSTALL_IGNORE_DOTENV=1
set PUBLIC_BASE_URL=http://localhost:8000
set WEB_BASE_URL=http://localhost:3000
set "DATABASE_URL=sqlite:///%KIT_FWD%/test-mode.db"
set "MEDIA_DIR=%KIT%\test-mode-media"
".venv\Scripts\python.exe" scripts\seed_demo.py --reset --demo-order
".venv\Scripts\python.exe" -m uvicorn openstall_api.main:app --host 127.0.0.1 --port 8000 --log-level warning
