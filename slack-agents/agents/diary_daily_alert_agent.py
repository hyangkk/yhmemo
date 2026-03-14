"""
생각일기 매일 분석알림 에이전트 (Diary Daily Alert Agent)

역할:
- 매일 밤 10시(KST) 노션 '생각일기' DB에서 4개 구간의 글을 조회
  1. 오늘: 최근 24시간 작성 글
  2. 어제: 24~48시간 전 작성 글
  3. 그제: 48~72시간 전 작성 글
  4. 과거: 최근 2년(24개월) 중 랜덤 1개
- 각 글의 한줄요약(제목) + 원문 링크로 슬랙 '명언-한마디' 채널에 전송
"""

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

        # KST 현재 시각 기준 슬라이딩 윈도우
        today_pages = await self._fetch_pages_in_range(now, 0, 24)
        logger.info(f"  오늘 글: {len(today_pages)}개")

        yesterday_pages = await self._fetch_pages_in_range(now, 24, 48)
        logger.info(f"  어제 글: {len(yesterday_pages)}개")

        day_before_pages = await self._fetch_pages_in_range(now, 48, 72)
        logger.info(f"  그제 글: {len(day_before_pages)}개")

        # 과거 랜덤 (72시간 이전 ~ 2년 이내)
        random_old_pages = await self._fetch_random_old(now)
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

        # 모든 항목을 모아서 한번에 AI 한줄요약 요청
        all_entries = []
        for key in ["today", "yesterday", "day_before", "random_old"]:
            for entry in sections.get(key, []):
                all_entries.append(entry)

        if all_entries:
            entries_for_ai = []
            for i, e in enumerate(all_entries):
                text = e["title"]
                if e.get("content"):
                    text += "\n" + e["content"][:500]
                entries_for_ai.append(f"[{i}] {text}")

            prompt = "다음 생각일기 항목들을 각각 한 줄(40~60자)로 요약해주세요.\n제목과 본문의 핵심 메시지를 자연스럽게 요약. 반드시 JSON 배열로만 응답.\n\n" + "\n\n".join(entries_for_ai) + '\n\n예: ["요약1", "요약2", ...]'

            result = await self.ai_think("한줄요약 전문가. JSON 배열만 반환.", prompt)
            try:
                clean = result.strip()
                if clean.startswith("```"):
                    clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0]
                summaries = json.loads(clean.strip())
                for i, entry in enumerate(all_entries):
                    if i < len(summaries):
                        entry["summary"] = summaries[i]
            except (json.JSONDecodeError, IndexError):
                logger.warning("[diary_daily_alert] 한줄요약 파싱 실패, 제목 사용")

        entry_counts = {
            "today": len(sections["today"]),
            "yesterday": len(sections["yesterday"]),
            "day_before": len(sections["day_before"]),
            "random_old": len(sections["random_old"]),
        }

        return {
            "action": "send_daily_alert",
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

        today_pages = await self._fetch_pages_in_range(now, 0, 24)
        yesterday_pages = await self._fetch_pages_in_range(now, 24, 48)
        day_before_pages = await self._fetch_pages_in_range(now, 48, 72)
        random_old_pages = await self._fetch_random_old(now)

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

    async def _fetch_pages_in_range(self, now_kst: datetime, start_hours_ago: int, end_hours_ago: int) -> list:
        """KST 현재 시각 기준 start~end시간 전 범위의 글 조회"""
        after = (now_kst - timedelta(hours=end_hours_ago)).astimezone(timezone.utc).isoformat()
        before = (now_kst - timedelta(hours=start_hours_ago)).astimezone(timezone.utc).isoformat()

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

    async def _fetch_random_old(self, now_kst: datetime) -> list:
        """KST 현재 시각 기준 72시간 이전 ~ 2년 이내 랜덤 1개"""
        after = (now_kst - timedelta(days=30 * 24)).astimezone(timezone.utc).isoformat()
        before = (now_kst - timedelta(hours=72)).astimezone(timezone.utc).isoformat()

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
        """페이지 목록에서 제목 + 본문 + 링크 수집"""
        entries = []
        for page in pages:
            title = self._extract_title(page)
            page_id = page.get("id", "")
            content = await self.notion.get_page_text(page_id) if page_id else ""
            page_url = page.get("url", "")
            created = page.get("created_time", "")
            entries.append({"title": title, "content": content, "page_url": page_url, "created_time": created})
        return entries

    @staticmethod
    def _extract_title(page: dict) -> str:
        for prop in page.get("properties", {}).values():
            if prop.get("type") == "title":
                return "".join(rt.get("plain_text", "") for rt in prop.get("title", [])).strip() or "(제목 없음)"
        return "(제목 없음)"

    def _format_message(self, decision: dict) -> str:
        """슬랙 메시지 포맷: 한줄요약(제목) + 원문 링크만"""
        entry_counts = decision["entry_counts"]
        sections = decision["sections"]
        now = decision["now"]

        time_str = now.strftime("%m/%d %H:%M")
        total = sum(entry_counts.values())

        lines = [f"*📔 생각일기 분석알림 · {time_str} KST*"]
        lines.append(f"_총 {total}개 항목_\n")

        section_config = [
            ("today", "📌 오늘"),
            ("yesterday", "📎 어제"),
            ("day_before", "📂 그제"),
            ("random_old", "🎲 랜덤"),
        ]

        for key, label in section_config:
            section_entries = sections.get(key, [])
            count = entry_counts[key]

            lines.append(f"*{label}*")
            if count == 0:
                lines.append("  (없음)")
            else:
                for entry in section_entries:
                    display = entry.get("summary", entry["title"])
                    # 랜덤 구간은 날짜 표시
                    if key == "random_old" and entry.get("created_time"):
                        ct = datetime.fromisoformat(entry["created_time"].replace("Z", "+00:00")).astimezone(KST)
                        display += f" ({ct.strftime('%y.%m.%d')})"
                    if entry.get("page_url"):
                        lines.append(f"  • {display}  <{entry['page_url']}|원문>")
                    else:
                        lines.append(f"  • {display}")
            lines.append("")

        lines.append("`⏰ 매일 밤 10시 자동 발송`")

        return "\n".join(lines)
