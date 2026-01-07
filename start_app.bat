@echo off
echo Starting Video Rendering API...
set PATH=C:\dake\tools\ffmpeg-8.0.1-essentials_build\bin;%PATH%
cd /d C:\dake
uvicorn app.api.main:app --reload --port 8888
