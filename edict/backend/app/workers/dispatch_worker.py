"""Dispatch Worker — 消费 task.dispatch 事件，执行 Agent 调用。

核心解决旧架构痛点：
- 旧: daemon 线程 + subprocess.run → kill -9 丢失一切
- 新: Redis Streams ACK 保证 → 崩溃后自动重新投递
- 新: Agent SDK 流式事件实时推送到 EventBus

流程:
1. 从 task.dispatch stream 消费事件
2. 通过 AgentRunner 调用 Agent SDK（流式事件实时推送）
3. ACK 事件
"""

import asyncio
import logging
import signal

from ..config import get_settings
from ..services.event_bus import (
    EventBus,
    TOPIC_TASK_DISPATCH,
    TOPIC_AGENT_THOUGHTS,
    TOPIC_AGENT_HEARTBEAT,
)
from ..services.agent_runner import AgentRunner
from ..services.usage_tracker import UsageTracker

log = logging.getLogger("edict.dispatcher")

GROUP = "dispatcher"
CONSUMER = "disp-1"


class DispatchWorker:
    """Agent 派发 Worker — 通过 AgentRunner 执行 agent 任务。"""

    def __init__(self, agent_runner: AgentRunner | None = None, max_concurrent: int = 3):
        self.bus = EventBus()
        self._running = False
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._active_tasks: dict[str, asyncio.Task] = {}
        self._agent_runner: AgentRunner | None = agent_runner

    async def start(self):
        await self.bus.connect()
        await self.bus.ensure_consumer_group(TOPIC_TASK_DISPATCH, GROUP)
        self._running = True

        # Initialize AgentRunner if not injected
        if self._agent_runner is None:
            usage_tracker = UsageTracker(redis=self.bus.redis)
            self._agent_runner = AgentRunner(
                event_bus=self.bus,
                usage_tracker=usage_tracker,
            )

        log.info("🚀 Dispatch worker started")

        # 恢复崩溃遗留
        await self._recover_pending()

        while self._running:
            try:
                await self._poll_cycle()
            except Exception as e:
                log.error(f"Dispatch poll error: {e}", exc_info=True)
                await asyncio.sleep(2)

    async def stop(self):
        self._running = False
        # 等待进行中的 agent 调用完成
        if self._active_tasks:
            log.info(f"Waiting for {len(self._active_tasks)} active dispatches...")
            await asyncio.gather(*self._active_tasks.values(), return_exceptions=True)
        await self.bus.close()
        log.info("Dispatch worker stopped")

    async def _recover_pending(self):
        events = await self.bus.claim_stale(
            TOPIC_TASK_DISPATCH, GROUP, CONSUMER, min_idle_ms=60000, count=20
        )
        if events:
            log.info(f"Recovering {len(events)} stale dispatch events")
            for entry_id, event in events:
                await self._dispatch(entry_id, event)

    async def _poll_cycle(self):
        events = await self.bus.consume(
            TOPIC_TASK_DISPATCH, GROUP, CONSUMER, count=3, block_ms=2000
        )
        for entry_id, event in events:
            # 每个派发在独立任务中执行，带并发控制
            task = asyncio.create_task(self._dispatch(entry_id, event))
            task_id = event.get("payload", {}).get("task_id", entry_id)
            self._active_tasks[task_id] = task
            task.add_done_callback(lambda t, tid=task_id: self._active_tasks.pop(tid, None))

    async def _dispatch(self, entry_id: str, event: dict):
        """执行一次 agent 派发 — 通过 AgentRunner 调用 Agent SDK。"""
        async with self._semaphore:
            payload = event.get("payload", {})
            task_id = payload.get("task_id", "")
            agent = payload.get("agent", "")
            message = payload.get("message", "")
            trace_id = event.get("trace_id", "")
            state = payload.get("state", "")

            log.info(f"🔄 Dispatching task {task_id} → agent '{agent}' state={state}")

            # 发布心跳
            await self.bus.publish(
                topic=TOPIC_AGENT_HEARTBEAT,
                trace_id=trace_id,
                event_type="agent.dispatch.start",
                producer="dispatcher",
                payload={"task_id": task_id, "agent": agent},
            )

            try:
                assert self._agent_runner is not None, "AgentRunner not initialized"
                settings = get_settings()
                result = await self._agent_runner.run_agent(
                    agent_id=agent,
                    message=message,
                    task_id=task_id,
                    trace_id=trace_id,
                    timeout=settings.agent_sdk_timeout_sec,
                )

                # 发布 agent 最终输出
                await self.bus.publish(
                    topic=TOPIC_AGENT_THOUGHTS,
                    trace_id=trace_id,
                    event_type="agent.output",
                    producer=f"agent.{agent}",
                    payload={
                        "task_id": task_id,
                        "agent": agent,
                        "output": result.output,
                        "return_code": result.return_code,
                        "cost_usd": result.cost_usd,
                        "duration_ms": result.duration_ms,
                    },
                )

                if result.success:
                    log.info(
                        f"✅ Agent '{agent}' completed task {task_id} "
                        f"(${result.cost_usd:.4f}, {result.duration_ms}ms)"
                    )
                else:
                    log.warning(
                        f"⚠️ Agent '{agent}' failed for task {task_id}: "
                        f"rc={result.return_code}"
                    )

                # ACK — 事件处理完毕
                await self.bus.ack(TOPIC_TASK_DISPATCH, GROUP, entry_id)

            except Exception as e:
                log.error(f"❌ Dispatch failed: task {task_id} → {agent}: {e}", exc_info=True)
                # 不 ACK → Redis 会重新投递给其他消费者


async def run_dispatcher():
    """入口函数 — 用于直接运行 worker。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    worker = DispatchWorker()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(worker.stop()))

    await worker.start()
