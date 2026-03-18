"""
에이전트 라이프사이클 관리자

에이전트 인스턴스 생성, 시작, 종료, 재시작을 중앙 관리.
orchestrator.py에서 에이전트 관리 로직을 분리하기 위한 기반.
"""
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from core import agent_tracker

logger = logging.getLogger("agent_manager")


@dataclass
class AgentEntry:
    """관리 대상 에이전트 엔트리"""
    name: str
    instance: Any  # BaseAgent 인스턴스
    task: asyncio.Task | None = None
    enabled: bool = True
    restart_count: int = 0


class AgentManager:
    """에이전트 라이프사이클 관리자

    Usage:
        manager = AgentManager()
        manager.register("collector", collector_agent, enabled=True)
        manager.register("curator", curator_agent, enabled=False)  # 비활성화 상태

        await manager.start_all()  # 활성화된 에이전트만 시작

        # 상태 확인
        status = manager.get_status()

        # 개별 재시작
        await manager.restart("collector")

        # 전체 종료
        manager.stop_all()
    """

    def __init__(self):
        self._agents: dict[str, AgentEntry] = {}
        self._message_bus_task: asyncio.Task | None = None

    def register(self, name: str, instance: Any, enabled: bool = True):
        """에이전트 등록"""
        self._agents[name] = AgentEntry(
            name=name,
            instance=instance,
            enabled=enabled,
        )
        logger.info(f"에이전트 등록: {name} (활성: {enabled})")

    def get(self, name: str) -> Any | None:
        """에이전트 인스턴스 조회"""
        entry = self._agents.get(name)
        return entry.instance if entry else None

    async def start_all(self) -> dict[str, asyncio.Task]:
        """활성화된 모든 에이전트 시작"""
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

        # 기존 태스크 중단
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
        """모든 태스크 정리 (shutdown 시 호출)"""
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
        """전체 에이전트 상태 점검

        Returns:
            {
                "alive": 3,
                "dead": 1,
                "disabled": 2,
                "issues": ["collector: 죽음 (재시작 시도)"],
                "restarts": ["collector"],
            }
        """
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
