"""
정보 선별 에이전트 (Curator Agent)

역할:
- 수집된 정보 중 사용자에게 가치 있는 것을 선별
- 사용자 피드백(슬랙 이모지)을 학습하여 선별 기준 고도화
- 부족한 정보 영역 파악 시 수집 에이전트에 추가 요청

자율 행동:
- Observe: 새로 수집된 정보 + 사용자 피드백 확인
- Think: 정보의 관련성/가치 판단, 부족한 영역 파악
- Act: 선별 → 요약 → 노션 저장 → 슬랙 브리핑
"""

import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from core.base_agent import BaseAgent
from core.message_bus import TaskMessage
from integrations.notion_client import NotionClient

logger = logging.getLogger(__name__)


class CuratorAgent(BaseAgent):
    """정보 선별 에이전트"""

    def __init__(self, notion_db_id: str = "", **kwargs):
        super().__init__(
            name="curator",
            description="수집된 정보를 분석하고 사용자에게 가치 있는 것을 선별하는 에이전트. "
                        "피드백을 학습하여 선별 기준을 지속 개선.",
            slack_channel="ai-curator",
            loop_interval=900,  # 15분 간격
            **kwargs,
        )
        self._notion_db_id = notion_db_id
        self._new_articles_buffer: list[dict] = []
        self._user_preferences: dict = {}

        # 수집 에이전트의 new_articles 이벤트 구독
        self.bus.subscribe("new_articles", self._on_new_articles)

    async def _on_new_articles(self, task: TaskMessage):
        """수집 에이전트에서 새 정보 도착 시 → 즉시 선별"""
        items = task.payload.get("items", [])
        self._new_articles_buffer.extend(items)
        logger.info(f"[curator] Received {len(items)} new articles from {task.from_agent}")

        # 버퍼에 충분한 기사가 쌓이면 즉시 선별 실행
        if len(self._new_articles_buffer) >= 5:
            logger.info(f"[curator] Auto-curating {len(self._new_articles_buffer)} articles")
            try:
                context = await self.observe()
                if context:
                    decision = await self.think(context)
                    if decision:
                        await self.act(decision)
            except Exception as e:
                logger.error(f"[curator] Auto-curate error: {e}")

    # ── Observe: 환경 감지 ─────────────────────────────

    async def observe(self) -> dict | None:
        """새로 수집된 정보와 사용자 피드백 확인"""
        context = {
            "current_time": self.now_str(),
            "new_articles_count": len(self._new_articles_buffer),
            "new_articles": self._new_articles_buffer[:20],  # 최신 20개
        }

        # 사용자 선호도 로드
        preferences = await self._load_preferences()
        context["user_preferences"] = preferences

        # 노션 액션아이템 확인
        if self.notion and self._notion_db_id:
            action_items = await self.notion.get_action_items(self._notion_db_id)
            context["action_items"] = [
                self._extract_notion_title(item) for item in action_items[:5]
            ]

        if context["new_articles_count"] == 0 and not context.get("action_items"):
            return None

        return context

    # ── Think: AI 판단 ─────────────────────────────────

    async def think(self, context: dict) -> dict | None:
        """정보의 관련성/가치를 판단하고 행동 결정"""

        if not context.get("new_articles"):
            # 액션아이템만 있는 경우
            if context.get("action_items"):
                return {
                    "action": "process_action_items",
                    "items": context["action_items"],
                }
            return None

        # AI에게 선별 요청
        articles_text = self._format_articles(context["new_articles"])
        prefs_text = json.dumps(context.get("user_preferences", {}), ensure_ascii=False)

        system_prompt = """당신은 정보 선별 전문가입니다.
수집된 뉴스/정보 목록을 분석하여 사용자에게 가치 있는 것을 선별합니다.

사용자 선호도를 참고하여 각 정보의 관련성 점수(0.0~1.0)를 매기고,
0.6 이상인 것만 선별합니다.

또한 현재 수집된 정보에서 부족한 영역이 있다면 추가 수집이 필요한 키워드를 제안합니다.

반드시 아래 JSON 형식으로만 응답하세요:
{
  "selected": [
    {"index": 0, "score": 0.85, "reason": "선별 이유", "summary": "한줄 요약"},
    ...
  ],
  "missing_topics": ["추가 수집 필요한 키워드1", "키워드2"],
  "briefing": "전체 브리핑 요약 (2-3문장)"
}"""

        user_prompt = f"""사용자 선호도:
{prefs_text}

수집된 정보 목록:
{articles_text}"""

        result_text = await self.ai_think(system_prompt, user_prompt)

        try:
            if "```json" in result_text:
                result_text = result_text.split("```json")[1].split("```")[0]
            elif "```" in result_text:
                result_text = result_text.split("```")[1].split("```")[0]
            result = json.loads(result_text.strip())
        except json.JSONDecodeError:
            logger.error(f"[curator] Failed to parse AI response: {result_text[:200]}")
            return None

        return {
            "action": "curate_and_brief",
            "selected": result.get("selected", []),
            "missing_topics": result.get("missing_topics", []),
            "briefing": result.get("briefing", ""),
            "articles": context["new_articles"],
        }

    # ── Act: 실행 ──────────────────────────────────────

    async def act(self, decision: dict):
        """선별 결과 저장 및 브리핑"""
        action = decision.get("action")

        if action == "curate_and_brief":
            await self._curate_and_brief(decision)

        elif action == "process_action_items":
            await self._process_action_items(decision.get("items", []))

    async def _curate_and_brief(self, decision: dict):
        """선별 → 노션 저장 → 슬랙 브리핑 → 추가 수집 요청"""
        general = "ai-agents-general"

        articles = decision.get("articles", [])
        selected = decision.get("selected", [])
        missing = decision.get("missing_topics", [])
        briefing = decision.get("briefing", "")

        logger.info(f"[curator] _curate_and_brief: {len(articles)} articles, {len(selected)} selected")

        try:
            await self.slack.send_message(
                general,
                f":brain: *[curator]* {len(articles)}건 중 {len(selected)}건을 선별했어요. 저장 중..."
            )
            logger.info("[curator] Sent brain message to general")
        except Exception as e:
            logger.error(f"[curator] Failed to send brain message: {e}")

        # 1. 선별된 항목 저장
        curated_count = 0
        for sel in selected:
            idx = sel.get("index", 0)
            if idx >= len(articles):
                continue

            article = articles[idx]
            score = sel.get("score", 0)
            summary = sel.get("summary", "")

            # Supabase에 선별 결과 저장
            try:
                await asyncio.to_thread(
                    lambda: self.supabase.table("curated_items").insert({
                        "relevance_score": score,
                        "ai_summary": summary,
                        "ai_reasoning": sel.get("reason", ""),
                    }).execute()
                )
                curated_count += 1
            except Exception as e:
                logger.error(f"[curator] Save curated item failed: {e}")

            # 노션에 저장
            if self.notion and self._notion_db_id:
                await self.notion.create_page(
                    self._notion_db_id,
                    properties={
                        "Name": NotionClient.prop_title(article.get("title", "")),
                        "Source": NotionClient.prop_select(article.get("source", "")),
                        "Score": NotionClient.prop_number(score),
                        "URL": NotionClient.prop_url(article.get("url", "")),
                        "Summary": NotionClient.prop_rich_text(summary),
                    },
                )

        # 2. 슬랙 브리핑
        if selected:
            brief_msg = f"*정보 브리핑* ({self.now_str()})\n\n"
            brief_msg += f"{briefing}\n\n"
            brief_msg += f"선별된 정보 {curated_count}건:\n"
            for sel in selected[:5]:
                idx = sel.get("index", 0)
                if idx < len(articles):
                    art = articles[idx]
                    brief_msg += f"- [{art.get('title', '')}]({art.get('url', '')}) "
                    brief_msg += f"(관련도: {sel.get('score', 0):.0%})\n"
                    brief_msg += f"  _{sel.get('summary', '')}_\n"
            logger.info(f"[curator] Sending briefing ({len(brief_msg)} chars) to {general}")
            await self.slack.send_message(general, brief_msg)
            logger.info("[curator] Briefing sent successfully")

        # 3. 부족한 영역 → 수집 에이전트에 추가 요청
        if missing:
            topics = ', '.join(missing[:3])
            await self.slack.send_message(
                general,
                f":speech_balloon: *[curator → collector]* 부족한 영역이 있어요. 추가 수집 요청: _{topics}_"
            )
            for keyword in missing[:3]:
                await self.ask_agent("collector", "collect_by_keyword", {"query": keyword})

        # 버퍼 비우기
        processed_count = len(articles)
        self._new_articles_buffer = self._new_articles_buffer[processed_count:]

    async def _process_action_items(self, items: list):
        """노션 액션아이템 처리"""
        for item in items:
            title = item if isinstance(item, str) else str(item)
            await self.say(f"액션아이템 처리 중: {title}")
            # AI가 액션아이템 해석 → 적절한 에이전트에 작업 할당
            decision = await self.ai_decide(
                context={"action_item": title},
                options=["collect_info", "analyze", "summarize", "delegate"],
            )
            if decision.get("action") == "collect_info":
                query = decision.get("details", {}).get("query", title)
                await self.ask_agent("collector", "collect_by_keyword", {"query": query})

    # ── 사용자 피드백 학습 ─────────────────────────────

    async def handle_reaction_feedback(self, reaction: str, message_data: dict):
        """슬랙 이모지 반응으로부터 피드백 학습"""
        score = 0
        if reaction in ("+1", "thumbsup", "heart", "star"):
            score = 1
        elif reaction in ("-1", "thumbsdown"):
            score = -1

        if score != 0:
            try:
                await asyncio.to_thread(
                    lambda: self.supabase.table("curation_preferences").insert({
                        "category": "reaction_feedback",
                        "keywords": [message_data.get("text", "")[:200]],
                        "weight": float(score),
                        "learned_from": "user_feedback",
                    }).execute()
                )
            except Exception as e:
                logger.error(f"[curator] Save feedback failed: {e}")

    # ── 외부 작업 수신 ─────────────────────────────────

    async def handle_external_task(self, task: TaskMessage) -> Any:
        """다른 에이전트의 선별 요청 처리"""
        if task.task_type == "curate_items":
            items = task.payload.get("items", [])
            self._new_articles_buffer.extend(items)
            return {"status": "queued", "count": len(items)}

        return await super().handle_external_task(task)

    # ── 유틸리티 ───────────────────────────────────────

    async def _load_preferences(self) -> dict:
        """Supabase에서 사용자 선호도 로드"""
        try:
            result = await asyncio.to_thread(
                lambda: self.supabase.table("curation_preferences").select("*").execute()
            )
            prefs = {}
            for row in result.data or []:
                cat = row.get("category", "general")
                if cat not in prefs:
                    prefs[cat] = []
                prefs[cat].append({
                    "keywords": row.get("keywords", []),
                    "weight": row.get("weight", 1.0),
                })
            return prefs
        except Exception:
            return {}

    def _format_articles(self, articles: list[dict]) -> str:
        """기사 목록을 텍스트로 포맷"""
        lines = []
        for i, art in enumerate(articles):
            lines.append(f"[{i}] {art.get('title', '제목없음')} ({art.get('source', '')})")
            if art.get("content"):
                lines.append(f"    {art['content'][:100]}")
            lines.append("")
        return "\n".join(lines)

    def _extract_notion_title(self, page: dict) -> str:
        """노션 페이지에서 제목 추출"""
        props = page.get("properties", {})
        for key in ("Name", "이름", "Title", "제목"):
            if key in props:
                title_arr = props[key].get("title", [])
                if title_arr:
                    return title_arr[0].get("plain_text", "")
        return ""
