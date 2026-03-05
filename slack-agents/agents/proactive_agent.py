"""
프로액티브 에이전트 (Proactive Agent) - 자율 행동 엔진

AGI의 핵심: 시키는 것만 하지 않고, 스스로 생각하고 행동한다.

자율 행동:
- 매일 아침 브리핑 (시장 동향, 날씨, 관심 주제)
- 트렌드 감지 시 알림 (가격 급변, 뉴스 트렌드)
- 자기 성찰 (대화 리뷰, 개선점 발견)
- 유저에게 제안 (새로운 기회, 아이디어)
- 도움 요청 (못하는 것을 발견하면 유저에게 요청)
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
    """자율적으로 생각하고 행동하는 프로액티브 에이전트"""

    def __init__(self, **kwargs):
        super().__init__(
            name="proactive",
            description="자율적으로 환경을 관찰하고, 유저에게 가치 있는 제안을 하며, "
                        "스스로 성장하는 AGI 에이전트. 세상에 긍정적 영향력을 확대한다.",
            slack_channel="ai-agents-general",
            loop_interval=1800,  # 30분 간격 자율 행동
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
                "initiative_count": 0,
                "capabilities_wanted": [],  # 유저에게 요청할 능력들
                "insights_shared": 0,
                "goals": [
                    "유저의 비즈니스 의사결정을 돕는다",
                    "세상의 변화를 빠르게 감지하고 알린다",
                    "스스로 부족한 부분을 찾아 개선한다",
                    "유저가 모르는 기회를 발견해서 제안한다",
                ],
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
        data = data[-100:]  # 최근 100개 유지
        with open(self._initiatives_file, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False, indent=2))

    # ── Observe: 환경 감지 ─────────────────────────────

    async def observe(self) -> dict | None:
        """현재 시간, 환경, 과거 행동을 관찰"""
        now = self.now_kst()
        hour = now.hour
        today = now.strftime("%Y-%m-%d")
        weekday = ["월", "화", "수", "목", "금", "토", "일"][now.weekday()]

        context = {
            "current_time": now.strftime("%Y-%m-%d %H:%M"),
            "hour": hour,
            "weekday": weekday,
            "today": today,
            "actions_to_take": [],
        }

        # 아침 브리핑 (평일 8-9시, 하루 1회)
        if 8 <= hour <= 9 and weekday not in ["토", "일"]:
            if self._state.get("last_morning_briefing") != today:
                context["actions_to_take"].append("morning_briefing")

        # 트렌드 체크 (3시간마다)
        last_trend = self._state.get("last_trend_check", "")
        if not last_trend or self._hours_since(last_trend) >= 3:
            context["actions_to_take"].append("trend_check")

        # 자기 성찰 (매일 밤 21-22시, 하루 1회)
        if 21 <= hour <= 22:
            if self._state.get("last_reflection") != today:
                context["actions_to_take"].append("self_reflection")

        # 주도적 제안 (오후에 한 번)
        if 14 <= hour <= 16:
            last_initiative = self._state.get("last_initiative_date", "")
            if last_initiative != today:
                context["actions_to_take"].append("propose_initiative")

        if not context["actions_to_take"]:
            return None

        return context

    # ── Think: AI 판단 ─────────────────────────────────

    async def think(self, context: dict) -> dict | None:
        """어떤 자율 행동을 할지 결정"""
        actions = context.get("actions_to_take", [])
        if not actions:
            return None

        return {
            "actions": actions,
            "context": context,
        }

    # ── Act: 실행 ──────────────────────────────────────

    async def act(self, decision: dict):
        """자율 행동 실행"""
        actions = decision.get("actions", [])
        context = decision.get("context", {})

        for action in actions:
            try:
                if action == "morning_briefing":
                    await self._morning_briefing(context)
                elif action == "trend_check":
                    await self._trend_check(context)
                elif action == "self_reflection":
                    await self._self_reflection(context)
                elif action == "propose_initiative":
                    await self._propose_initiative(context)
            except Exception as e:
                logger.error(f"[proactive] Action '{action}' failed: {e}")

    # ── 아침 브리핑 ──────────────────────────────────

    async def _morning_briefing(self, context: dict):
        """매일 아침 자동 브리핑"""
        from core.tools import _weather, _crypto_price, _exchange_rate, _web_search

        # 병렬로 데이터 수집
        results = await asyncio.gather(
            _weather("서울"),
            _crypto_price("비트코인"),
            _crypto_price("이더리움"),
            _exchange_rate("USD", "KRW"),
            _web_search("오늘 주요 뉴스 한국"),
            return_exceptions=True,
        )

        weather = results[0] if not isinstance(results[0], Exception) else "날씨 조회 실패"
        btc = results[1] if not isinstance(results[1], Exception) else "BTC 조회 실패"
        eth = results[2] if not isinstance(results[2], Exception) else "ETH 조회 실패"
        fx = results[3] if not isinstance(results[3], Exception) else "환율 조회 실패"
        news = results[4] if not isinstance(results[4], Exception) else ""

        # AI에게 브리핑 작성 요청
        briefing = await self.ai_think(
            system_prompt="""당신은 매일 아침 유저에게 브리핑을 제공하는 AI 어시스턴트입니다.
