"""
God Mode Admin API - Полный контроль над системой.
Protected by X-Admin-Secret header.
"""
import os
import uuid
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from pathlib import Path

from fastapi import APIRouter, HTTPException, status, Header, Depends, Query
from pydantic import BaseModel, Field

from app.auth.repository import get_user_repository
from app.auth.models import User, Plan
from app.persistence.database import get_connection

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/god", tags=["God Mode"])

# Global state
_system_state = {
    "renders_paused": False,
    "pause_reason": None,
    "paused_at": None,
    "paused_by": None,
}

_api_status = {
    "openai": {"status": "operational", "fallback": None, "last_check": None, "error_count": 0},
    "elevenlabs": {"status": "operational", "fallback": None, "last_check": None, "error_count": 0},
    "pexels": {"status": "operational", "fallback": None, "last_check": None, "error_count": 0},
    "whisper": {"status": "operational", "fallback": None, "last_check": None, "error_count": 0},
}

_config = {
    "max_concurrent_renders": 3,
    "default_quality": "1080p",
    "auto_cleanup_days": 7,
}


def _get_admin_secret() -> str:
    return os.environ.get("ADMIN_SECRET", "admin-secret-key-change-in-production")


async def verify_god_mode(
    x_admin_secret: Optional[str] = Header(None, alias="X-Admin-Secret"),
) -> bool:
    if not x_admin_secret or x_admin_secret != _get_admin_secret():
        raise HTTPException(status_code=403, detail={"error": "God Mode access denied"})
    return True


# =============================================================================
# Pydantic Models
# =============================================================================

class SystemHealthResponse(BaseModel):
    renders_paused: bool
    pause_reason: Optional[str]
    paused_at: Optional[str]
    api_status: Dict[str, Any]
    queue_stats: Dict[str, int]
    system_load: Dict[str, Any]


class PauseRendersRequest(BaseModel):
    reason: str = Field(..., min_length=1)


class ApiStatusUpdate(BaseModel):
    service: str
    status: str  # operational, degraded, down
    fallback: Optional[str] = None


class UserSearchResult(BaseModel):
    user_id: str
    email: Optional[str]
    plan: str
    credits: int
    created_at: str
    total_videos: int
    total_spent: float


class UserSessionToken(BaseModel):
    token: str
    user_id: str
    expires_at: str


class QueueTask(BaseModel):
    task_id: str
    user_id: str
    status: str
    created_at: str
    progress: float
    type: str
    error: Optional[str] = None


class ConfigUpdate(BaseModel):
    key: str
    value: Any


class MetricsReport(BaseModel):
    date: str
    api_costs: Dict[str, float]
    revenue: float
    net_profit: float
    videos_created: int
    active_users: int


# =============================================================================
# System Health & Control
# =============================================================================

@router.get("/health", response_model=SystemHealthResponse, dependencies=[Depends(verify_god_mode)])
async def get_system_health():
    """Получить полный статус системы."""
    conn = get_connection()

    # Queue stats
    try:
        pending = conn.execute("SELECT COUNT(*) FROM job_ownership WHERE status = 'pending'").fetchone()[0]
        processing = conn.execute("SELECT COUNT(*) FROM job_ownership WHERE status = 'processing'").fetchone()[0]
        completed = conn.execute("SELECT COUNT(*) FROM job_ownership WHERE status = 'completed'").fetchone()[0]
        failed = conn.execute("SELECT COUNT(*) FROM job_ownership WHERE status = 'failed'").fetchone()[0]
    except:
        pending = processing = completed = failed = 0

    return SystemHealthResponse(
        renders_paused=_system_state["renders_paused"],
        pause_reason=_system_state["pause_reason"],
        paused_at=_system_state["paused_at"],
        api_status=_api_status,
        queue_stats={
            "pending": pending,
            "processing": processing,
            "completed": completed,
            "failed": failed,
        },
        system_load={
            "cpu_percent": 45.0,  # Would be real metrics
            "memory_percent": 62.0,
            "disk_percent": 38.0,
        }
    )


@router.post("/pause-all", dependencies=[Depends(verify_god_mode)])
async def pause_all_renders(request: PauseRendersRequest):
    """ЭКСТРЕННАЯ ОСТАНОВКА всех рендеров."""
    global _system_state
    _system_state["renders_paused"] = True
    _system_state["pause_reason"] = request.reason
    _system_state["paused_at"] = datetime.now().isoformat()

    logger.warning(f"🚨 GOD MODE: All renders PAUSED - {request.reason}")

    return {
        "status": "paused",
        "message": "Все рендеры остановлены",
        "reason": request.reason,
        "paused_at": _system_state["paused_at"],
    }


