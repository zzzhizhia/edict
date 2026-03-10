"""Agent 配置加载器 — 从 ~/.claude/agents/edict/<id>.md 和 settings.json 解析 Agent 配置。"""

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("edict.agent_config")

# Claude Code agent 命名规范：~/.claude/agents/edict/<name>.md
AGENTS_DIR = Path.home() / ".claude" / "agents" / "edict"
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
    """从 ~/.claude/agents/edict/<id>.md + settings.json 加载 Agent 配置。"""

    _SETTINGS_TTL = 30  # seconds

    def __init__(self, agents_dir: Path | None = None):
        self._agents_dir = agents_dir or AGENTS_DIR
        self._claude_settings: dict = {}
        self._settings_loaded_at: float = 0

    def load(self, agent_id: str) -> AgentConfig:
        soul = self._load_soul(agent_id)
        model = self._get_model(agent_id)
        return AgentConfig(
            agent_id=agent_id,
            system_prompt=soul,
            model=model,
        )

    def _load_soul(self, agent_id: str) -> str:
        # Claude Code 单文件 agent 格式: <name>.md
        agent_md = self._agents_dir / f"{agent_id}.md"
        if not agent_md.exists():
            log.warning(f"Agent file not found: {agent_md}")
            return ""
        content = agent_md.read_text(encoding="utf-8")
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
        now = time.monotonic()
        if self._claude_settings and (now - self._settings_loaded_at) < self._SETTINGS_TTL:
            return self._claude_settings
        try:
            self._claude_settings = json.loads(CLAUDE_SETTINGS.read_text())
        except Exception:
            self._claude_settings = {}
        self._settings_loaded_at = now
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
