"""
에이전트 평가 시스템 (Agent Evaluator) — Level 5 성과 평가 + 해고 + 재생성

마스터(ProactiveAgent)가 매일/주기적으로:
  1. 모든 에이전트의 성과를 측정
  2. 등급(A~F) 부여
  3. 부진 에이전트 → 코드 수정 or 폐기 후 재생성
  4. 우수 에이전트 → 역할 확대/복제
  5. 전체 조직 구조 최적화

평가 기준:
  - 사이클 성공률
  - 위임 완수율
  - 슬랙 전송 빈도/품질
  - 목표 기여도
  - 에러 발생률
"""

import json
import logging
import os
from datetime import datetime, timezone, timedelta

from integrations.slack_client import SlackClient

logger = logging.getLogger("agent_evaluator")

KST = timezone(timedelta(hours=9))
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")


def _now() -> datetime:
    return datetime.now(KST)


class AgentEvaluator:
    """에이전트 성과 평가자 — 마스터의 인사 시스템"""

    def __init__(self, agent_factory=None, task_delegation=None, ai_think_fn=None):
        self._factory = agent_factory
        self._delegation = task_delegation
        self._ai_think = ai_think_fn
        self._eval_file = os.path.join(DATA_DIR, "agent_evaluations.json")
        self._evals = self._load()
        os.makedirs(DATA_DIR, exist_ok=True)

    def _load(self) -> dict:
        try:
            with open(self._eval_file, "r", encoding="utf-8") as f:
                return json.loads(f.read())
        except (FileNotFoundError, json.JSONDecodeError):
            return {
                "evaluations": [],  # [{date, agent, grade, metrics, action_taken}]
                "org_reviews": [],  # [{date, summary, changes}]
            }

    def _save(self):
        if len(self._evals["evaluations"]) > 500:
            self._evals["evaluations"] = self._evals["evaluations"][-500:]
        if len(self._evals["org_reviews"]) > 50:
            self._evals["org_reviews"] = self._evals["org_reviews"][-50:]
        with open(self._eval_file, "w", encoding="utf-8") as f:
            f.write(json.dumps(self._evals, ensure_ascii=False, indent=2))

    # ── 개별 에이전트 평가 ────────────────────────────

    def evaluate_agent(self, agent_name: str) -> dict:
        """단일 에이전트 성과 측정 → 등급 부여"""
        metrics = self._collect_metrics(agent_name)
        grade = self._compute_grade(metrics)

        evaluation = {
            "date": _now().strftime("%Y-%m-%d"),
            "timestamp": _now().isoformat(),
            "agent": agent_name,
            "grade": grade,
            "metrics": metrics,
            "action_taken": "",
        }

        self._evals["evaluations"].append(evaluation)
        self._save()

        logger.info(f"[evaluator] {agent_name}: grade={grade}, score={metrics.get('composite_score', 0):.2f}")
        return evaluation

    def _collect_metrics(self, agent_name: str) -> dict:
        """에이전트 메트릭 수집"""
        metrics = {
            "cycle_success_rate": 0.5,
            "delegation_reliability": 0.5,
            "error_rate": 0.0,
            "composite_score": 0.5,
        }

        # 팩토리에서 사이클 성과
        if self._factory:
            info = self._factory._registry.get("agents", {}).get(agent_name, {})
            perf = info.get("performance", {})
            cycles = perf.get("cycles", 0)
            if cycles > 0:
                metrics["cycle_success_rate"] = perf.get("successes", 0) / cycles
                metrics["error_rate"] = perf.get("failures", 0) / cycles
            metrics["factory_score"] = perf.get("score", 0.5)
            metrics["total_cycles"] = cycles

        # 위임 성과
        if self._delegation:
            reliability = self._delegation.get_agent_reliability(agent_name)
            metrics["delegation_reliability"] = reliability

        # 종합 점수 (가중 평균)
        metrics["composite_score"] = (
            metrics["cycle_success_rate"] * 0.4 +
            metrics["delegation_reliability"] * 0.3 +
            (1.0 - metrics["error_rate"]) * 0.3
        )

        return metrics

    def _compute_grade(self, metrics: dict) -> str:
        """종합 점수 → 등급"""
        score = metrics.get("composite_score", 0.5)
        if score >= 0.9:
            return "A"
        elif score >= 0.7:
            return "B"
        elif score >= 0.5:
            return "C"
        elif score >= 0.3:
            return "D"
        else:
            return "F"

    # ── 전체 에이전트 평가 ────────────────────────────

    async def evaluate_all(self) -> dict:
        """모든 에이전트 평가 → 조직 리뷰"""
        evaluations = {}

        # 정적 에이전트 (message bus에 등록된)
        if self._delegation and self._delegation._bus:
            for name in self._delegation._bus._handlers:
                evaluations[name] = self.evaluate_agent(name)

        # 동적 에이전트
        if self._factory:
            for name in self._factory.get_active_agents():
                if name not in evaluations:
                    evaluations[name] = self.evaluate_agent(name)

        # 조직 리뷰 생성
        review = await self._generate_org_review(evaluations)
        return review

    async def _generate_org_review(self, evaluations: dict) -> dict:
        """AI가 조직 전체 리뷰 생성"""
        review = {
            "date": _now().strftime("%Y-%m-%d"),
            "timestamp": _now().isoformat(),
            "agent_count": len(evaluations),
            "grades": {},
            "underperformers": [],
            "top_performers": [],
            "recommendations": [],
            "actions_taken": [],
        }

        for name, ev in evaluations.items():
            grade = ev.get("grade", "C")
            review["grades"][name] = grade
            score = ev.get("metrics", {}).get("composite_score", 0.5)

            if grade in ("D", "F"):
                review["underperformers"].append({
                    "name": name, "grade": grade, "score": score,
                })
            elif grade == "A":
                review["top_performers"].append({
                    "name": name, "grade": grade, "score": score,
                })

        # AI 리뷰 (선택적)
        if self._ai_think and evaluations:
            try:
                summary_data = {
                    name: {
                        "grade": ev.get("grade"),
                        "score": ev.get("metrics", {}).get("composite_score"),
                        "cycles": ev.get("metrics", {}).get("total_cycles", 0),
                    }
                    for name, ev in evaluations.items()
                }

                response = await self._ai_think(
                    system_prompt="""에이전트 조직 리뷰를 수행하라.
JSON: {"recommendations": ["추천1", ...], "should_retire": ["에이전트명", ...], "should_create": [{"name": "이름", "purpose": "목적"}]}""",
                    user_prompt=f"에이전트 평가 결과:\n{json.dumps(summary_data, ensure_ascii=False)}",
                )

                import re
                match = re.search(r"\{.*\}", response, re.DOTALL)
                if match:
                    parsed = json.loads(match.group(0))
                    review["recommendations"] = parsed.get("recommendations", [])
                    review["should_retire"] = parsed.get("should_retire", [])
                    review["should_create"] = parsed.get("should_create", [])
            except Exception as e:
                logger.error(f"[evaluator] AI review failed: {e}")

        self._evals["org_reviews"].append(review)
        self._save()
        return review

    # ── 자동 인사 조치 ────────────────────────────────

    async def enforce_actions(self, review: dict) -> list[dict]:
        """리뷰 결과에 따라 자동 조치 실행

        Returns: list of {action, agent, result}
        """
        actions = []

        # 1. 부진 동적 에이전트 폐기
        for agent_info in review.get("underperformers", []):
            name = agent_info["name"]
            grade = agent_info["grade"]

            # 정적 에이전트는 폐기 불가 (동적만)
            if not self._factory:
                continue
            if name not in self._factory.get_active_agents():
                continue

            # F등급: 즉시 폐기
            if grade == "F":
                retired = await self._factory.retire_agent(name, reason=f"성과 부진 (F등급)")
                actions.append({"action": "retire", "agent": name, "result": "폐기 완료" if retired else "폐기 실패"})

            # D등급: 재생성 시도
            elif grade == "D":
                old_info = self._factory._registry.get("agents", {}).get(name, {})
                new_spec = {
                    "purpose": old_info.get("purpose", ""),
                    "description": f"재생성: {old_info.get('description', '')} — 이전 D등급으로 코드 개선",
                    "slack_channel": old_info.get("slack_channel", SlackClient.CHANNEL_LOGS),
                    "loop_interval": old_info.get("loop_interval", 300),
                }
                result = await self._factory.rebuild_agent(name, new_spec)
                actions.append({
                    "action": "rebuild",
                    "agent": name,
                    "result": "재생성 성공" if result.get("success") else f"재생성 실패: {result.get('reason')}",
                })

        # 2. AI 추천 새 에이전트 생성
        for spec in review.get("should_create", []):
            if self._factory and self._factory.get_agent_count() < 10:
                result = await self._factory.create_agent(spec)
                if result.get("success"):
                    await self._factory.start_agent(result["agent_name"])
                    actions.append({"action": "create", "agent": result["agent_name"], "result": "생성+시작"})

        # 3. AI 추천 폐기
        for name in review.get("should_retire", []):
            if self._factory and name in self._factory.get_active_agents():
                await self._factory.retire_agent(name, reason="AI 조직 리뷰 추천")
                actions.append({"action": "retire", "agent": name, "result": "AI 추천 폐기"})

        # 기록
        if actions:
            review["actions_taken"] = actions
            self._save()

        return actions

    # ── 트렌드 분석 ──────────────────────────────────

    def get_agent_trend(self, agent_name: str, days: int = 7) -> list[dict]:
        """에이전트의 최근 평가 추세"""
        cutoff = (_now() - timedelta(days=days)).strftime("%Y-%m-%d")
        return [
            e for e in self._evals["evaluations"]
            if e.get("agent") == agent_name and e.get("date", "") >= cutoff
        ]

    def get_org_health(self) -> dict:
        """전체 조직 건강도"""
        recent = self._evals["evaluations"][-50:]
        if not recent:
            return {"health": "unknown", "avg_score": 0, "agent_count": 0}

        scores = [e.get("metrics", {}).get("composite_score", 0.5) for e in recent]
        avg = sum(scores) / len(scores)

        grade_counts = {"A": 0, "B": 0, "C": 0, "D": 0, "F": 0}
        for e in recent:
            g = e.get("grade", "C")
            grade_counts[g] = grade_counts.get(g, 0) + 1

        health = "excellent" if avg >= 0.8 else "good" if avg >= 0.6 else "fair" if avg >= 0.4 else "poor"

        return {
            "health": health,
            "avg_score": round(avg, 3),
            "agent_count": len(set(e.get("agent") for e in recent)),
            "grade_distribution": grade_counts,
        }

    def get_summary(self) -> str:
        health = self.get_org_health()
        return (
            f"조직 건강도: {health['health']} (평균 {health['avg_score']:.2f})\n"
            f"에이전트 {health['agent_count']}개 | "
            f"등급분포: A={health['grade_distribution'].get('A', 0)} "
            f"B={health['grade_distribution'].get('B', 0)} "
            f"C={health['grade_distribution'].get('C', 0)} "
            f"D={health['grade_distribution'].get('D', 0)} "
            f"F={health['grade_distribution'].get('F', 0)}"
        )
