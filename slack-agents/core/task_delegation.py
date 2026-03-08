"""
작업 위임 시스템 (Task Delegation) — Level 5 에이전트 간 협업

마스터(ProactiveAgent)가 작업을 분석하고:
  1. 어떤 에이전트가 적합한지 판단
  2. 작업을 위임하고 데드라인 설정
  3. 결과를 수집하고 평가
  4. 실패 시 다른 에이전트에게 재위임 또는 직접 수행

위임 흐름:
  delegate() → 대기 → 결과 콜백 → 평가 → 보고

MessageBus의 ask_agent를 래핑하면서 추가:
  - 데드라인/타임아웃
  - 결과 추적
  - 자동 재위임
  - 위임 이력 분석
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone, timedelta
from enum import Enum

logger = logging.getLogger("task_delegation")

KST = timezone(timedelta(hours=9))
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")


def _now() -> datetime:
    return datetime.now(KST)


class DelegationStatus(str, Enum):
    PENDING = "pending"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    REASSIGNED = "reassigned"


class TaskDelegation:
    """에이전트 간 작업 위임 관리자"""

    def __init__(self, message_bus=None, ai_think_fn=None, agent_factory=None):
        self._bus = message_bus
        self._ai_think = ai_think_fn
        self._factory = agent_factory
        self._delegations_file = os.path.join(DATA_DIR, "delegations.json")
        self._delegations = self._load()
        os.makedirs(DATA_DIR, exist_ok=True)

    # ── 영속성 ──────────────────────────────────────

    def _load(self) -> dict:
        try:
            with open(self._delegations_file, "r", encoding="utf-8") as f:
                return json.loads(f.read())
        except (FileNotFoundError, json.JSONDecodeError):
            return {
                "active": {},      # id → delegation
                "completed": [],   # 최근 완료 위임
                "stats": {
                    "total_delegated": 0,
                    "total_completed": 0,
                    "total_failed": 0,
                    "total_reassigned": 0,
                    "agent_stats": {},  # agent_name → {delegated, completed, failed, avg_time}
                },
            }

    def _save(self):
        # 완료 목록 최대 100건
        if len(self._delegations["completed"]) > 100:
            self._delegations["completed"] = self._delegations["completed"][-100:]
        with open(self._delegations_file, "w", encoding="utf-8") as f:
            f.write(json.dumps(self._delegations, ensure_ascii=False, indent=2, default=str))

    # ── 핵심: 작업 위임 ──────────────────────────────

    async def delegate(
        self,
        task_description: str,
        task_type: str = "general",
        preferred_agent: str = None,
        deadline_minutes: int = 30,
        payload: dict = None,
        from_agent: str = "proactive",
    ) -> dict:
        """작업을 적절한 에이전트에게 위임한다.

        Returns:
            {delegation_id, assigned_to, status}
        """
        delegation_id = f"dlg_{int(_now().timestamp() * 1000)}"

        # 대상 에이전트 결정
        target = preferred_agent or await self._pick_agent(task_description, task_type)
        if not target:
            return {"delegation_id": delegation_id, "assigned_to": None, "status": "no_agent_available"}

        # 위임 기록 생성
        delegation = {
            "id": delegation_id,
            "task_description": task_description,
            "task_type": task_type,
            "from_agent": from_agent,
            "assigned_to": target,
            "status": DelegationStatus.ASSIGNED.value,
            "payload": payload or {},
            "deadline": (_now() + timedelta(minutes=deadline_minutes)).isoformat(),
            "deadline_minutes": deadline_minutes,
            "created_at": _now().isoformat(),
            "assigned_at": _now().isoformat(),
            "completed_at": "",
            "result": None,
            "grade": "",
            "reassign_count": 0,
            "max_reassigns": 2,
        }

        self._delegations["active"][delegation_id] = delegation
        self._delegations["stats"]["total_delegated"] = \
            self._delegations["stats"].get("total_delegated", 0) + 1
        self._save()

        # MessageBus로 작업 전송
        if self._bus:
            try:
                task_id = await self._send_task(target, task_type, {
                    "delegation_id": delegation_id,
                    "task_description": task_description,
                    "deadline_minutes": deadline_minutes,
                    **(payload or {}),
                }, from_agent)

                delegation["bus_task_id"] = task_id
                delegation["status"] = DelegationStatus.IN_PROGRESS.value
                self._save()

            except Exception as e:
                logger.error(f"[delegation] Send failed: {e}")
                delegation["status"] = DelegationStatus.FAILED.value
                delegation["result"] = f"전송 실패: {e}"
                self._save()

        logger.info(f"[delegation] {delegation_id}: {task_description[:50]} → {target}")
        return {
            "delegation_id": delegation_id,
            "assigned_to": target,
            "status": delegation["status"],
        }

    async def _send_task(self, target: str, task_type: str, payload: dict, from_agent: str) -> str:
        """MessageBus를 통해 작업 전송"""
        from core.message_bus import TaskMessage, TaskStatus
        task = TaskMessage(
            from_agent=from_agent,
            to_agent=target,
            task_type=task_type,
            payload=payload,
            status=TaskStatus.PENDING,
        )
        return self._bus.send_task(task)

    # ── 에이전트 선택 ────────────────────────────────

    async def _pick_agent(self, task_description: str, task_type: str) -> str | None:
        """작업에 가장 적합한 에이전트를 선택"""
        # 등록된 에이전트 목록
        available = []
        if self._bus:
            for name in self._bus._handlers:
                available.append(name)

        # 동적 에이전트도 포함
        if self._factory:
            for name in self._factory.get_active_agents():
                if name not in available:
                    available.append(name)

        if not available:
            return None

        # task_type으로 매핑되는 에이전트 (빠른 경로)
        type_map = {
            "collect": "collector",
            "curate": "curator",
            "research": "proactive",
            "invest": "invest",
            "quote": "quote",
            "fortune": "fortune",
        }
        direct = type_map.get(task_type)
        if direct and direct in available:
            return direct

        # AI로 적합한 에이전트 선택
        if self._ai_think and len(available) > 1:
            # 에이전트별 정보 수집
            agent_info = []
            for name in available:
                info = {"name": name}
                if self._factory:
                    factory_info = self._factory._registry.get("agents", {}).get(name, {})
                    info["purpose"] = factory_info.get("purpose", "")
                    info["score"] = factory_info.get("performance", {}).get("score", 0.5)
                # 위임 성과
                stats = self._delegations["stats"].get("agent_stats", {}).get(name, {})
                info["delegation_completed"] = stats.get("completed", 0)
                info["delegation_failed"] = stats.get("failed", 0)
                agent_info.append(info)

            try:
                response = await self._ai_think(
                    system_prompt='작업에 가장 적합한 에이전트를 선택하라. JSON: {"agent": "이름", "reason": "이유"}',
                    user_prompt=f"""작업: {task_description}
