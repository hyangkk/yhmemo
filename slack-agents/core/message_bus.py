"""
에이전트 간 내부 메시지 버스

에이전트끼리 작업을 요청하고 결과를 주고받는 비동기 통신 시스템.
Supabase agent_tasks 테이블을 백엔드로 사용하여 영속성 보장.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Coroutine
from uuid import uuid4

from core import agent_tracker

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class TaskMessage:
    from_agent: str
    to_agent: str
    task_type: str
    payload: dict = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid4()))
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# 콜백 타입: async def handler(task: TaskMessage) -> Any
TaskHandler = Callable[[TaskMessage], Coroutine[Any, Any, Any]]


class MessageBus:
    """에이전트 간 비동기 메시지 버스"""

    def __init__(self, supabase_client=None):
        self._handlers: dict[str, TaskHandler] = {}  # agent_name → handler
        self._event_listeners: dict[str, list[TaskHandler]] = {}  # event_type → handlers
        self._queue: asyncio.Queue[TaskMessage] = asyncio.Queue()
        self._supabase = supabase_client
        self._running = False

    def register_agent(self, agent_name: str, handler: TaskHandler):
        """에이전트의 작업 수신 핸들러 등록"""
        self._handlers[agent_name] = handler
        logger.info(f"Agent '{agent_name}' registered on message bus")

    def subscribe(self, event_type: str, handler: TaskHandler):
        """브로드캐스트 이벤트 구독"""
        if event_type not in self._event_listeners:
            self._event_listeners[event_type] = []
        self._event_listeners[event_type].append(handler)

    async def send_task(self, task: TaskMessage) -> str:
        """특정 에이전트에게 작업 전송"""
        await self._queue.put(task)
        if self._supabase:
            await self._persist_task(task)
        logger.info(f"Task {task.id}: {task.from_agent} → {task.to_agent} [{task.task_type}]")
        return task.id

    async def broadcast(self, from_agent: str, event_type: str, data: dict):
        """모든 구독자에게 이벤트 브로드캐스트 (에러 격리)"""
        listeners = self._event_listeners.get(event_type, [])
        if not listeners:
            return

        tasks = []
        for listener in listeners:
            task = TaskMessage(
                from_agent=from_agent,
                to_agent="broadcast",
                task_type=event_type,
                payload=data,
            )
            tasks.append(listener(task))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Broadcast listener {i} error for {event_type}: {result}")

    async def run(self):
        """메시지 처리 루프 시작 (재시도 로직 포함)"""
        self._running = True
        self._retry_counts: dict[str, int] = {}
        self._hb_counter = 0
        logger.info("Message bus started")
        while self._running:
            try:
                task = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                # 타임아웃마다 카운터 증가, ~60초(60회)마다 heartbeat 전송
                self._hb_counter += 1
                if self._hb_counter >= 60:
                    agent_tracker.heartbeat("message_bus")
                    self._hb_counter = 0
                continue

            handler = self._handlers.get(task.to_agent)
            if not handler:
                logger.warning(f"No handler for agent '{task.to_agent}', task {task.id} dropped")
                continue

            task.status = TaskStatus.IN_PROGRESS
            try:
                task.result = await handler(task)
                task.status = TaskStatus.COMPLETED
                self._retry_counts.pop(task.id, None)
                logger.info(f"Task {task.id} completed")
            except Exception as e:
                retries = self._retry_counts.get(task.id, 0)
                max_retries = 3
                if retries < max_retries:
                    self._retry_counts[task.id] = retries + 1
                    delay = 2 ** retries  # 1s, 2s, 4s
                    logger.warning(f"Task {task.id} failed (attempt {retries + 1}/{max_retries}), retrying in {delay}s: {e}")
                    task.status = TaskStatus.PENDING
                    asyncio.get_event_loop().call_later(
                        delay, lambda t=task: asyncio.ensure_future(self._queue.put(t))
                    )
                    continue
                else:
                    task.status = TaskStatus.FAILED
                    task.result = {"error": str(e), "retries_exhausted": max_retries}
                    self._retry_counts.pop(task.id, None)
                    logger.error(f"Task {task.id} failed after {max_retries} retries: {e}")

            if self._supabase:
                await self._update_task(task)

    def stop(self):
        self._running = False

    async def _persist_task(self, task: TaskMessage):
        """Supabase에 작업 기록 저장"""
        try:
            await asyncio.to_thread(
                lambda: self._supabase.table("agent_tasks").insert({
                    "id": task.id,
                    "from_agent": task.from_agent,
                    "to_agent": task.to_agent,
                    "task_type": task.task_type,
                    "payload": task.payload,
                    "status": task.status.value,
                }).execute()
            )
        except Exception as e:
            logger.error(f"Failed to persist task: {e}")

    async def _update_task(self, task: TaskMessage):
        """Supabase 작업 상태 업데이트"""
        try:
            await asyncio.to_thread(
                lambda: self._supabase.table("agent_tasks").update({
                    "status": task.status.value,
                    "result": task.result if isinstance(task.result, dict) else {"value": str(task.result)},
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }).eq("id", task.id).execute()
            )
        except Exception as e:
            logger.error(f"Failed to update task: {e}")
