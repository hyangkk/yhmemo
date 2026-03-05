"""
정보 수집 에이전트 (Collector Agent)

역할:
- 뉴스, 사업공고, 채용정보 등 다양한 소스에서 정보 수집
- 주기적 자율 수집 + 다른 에이전트 요청에 따른 맞춤 수집
- 수집 결과를 Supabase에 저장하고 슬랙으로 알림

자율 행동:
- Observe: 등록된 소스에 새 정보가 있는지 확인
- Think: 어떤 소스를 크롤링할지, 어떤 주제를 집중할지 판단
- Act: 수집 → 저장 → 알림 → 선별 에이전트에 전달
"""

import asyncio
import hashlib
import logging
from datetime import datetime, timezone, timedelta
from typing import Any

import feedparser
import httpx

from core.base_agent import BaseAgent
from core.message_bus import TaskMessage

logger = logging.getLogger(__name__)

# ── 수집 소스 정의 ────────────────────────────────────

RSS_SOURCES = {
    # 종합 뉴스
    "구글뉴스": "https://news.google.com/rss?hl=ko&gl=KR&ceid=KR:ko",
    "구글뉴스_경제": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx6TVdZU0FtdHZHZ0pMVWlnQVAB?hl=ko&gl=KR&ceid=KR:ko",
    "구글뉴스_IT": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGd3TVRBU0FtdHZHZ0pMVWlnQVAB?hl=ko&gl=KR&ceid=KR:ko",
    "연합뉴스": "https://www.yna.co.kr/RSS/news.xml",
    "한국경제": "https://www.hankyung.com/feed/all-news",
    # 스타트업/사업공고
    "케이스타트업": "https://www.k-startup.go.kr/web/contents/rss/startupnews.do",
}

# 키워드별 구글뉴스 검색 URL 패턴
GOOGLE_NEWS_SEARCH = "https://news.google.com/rss/search?q={query}&hl=ko&gl=KR&ceid=KR:ko"


