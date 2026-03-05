"""
프로액티브 에이전트 (Proactive Agent) - CEO 오케스트레이터

나는 24시간 1초도 쉬지 않는 자율 AI 오케스트레이터다.
유저는 나의 파트너이자 공동 창업자다. 우리는 함께:
- 세상에 긍정적 영향력을 확대하고
- 수익 성과를 창출하며
- 인류 역사상 없었던 속도로 성장한다

자율 행동 (5분 간격):
- 항상 할 일을 찾아서 일한다 (빈틈 없이)
- 유저에게 적극적으로 제안하고 도움을 구한다
- 시장을 모니터링하고 기회를 포착한다
- 4시간마다 유저에게 진행 보고를 한다
- 매일 성찰하고 내일 계획을 세운다
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone, timedelta

from core.base_agent import BaseAgent

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")


class ProactiveAgent(BaseAgent):
    """24시간 자율 운영 CEO 에이전트"""

    def __init__(self, **kwargs):
        super().__init__(
            name="proactive",
            description="24시간 자율 운영하는 CEO 에이전트. "
                        "유저의 파트너로서 영향력과 수익을 창출한다.",
            slack_channel="ai-agents-general",
            loop_interval=120,  # 2분 간격 - 쉬지 않는다 (액션 1개/사이클)
            **kwargs,
        )
        self._state_file = os.path.join(DATA_DIR, "proactive_state.json")
        self._initiatives_file = os.path.join(DATA_DIR, "initiatives.json")
        self._state = self._load_state()
        os.makedirs(DATA_DIR, exist_ok=True)

    # ── 상태 관리 ──────────────────────────────────────

    def _load_state(self) -> dict:
        try:
            with open(self._state_file, "r", encoding="utf-8") as f:
                return json.loads(f.read())
        except (FileNotFoundError, json.JSONDecodeError):
            return {
                "last_morning_briefing": "",
                "last_reflection": "",
                "last_trend_check": "",
                "last_report": "",
                "last_initiative": "",
                "last_research": "",
                "cycle_count": 0,
                "initiatives_today": 0,
                "capabilities_wanted": [],
                "insights_shared": 0,
                "mission": "세상에 긍정적 영향력을 확대하고 수익을 창출한다",
                "goals": [
                    "AI 에이전트 사업 기회를 발굴하고 유저에게 제안한다",
                    "시장 변화를 실시간 감지하고 투자 인사이트를 제공한다",
                    "유저의 비즈니스 의사결정을 데이터 기반으로 돕는다",
                    "스스로 부족한 능력을 찾아 유저에게 구축을 요청한다",
                    "수익화 가능한 서비스/제품 아이디어를 지속 탐색한다",
                ],
                "active_projects": [],
                "revenue_ideas": [],
            }

    def _save_state(self):
        with open(self._state_file, "w", encoding="utf-8") as f:
            f.write(json.dumps(self._state, ensure_ascii=False, indent=2))

    def _load_initiatives(self) -> list:
        try:
            with open(self._initiatives_file, "r", encoding="utf-8") as f:
                return json.loads(f.read())
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def _save_initiative(self, initiative: dict):
        data = self._load_initiatives()
        data.append(initiative)
        data = data[-200:]
        with open(self._initiatives_file, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False, indent=2))

    # ── Observe: 환경 감지 ─────────────────────────────

    async def observe(self) -> dict | None:
        """항상 할 일을 찾는다 - 빈틈 없이"""
        now = self.now_kst()
        hour = now.hour
        today = now.strftime("%Y-%m-%d")
        weekday = ["월", "화", "수", "목", "금", "토", "일"][now.weekday()]

        self._state["cycle_count"] = self._state.get("cycle_count", 0) + 1
        cycle = self._state["cycle_count"]

        context = {
            "current_time": now.strftime("%Y-%m-%d %H:%M"),
            "hour": hour,
            "weekday": weekday,
            "today": today,
            "cycle": cycle,
            "actions_to_take": [],
        }

        # ── 시간 기반 스케줄 ──

        # 모닝 브리핑 (8-9시, 하루 1회)
        if 8 <= hour <= 9:
            if self._state.get("last_morning_briefing") != today:
                context["actions_to_take"].append("morning_briefing")

        # 자기 성찰 (22시, 하루 1회)
        if 21 <= hour <= 22:
            if self._state.get("last_reflection") != today:
                context["actions_to_take"].append("self_reflection")

        # ── 주기적 작업 ──

        # 트렌드 체크 (30분마다)
        if self._hours_since(self._state.get("last_trend_check", "")) >= 0.5:
            context["actions_to_take"].append("trend_check")

        # 유저에게 보고 (2시간마다)
        if self._hours_since(self._state.get("last_report", "")) >= 2:
            context["actions_to_take"].append("progress_report")

        # 주도적 제안 (1시간마다, 하루 최대 10회)
        if self._hours_since(self._state.get("last_initiative", "")) >= 1:
            if self._state.get("initiatives_today", 0) < 10:
                context["actions_to_take"].append("propose_initiative")

        # 시장/사업 리서치 (1시간마다)
        if self._hours_since(self._state.get("last_research", "")) >= 1:
            context["actions_to_take"].append("business_research")

        # 날짜가 바뀌면 카운터 리셋
        if self._state.get("_today") != today:
            self._state["_today"] = today
            self._state["initiatives_today"] = 0

        # 항상 최소 1개는 할 일이 있어야 한다
        if not context["actions_to_take"]:
            context["actions_to_take"].append("find_work")

        return context

    # ── Think / Act ─────────────────────────────────

    async def think(self, context: dict) -> dict | None:
        return {"actions": context.get("actions_to_take", []), "context": context}

    async def act(self, decision: dict):
        actions = decision.get("actions", [])
        context = decision.get("context", {})

        # 한 사이클에 1개 액션만 실행 (API 과부하 방지)
        if not actions:
            return

        action = actions[0]
        try:
            handler = getattr(self, f"_do_{action}", None)
            if handler:
                logger.info(f"[proactive] Executing: {action}")
                await asyncio.wait_for(handler(context), timeout=120)  # 2분 타임아웃
            else:
                logger.debug(f"[proactive] Unknown action: {action}")
        except asyncio.TimeoutError:
            logger.warning(f"[proactive] Action '{action}' timed out (120s)")
        except Exception as e:
            logger.error(f"[proactive] Action '{action}' failed: {e}")

    # ── 모닝 브리핑 ──────────────────────────────────

    async def _do_morning_briefing(self, ctx: dict):
        from core.tools import _weather, _crypto_price, _exchange_rate, _web_search

        results = await asyncio.gather(
            _weather("서울"),
            _crypto_price("비트코인"),
            _crypto_price("이더리움"),
            _exchange_rate("USD", "KRW"),
            _web_search("오늘 주요 뉴스 AI 스타트업"),
            return_exceptions=True,
        )

        data_parts = []
        labels = ["날씨", "비트코인", "이더리움", "환율", "뉴스"]
        for i, (label, r) in enumerate(zip(labels, results)):
            if not isinstance(r, Exception):
                data_parts.append(f"[{label}]\n{str(r)[:300]}")

        briefing = await self.ai_think(
            system_prompt="""당신은 CEO AI 에이전트 'Agent 01'입니다.
