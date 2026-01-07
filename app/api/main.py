"""
FastAPI Application - Video Rendering Gateway.
"""
import os
import sys
import asyncio
import logging
from pathlib import Path
from contextlib import asynccontextmanager
from typing import AsyncGenerator

# CRITICAL: Fix Windows asyncio for subprocess support
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# Load environment variables from .env file FIRST
from dotenv import load_dotenv
env_path = Path(__file__).parent.parent.parent / ".env"
load_dotenv(env_path)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from app.auth import AuthMiddleware

from .routes import health_router, render_router, admin_router, clips_router, youtube_router, video_router, broll_router, god_mode_router, faceless_router, portraits_router
from .routes.musicvideo import router as musicvideo_router
from .exceptions import APIError, api_error_handler, generic_exception_handler
from app.admin_ui import admin_ui_router
from app.saas_ui import saas_ui_router  # New SaaS UI (replaces public_ui)
from app.orchestration import orchestration_router
from app.youtube_shorts import youtube_shorts_router  # YouTube Shorts module

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    """Application lifespan handler."""
    logger.info("=" * 60)
    logger.info("Starting Video Rendering API...")
    logger.info("=" * 60)

    # Load and validate configuration
    from app.config import config
    config.log_status()

    # Check Redis/Celery (optional - not required for Faceless)
    try:
        from .dependencies import check_redis_connection, check_celery_connection
        redis_ok = check_redis_connection()
        celery_ok = check_celery_connection()
        logger.info(f"Redis connected: {redis_ok}")
        logger.info(f"Celery connected: {celery_ok}")

        if not redis_ok:
            logger.warning("⚠️  Redis not available - Faceless will run directly (no Celery workers needed)")
            logger.info("✅ Faceless Engine: Direct execution mode enabled")
    except Exception as e:
        logger.warning(f"Redis/Celery check skipped: {e}")
        logger.info("✅ Faceless Engine: Direct execution mode enabled")

    logger.info("=" * 60)
    logger.info("🚀 Server ready! Faceless AI Generation available at /api/faceless/generate")
    logger.info("=" * 60)

    yield

    logger.info("Shutting down Video Rendering API...")