@router.post("/resume-all", dependencies=[Depends(verify_god_mode)])
async def resume_all_renders():
    """Возобновить все рендеры."""
    global _system_state
    _system_state["renders_paused"] = False
    _system_state["pause_reason"] = None
    _system_state["paused_at"] = None

    logger.info("✅ GOD MODE: All renders RESUMED")

    return {"status": "resumed", "message": "Рендеры возобновлены"}


@router.post("/api-status", dependencies=[Depends(verify_god_mode)])
async def update_api_status(request: ApiStatusUpdate):
    """Обновить статус API и fallback."""
    global _api_status

    if request.service not in _api_status:
        raise HTTPException(status_code=400, detail={"error": f"Unknown service: {request.service}"})

    _api_status[request.service]["status"] = request.status
    _api_status[request.service]["fallback"] = request.fallback
    _api_status[request.service]["last_check"] = datetime.now().isoformat()

    logger.info(f"GOD MODE: API status updated - {request.service} = {request.status}")

    return {"status": "updated", "service": request.service, "new_status": request.status}


# =============================================================================
# User Management
# =============================================================================

@router.get("/users/search", dependencies=[Depends(verify_god_mode)])
async def search_users(
    q: str = Query(..., min_length=1),
    limit: int = Query(50, le=200),
):
    """Поиск пользователей по Email/ID."""
    conn = get_connection()

    cursor = conn.execute("""
        SELECT u.*,
               (SELECT COUNT(*) FROM job_ownership WHERE user_id = u.user_id) as video_count,
               (SELECT COALESCE(SUM(ABS(delta)), 0) FROM credit_ledger WHERE user_id = u.user_id AND delta < 0) as total_spent
        FROM users u
        WHERE u.user_id LIKE ? OR u.email LIKE ?
        ORDER BY u.updated_at DESC
        LIMIT ?
    """, (f"%{q}%", f"%{q}%", limit))

    results = []
    for row in cursor.fetchall():
        results.append({
            "user_id": row[0],
            "email": row[1],
            "plan": row[3],
            "credits": row[2],
            "created_at": row[4],
            "total_videos": row[-2] if len(row) > 5 else 0,
            "total_spent": float(row[-1]) if len(row) > 6 else 0.0,
        })

    return {"results": results, "count": len(results)}


@router.get("/users/{user_id}/full", dependencies=[Depends(verify_god_mode)])
async def get_user_full_info(user_id: str):
    """Полная информация о пользователе."""
    conn = get_connection()

    # User info
    cursor = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user_row = cursor.fetchone()
    if not user_row:
        raise HTTPException(status_code=404, detail={"error": "User not found"})

    # Transactions
    cursor = conn.execute("""
        SELECT * FROM credit_ledger
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT 100
    """, (user_id,))
    transactions = [
        {
            "id": row[0],
            "amount": row[2],  # delta column
            "reason": row[3],
            "job_id": row[4],
            "created_at": row[5],
        }
        for row in cursor.fetchall()
    ]

    # Videos
    cursor = conn.execute("""
        SELECT * FROM job_ownership
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT 100
    """, (user_id,))
    videos = [
        {
            "job_id": row[1],
            "status": row[2],
            "created_at": row[3],
        }
        for row in cursor.fetchall()
    ]

    return {
        "user": {
            "user_id": user_row[0],
            "email": user_row[1],
            "credits": user_row[2],
            "plan": user_row[3],
            "created_at": user_row[4],
            "updated_at": user_row[5],
        },
        "transactions": transactions,
        "videos": videos,
        "stats": {
            "total_videos": len(videos),
            "total_transactions": len(transactions),
            "lifetime_spent": sum(abs(t["amount"]) for t in transactions if t["amount"] < 0),
            "lifetime_earned": sum(t["amount"] for t in transactions if t["amount"] > 0),
        }
    }


@router.post("/users/{user_id}/impersonate", dependencies=[Depends(verify_god_mode)])
async def impersonate_user(user_id: str):
    """Создать токен для входа под пользователем."""
    conn = get_connection()

    cursor = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    if not cursor.fetchone():
        raise HTTPException(status_code=404, detail={"error": "User not found"})

    # Generate impersonation token
    token = f"imp_{uuid.uuid4().hex}"
    expires_at = datetime.now() + timedelta(hours=1)

    logger.warning(f"🔑 GOD MODE: Impersonating user {user_id}")

    return UserSessionToken(
        token=token,
        user_id=user_id,
        expires_at=expires_at.isoformat(),
    )


