"""
에이전트 베이스 클래스

모든 에이전트의 공통 기능:
- Observe → Think → Act 자율 판단 루프
- 슬랙 소통, 노션 연동, AI 판단
- 에이전트 간 작업 요청/수신
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone, timedelta
from typing import Any

import anthropic

from core.message_bus import MessageBus, TaskMessage
from core import agent_tracker

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))


class BaseAgent(ABC):
    """모든 에이전트의 기반 클래스"""

    def __init__(
        self,
        name: str,
        description: str,
        message_bus: MessageBus,
        slack_client,
        notion_client,
        supabase_client,
        anthropic_api_key: str,
        loop_interval: int = 300,  # 기본 5분 간격
        slack_channel: str | None = None,
    ):
        self.name = name
        self.description = description
        self.bus = message_bus
        self.slack = slack_client
        self.notion = notion_client
        self.supabase = supabase_client
        self.ai = anthropic.AsyncAnthropic(api_key=anthropic_api_key)
        self.loop_interval = loop_interval
        self.slack_channel = slack_channel
        self._running = False

        # 메시지 버스에 자신 등록
        self.bus.register_agent(self.name, self._handle_task)

        # 가동 추적 등록
        agent_tracker.register_agent(self.name, self.description, self.loop_interval)

    # ── 자율 판단 루프 ──────────────────────────────────

    async def start(self):
        """에이전트 루프 시작"""
        self._running = True
        logger.info(f"[{self.name}] Agent started (interval: {self.loop_interval}s)")
        while self._running:
            try:
                agent_tracker.heartbeat(self.name)
                context = await self.observe()
                if context:
                    decision = await self.think(context)
                    if decision:
                        await self.act(decision)
            except Exception as e:
                logger.error(f"[{self.name}] Loop error: {e}", exc_info=True)
                agent_tracker.record_error(self.name, e)
                await self.log(f"오류 발생: {e}")
            await asyncio.sleep(self.loop_interval)

    def stop(self):
        self._running = False
        agent_tracker.mark_stopped(self.name)
        logger.info(f"[{self.name}] Agent stopped")

    @abstractmethod
    async def observe(self) -> dict | None:
        """환경 감지: 새로운 상황이 있는지 확인
        Returns: 감지된 상황 컨텍스트 dict, 없으면 None
        """
        ...

    @abstractmethod
    async def think(self, context: dict) -> dict | None:
        """AI 판단: 어떤 행동을 할지 결정
        Returns: 행동 계획 dict, 행동 불필요 시 None
        """
        ...

    @abstractmethod
    async def act(self, decision: dict):
        """실행: think의 결정을 실제로 수행"""
        ...

    # ── 작업 수신 (다른 에이전트로부터) ──────────────────

    async def _handle_task(self, task: TaskMessage) -> Any:
        """다른 에이전트가 보낸 작업 처리"""
        logger.info(f"[{self.name}] Received task from {task.from_agent}: {task.task_type}")
        await self.log(f"📨 {task.from_agent}로부터 작업 수신: {task.task_type}")
        return await self.handle_external_task(task)

    async def handle_external_task(self, task: TaskMessage) -> Any:
        """외부 작업 처리 - 서브클래스에서 오버라이드"""
        logger.warning(f"[{self.name}] Unhandled task type: {task.task_type}")
        return {"status": "unhandled", "task_type": task.task_type}

    # ── 에이전트 간 협업 ────────────────────────────────

    async def ask_agent(self, target_agent: str, task_type: str, payload: dict = None) -> str:
        """다른 에이전트에게 작업 요청"""
        task = TaskMessage(
            from_agent=self.name,
            to_agent=target_agent,
            task_type=task_type,
            payload=payload or {},
        )
        await self.log(f"📤 {target_agent}에게 작업 요청: {task_type}")
        return await self.bus.send_task(task)

    async def broadcast_event(self, event_type: str, data: dict):
        """모든 구독 에이전트에게 이벤트 발행"""
        await self.bus.broadcast(self.name, event_type, data)

    # ── AI 판단 (Claude) ────────────────────────────────

    async def ai_think(self, system_prompt: str, user_prompt: str, model: str = "claude-sonnet-4-20250514") -> str:
        """Claude AI에게 판단 요청"""
        try:
            response = await self.ai.messages.create(
                model=model,
                max_tokens=4096,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            return response.content[0].text
        except Exception as e:
            logger.error(f"[{self.name}] AI think error: {e}")
            raise

    async def ai_decide(self, context: dict, options: list[str] = None) -> dict:
        """구조화된 AI 의사결정"""
        system = f"""당신은 '{self.name}' 에이전트입니다. {self.description}

현재 상황을 분석하고 다음 행동을 JSON으로 결정하세요.
반드시 아래 형식으로만 응답하세요:
{{"action": "행동명", "reason": "판단 근거", "details": {{...구체적 내용...}}}}

가능한 행동: {', '.join(options) if options else '자유롭게 판단'}"""

        import json
        user = f"현재 상황:\n{json.dumps(context, ensure_ascii=False, indent=2)}"
        result = await self.ai_think(system, user)

        try:
            # JSON 블록 추출
            if "```json" in result:
                result = result.split("```json")[1].split("```")[0]
            elif "```" in result:
                result = result.split("```")[1].split("```")[0]
            return json.loads(result.strip())
        except json.JSONDecodeError:
            return {"action": "raw_response", "reason": result, "details": {}}

    # ── 슬랙 소통 ──────────────────────────────────────

    async def say(self, message: str, channel: str = None):
        """슬랙 채널에 메시지 전송"""
        ch = channel or self.slack_channel
        if ch and self.slack:
            await self.slack.send_message(ch, f"*[{self.name}]* {message}")

    async def _reply(self, channel: str, text: str, thread_ts: str = None, broadcast: bool = False):
        """스레드가 있으면 스레드로, 없으면 채널에 직접 전송. broadcast=True면 채널에도 표시"""
        if thread_ts and self.slack:
            await self.slack.send_thread_reply(channel, thread_ts, text, also_send_to_channel=broadcast)
        elif self.slack:
            await self.slack.send_message(channel, text)

    async def log(self, message: str):
        """로그 채널에 메시지 전송"""
        if self.slack:
            await self.slack.send_log(f"[{self.name}] {message}")

    # ── 노션 연동 ──────────────────────────────────────

    async def save_to_notion(self, database_id: str, properties: dict, content_blocks: list = None):
        """노션 데이터베이스에 항목 추가"""
        if self.notion:
            return await self.notion.create_page(database_id, properties, content_blocks)

    async def read_notion_tasks(self, database_id: str, filter_dict: dict = None) -> list:
        """노션에서 액션아이템 읽기"""
        if self.notion:
            return await self.notion.query_database(database_id, filter_dict)
        return []

    # ── 유틸리티 ────────────────────────────────────────

    def now_kst(self) -> datetime:
        return datetime.now(KST)

    def now_str(self) -> str:
        return self.now_kst().strftime("%Y-%m-%d %H:%M")