유형: {task_type}

사용 가능 에이전트:
{json.dumps(agent_info, ensure_ascii=False)}""",
                )
                import re
                match = re.search(r"\{.*\}", response, re.DOTALL)
                if match:
                    parsed = json.loads(match.group(0))
                    chosen = parsed.get("agent", "")
                    if chosen in available:
                        return chosen
            except Exception:
                pass

        # 기본: 위임 실패가 가장 적은 에이전트
        return available[0] if available else None

    # ── 결과 처리 ────────────────────────────────────

    async def handle_result(self, delegation_id: str, result: str, success: bool) -> dict:
        """위임 결과 수신"""
        delegation = self._delegations["active"].get(delegation_id)
        if not delegation:
            return {"error": "위임 없음"}

        delegation["completed_at"] = _now().isoformat()
        delegation["result"] = result[:2000] if result else ""

        if success:
            delegation["status"] = DelegationStatus.COMPLETED.value
            self._delegations["stats"]["total_completed"] = \
                self._delegations["stats"].get("total_completed", 0) + 1
            self._update_agent_stats(delegation["assigned_to"], completed=True)
        else:
            delegation["status"] = DelegationStatus.FAILED.value
            self._delegations["stats"]["total_failed"] = \
                self._delegations["stats"].get("total_failed", 0) + 1
            self._update_agent_stats(delegation["assigned_to"], completed=False)

        # 활성 → 완료로 이동
        del self._delegations["active"][delegation_id]
        self._delegations["completed"].append(delegation)
        self._save()

        logger.info(f"[delegation] {delegation_id} {'✅' if success else '❌'}: {result[:80] if result else 'no result'}")

        # 실패 시 재위임 판단
        if not success and delegation.get("reassign_count", 0) < delegation.get("max_reassigns", 2):
            return await self._try_reassign(delegation)

        return {"delegation_id": delegation_id, "status": delegation["status"]}

    async def _try_reassign(self, failed_delegation: dict) -> dict:
        """실패 위임을 다른 에이전트에게 재위임"""
        failed_agent = failed_delegation["assigned_to"]
        task_desc = failed_delegation["task_description"]

        # 실패한 에이전트 제외하고 재선택
        new_target = await self._pick_agent(task_desc, failed_delegation["task_type"])
        if new_target and new_target != failed_agent:
            logger.info(f"[delegation] Reassigning: {failed_agent} → {new_target}")
            result = await self.delegate(
                task_description=task_desc,
                task_type=failed_delegation["task_type"],
                preferred_agent=new_target,
                deadline_minutes=failed_delegation.get("deadline_minutes", 30),
                payload=failed_delegation.get("payload", {}),
            )
            self._delegations["stats"]["total_reassigned"] = \
                self._delegations["stats"].get("total_reassigned", 0) + 1
            self._save()
            return result

        return {"delegation_id": failed_delegation["id"], "status": "reassign_failed"}

    # ── 타임아웃 체크 (주기적 호출) ──────────────────

    async def check_timeouts(self) -> list[dict]:
        """데드라인 초과한 위임 처리"""
        now = _now()
        timed_out = []

        for dlg_id, dlg in list(self._delegations["active"].items()):
            deadline_str = dlg.get("deadline", "")
            if not deadline_str:
                continue
            try:
                deadline = datetime.fromisoformat(deadline_str)
                if now > deadline:
                    dlg["status"] = DelegationStatus.TIMEOUT.value
                    dlg["completed_at"] = now.isoformat()
                    dlg["result"] = "타임아웃"

                    del self._delegations["active"][dlg_id]
                    self._delegations["completed"].append(dlg)
                    self._update_agent_stats(dlg["assigned_to"], completed=False)
                    timed_out.append(dlg)

                    logger.warning(f"[delegation] Timeout: {dlg_id} ({dlg['assigned_to']})")
            except (ValueError, TypeError):
                pass

        if timed_out:
            self._save()

        return timed_out

    # ── 통계 ──────────────────────────────────────────

    def _update_agent_stats(self, agent_name: str, completed: bool):
        stats = self._delegations["stats"].setdefault("agent_stats", {})
        agent = stats.setdefault(agent_name, {"delegated": 0, "completed": 0, "failed": 0})
        agent["delegated"] += 1
        if completed:
            agent["completed"] += 1
        else:
            agent["failed"] += 1

    def get_agent_reliability(self, agent_name: str) -> float:
        """에이전트의 위임 완수율 (0.0 ~ 1.0)"""
        stats = self._delegations["stats"].get("agent_stats", {}).get(agent_name, {})
        total = stats.get("delegated", 0)
        if total == 0:
            return 0.5  # 기본값
        return stats.get("completed", 0) / total

    def get_pending_count(self) -> int:
        return len(self._delegations["active"])

    def get_summary(self) -> str:
        s = self._delegations["stats"]
        active = len(self._delegations["active"])
        return (
            f"위임 현황: 진행중 {active}건 | "
            f"총 {s.get('total_delegated', 0)}건 위임, "
            f"{s.get('total_completed', 0)}건 완료, "
            f"{s.get('total_failed', 0)}건 실패, "
            f"{s.get('total_reassigned', 0)}건 재위임"
        )

    def get_best_agent_for(self, task_type: str) -> str | None:
        """특정 유형 작업에서 가장 성과 좋은 에이전트"""
        # 완료 이력에서 해당 유형 찾기
        agent_scores = {}
        for dlg in self._delegations["completed"]:
            if dlg.get("task_type") == task_type:
                agent = dlg["assigned_to"]
                score = agent_scores.setdefault(agent, {"success": 0, "total": 0})
                score["total"] += 1
                if dlg.get("status") == DelegationStatus.COMPLETED.value:
                    score["success"] += 1

        if not agent_scores:
            return None

        # 성공률 기준 정렬
        best = max(agent_scores.items(), key=lambda x: x[1]["success"] / max(x[1]["total"], 1))
        return best[0]
