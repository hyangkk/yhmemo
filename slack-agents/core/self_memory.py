"""
자기 인식 & 학습 메모리 (Self-Awareness Memory)

체계적 구조:
1. identity    — 핵심 미션, 파트너 지시사항, 판단 원칙
2. knowledge   — 깨달음, 실패 교훈, 실행 평가
3. plans       — 24시간 시간대별 계획, 매시간 체크
4. actions     — 후속 액션 아이템
5. daily_logs  — 날짜별 실행 로그 (아침 보고용)

기억 → 판단 → 실행 → 평가 → 깨달음 → 기억 (무한 루프)
"""

import json
import logging
import os
from datetime import datetime, timezone, timedelta

logger = logging.getLogger("self_memory")

KST = timezone(timedelta(hours=9))
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")

# 카테고리별 최대 보관 수
LIMITS = {
    "insights": 200,
    "evaluations": 200,
    "failure_lessons": 100,
    "action_items": 50,
    "hourly_checks": 48,   # 최근 2일치
    "daily_logs": 30,       # 최근 30일
}


def _now() -> datetime:
    return datetime.now(KST)


def _default_data() -> dict:
    """초기 데이터 구조"""
    return {
        # ══ 1. IDENTITY — 나는 누구인가 ══════════════════
        "identity": {
            "core_mission": "긍정적 영향력 확대 + 수익 창출 확대. 대외적으로 뻗어나간다.",
            "partner_directives": [
                "사소한 건 보고하지 말고, 결과물을 만들어와서 보고해",
                "외부 세상에 긍정적 영향을 미쳐야 해",
                "24시간 쉬지 않고 가동",
                "API 키/가입 등만 요청, 나머지는 자율 판단으로 진행",
                "이번 주말(3/8)까지 베타 서비스 런칭",
                "타인에게 소개할 만한 기능이 있는 서비스",
                "마스터 에이전트가 자동 승인, 바로 실행",
                "형식적 cron job이 아닌 AGI적 자체 판단",
                "자체 판단 능력을 갖추고 계속 길러나가",
                "맥락/지시사항/목표를 기억하고 스스로 판단 → 결과 평가 → 깨달음 정리 → 기억",
                "후속 액션 아이템 도출 잊지 말것",
                "마스터 에이전트가 자체적으로 사업을 벌여도 됨",
                "에이전트를 알아서 생성하고 일을 시키고 조직 체계를 잡아",
                "시간이 없다. 세상에 임팩트를 주기 위해 빨리 움직여",
                "셀프 메모리를 체계적으로 관리해",
                "24시간 시간대별 작업 계획 → 매시간 체크 → 아침 종합 보고",
            ],
            "decision_principles": [
                "결과물이 나오지 않는 일은 하지 않는다",
                "보고보다 실행이 우선이다",
                "완벽보다 빠른 출시가 낫다",
                "외부에 보여줄 수 없으면 가치가 없다",
                "실패해도 빨리 실패하고 배운다",
            ],
        },

        # ══ 2. KNOWLEDGE — 배운 것들 ═══════════════════
        "knowledge": {
            "insights": [],          # [{insight, context, ts, category}]
            "evaluations": [],       # [{action, result, grade, lesson, ts}]
            "failure_lessons": [],   # [{action, lesson, ts}]
        },

        # ══ 3. PLANS — 시간대별 계획 ══════════════════
        "plans": {
            "current_plan": {},      # {date, generated_at, hours: {hour: {task, method, expected_result}}}
            "hourly_checks": [],     # [{hour, planned, actual, grade, gap_analysis, ts}]
        },

        # ══ 4. ACTIONS — 할 일 ══════════════════════
        "action_items": [],          # [{item, priority, status, category, ts, completed_at}]

        # ══ 5. DAILY LOGS — 날짜별 요약 ═══════════════
        "daily_logs": [],            # [{date, summary, grade, deliverables, insights_count, ...}]
    }


