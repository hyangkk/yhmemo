"""
오늘의 운세 에이전트 (Fortune Agent)

역할:
- 12시간마다 (오전 8시, 오후 8시 KST) 오늘의 운세를 슬랙에 전송
- 띠별/별자리별 운세를 AI로 생성
- 재미있고 유쾌한 톤으로 하루의 기운을 전달

자율 행동:
- Observe: 현재 시각 확인, 전송 시간대 판단
- Think: AI로 오늘의 운세 생성
- Act: 슬랙 채널에 운세 전송
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
FORTUNE_HISTORY_FILE = os.path.join(DATA_DIR, "fortune_history.json")

# 오전 8시, 오후 8시에 전송
SEND_HOURS = (8, 20)


class FortuneAgent(BaseAgent):
    """12시간마다 오늘의 운세를 보내주는 에이전트"""

    def __init__(self, target_channel: str = "ai-agents-general", **kwargs):
        super().__init__(
            name="fortune",
            description="12시간마다 (오전 8시, 오후 8시) 오늘의 운세를 보내주는 에이전트",
            slack_channel=target_channel,
            loop_interval=60,  # 1분마다 체크 (정시에만 실행)
            **kwargs,
        )
        self._target_channel = target_channel
        self._last_sent_key: str | None = None  # "YYYY-MM-DD-HH" 형태
        self._fortune_history: list[dict] = self._load_history()

    def _load_history(self) -> list[dict]:
        try:
            with open(FORTUNE_HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.loads(f.read())
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def _save_history(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        self._fortune_history = self._fortune_history[-100:]
        with open(FORTUNE_HISTORY_FILE, "w", encoding="utf-8") as f:
            f.write(json.dumps(self._fortune_history, ensure_ascii=False, indent=2))

    # ── Observe ──────────────────────────────────────────

    async def observe(self) -> dict | None:
        now = datetime.now(KST)
        current_hour = now.hour

        # 전송 시간대가 아니면 스킵
        if current_hour not in SEND_HOURS:
            return None

        # 정각 근처(0~5분)에만 실행
        if now.minute > 5:
            return None

        # 이미 이 시간대에 보냈으면 스킵
        send_key = now.strftime("%Y-%m-%d") + f"-{current_hour}"
        if self._last_sent_key == send_key:
            return None

        return {
            "current_time": now.strftime("%Y-%m-%d %H:%M"),
            "current_hour": current_hour,
            "date_str": now.strftime("%Y년 %m월 %d일"),
            "weekday": ["월", "화", "수", "목", "금", "토", "일"][now.weekday()],
            "period": "아침" if current_hour == 8 else "저녁",
            "send_key": send_key,
            "recent_fortunes": [h.get("summary", "") for h in self._fortune_history[-10:]],
        }

    # ── Think ────────────────────────────────────────────

    async def think(self, context: dict) -> dict | None:
        period = context["period"]
        date_str = context["date_str"]
        weekday = context["weekday"]
        recent = context.get("recent_fortunes", [])

        recent_text = "\n".join(f"- {f}" for f in recent) if recent else "(없음)"

        system_prompt = f"""당신은 유쾌하고 따뜻한 운세 전문가입니다.

오늘의 운세를 작성해주세요.

규칙:
1. 전체 운세 (모든 사람에게 해당하는 오늘의 기운/메시지)
2. 12간지 중 3개를 랜덤하게 골라 띠별 한줄 운세 (쥐, 소, 호랑이, 토끼, 용, 뱀, 말, 양, 원숭이, 닭, 개, 돼지)
3. 오늘의 럭키 아이템, 럭키 컬러, 럭키 넘버 포함
4. {period} 시간대에 맞는 톤 (아침: 활기차고 희망적, 저녁: 편안하고 성찰적)
5. 유머와 위트를 섞되 너무 가볍지 않게
6. 최근 보낸 운세와 내용이 겹치지 않게

오늘: {date_str} ({weekday}요일) {period}

최근 보낸 운세 (중복 방지):
{recent_text}

반드시 아래 JSON 형식으로만 응답하세요:
{{
  "greeting": "{period} 인사 한마디 (15자 이내)",
  "overall": "오늘의 전체 운세 메시지 (3~4문장)",
  "zodiac": [
    {{"animal": "띠 이름", "emoji": "동물 이모지", "fortune": "한줄 운세"}},
    {{"animal": "띠 이름", "emoji": "동물 이모지", "fortune": "한줄 운세"}},
    {{"animal": "띠 이름", "emoji": "동물 이모지", "fortune": "한줄 운세"}}
  ],
  "lucky_item": "럭키 아이템",
  "lucky_color": "럭키 컬러",
  "lucky_number": 숫자,
  "closing": "마무리 한마디 (격려/응원, 15자 이내)"
}}"""

        result_text = await self.ai_think(system_prompt, f"{date_str} ({weekday}요일) {period} 운세를 작성해주세요.")

        try:
            clean = result_text.strip()
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0]
            parsed = json.loads(clean.strip())
        except json.JSONDecodeError:
            logger.error(f"[fortune] Failed to parse AI response: {result_text[:200]}")
            return None

        return {
            "action": "send_fortune",
            "data": parsed,
            "send_key": context["send_key"],
            "date_str": date_str,
            "weekday": weekday,
            "period": period,
        }

    # ── Act ──────────────────────────────────────────────

    async def act(self, decision: dict):
        if decision.get("action") != "send_fortune":
            return

        data = decision["data"]
        message = self._format_message(decision)
        await self._reply(self._target_channel, message)
        logger.info(f"[fortune] Sent {decision['period']} fortune for {decision['date_str']}")

        self._last_sent_key = decision["send_key"]

        self._fortune_history.append({
            "date": decision["date_str"],
            "period": decision["period"],
            "summary": data.get("overall", "")[:100],
        })
        self._save_history()

    def _format_message(self, decision: dict) -> str:
        data = decision["data"]
        date_str = decision["date_str"]
        weekday = decision["weekday"]
        period = decision["period"]

        greeting = data.get("greeting", "")
        overall = data.get("overall", "")
        zodiac = data.get("zodiac", [])
        lucky_item = data.get("lucky_item", "")
        lucky_color = data.get("lucky_color", "")
        lucky_number = data.get("lucky_number", "")
        closing = data.get("closing", "")

        msg = f"🔮 *{date_str} ({weekday}요일) {period} 운세*\n\n"
        if greeting:
            msg += f"_{greeting}_\n\n"
        msg += f"{overall}\n\n"

        if zodiac:
            msg += "*띠별 운세*\n"
            for z in zodiac:
                emoji = z.get("emoji", "")
                animal = z.get("animal", "")
                fortune = z.get("fortune", "")
                msg += f"> {emoji} *{animal}띠*: {fortune}\n"
            msg += "\n"

        msg += f"🍀 럭키 아이템: *{lucky_item}*\n"
        msg += f"🎨 럭키 컬러: *{lucky_color}*\n"
        msg += f"🔢 럭키 넘버: *{lucky_number}*\n"

        if closing:
            msg += f"\n✨ _{closing}_"

        return msg
