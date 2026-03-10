"""Agent Runner — 封装 Claude Agent SDK，执行 Agent 调用。

替代旧的 subprocess.run(['claude', '-p', '--agent', ...]) 调用方式，
提供优雅取消、精确 token 追踪。
"""

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field

from ..config import get_settings
from .agent_config_loader import AgentConfigLoader
from .usage_tracker import UsageTracker, UsageRecord

log = logging.getLogger("edict.agent_runner")

# SDK availability flag — graceful degradation to subprocess if unavailable
_SDK_AVAILABLE = False
try:
    from claude_agent_sdk import query as _sdk_query, ClaudeAgentOptions as _SDKOptions
    from claude_agent_sdk.types import StreamEvent as _StreamEvent, ResultMessage as _ResultMessage
    _SDK_AVAILABLE = True
    log.info("Claude Agent SDK loaded successfully")
except ImportError:
    log.warning("claude-agent-sdk not installed, falling back to subprocess mode")

    # Stubs for type checker — never used at runtime when SDK unavailable
    class _SDKOptions:  # type: ignore[no-redef]
        system_prompt: str | None
        def __init__(self, **kwargs): ...
    class _StreamEvent:  # type: ignore[no-redef]
        event: dict
    class _ResultMessage:  # type: ignore[no-redef]
        usage: dict | None = None
        total_cost_usd: float | None = None

    async def _sdk_query(**kwargs):  # type: ignore[no-redef]
        raise RuntimeError("SDK not available")
        yield  # noqa: unreachable — makes it an async generator for type checker


@dataclass
class AgentResult:
    success: bool
    output: str = ""
    return_code: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float = 0.0
    duration_ms: int = 0
    model: str = ""


@dataclass
class _ActiveSession:
    agent_id: str
    task_id: str
    trace_id: str
    started_at: float
    cancelled: bool = False
    process: asyncio.subprocess.Process | None = field(default=None, repr=False)


