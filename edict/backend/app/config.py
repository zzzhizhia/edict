"""Edict 配置管理 — 从环境变量加载所有配置。"""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # ── Server ──
    port: int = 8000
    secret_key: str = "change-me-in-production"
    debug: bool = False

    # ── Claude Code ──
    claude_code_bin: str = "claude"
    claude_code_project_dir: str | None = None

    # ── Agent SDK ──
    agent_sdk_max_concurrent: int = 3
    agent_sdk_timeout_sec: int = 300
    anthropic_api_key: str | None = None

    # ── 调度参数 ──
    stall_threshold_sec: int = 180
    max_dispatch_retry: int = 3
    dispatch_timeout_sec: int = 300
    heartbeat_interval_sec: int = 30
    scheduler_scan_interval_seconds: int = 60

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


@lru_cache
def get_settings() -> Settings:
    return Settings()
