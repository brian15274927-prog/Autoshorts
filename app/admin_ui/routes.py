"""
Admin UI Routes.
Web-based admin interface for managing the Video Rendering API.
"""
import os
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Request, Form, Depends, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

from .dependencies import (
    get_admin_secret,
    create_session_token,
    check_admin_auth,
    require_admin_ui,
    ADMIN_COOKIE_NAME,
)

from app.persistence.database import get_connection
from app.persistence.users_repo import SQLiteUserRepository
from app.persistence.ledger_repo import CreditLedgerRepository, CreditReason
from app.persistence.jobs_repo import SQLiteJobOwnershipTracker
from app.persistence.idempotency_repo import IdempotencyRepository, IdempotencyStatus
from app.auth.models import Plan

logger = logging.getLogger(__name__)

# Setup paths
BASE_DIR = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

router = APIRouter(prefix="/admin-ui", tags=["Admin UI"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def get_repos():
    """Get all repository instances."""
    return {
        "users": SQLiteUserRepository(),
        "ledger": CreditLedgerRepository(),
        "jobs": SQLiteJobOwnershipTracker(),
        "idempotency": IdempotencyRepository(),
    }


# ============================================================================
# Static Files
# ============================================================================

@router.get("/static/{filename}", include_in_schema=False)
async def static_files(filename: str):
    """Serve static files."""
    file_path = STATIC_DIR / filename
    if file_path.exists():
        content = file_path.read_text()
        media_type = "text/css" if filename.endswith(".css") else "text/plain"
        return HTMLResponse(content=content, media_type=media_type)
    return HTMLResponse(content="Not Found", status_code=404)


# ============================================================================
# Authentication
# ============================================================================

@router.get("/login", response_class=HTMLResponse, include_in_schema=False)
async def login_page(request: Request, error: Optional[str] = None):
    """Render login page."""
    if check_admin_auth(request):
        return RedirectResponse(url="/admin-ui", status_code=303)

    return templates.TemplateResponse("login.html", {
        "request": request,
        "authenticated": False,
        "error": error,
    })


@router.post("/login", include_in_schema=False)
async def login_submit(request: Request, secret: str = Form(...)):
    """Handle login form submission."""
    expected_secret = get_admin_secret()

    if secret != expected_secret:
        return templates.TemplateResponse("login.html", {
            "request": request,
            "authenticated": False,
            "error": "Invalid admin secret",
        })

    response = RedirectResponse(url="/admin-ui", status_code=303)
    token = create_session_token(secret)
    response.set_cookie(
        key=ADMIN_COOKIE_NAME,
        value=token,
        httponly=True,
        max_age=86400,  # 24 hours
        samesite="lax",
    )

    logger.info("Admin UI login successful")
    return response


@router.get("/logout", include_in_schema=False)
async def logout():
    """Handle logout."""
    response = RedirectResponse(url="/admin-ui/login", status_code=303)
    response.delete_cookie(key=ADMIN_COOKIE_NAME)
    logger.info("Admin UI logout")
    return response


# ============================================================================
# Dashboard
# ============================================================================

@router.get("", response_class=HTMLResponse, include_in_schema=False)
async def dashboard(request: Request, _: bool = Depends(require_admin_ui)):
    """Render dashboard page."""
    repos = get_repos()
    conn = get_connection()

    # Get stats
    users_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    jobs_count = conn.execute("SELECT COUNT(*) FROM job_ownership").fetchone()[0]
    ledger_count = conn.execute("SELECT COUNT(*) FROM credit_ledger").fetchone()[0]
    idempotency_count = conn.execute("SELECT COUNT(*) FROM idempotency_keys").fetchone()[0]

    # Get recent ledger entries
    cursor = conn.execute("""
        SELECT * FROM credit_ledger
        ORDER BY created_at DESC
        LIMIT 10
    """)
    recent_ledger = [repos["ledger"]._row_to_entry(row) for row in cursor.fetchall()]

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "authenticated": True,
        "active_page": "dashboard",
        "stats": {
            "total_users": users_count,
            "total_jobs": jobs_count,
            "total_ledger_entries": ledger_count,
            "total_idempotency_keys": idempotency_count,
        },
        "recent_ledger": recent_ledger,
    })


# ============================================================================
# Users
# ============================================================================

@router.get("/users", response_class=HTMLResponse, include_in_schema=False)
async def users_list(
    request: Request,
    search: Optional[str] = Query(None),
    _: bool = Depends(require_admin_ui),
):
    """Render users list page."""
    repos = get_repos()
    conn = get_connection()

    if search:
        cursor = conn.execute(
            "SELECT * FROM users WHERE user_id LIKE ? ORDER BY updated_at DESC LIMIT 100",
            (f"%{search}%",)
        )
    else:
        cursor = conn.execute("SELECT * FROM users ORDER BY updated_at DESC LIMIT 100")

    users = [repos["users"]._row_to_user(row) for row in cursor.fetchall()]

    return templates.TemplateResponse("users.html", {
        "request": request,
        "authenticated": True,
        "active_page": "users",
        "users": users,
        "search": search,
    })


