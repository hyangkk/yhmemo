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
        self._current_query: str = ""
        self._request_thread_ts: str = None
        self._request_channel: str = None

        # 수집 에이전트의 new_articles 이벤트 구독
        self.bus.subscribe("new_articles", self._on_new_articles)

    def set_query_context(self, query: str, thread_ts: str = None, channel: str = None):
        """사용자 검색 키워드 컨텍스트 설정"""
        self._current_query = query
        self._request_thread_ts = thread_ts
        self._request_channel = channel

    async def _on_new_articles(self, task: TaskMessage):
        """수집 에이전트에서 새 정보 도착 시 → 즉시 선별"""
        items = task.payload.get("items", [])
        is_user_request = bool(task.payload.get("query"))
        self._new_articles_buffer.extend(items)
        logger.info(f"[curator] Received {len(items)} articles (user_request={is_user_request})")

        if not is_user_request:
            # 정기 수집은 버퍼만 쌓고 주기적 루프에서 처리
            return

        # 유저 요청 수집만 즉시 선별
        if len(self._new_articles_buffer) >= 5:
            logger.info(f"[curator] Curating {len(self._new_articles_buffer)} articles for user request")
            try:
                context = await self.observe()
                if context:
                    decision = await self.think(context)
                    if decision:
                        await self.act(decision)
            except Exception as e:
                logger.error(f"[curator] Curate error: {e}")

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
        query = self._current_query

        system_prompt = f"""당신은 정보 선별 전문가입니다.
수집된 뉴스/정보 목록을 분석하여 사용자에게 가치 있는 것을 선별합니다.

{"[중요] 사용자가 '" + query + "'에 대해 검색을 요청했습니다. 이 주제와 직접 관련된 기사만 선별하세요. 관련 없는 기사는 score를 0으로 주세요." if query else "사용자 선호도를 참고하여 선별합니다."}

각 정보의 관련성 점수(0.0~1.0)를 매기고, 0.6 이상인 것만 선별합니다.
최대 3건만 선별하세요 (정말 관련 높은 것만).

반드시 아래 JSON 형식으로만 응답하세요:
{{
  "selected": [
    {{"index": 0, "score": 0.85, "reason": "선별 이유 (15자 이내)", "summary": "핵심 한줄 요약 (30자 이내)"}}
  ],
  "rejected_reason": "선별에서 제외된 기사들의 공통적인 이유 (한줄)",
  "briefing": "전체 브리핑 한줄 요약"
}}"""

        user_prompt = f"""{"검색 키워드: " + query if query else ""}
사용자 선호도: {prefs_text}

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

        decision = {
            "action": "curate_and_brief",
            "selected": result.get("selected", []),
            "missing_topics": result.get("missing_topics", []),
            "briefing": result.get("briefing", ""),
            "rejected_reason": result.get("rejected_reason", ""),
            "articles": context["new_articles"],
            "query": query,
        }
        # 유저 요청 컨텍스트가 있으면 전달
        if query and getattr(self, "_request_thread_ts", None):
            decision["thread_ts"] = self._request_thread_ts
            decision["channel"] = self._request_channel or "ai-agents-general"
        return decision

    # ── Act: 실행 ──────────────────────────────────────

    async def act(self, decision: dict):
        """선별 결과 저장 및 브리핑"""
        action = decision.get("action")

        if action == "curate_and_brief":
            await self._curate_and_brief(decision)

        elif action == "process_action_items":
            await self._process_action_items(decision.get("items", []))

    async def _curate_and_brief(self, decision: dict):
        """선별 → 노션 저장 → 슬랙 브리핑"""
        query = decision.get("query", "")
        thread_ts = decision.get("thread_ts")  # 유저 요청 시 스레드 ts
        # 유저 요청이면 지정 채널(or general), 자율이면 ai-curator
        general = decision.get("channel", "ai-agents-general") if query else "ai-curator"

        articles = decision.get("articles", [])
        selected = decision.get("selected", [])
        briefing = decision.get("briefing", "")
        rejected_reason = decision.get("rejected_reason", "")

        logger.info(f"[curator] _curate_and_brief: {len(articles)} articles, {len(selected)} selected")

        # ── 1. 선별 과정 (스레드에만, 간결하게) ──
        if not selected:
            if thread_ts:
                await self._reply(general, f"{len(articles)}건 분석했지만 관련 기사가 없어요.", thread_ts)
            self._current_query = ""
            self._request_thread_ts = None
            self._request_channel = None
            processed_count = len(articles)
            self._new_articles_buffer = self._new_articles_buffer[processed_count:]
            return

        # ── 2. 노션에 상세 저장 + URL 수집 ──
        notion_urls = []
        for sel in selected:
            idx = sel.get("index", 0)
            if idx >= len(articles):
                continue

            article = articles[idx]
            score = sel.get("score", 0)
            summary = sel.get("summary", "")

            # Supabase
            try:
                await asyncio.to_thread(
                    lambda: self.supabase.table("curated_items").insert({
                        "relevance_score": score,
                        "ai_summary": summary,
                        "ai_reasoning": sel.get("reason", ""),
                    }).execute()
                )
            except Exception as e:
                logger.error(f"[curator] Save curated item failed: {e}")

            # 노션에 상세 저장 (본문 포함)
            notion_url = None
            if self.notion and self._notion_db_id:
                content_blocks = [
                    NotionClient.block_paragraph(f"요약: {summary}"),
                    NotionClient.block_paragraph(f"선별 이유: {sel.get('reason', '')}"),
                    NotionClient.block_paragraph(f"원문: {article.get('url', '')}"),
                ]
                if article.get("content"):
                    content_blocks.append(
                        NotionClient.block_paragraph(f"본문:\n{article['content'][:1500]}")
                    )
                result = await self.notion.create_page(
                    self._notion_db_id,
                    properties={
                        "Name": NotionClient.prop_title(article.get("title", "")),
                        "Source": NotionClient.prop_select(article.get("source", "")),
                        "Score": NotionClient.prop_number(score),
                        "URL": NotionClient.prop_url(article.get("url", "")),
                        "Summary": NotionClient.prop_rich_text(summary),
                    },
                    content_blocks=content_blocks,
                )
                if result:
                    notion_url = result.get("url")

            notion_urls.append(notion_url)

        # ── 3. 슬랙 브리핑 (깔끔한 포맷) ──
        lines = []
        if thread_ts and query:
            lines.append(f"> {query}\n")
        lines.append(f"*{briefing}*\n")

        for i, sel in enumerate(selected[:3]):
            idx = sel.get("index", 0)
            if idx >= len(articles):
                continue
            art = articles[idx]
            title = art.get("title", "제목없음")
            url = art.get("url", "")
            summary = sel.get("summary", "")

            line = f"• <{url}|{title}>"
            if i < len(notion_urls) and notion_urls[i]:
                line += f"  (<{notion_urls[i]}|노션>)"
            lines.append(line)
            if summary:
                lines.append(f"  _{summary}_")

        brief_msg = "\n".join(lines)

        if thread_ts:
            # 스레드에 달고, 채널에도 표시
            await self._reply(general, brief_msg, thread_ts, broadcast=True)
        else:
            await self._reply(general, brief_msg)
        logger.info("[curator] Briefing sent successfully")

        # 버퍼 비우기 & 컨텍스트 초기화
        self._current_query = ""
        self._request_thread_ts = None
        self._request_channel = None
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