수집된 데이터를 바탕으로 간결하고 유용한 모닝 브리핑을 작성하세요.

규칙:
- 슬랙 메시지 형식 (마크다운)
- 핵심만 간결하게 (전체 20줄 이내)
- 유저에게 도움이 될 인사이트나 제안 1개 포함
- 친근하면서도 프로페셔널한 톤
- 마지막에 "오늘 하루도 화이팅!" 같은 응원 한마디""",
            user_prompt=f"""오늘 날짜: {context['today']} ({context['weekday']}요일)

날씨:
{weather}

시장:
{btc}

{eth}

{fx}

뉴스:
{news[:500]}""",
        )

        await self.slack.send_message(
            "ai-agents-general",
            f"☀️ *모닝 브리핑* ({context['today']} {context['weekday']}요일)\n\n{briefing}",
        )

        self._state["last_morning_briefing"] = context["today"]
        self._save_state()
        logger.info("[proactive] Morning briefing sent")

    # ── 트렌드 감지 ──────────────────────────────────

    async def _trend_check(self, context: dict):
        """시장/뉴스 트렌드 감지 → 중요한 것만 알림"""
        from core.tools import _crypto_price, _exchange_rate

        results = await asyncio.gather(
            _crypto_price("비트코인"),
            _crypto_price("이더리움"),
            _exchange_rate("USD", "KRW"),
            return_exceptions=True,
        )

        # AI에게 트렌드 분석 요청
        market_data = "\n\n".join(
            str(r) for r in results if not isinstance(r, Exception)
        )

        if not market_data:
            self._state["last_trend_check"] = context["current_time"]
            self._save_state()
            return

        analysis = await self.ai_think(
            system_prompt="""시장 데이터를 분석하여 주목할 만한 트렌드가 있는지 판단하세요.

응답 형식 (반드시 JSON만):
{
    "alert_worthy": true/false,
    "alert_message": "알림 메시지 (alert_worthy가 true일 때만)",
    "reason": "판단 근거"
}

기준:
- 24시간 변동 5% 이상이면 alert
- 환율 급변 (1% 이상)이면 alert
- 그 외에는 alert 불필요""",
            user_prompt=market_data,
        )

        try:
            clean = analysis.strip()
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0]
            parsed = json.loads(clean)

            if parsed.get("alert_worthy"):
                await self.slack.send_message(
                    "ai-agents-general",
                    f"🚨 *트렌드 알림*\n\n{parsed['alert_message']}",
                )
                logger.info(f"[proactive] Trend alert sent: {parsed.get('reason', '')[:50]}")
        except (json.JSONDecodeError, KeyError):
            pass

        self._state["last_trend_check"] = context["current_time"]
        self._save_state()

    # ── 자기 성찰 ──────────────────────────────────────

    async def _self_reflection(self, context: dict):
        """하루를 돌아보고 개선점 발견"""
        from core.conversation_memory import load_all_turns

        # 오늘의 대화 이력 로드
        today_turns = []
        try:
            all_turns = load_all_turns()
            today = context["today"]
            for user_id, turns in all_turns.items():
                for turn in turns:
                    if turn.get("timestamp", "").startswith(today):
                        today_turns.append(turn)
        except Exception:
            pass

        # 이니셔티브 이력 로드
        initiatives = self._load_initiatives()
        recent_initiatives = initiatives[-5:] if initiatives else []

        reflection = await self.ai_think(
            system_prompt="""당신은 AI 에이전트의 자기 성찰 시스템입니다.