@router.get("/users/{user_id}", response_class=HTMLResponse, include_in_schema=False)
async def user_detail(
    request: Request,
    user_id: str,
    message: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
    _: bool = Depends(require_admin_ui),
):
    """Render user detail page."""
    repos = get_repos()
    conn = get_connection()

    # Get user
    cursor = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if not row:
        return HTMLResponse(content="User not found", status_code=404)

    user = repos["users"]._row_to_user(row)

    # Get ledger
    ledger = repos["ledger"].get_user_history(user_id, limit=50)

    # Get jobs
    jobs = repos["jobs"].get_user_jobs(user_id)[-50:]

    # Get idempotency keys
    cursor = conn.execute(
        "SELECT * FROM idempotency_keys WHERE user_id = ? ORDER BY created_at DESC LIMIT 50",
        (user_id,)
    )
    idempotency_keys = [repos["idempotency"]._row_to_record(row) for row in cursor.fetchall()]

    return templates.TemplateResponse("user_detail.html", {
        "request": request,
        "authenticated": True,
        "active_page": "users",
        "user": user,
        "ledger": ledger,
        "jobs": jobs,
        "idempotency_keys": idempotency_keys,
        "message": message,
        "error": error,
    })


@router.post("/users/{user_id}/plan", include_in_schema=False)
async def update_user_plan(
    user_id: str,
    plan: str = Form(...),
    _: bool = Depends(require_admin_ui),
):
    """Update user plan."""
    repos = get_repos()
    conn = get_connection()

    try:
        # Validate plan
        new_plan = Plan(plan)

        # Update plan
        conn.execute(
            "UPDATE users SET plan = ?, updated_at = datetime('now') WHERE user_id = ?",
            (new_plan.value, user_id)
        )

        logger.info(f"Admin UI: Updated user {user_id} plan to {new_plan.value}")

        return RedirectResponse(
            url=f"/admin-ui/users/{user_id}?message=Plan updated to {new_plan.value}",
            status_code=303
        )

    except Exception as e:
        logger.error(f"Failed to update plan: {e}")
        return RedirectResponse(
            url=f"/admin-ui/users/{user_id}?error=Failed to update plan: {str(e)}",
            status_code=303
        )


@router.post("/users/{user_id}/credits", include_in_schema=False)
async def adjust_user_credits(
    user_id: str,
    delta: int = Form(...),
    reason: str = Form("admin"),
    _: bool = Depends(require_admin_ui),
):
    """Adjust user credits."""
    repos = get_repos()

    try:
        if delta == 0:
            return RedirectResponse(
                url=f"/admin-ui/users/{user_id}?error=Delta cannot be zero",
                status_code=303
            )

        if delta > 0:
            repos["ledger"].record_credit(
                user_id=user_id,
                amount=delta,
                reason=CreditReason.ADMIN,
            )
        else:
            repos["ledger"].record_debit(
                user_id=user_id,
                amount=abs(delta),
                reason=CreditReason.ADMIN,
            )

        logger.info(f"Admin UI: Adjusted user {user_id} credits by {delta}")

        return RedirectResponse(
            url=f"/admin-ui/users/{user_id}?message=Credits adjusted by {delta}",
            status_code=303
        )

    except Exception as e:
        logger.error(f"Failed to adjust credits: {e}")
        return RedirectResponse(
            url=f"/admin-ui/users/{user_id}?error=Failed to adjust credits: {str(e)}",
            status_code=303
        )


# ============================================================================
# Idempotency
# ============================================================================

@router.get("/idempotency", response_class=HTMLResponse, include_in_schema=False)
async def idempotency_list(
    request: Request,
    user_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    _: bool = Depends(require_admin_ui),
):
    """Render idempotency keys list."""
    repos = get_repos()
    conn = get_connection()

    query = "SELECT * FROM idempotency_keys WHERE 1=1"
    params = []

    if user_id:
        query += " AND user_id LIKE ?"
        params.append(f"%{user_id}%")

    if status:
        query += " AND status = ?"
        params.append(status)

    query += " ORDER BY created_at DESC LIMIT 100"

    cursor = conn.execute(query, params)
    keys = [repos["idempotency"]._row_to_record(row) for row in cursor.fetchall()]

    return templates.TemplateResponse("idempotency.html", {
        "request": request,
        "authenticated": True,
        "active_page": "idempotency",
        "keys": keys,
        "user_id": user_id,
        "status": status,
    })


# ============================================================================
# God Mode
# ============================================================================

@router.get("/god", response_class=HTMLResponse, include_in_schema=False)
async def god_mode_panel(request: Request, _: bool = Depends(require_admin_ui)):
    """Render God Mode admin panel."""
    return templates.TemplateResponse("god_mode.html", {
        "request": request,
        "authenticated": True,
        "active_page": "god",
    })
