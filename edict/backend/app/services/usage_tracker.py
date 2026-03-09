"""Usage Tracker — 精确记录每次 Agent SDK 调用的 token/cost。

数据存储在 Redis hash 中，按 agent_id 聚合，支持按时间段查询。
同时写入 data/usage_log.jsonl 供离线分析。
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import redis.asyncio as aioredis

log = logging.getLogger("edict.usage")

DATA_DIR = Path(__file__).resolve().parents[4] / "data"
USAGE_LOG = DATA_DIR / "usage_log.jsonl"
REDIS_KEY_PREFIX = "edict:usage:"


@dataclass
class UsageRecord:
    agent_id: str
    task_id: str
    trace_id: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float = 0.0
    duration_ms: int = 0
    model: str = ""
    timestamp: str = ""


class UsageTracker:
    """记录和查询 Agent SDK 调用的 token/cost。"""

    def __init__(self, redis: aioredis.Redis | None = None):
        self._redis = redis
        DATA_DIR.mkdir(parents=True, exist_ok=True)

    async def record(self, record: UsageRecord):
        record.timestamp = record.timestamp or datetime.now(timezone.utc).isoformat()

        entry = {
            "agent_id": record.agent_id,
            "task_id": record.task_id,
            "trace_id": record.trace_id,
            "input_tokens": record.input_tokens,
            "output_tokens": record.output_tokens,
            "cache_read_tokens": record.cache_read_tokens,
            "cache_write_tokens": record.cache_write_tokens,
            "cost_usd": record.cost_usd,
            "duration_ms": record.duration_ms,
            "model": record.model,
            "timestamp": record.timestamp,
        }

        # Append to JSONL file
        try:
            with open(USAGE_LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            log.warning(f"Failed to write usage log: {e}")

        # Update Redis aggregates
        if self._redis:
            try:
                key = f"{REDIS_KEY_PREFIX}{record.agent_id}"
                await self._redis.hincrby(key, "input_tokens", record.input_tokens)
                await self._redis.hincrby(key, "output_tokens", record.output_tokens)
                await self._redis.hincrby(key, "cache_read_tokens", record.cache_read_tokens)
                await self._redis.hincrby(key, "cache_write_tokens", record.cache_write_tokens)
                await self._redis.hincrbyfloat(key, "cost_usd", record.cost_usd)
                await self._redis.hincrby(key, "call_count", 1)
                await self._redis.hset(key, "last_active", record.timestamp)
            except Exception as e:
                log.warning(f"Failed to update Redis usage: {e}")

    async def get_agent_stats(self, agent_id: str) -> dict:
        if not self._redis:
            return {}
        try:
            key = f"{REDIS_KEY_PREFIX}{agent_id}"
            data = await self._redis.hgetall(key)
            if not data:
                return {}
            return {
                "agent_id": agent_id,
                "input_tokens": int(data.get("input_tokens", 0)),
                "output_tokens": int(data.get("output_tokens", 0)),
                "cache_read_tokens": int(data.get("cache_read_tokens", 0)),
                "cache_write_tokens": int(data.get("cache_write_tokens", 0)),
                "cost_usd": float(data.get("cost_usd", 0)),
                "call_count": int(data.get("call_count", 0)),
                "last_active": data.get("last_active", ""),
            }
        except Exception as e:
            log.warning(f"Failed to read Redis usage: {e}")
            return {}

    async def get_all_stats(self) -> list[dict]:
        if not self._redis:
            return []
        try:
            keys = []
            async for key in self._redis.scan_iter(f"{REDIS_KEY_PREFIX}*"):
                keys.append(key)
            results = []
            for key in keys:
                agent_id = key.removeprefix(REDIS_KEY_PREFIX)
                stats = await self.get_agent_stats(agent_id)
                if stats:
                    results.append(stats)
            return results
        except Exception as e:
            log.warning(f"Failed to list usage stats: {e}")
            return []
