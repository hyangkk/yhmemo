"""
목표 기반 자율 계획 시스템 (Goal Planner)

진짜 자율: 목표 → 계획 → 실행 → 피드백 → 재계획

타이머가 아닌 목표(Goal)를 중심으로 에이전트가 스스로 계획을 세우고,
실행하고, 결과를 평가하고, 필요하면 계획을 수정한다.
"""

import json
import logging
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Optional

logger = logging.getLogger("goal_planner")

KST = timezone(timedelta(hours=9))
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")


class GoalStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


class PlanStepStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class PlanStep:
    description: str
    method: str  # "research", "propose", "build", "measure", "communicate"
    status: PlanStepStatus = PlanStepStatus.PENDING
    result: str = ""
    started_at: str = ""
    completed_at: str = ""

    def to_dict(self) -> dict:
        return {
            "description": self.description,
            "method": self.method,
            "status": self.status.value,
            "result": self.result,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }

    @staticmethod
    def from_dict(d: dict) -> "PlanStep":
        return PlanStep(
            description=d["description"],
            method=d["method"],
            status=PlanStepStatus(d.get("status", "pending")),
            result=d.get("result", ""),
            started_at=d.get("started_at", ""),
            completed_at=d.get("completed_at", ""),
        )


@dataclass
class Goal:
    id: str
    title: str
    description: str
    priority: int  # 1 (highest) - 5 (lowest)
    status: GoalStatus = GoalStatus.ACTIVE
    plan: list[PlanStep] = field(default_factory=list)
    feedback_history: list[dict] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    deadline: str = ""  # optional
    success_criteria: str = ""
    current_step_index: int = 0
    replan_count: int = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "priority": self.priority,
            "status": self.status.value,
            "plan": [s.to_dict() for s in self.plan],
            "feedback_history": self.feedback_history[-20:],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "deadline": self.deadline,
            "success_criteria": self.success_criteria,
            "current_step_index": self.current_step_index,
            "replan_count": self.replan_count,
        }

    @staticmethod
    def from_dict(d: dict) -> "Goal":
        return Goal(
            id=d["id"],
            title=d["title"],
            description=d["description"],
            priority=int(d.get("priority", 3)) if str(d.get("priority", 3)).isdigit() else 3,
            status=GoalStatus(d.get("status", "active")),
            plan=[PlanStep.from_dict(s) for s in d.get("plan", [])],
            feedback_history=d.get("feedback_history", []),
            created_at=d.get("created_at", ""),
            updated_at=d.get("updated_at", ""),
            deadline=d.get("deadline", ""),
            success_criteria=d.get("success_criteria", ""),
            current_step_index=d.get("current_step_index", 0),
            replan_count=d.get("replan_count", 0),
        )

    def next_pending_step(self) -> Optional[PlanStep]:
        """다음 실행할 스텝 반환"""
        for i, step in enumerate(self.plan):
            if step.status == PlanStepStatus.PENDING:
                self.current_step_index = i
                return step
        return None

    def progress_pct(self) -> float:
        if not self.plan:
            return 0.0
        done = sum(1 for s in self.plan if s.status in (PlanStepStatus.COMPLETED, PlanStepStatus.SKIPPED))
        return round(done / len(self.plan) * 100, 1)

    def is_done(self) -> bool:
        return all(s.status in (PlanStepStatus.COMPLETED, PlanStepStatus.SKIPPED, PlanStepStatus.FAILED)
                    for s in self.plan) if self.plan else False


