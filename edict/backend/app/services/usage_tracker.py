"""Usage Tracker — 记录每次 Agent 调用的 token/cost 到 JSONL 文件。"""

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("edict.usage")

DATA_DIR = Path(os.environ.get('EDICT_HOME', Path.home() / '.claude' / 'edict')) / 'data'
USAGE_LOG = DATA_DIR / "usage_log.jsonl"


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
    """记录 Agent 调用的 token/cost 到 JSONL 文件。"""

    def __init__(self):
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

        try:
            with open(USAGE_LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            log.warning(f"Failed to write usage log: {e}")