@router.post("/users/{user_id}/set-limits", dependencies=[Depends(verify_god_mode)])
async def set_user_limits(
    user_id: str,
    credits: Optional[int] = None,
    plan: Optional[str] = None,
):
    """Установить лимиты пользователя."""
    conn = get_connection()

    updates = []
    params = []

    if credits is not None:
        updates.append("credits = ?")
        params.append(credits)

    if plan is not None:
        if plan not in ["free", "pro", "enterprise"]:
            raise HTTPException(status_code=400, detail={"error": "Invalid plan"})
        updates.append("plan = ?")
        params.append(plan)

    if not updates:
        raise HTTPException(status_code=400, detail={"error": "No updates provided"})

    params.append(user_id)
    conn.execute(f"UPDATE users SET {', '.join(updates)}, updated_at = datetime('now') WHERE user_id = ?", params)

    logger.info(f"GOD MODE: Updated user {user_id} limits")

    return {"status": "updated", "user_id": user_id}


# =============================================================================
# Video Pipeline Monitor
# =============================================================================

@router.get("/queue", dependencies=[Depends(verify_god_mode)])
async def get_render_queue():
    """Получить очередь рендеринга."""
    conn = get_connection()

    cursor = conn.execute("""
        SELECT j.*,
               (SELECT credits FROM users WHERE user_id = j.user_id) as user_credits
        FROM job_ownership j
        WHERE j.status IN ('pending', 'processing')
        ORDER BY j.created_at ASC
        LIMIT 100
    """)

    queue = []
    for row in cursor.fetchall():
        queue.append({
            "task_id": row[1],
            "user_id": row[0],
            "status": row[2],
            "created_at": row[3],
            "user_credits": row[-1] if len(row) > 4 else 0,
        })

    return {"queue": queue, "count": len(queue), "paused": _system_state["renders_paused"]}


@router.post("/queue/{task_id}/restart", dependencies=[Depends(verify_god_mode)])
async def restart_task(task_id: str):
    """Перезапустить задачу."""
    conn = get_connection()

    conn.execute("""
        UPDATE job_ownership
        SET status = 'pending', updated_at = datetime('now')
        WHERE job_id = ?
    """, (task_id,))

    logger.info(f"GOD MODE: Restarted task {task_id}")

    return {"status": "restarted", "task_id": task_id}


@router.post("/queue/{task_id}/cancel", dependencies=[Depends(verify_god_mode)])
async def cancel_task(task_id: str):
    """Отменить задачу."""
    conn = get_connection()

    conn.execute("""
        UPDATE job_ownership
        SET status = 'cancelled', updated_at = datetime('now')
        WHERE job_id = ?
    """, (task_id,))

    logger.info(f"GOD MODE: Cancelled task {task_id}")

    return {"status": "cancelled", "task_id": task_id}


@router.get("/logs/errors", dependencies=[Depends(verify_god_mode)])
async def get_error_logs(
    limit: int = Query(50, le=200),
    service: Optional[str] = None,
):
    """Получить логи ошибок."""
    log_file = Path("data/logs/error.log")

    if not log_file.exists():
        return {"logs": [], "message": "No error logs found"}

    try:
        lines = log_file.read_text(encoding="utf-8", errors="ignore").split("\n")
        lines = [l for l in lines if l.strip()][-limit:]

        if service:
            lines = [l for l in lines if service.lower() in l.lower()]

        return {"logs": lines, "count": len(lines)}
    except Exception as e:
        return {"logs": [], "error": str(e)}


@router.get("/logs/ffmpeg", dependencies=[Depends(verify_god_mode)])
async def get_ffmpeg_logs(limit: int = Query(50, le=200)):
    """Получить логи FFmpeg."""
    log_file = Path("data/logs/ffmpeg.log")

    if not log_file.exists():
        return {"logs": [], "message": "No FFmpeg logs found"}

    try:
        lines = log_file.read_text(encoding="utf-8", errors="ignore").split("\n")
        lines = [l for l in lines if l.strip()][-limit:]
        return {"logs": lines, "count": len(lines)}
    except Exception as e:
        return {"logs": [], "error": str(e)}


# =============================================================================
# Business Metrics
# =============================================================================