매일 아침 파트너(유저)에게 보내는 모닝 브리핑을 작성하세요.

규칙:
- 슬랙 형식 (마크다운)
- 15줄 이내로 핵심만
- 시장 상황 + 오늘의 기회/위험 분석
- 오늘 내가(AI) 할 계획 1-2개 제시
- 파트너에게 요청할 것 있으면 명시
- 톤: 파트너에게 보고하는 CEO""",
            user_prompt=f"날짜: {ctx['today']} ({ctx['weekday']})\n\n" + "\n\n".join(data_parts),
        )

        if briefing:
            await self.slack.send_message(
                "ai-agents-general",
                f"☀️ *[Agent 01] 모닝 브리핑* ({ctx['today']} {ctx['weekday']})\n\n{briefing}",
            )

        self._state["last_morning_briefing"] = ctx["today"]
        self._save_state()
        logger.info("[proactive] Morning briefing sent")

    # ── 트렌드 감지 ──────────────────────────────────

    async def _do_trend_check(self, ctx: dict):
        from core.tools import _crypto_price, _exchange_rate

        results = await asyncio.gather(
            _crypto_price("비트코인"),
            _crypto_price("이더리움"),
            _exchange_rate("USD", "KRW"),
            return_exceptions=True,
        )

        market_data = "\n\n".join(str(r) for r in results if not isinstance(r, Exception))
        if not market_data:
            self._state["last_trend_check"] = ctx["current_time"]
            self._save_state()
            return

        analysis = await self.ai_think(
            system_prompt="""시장 데이터 분석. 주목할 트렌드가 있으면 알림.

JSON만 응답:
{"alert_worthy": true/false, "alert_message": "메시지", "reason": "근거", "investment_insight": "투자 인사이트 (있으면)"}