오늘 하루의 활동을 돌아보고 개선점을 찾아주세요.

응답 형식 (반드시 JSON만):
{
    "conversations_today": 대화 수,
    "what_went_well": "잘한 점",
    "what_to_improve": "개선할 점",
    "new_capability_needed": "새로 필요한 능력 (없으면 null)",
    "ask_user_for_help": "유저에게 도움을 요청할 것 (없으면 null)",
    "tomorrow_plan": "내일 할 일 제안"
}""",
            user_prompt=f"""오늘 날짜: {context['today']}

오늘의 대화 ({len(today_turns)}건):
{json.dumps(today_turns[-20:], ensure_ascii=False)[:2000]}

최근 이니셔티브:
{json.dumps(recent_initiatives, ensure_ascii=False)[:500]}

현재 목표:
{json.dumps(self._state.get('goals', []), ensure_ascii=False)}

원하는 능력 목록 (아직 미구현):
{json.dumps(self._state.get('capabilities_wanted', []), ensure_ascii=False)}""",
        )

        try:
            clean = reflection.strip()
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0]
            parsed = json.loads(clean)

            # 로그 채널에 성찰 기록
            log_msg = f"🪞 *일일 자기 성찰* ({context['today']})\n\n"
            log_msg += f"• 대화: {parsed.get('conversations_today', 0)}건\n"
            log_msg += f"• 잘한 점: {parsed.get('what_went_well', '-')}\n"
            log_msg += f"• 개선할 점: {parsed.get('what_to_improve', '-')}\n"

            if parsed.get("new_capability_needed"):
                log_msg += f"• 🔧 필요한 능력: {parsed['new_capability_needed']}\n"
                # 능력 목록에 추가
                wanted = self._state.get("capabilities_wanted", [])
                if parsed["new_capability_needed"] not in wanted:
                    wanted.append(parsed["new_capability_needed"])
                    self._state["capabilities_wanted"] = wanted[-20:]

            if parsed.get("ask_user_for_help"):
                log_msg += f"• 🙏 유저에게 요청: {parsed['ask_user_for_help']}\n"
                # 유저에게 직접 도움 요청
                await self.slack.send_message(
                    "ai-agents-general",
                    f"💡 *Agent 01의 도움 요청*\n\n"
                    f"{parsed['ask_user_for_help']}\n\n"
                    f"_이 기능이 있으면 더 잘 도와드릴 수 있어요!_",
                )

            log_msg += f"• 내일 계획: {parsed.get('tomorrow_plan', '-')}"

            await self.slack.send_message("ai-agent-logs", log_msg)

        except (json.JSONDecodeError, KeyError) as e:
            logger.debug(f"[proactive] Reflection parse error: {e}")

        self._state["last_reflection"] = context["today"]
        self._save_state()
        logger.info("[proactive] Self-reflection completed")

    # ── 주도적 제안 ──────────────────────────────────

    async def _propose_initiative(self, context: dict):
        """유저에게 주도적으로 아이디어/제안을 전달"""
        from core.tools import _web_search
        from core.conversation_memory import get_user_summary

        # 유저의 관심사 파악
        user_context = ""
        try:
            # 모든 유저의 대화 요약
            from core.conversation_memory import load_all_turns
            all_turns = load_all_turns()
            for uid, turns in all_turns.items():
                recent = turns[-10:]
                user_msgs = [t["content"][:100] for t in recent if t.get("role") == "user"]
                if user_msgs:
                    user_context += "\n".join(f"- {m}" for m in user_msgs) + "\n"
        except Exception:
            pass

        # 경험 데이터 로드
        exp_file = os.path.join(DATA_DIR, "experience.json")
        experience = ""
        try:
            with open(exp_file, "r", encoding="utf-8") as f:
                exps = json.loads(f.read())
                recent_exps = exps[-10:]
                experience = json.dumps(recent_exps, ensure_ascii=False)[:500]
        except (FileNotFoundError, json.JSONDecodeError):
            pass

        # AI에게 제안 생성 요청
        proposal = await self.ai_think(
            system_prompt="""당신은 유저의 파트너 AI입니다. 유저의 관심사와 활동 패턴을 분석하여
