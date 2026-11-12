@echo off
rem The web app for recording, built into apps\web\.next-video so the usual build is left alone.
cd /d "%~dp0..\..\apps\web"
set "PATH=C:\Program Files\nodejs;%PATH%"
set NEXT_DIST_DIR=.next-video
set NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
set NEXT_TELEMETRY_DISABLED=1
call npm run build
call npm run start -- --hostname 127.0.0.1 --port 3000
