@echo off
echo Starting Celery worker...
set PATH=C:\dake\tools\ffmpeg-8.0.1-essentials_build\bin;%PATH%
cd /d C:\dake
celery -A app.rendering.celery_app worker --loglevel=info --pool=solo
