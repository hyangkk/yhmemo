"""
제안 라이프사이클 관리 (Proposal Lifecycle)

제안 → 승인 → 실행 → 측정 → 피드백

슬랙에서 제안을 보내고, 파트너가 이모지로 승인/거절하면
자동으로 실행하고, 결과를 측정하고, 피드백을 기록한다.
"""

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Optional

logger = logging.getLogger("proposal_lifecycle")

KST = timezone(timedelta(hours=9))
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")


class ProposalState(str, Enum):
    PROPOSED = "proposed"       # 슬랙에 제안됨, 승인 대기
    APPROVED = "approved"       # ✅ 승인됨, 실행 대기
    REJECTED = "rejected"       # ❌ 거절됨
    EXECUTING = "executing"     # 실행 중
    MEASURING = "measuring"     # 결과 측정 중
    COMPLETED = "completed"     # 완료
    FAILED = "failed"           # 실행 실패


@dataclass
class Proposal:
    id: str
    title: str
    content: str
    proposal_type: str  # revenue, growth, capability, partnership, insight
    action_needed: str
    potential_impact: str
    urgency: str  # high, medium, low

    state: ProposalState = ProposalState.PROPOSED
    slack_ts: str = ""          # 슬랙 메시지 timestamp (승인 추적용)
    slack_channel: str = ""

    # 실행 관련
    execution_plan: str = ""    # 실행 계획 (승인 후 생성)
    execution_result: str = ""
    goal_id: str = ""           # 연결된 Goal ID

    # 측정 관련
    metrics_before: dict = field(default_factory=dict)
    metrics_after: dict = field(default_factory=dict)
    measurement_summary: str = ""

    # 피드백
    feedback: str = ""
    lessons_learned: str = ""

    # 타임스탬프
    created_at: str = ""
    approved_at: str = ""
    executed_at: str = ""
    measured_at: str = ""
    completed_at: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "content": self.content,
            "proposal_type": self.proposal_type,
            "action_needed": self.action_needed,
            "potential_impact": self.potential_impact,
            "urgency": self.urgency,
            "state": self.state.value,
            "slack_ts": self.slack_ts,
            "slack_channel": self.slack_channel,
            "execution_plan": self.execution_plan,
            "execution_result": self.execution_result,
            "goal_id": self.goal_id,
            "metrics_before": self.metrics_before,
            "metrics_after": self.metrics_after,
            "measurement_summary": self.measurement_summary,
            "feedback": self.feedback,
            "lessons_learned": self.lessons_learned,
            "created_at": self.created_at,
            "approved_at": self.approved_at,
            "executed_at": self.executed_at,
            "measured_at": self.measured_at,
            "completed_at": self.completed_at,
        }

    @staticmethod
    def from_dict(d: dict) -> "Proposal":
        return Proposal(
            id=d["id"],
            title=d["title"],
            content=d.get("content", ""),
            proposal_type=d.get("proposal_type", "insight"),
            action_needed=d.get("action_needed", ""),
            potential_impact=d.get("potential_impact", ""),
            urgency=d.get("urgency", "medium"),
            state=ProposalState(d.get("state", "proposed")),
            slack_ts=d.get("slack_ts", ""),
            slack_channel=d.get("slack_channel", ""),
            execution_plan=d.get("execution_plan", ""),
            execution_result=d.get("execution_result", ""),
            goal_id=d.get("goal_id", ""),
            metrics_before=d.get("metrics_before", {}),
            metrics_after=d.get("metrics_after", {}),
            measurement_summary=d.get("measurement_summary", ""),
            feedback=d.get("feedback", ""),
            lessons_learned=d.get("lessons_learned", ""),
            created_at=d.get("created_at", ""),
            approved_at=d.get("approved_at", ""),
            executed_at=d.get("executed_at", ""),
            measured_at=d.get("measured_at", ""),
            completed_at=d.get("completed_at", ""),
        )