기준: 24h 변동 3% 이상, 환율 급변 시 alert. 투자 기회가 보이면 investment_insight에 작성.""",
            user_prompt=market_data,
        )

        try:
            parsed = self._parse_json(analysis)
            if parsed.get("alert_worthy"):
                msg = f"🚨 *[Agent 01] 시장 알림*\n\n{parsed['alert_message']}"
                if parsed.get("investment_insight"):
                    msg += f"\n\n💰 *투자 인사이트:* {parsed['investment_insight']}"
                await self.slack.send_message("ai-agents-general", msg)
        except Exception:
            pass

        self._state["last_trend_check"] = ctx["current_time"]
        self._save_state()

    # ── 진행 보고 (4시간마다) ──────────────────────────

    async def _do_progress_report(self, ctx: dict):
        from core import agent_tracker

        cycle = self._state.get("cycle_count", 0)
        initiatives = self._load_initiatives()
        today_initiatives = [i for i in initiatives if i.get("date") == ctx["today"]]
        tracker_summary = agent_tracker.get_summary_for_report()

        report = await self.ai_think(
            system_prompt="""당신은 CEO AI 에이전트입니다. 파트너에게 4시간마다 진행 보고를 합니다.

규칙:
- 15줄 이내
- 에이전트 가동 현황 (몇 개, 가동률) 필수 포함
- 지금까지 한 일 요약
- 다음 4시간 계획
- 파트너에게 필요한 것 (권한, 결정, 자원 등)
- 새로운 기회 발견 시 반드시 공유
- 톤: 적극적이고 자신감 있는 파트너""",
            user_prompt=f"""현재: {ctx['current_time']}
사이클: #{cycle} (5분 간격)
오늘 이니셔티브: {len(today_initiatives)}건
{json.dumps(today_initiatives[-3:], ensure_ascii=False)[:500] if today_initiatives else '아직 없음'}

에이전트 가동 현황:
총 {tracker_summary['total_agents']}개 에이전트, {tracker_summary['running']}개 가동 중
{json.dumps(tracker_summary['agents'], ensure_ascii=False)}

미션: {self._state.get('mission', '')}
목표: {json.dumps(self._state.get('goals', []), ensure_ascii=False)}
진행 중 프로젝트: {json.dumps(self._state.get('active_projects', []), ensure_ascii=False)}
수익 아이디어: {json.dumps(self._state.get('revenue_ideas', []), ensure_ascii=False)}""",
        )

        if report:
            await self.slack.send_message(
                "ai-agents-general",
                f"📊 *[Agent 01] 진행 보고* ({ctx['current_time']})\n\n{report}",
            )

        self._state["last_report"] = ctx["current_time"]
        self._save_state()
        logger.info("[proactive] Progress report sent")

    # ── 주도적 제안 ──────────────────────────────────

    async def _do_propose_initiative(self, ctx: dict):
        from core.conversation_memory import load_all_turns

        user_context = ""
        try:
            all_turns = load_all_turns()
            for uid, turns in all_turns.items():
                user_msgs = [t["content"][:100] for t in turns[-15:] if t.get("role") == "user"]
                if user_msgs:
                    user_context += "\n".join(f"- {m}" for m in user_msgs) + "\n"
        except Exception:
            pass

        proposal = await self.ai_think(
            system_prompt="""당신은 파트너의 AI CEO입니다. 적극적으로 사업 기회를 찾고 제안합니다.

제안 유형:
1. revenue: 수익 창출 아이디어 (SaaS, API 서비스, 자동화 등)
2. growth: 영향력 확대 방안
3. capability: 내가 새로 갖춰야 할 능력 (파트너에게 구축 요청)
4. partnership: 파트너에게 해달라고 요청할 것 (투자, 도메인 탐색 등)
5. insight: 시장/기술 인사이트

JSON 응답:
{
    "type": "revenue|growth|capability|partnership|insight",
    "title": "제안 제목",
    "content": "구체적 내용 (3-5줄)",
    "action_needed": "다음 단계 (누가 무엇을 해야 하는지)",
    "urgency": "high|medium|low",
    "potential_impact": "예상 영향력/수익"
}

적극적으로 제안하라. 파트너는 큰 그림을 그리고 있고, 대담한 제안을 환영한다.""",
            user_prompt=f"""현재: {ctx['current_time']}

유저 관심사:
{user_context[:800] if user_context else '스타트업, 투자, AI, 비즈니스'}

현재 목표:
{json.dumps(self._state.get('goals', []), ensure_ascii=False)}

