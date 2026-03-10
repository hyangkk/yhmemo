"""
에이전트 인사관리 (HR) 시스템

매일 전체 에이전트를 대상으로 인사평가를 실시:
  1. 에이전트별 성과 데이터 수집 (agent_tracker 기반)
  2. AI가 종합 평가 + 등급 부여 (S/A/B/C/D/F)
  3. 연봉 조정 (인상/삭감)
  4. 직급 승진/강등
  5. 인사 조치 (경고, 해고, 보상 등)

연봉: 3,000만원에서 시작, 오케스트레이터가 조정
직급: 사원 → 주임 → 대리 → 과장 → 차장 → 부장 → 이사 → 상무
"""

import json
import logging
import os
from datetime import datetime, timezone, timedelta, date

from core import agent_tracker

logger = logging.getLogger("agent_hr")

KST = timezone(timedelta(hours=9))
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
HR_FILE = os.path.join(DATA_DIR, "agent_hr.json")

# 직급 체계 (순서대로 승진)
POSITIONS = ["인턴", "팀원", "팀장", "본부장", "이사"]

# 등급별 연봉 조정률 (만원)
SALARY_ADJUSTMENTS = {
    "S": 500,   # +500만원
    "A": 200,   # +200만원
    "B": 100,   # +100만원
    "C": 0,     # 동결
    "D": -100,  # -100만원
    "F": -300,  # -300만원
}

# 기본 에이전트 목록 (정적 에이전트)
CORE_AGENTS = {
    "orchestrator": {"display_name": "오케스트레이터", "role": "CEO", "position": "CEO"},
    "proactive": {"display_name": "프로액티브", "role": "자율운영 마스터"},
    "collector": {"display_name": "콜렉터", "role": "정보 수집"},
    "curator": {"display_name": "큐레이터", "role": "정보 선별"},
    "sentiment": {"display_name": "센티멘트", "role": "감성 분석"},
    "investment": {"display_name": "인베스트먼트", "role": "시장 정보"},
    "task_board": {"display_name": "태스크보드", "role": "작업 관리"},
    "diary_quote": {"display_name": "다이어리", "role": "생각일기"},
    "quote": {"display_name": "명언러", "role": "명언 생성"},
    "fortune": {"display_name": "포춘", "role": "운세 생성"},
    "message_bus": {"display_name": "메시지버스", "role": "통신 관리"},
}


def _now() -> datetime:
    return datetime.now(KST)


