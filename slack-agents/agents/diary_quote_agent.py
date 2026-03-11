"""
생각일기 명언 에이전트 (Diary Quote Agent)

역할:
- 6시간마다(0시, 6시, 12시, 18시) 노션 '생각일기' DB에서 최근 60개월간 글을 조회
- 랜덤으로 하나를 골라 각오, 방향, 목표, 사고방식 등의 핵심 문장을 추출
- 슬랙 '명언' 채널에 전송하여 자신의 기록을 잊지 않도록 일깨움

자율 행동:
- Observe: 6시간 간격(0시, 6시, 12시, 18시) 확인 + 노션 생각일기 DB에서 최근 60개월 글 조회
- Think: AI로 랜덤 선택된 글에서 각오/목표/사고방식 핵심 문장 추출
- Act: 슬랙 명언 채널에 전송
"""

import asyncio
import json
import logging
import os
import random
from datetime import datetime, timezone, timedelta

from core.base_agent import BaseAgent

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

# 이력 파일
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
DIARY_QUOTE_HISTORY_FILE = os.path.join(DATA_DIR, "diary_quote_history.json")


class DiaryQuoteAgent(BaseAgent):
    """노션 생각일기에서 핵심 문장을 추출하여 6시간마다 슬랙에 전송하는 에이전트"""

    def __init__(self, diary_db_id: str = "", target_channel: str = "C0AJUJTHJGL", **kwargs):  # 명언-한마디
        super().__init__(
            name="diary_quote",
            description="노션 생각일기에서 각오, 방향, 목표, 사고방식 등의 핵심 문장을 6시간마다 추출하여 슬랙에 전송",
            slack_channel=target_channel,
            loop_interval=60,  # 1분마다 체크 (정각에만 실행)
            **kwargs,
        )
        self._diary_db_id = diary_db_id
        self._target_channel = target_channel
        self._last_sent_slot: str | None = None  # "HH:00" or "HH:30"
        self._quote_history: list[dict] = self._load_history()

    def _load_history(self) -> list[dict]:
        try:
            with open(DIARY_QUOTE_HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.loads(f.read())
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def _save_history(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        # 최근 500개만 유지 (페이지 ID 기반 중복 방지용)
        self._quote_history = self._quote_history[-500:]
        with open(DIARY_QUOTE_HISTORY_FILE, "w", encoding="utf-8") as f:
            f.write(json.dumps(self._quote_history, ensure_ascii=False, indent=2))

    def _recently_used_page_ids(self) -> set[str]:
        """최근 7일간 사용한 페이지 ID 집합 (같은 글 반복 방지)"""
        cutoff = (datetime.now(KST) - timedelta(days=7)).isoformat()
        return {
            h["page_id"]
            for h in self._quote_history
            if h.get("sent_at", "") >= cutoff
        }

    # ── Observe ──────────────────────────────────────────

    async def observe(self) -> dict | None:
        now = datetime.now(KST)
        current_hour = now.hour

        # 6시간 간격(0시, 6시, 12시, 18시) 정각(0~5분)에 실행
        if current_hour % 6 == 0 and 0 <= now.minute <= 5:
            current_slot = f"{current_hour}:00"
        else:
            return None

        # 이미 이번 슬롯에 보냈으면 스킵
        if self._last_sent_slot == current_slot:
            return None

        # 노션 DB ID 없으면 스킵
        if not self._diary_db_id or not self.notion:
            logger.warning("[diary_quote] Skipping: diary_db_id=%s, notion=%s", bool(self._diary_db_id), bool(self.notion))
            return None

        # 최근 60개월(5년)간의 글 조회
        five_years_ago = (now - timedelta(days=1825)).strftime("%Y-%m-%dT00:00:00+09:00")
        filter_dict = {
            "timestamp": "created_time",
            "created_time": {"after": five_years_ago},
        }

        pages = await self.notion.query_database_all(
            self._diary_db_id,
            filter_dict=filter_dict,
            sorts=[{"timestamp": "created_time", "direction": "descending"}],
        )

        if not pages:
            logger.warning("[diary_quote] No diary entries found in last 60 months (db=%s)", self._diary_db_id)
            return None

        logger.info("[diary_quote] Found %d diary entries, slot=%s", len(pages), current_slot)

        # 최근 7일간 이미 사용한 페이지 제외
        used_ids = self._recently_used_page_ids()
        candidates = [p for p in pages if p.get("id") not in used_ids]

        # 후보가 없으면 전체에서 선택 (순환)
        if not candidates:
            candidates = pages

        # 랜덤으로 하나 선택
        selected = random.choice(candidates)

        # 제목 추출
        title = "(제목 없음)"
        for prop in selected.get("properties", {}).values():
            if prop.get("type") == "title":
                title = "".join(
                    rt.get("plain_text", "") for rt in prop.get("title", [])
                ).strip() or "(제목 없음)"
                break

        # 페이지 내용 추출
        page_id = selected.get("id", "")
        content = await self.notion.get_page_text(page_id)

        # 제목 + 본문 합치기 (본문 없이 제목만 있는 페이지도 활용)
        full_text = f"{title}\n{content}" if content.strip() else title
        if len(full_text.strip()) < 10:
            logger.info(f"[diary_quote] Selected page too short: {title}")
            return None

        created_time = selected.get("created_time", "")
        page_url = selected.get("url", "")

        return {
            "current_time": now.strftime("%Y-%m-%d %H:%M"),
            "current_hour": current_hour,
            "page_id": page_id,
            "page_url": page_url,
            "title": title,
            "content": full_text[:3000],  # 토큰 절약
            "created_time": created_time,
            "recent_quotes": [h.get("quote", "") for h in self._quote_history[-20:]],
        }

    # ── Think ────────────────────────────────────────────

    async def think(self, context: dict) -> dict | None:
        title = context.get("title", "")
        content = context.get("content", "")
        recent_quotes = context.get("recent_quotes", [])

        recent_text = "\n".join(f"- {q}" for q in recent_quotes if q) if recent_quotes else "(아직 없음)"

        system_prompt = f"""당신은 사용자의 생각일기에서 핵심 문장을 추출하는 전문가입니다.

사용자가 직접 쓴 생각일기 내용에서, 다음과 같은 성격의 **핵심 한 문장**을 골라주세요:
- 각오, 결심, 다짐
- 방향성, 비전
- 목표, 계획
- 사고방식, 마인드셋
- 깨달음, 통찰
- 자기 자신에게 하는 말

규칙:
1. 원문에서 직접 발췌하거나, 원문의 의미를 살려 1~2문장으로 정리
2. 사용자 본인의 말투와 느낌을 최대한 살릴 것
3. 너무 길지 않게 (1~2문장, 최대 100자)
4. 일기의 핵심 메시지를 담을 것
5. 이전에 보낸 문구와 중복되지 않을 것

현재 시각: {context['current_time']}

반드시 아래 JSON 형식으로만 응답하세요:
{{
  "quote": "추출한 핵심 문장",
  "context_note": "이 문장이 담고 있는 의미 (15자 이내)",
  "category": "각오|방향|목표|사고방식|깨달음|다짐 중 하나"
}}"""

        user_prompt = f"""생각일기 제목: {title}

내용:
{content}

이전에 보낸 문구 (중복 금지):
{recent_text}"""

        result_text = await self.ai_think(system_prompt, user_prompt)

        try:
            clean = result_text.strip()
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0]
            parsed = json.loads(clean.strip())
        except json.JSONDecodeError:
            logger.error(f"[diary_quote] Failed to parse AI response: {result_text[:200]}")
            return None

        quote = parsed.get("quote", "").strip()
        if not quote:
            return None

        return {
            "action": "send_diary_quote",
            "quote": quote,
            "context_note": parsed.get("context_note", ""),
            "category": parsed.get("category", ""),
            "title": title,
            "created_time": context.get("created_time", ""),
            "page_id": context.get("page_id", ""),
            "page_url": context.get("page_url", ""),
            "hour": context["current_hour"],
        }

    # ── Act ──────────────────────────────────────────────

    async def act(self, decision: dict):
        if decision.get("action") != "send_diary_quote":
            return

        message = self._format_message(decision)
        await self._reply(self._target_channel, message)
        logger.info(f"[diary_quote] Sent diary quote: {decision['quote'][:50]}...")

        # 이번 슬롯 전송 완료 표시
        now = datetime.now(KST)
        self._last_sent_slot = f"{now.hour}:00"

        # 이력 저장
        self._quote_history.append({
            "quote": decision["quote"],
            "title": decision["title"],
            "page_id": decision["page_id"],
            "category": decision.get("category", ""),
            "sent_at": datetime.now(KST).isoformat(),
        })
        self._save_history()

    async def run_once(self, channel: str = None, thread_ts: str = None):
        """수동 실행: 슬랙 명령어로 즉시 생각일기 한 마디 전송"""
        if not self._diary_db_id or not self.notion:
            return "노션 연동이 안 되어 있어요."

        now = datetime.now(KST)
        five_years_ago = (now - timedelta(days=1825)).strftime("%Y-%m-%dT00:00:00+09:00")

        pages = await self.notion.query_database_all(
            self._diary_db_id,
            filter_dict={"timestamp": "created_time", "created_time": {"after": five_years_ago}},
            sorts=[{"timestamp": "created_time", "direction": "descending"}],
        )
        if not pages:
            return "생각일기가 없어요."

        used_ids = self._recently_used_page_ids()
        candidates = [p for p in pages if p.get("id") not in used_ids] or pages
        selected = random.choice(candidates)

        title = "(제목 없음)"
        for prop in selected.get("properties", {}).values():
            if prop.get("type") == "title":
                title = "".join(rt.get("plain_text", "") for rt in prop.get("title", [])).strip() or "(제목 없음)"
                break

        page_id = selected.get("id", "")
        content = await self.notion.get_page_text(page_id)
        full_text = f"{title}\n{content}" if content.strip() else title

        if len(full_text.strip()) < 10:
            return "선택된 일기가 너무 짧아요. 다시 시도해주세요."

        context = {
            "current_time": now.strftime("%Y-%m-%d %H:%M"),
            "current_hour": now.hour,
            "page_id": page_id,
            "page_url": selected.get("url", ""),
            "title": title,
            "content": full_text[:3000],
            "created_time": selected.get("created_time", ""),
            "recent_quotes": [h.get("quote", "") for h in self._quote_history[-20:]],
        }

        decision = await self.think(context)
        if not decision:
            return "핵심 문장 추출에 실패했어요."

        message = self._format_message(decision)
        target = channel or self._target_channel
        await self._reply(target, message, thread_ts=thread_ts)

        self._quote_history.append({
            "quote": decision["quote"],
            "title": decision["title"],
            "page_id": decision["page_id"],
            "category": decision.get("category", ""),
            "sent_at": datetime.now(KST).isoformat(),
        })
        self._save_history()
        return None  # 성공

    def _format_message(self, decision: dict) -> str:
        """생각일기 명언 메시지 포맷"""
        quote = decision.get("quote", "")
        category = decision.get("category", "")
        context_note = decision.get("context_note", "")
        title = decision.get("title", "")
        created_time = decision.get("created_time", "")
        page_url = decision.get("page_url", "")

        # 작성일 포맷
        date_str = ""
        if created_time:
            try:
                dt = datetime.fromisoformat(created_time.replace("Z", "+00:00")).astimezone(KST)
                date_str = dt.strftime("%Y.%m.%d")
            except (ValueError, TypeError):
                pass

        # 카테고리 이모지 매핑
        emoji_map = {
            "각오": "🔥",
            "방향": "🧭",
            "목표": "🎯",
            "사고방식": "💡",
            "깨달음": "✨",
            "다짐": "💪",
        }
        emoji = emoji_map.get(category, "📝")

        # 원문 보기 링크
        link = f"<{page_url}|원문 보기>" if page_url else ""

        message = f"{emoji} *나의 생각일기에서*\n\n"
        message += f"> _{quote}_\n"
        if date_str:
            message += f"> — {date_str}"
        if link:
            message += f"  {link}"
        if context_note:
            message += f"\n\n💭 _{context_note}_"
        message += "\n\n`⏰ 6시간마다 자동 발송`"
        return message