class AgentRunner:
    """Agent 执行引擎 — 管理所有活跃 Agent 会话。"""

    def __init__(self, usage_tracker: UsageTracker, config=None):
        self._usage = usage_tracker
        self._config = config or get_settings()
        self._semaphore = asyncio.Semaphore(self._config.agent_sdk_max_concurrent)
        self._active: dict[str, _ActiveSession] = {}
        self._config_loader = AgentConfigLoader()

    async def run_agent(
        self,
        agent_id: str,
        message: str,
        task_id: str,
        trace_id: str,
        timeout: int = 300,
    ) -> AgentResult:
        """执行 Agent 调用。"""
        session_key = f"{agent_id}:{task_id}"

        # 在等待 semaphore 之前就注册 session，让排队中的任务也能被 cancel 找到
        session = _ActiveSession(
            agent_id=agent_id,
            task_id=task_id,
            trace_id=trace_id,
            started_at=time.monotonic(),
        )
        self._active[session_key] = session

        try:
            async with self._semaphore:
                # 拿到 semaphore 后检查是否在排队期间已被取消
                if session.cancelled:
                    log.info(f"Agent '{agent_id}' was cancelled while queued for task {task_id}")
                    return AgentResult(success=False, output="CANCELLED (while queued)", return_code=-2)

                if _SDK_AVAILABLE:
                    result = await asyncio.wait_for(
                        self._run_sdk(session, message),
                        timeout=timeout,
                    )
                else:
                    result = await self._run_subprocess(
                        session, message, timeout
                    )

                # Record usage
                if result.input_tokens or result.cost_usd:
                    await self._usage.record(UsageRecord(
                        agent_id=agent_id,
                        task_id=task_id,
                        trace_id=trace_id,
                        input_tokens=result.input_tokens,
                        output_tokens=result.output_tokens,
                        cache_read_tokens=result.cache_read_tokens,
                        cache_write_tokens=result.cache_write_tokens,
                        cost_usd=result.cost_usd,
                        duration_ms=result.duration_ms,
                        model=result.model,
                    ))

                return result

        except asyncio.TimeoutError:
            log.error(f"Agent '{agent_id}' timed out after {timeout}s for task {task_id}")
            if session.process and session.process.returncode is None:
                session.process.terminate()
            return AgentResult(success=False, output=f"TIMEOUT after {timeout}s", return_code=-1)
        except asyncio.CancelledError:
            log.info(f"Agent '{agent_id}' cancelled for task {task_id}")
            if session.process and session.process.returncode is None:
                session.process.terminate()
            return AgentResult(success=False, output="CANCELLED", return_code=-2)
        finally:
            self._active.pop(session_key, None)

    async def _run_sdk(self, session: _ActiveSession, message: str) -> AgentResult:
        """通过 Claude Agent SDK 执行 Agent。"""
        agent_cfg = self._config_loader.load(session.agent_id)
        start_time = time.monotonic()
        output_parts: list[str] = []

        options = _SDKOptions(
            system_prompt=agent_cfg.system_prompt,
            model=agent_cfg.model,
            allowed_tools=agent_cfg.allowed_tools,
            permission_mode=agent_cfg.permission_mode,
            include_partial_messages=True,
            max_turns=agent_cfg.max_turns,
            max_budget_usd=agent_cfg.max_budget_usd,
        )

        # Inject task context into system prompt
        task_context = (
            f"\n\n[EDICT_CONTEXT]\n"
            f"EDICT_TASK_ID={session.task_id}\n"
            f"EDICT_TRACE_ID={session.trace_id}\n"
            f"EDICT_API_URL=http://localhost:{self._config.port}\n"
        )
        options.system_prompt = (options.system_prompt or "") + task_context

        result = AgentResult(success=True, model=agent_cfg.model)

        async for msg in _sdk_query(prompt=message, options=options):
            if session.cancelled:
                log.info(f"Agent '{session.agent_id}' session cancelled, breaking stream")
                break

            if isinstance(msg, _StreamEvent):
                event = msg.event
                event_type = event.get("type", "")

                if event_type == "content_block_delta":
                    delta = event.get("delta", {})
                    if delta.get("type") == "text_delta":
                        text = delta.get("text", "")
                        if text:
                            output_parts.append(text)

            elif isinstance(msg, _ResultMessage):
                usage = msg.usage or {}
                result.input_tokens = usage.get("input_tokens", 0)
                result.output_tokens = usage.get("output_tokens", 0)
                result.cache_read_tokens = usage.get("cache_read_input_tokens", 0)
                result.cache_write_tokens = usage.get("cache_creation_input_tokens", 0)
                result.cost_usd = msg.total_cost_usd or 0.0

        result.output = "".join(output_parts)[-5000:]
        result.duration_ms = int((time.monotonic() - start_time) * 1000)
        return result

    async def _run_subprocess(
        self,
        session: _ActiveSession,
        message: str,
        timeout: int,
    ) -> AgentResult:
        """降级路径：通过 async subprocess 调用 Claude CLI（SDK 不可用时）。

        使用 asyncio.create_subprocess_exec 代替 subprocess.run，
        支持 cancel 时真正 kill 子进程。
        """
        settings = self._config
        claude_bin = settings.claude_code_bin or "claude"
        cmd = [claude_bin, "-p", "--agent", session.agent_id, message]

        env = os.environ.copy()
        env["EDICT_TASK_ID"] = session.task_id
        env["EDICT_TRACE_ID"] = session.trace_id
        env["EDICT_API_URL"] = f"http://localhost:{settings.port}"

        start_time = time.monotonic()
        proc: asyncio.subprocess.Process | None = None

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                cwd=settings.claude_code_project_dir or None,
            )
            session.process = proc

            stdout_bytes, _ = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
            rc = proc.returncode or 0
            stdout = (stdout_bytes or b"").decode(errors="replace")

        except asyncio.TimeoutError:
            if proc and proc.returncode is None:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5)
                except asyncio.TimeoutError:
                    proc.kill()
            duration_ms = int((time.monotonic() - start_time) * 1000)
            return AgentResult(
                success=False,
                output=f"TIMEOUT after {timeout}s",
                return_code=-1,
                duration_ms=duration_ms,
            )
        except FileNotFoundError:
            return AgentResult(
                success=False,
                output="claude command not found",
                return_code=-1,
                duration_ms=0,
            )

        duration_ms = int((time.monotonic() - start_time) * 1000)
        return AgentResult(
            success=rc == 0,
            output=stdout[-5000:],
            return_code=rc,
            duration_ms=duration_ms,
        )

    async def cancel(self, agent_id: str, task_id: str) -> bool:
        """取消正在执行的 Agent — 标记取消 + kill 子进程。"""
        session_key = f"{agent_id}:{task_id}"
        session = self._active.get(session_key)
        if session:
            session.cancelled = True
            if session.process and session.process.returncode is None:
                session.process.terminate()
            log.info(f"Cancellation requested for {session_key}")
            return True
        return False

    def is_active(self, agent_id: str) -> bool:
        """检查 Agent 是否有活跃会话。"""
        return any(s.agent_id == agent_id for s in self._active.values())

    def list_active(self) -> list[dict]:
        """列出所有活跃会话。"""
        now = time.monotonic()
        return [
            {
                "agent_id": s.agent_id,
                "task_id": s.task_id,
                "trace_id": s.trace_id,
                "running_sec": int(now - s.started_at),
                "cancelled": s.cancelled,
            }
            for s in self._active.values()
        ]
