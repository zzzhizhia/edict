"""Agent 配置加载器 — 从 SOUL.md 和 ~/.claude/settings.json 解析 Agent 配置。"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("edict.agent_config")

AGENTS_DIR = Path(__file__).resolve().parents[4] / "agents"
CLAUDE_SETTINGS = Path.home() / ".claude" / "settings.json"

DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_ALLOWED_TOOLS = ["Read", "Edit", "Write", "Bash", "Glob", "Grep"]


@dataclass
class AgentConfig:
    agent_id: str
    system_prompt: str = ""
    model: str = DEFAULT_MODEL
    allowed_tools: list[str] = field(default_factory=lambda: list(DEFAULT_ALLOWED_TOOLS))
    permission_mode: str = "acceptEdits"
    max_turns: int = 30
    max_budget_usd: float = 5.0


class AgentConfigLoader:
    """从 agents/<id>/SOUL.md + ~/.claude/settings.json 加载 Agent 配置。"""

    def __init__(self, agents_dir: Path | None = None):
        self._agents_dir = agents_dir or AGENTS_DIR
        self._claude_settings: dict | None = None

    def load(self, agent_id: str) -> AgentConfig:
        soul = self._load_soul(agent_id)
        model = self._get_model(agent_id)
        return AgentConfig(
            agent_id=agent_id,
            system_prompt=soul,
            model=model,
        )

    def _load_soul(self, agent_id: str) -> str:
        soul_path = self._agents_dir / agent_id / "SOUL.md"
        if not soul_path.exists():
            log.warning(f"SOUL.md not found for agent '{agent_id}': {soul_path}")
            return ""
        content = soul_path.read_text(encoding="utf-8")
        # Strip YAML frontmatter if present
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                return parts[2].strip()
        return content

    def _get_model(self, agent_id: str) -> str:
        settings = self._load_claude_settings()
        agents_cfg = settings.get("agents", {})
        default = self._normalize_model(agents_cfg.get("defaults", {}).get("model", {}))

        for a in agents_cfg.get("list", []):
            if a.get("id") == agent_id:
                return self._normalize_model(a.get("model", default), default)
        # Legacy: taizi was previously "main"
        if agent_id == "taizi":
            for a in agents_cfg.get("list", []):
                if a.get("id") == "main":
                    return self._normalize_model(a.get("model", default), default)
        return default

    def _load_claude_settings(self) -> dict:
        if self._claude_settings is not None:
            return self._claude_settings
        try:
            self._claude_settings = json.loads(CLAUDE_SETTINGS.read_text())
        except Exception:
            self._claude_settings = {}
        return self._claude_settings

    @staticmethod
    def _normalize_model(value, fallback: str = DEFAULT_MODEL) -> str:
        if isinstance(value, str) and value:
            # Strip provider prefix if present (e.g. "anthropic/claude-sonnet-4-6")
            return value.split("/")[-1] if "/" in value else value
        if isinstance(value, dict):
            raw = value.get("primary") or value.get("id") or fallback
            return raw.split("/")[-1] if "/" in raw else raw
        return fallback