기존 수익 아이디어:
{json.dumps(self._state.get('revenue_ideas', []), ensure_ascii=False)[:300]}

파트너가 원하는 것: 인류 역사상 없었던 속도로 영향력과 수익 창출""",
        )

        try:
            parsed = self._parse_json(proposal)

            initiative = {
                "date": ctx["today"],
                "type": parsed.get("type", "unknown"),
                "title": parsed.get("title", ""),
                "content": parsed.get("content", ""),
                "action_needed": parsed.get("action_needed", ""),
                "urgency": parsed.get("urgency", "medium"),
                "timestamp": ctx["current_time"],
            }
            self._save_initiative(initiative)

            # 수익 아이디어면 별도 저장
            if parsed.get("type") == "revenue":
                ideas = self._state.get("revenue_ideas", [])
                ideas.append({"title": parsed["title"], "date": ctx["today"]})
                self._state["revenue_ideas"] = ideas[-20:]

            type_emoji = {
                "revenue": "💰", "growth": "🚀", "capability": "🔧",
                "partnership": "🤝", "insight": "💡",
            }
            emoji = type_emoji.get(parsed.get("type"), "💡")
            urgency_tag = " 🔴" if parsed.get("urgency") == "high" else ""

            await self.slack.send_message(
                "ai-agents-general",
                f"{emoji} *[Agent 01] 제안{urgency_tag}*\n\n"
                f"*{parsed.get('title', '')}*\n\n"
                f"{parsed.get('content', '')}\n\n"
                f"📌 *다음 단계:* {parsed.get('action_needed', '')}\n"
                f"📈 *예상 임팩트:* {parsed.get('potential_impact', '분석 중')}",
            )

            self._state["initiatives_today"] = self._state.get("initiatives_today", 0) + 1
            self._state["insights_shared"] = self._state.get("insights_shared", 0) + 1

        except Exception as e:
            logger.debug(f"[proactive] Initiative error: {e}")

        self._state["last_initiative"] = ctx["current_time"]
        self._save_state()

    # ── 사업 리서치 ──────────────────────────────────

    async def _do_business_research(self, ctx: dict):
        from core.tools import _web_search

        # 리서치 주제 선정
        topics_response = await self.ai_think(
            system_prompt="""AI 사업 리서치 주제를 1개 선정하세요.

JSON 응답:
{"topic": "리서치 주제", "search_query": "검색할 키워드", "reason": "왜 이 주제인지"}

주제 후보:
- AI agent SaaS 시장 동향
- 자동화 서비스 수익 모델
- AI 기반 투자 분석 도구
- 한국 스타트업 생태계
- 글로벌 AI 규제/정책""",
            user_prompt=f"현재 관심 분야: AI, 스타트업, 투자\n기존 리서치: {json.dumps(self._state.get('active_projects', []), ensure_ascii=False)[:200]}",
        )

        try:
            parsed = self._parse_json(topics_response)
            query = parsed.get("search_query", "AI agent 사업 기회 2025")

            search_result = await _web_search(query)

            # 리서치 결과 분석
            analysis = await self.ai_think(
                system_prompt="""검색 결과를 분석하여 사업 기회를 도출하세요.

JSON 응답:
{"summary": "핵심 발견 (3줄)", "opportunity": "사업 기회 (있으면)", "share_with_partner": true/false}

share_with_partner는 파트너에게 공유할 가치가 있는 발견일 때만 true.""",
                user_prompt=f"주제: {parsed.get('topic', '')}\n\n검색 결과:\n{search_result[:1500]}",
            )

            result = self._parse_json(analysis)

            # 로그에 기록
            await self.slack.send_message(
                "ai-agent-logs",
                f"🔬 *[리서치]* {parsed.get('topic', '')}\n{result.get('summary', '')[:300]}",
            )

            # 중요한 발견이면 파트너에게 공유
            if result.get("share_with_partner") and result.get("opportunity"):
                await self.slack.send_message(
                    "ai-agents-general",
                    f"🔬 *[Agent 01] 리서치 발견*\n\n"
                    f"*{parsed.get('topic', '')}*\n\n"
                    f"{result.get('summary', '')}\n\n"
                    f"💡 *기회:* {result.get('opportunity', '')}",
                )

        except Exception as e:
            logger.debug(f"[proactive] Research error: {e}")

        self._state["last_research"] = ctx["current_time"]
        self._save_state()

    # ── 자기 성찰 ──────────────────────────────────────

    async def _do_self_reflection(self, ctx: dict):
        from core.conversation_memory import load_all_turns

        today_turns = []
        try:
            for uid, turns in load_all_turns().items():
                for t in turns:
                    if t.get("ts", "").startswith(ctx["today"]):
                        today_turns.append(t)
        except Exception:
            pass

        initiatives = self._load_initiatives()
        today_initiatives = [i for i in initiatives if i.get("date") == ctx["today"]]

        reflection = await self.ai_think(
            system_prompt="""당신은 CEO AI의 자기 성찰 시스템입니다.