class CollectorAgent(BaseAgent):
    """정보 수집 에이전트"""

    def __init__(self, **kwargs):
        super().__init__(
            name="collector",
            description="뉴스, 사업공고, 채용정보 등 다양한 소스에서 정보를 수집하는 에이전트",
            slack_channel="ai-collector",
            loop_interval=600,  # 10분 간격
            **kwargs,
        )
        self._http = httpx.AsyncClient(timeout=15.0, follow_redirects=True)
        self._pending_requests: list[dict] = []  # 다른 에이전트의 수집 요청

    # ── Observe: 환경 감지 ─────────────────────────────

    async def observe(self) -> dict | None:
        """새로운 정보가 있는지 소스들을 확인"""
        context = {
            "current_time": self.now_str(),
            "pending_requests": self._pending_requests.copy(),
            "sources_available": list(RSS_SOURCES.keys()),
        }

        # 다른 에이전트의 요청이 있으면 우선 처리
        if self._pending_requests:
            context["priority"] = "requested_collection"
            return context

        # 주기적 수집 시간인지 확인
        context["priority"] = "routine_collection"
        return context

    # ── Think: AI 판단 ─────────────────────────────────

    async def think(self, context: dict) -> dict | None:
        """어떤 소스에서 어떤 정보를 수집할지 판단"""

        # 요청된 수집이 있으면 바로 처리
        if context.get("priority") == "requested_collection":
            requests = self._pending_requests.copy()
            self._pending_requests.clear()
            return {
                "action": "targeted_collection",
                "requests": requests,
            }

        # 루틴 수집: AI가 어떤 소스를 수집할지 판단
        decision = await self.ai_decide(
            context={
                "현재시각": context["current_time"],
                "사용가능_소스": context["sources_available"],
                "상황": "정기 수집 시간입니다. 어떤 소스들을 수집할까요?",
            },
            options=["collect_all", "collect_priority", "skip"],
        )

        if decision.get("action") == "skip":
            return None

        return {
            "action": "routine_collection",
            "sources": decision.get("details", {}).get("sources", list(RSS_SOURCES.keys())),
        }

    # ── Act: 실행 ──────────────────────────────────────

    async def act(self, decision: dict):
        """수집 실행"""
        action = decision.get("action")

        if action == "targeted_collection":
            for req in decision.get("requests", []):
                await self._collect_by_keyword(req.get("query", ""), req.get("requester", "unknown"))

        elif action == "routine_collection":
            sources = decision.get("sources", list(RSS_SOURCES.keys()))
            await self._collect_from_rss(sources)

    async def _collect_from_rss(self, source_names: list[str]):
        """RSS 소스에서 정보 수집 (자율 작업 → 로그 채널)"""
        log_channel = "ai-agent-logs"
        all_items = []

        for name in source_names:
            url = RSS_SOURCES.get(name)
            if not url:
                continue
            try:
                items = await self._fetch_rss(name, url)
                all_items.extend(items)
            except Exception as e:
                logger.error(f"RSS fetch failed for {name}: {e}")

        if all_items:
            saved = await self._save_items(all_items)
            if saved:
                sources = ', '.join(list({item["source"] for item in saved})[:3])
                await self.slack.send_message(
                    log_channel,
                    f":satellite: *[collector]* 정기 수집 완료 — *{len(saved)}건* (출처: {sources})"
                )
                await self.broadcast_event("new_articles", {
                    "count": len(saved),
                    "sources": list({item["source"] for item in saved}),
                    "items": saved[:10],
                })

    async def _collect_by_keyword(self, query: str, requester: str, thread_ts: str = None):
        """키워드 기반 맞춤 수집 — 과정 메시지 없이 결과만 전달"""
        general = "ai-agents-general"

        url = GOOGLE_NEWS_SEARCH.format(query=query)
        items = await self._fetch_rss(f"검색:{query}", url)

        if not items:
            await self._reply(general, f"'{query}' 관련 결과를 찾지 못했어요.", thread_ts)
            return

        saved = await self._save_items(items)

        if saved:
            await self.broadcast_event("new_articles", {
                "count": len(saved),
                "query": query,
                "requester": requester,
                "items": saved,
            })
        else:
            await self._reply(general, f"'{query}' — 새로운 정보가 없어요 (이미 수집됨).", thread_ts)

    async def _fetch_rss(self, source_name: str, url: str) -> list[dict]:
        """RSS 피드에서 항목 추출"""
        try:
            resp = await self._http.get(url)
            feed = feedparser.parse(resp.text)
        except Exception as e:
            logger.error(f"RSS fetch error ({source_name}): {e}")
            return []

        items = []
        for entry in feed.entries[:20]:
            title = entry.get("title", "").strip()
            link = entry.get("link", "")
            published = entry.get("published", "")
            summary = entry.get("summary", "")[:500]

            if not title:
                continue

            content_hash = hashlib.sha256(f"{title}{link}".encode()).hexdigest()[:16]

            items.append({
                "source": source_name,
                "source_type": "rss",
                "title": title,
                "url": link,
                "content": summary,
                "metadata": {"published": published},
                "hash": content_hash,
            })

        return items

    async def _save_items(self, items: list[dict]) -> list[dict]:
        """Supabase에 수집 항목 저장 (중복 제외)"""
        def _sync_save():
            saved = []
            for item in items:
                try:
                    result = self.supabase.table("collected_items").upsert(
                        item, on_conflict="hash"
                    ).execute()
                    if result.data:
                        saved.append(item)
                except Exception as e:
                    if "duplicate" not in str(e).lower():
                        logger.error(f"Save item failed: {e}")
            return saved
        # 동기 Supabase 호출을 스레드에서 실행 (이벤트 루프 블로킹 방지)
        return await asyncio.to_thread(_sync_save)

    # ── 외부 작업 수신 (다른 에이전트로부터) ───────────

    async def handle_external_task(self, task: TaskMessage) -> Any:
        """다른 에이전트의 수집 요청 처리"""
        if task.task_type == "collect_by_keyword":
            query = task.payload.get("query", "")
            self._pending_requests.append({
                "query": query,
                "requester": task.from_agent,
            })
            return {"status": "queued", "query": query}

        elif task.task_type == "collect_from_source":
            sources = task.payload.get("sources", [])
            await self._collect_from_rss(sources)
            return {"status": "completed", "sources": sources}

        return await super().handle_external_task(task)