# 승인 이모지 매핑
APPROVE_REACTIONS = {"white_check_mark", "heavy_check_mark", "thumbsup", "+1", "rocket"}
REJECT_REACTIONS = {"x", "thumbsdown", "-1", "no_entry"}


class ProposalLifecycle:
    """제안 라이프사이클 관리"""

    def __init__(self, ai_think_fn=None, slack_client=None):
        self._proposals_file = os.path.join(DATA_DIR, "proposals.json")
        self._proposals: list[Proposal] = self._load()
        self._ai_think = ai_think_fn
        self._slack = slack_client
        os.makedirs(DATA_DIR, exist_ok=True)

    # ── 영속성 ──────────────────────────────────────

    def _load(self) -> list[Proposal]:
        try:
            with open(self._proposals_file, "r", encoding="utf-8") as f:
                data = json.loads(f.read())
            return [Proposal.from_dict(p) for p in data]
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def _save(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(self._proposals_file, "w", encoding="utf-8") as f:
            f.write(json.dumps(
                [p.to_dict() for p in self._proposals[-100:]],  # 최근 100개 유지
                ensure_ascii=False, indent=2,
            ))

    # ── 1. 제안 생성 & 슬랙 전송 ────────────────────

    async def propose(self, title: str, content: str, proposal_type: str,
                      action_needed: str, potential_impact: str,
                      urgency: str = "medium") -> Optional[Proposal]:
        """제안을 생성하고 슬랙에 전송 (승인 이모지 대기)"""
        now = datetime.now(KST)
        proposal = Proposal(
            id=f"prop_{int(now.timestamp())}",
            title=title,
            content=content,
            proposal_type=proposal_type,
            action_needed=action_needed,
            potential_impact=potential_impact,
            urgency=urgency,
            created_at=now.isoformat(),
        )

        # 슬랙에 전송
        if self._slack:
            type_emoji = {
                "revenue": "💰", "growth": "🚀", "capability": "🔧",
                "partnership": "🤝", "insight": "💡",
            }
            emoji = type_emoji.get(proposal_type, "💡")
            urgency_tag = " 🔴" if urgency == "high" else ""

            msg = (
                f"{emoji} *제안{urgency_tag}*\n\n"
                f"*{title}*\n\n"
                f"{content}\n\n"
                f"📌 *다음 단계:* {action_needed}\n"
                f"📈 *예상 임팩트:* {potential_impact}\n\n"
                f"_✅ 승인 | ❌ 거절 — 이모지로 응답해주세요_"
            )

            try:
                result = await self._slack.send_message("ai-agents-general", msg)
                proposal.slack_ts = result.get("ts", "")
                proposal.slack_channel = "ai-agents-general"
                logger.info(f"[proposal] Sent: '{title}' (ts={proposal.slack_ts})")
            except Exception as e:
                logger.error(f"[proposal] Failed to send: {e}")
                return None

        self._proposals.append(proposal)
        self._save()
        return proposal

    # ── 2. 승인/거절 처리 ────────────────────────────

    def handle_reaction(self, reaction: str, message_ts: str) -> Optional[Proposal]:
        """슬랙 이모지 반응으로 제안 승인/거절. 상태 변경된 제안 반환."""
        proposal = self._find_by_ts(message_ts)
        if not proposal or proposal.state != ProposalState.PROPOSED:
            return None

        if reaction in APPROVE_REACTIONS:
            proposal.state = ProposalState.APPROVED
            proposal.approved_at = datetime.now(KST).isoformat()
            self._save()
            logger.info(f"[proposal] Approved: '{proposal.title}'")
            return proposal

        if reaction in REJECT_REACTIONS:
            proposal.state = ProposalState.REJECTED
            proposal.feedback = f"파트너가 거절 (reaction: {reaction})"
            self._save()
            logger.info(f"[proposal] Rejected: '{proposal.title}'")
            return proposal

        return None

    # ── 3. 실행 ──────────────────────────────────────

    async def execute(self, proposal: Proposal, goal_planner=None) -> bool:
        """승인된 제안을 실행. 성공하면 True."""
        if proposal.state != ProposalState.APPROVED:
            return False

        proposal.state = ProposalState.EXECUTING
        self._save()

        # Goal로 변환하여 체계적 추적
        if goal_planner:
            goal = goal_planner.add_goal(
                title=proposal.title,
                description=f"{proposal.content}\n\n액션: {proposal.action_needed}",
                priority=1 if proposal.urgency == "high" else 2 if proposal.urgency == "medium" else 3,
                success_criteria=proposal.potential_impact,
            )
            proposal.goal_id = goal.id

            # 계획 생성
            await goal_planner.generate_plan(goal)

            if self._slack:
                plan_text = "\n".join(
                    f"  {i+1}. {s.description} ({s.method})"
                    for i, s in enumerate(goal.plan)
                )
                await self._slack.send_message(
                    "ai-agents-general",
                    f"🎯 *'{proposal.title}' 실행 계획*\n\n{plan_text}\n\n_자동으로 실행을 시작합니다._",
                )

        proposal.executed_at = datetime.now(KST).isoformat()
        self._save()
        return True

    # ── 4. 측정 ──────────────────────────────────────

    async def measure(self, proposal: Proposal) -> str:
        """실행 결과를 측정하고 요약 반환"""
        if not self._ai_think:
            return ""

        proposal.state = ProposalState.MEASURING
        self._save()

        response = await self._ai_think(
            system_prompt="""제안의 실행 결과를 측정/평가하세요.

JSON 응답:
{
    "success": true/false,
    "summary": "결과 요약 (2-3줄)",
    "metrics": {"key": "value"},
    "lessons": "교훈/배운 점",
    "next_action": "후속 조치 (있으면)"
}""",
            user_prompt=f"""제안: {proposal.title}
내용: {proposal.content}
예상 임팩트: {proposal.potential_impact}
실행 결과: {proposal.execution_result[:500] if proposal.execution_result else '결과 데이터 없음'}""",
        )

        try:
            clean = response.strip()
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            result = json.loads(clean)

            proposal.measurement_summary = result.get("summary", "")
            proposal.metrics_after = result.get("metrics", {})
            proposal.lessons_learned = result.get("lessons", "")

            if result.get("success"):
                proposal.state = ProposalState.COMPLETED
                proposal.completed_at = datetime.now(KST).isoformat()
            else:
                proposal.state = ProposalState.FAILED
                proposal.feedback = result.get("summary", "측정 결과 실패")

            proposal.measured_at = datetime.now(KST).isoformat()
            self._save()
            return proposal.measurement_summary

        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"[proposal] Measurement parse error: {e}")
            proposal.state = ProposalState.COMPLETED
            proposal.measured_at = datetime.now(KST).isoformat()
            self._save()
            return ""

    # ── 조회 ────────────────────────────────────────

    def _find_by_ts(self, ts: str) -> Optional[Proposal]:
        for p in self._proposals:
            if p.slack_ts == ts:
                return p
        return None

    def get_pending_approvals(self) -> list[Proposal]:
        return [p for p in self._proposals if p.state == ProposalState.PROPOSED]

    def get_approved(self) -> list[Proposal]:
        return [p for p in self._proposals if p.state == ProposalState.APPROVED]

    def get_executing(self) -> list[Proposal]:
        return [p for p in self._proposals if p.state == ProposalState.EXECUTING]

    def get_recent_completed(self, n: int = 10) -> list[Proposal]:
        completed = [p for p in self._proposals if p.state in (ProposalState.COMPLETED, ProposalState.FAILED)]
        return completed[-n:]

    def get_stats(self) -> dict:
        """전체 제안 통계"""
        total = len(self._proposals)
        by_state = {}
        for p in self._proposals:
            by_state[p.state.value] = by_state.get(p.state.value, 0) + 1
        return {
            "total": total,
            "by_state": by_state,
            "approval_rate": (
                by_state.get("approved", 0) + by_state.get("executing", 0) +
                by_state.get("completed", 0)
            ) / max(1, total) * 100,
        }
