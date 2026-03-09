"""Admin API — 管理操作（迁移、诊断、配置、Agent 调度）。"""

import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from ..db import get_db
from ..services.event_bus import get_event_bus

log = logging.getLogger("edict.api.admin")
router = APIRouter()


# ── Request Models ──

class DispatchRequest(BaseModel):
    task_id: str
    agent_id: str
    message: str
    trigger: str = "admin-api"

class WakeAgentRequest(BaseModel):
    agent_id: str
    message: str = ""

class CancelAgentRequest(BaseModel):
    agent_id: str
    task_id: str


@router.get("/health/deep")
async def deep_health(db: AsyncSession = Depends(get_db)):
    """深度健康检查：Postgres + Redis 连通性。"""
    checks: dict[str, object] = {"postgres": False, "redis": False}

    # Postgres
    try:
        result = await db.execute(text("SELECT 1"))
        checks["postgres"] = result.scalar() == 1
    except Exception as e:
        checks["postgres_error"] = str(e)

    # Redis
    try:
        bus = await get_event_bus()
        pong = await bus.redis.ping()
        checks["redis"] = pong is True
    except Exception as e:
        checks["redis_error"] = str(e)

    status = "ok" if all(checks.get(k) for k in ["postgres", "redis"]) else "degraded"
    return {"status": status, "checks": checks}


@router.get("/pending-events")
async def pending_events(
    topic: str = "task.dispatch",
    group: str = "dispatcher",
    count: int = 20,
):
    """查看未 ACK 的 pending 事件（诊断工具）。"""
    bus = await get_event_bus()
    pending = await bus.get_pending(topic, group, count)
    return {
        "topic": topic,
        "group": group,
        "pending": [
            {
                "entry_id": str(p.get("message_id", "")),
                "consumer": str(p.get("consumer", "")),
                "idle_ms": p.get("time_since_delivered", 0),
                "delivery_count": p.get("times_delivered", 0),
            }
            for p in pending
        ] if pending else [],
    }


@router.post("/migrate/check")
async def migration_check():
    """检查旧数据文件是否存在。"""
    data_dir = Path(__file__).parents[4] / "data"
    files = {
        "tasks_source": (data_dir / "tasks_source.json").exists(),
        "live_status": (data_dir / "live_status.json").exists(),
        "agent_config": (data_dir / "agent_config.json").exists(),
        "officials_stats": (data_dir / "officials_stats.json").exists(),
    }
    return {"data_dir": str(data_dir), "files": files}


@router.get("/config")
async def get_config():
    """获取当前运行配置（脱敏）。"""
    from ..config import get_settings
    settings = get_settings()
    return {
        "port": settings.port,
        "debug": settings.debug,
        "database": settings.database_url.split("@")[-1] if "@" in settings.database_url else "***",
        "redis": settings.redis_url.split("@")[-1] if "@" in settings.redis_url else settings.redis_url,
        "scheduler_scan_interval": settings.scheduler_scan_interval_seconds,
    }


# ══════════════════════════════════════════════════════════════
# Agent SDK 管理端点 — 供 Dashboard (server.py) 调用
# ══════════════════════════════════════════════════════════════

_LOCALHOST_IPS = {"127.0.0.1", "::1", "localhost"}


def _require_localhost(request: Request):
    """限制 Agent 调度端点仅允许本机访问。"""
    client_host = request.client.host if request.client else ""
    if client_host not in _LOCALHOST_IPS:
        raise HTTPException(status_code=403, detail="Agent admin API is localhost-only")


def _get_runner(request: Request):
    """从 app.state 获取 AgentRunner 单例。"""
    _require_localhost(request)
    runner = getattr(request.app.state, "agent_runner", None)
    if runner is None:
        raise RuntimeError("AgentRunner not initialized")
    return runner


@router.post("/dispatch")
async def dispatch_agent(body: DispatchRequest, request: Request):
    """Dashboard 触发 Agent 派发 — 通过 Agent SDK 异步执行。"""
    runner = _get_runner(request)
    trace_id = f"admin-{body.task_id}"

    # 后台执行，立即返回
    async def _run():
        try:
            result = await runner.run_agent(
                agent_id=body.agent_id,
                message=body.message,
                task_id=body.task_id,
                trace_id=trace_id,
            )
            log.info(
                f"Dispatch complete: {body.task_id} → {body.agent_id} "
                f"success={result.success} cost=${result.cost_usd:.4f}"
            )
        except Exception as e:
            log.error(f"Dispatch error: {body.task_id} → {body.agent_id}: {e}")

    asyncio.create_task(_run())
    return {"ok": True, "message": f"Dispatch queued: {body.task_id} → {body.agent_id}"}


@router.post("/wake-agent")
async def wake_agent(body: WakeAgentRequest, request: Request):
    """Dashboard 唤醒 Agent — 发送心跳/唤醒消息。"""
    runner = _get_runner(request)
    trace_id = f"wake-{body.agent_id}"
    msg = body.message or f"系统心跳检测 — 请回复 OK 确认在线。"

    async def _run():
        try:
            await runner.run_agent(
                agent_id=body.agent_id,
                message=msg,
                task_id=f"wake-{body.agent_id}",
                trace_id=trace_id,
                timeout=130,
            )
        except Exception as e:
            log.error(f"Wake agent error: {body.agent_id}: {e}")

    asyncio.create_task(_run())
    return {"ok": True, "message": f"{body.agent_id} 唤醒指令已发出"}


@router.post("/cancel-agent")
async def cancel_agent(body: CancelAgentRequest, request: Request):
    """Dashboard 取消 Agent — 优雅中断正在执行的 Agent。"""
    runner = _get_runner(request)
    cancelled = await runner.cancel(body.agent_id, body.task_id)
    if cancelled:
        return {"ok": True, "message": f"{body.agent_id}:{body.task_id} 已请求取消"}
    return {"ok": False, "error": f"未找到活跃会话: {body.agent_id}:{body.task_id}"}


@router.get("/active-agents")
async def active_agents(request: Request):
    """Dashboard 查询活跃 Agent（替代 pgrep 检测）。"""
    runner = _get_runner(request)
    agents = runner.list_active()
    return {
        "ok": True,
        "active": agents,
        "count": len(agents),
    }