class GoalPlanner:
    """목표 기반 계획 시스템"""

    def __init__(self, ai_think_fn=None):
        self._goals_file = os.path.join(DATA_DIR, "goals.json")
        self._goals: list[Goal] = self._load_goals()
        self._ai_think = ai_think_fn  # async fn(system_prompt, user_prompt) -> str
        os.makedirs(DATA_DIR, exist_ok=True)

    # ── 영속성 ──────────────────────────────────────

    def _load_goals(self) -> list[Goal]:
        try:
            with open(self._goals_file, "r", encoding="utf-8") as f:
                data = json.loads(f.read())
            return [Goal.from_dict(g) for g in data]
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def _save_goals(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(self._goals_file, "w", encoding="utf-8") as f:
            f.write(json.dumps([g.to_dict() for g in self._goals], ensure_ascii=False, indent=2))

    # ── 목표 관리 ──────────────────────────────────

    def add_goal(self, title: str, description: str, priority: int = 3,
                 success_criteria: str = "", deadline: str = "") -> Goal:
        now = datetime.now(KST).isoformat()
        goal = Goal(
            id=f"goal_{int(datetime.now(KST).timestamp() * 1000)}",
            title=title,
            description=description,
            priority=int(priority) if str(priority).isdigit() else 3,
            created_at=now,
            updated_at=now,
            success_criteria=success_criteria,
            deadline=deadline,
        )
        self._goals.append(goal)
        self._save_goals()
        logger.info(f"[planner] New goal: {title} (priority={priority})")
        return goal

    def get_active_goals(self) -> list[Goal]:
        return sorted(
            [g for g in self._goals if g.status == GoalStatus.ACTIVE],
            key=lambda g: g.priority,
        )

    def get_goal(self, goal_id: str) -> Optional[Goal]:
        for g in self._goals:
            if g.id == goal_id:
                return g
        return None

    def complete_goal(self, goal_id: str, result: str = ""):
        goal = self.get_goal(goal_id)
        if goal:
            goal.status = GoalStatus.COMPLETED
            goal.updated_at = datetime.now(KST).isoformat()
            goal.feedback_history.append({
                "type": "completed", "result": result,
                "ts": datetime.now(KST).isoformat(),
            })
            self._save_goals()

    def fail_goal(self, goal_id: str, reason: str = ""):
        goal = self.get_goal(goal_id)
        if goal:
            goal.status = GoalStatus.FAILED
            goal.updated_at = datetime.now(KST).isoformat()
            goal.feedback_history.append({
                "type": "failed", "reason": reason,
                "ts": datetime.now(KST).isoformat(),
            })
            self._save_goals()

    # ── AI 계획 생성 ────────────────────────────────

    async def generate_plan(self, goal: Goal) -> list[PlanStep]:
        """AI가 목표를 분석하고 실행 계획을 생성"""
        if not self._ai_think:
            logger.warning("[planner] No AI function provided")
            return []

        existing_plan = ""
        if goal.plan:
            existing_plan = "\n".join(
                f"  {i+1}. [{s.status.value}] {s.description} ({s.method})"
                + (f" → {s.result[:100]}" if s.result else "")
                for i, s in enumerate(goal.plan)
            )

        feedback = ""
        if goal.feedback_history:
            recent = goal.feedback_history[-5:]
            feedback = "\n".join(f"  - [{f.get('type')}] {f.get('result', f.get('reason', ''))[:150]}"
                                 for f in recent)

        response = await self._ai_think(
            system_prompt="""당신은 전략적 계획 수립 AI입니다. 목표를 분석하고 구체적 실행 계획을 세웁니다.

각 스텝의 method는 다음 중 하나:
- research: 웹 검색/시장 조사/데이터 수집
- propose: 파트너에게 제안/승인 요청
- build: 코드 작성/서비스 구축 (Claude Code 활용)
- measure: 결과 측정/데이터 분석
- communicate: 슬랙으로 보고/소통

규칙:
- 3-7개 스텝으로 구성 (너무 세분화하지 말 것)
- 각 스텝은 하나의 사이클(2분)에 완료 가능한 크기
- 이전 계획의 피드백을 반영할 것
- 측정 가능한 스텝을 포함할 것

JSON 배열로만 응답:
[{"description": "스텝 설명", "method": "research|propose|build|measure|communicate"}]""",
            user_prompt=f"""목표: {goal.title}
설명: {goal.description}
성공 기준: {goal.success_criteria or '미정'}
우선순위: {goal.priority}/5
재계획 횟수: {goal.replan_count}

{"기존 계획:" + chr(10) + existing_plan if existing_plan else "새 계획 필요"}
{"피드백 이력:" + chr(10) + feedback if feedback else "첫 계획"}""",
        )

        try:
            clean = response.strip()
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            steps_data = json.loads(clean)
            steps = [
                PlanStep(description=s["description"], method=s["method"])
                for s in steps_data
            ]
            goal.plan = steps
            goal.current_step_index = 0
            goal.updated_at = datetime.now(KST).isoformat()
            self._save_goals()
            logger.info(f"[planner] Plan generated for '{goal.title}': {len(steps)} steps")
            return steps
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"[planner] Plan generation parse error: {e}")
            return []

    # ── 스텝 실행 관리 ──────────────────────────────

    def start_step(self, goal: Goal, step: PlanStep):
        step.status = PlanStepStatus.IN_PROGRESS
        step.started_at = datetime.now(KST).isoformat()
        self._save_goals()

    def complete_step(self, goal: Goal, step: PlanStep, result: str):
        step.status = PlanStepStatus.COMPLETED
        step.result = result[:500]
        step.completed_at = datetime.now(KST).isoformat()
        goal.updated_at = datetime.now(KST).isoformat()
        self._save_goals()

    def fail_step(self, goal: Goal, step: PlanStep, reason: str):
        step.status = PlanStepStatus.FAILED
        step.result = f"FAILED: {reason[:300]}"
        step.completed_at = datetime.now(KST).isoformat()
        self._save_goals()

    # ── 피드백 & 재계획 ────────────────────────────

    async def evaluate_and_replan(self, goal: Goal) -> bool:
        """목표 진행 평가 → 필요시 재계획. 재계획했으면 True."""
        if not self._ai_think:
            return False

        plan_summary = "\n".join(
            f"  {i+1}. [{s.status.value}] {s.description} → {s.result[:100] if s.result else '미실행'}"
            for i, s in enumerate(goal.plan)
        )

        response = await self._ai_think(
            system_prompt="""목표 진행 상황을 평가하고 재계획이 필요한지 판단하세요.

JSON 응답:
{
    "assessment": "현재 진행 상태 평가 (2줄)",
    "on_track": true/false,
    "needs_replan": true/false,
    "replan_reason": "재계획 사유 (needs_replan=true일 때만)",
    "goal_should_complete": true/false,
    "goal_should_fail": true/false,
    "fail_reason": "실패 사유 (goal_should_fail=true일 때만)"
}""",
            user_prompt=f"""목표: {goal.title}
설명: {goal.description}
성공 기준: {goal.success_criteria or '미정'}
진행률: {goal.progress_pct()}%
재계획 횟수: {goal.replan_count}

계획 및 결과:
{plan_summary}""",
        )

        try:
            clean = response.strip()
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            result = json.loads(clean)

            goal.feedback_history.append({
                "type": "evaluation",
                "assessment": result.get("assessment", ""),
                "on_track": result.get("on_track"),
                "ts": datetime.now(KST).isoformat(),
            })

            if result.get("goal_should_complete"):
                self.complete_goal(goal.id, result.get("assessment", ""))
                return False

            if result.get("goal_should_fail"):
                self.fail_goal(goal.id, result.get("fail_reason", ""))
                return False

            if result.get("needs_replan") and goal.replan_count < 5:
                goal.replan_count += 1
                goal.feedback_history.append({
                    "type": "replan",
                    "reason": result.get("replan_reason", ""),
                    "ts": datetime.now(KST).isoformat(),
                })
                await self.generate_plan(goal)
                return True

            self._save_goals()
            return False

        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"[planner] Evaluation parse error: {e}")
            return False

    # ── 다음 할 일 결정 ────────────────────────────

    def pick_next_action(self) -> Optional[tuple[Goal, PlanStep]]:
        """우선순위 기반으로 다음 실행할 (goal, step) 반환"""
        needs_plan = []
        for goal in self.get_active_goals():
            # 계획이 없는 목표 → 계획 생성 필요 (우선 수집)
            if not goal.plan:
                needs_plan.append(goal)
                continue

            step = goal.next_pending_step()
            if step:
                return goal, step

            # 모든 스텝 완료/실패 → 평가 필요
            if goal.is_done():
                return goal, None  # None step = 평가 필요

        # 계획 없는 목표가 있으면 첫 번째를 반환 (plan 생성 트리거)
        if needs_plan:
            return needs_plan[0], None

        return None

    # ── 상태 요약 ──────────────────────────────────

    def get_status_summary(self) -> str:
        active = self.get_active_goals()
        if not active:
            return "활성 목표 없음"

        lines = []
        for g in active:
            step = g.next_pending_step()
            next_action = f"→ {step.description}" if step else "→ 평가 필요"
            lines.append(f"[P{g.priority}] {g.title} ({g.progress_pct()}%) {next_action}")
        return "\n".join(lines)