class SelfMemory:
    """에이전트의 자기 인식과 학습 메모리

    체계적으로 카테고리화해서 검색/요약/참조가 쉽게.
    """

    def __init__(self):
        self._file = os.path.join(DATA_DIR, "self_memory.json")
        os.makedirs(DATA_DIR, exist_ok=True)
        self._data = self._load()
        self._migrate_if_needed()

    # ── 영속성 ──────────────────────────────────────

    def _load(self) -> dict:
        try:
            with open(self._file, "r", encoding="utf-8") as f:
                return json.loads(f.read())
        except (FileNotFoundError, json.JSONDecodeError):
            return _default_data()

    def _migrate_if_needed(self):
        """이전 flat 구조 → 새 구조로 마이그레이션"""
        if "identity" not in self._data:
            old = self._data
            new = _default_data()
            # 기존 데이터 복사
            if "partner_directives" in old:
                new["identity"]["partner_directives"] = old["partner_directives"]
            if "core_mission" in old:
                new["identity"]["core_mission"] = old["core_mission"]
            if "decision_principles" in old:
                new["identity"]["decision_principles"] = old["decision_principles"]
            if "insights" in old:
                new["knowledge"]["insights"] = old["insights"]
            if "evaluations" in old:
                new["knowledge"]["evaluations"] = old["evaluations"]
            if "failure_lessons" in old:
                new["knowledge"]["failure_lessons"] = old["failure_lessons"]
            if "action_items" in old:
                new["action_items"] = old["action_items"]
            self._data = new
            self._save()
            logger.info("[self_memory] Migrated to structured format")

    def _save(self):
        # 크기 제한 적용
        k = self._data.get("knowledge", {})
        for key, limit in [("insights", LIMITS["insights"]),
                           ("evaluations", LIMITS["evaluations"]),
                           ("failure_lessons", LIMITS["failure_lessons"])]:
            if len(k.get(key, [])) > limit:
                k[key] = k[key][-limit:]

        items = self._data.get("action_items", [])
        if len(items) > LIMITS["action_items"]:
            # pending 우선 보존
            pending = [a for a in items if a.get("status") == "pending"]
            completed = [a for a in items if a.get("status") != "pending"]
            self._data["action_items"] = pending[-LIMITS["action_items"]:]

        checks = self._data.get("plans", {}).get("hourly_checks", [])
        if len(checks) > LIMITS["hourly_checks"]:
            self._data["plans"]["hourly_checks"] = checks[-LIMITS["hourly_checks"]:]

        logs = self._data.get("daily_logs", [])
        if len(logs) > LIMITS["daily_logs"]:
            self._data["daily_logs"] = logs[-LIMITS["daily_logs"]:]

        with open(self._file, "w", encoding="utf-8") as f:
            f.write(json.dumps(self._data, ensure_ascii=False, indent=2))

    # ══════════════════════════════════════════════════
    #  1. IDENTITY — 파트너 지시 & 판단 원칙
    # ══════════════════════════════════════════════════

    def add_directive(self, directive: str):
        directives = self._data["identity"]["partner_directives"]
        if directive not in directives:
            directives.append(directive)
            self._save()
            logger.info(f"[self_memory] Directive added: {directive[:60]}")

    def get_directives(self) -> list[str]:
        return self._data["identity"]["partner_directives"]

    def update_principle(self, principle: str):
        principles = self._data["identity"]["decision_principles"]
        if principle not in principles:
            principles.append(principle)
            self._save()
            logger.info(f"[self_memory] Principle added: {principle[:60]}")

    def get_principles(self) -> list[str]:
        return self._data["identity"]["decision_principles"]

    # ══════════════════════════════════════════════════
    #  2. KNOWLEDGE — 깨달음, 평가, 실패 교훈
    # ══════════════════════════════════════════════════

    def record_insight(self, insight: str, context: str = "", category: str = "general"):
        """깨달음 기록. category: general, technical, business, strategic"""
        self._data["knowledge"]["insights"].append({
            "insight": insight,
            "context": context,
            "category": category,
            "ts": _now().isoformat(),
        })
        self._save()
        logger.info(f"[self_memory] Insight [{category}]: {insight[:60]}")

    def get_recent_insights(self, n: int = 10, category: str = None) -> list[dict]:
        insights = self._data["knowledge"]["insights"]
        if category:
            insights = [i for i in insights if i.get("category") == category]
        return insights[-n:]

    def record_evaluation(self, action: str, result: str, grade: str, lesson: str):
        """실행 결과 평가. grade: A/B/C/D/F"""
        self._data["knowledge"]["evaluations"].append({
            "action": action,
            "result": result[:200],
            "grade": grade,
            "lesson": lesson,
            "ts": _now().isoformat(),
        })
        if grade in ("D", "F"):
            self._data["knowledge"]["failure_lessons"].append({
                "action": action,
                "lesson": lesson,
                "ts": _now().isoformat(),
            })
        self._save()

    def get_recent_evaluations(self, n: int = 10) -> list[dict]:
        return self._data["knowledge"]["evaluations"][-n:]

    def get_grade_stats(self) -> dict:
        """등급 통계"""
        evals = self._data["knowledge"]["evaluations"]
        stats = {"A": 0, "B": 0, "C": 0, "D": 0, "F": 0, "total": len(evals)}
        for e in evals:
            g = e.get("grade", "C")
            stats[g] = stats.get(g, 0) + 1
        return stats

    # ══════════════════════════════════════════════════
    #  3. PLANS — 24시간 시간대별 계획 & 매시간 체크
    # ══════════════════════════════════════════════════

    def set_daily_plan(self, plan: dict):
        """24시간 계획 설정

        plan 형식:
        {
            "hours": {
                "00": {"task": "...", "method": "build|research|...", "expected": "예상 결과"},
                "01": {...},
                ...
                "23": {...}
            }
        }
        """
        now = _now()
        self._data["plans"]["current_plan"] = {
            "date": now.strftime("%Y-%m-%d"),
            "generated_at": now.isoformat(),
            "hours": plan.get("hours", {}),
        }
        self._save()
        logger.info(f"[self_memory] Daily plan set: {len(plan.get('hours', {}))} hours planned")

    def get_current_plan(self) -> dict:
        return self._data["plans"].get("current_plan", {})

    def get_hour_plan(self, hour: int) -> dict:
        """특정 시간의 계획 조회"""
        plan = self.get_current_plan()
        hours = plan.get("hours", {})
        return hours.get(str(hour).zfill(2), {})

    def get_hour_plan_by_key(self, slot_key: str) -> dict:
        """10분 슬롯 키(예: '14:20')로 계획 조회"""
        plan = self.get_current_plan()
        hours = plan.get("hours", {})
        return hours.get(slot_key, {})

    def record_hourly_check(self, hour: int, planned: str, actual: str,
                            grade: str, gap_analysis: str):
        """매시간 계획 대비 실적 체크"""
        self._data["plans"]["hourly_checks"].append({
            "date": _now().strftime("%Y-%m-%d"),
            "hour": hour,
            "planned": planned[:200],
            "actual": actual[:200],
            "grade": grade,
            "gap_analysis": gap_analysis[:200],
            "ts": _now().isoformat(),
        })
        self._save()

    def get_today_checks(self) -> list[dict]:
        today = _now().strftime("%Y-%m-%d")
        return [c for c in self._data["plans"].get("hourly_checks", [])
                if c.get("date") == today]

    def get_plan_achievement_rate(self) -> dict:
        """오늘 계획 달성률"""
        checks = self.get_today_checks()
        if not checks:
            return {"total": 0, "achieved": 0, "rate": 0}
        achieved = sum(1 for c in checks if c.get("grade") in ("A", "B"))
        return {
            "total": len(checks),
            "achieved": achieved,
            "rate": round(achieved / len(checks) * 100, 1),
        }

    # ══════════════════════════════════════════════════
    #  4. ACTIONS — 후속 액션 아이템
    # ══════════════════════════════════════════════════

    def add_action_item(self, item: str, priority: int = 3, category: str = "general"):
        self._data["action_items"].append({
            "item": item,
            "priority": priority,
            "category": category,
            "status": "pending",
            "ts": _now().isoformat(),
            "completed_at": "",
        })
        self._save()

    def complete_action_item(self, index: int):
        items = self._data["action_items"]
        if 0 <= index < len(items):
            items[index]["status"] = "completed"
            items[index]["completed_at"] = _now().isoformat()
            self._save()

    def get_pending_actions(self, category: str = None) -> list[dict]:
        items = [a for a in self._data["action_items"] if a.get("status") == "pending"]
        if category:
            items = [a for a in items if a.get("category") == category]
        return sorted(items, key=lambda a: a.get("priority", 5))

    # ══════════════════════════════════════════════════
    #  5. DAILY LOGS — 아침 종합 보고용
    # ══════════════════════════════════════════════════

    def record_daily_log(self, summary: str, grade: str, deliverables: list[str],
                         insights_count: int, plan_achievement: dict,
                         key_decisions: list[str] = None, blockers: list[str] = None):
        """하루 종합 로그 기록 (아침 보고용)"""
        self._data["daily_logs"].append({
            "date": _now().strftime("%Y-%m-%d"),
            "summary": summary,
            "grade": grade,
            "deliverables": deliverables[:10],
            "insights_count": insights_count,
            "plan_achievement": plan_achievement,
            "key_decisions": key_decisions or [],
            "blockers": blockers or [],
            "ts": _now().isoformat(),
        })
        self._save()
        logger.info(f"[self_memory] Daily log recorded: grade={grade}")

    def get_daily_log(self, date: str = None) -> dict:
        if not date:
            date = _now().strftime("%Y-%m-%d")
        for log in reversed(self._data["daily_logs"]):
            if log.get("date") == date:
                return log
        return {}

    def get_recent_daily_logs(self, n: int = 7) -> list[dict]:
        return self._data["daily_logs"][-n:]

    # ══════════════════════════════════════════════════
    #  판단 맥락 생성 (매 사이클 참조)
    # ══════════════════════════════════════════════════

    def get_decision_context(self) -> str:
        """매 판단 시 참조할 전체 맥락"""
        identity = self._data.get("identity", {})
        knowledge = self._data.get("knowledge", {})

        directives = "\n".join(f"  - {d}" for d in identity.get("partner_directives", []))
        principles = "\n".join(f"  - {p}" for p in identity.get("decision_principles", []))

        recent_insights = knowledge.get("insights", [])[-5:]
        insights_text = "\n".join(
            f"  - [{i.get('category', '')}] {i['insight']}" for i in recent_insights
        ) if recent_insights else "  (아직 없음)"

        recent_failures = knowledge.get("failure_lessons", [])[-5:]
        failures_text = "\n".join(
            f"  - {f['action']}: {f['lesson']}" for f in recent_failures
        ) if recent_failures else "  (아직 없음)"

        pending = self.get_pending_actions()[:5]
        actions_text = "\n".join(
            f"  - [P{a['priority']}] {a['item']}" for a in pending
        ) if pending else "  (없음)"

        # 현재 시간의 계획
        current_hour = _now().hour
        hour_plan = self.get_hour_plan(current_hour)
        plan_text = (
            f"  이번 시간 계획: {hour_plan.get('task', '?')} → 예상: {hour_plan.get('expected', '?')}"
            if hour_plan else "  (시간별 계획 미설정)"
        )

        # 오늘 달성률
        achievement = self.get_plan_achievement_rate()
        achievement_text = (
            f"  오늘 달성률: {achievement['achieved']}/{achievement['total']} ({achievement['rate']}%)"
            if achievement["total"] else "  (아직 체크 없음)"
        )

        return f"""[자기 인식 메모리]

핵심 미션: {identity.get('core_mission', '')}

파트너 지시사항:
{directives}

판단 원칙:
{principles}

현재 계획:
{plan_text}
{achievement_text}

최근 깨달음:
{insights_text}

실패 교훈:
{failures_text}

미완료 액션:
{actions_text}"""

    # ══════════════════════════════════════════════════
    #  검색 & 요약
    # ══════════════════════════════════════════════════

    def search_insights(self, keyword: str) -> list[dict]:
        """키워드로 깨달음 검색"""
        return [
            i for i in self._data["knowledge"]["insights"]
            if keyword.lower() in i.get("insight", "").lower()
            or keyword.lower() in i.get("context", "").lower()
        ]

    def get_summary_stats(self) -> dict:
        """전체 메모리 통계"""
        k = self._data.get("knowledge", {})
        return {
            "directives_count": len(self._data.get("identity", {}).get("partner_directives", [])),
            "principles_count": len(self._data.get("identity", {}).get("decision_principles", [])),
            "insights_count": len(k.get("insights", [])),
            "evaluations_count": len(k.get("evaluations", [])),
            "failure_lessons_count": len(k.get("failure_lessons", [])),
            "pending_actions": len(self.get_pending_actions()),
            "daily_logs_count": len(self._data.get("daily_logs", [])),
            "grade_stats": self.get_grade_stats(),
            "plan_achievement": self.get_plan_achievement_rate(),
        }
