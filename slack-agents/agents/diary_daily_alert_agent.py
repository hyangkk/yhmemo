"""
생각일기 매일 분석알림 에이전트 (Diary Daily Alert Agent)

역할:
- 매일 밤 10시(KST) 노션 '생각일기' DB에서 4개 구간의 글을 조회
  1. 오늘: 최근 24시간 작성 글
  2. 어제: 24~48시간 전 작성 글
  3. 그제: 48~72시간 전 작성 글
  4. 과거: 최근 5년(60개월) 중 랜덤 1개
- Claude AI로 각 구간별 요약 + 종합 분석 생성
- 슬랙 '명언-한마디' 채널에 전송
"""

import asyncio
import json
import logging
import random
from datetime import datetime, timezone, timedelta

from core.base_agent import BaseAgent

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

CHANNEL_QUOTE = "C0AJUJTHJGL"  # 명언-한마디 채널


class DiaryDailyAlertAgent(BaseAgent):
    """매일 밤 10시 생각일기 분석알림 에이전트"""

    def __init__(self, diary_db_id: str = "", **kwargs):
        super().__init__(
            name="diary_daily_alert",
            description="매일 밤 10시 생각일기 4개 구간 분석알림 (오늘/어제/그제/과거 랜덤)",
            slack_channel=CHANNEL_QUOTE,
            loop_interval=60,  # 1분마다 체크 (22시 정각에만 실행)
            **kwargs,
        )
        self._diary_db_id = diary_db_id
        self._last_sent_date: str | None = None  # "YYYY-MM-DD"

    # ── Observe ──────────────────────────────────────────

    async def observe(self) -> dict | None:
        now = datetime.now(KST)

        # 밤 10시 정각(22:00~22:05)에만 실행
        if now.hour != 22 or now.minute > 5:
            return None

        today_str = now.strftime("%Y-%m-%d")
        if self._last_sent_date == today_str:
            return None

        if not self._diary_db_id or not self.notion:
            logger.warning("[diary_daily_alert] diary_db_id=%s, notion=%s", bool(self._diary_db_id), bool(self.notion))
            return None

        logger.info("[diary_daily_alert] 밤 10시 — 4개 구간 생각일기 조회 시작")

        # 1. 오늘 글 (0~24시간)
        today_pages = await self._fetch_pages_in_range(0, 24)
        logger.info(f"  오늘 글: {len(today_pages)}개")

        # 2. 어제 글 (24~48시간)
        yesterday_pages = await self._fetch_pages_in_range(24, 48)
        logger.info(f"  어제 글: {len(yesterday_pages)}개")

        # 3. 그제 글 (48~72시간)
        day_before_pages = await self._fetch_pages_in_range(48, 72)
        logger.info(f"  그제 글: {len(day_before_pages)}개")

        # 4. 과거 랜덤 (72시간 이전 ~ 5년 이내)
        random_old_pages = await self._fetch_random_old()
        logger.info(f"  과거 랜덤: {len(random_old_pages)}개")

        total = len(today_pages) + len(yesterday_pages) + len(day_before_pages) + len(random_old_pages)
        if total == 0:
            logger.info("[diary_daily_alert] 모든 구간에서 항목 없음. 발송 생략.")
            self._last_sent_date = today_str
            return None

        # 각 구간별 내용 수집
        sections = {
            "today": await self._collect_entries(today_pages),
            "yesterday": await self._collect_entries(yesterday_pages),
            "day_before": await self._collect_entries(day_before_pages),
            "random_old": await self._collect_entries(random_old_pages),
        }

        return {
            "sections": sections,
            "now": now,
            "today_str": today_str,
        }

    # ── Think ────────────────────────────────────────────

    async def think(self, context: dict) -> dict | None:
        sections = context["sections"]

        # 구간별 텍스트 구성
        section_labels = {
            "today": "📌 오늘 글 (최근 24시간)",
            "yesterday": "📎 어제 글 (24~48시간 전)",
            "day_before": "📂 그제 글 (48~72시간 전)",
            "random_old": "🎲 과거 글 (5년간 랜덤)",
        }

        entries_text = ""
        for key in ["today", "yesterday", "day_before", "random_old"]:
            entries = sections.get(key, [])
            label = section_labels[key]
            entries_text += f"\n\n=== {label} ==="
            if not entries:
                entries_text += "\n(해당 구간 글 없음)"
            else:
                for i, e in enumerate(entries, 1):
                    entries_text += f"\n\n[{i}] {e['title']} ({e['created_kst']})\n"
                    if e["content"]:
                        entries_text += e["content"][:800]

        system_prompt = """당신은 사용자의 생각일기를 분석하여 따뜻하고 통찰력 있는 요약을 작성하는 전문가입니다.
사용자가 자신의 생각 흐름을 되돌아보고, 과거의 자신과 비교하며 성장을 느낄 수 있게 도와주세요."""

        user_prompt = f"""다음은 생각일기를 4개 구간으로 나눈 것입니다.
{entries_text}

---
각 구간별 요약과 종합 분석을 작성해주세요. 반드시 아래 JSON 형식으로만 응답하세요.

분석 규칙:
- 각 구간별 핵심 내용을 1~2문장으로 요약
- 글이 없는 구간은 summary를 빈 문자열로
- 과거 글(random_old)은 현재 상황과 비교하여 변화/성장 포인트 짚기
- overall은 3일간의 흐름 + 과거 대비 종합 인사이트 (2~3문장)
- 한 가지 핵심 메시지(one_liner)를 짧고 임팩트 있게

{{
  "today": "오늘 글 핵심 요약",
  "yesterday": "어제 글 핵심 요약",
  "day_before": "그제 글 핵심 요약",
  "random_old": "과거 글 요약 + 현재와의 비교",
  "overall": "3일간 흐름 + 과거 대비 종합 인사이트 (2~3문장)",
  "one_liner": "오늘의 핵심 메시지 한 줄"
}}"""

        result_text = await self.ai_think(system_prompt, user_prompt)

        try:
            clean = result_text.strip()
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0]
            parsed = json.loads(clean.strip())
        except json.JSONDecodeError:
            logger.error(f"[diary_daily_alert] JSON 파싱 실패: {result_text[:200]}")
            return None

        entry_counts = {
            "today": len(sections["today"]),
            "yesterday": len(sections["yesterday"]),
            "day_before": len(sections["day_before"]),
            "random_old": len(sections["random_old"]),
        }

        return {
            "action": "send_daily_alert",
            "analysis": parsed,
            "sections": sections,
            "entry_counts": entry_counts,
            "now": context["now"],
            "today_str": context["today_str"],
        }

    # ── Act ──────────────────────────────────────────────

    async def act(self, decision: dict):
        if decision.get("action") != "send_daily_alert":
            return

        message = self._format_message(decision)
        await self._reply(CHANNEL_QUOTE, message)
        logger.info("[diary_daily_alert] 밤 10시 분석알림 발송 완료")

        self._last_sent_date = decision["today_str"]

    # ── 수동 실행 ────────────────────────────────────────

    async def run_once(self, channel: str = None, thread_ts: str = None):
        """슬랙 명령어로 즉시 분석알림 실행"""
        if not self._diary_db_id or not self.notion:
            return "노션 연동이 안 되어 있어요."

        now = datetime.now(KST)

        today_pages = await self._fetch_pages_in_range(0, 24)
        yesterday_pages = await self._fetch_pages_in_range(24, 48)
        day_before_pages = await self._fetch_pages_in_range(48, 72)
        random_old_pages = await self._fetch_random_old()

        total = len(today_pages) + len(yesterday_pages) + len(day_before_pages) + len(random_old_pages)
        if total == 0:
            return "최근 3일간 생각일기가 없어요."

        sections = {
            "today": await self._collect_entries(today_pages),
            "yesterday": await self._collect_entries(yesterday_pages),
            "day_before": await self._collect_entries(day_before_pages),
            "random_old": await self._collect_entries(random_old_pages),
        }

        context = {"sections": sections, "now": now, "today_str": now.strftime("%Y-%m-%d")}
        decision = await self.think(context)
        if not decision:
            return "분석 생성에 실패했어요."

        message = self._format_message(decision)
        target = channel or CHANNEL_QUOTE
        await self._reply(target, message, thread_ts=thread_ts)
        return None  # 성공

    # ── 내부 헬퍼 ────────────────────────────────────────

    async def _fetch_pages_in_range(self, start_hours_ago: int, end_hours_ago: int) -> list:
        """start_hours_ago ~ end_hours_ago 범위의 글 조회"""
        now_utc = datetime.now(timezone.utc)
        after = (now_utc - timedelta(hours=end_hours_ago)).isoformat()
        before = (now_utc - timedelta(hours=start_hours_ago)).isoformat()

        filter_dict = {
            "and": [
                {"timestamp": "created_time", "created_time": {"after": after}},
                {"timestamp": "created_time", "created_time": {"on_or_before": before}},
            ]
        }
        try:
            return await self.notion.query_database_all(
                self._diary_db_id,
                filter_dict=filter_dict,
                sorts=[{"timestamp": "created_time", "direction": "descending"}],
            )
        except Exception as e:
            logger.error(f"[diary_daily_alert] Notion 조회 오류: {e}")
            return []

    async def _fetch_random_old(self) -> list:
        """72시간 이전 ~ 5년(60개월) 이내 랜덤 1개"""
        now_utc = datetime.now(timezone.utc)
        after = (now_utc - timedelta(days=30 * 60)).isoformat()
        before = (now_utc - timedelta(hours=72)).isoformat()

        filter_dict = {
            "and": [
                {"timestamp": "created_time", "created_time": {"after": after}},
                {"timestamp": "created_time", "created_time": {"on_or_before": before}},
            ]
        }
        try:
            all_pages = await self.notion.query_database_all(
                self._diary_db_id,
                filter_dict=filter_dict,
                sorts=[{"timestamp": "created_time", "direction": "descending"}],
            )
            if not all_pages:
                return []
            return [random.choice(all_pages)]
        except Exception as e:
            logger.error(f"[diary_daily_alert] 과거 글 조회 오류: {e}")
            return []

    async def _collect_entries(self, pages: list) -> list:
        """페이지 목록에서 제목 + 본문 수집"""
        entries = []
        for page in pages:
            title = self._extract_title(page)
            page_id = page.get("id", "")
            content = await self.notion.get_page_text(page_id) if page_id else ""
            created_str = page.get("created_time", "")
            created_kst = ""
            page_url = page.get("url", "")
            if created_str:
                try:
                    dt = datetime.fromisoformat(created_str.replace("Z", "+00:00")).astimezone(KST)
                    created_kst = dt.strftime("%m/%d %H:%M")
                except ValueError:
                    pass
            entries.append({
                "title": title,
                "content": content,
                "created_kst": created_kst,
                "page_url": page_url,
            })
        return entries

    @staticmethod
    def _extract_title(page: dict) -> str:
        for prop in page.get("properties", {}).values():
            if prop.get("type") == "title":
                return "".join(rt.get("plain_text", "") for rt in prop.get("title", [])).strip() or "(제목 없음)"
        return "(제목 없음)"

    def _format_message(self, decision: dict) -> str:
        """슬랙 메시지 포맷"""
        analysis = decision["analysis"]
        entry_counts = decision["entry_counts"]
        sections = decision["sections"]
        now = decision["now"]

        time_str = now.strftime("%m/%d %H:%M")
        total = sum(entry_counts.values())

        lines = [f"*📔 생각일기 분석알림 · {time_str} KST*"]
        lines.append(f"_매일 밤 10시 · 총 {total}개 항목_\n")

        # 구간별 요약
        section_config = [
            ("today", "📌 오늘", entry_counts["today"]),
            ("yesterday", "📎 어제", entry_counts["yesterday"]),
            ("day_before", "📂 그제", entry_counts["day_before"]),
            ("random_old", "🎲 과거 랜덤", entry_counts["random_old"]),
        ]

        for key, label, count in section_config:
            summary = analysis.get(key, "")
            section_entries = sections.get(key, [])
            if not summary and count == 0:
                continue

            lines.append(f"*{label} ({count}개)*")
            # 글 제목 나열
            for entry in section_entries:
                title_line = f"  • {entry['title']}"
                if entry.get("created_kst"):
                    title_line += f" _{entry['created_kst']}_"
                if entry.get("page_url"):
                    title_line += f"  <{entry['page_url']}|보기>"
                lines.append(title_line)
            if summary:
                lines.append(f"  → {summary}")
            lines.append("")

        # 종합 분석
        overall = analysis.get("overall", "")
        if overall:
            lines.append(f"*📊 종합 분석*\n{overall}\n")

        # 핵심 메시지
        one_liner = analysis.get("one_liner", "")
        if one_liner:
            lines.append(f"> 💡 _{one_liner}_")

        lines.append("\n`⏰ 매일 밤 10시 자동 발송`")

        return "\n".join(lines)