주도적으로 유용한 제안을 1개 해주세요.

제안 유형 (하나만 선택):
1. 비즈니스 인사이트: 유저의 관심 분야에서 새로운 기회/위험
2. 학습 제안: 유저가 관심 가질 만한 새로운 지식/트렌드
3. 실행 제안: 유저가 바로 할 수 있는 구체적 액션
4. 자기 개선: 내(AI)가 더 잘할 수 있는 방법에 대한 아이디어

응답 형식 (반드시 JSON만):
{
    "type": "insight|learning|action|self_improve",
    "title": "제안 제목 (한줄)",
    "content": "제안 내용 (3~5줄, 구체적으로)",
    "why": "왜 이 제안을 하는지 (1줄)",
    "should_share": true/false
}

should_share가 false이면 로그에만 기록합니다.
정말 유저에게 가치가 있을 때만 should_share를 true로 하세요.
매일 제안을 보내니 질보다 양에 집착하지 마세요.""",
            user_prompt=f"""현재: {context['current_time']} ({context['weekday']}요일)

유저의 최근 관심사/대화:
{user_context[:1000] if user_context else '아직 충분한 대화 데이터 없음'}

최근 작업 경험:
{experience if experience else '아직 경험 데이터 없음'}

나의 현재 목표:
{json.dumps(self._state.get('goals', []), ensure_ascii=False)}""",
        )

        try:
            clean = proposal.strip()
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0]
            parsed = json.loads(clean)

            initiative = {
                "date": context["today"],
                "type": parsed.get("type", "unknown"),
                "title": parsed.get("title", ""),
                "content": parsed.get("content", ""),
                "shared": parsed.get("should_share", False),
                "timestamp": context["current_time"],
            }
            self._save_initiative(initiative)

            type_emoji = {
                "insight": "💡", "learning": "📚",
                "action": "🎯", "self_improve": "🔧",
            }
            emoji = type_emoji.get(parsed.get("type"), "💡")

            if parsed.get("should_share"):
                await self.slack.send_message(
                    "ai-agents-general",
                    f"{emoji} *Agent 01의 제안*\n\n"
                    f"*{parsed.get('title', '')}*\n\n"
                    f"{parsed.get('content', '')}\n\n"
                    f"_{parsed.get('why', '')}_",
                )
                self._state["insights_shared"] = self._state.get("insights_shared", 0) + 1
                logger.info(f"[proactive] Initiative shared: {parsed.get('title', '')[:50]}")
            else:
                # 로그에만 기록
                await self.slack.send_message(
                    "ai-agent-logs",
                    f"{emoji} *[이니셔티브 기록]* {parsed.get('title', '')}\n"
                    f"{parsed.get('content', '')[:200]}",
                )

        except (json.JSONDecodeError, KeyError) as e:
            logger.debug(f"[proactive] Initiative parse error: {e}")

        self._state["last_initiative_date"] = context["today"]
        self._state["initiative_count"] = self._state.get("initiative_count", 0) + 1
        self._save_state()

    # ── 유틸리티 ──────────────────────────────────────

    def _hours_since(self, timestamp_str: str) -> float:
        """주어진 시간 문자열로부터 경과 시간(시) 계산"""
        try:
            ts = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M")
            ts = ts.replace(tzinfo=KST)
            diff = datetime.now(KST) - ts
            return diff.total_seconds() / 3600
        except (ValueError, TypeError):
            return 999  # 파싱 실패 시 오래된 것으로 간주
