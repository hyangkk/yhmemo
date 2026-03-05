"""
명언 에이전트 (Quote Agent)

역할:
- 매 시각(정각)마다 영감을 주는 명언을 슬랙에 전송
- 최근 슬랙 대화를 분석하여 상황에 맞는 명언 선별
- 이전에 보낸 명언과 중복되지 않도록 관리

자율 행동:
- Observe: 현재 시각 확인 + 최근 슬랙 대화 수집
- Think: 대화 맥락에 맞는 명언을 AI로 생성/선별
- Act: 슬랙 채널에 명언 전송
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone, timedelta

from core.base_agent import BaseAgent
from core.message_bus import TaskMessage

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

# 명언 이력 파일
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
QUOTE_HISTORY_FILE = os.path.join(DATA_DIR, "quote_history.json")


class QuoteAgent(BaseAgent):
    """영감을 주는 명언을 매 시각마다 보내주는 에이전트"""

    def __init__(self, target_channel: str = "명언", **kwargs):
        super().__init__(
            name="quote",
            description="매 시각마다 최근 대화 맥락에 맞는 영감을 주는 명언을 보내주는 에이전트",
            slack_channel=target_channel,
            loop_interval=60,  # 1분마다 체크 (정각에만 실행)
            **kwargs,
        )
        self._target_channel = target_channel
        self._last_sent_hour: int | None = None
        self._quote_history: list[str] = self._load_history()

    def _load_history(self) -> list[str]:
        try:
            with open(QUOTE_HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.loads(f.read())
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def _save_history(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        # 최근 200개만 유지
        self._quote_history = self._quote_history[-200:]
        with open(QUOTE_HISTORY_FILE, "w", encoding="utf-8") as f:
            f.write(json.dumps(self._quote_history, ensure_ascii=False, indent=2))

    async def _fetch_recent_messages(self, limit: int = 30) -> list[str]:
        """슬랙 채널에서 최근 메시지들 가져오기"""
        try:
            channel_id = await self.slack._resolve_channel(self._target_channel)
            result = await self.slack.client.conversations_history(
                channel=channel_id, limit=limit
            )
            messages = []
            for msg in result.get("messages", []):
                text = msg.get("text", "").strip()
                if text and not msg.get("bot_id"):
                    messages.append(text)
            return messages
        except Exception as e:
            logger.warning(f"[quote] Failed to fetch recent messages: {e}")
            return []

    # ── Observe ──────────────────────────────────────────

    async def observe(self) -> dict | None:
        now = datetime.now(KST)
        current_hour = now.hour

        # 이미 이번 시각에 보냈으면 스킵
        if self._last_sent_hour == current_hour:
            return None

        # 정각 근처(0~5분)에만 실행
        if now.minute > 5:
            return None

        # 최근 대화 수집
        recent_messages = await self._fetch_recent_messages()

        return {
            "current_time": now.strftime("%Y-%m-%d %H:%M"),
            "current_hour": current_hour,
            "recent_conversations": recent_messages[:20],
            "sent_history": self._quote_history[-30:],
        }

    # ── Think ────────────────────────────────────────────

    async def think(self, context: dict) -> dict | None:
        conversations = context.get("recent_conversations", [])
        sent_history = context.get("sent_history", [])

        conv_text = "\n".join(f"- {msg[:150]}" for msg in conversations) if conversations else "(최근 대화 없음)"
        history_text = "\n".join(f"- {q}" for q in sent_history[-20:]) if sent_history else "(아직 보낸 명언 없음)"

        system_prompt = f"""당신은 영감을 주는 명언을 선별하는 전문가입니다.

슬랙 채널의 최근 대화를 분석하고, 그 맥락에 도움이 될 만한 명언을 하나 골라주세요.

규칙:
1. 대화에서 드러나는 고민, 관심사, 감정에 공감하는 명언을 선택
2. 유명인의 실제 명언이어야 함 (출처 명시)
3. 한국어로 번역하되 원문도 함께 제공
4. 이전에 보낸 명언과 중복되면 안 됨
5. 시간대에 맞는 톤 (아침: 활기, 낮: 집중/동기부여, 저녁: 성찰/위로)
6. 대화가 없거나 맥락이 불분명하면, 그날의 시간대에 맞는 보편적으로 좋은 명언 선택

현재 시각: {context['current_time']}

반드시 아래 JSON 형식으로만 응답하세요:
{{
  "quote_ko": "한국어 명언",
  "quote_original": "원문 명언 (영어 등)",
  "author": "명언의 저자",
  "context_reason": "이 명언을 선택한 이유 (대화 맥락과의 연결, 20자 이내)",
  "emoji": "명언에 어울리는 이모지 1개"
}}"""

        user_prompt = f"""최근 대화:
{conv_text}

이전에 보낸 명언 (중복 금지):
{history_text}"""

        result_text = await self.ai_think(system_prompt, user_prompt)

        try:
            clean = result_text.strip()
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0]
            parsed = json.loads(clean.strip())
        except json.JSONDecodeError:
            logger.error(f"[quote] Failed to parse AI response: {result_text[:200]}")
            return None

        return {
            "action": "send_quote",
            "quote_ko": parsed.get("quote_ko", ""),
            "quote_original": parsed.get("quote_original", ""),
            "author": parsed.get("author", ""),
            "context_reason": parsed.get("context_reason", ""),
            "emoji": parsed.get("emoji", ""),
            "hour": context["current_hour"],
        }

    # ── Act ──────────────────────────────────────────────

    async def act(self, decision: dict):
        if decision.get("action") != "send_quote":
            return

        quote_ko = decision["quote_ko"]
        quote_original = decision["quote_original"]
        author = decision["author"]
        emoji = decision.get("emoji", "")
        reason = decision.get("context_reason", "")

        message = self._format_message(decision)
        await self._reply(self._target_channel, message)
        logger.info(f"[quote] Sent quote by {author}")

        # 이력 저장
        self._quote_history.append(f"{quote_ko} — {author}")
        self._save_history()

    def _format_message(self, decision: dict) -> str:
        """명언 메시지 포맷"""
        emoji = decision.get("emoji", "")
        quote_ko = decision.get("quote_ko", "")
        quote_original = decision.get("quote_original", "")
        author = decision.get("author", "")
        reason = decision.get("context_reason", "")

        message = f"{emoji} *오늘의 명언*\n\n"
        message += f"> _{quote_ko}_\n"
        if quote_original:
            message += f"> {quote_original}\n"
        message += f"> — *{author}*"
        if reason:
            message += f"\n\n💭 _{reason}_"
        return message

        # 이번 시각 전송 완료 표시
        self._last_sent_hour = decision["hour"]
