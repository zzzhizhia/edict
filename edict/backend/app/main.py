"""Edict Backend — FastAPI 应用入口。

仅提供 Agent 调度管理 API，供 Dashboard 调用。
任务数据由 Dashboard (JSON 文件) 管理。
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .services.agent_runner import AgentRunner
from .services.usage_tracker import UsageTracker
from .api import admin

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
log = logging.getLogger("edict")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理。"""
    settings = get_settings()
    log.info(f"🏛️ Edict Backend starting on port {settings.port}...")

    usage_tracker = UsageTracker()
    agent_runner = AgentRunner(usage_tracker=usage_tracker, config=settings)
    app.state.agent_runner = agent_runner
    log.info("✅ AgentRunner initialized")

    yield

    log.info("Edict Backend shutdown complete")


app = FastAPI(
    title="Edict 三省六部",
    description="Agent 调度管理 API",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS — 开发环境允许所有来源
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由 — 只保留 admin（Agent 调度）
app.include_router(admin.router, prefix="/api/admin", tags=["admin"])


@app.get("/health")
async def health():
    return {"status": "ok", "version": "2.0.0", "engine": "edict"}
