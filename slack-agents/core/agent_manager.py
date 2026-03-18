"""
에이전트 생명주기 관리자 (Agent Manager)

에이전트 인스턴스 생성, 시작, 종료, 재시작을 중앙 관리.
orchestrator.py에서 에이전트 관련 로직을 분리한 모듈.
"""

import asyncio
import json
import logging
import os
import signal
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Callable

from core import agent_tracker

logger = logging.getLogger("agent_manager")

KST = timezone(timedelta(hours=9))


@dataclass
class AgentEntry:
    """관리 대상 에이전트 엔트리"""
    name: str
    instance: Any  # BaseAgent 인스턴스
    task: asyncio.Task | None = None
    enabled: bool = True
    restart_count: int = 0


class AgentManager:
    """에이전트 생명주기 관리자

    오케스트레이터에서 사용하는 에이전트 생성/시작/종료 로직과
    기존 레지스트리 기능을 통합.

    Usage:
        manager = AgentManager()

        # 방법 1: orchestrator 스타일 - 팩토리로 일괄 생성
        manager.create_all_from_config(config, supabase, slack, notion, ls_client, bus)
        manager.start_all_tasks()

        # 방법 2: 개별 등록
        manager.register("collector", collector_agent, enabled=True)
        await manager.start_all()
    """

    def __init__(self):
        self._agents: dict[str, AgentEntry] = {}
        self._message_bus_task: asyncio.Task | None = None

        # 팩토리 패턴용 (orchestrator에서 사용)
        self.agent_starters: dict[str, Callable] = {}
        self.agent_tasks: dict[str, asyncio.Task] = {}

        # 부가 시스템
        self.invest_monitor = None
        self.agent_hr = None

        # 참조 저장
        self._bus = None
        self._notion = None

    # ── 팩토리: orchestrator에서 사용하는 일괄 생성 ──────────────

    def create_all_from_config(self, config: dict, supabase, slack, notion, ls_client, bus):
        """config를 기반으로 모든 에이전트를 일괄 생성하고 등록"""
        from agents.collector_agent import CollectorAgent
        from agents.curator_agent import CuratorAgent
        from agents.quote_agent import QuoteAgent
        from agents.proactive_agent import ProactiveAgent
        from agents.task_board_agent import TaskBoardAgent
        from agents.fortune_agent import FortuneAgent
        from agents.diary_quote_agent import DiaryQuoteAgent
        from agents.diary_daily_alert_agent import DiaryDailyAlertAgent
        from agents.sentiment_agent import SentimentAgent
        from agents.auto_trader_agent import AutoTraderAgent
        from agents.market_info_agent import MarketInfoAgent
        from agents.swing_trader_agent import SwingTraderAgent
        from agents.bulletin_agent import BulletinAgent
        from agents.qa_agent import QAAgent
        from agents.invest_research_agent import InvestResearchAgent
        from core.agent_hr import AgentHR
        from core.invest_monitor import InvestMonitor

        self._bus = bus
        self._notion = notion

        common_kwargs = {
            "message_bus": bus,
            "slack_client": slack,
            "notion_client": notion,
            "supabase_client": supabase,
            "anthropic_api_key": config["ANTHROPIC_API_KEY"],
        }

        # 에이전트 인스턴스 생성 + 등록
        instances = {
            "collector": CollectorAgent(**common_kwargs),
            "proactive": ProactiveAgent(**common_kwargs),
            "curator": CuratorAgent(
                notion_db_id=config.get("NOTION_DATABASE_ID", ""),
                **common_kwargs,
            ),
            "quote": QuoteAgent(**common_kwargs),
            "diary_quote": DiaryQuoteAgent(
                diary_db_id=config.get("DIARY_NOTION_DATABASE_ID", ""),
                **common_kwargs,
            ),
            "diary_daily_alert": DiaryDailyAlertAgent(
                diary_db_id=config.get("DIARY_NOTION_DATABASE_ID", ""),
                **common_kwargs,
            ),
            "fortune": FortuneAgent(**common_kwargs),
            "sentiment": SentimentAgent(**common_kwargs),
            "task_board": TaskBoardAgent(
                task_board_db_id=config.get("NOTION_TASK_BOARD_DB_ID", ""),
                **common_kwargs,
            ),
            "auto_trader": AutoTraderAgent(ls_client=ls_client, **common_kwargs),
            "market_info": MarketInfoAgent(**common_kwargs),
            "swing_trader": SwingTraderAgent(ls_client=ls_client, **common_kwargs),
            "bulletin": BulletinAgent(**common_kwargs),
            "invest_research": InvestResearchAgent(ls_client=ls_client, **common_kwargs),
            "qa": QAAgent(**common_kwargs),
        }

        for name, inst in instances.items():
            self.register(name, inst)

        # 투자 모니터링 시스템
        self.invest_monitor = InvestMonitor(
            supabase_client=supabase,
            ls_client=ls_client,
            ai_think_fn=instances["curator"].ai_think,
        )

        # 인사관리 (HR) 시스템
        self.agent_hr = AgentHR(
            ai_think_fn=instances["curator"].ai_think,
            supabase_client=supabase,
        )
        for _agent_name in [
            "orchestrator", "proactive", "collector", "curator",
            "sentiment", "task_board", "diary_quote", "diary_daily_alert", "quote",
            "fortune", "message_bus", "auto_trader", "market_info",
            "bulletin", "invest_research", "qa",
        ]:
            self.agent_hr.ensure_registered(_agent_name)

        # ProactiveAgent의 evaluator에 invest_monitor 주입
        instances["proactive"].evaluator._invest_monitor = self.invest_monitor

        logger.info(f"모든 에이전트 인스턴스 생성 완료 ({len(instances)}개)")

    def start_all_tasks(self):
        """모든 활성 에이전트의 asyncio 태스크 시작 (팩토리 패턴)"""
        self.agent_starters = {
            "message_bus": lambda: asyncio.create_task(self._bus.run(), name="message_bus"),
            "diary_quote": lambda: asyncio.create_task(self.get("diary_quote").start(), name="diary_quote"),
            "diary_daily_alert": lambda: asyncio.create_task(self.get("diary_daily_alert").start(), name="diary_daily_alert"),
            "proactive": lambda: asyncio.create_task(self.get("proactive").start(), name="proactive"),
            "task_board": lambda: asyncio.create_task(self.get("task_board").start(), name="task_board"),
            "sentiment": lambda: asyncio.create_task(self.get("sentiment").start(), name="sentiment"),
            "auto_trader": lambda: asyncio.create_task(self.get("auto_trader").start(), name="auto_trader"),
            "market_info": lambda: asyncio.create_task(self.get("market_info").start(), name="market_info"),
            "swing_trader": lambda: asyncio.create_task(self.get("swing_trader").start(), name="swing_trader"),
            "bulletin": lambda: asyncio.create_task(self.get("bulletin").start(), name="bulletin"),
            "invest_research": lambda: asyncio.create_task(self.get("invest_research").start(), name="invest_research"),
            "qa": lambda: asyncio.create_task(self.get("qa").start(), name="qa"),
        }
        self.agent_tasks = {name: starter() for name, starter in self.agent_starters.items()}

        # 오케스트레이터 자체도 추적 등록
        agent_tracker.register_agent("orchestrator", "메인 폴링 루프 + 메시지 라우터", 3)
        agent_tracker.register_agent("message_bus", "에이전트 간 메시지 버스", 0)

        logger.info(f"에이전트 태스크 {len(self.agent_tasks)}개 시작")

    async def start_dynamic_agents(self):
        """동적 에이전트 시작 (proactive agent가 초기화된 후)"""
        try:
            proactive = self.get("proactive")
            if proactive:
                started = await proactive.agent_factory.start_all_active()
                if started > 0:
                    logger.info(f"동적 에이전트 {started}개 시작")
        except Exception as e:
            logger.error(f"동적 에이전트 시작 실패: {e}")

    async def delayed_dynamic_start(self, delay: int = 10):
        """proactive 초기화 대기 후 동적 에이전트 시작"""
        await asyncio.sleep(delay)
        await self.start_dynamic_agents()

    def setup_shutdown(self, shutdown_event: asyncio.Event):
        """Graceful shutdown 시그널 핸들러 설정"""

        def signal_handler():
            logger.info("종료 시그널 수신")
            shutdown_event.set()
            if self._bus:
                self._bus.stop()
            for name in ["collector", "curator", "quote", "proactive", "swing_trader", "invest_research"]:
                agent = self.get(name)
                if agent and hasattr(agent, 'stop'):
                    agent.stop()

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, signal_handler)

    async def watchdog_health_check(self):
        """
        마스터 워치독: 에이전트 태스크 생존 확인 + 자동 재시작.
        (issues, restarts) 튜플 반환.
        """
        now = datetime.now(KST)
        now_str = now.strftime("%H:%M")
        issues = []
        restarts = []

        # 1. 에이전트 태스크 생존 확인 + 자동 재시작
        for name, task in list(self.agent_tasks.items()):
            if task.done():
                exc = task.exception() if not task.cancelled() else None
                err_msg = str(exc)[:100] if exc else "unknown"
                logger.warning(f"[watchdog] 에이전트 '{name}' 죽음 (error: {err_msg})")
                agent_tracker.record_error(name, f"Task died: {err_msg}")

                if name in self.agent_starters:
                    try:
                        self.agent_tasks[name] = self.agent_starters[name]()
                        agent_tracker.register_agent(name, f"자동 재시작됨 ({now_str})")
                        restarts.append(name)
                        logger.info(f"[watchdog] 에이전트 재시작: {name}")
                    except Exception as e:
                        issues.append(f"❌ {name}: 재시작 실패 ({e})")
                        logger.error(f"[watchdog] 재시작 실패 {name}: {e}")
                else:
                    issues.append(f"❌ {name}: 죽음 (재시작 불가)")

        # 2. heartbeat 체크
        tracker_data = agent_tracker._load()
        for name, info in tracker_data.get("agents", {}).items():
            if name not in self.agent_starters:
                continue
            last_hb = info.get("last_heartbeat", "")
            if last_hb:
                try:
                    hb_time = datetime.fromisoformat(last_hb)
                    if hb_time.tzinfo is None:
                        hb_time = hb_time.replace(tzinfo=KST)
                    elapsed = (now - hb_time).total_seconds()
                    loop_sec = info.get("loop_interval", 0)
                    threshold = max(900, loop_sec * 2 + 300)
                    if elapsed > threshold:
                        mins = int(elapsed / 60)
                        issues.append(f"⚠️ {name}: heartbeat {mins}분 전 (무응답)")
                except (ValueError, TypeError):
                    pass

        alive = sum(1 for t in self.agent_tasks.values() if not t.done())
        total = len(self.agent_tasks)
        logger.info(f"[watchdog] 헬스체크: {alive}/{total} 에이전트 생존, 이슈={len(issues)}, 재시작={restarts}")

        return issues, restarts

    async def cleanup_tasks(self):
        """모든 에이전트 태스크 정리 (shutdown 시 호출)"""
        for task in self.agent_tasks.values():
            task.cancel()
        await asyncio.gather(*self.agent_tasks.values(), return_exceptions=True)
        if self._notion:
            await self._notion.close()
        logger.info("에이전트 태스크 정리 완료")

    # ── 기존 레지스트리 인터페이스 (하위 호환) ─────────────────

    def register(self, name: str, instance: Any, enabled: bool = True):
        """에이전트 등록"""
        self._agents[name] = AgentEntry(
            name=name,
            instance=instance,
            enabled=enabled,
        )
        logger.debug(f"에이전트 등록: {name} (활성: {enabled})")

    def get(self, name: str) -> Any | None:
        """에이전트 인스턴스 조회"""
        entry = self._agents.get(name)
        return entry.instance if entry else None

    async def start_all(self) -> dict[str, asyncio.Task]:
        """활성화된 모든 에이전트 시작 (레거시 인터페이스)"""
        tasks = {}
        for name, entry in self._agents.items():
            if entry.enabled and entry.instance:
                entry.task = asyncio.create_task(
                    entry.instance.start(), name=name
                )
                tasks[name] = entry.task
                logger.info(f"에이전트 시작: {name}")
        return tasks

    async def start_one(self, name: str) -> asyncio.Task | None:
        """개별 에이전트 시작"""
        entry = self._agents.get(name)
        if not entry or not entry.instance:
            logger.warning(f"에이전트 '{name}' 미등록")
            return None
        if entry.task and not entry.task.done():
            logger.warning(f"에이전트 '{name}' 이미 실행 중")
            return entry.task
        entry.task = asyncio.create_task(
            entry.instance.start(), name=name
        )
        entry.enabled = True
        logger.info(f"에이전트 시작: {name}")
        return entry.task

    async def restart(self, name: str) -> asyncio.Task | None:
        """에이전트 재시작"""
        entry = self._agents.get(name)
        if not entry:
            return None
        if entry.task and not entry.task.done():
            entry.instance.stop()
            entry.task.cancel()
            try:
                await entry.task
            except (asyncio.CancelledError, Exception):
                pass
        entry.restart_count += 1
        agent_tracker.register_agent(
            name, f"재시작됨 (#{entry.restart_count})"
        )
        return await self.start_one(name)

    def stop_all(self):
        """모든 에이전트 종료"""
        for name, entry in self._agents.items():
            if entry.instance and hasattr(entry.instance, 'stop'):
                entry.instance.stop()
            if entry.task and not entry.task.done():
                entry.task.cancel()
        logger.info(f"전체 에이전트 종료 신호 ({len(self._agents)}개)")

    def stop_one(self, name: str):
        """개별 에이전트 종료"""
        entry = self._agents.get(name)
        if entry:
            if entry.instance and hasattr(entry.instance, 'stop'):
                entry.instance.stop()
            if entry.task and not entry.task.done():
                entry.task.cancel()
            entry.enabled = False

    async def cleanup(self):
        """모든 태스크 정리 (레거시 인터페이스)"""
        tasks = [
            entry.task for entry in self._agents.values()
            if entry.task and not entry.task.done()
        ]
        if tasks:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("에이전트 태스크 정리 완료")

    def check_health(self) -> dict:
        """전체 에이전트 상태 점검 (레거시 인터페이스)"""
        alive = 0
        dead = 0
        disabled = 0
        issues = []
        dead_agents = []

        for name, entry in self._agents.items():
            if not entry.enabled:
                disabled += 1
                continue
            if entry.task and not entry.task.done():
                alive += 1
            else:
                dead += 1
                exc = None
                if entry.task:
                    try:
                        exc = entry.task.exception() if not entry.task.cancelled() else None
                    except (asyncio.CancelledError, asyncio.InvalidStateError):
                        pass
                err_msg = str(exc)[:100] if exc else "unknown"
                issues.append(f"❌ {name}: 죽음 ({err_msg})")
                dead_agents.append(name)

        return {
            "alive": alive,
            "dead": dead,
            "disabled": disabled,
            "total": len(self._agents),
            "issues": issues,
            "dead_agents": dead_agents,
        }

    async def auto_restart_dead(self) -> list[str]:
        """죽은 에이전트 자동 재시작"""
        health = self.check_health()
        restarted = []
        for name in health["dead_agents"]:
            try:
                await self.restart(name)
                restarted.append(name)
                logger.info(f"[auto_restart] 에이전트 재시작 성공: {name}")
            except Exception as e:
                logger.error(f"[auto_restart] 에이전트 재시작 실패: {name} - {e}")
        return restarted

    def get_status(self) -> str:
        """상태 요약 문자열"""
        health = self.check_health()
        lines = [
            f"*에이전트 상태* ({health['alive']}/{health['total']} 가동중)",
        ]
        for name, entry in sorted(self._agents.items()):
            if not entry.enabled:
                lines.append(f"  ⚪ {name} (비활성)")
            elif entry.task and not entry.task.done():
                lines.append(f"  🟢 {name} (가동중, 재시작: {entry.restart_count}회)")
            else:
                lines.append(f"  🔴 {name} (중단됨)")
        return "\n".join(lines)

    @property
    def agent_names(self) -> list[str]:
        return list(self._agents.keys())

    @property
    def enabled_count(self) -> int:
        return sum(1 for e in self._agents.values() if e.enabled)