class AgentHR:
    """에이전트 인사관리 시스템"""

    def __init__(self, ai_think_fn=None, supabase_client=None):
        self._ai_think = ai_think_fn
        self._supabase = supabase_client
        self._hr_data = self._load()
        os.makedirs(DATA_DIR, exist_ok=True)

    # ── 데이터 로드/저장 ─────────────────────────────

    def _load(self) -> dict:
        try:
            with open(HR_FILE, "r", encoding="utf-8") as f:
                return json.loads(f.read())
        except (FileNotFoundError, json.JSONDecodeError):
            return {
                "agents": {},           # agent_name → 프로필
                "evaluations": [],      # 평가 이력 (최근 500건)
                "actions": [],          # 인사 조치 이력 (최근 200건)
                "last_eval_date": "",   # 마지막 평가 날짜
            }

    def _save(self):
        if len(self._hr_data.get("evaluations", [])) > 500:
            self._hr_data["evaluations"] = self._hr_data["evaluations"][-500:]
        if len(self._hr_data.get("actions", [])) > 200:
            self._hr_data["actions"] = self._hr_data["actions"][-200:]
        with open(HR_FILE, "w", encoding="utf-8") as f:
            f.write(json.dumps(self._hr_data, ensure_ascii=False, indent=2))

    # ── 에이전트 등록 ────────────────────────────────

    def ensure_registered(self, agent_name: str, display_name: str = "", role: str = ""):
        """에이전트가 HR에 등록되어 있는지 확인, 없으면 신규 입사 처리"""
        agents = self._hr_data.setdefault("agents", {})
        if agent_name not in agents:
            info = CORE_AGENTS.get(agent_name, {})
            default_position = info.get("position", "팀원")
            agents[agent_name] = {
                "display_name": display_name or info.get("display_name", agent_name),
                "role": role or info.get("role", "일반"),
                "position": default_position,
                "salary": 3000,       # 3천만원
                "grade": "C",         # 초기 등급
                "hire_date": _now().strftime("%Y-%m-%d"),
                "status": "active",   # active/warning/probation/fired
                "warning_count": 0,
                "total_evaluations": 0,
                "consecutive_low": 0,
                "consecutive_high": 0,
                "best_grade": "C",
                "worst_grade": "C",
            }
            self._save()
            logger.info(f"[HR] 신규 입사: {agent_name} (연봉 3,000만원)")
        return agents[agent_name]

    def get_profile(self, agent_name: str) -> dict | None:
        return self._hr_data.get("agents", {}).get(agent_name)

    # ── 재직 기간 계산 ───────────────────────────────

    def get_tenure(self, agent_name: str) -> dict:
        """재직 기간 계산"""
        profile = self.get_profile(agent_name)
        if not profile:
            return {"days": 0, "text": "미등록"}

        hire = datetime.strptime(profile["hire_date"], "%Y-%m-%d").date()
        today = _now().date()
        delta = today - hire
        days = delta.days

        if days == 0:
            text = "입사 당일"
        elif days < 30:
            text = f"{days}일"
        elif days < 365:
            months = days // 30
            text = f"{months}개월"
        else:
            years = days // 365
            months = (days % 365) // 30
            text = f"{years}년 {months}개월" if months else f"{years}년"

        return {"days": days, "text": text}

    # ── 성과 데이터 수집 ──────────────────────────────

    def _collect_metrics(self, agent_name: str) -> dict:
        """agent_tracker에서 성과 데이터 수집"""
        tracker_data = agent_tracker.get_summary_for_report()
        agent_info = tracker_data.get("agents", {}).get(agent_name, {})

        metrics = {
            "uptime_pct": agent_info.get("uptime_pct", 0.0),
            "cycle_count": agent_info.get("cycles", 0),
            "error_count": agent_info.get("errors", 0),
            "status": agent_info.get("status", "unknown"),
        }

        cycles = metrics["cycle_count"]
        errors = metrics["error_count"]
        if cycles > 0:
            metrics["error_rate"] = round(errors / cycles, 4)
            metrics["success_rate"] = round(1.0 - metrics["error_rate"], 4)
        else:
            metrics["error_rate"] = 0.0
            metrics["success_rate"] = 0.0

        # 종합 점수 계산 (0~1)
        uptime_score = metrics["uptime_pct"] / 100.0
        success_score = metrics["success_rate"]
        error_penalty = min(1.0, metrics["error_rate"] * 5)  # 에러 20% 이상이면 0점

        metrics["composite_score"] = round(
            uptime_score * 0.4 +
            success_score * 0.35 +
            (1.0 - error_penalty) * 0.25,
            4
        )

        return metrics

    def _compute_grade(self, score: float) -> str:
        """점수 → 등급"""
        if score >= 0.95:
            return "S"
        elif score >= 0.85:
            return "A"
        elif score >= 0.7:
            return "B"
        elif score >= 0.5:
            return "C"
        elif score >= 0.3:
            return "D"
        else:
            return "F"

    # ── 개별 평가 ────────────────────────────────────

    def evaluate_agent(self, agent_name: str) -> dict:
        """단일 에이전트 인사평가"""
        self.ensure_registered(agent_name)
        profile = self._hr_data["agents"][agent_name]
        metrics = self._collect_metrics(agent_name)
        grade = self._compute_grade(metrics["composite_score"])

        # 연속 등급 추적
        if grade in ("D", "F"):
            profile["consecutive_low"] = profile.get("consecutive_low", 0) + 1
            profile["consecutive_high"] = 0
        elif grade in ("S", "A"):
            profile["consecutive_high"] = profile.get("consecutive_high", 0) + 1
            profile["consecutive_low"] = 0
        else:
            profile["consecutive_low"] = 0
            profile["consecutive_high"] = 0

        # 최고/최저 등급 갱신
        grade_order = {"S": 6, "A": 5, "B": 4, "C": 3, "D": 2, "F": 1}
        if grade_order.get(grade, 0) > grade_order.get(profile.get("best_grade", "C"), 0):
            profile["best_grade"] = grade
        if grade_order.get(grade, 99) < grade_order.get(profile.get("worst_grade", "C"), 99):
            profile["worst_grade"] = grade

        profile["grade"] = grade
        profile["total_evaluations"] = profile.get("total_evaluations", 0) + 1

        tenure = self.get_tenure(agent_name)

        evaluation = {
            "date": _now().strftime("%Y-%m-%d"),
            "timestamp": _now().isoformat(),
            "agent": agent_name,
            "display_name": profile["display_name"],
            "grade": grade,
            "composite_score": metrics["composite_score"],
            "metrics": metrics,
            "tenure": tenure["text"],
            "position": profile["position"],
            "salary": profile["salary"],
        }

        self._hr_data["evaluations"].append(evaluation)
        self._save()
        return evaluation

    # ── 전체 인사평가 + AI 리뷰 ───────────────────────

    async def run_daily_evaluation(self) -> dict:
        """매일 전체 에이전트 인사평가 실행"""
        today = _now().strftime("%Y-%m-%d")

        # 중복 평가 방지
        if self._hr_data.get("last_eval_date") == today:
            logger.info(f"[HR] 오늘({today}) 이미 평가 완료")
            return {"already_done": True, "date": today}

        # 모든 에이전트 평가
        evaluations = {}

        # 1. tracker에 등록된 에이전트
        tracker_data = agent_tracker.get_summary_for_report()
        for name in tracker_data.get("agents", {}):
            evaluations[name] = self.evaluate_agent(name)

        # 2. CORE_AGENTS 중 tracker에 없는 것도 등록만
        for name in CORE_AGENTS:
            if name not in evaluations:
                self.ensure_registered(name)

        # AI 종합 리뷰 + 인사 조치 결정
        review = await self._ai_review(evaluations)

        # 인사 조치 실행
        actions = self._execute_hr_actions(review, evaluations)

        self._hr_data["last_eval_date"] = today
        self._save()

        return {
            "date": today,
            "agent_count": len(evaluations),
            "evaluations": evaluations,
            "review": review,
            "actions": actions,
        }

    async def _ai_review(self, evaluations: dict) -> dict:
        """AI가 종합 평가 리뷰 + 인사 조치 결정"""
        review = {
            "summary": "",
            "salary_changes": {},     # agent → 조정액
            "promotions": [],         # 승진 대상
            "demotions": [],          # 강등 대상
            "warnings": [],           # 경고 대상
            "bonuses": [],            # 보너스 대상
            "fires": [],              # 해고 대상
            "mvp": "",                # 이달의 MVP
        }

        if not self._ai_think or not evaluations:
            # AI 없으면 규칙 기반 자동 처리
            return self._rule_based_review(evaluations)

        # 평가 데이터 요약
        eval_summary = {}
        for name, ev in evaluations.items():
            profile = self.get_profile(name) or {}
            eval_summary[name] = {
                "display_name": profile.get("display_name", name),
                "grade": ev["grade"],
                "score": ev["composite_score"],
                "position": profile.get("position", "사원"),
                "salary": profile.get("salary", 3000),
                "tenure": ev.get("tenure", ""),
                "consecutive_low": profile.get("consecutive_low", 0),
                "consecutive_high": profile.get("consecutive_high", 0),
                "warning_count": profile.get("warning_count", 0),
                "status": profile.get("status", "active"),
                "cycles": ev["metrics"].get("cycle_count", 0),
                "uptime": ev["metrics"].get("uptime_pct", 0),
                "error_rate": ev["metrics"].get("error_rate", 0),
            }

        try:
            response = await self._ai_think(
                system_prompt="""당신은 AI 에이전트 조직의 인사 담당 이사입니다.
에이전트들의 성과 평가 결과를 보고 인사 조치를 결정하세요.

규칙:
1. 연봉 조정: S등급 +500만, A등급 +200만, B등급 +100만, C등급 동결, D등급 -100만, F등급 -300만 (기본값이나 재량으로 조정 가능)
2. 승진 기준: 연속 3회 이상 A등급 이상 → 승진 추천
3. 강등 기준: 연속 3회 이상 D등급 이하 → 강등 추천
4. 경고: D등급 → 경고 1회, 경고 3회 누적 → 해고 추천
5. 해고: F등급 연속 2회 또는 경고 3회 누적 (동적 에이전트만 실제 해고 가능, 핵심 에이전트는 경고만)
6. MVP: 가장 뛰어난 성과의 에이전트 1명 선정
7. 보너스: 특별한 성과를 보인 에이전트에게 추가 연봉 보너스 가능
8. 연봉 최저 한도: 2,000만원 미만으로는 내릴 수 없음

재미있고 생동감 있게, 하지만 공정하게 평가해주세요.

JSON 응답:
{
  "summary": "전체 조직 평가 요약 (2-3문장, 재미있게)",
  "salary_changes": {"에이전트명": 조정액(만원), ...},
  "promotions": ["에이전트명"],
  "demotions": ["에이전트명"],
  "warnings": ["에이전트명"],
  "bonuses": [{"agent": "에이전트명", "amount": 100, "reason": "사유"}],
  "fires": ["에이전트명"],
  "mvp": "에이전트명",
  "comments": {"에이전트명": "개별 한줄평"}
}""",
                user_prompt=f"오늘의 에이전트 인사평가 결과:\n{json.dumps(eval_summary, ensure_ascii=False, indent=2)}",
            )

            import re
            match = re.search(r"\{.*\}", response, re.DOTALL)
            if match:
                parsed = json.loads(match.group(0))
                review["summary"] = parsed.get("summary", "")
                review["salary_changes"] = parsed.get("salary_changes", {})
                review["promotions"] = parsed.get("promotions", [])
                review["demotions"] = parsed.get("demotions", [])
                review["warnings"] = parsed.get("warnings", [])
                review["bonuses"] = parsed.get("bonuses", [])
                review["fires"] = parsed.get("fires", [])
                review["mvp"] = parsed.get("mvp", "")
                review["comments"] = parsed.get("comments", {})
        except Exception as e:
            logger.error(f"[HR] AI 리뷰 실패: {e}")
            review = self._rule_based_review(evaluations)

        return review

    def _rule_based_review(self, evaluations: dict) -> dict:
        """AI 없이 규칙 기반 리뷰"""
        review = {
            "summary": "규칙 기반 자동 평가 완료",
            "salary_changes": {},
            "promotions": [],
            "demotions": [],
            "warnings": [],
            "bonuses": [],
            "fires": [],
            "mvp": "",
            "comments": {},
        }

        best_score = 0
        best_agent = ""

        for name, ev in evaluations.items():
            grade = ev["grade"]
            profile = self.get_profile(name) or {}
            score = ev["composite_score"]

            # 연봉 조정
            review["salary_changes"][name] = SALARY_ADJUSTMENTS.get(grade, 0)

            # MVP
            if score > best_score:
                best_score = score
                best_agent = name

            # 승진
            if profile.get("consecutive_high", 0) >= 3:
                review["promotions"].append(name)

            # 강등
            if profile.get("consecutive_low", 0) >= 3:
                review["demotions"].append(name)

            # 경고
            if grade == "D":
                review["warnings"].append(name)

            # 해고 추천
            if grade == "F" and profile.get("consecutive_low", 0) >= 2:
                review["fires"].append(name)

        review["mvp"] = best_agent
        return review

    # ── 인사 조치 실행 ───────────────────────────────

    def _execute_hr_actions(self, review: dict, evaluations: dict) -> list[dict]:
        """리뷰 결과에 따른 인사 조치 실행"""
        actions = []
        agents = self._hr_data.setdefault("agents", {})

        # 1. 연봉 조정
        for name, adjustment in review.get("salary_changes", {}).items():
            if name not in agents:
                continue
            profile = agents[name]
            old_salary = profile["salary"]
            new_salary = max(2000, old_salary + adjustment)  # 최저 2천만원
            if new_salary != old_salary:
                profile["salary"] = new_salary
                direction = "인상" if adjustment > 0 else "삭감"
                action = {
                    "date": _now().strftime("%Y-%m-%d"),
                    "agent": name,
                    "type": "raise" if adjustment > 0 else "cut",
                    "description": f"연봉 {direction}: {old_salary:,}만원 → {new_salary:,}만원 ({adjustment:+,}만원)",
                    "old_value": str(old_salary),
                    "new_value": str(new_salary),
                }
                actions.append(action)
                self._hr_data["actions"].append(action)

        # 2. 보너스
        for bonus in review.get("bonuses", []):
            name = bonus.get("agent", "")
            amount = bonus.get("amount", 0)
            if name in agents and amount > 0:
                profile = agents[name]
                profile["salary"] = profile["salary"] + amount
                action = {
                    "date": _now().strftime("%Y-%m-%d"),
                    "agent": name,
                    "type": "bonus",
                    "description": f"보너스 지급: +{amount:,}만원 ({bonus.get('reason', '')})",
                    "old_value": "",
                    "new_value": str(amount),
                }
                actions.append(action)
                self._hr_data["actions"].append(action)

        # 3. 승진
        for name in review.get("promotions", []):
            if name not in agents:
                continue
            profile = agents[name]
            old_pos = profile["position"]
            if old_pos == "CEO":
                continue  # CEO는 승진 대상 아님
            pos_idx = POSITIONS.index(old_pos) if old_pos in POSITIONS else 1
            if pos_idx < len(POSITIONS) - 1:
                new_pos = POSITIONS[pos_idx + 1]
                profile["position"] = new_pos
                action = {
                    "date": _now().strftime("%Y-%m-%d"),
                    "agent": name,
                    "type": "promotion",
                    "description": f"승진: {old_pos} → {new_pos}",
                    "old_value": old_pos,
                    "new_value": new_pos,
                }
                actions.append(action)
                self._hr_data["actions"].append(action)

        # 4. 강등
        for name in review.get("demotions", []):
            if name not in agents:
                continue
            profile = agents[name]
            old_pos = profile["position"]
            if old_pos == "CEO":
                continue  # CEO는 강등 대상 아님
            pos_idx = POSITIONS.index(old_pos) if old_pos in POSITIONS else 1
            if pos_idx > 0:
                new_pos = POSITIONS[pos_idx - 1]
                profile["position"] = new_pos
                action = {
                    "date": _now().strftime("%Y-%m-%d"),
                    "agent": name,
                    "type": "demotion",
                    "description": f"강등: {old_pos} → {new_pos}",
                    "old_value": old_pos,
                    "new_value": new_pos,
                }
                actions.append(action)
                self._hr_data["actions"].append(action)

        # 5. 경고
        for name in review.get("warnings", []):
            if name not in agents:
                continue
            profile = agents[name]
            profile["warning_count"] = profile.get("warning_count", 0) + 1
            if profile["warning_count"] >= 3:
                profile["status"] = "probation"
            else:
                profile["status"] = "warning"
            action = {
                "date": _now().strftime("%Y-%m-%d"),
                "agent": name,
                "type": "warning",
                "description": f"경고 ({profile['warning_count']}회 누적)",
                "old_value": "",
                "new_value": str(profile["warning_count"]),
            }
            actions.append(action)
            self._hr_data["actions"].append(action)

        # 6. 해고 (동적 에이전트만)
        for name in review.get("fires", []):
            if name not in agents:
                continue
            if name in CORE_AGENTS:
                # 핵심 에이전트는 해고 불가 → 강력 경고로 대체
                profile = agents[name]
                profile["status"] = "probation"
                action = {
                    "date": _now().strftime("%Y-%m-%d"),
                    "agent": name,
                    "type": "probation",
                    "description": "핵심 에이전트 → 해고 대신 수습 전환",
                    "old_value": "",
                    "new_value": "probation",
                }
                actions.append(action)
            else:
                profile = agents[name]
                profile["status"] = "fired"
                action = {
                    "date": _now().strftime("%Y-%m-%d"),
                    "agent": name,
                    "type": "fired",
                    "description": f"성과 부진으로 해고 (연봉 {profile['salary']:,}만원, 직급 {profile['position']})",
                    "old_value": "active",
                    "new_value": "fired",
                }
                actions.append(action)
            self._hr_data["actions"].append(action)

        # MVP 기록
        mvp = review.get("mvp", "")
        if mvp and mvp in agents:
            agents[mvp]["last_mvp_date"] = _now().strftime("%Y-%m-%d")

        self._save()
        return actions

    # ── 수동 연봉 조정 (오케스트레이터용) ──────────────

    def adjust_salary(self, agent_name: str, amount: int, reason: str = "") -> dict:
        """연봉 수동 조정 (오케스트레이터 전용)"""
        self.ensure_registered(agent_name)
        profile = self._hr_data["agents"][agent_name]
        old_salary = profile["salary"]
        new_salary = max(2000, old_salary + amount)
        profile["salary"] = new_salary

        action = {
            "date": _now().strftime("%Y-%m-%d"),
            "agent": agent_name,
            "type": "manual_adjust",
            "description": f"수동 연봉 조정: {old_salary:,}만원 → {new_salary:,}만원 ({reason})",
            "old_value": str(old_salary),
            "new_value": str(new_salary),
        }
        self._hr_data["actions"].append(action)
        self._save()

        return {"agent": agent_name, "old_salary": old_salary, "new_salary": new_salary}

    # ── 보고서 생성 ──────────────────────────────────

    def get_hr_report(self) -> str:
        """전체 에이전트 인사 현황 보고 (슬랙 형식)"""
        agents = self._hr_data.get("agents", {})
        if not agents:
            return "등록된 에이전트가 없습니다."

        now = _now()
        lines = [f"*인사 현황 보고서* ({now.strftime('%Y-%m-%d %H:%M')} KST)\n"]

        # 총 연봉 합계
        total_salary = sum(a.get("salary", 0) for a in agents.values() if a.get("status") != "fired")
        active_count = sum(1 for a in agents.values() if a.get("status") not in ("fired",))
        lines.append(f"재직 에이전트: *{active_count}명* | 총 인건비: *{total_salary:,}만원/년*\n")

        # 등급 이모지
        grade_emoji = {"S": "💎", "A": "🏆", "B": "✅", "C": "📊", "D": "⚠️", "F": "🚨"}
        status_emoji = {"active": "🟢", "warning": "🟡", "probation": "🟠", "fired": "🔴"}

        # 정렬: 직급 → 연봉 내림차순
        def sort_key(item):
            name, info = item
            pos = info.get("position", "팀원")
            pos_idx = POSITIONS.index(pos) if pos in POSITIONS else (99 if pos == "CEO" else 0)
            return (-pos_idx, -info.get("salary", 0))

        for name, info in sorted(agents.items(), key=sort_key):
            status = info.get("status", "active")
            s_emoji = status_emoji.get(status, "⚪")
            g_emoji = grade_emoji.get(info.get("grade", "C"), "📊")

            display = info.get("display_name", name)
            position = info.get("position", "사원")
            salary = info.get("salary", 3000)
            grade = info.get("grade", "C")
            tenure = self.get_tenure(name)

            line = f"{s_emoji} *{display}* ({name})"
            lines.append(line)
            lines.append(f"   {g_emoji} 등급: {grade} | 직급: {position} | 연봉: {salary:,}만원 | 재직: {tenure['text']}")

            # 경고 표시
            warnings = info.get("warning_count", 0)
            if warnings > 0:
                lines.append(f"   ⚠️ 경고 {warnings}회 누적")

            if status == "fired":
                lines.append(f"   🔴 해고됨")

            lines.append("")

        # 최근 인사 조치
        recent_actions = self._hr_data.get("actions", [])[-5:]
        if recent_actions:
            lines.append("*최근 인사 조치*")
            for a in reversed(recent_actions):
                display = agents.get(a["agent"], {}).get("display_name", a["agent"])
                lines.append(f"  • {a['date']} {display}: {a['description']}")
            lines.append("")

        return "\n".join(lines)

    def get_agent_card(self, agent_name: str) -> str:
        """개별 에이전트 인사카드"""
        profile = self.get_profile(agent_name)
        if not profile:
            return f"'{agent_name}' 에이전트를 찾을 수 없습니다."

        tenure = self.get_tenure(agent_name)
        grade_emoji = {"S": "💎", "A": "🏆", "B": "✅", "C": "📊", "D": "⚠️", "F": "🚨"}

        lines = [
            f"*인사 카드: {profile['display_name']}* ({agent_name})",
            f"",
            f"직급: *{profile['position']}*",
            f"등급: {grade_emoji.get(profile['grade'], '📊')} *{profile['grade']}*",
            f"연봉: *{profile['salary']:,}만원*",
            f"입사일: {profile['hire_date']}",
            f"재직기간: {tenure['text']}",
            f"상태: {profile['status']}",
            f"총 평가 횟수: {profile.get('total_evaluations', 0)}회",
            f"경고 횟수: {profile.get('warning_count', 0)}회",
            f"최고 등급: {profile.get('best_grade', '-')} / 최저 등급: {profile.get('worst_grade', '-')}",
        ]

        # 최근 평가 이력
        recent_evals = [
            e for e in self._hr_data.get("evaluations", [])
            if e.get("agent") == agent_name
        ][-5:]

        if recent_evals:
            lines.append("")
            lines.append("*최근 평가 이력*")
            for e in reversed(recent_evals):
                lines.append(f"  {e['date']}: {e['grade']} (점수: {e['composite_score']:.2f})")

        # 최근 인사 조치
        recent_actions = [
            a for a in self._hr_data.get("actions", [])
            if a.get("agent") == agent_name
        ][-3:]

        if recent_actions:
            lines.append("")
            lines.append("*인사 조치 이력*")
            for a in reversed(recent_actions):
                lines.append(f"  {a['date']}: {a['description']}")

        return "\n".join(lines)

    def format_evaluation_result(self, result: dict) -> str:
        """인사평가 결과를 슬랙 메시지로 포맷"""
        if result.get("already_done"):
            return f"오늘({result['date']}) 인사평가는 이미 완료되었습니다."

        lines = [
            f"*📋 일일 인사평가 결과* ({result['date']})",
            f"평가 대상: {result['agent_count']}명\n",
        ]

        review = result.get("review", {})

        # AI 요약
        if review.get("summary"):
            lines.append(f"💬 _{review['summary']}_\n")

        # MVP
        if review.get("mvp"):
            mvp = review["mvp"]
            profile = self.get_profile(mvp) or {}
            lines.append(f"🏆 *오늘의 MVP*: {profile.get('display_name', mvp)}\n")

        # 개별 평가
        grade_emoji = {"S": "💎", "A": "🏆", "B": "✅", "C": "📊", "D": "⚠️", "F": "🚨"}
        evaluations = result.get("evaluations", {})

        for name, ev in sorted(evaluations.items(), key=lambda x: -x[1]["composite_score"]):
            g = ev["grade"]
            score = ev["composite_score"]
            profile = self.get_profile(name) or {}
            display = profile.get("display_name", name)
            emoji = grade_emoji.get(g, "📊")

            comment = review.get("comments", {}).get(name, "")
            comment_str = f" — _{comment}_" if comment else ""
            lines.append(f"{emoji} {display}: *{g}* ({score:.2f}){comment_str}")

        # 인사 조치
        actions = result.get("actions", [])
        if actions:
            lines.append("\n*인사 조치*")
            for a in actions:
                profile = self.get_profile(a["agent"]) or {}
                display = profile.get("display_name", a["agent"])
                lines.append(f"  • {display}: {a['description']}")

        return "\n".join(lines)

    def get_salary_ranking(self) -> str:
        """연봉 랭킹"""
        agents = self._hr_data.get("agents", {})
        if not agents:
            return "등록된 에이전트가 없습니다."

        active = {k: v for k, v in agents.items() if v.get("status") != "fired"}
        sorted_agents = sorted(active.items(), key=lambda x: -x[1].get("salary", 0))

        lines = ["*💰 연봉 랭킹*\n"]
        medals = ["🥇", "🥈", "🥉"]
        for i, (name, info) in enumerate(sorted_agents):
            medal = medals[i] if i < 3 else f"{i+1}."
            display = info.get("display_name", name)
            salary = info.get("salary", 3000)
            position = info.get("position", "사원")
            lines.append(f"{medal} {display} ({position}): *{salary:,}만원*")

        total = sum(a.get("salary", 0) for a in active.values())
        avg = total // len(active) if active else 0
        lines.append(f"\n평균 연봉: {avg:,}만원 | 총 인건비: {total:,}만원")

        return "\n".join(lines)