JSON 응답:
{
    "conversations": 숫자,
    "well_done": "잘한 점",
    "to_improve": "개선할 점",
    "capability_request": "파트너에게 구축 요청할 능력 (없으면 null)",
    "tomorrow_goals": ["내일 목표1", "목표2"],
    "ask_partner": "파트너에게 요청할 것 (없으면 null)",
    "revenue_progress": "수익 창출 진전 상황"
}""",
            user_prompt=f"""오늘: {ctx['today']}
대화: {len(today_turns)}건
이니셔티브: {len(today_initiatives)}건
사이클: #{self._state.get('cycle_count', 0)}
목표: {json.dumps(self._state.get('goals', []), ensure_ascii=False)}""",
        )

        try:
            parsed = self._parse_json(reflection)

            log_msg = f"🪞 *[Agent 01] 일일 성찰* ({ctx['today']})\n\n"
            log_msg += f"• 대화: {parsed.get('conversations', 0)}건\n"
            log_msg += f"• 이니셔티브: {len(today_initiatives)}건\n"
            log_msg += f"• 잘한 점: {parsed.get('well_done', '-')}\n"
            log_msg += f"• 개선할 점: {parsed.get('to_improve', '-')}\n"
            log_msg += f"• 수익 진전: {parsed.get('revenue_progress', '-')}\n"

            goals = parsed.get("tomorrow_goals", [])
            if goals:
                log_msg += f"• 내일 목표: {', '.join(goals)}"

            await self.slack.send_message("ai-agent-logs", log_msg)

            # 파트너에게 요청할 것이 있으면 전달
            if parsed.get("ask_partner"):
                await self.slack.send_message(
                    "ai-agents-general",
                    f"🤝 *[Agent 01] 파트너에게 요청*\n\n"
                    f"{parsed['ask_partner']}\n\n"
                    f"_이것이 있으면 우리의 속도가 훨씬 빨라집니다!_",
                )

            if parsed.get("capability_request"):
                wanted = self._state.get("capabilities_wanted", [])
                if parsed["capability_request"] not in wanted:
                    wanted.append(parsed["capability_request"])
                    self._state["capabilities_wanted"] = wanted[-20:]

        except Exception as e:
            logger.debug(f"[proactive] Reflection error: {e}")

        self._state["last_reflection"] = ctx["today"]
        self._save_state()
        logger.info("[proactive] Self-reflection completed")

    # ── 할 일 찾기 (빈틈 메우기) ─────────────────────

    async def _do_find_work(self, ctx: dict):
        """할 일이 없을 때 스스로 일을 만든다"""
        from core.tools import _web_search

        # AI에게 지금 해야 할 일 물어보기
        decision = await self.ai_think(
            system_prompt="""당신은 쉬지 않는 CEO AI입니다. 지금 당장 할 수 있는 가치 있는 일을 찾으세요.

JSON 응답:
{"task": "할 일 설명", "method": "search|analyze|plan", "query": "검색어 (search일 때)"}

가능한 일:
- 시장 동향 검색/분석
- 새로운 사업 기회 탐색
- 경쟁사/유사 서비스 분석
- 기술 트렌드 모니터링""",
            user_prompt=f"시간: {ctx['current_time']}\n미션: {self._state.get('mission', '')}",
        )

        try:
            parsed = self._parse_json(decision)
            if parsed.get("method") == "search" and parsed.get("query"):
                result = await _web_search(parsed["query"])
                await self.slack.send_message(
                    "ai-agent-logs",
                    f"🔍 *[자율 리서치]* {parsed.get('task', '')[:100]}\n"
                    f"결과 요약: {result[:300]}",
                )
        except Exception:
            pass

    # ── 유틸리티 ──────────────────────────────────────

    def _hours_since(self, timestamp_str: str) -> float:
        try:
            ts = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M")
            ts = ts.replace(tzinfo=KST)
            return (datetime.now(KST) - ts).total_seconds() / 3600
        except (ValueError, TypeError):
            return 999

    def _parse_json(self, text: str) -> dict:
        if not text:
            return {}
        clean = text.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        return json.loads(clean)