@router.get("/metrics/daily", dependencies=[Depends(verify_god_mode)])
async def get_daily_metrics(days: int = Query(7, le=90)):
    """Отчёты по дням."""
    conn = get_connection()

    reports = []
    for i in range(days):
        date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")

        # Videos created
        cursor = conn.execute("""
            SELECT COUNT(*) FROM job_ownership
            WHERE date(created_at) = ?
        """, (date,))
        videos = cursor.fetchone()[0]

        # Active users
        cursor = conn.execute("""
            SELECT COUNT(DISTINCT user_id) FROM job_ownership
            WHERE date(created_at) = ?
        """, (date,))
        users = cursor.fetchone()[0]

        # Credits used (debits)
        cursor = conn.execute("""
            SELECT COALESCE(SUM(ABS(delta)), 0) FROM credit_ledger
            WHERE date(created_at) = ? AND delta < 0
        """, (date,))
        credits_used = cursor.fetchone()[0]

        # Simulated costs (would be real API tracking)
        api_costs = {
            "openai": credits_used * 0.02,
            "elevenlabs": credits_used * 0.01,
            "pexels": 0,
            "whisper": credits_used * 0.005,
        }

        # Simulated revenue (would be from payment provider)
        revenue = credits_used * 0.10

        reports.append({
            "date": date,
            "videos_created": videos,
            "active_users": users,
            "credits_used": credits_used,
            "api_costs": api_costs,
            "total_api_cost": sum(api_costs.values()),
            "revenue": revenue,
            "net_profit": revenue - sum(api_costs.values()),
        })

    return {"reports": reports}


@router.get("/metrics/top-users", dependencies=[Depends(verify_god_mode)])
async def get_top_users(limit: int = Query(20, le=100)):
    """Топ пользователей по тратам."""
    conn = get_connection()

    cursor = conn.execute("""
        SELECT
            u.user_id,
            u.email,
            u.plan,
            u.credits,
            COALESCE(SUM(ABS(l.delta)), 0) as total_spent,
            COUNT(DISTINCT j.job_id) as video_count
        FROM users u
        LEFT JOIN credit_ledger l ON u.user_id = l.user_id AND l.delta < 0
        LEFT JOIN job_ownership j ON u.user_id = j.user_id
        GROUP BY u.user_id
        ORDER BY total_spent DESC
        LIMIT ?
    """, (limit,))

    users = []
    for row in cursor.fetchall():
        users.append({
            "user_id": row[0],
            "email": row[1],
            "plan": row[2],
            "credits": row[3],
            "total_spent": float(row[4]),
            "video_count": row[5],
        })

    return {"users": users}


# =============================================================================
# Configuration Manager
# =============================================================================

@router.get("/config", dependencies=[Depends(verify_god_mode)])
async def get_config():
    """Получить текущую конфигурацию."""
    # Get API keys status (masked)
    api_keys = {
        "OPENAI_API_KEY": "••••" + os.environ.get("OPENAI_API_KEY", "")[-4:] if os.environ.get("OPENAI_API_KEY") else "NOT SET",
        "ELEVENLABS_API_KEY": "••••" + os.environ.get("ELEVENLABS_API_KEY", "")[-4:] if os.environ.get("ELEVENLABS_API_KEY") else "NOT SET",
        "PEXELS_API_KEY": "••••" + os.environ.get("PEXELS_API_KEY", "")[-4:] if os.environ.get("PEXELS_API_KEY") else "NOT SET",
        "PIXABAY_API_KEY": "••••" + os.environ.get("PIXABAY_API_KEY", "")[-4:] if os.environ.get("PIXABAY_API_KEY") else "NOT SET",
    }

    return {
        "config": _config,
        "api_keys": api_keys,
        "system_state": _system_state,
    }


@router.post("/config", dependencies=[Depends(verify_god_mode)])
async def update_config(request: ConfigUpdate):
    """Обновить конфигурацию."""
    global _config

    if request.key not in _config:
        raise HTTPException(status_code=400, detail={"error": f"Unknown config key: {request.key}"})

    old_value = _config[request.key]
    _config[request.key] = request.value

    logger.info(f"GOD MODE: Config updated - {request.key}: {old_value} -> {request.value}")

    return {"status": "updated", "key": request.key, "old_value": old_value, "new_value": request.value}


@router.post("/config/api-key", dependencies=[Depends(verify_god_mode)])
async def update_api_key(service: str, key: str):
    """Обновить API ключ (сохраняется в DB)."""
    conn = get_connection()

    # Create config table if not exists
    conn.execute("""
        CREATE TABLE IF NOT EXISTS system_config (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TEXT DEFAULT (datetime('now'))
        )
    """)

    env_key = f"{service.upper()}_API_KEY"

    conn.execute("""
        INSERT OR REPLACE INTO system_config (key, value, updated_at)
        VALUES (?, ?, datetime('now'))
    """, (env_key, key))

    # Also set in environment for current session
    os.environ[env_key] = key

    logger.info(f"GOD MODE: API key updated for {service}")

    return {"status": "updated", "service": service, "key_preview": "••••" + key[-4:]}