def create_app(
    debug: bool = False,
    require_auth: bool = True,
) -> FastAPI:
    """Create and configure FastAPI application."""
    app = FastAPI(
        title="Video Rendering API",
        description="SaaS API for AI-powered vertical video generation",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
        debug=debug,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_middleware(AuthMiddleware, require_auth=require_auth)

    app.add_exception_handler(APIError, api_error_handler)
    app.add_exception_handler(Exception, generic_exception_handler)

    app.include_router(health_router)
    app.include_router(render_router)
    app.include_router(admin_router)
    app.include_router(clips_router)
    app.include_router(youtube_router)
    app.include_router(video_router)
    app.include_router(broll_router)
    app.include_router(god_mode_router)
    app.include_router(faceless_router)  # Faceless video generation (AutoShorts clone)
    app.include_router(musicvideo_router)  # Music Video Generator
    app.include_router(portraits_router)  # AI Portraits with templates
    app.include_router(admin_ui_router)
    app.include_router(saas_ui_router)  # New SaaS UI (replaces old public_ui)
    app.include_router(orchestration_router)
    app.include_router(youtube_shorts_router)  # YouTube Shorts module

    # Mount static files for generated content (images, videos)
    data_dir = Path(__file__).parent.parent.parent / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/data", StaticFiles(directory=str(data_dir)), name="data")

    # Mount explicit outputs directory for permanent video URLs
    outputs_dir = Path(r"C:\dake\data\outputs")
    outputs_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/outputs", StaticFiles(directory=str(outputs_dir)), name="outputs")

    # CRITICAL: Mount temp_images directory for AI-generated images
    # This allows the editor to access images via /temp_images/{job_id}/{filename}
    temp_images_dir = Path(r"C:\dake\data\temp_images")
    temp_images_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/temp_images", StaticFiles(directory=str(temp_images_dir)), name="temp_images")

    # Mount shorts directory for YouTube clips
    shorts_dir = Path(r"C:\dake\data\shorts")
    shorts_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/shorts", StaticFiles(directory=str(shorts_dir)), name="shorts")

    # Mount templates directory for AI Portraits
    templates_dir = Path(r"C:\dake\data\templates")
    templates_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/templates", StaticFiles(directory=str(templates_dir)), name="templates")

    # Mount musicvideo directory for Music Video Generator
    musicvideo_dir = Path(r"C:\dake\data\musicvideo")
    musicvideo_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/musicvideo_files", StaticFiles(directory=str(musicvideo_dir)), name="musicvideo_files")

    logger.info(f"Static files mounted:")
    logger.info(f"  /data -> {data_dir}")
    logger.info(f"  /outputs -> {outputs_dir}")
    logger.info(f"  /temp_images -> {temp_images_dir} (for editor)")
    logger.info(f"  /shorts -> {shorts_dir} (for YouTube clips)")
    logger.info(f"  /templates -> {templates_dir} (for AI Portraits)")
    logger.info(f"  /musicvideo_files -> {musicvideo_dir} (for Music Videos)")

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        """Return a simple SVG favicon to prevent 404 errors."""
        # Simple AI/video icon as SVG
        svg_icon = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
            <rect width="32" height="32" rx="6" fill="#6366f1"/>
            <path d="M10 8v16l14-8z" fill="white"/>
        </svg>'''
        return Response(content=svg_icon, media_type="image/svg+xml")

    @app.get("/api", response_class=HTMLResponse, include_in_schema=False)
    async def api_info():
        return """
<!DOCTYPE html>
<html>
<head>
    <title>Video Rendering API</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 800px; margin: 50px auto; padding: 20px; background: #0f172a; color: #e2e8f0; }
        h1 { color: #38bdf8; }
        a { color: #38bdf8; text-decoration: none; }
        a:hover { text-decoration: underline; }
        .card { background: #1e293b; border-radius: 8px; padding: 20px; margin: 20px 0; }
        .endpoint { display: flex; align-items: center; gap: 10px; margin: 10px 0; padding: 10px; background: #334155; border-radius: 4px; }
        .method { background: #22c55e; color: white; padding: 2px 8px; border-radius: 4px; font-size: 12px; font-weight: bold; }
        .hint { color: #94a3b8; font-size: 14px; }
        code { background: #334155; padding: 2px 6px; border-radius: 4px; }
        .badge { background:#22c55e;color:white;padding:2px 8px;border-radius:4px;font-size:12px; }
    </style>
</head>
<body>
    <h1>Video Rendering API</h1>
    <p>SaaS API for AI-powered vertical video generation</p>
    <p>Browser Mode: <span class="badge">AUTO-AUTH ENABLED</span></p>

    <div class="card">
        <h2>Quick Links</h2>
        <div class="endpoint">
            <span class="method">GET</span>
            <a href="/docs">/docs</a>
            <span class="hint">- Swagger UI (interactive API docs)</span>
        </div>
        <div class="endpoint">
            <span class="method">GET</span>
            <a href="/redoc">/redoc</a>
            <span class="hint">- ReDoc (API documentation)</span>
        </div>
        <div class="endpoint">
            <span class="method">GET</span>
            <a href="/health">/health</a>
            <span class="hint">- Health check</span>
        </div>
    </div>

    <div class="card">
        <h2>Public UI</h2>
        <div class="endpoint">
            <span class="method">GET</span>
            <a href="/">/</a>
            <span class="hint">- Landing page</span>
        </div>
        <div class="endpoint">
            <span class="method">GET</span>
            <a href="/app">/app</a>
            <span class="hint">- Dashboard</span>
        </div>
        <div class="endpoint">
            <span class="method">GET</span>
            <a href="/app/create">/app/create</a>
            <span class="hint">- Create video</span>
        </div>
    </div>

    <div class="card">
        <h2>API Endpoints</h2>
        <div class="endpoint">
            <span class="method">GET</span>
            <a href="/render/me/credits">/render/me/credits</a>
            <span class="hint">- Your credits (auto-auth for browsers)</span>
        </div>
        <div class="endpoint">
            <span class="method">GET</span>
            <a href="/render">/render</a>
            <span class="hint">- List your render jobs</span>
        </div>
        <div class="endpoint">
            <span class="method">POST</span>
            <span>/render</span>
            <span class="hint">- Create render job (see /docs)</span>
        </div>
    </div>

    <div class="card">
        <h2>Admin</h2>
        <div class="endpoint">
            <span class="method">GET</span>
            <a href="/admin-ui">/admin-ui</a>
            <span class="hint">- Admin Web Interface</span>
        </div>
    </div>

    <div class="card">
        <h2>Authentication</h2>
        <p><strong style="color:#22c55e;">Browser Mode:</strong> Auto-authenticated as guest user (cookie-based)</p>
        <p class="hint">API calls: Add header <code>X-User-Id: your-user-id</code></p>
        <p class="hint">Admin endpoints require: <code>X-Admin-Secret</code></p>
    </div>

    <div class="card">
        <h2>Status</h2>
        <p>Version: 1.0.0</p>
        <p>Storage: SQLite (data/app.db)</p>
    </div>
</body>
</html>
"""

    return app


app = create_app(debug=False, require_auth=True)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
