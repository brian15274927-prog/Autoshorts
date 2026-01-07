"""
SaaS UI Routes - Unified AI Video Studio interface.
Implements the stepped workflow: Input → AI Processing → Clip Selection → Editor
"""
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.auth.dependencies import get_current_user_optional
from app.auth.models import User
from app.credits.service import get_credit_service

# Setup paths
BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"

router = APIRouter(tags=["SaaS UI"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def get_user_credits(user: Optional[User]) -> int:
    """Get user credits, return 3 for guests."""
    if not user:
        return 3
    try:
        service = get_credit_service()
        return service.get_balance(user)
    except Exception:
        return 3


# =============================================================================
# Root redirect
# =============================================================================

@router.get("/", response_class=RedirectResponse, include_in_schema=False)
async def root_redirect():
    """Redirect root to /app (Unified Workspace)."""
    return RedirectResponse(url="/app", status_code=302)


# =============================================================================
# Unified Workspace (Main Dashboard with stepped workflow)
# =============================================================================

@router.get("/app", response_class=HTMLResponse, include_in_schema=False)
async def unified_workspace(
    request: Request,
    user: Optional[User] = Depends(get_current_user_optional),
):
    """
    Unified Workspace - Main Dashboard.
    Implements stepped workflow:
    1. Input URL/File
    2. AI Processing (Director + LangChain)
    3. Clip Selection (with AI Reasoning & Score)
    4. Editor
    """
    credits = get_user_credits(user)
    user_id = user.user_id if user else None

    return templates.TemplateResponse("workspace.html", {
        "request": request,
        "credits": credits,
        "user_id": user_id,
    })


# =============================================================================
# Legacy Studio (redirect to workspace)
# =============================================================================

@router.get("/app/studio", response_class=RedirectResponse, include_in_schema=False)
async def legacy_studio_redirect():
    """Redirect legacy studio to unified workspace."""
    return RedirectResponse(url="/app", status_code=302)


# =============================================================================
# Legacy Create/Dashboard redirects
# =============================================================================

@router.get("/app/create", response_class=RedirectResponse, include_in_schema=False)
async def legacy_create_redirect():
    """Redirect legacy create to unified workspace."""
    return RedirectResponse(url="/app", status_code=302)


@router.get("/app/youtube", response_class=RedirectResponse, include_in_schema=False)
async def legacy_youtube_redirect():
    """Redirect legacy youtube page to unified workspace."""
    return RedirectResponse(url="/app", status_code=302)


@router.get("/app/dashboard", response_class=RedirectResponse, include_in_schema=False)
async def legacy_dashboard_redirect():
    """Redirect legacy dashboard to unified workspace."""
    return RedirectResponse(url="/app", status_code=302)


# =============================================================================
# Single Clip Editor
# =============================================================================

@router.get("/app/editor/{clip_id}", response_class=HTMLResponse, include_in_schema=False)
async def clip_editor(
    request: Request,
    clip_id: str,
    user: Optional[User] = Depends(get_current_user_optional),
):
    """
    Clip Editor page.
    Full editor with:
    - Video preview with subtitle overlay
    - Word-based timeline
    - Style settings (format, subtitle style, font size)
    - Export with format connected to Revideo render core
    """
    credits = get_user_credits(user)
    user_id = user.user_id if user else None

    return templates.TemplateResponse("editor.html", {
        "request": request,
        "credits": credits,
        "user_id": user_id,
        "clip_id": clip_id,
    })


# =============================================================================
# Batch Editor (multiple clips)
# =============================================================================

@router.get("/app/batch-editor", response_class=HTMLResponse, include_in_schema=False)
async def batch_editor(
    request: Request,
    clips: str = Query(..., description="Comma-separated clip IDs"),
    job: str = Query(None, description="Job ID"),
    user: Optional[User] = Depends(get_current_user_optional),
):
    """
    Batch Editor for multiple clips.
    Allows editing multiple clips at once with shared settings.
    """
    credits = get_user_credits(user)
    user_id = user.user_id if user else None
    clip_ids = [c.strip() for c in clips.split(",") if c.strip()]

    return templates.TemplateResponse("editor.html", {
        "request": request,
        "credits": credits,
        "user_id": user_id,
        "clip_id": clip_ids[0] if clip_ids else None,
        "batch_mode": True,
        "clip_ids": clip_ids,
        "job_id": job,
    })


# =============================================================================
# Jobs/Projects List
# =============================================================================

@router.get("/app/projects", response_class=HTMLResponse, include_in_schema=False)
async def projects_list(
    request: Request,
    user: Optional[User] = Depends(get_current_user_optional),
):
    """
    Projects list page.
    Shows all user's video projects with status.
    """
    credits = get_user_credits(user)
    user_id = user.user_id if user else None

    return templates.TemplateResponse("workspace.html", {
        "request": request,
        "credits": credits,
        "user_id": user_id,
        "show_projects": True,
    })


# =============================================================================
# Professional Editor (Faceless + YouTube Clips)
# =============================================================================

@router.get("/app/pro-editor", response_class=HTMLResponse, include_in_schema=False)
async def pro_editor(
    request: Request,
    clip_id: str = Query(None, description="Clip ID to edit"),
    job_id: str = Query(None, description="Faceless job ID"),
    user: Optional[User] = Depends(get_current_user_optional),
):
    """
    Professional Editor page.
    Combines YouTube Clips editing with Faceless AI generation.
    """
    credits = get_user_credits(user)
    user_id = user.user_id if user else None

    return templates.TemplateResponse("pro_editor.html", {
        "request": request,
        "credits": credits,
        "user_id": user_id,
        "clip_id": clip_id,
        "job_id": job_id,
    })


# =============================================================================
# Faceless Studio (Standalone Faceless Generator)
# =============================================================================

@router.get("/app/faceless", response_class=HTMLResponse, include_in_schema=False)
async def faceless_studio(
    request: Request,
    user: Optional[User] = Depends(get_current_user_optional),
):
    """
    Faceless Studio - Standalone faceless video generator.
    """
    credits = get_user_credits(user)
    user_id = user.user_id if user else None

    return templates.TemplateResponse("faceless.html", {
        "request": request,
        "credits": credits,
        "user_id": user_id,
    })


# =============================================================================
# Music Video Generator
# =============================================================================

@router.get("/app/musicvideo", response_class=HTMLResponse, include_in_schema=False)
async def musicvideo_studio(
    request: Request,
    user: Optional[User] = Depends(get_current_user_optional),
):
    """
    Music Video Generator - Create AI-generated music videos from audio.
    """
    credits = get_user_credits(user)
    user_id = user.user_id if user else None

    return templates.TemplateResponse("musicvideo.html", {
        "request": request,
        "credits": credits,
        "user_id": user_id,
    })


# =============================================================================
# AI Portraits Studio
# =============================================================================

@router.get("/app/portraits", response_class=HTMLResponse, include_in_schema=False)
async def portraits_studio(
    request: Request,
    user: Optional[User] = Depends(get_current_user_optional),
):
    """
    AI Portraits Studio - Generate professional portraits with templates.
    """
    credits = get_user_credits(user)
    user_id = user.user_id if user else None

    return templates.TemplateResponse("portraits.html", {
        "request": request,
        "credits": credits,
        "user_id": user_id,
    })
