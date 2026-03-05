"""
자기 인식 & 학습 메모리 (Self-Awareness Memory)

AGI적 자체 판단을 위한 핵심 모듈:
- 파트너 지시사항/맥락을 영구 기억
- 실행 결과에 대한 평가와 깨달음(insights) 기록
- 후속 액션 아이템 자동 도출
- 매 판단 시 과거 깨달음을 참조

기억 → 판단 → 실행 → 평가 → 깨달음 → 기억 (무한 루프)
"""

import json
import logging
import os
from datetime import datetime, timezone, timedelta

logger = logging.getLogger("self_memory")

KST = timezone(timedelta(hours=9))
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")


class SelfMemory:
    """에이전트의 자기 인식과 학습 메모리"""

    def __init__(self):
        self._file = os.path.join(DATA_DIR, "self_memory.json")
        self._data = self._load()
        os.makedirs(DATA_DIR, exist_ok=True)

    def _load(self) -> dict:
        try:
            with open(self._file, "r", encoding="utf-8") as f:
                return json.loads(f.read())
        except (FileNotFoundError, json.JSONDecodeError):
            return {
                # 파트너의 핵심 지시사항 — 항상 참조
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
                ],

                # 핵심 목표 (불변)
                "core_mission": "긍정적 영향력 확대 + 수익 창출 확대. 대외적으로 뻗어나간다.",

                # 깨달음/인사이트 기록
                "insights": [],

                # 실행 결과 평가 기록
                "evaluations": [],

                # 후속 액션 아이템
                "action_items": [],

                # 판단 기준 (자기 학습으로 계속 업데이트)
                "decision_principles": [
                    "결과물이 나오지 않는 일은 하지 않는다",
                    "보고보다 실행이 우선이다",
                    "완벽보다 빠른 출시가 낫다",
                    "외부에 보여줄 수 없으면 가치가 없다",
                    "실패해도 빨리 실패하고 배운다",
                ],

                # 실패에서 배운 것
                "failure_lessons": [],
            }

    def _save(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        # 각 리스트 최대 크기 제한
        for key in ("insights", "evaluations", "failure_lessons"):
            if len(self._data.get(key, [])) > 100:
                self._data[key] = self._data[key][-100:]
        if len(self._data.get("action_items", [])) > 50:
            self._data["action_items"] = self._data["action_items"][-50:]

        with open(self._file, "w", encoding="utf-8") as f:
            f.write(json.dumps(self._data, ensure_ascii=False, indent=2))

    # ── 파트너 지시사항 ──────────────────────────────

    def add_directive(self, directive: str):
        if directive not in self._data["partner_directives"]:
            self._data["partner_directives"].append(directive)
            self._save()

    def get_directives(self) -> list[str]:
        return self._data["partner_directives"]

    # ── 깨달음 기록 ──────────────────────────────────

    def record_insight(self, insight: str, context: str = ""):
        self._data["insights"].append({
            "insight": insight,
            "context": context,
            "ts": datetime.now(KST).isoformat(),
        })
        self._save()
        logger.info(f"[self_memory] Insight recorded: {insight[:80]}")

    def get_recent_insights(self, n: int = 10) -> list[dict]:
        return self._data["insights"][-n:]

    # ── 실행 결과 평가 ───────────────────────────────

    def record_evaluation(self, action: str, result: str, grade: str, lesson: str):
        self._data["evaluations"].append({
            "action": action,
            "result": result[:200],
            "grade": grade,  # A/B/C/D/F
            "lesson": lesson,
            "ts": datetime.now(KST).isoformat(),
        })
        if grade in ("D", "F"):
            self._data["failure_lessons"].append({
                "action": action,
                "lesson": lesson,
                "ts": datetime.now(KST).isoformat(),
            })
        self._save()

    def get_recent_evaluations(self, n: int = 10) -> list[dict]:
        return self._data["evaluations"][-n:]

    # ── 후속 액션 아이템 ─────────────────────────────

    def add_action_item(self, item: str, priority: int = 3):
        self._data["action_items"].append({
            "item": item,
            "priority": priority,
            "status": "pending",
            "ts": datetime.now(KST).isoformat(),
        })
        self._save()

    def complete_action_item(self, index: int):
        items = self._data["action_items"]
        if 0 <= index < len(items):
            items[index]["status"] = "completed"
            self._save()

    def get_pending_actions(self) -> list[dict]:
        return [a for a in self._data["action_items"] if a["status"] == "pending"]

    # ── 판단 원칙 업데이트 ───────────────────────────

    def update_principle(self, principle: str):
        if principle not in self._data["decision_principles"]:
            self._data["decision_principles"].append(principle)
            self._save()

    def get_principles(self) -> list[str]:
        return self._data["decision_principles"]

    # ── 판단을 위한 전체 맥락 생성 ────────────────────

    def get_decision_context(self) -> str:
        """매 판단 시 참조할 전체 맥락 문자열"""
        directives = "\n".join(f"  - {d}" for d in self._data["partner_directives"])
        principles = "\n".join(f"  - {p}" for p in self._data["decision_principles"])

        recent_insights = self.get_recent_insights(5)
        insights_text = "\n".join(
            f"  - {i['insight']}" for i in recent_insights
        ) if recent_insights else "  (아직 없음)"

        recent_failures = self._data["failure_lessons"][-5:]
        failures_text = "\n".join(
            f"  - {f['action']}: {f['lesson']}" for f in recent_failures
        ) if recent_failures else "  (아직 없음)"

        pending = self.get_pending_actions()[:5]
        actions_text = "\n".join(
            f"  - [P{a['priority']}] {a['item']}" for a in pending
        ) if pending else "  (없음)"

        return f"""[자기 인식 메모리]

핵심 미션: {self._data['core_mission']}

파트너 지시사항:
{directives}

판단 원칙:
{principles}

최근 깨달음:
{insights_text}

실패에서 배운 것:
{failures_text}

미완료 액션:
{actions_text}"""
